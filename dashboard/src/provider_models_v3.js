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

  function EnhancedApp() {
    const [showModels, setShowModels] = useState(false);
    return h("div", null,
      h("div", { className: "hx-page" }, h("div", { className: "hx-tabs" },
        h("button", { className: "hx-tab " + (!showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(false); } }, "Control Center"),
        h("button", { className: "hx-tab " + (showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(true); } }, "Provider Models")
      )),
      showModels ? h(ProviderModelsPage) : h(PreviousApp)
    );
  }

  HX.ManagementApp = EnhancedApp;
})();
