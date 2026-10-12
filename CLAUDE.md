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
`main`. Releases are tag-driven GitHub Actions (see DEVELOPMENT.md); the maintainer pushes the version tag. In the
workflows, `astral-sh/setup-uv` must be pinned to a full version (e.g. `@v10.3.0`): since v8 it publishes no
major-version tags.

## Layout

A uv workspace of two packages released together (version from git tags via hatch-vcs):

- `jupyter-storage-explorer` (root, `src/jupyter_storage_explorer/`): the anywidget widgets `StorageExplorer` (files)
  and `DataExplorer` (a dataframe given by the user, any library narwhals supports, with `QuerySettings`). Runtime
  dependencies are only anywidget, fsspec, narwhals, pygments, traitlets; polars, pandas, pyarrow, deltalake,
  fastexcel, openpyxl, Pillow, PySpark are all optional and probed at run time.
- `jupyter-storage-explorer-launcher` (`launcher/`): a JupyterLab launcher item opening a tab whose kernel runs
  `launch()`, which loads the user's `storage-explorer/launcher.py` from Jupyter's config paths. Its extension has a
  second plugin, `download.ts`: files dragged from any explorer onto JupyterLab's file browser are downloaded to the
  Jupyter server.

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
`abfs://container@account.dfs.core.windows.net/...` for Azure); subclasses can override `StorageExplorer._url`.

**File operations.** `StorageExplorer`'s methods are grouped in sections (UI logic first, one section per operation),
ending with a *File operations* block: the only methods that call fsspec on the filesystem shown (`self._fs`) for
listing, reading and writing, e.g. `_ls`, `_info`, `_exists`, `_isdir`, `_read_bytes`, `_put_file`. Other methods go
through them, never through fsspec directly. Moving, copying, deleting, downloading and creating folders go through
the operations objects instead (`operations.py`, the `operations=` argument): a chain of `FileSystemOperations`, each
method tried in order until one does not raise `NotImplementedError`, with `FsspecOperations` last (it walks folders
itself, to report progress file by file). Copies into storage go through a temporary file, so a failure leaves no
partial file. Object stores (S3, GCS) have no empty folders, which matters for creating folders.

**Jobs.** Move, delete, paste and both downloads to JupyterLab run in the background (`jobs.py`). Each operation is a
`*_task` method: it plans on the main thread (checks, conflicts to ask about, returned as a dict), and returns a
`_Task` whose `work(progress)` runs in the `JobRunner`'s worker thread (one job at a time) and whose `finish` (refresh
the list) runs back on the main thread. Work functions must not touch traits or `send`; they report to the `Progress`
and stop when `progress.check()` raises `OperationCancelled`. Requests answer `{"job": id}`; the kernel sends
`{"type": "job", ...}` as the job runs and with its result when it ends, and the frontend's `jobResult()` waits for
that. The main thread is reached through the kernel's asyncio loop (`call_soon_threadsafe`); without a running loop
(tests), jobs run synchronously, so tests see the result at once.

**Unsafe mode.** Folder operations (move, copy and paste, delete) are offered only while the "Unsafe mode" slider in
the status bar is on (trait `_unsafe_mode`). In the frontend, every operation calls `takeUnsafe()` as it starts, which
turns it off (one operation at a time), and sends whether it was on with its request (`"unsafe"`); the kernel refuses
folders without it (the methods' `folders=` parameter).

**Between explorers and with JupyterLab.** Drag data can only be text, so the frontend shares objects page-wide under
`Symbol.for(...)` keys on `globalThis`: `"jupyter-storage-explorer.clipboard"` (Copy, for Paste in any explorer:
pasted within the same explorer and filesystem by path, otherwise from the URL) and
`"jupyter-storage-explorer.drag"` (the current file drag, with a `download` function, read by the launcher's
`download.ts`).

**Lists.** The file list is filtered (by name), sorted and paged (100 per page) in the browser, from the full listing
the kernel sends; selection survives filtering and paging. Folders can hold tens of thousands of items, so the listing
(`_listing`, see `_make_listing`) is sent as columns, without paths or URLs: the frontend joins paths and asks for URLs
(`"urls"`) when copying. It sorts once per listing, not per keystroke. Folders of more than `max_browser_items` are
handled by the kernel instead (`listing.py`): `_listing` then only gives their size and a version, and the frontend
asks for pages (`"list"`), filtering the rows shown while it waits; sorting and filters there follow the browser's as
closely as Python allows (natural order ignoring case and accents; Python's `re`). Filters (tree, list, *Select columns*) use `createFilter`
in `common.js`: text or a regular expression, always case-insensitive.

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
- `from __future__ import annotations` everywhere, with type-only imports under `TYPE_CHECKING` (ruff `TC` rules).
- The README documents user-facing options and formats; update "Using the explorer" (and its "Unsafe operations"),
  "Supported formats", "Format options" and "StorageExplorer options" when operations, formats or options change. Keep
  it short.
- Images and links to other files in the READMEs are absolute URLs (`raw.githubusercontent.com/.../main/...` for
  images, `github.com/.../blob/main/...` for files): PyPI shows the README but cannot resolve relative paths.
