// Storage Explorer: directory tree (left) and file list (right), with a
// preview panel below them.

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

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  Object.assign(el, props);
  el.append(...children);
  return el;
}

// --- Preview sections (one renderer per Preview kind in formats/base.py) ---

function cellText(value) {
  if (value == null) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

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

// Body of the "Python code" dialog for one recipe ({library, install, code}).
function recipeBlocks(recipe) {
  if (!recipe.install) return [codeBlock("Load", recipe.code)];
  return [
    codeBlock("1. Install", recipe.install, "Some packages are not installed in this kernel. Run this in a cell first."),
    codeBlock("2. Load", recipe.code),
  ];
}

function render({ model, el }) {
  // Expanded tree folders, kept per filesystem so switching back restores them.
  const expandedByFs = new Map();
  let expanded = new Set();
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
  const confirmBody = h("div", { className: "jse-dialog-body" });
  const confirmButtons = h("div", { className: "jse-editor-foot" });
  const confirmEl = h(
    "div",
    { className: "jse-dialog", tabIndex: -1, hidden: true },
    h("div", { className: "jse-modal jse-confirm" }, confirmBody, confirmButtons),
  );

  el.classList.add("jse-browser");
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

  // --- Confirmation dialog ---

  let confirmResolve = null;

  // Resolves with the clicked button's value, or null for Cancel/Esc/backdrop.
  // buttons: [{label, value, primary}], shown left to right.
  function ask(lines, buttons) {
    confirmResolve?.(null);
    return new Promise((resolve) => {
      confirmResolve = resolve;
      confirmBody.replaceChildren(...lines);
      confirmButtons.replaceChildren(
        h("span", { className: "jse-spacer" }),
        ...buttons.map((b) => {
          const btn = h("button", { className: "jse-btn" + (b.primary ? " jse-primary" : ""), textContent: b.label });
          btn.addEventListener("click", () => answer(b.value));
          return btn;
        }),
      );
      confirmEl.hidden = false;
      confirmEl.focus({ preventScroll: true });
    });
  }

  function answer(value) {
    confirmEl.hidden = true;
    const resolve = confirmResolve;
    confirmResolve = null;
    resolve?.(value);
  }

  confirmEl.addEventListener("pointerdown", (ev) => ev.target === confirmEl && answer(null));
  confirmEl.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    ev.stopPropagation();
    answer(null);
  });

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
    return { el: listEl, dir: model.get("current_dir") };
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
  let nextRequestId = 1;
  const waitingReplies = new Map();

  function request(content, buffers) {
    const rid = nextRequestId++;
    return new Promise((resolve) => {
      waitingReplies.set(rid, resolve);
      model.send({ ...content, rid }, undefined, buffers);
    });
  }

  // Lets Markdown previews load the vendored libraries through this widget's kernel.
  fetchVendor = async (name) => {
    const reply = await request({ type: "vendor", name });
    if (reply.error) throw new Error(reply.error);
    return reply.source;
  };

  function onReply(msg) {
    const resolve = waitingReplies.get(msg.rid);
    waitingReplies.delete(msg.rid);
    resolve?.(msg);
  }

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
    const limit = model.get("max_upload_bytes");
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
    const selected = model.get("selected");
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

  function onMenuInfo(msg) {
    if (menuInfo?.path !== msg.path) return;
    const { path, previewRow, previewAsRow, previewAsSub, editRow, codeSub } = menuInfo;
    if (!msg.error && msg.query && previewRow) previewRow.firstChild.textContent = "Query data";
    // "Preview as" only appears when the item matches more than one format.
    if (!msg.error && msg.formats.length > 1) {
      const items = msg.formats.map((format) => ({ label: `Preview as ${format}`, action: () => openPreview(path, format) }));
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
    // The reply arrives after the menu is built, so the refs below are set by then.
    const info = single ? requestMenuInfo(single.path) : null;
    const items = [
      {
        label: "Preview",
        disabled: !single,
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
      disabled: !single,
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
    items.push({
      label: `Copy ${count}path${count ? "s" : ""}`,
      action: () => copy(targets.map((t) => t.path), count ? `${count}paths` : "path"),
    });
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
    const root = model.get("root");
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
    model.set("current_dir", path);
    model.save_changes();
  }

  function requestChildren(path) {
    if (path in model.get("tree") || pending.has(path)) return;
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
    const tree = model.get("tree");
    const root = model.get("root");
    const current = model.get("current_dir");

    for (const path of pending) if (path in tree) pending.delete(path);

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
    const chain = ancestors(model.get("current_dir"));
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
    const current = model.get("selected");
    const next = !additive
      ? [path]
      : current.includes(path)
        ? current.filter((p) => p !== path)
        : [...current, path];
    model.set("selected", next);
    model.save_changes();
    // While the preview panel is open, it follows a single selected file.
    // Folders are not previewed on click (use Preview for e.g. a Delta table).
    if (!previewEl.hidden && next.length === 1 && next[0] !== model.get("preview").path) {
      const entry = model.get("entries").find((e) => e.path === next[0]);
      if (entry && entry.type !== "directory") openPreview(next[0]);
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

    const selected = new Set(model.get("selected"));
    const entries = [...model.get("entries")].sort(compare);
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
          if (entry.path.startsWith(model.get("root"))) tr.dataset.depth = ancestors(entry.path).length - 1;
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
        tr.addEventListener("dblclick", () => (isDir ? navigate(entry.path) : openPreview(entry.path)));
        tr.addEventListener("contextmenu", (ev) => {
          // Like file managers: right-clicking outside the selection selects that item.
          let paths = model.get("selected");
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
    const selected = model.get("selected");
    if (selected.length === 0) {
      const format = model.get("current_format");
      return format ? { path: model.get("current_dir"), format, query: model.get("current_query") } : null;
    }
    const known = model.get("selected_format");
    if (selected.length === 1 && known.path === selected[0] && known.format) return known;
    return null;
  }

  function updatePreviewBtn() {
    const target = previewTarget();
    const selected = model.get("selected").length;
    // Tabular data opens in the data browser when polars is installed.
    const action = target?.query ? "Query data" : "Preview";
    previewBtn.disabled = target == null;
    previewBtn.textContent = target ? `${action} (${target.format})` : "Preview";
    previewBtn.title = target
      ? `${action}: ${selected === 0 ? "this folder" : "the selected item"} as ${target.format}`
      : selected > 1
        ? "Select one item to preview"
        : "Nothing to preview here";
  }

  function renderStatus() {
    if (flashTimer) return; // a message is showing; it calls back when done
    const error = model.get("error");
    statusEl.classList.toggle("jse-error", Boolean(error));
    // Errors always show. The item count is about the file list, so it is
    // hidden while the preview panel (just above the status bar) is open,
    // where it could be mistaken for a count of the previewed data.
    statusEl.hidden = !error && !previewEl.hidden;
    if (error) {
      statusEl.textContent = error;
      return;
    }
    const count = model.get("entries").length;
    const sel = model.get("selected").length;
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

  // --- Data browser ("Query data"): pages through a polars query in the kernel ---
  // The kernel applies the settings (filters, sort, hidden columns) and
  // returns QUERY_WINDOW rows at a time; pages of QUERY_PAGE rows are shown
  // from that window. The kernel also remembers the settings per dataset.

  const QUERY_WINDOW = 1000;
  const QUERY_PAGE = 100;
  const OP_LABELS = {
    not_null: "Not null",
    null: "Null",
    eq: "=",
    contains: "Contains",
    regex: "Regex",
    not_empty: "Not empty",
    empty: "Empty",
    gt: ">",
    lt: "<",
    ge: ">=",
    le: "<=",
  };
  const NO_VALUE_OPS = new Set(["not_null", "null", "not_empty", "empty"]);
  const VALUE_HINTS = { numeric: "e.g. 10", temporal: "e.g. 2025-01-31", boolean: "true or false", text: "" };

  let queryView = null; // the data browser shown in the preview panel

  function renderQuery(preview) {
    queryView = {
      path: preview.path,
      columns: preview.query.columns, // {name, dtype, kind, ops}
      settings: preview.query.settings, // remembered by the kernel
      start: 0, // first row of the fetched window
      rows: [],
      more: false,
      page: 0, // page within the window
      loading: false,
      error: "",
      el: h("div", { className: "jse-query" }),
    };
    fetchQuery(0, 0);
    return queryView.el;
  }

  async function fetchQuery(start, page) {
    const view = queryView;
    view.loading = true;
    drawQuery();
    const reply = await request({ type: "query_rows", path: view.path, settings: view.settings, offset: start, window: QUERY_WINDOW });
    if (queryView !== view) return; // another dataset was opened meanwhile
    view.loading = false;
    if (reply.settings) view.settings = reply.settings;
    if (reply.error) {
      Object.assign(view, { error: reply.error, rows: [], more: false, start: 0, page: 0 });
    } else {
      Object.assign(view, { error: "", start: reply.offset, rows: reply.rows, more: reply.more, page });
    }
    drawQuery();
  }

  function queryButton(label, onClick, title = "") {
    const btn = h("button", { className: "jse-btn", textContent: label, title });
    btn.addEventListener("click", onClick);
    return btn;
  }

  function drawQuery() {
    const view = queryView;
    const s = view.settings;
    const columns = view.columns.filter((c) => !s.hidden.includes(c.name));
    const pageRows = view.rows.slice(view.page * QUERY_PAGE, (view.page + 1) * QUERY_PAGE);
    const first = view.start + view.page * QUERY_PAGE;
    const hasNext = (view.page + 1) * QUERY_PAGE < view.rows.length || view.more;
    const resettable = Object.keys(s.filters).length > 0 || s.hidden.length > 0;

    let status;
    if (view.loading) status = "Loading…";
    else if (!pageRows.length) status = "No rows";
    else {
      const total = view.more ? "" : ` of ${(view.start + view.rows.length).toLocaleString()}`;
      status = `Rows ${(first + 1).toLocaleString()}–${(first + pageRows.length).toLocaleString()}${total}`;
    }

    const prev = queryButton("◀", prevQueryPage, "Previous page");
    prev.disabled = view.loading || first === 0;
    const next = queryButton("▶", nextQueryPage, "Next page");
    next.disabled = view.loading || !hasNext;
    const reset = queryButton("Reset", resetQuery, "Remove all filters and show all columns");
    reset.disabled = !resettable;
    const toolbar = h(
      "div",
      { className: "jse-query-bar" },
      queryButton(s.hidden.length ? `Select columns (${s.hidden.length} hidden)` : "Select columns", openColumnsDialog),
      h("div", { className: "jse-query-chips" }, ...Object.entries(s.filters).map(([name, f]) => filterChip(name, f))),
      reset,
      prev,
      h("span", { className: "jse-query-status", textContent: status }),
      next,
    );

    const head = h("tr", {}, ...columns.map((c) => queryHeaderCell(c)));
    const body = pageRows.map((row) =>
      h(
        "tr",
        {},
        ...row.map((v) => {
          const text = v == null ? "null" : cellText(v);
          // The title shows values cut off in narrow columns.
          return h("td", { textContent: text, title: text, className: v == null ? "jse-null" : "" });
        }),
      ),
    );
    const tableEl = h("table", { className: "jse-data" }, h("thead", {}, head), h("tbody", {}, ...body));
    wireColumnResizers(tableEl, columns);
    const parts = [toolbar];
    if (view.error) parts.push(h("div", { className: "jse-preview-error", textContent: view.error }));
    parts.push(h("div", { className: "jse-table-wrap" }, tableEl));
    view.el.replaceChildren(...parts);
  }

  // Column header filter icons: SVG, drawn in the text colour (currentColor);
  // CSS fills them in when the column has a filter. FILTER_ICON is the one used.
  const FUNNEL_ICON =
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' +
    '<path d="M1.5 2.5h13l-5 6v5l-3-1.5v-3.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  const SEARCH_ICON =
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' +
    '<circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/>' +
    '<path d="M10 10l4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  const FILTER_ICON = FUNNEL_ICON;

  // Name (click to sort) and filter button, and type underneath.
  function queryHeaderCell(column) {
    const s = queryView.settings;
    const sorted = s.sort?.column === column.name;
    const name = h("span", {
      className: "jse-query-name",
      textContent: column.name + (sorted ? (s.sort.descending ? " ▼" : " ▲") : ""),
      title: "Sort by this column (click again to reverse, a third time to stop sorting)",
    });
    name.addEventListener("click", () => toggleQuerySort(column.name));
    const active = s.filters[column.name];
    const filterBtn = h("button", {
      className: "jse-query-filter" + (active ? " jse-active" : ""),
      innerHTML: FILTER_ICON,
      title: active ? `Filter: ${describeFilter(column.name, active)}` : "Filter",
    });
    filterBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openFilterDialog(column);
    });
    return h(
      "th",
      {},
      h("div", { className: "jse-query-head" }, name, filterBtn),
      h("div", { className: "jse-query-dtype", textContent: column.dtype }),
      // Drag to resize the column; double-click to go back to automatic widths.
      h("span", { className: "jse-col-resizer", title: "Drag to resize; double-click for automatic widths" }),
    );
  }

  // --- Column widths: automatic until a column is resized, then fixed ---
  // Part of the dataset's settings ("widths": {column name: px}), so the
  // kernel remembers them with the filters.
  const MIN_COLUMN_WIDTH = 40;
  const DEFAULT_COLUMN_WIDTH = 120;

  // Remembers settings changed without fetching rows, e.g. column widths.
  function saveQuerySettings() {
    const view = queryView;
    request({ type: "query_save", path: view.path, settings: view.settings });
  }

  // Fixes the table's layout to the given widths.
  function applyColumnWidths(table, columns, widths) {
    table.querySelector("colgroup")?.remove();
    const cols = columns.map((c) => h("col", { style: `width: ${widths[c.name]}px` }));
    table.prepend(h("colgroup", {}, ...cols));
    table.classList.add("jse-fixed");
    table.style.width = `${columns.reduce((sum, c) => sum + widths[c.name], 0)}px`;
    return cols;
  }

  function wireColumnResizers(table, columns) {
    const view = queryView;
    const hasWidths = () => Object.keys(view.settings.widths ?? {}).length > 0;
    if (hasWidths()) {
      // Columns without a remembered width (e.g. shown again) get a default.
      const widths = { ...view.settings.widths };
      for (const c of columns) widths[c.name] ??= DEFAULT_COLUMN_WIDTH;
      applyColumnWidths(table, columns, widths);
    }
    table.querySelectorAll(".jse-col-resizer").forEach((handle, i) => {
      handle.addEventListener("click", (ev) => ev.stopPropagation());
      handle.addEventListener("dblclick", (ev) => {
        ev.stopPropagation();
        view.settings.widths = {};
        saveQuerySettings();
        drawQuery();
      });
      handle.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (!hasWidths()) {
          // First resize: fix every column at its current automatic width.
          const cells = table.querySelectorAll("thead th");
          view.settings.widths = Object.fromEntries(
            columns.map((c, j) => [c.name, Math.round(cells[j].getBoundingClientRect().width)]),
          );
        }
        const widths = view.settings.widths;
        for (const c of columns) widths[c.name] ??= DEFAULT_COLUMN_WIDTH;
        const cols = applyColumnWidths(table, columns, widths);
        const name = columns[i].name;
        const startX = ev.clientX;
        const startWidth = widths[name];
        handle.setPointerCapture(ev.pointerId);
        const move = (e) => {
          widths[name] = Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + e.clientX - startX));
          cols[i].style.width = `${widths[name]}px`;
          table.style.width = `${columns.reduce((sum, c) => sum + widths[c.name], 0)}px`;
        };
        const up = () => {
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          saveQuerySettings();
        };
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
      });
    });
  }

  // Ascending, then descending, then not sorted.
  function toggleQuerySort(name) {
    const s = queryView.settings;
    if (s.sort?.column !== name) s.sort = { column: name, descending: false };
    else if (!s.sort.descending) s.sort = { column: name, descending: true };
    else s.sort = null;
    fetchQuery(0, 0);
  }

  function nextQueryPage() {
    const view = queryView;
    if ((view.page + 1) * QUERY_PAGE < view.rows.length) {
      view.page += 1;
      drawQuery();
    } else if (view.more) {
      fetchQuery(view.start + QUERY_WINDOW, 0);
    }
  }

  function prevQueryPage() {
    const view = queryView;
    if (view.page > 0) {
      view.page -= 1;
      drawQuery();
    } else if (view.start > 0) {
      fetchQuery(Math.max(0, view.start - QUERY_WINDOW), QUERY_WINDOW / QUERY_PAGE - 1);
    }
  }

  // Removes the filters and shows all columns; the sort order stays.
  function resetQuery() {
    queryView.settings = { ...queryView.settings, filters: {}, hidden: [] };
    fetchQuery(0, 0);
  }

  // e.g. "quantity >= 8", "product contains tea (any case)", "comment: Not null".
  function describeFilter(name, filter) {
    if (NO_VALUE_OPS.has(filter.op)) return `${name}: ${OP_LABELS[filter.op]}`;
    const label = filter.op === "contains" || filter.op === "regex" ? OP_LABELS[filter.op].toLowerCase() : OP_LABELS[filter.op];
    return `${name} ${label} ${filter.value}` + (filter.case_sensitive === false ? " (any case)" : "");
  }

  // An applied filter in the toolbar: click to edit it, × to remove it.
  function filterChip(name, filter) {
    const text = describeFilter(name, filter);
    const label = h("span", { className: "jse-chip-label", textContent: text, title: `Edit filter: ${text}` });
    label.addEventListener("click", () => {
      const column = queryView.columns.find((c) => c.name === name);
      if (column) openFilterDialog(column);
    });
    const remove = h("button", { className: "jse-chip-remove", textContent: "×", title: "Remove this filter" });
    remove.addEventListener("click", () => {
      delete queryView.settings.filters[name];
      fetchQuery(0, 0);
    });
    return h("span", { className: "jse-chip" }, label, remove);
  }

  // The filter types that take no value (Null, Not null, Empty, Not empty)
  // are one type in the dialog, chosen between with radio buttons.
  const NO_VALUE_TYPE = "null_or_empty";
  const NO_VALUE_TYPE_LABEL = "Null / empty";

  // Text filters with a "Case sensitive" option.
  const CASE_OPS = new Set(["eq", "contains", "regex"]);
  // Browser field for each kind of value ("input" from the kernel).
  const INPUT_TYPES = {
    text: { type: "text" },
    number: { type: "number", step: "any" },
    date: { type: "date" },
    datetime: { type: "datetime-local", step: "1" },
    time: { type: "time", step: "1" },
  };

  // Radio buttons, one per [value, label]; returns the group and a getter.
  function radioGroup(choices, selected) {
    const name = `jse-radio-${Math.random().toString(36).slice(2)}`;
    const inputs = choices.map(([value]) => h("input", { type: "radio", name, value, checked: value === selected }));
    if (!inputs.some((i) => i.checked)) inputs[0].checked = true;
    const el = h(
      "div",
      { className: "jse-query-radios" },
      ...choices.map(([, label], i) => h("label", {}, inputs[i], h("span", { textContent: label }))),
    );
    return { el, value: () => inputs.find((i) => i.checked).value };
  }

  // `draft`: a filter the user entered but that was rejected, shown again to fix.
  async function openFilterDialog(column, draft = null) {
    const view = queryView;
    const current = view.settings.filters[column.name];
    const initial = draft ?? current;
    const currentValue = initial && !NO_VALUE_OPS.has(initial.op) ? initial.value : "";
    const noValueOps = column.ops.filter((op) => NO_VALUE_OPS.has(op));
    const valueOps = column.ops.filter((op) => !NO_VALUE_OPS.has(op));

    const typeSelect = h(
      "select",
      { className: "jse-query-input" },
      ...valueOps.map((op) => h("option", { value: op, textContent: OP_LABELS[op] })),
      h("option", { value: NO_VALUE_TYPE, textContent: NO_VALUE_TYPE_LABEL }),
    );
    if (initial) typeSelect.value = NO_VALUE_OPS.has(initial.op) ? NO_VALUE_TYPE : initial.op;
    else typeSelect.value = valueOps.includes("eq") ? "eq" : (valueOps[0] ?? NO_VALUE_TYPE);

    // The possible contents of the Value row; the type decides which is shown.
    const nullChoices = radioGroup(
      noValueOps.map((op) => [op, OP_LABELS[op]]),
      NO_VALUE_OPS.has(initial?.op) ? initial.op : "not_null",
    );
    const boolChoices = radioGroup(
      [
        ["true", "True"],
        ["false", "False"],
      ],
      ["false", "0", "no"].includes(currentValue.toLowerCase()) ? "false" : "true",
    );
    const valueInput = h("input", {
      className: "jse-query-input",
      ...(INPUT_TYPES[column.input] ?? INPUT_TYPES.text),
      // Date-time fields want "2025-01-31T12:00"; remembered values may have a space.
      value: column.input === "datetime" ? currentValue.replace(" ", "T") : currentValue,
      placeholder: VALUE_HINTS[column.kind] ?? "",
    });
    valueInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") answer("apply");
    });
    const caseBox = h("input", { type: "checkbox", checked: initial?.case_sensitive !== false });
    const caseLabel = h("label", { className: "jse-query-case" }, caseBox, h("span", { textContent: "Case sensitive" }));
    const valueCell = h("div", { className: "jse-query-value" });

    const isNoValue = () => typeSelect.value === NO_VALUE_TYPE;
    const showValue = () => {
      if (isNoValue()) valueCell.replaceChildren(nullChoices.el);
      else if (column.input === "boolean") valueCell.replaceChildren(boolChoices.el);
      else if (column.input === "text" && CASE_OPS.has(typeSelect.value)) valueCell.replaceChildren(valueInput, caseLabel);
      else valueCell.replaceChildren(valueInput);
    };
    typeSelect.addEventListener("change", showValue);
    showValue();

    const buttons = [{ label: "Cancel", value: null }];
    if (current) buttons.push({ label: "Clear filter", value: "clear" });
    buttons.push({ label: "Apply", value: "apply", primary: true });
    const asked = ask(
      [
        h("div", { className: "jse-section-title", textContent: `Filter: ${column.name}` }),
        h("div", { className: "jse-note", textContent: column.dtype }),
        h(
          "div",
          { className: "jse-query-form" },
          h("div", { className: "jse-query-row" }, h("span", { textContent: "Type" }), typeSelect),
          h("div", { className: "jse-query-row" }, h("span", { textContent: "Value" }), valueCell),
        ),
      ],
      buttons,
    );
    (valueInput.isConnected ? valueInput : typeSelect).focus({ preventScroll: true });
    const choice = await asked;
    if (queryView !== view || !choice) return;

    if (choice === "clear") {
      delete view.settings.filters[column.name];
      fetchQuery(0, 0);
      return;
    }
    let filter;
    if (isNoValue()) {
      filter = { op: nullChoices.value(), value: "" };
    } else if (column.input === "boolean") {
      filter = { op: typeSelect.value, value: boolChoices.value() };
    } else {
      filter = { op: typeSelect.value, value: valueInput.value };
      if (column.input === "text" && CASE_OPS.has(filter.op)) filter.case_sensitive = caseBox.checked;
    }

    // Check before applying: a value is given, and it fits the column (e.g. a
    // regular expression polars can compile). If not, say why and reopen the
    // dialog with what was entered.
    let problem = null;
    if (!NO_VALUE_OPS.has(filter.op) && filter.value.trim() === "") {
      problem = "Enter a value.";
    } else if (!NO_VALUE_OPS.has(filter.op)) {
      const reply = await request({ type: "query_check", path: view.path, column: column.name, filter });
      if (queryView !== view) return;
      problem = reply.error ?? null;
    }
    if (problem) {
      await showFilterError(column, filter, problem);
      if (queryView === view) openFilterDialog(column, filter);
      return;
    }
    view.settings.filters[column.name] = filter;
    fetchQuery(0, 0);
  }

  function showFilterError(column, filter, message) {
    const title = filter.op === "regex" ? "Invalid regular expression" : "Invalid filter value";
    return ask(
      [
        h("div", { className: "jse-section-title jse-error-text", textContent: title }),
        h("div", { className: "jse-note", textContent: `Filter on ${column.name}` }),
        // Monospace keeps polars' marker (^) under the right character.
        h("pre", { className: "jse-text jse-filter-error", textContent: message }),
      ],
      [{ label: "OK", value: true, primary: true }],
    );
  }

  async function openColumnsDialog() {
    const view = queryView;
    const boxes = view.columns.map((column) => ({
      column,
      box: h("input", { type: "checkbox", checked: !view.settings.hidden.includes(column.name) }),
    }));
    const setAll = (checked) => boxes.forEach(({ box }) => (box.checked = checked));
    const choice = await ask(
      [
        h("div", { className: "jse-section-title", textContent: "Select columns" }),
        h(
          "div",
          { className: "jse-query-colbar" },
          queryButton("Show all", () => setAll(true)),
          queryButton("Hide all", () => setAll(false)),
        ),
        h(
          "div",
          { className: "jse-query-cols" },
          ...boxes.map(({ column, box }) =>
            h("label", {}, box, h("span", { textContent: column.name }), h("span", { className: "jse-note", textContent: column.dtype })),
          ),
        ),
      ],
      [
        { label: "Cancel", value: null },
        { label: "Apply", value: true, primary: true },
      ],
    );
    if (queryView !== view || !choice) return;
    const hidden = boxes.filter(({ box }) => !box.checked).map(({ column }) => column.name);
    if (hidden.length === view.columns.length) {
      flash("Keep at least one column visible");
      return;
    }
    view.settings.hidden = hidden;
    fetchQuery(0, 0);
  }

  // --- Preview panel: shows the kernel's `preview` trait ---

  // `format` (a format name) previews with that format instead of the best match.
  function openPreview(path, format = null) {
    model.send({ type: "preview", path, format });
  }

  function closePreview() {
    // The kernel owns the preview; clearing it closes the panel.
    model.set("preview", {});
    model.save_changes();
  }

  function renderPreview() {
    const preview = model.get("preview");
    if (!preview.path) {
      previewEl.hidden = true;
      renderStatus(); // the item count shows again
      return;
    }
    const opening = previewEl.hidden || previewHead.dataset.path !== preview.path;
    previewHead.dataset.path = preview.path;
    previewHead.replaceChildren(h("span", { className: "jse-preview-name", textContent: preview.path, title: preview.path }));
    if (preview.format) previewHead.append(h("span", { className: "jse-badge", textContent: preview.format }));
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

  // Calls begin() on pointerdown; it returns a function given the vertical
  // distance dragged so far.
  function onDragY(handle, begin) {
    handle.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      handle.setPointerCapture(ev.pointerId);
      const startY = ev.clientY;
      const move = begin();
      const onMove = (e) => move(e.clientY - startY);
      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
    });
  }

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
    if (model.get("current_dir").startsWith(model.get("root"))) {
      for (const path of ancestors(model.get("current_dir"))) expanded.add(path);
    }
    renderTree();
    renderPath();
  }

  function applyHeight() {
    el.style.setProperty("--jse-height", model.get("height"));
    panesEl.style.height = ""; // a new `height` replaces any dragged size
  }

  // --- Filesystem chooser ---

  function renderFsSelect() {
    const names = model.get("filesystems");
    fsSelect.replaceChildren(...names.map((name) => h("option", { value: name, textContent: name })));
    fsSelect.value = model.get("filesystem");
    fsSelect.hidden = names.length < 2;
  }

  // The filesystem whose folders `expanded` holds. Tracked here because
  // anywidget's model has no previous(): its API is get/set/save_changes/on/off/send.
  let shownFs = model.get("filesystem");

  function onFilesystemChange() {
    const name = model.get("filesystem");
    if (name === shownFs) return;
    // Keep the tree's expanded folders of the filesystem left, and restore
    // those of the one switched to. The kernel restores its current folder.
    expandedByFs.set(shownFs, expanded);
    expanded = expandedByFs.get(name) ?? new Set();
    shownFs = name;
    pending.clear();
    fsSelect.value = name;
  }

  fsSelect.addEventListener("change", () => {
    model.set("filesystem", fsSelect.value);
    model.save_changes();
  });

  upBtn.addEventListener("click", () => {
    const chain = ancestors(model.get("current_dir"));
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
    "change:tree": renderTree,
    "change:current_dir": onDirChange,
    // The address bar starts at the root, which differs per filesystem.
    "change:root": onDirChange,
    "change:filesystem": onFilesystemChange,
    "change:filesystems": renderFsSelect,
    "change:entries": renderList,
    "change:selected": renderList,
    "change:error": renderStatus,
    "change:height": applyHeight,
    "change:preview": renderPreview,
    "change:current_format": updatePreviewBtn,
    "change:selected_format": updatePreviewBtn,
    "change:current_query": updatePreviewBtn,
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
  };
}

export default { render };
