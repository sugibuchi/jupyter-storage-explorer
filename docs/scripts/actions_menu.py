"""In the action development guide: docs/figs/actions-menu.png, an explorer's
settings menu (⚙), open, with "Edit actions" and "Reload actions"; and
docs/figs/actions-first.png, the guide's first action in a JSON file's
"Python code" submenu.

uv run --group docs docs/scripts/actions_menu.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, shot

if TYPE_CHECKING:
    from _lab import Lab

# The guide's first action, as the user's actions file.
FIRST_ACTION = '''\
from jupyter_storage_explorer.formats import Json
from jupyter_storage_explorer.formats.actions import code

PRETTY_PRINT = """
import json

import fsspec

with fsspec.open({url!r}) as f:
    print(json.dumps(json.load(f), indent=4))
""".strip()


@code(format=Json)
def pretty_print_json(url):
    return PRETTY_PRINT.format(url=url)
'''


def make(lab: Lab) -> None:
    with lab.user_actions("first.py", FIRST_ACTION), lab.page(1100, 900) as page:
        lab.open_notebook(page, _lab.explorer_source(height="320px"))
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        _lab.calm(page)
        _, row, menu_item = _lab.explorer_helpers(page)

        # The settings menu, "Edit actions" pointed at.
        settings = page.locator(".jse-settings-btn").first
        settings.click()
        menu = page.locator(".jse-menu:not(.jse-submenu)").first
        menu.wait_for(state="visible")
        menu.locator(".jse-menu-item", has_text="Edit actions").hover()
        page.wait_for_timeout(500)
        # From the menu's left, the toolbar down to the menu's bottom.
        y0 = box(page.locator(".jse-toolbar").first)[1]
        mx0, _, mx1, my1 = box(menu)
        right = max(box(settings)[2], mx1)
        shot(page, FIGS / "actions-menu.png", (mx0 - 6, y0, right + 6, my1 + 6), pad=0)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # catalog.json right-clicked: "Python code", with the user's snippet.
        row("catalog.json").click()
        row("catalog.json").click(button="right", position={"x": 120, "y": 10})
        # The menu grows when the item's views arrive: hover after them.
        menu_item("Preview as").wait_for(state="visible")
        page.wait_for_timeout(800)
        menu_item("Python code").hover()
        mine = page.locator(
            ".jse-submenu .jse-menu-item:visible", has_text="Pretty print json"
        )
        mine.hover()  # kept: moving the mouse away would close the submenu
        page.wait_for_timeout(800)
        # The whole menu, and the submenu beside its "Python code".
        sx0, sy0, _, sy1 = box(mine.locator("xpath=.."))
        _, my0, mx1, my1 = box(menu_item("Python code").locator("xpath=.."))
        area = (sx0 - 6, min(sy0, my0) - 6, mx1 + 6, max(sy1, my1) + 6)
        shot(page, FIGS / "actions-first.png", area, pad=0)
        page.keyboard.press("Escape")


if __name__ == "__main__":
    _lab.run(make)
