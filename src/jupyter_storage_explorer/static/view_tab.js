// View Tab: a view of a file or folder in a JupyterLab tab of its own ("View
// in a new tab"), rendered as the preview panel renders it (sections.js).
// Joined after icons.js, common.js, query.js and sections.js (see _static.py).

function render({ model, el }) {
  const frame = createFrame(model, el, { className: "jse-view-tab jse-fill", bodyClass: "jse-view-tab-body", label: "_label" });

  // Lets Markdown views load the vendored libraries through this widget's kernel.
  fetchVendor = vendorFetcher(frame.request);

  // A prompt's answer goes to the kernel, which shows the view of it in the
  // tab, in a widget of its own.
  const actions = { answer: (content) => model.send({ type: "answer", ...content }), widgetManager: model.widget_manager };

  function renderView() {
    frame.body.replaceChildren(renderSection(model.get("_view"), actions));
  }

  const unbind = frame.bind({ "change:_view": renderView });
  renderView();
  return unbind;
}

export default { render };
