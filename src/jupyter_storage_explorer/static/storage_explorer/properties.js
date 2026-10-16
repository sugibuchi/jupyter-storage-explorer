// "Properties" in the right-click menu. A file's are read at once; otherwise
// the kernel counts the files and folders in a job (properties.py), while a
// dialog blocks the widget, showing how far it has got, with Cancel. Not an
// operation: unsafe mode stays as it is.

// A table of [label, value] rows; a value is text or an element.
function propertyTable(rows) {
  const cell = (value) => (value instanceof Node ? value : cellText(value));
  return h(
    "table",
    { className: "jse-props" },
    h("tbody", {}, ...rows.map(([label, value]) => h("tr", {}, h("th", { textContent: label }), h("td", {}, cell(value))))),
  );
}

// E.g. "1.2 MB (1,234,567 bytes)".
function sizeText(bytes) {
  if (bytes == null) return "";
  return bytes < 1024 ? `${bytes.toLocaleString()} B` : `${formatSize(bytes)} (${bytes.toLocaleString()} bytes)`;
}

// A time with the file it is of below, e.g. for the oldest file.
function stampText(stamp) {
  if (!stamp) return "No modification times";
  return h("div", {}, h("div", { textContent: formatTime(stamp.mtime) }), h("div", { className: "jse-note", textContent: stamp.path }));
}

function createProperties(x) {
  const { request } = x;

  // targets: [{path, type}].
  async function show(targets) {
    const paths = targets.map((t) => t.path);
    const name = (p) => basename(p) || rootLabel(p);
    const what = paths.length === 1 ? name(paths[0]) : `${paths.length} items`;
    const reply = await x.busy.run(`Reading the properties of ${what}…`, () => request({ type: "properties", paths }));
    if (reply.error) {
      x.flash(`Properties: ${reply.error}`);
      return;
    }
    if (reply.file) {
      showFile(reply.file);
      return;
    }
    const result = await followCount(reply, what);
    if (result) showTotals(what, result);
  }

  function showFile(file) {
    const rows = [
      ["Name", file.name],
      ["Path", file.path],
      ...(file.url ? [["URL", file.url]] : []),
      ["Size", sizeText(file.size)],
      ["Modified", formatTime(file.mtime)],
    ];
    // Everything the filesystem's info() gave, as it gave it.
    const info = Object.entries(file.info).map(([key, value]) => [key, value]);
    x.modal.show(`Properties of ${file.name}`, [
      propertyTable(rows),
      h("div", { className: "jse-section-title jse-props-title", textContent: "From the storage" }),
      propertyTable(info),
    ]);
  }

  // Waits for the counting job of `reply`, showing its progress in a dialog
  // until it ends or the user cancels; its result (partial if cancelled), or
  // null if it failed.
  async function followCount(reply, what) {
    const detail = h("div", { className: "jse-note", textContent: "Starting…" });
    x.jobs.watch(reply.job, (job) => {
      const parts = [`${job.files_done.toLocaleString()} files`, formatSize(job.bytes_done)];
      if (job.current) parts.push(job.current);
      detail.textContent = job.cancelling ? "Cancelling…" : job.state === "queued" ? "Waiting…" : parts.join(" · ");
    });
    const ended = x.jobs.result(reply);
    const asked = x.ask([h("div", { textContent: `Counting the files of ${what}…` }), detail], [{ label: "Cancel", value: "cancel" }]);
    // Cancel, Esc and clicks outside cancel; the end of the job closes the dialog.
    const first = await Promise.race([ended.then(() => "ended"), asked]);
    let result;
    if (first === "ended") {
      x.answer("ended");
      result = await ended;
    } else {
      x.jobs.cancel(reply.job);
      result = await x.busy.run("Cancelling…", () => ended);
    }
    x.jobs.unwatch(reply.job);
    if (result.state === "failed") {
      x.flash(`Properties: ${result.error}`);
      return null;
    }
    return result;
  }

  function showTotals(what, result) {
    const children = [];
    if (result.cancelled) children.push(h("div", { className: "jse-note", textContent: "Cancelled: the counts are of what was found before." }));
    children.push(
      propertyTable([
        ["Files", result.files.toLocaleString()],
        ["Folders", result.folders.toLocaleString()],
        ["Total size", sizeText(result.bytes)],
        ["Oldest file", stampText(result.oldest)],
        ["Newest file", stampText(result.newest)],
      ]),
    );
    if (result.errors.length) {
      const count = result.errors.length;
      children.push(
        h("div", {
          className: "jse-section-title jse-error-text jse-props-title",
          textContent: `Not counted: ${count} item${count > 1 ? "s" : ""} that could not be read`,
        }),
        h("pre", { className: "jse-text", textContent: result.errors.join("\n") }),
      );
    }
    x.modal.show(`Properties of ${what}`, children);
  }

  return { show };
}
