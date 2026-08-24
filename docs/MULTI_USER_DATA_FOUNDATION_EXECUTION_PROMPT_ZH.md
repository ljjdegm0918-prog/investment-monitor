# 多账户数据基础执行提示词

## 角色与目标

你是负责 SQLite 数据迁移、服务端授权边界和测试的高级工程师。请从 `origin/ai功能测试` 创建隔离 worktree/功能分支，实现多账户数据基础，并通过 PR 合并回 `ai功能测试`。不得直接修改用户当前工作目录，不得撤销或带入无关改动。

本次只实现数据库所有权和 repository 隔离；不实现登录 UI、密码、Session、公开注册、MFA 或服务器部署。完成后 Web 仍映射到确定的 legacy 用户，但数据库和 repository 必须可以用两个可信 user_id 证明完全隔离。详细数据合同以 `docs/MULTI_USER_DATA_FOUNDATION_PLAN_ZH.md` 为准。

## 不可违反的边界

1. `companies`、`information_items`、采集结果和 source sync state 全局共享。
2. list、membership、read state、Research card/cache/generation 属于单一用户。
3. 旧数据固定归属 `legacy-local`，不能由第一个登录者认领。
4. 客户端不能提交/选择 user_id；本 PR 不新增这种接口。
5. `active_companies` 是全部用户列表成员的去重并集，不是当前用户视图。
6. Research 的所有读写、缓存、生成状态和后台完成/失败必须带 user_id。
7. 不得仅在 UI 过滤；数据库查询和更新必须强制 owner 条件。
8. 不得把 connector 密钥或 `app_settings` 误迁成普通用户可写数据。
9. 不得用非原子的 `executescript` 拼装危险的多表重建并假装可回滚。
10. 迁移失败必须停止启动，不能部分成功、吞错或静默丢数据。

## 实施关卡

### Gate A：基线与影响面

运行 Web、Research、persistent pipeline 基线测试；枚举所有私有 SQL；固定共享与私有数据清单；先写迁移前后 schema 与 legacy 数据映射测试。

### Gate B：版本化迁移

引入 `schema_migrations` 和顺序 runner；创建 deterministic legacy 用户；事务化重建 list/membership/read state；给 Research card 增加强制所有权；保留 ID/时间戳/内容/evidence；校验 count、PK、孤儿、unique、foreign key；证明重复启动幂等。

### Gate C：Repository 用户作用域

将用户态 repository 绑定可信 context；列表、成员、Daily/Feed、已读和 counts 查询加 owner；搜索候选可共享但不得返回其他用户 list slugs；添加公司复用公共 identity，只写当前用户 membership；全局采集 union 保持跨用户去重。

### Gate D：Research 隔离

cards 增加 user_id 与 owner-first indexes；cache/latest/in-progress/create/complete/fail/card/evidence/status 全带 owner；worker 捕获 user_id 并在调用模型前重验 scope；两用户同公司/范围可生成各自卡片。

### Gate E：反向安全测试

覆盖同名列表、跨用户 CRUD/read/bulk read、猜测对象 ID、Research 异步 TOCTOU、active union、迁移重复运行/故障/orphan 冲突、相关回归和 `git diff --check`。

## 临时多角色编排

1. Schema/Migration 实现者：版本 runner、表重建、legacy 迁移、WebRepository 用户作用域及数据库测试。
2. Research 实现者：ResearchRepository/Service owner contract、后台任务和隔离测试。
3. Security Reviewer：反向检查 IDOR、遗漏 SQL、缓存串用、FK 缺口和迁移原子性。
4. 主编排者：解决接口冲突、运行回归、更新文档并提交 PR。

共享工作树时每位实现者必须遵守文件所有权，不得回退他人改动；接口冲突须协调。

## PR 完成定义

- 方案与提示词随代码提交；当前用户工作树未被修改；legacy 迁移无损且幂等；两用户数据库和 Research 隔离测试通过；现有关键回归通过；PR base 为 `ai功能测试`；PR 明确“尚未实现登录/密码/Session”，不得包装成已可公网多用户使用。
