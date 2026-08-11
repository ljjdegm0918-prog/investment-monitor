# Spike: LSE Share Chat UK public community (2026-08-12)

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
| `GET https://www.londonstockexchange.com/robots.txt` | 200 | Official host publishes a sitemap reference; this does not expose post data |
| `GET https://www.londonstockexchange.com/sitemap.xml` | 404 | No usable sitemap document at the advertised path |
| `GET https://api.londonstockexchange.com/api/gw/lse/search/autocomplete?q=BP` | 200 | Public JSON contains instrument search metadata only; no posts, dates, or discussion links |
| `GET https://api.londonstockexchange.com/api/v1/pages` | 400 | Official SPA handshake requires page/request context; no anonymous feed payload |
| `GET https://api.londonstockexchange.com/api/gw/lse/search?q=BP` | 400 | Gateway search requires additional SPA request parameters; no usable anonymous result contract |
| `GET https://api.londonstockexchange.com/api/gw/lse/search?query=BP` | 400 | Same; query-only request is not a public feed |
| `GET https://api.londonstockexchange.com/api/gw/lse/instruments/alldata?code=BP` | 404 | No result for the guessed public instrument endpoint |
| `GET https://api.londonstockexchange.com/api/gw/lse/issuers?code=BP` | 404 | No result for the guessed public issuer endpoint |
| `GET https://www.londonstockexchange.com/stock/BP./bp-p-l-c/rns` | 200 | ~55KB SPA shell only; no server-rendered RNS rows, dates, ids, or deep links |
| `GET https://www.londonstockexchange.com/stock/BP./bp-p-l-c/news` | 200 | Same SPA shell; no public structured news/post list |
| `GET https://www.investegate.co.uk/company/bp/` | 200 | Public static RNS-class announcement table with dates/ids/deep links; announcements only, not community posts; existing `investegate` connector covers this source |
| `GET https://www.advfn.com/forum` | 403 | Alternative community host blocks automated client; no compliant public feed established |

## Day filter / ticker board
- **Per-ticker public board on lse.co.uk:** not reachable (403).
- **Stable post date / URL / title without JS login wall:** not available in HTML.
- **Europe/London calendar-day filter on a free feed:** not available.
- **Official LSE gateway:** autocomplete is metadata-only; other discovered routes require SPA context or return 404.
- **Compliant alternative:** Investegate exposes public RNS announcements, but it is an existing regulatory source and is not a Share Chat/community feed; no new connector name is justified by this probe.

## Conclusion
**Stub·STOP** for live scrape.

`lse.co.uk` Share Chat is blocked to automated clients (403). Official
`londonstockexchange.com` discussion/news/RNS URLs return an empty SPA shell;
the newly discovered gateway routes do not provide an anonymous post feed.
Investegate is a usable public RNS mirror already represented by the separate
`investegate` connector, but it cannot be relabeled as LSE Share Chat.
Login walls, Cloudflare/WAF bypass, and paid APIs are out of scope (same
honesty bar as `hotcopper_au`).

Unlock only if LSE publishes a stable public day-filterable feed (RSS/JSON)
with per-post timestamps and deep links, without login; or if a distinct,
compliant UK community provider publishes such a feed and receives its own
connector name. Official RNS/announcement data should continue through
`investegate` (or a separately named official-announcements connector), never
through `lse_share_chat`.
