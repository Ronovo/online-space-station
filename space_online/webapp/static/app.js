(() => {
  "use strict";

  const TICK_MS = 1000;
  const screen = document.getElementById("screen");
  const modal = document.getElementById("modal");
  const modalTitle = document.getElementById("modal-title");
  const modalMessage = document.getElementById("modal-message");
  const modalButtons = document.getElementById("modal-buttons");
  const connection = document.getElementById("connection");
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const { actUrl, homeUrl } = screen.dataset;

  const initial = JSON.parse(document.getElementById("initial-state").textContent);
  let screenHash = initial.hash;
  let pending = Promise.resolve();
  let inFlight = 0;
  let draggingRange = false;
  let choice = null;
  let answeringChoice = false;
  let shownChoiceId = null;
  // Scroll positions by data-scroll-key, kept while a list is hidden under another panel.
  let scrollMemory = {};

  function parseArgs(el) {
    try {
      return JSON.parse(el.dataset.args || "{}");
    } catch (_error) {
      return {};
    }
  }

  function formArgs(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  // Requests run one at a time so responses always apply in order.
  function enqueue(action, args) {
    inFlight += 1;
    pending = pending
      .then(() => send(action, args))
      .catch(() => {
        answeringChoice = false;
        connection.classList.remove("hidden");
      })
      .finally(() => { inFlight -= 1; });
    return pending;
  }

  async function send(action, args) {
    const response = await fetch(actUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ action, args: args || {}, hash: screenHash }),
    });
    const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
    if (response.redirected || !isJson) {
      window.location.href = response.redirected ? response.url : homeUrl;
      return;
    }
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    connection.classList.add("hidden");
    applyResponse(await response.json(), action);
  }

  function applyResponse(data, action) {
    if (data.redirect) {
      window.location.href = data.redirect;
      return;
    }
    if (data.html !== undefined && swapScreen(data.html, action === "tick")) {
      screenHash = data.hash;
    }
    if (data.title) {
      document.title = data.title;
    }
    // Responses queued before the player's answer still carry the old choice.
    if (action === "game.choose") {
      answeringChoice = false;
    }
    if (!answeringChoice) {
      choice = data.choice || null;
    }
    renderModal();
  }

  function captureState(preserveInputs) {
    const state = { inputs: {}, focusId: null, selection: null, windowY: window.scrollY };
    screen.querySelectorAll("[data-scroll-key]").forEach((el) => {
      scrollMemory[el.dataset.scrollKey] = el.scrollTop;
    });
    if (preserveInputs) {
      screen.querySelectorAll("input[id]:not([type=range]):not([type=radio]), textarea[id], select[id]").forEach((el) => {
        state.inputs[el.id] = el.value;
      });
      const active = document.activeElement;
      if (active && active.id && screen.contains(active)) {
        state.focusId = active.id;
        try {
          state.selection = [active.selectionStart, active.selectionEnd];
        } catch (_error) {
          state.selection = null;
        }
      }
    }
    return state;
  }

  function restoreState(state) {
    screen.querySelectorAll("[data-scroll-key]").forEach((el) => {
      if (scrollMemory[el.dataset.scrollKey] !== undefined) {
        el.scrollTop = scrollMemory[el.dataset.scrollKey];
      }
    });
    if (!screen.querySelector(".panel")) {
      scrollMemory = {};
    }
    Object.entries(state.inputs).forEach(([id, value]) => {
      const el = document.getElementById(id);
      if (el && screen.contains(el)) {
        el.value = value;
      }
    });
    if (state.focusId) {
      const el = document.getElementById(state.focusId);
      if (el) {
        el.focus();
        if (state.selection && state.selection[0] !== null) {
          try {
            el.setSelectionRange(state.selection[0], state.selection[1]);
          } catch (_error) {
            // Inputs like type=number do not support selection ranges.
          }
        }
      }
    }
    window.scrollTo(0, state.windowY);
  }

  function shownHealth() {
    const readout = screen.querySelector("[data-health]");
    return readout ? Number(readout.dataset.health) : null;
  }

  // Restarting the animation needs the class gone for a frame, which the reflow between gives it.
  function flashHurt() {
    screen.classList.remove("hurt");
    void screen.offsetWidth;
    screen.classList.add("hurt");
  }

  // Returns false when the swap is postponed so the next tick retries it.
  function swapScreen(html, fromTick) {
    if (fromTick && draggingRange) {
      return false;
    }
    const state = captureState(fromTick);
    const healthBefore = shownHealth();
    screen.innerHTML = html;
    restoreState(state);
    const healthNow = shownHealth();
    if (healthBefore !== null && healthNow !== null && healthNow < healthBefore) {
      flashHurt();
    }
    if (!fromTick) {
      const autofocus = screen.querySelector("[autofocus]");
      if (autofocus) {
        autofocus.focus();
      }
    }
    updateShareTotals();
    return true;
  }

  // The modal only ever asks a question the game is waiting on. Everything else is in the station log.
  function renderModal() {
    if (!choice) {
      hideModal();
      return;
    }
    if (shownChoiceId === choice.id) {
      return;
    }
    const current = choice;
    shownChoiceId = current.id;
    modalTitle.textContent = current.title;
    modalMessage.textContent = current.message;
    modalButtons.replaceChildren(...current.buttons.map((label, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn";
      button.textContent = label;
      button.addEventListener("click", () => {
        choice = null;
        answeringChoice = true;
        hideModal();
        enqueue("game.choose", { id: current.id, index });
      });
      return button;
    }));
    modal.classList.remove("hidden");
    modalButtons.querySelector("button").focus();
  }

  function hideModal() {
    shownChoiceId = null;
    modal.classList.add("hidden");
  }

  function updateShareTotals() {
    const input = screen.querySelector("[data-share-input]");
    if (!input) {
      return;
    }
    const price = parseFloat(input.dataset.price);
    const credits = parseFloat(input.dataset.credits);
    const owned = parseInt(input.dataset.owned, 10);
    const shares = Number(input.value);
    const valid = input.value.trim() !== "" && Number.isInteger(shares) && shares > 0;
    const total = valid ? shares * price : 0;
    screen.querySelector("[data-share-total]").textContent = `Total: ${total.toFixed(2)}`;
    screen.querySelector("[data-share-buy]").disabled = !(valid && total <= credits);
    screen.querySelector("[data-share-sell]").disabled = !(valid && shares <= owned);
  }

  document.addEventListener("click", (event) => {
    const setter = event.target.closest("[data-set-input]");
    if (setter && screen.contains(setter)) {
      const target = document.getElementById(setter.dataset.setInput);
      if (target) {
        target.value = setter.dataset.value;
        updateShareTotals();
      }
      return;
    }

    const el = event.target.closest("[data-action]");
    if (!el || !screen.contains(el) || el.disabled || el.tagName === "FORM" || el.tagName === "INPUT") {
      return;
    }
    event.preventDefault();
    const form = el.closest("form");
    enqueue(el.dataset.action, { ...(form ? formArgs(form) : {}), ...parseArgs(el) });
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!screen.contains(form)) {
      return;
    }
    event.preventDefault();
    if (form.dataset.action) {
      enqueue(form.dataset.action, { ...parseArgs(form), ...formArgs(form) });
    }
  });

  document.addEventListener("change", (event) => {
    const el = event.target;
    if (!screen.contains(el) || !el.dataset.action) {
      return;
    }
    if (el.type === "range") {
      enqueue(el.dataset.action, { ...parseArgs(el), value: el.value });
    } else if (el.type === "radio" && el.checked) {
      enqueue(el.dataset.action, parseArgs(el));
    }
  });

  document.addEventListener("input", (event) => {
    const el = event.target;
    if (!screen.contains(el)) {
      return;
    }
    if (el.matches("[data-share-input]")) {
      updateShareTotals();
    } else if (el.type === "range") {
      const output = screen.querySelector(`output[for="${el.id}"]`);
      if (output) {
        output.textContent = el.value;
      }
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (event.target.matches && event.target.matches('input[type="range"]')) {
      draggingRange = true;
    }
  });
  ["pointerup", "pointercancel"].forEach((type) => {
    document.addEventListener(type, () => { draggingRange = false; });
  });

  setInterval(() => {
    if (inFlight === 0) {
      enqueue("tick");
    }
  }, TICK_MS);

  choice = initial.choice || null;
  renderModal();
  updateShareTotals();
})();
