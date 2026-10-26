// The toolbar: the tree's button, bookmarks, Up, Refresh, the folder's path,
// Unsafe mode, and the settings menu: the list's Columns, "Edit
// configuration" in the launcher's tabs, "About". The sidebar layout has two narrower bars: the storage
// chooser (slot), bookmarks, Refresh, the filter button (the list's filter,
// hidden until it is pressed) and the settings menu, whose first item is
// then Unsafe mode; below (pathBar), Up and the folder's path.

function createToolbar(x) {
  const { model } = x;
  const sidebar = model.get("_layout") === "sidebar";
  // Shows or hides the folder tree (_tree_view); none without a tree.
  const treeBtn = iconButton("tree", "Folder tree", "jse-tree-btn");
  const upBtn = iconButton("up", "Parent directory");
  const refreshBtn = iconButton("refresh", "Refresh");
  const pathEl = h("div", { className: "jse-path" });
  const settingsBtn = iconButton("settings", "Settings", "jse-settings-btn");
  // The sidebar layout's filter button, left of the settings: shows or hides
  // the list's filter (list.js' showFilter), as JupyterLab's file browser's.
  const filterBtn = iconButton("filter", "Show the filter", "jse-filter-btn");
  // Where the storage chooser goes in the sidebar layout (see placeStorages
  // in storage_explorer.js); it takes the bar's room left by the buttons.
  const slot = h("div", { className: "jse-storage-slot" });
  const el = sidebar
    ? h("div", { className: "jse-toolbar" }, treeBtn, slot, x.bookmarks.button, refreshBtn, filterBtn, settingsBtn)
    : h("div", { className: "jse-toolbar" }, treeBtn, x.bookmarks.button, upBtn, refreshBtn, pathEl, x.unsafe.el, settingsBtn);
  const pathBar = sidebar ? h("div", { className: "jse-path-bar" }, upBtn, pathEl) : null;

  // In the sidebar layout, Unsafe mode is in the settings menu: while it is
  // on, the settings button is red, as the switch would be.
  function renderUnsafe() {
    const on = sidebar && x.unsafe.switchable() && x.unsafe.on();
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

  filterBtn.addEventListener("click", () => {
    const on = !x.list.filterShown();
    x.list.showFilter(on);
    filterBtn.classList.toggle("jse-on", on);
    filterBtn.title = filterBtn.ariaLabel = on ? "Hide the filter" : "Show the filter";
  });

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
    const root = rootLabel(chain[0]);
    chain.forEach((path, i) => {
      // Not after a root ending with "/" ("/", "C:/"): "/ data", not "/ / data".
      if (i > 1 || (i === 1 && !root.endsWith("/"))) crumbs.append(h("span", { className: "jse-sep", textContent: "/" }));
      const name = i === 0 ? root : basename(path);
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
  // editor, only in its tabs; "Actions", "Edit" the user's actions file. Both
  // need the launcher's extension, and come from the kernel's _config_paths.
  // "Actions" is there only if user_actions is enabled: the kernel then
  // offers the actions file.
  function showSettingsMenu() {
    const items = [];
    if (sidebar && x.unsafe.switchable()) {
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
    // The list's columns besides Name (_columns, remembered by the kernel),
    // each shown or hidden with a click.
    const chosen = model.get("_columns");
    const toggle = (key) => {
      const next = chosen.includes(key) ? chosen.filter((k) => k !== key) : [...chosen, key];
      model.set(
        "_columns",
        LIST_COLUMNS.map((col) => col.key).filter((k) => next.includes(k)),
      );
      model.save_changes();
    };
    items.push({
      label: "Columns",
      icon: "columns",
      submenu: (sub) =>
        sub.replaceChildren(
          ...x.menu.rows(
            LIST_COLUMNS.filter((col) => col.key !== "name").map((col) => ({
              label: col.label,
              icon: chosen.includes(col.key) ? "check" : null,
              action: () => toggle(col.key),
            })),
          ),
        ),
    });
    const paths = model.get("_config_paths");
    if (x.jupyterlab.canOpenSettings() && paths.launcher) {
      items.push({
        label: "Edit configuration",
        icon: "edit",
        title: `${visible(paths.launcher)}\nOpen a new Storage Explorer tab, or reload the page, to apply the changes.`,
        action: () => void x.jupyterlab.openSettings("launcher"),
      });
    }
    if (paths.actions) {
      const actions = [];
      if (x.jupyterlab.canOpenSettings()) {
        actions.push({
          label: "Edit",
          icon: "edit",
          title: `${visible(paths.actions)}\nReload, in this menu, to apply the changes.`,
          action: () => void x.jupyterlab.openSettings("actions"),
        });
      }
      // Without the extension too: the kernel reads the files itself.
      actions.push({
        label: "Reload",
        icon: "refresh",
        title: `Read ${visible(paths.actions)} and the other actions files again.`,
        action: () => void reloadActions(),
      });
      items.push({
        label: "Actions",
        icon: "bolt",
        submenu: (sub) => sub.replaceChildren(...x.menu.rows(actions)),
      });
    }
    items.push({ label: "About", icon: "info", action: () => void x.about.show() });
    x.menu.showBelow(settingsBtn, items);
  }

  // "Actions", "Reload": the kernel reads the user's actions files again and
  // lists the folder again ("reload_actions"). A file left out, e.g. with a
  // syntax error, is flashed as an error; the others' actions are used.
  async function reloadActions() {
    const reply = await x.request({ type: "reload_actions" });
    if (reply.error) {
      x.flash(`Cannot reload actions: ${visible(reply.error)}`, { error: true });
    } else if (reply.problems.length) {
      x.flash(reply.problems.map(visible).join("\n"), { error: true });
    } else {
      x.flash(`Actions reloaded: ${reply.actions} of yours`);
    }
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
// ("unsafe"). That is the explorer's unsafe_mode "on_demand"
// (_unsafe_policy); with "always" or "blocked", there is no switch, and
// folder operations are offered at all times, or never (the kernel decides).
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

  const policy = () => model.get("_unsafe_policy");
  // Whether the user turns it on and off: else it is always on, or never.
  const switchable = () => policy() === "on_demand";
  const on = () => (switchable() ? model.get("_unsafe_mode") : policy() === "always");

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
    switchable,
    render() {
      el.hidden = !switchable();
      input.checked = on();
      el.classList.toggle("jse-on", on());
    },
    // Whether folder operations are allowed for an operation starting now;
    // turns the switch off.
    take() {
      const was = on();
      if (was && switchable()) {
        model.set("_unsafe_mode", false);
        model.save_changes();
      }
      return was;
    },
    // Why `action` (e.g. "move folders") is refused: the switch is off, or
    // this explorer never does it.
    refusal(action) {
      return switchable() ? `Turn on unsafe mode to ${action}` : `This explorer does not ${action}`;
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
      x.flash(reply.error, { error: true });
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
    if (reply.error) x.flash(`Cannot open the bookmark: ${reply.error}`, { error: true });
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
