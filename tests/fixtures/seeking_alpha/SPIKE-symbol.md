# Spike: Seeking Alpha symbol pages (AAPL) (2026-08-11)

## Question
Can we stably collect public seekingalpha.com content for the AAPL symbol page
— forum discussion / comments / per-symbol article stream — filtered to a
calendar day, without login, captcha/WAF bypass, or paid API?

## Method
`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only.
No Selenium/Playwright, no captcha/login/WAF bypass attempted. Reproduce with
`python tests/fixtures/seeking_alpha/probe_symbol.py` (no cookie).

## Evidence
| Probe | HTTP | login? | id/time/title/link? |
|---|---|---|---|
| `GET https://seekingalpha.com/symbol/AAPL` | 403 | N | No — PerimeterX `px-captcha` challenge page (`_pxAppId=PXxgCxM9By`), no post content |
| `GET https://seekingalpha.com/symbol/AAPL/forum` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/comments` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/news` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/analysis` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/transcripts` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/earnings` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/dividends` | 403 | N | No — same px-captcha page |
| `GET https://seekingalpha.com/symbol/AAPL/news?source=feed_symbol_AAPL` | 403 | N | No — same px-captcha page (the deep link emitted inside the RSS feed is also blocked for bots) |
| `GET https://seekingalpha.com/api/sa/combined/AAPL.xml` | 200 | N | **Yes** — RSS 2.0, 30 items; each item has `<guid>` id (`MarketCurrent:4630410` / `Article:4932193`), `<pubDate>` minute-precision `-0400`, `<title>`, deep `<link>` with article id, `<sa:author_name>` |
| `GET https://seekingalpha.com/api/sa/combined/AAPL` | 200 | N | Yes — same RSS body as the `.xml` URL |
| `GET https://seekingalpha.com/api/sa/combined/aapl.xml` | 200 | N | Yes — lowercase symbol also works (case-insensitive) |
| Control: second `GET .../AAPL.xml` | 200 | N | Yes — stable: same item guid list, same 30844-byte body |

All HTML symbol pages (root + every tab) answer with a PerimeterX
`px-captcha` challenge (`<meta name="description" content="px-captcha">`,
`window._pxAppId='PXxgCxM9By'`) even to a browser UA with no cookie — an
interactive human-verification wall, not a login form. login? column is N
because no login/paywall wording is served; the blocker is the captcha WAF.

## Public RSS feed findings (`/api/sa/combined/{SYMBOL}.xml`)
- **Status:** 200, no login, no captcha challenge, no cookie required.
- **Shape:** RSS 2.0 `channel` with per-symbol `<title>` "Apple Inc. - News
  and Analysis on Seeking Alpha" and 30 `<item>` entries (fixed cap of 30).
- **Composition (AAPL sample):** 19 `MarketCurrent` news flashes + 11
  `Article` analysis pieces; each item carries author, symbol tags.
- **Timestamps:** `<pubDate>` RFC 2822 with minute precision, fixed US
  Eastern offset (`-0400`), e.g. `Tue, 11 Aug 2026 00:48:04 -0400`. Sample
  span ~8 days (2026-08-03 → 2026-08-11). Day filtering must convert the
  offset to the target calendar day (US Eastern, not UTC).
- **IDs and deep links:** `<guid>` embeds the stable content id
  (`MarketCurrent:NNNNNN` / `Article:NNNNNN`); `<link>` for articles is a real
  deep link `https://seekingalpha.com/article/4932193-...?source=feed_symbol_AAPL`,
  but that article page itself returns 403 px-captcha to bots, so the feed is
  metadata-only for scraping purposes.
- **Scope:** this is a news + analysis *article stream*, NOT forum comments /
  discussion posts. No comment/discussion ids or per-comment timestamps are
  exposed anywhere in the probe set.

## Day filter / symbol board
- **Per-symbol HTML board (forum/comments/tabs) without JS/captcha solving:**
  not obtainable — every HTML request is answered by a PerimeterX px-captcha
  challenge, which is a WAF bypass and out of scope.
- **Public JSON/HTML with per-comment id/time/title/link:** not present in
  any unauthenticated response.
- **Public metadata feed with per-post id/time/title/link:** available via
  `/api/sa/combined/{SYMBOL}.xml` (news + analysis article stream only,
  30-item rolling window, no pagination observed).

## Conclusion
**Stub·STOP** for symbol *page* scraping; **partial unlock** for the symbol
article feed only.

seekingalpha.com symbol pages (root and all tabs) are walled by PerimeterX
`px-captcha` (403) for automated clients — forum discussions and comments are
not reachable without solving the captcha, which is out of scope (same honesty
bar as `xueqiu`, `lse_share_chat`, `hotcopper_au`).

The separate public RSS feed `https://seekingalpha.com/api/sa/combined/AAPL.xml`
does return 200 with id/time/title/link for a 30-item rolling window of
`MarketCurrent` news + `Article` analysis, no login. It is a viable metadata
source for an "article stream" collector (per-symbol, minute-precision US
Eastern timestamps, stable ids), but it does NOT cover forum/comment content,
has a 30-item cap, and its deep links still 403 for bots.

Unlock forum/comment scraping only if Seeking Alpha publishes a stable public
day-filterable feed (RSS/JSON) with per-comment timestamps and deep links,
without login or captcha challenge.
