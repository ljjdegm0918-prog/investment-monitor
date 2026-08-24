# 第五批 CH/JP 股票与 ETF 覆盖实施报告

日期：2026-08-24
Branch：`ai功能测试`

## 1. 结果摘要

| 地区/项目 | 修改前 | 修改后 | 仍然缺少 | 状态 |
|---|---|---|---|---|
| CH 股票 universe | 无可运行目录，`stub` | SIX SA 224 行（223 股份/参与证书 + 1 认购权）+ Foreign Shares 36；全分页、交易线身份、SecType 和板块校验 | Sponsored shares、非 SIX 瑞士场所、历史退市 | `partial` |
| CH ETF universe | `unavailable` | SIX ETF Explorer 2,285 条交易线；保留同 ISIN 的多币种交易线 | 其他场所 ETF、历史退市、商业 SLA/再分发权 | `live`（仅 SIX 交易所范围） |
| CH 公司公告 | EQS 补充，`partial` | 未改变公告来源，利用新 universe 可改善 ticker/ISIN/name 解析 | SIX Exchange Regulation／FINMA 完整官方公告主链 | `partial` |
| JP 股票 universe | `unavailable` | JPX 官方前月末 XLS：3,903 条股票；每日检查源是否更新 | Cboe Japan、Japannext、月末后变更、历史退市 | `partial` |
| JP ETF/上市产品 universe | JPX ETF HTML 已有 `live` | 月度全量文件新增 476 ETF/ETN、63 上市基金、2 Equity Contribution Securities；保留原 ETF HTML 补充 | ETF/ETN 在月度文件中合并分类；PTS 产品未覆盖 | `live`（TSE 范围） |
| JP 公司公告 | TDnet/EDINET `live` | 未重写公告 connector；新 universe 为证券名称/板块/类型回填 | PTS 不产生独立发行人公告主链 | `live` |
| ETF 专属公告 | 两地均无 | 没有用目录或公司公告伪装基金公告 | 基金招募书、份额变更、指数、分红等专门来源 | `unavailable` |

这次将旧 28 国自动报告中的 universe 统计从 `15 live / 9 partial / 3 stub / 1 unavailable` 改为 `15 live / 11 partial / 2 stub / 0 unavailable`；ETF universe 从 3 个 live 增至 4 个 live。公司 disclosure 统计没有被目录改动虚假抬高。

## 2. 来源研究和裁决

### 2.1 瑞士 SIX

官方入口：

- Share Explorer：`https://www.six-group.com/en/market-data/shares/share-explorer.html`
- ETF Explorer：`https://www.six-group.com/en/market-data/etf/etf-explorer.html`
- 页面使用的 JSON：`https://www.six-group.com/fqs/ref.json`

实际请求合同：

| 范围 | where | orderby | 2026-08-24 实测 |
|---|---|---|---:|
| Swiss Shares | `PortalSegment=EQ*TitleSegment=SA` | `ShortName` | 224（223 股份/参与证书 + 1 认购权） |
| Foreign Shares | `PortalSegment=EQ*TitleSegment=AA` | `ShortName` | 36 |
| ETF | `ProductLine=ET*PortalSegment=FU` | `FundLongName` | 2,285 |

响应带 `protocolVersion`、`pageNumber`、`pageSize`、`totalRows`、`colNames` 和 `rowData`，并给出 `delayMinutes`、`delayedMillis`、`delayedDateTime`。代码不依赖页面 CSS，也不抓取每个详情页面；它按 `totalRows` 完成所有分页，逐页验证列顺序、请求范围、原生 `ValorId`，并交叉校验 Zurich 本地延迟时间与 epoch 毫秒。三类请求不是同一个瞬时快照，因此 cache 保存各 scope 的真实来源时间和总有效时间窗口，不拿本地采集时间冒充来源有效时间。

股票字段映射：

| SIX 字段 | cache 字段 | 用途 |
|---|---|---|
| `ValorId` | `valor_id` | 唯一交易线身份；跨页和跨产品不得重复 |
| `ValorSymbol` | `ticker` | 项目 ticker/name fallback |
| `ISIN` | `isin` | 公告和第三方补充源的稳定身份匹配 |
| `ListingSegmentCode/Desc` | `listing_segment_code/board` | SIX 上市板块 |
| `SecTypeCode/Desc` | `security_type_code/security_type` + `instrument_type` | RS/BS=`equity`，PC=`participation_certificate`，RI=`subscription_right`；未知类型失败关闭，RI 不进入公司映射 |
| `TitleSegment` | `title_segment` | SA/AA 范围证明 |

ETF 另保存交易币种、基金币种、复制方式、标的地域、法律结构国家和管理费。相同 ISIN 的 CHF/USD 等交易线不去重，因为 `ValorId` 和 ticker 可能不同；实际缓存有 125 个重复 mnemonic，name fallback 对这些歧义代码不猜测。

SIX 的网页免责声明不构成商业再分发授权。本实现只保存项目内部监控所需元数据，不复制完整网页或文件库，不声称接入 SIX 商业 Reference Data/Exfeed，也不对外提供原始数据转售能力。

### 2.2 日本 JPX

官方入口：

- 说明页：`https://www.jpx.co.jp/english/markets/statistics-equities/misc/01.html`
- 固定月度文件：`https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xls`
- ETF 补充页：`https://www.jpx.co.jp/english/equities/products/etfs/issues/01.html`

JPX 说明 `data_e.xls` 是前月末 TSE listed issues，并在每月第三个工作日左右替换。2026-08-24 下载的文件有效日为 2026-07-31，共 4,444 行：

| instrument_type | 数量 |
|---|---:|
| `equity` | 3,903 |
| `etf_etn` | 476 |
| `listed_fund` | 63 |
| `equity_contribution_security` | 2 |

代码用 `xlrd>=2.0,<3` 读取旧式 XLS，要求唯一 `Sheet1` 和精确 10 列表头。支持普通四位代码、新式 `123A` 字母代码，以及官方少量五位 class/preferred share 代码（例如 `25935`）；不会裁成四位或错误补零。

每日刷新并不声称上游每天变化。旧 cache 必须先通过 `jp_universe/v1` schema、来源 URL、最小规模、有效日、SHA-256、逐类型计数和逐行身份一致性校验，才会发送 ETag/Last-Modified 或接受 304；残缺旧 cache 不参与条件请求。即使服务器没有正确返回 304，只有通过同一严格校验的 cache 才能因 SHA-256 相同而不重写文件。新文件有效日倒退、未知 `Section/Products`、重复代码、坏 OLE/BIFF、空表或规模异常都会失败，并保留旧缓存。

JPX Data Portal 的公开页面能显示 4,607 条当前证券并提供“全件 CSV”按钮，但下载是 Salesforce 前端会话动作。本批没有逆向 Aura 请求、重放会话 token 或把浏览器动作伪装成稳定接口；选择了 JPX 明确公开且固定 URL 的月度 XLS。

## 3. 数据流和每日运行

```text
SIX Share/ETF Explorer FQS JSON ──完整分页/总数对账──┐
                                                       ├─> 原子 CH cache ─> Web 名称/ISIN/产品类型回填
JPX data_e.xls ──条件请求/XLS校验/SHA-256───────────┘
JPX ETF HTML ──已有专项解析──────────────────────────> JP ETF 补充名称
```

可由现有 cron、CI 或其他调度器每天执行：

```bash
investment-monitor-refresh-universes --market ch --market jp
```

命令只执行一次刷新，不自行常驻。某一市场失败时仍继续尝试另一个市场，最后汇总失败并以非零退出；不会把另一市场的结果冒充全部成功。Web 的 add-company 请求只读取已预热缓存，缓存冷时记录明确警告，不在 HTTP 请求内同步执行可能持续数十秒的全量下载。JPX 专项 ETF HTML 名称优先于月末 XLS 的较旧名称，但两者均保留明确产品类型。

## 4. 失败保护

- SIX：三范围任一失败则整次失败；不保存“两类成功、一类缺失”的假全量。
- SIX：总数漂移、页码/页长变化、列变化、跨页重复 `ValorId`、提前空页、来源延迟时间矛盾和 max-pages 触顶均失败。
- JPX：304/哈希不变是已验证的无变化；坏 XLS 或日期倒退不是 empty/success。
- 两地：403/429 不绕过、不伪造浏览器 token；临时 5xx/网络错误只有限重试。
- 两地：新 payload 完整验证后才通过临时文件 `replace` 原子覆盖；失败保留旧缓存。
- 两地：cache 不进入 `information_items`，证券目录不会显示成公告。
- ETF：`etf_universe=live` 不会改变 `etf_disclosure=unavailable`。

## 5. 代码和文件改动

主要实现：

- `src/investment_monitor/universe/ch_universe.py`：SIX FQS 客户端、三范围刷新、股票/ETF 分类、缓存/search/name map。
- `src/investment_monitor/universe/jp_universe.py`：JPX XLS 解析、条件请求、哈希、分类和缓存。
- `src/investment_monitor/universe/daily_refresh.py`：每日一次刷新 CLI。
- `src/investment_monitor/sources/tdnet/connector.py`：接受 JPX 官方五位 class/preferred share 代码，避免 universe 可识别而公告 connector 拒绝。
- `src/investment_monitor/web.py`：CH/JP resolver 隔离与预热缓存 fallback。
- `src/investment_monitor/universe/coverage_report.py`：CH/JP 股票和 ETF 状态修正；ETF disclosure 保持独立。
- `src/investment_monitor/{__init__.py,universe/__init__.py}`：新 API exports。
- `pyproject.toml`：增加 `xlrd` 和刷新命令入口。

文档：

- `docs/OFFICIAL_DISCLOSURE_BATCH5_CH_JP_UNIVERSE_ETF_PROMPT_ZH.md`
- `docs/OFFICIAL_DISCLOSURE_BATCH5_CH_JP_IMPLEMENTATION_REPORT_ZH.md`
- `docs/GLOBAL_MARKET_COVERAGE_STATUS_ZH.md`
- `README.md`
- `.env.example`

离线 fixtures/test：

- `tests/fixtures/ch_universe/*.json`
- `tests/fixtures/jp_universe/listed_issues.json`
- `tests/test_ch_universe.py`
- `tests/test_jp_universe.py`
- `tests/test_universe_daily_refresh.py`
- 更新 coverage、boundary 和 Web 接线测试。

## 6. 验证结果

- CH live smoke：2,545 条；SA 224、AA 36、ETF 2,285；类型为 equity 250、participation certificate 9、subscription right 1、ETF 2,285；官方股票与 ETF detail URL 均 HTTP 200。
- JP live smoke：有效日 2026-07-31，共 4,444 条，四类计数与上表一致。
- 定向 CH/JP/TDnet/coverage/Web 测试：122 passed。
- 相关 CH/JP 源文件 `mypy --strict --follow-imports=skip`：success。
- `git diff --check`：通过。
- 全仓 `pytest -q tests`：2,148 passed、2 skipped。
- 最终独立 Gate B：`ACCEPT`（无 P0/P1）。

全仓测试在允许测试绑定临时 localhost 端口的环境中完成，2,148 项通过、2 项按既有条件跳过。

## 7. 仍然缺少和下一步

1. CH 公司 disclosure 仍缺 SIX Exchange Regulation/FINMA 完整免费官方主链；EQS 只是 partial 补充。
2. JP 免费月度文件不能覆盖月内新增/退市差分；优先研究 JPX 免费日变更清单，并与月末快照对账。
3. Cboe Japan/Japannext PTS 仍没有接入可验证的免费官方目录；在此之前 JP 国家 universe 不升级为 complete。
4. CH 的其他瑞士场所和 Sponsored Foreign Shares 未纳入；如果未来需要 IBKR 路由层全覆盖，应建立 venue 映射，不应复制发行人公告。
5. CH/JP ETF issuer disclosure 仍为空；下一阶段应分别研究 SIX 基金文件、JPX/管理人基金公告体系，不能复用普通公司公告自动推断。

最终评级：CH 股票/公司整体 `partial`；JP 股票 universe `partial`、公司 disclosure `live`；两地交易所范围 ETF universe `live`，ETF disclosure `unavailable`。
