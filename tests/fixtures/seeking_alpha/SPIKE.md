# Spike: Seeking Alpha US community/article surface (2026-08-11)

## Question
Can we stably collect public Seeking Alpha content for a US ticker filtered to
an America/New_York calendar day without login, captcha/WAF bypass, or paid API?

## Method
`stdlib urllib` only, browser-like Chrome UA. Probes from Workers A/B/C
(`SPIKE-symbol.md`, `probe_*.py`, `probe_out.txt`). No Selenium/Playwright.
No captcha/login/WAF bypass.

## Evidence (merged)
| Probe | HTTP | login/paywall? | id / time / title / link? |
|---|---|---|---|
| `GET https://seekingalpha.com/symbol/AAPL` (+ forum/comments/news/analysis/…) | 403 | PerimeterX `px-captcha` | No — challenge page only |
| `GET https://seekingalpha.com/symbol/AAPL/rss` | 403 | px-captcha | No |
| `GET https://seekingalpha.com/api/sa/combined/AAPL.xml` | **200** | No | **Yes** — RSS items: `<guid>` (`MarketCurrent:N` / `Article:N`), `<pubDate>` ET, `<title>`, `<link>` |
| `GET https://seekingalpha.com/api/sa/combined/AAPL` | **200** | No | Same RSS body as `.xml` |
| `GET https://seekingalpha.com/api/sa/combined/aapl.xml` | **200** | No | Case-insensitive symbol |

## Category honesty
- **Forum / comments / discussion HTML:** not reachable (403 px-captcha). Out of scope to bypass.
- **Public combined RSS:** news flashes (`MarketCurrent`) + analysis (`Article`) — **article/news stream**, not forum posts. Product allows this if SPIKE/README mark the category honestly.
- Feed window ≈ **30 items**, no pagination observed; deep article HTML pages still 403 to bots (metadata+link only).

## Day filter
`<pubDate>` is RFC 2822 with Eastern offset (e.g. `-0400`). Filter with
`America/New_York` calendar day.

## Conclusion
**LIVE** — use public RSS `https://seekingalpha.com/api/sa/combined/{SYMBOL}.xml`
for per-ticker **news + analysis article** metadata (id/time/title/link),
stdlib urllib, no cookie.

**Not LIVE** for forum/comments. Do not scrape HTML symbol tabs.

Unlock forum only if SA ships a stable public comment feed without captcha.
