// Data Explorer: the data browser ("Query data") for one dataset, on its own.
// Joined after common.js and query.js (see _static.py).

function render({ model, el }) {
  const title = h("span", { className: "jse-preview-name" });
  const badge = h("span", { className: "jse-badge" });
  const body = h("div", { className: "jse-dialog-body jse-data-explorer-body" });
  const statusEl = h("div", { className: "jse-status", hidden: true });
  const grip = h("div", { className: "jse-grip", title: "Drag to resize" });
  const { el: confirmEl, ask, answer } = createConfirm();
  const { request, onReply } = createRequester(model);

  el.classList.add("jse-widget", "jse-data-explorer");
  // Keep JupyterLab's notebook shortcuts (e.g. "dd" deletes a cell) from
  // firing while keys are pressed in the widget.
  el.dataset.lmSuppressShortcuts = "true";
  el.replaceChildren(h("div", { className: "jse-dialog-head" }, title, badge), body, statusEl, grip, confirmEl);

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
    title.textContent = title.title = model.get("title");
    badge.textContent = model.get("format");
  }

  function renderPanel() {
    panel?.dispose();
    panel = createQueryPanel({ request, ask, answer, flash }, "", model.get("query"));
    body.replaceChildren(panel.el);
  }

  // Height of the table area: the `height` trait until resized by dragging.
  function applyHeight() {
    body.style.height = model.get("height");
  }

  onDragY(grip, () => {
    const start = body.offsetHeight;
    return (dy) => (body.style.height = `${Math.max(80, start + dy)}px`);
  });

  const onCustomMsg = (msg) => msg.type === "reply" && onReply(msg);
  const handlers = {
    "change:title": renderHead,
    "change:format": renderHead,
    "change:query": renderPanel,
    "change:height": applyHeight,
    "msg:custom": onCustomMsg,
  };
  for (const [event, handler] of Object.entries(handlers)) model.on(event, handler);

  renderHead();
  applyHeight();
  renderPanel();

  return () => {
    for (const [event, handler] of Object.entries(handlers)) model.off(event, handler);
    clearTimeout(flashTimer);
    panel?.dispose();
  };
}

export default { render };
