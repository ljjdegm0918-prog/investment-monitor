# Spike: Yellowbrick Investing public surface (2026-08-11)

## Question

Can we stably collect public **Yellowbrick Investing** content (community
ideas/pitches/ticker pages) for a ticker filtered to a calendar day, without
login, captcha/WAF bypass, or paid API?

## Product / entity honesty

Product under test = **Yellowbrick Investing** (social/pitch aggregation:
`joinyellowbrick.com`, `ybrick.co`, `yellowbrickinvesting.substack.com`).

**NOT** `yellowbrick.com` — that is a SQL data platform vendor (data warehouse
software) with a corporate blog. Treating its blog as the Yellowbrick Investing
community would be a category error; its LIVE blog RSS/JSON (see
`SPIKE-rss-json.md`) belongs to a different entity and must not be wired into
the investing community connector.

## Method

`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only,
no cookie. No Selenium/Playwright, no captcha/login/WAF bypass.

- Site surface: `probe_site.py` → `SPIKE-site.md`
- RSS/JSON feeds: `probe_rss.py` → `SPIKE-rss-json.md`

## Evidence (merged)

| Probe | HTTP | login/paywall? | id / time / title / link? | Notes |
|---|---|---|---|---|
| `GET https://ybrick.co/` (+ `/stocks`, `/ideas`) | 0 (transport) | N | No | DNS unreachable / transport error — domain dead |
| `GET https://www.joinyellowbrick.com/` | 200 | marketing only | No | `Yellowbrick Investing` landing page, no cookies, no member area |
| `GET https://www.joinyellowbrick.com/stocks` | 404 | — | No | 404 — no ticker page surface |
| `GET https://www.joinyellowbrick.com/ideas` | 404 | — | No | 404 — no ideas surface |
| `GET https://www.joinyellowbrick.com/pitches` | 404 | — | No | 404 — no pitches surface |
| `GET https://yellowbrickinvesting.substack.com/` | 200 | waitlist | No | `Yellowbrick Investing Waitlist | Substack` — waitlist capture only |
| `GET https://yellowbrick.com/feed` | 200 | no | Yes | RSS 2.0, ~100 items — **wrong entity** (SQL data platform blog) |
| `GET https://yellowbrick.com/wp-json/wp/v2/posts` | 200 | no | Yes | WP REST API — **wrong entity** |
| `GET https://yellowbrick.com/` | 200 | no | — | `Yellowbrick SQL Data Platform` — different company |

## Category honesty

- **joinyellowbrick.com**: marketing landing page only. `/stocks`, `/ideas`,
  `/pitches` all 404. No public community/idea/pitch content, no RSS/JSON.
- **ybrick.co**: dead domain (HTTP 0 on every path).
- **yellowbrickinvesting.substack.com**: waitlist capture page, no public posts.
- **yellowbrick.com**: live RSS + WP REST API, but it is the SQL data platform
  vendor's corporate blog — NOT Yellowbrick Investing content. Out of scope for
  this connector; must be marked honestly as a different entity if ever reused.

## Market timezone

**Not applicable** — there is no public ticker content to filter. Every content
path is 404 or waitlist-gated, so no per-post timestamps exist and no
`America/New_York` calendar-day filter can be built.

## Conclusion

**Stub·STOP** for live collection.

Yellowbrick Investing has no stable public, login-free surface: the product
domain (`ybrick.co`) is dead, `joinyellowbrick.com` is a marketing landing page
with all content paths 404, and the Substack is a waitlist. There is no ticker,
ideas/pitches feed, RSS, or JSON to collect — same honesty bar as
`hotcopper_au`, `lse_share_chat`, and `xueqiu`.

A LIVE connector against `yellowbrick.com` (SQL data platform blog) is **out of
scope** for the Yellowbrick Investing community seat: wrong entity.

Unlock only if joinyellowbrick.com publishes a stable public feed (RSS/JSON)
with per-post timestamps and deep links, or ybrick.co comes back with a public,
login-free ticker surface.
