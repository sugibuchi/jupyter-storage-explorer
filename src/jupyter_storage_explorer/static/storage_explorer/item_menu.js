// The right-click menu of items of the list and the tree. Some rows depend
// on the item's formats and the engine chosen, which only the kernel knows
// ("menu_info"): "Preview <format>" and "View <format> in new tab" (disabled
// when the engine chosen cannot view the item), "Preview as" and "View in
// new tab as" (each format and engine that can), and "Python code" (each
// recipe, with its engine), filled in when its reply arrives.

// Returns itemMenu(targets, withOpen = true): the menu items for one or more
// items ({path, type, no_url}). The tree passes withOpen = false: clicking a
// tree folder already opens it.
function createItemMenu(x) {
  const { model, request } = x;
  // For the open menu: {path, previewRow, viewTabRow, previewAsRow,
  // previewAsSub, viewTabAsRow, viewTabAsSub, codeRow, codeSub}, the
  // elements to fill when the kernel's "menu_info" reply arrives.
  let menuInfo = null;

  // The rows are set (by the menu's `ref`s) before the reply arrives.
  function requestMenuInfo(path) {
    const info = { path };
    menuInfo = info;
    request({ type: "menu_info", path }).then((reply) => onMenuInfo(info, reply));
    return info;
  }

  const canTab = () => x.jupyterlab.canOpenViewTab();
  // No "Preview" rows without a preview panel (preview_panel="disabled").
  const canPreview = () => x.preview.enabled();

  // "Preview <format>" and "View <format> in new tab": with the engine
  // chosen, so the kernel picks it; disabled if it cannot view the item.
  const previewItem = (path, label, view) => ({
    label: `Preview ${label}`,
    icon: "eye",
    disabled: !view,
    title: view ? "" : "The engine chosen cannot view it: see Preview as",
    action: () => x.preview.open(path),
  });
  const viewTabItem = (path, label, view) => ({
    label: `View ${label} in new tab`,
    icon: "open-in-new",
    disabled: !view,
    title: view ? "" : "The engine chosen cannot view it: see View in new tab as",
    action: () => x.jupyterlab.openViewTab(path),
  });

  // `info`: the menu the request was for; ignored once another has opened.
  function onMenuInfo(info, msg) {
    if (menuInfo !== info) return;
    const { path } = info;
    // A folder's rows, hidden until now: shown if it has a format (an error
    // shows in "Python code").
    if (msg.error || msg.formats.length) info.codeRow.hidden = false;
    if (!msg.error && msg.formats.length) {
      // The best format's rows, now that the kernel says whether the engine
      // chosen can view it.
      const label = x.formatLabel(msg.formats[0]);
      if (canPreview()) {
        const [preview] = x.menu.rows([previewItem(path, label, msg.view)]);
        info.previewRow.replaceWith(preview);
      }
      if (canTab()) {
        const [viewTab] = x.menu.rows([viewTabItem(path, label, msg.view)]);
        info.viewTabRow.replaceWith(viewTab);
      }
    }
    // Each format and engine that can view it ("CSV (Polars)"), for either.
    if (!msg.error && msg.views.length) {
      const items = (open) => msg.views.map((v) => ({ label: v.label, action: () => open(path, v.format, v.engine) }));
      if (canPreview()) {
        info.previewAsSub.replaceChildren(...x.menu.rows(items(x.preview.open)));
        info.previewAsRow.hidden = false;
      }
      if (canTab()) {
        info.viewTabAsSub.replaceChildren(...x.menu.rows(items(x.jupyterlab.openViewTab)));
        info.viewTabAsRow.hidden = false;
      }
    }
    let items;
    if (msg.error) {
      items = [{ label: msg.error, disabled: true }];
    } else if (!msg.recipes.length) {
      items = [{ label: "No code for this item", disabled: true }];
    } else {
      // Each recipe, with the engine it loads with: "Load as DataFrame (Polars)".
      items = msg.recipes.map((recipe) => {
        const title = `${recipe.title} (${recipe.engine})`;
        return { label: title, action: () => x.modal.show(title, recipeBlocks(recipe)) };
      });
    }
    info.codeSub.replaceChildren(...x.menu.rows(items));
    x.menu.place(); // rows shown above may have pushed it out of the widget
  }

  return function itemMenu(targets, withOpen = true) {
    const single = targets.length === 1 ? targets[0] : null;
    const count = targets.length > 1 ? `${targets.length} ` : "";
    // Items without a URL (the kernel's _url gave None) are not treated as data:
    // no preview or code.
    const data = single && hasUrl(single) ? single : null;
    // The reply arrives after the menu is built, so the refs below are set by then.
    const info = data ? requestMenuInfo(data.path) : null;
    const folder = single && isFolder(single) ? single : null;
    const files = !targets.some(isFolder);
    // Folder operations are dangerous: offered only in unsafe mode.
    const allowed = files || x.unsafe.on();
    const what = files ? "files" : "items";
    const withUrls = targets.every(hasUrl);

    // Groups of items, joined by separators; groups left empty are dropped.
    const open = [];
    if (withOpen && folder) open.push({ label: "Open", icon: "folder", action: () => x.navigate(folder.path) });
    const viewAs = [];
    if (info) {
      // Only for what has a format: a file's is in the listing; whether a
      // folder has one (a Delta table, a Parquet dataset) only the kernel
      // tells (onMenuInfo), so its rows appear then.
      const hasFormat = !isFolder(data) && Boolean(data.format);
      const label = hasFormat ? x.formatLabel(data.format) : "";
      // Shown as offered until the reply tells whether the engine chosen can view it.
      open.push(
        { ...viewTabItem(single.path, label, true), hidden: !hasFormat || !canTab(), ref: (row) => (info.viewTabRow = row) },
        { ...previewItem(single.path, label, true), hidden: !hasFormat || !canPreview(), ref: (row) => (info.previewRow = row) },
      );
      viewAs.push(
        {
          // The same views in a JupyterLab tab of their own (with the launcher's extension).
          label: "View in new tab as",
          icon: "open-in-new",
          hidden: true,
          ref: (row) => (info.viewTabAsRow = row),
          submenu: (sub) => (info.viewTabAsSub = sub),
        },
        {
          label: "Preview as",
          icon: "eye",
          hidden: true,
          ref: (row) => (info.previewAsRow = row),
          submenu: (sub) => (info.previewAsSub = sub),
        },
        {
          label: "Python code",
          icon: "code",
          hidden: !hasFormat,
          ref: (row) => (info.codeRow = row),
          submenu: (sub) => {
            sub.replaceChildren(...x.menu.rows([{ label: "Loading…", disabled: true }]));
            info.codeSub = sub;
          },
        },
      );
    }

    // "Copy" and "Cut" copy for "Paste" (and put the URLs on the clipboard).
    const clipboard = [];
    if (withUrls && allowed) {
      clipboard.push({ label: count ? `Copy ${count}${what}` : "Copy", icon: "copy", action: () => x.clipboard.copyFiles(targets) });
      if (!targets.some((t) => t.path === model.get("_root"))) {
        clipboard.push({ label: count ? `Cut ${count}${what}` : "Cut", icon: "cut", action: () => x.clipboard.copyFiles(targets, true) });
      }
    }
    // Locations are copied as URLs, and on a local disk as plain paths too:
    // elsewhere fsspec's paths can differ from the storage's own notion of a
    // path (e.g. abfs's "container/key"). "Copy" above also puts files' URLs
    // on the clipboard, so "Copy URL" is for folders, which "Copy" leaves to
    // unsafe mode; on a local disk, "Copy" gives paths, so it is for files too.
    const local = model.get("_local_paths");
    if (withUrls && (!files || local)) {
      clipboard.push({
        label: `Copy ${count}URL${count ? "s" : ""}`,
        icon: "link",
        action: async () =>
          x.copyText(
            (await x.locationsOf(targets)).map((l) => l.url),
            count ? `${count}URLs` : "URL",
          ),
      });
    }
    if (withUrls && local) {
      clipboard.push({
        label: `Copy ${count}path${count ? "s" : ""}`,
        icon: "file",
        action: async () =>
          x.copyText(
            (await x.locationsOf(targets)).map((l) => l.path),
            count ? `${count}paths` : "path",
          ),
      });
    }
    const paste = folder && x.clipboard.pasteItem(folder.path);
    if (paste) clipboard.push(paste);

    const change = [];
    // "Edit": the file in JupyterLab's own editor or viewer, in a tab of its
    // own (so the icon of "View in new tab").
    if (single && x.jupyterlab.canOpen(single)) {
      change.push({ label: "Edit", icon: "open-in-new", action: () => x.jupyterlab.open(single.path) });
    }
    if (single && allowed && single.path !== model.get("_root")) {
      change.push({ label: "Rename", icon: "edit", action: () => x.operations.rename(single) });
    }
    if (folder) change.push({ label: "Create a folder", icon: "new-folder", action: () => x.operations.createFolder(folder.path) });
    if (allowed) change.push({ label: count ? `Delete ${count}${what}` : "Delete", icon: "close", action: () => x.operations.remove(targets) });

    // Files only: downloading folders is intentionally not supported. The
    // kernel refuses files the explorer's policy does not let go there.
    const downloads = [];
    if (files) {
      const paths = targets.map((t) => t.path);
      downloads.push(
        { label: count ? `Download ${count}files to local` : "Download to local", icon: "download", action: () => x.transfers.download(paths) },
        {
          label: count ? `Download ${count}files to JupyterLab` : "Download to JupyterLab",
          icon: "inbox",
          action: () => x.transfers.downloadToJupyterLab(paths),
        },
      );
    }

    const about = [{ label: "Properties", icon: "info", action: () => x.properties.show(targets) }];
    if (folder) about.push(x.bookmarks.item(folder.path));

    return [open, viewAs, clipboard, change, downloads, about].filter((group) => group.length).flatMap((group, i) => (i ? ["-", ...group] : group));
  };
}
