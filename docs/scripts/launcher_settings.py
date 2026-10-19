"""In the launcher's README: launcher/figs/settings-button.png, the right of a
Storage Explorer tab's toolbar, the "Unsafe mode" switch and the settings
button (⚙) after it; launcher/figs/settings-editor.png, the user's
launcher.py, just created from the template, in JupyterLab's editor.

uv run --group docs docs/scripts/launcher_settings.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    path = lab.folder / "config" / "storage-explorer" / "launcher.py"
    with lab.launcher_settings(_lab.LAUNCHER_PY), lab.page(900, 640) as page:
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

        # A user without settings yet: the file is created from the template.
        path.unlink()  # read when the tab started
        tab.locator(".jse-settings-btn").click()
        tab.locator(".jse-dialog:visible").get_by_role("button", name="Create").click()
        page.locator(".jp-FileEditor .cm-content").first.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        _lab.calm(page)
        # The tabs and editor, down to the end of format_options' example.
        x0, y0, x1, _ = box(page.locator("#jp-main-dock-panel"))
        last = box(page.locator(".jp-FileEditor .cm-line").nth(28))[3]
        area = (x0, y0, x1, last + 1)
        shot(page, _lab.LAUNCHER_FIGS / "settings-editor.png", area, pad=0)


if __name__ == "__main__":
    _lab.run(make)
