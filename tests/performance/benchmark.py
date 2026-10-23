"""Timings of what users wait for, on a storage with a latency per call.

    uv run tests/performance/benchmark.py              # every scenario
    uv run tests/performance/benchmark.py listing copy # some of them

Cloud storages answer each call in tens of milliseconds, which counts more
than the kernel's own work. The scenarios run on fsspec's memory filesystem
made slow: each call waits ``LATENCY``, and copies also wait by their size.
That makes the cost of round trips repeatable, without cloud accounts.
Compare runs on the same machine only: the timings are not absolute.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from contextlib import contextmanager
from typing import Any, ClassVar, Self

import polars as pl
from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper
from fsspec.implementations.memory import MemoryFileSystem

from jupyter_storage_explorer import DataExplorer, QuerySettings, StorageExplorer
from jupyter_storage_explorer.filesystems import (
    AsyncFsspecOperations,
    FsspecOperations,
    Progress,
)

LATENCY = 0.05  # seconds per call
THROUGHPUT = 50e6  # bytes per second, for copies


class SlowMemoryFileSystem(MemoryFileSystem):
    """The memory filesystem, waiting ``LATENCY`` on each call it answers
    from the storage, and counting them. It shares the memory filesystem's
    store, and maps as it does (mappers match classes through the MRO)."""

    calls: ClassVar[Counter[str]] = Counter()
    latency = LATENCY

    def _wait(self, call: str, size: int = 0) -> None:
        self.calls[call] += 1
        time.sleep(self.latency + size / THROUGHPUT)

    def ls(self, path, detail=True, **kwargs):
        self._wait("ls")
        return super().ls(path, detail=detail, **kwargs)

    def info(self, path, **kwargs):
        self._wait("info")
        return super().info(path, **kwargs)

    def cat_file(self, path, start=None, end=None, **kwargs):
        self._wait("cat_file")
        return super().cat_file(path, start=start, end=end, **kwargs)

    def _open(self, path, mode="rb", **kwargs):
        self._wait("open")
        return SlowFile(super()._open(path, mode=mode, **kwargs))

    def cp_file(self, path1, path2, **kwargs):
        # The store's size, not ``self.size``: that would be a call too.
        self._wait("cp_file", self.store[self._strip_protocol(path1)].size)
        return super().cp_file(path1, path2, **kwargs)


class SlowFile:
    """A file of the slow filesystem: reads and writes wait by their size,
    as a network transfers them. Waits in different threads overlap, as a
    download and an upload do."""

    def __init__(self, file: Any) -> None:
        self._file = file

    def read(self, size: int = -1) -> bytes:
        data = self._file.read(size)
        time.sleep(len(data) / THROUGHPUT)
        return data

    def write(self, data: bytes) -> int:
        time.sleep(len(data) / THROUGHPUT)
        return self._file.write(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._file, name)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._file.close()


class Explorer(StorageExplorer):
    """An explorer driven as the frontend does, without a frontend."""

    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        pass

    def request(self, content: dict[str, Any]) -> None:
        self._on_custom_msg(self, {"rid": 1, **content}, None)


@contextmanager
def timed(label: str):
    """Print how long the block took, and the storage calls it made."""
    SlowMemoryFileSystem.calls.clear()
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    calls = ", ".join(f"{n} {c}" for c, n in sorted(SlowMemoryFileSystem.calls.items()))
    print(f"  {label:<44} {elapsed:7.2f} s   {calls or 'no calls'}")


def fresh() -> SlowMemoryFileSystem:
    fs = SlowMemoryFileSystem()
    fs.store.clear()
    fs.pseudo_dirs.clear()
    fs.pseudo_dirs.append("")
    return fs


def write(fs: SlowMemoryFileSystem, path: str, data: bytes) -> None:
    """Write a file for a scenario, without waiting: setting up is not what
    the scenario times. A plain memory filesystem shares the slow one's
    store, and none of its waits."""
    MemoryFileSystem().pipe_file(path, data)


def listing() -> None:
    """Opening large folders: the kernel's work besides the one listing."""
    fs = fresh()
    for n in (2_000, 20_000):
        for i in range(n):
            ext = ("csv", "parquet", "json", "txt", "png")[i % 5]
            write(fs, f"/big{n}/file{i:05d}.{ext}", b"x")
    explorer = Explorer("/", fs=fs)
    for n in (2_000, 20_000):
        with timed(f"open a folder of {n:,} files"):
            explorer._current_dir = f"/big{n}"


def clicks() -> None:
    """Clicking items: selecting, the right-click menu, the preview."""
    fs = fresh()
    write(fs, "/data/a.csv", b"a,b\n1,2\n")
    for y in range(3):
        for m in range(12):
            write(fs, f"/data/ds/year={2020 + y}/month={m:02d}/part-0.parquet", b"x")
    explorer = Explorer("/data", fs=fs)
    with timed("click a file, open its menu, preview it"):
        explorer._selected = ["/data/a.csv"]
        explorer.request({"type": "menu_info", "path": "/data/a.csv"})
        explorer.request({"type": "preview", "path": "/data/a.csv", "engine": None})
    explorer._selected = []
    with timed("click a partitioned dataset, open its menu"):
        explorer._selected = ["/data/ds"]
        explorer.request({"type": "menu_info", "path": "/data/ds"})


def copy() -> None:
    """Copying a folder of mixed sizes within an asynchronous storage: 300
    small files and 10 large ones, 32 at a time."""
    fs = fresh()
    for i in range(310):
        data = b"x" * (25_000_000 if i % 31 == 0 else 1_000)
        write(fs, f"/src/f{i:03d}.bin", data)
    async_fs = AsyncFileSystemWrapper(fs)
    with timed("copy 310 files (10 of 25 MB) within a storage"):
        AsyncFsspecOperations(concurrency=32).copy(
            async_fs, "/src", async_fs, "/dst", Progress(), same=True
        )


def transfer() -> None:
    """Copying between two storages, through the kernel: a folder of mixed
    sizes between asynchronous storages, 32 at a time, and one large file
    between synchronous ones."""
    fs = fresh()
    for i in range(310):
        data = b"x" * (25_000_000 if i % 31 == 0 else 1_000)
        write(fs, f"/src/f{i:03d}.bin", data)
    write(fs, "/big/one.bin", b"x" * 200_000_000)
    # Two storages, as the explorer sees them: the copies are not ``same``.
    source, target = AsyncFileSystemWrapper(fs), AsyncFileSystemWrapper(fresh_view())
    with timed("copy 310 files (10 of 25 MB) between storages"):
        AsyncFsspecOperations(concurrency=32).copy(
            source, "/src", target, "/dst", Progress(), same=False
        )
    with timed("copy one file of 200 MB between storages"):
        FsspecOperations()._copy_file(
            fs, "/big/one.bin", fresh_view(), "/big/copy.bin", Progress()
        )


def fresh_view() -> SlowMemoryFileSystem:
    """Another instance of the slow filesystem, on the same store."""
    return SlowMemoryFileSystem(skip_instance_cache=True)


def scrolling() -> None:
    """Scrolling the data browser in memory mode, filtered and sorted: 20
    pages of a million rows."""
    df = pl.DataFrame(
        {"a": range(1_000_000), "b": [f"s{i % 1000}" for i in range(1_000_000)]}
    )
    settings = QuerySettings(filters={"a": {"op": "range", "min": 1000}}, sort="b")
    for library, data in (("polars", df), ("pandas", df.to_pandas())):
        explorer = DataExplorer(data, settings=settings, max_memory_rows=1_000_000)
        explorer.send = lambda content, buffers=None: None
        with timed(f"scroll 20 pages of 1M rows in memory, {library}"):
            for page in range(20):
                explorer._on_custom_msg(
                    explorer,
                    {
                        "type": "query_rows",
                        "rid": page,
                        "offset": page * 100,
                        "window": 100,
                        "settings": explorer._query["settings"],
                    },
                    None,
                )


SCENARIOS = {
    "listing": listing,
    "clicks": clicks,
    "copy": copy,
    "transfer": transfer,
    "scrolling": scrolling,
}


if __name__ == "__main__":
    print(
        f"Latency {LATENCY * 1000:.0f} ms per call, copies at {THROUGHPUT / 1e6:.0f} MB/s"
    )
    for name in sys.argv[1:] or SCENARIOS:
        print(f"{name}:")
        SCENARIOS[name]()
