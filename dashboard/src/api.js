(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !SDK.React) return;
  const API = "/api/plugins/hermes-extensions";
  const PREFS = "hermes-extensions.management.prefs.v3";
  const HX = window.__HERMES_EXTENSIONS_UI__ = window.__HERMES_EXTENSIONS_UI__ || {};

  HX.SDK = SDK;
  HX.React = SDK.React;
  HX.h = SDK.React.createElement;
  HX.TABS = ["overview", "agents", "projects", "tasks", "wechat"];
  HX.request = function request(path, init) {
    const options = Object.assign({}, init || {});
    if (options.body && !options.headers) options.headers = { "Content-Type": "application/json" };
    return SDK.fetchJSON(API + path, options);
  };
  HX.errText = function errText(error) {
    if (!error) return "Unknown error";
    const detail = error.detail || (error.response && error.response.detail);
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
    if (error.message) return error.message;
    try { return JSON.stringify(detail || error); } catch (_) { return String(error); }
  };
  HX.fmt = function fmt(value) {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
  };
  HX.loadPrefs = function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(PREFS) || "{}"); } catch (_) { return {}; }
  };
  HX.savePrefs = function savePrefs(value) {
    try { localStorage.setItem(PREFS, JSON.stringify(value)); } catch (_) {}
  };
  HX.same = function same(a, b) {
    try { return JSON.stringify(a == null ? null : a) === JSON.stringify(b == null ? null : b); }
    catch (_) { return a === b; }
  };
})();
