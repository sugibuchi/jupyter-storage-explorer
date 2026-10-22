// Keyboard shortcuts in the file list, on the selected items, as the
// right-click menu's (item_menu.js, which shows them): Ctrl+C, Ctrl+X,
// Ctrl+V (into the folder shown), F2 (rename), Delete, Enter (opens, as a
// double-click); Cmd instead of Ctrl, and Cmd+Backspace for Delete, on macOS.
// Only while the list has the focus (a click in it): keys typed in the
// filter, a dialog, the tree or the preview panel are theirs. The
// operations check what they need themselves (unsafe mode for folders), as
// for the menu.

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

// How a shortcut (a key of SHORTCUTS) is written for the platform, e.g.
// "Ctrl+C" or "⌘C".
function keyLabel(shortcut) {
  const [mod, key] = shortcut.startsWith("mod+") ? [true, shortcut.slice(4)] : [false, shortcut];
  const name = key.length === 1 ? key.toUpperCase() : key === "Delete" && IS_MAC ? "⌘⌫" : key;
  if (!mod) return name;
  return IS_MAC ? `⌘${name}` : `Ctrl+${name}`;
}

function createShortcuts(x) {
  const { model } = x;
  const selected = () => x.list.entriesAt(model.get("_selected"));

  function copy(cut) {
    const targets = selected();
    if (!targets.length) return;
    if (!targets.every(hasUrl)) {
      x.flash(`Items without a URL cannot be ${cut ? "cut" : "copied"}`);
      return;
    }
    void x.clipboard.copyFiles(targets, cut);
  }

  function paste() {
    const item = x.clipboard.pasteItem(model.get("_current_dir"));
    if (item == null) x.flash(x.unsafe.refusal("paste folders"));
    else if (item.disabled) x.flash("Nothing to paste: copy or cut files first");
    else item.action();
  }

  // An action on the one selected item.
  function one(action) {
    const targets = selected();
    if (targets.length === 1) action(targets[0]);
    else if (targets.length > 1) x.flash("Select one item");
  }

  const SHORTCUTS = {
    "mod+c": () => copy(false),
    "mod+x": () => copy(true),
    "mod+v": paste,
    F2: () => one((target) => x.operations.rename(target)),
    Delete: () => {
      const targets = selected();
      if (targets.length) void x.operations.remove(targets);
    },
    Enter: () => one((target) => x.list.open(target)),
  };

  // The shortcut an event is, e.g. "mod+c", or null.
  function shortcutOf(ev) {
    if (ev.altKey || ev.shiftKey) return null;
    const mod = IS_MAC ? ev.metaKey : ev.ctrlKey;
    if ((IS_MAC ? ev.ctrlKey : ev.metaKey) || ev.isComposing) return null;
    if (mod && ev.key === "Backspace" && IS_MAC) return "Delete";
    const name = mod ? `mod+${ev.key.toLowerCase()}` : ev.key;
    return Object.hasOwn(SHORTCUTS, name) ? name : null;
  }

  function onKeyDown(ev) {
    // Keys typed in the list's filter or storage chooser are theirs.
    if (ev.target instanceof Element && ev.target.closest("input, textarea, select, [contenteditable]")) return;
    const shortcut = shortcutOf(ev);
    if (shortcut == null) return;
    ev.preventDefault();
    ev.stopPropagation();
    SHORTCUTS[shortcut]();
  }

  // The list's pane takes the focus when clicked (tabIndex), so its keys
  // reach it, and only while it has it.
  function attach(pane) {
    pane.tabIndex = -1;
    pane.addEventListener("keydown", onKeyDown);
  }

  return { attach };
}
