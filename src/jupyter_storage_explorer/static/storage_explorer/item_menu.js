// The right-click menu of items of the list and the tree. Some rows depend
// on the item's formats, which only the kernel knows ("menu_info"): "Preview
// as", "Query data" and "Python code", filled in when its reply arrives.

// Returns itemMenu(targets, withOpen = true): the menu items for one or more
// items ({path, type, no_url}). The tree passes withOpen = false: clicking a
// tree folder already opens it.
function createItemMenu(x) {
  const { model, request } = x;
  // For the open menu: {path, previewRow, queryTabRow, previewAsRow, previewAsSub, codeRow, codeSub},
  // the elements to fill when the kernel's "menu_info" reply arrives.
  let menuInfo = null;

  // The rows are set (by the menu's `ref`s) before the reply arrives.
  function requestMenuInfo(path) {
    const info = { path };
    menuInfo = info;
    request({ type: "menu_info", path }).then((reply) => onMenuInfo(info, reply));
    return info;
  }

  // `info`: the menu the request was for; ignored once another has opened.
  function onMenuInfo(info, msg) {
    if (menuInfo !== info) return;
    const { path, previewRow, previewAsRow, previewAsSub, codeRow, codeSub } = info;
    // A folder's rows, hidden until now: shown if it has a format (an error
    // shows in "Python code").
    if (msg.error || msg.formats.length) codeRow.hidden = false;
    if (!msg.error && msg.formats.length) previewRow.hidden = false;
    if (!msg.error && msg.query) {
      previewRow.querySelector(".jse-menu-label").textContent = "Query data";
      info.queryTabRow.hidden = !x.jupyterlab.canOpenQueryTab();
    }
    // "Preview as" only appears when the item matches more than one format.
    if (!msg.error && msg.formats.length > 1) {
      const items = msg.formats.map((format) => ({ label: `Preview as ${x.formatLabel(format)}`, action: () => x.preview.open(path, format) }));
      previewAsSub.replaceChildren(...x.menu.rows(items));
      previewAsRow.hidden = false;
    }
    let items;
    if (msg.error) {
      items = [{ label: msg.error, disabled: true }];
    } else if (!msg.recipes.length) {
      items = [{ label: "No code for this item", disabled: true }];
    } else {
      items = msg.recipes.map((recipe) => ({
        label: `Load with ${recipe.library}`,
        action: () => x.modal.show(`Load with ${recipe.library}`, recipeBlocks(recipe)),
      }));
    }
    codeSub.replaceChildren(...x.menu.rows(items));
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
    // Opening comes first, as in JupyterLab's file browser.
    const open = [];
    if (single && x.jupyterlab.canOpen(single)) {
      open.push({ label: "Open in JupyterLab", icon: "open-in-new", action: () => x.jupyterlab.open(single.path) });
    }
    if (withOpen && folder) open.push({ label: "Open", icon: "folder", action: () => x.navigate(folder.path) });
    if (info) {
      // Only for what has a format: a file's is in the listing; whether a
      // folder has one (a Delta table, a Parquet dataset) only the kernel
      // tells (onMenuInfo), so its rows appear then.
      const hasFormat = !isFolder(data) && Boolean(data.format);
      open.push(
        {
          label: "Preview",
          icon: "eye",
          hidden: !hasFormat,
          // Relabelled "Query data" when the kernel says it opens in the data browser.
          ref: (row) => (info.previewRow = row),
          action: () => x.preview.open(single.path),
        },
        {
          // Shown when the kernel says it opens in the data browser.
          label: "Query data in new tab",
          icon: "open-in-new",
          hidden: true,
          ref: (row) => (info.queryTabRow = row),
          action: () => x.jupyterlab.openQueryTab(single.path),
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
    // Locations are copied only as URLs: fsspec's paths can differ from the
    // storage's own notion of a path (e.g. abfs's "container/key"). Files'
    // URLs also come with "Copy" below, so "Copy URL" is for folders, which
    // "Copy" leaves to unsafe mode.
    if (withUrls && !files) {
      open.push({
        label: `Copy ${count}URL${count ? "s" : ""}`,
        icon: "link",
        action: async () => x.copyText(await x.urlsOf(targets), count ? `${count}URLs` : "URL"),
      });
    }

    // "Copy" and "Cut" copy for "Paste" (and put the URLs on the clipboard).
    const clipboard = [];
    if (withUrls && allowed) {
      clipboard.push({ label: count ? `Copy ${count}${what}` : "Copy", icon: "copy", action: () => x.clipboard.copyFiles(targets) });
      if (!targets.some((t) => t.path === model.get("_root"))) {
        clipboard.push({ label: count ? `Cut ${count}${what}` : "Cut", icon: "cut", action: () => x.clipboard.copyFiles(targets, true) });
      }
    }
    const paste = folder && x.clipboard.pasteItem(folder.path);
    if (paste) clipboard.push(paste);

    const change = [];
    if (folder) change.push({ label: "Create a folder", icon: "new-folder", action: () => x.operations.createFolder(folder.path) });
    if (single && allowed && single.path !== model.get("_root")) {
      change.push({ label: "Rename", icon: "edit", action: () => x.operations.rename(single) });
    }
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

    return [open, clipboard, change, downloads, about].filter((group) => group.length).flatMap((group, i) => (i ? ["-", ...group] : group));
  };
}
