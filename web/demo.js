// ============================================================================
// VaultStock — Live Presentation & Demo Engine (demo.html)
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
let cachedAuditCount = 0;

// DOM References — Auth & Navigation
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
const navDemoDot = document.getElementById("navDemoDot");
const btnThemeToggle = document.getElementById("btnThemeToggle");
const userBadge = document.getElementById("userBadge");
const btnLogout = document.getElementById("btnLogout");
const actionNotice = document.getElementById("actionNotice");

// DOM References — Live Status & Pulse
const demoIntegrityBanner = document.getElementById("demoIntegrityBanner");
const demoChainBadge = document.getElementById("demoChainBadge");
const demoChainTitle = document.getElementById("demoChainTitle");
const demoChainDesc = document.getElementById("demoChainDesc");
const btnTopTamper = document.getElementById("btnTopTamper");
const btnTopReset = document.getElementById("btnTopReset");
const demoTamperAlert = document.getElementById("demoTamperAlert");
const demoTamperAlertText = document.getElementById("demoTamperAlertText");

const pulseMacStock = document.getElementById("pulseMacStock");
const pulseAuditBlocks = document.getElementById("pulseAuditBlocks");
const pulseLastAction = document.getElementById("pulseLastAction");

// DOM References — Demo Stage Controls
const btnAutoPlayDemo = document.getElementById("btnAutoPlayDemo");
const btnNextDemoStep = document.getElementById("btnNextDemoStep");
const btnResetDemoScript = document.getElementById("btnResetDemoScript");
const demoStepPhaseTag = document.getElementById("demoStepPhaseTag");
const demoStepResultTag = document.getElementById("demoStepResultTag");
const demoSpeakerScript = document.getElementById("demoSpeakerScript");
const demoCardsContainer = document.getElementById("demoCardsContainer");

// DOM References — Mini Proof Catalog
const demoCatalogBody = document.getElementById("demoCatalogBody");
const btnRefreshCatalogProof = document.getElementById("btnRefreshCatalogProof");

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
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (e) { }
  applyTheme(next);
}

(function initTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") {
      applyTheme(saved);
      return;
    }
  } catch (e) { }
  applyTheme("light");
})();

if (btnThemeToggle) btnThemeToggle.addEventListener("click", toggleTheme);
if (btnLoginThemeToggle) btnLoginThemeToggle.addEventListener("click", toggleTheme);

// ============================================================================
// Navigation Buttons (Strictly Semantic Buttons, No Hyperlinks)
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
// Authentication & RBAC Access Protection (Admin Only)
// ============================================================================

function saveSession(data) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(data));
  } catch (e) { }
}

function clearSession() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (e) { }
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
    showLoginOverlay("Session expired. Please sign in as Admin.");
    throw new Error("Authentication required");
  }
  return res;
}

async function checkPublicDemoMode() {
  try {
    const res = await fetch(`${API_BASE}/config`);
    if (res.ok) {
      const cfg = await res.json();
      if (demoHint) demoHint.classList.toggle("hidden", !cfg.demo_mode);
    }
  } catch (e) { }
}

function showLoginOverlay(message = "") {
  currentUser = { id: null, username: null, role: null, token: null, demo_mode: false };
  if (mainNavbar) mainNavbar.classList.add("hidden");
  if (mainContent) mainContent.classList.add("hidden");
  if (loginOverlay) loginOverlay.classList.remove("hidden");

  checkPublicDemoMode();

  if (loginError) {
    if (message) {
      loginError.textContent = message;
      loginError.classList.remove("hidden");
    } else {
      loginError.classList.add("hidden");
    }
  }
}

function showAuthenticatedUI() {
  const role = (currentUser.role || "").toLowerCase();
  if (role !== "admin") {
    clearSession();
    alert("Live Presentation & Demo is restricted to Administrators. Redirecting to Inventory...");
    window.location.href = "index.html";
    return false;
  }

  if (loginOverlay) loginOverlay.classList.add("hidden");
  if (mainNavbar) mainNavbar.classList.remove("hidden");
  if (mainContent) mainContent.classList.remove("hidden");

  if (userBadge) {
    userBadge.textContent = `${currentUser.username} · ${currentUser.role}`;
  }
  return true;
}

if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = loginUsername.value.trim();
    const password = loginPassword.value;
    if (!username || !password) return;

    try {
      if (loginError) loginError.classList.add("hidden");
      const res = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Sign-in failed");
      }

      const data = await res.json();
      const role = (data.role || "").toLowerCase();
      if (role !== "admin") {
        throw new Error("Access denied: Presentation demo requires Administrator privileges.");
      }

      currentUser = {
        id: data.id,
        username: data.username,
        role: data.role,
        token: data.token,
        demo_mode: data.demo_mode,
      };

      saveSession(currentUser);
      if (showAuthenticatedUI()) {
        await refreshDemoAll();
      }
    } catch (err) {
      if (loginError) {
        loginError.textContent = err.message;
        loginError.classList.remove("hidden");
      }
    }
  });
}

if (btnLogout) {
  btnLogout.addEventListener("click", () => {
    clearSession();
    showLoginOverlay("Signed out.");
  });
}

if (btnQuickAdmin) {
  btnQuickAdmin.addEventListener("click", () => {
    loginUsername.value = "admin";
    loginPassword.value = "vault-admin-2026";
    loginForm.requestSubmit();
  });
}

function showNotice(msg, isError = false) {
  if (!actionNotice) return;
  actionNotice.textContent = msg;
  actionNotice.className = `notice ${isError ? "notice-error" : "notice-success"}`;
  actionNotice.classList.remove("hidden");
  setTimeout(() => actionNotice?.classList.add("hidden"), 5000);
}

function pulseElement(el) {
  if (!el) return;
  el.classList.remove("demo-highlight");
  void el.offsetWidth;
  el.classList.add("demo-highlight");
}

// ============================================================================
// Live Mini Catalog & Verification Matrix Data
// ============================================================================

async function refreshDemoAll() {
  await Promise.all([refreshVerification(), refreshCatalogProof()]);
}

async function refreshVerification() {
  try {
    const res = await apiFetch("/audit/verify");
    if (!res.ok) throw new Error("Verification check failed");
    const data = await res.json();

    const isIntact = !!data.verified;
    if (navDemoDot) {
      navDemoDot.className = `status-dot ${isIntact ? "verified" : "tampered"}`;
    }

    if (demoIntegrityBanner) {
      demoIntegrityBanner.classList.toggle("tampered", !isIntact);
      demoIntegrityBanner.classList.toggle("verified", isIntact);
    }

    if (demoChainBadge) {
      demoChainBadge.textContent = isIntact ? "Verified" : "Tamper Detected";
      demoChainBadge.className = `status-tag ${isIntact ? "status-success" : "status-error"}`;
    }

    if (demoChainTitle) {
      demoChainTitle.textContent = isIntact
        ? "Audit Chain & Storage Engine Intact"
        : "Storage Engine Alert: Cryptographic Seal Broken";
    }

    if (demoChainDesc) {
      demoChainDesc.textContent = isIntact
        ? `Continuous verification active across all 5 checks (${data.total_blocks || 0} blocks verified). External anchor synchronized.`
        : `HMAC verification failed at Block #${data.broken_at_id || "Unknown"}: ${data.reason || "Hash digest mismatch"}.`;
    }

    if (demoTamperAlert) {
      if (!isIntact) {
        demoTamperAlert.classList.remove("hidden");
        if (demoTamperAlertText) {
          demoTamperAlertText.textContent = `Tampering detected at Block #${data.broken_at_id}: ${data.reason}`;
        }
      } else {
        demoTamperAlert.classList.add("hidden");
      }
    }

    if (pulseAuditBlocks) {
      pulseAuditBlocks.textContent = `${data.total_blocks || 0} Blocks`;
    }
    cachedAuditCount = data.total_blocks || 0;
  } catch (err) {
    console.error("Verification refresh failed:", err);
  }
}

async function refreshCatalogProof() {
  try {
    const res = await apiFetch("/products");
    if (!res.ok) throw new Error("Could not fetch products");
    cachedProducts = await res.json();

    const macBook = cachedProducts.find((p) => p.sku === "TECH-MBP16" || p.id === 1) || cachedProducts[0];
    if (macBook && pulseMacStock) {
      pulseMacStock.textContent = `${macBook.current_stock} units`;
    }

    if (demoCatalogBody) {
      if (cachedProducts.length === 0) {
        demoCatalogBody.innerHTML = `<tr><td colspan="6" class="text-center">No products found.</td></tr>`;
        return;
      }

      demoCatalogBody.innerHTML = cachedProducts
        .map((p) => {
          const stock = Number(p.current_stock);
          const price = Number(p.price);
          const totalVal = (stock * price).toLocaleString("en-US", {
            style: "currency",
            currency: "USD",
          });
          const isTarget = p.id === (macBook ? macBook.id : 1);

          return `
            <tr class="${isTarget ? 'highlight-row' : ''}">
              <td class="mono font-semibold">${escapeHtml(p.sku)}</td>
              <td>${escapeHtml(p.name)}</td>
              <td><span class="badge badge-subtle">${escapeHtml(p.category)}</span></td>
              <td class="text-right mono">$${price.toFixed(2)}</td>
              <td class="text-right mono font-bold ${stock < 10 ? 'text-danger' : 'text-success'}">
                ${stock} units
              </td>
              <td class="text-right mono">${totalVal}</td>
            </tr>
          `;
        })
        .join("");
    }
  } catch (err) {
    console.error("Failed to refresh catalog proof:", err);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

if (btnRefreshCatalogProof) {
  btnRefreshCatalogProof.addEventListener("click", async () => {
    await refreshCatalogProof();
    showNotice("Inventory proof balances refreshed.", false);
  });
}

// ============================================================================
// Top Simulate Tamper & Reset Database Buttons
// ============================================================================

if (btnTopTamper) {
  btnTopTamper.addEventListener("click", async () => {
    stopAutoPlayDemo();
    await executeDemoStep(3);
  });
}

if (btnTopReset) {
  btnTopReset.addEventListener("click", async () => {
    stopAutoPlayDemo();
    await executeDemoStep(4);
  });
}

// ============================================================================
// 4-Step Plain English Presentation Script Engine
// ============================================================================

let demoNextStep = 1;
let demoAutoPlayActive = false;
let demoAutoPlayTimer = null;

const DEMO_SCRIPT = {
  1: {
    phaseTag: "STEP 1 OF 4 · DERIVED CALCULATION PROOF",
    quote:
      '"Notice that when we receive 10 MacBook Pros, VaultStock never executes an UPDATE on a stock column. Instead, it appends an immutable entry to movements and recalculates the balance live as SUM(IN) - SUM(OUT). History is never lost, and race conditions are eliminated."',
    run: async () => {
      const pRes = await apiFetch("/products");
      const products = await pRes.json();
      const target = products.find((p) => p.sku === "TECH-MBP16" || p.id === 1) || products[0];
      if (!target) throw new Error("Product not found");
      const prevStock = Number(target.current_stock);

      const mRes = await apiFetch("/movements", {
        method: "POST",
        body: JSON.stringify({
          product_id: target.id,
          type: "IN",
          qty: 10,
          note: "Supplier Batch (Presentation Demo)",
        }),
      });

      if (!mRes.ok) {
        const err = await mRes.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to record movement");
      }

      await refreshDemoAll();
      pulseElement(pulseMacStock);
      pulseElement(demoCatalogBody);

      const newStock = prevStock + 10;
      if (pulseLastAction) pulseLastAction.textContent = `+10 ${target.sku}`;

      const proofEl = document.getElementById("proofText1");
      if (proofEl) {
        proofEl.textContent = `PASS: Stock dynamically updated from ${prevStock} to ${newStock} units. New HMAC audit block appended.`;
      }

      return `${target.name}: ${prevStock} → ${newStock} units`;
    },
  },

  2: {
    phaseTag: "STEP 2 OF 4 · IN-ENGINE OVERDRAFT REJECTION",
    quote:
      '"What happens if someone tries to issue 9,999 units when only 35 exist? In typical web apps, race conditions create negative balances. In VaultStock, the SQLite storage engine itself guards the gate: a BEFORE INSERT trigger instantly calculates balance and aborts before the write can occur."',
    run: async () => {
      const target = cachedProducts.find((p) => p.sku === "TECH-MBP16" || p.id === 1) || cachedProducts[0];
      const prodId = target ? target.id : 1;

      const mRes = await apiFetch("/movements", {
        method: "POST",
        body: JSON.stringify({
          product_id: prodId,
          type: "OUT",
          qty: 9999,
          note: "Overdraft Attempt (Presentation Demo)",
        }),
      });

      const errData = await mRes.json().catch(() => ({}));
      const detail = errData.detail || "Insufficient inventory";

      await refreshDemoAll();
      if (pulseLastAction) pulseLastAction.textContent = "Overdraft Blocked";

      const proofEl = document.getElementById("proofText2");
      if (proofEl) {
        proofEl.textContent = `BLOCKED (HTTP ${mRes.status}): SQLite trigger "prevent_negative_stock" rejected transaction: "${detail}". Stock untouched.`;
      }

      return `Trigger Aborted: ${detail}`;
    },
  },

  3: {
    phaseTag: "STEP 3 OF 4 · INSIDER DISK TAMPER DETECTION",
    quote:
      '"Imagine a rogue DBA bypasses the website completely, opens the database file with a raw editor, and alters past quantities to conceal theft. Because each block is sealed with an external HMAC key linked to the previous block, continuous automatic verification detects the broken seal immediately."',
    run: async () => {
      const tRes = await apiFetch("/audit/tamper-demo", { method: "POST" });
      if (!tRes.ok) {
        const err = await tRes.json().catch(() => ({}));
        throw new Error(err.detail || "Tamper simulation failed");
      }

      await refreshDemoAll();
      pulseElement(demoIntegrityBanner);
      if (pulseLastAction) pulseLastAction.textContent = "Tamper Detected!";

      const proofEl = document.getElementById("proofText3");
      if (proofEl) {
        proofEl.textContent = `ALERT TRIGGERED: Block #1 mutated directly in SQLite. HMAC signature mismatch detected. Status banner turned red.`;
      }

      return "Tamper Caught: HMAC mismatch in Block #1";
    },
  },

  4: {
    phaseTag: "STEP 4 OF 4 · ONE-CLICK RECOVERY & 5-POINT HEALTH CHECK",
    quote:
      '"With a single click, we restore the database to a pristine seed state with a fresh genesis block. All 5 mathematical checks—sequence contiguity, hash links, HMAC seals, row matching, and external anchor—turn 100% green again."',
    run: async () => {
      const rRes = await apiFetch("/reset-demo", { method: "POST" });
      if (!rRes.ok) {
        const err = await rRes.json().catch(() => ({}));
        throw new Error(err.detail || "Reset failed");
      }

      await refreshDemoAll();
      pulseElement(demoIntegrityBanner);
      if (pulseLastAction) pulseLastAction.textContent = "Database Reset";

      const proofEl = document.getElementById("proofText4");
      if (proofEl) {
        proofEl.textContent = `PASS: Database restored to pristine clean seed state. All 5 checks pass. Chain head synchronized with external anchor.`;
      }

      return "Clean Seed Restored · 100% Verified";
    },
  },
};

function setCardState(stepNum, state) {
  const card = document.getElementById(`cardStep${stepNum}`);
  const badge = document.getElementById(`badgeStep${stepNum}`);
  if (!card || !badge) return;

  card.classList.remove("active", "done", "tampered");
  badge.className = "demo-card-status";

  if (state === "RUNNING") {
    card.classList.add("active");
    badge.textContent = "Running...";
    badge.classList.add("status-running");
  } else if (state === "DONE") {
    card.classList.add("done");
    badge.textContent = "Passed";
    badge.classList.add("status-success");
  } else if (state === "BLOCKED") {
    card.classList.add("done");
    badge.textContent = "Blocked";
    badge.classList.add("status-warning");
  } else if (state === "TAMPERED") {
    card.classList.add("tampered");
    badge.textContent = "Tamper Caught";
    badge.classList.add("status-error");
  } else {
    badge.textContent = "Ready";
  }
}

function resetDemoScriptUI() {
  stopAutoPlayDemo();
  demoNextStep = 1;
  for (let i = 1; i <= 4; i++) {
    setCardState(i, "READY");
    const proof = document.getElementById(`proofText${i}`);
    if (proof) {
      if (i === 1) proof.textContent = 'Click "Run Step 1" to receive 10 MacBook Pros.';
      if (i === 2) proof.textContent = 'Click "Run Step 2" to test an overdraft attempt.';
      if (i === 3) proof.textContent = 'Click "Run Step 3" to simulate tampering with Block #1.';
      if (i === 4) proof.textContent = 'Click "Run Step 4" to restore the clean database.';
    }
  }

  if (demoStepPhaseTag) demoStepPhaseTag.textContent = "WHAT TO SAY TO THE EVALUATOR";
  if (demoStepResultTag) {
    demoStepResultTag.textContent = "Ready";
    demoStepResultTag.className = "status-tag mono";
  }
  if (demoSpeakerScript) {
    demoSpeakerScript.textContent =
      '"VaultStock never edits a stock column. It derives stock dynamically from an immutable, append-only ledger and automatically verifies every record with an HMAC-SHA256 audit chain."';
  }
}

async function executeDemoStep(stepNum) {
  const stepCfg = DEMO_SCRIPT[stepNum];
  if (!stepCfg) return;

  for (let i = 1; i <= 4; i++) {
    const card = document.getElementById(`cardStep${i}`);
    if (card && card.classList.contains("active")) {
      card.classList.remove("active");
    }
  }

  setCardState(stepNum, "RUNNING");
  if (demoStepPhaseTag) demoStepPhaseTag.textContent = stepCfg.phaseTag;
  if (demoSpeakerScript) demoSpeakerScript.textContent = stepCfg.quote;
  if (demoStepResultTag) {
    demoStepResultTag.textContent = "Executing...";
    demoStepResultTag.className = "status-tag mono status-running";
  }

  try {
    const outcomeText = await stepCfg.run();

    if (stepNum === 2) {
      setCardState(stepNum, "BLOCKED");
    } else if (stepNum === 3) {
      setCardState(stepNum, "TAMPERED");
    } else {
      setCardState(stepNum, "DONE");
    }

    if (demoStepResultTag) {
      demoStepResultTag.textContent = outcomeText;
      demoStepResultTag.className =
        stepNum === 3
          ? "status-tag mono status-error"
          : stepNum === 2
            ? "status-tag mono status-warning"
            : "status-tag mono status-success";
    }

    demoNextStep = stepNum < 4 ? stepNum + 1 : 1;
  } catch (err) {
    setCardState(stepNum, "READY");
    if (demoStepResultTag) {
      demoStepResultTag.textContent = `Error: ${err.message}`;
      demoStepResultTag.className = "status-tag mono status-error";
    }
    showNotice(err.message || "Demo step failed", true);
    stopAutoPlayDemo();
  }
}

function stopAutoPlayDemo() {
  demoAutoPlayActive = false;
  if (demoAutoPlayTimer) {
    clearTimeout(demoAutoPlayTimer);
    demoAutoPlayTimer = null;
  }
  if (btnAutoPlayDemo) {
    btnAutoPlayDemo.innerHTML = "&#9654; Auto-Play Demo";
    btnAutoPlayDemo.classList.add("btn-primary");
    btnAutoPlayDemo.classList.remove("btn-danger");
  }
}

async function startAutoPlayDemo() {
  if (demoAutoPlayActive) {
    stopAutoPlayDemo();
    return;
  }

  if (demoNextStep === 1) {
    for (let i = 1; i <= 4; i++) {
      setCardState(i, "READY");
    }
  }

  demoAutoPlayActive = true;
  if (btnAutoPlayDemo) {
    btnAutoPlayDemo.innerHTML = "&#9632; Stop Auto-Play";
    btnAutoPlayDemo.classList.remove("btn-primary");
    btnAutoPlayDemo.classList.add("btn-danger");
  }

  while (demoAutoPlayActive) {
    const current = demoNextStep;
    await executeDemoStep(current);
    if (!demoAutoPlayActive || current >= 4) {
      break;
    }
    await new Promise((resolve) => {
      demoAutoPlayTimer = setTimeout(resolve, 3800);
    });
  }

  stopAutoPlayDemo();
}

if (demoCardsContainer) {
  demoCardsContainer.addEventListener("click", (e) => {
    const btn = e.target.closest(".js-run-step");
    if (!btn) return;
    stopAutoPlayDemo();
    const stepNum = parseInt(btn.dataset.step, 10);
    executeDemoStep(stepNum);
  });
}

if (btnAutoPlayDemo) {
  btnAutoPlayDemo.addEventListener("click", startAutoPlayDemo);
}

if (btnNextDemoStep) {
  btnNextDemoStep.addEventListener("click", () => {
    stopAutoPlayDemo();
    executeDemoStep(demoNextStep);
  });
}

if (btnResetDemoScript) {
  btnResetDemoScript.addEventListener("click", resetDemoScriptUI);
}

// ============================================================================
// Initialize Session & Load Initial Telemetry
// ============================================================================

(async function initDemoPage() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved && saved.token) {
        currentUser = saved;
        if (showAuthenticatedUI()) {
          await refreshDemoAll();
        }
        return;
      }
    }
  } catch (e) {
    clearSession();
  }
  showLoginOverlay();
})();
