(function () {
  "use strict";
  function cleanup() {
    const root = document.querySelector(".hx-page") || document;
    root.querySelectorAll("button").forEach(function (btn) {
      if ((btn.textContent || "").trim() === "WeChat") btn.style.display = "none";
    });
    root.querySelectorAll(".hx-section-head h2").forEach(function (title) {
      if ((title.textContent || "").trim() === "WeChat Desktop") {
        const card = title.closest(".hx-card") || title.parentElement;
        if (card) card.style.display = "none";
      }
    });
  }
  const observer = new MutationObserver(cleanup);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", cleanup);
  else cleanup();
})();
