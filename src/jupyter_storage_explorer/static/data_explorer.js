// Data Explorer: the data browser for one dataframe, on its own.
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
    title.textContent = title.title = model.get("_title");
    badge.textContent = model.get("_library");
  }

  function renderPanel() {
    panel?.dispose();
    panel = createQueryPanel({ request, ask, answer, flash }, "", model.get("_query"));
    body.replaceChildren(panel.el);
  }

  // Height of the table area: the `_height` trait until resized by dragging;
  // "fill": the widget fills its container (see "jse-fill" in the CSS).
  function applyHeight() {
    const height = model.get("_height");
    el.classList.toggle("jse-fill", height === "fill");
    body.style.height = height === "fill" ? "" : height;
  }

  onDragY(grip, () => {
    const start = body.offsetHeight;
    return (dy) => (body.style.height = `${Math.max(80, start + dy)}px`);
  });

  function onCustomMsg(msg) {
    if (msg.type === "reply") onReply(msg);
    // The kernel calls on_change's functions as it handles this answer, so
    // that an Output's with block shows what they display.
    else if (msg.type === "callbacks") model.send({ type: "callbacks", name: msg.name });
  }
  const handlers = {
    "change:_title": renderHead,
    "change:_library": renderHead,
    "change:_query": renderPanel,
    "change:_height": applyHeight,
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
