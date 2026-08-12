# Spike: HotCopper AU public board (2026-08-11)

## Question
Can we stably collect public HotCopper posts for an ASX ticker filtered to a
Sydney calendar day without login?

## Evidence
| Probe | Result |
|---|---|
| `GET https://hotcopper.com.au/asx/bhp/` (urllib + browser UA) | HTTP 403 Forbidden |
| `GET https://www.hotcopper.com.au/asx/bhp/` | HTTP 403 |
| `GET https://hotcopper.com.au/` | HTTP 403 |
| Playwright `page.goto(https://hotcopper.com.au/asx/bhp/)` | HTTP 403, Cloudflare challenge title「请稍候…」 |

## Conclusion
Honest stub / STOP for live scrape. Public ticker boards are behind bot
protection. Login/paywalled posts are out of scope. Do not hard-crawl.

Unlock only if HotCopper publishes a stable public RSS/JSON with per-post
timestamps, or explicitly authorises a bot-friendly board export.
