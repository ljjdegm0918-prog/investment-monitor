# ALIGN: Xueqiu (雪球) CN/HK community connector — alignment brief

Status: **STUB ALIGNMENT PACK** (Worker B). No code applied yet.
`xueqiu` is NOT implemented; this is the brief an implementer follows on the
next pass. The two reference connectors are `hotcopper_au` (registered STUB)
and `ceoca_ca` (LIVE), both already on `main`.

Source files read for this brief (all paths relative to repo root):

- `src/investment_monitor/sources/ceoca_ca/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/hotcopper_au/{connector,parser,__init__}.py`
- `src/investment_monitor/sources/lse_share_chat/{connector,parser,__init__}.py`
- `src/investment_monitor/{models,registry,config,dedupe,web_repository}.py`
- `tests/test_ceoca_ca.py`, `tests/test_hotcopper_au.py`,
  `tests/test_lse_share_chat.py`
- `tests/fixtures/ceoca/{SPIKE.md,shop_spiels_sample.json}`,
  `tests/fixtures/hotcopper/{SPIKE.md,bhp_board_2026-02-17.html}`,
  `tests/fixtures/lse_share_chat/{SPIKE.md,ALIGN.md,bp_board_2026-02-17.html}`,
  `tests/fixtures/xueqiu/{SPIKE.md,probe.py}`
- `config/settings.yaml` (community entries)

---

## 1. InformationItem fields for a community source (target: CN + HK)

`InformationItem` (dataclass, `src/investment_monitor/models.py:79-106`) is the
single shared shape. Both reference connectors fill it identically; the Xueqiu
connector must fill it the same way with `market=MARKET_CN` (`"cn"`,
`models.py:13`) for Shanghai/Shenzhen boards and `market=MARKET_HK` (`"hk"`,
`models.py:14`) for Hong Kong boards.

Canonical field values (from `ceoca_ca/connector.py:110-152` `map_rows` —
treat as the live-path template; `hotcopper_au` matches with `stub` notes):

| Field | Value | Notes |
|---|---|---|
| `source` | `self.name` (`"xueqiu"` for the new connector) | registry/config name |
| `source_type` | `"community"` | constant |
| `document_type` | `"community_post"` | constant (both refs) |
| `external_id` | `f"xueqiu-{row.<native-id>}"` style | prefix `<provider>-<native-id>`; see section 6 key rules |
| `tickers` | `(code,)` — normalized CN root (see section 3) | tuple, 1 element |
| `issuer` | `code` (normalized root) | both refs use root code |
| `published_at` | row timestamp `.astimezone(timezone.utc)` | **aware UTC** |
| `title` | post title (capped, e.g. 500 chars) | hotcopper caps `row.title[:500]` |
| `url` | stable public URL | per-source template (see section 2) |
| `collected_at` | `datetime.now(timezone.utc)` | once per `collect()` |
| `raw_metadata` | `{"provider": "xueqiu", "<native-key>": <native-id>, "stock_code": code, ...}` | both refs include provider + native id + stock_code; stub adds `"stub": True` |
| `market` | `MARKET_CN` or `MARKET_HK` | **required**; `InformationItem.__post_init__` validates against `ALLOWED_MARKETS` |
| `summary` | optional, `(body)[:500]` or `None` | ceoca caps at `MAX_SUMMARY_LEN = 500` |
| `effective_at` | same UTC value as `published_at` | both refs set it |

Constants to copy per-connector (module scope): `LOGGER =
logging.getLogger(__name__)`, `SHANGHAI = ZoneInfo("Asia/Shanghai")` for CN
boards and `HKT = ZoneInfo("Asia/Hong_Kong")` for HK boards (see section 4),
and a `BOARD_URL_TEMPLATE` for `url`.

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

For `xueqiu`:
- The spike result is **STUB** (SPIKE.md conclusion: "Stub·STOP for live
  scrape"). Mirror `hotcopper_au` exactly — `status = "stub"`, `collect()`
  returns `[]`, `last_errors` carries the honest reason including the
  documented URL and the WAF / login-wall observation from the spike.
- The honest reason string must mention: Aliyun WAF JS challenge on all HTML
  pages, JSON APIs require `xq_a_token` (error `400016`), and that
  captcha/login/WAF bypass is out of scope (same honesty bar as
  `hotcopper_au` and `lse_share_chat`).

Do NOT invent a third shape: `status` in {"stub", "live"} and the
`last_errors` tuple contract are what tests and the settings / Data Sources UI
already assume.

## 3. CN + HK symbol map — REUSE where possible, invent the CN normalizer

Facts from the repo:

1. **There is NO `normalize_cn_ticker` in `web_repository.py`** (grep for
   `normalize_cn` / `_CN_TICKER` finds nothing; the existing normalizers are
   au/be/ca/ch/de/es/fr/hk/it/nl/pl/se/sg/tw only).
2. **`normalize_hk_ticker` EXISTS** at `web_repository.py:2054-2069`. It
   accepts `700`, `0700`, `00700`, `0700.HK` and returns the canonical
   five-digit form `00700`. Non-numeric input is preserved unchanged. **Reuse
   this for HK tickers** — do not reinvent it.
3. CN tickers appear in several forms in the wild:
   - Pure numeric root: `600519` (茅台), `000001` (平安银行), `300750` (宁德时代)
   - Exchange-prefixed: `SH600519`, `SZ000001`, `SZ300750`
   - Yahoo-style suffix: `600519.SS` (Shanghai), `000001.SZ` (Shenzhen),
     `300750.SZ`
   - The exchange prefix/suffix encodes the listing venue: `SH` = 上交所
   (Shanghai), `SZ` = 深交所 (Shenzhen). This is the same information that
   `infer_ca_board` recovers for Canadian tickers.

**Recommended: add `normalize_cn_ticker` to `web_repository.py`** right after
`normalize_hk_ticker` (ends line 2069, before `normalize_tw_ticker`):

```python
_CN_TICKER_SUFFIXES = ("SS", "SZ")
_CN_TICKER_PREFIXES = ("SH", "SZ", "BJ")  # 北交所


def normalize_cn_ticker(ticker: str) -> str:
    """Normalize a Chinese A-share symbol to its canonical numeric root form.

    Accepts pure numeric roots (``600519``), exchange-prefixed forms
    (``SH600519``, ``SZ000001``), and Yahoo-style suffixes
    (``600519.SS``, ``000001.SZ``). The exchange marker is stripped and the
    numeric root is zero-padded to 6 digits. Non-numeric input is preserved
    unchanged rather than silently dropped.
    """
    cleaned = str(ticker).strip().upper()
    for prefix in _CN_TICKER_PREFIXES:
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix):
            candidate = cleaned[len(prefix):]
            if candidate.isdigit():
                return candidate.zfill(6)
    for suffix in _CN_TICKER_SUFFIXES:
        marker = "." + suffix
        if cleaned.endswith(marker):
            candidate = cleaned[: -len(marker)]
            if candidate.isdigit():
                return candidate.zfill(6)
    if cleaned.isdigit():
        return cleaned.zfill(6)
    return cleaned
```

That is the exact core with docstring. It lives next to the other market
normalizers and is imported by the Xueqiu connector the same way the CA
connector imports `normalize_ca_ticker`.

**Market routing rule:** the connector must assign `market` based on the
ticker form:
- HK tickers (pass through `normalize_hk_ticker`, 5-digit result) →
  `MARKET_HK`
- CN tickers (pass through `normalize_cn_ticker`, 6-digit result) →
  `MARKET_CN`
- The `CollectionRequest.markets` mapping is authoritative when present;
  fall back to the ticker-form heuristic above when absent.

## 4. Asia/Shanghai vs Asia/Hong_Kong day filter

Pattern to mirror (identical in both markets, different zone):

- Sydney: `sydney_day(moment)` in `hotcopper_au/connector.py:108-112`
  (naive -> assume UTC, then `.astimezone(SYDNEY).date()`); parser filters
  `published.astimezone(SYDNEY).date() != on_date`
  (`hotcopper_au/parser.py:80`).
- Toronto: `toronto_day(moment)` in `ceoca_ca/parser.py:74-78`; parser filter
  `published_at.astimezone(TORONTO).date() != on_date`
  (`ceoca_ca/parser.py:54`); plus `toronto_day_from_ms` for epoch-ms payloads.

For Xueqiu use **two** zones — already repo-standard in `dedupe.py`:

- `ZoneInfo("Asia/Shanghai")` — CN board day filter. Note: `dedupe.py` does
  not currently define a Shanghai zone constant (CN news/filing keys are not
  yet wired), so define it at module scope in the connector.
- `ZoneInfo("Asia/Hong_Kong")` — HK board day filter. `dedupe.py:109 HKT`
  already exists for HK news/filing keys.

Add, in the Xueqiu connector module (and parser if separate):

```python
SHANGHAI = ZoneInfo("Asia/Shanghai")
HKT = ZoneInfo("Asia/Hong_Kong")


def shanghai_day(moment: datetime) -> date:
    """Calendar day in Asia/Shanghai for CN board day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(SHANGHAI).date()


def hk_day(moment: datetime) -> date:
    """Calendar day in Asia/Hong_Kong for HK board day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(HKT).date()
```

and in the parser row loop: skip rows where the local-day filter for the
assigned market does not equal `on_date`. This keeps CN/HK community items on
the same local-day clock as the rest of their respective feeds.

## 5. Registry + settings.yaml skeleton (NOT applied yet)

This section is the checklist an implementer follows; nothing in it is
committed yet. The `xueqiu` entry is **not** registered and not in
`settings.yaml` as of this brief — apply only when the orchestrator approves.

Wiring points (every one required, in the same pattern as AU/CA/UK):

1. **`src/investment_monitor/sources/xueqiu/__init__.py`** exports the
   connector (+ parser helpers), with a module docstring stating the STUB
   verdict like `hotcopper_au/__init__.py`.
2. **`src/investment_monitor/registry.py`** — import the connector and add
   `registry.register(XueqiuConnector.name, XueqiuConnector)` next to
   `CeocaCaConnector` / `HotCopperAuConnector` / `LseShareChatConnector`
   (lines 232-234).
3. **`config/settings.yaml`** — add a community block next to `ceoca_ca` /
   `hotcopper_au` / `lse_share_chat` (lines 107-118), following the exact
   shape:

   ```yaml
   - name: xueqiu
     label: Xueqiu (CN/HK)
     source_type: community
     enabled: true          # registered stub: xueqiu.com HTML is Aliyun WAF JS-challenge shell; JSON APIs require xq_a_token (400016) (spike 2026-08-11); collect() returns []; login/WAF bypass out of scope
   ```

4. **`src/investment_monitor/config.py`** — add to `DEFAULT_SOURCE_META`:
   `"xueqiu": ("Xueqiu (CN/HK)", "community")` (mirrors the ceoca_ca /
   hotcopper_au / lse_share_chat entries).
5. **`src/investment_monitor/dedupe.py`** — three edits (mirror AU/CA/UK):
   - `COMMUNITY_SOURCE_PRIORITY`: add `"xueqiu": 0` (lines 187-191);
   - `SOURCE_DISPLAY_LABELS`: add `"xueqiu": "Xueqiu (CN/HK)"` (lines 249-252);
   - `_community_key` (lines 759-804): add `market == "cn"` and `market == "hk"`
     branches that prefer the stable native post id, else the source-scoped
     title fallback with the Shanghai / Hong Kong day (see section 6).
6. **`src/investment_monitor/web_repository.py`** — add `normalize_cn_ticker`
   (see section 3) and import it in `add_companies_batch` for the
   `market == MARKET_CN` branch (mirrors the HK/AU/CA normalization calls at
   lines 578-585).

## 6. Dedupe key rules for CN/HK community

Mirror the existing `_community_key` branches in `dedupe.py:759-804`:

- For `market == "cn"`: prefer the stable native Xueqiu post id from
  `raw_metadata` (e.g. `post_id` or `status_id`), key
  `cn:community:xueqiu:<native-id>`. Fallback: source-scoped title key
  `cn:community:title:xueqiu:<ticker>:<shanghai-day>:<normalized-title>`.
- For `market == "hk"`: prefer the stable native Xueqiu post id, key
  `hk:community:xueqiu:<native-id>`. Fallback: source-scoped title key
  `hk:community:title:xueqiu:<ticker>:<hk-day>:<normalized-title>`.

With only one community source wired per market there is no cross-source
"Also seen on" pairing — same-source duplicate rows can still annotate.

## 7. Test plan outline

Mirror `tests/test_hotcopper_au.py` (the STUB test pattern) and
`tests/test_ceoca_ca.py` (the LIVE parser pattern — reuse for the fixture
parser even though collect is a stub):

1. **`test_normalize_cn_ticker`** — pure root `600519` → `600519`;
   `SH600519` → `600519`; `600519.SS` → `600519`; `000001.SZ` → `000001`;
   `SZ300750` → `300750`; non-numeric preserved.
2. **`test_normalize_hk_ticker`** — `0700` → `00700`; `00700.HK` → `00700`
   (covers the `normalize_hk_ticker` reuse path for the HK board).
3. **`test_parser_filters_shanghai_day`** — synthetic fixture with two posts
   on the target Shanghai day, one on another day; assert only the two target
   day rows are returned.
4. **`test_parser_filters_hk_day`** — same fixture shape with HKT timestamps;
   assert only the two target HK-day rows are returned.
5. **`test_map_rows_builds_community_items`** — parse fixture, map with
   `map_rows_for_tests`, assert `source == "xueqiu"`, `source_type ==
   "community"`, `document_type == "community_post"`, `market` is `cn` or `hk`
   per ticker, `tickers` is the normalized root, `external_id` starts with
   `xueqiu-`.
6. **`test_collect_is_empty_stub`** — `collect()` returns `[]`, `status ==
   "stub"`, `last_errors` is non-empty and mentions WAF / `400016`.
7. **`test_registry_registers_xueqiu`** — `create_default_registry()` has a
   factory for `"xueqiu"` and the built connector's `.name == "xueqiu"`.
8. **`test_community_soft_dedupe_uses_native_id`** — two items sharing a
   native post id produce the same `dedupe_key`; annotated output has
   `also_seen_on == ["xueqiu"]` and `also_seen_on_labels == ["Xueqiu (CN/HK)"]`.
9. **`test_market_routing`** — `HK00700` → `MARKET_HK`; `SH600519` /
   `600519.SS` → `MARKET_CN`.

Fixture: `tests/fixtures/xueqiu/synthetic_board_2026-08-11.json` (or `.html`)
— a hand-crafted static fixture mirroring the documented Xueqiu post shape
with `status_id`, `title`, `text`/`summary`, `created_at` (ISO timestamp),
and per-post deep link. No live network dependency.
