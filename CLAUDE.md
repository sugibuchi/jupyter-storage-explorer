# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All Python goes through uv (never call `python`/`pip` directly). Node.js comes with the dev dependencies
(`nodejs-wheel`), so `uv run jlpm` works without a Node install.

```bash
uv sync                              # both workspace packages, editable, with dev dependencies
uv run pytest                        # all tests (tests/)
uv run pytest tests/test_query.py -k range   # one file / matching tests
uv run pytest --cov                  # with coverage of src/jupyter_storage_explorer (CI uploads it to Codecov)
uvx ruff check src launcher/src tests  # lint (ruff is not a dev dependency; config in pyproject.toml)
uvx ruff format src launcher/src tests # format
uv run jupyter lab                   # try the widgets in a browser (see notebooks/)
uv run notebooks/make_samples.py     # regenerate the sample data the notebooks use
```

Tests cover the Python side only. Fixtures in `tests/conftest.py`: `memfs` (a cleared fsspec memory filesystem) and
`make_target` (writes a file there and returns its `Target`). Anything polars reads by URL (`scan`, polars previews,
the data browser) needs real local files (`tmp_path`), as polars cannot read `memory://`. The data browser's tests
run each filter on polars, pandas, PyArrow, DuckDB and sqlframe (the PySpark API on DuckDB, which narwhals queries as
it does Spark; real Spark needs Java, so it is not tested). The widget tests subclass the
widget to capture `send()` and drive it through `_on_custom_msg`, as the frontend would.

The JavaScript is not covered by tests or CI. Check its syntax by joining it as the kernel does and running
`uv run node --check` on the result (`_static.esm("storage_explorer")`, also `"data_explorer"`). Check behaviour in a
real browser: `uv run jupyter lab --no-browser`, then a Playwright script run with
`uv run --with playwright python script.py`, using the installed Edge (`p.chromium.launch(channel="msedge")`), so no
browser download. In such scripts: write a temporary notebook under `notebooks/` with a new name each run (a reused
name reuses its kernel, which keeps the old JavaScript), open it in a reset workspace
(`/lab/workspaces/<name>/tree/notebooks/<file>?reset&token=...`), and delete it afterwards. Drag and drop in the widgets
only works in a browser, not in IntelliJ's notebook view.

Python and `src/jupyter_storage_explorer/static/` changes need no build: restart the kernel. The launcher's JupyterLab
extension (`launcher/labextension/`, TypeScript) is built by hand: `uv run jlpm install` / `uv run jlpm build` there,
then `uv sync` at the root and restart JupyterLab.

CI (`.github/workflows/ci.yaml`) runs ruff and pytest with coverage (uploaded to Codecov) on pull requests and pushes to
`main`. Releases are tag-driven GitHub Actions (see DEVELOPMENT.md, also for the annotated tag and the release notes' sections);
the maintainer pushes the version tag. In the
workflows, `astral-sh/setup-uv` must be pinned to a full version (e.g. `@v10.3.0`): since v8 it publishes no
major-version tags.

## Layout

A uv workspace of two packages released together (version from git tags via hatch-vcs); the launcher requires the
explorer of exactly its own version (`launcher/hatch_build.py` sets its dependencies; add new ones there):

- `jupyter-storage-explorer` (root, `src/jupyter_storage_explorer/`): the anywidget widgets `StorageExplorer` (files)
  and `DataExplorer` (a dataframe given by the user, any library narwhals supports, with `QuerySettings`). Runtime
  dependencies are only anywidget, fsspec, narwhals, pygments, traitlets; polars, pandas, pyarrow, deltalake,
  fastexcel, openpyxl, Pillow, PySpark are all optional and probed at run time. The "abfs" extra adds adlfs and the
  Data Lake SDK, for `filesystems/abfs.py`.
- `jupyter-storage-explorer-launcher` (`launcher/`): a JupyterLab launcher item opening a tab whose kernel runs
  `launch()`. It merges every `storage-explorer/launcher.py` in Jupyter's config paths as layers, system to user (their
  `filesystems()`, `formats()`, `format_options()`, `operations()`, `transfer_policy()`, `parameters()`, `style()` functions; `final()`
  names what later layers cannot change; see `load_settings`, tested in `tests/test_launcher.py`). The tab is a console
  (`index.ts`, `ExplorerTab`): ipywidgets binds a console's widgets to its first kernel, so a tab whose session is lost
  (server restart) or whose kernel changes or restarts is replaced by a new tab. Each tab's view (storage, folder per
  storage) is reported by the explorer as a bubbling `"jupyter-storage-explorer:view"` DOM event, kept in JupyterLab's
  state database (saved with the workspace) and passed back as `launch(view=...)` (`StorageExplorer._restore_view`).
  Check these in a browser against a server you restart (stop and start its process). Its extension has two more
  plugins: `download.ts`, files dragged from any explorer onto JupyterLab's file browser are downloaded to the Jupyter
  server; `files.ts`, "Open in JupyterLab": a JupyterLab drive (`StorageExplorer:<storage>/<path>`, not shown in the
  file browser) serving only the files explorers opened on the page, read and saved through the explorer's kernel
  (`"jupyterlab_get"`, `"jupyterlab_save"`; contents models in `_jupyterlab_files.py`, whose hash lets JupyterLab
  detect changes made elsewhere before saving). Anything else (typed paths, new files, renames) is refused. And
  `queryTabs.ts`, "Query data in new tab": the kernel opens a `DataExplorer` of the same query
  (`DataExplorer._of_query`, settings remembered by URL as the preview's) and keeps it in `_query_tabs` until the tab
  closes (`"query_tab"`, `"query_tab_closed"`); the tab renders it with the output renderers of the notebook or console
  holding the explorer (ipywidgets ties widgets to that kernel connection), and closes with it or a kernel restart.

## Architecture

**Widgets.** `storage_explorer.py` and `data_explorer.py` are `anywidget.AnyWidget` subclasses. State shared with the
browser is in `traitlets` tagged `sync=True` (underscore-prefixed). Everything else is custom messages: the frontend
sends `{"type": ..., "rid": ...}`, `_on_custom_msg` dispatches by `type` via `_message_handlers()`, and answers come back
as `{"type": "reply", "rid": ..., ...}` (uploads carry file pieces in binary `buffers`).

**Frontend.** Plain ES modules in `static/`, no bundler. anywidget cannot import neighbouring files, so `_static.esm()`
concatenates `common.js` + `query.js` + `<widget>.js` (shared files only define functions/constants; the widget file
has the `export`), and likewise for CSS. Third-party code is vendored in `static/vendor/`. The anywidget `model` only
supports `get`/`set`/`save_changes`/`on`/`off`/`send`; Backbone methods like `previous()` throw inside `set` and silently
break sync.

**Storage.** Everything is an fsspec filesystem; `StorageExplorer` can hold several named ones (`filesystems=`).
`_urls.default_url` turns paths into the URLs shown to users and passed to libraries (plain paths for local files,
`abfs://container@account.dfs.core.windows.net/...` for Azure); subclasses can override `StorageExplorer._url`, and
with it `_locate` (`_urls.default_location`), the reverse, used only to paste files copied in another kernel: the
explorer's own filesystem with the URL's protocol (Azure: its account), else one fsspec opens; URLs that do not tell
the storage (`abfs://container/...`, `dir://`) are refused, not guessed.

**File operations.** `StorageExplorer`'s methods are grouped in sections (UI logic first, one section per operation),
ending with a *File operations* block: the only methods that call fsspec on the filesystem shown (`self._fs`) for
listing, reading and writing, e.g. `_ls`, `_info`, `_exists`, `_isdir`, `_read_bytes`, `_put_file`. Other methods go
through them, never through fsspec directly. Moving, copying, deleting, downloading and creating folders go through
the operations objects instead (`operations.py`, the `operations=` argument): a chain of `FileSystemOperations`, each
method tried in order until one does not raise `FileSystemOperations.NotSupported` (its own exception, so that a
library's `NotImplementedError` is reported as an error). `OperationChain` adds nothing; `operations=` are tried before the defaults,
`StorageExplorer.default_operations()`, from the `filesystems/` package: `AtomicMoveOperation` (only moves within a
filesystem whose `mv` renames a folder in one step: local, memory, or a `DirFileSystem` over them), then
`AsyncFsspecOperations` (`async_fsspec.py`: async filesystems such as s3fs, their coroutines, many files at a time),
then `FsspecOperations` (`fsspec.py`). Both of the latter walk folders themselves, moves included, to report progress
file by file (helpers in `filesystems/_common.py`). Opt-in, not a default: `AzureDataLakeGen2Operation` (`abfs.py`,
the "abfs" extra: adlfs and `azure-storage-file-datalake`), moves (renames) and creates folders on accounts with a
hierarchical namespace with the async Data Lake SDK, connected from the adlfs filesystem's settings and run on its
loop with `fsspec.asyn.sync`; tested with a fake client (`tests/test_abfs.py`). `filesystems/__init__.py` does not
import it, as its packages are optional. `move` and `copy` take a source and a target filesystem, the same
one or not (`same_filesystem`: fsspec instances compare by their arguments). Between filesystems, single files go
through `FileSystemOperations._copy_file` and `_move_file` (`_copy_file_async`/`_move_file_async` in the async class),
overridable: by default through a temporary file, so a failure leaves no partial file, and a move copies then deletes
each file, so a cancel leaves each file in one place. Tests use fsspec's `AsyncFileSystemWrapper` around a memory
filesystem as an async one. Object stores (S3, GCS) have no empty folders, which matters for creating folders.

**Jobs.** Move, rename (a move within the folder, `FileTasks.rename`), delete, paste, uploads (from JupyterLab's file browser, and the storage half of uploads from the
computer) and both downloads to JupyterLab run in the background (`jobs.py`). Each is planned by a `FileTasks` method
(`file_tasks.py`, no widget involved) on the main thread: checks, conflicts to ask about (returned as a dict), else a
`Task` whose `work(progress)` runs in the `JobRunner`'s worker thread (one job at a time) and records what it changed
as each item is done, with `Task.record` (under a lock: `moved`, `removed`, `changed` folders, `added_to` those with new
items; `moved_away` from other filesystems). `StorageExplorer` only answers requests (`_plan_request`, `_start`) and
shows those changes on the main thread: as the job goes (`_follow`, run by the `JobRunner`'s `update` hook before
progress reports: items gone dropped from the list and tree without listing, at most every `_FOLLOW_INTERVAL`;
folders with new items listed again, keeping the selection, at most every `_RELIST_INTERVAL`), and all of them once
it has ended (`_finish`). Work functions must not touch traits or
`send`; they report to the `Progress` and stop when `progress.check()` raises `OperationCancelled`. A drop from
JupyterLab's file browser is a copy from the kernel's local disk (`FileTasks.upload`); files from the computer arrive in
pieces (`incoming.py`), and the last piece starts `FileTasks.upload_file`. Path helpers are in `_paths.py`. Requests answer `{"job": id}`; the kernel sends
`{"type": "job", ...}` as the job runs and with its result when it ends, and the frontend's `jobResult()` waits for
that. The main thread is reached through the kernel's asyncio loop (`call_soon_threadsafe`); without a running loop
(tests), jobs run synchronously, so tests see the result at once.

**Properties** ("Properties" in the right-click menu, `properties.py`). One file: its fsspec info, answered at once.
Folders or several items: `FileTasks.properties` adds up the operations' `measure` of each item (`properties.scan`),
as a job on a `JobRunner` of its own (`_scans`, ids `scan-N`), so it never waits for a move; the frontend shows it in
a blocking dialog with Cancel (not in the jobs above the status bar). It is not an operation: it does not take unsafe
mode. `FileSystemOperations.measure(fs, path, progress=None)` returns a `Measurement` (files, bytes, folders, oldest
and newest files, errors, `complete`): without `progress` (before a job's work, for its progress bar) the defaults
make one recursive `find`; with it, they list folder by folder (`_common.measure_by_folder`; async: `concurrency`
folders at a time), reporting files found, leaving unlistable folders in `errors` (not `fs.walk`, whose `on_error`
misses subfolders) and returning what was found, `complete` False, on a cancel. `_infos.mtime` gives the
modification time whichever key a filesystem uses, for the list too.

**Unsafe mode.** Folder operations (move, copy or cut and paste, rename, delete) are offered only while the "Unsafe mode" slider in
the toolbar is on (trait `_unsafe_mode`). In the frontend, every operation calls `takeUnsafe()` as it starts, which
turns it off (one operation at a time), and sends whether it was on with its request (`"unsafe"`); the kernel refuses
folders without it (the methods' `folders=` parameter).

**Transfer policy** (`transfer_policy.py`). `transfer_policy=` rules (`TransferPolicy`: first rule whose `src` and
`dest` both `fullmatch` decides, default allow) apply to transfers only: copies and moves between filesystems, not
within one (`same_filesystem`; moves never are). They are checked in the kernel only, per item as it is planned:
`FileTasks._refused` calls its `check` (the explorer's `_transfer_error`) from `_plan_copies` and `download`, and
refused items become errors while the others go on. URLs come from `_location` (`_url` on the storage shown, else `default_url`; files
pasted keep the URL they were copied with, from `_paste_sources`). Transfers with the user's computer use
`computer_url(name)` (`browser:///<name>`): checked in `_download` and `_upload_chunk`. Transfers with JupyterLab's file
browser (uploads from it, both downloads to the server) pass filesystem None to `check` for that side, which
`_location` makes `jupyterlab_url(path)` (`jupyterlab://<absolute path>`), unlike the explorer's own local storage
(plain paths). Not a security boundary.

**Between explorers and with JupyterLab.** Drag data can only be text, so the frontend shares objects page-wide under
`Symbol.for(...)` keys on `globalThis`: `"jupyter-storage-explorer.clipboard"` (Copy or Cut, for Paste in any explorer)
and `"jupyter-storage-explorer.drag"` (the current file drag, with a `download` function, read by the launcher's
`download.ts`); the launcher's `files.ts` and `queryTabs.ts` put their functions (`canOpen`, `open`, `openWidget`)
under `"jupyter-storage-explorer.jupyterlab"`, which the explorer offers ("Open in JupyterLab", "Query data in new
tab") only when they are there. Explorers on a page may be in different kernels (notebooks). The clipboard names the explorer and
storage copied from: an explorer of the same kernel is found in `_explorers` (by `_explorer_id`) and its filesystem
object used as it is (`_paste_sources`); otherwise the files' URLs are read back with `_locate`. After pasting files
cut in another explorer, the frontend dispatches a `"jupyter-storage-explorer:changed"` event on `globalThis`, so that
explorer asks its kernel to show what is left (`"changed"`, `_sources_changed`).

**States** (`states.py`). `ExplorerStates` keeps what explorers remember: bookmarks (storage name, folder, and its URL
when bookmarked, as `_url` only resolves the storage shown) and the data browser's queries (URL, settings, mode chosen),
the most recent first, at most `max_queries`. One in memory (`default_states`) is shared by the kernel's explorers
unless `states=` gives another, or a file's path (`explorer_states`: one object per file in the kernel). With a path
it is a JSON file shared with other kernels (each launcher tab is one; the launcher defaults to
`<jupyter_config_dir>/storage-explorer/states.json`): read again when an explorer is created and before each change,
then written whole, so kernels do not undo each other's changes; a file that cannot be read is never written over.
`DataQuery` remembers through it; `DataExplorer` uses a private one.
The frontend asks for the bookmarks when the bookmarks (star) menu opens (`"bookmarks"`, `"bookmark_add"`, ...), as other explorers
may have changed them.

**Lists.** The file list is filtered (by name), sorted and paged (100 per page) in the browser, from the full listing
the kernel sends; selection survives filtering and paging. Folders can hold tens of thousands of items, so the listing
(`_listing`, see `_make_listing`) is sent as columns, without paths or URLs: the frontend joins paths and asks for URLs
(`"urls"`) when copying. It sorts once per listing, not per keystroke. Folders of more than `max_browser_items` are
handled by the kernel instead (`listing.py`): `_listing` then only gives their size and a version, and the frontend
asks for pages (`"list"`), filtering the rows shown while it waits; sorting and filters there follow the browser's as
closely as Python allows (natural order ignoring case and accents; Python's `re`). Filters (the list's; *Select columns*) use
`createFilter` in `common.js`: text or a regular expression, always case-insensitive. The list's is cleared when
another folder's listing arrives (`renderList`), not on the click, so the previous folder's items never show unfiltered.

**Formats** (`formats/`). Each `DataFormat` subclass (`base.py`) declares `name`, `label`, `priority`, `extensions` and
which package sets can read it (`preferred_requirements` for previews and code, `code_only_requirements` such as PySpark
for code only, `query_requirements` for the data browser), and implements:
- `matches(target)`: cheap detection, called on every click; directory formats (Delta, Parquet datasets) inspect
  `target.children`. The highest `priority` wins (Delta 20 > Parquet 10 > default 0 > Text -10).
- `preview(target, limits)`: a list of `Preview` dataclasses (`TablePreview`, `TextPreview`, `TreePreview`,
  `MediaPreview`, `InstallPreview`...) that the frontend renders by `kind`; returns `install_hint()` when no package set
  is installed.
- `scan(url, is_dir)`: a polars LazyFrame for the data browser. `query.py`'s `DataQuery` does filters, sort and paging
  as narwhals expressions, so it takes any dataframe narwhals supports, either on the data itself ("live") or on rows
  read into memory (queried with polars); behaviour such as regex syntax then follows the data's library.
- `load_code(target, requirements)`: the "Python code" snippet for one package set; `recipes()` adds the `%pip install`,
  setup and import lines. Packages are referenced through `Requirement` classes (`requirements.py`), whose
  `code_name()` reuses the name the user already imported (e.g. `pl`).

**Format options.** `format_options` (same for both widgets) is one flat dict passed to *every* default format; each
`__init__` takes the keyword-only options it uses and ignores the rest via `**kwargs`. Names are
`<library>_<option>` for shared ones (`polars_storage_options`, `polars_credential_provider`, `pandas_storage_options`,
`fsspec_storage_options`) and `<library>_<format>_<option>` for format-specific ones (`polars_delta_use_pyarrow`). A new
option must also be added to the explicit `FORMAT_OPTIONS` list in `formats/utils.py`, which validates names;
`DEFAULT_FORMATS` there is a tuple of classes instantiated by `default_formats()`. Storage options go into generated code
through `snippet_options()`, which drops credential-looking keys and non-literal values. Spark snippets never get
storage options (`spark_url()` rewrites `abfs`/`s3` to `abfss`/`s3a`).

## Conventions

- Comments and docstrings are written in full sentences explaining *why*; keep that density and tone.
- Docstrings of the public API, what users construct, call, subclass or override (`StorageExplorer`, `DataExplorer`,
  `fetch_rows` (the `fetch_rows=` default of both), `QuerySettings`, `ExplorerStates` (with `Bookmark`, `QueryState`), `FileSystemOperations` and its subclasses (with `_copy_file`, `_move_file`), `Measurement`, `Progress`, `DataFormat`,
  `StorageExplorer._url` and `_locate`, `same_filesystem`), are in numpy style: `Parameters`, `Returns`, `Raises`, `Attributes`, `See Also`, `Examples`.
  Internal ones (underscore names, `DataQuery`, `FileTasks`, `JobRunner`, ...) stay prose.
- `from __future__ import annotations` everywhere, with type-only imports under `TYPE_CHECKING` (ruff `TC` rules).
- The root README is the quick start and highlights only; user-facing details are in `docs/storage-explorer.md`
  ("File operation extensions" (a table: add new ones there), "Using the explorer", "Unsafe operations", "Transfer policy", "Supported formats", "Format options",
  "StorageExplorer options") and `docs/data-explorer.md` (the data browser, `result()`, `on_change()`, `QuerySettings`,
  "DataExplorer options"). Update them when operations, formats or options change, and the README's highlights for
  new features. Keep them short.
- Images and links to other files in the READMEs are absolute URLs (`raw.githubusercontent.com/.../main/...` for
  images, `github.com/.../blob/main/...` for files): PyPI shows the README but cannot resolve relative paths. `docs/`
  is read on GitHub only, so it uses relative paths. Screenshots are in `docs/figs/` (the launcher's in
  `launcher/figs/`), taken at 2× and shown at their CSS size with `<img width="...">`.
