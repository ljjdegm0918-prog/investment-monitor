# Spike: LSE Share Chat UK public community (2026-08-11)

## Question
Can we stably collect public LSE.co.uk Share Chat (or londonstockexchange.com
public discussion) posts for an LSE/AIM ticker filtered to a Europe/London
calendar day without login, captcha bypass, or paid API?

## Evidence
| Probe | HTTP | Notes |
|---|---|---|
| `GET https://www.lse.co.uk/sharechat/` | 403 | Forbidden to automated client (browser UA) |
| `GET https://www.lse.co.uk/ShareChat.html` | 403 | Same |
| `GET https://www.lse.co.uk/share-chat/` | 403 | Same |
| `GET https://www.lse.co.uk/ShareChat/BP/` | 403 | Ticker board path blocked |
| `GET https://www.lse.co.uk/sharechat/bp/` | 403 | Same |
| `GET https://www.lse.co.uk/ShareChat/BP.L/` | 403 | Same |
| `GET https://www.lse.co.uk/` | 403 | Site root also blocked to bot UA |
| `GET https://www.lse.co.uk/sharechat/BP/rss` | 403 | No public RSS surface |
| `GET https://www.lse.co.uk/rss/sharechat/BP` | 403 | Same |
| `GET https://www.londonstockexchange.com/stock/BP./bp-p-l-c/discussion` | 200 | SPA shell only (`app-root`); **no** discussion/post body server-rendered; title generic LSE |
| `GET https://www.londonstockexchange.com/stock/BP./BP/discussions` | 200 | Same ~55KB shell; no per-post date/URL/title in HTML |
| `GET https://www.londonstockexchange.com/news-and-insights/share-chat` | 200 | Same SPA shell; not a scrapeable thread list |
| `GET https://community.londonstockexchange.com/` | timeout / closed | No usable public community host |
| `GET https://api.londonstockexchange.com/api/v1/components/refresh` | 405 | No free documented discussion JSON for bots |

## Day filter / ticker board
- **Per-ticker public board on lse.co.uk:** not reachable (403).
- **Stable post date / URL / title without JS login wall:** not available in HTML.
- **Europe/London calendar-day filter on a free feed:** not available.

## Conclusion
**Stub·STOP** for live scrape.

`lse.co.uk` Share Chat is blocked to automated clients (403). Official
`londonstockexchange.com` discussion URLs return an empty SPA shell with no
stable public HTML/JSON/RSS of per-ticker posts. Login walls, Cloudflare/
WAF bypass, and paid APIs are out of scope (same honesty bar as `hotcopper_au`).

Unlock only if LSE publishes a stable public day-filterable feed (RSS/JSON)
with per-post timestamps and deep links, without login.
