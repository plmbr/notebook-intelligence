(function () {
  var STORAGE_KEY = "nbi-theme";
  var root = document.documentElement;
  var btn = document.querySelector("[data-theme-toggle]");
  if (!btn) return;

  var sun = btn.querySelector(".theme-toggle__sun");
  var moon = btn.querySelector(".theme-toggle__moon");

  function effectiveTheme() {
    var attr = root.getAttribute("data-theme");
    if (attr === "light" || attr === "dark") return attr;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function render(theme) {
    var dark = theme === "dark";
    if (sun) sun.hidden = dark;
    if (moon) moon.hidden = !dark;
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }

  render(effectiveTheme());

  btn.addEventListener("click", function () {
    var next = effectiveTheme() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (e) {}
    render(next);
  });
})();
