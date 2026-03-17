const SQH = (() => {
  let currentUser = null;
  let storedQueries = [];
  let selectedQuery = null;
  let currentResults = [];
  let currentHistoryId = null;
  let sortCol = null;
  let sortAsc = true;
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
  }

  // ── Navigation ──
  function nav(page) {
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
  async function loadQueries() {
    try {
      const data = await api("/api/queries");
      if (!data) return;
      storedQueries = data.queries;
      renderQueryList();
    } catch {}
  }

  function renderQueryList(filterCat) {
    const cats = [...new Set(storedQueries.map(q => q.category))].sort();
    const filterEl = document.getElementById("category-filter");
    filterEl.innerHTML = `<button class="${!filterCat ? "active" : ""}" onclick="SQH.filterQueries()">All</button>` +
      cats.map(c => `<button class="${filterCat === c ? "active" : ""}" onclick="SQH.filterQueries('${c}')">${c}</button>`).join("");

    const queries = filterCat ? storedQueries.filter(q => q.category === filterCat) : storedQueries;
    const listEl = document.getElementById("query-list");
    if (!queries.length) { listEl.innerHTML = '<div class="empty-state">No stored queries available</div>'; return; }
    listEl.innerHTML = queries.map(q => `
      <div class="query-card ${selectedQuery?.id === q.id ? "selected" : ""}" onclick="SQH.selectQuery(${q.id})">
        <div class="query-card-title">${esc(q.name)}</div>
        <div class="query-card-desc">${esc(q.description)}</div>
        <div class="query-card-meta">
          <span class="badge badge-info">${esc(q.category)}</span>
          <span class="badge badge-muted">${q.params.length} param${q.params.length !== 1 ? "s" : ""}</span>
        </div>
      </div>`).join("");
  }

  function filterQueries(cat) { renderQueryList(cat); }

  function selectQuery(id) {
    selectedQuery = storedQueries.find(q => q.id === id);
    renderQueryList(document.querySelector(".category-filter button.active:not(:first-child)")?.textContent);
    renderQueryDetail();
  }

  function renderQueryDetail() {
    const el = document.getElementById("query-detail");
    if (!selectedQuery) { el.innerHTML = '<div class="empty-state">Select a query from the list</div>'; return; }
    const q = selectedQuery;
    const paramsHtml = q.params.map(p => {
      let input;
      if (p.param_type === "text") input = `<input type="text" id="param-${p.name}" placeholder="${esc(p.placeholder)}" class="w-full">`;
      else if (p.param_type === "datetime") input = `<input type="datetime-local" id="param-${p.name}" class="w-full">`;
      else if (p.param_type === "dropdown") input = `<select id="param-${p.name}" class="w-full">${(p.options||[]).map(o => `<option>${esc(o)}</option>`).join("")}</select>`;
      else input = `<input type="text" id="param-${p.name}" class="w-full">`;
      return `<div class="form-group"><label>${esc(p.label)} <span class="param-type-hint">(${p.param_type})</span></label>${input}</div>`;
    }).join("");

    el.innerHTML = `
      <div class="card-header">${esc(q.name)}</div>
      <p class="text-sm text-muted mb-md">${esc(q.description)}</p>
      <div class="dv-query-display">${esc(q.dv_query)}</div>
      ${paramsHtml}
      <button class="btn btn-primary" onclick="SQH.runQuery()">Run Query</button>`;
  }

  async function runQuery() {
    if (!selectedQuery) return;
    const paramValues = {};
    selectedQuery.params.forEach(p => {
      const el = document.getElementById(`param-${p.name}`);
      if (el) paramValues[p.name] = el.value;
    });

    document.getElementById("results-area").classList.add("hidden");
    document.getElementById("query-loading").classList.remove("hidden");

    try {
      const data = await api(`/api/queries/${selectedQuery.id}/run`, {
        method: "POST",
        body: JSON.stringify({ param_values: paramValues }),
      });
      if (!data) return;
      currentResults = data.data || [];
      currentHistoryId = data.history_id;
      sortCol = null;
      renderResults();
      document.getElementById("results-area").classList.remove("hidden");
      toast(`Query completed - ${data.count} results`, "success");
    } catch (e) {
      document.getElementById("results-area").innerHTML = `<div class="card"><div class="alert alert-danger">${esc(e.message)}</div></div>`;
      document.getElementById("results-area").classList.remove("hidden");
    } finally {
      document.getElementById("query-loading").classList.add("hidden");
    }
  }

  // ── Results Table ──
  function renderResults() {
    const area = document.getElementById("results-area");
    if (!currentResults.length) {
      area.innerHTML = '<div class="card"><div class="empty-state">No results returned</div></div>';
      return;
    }
    const cols = Object.keys(currentResults[0]);
    area.innerHTML = `
      <div class="card">
        <div class="card-header flex justify-between items-center"><span>Query Results</span><span class="results-meta">${currentResults.length} results</span></div>
        <div class="results-toolbar">
          <input type="text" class="search-input" placeholder="Filter results..." oninput="SQH.filterResults(this.value)">
          <div class="flex gap-sm">
            <button class="btn btn-success btn-sm" onclick="SQH.shareResults()">Share with All Users</button>
            <div class="export-dropdown">
              <button class="btn btn-sm" onclick="SQH.toggleExport(event)">Export</button>
              <div class="export-menu" id="export-menu">
                <button onclick="SQH.exportData('csv')">Export as CSV</button>
                <button onclick="SQH.exportData('json')">Export as JSON</button>
                <button onclick="SQH.exportData('pdf')">Export as PDF</button>
              </div>
            </div>
          </div>
        </div>
        <div class="table-wrap"><table><thead><tr>${cols.map(c => `<th onclick="SQH.sortResults('${c}')">${esc(c)} ${sortCol === c ? (sortAsc ? "&#9650;" : "&#9660;") : ""}</th>`).join("")}</tr></thead><tbody id="results-tbody"></tbody></table></div>
      </div>`;
    fillResultsBody(cols, currentResults);
  }

  function fillResultsBody(cols, data) {
    const tbody = document.getElementById("results-tbody");
    if (!tbody) return;
    tbody.innerHTML = data.map(row => "<tr>" + cols.map(c => {
      let v = row[c];
      const vs = String(v);
      if (c === "ThreatStatus" || c === "threatStatus") {
        const cls = vs === "Malicious" ? "badge-danger" : vs === "Suspicious" ? "badge-warning" : "badge-success";
        return `<td><span class="badge ${cls}">${esc(vs)}</span></td>`;
      }
      return `<td title="${esc(vs)}">${esc(vs.length > 60 ? vs.slice(0, 57) + "..." : vs)}</td>`;
    }).join("") + "</tr>").join("");
  }

  function sortResults(col) {
    if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = true; }
    currentResults.sort((a, b) => {
      const va = a[col] ?? "", vb = b[col] ?? "";
      return sortAsc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va > vb ? -1 : va < vb ? 1 : 0);
    });
    renderResults();
  }

  function filterResults(term) {
    const t = term.toLowerCase();
    const filtered = currentResults.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(t)));
    const cols = currentResults.length ? Object.keys(currentResults[0]) : [];
    fillResultsBody(cols, filtered);
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
        const statusCls = h.status === "success" ? "badge-success" : h.status === "error" ? "badge-danger" : "badge-warning";
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
    document.getElementById("results-area").classList.add("hidden");
    document.getElementById("query-loading").classList.remove("hidden");
    try {
      const data = await api(`/api/history/${id}/results`);
      if (!data) return;
      currentResults = data.data || [];
      currentHistoryId = id;
      sortCol = null;
      renderResults();
      document.getElementById("results-area").classList.remove("hidden");
    } catch {} finally {
      document.getElementById("query-loading").classList.add("hidden");
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

  // ── Admin: Stored Queries ──
  async function renderAdminQueries(el) {
    try {
      const data = await api("/api/admin/queries");
      if (!data) return;
      el.innerHTML = `
        <div class="flex justify-between items-center mb-md"><h2 style="font-size:1.25rem">Stored Queries</h2><button class="btn btn-primary btn-sm" onclick="SQH.showCreateQueryModal()">+ Create Query</button></div>
        <div class="table-wrap"><table><thead><tr><th>Name</th><th>Category</th><th>Parameters</th><th>Created By</th><th>Modified</th><th>Actions</th></tr></thead><tbody>${
          data.queries.map(q => `<tr>
            <td style="font-weight:500">${esc(q.name)}</td>
            <td><span class="badge badge-info">${esc(q.category)}</span></td>
            <td>${q.params.map(p => `<span class="badge badge-muted">${esc(p.label)}</span>`).join(" ")}</td>
            <td>${esc(q.creator_name || "")}</td><td>${esc(q.modified_at || "")}</td>
            <td><div class="flex gap-sm">
              <button class="btn btn-sm" onclick="SQH.showEditQueryModal(${q.id})">Edit</button>
              <button class="btn btn-sm btn-danger" onclick="SQH.deleteQuery(${q.id})">Delete</button>
            </div></td></tr>`).join("")
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
    const saved = localStorage.getItem("sqh-theme");
    if (saved) {
      document.documentElement.setAttribute("data-theme", saved);
      document.getElementById("theme-icon-sun").classList.toggle("hidden", saved === "dark");
      document.getElementById("theme-icon-moon").classList.toggle("hidden", saved === "light");
    }

    document.getElementById("btn-login").addEventListener("click", login);
    document.getElementById("login-pass").addEventListener("keydown", e => { if (e.key === "Enter") login(); });
    document.getElementById("btn-change-pw").addEventListener("click", changePassword);
    document.getElementById("btn-theme").addEventListener("click", toggleTheme);
    document.getElementById("user-menu").addEventListener("click", e => { e.stopPropagation(); document.getElementById("user-dropdown").classList.toggle("show"); });
    document.addEventListener("click", () => { document.getElementById("user-dropdown")?.classList.remove("show"); document.getElementById("export-menu")?.classList.remove("show"); });

    document.getElementById("history-scope").addEventListener("change", loadHistory);
    document.getElementById("history-status").addEventListener("change", loadHistory);
    document.getElementById("history-search").addEventListener("input", loadHistory);

    checkAuth();
  }

  document.addEventListener("DOMContentLoaded", init);

  return {
    nav, logout, filterQueries, selectQuery, runQuery, sortResults, filterResults,
    toggleExport, exportData, shareResults, viewHistoryResults, adminTab,
    showCreateUserModal, createUser, showResetPwModal, resetPassword, toggleUserStatus,
    showCreateQueryModal, createQuery, showEditQueryModal, updateQuery, deleteQuery,
    bulkDelete, wizardSave, wizardFinish, closeModal,
  };
})();
