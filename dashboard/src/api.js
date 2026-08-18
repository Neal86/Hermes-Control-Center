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
  HX.TABS = ["overview", "agents", "projects", "tasks"];

  function splitPath(path) {
    const q = String(path || "").indexOf("?");
    return q >= 0 ? { pathname: path.slice(0, q), query: path.slice(q + 1) } : { pathname: path, query: "" };
  }

  function addQuery(path, key, value) {
    const sep = path.indexOf("?") >= 0 ? "&" : "?";
    return path + sep + encodeURIComponent(key) + "=" + encodeURIComponent(value);
  }

  function fixedPluginPath(path, init) {
    const method = String((init && init.method) || "GET").toUpperCase();
    const parts = splitPath(String(path || ""));
    const pathname = parts.pathname;
    const query = parts.query ? "?" + parts.query : "";
    let match;

    match = pathname.match(/^\/agents\/([^/]+)\/action$/);
    if (match) return addQuery("/agent/action" + query, "name", decodeURIComponent(match[1]));

    match = pathname.match(/^\/agents\/([^/]+)\/resources$/);
    if (match) return addQuery("/agent/resources" + query, "agent", decodeURIComponent(match[1]));

    match = pathname.match(/^\/agents\/([^/]+)\/browser$/);
    if (match) return addQuery("/agent/browser" + query, "agent", decodeURIComponent(match[1]));

    match = pathname.match(/^\/agents\/([^/]+)\/wechat\/status$/);
    if (match) return addQuery("/agent/wechat/status" + query, "agent", decodeURIComponent(match[1]));

    match = pathname.match(/^\/agents\/([^/]+)\/wechat\/dry-run$/);
    if (match) return addQuery("/agent/wechat/dry-run" + query, "agent", decodeURIComponent(match[1]));

    match = pathname.match(/^\/agents\/([^/]+)$/);
    if (match && ["GET", "PATCH", "DELETE"].indexOf(method) >= 0) {
      return addQuery("/agent" + query, "name", decodeURIComponent(match[1]));
    }

    match = pathname.match(/^\/providers\/([^/]+)$/);
    if (match && method === "PUT") return addQuery("/provider" + query, "provider", decodeURIComponent(match[1]));

    match = pathname.match(/^\/resources\/(.+)\/bind$/);
    if (match && ["POST", "DELETE"].indexOf(method) >= 0) {
      return addQuery("/resource/bind" + query, "resource_id", decodeURIComponent(match[1]));
    }

    match = pathname.match(/^\/resources\/(.+)\/focus$/);
    if (match && method === "POST") {
      return addQuery("/resource/focus" + query, "resource_id", decodeURIComponent(match[1]));
    }

    return path;
  }

  HX.request = function request(path, init) {
    // WeChat discovery/binding/status lives under the Resources section now.
    // Legacy Control code may still ask for gateway health; satisfy it locally
    // so Control never calls the standalone WeChat API path.
    if (path === "/wechat/health") {
      return Promise.resolve({ status: "moved_to_resources", consecutive_failures: 0, last_error: null, last_success_at: null, updated_at: null });
    }
    const options = Object.assign({}, init || {});
    if (options.body && !options.headers) options.headers = { "Content-Type": "application/json" };
    return SDK.fetchJSON(API + fixedPluginPath(path, options), options);
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
