"""launcher/figs/settings-button.png, in the launcher's README: the toolbar of
a Storage Explorer tab, with the settings button (⚙) after "Unsafe mode".

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
        shot(
            page,
            _lab.LAUNCHER_FIGS / "settings-button.png",
            box(tab.locator(".jse-toolbar")),
            pad=0,
        )


if __name__ == "__main__":
    _lab.run(make)
