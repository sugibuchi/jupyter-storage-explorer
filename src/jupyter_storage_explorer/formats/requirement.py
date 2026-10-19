"""The packages a format needs to preview or load its data: the
``Requirement`` interface (requirements.py has the predefined ones)."""

from __future__ import annotations

import importlib
import importlib.util
from typing import TYPE_CHECKING, ClassVar, TypeAlias

if TYPE_CHECKING:
    import types


class Requirement:
    """A package needed to preview or load the data.

    Subclasses declare ``package`` and ``import_name``.
    """

    package: ClassVar[str]  # pip name, e.g. "scikit-learn"
    # Top-level module the package provides, e.g. "sklearn". Not dotted:
    # finding "a.b" imports "a".
    import_name: ClassVar[str]

    def is_installed(self) -> bool:
        # The import system caches directory listings, so a package installed
        # with %pip in the running kernel would otherwise still look missing.
        importlib.invalidate_caches()
        return importlib.util.find_spec(self.import_name) is not None

    def load(self, submodule: str | None = None) -> types.ModuleType:
        """Import the package, or one of its submodules (e.g. ``"dataset"`` for pyarrow.dataset)."""
        return importlib.import_module(
            f"{self.import_name}.{submodule}" if submodule else self.import_name
        )


Requirements: TypeAlias = tuple[type[Requirement], ...]
