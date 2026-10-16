# Development

## Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with two packages, released
together with the same version (from the git tags). The launcher requires the explorer of exactly its version
(`launcher/hatch_build.py`, which sets its dependencies), as it uses the explorer's internals:

| Package                             | Folder      | Contents                                                                 |
|-------------------------------------|-------------|--------------------------------------------------------------------------|
| `jupyter-storage-explorer`          | `.`         | The widgets `StorageExplorer` and `DataExplorer`; pure Python, no build. |
| `jupyter-storage-explorer-launcher` | `launcher/` | The JupyterLab launcher item, and `launch()` run in the tab it opens.    |

| Path                                                           | Contents                                                                     |
|----------------------------------------------------------------|------------------------------------------------------------------------------|
| `src/jupyter_storage_explorer/`                                | The widgets, formats and the data browser.                                   |
| `src/jupyter_storage_explorer/_explorer/`                      | `StorageExplorer`'s features, as mixins of the class.                        |
| `src/jupyter_storage_explorer/static/`                         | The widgets' JavaScript and CSS, loaded at run time (no build step).         |
| `src/jupyter_storage_explorer/static/storage_explorer/`        | The storage explorer's JavaScript, a file per feature, joined at run time.   |
| `launcher/src/jupyter_storage_explorer_launcher/`              | `launch()`, which merges the `storage-explorer/launcher.py` files (layers).  |
| `launcher/labextension/`                                       | The JupyterLab extension (TypeScript).                                       |
| `launcher/src/jupyter_storage_explorer_launcher/labextension/` | The extension built from `launcher/labextension/` (git-ignored).             |
| `notebooks/`                                                   | Demo notebooks and `make_samples.py`, which writes the sample data they use. |
| `tests/browser/`                                               | Checks of the widgets' JavaScript, and their smoke test in a browser.        |
| `docs/scripts/`                                                | Scripts making the docs' screenshots and the demo GIFs.                      |

All Python commands go through [uv](https://docs.astral.sh/uv/). Node.js, for the extension and the JavaScript's checks,
comes with the dev dependencies (`nodejs-wheel`), so `uv run node`, `uv run npx` and `uv run jlpm` work without
installing it.

## Setup

```bash
uv sync                    # both packages, editable, with the dev dependencies
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
uvx ruff check src launcher/src tests docs/scripts   # lint
uv run npx --yes prettier@3.3.3 --check .            # the widgets' JavaScript and CSS formatting
uv run tests/browser/check_js.py                     # their JavaScript: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py           # the widgets in a real JupyterLab
```

CI runs the first four. The JavaScript has no unit tests: `tests/browser/smoke.py` clicks through the widgets' main
features (browsing, previews, the data browser, file operations, uploads and downloads, the launcher's extension) in a
JupyterLab of its own, with the installed Microsoft Edge. CI does not run it: run it after changing `static/` or the
extension. Give check names to run only those; a failed check leaves a screenshot, `tests/browser/smoke-<check>.png`.

## How the code fits together

- **`StorageExplorer`** (`storage_explorer.py`) holds the widget's state and routes the frontend's messages
  (`_requests()`, answered with a reply, and `_notices()`); each feature is a mixin of it in `_explorer/` (the list and
  tree, previews, bookmarks, JupyterLab's files, jobs, file operations).
- **Its frontend** is a file per feature in `static/storage_explorer/` (the list, tree, preview, menus, operations,
  transfers, ...), each a `createX(x)` sharing the explorer `x` made in `storage_explorer.js`; the kernel joins them
  into one module with the shared `common.js` and `query.js` (`_static.py`), as anywidget cannot import files.
- **File operations** are planned by `FileTasks` (`file_tasks.py`), run as jobs in a worker thread (`jobs.py`), and
  done by a chain of `FileSystemOperations` objects (`operations.py`, `filesystems/`), which users can extend.
- **The data browser** is `DataQuery` (`query.py`), on any dataframe narwhals supports; `DataExplorer` shows it alone.
- **Formats** (`formats/`) detect, preview, scan and generate code for each kind of file.

CLAUDE.md describes each part in more detail.

## The JupyterLab extension

The extension is not built when the package is built: build it yourself with `jlpm` in `launcher/labextension/`. The
build output and `node_modules` are git-ignored, so commits do not keep them; they stay on disk until removed.

| Command (in `launcher/labextension/`) | Run it again when                                                                                        |
|---------------------------------------|----------------------------------------------------------------------------------------------------------|
| `uv run jlpm install`                 | `node_modules` is missing (new clone or machine), or `package.json` dependencies or `yarn.lock` changed. |
| `uv run jlpm build`                   | `src/`, `style/` or `package.json` changed, or the build output is missing.                              |
| `uv run jlpm build:prod`              | Before every release (a production build, without source maps).                                          |

After a build, run `uv sync` in the repository folder (it reinstalls the launcher package, copying the build to
`.venv/share/jupyter/labextensions`), then restart JupyterLab and reload the page.

Changes to the Python code or to `src/jupyter_storage_explorer/static/` need no build: restart the kernel.

Commit `package.json`, `yarn.lock`, `.yarnrc.yml`, `tsconfig.json`, `src/` and `style/` of `launcher/labextension/`;
not `node_modules/`, `lib/` or `.yarn/`.

## Releasing

Releases are made by GitHub Actions: push a version tag from `main`,

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

1. **Release explorer** (`.github/workflows/release-explorer.yaml`), run by the tag, builds `jupyter-storage-explorer`,
   checks it (version X.Y.Z), creates the GitHub release with it and notes generated from the merged pull requests (edit
   them on GitHub afterwards if needed), and publishes it to PyPI.
2. **Release launcher** (`.github/workflows/release-launcher.yaml`), run when the first has succeeded (so the package
   the launcher depends on is on PyPI), builds the JupyterLab extension and `jupyter-storage-explorer-launcher` for the
   same tag, checks them (version X.Y.Z, the wheel has the extension and requires `jupyter-storage-explorer==X.Y.Z`),
   adds them to the GitHub release and publishes them to PyPI. To retry it, run it by hand for the tag:
   *Actions ▸ Release launcher ▸ Run workflow*.

### Release notes

Once both workflows have succeeded, replace the generated notes (`gh release edit vX.Y.Z --notes-file notes.md`) with
these sections, leaving out those with nothing to say, and keeping the generated ones at the end:

- **New**, **Changes**, **Fixes**: one item each, saying what users can now do or what behaves differently, with the
  option or function names.
- **Breaking changes**: what users must change in their code or `launcher.py`, and how.
- Links to the documentation of the new features (absolute GitHub URLs).
- **Install**: the `pip install -U` command for both packages, and that the launcher requires the explorer of the same
  version (restart JupyterLab after upgrading it).
- **What's Changed** and **Full Changelog**: as generated.

### One-time setup for PyPI

The workflows publish with PyPI's [trusted publishing](https://docs.pypi.org/trusted-publishers/), without a token:

1. On PyPI, add a trusted publisher for each project (for a project not on PyPI yet, as a *pending publisher* under
   *Your account ▸ Publishing*), with the owner and repository of this GitHub repository and environment `pypi`:

   | PyPI project                        | Workflow                  |
   |-------------------------------------|---------------------------|
   | `jupyter-storage-explorer`          | `release-explorer.yaml`   |
   | `jupyter-storage-explorer-launcher` | `release-launcher.yaml`   |

2. On GitHub, create the environment `pypi` (*Settings ▸ Environments*); optionally require a reviewer there, so that
   publishing waits for approval.

### By hand

To build the packages locally, e.g. to publish them to another repository such as an internal Nexus:

```bash
cd launcher/labextension
uv run jlpm install        # only if package.json or yarn.lock changed
uv run jlpm build:prod
cd ../..
uv build --all-packages    # sdists and wheels of both packages, in dist/
uv publish --publish-url <url> dist/*
```

`<url>` is the repository's upload URL (e.g. `https://nexus.example.com/repository/pypi-internal/`); `uv publish` asks
for the credentials, or takes them from `UV_PUBLISH_USERNAME` / `UV_PUBLISH_PASSWORD`. Build from a clean checkout of
the tag: uncommitted changes give a version like `X.Y.Z.post0+g<commit>.d<date>`. If the extension was not built,
`uv build` still succeeds, but the launcher's wheel has no launcher item; `uv build` also packages whatever was built
last, so run `build:prod` just before it.

## Documentation

The root `README.md` is the quick start and highlights, shown on PyPI too: links and images there are absolute URLs on
GitHub, as PyPI cannot resolve relative paths. The details are in `docs/` (`storage-explorer.md`, `data-explorer.md`),
read on GitHub only, which link to each other and to the repository's files with relative paths.

The screenshots (`docs/figs/`, `launcher/figs/`) and the demo GIFs are made by the scripts in
[`docs/scripts/`](docs/scripts/README.md), with Playwright and the installed Microsoft Edge, from a made-up data lake in
memory. Their packages are in the `docs` dependency group, which `uv sync` does not install:

```bash
uv run --group docs docs/scripts/make_all.py
```

## Customizing icons

Rows in the explorer carry attributes you can style with CSS:

- **Folders** (tree and list): `data-depth`, their level below the top folder: `0` for the top folder itself, `1` for
  the folders in it, and so on.
- **Files** (list): `data-file-format`, the format name: `parquet`, `csv`, `json`, `json-lines`, `excel`, `markdown`,
  `text`, `image`. Files of no known format, or without a URL, have none.

The icons are JupyterLab's file browser's, as SVG images (`.jse-icon svg`), chosen by the file's extension. To change
one, hide its image and show something else in its `::before`, e.g. an emoji. Run the CSS in a notebook cell,
before or after the explorer. This example shows the top folder as 🗄️, the folders in it as 🗃️ (deeper ones keep the
folder icon), and gives data files their own icons:

```python
from IPython.display import HTML

HTML("""<style>
/* Folders: an emoji per depth */
.jse-browser :is([data-depth="0"], [data-depth="1"]) .jse-icon svg { display: none; }
.jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
.jse-browser [data-depth="1"] .jse-icon::before { content: "🗃️"; }

/* Files: an emoji per format */
.jse-browser [data-file-format] .jse-icon svg { display: none; }
.jse-browser [data-file-format] .jse-icon::before { content: "📄"; }
.jse-browser [data-file-format="csv"] .jse-icon::before,
.jse-browser [data-file-format="excel"] .jse-icon::before { content: "📊"; }
.jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
.jse-browser [data-file-format="image"] .jse-icon::before { content: "🖼️"; }
.jse-browser [data-file-format="markdown"] .jse-icon::before { content: "📝"; }
</style>""")
```

`HTML(...)` must be the last line of the cell (or use `display(HTML(...))`). The style lasts until the page is reloaded.
To apply it to every notebook, save the CSS (without `<style>`) to `~/.jupyter/custom/custom.css` and start JupyterLab
with `jupyter lab --LabApp.custom_css=True`. For the tab opened from the launcher, return the CSS from a `style()`
function in `storage-explorer/launcher.py` (see the [launcher's README](launcher/README.md)).
