# Spike: Substack 公共出版物 RSS / JSON 探测（2026-08-11）

## Question

能否在不登录、不破解付费墙的前提下，稳定采集公共 Substack newsletter
（作者通讯）的发布内容（标题 / 时间 / 链接 / 稳定 id）？

## Method

`stdlib urllib` only，Chrome UA，无 cookie，无 Selenium/Playwright，无新 pip。
探测日 2026-08-11。每个出版物探测三类表面：

- publication home（HTML）
- `/feed`（RSS 2.0）
- 公共 JSON API（`/api/v1/archive`、`/api/v1/posts`、`/api/v1/publication`）

出版物选择：3 个真实公共 Substack newsletter —— `noahpinion`、`thediff`、
`notboring`。均为投资 / 金融 / 科技作者通讯，非 waitlist 页，非 yellowbrick。

## Evidence

### noahpinion.substack.com（Noahpinion — Noah Smith，经济学/金融评论）

| URL | HTTP | login/paywall? | stable id/time/title/link? |
|---|---|---|---|
| `GET https://noahpinion.substack.com/` | **200** | 无登录墙；页面含订阅/付费墙提示文案（Substack 常态） | 无 JSON-LD（新版前端客户端渲染）；无法从 HTML 直接取稳定 id |
| `GET https://noahpinion.substack.com/feed` | **200** | 无登录（公开 RSS） | ✅ guid / pubDate / title / link 齐全 |
| `GET https://noahpinion.substack.com/api/v1/archive?sort=new&limit=2` | **200** | 无登录（公开 JSON） | ✅ id=210685540, post_date=2026-08-11T08:01:13, title, canonical_url |
| `GET https://noahpinion.substack.com/api/v1/posts?limit=2` | **200** | 无登录（公开 JSON） | ✅ 同上（返回同源数据） |
| `GET https://noahpinion.substack.com/api/v1/publication` | **403** | — | 无 |

RSS 样本（feed 首两条）：

| 字段 | 值 |
|---|---|
| guid | `https://www.noahpinion.blog/p/the-poverty-of-anti-tech-thought/…` |
| pubDate | `Tue, 11 Aug 2026 08:01:13 GMT` |
| title | `The poverty of anti-tech thought…` |
| link | `https://www.noahpinion.blog/p/the-poverty-of-anti-tech-…` |

注意：canonical 链接指向自定义域名 `www.noahpinion.blog`（Substack 支持自定义域），
guid 即该页 URL，稳定。

### thediff.substack.com（The Diff — Byrne Hobart，金融/科技）

| URL | HTTP | login/paywall? | stable id/time/title/link? |
|---|---|---|---|
| `GET https://thediff.substack.com/` | **200** | 无登录墙；含订阅/付费墙提示文案 | 无 JSON-LD |
| `GET https://thediff.substack.com/feed` | **200** | 无登录（公开 RSS） | ✅ 但仅 1 条占位文 `Coming soon`（2025-02-03），非真实内容流 |
| `GET https://thediff.substack.com/api/v1/archive?sort=new&limit=5` | **200** | 无登录（公开 JSON） | 仅 1 条 id=156405537, post_date=2025-02-03T19:24:11 |
| `GET https://thediff.substack.com/api/v1/posts?limit=2` | **200** | 无登录（公开 JSON） | 同上 |
| `GET https://thediff.substack.com/api/v1/publication` | **403** | — | 无 |
| `GET https://thediff.co/feed`（自建站迁移检查） | 0 | — | SSL `CERTIFICATE_VERIFY_FAILED`（本机 urllib 证书链校验失败，未能读取） |

结论：`thediff.substack.com` 已不再承载真实内容（仅剩占位文），刊物已迁移至
自建域 `thediff.co`，但该站证书链在本机 urllib 下校验失败 —— 按 urllib-only
约束不可作为稳定公开源。

### notboring.substack.com（Not Boring — Packy McCormick，科技投资）

| URL | HTTP | login/paywall? | stable id/time/title/link? |
|---|---|---|---|
| `GET https://notboring.substack.com/` | **200** | 无登录墙；含订阅/付费墙提示文案 | 无 JSON-LD |
| `GET https://notboring.substack.com/feed` | **200** | 无登录（公开 RSS） | ✅ guid / pubDate / title / link 齐全 |
| `GET https://notboring.substack.com/api/v1/archive?sort=new&limit=2` | **200** | 无登录（公开 JSON） | ✅ id=210074894, post_date=2026-08-07T12:50:11, title, canonical_url |
| `GET https://notboring.substack.com/api/v1/posts?limit=2` | **200** | 无登录（公开 JSON） | ✅ 同上 |
| `GET https://notboring.substack.com/api/v1/publication` | **403** | — | 无 |

RSS 样本（feed 首两条）：

| 字段 | 值 |
|---|---|
| guid | `https://www.notboring.co/p/weekly-dose-of-optimism-205` |
| pubDate | `Fri, 07 Aug 2026 12:50:11 GMT` |
| title | `Weekly Dose of Optimism #205` |
| link | `https://www.notboring.co/p/weekly-dose-of-optimism-205` |

同样，canonical 指向自定义域 `www.notboring.co`。

## RSS Item 结构（Substack /feed，稳定）

| 字段 | 说明 | 样本 |
|---|---|---|
| `item/guid` | 稳定 id（== canonical 文章 URL） | `https://www.noahpinion.blog/p/…` |
| `item/title` | 标题 | `Weekly Dose of Optimism #205` |
| `item/link` | 文章链接 | `https://www.notboring.co/p/…` |
| `item/pubDate` | RFC 2822 GMT | `Fri, 07 Aug 2026 12:50:11 GMT` |

## JSON API 结构（/api/v1/archive 与 /api/v1/posts 返回同源）

| 字段 | 类型 | 样本 |
|---|---|---|
| `id` | int | `210074894`（稳定 post id） |
| `post_date` | ISO 8601 | `2026-08-07T12:50:11` |
| `title` | string | `Weekly Dose of Optimism #205` |
| `canonical_url` | URL | `https://www.notboring.co/p/…` |

`/api/v1/archive?sort=new&limit=N` 可作分页（offset 参数存在），`/api/v1/posts?limit=N`
仅返回 N 条最新 —— 两者都能拿到稳定 id / 时间 / 标题 / 链接。

## Login / Paywall 评估

- 公开面（home / feed / archive JSON / posts JSON）：**无登录墙**，裸 urllib 可取。
- 正文付费墙：个别文章全文可能付费（`paid subscribers` 提示），但**元数据**
  （id / 时间 / 标题 / 链接）在 RSS 与 JSON 中全部公开。
- `/api/v1/publication`：403，不公开；未发现需要登录的元数据端点。

## Ticker 论坛能力评估

**Substack 是作者 newsletter，不是 ticker 论坛。**

- 无按股票 ticker 检索/过滤的公开接口；内容按作者（publication）组织。
- 无公开评论线程 API 可用作论坛（评论挂在各 post 页面，需页面渲染）。
- 可作为「作者/刊物级新闻源」接入（RSS 或 archive JSON 轮询），
  但**不能**作为论坛/社区讨论源，也无法做 ticker 粒度过滤。

## Conclusion

**LIVE（作者级新闻元数据）—— 可行且稳定**，对每个真实公共 Substack 出版物：

1. `/feed`：公开 RSS 2.0，guid/title/link/pubDate 稳定。
2. `/api/v1/archive?sort=new&limit=N`：公开 JSON，id/post_date/title/canonical_url 稳定，支持分页。
3. 主页 HTML：无 JSON-LD（客户端渲染），**不要**从 HTML 提取元数据。

**注意**：先确认出版物仍在 Substack 承载且未迁移自建域（如 thediff 已迁走）；
canonical URL 可能指向自定义域（noahpinion.blog / notboring.co），需按 canonical_url 采集。
**STOP（论坛能力）**：Substack 无 ticker 论坛面，评论无公开 API，不接入论坛管线。

## Probe Script

见 `probe_pub_rss.py`（stdlib urllib only，可复现）。
