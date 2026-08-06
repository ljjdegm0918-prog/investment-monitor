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
and is skipped by collection. Finnhub is **US only**; SEC mapping is never
used to fake A-share or HK resolution.

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
  sharing a 14-digit receipt number fold in the feed with an "Also from"
  label; all database rows are kept.

### UK sources (UK)
| Source | Type | Key | Boundaries |
|---|---|---|---|
| companies_house | filings | `COMPANIES_HOUSE_API_KEY` — Test app keys authenticate only against `https://api-sandbox.company-information.service.gov.uk`; Live keys use the default live API | Statutory company filings (accounts, officers), **not RNS** |
| investegate | filings | none | RNS-class public mirror, not an official LSEG RNS feed; page scrape, may break without notice |
| uk_universe / FIRDS | breadth cache | none | No ticker mnemonics; ISIN-keyed plus a small blue-chip ticker seed; never enters the feed |
| yahoo_uk | news | none | Free public RSS mirror; may be loosely related and fragile; `.L` suffix added at request time only |
| Finnhub | news | existing | **US only** — never queried for UK |

UK feed soft-dedupe (display only, all rows kept): filings fold on RNS ids
(Investegate) or Companies House transaction ids; title fallback is
same-source only, so Companies House and Investegate are never cross-folded
by title. News folds on ticker + London day + normalized title.

Companies House mapping trust: a unique name search is **not** proof of the
listed issuer. Search-only mappings are stored as `unverified` and do not
collect CH filings until confirmed; seed tickers and explicit company numbers
are verified (`mapped`) after a successful profile check.

### Hong Kong sources (HK)
| Source | Type | Key | Boundaries |
|---|---|---|---|
| hkexnews | filings | none | Unofficial HKEXnews title-search JSON (not an official HKEX API/IIS feed); may change without notice; HKEX stock-id mapped when a match exists, otherwise unmapped |
| hk_universe | breadth cache | none | HKEXnews active/inactive stock lists; not an IBKR-complete universe (structured products / multi-counter cases may be partial); never enters the feed |
| yahoo_hk | news | none | Yahoo Finance HK public RSS mirror; may be loosely related and break without notice; `.HK` symbol added at request time only |
| hkex_di | filings | none | Public DI notice search under SFO Part XV on the legacy archive (2003-04-01 to 2017-10-02); **disabled by default**, enable explicitly for historical backfill; not HKEXnews title-search, not DION/IIS; fragile ASP.NET page, may break without notice |

HK tickers are canonical five-digit codes (`700` / `0700` / `00700` /
`0700.HK` all store as `00700`). The universe cache refreshes with
`refresh_hk_universe()` (default path `.cache/investment_monitor/hk_universe.json`).
Finnhub remains **US only** and is never queried for HK.

HK feed soft-dedupe (display only, all rows kept; same
`KR_FEED_SOFT_DEDUPE` switch as KR/UK, default on): hkexnews filings fold on
NEWS_ID, hkex_di on form serial; hkexnews and hkex_di are **never** folded
against each other by title; yahoo_hk news folds on ticker + Hong Kong day +
normalized title.

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
yet been attempted, then checks daily at 6:00 AM ET. The default seven-day
overlap safely catches delayed or missed filings; accession-number
deduplication prevents duplicate records.

Adding a company through a list page immediately performs a one-year SEC
metadata backfill. The company remains in the selected lists even if SEC is
temporarily unavailable, and the page reports the backfill failure separately.
These defaults can be adjusted in `.env`.

## Main web behavior

- **Today** groups by the user's browser timezone (IANA, e.g.
  `Asia/Shanghai`) and deduplicates across lists. Date-only disclosures
  (DART `rcept_dt`, Companies House filing dates, HKEX DI notice dates) are
  aligned by their disclosure `calendar_date`, so they never fall into the
  previous day through a UTC-midnight conversion; legacy rows at exactly
  `00:00 UTC` are treated as date-only with their UTC date as the disclosure
  day. Stored timestamps remain UTC-compatible.
- **All Information** provides historical server-side filters and stable
  pagination.
- **Holdings, Planned Purchases, Watchlist** manage many-to-many company-list
  memberships. Removing memberships never deletes stored filings.
- **Search** searches stored metadata only: ticker, company name, title, form,
  and accession number. Filing bodies are not downloaded or indexed.
- **Read/Unread** persists in SQLite. Opening an official filing marks it read;
  explicit individual and scoped bulk actions are also available.
- **Activity & Logs** shows only collection operations recorded after this web
  migration was introduced. It does not invent metrics for earlier CLI runs.
- **Data Sources** reports the latest real SEC attempt and success, marks SEC
  data stale after 36 hours, and marks News, Community, and Research as
  not connected until a real connector is enabled.
- Official filing links open in a new tab with `noopener` and `noreferrer`.

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
