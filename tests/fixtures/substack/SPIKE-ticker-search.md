# Spike: Substack ticker/search 公开表面探测（2026-08-11）

## Question

能否在不登录、不破解付费墙的前提下，按 **US ticker**（如 NVDA / AAPL / TSLA）
在 Substack 公开内容中做过滤/检索，绑定「ticker → 当日 Substack 内容」？

## Method

`stdlib urllib` only，Chrome UA，无 cookie，无 Selenium/Playwright，无新 pip。
探测日 2026-08-11。探测六类表面：

- 全局搜索页（`substack.com/search?q=<TICKER>`）
- 搜索 API（`/api/v1/search`、`/api/v2/search`、`/api/search`）
- Tag 页（`substack.com/tag/<ticker>`）
- Topic / Category / Discover 页（`/discover`、`/topics`、`/discover/finance` 等）
- 出版物内搜索 / Tag（`noahpinion.substack.com/search?q=<TICKER>`、`/tag/<ticker>`）
- 按日期过滤（`/archive`、`/archive/YYYY/MM/DD`、archive JSON 参数）

## Evidence

### 1. 全局搜索页

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://substack.com/search?q=NVDA` | **200** | 含付费墙提示文案（SPA shell） | 客户端渲染，HTML 无搜索结果；body ~79KB 为 JS 壳，无稳定字段 |

结论：搜索页返回 200 但**服务端不渲染结果**，纯客户端 SPA，urllib 无法提取内容。

### 2. 搜索 API

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://substack.com/api/v1/search?q=NVDA&limit=5` | **404** | — | 不存在 |
| `GET https://substack.com/api/v2/search?q=NVDA&limit=5` | **404** | — | 不存在 |
| `GET https://substack.com/api/search?q=NVDA&limit=5` | **404** | — | 不存在 |
| （AAPL / TSLA 同上，均 404） | — | — | — |

结论：**Substack 无公开搜索 API**。所有搜索端点均 404。

### 3. Tag 页

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://substack.com/tag/nvda` | **404** | — | 不存在 |
| `GET https://substack.com/tag/aapl` | **404** | — | 不存在 |
| `GET https://substack.com/tag/tsla` | **404** | — | 不存在 |

结论：**Substack 无 ticker tag 体系**。所有 ticker tag 页均 404。

### 4. Topic / Category / Discover 页

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://substack.com/discover` | **200** | SPA shell | 客户端渲染，无 ticker 过滤 |
| `GET https://substack.com/browse` | **200** | SPA shell | 同上 |
| `GET https://substack.com/topics` | **200** | SPA shell | 同上 |
| `GET https://substack.com/discover/finance` | **404** | — | 不存在 |
| `GET https://substack.com/discover/investing` | **404** | — | 不存在 |
| `GET https://substack.com/discover/stocks` | **404** | — | 不存在 |

结论：Discover 类页面均为 SPA 壳，无服务端 ticker 过滤；子分类路径均 404。

### 5. 出版物内搜索 / Tag 页（noahpinion.substack.com）

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://noahpinion.substack.com/search?q=NVDA` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/search?q=AAPL` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/search?q=TSLA` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/tag/nvda` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/tag/aapl` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/tag/tsla` | **404** | — | 不存在 |

结论：出版物内搜索和 tag 均 404，**无出版物内 ticker 检索**。

### 6. 按日期过滤能力

| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |
|---|---|---|---|
| `GET https://noahpinion.substack.com/archive` | **200** | SPA shell | 客户端渲染，urllib 无法提取 |
| `GET https://noahpinion.substack.com/archive/2026/08/11` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/archive/2026-08-11` | **404** | — | 不存在 |
| `GET https://noahpinion.substack.com/api/v1/archive?sort=new&limit=5&start=2026-08-11` | **200** | 无登录 | ✅ 返回 5 条最新（id=210685540, date=2026-08-11T08:01:13），但 `start` 参数实际为**游标分页**而非日期过滤，返回的仍是最新 N 条 |
| `GET https://noahpinion.substack.com/api/v1/archive?sort=new&limit=5&year=2026&month=8` | **200** | 无登录 | 同上，`year`/`month` 参数无效，仍返回最新 5 条 |

结论：archive JSON API 支持**游标分页**（offset），但**不支持按日期精确过滤**，更不支持 ticker 过滤。

## 诚实回答：能否按 ticker 过滤？

**不能。** Substack 在公开面上**完全没有 ticker 过滤/检索能力**：

1. **无公开搜索 API** — 所有搜索端点 404。
2. **无 ticker tag 体系** — 所有 ticker tag 页 404。
3. **无 topic/category 过滤** — discover 页为 SPA 壳，子分类 404。
4. **无出版物内搜索** — 出版物内 `/search` 和 `/tag` 均 404。
5. **archive JSON 仅支持游标分页** — 无日期/ticker 过滤参数。

## 唯一可行的公开面：publication-whitelist-only

结合 `SPIKE-pub-rss.md`（温知夏，commit bb18b23）的结论，Substack 唯一稳定的公开采集面是**出版物级**：

- `/feed`（RSS 2.0）：guid / title / link / pubDate — 公开无登录
- `/api/v1/archive?sort=new&limit=N`：id / post_date / title / canonical_url — 公开无登录

这意味着只能做 **publication-whitelist-only** 接入：
- 预先选定一批"可能讨论目标 ticker"的 Substack 刊物
- 轮询其 RSS / archive JSON
- 在**客户端**做 ticker 关键词匹配（标题/正文含 "NVDA" / "NVIDIA" 等）

**无法**做「给定 ticker → 检索所有 Substack 相关内容」的查询。

## Conclusion

**STOP（ticker 过滤）** — Substack 公开面无任何 ticker 检索/过滤接口。

**LIVE（publication-whitelist-only）** — 仅可作为「刊物白名单 + 客户端 ticker 关键词匹配」的间接方案：

1. 维护一份与目标 ticker 相关的 Substack 刊物白名单。
2. 通过 `/feed` 或 `/api/v1/archive` 轮询白名单刊物的公开元数据。
3. 在客户端按 ticker / 公司名做关键词过滤。

**代价**：覆盖率依赖白名单质量；关键词匹配有误报/漏报（如 "Apple" 可指水果）；无法保证"给定 ticker → 当日全部 Substack 内容"的查全率。

## Probe Script

见 `probe_ticker_search.py`（stdlib urllib only，可复现）。
