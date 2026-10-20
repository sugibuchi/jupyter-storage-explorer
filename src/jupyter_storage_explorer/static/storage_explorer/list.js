// The list of the folder's items (right), with its filter and pager above it
// and the status bar below. It is filtered (by name), sorted and paged (pages
// of PAGE_SIZE) here, from the whole listing the kernel sends (_listing, as
// columns; see _make_listing); folders of more than the explorer's
// max_browser_items are filtered, sorted and paged by the kernel instead.

const PAGE_SIZE = 100;

const LIST_COLUMNS = [
  { key: "name", label: "Name" },
  { key: "size", label: "Size" },
  { key: "mtime", label: "Modified" },
];

// Names with numbers in order ("2" before "10"), ignoring case and accents.
// One collator for all comparisons: localeCompare with options sets one up
// for each call, which made sorting a large folder by name slow.
const nameOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

// Items, {name, path, type, size, mtime, ctime, format, no_url}, from the
// kernel's columns (see _make_listing).
function decodeColumns(l) {
  const noUrl = new Set(l.no_url ?? []);
  return (l.names ?? []).map((name, i) => ({
    name,
    path: l.paths ? l.paths[i] : join(l.dir, name),
    type: l.is_dir[i] ? "directory" : "file",
    size: l.sizes[i],
    mtime: l.mtimes[i],
    ctime: l.ctimes?.[i],
    format: l.formats[l.format[i]],
    no_url: noUrl.has(i),
  }));
}

function createList(x) {
  const { model, request } = x;
  const sort = { key: "name", asc: true };
  let page = 0;
  // Set while typing in the filter: in large folders, the kernel is then
  // asked once typing pauses (see kernelPage).
  let filterTyped = false;
  const filter = createFilter({
    placeholder: "Filter by name",
    onChange() {
      page = 0;
      filterTyped = true;
      render();
    },
  });
  const prevPageBtn = iconButton("chevron-left", "Previous page");
  const nextPageBtn = iconButton("chevron-right", "Next page");
  const pageLabel = h("span", { className: "jse-page-label" });
  const pagerEl = h("div", { className: "jse-pager", hidden: true }, prevPageBtn, pageLabel, nextPageBtn);
  const headRow = h("tr");
  const tbody = h("tbody");
  const el = h("div", { className: "jse-list" }, h("table", {}, h("thead", {}, headRow), tbody));
  const pane = h("div", { className: "jse-pane jse-list-pane" }, h("div", { className: "jse-pane-bar" }, filter.el, pagerEl), el);
  const statusEl = h("div", { className: "jse-status" });

  // --- The listing, decoded and sorted ---

  // The current directory's items (_listing), decoded once per listing. None
  // for a large folder, paged by the kernel (see kernelPage).
  let decoded = { listing: null, entries: [] };

  function listedEntries() {
    const l = model.get("_listing");
    if (decoded.listing !== l) decoded = { listing: l, entries: decodeColumns(l) };
    return decoded.entries;
  }

  // The listed items with these paths (e.g. the selection). In a large folder,
  // from the pages received: items are only selected by clicking them on one.
  function entriesAt(paths) {
    const wanted = new Set(paths);
    const entries = kernelMode() ? kernelState().seen.values() : listedEntries();
    return [...entries].filter((e) => wanted.has(e.path));
  }

  function compare(a, b) {
    const aDir = isFolder(a);
    if (aDir !== isFolder(b)) return aDir ? -1 : 1;
    const r = sort.key === "name" ? nameOrder.compare(a.name, b.name) : (a[sort.key] ?? -Infinity) - (b[sort.key] ?? -Infinity);
    return sort.asc ? r : -r;
  }

  // The listing sorted, kept until the listing or the sort order changes, so
  // that filtering and paging (each keystroke, each page) only filter and
  // slice it.
  let sorted = { entries: null, key: null, asc: null, list: [] };

  function sortedEntries() {
    const entries = listedEntries();
    if (sorted.entries !== entries || sorted.key !== sort.key || sorted.asc !== sort.asc) {
      sorted = { entries, key: sort.key, asc: sort.asc, list: [...entries].sort(compare) };
    }
    return sorted.list;
  }

  // --- Large folders: filtered, sorted and paged by the kernel ---
  // For them, the kernel only sends their size (_listing.query) and pages
  // come from "list" requests. Replies are kept until the listing changes,
  // and the next page is fetched ahead. While an answer for a new filter is
  // awaited, the rows shown are filtered here, so typing shows its effect at
  // once.

  const kernelMode = () => Boolean(model.get("_listing").query);
  // listing: the _listing these are for; pages: query key -> reply (null
  // while asked); seen: path -> item, of the pages received; shown: the
  // reply last shown, in this folder.
  let kernelPages = { listing: null, pages: new Map(), seen: new Map(), shown: null };
  let filterTimer = null;

  function kernelState() {
    const l = model.get("_listing");
    if (kernelPages.listing !== l) {
      // A new version of the same folder: keep showing its last page until the new one arrives.
      const shown = kernelPages.listing?.dir === l.dir ? kernelPages.shown : null;
      kernelPages = { listing: l, pages: new Map(), seen: new Map(), shown };
    }
    return kernelPages;
  }

  function kernelQuery(wanted = page) {
    const l = model.get("_listing");
    const query = filter.query();
    return {
      dir: l.dir,
      version: l.version,
      text: query?.text ?? "",
      regex: query?.regex ?? false,
      sort: sort.key,
      asc: sort.asc,
      page: wanted,
      page_size: PAGE_SIZE,
    };
  }

  // Asks for a page, unless already asked; shows it if it is still the one wanted.
  async function fetchPage(query) {
    const state = kernelState();
    const key = JSON.stringify(query);
    if (state.pages.has(key)) return;
    state.pages.set(key, null);
    const reply = await request({ type: "list", ...query });
    if (reply.stale || kernelPages !== state) return; // the listing has changed since
    const entries = decodeColumns(reply.listing);
    for (const e of entries) state.seen.set(e.path, e);
    state.pages.set(key, { ...reply, entries });
    if (key === JSON.stringify(kernelQuery())) render();
  }

  // The page to show of a large folder: {entries, matching, page, loading}.
  // Asks the kernel when needed, once typing in the filter pauses.
  function kernelPage() {
    const state = kernelState();
    const query = kernelQuery();
    const reply = state.pages.get(JSON.stringify(query));
    clearTimeout(filterTimer);
    if (reply) {
      state.shown = reply;
      if (reply.filter_error) filter.invalid(reply.filter_error);
      if ((reply.page + 1) * PAGE_SIZE < reply.matching) fetchPage(kernelQuery(reply.page + 1));
      return { entries: reply.entries, matching: reply.matching, page: reply.page, loading: false };
    }
    if (filterTyped) filterTimer = setTimeout(() => fetchPage(kernelQuery()), 200);
    else fetchPage(query);
    const shown = state.shown;
    return {
      entries: shown ? shown.entries.filter((e) => filter.test(e.name)) : [],
      matching: shown?.matching ?? 0,
      page,
      loading: true,
    };
  }

  // --- Selection ---

  function select(path, additive) {
    const current = model.get("_selected");
    const next = !additive ? [path] : current.includes(path) ? current.filter((p) => p !== path) : [...current, path];
    model.set("_selected", next);
    model.save_changes();
    // While the preview panel is open, it follows a single selected file.
    // Folders are not previewed on click (use Preview for e.g. a Delta table).
    if (x.preview.isOpen() && next.length === 1 && next[0] !== model.get("_preview").path) {
      const [entry] = entriesAt(next);
      if (entry && !isFolder(entry) && hasUrl(entry)) x.preview.open(next[0]);
    }
  }

  // --- Tooltips, as JupyterLab's file browser's: name, size, times, format
  // and URL. The listing does not carry URLs, so those of the rows shown are
  // asked for in one request as they are drawn, before any hover (a title
  // set while the pointer rests on a row would not show), and kept by
  // storage and path: a URL, or the request's promise while it is out. Items
  // without one show their path ---

  const tooltipUrls = new Map();

  function tooltip(entry, location) {
    const lines = [`Name: ${visible(entry.name)}`];
    if (entry.size != null) lines.push(`Size: ${formatSize(entry.size)}`);
    if (entry.mtime != null) lines.push(`Modified: ${formatTime(entry.mtime)}`);
    if (entry.ctime != null) lines.push(`Created: ${formatTime(entry.ctime)}`);
    if (entry.format) lines.push(`Format: ${x.formatLabel(entry.format)}`);
    if (location != null) lines.push(hasUrl(entry) ? `URL: ${location}` : `Path: ${location}`);
    return lines.join("\n");
  }

  // An item's URL if the list has it already (asked for as its row was drawn), else null.
  function urlOf(entry) {
    const known = hasUrl(entry) ? tooltipUrls.get(`${model.get("_filesystem")}\n${entry.path}`) : null;
    return typeof known === "string" ? known : null;
  }

  function setTooltips(rows) {
    const filesystem = model.get("_filesystem");
    const key = (entry) => `${filesystem}\n${entry.path}`;
    const missing = rows.map(([, entry]) => entry).filter((e) => hasUrl(e) && !tooltipUrls.has(key(e)));
    if (missing.length) {
      const asked = x.urlsOf(missing).then(
        (urls) => missing.forEach((e, i) => tooltipUrls.set(key(e), urls[i] ?? e.path)),
        () => missing.forEach((e) => tooltipUrls.delete(key(e))), // asked again when drawn again
      );
      missing.forEach((e) => tooltipUrls.set(key(e), asked));
    }
    for (const [tr, entry] of rows) {
      const known = hasUrl(entry) ? tooltipUrls.get(key(entry)) : entry.path;
      if (typeof known === "string") {
        tr.title = tooltip(entry, known);
      } else {
        tr.title = tooltip(entry, null);
        known.then(() => (tr.title = tooltip(entry, tooltipUrls.get(key(entry)))));
      }
    }
  }

  // --- Drawing ---

  // The folder whose items the list last showed, to tell when another's arrive.
  let showsDir = null;

  function row(entry, selected) {
    const isDir = isFolder(entry);
    const formatIcon = model.get("_format_icons")[entry.format];
    const tr = h(
      "tr",
      { className: selected.has(entry.path) ? "jse-selected" : "" },
      h(
        "td",
        { className: "jse-col-name" },
        h("span", { className: "jse-icon" }, fileIcon(entry.name, isDir, formatIcon, model.get("_file_icon_svgs")[formatIcon])),
        visible(entry.name),
      ),
      h("td", { className: "jse-col-size", textContent: formatSize(entry.size) }),
      h("td", { className: "jse-col-mtime", textContent: formatTime(entry.mtime) }),
    );
    if (isDir) {
      tr.dataset.dropDir = entry.path; // files dropped here are uploaded or moved into this folder
      // Depth from the root, as in the tree: ancestors() lists the root down to
      // this folder, so a top-level folder gives 2 entries, i.e. depth 1.
      if (entry.path.startsWith(model.get("_root"))) tr.dataset.depth = x.ancestors(entry.path).length - 1;
    } else if (entry.format) {
      // e.g. "csv", "json-lines"; lets CSS style the icon per format.
      tr.dataset.fileFormat = entry.format;
    }
    // Files (and, in unsafe mode, folders) can be dragged onto a folder to move
    // them there; files onto JupyterLab's file browser to download them to
    // the Jupyter server (see startDrag).
    tr.draggable = true;
    tr.addEventListener("dragstart", (ev) => x.transfers.startDrag(ev, entry));
    tr.addEventListener("click", (ev) => select(entry.path, ev.ctrlKey || ev.metaKey));
    // As in JupyterLab's file browser: a folder opens, a file opens in
    // JupyterLab's editor or viewer when it can show it, else in the preview.
    tr.addEventListener("dblclick", () => {
      if (isDir) x.navigate(entry.path);
      else if (x.jupyterlab.canOpen(entry)) x.jupyterlab.open(entry.path);
      else if (hasUrl(entry)) x.preview.open(entry.path); // no URL: no preview
    });
    tr.addEventListener("contextmenu", (ev) => {
      // Like file managers: right-clicking outside the selection selects that item.
      let paths = model.get("_selected");
      if (!paths.includes(entry.path)) {
        select(entry.path, false);
        paths = [entry.path];
      }
      x.menu.show(ev, x.itemMenu(entriesAt(paths)));
    });
    return tr;
  }

  function render() {
    // Another folder's items are shown unfiltered, from the first page. Done
    // when they arrive, not on clicking the folder: the previous folder's
    // items would show unfiltered until then, a long wait for a large folder.
    const dir = model.get("_listing").dir;
    if (dir !== showsDir) {
      showsDir = dir;
      page = 0;
      filter.clear(false);
    }
    headRow.replaceChildren(
      ...LIST_COLUMNS.map((col) => {
        const th = h("th", { className: `jse-col-${col.key}`, textContent: col.label });
        if (sort.key === col.key) th.append(icon(sort.asc ? "caret-up" : "caret-down"));
        th.addEventListener("click", () => {
          sort.asc = sort.key === col.key ? !sort.asc : true;
          sort.key = col.key;
          page = 0;
          render();
        });
        return th;
      }),
    );

    // Filtered by name, then cut into pages. The selection keeps items filtered
    // out or on other pages, and right-click actions apply to them too.
    let shown, matching, total, loading;
    if (kernelMode()) {
      const reply = kernelPage();
      ({ entries: shown, matching, loading } = reply);
      page = reply.page;
      total = model.get("_listing").total;
    } else {
      const entries = sortedEntries();
      const filtered = filter.active() ? entries.filter((e) => filter.test(e.name)) : entries;
      matching = filtered.length;
      total = entries.length;
      page = Math.min(page, Math.max(1, Math.ceil(matching / PAGE_SIZE)) - 1);
      shown = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
      loading = false;
    }
    filterTyped = false;
    const pages = Math.max(1, Math.ceil(matching / PAGE_SIZE));
    const first = page * PAGE_SIZE;
    pagerEl.hidden = pages < 2;
    pageLabel.textContent = `${(first + 1).toLocaleString()}–${(first + shown.length).toLocaleString()} of ${matching.toLocaleString()}`;
    pageLabel.title = kernelMode() ? "A large folder: filtered, sorted and paged by the kernel" : "";
    prevPageBtn.disabled = page === 0;
    nextPageBtn.disabled = page >= pages - 1;
    const selected = new Set(model.get("_selected"));
    const rows = shown.map((entry) => [row(entry, selected), entry]);
    tbody.replaceChildren(...rows.map(([tr]) => tr));
    setTooltips(rows);
    if (!shown.length && total) {
      const text = loading ? "Loading…" : "No items match the filter";
      tbody.append(h("tr", {}, h("td", { className: "jse-placeholder", colSpan: LIST_COLUMNS.length, textContent: text })));
    }
    x.preview.updateButton();
    renderStatus();
  }

  function showPage(delta) {
    page += delta;
    render();
    el.scrollTop = 0;
  }

  prevPageBtn.addEventListener("click", () => showPage(-1));
  nextPageBtn.addEventListener("click", () => showPage(1));

  // Right-clicking empty space in the list: paste into, or create a folder in, the folder shown.
  el.addEventListener("contextmenu", (ev) => {
    if (ev.target instanceof Element && ev.target.closest("tbody tr")) return; // a row's own menu
    const dest = model.get("_current_dir");
    x.menu.show(ev, [
      // Folders on the clipboard while locked: a greyed-out "Paste".
      x.clipboard.pasteItem(dest) ?? { label: "Paste", icon: "paste", disabled: true },
      { label: "Create a folder", icon: "new-folder", action: () => x.operations.createFolder(dest) },
    ]);
  });

  // --- The status bar: the items, those matching the filter and those
  // selected; or an error, or a short message (flash) ---

  let flashTimer = null;

  function flash(message) {
    statusEl.textContent = visible(message);
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      flashTimer = null;
      renderStatus();
    }, 1500);
  }

  function renderStatus() {
    if (flashTimer) return; // a message is showing; it calls back when done
    const error = model.get("_error");
    statusEl.classList.toggle("jse-error", Boolean(error));
    if (error) {
      statusEl.textContent = visible(error);
      return;
    }
    let total, matches;
    if (kernelMode()) {
      // Of the last page received: while a new filter's is awaited, the previous filter's.
      total = model.get("_listing").total;
      matches = () => kernelState().shown?.matching ?? total;
    } else {
      const entries = listedEntries();
      total = entries.length;
      matches = () => entries.filter((e) => filter.test(e.name)).length;
    }
    const count = `${total.toLocaleString()} item${total === 1 ? "" : "s"}`;
    const selected = model.get("_selected");
    const matching = filter.active() ? `${matches().toLocaleString()} of ${count} match` : count;
    statusEl.textContent = matching + (selected.length ? `, ${selectionSummary(selected)} selected` : "");
  }

  // "4 files (123 KB) 1 folder": the selected files and their total size,
  // from the listing, and the selected folders, whose contents are not
  // counted (Properties does).
  function selectionSummary(paths) {
    const entries = entriesAt(paths);
    if (!entries.length) return paths.length.toLocaleString(); // not in the pages received
    const files = entries.filter((e) => !isFolder(e));
    const folders = entries.length - files.length;
    const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
    const parts = [];
    if (files.length) parts.push(`${plural(files.length, "file")} (${formatSize(files.reduce((sum, e) => sum + (e.size ?? 0), 0))})`);
    if (folders) parts.push(plural(folders, "folder"));
    return parts.join(" ");
  }

  return {
    pane,
    el,
    statusEl,
    render,
    renderStatus,
    flash,
    entriesAt,
    urlOf,
    dispose: () => clearTimeout(flashTimer),
  };
}
