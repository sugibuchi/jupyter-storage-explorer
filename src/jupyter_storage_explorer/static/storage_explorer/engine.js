// The engine previews use: a button in the status bar, left of Preview,
// showing the one chosen (_engine, of the installed _engines); clicking it
// opens a menu of the engines, the one chosen checked.

function createEngine(x) {
  const { model } = x;
  const label = h("span", { className: "jse-engine-label" });
  const button = h("button", { className: "jse-btn jse-engine-btn" }, icon("memory"), label);

  function choose(key) {
    // The kernel remembers it, and previews again with it (_on_engine).
    model.set("_engine", key);
    model.save_changes();
  }

  function showMenu() {
    const chosen = model.get("_engine");
    const items = model.get("_engines").map((e) => ({
      label: e.label,
      icon: e.key === chosen ? "check" : undefined,
      action: () => choose(e.key),
    }));
    x.menu.showAbove(button, items);
  }

  button.addEventListener("click", () => {
    if (x.menu.isOpenFrom(button)) x.menu.hide();
    else showMenu();
  });

  // Hidden when no engine is installed: only the built-in views are left.
  function render() {
    const engine = model.get("_engines").find((e) => e.key === model.get("_engine"));
    button.hidden = !engine;
    label.textContent = engine ? engine.label : "";
    button.title = engine ? `Engine: ${engine.label}, the library previews use\nClick to choose another` : "";
  }

  return { button, render };
}
