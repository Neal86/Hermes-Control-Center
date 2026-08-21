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
          const actionKey = "agent:" + a.name + ":" + (running ? "gateway_stop" : "gateway_start");
          return h(Card, { key: a.name },
            h("div", { className: "hx-agent-head" }, h("div", null, h("h2", null, a.display_name || a.name), h("div", { className: "hx-muted" }, a.name)), a.is_default ? h(Pill, { kind: "ok" }, "default") : h(Pill, { kind: running ? "ok" : "paused" }, a.gateway || "stopped")),
            h("p", { className: "hx-description" }, a.description || "No role description"),
            h("div", { className: "hx-kv" }, h("span", null, "Model"), h("strong", null, a.model || "not configured"), h("span", null, "Provider"), h("strong", null, a.provider || "—"), h("span", null, "Workspace"), h("strong", null, a.workspace || "—")),
            h("div", { className: "hx-actions" },
              h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { openAgent(a.name); } }, "Manage"),
              !a.is_default ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { agentAction(a, "use", null, "Default Agent changed."); } }, "Set default") : null,
              h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { agentAction(a, running ? "gateway_stop" : "gateway_start", null, running ? "Gateway stopped." : "Gateway started."); } }, busyIs(actionKey) ? "Working…" : running ? "Stop" : "Start"),
              running ? h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy), onClick: function () { restartAgent(a); } }, "Restart") : null
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
            h("button", { className: "hx-button secondary", type: "button", disabled: Boolean(busy) || agentDirty, onClick: function () { agentAction(a, running ? "gateway_stop" : "gateway_start", null, running ? "Gateway stopped." : "Gateway started."); } }, running ? "Stop" : "Start"),
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
