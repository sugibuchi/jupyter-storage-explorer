"""docs/figs/demo.gif, in the README: Storage Explorer opened from JupyterLab's
launcher, a Delta Lake table queried in the data browser, and a CSV file
opened in JupyterLab's own viewer.

The GIF is put together from screenshots taken after each step, each shown
for as long as the script says, so its pace does not depend on how fast the
kernel answers. Headless browsers draw no mouse pointer: the page gets one of
its own, which follows the mouse and shows clicks.

uv run --group docs docs/scripts/demo_gif.py
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import _lab
from PIL import Image

if TYPE_CHECKING:
    from _lab import Lab
    from playwright.sync_api import Locator, Page

WIDTH, HEIGHT = 1200, 720

POINTER = """
addEventListener("DOMContentLoaded", () => {
  const pointer = document.createElement("div");
  pointer.id = "demo-pointer";
  pointer.innerHTML = '<svg width="22" height="26" viewBox="0 0 22 26"><path d="M2 2 L2 21 L7 16.5 L10.5 24 L14 22.5 L10.5 15 L17 15 Z" fill="black" stroke="white" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(pointer.style, {position: "fixed", left: "-40px", top: "-40px", zIndex: 2147483647,
    pointerEvents: "none", width: "22px", height: "26px", marginLeft: "-2px", marginTop: "-2px"});
  const ring = document.createElement("div");
  Object.assign(ring.style, {position: "fixed", zIndex: 2147483646, pointerEvents: "none", width: "28px",
    height: "28px", marginLeft: "-14px", marginTop: "-14px", borderRadius: "50%",
    background: "rgba(25, 118, 210, 0.35)", display: "none"});
  document.body.append(ring, pointer);
  addEventListener("mousemove", e => {
    pointer.style.left = ring.style.left = e.clientX + "px";
    pointer.style.top = ring.style.top = e.clientY + "px";
  }, true);
  addEventListener("mousedown", () => { ring.style.display = "block"; }, true);
  addEventListener("mouseup", () => setTimeout(() => { ring.style.display = "none"; }, 150), true);
});
"""


class Film:
    """Frames of a page and how long each is shown."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[tuple[bytes, int]] = []
        self.x, self.y = WIDTH / 2, HEIGHT / 2

    def snap(self, ms: int) -> None:
        self.frames.append((self.page.screenshot(), ms))

    def move(
        self, locator: Locator, steps: int = 12, dx: float = 0.5, dy: float = 0.5
    ) -> None:
        """Move the pointer to a point of ``locator`` (by default its middle), smoothly."""
        b = locator.bounding_box()
        assert b is not None, locator
        x, y = b["x"] + b["width"] * dx, b["y"] + b["height"] * dy
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # ease in and out
            self.page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t)
            self.snap(30)
        self.x, self.y = x, y

    def click(self, locator: Locator, double: bool = False, **position: float) -> None:
        self.move(locator, **position)
        self.snap(150)
        self.page.mouse.down()
        self.snap(120)
        self.page.mouse.up()
        if double:
            self.page.mouse.down(click_count=2)
            self.page.mouse.up(click_count=2)

    def save(self, path: str) -> None:
        images = [Image.open(io.BytesIO(png)).convert("RGB") for png, _ in self.frames]
        # One palette for all frames, so colours do not flicker between them:
        # from a strip of frames across the film.
        sample = images[:: max(1, len(images) // 12)]
        strip = Image.new("RGB", (WIDTH, HEIGHT * len(sample)))
        for i, image in enumerate(sample):
            strip.paste(image, (0, HEIGHT * i))
        palette = strip.quantize(255, method=Image.Quantize.MEDIANCUT)
        frames = [
            image.quantize(palette=palette, dither=Image.Dither.NONE)
            for image in images
        ]
        frames[0].save(
            path, save_all=True, append_images=frames[1:], loop=0,
            duration=[ms for _, ms in self.frames], optimize=True,
        )  # fmt: skip


def make(lab: Lab) -> None:
    with lab.page(WIDTH, HEIGHT, scale=1) as page:
        page.add_init_script(POINTER)
        page.goto(lab.url())
        page.wait_for_selector(".jp-LauncherCard", timeout=60000)
        # More room for the tab: no file browser.
        page.keyboard.press("Control+b")
        page.wait_for_timeout(1500)
        film = Film(page)
        page.mouse.move(film.x, film.y)
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
        film.click(label("curated"))
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

        # A CSV file, opened in JupyterLab's own viewer.
        film.click(label("landing"))
        page.wait_for_timeout(1000)
        film.snap(500)
        film.click(label("orders"))
        page.wait_for_timeout(1000)
        film.snap(700)
        film.click(row("orders_2026-09.csv"), double=True, dx=0.2)
        page.wait_for_selector(".jp-CSVViewer, .jp-DataGrid", timeout=30000)
        page.wait_for_timeout(1500)
        film.snap(3500)

        path = _lab.FIGS / "demo.gif"
        film.save(str(path))
        print(f"{path.relative_to(_lab.REPO).as_posix()}: {WIDTH} x {HEIGHT}, {len(film.frames)} frames, "
              f"{path.stat().st_size / 1e6:.1f} MB")  # fmt: skip


if __name__ == "__main__":
    _lab.run(make)
