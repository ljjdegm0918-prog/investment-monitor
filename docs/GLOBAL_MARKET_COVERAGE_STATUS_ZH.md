# 独立全球市场信息覆盖现状与缺口（2026-08-24）

## 1. 结论

项目用一份公开经纪商市场清单作为**一次性覆盖面参照**，记录 **28 个国家、87 个交易场所标签**。这只是帮助发现遗漏的 benchmark，不是产品数据源、账号体系或运行依赖。软件直接连接交易所、监管机构和正规第三方；同一证券在主交易所、MTF、ATS 或路由场所成交时，不为每条路由复制一套发行人披露。

产品明确不需要 IBKR 账号、Gateway、TWS、Client Portal、`conid` 或任何 IBKR API。未来即使参考其无需账号且许可允许的公开资料，也只能用于离线检查市场清单，不能进入公司身份、采集或交易逻辑。

当前自动报告结果：

- 股票/证券目录：15 live、11 partial、2 stub、0 unavailable。
- 公司披露：19 live、8 partial、1 unavailable。
- 新闻：27 live、1 unavailable；这里表示已配置 Yahoo/Google News 查询链，不保证新闻穷尽性。
- ETF 目录：4 live（美国、德国、瑞士、日本）、14 unknown、10 unavailable。
- ETF 专属发行人披露：28 个国家全部 unavailable。公司公告不能冒充基金招募书、份额变更、指数或分红文件。

“live”只表示项目已有可运行的官方接口、解析器和离线测试；不表示免费源承诺永久 SLA，也不表示覆盖清单等于任何经纪商的可交易证券清单。

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| live | 官方、免 key 接口已实现；结构异常或空数据会失败关闭 |
| partial | 已有真实数据，但范围、来源级别或证券映射不能证明完整 |
| stub | 已研究并保留接口边界，但没有可稳定自动刷新的免费结构化源 |
| unavailable | 当前没有可用实现，或因交易/访问限制明确停用 |
| unknown | 股票目录可用，但尚未验证其是否完整包含 ETF |

## 3. 28 国与 87 个场所明细

| 国家 | 参考场所标签 | 股票目录 | 公司披露 | 新闻 | ETF 目录 | ETF 披露 | 判断与主要缺口 |
|---|---|---:|---:|---:|---:|---:|---|
| CA 加拿大 | ALPHA, AEQLITN, AEQLITL, CHIXCA, LYNX, OMEGA, CSE, TSE, VENTURE | partial | partial | live | unavailable | unavailable | 官方 TMX TSX/TSXV + CSE 官网全证券 JSON；CSE 官方逐发行人 filing mirror、公司 IR 与双重上市 EDGAR 补漏已接，CEO.ca 仅 Tier 4；SEDAR+ 全国主链与 NEO/ATS 全量仍未完成，评级上限 high。 |
| MX 墨西哥 | MEXI | stub | live | live | unavailable | unavailable | BMV 官方 Eventos Relevantes 滚动公告已接并严格分页；完整定期财务/XBRL 登录产品未接入。 |
| US 美国 | ARCA, ARCAEDGE, BATS, CHX, DRCTEDGE, EDGEA, IEX, ISLAND, ISE, KNIGHT, LTSE, MEMX, PEARL, NASDAQ, BEX, PSX, NYSE, NSX, NYSENAT, AMEX, PINK | partial | live | live | live | unavailable | Nasdaq Trader 覆盖交易所上市股票/ETF；FINRA Security Master 补活跃 OTC 证券，Daily List 补公司行动，SEC 精确 OTC ticker 补 CIK。OTCQX/OTCQB/Pink 分层和非活跃历史仍未覆盖。 |
| AT 奥地利 | VSE | live | partial | live | unknown | unavailable | Wiener Börse 官方公司目录已接（无 ticker 时用 ISIN，可选审核 overlay）；官方 Ad-hoc News 严格分页与 opaque ID 已接，但滚动档案不等于完整 OAM/全历史。 |
| BE 比利时 | BATEEN, CHIXEN, ENEXT.BE, TRQXEN | live | live | live | unknown | unavailable | Euronext Brussels 股票 CSV + FSMA STORI；MTF 场所依赖主上市证券映射。 |
| CH 瑞士 | BATECH, CHIXCH, EBS, TRQXCH, VIRTX | partial | partial | live | live | unavailable | SIX FQS 已覆盖 Swiss Shares、Foreign Shares、Sponsored Foreign Shares 与 ETF，严格分页并保留 ValorId 交易线；SIX Exchange Regulation Official Notices 的公开总数列表/详情 JSON 已按 ISIN 精确接入。BATECH/CHIXCH/TRQXCH/VIRTX 是路由 MTF，不重复建立发行人目录；退市历史和完整 ad-hoc/财报等价覆盖仍缺。 |
| DE 德国 | BATEDE, CHIXDE, FWB, GETTEX, SWB, TGATE, TRQXDE, IBIS | live | partial | live | live | unavailable | Xetra 全可交易 CSV 含股票/ETF/ETN/ETC；其他德国场所及 EQS 披露不能证明全量。 |
| EE 爱沙尼亚 | N.TALLINN | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| ES 西班牙 | BATEES, BM, CHIXES | live | live | live | unknown | unavailable | BME 股票接口、CNMV/BME 披露已接；ETF 未单独验证。 |
| FR 法国 | BATEEN, CHIXEN, SBF, TRQXEN | live | live | live | unknown | unavailable | Euronext Paris 股票 CSV + AMF；ETF 官方动态列表尚未落成稳定解析器。 |
| GB 英国 | BATEUK, CHIXUK, LSE, LSEIOB1 | partial | live | live | unavailable | unavailable | Companies House/Investegate 已接；FIRDS 只有 ISIN、缺零售 ticker，LSE/IOB 全目录不能证明完整。 |
| HU 匈牙利 | BUX | partial | partial | live | unavailable | unavailable | BSE/BET 官方 issuer 目录与 profile 已接：154 个目录发行人、66 个 HU 股票组候选；逐证券验证 ticker/ISIN/Equity class，Market 优先取 security profile，Xtend 缺字段时仅由唯一 W_SME 组回填，并排除债券。公告会话和 CSRF 分页档案仍是有界历史。 |
| IL 以色列 | TASE | stub | live | live | unavailable | unavailable | MAYA 官方 per-company API 已接，保留希伯来语原文并严格核验总数。 |
| IT 意大利 | BVME | live | partial | live | unknown | unavailable | Euronext Milan 股票 CSV 已接；EQS 披露只是补充源；ETF 未单独验证。 |
| LT 立陶宛 | N.VILNIUS | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| LV 拉脱维亚 | N.RIGA | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| NL 荷兰 | BATEEN, CHIXEN, AEB, TRQXEN | live | partial | live | unknown | unavailable | Euronext Amsterdam 股票 CSV + AFM 官方 MAR Article 17 登记册已接并按总数分页对账；EQS 仅补充。年度报告/招股书等其他法定文件与 ETF 动态列表仍待接。 |
| NO 挪威 | OSE | live | live | live | unknown | unavailable | NewsWeb 官方 list/detail/attachment 已接，覆盖 Oslo 各市场并对 overflow 拆窗；单日溢出失败关闭。 |
| PL 波兰 | WSE | live | live | live | unknown | unavailable | GPW 目录和 ESPI 披露已接；ETF 分类仍未单独验证。 |
| PT 葡萄牙 | BVL | live | live | live | unknown | unavailable | Euronext Lisbon canonical 官方档案已接并限定 Filing 类别；CMVM 未接入。 |
| RU 俄罗斯 | MOEX | partial | unavailable | unavailable | unavailable | unavailable | MOEX ISS 仅用于只读研究；项目不提供交易、定价或规避监管限制的能力。 |
| SE 瑞典 | SFB | partial | live | live | unavailable | unavailable | Nasdaq Nordic 官方 Shares Screener 已接：2026-08-24 live 为 Main Market 412 + First North 332；NGM、Spotlight、其他场所和退市历史未覆盖。Nasdaq 官方公司公告保持 live。 |
| AU 澳大利亚 | ASX, ASXCEN, CHIXAU | live | live | live | unknown | unavailable | ASX 目录和公告已接；Centre Point/Cboe 是交易场所映射，ETF 分类待验证。 |
| HK 香港 | SEHK, SEHKSZSE, SEHKSTAR | partial | live | live | unavailable | unavailable | HKEX 主板目录/披露可用；沪港通与 STAR Connect 是路由范围，不等于 SEHK 全目录，故保持 partial。 |
| IN 印度 | NSE | live | live | live | unknown | unavailable | NSE 官方 equity CSV 与公告已接；不混入 BSE-only 股票，ETF 分类待验证。 |
| JP 日本 | CBOEJP, JPNNEXT, TSEJ | partial | live | live | live | unavailable | JPX 官方免费月度 `data_e.xls` 已接，覆盖前月末 TSE 股票、ETF/ETN、REIT/上市基金等并每日轮询；Cboe Japan、Japannext、月内变化及退市历史未覆盖。 |
| SG 新加坡 | SGX | partial | partial | live | unavailable | unavailable | StocksSG 目录仍是第三方 partial；Singtel 与 OCBC 官方 IR 历史档案已内置，另有审核配置式 issuer IR、已知 `links.sgx.com` 官方详情解析和显式 SG/US EDGAR 补漏。SGXNET 枚举受 token-gated SPA 限制，MAS OPERA 有 CAPTCHA、UOB ListedCompany 有 WAF challenge，故不声称 complete。 |
| TW 台湾 | TWSE | partial | live | live | unavailable | unavailable | TWSE/TPEx 披露可用，但证券目录的完整性仍不能证明。 |

## 4. 已经覆盖得较好的部分

若只看“官方股票目录 + 官方/监管披露均为 live”，当前较可靠的核心市场是：BE、EE、ES、FR、LT、LV、PL、AU、IN；英国在本次修正后披露为 live，但证券目录仍是 partial。美国公司披露为 live，股票目录因 OTC/Pink 缺口保持 partial。日本 TDnet/EDINET 为 live，TSE 月末股票/产品目录已接但两个 PTS 和月内变更未覆盖，因此国家 universe 仍是 partial。

Euronext/Cboe 等跨市场交易场所需要特别理解：项目能识别目录中的主上市证券和部分 venue 映射，并不意味着为每个 MTF 单独复制一套发行人目录。对“监控发行人披露”的目标，这才是正确的数据模型；软件不验证任何经纪商账号的下单权限。

## 5. 免费接口为什么不能保证完整

1. **市场参考清单不等于证券主数据。** 一条场所标签只能说明需要研究这个市场，完整证券目录仍必须来自交易所、监管机构或获授权供应商。
2. **免费网页没有 SLA。** HTML/SPA、临时下载链接、WAF、限流和 TLS 策略都可能变化；因此实现必须缓存、保留来源时间，并在结构变化时失败关闭。
3. **聚合新闻不是法定披露。** Yahoo/Google News 能提高召回率，但会漏报、延迟、重复，不能替代监管机构或交易所公告。
4. **第三方免费目录只能作候选。** EODHD/Twelve Data/OpenFIGI 等可补 ticker/ISIN/FIGI，但其免费层有额度、延迟或市场缺口，不能把市场状态提升为官方 live。
5. **ETF 是另一套披露体系。** 股票公告源通常不提供基金招募书、KID/KIID、份额变化、指数方法和分红全量；必须按交易所/发行人另建接口。

## 6. 本次实际完善

- 瑞士 `ch_universe` 扩展 SIX FQS 范围：在 SA、AA、ET/FU 基础上新增 SP Sponsored Foreign Shares；2026-08-24 live 为 SP 551 个交易币种线，全部为官方 `SecTypeCode=SS`，保存币种和首日，并与其他范围原子更新。新增 `six_official_notices`：分页读取 SIX/SER 官方列表总数，只对 universe 精确 ISIN 命中项读取详情，保存 noticeId、公告编号、Valor、官方 URL 与采集 URL；结构化产品噪声不进入股票 Filing。
- 日本新增 `jp_universe`：使用 JPX 官方固定月度 `data_e.xls`，严格校验工作表与 10 列表头，分类股票、ETF/ETN、REIT/上市基金和 Equity Contribution Securities；每日通过条件请求与 SHA-256 检查更新，源无变化时不重写。
- 新增/扩展 `investment-monitor-refresh-universes --market ch --market jp --market us`，可由现有调度系统每天调用；US 原子合并 Nasdaq Trader、FINRA 活跃 OTC Security Master 与 SEC CIK enrichment，任一 breadth 主来源失败时返回失败并保留旧缓存。
- CH/JP ETF universe 已明确为交易所目录覆盖，ETF issuer disclosure 仍保持 unavailable，避免把目录或公司公告误标为基金披露。

- 修正英国披露状态误判：报告此前错误地用 ISO `GB` 覆盖内部市场键 `uk`，导致已有 Companies House/Investegate 被显示为 unavailable；现为 live，并增加回归测试。
- 新增 JPX 官方 ETF 目录：解析 `Listed Issues - ETFs` 的 Listing Date、Index、Code、Fund Name、Management Company；现场页验证 408 条。
- 修正日本新式字母证券代码：例如 `473A` 不再被错误改成 `0473`，因此目录、新闻查询可保持同一代码。
- JPX 表头变化、空表、畸形行、重复代码、无效代码都会明确失败，不会静默写入坏缓存。
- 新增 `ceoca_sedar`：按 ticker 从 CEO.ca 公司频道提取 SEDAR bot 的真实 PDF 链接（不扫描全局历史），精确校验 bot、频道、格式、host 和路径；日期最多 31 天，分页触顶失败关闭；来源固定为 third_party/partial，不能冒充官方 SEDAR+ 全量。
- 新加坡证券目录从 stub 升为 partial：接入 StocksSG 公司 API，保存 ticker、名称、board、UEN、ISIN、LEI，并以总数、最小规模、重复代码检查失败关闭。
- 加拿大 CSE universe 改用 CSE 官网公开调用的 `api/companies/all`，保留 current/halted/suspended/delisted 和 ticker 重用别名；`cse_filings` 沿官方 issuer JSON 读取 accession、分类、状态和 CSE 托管 PDF，真实 CARM smoke 取得 20 条窗口内文件。
- 新加坡 `sg_ir` 新增免配置的 Singtel 与 OCBC 官方 IR 适配：前者解析公开 datamodel，后者解析 2001 起日期/PDF档案；2026-08-01～08-22 live smoke 分别取得 4 条和 2 条。UOB 的 ListedCompany 请求返回 AWS WAF challenge，保持未接入且不绕过。
- 瑞典 `se_universe` 改接 Nasdaq Nordic 官方 Shares Screener：严格使用 `market=STO` 和两个 category，对 `data.pagination` 完整对账，并把响应 `assetClass=SHARES` 作为行级约束；live smoke 共 744 条。currency 只记录，不误删 Stockholm 的 EUR 股票。
- 匈牙利 `hu_universe` 改接 BSE 官方 issuer/security profile：目录筛选只使用官方 country/group ID，逐证券确认股票类型、市场、ticker 和 ISIN；部分 profile 失败不覆盖已有好缓存，未匹配官方公告保留 pending。
- 本轮采用临时多代理编排完成来源侦察、架构审查、实现和独立 Gate B 复核；当前运行环境没有可调用的 DeepSeek 模型，因此没有伪称使用。最终来源裁决、代码整合与回归由 GPT 强模型完成。

## 7. 下一轮最值得做的接口（按质量收益排序）

1. **Euronext ETF 官方列表。** 官方页面覆盖 Amsterdam、Brussels、Milan、Oslo、Paris 等地点，但当前为动态列表；应先找到稳定官方数据端点或可验证导出，再接入 FR/BE/NL/IT/NO/PT，不能直接依赖脆弱 DOM。
2. **JPX 日内变更与 PTS。** 月末全量 XLS 已接；下一步寻找 JPX 免费日更新增/退市差分，并分别研究 Cboe Japan、Japannext 的合法公开目录，不能把 TSE 月末快照称为日本全市场。
3. **加拿大缺口。** CSE 官方目录与 filing mirror 已接；下一步是扩大 TSX/TSXV issuer IR 审核配置、寻找 NEO/ATS 免费官方参考数据，并继续用人工 SEDAR+ 抽样量化缺口。没有许可时不构建 SEDAR+ 自动主链。
4. **SG/IL/MX 与 CH/SE/HU 边界。** SG 已有受审 IR/known-link/EDGAR 补充；CH/SE/HU 已接官方目录但仍需其他交易场所、退市历史或完整公告主链；IL/MX 仍缺官方股票目录。AT 已改用 Wiener Börse 官方目录，不再列为 stub。
5. **ETF 发行人披露。** 按高持仓市场逐个接入交易所/基金管理人正式文件；这是独立项目，不宜用公司披露源自动推断。

## 8. 仍然无法完成的部分与所需条件

| 阻碍 | 受影响市场 | 真正可行的解法 |
|---|---|---|
| WAF、SPA、需要浏览器令牌 | CA SEDAR+、SGX 全市场枚举、UOB ListedCompany、部分 SE 等 | CSE/Singtel/OCBC 等免费可达源已补 partial；要升为全国/全市场完整仍需公开 API/授权或供应商，不能靠 token 重放、挑战绕过或无限重试 |
| 商业参考数据许可 | CH/SIX 全市场/再分发权、部分 venue 级证券主数据 | 当前仅用 SIX 官网公开 explorer 元数据做内部缓存；若要覆盖其他场所、商业 SLA 或对外再分发，需购买许可；不接经纪商账号 |
| 没有完整机器合同或全历史 | HU 公告历史、MX、PT，以及 AT 完整 OAM 历史 | 与交易所/监管机构确认 API/文件；HU 股票目录虽已接，但公告仍为有界档案；当前可用公开源只按已验证边界运行，禁止假全量 |
| ETF 法律文件分散在发行人 | 28 国 | 按发行人/监管体系建设专门 connector，接受需要授权或付费源 |
| 信息取得与使用受制裁/许可影响 | RU 等 | 只接许可允许的官方研究数据；不实现交易，也不通过技术规避法律或来源限制 |

## 9. 验收口径

以后只有同时满足以下条件才把接口升为 live：官方来源；许可证允许；自动刷新；分页/总数可验证；字段结构变化会失败；空结果不会覆盖旧缓存；有离线 fixtures；有小型 live smoke；能说明证券目录、披露和新闻之间的边界。否则保持 partial、stub 或 unavailable。
