"""What the scripts share: a JupyterLab server of their own, and a browser on it.

The server runs in a temporary folder, with its own JupyterLab settings,
workspaces, and Jupyter config and data folders, so every run starts from the same state
(default light theme, no news prompt) and leaves the user's untouched. That
folder holds the demo data (``demo_data.write``) and the notebooks the scripts
write; kernels get ``demo_data`` on their path. Its config folder has a
``storage-explorer/launcher.py`` showing the demo storages, for launcher tabs.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import TYPE_CHECKING, Any

import demo_data
from playwright.sync_api import sync_playwright

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from playwright.sync_api import Locator, Page

SCRIPTS = pathlib.Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
FIGS = REPO / "docs" / "figs"
LAUNCHER_FIGS = REPO / "launcher" / "figs"
TOKEN = "jse-docs"

LAUNCHER_PY = """\
import demo_data


def filesystems():
    return demo_data.filesystems()


def actions():
    return demo_data.actions()


def plugin_options():
    return demo_data.PLUGIN_OPTIONS
"""

# Settings of the server's JupyterLab: no prompt about news or updates.
SETTINGS = {
    "@jupyterlab/apputils-extension/notification.jupyterlab-settings": {
        "fetchNews": "false",
        "checkForUpdates": False,
    },
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    """A JupyterLab server in a temporary folder (see the module's docstring)."""

    def __init__(self, folder: pathlib.Path) -> None:
        self.folder = folder
        self.root = folder / "root"
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self._names = itertools.count(1)
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.root.mkdir()
        demo_data.write(self.root)
        settings = self.folder / "settings"
        for name, values in SETTINGS.items():
            path = settings / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(values), encoding="utf-8")
        config = self.folder / "config"
        (config / "storage-explorer").mkdir(parents=True)
        (config / "storage-explorer" / "launcher.py").write_text(
            LAUNCHER_PY, encoding="utf-8"
        )
        env = {
            **os.environ,
            "JUPYTERLAB_SETTINGS_DIR": str(settings),
            "JUPYTERLAB_WORKSPACES_DIR": str(self.folder / "workspaces"),
            "JUPYTER_CONFIG_DIR": str(config),
            # Notebook signatures (trust) and runtime files: not the user's.
            "JUPYTER_DATA_DIR": str(self.folder / "data"),
            # The kernels' IPython profile, for kernel_startup.
            "IPYTHONDIR": str(self.folder / "ipython"),
            "PYTHONPATH": os.pathsep.join(filter(None, [str(SCRIPTS), os.environ.get("PYTHONPATH")])),
            demo_data.DATA_ENV: str(self.root),
        }  # fmt: skip
        self._process = subprocess.Popen(
            [sys.executable, "-m", "jupyterlab", "--no-browser", f"--port={self.port}",
             f"--IdentityProvider.token={TOKEN}", f"--ServerApp.root_dir={self.root}"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        deadline = time.monotonic() + 120
        while True:
            try:
                urllib.request.urlopen(
                    f"{self.base}/api/status?token={TOKEN}", timeout=2
                )
                return
            except OSError:
                if time.monotonic() > deadline or self._process.poll() is not None:
                    raise RuntimeError("JupyterLab did not start") from None
                time.sleep(0.5)

    def stop(self) -> None:
        if self._process is None:
            return
        # Shut the server down through its API, which stops its kernels too.
        with contextlib.suppress(OSError):
            request = urllib.request.Request(
                f"{self.base}/api/shutdown",
                method="POST",
                headers={"Authorization": f"token {TOKEN}"},
            )
            urllib.request.urlopen(request, timeout=10)
        try:
            self._process.wait(30)
        except subprocess.TimeoutExpired:
            self._process.kill()

    @contextlib.contextmanager
    def launcher_settings(self, source: str) -> Iterator[None]:
        """Launcher tabs opened meanwhile use ``source`` as their
        ``storage-explorer/launcher.py`` (read when a tab starts), then the
        usual one again."""
        path = self.folder / "config" / "storage-explorer" / "launcher.py"
        path.write_text(source, encoding="utf-8")
        try:
            yield
        finally:
            path.write_text(LAUNCHER_PY, encoding="utf-8")

    @contextlib.contextmanager
    def user_actions(self, name: str, source: str) -> Iterator[None]:
        """Explorers created meanwhile read ``source`` as the user's actions
        file ``storage-explorer/actions/<name>``, removed after."""
        path = self.folder / "config" / "storage-explorer" / "actions" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        try:
            yield
        finally:
            path.unlink()

    @contextlib.contextmanager
    def kernel_startup(self, source: str) -> Iterator[None]:
        """Kernels started meanwhile run ``source`` first, as an IPython
        startup file: what a picture's notebook needs without showing it."""
        path = self.folder / "ipython" / "profile_default" / "startup" / "50-docs.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        try:
            yield
        finally:
            path.unlink()

    def url(self, path: str = "") -> str:
        """``/lab/<path>`` in a new, empty workspace, so that no tab or panel
        of an earlier page is restored."""
        return f"{self.base}/lab/workspaces/docs-{next(self._names)}/{path}?reset&token={TOKEN}"

    def notebook(self, *sources: str) -> str:
        """A new notebook with these code cells; returns its path in the server."""
        name = f"demo-{next(self._names)}.ipynb"
        cells = [
            {
                "cell_type": "code",
                "metadata": {},
                "outputs": [],
                "execution_count": None,
                "source": s,
            }
            for s in sources
        ]
        kernel = {"name": "python3", "display_name": "Python 3", "language": "python"}
        doc = {
            "cells": cells,
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": kernel},
        }
        (self.root / name).write_text(json.dumps(doc), encoding="utf-8")
        return name

    def open_notebook(self, page: Page, *sources: str, first: int = 0) -> None:
        """Open a new notebook of these cells and run them, from the cell of
        index ``first``: those before it are shown, not run."""
        page.goto(self.url(f"tree/{self.notebook(*sources)}"))
        page.wait_for_selector(".jp-Notebook", timeout=60000)
        page.wait_for_timeout(3000)  # the kernel starting
        if first:
            page.locator(".jp-Notebook .jp-Cell").nth(first).locator(
                ".jp-InputPrompt"
            ).click()
        page.click("text=Run", timeout=10000)
        # The menu's item: the command palette has hidden items of the same
        # text, which JupyterLab 4.0 puts first in the page.
        label = "Run Selected Cell and All Below" if first else "Run All Cells"
        page.locator(".lm-Menu-itemLabel:visible", has_text=label).filter(
            has_not_text="Restart"
        ).first.click()

    @contextlib.contextmanager
    def page(self, width: int, height: int, scale: int = 2) -> Iterator[Page]:
        """A page in the installed Edge, ``scale`` device pixels per CSS pixel."""
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            try:
                yield browser.new_page(
                    viewport={"width": width, "height": height}, device_scale_factor=scale,
                    locale="en-US", timezone_id="UTC",
                )  # fmt: skip
            finally:
                browser.close()


@contextlib.contextmanager
def lab() -> Iterator[Lab]:
    folder = pathlib.Path(tempfile.mkdtemp(prefix="jse-docs-"))
    server = Lab(folder)
    try:
        server.start()
        yield server
    finally:
        server.stop()
        shutil.rmtree(folder, ignore_errors=True)


def run(make: Callable[[Lab], None]) -> None:
    """Run a script's ``make`` on a server of its own."""
    with lab() as server:
        make(server)


# Pictures.


def box(locator: Locator) -> tuple[float, float, float, float]:
    """The locator's left, top, right and bottom."""
    b = locator.bounding_box()
    assert b is not None, locator
    return b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]


Area = tuple[float, float, float, float]


def shot(page: Page, path: pathlib.Path, area: Area, pad: float = 6) -> None:
    """A picture of the page's ``area`` (left, top, right, bottom), with a
    margin of ``pad``."""
    x0, y0, x1, y1 = area
    clip = {
        "x": x0 - pad,
        "y": y0 - pad,
        "width": x1 - x0 + 2 * pad,
        "height": y1 - y0 + 2 * pad,
    }
    page.screenshot(path=str(path), clip=clip)
    report(path, clip["width"], clip["height"])


def report(path: pathlib.Path, width: float, height: float) -> None:
    """Print a picture's size in CSS pixels: the ``<img width>`` in the docs."""
    print(f"{path.relative_to(REPO).as_posix()}: {round(width)} x {round(height)}")


def calm(page: Page, ms: int = 600) -> None:
    """Move the mouse away (no hover effects or tooltips) and let the page settle."""
    page.mouse.move(1, 1)
    page.wait_for_timeout(ms)


def explorer_helpers(
    page: Page,
) -> tuple[
    Callable[[str], Locator], Callable[[str], Locator], Callable[[str], Locator]
]:
    """Locators of an explorer's tree nodes, list rows and menu items by text."""

    def tree(name: str) -> Locator:
        return (
            page.locator(".jse-tree .jse-node")
            .filter(has=page.get_by_text(name, exact=True))
            .first
        )

    def row(name: str) -> Locator:
        return (
            page.locator("tbody tr")
            .filter(has=page.get_by_text(name, exact=True))
            .first
        )

    def menu_item(text: str) -> Locator:
        return page.locator(
            ".jse-menu:not(.jse-submenu) .jse-menu-item:visible", has_text=text
        ).first

    return tree, row, menu_item


EXPLORER = """\
import demo_data
from jupyter_storage_explorer import StorageExplorer

StorageExplorer(
    filesystems=demo_data.filesystems(),
    actions=demo_data.actions(),
    plugin_options=demo_data.PLUGIN_OPTIONS{args},
)"""


def explorer_source(**kwargs: Any) -> str:
    """A cell showing a StorageExplorer of the demo storages."""
    return EXPLORER.format(args="".join(f", {k}={v!r}" for k, v in kwargs.items()))
