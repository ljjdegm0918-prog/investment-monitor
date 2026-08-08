"use strict";

const state = { bootstrap: null, selectedList: "" };
document.addEventListener("DOMContentLoaded", init);

async function init() {
  const view = document.body.dataset.view === "manage" ? "manage" : "today";
  document.querySelector(`[data-nav="${view}"]`)?.classList.add("active");
  try {
    state.bootstrap = await api(`/api/bootstrap${location.search}`);
    state.selectedList = new URLSearchParams(location.search).get("list") || state.bootstrap.lists[0]?.slug || "";
    if (view === "manage") await renderManage(); else await renderDaily();
  } catch (error) { renderFatal(error); }
}

async function renderDaily() {
  const params = new URLSearchParams(location.search);
  const selectedDate = params.get("date") || state.bootstrap.selected_date;
  const selectedList = params.get("list") || "";
  document.getElementById("page").innerHTML = `
    <section class="daily-head">
      <div><p class="eyebrow">DAILY INFORMATION</p><h1>${formatDay(selectedDate)}</h1><p>Company updates for one Eastern Time calendar day.</p></div>
      <div class="daily-actions"><button class="button" id="print-page" type="button">Print / Save PDF</button></div>
    </section>
    <form class="toolbar" id="daily-filter">
      <label>Date<input type="date" id="daily-date" value="${escAttr(selectedDate)}"></label>
      <label>List<select id="daily-list"><option value="">All lists</option>${listOptions(selectedList)}</select></label>
      <button class="button primary" type="submit">View</button>
    </form>
    <div id="daily-content"><p class="loading">Loading information…</p></div>`;
  document.getElementById("print-page").addEventListener("click", () => window.print());
  document.getElementById("daily-filter").addEventListener("submit", event => {
    event.preventDefault();
    const next = new URLSearchParams({date: document.getElementById("daily-date").value});
    const list = document.getElementById("daily-list").value;
    if (list) next.set("list", list);
    location.href = `/today?${next}`;
  });
  try {
    const query = new URLSearchParams({date:selectedDate});
    if (selectedList) query.set("list", selectedList);
    const data = await api(`/api/daily?${query}`);
    document.getElementById("daily-content").innerHTML = dailyContent(data);
  } catch (error) {
    document.getElementById("daily-content").innerHTML = errorState("Request failed", error.message);
  }
}

function dailyContent(data) {
  if (!data.companies.length) return `<div class="empty"><h2>No information for this date</h2><p>Companies without updates are hidden by default.</p></div>`;
  return `<div class="daily-document">${data.companies.map(company => `
    <section class="company-section">
      <header><div><h2>${esc(company.name)}</h2><p>${esc(company.ticker)} · ${esc(company.exchange || "Unavailable")}</p></div><span>${company.items.length} update${company.items.length === 1 ? "" : "s"}</span></header>
      <div class="information-list">${company.items.map(item => `
        <article class="information-row">
          <time datetime="${escAttr(item.time)}">${formatTime(item.time)}</time>
          <span class="type type-${item.type.toLowerCase()}">${esc(item.type)}</span>
          <span class="source">${esc(item.source)}</span>
          <a class="title" href="${escAttr(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
          <a class="raw-url" href="${escAttr(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.url)}</a>
        </article>`).join("")}</div>
    </section>`).join("")}</div>`;
}

async function renderManage() {
  document.getElementById("page").innerHTML = `
    <section class="page-heading"><p class="eyebrow">MANAGEMENT</p><h1>Lists, companies &amp; sources</h1><p>Organize monitored companies and review collection health.</p></section>
    <section class="management-section" aria-labelledby="lists-title">
      <div class="section-heading"><div><h2 id="lists-title">Lists</h2><p>Create, rename, delete, and select a list.</p></div>
        <form id="create-list" class="inline-form"><label class="sr-only" for="new-list-name">New list name</label><input id="new-list-name" maxlength="80" placeholder="New list name" required><button class="button primary">Create</button></form>
      </div><div id="list-strip" class="list-strip"></div>
    </section>
    <section class="management-section" aria-labelledby="companies-title">
      <div class="section-heading"><div><h2 id="companies-title">Companies</h2><p id="company-context"></p></div></div>
      <form id="company-search" class="search-form"><label for="company-query">Search by company name or ticker</label><div><input id="company-query" autocomplete="off" placeholder="e.g. Apple or AAPL" required><button class="button primary">Search</button></div><small>Candidate data comes from the local official SEC mapping. Unknown exchange values are not inferred.</small></form>
      <div id="candidate-results"></div><div id="company-table"></div>
    </section>
    <section class="management-section" aria-labelledby="sources-title">
      <div class="section-heading"><div><h2 id="sources-title">Information sources</h2><p>Configured connectors, coverage, latest run, and failure summary.</p></div></div>
      <div id="source-grid"><p class="loading">Loading sources…</p></div>
    </section>`;
  bindManagement();
  await refreshManagement();
}

function bindManagement() {
  document.getElementById("create-list").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const result = await api("/api/lists", {method:"POST", body:JSON.stringify({name:document.getElementById("new-list-name").value})});
      state.selectedList = result.list.slug; toast("List created."); await reloadBootstrap(); await refreshManagement();
    } catch (error) { toast(error.message, true); }
  });
  document.getElementById("company-search").addEventListener("submit", searchCompanies);
}

async function refreshManagement() {
  renderLists(); renderCompanies();
  try { renderSources((await api("/api/sources")).sources); }
  catch (error) { document.getElementById("source-grid").innerHTML = errorState("Request failed", error.message); }
}

function renderLists() {
  const lists = state.bootstrap.lists;
  if (!lists.length) state.selectedList = "";
  if (state.selectedList && !lists.some(list => list.slug === state.selectedList)) state.selectedList = lists[0]?.slug || "";
  document.getElementById("list-strip").innerHTML = lists.length ? lists.map(list => `
    <article class="list-card ${list.slug === state.selectedList ? "selected" : ""}" data-slug="${escAttr(list.slug)}">
      <button class="list-select" type="button"><strong>${esc(list.name)}</strong><span>${list.company_count} companies</span></button>
      <div><button class="text-button rename-list" type="button">Rename</button><button class="text-button danger delete-list" type="button">Delete</button></div>
    </article>`).join("") : `<div class="empty compact"><p>Create a list to start monitoring companies.</p></div>`;
  document.querySelectorAll(".list-select").forEach(button => button.addEventListener("click", () => { state.selectedList = button.closest(".list-card").dataset.slug; renderLists(); renderCompanies(); }));
  document.querySelectorAll(".rename-list").forEach(button => button.addEventListener("click", () => renameList(button.closest(".list-card").dataset.slug)));
  document.querySelectorAll(".delete-list").forEach(button => button.addEventListener("click", () => deleteList(button.closest(".list-card").dataset.slug)));
}

async function renameList(slug) {
  const current = state.bootstrap.lists.find(list => list.slug === slug);
  const name = prompt("List name", current.name);
  if (name === null || !name.trim()) return;
  try { await api("/api/lists/rename", {method:"POST", body:JSON.stringify({slug,name})}); toast("List renamed."); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

async function deleteList(slug) {
  const current = state.bootstrap.lists.find(list => list.slug === slug);
  if (!confirm(`Delete “${current.name}”? Companies in other lists and stored information will be preserved.`)) return;
  try { await api("/api/lists/delete", {method:"POST", body:JSON.stringify({slug})}); toast("List deleted."); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

function renderCompanies() {
  const list = state.bootstrap.lists.find(item => item.slug === state.selectedList);
  const companies = state.bootstrap.companies.filter(company => company.list_slugs.includes(state.selectedList));
  document.getElementById("company-context").textContent = list ? `${list.name} · ${companies.length} companies` : "Create or select a list first.";
  document.getElementById("company-table").innerHTML = companies.length ? `<div class="table-wrap"><table><thead><tr><th>Company</th><th>Ticker</th><th>Exchange</th><th>Region</th><th></th></tr></thead><tbody>${companies.map(company => `<tr><td>${esc(company.name)}</td><td>${esc(company.ticker)}</td><td>${esc(company.exchange || "Unavailable")}</td><td>${regionForMarket(company.market)}</td><td><button class="text-button danger remove-company" data-ticker="${escAttr(company.ticker)}" data-market="${escAttr(company.market)}">Remove</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty compact"><p>No companies in this list.</p></div>`;
  document.querySelectorAll(".remove-company").forEach(button => button.addEventListener("click", () => removeCompany(button.dataset.ticker, button.dataset.market)));
}

async function searchCompanies(event) {
  event.preventDefault();
  if (!state.selectedList) { toast("Create or select a list first.", true); return; }
  const target = document.getElementById("candidate-results"); target.innerHTML = `<p class="loading">Searching candidates…</p>`;
  try {
    const data = await api(`/api/companies/search?q=${encodeURIComponent(document.getElementById("company-query").value.trim())}`);
    target.innerHTML = data.candidates.length ? `<div class="candidate-list">${data.candidates.map(candidate => `<article><div><strong>${esc(candidate.name)}</strong><p>${esc(candidate.ticker)} · ${esc(candidate.exchange)} · ${esc(candidate.region)}</p></div><button class="button add-candidate" data-ticker="${escAttr(candidate.ticker)}" data-market="${escAttr(candidate.market)}">Confirm &amp; add</button></article>`).join("")}</div>` : `<div class="empty compact"><p>No matching official candidates.</p></div>`;
    document.querySelectorAll(".add-candidate").forEach(button => button.addEventListener("click", () => addCandidate(button.dataset.ticker, button.dataset.market)));
  } catch (error) { target.innerHTML = errorState("Search returned no results", error.message); }
}

async function addCandidate(ticker, market) {
  try {
    await api("/api/companies/batch", {method:"POST", body:JSON.stringify({tickers:ticker, lists:[state.selectedList], market})});
    toast(`${ticker} added.`); document.getElementById("candidate-results").innerHTML = ""; await reloadBootstrap(); await refreshManagement();
  } catch (error) { toast(error.message, true); }
}

async function removeCompany(ticker, market) {
  try { await api("/api/memberships/remove", {method:"POST", body:JSON.stringify({ticker, market, list:state.selectedList})}); toast(`${ticker} removed from this list.`); await reloadBootstrap(); await refreshManagement(); }
  catch (error) { toast(error.message, true); }
}

function renderSources(sources) {
  document.getElementById("source-grid").innerHTML = `<div class="source-grid">${sources.map(source => `<article class="source-card"><div class="source-card-head"><div><h3>${esc(source.provider)}</h3><p>${esc(source.type)} · ${source.regions.length ? source.regions.map(esc).join(", ") : "Coverage not provided"}</p></div><span class="status ${escAttr(source.status)}">${statusLabel(source.status)}</span></div><dl><div><dt>Enabled</dt><dd>${source.enabled ? "Yes" : "No"}</dd></div><div><dt>Latest success</dt><dd>${source.latest_success ? formatDateTime(source.latest_success) : "None recorded"}</dd></div><div><dt>Latest attempt</dt><dd>${source.latest_attempt ? formatDateTime(source.latest_attempt) : "None recorded"}</dd></div></dl>${source.last_failure ? `<details><summary>Failure details</summary><p>${esc(source.last_failure)}</p></details>` : ""}</article>`).join("")}</div>`;
}

async function reloadBootstrap() { state.bootstrap = await api("/api/bootstrap"); }
function listOptions(selected) { return state.bootstrap.lists.map(list => `<option value="${escAttr(list.slug)}" ${list.slug === selected ? "selected" : ""}>${esc(list.name)}</option>`).join(""); }
function statusLabel(status) { return ({connected:"Connected",stale:"Data stale",not_connected:"Not connected",temporarily_unavailable:"Failed",unavailable:"Waiting for data"})[status] || status; }
function regionForMarket(market) { return ({us:"United States",jp:"Japan",hk:"Hong Kong",cn:"China"})[market] || "Unavailable"; }
function formatDay(value) { return new Intl.DateTimeFormat("en-US", {dateStyle:"full", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatTime(value) { return new Intl.DateTimeFormat("en-US", {hour:"numeric", minute:"2-digit", timeZone:"America/New_York", timeZoneName:"short"}).format(new Date(value)); }
function formatDateTime(value) { return new Intl.DateTimeFormat("en-US", {dateStyle:"medium", timeStyle:"short", timeZone:"America/New_York"}).format(new Date(value)) + " ET"; }
function errorState(title, message) { return `<div class="empty error"><h2>${esc(title)}</h2><p>${esc(message)}</p></div>`; }
async function api(url, options={}) { const response = await fetch(url, {headers:{"Content-Type":"application/json"}, ...options}); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`); return payload; }
function toast(message, error=false) { const node=document.createElement("div"); node.className=`toast ${error?"error":""}`; node.textContent=message; document.getElementById("toast-region").appendChild(node); setTimeout(()=>node.remove(),4000); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
function escAttr(value) { return esc(value); }
function renderFatal(error) { document.getElementById("page").innerHTML = errorState("Workspace request failed", error.message); }