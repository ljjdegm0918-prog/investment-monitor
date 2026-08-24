# 瑞士 Sponsored Foreign Shares 与 SIX 官方公告实施报告

日期：2026-08-25
分支：`ai功能测试`

## 结论

本批把瑞士免费官方覆盖从“SA/AA 股票和 ETF 目录 + EQS 披露”扩大为：

- SIX Swiss Shares（SA）
- SIX Foreign Shares（AA）
- SIX Sponsored Foreign Shares（SP）
- SIX ETF（ET/FU）
- SIX Exchange Regulation Official Notices（公开列表 + 详情）

瑞士仍评为 `partial`。原因不是 connector 不可用，而是免费公开范围仍不能证明包括历史退市、其他场所独有发行人、所有 ETF 专属公告和全部发行人财报/临时披露。

## 修改前后

| 项目 | 修改前 | 修改后 | 仍然缺少 | 状态 |
|---|---|---|---|---|
| Sponsored Foreign Shares | 未采集 | 纳入 SIX FQS 官方目录、每日原子刷新和身份映射 | 历史/退市 SP | 已实现 |
| SIX Official Notices | disabled 占位，无 connector | 公开 JSON 列表全分页、按 ISIN 匹配、详情交叉核验 | 不能替代所有发行人 Filing | 已实现 |
| 其他瑞士交易场所 | 笼统列为缺口 | 明确区分 issuer master 与交易路由，避免重复发行人 | 非 SIX 独有发行人主目录 | 部分改善 |
| 完整性判断 | SIX 目录健康可能被误读为全部瑞士覆盖 | cache 和报告明确 included/not covered；整体最高 `partial` | 跨官方系统长期对账 | 已改善 |

## 官方来源与请求合同

### 1. SIX Sponsored Foreign Shares

- 官方说明页：`https://www.six-group.com/en/market-data/shares/sponsored-foreign-shares.html`
- 官方公开 FQS：`https://www.six-group.com/fqs/ref.json`
- 查询范围：`PortalSegment=EQ*TitleSegment=SP`
- 强制字段：`ValorId`、`ISIN`、`ValorSymbol`、`ShortName`、`SecTypeCode`、`ListingSegment`、`TradingBaseCurrency`、`FirstTradingDate`
- 接受条件：`SecTypeCode=SS` 且 `ListingSegment=SP`，并通过身份、日期和币种格式校验。

SP 是外国主上市证券的 SIX 交易行。相同 ISIN 可能对应多个币种/Valor；缓存保留所有交易行，发行人身份映射只在名称、ISIN、证券类型完全一致时合并。

### 2. SIX Exchange Regulation Official Notices

- 官方页面：`https://www.six-group.com/en/market-data/news-tools/official-notices.html`
- 官方 RSS：`https://www.ser-ag.com/itf-data/official-notices/rss-en.xml`
- 公开列表：`https://www.ser-ag.com/sheldon/official_notices/v2/find.json`
- 公开详情：`https://www.ser-ag.com/sheldon/official_notices/v2/details/{noticeId}.json`

列表按日期、页码和页大小读取，先核对 `totalCount`，再从 `isin` 文本提取一个或多个合法 ISIN。只有命中请求证券时才读取详情。详情与列表对公告 ID、日期、类型、发行人和标题作严格交叉校验。

## 数据流和字段映射

```text
SIX FQS SA/AA/SP/ETF
        ↓ 四个 scope 全部成功、分页对账、源时间校验
瑞士 universe 原子缓存
        ↓ ticker / ISIN / Valor 身份映射
SIX Official Notices 日期全表
        ↓ 合法 ISIN 精确相交
官方 notice detail
        ↓ provenance + canonical ID + Zurich 时间
regulatory_filing
```

主要映射：

| 目标字段 | 官方字段/规则 |
|---|---|
| issuer identity | `ValorSymbol` + `ISIN` + `ValorId` |
| sponsored type | `SecTypeCode=SS`, `ListingSegment=SP` |
| official notice ID | `noticeId`，存为 `six-notice:{id}` |
| official notice number | 详情 `number` |
| published_at | `date` + `publishTime`，`Europe/Zurich` |
| issuer | `contact` |
| document type | `SIX Official Notice ({noticeType})` |
| official URL | SER 公告 permalink |
| retrieval URL | `find.json` 列表 URL + `details/{id}.json` |
| source tier | Tier 1，SIX Exchange Regulation |

## 失败保护

- SA、AA、SP、ETF 任一 scope 缺失、过小或失败时不覆盖旧缓存。
- FQS 分页状态、总数、页数、跨页重复、Valor 重复和源有效时间不一致均失败关闭。
- Official Notices 的 HTML/Loading、非 JSON、403、429、超时、空包结构变化、总数漂移、重复公告 ID、详情身份冲突均不能算成功。
- `isin` 为 `Part I` 等非证券标签时保留审计原文但不匹配；复合 ISIN 只匹配请求集合中的合法值。
- 完整列表成功且目标 ISIN 没有命中才返回 `empty`；未知 ticker/无 universe ISIN 返回 `unavailable`。

## 2026-08-25 实时只读抽样

SIX FQS 四个 scope 全部完成并写入临时缓存：

| 指标 | 数量 |
|---|---:|
| 总记录 | 3,096 |
| Swiss Shares scope | 224 |
| Foreign Shares scope | 36 |
| Sponsored Foreign Shares scope | 551 |
| ETF scope | 2,285 |
| 普通 equity | 250 |
| participation certificate | 9 |
| subscription right（独立类型，不作公司股票身份） | 1 |

源有效时间由 FQS 的 delayed metadata 得到，四个 scope 的窗口为 `2026-08-24T17:51:39.121000+00:00` 至 `2026-08-24T17:51:52.744000+00:00`，没有用本地采集时间冒充源时间。

Official Notices 对 `2026-08-18` 至 `2026-08-25` 的只读抽样完整核对 486 条列表记录；目标 Nestlé ISIN 在该窗口为 0 条。该零结果来自完成全表总数对账，而不是接口失败或漏页。
同一窗口另以实时列表中的 `CH1580929342` 做端到端命中抽样，成功读取并交叉核验
1 条详情（`noticeId=364576`），证明列表命中后的详情路径也可运行。

## 每日更新

- 瑞士 universe 已在现有 `daily_refresh` 路径中刷新；本批扩展后同一次任务会原子更新 SA、AA、SP、ETF。
- `six_official_notices` 已注册并在 settings 启用，随正常 Filing 日期窗口采集；connector 最大回看 30 天，按市场全表扫描一次，再按请求 ISIN 分发。
- 不需要付费 API key，也不需要登录、token 重放或浏览器自动化。

## 测试与验证

- 瑞士 connector/universe/dedupe 定向测试：43 passed。
- registry、settings、coverage、分页、pipeline、daily refresh、Web 相关回归：111 passed。
- 正式 `tests/` 全套：2,149 passed、2 skipped；另有 6 项 localhost
  mock-server 测试因沙箱禁止绑定端口而首次失败，在获准的本机隔离环境中重跑为
  6 passed。因此业务和正式测试合计 2,155 passed、2 skipped。
- 新增/修改核心 Python 文件 mypy：通过，无错误。
- `git diff --check`：提交前执行并要求通过。

离线 fixture 覆盖分页完成、总数漂移、跨页重复、页上限、详情身份错误、403、HTML/非 JSON、单 ISIN、复合 ISIN、非 ISIN 标签、SP 多币种身份和官方来源时间。

## 文件变更

- `src/investment_monitor/universe/ch_universe.py`
- `src/investment_monitor/sources/six_official_notices/__init__.py`
- `src/investment_monitor/sources/six_official_notices/client.py`
- `src/investment_monitor/sources/six_official_notices/connector.py`
- `src/investment_monitor/registry.py`
- `src/investment_monitor/dedupe.py`
- `src/investment_monitor/universe/coverage_report.py`
- `src/investment_monitor/__init__.py`
- `config/settings.yaml`
- `.env.example`
- `README.md`
- `docs/GLOBAL_MARKET_COVERAGE_STATUS_ZH.md`
- 本批提示词、实施报告及对应 tests/fixtures。

## 剩余缺口与建议优先级

1. **发行人 Filing 主链对账**：EQS 与 Official Notices 都不能单独证明覆盖所有 SIX 发行人财报和临时披露。下一步应做 30 天逐日数量/发行人抽样对账。
2. **历史和退市证券**：当前是活跃公开目录；需要官方历史清单或许可明确的历史产品，不能从当前快照推断。
3. **其他交易场所独有发行人**：先寻找官方、免费、可枚举的 issuer master；同一 SIX 证券的 MTF 路由只作 venue metadata，不复制 issuer。
4. **ETF 专属公告**：ETF 已有完整交易目录，但缺单独的官方公告主链；可按 ISIN 继续复用 Official Notices，同时研究基金发行人的正式文档源。
5. **Sponsored Foreign Shares 原市场公告**：SP 的瑞士交易目录已覆盖，但公司公告主来源通常在其原上市国；后续应以 ISIN/LEI 连接已有国家 connector，而不是将瑞士交易行当作瑞士发行人。
