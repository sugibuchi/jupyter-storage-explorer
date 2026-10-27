// What shows over the storage explorer: the busy screen, the modal dialog
// ("Python code", "Properties") and menus. Each create function returns the
// element to add to the widget, and the functions using it.

// Shown over the widget while a file operation waits for the kernel: it
// blocks clicks and keys from the start, and shows itself after a moment
// (CSS, .jse-busy), so quick operations do not flicker. Its messages may
// name files: they go through visible().
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
    text.textContent = visible(message);
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
    say: (message) => (text.textContent = visible(message)),
  };
}

// The modal window ("Python code", "Properties", "About"), centred over a
// backdrop that dims the widget. Esc (see render), its close button or a
// click on the backdrop closes it.
//
// With `onPage` (the side panel, too narrow for it), it is shown over the
// whole browser window instead (common.js' dialogLayer), on the page only
// while it is open. `el` is then null: nothing to add to the widget.
function createModal(widgetEl, onPage = false) {
  const closeBtn = iconButton("close", "Close (Esc)");
  const head = h("div", { className: "jse-dialog-head" });
  const body = h("div", { className: "jse-dialog-body" });
  const el = h("div", { className: "jse-dialog", tabIndex: -1, hidden: true }, h("div", { className: "jse-modal" }, head, body));
  const layer = onPage ? dialogLayer(el) : null;
  if (layer) {
    // Outside the widget, whose own handler closes it on Esc.
    el.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      close();
    });
  }

  function close() {
    el.hidden = true;
    layer?.remove();
    widgetEl.focus({ preventScroll: true });
  }

  closeBtn.addEventListener("click", close);
  el.addEventListener("pointerdown", (ev) => ev.target === el && close());

  return {
    el: layer ? null : el,
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
      if (layer) document.body.append(layer);
      el.hidden = false;
      el.focus({ preventScroll: true });
    },
  };
}

// Menus: right-click menus, and the toolbar's and status bar's. Shown in a
// layer of the page's own (`document.body`), as JupyterLab's menus are, so
// that they may cross the widget's borders, e.g. out of the narrow side
// panel; kept inside the browser's window. The layer has the widget's class
// for its colours and font, and is on the page only while a menu is open.
function createMenu() {
  const el = h("div", { className: "jse-menu", hidden: true });
  const layer = h("div", { className: "jse-widget jse-menu-layer" }, el);
  // As the widget: JupyterLab's shortcuts do not fire on keys pressed in it.
  layer.dataset.lmSuppressShortcuts = "true";
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
    layer.remove();
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
  // (a key of shortcuts.js'), shown at the right. Labels and titles may name
  // files: they go through visible() here, for every menu.
  function rows(items) {
    return items.map((item) => {
      if (item === "-") return h("div", { className: "jse-menu-sep" });
      const row = h(
        "div",
        { className: "jse-menu-item" + (item.disabled ? " jse-disabled" : ""), hidden: Boolean(item.hidden), title: visible(item.title ?? "") },
        h("span", { className: "jse-menu-icon" }, ...(item.icon ? [icon(item.icon)] : [])),
        h("span", { className: "jse-menu-label", textContent: visible(item.label) }),
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
        // Placed as it opens, and again if its rows arrive while it is open.
        row.addEventListener("mouseenter", () => placeSub(row, sub));
        new ResizeObserver(() => row.matches(":hover") && placeSub(row, sub)).observe(sub);
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
    document.body.append(layer);
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

  // The browser's window, which menus stay inside (client coordinates).
  function windowBox() {
    const { clientWidth, clientHeight } = document.documentElement;
    return { left: 0, top: 0, right: clientWidth, bottom: clientHeight };
  }

  // Places the menu at the pointer, kept inside the window. The layer is at
  // the window's top left, so the menu's position is the pointer's. Called
  // again when rows appear later ("Preview as").
  function place() {
    if (el.hidden) return;
    tidySeparators();
    const box = windowBox();
    const x = Math.min(at.x, box.right - el.offsetWidth - 4);
    const y = Math.min(at.y, box.bottom - el.offsetHeight - 4);
    el.style.left = `${Math.max(0, x)}px`;
    el.style.top = `${Math.max(0, y)}px`;
  }

  // Places the submenu `sub` of `row` inside the window, from its own size:
  // on the right of the menu, else on its left, else, where neither has
  // room, over the menu below its row, so that the row stays in sight. It
  // never goes above or below the window either.
  function placeSub(row, sub) {
    sub.style.display = "block"; // measured even before :hover shows it
    const box = windowBox();
    const r = row.getBoundingClientRect();
    const width = sub.offsetWidth;
    const height = sub.offsetHeight;
    sub.style.display = "";
    const margin = 4;
    let left;
    let top = -5;
    if (r.right + width <= box.right - margin) {
      left = r.width;
    } else if (r.left - width >= box.left + margin) {
      left = -width;
    } else {
      left = Math.max(box.left + margin, box.right - margin - width) - r.left;
      top = r.height;
    }
    // Inside the widget vertically: up from its bottom, but not past its top.
    top = Math.min(top, box.bottom - margin - height - r.top);
    top = Math.max(top, box.top + margin - r.top);
    sub.style.left = `${left}px`;
    sub.style.top = `${top}px`;
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
