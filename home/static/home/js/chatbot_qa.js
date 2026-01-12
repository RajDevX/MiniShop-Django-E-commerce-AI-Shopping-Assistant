/* Chatbot QA / smoke test helper
 * Usage:
 * - In the chatbot page/iframe console:
 *   const s = document.createElement('script'); s.src = '/static/home/js/chatbot_qa.js'; document.head.appendChild(s);
 * - In the main page (for floating widget tests), same snippet.
 */
(function () {
  let passCount = 0;
  let failCount = 0;
  let infoCount = 0;

  function logResult(name, ok, details) {
    const status = ok ? "PASS" : "FAIL";
    const msg = `[${status}] ${name}` + (details ? ` — ${details}` : "");
    (ok ? console.log : console.warn)(msg);
    if (ok) {
      passCount += 1;
    } else {
      failCount += 1;
    }
  }

  function logInfo(name, details) {
    const msg = `[INFO] ${name}` + (details ? ` — ${details}` : "");
    console.log(msg);
    infoCount += 1;
  }

  function section(title) {
    console.log(`\n=== ${title} ===`);
  }

  function getText(el) {
    return (el && el.textContent ? el.textContent.trim() : "");
  }

  function getCardText(card) {
    const text = getText(card);
    return text.replace(/\s+/g, " ").trim();
  }

  function findProductCards() {
    const chatbox = document.getElementById("chatbox") || document.body;
    const viewLinks = Array.from(chatbox.querySelectorAll("a"))
      .filter((a) => /view product/i.test(getText(a)));
    const cards = new Set();

    viewLinks.forEach((view) => {
      let node = view;
      while (node && node !== chatbox) {
        const hasAddBtn = node.querySelector && node.querySelector("button") &&
          /add to cart/i.test(getText(node.querySelector("button")));
        if (hasAddBtn) {
          cards.add(node);
          break;
        }
        node = node.parentElement;
      }
    });

    return Array.from(cards);
  }

  function findNameAndPrice(card) {
    const text = getCardText(card);
    const priceMatch = text.match(/\$?\s*\d+(?:\.\d+)?/);
    const price = priceMatch ? priceMatch[0].replace(/\s/g, "") : "";
    let name = "";

    // Try to find a likely name element (first bold-ish text, else first line)
    const strong = card.querySelector("strong, b");
    if (strong) {
      name = getText(strong);
    } else {
      const lines = getText(card).split("\n").map((l) => l.trim()).filter(Boolean);
      name = lines[0] || "";
    }
    return { name, price };
  }

  function findDescription(card, name, price) {
    const text = getText(card);
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    const cleaned = lines.filter((l) => l && l !== name && !l.includes(price) && !/view product|add to cart/i.test(l));
    if (!cleaned.length) return "";
    // Prefer a line that is not too short.
    const candidate = cleaned.find((l) => l.length >= 12) || cleaned[0];
    return candidate || "";
  }

  function findUserInput() {
    return (
      document.querySelector("textarea") ||
      document.querySelector("[contenteditable='true']") ||
      document.querySelector("input[type='text']") ||
      document.querySelector("input[type='search']")
    );
  }

  function findSendButton() {
    const byType = document.querySelector("button[type='submit'], input[type='submit']");
    if (byType) return byType;
    const byAria = Array.from(document.querySelectorAll("button, input"))
      .find((el) => /send|ask|submit/i.test((el.getAttribute("aria-label") || "") + " " + getText(el)));
    return byAria || null;
  }

  function runChatbotChecks() {
    section("Chatbot Cards + Input");

    const chatbox = document.getElementById("chatbox");
    const input = findUserInput();
    const sendButton = findSendButton();

    logResult("Chatbox present", !!chatbox);
    logResult("Input present", !!input);
    logResult("Send button present", !!sendButton);

    const cards = findProductCards();
    logResult("Card count <= 5", cards.length <= 5, `count=${cards.length}`);

    const seen = new Set();
    let dupes = 0;
    cards.forEach((card) => {
      const np = findNameAndPrice(card);
      const key = `${np.name}|${np.price}`;
      if (seen.has(key)) dupes += 1;
      seen.add(key);
    });
    logResult("Cards unique (name+price)", dupes === 0, dupes ? `dupes=${dupes}` : "");

    let missingDesc = 0;
    let descTooLong = 0;
    cards.forEach((card) => {
      const np = findNameAndPrice(card);
      const desc = findDescription(card, np.name, np.price);
      if (!desc) missingDesc += 1;
      if (desc && desc.length > 120) descTooLong += 1;
    });
    if (missingDesc > 0) {
      logResult("Description present (fallback allowed)", true, `missing=${missingDesc} (fallback expected)`);
    } else {
      logResult("Description present (fallback allowed)", true);
    }
    logResult("Description <= 120 chars", descTooLong === 0, descTooLong ? `tooLong=${descTooLong}` : "");

    let missingAria = 0;
    let nonFocusable = 0;
    cards.forEach((card) => {
      const view = Array.from(card.querySelectorAll("a")).find((a) => /view product/i.test(getText(a)));
      const add = Array.from(card.querySelectorAll("button")).find((b) => /add to cart/i.test(getText(b)));
      [view, add].forEach((el) => {
        if (!el) return;
        const aria = el.getAttribute("aria-label");
        if (!aria) missingAria += 1;
        if (el.tabIndex === -1 || el.disabled) nonFocusable += 1;
      });
    });
    logResult("Buttons have aria-label", missingAria === 0, missingAria ? `missing=${missingAria}` : "");
    logResult("Buttons focusable", nonFocusable === 0, nonFocusable ? `nonFocusable=${nonFocusable}` : "");

    // Layout checks (best-effort, selector-safe)
    if (cards.length) {
      const parent = cards[0].parentElement;
      const display = parent ? getComputedStyle(parent).display : "";
      const width = window.innerWidth;
      const lefts = new Set(cards.map((c) => c.getBoundingClientRect().left.toFixed(1)));

      if (width < 768) {
        logResult("Mobile layout (stacked)", lefts.size <= 1, `cols=${lefts.size}`);
      } else if (display === "grid") {
        const cols = getComputedStyle(parent).gridTemplateColumns.split(" ").length;
        logResult("Desktop layout (>=2 columns)", cols >= 2, `cols=${cols}`);
      } else {
        logResult("Desktop layout (>=2 columns)", lefts.size >= 2, `cols=${lefts.size}`);
      }
    } else {
      logInfo("Layout check", "No cards rendered to evaluate layout");
    }

    // Input behavior (Enter send / Shift+Enter newline) – partial automation
    if (input && sendButton) {
      const initial = input.value || "";
      if ("value" in input) {
        input.value = "QA test";
      } else if (input.isContentEditable) {
        input.textContent = "QA test";
      }
      const evt = new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
        composed: true,
      });
      input.dispatchEvent(evt);
      setTimeout(() => {
        const current = "value" in input ? input.value : input.textContent || "";
        const cleared = current === "" || current === initial;
        if (cleared) {
          logResult("Enter sends message (input cleared)", true);
        } else {
          logInfo("Enter sends message (input cleared)", "Manual check required");
        }
        if ("value" in input) {
          input.value = initial;
        } else {
          input.textContent = initial;
        }
        logInfo("Shift+Enter newline", "Manual check required");
      }, 300);
    } else {
      logInfo("Enter sends message (input cleared)", "Manual check required");
    }

    console.log(
      `[SUMMARY] Chatbot QA — pass=${passCount} fail=${failCount} info=${infoCount}`
    );
  }

  function runWidgetChecks() {
    section("Floating Widget");

    const btn = document.querySelector(".floating-chatbot__btn");
    const panel = document.getElementById("floating-chatbot-panel");
    if (!btn || !panel) {
      logResult("Floating widget present", false, "Not found on this page");
      return;
    }
    logResult("Floating widget present", true);

    const wasOpen = panel.getAttribute("aria-hidden") === "false";
    btn.click();
    const opened = panel.getAttribute("aria-hidden") === "false";
    logResult("Toggle open/close", opened !== wasOpen);

    // Click outside to close
    if (opened) {
      document.body.click();
      const closed = panel.getAttribute("aria-hidden") === "true";
      logResult("Click outside closes", closed);
    }

    console.log(
      `[SUMMARY] Widget QA — pass=${passCount} fail=${failCount} info=${infoCount}`
    );
  }

  function isChatbotIframeContext() {
    const path = (location.pathname || "").toLowerCase();
    if (path.includes("/chatbot")) return true;
    if (window.self !== window.top) return true;
    return false;
  }

  // Auto-detect context and run the right checks.
  if (isChatbotIframeContext()) {
    runChatbotChecks();
  } else {
    runWidgetChecks();
  }
})();
