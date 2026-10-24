"""Helpers for tests running in an asyncio loop, as code runs in a kernel:
there, jobs and loads run in worker threads (see _jobs/loader.py)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from jupyter_storage_explorer import StorageExplorer


async def until(condition: Callable[[], object], seconds: float = 5.0) -> None:
    """Let the loop run, so that workers' results reach the main thread,
    until ``condition()`` is true; AssertionError after ``seconds``."""
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"still not true after {seconds} s")


async def listed(explorer: StorageExplorer) -> StorageExplorer:
    """``explorer`` once it shows its folder's listing: folders are listed
    in loads too, so an explorer made in a loop shows "Loading…" first."""
    await until(lambda: not explorer._listing.get("loading"))
    return explorer
