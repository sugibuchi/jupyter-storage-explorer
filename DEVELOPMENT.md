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
| `jupyter-storage-explorer-<name>-support` | `plugins/<name>-support/` | The plugins: `polars`, `pandas`, `pyspark` (engines) and `abfs` (Azure Data Lake Storage operations). |

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
uvx ruff check src launcher/src plugins tests docs/scripts   # lint
uv run npx --yes prettier@3.3.3 --check .            # formatting: the widgets' JS and CSS, the extension's TS
uv run tests/browser/check_js.py                     # their JavaScript: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py           # the widgets in a real JupyterLab
```

CI runs the first four and compiles the extension's TypeScript. It does not run the smoke test: run it yourself after
changing `static/` or the extension.

The JavaScript has no unit tests. Instead, `tests/browser/smoke.py` starts a JupyterLab of its own and clicks through
the main features in the installed Microsoft Edge: browsing, previews, the data browser, file operations, transfers and
the launcher's tab. Give check names to run only those. A failed check leaves a screenshot,
`tests/browser/smoke-<check>.png`.

For performance, `uv run tests/performance/benchmark.py` times what users wait for: opening large folders, clicks,
copies and scrolling the data browser. It runs on a memory filesystem with a latency per call, so that round trips
count as on cloud storages. Compare its timings before and after a change, on the same machine.

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
- **Formats** (`formats/`) detect, preview, query and generate code for each kind of file.

CLAUDE.md describes each part in more detail.

## Design

### Security

The explorer runs in the user's kernel, as their code does: it can do what their code can, and no more. Keep it so.

- **Credentials** come from the environment, as each storage's library finds them: an AWS profile, an Azure CLI login
  or managed identity, Google's default credentials. Options given to a storage work too.
- **The explorer never asks for secrets**, and never reads them from environment variables. Asking would happen in
  every kernel: each launcher tab, each notebook. Secrets in environment variables are a practice we do not support.
- **"Python code" leaves out credentials**: options declared secret, and options whose names look like credentials.
- **Nothing is added to the Jupyter server**: no server extension, no endpoints reaching storages. The launcher's
  JupyterLab extension only shows explorers and passes the frontend's requests to their kernels.
- **Unsafe mode and the transfer policy prevent mistakes**; they are not a security boundary: code in the kernel can
  do whatever its credentials allow.
- **Notebooks opened from a storage** (Edit) are untrusted unless signed, as JupyterLab's own are. Their outputs' HTML
  and scripts do not run until the user trusts them. The kernel checks signatures with nbformat's notary, as
  jupyter_server does, and signs a notebook saved while trusted.
- **What storages hold is shown, never run**:
  - names show control and invisible characters as `\uXXXX` (`visible()`);
  - Markdown is sanitized;
  - a format's own icon is shown as an image, in which scripts do not run.
- **Pages cannot name files**: drags carry only a random id, so drags from other browser tabs or sites are refused.
- **Files pasted from another kernel** are read with one of the explorer's storages. For the kinds of storage the
  mappers know (Azure, S3, Google Cloud Storage, SFTP), the explorer may also open one with the user's credentials.
  An unknown URL is never opened (`MapperChain.locate`).

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

The icons are JupyterLab's file browser's, as SVG images (`.jse-icon svg`).

- **Files** get the icon of their format (its `file_icon`, one of `FILE_ICONS` in `formats/base.py`), else of their
  extension. A format can bring an icon of its own, `file_icon = ("avro", "<svg ...>...</svg>")`, shown as an image
  (`.jse-icon img`).
- **Folders that a storage makes more than folders** get icons of their own: Azure accounts and containers, S3 and
  GCS buckets, SFTP servers, local drives, the memory filesystem, and Databricks' catalogs, schemas, volumes and
  workspace folders. The filesystem's mapper tells which they are (`FileSystemMapper.level`, see
  [development-plugin.md](docs/development-plugin.md)).
- **Azure, S3, GCS and Databricks** icons are in their cloud's colour, the variable `--jse-storage-color`. For example,
  `.jse-browser[data-fs-protocol="s3"] { --jse-storage-color: green; }`, or `initial` for JupyterLab's grey.

The explorer and its rows carry attributes to select them by:

| Selector                                  | Rows                                                                                                   |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------|
| `.jse-browser`                            | The explorer. Every selector starts with it, so nothing else on the page changes.                      |
| `.jse-browser[data-fs-protocol="s3"]`     | The explorer while it shows a storage of that protocol: `abfs`, `s3`, `gs`, `dbfs`, `sftp`, `file`, …  |
| `[data-fs-level="container"]`             | Folders by what the storage makes of them: `account`, `container`, `endpoint`, `bucket`, `host`, `drive`, `memory` |
| `[data-fs-level="catalog"]`               | Databricks' folders: `workspace`, `volumes`, `catalog`, `schema`, `volume`, `workspace-files`, `repos`, `users`, `shared`, `user`, `repository`, `legacy` |
| `[data-depth="0"]`, `[data-depth="1"]`, … | Folders in the tree and the list, by their level: `0` the top folder, `1` the folders in it, …    |
| `[data-file-format]`                      | Files of a known format (not those of no known format, or without a URL)                          |
| `[data-file-format="parquet"]`            | Files of one format: `parquet`, `csv`, `json`, `json-lines`, `excel`, `markdown`, `text`, `image` |
| `.jse-icon svg`, `.jse-icon::before`      | In a row, the icon's image, and where to show something else instead                              |

To change an icon, hide its image and show something else in its `::before`, e.g. an emoji. This CSS shows the top
folder as 🗄️, the folders in it as 🗃️ (deeper ones keep the folder icon), and gives data files their own icons:

```css
/* Folders: an emoji per depth */
.jse-browser :is([data-depth="0"], [data-depth="1"]) .jse-icon svg {
    display: none;
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
}
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
