"""Packages used by previews and the generated load snippets."""

from __future__ import annotations

from jupyter_storage_explorer.formats.base import Requirement


class Fsspec(Requirement):
    package = "fsspec"
    import_name = "fsspec"
    preferred_names = ("fsspec",)


class Polars(Requirement):
    package = "polars"
    import_name = "polars"
    preferred_names = ("pl", "polars")


class Pandas(Requirement):
    package = "pandas"
    import_name = "pandas"
    preferred_names = ("pd", "pandas")


class Pillow(Requirement):
    package = "pillow"
    import_name = "PIL"
    preferred_names = ("PIL",)

    @property
    def import_command(self) -> str:
        # ``import PIL`` alone does not load the PIL.Image submodule the code uses.
        return "import PIL.Image"


# Optional dependencies of the packages above: installed, never imported by snippets.


class PyArrow(Requirement):
    """Parquet engine for pandas."""

    package = "pyarrow"
    import_name = "pyarrow"


class DeltaLake(Requirement):
    """Delta Lake reader used by ``pl.read_delta``."""

    package = "deltalake"
    import_name = "deltalake"


class Openpyxl(Requirement):
    """Excel engine for pandas."""

    package = "openpyxl"
    import_name = "openpyxl"


class Fastexcel(Requirement):
    """Excel engine for polars."""

    package = "fastexcel"
    import_name = "fastexcel"
