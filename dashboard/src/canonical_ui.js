(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.ManagementApp) {
    throw new Error("Hermes Control Center canonical UI entry could not resolve ManagementApp.");
  }

  if (HX.CanonicalManagementApp) {
    throw new Error("Hermes Control Center canonical UI entry was initialized more than once.");
  }

  // All compatibility modules must finish before this point. From here on,
  // the registered dashboard app is frozen to one canonical entry.
  HX.CanonicalManagementApp = HX.ManagementApp;
  Object.defineProperty(HX, "ManagementApp", {
    configurable: false,
    enumerable: true,
    get: function () { return HX.CanonicalManagementApp; },
    set: function () {
      throw new Error("ManagementApp is locked by canonical_ui.js; legacy modules may not replace the main UI.");
    }
  });
})();
