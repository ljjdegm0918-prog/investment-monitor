# Phase 4 CXE/TRQ venue-only 收口（2026-08-16）

## 结论

`cxe`（Cboe Europe CXE/BXE）与 `trq`（Turquoise 泛欧 MTF）在本仓**只保留
routing/venue 身份**，没有、也不允许新增发行人披露连接器。发行人披露仍归
主上市国家市场处理。

## 代码证据

- `src/investment_monitor/registry.py`
  - `164: from .sources.cxe_news import GoogleCxeNewsConnector`
  - `166: from .sources.trq_news import GoogleTrqNewsConnector`
  - 注册表只注册 `GoogleCxeNewsConnector` / `GoogleTrqNewsConnector`
    （Google News RSS），无任何 filings/disclosure connector。
- `config/settings.yaml`
  - `google_news_cxe`：source_type `news`，enabled true
  - `google_news_trq`：source_type `news`，enabled true
  - 无 `cxe_disclosure` / `trq_disclosure` 条目。
- `universe/exchange_catalog.py` seed 的 `extra_entries`：
  - `CXE`：`catalog_role=venue_only`
  - `TRQ`：`catalog_role=venue_only`
  - 两者均不进 28 国分母。

## coverage_report

`coverage_report()` 只对 28 个核心国家输出覆盖行；CXE/TRQ 在目录
`extra_entries` 中展示 `venue_only`，Manage 看板不会把它们当国家/披露源。
