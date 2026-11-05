// VaultStock — Theme Initializer (Pre-render execution to eliminate theme flash)
(function () {
  try {
    var t = localStorage.getItem("vaultstock_theme") || "light";
    document.documentElement.setAttribute("data-theme", t);
    if (t === "dark") {
      document.documentElement.classList.add("dark");
    }
  } catch (e) {}
})();

