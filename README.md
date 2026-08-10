# Investment Monitor

Investment Monitor is a local, list-centered workspace for monitoring financial
information. The first web MVP uses the SEC EDGAR connector already in this
project and leaves clear source boundaries for future News and Community
connectors.

The web interface is in English. It has three fixed lists:

- Holdings
- Planned Purchases
- Watchlist

One company may belong to any combination of these lists. One SEC filing is
stored once and shown with every applicable list badge, so belonging to several
lists does not duplicate the filing.

## What is connected

| Information type | Provider | Production status |
| --- | --- | --- |
| Filings | SEC EDGAR | Up to date after a recent sync; stale after 36 hours |
| News | Finnhub company news | Connected after a successful sync; needs `FINNHUB_API_KEY` |
| Community | None | Not connected |
| Research | None | Not connected |

The repository still contains mock connectors for automated extensibility
tests. They are not enabled in `config/settings.yaml`, and generated mock data
is excluded from the production web feed. A future real community connector
would use its own `source` name and `source_type="community"`; it would not be
labelled as SEC.

## Beginner setup

Open Terminal and enter the project:

```bash
cd "/Users/jiajunliu/Documents/New project/investment-monitor"
```

Check Python (3.9 or newer is required):

```bash
python3 --version
```

The project has no third-party runtime dependencies. SEC requires automated
clients to declare an application name and a real contact address. Create the
local environment file once:

```bash
cp .env.example .env
```

Open `.env` and replace `your-email@example.com` with a real contact address.
The web service automatically loads this file without overwriting environment
variables supplied by a hosting platform. The SEC connector keeps its timeout,
retry, cache, and maximum-five-requests-per-second controls. If a mapping-cache
refresh temporarily fails, the last valid local copy is used.

## 1. Configure the starting universe

Edit `config/universe.csv`:

```csv
ticker,list_type,market
AAPL,holdings,us
```

The CSV is an initial import only. It accepts 1-10 unique (ticker, market)
rows, and `list_type` must be `holdings`, `planned`, or `watchlist`. The
optional `market` column accepts `us`, `cn`, `hk`, or `unknown` and defaults
to `us`. After the first web
startup, active memberships in SQLite are the collection source of truth. A
company such as NVDA added in the web interface does not need to be added to
the CSV.

`config/settings.yaml` declares the logical sources (sec, news, community,
research), their enabled state, and selects the local SQLite file:

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

The News source is Finnhub company news. Set `FINNHUB_API_KEY` in `.env` (see
`.env.example`) to enable it; without a key the source stays Not connected
and is skipped by collection. Non-US markets (cn/hk) are mapped to Finnhub
symbols when possible (`.HK`, `.SS`/`.SZ`); SEC mapping is never used to fake
A-share or HK resolution.

### Korea sources (KR)
- OpenDART (`DART_API_KEY`): official disclosure API; corp_code mapping and
  disclosure list.
- KIND (KRX): key-free exchange disclosure page scrape; may break without
  notice.
- Naver Finance (`naver_news`): key-free stock news scrape; fragile, may be
  empty from non-KR networks. Hankyung/TheBell are implemented but disabled
  until their endpoints are reachable.
- Tradeable universe: cached from the OpenDART corpCode listing; ETF/ETN
  coverage is partial. FSC/data.go.kr is skipped because registration
  requires Korean identity.
- Feed soft-dedupe (default on, `KR_FEED_SOFT_DEDUPE`): OpenDART/KIND items
  sharing a 14-digit receipt number are annotated in the feed with an
  "Also seen on" label; every row stays (totals unchanged).

### UK sources (UK)
| Source | Type | Key | Boundaries |
|---|---|---|---|
| companies_house | filings | `COMPANIES_HOUSE_API_KEY` — Test app keys authenticate only against `https://api-sandbox.company-information.service.gov.uk`; Live keys use the default live API | Statutory company filings (accounts, officers), **not RNS** |
| investegate | filings | none | RNS-class public mirror, not an official LSEG RNS feed; page scrape, may break without notice |
| uk_universe / FIRDS | breadth cache | none | No ticker mnemonics; ISIN-keyed plus a small blue-chip ticker seed; never enters the feed |
| yahoo_uk | news | none | Free public RSS mirror; may be loosely related and fragile; `.L` suffix added at request time only |
| Finnhub | news | existing | **US only** — never queried for UK |

UK feed soft-dedupe (display only, all rows kept): filings annotate on RNS ids
(Investegate) or Companies House transaction ids; title fallback is
same-source only, so Companies House and Investegate are never cross-annotated
by title. News pairs on ticker + London day + normalized title.

### Hong Kong sources (HK)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| hkexnews | filings | none | Unofficial HKEXnews title-search JSON; may change without notice |
| hk_universe | breadth cache | none | HKEXnews active/inactive stock lists; never enters the feed |
| yahoo_hk | news | none | Yahoo Finance HK public RSS; `.HK` at request time |
| hkex_di | filings | none | Legacy DI archive 2003–2017; **disabled by default**; fragile |

HK tickers are canonical five-digit codes (`700` / `0700` / `00700.HK` →
`00700`). Finnhub is **US only**. Soft-dedupe: hkexnews on NEWS_ID, hkex_di on
form serial (never cross-paired by title); yahoo_hk on ticker + Hong Kong day.

### Canada sources (CA)

**Not a full Canadian market track.** Wired today: TSX/TSXV universe cache +
Yahoo/Google CA news + soft-dedupe. **Not wired:** SEDAR+ disclosure, CSE
universe/filings, NEO universe/filings (see boundaries below).

| Source | Type | Key | Boundaries |
|---|---|---|---|
| ca_universe | breadth cache | none | TSX + TSXV company directories via key-free official TMX JSON; **CSE** / **NEO** directories are not wired (TLS / origin failures); never enters the feed |
| yahoo_ca | news | none | Yahoo Finance CA public RSS (`region=CA`, `lang=en-CA`); `.TO` at request time (`.V` for TSXV boards from the universe cache, otherwise `.TO`); may be loosely related and break without notice |
| google_news_ca | news | none | Key-free Google News RSS search (`hl=en-CA&gl=CA&ceid=CA:en`); may be loosely related and break without notice |
| sedar_plus / cse_filings / neo_filings | filings | — | Listed in Settings as **Not implemented**. Regulatory disclosure is **deliberately not wired** (CA-1 spike, re-verified CA-4): SEDAR+ has no stable free public API (Radware 403); CSE/NEO filings share the same network blockers as their directories |

`market=ca` companies use canonical root tickers (`RY` / `RY.TO` / `RY-TO`
all store as `RY`). Board is written into `exchange` from
`ca_universe_name_map()` when warm, or inferred from the typed suffix when
cold. Companies remain unmapped. Finnhub is **US only** and never queried for
CA.

CA feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch, default on): `yahoo_ca` / `google_news_ca` news pairs across sources
on ticker + Toronto day (`America/Toronto`) + normalized title. Regulatory
filings are never annotated because no CA disclosure connector is wired.

### Taiwan sources (TW)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| twse_material | filings | none | TWSE OpenAPI material-information for **listed companies only**; key-free; OTC via tpex_material; 興櫃 not wired |
| tpex_material | filings | none | TPEx OpenAPI material-information for **OTC (上櫃)**; 興櫃 not wired |
| tw_universe | breadth cache | none | TWSE listed + TPEx OTC directories; emerging opt-in via env only; never enters the feed |
| yahoo_tw | news | none | Yahoo Finance TW public RSS (`region=TW`); `.TW`/`.TWO` at request time from board; may break without notice |
| google_news_tw | news | none | Key-free Google News RSS (`q={ticker}.TW`, zh-TW); may break without notice |

`market=tw` uses canonical four-digit tickers (`2330` / `02330` / `2330.TW`
→ `2330`). Finnhub is **US only**. Soft-dedupe: TWSE/TPEx filings are
same-source only (never cross-board by title); news pairs on ticker + Taipei
day + normalized title.

### Australia sources (AU)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| asx_announcements | filings | none | ASX company announcements via key-free research API; undocumented; latest 5 per company; may change without notice |
| au_universe | breadth cache | none | ASX company directory; never enters the feed |
| yahoo_au | news | none | Yahoo Finance AU public RSS (`region=AU`); `.AX` at request time |
| google_news_au | news | none | Key-free Google News RSS (`hl=en-AU&gl=AU&ceid=AU:en`) |

`market=au` uses canonical root tickers (`BHP` / `BHP.AX` → `BHP`). Finnhub
is **US only**. Soft-dedupe: ASX filings pair on document key (or same-source
title fallback); news pairs on ticker + Sydney day + normalized title.

### France sources (FR)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| amf_oam | filings | none | AMF OAM information feed (key-free; undocumented page API; may change); only wired FR disclosure source |
| fr_universe | breadth cache | none | Euronext live all-stocks CSV (Paris / Growth Paris / Access Paris); never enters the feed |
| yahoo_fr | news | none | Yahoo Finance FR public RSS (`region=FR`); `.PA` at request time |
| google_news_fr | news | none | Key-free Google News RSS (`hl=fr&gl=FR&ceid=FR:fr`) |

`market=fr` uses canonical root tickers (`MC` / `MC.PA` → `MC`; French ISINs
kept as-is). Add-company can backfill name/board from `fr_universe_name_map()`
when warm. Finnhub is **US only**. Soft-dedupe: AMF filings pair on OAM
document id (or same-source title fallback); news pairs on ticker + Paris day.

### Germany sources (DE)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_dgap | filings | none | EQS News JSON (ex-DGAP; key-free unofficial WP API; may change); only wired DE disclosure source; matched by ISIN |
| de_universe | breadth cache | none | Xetra `t7-xetr-allTradableInstruments.csv` common shares (CS); never enters the feed |
| yahoo_de | news | none | Yahoo Finance DE public RSS (`region=DE`); `.DE` at request time |
| google_news_de | news | none | Key-free Google News RSS (`hl=de&gl=DE&ceid=DE:de`) |

`market=de` uses canonical root tickers (`SAP` / `SAP.DE` → `SAP`; German ISINs
kept as-is). Add-company can backfill name/board/ISIN from `de_universe_name_map()`
when warm. Finnhub is **US only**. Soft-dedupe: EQS filings pair on news id
(or same-source title fallback); news pairs on ticker + Berlin day.
Unternehmensregister / BaFin HTML portals are **not** wired (no stable free JSON).

### Netherlands sources (NL)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_nl | filings | none | EQS News JSON by Dutch ISIN (key-free, unofficial WP API — may change; partial Dutch-issuer coverage; empty for issuers not on the platform; NOT an AFM official feed). AFM registers and Euronext announcement pages/APIs are not wired (no stable key-free JSON; Euronext web services are paid). NL-4 re-verified (2026-08-10): AFM registers are HTML-only, Euronext announcement pages use Drupal antibot and the guessed JSON endpoint 404s — no second free disclosure source. Needs ISIN from the NL universe cache or a typed Dutch ISIN. |
| nl_universe | breadth cache | none | Euronext live all-stocks CSV filtered to Amsterdam segment rows (key-free; live 2026-08-10: ~119 `Euronext Amsterdam` + ~16 multi-venue rows mentioning Amsterdam, e.g. `Euronext Amsterdam, Brussels`; non-Amsterdam boards, Global Equity Market, Trading After Hours and EuroTLX excluded); not an IBKR-complete universe; never enters the feed. |
| yahoo_nl | news | none | Yahoo Finance NL public RSS (`region=NL`, `lang=nl-NL` + `en-US` merged); `.AS` at request time; may be loosely related and break without notice |
| google_news_nl | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=nl&gl=NL&ceid=NL:nl`); may be loosely related and break without notice |

`market=nl` companies use canonical root tickers (`ASML` / `ASML.AS` /
`ASML-AMS` all store as `ASML`; exchange suffixes `.AS` / `.AMS` / `.AEA`
are stripped at add time, Dutch ISINs are kept as-is, board goes into
`exchange` when available) and remain unmapped;
`nl_universe_name_map()` backfills names, board and ISIN for add-company.
Finnhub is **US only** and never queried for NL. News comes from `yahoo_nl`
/ `google_news_nl`.

NL feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch as the other markets, default on): `yahoo_nl` / `google_news_nl` news
pairs across sources on ticker + Amsterdam day (`Europe/Amsterdam`) +
normalized title. `eqs_nl` filings pair on the stable EQS news id, or on a
same-source title fallback (ticker + Amsterdam day + normalized title);
with only one disclosure source wired there is no cross-source filing
pairing. Every row stays in the feed with an "Also seen on …" label;
totals and page sizes are never shrunk.

### Italy sources (IT)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_it | filings | none | EQS News JSON by Italian ISIN (key-free, unofficial WP API — may change; partial Italian-issuer coverage; empty for issuers not on the platform; NOT a Consob official feed). Consob public registers and Borsa Italiana/Euronext Milan announcement pages are not wired (no stable key-free JSON). IT-4 re-verified (2026-08-10): Consob serves a Radware captcha wall, Borsa Italiana is HTML-only, Euronext Milan announcement pages use antibot HTML — no second free disclosure source. Needs ISIN from the IT universe cache or a typed Italian ISIN. |
| it_universe | breadth cache | none | Euronext live all-stocks CSV filtered to Milan segment rows (key-free; live 2026-08-10: ~204 `Euronext Milan` + ~243 `Euronext Growth Milan`; filter also accepts `Borsa Italiana`/`Milano` labels if they ever appear; non-Italian boards, Global Equity Market, Trading After Hours and EuroTLX excluded); not an IBKR-complete universe; never enters the feed. |
| yahoo_it | news | none | Yahoo Finance IT public RSS (`region=IT`, `lang=it-IT` + `en-US` merged; identical titles stay single-language); `.MI` at request time; may be loosely related and break without notice |
| google_news_it | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=it&gl=IT&ceid=IT:it`); may be loosely related and break without notice |

`market=it` companies use canonical root tickers (`ENI` / `ENI.MI` /
`ENI-MIL` all store as `ENI`; exchange suffixes `.MI` / `.MIL` / `.BIT`
are stripped at add time, Italian ISINs are kept as-is, board goes into
`exchange` when available) and remain unmapped. Finnhub is **US only** and
never queried for IT. `it_universe_name_map()` backfills names, board and
ISIN for add-company. News comes from `yahoo_it` / `google_news_it`.

IT feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch as the other markets, default on): `yahoo_it` / `google_news_it` news
pairs across sources on ticker + Rome day (`Europe/Rome`) + normalized
title. `eqs_it` filings pair on the stable EQS news id, or on a same-source
title fallback (ticker + Rome day + normalized title); with only one
disclosure source wired there is no cross-source filing pairing. Every row
stays in the feed with an "Also seen on …" label; totals and page sizes are
never shrunk.

### Spain sources (ES)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| cnmv_hr | filings | none | CNMV official relevant-information RSS — inside information (IP) + other relevant information (OIR) feeds (key-free, official; live 2026-08-10). Records are keyed by issuer legal name (`Title`) with a stable `nreg` registration number; matched to requested tickers via the ES universe name/ISIN. The IP feed is sometimes empty for a day (honest `[]`). Not a paid MOPS-style push. |
| bme_relevant_facts | filings | none | Official BME relevant-facts JSON API (key-free; live 2026-08-10; same API family as the ES universe). Matched per company via the universe `companyKey`; records carry the same stable CNMV registration numbers (`IP`/`OI` prefixes) and CNMV detail deep links; date-only records use the Europe/Madrid noon anchor. The API clamps the requested range to at most ~31 calendar days, so older history is not available. Paid BME real-time/historical data services are deliberately not wired (ES-4 re-verified 2026-08-10). |
| es_universe | breadth cache | none | Official BME equity API (key-free; live 2026-08-10): `SIBE` (~123) + `Floor` (~5) + `Latibex` (~14) kept in full; `MTF` filtered to `BMEGrowth` (~111) + `BMEScaleUp` (~52); funds (SICAV/HedgeFunds/VCC) and other non-equity rows excluded. Tickers are enriched per ISIN from `ShareDetailsInfo` (rate-limited; reuses cached tickers; failed entries stay until next refresh). BME is a SIX company — the Euronext CSV family is NOT reused and no Madrid segment exists there. Not an IBKR-complete universe; never enters the feed. |
| yahoo_es | news | none | Yahoo Finance ES public RSS (`region=ES`, `lang=es-ES` + `en-US` merged; identical titles stay single-language); `.MC` at request time; may be loosely related and break without notice |
| google_news_es | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=es&gl=ES&ceid=ES:es`); may be loosely related (the `.MC` suffix also matches unrelated "MC" text) and break without notice |

`market=es` companies use canonical root tickers (`SAN` / `SAN.MC` /
`SAN-MAD` all store as `SAN`; exchange suffixes `.MC` / `.MAD` / `.BME`
are stripped at add time, Spanish ISINs are kept as-is, board goes into
`exchange` when available) and remain unmapped. Finnhub is **US only** and
never queried for ES. `es_universe_name_map()` backfills names, board and
ISIN for add-company; disclosure matching uses the universe identity
(name/ISIN for CNMV, company key for BME). News comes from `yahoo_es` /
`google_news_es`.

ES feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch as the other markets, default on): `yahoo_es` / `google_news_es` news
pairs across sources on ticker + Madrid day (`Europe/Madrid`) + normalized
title. `cnmv_hr` filings pair on the stable CNMV registration number
(`es:filing:cnmv:...`) and `bme_relevant_facts` on the same registration
number read from the BME JSON (`es:filing:bme:...`); the two sources are
never cross-annotated (independent APIs), and the title fallback is
source-scoped (ticker + Madrid day + normalized title). Every row stays in
the feed with an "Also seen on —" label; totals and page sizes are never
shrunk.

### Singapore sources (SG)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| sgx_announcements | filings | none | **Not wired (SG-1 spike A3; SG-4 re-verified 2026-08-10)**: SGX company announcements are a JS SPA; `api.sgx.com` routes return 403 (undocumented AWS Gateway, no stable free list endpoint), the legacy `infopub.sgx.com` SGXNet JSON is retired (TLS handshake fails), and `links.sgx.com/1.0.0/corporate-announcements/{id}` serves only per-announcement deep links/PDFs with no public list/search API. MAS/ACRA have no stable key-free per-issuer announcement feed. No production connector or second disclosure source is registered; SGX DataLink / LSEG / paid market-data products are deliberately not used (locked by tests). |
| sg_universe | breadth cache | none | **Boundary stub (SG-2 spike B2)**: no stable key-free SGX securities directory exists (`www.sgx.com/securities/*` is a JS SPA, the screener is Refinitiv/LSEG-powered; `api.sgx.com` 403; `data.gov.sg` has only aggregate SINGSTAT turnover; ACRA is the full company register without SGX codes). `load_sg_universe` / `sg_universe_name_map` / `search_sg_universe` read a local cache if one ever exists; `refresh_sg_universe` raises `SgUniverseError` instead of faking an STI-only universe. Never enters the feed. |
| yahoo_sg | news | none | Yahoo Finance SG public RSS (`region=SG`, `lang=en-SG` + `en-US` merged; identical titles stay single-language); `.SI` at request time; may be loosely related and break without notice |
| google_news_sg | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=en-SG&gl=SG&ceid=SG:en`); may be loosely related and break without notice |

`market=sg` companies use canonical root tickers (`D05` / `D05.SI` /
`D05-SG` all store as `D05`; exchange suffixes `.SI` / `.SG` are stripped
at add time, Singapore ISINs are kept as-is; SGX codes vary in length so no
fixed width is assumed) and remain unmapped. Finnhub is **US only** and
never queried for SG. News comes from `yahoo_sg` / `google_news_sg`. SG
feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch as the other markets, default on): `yahoo_sg` / `google_news_sg`
news pairs across sources on ticker + Singapore day (`Asia/Singapore`) +
normalized title. No SG disclosure connector is wired, so regulatory
filings never get a dedupe key and are never annotated. Every row stays in
the feed with an "Also seen on —" label; totals and page sizes are never
shrunk.

### Switzerland sources (CH)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| eqs_ch | filings | none | EQS News JSON by Swiss ISIN (key-free, unofficial public WP API; may change without notice; **partial Swiss coverage** — live 2026-08-10 Roche/UBS return records, Nestlé/Novartis return empty lists; NOT a SIX Exchange Regulation / FINMA official feed). SIX official channels have no stable free JSON (official-notices page is a React SPA; `api.six-group.com` routes undocumented; SIX equity-issuer news is the paid Exfeed product) — CH-4 re-verified 2026-08-10, no second disclosure source. Needs ISIN from the CH universe cache or a typed Swiss ISIN. |
| ch_universe | breadth cache | none | **Boundary stub (CH-2 spike B2)**: no stable key-free SIX securities directory exists (`six-group.com/market-data/shares/*` are React SPAs; share-explorer detail pages expose name/ticker/ISIN in meta tags but no board; `api.six-group.com` routes are undocumented 404s; SIX market-data APIs and the equity-issuer-news Exfeed product are paid). `load_ch_universe` / `ch_universe_name_map` / `search_ch_universe` read a local cache if one ever exists; `refresh_ch_universe` raises `ChUniverseError` instead of faking an SMI-only universe. Never enters the feed. |
| yahoo_ch | news | none | Yahoo Finance CH public RSS (`region=CH`, `lang=de-CH` + `en-US` merged; identical titles stay single-language); `.SW` at request time; may be loosely related and break without notice |
| google_news_ch | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=de&gl=CH&ceid=CH:de`; `de-CH`/`fr-CH`/`en` variants redirect, so the live-locked German-Swiss edition is used); may be loosely related and break without notice |

`market=ch` companies use canonical root tickers (`NESN` / `NESN.SW` /
`NESN-SWX` all store as `NESN`; exchange suffixes `.SW` / `.SWX` / `.S`
are stripped at add time, Swiss ISINs are kept as-is) and remain unmapped.
Finnhub is **US only** and never queried for CH. News comes from `yahoo_ch`
/ `google_news_ch`.

CH feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE`
switch as the other markets, default on): `yahoo_ch` / `google_news_ch`
news pairs across sources on ticker + Zurich day (`Europe/Zurich`) +
normalized title. `eqs_ch` filings pair on the stable EQS news id, or on a
same-source title fallback (ticker + Zurich day + normalized title); with
only one disclosure source wired there is no cross-source filing pairing.
Every row stays in the feed with an "Also seen on —" label; totals and page
sizes are never shrunk.

### Poland sources (PL)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `gpw_espi` | Filings | None (key-free) | Official GPW ESPI/EBI reports page (`www.gpw.pl/komunikaty`, server-rendered HTML list, ISIN-filterable via `searchText=` + `limit=`/`offset=`; live verified 2026-08-10). Matches by Polish ISIN from the PL universe cache (the list shows issuer name + ISIN, not ticker mnemonics); companies without a universe ISIN are skipped honestly (`no_universe_identity`). Europe/Warsaw day bounds; stable `geru_id` external ids; deep link to the report page (`komunikat?geru_id=...`, which also exposes attachment PDF paths). The PL-1 A3 boundary was based on `espi.gpw.pl` TLS failure and empty EQS records; PL-4 re-spike found this page reachable. `espi.gpw.pl` itself remains unreachable, EQS is still empty for sampled Polish ISINs, KNF has no per-issuer feed, and GPW paid data products are not used. |
| `pl_universe` | Universe | None (key-free) | Official GPW HTML directories, breadth only (never written to the feed): GPW Main Market (`www.gpw.pl/spolki?limit=403`, ~400 companies; observed 401–403 live 2026-08-10) and NewConnect (`newconnect.pl/spolki?limit=403`, ~350 companies; observed 348–349). Both are server-rendered tables with ISIN/name/mnemonic ticker; the old `lista-spolek*` URLs return a 404 shell and the `ajaxindex.php` search endpoint rejects non-browser clients, so only the public GET pages are used. The GPW hosts also drop TLS connections intermittently from this network (a refresh may need a retry; per-board partial failure keeps the other board and only a full failure raises `PlUniverseError`). No WIG20/WIG30 seed and no paid GPW data product. Refreshed via `refresh_pl_universe()`; `pl_universe_name_map()` backfills name/board/ISIN on add-company and drives `gpw_espi` disclosure matching. `market=pl` companies use canonical root tickers (`PKO` / `PKO.WA` / `PKO-GPW` all store as `PKO`; exchange suffixes `.WA` / `.WSE` / `.GPW` are stripped at add time, Polish ISINs are kept as-is) and remain unmapped. Finnhub is **US only** and never queried for PL. |
| `yahoo_pl` | News | None (key-free) | Yahoo Finance PL public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.WA&region=PL&lang=pl-PL`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`PKO`), `.WA` is request-time only. |
| `google_news_pl` | News | None (key-free) | Google News PL RSS (`news.google.com/rss/search?q={ROOT}.WA&hl=pl&gl=PL&ceid=PL:pl`). Live verified 2026-08-10; results can be loosely related (a `PKO.WA` query can include unrelated PKO BP Ekstraklasa football items); public RSS may break without notice. |

PL feed soft-dedupe is display-only ("Also seen on"; all rows are kept and totals/page sizes never shrink; shared switch `KR_FEED_SOFT_DEDUPE`). Filings: `gpw_espi` pairs on its stable GPW report id (`geru_id`); the title fallback is source-scoped (source + ticker + Warsaw day + normalized title), so a hypothetical second PL disclosure source would never be cross-annotated by title. News: `yahoo_pl` ↔ `google_news_pl` pair across sources on ticker + Warsaw day + normalized title.

### Sweden sources (SE)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `fi_oam` | filings | none | **Not wired (SE-1 spike A3, re-verified in SE-4)**: FI's public publication client (`marknadssok.fi.se/publiceringsklient`) only searches insider transactions (Insyn), not issuer announcements; Nasdaq Nordic company news is a Drupal SPA without a public JSON route (`webproxy/DataSubsidiesNews/GetNews.aspx` returns the SPA shell, `api.nasdaq.com` returns 404 for `.ST` symbols); the legacy `newsclient.omxgroup.com` disclosure search returns HTTP 500; EQS News returns empty records for every sampled Swedish ISIN (ERIC-B / VOLV-B / SEB-A / Investor-B / H&M-B / Boliden / Getinge-B / Volvo Car-B, verified 2026-08-10). SE-4 re-check (2026-08-10) found no second free disclosure source: EQS still empty, the legacy Hugin host (`cws.huginonline.com`) exposes no stable public announcement API, and Nasdaq paid data products are not used. |
| `se_universe` | Universe | None | **Boundary stub (SE-2 spike B2)**: Nasdaq Stockholm / First North Sweden directories are Drupal SPAs whose screener data route is not publicly reachable (`api.nasdaq.com/api/screener/shares` 404; `api.nasdaq.com/api/screener/stocks` returns zero rows for Stockholm exchange codes; `nasdaqomxnordic.com/screener/shares` returns the SPA shell). FI publishes no securities directory. `refresh_se_universe()` raises `SeUniverseError`; `load_se_universe()` / `se_universe_name_map()` / `search_se_universe()` read a manually placed cache if one ever exists. No OMXS30 hand-written seed and no Nasdaq paid data product. |
| `yahoo_se` | News | None (key-free) | Yahoo Finance SE public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.ST&region=SE&lang=sv-SE`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10 with `ERIC-B.ST`; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`ERIC-B`), `.ST` is request-time only; share-class mnemonics like `ERIC-B` / `VOLV-B` are kept intact. |
| `google_news_se` | News | None (key-free) | Google News SE RSS (`news.google.com/rss/search?q={ROOT}.ST&hl=sv&gl=SE&ceid=SE:sv`). Live verified 2026-08-10; results can be loosely related (an `ERIC-B.ST` query can include football items about a player named Eric Smith); public RSS may break without notice. |

`market=se` companies use canonical root tickers (`ERIC-B` / `ERIC-B.ST` / `eric-b.sto` all store as `ERIC-B`; exchange suffixes `.ST` / `.STO` / `.OMX` / `-ST` etc. are stripped at add time while share-class suffixes like `-B` / `-A` are preserved, Swedish ISINs are kept as-is) and remain unmapped. Finnhub is **US only** and never queried for SE.

SE feed soft-dedupe is display-only ("Also seen on"; all rows are kept and totals/page sizes never shrink; shared switch `KR_FEED_SOFT_DEDUPE`). Filings are never annotated because no SE disclosure connector is wired (SE-1 A3 / SE-4 D2). News: `yahoo_se` ↔ `google_news_se` pair across sources on ticker + Stockholm day + normalized title.

### Belgium sources (BE)

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `fsma_stori` | Filings | None (key-free) | Official FSMA STORI (Belgian central storage of regulated information, `webapi.fsma.be/api/v1/<lang>/stori/result`; powers the public `fsma.be/en/stori` portal). Matches by Belgian ISIN or company name — never by ticker mnemonic (`ABI` does not match `AB INBEV`). A BE ISIN typed as the ticker works now; mnemonic tickers get an ISIN/name from the BE universe cache (BE-2) once it is refreshed and are otherwise skipped honestly (`no_universe_identity`). Europe/Brussels day bounds, stable document ids (`requiredReportingTopicId`), dates constrained server- and client-side. Undocumented JSON surface; may change without notice. `market=be` companies use canonical root tickers (`ABI` / `ABI.BR` / `ABI-BRU` all store as `ABI`; exchange suffixes `.BR` / `.BRU` / `.EBR` are stripped at add time, Belgian ISINs are kept as-is) and remain unmapped. Finnhub is **US only** and never queried for BE. |
| `be_second_disclosure` | Filings | None | **Not wired (BE-4 re-verified 2026-08-10)**: no stable key-free second Belgian disclosure source exists. Euronext Brussels announcements are Drupal HTML pages keyed by per-company node IDs - no RSS (public RSS paths 404) and no JSON export (`_format=json` returns 406); the key-free EQS News JSON API (same family as the NL/IT connectors) returns zero records for every sampled Belgian ISIN, including BEL 20 names (ABI/KBC/UCB/Solvay/Ageas/Argenx and others); FSMA STORI remains the only official machine-readable feed. Paid feeds (Euronext Web Services/Saturn real-time or historical data, FinancialReports.eu, LSEG) are deliberately not wired. |
| `be_universe` | breadth cache | none | Euronext live all-stocks CSV filtered to Brussels segment rows (key-free; live 2026-08-10: ~95 `Euronext Brussels` + ~5 `Euronext Growth Brussels` + ~8 `Euronext Access Brussels` + ~25 multi-venue rows mentioning Brussels, e.g. `Euronext Paris, Brussels` / `Euronext Amsterdam, Brussels`; non-Brussels national boards, Global Equity Market, Trading After Hours, EuroTLX and Euronext Expert Market excluded); not an IBKR-complete universe; never enters the feed. |
| yahoo_be | news | none | Yahoo Finance BE public RSS (`region=BE`, `lang=fr-BE` + `en-US` merged; identical titles stay single-language); `.BR` at request time; may be loosely related and break without notice |
| google_news_be | news | none | Key-free Google News RSS search (`q={symbol}`, `hl=en-BE&gl=BE&ceid=BE:en`); may be loosely related and break without notice |

`market=be` feed soft-dedupe (display only, all rows kept; same `KR_FEED_SOFT_DEDUPE` switch as the other markets, default on): `yahoo_be` / `google_news_be` news pairs across sources on ticker + Brussels day (`Europe/Brussels`) + normalized title. FSMA STORI filings pair on the stable STORI document id (`external_id` = `requiredReportingTopicId`); without an id the fallback is source-scoped (source + ticker + Brussels day + normalized title), so a hypothetical second BE disclosure source is never cross-annotated by title. Every row stays in the feed with an "Also seen on" label; totals and page sizes are never shrunk.

### Aquis sources (AQ)

`market=aq` targets **Aquis Stock Exchange (AQSE)** issuers, not the Aquis
Exchange MTF pan-European trading venue. Companies use canonical root
tickers (`ADB` / `ADB.AQ` / `adb-aq` all store as `ADB`; the `.AQ` exchange
suffix is stripped at add time while AQSE mnemonics stay as-is and
12-character ISINs are kept as-is) and remain unmapped. Finnhub is **US
only** and never queried for AQ.

| Source | Type | Key | Boundaries |
|---|---|---|---|
| `aq_disclosure` | Filings | none | **Not wired (AQ-1 spike A3, 2026-08-10)**: the official AQSE announcements page (`www.aquis.eu/stock-exchange/announcements`) is a server-rendered HTML list (Date / Title / View rows, key-free), but `www.aquis.eu` and `embed.aquis.eu` sit behind a Vercel bot challenge — stdlib/curl clients get HTTP 429 with `X-Vercel-Mitigated: challenge` and a JS proof-of-work checkpoint; no key-free official JSON/RSS exists (`embed.aquis.eu/api/*` returns the same challenge; `api.aquis.eu` / `data.aquis.eu` abort TLS). LSE/Investegate/Companies House are deliberately **not** used as Aquis substitutes, and no paid Aquis data product is wired. |
| `aq_second_disclosure` | Filings | none | **Not wired (AQ-4 re-verified D2, 2026-08-10)**: no stable key-free second AQSE disclosure source appeared. The official announcements page and the market-notices page (`embed.aquis.eu/stock-exchange/rules-and-regulations/market-notices`) still return HTTP 429 (`X-Vercel-Mitigated: challenge`); no official RSS/JSON exists; third-party mirrors (Investegate / uk-wire / Proactive) are deliberately not wired as Aquis disclosure, and paid Aquis data products are excluded. |
| `aq_universe` | Universe | none | **Wired (AQ-2, partial unofficial mirror)**: `refresh_aq_universe()` fetches `https://www.ticker.app/aqse` (server-rendered Name / TIDM / ISIN table; key-free). Live 2026-08-10: ~79 unique AQSE instruments, 61 with ISIN; the official Aquis directory (`embed.aquis.eu/companies`) renders ~90 names but is behind a Vercel bot challenge for stdlib/curl clients, so completeness is **not verified** — this is a partial mirror, never a full AQSE universe, and no LSE/UK directory is filtered in. Board/exchange stored as `AQSE`; never enters the feed; backfills name/exchange/ISIN on add-company. |
| `yahoo_aq` | News | None (key-free) | Yahoo Finance AQ public RSS (`feeds.finance.yahoo.com/rss/2.0/headline?s={ROOT}.AQ&region=GB&lang=en-GB`, plus `lang=en-US`; identical titles are merged as a single language, never fake bilingual). Live verified 2026-08-10 with `ADB.AQ`; loosely related results possible; public RSS may break without notice. Stored ticker is always the canonical root (`ADB`), `.AQ` is request-time only. |
| `google_news_aq` | News | None (key-free) | Google News AQ RSS (`news.google.com/rss/search?q={ROOT}.AQ&hl=en-GB&gl=GB&ceid=GB:en`). Live verified 2026-08-10; results can be loosely related; public RSS may break without notice. |

The web Settings page shows Provider credentials for every implemented source
The web Settings page shows Provider credentials for every implemented source
(each connector declares its own fields, currently `FINNHUB_API_KEY` and
`SEC_USER_AGENT`); unimplemented sources are shown as Not implemented and
cannot be configured. An advanced section allows extra environment variables
for connectors that explicitly read them. Values saved in the workspace
database take priority over `.env` for the running process and are never
returned in full by any API response.

## 2. Optional manual SEC collection

Choose an inclusive filing-date range:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m investment_monitor.cli \
  --start-date 2025-07-27 \
  --end-date 2026-08-02
```

This command remains useful for an explicit initial range. It reads the initial
CSV, runs the SEC connector, stores standardized `InformationItem` records,
records truthful collection activity, and also
updates the legacy standalone report at `output/announcements.html`.

Typical successful collection output includes lines like:

```text
INFO collection source=sec ticker=AAPL status=success items=... inserted=... updated=...
collected=... failures=0 stored_total=... report=output/announcements.html
```

Re-running the same range updates records with the same `(source,
external_id)` identity instead of inserting duplicates.

## 3. Start the web interface

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m investment_monitor.web \
  --host 127.0.0.1 \
  --port 8765
```

Successful startup prints:

```text
Investment Monitor running at http://127.0.0.1:8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in a browser. Keep the
Terminal window open while using the site. Press `Control-C` to stop it.

While the service is running it performs one incremental collection per
Eastern calendar day. On startup it catches up if the current ET day has not
yet been attempted, then checks daily at 6:00 AM ET. To preview the stored data
without making external collection requests, start it with
`AUTO_DAILY_COLLECTION=false`.

Adding a company through a list page immediately performs a one-year SEC
metadata backfill. The company remains in the selected lists even if SEC is
temporarily unavailable, and the page reports the backfill failure separately.
These defaults can be adjusted in `.env`.

## Main web behavior

- **Daily information** selects one Eastern Time calendar day and an optional
  list, hides companies without updates, groups the remaining items by company,
  and shows only time, type, source, title, and original URL. The print action
  uses a dedicated layout suitable for browser PDF export.
- **Lists & sources** creates, renames, deletes, and switches lists. A company
  may belong to multiple lists; removing a membership never deletes stored
  information.
- Company candidates are searched from the local official SEC mapping by name
  or ticker and from already-known companies by name, ticker, or recorded
  exchange. The user confirms a candidate before it is added.
- Source cards report each configured connector separately, including its
  coverage region, enabled state, latest attempt and success, and persisted
  failure summary.
- Official links open in a new tab with `noopener` and `noreferrer`.

## Official EDINET connector

The `edinet` package uses only EDINET API v2 for disclosure metadata and
documents. Configure `EDINET_API_KEY` in `.env`; never commit the key. The
login-oriented API requests every Japanese file date intersecting the absolute
time window, filters by `submitDateTime`, and matches filer, issuer, subject,
and subsidiary EDINET-code roles without a `docTypeCode` whitelist:

```python
result = connector.getWatchlistDisclosuresSince(
    companies=user.watchlist,
    since=now - timedelta(hours=24),
    now=now,
    include_downloads=False,
)
```

The indexed-first implementation stores date-level completeness in SQLite and
uses a short cache before falling back to the official API. A failed date is
reported through `partial` and `errors`; successful dates are still returned.
See `examples/edinet_login.py` for a complete login hook.

CLI examples:

```bash
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli refresh-codes
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli \
  login-feed --watchlist 7203,6758,9984 --since 24h
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli \
  sync --from 2024-01-01 --to 2024-12-31
PYTHONPATH=src python3 -m investment_monitor.sources.edinet.cli sync --incremental
```

Downloads are opt-in. Types `1` through `5` are passed through to the official
v2 endpoint; stored payloads include SHA-256, size, content type, and ZIP
integrity state under `data/downloads/edinet/{fileDate}/{docID}/type-{n}/`.

The official EDINET code-list ZIP is imported into the same SQLite database for
exact EDINET code, securities code, JCN, and filer-name resolution. Ambiguous
or unknown inputs are returned in `unresolved` rather than silently dropped.

## TDnet operating mode

TDnet collection uses the official JPX public list as its source of truth. Its
official declared count, contiguous pagination, and parsed-row count remain
fail-closed checks. The optional non-official Yanoshin comparison is disabled
by default (`TDNET_YANOSHIN_CROSSCHECK_ENABLED=false`), so third-party downtime
cannot block otherwise complete official JPX collection.

## Data model and safe migration

The standardized item tables now carry `market`, nullable `summary`, and
`effective_at` in addition to the original columns:

```text
information_items -- unique (source, external_id)
information_item_tickers
```

`companies` has a `market` column and a unique `(ticker, market)` identity, so
the same code in different markets is never conflated. The idempotent startup
migration upgrades existing single-market databases without deleting stored
SEC records.

The idempotent web migration adds:

```text
companies
system_lists
company_list_memberships      Company <-> List
information_read_state
ingestion_runs
ingestion_logs
app_settings
```

The migration uses `CREATE TABLE IF NOT EXISTS` and inserts the three fixed
lists idempotently. It does not drop or rewrite existing SEC records. SQL lives
at `src/investment_monitor/migrations/001_web_mvp.sql` and is packaged with the
application.

SEC-specific HTTP and mapping code remains under:

```text
src/investment_monitor/sources/sec/
```

The generic collection pipeline still depends only on `SourceConnector` and
`InformationRepository`. The web query layer reads standardized records from
SQLite and does not call the SEC connector to render pages.

## Run automated tests

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

The normal suite uses saved SEC fixtures and does not require internet. A
successful run ends with:

```text
Ran ... tests in ...s

OK (skipped=1)
```

The skipped test is the optional live SEC integration test. The suite covers
fixed-list idempotency, cross-list deduplication, partial ticker resolution,
membership removal without history deletion, Eastern Time boundaries,
persistent read state, scoped bulk updates, search, stable pagination,
production exclusion of mocks, source states, and core HTTP/static routes.

## Run without keeping your computer on

The production pattern is to run this same service on an always-on Linux server
or a container hosting platform with a persistent disk. The included
`Dockerfile` packages the web service and its daily collector together.

For a quick local container check:

```bash
docker build -t investment-monitor .
docker run -d \
  --name investment-monitor \
  --restart unless-stopped \
  --env-file .env \
  -p 8765:8765 \
  -v investment-monitor-data:/app/data \
  investment-monitor
```

Running this command on your own computer still requires that computer to stay
on. To make the site continuously available to other people, deploy the image
to a VPS or a container host, attach a persistent volume at `/app/data`, set
`SEC_USER_AGENT` there, and place HTTPS/access control in front of it. SQLite is
appropriate for one small application instance; do not run several replicas
against the same SQLite file.

## Suggested manual acceptance test

1. Start the server and open Today.
2. Open Holdings and add `AAPL, MSFT BADTICKER` to Holdings and Watchlist.
3. Confirm valid mapped tickers succeed and the unresolved ticker has its own
   error without rolling back successful additions.
4. Confirm a company in both lists has both badges but each filing appears
   once.
5. Mark one filing read, refresh, and confirm it remains read everywhere.
6. Use filtered **Mark all in scope as read** and verify unrelated list items
   remain unread.
7. Remove a company from Holdings and confirm it remains in Watchlist.
8. Remove it from all lists and confirm the action says historical information
   is preserved.
9. Open Data Sources and confirm SEC is the only configured provider; News and
   Community say Not connected.

## Known first-MVP limitations

- No authentication or multi-user read state (single-user local persistence).
- No News or real Community connector yet.
- Daily scheduling runs inside the single web-service process; production still
  requires an always-on host and a persistent `/app/data` volume.
- No full filing-text download, full-text search, XBRL analysis, or AI features.
- Exchange is shown as **Unavailable** when the official SEC ticker mapping does
  not provide it.
- Older activity from before operational-log persistence is unavailable.
- Amendment records are identified and labelled independently by accession
  number; an original/amendment relationship is shown only if future stored
  metadata provides that relationship explicitly.
