"""Make every picture of the docs and the demo GIF, on one JupyterLab server.

uv run --group docs docs/scripts/make_all.py
"""

from __future__ import annotations

import _lab
import browser
import data_explorer
import data_explorer_gif
import demo_gif
import hero
import launcher_item
import unsafe
import using

SCRIPTS = (
    hero,
    using,
    unsafe,
    browser,
    data_explorer,
    launcher_item,
    demo_gif,
    data_explorer_gif,
)


def main() -> None:
    with _lab.lab() as lab:
        for script in SCRIPTS:
            script.make(lab)


if __name__ == "__main__":
    main()
