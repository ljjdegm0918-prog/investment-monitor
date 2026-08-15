# 添加公司加速 — 行为、验收与生产清单

> 本轮（分支 `fix/add-company-async-speed`，基底 `ai功能测试` tip `d55270d`）只做「让添加公司变快、前端有反馈」，**不改变任何 source connector 的接口契约**。
> 本文档是行为记录 + 验收脚本 + 现网对齐检查 + 生产优化清单（只列清单，不写部署代码）。

---

## 1. 行为变更

### 1.1 `POST /api/companies/batch` 秒回（新基底：多市场）

- 入参格式（新基底已支持混合市场）：`{ "tickers": "AAPL 00700@HK", "lists": ["<slug>"] }`。
  - `market` 参数可省略，默认 `us`；`TICKER@MARKET` 语法由 `parse_company_inputs` / `group_by_market` 解析。
- 返回仍为 201，保留原有 `added` / `already_present` / `failed` / `parsed` / `groups`，并新增：

```json
{
  "added": [{"ticker": "00700", "market": "hk", "name": "TENCENT", "..."}],
  "already_present": [],
  "failed": [],
  "collection": null,
  "backfill_task_id": "bf-<uuid4>",
  "backfill_status": "queued"
}
```

- `collection` 恒为 `null`（回填不再同步阻塞在 HTTP 线程里）。
- 若本次没有 ticker 被成功添加（`added` 为空），`backfill_task_id` 为 `null`、`backfill_status` 为 `"completed"`。
- **HTTP 处理线程里禁止调用 `collect_tickers` / `pipeline.collect`**；公司落库后立即启动一个 `daemon=True` 的 `threading.Thread` 跑后台回填，再返回。启动线程本身是瞬时的。

### 1.2 后台回填（方案 A：一次请求一个任务）

- 新增方法 `_run_add_company_backfill(task_id, markets_map, default_market)`，其中 `markets_map = {ticker: market}`（只含本次 added 的记录）：
  1. 先把任务置 `running`、写入 `started_at`（UTC ISO 时间）与 `sources`；
  2. `lookback_days` 读环境变量 `ADD_COMPANY_BACKFILL_DAYS`，默认 **30**，范围 1~3650；
  3. 用 `_add_company_backfill_sources(market)`（见 §2）作为每个市场的回填源列表；
  4. 按市场分组、逐 source 调用 `collect_tickers(tickers_for_market, lookback_days=..., markets={t: market}, sources=(source,), initial_backfill=True)`，用 `_combine_collection_summaries` 汇总；
  5. 终态：`success`（整体无失败）/ `partial`（有失败且有成功或 partial）/ `failure`（全部失败）；写 `finished_at`、`error`（失败原因汇总，JSON 安全字符串）、`summary`（汇总结果，JSON 安全）。
- 任务字段：`id` / `status` / `tickers` / `market`（默认市场，缺省 `us`）/ **`markets`（`{ticker: market}` 映射，JSON 字典）** / `sources`（各市场 `_add_company_backfill_sources` 的并集，保序去重）/ `started_at` / `finished_at` / `error` / `summary`。
- 线程内异常必须捕获并写入 `error`，任务一定落到终态，不会留下 `running` 卡死。
- 任务登记在内存 `self._backfill_tasks` + `self._backfill_tasks_lock`（`threading.Lock`）；**进程重启任务丢失，这是可接受的**（不做持久化）。

### 1.3 `GET /api/backfill-tasks/<task_id>`

只读查询接口，返回：

```json
{
  "id": "bf-...",
  "status": "queued|running|success|partial|failure",
  "tickers": ["AAPL", "00700"],
  "market": "us",
  "markets": {"AAPL": "us", "00700": "hk"},
  "sources": ["sec", "hkexnews", "yahoo_hk"],
  "started_at": "2026-... (UTC ISO) | null",
  "finished_at": "... | null",
  "error": null,
  "summary": {"status": "...", "records_fetched": 0, "inserted": 0, "updated": 0, "..."}
}
```

- 未知 `task_id` → 404 + `{ "error": "Backfill task not found" }`。

### 1.4 前端乐观 UI + 2s 轮询（i18n 版）

`src/investment_monitor/web_static/app.js`（新基底已支持 TICKER@MARKET 输入、无 market 下拉、`t()` 双语文案）：

- `addTickerDirect(event)`：
  1. 先 `event.preventDefault()`，再取 `button`；若 `button.disabled` 直接 return（防双提交）；
  2. 校验通过后立即 `button.disabled = true` + `toast(t("manage.adding_company"))`；
  3. `await POST /api/companies/batch`（入参保持新基底格式：`tickers` / `lists`，支持 `TICKER@MARKET`）；
  4. 成功后：失败项沿用红色 toast；再 `toast(t("manage.added_collecting_background", {items}))`（仅 added 非空时）；
  5. 立刻 `await reloadBootstrap()` + `await refreshManagement()`（不等待轮询）；
  6. 若 `result.backfill_task_id` 存在，`await pollBackfill(taskId)`；
  7. `catch` toast 错误，`finally` 恢复 `button.disabled = false`。
- `pollBackfill(taskId)`：每 2 秒 `GET /api/backfill-tasks/{id}`：
  - `success` → `toast(t("manage.collection_complete"))`；
  - `partial` → 红色 `toast(t("manage.collection_partial", {error}), true)`；
  - `failure` → 红色 `toast(t("manage.collection_failed", {error}), true)`；
  - 连续请求失败 3 次（约 6s）自动停止（`setTimeout` 递归，无 `setInterval` 泄漏）。
- 新增 i18n 键（en/zh 各 5 个）：`manage.adding_company`、`manage.added_collecting_background`、`manage.collection_complete`、`manage.collection_partial`、`manage.collection_failed`。
- 最小样式：`.button:disabled { opacity:.55; cursor:not-allowed; }`。

---

## 2. 源过滤（add-company 回填专用）

`_add_company_backfill_sources(market) -> Tuple[str, ...]`（`web.py`），从 `self._relevant_sources(market)` 出发（保持 `enabled_sources` 原有顺序），然后：

1. **永远排除**（注册 stub，`collect()` 恒返回空，跳过避免空转占队列）：

```text
hotcopper_au, lse_share_chat, yellowbrick, vic, x_community
```

2. **xueqiu 保留但排后**：只有配置了可选 cookie 时才是 LIVE，否则 connector 空跑；强制放在末尾（`ADD_COMPANY_BACKFILL_COMMUNITY_TAIL = {"xueqiu"}`）。
3. **LIVE community 排 filings/news 之后**：分类依据是 settings 里每个 source 的 `source_type`；`source_type == "community"` 的源放后段，`filings`/`disclosure`/`news`/其它放前段。
4. 无 `source_type` 或归属不清的源默认视为非 community（放前段），**不凭名字猜测**。

以 `market=hk` 为例（settings 启用 hkexnews / yahoo_hk / google_news_hk / xueqiu 时），回填顺序为：

```text
hkexnews, yahoo_hk, google_news_hk, xueqiu
```

多市场一次添加（如 `AAPL 00700@HK`）时，任务的 `sources` 是各市场过滤结果的并集，保序去重。

---

## 3. Timeout、熔断与 stub 处理

### 3.1 RSS timeout 8s（全部市场）

- 所有 Yahoo / Google News key-free RSS 客户端默认 timeout 从 **20.0s → 8.0s**。
- 范围：`src/investment_monitor/sources/*/yahoo/client.py`（19 个）+ `src/investment_monitor/sources/*/google/client.py`（23 个），共 **42 个文件**。
- 每个文件改两处，且 **env 覆盖键名原样保留**：
  - 构造器 `timeout: float = 20.0` → `8.0`；
  - `_read_float_environment("<SOURCE>_TIMEOUT_SECONDS", 20.0)` → `8.0`。
- 例（HK）：`GOOGLE_HK_NEWS_TIMEOUT_SECONDS`、`YAHOO_HK_NEWS_TIMEOUT_SECONDS` 默认均为 `8.0`。

### 3.2 per-source 熔断（circuit breaker）

`src/investment_monitor/pipeline.py`：

- 环境变量 `COLLECTION_CIRCUIT_BREAKER_THRESHOLD`，默认 **2**（`max(1, int(raw))`）。
- `_SourceCircuitBreaker`：同一 connector 在同一轮 `collect()` 里**连续失败**（`status == failure` 的 ticker 尝试，含 timeout/请求异常）达到阈值 → 本轮跳过该源剩余 ticker。
- 跳过时记录：
  - `CollectionFailure`，`message` 含 `circuit_open`；
  - `CollectionEvent`，`status=failure`，`error_message` 含 `circuit_open`；
  - 最终 summary 呈现 `partial`。
- 一次成功（或非失败）尝试即重置该源连续失败计数。
- 只作用于 per-ticker 循环，**不改变 `source_wide_collection` 分支语义**，不修改 `connector.collect()` 签名与 `InformationItem` 语义，不永久禁用源。

### 3.3 未配置 cookie 的 stub 按 informational empty（xueqiu）

- `src/investment_monitor/sources/xueqiu/connector.py`（最小改动，不改 `collect()` 签名 / `InformationItem` 语义）：
  - `__init__` 增加 `self._live_path_attempted = False`；
  - 新增只读 property `live_path_attempted`；
  - 补齐 `last_collection_status` property（返回 `self._status`，无 cookie 时 `"stub"`，cookie 成功时 `"LIVE(cookie)"`）；
  - `_fetch_via_cookie` 中：cookie 非空、真正 `urlopen` 之前置 `live_path_attempted = True`（空 cookie 提前 return 不置 True）。
- `pipeline.py` per-ticker 分类：`status_hint == "stub"` 且 `live_path_attempted is False` → `event_status="empty"`，**不进 failures**；stub 说明仍随 `CollectionEvent.error_message` 写入 activity（INFO 日志，`treated_as=empty`）。
- `status_hint == "stub"` 且 `live_path_attempted is True`（配置了 cookie 但 HTTP 尝试失败）→ 仍走原 `connector_error` 分支，如实 `failure`。
- 不把 stub 伪装成 LIVE；stub-empty 不算失败、不触发 §3.2 熔断计数。

---

## 4. 验收脚本

> 服务默认地址 `http://127.0.0.1:8765`（`PYTHONPATH=src python -m investment_monitor.web --host 127.0.0.1 --port 8765`）。
> 前提：先创建一个列表（`POST /api/lists`），拿到 `slug` 再添加公司。

### 4.1 验收要点

1. 添加腾讯 `00700@HK`（或混合 `AAPL 00700@HK`）：**POST 必须在 3 秒内返回**，且返回体带 `backfill_task_id`（`bf-` 前缀）、`backfill_status == "queued"`、`collection == null`。
2. `GET /api/backfill-tasks/<id>` 能查到任务，字段齐全（含 `markets` 映射），并最终落到 `success` / `partial` / `failure` 之一。
3. 前端：点击后按钮立即禁用、出现「Adding…」toast、列表刷新、随后出现后台采集 toast（成功/部分/失败）。
4. 熔断场景：若 Google News HK 超时（8s）触发同源连续失败 2 次，任务应 `partial`，且 HKEXnews / Yahoo HK 仍可能带回数据（不被 Google 拖垮）。

### 4.2 curl 示例（PowerShell）

```powershell
# 1) 建列表
curl.exe -s -X POST http://127.0.0.1:8765/api/lists `
  -H "Content-Type: application/json" `
  -d '{\"name\":\"acceptance\"}'
# 记下返回里的 slug，例如 "acceptance"

# 2) 添加 00700@HK（计时）
Measure-Command {
  curl.exe -s -X POST http://127.0.0.1:8765/api/companies/batch `
    -H "Content-Type: application/json" `
    -d '{\"tickers\":\"00700@HK\",\"lists\":[\"acceptance\"]}'
}
# 期望：TotalSeconds < 3；返回体含 "backfill_task_id": "bf-..."

# 3) 轮询任务
curl.exe -s http://127.0.0.1:8765/api/backfill-tasks/bf-<uuid>
# 期望：status 最终为 success/partial/failure；markets 含 {"00700":"hk"}
```

### 4.3 Python 示例（stdlib，无第三方依赖）

```python
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"

def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def get(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read())

# 1) 建列表
lst = post("/api/lists", {"name": "acceptance"})
slug = lst["list"]["slug"]

# 2) 添加混合市场（00700@HK 默认市场为 us），断言 < 3s 且带 backfill_task_id
t0 = time.monotonic()
batch = post("/api/companies/batch", {"tickers": "AAPL 00700@HK", "lists": [slug]})
elapsed = time.monotonic() - t0
assert elapsed < 3.0, f"batch took {elapsed:.2f}s"
assert isinstance(batch.get("backfill_task_id"), str) and batch["backfill_task_id"].startswith("bf-")
assert batch.get("backfill_status") == "queued"
assert batch.get("collection") is None
print(f"batch returned in {elapsed:.2f}s, task={batch['backfill_task_id']}")

# 3) 轮询到终态
task_id = batch["backfill_task_id"]
terminal = {"success", "partial", "failure"}
for _ in range(60):  # 最多 2 分钟
    task = get(f"/api/backfill-tasks/{task_id}")
    assert task["market"] == "us"
    assert task["markets"] == {"AAPL": "us", "00700": "hk"}
    if task["status"] in terminal:
        print("terminal:", task["status"], "error:", task["error"])
        print("summary:", task["summary"])
        break
    time.sleep(2)
else:
    raise SystemExit(f"task {task_id} did not reach terminal state")
```

> 真实外网回填耗时取决于源可达性；上面轮询给足 2 分钟即可，验收只需确认「秒回 + task 可查（含 markets）+ 终态」三件事。

---

## 5. 现网对齐（确认跑的是含本修复的 tip）

在部署目录执行：

```powershell
cd "C:\Users\seteiro\Documents\Codex\2026-08-05\investment-monitor-p0-ai-holdings-planned\investment-monitor-x"
git rev-parse HEAD
git log --oneline -7
```

- 预期 `git rev-parse HEAD` = **`ac43432`**（M2 源过滤，当前 tip）。
- 本分支 `fix/add-company-async-speed` 基于 `ai功能测试` 的 tip `d55270d` 切出，其上依次是 5 个提交：

| commit | message |
|---|---|
| `998935c` | fix(web): optimistic add-company UI with backfill polling |
| `2f365ba` | fix(sources): shorten RSS timeouts and add per-source circuit breaker |
| `a1b8f95` | fix(pipeline): treat unconfigured stub sources as informational empty |
| `4d27ff6` | feat(web): return add-company batch before backfill runs |
| `ac43432` | fix(web): skip stub community sources on add-company backfill |

- 若现网 `git rev-parse HEAD` 与上面不一致，说明跑的不是本修复的 tip，先 `git log --oneline -7` 核对再上线。
- 新基底全量测试基线：`1710 passed, 2 skipped, 0 failed`（`ai功能测试` d55270d）；M1 后 `1718 passed`；M2 后 `1721 passed`，均 `0 failed`。

---

## 6. 生产清单（只文档 — 本轮不写代码）

以下为上线前需要另行处理的生产项，**本分支一律不做**，仅列清单：

| 项 | 状态 | 说明 |
|---|---|---|
| 正式域名 | 不在本轮 | 现网用正式域名替换 `127.0.0.1` / IP |
| HTTPS 证书 | 不在本轮 | 配置 TLS 证书（如 Let's Encrypt / 云厂商证书），强制 302 跳 https |
| gzip / brotli | 不在本轮 | 对 JSON 与静态资源开启压缩 |
| 静态资源长缓存 | 不在本轮 | `web_static` 的 app.js/app.css 带内容 hash + `Cache-Control: max-age` |
| 生产 CDN | 不在本轮 | 静态资源走 CDN，减轻源站压力 |
| SQLite 备份 | 不在本轮 | 定时备份 `investment_monitor.sqlite3`（及 WAL），防止单文件损坏 |
| 进程守护 / 日志轮转 | 不在本轮 | 容器 + 日志轮转 |
| 速率限制 / 鉴权 | 不在本轮 | 生产环境对写接口加认证与限流 |
| 后台任务持久化 | 不在本轮 | 当前 backfill 任务在内存，重启丢失；如需跨重启可再评估 |

---

## 7. 已知边界

- 本分支 5 个 commit 未改动 `settings.yaml` 的源 `name`，未把 stub 源改成假 LIVE，未引入第三方运行时依赖（纯 stdlib）。
- xueqiu 的 stub-empty 分支只对提供 `last_collection_status == "stub"` 的 connector 生效（当前仅 xueqiu）；其它 stub 源（hotcopper_au 等）在 add-company 回填里已被 §2 过滤。
- 本文档不含任何密钥 / Token。
