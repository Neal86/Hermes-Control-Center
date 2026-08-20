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
