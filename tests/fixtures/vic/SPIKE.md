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

---

## Re-probe: New unlock angles (2026-08-12)

A second deep probe (`probe_deep.py` / manual fetch, stdlib urllib, no cookie,
no login) tested every NEW surface not covered by the 2026-08-11 spike.

### JSON Accept-header probes (all failed)

| Path | HTTP | JSON? | Notes |
|---|---|---|---|
| `GET /ideas` (Accept: application/json) | 200 | No | HTML shell |
| `GET /api/v2/ideas` | 200 | No | HTML shell |
| `GET /ideas.json` | 200 | No | HTML shell |
| `GET /graphql` | 200 | No | HTML shell |
| All other `/api/*` paths | 200 | No | HTML shell |

### Sitemap variants (all failed)

All of `/sitemap_index.xml`, `/sitemap-0.xml`, `/sitemap-ideas.xml`,
`/sitemap-posts.xml`, `/news-sitemap.xml` return the same ~3 778-byte HTML
shell — no XML sitemap content whatsoever.

### `/ideas` listing — actual HTML structure

The 20 idea links on `/ideas` are a **TRENDING** marquee bar only:

```html
<b>TRENDING:</b>
<a href="/idea/Kaspi.kz/8547833282" title="Kaspi.kz">KSPI</a>
<a href="/idea/VERSABANK/6098729790" title="VERSABANK">VBNK</a>
…
```

Key JS variables embedded in the page confirm guest (not logged in) status
and the guest cut-off date:

```javascript
var is_login       = 0;
var dimensionValue = 'free';
var end_date       = '05/13/2026';   // guest-visible cut-off (≈91 days ago)
```

**No date fields accompany the trending links.** Pagination (`?page=1/2/3`)
returns the identical 20 links (same MD5 hash) — the server ignores the
`page` parameter for guests.

### `/ideas/atoz` listing — actual HTML structure

Each entry is a `<span class="vich1">` block:

```html
<span class="vich1">
  <a href="/idea/VERSABANK/6098729790">VERSABANK</a> (Jul 20)
</span>
```

* Anchor text = **company name** (not ticker symbol).
* Date = **(Mon YY)** — month + 2-digit year; **no calendar-day resolution**.
* 2 523 ideas; covers many years (2016–2024+).
* No ticker field anywhere in the listing HTML.

**Local ticker filtering is not possible** from this listing: without a
ticker field there is no compliant ticker → idea mapping short of fetching
every one of the 2 523 individual idea pages.

### Individual `/idea/…` page — fields available to guests

`GET /idea/Kaspi.kz/8547833282` (HTTP 200, 160 KB):

```
title:            "Value Investors Club / Kaspi.kz (KSPI)"
date:             September 13, 2024 - 4:10pm EST
meta description: "Investment thesis for Kaspi.kz, KSPI"
show_txts:        0   (thesis text hidden for guests)
```

Individual pages **do** expose ticker, full timestamp, and a structured
financial header (Price / EPS / Shares) — but they require a **known idea
URL**. There is no key-free API to discover "which ideas exist for ticker X
on date Y": the TRENDING list (20 items, no dates) and the A-Z catalog
(company names + month-year, no tickers) cannot serve as a discovery index
for a ticker+calendar-day query.

### Pagination / delayed-path variants (all redirected to same shell)

`/ideas/delayed`, `/ideas/guest`, `/ideas/public`, `/ideas?view=delayed`,
`/ideas?delayed=1`, `/api/public/ideas`, `/api/ideas/delayed` → all return
the same 32 857-byte or 3 778-byte HTML shell with no additional idea links.

### Re-probe conclusion: Stub·STOP confirmed

| New angle | Verdict |
|---|---|
| JSON Accept-header on any path | HTML shell — No |
| Alternative sitemap variants | HTML shell — No |
| `/ideas` listing has ticker text | Yes (TRENDING bar, anchor=ticker), **but no dates** — insufficient for ticker+day query |
| `/ideas/atoz` has ticker text | No — anchor=company name; date=(Mon YY) only |
| Pagination of guest list | Broken for guests (same 20 regardless of `?page=`) |
| Individual idea pages have ticker+date | Yes, **but no discovery API** to map ticker+day → idea URL |
| Delayed-path URL variants | All redirect to same HTML shell |

No new viable unlock angle found. The guest-visible surface still lacks a
stable ticker + calendar-day discovery index without membership credentials
or a vendor export.

**Final verdict: Stub·STOP unchanged.**
