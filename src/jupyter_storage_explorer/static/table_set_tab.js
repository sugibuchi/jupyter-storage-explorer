// Table Set Tab: the tables of a file or folder in a JupyterLab tab of its own
// ("View in a new tab"): a tree or tabs to choose one, and the data browser
// on it, as the preview panel shows them (createTableSetPanel in query.js).
// Joined after icons.js, common.js, query.js and sections.js (see _static.py).

function render({ model, el }) {
  const title = h("span", { className: "jse-preview-name" });
  const badge = h("span", { className: "jse-badge" });
  const body = h("div", { className: "jse-dialog-body jse-table-set-view-tab-body" });
  const statusEl = h("div", { className: "jse-status", hidden: true });
  const { el: confirmEl, ask, answer } = createConfirm();
  const { request, onReply } = createRequester(model);

  el.classList.add("jse-widget", "jse-table-set-view-tab", "jse-fill");
  // Keep JupyterLab's shortcuts from firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  el.replaceChildren(h("div", { className: "jse-dialog-head" }, title, badge), body, statusEl, confirmEl);

  let flashTimer;
  // A short message under the table, e.g. why a choice was not applied.
  function flash(message) {
    statusEl.textContent = message;
    statusEl.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => (statusEl.hidden = true), 2500);
  }

  let panel = null;

  function renderHead() {
    title.textContent = title.title = visible(model.get("title"));
    badge.textContent = model.get("label");
  }

  function renderTables() {
    panel?.dispose();
    // The kernel's requests need no item path: the tab shows one item.
    panel = createTableSetPanel({ request, ask, answer, flash }, "", model.get("tables"));
    body.replaceChildren(panel.el);
  }

  const onCustomMsg = (msg) => msg.type === "reply" && onReply(msg);
  const handlers = {
    "change:title": renderHead,
    "change:label": renderHead,
    "change:tables": renderTables,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  renderHead();
  renderTables();

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
    clearTimeout(flashTimer);
    panel?.dispose();
  };
}

export default { render };
