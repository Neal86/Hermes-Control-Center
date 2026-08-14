(function () {
  "use strict";

  const composingFields = new WeakSet();

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
    if (!field || composingFields.has(field)) return;
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

  // Chinese/Japanese/Korean IMEs emit intermediate input events while the
  // composition candidate is still active. The Create Agent modal is currently
  // remounted after controlled-field state updates, which destroys the native
  // IME composition session. Keep those intermediate events away from React and
  // commit the final DOM value once composition ends.
  document.addEventListener("compositionstart", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    composingFields.add(field);
  }, true);

  document.addEventListener("compositionend", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;
    composingFields.delete(field);

    // Some Chromium/IME combinations emit the final input before compositionend;
    // others emit it afterwards. Dispatch one normal input in the next task so
    // React always receives the committed text exactly after composition ends.
    window.setTimeout(function () {
      if (!document.contains(field)) return;
      try {
        field.dispatchEvent(new Event("input", { bubbles: true }));
      } catch (_) {}
    }, 0);
  }, true);

  document.addEventListener("input", function (event) {
    const field = event.target;
    if (!isCreateAgentTextField(field)) return;

    if (event.isComposing || composingFields.has(field)) {
      event.stopImmediatePropagation();
      return;
    }

    const key = fieldKey(field);
    const start = typeof field.selectionStart === "number" ? field.selectionStart : null;
    const end = typeof field.selectionEnd === "number" ? field.selectionEnd : null;

    window.requestAnimationFrame(function () {
      restoreField(key, field, start, end);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 0);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 40);
      window.setTimeout(function () { restoreField(key, field, start, end); }, 140);
    });
  }, true);
})();
