# 地域性权威新闻覆盖（第一批）

更新时间：2026-08-31

## 目标与准入标准

本批次补充各市场当地主要编辑媒体，不以小道消息、论坛、匿名转载站或来源不明聚合站凑数量。来源必须同时满足：

1. RSS/API 位于媒体官方域名，或由媒体官方 RSS 目录明确链接；
2. 媒体在当地具备较高知名度与稳定编辑组织；
3. 接口无需登录、绕过付费墙或模拟浏览器挑战；
4. 只保存 feed 提供的标题、摘要、时间和 canonical 链接，不抓文章正文；
5. 能通过本地官方公司身份与公司名称保守初筛；开启相关性 AI 时，再经过统一主角判定；
6. 没有稳定公开接口或使用边界明显不适合的地区，明确记录为空白，不猜 URL、不抓脆弱 HTML。

公开可读取不等于获得商业再发布授权。本项目只实现最小 RSS 元数据与深链采集；正式商业部署前仍应逐家确认媒体条款或取得书面许可。

## 已接入的第一批

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

## 本轮没有强行接入的地区

| 市场 | 边界 |
|---|---|
| CN | 财新等主要媒体未发现可验证、公开、稳定的公司新闻 RSS/API；不抓付费站 HTML。 |
| JP | Nikkei RSS 的公开使用边界偏个人/非商业，且未取得稳定公司级端点；暂不接。 |
| TW | CNA feed 明确限制非商业；工商时报、经济日报未找到可验证公开接口；暂不接。 |
| AU | ABC 官方说明旧 RSS 已停止更新；Stockhead 已在项目中作为带商业内容风险标记的补充来源。 |
| IN | Economic Times RSS 的再利用边界不适合默认产品化，且具体 Markets feed 需再次确认；暂不接。 |
| BE | De Tijd/L’Echo 被 WAF 阻挡，VRT/RTBF 未得到可验证且使用边界合适的财经 feed；暂不接。 |
| DE | Handelsblatt 官方明确商业使用 RSS 需事前许可；获得许可前不接。 |
| NL | NOS Economie 技术可用，但官方条款限制私人、非商业用途；获得许可前不接。 |
| PL | PAP MediaRoom 的 business feed 实质为客户宣传/广告材料，不把它冒充独立财经新闻。 |

`AQ`、`CXE`、`TRQ`、`EUX`、`EMF` 是交易场所或产品范围而不是独立国家新闻地域。它们应按发行人主上市国家路由媒体，不创建虚假的“当地媒体”。

## 数据与失败契约

- `source_type=news`，`document_type=publisher_news`；
- 每条记录保留 publisher、publisher_domain、feed_url、feed_scope、language、matched_aliases 和 license_note；
- `article_body_fetched=false` 是硬边界；
- feed 使用市场当地时区做日期过滤，存储时间统一转 UTC；
- 响应有字节上限、超时、有限重试、限速、XML/RSS 结构校验；
- feed 重定向和文章链接必须是 HTTPS 且属于逐项审核的媒体域名；
- 优先使用 RSS GUID 作为稳定身份，URL 查询参数变化不会生成重复新闻；
- 同一轮同一 source/date range 只请求一次；
- `CONTENT_RELEVANCE_AI_ENABLED=true` 时，只有 `primary_subject` / `primary_affected` 才能入库；模型失败继续 fail closed。该开关默认关闭。
