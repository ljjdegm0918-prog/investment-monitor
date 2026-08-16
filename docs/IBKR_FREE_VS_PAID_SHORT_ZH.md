# IBKR 接入 — 免费 / 付费短表（发钧哥）

- **代码 / 生产 tip：** `12fa0a7`（2026-08-16）
- **口径：** Phase 0–5 已交付并上线 ≠ 计划书 §8 各国 `complete`
- **图例：** ✅ 免费可用　💰 稳定源通常需付费　🚧 公开但反爬/SPA　➖ 不做

---

## 1. 能力层（短）

| 能力 | 免费 | 付费 | 现状 |
|---|---|---|---|
| 新闻 | ✅ Yahoo/Google | 终端级新闻 | 绝大多数国 LIVE |
| 美股披露 | ✅ SEC | — | LIVE |
| 多国披露 | ✅ 有则接公开 API/CSV | 💰 官方 OAM/商业包 | 约半数 LIVE；多国 stub |
| 股票宇宙 | ✅ 公开目录 | 💰 完整 reference | 约半数 LIVE；多国 stub |
| ETF 目录 | ✅ 少数（如德 Xetra） | 💰 完整 ETF 库 | 仅 DE LIVE |
| ETF 发行人文件 | 极少免 key | 💰 基金/交易所 API | **0 国 LIVE** |
| IBKR 身份 | ✅ secdef（要账号会话） | 行情订阅另议 | 适配器有；生产默认未开 |
| 第三方补洞 | ✅ OpenFIGI / EODHD 免费档 | 💰 付费档 | 已接，标 third_party |
| 期货/Eurex/欧基 | — | 💰 | ➖ 排除 |

---

## 2. 薄弱国（短）

| 国家 | 宇宙 | 披露 | 主因 |
|---|---|---|---|
| MX / IL / HU / AT | stub | stub | 🚧 为主；稳接口常 💰 |
| CA | partial | unavailable | SEDAR+ 🚧/💰；CSE/NEO 弱 |
| SG | stub | unavailable | 🚧；SGX 产品 💰 |
| CH | stub | partial | SIX 目录/Exfeed 常 💰 |
| SE | stub | LIVE | 宇宙 SPA 🚧 |
| NO / PT | LIVE | stub | 披露 🚧 |
| US | partial | LIVE | SEC tickers 官方 JSON（breadth-only） |
| JP | unavailable | LIVE | 全量目录无稳定免 key 静态文件（Z0 复验） |

\*以 `coverage_report` 为准。

---

## 3. 数字一览

| 指标（28 国） | 数量 |
|---|---|
| 宇宙 LIVE | 14 |
| 披露 LIVE | 14 |
| ETF 宇宙 LIVE | 1（DE） |
| ETF 披露 LIVE | **0** |
| §8 complete | **≈ 0** |

---

## 4. 给钧哥的三句话

1. **施工已收口并上生产**（含边角 Phase 5）。  
2. **缺口不全是技术**：很多是无稳定免 key 官方机接口，或要买数据。  
3. **不花钱还能抠约 2–3 周**；买不到「28 国 complete」。若要变厚，请单独立项询价（优先看 CA/CH/IL/SG 官方包，或 ETF 文件类数据商）。

---

*文件用途：微信/邮件转发；详细长表可再要。*
