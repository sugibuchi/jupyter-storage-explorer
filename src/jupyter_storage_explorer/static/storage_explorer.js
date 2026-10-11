// Storage Explorer: directory tree (left) and file list (right), with a
// preview panel below them. Joined after common.js and query.js (see _static.py).

const join = (parent, name) => (!parent || parent.endsWith("/") ? parent + name : `${parent}/${name}`);
// Some filesystems (e.g. DirFileSystem) use "" as their top-level path.
const rootLabel = (root) => root || "/";

function formatSize(bytes) {
  if (bytes == null) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024;
    i++;
  }
  return `${i === 0 ? bytes : bytes.toFixed(1)} ${units[i]}`;
}

const formatTime = (ts) => (ts == null ? "" : new Date(ts * 1000).toLocaleString());

// --- Preview sections (one renderer per Preview kind in formats/base.py) ---

function renderTable(section) {
  const head = h("tr", {}, ...section.columns.map((c) => h("th", { textContent: c })));
  const thead = h("thead", {}, head);
  if (section.dtypes) {
    thead.append(h("tr", { className: "jse-dtypes" }, ...section.dtypes.map((t) => h("th", { textContent: t }))));
  }
  const body = section.rows.map((row) =>
    h(
      "tr",
      {},
      ...row.map((v) => h("td", { textContent: v == null ? "null" : cellText(v), className: v == null ? "jse-null" : "" })),
    ),
  );
  return h("div", { className: "jse-table-wrap" }, h("table", { className: "jse-data" }, thead, h("tbody", {}, ...body)));
}

function renderJson(value, key, depth) {
  const label = key == null ? "" : `${key}: `;
  if (value === null || typeof value !== "object") {
    return h("div", { className: "jse-json-leaf", textContent: label + JSON.stringify(value) });
  }
  const isArray = Array.isArray(value);
  const entries = isArray ? value.map((v, i) => [i, v]) : Object.entries(value);
  const summary = `${label}${isArray ? `[${entries.length}]` : `{${entries.length}}`}`;
  return h(
    "details",
    { open: depth < 2 },
    h("summary", { textContent: summary }),
    ...entries.map(([k, v]) => renderJson(v, k, depth + 1)),
  );
}

function renderMedia(section) {
  const src = section.src ?? `data:${section.mime};base64,${section.data}`;
  if (section.mime.startsWith("image/")) return h("img", { className: "jse-media", src });
  return h("div", { textContent: `Cannot show ${section.mime}` });
}

// Missing packages: the install commands to copy, one block per option.
function renderInstall(section) {
  const several = section.options.length > 1;
  const intro = several
    ? `To preview this ${section.format}, install one of these options in a notebook cell, then preview it again.`
    : `To preview this ${section.format}, install the packages below in a notebook cell, then preview it again.`;
  return h(
    "div",
    { className: "jse-install" },
    h("div", { textContent: intro }),
    h("div", { className: "jse-note", textContent: "No kernel restart is needed." }),
    ...section.options.map((option, i) =>
      codeBlock(several ? `Option ${i + 1}: ${option.packages}` : option.packages, option.command),
    ),
  );
}

// --- Markdown: rendered with marked, sanitized with DOMPurify ---
// Both are vendored in static/vendor. An anywidget module cannot import files
// next to it, so the kernel sends their source, imported once per page.

// Set by each widget's render(): asks its kernel for a vendored library's source.
let fetchVendor = null;
let markdownLibs = null; // Promise of {marked, DOMPurify}

async function importSource(source) {
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  try {
    return await import(url);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadMarkdownLibs() {
  markdownLibs ??= (async () => {
    const [markedSource, purifySource] = await Promise.all([fetchVendor("marked.esm.js"), fetchVendor("purify.es.mjs")]);
    const [markedModule, purifyModule] = await Promise.all([importSource(markedSource), importSource(purifySource)]);
    return { marked: markedModule.marked, DOMPurify: purifyModule.default };
  })().catch((err) => {
    markdownLibs = null; // try again next time
    throw err;
  });
  return markdownLibs;
}

function renderMarkdown(section) {
  // jp-RenderedHTMLCommon gives it JupyterLab's own Markdown styling.
  const box = h("div", { className: "jp-RenderedHTMLCommon jse-markdown", textContent: "Rendering…" });
  loadMarkdownLibs()
    .then(({ marked, DOMPurify }) => {
      // Sanitizing removes scripts, event handlers etc. the file may contain.
      box.innerHTML = DOMPurify.sanitize(marked.parse(section.text, { async: false }));
      for (const link of box.querySelectorAll("a[href]")) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    })
    .catch((err) => {
      box.replaceChildren(
        h("div", { className: "jse-note", textContent: `Cannot render Markdown (${err.message}); showing the text.` }),
        h("pre", { className: "jse-text", textContent: section.text }),
      );
    });
  return box;
}

const sectionRenderers = {
  markdown: renderMarkdown,
  table: renderTable,
  // Highlighted HTML comes from Pygments in the kernel, which escapes the text.
  text: (s) =>
    s.html ? h("pre", { className: "jse-text jse-highlight", innerHTML: s.html }) : h("pre", { className: "jse-text", textContent: s.text }),
  tree: (s) => h("div", { className: "jse-json" }, renderJson(s.value, null, 0)),
  media: renderMedia,
  install: renderInstall,
};

function renderSection(section) {
  // The kind class lets the preview panel stretch tables, text etc. to its height.
  const box = h("div", { className: `jse-section jse-section-${section.kind}` });
  if (section.title) box.append(h("div", { className: "jse-section-title", textContent: section.title }));
  const renderer = sectionRenderers[section.kind];
  box.append(renderer ? renderer(section) : h("div", { textContent: `Unknown preview: ${section.kind}` }));
  if (section.note) box.append(h("div", { className: "jse-note", textContent: section.note }));
  return box;
}

// A titled code block with a Copy button and an optional hint.
function codeBlock(title, code, hint) {
  const copyBtn = h("button", { className: "jse-btn", textContent: "Copy" });
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code);
      copyBtn.textContent = "Copied";
    } catch {
      copyBtn.textContent = "Copy failed";
    }
    setTimeout(() => (copyBtn.textContent = "Copy"), 1500);
  });
  return h(
    "div",
    { className: "jse-recipe" },
    h("div", { className: "jse-recipe-head" }, h("span", { textContent: title }), copyBtn),
    ...(hint ? [h("div", { className: "jse-note", textContent: hint })] : []),
    h("pre", { className: "jse-code", textContent: code }),
  );
}

// Body of the "Python code" dialog for one recipe ({library, install, code}):
// `install` is what to run once first (installing packages, setting up e.g.
// a Spark session), empty when nothing is needed.
function recipeBlocks(recipe) {
  if (!recipe.install) return [codeBlock("Load", recipe.code)];
  return [
    codeBlock("1. Set up", recipe.install, "Not done in this kernel yet: run this once in a cell first."),
    codeBlock("2. Load", recipe.code),
  ];
}

function render({ model, el }) {
  // Expanded tree folders, kept per filesystem so switching back restores them.
  const expandedByFs = new Map();
  let expanded = new Set();
  // Set when switching to a filesystem not shown before: its root is expanded
  // on the next render, like the first one's. Not left to onDirChange, as
  // filesystems can share their root path (e.g. "" for DirFileSystems), and
  // then neither _root nor _current_dir changes.
  let expandRoot = false;
  const pending = new Set(); // directories requested from the kernel but not yet in the tree
  const sort = { key: "name", asc: true };

  const upBtn = h("button", { className: "jse-btn", title: "Parent directory", textContent: "↑" });
  const refreshBtn = h("button", { className: "jse-btn", title: "Refresh", textContent: "⟳" });
  const previewBtn = h("button", { className: "jse-btn", textContent: "Preview" });
  // Filesystem chooser; hidden when there is only one.
  const fsSelect = h("select", { className: "jse-fs-select", title: "Filesystem" });
  const pathEl = h("div", { className: "jse-path" });
  const treeEl = h("div", { className: "jse-tree" });
  const headRow = h("tr");
  const tbody = h("tbody");
  const listEl = h("div", { className: "jse-list" }, h("table", {}, h("thead", {}, headRow), tbody));
  const statusEl = h("div", { className: "jse-status" });
  // Tree and list; its height is the `height` trait until resized by dragging.
  const panesEl = h("div", { className: "jse-panes" }, treeEl, listEl);
  // Bottom edge of the widget: resizes the last area (preview panel or tree and list).
  const grip = h("div", { className: "jse-grip", title: "Drag to resize" });
  // Preview panel below the tree and list; the splitter on its top edge moves
  // the boundary between them.
  const previewCloseBtn = h("button", { className: "jse-btn", title: "Close preview (Esc)", textContent: "✕" });
  const previewHead = h("div", { className: "jse-dialog-head" });
  const previewBody = h("div", { className: "jse-dialog-body" });
  const splitter = h("div", { className: "jse-splitter", title: "Drag to resize" });
  // tabIndex makes the panel focusable, so it receives Escape.
  const previewEl = h(
    "div",
    { className: "jse-preview-panel", tabIndex: -1, hidden: true },
    splitter,
    previewHead,
    previewBody,
  );
  // Modal window for "Python code", centred over a backdrop that dims the widget.
  const closeBtn = h("button", { className: "jse-btn", title: "Close (Esc)", textContent: "✕" });
  const dialogHead = h("div", { className: "jse-dialog-head" });
  const dialogBody = h("div", { className: "jse-dialog-body" });
  const dialogEl = h(
    "div",
    { className: "jse-dialog", tabIndex: -1, hidden: true },
    h("div", { className: "jse-modal" }, dialogHead, dialogBody),
  );
  const menuEl = h("div", { className: "jse-menu", hidden: true });
  // Modal text editor. Only Cancel/Save (or Esc/Ctrl+S) close it, so a stray
  // click outside cannot discard changes.
  const editorTitle = h("span", { className: "jse-preview-name" });
  const editorText = h("textarea", { className: "jse-editor-text", spellcheck: false });
  const editorMsg = h("span", { className: "jse-editor-msg" });
  const cancelBtn = h("button", { className: "jse-btn", textContent: "Cancel", title: "Close without saving (Esc)" });
  const saveBtn = h("button", { className: "jse-btn jse-primary", textContent: "Save", title: "Save changes (Ctrl+S)" });
  const editorEl = h(
    "div",
    { className: "jse-dialog", hidden: true },
    h(
      "div",
      { className: "jse-modal jse-editor" },
      h("div", { className: "jse-dialog-head" }, editorTitle),
      editorText,
      h("div", { className: "jse-editor-foot" }, editorMsg, h("span", { className: "jse-spacer" }), cancelBtn, saveBtn),
    ),
  );

  // Small confirmation dialog, e.g. "Upload sales.csv? [Cancel] [Upload]".
  const { el: confirmEl, ask, answer } = createConfirm();

  // "jse-browser" is for user styles too, e.g. icons by [data-depth] (DEVELOPMENT.md).
  el.classList.add("jse-widget", "jse-browser");
  // Focusable, so Escape reaches the widget after a click anywhere in it.
  el.tabIndex = -1;
  // Keep JupyterLab's notebook shortcuts (e.g. "dd" deletes a cell) from
  // firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  el.replaceChildren(
    h("div", { className: "jse-toolbar" }, fsSelect, upBtn, refreshBtn, pathEl, previewBtn),
    panesEl,
    previewEl,
    statusEl,
    grip,
    dialogEl,
    editorEl,
    confirmEl,
    menuEl,
  );

  // --- Right-click menu ---

  let flashTimer;
  // A short message in the status bar, shown even while it is otherwise hidden.
  function flash(message) {
    statusEl.textContent = message;
    statusEl.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      flashTimer = null;
      renderStatus();
    }, 1500);
  }

  async function copy(lines, what) {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      flash(`Copied ${what}`);
    } catch {
      flash("Copy failed: the browser denied clipboard access");
    }
  }

  function onOutsidePointer(ev) {
    if (!menuEl.contains(ev.target)) hideMenu();
  }

  function onMenuKey(ev) {
    if (ev.key === "Escape") {
      ev.stopPropagation();
      hideMenu();
    }
  }

  function hideMenu() {
    menuEl.hidden = true;
    document.removeEventListener("pointerdown", onOutsidePointer, true);
    document.removeEventListener("keydown", onMenuKey, true);
  }

  // items: {label, action, disabled}, {label, submenu, disabled} or "-" for a
  // separator. `submenu(el)` fills the submenu element, possibly later.
  // `hidden` rows can be shown later through the element passed to `ref(row)`.
  function menuRows(items) {
    return items.map((item) => {
      if (item === "-") return h("div", { className: "jse-menu-sep" });
      const row = h(
        "div",
        { className: "jse-menu-item" + (item.disabled ? " jse-disabled" : ""), hidden: Boolean(item.hidden) },
        h("span", { textContent: item.label }),
      );
      item.ref?.(row);
      if (item.disabled) return row;
      if (item.submenu) {
        const sub = h("div", { className: "jse-menu jse-submenu" });
        row.classList.add("jse-has-sub");
        row.append(h("span", { className: "jse-sub-arrow", textContent: "▸" }), sub);
        item.submenu(sub);
      } else {
        row.addEventListener("click", () => {
          hideMenu();
          item.action();
        });
      }
      return row;
    });
  }

  function showMenu(ev, items) {
    ev.preventDefault();
    ev.stopPropagation(); // keep JupyterLab's own context menu from opening
    menuEl.replaceChildren(...menuRows(items));
    menuEl.hidden = false;
    // Place at the pointer, kept inside the widget.
    const box = el.getBoundingClientRect();
    const x = Math.min(ev.clientX - box.left, box.width - menuEl.offsetWidth - 4);
    const y = Math.min(ev.clientY - box.top, box.height - menuEl.offsetHeight - 4);
    menuEl.style.left = `${Math.max(0, x)}px`;
    menuEl.style.top = `${Math.max(0, y)}px`;
    // Open submenus to the left when there is no room on the right.
    menuEl.classList.toggle("jse-flip", Math.max(0, x) + 2 * menuEl.offsetWidth > box.width);
    document.addEventListener("pointerdown", onOutsidePointer, true);
    document.addEventListener("keydown", onMenuKey, true);
  }

  // --- Menu items filled in by the kernel: "Preview as", "Edit" and "Python code" ---

  // For the open menu: {path, previewAsRow, previewAsSub, editRow, codeSub},
  // the elements to fill when the kernel's "menu_info" reply arrives.
  let menuInfo = null;

  function requestMenuInfo(path) {
    menuInfo = { path };
    model.send({ type: "menu_info", path });
    return menuInfo;
  }

  function onCustomMsg(msg, buffers) {
    if (msg.type === "menu_info") onMenuInfo(msg);
    else if (msg.type === "edit_open") onEditOpen(msg);
    else if (msg.type === "edit_save") onEditSave(msg);
    else if (msg.type === "download") onDownload(msg, buffers);
    else if (msg.type === "upload") onUpload(msg);
    else if (msg.type === "reply") onReply(msg);
  }

  // "a.csv", "a.csv and b.csv", or "3 files: a.csv, b.csv, c.csv" (long lists shortened).
  function describeFiles(names) {
    if (names.length === 1) return names[0];
    if (names.length === 2) return `${names[0]} and ${names[1]}`;
    const shown = names.slice(0, 8).join(", ");
    return `${names.length} files: ${shown}${names.length > 8 ? `, and ${names.length - 8} more` : ""}`;
  }

  // --- Upload: drag files from JupyterLab's file browser onto the list or tree ---

  // JupyterLab's file browser uses Lumino drag events ("lm-drag*"), not the
  // browser's native ones. Its data is a list of paths relative to the folder
  // the Jupyter server runs in.
  const CONTENTS_MIME = "application/x-jupyter-icontents";
  let dropHighlight = null;
  let uploadRequest = null; // {root, paths, dest} awaiting the kernel's reply

  // Where JupyterLab's paths are relative to (the server's folder on disk),
  // from the configuration JupyterLab puts in every page.
  function serverRoot() {
    try {
      return JSON.parse(document.getElementById("jupyter-config-data").textContent).serverRoot ?? null;
    } catch {
      return null;
    }
  }

  // A folder row (list or tree) under the pointer, else the folder shown.
  function dropTarget(ev) {
    const node = ev.target instanceof Element ? ev.target.closest("[data-drop-dir]") : null;
    if (node && panesEl.contains(node)) return { el: node, dir: node.dataset.dropDir };
    return { el: listEl, dir: model.get("_current_dir") };
  }

  function highlightDrop(target) {
    if (dropHighlight === target) return;
    dropHighlight?.classList.remove("jse-drop-target");
    dropHighlight = target;
    dropHighlight?.classList.add("jse-drop-target");
  }

  function acceptsDrag(ev) {
    return Boolean(ev.mimeData?.hasData?.(CONTENTS_MIME));
  }

  panesEl.addEventListener("lm-dragenter", (ev) => {
    if (!acceptsDrag(ev)) return;
    ev.preventDefault(); // makes the widget a drop target
    ev.stopPropagation();
  });
  panesEl.addEventListener("lm-dragover", (ev) => {
    if (!acceptsDrag(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
    // JupyterLab only offers "move"; accepting it is safe, as the dragging side
    // never deletes anything itself. The kernel copies; the original stays.
    ev.dropAction = ev.proposedAction;
    highlightDrop(dropTarget(ev).el);
  });
  panesEl.addEventListener("lm-dragleave", (ev) => {
    if (!acceptsDrag(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (!(ev.relatedTarget instanceof Node && panesEl.contains(ev.relatedTarget))) highlightDrop(null);
  });
  panesEl.addEventListener("lm-drop", (ev) => {
    if (!acceptsDrag(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
    highlightDrop(null);
    if (ev.proposedAction === "none") {
      ev.dropAction = "none";
      return;
    }
    ev.dropAction = ev.proposedAction;
    confirmUpload(ev.mimeData.getData(CONTENTS_MIME), dropTarget(ev).dir);
  });

  // The two upload dialogs, shared by drops from JupyterLab and from the computer.

  function askUpload(names, dest) {
    return ask(
      [h("div", { textContent: `Upload ${describeFiles(names)}?` }), h("div", { className: "jse-note", textContent: `To ${dest}` })],
      [
        { label: "Cancel", value: null },
        { label: "Upload", value: true, primary: true },
      ],
    );
  }

  // Resolves with "overwrite", "skip", or null (cancel).
  function askConflicts(conflicts, dest) {
    return ask(
      [
        h("div", { textContent: `${describeFiles(conflicts)} already ${conflicts.length === 1 ? "exists" : "exist"}.` }),
        h("div", { className: "jse-note", textContent: `In ${dest}` }),
      ],
      [
        { label: "Cancel", value: null },
        { label: "Skip existing", value: "skip" },
        { label: "Overwrite", value: "overwrite", primary: true },
      ],
    );
  }

  function uploadSummary(copied, skipped, errors) {
    const parts = [];
    if (copied.length) parts.push(`Uploaded ${copied.length === 1 ? copied[0] : `${copied.length} files`}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    flash(parts.join("; ") || "Nothing uploaded");
  }

  // From JupyterLab's file browser: the kernel copies the files itself.
  async function confirmUpload(paths, dest) {
    const root = serverRoot();
    if (root == null) {
      flash("Cannot upload: JupyterLab did not say where its files are");
      return;
    }
    const names = paths.map((p) => p.slice(p.lastIndexOf("/") + 1));
    if (!(await askUpload(names, dest))) return;
    uploadRequest = { root, paths, dest };
    flash("Uploading…");
    model.send({ type: "upload", ...uploadRequest, if_exists: "ask" });
  }

  async function onUpload(msg) {
    if (uploadRequest?.dest !== msg.dest) return;
    if (msg.conflicts) {
      const choice = await askConflicts(msg.conflicts, msg.dest);
      if (!choice) {
        uploadRequest = null;
        flash("Upload cancelled");
        return;
      }
      model.send({ type: "upload", ...uploadRequest, if_exists: choice });
      return;
    }
    uploadRequest = null;
    uploadSummary(msg.copied ?? [], msg.skipped ?? [], msg.errors ?? []);
  }

  // --- Upload from the computer (native drag and drop): the browser sends
  // each file in pieces, each acknowledged by the kernel before the next ---

  // Under the server's 10 MB limit for one message from the browser.
  const CHUNK_BYTES = 1024 * 1024;

  // Requests answered by a {"type": "reply", "rid"} message.
  const { request, onReply } = createRequester(model);

  // Lets Markdown previews load the vendored libraries through this widget's kernel.
  fetchVendor = async (name) => {
    const reply = await request({ type: "vendor", name });
    if (reply.error) throw new Error(reply.error);
    return reply.source;
  };

  // Files in a native drop; folders are listed separately, as they are not uploaded.
  function droppedFiles(dataTransfer) {
    const files = [];
    const folders = [];
    for (const item of dataTransfer.items) {
      if (item.kind !== "file") continue;
      const entry = item.webkitGetAsEntry?.();
      if (entry?.isDirectory) folders.push(entry.name);
      else if (item.getAsFile()) files.push(item.getAsFile());
    }
    return { files, folders };
  }

  let localUploadBusy = false;

  async function uploadLocalFiles({ files: dropped, folders }, dest) {
    const errors = folders.map((name) => `${name}: folders are not uploaded`);
    // Files over the widget's max_upload_bytes are refused before sending anything.
    const limit = model.get("_max_upload_bytes");
    const files = [];
    for (const file of dropped) {
      if (limit != null && file.size > limit) errors.push(`${file.name}: too large to upload (over ${formatSize(limit)})`);
      else files.push(file);
    }
    if (!files.length) {
      uploadSummary([], [], errors);
      return;
    }
    if (localUploadBusy) {
      flash("Another upload is still running");
      return;
    }
    if (!(await askUpload(files.map((f) => f.name), dest))) return;
    localUploadBusy = true;
    const copied = [];
    const skipped = [];
    try {
      const { conflicts = [] } = await request({ type: "upload_check", dest, names: files.map((f) => f.name) });
      let toSend = files;
      if (conflicts.length) {
        const choice = await askConflicts(conflicts, dest);
        if (!choice) {
          flash("Upload cancelled");
          return;
        }
        if (choice === "skip") {
          toSend = files.filter((f) => !conflicts.includes(f.name));
          skipped.push(...conflicts);
        }
      }
      for (const [i, file] of toSend.entries()) {
        const id = `${Date.now()}-${i}`;
        let offset = 0;
        do {
          const piece = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
          offset += piece.byteLength;
          const last = offset >= file.size;
          const reply = await request({ type: "upload_chunk", id, dest, name: file.name, last }, [piece]);
          if (reply.error) {
            errors.push(reply.error);
            break;
          }
          if (last) copied.push(file.name);
          else flash(`Uploading ${file.name}: ${Math.floor((100 * offset) / file.size)}%`);
        } while (offset < file.size);
      }
      if (copied.length) await request({ type: "upload_done", dest });
    } finally {
      localUploadBusy = false;
    }
    uploadSummary(copied, skipped, errors);
  }

  const hasFiles = (ev) => Array.from(ev.dataTransfer?.types ?? []).includes("Files");

  panesEl.addEventListener("dragenter", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
  });
  panesEl.addEventListener("dragover", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault(); // allows the drop
    ev.stopPropagation();
    ev.dataTransfer.dropEffect = "copy";
    highlightDrop(dropTarget(ev).el);
  });
  panesEl.addEventListener("dragleave", (ev) => {
    if (!hasFiles(ev)) return;
    if (!(ev.relatedTarget instanceof Node && panesEl.contains(ev.relatedTarget))) highlightDrop(null);
  });
  panesEl.addEventListener("drop", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault(); // otherwise the browser opens the file
    ev.stopPropagation(); // keep the notebook from handling it too
    highlightDrop(null);
    // The DataTransfer is only readable during this event, so collect the files now.
    uploadLocalFiles(droppedFiles(ev.dataTransfer), dropTarget(ev).dir);
  });

  // --- Move: drag files in the list onto a folder (list or tree) ---

  // Our own drag data type, so moves are told apart from uploads.
  const MOVE_MIME = "application/x-jse-move";
  const isMoveDrag = (ev) => Array.from(ev.dataTransfer?.types ?? []).includes(MOVE_MIME);

  // Files a drag starting on `entry` moves: the selected files if it is
  // selected, else just it. Folders are not moved.
  function draggedFiles(entry) {
    const selected = model.get("_selected");
    if (!selected.includes(entry.path)) return [entry.path];
    return model
      .get("entries")
      .filter((e) => selected.includes(e.path) && e.type !== "directory")
      .map((e) => e.path);
  }

  // Only a folder (row or tree node) is a target; the list itself is the folder they are in.
  function moveTarget(ev) {
    const node = ev.target instanceof Element ? ev.target.closest("[data-drop-dir]") : null;
    return node && panesEl.contains(node) ? node : null;
  }

  panesEl.addEventListener("dragover", (ev) => {
    if (!isMoveDrag(ev)) return;
    ev.stopPropagation();
    const node = moveTarget(ev);
    highlightDrop(node);
    if (!node) return; // not preventing the default refuses the drop here
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
  });
  panesEl.addEventListener("dragleave", (ev) => {
    if (!isMoveDrag(ev)) return;
    if (!(ev.relatedTarget instanceof Node && panesEl.contains(ev.relatedTarget))) highlightDrop(null);
  });
  panesEl.addEventListener("drop", (ev) => {
    if (!isMoveDrag(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
    highlightDrop(null);
    const node = moveTarget(ev);
    if (node) confirmMove(JSON.parse(ev.dataTransfer.getData(MOVE_MIME)), node.dataset.dropDir);
  });
  panesEl.addEventListener("dragend", () => highlightDrop(null));

  async function confirmMove(paths, dest) {
    const parentOf = (p) => p.slice(0, p.lastIndexOf("/"));
    const toMove = paths.filter((p) => p !== dest && parentOf(p) !== dest.replace(/\/$/, ""));
    if (!toMove.length) {
      flash("Already in that folder");
      return;
    }
    const names = toMove.map((p) => p.slice(p.lastIndexOf("/") + 1));
    const ok = await ask(
      [h("div", { textContent: `Move ${describeFiles(names)}?` }), h("div", { className: "jse-note", textContent: `To ${dest}` })],
      [
        { label: "Cancel", value: null },
        { label: "Move", value: true, primary: true },
      ],
    );
    if (!ok) return;
    let reply = await request({ type: "move", paths: toMove, dest, if_exists: "ask" });
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        flash("Move cancelled");
        return;
      }
      reply = await request({ type: "move", paths: toMove, dest, if_exists: choice });
    }
    const { moved = [], skipped = [], errors = [] } = reply;
    const parts = [];
    if (moved.length) parts.push(`Moved ${moved.length === 1 ? moved[0] : `${moved.length} files`}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    flash(parts.join("; ") || "Nothing moved");
  }

  // --- Download: the kernel sends each file's bytes; the browser saves them ---

  // Files requested but not received yet, and the errors so far.
  const downloads = { pending: 0, done: 0, errors: [] };

  function download(paths) {
    downloads.pending += paths.length;
    flash(`Downloading ${paths.length === 1 ? "1 file" : `${paths.length} files`}…`);
    model.send({ type: "download", paths });
  }

  function onDownload(msg, buffers) {
    downloads.pending -= 1;
    if (msg.error) {
      downloads.errors.push(msg.error);
    } else {
      const url = URL.createObjectURL(new Blob([buffers[0]]));
      const link = h("a", { href: url, download: msg.name });
      document.body.append(link);
      link.click();
      link.remove();
      // Revoking right away can cancel the download in some browsers.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      downloads.done += 1;
    }
    if (downloads.pending > 0) return;
    const { done, errors } = downloads;
    const summary = done ? `Downloaded ${done === 1 ? "1 file" : `${done} files`}` : "";
    flash([summary, ...errors.map((e) => `Failed: ${e}`)].filter(Boolean).join("; "));
    Object.assign(downloads, { done: 0, errors: [] });
  }

  // The kernel identifies formats by name (e.g. "delta"); users see their label.
  function formatLabel(name) {
    return model.get("_format_labels")[name] ?? name;
  }

  function onMenuInfo(msg) {
    if (menuInfo?.path !== msg.path) return;
    const { path, previewRow, previewAsRow, previewAsSub, editRow, codeSub } = menuInfo;
    if (!msg.error && msg.query && previewRow) previewRow.firstChild.textContent = "Query data";
    // "Preview as" only appears when the item matches more than one format.
    if (!msg.error && msg.formats.length > 1) {
      const items = msg.formats.map((format) => ({ label: `Preview as ${formatLabel(format)}`, action: () => openPreview(path, format) }));
      previewAsSub.replaceChildren(...menuRows(items));
      previewAsRow.hidden = false;
    }
    if (!msg.error && msg.editable) editRow.hidden = false;
    let items;
    if (msg.error) {
      items = [{ label: msg.error, disabled: true }];
    } else if (!msg.recipes.length) {
      items = [{ label: "No code for this item", disabled: true }];
    } else {
      items = msg.recipes.map((recipe) => ({
        label: `Load with ${recipe.library}`,
        action: () => showDialog(`Load with ${recipe.library}`, null, recipeBlocks(recipe)),
      }));
    }
    codeSub.replaceChildren(...menuRows(items));
  }

  // Menu items for one or more items ({path, url, type}). The tree passes
  // withOpen = false: clicking a tree folder already opens it.
  function itemMenu(targets, withOpen = true) {
    const single = targets.length === 1 ? targets[0] : null;
    const count = targets.length > 1 ? `${targets.length} ` : "";
    // Items without a URL (the kernel's _url gave None) are not treated as data:
    // no preview, code or editing.
    const data = single?.url ? single : null;
    // The reply arrives after the menu is built, so the refs below are set by then.
    const info = data ? requestMenuInfo(data.path) : null;
    const items = [
      {
        label: "Preview",
        disabled: !data,
        // Relabelled "Query data" when the kernel says it opens in the data browser.
        ref: (row) => info && (info.previewRow = row),
        action: () => openPreview(single.path),
      },
    ];
    if (info) {
      items.push({
        label: "Preview as",
        hidden: true,
        ref: (row) => (info.previewAsRow = row),
        submenu: (sub) => (info.previewAsSub = sub),
      });
    }
    if (withOpen && single?.type === "directory") items.push({ label: "Open", action: () => navigate(single.path) });
    if (info) {
      items.push({ label: "Edit", hidden: true, ref: (row) => (info.editRow = row), action: () => openEditor(single.path) });
    }
    items.push({
      label: "Python code",
      disabled: !data,
      submenu: (sub) => {
        sub.replaceChildren(...menuRows([{ label: "Loading…", disabled: true }]));
        info.codeSub = sub;
      },
    });
    items.push("-");
    // Files only: downloading folders is intentionally not supported.
    if (targets.every((t) => t.type !== "directory")) {
      items.push({
        label: count ? `Download ${count}files` : "Download",
        action: () => download(targets.map((t) => t.path)),
      });
    }
    // Locations are copied only as URLs: fsspec's paths can differ from the
    // storage's own notion of a path (e.g. abfs's "container/key").
    if (targets.every((t) => t.url)) {
      items.push({ label: `Copy ${count}URL${count ? "s" : ""}`, action: () => copy(targets.map((t) => t.url), count ? `${count}URLs` : "URL") });
    }
    return items;
  }

  const columns = [
    { key: "name", label: "Name" },
    { key: "size", label: "Size" },
    { key: "mtime", label: "Modified" },
  ];

  // Directories from the root down to and including `path`.
  function ancestors(path) {
    const root = model.get("_root");
    if (!path.startsWith(root)) return [path];
    const out = [root];
    let cur = root;
    for (const segment of path.slice(root.length).split("/").filter(Boolean)) {
      cur = join(cur, segment);
      out.push(cur);
    }
    return out;
  }

  function navigate(path) {
    model.set("_current_dir", path);
    model.save_changes();
  }

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
    renderTree();
  }

  function renderTree() {
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
      const isOpen = expanded.has(dir.path);
      if (isOpen) requestChildren(dir.path);

      const twisty = h("span", {
        className: "jse-twisty",
        textContent: children && children.length === 0 ? "" : isOpen ? "▾" : "▸",
      });
      twisty.addEventListener("click", (ev) => {
        ev.stopPropagation();
        toggle(dir.path);
      });

      const row = h(
        "div",
        { className: "jse-node" + (dir.path === current ? " jse-active" : ""), title: dir.path },
        twisty,
        h("span", { className: "jse-icon", textContent: "📁" }),
        h("span", { className: "jse-label", textContent: dir.name }),
      );
      row.style.paddingLeft = `${depth * 14 + 4}px`;
      row.dataset.dropDir = dir.path; // files dropped here are uploaded into this folder
      // For styling by depth, e.g. [data-depth="1"]: 0 is the root, 1 a top-level folder.
      row.dataset.depth = depth;
      row.addEventListener("click", () => navigate(dir.path));
      row.addEventListener("contextmenu", (ev) => showMenu(ev, itemMenu([{ ...dir, type: "directory" }], false)));

      const wrap = h("div", {}, row);
      if (isOpen && children) for (const child of children) wrap.append(node(child, depth + 1));
      return wrap;
    }

    treeEl.replaceChildren(node({ name: rootLabel(root), path: root }, 0));
    treeEl.querySelector(".jse-active")?.scrollIntoView({ block: "nearest" });
  }

  function renderPath() {
    const chain = ancestors(model.get("_current_dir"));
    pathEl.replaceChildren();
    chain.forEach((path, i) => {
      if (i > 0) pathEl.append(h("span", { className: "jse-sep", textContent: "/" }));
      const name = i === 0 ? rootLabel(path) : path.slice(path.lastIndexOf("/") + 1);
      const crumb = h("span", { className: "jse-crumb", textContent: name, title: path });
      crumb.addEventListener("click", () => navigate(path));
      pathEl.append(crumb);
    });
    upBtn.disabled = chain.length < 2;
  }

  function compare(a, b) {
    const aDir = a.type === "directory";
    if (aDir !== (b.type === "directory")) return aDir ? -1 : 1;
    const r =
      sort.key === "name"
        ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" })
        : (a[sort.key] ?? -Infinity) - (b[sort.key] ?? -Infinity);
    return sort.asc ? r : -r;
  }

  function select(path, additive) {
    const current = model.get("_selected");
    const next = !additive
      ? [path]
      : current.includes(path)
        ? current.filter((p) => p !== path)
        : [...current, path];
    model.set("_selected", next);
    model.save_changes();
    // While the preview panel is open, it follows a single selected file.
    // Folders are not previewed on click (use Preview for e.g. a Delta table).
    if (!previewEl.hidden && next.length === 1 && next[0] !== model.get("_preview").path) {
      const entry = model.get("_entries").find((e) => e.path === next[0]);
      if (entry && entry.type !== "directory" && entry.url) openPreview(next[0]);
    }
  }

  function renderList() {
    headRow.replaceChildren(
      ...columns.map((col) => {
        const arrow = sort.key === col.key ? (sort.asc ? " ▲" : " ▼") : "";
        const th = h("th", { className: `jse-col-${col.key}`, textContent: col.label + arrow });
        th.addEventListener("click", () => {
          sort.asc = sort.key === col.key ? !sort.asc : true;
          sort.key = col.key;
          renderList();
        });
        return th;
      }),
    );

    const selected = new Set(model.get("_selected"));
    const entries = [...model.get("_entries")].sort(compare);
    tbody.replaceChildren(
      ...entries.map((entry) => {
        const isDir = entry.type === "directory";
        const tr = h(
          "tr",
          { className: selected.has(entry.path) ? "jse-selected" : "", title: entry.path },
          h(
            "td",
            { className: "jse-col-name" },
            h("span", { className: "jse-icon", textContent: isDir ? "📁" : "📄" }),
            entry.name,
          ),
          h("td", { className: "jse-col-size", textContent: formatSize(entry.size) }),
          h("td", { className: "jse-col-mtime", textContent: formatTime(entry.mtime) }),
        );
        if (isDir) {
          tr.dataset.dropDir = entry.path; // files dropped here are uploaded or moved into this folder
          // Depth from the root, as in the tree: ancestors() lists the root down to
          // this folder, so a top-level folder gives 2 entries, i.e. depth 1.
          if (entry.path.startsWith(model.get("_root"))) tr.dataset.depth = ancestors(entry.path).length - 1;
        } else {
          // e.g. "csv", "json-lines"; lets CSS style the icon per format.
          if (entry.format) tr.dataset.fileFormat = entry.format;
          // Files can be dragged onto a folder to move them there.
          tr.draggable = true;
          tr.addEventListener("dragstart", (ev) => {
            const paths = draggedFiles(entry);
            ev.dataTransfer.setData(MOVE_MIME, JSON.stringify(paths));
            ev.dataTransfer.effectAllowed = "move";
          });
        }
        tr.addEventListener("click", (ev) => select(entry.path, ev.ctrlKey || ev.metaKey));
        tr.addEventListener("dblclick", () => {
          if (isDir) navigate(entry.path);
          else if (entry.url) openPreview(entry.path); // no URL: no preview
        });
        tr.addEventListener("contextmenu", (ev) => {
          // Like file managers: right-clicking outside the selection selects that item.
          let paths = model.get("_selected");
          if (!paths.includes(entry.path)) {
            select(entry.path, false);
            paths = [entry.path];
          }
          showMenu(ev, itemMenu(entries.filter((e) => paths.includes(e.path))));
        });
        return tr;
      }),
    );
    updatePreviewBtn();
    renderStatus();
  }

  // What the Preview button previews, and in which format: the single
  // selected item, or with nothing selected, the current folder (e.g. one just
  // clicked in the tree). null when that cannot be previewed, or while the
  // kernel has not yet said what the newly selected item is.
  function previewTarget() {
    const selected = model.get("_selected");
    if (selected.length === 0) {
      const format = model.get("_current_format");
      return format ? { path: model.get("_current_dir"), format, query: model.get("_current_query") } : null;
    }
    const known = model.get("_selected_format");
    if (selected.length === 1 && known.path === selected[0] && known.format) return known;
    return null;
  }

  function updatePreviewBtn() {
    const target = previewTarget();
    const selected = model.get("_selected").length;
    // Tabular data opens in the data browser when polars is installed.
    const action = target?.query ? "Query data" : "Preview";
    previewBtn.disabled = target == null;
    previewBtn.textContent = target ? `${action} (${formatLabel(target.format)})` : "Preview";
    previewBtn.title = target
      ? `${action}: ${selected === 0 ? "this folder" : "the selected item"} as ${formatLabel(target.format)}`
      : selected > 1
        ? "Select one item to preview"
        : "Nothing to preview here";
  }

  function renderStatus() {
    if (flashTimer) return; // a message is showing; it calls back when done
    const error = model.get("_error");
    statusEl.classList.toggle("jse-error", Boolean(error));
    // Errors always show. The item count is about the file list, so it is
    // hidden while the preview panel (just above the status bar) is open,
    // where it could be mistaken for a count of the previewed data.
    statusEl.hidden = !error && !previewEl.hidden;
    if (error) {
      statusEl.textContent = error;
      return;
    }
    const count = model.get("_entries").length;
    const sel = model.get("_selected").length;
    statusEl.textContent = `${count} item${count === 1 ? "" : "s"}` + (sel ? `, ${sel} selected` : "");
  }

  // --- Dialog for "Python code" ---

  function showDialog(title, badge, children) {
    dialogHead.replaceChildren(h("span", { className: "jse-preview-name", textContent: title, title }));
    if (badge) dialogHead.append(h("span", { className: "jse-badge", textContent: badge }));
    dialogHead.append(h("span", { className: "jse-spacer" }), closeBtn);
    dialogBody.replaceChildren(...children);
    dialogBody.scrollTop = 0;
    dialogEl.hidden = false;
    dialogEl.focus({ preventScroll: true });
  }

  function closeDialog() {
    dialogEl.hidden = true;
    el.focus({ preventScroll: true });
  }

  // --- Text editor: the kernel reads and writes the file ---

  // {path, version, original, saving} while the editor is open. `version`
  // identifies the contents opened, so the kernel can refuse to overwrite a
  // file changed elsewhere; `original` is the text as shown, to detect edits.
  let editing = null;

  function editorMessage(text, isError = false) {
    editorMsg.textContent = text;
    editorMsg.classList.toggle("jse-error-text", isError);
  }

  function updateEditorButtons() {
    const dirty = editing != null && editing.original != null && editorText.value !== editing.original;
    saveBtn.disabled = !dirty || editing.saving;
    cancelBtn.disabled = Boolean(editing?.saving);
  }

  function openEditor(path) {
    editing = { path, version: null, original: null, saving: false };
    editorTitle.textContent = editorTitle.title = path;
    editorText.value = "";
    editorText.disabled = true;
    editorMessage("Loading…");
    updateEditorButtons();
    editorEl.hidden = false;
    model.send({ type: "edit_open", path });
  }

  function onEditOpen(msg) {
    if (editing?.path !== msg.path) return;
    if (msg.error) {
      editorMessage(msg.error, true);
      return;
    }
    editorText.value = msg.text;
    // Browsers turn "\r\n" into "\n" in text areas; compare against what is shown.
    editing.original = editorText.value;
    editing.version = msg.version;
    editorText.disabled = false;
    editorMessage("");
    updateEditorButtons();
    editorText.focus({ preventScroll: true });
    editorText.setSelectionRange(0, 0);
    editorText.scrollTop = 0;
  }

  function saveEdit() {
    if (!editing || saveBtn.disabled) return;
    editing.saving = true;
    editorMessage("Saving…");
    updateEditorButtons();
    model.send({ type: "edit_save", path: editing.path, text: editorText.value, version: editing.version });
  }

  function onEditSave(msg) {
    if (editing?.path !== msg.path) return;
    editing.saving = false;
    if (msg.error) {
      editorMessage(msg.error, true);
      updateEditorButtons();
      return;
    }
    const name = editing.path.slice(editing.path.lastIndexOf("/") + 1);
    closeEditor();
    flash(`Saved ${name}`);
  }

  function cancelEdit() {
    if (editing?.saving) return;
    const dirty = editing?.original != null && editorText.value !== editing.original;
    if (dirty && !window.confirm("Discard your changes?")) return;
    closeEditor();
  }

  function closeEditor() {
    editing = null;
    editorEl.hidden = true;
    el.focus({ preventScroll: true });
  }

  editorText.addEventListener("input", updateEditorButtons);
  saveBtn.addEventListener("click", saveEdit);
  cancelBtn.addEventListener("click", cancelEdit);
  editorEl.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
      ev.preventDefault(); // not the browser's "Save page"
      saveEdit();
    } else if (ev.key === "Escape") {
      cancelEdit();
    } else {
      return;
    }
    ev.stopPropagation(); // keep the widget's own Escape handling out of it
  });

  // --- Data browser ("Query data"): the panel is in query.js ---

  let queryPanel = null; // the data browser shown in the preview panel

  function renderQuery(preview) {
    queryPanel?.dispose();
    queryPanel = createQueryPanel({ request, ask, answer, flash }, preview.path, preview.query);
    return queryPanel.el;
  }

  // --- Preview panel: shows the kernel's `preview` trait ---

  // `format` (a format name) previews with that format instead of the best match.
  function openPreview(path, format = null) {
    model.send({ type: "preview", path, format });
  }

  function closePreview() {
    // The kernel owns the preview; clearing it closes the panel.
    model.set("_preview", {});
    model.save_changes();
  }

  function renderPreview() {
    const preview = model.get("_preview");
    if (!preview.query) {
      queryPanel?.dispose();
      queryPanel = null;
    }
    if (!preview.path) {
      previewEl.hidden = true;
      renderStatus(); // the item count shows again
      return;
    }
    const opening = previewEl.hidden || previewHead.dataset.path !== preview.path;
    previewHead.dataset.path = preview.path;
    previewHead.replaceChildren(h("span", { className: "jse-preview-name", textContent: preview.path, title: preview.path }));
    if (preview.format) previewHead.append(h("span", { className: "jse-badge", textContent: formatLabel(preview.format) }));
    previewHead.append(h("span", { className: "jse-spacer" }), previewCloseBtn);

    let body;
    if (preview.loading) {
      body = [h("div", { className: "jse-placeholder", textContent: "Loading…" })];
    } else if (preview.error) {
      body = [h("div", { className: "jse-preview-error", textContent: preview.error })];
    } else if (!preview.format) {
      body = [h("div", { className: "jse-placeholder", textContent: "No preview for this kind of item" })];
    } else if (preview.query) {
      body = [renderQuery(preview)];
    } else {
      body = preview.sections.map(renderSection);
      if (preview.sections.some((s) => s.kind === "install")) {
        // After installing, this re-runs the preview with the same format.
        const again = h("button", { className: "jse-btn jse-primary", textContent: "Preview again" });
        again.addEventListener("click", () => openPreview(preview.path, preview.format));
        body.push(again);
      }
    }
    previewBody.replaceChildren(...body);
    previewEl.hidden = false;
    if (opening) {
      previewBody.scrollTop = 0;
      renderStatus(); // hides the item count
    }
  }

  // --- Resizing by dragging; heights set here are kept until `height` changes ---

  const MIN_AREA_HEIGHT = 80;

  // The splitter moves the boundary: the list gains what the panel loses.
  onDragY(splitter, () => {
    const panes = panesEl.offsetHeight;
    const panel = previewEl.offsetHeight;
    return (dy) => {
      const d = Math.max(MIN_AREA_HEIGHT - panes, Math.min(panel - MIN_AREA_HEIGHT, dy));
      panesEl.style.height = `${panes + d}px`;
      previewEl.style.height = `${panel - d}px`;
    };
  });

  // The bottom grip resizes the last area, so the whole widget grows or shrinks.
  onDragY(grip, () => {
    const area = previewEl.hidden ? panesEl : previewEl;
    const start = area.offsetHeight;
    return (dy) => (area.style.height = `${Math.max(MIN_AREA_HEIGHT, start + dy)}px`);
  });

  function onDirChange() {
    // Only folders under the root belong to this filesystem's tree.
    if (model.get("_current_dir").startsWith(model.get("_root"))) {
      for (const path of ancestors(model.get("_current_dir"))) expanded.add(path);
    }
    renderTree();
    renderPath();
  }

  // "fill": the widget fills its container (see "jse-fill" in the CSS);
  // otherwise the CSS height of the tree and list.
  function applyHeight() {
    const height = model.get("_height");
    el.classList.toggle("jse-fill", height === "fill");
    el.style.setProperty("--jse-height", height === "fill" ? "" : height);
    panesEl.style.height = ""; // a new `height` replaces any dragged size
  }

  // --- Filesystem chooser ---

  function renderFsSelect() {
    const names = model.get("_filesystem_names");
    fsSelect.replaceChildren(...names.map((name) => h("option", { value: name, textContent: name })));
    fsSelect.value = model.get("_filesystem");
    fsSelect.hidden = names.length < 2;
  }

  // The filesystem whose folders `expanded` holds. Tracked here because
  // anywidget's model has no previous(): its API is get/set/save_changes/on/off/send.
  let shownFs = model.get("_filesystem");

  function onFilesystemChange() {
    const name = model.get("_filesystem");
    if (name === shownFs) return;
    // Keep the tree's expanded folders of the filesystem left, and restore
    // those of the one switched to. The kernel restores its current folder.
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

  upBtn.addEventListener("click", () => {
    const chain = ancestors(model.get("_current_dir"));
    if (chain.length > 1) navigate(chain[chain.length - 2]);
  });
  refreshBtn.addEventListener("click", () => model.send({ type: "refresh" }));
  previewBtn.addEventListener("click", () => {
    const target = previewTarget();
    if (target != null) openPreview(target.path, target.format);
  });
  closeBtn.addEventListener("click", closeDialog);
  // Clicking the backdrop (outside the window) closes the dialog.
  dialogEl.addEventListener("pointerdown", (ev) => ev.target === dialogEl && closeDialog());
  previewCloseBtn.addEventListener("click", closePreview);
  el.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (!dialogEl.hidden) closeDialog();
    else if (!previewEl.hidden) closePreview();
    else return;
    ev.stopPropagation();
  });

  const handlers = {
    "change:_tree": renderTree,
    "change:_current_dir": onDirChange,
    // The address bar starts at the root, which differs per filesystem.
    "change:_root": onDirChange,
    "change:_filesystem": onFilesystemChange,
    "change:_filesystem_names": renderFsSelect,
    "change:_entries": renderList,
    "change:_selected": renderList,
    "change:_error": renderStatus,
    "change:_height": applyHeight,
    "change:_preview": renderPreview,
    "change:_current_format": updatePreviewBtn,
    "change:_selected_format": updatePreviewBtn,
    "change:_current_query": updatePreviewBtn,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  applyHeight();
  renderFsSelect();
  onDirChange();
  renderList();
  renderPreview();

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
    hideMenu();
    clearTimeout(flashTimer);
    queryPanel?.dispose();
  };
}

export default { render };
