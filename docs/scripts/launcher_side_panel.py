"""In the launcher's README: launcher/figs/side-panel.png, the side panel in
JupyterLab's left side bar, its file selected, beside the tab its View button
opened in the data browser; launcher/figs/side-panel-restart.png, the side
panel's kernel in JupyterLab's Running panel, its Shut Down button shown.

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

        # The Running panel, the side panel's kernel hovered: its Shut Down
        # button (a cross) shows. From the side bar to the kernel's console.
        page.locator(".jp-SideBar .lm-TabBar-tab[title*='Running']").click()
        kernel = page.locator(
            ".jp-RunningSessions-item.jp-mod-kernel", has_text="side panel"
        )
        kernel.wait_for()
        # Wider, so that the kernel's name shows whole.
        handle = page.locator("#jp-main-split-panel > .lm-SplitPanel-handle").first
        hx, hy, _, hy1 = box(handle)
        page.mouse.move(hx + 1, (hy + hy1) / 2)
        page.mouse.down()
        page.mouse.move(hx + 140, (hy + hy1) / 2, steps=5)
        page.mouse.up()
        _lab.calm(page)
        kernel.locator(":scope > .jp-RunningSessions-itemLabel").hover()
        kernel.locator(":scope > .jp-RunningSessions-itemShutdown").wait_for()
        page.wait_for_timeout(500)
        _, y0, _, _ = box(page.locator(".jp-RunningSessions"))
        _, _, x1, _ = box(page.locator("#jp-left-stack"))
        _, _, _, y1 = box(kernel)
        shot(
            page,
            _lab.LAUNCHER_FIGS / "side-panel-restart.png",
            (0, y0, x1, y1 + 8),
            pad=0,
        )


if __name__ == "__main__":
    _lab.run(make)
