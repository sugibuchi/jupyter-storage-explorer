"""launcher/figs/side-panel.png, in the launcher's README: the side panel in
JupyterLab's left side bar, its file selected, beside the tab its View button
opened in the data browser.

uv run --group docs docs/scripts/launcher_side_panel.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(900, 560) as page:
        page.goto(lab.url())
        page.locator(".jp-SideBar .lm-TabBar-tab[title='Storage Explorer']").click()
        side = page.locator(".jse-side-panel .jse-browser")
        rows = side.locator(".jse-list tbody tr")
        rows.first.wait_for(timeout=90_000)
        rows.filter(has=page.get_by_text("curated", exact=True)).dblclick()
        row = rows.filter(has=page.get_by_text("orders.parquet", exact=True))
        row.click()
        view = side.locator(".jse-status-bar .jse-preview-btn")
        view.filter(has_text="View (Parquet)").wait_for()
        view.click()
        page.locator(".jse-query-tab .jse-query-status").wait_for(timeout=60_000)
        _lab.calm(page, 1500)
        _, _, x1, y1 = box(page.locator("#jp-main-dock-panel"))
        shot(page, _lab.LAUNCHER_FIGS / "side-panel.png", (0, 0, x1, y1), pad=0)


if __name__ == "__main__":
    _lab.run(make)
