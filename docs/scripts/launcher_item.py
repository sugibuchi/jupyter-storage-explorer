"""launcher/figs/launcher.png, in the launcher's README: the Storage Explorer
item in JupyterLab's launcher, beside the first others of its section. At 1x.

uv run --group docs docs/scripts/launcher_item.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import box, shot

if TYPE_CHECKING:
    from _lab import Lab


def make(lab: Lab) -> None:
    with lab.page(1250, 1000, scale=1) as page:
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        page.wait_for_timeout(1500)
        section = page.locator(".jp-Launcher-section").filter(has_text="Other").first
        section.scroll_into_view_if_needed()
        _lab.calm(page)
        x0, y0, _, _ = box(section)
        cards = section.locator(".jp-LauncherCard")
        _, _, x1, y1 = box(cards.nth(2))
        shot(page, _lab.LAUNCHER_FIGS / "launcher.png", (x0, y0, x1 + 8, y1 + 8), pad=0)


if __name__ == "__main__":
    _lab.run(make)
