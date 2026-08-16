(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.CanonicalManagementApp || !window.__HERMES_PLUGINS__) {
    throw new Error("Hermes Control Center canonical UI is not initialized.");
  }
  window.__HERMES_PLUGINS__.register("hermes-extensions", HX.CanonicalManagementApp);
})();
