# 第三批官方公告连接器执行提示词：荷兰 NL + 奥地利 AT

## 角色与目标

你是一名负责证券交易所与监管公告采集的高级工程师。请在当前仓库的
`ai功能测试` branch 上，补强两个仍属低覆盖的市场：荷兰（NL）与奥地利
（AT）。先审计，后实现，再独立补强；不得撤销、覆盖或重排其他人已有改动。

这次任务只处理上市公司 Filing／监管或交易所官方公告，以及支持身份匹配所
必需的官方证券目录。新闻、社区、付费行情、自动绕过 WAF／验证码／登录与
未公开 token 不在范围内。

## 为什么选择这两个地区

1. **荷兰 NL**：证券目录已有 Euronext Amsterdam 官方 CSV，但披露只有
   非官方且不完整的 EQS。AFM 已公开“Openbaarmaking voorwetenschap”
   登记册、分页 HTML、官方详情编号及 CSV/XML 导出，免费、无需登录，能直接
   增加 Tier 1 监管来源。
2. **奥地利 AT**：当前代码和报告仍把 Wiener Börse 目录与公告写成 stub，
   实际官网已服务端渲染全部上市公司表，Ad-hoc News 也有公开分页档案。现有
   parser 错把发布平台前缀当发行人、只接受数字 ID、不能证明分页完整性，修复
   后可取得明显覆盖增量。

## 官方来源合同

### NL — AFM 内幕信息登记册

- 官方说明页：
  `https://www.afm.nl/en/sector/registers/meldingenregisters/openbaarmaking-voorwetenschap`
- 公共分页端点：
  `GET https://www.afm.nl/api/sitecore/RegisterOverview/PagedRegisters`
- 固定 context：`{6122672C-938A-4AA6-A244-80B2631E4AEF}`；参数包括
  `skip`、`take=50`、`currentPage`、`dateFrom`、`dateTill`，日期格式为
  `DD-MM-YYYY`。
- 每行必须解析官方详情 URL 中的 AFM ID（例如 `C2608-00947`）、法定名称、
  标题和 Amsterdam 本地发布时间。
- 必须读取页面总数并继续分页，最终唯一 AFM ID 数必须与总数一致。分页重叠、
  提前空页、总数变化、缺 ID／公司／标题／日期、Loading／登录／WAF HTML、
  页数触顶均失败关闭。
- 只有明确 `total=0` 且无结果行时才是 `empty`。
- 与现有 NL universe 通过法定名称匹配；不能匹配的官方记录进入
  `pending_matching`／待匹配状态，不能静默丢弃。
- `eqs_nl` 保留为补充来源，不得升级为官方监管源。

### AT — Wiener Börse 公司目录与 Ad-hoc News

- 官方公司目录：
  `https://www.wienerborse.at/en/listing/shares/companies-list/`
- 官方公告档案：`https://www.wienerborse.at/en/news-1/`
- 目录表必须保存 ISIN、发行人、国家、市场、板块、证券类型、官方 profile URL；
  排除 `global market` 的外国便利交易证券与 UCITS／基金，仅保留奥地利上市公司
  及合适的股权证券类型。缺关键列、重复 ISIN、结构变化或规模异常失败关闭。
- 如果目录没有公开 ticker，必须诚实以 ISIN 作为稳定可检索身份，并允许配置
  overlay 补 ticker／更名别名；不得臆造 ticker。
- Ad-hoc 档案使用官方分页（当前 25 条/页），只把 `Ad-hoc News` 当 issuer
  filing；`Vienna Stock Exchange News`、媒体稿和董事交易等不冒充本任务的
  issuer filing。
- 公告原生 ID 来自 `c93603[file]`，必须支持非数字 opaque ID；详情/PDF URL
  原样保存。发行人从标题剥离 `EQS-Adhoc:`／`PTA-Adhoc:` 等发布平台前缀并与
  官方目录匹配，不能把 `EQS` 或 `PTA` 当发行人。
- 分页必须验证页数、记录唯一性、日期倒序和终止条件；重复页、无进展、结构
  变化、达到上限但仍未覆盖请求日期，都失败关闭。
- 30 天滚动采集可以标记为官方 Ad-hoc 覆盖，但不得宣称覆盖 Wiener Börse
  2008 年以来全部历史，也不得把它写成奥地利全部监管文件。

## 统一数据和状态要求

每条记录至少包含：官方公告 ID、发行人、ticker 或 ISIN、发布时间与时区、
公告类型、官方原文 URL、附件 URL（若页面提供）、实际采集 URL、原始来源
provenance、market、source tier、匹配状态。

状态必须区分：

- `success`：请求窗口完整、分页与总数已经验证；
- `empty`：官方响应明确证明请求窗口为零；
- `partial`：取得有效官方行但有待匹配身份或已有补充源天然不全；
- `unavailable`／`failure`：网络、403/429、页面结构、分页或数据合同失败；
- `disabled`：配置主动关闭。

禁止把解析不到结果、只读第一页、命中页数上限、重复分页、HTML Loading 或
官方页面异常空包标为 success。单一连接器失败不得使同市场的其他连接器结果
丢失。

## 需要修改的范围

- 新增 `sources/afm_nl/` 官方连接器、离线 fixtures 和测试；
- 修复 `sources/wiener_boerse_news.py`，并把 `universe/at_universe.py` 从旧 stub
  升级为官方目录 cache；
- 仅追加 NL/AT 的 registry、settings、source label、coverage report、README
  与全局覆盖文档内容；
- NL dedupe 优先 AFM ID／官方详情 URL，EQS 继续使用自身 ID，跨来源只在
  ticker + Amsterdam 当地日 + 规范标题足够可靠时关联；
- AT dedupe 优先 Wiener opaque file ID／官方 URL，再使用 ticker/ISIN + Vienna
  当地日 + 规范标题；保留所有原始 source rows，只做项目既有的 annotate-only
  canonical 标注。

## 离线验收矩阵

1. AFM 两页、零结果、Dutch 月份、DST 边界、总数变化、重复 ID、提前空页、
   malformed/login/Loading、页数上限。
2. AFM 法定名称匹配与待匹配记录、官方 ID/详情 URL/provenance、EQS 跨来源
   去重与附件/来源保留。
3. Wiener 公司目录过滤 Regulated Market/direct market、排除 global market
   与基金、重复 ISIN、缺列、异常小规模、原子 cache、overlay ticker/别名。
4. Wiener Ad-hoc 两页、opaque ID、EQS/PTA 前缀剥离、非 filing 行排除、
   日期边界、重复页、倒序破坏、malformed 行、页数触顶。
5. registry/settings/coverage 报告不能再把已实现源写成 stub，也不能因注册就
   声称 complete；相关测试全部离线稳定通过。
6. 运行 NL/AT 定向测试、相关 registry/dedupe/coverage 测试、全量 pytest、
   `git diff --check`；失败必须区分本次回归与既有基线。

## 临时执行编排（只适用于本批）

1. **Source Analyst 关卡**：只用官方一手页面确认字段、分页和允许的公共访问
   边界，不实施绕过。
2. **GPT/Codex 强模型实现关卡**：负责数据合同、connector、registry、identity
   matching、dedupe 和 fail-closed 语义。
3. **Reviewer 补强关卡**：反向构造分页重叠、结构变化、可疑空包、身份误配、
   DST 边界和状态误报；发现 P1 必须修复后重跑测试。

当前可用运行环境没有可验证的 DeepSeek adapter，因此本批不伪称调用
DeepSeek；临时编排按上述职责顺序由当前 GPT/Codex 执行。若项目以后提供真实
adapter，可让 DeepSeek 承担端点考古、fixture 草案和初步测试审阅，但核心数据
合同与最终 code review 仍由强模型裁决。

## 提示词一致性复核

| 用户意图 | 提示词映射 | 结论 |
|---|---|---|
| 先找两个覆盖较低的地区 | 选择当前 disclosure 为 partial/stub 的 NL 与 AT | 覆盖 |
| 先给方案、再生成提示词 | 本文件先固定来源合同、范围和验收，再允许编码 | 覆盖 |
| 再实施，最后补强 | 明确 Source Analyst → 实现 → Reviewer 三关 | 覆盖 |
| 尽量接入项目全部链路 | registry、settings、identity、dedupe、coverage、README、测试均在范围 | 覆盖 |
| 官方优先、免费且不绕过 | 仅 AFM/Wiener Börse 公共 GET；排除付费、WAF、token、验证码 | 覆盖 |
| 不能把不完整当完整 | 明确 rolling/partial 边界、严格分页和状态失败关闭 | 覆盖 |
| 不破坏其他修改 | 限定 NL/AT，脏工作树只追加本工单内容 | 覆盖 |

**Gate A 结果：ACCEPT。** 提示词与本次命令是同一套流程与目标，没有把任务
扩大到其他市场，也没有以分析报告替代代码交付。
