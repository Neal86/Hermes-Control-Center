(function () {
  "use strict";

  function cleanup() {
    const root = document.querySelector(".hx-page") || document;
    root.querySelectorAll("button").forEach(function (btn) {
      if ((btn.textContent || "").trim() === "WeChat") btn.style.display = "none";
    });
    root.querySelectorAll(".hx-muted").forEach(function (node) {
      const text = (node.textContent || "").trim();
      if (text === "Agents · Projects · Tasks · Windows WeChat") node.textContent = "Agents · Projects · Tasks";
    });
    root.querySelectorAll(".hx-section-head h2").forEach(function (title) {
      if ((title.textContent || "").trim() === "WeChat Desktop") {
        const card = title.closest(".hx-card") || title.parentElement;
        if (card) card.style.display = "none";
      }
    });
    enhanceCustomProvider();
  }

  function textOfLabel(card, name) {
    const labels = Array.from(card.querySelectorAll("label"));
    return labels.find(function (label) { return (label.textContent || "").trim().startsWith(name); });
  }

  function inputFromLabel(card, name) {
    const label = textOfLabel(card, name);
    return label ? label.querySelector("input,select,textarea") : null;
  }

  function getCustomCard() {
    return Array.from(document.querySelectorAll(".hx-card")).find(function (card) {
      return /Custom OpenAI-compatible Provider|OpenAI-compatible Provider/i.test(card.textContent || "");
    }) || null;
  }

  function getProfile() {
    const heading = Array.from(document.querySelectorAll("h1")).find(function (node) { return (node.textContent || "").trim() === "Providers"; });
    if (!heading) return "default";
    const section = heading.closest(".hx-page") || document;
    const values = Array.from(section.querySelectorAll("input")).map(function (input) { return input.value; });
    const candidate = values.find(function (value) { return /^[a-z0-9][a-z0-9_-]{0,63}$/.test(String(value || "")); });
    return candidate || "default";
  }

  async function api(path, options) {
    const HX = window.__HERMES_EXTENSIONS_UI__;
    if (!HX || typeof HX.request !== "function") throw new Error("Hermes plugin API unavailable");
    return HX.request(path, options || {});
  }

  function renderModels(card, state) {
    let box = card.querySelector("[data-hx-model-discovery]");
    if (!box) {
      box = document.createElement("div");
      box.dataset.hxModelDiscovery = "1";
      box.className = "hx-stack";
      const actions = card.querySelector(".hx-actions");
      card.insertBefore(box, actions || null);
    }
    box.innerHTML = "";

    const row = document.createElement("div");
    row.className = "hx-actions";
    const load = document.createElement("button");
    load.type = "button";
    load.className = "hx-button secondary";
    load.textContent = state.loading ? "Loading models…" : "Load models";
    load.disabled = Boolean(state.loading);
    row.appendChild(load);
    const status = document.createElement("span");
    status.className = "hx-muted";
    status.textContent = state.models.length ? state.models.length + " available · " + state.selected.length + " selected" : "Save URL/key, then load available models";
    row.appendChild(status);
    box.appendChild(row);

    if (state.error) {
      const err = document.createElement("div");
      err.className = "hx-warning-card";
      err.textContent = state.error;
      box.appendChild(err);
    }

    if (state.models.length) {
      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Search models…";
      search.value = state.query;
      box.appendChild(search);

      const list = document.createElement("div");
      list.style.maxHeight = "260px";
      list.style.overflow = "auto";
      list.className = "hx-stack";
      state.models.filter(function (model) {
        return !state.query || model.toLowerCase().includes(state.query.toLowerCase());
      }).forEach(function (model) {
        const label = document.createElement("label");
        label.className = "hx-inline-check";
        const check = document.createElement("input");
        check.type = "checkbox";
        check.checked = state.selected.indexOf(model) >= 0;
        check.addEventListener("change", function () {
          if (check.checked && state.selected.indexOf(model) < 0) state.selected.push(model);
          if (!check.checked) state.selected = state.selected.filter(function (value) { return value !== model; });
          if (state.selected.length && state.selected.indexOf(state.defaultModel) < 0) state.defaultModel = state.selected[0];
          if (!state.selected.length) state.defaultModel = "";
          renderModels(card, state);
        });
        label.appendChild(check);
        label.appendChild(document.createTextNode(" " + model));
        list.appendChild(label);
      });
      box.appendChild(list);

      if (state.selected.length) {
        const defaultWrap = document.createElement("label");
        defaultWrap.className = "hx-field";
        const caption = document.createElement("span");
        caption.textContent = "Default model";
        defaultWrap.appendChild(caption);
        const select = document.createElement("select");
        state.selected.forEach(function (model) {
          const option = document.createElement("option");
          option.value = model;
          option.textContent = model;
          option.selected = model === state.defaultModel;
          select.appendChild(option);
        });
        select.addEventListener("change", function () { state.defaultModel = select.value; });
        defaultWrap.appendChild(select);
        box.appendChild(defaultWrap);
      }

      const saveModels = document.createElement("button");
      saveModels.type = "button";
      saveModels.className = "hx-button";
      saveModels.textContent = "Save selected models";
      saveModels.addEventListener("click", async function () {
        try {
          saveModels.disabled = true;
          const body = { models: state.selected.slice(), default_model: state.defaultModel || "" };
          await api("/providers/custom?profile=" + encodeURIComponent(getProfile()), { method: "PUT", body: JSON.stringify(body) });
          state.error = "";
          status.textContent = "Saved to Hermes configuration";
        } catch (e) {
          state.error = String(e && e.message ? e.message : e);
          renderModels(card, state);
        } finally {
          saveModels.disabled = false;
        }
      });
      box.appendChild(saveModels);

      search.addEventListener("input", function () {
        state.query = search.value;
        renderModels(card, state);
        const next = card.querySelector("[data-hx-model-discovery] input[type=search]");
        if (next) { next.focus(); next.setSelectionRange(state.query.length, state.query.length); }
      });
    }

    load.addEventListener("click", async function () {
      try {
        state.loading = true;
        state.error = "";
        renderModels(card, state);
        const base = inputFromLabel(card, "Base URL");
        const secret = inputFromLabel(card, "API key");
        const providerName = inputFromLabel(card, "Provider name");
        const saveBody = { base_url: base ? base.value : "", custom_name: providerName ? providerName.value : "" };
        if (secret && secret.value) saveBody["api" + "_key"] = secret.value;
        await api("/providers/custom?profile=" + encodeURIComponent(getProfile()), { method: "PUT", body: JSON.stringify(saveBody) });
        const result = await api("/providers/discover-models", { method: "POST", body: JSON.stringify({ provider: "custom", profile: getProfile() }) });
        state.models = Array.isArray(result && result.items) ? result.items : [];
        state.selected = state.selected.filter(function (model) { return state.models.indexOf(model) >= 0; });
        if (state.selected.length && state.selected.indexOf(state.defaultModel) < 0) state.defaultModel = state.selected[0];
      } catch (e) {
        state.error = String(e && e.message ? e.message : e);
      } finally {
        state.loading = false;
        renderModels(card, state);
      }
    });
  }

  function enhanceCustomProvider() {
    const card = getCustomCard();
    if (!card || card.dataset.hxModelsEnhanced === "1") return;
    card.dataset.hxModelsEnhanced = "1";
    const currentDefault = inputFromLabel(card, "Default model");
    const initial = currentDefault && currentDefault.value ? [currentDefault.value] : [];
    const state = { models: initial.slice(), selected: initial.slice(), defaultModel: initial[0] || "", query: "", loading: false, error: "" };
    renderModels(card, state);
  }

  const observer = new MutationObserver(cleanup);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", cleanup);
  else cleanup();
})();
