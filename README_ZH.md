# Investment Monitor 中文使用指南

> 本文面向本地使用者和部署维护者，说明 Investment Monitor 做什么、如何启动、如何维护列表和数据源、如何阅读每日信息，以及如何安全使用 Research 研究卡。采集 API key、云主机口令和 nginx 口令仍不进仓库；下列 5 个是私密仓库的应用登录测试账号。

完整的市场覆盖、连接器边界、探针证据和技术审计仍保留在项目根目录的 [README.md](README.md) 与 [README_EN.md](README_EN.md)。

## 测试登录账号

启动 Web（`investment-monitor-web`）时，若库里还没有下列用户名，会自动创建这五个账号。生产站点只走这个页面登录，不再弹出 nginx Basic（`im`）系统对话框。

| 用户名 | 角色 | 密码 | 说明 |
|---|---|---|---|
| 1 | 管理员 | `Rk8nM2wQ7pLx` | 可改实例密钥、调用 `/api/admin/users` 建号 |
| 2 | 普通用户 | `Hj4cT9bV3sNw` | 持仓/列表/已读/Research 仅自己可见 |
| 3 | 普通用户 | `Pq6fD1yK8mZr` | 同上 |
| 4 | 普通用户 | `Wb3gL7xC5nHs` | 同上 |
| 5 | 普通用户 | `Yt2sF8qN4vJm` | 同上 |

- 爬虫仍按全站关注并集只采集一次；公司档案和公告共享。
- `legacy-local` 旧数据不属于这五个号；登录后列表是空的。
- 已存在的同名用户不会被改密。已有可登录账号后，Web 会启用 Session 登录墙。

## 1. 这是什么

Investment Monitor 是一个以个人 watchlist 为中心的本地金融信息工作台。你维护三类公司：

- **Holdings / 持仓**：已经持有的公司；
- **Planned / 计划**：计划进一步研究或可能买入的公司；
- **Watchlist / 关注列表**：持续观察但尚未有明确计划的公司。

系统从已经配置且允许展示的免费公开数据源或你自行配置的 API 数据源中采集资料，并将资料保存到本地 SQLite 数据库。Web 页面用于浏览、筛选和研究已经入库的信息。

它处理的主要资料类型是：

| 类型 | 含义 | 典型内容 |
| --- | --- | --- |
| Filing / 披露 | 官方监管机构或交易所披露 | SEC EDGAR、交易所公告、监管文件 |
| News / 新闻 | 与公司相关的新闻资料 | Yahoo、Google News、配置的新闻源 |
| Community / 社区 | 公开论坛、文章、社交或 newsletter 类资料 | 仅限项目明确标注为 LIVE 的来源 |
| Research / 研究卡 | 基于已入库资料的结构化研究辅助 | 近期变化、风险、波动因素、待验证问题 |

## 2. 它不做什么

Investment Monitor 不是自动交易、荐股或价格预测系统。特别是 Research 研究卡：

- 不给出买入、卖出、持有建议；
- 不给出目标价；
- 不预测涨跌方向或幅度；
- 不扫描全市场寻找“推荐股票”；
- 不支持绕过 Holdings / Planned / Watchlist 对任意 ticker 生成分析；
- 不会自动触发采集、自动生成全部公司的卡片，或自动发送任何消息；
- 不会把没有稳定公开接口的数据源伪装成“已连接”。

研究卡是帮助你更快阅读已有资料的工具；最终判断、资料核实和投资决策仍由使用者负责。

## 3. 页面导览

启动 Web 服务后，主要页面如下。

| 页面 | 网址 | 用途 |
| --- | --- | --- |
| 每日信息 | `/today` | 按日期范围、列表、公司查看已入库的披露、新闻和社区更新 |
| 研究 | `/research` | 在指定日期范围内，用与每日信息完全一致的资料生成或查看研究卡 |
| 列表与来源 | `/manage` 或导航中的 Lists & sources | 维护公司列表、查看来源状态、了解是否已连接 |

右上角的语言入口用于切换中文和英文。语言只影响产品 UI 和研究卡的分析语言；不会翻译或改写公司名称、ticker、公告标题、新闻标题、社区原文、URL、source ID 或数据源品牌名。

## 4. 每日信息：如何看资料

进入 `/today` 后，依次选择：

1. **从 / From**：开始日期；
2. **到 / To**：结束日期；
3. **列表 / List**：全部列表、持仓、计划或关注列表；
4. 点击 **生成报告 / Generate reports**。

页面按日期倒序显示。每一天内部按公司分组；每家公司内部再按官方披露、新闻、社区资料分类。

### 日期是如何判断的

每日信息使用 **Asia/Shanghai（上海）自然日**，而不是采集到服务器的时间。

- 对带完整发布时间的新闻、社区和大多数披露，系统使用资料的规范事件时间 `effective_at` 并换算到上海日期；
- 对只提供日期、没有可靠时间的交易所披露，系统尊重资料中的原始 `calendar_date`，不因时区换算把公告移到前一天或后一天；
- `collected_at`、抓取时间和写入数据库时间不用于决定事件属于哪一天。

因此，建议以 Daily Information 的日期范围作为阅读和生成研究卡的共同口径。

### 软去重说明

相同或高度相似的资料可能来自不同来源。系统的“软去重”只会增加类似 “Also seen on … / 也见于 …” 的提示：

- 不删除任何原始行；
- 不改变计数；
- 不把一条来源资料伪装成另一条来源资料。

## 5. Research 研究卡：最重要的使用规则

Research 页面不是按“最近一年”或“最近若干条”另找资料。它和每日信息共用同一套日期、列表、来源和公司关联语义。

### 正确的使用流程

1. 先打开 `/today`，选定你希望研究的 **从 / 到 / 列表**；
2. 阅读该范围内的公司资料，确认范围合理；
3. 打开 `/research`；
4. 使用相同的 **从 / 到 / 列表**；
5. 在目标公司的行上点击 **生成研究卡 / Generate research card**；
6. 等待任务完成后查看卡片；若有新资料，选择 **重新生成 / Regenerate**。

Research 的 URL 会保留筛选条件，例如：

```text
/research?start_date=2026-08-10&end_date=2026-08-13&list=holdings&lang=zh-CN
```

刷新页面或切换中英文不会丢失日期范围和列表。

### Daily 与 Research 的资料一致性

对同一家公司、同一个开始日期、结束日期和列表范围：

```text
每日信息中显示给该公司的资料
=
Research 的候选证据
=
正常生成时发送给模型的证据
=
研究卡保存的证据快照
```

这意味着：

- Daily 中没有出现的资料，Research 不会偷偷拿去分析；
- Daily 中该公司的资料不会因为“只取最近 N 条”而被静默遗漏；
- 同 ticker 但不同市场的公司不会互相混入证据；
- 一条关联多家公司的资料会按各自公司的 Daily 展示行正确处理；
- Research 不会使用采集时间、数据库写入时间或范围外资料补足内容。

### 为什么有时不能生成

Research 只使用当前范围内的资料。如果当前范围资料不足，或资料全部来自社区而没有官方披露/新闻支持，系统会诚实显示“证据不足”，不会编造看似完整的结论。

Research 会完整使用当前范围资料；它不会正常情况下只取 30 条、120 条或任意固定数量。

但是，系统仍有请求体安全上限。如果整个日期范围的完整资料无法在不遗漏任何资料的情况下安全发送给模型，页面会显示：

> 所选日期范围内的资料过多，无法在不遗漏资料的情况下生成研究卡。请缩短日期范围后重试。

此时系统不会：

- 自动删掉部分资料后生成；
- 自动多次调用模型做分段摘要；
- 保存一张基于不完整资料的“成功卡”。

请缩短日期范围后再生成。

### 研究卡中包含什么

每张研究卡包含：

- 证据覆盖情况：日期范围、列表范围、资料数量和分类数量；
- 近期需要理解的变化：只概括证据中明确出现的变化；
- 主要风险：每条风险带有证据引用和来源性质；
- 主要波动因素：说明需要关注的事件或信号，但不预测价格；
- 待验证问题：列出资料不足、矛盾或尚需核实的事项；
- 完整证据清单：保留原始标题、来源、时间、URL 和资料类型。

社区观点会被标明为社区观点，不能被模型或页面包装成官方披露事实。每个实质性判断都应通过 `E1`、`E2` 等证据编号回溯到本次生成使用的资料。

### 打印 / 保存 PDF

研究卡成功生成后，卡片标题右侧会出现「打印 / 保存 PDF」按钮。点击后系统打开**浏览器原生打印窗口**，你在该窗口选择「另存为 PDF / Save as PDF」，并自行选择本地文件名和保存目录。

PDF 是该张卡的完整、可追溯版本，包含：

- 公司名称、ticker、市场；
- 生成所用日期范围（From / To）与列表范围；
- 生成时间；
- 范围内证据总数与 Filing / News / Community 分类数量；
- 实际发送给模型的证据数；
- 明确的研究辅助免责声明；
- 近期变化、主要风险、主要波动因素、待验证问题；
- 完整证据清单（`E1`/`E2`… 引用编号、类型、来源、原始标题、事件时间、原始 URL）。

关键边界：

- PDF 是该卡生成时冻结的证据快照，不会因为后来新增资料而自动更新；
- 卡片标记为「有新证据」（stale）时，仍可打印旧卡作为历史结果，但应重新生成新卡以反映当前范围的新证据；
- 切换日期范围或列表后，旧卡及其打印按钮会一起消失，绝不会把范围 A 的卡当作范围 B 的内容打印；
- 系统不在服务器保存 PDF，不自动上传 PDF，不替用户决定保存路径；PDF 文件由你的浏览器在本地生成并保存；
- PDF 仍仅供研究辅助，不构成投资建议。

### 缓存、范围和“有新证据”

研究卡缓存不是只按公司名保存。缓存身份包含：

- 公司；
- UI/分析语言；
- 开始日期、结束日期和列表范围；
- 模型与不含密钥的 provider 标识；
- prompt、schema 与证据规则版本；
- 本次实际使用资料的稳定 ID、事件时间和 prompt 相关字段。

因此，范围 A 的研究卡不会冒充范围 B 的最新卡。切换日期或列表时，页面会清空旧范围的卡片。当前范围有新增、删除或实质修改的资料时，该范围的旧卡会标记为需要更新；范围外资料变化不会让当前范围卡错误失效。

## 6. 首次启动

### 前提

- Python 3.9 或更高版本；
- Git（开发和更新仓库时需要）；
- Node.js 仅用于 JavaScript 语法检查，不是运行服务所必需；
- 项目运行时以 Python 标准库和 SQLite 为主。

在 PowerShell 中进入仓库根目录：

```powershell
Set-Location "C:\path\to\investment-monitor"
python --version
```

创建本机配置文件：

```powershell
Copy-Item .env.example .env
```

`.env` 是本机私密配置文件，不应提交到 Git、复制到聊天、写入 README 或发送给他人。

启动本机服务：

```powershell
$env:PYTHONPATH = "src"
python -m investment_monitor.web --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765/today
```

`127.0.0.1` 只允许当前电脑访问，适合本地预览。不要为了方便把它改为 `0.0.0.0` 并直接暴露到公网；生产部署应由反向代理、身份验证和 HTTPS 配置负责。

## 7. 公司列表：如何添加与管理

首次导入可编辑：

```text
config/universe.csv
```

示例：

```csv
ticker,list_type,market
AAPL,holdings,us
MSFT,watchlist,us
00700,planned,hk
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `ticker` | 市场规范化前的公司代码 |
| `list_type` | `holdings`、`planned` 或 `watchlist` |
| `market` | 市场代码，例如 `us`、`hk`、`cn`、`jp`、`kr` |

CSV 主要用于首次导入。之后，SQLite 中的公司与列表关联才是权威来源；建议通过 Web 的列表管理页面增删和调整公司。一个公司可以同时位于多个固定列表中，不会因此重复保存同一条资料。

### 在 Lists & sources 中批量添加公司

也可以直接在「添加代码」输入框一次粘贴多家公司，并为每一项指定市场：

```text
AAPL.US, 0700.HK, 005930.KR, RY.TO, BHP.AX
```

规则：

- 多个项目可用逗号、空格、分号或换行分隔；
- 推荐格式为 `TICKER.MARKET`，例如 `.US`、`.HK`、`.KR` 等；也支持常用交易所缩写，例如 `.TO` → 加拿大、`.AX` → 澳大利亚、`.KS` → 韩国、`.L` → 英国、`.T` → 日本、`.SS`/`.SZ` → 中国 A 股；
- 没有可识别后缀的 ticker 使用页面上的市场下拉框作为默认市场；
- 只有受支持的后缀才会被解释为市场/交易所；ticker 本身含点（例如 `BRK.B`、`BF.B`）不会被误判为市场后缀；
- 同 ticker 不同市场会作为两家独立公司保存。

## 8. 数据源与“已连接”状态

数据源配置位于：

```text
config/settings.yaml
```

Web 的 Lists & sources 页面会展示每个连接器的启用状态、最近尝试、最近成功和失败原因。

状态的含义：

| 状态 | 含义 |
| --- | --- |
| Connected / 已连接 | 已具备所需配置，且至少有成功运行记录或可用连接条件 |
| Waiting for data / 等待资料 | 已启用，但尚无相符资料或尚未完成成功采集 |
| Not connected / 未连接 | 缺少必需 key、来源是诚实 stub，或当前没有稳定可用的公开连接方式 |

不要把“Not connected”理解为系统故障。某些资料源依法或技术上没有稳定的免费公开 API，项目会诚实返回空结果，而不是伪造 LIVE 数据。

## 9. 环境变量：安全配置方式

所有可配置项的模板和注释在：

```text
.env.example
```

只在本机 `.env` 或受保护的部署环境变量中写真实值。

### 常见数据源配置

不同来源需求不同。常见变量示例：

```env
# SEC 请求识别所需联系邮箱
SEC_USER_AGENT_EMAIL=your-email@example.com

# 可选：使用 Finnhub 的 US 新闻
FINNHUB_API_KEY=

# 可选：OpenDART 韩国披露
DART_API_KEY=
```

是否需要某个 key，以 `.env.example` 的说明和 Lists & sources 页面状态为准。

### 地域性权威新闻 RSS

项目接入 30 个当地主要媒体来源，覆盖全部 29 个国家/地区市场。21 个来源是媒体官方 RSS 直连；CN、JP、TW、AU、IN、BE、DE、NL、PL 的 9 个来源使用“公司名 + 媒体域名”的 Google News RSS，并校验每条 RSS `source` 确实属于指定媒体。两种方式都不抓正文；9 个替代发现源强制要求启用 `CONTENT_RELEVANCE_AI_ENABLED`，没有公司主角 AI 门槛时失败关闭。

公开 RSS 不自动等同于商业再发布许可；正式商业部署前应逐家复核条款。替代发现源明确标为 Google News，不冒充媒体官方 API，也不用脆弱 HTML 或小道媒体填补。完整来源、直连接口缺口与理由见 [`docs/REGIONAL_AUTHORITATIVE_NEWS_COVERAGE_ZH.md`](docs/REGIONAL_AUTHORITATIVE_NEWS_COVERAGE_ZH.md)。

### Research 模型配置

Research 默认关闭。启用后，点击“生成研究卡”会将**你选择公司、日期范围和列表范围内已经入库的公开资料**发送到你自行配置的 OpenAI-compatible 模型服务。

示例模板：

```env
RESEARCH_AI_ENABLED=false
RESEARCH_AI_BASE_URL=https://api.deepseek.com
RESEARCH_AI_MODEL=deepseek-v4-flash
RESEARCH_AI_API_KEY=
RESEARCH_AI_REQUEST_TIMEOUT_SECONDS=60
# 新闻/社区入库前，仅保留目标公司为主角或主要受影响方的内容。
CONTENT_RELEVANCE_AI_ENABLED=false
RESEARCH_MIN_EVIDENCE_ITEMS=3
```

启用步骤：

1. 在 `.env` 中将 `RESEARCH_AI_ENABLED` 改为 `true`；
2. 填写你自己的 `RESEARCH_AI_API_KEY`；
3. 按服务商文档填写 Base URL 和模型名；
4. 重启 Web 服务；
5. 打开 `/research`，确认页面显示模型已配置；
6. 选择日期范围和列表后，手动点击生成。

如果还需要阻止仅“顺带提及”目标公司的新闻或社区内容入库，将
`CONTENT_RELEVANCE_AI_ENABLED` 设为 `true`。该开关复用上面的模型、Base URL、
API key 与超时配置；只影响 `news` 和 `community`，披露类信息不经过此判定。
模型异常、返回缺项或语义不明确时会失败关闭，不会把未经确认的内容归到公司名下。

安全边界：

- 浏览器不会获得 API key；
- API key 不写入 SQLite；
- API key 不返回给前端；
- 系统不应在日志或错误提示中打印 key；
- 未启用或未配置 key 时，系统不请求模型服务，也不生成假内容；
- 模型的自由文本不会直接作为 HTML 注入页面，输出必须先通过结构化 JSON 与证据引用验证。

### HTTPS 反向代理部署

Web 服务在本机以 HTTP 监听、但浏览器通过 HTTPS 反向代理访问时，生产部署必须同时满足以下三点，缺一不可：

1. 在受保护的部署环境中设置：

```env
WEB_EXTERNAL_SCHEME=https
```

2. 设置访问令牌 `WEB_AUTH_TOKEN`（强随机值，勿写入 git）。设置后所有 `/api/*` 请求必须携带
   `Authorization: Bearer <WEB_AUTH_TOKEN>`，否则返回 401。浏览器端在控制台执行
   `localStorage.setItem("im_web_auth_token", "<token>")` 后页面请求会自动带上；本机开发可留空以保持无鉴权。

3. 反向代理转发时保留客户端的原始 Host 头（含端口）。以 nginx 为例，`location` 内应使用 `$http_host` 而不是 `$host`：

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $http_host;   # 保留客户端的 host:port
}
```

同时应用进程只监听/映射 `127.0.0.1`，云安全组**不得**对公网放行 `8765`；完整清单见 `docs/security/HARDENING_CHECKLIST.md`。

本地 `http://127.0.0.1:8765` 开发通常保持：

```env
WEB_EXTERNAL_SCHEME=http
WEB_AUTH_TOKEN=
```

**原理与症状**：`WEB_EXTERNAL_SCHEME` 用于同源 POST/CSRF 校验，表示浏览器实际看到的外部协议，不是 Python 进程内部监听协议；客户端传来的 `X-Forwarded-Proto` 不被信任。服务端对**每一个** JSON POST 请求做同源校验：Origin 的 (scheme, hostname, 有效端口) 必须与 Host 完全一致，Host/Origin 不带端口时按协议默认端口计算（https→443、http→80）。缺少 `WEB_EXTERNAL_SCHEME=https` 时默认按 `http` 比对，`https://...` 的 Origin 会被拒绝；nginx 用 `$host` 转发会丢弃端口，对外暴露在非 443 端口时，后端按默认端口 443 计算、与真实端口不匹配。任一不满足都会让所有 JSON POST 写接口（例如批量添加公司 `POST /api/companies/batch`）返回 `403`，响应体为 `{"error": "cross-origin request rejected"}`，而 GET 页面一切正常——容易误判为服务故障，实际是反代配置问题。

## 10. 日常操作建议

一个实用工作流：

1. 在 Lists & sources 页面确认核心来源状态；
2. 运行或等待既有采集流程写入资料；
3. 在 `/today` 选择今天、最近数天或你关心的事件窗口；
4. 选择 Holdings / Planned / Watchlist，先阅读原始披露、新闻与社区资料；
5. 在 `/research` 使用相同 From / To / List；
6. 对需要深入理解的公司手动生成研究卡；
7. 从研究卡的 `E1/E2/...` 证据清单回到原文 URL 核查；
8. 将待验证问题转化为后续阅读或人工研究清单。

不要将 Research 卡替代原始资料阅读。尤其对官方披露、重大新闻和社区观点，应优先打开原始链接核实上下文。

## 11. 常见问题

### 每日信息显示“此日期没有信息”

常见原因：

- 选定日期范围内确实没有已入库的相符资料；
- 公司不在选定列表中；
- 对应数据源尚未运行、未配置或没有匹配结果；
- 资料按上海自然日归属到相邻日期；
- 来源被诚实标记为 Not connected/stub。

请先切换更宽日期范围，再到 Lists & sources 查看该来源的最近尝试与失败详情。

### Research 显示“此日期范围内证据不足”

这表示当前范围内资料不足，或者只有社区材料。系统不会调用模型用常识补全公司故事。可以扩大范围，或等待更多官方披露/新闻进入数据库后再生成。

### Research 显示“所选范围资料过多”

这表示系统不能在不遗漏资料的条件下安全发送完整范围。请缩短日期范围，例如从一个月缩短到一周或几天。系统不会静默只保留前若干条。

### Research 一直显示“生成中”

生成是后台任务。刷新 `/research` 后，页面会从服务器读取权威状态。若任务失败，页面会显示本地化失败状态并允许重新生成。常见失败包括模型超时、认证失败、上游限流、网络错误或模型未按严格 JSON schema 返回结果。

### 模型返回“无效结果”

这通常表示模型返回内容未通过严格研究卡 schema 验证，例如缺字段、引用不存在的证据 ID 或错误标注来源类别。系统拒绝保存这种不可靠卡片是预期安全行为。确认模型名、服务商兼容性和范围大小后重试；不要通过关闭 schema 校验来“修复”。

## 12. 测试与开发验证

在仓库根目录执行：

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

只验证 Research + Daily 关键路径时，可运行：

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_daily_range.py tests/test_web_repository.py tests/test_research_daily_scope.py tests/test_research_repository.py tests/test_research_web.py tests/test_web_app.py tests/test_web_i18n.py tests/test_research_ai.py -q

node --check src/investment_monitor/web_static/app.js
git diff --check
```

Windows 环境中，完整测试若出现 `tests/test_source_backfill_state.py` 的 `PermissionError: [WinError 32]` SQLite 文件锁问题，必须与干净基线的失败 test ID 逐项对比。只有失败集合完全一致时，才能说“无新增失败”；不能把这种结果写成“全绿”。

## 13. 提交前检查清单

涉及 Research/Daily 相关改动时，至少确认：

- [ ] `/today` 仍可按范围和列表生成日报；
- [ ] `/research` 有 From、To、List，且 URL 可复现；
- [ ] 同范围、同公司下 Daily 与 Research 的证据 ID 集合相等；
- [ ] 范围内 31、150 等数量的资料不会被静默截断；
- [ ] 超大请求明确报 `research_range_too_large`，且不调用模型；
- [ ] 范围 A 的卡不会显示到范围 B；
- [ ] 语言切换不改变原始证据文本；
- [ ] API key 不出现在 diff、日志、SQLite、响应或测试快照；
- [ ] `node --check`、相关 pytest、`git diff --check` 都已实际运行；
- [ ] 完整 pytest 的失败集合已与基线比较。

## 14. 维护原则

这个项目的核心原则是资料可追溯与状态诚实：

- 免费来源或用户自备 key；
- 无稳定公开接口时使用诚实 stub；
- 跨源重复只标注，不删行；
- 不自动回复即时通信；
- 密钥不进入文档、提交或数据库；
- 数据源、日期语义和 Research 证据边界应有测试保护；
- 小步变更、先测后提交。

如果要新增市场、连接器或新的 AI 能力，请先阅读根目录 README 中对应市场的来源审计和测试约定，再改变代码。
