// What shows over the storage explorer: the busy screen, the modal dialog
// ("Python code", "Properties") and menus. Each create function returns the
// element to add to the widget, and the functions using it.

// Shown over the widget while a file operation waits for the kernel: it
// blocks clicks and keys from the start, and shows itself after a moment
// (CSS, .jse-busy), so quick operations do not flicker.
function createBusy() {
  const text = h("div", { className: "jse-busy-text" });
  const el = h(
    "div",
    { className: "jse-dialog jse-busy", tabIndex: -1, hidden: true },
    h("div", { className: "jse-modal jse-busy-box" }, h("span", { className: "jse-spinner", ariaHidden: "true" }), text),
  );
  el.setAttribute("role", "alertdialog");
  el.setAttribute("aria-busy", "true");
  el.addEventListener("keydown", (ev) => {
    ev.preventDefault(); // nothing else runs meanwhile, Esc included
    ev.stopPropagation();
  });
  let count = 0;

  function start(message) {
    count += 1;
    text.textContent = message;
    // Restart the delay of its appearance.
    el.hidden = true;
    void el.offsetWidth;
    el.hidden = false;
    el.focus({ preventScroll: true });
  }

  function end() {
    count = Math.max(0, count - 1);
    if (!count) el.hidden = true;
  }

  return {
    el,
    start,
    end,
    // Runs `work` (async) with the widget blocked, showing `message`; returns its result.
    async run(message, work) {
      start(message);
      try {
        return await work();
      } finally {
        end();
      }
    },
    // Changes the message shown, e.g. to show progress.
    say: (message) => (text.textContent = message),
  };
}

// The modal window ("Python code", "Properties"), centred over a backdrop that
// dims the widget. Esc (see render), its close button or a click on the
// backdrop closes it.
function createModal(widgetEl) {
  const closeBtn = iconButton("close", "Close (Esc)");
  const head = h("div", { className: "jse-dialog-head" });
  const body = h("div", { className: "jse-dialog-body" });
  const el = h("div", { className: "jse-dialog", tabIndex: -1, hidden: true }, h("div", { className: "jse-modal" }, head, body));

  function close() {
    el.hidden = true;
    widgetEl.focus({ preventScroll: true });
  }

  closeBtn.addEventListener("click", close);
  el.addEventListener("pointerdown", (ev) => ev.target === el && close());

  return {
    el,
    close,
    isOpen: () => !el.hidden,
    show(title, children) {
      head.replaceChildren(
        h("span", { className: "jse-preview-name", textContent: visible(title), title: visible(title) }),
        h("span", { className: "jse-spacer" }),
        closeBtn,
      );
      body.replaceChildren(...children);
      body.scrollTop = 0;
      el.hidden = false;
      el.focus({ preventScroll: true });
    },
  };
}

// Menus: right-click menus, and the bookmarks button's. Kept inside the
// widget (`widgetEl`), which clips what is outside it.
function createMenu(widgetEl) {
  const el = h("div", { className: "jse-menu", hidden: true });
  // The button that opened the menu, if one did: pressing it again is left
  // to its click handler, which closes the menu, rather than closing it here
  // for the click to open it again.
  let owner = null;
  // Where the open menu was opened (client coordinates).
  let at = { x: 0, y: 0 };

  function onOutsidePointer(ev) {
    if (!el.contains(ev.target) && !owner?.contains(ev.target)) hide();
  }

  function onKey(ev) {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      hide();
    }
  }

  function hide() {
    el.hidden = true;
    document.removeEventListener("pointerdown", onOutsidePointer, true);
    document.removeEventListener("keydown", onKey, true);
  }

  // items: {label, action, disabled}, {label, submenu, disabled} or "-" for a
  // separator. `icon`: an icon's name (ICON_PATHS), on the left; rows without
  // one keep its space, so labels line up. `submenu(el)` fills the submenu
  // element, possibly later.
  // `hidden` rows can be shown later through the element passed to `ref(row)`.
  // `title`: the row's tooltip. `menu()`: the items of the menu right-clicking
  // the row opens in place of this one. `shortcut`: its key in the file list
  // (a key of shortcuts.js'), shown at the right.
  function rows(items) {
    return items.map((item) => {
      if (item === "-") return h("div", { className: "jse-menu-sep" });
      const row = h(
        "div",
        { className: "jse-menu-item" + (item.disabled ? " jse-disabled" : ""), hidden: Boolean(item.hidden), title: item.title ?? "" },
        h("span", { className: "jse-menu-icon" }, ...(item.icon ? [icon(item.icon)] : [])),
        h("span", { className: "jse-menu-label", textContent: item.label }),
        ...(item.shortcut ? [h("span", { className: "jse-menu-shortcut", textContent: keyLabel(item.shortcut) })] : []),
      );
      item.ref?.(row);
      if (item.menu) row.addEventListener("contextmenu", (ev) => show(ev, item.menu()));
      if (item.disabled) return row;
      if (item.submenu) {
        const sub = h("div", { className: "jse-menu jse-submenu" });
        row.classList.add("jse-has-sub");
        row.append(h("span", { className: "jse-sub-arrow" }, icon("caret-right")), sub);
        item.submenu(sub);
      } else {
        row.addEventListener("click", () => {
          hide();
          item.action();
        });
      }
      return row;
    });
  }

  // Opens the menu of `items` where the event `ev` happened.
  function show(ev, items) {
    ev.preventDefault();
    ev.stopPropagation(); // keep JupyterLab's own context menu from opening
    el.replaceChildren(...rows(items));
    el.hidden = false;
    owner = null;
    at = { x: ev.clientX, y: ev.clientY };
    place();
    document.addEventListener("pointerdown", onOutsidePointer, true);
    document.addEventListener("keydown", onKey, true);
  }

  // Separators only between visible rows: none first, last or doubled, as
  // rows hidden until the kernel answers (a folder's "Preview", "Python
  // code") can leave a group with nothing shown.
  function tidySeparators() {
    let seen = false;
    let pending = null;
    for (const child of el.children) {
      if (child.classList.contains("jse-menu-sep")) {
        child.hidden = true;
        if (seen) pending = child;
      } else if (!child.hidden) {
        if (pending) pending.hidden = false;
        pending = null;
        seen = true;
      }
    }
  }

  // Places the menu at the pointer, kept inside the widget. Called again when
  // rows appear later ("Preview as").
  function place() {
    if (el.hidden) return;
    tidySeparators();
    const box = widgetEl.getBoundingClientRect();
    const x = Math.min(at.x - box.left, box.width - el.offsetWidth - 4);
    const y = Math.min(at.y - box.top, box.height - el.offsetHeight - 4);
    el.style.left = `${Math.max(0, x)}px`;
    el.style.top = `${Math.max(0, y)}px`;
    // Open submenus to the left when there is no room on the right.
    el.classList.toggle("jse-flip", Math.max(0, x) + 2 * el.offsetWidth > box.width);
  }

  return {
    el,
    show,
    hide,
    rows,
    place,
    // Opens the menu of `items` below `button`, which then closes it (see isOpenFrom).
    showBelow(button, items) {
      const box = button.getBoundingClientRect();
      show({ clientX: box.left, clientY: box.bottom, preventDefault() {}, stopPropagation() {} }, items);
      owner = button;
    },
    // Opens the menu of `items` above `button` (in the status bar), likewise.
    showAbove(button, items) {
      const box = button.getBoundingClientRect();
      show({ clientX: box.left, clientY: box.top, preventDefault() {}, stopPropagation() {} }, items);
      at = { x: box.left, y: box.top - el.offsetHeight };
      place();
      owner = button;
    },
    isOpenFrom: (button) => !el.hidden && owner === button,
  };
}
