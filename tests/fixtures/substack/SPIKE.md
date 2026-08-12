# Spike: Substack public surface (2026-08-11)

## Question

Can we stably collect public **Substack** content for a ticker filtered to a
calendar day, without login, captcha/WAF bypass, or paid API?

## Product / entity honesty

Product under test = **Substack** (author newsletters, `substack.com` and
per-author custom domains). Substack is a platform of **author newsletters
(article streams)** — it is **NOT a ticker forum** and has no per-ticker
community/pitch surface.

`yellowbrickinvesting.substack.com` (waitlist-only page) is **out of scope**
— a waitlist capture page is not LIVE content; probes target real, active
publications instead.

## Method

`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only,
no cookie. No Selenium/Playwright, no captcha/login/WAF bypass. Probed
2026-08-11.

- Publication surface (home / `/feed` RSS / public JSON): `probe_pub_rss.py`
  → `SPIKE-pub-rss.md` (张三/温知夏)
- Ticker/search surface (global search, tag, topic, archive params):
  `probe_ticker_search.py` → `SPIKE-ticker-search.md` (李四/宋清和)
- Cross-check by SPIKE merge (顾知微): re-probed `noahpinion.blog`,
  `astralcodexten.com`, `paulkrugman.substack.com`, `oneusefulthing.org`,
  `notboring.co` (feed + archive JSON + `search` param).

## Evidence (merged)

### Publication surface — LIVE

| Probe | HTTP | login/paywall? | id / time / title / link? | Notes |
|---|---|---|---|---|
| `GET https://noahpinion.substack.com/` | 200 | no login; subscribe/paid prompts (Substack norm) | No JSON-LD (client-rendered) | Home is SPA; do not scrape HTML |
| `GET https://noahpinion.substack.com/feed` | 200 | no (public RSS) | ✅ guid/pubDate/title/link | RSS 2.0 |
| `GET https://noahpinion.substack.com/api/v1/archive?sort=new&limit=2` | 200 | no (public JSON) | ✅ id=210685540, post_date=2026-08-11T08:01:13Z, title, canonical_url | |
| `GET https://noahpinion.substack.com/api/v1/posts?limit=2` | 200 | no (public JSON) | ✅ same source | |
| `GET https://noahpinion.substack.com/api/v1/publication` | 403 | — | No | not public |
| `GET https://notboring.substack.com/` + `/feed` + archive JSON | 200 | no login | ✅ guid/id/time/title/link | canonical on custom domain `www.notboring.co` |
| `GET https://www.astralcodexten.com/feed` (+ archive JSON) | 200 | no login | ✅ | cross-check |
| `GET https://paulkrugman.substack.com/feed` (+ archive JSON) | 200 | no login | ✅ | cross-check |
| `GET https://www.oneusefulthing.org/feed` (+ archive JSON) | 200 | no login | ✅ | cross-check |
| `GET https://thediff.substack.com/feed` | 200 | no | ⚠️ 1 placeholder post `Coming soon` only | publication **migrated** to self-hosted `thediff.co`; `thediff.co/feed` → SSL verify fail under urllib-only. Whitelist must be maintained. |

RSS item fields: `guid` (= canonical article URL, stable), `title`, `link`,
`pubDate` (RFC 2822 **GMT**). JSON archive fields: `id` (int, stable),
`post_date` (ISO 8601 **UTC**), `title`, `canonical_url`. `/feed` and
`/api/v1/archive?sort=new&limit=N` (paged by offset) return the same items.

### Ticker / search surface — STOP for structured ticker

| Probe | HTTP | can filter by ticker? | Notes |
|---|---|---|---|
| `GET https://substack.com/search?q=NVDA` | 200 | No | SPA shell, client-rendered, no SSR content for urllib |
| `GET https://substack.com/api/v1/search?q=NVDA&limit=5` (also v2, `/api/search`) | 404 | No | **no public search API** |
| `GET https://substack.com/tag/{nvda,aapl,tsla}` | 404 | No | no ticker tag system |
| `GET https://substack.com/discover` / `/browse` / `/topics` | 200 | No | SPA shells; `/discover/{finance,investing,stocks}` 404 |
| `GET https://noahpinion.substack.com/search?q=NVDA` (+ `/tag/*`) | 404 | No | no in-publication ticker search |
| `GET https://noahpinion.substack.com/api/v1/archive?...&start=2026-08-11` | 200 | No | `start` is **cursor paging**, not date filter; same for `year/month` |
| `GET https://noahpinion.substack.com/api/v1/archive?...&search=AAPL` | 200 | ⚠️ keyword-level only | `search` param = **full-text keyword filter** (title+body): `search=AI`→5, `search=AAPL`→0, `search=NVDA`→0 on noahpinion; `search=AAPL`→2 (2021 posts mentioning Apple) on notboring. Not a structured ticker field. |

**Honest answer: cannot filter by US ticker in a structured way.** There is no
ticker taxonomy, no search API, no topic/category filtering. The only
filtering available is **full-text keyword** — server-side via the `search`
param on archive JSON, or client-side matching — inside a
**publication-whitelist** model: pick author newsletters likely to cover the
target ticker, poll their `/feed` or archive JSON, match keywords locally.
Coverage depends on whitelist quality; keyword matches have false
positives/negatives (`Apple` ≠ fruit disambiguation, etc.); no
"ticker → all of Substack for the day" recall guarantee.

## Category honesty

- Substack content is **author newsletter articles** — category is
  **article/news stream**, NOT forum posts (mirror the Seeking Alpha honesty
  bar: `MarketCurrent` news flashes + `Article` analysis).
- Metadata (`id` / time / title / link) is fully public via RSS + JSON; full
  article bodies may be paywalled (`paid subscribers`). If metadata-only, the
  connector must be marked article/news metadata, not forum/discussion.
- **No ticker forum surface**: no public comment-thread API usable as a
  forum; comments render on post pages only.
- Substack supports custom domains (`noahpinion.blog`, `notboring.co`);
  collect via `canonical_url`. Publications may migrate off-platform
  (`thediff` → `thediff.co`); whitelist requires maintenance.

## Market timezone

**America/New_York (US-facing).** `post_date` is UTC ISO 8601
(`2026-08-11T08:01:13.612Z`) and RSS `pubDate` is GMT (RFC 2822) — both
convert to America/New_York (EDT/EST) for the calendar-day filter; the
conversion must happen in the connector (post timestamps are per-author, no
per-publication timezone metadata is publicly exposed).

## Conclusion

**LIVE** — as a **publication-whitelist, article/news metadata** surface
(no ticker forum, no structured ticker filtering):

1. Stable public surface: `/feed` (RSS 2.0) and
   `/api/v1/archive?sort=new&limit=N` (public JSON) work without login on
   real active publications; stable `id` / `post_date` / `title` /
   `canonical_url` on every post. Cross-checked on 5 publications.
2. Per-ticker binding: **cannot filter by US ticker**. Only
   publication-whitelist + keyword filtering (server `search` param or
   client-side match), with the false-positive/negative caveats above.
3. Category: author newsletter **article/news** stream; metadata-only if
   bodies are paywalled; explicitly NOT a forum.
4. Timezone: UTC/GMT post times → convert to America/New_York for the
   calendar-day filter.
5. **No waitlist-only page counts as LIVE** — `yellowbrickinvesting.substack.com`
   is excluded; whitelist must contain active publications and be maintained
   against off-platform migration.

Unlock path for stronger ticker binding: none public today — Substack has no
ticker taxonomy, search API, or tag system. Stay whitelist + keyword.
