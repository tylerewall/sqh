const SQH = (() => {
  let currentUser = null;
  let storedQueries = [];
  let selectedQuery = null;
  let currentResults = [];
  let currentHistoryId = null;
  let _totalCount = 0;
  let _hasMore = false;
  let _currentQueryName = "";
  let _dashChartInstances = [];
  let _dashAutoTimer = null;
  let _dashCountdownTimer = null;
  let _dashNextRefresh = null;
  let _dashStoredQueryId = null;
  let _dashRefreshing = false;
  const DASH_REFRESH_MS = 60 * 60 * 1000;
  let _aiTools = [];
  let _aiToolsPanelOpen = true;
  let runningQueries = [];
  let pollingTimer = null;
  let sortCol = null;
  let sortAsc = true;
  let hiddenCols = new Set();
  let allFolders = [];
  let wizardStep = 1;
  let wizardConfig = {};

  // ── API Helper ──
  async function api(url, opts = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
    if (res.status === 401) { showScreen("login"); return null; }
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data?.detail || `Error ${res.status}`;
      toast(msg, "error");
      throw new Error(msg);
    }
    return data;
  }

  // ── Toast ──
  function toast(msg, type = "info") {
    const c = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, 3500);
  }

  function _showTooManyResultsDialog(queryName, count) {
    const existing = document.getElementById("too-many-dialog");
    if (existing) existing.remove();
    const overlay = document.createElement("div");
    overlay.id = "too-many-dialog";
    overlay.className = "dialog-overlay";
    overlay.innerHTML = `
      <div class="dialog-box">
        <div class="dialog-icon">&#9888;</div>
        <h3>Too Many Results</h3>
        <p>Your query <strong>"${esc(queryName)}"</strong> returned <strong>${count.toLocaleString()}</strong> results, which exceeds the 20,000 event limit.</p>
        <p>This many results is unlikely to be useful. Consider narrowing your search by:</p>
        <ul>
          <li>Using a shorter time range (e.g. 1 hour or 15 minutes)</li>
          <li>Adding an <code>EndpointName</code> or <code>UserName</code> filter</li>
          <li>Using more specific search terms</li>
        </ul>
        <div class="dialog-actions">
          <button class="btn btn-primary" onclick="document.getElementById('too-many-dialog').remove()">OK</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
  }

  // ── Screens ──
  function showScreen(name) {
    document.getElementById("screen-login").classList.toggle("hidden", name !== "login");
    document.getElementById("screen-password-change").classList.toggle("hidden", name !== "password-change");
    document.getElementById("app-shell").classList.toggle("hidden", name !== "app");
  }

  // ── Auth ──
  async function checkAuth() {
    try {
      const data = await api("/api/auth/me");
      if (!data) return;
      currentUser = data.user;
      if (currentUser.force_password_change) { showScreen("password-change"); return; }
      enterApp();
    } catch { showScreen("login"); }
  }

  async function login() {
    const u = document.getElementById("login-user").value;
    const p = document.getElementById("login-pass").value;
    const errEl = document.getElementById("login-error");
    errEl.classList.add("hidden");
    try {
      const data = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: u, password: p }) });
      if (!data) return;
      currentUser = data.user;
      if (currentUser.force_password_change) { showScreen("password-change"); return; }
      enterApp();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  }

  async function changePassword() {
    const cur = document.getElementById("pw-current").value;
    const nw = document.getElementById("pw-new").value;
    const cf = document.getElementById("pw-confirm").value;
    const errEl = document.getElementById("pw-change-error");
    errEl.classList.add("hidden");
    if (nw !== cf) { errEl.textContent = "Passwords do not match"; errEl.classList.remove("hidden"); return; }
    try {
      await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: cur, new_password: nw }) });
      currentUser.force_password_change = false;
      enterApp();
      toast("Password changed successfully", "success");
    } catch (e) { errEl.textContent = e.message; errEl.classList.remove("hidden"); }
  }

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    currentUser = null;
    showScreen("login");
  }

  function enterApp() {
    showScreen("app");
    document.getElementById("user-avatar").textContent = currentUser.full_name[0];
    document.getElementById("user-display").textContent = currentUser.username;
    document.getElementById("dropdown-name").textContent = currentUser.full_name;
    document.getElementById("dropdown-role").textContent = currentUser.role === "admin" ? "Admin" : "Standard User";
    document.getElementById("nav-admin").classList.toggle("hidden", currentUser.role !== "admin");
    loadDiskIndicator();
    loadQueries();
    loadRunningOnStart();
  }

  // ── Navigation ──
  function nav(page) {
    if (page !== "queries") _stopDashAutoRefresh();
    document.querySelectorAll(".topnav-links a").forEach(a => a.classList.remove("active"));
    const link = document.querySelector(`.topnav-links a[data-page="${page}"]`);
    if (link) link.classList.add("active");
    ["queries", "history", "admin"].forEach(p => document.getElementById(`page-${p}`).classList.toggle("hidden", p !== page));
    if (page === "history") loadHistory();
    if (page === "admin") { loadAdminTab("users"); }
    return false;
  }

  // ── Disk Indicator ──
  async function loadDiskIndicator() {
    try {
      const data = await api("/api/system/disk");
      if (!data) return;
      const d = data.disk;
      const fill = document.getElementById("disk-mini-fill");
      fill.style.width = d.percent + "%";
      fill.className = "disk-bar-mini-fill" + (d.percent >= d.threshold ? " crit" : d.percent >= d.threshold - 15 ? " warn" : "");
      document.getElementById("disk-mini-pct").textContent = d.percent + "%";
      document.getElementById("disk-indicator").title = `Disk: ${d.used_gb} GB / ${d.total_gb} GB (${d.percent}%)`;
    } catch {}
  }

  // ── Theme ──
  function toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute("data-theme") === "light" ? "dark" : "light";
    html.setAttribute("data-theme", next);
    document.getElementById("theme-icon-sun").classList.toggle("hidden", next === "dark");
    document.getElementById("theme-icon-moon").classList.toggle("hidden", next === "light");
    localStorage.setItem("sqh-theme", next);
  }

  // ── Queries Page ──
  let _activeFolderId = null;

  async function loadQueries() {
    try {
      const data = await api("/api/queries");
      if (!data) return;
      storedQueries = data.queries;
      allFolders = data.folders || [];
      renderQueryList();
    } catch {}
  }

  function renderQueryList() {
    const filterEl = document.getElementById("category-filter");
    const listEl = document.getElementById("query-list");

    const folderBtns = allFolders.map(f =>
      `<button class="${_activeFolderId === f.id ? "active" : ""}" onclick="SQH.filterQueries(${f.id})">${esc(f.name)}</button>`
    ).join("");
    filterEl.innerHTML = `<button class="${_activeFolderId === null ? "active" : ""}" onclick="SQH.filterQueries(null)">All</button>${folderBtns}`;

    let queries;
    if (_activeFolderId === null) {
      queries = storedQueries;
    } else {
      queries = storedQueries.filter(q => q.folder_id === _activeFolderId);
    }

    if (!queries.length) {
      listEl.innerHTML = '<div class="empty-state">No stored queries in this folder</div>';
      return;
    }

    const grouped = {};
    queries.forEach(q => {
      const folderLabel = q.folder_name || "Uncategorized";
      if (!grouped[folderLabel]) grouped[folderLabel] = [];
      grouped[folderLabel].push(q);
    });

    let html = "";
    for (const [folder, qs] of Object.entries(grouped)) {
      if (_activeFolderId === null && allFolders.length > 0) {
        html += `<div class="folder-group-label">${esc(folder)}</div>`;
      }
      qs.forEach(q => {
        html += `
          <div class="query-card ${selectedQuery?.id === q.id ? "selected" : ""}" onclick="SQH.selectQuery(${q.id})">
            <div class="query-card-title">${esc(q.name)}</div>
            <div class="query-card-desc">${esc(q.description)}</div>
            <div class="query-card-meta">
              <span class="badge badge-info">${esc(q.category)}</span>
              <span class="badge badge-muted">${q.params.length} param${q.params.length !== 1 ? "s" : ""}</span>
            </div>
          </div>`;
      });
    }
    listEl.innerHTML = html;
  }

  function filterQueries(folderId) { _activeFolderId = folderId !== undefined ? folderId : null; renderQueryList(); }

  function selectQuery(id) {
    _stopDashAutoRefresh();
    selectedQuery = storedQueries.find(q => q.id === id);
    renderQueryList();
    renderQueryDetail();
  }

  function renderQueryDetail() {
    const el = document.getElementById("query-detail");
    if (!selectedQuery) { el.innerHTML = '<div class="empty-state">Select a query to begin threat hunting</div>'; return; }
    const q = selectedQuery;
    const paramsHtml = q.params.map(p => {
      let input;
      if (p.param_type === "text") input = `<input type="text" id="param-${p.name}" placeholder="${esc(p.placeholder)}" class="w-full">`;
      else if (p.param_type === "datetime") input = `<input type="datetime-local" id="param-${p.name}" class="w-full">`;
      else if (p.param_type === "dropdown") input = `<select id="param-${p.name}" class="w-full">${(p.options||[]).map(o => `<option>${esc(o)}</option>`).join("")}</select>`;
      else input = `<input type="text" id="param-${p.name}" class="w-full">`;
      return `<div class="form-group"><label>${esc(p.label)}</label>${input}</div>`;
    }).join("");

    el.innerHTML = `
      <div class="dv-query-bar">
        <span class="dv-label">S1QL</span>
        <code>${esc(q.dv_query)}</code>
      </div>
      <div class="query-detail-body">
        <div class="query-detail-header">${esc(q.name)}</div>
        <div class="query-detail-desc">${esc(q.description)}</div>
        ${paramsHtml ? '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px">' + q.params.map(p => {
          let input;
          if (p.param_type === "text") input = `<input type="text" id="param-${p.name}" placeholder="${esc(p.placeholder)}" class="w-full">`;
          else if (p.param_type === "datetime") input = `<input type="datetime-local" id="param-${p.name}" class="w-full">`;
          else if (p.param_type === "dropdown") input = `<select id="param-${p.name}" class="w-full">${(p.options||[]).map(o => `<option>${esc(o)}</option>`).join("")}</select>`;
          else input = `<input type="text" id="param-${p.name}" class="w-full">`;
          return `<div class="form-group" style="margin-bottom:0"><label>${esc(p.label)}</label>${input}</div>`;
        }).join("") + '</div>' : ''}
        
      </div>
      <div class="query-detail-actions">
        <span class="text-sm text-muted">${esc(q.category)} &middot; ${q.params.length} parameter${q.params.length !== 1 ? "s" : ""}</span>
        <button class="run-btn" onclick="SQH.runQuery(false)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Execute Query</button>
        <button class="run-btn run-btn-refresh" onclick="SQH.runQuery(true)" title="Skip cache and fetch fresh data from SentinelOne"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M1 4v6h6M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg> Force Refresh</button>
      </div>`;

    _setDefaultDateRange();
  }

  let _selectedRange = "1h";

  function _setDefaultDateRange() {}

  function setGlobalTime(range, btn) {
    _selectedRange = range;
    document.querySelectorAll(".g-time-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    const custom = document.getElementById("global-custom-fields");
    if (range === "custom") {
      custom.classList.remove("hidden");
    } else {
      custom.classList.add("hidden");
    }
  }

  function setDateRange(range, btn) { setGlobalTime(range, btn); }

  function _computeDateRange() {
    const now = new Date();
    let from_date = "", to_date = "";
    to_date = now.toISOString().replace(/\.\d{3}Z$/, ".000Z");

    if (_selectedRange === "custom") {
      const fEl = document.getElementById("global-from-date");
      const tEl = document.getElementById("global-to-date");
      if (fEl && fEl.value) {
        const fd = new Date(fEl.value + "T00:00:00");
        from_date = fd.toISOString().replace(/\.\d{3}Z$/, ".000Z");
      }
      if (tEl && tEl.value) {
        const td = new Date(tEl.value + "T23:59:59");
        to_date = td.toISOString().replace(/\.\d{3}Z$/, ".000Z");
      }
    } else {
      const hours = _selectedRange === "15m" ? 0.25 : _selectedRange === "30m" ? 0.5 : _selectedRange === "1h" ? 1 : _selectedRange === "24h" ? 24 : _selectedRange === "3d" ? 72 : _selectedRange === "7d" ? 168 : _selectedRange === "14d" ? 336 : 720;
      const from = new Date(now.getTime() - hours * 3600000);
      from_date = from.toISOString().replace(/\.\d{3}Z$/, ".000Z");
    }
    return { from_date, to_date };
  }

  async function runQuery(forceRefresh = false) {
    if (!selectedQuery) return;
    const paramValues = {};
    selectedQuery.params.forEach(p => {
      const el = document.getElementById(`param-${p.name}`);
      if (el) paramValues[p.name] = el.value;
    });

    const { from_date, to_date } = _computeDateRange();

    try {
      const data = await api(`/api/queries/${selectedQuery.id}/run`, {
        method: "POST",
        body: JSON.stringify({ param_values: paramValues, from_date, to_date, force_refresh: forceRefresh }),
      });
      if (!data) return;
      const rangeLabel = _selectedRange === "custom" ? "custom range" : _selectedRange === "15m" ? "last 15 min" : _selectedRange === "30m" ? "last 30 min" : _selectedRange === "1h" ? "last 1 hour" : _selectedRange === "24h" ? "last 24 hours" : `last ${_selectedRange.replace("d"," days")}`;
      toast(`"${data.query_name}" submitted (${rangeLabel})${forceRefresh ? " (force refresh)" : ""} — running`, "info");
      runningQueries.push({ history_id: data.history_id, query_name: data.query_name, started: new Date() });
      renderRunningQueries();
      startPolling();
    } catch {}
  }

  function renderRunningQueries() {
    const panel = document.getElementById("running-queries");
    if (!runningQueries.length) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    panel.innerHTML = `
      <div class="results-card" style="margin:0 16px">
        <div class="results-header">
          <div class="results-header-left">
            <span class="results-count">${runningQueries.length}</span>
            <span class="results-title">Running</span>
          </div>
        </div>
        ${runningQueries.map(rq => {
          const pct = rq.progress_percent || 0;
          const count = rq._lastLiveCount || 0;
          const stage = rq.progress_stage || `Started ${_timeAgo(rq.started)}`;
          return `
          <div class="running-query-row" style="flex-direction:column;align-items:stretch;gap:6px;padding:12px 16px">
            <div style="display:flex;align-items:center;justify-content:space-between">
              <div class="running-query-info">
                <div class="spinner-sm"></div>
                <div>
                  <div style="font-weight:600;font-size:.85rem">${esc(rq.query_name)}</div>
                  <div style="font-size:.7rem;color:var(--text3)">${esc(stage)}</div>
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                ${count > 0 ? `<span class="live-count">${count.toLocaleString()} events</span>` : ""}
                <button class="btn btn-danger btn-sm" onclick="SQH.cancelQuery(${rq.history_id})">Cancel</button>
              </div>
            </div>
            <div class="progress-bar-full">
              <div class="progress-bar-full-fill" style="width:${pct}%"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:.65rem;color:var(--text3)">
              <span>${pct}% complete</span>
              <span>${count > 0 ? count.toLocaleString() + " / 20,000 max" : "Waiting for results..."}</span>
            </div>
          </div>`;
        }).join("")}
      </div>`;
  }

  function _timeAgo(d) {
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 5) return "just now";
    if (s < 60) return s + "s ago";
    return Math.floor(s / 60) + "m " + (s % 60) + "s ago";
  }

  function startPolling() {
    if (pollingTimer) return;
    pollingTimer = setInterval(pollRunningQueries, 1500);
  }

  function stopPolling() {
    if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null; }
  }

  async function pollRunningQueries() {
    if (!runningQueries.length) { stopPolling(); renderRunningQueries(); return; }

    const still = [];
    let anyFinished = false;
    let lastSuccessId = null;
    for (const rq of runningQueries) {
      try {
        const data = await api(`/api/queries/status/${rq.history_id}`);
        if (!data) { still.push(rq); continue; }
        if (data.status === "running") {
          rq.progress_percent = data.progress_percent || 0;
          rq.progress_stage = data.progress_stage || "";
          if (data.result_count > 0) {
            if (data.result_count !== rq._lastLiveCount) {
              rq._lastLiveCount = data.result_count;
              viewHistoryResults(rq.history_id);
            }
          }
          still.push(rq);
        } else if (data.status === "success") {
          toast(`"${rq.query_name}" completed — ${data.result_count} results`, "success");
          anyFinished = true;
          lastSuccessId = rq.history_id;
        } else if (data.status === "cancelled") {
          toast(`"${rq.query_name}" cancelled`, "info");
          anyFinished = true;
        } else {
          const errMsg = data.error_message || "unknown error";
          if (errMsg.includes("too many")) {
            _showTooManyResultsDialog(rq.query_name, 20000);
          } else {
            toast(`"${rq.query_name}" failed: ${errMsg}`, "error");
          }
          anyFinished = true;
        }
      } catch { still.push(rq); }
    }
    runningQueries = still;
    renderRunningQueries();
    if (!runningQueries.length) stopPolling();
    if (anyFinished) loadHistory();
    if (lastSuccessId) viewHistoryResults(lastSuccessId);
  }

  async function cancelQuery(historyId) {
    try {
      await api(`/api/queries/cancel/${historyId}`, { method: "POST" });
      runningQueries = runningQueries.filter(rq => rq.history_id !== historyId);
      renderRunningQueries();
      toast("Query cancelled", "info");
    } catch {}
  }

  async function loadRunningOnStart() {
    try {
      const data = await api("/api/queries/running");
      if (!data || !data.running.length) return;
      data.running.forEach(r => {
        runningQueries.push({ history_id: r.id, query_name: r.query_name, started: new Date(r.executed_at) });
      });
      renderRunningQueries();
      startPolling();
    } catch {}
  }

  // ── Results Table ──
  let _allCols = [];
  let _filteredData = null;

  function _getVisibleCols() {
    return _allCols.filter(c => !hiddenCols.has(c));
  }

  function _isEmptyCol(col) {
    return currentResults.every(r => {
      const v = r[col];
      return v === null || v === undefined || v === "" || v === "null";
    });
  }

  function renderResults() {
    const area = document.getElementById("results-area");
    if (!currentResults.length) {
      area.innerHTML = '<div class="results-card"><div class="empty-state">No events returned</div></div>';
      area.classList.remove("hidden");
      return;
    }

    _allCols = Object.keys(currentResults[0]);
    const autoHidden = _allCols.filter(c => _isEmptyCol(c));
    hiddenCols = new Set(autoHidden);
    _filteredData = null;

    const visCols = _getVisibleCols();
    const isStreaming = runningQueries.some(rq => rq.history_id === currentHistoryId);
    const streamingBadge = isStreaming ? '<span class="streaming-badge"><span class="spinner-sm"></span> Live</span>' : '';
    const loadMoreHtml = _hasMore
      ? `<div id="load-more-wrap" class="load-more-wrap"><button id="load-more-btn" class="btn btn-primary" onclick="SQH.loadMoreResults()">Load More (${currentResults.length} of ${_totalCount})</button></div>`
      : '<div id="load-more-wrap" class="load-more-wrap hidden"></div>';

    area.innerHTML = `
      <div class="results-card">
        <div class="results-header">
          <div class="results-header-left">
            <span class="results-count">${currentResults.length}</span>
            <span class="results-title">of <span id="results-total">${_totalCount}</span> Events</span>
            ${streamingBadge}
            <span class="results-meta">${visCols.length}/${_allCols.length} columns</span>
          </div>
          <div class="flex gap-sm">
            <input type="text" id="results-filter-input" class="search-input" placeholder="Filter events..." oninput="SQH.filterResults(this.value)">
            <button class="btn btn-sm" onclick="SQH.toggleColumnPicker(event)">Columns</button>
            <button class="btn btn-sm" onclick="SQH.shareResults()">Share</button>
            <div class="export-dropdown">
              <button class="btn btn-sm" onclick="SQH.toggleExport(event)">Export</button>
              <div class="export-menu" id="export-menu">
                <button onclick="SQH.exportData('csv')">CSV</button>
                <button onclick="SQH.exportData('json')">JSON</button>
                <button onclick="SQH.exportData('pdf')">PDF</button>
              </div>
            </div>
          </div>
        </div>
        <div id="column-picker" class="column-picker hidden">
          <div class="col-picker-header"><span>Show / Hide Columns</span><button class="btn btn-sm" onclick="SQH.resetColumns()">Show All</button></div>
          <div class="col-picker-list">${_allCols.map(c => `<label class="col-picker-item"><input type="checkbox" ${!hiddenCols.has(c) ? "checked" : ""} onchange="SQH.toggleColumn('${esc(c)}',this.checked)"> ${esc(c)}</label>`).join("")}</div>
        </div>
        <div class="raw-results-wrap" id="results-table-wrap"><table class="raw-results-table"><thead><tr id="results-thead-tr">${visCols.map(c => `<th onclick="SQH.sortResults('${esc(c)}')">${esc(c)} ${sortCol === c ? (sortAsc ? "&#9650;" : "&#9660;") : ""}</th>`).join("")}</tr></thead><tbody id="results-tbody"></tbody></table></div>
        ${loadMoreHtml}
      </div>`;
    area.classList.remove("hidden");
    fillResultsBody(visCols, currentResults);
  }

  const BATCH_SIZE = 200;
  let _renderBatchId = 0;

  function fillResultsBody(cols, data) {
    const tbody = document.getElementById("results-tbody");
    if (!tbody) return;
    _renderBatchId++;
    const batchId = _renderBatchId;
    tbody.innerHTML = "";
    _renderBatch(tbody, cols, data, 0, batchId);
  }

  function _renderBatch(tbody, cols, data, offset, batchId) {
    if (batchId !== _renderBatchId) return;
    const end = Math.min(offset + BATCH_SIZE, data.length);
    const frag = document.createDocumentFragment();
    for (let i = offset; i < end; i++) {
      const row = data[i];
      const tr = document.createElement("tr");
      for (const c of cols) {
        const td = document.createElement("td");
        let v = row[c];
        if (v === null || v === undefined) v = "";
        const vs = typeof v === "object" ? JSON.stringify(v) : String(v);
        if (c === "ThreatStatus" || c === "threatStatus") {
          const cls = vs === "Malicious" ? "badge-danger" : vs === "Suspicious" ? "badge-warning" : "badge-success";
          td.innerHTML = `<span class="badge ${cls}">${esc(vs)}</span>`;
        } else {
          td.className = "raw-cell";
          td.textContent = vs;
        }
        tr.appendChild(td);
      }
      frag.appendChild(tr);
    }
    tbody.appendChild(frag);
    if (end < data.length) {
      requestAnimationFrame(() => _renderBatch(tbody, cols, data, end, batchId));
    }
  }

  function _rebuildTable() {
    const visCols = _getVisibleCols();
    const theadTr = document.getElementById("results-thead-tr");
    if (theadTr) {
      theadTr.innerHTML = visCols.map(c => `<th onclick="SQH.sortResults('${esc(c)}')">${esc(c)} ${sortCol === c ? (sortAsc ? "&#9650;" : "&#9660;") : ""}</th>`).join("");
    }
    const data = _filteredData || currentResults;
    fillResultsBody(visCols, data);
    const countEl = document.querySelector(".results-count");
    if (countEl) countEl.textContent = data.length;
    const meta = document.querySelector(".results-meta");
    if (meta) meta.textContent = `${visCols.length}/${_allCols.length} columns`;
  }

  function toggleColumnPicker(e) {
    e.stopPropagation();
    const picker = document.getElementById("column-picker");
    picker.classList.toggle("hidden");
    picker.onclick = ev => ev.stopPropagation();
  }

  function toggleColumn(col, checked) {
    if (checked) hiddenCols.delete(col); else hiddenCols.add(col);
    _rebuildTable();
  }

  function resetColumns() {
    hiddenCols.clear();
    renderResults();
  }

  function sortResults(col) {
    if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = true; }
    currentResults.sort((a, b) => {
      const va = a[col] ?? "", vb = b[col] ?? "";
      return sortAsc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va > vb ? -1 : va < vb ? 1 : 0);
    });
    _rebuildTable();
  }

  function filterResults(term) {
    const t = term.toLowerCase();
    if (!t) { _filteredData = null; } else {
      _filteredData = currentResults.filter(r => Object.values(r).some(v => String(v ?? "").toLowerCase().includes(t)));
    }
    _rebuildTable();
  }

  function toggleExport(e) { e.stopPropagation(); document.getElementById("export-menu").classList.toggle("show"); }

  function exportData(fmt) {
    document.getElementById("export-menu").classList.remove("show");
    if (!currentHistoryId) { toast("No results to export", "error"); return; }
    window.open(`/api/history/${currentHistoryId}/export/${fmt}`, "_blank");
  }

  async function shareResults() {
    if (!currentHistoryId) return;
    try {
      await api(`/api/history/${currentHistoryId}/share`, { method: "POST" });
      toast("Results shared with all users", "success");
    } catch {}
  }

  // ── AI Dashboard ──
  function _isAIDashboardQuery(name) {
    const n = (name || "").toLowerCase();
    return (n.includes("ai") && n.includes("detect")) || n.includes("ai tool") || n.includes("ai usage");
  }

  async function _loadAITools() {
    try {
      const data = await api("/api/ai-tools");
      if (data && data.tools) _aiTools = data.tools;
    } catch {}
  }

  function _extractAppName(row) {
    const cmd = (row.ProcessCmd || row.SrcProcCmdLine || row.processCmd || "").toLowerCase();
    const proc = (row.ProcessName || row.SrcProcName || row.processName || "").toLowerCase();
    const combined = cmd + " " + proc;
    for (const tool of _aiTools) {
      if (combined.includes(tool.keyword)) return tool.display_name;
    }
    return proc || "Unknown";
  }

  function _aggregateAIData(results) {
    const appCounts = {};
    const endpointCounts = {};
    const userCounts = {};
    const endpointApps = {};
    const userApps = {};
    let rawTotal = 0;

    for (const row of results) {
      const n = row._eventCount || 1;
      rawTotal += n;
      const app = _extractAppName(row);
      const endpoint = row.EndpointName || row.endpointName || row.agentComputerName || "Unknown";
      const user = row.UserName || row.userName || row.user || "Unknown";

      appCounts[app] = (appCounts[app] || 0) + n;
      endpointCounts[endpoint] = (endpointCounts[endpoint] || 0) + n;
      userCounts[user] = (userCounts[user] || 0) + n;

      if (!endpointApps[endpoint]) endpointApps[endpoint] = {};
      endpointApps[endpoint][app] = (endpointApps[endpoint][app] || 0) + n;

      if (!userApps[user]) userApps[user] = {};
      userApps[user][app] = (userApps[user][app] || 0) + n;
    }

    const sortDesc = obj => Object.entries(obj).sort((a, b) => b[1] - a[1]);

    return {
      rawTotal,
      uniqueMatches: results.length,
      uniqueApps: Object.keys(appCounts).length,
      uniqueEndpoints: Object.keys(endpointCounts).length,
      uniqueUsers: Object.keys(userCounts).length,
      topApps: sortDesc(appCounts),
      topEndpoints: sortDesc(endpointCounts),
      topUsers: sortDesc(userCounts),
      endpointApps,
      userApps,
    };
  }

  function _formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return String(n);
  }

  function _buildAppBreakdown(appsObj) {
    return Object.entries(appsObj).sort((a, b) => b[1] - a[1])
      .map(([app, cnt]) => `${esc(app)} (${cnt})`).join(", ");
  }

  function _formatCountdown(ms) {
    if (ms <= 0) return "now";
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return m + "m " + String(s).padStart(2, "0") + "s";
  }

  function renderAIDashboard() {
    const area = document.getElementById("results-area");
    const agg = _aggregateAIData(currentResults);

    const topAppsRows = agg.topApps.slice(0, 20).map(([app, cnt]) =>
      `<tr class="drill-row" onclick="SQH.drillDown('app','${esc(app)}')"><td>${esc(app)}</td><td>${cnt.toLocaleString()}</td></tr>`
    ).join("");

    const topEndpointRows = agg.topEndpoints.slice(0, 20).map(([ep, cnt]) => {
      const breakdown = _buildAppBreakdown(agg.endpointApps[ep] || {});
      return `<tr class="drill-row" onclick="SQH.drillDown('endpoint','${esc(ep)}')"><td style="font-weight:500">${esc(ep)}</td><td class="text-sm" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)" title="${esc(breakdown)}">${breakdown}</td><td>${cnt.toLocaleString()}</td></tr>`;
    }).join("");

    const topUserRows = agg.topUsers.slice(0, 20).map(([usr, cnt]) => {
      const breakdown = _buildAppBreakdown(agg.userApps[usr] || {});
      return `<tr class="drill-row" onclick="SQH.drillDown('user','${esc(usr)}')"><td style="font-weight:500">${esc(usr)}</td><td class="text-sm" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)" title="${esc(breakdown)}">${breakdown}</td><td>${cnt.toLocaleString()}</td></tr>`;
    }).join("");

    const countdownText = _dashNextRefresh ? _formatCountdown(_dashNextRefresh - Date.now()) : "--";

    area.innerHTML = `
      <div class="results-card" style="border:none;display:flex;flex-direction:column;flex:1;min-height:0;position:relative">
        <div class="results-header">
          <div class="results-header-left">
            <span class="results-count">${agg.rawTotal.toLocaleString()}</span>
            <span class="results-title">Events &rarr; ${agg.uniqueMatches.toLocaleString()} Unique</span>
          </div>
          <div class="flex gap-sm">
            <button class="btn btn-sm" onclick="SQH.shareResults()">Share</button>
            <div class="export-dropdown">
              <button class="btn btn-sm" onclick="SQH.toggleExport(event)">Export</button>
              <div class="export-menu" id="export-menu">
                <button onclick="SQH.exportData('csv')">CSV</button>
                <button onclick="SQH.exportData('json')">JSON</button>
                <button onclick="SQH.exportData('pdf')">PDF</button>
              </div>
            </div>
          </div>
        </div>
        
        <div class="ai-dashboard">
          <div class="dash-cards">
            <div class="dash-card"><div class="dash-card-value">${_formatNumber(agg.rawTotal)}</div><div class="dash-card-label">Raw Events from S1</div></div>
            <div class="dash-card"><div class="dash-card-value">${_formatNumber(agg.uniqueMatches)}</div><div class="dash-card-label">Unique Matches</div></div>
            <div class="dash-card"><div class="dash-card-value">${agg.uniqueApps}</div><div class="dash-card-label">Apps Detected</div></div>
            <div class="dash-card"><div class="dash-card-value">${_formatNumber(agg.uniqueEndpoints)}</div><div class="dash-card-label">Unique Endpoints</div></div>
            <div class="dash-card"><div class="dash-card-value">${_formatNumber(agg.uniqueUsers)}</div><div class="dash-card-label">Unique Users</div></div>
          </div>

          <div class="dash-section ai-tools-panel">
            <div class="dash-section-header ai-tools-header" onclick="SQH.toggleToolsPanel()">
              <span class="dash-section-title">Tracked AI Tools (${_aiTools.length})</span>
              <span class="ai-tools-chevron ${_aiToolsPanelOpen ? 'open' : ''}">${_aiToolsPanelOpen ? '&#9660;' : '&#9654;'}</span>
            </div>
            <div class="ai-tools-body ${_aiToolsPanelOpen ? '' : 'hidden'}" id="ai-tools-body">
              <div class="ai-tools-add">
                <input type="text" id="ai-tool-keyword" placeholder="Keyword (e.g. grok)" class="ai-tool-input">
                <input type="text" id="ai-tool-display" placeholder="Display name (e.g. Grok)" class="ai-tool-input">
                <button class="btn btn-sm btn-primary" onclick="SQH.addAITool()">+ Add</button>
              </div>
              <div class="ai-tools-list">${_aiTools.map(t =>
                `<div class="ai-tool-tag" data-id="${t.id}"><span class="ai-tool-tag-name">${esc(t.display_name)}</span><span class="ai-tool-tag-kw">${esc(t.keyword)}</span><button class="ai-tool-remove" onclick="SQH.removeAITool(${t.id},'${esc(t.display_name)}')" title="Remove">&times;</button></div>`
              ).join("")}</div>
            </div>
          </div>

          <div class="dash-section">
            <div class="dash-section-header"><span class="dash-section-title">Most Popular Apps</span><span class="dash-section-subtitle">by event count</span></div>
            <div class="dash-table-scroll">
              <table class="dash-table"><thead><tr><th>Application</th><th>Events</th></tr></thead>
              <tbody>${topAppsRows || '<tr><td colspan="2" class="text-muted text-center">No data</td></tr>'}</tbody></table>
            </div>
          </div>

          <div class="dash-section">
            <div class="dash-section-header"><span class="dash-section-title">Top AI Users</span><span class="dash-section-subtitle">by user, grouped by app</span></div>
            <div class="dash-table-scroll">
              <table class="dash-table"><thead><tr><th>User</th><th>App Breakdown</th><th>Events</th></tr></thead>
              <tbody>${topUserRows || '<tr><td colspan="3" class="text-muted text-center">No data</td></tr>'}</tbody></table>
            </div>
          </div>

          <div class="dash-row-equal">
            <div class="dash-section">
              <div class="dash-section-header"><span class="dash-section-title">Top 25 Apps</span><span class="dash-section-subtitle">by event distribution</span></div>
              <div class="dash-chart-wrap" style="min-height:280px"><canvas id="dash-pie-chart"></canvas></div>
            </div>
            <div class="dash-section">
              <div class="dash-section-header"><span class="dash-section-title">Top Endpoints</span><span class="dash-section-subtitle">by endpoint, grouped by app</span></div>
              <div class="dash-table-scroll">
                <table class="dash-table"><thead><tr><th>Endpoint</th><th>App Breakdown</th><th>Events</th></tr></thead>
                <tbody>${topEndpointRows || '<tr><td colspan="3" class="text-muted text-center">No data</td></tr>'}</tbody></table>
              </div>
            </div>
          </div>
        </div>
        <div class="drill-down-overlay hidden" id="drill-down-overlay"></div>
      </div>`;
    area.classList.remove("hidden");
    _initDashCharts(agg);
  }

  function _initDashCharts(agg) {
    _dashChartInstances.forEach(c => c.destroy());
    _dashChartInstances = [];

    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const textColor = isDark ? "#8e90a6" : "#5c5d73";

    if (typeof Chart === "undefined") return;

    Chart.defaults.color = textColor;
    Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
    Chart.defaults.font.size = 11;

    const pieCtx = document.getElementById("dash-pie-chart");
    if (pieCtx && agg.topApps.length > 0) {
      const top25 = agg.topApps.slice(0, 25);
      const otherCount = agg.topApps.slice(25).reduce((s, e) => s + e[1], 0);
      const labels = top25.map(e => e[0]);
      const values = top25.map(e => e[1]);
      if (otherCount > 0) { labels.push(`Other (${agg.topApps.length - 25})`); values.push(otherCount); }

      const palette = [
        "#7c6aef","#34d399","#fbbf24","#f87171","#38bdf8","#a78bfa","#fb923c",
        "#4ade80","#f472b6","#22d3ee","#818cf8","#facc15","#2dd4bf","#c084fc",
        "#fb7185","#a3e635","#e879f9","#67e8f9","#fdba74","#86efac","#d946ef",
        "#93c5fd","#fcd34d","#6ee7b7","#c4b5fd","#9ca3af",
      ];

      const chart = new Chart(pieCtx, {
        type: "doughnut",
        data: {
          labels,
          datasets: [{ data: values, backgroundColor: palette.slice(0, labels.length), borderWidth: 0 }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          onClick: (evt, elements) => {
            if (elements.length > 0) {
              const idx = elements[0].index;
              const appName = labels[idx];
              if (appName && !appName.startsWith("Other")) drillDown("app", appName);
            }
          },
          plugins: {
            legend: { position: "left", labels: { boxWidth: 10, padding: 6, font: { size: 10 } } },
          },
        },
      });
      _dashChartInstances.push(chart);
    }
  }

  function drillDown(type, value) {
    const filtered = currentResults.filter(row => {
      if (type === "app") return _extractAppName(row) === value;
      if (type === "user") return (row.UserName || row.userName || row.user || "Unknown") === value;
      if (type === "endpoint") return (row.EndpointName || row.endpointName || row.agentComputerName || "Unknown") === value;
      return false;
    });

    const label = type === "app" ? "Application" : type === "user" ? "User" : "Endpoint";

    const cols = ["_eventCount", "agentComputerName", "processName", "ProcessName", "processCmd", "ProcessCmd", "user", "UserName", "userName", "createdAt", "eventTime"];
    const available = cols.filter(c => filtered.some(r => r[c] !== undefined && r[c] !== null && r[c] !== ""));
    if (!available.length && filtered.length > 0) {
      const allKeys = Object.keys(filtered[0]);
      available.push(...allKeys.slice(0, 8));
    }

    const headerCells = available.map(c => `<th>${esc(c)}</th>`).join("");
    const bodyRows = filtered.slice(0, 500).map(row => {
      const cells = available.map(c => {
        let v = row[c];
        if (v === null || v === undefined) v = "";
        return `<td class="raw-cell">${esc(String(v))}</td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    }).join("");

    const overlay = document.getElementById("drill-down-overlay");
    if (!overlay) return;
    overlay.innerHTML = `
      <div class="drill-header">
        <button class="btn btn-sm" onclick="SQH.closeDrillDown()">&#8592; Back to Dashboard</button>
        <span class="drill-title">${esc(label)}: <strong>${esc(value)}</strong></span>
        <span class="drill-meta">${filtered.length.toLocaleString()} events</span>
      </div>
      <div class="drill-table-wrap">
        <table class="raw-results-table">
          <thead><tr>${headerCells}</tr></thead>
          <tbody>${bodyRows || '<tr><td colspan="' + available.length + '" class="text-muted text-center">No matching events</td></tr>'}</tbody>
        </table>
      </div>
      ${filtered.length > 500 ? '<div class="drill-footer">Showing first 500 of ' + filtered.length.toLocaleString() + ' matches</div>' : ''}`;
    overlay.classList.remove("hidden");
  }

  function closeDrillDown() {
    const overlay = document.getElementById("drill-down-overlay");
    if (overlay) { overlay.classList.add("hidden"); overlay.innerHTML = ""; }
  }

  function _startDashAutoRefresh() {
    _stopDashAutoRefresh();
    _dashNextRefresh = Date.now() + DASH_REFRESH_MS;
    _dashAutoTimer = setInterval(() => { _refreshDashboard(); }, DASH_REFRESH_MS);
    _dashCountdownTimer = setInterval(_updateCountdown, 1000);
  }

  function _stopDashAutoRefresh() {
    if (_dashAutoTimer) { clearInterval(_dashAutoTimer); _dashAutoTimer = null; }
    if (_dashCountdownTimer) { clearInterval(_dashCountdownTimer); _dashCountdownTimer = null; }
    _dashNextRefresh = null;
    _dashRefreshing = false;
  }

  function _updateCountdown() {
    const el = document.getElementById("dash-countdown");
    if (!el || !_dashNextRefresh) return;
    const remaining = _dashNextRefresh - Date.now();
    el.innerHTML = "Next refresh in <strong>" + _formatCountdown(Math.max(0, remaining)) + "</strong>";
  }

  async function _refreshDashboard() {
    if (_dashRefreshing || !_dashStoredQueryId) return;
    _dashRefreshing = true;

    const bar = document.getElementById("dash-refresh-bar");
    if (bar) {
      const dot = bar.querySelector(".dash-refresh-dot");
      const lbl = bar.querySelector(".dash-refresh-label");
      if (dot) dot.classList.add("pulsing");
      if (lbl) lbl.textContent = "Refreshing...";
    }
    const overlay = document.getElementById("dash-refreshing-overlay");
    if (!overlay) {
      const area = document.getElementById("results-area");
      const card = area && area.querySelector(".results-card");
      if (card) {
        const ov = document.createElement("div");
        ov.className = "dash-refreshing-overlay";
        ov.id = "dash-refreshing-overlay";
        ov.innerHTML = '<div class="spinner"></div><span>Re-running query...</span>';
        card.appendChild(ov);
      }
    }

    try {
      const { from_date, to_date } = _computeDateRange();
      const runData = await api(`/api/queries/${_dashStoredQueryId}/run`, {
        method: "POST",
        body: JSON.stringify({ param_values: {}, from_date, to_date }),
      });
      if (!runData) throw new Error("Failed to submit query");

      const newHistoryId = runData.history_id;
      let status = "running";
      while (status === "running") {
        await new Promise(r => setTimeout(r, 3000));
        const check = await api(`/api/queries/status/${newHistoryId}`);
        if (!check) break;
        status = check.status;
        if (status === "error") throw new Error(check.error_message || "Query failed");
        if (status === "cancelled") throw new Error("Query was cancelled");
      }

      const allData = await api(`/api/history/${newHistoryId}/results?offset=0&limit=100000`);
      if (!allData || !allData.data) throw new Error("Failed to load results");
      _totalCount = allData.count || allData.data.length;

      currentResults = allData.data;
      currentHistoryId = newHistoryId;
      _hasMore = false;
      _dashRefreshing = false;
      _dashNextRefresh = Date.now() + DASH_REFRESH_MS;
      renderAIDashboard();
      toast("Dashboard refreshed — " + currentResults.length + " events", "success");

    } catch (e) {
      _dashRefreshing = false;
      _dashNextRefresh = Date.now() + DASH_REFRESH_MS;
      const ov = document.getElementById("dash-refreshing-overlay");
      if (ov) ov.remove();
      const bar2 = document.getElementById("dash-refresh-bar");
      if (bar2) {
        const dot = bar2.querySelector(".dash-refresh-dot");
        const lbl = bar2.querySelector(".dash-refresh-label");
        if (dot) dot.classList.remove("pulsing");
        if (lbl) lbl.textContent = "Live Dashboard";
      }
      toast("Dashboard refresh failed: " + (e.message || "unknown error"), "error");
    }
  }

  async function refreshDashboardNow() {
    _dashNextRefresh = Date.now() + DASH_REFRESH_MS;
    if (_dashAutoTimer) { clearInterval(_dashAutoTimer); }
    _dashAutoTimer = setInterval(() => { _refreshDashboard(); }, DASH_REFRESH_MS);
    await _refreshDashboard();
  }

  function toggleToolsPanel() {
    _aiToolsPanelOpen = !_aiToolsPanelOpen;
    const body = document.getElementById("ai-tools-body");
    const chevron = document.querySelector(".ai-tools-chevron");
    if (body) body.classList.toggle("hidden", !_aiToolsPanelOpen);
    if (chevron) {
      chevron.innerHTML = _aiToolsPanelOpen ? "&#9660;" : "&#9654;";
      chevron.classList.toggle("open", _aiToolsPanelOpen);
    }
  }

  async function addAITool() {
    const kwEl = document.getElementById("ai-tool-keyword");
    const dnEl = document.getElementById("ai-tool-display");
    const keyword = (kwEl ? kwEl.value : "").trim().toLowerCase();
    const display_name = (dnEl ? dnEl.value : "").trim();
    if (!keyword || !display_name) { toast("Both keyword and display name are required", "error"); return; }
    try {
      const data = await api("/api/ai-tools", {
        method: "POST",
        body: JSON.stringify({ keyword, display_name }),
      });
      if (data && data.tools) _aiTools = data.tools;
      toast(`Added "${display_name}" — query will update on next refresh`, "success");
      renderAIDashboard();
    } catch {}
  }

  async function removeAITool(id, name) {
    if (!confirm(`Remove "${name}" from tracked AI tools? The S1 query will be updated on next refresh.`)) return;
    try {
      const data = await api(`/api/ai-tools/${id}`, { method: "DELETE" });
      if (data && data.tools) _aiTools = data.tools;
      toast(`Removed "${name}"`, "success");
      renderAIDashboard();
    } catch {}
  }

  // ── History Page ──
  async function loadHistory() {
    const scope = document.getElementById("history-scope").value;
    const status = document.getElementById("history-status").value;
    const search = document.getElementById("history-search").value;
    try {
      const data = await api(`/api/history?scope=${scope}&status=${status}&search=${encodeURIComponent(search)}`);
      if (!data) return;
      renderHistory(data.history);
    } catch {}
  }

  function renderHistory(history) {
    const wrap = document.getElementById("history-table-wrap");
    if (!history.length) { wrap.innerHTML = '<div class="empty-state">No history entries</div>'; return; }
    wrap.innerHTML = `<table><thead><tr><th>Query Name</th><th>Category</th><th>Parameters</th><th>Run By</th><th>Executed</th><th>Status</th><th>Shared</th><th>Actions</th></tr></thead><tbody>${
      history.map(h => {
        const params = typeof h.params_json === "string" ? h.params_json : JSON.stringify(h.params_json);
        const paramShort = params.length > 40 ? params.slice(0, 37) + "..." : params;
        const statusCls = h.status === "success" ? "badge-success" : h.status === "error" ? "badge-danger" : h.status === "cancelled" ? "badge-muted" : "badge-warning";
        return `<tr>
          <td style="font-weight:500">${esc(h.query_name)}</td>
          <td><span class="badge badge-info">${esc(h.category)}</span></td>
          <td class="text-sm" title="${esc(params)}">${esc(paramShort)}</td>
          <td>${esc(h.run_by || "")}</td>
          <td>${esc(h.executed_at)}</td>
          <td><span class="badge ${statusCls}">${esc(h.status)}</span></td>
          <td>${h.shared ? '<span class="badge badge-info">Shared</span>' : '<span class="text-muted">-</span>'}</td>
          <td><button class="btn btn-sm" onclick="SQH.viewHistoryResults(${h.id})" ${h.status !== "success" ? "disabled" : ""}>View</button></td>
        </tr>`;
      }).join("")
    }</tbody></table>`;
  }

  async function viewHistoryResults(id) {
    nav("queries");
    const area = document.getElementById("results-area");
    const isLiveRefresh = (currentHistoryId === id && currentResults.length > 0);
    if (!isLiveRefresh) {
      area.classList.add("hidden");
      area.innerHTML = '<div class="results-card"><div class="loading-state"><div class="spinner"></div><span>Loading events...</span></div></div>';
      area.classList.remove("hidden");
    }
    try {
      const data = await api(`/api/history/${id}/results?offset=0&limit=200`);
      if (!data) return;
      currentResults = data.data || [];
      currentHistoryId = id;
      _totalCount = data.count || currentResults.length;
      _hasMore = !!data.has_more;
      _currentQueryName = data.query_name || "";
      if (!isLiveRefresh) { sortCol = null; _filteredData = null; }

      if (_isAIDashboardQuery(_currentQueryName)) {
        _dashStoredQueryId = data.stored_query_id || null;
        await _loadAITools();
        if (_hasMore) {
          if (!isLiveRefresh) {
            area.innerHTML = '<div class="results-card"><div class="loading-state"><div class="spinner"></div><span>Loading all ' + _totalCount.toLocaleString() + ' events for dashboard...</span></div></div>';
          }
          const allData = await api(`/api/history/${currentHistoryId}/results?offset=0&limit=100000`);
          if (allData && allData.data) {
            currentResults = allData.data;
            _totalCount = allData.count || currentResults.length;
          }
        }
        _hasMore = false;
        renderAIDashboard();
        _startDashAutoRefresh();
      } else {
        _stopDashAutoRefresh();
        renderResults();
      }
    } catch {
      if (!isLiveRefresh) {
        area.innerHTML = '<div class="results-card"><div class="empty-state">Failed to load events</div></div>';
      }
    }
  }

  async function loadMoreResults() {
    if (!currentHistoryId || !_hasMore) return;
    const btn = document.getElementById("load-more-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Loading..."; }
    try {
      const data = await api(`/api/history/${currentHistoryId}/results?offset=${currentResults.length}&limit=500`);
      if (!data || !data.data) return;
      currentResults = currentResults.concat(data.data);
      _hasMore = !!data.has_more;
      _filteredData = null;
      _rebuildTable();
      _updateResultsMeta();
    } catch {
      toast("Failed to load more results", "error");
    }
  }

  function _updateResultsMeta() {
    const countEl = document.querySelector(".results-count");
    if (countEl) countEl.textContent = currentResults.length;
    const totalEl = document.getElementById("results-total");
    if (totalEl) totalEl.textContent = _totalCount;
    const moreWrap = document.getElementById("load-more-wrap");
    if (moreWrap) {
      if (_hasMore) {
        moreWrap.innerHTML = `<button id="load-more-btn" class="btn btn-primary" onclick="SQH.loadMoreResults()">Load More (${currentResults.length} of ${_totalCount})</button>`;
        moreWrap.classList.remove("hidden");
      } else {
        moreWrap.classList.add("hidden");
      }
    }
  }

  // ── Admin Panel ──
  function adminTab(tab) {
    document.querySelectorAll(".admin-sidebar a").forEach(a => a.classList.remove("active"));
    const link = document.querySelector(`.admin-sidebar a[data-admin="${tab}"]`);
    if (link) link.classList.add("active");
    loadAdminTab(tab);
    return false;
  }

  async function loadAdminTab(tab) {
    const content = document.getElementById("admin-content");
    if (tab === "users") await renderAdminUsers(content);
    else if (tab === "folders") await renderAdminFolders(content);
    else if (tab === "queries") await renderAdminQueries(content);
    else if (tab === "hist-mgmt") renderAdminHistMgmt(content);
    else if (tab === "disk") await renderAdminDisk(content);
    else if (tab === "wizard") await renderWizard(content);
  }

  // ── Admin: Users ──
  async function renderAdminUsers(el) {
    try {
      const data = await api("/api/admin/users");
      if (!data) return;
      el.innerHTML = `
        <div class="flex justify-between items-center mb-md"><h2 style="font-size:1.25rem">User Management</h2><button class="btn btn-primary btn-sm" onclick="SQH.showCreateUserModal()">+ Create User</button></div>
        <div class="table-wrap"><table><thead><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Status</th><th>Created</th><th>Last Login</th><th>Actions</th></tr></thead><tbody>${
          data.users.map(u => `<tr>
            <td style="font-weight:500">${esc(u.username)}</td><td>${esc(u.full_name)}</td>
            <td><span class="badge ${u.role === "admin" ? "badge-warning" : "badge-info"}">${esc(u.role)}</span></td>
            <td><span class="status-dot ${u.status === "active" ? "status-active" : "status-inactive"}"></span>${esc(u.status)}</td>
            <td>${esc(u.created_at || "")}</td><td>${esc(u.last_login || "-")}</td>
            <td><div class="flex gap-sm">
              <button class="btn btn-sm" onclick="SQH.showResetPwModal(${u.id},'${esc(u.username)}')">Reset PW</button>
              <button class="btn btn-sm ${u.status === "active" ? "btn-danger" : "btn-success"}" onclick="SQH.toggleUserStatus(${u.id},'${u.status}')">${u.status === "active" ? "Deactivate" : "Activate"}</button>
            </div></td></tr>`).join("")
        }</tbody></table></div>`;
    } catch {}
  }

  function showCreateUserModal() {
    showModal(`<h3>Create New User</h3>
      <div class="form-group"><label>Username</label><input type="text" id="m-cu-user" class="w-full" placeholder="e.g. jsmith"></div>
      <div class="form-group"><label>Full Name</label><input type="text" id="m-cu-name" class="w-full" placeholder="e.g. Jane Smith"></div>
      <div class="form-group"><label>Role</label><select id="m-cu-role" class="w-full"><option value="standard">Standard User</option><option value="admin">Admin</option></select></div>
      <div class="form-group"><label>Temporary Password</label><input type="text" id="m-cu-pw" class="w-full" value="Changeme1"><span class="text-sm text-muted">User will be forced to change on first login</span></div>
      <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.createUser()">Create User</button></div>`);
  }

  async function createUser() {
    const body = {
      username: document.getElementById("m-cu-user").value,
      full_name: document.getElementById("m-cu-name").value,
      role: document.getElementById("m-cu-role").value,
      password: document.getElementById("m-cu-pw").value,
    };
    try {
      await api("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
      closeModal();
      toast("User created", "success");
      loadAdminTab("users");
    } catch {}
  }

  function showResetPwModal(id, username) {
    showModal(`<h3>Reset Password for ${esc(username)}</h3>
      <div class="form-group"><label>New Password</label><input type="text" id="m-rp-pw" class="w-full" value="Changeme1"></div>
      <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.resetPassword(${id})">Reset Password</button></div>`);
  }

  async function resetPassword(id) {
    try {
      await api(`/api/admin/users/${id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: document.getElementById("m-rp-pw").value }) });
      closeModal(); toast("Password reset", "success");
    } catch {}
  }

  async function toggleUserStatus(id, current) {
    const next = current === "active" ? "inactive" : "active";
    try {
      await api(`/api/admin/users/${id}`, { method: "PUT", body: JSON.stringify({ status: next }) });
      toast(`User ${next === "active" ? "activated" : "deactivated"}`, "success");
      loadAdminTab("users");
    } catch {}
  }

  // ── Admin: Folders ──
  async function renderAdminFolders(el) {
    try {
      const data = await api("/api/admin/folders");
      if (!data) return;
      const folders = data.folders;
      const qData = await api("/api/queries");
      const queries = qData ? qData.queries : [];

      el.innerHTML = `
        <div class="flex justify-between items-center mb-md">
          <h2 style="font-size:1.25rem">Folder Management</h2>
          <button class="btn btn-primary btn-sm" onclick="SQH.showCreateFolderModal()">+ Create Folder</button>
        </div>
        <p class="text-sm text-muted mb-md">Organize stored queries into folders. Drag handles to reorder.</p>
        <div id="folder-list">
          ${!folders.length ? '<div class="empty-state" style="min-height:100px">No folders yet. Queries will show under "Uncategorized".</div>' :
            folders.map((f, i) => `
              <div class="folder-mgmt-row" data-folder-id="${f.id}">
                <div class="folder-mgmt-left">
                  <span class="folder-drag-handle" title="Drag to reorder">&#9776;</span>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
                  <span class="folder-mgmt-name">${esc(f.name)}</span>
                  <span class="badge badge-muted">${queries.filter(q => q.folder_id === f.id).length} queries</span>
                </div>
                <div class="flex gap-sm">
                  ${i > 0 ? `<button class="btn btn-sm" onclick="SQH.moveFolderUp(${f.id})">Up</button>` : ""}
                  ${i < folders.length - 1 ? `<button class="btn btn-sm" onclick="SQH.moveFolderDown(${f.id})">Down</button>` : ""}
                  <button class="btn btn-sm" onclick="SQH.showRenameFolderModal(${f.id},'${esc(f.name)}')">Rename</button>
                  <button class="btn btn-sm btn-danger" onclick="SQH.deleteFolder(${f.id})">Delete</button>
                </div>
              </div>`).join("")
          }
        </div>
        ${folders.length ? `
        <h3 style="font-size:1rem;margin:24px 0 12px">Assign Queries to Folders</h3>
        <div class="table-wrap"><table><thead><tr><th>Query</th><th>Category</th><th>Current Folder</th><th>Move to</th></tr></thead><tbody>
          ${queries.map(q => `<tr>
            <td style="font-weight:500">${esc(q.name)}</td>
            <td><span class="badge badge-info">${esc(q.category)}</span></td>
            <td>${q.folder_name ? esc(q.folder_name) : '<span class="text-muted">Uncategorized</span>'}</td>
            <td><select onchange="SQH.moveQueryFolder(${q.id}, this.value)" style="font-size:.8rem;padding:3px 8px">
              <option value="" ${!q.folder_id ? "selected" : ""}>Uncategorized</option>
              ${folders.map(f => `<option value="${f.id}" ${q.folder_id === f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
            </select></td>
          </tr>`).join("")}
        </tbody></table></div>` : ""}`;
    } catch {}
  }

  function showCreateFolderModal() {
    showModal(`<h3>Create Folder</h3>
      <div class="form-group"><label>Folder Name</label><input type="text" id="m-cf-name" class="w-full" placeholder="e.g. Network Queries"></div>
      <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.createFolder()">Create</button></div>`);
  }

  async function createFolder() {
    const name = document.getElementById("m-cf-name").value.trim();
    if (!name) { toast("Folder name required", "error"); return; }
    try {
      await api("/api/admin/folders", { method: "POST", body: JSON.stringify({ name }) });
      closeModal(); toast("Folder created", "success"); loadAdminTab("folders"); loadQueries();
    } catch {}
  }

  function showRenameFolderModal(id, currentName) {
    showModal(`<h3>Rename Folder</h3>
      <div class="form-group"><label>New Name</label><input type="text" id="m-rf-name" class="w-full" value="${esc(currentName)}"></div>
      <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.renameFolder(${id})">Save</button></div>`);
  }

  async function renameFolder(id) {
    const name = document.getElementById("m-rf-name").value.trim();
    if (!name) { toast("Name required", "error"); return; }
    try {
      await api(`/api/admin/folders/${id}`, { method: "PUT", body: JSON.stringify({ name }) });
      closeModal(); toast("Folder renamed", "success"); loadAdminTab("folders"); loadQueries();
    } catch {}
  }

  async function deleteFolder(id) {
    if (!confirm("Delete this folder? Queries inside will become uncategorized.")) return;
    try {
      await api(`/api/admin/folders/${id}`, { method: "DELETE" });
      toast("Folder deleted", "success"); loadAdminTab("folders"); loadQueries();
    } catch {}
  }

  async function moveFolderUp(id) { await _swapFolderOrder(id, -1); }
  async function moveFolderDown(id) { await _swapFolderOrder(id, 1); }

  async function _swapFolderOrder(id, direction) {
    try {
      const data = await api("/api/admin/folders");
      if (!data) return;
      const folders = data.folders;
      const idx = folders.findIndex(f => f.id === id);
      if (idx < 0) return;
      const swapIdx = idx + direction;
      if (swapIdx < 0 || swapIdx >= folders.length) return;
      const order = folders.map(f => f.id);
      [order[idx], order[swapIdx]] = [order[swapIdx], order[idx]];
      await api("/api/admin/folders/reorder", { method: "POST", body: JSON.stringify({ order }) });
      loadAdminTab("folders"); loadQueries();
    } catch {}
  }

  async function moveQueryFolder(queryId, folderId) {
    try {
      await api(`/api/admin/queries/${queryId}/folder`, {
        method: "PUT",
        body: JSON.stringify({ folder_id: folderId ? parseInt(folderId) : null }),
      });
      toast("Query moved", "success"); loadQueries();
    } catch {}
  }

  // ── Admin: Stored Queries ──
  async function renderAdminQueries(el) {
    try {
      const data = await api("/api/admin/queries");
      if (!data) return;
      const fData = await api("/api/admin/folders");
      const folders = fData ? fData.folders : [];
      el.innerHTML = `
        <div class="flex justify-between items-center mb-md"><h2 style="font-size:1.25rem">Stored Queries</h2><button class="btn btn-primary btn-sm" onclick="SQH.showCreateQueryModal()">+ Create Query</button></div>
        <div class="table-wrap"><table><thead><tr><th>Name</th><th>Category</th><th>Folder</th><th>Parameters</th><th>Created By</th><th>Modified</th><th>Actions</th></tr></thead><tbody>${
          data.queries.map(q => {
            const fName = folders.find(f => f.id === q.folder_id)?.name || "";
            return `<tr>
            <td style="font-weight:500">${esc(q.name)}</td>
            <td><span class="badge badge-info">${esc(q.category)}</span></td>
            <td>${fName ? esc(fName) : '<span class="text-muted">-</span>'}</td>
            <td>${q.params.map(p => `<span class="badge badge-muted">${esc(p.label)}</span>`).join(" ")}</td>
            <td>${esc(q.creator_name || "")}</td><td>${esc(q.modified_at || "")}</td>
            <td><div class="flex gap-sm">
              <button class="btn btn-sm" onclick="SQH.showEditQueryModal(${q.id})">Edit</button>
              <button class="btn btn-sm btn-danger" onclick="SQH.deleteQuery(${q.id})">Delete</button>
            </div></td></tr>`;
          }).join("")
        }</tbody></table></div>`;
    } catch {}
  }

  function showCreateQueryModal() {
    showModal(`<h3>Create Stored Query</h3>
      <div class="form-row"><div class="form-group"><label>Name</label><input type="text" id="m-cq-name" class="w-full"></div><div class="form-group"><label>Category</label><input type="text" id="m-cq-cat" class="w-full" placeholder="e.g. Process, Network"></div></div>
      <div class="form-group"><label>Description</label><textarea id="m-cq-desc" rows="2" class="w-full"></textarea></div>
      <div class="form-group"><label>DV Query</label><textarea id="m-cq-dv" rows="3" class="w-full" style="font-family:var(--mono);font-size:.8rem" placeholder='ObjectType = "process" AND ProcessName = "{proc}"'></textarea></div>
      <div class="form-group"><label>Parameters (JSON array)</label><textarea id="m-cq-params" rows="3" class="w-full" style="font-family:var(--mono);font-size:.8rem" placeholder='[{"name":"proc","label":"Process Name","param_type":"text","placeholder":"e.g. powershell"}]'></textarea></div>
      <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.createQuery()">Create</button></div>`);
  }

  async function createQuery() {
    let params = [];
    try { params = JSON.parse(document.getElementById("m-cq-params").value || "[]"); } catch { toast("Invalid params JSON", "error"); return; }
    try {
      await api("/api/admin/queries", { method: "POST", body: JSON.stringify({
        name: document.getElementById("m-cq-name").value,
        category: document.getElementById("m-cq-cat").value,
        description: document.getElementById("m-cq-desc").value,
        dv_query: document.getElementById("m-cq-dv").value,
        params,
      })});
      closeModal(); toast("Query created", "success"); loadAdminTab("queries"); loadQueries();
    } catch {}
  }

  async function showEditQueryModal(id) {
    try {
      const data = await api(`/api/queries/${id}`);
      if (!data) return;
      const q = data.query;
      showModal(`<h3>Edit Query: ${esc(q.name)}</h3>
        <div class="form-row"><div class="form-group"><label>Name</label><input type="text" id="m-eq-name" class="w-full" value="${esc(q.name)}"></div><div class="form-group"><label>Category</label><input type="text" id="m-eq-cat" class="w-full" value="${esc(q.category)}"></div></div>
        <div class="form-group"><label>Description</label><textarea id="m-eq-desc" rows="2" class="w-full">${esc(q.description)}</textarea></div>
        <div class="form-group"><label>DV Query</label><textarea id="m-eq-dv" rows="3" class="w-full" style="font-family:var(--mono);font-size:.8rem">${esc(q.dv_query)}</textarea></div>
        <div class="form-group"><label>Parameters (JSON)</label><textarea id="m-eq-params" rows="3" class="w-full" style="font-family:var(--mono);font-size:.8rem">${esc(JSON.stringify(q.params, null, 2))}</textarea></div>
        <div class="modal-actions"><button class="btn" onclick="SQH.closeModal()">Cancel</button><button class="btn btn-primary" onclick="SQH.updateQuery(${id})">Save</button></div>`);
    } catch {}
  }

  async function updateQuery(id) {
    let params = [];
    try { params = JSON.parse(document.getElementById("m-eq-params").value || "[]"); } catch { toast("Invalid params JSON", "error"); return; }
    try {
      await api(`/api/admin/queries/${id}`, { method: "PUT", body: JSON.stringify({
        name: document.getElementById("m-eq-name").value,
        category: document.getElementById("m-eq-cat").value,
        description: document.getElementById("m-eq-desc").value,
        dv_query: document.getElementById("m-eq-dv").value,
        params,
      })});
      closeModal(); toast("Query updated", "success"); loadAdminTab("queries"); loadQueries();
    } catch {}
  }

  async function deleteQuery(id) {
    if (!confirm("Delete this stored query?")) return;
    try { await api(`/api/admin/queries/${id}`, { method: "DELETE" }); toast("Query deleted", "success"); loadAdminTab("queries"); loadQueries(); } catch {}
  }

  // ── Admin: History Management ──
  function renderAdminHistMgmt(el) {
    el.innerHTML = `
      <h2 style="font-size:1.25rem;margin-bottom:20px">Query History Management</h2>
      <div class="card" style="max-width:600px">
        <div class="card-header">Bulk Delete Operations</div>
        <div class="bulk-section flex justify-between items-center">
          <div><div class="bulk-section-title">Delete All History</div><div class="bulk-section-desc">Permanently remove all query history and results</div></div>
          <button class="btn btn-danger btn-sm" onclick="SQH.bulkDelete('all')">Delete All</button>
        </div>
        <div class="bulk-section flex justify-between items-center">
          <div><div class="bulk-section-title">Delete Last 30 Days</div><div class="bulk-section-desc">Remove history from the past 30 days</div></div>
          <button class="btn btn-danger btn-sm" onclick="SQH.bulkDelete('30days')">Delete 30 Days</button>
        </div>
        <div class="bulk-section">
          <div class="bulk-section-title mb-md">Delete by Date Range</div>
          <div class="flex gap-sm items-center">
            <input type="date" id="del-start"><span class="text-muted">to</span><input type="date" id="del-end">
            <button class="btn btn-danger btn-sm" onclick="SQH.bulkDelete('range')">Delete Range</button>
          </div>
        </div>
      </div>`;
  }

  async function bulkDelete(mode) {
    const msg = mode === "all" ? "Delete ALL history? This cannot be undone." : mode === "30days" ? "Delete last 30 days of history?" : "Delete history in the selected range?";
    if (!confirm(msg)) return;
    const body = { mode };
    if (mode === "range") {
      body.start_date = document.getElementById("del-start").value;
      body.end_date = document.getElementById("del-end").value;
      if (!body.start_date || !body.end_date) { toast("Select both dates", "error"); return; }
    }
    try { await api("/api/admin/history", { method: "DELETE", body: JSON.stringify(body) }); toast("History deleted", "success"); } catch {}
  }

  // ── Admin: Disk Usage ──
  async function renderAdminDisk(el) {
    try {
      const data = await api("/api/system/disk/breakdown");
      if (!data) return;
      const d = data.disk;
      const fillCls = d.percent >= d.threshold ? "crit" : d.percent >= d.threshold - 15 ? "warn" : "";
      const statusLabel = d.percent >= d.threshold ? "Cleanup Needed" : "Healthy";
      const statusCls = d.percent >= d.threshold ? "text-danger" : "text-success";
      el.innerHTML = `
        <h2 style="font-size:1.25rem;margin-bottom:20px">Disk Usage</h2>
        <div class="card" style="max-width:600px">
          <div class="card-header">Storage Overview</div>
          <div class="flex justify-between" style="font-size:.9rem"><span>${d.used_gb} GB used of ${d.total_gb} GB</span><span class="${statusCls}" style="font-weight:600">${d.percent}% - ${statusLabel}</span></div>
          <div class="disk-bar-large"><div class="disk-bar-large-fill ${fillCls}" style="width:${Math.min(d.percent,100)}%;background:var(--${d.percent >= d.threshold ? "danger" : d.percent >= d.threshold-15 ? "warning" : "success"})"></div><div class="disk-threshold-line" style="left:${d.threshold}%" title="Threshold: ${d.threshold}%"></div></div>
          <div class="flex justify-between text-sm text-muted" style="margin-top:4px"><span>0 GB</span><span style="color:var(--warning)">${d.threshold_gb} GB (threshold)</span><span>${d.total_gb} GB</span></div>
          <div class="disk-stats">
            <div class="disk-stat"><div class="disk-stat-value" style="color:var(--accent)">${d.used_gb} <span style="font-size:.9rem">GB</span></div><div class="disk-stat-label">Used</div></div>
            <div class="disk-stat"><div class="disk-stat-value" style="color:var(--success)">${d.free_gb} <span style="font-size:.9rem">GB</span></div><div class="disk-stat-label">Available</div></div>
            <div class="disk-stat"><div class="disk-stat-value" style="color:var(--warning)">${d.until_cleanup_gb} <span style="font-size:.9rem">GB</span></div><div class="disk-stat-label">Until Cleanup</div></div>
          </div>
        </div>
        <div class="card mt-lg" style="max-width:600px">
          <div class="card-header">Storage Breakdown</div>
          <table style="font-size:.85rem">${data.breakdown.map(b => `<tr><td style="padding:6px 12px">${esc(b.label)}</td><td style="padding:6px 12px;text-align:right;font-weight:600">${formatBytes(b.bytes)}</td></tr>`).join("")}</table>
        </div>`;
    } catch {}
  }

  // ── Admin: Setup Wizard ──
  async function renderWizard(el) {
    try {
      const data = await api("/api/system/config");
      if (!data) return;
      wizardConfig = data.config;
      wizardStep = 1;
      renderWizardContent(el);
    } catch {}
  }

  function renderWizardContent(el) {
    if (!el) el = document.getElementById("admin-content");
    const steps = ["S1 API", "Storage", "Sessions", "Passwords", "Retention"];
    const stepsHtml = steps.map((s, i) => {
      const n = i + 1;
      const cls = n === wizardStep ? "active" : n < wizardStep ? "completed" : "";
      return `<div class="wizard-step ${cls}"><span class="step-num">${n < wizardStep ? "&#10003;" : n}</span> ${s}</div>`;
    }).join("");

    let body = "";
    const c = wizardConfig;
    if (wizardStep === 1) {
      body = `<h3 style="font-size:1rem;margin-bottom:16px">SentinelOne API Credentials</h3>
        <div class="form-group"><label>Base URL</label><input type="text" id="wiz-s1-url" value="${esc(c.s1_base_url || "")}" class="w-full" placeholder="https://usea1-partners.sentinelone.net"></div>
        <div class="form-group"><label>API Key</label><input type="text" id="wiz-s1-key" value="${esc(c.s1_api_key || "")}" class="w-full"></div>
        <div class="form-group"><label>API Secret</label><input type="password" id="wiz-s1-secret" value="${esc(c.s1_api_secret || "")}" class="w-full"></div>
        <div class="form-group"><label>API Version</label><select id="wiz-s1-ver" class="w-full"><option ${c.s1_api_version === "2.1" ? "selected" : ""}>2.1</option><option ${c.s1_api_version === "2.0" ? "selected" : ""}>2.0</option></select></div>
        <div class="flex justify-between mt-lg"><span></span><button class="btn btn-primary" onclick="SQH.wizardSave(2)">Next: Storage &rarr;</button></div>`;
    } else if (wizardStep === 2) {
      body = `<h3 style="font-size:1rem;margin-bottom:16px">Disk Cleanup Threshold</h3>
        <div class="form-group"><label>Cleanup Trigger (%)</label><input type="number" id="wiz-threshold" value="${esc(c.disk_cleanup_threshold || "70")}" min="50" max="95" style="width:120px"><span class="text-sm text-muted mt-sm">FIFO cleanup starts when disk exceeds this percentage</span></div>
        <div class="flex justify-between mt-lg"><button class="btn" onclick="SQH.wizardSave(1)">&larr; Back</button><button class="btn btn-primary" onclick="SQH.wizardSave(3)">Next: Sessions &rarr;</button></div>`;
    } else if (wizardStep === 3) {
      body = `<h3 style="font-size:1rem;margin-bottom:16px">Session Timeout</h3>
        <div class="form-group"><label>Inactivity Timeout (hours)</label><select id="wiz-timeout" class="w-full" style="width:200px">
          ${["0.5","1","4","8","24"].map(v => `<option value="${v}" ${c.session_timeout_hours === v ? "selected" : ""}>${v === "0.5" ? "30 minutes" : v + " hour" + (v !== "1" ? "s" : "")}</option>`).join("")}
        </select></div>
        <div class="flex justify-between mt-lg"><button class="btn" onclick="SQH.wizardSave(2)">&larr; Back</button><button class="btn btn-primary" onclick="SQH.wizardSave(4)">Next: Passwords &rarr;</button></div>`;
    } else if (wizardStep === 4) {
      body = `<h3 style="font-size:1rem;margin-bottom:16px">Password Policy</h3>
        <div class="form-group"><label>Minimum Length</label><input type="number" id="wiz-pw-len" value="${esc(c.pw_min_length || "8")}" min="6" max="32" style="width:100px"></div>
        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px">
          <label style="display:flex;align-items:center;gap:8px;font-weight:400"><input type="checkbox" id="wiz-pw-upper" ${c.pw_require_upper === "1" ? "checked" : ""}> Require uppercase</label>
          <label style="display:flex;align-items:center;gap:8px;font-weight:400"><input type="checkbox" id="wiz-pw-lower" ${c.pw_require_lower === "1" ? "checked" : ""}> Require lowercase</label>
          <label style="display:flex;align-items:center;gap:8px;font-weight:400"><input type="checkbox" id="wiz-pw-num" ${c.pw_require_number === "1" ? "checked" : ""}> Require number</label>
          <label style="display:flex;align-items:center;gap:8px;font-weight:400"><input type="checkbox" id="wiz-pw-spec" ${c.pw_require_special === "1" ? "checked" : ""}> Require special character</label>
        </div>
        <div class="flex justify-between mt-lg"><button class="btn" onclick="SQH.wizardSave(3)">&larr; Back</button><button class="btn btn-primary" onclick="SQH.wizardSave(5)">Next: Retention &rarr;</button></div>`;
    } else if (wizardStep === 5) {
      body = `<h3 style="font-size:1rem;margin-bottom:16px">Query Result Retention</h3>
        <div class="form-group"><label>Retention Period</label><select id="wiz-retention" class="w-full" style="width:200px">
          ${[["0","No auto-expiration"],["30","30 days"],["90","90 days"],["180","180 days"],["365","365 days"]].map(([v,l]) => `<option value="${v}" ${c.retention_days === v ? "selected" : ""}>${l}</option>`).join("")}
        </select></div>
        <div class="flex justify-between mt-lg"><button class="btn" onclick="SQH.wizardSave(4)">&larr; Back</button><button class="btn btn-success" onclick="SQH.wizardFinish()">Save All Settings</button></div>`;
    }

    el.innerHTML = `<h2 style="font-size:1.25rem;margin-bottom:4px">Setup Wizard</h2><p class="text-sm text-muted mb-md">Configure core application settings</p><div class="wizard-steps">${stepsHtml}</div><div class="wizard-content">${body}</div>`;
  }

  function collectWizardValues() {
    const s = wizardStep;
    if (s === 1) {
      wizardConfig.s1_base_url = gv("wiz-s1-url"); wizardConfig.s1_api_key = gv("wiz-s1-key"); wizardConfig.s1_api_secret = gv("wiz-s1-secret"); wizardConfig.s1_api_version = gv("wiz-s1-ver");
    } else if (s === 2) { wizardConfig.disk_cleanup_threshold = gv("wiz-threshold"); }
    else if (s === 3) { wizardConfig.session_timeout_hours = gv("wiz-timeout"); }
    else if (s === 4) {
      wizardConfig.pw_min_length = gv("wiz-pw-len");
      wizardConfig.pw_require_upper = gcb("wiz-pw-upper"); wizardConfig.pw_require_lower = gcb("wiz-pw-lower");
      wizardConfig.pw_require_number = gcb("wiz-pw-num"); wizardConfig.pw_require_special = gcb("wiz-pw-spec");
    } else if (s === 5) { wizardConfig.retention_days = gv("wiz-retention"); }
  }

  function wizardSave(next) { collectWizardValues(); wizardStep = next; renderWizardContent(); }

  async function wizardFinish() {
    collectWizardValues();
    try {
      await api("/api/system/config", { method: "POST", body: JSON.stringify({ settings: wizardConfig }) });
      toast("Settings saved successfully", "success");
      loadDiskIndicator();
    } catch {}
  }

  // ── Modal ──
  function showModal(html) { document.getElementById("modal-body").innerHTML = html; document.getElementById("modal-overlay").classList.remove("hidden"); }
  function closeModal(e) { if (e && e.target.id !== "modal-overlay") return; document.getElementById("modal-overlay").classList.add("hidden"); }

  // ── Utilities ──
  function esc(s) { if (s == null) return ""; const d = document.createElement("div"); d.textContent = String(s); return d.innerHTML; }
  function gv(id) { const el = document.getElementById(id); return el ? el.value : ""; }
  function gcb(id) { const el = document.getElementById(id); return el && el.checked ? "1" : "0"; }
  function formatBytes(b) { if (b < 1024) return b + " B"; if (b < 1048576) return (b / 1024).toFixed(1) + " KB"; if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB"; return (b / 1073741824).toFixed(1) + " GB"; }

  // ── Init ──
  function init() {
    const saved = localStorage.getItem("sqh-theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    document.getElementById("theme-icon-sun").classList.toggle("hidden", saved === "dark");
    document.getElementById("theme-icon-moon").classList.toggle("hidden", saved === "light");

    document.getElementById("btn-login").addEventListener("click", login);
    document.getElementById("login-pass").addEventListener("keydown", e => { if (e.key === "Enter") login(); });
    document.getElementById("btn-change-pw").addEventListener("click", changePassword);
    document.getElementById("btn-theme").addEventListener("click", toggleTheme);
    document.getElementById("user-menu").addEventListener("click", e => { e.stopPropagation(); document.getElementById("user-dropdown").classList.toggle("show"); });
    document.addEventListener("click", () => { document.getElementById("user-dropdown")?.classList.remove("show"); document.getElementById("export-menu")?.classList.remove("show"); document.getElementById("column-picker")?.classList.add("hidden"); });

    document.getElementById("history-scope").addEventListener("change", loadHistory);
    document.getElementById("history-status").addEventListener("change", loadHistory);
    document.getElementById("history-search").addEventListener("input", loadHistory);

    checkAuth();
  }

  document.addEventListener("DOMContentLoaded", init);

  return {
    nav, logout, filterQueries, selectQuery, runQuery, cancelQuery, setDateRange, setGlobalTime,
    sortResults, filterResults, toggleColumnPicker, toggleColumn, resetColumns,
    toggleExport, exportData, shareResults, viewHistoryResults, loadMoreResults,
    refreshDashboardNow, drillDown, closeDrillDown, toggleToolsPanel, addAITool, removeAITool, adminTab,
    showCreateUserModal, createUser, showResetPwModal, resetPassword, toggleUserStatus,
    showCreateFolderModal, createFolder, showRenameFolderModal, renameFolder, deleteFolder,
    moveFolderUp, moveFolderDown, moveQueryFolder,
    showCreateQueryModal, createQuery, showEditQueryModal, updateQuery, deleteQuery,
    bulkDelete, wizardSave, wizardFinish, closeModal,
  };
})();
