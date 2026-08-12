# Spike: Xueqiu (雪球) CN public discussion stream (2026-08-11)

## Question
Can we stably collect public xueqiu.com discussion posts for CN/HK symbols
(SH600519, SZ000001, HK00700) filtered to a calendar day, without login,
captcha/WAF bypass, or paid API?

## Method
`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only.
No Selenium/Playwright, no captcha/login/WAF bypass attempted. Reproduce with
`python tests/fixtures/xueqiu/probe.py` (no cookie) or
`python tests/fixtures/xueqiu/probe.py --cookie "<xq_a_token=...>"` (optional
对照，未验证有效).

## Evidence
| Probe | HTTP | cookie required? | post id / time / title / link available? |
|---|---|---|---|
| `GET https://xueqiu.com/` | 200 | n/a | No — 110KB page is Aliyun WAF JS-challenge only (`aliyunwaf_6a6f5ea8` script + `renderData` ciphertext), no `<title>`, no post content |
| `GET https://xueqiu.com/S/SH600519` | 200 | n/a | No — same WAF challenge page, zero `statuses/post/comment` tokens in body |
| `GET https://xueqiu.com/S/SZ000001` | 200 | n/a | No — same WAF challenge page |
| `GET https://xueqiu.com/S/HK00700` | 200 | n/a | No — same WAF challenge page |
| `GET https://xueqiu.com/statuses/search.json?symbol=SH600519&count=10` | 400 | Yes (`xq_a_token`) | No — JSON error `error_code=400016` "遇到错误，请刷新页面或者重新登录帐号后再试" |
| `GET https://xueqiu.com/query/v1/symbol/search/status.json?symbol=SH600519&count=10` | 200 | n/a | No — request lands on WAF challenge page, no JSON delivered |
| `GET https://xueqiu.com/query/v1/symbol/search/status.json?symbol=SZ000001&count=10` | 200 | n/a | No — WAF challenge page |
| `GET https://xueqiu.com/query/v1/symbol/search/status.json?symbol=HK00700&count=10` | 200 | n/a | No — WAF challenge page |
| `GET https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=10` | 200 | n/a | No — WAF challenge page |
| `GET https://xueqiu.com/statuses/original/timeline.json?count=10` | 200 | n/a | No — WAF challenge page |
| `GET https://stock.xueqiu.com/v5/stock/quote.json?symbol=SH600519` | 400 | Yes (`xq_a_token`) | No — JSON error `error_code=400016` |
| `GET https://xueqiu.com/rss` | connection closed | n/a | No — server drops connection, no RSS surface |
| `GET https://m.xueqiu.com/S/SH600519` | SSL EOF | n/a | No — mobile host not reachable |
| `GET https://xueqiu.com/feed` | 200 | n/a | No — WAF challenge page |
| Control: `search.json` + fabricated `xq_a_token=FAKE...` cookie | 400 | Yes | No — still `400016`; fabricated token rejected |
| Control: `/S/SH600519` + fabricated cookie | 200 | n/a | No — still WAF challenge page |

## Day filter / ticker board
- **Public per-ticker board HTML without JS execution:** not obtainable — every
  HTML request is answered by an Aliyun WAF JS challenge page (`_waf_*`
  renderData); real content requires executing the challenge script, which is
  a WAF bypass and out of scope.
- **Public JSON API without login token:** not obtainable — `search.json`,
  `query/v1/symbol/search/status.json`, `statuses/hot/listV2.json`,
  `statuses/original/timeline.json` all either return `400016` (token
  required) or are intercepted by the WAF challenge.
- **Post id / timestamp / title / deep link in static HTML:** not present in
  any unauthenticated response.
- **Asia/Shanghai calendar-day filter on a free feed:** not available.

## Cookie path (documented, NOT verified)
A `XUEQIU_COOKIE` (`xq_a_token=...` from a logged-in session) may unlock the
JSON APIs, but: (a) it was not tested with a real token, (b) a fabricated
token was rejected with `400016`, and (c) the HTML surface still serves a WAF
challenge even with a cookie header, so a browser-grade session cookie alone
may not be sufficient. Not a stable no-login surface.

## Conclusion
**Stub·STOP** for live scrape.

xueqiu.com has no stable public HTML/JSON/RSS surface reachable without
executing Aliyun WAF JS challenges and supplying a valid login session token.
HTML pages are WAF challenge shells; JSON APIs demand `xq_a_token`
(`400016`). Captcha/login/WAF bypass and paid APIs are out of scope (same
honesty bar as `hotcopper_au` and `lse_share_chat`).

Unlock only if Xueqiu publishes a stable public day-filterable feed (RSS/JSON)
with per-post timestamps and deep links, without login or WAF challenge.
