# 新闻媒体接口总报告

更新时间：2026-09-02  
统计口径：`config/settings.yaml` 中 `source_type: news` 的逻辑来源，并与注册表、市场路由和连接器实现交叉核对。

## 一、结论摘要

项目当前共有 **96 个新闻逻辑接口**：

| 类别 | 数量 | 启用 | 停用 | 说明 |
|---|---:|---:|---:|---|
| Finnhub Company News | 1 | 1 | 0 | 美国公司级 JSON API，需要 API Key |
| Naver Finance | 1 | 1 | 0 | 韩国公司级公开网页接口 |
| 韩国早期实验接口 | 2 | 0 | 2 | Hankyung 旧公司页、TheBell；因不可稳定访问而停用 |
| Yahoo Finance RSS | 29 | 29 | 0 | 28 个国家/地区市场，加 AQ 交易场所 |
| Google News RSS | 33 | 33 | 0 | 28 个国家/地区市场，加 AQ/CXE/TRQ/EUX/EMF |
| 当地媒体官方 RSS 直连 | 21 | 21 | 0 | 覆盖 20 个国家/地区，香港有 2 家 |
| 当地媒体域名限定发现 | 9 | 9 | 0 | 覆盖没有合适媒体直连接口的 9 个地区 |
| **合计** | **96** | **94** | **2** | 30 个当地媒体来源覆盖全部 29 个国家/地区市场 |

“启用”表示来源已写入配置并注册连接器，不等于任何时候都必然返回文章：Finnhub 需要密钥；RSS 可能因当日无新闻返回空集合；媒体站点或聚合平台也可能调整接口。

## 二、按市场查看现有新闻接口

下表包含以前已有的聚合/公司级新闻源，以及本轮新增的当地媒体来源。`—` 表示该平台没有为该市场配置逻辑来源。

| 市场 | 以前已有的公司级/专用源 | Yahoo Finance | Google News | 当地媒体来源 |
|---|---|---|---|---|
| US 美国 | `news`（Finnhub） | `yahoo_us` | `google_news_us` | `marketwatch_us` |
| CA 加拿大 | — | `yahoo_ca` | `google_news_ca` | `globe_mail_ca` |
| MX 墨西哥 | — | `yahoo_mx` | `google_news_mx` | `el_economista_mx` |
| UK 英国 | — | `yahoo_uk` | `google_news_uk` | `bbc_business_uk` |
| FR 法国 | — | `yahoo_fr` | `google_news_fr` | `lemonde_economie_fr` |
| DE 德国 | — | `yahoo_de` | `google_news_de` | `handelsblatt_via_google_de` |
| NL 荷兰 | — | `yahoo_nl` | `google_news_nl` | `fd_via_google_nl` |
| BE 比利时 | — | `yahoo_be` | `google_news_be` | `de_tijd_via_google_be` |
| IT 意大利 | — | `yahoo_it` | `google_news_it` | `ilsole24ore_finanza_it` |
| ES 西班牙 | — | `yahoo_es` | `google_news_es` | `cincodias_mercados_es` |
| CH 瑞士 | — | `yahoo_ch` | `google_news_ch` | `nzz_news_ch` |
| AT 奥地利 | — | `yahoo_at` | `google_news_at` | `diepresse_news_at` |
| NO 挪威 | — | `yahoo_no` | `google_news_no` | `e24_finance_no` |
| PT 葡萄牙 | — | `yahoo_pt` | `google_news_pt` | `jornal_negocios_pt` |
| PL 波兰 | — | `yahoo_pl` | `google_news_pl` | `puls_biznesu_via_google_pl` |
| SE 瑞典 | — | `yahoo_se` | `google_news_se` | `dagens_industri_se` |
| HU 匈牙利 | — | `yahoo_hu` | `google_news_hu` | `portfolio_hu` |
| EE 爱沙尼亚 | — | `yahoo_ee` | `google_news_ee` | `err_news_ee` |
| LV 拉脱维亚 | — | `yahoo_lv` | `google_news_lv` | `lsm_news_lv` |
| LT 立陶宛 | — | `yahoo_lt` | `google_news_lt` | `lrt_business_lt` |
| KR 韩国 | `naver_news`；`hankyung`/`thebell` 已停用 | `yahoo_kr` | `google_news_kr` | `hankyung_finance_kr` |
| JP 日本 | — | `yahoo_jp` | `google_news_jp` | `nikkei_via_google_jp` |
| HK 香港 | — | `yahoo_hk` | `google_news_hk` | `rthk_finance_hk`、`scmp_business_hk` |
| CN 中国内地 | — | — | — | `caixin_via_google_cn` |
| TW 台湾 | — | `yahoo_tw` | `google_news_tw` | `cna_via_google_tw` |
| SG 新加坡 | — | `yahoo_sg` | `google_news_sg` | `business_times_sg` |
| IN 印度 | — | `yahoo_in` | `google_news_in` | `business_standard_via_google_in` |
| IL 以色列 | — | `yahoo_il` | `google_news_il` | `globes_news_il` |
| AU 澳大利亚 | — | `yahoo_au` | `google_news_au` | `afr_via_google_au` |
| AQ Aquis | — | `yahoo_aq` | `google_news_aq` | 不单列媒体，按发行人所属地区处理 |
| CXE Cboe Europe | — | — | `google_news_cxe` | 不单列媒体，按发行人所属地区处理 |
| TRQ Turquoise | — | — | `google_news_trq` | 不单列媒体，按发行人所属地区处理 |
| EUX Eurex | — | — | `google_news_eux` | 不单列媒体，属于交易场所/产品范围 |
| EMF ETF/基金范围 | — | — | `google_news_emf` | 不单列媒体，属于产品范围 |

## 三、以前已有的通用和公司级接口

### 3.1 Finnhub Company News

| Source | 市场 | 接口 | 状态 | 依赖/限制 |
|---|---|---|---|---|
| `news` | US | `GET https://finnhub.io/api/v1/company-news` | 已启用 | 需要 `FINNHUB_API_KEY`；按 symbol/from/to 查询；最大回看 30 天 |

### 3.2 Naver 与两个已停用韩国实验接口

| Source | 接口 | 状态 | 说明 |
|---|---|---|---|
| `naver_news` | `https://finance.naver.com/item/news_news.naver?code={code}` | 已启用 | 无 Key；HTML/EUC-KR；页面结构变化可能导致空结果或解析失败 |
| `hankyung` | Hankyung 旧公司股票页 | 已停用 | 目标页返回 403/404，无法确认稳定公司新闻入口 |
| `thebell` | TheBell 旧公司文章列表 | 已停用 | 候选地址返回 soft 404，且旧基础地址仍是 HTTP，不适合启用 |

注意：已启用的 `hankyung_finance_kr` 是本轮新增的韩国经济日报官方财经 RSS，与已停用的旧 `hankyung` 公司页连接器不是同一接口。

### 3.3 Yahoo Finance RSS

- 接口模板：`https://feeds.finance.yahoo.com/rss/2.0/headline`
- 查询方式：按经过市场后缀转换的证券代码请求，不同地区设置各自的 region/lang。
- 已有 29 个逻辑来源：
  - `yahoo_us`、`yahoo_ca`、`yahoo_mx`、`yahoo_uk`、`yahoo_fr`、`yahoo_de`、`yahoo_nl`、`yahoo_be`；
  - `yahoo_it`、`yahoo_es`、`yahoo_ch`、`yahoo_at`、`yahoo_no`、`yahoo_pt`、`yahoo_pl`、`yahoo_se`；
  - `yahoo_hu`、`yahoo_ee`、`yahoo_lv`、`yahoo_lt`；
  - `yahoo_kr`、`yahoo_jp`、`yahoo_hk`、`yahoo_tw`、`yahoo_sg`、`yahoo_in`、`yahoo_il`、`yahoo_au`；
  - `yahoo_aq`。
- 状态：全部启用、无需 Key。
- 主要限制：公开 RSS 镜像并非正式商业数据合同；文章可能只是提及目标公司；滚动窗口可能漏掉较旧文章。

### 3.4 Google News RSS

- 接口模板：`https://news.google.com/rss/search`
- 查询方式：公司名称或产品名称，加当地 `hl/gl/ceid` 参数。
- 28 个国家/地区来源：
  - `google_news_us`、`google_news_ca`、`google_news_mx`、`google_news_uk`；
  - `google_news_fr`、`google_news_de`、`google_news_nl`、`google_news_be`、`google_news_it`、`google_news_es`；
  - `google_news_ch`、`google_news_at`、`google_news_no`、`google_news_pt`、`google_news_pl`、`google_news_se`；
  - `google_news_hu`、`google_news_ee`、`google_news_lv`、`google_news_lt`；
  - `google_news_kr`、`google_news_jp`、`google_news_hk`、`google_news_tw`、`google_news_sg`、`google_news_in`、`google_news_il`、`google_news_au`。
- 5 个交易场所/产品来源：`google_news_aq`、`google_news_cxe`、`google_news_trq`、`google_news_eux`、`google_news_emf`。
- 状态：33 个全部启用、无需 Key。
- 主要限制：Google 是发现/聚合平台，不是原媒体 API；标题相关不等于公司是文章主角；结果完整性、排序和跳转链接均由 Google 控制。

## 四、当地媒体官方 RSS 直连（21 个）

这些接口直接读取媒体官方域名或其官方发布系统中的 RSS/XML，只保存 feed 提供的元数据和原文链接，不抓正文。

| 市场 | Source | 媒体/栏目 | 当前接口 |
|---|---|---|---|
| US | `marketwatch_us` | MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_topstories` |
| CA | `globe_mail_ca` | The Globe and Mail Business | `https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/business/` |
| MX | `el_economista_mx` | El Economista | `https://www.eleconomista.com.mx/rss/ultimas-noticias` |
| UK | `bbc_business_uk` | BBC News Business | `https://feeds.bbci.co.uk/news/business/rss.xml` |
| FR | `lemonde_economie_fr` | Le Monde Économie | `https://www.lemonde.fr/economie/rss_full.xml` |
| IT | `ilsole24ore_finanza_it` | Il Sole 24 Ore Finanza | `https://www.ilsole24ore.com/rss/finanza.xml` |
| ES | `cincodias_mercados_es` | Cinco Días Mercados | `https://feeds.elpais.com/mrss-s/list/ep/site/cincodias.elpais.com/section/mercados-financieros` |
| CH | `nzz_news_ch` | NZZ | `https://www.nzz.ch/recent.rss` |
| AT | `diepresse_news_at` | Die Presse | `https://www.diepresse.com/rss` |
| NO | `e24_finance_no` | E24 Børs og finans | `https://e24.no/rss2?seksjon=boers-og-finans` |
| PT | `jornal_negocios_pt` | Jornal de Negócios | `https://www.jornaldenegocios.pt/rss` |
| SE | `dagens_industri_se` | Dagens industri | `https://www.di.se/rss/` |
| HU | `portfolio_hu` | Portfolio.hu | `https://www.portfolio.hu/rss/all.xml` |
| EE | `err_news_ee` | ERR | `https://www.err.ee/rss` |
| LV | `lsm_news_lv` | LSM | `https://www.lsm.lv/rss/` |
| LT | `lrt_business_lt` | LRT Verslas | `https://www.lrt.lt/naujienos/verslas?rss=` |
| KR | `hankyung_finance_kr` | Korea Economic Daily Finance | `https://www.hankyung.com/feed/finance` |
| SG | `business_times_sg` | The Business Times | `https://www.businesstimes.com.sg/rss/banking-finance` |
| IL | `globes_news_il` | Globes | `https://www.globes.co.il/WebService/Rss/RssFeeder.asmx/FeederNode?iID=942` |
| HK | `rthk_finance_hk` | RTHK Finance | `https://rthk.hk/rthk/news/rss/e_expressnews_efinance.xml` |
| HK | `scmp_business_hk` | SCMP Business | `https://www.scmp.com/rss/92/feed` |

最近一次逐项真实联网复验为 2026-08-31：21/21 个端点均成功完成访问、RSS/XML 解析、发布时间转换和媒体域名校验。技术可读取不等于已经获得商业再发布权；正式商用仍需逐家确认许可。

## 五、当地媒体域名限定发现（9 个）

以下媒体没有采用直连。连接器向 Google News 发送“公司名称 + `site:媒体域名`”查询，然后再次验证 RSS `<source url>` 属于审核过的媒体域名。它不会把 Google News 冒充为媒体官方 API，也不会访问文章正文。

| 市场 | Source | 指定媒体 | 审核域名 | 未采用直连的原因 |
|---|---|---|---|---|
| CN | `caixin_via_google_cn` | 财新 | `caixin.com` | 未找到稳定公开新闻 RSS/API；正文和再利用有许可边界 |
| JP | `nikkei_via_google_jp` | 日本经济新闻 | `nikkei.com` | 未取得适合产品化的稳定公司级端点 |
| TW | `cna_via_google_tw` | 中央通讯社产经证券 | `cna.com.tw` | 官方 RSS 的公开使用规则限制非商业使用 |
| AU | `afr_via_google_au` | Australian Financial Review | `afr.com` | API/Headline Feed 属于企业产品，不是公开通用接口 |
| IN | `business_standard_via_google_in` | Business Standard | `business-standard.com` | 未找到稳定公开的公司新闻 RSS/API |
| BE | `de_tijd_via_google_be` | De Tijd | `tijd.be` | 直连 RSS 受 WAF 限制，商业监测另有授权边界 |
| DE | `handelsblatt_via_google_de` | Handelsblatt | `handelsblatt.com` | RSS 可访问，但官方商业内容使用需要许可 |
| NL | `fd_via_google_nl` | Het Financieele Dagblad | `fd.nl` | 未得到稳定公开 RSS，媒体监测另有商业许可 |
| PL | `puls_biznesu_via_google_pl` | Puls Biznesu | `pb.pl` | 未发现稳定公开 RSS/API；不采用偏宣传性质的替代 feed |

这 9 个来源有额外硬限制：

- 必须启用 `CONTENT_RELEVANCE_AI_ENABLED=true`；
- 必须配置可用的 `RESEARCH_AI_API_KEY`；
- AI 只有判定为 `primary_subject` 或 `primary_affected` 才允许入库；
- AI 未启用、返回异常、证据不足或只是顺带提及时，候选新闻零入库；
- 每家公司每次最多保留 25 条候选；
- 只保存标题、时间、Google News 链接和经校验的媒体来源域名，不保存 Google RSS description。

最近一次真实查询复验为 2026-08-31：9/9 个指定媒体域名均返回了可验证 `<source>` 归属的记录。

## 六、公司主角过滤与入库规则

所有 `news` 来源都可以进入统一的 AI 相关性过滤器，但当前行为分为两类：

1. 9 个媒体域名限定发现源强制要求 AI 门槛；没有 AI 就失败关闭。
2. Finnhub、Naver、Yahoo、普通 Google News 和 21 个媒体直连源在 `CONTENT_RELEVANCE_AI_ENABLED=true` 时执行 AI 门槛；开关为 false 时仅执行各连接器原有的代码/公司名称初筛。

如果生产要求是“新闻只有在目标公司是文章主角或主要受影响方时才能挂到公司下面”，必须在生产环境启用：

```dotenv
CONTENT_RELEVANCE_AI_ENABLED=true
RESEARCH_AI_API_KEY=已配置的模型密钥
```

模型判定采用失败关闭：格式错误、缺项、重复 ID、文章歧义、列表式顺带提及、泛比较或单纯出现公司名称均排除。

## 七、不计入新闻媒体接口的来源

以下来源可能包含文章或市场观点，但配置类型是 `community`，不计入上述 96 个新闻接口：

- `seeking_alpha`：Seeking Alpha 公开 RSS；
- `stockhead_au`：Stockhead ASX 搜索 RSS；
- `substack`：白名单 Newsletter RSS；
- `ceoca_ca`、`hotcopper_au`、`lse_share_chat`、`xueqiu`、`x_community`、`vic`、`yellowbrick` 等社区/社交来源。

SEC、交易所公告、监管披露、公司 IR、EQS、NewsWeb、Nasdaq Company News 等属于 `filings` 或 `regulatory_disclosure`，即使名称含有 News，也不计入新闻媒体接口。

## 八、当前主要风险

- **授权风险**：公开 RSS 不等于商业转载许可；本项目只保存最小元数据和深链。
- **完整性风险**：RSS 和聚合搜索是滚动窗口，不提供历史全量承诺。
- **相关性风险**：未开启 AI 时，普通来源可能仍存在“文章只是提到公司”的误归。
- **稳定性风险**：Naver HTML、Yahoo RSS、Google RSS 和媒体 feed 均可能改版或限流。
- **付费墙风险**：采集到标题和链接不代表用户一定能打开全文。
- **身份风险**：缺少可靠公司名称或多语言别名时，地域媒体连接器会保守排除或报 `no_universe_identity`。

## 九、维护入口

- 来源启用状态：`config/settings.yaml`
- 来源市场路由与注册：`src/investment_monitor/registry.py`
- 21 个官方 RSS 定义：`src/investment_monitor/sources/regional_press/profiles.py`
- 9 个域名限定媒体定义：`src/investment_monitor/sources/regional_press/discovery_profiles.py`
- 公司主角 AI 过滤：`src/investment_monitor/content_relevance.py`
- 地域媒体专项说明：`docs/REGIONAL_AUTHORITATIVE_NEWS_COVERAGE_ZH.md`

