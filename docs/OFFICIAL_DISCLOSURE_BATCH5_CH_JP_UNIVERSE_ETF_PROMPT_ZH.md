# 第五批实施提示词：瑞士与日本股票／ETF 覆盖补齐

## 一、任务背景

在 `ai功能测试` branch 中继续改进旧版 IBKR 27 国范围，不新增国家。本批只处理瑞士（CH）和日本（JP），因为最新覆盖审计显示两地股票 universe 仍处于最低覆盖组；同时把股票与 ETF 明确分开，补齐可安全落地的免费官方目录和每日刷新能力。

允许“partial／约 80% 可验证覆盖”，不要求伪造 complete。每日任务只需能检查并更新缓存；来源没有变化时不得重复写入。不得使用付费接口，不得申请许可，不得绕过登录、验证码、WAF、Cloudflare、会话 token 或频率限制。

## 二、用户意图映射

| 用户要求 | 本批落地方式 |
|---|---|
| 先看最新 IBKR 报告 | 只采用最新重跑的旧 27 国报告，不使用旧报告或新增 IBKR 国家 |
| 先给方案和提示词，再实施、最后补强 | 先完成来源裁决与本提示词；实现后执行独立失败语义和测试复核 |
| 覆盖尽量广、每日更新即可 | CH 同时采集 SIX Swiss/Foreign Shares 和 SIX ETF；JP 采集 JPX 月度全量上市证券并每日轮询源文件 |
| 可以接受 partial／约 80% | CH 不声称覆盖非 SIX 瑞士场所；JP 不声称覆盖 PTS 或月末后变更；两地国家 universe 均最高为 partial |
| 不能接受完全无覆盖 | 用真实免费官方目录替换 CH stub，并新增 JP 股票 universe；缓存冷或上游失败时明确报错而不是假成功 |
| ETF 也要统计 | 独立记录 instrument_type 和各类型数量；ETF universe 与 ETF disclosure 分开，目录不能冒充公告 |

## 三、来源裁决

### 3.1 瑞士 CH

使用 SIX 官方 Share Explorer 与 ETF Explorer 前端自身使用的公开 JSON：

- 页面：`https://www.six-group.com/en/market-data/shares/share-explorer.html`
- 页面：`https://www.six-group.com/en/market-data/etf/etf-explorer.html`
- JSON：`https://www.six-group.com/fqs/ref.json`
- 股票条件：`PortalSegment=EQ*TitleSegment=SA` 与 `PortalSegment=EQ*TitleSegment=AA`
- ETF 条件：`ProductLine=ET*PortalSegment=FU`

实现前已验证 JSON 返回 `pageNumber`、`pageSize`、`totalRows`、`colNames`、`rowData`。`SA` 为 Swiss Shares，`AA` 为 Foreign Shares；Sponsored Foreign Shares (`SP`) 不纳入主股票 universe。股票和 ETF 均以 `ValorId` 作为交易线身份，保留 ISIN、symbol、上市板块、产品/证券类型、交易币种和 SIX 官方详情 URL。必须按 `SecTypeCode` 白名单区分 RS/BS 股份、PC 参与证书和 RI 认购权；RI 可保留为单独产品但不得用于公司股票映射，未知类型失败关闭。

SIX 页面免责声明不等于数据再分发授权。本实现只用于项目内部每日元数据缓存，不复制网页内容库、不对外再分发原始数据，也不把公开 UI JSON 说成 SIX 商业 Reference Data API。国家范围仍为 partial，因为不覆盖全部瑞士交易场所和历史退市证券。

### 3.2 日本 JP

使用 JPX 官方免费月度全量上市证券文件：

- 说明页：`https://www.jpx.co.jp/english/markets/statistics-equities/misc/01.html`
- 文件：`https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xls`

JPX 说明其为前月末的 TSE listed issues，并在每月第三个工作日左右更新。每日任务轮询这个固定官方 URL，比较 ETag／Last-Modified／内容哈希；只有内容变化才替换缓存。使用开源 `xlrd` 读取旧版 XLS，严格验证唯一工作表、10 列表头、有效日期、代码、名称和 `Section/Products`。

分类至少区分：

- `equity`：Prime／Standard／Growth／PRO Market 的 Domestic/Foreign shares；
- `etf_etn`：`ETFs/ ETNs`；
- `listed_fund`：REIT、Venture Fund、Country Fund、Infrastructure Fund；
- `equity_contribution_security`：单独保留，不伪装普通股。

现有 JPX ETF HTML connector 继续保留，用作 ETF 当前目录补充和交叉验证；不得用前端 Data Portal 的 Salesforce 会话、token 或“全件 CSV”动作作为运行时接口。日本国家 universe 为 partial，因为不覆盖 Cboe Japan／Japannext PTS，且免费官方全量文件存在月末时点延迟。

## 四、实现范围

1. 重写 `ch_universe.py`：严格分页、限速、有限重试、响应结构校验、跨页重复/无进度/总数漂移失败关闭、股票和 ETF 类型分类、原子缓存、旧缓存保护。
2. 新增 `jp_universe.py`：官方 XLS 下载和解析、条件请求元数据、哈希不变不重写、类型分类、原子缓存、旧缓存保护。
3. 保留并接入 `jp_etf_universe.py`：作为 ETF 专项补充，不把 ETF 行混成股票公司。
4. 在 universe exports、Web add-company name fallback、coverage report 和 README 中接线；冷缓存刷新必须有界，不能阻塞数分钟。
5. 每个 cache 保存：source、source_url、updated_at、source_effective_date、coverage_boundary、counts_by_type、excluded_counts、items、HTTP 校验元数据（可用时）。
6. 每个 item 尽量保存：name、ticker、ISIN（源有时）、exchange、board、instrument_type、source、official_detail_url、官方原生 ID；JPX 月度文件没有 ISIN 时不得猜。
7. ETF disclosure 状态不因 ETF 目录上线而改变；没有免费稳定官方基金公告源时仍为 unavailable。

## 五、失败语义

- 403、429、5xx、超时、TLS/DNS、HTML/登录页、非 JSON、坏 XLS、缺列、空列表、分页触顶、总数漂移、跨页重复、身份冲突：均不能标 success。
- 临时网络错误最多有限重试；403/429 不绕过、不更换伪造身份。
- 刷新失败不得覆盖旧缓存；状态报告要能区分“旧缓存可用”和“本次刷新失败”。
- CH 的 SA、AA、ETF 三个范围任一失败，本轮全量 refresh 失败；不能以其余范围冒充完整本轮结果。
- JPX 官方文件哈希不变属于成功核验但不改写；月末文件日期异常倒退必须失败关闭。

## 六、离线测试矩阵

### CH

- SA、AA、ETF 三类正常响应及多页成功；
- 非 1 起始页、pageSize/totalRows/colNames 漂移、重复 ValorId、跨页 overlap、提前空页、页数上限；
- 同 ISIN 多币种 ETF 交易线保留，同 ValorId 冲突失败；
- SP、非预期 PortalSegment/ProductLine 不进入结果；
- 403、429、超时、非 JSON、HTML loading 页、空 rowData；
- 原子缓存与刷新失败旧缓存保护；
- `.SW` 等 ticker 归一化和 name fallback。

### JP

- 官方 XLS 表头、数字/字母代码、全产品分类、有效日期；
- Prime/Standard/Growth/PRO、Foreign shares、ETF/ETN、REIT/基金和 Equity Contribution Securities；
- 多交易类型不得混成普通股；ETF HTML 与月度 XLS 交叉统计；
- 多工作表、坏 OLE、缺列、空表、重复代码、代码/日期异常、发布日期倒退；
- ETag/Last-Modified/哈希不变不重写；
- 403、429、超时和旧缓存保护；
- Web 冷缓存有界刷新，覆盖报告不能把 partial 提升为 complete。

## 七、验收与最终报告

1. 定向测试、相关市场回归、全量测试全部通过；相关源文件 mypy 通过，`git diff --check` 通过。
2. 最终报告逐项列出：修改前/后/仍缺/状态、官方 URL 与请求契约、字段映射、数据流、文件改动、实时抽样、fixture、测试命令与结果、失败保护、量化纳入/排除、覆盖边界和下一步。
3. 报告明确：CH/JP 股票 universe 均为 partial；CH/JP ETF universe 可以按官方交易所范围标 live，但不等于 ETF disclosure live。
4. Git 操作只暂存本批明确修改文件；先审查 `git status`，不得提交此前已有的未跟踪 MD/DOCX。

## 八、实施前自检结论

- 与“先提示词、再实施、最后补强”一致：是。
- 与“旧 IBKR 27 国、不扩新市场”一致：是。
- 与“免费、无许可、无绕过”一致：是。
- 与“允许 partial／约 80%，但不能零覆盖”一致：是。
- 与“股票与 ETF 分开，目录不冒充公告”一致：是。
- 与“每日扫描更新”一致：是；CH 为每日分页刷新，JP 为每日条件轮询月度官方文件。
- 是否存在范围膨胀：否；本批不重写 CH/JP 公告 connector，不接付费 PTS/SIX 数据产品。
