// JupyterLab's own editors and viewers ("Open in JupyterLab"), and views in
// tabs of their own ("View in a new tab"), with the launcher's
// JupyterLab extension. When on the page, it puts its functions under this
// key: open(file) (launcher/labextension/src/files.ts), which shows the file
// through a drive of its own, reading and saving it with `get` and `save`
// below, through this widget's kernel ("jupyterlab_get", "jupyterlab_save");
// and openWidget(tab) (queryTabs.ts). Without the extension, neither is
// offered.
const JUPYTERLAB = Symbol.for("jupyter-storage-explorer.jupyterlab");
// A kernel that stopped never answers: JupyterLab then shows this error.
const JUPYTERLAB_TIMEOUT_MS = 120_000;

function createJupyterLab(x) {
  const { model, request } = x;

  // The model of the kernel's reply to `content`, for JupyterLab's drive.
  function askKernel(content) {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(
        () => reject(new Error("The Storage Explorer did not answer: its kernel may have stopped. Open the file from the explorer again.")),
        JUPYTERLAB_TIMEOUT_MS,
      );
    });
    return Promise.race([request(content), timeout]).then((reply) => {
      clearTimeout(timer);
      if (reply.error) throw new Error(reply.error);
      return reply.model;
    });
  }

  // Whether JupyterLab can show the file ({name, type, format}): the
  // extension is on the page, and JupyterLab knows the file's type (e.g. CSV,
  // JSON, notebooks, images) or the explorer reads it as text (its text
  // editor opens any), not e.g. Parquet or Excel, which it would only show
  // as an error.
  function canOpen(entry) {
    const jupyterlab = globalThis[JUPYTERLAB];
    if (!jupyterlab || isFolder(entry)) return false;
    return jupyterlab.canOpen(entry.name) || model.get("_text_formats").includes(entry.format);
  }

  function open(path) {
    x.unsafe.take(); // an operation, though not a risky one
    // The storage shown now: the file stays in it while the explorer moves on.
    const filesystem = model.get("_filesystem");
    const ask = (type, options) => askKernel({ ...options, type, filesystem, path });
    globalThis[JUPYTERLAB].open({
      explorer: model.get("_explorer_id"),
      storage: filesystem,
      path,
      get: (options) => ask("jupyterlab_get", options),
      save: (options) => ask("jupyterlab_save", options),
    }).catch((err) => x.flash(`Cannot open in JupyterLab: ${err.message ?? err}`));
  }

  // The launcher's settings file (the toolbar's settings button), created by
  // the kernel from its template if missing, once the user agrees
  // ("settings_open"), then opened as a file of its own storage: get and save
  // name no path, the kernel reads and writes that file only ("settings").
  const canOpenSettings = () => Boolean(globalThis[JUPYTERLAB]?.open);

  async function openSettings() {
    let reply = await request({ type: "settings_open" });
    if (reply.missing) {
      const lines = question("Create your launcher settings from a template?", model.get("_settings_path"));
      if (!(await x.ask(lines, confirmButtons("Create")))) return;
      reply = await request({ type: "settings_open", create: true });
    }
    if (reply.error) {
      x.flash(`Cannot open the settings: ${reply.error}`);
      return;
    }
    const ask = (type, options) => askKernel({ ...options, type, settings: true });
    globalThis[JUPYTERLAB].open({
      explorer: model.get("_explorer_id"),
      storage: "Launcher settings",
      path: "launcher.py",
      get: (options) => ask("jupyterlab_get", options),
      save: (options) => ask("jupyterlab_save", options),
    }).catch((err) => x.flash(`Cannot open the settings: ${err.message ?? err}`));
  }

  // "View in a new tab": the kernel views the item and opens a widget of the
  // view ("view_tab"), a DataExplorer for data to query, else a ViewTab; the
  // extension shows it with this widget's kernel connection (`openWidget`),
  // and the kernel lets it go when the tab closes.
  const canOpenViewTab = () => Boolean(globalThis[JUPYTERLAB]?.openWidget);

  // `format` and `engine` as for the preview (preview.js's open).
  async function openViewTab(path, format = null, engine = undefined) {
    const reply = await request({ type: "view_tab", path, format, ...(engine === undefined ? {} : { engine }) });
    if (reply.error) {
      x.flash(`Cannot open a tab: ${reply.error}`);
      return;
    }
    const closed = () => model.send({ type: "view_tab_closed", model_id: reply.model_id });
    try {
      await globalThis[JUPYTERLAB].openWidget({ modelId: reply.model_id, title: reply.title, caption: reply.url, owner: x.el, onClose: closed });
    } catch (err) {
      closed();
      x.flash(`Cannot open a tab: ${err.message ?? err}`);
    }
  }

  return { canOpen, open, canOpenSettings, openSettings, canOpenViewTab, openViewTab };
}
