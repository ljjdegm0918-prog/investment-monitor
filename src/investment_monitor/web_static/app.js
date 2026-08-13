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
    "region.aq": "Aquis (AQSE)",
    "region.cxe": "Cboe Europe (CXE)",
    "region.emf": "Europe (Funds)",
    "region.trq": "Turquoise (TRQ)",
    "region.eux": "Europe (Eurex)",
    "nav.research": "Research",
    "research.eyebrow": "RESEARCH ASSISTANT",
    "research.heading": "Research",
    "research.subtitle": "Evidence-backed summaries of the companies you already track in Holdings, Planned, or Watchlist.",
    "research.disclaimer": "Research assistance only. This is not investment advice.",
    "research.data_send": "Generating a card sends this company’s selected public evidence to your configured model provider.",
    "research.list": "List",
    "research.all_lists": "All lists",
    "research.model_label": "Model",
    "research.model_enabled": "enabled",
    "research.model_disabled": "not configured",
    "research.generate": "Generate research card",
    "research.view": "View latest card",
    "research.regenerate": "Regenerate",
    "research.new_evidence": "New evidence available",
    "research.evidence_coverage": "Evidence coverage",
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
    "region.aq": "Aquis (AQSE)",
    "region.cxe": "Cboe Europe (CXE)",
    "region.emf": "欧洲（基金）",
    "region.trq": "Turquoise (TRQ)",
    "region.eux": "欧洲（Eurex）",
    "nav.research": "研究",
    "research.eyebrow": "研究助手",
    "research.heading": "研究",
    "research.subtitle": "基于证据，梳理你已在持仓、计划或关注列表中的公司。",
    "research.disclaimer": "仅供研究辅助，不构成投资建议。",
    "research.data_send": "生成研究卡会把该公司的选定公开证据发送给你配置的模型服务。",
    "research.list": "列表",
    "research.all_lists": "所有列表",
    "research.model_label": "模型",
    "research.model_enabled": "已启用",
    "research.model_disabled": "未配置",
    "research.generate": "生成研究卡",
    "research.view": "查看最新研究卡",
    "research.regenerate": "重新生成",
    "research.new_evidence": "有新证据可更新",
    "research.evidence_coverage": "证据覆盖情况",
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
  const list = params.get("list") || "";
  document.getElementById("page").innerHTML = `
    <section class="page-heading">
      <p class="eyebrow">${t("research.eyebrow")}</p>
      <h1>${t("research.heading")}</h1>
      <p>${t("research.subtitle")}</p>
      <p class="disclaimer">${t("research.disclaimer")}</p>
    </section>
    <section class="research-toolbar">
      <label>${t("research.list")}<select id="research-list"><option value="">${t("research.all_lists")}</option>${listOptions(list)}</select></label>
      <p class="model-status" id="research-model"></p>
      <p class="data-send-note">${t("research.data_send")}</p>
    </section>
    <div id="research-companies"><p class="loading">${t("research.loading")}</p></div>
    <div id="research-card" class="research-card"></div>`;
  document.getElementById("research-list").addEventListener("change", event => {
    const next = withLang(new URLSearchParams());
    if (event.target.value) next.set("list", event.target.value);
    location.href = `/research?${next}`;
  });
  await loadResearchCompanies(list);
}

async function loadResearchCompanies(list) {
  const query = withLang(new URLSearchParams());
  if (list) query.set("list", list);
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
  const coverage = `${company.filing_count} ${t("research.filings")} · ${company.news_count} ${t("research.news")} · ${company.community_count} ${t("research.community")}`;
  const stale = company.stale ? `<span class="badge stale">${t("research.new_evidence")}</span>` : "";
  const latest = company.latest_evidence_at ? formatDateTime(company.latest_evidence_at) : t("common.none_recorded");
  const generated = company.latest_generated_at ? formatDateTime(company.latest_generated_at) : t("research.no_card");
  return `<tr>
    <td>${esc(company.name)}<br><small>${esc((company.lists || []).join(", "))}</small></td>
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

async function generateCard(companyId, force, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = t("research.generating");
  try {
    const result = await api("/api/research/generate", {
      method: "POST",
      body: JSON.stringify({ company_id: Number(companyId), language: lang, force }),
    });
    if (result.status === "cached" || result.status === "completed") {
      if (result.card_id) await viewCard(result.card_id);
      await loadResearchCompanies(new URLSearchParams(location.search).get("list") || "");
    } else if (result.status === "generating") {
      await pollGeneration(result.generation_id);
      await loadResearchCompanies(new URLSearchParams(location.search).get("list") || "");
    } else {
      toast(result.error || t("research.generation_failed"), true);
    }
  } catch (error) {
    toast(error.message, true);
  }
  button.disabled = false;
  button.textContent = original;
}

async function pollGeneration(generationId) {
  for (let attempt = 0; attempt < 120; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    try {
      const status = await api(`/api/research/generations/${generationId}`);
      if (status.status === "completed") { if (status.card_id) await viewCard(status.card_id); return; }
      if (status.status === "failed") { toast(status.error_code || t("research.generation_failed"), true); return; }
    } catch (_) { return; }
  }
  toast(t("research.generation_failed"), true);
}

async function viewCard(cardId) {
  try {
    const card = await api(`/api/research/cards/${cardId}`);
    document.getElementById("research-card").innerHTML = researchCardContent(card);
  } catch (error) {
    document.getElementById("research-card").innerHTML = errorState(t("research.generation_failed"), error.message);
  }
}

function researchCardContent(card) {
  const content = card.content || {};
  const coverage = content.coverage || {};
  const sections = [
    `<section class="research-card-inner">
      <header><h2>${t("research.heading")}</h2><p class="disclaimer">${t("research.disclaimer")}</p></header>
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
      <small>${esc(item.source)} · ${esc(item.information_type)} · ${formatDateTime(item.event_timestamp)}</small></li>`).join("")}</ul></details>`;
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
      <form id="company-search" class="search-form">
        <label for="company-query">${t("manage.search_by")}</label>
        <div>
          <select id="market-select" aria-label="${t("manage.market")}">
            <option value="us" selected>US</option>
            <option value="jp">JP</option>
            <option value="hk">HK</option>
            <option value="cn">CN</option>
            <option value="kr">KR</option>
            <option value="uk">UK</option>
            <option value="tw">TW</option>
            <option value="ca">CA</option>
            <option value="au">AU</option>
            <option value="be">Belgium (Euronext)</option>
            <option value="fr">France (Euronext)</option>
            <option value="de">Germany (XETRA/Frankfurt)</option>
            <option value="nl">Netherlands (Euronext)</option>
            <option value="it">Italy (Euronext)</option>
            <option value="es">Spain (BME/Madrid)</option>
            <option value="sg">Singapore (SGX)</option>
            <option value="ch">Switzerland (SIX)</option>
            <option value="pl">Poland (GPW)</option>
            <option value="se">Sweden (Nasdaq Stockholm)</option>
            <option value="aq">Aquis (AQSE)</option>
            <option value="cxe">Cboe Europe (CXE)</option>
            <option value="emf">European Mutual Funds</option>
            <option value="trq">Turquoise (TRQ)</option>
            <option value="eux">Eurex Core (EUX)</option>
          </select>
          <input id="company-query" autocomplete="off" placeholder="e.g. Apple, AAPL, or RY.TO" required>
          <button class="button primary" type="submit">${t("manage.search")}</button>
          <button class="button" id="add-ticker-direct" type="button">${t("manage.add_ticker")}</button>
        </div>
        <small id="market-hint">${marketHint("us")}</small>
      </form>
      <div id="candidate-results"></div><div id="company-table"></div>
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
  document.getElementById("company-search").addEventListener("submit", searchCompanies);
  document.getElementById("market-select").addEventListener("change", updateMarketHint);
  document.getElementById("add-ticker-direct").addEventListener("click", addTickerDirect);
  updateMarketHint();
}

const MARKET_HINTS_EN = {
  us: "US candidates come from the local official SEC mapping. News: Finnhub (needs FINNHUB_API_KEY) + Yahoo Finance US + Google News US (key-free RSS). Community: Seeking Alpha (seeking_alpha) LIVE via public combined RSS (/api/sa/combined/{SYMBOL}.xml) — article/news metadata with NY day filter; HTML symbol/forum/comments pages return PerimeterX 403 and are out of scope. Substack (substack) LIVE publication-whitelist RSS (https://{publication}/feed) — newsletter article/news metadata, NY day filter, no structured ticker binding; whitelist: noahpinion.blog, notboring.co, astralcodexten.com, paulkrugman.substack.com, oneusefulthing.org. Yellowbrick Investing (yellowbrick) registered stub — ybrick.co dead, joinyellowbrick.com 404 (spike 2026-08-11); collect() empty. X (x_community) registered stub — no public login-free ticker surface; official API needs paid Bearer (not wired); HTML/syndication scrape out of scope (spike 2026-08-11); collect() empty. Value Investors Club (vic) registered stub — no public RSS/JSON; /ideas?symbol= does not filter; guest access is 45-day delayed only; membership/HTML scrape out of scope (spike 2026-08-11); collect() empty.",
  jp: "Japan companies are added as unmapped. Use Add ticker with the local code; EDINET/TDnet collect by market=jp. News: Yahoo Finance JP + Google News JP (key-free RSS).",
  hk: "HKEXnews announcement search is connected (unofficial page API; may change). HKEX DI is available but disabled by default (legacy archive 2003-2017). Yahoo Finance HK + Google News HK via key-free RSS. Universe cache can backfill names. Community: Xueqiu (xueqiu) registered stub — xueqiu.com HTML is an Aliyun WAF JS-challenge shell and JSON APIs require xq_a_token (spike 2026-08-11); collect() empty until a stable public feed exists. Finnhub is US-only.",
  cn: "A-share companies are added as unmapped (no SEC mapping). Community: Xueqiu (xueqiu) registered stub — xueqiu.com HTML is an Aliyun WAF JS-challenge shell and JSON APIs require xq_a_token (spike 2026-08-11); collect() empty until a stable public feed exists.",
  kr: "Korea companies resolve via OpenDART when configured; otherwise add as unmapped. News: Naver Finance + Yahoo Finance KR + Google News KR (key-free RSS).",
  uk: "UK companies resolve via Companies House when configured. News: Yahoo Finance UK + Google News UK (key-free RSS).",
  tw: "TWSE (listed) and TPEx (OTC) OpenAPI material-information are connected (key-free; not a paid MOPS push). 興櫃 disclosure is not wired. Yahoo Finance TW and Google News (TW) via key-free RSS. Universe cache can backfill names/board. Finnhub is US-only.",
  ca: "CA market (partial — not a full Canadian stack): root tickers strip .TO/.TSX/.V/.TSXV/.CN/.NE/.NEO; board backfills from ca_universe (TSX/TSXV) or typed suffix when cold. Universe does NOT cover CSE/NEO directories. Disclosure is NOT wired: SEDAR+/CSE/NEO filings unwired. News: Yahoo Finance CA + Google News CA. Community: CEO.ca (ceoca_ca) via key-free JSON API (Toronto day filter; channel page URL only; ~50 spiels/page). Finnhub is US-only.",
  au: "AU market: root tickers strip .AX/.ASX. ASX announcements via key-free research API (latest 5 per company; may change). Universe backfills names/board. News: Yahoo Finance AU + Google News AU. Community: Stockhead (stockhead_au) LIVE WordPress search RSS; HotCopper (hotcopper_au) registered stub — public boards return HTTP 403 Cloudflare to bots; collect() empty until a stable public feed exists. Finnhub is US-only.",
  be: "BE market (Euronext Brussels): root tickers strip .BR/.BRU/.EBR; Belgian ISINs kept as-is. Disclosure: FSMA STORI (official key-free Belgian central storage of regulated information) is wired and matches by BE ISIN or company name - mnemonic tickers get an ISIN/name from the BE universe cache (BE-2) once refreshed, or a BE ISIN typed directly; tickers without an identity are skipped honestly. Second disclosure source NOT wired (BE-4 re-verified 2026-08-10): Euronext Brussels announcements are HTML-only pages keyed by company node ids (no RSS/JSON export) and the key-free EQS News API returns zero Belgian records; paid feeds (Euronext Web Services, FinancialReports.eu) are excluded. Universe: be_universe caches free Euronext Brussels directories (Euronext Brussels / Growth Brussels / Access Brussels plus multi-venue Brussels rows; not a full broker universe) and backfills name/board/ISIN for add-company and STORI matching. News: Yahoo Finance BE (region=BE, fr-BE + en-US merged; identical titles stay single-language; .BR at request time) and Google News BE (hl=en-BE&gl=BE&ceid=BE:en) via key-free RSS; may be loosely related and break without notice. Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE): FSMA STORI filings pair on their stable STORI document id; Yahoo BE and Google News BE news pairs on ticker + Brussels day + normalized title. BE companies are added as unmapped. Finnhub is US-only and never queried for BE.",
  fr: "FR market (Euronext Paris): root tickers strip .PA/.PAR; French ISINs kept as-is. AMF OAM disclosure + Euronext Paris/Growth/Access universe cache + Yahoo/Google FR news. Companies stay unmapped. Finnhub is US-only.",
  de: "DE market (Xetra / Deutsche Börse Cash Market): the German ETF's deepening stays on market=de (no separate etf market code; not Eurex derivatives). Root tickers strip .DE/.XETRA/.XE/.F; German ISINs kept as-is. EQS News (DGAP) disclosure via key-free JSON (needs ISIN from universe or typed ISIN; EQS returns no records for sampled Xetra ETF ISINs - ETF disclosure not deepened). Universe cache includes Xetra CS + ETF + ETN + ETC (instrument_type stored; live ~1,422 CS / 3,082 ETF / 385 ETN / 205 ETC) and backfills name/board/ISIN. News: Yahoo DE + Google News DE shared by stocks and ETFs (.DE at request time; ETF feeds may be empty/loosely related). Unternehmensregister/BaFin HTML not wired. Companies stay unmapped. Finnhub is US-only.",
  nl: "NL market (Euronext Amsterdam): root tickers strip .AS/.AMS/.AEA; Dutch ISINs kept as-is. EQS News (NL) disclosure via key-free JSON by Dutch ISIN (partial coverage; not AFM official; second disclosure source not wired — AFM/Euronext have no free JSON). Universe cache backfills names/board/ISIN from Euronext Amsterdam directories. News: Yahoo Finance NL + Google News NL. Companies stay unmapped. Finnhub is US-only and never queried for NL.",
  it: "IT market (Euronext Milan): root tickers strip .MI/.MIL/.BIT; Italian ISINs kept as-is. EQS News (IT) disclosure via key-free JSON by Italian ISIN (partial coverage; not Consob official; second disclosure source not wired — Consob captcha/Borsa Italiana/Euronext have no free JSON). Universe cache backfills names/board/ISIN from Euronext Milan directories. News: Yahoo Finance IT + Google News IT. Companies stay unmapped. Finnhub is US-only and never queried for IT.",
  es: "ES market (BME / Bolsa de Madrid): root tickers strip .MC/.MAD/.BME; Spanish ISINs kept as-is. Disclosure: CNMV official RSS (IP + OIR) plus BME relevant-facts JSON (official, key-free, same CNMV registration numbers; ~31-day range cap). The ES universe cache (BME official API: SIBE/Floor/Latibex + BME Growth/ScaleUp equities; funds excluded) backfills names/board/ISIN and drives disclosure matching. News: Yahoo Finance ES + Google News ES (key-free RSS; loosely related possible; .MC at request time). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE). ES companies are added as unmapped. Finnhub is US-only and never queried for ES.",
  sg: "SG market (SGX): root tickers strip .SI/.SG; Singapore ISINs kept as-is; SGX codes vary in length (no fixed width). Disclosure is NOT wired (SG-1/SG-4 spikes: SGX announcements are a JS SPA; api.sgx.com returns 403; legacy infopub SGXNet JSON retired; links.sgx.com has deep links only; no paid SGX DataLink). The SG universe is a boundary stub (no stable free SGX directory; refresh raises; cache shape reserved). News: Yahoo Finance SG + Google News SG (key-free RSS; loosely related possible; .SI at request time). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; filings not annotated since no disclosure source). SG companies are added as unmapped. Finnhub is US-only and never queried for SG.",
  ch: "CH market (SIX Swiss Exchange): root tickers strip .SW/.SWX/.S; Swiss ISINs kept as-is. Disclosure: EQS News (CH) via key-free JSON by Swiss ISIN (unofficial; partial coverage - Roche/UBS yes, some ISINs empty; NOT SIX/FINMA official; SIX official notices are a JS SPA and equity-issuer news is paid Exfeed). Needs ISIN from the CH universe cache or a typed Swiss ISIN. The CH universe is a boundary stub (no stable free SIX directory; refresh raises; cache shape reserved). News: Yahoo Finance CH + Google News CH (key-free RSS; German-Swiss; loosely related possible; .SW at request time). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; eqs_ch filings pair on EQS id). CH companies are added as unmapped. Finnhub is US-only and never queried for CH.",
  pl: "PL market (GPW / Warsaw): root tickers strip .WA/.WSE/.GPW; Polish ISINs kept as-is. Disclosure: official GPW ESPI/EBI reports page (www.gpw.pl/komunikaty; key-free HTML list filtered by Polish ISIN from the PL universe; stable geru_id; espi.gpw.pl itself unreachable; EQS empty for PL ISINs; KNF no per-issuer feed; no paid GPW data products). Universe: official GPW HTML directories (GPW Main Market ~400 + NewConnect ~350; breadth only, never in feed; backfills name/board/ISIN on add-company; GPW hosts drop TLS intermittently so refresh may need a retry). News: Yahoo Finance PL + Google News PL (key-free RSS; .WA at request time; loosely related possible - a PKO.WA Google query can include football items). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; gpw_espi pairs on geru_id; news pairs on Warsaw day + title). PL companies are added as unmapped. Finnhub is US-only and never queried for PL.",
  se: "SE market (Nasdaq Stockholm / First North Sweden): root tickers strip .ST/.STO/.OMX; share-class suffixes like -B/-A are kept (ERIC-B stays ERIC-B); Swedish ISINs kept as-is. Disclosure is NOT wired (SE-1 spike + SE-4 re-check: FI publiceringsklient is insider-transactions only; Nasdaq Nordic company news is a Drupal SPA with no public JSON; old OMX disclosure search HTTP 500; EQS empty for sampled Swedish ISINs; legacy Hugin host has no stable public API; no paid Nasdaq data products). Universe: boundary stub (SE-2 spike B2: Nasdaq Stockholm/First North directories are JS screener SPAs without a reachable public JSON route; refresh raises SeUniverseError; no OMXS30 seed). News: Yahoo Finance SE + Google News SE (key-free RSS; .ST at request time; loosely related possible - an ERIC-B.ST Google query can include football items). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on Stockholm day + title; filings never annotated - no disclosure source). SE companies are added as unmapped. Finnhub is US-only and never queried for SE.",
  aq: "AQ market (Aquis Stock Exchange, AQSE): root tickers strip .AQ; AQSE mnemonics kept as-is; ISINs (GB/IE/other) kept as-is. Companies are added as unmapped (no SEC mapping). Disclosure is NOT wired (AQ-1 A3 / AQ-4 D2: official aquis.eu pages sit behind a Vercel bot challenge for non-browser clients; no key-free official JSON/RSS; no second source; LSE/Investegate/Companies House are NOT used as Aquis substitutes). Universe: partial unofficial ticker.app AQSE mirror backfills names/exchange/ISIN (not verified complete). News: Yahoo Finance AQ + Google News AQ (key-free RSS; .AQ at request time; loosely related possible). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on London day + title; filings never annotated - no disclosure source). Finnhub is US-only and never queried for AQ.",
  cxe: "CXE market (Cboe Europe equities, CXE/BXE books): first Alternative European Equities venue only - NOT the whole package (Turquoise and other MTFs are deferred; no virtual aee/eu code). Cboe symbols are kept uppercased (AZNl -> AZNL); .CXE/.BXE suffixes stripped at add time; ISINs kept as-is. Companies are added as unmapped (no SEC mapping). Disclosure is NOT wired (AEE-1 A3 / AEE-4: Cboe Europe is an MTF without an independent issuer OAM; venue symbol/trade pages are not issuer disclosures; no second source). Universe: official Cboe Europe Symbol Data CSVs for CXE+BXE backfill names/exchange/venue (~5.3k + ~6.5k symbols live 2026-08-10; no ISIN column). News: Google News (CXE) via key-free RSS (queries company name from universe, else Cboe symbol; no Yahoo suffix exists for Cboe Europe, so no yahoo_cxe). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on London day + title; filings never annotated - no disclosure source). Finnhub is US-only and never queried for CXE.",
  emf: "EMF market (European Mutual Funds / UCITS): ISIN-first identifiers (12-character fund ISINs kept as-is; .F/.MF fund-data suffixes stripped at add time). Funds are added as unmapped (no SEC mapping). This is NOT the German ETF (market=de) or Cboe Europe (market=cxe) universe, and not Eurex derivatives. Disclosure is NOT wired (EMF-1 A3 / EMF-4: ESMA exposes only AIFMD fund reports without ISINs and no UCITS register; KIID/PRIIPs live on manager sites; no stock OAM re-mapped; no second source). Universe: boundary stub (EMF-2 B2: no stable free ISIN-bearing European fund directory; refresh raises EmfUniverseError; no fund seed). News: Google News (EMF) via key-free RSS (fund name from a manually placed cache, else typed ISIN - usually sparse; no Yahoo suffix exists for European funds, so no yahoo_emf). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on Luxembourg day + title; filings never annotated - no disclosure source). Finnhub is US-only and never queried for EMF.",
  trq: "TRQ market (Turquoise, LSEG MTF): second Alternative European Equities venue after Cboe Europe (market=cxe) - NOT the whole package (other MTFs deferred) and NOT AQSE/LSE/Eurex. Common symbols are kept uppercased (AZN stays AZN); .TRQ/.TRQX/.TQEX suffixes stripped at add time; ISINs kept as-is. Companies are added as unmapped (no SEC mapping). Disclosure is NOT wired (TRQ-1 A3 / TRQ-4: MTF without issuer OAM; re-test 2026-08-11: turquoise.com parked, turquoise.eu is an unrelated company, tradeturquoise.com redirects to a JS-only LSE SPA, old TRQX/TQEX reference-file CSVs 404; no stock OAM re-mapped; no second source). Universe: boundary stub (TRQ-2 B2: no stable free Turquoise directory; refresh raises TrqUniverseError; no CXE CSV reuse; no seed). News: Google News (TRQ) via key-free RSS (company name from a manually placed cache, else Turquoise symbol; no Yahoo suffix exists for Turquoise, so no yahoo_trq). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on London day + title; filings never annotated - no disclosure source). Finnhub is US-only and never queried for TRQ.",
  eux: "EUX market (Eurex Core, derivatives exchange): futures/options product codes are kept uppercased (FDAX stays FDAX); .EUX suffixes stripped at add time; ISINs kept as-is. Products are added as unmapped (no SEC mapping). This is NOT Xetra stocks/ETFs (market=de), NOT AEE (cxe/trq), NOT AQSE/Mutual Funds/Display Bundle. Disclosure is NOT wired (EUX-1 A3 / EUX-4: Eurex circulars are a JS search surface without per-product rows/JSON; derivatives have no issuer OAM; no stock OAM re-mapped; no second source; Display Bundle not wired). Universe: official Eurex product list CSV backfills product name/ISIN/group (~2,997 products live 2026-08-11; product-level; never in feed; TLS intermittent). News: Google News (EUX) via key-free RSS (product name from universe, else Eurex product code; hl=de&gl=DE; no Yahoo suffix exists for Eurex derivatives, so no yahoo_eux). Feed soft-dedupe is display-only (Also seen on; all rows kept; KR_FEED_SOFT_DEDUPE; news pairs on Berlin day + title; filings never annotated - no disclosure source). Finnhub is US-only and never queried for EUX.",
};

const MARKET_HINTS_ZH = {
  us: "美国候选公司来自本地官方 SEC 映射。新闻：Finnhub（需要 FINNHUB_API_KEY）+ Yahoo Finance US + Google News US（免 key RSS）。社区：Seeking Alpha（seeking_alpha）通过公开 combined RSS（/api/sa/combined/{SYMBOL}.xml）LIVE —— 文章/快讯元数据，按纽约日过滤；HTML 代码/论坛/评论页返回 PerimeterX 403，超出范围。Substack（substack）LIVE 刊物白名单 RSS（https://{publication}/feed）—— 通讯稿文章/快讯元数据，纽约日过滤，无结构化 ticker 绑定；白名单：noahpinion.blog、notboring.co、astralcodexten.com、paulkrugman.substack.com、oneusefulthing.org。Yellowbrick Investing（yellowbrick）注册 stub —— ybrick.co 死链，joinyellowbrick.com 404（spike 2026-08-11）；collect() 为空。X（x_community）注册 stub —— 无公开免登录 ticker 接口；官方 API 需要付费 Bearer（未接线）；HTML/聚合抓取超出范围（spike 2026-08-11）；collect() 为空。Value Investors Club（vic）注册 stub —— 无公开 RSS/JSON；/ideas?symbol= 不过滤；访客访问仅限 45 天延迟；会员/HTML 抓取超出范围（spike 2026-08-11）；collect() 为空。",
  jp: "日本公司以未映射方式添加。使用“添加代码”输入本地代码；EDINET/TDnet 按 market=jp 采集。新闻：Yahoo Finance JP + Google News JP（免 key RSS）。",
  hk: "HKEXnews 公告搜索已连接（非官方页面 API；可能变更）。HKEX DI 可用但默认禁用（旧归档 2003-2017）。Yahoo Finance HK + Google News HK 走免 key RSS。宇宙缓存可回填名称。社区：雪球（xueqiu）注册 stub —— xueqiu.com HTML 是阿里云 WAF JS 挑战壳，JSON API 需要 xq_a_token（spike 2026-08-11）；在稳定公开 feed 出现前 collect() 为空。Finnhub 仅限美国。",
  cn: "A 股公司以未映射方式添加（无 SEC 映射）。社区：雪球（xueqiu）注册 stub —— xueqiu.com HTML 是阿里云 WAF JS 挑战壳，JSON API 需要 xq_a_token（spike 2026-08-11）；在稳定公开 feed 出现前 collect() 为空。",
  kr: "韩国公司配置 OpenDART 时解析；否则以未映射方式添加。新闻：Naver Finance + Yahoo Finance KR + Google News KR（免 key RSS）。",
  uk: "英国公司配置 Companies House 时解析。新闻：Yahoo Finance UK + Google News UK（免 key RSS）。",
  tw: "TWSE（上市）与 TPEx（上柜）OpenAPI 重大信息已连接（免 key；不是付费 MOPS 推送）。興櫃披露未接线。Yahoo Finance TW 和 Google News (TW) 走免 key RSS。宇宙缓存可回填名称/板别。Finnhub 仅限美国。",
  ca: "CA 市场（部分，非完整加拿大栈）：根代码去除 .TO/.TSX/.V/.TSXV/.CN/.NE/.NEO；板别在缓存为空时从 ca_universe（TSX/TSXV）或输入后缀回填。宇宙不覆盖 CSE/NEO 目录。披露未接线：SEDAR+/CSE/NEO 申报未接线。新闻：Yahoo Finance CA + Google News CA。社区：CEO.ca（ceoca_ca）走免 key JSON API（多伦多日过滤；仅频道页 URL；约 50 条/页）。Finnhub 仅限美国。",
  au: "AU 市场：根代码去除 .AX/.ASX。ASX 公告走免 key 研究 API（每公司最近 5 条；可能变更）。宇宙回填名称/板别。新闻：Yahoo Finance AU + Google News AU。社区：Stockhead（stockhead_au）LIVE WordPress 搜索 RSS；HotCopper（hotcopper_au）注册 stub —— 公开板块对机器人返回 HTTP 403 Cloudflare；在稳定公开 feed 出现前 collect() 为空。Finnhub 仅限美国。",
  be: "BE 市场（Euronext Brussels）：根代码去除 .BR/.BRU/.EBR；比利时 ISIN 保持原样。披露：FSMA STORI（官方免 key 比利时受监管信息集中存储）已接线，按 BE ISIN 或公司名匹配 —— 助记代码在 BE 宇宙缓存（BE-2）刷新后获取 ISIN/名称，或直接输入 BE ISIN；无身份信息的代码被诚实跳过。第二个披露源未接线（BE-4 于 2026-08-10 复核）：Euronext Brussels 公告是仅 HTML 页面、按公司节点 id 索引（无 RSS/JSON 导出），免 key EQS News API 返回零条比利时记录；付费订阅（Euronext Web Services、FinancialReports.eu）被排除。宇宙：be_universe 缓存免 key Euronext Brussels 目录并回填名称/板别/ISIN。新闻：Yahoo Finance BE（region=BE，fr-BE + en-US 合并；相同标题保持单语言；请求时 .BR）和 Google News BE（hl=en-BE&gl=BE&ceid=BE:en）走免 key RSS；可能松散相关且可能无预警失效。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE）：FSMA STORI 申报按稳定 STORI 文档 id 配对；Yahoo BE 与 Google News BE 按 ticker + 布鲁塞尔日 + 归一化标题配对。BE 公司以未映射方式添加。Finnhub 仅限美国且从不查询 BE。",
  fr: "FR 市场（Euronext Paris）：根代码去除 .PA/.PAR；法国 ISIN 保持原样。AMF OAM 披露 + Euronext Paris/Growth/Access 宇宙缓存 + Yahoo/Google FR 新闻。公司保持未映射。Finnhub 仅限美国。",
  de: "DE 市场（Xetra / Deutsche Börse Cash Market）：德国 ETF 的深化保持在 market=de（无单独 etf 市场代码；非 Eurex 衍生品）。根代码去除 .DE/.XETRA/.XE/.F；德国 ISIN 保持原样。EQS News (DGAP) 披露走免 key JSON（需要来自宇宙或输入的 ISIN；EQS 对抽样 Xetra ETF ISIN 返回零记录 —— ETF 披露未深化）。宇宙缓存包含 Xetra CS + ETF + ETN + ETC（记录 instrument_type；实时约 1,422 CS / 3,082 ETF / 385 ETN / 205 ETC）并回填名称/板别/ISIN。新闻：Yahoo DE + Google News DE 由股票和 ETF 共享（请求时 .DE；ETF feed 可能为空/松散相关）。Unternehmensregister/BaFin HTML 未接线。公司保持未映射。Finnhub 仅限美国。",
  nl: "NL 市场（Euronext Amsterdam）：根代码去除 .AS/.AMS/.AEA；荷兰 ISIN 保持原样。EQS News (NL) 披露走免 key JSON 按荷兰 ISIN（部分覆盖；非 AFM 官方；第二个披露源未接线 —— AFM/Euronext 无免费 JSON）。宇宙缓存回填名称/板别/ISIN。新闻：Yahoo Finance NL + Google News NL。公司保持未映射。Finnhub 仅限美国且从不查询 NL。",
  it: "IT 市场（Euronext Milan）：根代码去除 .MI/.MIL/.BIT；意大利 ISIN 保持原样。EQS News (IT) 披露走免 key JSON 按意大利 ISIN（部分覆盖；非 Consob 官方；第二个披露源未接线 —— Consob 验证码/Borsa Italiana/Euronext 无免费 JSON）。宇宙缓存回填名称/板别/ISIN。新闻：Yahoo Finance IT + Google News IT。公司保持未映射。Finnhub 仅限美国且从不查询 IT。",
  es: "ES 市场（BME / Bolsa de Madrid）：根代码去除 .MC/.MAD/.BME；西班牙 ISIN 保持原样。披露：CNMV 官方 RSS（IP + OIR）加 BME 重大事实 JSON（官方、免 key、同一 CNMV 注册号；约 31 天范围上限）。ES 宇宙缓存（BME 官方 API：SIBE/Floor/Latibex + BME Growth/ScaleUp 股票；基金排除）回填名称/板别/ISIN 并驱动披露匹配。新闻：Yahoo Finance ES + Google News ES（免 key RSS；可能松散相关；请求时 .MC）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE）。ES 公司以未映射方式添加。Finnhub 仅限美国且从不查询 ES。",
  sg: "SG 市场（SGX）：根代码去除 .SI/.SG；新加坡 ISIN 保持原样；SGX 代码长度不一（无固定宽度）。披露未接线（SG-1/SG-4 spikes：SGX 公告是 JS SPA；api.sgx.com 返回 403；旧 infopub SGXNet JSON 已退役；links.sgx.com 只有深链接；无付费 SGX DataLink）。SG 宇宙是边界 stub（无稳定免费 SGX 目录；refresh 抛错；缓存形态预留）。新闻：Yahoo Finance SG + Google News SG（免 key RSS；可能松散相关；请求时 .SI）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；无披露源故 filing 不标注）。SG 公司以未映射方式添加。Finnhub 仅限美国且从不查询 SG。",
  ch: "CH 市场（SIX Swiss Exchange）：根代码去除 .SW/.SWX/.S；瑞士 ISIN 保持原样。披露：EQS News (CH) 走免 key JSON 按瑞士 ISIN（非官方；部分覆盖 —— Roche/UBS 有，部分 ISIN 为空；非 SIX/FINMA 官方；SIX 官方公告是 JS SPA，股票发行人新闻是付费 Exfeed）。需要来自 CH 宇宙缓存或输入的瑞士 ISIN。CH 宇宙是边界 stub（无稳定免费 SIX 目录；refresh 抛错；缓存形态预留）。新闻：Yahoo Finance CH + Google News CH（免 key RSS；德语区；可能松散相关；请求时 .SW）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；eqs_ch 申报按 EQS id 配对）。CH 公司以未映射方式添加。Finnhub 仅限美国且从不查询 CH。",
  pl: "PL 市场（GPW / Warsaw）：根代码去除 .WA/.WSE/.GPW；波兰 ISIN 保持原样。披露：官方 GPW ESPI/EBI 报告页（www.gpw.pl/komunikaty；免 key HTML 列表，按来自 PL 宇宙的波兰 ISIN 过滤；稳定 geru_id；espi.gpw.pl 本身不可达；EQS 对 PL ISIN 为空；KNF 无逐发行人 feed；无付费 GPW 数据产品）。宇宙：官方 GPW HTML 目录（GPW 主板约 400 + NewConnect 约 350；仅广度，从不进入 feed；添加公司时回填名称/板别/ISIN；GPW 主机间歇性 TLS 中断，刷新可能需要重试）。新闻：Yahoo Finance PL + Google News PL（免 key RSS；请求时 .WA；可能松散相关 —— PKO.WA 的 Google 查询可能包含足球条目）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；gpw_espi 按 geru_id 配对；新闻按华沙日 + 标题配对）。PL 公司以未映射方式添加。Finnhub 仅限美国且从不查询 PL。",
  se: "SE 市场（Nasdaq Stockholm / First North Sweden）：根代码去除 .ST/.STO/.OMX；份额类后缀如 -B/-A 保留（ERIC-B 保持 ERIC-B）；瑞典 ISIN 保持原样。披露未接线（SE-1 spike + SE-4 复核：FI publiceringsklient 仅限内幕交易；Nasdaq Nordic 公司新闻是 Drupal SPA 无公开 JSON；旧 OMX 披露搜索 HTTP 500；EQS 对抽样瑞典 ISIN 为空；旧 Hugin 主机无稳定公开 API；无付费 Nasdaq 数据产品）。宇宙：边界 stub（SE-2 spike B2：Nasdaq Stockholm/First North 目录是无可达公开 JSON 路径的 JS 筛选 SPA；refresh 抛 SeUniverseError；无 OMXS30 种子）。新闻：Yahoo Finance SE + Google News SE（免 key RSS；请求时 .ST；可能松散相关 —— ERIC-B.ST 的 Google 查询可能包含足球条目）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按斯德哥尔摩日 + 标题配对；无披露源故 filing 从不标注）。SE 公司以未映射方式添加。Finnhub 仅限美国且从不查询 SE。",
  aq: "AQ 市场（Aquis Stock Exchange, AQSE）：根代码去除 .AQ；AQSE 助记码保持原样；ISIN（GB/IE/其他）保持原样。公司以未映射方式添加（无 SEC 映射）。披露未接线（AQ-1 A3 / AQ-4 D2：官方 aquis.eu 页面位于 Vercel 机器人挑战之后，非浏览器客户端无法访问；无免 key 官方 JSON/RSS；无第二源；LSE/Investegate/Companies House 不作为 Aquis 替代）。宇宙：非官方 ticker.app AQSE 部分镜像回填名称/交易所/ISIN（未验证完整）。新闻：Yahoo Finance AQ + Google News AQ（免 key RSS；请求时 .AQ；可能松散相关）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按伦敦日 + 标题配对；无披露源故 filing 从不标注）。Finnhub 仅限美国且从不查询 AQ。",
  cxe: "CXE 市场（Cboe Europe 股票，CXE/BXE 订单簿）：仅第一个 Alternative European Equities 场所 —— 不是完整套餐（Turquoise 和其他 MTF 推迟；无虚拟 aee/eu 代码）。Cboe 代码保持大写（AZNl -> AZNL）；添加时去除 .CXE/.BXE 后缀；ISIN 保持原样。公司以未映射方式添加（无 SEC 映射）。披露未接线（AEE-1 A3 / AEE-4：Cboe Europe 是无独立发行人 OAM 的 MTF；场所代码/交易页不是发行人披露；无第二源）。宇宙：官方 Cboe Europe Symbol Data CSV 回填 CXE+BXE 名称/交易所/场所（实时约 5.3k + 6.5k 代码，2026-08-10；无 ISIN 列）。新闻：Google News (CXE) 走免 key RSS（查询来自宇宙的公司名，否则 Cboe 代码；Cboe Europe 无 Yahoo 后缀，故无 yahoo_cxe）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按伦敦日 + 标题配对；无披露源故 filing 从不标注）。Finnhub 仅限美国且从不查询 CXE。",
  emf: "EMF 市场（欧洲共同基金 / UCITS）：ISIN 优先标识（12 字符基金 ISIN 保持原样；添加时去除 .F/.MF 基金数据后缀）。基金以未映射方式添加（无 SEC 映射）。这不是德国 ETF（market=de）或 Cboe Europe（market=cxe）宇宙，也不是 Eurex 衍生品。披露未接线（EMF-1 A3 / EMF-4：ESMA 仅公开无 ISIN 的 AIFMD 基金报告且无 UCITS 登记；KIID/PRIIPs 在管理人站点；无股票 OAM 重映射；无第二源）。宇宙：边界 stub（EMF-2 B2：无稳定免费带 ISIN 的欧洲基金目录；refresh 抛 EmfUniverseError；无基金种子）。新闻：Google News (EMF) 走免 key RSS（基金名来自手工放置的缓存，否则输入 ISIN —— 通常稀疏；欧洲基金无 Yahoo 后缀，故无 yahoo_emf）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按卢森堡日 + 标题配对；无披露源故 filing 从不标注）。Finnhub 仅限美国且从不查询 EMF。",
  trq: "TRQ 市场（Turquoise, LSEG MTF）：Cboe Europe（market=cxe）之后的第二个 Alternative European Equities 场所 —— 不是完整套餐（其他 MTF 推迟）且不是 AQSE/LSE/Eurex。常见代码保持大写（AZN 保持 AZN）；添加时去除 .TRQ/.TRQX/.TQEX 后缀；ISIN 保持原样。公司以未映射方式添加（无 SEC 映射）。披露未接线（TRQ-1 A3 / TRQ-4：无发行人 OAM 的 MTF；2026-08-11 复测：turquoise.com 停用，turquoise.eu 是无关公司，tradeturquoise.com 重定向到仅 JS 的 LSE SPA，旧 TRQX/TQEX 参考文件 CSV 404；无股票 OAM 重映射；无第二源）。宇宙：边界 stub（TRQ-2 B2：无稳定免费 Turquoise 目录；refresh 抛 TrqUniverseError；不复用 CXE CSV；无种子）。新闻：Google News (TRQ) 走免 key RSS（公司名来自手工放置的缓存，否则 Turquoise 代码；Turquoise 无 Yahoo 后缀，故无 yahoo_trq）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按伦敦日 + 标题配对；无披露源故 filing 从不标注）。Finnhub 仅限美国且从不查询 TRQ。",
  eux: "EUX 市场（Eurex Core，衍生品交易所）：期货/期权产品代码保持大写（FDAX 保持 FDAX）；添加时去除 .EUX 后缀；ISIN 保持原样。产品以未映射方式添加（无 SEC 映射）。这不是 Xetra 股票/ETF（market=de），不是 AEE（cxe/trq），不是 AQSE/共同基金/Display Bundle。披露未接线（EUX-1 A3 / EUX-4：Eurex circulars 是无逐产品行/JSON 的 JS 搜索界面；衍生品无发行人 OAM；无股票 OAM 重映射；无第二源；Display Bundle 未接线）。宇宙：官方 Eurex 产品列表 CSV 回填产品名/ISIN/组（实时约 2,997 产品，2026-08-11；产品级；从不进入 feed；TLS 间歇性）。新闻：Google News (EUX) 走免 key RSS（产品名来自宇宙，否则 Eurex 产品代码；hl=de&gl=DE；Eurex 衍生品无 Yahoo 后缀，故无 yahoo_eux）。Feed 软去重仅用于展示（Also seen on；保留所有行；KR_FEED_SOFT_DEDUPE；新闻按柏林日 + 标题配对；无披露源故 filing 从不标注）。Finnhub 仅限美国且从不查询 EUX。",
};

function marketHint(market) {
  const table = lang === "zh-CN" ? MARKET_HINTS_ZH : MARKET_HINTS_EN;
  return table[market] || table.us;
}

function updateMarketHint() {
  const market = document.getElementById("market-select").value;
  document.getElementById("market-hint").textContent = marketHint(market);
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
      <button class="list-select" type="button"><strong>${esc(list.name)}</strong><span>${t("manage.companies_count", {count: list.company_count})}</span></button>
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
  document.getElementById("company-context").textContent = list ? `${list.name} · ${t("manage.companies_count", {count: companies.length})}` : t("manage.create_or_select_first");
  document.getElementById("company-table").innerHTML = companies.length ? `<div class="table-wrap"><table><thead><tr><th>${t("manage.company")}</th><th>${t("manage.ticker")}</th><th>${t("manage.exchange")}</th><th>${t("manage.region")}</th><th></th></tr></thead><tbody>${companies.map(company => `<tr><td>${esc(company.name)}</td><td>${esc(company.ticker)}</td><td>${esc(exchangeLabel(company.exchange))}</td><td>${regionForMarket(company.market)}</td><td><button class="text-button danger remove-company" data-ticker="${escAttr(company.ticker)}" data-market="${escAttr(company.market)}">${t("manage.remove")}</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty compact"><p>${t("manage.no_companies")}</p></div>`;
  document.querySelectorAll(".remove-company").forEach(button => button.addEventListener("click", () => removeCompany(button.dataset.ticker, button.dataset.market)));
}

async function searchCompanies(event) {
  event.preventDefault();
  if (!state.selectedList) { toast(t("manage.create_or_select_first"), true); return; }
  const market = document.getElementById("market-select").value;
  if (market !== "us") {
    toast(t("manage.non_us_markets"), true);
    return;
  }
  const target = document.getElementById("candidate-results"); target.innerHTML = `<p class="loading">${t("manage.searching_candidates")}</p>`;
  try {
    const data = await api(`/api/companies/search?q=${encodeURIComponent(document.getElementById("company-query").value.trim())}`);
    target.innerHTML = data.candidates.length ? `<div class="candidate-list">${data.candidates.map(candidate => `<article><div><strong>${esc(candidate.name)}</strong><p>${esc(candidate.ticker)} · ${esc(candidate.exchange)} · ${esc(candidate.region)}</p></div><button class="button add-candidate" data-ticker="${escAttr(candidate.ticker)}" data-market="${escAttr(candidate.market)}">${t("manage.confirm_add")}</button></article>`).join("")}</div>` : `<div class="empty compact"><p>${t("manage.no_matching_candidates")}</p></div>`;
    document.querySelectorAll(".add-candidate").forEach(button => button.addEventListener("click", () => addCandidate(button.dataset.ticker, button.dataset.market)));
  } catch (error) { target.innerHTML = errorState(t("manage.search_no_results"), error.message); }
}

async function addTickerDirect() {
  if (!state.selectedList) { toast(t("manage.create_or_select_first"), true); return; }
  const tickers = document.getElementById("company-query").value.trim();
  if (!tickers) { toast(t("manage.enter_ticker_first"), true); return; }
  const market = document.getElementById("market-select").value;
  try {
    const result = await api("/api/companies/batch", {method:"POST", body:JSON.stringify({tickers, lists:[state.selectedList], market})});
    const added = (result.added || []).map(row => row.ticker).join(", ") || tickers;
    toast(t("manage.added_market", {tickers: added, market}));
    document.getElementById("candidate-results").innerHTML = "";
    await reloadBootstrap();
    await refreshManagement();
  } catch (error) { toast(error.message, true); }
}

async function addCandidate(ticker, market) {
  try {
    await api("/api/companies/batch", {method:"POST", body:JSON.stringify({tickers:ticker, lists:[state.selectedList], market})});
    toast(t("manage.added", {ticker})); document.getElementById("candidate-results").innerHTML = ""; await reloadBootstrap(); await refreshManagement();
  } catch (error) { toast(error.message, true); }
}

async function removeCompany(ticker, market) {
  try { await api("/api/memberships/remove", {method:"POST", body:JSON.stringify({ticker, market, list:state.selectedList})}); toast(t("manage.removed", {ticker})); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

function renderSources(sources) {
  document.getElementById("source-grid").innerHTML = `<div class="source-grid">${sources.map(source => `<article class="source-card"><div class="source-card-head"><div><h3>${esc(source.provider)}</h3><p>${esc(source.type)} · ${source.regions.length ? source.regions.map(esc).join(", ") : t("manage.coverage_not_provided")}</p></div><span class="status ${escAttr(source.status)}">${statusLabel(source.status)}</span></div><dl><div><dt>${t("manage.enabled")}</dt><dd>${source.enabled ? t("manage.yes") : t("manage.no")}</dd></div><div><dt>${t("manage.latest_success")}</dt><dd>${source.latest_success ? formatDateTime(source.latest_success) : t("manage.none_recorded")}</dd></div><div><dt>${t("manage.latest_attempt")}</dt><dd>${source.latest_attempt ? formatDateTime(source.latest_attempt) : t("manage.none_recorded")}</dd></div></dl>${source.last_failure ? `<details><summary>${t("manage.failure_details")}</summary><p>${esc(source.last_failure)}</p></details>` : ""}</article>`).join("")}</div>`;
}

async function reloadBootstrap() { state.bootstrap = await api("/api/bootstrap"); }
function listOptions(selected) { return state.bootstrap.lists.map(list => `<option value="${escAttr(list.slug)}" ${list.slug === selected ? "selected" : ""}>${esc(list.name)}</option>`).join(""); }
function statusLabel(status) { const key = {connected:"status.connected", stale:"status.data_stale", not_connected:"status.not_connected", temporarily_unavailable:"status.failed", unavailable:"status.waiting_for_data"}[status]; return key ? t(key) : status; }
function regionForMarket(market) { const key = {us:"region.us", jp:"region.jp", hk:"region.hk", cn:"region.cn", kr:"region.kr", uk:"region.uk", tw:"region.tw", ca:"region.ca", au:"region.au", be:"region.be", fr:"region.fr", de:"region.de", nl:"region.nl", it:"region.it", es:"region.es", sg:"region.sg", ch:"region.ch", pl:"region.pl", se:"region.se", aq:"region.aq", cxe:"region.cxe", emf:"region.emf", trq:"region.trq", eux:"region.eux"}[market]; return key ? t(key) : t("common.unavailable"); }
function categoryLabel(type) { const key = {Filing:"cat.official_filings", News:"cat.news", Community:"cat.community"}[type]; return key ? t(key) : type; }
function exchangeLabel(exchange) { return exchange && exchange !== "Unavailable" ? exchange : t("common.unavailable"); }
function formatDay(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"full", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatShortDay(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"medium", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatRange(start, end) { return start === end ? formatDay(start) : `${formatShortDay(start)} – ${formatShortDay(end)}`; }
function formatTime(value) { return new Intl.DateTimeFormat(localeFor(), {hour:"numeric", minute:"2-digit", timeZone:"Asia/Shanghai", timeZoneName:"short"}).format(new Date(value)); }
function formatDateTime(value) { return new Intl.DateTimeFormat(localeFor(), {dateStyle:"medium", timeStyle:"short", timeZone:"America/New_York"}).format(new Date(value)) + " ET"; }
function errorState(title, message) { return `<div class="empty error"><h2>${esc(title)}</h2><p>${esc(message)}</p></div>`; }
async function api(url, options={}) { const response = await fetch(url, {headers:{"Content-Type":"application/json"}, ...options}); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || t("common.request_failed_status", {status: response.status})); return payload; }
function toast(message, error=false) { const node=document.createElement("div"); node.className=`toast ${error?"error":""}`; node.textContent=message; document.getElementById("toast-region").appendChild(node); setTimeout(()=>node.remove(),4000); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
function escAttr(value) { return esc(value); }
function safeUrl(value) { try { const url = new URL(String(value)); return ["http:", "https:"].includes(url.protocol) ? url.href : "#"; } catch (_) { return "#"; } }
function renderFatal(error) { document.getElementById("page").innerHTML = errorState(t("common.workspace_failed"), error.message); }
