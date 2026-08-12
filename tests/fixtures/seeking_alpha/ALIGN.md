# ALIGN: Seeking Alpha (US) community connector — alignment brief

Status: **STUB ALIGNMENT PACK** (Worker E). No code applied yet.
`seeking_alpha` is NOT implemented; this is the brief an implementer follows
on the next pass. The two reference connectors are `hotcopper_au` (registered
STUB) and `ceoca_ca` (LIVE), both already on `main`.

Source files read for this brief (all paths relative to repo root):

- `src/investment_monitor/sources/ceoca_ca/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/hotcopper_au/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/lse_share_chat/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/xueqiu/{connector,parser,__init__}.py`
- `src/investment_monitor/{models,registry,config,dedupe,web_repository}.py`
- `tests/test_ceoca_ca.py`, `tests/test_hotcopper_au.py`,
  `tests/test_lse_share_chat.py`, `tests/test_xueqiu.py`
- `tests/fixtures/ceoca/{SPIKE.md,shop_spiels_sample.json}`,
  `tests/fixtures/hotcopper/{SPIKE.md,bhp_board_2026-02-17.html}`,
  `tests/fixtures/lse_share_chat/{SPIKE.md,ALIGN.md,bp_board_2026-02-17.html}`,
  `tests/fixtures/xueqiu/{SPIKE.md,ALIGN.md,probe.py}`
- `config/settings.yaml` (community entries)

---

## 1. InformationItem fields for a community source (target: US)

`InformationItem` (dataclass, `src/investment_monitor/models.py:79-106`) is the
single shared shape. Both reference connectors fill it identically; the Seeking
Alpha connector must fill it the same way with `market=MARKET_US` (`"us"`,
`models.py:12`).

Canonical field values (from `ceoca_ca/connector.py:110-152` `map_rows` —
treat as the live-path template; `hotcopper_au` matches with `stub` notes):

| Field | Value | Notes |
|---|---|---|
| `source` | `self.name` (`"seeking_alpha"` for the new connector) | registry/config name |
| `source_type` | `"community"` | constant |
| `document_type` | `"community_post"` | constant (both refs) |
| `external_id` | `f"seeking-alpha-{row.<native-id>}"` style | prefix `<provider>-<native-id>`; see section 6 key rules |
| `tickers` | `(code,)` — normalized US root (see section 3) | tuple, 1 element |
| `issuer` | `code` (normalized root) | both refs use root code |
| `published_at` | row timestamp `.astimezone(timezone.utc)` | **aware UTC** |
| `title` | post title (capped, e.g. 500 chars) | hotcopper caps `row.title[:500]` |
| `url` | stable public URL | per-source template (see section 2) |
| `collected_at` | `datetime.now(timezone.utc)` | once per `collect()` |
| `raw_metadata` | `{"provider": "seeking_alpha", "<native-key>": <native-id>, "stock_code": code, ...}` | both refs include provider + native id + stock_code; stub adds `"stub": True` |
| `market` | `MARKET_US` | **required**; `InformationItem.__post_init__` validates against `ALLOWED_MARKETS` |
| `summary` | optional, `(body)[:500]` or `None` | ceoca caps at `MAX_SUMMARY_LEN = 500` |
| `effective_at` | same UTC value as `published_at` | both refs set it |

Constants to copy per-connector (module scope): `LOGGER =
logging.getLogger(__name__)`, `NEW_YORK = ZoneInfo("America/New_York")` (see
section 4), and an `ARTICLE_URL_TEMPLATE` / `BOARD_URL_TEMPLATE` for `url`.

## 2. Stub vs LIVE connector shape

Both reference connectors expose the same public surface; only the body of
`collect()` differs:

| Member | `hotcopper_au` (STUB) | `ceoca_ca` (LIVE) |
|---|---|---|
| class attrs | `name`, `provider`, `status = "stub"` | `name`, `provider`, `status = "live"` |
| `collect(request)` | no network; per-ticker appends `(code, "...stub: URL returns HTTP 403...")` note; `self._last_errors = tuple(notes)`; returns `[]` | per-ticker: normalize -> market check (`if market != MARKET_CA: continue`) -> fetch -> `map_rows`; failures appended as `(ticker, message)`; returns items |
| `last_errors` property | `Tuple[Tuple[str, str], ...]` | same (empty tuple on success) |
| error escalation | none (stub) | single ticker + any failure -> raise `CeocaRequestError(failures[0][1])` |
| mapping helper | `map_rows_for_tests(rows, ticker=..., collected_at=...)` | `map_rows(rows, ticker=..., collected_at=...)` |
| skip log | — | `LOGGER.info("ceoca_ca ticker=%s market=%s skipped not_ca_market", ...)` |

`last_errors` is always a tuple of `(ticker, message)` pairs, never a list,
and never leaks HTTP bodies. `_last_errors` is initialized in `__init__`.

For `seeking_alpha`:
- The expected result is **STUB** (Seeking Alpha discussion/comment sections
  are behind Cloudflare bot protection and/or login walls for automated
  clients, consistent with the AU/UK/CN community spike verdicts). Mirror
  `hotcopper_au` exactly — `status = "stub"`, `collect()` returns `[]`,
  `last_errors` carries the honest reason including the documented URL and
  the Cloudflare / login-wall observation from the spike.
- The honest reason string must mention: Cloudflare bot protection on
  ticker discussion pages, that comments/posts require JS execution or
  login to access, and that captcha/login/Cloudflare bypass is out of scope
  (same honesty bar as `hotcopper_au`, `lse_share_chat`, and `xueqiu`).

Do NOT invent a third shape: `status` in {"stub", "live"} and the
`last_errors` tuple contract are what tests and the settings / Data Sources UI
already assume.

## 3. US ticker normalize rule — REUSE the existing pattern, minimal helper

Facts from the repo:

1. **There is NO `normalize_us_ticker` in `web_repository.py`** (grep for
   `normalize_us` / `_US_TICKER` finds nothing; the existing normalizers are
   au/be/ca/ch/cxe/de/emf/es/eux/fr/hk/it/nl/pl/se/sg/trq/tw/uk only).
2. **US tickers in `add_companies_batch` are NOT normalized** — there is no
   `if market == MARKET_US` normalization block (see `web_repository.py:580-651`;
   the HK/AU/BE/FR/DE/NL/IT/ES/SG/CH/PL/SE/AQ/CXE/EMF/TRQ/EUX/TW/CA branches
   each call their respective normalizer, but the US path is absent). US
   tickers flow through as-is (uppercased by `CollectionRequest.__post_init__`).
3. US tickers are plain 1–5 letter symbols (e.g. `AAPL`, `MSFT`, `GOOGL`,
   `BRK-B`, `BF-A`). Unlike CA/UK/AU tickers there is no exchange suffix to
   strip — the canonical form is simply the uppercased root.

**Recommended helper — add `normalize_us_ticker` to `web_repository.py`**
right before `normalize_au_ticker` (line 1988, the first normalizer), so the
family stays alphabetical:

```python
def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US ticker symbol to its canonical root form.

    US tickers are plain 1–5 letter symbols (``AAPL``, ``MSFT``) sometimes
    with a share-class hyphen (``BRK-B``, ``BF-A``). There is no exchange
    suffix to strip; the canonical form is the uppercased, whitespace-stripped
    symbol. Non-conforming input is preserved unchanged rather than silently
    dropped.
    """
    return str(ticker).strip().upper()
```

That is the exact 3-line core with docstring. It lives at the head of the
market normalizer family and is imported by the Seeking Alpha connector the
same way the CA connector imports `normalize_ca_ticker`. It also future-proofs
the US path in `add_companies_batch` (a `market == MARKET_US` branch can be
added later to match the AU/HK/CA pattern if the universe grows).

## 4. America/New_York day filter — mirror Toronto/Sydney/London

Pattern to mirror (identical in every market, different zone):

- Sydney: `sydney_day(moment)` in `hotcopper_au/connector.py:108-112`
  (naive -> assume UTC, then `.astimezone(SYDNEY).date()`); parser filters
  `published.astimezone(SYDNEY).date() != on_date`
  (`hotcopper_au/parser.py:80`).
- Toronto: `toronto_day(moment)` in `ceoca_ca/parser.py:74-78`; parser filter
  `published_at.astimezone(TORONTO).date() != on_date`
  (`ceoca_ca/parser.py:54`).
- London: `london_day(moment)` in `lse_share_chat/connector.py:110-114`;
  parser filter `published_at.astimezone(LONDON).date() != on_date`.

For Seeking Alpha use `ZoneInfo("America/New_York")` — the canonical US
equity market timezone (NYSE/Nasdaq trading hours and market-close
reference). Add, in the Seeking Alpha connector module (and parser if
separate):

```python
NEW_YORK = ZoneInfo("America/New_York")


def new_york_day(moment: datetime) -> date:
    """Calendar day in America/New_York for US community day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(NEW_YORK).date()
```

and in the parser row loop: skip rows where
`row.published_at.astimezone(NEW_YORK).date() != on_date`. This keeps US
community items on the same New-York-day clock as the rest of the US feed.

Note: `dedupe.py` does not currently define a New_York zone constant (US
news/filing keys are not yet wired), so define it at module scope in the
connector. The US news/filing `_news_key` path (when later wired) will need
to add `"us"` to the `dedupe_key` allowed-markets set and pick
`NEW_YORK` in the `_news_key` zone cascade — but that is **out of scope**
for this community-only brief (see section 6 for the community-key change
that IS in scope).

## 5. Registry + settings.yaml skeleton (NOT applied yet)

This section is the checklist an implementer follows; nothing in it is
committed yet. The `seeking_alpha` entry is **not** registered and not in
`settings.yaml` as of this brief — apply only when the orchestrator approves.

Wiring points (every one required, in the same pattern as AU/CA/UK/CN-HK):

1. **`src/investment_monitor/sources/seeking_alpha/__init__.py`** exports
   the connector (+ parser helpers), with a module docstring stating the STUB
   verdict like `hotcopper_au/__init__.py`.
2. **`src/investment_monitor/registry.py`** — import the connector and add
   `registry.register(SeekingAlphaConnector.name, SeekingAlphaConnector)`
   next to `CeocaCaConnector` / `HotCopperAuConnector` /
   `LseShareChatConnector` / `XueqiuConnector` (line 236).
3. **`config/settings.yaml`** — add a community block next to `ceoca_ca` /
   `hotcopper_au` / `lse_share_chat` / `xueqiu` (lines 107-122), following
   the exact shape:

   ```yaml
   - name: seeking_alpha
     label: Seeking Alpha (US)
     source_type: community
     enabled: true          # registered stub: Seeking Alpha discussion/comment pages are behind Cloudflare bot protection and/or login wall for automated clients (spike TBD); collect() returns []; login/Cloudflare bypass out of scope
   ```

4. **`src/investment_monitor/config.py`** — add to `DEFAULT_SOURCE_META`:
   `"seeking_alpha": ("Seeking Alpha (US)", "community")` (mirrors the
   ceoca_ca / hotcopper_au / lse_share_chat / xueqiu entries).
5. **`src/investment_monitor/dedupe.py`** — four edits (mirror AU/CA/UK/CN-HK):
   - `dedupe_key` allowed-markets set (line 266-270): add `"us"` so US
     community items can receive a dedupe key.
   - `COMMUNITY_SOURCE_PRIORITY`: add `"seeking_alpha": 0` (lines 188-193).
   - `SOURCE_DISPLAY_LABELS`: add `"seeking_alpha": "Seeking Alpha (US)"`
     (lines 252-255).
   - `_community_key` (lines 763-832): add a `market == "us"` branch that
     prefers the stable native post id, else the source-scoped title
     fallback with the New York day (see section 6).
6. **`src/investment_monitor/web_repository.py`** — add `normalize_us_ticker`
   (see section 3). Optionally wire a `market == MARKET_US` normalization
   branch in `add_companies_batch` to mirror the AU/HK/CA pattern.

## 6. Dedupe key rules for US community

Mirror the existing `_community_key` branches in `dedupe.py:763-832`:

- For `market == "us"`: prefer the stable native Seeking Alpha post id from
  `raw_metadata` (e.g. `comment_id` or `article_id`), key
  `us:community:seeking_alpha:<native-id>`. Fallback: source-scoped title key
  `us:community:title:seeking_alpha:<ticker>:<new-york-day>:<normalized-title>`.

With only one community source wired for the US there is no cross-source
"Also seen on" pairing — same-source duplicate rows can still annotate.

**Critical:** `dedupe_key` currently returns `None` for any item whose
`market` is not in the explicit allow-set (line 266-270). `"us"` is **not**
in that set, so without the edit in section 5.5 the US community branch in
`_community_key` is dead code — items would never be keyed. Both edits
(allow-set + branch) must land together.

## 7. Test plan outline

Mirror `tests/test_hotcopper_au.py` (the STUB test pattern) and
`tests/test_ceoca_ca.py` (the LIVE parser pattern — reuse for the fixture
parser even though collect is a stub):

1. **`test_normalize_us_ticker`** — `AAPL` → `AAPL`; `aapl` → `AAPL`;
   `BRK-B` → `BRK-B`; `  msft  ` → `MSFT`; non-conforming input preserved.
2. **`test_parser_filters_new_york_day`** — synthetic fixture with two posts
   on the target New York day, one on another day; assert only the two target
   day rows are returned.
3. **`test_parser_empty_for_other_day`** — same fixture, wrong day; assert
   `[]`.
4. **`test_map_rows_builds_community_items`** — parse fixture, map with
   `map_rows_for_tests`, assert `source == "seeking_alpha"`, `source_type ==
   "community"`, `document_type == "community_post"`, `market == "us"`,
   `tickers` is the normalized root, `external_id` starts with
   `seeking-alpha-`.
5. **`test_collect_is_empty_stub`** — `collect()` returns `[]`, `status ==
   "stub"`, `last_errors` is non-empty and mentions Cloudflare / login.
6. **`test_registry_registers_seeking_alpha`** —
   `create_default_registry()` has a factory for `"seeking_alpha"` and the
   built connector's `.name == "seeking_alpha"`.
7. **`test_community_soft_dedupe_uses_native_id`** — two items sharing a
   native post id produce the same `dedupe_key`; annotated output has
   `also_seen_on == ["seeking_alpha"]` and `also_seen_on_labels ==
   ["Seeking Alpha (US)"]`.
8. **`test_market_routing`** — US tickers route to `MARKET_US`; non-US
   tickers (e.g. `BHP.AX`) are skipped by the market filter in
   `collect()`.

Fixture: `tests/fixtures/seeking_alpha/synthetic_board_2026-08-11.html` — a
hand-crafted static fixture mirroring the documented Seeking Alpha post shape
with `comment_id`/`article_id`, `title`, `text`/`summary`, `created_at` (ISO
timestamp), and per-post deep link. No live network dependency.
