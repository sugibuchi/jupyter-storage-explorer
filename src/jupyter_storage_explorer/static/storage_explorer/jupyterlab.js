// JupyterLab's own editors and viewers ("Open in JupyterLab"), and views in
// tabs of their own ("View in a new tab"), with the launcher's
// JupyterLab extension. When on the page, it puts its functions under this
// key: open(file) (launcher/labextension/src/files.ts), which shows the file
// through a drive of its own, reading and saving it with `get` and `save`
// below, through this widget's kernel ("jupyterlab_get", "jupyterlab_save");
// and openViewTab(tab) (queryTabs.ts). Without the extension, neither is
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
    }).catch((err) => x.flash(`Cannot open in JupyterLab: ${err.message ?? err}`, { error: true }));
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
      x.flash(`Cannot open the settings: ${reply.error}`, { error: true });
      return;
    }
    const ask = (type, options) => askKernel({ ...options, type, settings: true });
    globalThis[JUPYTERLAB].open({
      explorer: model.get("_explorer_id"),
      storage: "Launcher settings",
      path: "launcher.py",
      get: (options) => ask("jupyterlab_get", options),
      save: (options) => ask("jupyterlab_save", options),
    }).catch((err) => x.flash(`Cannot open the settings: ${err.message ?? err}`, { error: true }));
  }

  // "View in a new tab": the kernel answers at once ("view_tab"), and the
  // extension opens the tab, showing that the view loads (`openViewTab`).
  // The kernel reads it in a worker thread, then sends a "view_tab" message
  // with the model id of a widget of the view (a DataExplorer for data to
  // query, a TableSetTab, else a ViewTab), which the tab shows with this
  // widget's kernel connection, or with the error. Closing the tab lets the
  // widget go, or drops the view still loading. A view asking the user first
  // (ViewWithPrompt) comes as a ViewTab of the prompt, "asking": the tab
  // keeps waiting, then shows the view's widget instead, and lets the
  // prompt's go.
  const canOpenViewTab = () => Boolean(globalThis[JUPYTERLAB]?.openViewTab);
  // The tabs waiting for their view: load id -> the extension's handle.
  const loadingTabs = new Map();

  // `format` and `engine` as for the preview (preview.js's open).
  async function openViewTab(path, format = null, engine = undefined) {
    const reply = await request({ type: "view_tab", path, format, ...(engine === undefined ? {} : { engine }) });
    if (reply.error) {
      x.flash(`Cannot open a tab: ${reply.error}`, { error: true });
      return;
    }
    const loadId = reply.load_id;
    let modelId = null;
    const closed = () => {
      loadingTabs.delete(loadId);
      model.send({ type: "view_tab_closed", load_id: loadId, model_id: modelId });
    };
    try {
      const tab = globalThis[JUPYTERLAB].openViewTab({ title: reply.title, caption: reply.url, owner: x.el, onClose: closed });
      loadingTabs.set(loadId, {
        show: (id) => {
          const previous = modelId;
          modelId = id;
          // The prompt's widget, replaced once the view's is shown.
          return tab.show(id).finally(() => previous && model.send({ type: "view_tab_closed", model_id: previous }));
        },
        fail: tab.fail,
      });
    } catch (err) {
      closed();
      x.flash(`Cannot open a tab: ${err.message ?? err}`, { error: true });
    }
  }

  // The kernel's "view_tab" message: the view of a tab has loaded, or failed.
  function onViewTab(msg) {
    const tab = loadingTabs.get(msg.load_id);
    if (!tab) {
      // Closed meanwhile: the kernel lets the widget go.
      if (msg.model_id) model.send({ type: "view_tab_closed", model_id: msg.model_id });
      return;
    }
    // A prompt: the view of its answer comes for the same load.
    if (!msg.asking) loadingTabs.delete(msg.load_id);
    if (msg.error) tab.fail(msg.error);
    else tab.show(msg.model_id).catch((err) => tab.fail(`Cannot show the view: ${err.message ?? err}`));
  }

  return { canOpen, open, canOpenSettings, openSettings, canOpenViewTab, openViewTab, onViewTab };
}
