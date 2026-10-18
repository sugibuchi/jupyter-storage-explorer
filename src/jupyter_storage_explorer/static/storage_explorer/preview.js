// The preview panel below the tree and list, showing the kernel's _preview:
// a file's sections (sections.js), or the data browser ("Query data",
// query.js). The Preview link at the right of the status bar opens it for
// the selected item (or the folder shown); the link or Esc closes it.

function createPreview(x) {
  const { model } = x;
  // A link, as JupyterLab's "Close All" in its running sessions panel: previews
  // the selected item, or closes the preview panel showing it (see updateButton).
  const button = h("button", { className: "jse-link", textContent: "Preview" });
  const head = h("div", { className: "jse-dialog-head" });
  const body = h("div", { className: "jse-dialog-body" });
  // On the panel's top edge: moves the boundary with the tree and list (see render()).
  const splitter = h("div", { className: "jse-splitter", title: "Drag to resize" });
  // tabIndex makes the panel focusable, so it receives Escape.
  const el = h("div", { className: "jse-preview-panel", tabIndex: -1, hidden: true }, splitter, head, body);
  let queryPanel = null; // the data browser shown in the panel

  // `format` (a format name) previews with that format instead of the best match.
  function open(path, format = null) {
    model.send({ type: "preview", path, format });
  }

  function close() {
    // The kernel owns the preview; clearing it closes the panel.
    model.set("_preview", {});
    model.save_changes();
  }

  function render() {
    const preview = model.get("_preview");
    if (!preview.query) {
      queryPanel?.dispose();
      queryPanel = null;
    }
    if (!preview.path) {
      el.hidden = true;
      return;
    }
    const opening = el.hidden || head.dataset.path !== preview.path;
    head.dataset.path = preview.path;
    head.replaceChildren(h("span", { className: "jse-preview-name", textContent: visible(preview.path), title: visible(preview.path) }));
    if (preview.format) head.append(h("span", { className: "jse-badge", textContent: x.formatLabel(preview.format) }));
    // The data browser, in a tab of its own (with the launcher's extension).
    if (preview.query && x.jupyterlab.canOpenQueryTab()) {
      const tabBtn = iconButton("open-in-new", "Open in a new tab");
      tabBtn.addEventListener("click", () => x.jupyterlab.openQueryTab(preview.path, preview.format));
      head.append(h("span", { className: "jse-spacer" }), tabBtn);
    }

    let children;
    if (preview.loading) {
      children = [h("div", { className: "jse-placeholder", textContent: "Loading…" })];
    } else if (preview.error) {
      children = [h("div", { className: "jse-preview-error", textContent: preview.error })];
    } else if (!preview.format) {
      children = [h("div", { className: "jse-placeholder", textContent: "No preview for this kind of item" })];
    } else if (preview.query) {
      queryPanel?.dispose();
      queryPanel = createQueryPanel({ request: x.request, ask: x.ask, answer: x.answer, flash: x.flash }, preview.path, preview.query);
      children = [queryPanel.el];
    } else {
      children = preview.sections.map(renderSection);
      if (preview.sections.some((s) => s.kind === "install")) {
        // After installing, this re-runs the preview with the same format.
        const again = h("button", { className: "jse-btn jse-primary", textContent: "Preview again" });
        again.addEventListener("click", () => open(preview.path, preview.format));
        children.push(again);
      }
    }
    body.replaceChildren(...children);
    el.hidden = false;
    if (opening) body.scrollTop = 0;
  }

  // What the Preview link previews, and in which format: the single
  // selected item, or with nothing selected, the current folder (e.g. one just
  // clicked in the tree). null when that cannot be previewed, or while the
  // kernel has not yet said what the newly selected item is.
  function target() {
    const selected = model.get("_selected");
    if (selected.length === 0) {
      const format = model.get("_current_format");
      return format ? { path: model.get("_current_dir"), format, query: model.get("_current_query") } : null;
    }
    const known = model.get("_selected_format");
    if (selected.length === 1 && known.path === selected[0] && known.format) return known;
    return null;
  }

  // The panel shows what the link would preview, or nothing else can be
  // previewed: the link closes it.
  function linkCloses() {
    const shown = model.get("_preview").path;
    if (shown == null) return false;
    const wanted = target();
    return wanted == null || wanted.path === shown;
  }

  function updateButton() {
    if (linkCloses()) {
      button.disabled = false;
      button.textContent = "Close preview";
      button.title = "Close the preview panel (Esc)";
      return;
    }
    const wanted = target();
    const selected = model.get("_selected").length;
    // Tabular data opens in the data browser when polars is installed.
    const action = wanted?.query ? "Query data" : "Preview";
    button.disabled = wanted == null;
    button.textContent = wanted ? `${action} (${x.formatLabel(wanted.format)})` : "Preview";
    button.title = wanted
      ? `${action}: ${selected === 0 ? "this folder" : "the selected item"} as ${x.formatLabel(wanted.format)}`
      : selected > 1
        ? "Select one item to preview"
        : "Nothing to preview here";
  }

  button.addEventListener("click", () => {
    if (linkCloses()) return close();
    const wanted = target();
    if (wanted != null) open(wanted.path, wanted.format);
  });

  return {
    el,
    button,
    splitter,
    open,
    close,
    render,
    updateButton,
    isOpen: () => !el.hidden,
    dispose: () => queryPanel?.dispose(),
  };
}
