// ============================================================================
// VaultStock — Unified Client Logic (app.js)
// Unified Single-Page Application: Inventory, Operations, Audit, Diagnostics
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

let cachedProducts = [];
let cachedCategories = [];
let cachedSuppliers = [];
let cachedLocations = [];

// ============================================================================
// DOM References
// ============================================================================
// Login
const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginUsername = document.getElementById("loginUsername");
const loginPassword = document.getElementById("loginPassword");
const loginError = document.getElementById("loginError");
const demoHint = document.getElementById("demoHint");
const btnLoginThemeToggle = document.getElementById("btnLoginThemeToggle");
const btnQuickAdmin = document.getElementById("btnQuickAdmin");
const btnQuickStaff = document.getElementById("btnQuickStaff");

// Navigation & Global UI
const mainNavbar = document.getElementById("mainNavbar");
const mainContent = document.getElementById("mainContent");
const btnBrand = document.getElementById("btnBrand");
const btnNavInventory = document.getElementById("btnNavInventory");
const btnNavOperations = document.getElementById("btnNavOperations");
const btnNavAudit = document.getElementById("btnNavAudit");
const btnNavDiagnostics = document.getElementById("btnNavDiagnostics");
const chainStatusDot = document.getElementById("chainStatusDot");
const chainStatusText = document.getElementById("chainStatusText");
const btnOpenHelp = document.getElementById("btnOpenHelp");
const btnThemeToggle = document.getElementById("btnThemeToggle");
const userBadge = document.getElementById("userBadge");
const btnLogout = document.getElementById("btnLogout");
const actionNotice = document.getElementById("actionNotice");
const globalNotice = document.getElementById("globalNotice");

// Tabs
const tabInventory = document.getElementById("tabInventory");
const tabOperations = document.getElementById("tabOperations");
const tabAudit = document.getElementById("tabAudit");
const tabDiagnostics = document.getElementById("tabDiagnostics");

// Tab 1: Inventory
const kpiTotalProducts = document.getElementById("kpiTotalProducts");
const kpiTotalUnits = document.getElementById("kpiTotalUnits");
const kpiTotalValuation = document.getElementById("kpiTotalValuation");
const kpiLowStockCount = document.getElementById("kpiLowStockCount");
const kpiLowStockSub = document.getElementById("kpiLowStockSub");
const lowStockBanner = document.getElementById("lowStockBanner");
const lowStockBannerText = document.getElementById("lowStockBannerText");
const productSearchInput = document.getElementById("productSearchInput");
const categoryFilterSelect = document.getElementById("categoryFilterSelect");
const stockFilterSelect = document.getElementById("stockFilterSelect");
const btnRefreshInventory = document.getElementById("btnRefreshInventory");
const btnOpenAddProduct = document.getElementById("btnOpenAddProduct");
const productTableBody = document.getElementById("productTableBody");

// Tab 2: Operations
const formReceiveStock = document.getElementById("formReceiveStock");
const receiveProductSelect = document.getElementById("receiveProductSelect");
const receiveSupplierSelect = document.getElementById("receiveSupplierSelect");
const receiveLocationSelect = document.getElementById("receiveLocationSelect");
const receiveQty = document.getElementById("receiveQty");
const receiveRefDoc = document.getElementById("receiveRefDoc");
const receiveNote = document.getElementById("receiveNote");

const formDispatchStock = document.getElementById("formDispatchStock");
const dispatchProductSelect = document.getElementById("dispatchProductSelect");
const dispatchLocationSelect = document.getElementById("dispatchLocationSelect");
const dispatchQty = document.getElementById("dispatchQty");
const dispatchRefDoc = document.getElementById("dispatchRefDoc");
const dispatchNote = document.getElementById("dispatchNote");
const dispatchBalanceSpan = document.getElementById("dispatchBalanceSpan");
const movementTableBody = document.getElementById("movementTableBody");

// Tab 3: Audit
const auditHeroBadge = document.getElementById("auditHeroBadge");
const auditHeroTitle = document.getElementById("auditHeroTitle");
const auditHeroSubtitle = document.getElementById("auditHeroSubtitle");
const btnRunAuditVerify = document.getElementById("btnRunAuditVerify");
const btnSimulateTamper = document.getElementById("btnSimulateTamper");
const btnResetDatabase = document.getElementById("btnResetDatabase");
const auditBlockCountBadge = document.getElementById("auditBlockCountBadge");
const auditTableBody = document.getElementById("auditTableBody");

// Tab 4: Diagnostics
const diagSqliteVersion = document.getElementById("diagSqliteVersion");
const diagWalSub = document.getElementById("diagWalSub");
const diagDbSize = document.getElementById("diagDbSize");
const diagPageSub = document.getElementById("diagPageSub");
const diagFkStatus = document.getElementById("diagFkStatus");
const diagBusyTimeout = document.getElementById("diagBusyTimeout");
const diagRowCountsGrid = document.getElementById("diagRowCountsGrid");
const probeResultBox = document.getElementById("probeResultBox");
const probeTitle = document.getElementById("probeTitle");
const probeStatusBadge = document.getElementById("probeStatusBadge");
const probeSql = document.getElementById("probeSql");
const probeEngineOutput = document.getElementById("probeEngineOutput");
const probeStepsList = document.getElementById("probeStepsList");
const diagTriggersViewsList = document.getElementById("diagTriggersViewsList");

// Modals
const addProductModal = document.getElementById("addProductModal");
const btnCloseAddProduct = document.getElementById("btnCloseAddProduct");
const btnCancelAddProduct = document.getElementById("btnCancelAddProduct");
const formAddProduct = document.getElementById("formAddProduct");
const newProdSku = document.getElementById("newProdSku");
const newProdName = document.getElementById("newProdName");
const newProdCategory = document.getElementById("newProdCategory");
const newProdPrice = document.getElementById("newProdPrice");
const newProdThreshold = document.getElementById("newProdThreshold");

const vivaGuideModal = document.getElementById("vivaGuideModal");
const btnCloseVivaGuide = document.getElementById("btnCloseVivaGuide");
const btnDoneVivaGuide = document.getElementById("btnDoneVivaGuide");

// ============================================================================
// Theme Management
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
}

function toggleTheme() {
  const current = localStorage.getItem(THEME_KEY) || "light";
  const next = current === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (e) {}
  applyTheme(next);
}

// ============================================================================
// Notifications & Alerts
// ============================================================================
let noticeTimer = null;
function showNotice(message, type = "success") {
  if (!actionNotice) return;
  actionNotice.className = `notice notice-${type}`;
  actionNotice.textContent = message;
  globalNotice.classList.remove("hidden");

  if (noticeTimer) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    globalNotice.classList.add("hidden");
  }, 5000);
}

// ============================================================================
// API Fetch Helper
// ============================================================================
async function apiCall(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = options.headers ? { ...options.headers } : {};

  if (currentUser.token) {
    headers["Authorization"] = `Bearer ${currentUser.token}`;
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  try {
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error("Session expired. Please sign in again.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail || (typeof data === "string" ? data : `Error ${res.status}`);
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    throw err;
  }
}

// ============================================================================
// Authentication & Session
// ============================================================================
async function checkPublicConfig() {
  try {
    const res = await fetch(`${API_BASE}/config`);
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.demo_mode && demoHint) {
        demoHint.classList.remove("hidden");
      }
    }
  } catch (e) {}
}

function saveSession(user) {
  currentUser = { ...user };
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(currentUser));
  } catch (e) {}
}

function loadSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      currentUser = JSON.parse(raw);
      return Boolean(currentUser.token);
    }
  } catch (e) {}
  return false;
}

function clearSession() {
  currentUser = { id: null, username: null, role: null, token: null, demo_mode: false };
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (e) {}
}

function handleUnauthorized() {
  clearSession();
  showLogin();
}

function showLogin() {
  loginOverlay.classList.remove("hidden");
  mainNavbar.classList.add("hidden");
  mainContent.classList.add("hidden");
  globalNotice.classList.add("hidden");
  loginPassword.value = "";
}

function showApp() {
  loginOverlay.classList.add("hidden");
  mainNavbar.classList.remove("hidden");
  mainContent.classList.remove("hidden");

  // User badge
  userBadge.textContent = `${currentUser.username} (${currentUser.role.toUpperCase()})`;
  userBadge.className = `user-label role-${currentUser.role}`;

  // RBAC permissions visibility
  const isAdmin = currentUser.role === "admin";
  document.querySelectorAll(".admin-only").forEach((el) => {
    if (isAdmin) {
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  });

  // Load initial data
  loadAllData();
}

async function handleLogin(username, password) {
  loginError.classList.add("hidden");
  try {
    const res = await fetch(`${API_BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Invalid login credentials");
    }
    saveSession(data);
    showApp();
    showNotice(`Welcome back, ${data.username}!`, "success");
  } catch (err) {
    loginError.textContent = err.message;
    loginError.classList.remove("hidden");
  }
}

// ============================================================================
// Tab Navigation
// ============================================================================
const tabs = [
  { btn: btnNavInventory, pane: tabInventory },
  { btn: btnNavOperations, pane: tabOperations },
  { btn: btnNavAudit, pane: tabAudit },
  { btn: btnNavDiagnostics, pane: tabDiagnostics },
];

function switchTab(targetPane) {
  tabs.forEach(({ btn, pane }) => {
    if (pane === targetPane) {
      pane.classList.remove("hidden");
      pane.classList.add("active");
      btn.classList.add("active");
    } else {
      pane.classList.add("hidden");
      pane.classList.remove("active");
      btn.classList.remove("active");
    }
  });

  // Tab-specific refreshes
  if (targetPane === tabInventory) {
    loadProducts();
  } else if (targetPane === tabOperations) {
    loadOperationsData();
  } else if (targetPane === tabAudit) {
    loadAuditTrail();
  } else if (targetPane === tabDiagnostics) {
    loadDiagnostics();
  }
}

// ============================================================================
// Data Loading & Renderers
// ============================================================================
async function loadAllData() {
  await Promise.allSettled([
    loadLookups(),
    loadProducts(),
    checkAuditHealth(),
  ]);
}

async function loadLookups() {
  try {
    const [cats, supps, locs] = await Promise.all([
      apiCall("/categories"),
      apiCall("/suppliers"),
      apiCall("/locations"),
    ]);
    cachedCategories = cats;
    cachedSuppliers = supps;
    cachedLocations = locs;

    populateSelects();
  } catch (e) {
    console.error("Failed to load relational lookups:", e);
  }
}

function populateSelects() {
  // Category Filter in Inventory
  categoryFilterSelect.innerHTML = '<option value="">All Categories</option>';
  cachedCategories.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.name} (${c.code})`;
    categoryFilterSelect.appendChild(opt);
  });

  // Category in Add Product Modal
  newProdCategory.innerHTML = '<option value="">-- Choose Category --</option>';
  cachedCategories.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.name} (${c.code})`;
    newProdCategory.appendChild(opt);
  });

  // Supplier in Receive Stock
  receiveSupplierSelect.innerHTML = '<option value="">-- Choose Supplier --</option>';
  cachedSuppliers.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    receiveSupplierSelect.appendChild(opt);
  });

  // Location in Receive Stock & Dispatch
  const locOptions = cachedLocations
    .map((l) => `<option value="${l.id}">${l.name} (${l.code})</option>`)
    .join("");
  receiveLocationSelect.innerHTML = '<option value="">-- Choose Location --</option>' + locOptions;
  dispatchLocationSelect.innerHTML = '<option value="">-- Choose Location --</option>' + locOptions;
}

// ----------------------------------------------------------------------------
// Tab 1: Products & Catalog
// ----------------------------------------------------------------------------
async function loadProducts() {
  try {
    const products = await apiCall("/products");
    cachedProducts = products;
    renderInventory();
    populateProductSelects();
  } catch (err) {
    productTableBody.innerHTML = `<tr><td colspan="9" class="text-center text-error">Failed to load inventory: ${err.message}</td></tr>`;
  }
}

function populateProductSelects() {
  const pOpts = cachedProducts
    .map((p) => `<option value="${p.id}">${p.name} [${p.sku}] (Current Stock: ${p.current_stock})</option>`)
    .join("");

  receiveProductSelect.innerHTML = '<option value="">-- Choose Product --</option>' + pOpts;
  dispatchProductSelect.innerHTML = '<option value="">-- Choose Product --</option>' + pOpts;
}

function renderInventory() {
  const searchTerm = (productSearchInput.value || "").trim().toLowerCase();
  const selectedCat = categoryFilterSelect.value;
  const stockFilter = stockFilterSelect.value;

  let totalSkus = cachedProducts.length;
  let totalUnits = 0;
  let totalValuation = 0;
  let lowStockCount = 0;
  let lowStockNames = [];

  const filtered = cachedProducts.filter((p) => {
    totalUnits += p.current_stock;
    totalValuation += p.total_valuation || (p.current_stock * p.unit_price);

    if (p.is_low_stock) {
      lowStockCount++;
      lowStockNames.push(`${p.name} (${p.current_stock}/${p.reorder_threshold})`);
    }

    // Filter by search
    if (searchTerm) {
      const matchSku = p.sku.toLowerCase().includes(searchTerm);
      const matchName = p.name.toLowerCase().includes(searchTerm);
      if (!matchSku && !matchName) return false;
    }

    // Filter by Category
    if (selectedCat && String(p.category_id) !== String(selectedCat)) {
      return false;
    }

    // Filter by Stock status
    if (stockFilter === "LOW" && !p.is_low_stock) return false;
    if (stockFilter === "IN_STOCK" && p.is_low_stock) return false;

    return true;
  });

  // Update KPI Cards
  kpiTotalProducts.textContent = totalSkus;
  kpiTotalUnits.textContent = totalUnits.toLocaleString();
  kpiTotalValuation.textContent = `$${totalValuation.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  kpiLowStockCount.textContent = lowStockCount;

  if (lowStockCount > 0) {
    kpiLowStockSub.textContent = `${lowStockCount} item(s) need replenishment`;
    lowStockBanner.classList.remove("hidden");
    lowStockBannerText.textContent = `The following items have reached or fallen below safety stock: ${lowStockNames.join(", ")}. Please issue a stock receipt.`;
  } else {
    kpiLowStockSub.textContent = "All stock levels optimal";
    lowStockBanner.classList.add("hidden");
  }

  // Render Rows
  if (filtered.length === 0) {
    productTableBody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">No products matched the selected filters.</td></tr>`;
    return;
  }

  productTableBody.innerHTML = filtered
    .map((p) => {
      const statusBadge = p.is_low_stock
        ? `<span class="badge badge-warning">LOW STOCK</span>`
        : `<span class="badge badge-success">IN STOCK</span>`;

      return `
        <tr>
          <td><code class="sku-code">${escapeHtml(p.sku)}</code></td>
          <td><strong>${escapeHtml(p.name)}</strong></td>
          <td><span class="badge badge-secondary">${escapeHtml(p.category_name || "General")}</span></td>
          <td class="text-right">$${p.unit_price.toFixed(2)}</td>
          <td class="text-right"><strong>${p.current_stock.toLocaleString()}</strong></td>
          <td class="text-right text-muted">$${(p.total_valuation || p.current_stock * p.unit_price).toFixed(2)}</td>
          <td class="text-center text-muted">${p.reorder_threshold}</td>
          <td class="text-center">${statusBadge}</td>
          <td class="text-right">
            <button type="button" class="btn btn-xs" onclick="quickPrepareReceive(${p.id})">+ Receive</button>
            <button type="button" class="btn btn-xs" onclick="quickPrepareDispatch(${p.id})">- Issue</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

window.quickPrepareReceive = function (productId) {
  switchTab(tabOperations);
  receiveProductSelect.value = productId;
  receiveQty.focus();
};

window.quickPrepareDispatch = function (productId) {
  switchTab(tabOperations);
  dispatchProductSelect.value = productId;
  updateDispatchBalance();
  dispatchQty.focus();
};

// ----------------------------------------------------------------------------
// Tab 2: Stock Operations (Receive & Dispatch)
// ----------------------------------------------------------------------------
async function loadOperationsData() {
  await Promise.allSettled([
    loadProducts(),
    loadMovements(),
  ]);
}

async function loadMovements() {
  try {
    const movements = await apiCall("/movements?limit=50");
    if (!movements || movements.length === 0) {
      movementTableBody.innerHTML = `<tr><td colspan="11" class="text-center text-muted">No stock movements recorded yet.</td></tr>`;
      return;
    }

    movementTableBody.innerHTML = movements
      .map((m) => {
        const typeBadge =
          m.type === "IN"
            ? `<span class="badge badge-success">INWARD</span>`
            : `<span class="badge badge-warning">OUTWARD</span>`;

        const partnerOrDoc = m.type === "IN" ? m.supplier_name : "Customer Dispatch";

        return `
          <tr>
            <td>#${m.id}</td>
            <td class="text-muted"><small>${formatDate(m.created_at)}</small></td>
            <td>${typeBadge}</td>
            <td><strong>${escapeHtml(m.product_name)}</strong> <small class="text-muted">(${escapeHtml(m.sku)})</small></td>
            <td><small class="badge badge-secondary">${escapeHtml(m.category_name || "-")}</small></td>
            <td>${escapeHtml(partnerOrDoc || "-")}</td>
            <td><small>${escapeHtml(m.location_name || "-")}</small></td>
            <td class="text-right"><strong>${m.type === "IN" ? "+" : "-"}${m.qty.toLocaleString()}</strong></td>
            <td><code>${escapeHtml(m.reference_doc || "-")}</code></td>
            <td class="text-muted"><small>${escapeHtml(m.note || "-")}</small></td>
            <td><small class="user-pill">${escapeHtml(m.created_by)}</small></td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    movementTableBody.innerHTML = `<tr><td colspan="11" class="text-center text-error">Failed to load movements: ${err.message}</td></tr>`;
  }
}

function updateDispatchBalance() {
  const prodId = Number(dispatchProductSelect.value);
  const prod = cachedProducts.find((p) => p.id === prodId);
  if (prod) {
    dispatchBalanceSpan.textContent = prod.current_stock.toLocaleString();
    dispatchQty.max = prod.current_stock;
  } else {
    dispatchBalanceSpan.textContent = "-";
    dispatchQty.removeAttribute("max");
  }
}

dispatchProductSelect.addEventListener("change", updateDispatchBalance);

// Handle Receive Stock (IN)
formReceiveStock.addEventListener("submit", async (e) => {
  e.preventDefault();
  const prodId = Number(receiveProductSelect.value);
  const suppId = receiveSupplierSelect.value ? Number(receiveSupplierSelect.value) : null;
  const locId = receiveLocationSelect.value ? Number(receiveLocationSelect.value) : 1;
  const qty = Number(receiveQty.value);
  const refDoc = receiveRefDoc.value.trim() || null;
  const note = receiveNote.value.trim() || "Standard supplier shipment intake";

  try {
    const res = await apiCall("/movements", {
      method: "POST",
      body: JSON.stringify({
        product_id: prodId,
        supplier_id: suppId,
        location_id: locId,
        type: "IN",
        qty: qty,
        reference_doc: refDoc,
        note: note,
      }),
    });
    showNotice(res.message || `Successfully received ${qty} units!`, "success");
    formReceiveStock.reset();
    await loadOperationsData();
    checkAuditHealth();
  } catch (err) {
    showNotice(err.message, "error");
  }
});

// Handle Dispatch Stock (OUT)
formDispatchStock.addEventListener("submit", async (e) => {
  e.preventDefault();
  const prodId = Number(dispatchProductSelect.value);
  const locId = dispatchLocationSelect.value ? Number(dispatchLocationSelect.value) : 1;
  const qty = Number(dispatchQty.value);
  const refDoc = dispatchRefDoc.value.trim() || null;
  const note = dispatchNote.value.trim() || "Standard stock issue/dispatch";

  const prod = cachedProducts.find((p) => p.id === prodId);
  if (prod && qty > prod.current_stock) {
    showNotice(`Cannot dispatch ${qty} units! Only ${prod.current_stock} available.`, "error");
    return;
  }

  try {
    const res = await apiCall("/movements", {
      method: "POST",
      body: JSON.stringify({
        product_id: prodId,
        location_id: locId,
        type: "OUT",
        qty: qty,
        reference_doc: refDoc,
        note: note,
      }),
    });
    showNotice(res.message || `Successfully dispatched ${qty} units!`, "success");
    formDispatchStock.reset();
    dispatchBalanceSpan.textContent = "-";
    await loadOperationsData();
    checkAuditHealth();
  } catch (err) {
    showNotice(err.message, "error");
  }
});

// ----------------------------------------------------------------------------
// Tab 3: Audit Ledger & Tamper Demo
// ----------------------------------------------------------------------------
async function checkAuditHealth() {
  try {
    const verify = await apiCall("/audit/verify");
    updateAuditUI(verify);
  } catch (e) {
    console.error("Health check error:", e);
  }
}

async function loadAuditTrail() {
  try {
    const [blocks, verify] = await Promise.all([
      apiCall("/audit?limit=50"),
      apiCall("/audit/verify"),
    ]);

    updateAuditUI(verify);
    renderAuditBlocks(blocks);
  } catch (err) {
    auditTableBody.innerHTML = `<tr><td colspan="7" class="text-center text-error">Failed to load audit blocks: ${err.message}</td></tr>`;
  }
}

function updateAuditUI(verify) {
  const isOk = verify && verify.verified;

  // Topbar indicator
  if (isOk) {
    chainStatusDot.className = "status-dot verified";
    chainStatusText.textContent = "Audit Ledger: Verified";
  } else {
    chainStatusDot.className = "status-dot tampered";
    chainStatusText.textContent = `Tamper Detected! (Block #${verify.broken_at_id || "?"})`;
  }

  // Hero Card
  if (isOk) {
    auditHeroBadge.className = "status-indicator-badge verified";
    auditHeroBadge.textContent = "100% VERIFIED";
    auditHeroTitle.textContent = "Cryptographic Audit Chain Intact";
    auditHeroSubtitle.textContent = `All ${verify.total_blocks} blocks mathematically verified across Contiguity, Linkage, HMAC-SHA256, Relational Reconciliation, and External Anchor.`;
  } else {
    auditHeroBadge.className = "status-indicator-badge tampered";
    auditHeroBadge.textContent = "TAMPER DETECTED";
    auditHeroTitle.textContent = `Mathematical Violation at Block #${verify.broken_at_id || "Head"}`;
    auditHeroSubtitle.textContent = `Security alert: ${verify.reason || "Hash chain mismatch or unkeyed direct file modification detected."}`;
  }

  // 5-Point Check Grid
  const checks = verify.checks || {};
  setCheckStatus("checkContiguity", checks.contiguity);
  setCheckStatus("checkLinkage", checks.linkage);
  setCheckStatus("checkIntegrity", checks.integrity);
  setCheckStatus("checkReconciliation", checks.reconciliation);
  setCheckStatus("checkAnchor", checks.anchor);
}

function setCheckStatus(elemId, passed) {
  const el = document.getElementById(elemId);
  if (!el) return;
  const dot = el.querySelector(".check-dot");
  if (passed) {
    dot.className = "check-dot pass";
    dot.textContent = "OK";
  } else {
    dot.className = "check-dot fail";
    dot.textContent = "FAIL";
  }
}

function renderAuditBlocks(blocks) {
  auditBlockCountBadge.textContent = `${blocks.length} Blocks`;

  if (!blocks || blocks.length === 0) {
    auditTableBody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No audit entries found.</td></tr>`;
    return;
  }

  auditTableBody.innerHTML = blocks
    .map((b) => {
      return `
        <tr>
          <td><strong class="block-num">#${b.id}</strong></td>
          <td><span class="badge badge-secondary">${escapeHtml(b.action)}</span></td>
          <td><span class="user-pill">${escapeHtml(b.actor)}</span></td>
          <td><small>${escapeHtml(b.ref_table || "-")} ${b.ref_id ? `(#${b.ref_id})` : ""}</small></td>
          <td class="text-muted"><small>${formatDate(b.timestamp)}</small></td>
          <td><small>${escapeHtml(b.details)}</small></td>
          <td>
            <code class="hash-code" title="Full Hash: ${b.row_hash}">${b.row_hash.substring(0, 16)}...</code>
          </td>
        </tr>
      `;
    })
    .join("");
}

btnRunAuditVerify.addEventListener("click", async () => {
  btnRunAuditVerify.disabled = true;
  btnRunAuditVerify.textContent = "Scanning...";
  try {
    const verify = await apiCall("/audit/verify");
    updateAuditUI(verify);
    if (verify.verified) {
      showNotice("Integrity Scan complete: All audit blocks 100% valid!", "success");
    } else {
      showNotice(`Integrity Scan alert: ${verify.reason}`, "error");
    }
  } catch (err) {
    showNotice(err.message, "error");
  } finally {
    btnRunAuditVerify.disabled = false;
    btnRunAuditVerify.textContent = "Verify Chain";
  }
});

btnSimulateTamper.addEventListener("click", async () => {
  if (!confirm("Simulate rogue disk-level tampering on Block #1? (Bypasses triggers and writes unkeyed SHA-256 hash to test cryptographic detection)")) {
    return;
  }
  try {
    const res = await apiCall("/audit/tamper-demo", { method: "POST" });
    showNotice("Tampering simulated on Block #1. Running verification scan...", "warning");
    const verify = await apiCall("/audit/verify");
    updateAuditUI(verify);
    loadAuditTrail();
  } catch (err) {
    showNotice(err.message, "error");
  }
});

btnResetDatabase.addEventListener("click", async () => {
  if (!confirm("Reset database to clean relational baseline? All products, initial receipts, and audit chain will be cleanly reseeded.")) {
    return;
  }
  try {
    const res = await apiCall("/reset-demo", { method: "POST" });
    showNotice(res.message || "Database reset successfully!", "success");
    await loadAllData();
    switchTab(tabInventory);
  } catch (err) {
    showNotice(err.message, "error");
  }
});

// ----------------------------------------------------------------------------
// Tab 4: Engine Diagnostics & Probes
// ----------------------------------------------------------------------------
async function loadDiagnostics() {
  try {
    const info = await apiCall("/debug/internals");
    diagSqliteVersion.textContent = `v${info.sqlite_version}`;
    diagWalSub.textContent = `Journal: ${info.pragmas.journal_mode}`;
    diagDbSize.textContent = `${(info.pragmas.db_size_bytes / 1024).toFixed(1)} KB`;
    diagPageSub.textContent = `Page Size: ${info.pragmas.page_size_bytes}B`;
    diagFkStatus.textContent = info.pragmas.foreign_keys ? "ENFORCED" : "OFF";
    diagBusyTimeout.textContent = `${info.pragmas.busy_timeout_ms.toLocaleString()} ms`;

    // Row counts (clickable to jump to table explorer)
    const counts = info.row_counts || {};
    diagRowCountsGrid.innerHTML = Object.entries(counts)
      .map(([tbl, cnt]) => `
        <div class="row-count-card" style="cursor: pointer;" onclick="selectExplorerTable('${tbl}')" title="Click to inspect ${tbl} table">
          <span class="count-table">${tbl}</span>
          <strong class="count-num">${cnt}</strong>
        </div>
      `)
      .join("");

    // Load default table in Explorer
    const activeBtn = document.querySelector(".btn-db-table.active");
    const defaultTbl = activeBtn ? activeBtn.getAttribute("data-table") : "products";
    await loadTableExplorer(defaultTbl);

    // Triggers and Views definitions
    const triggers = info.triggers || [];
    const views = info.views || [];
    let html = "";

    if (views.length > 0) {
      html += `<h4>Compiled Relational Views (${views.length})</h4>`;
      views.forEach((v) => {
        html += `
          <div class="def-box">
            <div class="def-header"><strong>VIEW:</strong> <code>${escapeHtml(v.name)}</code></div>
            <pre><code>${escapeHtml(v.sql || "")}</code></pre>
          </div>
        `;
      });
    }

    if (triggers.length > 0) {
      html += `<h4 class="mt-3">Active Engine Triggers (${triggers.length})</h4>`;
      triggers.forEach((t) => {
        html += `
          <div class="def-box">
            <div class="def-header"><strong>TRIGGER:</strong> <code>${escapeHtml(t.name)}</code> <small class="text-muted">(Table: ${escapeHtml(t.tbl_name)})</small></div>
            <pre><code>${escapeHtml(t.sql || "")}</code></pre>
          </div>
        `;
      });
    }

    diagTriggersViewsList.innerHTML = html;
  } catch (err) {
    diagTriggersViewsList.innerHTML = `<div class="notice notice-error">${err.message}</div>`;
  }
}

// Live Database Table & Schema Explorer
window.selectExplorerTable = async function (tableName) {
  document.querySelectorAll(".btn-db-table").forEach((btn) => {
    if (btn.getAttribute("data-table") === tableName) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
  await loadTableExplorer(tableName);
};

document.querySelectorAll(".btn-db-table").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tbl = btn.getAttribute("data-table");
    window.selectExplorerTable(tbl);
  });
});

async function loadTableExplorer(tableName) {
  const explorerRowCountBadge = document.getElementById("explorerRowCountBadge");
  const explorerSchemaTitle = document.getElementById("explorerSchemaTitle");
  const explorerColumnsBody = document.getElementById("explorerColumnsBody");
  const explorerRowsTitle = document.getElementById("explorerRowsTitle");
  const explorerRawHead = document.getElementById("explorerRawHead");
  const explorerRawBody = document.getElementById("explorerRawBody");
  const explorerDdlLabel = document.getElementById("explorerDdlLabel");
  const explorerDdlCode = document.getElementById("explorerDdlCode");

  if (!explorerColumnsBody) return;

  try {
    const data = await apiCall(`/debug/table/${encodeURIComponent(tableName)}?limit=50`);
    explorerRowCountBadge.textContent = `${data.total_rows} Rows (${data.object_type})`;
    explorerSchemaTitle.textContent = `${data.object_type} Structure: ${data.name} (PRAGMA table_info & foreign_key_list)`;
    explorerRowsTitle.textContent = `Actual Raw Database Rows: SELECT * FROM ${data.name} LIMIT 50;`;
    explorerDdlLabel.textContent = `Compiled SQLite DDL (${data.object_type} ${data.name}):`;
    explorerDdlCode.textContent = data.ddl_sql || "-- Built-in object";

    // Build FK lookup map by column name
    const fkMap = {};
    (data.foreign_keys || []).forEach((fk) => {
      fkMap[fk.column] = fk;
    });

    // Render column definitions
    const cols = data.columns || [];
    explorerColumnsBody.innerHTML = cols
      .map((c) => {
        let keyBadge = "-";
        if (c.is_pk) {
          keyBadge = `<span class="badge badge-success">PRIMARY KEY</span>`;
        } else if (fkMap[c.name]) {
          const fk = fkMap[c.name];
          keyBadge = `<span class="badge badge-warning">FK &rarr; ${escapeHtml(fk.references_table)}(${escapeHtml(fk.references_column)}) [${escapeHtml(fk.on_delete)}]</span>`;
        }
        return `
          <tr>
            <td>${c.cid}</td>
            <td><strong><code>${escapeHtml(c.name)}</code></strong></td>
            <td><span class="badge badge-secondary">${escapeHtml(c.type)}</span></td>
            <td>${c.notnull ? "NOT NULL" : "NULLABLE"}</td>
            <td><code>${c.default_value !== null ? escapeHtml(String(c.default_value)) : "-"}</code></td>
            <td>${keyBadge}</td>
          </tr>
        `;
      })
      .join("");

    // Render Raw Rows
    const rows = data.rows || [];
    if (cols.length > 0) {
      explorerRawHead.innerHTML = `<tr>${cols.map((c) => `<th>${escapeHtml(c.name)}</th>`).join("")}</tr>`;
    } else {
      explorerRawHead.innerHTML = "";
    }

    if (rows.length === 0) {
      explorerRawBody.innerHTML = `<tr><td colspan="${Math.max(1, cols.length)}" class="text-center text-muted">No rows in ${escapeHtml(data.name)}.</td></tr>`;
    } else {
      explorerRawBody.innerHTML = rows
        .map((r) => {
          const cells = cols
            .map((c) => {
              let val = r[c.name];
              if (val === null || val === undefined) {
                return `<td class="text-muted"><em>NULL</em></td>`;
              }
              let strVal = String(val);
              if (strVal.length > 48) {
                return `<td title="${escapeHtml(strVal)}"><code>${escapeHtml(strVal.substring(0, 45))}...</code></td>`;
              }
              return `<td>${escapeHtml(strVal)}</td>`;
            })
            .join("");
          return `<tr>${cells}</tr>`;
        })
        .join("");
    }
  } catch (err) {
    explorerColumnsBody.innerHTML = `<tr><td colspan="6" class="text-center text-error">${escapeHtml(err.message)}</td></tr>`;
  }
}

// Interactive SQL Probe runner
document.querySelectorAll(".btn-probe").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const probeType = btn.getAttribute("data-probe");
    try {
      const res = await apiCall("/debug/sql-probe", {
        method: "POST",
        body: JSON.stringify({ probe_type: probeType }),
      });

      probeResultBox.classList.remove("hidden");
      probeTitle.textContent = `${res.title} (${res.execution_time_ms} ms)`;
      probeStatusBadge.textContent = res.status;
      probeStatusBadge.className = `badge ${res.status === "INTERCEPTED" ? "badge-success" : "badge-secondary"}`;
      probeSql.textContent = res.sql;

      if (res.plan_rows) {
        probeEngineOutput.innerHTML = `<pre>${JSON.stringify(res.plan_rows, null, 2)}</pre>`;
      } else {
        probeEngineOutput.innerHTML = `<strong>Result:</strong> <code>${escapeHtml(res.result || "")}</code>`;
      }

      if (res.process_steps) {
        probeStepsList.innerHTML = res.process_steps
          .map((step) => `<li>${escapeHtml(step)}</li>`)
          .join("");
      }
    } catch (err) {
      showNotice(err.message, "error");
    }
  });
});

// ----------------------------------------------------------------------------
// Modals Handlers
// ----------------------------------------------------------------------------
btnOpenAddProduct.addEventListener("click", () => {
  addProductModal.classList.remove("hidden");
  newProdSku.focus();
});
btnCloseAddProduct.addEventListener("click", () => addProductModal.classList.add("hidden"));
btnCancelAddProduct.addEventListener("click", () => addProductModal.classList.add("hidden"));

formAddProduct.addEventListener("submit", async (e) => {
  e.preventDefault();
  const sku = newProdSku.value.trim().toUpperCase();
  const name = newProdName.value.trim();
  const catId = Number(newProdCategory.value);
  const price = Number(newProdPrice.value);
  const threshold = Number(newProdThreshold.value);

  try {
    const res = await apiCall("/products", {
      method: "POST",
      body: JSON.stringify({
        sku: sku,
        name: name,
        category_id: catId,
        unit_price: price,
        reorder_threshold: threshold,
      }),
    });
    showNotice(res.message || "Product created successfully!", "success");
    addProductModal.classList.add("hidden");
    formAddProduct.reset();
    await loadProducts();
    checkAuditHealth();
  } catch (err) {
    showNotice(err.message, "error");
  }
});

btnOpenHelp.addEventListener("click", () => vivaGuideModal.classList.remove("hidden"));
btnCloseVivaGuide.addEventListener("click", () => vivaGuideModal.classList.add("hidden"));
btnDoneVivaGuide.addEventListener("click", () => vivaGuideModal.classList.add("hidden"));

// ----------------------------------------------------------------------------
// Navigation and Filter Listeners
// ----------------------------------------------------------------------------
btnNavInventory.addEventListener("click", () => switchTab(tabInventory));
btnNavOperations.addEventListener("click", () => switchTab(tabOperations));
btnNavAudit.addEventListener("click", () => switchTab(tabAudit));
btnNavDiagnostics.addEventListener("click", () => switchTab(tabDiagnostics));
btnBrand.addEventListener("click", () => switchTab(tabInventory));

productSearchInput.addEventListener("input", renderInventory);
categoryFilterSelect.addEventListener("change", renderInventory);
stockFilterSelect.addEventListener("change", renderInventory);
btnRefreshInventory.addEventListener("click", loadProducts);

// ----------------------------------------------------------------------------
// Auth Form Listeners
// ----------------------------------------------------------------------------
loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  handleLogin(loginUsername.value.trim(), loginPassword.value);
});

btnQuickAdmin.addEventListener("click", () => {
  handleLogin("admin", "vault-admin-2026");
});

btnQuickStaff.addEventListener("click", () => {
  handleLogin("staff", "vault-staff-2026");
});

btnLogout.addEventListener("click", () => {
  clearSession();
  showLogin();
  showNotice("Signed out successfully.", "info");
});

btnThemeToggle.addEventListener("click", toggleTheme);
btnLoginThemeToggle.addEventListener("click", toggleTheme);

// ----------------------------------------------------------------------------
// App Bootstrapping
// ============================================================================
window.addEventListener("DOMContentLoaded", () => {
  const currentTheme = localStorage.getItem(THEME_KEY) || "light";
  applyTheme(currentTheme);

  checkPublicConfig();

  if (loadSession()) {
    showApp();
  } else {
    showLogin();
  }
});

// Helper utilities
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch (e) {
    return isoStr;
  }
}
