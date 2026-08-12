# COORDINATION

## 冲突消解记录

**日期：** 2026-08-12  
**冲突：** `stockhead_au` 归类为 community，与 AU 新闻 yahoo/google 是否跨源 dedupe。  
**决议：** stockhead 保持 `source_type=community`；dedupe 走 `_community_key`（`article_slug`），**不**与 yahoo_au/google_news_au 的 `_news_key` 配对。HotCopper stub 仍独立。  
**证据：** `dedupe.py` `_community_key` 新增 `stockhead_au` 分支；`tests/test_stockhead_au.py` 不变。
