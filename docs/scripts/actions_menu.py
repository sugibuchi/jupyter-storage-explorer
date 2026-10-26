"""In the action development guide: docs/figs/actions-notebook.png, the
notebook developing the guide's first action, its explorer showing the action
in a JSON file's "Python code" submenu; and docs/figs/actions-menu.png, an
explorer's settings menu (⚙), open, with "Actions" and its "Edit" and "Reload".

uv run --group docs docs/scripts/actions_menu.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, shot

if TYPE_CHECKING:
    from _lab import Lab

# The guide's first action: its notebook's second cell.
FIRST_ACTION = '''\
from jupyter_storage_explorer.actions import code
from jupyter_storage_explorer.formats import Json

PRETTY_PRINT = """
import json

import fsspec

with fsspec.open({url!r}) as f:
    print(json.dumps(json.load(f), indent=4))
""".strip()


@code(format=Json)
def pretty_print_json(url):
    return PRETTY_PRINT.format(url=url)'''

# The notebook's other cells. The guide's explorer opens "s3://my-bucket/data",
# the picture's the demo lake, which DEMO_LAKE fills unseen.
INSTALL = """\
# If the jupyter-storage-explorer package is not installed
%pip install jupyter-storage-explorer"""
EXPLORER = """\
from jupyter_storage_explorer import StorageExplorer

StorageExplorer("memory:///sales-lake", actions=[pretty_print_json])"""
DEMO_LAKE = "import demo_data\n\ndemo_data.filesystems()\n"


def make(lab: Lab) -> None:
    notebook(lab)
    settings_menu(lab)


def notebook(lab: Lab) -> None:
    """The three cells, run from the action's: the package is installed, and
    the docs' environment has no pip."""
    with lab.kernel_startup(DEMO_LAKE), lab.page(1000, 1300) as page:
        lab.open_notebook(page, INSTALL, FIRST_ACTION, EXPLORER, first=1)
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        # Without the active cell's bar and toolbar, which are not the point.
        page.add_style_tag(
            content=".jp-Collapser, jp-toolbar.jp-cell-toolbar { visibility: hidden; }"
        )
        _lab.calm(page)
        _, row, menu_item = _lab.explorer_helpers(page)

        # catalog.json right-clicked, "Python code" open: the action, hovered.
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

        # The cells, from the first's top to the explorer's bottom, and the
        # menus wherever they reach out of them.
        cells = page.locator(".jp-Notebook .jp-Cell")
        x0, y0, x1, _ = box(cells.first)
        y1 = box(cells.nth(2))[3]
        sx0, _, sx1, sy1 = box(mine.locator("xpath=.."))
        menu = page.locator(".jse-menu:not(.jse-submenu)").first
        _, _, mx1, my1 = box(menu)
        area = (min(x0, sx0), y0, max(x1, sx1, mx1), max(y1, sy1, my1))
        shot(page, FIGS / "actions-notebook.png", area)
        page.keyboard.press("Escape")


def settings_menu(lab: Lab) -> None:
    with lab.page(1100, 900) as page:
        # As the launcher's explorers: with the user's actions files.
        lab.open_notebook(
            page, _lab.explorer_source(height="320px", user_actions="enabled")
        )
        page.wait_for_selector(".jse-tree .jse-node", timeout=60000)
        page.wait_for_timeout(1500)
        _lab.calm(page)

        # The settings menu, "Actions" open, its "Edit" pointed at.
        settings = page.locator(".jse-settings-btn").first
        settings.click()
        menu = page.locator(".jse-menu:not(.jse-submenu)").first
        menu.wait_for(state="visible")
        menu.locator(".jse-menu-item", has_text="Actions").hover()
        sub = page.locator(".jse-submenu:visible").first
        sub.locator(".jse-menu-item", has_text="Edit").hover()
        page.wait_for_timeout(500)
        # From the menus' left, the toolbar down to the menus' bottom.
        y0 = box(page.locator(".jse-toolbar").first)[1]
        mx0, _, mx1, my1 = box(menu)
        sx0, _, sx1, sy1 = box(sub)
        left = min(mx0, sx0)
        right = max(box(settings)[2], mx1, sx1)
        area = (left - 6, y0, right + 6, max(my1, sy1) + 6)
        shot(page, FIGS / "actions-menu.png", area, pad=0)
        page.keyboard.press("Escape")


if __name__ == "__main__":
    _lab.run(make)
