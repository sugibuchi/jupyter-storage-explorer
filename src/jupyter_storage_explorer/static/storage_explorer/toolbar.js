// The toolbar: the tree's button, bookmarks, Up, Refresh, the folder's path,
// Unsafe mode, and the settings menu: "Edit configuration" in the launcher's
// tabs, "About". The sidebar layout has two narrower bars: the storage
// chooser (slot), bookmarks, Refresh and the settings menu, whose first item
// is then Unsafe mode; below (pathBar), Up and the folder's path.

function createToolbar(x) {
  const { model } = x;
  const sidebar = model.get("_layout") === "sidebar";
  // Shows or hides the folder tree (_tree_view); none without a tree.
  const treeBtn = iconButton("tree", "Folder tree", "jse-tree-btn");
  const upBtn = iconButton("up", "Parent directory");
  const refreshBtn = iconButton("refresh", "Refresh");
  const pathEl = h("div", { className: "jse-path" });
  const settingsBtn = iconButton("settings", "Settings", "jse-settings-btn");
  // Where the storage chooser goes in the sidebar layout (see placeStorages
  // in storage_explorer.js); it takes the bar's room left by the buttons.
  const slot = h("div", { className: "jse-storage-slot" });
  const el = sidebar
    ? h("div", { className: "jse-toolbar" }, treeBtn, slot, x.bookmarks.button, refreshBtn, settingsBtn)
    : h("div", { className: "jse-toolbar" }, treeBtn, x.bookmarks.button, upBtn, refreshBtn, pathEl, x.unsafe.el, settingsBtn);
  const pathBar = sidebar ? h("div", { className: "jse-path-bar" }, upBtn, pathEl) : null;

  // In the sidebar layout, Unsafe mode is in the settings menu: while it is
  // on, the settings button is red, as the switch would be.
  function renderUnsafe() {
    const on = sidebar && x.unsafe.on();
    settingsBtn.classList.toggle("jse-unsafe-on", on);
    settingsBtn.title = on ? "Settings (Unsafe mode is on)" : "Settings";
  }

  function renderTreeButton() {
    const state = model.get("_tree_view");
    treeBtn.hidden = state === "disabled";
    treeBtn.classList.toggle("jse-on", state === "open");
    treeBtn.title = state === "open" ? "Hide the folder tree" : "Show the folder tree";
    treeBtn.ariaLabel = treeBtn.title;
  }

  treeBtn.addEventListener("click", () => {
    model.set("_tree_view", model.get("_tree_view") === "open" ? "closed" : "open");
    model.save_changes();
  });

  // The current folder's path, a crumb per folder from the root.
  function renderPath() {
    const chain = x.ancestors(model.get("_current_dir"));
    // In a span of its own, left to right: pathEl is right to left, so that a
    // path too long is cut at its start, and the current folder stays in view.
    const crumbs = h("span", { className: "jse-crumbs" });
    chain.forEach((path, i) => {
      if (i > 0) crumbs.append(h("span", { className: "jse-sep", textContent: "/" }));
      const name = i === 0 ? rootLabel(path) : basename(path);
      const crumb = h("span", { className: "jse-crumb", textContent: visible(name), title: visible(path) });
      crumb.addEventListener("click", () => x.navigate(path));
      crumbs.append(crumb);
    });
    pathEl.replaceChildren(crumbs);
    upBtn.disabled = chain.length < 2;
  }

  upBtn.addEventListener("click", () => {
    const chain = x.ancestors(model.get("_current_dir"));
    if (chain.length > 1) x.navigate(chain[chain.length - 2]);
  });
  refreshBtn.addEventListener("click", () => model.send({ type: "refresh" }));
  // "Edit configuration" opens the launcher's settings file in JupyterLab's
  // editor: only in its tabs (the kernel sets _settings_path), with the
  // launcher's extension.
  function showSettingsMenu() {
    const items = [];
    if (sidebar) {
      const on = x.unsafe.on();
      items.push(
        {
          label: on ? "Unsafe mode: on" : "Unsafe mode: off",
          icon: on ? "check" : null,
          title: x.unsafe.el.title,
          action: () => x.unsafe.set(!on),
        },
        "-",
      );
    }
    const path = model.get("_settings_path");
    if (path && x.jupyterlab.canOpenSettings()) {
      items.push({
        label: "Edit configuration",
        icon: "edit",
        title: `${visible(path)}\nReload the web browser, then open the explorer tab again to apply the changes.`,
        action: () => void x.jupyterlab.openSettings(),
      });
    }
    items.push({ label: "About", icon: "info", action: () => void x.about.show() });
    x.menu.showBelow(settingsBtn, items);
  }

  settingsBtn.addEventListener("click", () => {
    if (x.menu.isOpenFrom(settingsBtn)) x.menu.hide();
    else showSettingsMenu();
  });

  return { el, pathBar, slot, renderPath, renderTreeButton, renderUnsafe };
}

// "Unsafe mode": while on, risky operations are offered (today: moving,
// copying, pasting, renaming and deleting folders). Any operation turns it
// off as it starts, risky or not (take), so it allows one operation at a
// time. The kernel refuses folders unless the request says it was on
// ("unsafe").
function createUnsafe(x) {
  const { model } = x;
  // A slider at the right end of the toolbar. The checkbox is hidden but
  // still focusable (Space toggles it); the track and knob are drawn by CSS.
  const input = h("input", { type: "checkbox", role: "switch", className: "jse-switch-input" });
  const el = h(
    "label",
    {
      className: "jse-unsafe",
      title:
        "For the next operation only: allows risky operations (moving, copying, pasting, renaming and deleting folders). " +
        "Turns off when any operation starts.",
    },
    input,
    h("span", { className: "jse-switch", ariaHidden: "true" }),
    h("span", { textContent: "Unsafe mode" }), // grey, red while on
  );

  const on = () => model.get("_unsafe_mode");

  // Also from the settings menu, in the sidebar layout (no switch there).
  function set(value) {
    model.set("_unsafe_mode", value);
    model.save_changes();
  }

  input.addEventListener("change", () => set(input.checked));

  return {
    el,
    on,
    set,
    render() {
      input.checked = on();
      el.classList.toggle("jse-on", on());
    },
    // Whether the switch is on for an operation starting now; turns it off.
    take() {
      const was = on();
      if (was) {
        model.set("_unsafe_mode", false);
        model.save_changes();
      }
      return was;
    },
  };
}

// Bookmarks: folders, kept by the kernel (its ExplorerStates, shared with
// other explorers); the list is asked for each time the menu opens.
function createBookmarks(x) {
  const { model, request } = x;
  // Opens the bookmarks menu; a filled star while the folder shown is bookmarked.
  const button = iconButton("star-border", "Bookmarks", "jse-bookmark-btn");
  // [{filesystem, path, url, label}] as last received: for the button's star
  // and the folders' "Add/Remove bookmark".
  let bookmarks = [];

  function set(reply) {
    if (reply.error) {
      x.flash(reply.error);
      return;
    }
    bookmarks = reply.bookmarks;
    render();
  }

  async function load() {
    set(await request({ type: "bookmarks" }));
  }

  function isBookmarked(path, filesystem = model.get("_filesystem")) {
    return bookmarks.some((b) => b.filesystem === filesystem && b.path === path);
  }

  function render() {
    const marked = isBookmarked(model.get("_current_dir"));
    button.replaceChildren(icon(marked ? "star" : "star-border"));
    button.classList.toggle("jse-on", marked);
  }

  const add = async (path) => set(await request({ type: "bookmark_add", path }));
  const remove = async ({ filesystem, path }) => set(await request({ type: "bookmark_remove", filesystem, path }));

  async function open({ filesystem, path }) {
    const reply = await request({ type: "bookmark_open", filesystem, path });
    if (reply.error) x.flash(`Cannot open the bookmark: ${reply.error}`);
  }

  // The menu item adding or removing the bookmark of folder `path` of the storage shown.
  function item(path) {
    const filesystem = model.get("_filesystem");
    return isBookmarked(path)
      ? { label: "Remove bookmark", icon: "star-border", action: () => remove({ filesystem, path }) }
      : { label: "Add bookmark", icon: "star", action: () => add(path) };
  }

  // The bookmarks menu, below the button: bookmarking the folder shown, then
  // the bookmarks ("[storage] path", in the kernel's order); right-click one
  // for "Copy URL", "Copy path" (local folders) and "Delete bookmark".
  async function showMenu() {
    await load();
    const current = model.get("_current_dir");
    const label = isBookmarked(current) ? "Remove this folder's bookmark" : "Bookmark this folder";
    const items = [{ ...item(current), label }, "-"];
    if (!bookmarks.length) items.push({ label: "No bookmarks", disabled: true });
    for (const b of bookmarks) {
      items.push({
        label: b.label,
        icon: "folder",
        title: b.url ?? b.path,
        action: () => open(b),
        menu: () => [
          { label: "Copy URL", icon: "link", disabled: !b.url, action: () => x.copyText([b.url], "URL") },
          ...(b.local_path ? [{ label: "Copy path", icon: "file", action: () => x.copyText([b.local_path], "path") }] : []),
          { label: "Delete bookmark", icon: "close", action: () => remove(b) },
        ],
      });
    }
    x.menu.showBelow(button, items);
  }

  button.addEventListener("click", () => {
    if (x.menu.isOpenFrom(button)) x.menu.hide();
    else void showMenu();
  });

  return { button, load, render, item };
}
