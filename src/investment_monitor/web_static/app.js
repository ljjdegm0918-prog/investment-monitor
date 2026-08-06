"use strict";

const state = {
  view: document.body.dataset.view,
  path: document.body.dataset.path,
  bootstrap: null,
  filters: {},
  items: [],
  currentFeed: null,
  controller: null,
};

const USER_TIMEZONE = (() => {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York"; }
  catch { return "America/New_York"; }
})();

const listLabels = { holdings: "Holdings", planned: "Planned Purchases", watchlist: "Watchlist" };
const viewTitles = {
  today: "Today",
  activity: "Activity & Logs", sources: "Data Sources", settings: "Settings",
  holdings: "Holdings", planned: "Planned Purchases", watchlist: "Watchlist",
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  document.getElementById("mobile-menu").addEventListener("click", event => {
    const open = document.querySelector(".sidebar").classList.toggle("open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });
  try {
    state.bootstrap = await api(`/api/bootstrap?timezone=${encodeURIComponent(USER_TIMEZONE)}`);
    renderShell();
    await renderPage();
  } catch (error) {
    renderFatal(error);
  }
}

function renderShell() {
  const b = state.bootstrap;
  document.getElementById("topbar-title").textContent = viewTitles[state.view] || "Investment Monitor";
  document.getElementById("current-date").textContent = `${b.display_date} · ${b.timezone_label}`;
  const summary = b.topbar_summary || { text: "Sources unavailable", level: "failed" };
  const status = document.getElementById("top-source-status");
  status.textContent = summary.text;
  status.className = `status-line ${summary.level}`;
  const listBySlug = Object.fromEntries(b.lists.map(list => [list.slug, list]));
  const svg = body => `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
  const navIcons = {
    today: svg(`<circle cx="8" cy="8" r="5.75"/><path d="M8 4.75V8l2.25 1.5"/>`),
    holdings: svg(`<circle cx="8" cy="8" r="5.75"/><path d="M8 2.25V8h5.5"/>`),
    planned: svg(`<circle cx="8" cy="8" r="5.75"/><path d="M8 5.5v5M5.5 8h5"/>`),
    watchlist: svg(`<path d="M1.75 8S4.25 3.75 8 3.75 14.25 8 14.25 8 11.75 12.25 8 12.25 1.75 8 1.75 8z"/><circle cx="8" cy="8" r="1.9"/>`),
    settings: svg(`<path d="M2.25 4.75h11.5M2.25 11.25h11.5"/><circle cx="5.9" cy="4.75" r="1.7"/><circle cx="10.1" cy="11.25" r="1.7"/>`),
  };
  const nav = [
    ["OVERVIEW", [["/today","today","Today"]]],
    ["MY LISTS", [["/lists/holdings","holdings","Holdings",listBySlug.holdings.unread_count],["/lists/planned","planned","Planned Purchases",listBySlug.planned.unread_count],["/lists/watchlist","watchlist","Watchlist",listBySlug.watchlist.unread_count]]],
    ["SYSTEM", [["/settings","settings","Settings"]]],
  ];
  document.getElementById("sidebar-nav").innerHTML = nav.map(([heading, links]) => `
    <section class="nav-section"><h2 class="nav-heading">${heading}</h2>
      ${links.map(([href,icon,label,count]) => `<a class="nav-link ${isActive(href) ? "active" : ""}" href="${href}" aria-label="${label}${count !== undefined ? `, ${count} unread` : ""}"><span class="nav-icon" aria-hidden="true">${navIcons[icon]}</span><span>${label}</span>${count !== undefined ? `<span class="nav-count" aria-hidden="true">${count}</span>` : ""}</a>`).join("")}
    </section>`).join("");
}

function isActive(href) {
  return state.path === href || (href === "/today" && state.path === "/");
}

async function renderPage() {
  if (state.view === "today") return renderTodayPage();
  if (["holdings","planned","watchlist"].includes(state.view)) return renderListPage();
  if (state.view === "activity") return renderActivity();
  if (state.view === "sources") return renderSources();
  if (state.view === "settings") return renderSettings();
  location.replace("/today");
}

async function renderTodayPage() {
  state.filters = {
    list: "",
    ticker: "",
    type: "all",
    form: "",
    start_date: state.bootstrap.selected_date,
    end_date: state.bootstrap.selected_date,
    timezone: USER_TIMEZONE,
    read: "all",
    amendment: "all",
    q: "",
    page: 1,
    page_size: state.bootstrap.settings.page_size,
  };
  state.items = [];
  document.getElementById("page").innerHTML = `
    <header class="page-header"><div><h1>Today</h1><p>Everything new collected today across all tracked companies, newest first. No filters needed.</p></div><button class="button" id="refresh-feed" type="button">Refresh</button></header>
    <section class="panel" aria-label="Today's new information">
      <div class="results-toolbar"><span id="result-count">Loading results…</span><button class="button link" id="mark-all" type="button">Mark all as read</button></div>
      <div id="feed-content"><div class="loading-state" role="status"><span class="spinner"></span> Loading information…</div></div>
    </section>`;
  document.getElementById("refresh-feed").addEventListener("click", () => loadFeed("replace"));
  document.getElementById("mark-all").addEventListener("click", markAllRead);
  await loadFeed("replace");
}

async function renderListPage() {
  const companies = state.bootstrap.companies.filter(company => company.list_slugs.includes(state.view));
  const companyCount = companies.length;
  document.getElementById("page").innerHTML = `
    <header class="page-header"><div><h1>${viewTitles[state.view]}</h1><p>${companyCount} ${companyCount === 1 ? "company" : "companies"} tracked · new items appear on Today</p></div><button class="button primary" id="toggle-add">+ Add companies</button></header>
    ${addCompanyPanel()}
    ${companyManagement(companies)}`;
  bindListControls();
}

function addCompanyPanel() {
  return `<section class="panel add-panel" id="add-panel" hidden><form class="add-form" id="add-form"><div class="filter-field"><label for="ticker-input">Ticker symbols</label><textarea id="ticker-input" placeholder="AAPL, MSFT NVDA&#10;One or many tickers"></textarea></div><div class="filter-field"><label for="market-select">Market</label><select id="market-select"><option value="us" selected>US</option><option value="cn">CN (A-share)</option><option value="hk">HK</option><option value="kr">KR (Korea)</option><option value="uk">UK (LSE/AIM)</option><option value="tw">TW (Taiwan)</option><option value="unknown">Unknown</option></select><p class="timestamp" id="market-hint" hidden>Non-US tickers cannot be mapped through SEC; they are added as unmapped.</p></div><div class="filter-field"><label>Destination lists</label><div class="checkboxes">${state.bootstrap.lists.map(list => `<label><input type="checkbox" name="destination" value="${list.slug}" ${list.slug === state.view ? "checked" : ""}> ${list.name}</label>`).join("")}</div></div><button class="button primary" type="submit">Resolve and add</button></form><div id="batch-result"></div></section>`;
}

function companyManagement(companies) {
  return `<section class="panel" style="margin-top:16px"><div class="results-toolbar"><strong>Companies in ${listLabels[state.view]}</strong><span>Membership changes never delete stored information.</span></div><div style="overflow:auto"><table class="company-table"><thead><tr><th>Ticker</th><th>Market</th><th>Company</th><th>Exchange</th><th>Identifier</th><th>Lists</th><th>Actions</th></tr></thead><tbody>${companies.length ? companies.map(company => { const idText = company.market === "kr" && company.cik ? `Corp ${esc(company.cik)}` : company.market === "uk" && company.cik ? `Company ${esc(company.cik)}${company.mapping_status === "unverified" ? ' <span class="form-badge">Unverified</span>' : ""}` : company.market === "hk" && company.cik ? `HKEX ${esc(company.cik)}` : esc(company.cik || "Unmapped"); const confirmButton = company.market === "uk" && company.mapping_status === "unverified" ? `<button class="button link confirm-ch" data-ticker="${company.ticker}" data-market="${company.market}" data-cik="${esc(company.cik || "")}">Confirm</button>` : ""; return `<tr><td><strong>${company.ticker}</strong></td><td>${marketLabel(company.market)}</td><td>${esc(company.name)}</td><td>${esc(company.exchange || "Unavailable")}</td><td>${idText}</td><td>${company.list_slugs.map(slug => badge(slug)).join("")}</td><td>${confirmButton}<button class="button link remove-current" data-ticker="${company.ticker}" data-market="${company.market}">Remove from this list</button><button class="button link remove-all" data-ticker="${company.ticker}" data-market="${company.market}">Remove from all lists</button></td></tr>`; }).join("") : `<tr><td colspan="7">No companies in this list.</td></tr>`}</tbody></table></div></section>`;
}

async function loadFeed(mode) {
  if (state.controller) state.controller.abort();
  state.controller = new AbortController();
  if (mode === "append") state.filters.page += 1;
  else {
    state.filters.page = 1;
    document.getElementById("feed-content").innerHTML = `<div class="loading-state" role="status"><span class="spinner"></span> Loading information…</div>`;
  }
  try {
    const query = new URLSearchParams(Object.entries(state.filters).filter(([,value]) => value !== "" && value !== null));
    const response = await api(`/api/feed?${query}`, { signal: state.controller.signal });
    state.currentFeed = response;
    state.items = mode === "append" ? state.items.concat(response.items) : response.items;
    renderFeed();
  } catch (error) {
    if (error.name === "AbortError") return;
    document.getElementById("feed-content").innerHTML = `<div class="error-state"><div><strong>Request failed</strong><p>${esc(error.message)}</p><button class="button" id="retry-feed">Retry</button></div></div>`;
    document.getElementById("retry-feed").addEventListener("click", () => loadFeed("replace"));
  }
}

function renderFeed() {
  const response = state.currentFeed;
  const container = document.getElementById("feed-content");
  const total = response.pagination.total;
  document.getElementById("result-count").textContent = `${total} new ${total === 1 ? "item" : "items"} today`;
  document.getElementById("mark-all").disabled = total === 0;
  if (response.disconnected_message) { container.innerHTML = `<div class="not-connected"><div><strong>${response.disconnected_message}</strong><p>This source is not configured. Connected sources remain available under All.</p></div></div>`; return; }
  if (!state.items.length) { container.innerHTML = `<div class="empty-state"><div><strong>No information for this date</strong><p>New filings, disclosures and news will appear here as they are collected today.</p></div></div>`; return; }
  const p = response.pagination;
  const more = p.page < p.pages ? `<div class="pagination"><span>Showing ${state.items.length} of ${total}</span><div><button class="button" id="load-more" type="button">Load more</button></div></div>` : "";
  container.innerHTML = `<div class="feed">${state.items.map(feedItem).join("")}</div>${more}`;
  container.querySelectorAll(".read-control").forEach(button => button.addEventListener("click", () => markRead(Number(button.dataset.id), button.dataset.read !== "true")));
  container.querySelectorAll(".open-link").forEach(link => link.addEventListener("click", async event => {
    event.preventDefault();
    const newWindow = window.open("about:blank", "_blank", "noopener,noreferrer");
    try { await setRead([Number(link.dataset.id)], true); if (newWindow) newWindow.location = link.href; else location.href = link.href; markLocalRead([Number(link.dataset.id)], true); await reloadWorkspaceCounts(); renderFeed(); }
    catch (error) { if (newWindow) newWindow.close(); toast(error.message, true); }
  }));
  const loadMore = document.getElementById("load-more");
  if (loadMore) loadMore.addEventListener("click", () => loadFeed("append"));
}

function feedItem(item, index) {
  const readControl = item.is_read ? `<span class="read-check">✓</span><span class="read-label">Read</span>` : `<span class="unread-dot"></span><span class="sr-only">Unread</span>`;
  const summaryHtml = item.summary ? `<p class="item-summary">${esc(item.summary)}</p>` : "";
  const identityLabel = item.source === "sec" ? `Accession ${esc(item.external_id)}` : `ID ${esc(item.external_id)}`;
  const alsoSeen = (item.also_seen_on_labels || []).map(label => `Also seen on ${esc(label)}`).join(", ");
  const alsoHtml = alsoSeen ? `<span class="timestamp">${alsoSeen}</span>` : "";
  return `<article class="feed-item ${item.is_read ? "is-read" : "is-unread"}" style="--i:${index}"><button class="read-control" data-id="${item.id}" data-read="${item.is_read}" aria-label="Mark ${item.ticker} ${item.document_type} as ${item.is_read ? "unread" : "read"}">${readControl}</button><div class="company-cell"><strong>${item.ticker}</strong><span>${esc(item.company_name || item.issuer)}</span></div><span class="form-badge">${esc(item.document_type || "Information")}${item.is_amendment ? " · Amended" : ""}</span><time class="timestamp" datetime="${item.effective_at}">${esc(item.effective_et)}</time><div class="item-title"><strong>${esc(item.title)}</strong><span>${esc(item.source_label)} · ${marketLabel(item.market)} · Live · ${identityLabel}</span>${alsoHtml}</div>${summaryHtml}<div class="list-badges">${item.list_slugs.map(slug => badge(slug)).join("")}</div><a class="open-link" data-id="${item.id}" href="${escAttr(item.url)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open original →</a></article>`;
}

function badge(slug) { return `<span class="list-badge ${slug}">${listLabels[slug] || slug}</span>`; }
function marketLabel(market) { return ({ us: "US", cn: "CN", hk: "HK", kr: "KR", uk: "UK", tw: "TW", unknown: "Market unknown" })[market] || esc(market || "Unknown"); }

const MARKET_HINTS = {
  cn: "CN tickers cannot be mapped through SEC; they are added as unmapped.",
  hk: "HKEXnews announcement search is connected (not an official HKEX API/IIS feed; page may change without notice). HKEX DI public notice search is available but disabled by default (legacy archive 2003-2017; fragile, not DION/IIS). Yahoo Finance HK news is connected via public RSS (may be loosely related; may break without notice). HK symbols without a stock match are still added as unmapped.",
  kr: "KR tickers map through OpenDART when a corp code is found; otherwise they are added as unmapped.",
  uk: "UK Companies House filings, an Investegate RNS-class public mirror, and Yahoo Finance UK news are connected; not an official LSEG RNS feed. Unique name search is not proof of the listed issuer; unverified mappings need confirmation before Companies House filings are collected.",
  tw: "TWSE OpenAPI material-information (重大訊息) is connected for listed companies (key-free; not a paid MOPS push). TPEx/興櫃 disclosure is not covered yet. A TWSE/TPEx universe cache can backfill company names and board for add-company. TW symbols without a match are added as unmapped. Finnhub is US-only and never queried for TW.",
  unknown: "Unknown-market tickers are added as unmapped.",
};

function markLocalRead(ids, isRead) {
  state.items.forEach(item => { if (ids.includes(item.id)) item.is_read = isRead; });
}

async function markRead(id, isRead) { try { await setRead([id], isRead); markLocalRead([id], isRead); await reloadWorkspaceCounts(); renderFeed(); toast(`Marked as ${isRead ? "read" : "unread"}.`); } catch (error) { toast(error.message, true); } }
async function setRead(itemIds, isRead) { return api("/api/read", { method:"POST", body: JSON.stringify({ item_ids:itemIds, is_read:isRead }) }); }
async function markAllRead() {
  const count = state.currentFeed?.pagination.total || 0;
  if (!count || !confirm(`Mark all ${count} items from today as read?`)) return;
  try { const result = await api("/api/read/bulk", { method:"POST", body: JSON.stringify({ filters: state.filters, is_read:true }) }); markLocalRead(state.items.map(item => item.id), true); toast(`Marked ${result.updated} items as read.`); await reloadWorkspaceCounts(); renderFeed(); } catch (error) { toast(error.message, true); }
}
async function reloadWorkspaceCounts() { state.bootstrap = await api("/api/bootstrap"); renderShell(); }

function bindListControls() {
  document.getElementById("toggle-add").addEventListener("click", () => { const panel = document.getElementById("add-panel"); panel.hidden = !panel.hidden; if (!panel.hidden) document.getElementById("ticker-input").focus(); });
  document.getElementById("add-form").addEventListener("submit", async event => {
    event.preventDefault(); const button = event.submitter; button.disabled = true;
    const lists = [...document.querySelectorAll('[name="destination"]:checked')].map(input => input.value);
    const market = document.getElementById("market-select").value;
    try { const result = await api("/api/companies/batch", { method:"POST", body: JSON.stringify({ tickers:document.getElementById("ticker-input").value, lists, market }) }); document.getElementById("batch-result").innerHTML = batchResult(result) + `<p style="margin-top:10px"><a class="button" href="/today">← Back to Today</a></p>`; await reloadWorkspaceCounts(); toast("Batch add completed. New items will show up on Today."); }
    catch (error) { document.getElementById("batch-result").innerHTML = `<div class="batch-result">${esc(error.message)}</div>`; }
    finally { button.disabled = false; }
  });
  const marketSelect = document.getElementById("market-select");
  const marketHint = document.getElementById("market-hint");
  if (marketSelect && marketHint) {
    marketSelect.addEventListener("change", () => {
      const market = marketSelect.value;
      marketHint.hidden = market === "us";
      marketHint.textContent = MARKET_HINTS[market] || "Non-US tickers cannot be mapped through SEC; they are added as unmapped.";
    });
  }
  document.querySelectorAll(".remove-current").forEach(button => button.addEventListener("click", async () => { try { await api("/api/memberships/remove", { method:"POST", body:JSON.stringify({ticker:button.dataset.ticker,list:state.view,market:button.dataset.market || "us"}) }); toast(`${button.dataset.ticker} removed from ${listLabels[state.view]}.`); await reloadWorkspaceCounts(); renderListPage(); } catch(error) { toast(error.message,true); } }));
  document.querySelectorAll(".remove-all").forEach(button => button.addEventListener("click", async () => { if (!confirm(`Remove ${button.dataset.ticker} from all lists? Stored information will be preserved.`)) return; try { const result = await api("/api/companies/remove-all", { method:"POST", body:JSON.stringify({ticker:button.dataset.ticker,market:button.dataset.market || "us"}) }); toast(`Removed ${result.removed_memberships} memberships. Stored information was preserved.`); await reloadWorkspaceCounts(); renderListPage(); } catch(error) { toast(error.message,true); } }));
  document.querySelectorAll(".confirm-ch").forEach(button => button.addEventListener("click", async () => {
    const number = prompt("Confirm Companies House mapping (edit company number if needed)", button.dataset.cik || "");
    if (number === null) return;
    try { const result = await api("/api/companies/confirm-mapping", { method:"POST", body: JSON.stringify({ ticker:button.dataset.ticker, market:button.dataset.market || "uk", company_number:number.trim() }) }); toast(`Confirmed ${result.ticker} as Company ${result.cik}.`); await reloadWorkspaceCounts(); renderListPage(); } catch(error) { toast(error.message, true); }
  }));
}

function batchResult(result) {
  const sections = [];
  if (result.added.length) sections.push(`<strong>Added:</strong> ${result.added.map(item => `${item.ticker} ${marketLabel(item.market)} (${esc(item.name)}, ${item.market === "kr" && item.cik ? `Corp code ${esc(item.cik)}` : item.market === "uk" && item.cik ? `Company no ${esc(item.cik)}` : item.market === "hk" && item.cik ? `HKEX id ${esc(item.cik)}` : item.cik ? `CIK ${esc(item.cik)}` : "Unmapped"}${item.mapping_status === "unmapped" ? ", unmapped for SEC" : item.mapping_status === "unverified" ? ", unverified" : ""})`).join(", ")}`);
  if (result.already_present.length) sections.push(`<strong>Already present:</strong> ${result.already_present.map(item => `${item.ticker} ${marketLabel(item.market)}`).join(", ")}`);
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
  document.getElementById("page").innerHTML = `<header class="page-header"><div><h1>Activity &amp; Logs</h1><p>Truthful collection operations only; unavailable metrics are not estimated.</p></div></header><div class="panel"><div class="filter-bar"><div class="filter-field"><label for="activity-source">Source</label><select id="activity-source"><option value="">All sources</option><option value="sec">SEC</option><option value="news">News</option><option value="community">Community</option><option value="research">Research</option></select></div><div class="filter-field"><label for="activity-status">Status</label><select id="activity-status"><option value="">All statuses</option><option value="success">Success</option><option value="partial">Partial</option><option value="empty">Empty</option><option value="failure">Failure</option></select></div><div class="filter-field"><label for="activity-start">Start date</label><input id="activity-start" type="date"></div><div class="filter-field"><label for="activity-end">End date</label><input id="activity-end" type="date"></div></div><div id="activity-content"><div class="loading-state"><span class="spinner"></span> Loading activity…</div></div></div>`;
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
  api("/api/settings").then(data => {
    const size = data.page_size;
    const providerSections = (data.providers || []).map(provider => {
      const fields = (provider.fields || []).map(field => {
        const statusText = field.configured ? `Configured (${esc(field.hint)})` : "Not configured";
        const inputType = field.kind === "password" ? "password" : "text";
        return `<div class="filter-field"><label for="cred-${field.env}">${esc(field.label)}</label><input id="cred-${field.env}" type="${inputType}" autocomplete="new-password" placeholder="Leave blank to keep current"><span class="timestamp">${statusText}</span><button class="button link" type="button" data-clear-credential="${field.env}" ${field.configured ? "" : "disabled"}>Clear</button><p class="timestamp">${esc(field.help || "")}</p></div>`;
      }).join("");
      const body = provider.implemented
        ? fields || `<p class="timestamp">This source declares no credentials.</p>`
        : `<div class="source-provider">Not implemented / Not connected</div>`;
      return `<article class="provider-credential"><h3>${esc(provider.label)}${provider.enabled ? "" : " (disabled in settings)"}</h3>${body}</article>`;
    }).join("");
    const extraRows = (data.extra_env || []).map(entry => extraEnvRow(entry.name, "", entry.hint)).join("");
    document.getElementById("page").innerHTML = `<header class="page-header"><div><h1>Settings</h1><p>Only settings that currently affect the product are shown.</p></div></header><section class="panel settings-card"><h2>Display</h2><div class="filter-field"><label for="page-size-setting">Information items per page</label><select id="page-size-setting"><option ${size===10?"selected":""}>10</option><option ${size===25?"selected":""}>25</option><option ${size===50?"selected":""}>50</option></select></div><p class="timestamp">Today grouping and displayed item timestamps use your browser timezone (${USER_TIMEZONE}). Canonical stored timestamps remain UTC-compatible.</p><button class="button primary" id="save-settings">Save settings</button></section><section class="panel settings-card"><h2>Provider credentials</h2><p class="timestamp">Credential fields are declared by each implemented source; unimplemented sources cannot be configured here.</p>${providerSections}<button class="button primary" id="save-provider-credentials">Save provider credentials</button></section><section class="panel settings-card"><h2>System pages</h2><p class="timestamp">Operational detail lives outside the daily flow.</p><p><a href="/sources">Data Sources</a> · <a href="/activity">Activity &amp; Logs</a></p></section><section class="panel settings-card"><h2>Extra environment variables</h2><details id="advanced-env"><summary>Advanced: extra environment variables</summary><p class="timestamp">These variables are only used if a connector explicitly reads them; setting one does not connect any new source. Names must match <code>[A-Za-z_][A-Za-z0-9_]*</code>. Dangerous names (PATH, PYTHONPATH, LD_*, SSL*, HOME, USERPROFILE, ...) are rejected.</p><div id="extra-env-rows">${extraRows}</div><button class="button link" id="add-extra-env" type="button">+ Add variable</button><button class="button primary" id="save-extra-env" type="button">Save extra variables</button></details></section>`;
    document.getElementById("save-settings").addEventListener("click", async () => { try { await api("/api/settings", {method:"POST",body:JSON.stringify({key:"page_size",value:document.getElementById("page-size-setting").value})}); await reloadWorkspaceCounts(); toast("Settings saved."); } catch(error) { toast(error.message,true); } });
    document.getElementById("save-provider-credentials").addEventListener("click", saveProviderCredentials);
    document.querySelectorAll("[data-clear-credential]").forEach(button => button.addEventListener("click", () => clearCredential(button.dataset.clearCredential)));
    document.getElementById("add-extra-env").addEventListener("click", () => { document.getElementById("extra-env-rows").insertAdjacentHTML("beforeend", extraEnvRow("", "")); bindExtraEnvRows(); });
    document.getElementById("save-extra-env").addEventListener("click", saveExtraEnv);
    bindExtraEnvRows();
  }).catch(error => { document.getElementById("page").innerHTML = `<div class="error-state"><div><strong>Settings request failed</strong><p>${esc(error.message)}</p></div></div>`; });
}

function extraEnvRow(name, value, hint = "") {
  return `<div class="extra-env-row"><input class="extra-env-name" type="text" value="${esc(name)}" placeholder="VARIABLE_NAME" spellcheck="false"><input class="extra-env-value" type="password" autocomplete="new-password" value="${esc(value)}" placeholder="value (leave blank to keep)"><span class="timestamp">${hint ? `Configured (${esc(hint)})` : ""}</span><button class="button link" type="button" data-remove-extra-env>Remove</button></div>`;
}

function bindExtraEnvRows() {
  document.querySelectorAll("[data-remove-extra-env]").forEach(button => button.addEventListener("click", async () => {
    const row = button.closest(".extra-env-row");
    const name = row.querySelector(".extra-env-name").value.trim();
    if (name) {
      try { await api("/api/settings", { method:"POST", body: JSON.stringify({ key:`extra_env:${name}`, value:"" }) }); } catch (error) { toast(error.message, true); return; }
    }
    await reloadWorkspaceCounts();
    await renderSettings();
  }));
}

async function saveProviderCredentials() {
  const updates = [];
  document.querySelectorAll("[id^='cred-']").forEach(input => {
    const value = input.value.trim();
    if (value) updates.push({ key: input.id.slice("cred-".length), value });
  });
  try {
    for (const update of updates) await api("/api/settings", { method:"POST", body: JSON.stringify(update) });
    await reloadWorkspaceCounts();
    await renderSettings();
    toast(updates.length ? "Provider credentials saved." : "No credential changed.");
  } catch (error) { toast(error.message, true); }
}

async function clearCredential(env) {
  try {
    await api("/api/settings", { method:"POST", body: JSON.stringify({ key: env, value:"" }) });
    await reloadWorkspaceCounts();
    await renderSettings();
    toast(`${env} cleared.`);
  } catch (error) { toast(error.message, true); }
}

async function saveExtraEnv() {
  const updates = [];
  document.querySelectorAll(".extra-env-row").forEach(row => {
    const name = row.querySelector(".extra-env-name").value.trim();
    const inputValue = row.querySelector(".extra-env-value").value.trim();
    if (name && inputValue) updates.push({ key: `extra_env:${name}`, value: inputValue });
  });
  try {
    for (const update of updates) await api("/api/settings", { method:"POST", body: JSON.stringify(update) });
    await reloadWorkspaceCounts();
    await renderSettings();
    toast(updates.length ? "Extra environment variables saved." : "No extra variable changed.");
  } catch (error) { toast(error.message, true); }
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
function formatDateTime(value) { try { return new Intl.DateTimeFormat("en-US",{dateStyle:"medium",timeStyle:"short",timeZone:USER_TIMEZONE}).format(new Date(value)) + " " + USER_TIMEZONE; } catch { return value || "Unavailable"; } }
function sourceStatusLabel(status) { return ({connected:"● Connected and up to date",stale:"▲ Connected, data is stale",not_connected:"○ Not connected",temporarily_unavailable:"! Temporarily unavailable",failed:"! Failed",loading:"… Checking",unavailable:"! Unavailable"})[status] || `! ${status}`; }
function renderFatal(error) { document.getElementById("page").innerHTML = `<div class="error-state"><div><strong>Workspace request failed</strong><p>${esc(error.message)}</p><button class="button" id="retry-workspace">Retry</button></div></div>`; document.getElementById("retry-workspace").addEventListener("click", () => location.reload()); }
