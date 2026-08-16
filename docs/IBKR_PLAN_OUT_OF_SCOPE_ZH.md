# IBKR 计划书范围外清单（ZH）

本文档冻结本项目**不做什么**，防止后续轨道把边界当缺口误修。更新于
2026-08-16（Phase 5 / Z 扫尾后）。

## 明确不做

1. **eux / emf**：Eurex 衍生品与欧洲共同基金不属于 `secType=STK` 股票类
   范围，不做 universe/披露/新闻接入；catalog 中保持
   `catalog_role=out_of_scope`。
2. **期货、期权、权证、结构化产品**：不建交易场所体系、不接数据。
3. **俄罗斯可交易**：MOEX 只保留只读研究目录（`ru_universe`），
   `trading_status=unavailable`；IBKR 当前不可开平仓且无定价，永不把 RU
   标成可交易 complete。
4. **CN 监管披露连接器**：`cn` 保持 catalog extra；中国 A 股经 HK Stock
   Connect venue 映射表达（`universe/stock_connect.py`），不新开一套 CN
   披露。
5. **付费/注册源冒充 LIVE**：禁止新注册账号；EODHD、Twelve Data、
   IBKR Web API、SIX Data、SGX DataLink、Refinitiv/LSEG、Data Hub 等
   付费/需 key 源不申请、不冒充免费 live。允许记录“免费不可用”边界。
6. **Playwright / 浏览器自动化**：本轨与后续默认禁止；侦察与采集只用
   stdlib urllib（页面 SPA 无法稳定自动化的，标 partial/stub）。
7. **ETF 发行人文件攻坚**：基金文件/份额变更/指数/分红公告不在零注册
   扫尾范围；`etf_disclosure` 诚实保持 unavailable，直到出现真正免费
   官方源。
8. **28 国 complete 吹嘘**：任何国家必须同时满足计划书 §8 的完整标准
   才能标 complete；当前所有 partial/stub 均按真实状态展示。

## 已完成轨道的边界（防止回退）

- Phase 0：28 国 / 87 venue 目录冻结，BATS/Chi-X/Cboe/Turquoise 只作
  venue，禁止注册成发行人披露连接器。
- Phase 1：`global_equity_reference` 第三方候选层，官方字段永远优先。
- Phase 4：CA/SG/SE/CH 主链与七国 ETF 完整性已按真实可达性锁边。
- Phase 5：俄罗斯只读、CN↔Connect 映射、ETF 披露骨架、conid 真写、
  季度对表工具。

## 一句话原则

> 接得上就接（官方免费优先）；接不上就诚实 partial/stub + 证据锁死；
> 不注册、不付费、不冒充、不把新闻当披露。
