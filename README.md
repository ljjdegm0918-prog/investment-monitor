# Investment Monitor

中文 · [中文使用指南](README_ZH.md) · [English](README_EN.md)

> **说明：** Web 界面目前仍为英文。

Investment Monitor 是一个以列表为中心的本地金融信息监控工作区。首个 Web MVP 使用本项目已有的 SEC EDGAR 连接器，并为 News 与 Community 连接器预留清晰的数据源边界。

## 独立全球市场覆盖总览（Draft PR #35）

产品目标是独立覆盖全球市场信息。公开经纪商市场清单只作为一次性的范围 benchmark：**美洲、欧洲、亚洲 3 个地区，28 个国家、87 个交易场所标签**；产品不需要 IBKR 账号、API、Gateway、TWS、Client Portal 或 `conid`，也不判断用户能否下单。真实数据直接来自交易所、监管机构和正规第三方。接口按“国家证券目录、法定/交易所披露、新闻、ETF 目录、ETF 专属披露”计数，不把同一主上市证券经过的每个 MTF/ATS 路由伪装成独立发行人接口。

| 地区 | 国家 / 参考场所 | 证券目录 | 公司披露 | 仍缺少的核心国家轨道 |
|---|---:|---|---|---|
| 美洲 | 3 / 31 | 2 partial、1 stub | 2 live、1 partial | 加拿大 SEDAR+ 完整性/NEO；墨西哥官方证券目录；美国 OTC/Pink |
| 欧洲 | 19 / 44 | 13 live、4 partial、2 stub | 12 live、6 partial、1 unavailable | CH/IL/MX 的证券主数据；SE/HU 已接官方边界目录但不含其他场所/退市历史；AT/NL 等法定披露仍非全文件；RU 仅只读 |
| 亚洲 | 6 / 12 | 2 live、3 partial、1 unavailable | 5 live、1 partial | 日本股票全目录/PTS；SGXNET 全市场发现；香港/台湾完整证券目录 |

全局自动报告当前为：证券目录 **15 live、9 partial、3 stub、1 unavailable**；公司披露 **19 live、8 partial、1 unavailable**；新闻 **27 live、1 unavailable**；ETF 目录 **3 live、14 unknown、11 unavailable**；ETF 专属披露仍为 **28 unavailable**。详细到每个国家和场所的表见 [全球市场覆盖报告](docs/GLOBAL_MARKET_COVERAGE_STATUS_ZH.md)。

本 PR 已补：美国 Nasdaq Trader 官方股票/ETF 目录健壮性、日本 JPX 官方 ETF 目录、加拿大 CEO.ca SEDAR PDF 镜像（第三方 partial）、新加坡 StocksSG 公司目录（第三方 partial），并修正英国覆盖统计。仍未完成的项目及其授权/WAF/完整性原因在覆盖报告第 7–8 节列出。

Web 界面为英文，包含三个固定列表：

- Holdings（持仓）
- Planned Purchases（计划买入）
- Watchlist（观察列表）

同一家公司可属于上述任意组合。一份 SEC 申报只存储一次，并在所有适用列表徽章下展示，因此属于多个列表不会重复存储申报记录。

## 已接入能力

| 信息类型 | Provider | 生产状态 |
| --- | --- | --- |
| Filings | SEC EDGAR | 近期同步后为最新；超过 36 小时视为过期 |
| News | Finnhub company news | 成功同步后已接入；需配置 `FINNHUB_API_KEY` |
| Community | CEO.ca (CA) LIVE；Seeking Alpha (US) LIVE RSS；Substack (US) LIVE publication-whitelist RSS；Yellowbrick Investing (US) stub；X (US) stub；HotCopper (AU) stub；LSE Share Chat (UK) stub；Xueqiu (CN/HK) stub | CA/US 社区已接入（SA 为公开 article/news RSS，非论坛；Substack 为 LIVE publication-whitelist article/news 元数据，无结构化 ticker 绑定）；Yellowbrick / X 为 stub（无稳定公开 login-free surface；X 官方 API 需付费 Bearer，本连接器未接线 key 路径）；AU/UK/CN/HK 为 stub |
| Research | None | 未接入 |

仓库中仍保留用于自动化可扩展性测试的 mock 连接器。它们未在 `config/settings.yaml` 中启用，生成的 mock 数据也不会进入生产 Web 信息流。未来的真实 community 连接器将使用独立的 `source` 名称与 `source_type="community"`，不会被标注为 SEC。

## 新手入门

打开 Terminal 并进入项目：

```bash
cd "/Users/jiajunliu/Documents/New project/investment-monitor"
```

检查 Python（需 3.9 或更高版本）：

```bash
python3 --version
```

项目无第三方运行时依赖。SEC 要求自动化客户端声明应用名称与真实联系邮箱。一次性创建本地环境文件：

```bash
cp .env.example .env
```

打开 `.env`，将 `your-email@example.com` 替换为真实联系地址。Web 服务会自动加载该文件，且不会覆盖托管平台提供的环境变量。SEC 连接器保留超时、重试、缓存及每秒最多五次请求的限制。若映射缓存刷新暂时失败，将使用最后一次有效的本地副本。

## 1. 配置初始标的池

编辑 `config/universe.csv`：

```csv
ticker,list_type,market
AAPL,holdings,us
```

CSV 仅用于初始导入。接受 1–10 行唯一的 (ticker, market) 组合，`list_type` 必须为 `holdings`、`planned` 或 `watchlist`。可选列 `market` 接受 `us`、`cn`、`hk` 或 `unknown`，默认为 `us`。首次 Web 启动后，SQLite 中的活跃成员关系为集合的权威来源；在 Web 界面添加的公司（如 NVDA）无需再写入 CSV。

`config/settings.yaml` 声明逻辑数据源（sec、news、community、research）、启用状态，并选择本地 SQLite 文件：

```yaml
database_path: ../data/investment_monitor.sqlite3
sources:
  - name: sec
    label: SEC EDGAR
    source_type: filings
    enabled: true
  - name: news
    label: News
    source_type: news
    enabled: true
  - name: community
    label: Community
    source_type: community
    enabled: false
  - name: research
    label: Research
    source_type: research
    enabled: false
```

News 数据源为 Finnhub 公司新闻。在 `.env` 中设置 `FINNHUB_API_KEY`（见 `.env.example`）以启用；无密钥时该源保持 Not connected 并在采集时跳过。非 US 市场（cn/hk）在可能时映射为 Finnhub 符号（`.HK`、`.SS`/`.SZ`）；绝不使用 SEC 映射来伪造 A 股或港股解析。

### 美国数据源（US）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| sec | filings | none (EDGAR) | Official SEC company filings |
| news / Finnhub | news | `FINNHUB_API_KEY` | US company news |
| yahoo_us | news | none | Yahoo Finance US public RSS; may be loosely related and break without notice |
| google_news_us | news | none | Key-free Google News RSS search (`hl=en-US&gl=US&ceid=US:en`); may be loosely related and break without notice |
| seeking_alpha | community | none | **LIVE** public combined RSS `https://seekingalpha.com/api/sa/combined/{SYMBOL}.xml` (spike 2026-08-11; `tests/fixtures/seeking_alpha/SPIKE.md`). Article/news metadata only (`MarketCurrent` + `Article`); ~30-item rolling window; America/New_York day filter; stdlib urllib, no cookie. HTML symbol/forum/comments pages return PerimeterX 403 — out of scope. **Not** forum discussion posts. |
| substack | community | none | **LIVE** publication-whitelist article/news metadata via public RSS (`https://{publication}/feed`; spike 2026-08-11; `tests/fixtures/substack/SPIKE.md`). stdlib urllib, no cookie. Default whitelist: noahpinion.blog, notboring.co, astralcodexten.com, paulkrugman.substack.com, oneusefulthing.org. America/New_York calendar-day filter. **No structured ticker binding:** optional client-side keyword match (best-effort, false positives/negatives). Category is newsletter article/news metadata, **not** forum/discussion posts. Whitelist requires maintenance against off-platform publication migration. |
| yellowbrick | community | none | Yellowbrick Investing (US) social stock-pitch community. **Honest stub:** no stable public login-free surface (spike 2026-08-11; `tests/fixtures/yellowbrick/SPIKE.md`): `ybrick.co` dead (DNS/transport error); `joinyellowbrick.com/stocks`, `/ideas`, `/pitches` all return HTTP 404; Substack is waitlist-only. `collect()` returns `[]`. Login/Supabase-key scraping out of scope. |
| x_community | community | `X_BEARER_TOKEN` | X (formerly Twitter) US social post stream. **LIVE (requires `X_BEARER_TOKEN`):** uses official X API v2 `GET /2/tweets/search/recent` with cashtag `$TICKER` + day window, returning structured post items (`id` / `created_at` / `text` / deeplink, plus `community_id` when present). No key-free discovery path exists: `x.com` search/Communities/profile timelines are client-rendered SPA shells behind a login wall for urllib; Nitter mirrors are dead/bot-walled; key-free oEmbed/syndication need a known tweet id and cannot search by ticker. Without a token the source stays Not connected. Category: social post stream (not forum/article). |
| vic | community | none | Value Investors Club (US) investment-idea club. **Honest stub (Stub·STOP):** no stable public login-free ticker+day surface (spike 2026-08-11; `tests/fixtures/vic/SPIKE.md`): `/feed` `/rss` `/api/ideas` `/sitemap.xml` return HTML shells (not RSS/JSON); `/ideas?symbol=TICKER` does not filter (identical idea-href set for MSFT/AAPL/bare `/ideas`); homepage free signup only unlocks **45-day delayed** guest ideas; membership/login and HTML catalog scrape out of scope. `collect()` returns `[]`. Category if ever LIVE: club investment-idea write-ups (not forum/article RSS). |

US feed Community 软去重：Seeking Alpha 用 `content_id`（或同源 scoped 标题回退）；Substack 用稳定 post id（`external_id` = `substack-{guid}`）或同源 scoped 标题回退（ticker + New York day + normalized title）。Yellowbrick / X / VIC 为 stub，`collect()` 无行，不产生去重键。News 软去重（仅展示）：`yahoo_us` / `google_news_us` / Finnhub（`news`，market=us）按 ticker + New York day + normalized title 配对；SEC filings 永不跨源标注。

### 韩国数据源（KR）

- OpenDART（`DART_API_KEY`）：官方披露 API；corp_code 映射与披露列表。
- KIND（KRX）：免密钥的交易所披露页抓取；可能随时失效。
- Naver Finance（`naver_news`）：免密钥的股票新闻抓取；脆弱，非 KR 网络可能为空。Hankyung/TheBell 已实现但暂禁用，直至其端点可访问。
- Yahoo Finance KR（`yahoo_kr`）/ Google News KR（`google_news_kr`）：免密钥 RSS；请求时加 `.KS`/`.KQ` 后缀；可能 loosely related 且随时失效。
- 可交易标的池：缓存自 OpenDART corpCode 列表；ETF/ETN 覆盖不完整。FSC/data.go.kr 因注册需韩国身份而跳过。
- Feed 软去重（默认开启，`KR_FEED_SOFT_DEDUPE`）：共享 14 位受理编号的 OpenDART/KIND 条目在 feed 中标注 "Also seen on"；所有行保留（总数不变）。News：`naver_news` / `yahoo_kr` / `google_news_kr` / Finnhub（`news`，market=kr）跨源按 ticker + Seoul day + normalized title 配对。

### 英国数据源（UK）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| companies_house | filings | `COMPANIES_HOUSE_API_KEY` — Test app keys authenticate only against `https://api-sandbox.company-information.service.gov.uk`; Live keys use the default live API | Statutory company filings (accounts, officers), **not RNS** |
| investegate | filings | none | RNS-class public mirror, not an official LSEG RNS feed; page scrape, may break without notice |
| uk_universe / FIRDS | breadth cache | none | No ticker mnemonics; ISIN-keyed plus a small blue-chip ticker seed; never enters the feed |
| yahoo_uk | news | none | Free public RSS mirror; may be loosely related and fragile; `.L` suffix added at request time only |
| google_news_uk | news | none | Key-free Google News RSS search (`hl=en-GB&gl=GB&ceid=GB:en`); may be loosely related and break without notice |
| lse_share_chat | community | none | LSE.co.uk Share Chat. **Honest stub:** HTTP 403 to automated clients; official LSE gateway probes and discussion/news/RNS pages do not expose anonymous post rows (spike 2026-08-12; `tests/fixtures/lse_share_chat/SPIKE.md`). `collect()` returns `[]`. Investegate RNS is a separate existing source, not community chat. Login/paywall out of scope. |
| Finnhub | news | existing | **US only** — never queried for UK |

UK feed 软去重（仅展示，保留所有行）：filings 在 RNS id（Investegate）或 Companies House transaction id 上标注；标题回退仅限同源，Companies House 与 Investegate 不会因标题交叉标注。News：`yahoo_uk` / `google_news_uk` 跨源按 ticker + London day + normalized title 配对。Community 软去重使用 LSE Share Chat thread id（或同源 scoped 标题回退）；当前仅 `lse_share_chat` 时无跨源 community 配对 — 同源重复仍可显示 "Also seen on"。

### 香港数据源（HK）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| hkexnews | filings | none | HKEX official public Title Search frontend JSON contract; undocumented, fully paged and fail-closed |
| hk_universe | breadth cache | none | HKEXnews active/inactive stock lists; never enters the feed |
| yahoo_hk | news | none | Yahoo Finance HK public RSS; `.HK` at request time |
| google_news_hk | news | none | Key-free Google News RSS search (`hl=zh-HK&gl=HK&ceid=HK:zh-Hant`); may be loosely related and break without notice |
| hkex_di | filings | none | Legacy DI archive 2003–2017; **disabled by default**; fragile |
| xueqiu | community | none | Xueqiu (雪球) CN/HK statuses. **Cookie‑backed LIVE** when `XUEQIU_COOKIE=xq_a_token` is set in `.env`; otherwise honest stub (`collect()` returns `[]`). JSON API `statuses/search.json` returns structured posts with id/title/timestamp/deeplink. Login/WAF bypass out of scope. |

HK ticker 规范为五位代码（`700` / `0700` / `00700.HK` → `00700`）；Xueqiu 社区符号为 `HK` + 五位代码（`0700` → `HK00700`）。Finnhub **仅 US**。软去重：hkexnews 按 NEWS_ID，hkex_di 按 form serial（标题永不交叉配对）；`yahoo_hk` / `google_news_hk` news 跨源按 ticker + Hong Kong day + normalized title 配对。Community 软去重使用 Xueqiu status id（或同源 scoped 标题回退）。

### 中国大陆数据源（CN）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| xueqiu | community | none | Xueqiu (雪球) CN statuses. **Cookie‑backed LIVE** when `XUEQIU_COOKIE=xq_a_token` is set in `.env`; otherwise honest stub (`collect()` returns `[]`). JSON API `statuses/search.json` returns structured posts with id/title/timestamp/deeplink. Login/WAF bypass out of scope. |

CN 股票以未映射方式添加（无 SEC 映射）；Xueqiu 社区符号为 `SH`/`SZ` + 六位代码（`600519` / `600519.SS` / `SH600519` → `SH600519`；`000001.SZ` → `SZ000001`）。Finnhub **仅 US**。Community 软去重使用 Xueqiu status id（或同源 scoped 标题回退）。

### 加拿大数据源（CA）

**非完整加拿大市场轨道。** 当前已接入：TSX/TSXV universe、CSE 官网公开全证券目录及逐发行人 filing mirror、公司自有 IR feed、加拿大双重上市公司的 SEC EDGAR 补漏、CEO.ca discovery 镜像。**未接入：** SEDAR+ 官方全量和 NEO 全量；加拿大在完成监管全量对账前最高只能评为 `high`。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| ca_universe | breadth cache | optional `CA_CSE_UNIVERSE_EXPORT_PATH`, `CA_UNIVERSE_OVERLAY_PATH` | TSX + TSXV 使用免费官方 TMX JSON；CSE 使用官网自己调用的 `website-data-api-v2.thecse.com/api/companies/all`，严格校验全量规模、ID、状态、退市日期和 recycled symbol，并保留官方离线 export/overlay 兜底；NEO 仍未完成。 |
| ca_ir | filings | `CA_IR_CONFIG_PATH` | Tier 2 公司官方 IR；严格 allowlist，支持 RSS/Atom、公开 JSON、Sitemap、HTML adapter；仅保存公告元数据/官方链接与附件，滚动 feed 固定为 partial。 |
| ca_edgar | filings | `SEC_USER_AGENT`, `CA_EDGAR_IDENTITY_PATH` | Tier 1 美国监管补漏；只接受人工审核的 CA ticker/exchange→US ticker/CIK 映射，采集 6-K/40-F/20-F/F-10/8-K 及附件；明确标记 US regulator / non-SEDAR。 |
| cse_filings | filings | none | **CSE official exchange mirror / CA partial**：由 CSE universe 精确解析官方 security JSON → `sedar_filings/{issuer-id}.json` → CSE 托管 PDF；校验发行人、symbol、category 总数、accession、状态和日期，保留 removed revision，单发行人失败不抹掉其他结果。仅覆盖 CSE，不冒充 SEDAR+ 全国主链。 |
| yahoo_ca | news | none | Yahoo Finance CA public RSS (`region=CA`, `lang=en-CA`); `.TO` at request time (`.V` for TSXV boards from the universe cache, otherwise `.TO`); may be loosely related and break without notice |
| google_news_ca | news | none | Key-free Google News RSS search (`hl=en-CA&gl=CA&ceid=CA:en`); may be loosely related and break without notice |
| ceoca_ca | community | none | CEO.ca channel spiels via key-free JSON API (`new-api.ceo.ca`; spike 2026-08-11). API returns ~50 spiels/page (`limit` ignored); paginate with `until`. Toronto calendar-day filter; channel page URL only — no per-spiel deep link. Undocumented API may change without notice. |
| ceoca_sedar | filings | none | **partial**：按请求 ticker 读取 CEO.ca 公司频道中的 `#sedar` bot 消息并保留实际 PDF 深链接，不扫描全局 SEDAR 历史；只接受精确 bot 身份、消息格式和 `ceo.ca/content/sedar/*.pdf`，日期最多 31 天且分页上限会失败关闭。这是 SEDAR+ 的第三方镜像，端点未文档化且无法证明无漏页，所以绝不标 official/live。 |
| sedar_plus / neo_filings | filings | — | SEDAR+ 公共站条款禁止自动批量抓取及据此建立数据库；官方可行路径是 ASC/CSA 许可的 bulk/ad-hoc 数据分发。未取得书面许可、凭据和数据合同前不接入；Cboe Canada/NEO 仍缺本任务允许的免费完整 issuer-filing 主链。 |

`market=ca` 公司使用规范根 ticker（`RY` / `RY.TO` / `RY-TO` 均存为 `RY`）。Board 在 universe 温热时由 `ca_universe_name_map()` 写入 `exchange`，冷启动时从输入后缀推断。公司保持 unmapped。Finnhub **仅 US**，不对 CA 查询。

CA feed 软去重只做关联、不删除来源行：Filing 优先使用 canonical id、官方 ID/URL、文件哈希，再使用 ticker + Toronto day + normalized title 的相似键；`yahoo_ca` / `google_news_ca` news 继续按 ticker + Toronto day + normalized title 配对。CEO.ca 始终保留 Tier 4 mirror 身份。

### 台湾数据源（TW）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| twse_material | filings | none | TWSE OpenAPI material-information for **listed companies only**; key-free; OTC via tpex_material; 興櫃 not wired |
| tpex_material | filings | none | TPEx OpenAPI material-information for **OTC (上櫃)**; 興櫃 not wired |
| mops_disclosures | filings | none | Official MOPS company/month history plus detail endpoint; covers the material-disclosure family, not every MOPS file family |
| tw_universe | breadth cache | none | TWSE listed + TPEx OTC directories; emerging opt-in via env only; never enters the feed |
| yahoo_tw | news | none | Yahoo Finance TW public RSS (`region=TW`); `.TW`/`.TWO` at request time from board; may break without notice |
| google_news_tw | news | none | Key-free Google News RSS (`q={ticker}.TW`, zh-TW); may break without notice |

`market=tw` 使用规范四位 ticker（`2330` / `02330` / `2330.TW` → `2330`）。Finnhub **仅 US**。软去重：TWSE/TPEx filings 仅同源（标题永不跨板配对）；news 按 ticker + Taipei day + normalized title 配对。

### 澳大利亚数据源（AU）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| asx_announcements | filings | none | Official ASX historical company-announcement archive, queried by company and calendar year |
| au_universe | breadth cache | none | ASX company directory; never enters the feed |
| yahoo_au | news | none | Yahoo Finance AU public RSS (`region=AU`); `.AX` at request time |
| google_news_au | news | none | Key-free Google News RSS (`hl=en-AU&gl=AU&ceid=AU:en`) |
| hotcopper_au | community | none | HotCopper ASX ticker boards. **Honest stub:** HTTP 403 Cloudflare on public pages (spike 2026-08-11; re-probe 2026-08-12; `tests/fixtures/hotcopper/SPIKE.md`). `collect()` returns `[]` until a stable public day-filter feed exists. Login/paywall out of scope. |
| stockhead_au | community | none | Stockhead.com.au ASX news/analysis. **LIVE** (spike 2026-08-12): WordPress search RSS `/?s={TICKER}&feed=rss2` returns ticker-tagged articles (`CompanyName - TICKER` category). 50-item rolling window; URL slug as external ID. Independent source — not a substitute label for HotCopper. |

`market=au` 使用规范根 ticker（`BHP` / `BHP.AX` → `BHP`）。Finnhub **仅 US**。软去重：ASX filings 按 document key 配对（或同源标题回退）；news 按 ticker + Sydney day + normalized title 配对。Community：`stockhead_au` 按 article slug 配对（独立于 `hotcopper_au` stub）；HotCopper thread id 软去重仅在同源重复时显示 "Also seen on"。

### 法国数据源（FR）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| amf_oam | filings | none | AMF OAM information feed (key-free; undocumented page API; may change); only wired FR disclosure source |
| fr_universe | breadth cache | none | Euronext live all-stocks CSV (Paris / Growth Paris / Access Paris); never enters the feed |
| yahoo_fr | news | none | Yahoo Finance FR public RSS (`region=FR`); `.PA` at request time |
| google_news_fr | news | none | Key-free Google News RSS (`hl=fr&gl=FR&ceid=FR:fr`) |

`market=fr` 使用规范根 ticker（`MC` / `MC.PA` → `MC`；法国 ISIN 原样保留）。Add-company 在 universe 温热时可从 `fr_universe_name_map()` 回填 name/board。Finnhub **仅 US**。软去重：AMF filings 按 OAM document id 配对（或同源标题回退）；news 按 ticker + Paris day 配对。

### 德国数据源（DE）

德国 ETF 深化沿用现有 `market=de` 代码 — **无** `market=etf` / `de_etf` / `xetra_etf`。目标为 Xetra / Deutsche Börse Cash Market ETF（及同 CSV 的 ETN/ETC）工具，与现有普通股（CS）universe 并存；**非** Eurex 衍生品，**非**付费 Deutsche Börse 数据产品。最终状态：universe 现接受 CSV Instrument Types `CS`、`ETF`、`ETN`、`ETC`（同属 Xetra / Deutsche Börse Cash Market 交易所家族），每条记录存储 `instrument_type`，CSV 本身为 Cash Market 文件，不含 Eurex 衍生品。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_dgap | filings | none | EQS News JSON (ex-DGAP; key-free unofficial WP API; may change); only wired DE disclosure source; matched by ISIN. **DETF-1 live (2026-08-10): returns 0 records for sampled DE-domiciled Xetra ETF ISINs** (iShares Core DAX `DE0005933931`, iShares DivDAX `DE0002635273`, Deka DAX `DE000ETFL011`, iShares Core DAX EOD `DE000A2QP331`, iShares STOXX Europe 600 `DE0002635307`) — ETF disclosure is **not** deepened; EQS stays equity-side and the connector honestly returns empty. The EQS host also shows intermittent TLS EOFs (same host quirk as other EQS rails). No paid fund-document feed is wired. |
| de_etf_second_disclosure | filings | none | **Not wired (DETF-4 re-verified 2026-08-10)**: no stable key-free German ETF-specific disclosure/prospectus feed exists. BaFin prospectus portal path returns HTTP 404 for non-browser clients, Bundesanzeiger redirects to a session/JS wall (HTTP 302, no per-ISIN JSON), and EQS returns empty for ETF ISINs. Paid Xetra ETF data packs / Eurex products are deliberately not wired; no hand-written ETF seed is used. |
| de_universe | breadth cache | none | Xetra `t7-xetr-allTradableInstruments.csv` **CS + ETF + ETN + ETC** (DETF-2; live 2026-08-10: 5,094 active XETR rows → CS 1,422 / ETF 3,082 / ETN 385 / ETC 205; each entry carries `instrument_type`, counts exposed as `counts` by board and `counts_by_type`); never enters the feed; backfills name/board/ISIN on add-company and for EQS ISIN matching |
| yahoo_de | news | none | Yahoo Finance DE public RSS (`region=DE`); `.DE` at request time; shared by stocks and ETFs (DETF-3 live 2026-08-10: `EXS1.DE` / `EXSB.DE` return HTTP 200 but usually empty ETF feeds) |
| google_news_de | news | none | Key-free Google News RSS (`hl=de&gl=DE&ceid=DE:de`); shared by stocks and ETFs (DETF-3 live: `EXS1.DE` returns items; may be loosely related) |

`market=de` 使用规范根 ticker（`SAP` / `SAP.DE` → `SAP`；德国 ISIN 原样保留）。Add-company 在 universe 温热时可从 `de_universe_name_map()` 回填 name/board/ISIN；ETF/ETN/ETC 工具共用同一 market 代码与 ticker 规则（无独立 etf market code），由 universe 缓存中的 `instrument_type` 区分。Finnhub **仅 US**。软去重：EQS filings 按 news id 配对（或同源标题回退）；news 按 ticker + Berlin day 配对。Unternehmensregister / BaFin HTML 门户 **未接入**（无稳定免费 JSON）。

### 荷兰数据源（NL）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| afm_nl | filings | none | AFM 官方 MAR Article 17 内幕信息登记册。调用官网公开 `PagedRegisters` HTML 端点，按 `DD-MM-YYYY` 日期窗读取，逐页核验 50 条 page size、active page、总数、唯一 AFM ID、日期边界和结构；只有明确 total=0 才是 empty。未匹配法定名称进入 pending，不能冒充荷兰全部年度报告/招股书/OAM 文件。 |
| eqs_nl | filings | none | EQS News JSON by Dutch ISIN (key-free unofficial WP API, Tier 3 supplement); needs ISIN from the NL universe cache or a typed Dutch ISIN. It remains partial and is never labelled AFM/official regulatory coverage. |
| nl_universe | breadth cache | none | Euronext live all-stocks CSV filtered to Amsterdam segment rows (key-free; live 2026-08-10: ~119 `Euronext Amsterdam` + ~16 multi-venue rows mentioning Amsterdam, e.g. `Euronext Amsterdam, Brussels`; non-Amsterdam boards, Global Equity Market, Trading After Hours and EuroTLX excluded); not a complete national universe; never enters the feed. |
| yahoo_nl | news | none | Yahoo Finance NL public RSS (`region=NL`, `lang=nl-NL` + `en-US` merged); `.AS` at request time; may be loosely related and break without notice |
| google_news_nl | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=nl&gl=NL&ceid=NL:nl`); may be loosely related and break without notice |

`market=nl` 公司使用规范根 ticker（`ASML` / `ASML.AS` / `ASML-AMS` 均存为 `ASML`；交易所后缀 `.AS` / `.AMS` / `.AEA` 在添加时剥离，荷兰 ISIN 原样保留，board 可用时写入 `exchange`）并保持 unmapped；`nl_universe_name_map()` 为 add-company 回填 name、board 与 ISIN。Finnhub **仅 US**，不对 NL 查询。News 来自 `yahoo_nl` / `google_news_nl`。

NL feed 软去重（仅展示，保留所有行；与其他市场共用 `KR_FEED_SOFT_DEDUPE` 开关，默认开启）：`yahoo_nl` / `google_news_nl` news 跨源按 ticker + Amsterdam day（`Europe/Amsterdam`）+ normalized title 配对。AFM 优先使用官方登记编号，EQS 使用自身平台 ID；无原生 ID 时才允许受信来源按 ticker + Amsterdam day + normalized title 回退。每行保留在 feed 中并标注 "Also seen on …"；总数与分页大小永不缩减。

### 意大利数据源（IT）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_it | filings | none | EQS News JSON by Italian ISIN (key-free, unofficial WP API — may change; partial Italian-issuer coverage; empty for issuers not on the platform; NOT a Consob official feed). Consob public registers and Borsa Italiana/Euronext Milan announcement pages are not wired (no stable key-free JSON). IT-4 re-verified (2026-08-10): Consob serves a Radware captcha wall, Borsa Italiana is HTML-only, Euronext Milan announcement pages use antibot HTML — no second free disclosure source. Needs ISIN from the IT universe cache or a typed Italian ISIN. |
| it_universe | breadth cache | none | Euronext live all-stocks CSV filtered to Milan segment rows (key-free; live 2026-08-10: ~204 `Euronext Milan` + ~243 `Euronext Growth Milan`; filter also accepts `Borsa Italiana`/`Milano` labels if they ever appear; non-Italian boards, Global Equity Market, Trading After Hours and EuroTLX excluded); not a complete national universe; never enters the feed. |
| yahoo_it | news | none | Yahoo Finance IT public RSS (`region=IT`, `lang=it-IT` + `en-US` merged; identical titles stay single-language); `.MI` at request time; may be loosely related and break without notice |
| google_news_it | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=it&gl=IT&ceid=IT:it`); may be loosely related and break without notice |

`market=it` 公司使用规范根 ticker（`ENI` / `ENI.MI` / `ENI-MIL` 均存为 `ENI`；交易所后缀 `.MI` / `.MIL` / `.BIT` 在添加时剥离，意大利 ISIN 原样保留，board 可用时写入 `exchange`）并保持 unmapped。Finnhub **仅 US**，不对 IT 查询。`it_universe_name_map()` 为 add-company 回填 name、board 与 ISIN。News 来自 `yahoo_it` / `google_news_it`。

IT feed 软去重（仅展示，保留所有行；与其他市场共用 `KR_FEED_SOFT_DEDUPE` 开关，默认开启）：`yahoo_it` / `google_news_it` news 跨源按 ticker + Rome day（`Europe/Rome`）+ normalized title 配对。`eqs_it` filings 按稳定 EQS news id 配对，或同源标题回退（ticker + Rome day + normalized title）；仅接入一个披露源时无跨源 filing 配对。每行保留在 feed 中并标注 "Also seen on …"；总数与分页大小永不缩减。

### 西班牙数据源（ES）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| cnmv_hr | filings | none | CNMV official relevant-information RSS — inside information (IP) + other relevant information (OIR) feeds (key-free, official; live 2026-08-10). Records are keyed by issuer legal name (`Title`) with a stable `nreg` registration number; matched to requested tickers via the ES universe name/ISIN. The IP feed is sometimes empty for a day (honest `[]`). Not a paid MOPS-style push. |
| bme_relevant_facts | filings | none | Official BME relevant-facts JSON API (key-free; live 2026-08-10; same API family as the ES universe). Matched per company via the universe `companyKey`; records carry the same stable CNMV registration numbers (`IP`/`OI` prefixes) and CNMV detail deep links; date-only records use the Europe/Madrid noon anchor. The API clamps the requested range to at most ~31 calendar days, so older history is not available. Paid BME real-time/historical data services are deliberately not wired (ES-4 re-verified 2026-08-10). |
| es_universe | breadth cache | none | Official BME equity API (key-free; live 2026-08-10): `SIBE` (~123) + `Floor` (~5) + `Latibex` (~14) kept in full; `MTF` filtered to `BMEGrowth` (~111) + `BMEScaleUp` (~52); funds (SICAV/HedgeFunds/VCC) and other non-equity rows excluded. Tickers are enriched per ISIN from `ShareDetailsInfo` (rate-limited; reuses cached tickers; failed entries stay until next refresh). BME is a SIX company — the Euronext CSV family is NOT reused and no Madrid segment exists there. Not a complete national universe; never enters the feed. |
| yahoo_es | news | none | Yahoo Finance ES public RSS (`region=ES`, `lang=es-ES` + `en-US` merged; identical titles stay single-language); `.MC` at request time; may be loosely related and break without notice |
| google_news_es | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=es&gl=ES&ceid=ES:es`); may be loosely related (the `.MC` suffix also matches unrelated "MC" text) and break without notice |

`market=es` 公司使用规范根 ticker（`SAN` / `SAN.MC` / `SAN-MAD` 均存为 `SAN`；交易所后缀 `.MC` / `.MAD` / `.BME` 在添加时剥离，西班牙 ISIN 原样保留，board 可用时写入 `exchange`）并保持 unmapped。Finnhub **仅 US**，不对 ES 查询。`es_universe_name_map()` 为 add-company 回填 name、board 与 ISIN；披露匹配使用 universe 身份（CNMV 用 name/ISIN，BME 用 company key）。News 来自 `yahoo_es` / `google_news_es`。

ES feed 软去重（仅展示，保留所有行；与其他市场共用 `KR_FEED_SOFT_DEDUPE` 开关，默认开启）：`yahoo_es` / `google_news_es` news 跨源按 ticker + Madrid day（`Europe/Madrid`）+ normalized title 配对。`cnmv_hr` filings 按稳定 CNMV 注册号（`es:filing:cnmv:...`）配对，`bme_relevant_facts` 按 BME JSON 中同一注册号（`es:filing:bme:...`）配对；两源永不交叉标注（独立 API），标题回退为 source-scoped（ticker + Madrid day + normalized title）。每行保留在 feed 中并标注 "Also seen on —"；总数与分页大小永不缩减。

### 新加坡数据源（SG）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| sgx_announcements | filings | `SGX_KNOWN_ANNOUNCEMENTS_PATH` | **partial**：解析经审核的 `links.sgx.com/1.0.0/corporate-announcements/{id}` 已知官方详情及多附件，保存 SGX reference、SGT 时间、证券身份和发现来源。绝不调用或重放 SPA `authorizationToken`，因此不能枚举完整 SGXNET。 |
| sg_ir | filings | optional `SG_IR_CONFIG_PATH` | **partial**：默认内置已审计的 Singtel Stock Exchange Announcements（公开 JSON datamodel，约 1,975 条 live 历史记录）和 OCBC Major Regulatory Announcements（2001 起公开日期/PDF档案）；另支持配置驱动的 RSS/Atom、公开 JSON、Sitemap、HTML、ListedCompany/ShareInvestor。所有 URL 走 HTTPS host/path allowlist，发行人官网为 Tier 2。UOB ListedCompany 现场为 WAF challenge，未绕过。 |
| sg_edgar | filings | `SEC_USER_AGENT`, `SG_EDGAR_IDENTITY_PATH` | **partial supplement**：仅对人工审核的 SG/US 双重上市映射读取 SEC 6-K、20-F、F-1、F-3、8-K 及附件；明确标记为美国监管文件，不冒充 SGX 公告。 |
| sg_universe | breadth cache | none | **partial**：从正规新加坡第三方 StocksSG 的公开 `/api/v1/companies` 目录读取 ticker、公司名、UEN、board、ISIN、LEI；校验响应总数、重复 ticker 和最小规模后原子写缓存。现场接口仅约 183 行，明显不能证明 SGX 全量，因此不标 official/live；缓存永不进入信息 feed。 |
| yahoo_sg | news | none | Yahoo Finance SG public RSS (`region=SG`, `lang=en-SG` + `en-US` merged; identical titles stay single-language); `.SI` at request time; may be loosely related and break without notice |
| google_news_sg | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=en-SG&gl=SG&ceid=SG:en`); may be loosely related and break without notice |

`market=sg` 公司使用规范根 ticker（`D05` / `D05.SI` / `D05-SG` 均存为 `D05`；交易所后缀 `.SI` / `.SG` 在添加时剥离，新加坡 ISIN 原样保留；SGX 代码长度不一，不假设固定位宽）。目录缓存温热时可回填名称、board 与 ISIN；冷启动仍保持 unmapped。Finnhub **仅 US**，不对 SG 查询。News 来自 `yahoo_sg` / `google_news_sg`，不会进入 Filing。MAS OPERA 检索需要图形 CAPTCHA，因此只作人工核对，不自动化。SG 覆盖最高为 `high`；没有可枚举的 SGXNET 主链时绝不标 `complete`。

### 瑞士数据源（CH）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_ch | filings | none | EQS News JSON by Swiss ISIN (key-free, unofficial public WP API; may change without notice; **partial Swiss coverage** — live 2026-08-10 Roche/UBS return records, Nestlé/Novartis return empty lists; NOT a SIX Exchange Regulation / FINMA official feed). SIX official channels have no stable free JSON (official-notices page is a React SPA; `api.six-group.com` routes undocumented; SIX equity-issuer news is the paid Exfeed product) — CH-4 re-verified 2026-08-10, no second disclosure source. Needs ISIN from the CH universe cache or a typed Swiss ISIN. |
| ch_universe | breadth cache | none | **Boundary stub (CH-2 spike B2)**: no stable key-free SIX securities directory exists (`six-group.com/market-data/shares/*` are React SPAs; share-explorer detail pages expose name/ticker/ISIN in meta tags but no board; `api.six-group.com` routes are undocumented 404s; SIX market-data APIs and the equity-issuer-news Exfeed product are paid). `load_ch_universe` / `ch_universe_name_map` / `search_ch_universe` read a local cache if one ever exists; `refresh_ch_universe` raises `ChUniverseError` instead of faking an SMI-only universe. Never enters the feed. |
| yahoo_ch | news | none | Yahoo Finance CH public RSS (`region=CH`, `lang=de-CH` + `en-US` merged; identical titles stay single-language); `.SW` at request time; may be loosely related and break without notice |
| google_news_ch | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=de&gl=CH&ceid=CH:de`; `de-CH`/`fr-CH`/`en` variants redirect, so the live-locked German-Swiss edition is used); may be loosely related and break without notice |

`market=ch` 公司使用规范根 ticker（`NESN` / `NESN.SW` / `NESN-SWX` 均存为 `NESN`；交易所后缀 `.SW` / `.SWX` / `.S` 在添加时剥离，瑞士 ISIN 原样保留）并保持 unmapped。Finnhub **仅 US**，不对 CH 查询。News 来自 `yahoo_ch` / `google_news_ch`。

CH feed 软去重（仅展示，保留所有行；与其他市场共用 `KR_FEED_SOFT_DEDUPE` 开关，默认开启）：`yahoo_ch` / `google_news_ch` news 跨源按 ticker + Zurich day（`Europe/Zurich`）+ normalized title 配对。`eqs_ch` filings 按稳定 EQS news id 配对，或同源标题回退（ticker + Zurich day + normalized title）；仅接入一个披露源时无跨源 filing 配对。每行保留在 feed 中并标注 "Also seen on —"；总数与分页大小永不缩减。

### 波兰数据源（PL）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `gpw_espi` | Filings | None (key-free) | Official GPW ESPI/EBI reports page (`www.gpw.pl/komunikaty`, server-rendered HTML list, ISIN-filterable via `searchText=` + `limit=`/`offset=`; live verified 2026-08-10). Matches by Polish ISIN from the PL universe cache (the list shows issuer name + ISIN, not ticker mnemonics); companies without a universe ISIN are skipped honestly (`no_universe_identity`). Europe/Warsaw day bounds; stable `geru_id` external ids; deep link to the report page (`komunikat?geru_id=...`, which also exposes attachment PDF paths). The PL-1 A3 boundary was based on `espi.gpw.pl` TLS failure and empty EQS records; PL-4 re-spike found this page reachable. `espi.gpw.pl` itself remains unreachable, EQS is still empty for sampled Polish ISINs, KNF has no per-issuer feed, and GPW paid data products are not used. |
| `pl_universe` | Universe | None (key-free) | Official GPW HTML directories, breadth only (never written to the feed): GPW Main Market (`www.gpw.pl/spolki?limit=403`, ~400 companies; observed 401–403 live 2026-08-10) and NewConnect (`newconnect.pl/spolki?limit=403`, ~350 companies; observed 348–349). Both are server-rendered tables with ISIN/name/mnemonic ticker; the old `lista-spolek*` URLs return a 404 shell and the `ajaxindex.php` search endpoint rejects non-browser clients, so only the public GET pages are used. The GPW hosts also drop TLS connections intermittently from this network (a refresh may need a retry; per-board partial failure keeps the other board and only a full failure raises `PlUniverseError`). No WIG20/WIG30 seed and no paid GPW data product. Refreshed via `refresh_pl_universe()`; `pl_universe_name_map()` backfills name/board/ISIN on add-company and drives `gpw_espi` disclosure matching. `market=pl` companies use canonical root tickers (`PKO` / `PKO.WA` / `PKO-GPW` all store as `PKO`; exchange suffixes `.WA` / `.WSE` / `.GPW` are stripped at add time, Polish ISINs are kept as-is) and remain unmapped. Finnhub is **US only** and never queried for PL. |
| `yahoo_pl` | News | None (key-free) | Yahoo Finance PL public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.WA&region=PL&lang=pl-PL`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`PKO`), `.WA` is request-time only. |
| `google_news_pl` | News | None (key-free) | Google News PL RSS (`news.google.com/rss/search?q={ROOT}.WA&hl=pl&gl=PL&ceid=PL:pl`). Live verified 2026-08-10; results can be loosely related (a `PKO.WA` query can include unrelated PKO BP Ekstraklasa football items); public RSS may break without notice. |

PL feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings：`gpw_espi` 按稳定 GPW report id（`geru_id`）配对；标题回退为 source-scoped（source + ticker + Warsaw day + normalized title），假设的第二 PL 披露源不会因标题交叉标注。News：`yahoo_pl` ↔ `google_news_pl` 跨源按 ticker + Warsaw day + normalized title 配对。

### 瑞典数据源（SE）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `nasdaq_se_filings` | filings | none | Nasdaq Nordic 官方 Company News：使用官方公司目录身份匹配 Main Market Stockholm / First North Sweden，再按公司和日期读取公告；保存 disclosure ID、语言、Stockholm 时间、分类、官方消息与附件。分页必须达到官方 count，目录或公告身份无法唯一匹配时失败关闭；单次查询最多回看 365 天。FI Insyn 不是发行人公告，EQS/Hugin 也未作为第二源。 |
| `se_universe` | Universe | none | Nasdaq Nordic 官方公开 Shares Screener，分别请求 `category=MAIN_MARKET/FIRST_NORTH`、`market=STO`，以 `data.pagination` 的 total/size/page/totalPages 对账，并验证每行 `assetClass=SHARES`。2026-08-24 live smoke：Main Market 412、First North 332，共 744 条；保存 ticker、ISIN、名称、currency、orderbook ID、板块和实际请求 URL。currency 只作审计字段，不排除 Stockholm 的 EUR 股票。NGM、Spotlight、其他场所和退市历史未覆盖，因此为 official partial；失败时原子保护旧缓存。 |
| `yahoo_se` | News | None (key-free) | Yahoo Finance SE public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.ST&region=SE&lang=sv-SE`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10 with `ERIC-B.ST`; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`ERIC-B`), `.ST` is request-time only; share-class mnemonics like `ERIC-B` / `VOLV-B` are kept intact. |
| `google_news_se` | News | None (key-free) | Google News SE RSS (`news.google.com/rss/search?q={ROOT}.ST&hl=sv&gl=SE&ceid=SE:sv`). Live verified 2026-08-10; results can be loosely related (an `ERIC-B.ST` query can include football items about a player named Eric Smith); public RSS may break without notice. |

`market=se` 公司使用规范根 ticker（`ERIC-B` / `ERIC-B.ST` / `eric-b.sto` 均存为 `ERIC-B`；交易所后缀 `.ST` / `.STO` / `.OMX` / `-ST` 等在添加时剥离，股份类别后缀如 `-B` / `-A` 保留，瑞典 ISIN 原样保留）。Web 冷缓存首次添加会安全刷新官方目录并回填 name/board/ISIN；刷新失败保留 unmapped，不影响添加。Finnhub **仅 US**，不对 SE 查询。

SE feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 SE 披露连接器（SE-1 A3 / SE-4 D2）。News：`yahoo_se` ↔ `google_news_se` 跨源按 ticker + Stockholm day + normalized title 配对。

### 比利时数据源（BE）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `fsma_stori` | Filings | None (key-free) | Official FSMA STORI (Belgian central storage of regulated information, `webapi.fsma.be/api/v1/<lang>/stori/result`; powers the public `fsma.be/en/stori` portal). Matches by Belgian ISIN or company name — never by ticker mnemonic (`ABI` does not match `AB INBEV`). A BE ISIN typed as the ticker works now; mnemonic tickers get an ISIN/name from the BE universe cache (BE-2) once it is refreshed and are otherwise skipped honestly (`no_universe_identity`). Europe/Brussels day bounds, stable document ids (`requiredReportingTopicId`), dates constrained server- and client-side. Undocumented JSON surface; may change without notice. `market=be` companies use canonical root tickers (`ABI` / `ABI.BR` / `ABI-BRU` all store as `ABI`; exchange suffixes `.BR` / `.BRU` / `.EBR` are stripped at add time, Belgian ISINs are kept as-is) and remain unmapped. Finnhub is **US only** and never queried for BE. |
| `be_second_disclosure` | Filings | None | **Not wired (BE-4 re-verified 2026-08-10)**: no stable key-free second Belgian disclosure source exists. Euronext Brussels announcements are Drupal HTML pages keyed by per-company node IDs - no RSS (public RSS paths 404) and no JSON export (`_format=json` returns 406); the key-free EQS News JSON API (same family as the NL/IT connectors) returns zero records for every sampled Belgian ISIN, including BEL 20 names (ABI/KBC/UCB/Solvay/Ageas/Argenx and others); FSMA STORI remains the only official machine-readable feed. Paid feeds (Euronext Web Services/Saturn real-time or historical data, FinancialReports.eu, LSEG) are deliberately not wired. |
| `be_universe` | breadth cache | none | Euronext live all-stocks CSV filtered to Brussels segment rows (key-free; live 2026-08-10: ~95 `Euronext Brussels` + ~5 `Euronext Growth Brussels` + ~8 `Euronext Access Brussels` + ~25 multi-venue rows mentioning Brussels, e.g. `Euronext Paris, Brussels` / `Euronext Amsterdam, Brussels`; non-Brussels national boards, Global Equity Market, Trading After Hours, EuroTLX and Euronext Expert Market excluded); not a complete national universe; never enters the feed. |
| yahoo_be | news | none | Yahoo Finance BE public RSS (`region=BE`, `lang=fr-BE` + `en-US` merged; identical titles stay single-language); `.BR` at request time; may be loosely related and break without notice |
| google_news_be | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=en-BE&gl=BE&ceid=BE:en`); may be loosely related and break without notice |

`market=be` feed 软去重（仅展示，保留所有行；与其他市场共用 `KR_FEED_SOFT_DEDUPE` 开关，默认开启）：`yahoo_be` / `google_news_be` news 跨源按 ticker + Brussels day（`Europe/Brussels`）+ normalized title 配对。FSMA STORI filings 按稳定 STORI document id（`external_id` = `requiredReportingTopicId`）配对；无 id 时回退为 source-scoped（source + ticker + Brussels day + normalized title），假设的第二 BE 披露源不会因标题交叉标注。每行保留在 feed 中并标注 "Also seen on"；总数与分页大小永不缩减。

### Aquis 数据源（AQ）

`market=aq` 面向 **Aquis Stock Exchange (AQSE)** 发行人，而非 Aquis Exchange MTF 泛欧交易场所。公司使用规范根 ticker（`ADB` / `ADB.AQ` / `adb-aq` 均存为 `ADB`；`.AQ` 交易后缀在添加时剥离，AQSE mnemonic 原样保留，12 位 ISIN 原样保留）并保持 unmapped。Finnhub **仅 US**，不对 AQ 查询。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `aq_disclosure` | Filings | none | **Not wired (AQ-1 spike A3, 2026-08-10)**: the official AQSE announcements page (`www.aquis.eu/stock-exchange/announcements`) is a server-rendered HTML list (Date / Title / View rows, key-free), but `www.aquis.eu` and `embed.aquis.eu` sit behind a Vercel bot challenge — stdlib/curl clients get HTTP 429 with `X-Vercel-Mitigated: challenge` and a JS proof-of-work checkpoint; no key-free official JSON/RSS exists (`embed.aquis.eu/api/*` returns the same challenge; `api.aquis.eu` / `data.aquis.eu` abort TLS). LSE/Investegate/Companies House are deliberately **not** used as Aquis substitutes, and no paid Aquis data product is wired. |
| `aq_second_disclosure` | Filings | none | **Not wired (AQ-4 re-verified D2, 2026-08-10)**: no stable key-free second AQSE disclosure source appeared. The official announcements page and the market-notices page (`embed.aquis.eu/stock-exchange/rules-and-regulations/market-notices`) still return HTTP 429 (`X-Vercel-Mitigated: challenge`); no official RSS/JSON exists; third-party mirrors (Investegate / uk-wire / Proactive) are deliberately not wired as Aquis disclosure, and paid Aquis data products are excluded. |
| `aq_universe` | Universe | none | **Wired (AQ-2, partial unofficial mirror)**: `refresh_aq_universe()` fetches `https://www.ticker.app/aqse` (server-rendered Name / TIDM / ISIN table; key-free). Live 2026-08-10: ~79 unique AQSE instruments, 61 with ISIN; the official Aquis directory (`embed.aquis.eu/companies`) renders ~90 names but is behind a Vercel bot challenge for stdlib/curl clients, so completeness is **not verified** — this is a partial mirror, never a full AQSE universe, and no LSE/UK directory is filtered in. Board/exchange stored as `AQSE`; never enters the feed; backfills name/exchange/ISIN on add-company. |
| `yahoo_aq` | News | None (key-free) | Yahoo Finance AQ public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.AQ&region=GB&lang=en-GB`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10 with `ADB.AQ`; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`ADB`), `.AQ` is request-time only. |
| `google_news_aq` | News | None (key-free) | Google News AQ RSS (`news.google.com/rss/search?q={ROOT}.AQ&hl=en-GB&gl=GB&ceid=GB:en`). Live verified 2026-08-10; results can be loosely related; public RSS may break without notice. |

AQ feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 AQ 披露连接器（AQ-1 A3 / AQ-4 D2）。News：`yahoo_aq` ↔ `google_news_aq` 跨源按 ticker + London day（`Europe/London`）+ normalized title 配对。

### Cboe Europe (CXE) — Alternative European Equities，首个场所

Alternative European Equities 参考范围包含多个场所。本轨道仅落地 **一个场所**：Cboe Europe 股票（CXE 与 BXE 订单簿，MIC `CXEM`/`CXET`/`BXEM`/`BXET`）。**无** 虚拟 `aee` / `eu` / `eu_alt` market 代码。延期场所（本轨道未接入）：Turquoise（LSEG MTF；旧 turquoise.com 域名已停放，LSEG 替代路径非稳定免密钥目录）及其他 alternative European 订单簿。`market=cxe` 公司使用规范大写 Cboe 符号（`AZNl` → `AZNL`；`.CXE`/`.BXE` 后缀在添加时剥离；泛欧 ISIN 原样保留）并保持 unmapped。Finnhub **仅 US**，不对 CXE 查询。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `cxe_disclosure` | Filings | none | **Not wired (AEE-1 spike A3, 2026-08-10)**: Cboe Europe (BXE/CXE) is an MTF whose official symbol/trade-data surfaces (`cboe.com/europe/equities/market_statistics/symbol_data/...`, `.../trade_data/`) are venue quote/trade data, not issuer announcements. Issuers' official disclosures live at their primary listing venue (LSE/Xetra/…) and are deliberately **not** re-mapped onto `market=cxe`; no key-free Cboe Europe issuer OAM feed exists and no paid Cboe/LSEG data product is wired. |
| `cxe_second_disclosure` | Filings | none | **Not wired (AEE-4 re-verified 2026-08-10)**: no stable key-free second Cboe Europe disclosure source appeared. The official `trade_data/` page (HTTP 200) is MiFID venue trade data, not issuer disclosures; Turquoise is unreachable as a stable directory (`turquoise.com` parked; `lseg.com/en/turquoise` 404; `turquoise.eu` Cloudflare 403), and no paid MTF/LSEG/Cboe Data Vantage feed is wired. This track remains first-venue only. |
| `cxe_universe` | Universe | none | **Wired (AEE-2)**: `refresh_cxe_universe()` fetches the key-free official Cboe Europe Symbol Data CSVs for both order books (`.../market_statistics/symbol_data/csv/?mkt=cxe` and `?mkt=bxe`; live 2026-08-10: CXE 5,305 rows / BXE 6,469 rows, including zero-volume rows). CSV columns are `Name` (case-sensitive Cboe symbol, e.g. `AZNl`) + `Company Name / Description`; there is **no ISIN or instrument-type column**, so entries carry an empty ISIN honestly and keep the raw `symbol` plus `venue`/`venues` (CXE/BXE). Duplicate symbols on both books merge into one entry. Breadth only; never enters the feed; backfills name/exchange/venue on add-company. First Alternative European Equities venue only - Turquoise and other MTFs are deferred. |
| `google_news_cxe` | News | None (key-free) | Google News RSS (`news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en`). Live verified 2026-08-10. Query = exact company name from the CXE universe when available (quoted; ~100 items for `"AstraZeneca PLC"`), otherwise the Cboe symbol (bare `AZNl` query returns ~2 items). **No `yahoo_cxe` connector exists** because Yahoo Finance has no suffix for Cboe Europe symbols (Yahoo only covers primary listings). Results may be loosely related; public RSS may break without notice. |

CXE feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 CXE 披露连接器（AEE-1 A3 / AEE-4）。News：`google_news_cxe` 按 ticker + London day（`Europe/London`）+ normalized title 配对（仅一个 CXE news 源，配对为同源）。

### 欧洲共同基金（EMF）

「European Mutual Funds」轨道覆盖欧洲开放式共同基金 / UCITS（以 ISIN 为首要标识），**非** 德国 ETF/ETN/ETC（market=de），**非** Cboe Europe 股票（market=cxe），**非** Eurex 衍生品。market 短码为 `emf`；不使用过宽的 `fund`/`mf`/`ucits` 代码。基金 ISIN（如 `LU0171254561`）为规范标识；fund-data 后缀（`.F` / `.MF`）在添加时剥离。基金以 unmapped 添加。Finnhub **仅 US**，不对 EMF 查询。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `emf_disclosure` | Filings | none | **Not wired (EMF-1 spike A3, 2026-08-10)**: the ESMA registers public SOLR surface exposes a funds core (`esma_registers_funds`: ~212k docs = 107,388 AIFMD fund reports + marketing notifications; legal frameworks AIF/EuVECA/ELTIF/EuSEF) and a MiFID firms core (`esma_registers_upreg`), but **no UCITS register and no ISIN field** is exposed; KIID/PRIIPs documents live on manager sites with no central key-free feed. No stock OAM (eqs_dgap / investegate / etc.) is re-mapped onto `market=emf`, and no paid fund data product (Morningstar/Lipper) is wired. |
| `emf_second_disclosure` | Filings | none | **Not wired (EMF-4 re-verified 2026-08-10)**: no stable key-free second European fund document source appeared. ESMA registers remain reachable (funds core HTTP 200, AIFMD-only, no ISINs; UCITS core absent), national fund registers still have no stable key-free ISIN export (BaFin 404, Bundesanzeiger session wall), and paid products (Morningstar, Lipper, fund terminals) and Eurex fund products are deliberately not wired. This is a fund/UCITS track - not the German ETF or Cboe Europe packages. |
| `emf_universe` | Universe | none | **Boundary stub (EMF-2 spike B2, 2026-08-10)**: no stable key-free ISIN-bearing European mutual fund directory exists. ESMA registers expose a funds SOLR core (`esma_registers_funds`: ~212k docs = 107,388 AIFMD `funds_report` docs; legal frameworks AIF/EuVECA/ELTIF/EuSEF; fund name/country/manager only) and a MiFID firms core, but **no UCITS register and no ISIN field**; national fund registers have no stable key-free ISIN export (BaFin 404, Bundesanzeiger session wall), Morningstar/Lipper are paid. `refresh_emf_universe()` raises `EmfUniverseError`; `load/name_map/search` read a manually placed cache if one ever exists. No hand-written fund seed. |
| `google_news_emf` | News | None (key-free) | Google News RSS (`news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en`). Live verified 2026-08-10: a quoted fund name returns items (~26 for `"BlackRock Global Allocation Fund"`), while a bare fund ISIN returns zero. Query = fund name from an injectable resolver / a manually placed EMF universe cache when available, otherwise the typed fund ISIN (usually sparse - honest). **No `yahoo_emf` connector exists** because Yahoo Finance has no stable symbol suffix for European mutual funds (a guessed fund symbol returns an empty feed). Results may be loosely related; public RSS may break without notice. |

EMF feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 EMF 披露连接器（EMF-1 A3 / EMF-4）。News：`google_news_emf` 按 fund ISIN + Luxembourg day（`Europe/Luxembourg`）+ normalized title 配对（仅一个 EMF news 源，配对为同源）。

### Turquoise (TRQ) — Alternative European Equities，第二个场所

Turquoise（LSEG MTF；MIC `TRQX` / `TQEX`）为 Alternative European Equities 包中 **第二个** 场所，次于 Cboe Europe（`market=cxe`）。**无** 虚拟 `aee` / `eu` / `eu_alt` market 代码，`trq` market 非 AQSE（`aq`）、非 LSE（`uk`）、非 Eurex。常见 Turquoise 符号保持大写（`AZN` / `SHEL`）；`.TRQ` / `.TRQX` / `.TQEX` 后缀在添加时剥离；泛欧 ISIN 原样保留。公司以 unmapped 添加。Finnhub **仅 US**，不对 TRQ 查询。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `trq_disclosure` | Filings | none | **Not wired (TRQ-1 spike A3, 2026-08-11)**: Turquoise is an LSEG MTF without an independent issuer OAM. Re-test: `turquoise.com` is a parked domain-for-sale (HTTP 200); `turquoise.eu` now hosts an unrelated "Climate Tech Investment & Advisory" firm (was Cloudflare 403 on 2026-08-10); `tradeturquoise.com` and the LSEG Turquoise path redirect to `londonstockexchange.com/securities-trading/turquoise` (JS-only SPA shell, no server-rendered instrument/disclosure data); the old LSEG reference-file URLs (`lseg.com/turquoise/symbol/YYYYMMDD_TRQX_Instrument.csv`) return 404. No key-free Turquoise issuer announcement feed exists; no stock OAM (uk/de/cxe) is re-mapped onto `market=trq`. |
| `trq_second_disclosure` | Filings | none | **Not wired (TRQ-4 re-verified 2026-08-11)**: no stable key-free second Turquoise disclosure source appeared. The old LSEG reference-file CSV still returns 404, `turquoise.eu` now redirects (unrelated company), the LSE Turquoise page remains a JS-only SPA, and no Turquoise-specific issuer feed exists. Paid LSEG MTF data products (`lseg_mtf_paid` / `turquoise_data_paid`) are not wired. AEE package status: first venue Cboe Europe (`cxe`) and second venue Turquoise (`trq`) done; other package MTFs remain deferred - this track does not claim the whole package. |
| `trq_universe` | Universe | none | **Boundary stub (TRQ-2 re-spike B2, 2026-08-11)**: no stable key-free Turquoise directory exists. `turquoise.com` parked; `turquoise.eu` hosts an unrelated company; `tradeturquoise.com` / LSEG Turquoise paths redirect to a JS-only LSE SPA; the old LSEG reference files (`lseg.com/turquoise/symbol/YYYYMMDD_TRQX_Instrument.csv` / `..._TQEX_Instrument.csv`) return 404. `refresh_trq_universe()` raises `TrqUniverseError`; `load/name_map/search` read a manually placed cache if one ever exists. No hand-written seed and **no CXE CSV is reused** as a Turquoise directory. |
| `google_news_trq` | News | None (key-free) | Google News RSS (`news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en`). Live verified 2026-08-11: both quoted company names and bare Turquoise common symbols return items (symbols are more loosely related). Query = company name from a manually placed TRQ universe cache when available, otherwise the Turquoise common symbol. **No `yahoo_trq` connector exists** because Yahoo Finance has no Turquoise-specific symbol suffix (Yahoo quotes primary listings, not the TRQX/TQEX books). Results may be loosely related; public RSS may break without notice. |

TRQ feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 TRQ 披露连接器（TRQ-1 A3 / TRQ-4）。News：`google_news_trq` 按 ticker + London day（`Europe/London`）+ normalized title 配对（仅一个 TRQ news 源，配对为同源）。

### Eurex Core（EUX）

「Eurex Core (NP, L1)」轨道为 **衍生品交易所** 轨道（期货/期权产品代码），非股票国家轨道，非 AEE（`cxe`/`trq`），非 AQSE（`aq`），非 Mutual Funds（`emf`），非 Europe Display Value Bundle。market 短码为 `eux`；不使用过宽的 `fut`/`opt`/`deriv` 代码。Eurex 产品代码（`FDAX` / `FGBL` / `ESX5` / `2FE`）为规范标识（根/产品级，非单个到期合约）；`.EUX` 后缀在添加时剥离；产品 ISIN 原样保留。产品以 unmapped 添加。Finnhub **仅 US**，不对 EUX 查询。

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `eux_disclosure` | Filings | none | **Not wired (EUX-1 spike A3, 2026-08-11)**: the official Eurex circulars page (`eurex.com/ex-en/find/circulars`) is a JS-driven search surface (HTTP 200, but no server-rendered per-product rows and no stable JSON feed; the page lists exchange-wide operational notices, not per-product issuer OAM). Eurex derivatives are exchange-listed contracts without issuers, so no circular connector is wired and no stock OAM (eqs_dgap / investegate / uk / de / cxe) is re-mapped onto `market=eux`. The Eurex host also shows intermittent TLS EOFs (same host quirk as GPW/EQS). |
| `eux_second_disclosure` | Filings | none | **Not wired (EUX-4 re-verified 2026-08-11)**: no stable key-free second Eurex disclosure source appeared. The official product list CSV remains reachable (HTTP 200, 844,916 bytes) and the circulars page remains a JS search surface (HTTP 200); no per-product notice JSON exists and paid Eurex/Deutsche Börse market-data products (`eurex_data_paid` / `deutsche_boerse_paid`) and the Europe Display Value Bundle are deliberately not wired. This is a derivatives track - not a stock or Display Bundle track. |
| `eux_universe` | Universe | none | **Wired (EUX-2)**: `refresh_eux_universe()` fetches the key-free official Eurex product list CSV (linked from `eurex.com/ex-en/markets/productSearch`; live 2026-08-11: ~2,997 product rows, product-level - no individual expiry contracts). Semicolon-delimited with PRODUCT_ID / PRODUCT_TYPE / PRODUCT_NAME / PRODUCT_GROUP / CURRENCY / PRODUCT_ISIN / UNDERLYING_ISIN / COUNTRY_CODE / CASH_MARKET_ID etc.; types include FSTK/OSTK/FINX/OINX/FCUR/FBND/... (single-stock futures/options are Eurex derivatives, not Xetra cash equities). `counts` by product type and `counts_by_group`; backfills name/exchange/ISIN/group on add-company; breadth only, never enters the feed. The Eurex host shows intermittent TLS EOFs (fetch retries); the CSV blob URL may change and `EUX_UNIVERSE_PRODUCT_URL` overrides it. |
| `google_news_eux` | News | None (key-free) | Google News RSS (`news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de`). Live verified 2026-08-11: quoted product names return items (~71 for `"DAX Futures"`); bare product codes also return items (~19 for `FDAX`) but are more loosely related. Query = product name from the EUX universe cache when available, otherwise the Eurex product code. **No `yahoo_eux` connector exists** because Yahoo Finance does not quote Eurex derivatives with a stable suffix. Results may be loosely related; public RSS may break without notice. |

EUX feed 软去重仅用于展示（"Also seen on"；保留所有行，总数/分页永不缩减；共用开关 `KR_FEED_SOFT_DEDUPE`）。Filings 永不标注，因无 EUX 披露连接器（EUX-1 A3 / EUX-4）。News：`google_news_eux` 按 product code + Berlin day（`Europe/Berlin`）+ normalized title 配对（仅一个 EUX news 源，配对为同源）。

Web Settings 页面为每个已实现的数据源展示 Provider credentials（各连接器声明自有字段，当前为 `FINNHUB_API_KEY` 与 `SEC_USER_AGENT`）；未实现的源显示为 Not implemented 且不可配置。高级区域允许为显式读取它们的连接器设置额外环境变量。工作区数据库中保存的值优先于 `.env` 作用于运行进程，且任何 API 响应均不会完整返回这些值。

### 波罗的海（EE/LV/LT）— Nasdaq Baltic 三国市场

- 市场代码：`ee`（爱沙尼亚 / Tallinn）、`lv`（拉脱维亚 / Riga）、`lt`（立陶宛 / Vilnius），
  2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；`TICKER@EE|LV|LT` 与 Yahoo 后缀
  `.TL` / `.RG` / `.VL` 均可导入。
- **披露/公告主链 `nasdaq_baltic_news`**（filings，免 key）：官方页面
  https://nasdaqbaltic.com/statistics/en/news 背后的公开 JSON API
  `https://api.news.eu.nasdaq.com/news/query.action`（live 验证 2026-08-15）。
  按 `Europe/Tallinn` 时区逐日请求，仅收集发行人公告；交易所公告
  （company 为 `Nasdaq Tallinn/Riga/Vilnius`）不属于单一 ticker，跳过。
  官方 API 不返回 ISIN/代码，公告按**归一化公司名精确匹配** Baltic 宇宙缓存；
  匹配不上就诚实跳过，不做短码猜名。稳定主键 = 官方 `disclosureId`
  （external_id `baltic:<id>`），PDF 附件链接保留官方 URL。
- **可交易宇宙**：官方 XLSX（`/statistics/en/shares?download=1`，20 列，含
  Ticker/Name/ISIN/MarketPlace/List/segment），stdlib `zipfile` 解析，按
  MarketPlace `TLN/RIG/VLN` 分桶。live 条数（2026-08-15）：ee 30、lv 13、
  lt 25。缓存仅用于回填名称/板别/ISIN 与披露匹配，永不进入 feed；
  无手写蓝筹种子。
- **新闻**：`yahoo_ee` / `google_news_ee`、`yahoo_lv` / `google_news_lv`、
  `yahoo_lt` / `google_news_lt`（免 key RSS）。Yahoo 请求后缀 `.TL`/`.RG`/`.VL`，
  本地语言 `et-EE`/`lv-LV`/`lt-LT` 与 `en-US` 双查后合并；Google 参数
  `hl=et&gl=EE&ceid=EE:et`、`hl=lv&gl=LV&ceid=LV:lv`、`hl=lt&gl=LT&ceid=LT:lt`。
  可能松散相关，按已知 RSS 边界处理。**Finnhub 永不查 ee/lv/lt。**
- **第二披露源（BALTIC-4 锁死）**：三国发行人公告的稳定免费第二源不存在——
  Nasdaq Baltic 官方 API 已是唯一权威入口；中央证券存管与交易所无额外免 key
  接口，付费 Nasdaq 数据产品不接。新闻侧 Yahoo/Google 互为第二通道，
  披露侧保持单一官方源。
- **软去重**：披露按稳定 `disclosureId` 配对（无 id 时 source-scoped +
  Tallinn 日 + 标题）；三国新闻在 Yahoo↔Google 间按 ticker + Tallinn 日 +
  归一化标题配对。只标注 `Also seen on`，保留所有行、不缩页。

### 挪威与葡萄牙（NO/PT）— Euronext 扩展轨

- 市场代码：`no`（挪威 / Oslo Børs）、`pt`（葡萄牙 / Euronext Lisbon），
  2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；`TICKER@NO|PT` 与
  Yahoo 后缀 `.OL` / `.LS` 均可导入。
- **披露主链**：`newsweb_no` 使用 NewsWeb 官方 `api3.oslo.oslobors.no`
  list/detail JSON（覆盖 XOSL/XOAX/XOAM/MERK，overflow 自动拆窗），并保存正文、
  修正关系及官方附件；单日仍 overflow 时失败关闭。
  `euronext_lisbon_news` 使用 Euronext Lisbon 当前 canonical company press-release
  archive，严格验证日期参数未被重定向丢弃并分页到明确空页。CMVM 法定披露系统
  尚无公开、稳定、可版本化的数据合同，因此没有接入。
- **可交易宇宙**：复用 Euronext live CSV
  （`live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock`，
  同 NL/FR 家族），按 `market` 列的 **live 锁定写法**过滤：
  NO 保留含 `Oslo` 的行（`Oslo Børs` 198 + `Euronext Growth Oslo` 87 +
  `Euronext Expand Oslo` 10 = **295**）；PT 保留含 `Lisbon` 的行
  （`Euronext Lisbon` 33 + `Euronext Access Lisbon` 14 +
  `Euronext Growth Lisbon` 1 = **48**）。Amsterdam/Paris/Brussels 行一律
  丢弃；无 OBX/PSI20 手写种子；缓存不进 feed。
- **新闻**：`yahoo_no`/`google_news_no`、`yahoo_pt`/`google_news_pt`
  （免 key RSS）。Yahoo 请求后缀 `.OL`/`.LS`，本地语言 `nb-NO`/`pt-PT` 与
  `en-US` 双查合并；Google 参数 `hl=no&gl=NO&ceid=NO:no` 与
  `hl=pt&gl=PT&ceid=PT:pt`。可能松散相关。**Finnhub 永不查 no/pt。**
- **第二源（ENP-4 锁死）**：当前未接额外付费/聚合披露源；主链均为官方源。
- **软去重**：披露 filing 行永不跨源标注；NO/PT 新闻在
  Yahoo↔Google 间按 ticker + Oslo/Lisbon 日 + 归一化标题配对。只标注
  `Also seen on`，保留所有行、不缩页。

### 奥地利（AT）— Vienna Stock Exchange / Wiener Börse

- 市场代码：`at`，2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；
  `TICKER@AT` 与 Yahoo 后缀 `.VI` 均可导入。
- **披露主链**：`wiener_boerse_news` 分页读取 Wiener Börse 官方
  `/en/news-1/`，只保留 issuer `Ad-hoc News`，排除交易所编辑内容和董事交易；
  支持非数字 `c93603[file]` ID，严格核验总 hits、25 条分页、倒序、重页与
  30 日日期边界。保存官方文件 URL 与原始 HTML；这是滚动 Ad-hoc 档案，不
  宣称等同完整奥地利 OAM 文件库或 2008 年以来全历史。
- **可交易宇宙**：`refresh_at_universe()` 读取 Wiener Börse 官方服务端渲染
  companies list，保存 ISIN、发行人、国家、市场、板块、证券类型与 profile；
  排除外国 `global market` 便利交易和基金/证书。官网表不发布 ticker，因此
  默认以 ISIN 为诚实主键；可用 `AT_UNIVERSE_OVERLAY_PATH`（schema
  `at_universe_overlay/v1`）追加经审核 ticker 与更名别名，绝不臆造代码。
- **新闻**：`yahoo_at`（`.VI` 后缀，`de-AT` + `en-US` 双查）与
  `google_news_at`（`hl=de&gl=AT&ceid=AT:de`），免 key RSS，可能松散相关。
  **Finnhub 永不查 at。**
- **第二源（AT-4 锁死）**：EQS Austria 样本空记录，暂不接第二披露源。
- **软去重**：Wiener filing 优先 opaque file ID，再回退 ticker/ISIN + Vienna
  当地日 + 规范标题；AT 新闻在
  Yahoo↔Google 间按 ticker + Vienna 日 + 归一化标题配对。只标注
  `Also seen on`，保留所有行、不缩页。

### 印度（IN）— NSE（主）/ BSE India（第二交易所）

- 市场代码：`in`，2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；
  `TICKER@IN` 与 Yahoo 后缀 `.NS`（BSE 报价 `.BO`）均可导入。
- **披露主链 `nse_announcements`**（filings，免 key）：官方 JSON
  `https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=dd-MM-yyyy&to_date=dd-MM-yyyy`
  （live 验证 2026-08-15，无 WAF/cookie）。字段含 `seq_id`（稳定主键，
  external_id `nse:<seq_id>`）、`symbol`、`sm_name`、`sm_isin`、`desc`
  类别、`an_dt`（IST）、`attchmntText` 摘要与官方 PDF 附件。单日约
  1600 条，连接器按请求 symbols 过滤；日期窗真实约束；时区 Asia/Kolkata。
- **可交易宇宙**：官方免 key CSV
  `https://archives.nseindia.com/content/equities/EQUITY_L.csv`
  （live 验证 2026-08-15），仅保留 `SERIES == EQ` 的股票行（条数见回执）；
  **BSE 行不混入**；无 Nifty50 手写种子；缓存永不进 feed。
- **新闻**：`yahoo_in`（`.NS` 后缀，`en-IN` + `en-US` 双查）与
  `google_news_in`（`hl=en&gl=IN&ceid=IN:en`），免 key RSS，可能松散相关。
  **Finnhub 永不查 in。**
- **第二披露源 `bse_india_announcements`**：调用 BSE India 官方公开网站的
  active-equity directory 与 `AnnSubCategoryGetData/w`，按 BSE scrip code、
  日期和 `ROWCNT` 完整分页；保存 `NEWSID`、ISIN、IST 时间及官方附件。BSE
  目录只用于身份解析，不并入 NSE universe；无映射或分页不完整时失败关闭。
- **软去重**：NSE/BSE 仅在 ticker、Kolkata 日与归一化标题完全相同的情况下
  标记 `Also seen on`，两个交易所原始记录全部保留；IN 新闻同样只做展示标注。

### 墨西哥（MX）— BMV（主）/ BIVA（第二源边界）

- 市场代码：`mx`，2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；
  `TICKER@MX` 与 Yahoo 后缀 `.MX` 均可导入。
- **披露主链**：`bmv_relevant_events` 分页读取 BMV 官方 Sala de
  Prensa 的滚动 Eventos Relevantes，直接保存 PRINCIPAL/ANEXO、原生文档 ID、
  Mexico City 时间和实际采集 URL；重复页、排序倒退、结构变化或分页触顶均失败
  关闭。市场操作通知和评级机构事件不混入发行人 Filing，未匹配身份保留为 pending。
  BMV 完整定期财务/XBRL 档案属于登录付费产品，目前不接入该产品。
- **可交易宇宙（边界 stub）**：BMV 无稳定免 key 目录端点，`refresh` 抛
  `MxUniverseError`；只读手工放置的
  `.cache/investment_monitor/mx_universe.json`。**无 IPC 手写种子**；缓存
  不进 feed。
- **新闻**：`yahoo_mx`（`.MX` 后缀、`es-MX` + `en-US` 双查）与
  `google_news_mx`（`hl=es&gl=MX&ceid=MX:es`），免 key RSS，可能松散相关。
  **Finnhub 永不查 mx。**
- **第二源（MX-4 锁死）**：BIVA 门户为 React SPA，事件页无服务端数据；
  `rss.biva.com.mx` TLS 握手失败，无稳定 RSS。不接 EODHD/OpenFIGI 等
  third_party 冒充官方；不接付费终端。
- **软去重**：披露 filing 行永不跨源标注；MX 新闻
  Yahoo↔Google 按 ticker + **Mexico City 日** + 归一化标题配对。只标注
  `Also seen on`，保留所有行、不缩页。

### 以色列（IL）— TASE / MAYA

- 市场代码：`il`，2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；
  `TICKER@IL` 与 Yahoo 后缀 `.TA` 均可导入。
- **披露主链**：`maya_announcements` 使用 MAYA 官方公司自动完成接口
  取得 `companyId`，再调用 `/api/v1/reports/companies` 按公司和日期分页；以
  `x-total-count` 严格核验完整性，保留希伯来语标题、report/form ID、correctives
  及 `mayafiles.tase.co.il` 官方原文附件。单一 ticker 解析失败会进入 source error，
  不拖垮其他 ticker。
- **可交易宇宙（边界 stub）**：TASE 无稳定免 key 目录端点，`refresh`
  抛 `IlUniverseError`；只读手工缓存
  `.cache/investment_monitor/il_universe.json`。**无 TA-35 手写种子**；
  缓存不进 feed。TASE Data Hub 付费产品不接。
- **新闻**：`yahoo_il`（`.TA` 后缀，`he-IL` + `en-US` 双查，live 均
  200）与 `google_news_il`（`hl=en&gl=IL&ceid=IL:en`；`hl=he` 实测仅 1
  条故采用 en），免 key RSS，可能松散相关。**Finnhub 永不查 il。**
- **第二源（IL-4 锁死）**：ISA 公开披露无稳定免 key 通道；TASE Data
  Hub 需注册/付费，不接。README 写死边界。
- **软去重**：披露 filing 行永不跨源标注；IL 新闻
  Yahoo↔Google 按 ticker + **Jerusalem 日** + 归一化标题配对。只标注
  `Also seen on`，保留所有行、不缩页。

### 匈牙利（HU）— Budapest Stock Exchange（BSE/BET）

> 注意：这里的 **BSE 是布达佩斯证券交易所（bse.hu / bet.hu）**，与本仓
> 印度轨锁死的印度 BSE（bseindia.com）完全不同，两者不共享任何端点或逻辑。

- 市场代码：`hu`，2026-08-15 接入。公司以未映射方式添加（无 SEC 映射）；
  `TICKER@HU` 与 Yahoo 后缀 `.BU` 均可导入。
- **披露主链（有界历史覆盖）**：`bse_hu_announcements` 先建立 BSE/BET 官方
  `issuers_news` 会话，提取 CSRF 和分页 URL，再按页读取档案。默认最多 200 页；
  尚未越过请求起始日便触顶时明确标记 `partial`，覆盖级别为
  `official_bounded_archive`，不冒充完整历史。
- **可交易宇宙（official partial）**：`refresh_hu_universe()` 匿名读取 BSE
  官方 issuer 页内嵌的 `IssuerDataSource`，按官方 `country=HU` 和
  Prime/Standard/Xtend 股票组筛选候选，再逐 issuer/security profile 验证
  ticker、ISIN 与 `Equity class`；`Market` 优先取 security profile，当前 Xtend
  页面缺字段时只允许由唯一官方 `W_SME` 目录组回填，混合组保持失败。2026-08-23 live：目录 154 个发行人，
  其中 66 个 HU equity-group 候选；4iG profile 的普通股 `4IG / HU0000167788`
  被纳入，同页债券被排除。单 profile 失败有审计记录，部分刷新不覆盖既有好
  缓存；全部失败、结构变化或身份冲突失败关闭。范围不含其他匈牙利场所与退市
  历史，故保持 partial；缓存只服务 Web name/ISIN 回填和公告匹配，不进入 feed。
  因完整刷新需要逐 issuer/security 限速验证，Web 添加公司不会同步执行数分钟的
  全量刷新；应在启动/定时维护阶段预热缓存，冷缓存时添加公司快速降级为 unmapped。
- **新闻**：`yahoo_hu`（`.BU` 后缀、`hu-HU` + `en-US` 双查；live 实测 Yahoo
  `.BU` RSS 返回 200 但 **0 items**，保留连接器并如实标注空 feed）与
  `google_news_hu`（`hl=hu&gl=HU&ceid=HU:hu`；live 实测 69 条，`hl=en`
  被重定向到 US 且 65 条，故采用 hu），免 key RSS，可能松散相关。
  **Finnhub 永不查 hu。**
- **第二源（HU-4 锁死）**：MNB 公开通道无稳定免 key 披露端点；不接
  EODHD/OpenFIGI 等 third_party；不接付费终端。
- **软去重**：披露 filing 行永不跨源标注；HU 新闻
  Yahoo↔Google 按 ticker + **Budapest 日** + 归一化标题配对。只标注
  `Also seen on`，保留所有行、不缩页。

## 1.4 全球市场参考目录 + 覆盖看板（Phase 0）

`universe/exchange_catalog.py` 是 Phase 0 的静态参考目录。历史文件名
`universe/ibkr_exchange_catalog.json` 记录它最初由公开经纪商市场清单整理而来，
但它只是一次性的覆盖范围 benchmark：运行时不访问该经纪商、不登录账号、
不调用 API，也不提供交易能力。产品数据来自交易所、监管机构和正规第三方。

- **冻结基线**：28 国（美洲 3 / 欧洲 19 / 亚太 6）、87 条股票场所/路由记录
  （31 / 44 / 12）；测试逐项断言。美国页面的 `Nasdaq/BX/PSX`、
  `Direct Edge/EDGEA`、加拿大 `Aequitas NEO/NEO Lit` 等组合行按计划书计数
  拆分，回执内说明映射。ETF 栏目 27 条与股票场所大体重复，Phase 0 保持
  单一场所体系，只在 seed `normalization.etf_columns` 记录 11/15/1。
- **覆盖状态**（`coverage_report.py`，自动推导）：
  `live / partial / stub / unavailable`，另有
  `etf_universe: live|partial|unavailable|unknown` 与
  `source_tier_summary: official|mixed|third_party|none`。边界 stub 国
  （AT/CH/HU/IL/MX/SE/SG 宇宙；AT/HU/IL/MX/NO/PT 披露）绝不标 live；
  RU 只接 MOEX 研究目录。报告不进 feed，也不表达任何经纪商交易状态。
- **API/UI**：`GET /api/coverage` 返回目录摘要 + 28 国信息源覆盖（沿用现有
  `/api/*` 鉴权）；Manage 页显示「全球市场信息覆盖」。响应明确声明
  `broker_runtime_dependency=false`、`broker_account_required=false`，且不包含
  交易状态。
- **产品边界**：不接 IBKR 或其他经纪商账号/API，不使用 Gateway、TWS、
  Client Portal、`conid`，也不以账户权限验证信息覆盖。
- **本轨不做**：不把 BATS/Chi-X/Cboe/Turquoise 路由场所注册成披露连接器；
  不做 Phase 4（CA/SG/SE/CH 主链与各国 ETF 爬全）；不重做 Phase 1 的
  `global_equity_reference`/EODHD 日预算；不动 eux/emf；不上云、不改生产。

## 1.5 共享股票身份 + ETF 子类型基建（Phase 1）

`universe/global_equity_reference.py` 是跨市场的第三方候选参考层
（`source_tier="third_party"`），为 Euronext ETF 候选、ISIN/FIGI 富化与
证券身份富化提供 ISIN/FIGI 等跨市场参考字段。缓存位于
`.cache/investment_monitor/global_equity_reference.json`。

- **官方宇宙永远赢**：`refresh_global_equity_reference()` 把 DE/BE/FR/NL/IT
  官方 `name_map` 作为锚；同一 symbol 的官方 name/ISIN/board 覆盖第三方
  候选，候选只保留 provenance。DE Xetra 官方目录（含 3000+ ETF）不受影响。
- **EODHD（P1-2）**：`EODHD_API_KEY` 从 `.env`/环境注入（不写进仓库，
  不进 Web Settings extra-env——密钥后缀被安全白名单拒绝）。
  `exchange-symbol-list/{EXCHANGE}` 逐交易所收编权益行，默认每日预算
  `EODHD_DAILY_BUDGET=20` 次调用，预算日期与已刷交易所都持久化在缓存里，
  防止坏 token 空转。未配置 key 时管线如实记录 `skipped_eodhd_no_key`，
  **不产生任何假候选**。
- **OpenFIGI（P1-1）**：`POST https://api.openfigi.com/v3/mapping` 免 key
  可用（2026-08-15 live 实测；GET 返回 405）。只对缺 ISIN/FIGI 的 ETF
  候选批量富化（默认最多 100 条、每请求 10 个 job），尊重其 25 次/60 秒
  限速窗口；可选 `OPENFIGI_API_KEY` 头。
- **Twelve Data（P1-3，可选）**：无 `TWELVE_DATA_API_KEY` 时跳过并记录
  `skipped_twelve_no_key`；显式 `allow_no_key=True` 才走免 key
  `symbol_search`，只写 `twelve_*` provenance 字段。
- **add-company 接线**：`/api/companies/batch` 在官方 `name_fallback`
  之下合并参考层条目（官方命中保留，参考层只补官方没有的 ticker，如
  Euronext ETF 候选），无需改前端。
- **测试**：`test_global_equity_reference.py`、`test_phase1_equity_reference.py`
  （DE 黄金样本 + Euronext ETF 候选）、`test_eodhd_client.py`、
  `test_openfigi_client.py`、`test_twelve_data_client.py`，全部离线 fake
  opener，不发真实网络请求。

## 1.6 Phase 4 partial 边界与 ETF 完整性（2026-08-16）

计划书 Phase 4 的四国主链在 2026-08-16 重新 live 侦察后按实际可达性锁边：

- **CA**：universe 保持 `partial`（官方 TMX TSX/TSXV + CSE 官网公开全证券
  JSON 已接；NEO/Cboe Canada 仍缺免费完整目录）。CSE 官方逐发行人 filing mirror、
  issuer IR、EDGAR 双重上市补漏和 CEO.ca discovery 已接；因 SEDAR+ 全国主链不可
  自动批量使用，披露总体仍是 `partial`，不假称 complete。
- **SG**：universe 保持第三方 `partial`。Singtel 与 OCBC 官方 IR 档案已内置并
  完成 live smoke；此外支持审核配置的 issuer IR、已知 SGX 官方详情链接和显式
  SG/US EDGAR 映射。SGX 公告 SPA 仍受内部 token 合同限制、MAS OPERA 有 CAPTCHA、
  UOB ListedCompany 返回 WAF challenge；均不绕过，因此不声称 SGXNET 全量。
- **SE**：后续重新定位到当前 Nasdaq Nordic 官方公开 Shares Screener；
  `market=STO` 下 Main Market 412、First North 332 条，分页对账和官方股票字段
  校验均已接。universe 从历史 stub 提升为 official partial；NGM、Spotlight、
  其他场所和退市历史仍不在范围内。披露 `nasdaq_se_filings` 保持 live。
- **CH**：universe 保持 `stub`（SIX 页面与 `api.six-group.com` 均 404）；
  披露 `eqs_ch` 保持 partial。EODHD/OpenFIGI 候选可转 partial，但永远
  `source_tier=third_party`，不得覆盖官方字段。
- **ETF 七国**：UK 官方 FIRDS 已按 CFI 分类 ETF（`uk_universe_etf_count`），
  缓存含 ETF 行时 coverage 显示 `partial`（FIRDS 只有 ISIN、无零售 ticker，
  故不标 live）；HK/JP/TW/AU/PL/ES 本轮未发现可自动化的官方 ETF
  CSV/XLSX/API（HKEX/LSE/ASX 为 SPA 或前端导出，JPX/BME 404，GPW 连接
  不稳），coverage 诚实保持 `unknown`，一旦第三方候选层有行自动转
  `partial`。DE 黄金样本（官方 Xetra 含 ETF/ETN/ETC）不回退，测试锁死。
- **CXE/TRQ**：`docs/phase4-cxe-trq-venue.md` 收口——两市场只有
  `google_news_*` 新闻源，无任何披露 connector；catalog `catalog_role`
  为 `venue_only`，永不进 28 国分母。
- `coverage_report.py` 新增 `MARKET_NOTES` 显式锁边文案；四个模块新增
  `PHASE4_BOUNDARY` 常量，`tests/test_phase4_boundaries.py` 逐项断言
  Manage 看板状态与边界一致。

## 1.7 Phase 5 计划书边角收口（2026-08-16）

- **俄罗斯只读宇宙**：`universe/ru_universe.py` 接官方 MOEX ISS
  `…/engines/stock/markets/shares/boards/TQBR/securities.json`（免 key，
  live 505 行 TQBR）。payload 固定 `readonly=true`，只做研究目录，绝不进
  feed；coverage RU 显示 universe partial；产品不提供行情或交易状态。
- **CN↔Stock Connect**：`universe/stock_connect.py` 静态记录
  `SEHKSZSE`（Shanghai-HK Stock Connect）与 `SEHKSTAR`（STAR Connect）
  northbound 映射；`cn` 保持 catalog extra，**不新开 CN 监管披露连接器**。
- **ETF 发行人披露骨架**：coverage 新增 `etf_disclosure` 字段
  （live|partial|stub|unavailable）。当前无免 key ETF 文件/公告源，28 国
  全部 unavailable；股权 `eqs_*`/公司公告绝不冒充 ETF 基金文件。看板新增
  一列。
- **经纪商身份路径已移除**：添加公司只使用项目自身市场代码、官方目录及
  ISIN/FIGI 参考信息，不查询或保存 `conid`。迁移不会删除历史数据库表或数据。
- **季度覆盖对表工具**：`PYTHONPATH=src python -m investment_monitor.catalog_diff`
  可把当前静态 benchmark 与 `docs/ibkr_catalog_snapshot.json` 比较；该工具仅供
  离线发现范围变化，不是运行时依赖，也不调用账号/API。
- **薄国结论（2026-08-16 历史复验）**：当时 NO/PT 已有 Euronext Live CSV，
  AT/MX/IL/HU 尚锁 stub；这些结论已被后续官方连接器批次逐项更新，不能作为
  当前状态读取。当前状态以顶部自动覆盖表和各市场专节为准。

## 1.8 零注册免费扫尾（Z，2026-08-16）

- **US**：新增 `us_universe.py`，官方 SEC
  `company_tickers_exchange.json`（约 10k 行，必须带 User-Agent）；这是
  SEC 注册边界内的 breadth-only 目录，coverage 标 `partial`，不冒充完整
  交易所目录。
- **JP**：JPX 上市公司页未暴露静态 xlsx/xls 直链（Z0 复验），无稳定免
  key 官方目录 → universe 保持 `unavailable`；TDnet/EDINET 披露保持 live。
- **公开 ETF 目录**：未发现新的免 key 官方静态文件（LSE/HKEX/ASX SPA、
  JPX/BME 404、GPW 不稳）；七国 ETF 状态维持 unknown，第三方候选行出现
  才转 partial。不申请 EODHD/新 key。
- **薄国（当时结论）**：2026-08-16 曾把 AT/MX/IL/HU 锁为 stub；后续批次
  已分别接入可验证的官方边界。本节保留历史决策时间点，当前状态以顶部自动
  覆盖表和各市场专节为准。
- **文档**：`docs/MARKET_COVERAGE_OUT_OF_SCOPE_ZH.md`（范围外清单）与
  `docs/MARKET_DATA_FREE_VS_PAID_ZH.md`（免费 vs 付费短表）入库。
- **禁止项**：不注册账号、不申请 key、不用 Playwright、不把新闻标成
  披露/ETF 文件。

## 2. 可选的手动 SEC 采集

选择包含起止的申报日期范围：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m investment_monitor.cli \
  --start-date 2025-07-27 \
  --end-date 2026-08-02
```

该命令仍适用于显式指定初始范围。它读取初始 CSV、运行 SEC 连接器、存储标准化的 `InformationItem` 记录、如实记录采集活动，并更新独立遗留报告 `output/announcements.html`。

典型成功采集输出包含类似行：

```text
INFO collection source=sec ticker=AAPL status=success items=... inserted=... updated=...
collected=... failures=0 stored_total=... report=output/announcements.html
```

对同一范围重复运行会更新具有相同 `(source, external_id)` 身份的记录，而非插入重复项。

## 3. 启动 Web 界面

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m investment_monitor.web \
  --host 127.0.0.1 \
  --port 8765
```

成功启动会打印：

```text
Investment Monitor running at http://127.0.0.1:8765
```

在浏览器中打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。使用期间请保持 Terminal 窗口打开。按 `Control-C` 停止服务。

服务运行期间，每个 Eastern 日历日执行一次增量采集。启动时若当前 ET 日尚未尝试，会先补跑，之后每日 6:00 AM ET 检查。若要在不发起外部采集请求的情况下预览已存数据，可使用 `AUTO_DAILY_COLLECTION=false` 启动。

通过列表页添加公司会立即触发一年 SEC 元数据回填。即使 SEC 暂时不可用，公司仍保留在所选列表中，页面会单独报告回填失败。这些默认值可在 `.env` 中调整。

## 主要 Web 行为

- **Daily information** 选择一个 Eastern Time 日历日与可选列表，隐藏无更新的公司，将其余条目按公司分组，仅展示时间、类型、source、标题与原始 URL。打印操作使用适合浏览器 PDF 导出的专用布局。
- **Lists & sources** 创建、重命名、删除与切换列表。一家公司可属于多个列表；移除成员关系永不删除已存信息。
- 公司候选从本地官方 SEC 映射（按名称或 ticker）及已已知公司（按名称、ticker 或记录的 exchange）搜索。用户确认候选后才添加。
- Source 卡片分别报告各已配置连接器，包括覆盖区域、启用状态、最近尝试与成功，以及持久化失败摘要。
- 官方链接在新标签页打开，带 `noopener` 与 `noreferrer`。
- **Research** 只列出 Holdings / Planned / Watchlist 中的公司，并基于该公司已入库的披露、新闻与社区内容生成研究卡。模型功能默认关闭。

## 研究卡（Research cards）

研究卡仅供研究辅助，**不构成投资建议**。它绝不给出买入/卖出评级、目标价或价格预测。

- 只有已属于 Holdings / Planned / Watchlist 的公司才可生成。
- 只使用监控器已入库的证据（官方披露、新闻与社区内容）；不做外部网页搜索或 IR 抓取。
- 原始新闻、披露与社区文本**绝不翻译或改写**。卡片按语言（`en` 或 `zh-CN`）分别生成并分别缓存。
- 证据少于 `RESEARCH_MIN_EVIDENCE_ITEMS` 条、或全部来自社区时，返回 `insufficient_evidence`，不调用模型。
- **不按数量截断**：日期范围内所有合格证据都会送入模型，不取"最新 30 条"之类的子集。若全量证据构成的请求超过安全发送上限，系统会明确拒绝（`research_range_too_large`）并提示缩短日期范围，**绝不悄悄漏掉资料**。
- 卡片按证据指纹缓存（公司、语言、模型、provider、prompt/schema/rule 版本及排序后的**全量**证据集合）。范围内任意证据新增、删除或变化都会使旧卡变为 `stale`；`Regenerate` 绕过缓存。
- 模型功能**默认关闭**。启用后，生成卡片会把选定的公开证据发送给你配置的 OpenAI-compatible 服务。API key 只从环境读取，绝不写入 SQLite、通过 API 返回或写入日志。

```text
RESEARCH_AI_ENABLED=false
RESEARCH_AI_BASE_URL=https://api.deepseek.com
RESEARCH_AI_MODEL=deepseek-chat
RESEARCH_AI_API_KEY=
RESEARCH_AI_REQUEST_TIMEOUT_SECONDS=60
RESEARCH_MIN_EVIDENCE_ITEMS=3

# 浏览器在反代入口看到的协议（本地开发 http，HTTPS 反代生产必须设为 https）。
# 用于同源 CSRF 校验，代表外部协议而非内部监听协议。
# 客户端发送的 X-Forwarded-Proto 永不被信任。
WEB_EXTERNAL_SCHEME=http
```

### 日本数据源（JP）

| Source | Type | Key | Boundaries |
|---|---|---|---|
| tdnet_public_web | filings | none | Official JPX TDnet public list; fail-closed completeness checks |
| edinet | filings | `EDINET_API_KEY` | Official EDINET API v2 metadata (see below) |
| yahoo_jp | news | none | Yahoo Finance JP public RSS; `.T` suffix at request time only |
| google_news_jp | news | none | Key-free Google News RSS search (`hl=ja&gl=JP&ceid=JP:ja`); may be loosely related and break without notice |

`market=jp` 公司以未映射方式添加（本地证券代码，如 `7203`）。Finnhub **仅 US**。News 软去重（仅展示）：`yahoo_jp` / `google_news_jp` 跨源按 ticker + Tokyo day + normalized title 配对。TDnet/EDINET filings 暂无跨源 soft-dedupe 键。

## 官方 EDINET 连接器

`edinet` 包仅使用 EDINET API v2 获取披露元数据与文档。在 `.env` 中配置 `EDINET_API_KEY`；切勿提交密钥。面向登录的 API 请求与绝对时间窗口相交的每个日本文件日期，按 `submitDateTime` 过滤，并匹配 filer、issuer、subject 与 subsidiary EDINET-code 角色，无 `docTypeCode` 白名单：

```python
result = connector.getWatchlistDisclosuresSince(
    companies=user.watchlist,
    since=now - timedelta(hours=24),
    now=now,
    include_downloads=False,
)
```

索引优先实现将日期级完整性存入 SQLite，在回退至官方 API 前使用短缓存。失败的日期通过 `partial` 与 `errors` 报告；成功的日期仍会返回。完整登录钩子见 `examples/edinet_login.py`。

CLI 示例：

```bash
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli refresh-codes
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli \
  login-feed --watchlist 7203,6758,9984 --since 24h
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli \
  sync --from 2024-01-01 --to 2024-12-31
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli sync --incremental
```

下载为可选。类型 `1` 至 `5` 透传至官方 v2 端点；存储的 payload 包含 SHA-256、大小、content type 及 ZIP 完整性状态，路径为 `data/downloads/edinet/{fileDate}/{docID}/type-{n}/`。

官方 EDINET 代码列表 ZIP 导入同一 SQLite 数据库，用于精确 EDINET code、证券代码、JCN 与 filer 名称解析。模糊或未知输入返回于 `unresolved`，而非静默丢弃。

## TDnet 运行模式

TDnet 采集以官方 JPX 公开列表为权威来源。其官方声明计数、连续分页与解析行数仍为 fail-closed 检查。可选的非官方 Yanoshin 对比默认关闭（`TDNET_YANOSHIN_CROSSCHECK_ENABLED=false`），因此第三方 downtime 不会阻塞原本完整的官方 JPX 采集。

## 数据模型与安全迁移

标准化 item 表现在除原有列外还包含 `market`、可空 `summary` 与 `effective_at`：

```text
information_items -- unique (source, external_id)
information_item_tickers
```

`companies` 含 `market` 列与唯一 `(ticker, market)` 身份，因此不同市场的同一代码永不混淆。幂等启动迁移可在不删除已存 SEC 记录的情况下升级现有单市场数据库。

幂等 Web 迁移新增：

```text
companies
system_lists
company_list_memberships      Company <-> List
information_read_state
ingestion_runs
ingestion_logs
app_settings
```

迁移使用 `CREATE TABLE IF NOT EXISTS` 并幂等插入三个固定列表。不会删除或重写现有 SEC 记录。SQL 位于 `src/investment_monitor/migrations/001_web_mvp.sql`，随应用打包。

SEC 专用 HTTP 与映射代码仍位于：

```text
src/investment_monitor/sources/sec/
```

通用采集流水线仍仅依赖 `SourceConnector` 与 `InformationRepository`。Web 查询层从 SQLite 读取标准化记录，渲染页面时不调用 SEC 连接器。

## 运行自动化测试

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

常规套件使用保存的 SEC fixtures，无需联网。成功运行以如下结尾：

```text
Ran ... tests in ...s

OK (skipped=1)
```

跳过的测试为可选 live SEC 集成测试。套件覆盖固定列表幂等、跨列表去重、部分 ticker 解析、移除成员关系但不删历史、Eastern Time 边界、持久化已读状态、范围内批量更新、搜索、稳定分页、生产环境排除 mock、source 状态，以及核心 HTTP/静态路由。

## 无需保持电脑开机时如何运行

生产模式是在常开 Linux 服务器或带持久磁盘的容器托管平台上运行同一服务。随附的 `Dockerfile` 将 Web 服务与每日采集器打包在一起。

本地容器快速验证（仅本机访问）：

```bash
docker build -t investment-monitor .
docker run -d \
  --name investment-monitor \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8765:8765 \
  -v investment-monitor-data:/app/data \
  investment-monitor
```

生产部署必须满足（详见 `docs/security/HARDENING_CHECKLIST.md`）：

1. **端口隔离**：容器/进程只映射到 `127.0.0.1`，由 Nginx/Caddy 在前方终结 HTTPS 并反代；云安全组**禁止**对公网放行 `8765`。
2. **访问鉴权**：设置强随机的 `WEB_AUTH_TOKEN`。设置后所有 `/api/*` 请求必须携带 `Authorization: Bearer <WEB_AUTH_TOKEN>`，否则返回 401。浏览器端在控制台执行
   `localStorage.setItem("im_web_auth_token", "<token>")` 后页面请求会自动带上。
3. **同源校验**：设置 `WEB_EXTERNAL_SCHEME=https`（CSRF 同源校验依赖外部协议）。
4. **数据安全**：为 `/app/data` 挂持久卷并纳入备份；SQLite 适用于单个小应用实例，勿对同一 SQLite 文件运行多个副本。

在服务器上运行该服务仍要求持续供电联网；若需他人访问，按上述清单配置即可。

## 建议的手动验收测试

1. 启动服务器并打开 Today。
2. 打开 Holdings，将 `AAPL, MSFT BADTICKER` 加入 Holdings 与 Watchlist。
3. 确认有效映射 ticker 成功添加，未解析 ticker 单独报错，且不回滚已成功添加项。
4. 确认同时在两个列表的公司显示两个徽章，但每条 filing 只出现一次。
5. 将一条 filing 标为已读，刷新后确认各处仍为已读。
6. 使用筛选后的 **Mark all in scope as read**，确认无关列表项仍为未读。
7. 从 Holdings 移除公司，确认其仍在 Watchlist。
8. 从所有列表移除，确认操作提示历史信息已保留。
9. 打开 Data Sources，确认 SEC 为已配置 provider；News 在配置 `FINNHUB_API_KEY` 并成功同步后显示已连接；Community 中 CEO.ca（CA）已上线，HotCopper（AU）、LSE Share Chat（UK）与 Xueqiu（CN/HK）为 stub（Not connected / 空采集）。

## 已知首个 MVP 限制

- 无认证或多用户已读状态（单用户本地持久化）。
- News 已接入（Finnhub，需 `FINNHUB_API_KEY`）；Community 部分接入 — CEO.ca（CA）LIVE，Seeking Alpha（US）LIVE 公开 combined RSS（article/news 元数据，非论坛帖；HTML/论坛为 PerimeterX 403），HotCopper（AU）、LSE Share Chat（UK）与 Xueqiu（CN/HK）为 honest stub（bot 拦截 / WAF / SPA 空壳，`collect()` 返回空）。
- 每日调度在单一 Web 服务进程内运行；生产环境仍需常开主机与持久 `/app/data` 卷。
- 无完整申报正文下载、全文搜索、XBRL 分析或 AI 功能。
- 当官方 SEC ticker 映射未提供 exchange 时，显示为 **Unavailable**。
- 运营日志持久化之前的较早活动不可用。
- 修订记录按 accession number 独立识别与标注；仅当未来存储的元数据显式提供该关系时才显示 original/amendment 关系。
