(function () {
  function getContainer() {
    var el = document.getElementById("toast-container");
    if (el) return el;
    el = document.createElement("div");
    el.id = "toast-container";
    document.body.appendChild(el);
    return el;
  }

  function normalizeType(type) {
    var t = String(type || "info").toLowerCase().trim();
    if (t === "debug") return "info";
    return t || "info";
  }

  window.showToast = function (type, message, opts) {
    opts = opts || {};
    var t = normalizeType(type);
    var text = String(message || "").trim();
    if (!text) return;

    var timeoutMs = typeof opts.timeoutMs === "number" ? opts.timeoutMs : 4000;

    var toast = document.createElement("div");
    toast.className = "toast toast--" + t;
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");

    var textEl = document.createElement("div");
    textEl.className = "toast__text";
    textEl.textContent = text;

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "toast__close";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.textContent = "×";

    var remove = function () {
      toast.classList.remove("is-visible");
      window.setTimeout(function () {
        if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
      }, 200);
    };
    closeBtn.addEventListener("click", remove);

    toast.appendChild(textEl);
    toast.appendChild(closeBtn);

    var container = getContainer();
    container.appendChild(toast);

    // Trigger enter animation.
    window.requestAnimationFrame(function () {
      toast.classList.add("is-visible");
    });

    if (timeoutMs > 0) {
      window.setTimeout(remove, timeoutMs);
    }
  };
})();

