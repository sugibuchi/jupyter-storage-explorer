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
  // Opens the bookmarks menu; filled (★) while the folder shown is bookmarked.
  const bookmarkBtn = h("button", { className: "jse-btn jse-bookmark-btn", title: "Bookmarks", textContent: "☆" });
  const pathEl = h("div", { className: "jse-path" });
  const treeEl = h("div", { className: "jse-tree" });
  const headRow = h("tr");
  const tbody = h("tbody");
  const listEl = h("div", { className: "jse-list" }, h("table", {}, h("thead", {}, headRow), tbody));
  const statusEl = h("div", { className: "jse-status" });
  // "Unsafe mode", at the right end of the toolbar (see takeUnsafe): a
  // slider. The checkbox is hidden but still focusable (Space toggles it);
  // the track and knob are drawn by CSS.
  const unsafeInput = h("input", { type: "checkbox", role: "switch", className: "jse-switch-input" });
  const unsafeLabel = h("span");
  const unsafeEl = h(
    "label",
    {
      className: "jse-unsafe",
      title:
        "For the next operation only: allows risky operations (moving, copying, pasting and deleting folders). " +
        "Turns off when any operation starts.",
    },
    unsafeInput,
    h("span", { className: "jse-switch", ariaHidden: "true" }),
    unsafeLabel,
  );
  // The status bar: messages on the left, Preview on the right.
  const statusBarEl = h("div", { className: "jse-status-bar" }, statusEl, previewBtn);
  // Tree and list; its height is the `height` trait until resized by dragging.
  // Above each pane, a bar: the filesystem chooser for the tree; for the list,
  // its filter and the pager (pages of PAGE_SIZE items; see renderList).
  const PAGE_SIZE = 100;
  let listPage = 0;
  // Set while typing in the list's filter: in large folders, the kernel is
  // then asked once typing pauses (see renderList).
  let filterTyped = false;
  const listFilter = createFilter({
    placeholder: "Filter by name",
    onChange() {
      listPage = 0;
      filterTyped = true;
      renderList();
    },
  });
  const prevPageBtn = h("button", { className: "jse-btn", title: "Previous page", textContent: "◀" });
  const nextPageBtn = h("button", { className: "jse-btn", title: "Next page", textContent: "▶" });
  const pageLabel = h("span", { className: "jse-page-label" });
  const pagerEl = h("div", { className: "jse-pager", hidden: true }, prevPageBtn, pageLabel, nextPageBtn);
  // Each pane is a column, its bar on top, so the bars follow the tree's width when it is resized.
  const panesEl = h(
    "div",
    { className: "jse-panes" },
    h("div", { className: "jse-pane jse-tree-pane" }, h("div", { className: "jse-pane-bar" }, fsSelect), treeEl),
    h("div", { className: "jse-pane jse-list-pane" }, h("div", { className: "jse-pane-bar" }, listFilter.el, pagerEl), listEl),
  );
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

  // Shown over the widget while a file operation waits for the kernel (see
  // busy()): it blocks clicks and keys from the start, and shows itself after
  // a moment (CSS), so quick operations do not flicker.
  const busyText = h("div", { className: "jse-busy-text" });
  const busyEl = h(
    "div",
    { className: "jse-dialog jse-busy", tabIndex: -1, hidden: true },
    h("div", { className: "jse-modal jse-busy-box" }, h("span", { className: "jse-spinner", ariaHidden: "true" }), busyText),
  );
  busyEl.setAttribute("role", "alertdialog");
  busyEl.setAttribute("aria-busy", "true");
  busyEl.addEventListener("keydown", (ev) => {
    ev.preventDefault(); // nothing else runs meanwhile, Esc included
    ev.stopPropagation();
  });

  // "jse-browser" is for user styles too, e.g. icons by [data-depth] (DEVELOPMENT.md).
  el.classList.add("jse-widget", "jse-browser");
  // Focusable, so Escape reaches the widget after a click anywhere in it.
  el.tabIndex = -1;
  // Keep JupyterLab's notebook shortcuts (e.g. "dd" deletes a cell) from
  // firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  // Jobs running in the kernel (moves, deletions, pastes, downloads), one row
  // each, above the status bar; see "Jobs" below.
  const jobsEl = h("div", { className: "jse-jobs", hidden: true });
  // The status bar belongs to the list, so it stays under it, above the
  // preview panel: Preview and the item count stay in view when the panel
  // opens.
  el.replaceChildren(
    h("div", { className: "jse-toolbar" }, bookmarkBtn, upBtn, refreshBtn, pathEl, unsafeEl),
    panesEl,
    jobsEl,
    statusBarEl,
    previewEl,
    grip,
    dialogEl,
    editorEl,
    confirmEl,
    menuEl,
    busyEl,
  );

  // --- Busy: file operations block the widget while the kernel works ---

  let busyCount = 0;

  function busyStart(text) {
    busyCount += 1;
    busyText.textContent = text;
    // Restart the delay of its appearance (see .jse-busy in the CSS).
    busyEl.hidden = true;
    void busyEl.offsetWidth;
    busyEl.hidden = false;
    busyEl.focus({ preventScroll: true });
  }

  function busyEnd() {
    busyCount = Math.max(0, busyCount - 1);
    if (!busyCount) busyEl.hidden = true;
  }

  // Runs `work` (async) with the widget blocked, showing `text`; returns its result.
  async function busy(text, work) {
    busyStart(text);
    try {
      return await work();
    } finally {
      busyEnd();
    }
  }

  // --- Jobs: moves, deletions, pastes and downloads run in the kernel's
  // background (jobs.py). A request starting one is answered {"job": id};
  // the kernel then sends {"type": "job", id, state, counts...} as it runs,
  // and its result when it ends. The widget stays usable meanwhile ---

  // id -> {row, parts, waiters}; finished jobs' last messages are kept briefly
  // in `ended`, in case one ends before its request's reply is handled.
  const jobs = new Map();
  const ended = new Map();
  const FINAL_STATES = new Set(["done", "failed", "cancelled"]);

  function jobRow(id) {
    const title = h("span", { className: "jse-job-title" });
    const cancel = h("button", { className: "jse-btn jse-job-cancel", textContent: "Cancel", title: "Stop after the file being worked on" });
    cancel.addEventListener("click", () => {
      cancel.disabled = true;
      model.send({ type: "job_cancel", id });
    });
    const fill = h("div", { className: "jse-job-fill" });
    const bar = h("div", { className: "jse-job-bar" }, fill);
    const detail = h("span", { className: "jse-job-detail" });
    const row = h("div", { className: "jse-job" }, h("div", { className: "jse-job-head" }, title, detail, cancel), bar);
    return { row, parts: { title, detail, cancel, bar, fill }, waiters: [] };
  }

  // e.g. "12 / 340 files · 45 MB / 1.2 GB · a.csv"; "Counting files…".
  function jobDetail(job) {
    if (job.cancelling) return "Cancelling…";
    if (job.state === "queued") return "Waiting…";
    if (!job.files_total) return "Counting files…";
    const parts = [`${job.files_done.toLocaleString()} / ${job.files_total.toLocaleString()} files`];
    if (job.bytes_total) parts.push(`${formatSize(job.bytes_done)} / ${formatSize(job.bytes_total)}`);
    if (job.current) parts.push(job.current);
    return parts.join(" · ");
  }

  function onJob(job) {
    // Counting files for "Properties": shown in its dialog, not above the status bar.
    const counting = job.kind === "properties";
    if (counting && scanning?.id === job.id && !FINAL_STATES.has(job.state)) scanning.show(job);
    let entry = jobs.get(job.id);
    if (FINAL_STATES.has(job.state)) {
      entry?.row.remove();
      jobs.delete(job.id);
      jobsEl.hidden = jobs.size === 0;
      if (entry) entry.waiters.forEach((resolve) => resolve(job));
      else {
        ended.set(job.id, job);
        setTimeout(() => ended.delete(job.id), 60_000);
      }
      return;
    }
    if (!entry) {
      entry = jobRow(job.id);
      jobs.set(job.id, entry);
    }
    if (counting) return;
    if (!entry.row.isConnected) {
      jobsEl.append(entry.row);
      jobsEl.hidden = false;
    }
    const { title, detail, cancel, bar, fill } = entry.parts;
    title.textContent = title.title = job.title;
    detail.textContent = detail.title = jobDetail(job);
    cancel.disabled = cancel.disabled || job.cancelling;
    // By bytes when known, else by files; unknown yet: an indeterminate bar.
    const fraction = job.bytes_total ? job.bytes_done / job.bytes_total : job.files_total ? job.files_done / job.files_total : null;
    bar.classList.toggle("jse-indeterminate", fraction == null);
    fill.style.width = fraction == null ? "" : `${Math.min(100, fraction * 100).toFixed(1)}%`;
  }

  // The result of a request that may have started a job: for {"job": id},
  // waits for it to end and returns its result with "state" and "error";
  // other replies (e.g. {"conflicts": [...]}) as they are.
  function jobResult(reply) {
    if (!reply.job) return Promise.resolve(reply);
    const asResult = (job) => ({ ...(job.result ?? {}), state: job.state, error: job.error });
    const done = ended.get(reply.job);
    if (done) return Promise.resolve(asResult(done));
    return new Promise((resolve) => {
      let entry = jobs.get(reply.job);
      if (!entry) {
        // Its first message has not arrived yet.
        entry = jobRow(reply.job);
        jobs.set(reply.job, entry);
      }
      entry.waiters.push((job) => resolve(asResult(job)));
    });
  }

  // The end of a job's message, after `parts` (e.g. ["Pasted a.csv"]): why it
  // failed, or that it was cancelled ("Paste cancelled" with nothing done,
  // what = "Paste") and the item it left incomplete (e.g. a folder partly
  // copied).
  function jobOutcome(result, parts, what) {
    if (result.state === "failed") return [`Failed: ${result.error}`];
    if (!(result.cancelled || result.state === "cancelled")) return [];
    const out = [parts.length ? "cancelled" : `${what} cancelled`];
    if (result.incomplete) out.push(`${result.incomplete} left incomplete`);
    return out;
  }

  // --- "Unsafe mode": while on, risky operations are offered (today:
  // moving, copying, pasting and deleting folders). Any operation turns it
  // off as it starts, risky or not, so it allows one operation at a time. The
  // kernel refuses folders unless the request says it was on ("unsafe") ---

  const unsafe = () => model.get("_unsafe_mode");

  function renderUnsafe() {
    const on = unsafe();
    unsafeInput.checked = on;
    unsafeEl.classList.toggle("jse-on", on);
    unsafeLabel.textContent = on ? "Unsafe mode on" : "Unsafe mode";
  }

  unsafeInput.addEventListener("change", () => {
    model.set("_unsafe_mode", unsafeInput.checked);
    model.save_changes();
  });

  // Whether the switch is on for an operation starting now; turns it off.
  function takeUnsafe() {
    const on = unsafe();
    if (on) {
      model.set("_unsafe_mode", false);
      model.save_changes();
    }
    return on;
  }

  const isFolder = (item) => item.type === "directory";

  // --- Right-click menu ---

  let flashTimer;
  // A short message in the status bar, in place of the item count.
  function flash(message) {
    statusEl.textContent = message;
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

  // The button that opened the menu, if one did: pressing it again is left
  // to its click handler, which closes the menu, rather than closing it here
  // for the click to open it again.
  let menuOwner = null;

  function onOutsidePointer(ev) {
    if (!menuEl.contains(ev.target) && !menuOwner?.contains(ev.target)) hideMenu();
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
  // `title`: the row's tooltip. `menu()`: the items of the menu right-clicking
  // the row opens in place of this one.
  function menuRows(items) {
    return items.map((item) => {
      if (item === "-") return h("div", { className: "jse-menu-sep" });
      const row = h(
        "div",
        { className: "jse-menu-item" + (item.disabled ? " jse-disabled" : ""), hidden: Boolean(item.hidden), title: item.title ?? "" },
        h("span", { textContent: item.label }),
      );
      item.ref?.(row);
      if (item.menu) row.addEventListener("contextmenu", (ev) => showMenu(ev, item.menu()));
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

  // Where the open menu was opened (client coordinates).
  let menuAt = { x: 0, y: 0 };

  function showMenu(ev, items) {
    ev.preventDefault();
    ev.stopPropagation(); // keep JupyterLab's own context menu from opening
    menuEl.replaceChildren(...menuRows(items));
    menuEl.hidden = false;
    menuOwner = null;
    menuAt = { x: ev.clientX, y: ev.clientY };
    placeMenu();
    document.addEventListener("pointerdown", onOutsidePointer, true);
    document.addEventListener("keydown", onMenuKey, true);
  }

  // Places the menu at the pointer, kept inside the widget (which clips what
  // is outside it). Called again when rows appear later ("Preview as", "Edit").
  function placeMenu() {
    const box = el.getBoundingClientRect();
    const x = Math.min(menuAt.x - box.left, box.width - menuEl.offsetWidth - 4);
    const y = Math.min(menuAt.y - box.top, box.height - menuEl.offsetHeight - 4);
    menuEl.style.left = `${Math.max(0, x)}px`;
    menuEl.style.top = `${Math.max(0, y)}px`;
    // Open submenus to the left when there is no room on the right.
    menuEl.classList.toggle("jse-flip", Math.max(0, x) + 2 * menuEl.offsetWidth > box.width);
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
    else if (msg.type === "reply") onReply(msg);
    else if (msg.type === "job") onJob(msg);
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

  // `result`: a job's result, for its "cancelled" or failure (see jobOutcome).
  function uploadSummary(copied, skipped, errors, result = {}) {
    const parts = [];
    if (copied.length) parts.push(`Uploaded ${copied.length === 1 ? copied[0] : `${copied.length} items`}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    parts.push(...jobOutcome(result, parts, "Upload"));
    flash(parts.join("; ") || "Nothing uploaded");
  }

  // From JupyterLab's file browser: the kernel copies the files (and, in
  // unsafe mode, folders) itself, as a job.
  async function confirmUpload(paths, dest) {
    const folders = takeUnsafe();
    const root = serverRoot();
    if (root == null) {
      flash("Cannot upload: JupyterLab did not say where its files are");
      return;
    }
    const names = paths.map((p) => p.slice(p.lastIndexOf("/") + 1));
    if (!(await askUpload(names, dest))) return;
    const content = { type: "upload", root, paths, dest, unsafe: folders };
    const text = `Uploading ${describeFiles(names)}…`;
    let reply = await busy(text, () => request({ ...content, if_exists: "ask" }));
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        flash("Upload cancelled");
        return;
      }
      reply = await busy(text, () => request({ ...content, if_exists: choice }));
    }
    const result = await jobResult(reply);
    uploadSummary(result.copied ?? [], result.skipped ?? [], result.errors ?? [], result);
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
    takeUnsafe(); // an operation, though not on folders
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
      const names = files.map((f) => f.name);
      const { conflicts = [] } = await busy("Checking…", () => request({ type: "upload_check", dest, names }));
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
      // Blocked while the pieces are sent; the busy dialog shows the progress.
      // After a file's last piece, the kernel copies it to the storage as a
      // job, which goes on in the background once all pieces are sent.
      const jobs = [];
      await busy("Uploading…", async () => {
        for (const [i, file] of toSend.entries()) {
          const id = `${Date.now()}-${i}`;
          let offset = 0;
          do {
            busyText.textContent = `Uploading ${file.name}: ${file.size ? Math.floor((100 * offset) / file.size) : 0}%`;
            const piece = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
            offset += piece.byteLength;
            const last = offset >= file.size;
            const reply = await request({ type: "upload_chunk", id, dest, name: file.name, last }, [piece]);
            if (reply.error) {
              errors.push(reply.error);
              break;
            }
            if (last) jobs.push(jobResult(reply));
          } while (offset < file.size);
        }
      });
      for (const result of await Promise.all(jobs)) {
        copied.push(...(result.copied ?? []));
        errors.push(...(result.errors ?? []));
        if (result.state === "failed") errors.push(result.error);
        else if (result.state === "cancelled") errors.push("cancelled");
      }
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

  // --- Move: drag files (and, in unsafe mode, folders) in the list onto a folder (list or tree) ---

  // Our own drag data type, so moves are told apart from uploads:
  // {paths, folders: whether unsafe mode was on when the drag started}.
  const MOVE_MIME = "application/x-jse-move";
  const isMoveDrag = (ev) => Array.from(ev.dataTransfer?.types ?? []).includes(MOVE_MIME);

  // Entries a drag starting on `entry` moves: the selected ones if it is
  // selected, else just it. Folders only with `folders` (unsafe mode).
  function draggedItems(entry, folders) {
    const allowed = (e) => folders || !isFolder(e);
    if (!allowed(entry)) return [];
    const selected = model.get("_selected");
    if (!selected.includes(entry.path)) return [entry];
    return entriesAt(selected).filter(allowed);
  }

  // A list row's drag: a move within the explorer, and for files a download
  // onto JupyterLab's file browser. Starting a drag is an operation (see takeUnsafe).
  function startDrag(ev, entry) {
    const folders = takeUnsafe();
    const items = draggedItems(entry, folders);    if (!items.length) {
      ev.preventDefault(); // a folder, locked
      flash("Turn on unsafe mode to move folders");
      return;
    }
    ev.dataTransfer.setData(MOVE_MIME, JSON.stringify({ paths: items.map((e) => e.path), folders }));
    const files = items.filter((e) => !isFolder(e)).map((e) => e.path);
    if (files.length) startDownloadDrag(ev, files);
    ev.dataTransfer.effectAllowed = "copyMove";
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
    if (!node) return;
    const { paths, folders } = JSON.parse(ev.dataTransfer.getData(MOVE_MIME));
    confirmMove(paths, node.dataset.dropDir, folders);
  });
  panesEl.addEventListener("dragend", () => highlightDrop(null));

  // --- Download: drag files onto JupyterLab's file browser ---
  // The launcher's JupyterLab extension (jupyter-storage-explorer-launcher)
  // handles drops of this type on the file browser: it asks the user, then
  // downloads with the drag's `download` from the page-wide registry, as drag
  // data can only be text. Without the extension, such drops do nothing.
  const DOWNLOAD_MIME = "application/x-jupyter-storage-explorer-download";
  const DRAG_REGISTRY = Symbol.for("jupyter-storage-explorer.drag");

  // Adds the download to a drag of `paths` starting in the list.
  function startDownloadDrag(ev, paths) {
    const names = paths.map((p) => p.slice(p.lastIndexOf("/") + 1));
    ev.dataTransfer.setData(DOWNLOAD_MIME, JSON.stringify(names));
    const drag = {
      names,
      // `dest`: a folder relative to the Jupyter server's, as JupyterLab names
      // it. Resolves with the kernel's reply: {conflicts} if files exist there
      // and `ifExists` is "ask", else, once the download (a job) has ended,
      // {copied, skipped, errors} (file names; a cancel or failure is an error).
      async download(dest, ifExists = "ask") {
        const root = serverRoot();
        if (root == null) return { errors: ["JupyterLab did not say where its files are"] };
        const reply = await busy(`Downloading ${describeFiles(names)} to JupyterLab…`, () =>
          request({ type: "download_to_server", paths, root, dest, if_exists: ifExists }),
        );
        const result = await jobResult(reply);
        const outcome = jobOutcome(result, result.copied ?? [], "Download");
        return { ...result, errors: [...(result.errors ?? []), ...outcome] };
      },
    };
    // Replaced by the next drag; the extension only reads it on a drop of this type.
    globalThis[DRAG_REGISTRY] = drag;
  }

  // `folders`: whether unsafe mode was on when the drag started.
  async function confirmMove(paths, dest, folders = false) {
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
    const content = { type: "move", paths: toMove, dest, unsafe: folders };
    const text = `Moving ${describeFiles(names)}…`;
    let reply = await busy(text, () => request({ ...content, if_exists: "ask" }));
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        flash("Move cancelled");
        return;
      }
      reply = await busy(text, () => request({ ...content, if_exists: choice }));
    }
    const result = await jobResult(reply);
    const { moved = [], skipped = [], errors = [] } = result;
    const parts = [];
    if (moved.length) parts.push(`Moved ${moved.length === 1 ? moved[0] : `${moved.length} items`}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    parts.push(...jobOutcome(result, parts, "Move"));
    flash(parts.join("; ") || "Nothing moved");
  }

  // --- Delete: files (and, in unsafe mode, folders) chosen with "Delete" in the right-click menu ---

  // targets: [{path, type}].
  async function confirmDelete(targets) {
    const folders = takeUnsafe();
    if (targets.some(isFolder) && !folders) {
      flash("Turn on unsafe mode to delete folders");
      return;
    }
    const paths = targets.map((t) => t.path);
    const names = paths.map((p) => p.slice(p.lastIndexOf("/") + 1));
    const note = targets.some(isFolder)
      ? "Folders are deleted with everything in them. This cannot be undone."
      : "This cannot be undone.";
    const ok = await ask(
      [h("div", { textContent: `Delete ${describeFiles(names)}?` }), h("div", { className: "jse-note", textContent: note })],
      [
        { label: "Cancel", value: null },
        { label: "Delete", value: true, primary: true },
      ],
    );
    if (!ok) return;
    const reply = await busy(`Deleting ${describeFiles(names)}…`, () => request({ type: "delete", paths, unsafe: folders }));
    const result = await jobResult(reply);
    const { deleted = [], errors = [] } = result;
    const parts = [];
    if (deleted.length) parts.push(`Deleted ${deleted.length === 1 ? deleted[0] : `${deleted.length} items`}`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    parts.push(...jobOutcome(result, parts, "Delete"));
    flash(parts.join("; ") || "Nothing deleted");
  }

  // --- Copy, cut and paste: "Copy" (or "Cut") puts files (and, in unsafe
  // mode, folders) on a clipboard shared by the explorers on the page (and
  // their URLs on the system clipboard); "Paste" copies (or moves) them into a
  // folder, of any explorer and storage ---

  const CLIPBOARD = Symbol.for("jupyter-storage-explorer.clipboard");
  // Dispatched on globalThis once files cut in an explorer were pasted in
  // another, which may be in another kernel: {explorer, filesystem, paths} of
  // the files cut; that explorer then asks its kernel to show what is left.
  const CHANGED_EVENT = "jupyter-storage-explorer:changed";

  // Whether an item of the list or the tree has a URL (see _url in the kernel).
  const hasUrl = (item) => !item.no_url;

  // The URLs of items ({path}), from the kernel: the listing does not carry them.
  async function urlsOf(items) {
    const { urls } = await request({ type: "urls", paths: items.map((t) => t.path) });
    return urls;
  }

  // targets: [{path, type}] of the filesystem shown, all with URLs. `cut`:
  // pasting moves them.
  async function copyFiles(targets, cut = false) {
    const hasFolders = targets.some(isFolder);
    if (!takeUnsafe() && hasFolders) {
      flash(`Turn on unsafe mode to ${cut ? "cut" : "copy"} folders`);
      return;
    }
    const urls = await urlsOf(targets);
    globalThis[CLIPBOARD] = {
      // Pasted in an explorer of the same kernel, they are read with this
      // explorer's filesystem; otherwise from their URLs.
      explorer: model.get("_explorer_id"),
      filesystem: model.get("_filesystem"),
      cut,
      // Pasting folders needs unsafe mode again.
      folders: hasFolders,
      files: targets.map(({ path }, i) => {
        const url = urls[i];
        return { path, url, name: url.slice(url.replace(/\/$/, "").lastIndexOf("/") + 1) };
      }),
    };
    const what = `${cut ? "Cut" : "Copied"} ${targets.length === 1 ? globalThis[CLIPBOARD].files[0].name : `${targets.length} items`}`;
    try {
      await navigator.clipboard.writeText(urls.join("\n"));
      flash(what);
    } catch {
      // Paste still works; only the URLs are not on the system clipboard.
      flash(`${what} (the browser denied clipboard access for the URLs)`);
    }
  }

  // The "Paste" item for folder `dest` ("Move here" after "Cut"): greyed out
  // when nothing was copied, and null (left out) when folders were copied and
  // unsafe mode is off.
  function pasteItem(dest) {
    const clip = globalThis[CLIPBOARD];
    if (!clip?.files.length) return { label: "Paste", disabled: true };
    if (clip.folders && !unsafe()) return null;
    const what = clip.files.length === 1 ? clip.files[0].name : `${clip.files.length} items`;
    return { label: clip.cut ? `Move ${what} here` : `Paste ${what}`, action: () => confirmPaste(clip, dest) };
  }

  async function confirmPaste(clip, dest) {
    const folders = takeUnsafe();
    const [Verb, verb, noun] = clip.cut ? ["Move", "move", "Move"] : ["Paste", "paste", "Paste"];
    if (clip.folders && !folders) {
      flash(`Turn on unsafe mode to ${verb} folders`);
      return;
    }
    const names = clip.files.map((f) => f.name);
    const ok = await ask(
      [h("div", { textContent: `${Verb} ${describeFiles(names)}?` }), h("div", { className: "jse-note", textContent: `Into ${dest}` })],
      [
        { label: "Cancel", value: null },
        { label: Verb, value: true, primary: true },
      ],
    );
    if (!ok) return;
    const content = { type: "paste", explorer: clip.explorer, filesystem: clip.filesystem, files: clip.files, dest, unsafe: folders, cut: clip.cut };
    const text = `${clip.cut ? "Moving" : "Pasting"} ${describeFiles(names)}…`;
    let reply = await busy(text, () => request({ ...content, if_exists: "ask" }));
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        flash(`${noun} cancelled`);
        return;
      }
      reply = await busy(text, () => request({ ...content, if_exists: choice }));
    }
    const result = await jobResult(reply);
    if (clip.cut) cutPasted(clip, result);
    const { skipped = [], errors = [] } = result;
    const done = (clip.cut ? result.moved : result.pasted) ?? [];
    const parts = [];
    if (done.length) parts.push(`${clip.cut ? "Moved" : "Pasted"} ${done.length === 1 ? done[0] : `${done.length} items`}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    parts.push(...jobOutcome(result, parts, noun));
    flash(parts.join("; ") || `Nothing ${clip.cut ? "moved" : "pasted"}`);
  }

  // After pasting files cut: they are no longer where they were cut, so the
  // clipboard is emptied once some have moved; and the explorer they were cut
  // in is told (this one's kernel has already shown its own changes).
  function cutPasted(clip, result) {
    if (result.moved?.length && globalThis[CLIPBOARD] === clip) globalThis[CLIPBOARD] = null;
    if (clip.explorer === model.get("_explorer_id")) return;
    const detail = { explorer: clip.explorer, filesystem: clip.filesystem, paths: clip.files.map((f) => f.path) };
    globalThis.dispatchEvent(new CustomEvent(CHANGED_EVENT, { detail }));
  }

  // Files cut in this explorer were pasted in another: show what is left.
  function onChanged(ev) {
    const { explorer, filesystem, paths } = ev.detail ?? {};
    if (explorer === model.get("_explorer_id")) model.send({ type: "changed", filesystem, paths });
  }
  globalThis.addEventListener(CHANGED_EVENT, onChanged);

  // --- Create a folder: "Create a folder" in the right-click menu ---

  // Why `name` cannot name a new folder, or null: the kernel's checks
  // (_folder_name_error in storage_explorer.py), answered before sending anything.
  function folderNameError(name) {
    if (!name.trim()) return "Enter a name";
    if (name !== name.trim()) return "No spaces at the start or the end";
    if (name === "." || name === "..") return `"${name}" is not a folder name`;
    if (/[\\/]/.test(name)) return "A name, without / or \\";
    if (/[\x00-\x1f\x7f]/.test(name)) return "No control characters";
    if (name.length > 255) return "At most 255 characters";
    return null;
  }

  // Asks for the new folder's name (a name, not a path) and creates it in
  // folder `dest`. A name that cannot be used is explained in the dialog,
  // which stays open until a folder is created or it is cancelled.
  async function createFolder(dest) {
    takeUnsafe(); // an operation, though not a risky one
    const input = h("input", { type: "text", className: "jse-name-input", placeholder: "Folder name", spellcheck: false });
    const problem = h("div", { className: "jse-note jse-error-text" });
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      answer(true);
    });
    for (;;) {
      const asked = ask(
        [h("div", { textContent: "Create a folder" }), h("div", { className: "jse-note", textContent: `In ${dest}` }), input, problem],
        [
          { label: "Cancel", value: null },
          { label: "Create", value: true, primary: true },
        ],
      );
      input.focus();
      input.select();
      if (!(await asked)) return;
      const name = input.value;
      const error = folderNameError(name);
      if (error) {
        problem.textContent = error;
        continue;
      }
      const reply = await busy(`Creating ${name}…`, () => request({ type: "create_folder", dest, name }));
      if (reply.error) {
        problem.textContent = reply.error; // e.g. "x already exists" (the name as it is)
        continue;
      }
      flash(
        reply.hidden
          ? `Created ${name}: it shows once a file is put in it (this storage has no empty folders)`
          : `Created ${name}`,
      );
      return;
    }
  }

  // --- Properties: "Properties" in the right-click menu. A file's are read
  // at once; otherwise the kernel counts the files and folders in a job
  // (properties.py), while a dialog blocks the widget, showing how far it has
  // got, with Cancel. Not an operation: unsafe mode stays as it is ---

  // The job counting for the dialog: {id, show(job)}, while it runs.
  let scanning = null;

  // A table of [label, value] rows; a value is text or an element.
  function propertyTable(rows) {
    const cell = (value) => (value instanceof Node ? value : cellText(value));
    return h(
      "table",
      { className: "jse-props" },
      h("tbody", {}, ...rows.map(([label, value]) => h("tr", {}, h("th", { textContent: label }), h("td", {}, cell(value))))),
    );
  }

  // E.g. "1.2 MB (1,234,567 bytes)".
  function sizeText(bytes) {
    if (bytes == null) return "";
    return bytes < 1024 ? `${bytes.toLocaleString()} B` : `${formatSize(bytes)} (${bytes.toLocaleString()} bytes)`;
  }

  // A time with the file it is of below, e.g. for the oldest file.
  function stampText(stamp) {
    if (!stamp) return "No modification times";
    return h("div", {}, h("div", { textContent: formatTime(stamp.mtime) }), h("div", { className: "jse-note", textContent: stamp.path }));
  }

  // targets: [{path, type}].
  async function showProperties(targets) {
    const paths = targets.map((t) => t.path);
    const name = (p) => p.slice(p.lastIndexOf("/") + 1) || rootLabel(p);
    const what = paths.length === 1 ? name(paths[0]) : `${paths.length} items`;
    const reply = await busy(`Reading the properties of ${what}…`, () => request({ type: "properties", paths }));
    if (reply.error) {
      flash(`Properties: ${reply.error}`);
      return;
    }
    if (reply.file) {
      showFileProperties(reply.file);
      return;
    }
    const result = await followCount(reply, what);
    if (result) showTotals(what, result);
  }

  function showFileProperties(file) {
    const rows = [
      ["Name", file.name],
      ["Path", file.path],
      ...(file.url ? [["URL", file.url]] : []),
      ["Size", sizeText(file.size)],
      ["Modified", formatTime(file.mtime)],
    ];
    // Everything the filesystem's info() gave, as it gave it.
    const info = Object.entries(file.info).map(([key, value]) => [key, value]);
    showDialog(`Properties of ${file.name}`, null, [
      propertyTable(rows),
      h("div", { className: "jse-section-title jse-props-title", textContent: "From the storage" }),
      propertyTable(info),
    ]);
  }

  // Waits for the counting job of `reply`, showing its progress in a dialog
  // until it ends or the user cancels; its result (partial if cancelled), or
  // null if it failed.
  async function followCount(reply, what) {
    const detail = h("div", { className: "jse-note", textContent: "Starting…" });
    scanning = {
      id: reply.job,
      show: (job) => {
        const parts = [`${job.files_done.toLocaleString()} files`, formatSize(job.bytes_done)];
        if (job.current) parts.push(job.current);
        detail.textContent = job.cancelling ? "Cancelling…" : job.state === "queued" ? "Waiting…" : parts.join(" · ");
      },
    };
    const ended = jobResult(reply);
    const asked = ask([h("div", { textContent: `Counting the files of ${what}…` }), detail], [{ label: "Cancel", value: "cancel" }]);
    // Cancel, Esc and clicks outside cancel; the end of the job closes the dialog.
    const first = await Promise.race([ended.then(() => "ended"), asked]);
    let result;
    if (first === "ended") {
      answer("ended");
      result = await ended;
    } else {
      model.send({ type: "job_cancel", id: reply.job });
      result = await busy("Cancelling…", () => ended);
    }
    scanning = null;
    if (result.state === "failed") {
      flash(`Properties: ${result.error}`);
      return null;
    }
    return result;
  }

  function showTotals(what, result) {
    const children = [];
    if (result.cancelled) children.push(h("div", { className: "jse-note", textContent: "Cancelled: the counts are of what was found before." }));
    children.push(
      propertyTable([
        ["Files", result.files.toLocaleString()],
        ["Folders", result.folders.toLocaleString()],
        ["Total size", sizeText(result.bytes)],
        ["Oldest file", stampText(result.oldest)],
        ["Newest file", stampText(result.newest)],
      ]),
    );
    if (result.errors.length) {
      const count = result.errors.length;
      children.push(
        h("div", { className: "jse-section-title jse-error-text jse-props-title", textContent: `Not counted: ${count} item${count > 1 ? "s" : ""} that could not be read` }),
        h("pre", { className: "jse-text", textContent: result.errors.join("\n") }),
      );
    }
    showDialog(`Properties of ${what}`, null, children);
  }

  // Right-clicking empty space in the list: paste into, or create a folder in, the folder shown.
  listEl.addEventListener("contextmenu", (ev) => {
    if (ev.target instanceof Element && ev.target.closest("tbody tr")) return; // a row's own menu
    const dest = model.get("_current_dir");
    showMenu(ev, [
      // Folders on the clipboard while locked: a greyed-out "Paste".
      pasteItem(dest) ?? { label: "Paste", disabled: true },
      { label: "Create a folder", action: () => createFolder(dest) },
    ]);
  });

  // --- Download to local: the kernel sends each file's bytes; the browser saves them ---

  // Files requested but not received yet, and the errors so far.
  const downloads = { pending: 0, done: 0, errors: [] };

  function download(paths) {
    takeUnsafe(); // an operation, though not on folders
    downloads.pending += paths.length;
    // Blocked until the last file arrives (onDownload); the kernel sends one message per file.
    busyStart(`Downloading ${paths.length === 1 ? "1 file" : `${paths.length} files`} to local…`);
    model.send({ type: "download", paths });
  }

  function onDownload(msg, buffers) {
    downloads.pending -= 1;
    if (downloads.pending <= 0) busyEnd();
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
    const summary = done ? `Downloaded ${done === 1 ? "1 file" : `${done} files`} to local` : "";
    flash([summary, ...errors.map((e) => `Failed: ${e}`)].filter(Boolean).join("; "));
    Object.assign(downloads, { done: 0, errors: [] });
  }

  // --- Download to JupyterLab: the kernel copies the files into its folder
  // download_to_jupyterlab_path (on the Jupyter server's machine) ---

  async function downloadToJupyterLab(paths) {
    takeUnsafe(); // an operation, though not on folders
    const dest = model.get("_download_to_jupyterlab_path");
    const names = paths.map((p) => p.slice(p.lastIndexOf("/") + 1));
    const confirmed = await ask(
      [h("div", { textContent: `Download ${describeFiles(names)} to JupyterLab?` }), h("div", { className: "jse-note", textContent: `To ${dest}` })],
      [
        { label: "Cancel", value: null },
        { label: "Download", value: true, primary: true },
      ],
    );
    if (!confirmed) return;
    const text = `Downloading ${describeFiles(names)} to JupyterLab…`;
    let reply = await busy(text, () => request({ type: "download_to_jupyterlab", paths, if_exists: "ask" }));
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        flash("Download cancelled");
        return;
      }
      reply = await busy(text, () => request({ type: "download_to_jupyterlab", paths, if_exists: choice }));
    }
    const result = await jobResult(reply);
    const { copied = [], skipped = [], errors = [] } = result;
    const parts = [];
    if (copied.length) parts.push(`Downloaded ${describeFiles(copied)} to ${dest}`);
    if (skipped.length) parts.push(`skipped ${skipped.length} existing`);
    parts.push(...errors.map((e) => `Failed: ${e}`));
    parts.push(...jobOutcome(result, parts, "Download"));
    flash(parts.join("; ") || "Nothing downloaded");
  }

  // --- Bookmarks: folders, kept by the kernel (its ExplorerStates, shared
  // with other explorers); the list is asked for each time the menu opens ---

  // [{filesystem, path, url, label}] as last received: for the button's star
  // and the folders' "Add/Remove bookmark".
  let bookmarks = [];

  function setBookmarks(reply) {
    if (reply.error) {
      flash(reply.error);
      return;
    }
    bookmarks = reply.bookmarks;
    renderBookmarkBtn();
  }

  async function fetchBookmarks() {
    setBookmarks(await request({ type: "bookmarks" }));
  }

  function isBookmarked(path, filesystem = model.get("_filesystem")) {
    return bookmarks.some((b) => b.filesystem === filesystem && b.path === path);
  }

  function renderBookmarkBtn() {
    const marked = isBookmarked(model.get("_current_dir"));
    bookmarkBtn.textContent = marked ? "★" : "☆";
    bookmarkBtn.classList.toggle("jse-on", marked);
  }

  async function addBookmark(path) {
    setBookmarks(await request({ type: "bookmark_add", path }));
  }

  async function removeBookmark(bookmark) {
    setBookmarks(await request({ type: "bookmark_remove", filesystem: bookmark.filesystem, path: bookmark.path }));
  }

  async function openBookmark(bookmark) {
    const reply = await request({ type: "bookmark_open", filesystem: bookmark.filesystem, path: bookmark.path });
    if (reply.error) flash(`Cannot open the bookmark: ${reply.error}`);
  }

  // Add or remove the bookmark of folder `path` of the storage shown.
  function bookmarkItem(path) {
    const filesystem = model.get("_filesystem");
    return isBookmarked(path)
      ? { label: "Remove bookmark", action: () => removeBookmark({ filesystem, path }) }
      : { label: "Add bookmark", action: () => addBookmark(path) };
  }

  // The bookmarks menu, below the button: bookmarking the folder shown, then
  // the bookmarks ("[storage] path", in the kernel's order); right-click one
  // for "Copy URL" and "Delete bookmark".
  async function showBookmarks() {
    await fetchBookmarks();
    const current = model.get("_current_dir");
    const label = isBookmarked(current) ? "Remove this folder's bookmark" : "Bookmark this folder";
    const items = [{ ...bookmarkItem(current), label }, "-"];
    if (!bookmarks.length) items.push({ label: "No bookmarks", disabled: true });
    for (const b of bookmarks) {
      items.push({
        label: b.label,
        title: b.url ?? b.path,
        action: () => openBookmark(b),
        menu: () => [
          { label: "Copy URL", disabled: !b.url, action: () => copy([b.url], "URL") },
          { label: "Delete bookmark", action: () => removeBookmark(b) },
        ],
      });
    }
    const box = bookmarkBtn.getBoundingClientRect();
    const at = { clientX: box.left, clientY: box.bottom, preventDefault() {}, stopPropagation() {} };
    showMenu(at, items);
    menuOwner = bookmarkBtn;
  }

  // The button closes its menu if open (see onOutsidePointer).
  bookmarkBtn.addEventListener("click", () => {
    if (!menuEl.hidden && menuOwner === bookmarkBtn) hideMenu();
    else void showBookmarks();
  });

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
    if (!menuEl.hidden) placeMenu(); // rows shown above may have pushed it out of the widget
  }

  // Menu items for one or more items ({path, type, no_url}). The tree passes
  // withOpen = false: clicking a tree folder already opens it.
  function itemMenu(targets, withOpen = true) {
    const single = targets.length === 1 ? targets[0] : null;
    const count = targets.length > 1 ? `${targets.length} ` : "";
    // Items without a URL (the kernel's _url gave None) are not treated as data:
    // no preview, code or editing.
    const data = single && hasUrl(single) ? single : null;
    // The reply arrives after the menu is built, so the refs below are set by then.
    const info = data ? requestMenuInfo(data.path) : null;
    const folder = single?.type === "directory" ? single : null;
    const files = !targets.some(isFolder);
    // Folder operations are dangerous: offered only in unsafe mode.
    const allowed = files || unsafe();
    const what = files ? "files" : "items";
    const withUrls = targets.every(hasUrl);

    // Groups of items, joined by separators; groups left empty are dropped.
    const open = [
      {
        label: "Preview",
        disabled: !data,
        // Relabelled "Query data" when the kernel says it opens in the data browser.
        ref: (row) => info && (info.previewRow = row),
        action: () => openPreview(single.path),
      },
    ];
    if (info) {
      open.push({
        label: "Preview as",
        hidden: true,
        ref: (row) => (info.previewAsRow = row),
        submenu: (sub) => (info.previewAsSub = sub),
      });
    }
    if (withOpen && folder) open.push({ label: "Open", action: () => navigate(folder.path) });
    if (info) {
      open.push({ label: "Edit", hidden: true, ref: (row) => (info.editRow = row), action: () => openEditor(single.path) });
    }
    open.push({
      label: "Python code",
      disabled: !data,
      submenu: (sub) => {
        sub.replaceChildren(...menuRows([{ label: "Loading…", disabled: true }]));
        info.codeSub = sub;
      },
    });
    // Locations are copied only as URLs: fsspec's paths can differ from the
    // storage's own notion of a path (e.g. abfs's "container/key"). Files'
    // URLs also come with "Copy" below, so "Copy URL" is for folders, which
    // "Copy" leaves to unsafe mode.
    if (withUrls && !files) {
      open.push({
        label: `Copy ${count}URL${count ? "s" : ""}`,
        action: async () => copy(await urlsOf(targets), count ? `${count}URLs` : "URL"),
      });
    }

    // "Copy" and "Cut" copy for "Paste" (and put the URLs on the clipboard).
    const clipboard = [];
    if (withUrls && allowed) {
      clipboard.push({ label: count ? `Copy ${count}${what}` : "Copy", action: () => copyFiles(targets) });
      if (!targets.some((t) => t.path === model.get("_root"))) {
        clipboard.push({ label: count ? `Cut ${count}${what}` : "Cut", action: () => copyFiles(targets, true) });
      }
    }
    const paste = folder && pasteItem(folder.path);
    if (paste) clipboard.push(paste);

    const change = [];
    if (folder) change.push({ label: "Create a folder", action: () => createFolder(folder.path) });
    if (allowed) change.push({ label: count ? `Delete ${count}${what}` : "Delete", action: () => confirmDelete(targets) });

    // Files only: downloading folders is intentionally not supported. The
    // kernel refuses files the explorer's policy does not let go there.
    const downloads = [];
    if (files) {
      const paths = targets.map((t) => t.path);
      downloads.push(
        { label: count ? `Download ${count}files to local` : "Download to local", action: () => download(paths) },
        { label: count ? `Download ${count}files to JupyterLab` : "Download to JupyterLab", action: () => downloadToJupyterLab(paths) },
      );
    }

    const about = [{ label: "Properties", action: () => showProperties(targets) }];
    if (folder) about.push(bookmarkItem(folder.path));

    return [open, clipboard, change, downloads, about]
      .filter((group) => group.length)
      .flatMap((group, i) => (i ? ["-", ...group] : group));
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

  // At most this many subfolders of a folder below the root are shown in the
  // tree, so that opening a folder of thousands does not draw them all.
  const TREE_FOLDERS = 100;

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
      if (isOpen && children) {
        const shown = shownChildren(children, depth);
        for (const child of shown) wrap.append(node(child, depth + 1));
        const more = children.length - shown.length;
        if (more) {
          const note = h("div", {
            className: "jse-node jse-tree-more",
            textContent: `plus ${more.toLocaleString()} folder${more === 1 ? "" : "s"}`,
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
    treeEl.replaceChildren(node({ name: treeRootLabel(root), path: root, no_url: true }, 0));
    treeEl.querySelector(".jse-active")?.scrollIntoView({ block: "nearest" });
  }

  // A root of just "/" (e.g. memory://, or a DirFileSystem's "") does not tell
  // filesystems apart, so with several, the tree names the one shown too:
  // "/ [Scratch (memory)]".
  function treeRootLabel(root) {
    const label = rootLabel(root);
    if (label !== "/" || model.get("_filesystem_names").length < 2) return label;
    return `${label} [${model.get("_filesystem")}]`;
  }

  function renderPath() {
    const chain = ancestors(model.get("_current_dir"));
    // In a span of its own, left to right: pathEl is right to left, so that a
    // path too long is cut at its start, and the current folder stays in view.
    const crumbs = h("span", { className: "jse-crumbs" });
    chain.forEach((path, i) => {
      if (i > 0) crumbs.append(h("span", { className: "jse-sep", textContent: "/" }));
      const name = i === 0 ? rootLabel(path) : path.slice(path.lastIndexOf("/") + 1);
      const crumb = h("span", { className: "jse-crumb", textContent: name, title: path });
      crumb.addEventListener("click", () => navigate(path));
      crumbs.append(crumb);
    });
    pathEl.replaceChildren(crumbs);
    upBtn.disabled = chain.length < 2;
  }

  // Names with numbers in order ("2" before "10"), ignoring case and accents.
  // One collator for all comparisons: localeCompare with options sets one up
  // for each call, which made sorting a large folder by name slow.
  const nameOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

  function compare(a, b) {
    const aDir = a.type === "directory";
    if (aDir !== (b.type === "directory")) return aDir ? -1 : 1;
    const r = sort.key === "name" ? nameOrder.compare(a.name, b.name) : (a[sort.key] ?? -Infinity) - (b[sort.key] ?? -Infinity);
    return sort.asc ? r : -r;
  }

  // Items, {name, path, type, size, mtime, format, no_url}, from the kernel's
  // columns (see _make_listing).
  function decodeColumns(l) {
    const noUrl = new Set(l.no_url ?? []);
    return (l.names ?? []).map((name, i) => ({
      name,
      path: l.paths ? l.paths[i] : join(l.dir, name),
      type: l.is_dir[i] ? "directory" : "file",
      size: l.sizes[i],
      mtime: l.mtimes[i],
      format: l.formats[l.format[i]],
      no_url: noUrl.has(i),
    }));
  }

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

  // --- Large folders: filtered, sorted and paged by the kernel ---
  // For folders of more than the explorer's max_browser_items, the kernel only
  // sends their size (_listing.query) and pages come from "list" requests.
  // Replies are kept until the listing changes, and the next page is fetched
  // ahead. While an answer for a new filter is awaited, the rows shown are
  // filtered here, so typing shows its effect at once.
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

  function kernelQuery(page = listPage) {
    const l = model.get("_listing");
    const filter = listFilter.query();
    return {
      dir: l.dir,
      version: l.version,
      text: filter?.text ?? "",
      regex: filter?.regex ?? false,
      sort: sort.key,
      asc: sort.asc,
      page,
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
    if (key === JSON.stringify(kernelQuery())) renderList();
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
      if (reply.filter_error) listFilter.invalid(reply.filter_error);
      if ((reply.page + 1) * PAGE_SIZE < reply.matching) fetchPage(kernelQuery(reply.page + 1));
      return { entries: reply.entries, matching: reply.matching, page: reply.page, loading: false };
    }
    if (filterTyped) filterTimer = setTimeout(() => fetchPage(kernelQuery()), 200);
    else fetchPage(query);
    const shown = state.shown;
    return {
      entries: shown ? shown.entries.filter((e) => listFilter.test(e.name)) : [],
      matching: shown?.matching ?? 0,
      page: listPage,
      loading: true,
    };
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
      const [entry] = entriesAt(next);
      if (entry && entry.type !== "directory" && hasUrl(entry)) openPreview(next[0]);
    }
  }

  // The folder whose items the list last showed, to tell when another's arrive.
  let listShowsDir = null;

  function renderList() {
    // Another folder's items are shown unfiltered, from the first page. Done
    // when they arrive, not on clicking the folder: the previous folder's
    // items would show unfiltered until then, a long wait for a large folder.
    const dir = model.get("_listing").dir;
    if (dir !== listShowsDir) {
      listShowsDir = dir;
      listPage = 0;
      listFilter.clear(false);
    }
    headRow.replaceChildren(
      ...columns.map((col) => {
        const arrow = sort.key === col.key ? (sort.asc ? " ▲" : " ▼") : "";
        const th = h("th", { className: `jse-col-${col.key}`, textContent: col.label + arrow });
        th.addEventListener("click", () => {
          sort.asc = sort.key === col.key ? !sort.asc : true;
          sort.key = col.key;
          listPage = 0;
          renderList();
        });
        return th;
      }),
    );

    const selected = new Set(model.get("_selected"));
    // Filtered by name, then cut into pages. The selection keeps items filtered
    // out or on other pages, and right-click actions apply to them too.
    let page, matching, total, loading;
    if (kernelMode()) {
      const shown = kernelPage();
      ({ entries: page, matching, loading } = shown);
      listPage = shown.page;
      total = model.get("_listing").total;
    } else {
      const entries = sortedEntries();
      const filtered = listFilter.active() ? entries.filter((e) => listFilter.test(e.name)) : entries;
      matching = filtered.length;
      total = entries.length;
      listPage = Math.min(listPage, Math.max(1, Math.ceil(matching / PAGE_SIZE)) - 1);
      page = filtered.slice(listPage * PAGE_SIZE, (listPage + 1) * PAGE_SIZE);
      loading = false;
    }
    filterTyped = false;
    const pages = Math.max(1, Math.ceil(matching / PAGE_SIZE));
    const first = listPage * PAGE_SIZE;
    pagerEl.hidden = pages < 2;
    pageLabel.textContent = `${(first + 1).toLocaleString()}–${(first + page.length).toLocaleString()} of ${matching.toLocaleString()}`;
    pageLabel.title = kernelMode() ? "A large folder: filtered, sorted and paged by the kernel" : "";
    prevPageBtn.disabled = listPage === 0;
    nextPageBtn.disabled = listPage >= pages - 1;
    tbody.replaceChildren(
      ...page.map((entry) => {
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
        } else if (entry.format) {
          // e.g. "csv", "json-lines"; lets CSS style the icon per format.
          tr.dataset.fileFormat = entry.format;
        }
        // Files (and, in unsafe mode, folders) can be dragged onto a folder to move
        // them there; files onto JupyterLab's file browser to download them to
        // the Jupyter server (see startDrag).
        tr.draggable = true;
        tr.addEventListener("dragstart", (ev) => startDrag(ev, entry));
        tr.addEventListener("click", (ev) => select(entry.path, ev.ctrlKey || ev.metaKey));
        tr.addEventListener("dblclick", () => {
          if (isDir) navigate(entry.path);
          else if (hasUrl(entry)) openPreview(entry.path); // no URL: no preview
        });
        tr.addEventListener("contextmenu", (ev) => {
          // Like file managers: right-clicking outside the selection selects that item.
          let paths = model.get("_selected");
          if (!paths.includes(entry.path)) {
            select(entry.path, false);
            paths = [entry.path];
          }
          showMenu(ev, itemMenu(entriesAt(paths)));
        });
        return tr;
      }),
    );
    if (!page.length && total) {
      const text = loading ? "Loading…" : "No items match the filter";
      tbody.append(h("tr", {}, h("td", { className: "jse-placeholder", colSpan: columns.length, textContent: text })));
    }
    updatePreviewBtn();
    renderStatus();
  }

  function showPage(delta) {
    listPage += delta;
    renderList();
    listEl.scrollTop = 0;
  }

  prevPageBtn.addEventListener("click", () => showPage(-1));
  nextPageBtn.addEventListener("click", () => showPage(1));

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
    if (error) {
      statusEl.textContent = error;
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
      matches = () => entries.filter((e) => listFilter.test(e.name)).length;
    }
    const count = `${total.toLocaleString()} item${total === 1 ? "" : "s"}`;
    const sel = model.get("_selected").length;
    const matching = listFilter.active() ? `${matches().toLocaleString()} of ${count} match` : count;
    statusEl.textContent = matching + (sel ? `, ${sel} selected` : "");
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
    takeUnsafe(); // an operation, though not on folders
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
    if (opening) previewBody.scrollTop = 0;
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
    renderBookmarkBtn();
    reportView();
  }

  // Tells whoever contains the explorer which storage and folder it shows:
  // the launcher's tab keeps them, to reopen there (its index.ts). Elsewhere,
  // e.g. in a notebook, nobody listens.
  function reportView() {
    const detail = { filesystem: model.get("_filesystem"), folder: model.get("_current_dir") };
    el.dispatchEvent(new CustomEvent("jupyter-storage-explorer:view", { bubbles: true, detail }));
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
    renderBookmarkBtn(); // the folder's path may be the same as on the storage left
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
    "change:_listing": renderList,
    "change:_selected": renderList,
    "change:_error": renderStatus,
    "change:_height": applyHeight,
    "change:_preview": renderPreview,
    "change:_current_format": updatePreviewBtn,
    "change:_selected_format": updatePreviewBtn,
    "change:_current_query": updatePreviewBtn,
    "change:_unsafe_mode": renderUnsafe,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  applyHeight();
  renderFsSelect();
  renderUnsafe();
  onDirChange();
  renderList();
  renderPreview();
  void fetchBookmarks(); // for the star

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
    globalThis.removeEventListener(CHANGED_EVENT, onChanged);
    hideMenu();
    clearTimeout(flashTimer);
    queryPanel?.dispose();
  };
}

export default { render };
