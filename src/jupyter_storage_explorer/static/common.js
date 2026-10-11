// Shared by the widgets. Each widget's module is this file, query.js and the
// widget's own file (storage_explorer.js, data_explorer.js) joined together by
// the kernel (see _static.py), as an anywidget module cannot import files next
// to it.

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  Object.assign(el, props);
  el.append(...children);
  return el;
}

function cellText(value) {
  if (value == null) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

// Requests to the kernel answered by a {"type": "reply", "rid"} message:
// request() resolves with the reply; pass replies to onReply().
function createRequester(model) {
  let nextId = 1;
  const waiting = new Map();
  return {
    request(content, buffers) {
      const rid = nextId++;
      return new Promise((resolve) => {
        waiting.set(rid, resolve);
        model.send({ ...content, rid }, undefined, buffers);
      });
    },
    onReply(msg) {
      const resolve = waiting.get(msg.rid);
      waiting.delete(msg.rid);
      resolve?.(msg);
    },
  };
}

// Small modal dialog, e.g. "Upload sales.csv? [Cancel] [Upload]". Add `el` to
// the widget. ask(lines, buttons) resolves with the clicked button's value, or
// null for Cancel/Esc/backdrop; buttons: [{label, value, primary}], shown left
// to right. answer(value) closes it as if a button was clicked.
function createConfirm() {
  const body = h("div", { className: "jse-dialog-body" });
  const buttons = h("div", { className: "jse-editor-foot" });
  const el = h("div", { className: "jse-dialog", tabIndex: -1, hidden: true }, h("div", { className: "jse-modal jse-confirm" }, body, buttons));
  let pending = null;

  function ask(lines, choices) {
    pending?.(null);
    return new Promise((resolve) => {
      pending = resolve;
      body.replaceChildren(...lines);
      buttons.replaceChildren(
        h("span", { className: "jse-spacer" }),
        ...choices.map((b) => {
          const btn = h("button", { className: "jse-btn" + (b.primary ? " jse-primary" : ""), textContent: b.label });
          btn.addEventListener("click", () => answer(b.value));
          return btn;
        }),
      );
      el.hidden = false;
      el.focus({ preventScroll: true });
    });
  }

  function answer(value) {
    el.hidden = true;
    const resolve = pending;
    pending = null;
    resolve?.(value);
  }

  el.addEventListener("pointerdown", (ev) => ev.target === el && answer(null));
  el.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    ev.stopPropagation();
    answer(null);
  });
  return { el, ask, answer };
}

// A one-line filter: a text field and a ".*" toggle for regular expressions.
// Matching is always case-insensitive. onChange() is called as it changes.
// test(text) tells whether a name matches: everything matches while the field
// is empty, or while its regular expression is invalid (marked in red).
// active() tells whether it filters. Esc in the field clears it.
function createFilter({ placeholder = "Filter", onChange = () => {} } = {}) {
  const input = h("input", { type: "text", className: "jse-filter-input", placeholder, spellcheck: false });
  const regexBtn = h("button", {
    type: "button",
    className: "jse-btn jse-filter-regex",
    textContent: ".*",
    title: "Regular expression (case-insensitive)",
  });
  regexBtn.setAttribute("aria-pressed", "false");
  const el = h("div", { className: "jse-filter" }, input, regexBtn);
  let regex = false;
  let test = () => true;
  let active = false;

  function update() {
    const text = input.value;
    input.classList.remove("jse-invalid");
    input.title = "";
    test = () => true;
    active = false;
    if (text && regex) {
      try {
        const re = new RegExp(text, "i");
        test = (name) => re.test(name);
        active = true;
      } catch (err) {
        input.classList.add("jse-invalid");
        input.title = err.message; // e.g. "Invalid regular expression: /a(/i: Unterminated group"
      }
    } else if (text) {
      const needle = text.toLowerCase();
      test = (name) => name.toLowerCase().includes(needle);
      active = true;
    }
    onChange();
  }

  input.addEventListener("input", update);
  input.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || !input.value) return;
    ev.stopPropagation(); // clears the field, rather than closing a dialog or panel
    input.value = "";
    update();
  });
  regexBtn.addEventListener("click", () => {
    regex = !regex;
    regexBtn.classList.toggle("jse-on", regex);
    regexBtn.setAttribute("aria-pressed", String(regex));
    update();
  });
  return {
    el,
    test: (name) => test(name),
    active: () => active,
    focus: () => input.focus({ preventScroll: true }),
  };
}

// Calls begin() on pointerdown; it returns a function given the vertical
// distance dragged so far.
function onDragY(handle, begin) {
  handle.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    handle.setPointerCapture(ev.pointerId);
    const startY = ev.clientY;
    const move = begin();
    const onMove = (e) => move(e.clientY - startY);
    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });
}
