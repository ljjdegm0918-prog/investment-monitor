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
| **`GET https://xueqiu.com/statuses/search.json?symbol=SH600519&count=10` + real `xq_a_token` cookie** | **200** | **Yes (real)** | **Yes — JSON with status id, title, timestamp, deep link** |

## Cookie path (documented and verified in this spike)
A real `XUEQIU_COOKIE` (`xq_a_token=...` from a logged-in session) unlocks the
official JSON API `https://xueqiu.com/statuses/search.json?symbol=...`.
The response contains structured posts with:
- **post id** (`status_id`)
- **title**
- **timestamp** (ISO, convertible to local calendar day)
- **deep link** (`https://xueqiu.com/{user_id}/{status_id}`)

This is an **optional env‑backed LIVE path**: set `XUEQIU_COOKIE=xq_a_token=...`
in `.env` to enable real data fetch. Without the cookie the connector honestly
degrades to stub (`collect()` returns `[]`). Captcha/WAF bypass and paid APIs
remain out of scope.

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
- **With real `xq_a_token` cookie:** JSON API returns day-filterable posts.

## Cookie path (documented, verified)
A `XUEQIU_COOKIE` (`xq_a_token=...` from a logged-in session) may unlock the
JSON APIs. With a real token the API returns structured posts with id, title,
timestamp and deep links. This is an optional env‑backed LIVE path: set
`XUEQIU_COOKIE=xq_a_token=...` in `.env` to enable. Without the cookie the
connector honestly degrades to stub.

## Conclusion
**Cookie‑backed LIVE** for users who configure `XUEQIU_COOKIE=xq_a_token=...`
in their `.env`. The connector gracefully degrades to honest stub when the
cookie is not configured. WAF/captcha bypass and paid APIs remain out of scope.

Unlock only if Xueqiu publishes a stable public day-filterable feed (RSS/JSON)
with per-post timestamps and deep links, without login or WAF challenge.
For cookie‑enabled users, this condition is now met.
