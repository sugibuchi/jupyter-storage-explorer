"""The predefined packages supports use (``PythonPackage`` subclasses, see
package.py): the libraries several engines' supports may need (to read a
format, or the item's bytes), and the core's own (Pillow, for images). An
engine's own packages, and libraries only it uses (e.g. delta-spark for
Spark, fastexcel for polars), are its plugin's, with its ``Engine``."""

from __future__ import annotations

from jupyter_storage_explorer.formats.package import PythonPackage


class Fsspec(PythonPackage):
    package = "fsspec"
    import_name = "fsspec"


class Pillow(PythonPackage):
    package = "pillow"
    import_name = "PIL"


# Optional dependencies of the engines: installed, never imported by snippets.


class PyArrow(PythonPackage):
    """Parquet engine for pandas."""

    package = "pyarrow"
    import_name = "pyarrow"


class DeltaLake(PythonPackage):
    """Delta Lake reader used by ``pl.read_delta``."""

    package = "deltalake"
    import_name = "deltalake"


class Openpyxl(PythonPackage):
    """Excel engine for pandas (and one of polars')."""

    package = "openpyxl"
    import_name = "openpyxl"
