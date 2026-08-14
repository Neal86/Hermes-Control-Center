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
    if (!input) return;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (setter && setter.set) setter.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function AgentProviderModelSelectBridge(props) {
    useEffect(function () {
      if (!props.enabled) return undefined;

      let stopped = false;
      let providerRows = [];
      let providerPromise = null;

      function configuredProviders(rows) {
        return (rows || []).filter(function (p) {
          const id = providerRuntimeId(p);
          const models = Array.isArray(p.models) ? p.models.filter(Boolean) : [];
          return Boolean(id && p.configured && models.length);
        });
      }

      function loadProviders() {
        if (providerPromise) return providerPromise;
        providerPromise = request("/providers?profile=default").then(function (result) {
          providerRows = configuredProviders((result && result.items) || []);
          return providerRows;
        }).catch(function () {
          providerRows = [];
          return providerRows;
        });
        return providerPromise;
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

      function enhanceDialog() {
        if (stopped) return;
        const dialog = document.querySelector('.hx-dialog[aria-label="Create Agent"]');
        if (!dialog) return;

        const providerField = findField(dialog, "Provider");
        const modelField = findField(dialog, "Model");
        if (!providerField || !modelField) return;

        const providerInput = providerField.querySelector("input");
        const modelInput = modelField.querySelector("input");
        if (!providerInput || !modelInput) return;

        loadProviders().then(function (providers) {
          if (stopped || !document.contains(dialog)) return;

          const oldProviderSelect = providerField.querySelector('select[data-hx-agent-provider="1"]');
          const oldModelSelect = modelField.querySelector('select[data-hx-agent-model="1"]');
          if (oldProviderSelect && oldModelSelect) return;

          if (oldProviderSelect) oldProviderSelect.remove();
          if (oldModelSelect) oldModelSelect.remove();

          const providerSelect = document.createElement("select");
          providerSelect.setAttribute("data-hx-agent-provider", "1");
          providerSelect.setAttribute("aria-label", "Provider");
          addOption(providerSelect, "", providers.length ? "Select provider" : "No configured providers");

          providers.forEach(function (provider) {
            const value = providerRuntimeId(provider);
            addOption(providerSelect, value, providerDisplayName(provider));
          });

          const modelSelect = document.createElement("select");
          modelSelect.setAttribute("data-hx-agent-model", "1");
          modelSelect.setAttribute("aria-label", "Model");

          providerInput.style.display = "none";
          modelInput.style.display = "none";
          providerField.insertBefore(providerSelect, providerInput);
          modelField.insertBefore(modelSelect, modelInput);

          function selectedProvider() {
            return providers.find(function (p) { return providerRuntimeId(p) === providerSelect.value; }) || null;
          }

          function rebuildModels(preferred) {
            const provider = selectedProvider();
            while (modelSelect.firstChild) modelSelect.removeChild(modelSelect.firstChild);
            if (!provider) {
              addOption(modelSelect, "", "Select provider first");
              modelSelect.value = "";
              setControlledInputValue(modelInput, "");
              return;
            }

            const models = Array.isArray(provider.models) ? provider.models.filter(Boolean) : [];
            addOption(modelSelect, "", models.length ? "Select model" : "No saved models");
            models.forEach(function (model) { addOption(modelSelect, model, model); });

            let next = preferred && models.indexOf(preferred) >= 0 ? preferred : "";
            if (!next && provider.default_model && models.indexOf(provider.default_model) >= 0) next = provider.default_model;
            if (!next && models.length === 1) next = models[0];
            modelSelect.value = next;
            setControlledInputValue(modelInput, next);
          }

          let initialProvider = providerInput.value;
          if (!providers.some(function (p) { return providerRuntimeId(p) === initialProvider; })) {
            initialProvider = providers.length === 1 ? providerRuntimeId(providers[0]) : "";
          }
          providerSelect.value = initialProvider;
          setControlledInputValue(providerInput, initialProvider);
          rebuildModels(modelInput.value);

          providerSelect.addEventListener("change", function () {
            setControlledInputValue(providerInput, providerSelect.value);
            rebuildModels("");
          });
          modelSelect.addEventListener("change", function () {
            setControlledInputValue(modelInput, modelSelect.value);
          });
        });
      }

      const observer = new MutationObserver(enhanceDialog);
      observer.observe(document.body, { childList: true, subtree: true });
      enhanceDialog();

      return function () {
        stopped = true;
        observer.disconnect();
      };
    }, [props.enabled]);

    return null;
  }

  function EnhancedApp() {
    const [showModels, setShowModels] = useState(false);
    return h("div", null,
      h(AgentProviderModelSelectBridge, { enabled: !showModels }),
      h("div", { className: "hx-page" }, h("div", { className: "hx-tabs" },
        h("button", { className: "hx-tab " + (!showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(false); } }, "Control Center"),
        h("button", { className: "hx-tab " + (showModels ? "active" : ""), type: "button", onClick: function () { setShowModels(true); } }, "Provider Models")
      )),
      showModels ? h(ProviderModelsPage) : h(PreviousApp)
    );
  }

  HX.ManagementApp = EnhancedApp;
})();