# Development

## Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) of packages. They are
released together, with one version taken from the git tag.

The launcher and the plugins require the explorer of exactly their own version, as they may use its internals. Their
`hatch_build.py` sets these dependencies, because the version comes from git.

The explorer's extras (`polars`, `polars-support`, ...) have no versions in its `pyproject.toml`. Each plugin pins the
explorer exactly, so an extra always installs the plugin of the explorer's version. The launcher has the same extras.

| Package                                   | Folder                    | Contents                                                                                              |
|-------------------------------------------|---------------------------|-------------------------------------------------------------------------------------------------------|
| `jupyter-storage-explorer`                | `.`                       | The widgets `StorageExplorer` and `DataExplorer`; pure Python, no build.                              |
| `jupyter-storage-explorer-launcher`       | `launcher/`               | The JupyterLab launcher item, and `launch()` run in the tab it opens.                                 |
| `jupyter-storage-explorer-<name>-support` | `plugins/<name>-support/` | The plugins: `polars`, `pandas`, `pyspark` (engines), `abfs` (Azure Data Lake Storage operations) and `databricks` (Databricks locations and the Databricks Connect engine, experimental). |

| Path                                                           | Contents                                                                                             |
|----------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `src/jupyter_storage_explorer/`                                | The widgets: `storage_explorer.py`, `data_explorer.py`.                                              |
| `src/jupyter_storage_explorer/filesystems/`                    | Filesystems' locations (mappers) and file operations: interfaces users extend, and the default ones. |
| `src/jupyter_storage_explorer/formats/`                        | The formats files are previewed, queried and loaded as.                                              |
| `src/jupyter_storage_explorer/_explorer/`                      | `StorageExplorer`'s features, as mixins of the class.                                                |
| `src/jupyter_storage_explorer/_jobs/`                          | File operations planned and run as jobs, without the widget.                                         |
| `src/jupyter_storage_explorer/_query/`                         | The data browser: filters, settings, and a dataset open in it.                                       |
| `src/jupyter_storage_explorer/static/`                         | The widgets' JavaScript and CSS, loaded at run time (no build step).                                 |
| `src/jupyter_storage_explorer/static/storage_explorer/`        | The storage explorer's JavaScript, a file per feature, joined at run time.                           |
| `launcher/src/jupyter_storage_explorer_launcher/`              | `launch()`, which merges the `storage-explorer/launcher.py` files (layers).                          |
| `launcher/labextension/`                                       | The JupyterLab extension (TypeScript).                                                               |
| `launcher/src/jupyter_storage_explorer_launcher/labextension/` | The extension built from `launcher/labextension/` (git-ignored).                                     |
| `notebooks/`                                                   | Demo notebooks and `make_samples.py`, which writes the sample data they use.                         |
| `tests/`                                                       | The Python tests, a folder per part of the package (`explorer/`, `formats/`, ...); shared helpers.   |
| `tests/browser/`                                               | Checks of the widgets' JavaScript, and their smoke test in a browser.                                |
| `docs/scripts/`                                                | Scripts making the docs' screenshots and the demo GIFs.                                              |
| `binder/`                                                      | The demo on mybinder.org (the README's "Try it" link): released packages, demo data.                 |

The explorer's runtime dependencies are only anywidget, fsspec, narwhals, pygments and traitlets. Every other library,
such as polars, pandas, PyArrow, Pillow or PySpark, is optional and probed at run time. The engines' supports come with
the plugins.

### The public API

Users import only from these modules and the plugins' packages. Their `__all__` is the public API: what users
construct, subclass, call or annotate with.

- `jupyter_storage_explorer`, the top level: the widgets, `Location` and `StorageExplorerPlugin`;
- `jupyter_storage_explorer.filesystems`: locations, mappers and operations;
- `jupyter_storage_explorer.formats` and `formats.supports`.

The explorer's machinery stays out of them, such as `SupportChain`, `OperationChain` and `detect`. The package and the
tests import it from its modules.

`jupyter_storage_explorer.testing` has the helpers plugins test with: items and pytest fixtures. It needs pytest.

All Python commands go through [uv](https://docs.astral.sh/uv/). Node.js, for the extension and the JavaScript's checks,
comes with the dev dependencies (`nodejs-wheel`), so `uv run node`, `uv run npx` and `uv run jlpm` work without
installing it.

## Setup

```bash
uv sync                    # every package, editable, with the dev dependencies
cd launcher/labextension
uv run jlpm install        # the extension's build tools, into node_modules
uv run jlpm build          # builds the extension into launcher/src/jupyter_storage_explorer_launcher/labextension
cd ../..
uv sync                    # reinstalls the launcher package with the built extension
```

To try the widgets in a browser:

```bash
uv run jupyter lab
```

IntelliJ's notebook view runs the widgets too, but dragging files in or out of them only works in a browser.

## Tests

```bash
uv run pytest                                        # the Python side
uvx ruff check src launcher/src plugins tests docs/scripts           # lint
uvx ruff format --check src launcher/src plugins tests docs/scripts  # formatting of the Python
uv run npx --yes prettier@3.3.3 --check .            # formatting: the widgets' JS and CSS, the extension's TS
uv run tests/browser/check_js.py                     # their JavaScript: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py           # the widgets in a real JupyterLab
```

CI runs all but the last, and compiles the extension's TypeScript. It does not run the smoke test: run it yourself after
changing `static/` or the extension.

### Python tests

The explorer's and the launcher's tests are in `tests/`, and each plugin's in `plugins/<name>-support/tests/`.
`uv run pytest` at the root runs them all.

To run a plugin's tests alone, with only its dependencies, run this in its folder:

```bash
uv run --isolated --package <its package> pytest
```

A plain `uv run` there would install the plugin's `dev` group into the shared `.venv`, e.g. pyspark. The explorer's
tests expect pyspark missing, until `uv sync` at the root removes it.

`tests/` has a folder per part of the package:

| Folder         | Tests of                                       |
|----------------|------------------------------------------------|
| `explorer/`    | `StorageExplorer` and `_explorer/`             |
| `query/`       | `_query/` and `DataExplorer`                   |
| `formats/`     | `formats/`                                     |
| `filesystems/` | `filesystems/`                                 |
| `jobs/`        | `_jobs/`                                       |
| `launcher/`    | The launcher                                   |
| `browser/`     | The JavaScript's checks and the smoke test     |

The top of `tests/` has `conftest.py`, the tests of the top-level modules, and the helpers the folders share.

- The folders have no `__init__.py`. pytest puts `conftest.py`'s folder on `sys.path`, so helpers are imported by name.
- Never import one test file from another: move what they share to a helper.
- Test files' names are unique across the folders, as pytest imports them by name. A plugin's are `test_<plugin>_*.py`.

The fixtures come from the public `jupyter_storage_explorer.testing`, which plugins' tests use too:

- `memfs`: a cleared fsspec memory filesystem;
- `make_item`: writes a file there and returns it as formats and supports get it, an `ItemContext`;
- `local_item`: the same for a local file.

`tests/conftest.py` adds `mem_explorer` and `local`, explorers of those.

The widget tests subclass the widget to capture `send()`. They drive it through `_on_custom_msg`, as the frontend
would. `StorageExplorer`'s are in `tests/explorer/test_explorer_*.py`, a file per feature, on the harness of
`tests/explorers.py`.

Without a running asyncio loop, jobs and loads run at once, so most tests need no threads. Tests of the worker threads
run in `asyncio.run`, as code runs in a kernel. `until`, in `tests/in_a_kernel.py`, lets the loop run until a
condition holds.

Plugins' tests cover their own code: supports, options, engine, operations and entry point. The explorer's tests use
the plugins' supports as material, from `tests/all_supports.py`. The plugins' test dependencies are in each one's
`dev` group.

A few libraries need care:

- **polars** cannot read `memory://`. Whatever polars reads by URL needs real local files, in `tmp_path`.
- **The data browser's tests** run each filter on polars, pandas, PyArrow, DuckDB and sqlframe. sqlframe is the PySpark
  API on DuckDB, which narwhals queries as it does Spark: the core's tests have no Spark.
- **pyspark-support's view tests** run on a real local Spark session. They are skipped without Java or pyspark, which
  the shared `.venv` lacks. CI's `spark` job runs them alone, with Java.

### The smoke test

The JavaScript has no unit tests. Instead, `tests/browser/smoke.py` starts a JupyterLab of its own and clicks through
the main features in the installed Microsoft Edge: browsing, previews, the data browser, file operations, transfers and
the launcher's tab. Give check names to run only those. A failed check leaves a screenshot,
`tests/browser/smoke-<check>.png`.

- Add a check there for each new feature.
- It runs JupyterLab with the demo data of `docs/scripts/`, through `_lab.py` and `demo_data.py`.
- It reloads the page and restarts a launcher tab's kernel. Check a server restart by hand: stop and start its process.

For a one-off look, write a Playwright script on `_lab` the same way. Use a new notebook each time: a reused name
reuses its kernel, which keeps the old JavaScript.

`tests/browser/check_js.py` joins each widget's module as the kernel does. It runs `node --check` and ESLint on it, for
names used but defined nowhere, or defined but unused.

### Performance

`uv run tests/performance/benchmark.py` times what users wait for: opening large folders, clicks, copies and scrolling
the data browser. It runs on a memory filesystem with a latency per call, so that round trips count as on cloud
storages. Compare its timings before and after a change, on the same machine.

### Older JupyterLab

The packages support JupyterLab 4.0 or later, but the development environment has the latest. To run the smoke test on
an older JupyterLab, make an environment of its own, outside the repository. `uv run --with` would not do, as it does
not see the extensions installed in `.venv`.

```bash
uv export --group docs --group dev --no-hashes --no-emit-workspace -o ../req.txt
echo "jupyterlab==4.0.*" > ../override.txt
uv venv ../lab40
uv pip install --python ../lab40 -r ../req.txt --override ../override.txt -e . -e launcher
uv run --no-project --python ../lab40 tests/browser/smoke.py
```

After rebuilding the extension, install it there again:

```bash
uv pip install --python ../lab40 -e launcher --reinstall-package jupyter-storage-explorer-launcher
```

## Design

The choices below shape the whole project. Keep to them, or change them on purpose.

### Everything runs in the kernel

The explorer is a widget in the user's kernel, as their code is. It adds nothing to the Jupyter server: no server
extension, and no endpoints reaching storages.

- The kernel reaches storages with the user's credentials and libraries, as a notebook would.
- The launcher's JupyterLab extension only shows explorers, and passes the frontend's requests to their kernels.
- Explorers in different kernels work together through the page: the clipboard, drags and locations.

So the explorer works wherever widgets work: JupyterLab, notebooks, consoles and IntelliJ.

### The kernel decides, the browser shows

The browser holds no authority. Every check is made in the kernel, as it plans each item.

- Unsafe mode, the transfer policy and conflicts are checked there.
- The browser names files only by the paths the kernel sent. A drop from another page carries no file names at all.
- File names are shown through `visible()`, so a name cannot pretend to be another.

The browser does what needs no round trip: filtering, sorting and paging a listing, and the menus.

### Security

The explorer can do what the user's code can, and no more. Keep it so.

Credentials come from the environment, as each storage's library finds them. Examples are an AWS profile, an Azure CLI
login or managed identity, and Google's default credentials. Options given to a storage work too.

The explorer never asks for secrets, and never reads them from environment variables.

- Asking would happen in every kernel: each launcher tab and each notebook.
- Secrets in environment variables are a practice we do not support.

"Python code" leaves out credentials. It drops options declared secret, and options whose names look like credentials.

Unsafe mode and the transfer policy prevent mistakes. They are not a security boundary: code in the kernel can do
whatever its credentials allow.

What storages hold is shown, never run:

- Names show control and invisible characters as `\uXXXX`.
- Markdown is sanitized.
- A format's own icon is shown as an image, in which scripts do not run.
- Notebooks opened with Edit are untrusted unless signed, as JupyterLab's own are. The kernel checks signatures with
  nbformat's notary, and signs a notebook saved while trusted.

Files pasted from another kernel are read with one of the explorer's storages. For the kinds of storage the mappers
know, the explorer may also open one with the user's credentials. It never opens an unknown URL.

### Extended by chains, users first

Formats, supports, file operations and mappers are each a chain of objects, tried in order:

1. what the explorer's arguments give;
2. what the plugins give;
3. the defaults.

The first that takes an item handles it:

- A support takes the items its `supports` accepts. What its method then raises is the item's error.
- An operation refuses a call by raising `FileSystemOperations.NotSupported`, and the next one is tried.
- A mapper takes the filesystems it matches.
- The highest priority among matching formats wins.

So a plugin or a user adds or replaces behaviour without changing the core.

A format only detects, and a support handles one format with one library. So a new library for a format needs only a
support.

### Optional libraries, probed at run time

The core needs only anywidget, fsspec, narwhals, pygments and traitlets. Every other library is optional.

- Supports import their libraries inside methods, and the chain calls only those whose packages are installed.
- Mappers match filesystems by class name, so they never import a storage's library.
- Plugins never depend on their libraries: their `full` extra installs them.

So installing a plugin never changes the libraries of a shared environment.

### Locations, not fsspec objects

Items travel between kernels, to generated code and to the transfer policy as `Location`s. A location describes the
storage, not the fsspec implementation, so two implementations of one storage agree. It never holds credentials.

### Few round trips to storages

Cloud storages answer each call in tens of milliseconds, and folders hold tens of thousands of items. So:

- A listing makes one `ls`, and reads no file. Formats that need a file's first bytes wait for a click.
- The listing goes to the browser as columns, without paths or URLs.
- A click detects its item once, for the selection, the menu and the preview.
- The data browser queries lazy data where it is, rather than reading it all.

`tests/performance/benchmark.py` counts the calls of each scenario. A change should not add calls.

### Written for AI to extend

Users are expected to generate formats, supports and plugins with AI. So the rules are written where AI reads them:
in docstrings and in docs/development-plugin.md.

- The explorer does not check at run time that a support keeps them, by design.
- Tests keep the rules true of the defaults, so the examples AI learns from stay right.

### Known limits

These follow from the choices above. Users may meet them.

- **One job at a time.** A kernel runs file operations one after another, so a long copy delays a delete. Properties
  run apart.
- **Copies between storages go through the kernel.** Bandwidth is the kernel's. Files stream through its memory, not
  its disk.
- **Synchronous filesystems copy one file at a time.** Only async filesystems, such as s3fs and adlfs, run files in
  parallel.
- **A click may show a file as it was up to 5 seconds before.** The detection is reused for a few seconds. Refresh
  and the explorer's own writes clear it.
- **Listing a folder holds the kernel.** Previews, the data browser and clicks load in worker threads, but a listing
  runs on the main thread: a slow one delays the explorer's other answers.
- **Kernels sharing a states file do not lock it.** Each re-reads the file before a change and replaces it atomically.
  Two changes in the same instant can still lose one.

## Architecture

- **`StorageExplorer`** holds the widget's state and routes the frontend's messages. Each of its features is a mixin,
  in `_explorer/`.
- **Its frontend** is a JavaScript file per feature, in `static/storage_explorer/`. The kernel joins them into one
  module.
- **Storages** are fsspec filesystems. Locations say where their files are, independently of fsspec. Mappers, in
  `filesystems/`, make them.
- **File operations** are planned by `FileTasks` and run as jobs in a worker thread, both in `_jobs/`. A chain of
  `FileSystemOperations` objects does the work, and users can extend it.
- **The data browser** is `DataQuery`, in `_query/`. It works on any dataframe narwhals supports. `DataExplorer` shows
  it alone.
- **Formats**, in `formats/`, detect each kind of file. Supports preview, query and load it, one library each.
- **The launcher** opens explorers in JupyterLab's tabs and side bar, with the settings of `launcher.py` files.

The sections below describe each part.

### Widgets

The widgets are `anywidget.AnyWidget` subclasses:

- `StorageExplorer`, in `storage_explorer.py`;
- `DataExplorer`, in `data_explorer.py`;
- `ViewTab` and `TableSetTab`, private, which "View in a new tab" opens.

They talk to the frontend in two ways:

- **Traits** hold the state shared with the browser: `traitlets` tagged `sync=True`. Their names start with an
  underscore, as a public trait would be public API.
- **Custom messages** carry everything else. `_on_custom_msg` dispatches them by their `type`.

A message is a request or a notice:

- A **request** carries an id, `rid`. Its answer is a message of type `"reply"` with the same `rid`.
- A **notice** gets no answer, and its effects show in the traits. The exception is "download", answered by a message
  per file with the file's bytes attached.

Most requests are answered at once, by their handler in `_requests()`. Those that read data are answered by a load
later (see "Loading views"): the data browser's, and the right-click menu's. "view_tab" is answered at once, then
followed by a "view_tab" message once its view has loaded.

Uploads carry the pieces of files in the messages' binary buffers. Values sent go through `_json.jsonable`.

A failed request's reply is `{"error": text}`. For the explorer's own refusals, which are `ValueError`s, the text
leaves out the exception's type. File operations reply with a list instead, `{"errors": [...]}`, as jobs do.

Users' callbacks are kept in `_callbacks.Callbacks`. The widget compares what it shows with what they last heard of, so
each is called once per change.

- `on_change` hears of the storage, the folder and the selection, from the traits' observers.
- `StorageExplorer.on_query_change` hears of the query in the preview panel and of its result settings. It is called
  after the data browser's replies and when the preview changes, but not while a preview loads.

`StorageExplorer` itself keeps:

- its state, set up in `__init__`;
- the routing of the messages;
- the traits' observers, which must be on the class itself;
- the locations of paths: `_location_of`, `_url`, and `_location_reply` for the frontend;
- the only calls to fsspec on the storage shown, in its last block, *File operations*.

Its features are mixins in `_explorer/`, listed before `AnyWidget` in its bases. They hold only methods. What they
share is in `_explorer/common.py`.

| Mixin                  | File            | Feature                                                                  |
|------------------------|-----------------|--------------------------------------------------------------------------|
| `FoldersMixin`         | `folders.py`    | The list and the tree.                                                   |
| `PreviewsMixin`        | `previews.py`   | Previews, the data browser, view tabs, and the formats in the menu.      |
| `BookmarksMixin`       | `bookmarks.py`  | Bookmarks.                                                               |
| `JupyterLabFilesMixin` | `jupyterlab.py` | Files opened in JupyterLab's editors.                                    |
| `JobsMixin`            | `jobs.py`       | Running file operations as jobs, and showing what they change.           |
| `FileRequestsMixin`    | `requests.py`   | The requests for file operations.                                        |
| `AboutMixin`           | `about.py`      | The settings menu's About: the versions of the explorer and the plugins. |

### Frontend

The frontend is plain ES modules in `static/`, with no bundler. anywidget cannot import neighbouring files, so the
kernel joins each widget's files into one module (`_static.esm`), in this order:

1. the shared files: `icons.js`, `common.js`, `query.js` for the data browser, and `sections.js` for views;
2. the widget's parts, the files of `static/<widget>/`, if any;
3. the widget's own file, `<widget>.js`, with `render` and the export.

All but the last only define functions and constants. The CSS is joined the same way, without parts.

The storage explorer's parts are in `static/storage_explorer/`, one feature each:

- `tree.js`, `list.js` and `preview.js`;
- `item_menu.js`, the right-click menu, and `shortcuts.js`, the list's keys;
- `operations.js`, with the clipboard;
- `transfers.js`: drag and drop, uploads and downloads;
- `jupyterlab.js`, `properties.js` and `jobs.js`;
- `toolbar.js`, with unsafe mode and bookmarks;
- `engine.js`, the engine chosen, and `about.js`, the settings menu's About;
- `overlays.js`, for the busy screen, dialogs and menus, and `util.js`.

Each part is a function `createX(x)` returning its elements and functions. `x` is the explorer, made in `render()`. It
holds what the features share, such as `model`, `request` and `navigate`. It also holds the features themselves, such
as `x.list`. A feature uses another when needed, not when made, so their order rarely matters.

Third-party code is vendored in `static/vendor/`. The kernel sends it when the frontend asks, e.g. marked for Markdown
views.

Two rules keep the frontend working:

- File names, paths and messages naming files are shown through `visible()`, in `common.js`. It shows control, bidi
  and invisible characters as `\uXXXX`.
- anywidget's `model` has only `get`, `set`, `save_changes`, `on`, `off` and `send`. Backbone methods such as
  `previous()` throw inside `set`, which silently breaks syncing.

Errors are made readable in two places:

- **In the kernel**, `error_text` puts a line saying what went wrong first. For Spark's errors, that is the Java
  exception, not the call that failed.
- **In the frontend**, `errorBlock`, in `common.js`, shows that first line, and the rest, such as a Java stack trace,
  under "Details". The launcher extension's view tabs show their errors the same way.

`x.flash(message)` shows a notice in the status bar for 1.5 seconds. With `{ error: true }`, the message stays until
clicked or replaced: an error may come long after the action, e.g. a job's. A job's result with failures is flashed
that way, with `resultFailed`.

### The launcher

The launcher, in `launcher/`, adds a JupyterLab launcher item. It opens a tab whose kernel runs `launch()`.

`launch()` merges every `storage-explorer/launcher.py` in Jupyter's configuration paths, as layers from system to
user. `load_settings` does the merging. Each file may define these functions:

- `filesystems()`, `operations()`, `filesystem_mappers()` and `transfer_policy()`;
- `plugin_options()`, merged by plugin, then option;
- `supports()`, and `engine_options()`, merged by engine, format, then option;
- `parameters()`, the explorer's other arguments;
- `final()`, which names what later layers cannot change.

The retired `style()` and `formats()` are ignored with a warning.

Errors are handled by whose file has them:

- **The user's file** is left out, with a warning above the explorer and in its status bar, so that "Edit
  configuration" can fix it. `load_settings` reads and checks each layer before applying it, so a bad file changes
  nothing.
- **Values the explorer refuses** show only when it is created. `_create_explorer` then creates it again without the
  user's file.
- **Another file's error**, or an explorer that cannot be created even then, stops the tab. `launch()` prints the error
  alone, without a traceback.

The settings menu, ⚙, is on every explorer. Its "About" shows the versions of the explorer and of the plugins
installed, with plugins not loaded greyed out and why. Its icon, `static/storage-explorer.svg`, is a copy of the
launcher's, which a test keeps the same.

In a launcher tab, the menu also has "Edit configuration". It opens the user's `launcher.py` in JupyterLab's editor.

- If the file is missing, it is created from `launcher_template.py`, once the user confirms.
- It is read and written through the explorer's kernel. `~/.jupyter` is hidden, so JupyterLab's own contents API
  would refuse it.
- Notebooks never offer it.

#### The JupyterLab extension

The extension has four plugins:

| Plugin         | Does                                                                                   |
|----------------|----------------------------------------------------------------------------------------|
| `index.ts`     | The tab, a console, and the side panel.                                                |
| `download.ts`  | Downloads items dropped onto JupyterLab's file browser to the Jupyter server.           |
| `files.ts`     | "Open in JupyterLab": a drive serving the files explorers opened.                       |
| `queryTabs.ts` | "View in a new tab".                                                                   |

**The tab.** ipywidgets binds a console's widgets to its first kernel. So a tab whose session is lost, or whose kernel
changes or restarts, is replaced by a new tab.

Each tab's view, its storage and folders, is restored with the workspace:

1. The explorer reports it as a bubbling `"jupyter-storage-explorer:view"` DOM event.
2. The tab keeps it in JupyterLab's state database, which is saved with the workspace.
3. A restored tab passes it back as `launch(view=...)`.

A page reload keeps the tab's kernel, and runs `launch()` in it again. `launch()` then shows the explorer it made
before, as it was: its folder, selection and preview. It makes a new one only if the `launcher.py` files changed, so
that a reload still applies new settings, or if the explorer was closed. The view tabs it had went with the page, so
their widgets are released. The side panel's console works the same way. The saved view serves new kernels, e.g.
after a server restart.

**The side panel** holds such a console too, under a session name of its own. The command "Show Storage Explorer in
the Side Bar" shows it.

- Its console is made by `console:create` when the panel is first shown, for ipywidgets' widget manager. Then it is
  moved into the panel.
- Restored consoles of that name are moved back in, once JupyterLab is restored.
- It runs `launch(sidebar=True)`: the sidebar layout, without the tree or the preview panel.

**Open in JupyterLab.** `files.ts` is a JupyterLab drive, `StorageExplorer:<storage>/<path>`, not shown in the file
browser.

- It serves only the files explorers opened on the page. Typed paths, new files and renames are refused.
- Files are read and saved through the explorer's kernel, with contents models from `_explorer/jupyterlab_files.py`.
- Their hash lets JupyterLab detect changes made elsewhere before saving.
- Notebooks are trusted as jupyter_server trusts them, with nbformat's notary in the kernel. Tests get their own
  `JUPYTER_DATA_DIR`.

**View in a new tab.** The kernel answers at once with a load id, and the tab opens showing "Loading…". The kernel
reads the view in a worker thread, as a preview's (see "Loading views"). It then sends a "view_tab" message with
the model id of a widget of the view, or the error, which the tab shows. The widget is:

- a `DataExplorer` of the same query, for a `QueryView`;
- a `TableSetTab`, for a `TableSetView`;
- else a `ViewTab`, which renders the view's section with the shared `sections.js`.

Closing the tab while the view loads cancels the load. The explorer keeps the widget until its tab closes.

The tab renders the widget with the output renderers of the notebook or console holding the explorer, as ipywidgets
ties widgets to that kernel connection. The tab closes with the explorer or a kernel restart.

### Storages

Every storage is an fsspec filesystem. A `StorageExplorer` can hold several, by name.

#### Why locations and mappers

A URL does not always say where a file is. `s3://sales/orders.parquet` names a bucket and a key, but not the server.
AWS, a MinIO server and another S3-compatible store can each have a bucket named "sales". So the same URL can name
different files on different servers.

Software working with one storage service at a time can ignore this. Storage Explorer cannot, as it is built to reach
several storage services at once.

What the URL leaves out is held by the client. An fsspec filesystem knows its S3 endpoint, or its Azure account, from
its settings.

Storage Explorer handles this with two classes:

- A `Location` names a file or folder uniquely across storage services. An `S3Location` holds the endpoint besides the
  bucket and the key, for example. Its `url` is the URL in its usual form, for libraries and users.
- A `FileSystemMapper` maps between locations and an fsspec filesystem with its paths. It gives a path's location, and
  the path of a location in a filesystem, if that filesystem reaches it.

#### Locations

A `Location`, in `location.py`, says where an item is, independently of fsspec's implementations. So it can travel to
other kernels, and to libraries that do their own I/O.

- It is a frozen, keyword-only dataclass.
- It is normalized when made: hosts and accounts in lower case, endpoints as origins, no trailing "/". So equal
  locations name the same item, and can be dict keys.
- Whether the item is a folder is not part of it.
- A subclass gives only its fields, its `kind` and its `url`. The URL is the common form, which the fsspec
  implementation also reads.
- `to_json()` gives `{"kind", "url", ...fields}`, and `Location.from_json()` reads it back. Subclasses register by
  `kind`.
- An unknown kind is read as an `FsspecLocation`. For known kinds, the URL in the JSON is ignored.

A location does not say which storage it is on. What one fsspec instance reaches depends on the implementation: an
adlfs instance reaches all of an account's containers. Only mappers can tell.

The predefined locations are in `filesystems/locations.py`:

| Location         | Fields                                     | URL                                                  |
|------------------|--------------------------------------------|------------------------------------------------------|
| `AbfsLocation`   | Account, container, path, endpoint suffix. | `abfs://container@account.dfs.core.windows.net/path` |
| `S3Location`     | Bucket, key, endpoint or AWS partition.    | `s3://bucket/key`                                    |
| `GcsLocation`    | Bucket, key, endpoint.                     | `gs://bucket/key`                                    |
| `SftpLocation`   | Host, port, user, path.                    | `sftp://user@host:port/path`                         |
| `LocalLocation`  | Path, host name, machine id.               | `file:///path`                                       |
| `MemoryLocation` | Path, process.                             | `memory://path`                                      |
| `FsspecLocation` | URL.                                       | fsspec's URL, for filesystems no mapper knows.       |

With an emulator, an `AbfsLocation`'s URL is adlfs's own form, `abfs://container/path`. A `LocalLocation`'s `path` is
fsspec's, such as "C:/x" on Windows, and its `os_path` is the system's.

#### Mappers

A `FileSystemMapper`, in `filesystems/mapper.py`, maps the paths of one fsspec implementation:

- `to_location(fs, path)` gives a path's location, without credentials. "" gives the top folder. None means the item
  has no location.
- `path_of(fs, location)` is the reverse. It gives None unless `fs` reaches the location, which the mapper decides from
  the location's fields and the instance's settings.
- `level(fs, path)` says what the storage makes of a folder, such as "container". It gives the folder's row its
  `data-fs-level`.
- `css` is how the explorer shows the mapper's storages, e.g. the icons of its levels and its colour.

By default, `level` reads `levels`, a name per depth from the top folder, e.g. adlfs's `("account", "container")`.
The explorer sends each folder's level with the tree and the listing.

The explorer sends its storages' mappers' CSS, each nested in `:where(.jse-browser[data-fs-mapper="<class>"])`, which
adds no weight to its selectors. It sets `data-fs-mapper` to the mapper of the storage shown. The frontend puts each
mapper's CSS on the page once, in a `<style>` of its own (`mapper_css.js`).

- `level_icon_css`, in `filesystems/level_icons.py`, writes icons as masks in the storage's colour. That module has
  the predefined mappers' icons.
- Filesystem-specific CSS belongs in its mapper, never in `static/`.

A mapper matches filesystems by the qualified names of their classes and bases. So optional packages are never
imported. Tests fake s3fs, gcsfs, SFTP and Databricks classes by setting their `__module__`.

Locations are defined per kind of storage, not per implementation. So the mappers of fsspec's SFTP and of sshfs give
the same `SftpLocation`s.

The predefined mappers are in `filesystems/mappers.py`: Azure, S3, GCS, local, memory, SFTP, sshfs and Databricks.
`DatabricksMapper` maps both fsspec-databricks and fsspec's own DBFS, with URLs `dbfs://Volumes/...`. pyspark-support's
`spark_url` turns those into Databricks' `dbfs:/Volumes/...`.

#### The mapper chain

An explorer asks its mappers through a `MapperChain`. The chain has the explorer's `filesystem_mappers`, then the
defaults, and it falls back to `FsspecMapper`.

- `location_of(fs, path)` and `level_of(fs, path)` ask the filesystem's mapper.
- `path_in(fs, location)` gives the location's path in `fs`, or None.
- `same_filesystem(a, b)` tells whether each reaches the other's top folder. So the same storage opened with other
  credentials is one. Filesystems no mapper knows are compared as fsspec does.
- `locate(location, filesystems)` finds files pasted from another kernel. See below.

`DirFileSystem`s are not mapped. The chain unwraps them, so their locations are those of the filesystem they wrap.
`same_filesystem` also compares their folders.

`locate` tries the explorer's storages in order, and takes the first that reaches the location. Otherwise, it opens a
filesystem from the location's URL, with the user's credentials, and checks that this one reaches it. Else it refuses.
So another kernel's memory or another machine's disk is never read.

`locate` never opens an `FsspecLocation`'s URL, as nothing tells which storage such a URL is on. Otherwise a dropped
URL could make the kernel connect anywhere.

File operations need to know whether two filesystems are the same. `FileTasks` passes the explorer's chain to `move`
and `copy`, as their keyword `same`.

### File operations

`StorageExplorer` lists, reads and writes the storage shown through its own methods only, such as `_ls` and
`_read_bytes`. They are the last block of the class, *File operations*.

Moving, copying, deleting, downloading and creating folders go through operations objects instead, in
`filesystems/operation.py`. They form a chain of `FileSystemOperations`:

- Each method is tried on each object in order, until one does not raise `FileSystemOperations.NotSupported`.
- A library's own `NotImplementedError` is an error, not a refusal. That is why the chain has an exception of its own.
- The explorer's `operations=` come first, then the plugins', then `StorageExplorer.default_operations()`.

The default operations, in `filesystems/operations.py`:

| Operations              | Does                                                                                     |
|-------------------------|------------------------------------------------------------------------------------------|
| `AtomicMoveOperation`   | Moves within a filesystem whose `mv` renames a folder in one step: local and memory.     |
| `AsyncFsspecOperations` | Everything on async filesystems, such as s3fs, with up to 32 files running at a time.    |
| `FsspecOperations`      | Everything else, one file at a time.                                                     |

`AtomicMoveOperation` also takes a `DirFileSystem` over local or memory filesystems. The other two walk folders
themselves, moves included, so that they can report progress file by file. Their shared helpers are in
`filesystems/_common.py`.

`move` and `copy` take a source and a target filesystem, the same one or not. Between filesystems, each file goes
through `_copy_file` and `_move_file`, which subclasses can override.

- By default, a copy goes through the kernel's memory, in `filesystems/_streaming.py`.
- A move copies, then deletes each file, so a cancel leaves each file in one place.
- The async class has `_copy_file_async` and `_move_file_async` instead.

A file up to 8 MiB is read whole, then written in one call. A larger one streams: a thread reads the next blocks while
the last is written, so reading and writing overlap. The async class streams in a few threads at a time, which bounds
the memory used.

A failed or cancelled stream leaves no partial file:

- On object stores, the file is never completed. Its last part is not sent, and the parts sent are discarded.
- On other storages, such as local disks, the file written is deleted.
- A file the copy was replacing is never deleted. Object stores keep it until a write completes, but on a local disk
  it is spoiled.

After a stream, the target's size is checked against the bytes written. A storage whose writable files lose bytes
then fails the copy, instead of losing them silently. fsspec's `AsyncFileSystemWrapper` has such files, so streams
use the filesystem it wraps.

A folder copy is refused before anything is written if a file's path in it has `.` or `..` parts. Object stores keep
such keys, and on a local disk they would land outside the target folder.

Object stores, such as S3 and GCS, have no empty folders. That matters when creating folders.

databricks-support, in `plugins/databricks-support`, adds `DatabricksWorkspaceMapper`, for fsspec-databricks'
filesystems. Its `DatabricksLocation`s keep the workspace's host besides the path, so that workspaces are told apart and
files pasted from another kernel are found in theirs. The host is the filesystem's Databricks SDK configuration's,
which fsspec-databricks makes once. The mapper does not subclass `DatabricksMapper`: the chain takes `FsspecMapper` subclasses to know
nothing of what an instance reaches. The plugin is experimental, as fsspec-databricks is, and stays out of `all` and
`all-supports`.

abfs-support adds `AzureDataLakeGen2Operation`, in `plugins/abfs-support`. On accounts with a hierarchical namespace,
it renames and creates folders with the Data Lake SDK. Within an account, it copies on the server with Copy Blob. Its
tests fake the SDK and adlfs, which the plugin imports on first use.

Tests use fsspec's `AsyncFileSystemWrapper` around a memory filesystem as an async filesystem.

### Jobs

These run in the background, as jobs:

- move, rename, delete and paste;
- uploads, from JupyterLab's file browser or from the user's computer;
- both downloads to JupyterLab.

A job goes through three steps:

1. **Planning**, on the main thread: a `FileTasks` method, in `_jobs/tasks.py`, checks the request without the widget.
   It returns the conflicts to ask the user about, or a `Task`.
2. **Work**, in the worker thread of a `JobRunner`, in `_jobs/runner.py`: the task's `work(progress)`. The runner runs
   one job at a time. The task records what it changes as each item is done.
3. **Showing the changes**, on the main thread: `JobsMixin` follows them as the job goes, and shows them all once it
   ends.

While the job goes, items gone are dropped from the list and the tree without listing, at most once a second. Folders
with new items are listed again, at most every 3 seconds, keeping the selection.

Work functions must not touch traits or call `send`. They report to the `Progress`, and stop when `progress.check()`
raises `OperationCancelled`.

The public `Progress`, in `filesystems/operation.py`, has only what operations use. The runner's `JobProgress`, in
`_jobs/progress.py`, adds the job's bookkeeping, such as totals, items and cancelling.

The main thread is reached through the kernel's asyncio loop. Without a running loop, as in tests, jobs run at once, so
tests see their result immediately.

A request answers `{"job": id}`. The kernel then sends `{"type": "job", ...}` messages as the job runs, and one with the
result when it ends. The frontend's `x.jobs.result()` waits for that one.

Uploads come in two kinds:

- A drop from JupyterLab's file browser is a copy from the kernel's local disk: `FileTasks.upload`.
- Files from the user's computer arrive in pieces, in `_jobs/incoming.py`. The last piece starts
  `FileTasks.upload_file`.

### Properties

Properties of one file are its fsspec info, answered at once. For folders or several items, `FileTasks.properties`
adds up the operations' `measure` of each item, as a job.

That job runs on a `JobRunner` of its own, so it never waits for a move. The frontend shows it in a dialog with
Cancel, not with the jobs above the status bar. It is not an operation, so it does not turn off unsafe mode.

`FileSystemOperations.measure` returns a `Measurement`: files, bytes, folders, oldest and newest files, errors, and
whether it is complete. The defaults measure in two ways:

- Without a `Progress`, for a job's progress bar, they make one recursive `find`.
- With one, they list folder by folder, reporting the files found. Unlistable folders go in `errors`. A cancel returns
  what was found, not complete.

They do not use `fs.walk`, whose `on_error` misses subfolders.

### Unsafe mode

Folder operations are offered only while the toolbar's "Unsafe mode" slider is on. They are move, copy, cut and paste,
rename and delete.

- In the frontend, every operation calls `x.unsafe.take()` as it starts, which turns the mode off. So it allows one
  operation at a time.
- The request says whether the mode was on, and the kernel refuses folders without it.

That is `unsafe_mode="on_demand"`, the default. With `"always"` or `"blocked"`, the slider is hidden. The kernel then
decides from the argument, kept apart from the traits, which the page could set: folders are always allowed, or never.
The frontend's `x.unsafe` follows `_unsafe_policy` for what it offers and says.

### Transfer policy

A `TransferPolicy`, in `_jobs/transfer_policy.py`, applies to every copy and move. That includes those within a
filesystem.

- Its rules are tried in order. The first whose `src` and `dest` patterns both match decides.
- A rule's patterns must have the same named groups, and they must capture the same text on both sides.
- Without a matching rule, the transfer is allowed.

The kernel checks it per item, as it plans. Refused items become errors, and the others go on.

The policy compares URLs: the item's location's, else fsspec's. Files pasted keep the URL of the location they were
copied with. Two other sides have URLs of their own:

- the user's computer, `browser:///<name>`;
- JupyterLab's file browser, `jupyterlab://<absolute path>`, unlike the explorer's own local storage, `file:///`.

The policy prevents mistakes. It is not a security boundary.

### Layout

Three options of `StorageExplorer` set its layout. Each has a private trait of the same name, e.g. `_tree_view`.

- `tree_view`: "open" or "closed", which the toolbar's tree button switches. "disabled" removes the tree for good.
- `preview_panel`: "open" or "closed", or "disabled". Without the panel, items are viewed in new tabs, and the Preview
  button becomes View.
- `layout`: "standard", or "sidebar" for JupyterLab's side bar, a narrow layout described below.

The sidebar layout, with the class `jse-sidebar`, has:

- a bar of the storage chooser, bookmarks, Refresh, the filter button and ⚙;
- a bar of Up and the path;
- the filter, hidden until its button shows it, as in JupyterLab's file browser;
- the list, and its pager.

In the sidebar, ⚙'s menu has Unsafe mode first, and the button turns red while it is on.

The list's columns besides Name are chosen in ⚙ → Columns: Size, Modified, Created and Format. They are remembered by
layout. The defaults are Size and Modified, and the sidebar's is Size.

In the other layouts, the storage chooser sits above the tree while the tree shows. Otherwise it comes first in the
list's bar.

### Between explorers and with JupyterLab

Explorers on a page may be in different kernels, one per notebook. They share objects under `Symbol.for(...)` keys on
`globalThis`:

| Key                                      | Holds                                                                       |
|------------------------------------------|-----------------------------------------------------------------------------|
| `"jupyter-storage-explorer.clipboard"`   | Items copied or cut, for Paste in any explorer.                             |
| `"jupyter-storage-explorer.drag"`        | The drag of items running, from its start to its end.                       |
| `"jupyter-storage-explorer.explorers"`   | The explorers on the page by id, each with its `download`.                  |
| `"jupyter-storage-explorer.jupyterlab"`  | The launcher extension's functions, such as `open` and `openViewTab`.       |

The explorer offers "Open in JupyterLab" and "View in a new tab" only when the launcher extension's functions are there.
The extension's `download.ts` calls an explorer's `download` on a drop onto JupyterLab's file browser.

A drag of items carries one type, `application/x-jupyter-storage-explorer-items`. Its value is a random id, and nothing
else.

- The drag itself is kept in the page, and a drop is taken only if it carries that id. So drags from other tabs,
  windows or sites can never name files.
- A drop on the same explorer moves the items. A drop on another explorer of the page copies them, as Paste does.

The clipboard names the explorer and the storage copied from, and each file's path and location. Paste finds the files
in one of two ways:

- An explorer of the same kernel is found in the registry of explorers, and its filesystem object is used as it is.
- Otherwise, the files' locations are found with `MapperChain.locate`.

Copy also puts the items on the system clipboard: local items' plain paths, and other items' URLs. "Copy path" is
offered on local storages.

After pasting files cut in another explorer, the frontend dispatches a `"jupyter-storage-explorer:changed"` event on
`globalThis`. That explorer then asks its kernel to show what is left.

### States

An `ExplorerStates`, in `_explorer/states.py`, keeps what explorers remember:

- bookmarks: the storage name, the folder, and its location when bookmarked;
- the data browser's queries, by location: settings, and the mode chosen;
- the engine chosen, and the list's columns by layout.

Queries are kept most recent first, at most `max_queries`. `DataQuery` remembers through the states, and
`DataExplorer` has a private one.

The kernel's explorers share one in memory, unless `states=` gives another or a file's path. With a path, it is a JSON
file shared with other kernels: each launcher tab is a kernel. The launcher's file is
`<jupyter_config_dir>/storage-explorer/states.json`.

Kernels sharing a file must not undo each other's changes:

- The file is read again when an explorer is created, and before each change. Then it is written whole.
- A file that cannot be read is never written over.
- The frontend asks for the bookmarks each time their menu opens, as other kernels may have changed them.

Older entries have a URL only, without a location. They still match a location of that URL or plain path, and are
rewritten with the location at their next change.

### Lists

The browser filters, sorts and pages the file list, 100 items per page, from the full listing the kernel sends. The
selection survives filtering and paging.

Folders can hold tens of thousands of items, so the listing is sent as columns, without paths or URLs.

- The frontend joins the paths itself.
- It asks for locations only when it needs them: to copy, and for tooltips.
- It sorts once per listing, not per keystroke.

Folders of more than `max_browser_items`, 20,000 by default, are handled by the kernel instead, in
`_explorer/listing.py`. The kernel then sends only their size and a version, and the frontend asks for pages. While it
waits, it filters the rows shown.

The kernel's sorting and filters follow the browser's as closely as Python allows: natural order ignoring case and
accents, and Python's `re`.

The list's filter and the one in *Select columns* use `createFilter` in `common.js`. A filter is text or a
regular expression, always case-insensitive.

The list's filter is cleared when another folder's listing arrives, not on the click. So the previous folder's items
never show unfiltered.

### Formats

A format only detects files. A support handles one format's data with one library. So a library is added to a format,
e.g. DuckDB for Parquet, without touching the format.
[development-plugin.md](docs/development-plugin.md) says how to write each, with their rules.

`formats/` is laid out as `filesystems/`:

| Module                          | Contents                                                                         |
|---------------------------------|----------------------------------------------------------------------------------|
| `base.py`                       | `DataFormat`, `ItemContext`, the file icons, and the explorer's `detect`.        |
| `support.py`                    | `FormatSupport`, its options, and the helpers of the generated code.             |
| `engine.py`                     | `Engine`: a library users choose, such as polars.                                |
| `package.py`, `packages.py`     | `PythonPackage`: what a support needs, and the packages several engines share.   |
| `view.py`                       | The views supports return, and `ViewLimits`.                                     |
| `delta.py`, `parquet.py`, ...   | A module per predefined format.                                                  |
| `supports/python.py`            | The core's supports, without an engine: text, JSON, Markdown, images.            |
| `defaults.py`                   | `DEFAULT_FORMATS` and `DEFAULT_SUPPORTS`.                                        |

The engines' supports are in their plugins, in `plugins/<engine>-support/src/.../supports.py`. They import their
libraries only inside methods, through `PythonPackage.load()`.

`formats` never imports `_explorer`. Presentation, such as the wording of a table's row counts, stays in the explorer.

#### Detection

A `DataFormat` declares its name, label, priority, extensions and file icon. Its `matches(ctx)` is cheap: it is called
on every click and for every file listed, and reads nothing.

`ctx` is an `ItemContext`. It is one frozen dataclass rather than parameters, so it can grow without changing
signatures. It has:

- the item's location, the explorer's filesystem, and the item's path there;
- its fsspec info, and a folder's listing as `children`;
- methods reading the item: `head`, `head_text` and `read_whole`.

Formats with a binary signature also declare `sniff_bytes` and `sniff(ctx, head)`.

- `detect` reads a file's first bytes once for all the formats sniffing it, and drops those refusing it.
- It does so whichever plugins are installed: the files in a storage need not be what the plugins expect.
- Listings skip sniffing, so such files have no format until clicked. Folders are never sniffed.

The highest priority wins: Delta 20, Parquet 10, others 0, and Text -10. What supports share about a format is on it,
such as `Csv.separator` or `Parquet.data_url`.

Directory formats, Delta and Parquet datasets, inspect the folder's listing. Parquet also takes Hive-style partition
folders, such as `year=…/month=…/`. It follows them down one branch, one more listing per partition column, and keeps
each dataset's layout by location for the supports.

A format's file icon is one of JupyterLab's, or an SVG of its own shown as an image, so its scripts never run. Files of
a format without an icon get their extension's.

#### Supports

A `FormatSupport` declares:

- `format`, matched with `isinstance`, so subclasses too;
- `engine`, an `Engine` class, or None for the built-in views;
- `additional_requirements`, packages besides the engine's.

It implements `view`, `recipe` or both. Its `supports(fmt, ctx, options, task)` tells whether it does a task for an
item, with its options for that item:

- By default, it does what its class implements, for every item.
- A support overrides it to refuse items, such as a storage its library cannot read.
- It decides without reading the storage, as it runs on the main thread for each item clicked.

Once a support accepts an item, the chain tries no other. What its method raises is shown as the item's error, so a
failure is never hidden by another library's view. Without an item, as for the engines offered, the chain asks
`implements(task)`.

Each method gets the format object, then the `ItemContext`, then the support's options. `view` also gets the
`ViewLimits`.

Supports never check their packages: the chain calls only installed ones. They take no `__init__` arguments.

#### The support chain

The explorer's `SupportChain`, in `_explorer/supports.py`, holds its supports in order:

1. the explorer's `supports=`;
2. the plugins' supports;
3. `DEFAULT_SUPPORTS`, the core's.

Its formats are an object of each support's format, in that order, then the plugins' own formats and the defaults.
The explorer has no `formats=` argument. Two format classes of one name are a `ValueError`, as two engine classes of
one key are.

The chain answers:

- `of(fmt, ctx, task)`: the installed supports of a format that support a task for the item;
- `engines`: the installed engines with a view support, the preferred first;
- `viewers(fmt, ctx)`: the engines that can view the item, then None for the built-in views;
- `engine_for(fmt, ctx, engine)`: the engine chosen if it handles the format, else the built-in views;
- `view(...)`, with the first of one engine's supports;
- `recipes(...)`: the first support of each library for the item, as for views.

`engine_for` never falls back to another engine. It raises `LookupError` in two cases:

- the chosen engine's support is not installed;
- its support refuses the item.

A support whose `recipe` fails gives a recipe holding the error. "Python code" shows it in place of that library's code,
and the others' code still shows.

#### Views

`view` returns one `View`, from `view.py`:

- A `QueryView` opens the data browser. Its `data` is any dataframe narwhals supports, best lazy. `more` says the data
  holds only the item's first part:
  - eager data of the first rows, such as pandas' `max_memory_rows`, counted as rows in memory are;
  - lazy data of a file's first bytes, which the browser notes in either mode (`partial`).
- A `TableSetView` offers several tables, such as Excel's sheets, on a tree or on tabs. Choosing one opens the data
  browser on it.
- A `ViewWithPrompt` asks the user first: `ViewWithConfirmation`, `ViewWithChoice` or `ViewWithInput`.
- The others, `TableView`, `TextView`, `TreeView`, `MarkdownView` and `MediaView`, are sent to the frontend as a
  section, which it renders by kind.

A prompt is a section too, without its function or a choice's values: the frontend answers with a label. Where it is
shown:

- In the preview panel, the answer comes back as "preview_answer". The view of it is read as a preview.
- In a view tab, the prompt is a `ViewTab` sent with "asking". The tab keeps waiting, then shows the view's widget
  instead and lets the prompt's go. The prompt's widget shows a later error or prompt.

Each prompt shown has an id, and an answer to one no longer shown is ignored. The answers are kept by the item's viewer,
`_Viewer` in `_explorer/previews.py`. A reload gives them to the prompts again, so it asks nothing. A prompt is closed
with the view of its answer, or when cancelled.

Whether an item opens in the data browser is known only once viewed. So the menu offers "Preview" and "View in a new
tab" for anything with a format.

A reload views the item again, with a context read again without fsspec's cache. If its format no longer matches, the
reload is an error.

Functions given to a view's `on_close` are called once, when the explorer no longer shows the view:

- another preview replaces it, the panel closes, or the storage changes;
- its view tab closes;
- the explorer closes, or the kernel exits.

A `QueryView`'s `DataQuery` owns it. A reload's view replaces it, and the previous one is closed.

#### Local copies

Libraries that open only local files, such as DuckDB for its databases, view a local copy. `LocalFileCache`, in
`formats/local_files.py`, keeps them, and `local_file_cache()` is the kernel's:

- A copy is keyed by the item's location, and downloaded whole by `get` with the explorer's filesystem.
- It stays valid while the remote file's modification time and size, from the item's info, are the same.
- `get` counts a user, and `release` releases one. An unused copy is deleted after the delay given, by a timer,
  unless `get` takes it again first.
- A copy replaced while still used is kept until it can be deleted, at the latest at exit.
- The copies live in a temporary folder of the kernel's, removed at exit.

A local file is its own copy, so nothing is downloaded.

#### Loading views

A preview's reads can take minutes, e.g. while a Spark session starts. So they run in a worker thread of a `Loader`, in
`_jobs/loader.py`:

1. On the main thread, the panel is set to "loading". What the reads need of the explorer is taken now: the storage
   shown and the engine chosen.
2. In the worker: the item's detection, shared with the click's (see below), then `view`, then the data browser's
   query or tables. A `DataQuery` reads its first rows when it is made, so it is made here.
3. On the main thread: the previous preview is closed, and the new one shown, or its error.

Loads run apart from jobs, up to 8 at a time in the kernel. Their work must not touch traits or call `send`, as jobs'
work. Another preview, closing the panel or another storage cancels a load: what it read is closed instead of shown.
Without a running loop, as in tests, loads run at once.

View tabs load the same way.

The data browser's requests may read the data too, e.g. a Spark job for each page. They run as loads in the lane of
their `DataQuery` or `TableSet`:

- Loads of one lane run one at a time, in order, as a query is not safe to use from two threads at once.
- Lanes of other data run side by side.
- Closing a query or table set goes through its lane, after the requests still reading it.
- The reply is sent on the main thread, then `on_change` and `on_query_change` functions are told.

This holds in the preview panel, in view tabs and in a `DataExplorer` of its own.

A click asks for the item's detection three times at once: for the selection's Preview button, for the right-click
menu, and for the preview. `_detection` gives each a future of the same detection, run as a load:

- A detection still running for the item is shared, and the last one is kept for 5 seconds.
- The selection's load waits for it, then sets the format on the main thread. A later selection cancels it.
- The menu's load also builds the recipes, which may read the file.

Listing folders still runs on the main thread.

`PythonPackage.is_installed` probes one package at a time. Two threads clearing the import caches at once can raise a
`KeyError` in one of them.

#### The data browser

`DataQuery`, in `_query/data_query.py`, filters, sorts and pages as narwhals expressions. It works in one of two modes:

- **Live**, on the data itself.
- **In memory**, on rows read into memory. They are queried in the data's own library: eager data as it is, lazy data
  in the library narwhals collects it into, e.g. PyArrow for DuckDB and Spark.

So behaviour such as regular expressions follows the data's library. The core needs no engine: polars is optional.

Every read of lazy data, the first rows when opening and each live page, goes through `DataQuery._read`. It asks, in
order, until one gives rows:

1. the explorer's `fetch_rows`, the user's;
2. the `fetch` of the `QueryView` the data came from, a support's, asked at each read, as a reload's view may differ;
3. `fetch_rows`, the default: polars and DuckDB skip rows themselves, and Dask is read partition by partition, as
   narwhals' `head` would read every partition. Others read all rows up to `offset + length`.

`ViewLimits` sets the browser's page size, `max_display_rows`, and its limits for live and memory modes.

#### Recipes

`recipe` returns the code of "Python code", by title, such as "Load as LazyFrame". The code runs as it is in a new
notebook, with its imports and, for Spark, its session.

- Titles never name the library. The chain adds the support's requirements, and the frontend groups the code by library.
- Supports fill class attributes `*_template` with `str.format`: `{url}`, a repr, and `{kwargs}`, the options.
- Installing packages and configuring access to the storage depend on the environment, so they are left to the user.

`code_snippet` limits the recipes to some engines' keys, `"python"` for those without an engine, or turns "Python
code" off. Unknown keys are left out with a warning, as one launcher configuration may serve environments with other
plugins.

### Plugins

A plugin is a `StorageExplorerPlugin` subclass, in `plugin.py`. It is registered as an entry point of
`jupyter_storage_explorer.plugins`, named by its `key`.

Each explorer creates each plugin with its options. The options model is a frozen dataclass subclassing
`StorageExplorerPluginOptions`, which has `enabled` and `priority`. The plugin's properties give its components, made
with those options:

- `format_supports` and `formats`;
- `filesystem_operations` and `filesystem_mappers`.

`load_plugins`, in `_plugins.py`, loads every plugin installed, highest priority first, then by key.

- A disabled plugin is not even imported. A plugin may default to disabled, to be opt-in.
- An option the model lacks is a `ValueError`.
- A plugin that fails is left out with a `RuntimeWarning`: it fails to import or be created, is no plugin class, or
  clashes with another's name or key.

The explorer uses each kind of component as given in its arguments, then the plugins', then its defaults.

A plugin's name, description, version, authors, license and URLs are its package's metadata. About shows them, also for
plugins not loaded. Plugins never depend on their libraries: their `full` extra installs them.

databricks-support depends on pyspark-support, of exactly its own version. Its engine, Databricks Connect, has
pyspark-support's supports as subclasses, which override how the session is made:

- `session` makes it with `DatabricksSession`, on the workspace of fsspec-databricks' filesystem when the item is on
  one.
- `session_code` and `session_import` give the code's lines.
- `databricks-connect` brings a pyspark of its own, which makes no session with `SparkSession.builder`. pyspark-support's
  `PySpark` package then counts as not installed, so its engine is not offered.
- `databricks-connect` is in databricks-support's `full` extra. It replaces pyspark, so the two extras must not be
  installed together.

Tests fake entry points to `tests/plugin_samples.py`. `tests/all_supports.py` has the supports of this repository's
plugins, which the other tests use, and `NO_PLUGINS`, options disabling them all.

### Engines in the explorer

`engine_preference=` orders the engines users can choose. The one chosen is the user's last, if still offered, else the
first. The status bar's engine button chooses it, and the states remember it.

The preview and "View in a new tab" take an optional engine: a key, or None for the built-in views. The preview's badge
shows the format and the engine, e.g. "Parquet · Polars".

The right-click menu has, in groups:

- the view: View in new tab and Preview, with the engine chosen; View in new tab as and Preview as; Python code;
- the clipboard: Copy, Cut, Copy URL or path, Paste;
- editing: Edit, Rename, Create a folder, Delete;
- downloads;
- Properties, and the bookmark.

Separators left without visible rows around them are hidden.

### Engine options

`engine_options` is `{engine key: {format name or "*": {option: value}}}`. A support gets its engine's options for "*",
then for its format's name. It gets only those its options model has, as an object of that model.

- An entry may instead be a function of the item's `Location`, returning the dict. It gives options per storage, e.g.
  by account. It is called at each view and recipe.
- The launcher merges its layers option by option, even for such functions.
- Unknown engines, formats and options are `ValueError`s.

Secrets are declared on the options' fields, with `secret_field` and `secret_dict_field`. Generated code gets options
only through `SupportOptions.code_value`. It drops secret fields and secret keys, and also keys that look like
credentials, as a safety net.

Spark reads with its own storage settings. PySpark's supports take `session_options`, for the session, and
`reader_options`, for `spark.read.option`. A subclass per format has Spark's documented reader options, in snake case.

The options of each library are listed in its plugin's README only.

## The JupyterLab extension

The extension is not built when the package is built: build it yourself with `jlpm` in `launcher/labextension/`. The
build output and `node_modules` are git-ignored. They stay on disk until removed.

| Command (in `launcher/labextension/`) | Run it again when                                                                                        |
|---------------------------------------|----------------------------------------------------------------------------------------------------------|
| `uv run jlpm install`                 | `node_modules` is missing (new clone or machine), or `package.json` dependencies or `yarn.lock` changed. |
| `uv run jlpm build`                   | `src/`, `style/` or `package.json` changed, or the build output is missing.                              |
| `uv run jlpm build:prod`              | Before every release (a production build, without source maps).                                          |

After a build, run `uv sync` in the repository folder. It reinstalls the launcher package, which copies the build to
`.venv/share/jupyter/labextensions`. Then restart JupyterLab and reload the page.

Changes to the Python code or to `src/jupyter_storage_explorer/static/` need no build: restart the kernel.

Commit `package.json`, `yarn.lock`, `.yarnrc.yml`, `tsconfig.json`, `src/` and `style/` of `launcher/labextension/`;
not `node_modules/`, `lib/` or `.yarn/`.

The extension's packages are updated by hand: `uv run jlpm up <package>` there, then `uv run jlpm build` and the smoke
test. Dependabot does not update them, as it writes `yarn.lock` in a format jlpm's Yarn does not, but its alerts report
vulnerable ones.

## Releasing

Releases are made by GitHub Actions: push a version tag from `main`,

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

The workflows, in `.github/workflows/`:

1. **Release explorer** (`release-explorer.yaml`) runs on the tag. It builds `jupyter-storage-explorer` and checks its
   version. It creates the GitHub release, with notes generated from the merged pull requests, and publishes the
   package to PyPI.
2. **Release launcher** (`release-launcher.yaml`) runs once the first has succeeded, so that the explorer it depends on
   is on PyPI. It builds the JupyterLab extension and the launcher, then checks the version, the extension in the
   wheel, and the dependency on `jupyter-storage-explorer==X.Y.Z`. It adds the packages to the release and publishes
   them.
3. **Release <plugin>** (`release-<plugin>.yaml`) also runs once the first has succeeded. There is one per plugin, as
   PyPI's trusted publishing takes one workflow per project; they share `_release-plugin.yaml`. Each builds its plugin,
   then checks the version, the dependency on the explorer, and the entry point. It adds the packages to the release
   and publishes them.

To retry the launcher's or a plugin's, run it by hand for the tag: *Actions ▸ Release launcher ▸ Run workflow*.

The workflows are kept safe for a public repository:

- Each action is pinned to a commit SHA, and Dependabot (`.github/dependabot.yml`) updates them monthly.
- Jobs get only the permissions they need: `contents: write` to add files to the release, `id-token: write` to
  publish. No token is kept in the checkout.
- The workflows started by `workflow_run` run only for a successful "Release explorer" run on a tag pushed to this
  repository. A fork's pull request could otherwise run a workflow of that name, and start them.
- The release builds the extension with `jlpm install --immutable`, and the build tools at exact versions.

`uvx zizmor --offline .github/workflows` audits them, and `uvx --from actionlint-py actionlint` checks their syntax.
SECURITY.md says how to report a vulnerability.

### Release notes

Once all the workflows have succeeded, replace the generated notes (`gh release edit vX.Y.Z --notes-file notes.md`).
Use these sections, leaving out those with nothing to say:

- **New**, **Changes**, **Fixes**: one item each, saying what users can now do or what behaves differently, with the
  option or function names.
- **Breaking changes**: what users must change in their code or `launcher.py`, and how.
- Links to the documentation of the new features (absolute GitHub URLs).
- **Install**: the `pip install -U` command for both packages. Say that the launcher requires the explorer of the same
  version, and that JupyterLab must be restarted after upgrading it.
- **What's Changed** and **Full Changelog**: kept at the end, as generated.

### One-time setup for PyPI

The workflows publish with PyPI's [trusted publishing](https://docs.pypi.org/trusted-publishers/), without a token:

1. On PyPI, add a trusted publisher for each project, with this GitHub repository's owner and name and the
   environment `pypi`. For a project not on PyPI yet, add it as a *pending publisher* under *Your account ▸
   Publishing*.

   | PyPI project                               | Workflow                       |
   |--------------------------------------------|--------------------------------|
   | `jupyter-storage-explorer`                 | `release-explorer.yaml`        |
   | `jupyter-storage-explorer-launcher`        | `release-launcher.yaml`        |
   | `jupyter-storage-explorer-abfs-support`    | `release-abfs-support.yaml`    |
   | `jupyter-storage-explorer-databricks-support` | `release-databricks-support.yaml` |
   | `jupyter-storage-explorer-pandas-support`  | `release-pandas-support.yaml`  |
   | `jupyter-storage-explorer-polars-support`  | `release-polars-support.yaml`  |
   | `jupyter-storage-explorer-pyspark-support` | `release-pyspark-support.yaml` |

   Before its first release, a new plugin needs a workflow of its own (a copy of a `release-<plugin>.yaml`) and its
   trusted publisher.

2. On GitHub, create the environment `pypi` (*Settings ▸ Environments*). Optionally, require a reviewer there, so
   that publishing waits for approval.

### By hand

To build the packages locally, e.g. to publish them to another repository such as an internal Nexus:

```bash
cd launcher/labextension
uv run jlpm install        # only if package.json or yarn.lock changed
uv run jlpm build:prod
cd ../..
uv build --all-packages    # sdists and wheels of every package, in dist/
uv publish --publish-url <url> dist/*
```

`<url>` is the repository's upload URL, e.g. `https://nexus.example.com/repository/pypi-internal/`. `uv publish` asks
for the credentials, or reads them from `UV_PUBLISH_USERNAME` and `UV_PUBLISH_PASSWORD`.

Build from a clean checkout of the tag: uncommitted changes give a version like `X.Y.Z.post0+g<commit>.d<date>`.

`uv build` packages whatever extension was built last, so run `build:prod` just before it. Without a built extension,
`uv build` still succeeds, but the launcher's wheel has no launcher item.

## Documentation

The root `README.md` is the quick start and highlights. PyPI shows it too and cannot resolve relative paths, so its
links and images are absolute GitHub URLs.

The details are in `docs/` (`storage-explorer.md`, `data-explorer.md`). They are read on GitHub only, so they link to
each other and to the repository's files with relative paths.

The screenshots (`docs/figs/`, `launcher/figs/`) and the demo GIFs are made by the scripts in
[`docs/scripts/`](docs/scripts/README.md). They use Playwright and the installed Microsoft Edge, on a made-up data lake
in memory. Their packages are in the `docs` dependency group, which `uv sync` does not install:

```bash
uv run --group docs docs/scripts/make_all.py
```

## Customizing

Icons are changed with CSS (below). Formats, engines, file operations and storages are added in Python, as plugins
that every explorer uses once installed. See [development-plugin.md](docs/development-plugin.md), which also covers
this repository's plugins (`plugins/`).

### Icons

The icons of files and plain folders are JupyterLab's file browser's, as SVG images (`.jse-icon svg`).

- **Files** get the icon of their format (its `file_icon`, one of `FILE_ICONS` in `formats/base.py`), else of their
  extension. A format can bring an icon of its own, `file_icon = ("avro", "<svg ...>...</svg>")`, shown as an image
  (`.jse-icon img`).
- **Folders that a storage makes more than folders** get icons of their own, e.g.:
  - Azure accounts and containers, S3 and GCS buckets, SFTP servers, local drives and the memory filesystem;
  - Databricks' catalogs, schemas, volumes and workspace folders.

  The filesystem's mapper tells which they are, and its CSS gives their icons: `FileSystemMapper.level` and
  `FileSystemMapper.css`, see [development-plugin.md](docs/development-plugin.md#how-its-storages-look). The icon
  hides the folder's image, and is drawn in its `.jse-icon::before`, as a mask.
- **Azure, S3, GCS and Databricks** icons are in their cloud's colour, the variable `--jse-storage-color`. For example,
  `.jse-browser[data-fs-protocol="s3"] { --jse-storage-color: green; }`, or `initial` for JupyterLab's grey.

The explorer and its rows carry attributes to select them by:

| Selector                                  | Rows                                                                                                   |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------|
| `.jse-browser`                            | The explorer. Every selector starts with it, so nothing else on the page changes.                      |
| `.jse-browser[data-fs-protocol="s3"]`     | The explorer while it shows a storage of that protocol: `abfs`, `s3`, `gs`, `dbfs`, `sftp`, `file`, …  |
| `.jse-browser[data-fs-mapper="…"]`        | The explorer while it shows a storage of that mapper, by its class's qualified name, if it has CSS |
| `[data-fs-level="container"]`             | Folders by what the storage makes of them: `account`, `container`, `endpoint`, `bucket`, `host`, `drive`, `memory` |
| `[data-fs-level="catalog"]`               | Databricks' folders: `workspace`, `volumes`, `catalog`, `schema`, `volume`, `workspace-files`, `repos`, `users`, `shared`, `user`, `repository`, `legacy` |
| `[data-depth="0"]`, `[data-depth="1"]`, … | Folders in the tree and the list, by their level: `0` the top folder, `1` the folders in it, …    |
| `[data-file-format]`                      | Files of a known format (not those of no known format, or without a URL)                          |
| `[data-file-format="parquet"]`            | Files of one format: `parquet`, `csv`, `json`, `json-lines`, `excel`, `markdown`, `text`, `image` |
| `.jse-icon svg`, `.jse-icon::before`      | In a row, the icon's image, and where to show something else instead                              |

To change an icon, hide its image and show something else in its `::before`, e.g. an emoji.

- A folder of a level has its mapper's icon there already, drawn as a mask. Reset it too: `mask: none; background:
  none; width: auto; height: auto;`.
- Your CSS overrides the mappers' when its selectors start with `.jse-browser`, as below.

This CSS shows the top folder as 🗄️, the folders in it as 🗃️, and gives data files their own icons. Deeper folders
keep the folder icon:

```css
/* Folders: an emoji per depth */
.jse-browser :is([data-depth="0"], [data-depth="1"]) .jse-icon svg {
    display: none;
}

/* Not their mapper's icon, if they have one */
.jse-browser :is([data-depth="0"], [data-depth="1"]) .jse-icon::before {
    mask: none;
    background: none;
    width: auto;
    height: auto;
}

.jse-browser [data-depth="0"] .jse-icon::before {
    content: "🗄️";
}

.jse-browser [data-depth="1"] .jse-icon::before {
    content: "🗃️";
}

/* Files: an emoji per format */
.jse-browser [data-file-format] .jse-icon svg {
    display: none;
}

.jse-browser [data-file-format] .jse-icon::before {
    content: "📄";
}

.jse-browser [data-file-format="csv"] .jse-icon::before,
.jse-browser [data-file-format="excel"] .jse-icon::before {
    content: "📊";
}

.jse-browser [data-file-format="parquet"] .jse-icon::before {
    content: "🧱";
}

.jse-browser [data-file-format="image"] .jse-icon::before {
    content: "🖼️";
}

.jse-browser [data-file-format="markdown"] .jse-icon::before {
    content: "📝";
}
```

The storages' own logos are not shipped, as they are their owners' trademarks. You can show logos you are allowed to
use, e.g. an image of yours for S3 buckets:

```css
.jse-browser[data-fs-protocol="s3"] [data-fs-level="bucket"] .jse-icon svg {
    display: none;
}

.jse-browser[data-fs-protocol="s3"] [data-fs-level="bucket"] .jse-icon::before {
    content: url("https://example.com/my-bucket-icon.svg");
    mask: none;
    background: none;
    width: auto;
    height: auto;
}
```

A plugin's mapper can bring such icons for every user instead, in its `css`.

#### Test in notebooks

Run the CSS in a notebook cell, before or after an explorer, inside `<style>`. It applies to the whole page (every
explorer in it) until the page is reloaded:

```python
from IPython.display import HTML

HTML("""<style>
.jse-browser [data-depth="0"] .jse-icon svg { display: none; }
.jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
</style>""")
```

`HTML(...)` must be the last line of the cell (or use `display(HTML(...))`).

#### Apply to all of JupyterLab

JupyterLab's custom CSS applies to every page: notebooks, consoles and the launcher's explorer tabs.

1. Save the CSS, without `<style>`, as `custom/custom.css` in Jupyter's configuration directory.
   `jupyter --config-dir` prints that directory: `~/.jupyter` by default (`%USERPROFILE%\.jupyter` on Windows), or
   `$JUPYTER_CONFIG_DIR` where it is set.

   JupyterLab reads the file from there only, not from the other configuration directories. For several users, set
   `JUPYTER_CONFIG_DIR`, or put the file in each user's directory. For example, `~/.jupyter/custom/custom.css`:

   ```css
   /* Storage Explorer: the top folder as 🗄️, Parquet files as 🧱 */
   .jse-browser [data-depth="0"] .jse-icon svg { display: none; }
   .jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
   .jse-browser [data-file-format="parquet"] .jse-icon svg { display: none; }
   .jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
   ```

2. Turn it on in a `jupyter_lab_config.py`, in any of Jupyter's configuration directories (`jupyter --paths`):
   - for one user, `~/.jupyter/jupyter_lab_config.py`;
   - for an environment, `<env>/etc/jupyter/jupyter_lab_config.py`;
   - for everyone, `/etc/jupyter/jupyter_lab_config.py`.

   ```python
   c.LabApp.custom_css = True
   ```

   or start JupyterLab with `jupyter lab --custom-css`.
3. Restart JupyterLab, then reload the page.
