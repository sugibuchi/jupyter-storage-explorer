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
| `src/jupyter_storage_explorer/`                                | The widgets: `storage_explorer.py`, `data_explorer.py`.                      |
| `src/jupyter_storage_explorer/filesystems/`                    | Filesystems' URLs and identities (mappers) and file operations: interfaces users extend, and the default ones. |
| `src/jupyter_storage_explorer/formats/`                        | The formats files are previewed, queried and loaded as.                      |
| `src/jupyter_storage_explorer/_explorer/`                      | `StorageExplorer`'s features, as mixins of the class.                        |
| `src/jupyter_storage_explorer/_jobs/`                          | File operations planned and run as jobs, without the widget.                 |
| `src/jupyter_storage_explorer/_query/`                         | The data browser: filters, settings, and a dataset open in it.               |
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
uv run npx --yes prettier@3.3.3 --check .            # formatting: the widgets' JS and CSS, the extension's TS
uv run tests/browser/check_js.py                     # their JavaScript: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py           # the widgets in a real JupyterLab
```

CI runs the first four, and compiles the extension's TypeScript. The JavaScript has no unit tests:
`tests/browser/smoke.py` clicks through the widgets' main features (browsing, previews, the data browser, file
operations, uploads and downloads, the launcher's extension and its tab, reopened after a page reload and replaced after
a kernel restart) in a JupyterLab of its own, with the installed Microsoft Edge. CI does not run it: run it after
changing `static/` or the extension. Give check names to run only those; a failed check leaves a screenshot,
`tests/browser/smoke-<check>.png`.

## How the code fits together

- **`StorageExplorer`** (`storage_explorer.py`) holds the widget's state and routes the frontend's messages
  (`_requests()`, answered with a reply, and `_notices()`); each feature is a mixin of it in `_explorer/` (the list and
  tree, previews, bookmarks, JupyterLab's files, jobs, file operations).
- **Its frontend** is a file per feature in `static/storage_explorer/` (the list, tree, preview, menus, operations,
  transfers, ...), each a `createX(x)` sharing the explorer `x` made in `storage_explorer.js`; the kernel joins them
  into one module with the shared `common.js` and `query.js` (`_static.py`), as anywidget cannot import files.
- **File operations** are planned by `FileTasks` (`_jobs/tasks.py`), run as jobs in a worker thread (`_jobs/runner.py`),
  and done by a chain of `FileSystemOperations` objects (`filesystems/`), which users can extend. Mappers there
  (`FileSystemMapper`) tell filesystems apart and give their URLs.
- **The data browser** is `DataQuery` (`_query/`), on any dataframe narwhals supports; `DataExplorer` shows it alone.
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

## Customizing

Icons are changed with CSS; how storages are named and how files are moved and copied, with Python objects given to
`StorageExplorer` (or returned by functions of the launcher's `storage-explorer/launcher.py`, see the
[launcher's README](launcher/README.md)), each tried before the defaults.

### Icons

The icons are JupyterLab's file browser's, as SVG images (`.jse-icon svg`), chosen by the file's extension. Rows in
the explorer carry attributes to select them by:

| Selector                                 | Rows                                                                                     |
|------------------------------------------|------------------------------------------------------------------------------------------|
| `.jse-browser`                           | The explorer (every selector starts with it, so nothing else on the page changes)        |
| `[data-depth="0"]`, `[data-depth="1"]`, … | Folders in the tree and the list, by their level: `0` the top folder, `1` the folders in it, … |
| `[data-file-format]`                     | Files of a known format (not those of no known format, or without a URL)                 |
| `[data-file-format="parquet"]`           | Files of one format: `parquet`, `csv`, `json`, `json-lines`, `excel`, `markdown`, `text`, `image` |
| `.jse-icon svg`, `.jse-icon::before`     | In a row, the icon's image, and where to show something else instead                     |

To change an icon, hide its image and show something else in its `::before`, e.g. an emoji. This CSS shows the top
folder as 🗄️, the folders in it as 🗃️ (deeper ones keep the folder icon), and gives data files their own icons:

```css
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
```

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

1. Save the CSS (without `<style>`) as `custom/custom.css` in Jupyter's configuration directory, which
   `jupyter --config-dir` prints: `~/.jupyter/custom/custom.css` by default (on Windows,
   `%USERPROFILE%\.jupyter\custom\custom.css`), or `$JUPYTER_CONFIG_DIR/custom/custom.css` where
   `JUPYTER_CONFIG_DIR` is set. JupyterLab reads it from there only, not from the other configuration directories
   (`jupyter --paths`), so for several users, set `JUPYTER_CONFIG_DIR` or put the file in each user's. For example,
   `~/.jupyter/custom/custom.css`:

   ```css
   /* Storage Explorer: the top folder as 🗄️, Parquet files as 🧱 */
   .jse-browser [data-depth="0"] .jse-icon svg { display: none; }
   .jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
   .jse-browser [data-file-format="parquet"] .jse-icon svg { display: none; }
   .jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
   ```

2. Turn it on, in any of Jupyter's configuration directories (`jupyter --paths`), e.g. for one user
   `~/.jupyter/jupyter_lab_config.py`, for an environment `<env>/etc/jupyter/jupyter_lab_config.py`, or for everyone
   `/etc/jupyter/jupyter_lab_config.py`:

   ```python
   c.LabApp.custom_css = True
   ```

   or start JupyterLab with `jupyter lab --custom-css`.
3. Restart JupyterLab, then reload the page.

The launcher's `style()` (in `storage-explorer/launcher.py`) applies only while an explorer tab is open, not to
explorers in notebooks.

### Filesystem mappers

A `FileSystemMapper` (`filesystems/mapper.py`) describes the filesystems of one fsspec implementation:

- `identifier(fs)`: which storage the instance is connected to, e.g. the account for Azure or the server and user
  for SFTP. Two instances with the same identifier are the same storage, so the explorer moves files between them
  within the storage, and finds files copied or dragged from another kernel on it.
- `to_url(fs, path)`: the URL of a path, shown by "Copy URL" and used in "Python code", previews and the transfer
  policy.
- `path_of(fs, url)`: the reverse.

The predefined mappers (`filesystems/mappers.py`) cover Azure, S3, Google Cloud Storage, SFTP, local disks and memory;
others get fsspec's URLs and are told apart as fsspec compares them.

```python
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems import FileSystemMapper


class MyMapper(FileSystemMapper):
    protocol = "myfs"
    classes = ("mypackage.MyFileSystem",)  # matched by name, subclasses too

    def identifier(self, fs):
        return {"server": fs.server.lower()}  # never credentials

    def to_url(self, fs, path):
        return f"myfs://{fs.server.lower()}/{path.lstrip('/')}"

    def path_of(self, fs, url):
        scheme, _, rest = url.partition("://")
        return rest.partition("/")[2] if scheme == "myfs" else None


StorageExplorer(fs=my_fs, filesystem_mappers=[MyMapper()])
```

In `launcher.py`, return them from `filesystem_mappers()`. `tests/test_mappers.py` shows how to test one with a stand-in
class, without the storage's package.

### File operations

A `FileSystemOperations` (`filesystems/operation.py`) moves, copies, deletes, uploads, downloads, measures files and
creates folders, a method each. The explorer calls each operation on the first object that does not raise
`FileSystemOperations.NotSupported`, so an object can do some operations for some storages and leave the rest to the
defaults (`filesystems/operations.py`, with fsspec). `move` and `copy` are told with `same` whether the source and
target are one filesystem, as the mappers tell; `_copy_file` and `_move_file` copy or move single files between
filesystems and can be overridden alone.

```python
from jupyter_storage_explorer.filesystems import FileSystemOperations


class ServerSideCopy(FileSystemOperations):
    """Copies within one storage with its own API; everything else as by default."""

    def copy(self, source_fs, source, target_fs, target, progress, *, same):
        if not same or not isinstance(source_fs, MyFileSystem):
            raise self.NotSupported
        progress.working_on(source.rsplit("/", 1)[-1])
        source_fs.server_copy(source, target)


StorageExplorer(fs=my_fs, operations=[ServerSideCopy()])
```

Operations run in a worker thread: report to `progress` and call `progress.check()` between steps, so that Cancel
stops them. In `launcher.py`, return them from `operations()`. `AzureDataLakeGen2Operation` (`filesystems/abfs.py`) is
a complete example.
