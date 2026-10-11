# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All Python goes through uv (never call `python`/`pip` directly). Node.js comes with the dev dependencies
(`nodejs-wheel`), so `uv run jlpm` works without a Node install.

```bash
uv sync                              # both workspace packages, editable, with dev dependencies
uv run pytest                        # all tests (tests/)
uv run pytest tests/test_query.py -k range   # one file / matching tests
uvx ruff check src launcher/src tests  # lint (ruff is not a dev dependency; config in pyproject.toml)
uvx ruff format src launcher/src tests # format
uv run jupyter lab                   # try the widgets in a browser (see notebooks/)
uv run notebooks/make_samples.py     # regenerate the sample data the notebooks use
```

Tests cover the Python side only. Fixtures in `tests/conftest.py`: `memfs` (a cleared fsspec memory filesystem) and
`make_target` (writes a file there and returns its `Target`). Anything polars reads by URL (`scan`, polars previews,
the data browser) needs real local files (`tmp_path`), as polars cannot read `memory://`. The widget tests subclass the
widget to capture `send()` and drive it through `_on_custom_msg`, as the frontend would. The JavaScript is checked by
hand in JupyterLab; drag and drop in the widgets only works in a browser, not in IntelliJ's notebook view.

Python and `src/jupyter_storage_explorer/static/` changes need no build: restart the kernel. The launcher's JupyterLab
extension (`launcher/labextension/`, TypeScript) is built by hand: `uv run jlpm install` / `uv run jlpm build` there,
then `uv sync` at the root and restart JupyterLab. Releases are tag-driven GitHub Actions; see DEVELOPMENT.md.

## Layout

A uv workspace of two packages released together (version from git tags via hatch-vcs):

- `jupyter-storage-explorer` (root, `src/jupyter_storage_explorer/`): the anywidget widgets `StorageExplorer` and
  `DataExplorer`. Runtime dependencies are only anywidget, fsspec, pygments, traitlets; polars, pandas, pyarrow,
  deltalake, fastexcel, openpyxl, Pillow, PySpark are all optional and probed at run time.
- `jupyter-storage-explorer-launcher` (`launcher/`): a JupyterLab launcher item opening a tab whose kernel runs
  `launch()`, which loads the user's `storage-explorer/launcher.py` from Jupyter's config paths.

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

**Formats** (`formats/`). Each `DataFormat` subclass (`base.py`) declares `name`, `label`, `priority`, `extensions` and
which package sets can read it (`preferred_requirements` for previews and code, `code_only_requirements` such as PySpark
for code only, `query_requirements` for the data browser), and implements:
- `matches(target)`: cheap detection, called on every click; directory formats (Delta, Parquet datasets) inspect
  `target.children`. The highest `priority` wins (Delta 20 > Parquet 10 > default 0 > Text -10).
- `preview(target, limits)`: a list of `Preview` dataclasses (`TablePreview`, `TextPreview`, `TreePreview`,
  `MediaPreview`, `InstallPreview`...) that the frontend renders by `kind`; returns `install_hint()` when no package set
  is installed.
- `scan(url, is_dir)`: a polars LazyFrame for the data browser (`query.py`'s `DataQuery` does filters, sort, paging).
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
- The README documents user-facing options and formats; update its "Supported formats" and "Format options" tables when
  formats or options change.
