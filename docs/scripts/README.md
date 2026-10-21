# Scripts for the docs' pictures

These scripts take the screenshots in `docs/figs/` and `launcher/figs/`, and make the demo GIFs. Each one starts a
JupyterLab server of its own and drives it in the installed Microsoft Edge with Playwright.

```bash
uv run --group docs docs/scripts/make_all.py   # everything
uv run --group docs docs/scripts/using.py      # one script's pictures
```

Each script prints the size of each picture in CSS pixels. That is the `<img width="...">` the docs show it at, as
the pictures are taken at 2× (`data-explorer.png`, `launcher.png` and the GIFs are taken at 1×).

| Script                    | Makes                                                                 |
|---------------------------|-----------------------------------------------------------------------|
| `hero.py`                 | `docs/figs/storage-explorer.png`                                      |
| `using.py`                | `docs/figs/using-*.png` ("Using the explorer")                        |
| `unsafe.py`               | `docs/figs/unsafe-mode.png`                                           |
| `browser.py`              | `docs/figs/browser-*.png` ("Using the data browser")                  |
| `data_explorer.py`        | `docs/figs/data-explorer.png`                                         |
| `launcher_item.py`        | `launcher/figs/launcher.png`                                          |
| `launcher_settings.py`    | `launcher/figs/settings-*.png` (the settings button, `launcher.py`)   |
| `launcher_side_panel.py`  | `launcher/figs/side-panel.png` (the side panel, and a tab from View)  |
| `storage_explorer_gif.py` | `docs/figs/storage-explorer.gif`                                      |
| `data_explorer_gif.py`    | `docs/figs/data-explorer.gif`                                         |
| `file_transfer_gif.py`    | `docs/figs/file-transfer.gif` ("File transfer between file systems")  |
| `make_all.py`             | All of the above, on one server                                       |
| `_lab.py`                 | The server (in a temporary folder, with its own settings) and helpers |
| `_film.py`                | The GIFs' frames, and a mouse pointer drawn in the page               |
| `demo_data.py`            | The demo storage: a made-up sales data lake                           |

The explorers show the demo storage from fsspec's memory filesystem (`memory:///sales-lake`), so the pictures show no
path of your computer. Notebook widgets and launcher tabs alike get it: the server's Jupyter config folder has a
`storage-explorer/launcher.py` for them. `file_transfer_gif.py` gives its tabs a `launcher.py` of its own (`Lab.launcher_settings`), adding a
"Shared drive", a folder on the server's disk shown from its top (a `DirFileSystem`): the tabs' kernels cannot read each
other's memory, but both reach that folder.
