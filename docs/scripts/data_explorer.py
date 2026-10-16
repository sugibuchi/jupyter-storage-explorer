"""docs/figs/data-explorer.png, in the README: a notebook cell showing a
DataExplorer of the demo customers, a Delta Lake table. Taken at 1x, as the
README shows it at its own size.

uv run --group docs docs/scripts/data_explorer.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab

if TYPE_CHECKING:
    from _lab import Lab

SOURCE = """\
import polars as pl
from jupyter_storage_explorer import DataExplorer

DataExplorer(pl.scan_delta("sales-lake/curated/customers"))  # a Delta Lake table"""

# The picture's size in CSS pixels.
WIDTH, HEIGHT = 912, 548


def make(lab: Lab) -> None:
    with lab.page(1210, 900, scale=1) as page:
        lab.open_notebook(page, SOURCE)
        # Without the file browser, the notebook is as wide as the picture.
        page.keyboard.press("Control+b")
        page.wait_for_selector(".jse-data-explorer .jse-data tbody tr", timeout=60000)
        page.wait_for_timeout(2500)
        page.mouse.move(1, 1)
        # No active cell's marks: the notebook only has focus because it was just run.
        page.add_style_tag(
            content=".jp-Collapser, .jp-Collapser-child { background: transparent !important; }"
            " .jp-cell-toolbar { display: none !important; }"
        )
        cell = page.locator(".jp-Cell").first
        b = cell.bounding_box()
        if b["width"] > WIDTH:
            page.set_viewport_size(
                {"width": 1210 - round(b["width"] - WIDTH + 7), "height": 900}
            )
            page.wait_for_timeout(1500)
            b = cell.bounding_box()
        clip = {
            "x": b["x"],
            "y": b["y"],
            "width": min(b["width"], WIDTH),
            "height": min(b["height"], HEIGHT),
        }
        path = _lab.FIGS / "data-explorer.png"
        page.screenshot(path=str(path), clip=clip)
        _lab.report(path, clip["width"], clip["height"])


if __name__ == "__main__":
    _lab.run(make)
