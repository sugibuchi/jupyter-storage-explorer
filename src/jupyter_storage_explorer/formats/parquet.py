"""Parquet files and directories of them (e.g. Spark output)."""

from __future__ import annotations

import itertools
import re
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.formats.base import (
    DataFormat,
    Preview,
    PreviewLimits,
    Requirements,
    Target,
    format_args,
    spark_url,
)
from jupyter_storage_explorer.formats.frames import (
    pandas_table,
    polars_table,
    rows_note,
)
from jupyter_storage_explorer.formats.requirements import (
    Pandas,
    Polars,
    PyArrow,
    PySpark,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Items of a directory looked at to decide whether it is a Parquet dataset.
_MAX_DETECT_ITEMS = 100
# Data files read for a directory preview: enough for the first rows.
_PREVIEW_FILES = 10


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


def _is_dataset(entries: Iterable[Mapping[str, Any]], fs: Any) -> bool:
    """Whether a directory listing is one dataset of Parquet files (e.g. Spark or Hive output).

    A quick check of the directory's own items only, at most the first
    ``_MAX_DETECT_ITEMS``; subdirectories are not opened, as data lakes can be
    arbitrarily deep. Every visible item must be a Parquet file, so an
    ordinary folder that happens to hold one does not count, and neither does
    a folder of partition directories (its innermost partitions do). The
    files must also be named alike (see ``_name_pattern``): differently named
    ones, like "orders.parquet" and "customers.parquet", are separate tables.

    Hive's extensionless file names are also used for ORC and text tables, so
    for those one file's first bytes are read to check that it is Parquet.
    """
    patterns = set()
    hive_file = None
    for entry in itertools.islice(entries, _MAX_DETECT_ITEMS):
        name = _basename(entry["name"])
        if _is_hidden(name):
            continue
        if not _is_parquet_file(entry):
            return False
        patterns.add(_name_pattern(name))
        if hive_file is None and _is_hive_file(entry):
            hive_file = entry["name"]
    if len(patterns) != 1:
        return False
    return hive_file is None or _starts_like_parquet(fs, hive_file)


def _data_files(target: Target, limit: int | None = None) -> list[str]:
    """Paths of (up to ``limit``) Parquet files directly in the directory, from its listing."""
    files = sorted(
        e["name"]
        for e in target.children or ()
        if _is_parquet_file(e) and not _is_hidden(_basename(e["name"]))
    )
    return files[:limit]


class Parquet(DataFormat):
    name = "Parquet"
    extensions = (".parquet", ".parq")
    priority = 10  # above generic directories, below table formats such as Delta Lake
    preferred_requirements = ((Polars,), (Pandas, PyArrow))
    code_only_requirements = ((PySpark,),)
    query_requirements = (Polars,)

    def matches(self, target: Target) -> bool:
        if target.is_dir:
            return _is_dataset(target.children, target.fs)
        return super().matches(target)

    def scan(self, url: str) -> Any:
        """A LazyFrame over a Parquet file, or over a directory's data files.

        For a directory, polars lists the files itself. Names starting with
        "." or "_" are skipped, as Spark writes "_SUCCESS" and ".crc"
        checksums next to the data.
        """
        return Polars().load().scan_parquet(url, hidden_file_prefix=[".", "_"])

    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        requirements = self.installed_requirements()
        if requirements is None:
            return self.install_hint()
        if Polars in requirements:
            return self.preview_with_polars(target, limits)
        return self.preview_with_pandas(target, limits)

    def preview_with_polars(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pl = Polars().load()
        lf = self.scan(target.url)
        df = lf.head(limits.max_rows).collect()
        if target.is_dir:
            note = rows_note(df.height, df.height == limits.max_rows)
        else:
            # Counting rows only reads the file's metadata.
            total = lf.select(pl.len()).collect().item()
            note = rows_note(df.height, df.height < total, total=total)
        return [polars_table(df, note=note)]

    def preview_with_pandas(
        self, target: Target, limits: PreviewLimits
    ) -> list[Preview]:
        pa_dataset = PyArrow().load("dataset")
        # pyarrow reads through the browser's fsspec filesystem, so any storage
        # works. For a directory, given its first few files: pyarrow would
        # otherwise search all subdirectories.
        source = _data_files(target, _PREVIEW_FILES) if target.is_dir else target.path
        if not source:
            raise ValueError("no Parquet files found")
        dataset = pa_dataset.dataset(source, filesystem=target.fs, format="parquet")
        df = dataset.head(limits.max_rows).to_pandas()
        if target.is_dir:
            note = rows_note(len(df), len(df) == limits.max_rows)
        else:
            total = dataset.count_rows()
            note = rows_note(len(df), len(df) < total, total=total)
        return [pandas_table(df, note=note)]

    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        if PySpark in requirements:
            # A file or a folder of them; Spark uses its own storage configuration.
            return f"df = {PySpark().code_name()}.read.parquet({format_args(spark_url(target.url))})"
        options = dict(storage_options) or None
        if Polars not in requirements:
            return f"df = {Pandas().code_name()}.read_parquet({format_args(target.url, storage_options=options)})"
        pl = Polars().code_name()
        if target.is_dir:
            # Lazy, so only the needed rows and columns are read.
            return (
                f"lf = {pl}.scan_parquet({format_args(target.url, storage_options=options)})\n"
                "df = lf.head(1000).collect()"
            )
        return f"df = {pl}.read_parquet({format_args(target.url, storage_options=options)})"
