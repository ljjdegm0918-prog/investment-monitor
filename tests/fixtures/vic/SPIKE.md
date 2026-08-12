# Spike: Value Investors Club (VIC) public surface (2026-08-11)

## Question

Can we stably collect public **Value Investors Club**
(`valueinvestorsclub.com`) investment ideas filtered to a ticker and calendar
day, without membership login, captcha/WAF bypass, or a paid/private API?

## Product / entity honesty

Product under test = **Value Investors Club (VIC)** — a US equity long/short
**investment-idea club** (members submit and discuss pitch write-ups). It is
**not** a retail forum thread board and **not** an article/news RSS product.
Category if ever LIVE: community investment-idea write-ups (club pitches).

## Method

`stdlib urllib` only, browser-like UA, GET only, no cookie, no login.
No Selenium/Playwright, no membership signup automation. Probed 2026-08-11
via `probe_public.py`.

## Evidence

### No public RSS / JSON API

| Probe | HTTP | Content | usable feed? |
|---|---|---|---|
| `GET /feed` | 200 | ~3.8 KB HTML shell | **No** — not RSS (`<item>` / `<entry>` absent) |
| `GET /rss` | 200 | ~3.8 KB HTML shell | **No** |
| `GET /api/ideas` | 200 | ~3.8 KB HTML shell | **No** |
| `GET /api/v1/ideas` | 200 | ~3.8 KB HTML shell | **No** |
| `GET /sitemap.xml` | 200 | ~3.8 KB HTML shell | **No** |
| `GET /robots.txt` | 200 | plain text | n/a |

### Ideas listing — no ticker filter

| Probe | HTTP | idea `/idea/...` hrefs | notes |
|---|---|---|---|
| `GET /ideas` | 200 | 20 | same first-5 set as below |
| `GET /ideas?symbol=MSFT` | 200 | 20 | **identical** href set / hash to `/ideas` |
| `GET /ideas?symbol=AAPL` | 200 | 20 | **identical** href set / hash to `/ideas` |
| `GET /ideas?q=MSFT` | 200 | 20 | same shell; query ignored for filtering |
| `GET /ideas/MSFT` | 200 | 20 | same |
| `GET /search?q=MSFT` | 200 | 0 | no idea links |
| `GET /symbol/MSFT` | 200 | 0 | ~3.8 KB shell |

Conclusion: guessed symbol query params **do not** produce a ticker-scoped
idea list.

### Membership / guest delay

Homepage (`GET /`, HTTP 200) copy (verbatim sense): visitors need a valid
email address **to get access to 45 days delayed ideas**. Signup CTA on
`/ideas`: “To gain access to more recent ideas … signup free for membership”.
Login page (`/login`) exposes password fields.

### Historical idea HTML (not a discovery path)

| Probe | HTTP | ticker / date? | discovery? |
|---|---|---|---|
| `GET /idea/MICROSOFT_CORP/8319612353` | 200 | title has `MSFT`; body dates e.g. `August 07, 2018` | **No** — requires a known idea URL; not ticker+day listing |
| `GET /ideas/atoz` | 200 | ~2522 unique `/idea/...` links; labels like `(Dec 23)` without full year/ticker in href | HTML catalog scrape of a membership club — **out of scope**; still not a day-filtered API |

## Category honesty

- VIC = exclusive **investment-idea club** pitches, not forum threads and not
  news RSS.
- No structured public “ticker → ideas for calendar day” surface without
  membership (and even guest access is **45-day delayed**).
- Do not treat readable historical idea HTML as LIVE collection: no stable
  key-free discovery, ToS/membership wall for recent content.

## Market timezone

**America/New_York (US-facing)** if a future membership/export path exposes
stable timestamps. Not applicable while stub.

## Conclusion

**Stub·STOP** for key-free collection.

1. No public RSS/JSON API (`/feed`, `/rss`, `/api/ideas`, sitemap → HTML
   shells).
2. `/ideas?symbol=TICKER` does **not** filter by ticker (identical lists).
3. Guest path is membership signup with **45-day delayed** ideas; recent ideas
   need membership.
4. Known idea URLs and `/ideas/atoz` HTML are not a compliant ticker+day
   collector — membership/login and HTML catalog scrape stay out of scope
   (same honesty bar as `x_community`, `yellowbrick`, `xueqiu`).

Unlock only if the product accepts **membership credentials** or a
vendor-provided structured export with stable id / time / ticker fields —
not wired in this stub.
