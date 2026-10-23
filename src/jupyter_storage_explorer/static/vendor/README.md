# Vendored JavaScript libraries

Used to render Markdown previews in the browser. They are loaded on demand:
the widget asks the kernel for a file's source (only the files listed in
`storage_explorer.py`'s `_VENDOR_FILES`) and imports it as a module.

| File | Library | Version | License |
|---|---|---|---|
| `marked.esm.js` | [marked](https://github.com/markedjs/marked) (the Markdown parser JupyterLab uses) | 16.4.2 | MIT, see `marked.LICENSE.md` |
| `purify.es.mjs` | [DOMPurify](https://github.com/cure53/DOMPurify) (removes scripts etc. from the HTML) | 3.4.16 | Apache-2.0 or MPL-2.0, see `dompurify.LICENSE` |

Downloaded unmodified from jsDelivr (`npm/marked@16.4.2/lib/marked.esm.js`,
`npm/dompurify@3/dist/purify.es.mjs`), except that the trailing
`//# sourceMappingURL=` line was removed, as the source maps are not included.

## Icons

The SVG paths of `ICON_PATHS` in `../icons.js` (menus, buttons) are from
[Material Design Icons](https://github.com/google/material-design-icons) (filled style), as JupyterLab's own icons
are. Apache License 2.0, https://www.apache.org/licenses/LICENSE-2.0.

`ICONS` in `../../filesystems/level_icons.py` (the icons of accounts, containers, buckets, hosts, drives, memory and
Databricks' folders in the tree and list, which the predefined mappers' CSS shows): `cloud`, `box` (`inventory_2`), `server` (`dns`), `chip` (`memory`), `work`, `group`, `person`
and `folder-shared` (`folder_shared`) from the same Material Design Icons; `book2` (`book_2`) and `files` from
[Material Symbols](https://github.com/google/material-design-icons) (filled, `@material-symbols/svg-400` 0.27.0);
`bucket`, `harddisk`, `bookshelf`, `database`, `repository` (`source-repository`), `repositories`
(`source-repository-multiple`) and `folder-clock` from
[Pictogrammers' Material Design Icons](https://github.com/Templarian/MaterialDesign) (`@mdi/svg` 7.4.47). All Apache
License 2.0. No cloud provider's own icons: their licences allow them in diagrams and documents only.

`FILE_ICON_SVGS` there (the tree and list) are JupyterLab's file icons, copied from JupyterLab 4.6.4
(`@jupyterlab/ui-components`), and `FILE_ICON_EXTENSIONS` its default file types' extensions, for files whose format sets
no icon (plus old Excel files, with its CSV icon). BSD-3-Clause,
Copyright (c) 2015-2026 Project Jupyter Contributors, https://github.com/jupyterlab/jupyterlab/blob/main/LICENSE.
