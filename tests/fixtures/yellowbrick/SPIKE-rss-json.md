# Spike: Yellowbrick RSS/JSON Feed Probes (2026-08-11)

## Question

Can we stably collect public Yellowbrick content (blog / news / product updates) via RSS or JSON feeds without login, captcha/WAF bypass, or paid API?

## Method

`stdlib urllib` only, browser-like Chrome UA. All probes done 2026-08-11. No Selenium/Playwright. No captcha/login/WAF bypass.

## Domains Probed

| Domain | Status |
|---|---|
| `yellowbrick.com` | ✅ Live — data platform company (NOT a stock ticker) |
| `yellowbrickresearch.com` | ❌ 404 on /feed, /rss |
| `ybrick.co` | ❌ DNS unreachable / transport error |
| `joinyellowbrick.com` | ❌ 404 on /feed, /rss |
| `yellowbrickinvesting.substack.com` | ✅ Live — Substack newsletter (separate entity) |

## Evidence: RSS Feeds

| URL | HTTP | Content | Notes |
|---|---|---|---|
| `https://yellowbrick.com/feed` | **200** | RSS 2.0 XML | ✅ Blog feed, ~100+ items |
| `https://yellowbrick.com/rss` | **200** | Same RSS 2.0 XML | Alias for /feed |
| `https://yellowbrickresearch.com/feed` | 404 | — | No feed |
| `https://yellowbrickresearch.com/rss` | 404 | — | No feed |
| `https://ybrick.co/feed` | ERR | DNS unreachable | Domain not resolvable |
| `https://joinyellowbrick.com/feed` | 404 | — | No feed |
| `https://joinyellowbrick.com/rss` | 404 | — | No feed |
| `https://yellowbrickinvesting.substack.com/feed` | **200** | RSS 2.0 XML | Substack newsletter, different entity |

## Evidence: JSON / WP REST API

| URL | HTTP | Content | Notes |
|---|---|---|---|
| `https://yellowbrick.com/wp-json/wp/v2/posts` | **200** | JSON array | ✅ WP REST API, full post metadata |
| `https://yellowbrick.com/wp-json/wp/v2/posts?_fields=id,date,title,link,slug,categories` | **200** | JSON (slim) | `_fields` projection works |
| `https://yellowbrick.com/wp-json/wp/v2/posts?categories=7` | **200** | JSON | Category filter works (7 = Yellowbrick Product) |
| `https://yellowbrick.com/wp-json/wp/v2/posts?search=Netezza` | **200** | JSON | Full-text search works |
| `https://yellowbrick.com/wp-json/wp/v2/categories` | **200** | JSON | Category list with counts |
| `https://yellowbrick.com/feed/json` | 404 | — | No JSON feed endpoint |
| `https://yellowbrick.com/wp-json` | **200** | JSON | WP REST discovery root |

## RSS Item Structure (yellowbrick.com/feed)

Per-item fields (stable across items):

| Field | Path | Sample |
|---|---|---|
| **id** | `item/guid` | `https://yellowbrick.com/?p=23235` (WP post ID in URL) |
| **id (permalink)** | `item/guid[@isPermaLink]` | `false` — the GUID is a WP post URL, not the canonical link |
| **title** | `item/title` | `Why AI copilots need a modern, high-concurrency SQL platform...` |
| **link** | `item/link` | `https://yellowbrick.com/blog/yellowbrick-product/why-ai-copilots-...` |
| **pubDate** | `item/pubDate` | `Tue, 28 Jul 2026 15:33:34 +0000` (RFC 2822, UTC) |
| **creator** | `item/dc:creator` | `Rosa Lear` |
| **category** | `item/category` | `Yellowbrick Product` (single value per item) |
| **description** | `item/description` | HTML excerpt (CDATA) |
| **content:encoded** | `item/content:encoded` | Full HTML body (CDATA) |

Channel metadata:
- `<title>Yellowbrick</title>`
- `<language>en-US</language>`
- `<sy:updatePeriod>hourly</sy:updatePeriod>`
- `<sy:updateFrequency>1</sy:updateFrequency>`
- `<lastBuildDate>` present and updates

## JSON Post Structure (WP REST API)

Per-post fields (stable):

| Field | Type | Sample |
|---|---|---|
| `id` | int | `23235` |
| `date` | ISO 8601 | `2026-07-28T08:33:34` (local) |
| `date_gmt` | ISO 8601 | `2026-07-28T15:33:34` (UTC) |
| `modified` | ISO 8601 | `2026-07-28T08:36:15` |
| `slug` | string | `why-ai-copilots-need-a-modern-...` |
| `status` | string | `publish` |
| `type` | string | `post` |
| `link` | URL | `https://yellowbrick.com/blog/yellowbrick-product/...` |
| `title.rendered` | string | HTML-decoded title |
| `categories` | int[] | `[7]` |
| `tags` | int[] | `[]` (mostly empty) |
| `author` | int | `65` |
| `featured_media` | int | `0` |
| `excerpt.rendered` | string | HTML excerpt |

Custom fields also present: `audience`, `topic`, `industry`, `resources-categories` (all empty/default in tested items).

## WP REST API Category Map

| ID | Slug | Name | Post Count |
|---|---|---|---|
| 299 | application-development | Application Development | 7 |
| 140 | blog | blog | 0 |
| 15 | data-industry | Data Industry | 37 |
| 353 | data-platform | Data Platform | 5 |
| 59 | data-practice | Data Practice | 11 |
| 14 | data-security | Data Security | 4 |
| 115 | life-at-yellowbrick | Life@Yellowbrick | 4 |
| 1 | others | Others | 4 |
| 9 | yellowbrick-engineering | Yellowbrick Engineering | 19 |
| 7 | yellowbrick-product | Yellowbrick Product | 87 |

## Filtering / Query Capabilities

| Capability | RSS | WP REST API |
|---|---|---|
| Filter by category | ❌ No | ✅ `?categories=7` |
| Full-text search | ❌ No | ✅ `?search=keyword` |
| Pagination | ❌ No (feed window ~100 items) | ✅ `?per_page=N&page=M` |
| Field projection | ❌ No | ✅ `?_fields=id,date,title,link` |
| Sort order | Publication order only | ✅ `?orderby=date&order=desc` |
| Ticker filtering | ❌ N/A (not a stock ticker) | ❌ N/A (content is about data platform, not stocks) |

## Ticker Filtering Assessment

**Yellowbrick (yellowbrick.com) is a data platform company, NOT a publicly traded stock ticker.** The RSS/JSON feeds contain blog posts about their product — there is no stock ticker concept to filter by.

The `search` parameter on the WP REST API can filter by keyword (e.g., `?search=Netezza`) but this is content-level search, not ticker filtering.

If the investment-monitor project needs to track mentions of specific tickers within Yellowbrick blog posts, the approach would be:
1. Fetch all posts via WP REST API (paginated, ~87 posts in Yellowbrick Product category)
2. Client-side keyword search for ticker symbols in title + content

## Substack Separate Entity

`yellowbrickinvesting.substack.com` is a **different entity** from `yellowbrick.com`. It's a Substack newsletter about investing, not the data platform company. Its RSS feed is a standard Substack feed.

## Conclusion

**LIVE for blog monitoring** — two reliable public endpoints:

1. **RSS**: `https://yellowbrick.com/feed` — standard RSS 2.0, stable guid/title/link/pubDate/category fields
2. **JSON**: `https://yellowbrick.com/wp-json/wp/v2/posts` — WP REST API with filtering, search, pagination, field projection

**Recommended**: Use WP REST API (`/wp-json/wp/v2/posts`) for programmatic access — supports category filtering, search, pagination, and `_fields` projection. RSS is simpler for basic polling.

**Not available**: ticker-based filtering, forum/comments, private content. No paywall on public blog content.

## Probe Script

See `probe_rss.py` for the reproducible probe (stdlib urllib only).
