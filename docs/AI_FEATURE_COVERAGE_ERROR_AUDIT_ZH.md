# AI 功能测试：网站覆盖状态与错误审查

## 结论

`Global market information coverage` 是静态能力覆盖表，不是实时 API 健康检查。原页面的 `unavailable` / `unknown` 大部分表示尚未覆盖或尚未评估，并不等于网站请求失败。

本次调整：

- 页面聚焦用户主动查询和分析的股票，移除 ETF Universe 与 ETF Disclosure 两列；
- 保留后端 ETF 覆盖字段和采集代码，避免破坏现有数据契约，后续可以恢复；
- 将原始状态转换为更清楚、但仍然真实的产品文案，例如 `Not covered` / `未覆盖`、`Not assessed` / `尚未评估`；
- 股票或地区信息本身缺失时统一显示破折号，不再把缺少元数据写成 `Unavailable`；
- 将 `pytest` 的默认收集目录限制为正式的 `tests/`，避免误收集 `agents_sdk/runtime_runs` 中的临时测试副本。

## 缺少 API Key 或配置路径：暂时跳过

以下来源已启用，但当前本地环境没有必要的凭据或人工审核配置。注册表会将它们标记为未连接并跳过，不应伪装成可用。

| 来源 | 缺少配置 | 影响 |
| --- | --- | --- |
| OpenDART | `DART_API_KEY` | 韩国公司披露 |
| Companies House | `COMPANIES_HOUSE_API_KEY` | 英国法定申报 |
| Finnhub News | `FINNHUB_API_KEY` | Finnhub 公司新闻 |
| Canada EDGAR cross-listing | `CA_EDGAR_IDENTITY_PATH` | 加拿大公司到 SEC 身份映射 |
| Canada issuer IR | `CA_IR_CONFIG_PATH` | 加拿大公司 IR 来源清单 |
| X Community | `X_BEARER_TOKEN` | X 社区内容 |
| SGX announcements | `SGX_KNOWN_ANNOUNCEMENTS_PATH` | 新加坡已审核公告入口 |
| Singapore EDGAR cross-listing | `SG_EDGAR_IDENTITY_PATH` | 新加坡公司到 SEC 身份映射 |
| EDINET | `EDINET_API_KEY` | 日本法定申报 |

说明：`SEC_USER_AGENT` 当前已配置；Canada/Singapore 的 EDGAR 路径仍需单独提供并审核。ETF 专属披露目前没有已接入的免费稳定来源，因此从产品页面移除 ETF 展示，但不会篡改后端真实状态。

## 不是凭据缺失的问题

- CSE filings 在本地缓存为空时会尝试刷新 TSX、TSXV 和 CSE 证券目录；若网络或 DNS 无法访问这些端点，来源会诚实地标记为不可用。这属于运行时外部端点问题，不应当当作空结果。
- `/api/coverage` 处理器捕获到覆盖数据构建异常时会返回 HTTP 500；表格里的“未覆盖”只是能力声明，两者需要分开排查。
- 系统 Python 若未安装 `xlrd` 会导入失败；项目已经在 `pyproject.toml` 声明该依赖，应该使用项目虚拟环境或先安装项目依赖。

## 已修复的测试错误

过去直接运行 `pytest` 会递归进入 `agents_sdk/runtime_runs`，多份同名测试文件造成大量 `import file mismatch` 收集错误。现在通过 `testpaths = ["tests"]` 只收集正式测试目录。这是测试编排问题，与外部 API 无关。
