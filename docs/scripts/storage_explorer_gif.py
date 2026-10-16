"""docs/figs/storage-explorer.gif, in the README: Storage Explorer opened from
JupyterLab's launcher, a Delta Lake table queried in the data browser, a
folder's list filtered as the user types, and a Markdown file edited in
JupyterLab's own editor, saved back to the storage and previewed in the
explorer. Made with ``_film.Film``.

uv run --group docs docs/scripts/storage_explorer_gif.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _film import POINTER, Film

if TYPE_CHECKING:
    from _lab import Lab
    from playwright.sync_api import Locator

WIDTH, HEIGHT = 1200, 720


def make(lab: Lab) -> None:
    with lab.page(WIDTH, HEIGHT, scale=1) as page:
        page.add_init_script(POINTER)
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        # More room for the tab: no file browser.
        page.keyboard.press("Control+b")
        page.wait_for_timeout(1500)
        film = Film(page)
        film.snap(1200)

        # The launcher's item opens an explorer tab.
        film.click(page.locator(".jp-LauncherCard", has_text="Storage Explorer").first)
        page.wait_for_selector(".jse-tree .jse-node", timeout=90000)
        page.wait_for_timeout(1500)
        film.snap(1200)
        tree, row, _ = _lab.explorer_helpers(page)

        def label(name: str) -> Locator:
            return tree(name).get_by_text(name, exact=True)

        # A Delta Lake table, queried.
        film.click(label("curated"), double=True)
        page.wait_for_timeout(1000)
        film.snap(700)
        film.click(row("customers"))
        page.wait_for_timeout(800)
        film.snap(500)
        film.click(
            page.locator(".jse-status-bar .jse-link", has_text="Query data").first
        )
        page.wait_for_selector(".jse-data tbody tr", timeout=30000)
        page.wait_for_timeout(1000)
        film.snap(1500)
        film.click(page.locator(".jse-query-name", has_text="signup_date").first)
        page.wait_for_timeout(1000)
        film.snap(600)
        film.click(page.locator(".jse-query-name", has_text="signup_date").first)
        page.wait_for_timeout(1000)
        film.snap(1800)

        # The list filtered as the user types.
        film.click(label("pipelines"))
        page.wait_for_timeout(1000)
        film.snap(700)
        film.click(page.get_by_placeholder("Filter by name"))
        film.type("md", ms=250)
        film.snap(800)

        # The Markdown file edited in JupyterLab's own editor, and saved back.
        film.click(row("README.md"), double=True, dx=0.2)
        editor = page.locator(".jp-FileEditor .cm-content").first
        editor.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        film.snap(1000)
        film.click(page.locator(".jp-FileEditor .cm-line").last)
        page.keyboard.press("Control+End")
        film.type(
            "\n## Changes\n\n- 2026-10-16: reports/ refreshed on the 1st at 06:00 UTC",
            chunk=3,
            ms=60,
        )
        film.snap(600)
        page.keyboard.press("Control+s")
        page.wait_for_timeout(1500)
        film.snap(1200)

        # Back in the explorer, whose preview shows the file as saved.
        film.click(page.locator(".lm-TabBar-tab", has_text="Storage Explorer").first)
        page.wait_for_timeout(1000)
        film.snap(1000)
        changes = page.get_by_text("refreshed on the 1st").first
        film.move(page.get_by_text("Owner: data platform team").first)
        for _ in range(8):
            page.mouse.wheel(0, 40)
            page.wait_for_timeout(50)
            film.snap(60)
        changes.wait_for(timeout=10000)
        film.snap(4000)

        path = _lab.FIGS / "storage-explorer.gif"
        film.save(str(path))
        print(f"{path.relative_to(_lab.REPO).as_posix()}: {WIDTH} x {HEIGHT}, {len(film.frames)} frames, "
              f"{path.stat().st_size / 1e6:.1f} MB")  # fmt: skip


if __name__ == "__main__":
    _lab.run(make)
