(function () {
  "use strict";

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
    if (!field) return;
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

  document.addEventListener("input", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    const key = fieldKey(field);
    const start = typeof field.selectionStart === "number" ? field.selectionStart : null;
    const end = typeof field.selectionEnd === "number" ? field.selectionEnd : null;

    // AgentModal is currently declared inside ManagementApp, so every form state
    // update can remount the dialog tree. Remember the logical field (label), not
    // only the old DOM node, and refocus its replacement after React commits.
    window.requestAnimationFrame(function () {
      restoreField(key, field, start, end);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 0);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 40);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 140);
    });
  }, true);
})();
