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
          <span class="source">${esc(item.source)}${(item.also_seen_on || []).length ? ` · Also seen on ${item.also_seen_on.map(esc).join(", ")}` : ""}</span>
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
      <form id="company-search" class="search-form">
        <label for="company-query">Search by company name or ticker</label>
        <div>
          <select id="market-select" aria-label="Market">
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
          <button class="button primary" type="submit">Search</button>
          <button class="button" id="add-ticker-direct" type="button">Add ticker</button>
        </div>
        <small id="market-hint">US candidates come from the local official SEC mapping. Non-US markets are added as unmapped.</small>
      </form>
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
  document.getElementById("market-select").addEventListener("change", updateMarketHint);
  document.getElementById("add-ticker-direct").addEventListener("click", addTickerDirect);
  updateMarketHint();
}

const MARKET_HINTS = {
  us: "US candidates come from the local official SEC mapping.",
  jp: "Japan companies are added as unmapped. Use Add ticker with the local code; EDINET/TDnet collect by market=jp.",
  hk: "HKEXnews announcement search is connected (unofficial page API; may change). HKEX DI is available but disabled by default (legacy archive 2003-2017). Yahoo Finance HK news via public RSS. Universe cache can backfill names. Finnhub is US-only.",
  cn: "A-share companies are added as unmapped (no SEC mapping).",
  kr: "Korea companies resolve via OpenDART when configured; otherwise add as unmapped.",
  uk: "UK companies resolve via Companies House when configured.",
  tw: "TWSE (listed) and TPEx (OTC) OpenAPI material-information are connected (key-free; not a paid MOPS push). 興櫃 disclosure is not wired. Yahoo Finance TW and Google News (TW) via key-free RSS. Universe cache can backfill names/board. Finnhub is US-only.",
  ca: "CA market (partial — not a full Canadian stack): root tickers strip .TO/.TSX/.V/.TSXV/.CN/.NE/.NEO; board backfills from ca_universe (TSX/TSXV) or typed suffix when cold. Universe does NOT cover CSE/NEO directories. Disclosure is NOT wired: SEDAR+/CSE/NEO filings unwired. News: Yahoo Finance CA + Google News CA. Finnhub is US-only.",
  au: "AU market: root tickers strip .AX/.ASX. ASX announcements via key-free research API (latest 5 per company; may change). Universe backfills names/board. News: Yahoo Finance AU + Google News AU. Finnhub is US-only.",
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

function updateMarketHint() {
  const market = document.getElementById("market-select").value;
  document.getElementById("market-hint").textContent = MARKET_HINTS[market] || MARKET_HINTS.us;
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
  const market = document.getElementById("market-select").value;
  if (market !== "us") {
    toast("Non-US markets: use Add ticker (SEC search is US-only).", true);
    return;
  }
  const target = document.getElementById("candidate-results"); target.innerHTML = `<p class="loading">Searching candidates…</p>`;
  try {
    const data = await api(`/api/companies/search?q=${encodeURIComponent(document.getElementById("company-query").value.trim())}`);
    target.innerHTML = data.candidates.length ? `<div class="candidate-list">${data.candidates.map(candidate => `<article><div><strong>${esc(candidate.name)}</strong><p>${esc(candidate.ticker)} · ${esc(candidate.exchange)} · ${esc(candidate.region)}</p></div><button class="button add-candidate" data-ticker="${escAttr(candidate.ticker)}" data-market="${escAttr(candidate.market)}">Confirm &amp; add</button></article>`).join("")}</div>` : `<div class="empty compact"><p>No matching official candidates.</p></div>`;
    document.querySelectorAll(".add-candidate").forEach(button => button.addEventListener("click", () => addCandidate(button.dataset.ticker, button.dataset.market)));
  } catch (error) { target.innerHTML = errorState("Search returned no results", error.message); }
}

async function addTickerDirect() {
  if (!state.selectedList) { toast("Create or select a list first.", true); return; }
  const tickers = document.getElementById("company-query").value.trim();
  if (!tickers) { toast("Enter a ticker first.", true); return; }
  const market = document.getElementById("market-select").value;
  try {
    const result = await api("/api/companies/batch", {method:"POST", body:JSON.stringify({tickers, lists:[state.selectedList], market})});
    const added = (result.added || []).map(row => row.ticker).join(", ") || tickers;
    toast(`${added} added (${market}).`);
    document.getElementById("candidate-results").innerHTML = "";
    await reloadBootstrap();
    await refreshManagement();
  } catch (error) { toast(error.message, true); }
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
function regionForMarket(market) { return ({us:"United States",jp:"Japan",hk:"Hong Kong",cn:"China",kr:"Korea",uk:"United Kingdom",tw:"Taiwan",ca:"Canada",au:"Australia",be:"Belgium",fr:"France",de:"Germany",nl:"Netherlands",it:"Italy",es:"Spain",sg:"Singapore",ch:"Switzerland",pl:"Poland",se:"Sweden",aq:"Aquis (AQSE)",cxe:"Cboe Europe (CXE)",emf:"Europe (Funds)",trq:"Turquoise (TRQ)",eux:"Europe (Eurex)"})[market] || "Unavailable"; }
function formatDay(value) { return new Intl.DateTimeFormat("en-US", {dateStyle:"full", timeZone:"UTC"}).format(new Date(`${value}T12:00:00Z`)); }
function formatTime(value) { return new Intl.DateTimeFormat("en-US", {hour:"numeric", minute:"2-digit", timeZone:"America/New_York", timeZoneName:"short"}).format(new Date(value)); }
function formatDateTime(value) { return new Intl.DateTimeFormat("en-US", {dateStyle:"medium", timeStyle:"short", timeZone:"America/New_York"}).format(new Date(value)) + " ET"; }
function errorState(title, message) { return `<div class="empty error"><h2>${esc(title)}</h2><p>${esc(message)}</p></div>`; }
async function api(url, options={}) { const response = await fetch(url, {headers:{"Content-Type":"application/json"}, ...options}); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`); return payload; }
function toast(message, error=false) { const node=document.createElement("div"); node.className=`toast ${error?"error":""}`; node.textContent=message; document.getElementById("toast-region").appendChild(node); setTimeout(()=>node.remove(),4000); }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char])); }
function escAttr(value) { return esc(value); }
function renderFatal(error) { document.getElementById("page").innerHTML = errorState("Workspace request failed", error.message); }
