// Preview sections: one renderer per Preview kind of formats/base.py, and the
// code blocks of "Python code".

function renderTable(section) {
  const head = h("tr", {}, ...section.columns.map((c) => h("th", { textContent: c })));
  const thead = h("thead", {}, head);
  if (section.dtypes) {
    thead.append(h("tr", { className: "jse-dtypes" }, ...section.dtypes.map((t) => h("th", { textContent: t }))));
  }
  const body = section.rows.map((row) =>
    h("tr", {}, ...row.map((v) => h("td", { textContent: v == null ? "null" : cellText(v), className: v == null ? "jse-null" : "" }))),
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
  return h("details", { open: depth < 2 }, h("summary", { textContent: summary }), ...entries.map(([k, v]) => renderJson(v, k, depth + 1)));
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
    ...section.options.map((option, i) => codeBlock(several ? `Option ${i + 1}: ${option.packages}` : option.packages, option.command)),
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
  text: (s) => (s.html ? h("pre", { className: "jse-text jse-highlight", innerHTML: s.html }) : h("pre", { className: "jse-text", textContent: s.text })),
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
  return [codeBlock("1. Set up", recipe.install, "Not done in this kernel yet: run this once in a cell first."), codeBlock("2. Load", recipe.code)];
}
