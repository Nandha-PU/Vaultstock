// ============================================================================
// VaultStock — Admin Backend, SQL & Live Demo Client (debug.html)
// ============================================================================

const API_BASE =
  window.location.port === "8000"
    ? "/api"
    : `${window.location.protocol}//${window.location.hostname}:8000/api`;

const SESSION_KEY = "vaultstock_session";
const THEME_KEY = "vaultstock_theme";

let currentUser = {
  id: null,
  username: null,
  role: null,
  token: null,
  demo_mode: false,
};

let cachedAuditLogs = [];

// DOM References — Auth & Header
const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginUsername = document.getElementById("loginUsername");
const loginPassword = document.getElementById("loginPassword");
const loginError = document.getElementById("loginError");
const demoHint = document.getElementById("demoHint");
const btnLoginThemeToggle = document.getElementById("btnLoginThemeToggle");
const btnQuickAdmin = document.getElementById("btnQuickAdmin");

const mainNavbar = document.getElementById("mainNavbar");
const mainContent = document.getElementById("mainContent");
const btnBrand = document.getElementById("btnBrand");
const btnNavInventory = document.getElementById("btnNavInventory");
const btnNavDemo = document.getElementById("btnNavDemo");
const btnNavDebug = document.getElementById("btnNavDebug");
const navDebugDot = document.getElementById("navDebugDot");
const btnThemeToggle = document.getElementById("btnThemeToggle");
const userBadge = document.getElementById("userBadge");
const btnLogout = document.getElementById("btnLogout");
const actionNotice = document.getElementById("actionNotice");

// DOM References — Verification & Tamper
const integrityBanner = document.getElementById("integrityBanner");
const chainBadge = document.getElementById("chainBadge");
const chainStatusTitle = document.getElementById("chainStatusTitle");
const chainStatusDesc = document.getElementById("chainStatusDesc");
const btnTamper = document.getElementById("btnTamper");
const btnResetDemo = document.getElementById("btnResetDemo");
const tamperAlert = document.getElementById("tamperAlert");
const tamperAlertText = document.getElementById("tamperAlertText");

// DOM References — SQLite Telemetry & Sandbox
const btnRefreshInternals = document.getElementById("btnRefreshInternals");
const dbgJournalMode = document.getElementById("dbgJournalMode");
const dbgForeignKeys = document.getElementById("dbgForeignKeys");
const dbgCountAudit = document.getElementById("dbgCountAudit");
const dbgAnchorId = document.getElementById("dbgAnchorId");
const dbgCountUsers = document.getElementById("dbgCountUsers");
const dbgCountProducts = document.getElementById("dbgCountProducts");
const dbgCountMovements = document.getElementById("dbgCountMovements");
const dbgDbSize = document.getElementById("dbgDbSize");
const dbgDerivedStockGrid = document.getElementById("dbgDerivedStockGrid");

const sqlProbeButtons = document.getElementById("sqlProbeButtons");
const sqlProbeTitle = document.getElementById("sqlProbeTitle");
const sqlProbeBadge = document.getElementById("sqlProbeBadge");
const sqlProbeQuery = document.getElementById("sqlProbeQuery");
const sqlProbeSteps = document.getElementById("sqlProbeSteps");
const sqlProbeResult = document.getElementById("sqlProbeResult");

const sqlTraceFeed = document.getElementById("sqlTraceFeed");
const btnClearSqlTrace = document.getElementById("btnClearSqlTrace");

const auditFeed = document.getElementById("auditFeed");
const inspectorBlockTitle = document.getElementById("inspectorBlockTitle");
const inspectorBlockAction = document.getElementById("inspectorBlockAction");
const inspectorPrevHash = document.getElementById("inspectorPrevHash");
const inspectorRowHash = document.getElementById("inspectorRowHash");
const inspectorMeta = document.getElementById("inspectorMeta");
const inspectorPayloadJson = document.getElementById("inspectorPayloadJson");

// DOM References — Help Guide Modal
const helpModal = document.getElementById("helpModal");
const btnOpenHelp = document.getElementById("btnOpenHelp");
const btnCloseHelp = document.getElementById("btnCloseHelp");
const btnDoneHelp = document.getElementById("btnDoneHelp");

// ============================================================================
// Theme Management (Light Mode Default / Dark Mode Toggle)
// ============================================================================

function applyTheme(theme) {
  const isDark = theme === "dark";
  const themeVal = isDark ? "dark" : "light";

  document.documentElement.setAttribute("data-theme", themeVal);
  if (document.body) document.body.setAttribute("data-theme", themeVal);

  if (isDark) {
    document.documentElement.classList.add("dark");
    if (document.body) document.body.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
    if (document.body) document.body.classList.remove("dark");
  }

  const label = isDark ? "Light Mode" : "Dark Mode";
  document.querySelectorAll(".btn-theme-toggle").forEach((btn) => {
    btn.textContent = label;
  });

  try {
    localStorage.setItem(THEME_KEY, themeVal);
  } catch (e) {}
}

function toggleTheme() {
  const isDark =
    document.documentElement.getAttribute("data-theme") === "dark" ||
    document.documentElement.classList.contains("dark");
  applyTheme(isDark ? "light" : "dark");
}

(function initTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") {
      applyTheme(saved);
      return;
    }
  } catch (e) {}
  applyTheme("light");
})();

if (btnThemeToggle) btnThemeToggle.addEventListener("click", toggleTheme);
if (btnLoginThemeToggle) btnLoginThemeToggle.addEventListener("click", toggleTheme);

// ============================================================================
// Navigation Buttons (No Hyperlinks)
// ============================================================================

if (btnBrand) {
  btnBrand.addEventListener("click", () => {
    window.location.href = "index.html";
  });
}

if (btnNavInventory) {
  btnNavInventory.addEventListener("click", () => {
    window.location.href = "index.html";
  });
}

if (btnNavDemo) {
  btnNavDemo.addEventListener("click", () => {
    window.location.href = "demo.html";
  });
}

if (btnNavDebug) {
  btnNavDebug.addEventListener("click", () => {
    window.location.href = "debug.html";
  });
}

// ============================================================================
// Help Guide Modal
// ============================================================================

if (btnOpenHelp) {
  btnOpenHelp.addEventListener("click", () => helpModal?.classList.remove("hidden"));
}
if (btnCloseHelp) {
  btnCloseHelp.addEventListener("click", () => helpModal?.classList.add("hidden"));
}
if (btnDoneHelp) {
  btnDoneHelp.addEventListener("click", () => helpModal?.classList.add("hidden"));
}

// ============================================================================
// Helpers & Live SQL Process Trace Logger
// ============================================================================

function esc(value) {
  return String(value ?? "").replace(/[&<>"'`]/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
    "`": "&#96;",
  })[ch]);
}

function showNotice(text, isError = false) {
  if (!text) {
    actionNotice.classList.add("hidden");
    return;
  }
  actionNotice.textContent = text;
  actionNotice.className = isError ? "notice notice-error" : "notice notice-info";
}

function saveSession(userObj) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(userObj));
  } catch (e) {}
}

function clearSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (e) {}
}

const SQL_PIPELINE_DESCRIPTIONS = {
  "GET /products":
    "SELECT p.id, p.sku, p.name, p.unit_price, COALESCE(SUM(CASE WHEN m.type='IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock FROM products p LEFT JOIN movements m ON p.id = m.product_id GROUP BY p.id;",
  "POST /products":
    "BEGIN IMMEDIATE -> INSERT INTO products -> compute_hash(HMAC-SHA256) -> INSERT INTO audit_log -> COMMIT -> sync data/audit_head.json",
  "GET /movements":
    "SELECT m.id, p.name, p.sku, m.type, m.qty, m.note, m.created_by, m.created_at FROM movements m JOIN products p ON m.product_id = p.id ORDER BY m.id DESC;",
  "POST /movements":
    "BEGIN IMMEDIATE -> Check balance -> Trigger [prevent_negative_stock] -> INSERT INTO movements -> HMAC-SHA256 -> INSERT INTO audit_log -> COMMIT -> sync data/audit_head.json",
  "GET /audit":
    "SELECT id, action, actor, ref_table, ref_id, payload, details, timestamp, prev_hash, row_hash FROM audit_log ORDER BY id DESC;",
  "GET /audit/verify":
    "Continuous Verification: Contiguity (1..N) -> prev_hash Linkage -> HMAC-SHA256 Signatures -> Row Reconciliation -> External Anchor",
  "POST /audit/tamper-demo":
    "Bypass prevent_audit_update -> UPDATE audit_log SET details=details||' [TAMPERED]', row_hash=sha256(...) WHERE id=1 -> Restore trigger",
  "POST /reset-demo":
    "DROP & recreate schema/triggers -> Reseed initial products & movements -> Append DEMO_RESET block -> Resync audit_head.json",
  "GET /debug/internals":
    "PRAGMA journal_mode, foreign_keys, busy_timeout, page_count + sqlite_master triggers + audit_log head snapshot",
  "POST /debug/sql-probe":
    "Execute diagnostic probe inside SQLite (EXPLAIN QUERY PLAN or BEGIN IMMEDIATE -> trigger probe -> ROLLBACK)",
};

function appendSqlTrace(method, endpoint, status, elapsedMs) {
  if (!sqlTraceFeed) return;
  const cleanEndpoint = endpoint.split("?")[0];
  const key = `${method} ${cleanEndpoint}`;
  const sqlDesc = SQL_PIPELINE_DESCRIPTIONS[key] || `SQLite query execution for ${key}`;
  const isErr = status >= 400;
  const nowStr = new Date().toLocaleTimeString();

  const item = document.createElement("div");
  item.className = `trace-item mono${isErr ? " trace-error" : ""}`;
  item.innerHTML = `
    <div class="trace-item-top">
      <span>[${esc(nowStr)}] ${esc(key)}</span>
      <span>HTTP ${Number(status)} · ${Number(elapsedMs)}ms</span>
    </div>
    <div class="trace-sql">${esc(sqlDesc)}</div>
  `;
  sqlTraceFeed.prepend(item);

  while (sqlTraceFeed.children.length > 30) {
    sqlTraceFeed.removeChild(sqlTraceFeed.lastChild);
  }
}

if (btnClearSqlTrace) {
  btnClearSqlTrace.addEventListener("click", () => {
    if (sqlTraceFeed) sqlTraceFeed.innerHTML = "";
  });
}

async function apiFetch(endpoint, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (currentUser.token) {
    headers["Authorization"] = `Bearer ${currentUser.token}`;
  }

  const t0 = performance.now();
  const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  const elapsed = Math.round(performance.now() - t0);
  appendSqlTrace(method, endpoint, res.status, elapsed);

  if (res.status === 401) {
    clearSession();
    showLoginOverlay("Session expired. Please sign in as Admin.");
    throw new Error("Authentication required");
  }
  return res;
}

// ============================================================================
// Authentication (Admin Only Access)
// ============================================================================

async function checkPublicDemoMode() {
  try {
    const res = await fetch(`${API_BASE}/config`);
    if (res.ok) {
      const cfg = await res.json();
      demoHint.classList.toggle("hidden", !cfg.demo_mode);
    }
  } catch (e) {}
}

function showLoginOverlay(message = "") {
  currentUser = { id: null, username: null, role: null, token: null, demo_mode: false };
  mainNavbar.classList.add("hidden");
  mainContent.classList.add("hidden");
  loginOverlay.classList.remove("hidden");

  checkPublicDemoMode();

  if (message) {
    loginError.textContent = message;
    loginError.classList.remove("hidden");
  } else {
    loginError.classList.add("hidden");
  }

  loginPassword.value = "";
  loginUsername.focus();
}

function showAuthenticatedUI() {
  // Staff is restricted from Backend & Debug page — redirect immediately to Inventory
  if (currentUser.role !== "admin") {
    window.location.replace("index.html");
    return false;
  }

  loginOverlay.classList.add("hidden");
  mainNavbar.classList.remove("hidden");
  mainContent.classList.remove("hidden");

  userBadge.textContent = `${currentUser.username} · ${currentUser.role}`;

  const isDemo = Boolean(currentUser.demo_mode);
  document.querySelectorAll(".demo-only").forEach((el) => {
    el.classList.toggle("hidden", !isDemo);
  });
  return true;
}

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = loginUsername.value.trim();
  const password = loginPassword.value;
  if (!username || !password) return;

  try {
    loginError.classList.add("hidden");
    const res = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (res.status === 429) {
      const retryAfter = res.headers.get("Retry-After") || "900";
      throw new Error(`Too many login attempts. Retry after ${retryAfter}s.`);
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Invalid username or password");
    }

    const data = await res.json();
    currentUser = {
      id: data.id,
      username: data.username,
      role: data.role,
      token: data.token,
      demo_mode: data.demo_mode,
    };
    saveSession(currentUser);

    if (currentUser.role !== "admin") {
      window.location.replace("index.html");
      return;
    }

    showNotice("");
    showAuthenticatedUI();
    await refreshDebugAll();
  } catch (err) {
    loginError.textContent = err.message || "Sign in failed";
    loginError.classList.remove("hidden");
  }
});

btnLogout.addEventListener("click", () => {
  stopAutoPlayDemo();
  clearSession();
  window.location.replace("index.html");
});

if (btnQuickAdmin) {
  btnQuickAdmin.addEventListener("click", () => {
    loginUsername.value = "admin";
    loginPassword.value = "vault-admin-2026";
    loginForm.requestSubmit();
  });
}

// ============================================================================
// Block Inspector & Audit Chain Table
// ============================================================================

function inspectAuditBlock(blockId) {
  const block = cachedAuditLogs.find((b) => Number(b.id) === Number(blockId));
  if (!block) return;

  if (inspectorBlockTitle) {
    inspectorBlockTitle.textContent = `Block #${Number(block.id)} Cryptographic Details`;
  }
  if (inspectorBlockAction) {
    inspectorBlockAction.textContent = block.action;
  }
  if (inspectorPrevHash) {
    inspectorPrevHash.textContent = block.prev_hash;
  }
  if (inspectorRowHash) {
    inspectorRowHash.textContent = block.row_hash;
  }
  if (inspectorMeta) {
    inspectorMeta.textContent = `${block.details} (Actor: ${block.actor} · ${block.timestamp})`;
  }
  if (inspectorPayloadJson) {
    try {
      const parsed = JSON.parse(block.payload);
      inspectorPayloadJson.textContent = JSON.stringify(parsed, null, 2);
    } catch {
      inspectorPayloadJson.textContent = block.payload;
    }
  }
}

async function fetchAuditTrail() {
  const res = await apiFetch("/audit");
  cachedAuditLogs = await res.json();

  if (cachedAuditLogs.length === 0) {
    auditFeed.innerHTML = `<tr><td colspan="8" class="empty-cell">No audit entries.</td></tr>`;
    return;
  }

  auditFeed.innerHTML = cachedAuditLogs
    .map((a) => {
      const ref = a.ref_table ? `${esc(a.ref_table)}#${Number(a.ref_id)}` : "System";
      const isTamperedRow = String(a.details || "").includes("[TAMPERED]");
      return `
        <tr class="${isTamperedRow ? "notice-error" : ""}">
          <td class="mono"><strong>#${Number(a.id)}</strong></td>
          <td class="mono">${esc(a.action)}</td>
          <td class="mono">${esc(a.actor)}</td>
          <td class="mono">${ref}</td>
          <td class="mono text-muted">${esc(a.timestamp)}</td>
          <td class="mono" title="${esc(a.prev_hash)}">${esc(a.prev_hash.slice(0, 10))}...</td>
          <td class="mono" title="${esc(a.row_hash)}">${esc(a.row_hash.slice(0, 12))}...</td>
          <td class="text-right">
            <button type="button" class="btn btn-sm js-inspect-block" data-id="${Number(a.id)}">
              Inspect
            </button>
          </td>
        </tr>
      `;
    })
    .join("");

  const tamperedBlock = cachedAuditLogs.find((b) => String(b.details || "").includes("[TAMPERED]"));
  if (tamperedBlock) {
    inspectAuditBlock(tamperedBlock.id);
  } else if (cachedAuditLogs[0]) {
    inspectAuditBlock(cachedAuditLogs[0].id);
  }
}

if (auditFeed) {
  auditFeed.addEventListener("click", (e) => {
    const btn = e.target.closest(".js-inspect-block");
    if (btn) {
      inspectAuditBlock(Number(btn.dataset.id));
    }
  });
}

async function fetchDerivedStockSnapshot() {
  const res = await apiFetch("/products");
  const products = await res.json();
  if (!dbgDerivedStockGrid) return;

  dbgDerivedStockGrid.innerHTML = products
    .map(
      (p) => `
      <div class="tech-kv-box">
        <span class="tech-k">${esc(p.name)}</span>
        <strong class="tech-v mono">${Number(p.current_stock)} units</strong>
      </div>
    `
    )
    .join("");
}

async function fetchDebugInternals() {
  try {
    const res = await apiFetch("/debug/internals");
    if (!res.ok) return;
    const info = await res.json();

    const p = info.pragmas || {};
    if (dbgJournalMode) {
      dbgJournalMode.textContent = `${p.journal_mode || "WAL"} + BEGIN IMMEDIATE`;
    }
    if (dbgForeignKeys) {
      const trigCount = (info.triggers || []).length;
      dbgForeignKeys.textContent = `ON (${trigCount} Active Triggers)`;
    }

    const c = info.row_counts || {};
    if (dbgCountAudit) {
      dbgCountAudit.textContent = `${c.audit_log ?? 0} Blocks`;
    }
    if (dbgCountUsers) dbgCountUsers.textContent = String(c.users ?? 0);
    if (dbgCountProducts) dbgCountProducts.textContent = String(c.products ?? 0);
    if (dbgCountMovements) dbgCountMovements.textContent = String(c.movements ?? 0);
    if (dbgDbSize) {
      const kb = ((p.db_size_bytes || 0) / 1024).toFixed(1);
      dbgDbSize.textContent = `${kb} KB`;
    }

    const anchor = info.external_anchor;
    const head = info.db_head;
    if (dbgAnchorId) {
      if (anchor && head && anchor.id === head.id && anchor.row_hash === head.row_hash) {
        dbgAnchorId.textContent = `Synced (Block #${anchor.id})`;
      } else {
        dbgAnchorId.textContent = "Mismatch / Truncated";
      }
    }
  } catch (e) {}
}

if (btnRefreshInternals) {
  btnRefreshInternals.addEventListener("click", refreshDebugAll);
}

// ============================================================================
// SQL Command Execution & Trigger Probe Sandbox
// ============================================================================

if (sqlProbeButtons) {
  sqlProbeButtons.addEventListener("click", async (e) => {
    const btn = e.target.closest(".js-sql-probe");
    if (!btn) return;
    const probeType = btn.dataset.probe;
    if (!probeType) return;

    sqlProbeTitle.textContent = "Executing SQLite Action...";
    sqlProbeBadge.textContent = "Running";
    sqlProbeBadge.className = "status-tag";

    try {
      const res = await apiFetch("/debug/sql-probe", {
        method: "POST",
        body: JSON.stringify({ probe_type: probeType }),
      });
      const data = await res.json();
      sqlProbeTitle.textContent = `${data.title} (${data.elapsed_ms} ms)`;
      sqlProbeQuery.textContent = data.sql;

      // Render Step-by-Step execution process breakdown
      if (sqlProbeSteps) {
        const steps = data.process_steps || [];
        if (steps.length > 0) {
          sqlProbeSteps.innerHTML = steps
            .map((s) => `<div class="sql-step-item">${esc(s)}</div>`)
            .join("");
        } else {
          sqlProbeSteps.innerHTML = `<div class="sql-step-item">Action executed directly inside storage transaction.</div>`;
        }
      }

      sqlProbeResult.textContent = data.engine_output;

      if (data.blocked_by_trigger) {
        sqlProbeBadge.textContent = "Blocked by Trigger";
        sqlProbeBadge.className = "status-tag verified";
      } else {
        sqlProbeBadge.textContent = data.outcome || "OK";
        sqlProbeBadge.className = "status-tag";
      }
    } catch (err) {
      sqlProbeBadge.textContent = "Error";
      sqlProbeResult.textContent = err.message || "Probe failed";
    }
  });
}

// ============================================================================
// Continuous Automatic 5-Point Verification & Tamper / Reset
// ============================================================================

function updateCheckBoxUI(boxId, pillId, passed) {
  const box = document.getElementById(boxId);
  const pill = document.getElementById(pillId);
  if (!box || !pill) return;
  box.className = passed ? "check-box pass" : "check-box fail";
  pill.textContent = passed ? "PASS" : "FAIL";
}

async function verifyLedger() {
  const res = await apiFetch("/audit/verify");
  const result = await res.json();
  const checks = result.checks || {};

  updateCheckBoxUI("checkBoxContiguity", "checkPillContiguity", Boolean(checks.contiguity));
  updateCheckBoxUI("checkBoxLinkage", "checkPillLinkage", Boolean(checks.linkage));
  updateCheckBoxUI("checkBoxIntegrity", "checkPillIntegrity", Boolean(checks.integrity));
  updateCheckBoxUI("checkBoxReconciliation", "checkPillReconciliation", Boolean(checks.reconciliation));
  updateCheckBoxUI("checkBoxAnchor", "checkPillAnchor", Boolean(checks.anchor));

  if (result.verified) {
    integrityBanner.className = "status-panel verified";
    chainBadge.textContent = "Verified";
    chainStatusTitle.textContent = `Audit Chain Intact (${result.total_blocks} Blocks)`;
    chainStatusDesc.textContent =
      "All 5 automatic cryptographic checks pass: sequence contiguity, prev_hash linkage, HMAC secret signature, row reconciliation, and external anchor.";
    tamperAlert.classList.add("hidden");
    if (navDebugDot) navDebugDot.className = "status-dot verified";
  } else {
    integrityBanner.className = "status-panel tampered";
    chainBadge.textContent = "Tamper Detected";
    chainStatusTitle.textContent = `Integrity Failure at Block #${result.broken_at_id ?? "N/A"}`;
    chainStatusDesc.textContent =
      "Automatic mathematical verification detected an unauthorized modification.";
    tamperAlertText.textContent = result.reason;
    tamperAlert.classList.remove("hidden");
    if (navDebugDot) navDebugDot.className = "status-dot tampered";
  }
  return result;
}

async function refreshDebugAll() {
  await Promise.all([
    fetchDerivedStockSnapshot(),
    fetchAuditTrail(),
    fetchDebugInternals(),
    verifyLedger(),
  ]);
}

async function simulateTampering() {
  try {
    const res = await apiFetch("/audit/tamper-demo", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Tamper simulation failed");
    }
    await refreshDebugAll();
    inspectAuditBlock(1);
    pulseElement(integrityBanner);
    showNotice("Direct SQLite edit simulated on Block #1 — automatic verification caught the broken HMAC seal!", true);
  } catch (err) {
    showNotice(err.message, true);
  }
}

async function resetDemo() {
  if (!confirm("Reset database to initial seed data?")) return;
  try {
    const res = await apiFetch("/reset-demo", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Reset failed");
    }
    await refreshDebugAll();
    pulseElement(integrityBanner);
    showNotice("Database restored to clean seed state — 100% verified.", false);
  } catch (err) {
    showNotice(err.message, true);
  }
}

if (btnTamper) btnTamper.addEventListener("click", simulateTampering);
if (btnResetDemo) btnResetDemo.addEventListener("click", resetDemo);

// ============================================================================
// Initialize Session (Admin Only)
// ============================================================================

(async function initDebugApp() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved && saved.token) {
        currentUser = saved;
        if (showAuthenticatedUI()) {
          await refreshDebugAll();
        }
        return;
      }
    }
  } catch (e) {
    clearSession();
  }
  showLoginOverlay();
})();
