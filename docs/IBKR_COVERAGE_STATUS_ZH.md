# IBKR 交易场所覆盖现状与缺口（2026-08-16）

## 1. 结论

项目目录记录了 **28 个国家、87 个 IBKR 交易场所标签**。这里的“覆盖”不是“每个撮合场所都有独立接口”：同一证券会在主交易所、MTF、ATS 或路由场所成交，项目以国家/市场的证券目录和披露源为主，再保留 IBKR 的 venue ID 做映射。

当前自动报告结果：

- 股票/证券目录：14 live、6 partial、7 stub、1 unavailable。
- 公司披露：15 live、4 partial、6 stub、3 unavailable。
- 新闻：27 live、1 unavailable；这里表示已配置 Yahoo/Google News 查询链，不保证新闻穷尽性。
- ETF 目录：3 live（美国、德国、日本）、13 unknown、12 unavailable。
- ETF 专属发行人披露：28 个国家全部 unavailable。公司公告不能冒充基金招募书、份额变更、指数或分红文件。

“live”只表示项目已有可运行的官方接口、解析器和离线测试；不表示免费源承诺永久 SLA，也不表示 IBKR 可交易证券与交易所公开证券一一相等。

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| live | 官方、免 key 接口已实现；结构异常或空数据会失败关闭 |
| partial | 已有真实数据，但范围、来源级别或证券映射不能证明完整 |
| stub | 已研究并保留接口边界，但没有可稳定自动刷新的免费结构化源 |
| unavailable | 当前没有可用实现，或因交易/访问限制明确停用 |
| unknown | 股票目录可用，但尚未验证其是否完整包含 ETF |

## 3. 28 国与 87 个场所明细

| 国家 | IBKR 场所（venue ID） | 股票目录 | 公司披露 | 新闻 | ETF 目录 | ETF 披露 | 判断与主要缺口 |
|---|---|---:|---:|---:|---:|---:|---|
| CA 加拿大 | ALPHA, AEQLITN, AEQLITL, CHIXCA, LYNX, OMEGA, CSE, TSE, VENTURE | partial | unavailable | live | unavailable | unavailable | 官方 TSX/TSXV 可用；CSE、NEO/ATS 未形成完整目录；SEDAR+ 有 WAF/TLS 边界。 |
| MX 墨西哥 | MEXI | stub | stub | live | unavailable | unavailable | BMV 已探测的上市公司/重大事件候选地址返回 404；没有稳定免 key 结构化源。 |
| US 美国 | ARCA, ARCAEDGE, BATS, CHX, DRCTEDGE, EDGEA, IEX, ISLAND, ISE, KNIGHT, LTSE, MEMX, PEARL, NASDAQ, BEX, PSX, NYSE, NSX, NYSENAT, AMEX, PINK | partial | live | live | live | unavailable | Nasdaq Trader 覆盖交易所上市股票/ETF，SEC 补 CIK；OTC/Pink 完整性未证明，路由 venue 不是独立发行人目录。 |
| AT 奥地利 | VSE | stub | stub | live | unavailable | unavailable | 维也纳交易所目前仅稳定取得 HTML 展示，未找到稳定免 key 导出。 |
| BE 比利时 | BATEEN, CHIXEN, ENEXT.BE, TRQXEN | live | live | live | unknown | unavailable | Euronext Brussels 股票 CSV + FSMA STORI；MTF 场所依赖主上市证券映射。 |
| CH 瑞士 | BATECH, CHIXCH, EBS, TRQXCH, VIRTX | stub | partial | live | unavailable | unavailable | SIX 完整参考数据偏商业授权/SPA；EQS 只能提供部分披露，不能证明法定披露完整。 |
| DE 德国 | BATEDE, CHIXDE, FWB, GETTEX, SWB, TGATE, TRQXDE, IBIS | live | partial | live | live | unavailable | Xetra 全可交易 CSV 含股票/ETF/ETN/ETC；其他德国场所及 EQS 披露不能证明全量。 |
| EE 爱沙尼亚 | N.TALLINN | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| ES 西班牙 | BATEES, BM, CHIXES | live | live | live | unknown | unavailable | BME 股票接口、CNMV/BME 披露已接；ETF 未单独验证。 |
| FR 法国 | BATEEN, CHIXEN, SBF, TRQXEN | live | live | live | unknown | unavailable | Euronext Paris 股票 CSV + AMF；ETF 官方动态列表尚未落成稳定解析器。 |
| GB 英国 | BATEUK, CHIXUK, LSE, LSEIOB1 | partial | live | live | unavailable | unavailable | Companies House/Investegate 已接；FIRDS 只有 ISIN、缺零售 ticker，LSE/IOB 全目录不能证明完整。 |
| HU 匈牙利 | BUX | stub | stub | live | unavailable | unavailable | BSE 页面可读但没有稳定结构化导出。 |
| IL 以色列 | TASE | stub | stub | live | unavailable | unavailable | TASE/MAYA 请求遇到 400/403 WAF；需要浏览器会话、授权源或付费数据。 |
| IT 意大利 | BVME | live | partial | live | unknown | unavailable | Euronext Milan 股票 CSV 已接；EQS 披露只是补充源；ETF 未单独验证。 |
| LT 立陶宛 | N.VILNIUS | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| LV 拉脱维亚 | N.RIGA | live | live | live | unknown | unavailable | Nasdaq Baltic 官方证券表与公告已接；ETF 分类仍未单独验证。 |
| NL 荷兰 | BATEEN, CHIXEN, AEB, TRQXEN | live | partial | live | unknown | unavailable | Euronext Amsterdam 股票 CSV 已接；EQS 非完整法定源；ETF 动态列表待接。 |
| NO 挪威 | OSE | live | stub | live | unknown | unavailable | Euronext Oslo 股票 CSV 已接；NewsWeb 是 SPA，未找到稳定免 key API。 |
| PL 波兰 | WSE | live | live | live | unknown | unavailable | GPW 目录和 ESPI 披露已接；ETF 分类仍未单独验证。 |
| PT 葡萄牙 | BVL | live | stub | live | unknown | unavailable | Euronext Lisbon 股票 CSV 已接；CMVM/Lisbon 披露缺稳定免 key API。 |
| RU 俄罗斯 | MOEX | partial | unavailable | unavailable | unavailable | unavailable | MOEX ISS 仅用于只读研究；IBKR 交易暂停，项目不提供定价或可交易性承诺。 |
| SE 瑞典 | SFB | stub | live | live | unavailable | unavailable | Nasdaq Stockholm 目录存在 SPA 边界；FI OAM/Nasdaq 披露可用。 |
| AU 澳大利亚 | ASX, ASXCEN, CHIXAU | live | live | live | unknown | unavailable | ASX 目录和公告已接；Centre Point/Cboe 是交易场所映射，ETF 分类待验证。 |
| HK 香港 | SEHK, SEHKSZSE, SEHKSTAR | partial | live | live | unavailable | unavailable | HKEX 主板目录/披露可用；沪港通与 STAR Connect 是路由范围，不等于 SEHK 全目录，故保持 partial。 |
| IN 印度 | NSE | live | live | live | unknown | unavailable | NSE 官方 equity CSV 与公告已接；不混入 BSE-only 股票，ETF 分类待验证。 |
| JP 日本 | CBOEJP, JPNNEXT, TSEJ | unavailable | live | live | live | unavailable | 本次新增 JPX 官方 TSE ETF 目录（实测 408 条）；股票全市场及两个 PTS 仍无稳定免 key 完整目录。 |
| SG 新加坡 | SGX | stub | unavailable | live | unavailable | unavailable | SGX 目录/公告受 SPA/403 限制；不能用 STI 成分股冒充全市场。 |
| TW 台湾 | TWSE | partial | live | live | unavailable | unavailable | TWSE/TPEx 披露可用，但当前目录范围和 IBKR 可交易范围仍不能证明完全一致。 |

## 4. 已经覆盖得较好的部分

若只看“官方股票目录 + 官方/监管披露均为 live”，当前较可靠的核心市场是：BE、EE、ES、FR、LT、LV、PL、AU、IN；英国在本次修正后披露为 live，但证券目录仍是 partial。美国公司披露为 live，股票目录因 OTC/Pink 缺口保持 partial。日本的 TDnet/EDINET 为 live，本次只补齐 TSE ETF，不代表日本股票目录完成。

Euronext/Cboe 等跨市场交易场所需要特别理解：项目能识别目录中的主上市证券和部分 venue 映射，并不意味着为每个 MTF 单独复制一套发行人目录。对“监控发行人披露”的目标，这通常是正确的数据模型；对“逐 venue 验证 IBKR 可下单合约”，最终必须调用 IBKR TWS/Client Portal 的 secdef/contractDetails。

## 5. 免费接口为什么不能保证完整

1. **交易所目录不等于 IBKR 合约目录。** 官方目录说明“在本交易所上市”，IBKR 还会按账户地区、产品权限、币种、路由和监管状态筛选。
2. **免费网页没有 SLA。** HTML/SPA、临时下载链接、WAF、限流和 TLS 策略都可能变化；因此实现必须缓存、保留来源时间，并在结构变化时失败关闭。
3. **聚合新闻不是法定披露。** Yahoo/Google News 能提高召回率，但会漏报、延迟、重复，不能替代监管机构或交易所公告。
4. **第三方免费目录只能作候选。** EODHD/Twelve Data/OpenFIGI 等可补 ticker/ISIN/FIGI，但其免费层有额度、延迟或市场缺口，不能把市场状态提升为官方 live。
5. **ETF 是另一套披露体系。** 股票公告源通常不提供基金招募书、KID/KIID、份额变化、指数方法和分红全量；必须按交易所/发行人另建接口。

## 6. 本次实际完善

- 修正英国披露状态误判：报告此前错误地用 ISO `GB` 覆盖内部市场键 `uk`，导致已有 Companies House/Investegate 被显示为 unavailable；现为 live，并增加回归测试。
- 新增 JPX 官方 ETF 目录：解析 `Listed Issues - ETFs` 的 Listing Date、Index、Code、Fund Name、Management Company；现场页验证 408 条。
- 修正日本新式字母证券代码：例如 `473A` 不再被错误改成 `0473`，因此目录、新闻查询可保持同一代码。
- JPX 表头变化、空表、畸形行、重复代码、无效代码都会明确失败，不会静默写入坏缓存。

## 7. 下一轮最值得做的接口（按质量收益排序）

1. **IBKR 合约校验层。** 用户运行 TWS/IB Gateway 后，以现有官方目录为候选，通过 `contractDetails/secdef` 得到真实 conid、validExchanges 和账户可交易性。这是缩小“交易所目录 ≠ IBKR 可交易目录”差距的唯一权威办法，但需要本机 IBKR 登录会话。
2. **Euronext ETF 官方列表。** 官方页面覆盖 Amsterdam、Brussels、Milan、Oslo、Paris 等地点，但当前为动态列表；应先找到稳定官方数据端点或可验证导出，再接入 FR/BE/NL/IT/NO/PT，不能直接依赖脆弱 DOM。
3. **JPX 股票全目录。** 继续寻找 JPX 官方日更列表或授权下载；若只能获得 PDF/网页分片，需要建立分页完整性和退市处理，不能以 ETF 页代替股票页。
4. **加拿大缺口。** 接 CSE 官方目录并寻找 NEO/ATS 参考数据；SEDAR+ 若继续 WAF 阻断，只能采用获授权 API、浏览器会话型采集或付费供应商。
5. **SG/IL/CH。** 这些市场的核心阻碍是 WAF/SPA 或商业参考数据授权，不是解析代码本身。质量优先时，应购买/申请官方授权，而不是用指数成分股或抓取镜像伪装全量。
6. **ETF 发行人披露。** 按高持仓市场逐个接入交易所/基金管理人正式文件；这是独立项目，不宜用公司披露源自动推断。

## 8. 仍然无法完成的部分与所需条件

| 阻碍 | 受影响市场 | 真正可行的解法 |
|---|---|---|
| WAF、SPA、需要浏览器令牌 | CA SEDAR+、IL、SG、SE、NO 等 | 官方 API/授权、合规浏览器会话或供应商；不能靠无限重试 |
| 商业参考数据许可 | CH/SIX、部分 venue 级证券主数据 | 购买许可或用 IBKR 登录后的合约查询做账户范围校验 |
| 没有稳定结构化导出 | AT、HU、MX、PT 等 | 与交易所确认 API/文件；否则只保留 stub，禁止假全量 |
| IBKR 账户/地区权限差异 | 全部 87 场所 | 在用户已登录的 IB Gateway/TWS 上运行 secdef/contractDetails |
| ETF 法律文件分散在发行人 | 28 国 | 按发行人/监管体系建设专门 connector，接受需要授权或付费源 |
| 交易暂停/监管限制 | RU | 保持只读研究状态；不能通过技术绕过交易限制 |

## 9. 验收口径

以后只有同时满足以下条件才把接口升为 live：官方来源；许可证允许；自动刷新；分页/总数可验证；字段结构变化会失败；空结果不会覆盖旧缓存；有离线 fixtures；有小型 live smoke；能说明与 IBKR venue/conid 的边界。否则保持 partial、stub 或 unavailable。
