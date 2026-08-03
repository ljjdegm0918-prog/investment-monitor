"use strict";

const state = {
  view: document.body.dataset.view,
  path: document.body.dataset.path,
  bootstrap: null,
  filters: {},
  currentFeed: null,
  controller: null,
};

const listLabels = { holdings: "Holdings", planned: "Planned Purchases", watchlist: "Watchlist" };
const viewTitles = {
  today: "Today", information: "All Information", search: "Search",
  activity: "Activity & Logs", sources: "Data Sources", settings: "Settings",
  holdings: "Holdings", planned: "Planned Purchases", watchlist: "Watchlist",
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  document.getElementById("mobile-menu").addEventListener("click", event => {
    const open = document.querySelector(".sidebar").classList.toggle("open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });
  document.getElementById("global-search").addEventListener("submit", event => {
    event.preventDefault();
    const q = document.getElementById("global-search-input").value.trim();
    location.href = `/search${q ? `?q=${encodeURIComponent(q)}` : ""}`;
  });
  try {
    state.bootstrap = await api("/api/bootstrap");
    renderShell();
    await renderPage();
  } catch (error) {
    renderFatal(error);
  }
}

function renderShell() {
  const b = state.bootstrap;
  document.getElementById("topbar-title").textContent = viewTitles[state.view] || "Investment Monitor";
  document.getElementById("current-date").textContent = `${b.display_date} · ET`;
  const sec = b.sources.find(source => source.type === "Filings");
  const status = document.getElementById("top-source-status");
  status.textContent = sec.status === "connected" ? "SEC Up to date" : sec.status === "stale" ? "SEC Data stale" : "SEC Unavailable";
  status.className = `status-line ${sec.status === "connected" ? "connected" : sec.status === "stale" ? "stale" : "failed"}`;
  const listBySlug = Object.fromEntries(b.lists.map(list => [list.slug, list]));
  const nav = [
    ["OVERVIEW", [["/today","◷","Today"],["/information","▤","All Information"]]],
    ["MY LISTS", [["/lists/holdings","▣","Holdings",listBySlug.holdings.unread_count],["/lists/planned","◫","Planned Purchases",listBySlug.planned.unread_count],["/lists/watchlist","◉","Watchlist",listBySlug.watchlist.unread_count]]],
    ["TOOLS", [["/search","⌕","Search"],["/activity","↶","Activity & Logs"]]],
    ["SYSTEM", [["/sources","◫","Data Sources"],["/settings","⚙","Settings"]]],
  ];
  document.getElementById("sidebar-nav").innerHTML = nav.map(([heading, links]) => `
    <section class="nav-section"><h2 class="nav-heading">${heading}</h2>
      ${links.map(([href,icon,label,count]) => `<a class="nav-link ${isActive(href) ? "active" : ""}" href="${href}" aria-label="${label}${count !== undefined ? `, ${count} unread` : ""}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span>${count !== undefined ? `<span class="nav-count" aria-hidden="true">${count}</span>` : ""}</a>`).join("")}
    </section>`).join("");
}

function isActive(href) {
  return state.path === href || (href === "/today" && state.path === "/");
}

async function renderPage() {
  if (["today","information","search","holdings","planned","watchlist"].includes(state.view)) return renderInformationPage();
  if (state.view === "activity") return renderActivity();
  if (state.view === "sources") return renderSources();
  if (state.view === "settings") return renderSettings();
}

async function renderInformationPage() {
  const isToday = state.view === "today";
  const isList = ["holdings","planned","watchlist"].includes(state.view);
  const isSearch = state.view === "search";
  const title = viewTitles[state.view];
  const companies = isList ? state.bootstrap.companies.filter(company => company.list_slugs.includes(state.view)) : state.bootstrap.companies;
  const currentList = isList ? state.bootstrap.lists.find(list => list.slug === state.view) : null;
  const params = new URLSearchParams(location.search);
  state.filters = {
    list: isList ? state.view : params.get("list") || "",
    ticker: params.get("ticker") || "",
    type: params.get("type") || "all",
    form: params.get("form") || "",
    start_date: isToday ? state.bootstrap.selected_date : params.get("start_date") || "",
    end_date: isToday ? state.bootstrap.selected_date : params.get("end_date") || "",
    read: params.get("read") || "all",
    amendment: params.get("amendment") || "all",
    q: isSearch ? params.get("q") || "" : "",
    page: Number(params.get("page") || 1),
    page_size: state.bootstrap.settings.page_size,
  };
  const companyCount = companies.length;
  document.getElementById("page").innerHTML = `
    <header class="page-header"><div><h1>${title}</h1><p>${isToday ? "Updates across your lists, grouped by filing acceptance time in Eastern Time." : isSearch ? "Metadata search across information already collected and stored." : isList ? `${companyCount} ${companyCount === 1 ? "company" : "companies"} · ${currentList.unread_count} unread items` : "Historical information across every company in at least one list."}</p></div>${isList ? `<button class="button primary" id="toggle-add">+ Add companies</button>` : ""}</header>
    ${isToday ? summaryCards() : ""}
    ${isSearch ? `<div class="notice"><strong>Metadata search only.</strong> Filing bodies have not been downloaded or full-text indexed.</div>` : ""}
    ${isList ? addCompanyPanel() : ""}
    <section class="panel" aria-label="Information feed">
      ${filterBar(companies, { advanced: !isToday })}
      <div id="feed-content"><div class="loading-state" role="status"><span class="spinner"></span> Loading information…</div></div>
    </section>
    ${isList ? companyManagement(companies) : ""}`;
  bindFeedControls();
  if (isList) bindListControls();
  await loadFeed();
}

function summaryCards() {
  const c = state.bootstrap.counts;
  return `<div class="summary-grid">
    ${summaryCard("▦", c.companies, "followed companies")}
    ${summaryCard("✉", c.unread, "unread items")}
    ${summaryCard("▤", c.filings, "filings for selected date")}
  </div>`;
}
function summaryCard(icon, number, label) { return `<div class="summary-card"><span class="summary-icon" aria-hidden="true">${icon}</span><div><div class="summary-number">${number}</div><div class="summary-label">${label}</div></div></div>`; }

function filterBar(companies, options) {
  const types = [["all","All"],["filings","Filings"],["news","News"],["community","Community"]];
  const searchInput = state.view === "search" ? `<div class="filter-field" style="min-width:260px"><label for="metadata-search">Metadata search</label><input id="metadata-search" value="${esc(state.filters.q)}" placeholder="Ticker, company, title, form, accession"></div>` : "";
  return `<div class="filter-bar">
    ${searchInput}
    <div class="type-tabs" role="group" aria-label="Information type">${types.map(([value,label]) => `<button class="tab ${state.filters.type === value ? "active" : ""}" type="button" data-filter-type="${value}">${label}</button>`).join("")}</div>
    <div class="company-chips" role="group" aria-label="Company"><button class="chip ${!state.filters.ticker ? "active" : ""}" data-ticker="" type="button">All Companies</button>${companies.map(company => `<button class="chip ${state.filters.ticker === company.ticker ? "active" : ""}" data-ticker="${company.ticker}" type="button">${company.ticker}</button>`).join("")}</div>
    ${options.advanced ? advancedFilters() : ""}
    <button class="button link" id="clear-filters" type="button">Clear all filters</button>
  </div><div class="results-toolbar"><span id="result-count">Loading results…</span><button class="button link" id="mark-all" type="button">Mark all in scope as read</button></div>`;
}

function advancedFilters() {
  return `<div class="filter-field"><label for="form-filter">SEC form</label><input id="form-filter" value="${esc(state.filters.form)}" placeholder="10-K, 8-K…"></div>
    <div class="filter-field"><label for="start-date">Start date</label><input id="start-date" type="date" value="${state.filters.start_date}"></div>
    <div class="filter-field"><label for="end-date">End date</label><input id="end-date" type="date" value="${state.filters.end_date}"></div>
    <div class="filter-field"><label for="read-filter">Read state</label><select id="read-filter"><option value="all">All</option><option value="unread" ${state.filters.read === "unread" ? "selected" : ""}>Unread</option><option value="read" ${state.filters.read === "read" ? "selected" : ""}>Read</option></select></div>
    <div class="filter-field"><label for="amendment-filter">Amendment</label><select id="amendment-filter"><option value="all">All</option><option value="no" ${state.filters.amendment === "no" ? "selected" : ""}>Original only</option><option value="yes" ${state.filters.amendment === "yes" ? "selected" : ""}>Amendments only</option></select></div>`;
}

function addCompanyPanel() {
  return `<section class="panel add-panel" id="add-panel" hidden><form class="add-form" id="add-form"><div class="filter-field"><label for="ticker-input">Ticker symbols</label><textarea id="ticker-input" placeholder="AAPL, MSFT NVDA&#10;One or many tickers"></textarea></div><div class="filter-field"><label>Destination lists</label><div class="checkboxes">${state.bootstrap.lists.map(list => `<label><input type="checkbox" name="destination" value="${list.slug}" ${list.slug === state.view ? "checked" : ""}> ${list.name}</label>`).join("")}</div></div><button class="button primary" type="submit">Resolve and add</button></form><div id="batch-result"></div></section>`;
}

function companyManagement(companies) {
  return `<section class="panel" style="margin-top:16px"><div class="results-toolbar"><strong>Companies in ${listLabels[state.view]}</strong><span>Membership changes never delete historical information.</span></div><div style="overflow:auto"><table class="company-table"><thead><tr><th>Ticker</th><th>Company</th><th>Exchange</th><th>CIK</th><th>Lists</th><th>Actions</th></tr></thead><tbody>${companies.length ? companies.map(company => `<tr><td><strong>${company.ticker}</strong></td><td>${esc(company.name)}</td><td>${esc(company.exchange || "Unavailable")}</td><td>${esc(company.cik || "Unmapped")}</td><td>${company.list_slugs.map(slug => badge(slug)).join("")}</td><td><button class="button link remove-current" data-ticker="${company.ticker}">Remove from this list</button><button class="button link remove-all" data-ticker="${company.ticker}">Remove from all lists</button></td></tr>`).join("") : `<tr><td colspan="6">No companies in this list.</td></tr>`}</tbody></table></div></section>`;
}

function bindFeedControls() {
  document.querySelectorAll("[data-filter-type]").forEach(button => button.addEventListener("click", () => { state.filters.type = button.dataset.filterType; state.filters.page = 1; refreshFilterUI(); loadFeed(); }));
  document.querySelectorAll("[data-ticker]").forEach(button => button.addEventListener("click", () => { state.filters.ticker = button.dataset.ticker; state.filters.page = 1; refreshFilterUI(); loadFeed(); }));
  document.getElementById("clear-filters").addEventListener("click", () => {
    const keepList = ["holdings","planned","watchlist"].includes(state.view) ? state.view : "";
    state.filters = { ...state.filters, list: keepList, ticker:"", type:"all", form:"", start_date: state.view === "today" ? state.bootstrap.selected_date : "", end_date: state.view === "today" ? state.bootstrap.selected_date : "", read:"all", amendment:"all", q:"", page:1 };
    renderInformationPage();
  });
  ["form-filter","start-date","end-date","read-filter","amendment-filter"].forEach(id => {
    const element = document.getElementById(id); if (!element) return;
    element.addEventListener("change", () => { const key = {"form-filter":"form","start-date":"start_date","end-date":"end_date","read-filter":"read","amendment-filter":"amendment"}[id]; state.filters[key] = element.value; state.filters.page = 1; loadFeed(); });
  });
  const search = document.getElementById("metadata-search");
  if (search) { let timer; search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { state.filters.q = search.value.trim(); state.filters.page = 1; loadFeed(); }, 300); }); }
  document.getElementById("mark-all").addEventListener("click", markAllRead);
}

function refreshFilterUI() {
  document.querySelectorAll("[data-filter-type]").forEach(button => button.classList.toggle("active", button.dataset.filterType === state.filters.type));
  document.querySelectorAll("[data-ticker]").forEach(button => button.classList.toggle("active", button.dataset.ticker === state.filters.ticker));
}

async function loadFeed() {
  if (state.controller) state.controller.abort();
  state.controller = new AbortController();
  document.getElementById("feed-content").innerHTML = `<div class="loading-state" role="status"><span class="spinner"></span> Loading information…</div>`;
  try {
    const query = new URLSearchParams(Object.entries(state.filters).filter(([,value]) => value !== "" && value !== null));
    const response = await api(`/api/feed?${query}`, { signal: state.controller.signal });
    state.currentFeed = response;
    renderFeed(response);
  } catch (error) {
    if (error.name === "AbortError") return;
    document.getElementById("feed-content").innerHTML = `<div class="error-state"><div><strong>Request failed</strong><p>${esc(error.message)}</p><button class="button" id="retry-feed">Retry</button></div></div>`;
    document.getElementById("retry-feed").addEventListener("click", loadFeed);
  }
}

function renderFeed(response) {
  const container = document.getElementById("feed-content");
  document.getElementById("result-count").textContent = `${response.pagination.total} ${response.pagination.total === 1 ? "result" : "results"}`;
  document.getElementById("mark-all").disabled = response.pagination.total === 0;
  if (response.disconnected_message) { container.innerHTML = `<div class="not-connected"><div><strong>${response.disconnected_message}</strong><p>This source is not configured. Connected sources remain available under All.</p></div></div>`; return; }
  if (!response.items.length) { container.innerHTML = `<div class="empty-state"><div><strong>${state.view === "today" ? "No information for this date" : state.view === "search" ? "Search returned no results" : "No information matches these filters"}</strong><p>Change the active filters or date range and try again.</p></div></div>`; return; }
  container.innerHTML = `<div class="feed">${response.items.map(feedItem).join("")}</div>${pagination(response.pagination)}`;
  container.querySelectorAll(".read-control").forEach(button => button.addEventListener("click", () => markRead(Number(button.dataset.id), button.dataset.read !== "true")));
  container.querySelectorAll(".open-link").forEach(link => link.addEventListener("click", async event => {
    event.preventDefault();
    const newWindow = window.open("about:blank", "_blank", "noopener,noreferrer");
    try { await setRead([Number(link.dataset.id)], true); if (newWindow) newWindow.location = link.href; else location.href = link.href; await reloadWorkspaceCounts(); await loadFeed(); }
    catch (error) { if (newWindow) newWindow.close(); toast(error.message, true); }
  }));
  container.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => { state.filters.page = Number(button.dataset.page); loadFeed(); document.getElementById("main-content").focus(); }));
}

function feedItem(item) {
  const readControl = item.is_read ? `<span class="read-check">✓</span><span class="read-label">Read</span>` : `<span class="unread-dot"></span><span class="sr-only">Unread</span>`;
  return `<article class="feed-item ${item.is_read ? "is-read" : "is-unread"}"><button class="read-control" data-id="${item.id}" data-read="${item.is_read}" aria-label="Mark ${item.ticker} ${item.document_type} as ${item.is_read ? "unread" : "read"}">${readControl}</button><div class="company-cell"><strong>${item.ticker}</strong><span>${esc(item.company_name || item.issuer)}</span></div><span class="form-badge">${esc(item.document_type)}${item.is_amendment ? " · Amended" : ""}</span><time class="timestamp" datetime="${item.effective_at}">${esc(item.effective_et)}</time><div class="item-title"><strong>${esc(item.title)}</strong><span>${esc(item.source_label)} · Live · Accession ${esc(item.external_id)}</span></div><div class="list-badges">${item.list_slugs.map(slug => badge(slug)).join("")}</div><a class="open-link" data-id="${item.id}" href="${escAttr(item.url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open filing ↗</a></article>`;
}

function badge(slug) { return `<span class="list-badge ${slug}">${listLabels[slug] || slug}</span>`; }
function pagination(p) { return `<div class="pagination"><span>Page ${p.page} of ${p.pages}</span><div><button class="button" data-page="${p.page - 1}" ${p.page <= 1 ? "disabled" : ""}>Previous</button> <button class="button" data-page="${p.page + 1}" ${p.page >= p.pages ? "disabled" : ""}>Next</button></div></div>`; }

async function markRead(id, isRead) { try { await setRead([id], isRead); await reloadWorkspaceCounts(); await loadFeed(); toast(`Marked as ${isRead ? "read" : "unread"}.`); } catch (error) { toast(error.message, true); } }
async function setRead(itemIds, isRead) { return api("/api/read", { method:"POST", body: JSON.stringify({ item_ids:itemIds, is_read:isRead }) }); }
async function markAllRead() {
  const count = state.currentFeed?.pagination.total || 0;
  if (!count || !confirm(`Mark all ${count} items matching the active filters as read? This includes every result page.`)) return;
  try { const result = await api("/api/read/bulk", { method:"POST", body: JSON.stringify({ filters: state.filters, is_read:true }) }); toast(`Marked ${result.updated} scoped items as read.`); await reloadWorkspaceCounts(); await loadFeed(); } catch (error) { toast(error.message, true); }
}
async function reloadWorkspaceCounts() { state.bootstrap = await api("/api/bootstrap"); renderShell(); }

function bindListControls() {
  document.getElementById("toggle-add").addEventListener("click", () => { const panel = document.getElementById("add-panel"); panel.hidden = !panel.hidden; if (!panel.hidden) document.getElementById("ticker-input").focus(); });
  document.getElementById("add-form").addEventListener("submit", async event => {
    event.preventDefault(); const button = event.submitter; button.disabled = true;
    const lists = [...document.querySelectorAll('[name="destination"]:checked')].map(input => input.value);
    try { const result = await api("/api/companies/batch", { method:"POST", body: JSON.stringify({ tickers:document.getElementById("ticker-input").value, lists }) }); document.getElementById("batch-result").innerHTML = batchResult(result); await reloadWorkspaceCounts(); toast("Batch add completed."); }
    catch (error) { document.getElementById("batch-result").innerHTML = `<div class="batch-result">${esc(error.message)}</div>`; }
    finally { button.disabled = false; }
  });
  document.querySelectorAll(".remove-current").forEach(button => button.addEventListener("click", async () => { try { await api("/api/memberships/remove", { method:"POST", body:JSON.stringify({ticker:button.dataset.ticker,list:state.view}) }); toast(`${button.dataset.ticker} removed from ${listLabels[state.view]}.`); await reloadWorkspaceCounts(); renderInformationPage(); } catch(error) { toast(error.message,true); } }));
  document.querySelectorAll(".remove-all").forEach(button => button.addEventListener("click", async () => { if (!confirm(`Remove ${button.dataset.ticker} from all lists? Historical information will be preserved.`)) return; try { const result = await api("/api/companies/remove-all", { method:"POST", body:JSON.stringify({ticker:button.dataset.ticker}) }); toast(`Removed ${result.removed_memberships} memberships. Historical information was preserved.`); await reloadWorkspaceCounts(); renderInformationPage(); } catch(error) { toast(error.message,true); } }));
}

function batchResult(result) {
  const sections = [];
  if (result.added.length) sections.push(`<strong>Added:</strong> ${result.added.map(item => `${item.ticker} (${esc(item.name)}, CIK ${esc(item.cik)})`).join(", ")}`);
  if (result.already_present.length) sections.push(`<strong>Already present:</strong> ${result.already_present.map(item => item.ticker).join(", ")}`);
  if (result.failed.length) sections.push(`<strong>Failed:</strong> ${result.failed.map(item => `${item.ticker} — ${esc(item.error)}`).join("; ")}`);
  if (result.collection) {
    const sync = result.collection;
    const detail = `${sync.records_fetched} fetched, ${sync.inserted} new, ${sync.updated} refreshed`;
    if (sync.status === "failure") sections.push(`<strong>SEC backfill failed:</strong> The company remains in your list. ${sync.failures.map(item => `${esc(item.ticker)} — ${esc(item.message)}`).join("; ")}`);
    else if (sync.status === "partial") sections.push(`<strong>SEC backfill partially completed:</strong> ${detail}. ${sync.failures.map(item => `${esc(item.ticker)} — ${esc(item.message)}`).join("; ")}`);
    else sections.push(`<strong>SEC backfill ${sync.status === "empty" ? "completed with no filings" : "completed"}:</strong> ${detail}.`);
  }
  return `<div class="batch-result">${sections.join("<br>") || "No changes."}</div>`;
}

async function renderSources() {
  const data = await api("/api/sources");
  document.getElementById("page").innerHTML = `<header class="page-header"><div><h1>Data Sources</h1><p>Connection health based on real stored data and recorded collection activity.</p></div></header><div class="source-grid">${data.sources.map(source => `<article class="panel source-card"><h3>${source.type}</h3><div class="source-provider">${source.provider || "No provider configured"}</div><div class="source-status ${source.status}">${sourceStatusLabel(source.status)}</div><p class="timestamp">${source.latest_success ? `Latest successful sync: ${formatDateTime(source.latest_success)}` : "No successful sync recorded"}</p>${source.latest_attempt ? `<p class="timestamp">Latest attempt: ${formatDateTime(source.latest_attempt)}</p>` : ""}${source.last_failure ? `<details class="error-details"><summary>Last failure</summary><p>${esc(source.last_failure)}</p></details>` : ""}</article>`).join("")}</div>`;
}

async function renderActivity() {
  document.getElementById("page").innerHTML = `<header class="page-header"><div><h1>Activity &amp; Logs</h1><p>Truthful collection operations only; unavailable metrics are not estimated.</p></div></header><div class="panel"><div class="filter-bar"><div class="filter-field"><label for="activity-source">Source</label><select id="activity-source"><option value="">All sources</option><option value="sec">SEC</option></select></div><div class="filter-field"><label for="activity-status">Status</label><select id="activity-status"><option value="">All statuses</option><option value="success">Success</option><option value="partial">Partial</option><option value="empty">Empty</option><option value="failure">Failure</option></select></div><div class="filter-field"><label for="activity-start">Start date</label><input id="activity-start" type="date"></div><div class="filter-field"><label for="activity-end">End date</label><input id="activity-end" type="date"></div></div><div id="activity-content"><div class="loading-state"><span class="spinner"></span> Loading activity…</div></div></div>`;
  const load = async () => { const params = new URLSearchParams({source:document.getElementById("activity-source").value,status:document.getElementById("activity-status").value,start_date:document.getElementById("activity-start").value,end_date:document.getElementById("activity-end").value}); try { const data = await api(`/api/activity?${params}`); document.getElementById("activity-content").innerHTML = activityContent(data); } catch (error) { document.getElementById("activity-content").innerHTML = `<div class="error-state"><div><strong>Activity request failed</strong><p>${esc(error.message)}</p><button class="button" id="retry-activity">Retry</button></div></div>`; document.getElementById("retry-activity").addEventListener("click", load); } };
  ["activity-source","activity-status","activity-start","activity-end"].forEach(id => document.getElementById(id).addEventListener("change", load));
  await load();
}
function activityContent(data) {
  if (!data.runs.length && !data.logs.length) return `<div class="empty-state"><div><strong>No persisted collection runs yet</strong><p>Existing CLI logs predate operational-log persistence, so this page does not invent historical metrics.</p></div></div>`;
  const rows = data.logs.map(log => `<tr><td>${formatDateTime(log.occurred_at)}</td><td>${esc(log.operation)}</td><td>${esc(log.source)}</td><td>${esc(log.ticker || "—")}</td><td>${esc(log.status)}</td><td>${log.records_read ?? "Unavailable"}</td><td>${log.records_written ?? "Unavailable"}</td><td>${log.error_message ? `<details class="error-details"><summary>View error</summary>${esc(log.error_message)}</details>` : "—"}</td></tr>`).join("");
  const runs = data.runs.map(run => `<div class="summary-card"><div><strong>${esc(run.source.toUpperCase())} · ${esc(run.status)}</strong><div class="summary-label">${formatDateTime(run.started_at)} to ${formatDateTime(run.finished_at)} · ${run.companies_processed} companies · ${run.records_fetched} fetched · ${run.records_inserted} inserted · ${run.duplicate_records} existing identities updated</div></div></div>`).join("");
  return `<div class="summary-grid">${runs}</div><div style="overflow:auto"><table class="data-table"><thead><tr><th>Time</th><th>Operation</th><th>Source</th><th>Company</th><th>Status</th><th>Read</th><th>Written</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderSettings() {
  const size = state.bootstrap.settings.page_size;
  document.getElementById("page").innerHTML = `<header class="page-header"><div><h1>Settings</h1><p>Only settings that currently affect the product are shown.</p></div></header><section class="panel settings-card"><h2>Display</h2><div class="filter-field"><label for="page-size-setting">Information items per page</label><select id="page-size-setting"><option ${size===10?"selected":""}>10</option><option ${size===25?"selected":""}>25</option><option ${size===50?"selected":""}>50</option></select></div><p class="timestamp">Today grouping and displayed filing timestamps use America/New_York (ET). Canonical stored timestamps remain UTC-compatible.</p><button class="button primary" id="save-settings">Save settings</button></section>`;
  document.getElementById("save-settings").addEventListener("click", async () => { try { await api("/api/settings", {method:"POST",body:JSON.stringify({key:"page_size",value:document.getElementById("page-size-setting").value})}); await reloadWorkspaceCounts(); toast("Settings saved."); } catch(error) { toast(error.message,true); } });
}

async function api(url, options = {}) {
  const response = await fetch(url, { headers:{"Content-Type":"application/json"}, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}
function toast(message, error=false) { const region=document.getElementById("toast-region"); const node=document.createElement("div"); node.className=`toast ${error?"error":""}`; node.textContent=message; region.appendChild(node); setTimeout(()=>node.remove(),4500); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
function escAttr(value) { return esc(value); }
function formatDateTime(value) { try { return new Intl.DateTimeFormat("en-US",{dateStyle:"medium",timeStyle:"short",timeZone:"America/New_York"}).format(new Date(value)) + " ET"; } catch { return value || "Unavailable"; } }
function sourceStatusLabel(status) { return ({connected:"● Connected and up to date",stale:"△ Connected, data is stale",not_connected:"○ Not connected",temporarily_unavailable:"! Temporarily unavailable",failed:"! Failed",loading:"… Checking",unavailable:"! Unavailable"})[status] || `! ${status}`; }
function renderFatal(error) { document.getElementById("page").innerHTML = `<div class="error-state"><div><strong>Workspace request failed</strong><p>${esc(error.message)}</p><button class="button" id="retry-workspace">Retry</button></div></div>`; document.getElementById("retry-workspace").addEventListener("click", () => location.reload()); }
