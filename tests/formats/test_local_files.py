"""formats/local_files.py: local copies of remote files, downloaded on
demand, valid while the remote file's modification time is the same, kept
while used."""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from jupyter_storage_explorer.formats import LocalFileCache, local_file_cache
from jupyter_storage_explorer.testing import local_item


@pytest.fixture
def cache(tmp_path):
    cache = LocalFileCache(tmp_path / "copies")
    yield cache
    cache.clear()


@pytest.fixture
def downloads(memfs, monkeypatch):
    """The paths memfs downloads, in order."""
    got = []
    get_file = memfs.get_file

    def counting(rpath, lpath, **kwargs):
        got.append(rpath)
        return get_file(rpath, lpath, **kwargs)

    monkeypatch.setattr(memfs, "get_file", counting)
    return got


def remote(make_item, data=b"v1", mtime=1.0, path="/data/a.db"):
    """A remote file (on memfs) as clicked, modified at ``mtime``."""
    ctx = make_item(path, data)
    return dataclasses.replace(ctx, info={**ctx.info, "mtime": mtime})


def until(condition, seconds=2.0):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_downloaded_on_demand_once(cache, make_item, downloads):
    item = remote(make_item)
    assert cache.status(item) == "not_cached"
    path = cache.get(item)
    assert path.read_bytes() == b"v1"
    assert path.name == "a.db"  # its name, which libraries may read
    assert cache.status(item) == "cached"
    assert cache.get(item) == path
    assert downloads == ["/data/a.db"]


def test_downloaded_again_once_changed(cache, make_item, downloads):
    first = cache.get(remote(make_item))
    # Unused, kept for a while.
    cache.release(remote(make_item).location, delay=60)
    changed = remote(make_item, b"v2", mtime=2.0)
    assert cache.status(changed) == "invalid"
    path = cache.get(changed)
    assert path.read_bytes() == b"v2"
    assert len(downloads) == 2
    assert not first.exists()  # unused: deleted at once


def test_a_copy_replaced_while_used_is_deleted_later(cache, make_item):
    first = cache.get(remote(make_item))
    changed = remote(make_item, b"v2", mtime=2.0)
    second = cache.get(changed)
    assert first.exists()  # its user may still read it
    cache.release(changed.location)
    cache.release(changed.location)
    assert not second.exists()
    assert not first.exists()


def test_kept_while_used(cache, make_item):
    item = remote(make_item)
    path = cache.get(item)
    cache.get(item)  # a second view
    cache.release(item.location)
    assert cache.status(item) == "cached"
    cache.release(item.location)
    assert cache.status(item) == "not_cached"
    assert not path.exists()


def test_deleted_after_the_delay(cache, make_item):
    item = remote(make_item)
    path = cache.get(item)
    cache.release(item.location, delay=0.05)
    assert cache.status(item) == "cached"  # viewing it again soon reuses it
    until(lambda: not path.exists())
    assert cache.status(item) == "not_cached"


def test_taken_again_within_the_delay(cache, make_item, downloads):
    item = remote(make_item)
    cache.get(item)
    cache.release(item.location, delay=0.1)
    cache.get(item)  # cancels the deletion
    time.sleep(0.2)
    assert cache.status(item) == "cached"
    assert len(downloads) == 1


def test_unknown_locations_ignored(cache, make_item):
    cache.release(remote(make_item).location)


def test_one_download_for_calls_at_once(cache, make_item, memfs, monkeypatch):
    started, release, got = threading.Event(), threading.Event(), []
    get_file = memfs.get_file

    def slow(rpath, lpath, **kwargs):
        got.append(rpath)
        started.set()
        assert release.wait(2)
        return get_file(rpath, lpath, **kwargs)

    monkeypatch.setattr(memfs, "get_file", slow)
    item = remote(make_item)
    paths = []
    threads = [threading.Thread(target=lambda: paths.append(cache.get(item)))]
    threads[0].start()
    assert started.wait(2)
    threads.append(threading.Thread(target=lambda: paths.append(cache.get(item))))
    threads[1].start()
    release.set()
    for thread in threads:
        thread.join(2)
    assert len(got) == 1
    assert paths[0] == paths[1]


def test_local_files_are_their_own_copies(cache, tmp_path):
    path = tmp_path / "a.db"
    path.write_bytes(b"local")
    item = local_item(path)
    assert cache.status(item) == "cached"
    assert cache.get(item) == path
    assert not (tmp_path / "copies").exists()  # nothing copied


def test_files_only(cache, make_item, memfs):
    memfs.pipe_file("/data/t/part", b"")
    with pytest.raises(ValueError, match="is a folder"):
        cache.get(make_item("/data/t"))


def test_its_own_folder_removed_when_cleared(make_item):
    cache = LocalFileCache()
    path = cache.get(remote(make_item))
    folder = path.parent.parent
    cache.clear()
    assert not folder.exists()


def test_the_kernels_cache():
    assert local_file_cache() is local_file_cache()
