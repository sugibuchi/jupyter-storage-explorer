"""launcher/figs/settings-button.png, in the launcher's README: the right of a
Storage Explorer tab's toolbar, the "Unsafe mode" switch and the settings
button (⚙) after it.

uv run --group docs docs/scripts/launcher_settings.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(900, 600) as page:
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        # A narrower toolbar: no file browser.
        page.keyboard.press("Control+b")
        page.locator(".jp-LauncherCard", has_text="Storage Explorer").first.click()
        tab = page.locator(".jse-launcher-panel .jse-browser").last
        tab.locator(".jse-tree .jse-node").first.wait_for(timeout=90000)
        page.wait_for_timeout(1500)
        _lab.calm(page)
        # From the Unsafe mode switch to the settings button.
        _, y0, _, y1 = box(tab.locator(".jse-toolbar"))
        left = box(tab.locator(".jse-unsafe"))[0]
        right = box(tab.locator(".jse-settings-btn"))[2]
        # The toolbar's height, without its bottom border.
        area = (left - 6, y0, right + 6, y1 - 1)
        shot(page, _lab.LAUNCHER_FIGS / "settings-button.png", area, pad=0)


if __name__ == "__main__":
    _lab.run(make)
