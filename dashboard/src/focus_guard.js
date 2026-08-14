(function () {
  "use strict";

  function isCreateAgentTextField(el) {
    if (!el || !el.closest) return false;
    const dialog = el.closest('.hx-dialog[aria-label="Create Agent"]');
    if (!dialog) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName !== "INPUT") return false;
    const type = String(el.type || "text").toLowerCase();
    return type === "text" || type === "search" || type === "url" || type === "email" || type === "password";
  }

  function restoreField(field, start, end) {
    if (!field || !document.contains(field)) return;
    const dialog = field.closest('.hx-dialog[aria-label="Create Agent"]');
    if (!dialog) return;
    const active = document.activeElement;
    if (active === field) return;
    if (active && isCreateAgentTextField(active)) return;
    try {
      field.focus({ preventScroll: true });
      if (typeof field.setSelectionRange === "function" && start != null && end != null) {
        field.setSelectionRange(start, end);
      }
    } catch (_) {}
  }

  document.addEventListener("input", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    const start = typeof field.selectionStart === "number" ? field.selectionStart : null;
    const end = typeof field.selectionEnd === "number" ? field.selectionEnd : null;

    // Provider/Model enhancement may update React state asynchronously and
    // accidentally move focus to a dialog action button. Restore the field
    // after React and overlay work have both had a chance to run.
    window.requestAnimationFrame(function () {
      restoreField(field, start, end);
      window.setTimeout(function () { restoreField(field, start, end); }, 0);
      window.setTimeout(function () { restoreField(field, start, end); }, 120);
    });
  }, true);
})();
