// If the app fails before React can mount, surface the reason on the page
// rather than leaving a blank screen with the cause only in the console.
//
// A separate file rather than an inline <script>: the production CSP is
// script-src 'self', which blocks inline scripts. Inline, this guard
// silently never ran in the one environment it exists for.
(function () {
  var shown = false;
  function show(detail) {
    if (shown) return;
    // React mounts into #root; if it has children the app is alive and
    // this was a later, non-fatal error.
    var root = document.getElementById("root");
    if (root && root.childElementCount > 0) return;
    shown = true;
    var box = document.getElementById("boot-error");
    document.getElementById("boot-error-detail").textContent = detail;
    box.style.display = "block";
  }
  window.addEventListener("error", function (e) {
    var where = e.filename ? "\n  at " + e.filename + ":" + e.lineno + ":" + e.colno : "";
    show((e.message || "Script error") + where + (e.error && e.error.stack ? "\n\n" + e.error.stack : ""));
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason;
    show("Unhandled promise rejection: " + ((r && (r.stack || r.message)) || String(r)));
  });
  // Nothing rendered and nothing threw: usually a module that failed to
  // resolve, which the console records but no event surfaces.
  window.addEventListener("load", function () {
    setTimeout(function () {
      var root = document.getElementById("root");
      if (root && root.childElementCount === 0) {
        show("No error was raised, but nothing rendered.\n\n" +
             "Usually a module that failed to resolve or a component that\n" +
             "returned undefined. Open the browser console for the detail.");
      }
    }, 3000);
  });
})();
