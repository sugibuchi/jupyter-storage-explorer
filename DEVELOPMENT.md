# Development

## Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with two packages, released
together with the same version (from the git tags):

| Package                             | Folder      | Contents                                                                 |
|-------------------------------------|-------------|--------------------------------------------------------------------------|
| `jupyter-storage-explorer`          | `.`         | The widgets `StorageExplorer` and `DataExplorer`; pure Python, no build. |
| `jupyter-storage-explorer-launcher` | `launcher/` | The JupyterLab launcher item, and `launch()` run in the tab it opens.    |

| Path                                                           | Contents                                                                     |
|----------------------------------------------------------------|------------------------------------------------------------------------------|
| `src/jupyter_storage_explorer/`                                | The widgets, formats and the data browser.                                   |
| `src/jupyter_storage_explorer/static/`                         | The widgets' JavaScript and CSS, loaded at run time (no build step).         |
| `launcher/src/jupyter_storage_explorer_launcher/`              | `launch()`, which reads the user's `storage-explorer/launcher.py`.           |
| `launcher/labextension/`                                       | The JupyterLab extension (TypeScript).                                       |
| `launcher/src/jupyter_storage_explorer_launcher/labextension/` | The extension built from `launcher/labextension/` (git-ignored).             |
| `notebooks/`                                                   | Demo notebooks and `make_samples.py`, which writes the sample data they use. |

All Python commands go through [uv](https://docs.astral.sh/uv/). Node.js, needed only to build the extension, comes
with the dev dependencies (`nodejs-wheel`), so `uv run node` and `uv run jlpm` work without installing it.

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
   checks it (version X.Y.Z), creates the GitHub release with it and notes generated from the merged pull requests
   (edit them on GitHub afterwards if needed), and publishes it to PyPI.
2. **Release launcher** (`.github/workflows/release-launcher.yaml`), run when the first has succeeded (so the package
   the launcher depends on is on PyPI), builds the JupyterLab extension and `jupyter-storage-explorer-launcher` for the
   same tag, checks them (version X.Y.Z, the wheel has the extension), adds them to the GitHub release and publishes
   them to PyPI. To retry it, run it by hand for the tag: *Actions ▸ Release launcher ▸ Run workflow*.

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

## Customizing icons

Rows in the explorer carry attributes you can style with CSS:

- **Folders** (tree and list): `data-depth`, their level below the top folder: `0` for the top folder itself, `1` for
  the folders in it, and so on.
- **Files** (list): `data-file-format`, the format name in lower case with `-` for spaces: `parquet`, `csv`, `json`,
  `json-lines`, `excel-workbook`, `markdown`, `text`, `image`. Files of no known format, or without a URL, have none.

Run CSS in a notebook cell, before or after the explorer. This example shows the top folder as a grey container,
the folders in it in blue-grey and deeper folders in yellow, and gives data files their own icons:

```python
from IPython.display import HTML

HTML("""<style>
/* Folders: draw an SVG shape in a colour, both chosen per depth below */
.jse-browser [data-depth] .jse-icon { font-size: 0; }
.jse-browser [data-depth] .jse-icon::before {
  content: ""; display: inline-block; width: 16px; height: 13px; vertical-align: -2px;
  background: var(--folder-color);
  -webkit-mask: var(--folder-shape) no-repeat center / contain;
          mask: var(--folder-shape) no-repeat center / contain;
}
.jse-browser [data-depth] {
  --folder-color: #eab308;
  --folder-shape: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 13'%3E%3Cpath d='M0 1.5A1.5 1.5 0 0 1 1.5 0h4l1.5 2h7.5A1.5 1.5 0 0 1 16 3.5v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 0 11.5z'/%3E%3C/svg%3E");
}
.jse-browser [data-depth="1"] { --folder-color: #64748b; }
.jse-browser [data-depth="0"] {
  --folder-color: #6b7280;
  --folder-shape: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 13'%3E%3Cpath fill-rule='evenodd' d='M1 0.5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1zM3 3v7h1.3V3zM6 3v7h1.3V3zM9 3v7h1.3V3zM12 3v7h1.3V3z'/%3E%3C/svg%3E");
}

/* Files: a different emoji per format */
.jse-browser [data-file-format] .jse-icon { font-size: 0; }
.jse-browser [data-file-format] .jse-icon::before { font-size: 14px; content: "📄"; }
.jse-browser [data-file-format="csv"] .jse-icon::before,
.jse-browser [data-file-format="excel-workbook"] .jse-icon::before { content: "📊"; }
.jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
.jse-browser [data-file-format="image"] .jse-icon::before { content: "🖼️"; }
.jse-browser [data-file-format="markdown"] .jse-icon::before { content: "📝"; }
</style>""")
```

`HTML(...)` must be the last line of the cell (or use `display(HTML(...))`). The style lasts until the page is reloaded.
To apply it to every notebook, save the CSS (without `<style>`) to `~/.jupyter/custom/custom.css` and start JupyterLab
with `jupyter lab --LabApp.custom_css=True`. For the tab opened from the launcher, return the CSS from a `style()`
function in `storage-explorer/launcher.py` (see the [launcher's README](launcher/README.md)).
