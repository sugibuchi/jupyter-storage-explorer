"""The packages a format's support needs to handle its data: the
``PythonPackage`` interface (packages.py has the predefined ones)."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import threading
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    import types

# Held while a package is probed (see PythonPackage.is_installed).
_probing = threading.Lock()


class PythonPackage:
    """A package an engine or a support needs (``Engine.requirements``,
    ``FormatSupport.additional_requirements``), given as an instance, e.g.
    ``Polars()``.

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

    def load(self, submodule: str | None = None) -> types.ModuleType:
        """Import the package, or one of its submodules (e.g. ``"dataset"`` for pyarrow.dataset)."""
        return importlib.import_module(
            f"{self.import_name}.{submodule}" if submodule else self.import_name
        )
