// Transfers: drag and drop onto the tree and list (uploads from JupyterLab's
// file browser and from the computer, moves within the explorer), drags of
// files out onto JupyterLab's file browser, and downloads to the computer
// and to JupyterLab.

// JupyterLab's file browser uses Lumino drag events ("lm-drag*"), not the
// browser's native ones. Its data is a list of paths relative to the folder
// the Jupyter server runs in.
const CONTENTS_MIME = "application/x-jupyter-icontents";
// Drags of items from the list carry this type, its value their JSON: the
// items as Copy puts them on the clipboard (see copyFiles: {explorer,
// filesystem, folders, files: [{path, url, name}]}), and "unsafe": whether
// unsafe mode was on when the drag started. Readable on the drop only, but on
// any page: a drag copies between browser windows too.
const ITEMS_TYPE = "application/x-jupyter-storage-explorer-items";
// While a drag of items runs, the id of the explorer it started in (set as it
// starts, cleared as it ends): before the drop, targets on this page tell
// their own explorer's drags (moves) from another's (copies, as Paste does)
// by it. Drags from another page leave it unset: another explorer's.
const DRAG_SOURCE = Symbol.for("jupyter-storage-explorer.drag-source");
// The explorers on this page, by id: {download(paths, dest, ifExists)}, the
// download to the Jupyter server that the launcher's JupyterLab extension
// calls on a drop of items onto JupyterLab's file browser (download.ts), as
// drag data can only be text. Without the extension, such drops do nothing.
const EXPLORERS = Symbol.for("jupyter-storage-explorer.explorers");
// Under the server's 10 MB limit for one message from the browser.
const CHUNK_BYTES = 1024 * 1024;

// Where JupyterLab's paths are relative to (the server's folder on disk),
// from the configuration JupyterLab puts in every page.
function serverRoot() {
  try {
    return JSON.parse(document.getElementById("jupyter-config-data").textContent).serverRoot ?? null;
  } catch {
    return null;
  }
}

// Files in a native drop; folders are listed separately, as they are not uploaded.
function droppedFiles(dataTransfer) {
  const files = [];
  const folders = [];
  for (const item of dataTransfer.items) {
    if (item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isDirectory) folders.push(entry.name);
    else if (item.getAsFile()) files.push(item.getAsFile());
  }
  return { files, folders };
}

function createTransfers(x) {
  const { model, request } = x;
  const uploadMessage = (result, done) => resultMessage(result, { verb: "Uploaded", noun: "Upload", done });
  // The upload dialog, for drops from JupyterLab and from the computer.
  const askUpload = (names, dest) => x.ask(question(`Upload ${describeFiles(names)}?`, `To ${dest}`), confirmButtons("Upload"));
  const explorer = model.get("_explorer_id");
  const explorers = (globalThis[EXPLORERS] ??= new Map());
  explorers.set(explorer, { download: downloadToServer });

  // --- Drops on the panes (`panes`: the tree's and the list's) ---

  function attach(panes) {
    let highlighted = null;

    function highlight(target) {
      if (highlighted === target) return;
      highlighted?.classList.remove("jse-drop-target");
      highlighted = target;
      highlighted?.classList.add("jse-drop-target");
    }

    // A folder row (list or tree) under the pointer, else the folder shown.
    function dropTarget(ev) {
      const node = ev.target instanceof Element ? ev.target.closest("[data-drop-dir]") : null;
      if (node && panes.contains(node)) return { el: node, dir: node.dataset.dropDir };
      return { el: x.list.el, dir: model.get("_current_dir") };
    }

    // Drops of one kind of drag, the drags that `accepts(ev)`: `target(ev)`
    // tells where one would go, {el, dir} (el is highlighted), or null where
    // it cannot be dropped; `drop(ev, target)` takes a drop there. `prefix`:
    // "lm-" for Lumino's drags (JupyterLab's file browser), "" for the
    // browser's own.
    function onDrops(prefix, { accepts, target, drop }) {
      const on = (type, handle) =>
        panes.addEventListener(prefix + type, (ev) => {
          if (!accepts(ev)) return;
          ev.stopPropagation(); // keep the notebook from handling it too
          handle(ev);
        });
      on("dragenter", (ev) => ev.preventDefault()); // the panes may take it
      on("dragover", (ev) => {
        const at = target(ev);
        highlight(at?.el ?? null);
        if (at) ev.preventDefault(); // else it cannot be dropped here
      });
      on("dragleave", (ev) => {
        if (!(ev.relatedTarget instanceof Node && panes.contains(ev.relatedTarget))) highlight(null);
      });
      on("drop", (ev) => {
        ev.preventDefault(); // otherwise the browser opens a file dropped
        highlight(null);
        const at = target(ev);
        if (at) drop(ev, at);
      });
    }

    // From JupyterLab's file browser: uploaded.
    onDrops("lm-", {
      accepts: (ev) => Boolean(ev.mimeData?.hasData?.(CONTENTS_MIME)),
      target(ev) {
        // JupyterLab only offers "move"; accepting it is safe, as the dragging side
        // never deletes anything itself. The kernel copies; the original stays.
        ev.dropAction = ev.proposedAction;
        return dropTarget(ev);
      },
      drop(ev, at) {
        if (ev.proposedAction !== "none") uploadFromJupyterLab(ev.mimeData.getData(CONTENTS_MIME), at.dir);
      },
    });

    // From the computer: uploaded.
    onDrops("", {
      accepts: (ev) => Array.from(ev.dataTransfer?.types ?? []).includes("Files"),
      target(ev) {
        ev.dataTransfer.dropEffect = "copy";
        return dropTarget(ev);
      },
      // The DataTransfer is only readable during this event, so collect the files now.
      drop: (ev, at) => uploadFromComputer(droppedFiles(ev.dataTransfer), at.dir),
    });

    // From this explorer's list: moved, only onto a folder (row or tree node),
    // as the list itself is the folder they are in. From another explorer's
    // (another tab or notebook, maybe another kernel): copied, as Paste does,
    // onto a folder or the folder shown.
    onDrops("", {
      accepts: (ev) => Array.from(ev.dataTransfer?.types ?? []).includes(ITEMS_TYPE),
      target(ev) {
        const own = globalThis[DRAG_SOURCE] === explorer;
        const at = dropTarget(ev);
        if (own && at.el === x.list.el) return null;
        ev.dataTransfer.dropEffect = own ? "move" : "copy";
        return at;
      },
      drop(ev, at) {
        const { unsafe, ...items } = JSON.parse(ev.dataTransfer.getData(ITEMS_TYPE));
        if (items.explorer === explorer) {
          x.operations.move(
            items.files.map((f) => f.path),
            at.dir,
            unsafe,
          );
        } else {
          x.clipboard.paste({ ...items, cut: false }, at.dir, unsafe);
        }
      },
    });
    panes.addEventListener("dragend", () => highlight(null));
  }

  // --- Uploads ---

  // From JupyterLab's file browser: the kernel copies the files (and, in
  // unsafe mode, folders) itself, as a job.
  async function uploadFromJupyterLab(paths, dest) {
    const folders = x.unsafe.take();
    const root = serverRoot();
    if (root == null) {
      x.flash("Cannot upload: JupyterLab did not say where its files are");
      return;
    }
    const names = paths.map(basename);
    const result = await x.operations.run({
      lines: question(`Upload ${describeFiles(names)}?`, `To ${dest}`),
      button: "Upload",
      text: `Uploading ${describeFiles(names)}…`,
      content: { type: "upload", root, paths, dest, unsafe: folders },
      dest,
      noun: "Upload",
    });
    if (result) x.flash(uploadMessage(result, result.copied));
  }

  // From the computer (native drag and drop): the browser sends each file in
  // pieces, each acknowledged by the kernel before the next. One at a time.
  let uploading = false;

  async function uploadFromComputer({ files: dropped, folders }, dest) {
    x.unsafe.take(); // an operation, though not on folders
    const errors = folders.map((name) => `${name}: folders are not uploaded`);
    // Files over the widget's max_upload_bytes are refused before sending anything.
    const limit = model.get("_max_upload_bytes");
    const files = [];
    for (const file of dropped) {
      if (limit != null && file.size > limit) errors.push(`${file.name}: too large to upload (over ${formatSize(limit)})`);
      else files.push(file);
    }
    if (!files.length) {
      x.flash(uploadMessage({ errors }, []));
      return;
    }
    if (uploading) {
      x.flash("Another upload is still running");
      return;
    }
    const names = files.map((f) => f.name);
    if (!(await askUpload(names, dest))) return;
    uploading = true;
    const copied = [];
    const skipped = [];
    try {
      const { conflicts = [] } = await x.busy.run("Checking…", () => request({ type: "upload_check", dest, names }));
      let toSend = files;
      if (conflicts.length) {
        const choice = await x.operations.askConflicts(conflicts, dest);
        if (!choice) {
          x.flash("Upload cancelled");
          return;
        }
        if (choice === "skip") {
          toSend = files.filter((f) => !conflicts.includes(f.name));
          skipped.push(...conflicts);
        }
      }
      // Blocked while the pieces are sent; the busy dialog shows the progress.
      // After a file's last piece, the kernel copies it to the storage as a
      // job, which goes on in the background once all pieces are sent.
      const jobs = [];
      await x.busy.run("Uploading…", async () => {
        for (const [i, file] of toSend.entries()) {
          const id = `${Date.now()}-${i}`;
          let offset = 0;
          do {
            x.busy.say(`Uploading ${file.name}: ${file.size ? Math.floor((100 * offset) / file.size) : 0}%`);
            const piece = await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer();
            offset += piece.byteLength;
            const last = offset >= file.size;
            const reply = await request({ type: "upload_chunk", id, dest, name: file.name, last }, [piece]);
            if (reply.error) {
              errors.push(reply.error);
              break;
            }
            if (last) jobs.push(x.jobs.result(reply));
          } while (offset < file.size);
        }
      });
      for (const result of await Promise.all(jobs)) {
        copied.push(...(result.copied ?? []));
        errors.push(...(result.errors ?? []));
        if (result.state === "failed") errors.push(result.error);
        else if (result.state === "cancelled") errors.push("cancelled");
      }
    } finally {
      uploading = false;
    }
    x.flash(uploadMessage({ skipped, errors }, copied));
  }

  // --- Drags out of the list ---

  // Entries a drag starting on `entry` moves: the selected ones if it is
  // selected, else just it. Folders only with `folders` (unsafe mode).
  function draggedItems(entry, folders) {
    const allowed = (e) => folders || !isFolder(e);
    if (!allowed(entry)) return [];
    const selected = model.get("_selected");
    if (!selected.includes(entry.path)) return [entry];
    return x.list.entriesAt(selected).filter(allowed);
  }

  // A list row's drag: a move within the explorer, a copy onto another, and
  // a download onto JupyterLab's file browser. Starting a drag is an
  // operation (see createUnsafe).
  function startDrag(ev, entry) {
    const folders = x.unsafe.take();
    const items = draggedItems(entry, folders);
    if (!items.length) {
      ev.preventDefault(); // a folder, locked
      x.flash("Turn on unsafe mode to move folders");
      return;
    }
    // With their URLs, which another kernel finds them by (known from the list's tooltips).
    const drag = {
      explorer,
      filesystem: model.get("_filesystem"),
      folders: items.some(isFolder),
      unsafe: folders,
      files: items.map((e) => ({ path: e.path, url: x.list.urlOf(e), name: e.name })),
    };
    ev.dataTransfer.setData(ITEMS_TYPE, JSON.stringify(drag));
    ev.dataTransfer.effectAllowed = "copyMove";
    globalThis[DRAG_SOURCE] = explorer;
    // On the row, which gets the event even if the list has redrawn it meanwhile.
    ev.target.addEventListener("dragend", endDrag, { once: true });
  }

  function endDrag() {
    if (globalThis[DRAG_SOURCE] === explorer) globalThis[DRAG_SOURCE] = null;
  }

  // Copies files `paths` into `dest`, a folder relative to the Jupyter
  // server's, as JupyterLab names it: files dropped onto its file browser
  // (see EXPLORERS). Resolves with the kernel's reply: {conflicts} if files
  // exist there and `ifExists` is "ask", else, once the download (a job) has
  // ended, {copied, skipped, errors} (file names; folders, a cancel or a
  // failure are errors).
  async function downloadToServer(paths, dest, ifExists = "ask") {
    const root = serverRoot();
    if (root == null) return { errors: ["JupyterLab did not say where its files are"] };
    const reply = await x.busy.run(`Downloading ${describeFiles(paths.map(basename))} to JupyterLab…`, () =>
      request({ type: "download_to_server", paths, root, dest, if_exists: ifExists }),
    );
    const result = await x.jobs.result(reply);
    const outcome = jobOutcome(result, result.copied ?? [], "Download");
    return { ...result, errors: [...(result.errors ?? []), ...outcome] };
  }

  // --- Download to local: the kernel sends each file's bytes ("download"
  // messages); the browser saves them ---

  // Files requested but not received yet, and the errors so far.
  const downloads = { pending: 0, done: 0, errors: [] };

  function download(paths) {
    x.unsafe.take(); // an operation, though not on folders
    downloads.pending += paths.length;
    // Blocked until the last file arrives (onDownload); the kernel sends one message per file.
    x.busy.start(`Downloading ${paths.length === 1 ? "1 file" : `${paths.length} files`} to local…`);
    model.send({ type: "download", paths });
  }

  function onDownload(msg, buffers) {
    downloads.pending -= 1;
    if (downloads.pending <= 0) x.busy.end();
    if (msg.error) {
      downloads.errors.push(msg.error);
    } else {
      const url = URL.createObjectURL(new Blob([buffers[0]]));
      const link = h("a", { href: url, download: msg.name });
      document.body.append(link);
      link.click();
      link.remove();
      // Revoking right away can cancel the download in some browsers.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      downloads.done += 1;
    }
    if (downloads.pending > 0) return;
    const { done, errors } = downloads;
    const summary = done ? `Downloaded ${done === 1 ? "1 file" : `${done} files`} to local` : "";
    x.flash([summary, ...errors.map((e) => `Failed: ${e}`)].filter(Boolean).join("; "));
    Object.assign(downloads, { done: 0, errors: [] });
  }

  // --- Download to JupyterLab: the kernel copies the files into its folder
  // download_to_jupyterlab_path (on the Jupyter server's machine) ---

  async function downloadToJupyterLab(paths) {
    x.unsafe.take(); // an operation, though not on folders
    const dest = model.get("_download_to_jupyterlab_path");
    const names = paths.map(basename);
    const result = await x.operations.run({
      lines: question(`Download ${describeFiles(names)} to JupyterLab?`, `To ${dest}`),
      button: "Download",
      text: `Downloading ${describeFiles(names)} to JupyterLab…`,
      content: { type: "download_to_jupyterlab", paths },
      dest,
      noun: "Download",
    });
    if (!result) return;
    const copied = result.copied ?? [];
    x.flash(resultMessage(result, { verb: "Downloaded", noun: "Download", done: copied, doneText: `Downloaded ${describeFiles(copied)} to ${dest}` }));
  }

  return {
    attach,
    startDrag,
    download,
    onDownload,
    downloadToJupyterLab,
    dispose() {
      explorers.delete(explorer);
      endDrag();
    },
  };
}
