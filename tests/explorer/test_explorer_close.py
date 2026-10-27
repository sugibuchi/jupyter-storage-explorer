"""Closing the explorer: its jobs cancelled, its uploads discarded."""

from __future__ import annotations

import asyncio
import os
import threading

from explorers import make
from in_a_kernel import listed, until


def piece(last: bool) -> dict[str, object]:
    return {
        "type": "upload_chunk",
        "rid": 1,
        "id": "u",
        "dest": "/data",
        "name": "c.txt",
        "last": last,
    }


def test_files_being_uploaded_are_discarded(memfs):
    memfs.pipe_file("/data/a.txt", b"a")
    explorer = make("/data", fs=memfs)
    explorer.message(piece(last=False), [b"hello"])
    [incoming] = explorer._incoming._files.values()
    explorer.close()
    assert not os.path.exists(incoming.path)
    assert "u" not in explorer._incoming


def test_a_job_ending_after_close_only_cleans_up(memfs, monkeypatch):
    """The upload's temporary file is deleted; no folder is listed again."""
    memfs.pipe_file("/data/a.txt", b"a")
    started, release = threading.Event(), threading.Event()
    put_file = memfs.put_file

    def holding(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return put_file(*args, **kwargs)

    monkeypatch.setattr(memfs, "put_file", holding)

    async def main():
        explorer = await listed(make("/data", fs=memfs))
        refreshed = []
        monkeypatch.setattr(explorer, "_refresh_dir", refreshed.append)
        explorer.message(piece(last=False), [b"hello"])
        [incoming] = explorer._incoming._files.values()
        explorer.message(piece(last=True), [b""])
        await until(started.is_set)
        explorer.close()
        release.set()
        await until(lambda: not explorer._jobs.jobs)
        return incoming, refreshed

    incoming, refreshed = asyncio.run(main())
    assert not os.path.exists(incoming.path)
    assert refreshed == []
