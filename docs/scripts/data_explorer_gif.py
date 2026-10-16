"""docs/figs/data-explorer.gif, in the README: a DataExplorer of the demo
orders in a notebook, paged, its columns chosen, filtered and sorted. Made
with ``_film.Film``.

uv run --group docs docs/scripts/data_explorer_gif.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _film import POINTER, Film

if TYPE_CHECKING:
    from _lab import Lab
    from playwright.sync_api import Locator

WIDTH, HEIGHT = 1200, 720

SOURCE = """\
import polars as pl
from jupyter_storage_explorer import DataExplorer

orders = pl.scan_parquet("sales-lake/curated/orders.parquet")
DataExplorer(orders, title="orders.parquet", height="420px")"""


def make(lab: Lab) -> None:
    with lab.page(WIDTH, HEIGHT, scale=1) as page:
        page.add_init_script(POINTER)
        lab.open_notebook(page, SOURCE)
        # More room for the notebook: no file browser.
        page.keyboard.press("Control+b")
        page.wait_for_selector(".jse-data-explorer .jse-data tbody tr", timeout=60000)
        page.wait_for_timeout(2500)
        # No active cell's marks: the notebook only has focus because it was just run.
        page.add_style_tag(
            content=".jp-Collapser, .jp-Collapser-child { background: transparent !important; }"
            " .jp-cell-toolbar { display: none !important; }"
        )
        bar = page.locator(".jse-query-bar").first
        dialog = page.locator(".jse-confirm:visible").first

        def header(column: str) -> Locator:
            return page.locator(
                "th", has=page.locator(".jse-query-name", has_text=column)
            ).first

        def settle(ms: int) -> None:
            page.wait_for_timeout(1000)
            film.snap(ms)

        film = Film(page)
        film.snap(1500)

        # Pages of 100 rows.
        next_page = bar.locator("button[title='Next page']")
        film.click(next_page)
        settle(700)
        film.click(next_page)
        settle(1000)

        # Fewer columns.
        film.click(bar.locator(".jse-btn", has_text="Select columns"))
        settle(600)
        for column in ("customer_id", "sku", "status"):
            film.click(dialog.locator("label", has_text=column).locator("input"))
            film.snap(300)
        film.click(dialog.locator(".jse-btn", has_text="Apply"))
        settle(1200)

        # Wholesale orders only.
        film.click(header("channel").locator(".jse-query-filter"))
        settle(500)
        dialog.locator("select").first.select_option(label="Contains")
        film.snap(400)
        film.click(dialog.locator("input[type=text], input:not([type])").first)
        film.type("wholesale", ms=80)
        film.snap(300)
        film.click(dialog.locator(".jse-btn", has_text="Apply"))
        settle(1200)

        # The largest first.
        film.click(header("amount").locator(".jse-query-name"))
        settle(500)
        film.click(header("amount").locator(".jse-query-name"))
        settle(1500)
        film.click(next_page)
        settle(3000)

        path = _lab.FIGS / "data-explorer.gif"
        film.save(str(path))
        print(f"{path.relative_to(_lab.REPO).as_posix()}: {WIDTH} x {HEIGHT}, {len(film.frames)} frames, "
              f"{path.stat().st_size / 1e6:.1f} MB")  # fmt: skip


if __name__ == "__main__":
    _lab.run(make)
