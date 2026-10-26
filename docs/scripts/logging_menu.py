"""In docs/storage-explorer.md's Logs: docs/figs/logging-menu.png, a Storage
Explorer tab's settings menu (⚙), open, with "Logging" and its levels,
WARNING chosen, and "Open log file".

uv run --group docs docs/scripts/logging_menu.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.launcher_settings(_lab.LAUNCHER_PY), lab.page(900, 740) as page:
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        # A narrower toolbar: no file browser.
        page.keyboard.press("Control+b")
        page.locator(".jp-LauncherCard", has_text="Storage Explorer").first.click()
        tab = page.locator(".jse-launcher-panel .jse-browser").last
        tab.locator(".jse-tree .jse-node").first.wait_for(timeout=90000)
        page.wait_for_timeout(1500)
        _lab.calm(page)

        settings = tab.locator(".jse-settings-btn")
        menu = page.locator(".jse-menu:not(.jse-submenu)").first
        sub = page.locator(".jse-submenu:visible").first

        def open_logging() -> None:
            settings.click()
            menu.wait_for(state="visible")
            menu.locator(".jse-menu-item", has_text="Logging").hover()
            sub.locator(".jse-menu-item", has_text="Open log file").wait_for()

        # The tab logs nothing at first: choose WARNING, then open it again.
        open_logging()
        sub.locator(".jse-menu-item", has_text="WARNING").click()
        page.wait_for_timeout(800)
        open_logging()
        sub.locator(".jse-menu-item", has_text="WARNING").hover()
        page.wait_for_timeout(500)

        # From the menus' left, the toolbar down to the menus' bottom.
        y0 = box(tab.locator(".jse-toolbar"))[1]
        mx0, _, mx1, my1 = box(menu)
        sx0, _, sx1, sy1 = box(sub)
        left = min(mx0, sx0)
        right = max(box(settings)[2], mx1, sx1)
        area = (left - 6, y0, right + 6, max(my1, sy1) + 6)
        shot(page, FIGS / "logging-menu.png", area, pad=0)
        page.keyboard.press("Escape")


if __name__ == "__main__":
    _lab.run(make)
