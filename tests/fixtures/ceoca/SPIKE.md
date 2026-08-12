# Spike: CEO.ca (Canada) public spiel API (2026-08-11)

## Question
Can we stably collect public CEO.ca channel posts for a TSX/TSXV ticker
filtered to a Toronto calendar day without login?

## Evidence
| Probe | Result |
|---|---|
| `GET https://new-api.ceo.ca/api/get_spiels?channel=shop&limit=100` (urllib + browser UA) | HTTP 200 `application/json`; keys `channel`, `spiels[]`, `total_spiels` |
| Each spiel object | `spiel_id`, `spiel` (body), `name`, `timestamp` (ms epoch), `channel` |
| `GET https://ceo.ca/SHOP` (HTML) | SPA shell only; no embedded post list — use JSON API |
| RSS / Atom discovery on `ceo.ca` | No public RSS feed found |
| Pagination `until={oldest_timestamp_ms - 1}` | Returns older spiels (50 per page); usable for day backfill |
| Login / paywall probe | API works without cookies or API key |

## Conclusion
Wire **live** community connector via `new-api.ceo.ca` JSON. Do not scrape the
SPA HTML shell. Channel param is lowercase normalized ticker root (e.g. `shop`
for `SHOP.TO`). Item URL pattern is `https://ceo.ca/{CHANNEL}` (channel page;
no per-spiel deep link in public API). Paginate with `until` until all spiels
on the target Toronto day are collected or timestamps fall before day start.

## Re-verify 2026-08-11

Independent re-probe by Worker 2 (urllib + browser UA, no cookies/auth).

| Probe | Result |
|---|---|
| `GET .../get_spiels?channel=shop&limit=10` | HTTP 200 `application/json; charset=utf-8` |
| `GET .../get_spiels?channel=shop&limit=50&until={ts-1}` | HTTP 200 `application/json; charset=utf-8` |

**Top-level keys (live):** `channel`, `channel_details`, `banned`, `spiels`,
`latest_spiel_id`, `total_spiels`, `online`, `quote`, `stock_info`, `articles`,
`wiki`, `pinned`, `polls` — richer than original spike documented.

**`total_spiels`:** 100 (for `shop` at probe time).

**Page size:** API returns 50 spiels per page regardless of `limit` (requesting
`limit=10` still returned 50). Connector must not assume `limit` is honored.

**Sort order:** oldest to newest within a page (first spiel has the lowest
timestamp, last spiel has the highest).

**Sample spiel fields (live):** `channel`, `spiel`, `spiel_reply_to_id`,
`spiel_reply_to`, `spiel_reply_to_name`, `user_id`, `name`, `timestamp`,
`spiel_id`, `color`, `parent_id`, `public_id`, `parent_channel`,
`parent_timestamp`, `votes`, `editable`, `edited`, `featured`, `verified`,
`fake`, `bot`, `voted`, `flagged`, `own_spiel`, `score`, `saved_id`,
`saved_timestamp`, `poll`, `boost_count`, `booster_count`.

**Pagination behavior:** `until={oldest_timestamp_ms - 1}` returns the next 50
spiels strictly older than `until` (verified: all timestamps in probe 2 were
< `until` boundary). Probe 1 oldest ts = `1786108682675` (2026-08-07 13:18
UTC); probe 2 used `until=1786108682674` and returned spiels from
`1786029485806` (2026-08-06 15:18 UTC) down to `1779233771841` (2026-05-19
23:36 UTC).

**Timestamps:** millisecond epoch (13 digits). Confirmed by converting sample
values to UTC dates consistent with the probe date (2026-08-11).

**Login / paywall:** No cookies, no API key, no auth header required. Clean
HTTP 200 with browser UA.

## Re-verify Conclusion

**LIVE.** Public API is independently confirmed accessible without auth on
2026-08-11. Connector can safely use `new-api.ceo.ca` JSON. Note: `limit`
param is ignored (always 50/page); paginate by `until` using the last spiel's
timestamp - 1. Sort is oldest-first within each page.
