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
    const load = useCallback(async function (refresh) {
      setLoading(true); setError("");
      try { setData(await request("/resources?refresh=" + (refresh ? "true" : "false"))); }
      catch (e) { setError(errText(e)); }
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
