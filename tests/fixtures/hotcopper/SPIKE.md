# Spike: HotCopper AU public board (2026-08-11 + re-probe 2026-08-12)

## Question
Can we stably collect public HotCopper posts for an ASX ticker filtered to a
Sydney calendar day without login?

## Evidence — Round 1 (2026-08-11)
| Probe | Result |
|---|---|
| `GET https://hotcopper.com.au/asx/bhp/` (urllib + browser UA) | HTTP 403 Forbidden |
| `GET https://www.hotcopper.com.au/asx/bhp/` | HTTP 403 |
| `GET https://hotcopper.com.au/` | HTTP 403 |
| Playwright `page.goto(https://hotcopper.com.au/asx/bhp/)` | HTTP 403, Cloudflare challenge title「请稍候…」 |

## Re-probe — Round 2 (2026-08-12)
| Probe | Result |
|---|---|
| `HEAD https://hotcopper.com.au/feed` | HTTP 403 |
| `HEAD https://hotcopper.com.au/rss` | HTTP 403 |
| `HEAD https://hotcopper.com.au/asx/bhp/feed` | HTTP 403 |
| `HEAD https://hotcopper.com.au/asx/bhp/rss` | HTTP 403 |
| `HEAD https://hotcopper.com.au/threads/rss` | HTTP 403 |
| `HEAD https://hotcopper.com.au/sitemap.xml` | HTTP 403 |
| `HEAD https://hotcopper.com.au/api` | HTTP 403 |
| `HEAD https://hotcopper.com.au/robots.txt` | HTTP 403 |

**Result:** All HotCopper endpoints return HTTP 403 (Cloudflare WAF), including
`robots.txt` and the site home. No public RSS, JSON, or official API found.
No developer/API documentation discovered. Status: **UNCHANGED — remain stub**.

## Alternative Source Angle (2026-08-12)
Explored compliant AU community/analysis alternatives with a NEW connector name:

| Probe | Result |
|---|---|
| `HEAD https://stockhead.com.au/feed/` | **HTTP 200** `application/rss+xml` |
| `GET https://stockhead.com.au/?s=BHP&feed=rss2` | **HTTP 200** RSS 2.0, 50 items |
| Categories per item | `CompanyName - TICKER` format, e.g. `BHP - BHP` |
| External ID | URL path slug (stable); GUIDs are empty |
| `GET https://stockhead.com.au/?s=ANZ&feed=rss2` | **HTTP 200**, ANZ items present |
| `HEAD https://www.reddit.com/r/ASX_Bets/.json` | HTTP 403 |
| `HEAD https://www.marketindex.com.au/feed` | HTTP 403 |
| `HEAD https://www.fool.com.au/tag/bhp/feed/` | HTTP 200, but oldest-first stale articles |
| `HEAD https://ausbiz.com.au/feed` | HTTP 404 |
| `HEAD https://www.proactiveinvestors.com.au/companies/news/rss/` | HTTP 500 |

**Decision:** `stockhead_au` LIVE connector implemented using WordPress search RSS
(`/?s={TICKER}&feed=rss2`). Filter: category tag `CompanyName - TICKER` must
contain the target ASX code; date filter on Sydney calendar day.
`hotcopper_au` remains honest stub.

## Conclusion
`hotcopper_au`: Honest stub / STOP. WAF blocks all endpoints including RSS.
Unlock requires HotCopper publishing a stable public RSS/JSON with per-post
timestamps or explicit bot-friendly authorisation.

`stockhead_au`: **NEW connector — LIVE** (2026-08-12). WordPress search RSS
is publicly accessible; ticker category tags allow reliable per-ticker
filtering. See `src/investment_monitor/sources/stockhead_au/`.

## Unlock Recipe (hotcopper_au — still needed)
1. HotCopper publishes `https://hotcopper.com.au/asx/{ticker}/rss` accessible
   without Cloudflare challenge.
2. OR HotCopper provides an official API with bearer-token auth
   (env var `HOTCOPPER_API_KEY`).
3. Do NOT bypass WAF / Cloudflare. Do NOT scrape login-walled content.
