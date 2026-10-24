"""A smoke test of the widgets in a real JupyterLab: the main things a user
does, clicked through in the installed Microsoft Edge with Playwright.

The JavaScript has no unit tests, so this is what tells a frontend change
(or a refactoring) from a broken one. Run it by hand before merging such a
change; it is not run by pytest or CI:

    uv run --group docs tests/browser/smoke.py              # every check
    uv run --group docs tests/browser/smoke.py paste rename # some of them

It uses the docs' scripts' server and demo data (``docs/scripts/_lab.py``,
``demo_data.py``): a JupyterLab of its own in a temporary folder, with the
launcher's extension, and explorers of a made-up data lake in fsspec's memory
filesystem, whose "Scratch" storage the checks change. Each check prints
"ok" or why it failed; a failure leaves a screenshot next to this script
(``smoke-<check>.png``, git-ignored) and the next check starts on a new
notebook, so one failure does not fail the rest.
"""

# The widgets' own texts have en dashes, in ranges of rows.
# ruff: noqa: RUF001

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import traceback
import urllib.request
from typing import TYPE_CHECKING

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "docs" / "scripts"))

import _lab  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable

    from _lab import Lab
    from playwright.sync_api import Locator, Page

# The demo storages, with two more folders of Scratch for paging: "some" is
# paged by the browser, "many" (over max_browser_items) by the kernel.
EXPLORER = """\
import fsspec
import demo_data
from jupyter_storage_explorer import StorageExplorer

storages = demo_data.filesystems()
memory = fsspec.filesystem("memory")
for i in range(150):
    memory.pipe_file(f"/scratch/some/file_{i:03}.txt", b"x")
for i in range(250):
    memory.pipe_file(f"/scratch/many/file_{i:03}.txt", b"x")
StorageExplorer(filesystems=storages, supports=demo_data.supports(), max_browser_items=200)"""

# A switch or button that is on.
ON = re.compile(r"\bjse-on\b")

CHECKS: dict[str, Callable[[Explorer], None]] = {}


def check(fn: Callable[[Explorer], None]) -> Callable[[Explorer], None]:
    CHECKS[fn.__name__] = fn
    return fn


class Explorer:
    """A notebook showing ``EXPLORER`` (or the explorer of ``source``), and
    ways to drive it."""

    def __init__(self, lab: Lab, page: Page, source: str = EXPLORER) -> None:
        self.lab = lab
        self.page = page
        lab.open_notebook(page, source)
        self.el = page.locator(".jse-browser").first
        expect(self.el.locator(".jse-tree .jse-node").first).to_be_visible(
            timeout=90_000
        )
        self.notebook_tab = page.locator(
            ".lm-TabBar-tab.jp-mod-current"
        ).first.inner_text()

    # --- Locators ---

    def node(self, name: str) -> Locator:
        """A folder of the tree."""
        return (
            self.el.locator(".jse-tree .jse-node")
            .filter(has=self.page.get_by_text(name, exact=True))
            .first
        )

    def row(self, name: str) -> Locator:
        """An item of the list."""
        return (
            self.el.locator(".jse-list tbody tr")
            .filter(has=self.page.get_by_text(name, exact=True))
            .first
        )

    @property
    def names(self) -> Locator:
        """The names in the list, in order."""
        return self.el.locator(".jse-list tbody td.jse-col-name")

    def menu_item(self, text: str) -> Locator:
        return self.el.locator(
            ".jse-menu:not(.jse-submenu) > .jse-menu-item:visible", has_text=text
        ).first

    def button(self, label: str) -> Locator:
        """A button of the explorer's confirmation dialog."""
        return self.el.locator(".jse-confirm:visible").get_by_role(
            "button", name=label, exact=True
        )

    @property
    def status(self) -> Locator:
        return self.el.locator(".jse-status")

    @property
    def preview(self) -> Locator:
        return self.el.locator(".jse-preview-panel")

    # --- Actions ---

    def storage(self, name: str) -> None:
        self.el.locator(".jse-fs-select").select_option(name)
        expect(self.el.locator(".jse-tree .jse-node").first).to_contain_text(
            "sales-lake" if name == "Sales lake" else "scratch"
        )

    def top(self, storage: str) -> None:
        """Show the top folder of ``storage``."""
        self.storage(storage)
        self.el.locator(".jse-crumb").first.click()
        expect(self.el.locator(".jse-crumb")).to_have_count(1)

    def go(self, *folders: str, storage: str = "Sales lake") -> None:
        """Show a folder of ``storage``: the first from the tree, then down the list."""
        self.storage(storage)
        self.node(folders[0]).click()
        expect(self.el.locator(".jse-crumb").last).to_have_text(folders[0])
        for name in folders[1:]:
            self.row(name).dblclick()
            expect(self.el.locator(".jse-crumb").last).to_have_text(name)

    def menu(self, target: Locator, item: str) -> None:
        """Choose ``item`` in ``target``'s right-click menu."""
        target.click(button="right")
        self.menu_item(item).click()

    def list_menu(self, item: str) -> None:
        """Choose ``item`` in the menu of the list's empty space."""
        box = self.el.locator(".jse-list").bounding_box()
        assert box is not None
        self.el.locator(".jse-list").click(
            button="right", position={"x": 40, "y": box["height"] - 12}
        )
        self.menu_item(item).click()

    def back_to_notebook(self) -> None:
        self.page.locator(".lm-TabBar-tab", has_text=self.notebook_tab).first.click()
        expect(self.el).to_be_visible()


# --- Browsing ---


@check
def browse(x: Explorer) -> None:
    x.go("curated")
    expect(x.names).to_have_text(["customers", "orders_by_month", "orders.parquet"])
    # Icons: the format's file_icon, else the extension's (Text sets none).
    icon = ".jse-col-name svg"
    expect(x.row("orders.parquet").locator(icon)).to_have_attribute(
        "data-icon", "spreadsheet"
    )
    expect(x.row("customers").locator(icon)).to_have_attribute("data-icon", "folder")
    x.go("pipelines")
    expect(x.row("daily_orders.yaml").locator(icon)).to_have_attribute(
        "data-icon", "yaml"
    )
    expect(x.row("monthly_revenue.sql").locator(icon)).to_have_attribute(
        "data-icon", "file"
    )
    x.go("curated")
    x.row("customers").dblclick()
    expect(x.el.locator(".jse-crumb")).to_have_text(
        ["/sales-lake", "curated", "customers"]
    )
    x.el.locator(".jse-toolbar button[title='Parent directory']").click()
    expect(x.el.locator(".jse-crumb").last).to_have_text("curated")
    x.el.locator(".jse-crumb", has_text="/sales-lake").click()
    expect(x.names.first).to_have_text("curated")
    # The engine, in the status bar, in every explorer.
    expect(x.el.locator(".jse-engine-btn")).to_have_text("Polars")


@check
def tree_toggle(x: Explorer) -> None:
    # The tree's button, first in the toolbar, hides the tree; the storage
    # chooser then comes first in the list's bar.
    button = x.el.locator(".jse-toolbar .jse-tree-btn")
    expect(button).to_have_class(ON)
    button.click()
    expect(x.el.locator(".jse-tree-pane")).to_be_hidden()
    expect(button).not_to_have_class(ON)
    select = x.el.locator(".jse-list-pane .jse-pane-bar .jse-fs-select")
    expect(select).to_be_visible()
    select.select_option("Scratch")
    expect(x.el.locator(".jse-crumb").first).to_have_text("/scratch")
    button.click()
    expect(x.el.locator(".jse-tree-pane .jse-fs-select")).to_have_value("Scratch")
    expect(x.el.locator(".jse-tree .jse-node").first).to_contain_text("scratch")
    x.storage("Sales lake")


@check
def list_columns(x: Explorer) -> None:
    # The settings menu's Columns shows and hides the list's columns but Name.
    x.go("curated")
    headers = x.el.locator(".jse-list th")
    expect(headers).to_have_text(["Name", "Size", "Modified"])

    def toggle(label: str) -> None:
        x.el.locator(".jse-settings-btn").click()
        x.menu_item("Columns").hover()
        x.el.locator(".jse-submenu .jse-menu-item", has_text=label).click()

    toggle("Format")
    expect(headers).to_have_text(["Name", "Size", "Modified", "Format"])
    expect(x.row("orders.parquet").locator(".jse-col-format")).to_have_text("Parquet")
    toggle("Modified")
    expect(headers).to_have_text(["Name", "Size", "Format"])
    toggle("Modified")
    toggle("Format")
    expect(headers).to_have_text(["Name", "Size", "Modified"])


@check
def about(x: Explorer) -> None:
    # The settings menu: "About" in every explorer; "Edit configuration" in
    # the launcher's tabs only (launcher_settings).
    x.el.locator(".jse-settings-btn").click()
    expect(x.menu_item("About")).to_be_visible()
    expect(x.menu_item("Edit configuration")).to_have_count(0)
    x.menu_item("About").click()
    dialog = x.el.locator(".jse-dialog:visible")
    expect(dialog.locator(".jse-about-name")).to_have_text("Jupyter Storage Explorer")
    expect(dialog.locator(".jse-about-icon")).to_be_visible()
    # Names link to their packages' home pages, in a new browser tab.
    github = "https://github.com/sugibuchi/jupyter-storage-explorer"
    expect(dialog.locator("a.jse-about-name")).to_have_attribute(
        "href", re.compile(f"^{re.escape(github)}")
    )
    expect(dialog.locator(".jse-about-head")).to_contain_text("License: MIT")
    polars = dialog.locator(".jse-about-plugin", has_text="polars-support")
    expect(polars).not_to_have_class(re.compile("jse-disabled"))
    link = polars.locator("a.jse-about-plugin-name")
    expect(link).to_have_attribute("href", f"{github}/tree/main/plugins/polars-support")
    expect(link).to_have_attribute("target", "_blank")
    info = polars.locator(".jse-about-info")
    expect(info).to_have_attribute(
        "title",
        "Polars support for Storage Explorer\nBy Tsuyoshi SUGIBUCHI\nLicense: MIT",
    )
    dialog.press("Escape")
    expect(dialog).to_be_hidden()


@check
def sort(x: Explorer) -> None:
    x.go("curated")
    header = x.el.locator(".jse-list th", has_text="Name")
    header.click()  # descending; folders stay first
    expect(x.names).to_have_text(["orders_by_month", "customers", "orders.parquet"])
    header.click()
    expect(x.names).to_have_text(["customers", "orders_by_month", "orders.parquet"])


@check
def filter_list(x: Explorer) -> None:
    x.go("landing", "orders")
    # Typed once the folder's items are shown, as their arrival clears it.
    months = ["orders_2026-07.csv", "orders_2026-08.csv", "orders_2026-09.csv"]
    expect(x.names).to_have_text(months)
    field = x.el.locator(".jse-list-pane .jse-filter-input")
    field.fill("08")
    expect(x.names).to_have_text(["orders_2026-08.csv"])
    expect(x.status).to_contain_text("1 of 3 items match")
    x.el.locator(".jse-list-pane .jse-filter-regex").click()
    field.fill(r"0[79]\.csv$")
    expect(x.names).to_have_text(["orders_2026-07.csv", "orders_2026-09.csv"])
    field.press("Escape")  # clears it
    expect(x.names).to_have_text(months)


@check
def paging(x: Explorer) -> None:
    label = x.el.locator(".jse-page-label")
    following = x.el.locator(".jse-pager button[title='Next page']")
    # Paged by the browser.
    x.go("some", storage="Scratch")
    expect(label).to_have_text("1–100 of 150")
    following.click()
    expect(label).to_have_text("101–150 of 150")
    expect(x.names.first).to_have_text("file_100.txt")
    # Paged by the kernel: over max_browser_items.
    x.go("many", storage="Scratch")
    expect(label).to_have_text("1–100 of 250")
    following.click()
    expect(x.names.first).to_have_text("file_100.txt")
    x.el.locator(".jse-list th", has_text="Name").click()
    expect(x.names.first).to_have_text("file_249.txt")
    x.el.locator(".jse-list-pane .jse-filter-input").fill("file_24")
    expect(label).to_be_hidden()  # one page
    expect(x.names).to_have_count(10)


# --- Previews and data ---


@check
def preview(x: Explorer) -> None:
    x.go("pipelines")
    x.row("README.md").click()
    link = x.el.locator(".jse-status-bar .jse-preview-btn")
    expect(link).to_have_text("Preview (Markdown)")
    link.click()
    expect(x.preview.locator(".jse-markdown")).to_contain_text(
        "Owner: data platform team"
    )
    # The open panel follows the selection.
    x.row("daily_orders.yaml").click()
    expect(x.preview.locator(".jse-text")).to_contain_text("pipeline: daily_orders")
    x.preview.press("Escape")
    expect(x.preview).to_be_hidden()


@check
def preview_follows_clicks(x: Explorer) -> None:
    # While the panel is open, a click previews a file, and a data folder too
    # (a Delta table, a partitioned Parquet dataset), as the kernel finds its
    # format.
    badge = x.preview.locator(".jse-badge")
    x.go("curated")
    x.row("orders.parquet").click()
    x.el.locator(".jse-status-bar .jse-preview-btn").click()
    expect(badge).to_have_text("Parquet · Polars")
    x.row("customers").click()
    expect(x.preview.locator(".jse-preview-name")).to_contain_text("customers")
    expect(badge).to_have_text("Delta Lake table · Polars")
    x.row("orders_by_month").click()
    expect(x.preview.locator(".jse-preview-name")).to_contain_text("orders_by_month")
    expect(badge).to_have_text("Parquet · Polars")
    x.row("orders.parquet").click()
    expect(x.preview.locator(".jse-preview-name")).to_contain_text("orders.parquet")
    x.preview.press("Escape")


@check
def query(x: Explorer) -> None:
    x.go("curated")
    x.row("orders.parquet").click()
    x.el.locator(".jse-status-bar .jse-preview-btn", has_text="Preview").click()
    status = x.preview.locator(".jse-query-status")
    expect(status).to_have_text("Rows 1–100 / 2,400")
    x.preview.locator(".jse-query-bar button[title='Next page']").click()
    expect(status).to_have_text("Rows 101–200 / 2,400")
    # A filter, from the column's funnel.
    header = x.preview.locator(
        "th", has=x.page.locator(".jse-query-name", has_text="channel")
    ).first
    header.locator(".jse-query-filter").click()
    dialog = x.el.locator(".jse-confirm:visible")
    dialog.locator("select").first.select_option(label="Contains")
    dialog.locator("input[type=text], input:not([type])").first.fill("wholesale")
    dialog.get_by_role("button", name="Apply").click()
    expect(x.preview.locator(".jse-query-chips")).to_contain_text(
        "channel contains wholesale"
    )
    expect(status).to_have_text("Rows 1–100 / 341")
    x.preview.locator(".jse-query-bar .jse-btn", has_text="Reset").click()
    expect(status).to_have_text("Rows 1–100 / 2,400")
    x.preview.press("Escape")


@check
def delta_folder(x: Explorer) -> None:
    # The folder shown, with nothing selected: a Delta table, queried.
    x.go("curated", "customers")
    link = x.el.locator(".jse-status-bar .jse-preview-btn")
    expect(link).to_have_text("Preview (Delta Lake table)")
    link.click()
    expect(x.preview.locator(".jse-query-status")).to_contain_text("/ 200")
    x.preview.press("Escape")


@check
def partitioned_parquet(x: Explorer) -> None:
    # Hive-style partitions (year=…/month=…/): one table, its partition
    # columns from the folders' names.
    x.go("curated")
    x.row("orders_by_month").click()
    link = x.el.locator(".jse-status-bar .jse-preview-btn")
    expect(link).to_have_text("Preview (Parquet)")
    link.click()
    expect(x.preview.locator(".jse-query-status")).to_have_text("Rows 1–100 / 2,400")
    for column in ("year", "month"):
        expect(
            x.preview.locator(".jse-query-name", has_text=re.compile(f"^{column}$"))
        ).to_be_visible()
    x.preview.press("Escape")


@check
def python_code(x: Explorer) -> None:
    x.go("curated")
    x.row("orders.parquet").click(button="right")
    x.menu_item("Python code").hover()
    code = x.el.locator(".jse-submenu .jse-menu-item:visible")
    # The engines installed only: development has no pyspark.
    expect(code.filter(has_text="(Polars)").first).to_be_visible()
    expect(code.filter(has_text="(PySpark)")).to_have_count(0)
    # Each recipe by title, with its engine.
    code.filter(has_text="Load as DataFrame (Polars)").click()
    dialog = x.el.locator(".jse-dialog:visible")
    expect(dialog).to_contain_text("Load as DataFrame (Polars)")
    expect(dialog).to_contain_text("read_parquet")
    expect(dialog).to_contain_text("Needs polars")
    dialog.press("Escape")
    expect(dialog).to_be_hidden()


@check
def engines(x: Explorer) -> None:
    # Previews use the engine chosen in the status bar: Polars first.
    engine_btn = x.el.locator(".jse-engine-btn")
    panel = x.el.locator(".jse-preview-panel")
    badge = panel.locator(".jse-badge")
    x.go("curated")
    x.menu(x.row("orders.parquet"), "Preview Parquet")
    expect(badge).to_have_text("Parquet · Polars")
    expect(panel.locator(".jse-query")).to_be_visible()  # the data browser

    def choose(engine: str) -> None:
        engine_btn.click()
        x.menu_item(engine).click()
        expect(engine_btn).to_have_text(engine)

    # Another engine: the preview open is viewed again with it.
    choose("pandas")
    expect(badge).to_have_text("Parquet · pandas")
    expect(panel.locator(".jse-query")).to_be_visible()  # on pandas' rows
    # "Preview as": each format and engine that can view the item.
    x.row("orders.parquet").click(button="right")
    x.menu_item("Preview as").hover()
    x.el.locator(
        ".jse-submenu .jse-menu-item:visible", has_text="Parquet (Polars)"
    ).click()
    expect(badge).to_have_text("Parquet · Polars")
    # A format pandas does not handle: the built-in view, whatever the engine.
    x.go("pipelines")
    x.menu(x.row("README.md"), "Preview Markdown")
    expect(badge).to_have_text("Markdown")
    choose("Polars")


@check
def properties(x: Explorer) -> None:
    x.menu(x.node("landing"), "Properties")
    dialog = x.el.locator(".jse-dialog:visible")
    expect(dialog.locator(".jse-props").first).to_contain_text("Files")
    expect(dialog).to_contain_text("Properties of landing")
    dialog.press("Escape")
    x.go("pipelines")
    x.menu(x.row("ingest.log"), "Properties")
    expect(dialog).to_contain_text("From the storage")
    dialog.press("Escape")


@check
def bookmarks(x: Explorer) -> None:
    x.go("reports")
    star = x.el.locator(".jse-bookmark-btn")
    star.click()
    x.menu_item("Bookmark this folder").click()
    expect(star).to_have_class(ON)
    x.go("landing")
    expect(star).not_to_have_class(ON)
    star.click()
    x.menu_item("[Sales lake] /sales-lake/reports").click()
    expect(x.el.locator(".jse-crumb").last).to_have_text("reports")
    expect(star).to_have_class(ON)
    x.menu(x.node("reports"), "Remove bookmark")
    expect(star).not_to_have_class(ON)


# --- File operations, in Scratch ---


@check
def copy_paste(x: Explorer) -> None:
    x.go("landing")
    x.menu(x.row("products.tsv"), "Copy")
    expect(x.status).to_contain_text("Copied products.tsv")
    x.top("Scratch")
    x.list_menu("Paste products.tsv")
    x.button("Paste").click()
    expect(x.row("products.tsv")).to_be_visible()
    expect(x.status).to_contain_text("Pasted products.tsv")


@check
def copy_paste_folder(x: Explorer) -> None:
    # A folder of the lake, pasted into Scratch as a job: the job ends, and
    # the folder shows without a refresh.
    x.storage("Sales lake")
    x.el.locator(".jse-crumb", has_text="/sales-lake").click()
    # Unsafe mode for the copy, then again for the paste.
    x.el.locator(".jse-unsafe").click()
    x.menu(x.row("curated"), "Copy")
    expect(x.status).to_contain_text("Copied curated")
    x.top("Scratch")
    x.el.locator(".jse-unsafe").click()
    x.list_menu("Paste curated")
    x.button("Paste").click()
    expect(x.row("curated")).to_be_visible()
    expect(x.el.locator(".jse-job")).to_have_count(0)
    expect(x.status).to_contain_text("Pasted curated")


@check
def rename(x: Explorer) -> None:
    x.top("Scratch")
    paste_from_lake(x, "catalog.json")
    x.menu(x.row("catalog.json"), "Rename")
    x.el.locator(".jse-confirm:visible .jse-name-input").fill("catalog-copy.json")
    x.button("Rename").click()
    expect(x.row("catalog-copy.json")).to_be_visible()
    expect(x.row("catalog.json")).to_have_count(0)


@check
def create_folder(x: Explorer) -> None:
    x.top("Scratch")
    x.list_menu("Create a folder")
    field = x.el.locator(".jse-confirm:visible .jse-name-input")
    field.fill("a/b")
    x.button("Create").click()
    expect(x.el.locator(".jse-confirm:visible .jse-error-text")).to_contain_text(
        "without /"
    )
    field.fill("archive")
    x.button("Create").click()
    expect(x.row("archive")).to_be_visible()


@check
def move_by_drag(x: Explorer) -> None:
    x.top("Scratch")
    new_folder(x, "inbox")
    paste_from_lake(x, "catalog.json")
    x.row("catalog.json").drag_to(x.row("inbox"))
    x.button("Move").click()
    expect(x.row("catalog.json")).to_have_count(0)
    x.row("inbox").dblclick()
    expect(x.names).to_have_text(["catalog.json"])


@check
def cut_paste(x: Explorer) -> None:
    x.top("Scratch")
    new_folder(x, "outbox")
    paste_from_lake(x, "catalog.json")
    x.menu(x.row("catalog.json"), "Cut")
    x.menu(x.row("outbox"), "Move catalog.json here")
    x.button("Move").click()
    expect(x.row("catalog.json")).to_have_count(0)
    x.row("outbox").dblclick()
    expect(x.names).to_have_text(["catalog.json"])


@check
def delete(x: Explorer) -> None:
    x.top("Scratch")
    paste_from_lake(x, "catalog.json")
    x.menu(x.row("catalog.json"), "Delete")
    x.button("Delete").click()
    expect(x.row("catalog.json")).to_have_count(0)


@check
def keyboard_shortcuts(x: Explorer) -> None:
    # The list's keys, as its menu's rows (which show them): Ctrl+C, Ctrl+V,
    # F2, Enter, Ctrl+X, Delete; on the selection, while the list has the focus.
    keys = x.page.keyboard
    empty_space = x.el.locator(".jse-list")

    def focus_list() -> None:
        box = empty_space.bounding_box()
        assert box is not None
        empty_space.click(position={"x": 40, "y": box["height"] - 12})

    x.go("landing")
    x.row("products.tsv").click(button="right")
    expect(x.menu_item("Copy").locator(".jse-menu-shortcut")).to_have_text("Ctrl+C")
    keys.press("Escape")
    x.row("products.tsv").click()
    keys.press("Control+c")
    expect(x.status).to_contain_text("Copied products.tsv")
    x.top("Scratch")
    new_folder(x, "keys")
    x.row("keys").click()
    keys.press("Enter")  # opens the folder
    expect(x.el.locator(".jse-crumb").last).to_have_text("keys")
    focus_list()
    keys.press("Control+v")
    x.button("Paste").click()
    expect(x.row("products.tsv")).to_be_visible()
    x.row("products.tsv").click()
    keys.press("F2")
    x.el.locator(".jse-confirm:visible .jse-name-input").fill("keyed.tsv")
    x.button("Rename").click()
    expect(x.row("keyed.tsv")).to_be_visible()
    # Typed in the filter, keys are the filter's.
    x.el.locator(".jse-list-pane .jse-filter input").fill("keyed")
    keys.press("Delete")
    expect(x.el.locator(".jse-confirm:visible")).to_have_count(0)
    x.el.locator(".jse-list-pane .jse-filter input").fill("")
    x.row("keyed.tsv").click()
    keys.press("Control+x")
    x.top("Scratch")
    focus_list()
    keys.press("Control+v")
    x.button("Move").click()
    expect(x.row("keyed.tsv")).to_be_visible()
    x.row("keyed.tsv").click()
    keys.press("Delete")
    x.button("Delete").click()
    expect(x.row("keyed.tsv")).to_have_count(0)


@check
def unsafe_mode(x: Explorer) -> None:
    x.top("Scratch")
    new_folder(x, "old")
    switch = x.el.locator(".jse-unsafe")
    # Locked: no folder operations.
    x.row("old").click(button="right")
    expect(x.menu_item("Delete")).to_have_count(0)
    x.page.keyboard.press("Escape")
    # On for one operation: the folder is moved into another.
    switch.click()
    expect(switch).to_have_class(ON)
    x.row("old").drag_to(x.row("exports"))
    x.button("Move").click()
    expect(x.row("old")).to_have_count(0)
    expect(switch).not_to_have_class(ON)
    # And deleted.
    x.row("exports").dblclick()
    switch.click()
    x.menu(x.row("old"), "Delete")
    expect(x.el.locator(".jse-confirm:visible")).to_contain_text(
        "Folders are deleted with everything in them"
    )
    x.button("Delete").click()
    expect(x.row("old")).to_have_count(0)


# --- Transfers: the user's computer and JupyterLab ---


@check
def download_to_local(x: Explorer) -> None:
    x.go("pipelines")
    with x.page.expect_download() as download:
        x.menu(x.row("ingest.log"), "Download to local")
    assert download.value.suggested_filename == "ingest.log"
    expect(x.status).to_contain_text("Downloaded 1 file to local")


@check
def download_to_jupyterlab(x: Explorer) -> None:
    x.go("pipelines")
    x.menu(x.row("monthly_revenue.sql"), "Download to JupyterLab")
    x.button("Download").click()
    expect(x.status).to_contain_text("Downloaded monthly_revenue.sql")
    wait_for((x.lab.root / "monthly_revenue.sql").is_file, "the file on the server")


@check
def download_by_drag(x: Explorer) -> None:
    # Dropped on JupyterLab's file browser (the launcher's extension).
    x.go("pipelines")
    x.row("daily_orders.yaml").drag_to(x.page.locator(".jp-DirListing-content").first)
    dialog = x.page.locator(".jp-Dialog")
    expect(dialog).to_contain_text("Download daily_orders.yaml from Storage Explorer")
    dialog.get_by_role("button", name="Download").click()
    wait_for((x.lab.root / "daily_orders.yaml").is_file, "the file on the server")


@check
def download_folder_by_drag(x: Explorer) -> None:
    # A folder (unsafe mode) dropped on JupyterLab's file browser: not
    # downloaded, and said so, as only the drop can tell what the drag holds.
    x.storage("Sales lake")
    x.el.locator(".jse-crumb", has_text="/sales-lake").click()
    x.el.locator(".jse-unsafe").click()
    x.row("reports").drag_to(x.page.locator(".jp-DirListing-content").first)
    dialog = x.page.locator(".jp-Dialog")
    expect(dialog).to_contain_text("Download reports from Storage Explorer")
    dialog.get_by_role("button", name="Download").click()
    # In JupyterLab's notifications (the bell in the status bar).
    x.page.locator(".jp-Notification-Status").click()
    expect(
        x.page.get_by_text("reports: folders are not downloaded").first
    ).to_be_visible()
    x.page.locator(".jp-Notification-Status").click()
    assert not (x.lab.root / "reports").exists()


@check
def drag_from_another_page_refused(x: Explorer) -> None:
    # A drop of our type from another page (tab, window, site), whatever it
    # carries: never taken, as only this page's drag (by its id) is.
    x.top("Scratch")
    crafted = json.dumps(
        {
            "explorer": "elsewhere",
            "filesystem": {"name": "Sales lake"},
            "folders": True,
            "unsafe": True,
            "files": [
                {
                    "path": "/sales-lake/catalog.json",
                    "name": "catalog.json",
                    "location": {
                        "kind": "fsspec",
                        "url": "memory:///sales-lake/catalog.json",
                    },
                }
            ],
        }
    )
    drop = """(list, [value, pageDrag]) => {
      const key = Symbol.for("jupyter-storage-explorer.drag");
      globalThis[key] = pageDrag;
      const data = new DataTransfer();
      data.setData("application/x-jupyter-storage-explorer-items", value);
      for (const type of ["dragenter", "dragover", "drop"]) {
        list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
      }
      globalThis[key] = null;
    }"""
    lst = x.el.locator(".jse-list")
    # No drag on this page: not even taken.
    lst.evaluate(drop, [crafted, None])
    # This page has a drag, but the drop carries another id.
    page_drag = {"id": "this-page", "explorer": "x", "unsafe": False, "items": {}}
    lst.evaluate(drop, ["another-page", page_drag])
    expect(x.status).to_contain_text(
        "Drag files between explorers of one JupyterLab page"
    )
    expect(x.el.locator(".jse-confirm:visible")).to_have_count(0)
    expect(x.row("catalog.json")).to_have_count(0)


@check
def hidden_characters_shown(x: Explorer) -> None:
    # A name with a bidi override reads as another ("reportexe.jpg"): shown
    # with the character escaped, in the list and the messages.
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list) => {
          const data = new DataTransfer();
          data.items.add(new File(["x"], "report\u202egpj.exe", { type: "application/octet-stream" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }"""
    )
    expect(x.el.locator(".jse-confirm:visible")).to_contain_text("report\\u202egpj.exe")
    x.button("Upload").click()
    expect(x.row("report\\u202egpj.exe")).to_be_visible()
    expect(x.status).to_contain_text("Uploaded report\\u202egpj.exe")


@check
def upload_from_computer(x: Explorer) -> None:
    # A native drop of a file, as from the computer's file manager.
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list) => {
          const data = new DataTransfer();
          data.items.add(new File(["hello\\n"], "hello.txt", { type: "text/plain" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }"""
    )
    x.button("Upload").click()
    expect(x.row("hello.txt")).to_be_visible()
    expect(x.status).to_contain_text("Uploaded hello.txt")


@check
def upload_from_jupyterlab(x: Explorer) -> None:
    # A drop of JupyterLab's file browser (a Lumino drag, as it sends it).
    (x.lab.root / "from_lab.txt").write_text("from JupyterLab\n", encoding="utf-8")
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list) => {
          for (const type of ["lm-dragenter", "lm-dragover", "lm-drop"]) {
            const ev = new Event(type, { bubbles: true, cancelable: true });
            ev.mimeData = {
              hasData: (mime) => mime === "application/x-jupyter-icontents",
              getData: () => ["from_lab.txt"],
            };
            ev.proposedAction = "move";
            ev.dropAction = "none";
            list.dispatchEvent(ev);
          }
        }"""
    )
    x.button("Upload").click()
    expect(x.row("from_lab.txt")).to_be_visible()


# --- JupyterLab: its editors and tabs (the launcher's extension) ---


@check
def open_in_jupyterlab(x: Explorer) -> None:
    x.top("Scratch")
    # A text file, which opens in JupyterLab's editor.
    paste_from_lake(x, "daily_orders.yaml", "pipelines")
    x.row("daily_orders.yaml").click()
    # Previewed, to see the edit.
    x.el.locator(".jse-status-bar .jse-preview-btn").click()
    x.row("daily_orders.yaml").dblclick()
    editor = x.page.locator(".jp-FileEditor .cm-content").first
    expect(editor).to_contain_text("pipeline: daily_orders")
    x.page.locator(".jp-FileEditor .cm-line").first.click()
    x.page.keyboard.press("Control+Home")
    x.page.keyboard.type("# edited\n")
    x.page.keyboard.press("Control+s")
    dirty = x.page.locator(".lm-TabBar-tab.jp-mod-current.jp-mod-dirty")
    expect(dirty).to_have_count(0)
    x.back_to_notebook()
    expect(x.preview).to_contain_text("# edited")
    x.preview.press("Escape")


# A notebook whose cell claims to be trusted, with outputs that run script
# when rendered as trusted: written by anyone with access to a storage.
UNTRUSTED_NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "name": "python3",
            "display_name": "Python 3",
            "language": "python",
        }
    },
    "cells": [
        {
            "cell_type": "code",
            "execution_count": 1,
            "id": "c1",
            "metadata": {"trusted": True},
            "source": "1",
            "outputs": [
                {
                    "output_type": "display_data",
                    "metadata": {},
                    "data": {
                        "text/html": '<img src="x" onerror="window.__jse_ran = true">',
                        "application/javascript": "window.__jse_ran = true;",
                        "text/plain": "output",
                    },
                }
            ],
        }
    ],
}


@check
def notebook_opened_untrusted(x: Explorer) -> None:
    # A notebook from a storage, opened in JupyterLab: its outputs never run
    # script by themselves, whatever its cells claim.
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list, text) => {
          const data = new DataTransfer();
          data.items.add(new File([text], "untrusted.ipynb", { type: "application/json" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }""",
        json.dumps(UNTRUSTED_NOTEBOOK),
    )
    x.button("Upload").click()
    x.row("untrusted.ipynb").dblclick()
    expect(
        x.page.locator(
            ".jp-NotebookPanel:not(.lm-mod-hidden) .jp-OutputArea-output"
        ).first
    ).to_be_visible()
    x.page.wait_for_timeout(1500)
    assert x.page.evaluate("window.__jse_ran") is None, "the notebook's outputs ran"
    x.back_to_notebook()


@check
def notebook_trust_kept(x: Explorer) -> None:
    # Trusted by the user and saved, a notebook from a storage is trusted
    # when opened again (signed with nbformat's notary, as JupyterLab does).
    notebook = json.loads(json.dumps(UNTRUSTED_NOTEBOOK))
    notebook["cells"][0]["outputs"][0]["data"] = {
        "application/javascript": "window.__jse_trusted_ran = (window.__jse_trusted_ran || 0) + 1;",
        "text/plain": "output",
    }
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list, text) => {
          const data = new DataTransfer();
          data.items.add(new File([text], "trusted.ipynb", { type: "application/json" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }""",
        json.dumps(notebook),
    )
    x.button("Upload").click()
    x.row("trusted.ipynb").dblclick()
    shown = x.page.locator(".jp-NotebookPanel:not(.lm-mod-hidden)")
    expect(shown.locator(".jp-OutputArea-output").first).to_be_visible()
    assert x.page.evaluate("window.__jse_trusted_ran") is None
    # Trust it (JupyterLab's command, from its palette: the notebook focused
    # first, as the shortcut needs the focus in JupyterLab), then save.
    x.page.locator(".lm-TabBar-tab.jp-mod-current", has_text="trusted.ipynb").click()
    x.page.keyboard.press("Control+Shift+c")
    x.page.locator(".lm-CommandPalette-input").fill("Trust Notebook")
    x.page.locator(
        ".lm-CommandPalette-item:visible", has_text="Trust Notebook"
    ).first.click()
    x.page.locator(".jp-Dialog-footer .jp-Dialog-button", has_text="Trust").click()
    x.page.wait_for_timeout(1000)
    trusted_runs = x.page.evaluate("window.__jse_trusted_ran || 0")
    x.page.keyboard.press("Control+s")
    expect(x.page.locator(".lm-TabBar-tab.jp-mod-current.jp-mod-dirty")).to_have_count(
        0
    )
    # Closed, then opened again from the explorer: trusted, its output runs.
    x.page.locator(".lm-TabBar-tab.jp-mod-current .lm-TabBar-tabCloseIcon").click()
    x.back_to_notebook()
    x.row("trusted.ipynb").dblclick()
    expect(shown.locator(".jp-OutputArea-output").first).to_be_visible()
    x.page.wait_for_timeout(1500)
    assert x.page.evaluate("window.__jse_trusted_ran || 0") > trusted_runs, (
        "not trusted again"
    )
    x.back_to_notebook()


# A notebook whose outputs link to an image by a relative path (next to it),
# which the drive does not serve.
RELATIVE_IMAGE_NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "name": "python3",
            "display_name": "Python 3",
            "language": "python",
        }
    },
    "cells": [
        {
            "cell_type": "markdown",
            "id": "m1",
            "metadata": {},
            "source": "![chart](chart.png)",
        },
        {
            "cell_type": "code",
            "execution_count": 1,
            "id": "c1",
            "metadata": {},
            "source": "1",
            "outputs": [
                {
                    "output_type": "display_data",
                    "metadata": {},
                    "data": {
                        "text/html": '<img src="chart.png">',
                        "text/plain": "chart",
                    },
                }
            ],
        },
    ],
}


@check
def notebook_relative_links_and_download(x: Explorer) -> None:
    # Relative links load nothing, without an error; File > Download saves
    # the file itself.
    text = json.dumps(RELATIVE_IMAGE_NOTEBOOK)
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list, text) => {
          const data = new DataTransfer();
          data.items.add(new File([text], "charts.ipynb", { type: "application/json" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }""",
        text,
    )
    x.button("Upload").click()
    x.row("charts.ipynb").dblclick()
    panel = x.page.locator(".jp-NotebookPanel:not(.lm-mod-hidden)")
    expect(panel.locator(".jp-OutputArea-output").first).to_be_visible()
    x.page.wait_for_timeout(1500)
    expect(panel).not_to_contain_text("Javascript Error")
    with x.page.expect_download() as download:
        x.page.locator(".lm-MenuBar-itemLabel", has_text="File").click()
        x.page.locator(".lm-Menu-itemLabel", has_text="Download").first.click()
    saved = json.loads(pathlib.Path(download.value.path()).read_text(encoding="utf-8"))
    assert saved["cells"][0]["source"] == "![chart](chart.png)", saved
    x.back_to_notebook()


# Markdown whose HTML would restyle or cover JupyterLab, or ask for a password.
HOSTILE_MARKDOWN = """# Report

<p>x</p><style>.jp-LabShell { display: none }</style>
<div style="position: fixed; inset: 0; background: white">Session expired</div>
<form action="https://evil.example/login"><input type="password"><button>Sign in</button></form>
<img src="x" onerror="window.__jse_ran = true">

| a | b |
|--:|---|
| 1 | 2 |
"""


@check
def markdown_preview_sanitized(x: Explorer) -> None:
    x.top("Scratch")
    x.el.locator(".jse-list").evaluate(
        """(list, text) => {
          const data = new DataTransfer();
          data.items.add(new File([text], "report.md", { type: "text/markdown" }));
          for (const type of ["dragenter", "dragover", "drop"]) {
            list.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
          }
        }""",
        HOSTILE_MARKDOWN,
    )
    x.button("Upload").click()
    x.row("report.md").click()
    x.el.locator(".jse-status-bar .jse-preview-btn").click()
    markdown = x.preview.locator(".jse-markdown")
    expect(markdown.locator("h1")).to_have_text("Report")
    expect(markdown.locator("td").first).to_have_text("1")  # tables kept
    for selector in ("style", "form", "input", "button", "[style]"):
        expect(markdown.locator(selector)).to_have_count(0)
    expect(x.page.locator(".jp-LabShell")).to_be_visible()
    assert x.page.evaluate("window.__jse_ran") is None, "the file's script ran"
    x.preview.press("Escape")


@check
def view_in_new_tab(x: Explorer) -> None:
    # Data: the data browser, a DataExplorer, in the tab.
    x.go("curated")
    x.menu(x.row("orders.parquet"), "View Parquet in new tab")
    tab = x.page.locator(".jse-query-tab")
    expect(tab.locator(".jse-query-status")).to_have_text("Rows 1–100 / 2,400")
    expect(x.page.locator(".lm-TabBar-tab.jp-mod-current")).to_contain_text(
        "orders.parquet"
    )
    x.page.locator(".lm-TabBar-tab.jp-mod-current .lm-TabBar-tabCloseIcon").click()
    expect(tab).to_have_count(0)
    x.back_to_notebook()
    # Other views: a ViewTab, rendered as in the preview panel.
    x.go("pipelines")
    x.menu(x.row("README.md"), "View Markdown in new tab")
    view = x.page.locator(".jse-query-tab .jse-view-tab")
    expect(view.locator(".jse-markdown")).to_contain_text("Sales lake")
    x.page.locator(".lm-TabBar-tab.jp-mod-current .lm-TabBar-tabCloseIcon").click()
    expect(view).to_have_count(0)
    x.back_to_notebook()


# --- The launcher's tab ---


# Checks given the server and the page, each on a page of its own.
LAB_CHECKS: dict[str, Callable[[Lab, Page], None]] = {}


def lab_check(fn: Callable[[Lab, Page], None]) -> Callable[[Lab, Page], None]:
    LAB_CHECKS[fn.__name__] = fn
    return fn


# An explorer whose preview panel starts open, and labels its on_change and
# on_query_change functions write to.
CALLBACKS = """\
import demo_data
import ipywidgets
from jupyter_storage_explorer import StorageExplorer

explorer = StorageExplorer(
    filesystems=demo_data.filesystems(), supports=demo_data.supports(), preview_panel="open"
)
selected = ipywidgets.Label("-").add_class("smoke-selected")
rows = ipywidgets.Label("-").add_class("smoke-rows")


def show_selected(e):
    selected.value = ",".join(url.rsplit("/", 1)[-1] for url in e.selected_urls) or "-"


def show_rows(e):
    result = e.query_result()
    rows.value = "none" if result is None else str(len(result.collect()))


explorer.on_change(show_selected)
explorer.on_query_change(show_rows)
display(explorer, selected, rows)"""


@lab_check
def local_paths_copied(lab: Lab, page: Page) -> None:
    # On a local disk, items have a plain path besides their file:/// URL:
    # "Copy path" copies it, and "Copy" puts it on the system clipboard.
    folder = lab.root / "local-disk"
    folder.mkdir(exist_ok=True)
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    source = f"from jupyter_storage_explorer import StorageExplorer\nStorageExplorer({str(folder)!r})"
    x = Explorer(lab, page, source)
    clipboard = "() => navigator.clipboard.readText()"
    x.menu(x.row("notes.txt"), "Copy path")
    expect(x.status).to_contain_text("Copied path")
    assert page.evaluate(clipboard) == str(folder / "notes.txt")
    x.menu(x.row("notes.txt"), "Copy URL")
    expect(x.status).to_contain_text("Copied URL")
    assert page.evaluate(clipboard) == (folder / "notes.txt").as_uri()
    x.row("notes.txt").click(button="right")
    x.el.locator(".jse-menu:not(.jse-submenu) > .jse-menu-item:visible").filter(
        has=page.get_by_text("Copy", exact=True)
    ).click()
    expect(x.status).to_contain_text("Copied notes.txt")
    assert page.evaluate(clipboard) == str(folder / "notes.txt")


# Memory filesystems as an Azure account and as S3, to their mappers: folders
# at their top are containers and buckets (FileSystemMapper.levels), with the
# icons of Azure's mapper, and an emoji of the mapper's own for buckets
# (FileSystemMapper.css).
STORAGE_LEVELS = """\
from fsspec.implementations.memory import MemoryFileSystem
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems import (
    AbfsLocation, AzureBlobMapper, FileSystemMapper, S3Location,
)

class Account(MemoryFileSystem):
    store, pseudo_dirs = {}, [""]

class Buckets(MemoryFileSystem):
    store, pseudo_dirs = {}, [""]

class AccountMapper(FileSystemMapper):
    classes, levels = ("__main__.Account",), ("account", "container")
    css = AzureBlobMapper.css
    def to_location(self, fs, path):
        container, _, key = path.strip("/").partition("/")
        return AbfsLocation(account_name="lake", container_name=container, path=key)

class BucketMapper(FileSystemMapper):
    classes, levels = ("__main__.Buckets",), ("endpoint", "bucket")
    css = '''
    [data-fs-level="bucket"] .jse-icon svg { display: none; }
    [data-fs-level="bucket"] .jse-icon::before { content: "B"; }
    '''
    def to_location(self, fs, path):
        bucket, _, key = path.strip("/").partition("/")
        return S3Location(bucket=bucket, key=key)

account, buckets = Account(), Buckets()
account.pipe_file("/raw/sales/a.csv", b"a")
buckets.pipe_file("/landing/b.csv", b"b")
StorageExplorer(
    filesystems={"Azure": account, "S3": buckets},
    filesystem_mappers=[AccountMapper(), BucketMapper()],
)"""


def before(target: Locator, prop: str) -> str:
    """A computed property of the ``::before`` of ``target``'s icon."""
    return target.locator(".jse-icon").evaluate(
        "(el, prop) => getComputedStyle(el, '::before').getPropertyValue(prop)", prop
    )


@lab_check
def storage_levels(lab: Lab, page: Page) -> None:
    # Accounts, containers and buckets get their rows' data-fs-level, and the
    # icons their mapper's CSS gives them, while the explorer shows one of
    # its storages (data-fs-mapper); plain folders keep the folder icon.
    x = Explorer(lab, page, STORAGE_LEVELS)
    svg = ".jse-icon svg"
    expect(x.el).to_have_attribute("data-fs-protocol", "abfs")
    expect(x.el).to_have_attribute("data-fs-mapper", "__main__.AccountMapper")
    root = x.el.locator(".jse-tree .jse-node").first
    expect(root).to_have_attribute("data-fs-level", "account")
    expect(x.node("raw")).to_have_attribute("data-fs-level", "container")
    expect(x.row("raw")).to_have_attribute("data-fs-level", "container")
    # Azure's icons: masks, in Azure's colour; the selection's in the tree's
    # current folder, the root.
    for target in (root, x.row("raw")):
        expect(target.locator(svg)).to_be_hidden()
        assert "data:image/svg+xml" in before(target, "mask-image")
    assert before(x.row("raw"), "background-color") == "rgb(0, 120, 212)"
    assert before(root, "background-color") != "rgb(0, 120, 212)"
    # Users' CSS, as in custom.css, overrides the mapper's, in selected rows too.
    user_css = page.add_style_tag(
        content='.jse-browser [data-fs-level="container"] .jse-icon::before'
        ' { content: "C"; mask: none; background: none; }'
    )
    x.row("raw").click()
    expect(x.row("raw")).to_have_class(re.compile("jse-selected"))
    assert before(x.row("raw"), "content") == '"C"'
    assert before(x.row("raw"), "mask-image") == "none"
    assert before(x.row("raw"), "background-color") == "rgba(0, 0, 0, 0)"
    user_css.evaluate("style => style.remove()")
    x.row("raw").dblclick()
    # The path: "/ raw", no separator after a root of "/".
    expect(x.el.locator(".jse-crumb")).to_have_text(["/", "raw"])
    expect(x.el.locator(".jse-crumbs .jse-sep")).to_have_count(0)
    expect(x.row("sales")).not_to_have_attribute("data-fs-level", re.compile("."))
    expect(x.row("sales").locator(svg)).to_have_attribute("data-icon", "folder")
    expect(x.row("sales").locator(svg)).to_be_visible()
    x.el.locator(".jse-fs-select").select_option("S3")
    expect(x.el).to_have_attribute("data-fs-mapper", "__main__.BucketMapper")
    expect(x.node("landing")).to_have_attribute("data-fs-level", "bucket")
    # The bucket mapper's own CSS, and none of Azure's.
    expect(x.row("landing").locator(svg)).to_be_hidden()
    assert before(x.row("landing"), "content") == '"B"'
    assert before(x.row("landing"), "mask-image") == "none"
    # Each mapper's CSS once on the page.
    for mapper in ("AccountMapper", "BucketMapper"):
        style = page.locator(f'style[data-jse-mapper="__main__.{mapper}"]')
        expect(style).to_have_count(1)


# A support taking seconds to view text files, as a Spark session starting.
SLOW_PREVIEW = """\
import io
import time
import fsspec
import polars as pl
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import Csv, FormatSupport, QueryView, Text, TextView, ViewLimits
from jupyter_storage_explorer_polars_support import PolarsEngine

class SlowText(FormatSupport):
    format = Text

    def view(self, fmt, ctx, options, limits):
        if ctx.name == "broken.txt":
            raise ValueError("cannot read broken.txt")
        time.sleep(4)
        return TextView(text=ctx.fs.cat_file(ctx.path).decode())

class CsvInMemory(FormatSupport):
    format = Csv
    engine = PolarsEngine

    def view(self, fmt, ctx, options, limits):
        return QueryView(data=pl.read_csv(io.BytesIO(ctx.fs.cat_file(ctx.path))).lazy())

def slow_page(lf, offset, length):
    time.sleep(3)  # as a Spark job for each page; then polars reads it

memory = fsspec.filesystem("memory")
memory.pipe_file("/slow/notes.txt", b"read slowly")
memory.pipe_file("/slow/broken.txt", b"x")
memory.pipe_file("/slow/table.csv", b"a\\n1\\n2\\n3\\n")
memory.pipe_file("/slow/inner/other.txt", b"x")
StorageExplorer(
    "/slow",
    fs=memory,
    supports=[SlowText, CsvInMemory],
    preview_panel="open",
    fetch_rows=slow_page,
    view_limits=ViewLimits(max_live_rows=1),  # live queries: each page fetched
)"""


@lab_check
def slow_preview(lab: Lab, page: Page) -> None:
    # A slow view loads in the background: the panel says so at once, and
    # the explorer answers meanwhile, e.g. showing another folder.
    x = Explorer(lab, page, SLOW_PREVIEW)
    x.row("notes.txt").click()
    expect(x.preview.locator(".jse-placeholder")).to_have_text("Loading…")
    x.row("inner").dblclick()
    expect(x.el.locator(".jse-crumb").last).to_have_text("inner", timeout=2_000)
    expect(x.preview.locator(".jse-text")).to_contain_text(
        "read slowly", timeout=10_000
    )
    # A view tab opens at once too, saying it loads, then shows the view.
    x.el.locator(".jse-crumb").first.click()
    x.menu(x.row("notes.txt"), "View Text in new tab")
    tab = x.page.locator(".jse-query-tab")
    expect(tab.locator(".jse-view-tab-message")).to_have_text("Loading…")
    expect(tab.locator(".jse-text")).to_contain_text("read slowly", timeout=10_000)
    expect(tab.locator(".jse-view-tab-message")).to_have_count(0)
    x.back_to_notebook()
    # A view failing: its tab says why.
    x.menu(x.row("broken.txt"), "View Text in new tab")
    message = x.page.locator(".jse-query-tab .jse-view-tab-message.jse-mod-error")
    expect(message).to_contain_text("cannot read broken.txt")
    x.back_to_notebook()
    # The data browser's pages too: the explorer answers while one is read.
    x.row("table.csv").click()
    expect(x.preview.locator(".jse-query-status")).to_have_text("Loading…")
    x.row("inner").dblclick()
    expect(x.el.locator(".jse-crumb").last).to_have_text("inner", timeout=2_000)
    expect(x.preview.locator(".jse-query tbody tr")).to_have_count(3, timeout=10_000)


# CSV files polars cannot read itself (here in memory): read through fsspec,
# the large one once the user chooses how much (ViewWithChoice).
PROMPTS = """\
import fsspec
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import ViewLimits

memory = fsspec.filesystem("memory")
memory.pipe_file("/prompts/small.csv", b"a\\n1\\n2\\n")
memory.pipe_file("/prompts/large.csv", b"a\\n" + b"1\\n" * 3000)
StorageExplorer(
    "/prompts",
    fs=memory,
    preview_panel="open",
    view_limits=ViewLimits(max_whole_file_bytes=1024),
)"""


@lab_check
def prompts(lab: Lab, page: Page) -> None:
    # A small file is read at once; a large one asks first, in the panel.
    x = Explorer(lab, page, PROMPTS)
    x.row("small.csv").click()
    expect(x.preview.locator(".jse-query tbody tr")).to_have_count(2)
    x.row("large.csv").click()
    prompt = x.preview.locator(".jse-prompt")
    expect(prompt).to_contain_text("Polars cannot read this storage itself")
    # Cancelled: nothing read, and a button to ask again.
    prompt.get_by_role("button", name="Cancel").click()
    expect(x.preview.locator(".jse-notice")).to_contain_text("Not previewed")
    x.preview.get_by_role("button", name="Preview again").click()
    # Its first KB: the data browser says it holds the first part only.
    x.preview.get_by_role("button", name="Its first 1 KB").click()
    expect(x.preview.locator(".jse-query tbody tr").first).to_be_visible()
    expect(x.preview.locator(".jse-prompt")).to_have_count(0)
    expect(x.preview.locator(".jse-query-mode-note")).to_have_text(
        "First part of the data"
    )
    # In a new tab, the tab asks, then shows the data instead.
    x.menu(x.row("large.csv"), "View CSV in new tab")
    tab = x.page.locator(".jse-query-tab")
    tab.get_by_role("button", name="The whole file (5 KB)").click()
    expect(tab.locator(".jse-query tbody tr").first).to_be_visible()
    expect(tab.locator(".jse-prompt")).to_have_count(0)
    x.back_to_notebook()


# A support failing as Spark does, with the Java stack trace, and a file whose
# info cannot be read.
ERRORS = """\
from fsspec.implementations.memory import MemoryFileSystem
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import FormatSupport, Text

class Py4JJavaError(Exception):
    pass

class SparkLike(FormatSupport):
    format = Text

    def view(self, fmt, ctx, options, limits):
        raise Py4JJavaError(
            "An error occurred while calling o57.parquet.\\n"
            ": java.lang.ClassNotFoundException: Class AzureBlobFileSystem not found\\n"
            "\\tat org.apache.hadoop.conf.Configuration.getClass(Configuration.java:2688)\\n"
        )

class Locked(MemoryFileSystem):
    store, pseudo_dirs = {}, [""]

    def info(self, path, **kwargs):
        if path.endswith("locked.txt"):
            raise PermissionError("locked.txt is not yours")
        return super().info(path, **kwargs)

fs = Locked()
fs.pipe_file("/errors/data.txt", b"x")
fs.pipe_file("/errors/locked.txt", b"x")
StorageExplorer("/errors", fs=fs, supports=[SparkLike], preview_panel="open")"""


@lab_check
def readable_errors(lab: Lab, page: Page) -> None:
    # A long error shows its first line, the Java exception for Spark's, and
    # the rest under "Details", in the preview and in a tab; an error in the
    # status bar stays until clicked.
    x = Explorer(lab, page, ERRORS)
    java = "java.lang.ClassNotFoundException: Class AzureBlobFileSystem not found"
    x.row("data.txt").click()
    error = x.preview.locator(".jse-preview-error")
    expect(error.locator(".jse-error-summary")).to_have_text(java)
    stack = error.locator(".jse-error-details pre")
    expect(stack).to_be_hidden()
    error.locator(".jse-error-details summary").click()
    expect(stack).to_contain_text("at org.apache.hadoop.conf.Configuration")
    x.menu(x.row("data.txt"), "View Text in new tab")
    message = page.locator(".jse-query-tab .jse-view-tab-message.jse-mod-error")
    expect(message).to_contain_text(java)
    expect(message.locator("pre")).to_be_hidden()
    x.back_to_notebook()
    x.menu(x.row("locked.txt"), "Properties")
    expect(x.status).to_contain_text("locked.txt is not yours")
    page.wait_for_timeout(2_500)  # longer than a notice stays
    expect(x.status).to_contain_text("locked.txt is not yours")
    x.status.click()
    expect(x.status).not_to_contain_text("locked.txt is not yours")


# Explorers of the toggles: folder operations never or always, "Python code"
# of no engine or one.
TOGGLES = """\
import fsspec
from jupyter_storage_explorer import StorageExplorer

memory = fsspec.filesystem("memory")
memory.pipe_file("/toggles/a.csv", b"x,y\\n1,2\\n")
memory.pipe_file("/toggles/folder/b.txt", b"b")
StorageExplorer("/toggles", fs=memory, unsafe_mode={unsafe!r}, code_snippet={code!r})"""


@lab_check
def toggles(lab: Lab, page: Page) -> None:
    # unsafe_mode="blocked": no switch, no folder operations; code_snippet
    # "disabled": no "Python code".
    x = Explorer(lab, page, TOGGLES.format(unsafe="blocked", code="disabled"))
    expect(x.el.locator(".jse-unsafe")).to_be_hidden()
    x.row("folder").click(button="right")
    expect(x.menu_item("Rename")).to_have_count(0)
    expect(x.menu_item("Delete")).to_have_count(0)
    page.keyboard.press("Escape")
    x.row("a.csv").click(button="right")
    expect(x.menu_item("Preview")).to_be_visible()
    expect(x.menu_item("Python code")).to_have_count(0)
    page.keyboard.press("Escape")
    # "always": no switch, folder operations at all times; one engine's code.
    x = Explorer(lab, page, TOGGLES.format(unsafe="always", code=["pandas"]))
    expect(x.el.locator(".jse-unsafe")).to_be_hidden()
    x.row("folder").click(button="right")
    expect(x.menu_item("Delete")).to_be_visible()
    page.keyboard.press("Escape")
    x.row("a.csv").click(button="right")
    x.menu_item("Python code").hover()
    code = x.el.locator(".jse-submenu .jse-menu-item:visible")
    expect(code.first).to_contain_text("(pandas)")
    expect(code.filter(has_text="(Polars)")).to_have_count(0)
    page.keyboard.press("Escape")


@check
def excel_sheets(x: Explorer) -> None:
    # A workbook's sheets on tabs below the data browser (a table set, from
    # polars' and pandas' Excel views): the first shown, then the one chosen.
    tables = x.preview.locator(".jse-table-set")
    tabs = tables.locator(".jse-table-set-tabs .jse-table-set-tab")
    status = tables.locator(".jse-query-status")
    active = re.compile(r"\bjse-active\b")
    x.go("reports")
    for engine in ("Polars", "pandas"):
        x.row("budget_2026.xlsx").click(button="right")
        x.menu_item("Preview as").hover()
        x.el.locator(
            ".jse-submenu .jse-menu-item:visible", has_text=f"({engine})"
        ).click()
        expect(x.preview.locator(".jse-badge")).to_have_text(
            f"Excel workbook · {engine}"
        )
        expect(tabs).to_have_text(["Budget 2026", "Notes"])
        expect(tabs.first).to_have_class(active)
        expect(status).to_have_text("Rows 1–36 / 36")
        tabs.last.click()
        expect(tabs.last).to_have_class(active)
        expect(tables.locator(".jse-query thead")).to_contain_text("Figures in EUR")
    x.preview.press("Escape")


# A support of the explorer's own, viewing Excel workbooks' sheets in a tree,
# under a group: a table set's other selector.
TABLE_SET_TREE = """\
import demo_data
import polars as pl
from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import Excel, FormatSupport, Leaf, Node, TableSetView
from jupyter_storage_explorer_polars_support import PolarsEngine

class SheetsByPolars(FormatSupport):
    format = Excel
    engine = PolarsEngine

    def view(self, fmt, ctx, options, limits):
        sheets = pl.read_excel(ctx.fs.cat_file(ctx.path), sheet_id=0)
        tables = [Leaf(label=name, id=name) for name in sheets]
        return TableSetView(nodes=[Node(label="workbook", children=tables)], loader=sheets.__getitem__)

supports = [SheetsByPolars, *demo_data.supports()]
StorageExplorer(filesystems=demo_data.filesystems(), supports=supports)"""


@lab_check
def table_set_tree(lab: Lab, page: Page) -> None:
    # A table set's tables in a tree beside the data browser, and in a tab of
    # its own.
    x = Explorer(lab, page, TABLE_SET_TREE)
    x.go("reports")
    x.row("budget_2026.xlsx").click()
    x.el.locator(".jse-status-bar .jse-preview-btn").click()
    tables = x.preview.locator(".jse-table-set")
    tree = tables.locator(".jse-table-set-tree")
    rows = tree.locator(".jse-table-set-row")
    expect(rows).to_have_text(["workbook", "Budget 2026", "Notes"])
    tree.locator(".jse-table-set-leaf", has_text="Notes").click()
    expect(tree.locator(".jse-table-set-leaf.jse-active")).to_have_text("Notes")
    expect(tables.locator(".jse-query thead")).to_contain_text("Figures in EUR")
    x.preview.locator("button[title='View in a new tab']").click()
    tab = page.locator(".jse-table-set-view-tab")
    expect(tab.locator(".jse-table-set-leaf")).to_have_text(["Budget 2026", "Notes"])
    expect(tab.locator(".jse-query-status")).to_have_text("Rows 1–36 / 36")
    x.back_to_notebook()


# duckdb-support's engine on a storage DuckDB cannot read itself: a database
# (copied to the kernel's disk), a SQLite file of the same extension, and a
# Parquet file (read through the explorer's filesystem).
DUCKDB = """\
import pathlib
import tempfile
import duckdb
import fsspec
from jupyter_storage_explorer import StorageExplorer

folder = pathlib.Path(tempfile.mkdtemp())
con = duckdb.connect(str(folder / "shop.db"))
con.sql("create schema sales; create table sales.orders as select range as id from range(250)")
con.sql("create table main.customers as select range as id from range(10)")
con.sql(f"copy (select range as id from range(300)) to '{(folder / 'o.parquet').as_posix()}'")
con.close()
memory = fsspec.filesystem("memory")
memory.pipe_file("/duck/shop.db", (folder / "shop.db").read_bytes())
memory.pipe_file("/duck/orders.parquet", (folder / "o.parquet").read_bytes())
memory.pipe_file("/duck/other.db", b"SQLite format 3\\0" + bytes(100))
StorageExplorer("/duck", fs=memory, engine_preference=["duckdb"])"""


@lab_check
def duckdb_engine(lab: Lab, page: Page) -> None:
    # A database's tables and views in a tree, by schema, the data browser on
    # the one chosen; Parquet with DuckDB; a ".db" of SQLite has no format.
    x = Explorer(lab, page, DUCKDB)
    expect(x.el.locator(".jse-engine-btn")).to_have_text("DuckDB")
    x.row("shop.db").click()
    link = x.el.locator(".jse-status-bar .jse-preview-btn")
    expect(link).to_have_text("Preview (DuckDB database)")
    link.click()
    expect(x.preview.locator(".jse-badge")).to_have_text("DuckDB database · DuckDB")
    tables = x.preview.locator(".jse-table-set")
    tree = tables.locator(".jse-table-set-tree")
    expect(tree.locator(".jse-table-set-row")).to_have_text(
        ["main", "customers", "sales", "orders"]
    )
    tree.locator(".jse-table-set-leaf", has_text="orders").click()
    expect(tables.locator(".jse-query-status")).to_have_text("Rows 1–100 / 250")
    x.row("orders.parquet").click()
    expect(x.preview.locator(".jse-badge")).to_have_text("Parquet · DuckDB")
    expect(x.preview.locator(".jse-query-status")).to_have_text("Rows 1–100 / 300")
    x.preview.press("Escape")
    x.row("other.db").click()
    expect(link).to_be_disabled()
    expect(link).to_have_text("Preview")
    # The code downloads the database, as DuckDB opens only local ones.
    x.row("shop.db").click(button="right")
    x.menu_item("Python code").hover()
    x.el.locator(
        ".jse-submenu .jse-menu-item:visible", has_text="Open the database (DuckDB)"
    ).click()
    dialog = x.el.locator(".jse-dialog:visible")
    expect(dialog).to_contain_text(
        "fsspec.open_local('simplecache::memory:///duck/shop.db')"
    )
    dialog.press("Escape")


@lab_check
def python_callbacks(lab: Lab, page: Page) -> None:
    x = Explorer(lab, page, CALLBACKS)
    selected, rows = page.locator(".smoke-selected"), page.locator(".smoke-rows")
    expect(x.preview).to_contain_text("Click a file to preview it")
    x.go("curated")
    x.row("orders.parquet").click()  # the open panel previews it
    expect(selected).to_have_text("orders.parquet")
    expect(x.preview.locator(".jse-query-status")).to_have_text("Rows 1–100 / 2,400")
    expect(rows).to_have_text("2400")
    header = x.preview.locator(
        "th", has=page.locator(".jse-query-name", has_text="channel")
    ).first
    header.locator(".jse-query-filter").click()
    dialog = x.el.locator(".jse-confirm:visible")
    dialog.locator("select").first.select_option(label="Contains")
    dialog.locator("input[type=text], input:not([type])").first.fill("wholesale")
    dialog.get_by_role("button", name="Apply").click()
    expect(rows).to_have_text("341")
    x.preview.press("Escape")
    expect(x.preview).to_be_hidden()
    expect(rows).to_have_text("none")
    x.row("customers").dblclick()
    expect(selected).to_have_text("-")


def open_launcher_tab(lab: Lab, page: Page) -> Locator:
    """A new launcher tab, once its explorer shows the lake: its explorer."""
    page.goto(lab.url())
    page.locator(".jp-LauncherCard", has_text="Storage Explorer").first.click()
    return launcher_explorer(page)


def launcher_explorer(page: Page, panel: str = ".jse-launcher-panel") -> Locator:
    tab = page.locator(f"{panel} .jse-browser")
    expect(tab.locator(".jse-tree .jse-node").first).to_be_visible(timeout=90_000)
    return tab


def tab_go(page: Page, tab: Locator, storage: str, folder: str) -> None:
    """Show ``folder`` of ``storage`` in a launcher tab's explorer."""
    tab.locator(".jse-fs-select").select_option(storage)
    tab.locator(".jse-tree .jse-node").filter(
        has=page.get_by_text(folder, exact=True)
    ).first.click()
    expect(tab.locator(".jse-crumb").last).to_have_text(folder)


@lab_check
def launcher_tab(lab: Lab, page: Page) -> None:
    tab = open_launcher_tab(lab, page)
    expect(tab.locator(".jse-tree .jse-node").first).to_contain_text("sales-lake")
    expect(tab.locator(".jse-fs-select")).to_be_visible()


@lab_check
def launcher_tab_paste_folder(lab: Lab, page: Page) -> None:
    # A folder of the lake, pasted into Scratch's exports in a launcher tab:
    # the job ends, and the folder shows without a refresh.
    x = Explorer.__new__(Explorer)
    x.lab, x.page = lab, page
    x.el = open_launcher_tab(lab, page)  # on the lake's top folder
    x.el.locator(".jse-unsafe").click()
    x.menu(x.row("curated"), "Copy")
    expect(x.status).to_contain_text("Copied curated")
    tab_go(page, x.el, "Scratch", "exports")
    x.el.locator(".jse-unsafe").click()
    x.list_menu("Paste curated")
    x.button("Paste").click()
    expect(x.row("curated")).to_be_visible()
    expect(x.el.locator(".jse-job")).to_have_count(0)
    expect(x.status).to_contain_text("Pasted curated")


@lab_check
def launcher_settings(lab: Lab, page: Page) -> None:
    # The settings menu's "Edit configuration" opens the user's launcher.py in
    # JupyterLab's editor, created from the template if missing (once the user
    # agrees); saved, it applies to new tabs.
    path = lab.folder / "config" / "storage-explorer" / "launcher.py"
    with lab.launcher_settings(_lab.LAUNCHER_PY):
        tab = open_launcher_tab(lab, page)
        path.unlink()  # read when the tab started
        dialog = tab.locator(".jse-dialog:visible")
        edit = tab.locator(
            ".jse-menu:not(.jse-submenu) > .jse-menu-item:visible",
            has_text="Edit configuration",
        )
        tab.locator(".jse-settings-btn").click()
        edit.click()
        expect(dialog).to_contain_text("Create your launcher settings")
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        assert not path.exists()
        tab.locator(".jse-settings-btn").click()
        edit.click()
        dialog.get_by_role("button", name="Create").click()
        editor = page.locator(".jp-FileEditor .cm-content").first
        expect(editor).to_contain_text("def filesystems():")
        expect(page.locator(".lm-TabBar-tab.jp-mod-current")).to_contain_text(
            "launcher.py"
        )
        assert "def filesystems():" in path.read_text(encoding="utf-8")
        editor.click()
        page.keyboard.press("Control+End")
        # Not typed: the editor would indent and close brackets itself.
        page.keyboard.insert_text(
            "\n\ndef parameters():\n    return {'preview_panel': 'open'}\n"
        )
        page.keyboard.press("Control+s")
        wait_for(
            lambda: "preview_panel" in path.read_text(encoding="utf-8"), "the save"
        )
        tab = open_launcher_tab(lab, page)  # the folder it opens on, as no storages
        expect(tab.locator(".jse-preview-panel")).to_contain_text(
            "Click a file to preview it"
        )


@lab_check
def launcher_settings_with_an_error(lab: Lab, page: Page) -> None:
    # The user's launcher.py has an error: the tab opens without it, says so,
    # and "Edit configuration" opens it to be fixed.
    broken = _lab.LAUNCHER_PY + "\n\ndef parameters():\n    return {'hieght': 1}\n"
    with lab.launcher_settings(broken):
        tab = open_launcher_tab(lab, page)
        warning = "Your launcher settings were left out"
        expect(page.locator(".jse-launcher-panel").first).to_contain_text(warning)
        expect(tab.locator(".jse-status")).to_contain_text("unknown parameter 'hieght'")
        tab.locator(".jse-settings-btn").click()
        tab.locator(
            ".jse-menu:not(.jse-submenu) > .jse-menu-item:visible",
            has_text="Edit configuration",
        ).click()
        editor = page.locator(".jp-FileEditor .cm-content").first
        expect(editor).to_contain_text("hieght")


@lab_check
def launcher_tab_reload(lab: Lab, page: Page) -> None:
    # The tab reopens where it was after a page reload: the storage shown, and
    # each storage's folder (index.ts saves them with the workspace).
    tab = open_launcher_tab(lab, page)
    tab_go(page, tab, "Sales lake", "pipelines")
    tab_go(page, tab, "Scratch", "exports")
    page.wait_for_timeout(3000)  # the workspace saved
    page.goto(re.sub(r"([?&])reset&?", r"\1", page.url))  # the same workspace, kept
    tab = launcher_explorer(page)
    expect(tab.locator(".jse-fs-select")).to_have_value("Scratch")
    expect(tab.locator(".jse-crumb").last).to_have_text("exports")
    tab.locator(".jse-fs-select").select_option("Sales lake")
    expect(tab.locator(".jse-crumb").last).to_have_text("pipelines")


@lab_check
def drag_between_tabs(lab: Lab, page: Page) -> None:
    # Two launcher tabs side by side, each with its own kernel: a file dragged
    # from one onto the other is pasted there by its location, which names
    # its storage. The demo storages are in each kernel's own memory, so the
    # other kernel refuses it rather than read its own memory.
    first = open_launcher_tab(lab, page)
    page.keyboard.press("Control+Shift+L")
    page.locator(".jp-LauncherCard", has_text="Storage Explorer").first.click()
    expect(page.locator(".jse-launcher-panel")).to_have_count(2, timeout=30_000)
    # Side by side: the second tab dragged to the right edge of the main area
    # (JupyterLab 4.0's tab menu has no "Split Tab").
    page.locator(
        "#jp-main-dock-panel .lm-TabBar-tab", has_text="Storage Explorer"
    ).last.hover()
    dock = page.locator("#jp-main-dock-panel").bounding_box()
    assert dock is not None
    page.mouse.down()
    page.mouse.move(
        dock["x"] + dock["width"] - 30, dock["y"] + dock["height"] / 2, steps=15
    )
    page.mouse.up()
    second = launcher_explorer(page, ".jse-launcher-panel:nth-child(n)")
    explorers = page.locator(".jse-launcher-panel .jse-browser")
    expect(explorers).to_have_count(2, timeout=90_000)
    first, second = explorers.all()
    expect(second.locator(".jse-tree .jse-node").first).to_be_visible(timeout=90_000)
    tab_go(page, second, "Scratch", "exports")
    row = (
        first.locator("tbody tr")
        .filter(has=page.get_by_text("catalog.json", exact=True))
        .first
    )
    expect(row).to_have_attribute("title", re.compile("URL: "))  # its URL known
    row.drag_to(second.locator(".jse-list"), target_position={"x": 100, "y": 150})
    dialog = second.locator(".jse-confirm:visible")
    expect(dialog).to_contain_text("Paste catalog.json?")
    dialog.get_by_role("button", name="Paste", exact=True).click()
    expect(second).to_contain_text("not reachable from this kernel")
    expect(
        second.locator("tbody tr").filter(
            has=page.get_by_text("catalog.json", exact=True)
        )
    ).to_have_count(0)
    expect(row).to_be_visible()


@lab_check
def launcher_tab_restart(lab: Lab, page: Page) -> None:
    # A kernel restart loses the explorer: a new tab replaces the tab, where it was.
    tab = open_launcher_tab(lab, page)
    tab_go(page, tab, "Sales lake", "pipelines")
    old = page.locator(".jse-launcher-panel").first.get_attribute("id")
    page.locator(".lm-MenuBar-itemLabel", has_text="Kernel").click()
    page.locator(".lm-Menu-itemLabel", has_text="Restart Kernel…").first.click()
    page.locator(".jp-Dialog-footer .jp-Dialog-button", has_text="Restart").click()
    tab = launcher_explorer(page, f'.jse-launcher-panel:not([id="{old}"])')
    expect(tab.locator(".jse-crumb").last).to_have_text("pipelines")
    expect(page.locator(".jse-launcher-panel")).to_have_count(1)


def open_side_panel(page: Page, *, click: bool = True) -> Locator:
    """The side panel, opened from its side bar icon (else, as restored after
    a reload), once its explorer lists the lake: its explorer."""
    panel = page.locator(".jse-side-panel")
    if click:
        page.locator(".jp-SideBar .lm-TabBar-tab[title='Storage Explorer']").click()
    explorer = panel.locator(".jse-browser")
    expect(explorer.locator(".jse-list tbody tr").first).to_be_visible(timeout=90_000)
    return explorer


@lab_check
def side_panel(lab: Lab, page: Page) -> None:
    # The narrow explorer in the left side bar, of a kernel of its own: no
    # tree, no preview panel (items open in new tabs); the storage chooser in
    # the toolbar, Unsafe mode in the settings menu, Up and the path below;
    # the engine in the status bar.
    page.goto(lab.url())
    side = open_side_panel(page)
    expect(side).to_have_class(re.compile(r"\bjse-sidebar\b"))
    expect(side.locator(".jse-tree-pane")).to_be_hidden()
    expect(side.locator(".jse-tree-btn")).to_be_hidden()
    view = side.locator(".jse-status-bar .jse-preview-btn")  # View, without the panel
    expect(view).to_have_text("View")
    expect(view).to_be_disabled()
    expect(side.locator(".jse-unsafe")).to_have_count(0)
    expect(side.locator(".jse-engine-btn")).to_have_text("Polars")
    expect(side.locator(".jse-toolbar .jse-fs-select")).to_be_visible()
    expect(
        side.locator(".jse-path-bar button[title='Parent directory']")
    ).to_be_visible()
    expect(side.locator(".jse-path-bar .jse-crumb").first).to_have_text("/sales-lake")
    settings = side.locator(".jse-settings-btn")
    menu = side.locator(".jse-menu:not(.jse-submenu) > .jse-menu-item:visible")
    settings.click()
    expect(menu.first).to_have_text("Unsafe mode: off")
    menu.first.click()
    expect(settings).to_have_class(re.compile(r"\bjse-unsafe-on\b"))
    settings.click()
    expect(menu.first).to_have_text("Unsafe mode: on")
    menu.first.click()
    expect(settings).not_to_have_class(re.compile(r"\bjse-unsafe-on\b"))
    row = side.locator(".jse-list tbody tr")
    # The filter, hidden until its button (left of the settings) shows it;
    # hidden again, it filters nothing.
    filter_btn = side.locator(".jse-toolbar .jse-filter-btn")
    field = side.locator(".jse-list-pane .jse-filter-input")
    expect(field).to_be_hidden()
    filter_btn.click()
    expect(field).to_be_focused()
    field.press_sequentially("cur")
    expect(row).to_have_count(1)
    filter_btn.click()
    expect(field).to_be_hidden()
    expect(row.filter(has=page.get_by_text("landing", exact=True))).to_be_visible()
    row.filter(has=page.get_by_text("curated", exact=True)).dblclick()
    expect(side.locator(".jse-crumb").last).to_have_text("curated")
    row.filter(has=page.get_by_text("orders.parquet", exact=True)).click(button="right")
    expect(menu.filter(has_text="View Parquet in new tab")).to_be_visible()
    expect(menu.filter(has_text="Preview")).to_have_count(0)
    side.press("Escape")
    page.keyboard.press("Escape")
    # View, in the status bar, views the selected item in a new tab; so does a
    # double-click.
    row.filter(has=page.get_by_text("orders.parquet", exact=True)).click()
    expect(view).to_have_text("View (Parquet)")
    view.click()
    tab = page.locator(".jse-query-tab")
    expect(tab.locator(".jse-query-status")).to_have_text("Rows 1–100 / 2,400")
    row.filter(has=page.get_by_text("orders.parquet", exact=True)).dblclick()
    expect(tab).to_have_count(2)
    # The tab's stylesheets, on the page after the panel's, keep its hidden
    # buttons hidden.
    expect(side.locator(".jse-tree-btn")).to_be_hidden()
    # After a page reload, the panel is open again, with its console (not a
    # tab of the main area), where it was: the same explorer, in the same
    # kernel, its selection kept.
    expect(row.filter(has_text="orders.parquet")).to_have_class(
        re.compile(r"\bjse-selected\b")
    )
    kernels = side_panel_kernels(lab)
    page.wait_for_timeout(3000)  # the workspace saved
    page.goto(re.sub(r"([?&])reset&?", r"\1", page.url))
    side = open_side_panel(page, click=False)
    expect(side.locator(".jse-crumb").last).to_have_text("curated")
    expect(page.locator(".jse-launcher-panel")).to_have_count(1)
    expect(page.locator(".jse-side-panel .jse-launcher-panel")).to_have_count(1)
    row = side.locator(".jse-list tbody tr")
    expect(row.filter(has_text="orders.parquet")).to_have_class(
        re.compile(r"\bjse-selected\b")
    )
    assert side_panel_kernels(lab) == kernels


# --- Helpers ---


def side_panel_kernels(lab: Lab) -> list[str]:
    """The ids of the side panel's kernels, from the server's sessions."""
    url = f"{lab.base}/api/sessions?token={_lab.TOKEN}"
    with urllib.request.urlopen(url) as response:
        sessions = json.load(response)
    return [s["kernel"]["id"] for s in sessions if "side panel" in s["name"]]


def paste_from_lake(x: Explorer, name: str, folder: str | None = None) -> None:
    """Copy file ``name`` of the lake (in its top folder, or ``folder`` in
    it) into Scratch's top folder."""
    x.storage("Sales lake")
    if folder is None:
        x.el.locator(".jse-crumb", has_text="/sales-lake").click()
    else:
        x.node(folder).click()
    x.menu(x.row(name), "Copy")
    x.top("Scratch")
    x.list_menu(f"Paste {name}")
    x.button("Paste").click()
    expect(x.row(name)).to_be_visible()


def new_folder(x: Explorer, name: str) -> None:
    x.list_menu("Create a folder")
    x.el.locator(".jse-confirm:visible .jse-name-input").fill(name)
    x.button("Create").click()
    expect(x.row(name)).to_be_visible()


def wait_for(condition: Callable[[], bool], what: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"no {what} after {timeout} s")
        time.sleep(0.2)


# --- Running ---


def main(names: list[str]) -> int:
    unknown = set(names) - {*CHECKS, *LAB_CHECKS}
    if unknown:
        print(f"unknown checks: {', '.join(sorted(unknown))}")
        return 2
    chosen = [n for n in [*CHECKS, *LAB_CHECKS] if not names or n in names]
    failed = []
    with _lab.lab() as lab, lab.page(1400, 1000, scale=1) as page:
        page.set_default_timeout(20_000)
        x = None
        for name in chosen:
            start = time.monotonic()
            try:
                if name in LAB_CHECKS:
                    LAB_CHECKS[name](lab, page)
                    x = None  # the page has left the notebook
                else:
                    x = x or Explorer(lab, page)
                    CHECKS[name](x)
            except Exception as exc:
                failed.append(name)
                shot = HERE / f"smoke-{name}.png"
                page.screenshot(path=str(shot))
                print(f"FAIL {name}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
                print("".join(traceback.format_exception(exc, limit=-3)), end="")
                print(f"     screenshot: {shot.relative_to(_lab.REPO).as_posix()}")
                x = None  # the next check starts on a new notebook
            else:
                print(f"ok   {name} ({time.monotonic() - start:.1f} s)")
    print(f"\n{len(chosen) - len(failed)} of {len(chosen)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
