# 美国 OTC 官方覆盖补强报告

日期：2026-08-25
目标分支：`ai功能测试`

## 1. 修改前审计

| 模块 | 修改前 | 主要缺口 |
|---|---|---|
| US universe | Nasdaq Trader `nasdaqlisted` / `otherlisted` | OTC 证券全部缺失，SEC ticker JSON 只富化已有证券 |
| 官方 Filing | SEC EDGAR | 能覆盖 SEC-reporting OTC 公司，但不能枚举整个活跃 OTC 范围 |
| OTC 公司行动 | 无 connector | 新增/删除、代码变更、分红、拆股等没有每日官方扫描 |
| 每日运维 | CH/JP universe refresh | US universe 无统一日更入口 |

## 2. 来源和实现

### 2.1 FINRA OTC Security Master

- 官方 partition：`/partitions/group/otcMarket/name/otcSecurityMaster`
- 官方 data：`/data/group/otcMarket/name/otcSecurityMaster`
- 每日选择最新 `asOfDate`，按 `issueSymbolIdentifier` 排序读取全量。
- 每页严格核对 FINRA 返回的 total/limit/offset/max-limit；任何断页、漂移、重复或结构变化均拒绝写缓存。
- Nasdaq Trader 交易所目录、FINRA 活跃 OTC master 和可选 SEC CIK enrichment 原子合并；SEC market 不一致则失败关闭。

### 2.2 FINRA OTC Daily List

- 官方 partition：`/partitions/group/otcMarket/name/otcDailyList`
- 官方 data：`/data/group/otcMarket/name/otcDailyList`
- 按请求日期选择全部可用分区并完整分页；保存 reason、old/new symbol、市场/财务状态、ex/record/payment date、现金金额和 split rate。
- 连接器只处理 US universe 已确认的 OTC ticker；输出 Tier 1 FINRA 公司行动，使用原始行确定性哈希作为身份。
- 这是公司行动补充，不是财报/年度报告替代品；SEC accession 与 FINRA 事件各保留机构原生身份。

## 3. 失败保护与覆盖边界

- 403/429、超时、非 JSON、partition envelope 变化、缺少分页头、总数漂移、重复行和页数触顶都不能标记成功。
- breadth refresh 失败不会覆盖最后一份有效缓存；损坏、计数不一致或无有效日期的缓存会被拒绝加载。
- 没有 OTC ticker 的请求不会访问 FINRA Daily List。
- 未覆盖：OTCQX/OTCQB/Pink tier、非活跃/历史 security master、OTC Markets 付费数据、非 SEC-reporting 公司完整财报。因此美国 universe 仍为 `partial`，没有冒充 complete。

## 4. 数据流

`Nasdaq Trader listed issues + FINRA active OTC master → US cache → ticker identity → FINRA Daily List daily scan`；`SEC ticker JSON → exact OTC CIK enrichment`；`SEC EDGAR → SEC-reporting issuer filings`。

## 5. 运维

`investment-monitor-refresh-universes --market us` 每日重建 US breadth cache。配置提供超时、有限重试和速率限制；Daily List connector 由现有 source pipeline 按日期执行。

## 6. 2026-08-25 实时只读抽样

- 最新 Security Master 分区：`2026-08-24`。
- `record-total=17,978`，当前实现按 5,000 条每页完整读取 4 页；排序首尾代码为 `AAAIF` / `ZZZOF`。
- 端到端原子合并共 31,114 条：交易所上市 13,136、活跃 OTC 17,978；SEC CIK enrichment 9,614，其中 OTC 2,483。
- OTC 类型量化：普通股票 14,059、DR 2,242、ETF 666、unit 318、preferred 292、warrant 200、REIT 61、right 17、其他 123。
- 端到端合并发现 27 个 SEC/FINRA 跨市场 ticker 冲突（如 SEC 的 `AIXN` 仍关联非 OTC exchange，而 FINRA 当前列为活跃 OTC）。实现拒绝附加这些 SEC CIK、记录 `sec_market_conflicts_skipped`，但不让单个冲突抹掉其余官方 FINRA 目录；另有 21 个 SEC OTC ticker 不在最新 FINRA active snapshot，亦不擅自补入。
- `2026-08-24` Daily List 共 42 条；抽样包含 `ELMGF` Conversion/Reclassification、`LRBI` Cash Dividend Regular、`FRESY` Addition、`UCLQF` 与 `ANSLY` Cash Dividend Regular。
- `LRBI` 样例保存现金金额 `0.63`、record date `2026-08-19`、payment date `2026-09-16`；FINRA Addition 行实际可能把当前代码放在 `oldSymbolCode`，实现因此同时匹配 old/new symbol，没有假定字段名称等同业务方向。

## 7. 结论

本次把美国 OTC 从“SEC 恰好能识别的少数公司”提升为“FINRA 活跃 OTC 证券范围 + 每日官方公司行动 + SEC 文件补充”。这显著提高每日扫描可用性，但基于公开免费合同，仍诚实保留分层、历史和非 SEC 文件缺口。

## 8. 文件与测试

- 新增：`universe/finra_otc.py`、`sources/finra_otc_daily_list/`、FINRA 离线 fixtures、`test_finra_otc.py`、执行提示词和本报告。
- 修改：US universe、registry/settings、dedupe、Web source labels/name fallback、daily refresh、coverage report、README、`.env.example` 及相应回归测试。
- 定向验收：71 passed；4 个核心模块 mypy clean；`git diff --check` clean。
- 基于远端最新 `ai功能测试` 变基后的全仓验收：`2203 passed, 2 skipped`。目标分支新加入的登录测试需要其已声明依赖 `argon2-cffi`；安装项目依赖并允许本地测试 server 后全部通过，与 OTC 代码无失败关联。
