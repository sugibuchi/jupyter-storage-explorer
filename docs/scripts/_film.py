"""Animated GIFs of a page: ``Film`` puts them together from screenshots taken
after each step, each shown for as long as the script says, so their pace does
not depend on how fast the kernel answers. Headless browsers draw no mouse
pointer: ``POINTER``, added to the page before it loads, draws one that
follows the mouse and shows clicks.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

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
  // What is dragged: screenshots do not show the browser's drag image, so the
  // name of the table row dragged (its first cell) follows the pointer.
  const label = document.createElement("div");
  Object.assign(label.style, {position: "fixed", zIndex: 2147483646, pointerEvents: "none", marginLeft: "18px",
    marginTop: "14px", padding: "2px 8px", borderRadius: "4px", background: "rgba(25, 118, 210, 0.9)",
    color: "white", font: "12px sans-serif", whiteSpace: "nowrap", display: "none"});
  document.body.append(ring, label, pointer);
  const follow = e => {
    pointer.style.left = ring.style.left = label.style.left = e.clientX + "px";
    pointer.style.top = ring.style.top = label.style.top = e.clientY + "px";
  };
  addEventListener("dragstart", e => {
    const cell = e.target.closest?.("tr")?.cells?.[0];
    label.textContent = cell ? cell.textContent.trim() : "";
    label.style.display = label.textContent ? "block" : "none";
  }, true);
  const dropped = () => { label.style.display = "none"; };
  addEventListener("dragend", dropped, true);
  addEventListener("drop", dropped, true);
  // While dragging, the browser sends dragover events instead of mousemove.
  addEventListener("mousemove", follow, true);
  addEventListener("dragover", follow, true);
  addEventListener("mousedown", () => { ring.style.display = "block"; }, true);
  const release = () => setTimeout(() => { ring.style.display = "none"; }, 150);
  addEventListener("mouseup", release, true);
  addEventListener("dragend", release, true);
  addEventListener("drop", release, true);
});
"""


class Film:
    """Frames of a page and how long each is shown."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[tuple[bytes, int]] = []
        size = page.viewport_size
        assert size is not None
        self.width, self.height = size["width"], size["height"]
        self.x, self.y = self.width / 2, self.height / 2
        page.mouse.move(self.x, self.y)

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

    def type(self, text: str, chunk: int = 1, ms: int = 90) -> None:
        """Type ``text`` where the focus is, ``chunk`` characters a frame."""
        for i in range(0, len(text), chunk):
            self.page.keyboard.type(text[i : i + chunk])
            self.page.wait_for_timeout(60)
            self.snap(ms)

    def save(self, path: str) -> None:
        images = [Image.open(io.BytesIO(png)).convert("RGB") for png, _ in self.frames]
        # One palette for all frames, so colours do not flicker between them:
        # from a strip of frames across the film.
        sample = images[:: max(1, len(images) // 12)]
        strip = Image.new("RGB", (self.width, self.height * len(sample)))
        for i, image in enumerate(sample):
            strip.paste(image, (0, self.height * i))
        palette = strip.quantize(255, method=Image.Quantize.MEDIANCUT)
        frames = [
            image.quantize(palette=palette, dither=Image.Dither.NONE)
            for image in images
        ]
        frames[0].save(
            path, save_all=True, append_images=frames[1:], loop=0,
            duration=[ms for _, ms in self.frames], optimize=True,
        )  # fmt: skip
