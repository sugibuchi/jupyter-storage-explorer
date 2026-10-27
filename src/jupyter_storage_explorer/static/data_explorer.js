// Data Explorer: the data browser for one dataframe, on its own.
// Joined after icons.js, common.js, query.js and sections.js (see _static.py).

function render({ model, el }) {
  const grip = h("div", { className: "jse-grip", title: "Drag to resize" });
  const frame = createFrame(model, el, { className: "jse-data-explorer", bodyClass: "jse-data-explorer-body", label: "_library", after: [grip] });
  const { body } = frame;
  let panel = null;

  function renderPanel() {
    panel?.dispose();
    panel = createQueryPanel(frame, "", model.get("_query"));
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

  const unbind = frame.bind({
    "change:_query": renderPanel,
    "change:_height": applyHeight,
    // The kernel calls on_change's functions as it handles this answer, so
    // that an Output's with block shows what they display.
    "msg:custom": (msg) => msg.type === "callbacks" && model.send({ type: "callbacks", name: msg.name }),
  });
  applyHeight();
  renderPanel();

  return () => {
    unbind();
    panel?.dispose();
  };
}

export default { render };
