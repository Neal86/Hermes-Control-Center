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
