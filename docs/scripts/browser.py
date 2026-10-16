"""The pictures of "Using the data browser" in docs/data-explorer.md:
browser-sort.png, browser-filter.png, browser-chips.png, browser-columns.png
and browser-mode.png.

A DataExplorer of the demo orders, kept live (``max_live_rows=10``) so that
Live and In memory can be switched.

uv run --group docs docs/scripts/browser.py
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _lab
from _lab import FIGS, box, shot

if TYPE_CHECKING:
    from _lab import Lab

SOURCE = """\
import polars as pl
from jupyter_storage_explorer import DataExplorer

orders = pl.scan_parquet("sales-lake/curated/orders.parquet")
DataExplorer(
    orders.select(
        "order_id",
        pl.col("order_ts").dt.date().alias("order_date"),
        "customer_id",
        "product",
        "quantity",
        "unit_price",
    ),
    title="orders.parquet",
    max_live_rows=10,
    max_memory_rows=1000,
    height="260px",
)"""


def make(lab: Lab) -> None:
    with lab.page(1250, 1000) as page:
        lab.open_notebook(page, SOURCE)
        page.wait_for_selector(
            ".jse-data-explorer table.jse-data tbody tr", timeout=60000
        )
        page.wait_for_timeout(1500)
        widget = page.locator(".jse-data-explorer").first
        widget.scroll_into_view_if_needed()
        wx0, wy0, wx1, _ = box(widget)
        bar = page.locator(".jse-query-bar").first
        dialog = page.locator(".jse-confirm:visible").first

        def header(column: str):
            return page.locator(
                "th", has=page.locator(".jse-query-name", has_text=column)
            ).first

        def idle() -> None:
            page.mouse.move(1, 1)
            page.wait_for_timeout(1200)

        def rows_bottom(n: int) -> float:
            return box(page.locator("table.jse-data tbody tr").nth(n - 1))[3]

        # Page and sort: sorted by unit_price, descending.
        header("unit_price").locator(".jse-query-name").click()
        page.wait_for_timeout(1200)
        header("unit_price").locator(".jse-query-name").click()
        idle()
        shot(page, FIGS / "browser-sort.png", (wx0, wy0, wx1, rows_bottom(4)))

        # Filter: the dialog of a column's funnel, a range on quantity.
        header("quantity").locator(".jse-query-filter").click()
        page.wait_for_timeout(800)
        dialog.locator("select").first.select_option(label="Range")
        page.wait_for_timeout(300)
        inputs = dialog.locator(".jse-query-range input")
        inputs.nth(0).fill("3")
        inputs.nth(1).fill("")
        page.wait_for_timeout(300)
        shot(page, FIGS / "browser-filter.png", box(dialog), pad=0)
        dialog.locator(".jse-btn", has_text="Apply").click()
        page.wait_for_timeout(1500)

        # Active filters: a second one, on product, then the toolbar's chips.
        header("product").locator(".jse-query-filter").click()
        page.wait_for_timeout(800)
        dialog.locator("select").first.select_option(label="Contains")
        page.wait_for_timeout(300)
        dialog.locator("input[type=text], input:not([type])").first.fill("Colombia")
        dialog.locator(".jse-btn", has_text="Apply").click()
        idle()
        shot(page, FIGS / "browser-chips.png", (wx0, wy0, wx1, rows_bottom(3)))

        # Select columns.
        bar.locator(".jse-btn", has_text="Select columns").click()
        page.wait_for_timeout(800)
        dialog.locator("label", has_text="customer_id").locator("input").uncheck()
        page.wait_for_timeout(300)
        shot(page, FIGS / "browser-columns.png", box(dialog), pad=0)
        dialog.locator(".jse-btn", has_text="Cancel").click()
        page.wait_for_timeout(500)

        # Live / In memory: In memory, with its note on rows left out.
        bar.locator(".jse-btn", has_text="In memory").click()
        idle()
        mode = page.locator(".jse-query-mode").first
        note = page.locator(".jse-query-mode-note").first
        x0 = box(note)[0] if note.count() else box(mode)[0]
        _, by0, bx1, by1 = box(bar)
        shot(page, FIGS / "browser-mode.png", (x0, by0, bx1, by1))


if __name__ == "__main__":
    _lab.run(make)
