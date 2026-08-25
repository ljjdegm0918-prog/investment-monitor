# 美国 OTC 覆盖补强执行提示词

你是一名证券监管数据连接器高级工程师。只修改美国 OTC 的 universe、官方公司行动 connector、注册/配置、去重、每日刷新、离线测试和对应文档；不得覆盖工作区已有改动。

## 目标与来源裁决

1. 使用 FINRA 官方公开 Query API 的 `otcSecurityMaster` 日期分区，补齐活跃 OTC Equity Security 范围。
2. 使用 FINRA 官方 `otcDailyList` 日期分区采集新增、删除、代码/名称变更、分红、拆股、破产和其他公司行动。
3. SEC `company_tickers_exchange.json` 只对 FINRA 已确认且 SEC exchange=`OTC` 的同 ticker 补 CIK；SEC EDGAR 继续负责有申报义务公司的监管文件。
4. 不抓取 OTC Markets 付费产品，不绕过登录/WAF，不把新闻或 FINRA 公司行动冒充财报。
5. FINRA Security Master 未提供 OTCQX/OTCQB/Pink tier 和非活跃历史，最终状态必须保持 `partial`。

## 工程验收

- 全量分页必须按 `record-total`、`record-limit`、`record-offset`、`record-max-limit` 对账；总数漂移、重复 symbol/row、缺页、触顶、非 JSON、403/429 均失败关闭。
- universe 原子写缓存，FINRA breadth 主来源失败不得覆盖旧缓存；每日刷新可用 `--market us`。
- Daily List 只查询已在缓存中验证为 OTC 的 US ticker，交易所上市 ticker 不发 HTTP。
- 每条公司行动保存 FINRA 身份、发布时间与 America/New_York 时区、原因/分类、old/new symbol、ex/record/payment date、金额/拆股字段、官方页面和实际 API URL。
- 增加脱敏 fixture，覆盖多页成功、总数漂移、重复页、页数上限、精确匹配、非 OTC 零请求、缓存损坏。
- 完成实时只读 smoke，报告实际分区日期、活跃证券总数、分页数、Daily List 样例；不得将 smoke 写成稳定测试依赖。

## 最终 Git 边界

仅暂存本工单明确修改/新增文件，排除所有既有未跟踪 MD/DOCX。定向测试、mypy、全套测试和 `git diff --check` 通过后提交 feature branch，推送并向 `ai功能测试` 发起 PR。
