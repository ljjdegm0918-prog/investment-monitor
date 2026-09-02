# 地域性权威新闻覆盖

更新时间：2026-08-31

## 目标与准入标准

本批次补充各市场当地主要编辑媒体，不以小道消息、论坛、匿名转载站或来源不明聚合站凑数量。来源必须同时满足：

1. 优先使用媒体官方 RSS/API；没有合适直连时，使用限定媒体域名且校验 RSS 来源归属的 Google News 发现源；
2. 媒体在当地具备较高知名度与稳定编辑组织；
3. 接口无需登录、绕过付费墙或模拟浏览器挑战；
4. 只保存 feed 提供的标题、摘要、时间和 canonical 链接，不抓文章正文；
5. 能通过本地官方公司身份与公司名称保守初筛；开启相关性 AI 时，再经过统一主角判定；
6. 不猜 URL、不抓脆弱 HTML；替代发现源必须明确标注，不能冒充媒体官方 API。

公开可读取不等于获得商业再发布授权。本项目只实现最小 RSS 元数据与深链采集；正式商业部署前仍应逐家确认媒体条款或取得书面许可。

## 官方 Feed 直连（21 个来源、20 个地区）

| 市场 | Source | 媒体/栏目 | 官方 feed |
|---|---|---|---|
| US | `marketwatch_us` | MarketWatch Top Stories | `feeds.content.dowjones.io/public/rss/mw_topstories` |
| CA | `globe_mail_ca` | The Globe and Mail Business | `theglobeandmail.com/arc/outboundfeeds/rss/category/business/` |
| MX | `el_economista_mx` | El Economista | `eleconomista.com.mx/rss/ultimas-noticias` |
| UK | `bbc_business_uk` | BBC News Business | `feeds.bbci.co.uk/news/business/rss.xml` |
| FR | `lemonde_economie_fr` | Le Monde Économie | `lemonde.fr/economie/rss_full.xml` |
| IT | `ilsole24ore_finanza_it` | Il Sole 24 Ore Finanza | `ilsole24ore.com/rss/finanza.xml` |
| ES | `cincodias_mercados_es` | Cinco Días Mercados | `feeds.elpais.com/.../mercados-financieros` |
| CH | `nzz_news_ch` | Neue Zürcher Zeitung | `nzz.ch/recent.rss` |
| AT | `diepresse_news_at` | Die Presse | `diepresse.com/rss` |
| NO | `e24_finance_no` | E24 Børs og finans | `e24.no/rss2?seksjon=boers-og-finans` |
| PT | `jornal_negocios_pt` | Jornal de Negócios | `jornaldenegocios.pt/rss` |
| SE | `dagens_industri_se` | Dagens industri | `di.se/rss/` |
| HU | `portfolio_hu` | Portfolio.hu | `portfolio.hu/rss/all.xml` |
| EE | `err_news_ee` | ERR | `err.ee/rss` |
| LV | `lsm_news_lv` | LSM | `lsm.lv/rss/` |
| LT | `lrt_business_lt` | LRT Verslas | `lrt.lt/naujienos/verslas?rss=` |
| KR | `hankyung_finance_kr` | The Korea Economic Daily Finance | `hankyung.com/feed/finance` |
| SG | `business_times_sg` | The Business Times | `businesstimes.com.sg/rss/banking-finance` |
| IL | `globes_news_il` | Globes | `globes.co.il/WebService/Rss/...iID=942` |
| HK | `rthk_finance_hk` | RTHK Finance | `rthk.hk/rthk/news/rss/e_expressnews_efinance.xml` |
| HK | `scmp_business_hk` | South China Morning Post Business | `scmp.com/rss/92/feed` |

这些都是栏目级滚动 feed，不支持原生 ticker/company 参数，因此属于补充覆盖，不能宣称历史全量。连接器每轮只拉取一次 feed，然后用本地证券目录中的公司正式名称和足够明确的简称做初筛，避免为每家公司重复请求媒体。缺少公司身份映射时失败关闭；裸 ticker、类别股根代码及过短简称不参与普通文本匹配。

## 无合适直连时的媒体发现源（9 个来源、9 个地区）

| 市场 | Source | 当地媒体 | 未采用直连的原因 | 替代接入 |
|---|---|---|---|---|
| CN | `caixin_via_google_cn` | 财新 | 无可验证、稳定的公开新闻 RSS/API，正文付费且禁止未授权转载/摘编 | 公司名 + `site:caixin.com` |
| JP | `nikkei_via_google_jp` | 日本经济新闻 | RSS 使用边界偏个人/非商业，未取得可用于产品的公司级端点 | 公司名 + `site:nikkei.com` |
| TW | `cna_via_google_tw` | 中央通讯社产经证券 | 官方 RSS 明确限个人及非营利组织的非商业用途 | 公司名 + `site:cna.com.tw` |
| AU | `afr_via_google_au` | Australian Financial Review | 没有公开通用 RSS；官方把 API/Headline Feed 作为企业产品 | 公司名 + `site:afr.com` |
| IN | `business_standard_via_google_in` | Business Standard | 未找到稳定公开公司新闻 RSS/API；Economic Times RSS 使用边界不适合默认产品化 | 公司名 + `site:business-standard.com` |
| BE | `de_tijd_via_google_be` | De Tijd | RSS 端点被 WAF 阻挡，媒体监测/商业访问另有授权安排 | 公司名 + `site:tijd.be` |
| DE | `handelsblatt_via_google_de` | Handelsblatt | 直连 RSS 技术可用，但官方明确商业内容使用需许可 | 公司名 + `site:handelsblatt.com` |
| NL | `fd_via_google_nl` | Het Financieele Dagblad | 未得到稳定直连 RSS；媒体监测需要商业许可 | 公司名 + `site:fd.nl` |
| PL | `puls_biznesu_via_google_pl` | Puls Biznesu | 未发现可验证公开 RSS/API；PAP MediaRoom 实质是客户宣传材料 | 公司名 + `site:pb.pl` |

替代源只保存 Google News RSS 的标题、时间、Google News 跳转链接和经过校验的原媒体 `source` 域名；不保存 RSS description，不访问媒体正文，也不把它标成媒体直连。由于不同语言的本地标题不一定包含证券目录里的英文公司名，这 9 个来源强制要求 `CONTENT_RELEVANCE_AI_ENABLED=true`，没有 AI 主角门槛时失败关闭、绝不入库。每家公司默认最多取最新 25 条候选，控制模型成本和噪声。查询会把目标公司名称发送给 Google News，这一点与项目现有 Google News 公司搜索源相同。2026-08-31 的真实查询复验中，9/9 个媒体域名都返回了可校验的来源记录。

因此目前 29 个国家/地区市场均至少有一个当地主要媒体来源：其中 20 个地区使用媒体直连，另外 9 个地区使用清晰标注的媒体域名限定发现源。

`AQ`、`CXE`、`TRQ`、`EUX`、`EMF` 是交易场所或产品范围而不是独立国家新闻地域。它们应按发行人主上市国家路由媒体，不创建虚假的“当地媒体”。

## 数据与失败契约

- `source_type=news`；直连为 `document_type=publisher_news`，替代发现为 `publisher_news_discovery`；
- 直连记录保留 publisher、publisher_domain、feed_url、feed_scope、language、matched_aliases 和 license_note；
- 替代发现记录保留 discovery_method、publisher_domains、publisher_source_url、query_domain 和 access_note；
- `article_body_fetched=false` 是硬边界；
- feed 使用市场当地时区做日期过滤，存储时间统一转 UTC；
- 响应有字节上限、超时、有限重试、限速、XML/RSS 结构校验；
- feed 重定向和文章链接必须是 HTTPS 且属于逐项审核的媒体域名；
- 优先使用 RSS GUID 作为稳定身份，URL 查询参数变化不会生成重复新闻；
- 直连栏目同一轮同一 source/date range 只请求一次；替代发现按公司查询并共享限速器；
- `CONTENT_RELEVANCE_AI_ENABLED=true` 时，只有 `primary_subject` / `primary_affected` 才能入库；模型失败继续 fail closed。该开关默认关闭。
