# ALIGN: Value Investors Club (VIC) US community connector — alignment brief

Status: **IMPLEMENTED — Stub·STOP** (2026-08-11). No live key-free ticker+day
collection. The `vic` connector in `src/investment_monitor/sources/vic/` is a
registered **stub**. This commit wires registry / settings / README / UI only;
it does **not** enable membership login or HTML catalog scrape.

---

## SPIKE_CONFIRMED — Stub·STOP

From `tests/fixtures/vic/SPIKE.md`:

| Surface | Result |
|---|---|
| `/feed`, `/rss`, `/api/ideas`, `sitemap.xml` | HTML shells — not RSS/JSON |
| `/ideas?symbol=TICKER` | does **not** filter (identical href set vs `/ideas`) |
| Homepage guest access | free signup → **45-day delayed** ideas only |
| Known `/idea/...` HTML / `/ideas/atoz` | readable history / catalog, not ticker+day discovery |

**Verdict:** Stub·STOP for no-key public collection. Membership credentials /
vendor export would be a separate unlock — **not wired**. HTML membership-wall
scrape remains out of scope (same honesty bar as `x_community`, `yellowbrick`,
`xueqiu`).

---

## Connector shape

| Member | Value |
|---|---|
| `name` | `vic` |
| `provider` | `Value Investors Club` |
| `status` | `stub` |
| `collect()` | no network; per-US-ticker honest `last_errors`; returns `[]` |
| market | `us` only; other markets skipped |

Category if ever LIVE: **community investment-idea write-ups** (club pitches),
not forum threads and not article/news RSS.

---

## Registration checklist (this change)

- [x] `registry.py` — `VicConnector`
- [x] `config.py` — `DEFAULT_SOURCE_META`
- [x] `config/settings.yaml` — community entry `enabled: true` + Stub·STOP comment
- [x] `dedupe.py` — priority + display label (harmless while stub)
- [x] `web_repository.py` — source/provider labels
- [x] `README.md` / `README_EN.md`
- [x] `web_static/app.js` — US market hint
- [x] `tests/test_vic.py` — `test_registry_registers_vic`

---

## Unlock note (future, out of this commit)

Optional LIVE only with product-accepted membership credentials or a
structured vendor export exposing stable id / timestamp / ticker — separate
work order, Settings secrets whitelist, and honest docs that recent ideas are
membership-gated (guest = 45-day delay).
