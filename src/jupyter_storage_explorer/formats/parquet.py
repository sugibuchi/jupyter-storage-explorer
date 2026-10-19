"""Parquet files and directories of them (e.g. Spark output), partitioned or not."""

from __future__ import annotations

import dataclasses
import itertools
import re
from typing import TYPE_CHECKING, Any

import fsspec

from jupyter_storage_explorer.formats.base import DataFormat, Target

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Items of a directory looked at to decide whether it is a Parquet dataset.
_MAX_DETECT_ITEMS = 100
# Partition columns followed down a partitioned dataset, at most.
_MAX_PARTITION_DEPTH = 5
# Partition folders listed at each level, at most: the next only when one is
# empty (e.g. a partition whose data was deleted).
_PARTITION_TRIES = 2
# Hive-style partition folders: "<column>=<value>", e.g. "year=2026".
_PARTITION = re.compile(r"([^=/]+)=([^/]*)")
# Apache Hudi tables are folders of Parquet files whose rows are versioned by
# the table's timeline: read as plain Parquet, they show stale rows.
_HUDI_FOLDER = ".hoodie"
# Datasets' layouts remembered per format, for ``query`` (by URL).
_MAX_LAYOUTS = 256


def _is_hidden(name: str) -> bool:
    # Spark and Hive skip these: _SUCCESS, _temporary/, .part-0.crc, ...
    return name.startswith(("_", "."))


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


# Hive names its data files without an extension: "000000_0", and
# "000000_0_copy_1" etc. after further loads into the same table.
_HIVE_FILE = re.compile(r"\d+_\d+(_copy_\d+)?")
_COPY_SUFFIX = re.compile(r"_copy_\d+$")
# Every Parquet file starts (and ends) with these bytes.
_PARQUET_MAGIC = b"PAR1"


def _is_hive_file(entry: Mapping[str, Any]) -> bool:
    return (
        entry["type"] != "directory"
        and _HIVE_FILE.fullmatch(_basename(entry["name"])) is not None
    )


def _is_parquet_file(entry: Mapping[str, Any]) -> bool:
    """A Parquet file by its name, or a Hive data file, which may be Parquet (see ``_is_dataset``)."""
    if entry["type"] == "directory":
        return False
    return _basename(entry["name"]).lower().endswith(
        (".parquet", ".parq")
    ) or _is_hive_file(entry)


def _starts_like_parquet(fs: Any, path: str) -> bool:
    try:
        with fs.open(path, "rb") as f:
            return f.read(len(_PARQUET_MAGIC)) == _PARQUET_MAGIC
    except Exception:
        return False


# Parts of file names that differ between the files of one dataset: random
# IDs (UUIDs), job IDs and hashes (8+ hex characters), and numbers.
_VARYING_NAME_PARTS = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|(?<![0-9a-z])[0-9a-f]{8,}(?![0-9a-z])"  # standalone hex run
    r"|[0-9]+"
)


def _name_pattern(name: str) -> str:
    """A file name with its varying parts replaced by "#".

    The files of one dataset share it, e.g. Spark's
    "part-00000-2e8a686a-d04f-4489-ad50-a834723e6591-c000.snappy.parquet" and
    "part-00001-…" both give "part-#-#-c#.snappy.parquet". Hive's "_copy_N"
    suffix is dropped, as later loads into a table add it.
    """
    return _VARYING_NAME_PARTS.sub("#", _COPY_SUFFIX.sub("", name.lower()))


@dataclasses.dataclass(frozen=True)
class ParquetLayout:
    """Where a dataset's data files are, below its directory: in partition
    folders of ``keys``, in order ("year", "month": in "year=…/month=…/"),
    or directly in it (no keys); named as ``files`` matches ("*.parquet",
    "*.parq", or "*" for other names, e.g. Hive's). ``leaf`` is a folder
    holding data files: the directory itself, or a partition found by
    ``_partitioned_layout``."""

    keys: tuple[str, ...]
    files: str
    leaf: str

    def glob(self, url: str) -> str:
        """The data files' URLs, as a glob of polars: each partition level a
        "<key>=*" folder, rather than "**", which would also read the
        directory's other folders (e.g. Spark's "_temporary")."""
        return "/".join(
            [url.rstrip("/"), *(f"{key}=*" for key in self.keys), self.files]
        )


def _files_glob(names: Iterable[str]) -> str:
    """A glob matching the data files ``names``, as tight as their extension
    allows (globs are case-sensitive on object stores)."""
    names = list(names)
    for extension in (".parquet", ".parq"):
        if all(name.endswith(extension) for name in names):
            return f"*{extension}"
    return "*"


def _dataset_files(entries: Iterable[Mapping[str, Any]], fs: Any) -> str | None:
    """The glob of a directory's data files (see ``_files_glob``) if its
    listing is one dataset of Parquet files (e.g. Spark or Hive output), else None.

    A quick check of the directory's own items only, at most the first
    ``_MAX_DETECT_ITEMS``; subdirectories are not opened. Every visible item
    must be a Parquet file, so an ordinary folder that happens to hold one
    does not count, and neither does a folder of partition directories (see
    ``_partitioned_layout``). The files must also be named alike (see
    ``_name_pattern``): differently named ones, like "orders.parquet" and
    "customers.parquet", are separate tables.

    Hive's extensionless file names are also used for ORC and text tables, so
    for those one file's first bytes are read to check that it is Parquet.
    """
    patterns, names = set(), []
    hive_file = None
    for entry in itertools.islice(entries, _MAX_DETECT_ITEMS):
        name = _basename(entry["name"])
        if _is_hidden(name):
            continue
        if not _is_parquet_file(entry):
            return None
        patterns.add(_name_pattern(name))
        names.append(name)
        if hive_file is None and _is_hive_file(entry):
            hive_file = entry["name"]
    if len(patterns) != 1:
        return None
    if hive_file is not None and not _starts_like_parquet(fs, hive_file):
        return None
    return _files_glob(names)


def _partition_folders(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[str, list[str]] | None:
    """The partition column and the paths of the partition folders, sorted,
    if every visible item of a listing (of the first ``_MAX_DETECT_ITEMS``) is
    a folder "<column>=<value>" of the same column; else None."""
    key, folders = None, []
    for entry in itertools.islice(entries, _MAX_DETECT_ITEMS):
        name = _basename(entry["name"])
        if _is_hidden(name):
            continue
        match = _PARTITION.fullmatch(name)
        if entry["type"] != "directory" or match is None:
            return None
        if key is None:
            key = match[1]
        elif match[1] != key:
            return None
        folders.append(entry["name"])
    return (key, sorted(folders)) if key is not None else None


def _partitioned_layout(
    entries: Iterable[Mapping[str, Any]], fs: Any, keys: tuple[str, ...] = ()
) -> ParquetLayout | None:
    """The layout of a Hive-style partitioned dataset of Parquet files (e.g.
    "year=2026/month=9/part-0.parquet"), given its directory's listing; None
    if it is not one. ``keys``: the partition columns above it.

    The listing must be partition folders of one column (see
    ``_partition_folders``). Their contents are checked down one branch only,
    the first partition at each level, as the others are written alike: one
    more listing per partition column, at most ``_MAX_PARTITION_DEPTH``. A
    partition with nothing in it is passed over for the next, at most
    ``_PARTITION_TRIES`` at each level. At the bottom, the data files must be
    a dataset (see ``_dataset_files``).
    """
    found = _partition_folders(entries)
    if found is None:
        return None
    key, folders = found
    if key in keys or len(keys) == _MAX_PARTITION_DEPTH:
        return None
    keys = (*keys, key)
    for folder in folders[:_PARTITION_TRIES]:
        try:
            children = [
                c
                for c in fs.ls(folder, detail=True)
                # Some backends include the folder itself in its listing.
                if c["name"].rstrip("/") != folder.rstrip("/")
            ]
        except Exception:
            continue
        if all(_is_hidden(_basename(c["name"])) for c in children):
            continue  # empty: the next partition
        if (files := _dataset_files(children, fs)) is not None:
            return ParquetLayout(keys, files, folder)
        return _partitioned_layout(children, fs, keys)
    return None


def _data_files(entries: Iterable[Mapping[str, Any]], limit: int) -> list[str]:
    """Paths of up to ``limit`` Parquet files of a listing."""
    files = sorted(
        e["name"]
        for e in entries
        if _is_parquet_file(e) and not _is_hidden(_basename(e["name"]))
    )
    return files[:limit]


class Parquet(DataFormat):
    """Parquet files, and directories of them, partitioned or not.

    ``matches`` keeps each directory's layout by URL (``layout()``), for the
    supports reading it.
    """

    name = "parquet"
    label = "Parquet"
    extensions = (".parquet", ".parq")
    file_icon = "spreadsheet"
    priority = 10  # above generic directories, below table formats such as Delta Lake

    def __init__(self) -> None:
        # Directory URL -> its layout, found by ``matches`` for the supports'
        # ``query``, which is given the URL only.
        self._layouts: dict[str, ParquetLayout] = {}

    def matches(self, target: Target) -> bool:
        """A Parquet file by its extension; a directory if it is a dataset of
        Parquet files, directly in it or in Hive-style partition folders (see
        ``_dataset_files`` and ``_partitioned_layout``), and not a Hudi table."""
        if not target.is_dir:
            return super().matches(target)
        if _HUDI_FOLDER in target.child_names:
            return False
        children = list(target.children or ())
        if (files := _dataset_files(children, target.fs)) is not None:
            layout = ParquetLayout((), files, target.path)
        elif (layout := _partitioned_layout(children, target.fs)) is None:
            return False
        if len(self._layouts) >= _MAX_LAYOUTS:
            del self._layouts[next(iter(self._layouts))]
        self._layouts[target.url.rstrip("/")] = layout
        return True

    def layout(self, url: str) -> ParquetLayout:
        """The layout of directory ``url``, as ``matches`` found it, else as
        found now (see ``_discover``); without one, its own "*.parquet" files."""
        layout = self._layouts.get(url.rstrip("/")) or self._discover(url)
        return layout or ParquetLayout((), "*.parquet", url)

    def _discover(self, url: str) -> ParquetLayout | None:
        """The layout of directory ``url``, which ``matches`` was not given
        (e.g. a URL a support's ``query`` rewrote): read with fsspec, with the
        environment's credentials. None if it cannot be read or is no dataset."""
        try:
            fs, path = fsspec.core.url_to_fs(url)
            children = fs.ls(path, detail=True)
        except Exception:
            return None
        info = {"name": path, "type": "directory"}
        target = Target(fs=fs, path=path, url=url, info=info, children=children)
        return self._layouts.get(url.rstrip("/")) if self.matches(target) else None

    def target_layout(self, target: Target) -> ParquetLayout:
        """The layout of directory ``target``, found now if ``matches`` has
        not been given it."""
        if target.url.rstrip("/") not in self._layouts:
            self.matches(target)
        return self.layout(target.url)

    def data_url(self, url: str, is_dir: bool) -> str:
        """The URL of the data files: a file's as it is, a directory's data
        files as a glob (see ``ParquetLayout.glob``), rather than the
        directory itself, which libraries would search recursively."""
        return self.layout(url).glob(url) if is_dir else url

    def first_files(self, target: Target, limit: int) -> list[str]:
        """Paths of a directory's first ``limit`` data files, in its first
        partition if it is partitioned (``target_layout(target).keys``)."""
        layout = self.target_layout(target)
        if layout.keys:
            return _data_files(target.fs.ls(layout.leaf, detail=True), limit)
        return _data_files(target.children or (), limit)
