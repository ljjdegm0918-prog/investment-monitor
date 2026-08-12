# ALIGN: X (Twitter) US community connector — alignment brief

Status: **IMPLEMENTED — Stub·STOP** (2026-08-11). No live collection
possible without a user-provided paid official X API key. The `x_community`
connector in `src/investment_monitor/sources/x_community/` is a registered
**stub**. This commit wires registry / settings / README / UI only; it does
**not** enable a Bearer key path.

---

## SPIKE_CONFIRMED — Stub·STOP

From `tests/fixtures/x_community/SPIKE.md` (e3d61d6):

| Surface | Result |
|---|---|
| Official X API v2 `search/recent` (no key) | 401 — Bearer/OAuth2 required; pay-per-usage |
| `x.com` search / Communities / profile HTML | SPA shell behind login wall for urllib |
| Nitter mirrors | dead or bot-walled |
| oEmbed / undocumented syndication `tweet-result` | need known tweet id; cannot enumerate by ticker |

**Verdict:** Stub·STOP for no-key public collection. The only compliance-aligned
LIVE unlock is **user-provided official X API v2 key** — **not wired** in this
stub. No-key HTML / undocumented syndication scrape remain out of scope
(same honesty bar as `yellowbrick`, `hotcopper_au`, `xueqiu`).

---

## Connector shape

| Member | Value |
|---|---|
| `name` | `x_community` |
| `provider` | `X` |
| `status` | `stub` |
| `collect()` | no network; per-US-ticker honest `last_errors`; returns `[]` |
| market | `us` only; other markets skipped |

Category if ever LIVE: **social post stream** (not forum threads, not
article/news RSS).

---

## Registration checklist (this change)

- [x] `registry.py` — `XCommunityConnector`
- [x] `config.py` — `DEFAULT_SOURCE_META`
- [x] `config/settings.yaml` — community entry `enabled: true` + Stub·STOP comment
- [x] `dedupe.py` — priority + display label (harmless while stub)
- [x] `web_repository.py` — source/provider labels
- [x] `README.md` / `README_EN.md`
- [x] `web_static/app.js` — US market hint
- [x] `tests/test_x_community.py` — `test_registry_registers_x_community`

---

## Unlock note (future, out of this commit)

Optional LIVE via `X_BEARER_TOKEN` + `GET /2/tweets/search/recent` (cashtag,
7-day window) would require a separate work order, Settings whitelist, and
honest docs that the feed is paywalled API — not a free public scrape.
