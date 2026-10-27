// The tree of folders (left), with the storage chooser above it. The kernel
// sends the folders it has listed (_tree: path -> subfolders); the tree asks
// for those of the folders opened ("expand").

// At most this many subfolders of a folder below the root are shown in the
// tree, so that opening a folder of thousands does not draw them all.
const TREE_FOLDERS = 50;

function createTree(x) {
  const { model } = x;
  const el = h("div", { className: "jse-tree" });
  // Storage chooser; hidden when there is only one. In the tree's bar while
  // the tree shows, else elsewhere (see placeStorages in storage_explorer.js).
  const fsSelect = h("select", { className: "jse-fs-select", title: "Filesystem" });
  const bar = h("div", { className: "jse-pane-bar" }, fsSelect);
  // Each pane is a column, its bar on top, so the bar follows the tree's width when it is resized.
  const pane = h("div", { className: "jse-pane jse-tree-pane" }, bar, el);
  // Hidden (closed or disabled, _tree_view), the tree is not drawn, nor are
  // its folders asked for; it is drawn again as it opens (onTreeView in
  // storage_explorer.js).
  const shown = () => model.get("_tree_view") === "open";

  // Expanded tree folders, kept per filesystem so switching back restores them.
  const expandedByFs = new Map();
  let expanded = new Set();
  // Set at first and when switching to a filesystem not shown before: its
  // root is expanded on the next render. Not left to showCurrent, which opens
  // the folders above the current one only (none when it is the root), and as
  // filesystems can share their root path (e.g. "" for DirFileSystems), when
  // neither _root nor _current_dir changes.
  let expandRoot = true;
  const pending = new Set(); // directories requested from the kernel but not yet in the tree
  // The filesystem whose folders `expanded` holds. Tracked here because
  // anywidget's model has no previous(): its API is get/set/save_changes/on/off/send.
  let shownFs = model.get("_filesystem");

  function requestChildren(path) {
    if (path in model.get("_tree") || pending.has(path)) return;
    pending.add(path);
    model.send({ type: "expand", path });
  }

  function toggle(path) {
    if (expanded.has(path)) {
      expanded.delete(path);
    } else {
      expanded.add(path);
      requestChildren(path);
    }
    render();
  }

  function render() {
    pane.hidden = !shown();
    if (!shown()) return;
    const tree = model.get("_tree");
    const root = model.get("_root");
    const current = model.get("_current_dir");

    for (const path of pending) if (path in tree) pending.delete(path);
    if (expandRoot) {
      expanded.add(root);
      expandRoot = false;
    }

    function node(dir, depth) {
      const children = tree[dir.path];
      const level = dir.level || null; // e.g. "container": _tree's entries, _root_level
      const isOpen = expanded.has(dir.path);
      if (isOpen) requestChildren(dir.path);

      const twisty = h("span", { className: "jse-twisty" }, ...(children && children.length === 0 ? [] : [icon(isOpen ? "caret-down" : "caret-right")]));
      twisty.addEventListener("click", (ev) => {
        ev.stopPropagation();
        toggle(dir.path);
      });
      // Not a double-click on the row: the twisty's two clicks toggled already.
      twisty.addEventListener("dblclick", (ev) => ev.stopPropagation());

      const row = h(
        "div",
        { className: "jse-node" + (dir.path === current ? " jse-active" : ""), title: visible(dir.path) },
        twisty,
        h("span", { className: "jse-icon" }, fileIcon(dir.name, true)),
        h("span", { className: "jse-label", textContent: visible(dir.name) }),
      );
      row.style.paddingLeft = `${depth * 14 + 4}px`;
      row.dataset.dropDir = dir.path; // files dropped here are uploaded into this folder
      // For styling by depth, e.g. [data-depth="1"]: 0 is the root, 1 a top-level folder.
      row.dataset.depth = depth;
      // And by the storage's level, e.g. [data-fs-level="container"].
      if (level) row.dataset.fsLevel = level;
      // A click selects the folder (shows it in the list); a double-click, or
      // the twisty, opens or closes it in the tree, as in tree views elsewhere.
      row.addEventListener("click", () => x.navigate(dir.path));
      row.addEventListener("dblclick", () => toggle(dir.path));
      // Clicking a tree folder already opens it: its menu has no "Open".
      row.addEventListener("contextmenu", (ev) => x.menu.show(ev, x.itemMenu([{ ...dir, type: "directory" }], false)));

      const wrap = h("div", {}, row);
      // Open, its folders still listed by the kernel.
      if (isOpen && !children) {
        const note = h("div", { className: "jse-node jse-tree-more jse-tree-loading", textContent: "Loading…" });
        note.style.paddingLeft = `${(depth + 1) * 14 + 4 + 16}px`; // aligned with the folders' icons
        wrap.append(note);
      }
      if (isOpen && children) {
        const shown = shownChildren(children, depth);
        for (const child of shown) wrap.append(node(child, depth + 1));
        const more = children.length - shown.length;
        if (more) {
          const note = h("div", {
            className: "jse-node jse-tree-more",
            textContent: `plus ${plural(more, "folder")}`,
          });
          note.style.paddingLeft = `${(depth + 1) * 14 + 4 + 16}px`; // aligned with the folders' icons
          wrap.append(note);
        }
      }
      return wrap;
    }

    // The root's folders, all; below, the first TREE_FOLDERS (the rest are in
    // the list), and the one leading to the current folder if after those.
    function shownChildren(children, depth) {
      if (depth === 0 || children.length <= TREE_FOLDERS) return children;
      const shown = children.slice(0, TREE_FOLDERS);
      const onPath = children.slice(TREE_FOLDERS).find((c) => current === c.path || current.startsWith(`${c.path}/`));
      if (onPath) shown.push(onPath);
      return shown;
    }

    // The root's menu offers no previews, code or copying (no_url).
    el.replaceChildren(node({ name: rootName(root), path: root, no_url: true, level: model.get("_root_level") }, 0));
    el.querySelector(".jse-active")?.scrollIntoView({ block: "nearest" });
  }

  // A root of just "/" (e.g. memory://, or a DirFileSystem's "") does not tell
  // filesystems apart, so with several, the tree names the one shown too:
  // "/ [Scratch (memory)]".
  function rootName(root) {
    const label = rootLabel(root);
    if (label !== "/" || model.get("_filesystem_names").length < 2) return label;
    return `${label} [${model.get("_filesystem")}]`;
  }

  // The folders leading to the current one are opened, so it shows in the
  // tree; the current one is not (a double-click or its twisty opens it).
  // Only folders under the root belong to this filesystem's tree.
  function showCurrent() {
    const current = model.get("_current_dir");
    if (current.startsWith(model.get("_root"))) {
      for (const path of x.ancestors(current).slice(0, -1)) expanded.add(path);
    }
    render();
  }

  function renderStorages() {
    const names = model.get("_filesystem_names");
    fsSelect.replaceChildren(...names.map((name) => h("option", { value: name, textContent: name })));
    fsSelect.value = model.get("_filesystem");
    fsSelect.hidden = names.length < 2;
  }

  // Keeps the tree's expanded folders of the filesystem left, and restores
  // those of the one switched to. The kernel restores its current folder.
  function onStorageChange() {
    const name = model.get("_filesystem");
    if (name === shownFs) return;
    expandedByFs.set(shownFs, expanded);
    expanded = expandedByFs.get(name) ?? new Set();
    expandRoot = !expandedByFs.has(name);
    shownFs = name;
    pending.clear();
    fsSelect.value = name;
  }

  fsSelect.addEventListener("change", () => {
    model.set("_filesystem", fsSelect.value);
    model.save_changes();
  });

  return { pane, bar, fsSelect, shown, render, showCurrent, renderStorages, onStorageChange };
}
