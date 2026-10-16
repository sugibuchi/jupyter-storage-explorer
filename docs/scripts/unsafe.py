"""docs/figs/unsafe-mode.png: the "Unsafe mode" switch, on, at the right of
the toolbar, above a folder's list with a folder selected.

uv run --group docs docs/scripts/unsafe.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(1100, 900) as page:
        lab.open_notebook(page, _lab.explorer_source(height="180px"))
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        tree, row, _ = _lab.explorer_helpers(page)
        tree("curated").click()
        page.wait_for_timeout(1500)
        page.locator(".jse-unsafe").click()
        page.wait_for_timeout(500)
        _lab.calm(page)
        row("orders_by_month").click()
        page.mouse.move(1, 1)
        page.wait_for_timeout(800)
        # From the list's left, the toolbar down to the last row.
        x0 = box(page.locator("thead").first)[0]
        y0 = box(page.locator(".jse-toolbar").first)[1]
        x1 = box(page.locator(".jse-status-bar").first)[2]
        y1 = box(row("orders.parquet"))[3]
        shot(page, FIGS / "unsafe-mode.png", (x0, y0, x1, y1 + 6), pad=0)


if __name__ == "__main__":
    _lab.run(make)
