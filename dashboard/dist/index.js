/* Hermes Control Center dashboard bundle. Single canonical UI entry: canonical_ui.js. Golden baseline: 3dfd2e2d5424eaa037394fa9c9e8f973fe2c911d. */
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

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.request) return;

  const originalRequest = HX.request;

  function isOnline(row) {
    return Boolean(row) && row.online !== false && String(row.status || "").toLowerCase() !== "offline";
  }

  function filterResourcePayload(path, payload) {
    if (!payload || typeof payload !== "object") return payload;
    if (!String(path || "").startsWith("/resources")) return payload;
    if (Array.isArray(payload.items)) {
      payload = Object.assign({}, payload, {
        items: payload.items.filter(isOnline)
      });
    }
    return payload;
  }

  HX.request = async function requestWithOnlineResourcePolicy(path, init) {
    const payload = await originalRequest(path, init);
    return filterResourcePayload(path, payload);
  };

  let resources = [];
  let loading = false;

  function browserLabel(row) {
    const app = String(row.app || "browser").toLowerCase();
    const appName = app === "ixbrowser" ? "iXBrowser" : app === "edge" ? "Edge" : app === "chrome" ? "Chrome" : row.app || "Browser";
    const title = String(row.title || "").trim();
    const profile = String(row.profile || "").trim();
    const detail = [title, profile && profile !== "Default" ? profile : ""].filter(Boolean).join(" · ");
    const readiness = row.attachable ? (row.debug_port ? " · CDP " + row.debug_port : " · ready") : " · not attachable";
    return appName + (detail ? " · " + detail : "") + readiness;
  }

  async function reloadResources() {
    if (loading) return;
    loading = true;
    try {
      const data = await HX.request("/resources?refresh=false");
      resources = ((data && data.items) || []).filter(function (row) {
        return row && row.kind === "browser" && isOnline(row);
      });
    } catch (_) {
      resources = [];
    } finally {
      loading = false;
    }
  }

  function findResourcesHeaderActions() {
    const buttons = Array.from(document.querySelectorAll("button"));
    const launchButton = buttons.find(function (button) {
      return String(button.textContent || "").trim() === "Launch Agent Browser" ||
             String(button.textContent || "").trim() === "Connect / Launch Browser";
    });
    if (!launchButton) return null;
    const actions = launchButton.closest(".hx-actions");
    if (!actions) return null;
    const agentSelect = actions.querySelector("select:not([data-hcc-browser-selector])");
    if (!agentSelect) return null;
    return { actions: actions, launchButton: launchButton, agentSelect: agentSelect };
  }

  function addOption(select, value, text, disabled) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.disabled = Boolean(disabled);
    select.appendChild(option);
  }

  function populateBrowserSelect(select) {
    const previous = select.value;
    while (select.firstChild) select.removeChild(select.firstChild);
    addOption(select, "managed:chrome", "Chrome · new managed browser", false);
    addOption(select, "managed:edge", "Edge · new managed browser", false);
    resources.forEach(function (row) {
      addOption(
        select,
        "resource:" + String(row.id || ""),
        browserLabel(row),
        String(row.app || "").toLowerCase() === "ixbrowser" && !row.attachable
      );
    });
    const values = Array.from(select.options).map(function (option) { return option.value; });
    select.value = values.indexOf(previous) >= 0 ? previous : "managed:chrome";
  }

  function statusNode(actions) {
    let node = actions.querySelector("[data-hcc-browser-selector-status]");
    if (!node) {
      node = document.createElement("span");
      node.className = "hx-muted";
      node.setAttribute("data-hcc-browser-selector-status", "1");
      actions.appendChild(node);
    }
    return node;
  }

  async function performBrowserAction(selection, agent, status) {
    if (!agent) throw new Error("Select an Agent first.");
    if (selection.indexOf("managed:") === 0) {
      const browser = selection.slice("managed:".length);
      status.textContent = "Launching " + (browser === "edge" ? "Edge" : "Chrome") + "…";
      const result = await HX.request("/resources/browser/launch", {
        method: "POST",
        body: JSON.stringify({ agent: agent, browser: browser, start_url: "https://wx.qq.com/" })
      });
      const port = result && result.launch && result.launch.debug_port;
      status.textContent = "Ready" + (port ? " · CDP " + port : "") + " · bound to " + agent;
      return;
    }

    if (selection.indexOf("resource:") === 0) {
      const id = selection.slice("resource:".length);
      const row = resources.find(function (item) { return String(item.id || "") === id; });
      if (!row) throw new Error("Selected browser is no longer online. Refresh Resources.");
      if (row.attachable) {
        status.textContent = "Binding selected browser…";
        await HX.request("/resources/" + encodeURIComponent(id) + "/bind", {
          method: "POST",
          body: JSON.stringify({ agent: agent })
        });
        status.textContent = "Bound " + browserLabel(row) + " to " + agent;
        return;
      }

      const app = String(row.app || "").toLowerCase();
      if (app === "chrome" || app === "edge") {
        status.textContent = "Importing existing " + (app === "edge" ? "Edge" : "Chrome") + " session to CDP…";
        const result = await HX.request("/resources/browser/" + encodeURIComponent(id) + "/import-cdp", {
          method: "POST",
          body: JSON.stringify({ agent: agent, start_url: "https://wx.qq.com/" })
        });
        const port = result && result.launch && result.launch.debug_port;
        status.textContent = "Ready" + (port ? " · CDP " + port : "") + " · bound to " + agent;
        return;
      }

      throw new Error("Selected iXBrowser is running but does not expose a CDP endpoint. Open an iXBrowser profile with remote debugging enabled, then Refresh.");
    }
  }

  function enhanceBrowserSelector() {
    const found = findResourcesHeaderActions();
    if (!found) return;

    let select = found.actions.querySelector("select[data-hcc-browser-selector]");
    if (!select) {
      select = document.createElement("select");
      select.setAttribute("data-hcc-browser-selector", "1");
      select.setAttribute("aria-label", "Browser");
      found.actions.insertBefore(select, found.launchButton);
      populateBrowserSelect(select);
    }

    found.launchButton.textContent = "Connect / Launch Browser";
    found.launchButton.setAttribute("data-hcc-browser-action", "1");

    if (!found.launchButton.__hccBrowserCaptureInstalled) {
      found.launchButton.__hccBrowserCaptureInstalled = true;
      found.launchButton.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const currentSelect = found.actions.querySelector("select[data-hcc-browser-selector]");
        const status = statusNode(found.actions);
        const selection = currentSelect ? currentSelect.value : "managed:chrome";
        const agent = found.agentSelect.value;
        found.launchButton.disabled = true;
        performBrowserAction(selection, agent, status)
          .then(function () {
            return reloadResources();
          })
          .then(function () {
            if (currentSelect) populateBrowserSelect(currentSelect);
            const refresh = Array.from(document.querySelectorAll("button")).find(function (button) {
              return String(button.textContent || "").trim() === "Refresh";
            });
            if (refresh && !refresh.disabled) refresh.click();
          })
          .catch(function (error) {
            status.textContent = HX.errText ? HX.errText(error) : String(error);
          })
          .finally(function () {
            found.launchButton.disabled = false;
          });
      }, true);
    }
  }

  const observer = new MutationObserver(function () {
    const bodyText = String(document.body && document.body.textContent || "");
    if (bodyText.indexOf("Resources") >= 0) enhanceBrowserSelector();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  reloadResources().then(enhanceBrowserSelector);
  window.setInterval(function () {
    const found = findResourcesHeaderActions();
    if (found) {
      reloadResources().then(function () {
        const select = found.actions.querySelector("select[data-hcc-browser-selector]");
        if (select) populateBrowserSelect(select);
      });
    }
  }, 5000);
})();

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.React) return;
  const React = HX.React;
  const h = HX.h;
  const { useEffect, useRef } = React;
  const DIALOG_STACK = [];
  let DIALOG_ID = 0;

  HX.Card = function Card(p) { return h("section", { className: "hx-card " + (p.className || "") }, p.children); };
  HX.Pill = function Pill(p) { return h("span", { className: "hx-pill " + (p.kind || "") }, p.children); };
  HX.Stat = function Stat(p) { return h(HX.Card, { className: "hx-stat" }, h("div", { className: "hx-stat-value" }, String(p.value == null ? 0 : p.value)), h("div", { className: "hx-muted" }, p.label)); };
  HX.Field = function Field(label, child, help) { return h("label", null, h("span", null, label), child, help ? h("small", null, help) : null); };
  HX.Empty = function Empty(p) { return h("div", { className: "hx-empty" }, p.children); };
  HX.LoadingBlock = function LoadingBlock(p) { return h("div", { className: "hx-loading" }, h("span", { className: "hx-spinner" }), p.children || "Loading…"); };
  HX.SearchBox = function SearchBox(p) { return h("input", { className: "hx-search", type: "search", placeholder: p.placeholder || "Search…", value: p.value, onChange: function (e) { p.onChange(e.target.value); } }); };
  HX.Tabs = function Tabs(p) {
    return h("div", { className: "hx-tabs", role: "tablist", "aria-label": "Management sections" }, HX.TABS.map(function (name) {
      const label = name === "wechat" ? "WeChat" : name.charAt(0).toUpperCase() + name.slice(1);
      return h("button", { key: name, role: "tab", type: "button", "aria-selected": p.value === name, className: "hx-tab " + (p.value === name ? "active" : ""), onClick: function () { p.onChange(name); } }, label);
    }));
  };

  function focusables(root) {
    if (!root) return [];
    return Array.from(root.querySelectorAll('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')).filter(function (el) {
      return el.offsetParent !== null || el === document.activeElement;
    });
  }

  HX.Dialog = function Dialog(p) {
    const boxRef = useRef(null);
    const previousFocus = useRef(null);
    const closeRef = useRef(p.onRequestClose);
    const lockedRef = useRef(Boolean(p.locked));
    const idRef = useRef(null);
    closeRef.current = p.onRequestClose;
    lockedRef.current = Boolean(p.locked);
    if (idRef.current == null) idRef.current = ++DIALOG_ID;

    useEffect(function () {
      if (!p.open) return undefined;
      const id = idRef.current;
      DIALOG_STACK.push(id);
      previousFocus.current = document.activeElement;
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      const timer = setTimeout(function () {
        if (DIALOG_STACK[DIALOG_STACK.length - 1] !== id) return;
        const items = focusables(boxRef.current);
        if (items.length) items[0].focus();
        else if (boxRef.current) boxRef.current.focus();
      }, 0);

      function onKey(e) {
        if (DIALOG_STACK[DIALOG_STACK.length - 1] !== id) return;
        if (e.key === "Escape" && !lockedRef.current) {
          e.preventDefault();
          if (typeof closeRef.current === "function") closeRef.current();
          return;
        }
        if (e.key !== "Tab") return;
        const items = focusables(boxRef.current);
        if (!items.length) { e.preventDefault(); return; }
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }

      document.addEventListener("keydown", onKey);
      return function () {
        clearTimeout(timer);
        document.removeEventListener("keydown", onKey);
        const index = DIALOG_STACK.lastIndexOf(id);
        if (index >= 0) DIALOG_STACK.splice(index, 1);
        document.body.style.overflow = previousOverflow;
        const target = previousFocus.current;
        if (target && typeof target.focus === "function" && document.contains(target)) {
          setTimeout(function () { try { target.focus(); } catch (_) {} }, 0);
        }
      };
    }, [p.open]);

    if (!p.open) return null;
    return h("div", { className: "hx-dialog-backdrop", role: "presentation", onMouseDown: function (e) { if (e.target === e.currentTarget && !lockedRef.current && typeof closeRef.current === "function") closeRef.current(); } },
      h("div", { ref: boxRef, className: "hx-dialog", role: "dialog", "aria-modal": "true", "aria-label": p.title, tabIndex: -1 },
        h("div", { className: "hx-dialog-head" }, h("div", null, h("h2", null, p.title), p.subtitle ? h("div", { className: "hx-muted" }, p.subtitle) : null), h("button", { type: "button", className: "hx-icon-button", disabled: Boolean(p.locked), onClick: p.onRequestClose, "aria-label": "Close" }, "×")),
        h("div", { className: "hx-dialog-body" }, p.children)
      )
    );
  };

  HX.ConfirmDialog = function ConfirmDialog(p) {
    const spec = p.spec;
    if (!spec) return null;
    return h(HX.Dialog, { open: true, title: spec.title || "Confirm action", subtitle: spec.subtitle || "", locked: Boolean(spec.locked), onRequestClose: p.onCancel },
      h("div", { className: "hx-confirm" },
        h("p", null, spec.message || "Are you sure?"),
        spec.detail ? h("div", { className: "hx-confirm-detail" }, spec.detail) : null,
        h("div", { className: "hx-actions hx-confirm-actions" },
          h("button", { type: "button", className: "hx-button secondary", onClick: p.onCancel, disabled: Boolean(spec.locked) }, spec.cancelLabel || "Cancel"),
          h("button", { type: "button", className: "hx-button " + (spec.destructive ? "danger" : ""), onClick: p.onConfirm, disabled: Boolean(spec.locked) }, spec.confirmLabel || "Confirm")
        )
      )
    );
  };
})();

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.React) return;
  const React = HX.React;
  const h = HX.h;
  const { useCallback, useEffect, useMemo, useState } = React;
  const { request, errText, fmt, loadPrefs, savePrefs, same, Card, Pill, Stat, Field, Empty, LoadingBlock, Dialog, ConfirmDialog, Tabs, SearchBox } = HX;

  if (!document.getElementById("hx-agent-device-styles")) {
    const style = document.createElement("style");
    style.id = "hx-agent-device-styles";
    style.textContent = ".hx-dialog{background:#061a17!important;opacity:1}.hx-dialog-head,.hx-dialog-body{background:#061a17!important}.hx-page select,.hx-dialog select{color-scheme:dark;background-color:#000!important;color:#fff!important}.hx-page select option,.hx-page select optgroup,.hx-dialog select option,.hx-dialog select optgroup{background:#000!important;color:#fff!important}.hx-agent-device{grid-column:2;align-self:start;border:1px solid var(--border,#29433f);border-radius:14px;padding:16px;background:#102b27;min-width:0}.hx-agent-device .hx-section-head{margin-bottom:12px}.hx-device-actions{display:grid;gap:7px;margin-bottom:12px}.hx-device-tabs{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--border,#29433f);border-radius:11px;padding:4px;margin-bottom:12px}.hx-device-tab{border:0;background:transparent;color:inherit;padding:10px;border-radius:8px;font:inherit;font-weight:700;cursor:pointer}.hx-device-tab.active{background:#1b3934;box-shadow:inset 0 0 0 1px var(--border,#35534e)}.hx-device-list{display:grid;gap:8px;max-height:260px;overflow:auto;padding-right:2px}.hx-device-row{display:grid;grid-template-columns:minmax(0,1fr) 76px;align-items:stretch;border:1px solid var(--border,#29433f);border-radius:11px;overflow:hidden;min-width:0}.hx-device-row.selected{border-color:var(--text,#f2d8bd)}.hx-device-select{display:grid;grid-template-columns:12px minmax(0,1fr) 24px;gap:10px;align-items:center;text-align:left;border:0;background:transparent;color:inherit;padding:12px;cursor:pointer;font:inherit;min-width:0;overflow:hidden}.hx-device-dot{width:10px;height:10px;border-radius:50%;background:var(--text,#f2d8bd)}.hx-device-copy,.hx-device-title,.hx-device-detail{display:block;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis}.hx-device-title{font-weight:700;white-space:nowrap}.hx-device-detail{font-size:.86em;opacity:.75;white-space:nowrap}.hx-device-check{width:22px;height:22px;border:1px solid var(--border,#35534e);border-radius:50%;display:grid;place-items:center}.hx-device-row.selected .hx-device-check{background:var(--text,#f2d8bd);color:#13231f}.hx-device-open{width:66px;align-self:center;justify-self:center;padding:7px 8px;border:1px solid var(--border,#35534e);border-radius:8px;background:#102b27;color:inherit;font:inherit;font-weight:700;cursor:pointer}.hx-device-open:hover{background:#1b3934}.hx-device-summary{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;border-top:1px solid var(--border,#29433f);margin-top:12px;padding-top:12px}.hx-device-summary strong{max-width:55%;text-align:right;overflow-wrap:anywhere}.hx-device-empty{padding:20px;text-align:center;opacity:.7}.hx-agent-device button:disabled{opacity:.5;cursor:not-allowed}@media(max-width:900px){.hx-agent-device{grid-column:1/-1}}";
    document.head.appendChild(style);
  }

  const DEFAULT_AGENT = { name: "", description: "", clone_mode: "blank", clone_from: "", workspace: "", model: "", provider: "", soul: "", no_skills: false };
  const DEFAULT_PROJECT = { name: "", profile: "default", slug: "", folders: "", primary: "", description: "", icon: "", color: "", board: "", agent: "", use: true };
  const DEFAULT_TASK = { type: "cron", name: "", prompt: "", schedule: "", profile: "default", priority: 50, deliver: "local" };

  function agentEditable(a) {
    if (!a) return null;
    return { name: a.edit_name == null ? a.name : a.edit_name, description: a.description || "", workspace: a.workspace || "", provider: a.provider || "", model: a.model || "", soul: a.soul || "" };
  }
  function projectEditable(p) {
    if (!p) return null;
    return { name: p.name || "", primary_path: p.primary_path || "", board: p.board || "" };
  }
  function taskEditable(t) {
    if (!t) return null;
    return { name: t.name || "", prompt: t.prompt || t.body || "", profile: t.profile || "", schedule: t.type === "cron" ? (t.schedule || "") : "", priority: t.type === "kanban" ? Number(t.priority == null ? 50 : t.priority) : null };
  }

  function providerValue(provider) {
    if (!provider) return "";
    return String(provider.runtime_provider_id || provider.id || "").trim();
  }

  function mergeProviderData(primary, fallback) {
    const sources = [fallback, primary].filter(Boolean);
    if (!sources.length) return null;
    const items = [];
    const positions = {};
    sources.forEach(function (source) {
      ((source && source.items) || []).forEach(function (provider) {
        const value = providerValue(provider);
        if (!value) return;
        const next = Object.assign({}, provider);
        if (positions[value] == null) {
          positions[value] = items.length;
          items.push(next);
        } else {
          items[positions[value]] = Object.assign({}, items[positions[value]], next);
        }
      });
    });
    return { items: items };
  }

  function ManagementApp() {
    const prefs = useMemo(loadPrefs, []);
    const [tab, setTab] = useState(HX.TABS.indexOf(prefs.tab) >= 0 ? prefs.tab : "overview");
    const [management, setManagement] = useState(null);
    const [tasks, setTasks] = useState(null);
    const [upcoming, setUpcoming] = useState([]);
    const [wechatHealth, setWechatHealth] = useState(null);
    const [wechatStatus, setWechatStatus] = useState(null);
    const [wechatChats, setWechatChats] = useState([]);
    const [wechatUnread, setWechatUnread] = useState([]);
    const [wechatErrors, setWechatErrors] = useState([]);
    const [coreLoading, setCoreLoading] = useState(true);
    const [tasksLoading, setTasksLoading] = useState(false);
    const [healthLoading, setHealthLoading] = useState(false);
    const [wechatLoading, setWechatLoading] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [busy, setBusy] = useState("");
    const [confirmSpec, setConfirmSpec] = useState(null);

    const [agentModal, setAgentModal] = useState(false);
    const [projectModal, setProjectModal] = useState(false);
    const [taskModal, setTaskModal] = useState(false);
    const [agentDetail, setAgentDetail] = useState(null);
    const [agentResources, setAgentResources] = useState([]);
    const [availableResources, setAvailableResources] = useState([]);
    const [agentResourcesLoading, setAgentResourcesLoading] = useState(false);
    const [agentProviderData, setAgentProviderData] = useState(null);
    const [agentDeviceTab, setAgentDeviceTab] = useState("wechat");
    const [projectDetail, setProjectDetail] = useState(null);
    const [taskDetail, setTaskDetail] = useState(null);
    const [agentOriginal, setAgentOriginal] = useState(null);
    const [projectOriginal, setProjectOriginal] = useState(null);
    const [taskOriginal, setTaskOriginal] = useState(null);
    const [history, setHistory] = useState([]);
    const [historyLoading, setHistoryLoading] = useState(false);

    const [agentSearch, setAgentSearch] = useState("");
    const [projectSearch, setProjectSearch] = useState("");
    const [projectFilter, setProjectFilter] = useState("active");
    const [taskSearch, setTaskSearch] = useState("");
    const [taskTypeFilter, setTaskTypeFilter] = useState("all");
    const [taskProfile, setTaskProfile] = useState(prefs.taskProfile || "");
    const [taskRange, setTaskRange] = useState(Number(prefs.taskRange) || 168);
    const [includeCompleted, setIncludeCompleted] = useState(Boolean(prefs.includeCompleted));
    const [projectFolderInput, setProjectFolderInput] = useState("");
    const [wechatDryRun, setWechatDryRun] = useState({ chat: "", text: "Test message — dry run only" });
    const [agentForm, setAgentForm] = useState(Object.assign({}, DEFAULT_AGENT));
    const [projectForm, setProjectForm] = useState(Object.assign({}, DEFAULT_PROJECT));
    const [taskForm, setTaskForm] = useState(Object.assign({}, DEFAULT_TASK));

    useEffect(function () {
      savePrefs({ tab: tab, taskProfile: taskProfile, taskRange: taskRange, includeCompleted: includeCompleted });
    }, [tab, taskProfile, taskRange, includeCompleted]);

    const agents = (management && management.agents) || [];
    const projects = (management && management.projects) || [];
    const projectSupported = Boolean(management && management.project_supported);
    const taskProfiles = (tasks && tasks.profiles) || [];
    const agentNames = agents.map(function (a) { return a.name; });
    const taskRows = taskProfiles.flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); });
    const anyDialog = Boolean(agentModal || projectModal || taskModal || agentDetail || projectDetail || taskDetail || confirmSpec);

    const agentDirty = Boolean(agentDetail && !same(agentEditable(agentDetail), agentOriginal));
    const projectDirty = Boolean(projectDetail && !same(projectEditable(projectDetail), projectOriginal));
    const taskDirty = Boolean(taskDetail && !same(taskEditable(taskDetail), taskOriginal));
    const agentCreateDirty = !same(agentForm, DEFAULT_AGENT);
    const projectCreateDirty = !same(projectForm, DEFAULT_PROJECT);
    const taskCreateDirty = !same(taskForm, DEFAULT_TASK);

    const loadHealth = useCallback(async function (quiet) {
      if (!quiet) setHealthLoading(true);
      try {
        const health = await request("/wechat/health");
        setWechatHealth(health);
        return health;
      } catch (e) {
        if (!quiet) setError(errText(e));
        return null;
      } finally {
        if (!quiet) setHealthLoading(false);
      }
    }, []);

    const loadCore = useCallback(async function (quiet) {
      if (!quiet) setCoreLoading(true);
      try {
        const results = await Promise.allSettled([request("/management/overview"), request("/wechat/health")]);
        const failures = [];
        if (results[0].status === "fulfilled") setManagement(results[0].value); else failures.push("Management: " + errText(results[0].reason));
        if (results[1].status === "fulfilled") setWechatHealth(results[1].value); else failures.push("WeChat health: " + errText(results[1].reason));
        if (failures.length && !quiet) setError(failures.join(" · "));
      } finally {
        if (!quiet) setCoreLoading(false);
      }
    }, []);

    const loadTasks = useCallback(async function (quiet) {
      if (!quiet) setTasksLoading(true);
      try {
        const q = new URLSearchParams();
        if (taskProfile) q.set("profile", taskProfile);
        if (includeCompleted) q.set("include_completed", "true");
        const uq = new URLSearchParams({ hours: String(taskRange) });
        if (taskProfile) uq.set("profile", taskProfile);
        const results = await Promise.allSettled([
          request("/overview" + (q.toString() ? "?" + q.toString() : "")),
          request("/upcoming?" + uq.toString())
        ]);
        const failures = [];
        if (results[0].status === "fulfilled") setTasks(results[0].value); else failures.push("Task list: " + errText(results[0].reason));
        if (results[1].status === "fulfilled") setUpcoming((results[1].value && results[1].value.items) || []); else failures.push("Upcoming: " + errText(results[1].reason));
        if (failures.length && !quiet) setError(failures.join(" · "));
        return results[0].status === "fulfilled" ? results[0].value : null;
      } finally {
        if (!quiet) setTasksLoading(false);
      }
    }, [taskProfile, taskRange, includeCompleted]);

    const checkWeChatDesktop = useCallback(async function () {
      setWechatLoading(true);
      setWechatErrors([]);
      setError("");
      const failures = [];
      try {
        try { setWechatHealth(await request("/wechat/health")); } catch (e) { failures.push("health: " + errText(e)); }
        try { setWechatStatus(await request("/wechat/status")); } catch (e) { failures.push("desktop: " + errText(e)); }
        try {
          const data = await request("/wechat/chats?limit=200");
          const items = (data && data.items) || [];
          setWechatChats(items.slice(0, 40));
          setWechatUnread(items.filter(function (row) { return Boolean(row.unread); }).slice(0, 40));
        } catch (e) {
          failures.push("chat list: " + errText(e));
        }
        setWechatErrors(failures);
      } finally {
        setWechatLoading(false);
      }
    }, []);

    const refreshCurrent = useCallback(async function () {
      setError("");
      if (tab === "tasks") {
        await Promise.all([loadCore(false), loadTasks(false)]);
        return;
      }
      if (tab === "wechat") {
        await loadHealth(false);
        return;
      }
      await loadCore(false);
    }, [tab, loadCore, loadTasks, loadHealth]);

    useEffect(function () { loadCore(false); }, [loadCore]);
    useEffect(function () { if (tab === "tasks") loadTasks(false); }, [tab, loadTasks]);
    useEffect(function () { if (tab === "wechat") loadHealth(false); }, [tab, loadHealth]);
    useEffect(function () {
      const ms = tab === "wechat" ? 15000 : 30000;
      const timer = setInterval(function () {
        if (document.visibilityState !== "visible" || busy || anyDialog) return;
        if (tab === "tasks") {
          loadCore(true);
          loadTasks(true);
        } else if (tab === "wechat") {
          loadHealth(true);
        } else {
          loadCore(true);
        }
      }, ms);
      return function () { clearInterval(timer); };
    }, [tab, busy, anyDialog, loadCore, loadTasks, loadHealth]);

    function flattenTaskOverview(data) {
      return ((data && data.profiles) || []).flatMap(function (p) { return (p.cron || []).concat(p.kanban || []); });
    }
    function busyIs(key) { return busy === key; }
    function askConfirm(spec, action) { setConfirmSpec(Object.assign({}, spec, { action: action, locked: false })); }
    async function confirmNow() {
      if (!confirmSpec || confirmSpec.locked) return;
      const action = confirmSpec.action;
      setConfirmSpec(Object.assign({}, confirmSpec, { locked: true }));
      try { await action(); } finally { setConfirmSpec(null); }
    }
    function guardedClose(dirty, close) {
      if (!dirty) { close(); return; }
      askConfirm({ title: "Discard unsaved changes?", message: "Your edits have not been saved.", confirmLabel: "Discard changes", destructive: true }, close);
    }

    async function doAction(key, fn, success, options) {
      if (busy) return { ok: false };
      const opts = options || {};
      setBusy(key);
      setError("");
      setNotice("");
      try {
        const result = await fn();
        if (result && result.ok === false) throw new Error(result.warning || result.message || "Hermes action could not be verified");
        if (success) setNotice(typeof success === "function" ? success(result) : success);
        if (opts.refreshCore !== false) await loadCore(true);
        if (opts.refreshTasks) await loadTasks(true);
        if (opts.after) await opts.after(result);
        return { ok: true, result: result };
      } catch (e) {
        setError(errText(e));
        return { ok: false, error: e };
      } finally {
        setBusy("");
      }
    }

    async function createAgent(e) {
      e.preventDefault();
      const payload = Object.assign({}, agentForm);
      ["clone_from", "workspace", "model", "provider", "soul"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const out = await doAction("agent-create", function () { return request("/agents", { method: "POST", body: JSON.stringify(payload) }); }, "Agent created.");
      if (!out.ok) return;
      setAgentModal(false);
      setAgentForm(Object.assign({}, DEFAULT_AGENT));
      if (out.result && out.result.agent) {
        setAgentDetail(out.result.agent);
        setAgentOriginal(agentEditable(out.result.agent));
      }
    }

    async function openAgent(name) {
      if (busy) return;
      setBusy("agent-open");
      setError("");
      setAgentResourcesLoading(true);
      try {
        const results = await Promise.allSettled([
          request("/agents/" + encodeURIComponent(name)),
          request("/resources?refresh=true"),
          request("/providers?profile=" + encodeURIComponent(name)),
          name === "default" ? Promise.resolve(null) : request("/providers?profile=default")
        ]);
        if (results[0].status !== "fulfilled") throw results[0].reason;
        const data = results[0].value;
        setAgentDetail(data);
        setAgentOriginal(agentEditable(data));
        const profileProviders = results[2].status === "fulfilled" ? results[2].value : null;
        const defaultProviders = results[3].status === "fulfilled" ? results[3].value : null;
        setAgentProviderData(mergeProviderData(profileProviders, defaultProviders));
        if (results[1].status === "fulfilled") {
          const resources = (results[1].value && results[1].value.items) || [];
          setAvailableResources(resources);
          setAgentResources(resources.filter(function (row) { return row.assigned_agent === name; }));
        } else {
          setAvailableResources([]);
          setAgentResources([]);
          setError("Agent loaded, but bound resources could not be loaded: " + errText(results[1].reason));
        }
        if (!profileProviders && !defaultProviders) {
          setError("Agent loaded, but Provider/Model choices could not be loaded: " + errText(results[2].reason));
        }
        setTab("agents");
      } catch (e) {
        setError(errText(e));
      } finally {
        setAgentResourcesLoading(false);
        setBusy("");
      }
    }

    function unbindAgentResource(resource) {
      if (!agentDetail || !resource) return;
      const kind = resource.kind === "wechat" ? "WeChat" : "browser";
      askConfirm({
        title: "Unbind " + kind + "?",
        message: "This Agent will immediately lose access to the bound " + kind + ".",
        detail: resource.title || resource.app || resource.id,
        confirmLabel: "Unbind",
        destructive: true
      }, async function () {
        const out = await doAction("resource-unbind:" + resource.id, function () {
          return request("/resources/" + encodeURIComponent(resource.id) + "/bind", { method: "DELETE" });
        }, kind + " unbound.", { refreshCore: false });
        if (out.ok) {
          setAgentResources(function (rows) { return rows.filter(function (row) { return row.id !== resource.id; }); });
          setAvailableResources(function (rows) { return rows.map(function (row) { return row.id === resource.id ? Object.assign({}, row, { assigned_agent: null }) : row; }); });
        }
      });
    }

    async function bindAgentResource(kind, resourceId) {
      if (!agentDetail || !resourceId) return;
      const resource = availableResources.find(function (row) { return row.id === resourceId; });
      if (!resource) return;
      const out = await doAction("resource-bind:" + kind, function () {
        return request("/resources/" + encodeURIComponent(resource.id) + "/bind", {
          method: "POST",
          body: JSON.stringify({ agent: agentDetail.name })
        });
      }, (kind === "wechat" ? "WeChat" : "Browser") + " linked.", { refreshCore: false });
      if (!out.ok) return;
      setAvailableResources(function (rows) { return rows.map(function (row) {
        if (row.kind === kind && row.assigned_agent === agentDetail.name) return Object.assign({}, row, { assigned_agent: null });
        if (row.id === resource.id) return Object.assign({}, row, { assigned_agent: agentDetail.name });
        return row;
      }); });
      setAgentResources(function (rows) {
        return rows.filter(function (row) { return row.kind !== kind; }).concat([Object.assign({}, resource, { assigned_agent: agentDetail.name })]);
      });
    }

    function selectAgentResource(resource) {
      if (!resource) return;
      if (resource.assigned_agent && resource.assigned_agent !== agentDetail.name) {
        askConfirm({
          title: "Transfer " + (resource.kind === "wechat" ? "WeChat" : "Browser") + " window?",
          message: "This window is currently assigned to Agent " + resource.assigned_agent + ".",
          detail: "Transfer it to Agent " + agentDetail.name + "? The previous Agent will lose access.",
          confirmLabel: "Transfer window",
          destructive: true
        }, function () { return bindAgentResource(resource.kind, resource.id); });
        return;
      }
      bindAgentResource(resource.kind, resource.id);
    }

    async function refreshAgentDevices() {
      if (!agentDetail || busy) return;
      setAgentResourcesLoading(true);
      try {
        const result = await request("/resources?refresh=true");
        const resources = (result && result.items) || [];
        setAvailableResources(resources);
        setAgentResources(resources.filter(function (row) { return row.assigned_agent === agentDetail.name; }));
      } catch (e) { setError(errText(e)); }
      finally { setAgentResourcesLoading(false); }
    }

    async function launchAgentBrowser() {
      if (!agentDetail || busy || agentDirty) return;
      const out = await doAction("resource-launch:browser", function () {
        return request("/resources/browser/launch", {
          method: "POST",
          body: JSON.stringify({ agent: agentDetail.name, browser: "chrome", start_url: "https://www.google.com/" })
        });
      }, "Agent Browser launched and linked.", { refreshCore: false });
      if (!out.ok) return;
      await refreshAgentDevices();
    }

    async function focusAgentDevice(resource) {
      if (!resource || busy) return;
      const out = await doAction("resource-focus:" + resource.id, function () {
        return request("/resources/" + encodeURIComponent(resource.id) + "/focus", { method: "POST" });
      }, (resource.kind === "wechat" ? "WeChat" : "Browser") + " opened.", { refreshCore: false });
      return out;
    }

    function AgentResourcePicker() {
      const online = availableResources.filter(function (row) { return row.online; });
      const rows = online.filter(function (row) { return row.kind === agentDeviceTab; });
      const current = agentResources.find(function (row) { return row.kind === agentDeviceTab; });
      const wechatCount = online.filter(function (row) { return row.kind === "wechat"; }).length;
      return h("section", { className: "hx-agent-device" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h3", null, "Computer use"), h("div", { className: "hx-muted" }, "Choose the local window this Agent may operate.")), h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentResourcesLoading, onClick: refreshAgentDevices }, agentResourcesLoading ? "Scanning…" : "Rescan")),
        h("div", { className: "hx-device-tabs", role: "tablist" },
          h("button", { type: "button", className: "hx-device-tab" + (agentDeviceTab === "browser" ? " active" : ""), onClick: function () { setAgentDeviceTab("browser"); } }, "Browser"),
          h("button", { type: "button", className: "hx-device-tab" + (agentDeviceTab === "wechat" ? " active" : ""), onClick: function () { setAgentDeviceTab("wechat"); } }, "Local WeChat · " + wechatCount)
        ),
        agentDeviceTab === "browser" ? h("div", { className: "hx-device-actions" },
          h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentResourcesLoading || agentDirty, onClick: launchAgentBrowser }, busyIs("resource-launch:browser") ? "Launching…" : "Launch / reconnect Agent Browser"),
          h("span", { className: "hx-muted" }, "Ordinary Chrome windows need a dedicated controllable copy.")) : null,
        agentResourcesLoading ? h(LoadingBlock, null, "Loading resources…") : h("div", { className: "hx-device-list" }, rows.length ? rows.map(function (row) {
          const selected = Boolean(current && current.id === row.id);
          const title = row.title || row.app || (row.kind === "wechat" ? "WeChat" : "Browser");
          const owner = row.assigned_agent && row.assigned_agent !== agentDetail.name ? " · assigned to Agent " + row.assigned_agent : "";
          const detail = (row.kind === "wechat" ? "PID " + row.pid + " · local desktop window" : (row.app || "browser") + " · " + (row.profile || "Default") + (row.debug_port ? " · controllable · CDP " + row.debug_port : " · visible only · use Launch / reconnect above")) + owner;
          return h("div", { className: "hx-device-row" + (selected ? " selected" : ""), key: row.id },
            h("button", { className: "hx-device-select", type: "button", disabled: Boolean(busy) || agentDirty || (row.kind === "browser" && !row.attachable), onClick: function () { selectAgentResource(row); } }, h("span", { className: "hx-device-dot" }), h("span", { className: "hx-device-copy" }, h("span", { className: "hx-device-title" }, title), h("span", { className: "hx-device-detail" }, detail)), h("span", { className: "hx-device-check" }, selected ? "✓" : "")),
            h("button", { className: "hx-device-open", type: "button", disabled: busyIs("resource-focus:" + row.id), onClick: function () { focusAgentDevice(row); }, "aria-label": "Open " + title }, busyIs("resource-focus:" + row.id) ? "Opening…" : "Open")
          );
        }) : h("div", { className: "hx-device-empty" }, "No available " + (agentDeviceTab === "wechat" ? "WeChat" : "browser") + " windows.")),
        h("div", { className: "hx-device-summary" }, h("span", null, "Assigned to this Agent"), h("strong", null, current ? (current.title || current.app || (agentDeviceTab === "wechat" ? "WeChat" : "Browser")) : "None"))
      );
    }

    async function saveAgent(e) {
      e.preventDefault();
      if (!agentDetail) return;
      const oldName = agentDetail.name;
      const payload = agentEditable(agentDetail);
      const out = await doAction("agent-save", function () {
        return request("/agents/" + encodeURIComponent(oldName), { method: "PATCH", body: JSON.stringify(payload) });
      }, "Agent changes saved.", { refreshCore: true });
      if (!out.ok) return;
      const nextName = out.result && out.result.agent ? out.result.agent.name : payload.name;
      await openAgent(nextName);
    }

    function agentAction(agent, action, value, label) {
      return doAction("agent:" + agent.name + ":" + action, function () {
        return request("/agents/" + encodeURIComponent(agent.name) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null }) });
      }, label || "Agent action completed.", {
        refreshCore: true,
        after: function (result) {
          if (result && result.agent && agentDetail && agentDetail.name === agent.name && !agentDirty) {
            const next = Object.assign({}, agentDetail, result.agent);
            setAgentDetail(next);
            setAgentOriginal(agentEditable(next));
          }
        }
      });
    }

    function restartAgent(agent) {
      askConfirm({ title: "Restart Gateway?", message: "Active sessions for " + agent.name + " may be interrupted.", confirmLabel: "Restart Gateway" }, function () {
        return agentAction(agent, "gateway_restart", null, "Gateway restarted.");
      });
    }

    function deleteAgent(agent) {
      askConfirm({ title: "Delete Agent?", message: "This permanently deletes the Hermes Profile and its profile-scoped state.", detail: agent.name, confirmLabel: "Delete Agent", destructive: true }, async function () {
        const out = await doAction("agent-delete", function () { return request("/agents/" + encodeURIComponent(agent.name), { method: "DELETE" }); }, "Agent deleted.");
        if (out.ok) { setAgentDetail(null); setAgentOriginal(null); }
      });
    }

    async function createProject(e) {
      e.preventDefault();
      if (!projectSupported) return;
      const payload = Object.assign({}, projectForm);
      payload.folders = String(payload.folders || "").split(/[,\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
      ["slug", "primary", "description", "icon", "color", "board", "agent"].forEach(function (key) { if (!payload[key]) delete payload[key]; });
      const out = await doAction("project-create", function () { return request("/projects", { method: "POST", body: JSON.stringify(payload) }); }, "Project created.");
      if (!out.ok) return;
      setProjectModal(false);
      setProjectForm(Object.assign({}, DEFAULT_PROJECT));
      if (out.result && out.result.project) {
        setProjectDetail(out.result.project);
        setProjectOriginal(projectEditable(out.result.project));
      }
    }

    async function openProject(project) {
      if (!projectSupported || busy) return;
      setBusy("project-open");
      setError("");
      try {
        const data = await request("/projects/" + encodeURIComponent(project.slug) + "?profile=" + encodeURIComponent(project.profile || "default"));
        setProjectDetail(data);
        setProjectOriginal(projectEditable(data));
        setTab("projects");
      } catch (e) {
        setError(errText(e));
      } finally {
        setBusy("");
      }
    }

    async function saveProject(e) {
      e.preventDefault();
      if (!projectDetail) return;
      const payload = { profile: projectDetail.profile || "default", name: projectDetail.name || "", primary: projectDetail.primary_path || "", board: projectDetail.board || "" };
      const out = await doAction("project-save", function () {
        return request("/projects/" + encodeURIComponent(projectDetail.slug), { method: "PATCH", body: JSON.stringify(payload) });
      }, "Project changes saved.", { refreshCore: true });
      if (out.ok) await openProject(projectDetail);
    }

    function projectAction(project, action, value, label) {
      return doAction("project:" + project.slug + ":" + action, function () {
        return request("/projects/" + encodeURIComponent(project.slug) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null, profile: project.profile || "default" }) });
      }, label || "Project action completed.", { refreshCore: true, after: function () { return openProject(project); } });
    }

    async function createTask(e) {
      e.preventDefault();
      const payload = Object.assign({}, taskForm);
      if (payload.type === "kanban") { delete payload.schedule; delete payload.deliver; } else delete payload.priority;
      const out = await doAction("task-create", function () { return request("/tasks", { method: "POST", body: JSON.stringify(payload) }); }, "Task created.", { refreshCore: true, refreshTasks: true });
      if (!out.ok) return;
      setTaskModal(false);
      setTaskForm(Object.assign({}, DEFAULT_TASK));
    }

    async function openTask(task) {
      if (busy) return;
      setHistory([]);
      setHistoryLoading(true);
      setError("");
      setTab("tasks");
      try {
        let actual = Object.assign({}, task);
        const hasEditable = Object.prototype.hasOwnProperty.call(actual, "prompt") || Object.prototype.hasOwnProperty.call(actual, "body") || Object.prototype.hasOwnProperty.call(actual, "priority");
        if (!hasEditable && task && task.type && task.id) {
          const q = new URLSearchParams({ include_completed: "true" });
          if (task.profile) q.set("profile", task.profile);
          const detailOverview = await request("/overview?" + q.toString());
          const candidate = flattenTaskOverview(detailOverview).find(function (row) {
            return row.id === task.id && row.type === task.type && (!task.profile || row.profile === task.profile);
          });
          if (candidate) actual = Object.assign({}, candidate);
        }
        setTaskDetail(actual);
        setTaskOriginal(taskEditable(actual));
        const hq = actual.profile ? "?profile=" + encodeURIComponent(actual.profile) + "&limit=40" : "?limit=40";
        const data = await request("/tasks/" + encodeURIComponent(actual.type) + "/" + encodeURIComponent(actual.id) + "/history" + hq);
        setHistory(data.items || []);
      } catch (e) {
        setError(errText(e));
        setTaskDetail(Object.assign({}, task));
        setTaskOriginal(taskEditable(task));
      } finally {
        setHistoryLoading(false);
      }
    }

    async function saveTask(e) {
      e.preventDefault();
      if (!taskDetail) return;
      const t = taskDetail;
      const payload = { name: t.name || "", prompt: t.prompt || t.body || "", profile: t.profile || "" };
      if (t.type === "cron") payload.schedule = t.schedule || ""; else payload.priority = Number(t.priority == null ? 50 : t.priority);
      const out = await doAction("task-save", function () {
        return request("/tasks/" + encodeURIComponent(t.type) + "/" + encodeURIComponent(t.id), { method: "PATCH", body: JSON.stringify(payload) });
      }, "Task changes saved.", { refreshCore: true, refreshTasks: true });
      if (out.ok) {
        const next = Object.assign({}, t, payload);
        setTaskDetail(next);
        setTaskOriginal(taskEditable(next));
      }
    }

    function taskAction(task, action, value, label) {
      const execute = async function () {
        const out = await doAction("task:" + task.id + ":" + action, function () {
          return request("/tasks/" + encodeURIComponent(task.type) + "/" + encodeURIComponent(task.id) + "/action", { method: "POST", body: JSON.stringify({ action: action, value: value || null, profile: task.profile || null }) });
        }, label || "Task action completed.", { refreshCore: true, refreshTasks: true });
        if (!out.ok) return;
        if (action === "remove" || action === "archive") {
          setTaskDetail(null);
          setTaskOriginal(null);
          setHistory([]);
          return;
        }
        if (taskDetail && taskDetail.id === task.id && taskDetail.type === task.type && !taskDirty) {
          const patch = action === "pause" ? { enabled: false } : action === "resume" ? { enabled: true } : action === "assign" && value ? { profile: value } : {};
          const next = Object.assign({}, taskDetail, patch);
          setTaskDetail(next);
          setTaskOriginal(taskEditable(next));
        }
      };
      if (action === "remove" || action === "archive") {
        askConfirm({ title: action === "remove" ? "Delete Task?" : "Archive Task?", message: action === "remove" ? "This removes the Cron task." : "This archives the Kanban task.", detail: task.name || task.id, confirmLabel: action === "remove" ? "Delete Task" : "Archive Task", destructive: true }, execute);
        return;
      }
      return execute();
    }

    async function runWeChatDryRun(e) {
      e.preventDefault();
      if (busy) return;
      setBusy("wechat-dry-run");
      setError("");
      setNotice("");
      try {
        const result = await request("/wechat/dry-run", { method: "POST", body: JSON.stringify(wechatDryRun) });
        setNotice(result && result.dry_run ? "Dry run completed. No message was sent." : "Dry run completed.");
        await loadHealth(true);
      } catch (e2) {
        setError(errText(e2));
      } finally {
        setBusy("");
      }
    }

    const filteredAgents = agents.filter(function (a) {
      const q = agentSearch.trim().toLowerCase();
      return !q || [a.name, a.display_name, a.description, a.workspace, a.model, a.provider].some(function (v) { return String(v || "").toLowerCase().includes(q); });
    });
    const filteredProjects = projects.filter(function (p) {
      const q = projectSearch.trim().toLowerCase();
      const stateOk = projectFilter === "all" || (projectFilter === "archived" ? p.archived : !p.archived);
      return stateOk && (!q || [p.name, p.slug, p.profile, p.primary_path, p.board].some(function (v) { return String(v || "").toLowerCase().includes(q); }));
    });
    const filteredTasks = taskRows.filter(function (t) {
      const q = taskSearch.trim().toLowerCase();
      const typeOk = taskTypeFilter === "all" || t.type === taskTypeFilter;
      return typeOk && (!q || [t.name, t.id, t.schedule, t.status, t.profile].some(function (v) { return String(v || "").toLowerCase().includes(q); }));
    });
    const meaningfulErrors = ((management && management.errors) || []).filter(function (row) { return !(row.scope === "projects" && !projectSupported); });

    function Header() {
      const refreshing = tab === "tasks" ? (coreLoading || tasksLoading) : tab === "wechat" ? healthLoading : coreLoading;
      return h(React.Fragment, null,
        h("div", { className: "hx-header" },
          h("div", null, h("h1", null, "Hermes Management Center"), h("div", { className: "hx-muted" }, "Agents · Projects · Tasks · Windows WeChat")),
          h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", type: "button", disabled: refreshing || Boolean(busy), onClick: refreshCurrent }, refreshing ? "Refreshing…" : "Refresh"))
        ),
        h(Tabs, { value: tab, onChange: setTab }),
        meaningfulErrors.length ? h("div", { className: "hx-warning" }, "Some Hermes state could not be loaded. Open Overview for details.") : null,
        error ? h("div", { className: "hx-toast hx-error", role: "alert" }, h("span", null, error), h("button", { type: "button", onClick: function () { setError(""); }, "aria-label": "Dismiss error" }, "×")) : null,
        notice ? h("div", { className: "hx-toast hx-notice", role: "status" }, h("span", null, notice), h("button", { type: "button", onClick: function () { setNotice(""); }, "aria-label": "Dismiss notice" }, "×")) : null
      );
    }

    function Overview() {
      if (coreLoading && !management) return h(LoadingBlock, null, "Loading Management Center…");
      const c = (management && management.counts) || {};
      const tc = (management && management.task_counts) || {};
      const wh = wechatHealth || {};
      const hk = wh.status === "healthy" ? "ok" : wh.status === "degraded" ? "warning" : wh.status === "failed" ? "failed" : "paused";
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-stats" }, h(Stat, { label: "Agents", value: c.agents }), h(Stat, { label: "Running agents", value: c.running_agents }), h(Stat, { label: "Projects", value: projectSupported ? c.projects : "—" }), h(Stat, { label: "Scheduled", value: tc.cron }), h(Stat, { label: "Running tasks", value: tc.running }), h(Stat, { label: "Failed", value: tc.failed })),
        h("div", { className: "hx-two-col" },
          h(Card, null,
            h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "WeChat Desktop"), h("div", { className: "hx-muted" }, "Gateway health only; this view never focuses the desktop app.")), h(Pill, { kind: hk }, wh.status || "unknown")),
            h("div", { className: "hx-kv" }, h("span", null, "Last success"), h("strong", null, fmt(wh.last_success_at)), h("span", null, "Failures"), h("strong", null, wh.consecutive_failures == null ? "—" : String(wh.consecutive_failures)), h("span", null, "Last error"), h("strong", null, wh.last_error || "—")),
            h("button", { className: "hx-button secondary", type: "button", onClick: function () { setTab("wechat"); } }, "Open WeChat status")
          ),
          projectSupported ? h(Card, null,
            h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native Hermes Projects")), h("button", { className: "hx-button", type: "button", onClick: function () { setProjectModal(true); setTab("projects"); } }, "+ Project")),
            projects.filter(function (p) { return !p.archived; }).slice(0, 6).map(function (p) { return h("button", { type: "button", className: "hx-list-row hx-row-button", key: p.profile + ":" + p.slug, onClick: function () { openProject(p); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, p.name || p.slug), h("div", { className: "hx-muted" }, p.primary_path || "No primary folder")), p.active ? h(Pill, { kind: "ok" }, "active") : null); })
          ) : h(Card, { className: "hx-unsupported" }, h("h2", null, "Projects unavailable"), h("p", null, "This Hermes build does not expose the native `hermes project` command. Agents, Tasks and WeChat remain available."))
        ),
        meaningfulErrors.length ? h(Card, null, h("h2", null, "Partial load errors"), meaningfulErrors.map(function (row, i) { return h("div", { className: "hx-error-row", key: i }, h("strong", null, row.scope), h("span", null, row.message)); })) : null,
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Agents"), h("button", { className: "hx-button", type: "button", onClick: function () { setAgentModal(true); setTab("agents"); } }, "+ Agent")), agents.slice(0, 8).map(function (a) { return h("button", { type: "button", className: "hx-list-row hx-row-button", key: a.name, onClick: function () { openAgent(a.name); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, a.display_name || a.name), h("div", { className: "hx-muted" }, a.description || a.workspace || "No description")), h(Pill, { kind: String(a.gateway).toLowerCase().startsWith("running") ? "ok" : "paused" }, a.gateway || "unknown")); })),
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Next 7 days"), h("button", { className: "hx-button secondary", type: "button", onClick: function () { setTab("tasks"); } }, "Open Tasks")), ((management && management.upcoming) || []).slice(0, 10).map(function (t, i) { return h("button", { type: "button", className: "hx-list-row hx-row-button", key: t.type + ":" + t.id + ":" + i, onClick: function () { openTask(t); } }, h("div", { className: "hx-time" }, fmt(t.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, t.name), h("div", { className: "hx-muted" }, t.profile || "unassigned")), h(Pill, { kind: t.type }, t.type)); }))
        )
      );
    }

    function Agents() {
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Agents"), h("div", { className: "hx-muted" }, "Hermes Profiles are isolated Agents.")), h("button", { className: "hx-button", type: "button", onClick: function () { setAgentModal(true); } }, "+ Create Agent")),
        h("div", { className: "hx-toolbar" }, h(SearchBox, { value: agentSearch, onChange: setAgentSearch, placeholder: "Search name, role, workspace, model…" }), h("span", { className: "hx-muted" }, filteredAgents.length + " of " + agents.length)),
        filteredAgents.length ? h("div", { className: "hx-agent-grid" }, filteredAgents.map(function (a) {
          const running = String(a.gateway || "").toLowerCase().startsWith("running");
          const multiplexed = Boolean(a.gateway_managed_by);
          const actionKey = "agent:" + a.name + ":" + (running ? "gateway_stop" : "gateway_start");
          return h(Card, { key: a.name },
            h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, a.display_name || a.name), h("div", { className: "hx-muted" }, a.name)), a.is_default ? h(Pill, { kind: "ok" }, "default") : h(Pill, { kind: running ? "ok" : "paused" }, a.gateway || "stopped")),
            h("p", { className: "hx-description" }, a.description || "No role description"),
            h("div", { className: "hx-kv" }, h("span", null, "Model"), h("strong", null, a.model || "not configured"), h("span", null, "Provider"), h("strong", null, a.provider || "—"), h("span", null, "Workspace"), h("strong", null, a.workspace || "—")),
            h("div", { className: "hx-actions" },
              h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { openAgent(a.name); } }, "Manage"),
              !a.is_default ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { agentAction(a, "use", null, "Default Agent changed."); } }, "Set default") : null,
              multiplexed ? null : h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { agentAction(a, running ? "gateway_stop" : "gateway_start", null, running ? "Gateway stopped." : "Gateway started."); } }, busyIs(actionKey) ? "Working…" : running ? "Stop" : "Start"),
              running ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { restartAgent(a); } }, multiplexed ? "Restart shared gateway" : "Restart") : null
            )
          );
        })) : h(Card, null, h(Empty, null, "No Agents match this view."))
      );
    }

    function Projects() {
      if (!projectSupported) return h("div", { className: "hx-stack" }, h("div", { className: "hx-section-head" }, h("h2", null, "Projects")), h(Card, { className: "hx-unsupported" }, h("h2", null, "Native Projects unavailable"), h("p", null, "Your current Hermes installation does not expose `hermes project`."), h("button", { className: "hx-button secondary", type: "button", onClick: async function () { try { await request("/capabilities?refresh=true"); await loadCore(false); } catch (e) { setError(errText(e)); } } }, "Refresh capabilities")));
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Projects"), h("div", { className: "hx-muted" }, "Native multi-folder Hermes workspaces.")), h("button", { className: "hx-button", type: "button", onClick: function () { setProjectModal(true); } }, "+ Create Project")),
        h("div", { className: "hx-toolbar" }, h(SearchBox, { value: projectSearch, onChange: setProjectSearch, placeholder: "Search project, slug, profile, folder…" }), h("select", { value: projectFilter, onChange: function (e) { setProjectFilter(e.target.value); } }, h("option", { value: "active" }, "Active"), h("option", { value: "archived" }, "Archived"), h("option", { value: "all" }, "All"))),
        filteredProjects.length ? h("div", { className: "hx-agent-grid" }, filteredProjects.map(function (p) { return h(Card, { key: p.profile + ":" + p.slug }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, p.name || p.slug), h("div", { className: "hx-muted" }, p.profile + " · " + p.slug)), p.archived ? h(Pill, { kind: "paused" }, "archived") : p.active ? h(Pill, { kind: "ok" }, "active") : null), h("div", { className: "hx-kv" }, h("span", null, "Primary"), h("strong", null, p.primary_path || "—"), h("span", null, "Board"), h("strong", null, p.board || "—"), h("span", null, "Folders"), h("strong", null, String((p.folders || []).length))), h("div", { className: "hx-actions" }, h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { openProject(p); } }, "Manage"), !p.active && !p.archived ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { projectAction(p, "use", null, "Project activated."); } }, "Use") : null)); })) : h(Card, null, h(Empty, null, "No Projects match this view."))
      );
    }

    function Tasks() {
      if (tasksLoading && !tasks) return h(LoadingBlock, null, "Loading Tasks…");
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Tasks"), h("div", { className: "hx-muted" }, "Native Cron and Kanban across Agents.")), h("button", { className: "hx-button", type: "button", onClick: function () { setTaskModal(true); } }, "+ Create Task")),
        h("div", { className: "hx-toolbar" }, h(SearchBox, { value: taskSearch, onChange: setTaskSearch, placeholder: "Search tasks…" }), h("select", { value: taskProfile, onChange: function (e) { setTaskProfile(e.target.value); } }, h("option", { value: "" }, "All Agents"), agentNames.map(function (n) { return h("option", { key: n, value: n }, n); })), h("select", { value: taskTypeFilter, onChange: function (e) { setTaskTypeFilter(e.target.value); } }, h("option", { value: "all" }, "Cron + Kanban"), h("option", { value: "cron" }, "Cron"), h("option", { value: "kanban" }, "Kanban")), h("select", { value: taskRange, onChange: function (e) { setTaskRange(Number(e.target.value)); } }, h("option", { value: 24 }, "24 hours"), h("option", { value: 168 }, "7 days"), h("option", { value: 720 }, "30 days")), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: includeCompleted, onChange: function (e) { setIncludeCompleted(e.target.checked); } }), " Show completed")),
        h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Upcoming"), tasksLoading ? h("span", { className: "hx-muted" }, "Refreshing…") : null), upcoming.length ? upcoming.slice(0, 30).map(function (u, i) { return h("button", { type: "button", className: "hx-list-row hx-row-button", key: "u:" + u.type + ":" + u.id + ":" + i, onClick: function () { openTask(taskRows.find(function (r) { return r.id === u.id && r.type === u.type && (!u.profile || r.profile === u.profile); }) || u); } }, h("div", { className: "hx-time" }, fmt(u.at)), h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, u.name), h("div", { className: "hx-muted" }, u.profile || "unassigned")), h(Pill, { kind: u.type }, u.type)); }) : h(Empty, null, "No upcoming tasks in this range.")),
        filteredTasks.length ? h("div", { className: "hx-agent-grid" }, filteredTasks.map(function (t) { return h(Card, { key: (t.profile || "") + ":" + t.type + ":" + t.id }, h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, t.name || t.id), h("div", { className: "hx-muted" }, (t.profile || "unassigned") + " · " + t.type)), h(Pill, { kind: t.type }, t.type)), h("div", { className: "hx-kv" }, h("span", null, "Schedule"), h("strong", null, t.type === "cron" ? (t.schedule || "—") : "—"), h("span", null, "Status"), h("strong", null, t.status || (t.enabled === false ? "paused" : "active")), h("span", null, "Next run"), h("strong", null, fmt(t.next_run_at))), h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { openTask(t); } }, "Manage")); })) : h(Card, null, h(Empty, null, "No Tasks match your filters."))
      );
    }

    function WeChat() {
      const wh = wechatHealth || {};
      const ws = wechatStatus || {};
      const hk = wh.status === "healthy" ? "ok" : wh.status === "degraded" ? "warning" : wh.status === "failed" ? "failed" : "paused";
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "WeChat Desktop"), h("div", { className: "hx-muted" }, "Opening this tab never touches the desktop app. Check desktop performs one status check and one conversation-list scan.")), h("button", { className: "hx-button secondary", type: "button", disabled: wechatLoading || Boolean(busy), onClick: checkWeChatDesktop }, wechatLoading ? "Checking…" : "Check desktop")),
        wechatErrors.length ? h(Card, { className: "hx-warning-card" }, h("h2", null, "Partial desktop results"), wechatErrors.map(function (x, i) { return h("div", { className: "hx-error-row", key: i }, h("strong", null, "Warning"), h("span", null, x)); })) : null,
        h("div", { className: "hx-two-col" },
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Gateway health"), h(Pill, { kind: hk }, wh.status || "unknown")), h("div", { className: "hx-kv" }, h("span", null, "Last success"), h("strong", null, fmt(wh.last_success_at)), h("span", null, "Failures"), h("strong", null, wh.consecutive_failures == null ? "—" : String(wh.consecutive_failures)), h("span", null, "Last error"), h("strong", null, wh.last_error || "—"), h("span", null, "Updated"), h("strong", null, fmt(wh.updated_at)))),
          h(Card, null, h("div", { className: "hx-section-head" }, h("h2", null, "Desktop connection"), h(Pill, { kind: ws.available ? "ok" : "failed" }, ws.available == null ? "not checked" : ws.available ? "available" : "unavailable")), h("div", { className: "hx-kv" }, h("span", null, "Window"), h("strong", null, ws.window_title || "—"), h("span", null, "Backend"), h("strong", null, ws.backend || ws.transport || "—"), h("span", null, "Reason"), h("strong", null, ws.reason || "—")))
        ),
        h("div", { className: "hx-two-col" },
          h(Card, null, h("h2", null, "Unread chats"), wechatUnread.length ? wechatUnread.map(function (c) { return h("div", { className: "hx-list-row", key: c.name }, h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, c.name), h("div", { className: "hx-muted" }, c.preview || "Unread")), h(Pill, { kind: "warning" }, "unread")); }) : h(Empty, null, wechatStatus ? "No unread chats detected." : "Run Check desktop to load chats.")),
          h(Card, null, h("h2", null, "Recent chats"), wechatChats.length ? wechatChats.map(function (c) { return h("button", { type: "button", className: "hx-list-row hx-row-button", key: c.name, onClick: function () { setWechatDryRun(Object.assign({}, wechatDryRun, { chat: c.name })); } }, h("div", { className: "hx-grow hx-left" }, h("div", { className: "hx-title" }, c.name), h("div", { className: "hx-muted" }, c.preview || "—")), c.unread ? h(Pill, { kind: "warning" }, "unread") : null); }) : h(Empty, null, "No recent chats loaded."))
        ),
        h(Card, { className: "hx-safe-test" }, h("div", { className: "hx-section-head" }, h("div", null, h("h2", null, "Safe dry-run test"), h("div", { className: "hx-muted" }, "Locates the exact conversation, types the text, then clears it. Enter is never pressed.")), h(Pill, { kind: "ok" }, "NO SEND")), h("form", { className: "hx-form", onSubmit: runWeChatDryRun }, Field("Exact chat name", h("input", { required: true, value: wechatDryRun.chat, onChange: function (e) { setWechatDryRun(Object.assign({}, wechatDryRun, { chat: e.target.value })); } })), Field("Test text", h("textarea", { rows: 3, required: true, value: wechatDryRun.text, onChange: function (e) { setWechatDryRun(Object.assign({}, wechatDryRun, { text: e.target.value })); } })), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busyIs("wechat-dry-run") }, busyIs("wechat-dry-run") ? "Testing…" : "Run dry test"))))
      );
    }

    function DirtyNote(p) {
      return p.dirty ? h("div", { className: "hx-warning hx-span-2" }, "Save or discard edits before running lifecycle actions so refreshed state cannot overwrite your changes.") : null;
    }

    function AgentDetail() {
      if (!agentDetail) return null;
      const a = agentDetail;
      const running = String(a.gateway || "").toLowerCase().startsWith("running");
      const workspaceOptions = Array.from(new Set([a.workspace || ".", "."].concat(projects.flatMap(function (p) { return [p.primary_path, p.slug].filter(Boolean); }))));
      const providerItems = (agentProviderData && agentProviderData.items) || [];
      const providerOptions = Array.from(new Set([a.provider].concat(providerItems.map(providerValue)).filter(Boolean)));
      const activeProvider = providerItems.find(function (p) { return providerValue(p) === a.provider || p.id === a.provider; });
      const modelOptions = Array.from(new Set([a.model].concat(activeProvider && Array.isArray(activeProvider.models) ? activeProvider.models : []).filter(Boolean)));
      return h(Dialog, { open: true, title: "Agent · " + (a.display_name || a.name), subtitle: agentDirty ? "Unsaved changes" : "Native Hermes Profile", locked: Boolean(busy), onRequestClose: function () { guardedClose(agentDirty, function () { setAgentDetail(null); setAgentOriginal(null); setAgentResources([]); }); } },
        h("form", { className: "hx-form", onSubmit: saveAgent },
          error ? h("div", { className: "hx-toast hx-error hx-span-2", role: "alert", "aria-live": "assertive" }, h("span", null, h("strong", null, "Action failed: "), error), h("button", { type: "button", onClick: function () { setError(""); }, "aria-label": "Dismiss error" }, "×")) : null,
          Field("Profile name", h("input", { value: a.edit_name == null ? a.name : a.edit_name, disabled: a.name === "default", onChange: function (e) { setAgentDetail(Object.assign({}, a, { edit_name: e.target.value })); } })),
          Field("Description / role", h("textarea", { rows: 3, value: a.description || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { description: e.target.value })); } })),
          Field("Workspace", h("select", { value: a.workspace || ".", onChange: function (e) { setAgentDetail(Object.assign({}, a, { workspace: e.target.value })); } }, workspaceOptions.map(function (value) { return h("option", { key: value, value: value }, value === "." ? "Default workspace (.)" : value); }))),
          Field("Provider", h("select", { value: a.provider || "", onChange: function (e) { const nextProvider = providerItems.find(function (p) { return providerValue(p) === e.target.value || p.id === e.target.value; }); const models = nextProvider && Array.isArray(nextProvider.models) ? nextProvider.models : []; const nextModel = nextProvider && nextProvider.default_model ? nextProvider.default_model : (models[0] || ""); setAgentDetail(Object.assign({}, a, { provider: e.target.value, model: nextModel })); } }, providerOptions.length ? providerOptions.map(function (value) { const item = providerItems.find(function (p) { return providerValue(p) === value || p.id === value; }); return h("option", { key: value, value: value }, item && (item.custom_name || item.label || item.name) ? (item.custom_name || item.label || item.name) : value); }) : h("option", { value: a.provider || "" }, a.provider || "No configured providers"))),
          Field("Model", h("select", { value: a.model || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { model: e.target.value })); } }, modelOptions.length ? modelOptions.map(function (value) { return h("option", { key: value, value: value }, value); }) : h("option", { value: "" }, "No saved models"))),
          Field("Gateway", h("input", { value: a.gateway || "unknown", readOnly: true })),
          Field("SOUL.md", h("textarea", { rows: 12, value: a.soul || "", onChange: function (e) { setAgentDetail(Object.assign({}, a, { soul: e.target.value })); } })),
          h(AgentResourcePicker),
          h(DirtyNote, { dirty: agentDirty }),
          h("div", { className: "hx-actions hx-span-2" },
            h("button", { className: "hx-button", type: "submit", disabled: busyIs("agent-save") || !agentDirty }, busyIs("agent-save") ? "Saving…" : "Save"),
            h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { agentAction(a, "gateway_status", null, "Gateway status refreshed."); } }, "Check gateway"),
            a.gateway_managed_by ? null : h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { agentAction(a, running ? "gateway_stop" : "gateway_start", null, running ? "Gateway stopped." : "Gateway started."); } }, running ? "Stop" : "Start"),
            running ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { restartAgent(a); } }, "Restart") : null,
            h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { agentAction(a, "export", null, "Agent exported."); } }, "Export"),
            a.name !== "default" ? h("button", { className: "hx-button danger", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { deleteAgent(a); } }, "Delete") : null
          )
        )
      );
    }

    function ProjectDetail() {
      if (!projectDetail) return null;
      const p = projectDetail;
      const blockAction = Boolean(busy) || projectDirty;
      return h(Dialog, { open: true, title: "Project · " + (p.name || p.slug), subtitle: projectDirty ? "Unsaved changes" : (p.profile + " · " + p.slug), locked: Boolean(busy), onRequestClose: function () { guardedClose(projectDirty, function () { setProjectDetail(null); setProjectOriginal(null); setProjectFolderInput(""); }); } },
        h("form", { className: "hx-form", onSubmit: saveProject },
          Field("Name", h("input", { value: p.name || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { name: e.target.value })); } })),
          Field("Primary folder", h("input", { value: p.primary_path || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { primary_path: e.target.value })); } })),
          Field("Kanban board", h("input", { value: p.board || "", onChange: function (e) { setProjectDetail(Object.assign({}, p, { board: e.target.value })); } })),
          h(DirtyNote, { dirty: projectDirty }),
          h("div", { className: "hx-actions hx-span-2" },
            h("button", { className: "hx-button", type: "submit", disabled: busyIs("project-save") || !projectDirty }, busyIs("project-save") ? "Saving…" : "Save"),
            !p.active && !p.archived ? h("button", { className: "hx-button secondary", type: "button", disabled: blockAction, onClick: function () { projectAction(p, "use", null, "Project activated."); } }, "Use project") : null,
            h("button", { className: "hx-button secondary", type: "button", disabled: blockAction, onClick: function () { projectAction(p, p.archived ? "restore" : "archive", null, p.archived ? "Project restored." : "Project archived."); } }, p.archived ? "Restore" : "Archive")
          )
        ),
        h("div", { className: "hx-detail-section" },
          h("div", { className: "hx-section-head" }, h("h3", null, "Folders"), h("div", { className: "hx-inline-add" }, h("input", { placeholder: "Folder path", value: projectFolderInput, disabled: projectDirty, onChange: function (e) { setProjectFolderInput(e.target.value); } }), h("button", { className: "hx-button secondary", type: "button", disabled: blockAction || !projectFolderInput.trim(), onClick: async function () { const value = projectFolderInput.trim(); await projectAction(p, "add_folder", value, "Folder added."); setProjectFolderInput(""); } }, "Add"))),
          (p.folders || []).map(function (f) { return h("div", { className: "hx-list-row", key: f.path }, h("div", { className: "hx-grow" }, h("div", { className: "hx-title" }, f.path)), f.is_primary ? h(Pill, { kind: "ok" }, "primary") : h("button", { className: "hx-button secondary", type: "button", disabled: blockAction, onClick: function () { projectAction(p, "set_primary", f.path, "Primary folder updated."); } }, "Set primary"), !f.is_primary ? h("button", { className: "hx-button danger ghost", type: "button", disabled: blockAction, onClick: function () { askConfirm({ title: "Remove folder?", message: "Remove this folder from the Project?", detail: f.path, confirmLabel: "Remove folder", destructive: true }, function () { return projectAction(p, "remove_folder", f.path, "Folder removed."); }); } }, "Remove") : null); })
        ),
        h("div", { className: "hx-detail-section" }, h("h3", null, "Workspace Agents"), h("div", { className: "hx-muted" }, (p.agents || []).join(", ") || "None"), h("select", { defaultValue: "", disabled: blockAction, onChange: function (e) { if (e.target.value) projectAction(p, "assign_agent", e.target.value, "Workspace Agent assigned."); } }, h("option", { value: "" }, "Assign workspace Agent…"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); })))
      );
    }

    function TaskDetail() {
      if (!taskDetail) return null;
      const t = taskDetail;
      const blockAction = Boolean(busy) || taskDirty;
      return h(Dialog, { open: true, title: "Task · " + (t.name || t.id), subtitle: taskDirty ? "Unsaved changes" : ((t.profile || "unassigned") + " · " + t.type), locked: Boolean(busy), onRequestClose: function () { guardedClose(taskDirty, function () { setTaskDetail(null); setTaskOriginal(null); setHistory([]); }); } },
        h("form", { className: "hx-form", onSubmit: saveTask },
          Field("Name", h("input", { value: t.name || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { name: e.target.value })); } })),
          Field("Agent/Profile", h("select", { value: t.profile || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { profile: e.target.value })); } }, h("option", { value: "" }, "Unassigned/default"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))),
          Field(t.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 5, value: t.prompt || t.body || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { prompt: e.target.value })); } })),
          t.type === "cron" ? Field("Schedule", h("input", { value: t.schedule || "", onChange: function (e) { setTaskDetail(Object.assign({}, t, { schedule: e.target.value })); } })) : Field("Priority", h("input", { type: "number", min: 0, max: 100, value: t.priority == null ? 50 : t.priority, onChange: function (e) { setTaskDetail(Object.assign({}, t, { priority: Number(e.target.value) })); } })),
          h(DirtyNote, { dirty: taskDirty }),
          h("div", { className: "hx-actions hx-span-2" },
            h("button", { className: "hx-button", type: "submit", disabled: busyIs("task-save") || !taskDirty }, busyIs("task-save") ? "Saving…" : "Save"),
            t.type === "cron" ? h("button", { className: "hx-button secondary", type: "button", disabled: blockAction, onClick: function () { taskAction(t, t.enabled === false ? "resume" : "pause", null, t.enabled === false ? "Task resumed." : "Task paused."); } }, t.enabled === false ? "Resume" : "Pause") : null,
            t.type === "cron" ? h("button", { className: "hx-button secondary", type: "button", disabled: blockAction, onClick: function () { taskAction(t, "run", null, "Task started."); } }, "Run now") : null,
            h("button", { className: "hx-button danger", type: "button", disabled: blockAction, onClick: function () { taskAction(t, t.type === "cron" ? "remove" : "archive"); } }, t.type === "cron" ? "Delete" : "Archive")
          )
        ),
        h("div", { className: "hx-detail-section" }, h("h3", null, "Execution history"), historyLoading ? h(LoadingBlock, null, "Loading history…") : history.length ? history.map(function (row, i) { return h("div", { className: "hx-history-row", key: i }, h(Pill, { kind: row.status || row.state || "" }, row.status || row.state || "record"), h("div", { className: "hx-grow" }, fmt(row.claimed_at || row.started_at || row.completed_at || row.updated_at)), row.error ? h("div", { className: "hx-muted" }, row.error) : null); }) : h(Empty, null, "No execution history."))
      );
    }

    function AgentModal() {
      return h(Dialog, { open: agentModal, title: "Create Agent", subtitle: agentCreateDirty ? "Unsaved new Agent" : "Create a native Hermes Profile", locked: busyIs("agent-create"), onRequestClose: function () { guardedClose(agentCreateDirty, function () { setAgentModal(false); setAgentForm(Object.assign({}, DEFAULT_AGENT)); }); } }, h("form", { className: "hx-form", onSubmit: createAgent }, Field("Name", h("input", { required: true, pattern: "[a-z0-9][a-z0-9_-]{0,63}", value: agentForm.name, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { name: e.target.value.toLowerCase() })); } })), Field("Description / role", h("textarea", { rows: 3, value: agentForm.description, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { description: e.target.value })); } })), Field("Clone mode", h("select", { value: agentForm.clone_mode, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_mode: e.target.value })); } }, h("option", { value: "blank" }, "Blank"), h("option", { value: "clone" }, "Clone config"), h("option", { value: "clone_all" }, "Clone all state"))), agentForm.clone_mode !== "blank" ? Field("Clone from", h("select", { value: agentForm.clone_from, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { clone_from: e.target.value })); } }, h("option", { value: "" }, "Active/default source"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))) : null, Field("Workspace", h("input", { value: agentForm.workspace, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { workspace: e.target.value })); } })), Field("Provider", h("input", { value: agentForm.provider, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { provider: e.target.value })); } })), Field("Model", h("input", { value: agentForm.model, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { model: e.target.value })); } })), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: agentForm.no_skills, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { no_skills: e.target.checked })); } }), " Create without bundled skills"), Field("Initial SOUL.md", h("textarea", { rows: 8, value: agentForm.soul, onChange: function (e) { setAgentForm(Object.assign({}, agentForm, { soul: e.target.value })); } })), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busyIs("agent-create") }, busyIs("agent-create") ? "Creating…" : "Create Agent"), h("button", { className: "hx-button secondary", type: "button", disabled: busyIs("agent-create"), onClick: function () { guardedClose(agentCreateDirty, function () { setAgentModal(false); setAgentForm(Object.assign({}, DEFAULT_AGENT)); }); } }, "Cancel"))));
    }

    function ProjectModal() {
      return h(Dialog, { open: projectModal && projectSupported, title: "Create Project", subtitle: projectCreateDirty ? "Unsaved new Project" : "Create a native Hermes Project", locked: busyIs("project-create"), onRequestClose: function () { guardedClose(projectCreateDirty, function () { setProjectModal(false); setProjectForm(Object.assign({}, DEFAULT_PROJECT)); }); } }, h("form", { className: "hx-form", onSubmit: createProject }, Field("Name", h("input", { required: true, value: projectForm.name, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { name: e.target.value })); } })), Field("Slug", h("input", { value: projectForm.slug, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { slug: e.target.value })); } })), Field("Profile owner", h("select", { value: projectForm.profile, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Workspace Agent", h("select", { value: projectForm.agent, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { agent: e.target.value })); } }, h("option", { value: "" }, "None"), agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), Field("Folders (comma/newline)", h("textarea", { rows: 4, value: projectForm.folders, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { folders: e.target.value })); } })), Field("Primary folder", h("input", { value: projectForm.primary, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { primary: e.target.value })); } })), Field("Description", h("textarea", { rows: 3, value: projectForm.description, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { description: e.target.value })); } })), Field("Board", h("input", { value: projectForm.board, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { board: e.target.value })); } })), Field("Icon", h("input", { value: projectForm.icon, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { icon: e.target.value })); } })), Field("Color", h("input", { value: projectForm.color, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { color: e.target.value })); } })), h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: projectForm.use, onChange: function (e) { setProjectForm(Object.assign({}, projectForm, { use: e.target.checked })); } }), " Use this Project after creation"), h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busyIs("project-create") }, busyIs("project-create") ? "Creating…" : "Create Project"), h("button", { className: "hx-button secondary", type: "button", disabled: busyIs("project-create"), onClick: function () { guardedClose(projectCreateDirty, function () { setProjectModal(false); setProjectForm(Object.assign({}, DEFAULT_PROJECT)); }); } }, "Cancel"))));
    }

    function TaskModal() {
      return h(Dialog, { open: taskModal, title: "Create Task", subtitle: taskCreateDirty ? "Unsaved new Task" : "Native Cron or Kanban", locked: busyIs("task-create"), onRequestClose: function () { guardedClose(taskCreateDirty, function () { setTaskModal(false); setTaskForm(Object.assign({}, DEFAULT_TASK)); }); } }, h("form", { className: "hx-form", onSubmit: createTask }, Field("Type", h("select", { value: taskForm.type, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { type: e.target.value })); } }, h("option", { value: "cron" }, "Cron"), h("option", { value: "kanban" }, "Kanban"))), Field("Name", h("input", { required: true, value: taskForm.name, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { name: e.target.value })); } })), Field("Agent/Profile", h("select", { value: taskForm.profile, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { profile: e.target.value })); } }, agentNames.map(function (name) { return h("option", { key: name, value: name }, name); }))), taskForm.type === "cron" ? Field("Deliver", h("input", { value: taskForm.deliver, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { deliver: e.target.value })); } })) : Field("Priority", h("input", { type: "number", min: 0, max: 100, value: taskForm.priority, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { priority: Number(e.target.value) })); } })), Field(taskForm.type === "cron" ? "Prompt" : "Details", h("textarea", { rows: 6, required: taskForm.type === "cron", value: taskForm.prompt, onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { prompt: e.target.value })); } })), taskForm.type === "cron" ? Field("Schedule", h("input", { required: true, value: taskForm.schedule, placeholder: "every 10m or cron expression", onChange: function (e) { setTaskForm(Object.assign({}, taskForm, { schedule: e.target.value })); } })) : null, h("div", { className: "hx-actions hx-span-2" }, h("button", { className: "hx-button", type: "submit", disabled: busyIs("task-create") }, busyIs("task-create") ? "Creating…" : "Create Task"), h("button", { className: "hx-button secondary", type: "button", disabled: busyIs("task-create"), onClick: function () { guardedClose(taskCreateDirty, function () { setTaskModal(false); setTaskForm(Object.assign({}, DEFAULT_TASK)); }); } }, "Cancel"))));
    }

    // These render helpers are declared inside ManagementApp, so using them as
    // React component types would create a new type on every keystroke. React
    // would then unmount/remount the dialog and its initial-focus effect would
    // move focus to the first enabled control (normally Close). Invoke the
    // hook-free helpers directly so the stable Dialog/input elements reconcile.
    return h("div", { className: "hx-page" },
      Header(),
      tab === "overview" ? Overview() : tab === "agents" ? Agents() : tab === "projects" ? Projects() : tab === "tasks" ? Tasks() : WeChat(),
      AgentDetail(), ProjectDetail(), TaskDetail(), AgentModal(), ProjectModal(), TaskModal(),
      h(ConfirmDialog, { spec: confirmSpec, onCancel: function () { if (!confirmSpec || !confirmSpec.locked) setConfirmSpec(null); }, onConfirm: confirmNow })
    );
  }

  HX.ManagementApp = ManagementApp;
})();

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.React || !HX.ManagementApp) return;
  const React = HX.React;
  const h = HX.h;
  const { useCallback, useEffect, useMemo, useState } = React;
  const { request, errText, Card, Pill, Field, Empty, LoadingBlock } = HX;
  const LegacyManagementApp = HX.ManagementApp;
  const RESOURCE_LABEL_STORAGE_KEY = "hermes-control-center-resource-labels-v1";

  function readResourceLabels() {
    try {
      const raw = window.localStorage.getItem(RESOURCE_LABEL_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function writeResourceLabels(labels) {
    try { window.localStorage.setItem(RESOURCE_LABEL_STORAGE_KEY, JSON.stringify(labels || {})); }
    catch (_) {}
  }

  function shortResourceId(resourceId) {
    const value = String(resourceId || "");
    const suffix = value.indexOf(":") >= 0 ? value.split(":").pop() : value;
    return suffix ? suffix.slice(-8) : "unknown";
  }

  function browserAttachHint(row) {
    if (row.attachable) return row.debug_port ? "CDP endpoint verified on port " + row.debug_port + "." : "Browser is attachable.";
    if (row.attach_reason === "remote_debugging_not_enabled") return "This is a normal Chrome/Edge window without CDP. Launch an Agent Browser above instead of changing your personal browser.";
    if (String(row.attach_reason || "").indexOf("cdp_unreachable") === 0) return "A remote-debugging port was detected, but the CDP endpoint did not answer. Check browser-attach.log.";
    return row.attach_error || row.attach_reason || "Browser cannot be attached.";
  }

  function ResourcePage() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [labels, setLabels] = useState(readResourceLabels);
    const [launchAgent, setLaunchAgent] = useState("");
    function timedRequest(path, timeoutMs) {
      return Promise.race([
        request(path),
        new Promise(function (_, reject) {
          window.setTimeout(function () { reject(new Error("Desktop resource scan timed out")); }, timeoutMs);
        })
      ]);
    }
    const load = useCallback(async function (refresh) {
      setLoading(true); setError("");
      try { setData(await timedRequest("/resources?refresh=" + (refresh ? "true" : "false"), refresh ? 12000 : 5000)); }
      catch (e) {
        if (refresh) {
          try {
            setData(await timedRequest("/resources?refresh=false", 5000));
            setError("Live desktop scan timed out; showing the last known resource state. Click Refresh to retry.");
          } catch (_) { setError(errText(e)); }
        } else setError(errText(e));
      }
      finally { setLoading(false); }
    }, []);
    useEffect(function () { load(true); }, [load]);
    useEffect(function () {
      const agents = (data && data.agents) || [];
      if (!launchAgent && agents.length) setLaunchAgent(agents[0]);
    }, [data, launchAgent]);

    function setResourceLabel(row, value) {
      const nextValue = String(value || "").slice(0, 80);
      setLabels(function (current) {
        const next = Object.assign({}, current);
        if (nextValue.trim()) next[row.id] = nextValue;
        else delete next[row.id];
        writeResourceLabels(next);
        return next;
      });
    }

    async function bind(row, agent) {
      setBusy(row.id); setError(""); setNotice("");
      try {
        if (!agent) await request("/resources/" + encodeURIComponent(row.id) + "/bind", { method: "DELETE" });
        else await request("/resources/" + encodeURIComponent(row.id) + "/bind", { method: "POST", body: JSON.stringify({ agent: agent }) });
        await load(true);
      } catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    async function launchManagedBrowser() {
      if (!launchAgent || busy) return;
      setBusy("launch-browser"); setError(""); setNotice("");
      try {
        const result = await request("/resources/browser/launch", {
          method: "POST",
          body: JSON.stringify({ agent: launchAgent, browser: "chrome", start_url: "https://wx.qq.com/" })
        });
        const port = result && result.launch && result.launch.debug_port;
        setNotice("Managed Chrome launched and bound to " + launchAgent + (port ? " · CDP " + port : "") + ". WeChat Web is opening in the dedicated profile.");
        await load(true);
      } catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    if (loading && !data) return h(LoadingBlock, null, "Scanning desktop resources…");
    const rows = (data && data.items) || [];
    const agents = (data && data.agents) || [];
    const wechat = rows.filter(function (r) { return r.kind === "wechat"; });
    const browsers = rows.filter(function (r) { return r.kind === "browser"; });
    function block(title, items) {
      return h("div", { className: "hx-stack" },
        h("div", { className: "hx-section-head" }, h("h2", null, title), h("span", { className: "hx-muted" }, items.length + " detected")),
        items.length ? h("div", { className: "hx-agent-grid" }, items.map(function (r, index) {
          const kind = r.status === "ready" ? "ok" : r.status === "offline" ? "failed" : "warning";
          const customLabel = String(labels[r.id] || "").trim();
          const detectedTitle = String(r.title || "").trim();
          const conversationTitle = String(r.conversation_title || "").trim();
          const wechatFallback = "WeChat #" + (index + 1) + " · " + shortResourceId(r.id);
          const displayName = r.kind === "wechat"
            ? (customLabel || conversationTitle || detectedTitle || wechatFallback)
            : (detectedTitle || r.app);
          return h(Card, { key: r.id },
            h("div", { className: "hx-agent-head" }, h("div", null,
              h("h2", null, displayName),
              r.kind === "wechat" && customLabel && conversationTitle ? h("div", { className: "hx-muted" }, "Current chat: " + conversationTitle) : null,
              r.kind === "wechat" && customLabel ? h("div", { className: "hx-muted" }, "Window title: " + (detectedTitle || "—")) : null,
              h("div", { className: "hx-muted" }, r.app + " · PID " + r.pid + (r.kind === "wechat" ? " · Instance " + shortResourceId(r.id) : ""))
            ), h(Pill, { kind: kind }, r.status || "unknown")),
            r.kind === "wechat" ? Field("Instance label", h("input", {
              value: labels[r.id] || "",
              placeholder: "e.g. Warehouse CS / 售后微信",
              maxLength: 80,
              disabled: busy === r.id,
              onChange: function (e) { setResourceLabel(r, e.target.value); }
            }), "Saved in this Control Center browser. Use a label to distinguish multiple WeChat accounts.") : null,
            h("div", { className: "hx-kv" },
              r.kind === "wechat" ? h("span", null, "Current chat") : null, r.kind === "wechat" ? h("strong", null, conversationTitle || "Not detected") : null,
              r.kind === "wechat" ? h("span", null, "Window title") : null, r.kind === "wechat" ? h("strong", null, detectedTitle || "—") : null,
              r.kind === "wechat" ? h("span", null, "Instance") : null, r.kind === "wechat" ? h("strong", null, "PID " + r.pid + " · " + shortResourceId(r.id)) : null,
              h("span", null, "Resource ID"), h("strong", null, r.id),
              h("span", null, "Window"), h("strong", null, r.hwnd || "—"),
              r.kind === "browser" ? h("span", null, "Profile") : null, r.kind === "browser" ? h("strong", null, r.profile || "Default") : null,
              r.kind === "browser" ? h("span", null, "Attachable") : null, r.kind === "browser" ? h("strong", null, r.attachable ? ("Ready" + (r.debug_port ? " · CDP " + r.debug_port : "")) : "Not attachable") : null,
              r.kind === "browser" ? h("span", null, "Attach reason") : null, r.kind === "browser" ? h("strong", null, r.attach_reason || "—") : null,
              h("span", null, "Assigned Agent"), h("strong", null, r.assigned_agent || "Unbound")
            ),
            r.kind === "browser" ? h("div", { className: "hx-muted", style: { marginTop: "10px" } }, browserAttachHint(r)) : null,
            h("div", { className: "hx-actions" },
              h("select", { value: r.assigned_agent || "", disabled: busy === r.id || (r.kind === "browser" && !r.attachable), onChange: function (e) { bind(r, e.target.value); } },
                h("option", { value: "" }, "Unbound"), agents.map(function (a) { return h("option", { key: a, value: a }, a); })
              )
            )
          );
        })) : h(Card, null, h(Empty, null, "No " + title.toLowerCase() + " detected."))
      );
    }
    return h("div", { className: "hx-page hx-stack" },
      h("div", { className: "hx-section-head" },
        h("div", null, h("h1", null, "Resources"), h("div", { className: "hx-muted" }, "Fail-closed policy: an Agent can use only resources explicitly bound to it. No fallback to another account or browser.")),
        h("div", { className: "hx-actions" },
          h("select", { value: launchAgent, disabled: busy === "launch-browser" || !agents.length, onChange: function (e) { setLaunchAgent(e.target.value); } },
            agents.length ? agents.map(function (a) { return h("option", { key: a, value: a }, a); }) : h("option", { value: "" }, "No Agents")
          ),
          h("button", { className: "hx-button", type: "button", disabled: busy === "launch-browser" || !launchAgent, onClick: launchManagedBrowser }, busy === "launch-browser" ? "Launching…" : "Launch Agent Browser"),
          h("button", { className: "hx-button secondary", type: "button", disabled: loading || Boolean(busy), onClick: function () { load(true); } }, loading ? "Scanning…" : "Refresh")
        )
      ),
      h(Card, null,
        h("strong", null, "Agent Browser uses a dedicated Chrome profile + verified CDP endpoint."),
        h("div", { className: "hx-muted", style: { marginTop: "6px" } }, "It opens WeChat Web first and is automatically bound to the selected Agent. Your normal Chrome stays separate and is intentionally shown as Not attachable.")),
      error ? h(Card, { className: "hx-warning-card" }, error) : null,
      notice ? h(Card, null, notice) : null,
      block("WeChat instances", wechat),
      block("Browser instances", browsers)
    );
  }

  function ProviderPage() {
    const [profile, setProfile] = useState("default");
    const [profileDraft, setProfileDraft] = useState("default");
    const [data, setData] = useState(null);
    const [forms, setForms] = useState({});
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const load = useCallback(async function () {
      setLoading(true); setError("");
      try {
        const result = await request("/providers?profile=" + encodeURIComponent(profile));
        setData(result);
        const next = {};
        (result.items || []).forEach(function (p) {
          next[p.id] = {
            api_key: "",
            base_url: p.base_url || "",
            default_model: p.default_model || "",
            custom_name: p.custom_name || "",
            configured: Boolean(p.configured)
          };
        });
        setForms(next);
      } catch (e) { setError(errText(e)); }
      finally { setLoading(false); }
    }, [profile]);
    useEffect(function () { load(); }, [load]);
    function applyProfile() {
      const value = (profileDraft || "default").trim().toLowerCase() || "default";
      setProfileDraft(value);
      setProfile(value);
    }
    async function save(p) {
      setBusy(p.id); setError(""); setNotice("");
      try {
        const form = forms[p.id] || {};
        const payload = { base_url: form.base_url || "", default_model: form.default_model || "" };
        if (p.supports_custom_name) payload.custom_name = form.custom_name || "";
        if (form.api_key) payload.api_key = form.api_key;
        if (p.auth === "oauth") payload.configured = Boolean(form.configured);
        await request("/providers/" + encodeURIComponent(p.id) + "?profile=" + encodeURIComponent(profile), { method: "PUT", body: JSON.stringify(payload) });
        setNotice(p.label + " saved for " + profile + ".");
        await load();
      } catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }
    const items = (data && data.items) || [];
    return h("div", { className: "hx-page hx-stack" },
      h("div", { className: "hx-section-head" }, h("div", null, h("h1", null, "Providers"), h("div", { className: "hx-muted" }, "Configure model providers here, then choose Provider/Model on each Agent.")),
        h("div", { className: "hx-actions" },
          h("input", { value: profileDraft, onChange: function (e) { setProfileDraft(e.target.value); }, onKeyDown: function (e) { if (e.key === "Enter") applyProfile(); }, placeholder: "Hermes profile" }),
          h("button", { className: "hx-button secondary", type: "button", onClick: applyProfile, disabled: loading }, "Apply")
        )
      ),
      error ? h(Card, { className: "hx-warning-card" }, error) : null,
      notice ? h(Card, null, notice) : null,
      loading && !data ? h(LoadingBlock, null, "Loading providers…") : h("div", { className: "hx-agent-grid" }, items.map(function (p) {
        const f = forms[p.id] || {};
        return h(Card, { key: p.id },
          h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, p.label), h("div", { className: "hx-muted" }, p.auth === "oauth" ? "OAuth / external login" : "API key")), h(Pill, { kind: p.configured ? "ok" : "paused" }, p.configured ? "configured" : "not configured")),
          p.supports_custom_name ? Field("Provider name", h("input", { value: f.custom_name || "", placeholder: "e.g. APIPLANT", onChange: function (e) { setForms(Object.assign({}, forms, { [p.id]: Object.assign({}, f, { custom_name: e.target.value }) })); } })) : null,
          p.auth === "api_key" ? Field("API key", h("input", { type: "password", autoComplete: "off", value: f.api_key || "", placeholder: p.has_api_key ? "Stored — enter only to replace" : "Enter API key", onChange: function (e) { setForms(Object.assign({}, forms, { [p.id]: Object.assign({}, f, { api_key: e.target.value }) })); } })) : h("label", { className: "hx-inline-check" }, h("input", { type: "checkbox", checked: Boolean(f.configured), onChange: function (e) { setForms(Object.assign({}, forms, { [p.id]: Object.assign({}, f, { configured: e.target.checked }) })); } }), " Authentication completed externally"),
          p.supports_base_url ? Field("Base URL", h("input", { value: f.base_url || "", placeholder: p.id === "custom" ? "https://provider.example/v1" : "Optional/custom endpoint", onChange: function (e) { setForms(Object.assign({}, forms, { [p.id]: Object.assign({}, f, { base_url: e.target.value }) })); } })) : null,
          Field("Default model", h("input", { value: f.default_model || "", placeholder: p.id === "custom" ? "Model ID" : "Optional", onChange: function (e) { setForms(Object.assign({}, forms, { [p.id]: Object.assign({}, f, { default_model: e.target.value }) })); } })),
          h("div", { className: "hx-actions" }, h("button", { type: "button", className: "hx-button", disabled: busy === p.id, onClick: function () { save(p); } }, busy === p.id ? "Saving…" : "Save"))
        );
      }))
    );
  }

  function ControlCenterApp() {
    const [section, setSection] = useState("control");
    const nav = useMemo(function () { return [["control", "Control"], ["providers", "Providers"], ["resources", "Resources"]]; }, []);
    return h("div", null,
      h("div", { className: "hx-page" }, h("div", { className: "hx-tabs", role: "tablist", "aria-label": "Hermes Control Center" }, nav.map(function (item) {
        return h("button", { key: item[0], type: "button", role: "tab", "aria-selected": section === item[0], className: "hx-tab " + (section === item[0] ? "active" : ""), onClick: function () { setSection(item[0]); } }, item[1]);
      }))),
      section === "control" ? h(LegacyManagementApp) : section === "providers" ? h(ProviderPage) : h(ResourcePage)
    );
  }

  HX.ManagementApp = ControlCenterApp;
})();

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.React || !HX.ManagementApp) return;
  const React = HX.React;
  const h = HX.h;
  const { useCallback, useEffect, useState } = React;
  const { request, errText, Card, Pill, Field, LoadingBlock } = HX;
  const PreviousApp = HX.ManagementApp;

  function ProviderModelsPage() {
    const [profile, setProfile] = useState("default");
    const [data, setData] = useState(null);
    const [forms, setForms] = useState({});
    const [queries, setQueries] = useState({});
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    const load = useCallback(async function () {
      setLoading(true); setError("");
      try {
        const result = await request("/providers?profile=" + encodeURIComponent(profile));
        setData(result);
        const next = {};
        (result.items || []).forEach(function (p) {
          const models = Array.isArray(p.models) ? p.models.slice() : (p.default_model ? [p.default_model] : []);
          next[p.id] = {
            key_value: "",
            base_url: p.base_url || "",
            custom_name: p.custom_name || "",
            default_model: p.default_model || "",
            selected: models,
            available: models.slice()
          };
        });
        setForms(next);
      } catch (e) { setError(errText(e)); }
      finally { setLoading(false); }
    }, [profile]);
    useEffect(function () { load(); }, [load]);

    function patch(id, values) {
      setForms(function (current) {
        const next = Object.assign({}, current);
        next[id] = Object.assign({}, current[id] || {}, values);
        return next;
      });
    }

    async function persist(p, includeModels) {
      const f = forms[p.id] || {};
      const payload = { base_url: f.base_url || "", default_model: f.default_model || "" };
      if (p.supports_custom_name) payload.custom_name = f.custom_name || "";
      if (f.key_value) payload.api_key = f.key_value;
      if (includeModels) payload.models = f.selected || [];
      return request("/providers/" + encodeURIComponent(p.id) + "?profile=" + encodeURIComponent(profile), {
        method: "PUT", body: JSON.stringify(payload)
      });
    }

    async function discover(p) {
      setBusy("discover:" + p.id); setError(""); setNotice("");
      try {
        await persist(p, false);
        const result = await request("/providers/discover-models", {
          method: "POST", body: JSON.stringify({ provider: p.id, profile: profile })
        });
        const available = (result && result.items) || [];
        const f = forms[p.id] || {};
        const selected = (f.selected || []).filter(function (m) { return available.indexOf(m) >= 0; });
        patch(p.id, { available: available, selected: selected, default_model: selected.indexOf(f.default_model) >= 0 ? f.default_model : (selected[0] || "") });
        setNotice("Found " + available.length + " available models.");
      } catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    function toggle(p, model, checked) {
      const f = forms[p.id] || {};
      let selected = (f.selected || []).slice();
      if (checked && selected.indexOf(model) < 0) selected.push(model);
      if (!checked) selected = selected.filter(function (m) { return m !== model; });
      let defaultModel = f.default_model || "";
      if (selected.length && selected.indexOf(defaultModel) < 0) defaultModel = selected[0];
      if (!selected.length) defaultModel = "";
      patch(p.id, { selected: selected, default_model: defaultModel });
    }

    async function save(p) {
      setBusy("save:" + p.id); setError(""); setNotice("");
      try {
        await persist(p, true);
        setNotice("Saved. Selected models are synced to Hermes native configuration.");
        await load();
      } catch (e) { setError(errText(e)); }
      finally { setBusy(""); }
    }

    if (loading && !data) return h(LoadingBlock, null, "Loading provider models…");
    const items = ((data && data.items) || []).filter(function (p) { return p.id === "custom"; });
    return h("div", { className: "hx-page hx-stack" },
      h("div", { className: "hx-section-head" },
        h("div", null, h("h1", null, "Provider Models"), h("div", { className: "hx-muted" }, "Enter URL and key, load available models, search/select them, and sync the selection to Hermes.")),
        h("input", { value: profile, onChange: function (e) { setProfile(e.target.value.trim().toLowerCase() || "default"); } })
      ),
      error ? h(Card, { className: "hx-warning-card" }, error) : null,
      notice ? h(Card, null, notice) : null,
      items.map(function (p) {
        const f = forms[p.id] || {};
        const q = String(queries[p.id] || "").trim().toLowerCase();
        const visible = (f.available || []).filter(function (m) { return !q || m.toLowerCase().includes(q); });
        return h(Card, { key: p.id },
          h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, p.label), h("div", { className: "hx-muted" }, "OpenAI-compatible provider")), h(Pill, { kind: p.configured ? "ok" : "paused" }, p.configured ? "configured" : "not configured")),
          Field("Provider name", h("input", { value: f.custom_name || "", onChange: function (e) { patch(p.id, { custom_name: e.target.value }); } })),
          Field("API key", h("input", { type: "password", autoComplete: "off", value: f.key_value || "", placeholder: p.has_api_key ? "Stored — enter only to replace" : "Enter API key", onChange: function (e) { patch(p.id, { key_value: e.target.value }); } })),
          Field("Base URL", h("input", { value: f.base_url || "", placeholder: "https://provider.example/v1", onChange: function (e) { patch(p.id, { base_url: e.target.value, available: [] }); } })),
          h("div", { className: "hx-actions" }, h("button", { type: "button", className: "hx-button secondary", disabled: busy === "discover:" + p.id || !f.base_url, onClick: function () { discover(p); } }, busy === "discover:" + p.id ? "Loading…" : "Load models")),
          (f.available || []).length ? h("div", { className: "hx-stack" },
            h("input", { type: "search", placeholder: "Search models…", value: queries[p.id] || "", onChange: function (e) { setQueries(Object.assign({}, queries, { [p.id]: e.target.value })); } }),
            h("div", { style: { maxHeight: "260px", overflow: "auto" } }, visible.map(function (model) {
              return h("label", { className: "hx-inline-check", key: model }, h("input", { type: "checkbox", checked: (f.selected || []).indexOf(model) >= 0, onChange: function (e) { toggle(p, model, e.target.checked); } }), model);
            })),
            (f.selected || []).length ? Field("Default model", h("select", { value: f.default_model || f.selected[0], onChange: function (e) { patch(p.id, { default_model: e.target.value }); } }, f.selected.map(function (model) { return h("option", { key: model, value: model }, model); }))) : null
          ) : null,
          h("div", { className: "hx-actions" }, h("button", { type: "button", className: "hx-button", disabled: busy === "save:" + p.id, onClick: function () { save(p); } }, busy === "save:" + p.id ? "Saving…" : "Save models"))
        );
      })
    );
  }

  function providerRuntimeId(provider) {
    return String(provider.runtime_provider_id || provider.custom_name || provider.id || "").trim();
  }

  function providerDisplayName(provider) {
    return String(provider.custom_name || provider.label || provider.runtime_provider_id || provider.id || "").trim();
  }

  function setControlledInputValue(input, value) {
    if (!input || input.value === value) return;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (setter && setter.set) setter.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function AgentProviderModelSelectOverlay(props) {
    useEffect(function () {
      if (!props.enabled) return undefined;

      let stopped = false;
      let providers = [];
      let loadingPromise = null;
      let activeDialog = null;
      let providerInput = null;
      let modelInput = null;
      let providerSelect = null;
      let modelSelect = null;
      let initialized = false;

      function loadProviders() {
        if (loadingPromise) return loadingPromise;
        loadingPromise = request("/providers?profile=default").then(function (result) {
          providers = ((result && result.items) || []).filter(function (p) {
            const id = providerRuntimeId(p);
            const models = Array.isArray(p.models) ? p.models.filter(Boolean) : [];
            return Boolean(id && p.configured && models.length);
          });
          return providers;
        }).catch(function () {
          providers = [];
          return providers;
        });
        return loadingPromise;
      }

      function findField(dialog, name) {
        return Array.from(dialog.querySelectorAll("label")).find(function (label) {
          const span = label.querySelector(":scope > span");
          return span && span.textContent.trim() === name;
        }) || null;
      }

      function addOption(select, value, label) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      }

      function clearSelect(select) {
        while (select && select.firstChild) select.removeChild(select.firstChild);
      }

      function removeOverlay() {
        if (providerInput) providerInput.style.visibility = "";
        if (modelInput) modelInput.style.visibility = "";
        if (providerSelect && providerSelect.parentNode) providerSelect.parentNode.removeChild(providerSelect);
        if (modelSelect && modelSelect.parentNode) modelSelect.parentNode.removeChild(modelSelect);
        activeDialog = null;
        providerInput = null;
        modelInput = null;
        providerSelect = null;
        modelSelect = null;
        initialized = false;
      }

      function styleOverlay(select, input) {
        const rect = input.getBoundingClientRect();
        select.style.position = "fixed";
        select.style.left = rect.left + "px";
        select.style.top = rect.top + "px";
        select.style.width = rect.width + "px";
        select.style.height = rect.height + "px";
        select.style.boxSizing = "border-box";
        select.style.zIndex = "2147483000";
        select.style.margin = "0";
      }

      function providerForValue(value) {
        return providers.find(function (p) { return providerRuntimeId(p) === value; }) || null;
      }

      function rebuildModels(preferred, commitDefault) {
        if (!modelSelect) return;
        const provider = providerForValue(providerSelect ? providerSelect.value : "");
        clearSelect(modelSelect);
        if (!provider) {
          addOption(modelSelect, "", "Select provider first");
          modelSelect.value = "";
          if (commitDefault) setControlledInputValue(modelInput, "");
          return;
        }
        const models = Array.isArray(provider.models) ? provider.models.filter(Boolean) : [];
        addOption(modelSelect, "", models.length ? "Select model" : "No saved models");
        models.forEach(function (model) { addOption(modelSelect, model, model); });
        let next = preferred && models.indexOf(preferred) >= 0 ? preferred : "";
        if (!next && provider.default_model && models.indexOf(provider.default_model) >= 0) next = provider.default_model;
        if (!next && models.length === 1) next = models[0];
        modelSelect.value = next;
        if (commitDefault) setControlledInputValue(modelInput, next);
      }

      function createOverlay(dialog, pInput, mInput) {
        activeDialog = dialog;
        providerInput = pInput;
        modelInput = mInput;
        providerSelect = document.createElement("select");
        modelSelect = document.createElement("select");
        providerSelect.setAttribute("aria-label", "Provider");
        modelSelect.setAttribute("aria-label", "Model");
        providerSelect.setAttribute("data-hx-agent-provider-overlay", "1");
        modelSelect.setAttribute("data-hx-agent-model-overlay", "1");
        document.body.appendChild(providerSelect);
        document.body.appendChild(modelSelect);
        providerInput.style.visibility = "hidden";
        modelInput.style.visibility = "hidden";

        providerSelect.addEventListener("change", function () {
          setControlledInputValue(providerInput, providerSelect.value);
          rebuildModels("", true);
        });
        modelSelect.addEventListener("change", function () {
          setControlledInputValue(modelInput, modelSelect.value);
        });

        clearSelect(providerSelect);
        addOption(providerSelect, "", providers.length ? "Select provider" : "No configured providers");
        providers.forEach(function (provider) {
          addOption(providerSelect, providerRuntimeId(provider), providerDisplayName(provider));
        });

        let initialProvider = providerInput.value;
        if (!providerForValue(initialProvider)) initialProvider = providers.length === 1 ? providerRuntimeId(providers[0]) : "";
        providerSelect.value = initialProvider;
        if (!providerInput.value && initialProvider) setControlledInputValue(providerInput, initialProvider);
        rebuildModels(modelInput.value, !modelInput.value);
        initialized = true;
      }

      function tick() {
        if (stopped) return;
        const dialog = document.querySelector('.hx-dialog[aria-label="Create Agent"]');
        if (!dialog) {
          if (activeDialog) removeOverlay();
          return;
        }
        const providerField = findField(dialog, "Provider");
        const modelField = findField(dialog, "Model");
        const pInput = providerField ? providerField.querySelector("input") : null;
        const mInput = modelField ? modelField.querySelector("input") : null;
        if (!pInput || !mInput) return;

        loadProviders().then(function () {
          if (stopped || !document.contains(dialog)) return;
          if (activeDialog !== dialog || providerInput !== pInput || modelInput !== mInput || !providerSelect || !modelSelect) {
            removeOverlay();
            createOverlay(dialog, pInput, mInput);
          }
          if (!initialized) return;
          styleOverlay(providerSelect, providerInput);
          styleOverlay(modelSelect, modelInput);

          if (providerSelect.value !== providerInput.value && providerForValue(providerInput.value)) {
            providerSelect.value = providerInput.value;
            rebuildModels(modelInput.value, false);
          }
          if (modelSelect.value !== modelInput.value) {
            const provider = providerForValue(providerSelect.value);
            const models = provider && Array.isArray(provider.models) ? provider.models : [];
            if (models.indexOf(modelInput.value) >= 0 || !modelInput.value) modelSelect.value = modelInput.value;
          }
        });
      }

      const timer = window.setInterval(tick, 80);
      tick();
      return function () {
        stopped = true;
        window.clearInterval(timer);
        removeOverlay();
      };
    }, [props.enabled]);
    return null;
  }

  function EnhancedApp() {
    const [showModels, setShowModels] = useState(false);
    return h("div", null,
      h(AgentProviderModelSelectOverlay, { enabled: !showModels }),
      h("div", { className: "hx-page" }, h("div", { className: "hx-tabs" },
        h("button", { className: "hx-tab " + (!showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(false); } }, "Control Center"),
        h("button", { className: "hx-tab " + (showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(true); } }, "Provider Models")
      )),
      showModels ? h(ProviderModelsPage) : h(PreviousApp)
    );
  }

  HX.ManagementApp = EnhancedApp;
})();

(function () {
  "use strict";

  const composingFields = new WeakSet();

  function createAgentDialog() {
    return document.querySelector('.hx-dialog[aria-label="Create Agent"]');
  }

  function fieldKey(el) {
    if (!el || !el.closest) return "";
    const label = el.closest("label");
    if (!label) return "";
    const span = label.querySelector(":scope > span");
    return span ? String(span.textContent || "").trim() : "";
  }

  function isCreateAgentTextField(el) {
    if (!el || !el.closest) return false;
    const dialog = el.closest('.hx-dialog[aria-label="Create Agent"]');
    if (!dialog) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName !== "INPUT") return false;
    const type = String(el.type || "text").toLowerCase();
    return type === "text" || type === "search" || type === "url" || type === "email" || type === "password";
  }

  function findCurrentField(key, original) {
    if (original && document.contains(original)) return original;
    const dialog = createAgentDialog();
    if (!dialog || !key) return null;
    const labels = Array.from(dialog.querySelectorAll("label"));
    const label = labels.find(function (item) {
      const span = item.querySelector(":scope > span");
      return span && String(span.textContent || "").trim() === key;
    });
    if (!label) return null;
    return label.querySelector("input,textarea");
  }

  function restoreField(key, original, start, end) {
    const field = findCurrentField(key, original);
    if (!field || composingFields.has(field)) return;
    const active = document.activeElement;
    if (active === field) return;
    if (active && isCreateAgentTextField(active)) return;
    try {
      field.focus({ preventScroll: true });
      if (typeof field.setSelectionRange === "function" && start != null && end != null) {
        const length = String(field.value || "").length;
        field.setSelectionRange(Math.min(start, length), Math.min(end, length));
      }
    } catch (_) {}
  }

  // Chinese/Japanese/Korean IMEs emit intermediate input events while the
  // composition candidate is still active. The Create Agent modal is currently
  // remounted after controlled-field state updates, which destroys the native
  // IME composition session. Keep those intermediate events away from React and
  // commit the final DOM value once composition ends.
  document.addEventListener("compositionstart", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    composingFields.add(field);
  }, true);

  document.addEventListener("compositionend", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    composingFields.delete(field);

    // Some Chromium/IME combinations emit the final input before compositionend;
    // others emit it afterwards. Dispatch one normal input in the next task so
    // React always receives the committed text exactly after composition ends.
    window.setTimeout(function () {
      if (!document.contains(field)) return;
      try {
        field.dispatchEvent(new Event("input", { bubbles: true }));
      } catch (_) {}
    }, 0);
  }, true);

  document.addEventListener("input", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;

    if (event.isComposing || composingFields.has(field)) {
      event.stopImmediatePropagation();
      return;
    }

    const key = fieldKey(field);
    const start = typeof field.selectionStart === "number" ? field.selectionStart : null;
    const end = typeof field.selectionEnd === "number" ? field.selectionEnd : null;

    window.requestAnimationFrame(function () {
      restoreField(key, field, start, end);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 0);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 40);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 140);
    });
  }, true);
})();

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.request) return;

  let resources = [];
  let agents = [];
  let loading = false;

  function resourceCards() {
    return Array.from(document.querySelectorAll(".hx-agent-grid > *"));
  }

  function refreshResourcePage() {
    const buttons = Array.from(document.querySelectorAll("button"));
    const refresh = buttons.find(function (button) {
      return String(button.textContent || "").trim() === "Refresh";
    });
    if (refresh && !refresh.disabled) refresh.click();
  }

  async function importToCdp(row, agent, status) {
    if (!agent) return;
    const message =
      "This will briefly close the selected " + String(row.app || "browser") +
      " so its logged-in profile can be copied safely. Your normal browser is then reopened, and an Agent CDP copy is launched. Continue?";
    if (!window.confirm(message)) return;
    status.textContent = "Importing profile and enabling CDP…";
    try {
      const result = await HX.request(
        "/resources/browser/" + encodeURIComponent(row.id) + "/import-cdp",
        {
          method: "POST",
          body: JSON.stringify({ agent: agent, start_url: "https://wx.qq.com/" })
        }
      );
      const port = result && result.launch && result.launch.debug_port;
      status.textContent = "Ready" + (port ? " · CDP " + port : "") + " · bound to " + agent;
      setTimeout(refreshResourcePage, 500);
    } catch (error) {
      status.textContent = HX.errText ? HX.errText(error) : String(error);
    }
  }

  function enhance() {
    if (!resources.length) return;
    const cards = resourceCards();
    resources.forEach(function (row) {
      if (!row || row.kind !== "browser" || row.attachable || !row.online) return;
      const card = cards.find(function (candidate) {
        return String(candidate.textContent || "").indexOf(String(row.id || "")) >= 0;
      });
      if (!card || card.querySelector('[data-hcc-cdp-import="' + row.id + '"]')) return;

      const wrap = document.createElement("div");
      wrap.setAttribute("data-hcc-cdp-import", row.id);
      wrap.className = "hx-stack";
      wrap.style.marginTop = "12px";
      wrap.style.paddingTop = "12px";
      wrap.style.borderTop = "1px dashed var(--hx-border, rgba(127,127,127,.35))";

      const note = document.createElement("div");
      note.className = "hx-muted";
      note.textContent = "Use this already-open browser session as CDP: its profile is copied into an Agent-owned CDP profile, then the original browser is reopened.";
      wrap.appendChild(note);

      const actions = document.createElement("div");
      actions.className = "hx-actions";

      const select = document.createElement("select");
      agents.forEach(function (agent) {
        const option = document.createElement("option");
        option.value = agent;
        option.textContent = agent;
        select.appendChild(option);
      });
      actions.appendChild(select);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "hx-button";
      button.textContent = "Import Session → CDP";
      button.disabled = !agents.length;
      actions.appendChild(button);

      const status = document.createElement("span");
      status.className = "hx-muted";
      actions.appendChild(status);

      button.addEventListener("click", async function () {
        if (button.disabled) return;
        button.disabled = true;
        try {
          await importToCdp(row, select.value, status);
        } finally {
          button.disabled = !agents.length;
        }
      });

      wrap.appendChild(actions);
      card.appendChild(wrap);
    });
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const data = await HX.request("/resources?refresh=false");
      resources = (data && data.items) || [];
      agents = (data && data.agents) || [];
      enhance();
    } catch (_) {
      // The main Resources page owns visible load errors.
    } finally {
      loading = false;
    }
  }

  const observer = new MutationObserver(function () {
    const text = String(document.body && document.body.textContent || "");
    if (text.indexOf("Browser instances") >= 0 && text.indexOf("Resources") >= 0) {
      if (!resources.length) load(); else enhance();
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(load, 700);
})();

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

(function () {
  "use strict";
  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || !HX.CanonicalManagementApp || !window.__HERMES_PLUGINS__) {
    throw new Error("Hermes Control Center canonical UI is not initialized.");
  }
  window.__HERMES_PLUGINS__.register("hermes-extensions", HX.CanonicalManagementApp);
})();

(function () {
  "use strict";

  const HX = window.__HERMES_EXTENSIONS_UI__;
  if (!HX || typeof HX.request !== "function") return;

  const BADGE_ID = "hx-control-center-version-badge";
  let loading = false;
  let lastCheck = 0;

  function ensureStyles() {
    if (document.getElementById("hx-version-badge-styles")) return;
    const style = document.createElement("style");
    style.id = "hx-version-badge-styles";
    style.textContent = [
      "#" + BADGE_ID + "{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-right:4px}",
      "#" + BADGE_ID + " .hx-version-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--border,#29433f);border-radius:8px;padding:7px 9px;background:#102b27;color:inherit;font-size:12px;line-height:1.15;white-space:nowrap}",
      "#" + BADGE_ID + " .hx-version-chip strong{font-weight:800}",
      "#" + BADGE_ID + " .hx-version-state{font-weight:800}",
      "#" + BADGE_ID + " .hx-version-state.ok{color:#7fe0b3}",
      "#" + BADGE_ID + " .hx-version-state.update{color:#ffd199}",
      "#" + BADGE_ID + " .hx-version-state.unknown{opacity:.72}",
      "@media(max-width:900px){#" + BADGE_ID + "{width:100%;margin:0 0 8px 0}}"
    ].join("");
    document.head.appendChild(style);
  }

  function versionText(value) {
    const text = String(value || "unknown");
    return text === "unknown" ? text : (text.charAt(0).toLowerCase() === "v" ? text : "v" + text);
  }

  function render(data) {
    const host = document.getElementById(BADGE_ID);
    if (!host) return;
    const installed = versionText(data && data.installed);
    const latest = data && data.latest ? versionText(data.latest) : "unknown";
    const update = Boolean(data && data.update_available);
    const knownLatest = Boolean(data && data.latest);
    const stateText = update ? "Update available" : (knownLatest ? "Up to date" : "Latest unknown");
    const stateClass = update ? "update" : (knownLatest ? "ok" : "unknown");
    host.innerHTML = "";

    const installedChip = document.createElement("span");
    installedChip.className = "hx-version-chip";
    installedChip.innerHTML = "<span>Installed:</span><strong></strong>";
    installedChip.querySelector("strong").textContent = installed;

    const latestChip = document.createElement("span");
    latestChip.className = "hx-version-chip";
    latestChip.innerHTML = "<span>Latest:</span><strong></strong>";
    latestChip.querySelector("strong").textContent = latest;

    const stateChip = document.createElement("span");
    stateChip.className = "hx-version-chip";
    const state = document.createElement("span");
    state.className = "hx-version-state " + stateClass;
    state.textContent = stateText;
    stateChip.appendChild(state);

    host.appendChild(installedChip);
    host.appendChild(latestChip);
    host.appendChild(stateChip);
  }

  async function refreshVersion(force) {
    const now = Date.now();
    if (loading || (!force && now - lastCheck < 30000)) return;
    loading = true;
    lastCheck = now;
    try {
      const data = await HX.request("/version-status" + (force ? "?refresh=true" : ""));
      render(data || {});
    } catch (_) {
      render({ installed: "unknown", latest: null, update_available: false });
    } finally {
      loading = false;
    }
  }

  function attach() {
    ensureStyles();
    const header = document.querySelector(".hx-header");
    if (!header) return false;
    const actions = header.querySelector(".hx-actions");
    if (!actions) return false;

    let badge = document.getElementById(BADGE_ID);
    if (!badge) {
      badge = document.createElement("div");
      badge.id = BADGE_ID;
      badge.setAttribute("aria-label", "Hermes Control Center version status");
      actions.insertBefore(badge, actions.firstChild);
      render({ installed: "…", latest: null, update_available: false });
      refreshVersion(true);
    }

    const refreshButton = Array.from(actions.querySelectorAll("button")).find(function (button) {
      return /refresh/i.test(String(button.textContent || ""));
    });
    if (refreshButton && !refreshButton.dataset.hxVersionHook) {
      refreshButton.dataset.hxVersionHook = "1";
      refreshButton.addEventListener("click", function () {
        window.setTimeout(function () { refreshVersion(true); }, 150);
      });
    }
    return true;
  }

  const observer = new MutationObserver(function () { attach(); });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  attach();
  window.setInterval(function () {
    if (document.visibilityState === "visible") {
      attach();
      refreshVersion(false);
    }
  }, 30000);
})();
