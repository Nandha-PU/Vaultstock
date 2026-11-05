// ============================================================================
// VaultStock — Inventory Management Client (index.html)
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

let currentMovementType = "IN";
let cachedProducts = [];

// DOM References
const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginUsername = document.getElementById("loginUsername");
const loginPassword = document.getElementById("loginPassword");
const loginError = document.getElementById("loginError");
const demoHint = document.getElementById("demoHint");
const btnLoginThemeToggle = document.getElementById("btnLoginThemeToggle");
const btnQuickAdmin = document.getElementById("btnQuickAdmin");
const btnQuickStaff = document.getElementById("btnQuickStaff");

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

const kpiTotalSkus = document.getElementById("kpiTotalSkus");
const kpiTotalUnits = document.getElementById("kpiTotalUnits");
const kpiTotalValue = document.getElementById("kpiTotalValue");
const dashboardChainBadge = document.getElementById("dashboardChainBadge");
const dashboardChainText = document.getElementById("dashboardChainText");
const btnOpenDemo = document.getElementById("btnOpenDemo");
const btnOpenDebug = document.getElementById("btnOpenDebug");

const productSearchInput = document.getElementById("productSearchInput");
const stockFilterSelect = document.getElementById("stockFilterSelect");
const productTableBody = document.getElementById("productTableBody");
const movementFeed = document.getElementById("movementFeed");
const btnRefreshDashboard = document.getElementById("btnRefreshDashboard");

const movementModal = document.getElementById("movementModal");
const btnCloseModal = document.getElementById("btnCloseModal");
const btnCancelModal = document.getElementById("btnCancelModal");
const movementForm = document.getElementById("movementForm");
const modalProductTitle = document.getElementById("modalProductTitle");
const modalProductId = document.getElementById("modalProductId");

const productModal = document.getElementById("productModal");
const btnOpenAddProduct = document.getElementById("btnOpenAddProduct");
const btnCloseProductModal = document.getElementById("btnCloseProductModal");
const btnCancelProductModal = document.getElementById("btnCancelProductModal");
const productForm = document.getElementById("productForm");

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
  } catch (e) {
    // Ignore storage restrictions
  }
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

if (btnOpenDemo) {
  btnOpenDemo.addEventListener("click", () => {
    window.location.href = "demo.html";
  });
}

if (btnOpenDebug) {
  btnOpenDebug.addEventListener("click", () => {
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
// Helpers & API Client
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

async function apiFetch(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (currentUser.token) {
    headers["Authorization"] = `Bearer ${currentUser.token}`;
  }

  const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  if (res.status === 401) {
    clearSession();
    showLoginOverlay("Session expired. Please sign in again.");
    throw new Error("Authentication required");
  }
  return res;
}

// ============================================================================
// Authentication & RBAC Visibility
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
  loginOverlay.classList.add("hidden");
  mainNavbar.classList.remove("hidden");
  mainContent.classList.remove("hidden");

  userBadge.textContent = `${currentUser.username} · ${currentUser.role}`;

  const isAdmin = currentUser.role === "admin";
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.classList.toggle("hidden", !isAdmin);
  });
  document.querySelectorAll(".staff-only").forEach((el) => {
    el.classList.toggle("hidden", isAdmin);
  });
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

    showNotice("");
    showAuthenticatedUI();
    await refreshDashboard();
  } catch (err) {
    loginError.textContent = err.message || "Sign in failed";
    loginError.classList.remove("hidden");
  }
});

btnLogout.addEventListener("click", () => {
  clearSession();
  showLoginOverlay("Signed out.");
});

if (btnQuickAdmin) {
  btnQuickAdmin.addEventListener("click", () => {
    loginUsername.value = "admin";
    loginPassword.value = "vault-admin-2026";
    loginForm.requestSubmit();
  });
}

if (btnQuickStaff) {
  btnQuickStaff.addEventListener("click", () => {
    loginUsername.value = "staff";
    loginPassword.value = "vault-staff-2026";
    loginForm.requestSubmit();
  });
}

// ============================================================================
// Inventory Data & Rendering
// ============================================================================

function renderProductsTable() {
  const query = (productSearchInput?.value || "").trim().toLowerCase();
  const stockFilter = stockFilterSelect?.value || "ALL";

  const filtered = cachedProducts.filter((p) => {
    const matchesSearch =
      !query ||
      p.sku.toLowerCase().includes(query) ||
      p.name.toLowerCase().includes(query);
    const stock = Number(p.current_stock);
    const matchesStock =
      stockFilter === "ALL" ||
      (stockFilter === "OK" && stock > 5) ||
      (stockFilter === "LOW" && stock <= 5);
    return matchesSearch && matchesStock;
  });

  if (filtered.length === 0) {
    productTableBody.innerHTML = `<tr><td colspan="6" class="empty-cell">No matching products found.</td></tr>`;
    return;
  }

  productTableBody.innerHTML = filtered
    .map((p) => {
      const stock = Number(p.current_stock);
      const isLow = stock <= 5;
      const tagClass = isLow ? "tag tag-out" : "tag tag-in";
      const statusLabel = stock === 0 ? "Out of Stock" : isLow ? "Low Stock" : "In Stock";

      return `
        <tr>
          <td class="mono"><strong>${esc(p.sku)}</strong></td>
          <td>${esc(p.name)}</td>
          <td class="num">$${Number(p.unit_price).toFixed(2)}</td>
          <td class="num"><strong>${stock}</strong></td>
          <td><span class="${tagClass}">${statusLabel}</span></td>
          <td class="text-right">
            <div class="action-btn-group">
              <button type="button" class="btn btn-sm btn-in js-move" data-id="${Number(p.id)}" data-name="${esc(p.name)}" data-dir="IN">
                + In
              </button>
              <button type="button" class="btn btn-sm btn-out js-move" data-id="${Number(p.id)}" data-name="${esc(p.name)}" data-dir="OUT">
                &minus; Out
              </button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function updateDashboardKpis() {
  const totalSkus = cachedProducts.length;
  const totalUnits = cachedProducts.reduce((acc, p) => acc + Number(p.current_stock), 0);
  const totalVal = cachedProducts.reduce(
    (acc, p) => acc + Number(p.current_stock) * Number(p.unit_price),
    0
  );

  if (kpiTotalSkus) kpiTotalSkus.textContent = String(totalSkus);
  if (kpiTotalUnits) kpiTotalUnits.textContent = totalUnits.toLocaleString();
  if (kpiTotalValue) {
    kpiTotalValue.textContent =
      "$" + totalVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

async function fetchProducts() {
  const res = await apiFetch("/products");
  cachedProducts = await res.json();
  updateDashboardKpis();
  renderProductsTable();
}

async function fetchMovements() {
  const res = await apiFetch("/movements");
  const movements = await res.json();

  if (movements.length === 0) {
    movementFeed.innerHTML = `<tr><td colspan="7" class="empty-cell">No inventory movements recorded yet.</td></tr>`;
    return;
  }

  movementFeed.innerHTML = movements
    .map((m) => {
      const tagClass = m.type === "IN" ? "tag tag-in" : "tag tag-out";
      const sign = m.type === "IN" ? "+" : "−";
      return `
        <tr>
          <td class="mono">#${Number(m.id)}</td>
          <td><strong>${esc(m.product_name)}</strong> <span class="mono text-muted">(${esc(m.sku)})</span></td>
          <td><span class="${tagClass}">${esc(m.type)}</span></td>
          <td class="num"><strong>${sign}${Number(m.qty)}</strong></td>
          <td>${esc(m.note || "-")}</td>
          <td class="mono">${esc(m.created_by)}</td>
          <td class="mono text-muted">${esc(m.created_at || "-")}</td>
        </tr>
      `;
    })
    .join("");
}

async function fetchIntegrityStatusSummary() {
  const res = await apiFetch("/audit/verify");
  const result = await res.json();

  if (result.verified) {
    if (navDebugDot) navDebugDot.className = "status-dot verified";
    if (dashboardChainBadge) {
      dashboardChainBadge.className = "status-tag verified";
      dashboardChainBadge.textContent = "Verified";
    }
    if (dashboardChainText) {
      dashboardChainText.textContent = "All Records Intact";
    }
  } else {
    if (navDebugDot) navDebugDot.className = "status-dot tampered";
    if (dashboardChainBadge) {
      dashboardChainBadge.className = "status-tag tampered";
      dashboardChainBadge.textContent = "Tamper Alert";
    }
    if (dashboardChainText) {
      dashboardChainText.textContent = `Anomaly at Block #${result.broken_at_id ?? "?"}`;
    }
  }
}

async function refreshDashboard() {
  await Promise.all([fetchProducts(), fetchMovements(), fetchIntegrityStatusSummary()]);
}

if (productSearchInput) {
  productSearchInput.addEventListener("input", renderProductsTable);
}
if (stockFilterSelect) {
  stockFilterSelect.addEventListener("change", renderProductsTable);
}
if (btnRefreshDashboard) {
  btnRefreshDashboard.addEventListener("click", async () => {
    await refreshDashboard();
    showNotice("Inventory refreshed.", false);
  });
}

// ============================================================================
// Modals & Forms
// ============================================================================

function openMovementModal(id, name, defaultType = "IN") {
  modalProductId.value = Number(id);
  modalProductTitle.textContent = `Adjust Stock — ${name}`;
  document.getElementById("moveQty").value = 5;
  document.getElementById("moveNote").value = "Standard stock operation";
  setMovementType(defaultType);
  movementModal.classList.remove("hidden");
}

function closeMovementModal() {
  movementModal.classList.add("hidden");
}

function setMovementType(type) {
  currentMovementType = type;
  document.querySelectorAll(".btn-toggle").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.type === type);
  });
}

productTableBody.addEventListener("click", (e) => {
  const btn = e.target.closest(".js-move");
  if (btn) {
    openMovementModal(Number(btn.dataset.id), btn.dataset.name, btn.dataset.dir || "IN");
  }
});

document.querySelectorAll(".btn-toggle").forEach((btn) => {
  btn.addEventListener("click", () => setMovementType(btn.dataset.type));
});

btnCloseModal.addEventListener("click", closeMovementModal);
btnCancelModal.addEventListener("click", closeMovementModal);

movementForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const productId = parseInt(modalProductId.value, 10);
  const rawQty = document.getElementById("moveQty").value.trim();
  const qty = Number(rawQty);
  if (!Number.isInteger(qty) || qty < 1 || qty > 1000000) {
    showNotice("Quantity must be between 1 and 1,000,000.", true);
    return;
  }
  const note = document.getElementById("moveNote").value.trim();

  try {
    const res = await apiFetch("/movements", {
      method: "POST",
      body: JSON.stringify({
        product_id: productId,
        type: currentMovementType,
        qty: qty,
        note: note || "Standard stock operation",
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to record movement");
    }

    closeMovementModal();
    showNotice(`Recorded ${currentMovementType} movement of ${qty} units.`, false);
    await refreshDashboard();
  } catch (err) {
    showNotice(err.message, true);
  }
});

btnOpenAddProduct.addEventListener("click", () => productModal.classList.remove("hidden"));
btnCloseProductModal.addEventListener("click", () => productModal.classList.add("hidden"));
btnCancelProductModal.addEventListener("click", () => productModal.classList.add("hidden"));

productForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const sku = document.getElementById("newSku").value.trim().toUpperCase();
  const name = document.getElementById("newName").value.trim();
  const unit_price = parseFloat(document.getElementById("newPrice").value);

  try {
    const res = await apiFetch("/products", {
      method: "POST",
      body: JSON.stringify({ sku, name, unit_price }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Could not create product");
    }

    productForm.reset();
    productModal.classList.add("hidden");
    showNotice(`Added product ${name} (${sku}).`, false);
    await refreshDashboard();
  } catch (err) {
    showNotice(err.message, true);
  }
});

// ============================================================================
// Initialize Session
// ============================================================================

(async function initApp() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved && saved.token) {
        currentUser = saved;
        showAuthenticatedUI();
        await refreshDashboard();
        return;
      }
    }
  } catch (e) {
    clearSession();
  }
  showLoginOverlay();
})();
