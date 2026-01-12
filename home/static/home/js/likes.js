(function () {
  "use strict";

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function setButtonState(btn, liked) {
    btn.setAttribute("aria-pressed", liked ? "true" : "false");
    var icon = btn.querySelector("span");
    if (!icon) return;
    icon.className = liked ? "ion-ios-heart" : "ion-ios-heart-empty";
  }

  document.addEventListener("click", async function (e) {
    var btn = e.target.closest(".js-like-toggle");
    if (!btn) return;
    e.preventDefault();

    var url = btn.getAttribute("data-like-url");
    if (!url) return;

    btn.disabled = true;
    try {
      var res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
          Accept: "application/json",
        },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error("Request failed");
      var data = await res.json();
      setButtonState(btn, !!data.liked);
    } catch (_err) {
      // noop (optional: toast)
    } finally {
      btn.disabled = false;
    }
  });
})();
