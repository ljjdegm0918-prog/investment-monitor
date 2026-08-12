# Spike: Seeking Alpha comments / discussion (2026-08-11)

## Question
Can we stably collect public Seeking Alpha comments and discussion for a US
ticker (AAPL) filtered to a New York calendar day without login?

## Evidence

| Probe | HTTP | login? | post id/time/title/link? |
|---|---|---|---|
| `GET https://seekingalpha.com/symbol/AAPL/comments` (urllib + browser UA) | 403 | N (Cloudflare block before login wall) | none (Set-Cookie=2; len=4887) |
| `GET https://seekingalpha.com/symbol/AAPL/forum` | 403 | N | none (Set-Cookie=2; len=3280) |
| `GET https://seekingalpha.com/article/4934079-…` | 403 | N | none (Set-Cookie=2; len=4999) |
| `GET https://seekingalpha.com/article/4934079/comments` | 403 | N | none (Set-Cookie=2; len=4871) |
| `GET https://seekingalpha.com/api/sa/comments/4934079` | 403 | N | none |
| `GET https://seekingalpha.com/api/sa/threads/AAPL` | 403 | N | none |
| `GET https://seekingalpha.com/api/v1/comments?article_id=…` | 404 | — | — |
| `GET https://seekingalpha.com/api/v2/comments?symbol=AAPL` | 404 | — | — |
| `GET https://seekingalpha.com/symbol/AAPL/rss` | 403 | N | none |
| `GET https://seekingalpha.com/symbol/AAPL/feed` | 200 | N | news items only (no comments); RSS `<item>` has title/link/pubDate/guid — **news articles, not user comments** |
| `GET https://seekingalpha.com/api/sa/combined/AAPL.xml` | 200 | N | same RSS news feed — no comment data |
| `GET https://seekingalpha.com/api/sa/combined/AAPL` | 200 | N | same RSS news feed — no comment data |

## Conclusion

**Honest stub / STOP for live comment scrape.** Seeking Alpha comments and
discussion threads are inaccessible to bare urllib (stdlib, no cookies, browser
UA):

1. **Cloudflare bot protection** — every HTML page and most API endpoints
   return HTTP 403 before any login wall is even evaluated. The response body
   is a Cloudflare challenge page, not actual content.
2. **No public comment API** — all tested `/api/sa/comments/*` and
   `/api/sa/threads/*` paths return 403. The only accessible endpoints are the
   RSS news feeds (`/feed`, `/api/sa/combined/*.xml`) which contain **article
   metadata only** (title, link, pubDate, guid) — zero user comment data.
3. **Login wall is moot** — the 403 blocks happen before any login/signup
   prompt is served, so even logged-in sessions would need full browser
   rendering (Playwright/Selenium) to pass Cloudflare.

Do NOT hard-crawl Seeking Alpha for comments. The site requires either:
- A paid Seeking Alpha premium API subscription (if one exists),
- Authenticated browser sessions via Playwright/Selenium (out of scope for
  this spike — comments-only, no Selenium), or
- An official public RSS/JSON feed that includes comment threads (none found).

## What IS accessible (out of scope for this spike)

The RSS feeds at `/feed` and `/api/sa/combined/{SYMBOL}.xml` are accessible
without auth and return news article metadata. These could feed a **news
connector** but NOT a comments/discussion connector.

## Recommendation

**STOP.** Comments/discussion collection from Seeking Alpha is not feasible
with urllib-only, no-auth, no-browser-rendering constraints. Mark as
unsupported source for the comments pipeline.
