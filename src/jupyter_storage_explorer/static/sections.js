// Views' sections: one renderer per View kind of formats/view.py (all but the
// data browser's QueryView), for the preview panel and view tabs, and the code
// blocks of "Python code".

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

// --- Jupyter widgets (JupyterWidgetView): the widget's own view, made by the
// page's widget manager from its model, as a notebook's output would be. The
// manager is anywidget's model.widget_manager, beyond the model's documented
// API: where it cannot make views, the widget is not shown. The kernel closes
// the widget with the view, which removes this view of it. ---

function renderWidget(section, actions) {
  const box = h("div", { className: "jse-jupyter-widget", textContent: "Loading the widget…" });
  const manager = actions.widgetManager;
  if (typeof manager?.create_view !== "function") {
    box.replaceChildren(errorBlock("This page cannot show Jupyter widgets in the explorer."));
    return box;
  }
  (async () => {
    const view = await manager.create_view(await manager.get_model(section.model_id));
    box.replaceChildren(view.el);
    // Widgets that size or draw themselves once on the page, e.g. charts.
    view.trigger?.("displayed");
  })().catch((err) => box.replaceChildren(errorBlock(`Cannot show the widget: ${err.message ?? err}`)));
  return box;
}

// --- Markdown: rendered with marked, sanitized with DOMPurify ---
// Both are vendored in static/vendor. An anywidget module cannot import files
// next to it, so the kernel sends their source, imported once per page.

// Set by each widget's render(): asks its kernel for a vendored library's source.
let fetchVendor = null;

// The fetchVendor of a widget whose requests go through `request`
// (createRequester): "vendor", answered by _static.vendor_source.
function vendorFetcher(request) {
  return async (name) => {
    const reply = await request({ type: "vendor", name });
    if (reply.error) throw new Error(reply.error);
    return reply.source;
  };
}
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

// Beyond DOMPurify's defaults (no scripts, event handlers, frames, links to
// javascript: etc.): no CSS, as a <style> element applies to all of
// JupyterLab's page and inline styles can cover it (e.g. a fake prompt), and
// no forms, which could send what users type elsewhere. Markdown needs none.
const PURIFY_OPTIONS = {
  FORBID_TAGS: ["style", "form", "input", "button", "select", "option", "textarea"],
  FORBID_ATTR: ["style"],
};

function renderMarkdown(section) {
  // jp-RenderedHTMLCommon gives it JupyterLab's own Markdown styling.
  const box = h("div", { className: "jp-RenderedHTMLCommon jse-markdown", textContent: "Rendering…" });
  loadMarkdownLibs()
    .then(({ marked, DOMPurify }) => {
      // Sanitizing removes scripts, event handlers, CSS etc. the file may contain.
      box.innerHTML = DOMPurify.sanitize(marked.parse(section.text, { async: false }), PURIFY_OPTIONS);
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

// --- Prompts before a view (ViewWithPrompt): a confirmation, a choice, a
// text to enter. actions.answer({prompt, value}) or ({prompt, cancel: true})
// sends the user's answer to the kernel, which then shows the view; the
// buttons are disabled once one is clicked. ---

function renderPrompt(section, actions) {
  const box = h("div", { className: "jse-prompt" }, h("div", { className: "jse-prompt-message", textContent: visible(section.message) }));
  const buttons = h("div", { className: "jse-prompt-buttons" });
  const send = (content) => {
    for (const btn of buttons.querySelectorAll("button")) btn.disabled = true;
    actions.answer?.({ prompt: section.prompt, ...content });
  };
  const button = (label, primary, onClick) => {
    const btn = h("button", { className: "jse-btn" + (primary ? " jse-primary" : ""), textContent: label });
    btn.addEventListener("click", onClick);
    return btn;
  };
  let value = () => undefined; // a confirmation answers nothing
  const chosen = section.default ?? section.choices?.[0];
  if (section.kind === "choice" && section.style === "radio") {
    const name = `jse-prompt-${section.prompt}`;
    const radios = section.choices.map((label) => h("input", { type: "radio", name, value: label, checked: label === chosen }));
    box.append(h("div", { className: "jse-prompt-choices" }, ...radios.map((radio) => h("label", {}, radio, ` ${radio.value}`))));
    value = () => radios.find((radio) => radio.checked)?.value;
  } else if (section.kind === "choice" && section.style === "dropdown") {
    const select = h(
      "select",
      { className: "jse-prompt-select" },
      ...section.choices.map((label) => h("option", { value: label, textContent: label, selected: label === chosen })),
    );
    box.append(select);
    value = () => select.value;
  } else if (section.kind === "input") {
    const input = h("input", { type: "text", className: "jse-prompt-input", value: section.value, placeholder: section.placeholder, spellcheck: false });
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" || ev.isComposing) return;
      ev.preventDefault();
      send({ value: input.value });
    });
    box.append(input);
    value = () => input.value;
  }
  // A choice has Cancel only if asked (with_cancel).
  if (section.kind !== "choice" || section.with_cancel) buttons.append(button("Cancel", false, () => send({ cancel: true })));
  if (section.kind === "choice" && section.style === "button") {
    // A button of each label, which answers at once.
    for (const label of section.choices) buttons.append(button(label, label === chosen, () => send({ value: label })));
  } else {
    buttons.append(button(section.button, true, () => send({ value: value() })));
  }
  box.append(buttons);
  return box;
}

// What shows instead of a view: that it loads or was not viewed (with a
// button to preview it again, in the preview panel), or why it failed.
function renderNotice(section, actions) {
  const box = h("div", { className: "jse-notice", textContent: section.text });
  if (section.again && actions.again) {
    const again = h("button", { className: "jse-btn jse-primary", textContent: "Preview again" });
    again.addEventListener("click", () => actions.again());
    box.append(h("div", { className: "jse-prompt-buttons" }, again));
  }
  return box;
}

const sectionRenderers = {
  markdown: renderMarkdown,
  table: renderTable,
  // Highlighted HTML comes from Pygments in the kernel, which escapes the text.
  text: (s) => (s.html ? h("pre", { className: "jse-text jse-highlight", innerHTML: s.html }) : h("pre", { className: "jse-text", textContent: s.text })),
  tree: (s) => h("div", { className: "jse-json" }, renderJson(s.value, null, 0)),
  media: renderMedia,
  widget: renderWidget,
  confirmation: renderPrompt,
  choice: renderPrompt,
  input: renderPrompt,
  notice: renderNotice,
  error: (s) => errorBlock(s.text),
};

// `actions`: what prompts and notices do (see renderPrompt, renderNotice), and
// the widget manager rendering Jupyter widgets (renderWidget).
function renderSection(section, actions = {}) {
  // The kind class lets the preview panel stretch tables, text etc. to its height.
  const box = h("div", { className: `jse-section jse-section-${section.kind}` });
  if (section.title) box.append(h("div", { className: "jse-section-title", textContent: section.title }));
  const renderer = sectionRenderers[section.kind];
  box.append(renderer ? renderer(section, actions) : h("div", { textContent: `Unknown view: ${section.kind}` }));
  if (section.note) box.append(h("div", { className: "jse-note", textContent: section.note }));
  return box;
}

// A titled code block with a Copy button.
function codeBlock(title, code) {
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
    h("pre", { className: "jse-code", textContent: code }),
  );
}

// Body of the "Python code" dialog for one recipe: the code, and the packages
// it needs (installing them is left to the user); or why its code failed.
function recipeBlocks(recipe) {
  if (recipe.error) return [errorBlock(recipe.error)];
  const blocks = [codeBlock(recipe.title, recipe.code)];
  if (recipe.packages.length) {
    blocks.push(h("div", { className: "jse-note", textContent: `Needs ${recipe.packages.join(", ")}` }));
  }
  return blocks;
}
