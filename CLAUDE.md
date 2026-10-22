# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All Python goes through uv (never call `python`/`pip` directly). Node.js comes with the dev dependencies
(`nodejs-wheel`), so `uv run node`, `uv run npx` and `uv run jlpm` work without a Node install.

```bash
uv sync                                             # both workspace packages, editable, with dev dependencies
uv run pytest                                       # the Python tests (tests/)
uv run pytest tests/query/test_query.py -k range         # one file / matching tests
uv run pytest --cov                                 # with coverage of src/jupyter_storage_explorer
uvx ruff check src launcher/src plugins tests docs/scripts  # lint (ruff is not a dev dependency; config in pyproject.toml)
uvx ruff format src launcher/src plugins tests docs/scripts # format
uv run npx --yes prettier@3.3.3 --write .           # format static/ and the extension's src/ (.prettierignore)
uv run tests/browser/check_js.py                    # the joined JS modules: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py          # the widgets in a real JupyterLab (see below)
uv run tests/performance/benchmark.py               # timings on a storage with latency: before and after a change
uv run jupyter lab                                  # try the widgets in a browser (see notebooks/)
uv run notebooks/make_samples.py                    # regenerate the sample data the notebooks use
```

CI (`.github/workflows/ci.yaml`) runs ruff, Prettier, `check_js.py`, pytest with coverage (uploaded to Codecov),
pyspark-support's tests alone on a local Spark with Java (the `spark` job) and compiles the launcher's extension (`jlpm build:lib`: tsc; `yarn.lock` must be up to date) on pull requests and pushes
to `main`. Releases are tag-driven GitHub Actions (see DEVELOPMENT.md, also for the annotated
tag and the release notes' sections); the maintainer pushes the version tag. In the workflows, `astral-sh/setup-uv`
must be pinned to a full version (e.g. `@v10.3.0`): since v8 it publishes no major-version tags.

Python and `static/` changes need no build: restart the kernel. The launcher's JupyterLab extension
(`launcher/labextension/`, TypeScript) is built by hand: `uv run jlpm install` / `uv run jlpm build` there, then
`uv sync` at the root and restart JupyterLab.

## Tests

The Python tests: the explorer's and the launcher's in `tests/`, each plugin's in `plugins/<name>-support/tests/`
(`uv run pytest` at the root runs both; a plugin's alone, with only its dependencies, in its folder: `uv run
--isolated --package <its package> pytest`. Not a plain `uv run` there: it installs the plugin's `dev` group into the
shared `.venv`, e.g. pyspark, which the explorer's tests expect missing, until `uv sync` at the root). Plugins' tests cover their own code (supports, options, engine,
operations, entry point); the explorer's use the plugins' supports as material (`tests/all_supports.py`). Their
dependencies are in each plugin's `dev` group. Fixtures from the public `jupyter_storage_explorer.testing` (for
plugins too: their `tests/conftest.py` imports them; `tests/conftest.py` names it in `pytest_plugins`): `memfs` (a
cleared fsspec memory filesystem), `make_item` (writes a file there and returns it as formats and supports are given
it, an `ItemContext`, made by `item_of`; `local_item` for a local file); in `tests/conftest.py`, `mem_explorer` and
`local` (explorers of those). `tests/` has a folder per part of the package: `explorer/` (`StorageExplorer` and
`_explorer/`), `query/` (`_query/`, `DataExplorer`), `formats/`, `filesystems/`, `jobs/` (`_jobs/`), `launcher/` and
`browser/`; at its top, `conftest.py`, the tests of the top-level modules (`test_plugins.py`, `test_json.py`) and the
helpers the folders share (`explorers.py`, `items.py`, `all_supports.py`, `plugin_samples.py`, `format_samples.py`),
imported by name (the folders have no `__init__.py`: pytest puts `conftest.py`'s folder on `sys.path`; never import
one test file from another, but a helper). Test files' names are unique across the folders (`test_<plugin>_*.py`):
pytest imports them by name. Anything polars
reads by URL (`query`, polars previews, the data browser) needs real local files (`tmp_path`), as polars cannot read
`memory://`. The data browser's tests run each filter on polars, pandas, PyArrow, DuckDB and sqlframe (the PySpark API
on DuckDB, which narwhals queries as it does Spark: the core's tests have no Spark). pyspark-support's view tests run
on a real local Spark session (`local_spark`), skipped without Java or pyspark (the shared `.venv` has none): CI's
`spark` job runs them alone, with Java. The widget tests
subclass the widget to capture `send()` and drive it through `_on_custom_msg`, as the frontend would; for
`StorageExplorer`, in `tests/explorer/test_explorer_*.py` (a file per feature, as its mixins) on the harness of
`tests/explorers.py` (`Explorer`, `make`, `entries`, ...).

The JavaScript has no unit tests. `check_js.py` joins each widget's module as the kernel does (`_static.esm`) and runs
`node --check` and ESLint on it (names used but defined in no file, or defined but unused). Behaviour is checked by the
smoke test, `tests/browser/smoke.py` (or some of its checks, by name): it runs JupyterLab with the demo data of
`docs/scripts/` (`_lab.py`, `demo_data.py`) and clicks through the main features in the installed Edge with
Playwright, leaving `tests/browser/smoke-<check>.png` for a failed check. Run it after any change to `static/` or the
extension, and add a check for a new feature there. For a one-off look, write a Playwright script on `_lab` the same
way (a new notebook each time: a reused name reuses its kernel, which keeps the old JavaScript). Drag and drop in the
widgets only works in a browser, not in IntelliJ's notebook view. The smoke test reloads the page and restarts a
launcher tab's kernel (`launcher_tab_reload`, `launcher_tab_restart`); check a server restart by hand (stop and start
its process).

## Layout

A uv workspace of packages released together (version from git tags via hatch-vcs): the explorer, the launcher and
the plugins (`plugins/<name>-support`). The launcher and the plugins require the explorer of exactly their own version
(their `hatch_build.py` sets their dependencies, as the version comes from git; add new ones there); the explorer's
extras, declared in the root's `pyproject.toml` without versions (each plugin's exact pin of the explorer makes them the
plugins of its version), are `<name>`, the plugin with its `full` extra (its libraries), and `<name>-support`, the
plugin alone (`all` and `all-supports`: every plugin so); the launcher's `pyproject.toml` offers the same extras (the explorer's, at the version it pins):

- `jupyter-storage-explorer` (root, `src/jupyter_storage_explorer/`): the anywidget widgets `StorageExplorer` (files)
  and `DataExplorer` (a dataframe given by the user, any library narwhals supports, with `QuerySettings`). Runtime
  dependencies are only anywidget, fsspec, narwhals, pygments, traitlets; polars, pandas, pyarrow, deltalake, fastexcel,
  openpyxl, Pillow, PySpark are all optional and probed at run time; the engines' supports come with plugins. Its top
  level has the widgets (`storage_explorer.py`, `data_explorer.py`), the
  `Location` interface (`location.py`), the `StorageExplorerPlugin` class (`plugin.py`; loaded by `_plugins.py`), the helpers plugins test with (`testing.py`: items and pytest fixtures; needs pytest) and small
  private helpers (`_paths`, `_infos`, `_json`, `_static`, `_callbacks`); the rest is in packages: public, `filesystems/`
  (`locations.py`: the predefined locations; `mapper.py`: the `FileSystemMapper` interface and `MapperChain`; `mappers.py`: the predefined mappers;
  `operation.py`: the `FileSystemOperations` interface; `operations.py`: the predefined operations) and `formats/`; private, `_explorer/`
  (`StorageExplorer`'s mixins, with `states.py`, `listing.py` and `jupyterlab_files.py`), `_jobs/` (`tasks.py`:
  `FileTasks`; `runner.py`: `JobRunner`; `operation_chain.py`: `OperationChain`; `incoming.py`, `properties.py`,
  `transfer_policy.py`) and `_query/`
  (`filters.py`, `settings.py`: `QuerySettings`, `QueryState`; `data_query.py`: `DataQuery`, `fetch_rows`). Users import
  from the top level, `filesystems`, `formats` and `formats.supports` only (and the plugins' packages), whose `__all__` are the public API:
  what users construct, subclass, call or annotate with. The explorer's machinery (`SupportChain` and `Recipe`,
  in `_explorer/supports.py`; `OperationChain`, in `_jobs/operation_chain.py`; `detect`, `matching_formats`, the `DEFAULT_*` tuples) stays out of
  them, imported from its modules by the package and the tests.
- `jupyter-storage-explorer-launcher` (`launcher/`): a JupyterLab launcher item opening a tab whose kernel runs
  `launch()`. It merges every `storage-explorer/launcher.py` in Jupyter's config paths as layers, system to user
  (their `filesystems()`, `plugin_options()` (merged by plugin, then option), `supports()`, `format_options()` (merged by library, format, then option), `operations()`, `filesystem_mappers()`, `transfer_policy()`, `parameters()`;
  `final()` names what later layers cannot change; retired `style()` and `formats()` are ignored with a warning, `RETIRED`; see `load_settings`, tested in
  `tests/launcher/test_launcher.py`). The settings menu (toolbar.js: ⚙, on every explorer: "About", about.js and `_explorer/about.py`, the
  explorer's version and icon, `static/storage-explorer.svg`, a copy of the launcher's kept the same by
  `tests/explorer/test_explorer_about.py`, and the plugins installed from their entry points' metadata, those not loaded greyed
  out with why; names link to their packages' home pages, the tooltips add authors and license; and in the tab, "Edit configuration": `_offer_settings`, trait `_settings_path`, never in notebooks) opens the user's `launcher.py` through the `files.ts` drive, created from
  `launcher_template.py` if missing, once the user confirms (`"settings_open"`: `{"missing"}`, then with `"create"`; `"jupyterlab_get"`/`"jupyterlab_save"` with `"settings"` read
  and write that file only): `~/.jupyter` is hidden, so JupyterLab's own contents API would refuse it. Its JupyterLab extension has four plugins:
  - `index.ts`: the tab, a console (`ExplorerTab`). ipywidgets binds a console's widgets to its first kernel, so a tab
    whose session is lost (server restart) or whose kernel changes or restarts is replaced by a new tab. Each tab's
    view (storage, folder per storage) is reported by the explorer as a bubbling `"jupyter-storage-explorer:view"` DOM
    event, kept in JupyterLab's state database (saved with the workspace) and passed back as `launch(view=...)`
    (`StorageExplorer._restore_view`). The side panel (`sidePanel.ts`, `ExplorerSidePanel`, in the left side bar, and
    the command "Show Storage Explorer in the Side Bar") holds such a console too, of its own session name, made by
    `console:create` (for ipywidgets' widget manager) when the panel is first shown, then moved into the panel
    (`panel.show()`: it was a hidden tab); restored consoles of that name are moved back in (`adopt`, after
    `app.restored`); an `ExplorerTab` with `side` runs `launch(sidebar=True)` (`SIDEBAR`: `layout="sidebar"`, no tree,
    no preview panel, over `parameters()`) and replaces itself through the panel.
  - `download.ts`: files dragged from any explorer onto JupyterLab's file browser are downloaded to the Jupyter server.
  - `files.ts`, "Open in JupyterLab": a JupyterLab drive (`StorageExplorer:<storage>/<path>`, not shown in the file
    browser) serving only the files explorers opened on the page, read and saved through the explorer's kernel
    (`"jupyterlab_get"`, `"jupyterlab_save"`; contents models in `_explorer/jupyterlab_files.py`, whose hash lets
    JupyterLab detect changes made elsewhere before saving; notebooks' cells are trusted as jupyter_server trusts them,
    with nbformat's notary in the kernel: untrusted unless signed, signed when saved trusted; tests get their own
    `JUPYTER_DATA_DIR`). Anything else (typed paths, new files, renames) is refused.
  - `queryTabs.ts`, "View in a new tab": the kernel views the item and opens a widget of the view, a `DataExplorer`
    of the same query for a `QueryView` (`DataExplorer._of_query`, settings remembered by location as the preview's),
    else a `ViewTab` (`_view_tab.py`: the view's section, rendered by `static/view_tab.js` with the shared
    `sections.js`), and keeps it in `_view_tabs` until the tab closes (`"view_tab"`, `"view_tab_closed"`); the tab
    renders any widget by model id (`openWidget`), with the output renderers of the notebook or console holding the
    explorer (ipywidgets ties widgets to that kernel connection; the side panel's: its `explorerConsole`), and closes
    with it or a kernel restart.

## Architecture

DEVELOPMENT.md's Architecture section describes each part: read it before changing one. docs/development-plugin.md
has the rules for formats, supports, options, operations, mappers and plugins: follow them, and keep them in step with
the code. The traps:

- Traits are underscore-prefixed in every widget: a public trait would be public API.
- Traitlets observers must be on `StorageExplorer` itself. The mixins in `_explorer/` hold only methods.
- Only `StorageExplorer`'s *File operations* block calls fsspec on the storage shown.
- In JavaScript, file names, paths and messages naming files go through `visible()`, never as they are.
- anywidget's `model` has only `get`, `set`, `save_changes`, `on`, `off` and `send`. Backbone methods such as
  `previous()` throw inside `set` and silently break syncing.
- A new frontend file in `static/` is joined into the module only if `_static.esm` names it. A part in
  `static/<widget>/` is joined automatically.
- Mappers match classes by qualified name: never import an optional package to map it.
- `MapperChain.locate` never opens an `FsspecLocation`'s URL.
- Outside an explorer, callers of `move` and `copy` pass `same` themselves, e.g. the module-level `same_filesystem`.
- An operation that cannot handle a call raises `FileSystemOperations.NotSupported`, never `NotImplementedError`,
  which the chain reports as an error.
- Work functions of jobs run in a worker thread: never touch traits or call `send` there. Call `progress.check()`
  between items, so a cancel stops them.
- Without a running asyncio loop, as in tests, jobs run synchronously.
- Measuring with a `Progress` lists folder by folder, never with `fs.walk`: its `on_error` misses subfolders.
- The transfer policy is checked per item in the kernel, from `FileTasks._refused`. A new kind of transfer must call
  it there.
- A drop is taken only if it carries the id of the drag kept in the page. Never let a drag's data name files.
- `ExplorerStates` with a file reads it again before each change and writes it whole. Never write over a file that
  could not be read.
- The listing is sent as columns, without paths or URLs: folders may hold tens of thousands of items. The kernel's
  sorting and filters in `_explorer/listing.py` must follow the browser's.
- `open_preview` is deprecated, with a `DeprecationWarning`.
- A format's `matches` reads nothing: it runs for every file listed. A signature check goes in `sniff`.
- `formats` never imports `_explorer`. Supports import their libraries only inside methods, through
  `PythonPackage.load()`, so that plugins load without them.
- The explorer calls only the methods a support lists in `capabilities`. Keep
  `test_capabilities_are_the_methods_implemented` passing for the defaults.
- Supports never check their packages, and take no `__init__` arguments.
- A recipe's title never names the library.
- Generated code gets options only through `SupportOptions.code_value`, which leaves out secrets.
- Plugins never depend on their libraries: their `full` extra installs them. A new dependency of a plugin goes in its
  `hatch_build.py`.
- Each library's options are listed in its plugin's README only. Update it when an options model changes.

## Conventions

- Comments and docstrings are written in full sentences explaining *why*; keep that density and tone.
- Write docs (this file, DEVELOPMENT.md, `docs/`, READMEs) so that people can review them:
  - One idea per sentence: about 30 words, never more than 50.
  - At most one parenthesis per sentence, never nested.
  - Three or more items make a list.
  - Add a new fact as its own sentence or bullet where it belongs. Never append it to an existing sentence.
  - Name an identifier only when the reader needs it to find the code. A function's details belong in its docstring.
  - Describe what is, not what was: git keeps the history.
  - When editing a passage that breaks these rules, rewrite it.
- Docstrings of the public API, what users construct, call, subclass or override (`StorageExplorer`, `DataExplorer`,
  `fetch_rows` (the `fetch_rows=` default of both), `QuerySettings`, `ExplorerStates` (with `Bookmark`,
  `QueryState`), `FileSystemOperations` and its subclasses (with `_copy_file`, `_move_file`), `Measurement`,
  `Progress`, `DataFormat`, `FormatSupport`, `View`, `Location` and its subclasses, `FileSystemMapper` and its subclasses, `MapperChain`, `same_filesystem`), are in numpy style:
  `Parameters`, `Returns`, `Raises`, `Attributes`, `See Also`, `Examples`. Internal ones (underscore names,
  `DataQuery`, `FileTasks`, `JobRunner`, the mixins, ...) stay prose.
- `from __future__ import annotations` everywhere, with type-only imports under `TYPE_CHECKING` (ruff `TC` rules).
- A new feature of the storage explorer is a mixin in `_explorer/` (Python) and a part in `static/storage_explorer/`
  (JavaScript), each one feature; its tests go in a `tests/explorer/test_explorer_*.py` and, for what users do, a check in
  `tests/browser/smoke.py`.
- The root README is the quick start and highlights only; user-facing details are in `docs/storage-explorer.md`
  ("Installation", the extras of both kinds; "Using the explorer", "Unsafe operations", "Transfer policy", "Supported formats", "Format options",
  "StorageExplorer options", grouped by use, and last "Extensions" with "File operation extensions" (a table: add new
  ones there)) and `docs/data-explorer.md` (the data
  browser, `result()`, `on_change()`, `QuerySettings`, "DataExplorer options"). Custom icons (CSS) are in
  DEVELOPMENT.md's "Customizing"; extending the explorer in Python (formats, engines, supports with their options and
  secrets, file operations, filesystem mappers) and packaging plugins, with the conventions, in docs/development-plugin.md. Update them when operations, formats or options change, and the README's
  highlights for new features. Keep them short: what users do, not how it works. `supports`, `operations` and
  `filesystem_mappers` are for development: last in the docs, the options tables and the launcher's template.
- Images and links to other files in the READMEs are absolute URLs (`raw.githubusercontent.com/.../main/...` for
  images, `github.com/.../blob/main/...` for files): PyPI shows the README but cannot resolve relative paths. `docs/`
  is read on GitHub only, so it uses relative paths. Screenshots are in `docs/figs/` (the launcher's in
  `launcher/figs/`), taken at 2× and shown at their CSS size with `<img width="...">`. They and the demo GIFs are made
  by `docs/scripts/` (`uv run --group docs docs/scripts/make_all.py`, or one script; see its README): each starts
  JupyterLab in a temporary folder with its own settings, and explorers show a made-up data lake in fsspec's memory
  filesystem (`demo_data.py`), so no local path appears. Change or add a script there rather than taking pictures by
  hand.
