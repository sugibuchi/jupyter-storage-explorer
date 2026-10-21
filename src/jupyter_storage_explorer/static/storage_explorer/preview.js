// The preview panel below the tree and list, showing the kernel's _preview:
// the item's view (sections.js), or the data browser for data to query
// (query.js). The Preview button at the right of the status bar opens it for
// the selected item (or the folder shown); the button or Esc closes it.
// Without the panel, the button is View, which opens a new tab instead.

function createPreview(x) {
  const { model } = x;
  // A borderless button, an icon and a label: previews the selected item, or
  // closes the preview panel showing it (see updateButton).
  const label = h("span", { className: "jse-preview-label", textContent: "Preview" });
  const button = h("button", { className: "jse-btn jse-preview-btn" }, icon("eye"), label);
  const head = h("div", { className: "jse-dialog-head" });
  const body = h("div", { className: "jse-dialog-body" });
  // On the panel's top edge: moves the boundary with the tree and list (see render()).
  const splitter = h("div", { className: "jse-splitter", title: "Drag to resize" });
  // tabIndex makes the panel focusable, so it receives Escape.
  const el = h("div", { className: "jse-preview-panel", tabIndex: -1, hidden: true }, splitter, head, body);
  let queryPanel = null; // the data browser (or a table set's) shown in the panel

  // `format` (a format name) previews with that format instead of the best
  // match; `engine` (a key, or null for the built-in views) with that
  // engine instead of the one chosen ("Preview as").
  function open(path, format = null, engine = undefined) {
    model.send({ type: "preview", path, format, ...(engine === undefined ? {} : { engine }) });
  }

  // Without a preview panel (preview_panel="disabled"), the menus offer no
  // "Preview"; items are viewed in new tabs (view), and the button is View,
  // opening a tab of what Preview would preview (hidden without the
  // launcher's extension, which makes the tabs).
  const enabled = () => model.get("_preview_panel") !== "disabled";

  // Views the item where this explorer views items: in the panel, else in a
  // new tab (with the launcher's extension), else not at all.
  function view(path) {
    if (enabled()) open(path);
    else if (x.jupyterlab.canOpenViewTab()) void x.jupyterlab.openViewTab(path);
    else x.flash("This explorer has no preview panel");
  }

  function close() {
    // The kernel owns the preview; clearing it closes the panel.
    model.set("_preview", {});
    model.save_changes();
  }

  function render() {
    const preview = model.get("_preview");
    if (!preview.query && !preview.table_set) {
      queryPanel?.dispose();
      queryPanel = null;
    }
    if (!preview.path) {
      // Open with nothing in it (preview_panel="open"): clicking a file fills it.
      if (preview.empty) {
        delete head.dataset.path;
        head.replaceChildren(h("span", { className: "jse-preview-name", textContent: "Preview" }));
        body.replaceChildren(h("div", { className: "jse-placeholder", textContent: "Click a file to preview it" }));
      }
      el.hidden = !preview.empty;
      return;
    }
    const opening = el.hidden || head.dataset.path !== preview.path;
    head.dataset.path = preview.path;
    head.replaceChildren(h("span", { className: "jse-preview-name", textContent: visible(preview.path), title: visible(preview.path) }));
    // The format, and the engine viewing it (none for the built-in views).
    if (preview.format) {
      const badge = [x.formatLabel(preview.format), preview.engine_label].filter(Boolean).join(" · ");
      head.append(h("span", { className: "jse-badge", textContent: badge }));
    }
    // The same view in a tab of its own (with the launcher's extension).
    if (preview.format && !preview.loading && !preview.error && x.jupyterlab.canOpenViewTab()) {
      const tabBtn = iconButton("open-in-new", "View in a new tab");
      tabBtn.addEventListener("click", () => x.jupyterlab.openViewTab(preview.path, preview.format, preview.engine));
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
    } else if (preview.table_set) {
      // Several tables: a tree or tabs to choose one, and the data browser on it.
      queryPanel?.dispose();
      queryPanel = createTableSetPanel({ request: x.request, ask: x.ask, answer: x.answer, flash: x.flash }, preview.path, preview.table_set);
      children = [queryPanel.el];
    } else {
      children = preview.sections.map(renderSection);
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
      return format ? { path: model.get("_current_dir"), format } : null;
    }
    const known = model.get("_selected_format");
    if (selected.length === 1 && known.path === selected[0] && known.format) return known;
    return null;
  }

  // The panel shows what the link would preview, or nothing else can be
  // previewed: the link closes it.
  function linkCloses() {
    const preview = model.get("_preview");
    if (preview.path == null && !preview.empty) return false;
    const wanted = target();
    return wanted == null || wanted.path === preview.path;
  }

  // The icon: an eye to preview, a cross to close.
  function setButton(name, text) {
    button.firstChild.replaceWith(icon(name));
    label.textContent = text;
  }

  function updateButton() {
    const tabs = !enabled();
    button.hidden = tabs && !x.jupyterlab.canOpenViewTab();
    if (!tabs && linkCloses()) {
      button.disabled = false;
      setButton("close", "Close preview");
      button.title = "Close the preview panel (Esc)";
      return;
    }
    const wanted = target();
    const selected = model.get("_selected").length;
    const action = tabs ? "View" : "Preview";
    button.disabled = wanted == null;
    setButton(tabs ? "open-in-new" : "eye", wanted ? `${action} (${x.formatLabel(wanted.format)})` : action);
    button.title = wanted
      ? `${tabs ? "View in a new tab" : action}: ${selected === 0 ? "this folder" : "the selected item"} as ${x.formatLabel(wanted.format)}`
      : selected > 1
        ? `Select one item to ${action.toLowerCase()}`
        : `Nothing to ${action.toLowerCase()} here`;
  }

  button.addEventListener("click", () => {
    if (enabled() && linkCloses()) return close();
    const wanted = target();
    if (wanted == null) return;
    if (enabled()) open(wanted.path, wanted.format);
    else void x.jupyterlab.openViewTab(wanted.path, wanted.format);
  });

  return {
    el,
    button,
    splitter,
    open,
    view,
    enabled,
    close,
    render,
    updateButton,
    isOpen: () => !el.hidden,
    dispose: () => queryPanel?.dispose(),
  };
}
