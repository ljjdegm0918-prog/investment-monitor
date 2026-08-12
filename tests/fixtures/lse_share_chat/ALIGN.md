# ALIGN: LSE Share Chat (UK) community connector — alignment brief

Status: **READ-MOSTLY ALIGNMENT PACK** (Worker B). No code applied yet.
`lse_share_chat` is NOT implemented; this is the brief an implementer follows
on the next pass. The two reference connectors are `hotcopper_au` (registered
STUB) and `ceoca_ca` (LIVE), both on branch `feat/community-lse-uk`.

Source files read for this brief (all paths relative to repo root):

- `src/investment_monitor/sources/hotcopper_au/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/ceoca_ca/{connector,parser,__init__}.py`
- `src/investment_monitor/connectors/{base,mock_community}.py`
- `src/investment_monitor/sources/uk_news/yahoo/connector.py` (`_yahoo_symbol`)
- `src/investment_monitor/{models,registry,config,dedupe,web_repository}.py`
- `src/investment_monitor/uk_universe.py`
- `tests/test_hotcopper_au.py`, `tests/test_ceoca_ca.py`,
  `tests/test_uk_dedupe.py`, `tests/test_yahoo_uk_connector.py`
- `tests/fixtures/hotcopper/{SPIKE.md,bhp_board_2026-02-17.html}`,
  `tests/fixtures/ceoca/{SPIKE.md,shop_spiels_sample.json}`
- `config/settings.yaml` (community entries)

---

## 1. InformationItem fields for a community source (target: UK)

`InformationItem` (dataclass, `src/investment_monitor/models.py:79-106`) is the
single shared shape. Both reference connectors fill it identically; the LSE
connector must fill it the same way with `market=MARKET_UK` (`"uk"`,
`models.py:16`).

Canonical field values (from `ceoca_ca/connector.py:110-152` `map_rows` —
treat as the live-path template; `hotcopper_au` matches with `stub` notes):

| Field | Value | Notes |
|---|---|---|
| `source` | `self.name` (`"lse_share_chat"` for the new connector) | registry/config name |
| `source_type` | `"community"` | constant |
| `document_type` | `"community_post"` | constant (both refs) |
| `external_id` | `f"lse-{row.<native-id>}"` style | prefix `<provider>-<native-id>`; see section 6 key rules |
| `tickers` | `(code,)` — UK **root** ticker (strip `.L`/trailing dot, see section 3) | tuple, 1 element |
| `issuer` | `code` (root ticker) | both refs use root code |
| `published_at` | row timestamp `.astimezone(timezone.utc)` | **aware UTC** |
| `title` | thread/post title (capped, e.g. 500 chars) | hotcopper: `row.title[:500]` |
| `url` | stable public URL | per-source template (see section 2) |
| `collected_at` | `datetime.now(timezone.utc)` | once per `collect()` |
| `raw_metadata` | `{"provider": ..., "<native-key>": <native-id>, "stock_code": code, ...}` | both refs include provider + native id + stock_code; hotcopper adds `"stub": True` |
| `market` | `MARKET_UK` | **required**; `InformationItem.__post_init__` validates against `ALLOWED_MARKETS` |
| `summary` | optional, `(body)[:500]` or `None` | ceoca caps at `MAX_SUMMARY_LEN = 500` |
| `effective_at` | same UTC value as `published_at` | both refs set it |

Constants to copy per-connector (module scope): `LOGGER =
logging.getLogger(__name__)`, `LONDON = ZoneInfo("Europe/London")` (see
section 4), and a `CHANNEL_URL_TEMPLATE` / `BOARD_URL_TEMPLATE` for `url`.

`mock_community.py` is the minimal proof-of-extensibility shape (no `status`,
no `last_errors`); it is NOT the production template. The production template
is the AU/CA pair in section 2.

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

For `lse_share_chat`:
- If the spike result is **LIVE**: mirror `ceoca_ca` exactly — `status =
  "live"`, `collect()` loop with `market != MARKET_UK: continue`, fetch per
  ticker, map, `(ticker, message)` failures, and single-ticker raise of a
  connector-specific error class (subclass `RuntimeError`, e.g.
  `LseShareChatRequestError`).
- If the spike result is **blocked** (Cloudflare/login wall, like HotCopper):
  mirror `hotcopper_au` exactly — `status = "stub"`, `collect()` returns
  `[]`, `last_errors` carries the honest reason including the documented URL
  and the HTTP code observed in the spike.

Do NOT invent a third shape: `status` in {"stub", "live"} and the
`last_errors` tuple contract are what tests and the settings / Data Sources UI
already assume.

## 3. UK ticker normalize rule — REUSE, do not invent

Facts from the repo:

1. **There is NO `normalize_uk_ticker` in `web_repository.py`** (grep for
   `normalize_uk` / `_UK_TICKER` / `removesuffix(".L")` finds nothing; the
   existing normalizers are au/ca/be/fr/hk/tw only).
2. The only existing `.L` handling is the Yahoo request-time helper
   `_yahoo_symbol` in
   `src/investment_monitor/sources/uk_news/yahoo/connector.py:77-81`:

   ```python
   def _yahoo_symbol(code: str) -> str:
       """Convert a UK ticker to a Yahoo symbol at request time only."""
       if code.endswith(".L"):
           return code
       return code.rstrip(".") + ".L"
   ```

   It is **append-only** (adds `.L` for the Yahoo `s=` param) and is covered
   by `tests/test_yahoo_uk_connector.py:152-170` (`_yahoo_symbol("BP.") ==
   "BP.L"`). It is NOT a root-strip normalizer and must not be reused for the
   canonical `InformationItem.tickers` value.
3. `uk_universe.py` seeds tickers like `"BP."` (trailing-dot form,
   `TICKER_ISIN_SEED`), so the UK connector must tolerate both `BP.` and
   `BP.L` and collapse to root `BP`.

**Recommended helper — reuse the AU/CA skeleton style and location.**
`web_repository.py` already holds every market normalizer (`normalize_au_ticker`
line 1984, `normalize_ca_ticker` line 2115, `normalize_fr_ticker` line 2146,
...). Add the UK one in the same file, right after `normalize_ca_ticker`
(ends line 2138, before `_FR_TICKER_SUFFIXES`):

```python
def normalize_uk_ticker(ticker: str) -> str:
    """Normalize a London Stock Exchange symbol to its canonical root form.

    Accepts plain symbols (``VOD``) and the common LSE suffix forms
    (``VOD.L``, ``BP.``; trailing dots are tolerated too, and stacked
    suffixes like ``VOD.L.L`` collapse to ``VOD``). The suffix is stripped
    and the root symbol is uppercased; a plain symbol without a suffix is
    preserved as-is.
    """
    cleaned = str(ticker).strip().upper()
    while cleaned.endswith(".L") or cleaned.endswith("."):
        cleaned = cleaned[:-2] if cleaned.endswith(".L") else cleaned[:-1]
    return cleaned.strip()
```

That is the exact 5-line core with docstring. It lives next to the other
market normalizers and is imported by the LSE connector the same way the CA
connector imports `normalize_ca_ticker`. If an implementer prefers
`removesuffix`, keep the same semantics: strip `.L` first, then trailing
dots, so `BP.L` -> `BP` and `BP.` -> `BP` while `BP` stays `BP`.

## 4. Europe/London day filter — mirror Toronto/Sydney

Pattern to mirror (identical in both markets, different zone):

- Sydney: `sydney_day(moment)` in `hotcopper_au/connector.py:108-112`
  (naive -> assume UTC, then `.astimezone(SYDNEY).date()`); parser filters
  `published.astimezone(SYDNEY).date() != on_date`
  (`hotcopper_au/parser.py:80`).
- Toronto: `toronto_day(moment)` in `ceoca_ca/parser.py:74-78`; parser filter
  `published_at.astimezone(TORONTO).date() != on_date`
  (`ceoca_ca/parser.py:54`); plus `toronto_day_from_ms` for epoch-ms payloads.

For LSE use `ZoneInfo("Europe/London")` — already the repo-standard UK zone
(`dedupe.py:108 LONDON`, used for uk/aq/cxe/trq news and uk filings). Add, in
the LSE connector module (and parser if separate):

```python
LONDON = ZoneInfo("Europe/London")

def london_day(moment: datetime) -> date:
    """Calendar day in Europe/London for day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LONDON).date()
```

and in the parser row loop: skip rows where
`row.published_at.astimezone(LONDON).date() != on_date`. This keeps UK
community items on the same London-day clock as the rest of the UK feed and
the `_news_key` / `_uk_filing_key` fallbacks in `dedupe.py`.

## 5. Registry + settings.yaml skeleton (NOT applied yet)

This section is the checklist an implementer follows; nothing in it is
committed yet. The `lse_share_chat` entry is **not** registered and not in
`settings.yaml` as of this brief — apply only when the spike verdict says
STUB and the orchestrator approves.

Wiring points (every one required, in the same pattern as AU/CA):

1. **`src/investment_monitor/sources/lse_share_chat/__init__.py`** exports the
   connector (+ parser helpers), with a module docstring stating the LIVE or
   STUB verdict like `ceoca_ca/__init__.py` / `hotcopper_au/__init__.py`.
2. **`src/investment_monitor/registry.py`** — import the connector and add
   `registry.register(LseShareChatConnector.name, LseShareChatConnector)`
   next to `CeocaCaConnector` / `HotCopperAuConnector` (lines 231-232).
3. **`config/settings.yaml`** — add a community block next to `ceoca_ca` /
   `hotcopper_au` (lines 107-114), following the exact shape:

   ```yaml
   - name: lse_share_chat
     label: LSE Share Chat (UK)
     source_type: community
     enabled: true          # verdict pending spike; update comment with STUB reason or LIVE API notes
   ```
4. **`src/investment_monitor/config.py`** — add to `DEFAULT_SOURCE_META`:
   `"lse_share_chat": ("LSE Share Chat (UK)", "community")` (mirrors lines
   34-35).
5. **`src/investment_monitor/dedupe.py`** — three edits (mirror AU/CA):
   - `COMMUNITY_SOURCE_PRIORITY`: add `"lse_share_chat": 0` (lines 187-190);
   - `SOURCE_DISPLAY_LABELS`: add `"lse_share_chat": "LSE Share Chat (UK)"`
     (lines 249-250);
   - `_community_key` (lines 757-790): add a `market == "uk"` branch that
     prefers the stable native post id, else the source-scoped title fallback
     with the London day (see section 6).
6. **`src/investment_monitor/__init__.py`** exports, if the app re-exports
   connectors (follow the AU/CA precedent at the import site).
