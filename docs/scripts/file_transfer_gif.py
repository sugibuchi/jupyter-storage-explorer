"""docs/figs/file-transfer.gif, in "File transfer between file systems": two
Storage Explorer tabs from JupyterLab's launcher, one above the other, each
with a kernel of its own, and a file dragged from a team's shared folder on
the server's disk (top) into the scratch storage of the other tab (bottom).
Made with ``_film.Film``.

The demo lake and the scratch storage are in each kernel's memory, which the
other kernel cannot read: the drag starts from the shared folder, which both
kernels reach (see demo_data.shared_drive).

uv run --group docs docs/scripts/file_transfer_gif.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
import demo_data
from _film import POINTER, Film

if TYPE_CHECKING:
    from _lab import Lab
    from playwright.sync_api import Locator, Page

WIDTH, HEIGHT = 1200, 800

LAUNCHER_PY = """\
import demo_data


def filesystems():
    return {**demo_data.shared_drive(), **demo_data.filesystems()}


def supports():
    return demo_data.supports()
"""


def open_tab(page: Page, film: Film) -> Locator:
    """Open an explorer tab from the launcher shown; its panel."""
    panels = page.locator(".jse-launcher-panel")
    count = panels.count()
    film.click(page.locator(".jp-LauncherCard", has_text="Storage Explorer").last)
    page.wait_for_function(
        f"document.querySelectorAll('.jse-launcher-panel .jse-tree .jse-node').length > 0"
        f" && document.querySelectorAll('.jse-launcher-panel').length > {count}",
        timeout=90000,
    )
    panel = panels.nth(count)
    panel.locator(".jse-tree .jse-node").first.wait_for(timeout=90000)
    page.wait_for_timeout(1000)
    return panel


def make(lab: Lab) -> None:
    demo_data.write_share(lab.root)
    with (
        lab.launcher_settings(LAUNCHER_PY),
        lab.page(WIDTH, HEIGHT, scale=1) as page,
    ):
        page.add_init_script(POINTER)
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        # More room for the tabs: no file browser.
        page.keyboard.press("Control+b")
        page.wait_for_timeout(1500)
        film = Film(page)

        # Two explorer tabs, the second below the first.
        top = open_tab(page, film)
        page.keyboard.press("Control+Shift+L")
        page.wait_for_selector(".jp-LauncherCard:visible", timeout=30000)
        bottom = open_tab(page, film)
        page.locator(".lm-TabBar-tab", has_text="Storage Explorer").last.click(
            button="right"
        )
        page.locator(".lm-Menu-itemLabel", has_text="Split Tab").first.hover()
        page.get_by_role("menuitem", name="Down", exact=True).click()
        page.mouse.move(WIDTH / 2, HEIGHT / 2)
        page.wait_for_timeout(1500)
        film.snap(1200)

        def node(tab: Locator, name: str) -> Locator:
            return (
                tab.locator(".jse-tree .jse-node")
                .filter(has=page.get_by_text(name, exact=True))
                .first
            )

        def row(tab: Locator, name: str) -> Locator:
            return (
                tab.locator("tbody tr")
                .filter(has=page.get_by_text(name, exact=True))
                .first
            )

        # The bottom tab shows the scratch storage, the top one the shared folder.
        film.click(bottom.locator(".jse-fs-select"))
        bottom.locator(".jse-fs-select").select_option("Scratch")
        page.wait_for_timeout(1000)
        film.snap(700)
        film.click(node(bottom, "exports").get_by_text("exports", exact=True))
        page.wait_for_timeout(1000)
        film.snap(700)
        film.click(node(top, "pricing").get_by_text("pricing", exact=True))
        page.wait_for_timeout(1000)
        film.snap(1000)

        # A file dragged from the top tab onto the bottom one, and pasted there.
        film.move(row(top, "price_list_2027.csv"))
        film.snap(300)
        page.mouse.down()
        film.snap(150)
        film.move(bottom.locator(".jse-list"), steps=20, dy=0.4)
        film.snap(500)
        page.mouse.up()
        dialog = bottom.locator(".jse-confirm:visible")
        dialog.wait_for(timeout=30000)
        page.wait_for_timeout(500)
        film.snap(1200)
        film.click(dialog.get_by_role("button", name="Paste", exact=True))
        row(bottom, "price_list_2027.csv").wait_for(timeout=30000)
        page.wait_for_timeout(800)
        page.mouse.move(WIDTH - 5, HEIGHT - 5)
        film.snap(3500)

        path = _lab.FIGS / "file-transfer.gif"
        film.save(str(path))
        print(f"{path.relative_to(_lab.REPO).as_posix()}: {WIDTH} x {HEIGHT}, {len(film.frames)} frames, "
              f"{path.stat().st_size / 1e6:.1f} MB")  # fmt: skip


if __name__ == "__main__":
    _lab.run(make)
