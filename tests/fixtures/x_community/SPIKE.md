# Spike: X (Twitter) community public surface (2026-08-11)

## Question

Can we stably collect public **X (Twitter)** community content — posts from
X Communities (`x.com/i/communities/...`) or ticker-relevant posts — filtered
to a calendar day, without login, captcha/WAF bypass, or paid API?

## Product / entity honesty

Product under test = **X** (formerly Twitter, `x.com` / `twitter.com`), its
**Communities** feature (`x.com/i/communities/<id>`, community posts carry a
`community_id`) and its global post stream.

X is a **social post stream** — posts are short-form messages, not forum
threads and not article/news streams. Community posts are grouped by community,
not by ticker; there is **no native per-ticker surface** on X.

## Method

`stdlib urllib` only, browser-like Chrome UA, `Connection: close`, GET only,
no cookie, no login. No Selenium/Playwright, no captcha/login/WAF bypass, no
guest-token flows. Probed 2026-08-11.

- Official X API v2 no-key behavior: `probe_api.py` (林渡舟) — all endpoints
  with no Authorization / fake Bearer / browser UA.
- Public syndication / embed / HTML negative probes: `probe_public.py`
  (沈照临) — direct HTML, oEmbed, syndication, Nitter mirrors, legacy paths.
- Cross-check by SPIKE merge (傅行止): re-probed `api.x.com/2/tweets/
  search/recent` (no key → 401), `x.com` search/community/status HTML,
  `publish.twitter.com/oembed` and `cdn.syndication.twimg.com/tweet-result`
  against a **known-good** tweet (`x.com/jack/status/20`, id `20`), plus the
  official docs (`docs.x.com`): auth requirements, pricing, search operators.

## Evidence (merged)

### Official X API v2 — key required, no-key = 401

| Endpoint | No-key HTTP | key required? | ticker filter? | stable id/time/title/link? |
|---|---|---|---|---|
| `GET /2/tweets/search/recent?query=$NVDA` | **401** | Yes — OAuth2 `users.read`+`tweet.read` or Bearer | cashtag keyword `$NVDA` in `query`; `start_time`/`end_time` (7-day window); `sort_order` | ✅ `id`, `created_at` (ISO 8601 UTC), `text`, `community_id`, `entities.cashtags` |
| `GET /2/tweets/search/recent?query=$NVDA lang:en` | **401** | Yes (same) | same + `lang:` operator | same |
| `GET /2/users/by/username/{user}` | **401** | Yes — Bearer | no | ✅ stable `id`/`name`/`username` |
| `GET /2/users/{id}/tweets` (timeline) | **401** | Yes — OAuth2/Bearer | no (account-level only) | ✅ `id`/`created_at`/`text`/`link` |
| `GET /2/news/search?keywords=AAPL` | **401** | Yes — Bearer | keyword only | — |
| Communities: `GET /2/communities/{id}`, Search Communities (docs) | (needs key) | Yes — Bearer | by community id / keyword | ✅ `community_id` stable (docs) |

Docs (`docs.x.com/x-api`): all reads require OAuth2/Bearer; pricing is
**pay-per-usage credits** — Post Read `$0.005/resource`, Community Read
`$0.005/resource`, User Read `$0.010/resource`, capped at 2M Post reads/month.
No subscription; no free read tier. Every endpoint above answered
`401 Unauthorized` (`application/problem+json`) without a valid key.

### Public surface (no key) — negative

| Probe | HTTP | login/bot-wall? | id / time / title / link? |
|---|---|---|---|
| `GET https://x.com/search?q=NVDA&f=live` | 200 | SPA error shell, client-rendered, no SSR (`Something went wrong`, guest_id cookie only) | **No** — no content for urllib |
| `GET https://x.com/i/communities` | 200 | SPA error shell, no SSR | No |
| `GET https://x.com/i/communities/1` | 404 | login wall | No |
| `GET https://x.com/NYSE` / `x.com/WSJ` | 200 | SPA shell, `data-testid="tweet"` SSR=False | No — profile HTML has no post content |
| `GET https://x.com/jack/status/20` | 200 | no login (single status page) | ⚠️ **single-post page only**: SSR title/og:description contain the tweet text, but only for a **known tweet URL** — no discovery/listing |
| `GET https://publish.twitter.com/oembed?url=…jack/status/20` | **200** | no | ⚠️ embed JSON only: `author_name`/`url`/`html` — **no id/time/link fields**; 404 for non-existent tweet ids |
| `GET https://cdn.syndication.twimg.com/tweet-result?id=20&token=…` | **200** | no | ⚠️ unofficial: returns full tweet JSON (`id_str`, `created_at`, `text`) but `token` is not validated (any value works) and there is **no search/list capability** — only known ids |
| Nitter mirrors (`nitter.net`, `privacydev`, `poast`, `1d4.us`, `tiekoetter`, `xcancel.com`, …) | 0/403 | TLS EOF, connection reset, or `Verifying your browser` (bot check) | No — every tested instance dead or bot-walled |
| `GET https://syndication.twitter.com/timeline/profile?screen_name=…` (legacy) | 200 | no | empty shell, no items |

**Honest answer: no stable, key-free discovery path.** Search, Communities,
and profile timelines are client-rendered SPA shells behind a login wall for
urllib. The only key-free endpoints that return real content — single status
page SSR, oEmbed, syndication `tweet-result` — require a **known tweet id/URL
in advance** (no ticker search, no listing) and the syndication endpoint is
**undocumented** (token not validated, behavior not guaranteed). Nitter RSS
mirrors are all dead or bot-walled.

## Category honesty

- X is a **social post stream** (short-form posts), **not a forum** and
  **not an article/news stream**. Communities group posts by community, not by
  ticker.
- **No structured ticker taxonomy**: the closest thing is the cashtag
  convention (`$NVDA`, surfaced as `entities.cashtags` in API responses), but
  search matching is keyword-level — posts that mention `NVDA` without a
  cashtag are missed, and bare-word matches are noisy. No
  "ticker → all X posts for the day" recall guarantee.
- **No unofficial scrape as default LIVE**: the key-free `tweet-result`
  syndication endpoint is undocumented and token-less; it cannot enumerate
  content and may break at any time. It is not a live-collection path.
- Third-party mirrors (Nitter) are not X surfaces and are all currently dead.

## Market timezone

**America/New_York (US-facing).** API `created_at` is ISO 8601 UTC
(`2026-08-11T08:01:13Z`); single-post SSR/`tweet-result` also expose UTC.
Convert to America/New_York (EDT/EST) for the calendar-day filter in the
connector. Applies only if an API-key path is enabled.

## Conclusion

**Stub·STOP** for key-free collection.

1. **No key-free surface**: X search/Communities/timelines are login-walled
   SPA shells (no SSR), there is no official public RSS/JSON, and every Nitter
   mirror is dead or bot-walled. Same honesty bar as `hotcopper_au`,
   `lse_share_chat`, `xueqiu`.
2. **Official path exists but requires a paid key**: X API v2
   `GET /2/tweets/search/recent` (Bearer/OAuth2, pay-per-usage credits,
   ~`$0.005`/Post read) supports cashtag queries, `start_time`/`end_time`
   within a 7-day window, and returns stable `id` / `created_at` / `text` /
   `community_id`; Communities lookup/search also exist behind the same auth.
   This is the **only compliant LIVE path** — but it needs a user-provided
   paid API key (Bearer, `.env.example` placeholder), so it is **not default
   LIVE** under the no-key rule.
3. **No account-whitelist analog** (unlike Substack): there is no public RSS
   or syndication feed per account/community; account timelines require the
   same paid API key.
4. Category = social post stream, keyword-level cashtag matching only, no
   structured ticker recall. Timezone America/New_York via UTC `created_at`.

Unlock only if the product accepts a **user-provided official X API key**
(pay-per-usage credits): then `search/recent?query=$TICKER&start_time=…` is a
viable LIVE connector (id/time/text/link + `community_id` filter), matching
the API+key option. Without a key, stay Stub·STOP — do not scrape x.com HTML
and do not depend on the undocumented syndication endpoint.
