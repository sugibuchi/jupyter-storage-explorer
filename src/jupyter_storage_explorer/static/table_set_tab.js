// Table Set Tab: the tables of a file or folder in a JupyterLab tab of its own
// ("View in a new tab"): a tree or tabs to choose one, and the data browser
// on it, as the preview panel shows them (createTableSetPanel in query.js).
// Joined after icons.js, common.js, query.js and sections.js (see _static.py).

function render({ model, el }) {
  const frame = createFrame(model, el, { className: "jse-table-set-view-tab jse-fill", bodyClass: "jse-table-set-view-tab-body", label: "_label" });
  let panel = null;

  function renderTables() {
    panel?.dispose();
    // The kernel's requests need no item path: the tab shows one item.
    panel = createTableSetPanel(frame, "", model.get("_tables"));
    frame.body.replaceChildren(panel.el);
  }

  const unbind = frame.bind({ "change:_tables": renderTables });
  renderTables();

  return () => {
    unbind();
    panel?.dispose();
  };
}

export default { render };
