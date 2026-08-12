# FREE_SOURCE_AUDIT

审计日期：2026-08-12 · tip 见当前分支 HEAD

## P0 已处理（本分支）

| 项 | 动作 |
|---|---|
| stockhead_au 未进 settings | 已 enabled |
| UK/HK/KR/JP/US 缺 Yahoo/Google | 已新增 8 源 + registry + tests |
| BME >31 天窗口 | client 按 31 天 chunk |
| ASX 最多 5 条 | raw_metadata `api_max_items_per_company: 5` |
| dedupe uk/us/jp 时区 | `_news_key` 显式 LONDON / NEW_YORK / TOKYO |
| stockhead 社区 dedupe | `article_slug` 键，独立于 hotcopper |

## 仍诚实 STOP / 未接（勿假装）

| source | 原因 |
|---|---|
| sedar_plus / cse / neo | 无稳定免费 API |
| sgx_announcements | SPA + 403 |
| fi_oam / six_official | 无 per-issuer 免费 JSON |
| hotcopper / lse / xueqiu / vic / yellowbrick / x | stub，无 login-free 面 |

## 已知上限（文档化，非 bug）

- 多数源 `MAX_LOOKBACK_DAYS=30`
- RSS/Google/Yahoo rolling window（~30–50 条）
- ASX API 每公司最新 5 条
- BME API 单次请求 ~31 天（已 chunk）
- CEO.ca ~50 条/页，需 until 分页

## 新闻覆盖矩阵（本分支后）

| 市场 | Yahoo | Google | 其他 |
|---|---|---|---|
| US | yahoo_us | google_news_us | Finnhub（要 key） |
| UK | yahoo_uk | google_news_uk | — |
| HK | yahoo_hk | google_news_hk | — |
| KR | yahoo_kr | google_news_kr | naver_news |
| JP | yahoo_jp | google_news_jp | — |
| CA/TW/AU/FR/DE/… | 已有 | 已有 | — |
