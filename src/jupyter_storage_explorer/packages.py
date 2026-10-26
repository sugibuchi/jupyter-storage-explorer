"""The packages engines and actions need: the ``PythonPackage`` interface,
and the predefined packages, the libraries several engines' actions may need
(to read a format, or the item's bytes) and the core's own (Pillow, for
images). An engine's own packages, and libraries only it uses (e.g.
delta-spark for Spark, fastexcel for polars), are its plugin's, with its
``Engine``."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import threading
from typing import ClassVar

__all__ = [
    "DeltaLake",
    "Fsspec",
    "Openpyxl",
    "Pillow",
    "PyArrow",
    "PythonPackage",
]

# Held while a package is probed (see PythonPackage.is_installed).
_probing = threading.Lock()


class PythonPackage:
    """A package an engine or an action needs (``Engine.requirements``, an
    action's ``requires``), given as an instance, e.g. ``Polars()``: what
    explorers check is installed before offering them, and what "Python
    code" names. Actions import the package themselves, inside their
    functions.

    Subclasses declare ``package`` and ``import_name``.
    """

    package: ClassVar[str]  # pip name, e.g. "scikit-learn"
    # The module the package provides, e.g. "sklearn": best top-level, as
    # finding "a.b" imports "a"; dotted when "a" is a namespace other packages
    # share (e.g. "databricks.connect").
    import_name: ClassVar[str]
    # Whether the module counts only when the distribution ``package`` itself
    # is installed: for a module other packages may bring a copy of, which
    # may not work as the package's does (e.g. pyspark's).
    own_distribution: ClassVar[bool] = False

    def is_installed(self) -> bool:
        # The import system caches directory listings, so a package installed
        # with %pip in the running kernel would otherwise still look missing.
        # One probe at a time: invalidating the caches while another thread
        # looks a package up can make an installed one look missing (the
        # explorer reads views in worker threads).
        with _probing:
            importlib.invalidate_caches()
            try:
                if importlib.util.find_spec(self.import_name) is None:
                    return False
            except ModuleNotFoundError:  # "a" of "a.b" missing
                return False
        if self.own_distribution:
            try:
                importlib.metadata.distribution(self.package)
            except importlib.metadata.PackageNotFoundError:
                return False
        return True


# The predefined packages.


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
