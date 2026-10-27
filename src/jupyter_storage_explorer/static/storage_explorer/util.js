// Small helpers of the storage explorer: paths, sizes, times and wording.

const join = (parent, name) => (!parent || parent.endsWith("/") ? parent + name : `${parent}/${name}`);

// The last part of a path or URL, e.g. "b.csv" for "a/b.csv" (and "b" for "a/b/").
function basename(path) {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.slice(trimmed.lastIndexOf("/") + 1);
}

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

// Items of the list and the tree: {name, path, type, no_url, ...}.
const isFolder = (item) => item.type === "directory";
// Whether an item has a URL (see _url in the kernel): items without one are
// not treated as data (no preview or code) and are not copied.
const hasUrl = (item) => !item.no_url;

// What to view, as "preview" and "view_tab" messages give it: `path`, its
// `format` (null: the first it matches), `engine` (a key, null for the
// built-in views; left out: the one chosen) and `action` (a view's id; left
// out: the engine's first view).
const viewTarget = (path, format, engine, action) => ({ path, format, ...(engine === undefined ? {} : { engine }), ...(action ? { action } : {}) });

// A count of things, e.g. "1 file", "1,234 files".
const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

// "a.csv", "a.csv and b.csv", or "3 files: a.csv, b.csv, c.csv" (long lists shortened).
function describeFiles(names) {
  names = names.map(visible);
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  const shown = names.slice(0, 8).join(", ");
  return `${names.length} files: ${shown}${names.length > 8 ? `, and ${names.length - 8} more` : ""}`;
}

// A confirmation's lines: a question and a note under it, e.g. "Move
// a.csv?" and "To /data".
const question = (text, note) => [h("div", { textContent: visible(text) }), h("div", { className: "jse-note", textContent: visible(note) })];
