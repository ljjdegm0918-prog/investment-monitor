# 官方披露覆盖第四批执行提示词：瑞典 SE + 匈牙利 HU

## 1. 用户目标映射（Gate A）

本批延续固定工作流：**先审计与来源裁决 → 生成可验收提示词 → 实施 → 独立补强 → 全量测试 → 详细报告**。

用户要求落实为：

1. 从当前低覆盖地区中再完成两个地区，不伪造完整覆盖。
2. 只使用免费、官方、无需登录且无需绕过验证码/WAF/访问控制的入口。
3. 不只写报告，必须把 Universe、公告匹配、Web 添加公司和覆盖报告真正接通。
4. 失败、空数据、结构变化和部分结果必须有明确语义；缓存必须原子写入。
5. 不修改新闻模块，不撤销或覆盖其他地区已有改动。
6. 最终报告必须详细说明做了什么、为什么这样做、数据如何流动、验证结果和剩余缺口。

Gate A 结论：**ACCEPT**。以下范围逐条覆盖用户命令，且没有把研究边界扩大为付费数据、浏览器令牌重放或全国市场“complete”承诺。

## 2. 本批地区选择

### 瑞典 SE

当前状态：Nasdaq Sweden 公司公告已接入，但 `se_universe` 仍是历史 stub，导致冷缓存无法用官方公司名称、ISIN 和板块映射 ticker。

官方来源：

- Nasdaq Nordic 官方公开 Shares Screener：
  `https://api.nasdaq.com/api/nordic/screener/shares`
- 分类分别请求：`MAIN_MARKET`、`FIRST_NORTH`。
- 官方市场说明：`https://www.nasdaq.com/products/european-markets/stockholm`

来源裁决门：实施前必须取得并保存脱敏真实响应结构，验证两个 category 各自返回、`data.pagination.total/size/page/totalPages` 与 rows 数量一致、状态码为成功、没有隐藏下一页，并验证 `market=STO` 官方过滤器确实把结果限定为 Stockholm/First North Sweden。若只能以 `currency=SEK` 近似筛选，则必须把它明确写成范围限制，量化排除数量，Universe 只能保持 partial。任一关键条件不成立则不实施、不移除 stub。最终 2026-08-24 现场验证的真实请求参数为 `market=STO`、`category=MAIN_MARKET/FIRST_NORTH`、`size/page`、`tableonly=false`；`assetClass` 不是合法请求参数（发送会 HTTP 400），而是必须在返回行中校验为 `SHARES`。MAIN_MARKET 返回 412，FIRST_NORTH 返回 332，共 744 行；字段含 `fullName/symbol/isin/currency/assetClass/orderbookId`，其中 Stockholm Main Market 合法包含 EUR 报价股票，currency 不得用于排除。

只有上述门通过，才可裁决为免费、免 key、无需登录的 Nasdaq 官方 UI 数据入口。它最多支持已验证的 Nasdaq Stockholm Main Market 与 First North 股票范围，不能证明覆盖 NGM、Spotlight、退市历史或所有瑞典交易场所。因此本批将 SE Universe 从 stub 提升为 **official partial**，不得声称全国 complete。

### 匈牙利 HU

当前状态：BSE/BET 公告档案已接入但 Universe 仍是 stub，公告只能依赖手工 ticker/name；发行人映射不足。

官方来源：

- BSE 官方发行人目录：`https://www.bse.hu/site/Angol/pages/issuers`
- 页面内嵌 `window.dataSourceResults.IssuerDataSource` JSON。
- 官方发行人 profile：`https://www.bse.hu/pages/company_profile/$issuer/{issuer_id}`。
- 官方产品列表页面：`https://bse.hu/Prices-and-Markets/Termeklista/Download-product-list`。

来源裁决门：实施前必须保存脱敏发行人目录和 profile 结构样本，证明无需登录即可读取数据，而不是把页面公共的 Sign-in/CAPTCHA UI 当成数据认证要求；验证目录没有分页/惰性加载遗漏，并确认 `country`、`issuerid`、`instrumentumGroups` 以及 profile 的 Ticker/ISIN/证券类型字段真实存在。若产品 Excel 需要 session、认证或无法进行总数核验，不得依赖它证明完整。任一关键字段或公开访问条件不成立则维持 stub。

经 2026-08-23 现场验证：无需登录的 issuer HTML 内嵌 `window.dataSourceResults.IssuerDataSource`，共 154 行；按实际字段筛选 `country=HU` 且组含 `W_RESZVENYA/W_RESZVENYB/W_SME` 得到 66 个候选；官方 4iG profile 的“Listed securities of the issuer”同时列出债券和 `4iG share / 4IG / HU0000167788`，证券详情明确显示 `Equity class=Ordinary share`、`Market=Prime`。实现必须基于这些真实字段，不可只靠名称猜测；无法从官方页面证实 HU/股票属性的发行人不能入 Universe，只能进入审计计数。

通过来源裁决门后，目录先筛选匈牙利发行人与实际股票组，再用 profile 中明确的 Ticker/ISIN/股票特征补全。无法确认证券类型或身份冲突的记录必须进入待匹配/错误统计，不得把债券、基金或 BETa 外国股票混入。

## 3. 实施范围

### SE Universe

1. 重写 `universe/se_universe.py`，复用或兼容 `NasdaqSeClient.fetch_share_directory()`。
2. 两个分类必须分别取得有效响应；记录分类、ticker、ISIN、名称、货币、asset class、orderbook ID、官方来源 URL。
3. 使用经实测的官方 `market=STO` 过滤器和 `category`；`assetClass=SHARES` 只作为响应行约束，`currency` 只作审计字段。只有在 market 过滤不可验证时才允许退回 `currency=SEK` 的明确 partial 范围，并记录被排除数量及原因。
4. 校验 `pagination.total/size/page/totalPages`，不允许只读默认第一页；对缺字段、空分类、重复 ticker 对应不同 ISIN、重复 ISIN 对应不同 ticker、异常规模、HTML/登录页/429 等失败关闭。
5. 原子写缓存，保留分类计数、排除计数、采集时间与 coverage boundary。
6. Web 首次添加 SE 公司时安全 warm cache；刷新失败不得破坏旧缓存。
7. 覆盖报告改为 partial，并清楚写出 Nasdaq Stockholm 范围边界。

### HU Universe 与公告匹配

1. 重写 `universe/hu_universe.py`，解析官方发行人页内嵌 JSON。
2. 按真实 fixture 验证后的官方字段选择 `country=HU` 且包含 Prime/Standard/Xtend equity group 的发行人；不得以名称猜测国别或证券类型。
3. 逐发行人读取官方 profile，严格解析 issuer name、ticker、ISIN、market、security type；限速、有限重试。
4. 只保存能证明为股票的证券；同 issuer 多股票系列允许保留，同 ticker/ISIN 冲突失败关闭。
5. 单个 profile 失败时保留其他成功结果，但记录 `partial` 与失败发行人；全部失败不得写入新缓存。
6. 原子写缓存，保存 issuer ID、profile URL、board、ISIN、官方来源和更新时间。
7. HU 全量刷新需逐 profile 限速，禁止在 Web 添加公司的同步 HTTP 路径执行；由启动/定时维护预热缓存，冷缓存添加快速降级为 unmapped。覆盖报告从 stub 提升为 partial。
8. 复核 `bse_hu_announcements` 使用新 Universe 后的 issuer 匹配，不改变公告的历史分页边界。

## 4. 非目标

- 不接付费 Nasdaq/BSE reference-data feed。
- 不绕过登录、验证码、WAF、频控或安全措施。
- 不把 Main Market/First North 目录称为完整瑞典全国市场。
- 不把 BSE 债券、基金、证书、BETa 外国股票混入匈牙利股票 Universe。
- 不修改 SE/HU 新闻 connector。
- 不把“代码已注册”或“缓存里有少量测试记录”当作 complete。

## 5. 状态与失败语义

- `success/live`：只用于一次官方请求在其声明范围内完整、结构和计数均通过验证。
- `partial`：至少一个官方板块/发行人成功，但其他请求失败或范围天然不覆盖全国全市场。
- `empty`：只有官方结构有效且明确总数为零时允许。
- `unavailable`：403/429、超时、非 JSON/HTML、登录页、缺必要结构、全部 profile 失败。
- 触顶、重复页、重复身份、规模显著异常必须失败关闭，旧缓存不得被空结果覆盖。

## 6. 离线验收矩阵

### SE

- Main Market + First North fixture 合并。
- `.ST/.SE`、空格/连字符 ticker 归一化。
- 以经验证的请求 `market=STO + category` 和响应 `assetClass=SHARES` 为纳入条件，currency 只记录和统计；只有缺少可验证 market 过滤时才允许 SEK fallback，并量化排除项、保持 partial。
- 分类缺失、空 rows、非法 JSON、403/429、重复 ticker/ISIN、异常小规模失败关闭。
- 缓存原子更新和旧缓存保护。
- Web 冷缓存 warm-up、搜索和 name fallback。
- 覆盖报告为 partial，不能变 complete/live 全国范围。

### HU

- 内嵌 `IssuerDataSource` JSON 解析。
- HU + Prime/Standard/Xtend 筛选，外国/债券发行人排除。
- profile 解析 ticker、ISIN、市场和股票类型；同 issuer 多系列。
- profile 缺字段、结构变化、身份冲突、403/429、超时。
- 部分 issuer 失败保留成功记录并标 partial；全部失败不覆盖缓存。
- Web 冷缓存 warm-up、搜索和公告 issuer 映射。
- 覆盖报告为 partial，保留完整历史与其他交易场所缺口说明。

## 7. 本次临时模型编排

- 轻量/并行角色：候选市场代码审计、官方入口研究、fixture/测试矩阵草案。
- 主流程强模型：来源合法性与覆盖范围裁决、核心 Universe/状态/缓存实现、共享文件整合、最终 Gate B 和详细报告。
- 当前环境没有可验证的 DeepSeek SDK/adapter，因此不伪称使用；其缺席不得阻塞交付。

## 8. Gate B

实施完成后必须进行独立补强审查，重点检查：

1. 部分数据是否错误覆盖旧缓存。
2. 重复 ticker/ISIN、分类遗漏是否可能静默漏数。
3. 页面结构变化是否会被当成合法 empty。
4. Web/coverage 是否真正接线，而不只是新增孤立 parser。
5. 是否误把 partial 范围升级为完整市场。
6. 所有相关离线测试、全项目测试、mypy 和 `git diff --check` 是否通过。

## 9. 最终详细报告模板

最终报告不得只给结论表，必须至少包含：

1. 修改前审计：两个市场原有 Universe/connector/registry/settings/Web/coverage 状态和具体断点。
2. 来源裁决：每个官方 URL、请求参数、响应结构、分页/总数合同，以及免费性、官方性、无需登录的现场证据。
3. 架构与数据流：官方入口 → 严格解析 → 身份/板块过滤 → 原子缓存 → name fallback → 公告匹配 → coverage report。
4. 字段映射：官方字段如何映射到 ticker、ISIN、issuer、board、source URL、更新时间和审计字段。
5. 文件逐项变更：每个新增/修改文件做了什么，不能只列文件名。
6. 失败保护：403/429、超时、HTML/JSON 结构变化、分页不完整、身份冲突、部分 profile 失败、旧缓存保护如何处理。
7. 量化结果：现场总行数、纳入数、分类计数、排除数、失败/待匹配数和覆盖评级。
8. 测试证据：离线 fixture、实时 smoke、完整测试/mypy/diff-check 的具体命令与结果；环境限制必须单独说明。
9. 遗留缺口：未覆盖交易场所、历史/退市、付费边界和下一步三个最有价值改进。
10. Git 交付：先审计 `git status`，只暂存本批明确文件；不得把工作区已有未跟踪文档或其他人的改动带入提交。报告 commit hash 与 push 结果。
