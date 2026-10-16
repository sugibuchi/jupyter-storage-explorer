"""docs/figs/storage-explorer.png, the README's first picture: a JSON Lines
file of web events open in the data browser, below the folders browsed.

uv run --group docs docs/scripts/hero.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(1386, 1300) as page:
        lab.open_notebook(page, _lab.explorer_source())
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        tree, row, _ = _lab.explorer_helpers(page)
        for folder in ("curated", "customers", "landing", "events"):
            tree(folder).click()
            page.wait_for_timeout(1200)
        row("events_2026-09-30.jsonl").click()
        page.wait_for_timeout(1000)
        page.locator(".jse-status-bar .jse-link", has_text="Query data").first.click()
        page.wait_for_selector(".jse-data tbody tr", timeout=30000)
        page.wait_for_timeout(1500)
        _lab.calm(page)
        widget = page.locator(".jse-browser").first
        widget.scroll_into_view_if_needed()
        path = _lab.FIGS / "storage-explorer.png"
        widget.screenshot(path=str(path))
        b = widget.bounding_box()
        _lab.report(path, b["width"], b["height"])


if __name__ == "__main__":
    _lab.run(make)
