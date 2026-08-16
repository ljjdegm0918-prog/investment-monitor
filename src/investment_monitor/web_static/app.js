"use strict";

const SUPPORTED_LANGS = ["en", "zh-CN"];
const LANG_STORAGE_KEY = "im-lang";

const MESSAGES = {
  en: {
    "nav.daily_info": "Daily information",
    "nav.lists_sources": "Lists & sources",
    "skip.content": "Skip to content",
    "loading.workspace": "Loading workspace…",
    "lang.switch": "中文",
    "daily.eyebrow": "DAILY REPORTS",
    "daily.subtitle": "One report per Asia/Shanghai calendar day, limited to filings, news, and community updates.",
    "daily.print": "Print / Save PDF",
    "daily.from": "From",
    "daily.to": "To",
    "daily.list": "List",
    "daily.all_lists": "All lists",
    "daily.generate": "Generate reports",
    "daily.loading": "Loading information…",
    "daily.start_before_end": "The start date must be on or before the end date.",
    "daily.no_info": "No information for this date",
    "daily.no_info_desc": "No filing, news, or community updates were published in the selected day.",
    "daily.range_summary": "Range summary",
    "daily.updates": "updates",
    "daily.daily_report_one": "daily report",
    "daily.daily_report_many": "daily reports",
    "daily.day_report": "DAILY REPORT",
    "daily.update_counts": "Update counts",
    "daily.no_updates": "No updates for this day.",
    "common.also_seen_on": "Also seen on",
    "common.unavailable": "Unavailable",
    "common.update_one": "update",
    "common.update_many": "updates",
    "common.request_failed": "Request failed",
    "common.workspace_failed": "Workspace request failed",
    "common.request_failed_status": "Request failed ({status})",
    "common.asia_shanghai": "Asia/Shanghai",
    "common.none_recorded": "None recorded",
    "cat.filings": "Filings",
    "cat.news": "News",
    "cat.community": "Community",
    "cat.official_filings": "Official filings",
    "manage.eyebrow": "MANAGEMENT",
    "manage.heading": "Lists, companies & sources",
    "manage.subtitle": "Organize monitored companies and review collection health.",
    "manage.lists": "Lists",
    "manage.lists_desc": "Create, rename, delete, and select a list.",
    "manage.new_list_name": "New list name",
    "manage.create": "Create",
    "manage.companies": "Companies",
    "manage.search_by": "Search by company name or ticker",
    "manage.market": "Market",
    "manage.search": "Search",
    "manage.add_ticker": "Add ticker",
    "manage.manual_add": "Ticker input",
    "manage.csv_add": "CSV / table import",
    "manage.csv_desc": "Paste spreadsheet rows or upload a CSV/TSV file. Each row can use a different market and list.",
    "manage.csv_rows": "CSV or spreadsheet rows",
    "manage.csv_file": "Or choose a CSV/TSV file",
    "manage.csv_import": "Import rows",
    "manage.csv_help": "Required columns: ticker, market, list. List accepts an existing list name or slug. Up to 500 rows.",
    "manage.csv_done": "CSV import completed.",
    "manage.csv_added": "Added",
    "manage.csv_existing": "Already present",
    "manage.csv_failed": "Failed",
    "manage.csv_row": "Row {row}",
    "manage.add_placeholder": "e.g. AAPL@US, 0700@HK, RY@TO",
    "manage.add_help": "Add one or more symbols, separated by commas, spaces, semicolons, or new lines. A market suffix selects that market: use @ (AAPL@US, 0700@HK) or a dot (AAPL.US, 0700.HK). A recognized suffix (for example .US, .HK, .TO, .AX, or the same code after @) selects the market; symbols without one are treated as US. A dot inside a ticker (for example BRK.B) is never treated as a suffix.",
    "manage.added_multi": "Added: {items}",
    "manage.manual_add": "Ticker input",
    "manage.csv_add": "CSV / table import",
    "manage.csv_desc": "Paste spreadsheet rows or upload a CSV/TSV file. Each row can use a different market and list.",
    "manage.csv_rows": "CSV or spreadsheet rows",
    "manage.csv_file": "Or choose a CSV/TSV file",
    "manage.csv_import": "Import rows",
    "manage.csv_help": "Required columns: ticker, market, list. List accepts an existing list name or slug. Up to 500 rows.",
    "manage.csv_done": "CSV import completed.",
    "manage.csv_added": "Added",
    "manage.csv_existing": "Already present",
    "manage.csv_failed": "Failed",
    "manage.csv_row": "Row {row}",
    "manage.information_sources": "Information sources",
    "manage.sources_desc": "Configured connectors, coverage, latest run, and failure summary.",
    "manage.loading_sources": "Loading sources…",
    "manage.companies_count": "{count} companies",
    "manage.rename": "Rename",
    "manage.delete": "Delete",
    "manage.create_list_first": "Create a list to start monitoring companies.",
    "manage.list_name": "List name",
    "manage.list_created": "List created.",
    "manage.list_renamed": "List renamed.",
    "manage.list_deleted": "List deleted.",
    "manage.delete_confirm": "Delete “{name}”? Companies in other lists and stored information will be preserved.",
    "manage.company": "Company",
    "manage.ticker": "Ticker",
    "manage.exchange": "Exchange",
    "manage.region": "Region",
    "manage.remove": "Remove",
    "manage.no_companies": "No companies in this list.",
    "manage.create_or_select_first": "Create or select a list first.",
    "manage.non_us_markets": "Non-US markets: use Add ticker (SEC search is US-only).",
    "manage.searching_candidates": "Searching candidates…",
    "manage.confirm_add": "Confirm & add",
    "manage.no_matching_candidates": "No matching official candidates.",
    "manage.search_no_results": "Search returned no results",
    "manage.enter_ticker_first": "Enter a ticker first.",
    "manage.added_market": "{tickers} added ({market}).",
    "manage.added": "{ticker} added.",
    "manage.removed": "{ticker} removed from this list.",
    "manage.coverage_not_provided": "Coverage not provided",
    "manage.enabled": "Enabled",
    "manage.yes": "Yes",
    "manage.no": "No",
    "manage.latest_success": "Latest success",
    "manage.latest_attempt": "Latest attempt",
    "manage.none_recorded": "None recorded",
    "manage.failure_details": "Failure details",
    "manage.adding_company": "Adding…",
    "manage.added_collecting_background": "{items} added. Collecting in background…",
    "manage.collection_complete": "Collection complete.",
    "manage.collection_partial": "Collection partial. {error}",
    "manage.collection_failed": "Collection failed. {error}",
    "status.connected": "Connected",
    "status.data_stale": "Data stale",
    "status.not_connected": "Not connected",
    "status.failed": "Failed",
    "status.waiting_for_data": "Waiting for data",
    "region.us": "United States",
    "region.jp": "Japan",
    "region.hk": "Hong Kong",
    "region.cn": "China",
    "region.kr": "Korea",
    "region.uk": "United Kingdom",
    "region.tw": "Taiwan",
    "region.ca": "Canada",
    "region.au": "Australia",
    "region.be": "Belgium",
    "region.fr": "France",
    "region.de": "Germany",
    "region.nl": "Netherlands",
    "region.it": "Italy",
    "region.es": "Spain",
    "region.sg": "Singapore",
    "region.ch": "Switzerland",
    "region.pl": "Poland",
    "region.se": "Sweden",
    "region.ee": "Estonia",
    "region.lv": "Latvia",
    "region.lt": "Lithuania",
    "region.no": "Norway",
    "region.pt": "Portugal",
    "region.at": "Austria",
    "region.in": "India",
    "region.aq": "Aquis (AQSE)",
    "region.cxe": "Cboe Europe (CXE)",
    "region.emf": "Europe (Funds)",
    "region.trq": "Turquoise (TRQ)",
    "region.eux": "Europe (Eurex)",
    "nav.research": "Research",
    "research.eyebrow": "RESEARCH ASSISTANT",
    "research.heading": "Research",
    "research.print_pdf": "Print / Save PDF",
    "research.print_title": "Research card",
    "research.subtitle": "Evidence-backed summaries of the companies you already track in Holdings, Planned, or Watchlist.",
    "research.disclaimer": "Research assistance only. This is not investment advice.",
    "research.data_send": "Generating a card sends this company’s selected public evidence to your configured model provider.",
    "research.list": "List",
    "research.all_lists": "All lists",
    "research.from": "From",
    "research.to": "To",
    "research.apply": "Apply",
    "research.selected_range": "Selected date range",
    "research.evidence_in_range": "Evidence in selected range",
    "research.evidence_sent": "Evidence sent to model",
    "research.no_card_for_range": "No research card for this range",
    "research.insufficient_in_range": "Insufficient evidence in this date range",
    "research.card_scope": "This card was generated for",
    "research.range_new_evidence": "Current range has new evidence available",
    "research.start_after_end": "Range start must not be after range end",
    "research.model_label": "Model",
    "research.model_enabled": "enabled",
    "research.model_disabled": "not configured",
    "research.generate": "Generate research card",
    "research.view": "View latest card",
    "research.regenerate": "Regenerate",
    "research.new_evidence": "New evidence available",
    "research.evidence_coverage": "Evidence coverage",
    "research.total_items": "items",
    "research.filings": "Filings",
    "research.news": "News",
    "research.community": "Community",
    "research.latest_evidence": "Latest evidence",
    "research.card_status": "Card status",
    "research.last_generated": "Last generated",
    "research.no_companies": "No companies in this list.",
    "research.loading": "Loading research…",
    "research.recent_changes": "Recent changes",
    "research.main_risks": "Main risks",
    "research.volatility_drivers": "Catalysts and volatility drivers",
    "research.questions": "What to investigate next",
    "research.evidence": "Evidence",
    "research.limitations": "Coverage limitations",
    "research.insufficient_evidence": "Insufficient evidence",
    "research.model_not_configured": "Model not configured",
    "research.generation_failed": "Generation failed",
    "research.generating": "Generating…",
    "research.generating_in_background": "Generation is still running in the background; refresh the page later to see the result.",
    "research.error.invalid_response": "The model returned an invalid response. Try regenerating.",
    "research.error.upstream_timeout": "The model request timed out.",
    "research.error.upstream_network": "Could not reach the model provider.",
    "research.error.upstream_auth": "The model API key was rejected.",
    "research.error.upstream_rate_limited": "The model provider rate limit was reached.",
    "research.error.upstream_server": "The model provider returned an error.",
    "research.error.internal": "An internal error occurred.",
    "research.error.request_too_large": "The request was too large.",
    "research.error.response_too_large": "The model response was too large.",
    "research.error.range_too_large": "The selected date range contains too much evidence to generate a research card without omitting items. Please choose a shorter date range and try again.",
    "research.no_card": "No card generated yet.",
    "research.signals": "Signals to watch",
    "research.claim.direct_disclosure_fact": "Disclosure fact",
    "research.claim.reported_news": "Reported news",
    "research.claim.community_viewpoint": "Community viewpoint",
    "research.claim.cautious_inference": "Cautious inference",
    "research.strength.high": "High",
    "research.strength.medium": "Medium",
    "research.strength.low": "Low",
    "status.not_generated": "Not generated",
    "status.ready": "Ready",
    "status.generating": "Generating",
    "status.cached": "Cached",
    "status.stale": "Stale",
  },
  "zh-CN": {
    "nav.daily_info": "每日信息",
    "nav.lists_sources": "列表与来源",
    "skip.content": "跳到内容",
    "loading.workspace": "正在加载工作区…",
    "lang.switch": "English",
    "daily.eyebrow": "每日报告",
    "daily.subtitle": "每个上海自然日一份报告，仅限申报、新闻和社区更新。",
    "daily.print": "打印 / 保存 PDF",
    "daily.from": "从",
    "daily.to": "到",
    "daily.list": "列表",
    "daily.all_lists": "全部列表",
    "daily.generate": "生成报告",
    "daily.loading": "正在加载信息…",
    "daily.start_before_end": "开始日期必须早于或等于结束日期。",
    "daily.no_info": "此日期没有信息",
    "daily.no_info_desc": "所选当天没有发布申报、新闻或社区更新。",
    "daily.range_summary": "范围摘要",
    "daily.updates": "更新",
    "daily.daily_report_one": "日报",
    "daily.daily_report_many": "日报",
    "daily.day_report": "每日报告",
    "daily.update_counts": "更新计数",
    "daily.no_updates": "当天没有更新。",
    "common.also_seen_on": "也见于",
    "common.unavailable": "不可用",
    "common.update_one": "更新",
    "common.update_many": "更新",
    "common.request_failed": "请求失败",
    "common.workspace_failed": "工作区请求失败",
    "common.request_failed_status": "请求失败（{status}）",
    "common.asia_shanghai": "上海时间",
    "common.none_recorded": "无记录",
    "cat.filings": "申报",
    "cat.news": "新闻",
    "cat.community": "社区",
    "cat.official_filings": "官方披露",
    "manage.eyebrow": "管理",
    "manage.heading": "列表、公司与来源",
    "manage.subtitle": "整理监控的公司并查看采集健康状态。",
    "manage.lists": "列表",
    "manage.lists_desc": "创建、重命名、删除和选择列表。",
    "manage.new_list_name": "新列表名称",
    "manage.create": "创建",
    "manage.companies": "公司",
    "manage.search_by": "按公司名称或代码搜索",
    "manage.market": "市场",
    "manage.search": "搜索",
    "manage.add_ticker": "添加代码",
    "manage.manual_add": "代码输入",
    "manage.csv_add": "CSV / 表格导入",
    "manage.csv_desc": "可粘贴表格行或上传 CSV/TSV 文件；每一行可指定不同市场和列表。",
    "manage.csv_rows": "CSV 或表格内容",
    "manage.csv_file": "或者选择 CSV/TSV 文件",
    "manage.csv_import": "导入表格",
    "manage.csv_help": "必需列：ticker、market、list。list 可填写现有列表名称或 slug，最多 500 行。",
    "manage.csv_done": "CSV 导入完成。",
    "manage.csv_added": "已添加",
    "manage.csv_existing": "已存在",
    "manage.csv_failed": "失败",
    "manage.csv_row": "第 {row} 行",
    "manage.add_placeholder": "例如：AAPL@US、0700@HK、RY@TO",
    "manage.add_help": "可一次输入多个“股票代码@市场/交易所”或“股票代码.市场/交易所”，用逗号、空格、分号或换行分隔。@ 格式（如 0700@HK）不会与代码本身冲突，更推荐；. 格式（如 0700.HK）也支持。可识别的后缀（如 .US、.HK、.TO、.AX，或 @ 后的相同代码）会指定对应市场；没有后缀的代码默认视为美股（US）。代码本身含点（如 BRK.B）不会被误判为后缀。",
    "manage.added_multi": "已添加：{items}",
    "manage.manual_add": "代码输入",
    "manage.csv_add": "CSV / 表格导入",
    "manage.csv_desc": "可粘贴表格行或上传 CSV/TSV 文件；每一行可指定不同市场和列表。",
    "manage.csv_rows": "CSV 或表格内容",
    "manage.csv_file": "或者选择 CSV/TSV 文件",
    "manage.csv_import": "导入表格",
    "manage.csv_help": "必需列：ticker、market、list。list 可填写现有列表名称或 slug，最多 500 行。",
    "manage.csv_done": "CSV 导入完成。",
    "manage.csv_added": "已添加",
    "manage.csv_existing": "已存在",
    "manage.csv_failed": "失败",
    "manage.csv_row": "第 {row} 行",
    "manage.information_sources": "信息来源",
    "manage.sources_desc": "已配置连接器、覆盖范围、最近运行和失败摘要。",
    "manage.loading_sources": "正在加载来源…",
    "manage.companies_count": "{count} 家公司",
    "manage.rename": "重命名",
    "manage.delete": "删除",
    "manage.create_list_first": "创建列表以开始监控公司。",
    "manage.list_name": "列表名称",
    "manage.list_created": "列表已创建。",
    "manage.list_renamed": "列表已重命名。",
    "manage.list_deleted": "列表已删除。",
    "manage.delete_confirm": "删除“{name}”？其他列表中的公司和已存储的信息将被保留。",
    "manage.company": "公司",
    "manage.ticker": "代码",
    "manage.exchange": "交易所",
    "manage.region": "地区",
    "manage.remove": "移除",
    "manage.no_companies": "此列表中没有公司。",
    "manage.create_or_select_first": "请先创建或选择列表。",
    "manage.non_us_markets": "非美国市场：请使用“添加代码”（SEC 搜索仅限美国）。",
    "manage.searching_candidates": "正在搜索候选项…",
    "manage.confirm_add": "确认并添加",
    "manage.no_matching_candidates": "没有匹配的官方候选项。",
    "manage.search_no_results": "搜索无结果",
    "manage.enter_ticker_first": "请先输入代码。",
    "manage.added_market": "{tickers} 已添加（{market}）。",
    "manage.added": "{ticker} 已添加。",
    "manage.removed": "{ticker} 已从此列表移除。",
    "manage.coverage_not_provided": "未提供覆盖范围",
    "manage.enabled": "已启用",
    "manage.yes": "是",
    "manage.no": "否",
    "manage.latest_success": "最近成功",
    "manage.latest_attempt": "最近尝试",
    "manage.none_recorded": "无记录",
    "manage.failure_details": "失败详情",
    "manage.adding_company": "正在添加…",
    "manage.added_collecting_background": "{items} 已添加，正在后台采集…",
    "manage.collection_complete": "采集完成。",
    "manage.collection_partial": "采集部分完成。{error}",
    "manage.collection_failed": "采集失败。{error}",
    "status.connected": "已连接",
    "status.data_stale": "数据过期",
    "status.not_connected": "未连接",
    "status.failed": "失败",
    "status.waiting_for_data": "等待数据",
    "region.us": "美国",
    "region.jp": "日本",
    "region.hk": "香港",
    "region.cn": "中国",
    "region.kr": "韩国",
    "region.uk": "英国",
    "region.tw": "台湾",
    "region.ca": "加拿大",
    "region.au": "澳大利亚",
    "region.be": "比利时",
    "region.fr": "法国",
    "region.de": "德国",
    "region.nl": "荷兰",
    "region.it": "意大利",
    "region.es": "西班牙",
    "region.sg": "新加坡",
    "region.ch": "瑞士",
    "region.pl": "波兰",
    "region.se": "瑞典",
    "region.ee": "爱沙尼亚",
    "region.lv": "拉脱维亚",
    "region.lt": "立陶宛",
    "region.no": "挪威",
    "region.pt": "葡萄牙",
    "region.at": "奥地利",
    "region.in": "印度",
    "region.aq": "Aquis (AQSE)",
    "region.cxe": "Cboe Europe (CXE)",
    "region.emf": "欧洲（基金）",
    "region.trq": "Turquoise (TRQ)",
    "region.eux": "欧洲（Eurex）",
    "nav.research": "研究",
    "research.eyebrow": "研究助手",
    "research.heading": "研究",
    "research.print_pdf": "打印 / 保存 PDF",
    "research.print_title": "研究卡",
    "research.subtitle": "基于证据，梳理你已在持仓、计划或关注列表中的公司。",
    "research.disclaimer": "仅供研究辅助，不构成投资建议。",
    "research.data_send": "生成研究卡会把该公司的选定公开证据发送给你配置的模型服务。",
    "research.list": "列表",
    "research.all_lists": "所有列表",
    "research.from": "从",
    "research.to": "到",
    "research.apply": "应用",
    "research.selected_range": "所选日期范围",
    "research.evidence_in_range": "所选范围内证据",
    "research.evidence_sent": "已发送给模型的证据",
    "research.no_card_for_range": "此日期范围尚未生成研究卡",
    "research.insufficient_in_range": "此日期范围内证据不足",
    "research.card_scope": "此研究卡生成所用范围为",
    "research.range_new_evidence": "当前范围有新证据可更新",
    "research.start_after_end": "开始日期不能晚于结束日期",
    "research.model_label": "模型",
    "research.model_enabled": "已启用",
    "research.model_disabled": "未配置",
    "research.generate": "生成研究卡",
    "research.view": "查看最新研究卡",
    "research.regenerate": "重新生成",
    "research.new_evidence": "有新证据可更新",
    "research.evidence_coverage": "证据覆盖情况",
    "research.total_items": "条",
    "research.filings": "申报",
    "research.news": "新闻",
    "research.community": "社区",
    "research.latest_evidence": "最近证据",
    "research.card_status": "研究卡状态",
    "research.last_generated": "最近生成",
    "research.no_companies": "此列表中没有公司。",
    "research.loading": "正在加载研究…",
    "research.recent_changes": "近期需要理解的变化",
    "research.main_risks": "主要风险",
    "research.volatility_drivers": "主要波动因素",
    "research.questions": "待验证问题",
    "research.evidence": "证据",
    "research.limitations": "覆盖局限",
    "research.insufficient_evidence": "证据不足",
    "research.model_not_configured": "分析模型未配置",
    "research.generation_failed": "生成失败",
    "research.generating": "生成中…",
    "research.generating_in_background": "生成仍在后台进行，稍后刷新页面可查看结果。",
    "research.error.invalid_response": "模型返回了无效结果，请尝试重新生成。",
    "research.error.upstream_timeout": "模型请求超时。",
    "research.error.upstream_network": "无法连接模型服务。",
    "research.error.upstream_auth": "模型 API key 被拒绝。",
    "research.error.upstream_rate_limited": "已达到模型服务速率限制。",
    "research.error.upstream_server": "模型服务返回错误。",
    "research.error.internal": "发生内部错误。",
    "research.error.request_too_large": "请求过大。",
    "research.error.response_too_large": "模型响应过大。",
    "research.error.range_too_large": "所选日期范围内的资料过多，无法在不遗漏资料的情况下生成研究卡。请缩短日期范围后重试。",
    "research.no_card": "尚未生成研究卡。",
    "research.signals": "需要关注的信号",
    "research.claim.direct_disclosure_fact": "披露事实",
    "research.claim.reported_news": "新闻报道",
    "research.claim.community_viewpoint": "社区观点",
    "research.claim.cautious_inference": "谨慎推断",
    "research.strength.high": "高",
    "research.strength.medium": "中",
    "research.strength.low": "低",
    "status.not_generated": "未生成",
    "status.ready": "可生成",
    "status.generating": "生成中",
    "status.cached": "已缓存",
    "status.stale": "有更新",
  },
};

let lang = detectLang();

function detectLang() {
  const param = new URLSearchParams(location.search).get("lang");
  if (SUPPORTED_LANGS.includes(param)) return param;
  try {
    const stored = localStorage.getItem(LANG_STORAGE_KEY);
    if (SUPPORTED_LANGS.includes(stored)) return stored;
  } catch (_) { /* localStorage unavailable */ }
  return "en";
}

function t(key, params) {
  const table = MESSAGES[lang] || MESSAGES.en;
  let text = table[key] ?? MESSAGES.en[key] ?? key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

function localeFor() {
  return lang === "zh-CN" ? "zh-CN" : "en-US";
}

function toggleLang() {
  const next = lang === "en" ? "zh-CN" : "en";
  try { localStorage.setItem(LANG_STORAGE_KEY, next); } catch (_) { /* ignore */ }
  const params = new URLSearchParams(location.search);
  params.set("lang", next);
  location.href = `${location.pathname}?${params}`;
}

function withLang(query) {
  const next = new URLSearchParams(query);
  if (lang !== "en") next.set("lang", lang);
  return next;
}

function applyStaticLabels() {
  document.documentElement.lang = lang;
  const dailyNav = document.querySelector('[data-nav="today"]');
  if (dailyNav) dailyNav.textContent = t("nav.daily_info");
  const manageNav = document.querySelector('[data-nav="manage"]');
  if (manageNav) manageNav.textContent = t("nav.lists_sources");
  const researchNav = document.querySelector('[data-nav="research"]');
  if (researchNav) researchNav.textContent = t("nav.research");
  const skip = document.querySelector(".skip-link");
  if (skip) skip.textContent = t("skip.content");
  const initialLoading = document.querySelector("#page .loading");
  if (initialLoading) initialLoading.textContent = t("loading.workspace");
  const header = document.querySelector(".site-header nav");
  if (header && !document.getElementById("lang-toggle")) {
    const button = document.createElement("button");
    button.id = "lang-toggle";
    button.className = "lang-toggle";
    button.type = "button";
    button.setAttribute("aria-label", "Switch language");
    button.textContent = t("lang.switch");
    button.addEventListener("click", toggleLang);
    header.appendChild(button);
  }
}

const state = { bootstrap: null, selectedList: "" };
document.addEventListener("DOMContentLoaded", init);

// Printing must include the full evidence list, so unfold every <details>
// before the browser snapshots the page for print / save-as-PDF. The native
// print button never re-queries the server or alters card data.
if (typeof window !== "undefined") {
  window.addEventListener("beforeprint", () => {
    document.querySelectorAll(".evidence-list").forEach(details => details.setAttribute("open", ""));
  });
}

async function init() {
  applyStaticLabels();
  const view = document.body.dataset.view === "manage" ? "manage"
    : document.body.dataset.view === "research" ? "research" : "today";
  document.querySelector(`[data-nav="${view}"]`)?.classList.add("active");
  try {
    state.bootstrap = await api(`/api/bootstrap${location.search}`);
    state.selectedList = new URLSearchParams(location.search).get("list") || state.bootstrap.lists[0]?.slug || "";
    if (view === "manage") await renderManage();
    else if (view === "research") await renderResearch();
    else await renderDaily();
  } catch (error) { renderFatal(error); }
}

async function renderDaily() {
  const params = new URLSearchParams(location.search);
  const legacyDate = params.get("date");
  const endDate = params.get("end_date") || legacyDate || state.bootstrap.report_selected_date;
  const startDate = params.get("start_date") || legacyDate || endDate;
  const selectedList = params.get("list") || "";
  document.getElementById("page").innerHTML = `
    <section class="daily-head">
      <div><p class="eyebrow">${t("daily.eyebrow")}</p><h1>${formatRange(startDate, endDate)}</h1><p>${t("daily.subtitle")}</p></div>
      <div class="daily-actions"><button class="button" id="print-page" type="button">${t("daily.print")}</button></div>
    </section>
    <form class="toolbar range-toolbar" id="daily-filter">
      <label>${t("daily.from")}<input type="date" id="daily-start-date" value="${escAttr(startDate)}" required></label>
      <label>${t("daily.to")}<input type="date" id="daily-end-date" value="${escAttr(endDate)}" required></label>
      <label>${t("daily.list")}<select id="daily-list"><option value="">${t("daily.all_lists")}</option>${listOptions(selectedList)}</select></label>
      <button class="button primary" type="submit">${t("daily.generate")}</button>
    </form>
    <div id="daily-content"><p class="loading">${t("daily.loading")}</p></div>`;
  document.getElementById("print-page").addEventListener("click", () => window.print());
  document.getElementById("daily-filter").addEventListener("submit", event => {
    event.preventDefault();
    const start = document.getElementById("daily-start-date").value;
    const end = document.getElementById("daily-end-date").value;
    if (start > end) { toast(t("daily.start_before_end"), true); return; }
    const next = withLang(new URLSearchParams({start_date: start, end_date: end}));
    const list = document.getElementById("daily-list").value;
    if (list) next.set("list", list);
    location.href = `/today?${next}`;
  });
  try {
    const query = withLang(new URLSearchParams({start_date: startDate, end_date: endDate}));
    if (selectedList) query.set("list", selectedList);
    const data = await api(`/api/daily-range?${query}`);
    document.getElementById("daily-content").innerHTML = dailyContent(data);
  } catch (error) {
    document.getElementById("daily-content").innerHTML = errorState(t("common.request_failed"), error.message);
  }
}

function dailyContent(data) {
  const days = data.days || [data];
  const total = data.item_count ?? days.reduce((sum, day) => sum + day.item_count, 0);
  const perf = data.performance;
  const perfBanner = perf?.warnings?.length
    ? `<aside class="range-performance-warn" role="status">${perf.warnings.map(w => `<p>${esc(w)}</p>`).join("")}</aside>`
    : "";
  if (!total && days.length === 1) return `${perfBanner}<div class="empty"><h2>${t("daily.no_info")}</h2><p>${t("daily.no_info_desc")}</p></div>`;
  const reportLabel = days.length === 1 ? t("daily.daily_report_one") : t("daily.daily_report_many");
  return `${perfBanner}<section class="range-summary" aria-label="${t("daily.range_summary")}"><div><strong>${total}</strong><span>${t("daily.updates")}</span></div><p>${days.length} ${reportLabel} · ${t("common.asia_shanghai")}</p></section>
    <div class="daily-range">${days.map(day => dailyDay(day)).join("")}</div>`;
}

function dailyDay(day) {
  const counts = day.counts || {filings: 0, news: 0, community: 0};
  return `<section class="daily-document day-report" id="day-${escAttr(day.date)}">
    <header class="day-report-head">
      <div><p class="eyebrow">${t("daily.day_report")}</p><h2>${formatDay(day.date)}</h2></div>
      <div class="category-counts" aria-label="${t("daily.update_counts")}">
        <span><strong>${counts.filings || 0}</strong> ${t("cat.filings")}</span>
        <span><strong>${counts.news || 0}</strong> ${t("cat.news")}</span>
        <span><strong>${counts.community || 0}</strong> ${t("cat.community")}</span>
      </div>
    </header>
    ${day.companies.length ? day.companies.map(company => dailyCompany(company)).join("") : `<div class="day-empty"><p>${t("daily.no_updates")}</p></div>`}
  </section>`;
}

function dailyCompany(company) {
  const items = company.items || [];
  let groups = "";
  let lastType = null;
  for (const item of items) {
    const label = categoryLabel(item.type);
    if (label !== lastType) {
      groups += `<h3 class="category-title">${esc(label)}</h3>`;
      lastType = label;
    }
    const url = safeUrl(item.url);
    groups += `
      <article class="information-row">
        <time datetime="${escAttr(item.time)}">${formatTime(item.time)}</time>
        <span class="type type-${escAttr(String(item.type).toLowerCase())}">${esc(item.type)}</span>
        <span class="source">${esc(item.source)}${(item.also_seen_on || []).length ? ` · ${t("common.also_seen_on")} ${item.also_seen_on.map(esc).join(", ")}` : ""}</span>
        <a class="title" href="${escAttr(url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
        <a class="raw-url" href="${escAttr(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>
      </article>`;
  }
  const updateLabel = items.length === 1 ? t("common.update_one") : t("common.update_many");
  return `<section class="company-section">
    <header><div><h2>${esc(company.name)}</h2><p>${esc(company.ticker)} · ${esc(exchangeLabel(company.exchange))}${company.market ? ` · ${esc(String(company.market).toUpperCase())}` : ""}</p></div><span>${items.length} ${updateLabel}</span></header>
    <div class="information-list">${groups}</div>
  </section>`;
}

async function renderResearch() {
  const params = new URLSearchParams(location.search);
  const legacyDate = params.get("date");
  const endDate = params.get("end_date") || legacyDate || state.bootstrap.report_selected_date;
  const startDate = params.get("start_date") || legacyDate || endDate;
  const list = params.get("list") || "";
  document.getElementById("page").innerHTML = `
    <section class="page-heading">
      <p class="eyebrow">${t("research.eyebrow")}</p>
      <h1>${t("research.heading")}</h1>
      <p>${t("research.subtitle")}</p>
      <p class="disclaimer">${t("research.disclaimer")}</p>
    </section>
    <form class="toolbar range-toolbar research-range-toolbar" id="research-filter">
      <label>${t("research.from")}<input type="date" id="research-start-date" value="${escAttr(startDate)}" required></label>
      <label>${t("research.to")}<input type="date" id="research-end-date" value="${escAttr(endDate)}" required></label>
      <label>${t("research.list")}<select id="research-list"><option value="">${t("research.all_lists")}</option>${listOptions(list)}</select></label>
      <button class="button primary" type="submit">${t("research.apply")}</button>
      <p class="model-status" id="research-model"></p>
      <p class="data-send-note">${t("research.data_send")}</p>
    </form>
    <div id="research-companies"><p class="loading">${t("research.loading")}</p></div>
    <div id="research-card" class="research-card"></div>`;
  document.getElementById("research-filter").addEventListener("submit", event => {
    event.preventDefault();
    const start = document.getElementById("research-start-date").value;
    const end = document.getElementById("research-end-date").value;
    if (start > end) { toast(t("research.start_after_end"), true); return; }
    // Navigating rebuilds the page, so a previous range's card is never shown
    // under the new scope.
    const next = withLang(new URLSearchParams({start_date: start, end_date: end}));
    const nextList = document.getElementById("research-list").value;
    if (nextList) next.set("list", nextList);
    location.href = `/research?${next}`;
  });
  await loadResearchCompanies(startDate, endDate, list);
}

function researchScopeParams(startDate, endDate, list) {
  const query = withLang(new URLSearchParams({start_date: startDate, end_date: endDate}));
  if (list) query.set("list", list);
  return query;
}

function currentResearchScope() {
  const params = new URLSearchParams(location.search);
  const legacyDate = params.get("date");
  const endDate = params.get("end_date") || legacyDate || state.bootstrap.report_selected_date;
  const startDate = params.get("start_date") || legacyDate || endDate;
  return {startDate, endDate, list: params.get("list") || ""};
}

async function loadResearchCompanies(startDate, endDate, list) {
  const query = researchScopeParams(startDate, endDate, list);
  try {
    const data = await api(`/api/research/companies?${query}`);
    renderResearchModel(data.model);
    renderResearchCompanies(data.companies);
  } catch (error) {
    document.getElementById("research-companies").innerHTML = errorState(t("common.request_failed"), error.message);
  }
}

function renderResearchModel(model) {
  const el = document.getElementById("research-model");
  if (!el) return;
  el.textContent = model && model.enabled && model.configured
    ? `${t("research.model_label")}: ${String(model.model)}`
    : t("research.model_not_configured");
}

function renderResearchCompanies(companies) {
  const target = document.getElementById("research-companies");
  if (!companies.length) {
    target.innerHTML = `<div class="empty compact"><p>${t("research.no_companies")}</p></div>`;
    return;
  }
  target.innerHTML = `<div class="table-wrap"><table class="research-table"><thead><tr>
    <th>${t("manage.company")}</th><th>${t("manage.ticker")}</th><th>${t("manage.market")}</th>
    <th>${t("research.evidence_coverage")}</th><th>${t("research.latest_evidence")}</th>
    <th>${t("research.card_status")}</th><th>${t("research.last_generated")}</th><th></th>
  </tr></thead><tbody>${companies.map(researchCompanyRow).join("")}</tbody></table></div>`;
  bindResearchActions();
}

function researchCompanyRow(company) {
  const coverage = `${company.evidence_total} ${t("research.total_items")} · ${company.filing_count} ${t("research.filings")} · ${company.news_count} ${t("research.news")} · ${company.community_count} ${t("research.community")}`;
  const stale = company.stale ? `<span class="badge stale">${t("research.new_evidence")}</span>` : "";
  const latest = company.latest_evidence_at ? formatDateTime(company.latest_evidence_at) : t("common.none_recorded");
  const generated = company.latest_generated_at ? formatDateTime(company.latest_generated_at) : t("research.no_card");
  return `<tr>
    <td>${esc(company.name)}<br><small>${(company.lists || []).map(slug => esc(listDisplayName(slug))).join(", ")}</small></td>
    <td>${esc(company.ticker)}</td>
    <td>${esc(String(company.market).toUpperCase())}</td>
    <td>${coverage}</td>
    <td>${latest}</td>
    <td><span class="status rs-${escAttr(company.status)}">${esc(researchStatusLabel(company.status))}</span>${stale}</td>
    <td>${generated}</td>
    <td>${researchButtons(company)}</td>
  </tr>`;
}

function researchStatusKey(status) {
  const map = {
    not_generated: "status.not_generated",
    ready: "status.ready",
    generating: "status.generating",
    cached: "status.cached",
    stale: "status.stale",
    insufficient_evidence: "research.insufficient_evidence",
    model_not_configured: "research.model_not_configured",
    failed: "research.generation_failed",
  };
  return map[status] || status;
}

function researchStatusLabel(status) { return t(researchStatusKey(status)); }

function researchButtons(company) {
  const id = company.id;
  if (company.status === "model_not_configured") {
    return `<button class="button" disabled>${t("research.generate")}</button>`;
  }
  if (company.status === "generating") {
    return `<button class="button" disabled>${t("research.generating")}</button>`;
  }
  if (company.status === "insufficient_evidence") {
    return `<button class="button" disabled>${t("research.insufficient_evidence")}</button>`;
  }
  const hasCard = company.status === "cached" || company.status === "stale" || company.status === "failed";
  const view = hasCard && company.latest_card_id
    ? `<button class="button" data-action="view" data-id="${escAttr(id)}" data-card="${escAttr(company.latest_card_id)}">${t("research.view")}</button>`
    : "";
  const label = hasCard ? t("research.regenerate") : t("research.generate");
  return `${view}<button class="button primary" data-action="generate" data-id="${escAttr(id)}" data-force="${hasCard}">${label}</button>`;
}

function bindResearchActions() {
  document.querySelectorAll("[data-action='generate']").forEach(button => {
    button.addEventListener("click", () => generateCard(button.dataset.id, button.dataset.force === "true", button));
  });
  document.querySelectorAll("[data-action='view']").forEach(button => {
    button.addEventListener("click", () => viewCard(button.dataset.card));
  });
}

const GENERATION_POLL_INTERVAL_MS = 1500;
const GENERATION_FOREGROUND_TIMEOUT_MS = 120000;

const GENERATION_ERROR_MESSAGES = {
  research_disabled: "research.error.internal",
  model_not_configured: "research.model_not_configured",
  no_eligible_evidence: "research.insufficient_evidence",
  insufficient_evidence: "research.insufficient_evidence",
  upstream_timeout: "research.error.upstream_timeout",
  upstream_network_error: "research.error.upstream_network",
  upstream_auth_error: "research.error.upstream_auth",
  upstream_rate_limited: "research.error.upstream_rate_limited",
  upstream_server_error: "research.error.upstream_server",
  upstream_redirect_error: "research.error.upstream_server",
  invalid_model_response: "research.error.invalid_response",
  invalid_evidence_reference: "research.error.invalid_response",
  generation_in_progress: "research.generating",
  research_internal_error: "research.error.internal",
  request_too_large: "research.error.request_too_large",
  response_too_large: "research.error.response_too_large",
  research_range_too_large: "research.error.range_too_large",
};

function generationFailureMessage(status) {
  const code = (status && (status.error_code || status.code)) || "";
  const key = GENERATION_ERROR_MESSAGES[code];
  return key ? t(key) : t("research.generation_failed");
}

async function generateCard(companyId, force, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = t("research.generating");
  const scope = currentResearchScope();
  try {
    const result = await api("/api/research/generate", {
      method: "POST",
      body: JSON.stringify({
        company_id: Number(companyId),
        language: lang,
        force,
        start_date: scope.startDate,
        end_date: scope.endDate,
        list: scope.list || "all",
      }),
    });
    if (result.status === "cached" || result.status === "completed") {
      if (result.card_id) await viewCard(result.card_id);
    } else if (result.status === "generating") {
      await pollGeneration(result.generation_id);
    } else {
      toast(generationFailureMessage(result), true);
    }
  } catch (error) {
    toast(t("common.request_failed"), true);
  } finally {
    button.disabled = false;
    button.textContent = original;
    // Always re-sync from the server so the authoritative status overwrites
    // any local "generating" state (including after a foreground timeout).
    await loadResearchCompanies(scope.startDate, scope.endDate, scope.list);
  }
}

async function pollGeneration(generationId) {
  const deadline = Date.now() + GENERATION_FOREGROUND_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, GENERATION_POLL_INTERVAL_MS));
    try {
      const status = await api(`/api/research/generations/${generationId}`);
      if (status.status === "completed") { if (status.card_id) await viewCard(status.card_id); return; }
      if (status.status === "failed") { toast(generationFailureMessage(status), true); return; }
    } catch (_) { return; }
  }
  // Reached the foreground wait limit: do not pretend this failed. The list is
  // re-synced by generateCard's finally, and the user is told it continues in
  // the background.
  toast(t("research.generating_in_background"));
}

async function viewCard(cardId) {
  try {
    const card = await api(`/api/research/cards/${cardId}`);
    if (!card || card.status !== "completed") {
      document.getElementById("research-card").innerHTML = errorState(t("research.generation_failed"), "");
      return;
    }
    document.getElementById("research-card").innerHTML = researchCardContent(card);
    bindResearchPrint();
  } catch (error) {
    document.getElementById("research-card").innerHTML = errorState(t("research.generation_failed"), error.message);
  }
}

function bindResearchPrint() {
  const button = document.querySelector('[data-action="print-research"]');
  if (button) button.addEventListener("click", () => window.print());
}

function listScopeLabel(slug) {
  if (!slug) return t("research.all_lists");
  const found = (state.bootstrap?.lists || []).find(l => l.slug === slug);
  return found ? listDisplayName(found) : listDisplayName(slug);
}

function researchCardMeta(card) {
  if (!card.start_date || !card.end_date) return "";
  const generated = card.generated_at ? formatDateTime(card.generated_at) : "";
  const counts = `${t("research.filings")}: ${card.filing_count || 0} · ${t("research.news")}: ${card.news_count || 0} · ${t("research.community")}: ${card.community_count || 0}`;
  return `<p class="meta research-card-scope">${t("research.card_scope")}: ${esc(card.start_date)} → ${esc(card.end_date)} · ${esc(listScopeLabel(card.list_scope))}</p>
    <p class="meta research-card-counts">${t("research.evidence_in_range")}: ${card.evidence_total} · ${counts} · ${t("research.evidence_sent")}: ${card.evidence_sent}${generated ? ` · ${t("research.last_generated")}: ${esc(generated)}` : ""}</p>`;
}

function researchCompanyLine(card) {
  const parts = [];
  if (card.company_name) parts.push(card.company_name);
  if (card.ticker) parts.push(card.ticker);
  if (card.market) parts.push(String(card.market).toUpperCase());
  if (!parts.length) return "";
  return `<p class="research-company">${parts.map(esc).join(" · ")}</p>`;
}

function researchCardContent(card) {
  if (!card || card.status !== "completed") return "";
  const content = card.content || {};
  const coverage = content.coverage || {};
  const sections = [
    `<section class="research-card-inner" data-card-id="${escAttr(card.id)}">
      <header class="research-card-header">
        <p class="print-brand">Investment Monitor · ${t("research.print_title")}</p>
        <div class="research-card-title">
          <h2>${t("research.heading")}</h2>
          <button class="button" data-action="print-research" type="button">${t("research.print_pdf")}</button>
        </div>
        ${researchCompanyLine(card)}
        ${researchCardMeta(card)}
        <p class="disclaimer">${t("research.disclaimer")}</p>
      </header>
      <section><h3>${t("research.evidence_coverage")}</h3>
        <p>${esc(coverage.summary || "")}</p>
        ${(coverage.limitations || []).length ? `<ul>${coverage.limitations.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      </section>`,
    researchChangeSection(content.recent_changes),
    researchRiskSection(content.main_risks),
    researchVolatilitySection(content.volatility_drivers),
    researchQuestionSection(content.questions_to_investigate),
    researchEvidenceList(card.evidence),
    `</section>`,
  ];
  return sections.join("");
}

function refBadges(ids) { return (ids || []).map(id => `<span class="ref">${esc(id)}</span>`).join(" "); }
function claimLabel(claim) {
  const map = { direct_disclosure_fact: "research.claim.direct_disclosure_fact", reported_news: "research.claim.reported_news", community_viewpoint: "research.claim.community_viewpoint", cautious_inference: "research.claim.cautious_inference" };
  return map[claim] ? t(map[claim]) : claim;
}
function strengthLabel(s) {
  const map = { high: "research.strength.high", medium: "research.strength.medium", low: "research.strength.low" };
  return map[s] ? t(map[s]) : s;
}

function researchChangeSection(changes) {
  if (!changes || !changes.length) return "";
  return `<section><h3>${t("research.recent_changes")}</h3>
    <ul class="research-claims">${changes.map(c => `<li><strong>${esc(c.title)}</strong><p>${esc(c.summary)}</p><p class="meta">${claimLabel(c.claim_type)} · ${refBadges(c.evidence_ids)}</p></li>`).join("")}</ul></section>`;
}

function researchRiskSection(risks) {
  if (!risks || !risks.length) return "";
  return `<section><h3>${t("research.main_risks")}</h3>
    <ul class="research-claims">${risks.map(r => `<li><strong>${esc(r.title)}</strong><span class="meta">${esc(r.category)} · ${strengthLabel(r.evidence_strength)}</span><p>${esc(r.explanation)}</p><p class="meta">${claimLabel(r.claim_type)} · ${refBadges(r.evidence_ids)}</p></li>`).join("")}</ul></section>`;
}

function researchVolatilitySection(drivers) {
  if (!drivers || !drivers.length) return "";
  return `<section><h3>${t("research.volatility_drivers")}</h3>
    <ul class="research-claims">${drivers.map(d => `<li><strong>${esc(d.trigger)}</strong><p>${esc(d.why_it_matters)}</p>${(d.signals_to_watch || []).length ? `<p class="meta">${t("research.signals")}: ${d.signals_to_watch.map(esc).join(", ")}</p>` : ""}<p class="meta">${claimLabel(d.claim_type)} · ${refBadges(d.evidence_ids)}</p></li>`).join("")}</ul></section>`;
}

function researchQuestionSection(questions) {
  if (!questions || !questions.length) return "";
  return `<section><h3>${t("research.questions")}</h3>
    <ul class="research-claims">${questions.map(q => `<li><strong>${esc(q.question)}</strong><p>${esc(q.reason)}</p><p class="meta">${refBadges(q.evidence_ids)}</p></li>`).join("")}</ul></section>`;
}

function researchEvidenceList(evidence) {
  if (!evidence || !evidence.length) return "";
  return `<details class="evidence-list"><summary>${t("research.evidence")} (${evidence.length})</summary>
    <ul>${evidence.map(item => `<li><span class="ref">${esc(item.evidence_ref)}</span>
      <a href="${escAttr(safeUrl(item.url_snapshot))}" target="_blank" rel="noopener noreferrer">${esc(item.title_snapshot)}</a>
      <a class="raw-url" href="${escAttr(safeUrl(item.url_snapshot))}" target="_blank" rel="noopener noreferrer">${esc(item.url_snapshot)}</a>
      <small>${esc(item.source)} · ${researchInfoTypeLabel(item.information_type)} · ${formatDateTime(item.event_timestamp)}</small></li>`).join("")}</ul></details>`;
}

function researchInfoTypeLabel(type) {
  const key = {filing: "research.filings", news: "research.news", community: "research.community"}[type];
  return key ? t(key) : type;
}

const MARKET_CODES = ["us","jp","hk","cn","kr","uk","tw","ca","au","be","fr","de","nl","it","es","sg","ch","pl","se","ee","lv","lt","no","pt","at","in","aq","cxe","emf","trq","eux","unknown"];

// 固定列表名按当前语言显示；用户重命名的自定义列表始终显示用户的名字。
const FIXED_LIST_LABELS = {
  holdings: {en: "Holdings", "zh-CN": "持仓"},
  planned: {en: "Planned Purchases", "zh-CN": "计划买入"},
  watchlist: {en: "Watchlist", "zh-CN": "观察列表"},
};
function listDisplayName(list) {
  if (typeof list === "string") {
    const found = (state.bootstrap?.lists || []).find(item => item.slug === list);
    if (found) return listDisplayName(found);
    const label = FIXED_LIST_LABELS[list];
    return label ? (label[lang] || label.en) : list;
  }
  if (list && list.is_fixed && FIXED_LIST_LABELS[list.slug]) {
    return FIXED_LIST_LABELS[list.slug][lang] || FIXED_LIST_LABELS[list.slug].en;
  }
  return list ? list.name : "";
}

async function renderManage() {
  document.getElementById("page").innerHTML = `
    <section class="page-heading"><p class="eyebrow">${t("manage.eyebrow")}</p><h1>${t("manage.heading")}</h1><p>${t("manage.subtitle")}</p></section>
    <section class="management-section" aria-labelledby="lists-title">
      <div class="section-heading"><div><h2 id="lists-title">${t("manage.lists")}</h2><p>${t("manage.lists_desc")}</p></div>
        <form id="create-list" class="inline-form"><label class="sr-only" for="new-list-name">${t("manage.new_list_name")}</label><input id="new-list-name" maxlength="80" placeholder="${t("manage.new_list_name")}" required><button class="button primary">${t("manage.create")}</button></form>
      </div><div id="list-strip" class="list-strip"></div>
    </section>
    <section class="management-section" aria-labelledby="companies-title">
      <div class="section-heading"><div><h2 id="companies-title">${t("manage.companies")}</h2><p id="company-context"></p></div></div>
      <div class="company-add-grid">
        <div class="company-add-card">
          <h3>${t("manage.manual_add")}</h3>
          <form id="company-search" class="search-form">
            <div>
              <input id="company-query" autocomplete="off" placeholder="${t("manage.add_placeholder")}" required>
              <button class="button primary" id="add-ticker-direct" type="submit">${t("manage.add_ticker")}</button>
            </div>
            <small class="add-help">${t("manage.add_help")}</small>
          </form>
        </div>
        <form id="company-csv" class="company-add-card csv-import-form">
          <div><h3>${t("manage.csv_add")}</h3><p>${t("manage.csv_desc")}</p></div>
          <label for="company-csv-input">${t("manage.csv_rows")}</label>
          <textarea id="company-csv-input" spellcheck="false" placeholder="ticker,market,list&#10;AAPL,US,holdings&#10;7203,JP,watchlist&#10;RY,CA,planned&#10;BHP,AU,holdings"></textarea>
          <small>${t("manage.csv_help")}<br><code>${MARKET_CODES.join(", ")}</code></small>
          <label for="company-csv-file">${t("manage.csv_file")}</label>
          <input id="company-csv-file" type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values">
          <button class="button primary" type="submit">${t("manage.csv_import")}</button>
        </form>
      </div>
      <div id="csv-import-result" aria-live="polite"></div>
      <div id="company-table"></div>
    </section>
    <section class="management-section" aria-labelledby="sources-title">
      <div class="section-heading"><div><h2 id="sources-title">${t("manage.information_sources")}</h2><p>${t("manage.sources_desc")}</p></div></div>
      <div id="source-grid"><p class="loading">${t("manage.loading_sources")}</p></div>
    </section>`;
  bindManagement();
  await refreshManagement();
}

function bindManagement() {
  document.getElementById("create-list").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const result = await api("/api/lists", {method:"POST", body:JSON.stringify({name:document.getElementById("new-list-name").value})});
      state.selectedList = result.list.slug; toast(t("manage.list_created")); await reloadBootstrap(); await refreshManagement();
    } catch (error) { toast(error.message, true); }
  });
  document.getElementById("company-search").addEventListener("submit", addTickerDirect);
  document.getElementById("company-csv-file").addEventListener("change", loadCsvFile);
  document.getElementById("company-csv").addEventListener("submit", importCompanyCsv);
}

async function loadCsvFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  try { document.getElementById("company-csv-input").value = await file.text(); }
  catch (_) { toast(t("common.request_failed"), true); }
}

async function importCompanyCsv(event) {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  const target = document.getElementById("csv-import-result");
  button.disabled = true;
  try {
    const result = await api("/api/companies/csv", {
      method:"POST",
      body:JSON.stringify({csv:document.getElementById("company-csv-input").value}),
    });
    target.innerHTML = csvImportResult(result);
    toast(t("manage.csv_done"));
    await reloadBootstrap();
    await refreshManagement();
  } catch (error) {
    target.innerHTML = `<div class="csv-result error">${esc(error.message)}</div>`;
  } finally { button.disabled = false; }
}

function csvImportResult(result) {
  const sections = [];
  if (result.added?.length) sections.push(`<strong>${t("manage.csv_added")}:</strong> ${result.added.map(item => `${esc(item.ticker)} (${esc(String(item.market).toUpperCase())})`).join(", ")}`);
  if (result.already_present?.length) sections.push(`<strong>${t("manage.csv_existing")}:</strong> ${result.already_present.map(item => `${esc(item.ticker)} (${esc(String(item.market).toUpperCase())})`).join(", ")}`);
  if (result.failed?.length) sections.push(`<strong>${t("manage.csv_failed")}:</strong> ${result.failed.map(item => `${item.row ? `${t("manage.csv_row", {row:item.row})}: ` : ""}${esc(item.ticker)} — ${esc(item.error)}`).join("; ")}`);
  return `<div class="csv-result">${sections.join("<br>") || t("manage.csv_done")}</div>`;
}

async function refreshManagement() {
  renderLists(); renderCompanies();
  try { renderSources((await api("/api/sources")).sources); }
  catch (error) { document.getElementById("source-grid").innerHTML = errorState(t("common.request_failed"), error.message); }
}

function renderLists() {
  const lists = state.bootstrap.lists;
  if (!lists.length) state.selectedList = "";
  if (state.selectedList && !lists.some(list => list.slug === state.selectedList)) state.selectedList = lists[0]?.slug || "";
  document.getElementById("list-strip").innerHTML = lists.length ? lists.map(list => `
    <article class="list-card ${list.slug === state.selectedList ? "selected" : ""}" data-slug="${escAttr(list.slug)}">
      <button class="list-select" type="button"><strong>${esc(listDisplayName(list))}</strong><span>${t("manage.companies_count", {count: list.company_count})}</span></button>
      <div><button class="text-button rename-list" type="button">${t("manage.rename")}</button><button class="text-button danger delete-list" type="button">${t("manage.delete")}</button></div>
    </article>`).join("") : `<div class="empty compact"><p>${t("manage.create_list_first")}</p></div>`;
  document.querySelectorAll(".list-select").forEach(button => button.addEventListener("click", () => { state.selectedList = button.closest(".list-card").dataset.slug; renderLists(); renderCompanies(); }));
  document.querySelectorAll(".rename-list").forEach(button => button.addEventListener("click", () => renameList(button.closest(".list-card").dataset.slug)));
  document.querySelectorAll(".delete-list").forEach(button => button.addEventListener("click", () => deleteList(button.closest(".list-card").dataset.slug)));
}

async function renameList(slug) {
  const current = state.bootstrap.lists.find(list => list.slug === slug);
  const name = prompt(t("manage.list_name"), current.name);
  if (name === null || !name.trim()) return;
  try { await api("/api/lists/rename", {method:"POST", body:JSON.stringify({slug,name})}); toast(t("manage.list_renamed")); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

async function deleteList(slug) {
  const current = state.bootstrap.lists.find(list => list.slug === slug);
  if (!confirm(t("manage.delete_confirm", {name: current.name}))) return;
  try { await api("/api/lists/delete", {method:"POST", body:JSON.stringify({slug})}); toast(t("manage.list_deleted")); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

function renderCompanies() {
  const list = state.bootstrap.lists.find(item => item.slug === state.selectedList);
  const companies = state.bootstrap.companies.filter(company => company.list_slugs.includes(state.selectedList));
  document.getElementById("company-context").textContent = list ? `${listDisplayName(list)} · ${t("manage.companies_count", {count: companies.length})}` : t("manage.create_or_select_first");
  document.getElementById("company-table").innerHTML = companies.length ? `<div class="table-wrap"><table><thead><tr><th>${t("manage.company")}</th><th>${t("manage.ticker")}</th><th>${t("manage.exchange")}</th><th>${t("manage.region")}</th><th></th></tr></thead><tbody>${companies.map(company => `<tr><td>${esc(company.name)}</td><td>${esc(company.ticker)}</td><td>${esc(exchangeLabel(company.exchange))}</td><td>${regionForMarket(company.market)}</td><td><button class="text-button danger remove-company" data-ticker="${escAttr(company.ticker)}" data-market="${escAttr(company.market)}">${t("manage.remove")}</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty compact"><p>${t("manage.no_companies")}</p></div>`;
  document.querySelectorAll(".remove-company").forEach(button => button.addEventListener("click", () => removeCompany(button.dataset.ticker, button.dataset.market)));
}

async function loadCsvFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  try { document.getElementById("company-csv-input").value = await file.text(); }
  catch (_) { toast(t("common.request_failed"), true); }
}

async function importCompanyCsv(event) {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
  const target = document.getElementById("csv-import-result");
  button.disabled = true;
  try {
    const result = await api("/api/companies/csv", {
      method:"POST",
      body:JSON.stringify({csv:document.getElementById("company-csv-input").value}),
    });
    target.innerHTML = csvImportResult(result);
    toast(t("manage.csv_done"));
    await reloadBootstrap();
    await refreshManagement();
  } catch (error) {
    target.innerHTML = `<div class="csv-result error">${esc(error.message)}</div>`;
  } finally { button.disabled = false; }
}

function csvImportResult(result) {
  const sections = [];
  if (result.added?.length) sections.push(`<strong>${t("manage.csv_added")}:</strong> ${result.added.map(item => `${esc(item.ticker)} (${esc(String(item.market).toUpperCase())})`).join(", ")}`);
  if (result.already_present?.length) sections.push(`<strong>${t("manage.csv_existing")}:</strong> ${result.already_present.map(item => `${esc(item.ticker)} (${esc(String(item.market).toUpperCase())})`).join(", ")}`);
  if (result.failed?.length) sections.push(`<strong>${t("manage.csv_failed")}:</strong> ${result.failed.map(item => `${item.row ? `${t("manage.csv_row", {row:item.row})}: ` : ""}${esc(item.ticker)} — ${esc(item.error)}`).join("; ")}`);
  return `<div class="csv-result">${sections.join("<br>") || t("manage.csv_done")}</div>`;
}

async function addTickerDirect(event) {
  event.preventDefault();
  const button = document.getElementById("add-ticker-direct");
  if (button.disabled) return;
  if (!state.selectedList) { toast(t("manage.create_or_select_first"), true); return; }
  const tickers = document.getElementById("company-query").value.trim();
  if (!tickers) { toast(t("manage.enter_ticker_first"), true); return; }
  button.disabled = true;
  toast(t("manage.adding_company"));
  try {
    const result = await api("/api/companies/batch", {method:"POST", body:JSON.stringify({tickers, lists:[state.selectedList]})});
    const added = (result.added || []).map(row => `${esc(row.ticker)} (${esc(String(row.market).toUpperCase())})`);
    if (added.length) toast(t("manage.added_collecting_background", {items: added.join(", ")}));
    for (const item of (result.failed || [])) {
      toast(`${esc(item.ticker)}: ${esc(item.error)}`, true);
    }
    await reloadBootstrap();
    await refreshManagement();
    if (result.backfill_task_id) await pollBackfill(result.backfill_task_id);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function pollBackfill(taskId) {
  let consecutiveFailures = 0;
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 2000));
    try {
      const task = await api(`/api/backfill-tasks/${encodeURIComponent(taskId)}`);
      if (task.status === "success") { toast(t("manage.collection_complete")); return; }
      if (task.status === "partial") { toast(t("manage.collection_partial", {error: task.error || ""}).trim(), true); return; }
      if (task.status === "failure") { toast(t("manage.collection_failed", {error: task.error || ""}).trim(), true); return; }
      consecutiveFailures = 0;
    } catch (error) {
      consecutiveFailures += 1;
      if (consecutiveFailures >= 3) return;
    }
  }
}

async function removeCompany(ticker, market) {
  try { await api("/api/memberships/remove", {method:"POST", body:JSON.stringify({ticker, market, list:state.selectedList})}); toast(t("manage.removed", {ticker})); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

function renderSources(sources) {
  document.getElementById("source-grid").innerHTML = `<div class="source-grid">${sources.map(source => `<article class="source-card"><div class="source-card-head"><div><h3>${esc(source.provider)}</h3><p>${esc(source.type)} · ${source.regions.length ? source.regions.map(esc).join(", ") : t("manage.coverage_not_provided")}</p></div><span class="status ${escAttr(source.status)}">${statusLabel(source.status)}</span></div><dl><div><dt>${t("manage.enabled")}</dt><dd>${source.enabled ? t("manage.yes") : t("manage.no")}</dd></div><div><dt>${t("manage.latest_success")}</dt><dd>${source.latest_success ? formatDateTime(source.latest_success) : t("manage.none_recorded")}</dd></div><div><dt>${t("manage.latest_attempt")}</dt><dd>${source.latest_attempt ? formatDateTime(source.latest_attempt) : t("manage.none_recorded")}</dd></div></dl>${source.last_failure ? `<details><summary>${t("manage.failure_details")}</summary><p>${esc(source.last_failure)}</p></details>` : ""}</article>`).join("")}</div>`;
}

async function reloadBootstrap() { state.bootstrap = await api("/api/bootstrap"); }
function listOptions(selected) { return state.bootstrap.lists.map(list => `<option value="${escAttr(list.slug)}" ${list.slug === selected ? "selected" : ""}>${esc(listDisplayName(list))}</option>`).join(""); }
function statusLabel(status) { const key = {connected:"status.connected", stale:"status.data_stale", not_connected:"status.not_connected", temporarily_unavailable:"status.failed", unavailable:"status.waiting_for_data"}[status]; return key ? t(key) : status; }
function regionForMarket(market) { const key = {us:"region.us", jp:"region.jp", hk:"region.hk", cn:"region.cn", kr:"region.kr", uk:"region.uk", tw:"region.tw", ca:"region.ca", au:"region.au", be:"region.be", fr:"region.fr", de:"region.de", nl:"region.nl", it:"region.it", es:"region.es", sg:"region.sg", ch:"region.ch", pl:"region.pl", se:"region.se", ee:"region.ee", lv:"region.lv", lt:"region.lt", no:"region.no", pt:"region.pt", at:"region.at", in:"region.in", aq:"region.aq", cxe:"region.cxe", emf:"region.emf", trq:"region.trq", eux:"region.eux"}[market]; return key ? t(key) : t("common.unavailable"); }
function categoryLabel(type) { const key = {Filing:"cat.official_filings", News:"cat.news", Community:"cat.community"}[type]; return key ? t(key) : type; }
function exchangeLabel(exchange) { return exchange && exchange !== "Unavailable" ? exchange : t("common.unavailable"); }
function formatDay(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"full", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatShortDay(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"medium", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatRange(start, end) { return start === end ? formatDay(start) : `${formatShortDay(start)} – ${formatShortDay(end)}`; }
function formatTime(value) { return new Intl.DateTimeFormat(localeFor(), {hour:"numeric", minute:"2-digit", timeZone:"Asia/Shanghai", timeZoneName:"short"}).format(new Date(value)); }
function formatDateTime(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"medium", timeStyle:"short", timeZone:"America/New_York"}).format(new Date(value)) + " ET"; }
function errorState(title, message) { return `<div class="empty error"><h2>${esc(title)}</h2><p>${esc(message)}</p></div>`; }
async function api(url, options={}) { const headers = {"Content-Type":"application/json", ...(options.headers||{})}; let token=""; try { token = localStorage.getItem("im_web_auth_token") || ""; } catch (_) { /* localStorage unavailable */ } if (token) headers.Authorization = `Bearer ${token}`; const response = await fetch(url, {...options, headers}); const payload = await response.json(); if (!response.ok) { const error = new Error(payload.error || t("common.request_failed_status", {status: response.status})); error.status = response.status; error.code = payload.code || ""; throw error; } return payload; }
function toast(message, error=false) { const node=document.createElement("div"); node.className=`toast ${error?"error":""}`; node.textContent=message; document.getElementById("toast-region").appendChild(node); setTimeout(()=>node.remove(),4000); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
function escAttr(value) { return esc(value); }
function safeUrl(value) { try { const url = new URL(String(value)); return ["http:", "https:"].includes(url.protocol) ? url.href : "#"; } catch (_) { return "#"; } }
function renderFatal(error) { document.getElementById("page").innerHTML = errorState(t("common.workspace_failed"), error.message); }
