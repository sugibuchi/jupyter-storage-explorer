// View Tab: a view of a file or folder in a JupyterLab tab of its own ("View
// in a new tab"), rendered as the preview panel renders it (sections.js).
// Joined after icons.js, common.js, query.js and sections.js (see _static.py).

function render({ model, el }) {
  const title = h("span", { className: "jse-preview-name" });
  const badge = h("span", { className: "jse-badge" });
  const body = h("div", { className: "jse-dialog-body jse-view-tab-body" });
  const { request, onReply } = createRequester(model);

  el.classList.add("jse-widget", "jse-view-tab", "jse-fill");
  // Keep JupyterLab's shortcuts from firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  el.replaceChildren(h("div", { className: "jse-dialog-head" }, title, badge), body);

  // Lets Markdown views load the vendored libraries through this widget's kernel.
  fetchVendor = async (name) => {
    const reply = await request({ type: "vendor", name });
    if (reply.error) throw new Error(reply.error);
    return reply.source;
  };

  function renderHead() {
    title.textContent = title.title = visible(model.get("title"));
    badge.textContent = model.get("label");
  }

  // A prompt's answer goes to the kernel, which shows the view of it in the
  // tab, in a widget of its own.
  const actions = { answer: (content) => model.send({ type: "answer", ...content }), widgetManager: model.widget_manager };

  function renderView() {
    body.replaceChildren(renderSection(model.get("view"), actions));
  }

  const onCustomMsg = (msg) => msg.type === "reply" && onReply(msg);
  const handlers = {
    "change:title": renderHead,
    "change:label": renderHead,
    "change:view": renderView,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  renderHead();
  renderView();

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
  };
}

export default { render };
