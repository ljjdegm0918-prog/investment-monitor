# 多账户独立数据基础详细方案

## 1. 本 PR 的目标

本 PR 只建立可安全承载多账户的数据库与 repository 边界，不开放公网注册、用户名密码登录或管理员页面。

完成后应满足：

- 公司身份、公开披露、新闻、社区资料、采集状态继续全局共享；
- 每个用户的列表、列表成员关系、已读状态和 Research 卡片彼此隔离；
- 旧单用户数据库中的全部私有数据无损归属到确定的 legacy 用户；
- repository 已能用两个不同的可信 `user_id` 做隔离测试；
- Web 仍以 legacy 用户兼容运行，不能从浏览器提交或选择 `user_id`；
- 后续认证 PR 只需把经过验证的 Session 映射到服务器端 `user_id`，无需再次重新设计数据所有权。

本 PR 明确不包含：密码哈希、登录页面、Session Cookie、用户自助注册、邮件找回密码、管理员 UI、MFA、部署配置。没有这些功能前，不得宣称产品已经支持公网多用户登录。

## 2. 数据边界

### 全局共享数据

- `companies`
- `information_items`
- `information_item_tickers`
- `ingestion_runs` / `ingestion_logs`
- `source_ticker_sync_state`
- connector credentials 与实例级 `app_settings`

同一家公司被多个用户关注时只采集和保存一次。全局调度使用全部用户列表成员的并集；任何一个用户移除公司都不能删除其他用户的关系或公共历史资料。

### 用户私有数据

- 用户身份记录；
- Holdings / Planned / Watchlist 与自定义列表；
- 公司和列表的成员关系；
- 每条公开资料的已读状态；
- Research 卡片、生成状态、缓存与证据快照的访问权。

## 3. 目标表结构

`users` 本 PR 只存稳定身份与生命周期，不存密码：

```text
id INTEGER PRIMARY KEY
subject TEXT NOT NULL UNIQUE
display_name TEXT NOT NULL
status TEXT NOT NULL CHECK(status IN ('legacy', 'active', 'disabled'))
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

迁移固定创建一个不可歧义的 `legacy-local` 用户。旧数据全部归属此用户，绝不根据“第一个登录的人”动态认领。

`system_lists` 保留现有表名以减少调用面变化，但加入 `user_id` 和 `name_key`，唯一约束改为 `(user_id, slug)`、`(user_id, name_key)`、`(user_id, position)`。不同用户可以分别拥有 `holdings`。

`company_list_memberships` 增加 `user_id`，主键为 `(user_id, company_id, list_id)`，并以 `(user_id, list_id)` 复合外键保证不能把 A 的成员关系写进 B 的列表。

`information_read_state` 主键改为 `(user_id, item_id)`；没有记录表示该用户未读。

`research_cards` 增加 `user_id INTEGER NOT NULL REFERENCES users(id)`。所有查找、缓存、并发生成去重、完成和失败更新都必须同时使用 `user_id`。Research 证据表通过 card 外键继承归属；读取证据时必须先验证 card owner。

## 4. Repository 合同

用户态 repository 必须绑定服务器端 principal，不能接受来自 query/body 的 `user_id`。本 PR 可保留 legacy 默认值供现有应用和测试兼容，但新增双用户测试必须显式创建两个 repository scope。

必须隔离：列表 CRUD、公司列表视图、membership、feed/daily/counts、单条与批量已读、Research 公司范围、卡片缓存、generation 状态及 card/evidence 读取。

全局方法必须在名称和注释中明确，且不得隐式使用当前用户：每日采集 active companies union、source/ticker sync state、ingestion 状态、公共公司和 information item 保存。

## 5. 迁移策略

1. 新增单调递增的 `schema_migrations(version, checksum, applied_at)`。
2. 从当前受支持的单用户 schema 创建确定的 legacy 用户。
3. 使用 `_new` 表重建需要改变唯一键/主键的表，保留原始 ID。
4. 将旧 list、membership、read state、Research card 复制给 legacy 用户。
5. 对源/目标行数、主键集合、孤儿行、唯一冲突执行显式校验。
6. 必要时只在隔离的重建事务中关闭 FK，提交前执行 `foreign_key_check`。
7. 迁移版本记录最后写入；任一步失败不得留下“已迁移”标志。
8. 重启和重复初始化必须幂等，不能重复用户、列表或成员关系。

升级前必须备份 SQLite。产品回滚方式是恢复备份，不支持让旧二进制写入新 schema。

## 6. 安全规则

- 客户端永远不能决定 `user_id`；
- 跨用户访问 list/card/generation 返回 404，不泄露对象是否存在；
- Research worker 必须冻结 user_id，并在调用模型前重新验证该用户的列表成员关系；
- Research cache 和 in-progress 去重键包含 user_id，用户之间不共享卡片；
- 普通用户未来不得读写实例级 `app_settings`、数据源密钥和采集配置；
- 本 PR 不创建弱口令、默认口令或明文凭据字段。

## 7. 验收矩阵

1. 旧库迁移：固定/自定义列表、membership、已读、Research 卡片和证据全部保留并归 legacy 用户，公共 information items 数量不变。
2. 连续初始化两次，schema/version/ID/行数不变。
3. 两用户同名列表可以并存，同一用户内重复被拒。
4. A 添加/移除/改名不会改变 B。
5. 同一 item A 已读、B 未读；bulk read 只更新当前用户可见范围。
6. A/B 同时关注 AAPL，公共 item 只有一份；A 移除后全局 active union 仍有 AAPL，最后一位移除后才停止采集。
7. A 无法读取 B 的 Research card/generation/evidence。
8. A/B 同公司、语言和范围的 Research cache/in-progress 状态相互独立。
9. FK/integrity check 通过；孤儿/归属冲突时迁移失败关闭。
10. 现有 Web/Research/持久化测试及 `git diff --check` 通过。

## 8. 后续 PR

数据库基础合并后，再独立实现认证层：Argon2id 密码哈希、管理员创建账号、Secure/HttpOnly/SameSite Session Cookie、登录限流、密码修改后撤销 Session、管理员权限和审计日志。认证 PR 必须从可信 Session 产生 principal，再创建 user-scoped repository，不能透传浏览器提交的 user_id。
