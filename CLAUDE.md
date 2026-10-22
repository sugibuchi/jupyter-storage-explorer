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

CI, in `.github/workflows/ci.yaml`, runs on pull requests and pushes to `main`:

- ruff, Prettier and `check_js.py`;
- pytest with coverage, uploaded to Codecov;
- pyspark-support's tests alone, on a local Spark with Java: the `spark` job;
- a compile of the launcher's extension with `jlpm build:lib`, which needs `yarn.lock` up to date.

Releases are GitHub Actions run by a version tag, which the maintainer pushes. DEVELOPMENT.md describes them, with
the release notes' sections. In the workflows, pin `astral-sh/setup-uv` to a full version, e.g. `@v10.3.0`: since v8
it publishes no major-version tags.

Python and `static/` changes need no build: restart the kernel. The launcher's extension, in `launcher/labextension/`,
is built by hand: `uv run jlpm install` and `uv run jlpm build` there, then `uv sync` at the root. Then restart
JupyterLab.

## Tests and layout

DEVELOPMENT.md describes the packages, the public API, the tests and the launcher. Read its Tests section before
writing tests. The traps:

- `uv run pytest` at the root runs the explorer's and the plugins' tests. A plugin's alone runs in its folder, with
  `uv run --isolated --package <its package> pytest`, never a plain `uv run`: that installs its `dev` group into the
  shared `.venv`.
- Test folders have no `__init__.py`. Never import one test file from another: share code through the helpers at the
  top of `tests/`. Test files' names must be unique across the folders.
- Use the fixtures of `jupyter_storage_explorer.testing`: `memfs`, `make_item`, `local_item`. `tests/conftest.py` adds
  `mem_explorer` and `local`.
- polars cannot read `memory://`: what it reads by URL needs real files in `tmp_path`.
- The core's tests have no Spark: sqlframe stands in for it. pyspark-support's view tests need Java.
- Widget tests capture `send()` and drive the widget through `_on_custom_msg`. `StorageExplorer`'s go in a
  `tests/explorer/test_explorer_*.py` per feature, on `tests/explorers.py`.
- The JavaScript has no unit tests. Run the smoke test after any change to `static/` or the extension, and add a check
  for each new feature. Drag and drop works only in a browser, not in IntelliJ's notebook view.
- The launcher and the plugins pin the explorer of their exact version in their `hatch_build.py`. Add their new
  dependencies there.
- Users import only from the top level, `filesystems`, `formats`, `formats.supports` and the plugins' packages. Keep
  the explorer's machinery out of their `__all__`.
- `static/storage-explorer.svg` is a copy of the launcher's icon: change both.

## Architecture

DEVELOPMENT.md's Architecture section describes each part: read it before changing one. docs/development-plugin.md
has the rules for formats, supports, options, operations, mappers and plugins: follow them, and keep them in step with
the code. The traps:

- Traits are underscore-prefixed in every widget: a public trait would be public API.
- Traitlets observers must be on `StorageExplorer` itself. The mixins in `_explorer/` hold only methods.
- Only `StorageExplorer`'s *File operations* block calls fsspec on the storage shown.
- In JavaScript, file names, paths and messages naming files go through `visible()`, never as they are.
- Show the kernel's errors with `errorBlock()`, and flash them with `x.flash(message, { error: true })`: a plain flash
  is gone after 1.5 seconds.
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
- The reads of a preview or a view tab run in a worker thread too, as a load (`_jobs/loader.py`). Take what they need of the explorer,
  such as `_fs` and `_engine`, on the main thread before, and show the result in the load's `done`.
- Detect an item with `_detection(path, fs)`, on the main thread, and wait for its future in a load's work: a click's
  selection, menu and preview share one detection.
- The data browser's requests run in the lane of their query (`Loader.answer`). Close a query or table set with
  `close_in_lane`, never directly, except at the kernel's exit (`now=True`).
- Without a running asyncio loop, as in tests, jobs and loads run synchronously. Tests of the threaded path run in
  `asyncio.run`, with `until` from `tests/in_a_kernel.py`.
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

### Code

- Comments and docstrings are written in full sentences explaining *why*. Keep that density and tone.
- `from __future__ import annotations` everywhere, with type-only imports under `TYPE_CHECKING`: ruff's `TC` rules.
- A new feature of the storage explorer is one mixin in `_explorer/` and one part in `static/storage_explorer/`. Its
  tests go in a `tests/explorer/test_explorer_*.py`. What users do also gets a check in `tests/browser/smoke.py`.

### Docstrings

Docstrings of the public API are in numpy style: `Parameters`, `Returns`, `Raises`, `Attributes`, `See Also`,
`Examples`. The public API is what users construct, call, subclass or override:

- `StorageExplorer`, `DataExplorer`, `fetch_rows` and `QuerySettings`;
- `ExplorerStates`, with `Bookmark` and `QueryState`;
- `FileSystemOperations` and its subclasses, with `_copy_file` and `_move_file`, and `Measurement` and `Progress`;
- `DataFormat`, `FormatSupport` and `View`;
- `Location`, `FileSystemMapper` and their subclasses, `MapperChain` and `same_filesystem`.

Internal docstrings stay prose: underscore names, `DataQuery`, `FileTasks`, `JobRunner`, the mixins and the like.

### Writing docs

Write docs so that people can review them. That covers this file, DEVELOPMENT.md, `docs/` and the READMEs.

- One idea per sentence: about 30 words, never more than 50.
- At most one parenthesis per sentence, never nested.
- Three or more items make a list.
- Add a new fact as its own sentence or bullet where it belongs. Never append it to an existing sentence.
- Name an identifier only when the reader needs it to find the code. A function's details belong in its docstring.
- Describe what is, not what was: git keeps the history.
- When editing a passage that breaks these rules, rewrite it.

### Where docs go

- The root README is the quick start and the highlights. Update its highlights for new features.
- `docs/storage-explorer.md` has the user-facing details: installation, using the explorer, unsafe operations, the
  transfer policy, formats, format options and the explorer's options.
- Its last section, "Extensions", has the table of file operation extensions. Add new ones there.
- `docs/data-explorer.md` covers the data browser, `result()`, `on_change()`, `QuerySettings` and `DataExplorer`'s
  options.
- DEVELOPMENT.md has custom icons, in "Customizing", and how the code fits together, in "Architecture".
- docs/development-plugin.md covers extending the explorer in Python and packaging plugins, with the conventions.

Update the docs when operations, formats or options change. Keep user docs short: what users do, not how it works.

`supports`, `operations` and `filesystem_mappers` are for development. They come last in the docs, the options tables
and the launcher's template.

### Links and images

- The READMEs use absolute URLs for images and links to files, as PyPI shows them but cannot resolve relative paths.
  Images are `raw.githubusercontent.com/.../main/...`, files `github.com/.../blob/main/...`.
- `docs/` is read on GitHub only, so it uses relative paths.
- Screenshots are in `docs/figs/`, and the launcher's in `launcher/figs/`. They are taken at 2× and shown at their CSS
  size, with `<img width="...">`.

The screenshots and the demo GIFs are made by the scripts in `docs/scripts/`: `uv run --group docs
docs/scripts/make_all.py`, or one script. Change or add a script there rather than taking pictures by hand.

- Each script starts JupyterLab in a temporary folder, with its own settings.
- Explorers show a made-up data lake in fsspec's memory filesystem, from `demo_data.py`, so no local path appears.
