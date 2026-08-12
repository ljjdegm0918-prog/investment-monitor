# Spike: Yellowbrick Investing site surface probes (2026-08-11)

## Question

Can we stably collect public Yellowbrick Investing content (ticker pages,
ideas/pitches, community posts) without login, captcha/WAF bypass, or paid API?

## Method

`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only,
no cookie. No Selenium/Playwright, no captcha/login/WAF bypass. Reproduce with
`python tests/fixtures/yellowbrick/probe_site.py`.

## Evidence

| URL | HTTP | login/paywall? | id / time / title / link? | 摘要 |
|---|---|---|---|---|
| `https://ybrick.co/` | 0 (transport) | N | No | DNS unreachable / transport error, 117-byte body, no title |
| `https://ybrick.co/stocks` | 0 (transport) | N | No | same as above |
| `https://ybrick.co/ideas` | 0 (transport) | N | No | same as above |
| `https://www.joinyellowbrick.com/` | 200 | marketing only | No | Title `Yellowbrick Investing`, 278 KB landing page, `Set-Cookie=0` |
| `https://www.joinyellowbrick.com/stocks` | 404 | — | No | 404 page (title `Yellowbrick Investing`) |
| `https://www.joinyellowbrick.com/ideas` | 404 | — | No | 404 page (title `Yellowbrick Investing`) |
| `https://www.joinyellowbrick.com/pitches` | 404 | — | No | 404 page (title `Yellowbrick Investing`) |
| `https://yellowbrickinvesting.substack.com/` | 200 | waitlist | No | Title `Yellowbrick Investing Waitlist | Substack`, `Set-Cookie=3` — waitlist capture only, no public posts |
| `https://yellowbrick.com/` | 200 | no | No | Wrong entity — `Yellowbrick SQL Data Platform \| Secure. Efficient. Anywhere` (data warehouse vendor blog) |
| `https://www.yellowbrick.com/` | 200 | no | No | same as above |
| `https://yellowbrickresearch.com/` | 200 | no | No | `About. \| YellowBrick.` — consulting site, not the investing product |
| `https://www.yellowbrickresearch.com/` | 200 | no | No | same as above |

Note on the `login?` column: the probe's keyword heuristic flags
"join yellowbrick" marketing copy inside the landing page, but
`joinyellowbrick.com` sets **no cookies** and serves **no member area** — the
page is public marketing text only. The Substack is a waitlist signup page.

## Assessment

- **joinyellowbrick.com** — marketing landing page only. `/stocks`, `/ideas`,
  `/pitches` are all 404. No public ticker/pitch/idea content.
- **ybrick.co** — domain dead (DNS/transport failure, HTTP 0 on every path).
- **yellowbrickinvesting.substack.com** — waitlist capture only; no published
  posts reachable without signing up (and signup is a waitlist, not content).
- **yellowbrick.com / yellowbrickresearch.com** — different entities (SQL data
  platform vendor, consulting firm), not the Yellowbrick Investing product.

## Conclusion

**No public Yellowbrick Investing content surface.** No ticker pages, no
ideas/pitches feed, no RSS/JSON — marketing landing page and waitlist only.
**Stub·STOP** for live collection.

Unlock only if joinyellowbrick.com publishes a stable public feed (RSS/JSON)
with per-post timestamps and deep links, or ybrick.co comes back with a public,
login-free ticker surface.
