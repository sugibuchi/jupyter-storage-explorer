// Storage Explorer: directory tree (left) and file list (right), with a
// preview panel below them. Its features are in storage_explorer/, each a
// create function given the explorer, `x` below; they are joined before this
// file, after icons.js, common.js and query.js (see _static.py).

function render({ model, el }) {
  // Requests answered by a {"type": "reply", "rid"} message.
  const { request, onReply } = createRequester(model);
  // Small confirmation dialog, e.g. "Upload sales.csv? [Cancel] [Upload]";
  // over the whole window in the side panel, which is too narrow for it.
  const confirm = createConfirm(model.get("_layout") === "sidebar");

  // The explorer: what its features share, and the features themselves (set
  // below), which use each other through it once all are made.
  const x = {
    model,
    el,
    request,
    ask: confirm.ask,
    answer: confirm.answer,
    // A short message in the status bar, in place of the item count.
    // A short notice; with { error: true }, an error that stays until clicked.
    flash: (message, options) => x.list.flash(message, options),
    // The kernel identifies formats by name (e.g. "delta"); users see their label.
    formatLabel: (name) => model.get("_format_labels")[name] ?? name,
    navigate(path) {
      model.set("_current_dir", path);
      model.save_changes();
    },
    // Directories from the root down to and including `path`.
    ancestors(path) {
      const root = model.get("_root");
      if (!path.startsWith(root)) return [path];
      const out = [root];
      let cur = root;
      for (const segment of path.slice(root.length).split("/").filter(Boolean)) {
        cur = join(cur, segment);
        out.push(cur);
      }
      return out;
    },
    // The storage shown, as files copied or dragged name it: {name}. An
    // explorer of another kernel finds them by their locations instead.
    storage: () => ({ name: model.get("_filesystem") }),
    // The locations of items ({path}), from the kernel: the listing does not
    // carry them. Each {url, path: a local item's plain path (else null),
    // location: its JSON, which files copied or dragged carry}, or null.
    // Rejects on the kernel's error, flashed unless `quiet` (the tooltips').
    async locationsOf(items, { quiet = false } = {}) {
      const { locations, error } = await request({ type: "locations", paths: items.map((t) => t.path) });
      if (error) {
        if (!quiet) x.flash(`Cannot find the locations: ${visible(error)}`, { error: true });
        throw new Error(error);
      }
      return locations;
    },
    // Puts `lines` on the system clipboard; `what` they are, for the message.
    async copyText(lines, what) {
      try {
        await navigator.clipboard.writeText(lines.join("\n"));
        x.flash(`Copied ${what}`);
      } catch {
        x.flash("Copy failed: the browser denied clipboard access", { error: true });
      }
    },
  };
  x.busy = createBusy();
  // Over the whole window in the side panel, which is too narrow for it.
  x.modal = createModal(el, model.get("_layout") === "sidebar");
  x.menu = createMenu();
  x.jobs = createJobs(x);
  x.unsafe = createUnsafe(x);
  x.bookmarks = createBookmarks(x);
  x.toolbar = createToolbar(x);
  x.tree = createTree(x);
  x.list = createList(x);
  x.preview = createPreview(x);
  x.engine = createEngine(x);
  x.itemMenu = createItemMenu(x);
  x.operations = createOperations(x);
  x.clipboard = createClipboard(x);
  x.transfers = createTransfers(x);
  x.jupyterlab = createJupyterLab(x);
  x.properties = createProperties(x);
  x.about = createAbout(x);
  x.mapperCss = createMapperCss(x);
  // Keys in the file list: Ctrl+C, Ctrl+X, Ctrl+V, F2, Delete, Enter.
  createShortcuts(x).attach(x.list.pane);

  // Lets Markdown previews load the vendored libraries through this widget's kernel.
  fetchVendor = async (name) => {
    const reply = await request({ type: "vendor", name });
    if (reply.error) throw new Error(reply.error);
    return reply.source;
  };

  // --- Layout ---

  // Tree and list; their height is the `height` trait until resized by dragging.
  const panesEl = h("div", { className: "jse-panes" }, x.tree.pane, x.list.pane);
  x.transfers.attach(panesEl);
  // Bottom edge of the widget: resizes the last area (preview panel or tree and list).
  const grip = h("div", { className: "jse-grip", title: "Drag to resize" });
  // "jse-browser" is for user styles too, e.g. icons by [data-depth] (DEVELOPMENT.md),
  // with the storage shown's protocol, e.g. .jse-browser[data-fs-protocol="s3"],
  // and its mapper, whose CSS shows its storages (mapper_css.js).
  el.classList.add("jse-widget", "jse-browser");
  const renderProtocol = () => (el.dataset.fsProtocol = model.get("_fs_protocol"));
  // The narrow layout of JupyterLab's side bar (the launcher's side panel):
  // two bars (toolbar.js), the pager below the list (list.js) and fewer
  // columns (the CSS).
  const sidebar = model.get("_layout") === "sidebar";
  el.classList.toggle("jse-sidebar", sidebar);
  // Focusable, so Escape reaches the widget after a click anywhere in it.
  el.tabIndex = -1;
  // Keep JupyterLab's notebook shortcuts (e.g. "dd" deletes a cell) from
  // firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  // The status bar (messages on the left, the engine and Preview on the right) belongs to
  // the list, so it stays under it, above the preview panel: Preview and the
  // item count stay in view when the panel opens. The jobs running are above it.
  el.replaceChildren(
    x.toolbar.el,
    ...(x.toolbar.pathBar ? [x.toolbar.pathBar] : []),
    panesEl,
    x.jobs.el,
    h("div", { className: "jse-status-bar" }, x.list.statusEl, x.engine.button, x.preview.button),
    x.preview.el,
    grip,
    ...(x.modal.el ? [x.modal.el] : []),
    ...(confirm.el ? [confirm.el] : []),
    x.busy.el,
  );

  // Resizing by dragging; heights set here are kept until `height` changes.
  const MIN_AREA_HEIGHT = 80;

  // The splitter moves the boundary: the list gains what the panel loses.
  onDragY(x.preview.splitter, () => {
    const panes = panesEl.offsetHeight;
    const panel = x.preview.el.offsetHeight;
    return (dy) => {
      const d = Math.max(MIN_AREA_HEIGHT - panes, Math.min(panel - MIN_AREA_HEIGHT, dy));
      panesEl.style.height = `${panes + d}px`;
      x.preview.el.style.height = `${panel - d}px`;
    };
  });

  // The bottom grip resizes the last area, so the whole widget grows or shrinks.
  onDragY(grip, () => {
    const area = x.preview.isOpen() ? x.preview.el : panesEl;
    const start = area.offsetHeight;
    return (dy) => (area.style.height = `${Math.max(MIN_AREA_HEIGHT, start + dy)}px`);
  });

  // "fill": the widget fills its container (see "jse-fill" in the CSS);
  // otherwise the CSS height of the tree and list.
  function applyHeight() {
    const height = model.get("_height");
    el.classList.toggle("jse-fill", height === "fill");
    el.style.setProperty("--jse-height", height === "fill" ? "" : height);
    panesEl.style.height = ""; // a new `height` replaces any dragged size
  }

  // The storage chooser: in the toolbar in the sidebar layout; else above the
  // tree while it shows, or first in the list's bar while it is hidden.
  function placeStorages() {
    const select = x.tree.fsSelect;
    if (sidebar) x.toolbar.slot.append(select);
    else if (x.tree.shown()) x.tree.bar.append(select);
    else x.list.bar.prepend(select);
  }

  // The tree opened or closed (its button, toolbar.js).
  function onTreeView() {
    x.toolbar.renderTreeButton();
    placeStorages();
    x.tree.showCurrent(); // draws it as it opens; hides it
  }

  el.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (x.modal.isOpen()) x.modal.close();
    else if (x.preview.isOpen()) x.preview.close();
    else return;
    ev.stopPropagation();
  });

  // --- The model's changes and messages ---

  function onDirChange() {
    x.tree.showCurrent();
    x.toolbar.renderPath();
    x.bookmarks.render();
    // Tells whoever contains the explorer which storage and folder it shows:
    // the launcher's tab keeps them, to reopen there (its index.ts).
    // Elsewhere, e.g. in a notebook, nobody listens.
    const detail = { filesystem: model.get("_filesystem"), folder: model.get("_current_dir") };
    el.dispatchEvent(new CustomEvent("jupyter-storage-explorer:view", { bubbles: true, detail }));
  }

  function onCustomMsg(msg, buffers) {
    if (msg.type === "download") x.transfers.onDownload(msg, buffers);
    else if (msg.type === "reply") onReply(msg);
    else if (msg.type === "job") x.jobs.onJob(msg);
    else if (msg.type === "view_tab") x.jupyterlab.onViewTab(msg);
    // The kernel calls on_change's functions as it handles this answer, so
    // that an Output's with block shows what they display.
    else if (msg.type === "callbacks") model.send({ type: "callbacks", name: msg.name });
  }

  const handlers = {
    "change:_tree": x.tree.render,
    "change:_current_dir": onDirChange,
    // The address bar starts at the root, which differs per filesystem.
    "change:_root": onDirChange,
    "change:_filesystem": () => {
      x.tree.onStorageChange();
      x.bookmarks.render(); // the folder's path may be the same as on the storage left
    },
    "change:_filesystem_names": x.tree.renderStorages,
    "change:_fs_protocol": renderProtocol,
    "change:_fs_mapper": x.mapperCss.render,
    "change:_mapper_css": x.mapperCss.render,
    // Sent with the storage's _root, which draws the tree again.
    "change:_root_level": x.tree.render,
    "change:_listing": x.list.render,
    "change:_selected": x.list.render,
    "change:_columns": x.list.render,
    "change:_error": x.list.renderStatus,
    "change:_height": applyHeight,
    "change:_tree_view": onTreeView,
    "change:_preview": () => {
      x.preview.render();
      x.preview.updateButton(); // "Close preview" while the panel shows the selected item
    },
    "change:_current_format": x.preview.updateButton,
    "change:_selected_format": () => {
      x.preview.updateButton();
      x.preview.followFolder(); // a data folder selected, while the panel is open
    },
    "change:_unsafe_mode": () => {
      x.unsafe.render();
      x.toolbar.renderUnsafe();
    },
    "change:_engines": x.engine.render,
    "change:_engine": x.engine.render,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  applyHeight();
  renderProtocol();
  x.mapperCss.render();
  x.toolbar.renderTreeButton();
  placeStorages();
  x.tree.renderStorages();
  x.unsafe.render();
  x.toolbar.renderUnsafe();
  x.engine.render();
  onDirChange();
  x.list.render();
  x.preview.render();
  void x.bookmarks.load(); // for the star

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
    x.clipboard.dispose();
    x.transfers.dispose();
    x.menu.hide();
    x.list.dispose();
    x.preview.dispose();
  };
}

export default { render };
