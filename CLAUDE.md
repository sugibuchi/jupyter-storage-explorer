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

DEVELOPMENT.md's Architecture section describes every part but the formats, the plugins and the engines, below. Read
it before changing them. The traps there:

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

**Formats** (`formats/`). Laid out as `filesystems/`: the interfaces `DataFormat` (`base.py`, with
`ItemContext`, which reads the item for formats and supports (`head`, `head_text`, `read_whole`; `name`, `size`,
`child_names`, `library_url`: the location as most libraries read it, a local file's plain path), `FILE_ICONS`,
and the explorer's `detect` and `matching_formats`, not exported), `FormatSupport` (`support.py`, with
`SupportOptions`, `Capability`, `FormatOptions`, `LIBRARY_DEFAULT`, and the generated code's helpers: `format_kwargs`,
`format_arguments`, the secret fields, `_shown_options`; only what plugin authors use) and `PythonPackage`
(`package.py`); a module per predefined format (`delta.py`, `parquet.py`, `excel.py`, `text.py`, `images.py`) and
the core's supports, those without an engine (library "python"), in `supports/python.py`: the built-in views,
`TextByPython` and `JsonByPython` also with fsspec's code, and `ImageByPillow`'s code (apart, so that Pillow is not
needed to view images), exported by `formats.supports`, not `formats`; the engines' supports, each plugin's with its
`Engine`, in `plugins/<engine>-support/src/jupyter_storage_explorer_<engine>_support/supports.py` (polars, pandas,
pyspark; exported by the plugin's package, with its plugin class), importing their libraries only inside methods,
through `PythonPackage.load()`; packages: an engine's own and those only it uses in its plugin's `supports.py`,
beside its `Engine` (polars: `Polars`, `Fastexcel`; pandas: `Pandas`; pyspark: `PySpark`, `DatabricksConnect`,
`DeltaSpark`), the support libraries several engines may use (and the core's `Pillow`) in `packages.py`, the
views in `view.py` (`View`s, `ViewLimits`; `TableView`s, for plugins (the defaults give none), give their counts, `TableView.more`, `total` and `unit`, and the explorer words them in the note, `section()`'s
`_rows_note`: presentation stays out of `formats`, which never imports `_explorer`), and the defaults in `defaults.py` (`DEFAULT_FORMATS`,
the standard formats, detected even without a plugin; `DEFAULT_SUPPORTS`, the core's). A format only detects; a support handles one format's data with one library,
so a library is added to a format (e.g. DuckDB for Parquet) without touching it.
- `DataFormat` subclasses declare `name`, `label`, `priority`, `extensions`, `file_icon` (its files' icon in the list:
  one of `FILE_ICONS`, or `(name, svg)` for one of its own, shown as an `<img>` so its scripts never run; sent as
  `_format_icons` and `_file_icon_svgs`, checked by `format_icons()` (`_explorer/icons.py`); files of formats without one, e.g. Text's, get
  their extension's icon, `FILE_ICON_EXTENSIONS` in `icons.js`) and implement `matches(ctx)`: cheap detection, called on
  every click and for every file listed (`_file_format`), reading nothing. Formats with a binary signature declare
  `sniff_bytes` and `sniff(ctx, head)`: `detect`/`matching_formats` read the file's first bytes once for all formats
  sniffing it and drop those refusing it (an unreadable file confirms none), always, whichever formats are installed
  (the files in a storage need not be what installed plugins expect); listings pass `sniff=False`, leaving such files
  without a format until clicked; folders are never sniffed. `ctx` is an `ItemContext` (`base.py`): a frozen dataclass of the item's `location`, the explorer's
  `fs` and its `path` there (to read more), its fsspec `info` and `children` (a folder's listing, None for a file;
  `is_dir`, `name`), one object rather than parameters so that it can grow without changing the methods'
  signatures; directory formats (Delta, Parquet datasets) inspect `ctx.children`. `detect` and `matching_formats`
  take a context and `formats=`. Parquet also takes
  Hive-style partition folders (`year=…/month=…/`), followed down one branch (one more `ls` per partition column,
  `_partitioned_layout`), and keeps each directory's `ParquetLayout` by location, for the supports
  (`layout(ctx)`: one not seen is detected then from `ctx.children`; else its own "*.parquet" files;
  `data_url(ctx)`, `first_files(ctx, n)`). The highest
  `priority` wins (Delta 20 > Parquet 10 > default 0 > Text -10). What supports share about a format is on it
  (`Csv.separator`, `Text.language`, `Image.mime_type`, `Parquet.data_url`, ...).
- `Engine` (`engine.py`; the predefined ones with their plugins' supports: `PolarsEngine`, `PandasEngine`,
  `PySparkEngine` (pyspark or databricks-connect); one class per key, a second is a ValueError, `_check_engine_keys`): a library users choose, with `key`
  (`engine_preference`, `format_options`), `label` and `requirements`, `PythonPackage` instances: a tuple, all needed,
  or a tuple of tuples, alternatives (`alternatives()`, `packages()`: the first installed, `is_installed()`).
- `FormatSupport` subclasses declare `format` (matched with `isinstance`, so subclasses too: `MarkdownByPython` comes
  before `TextByPython`), `engine` (an `Engine` class; None for the built-in views, engine-neutral: used for the
  formats the engine chosen does not handle; `library()` is its key, "python" for none), `additional_requirements` (`PythonPackage` instances, besides the engine's), and `capabilities`, the names of the methods it implements (`"view"`,
  `"recipe"`; `Capability`; not "jobs" or "tasks", which are file operations here): the explorer reads only
  `capabilities`, so a method not listed is never called (no runtime check of that, by design: users are expected to
  generate supports with AI from the written rules in `FormatSupport`'s docstring, kept by
  `test_capabilities_are_the_methods_implemented` for the defaults). Each method gets the detected format object first, then the item's `ItemContext`
  (`ctx`): its location (for libraries doing their own I/O and for the code: `ctx.library_url`; Spark's
  `spark_url(ctx.location.url)`, in pyspark-support), the explorer's fsspec filesystem and the item's path in it
  (to read it through the explorer, with its credentials); then its options, and for `view` the `limits`
  (`ViewLimits`), all positional, never in the context. Any may raise `FormatSupport.NotSupported` for an item, and
  the next support is tried. Options are the fields of the class's `options_model` (`SupportOptions`, the default,
  has none): a frozen, keyword-only dataclass, each field with a default, its helpers as methods (e.g.
  `PolarsOptions.storage()`); each format's model of an engine (`CsvByPolarsOptions`, `CsvByPandasOptions`, ...) has
  its reader's arguments as fields of the same names (from the library's API documentation; not the source, callables
  or what changes the result's type), default `LIBRARY_DEFAULT` (`support.py`: not passed; None is a value), passed
  with `options.arguments()` after the support's own defaults (a separator detected, polars' `try_parse_dates` in the
  data browser, pandas' `nrows` at most `max_memory_rows`), in the code `format_arguments(options.code_arguments())`
  (no secrets or Python objects, None kept); their tables, the docstrings' descriptions, are in each plugin's README
  only (docs link to them), with the plugin's options; a library's supports share a base model (`PolarsOptions`, `PandasOptions`,
  `FsspecOptions`; exported by the plugins' packages and `formats.supports`). Supports take no `__init__` arguments: the chain creates those
  given as classes. Class names are `<Format>By<Library>`, options `<Library>Options` or `<Format>By<Library>Options`.
- `SupportChain(supports, format_options, formats=)` (`_explorer/supports.py`, with `Recipe` and the
  `format_options` checks; the explorer's `_supports`: `supports=`, the plugins', then
  `StorageExplorer.default_supports()`, i.e. `DEFAULT_SUPPORTS`) has the explorer's `formats` (`_formats`: one object of
  each support's `format`, in their order, then of `formats=`, `DEFAULT_FORMATS` and the plugins' own; there is no
  `formats=` argument of the explorer) and calls the supports, with their options:
  `of(fmt, capability)` lists the supports for the format with the capability whose packages are installed (empty:
  none of the registered ones can); `engines`: the installed engines with a view support, `engine_preference` (keys;
  default `DEFAULT_ENGINE_PREFERENCE`, polars then pandas) first, then by key; `viewers(fmt)`: the engine keys that can view it,
  then None for the built-in views ("Preview as"); `engine_for(fmt, engine)`: the engine chosen if it handles the
  format (no fallback to another engine: LookupError if its support is not installed), else the built-in views;
  `view(fmt, ctx, limits, engine)` with that engine's supports (ValueError if each refuses it; RuntimeError, the
  caller's error, if it has none: the explorer resolves the engine first, `_view_engine`, and reports why it cannot
  view); `recipes` with the first support with `"recipe"` of each library
  (so one given replaces the default's), installed or not (the code may run elsewhere; `_registered`).
- `view(fmt, ctx, options, limits)`: one `View` dataclass of `view.py`. A `QueryView` (`data`: any
  dataframe narwhals supports, best lazy; `more`: eager data of the first rows only, e.g. pandas' `max_memory_rows`,
  which the browser notes as rows cut in memory, `DataQuery(cut=)`; PySpark's read the URL in the kernel's Spark
  session, `spark_session()`, a local Spark session in `plugins/pyspark-support/tests/test_pyspark_supports.py`) opens the data browser (`_new_query`: the first view's data, then the view
  again on reload, with a context read again: `_viewer`'s later calls, `_refreshed`, the item's info and listing on its
  own filesystem without fsspec's cache, its format checked again, else an error; a table set's reload views it again
  too, `TableSet._load`, the new view replacing the old); whether an item opens in the data browser is known only
  once viewed, so the menu offers "Preview" and "View in a new tab" for whatever has a format. A `TableSetView`
  (`nodes`: `Leaf(label, id)` tables, maybe in `Node(label, children)` groups; `loader(id)`, a table's data or a
  `QueryView` of it, whose `more` and `on_close` are kept, as pandas' Excel sheets; `selector` "tree" or "tab"; polars'
  and pandas' Excel views give the sheets on tabs unless options name one, or the workbook has one) opens the data
  browser on the table chosen: a `TableSet` (`_query/table_set.py`; one
  `DataQuery` at a time, settings remembered by "<url>#<id>"), sent as the preview's `"table_set"` and shown by
  `createTableSetPanel` (query.js); "table_set_open" chooses a table, and the data browser's requests carry
  `query_path(path, id)` (path NUL id), so a table no longer shown is never answered for; `query_result()` is the
  table chosen's, which `StorageExplorer.query_table` names (its id); in a view tab, a
  `TableSetTab` (`_table_set_tab.py`). The others
  (`TableView`, `TextView`, `TreeView`, `MarkdownView`, `MediaView`...) are sent as the one item of the preview's
  `"sections"` (`section()`), which the frontend renders by `kind`. Supports never check their packages: the
  chain calls only installed ones. `ViewLimits`: `max_bytes`,
  `max_display_rows` (table views' rows and the data browser's page size, sent as `"page_rows"`),
  `max_whole_file_bytes`, `max_live_rows` and `max_memory_rows` (the data browser's; `StorageExplorer(view_limits=)`).
  The functions given to a view's `on_close(callback, *, remove=False)` (the widgets' `on_change` idiom; kept in a
  private field, not sent to the frontend) are called with the view by `View.close()`, the first time only, errors
  logged: the explorer closes a view once it no longer shows it (`_release_preview`: another preview, the panel closed,
  another storage; a view tab closed; `StorageExplorer.close()`; the kernel's exit: `previews._close_views_at_exit`,
  an `atexit` function over the `explorers` registry, calling each one's `_release_views()`, which closes the views
  of the preview and the tabs, `_release()` of `DataExplorer` and `ViewTab`, without closing widgets). A
  `QueryView`'s `DataQuery` owns it (its
  `on_close`): a reload's view replaces it, the previous one closed, and closing the query (`DataExplorer.close()` for
  a tab) closes the last.
  `_query/data_query.py`'s `DataQuery` does filters, sort and paging as narwhals expressions, either on the data itself
  ("live") or on rows read into memory (queried in the data's own library: eager data as it is, lazy data in the one
  narwhals collects it into, e.g. PyArrow for DuckDB and Spark; pandas' NaN shown as missing); behaviour such as regex
  syntax then follows the data's library, as `result()`'s. The core needs no engine: polars is optional.
- `recipe(fmt, ctx, options)`: the code of "Python code", by title, e.g. `{"Load as LazyFrame": ...,
  "Load as DataFrame": ...}` (`ctx.fs` and `ctx.path` only for what the code must know of the file, e.g. a CSV file's
  separator; titles never name the library: the chain makes a `Recipe` of each, adding the support's
  `requirements()`, and the frontend groups them in a submenu per library, the first package, and lists the packages
  under the code), run as it is in a new notebook: its imports (`import polars as
  pl`, whatever the notebook has), and a Spark session (`SparkSession.builder.getOrCreate()`). It fills class
  attributes `*_template` (e.g. `lazy_frame_template`), written just before the method, an indented `inspect.cleandoc("""...""")`, with
  `str.format`: `{url}` (a repr) and `{kwargs}` (`format_kwargs`, the options; empty when none). Installing packages and
  configuring access to the storage (credentials, Spark's setup for Delta Lake) depend on the environment, so they are
  left to the user. `PythonPackage`s (`packages.py`) only say what a support needs (`package`, `import_name`,
  `is_installed()`, `load()`).

**Plugins** (`plugin.py`, `_plugins.py`). A `StorageExplorerPlugin` subclass, registered as an entry point of
`jupyter_storage_explorer.plugins` named by its `key`, is created by each explorer with its options (`options_model`, a
frozen dataclass subclassing `StorageExplorerPluginOptions`: `enabled`, `priority`, default `LOWEST_PRIORITY`, and its
own; `self.options`); its properties give its components, made with them (`format_supports`: classes or objects;
`formats`: classes; `filesystem_operations`, `filesystem_mappers`: objects, classes created without arguments).
`load_plugins(plugin_options)` (the explorer's `plugin_options`: `{key: {option: value}}`) loads every plugin installed
but those disabled (`"enabled": False`: not imported; a model may default to False, opt-in), highest priority first, then
by key; an option the model lacks is a ValueError; it leaves out, with a reason the explorer warns of
(`RuntimeWarning`), a plugin that fails to import or be created, is no plugin class, has another key, or a name two
packages register, and options of plugins not installed. `PluginComponents` gathers the components. The explorer uses
each kind as given (`supports=`, `operations=`, `filesystem_mappers=`), then the plugins', then its defaults. The
launcher's `plugin_options()` (merged by plugin, then option) sets `plugin_options`. `name`, `description` and `version`
(properties) are the plugin's package's metadata (`[project]` of its pyproject.toml): its entry point's distribution (set
by `load_plugins`), else the one registering the class (`_distribution_of`; editable installs list no packages), else
the one of its top-level package; None for none. So are `authors` (names, from `Author`/`Author-email`/`Maintainer`,
emails left out), `license` (`License-Expression`, else a one-line `License`) and `urls` (`Project-URL` and the legacy
`Home-page`, http(s) only: shown as links), by plugin.py's `package_authors`, `package_license`, `package_urls` and
`homepage` (also for About's plugins not loaded, and the explorer itself). abfs-support's `concurrency` is
its operation's. Tests:
`tests/test_plugins.py` (fake entry points to `tests/plugin_samples.py`); `tests/all_supports.py` has the supports of the
repository's plugins, as installed for development, which the other tests chain (`ALL_SUPPORTS`, `all_supports()`),
and `NO_PLUGINS`, the `plugin_options` disabling them all.
Plugins never depend on their libraries (their `full` extra installs them): see docs/development-plugin.md (developing each kind of component and packaging a plugin, with the conventions; written for
developers and for AI generating plugins: keep its rules, templates and checklist in step with the code).

**Engines in the explorer.** `StorageExplorer(engine_preference=)` orders the chain's `engines`, synced as
`_engines` (`[{"key", "label"}]`); `_engine` is the one chosen: the user's last (`ExplorerStates.engine`, its JSON
"engine") if still offered, else the first; the frontend sets it from the status bar (engine.js: a button left of Preview, with
the engine's label, opening a menu of the engines), `_on_engine` remembers it
(`remember_engine`; not the value `__init__` sets, `_engine_ready`) and shows again what can be previewed
(`_selected_format`, `_current_format` via `_viewable`, and the preview open). Requests "preview" and "view_tab"
take an optional "engine" (a key, or null for the built-in views; absent: the one chosen, `...` in Python), the
preview keeps "engine" and "engine_label" (its badge, "Parquet · Polars"), and "menu_info" answers "view" (the best
format and its engine, or None: "Preview <format>" disabled), "views" ("Preview as", "View in new tab as":
"CSV (pandas)") and recipes with their engine's label ("Load as DataFrame (Polars)"). The right-click menu
(item_menu.js): View/Preview <format>; View in new tab as, Preview as, Python code; Copy, Cut, Copy URL/path,
Paste; Edit (JupyterLab's editor), Rename, Create a folder, Delete; downloads; Properties, bookmark. The menu hides
separators left without visible rows around them (`tidySeparators`, overlays.js).

**Format options.** `format_options` is `{library: {format name or "*": {option: value}}}` (`SupportChain`,
`FormatOptions`): a support gets its library's (`library()`: its engine's key, "python" for none; only engines' keys go in
`engine_preference`) options for `"*"`, then for its `format.name`, only
those its `options_model` has (`options_model.option_names()`), as an `options_model` object passed to each of its methods. An entry
may instead be a function of the item's `Location` returning the dict (options per storage, e.g. by
`account_name`): `SupportChain.options_of(support, location)` calls it at each view and recipe, for the support
called only, and checks what it returns then (format names are checked at once). The launcher merges layers option
by option even so: an entry that is a function in either layer becomes a function giving the earlier layer's options
updated with the later's (`_merged_options`). Unknown
libraries, formats (of the explorer's formats or the supports') and options (taken by no support of that library and
format) are ValueErrors. Supports given as objects get options as classes do (they carry none). Secrets are
declared on the fields (`support.py`): `secret_field(...)` (metadata `is_secret`; also `repr=False`) for a whole value,
`secret_dict_field(..., secret_keys=[...])` for keys of a mapping (storage options); generated code gets options
only through `SupportOptions.code_value(name)`, which drops secret fields, secret keys at any depth, and, through
`_shown_options(value, secret_keys)`, credential-looking keys anyway (a safety net: storage options' keys come from
many backends) and non-literal values. ruff's `extend-immutable-calls` (pyproject.toml) knows the two helpers. Spark
reads with its own storage settings (`spark_url()` rewrites `abfs`/`s3` to `abfss`/`s3a`): PySpark's supports take
`PySparkOptions`, `session_options` (`SparkSession.builder.config`, by `spark_session(session_options)`; a running
session gets the runtime ones) and `reader_options` (`spark.read.option`), and a subclass per format
(`CsvByPySparkOptions`, ...) whose fields are Spark's (and Delta's) documented reader options in snake case (the
camel-case name, or metadata `SPARK_NAME`; None leaves it to Spark): the support's defaults (CSV's separator detected),
then the fields, then `reader_options` (option names ignore case), in the views and the code (`session_code()`,
`reader_code()`: `.options(...)` then `.option(...)`). Their tables are in the plugin's README only (docs link to it).

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
