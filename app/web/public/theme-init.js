// Runs before the application: applies the theme the visitor chose last time, if any.
// The same key as src/lib/theme.ts; without a stored choice the system setting applies.
(function () {
  try {
    var theme = localStorage.getItem("insight-theme");
    if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {
    /* storage blocked: follow the system */
  }
})();
