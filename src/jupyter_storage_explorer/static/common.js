// Shared by the widgets. Each widget's module is the shared files (icons.js,
// this file, query.js and sections.js), its parts (static/<widget>/) and its
// own file, joined together by the kernel (see _static.esm), as an anywidget
// module cannot import files next to it.

// Characters that change how the text around them reads, or are not seen:
// controls, bidi embeddings, overrides and isolates (e.g. "report\u202Egpj.exe"
// reads as "reportexe.jpg"), zero-width and other invisible format characters.
const HIDDEN_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]/g;

// `text` (a file name, a path, a message naming files) as users should read
// it: HIDDEN_CHARACTERS shown as \uXXXX escapes, so that a name cannot pass
// for another. Only for display; names are sent and compared as they are.
function visible(text) {
  return String(text).replace(HIDDEN_CHARACTERS, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  Object.assign(el, props);
  el.append(...children);
  return el;
}

// An error from the kernel (see error_text in _explorer/common.py): its first
// line, which says what went wrong, and the rest folded under "Details", e.g.
// a Java stack trace. Each line goes through visible(), tabs as spaces.
function errorBlock(text) {
  const lines = String(text)
    .split(/\r?\n/)
    .map((line) => visible(line.replace(/\t/g, "    ")));
  const el = h("div", { className: "jse-preview-error" }, h("div", { className: "jse-error-summary", textContent: lines[0] }));
  const rest = lines.slice(1).join("\n").trim();
  if (rest) {
    el.append(h("details", { className: "jse-error-details" }, h("summary", { textContent: "Details" }), h("pre", { textContent: rest })));
  }
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

// A layer of the page's own for the dialog `el`, shown over the whole browser
// window, as JupyterLab's dialogs are, rather than over the widget: for the
// side panel, too narrow for dialogs. It has the widget's class for its
// colours and font. Add it to `document.body` while the dialog is open.
function dialogLayer(el) {
  const layer = h("div", { className: "jse-widget jse-dialog-layer" }, el);
  // As the widget: JupyterLab's shortcuts do not fire on keys pressed in it.
  layer.dataset.lmSuppressShortcuts = "true";
  return layer;
}

// Small modal dialog, e.g. "Upload sales.csv? [Cancel] [Upload]". Add `el` to
// the widget. ask(lines, buttons) resolves with the clicked button's value, or
// null for Cancel/Esc/backdrop; buttons: [{label, value, primary}], shown left
// to right. answer(value) closes it as if a button was clicked. With `onPage`
// (the side panel), it is shown over the whole window (dialogLayer), and `el`
// is null: nothing to add to the widget.
function createConfirm(onPage = false) {
  const body = h("div", { className: "jse-dialog-body" });
  const buttons = h("div", { className: "jse-dialog-foot" });
  const el = h("div", { className: "jse-dialog", tabIndex: -1, hidden: true }, h("div", { className: "jse-modal jse-confirm" }, body, buttons));
  const layer = onPage ? dialogLayer(el) : null;
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
      if (layer) document.body.append(layer);
      el.hidden = false;
      el.focus({ preventScroll: true });
    });
  }

  function answer(value) {
    el.hidden = true;
    layer?.remove();
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
  return { el: layer ? null : el, ask, answer };
}

// The buttons of a confirmation: Cancel, and `label`, answering true.
function confirmButtons(label) {
  return [
    { label: "Cancel", value: null },
    { label, value: true, primary: true },
  ];
}

// A one-line filter: a text field with a search icon (not a button) and a
// clear button (✕, while it has text), and a ".*" toggle for regular expressions. Matching is always
// case-insensitive. onChange() is called as it changes. test(text) tells
// whether a name matches: everything matches while the field is empty, or
// while its regular expression is invalid (marked in red). active() tells
// whether it filters; clear() empties it. Esc in the field clears it too.
// For filtering elsewhere (the kernel): query() gives {text, regex} while it
// filters, else null, and invalid(message) marks the field as invalid until
// it changes.
function createFilter({ placeholder = "Filter", onChange = () => {} } = {}) {
  const input = h("input", { type: "text", className: "jse-filter-input", placeholder, spellcheck: false });
  const clearBtn = h("button", { type: "button", className: "jse-filter-clear", textContent: "✕", title: "Clear", hidden: true });
  const regexBtn = h("button", {
    type: "button",
    className: "jse-btn jse-filter-regex",
    textContent: ".*",
    title: "Regular expression (case-insensitive)",
  });
  regexBtn.setAttribute("aria-pressed", "false");
  const searchIcon = icon("search");
  searchIcon.classList.add("jse-filter-icon");
  const el = h("div", { className: "jse-filter" }, h("span", { className: "jse-filter-field" }, searchIcon, input, clearBtn), regexBtn);
  let regex = false;
  let test = () => true;
  let active = false;

  function update(notify = true) {
    const text = input.value;
    clearBtn.hidden = !text;
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
    if (notify) onChange();
  }

  // Empties the field; onChange() only if it had text, and `notify` is true
  // (false when the caller is about to render anyway).
  function clear(notify = true) {
    if (!input.value) return;
    input.value = "";
    update(notify);
  }

  input.addEventListener("input", () => update());
  input.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || !input.value) return;
    ev.stopPropagation(); // clears the field, rather than closing a dialog or panel
    clear();
  });
  clearBtn.addEventListener("click", () => {
    clear();
    input.focus({ preventScroll: true });
  });
  regexBtn.addEventListener("click", () => {
    regex = !regex;
    regexBtn.classList.toggle("jse-on", regex);
    regexBtn.setAttribute("aria-pressed", String(regex));
    update();
  });
  function invalid(message) {
    input.classList.add("jse-invalid");
    input.title = message;
  }

  return {
    el,
    test: (name) => test(name),
    active: () => active,
    query: () => (active ? { text: input.value, regex } : null),
    invalid,
    clear,
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
