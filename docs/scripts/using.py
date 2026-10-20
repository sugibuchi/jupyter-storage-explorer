"""The pictures of "Using the explorer" in docs/storage-explorer.md:
using-browse.png, using-filter.png, using-preview.png, using-right-click.png,
using-properties.png and using-bookmarks.png.

uv run --group docs docs/scripts/using.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, calm, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(1250, 1000) as page:
        lab.open_notebook(page, _lab.explorer_source(height="400px"))
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        # The widget in view, the notebook's cell input scrolled away.
        page.locator(".jse-browser").first.scroll_into_view_if_needed()
        tree, row, menu_item = _lab.explorer_helpers(page)
        menu = page.locator(".jse-menu:not(.jse-submenu)")
        list_bar = page.locator(".jse-list-pane .jse-pane-bar").first

        # Browse: a folder open, two items selected.
        tree("curated").dblclick()
        page.wait_for_timeout(1500)
        row("customers").click()
        row("orders.parquet").click(modifiers=["Control"])
        calm(page)
        wx0, wy0, wx1, _ = box(page.locator(".jse-browser").first)
        area = (wx0, wy0, wx1, box(tree("pipelines"))[3] - 6)
        shot(page, FIGS / "using-browse.png", area)

        # Filter: a regular expression on the list.
        tree("landing").dblclick()
        page.wait_for_timeout(1200)
        tree("orders").click()
        page.wait_for_timeout(1500)
        page.locator(".jse-btn", has_text=".*").first.click()
        page.get_by_placeholder("Filter by name").fill(r"_2026-0[89]\.csv$")
        page.wait_for_timeout(800)
        calm(page)
        fx0, fy0, _, _ = box(list_bar)
        area = (fx0 + 6, fy0 + 6, wx1, box(row("orders_2026-09.csv"))[3])
        shot(page, FIGS / "using-filter.png", area)
        page.get_by_placeholder("Filter by name").fill("")
        page.locator(".jse-btn", has_text=".*").first.click()

        # Preview: right-click a Markdown file, beside the Preview link.
        tree("pipelines").click()
        page.wait_for_timeout(1500)
        row("README.md").click()
        row("README.md").click(button="right", position={"x": 190, "y": 10})
        page.wait_for_timeout(1500)
        lx0 = box(row("README.md"))[0]
        menu_item("Preview as").hover()
        page.wait_for_timeout(800)
        sx0, sy0, sx1, sy1 = box(page.locator(".jse-menu.jse-submenu:visible").first)
        _, my0, _, my1 = box(menu)
        # From the list's bar down to the status bar, where Preview is.
        py0 = box(list_bar)[1] + 6
        py1 = box(page.locator(".jse-status-bar").first)[3]
        area = (
            min(lx0 + 6, sx0),
            min(py0, my0, sy0),
            max(wx1, sx1),
            max(my1, sy1, py1),
        )
        shot(page, FIGS / "using-preview.png", area)
        page.keyboard.press("Escape")

        # Right-click: a JSON Lines file.
        tree("landing").click()
        page.wait_for_timeout(1200)
        tree("events").click()
        page.wait_for_timeout(1500)
        row("events_2026-09-30.jsonl").click(
            button="right", position={"x": 190, "y": 10}
        )
        page.wait_for_timeout(1500)
        _, my0, mx1, my1 = box(menu)
        area = (lx0 + 6, min(box(page.locator("thead").first)[1] + 6, my0), mx1, my1)
        shot(page, FIGS / "using-right-click.png", area)
        page.keyboard.press("Escape")

        # Properties of a folder.
        tree("curated").click(button="right")
        page.wait_for_timeout(1000)
        menu_item("Properties").click()
        page.wait_for_selector(".jse-props", timeout=30000)
        page.wait_for_timeout(3000)
        calm(page)
        hx0, hy0, hx1, _ = box(page.locator(".jse-dialog-head:visible").first)
        area = (hx0, hy0, hx1, box(page.locator(".jse-dialog-body:visible").first)[3])
        shot(page, FIGS / "using-properties.png", area, pad=0)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        for button in page.locator(".jse-dialog:visible .jse-btn").all():
            if button.inner_text().strip() in ("Close", "OK"):
                button.click()

        # Bookmarks: three folders bookmarked, then the star's menu.
        for folder in ("curated", "landing", "customers"):
            if folder == "customers":
                tree("curated").click()
                page.wait_for_timeout(1200)
            tree(folder).click(button="right")
            page.wait_for_timeout(800)
            menu_item("Add bookmark").click()
            page.wait_for_timeout(800)
        tree("landing").click()
        page.wait_for_timeout(1200)
        page.locator(".jse-bookmark-btn").first.click()
        page.wait_for_timeout(1200)
        _, _, mx1, my1 = box(menu)
        shot(page, FIGS / "using-bookmarks.png", (wx0, wy0, mx1, my1))


if __name__ == "__main__":
    _lab.run(make)
