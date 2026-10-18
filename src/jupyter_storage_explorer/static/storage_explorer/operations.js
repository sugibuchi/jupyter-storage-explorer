// File operations within the storage: move, delete, rename and create a
// folder; and the clipboard: copy (or cut) and paste, also between storages
// and explorers. Each operation starts by taking unsafe mode (see
// createUnsafe), which folders need.

// Why `name` cannot name a new folder or a renamed item, or null: the
// kernel's checks (name_error in _paths.py), answered before sending anything.
function nameError(name) {
  if (!name.trim()) return "Enter a name";
  if (name !== name.trim()) return "No spaces at the start or the end";
  if (name === "." || name === "..") return `"${name}" is not a name`;
  if (/[\\/]/.test(name)) return "A name, without / or \\";
  if (/[\x00-\x1f\x7f]/.test(name)) return "No control characters";
  if (name.length > 255) return "At most 255 characters";
  return null;
}

function createOperations(x) {
  const { request, ask, answer } = x;

  // Resolves with "overwrite", "skip", or null (cancel).
  function askConflicts(conflicts, dest) {
    return ask(question(`${describeFiles(conflicts)} already ${conflicts.length === 1 ? "exists" : "exist"}.`, `In ${dest}`), [
      { label: "Cancel", value: null },
      { label: "Skip existing", value: "skip" },
      { label: "Overwrite", value: "overwrite", primary: true },
    ]);
  }

  // An operation the kernel runs as a job, once the user confirms it (`lines`,
  // and the `button` to press): sends `content`, showing `text` while the
  // widget waits, and if files exist where they go (the reply's "conflicts",
  // in folder `dest`), sends it again with the user's choice of overwriting or
  // skipping them. Resolves with the job's result (see createJobs), or null if
  // the user cancelled ("<noun> cancelled" when asked about the files).
  async function run({ lines, button, text, content, dest, noun }) {
    if (!(await ask(lines, confirmButtons(button)))) return null;
    let reply = await x.busy.run(text, () => request({ ...content, if_exists: "ask" }));
    if (reply.conflicts) {
      const choice = await askConflicts(reply.conflicts, dest);
      if (!choice) {
        x.flash(`${noun} cancelled`);
        return null;
      }
      reply = await x.busy.run(text, () => request({ ...content, if_exists: choice }));
    }
    return x.jobs.result(reply);
  }

  // Moves `paths` into folder `dest`: files (and folders) dragged onto a
  // folder. `folders`: whether unsafe mode was on when the drag started.
  async function move(paths, dest, folders = false) {
    const parentOf = (p) => p.slice(0, p.lastIndexOf("/"));
    const toMove = paths.filter((p) => p !== dest && parentOf(p) !== dest.replace(/\/$/, ""));
    if (!toMove.length) {
      x.flash("Already in that folder");
      return;
    }
    const names = toMove.map(basename);
    const result = await run({
      lines: question(`Move ${describeFiles(names)}?`, `To ${dest}`),
      button: "Move",
      text: `Moving ${describeFiles(names)}…`,
      content: { type: "move", paths: toMove, dest, unsafe: folders },
      dest,
      noun: "Move",
    });
    if (result) x.flash(resultMessage(result, { verb: "Moved", noun: "Move", done: result.moved }));
  }

  // Deletes `targets` ([{path, type}]), files (and, in unsafe mode, folders).
  async function remove(targets) {
    const folders = x.unsafe.take();
    if (targets.some(isFolder) && !folders) {
      x.flash("Turn on unsafe mode to delete folders");
      return;
    }
    const paths = targets.map((t) => t.path);
    const names = paths.map(basename);
    const note = targets.some(isFolder) ? "Folders are deleted with everything in them. This cannot be undone." : "This cannot be undone.";
    const result = await run({
      lines: question(`Delete ${describeFiles(names)}?`, note),
      button: "Delete",
      text: `Deleting ${describeFiles(names)}…`,
      content: { type: "delete", paths, unsafe: folders },
      noun: "Delete",
    });
    if (result) x.flash(resultMessage(result, { verb: "Deleted", noun: "Delete", done: result.deleted }));
  }

  // Asks for a name (not a path) in a dialog of `lines` above the field,
  // which stays open, explaining what is wrong, until `submit(name)` takes
  // the name (resolving with null; else with why not), or it is cancelled.
  // `value`: the name to start with, of which the first `selected`
  // characters are selected.
  async function askName({ lines, button, placeholder = "", value = "", selected = value.length, submit }) {
    const input = h("input", { type: "text", className: "jse-name-input", placeholder, value, spellcheck: false });
    const problem = h("div", { className: "jse-note jse-error-text" });
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      answer(true);
    });
    for (let first = true; ; first = false) {
      const asked = ask([...lines, input, problem], confirmButtons(button));
      input.focus();
      if (first) input.setSelectionRange(0, selected);
      else input.select();
      if (!(await asked)) return;
      const name = input.value;
      const error = nameError(name) ?? (await submit(name));
      if (!error) return;
      problem.textContent = error;
    }
  }

  // Asks for the new folder's name and creates it in folder `dest`.
  async function createFolder(dest) {
    x.unsafe.take(); // an operation, though not a risky one
    await askName({
      lines: question("Create a folder", `In ${dest}`),
      button: "Create",
      placeholder: "Folder name",
      async submit(name) {
        const reply = await x.busy.run(`Creating ${name}…`, () => request({ type: "create_folder", dest, name }));
        if (reply.error) return reply.error; // e.g. "x already exists" (the name as it is)
        x.flash(reply.hidden ? `Created ${name}: it shows once a file is put in it (this storage has no empty folders)` : `Created ${name}`);
        return null;
      },
    });
  }

  // Asks for the new name, with the current one to edit (a file's without its
  // extension selected), and renames `target` ({path, type}), a file (or, in
  // unsafe mode, a folder), in its folder: a move, as a job. A name taken is
  // explained in the dialog.
  async function rename(target) {
    const folders = x.unsafe.take();
    if (isFolder(target) && !folders) {
      x.flash("Turn on unsafe mode to rename folders");
      return;
    }
    const old = basename(target.path);
    const dot = old.lastIndexOf(".");
    await askName({
      lines: [h("div", { textContent: `Rename ${old}` })],
      button: "Rename",
      value: old,
      selected: !isFolder(target) && dot > 0 ? dot : old.length,
      async submit(name) {
        if (name === old) return null;
        const reply = await x.busy.run(`Renaming ${old}…`, () => request({ type: "rename", path: target.path, name, unsafe: folders }));
        if (reply.error || reply.errors) return reply.error ?? reply.errors.join("; ");
        const result = await x.jobs.result(reply);
        x.flash(resultMessage(result, { verb: "Renamed", noun: "Rename", done: result.renamed, doneText: `Renamed ${old} to ${name}` }));
        return null;
      },
    });
  }

  return { run, askConflicts, move, remove, rename, createFolder };
}

// "Copy" (or "Cut") puts files (and, in unsafe mode, folders) on a clipboard
// shared by the explorers on the page (and their URLs on the system
// clipboard); "Paste" copies (or moves) them into a folder, of any explorer
// and storage.
const CLIPBOARD = Symbol.for("jupyter-storage-explorer.clipboard");
// Dispatched on globalThis once files cut in an explorer were pasted in
// another, which may be in another kernel: {explorer, filesystem, paths} of
// the files cut; that explorer then asks its kernel to show what is left.
const CHANGED_EVENT = "jupyter-storage-explorer:changed";

function createClipboard(x) {
  const { model } = x;

  // targets: [{path, type}] of the filesystem shown, all with URLs. `cut`:
  // pasting moves them.
  async function copyFiles(targets, cut = false) {
    const hasFolders = targets.some(isFolder);
    if (!x.unsafe.take() && hasFolders) {
      x.flash(`Turn on unsafe mode to ${cut ? "cut" : "copy"} folders`);
      return;
    }
    const urls = await x.urlsOf(targets);
    globalThis[CLIPBOARD] = {
      // Pasted in an explorer of the same kernel, they are read with this
      // explorer's filesystem; otherwise from their URLs, on the filesystem
      // of this one's identifier.
      explorer: model.get("_explorer_id"),
      filesystem: x.storage(),
      cut,
      // Pasting folders needs unsafe mode again.
      folders: hasFolders,
      files: targets.map(({ path }, i) => {
        const url = urls[i];
        return { path, url, name: basename(url) };
      }),
    };
    const what = `${cut ? "Cut" : "Copied"} ${targets.length === 1 ? globalThis[CLIPBOARD].files[0].name : `${targets.length} items`}`;
    try {
      await navigator.clipboard.writeText(urls.join("\n"));
      x.flash(what);
    } catch {
      // Paste still works; only the URLs are not on the system clipboard.
      x.flash(`${what} (the browser denied clipboard access for the URLs)`);
    }
  }

  // The "Paste" item for folder `dest` ("Move here" after "Cut"): greyed out
  // when nothing was copied, and null (left out) when folders were copied and
  // unsafe mode is off.
  function pasteItem(dest) {
    const clip = globalThis[CLIPBOARD];
    if (!clip?.files.length) return { label: "Paste", icon: "paste", disabled: true };
    if (clip.folders && !x.unsafe.on()) return null;
    const what = clip.files.length === 1 ? clip.files[0].name : `${clip.files.length} items`;
    return { label: clip.cut ? `Move ${what} here` : `Paste ${what}`, icon: "paste", action: () => paste(clip, dest) };
  }

  // Pastes `clip` (see copyFiles) into folder `dest`. `folders`: whether
  // unsafe mode is on for it; taken now, unless given (a drag took it as it started).
  async function paste(clip, dest, folders = x.unsafe.take()) {
    const [noun, verb, doing] = clip.cut ? ["Move", "Moved", "Moving"] : ["Paste", "Pasted", "Pasting"];
    if (clip.folders && !folders) {
      x.flash(`Turn on unsafe mode to ${noun.toLowerCase()} folders`);
      return;
    }
    const names = clip.files.map((f) => f.name);
    const result = await x.operations.run({
      lines: question(`${noun} ${describeFiles(names)}?`, `Into ${dest}`),
      button: noun,
      text: `${doing} ${describeFiles(names)}…`,
      content: { type: "paste", explorer: clip.explorer, filesystem: clip.filesystem, files: clip.files, dest, unsafe: folders, cut: clip.cut },
      dest,
      noun,
    });
    if (!result) return;
    if (clip.cut) cutPasted(clip, result);
    x.flash(resultMessage(result, { verb, noun, done: clip.cut ? result.moved : result.pasted }));
  }

  // After pasting files cut: they are no longer where they were cut, so the
  // clipboard is emptied once some have moved; and the explorer they were cut
  // in is told (this one's kernel has already shown its own changes).
  function cutPasted(clip, result) {
    if (result.moved?.length && globalThis[CLIPBOARD] === clip) globalThis[CLIPBOARD] = null;
    if (clip.explorer === model.get("_explorer_id")) return;
    const detail = { explorer: clip.explorer, filesystem: clip.filesystem.name, paths: clip.files.map((f) => f.path) };
    globalThis.dispatchEvent(new CustomEvent(CHANGED_EVENT, { detail }));
  }

  // Files cut in this explorer were pasted in another: show what is left.
  function onChanged(ev) {
    const { explorer, filesystem, paths } = ev.detail ?? {};
    if (explorer === model.get("_explorer_id")) model.send({ type: "changed", filesystem, paths });
  }
  globalThis.addEventListener(CHANGED_EVENT, onChanged);

  return {
    copyFiles,
    pasteItem,
    paste,
    dispose: () => globalThis.removeEventListener(CHANGED_EVENT, onChanged),
  };
}
