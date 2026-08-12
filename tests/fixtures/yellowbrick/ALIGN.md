# ALIGN: Yellowbrick Investing (US) community connector — alignment brief

Status: **IMPLEMENTED — Stub·STOP** (2026-08-11). No live collection
possible. The `yellowbrick` connector in
`src/investment_monitor/sources/yellowbrick/` is a registered **stub** that
correctly targets **Yellowbrick Investing** (`joinyellowbrick.com` /
`ybrick.co`). The earlier out-of-scope `yellowbrick.com` data-platform blog
connector has been replaced by this stub. The correct product target is the
Yellowbrick Investing social stock-pitch / investment-ideas community.

---

## Scope correction — READ FIRST

| Entity | Domain | What it is | In scope? |
|---|---|---|---|
| **Yellowbrick** (data platform) | `yellowbrick.com` | SQL data-platform company blog (RSS feed works, LIVE) | **❌ OUT OF SCOPE** — wrong product |
| **Yellowbrick Investing** | `joinyellowbrick.com`, `ybrick.co` | Social stock-pitch / investment-ideas community | ✅ **Correct target** |

The `src/investment_monitor/sources/yellowbrick/` connector now implements
the Yellowbrick Investing stub; the earlier out-of-scope `yellowbrick.com`
data-platform blog connector has been removed. The `yellowbrick.com/feed`
SPIKE data in `SPIKE-rss-json.md` remains documented as a different entity
and is not wired into the investing community connector.

---

## Source files read (all paths relative to repo root)

- `tests/fixtures/yellowbrick/SPIKE.md`, `SPIKE-site.md`, `SPIKE-rss-json.md`
- `tests/fixtures/yellowbrick/{probe_rss.py,probe_site.py}`
- `src/investment_monitor/sources/yellowbrick/{connector,parser,__init__}.py`
  — **reference only** (wrong entity, out of scope)
- `src/investment_monitor/sources/hotcopper_au/{connector,parser,__init__}.py`
  — **reference for STUB pattern**
- `src/investment_monitor/{models,registry,config,dedupe}.py`
- `tests/test_hotcopper_au.py` — **reference for STUB test pattern**
- `config/settings.yaml` (community entries)

---

## 1. SPIKE evidence (from `tests/fixtures/yellowbrick/SPIKE.md`, d17da3e)

| Probe | HTTP | login/paywall? | id/time/title/link? | Notes |
|---|---|---|---|---|
| `https://ybrick.co/` (+ `/stocks`, `/ideas`) | 0 (transport) | N | No | DNS unreachable — domain dead |
| `https://www.joinyellowbrick.com/` | 200 | marketing only | No | Landing page, no cookies, no member area |
| `https://www.joinyellowbrick.com/stocks` | 404 | — | No | No ticker page surface |
| `https://www.joinyellowbrick.com/ideas` | 404 | — | No | No ideas surface |
| `https://www.joinyellowbrick.com/pitches` | 404 | — | No | No pitches surface |
| `https://yellowbrickinvesting.substack.com/` | 200 | waitlist | No | Waitlist capture only, no public posts |
| `https://yellowbrick.com/feed` | 200 | no | Yes | RSS 2.0 — **wrong entity** (SQL data platform) |
| `https://yellowbrick.com/wp-json/wp/v2/posts` | 200 | no | Yes | WP REST API — **wrong entity** |

**SPIKE verdict: Stub·STOP.** No public Yellowbrick Investing content
surface. The product domain (`ybrick.co`) is dead, `joinyellowbrick.com` is a
marketing landing page with all content paths 404, and the Substack is a
waitlist. No ticker/ideas/pitches feed, RSS, or JSON to collect.

---

## 2. Stub connector shape — mirror `hotcopper_au`

Per SPIKE verdict, the Yellowbrick Investing connector is a registered
**STUB**. Mirror `hotcopper_au` exactly:

| Member | `hotcopper_au` (STUB reference) | `yellowbrick` (implemented) |
|---|---|---|
| class attrs | `name`, `provider`, `status = "stub"` | `name = "yellowbrick"`, `provider = "Yellowbrick Investing"`, `status = "stub"` |
| `collect(request)` | no network; per-ticker appends `(code, "...stub: URL returns HTTP 403...")` note; `self._last_errors = tuple(notes)`; returns `[]` | no network; per-ticker appends `(code, "...stub: ybrick.co DNS unreachable, joinyellowbrick.com all content paths 404, Substack waitlist only...")` note; returns `[]` |
| `last_errors` property | `Tuple[Tuple[str, str], ...]` | same |
| error escalation | none (stub) | none (stub) |
| mapping helper | `map_rows_for_tests` | none needed (no live data) |

**Honest reason string must mention:** `ybrick.co` DNS unreachable (HTTP 0),
`joinyellowbrick.com` marketing landing with `/stocks`, `/ideas`, `/pitches`
all 404, `yellowbrickinvesting.substack.com` waitlist-gated, and that
bypass/login/signup is out of scope (same honesty bar as `hotcopper_au`,
`lse_share_chat`, `xueqiu`).

**Name:** the source is registered as `"yellowbrick"` with provider label
`"Yellowbrick Investing"`.

---

## 3. Registry + settings.yaml wiring

Wiring points (every one required, in the same pattern as `hotcopper_au`):

1. ✅ `src/investment_monitor/sources/yellowbrick/__init__.py` — exports
   `YellowbrickConnector`.
2. ✅ `src/investment_monitor/registry.py` — imports and registers
   `registry.register(YellowbrickConnector.name, YellowbrickConnector)` next
   to `SeekingAlphaConnector`.
3. ✅ `config/settings.yaml` — added community block:

   ```yaml
   - name: yellowbrick
     label: Yellowbrick Investing (US)
     source_type: community
     enabled: true          # registered stub: ybrick.co DNS unreachable; joinyellowbrick.com all content paths 404; Substack waitlist only (spike 2026-08-11); collect() returns []; bypass out of scope
   ```

4. ✅ `src/investment_monitor/config.py` — added to `DEFAULT_SOURCE_META`:
   `"yellowbrick": ("Yellowbrick Investing (US)", "community")`.

No parser, no map_rows, no dedupe community-key branch needed (stub).

---

## 4. Dedupe — NOT applicable for stub

No live items means no dedupe key generation needed. Skip `dedupe.py`
edits. The stub connector produces no `InformationItem` output.

---

## 5. US ticker normalize — NOT needed for stub

Stub `collect()` returns `[]` before any ticker processing. Skip
`normalize_us_ticker` and `America/New_York` day filter — no data flows
through the connector.

---

## 6. Test plan outline — mirror `tests/test_hotcopper_au.py`

1. ✅ `test_connector_attributes` — `name == "yellowbrick"`, `provider ==
   "Yellowbrick Investing"`, `status == "stub"`.
2. ✅ `test_collect_is_empty_stub` — `collect()` returns `[]`, `status ==
   "stub"`, `last_errors` is non-empty and mentions DNS / 404 / waitlist.
3. ✅ `test_collect_records_each_us_ticker` — each requested US ticker gets
   its own honest stub note.
4. ✅ `test_collect_skips_non_us` — non-US tickers are skipped without a
   network attempt or failure record.
5. ✅ `test_collect_mixed_us_and_other` — only US tickers get notes in a
   mixed-market request.
6. ✅ `test_registry_registers_yellowbrick` — `create_default_registry()` has
   a factory for `"yellowbrick"` and the built connector's `.name ==
   "yellowbrick"` and `.status == "stub"`.

No fixture needed (no live data to parse).

---

## Action items

1. ✅ SPIKE.md confirmed Stub·STOP at d17da3e.
2. ✅ Implemented `yellowbrick` stub connector + registry + settings.yaml +
   config (per section 3).
3. ✅ Added tests per section 6 in `tests/test_yellowbrick.py`.
4. ✅ Out-of-scope `yellowbrick.com` data-platform connector removed from
   `src/investment_monitor/sources/yellowbrick/`; the directory now contains
   the Yellowbrick Investing stub.
