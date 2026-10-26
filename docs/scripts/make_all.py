"""Make every picture of the docs and the demo GIFs, on one JupyterLab server.

uv run --group docs docs/scripts/make_all.py
"""

from __future__ import annotations

import _lab
import actions_menu
import browser
import data_explorer
import data_explorer_gif
import file_transfer_gif
import hero
import launcher_item
import launcher_settings
import launcher_side_panel
import logging_menu
import storage_explorer_gif
import unsafe
import using

SCRIPTS = (
    hero,
    using,
    unsafe,
    actions_menu,
    logging_menu,
    browser,
    data_explorer,
    launcher_item,
    launcher_settings,
    launcher_side_panel,
    storage_explorer_gif,
    data_explorer_gif,
    file_transfer_gif,
)


def main() -> None:
    with _lab.lab() as lab:
        for script in SCRIPTS:
            script.make(lab)


if __name__ == "__main__":
    main()
