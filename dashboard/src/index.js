(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.ManagementApp || !window.__HERMES_PLUGINS__) return;
  window.__HERMES_PLUGINS__.register("hermes-extensions", HX.ManagementApp);
})();
