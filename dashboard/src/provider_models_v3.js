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
