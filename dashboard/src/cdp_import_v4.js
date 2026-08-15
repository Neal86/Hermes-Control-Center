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
