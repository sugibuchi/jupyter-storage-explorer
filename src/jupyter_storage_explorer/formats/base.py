"""Base classes describing how to detect, preview and load each kind of data."""

from __future__ import annotations

import abc
import datetime as dt
import decimal
import importlib
import importlib.util
import math
import types
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias

# Always installed: anywidget needs ipywidgets, which needs IPython.
from IPython import get_ipython

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from fsspec import AbstractFileSystem


@dataclass(frozen=True, kw_only=True)
class Target:
    """A file or directory selected in the browser."""

    fs: AbstractFileSystem
    path: str
    # Location to use in generated code and for libraries to read, e.g.
    # "s3://bucket/key"; set by StorageExplorer._url.
    url: str
    info: Mapping[str, Any]
    # Listing of the directory (fsspec ``ls(detail=True)`` entries); None for files.
    children: Sequence[Mapping[str, Any]] | None = None

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def name(self) -> str:
        return self.path.rstrip("/").rsplit("/", 1)[-1]

    @property
    def size(self) -> int | None:
        return self.info.get("size")

    @property
    def child_names(self) -> set[str]:
        return {c["name"].rstrip("/").rsplit("/", 1)[-1] for c in self.children or ()}

    def child_path(self, name: str) -> str:
        return f"{self.path.rstrip('/')}/{name}"

    def head(self, size: int) -> bytes:
        """The first ``size`` bytes of the file, without reading the rest."""
        with self.fs.open(self.path, "rb") as f:
            return f.read(size)

    def read_whole(self, limits: PreviewLimits) -> bytes:
        """The whole file, for formats that cannot be read in part."""
        if self.size is not None and self.size > limits.max_whole_file_bytes:
            limit = limits.max_whole_file_bytes // (1024 * 1024)
            raise ValueError(f"too large to preview (over {limit} MB)")
        return self.fs.cat_file(self.path)

    def head_text(self, size: int) -> tuple[str, bool]:
        """The first ``size`` bytes decoded as UTF-8, and whether the file is longer.

        When the file is longer, the text is cut after its last complete line.
        """
        data = self.head(size + 1)
        truncated = len(data) > size
        if truncated:
            data = data[:size]
            if (end := data.rfind(b"\n")) >= 0:
                data = data[: end + 1]
        return data.decode("utf-8-sig", errors="replace"), truncated


@dataclass(frozen=True, kw_only=True)
class PreviewLimits:
    max_bytes: int = 64 * 1024
    max_rows: int = 100
    # Largest file read whole, e.g. images (sent to the browser) and Excel workbooks.
    max_whole_file_bytes: int = 10 * 1024 * 1024


# --- Preview sections -------------------------------------------------------
# ``DataFormat.preview`` returns a list of these; the frontend renders each
# section according to its ``kind``.


@dataclass(frozen=True, kw_only=True)
class Preview:
    kind: ClassVar[str]
    title: str = ""
    # Shown under the section, e.g. "First 100 rows of 1,234,567".
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class TextPreview(Preview):
    kind: ClassVar[str] = "text"
    text: str
    # Hint for syntax highlighting, e.g. "python", "json", "yaml".
    language: str | None = None
    # ``text`` with syntax highlighting: HTML-escaped, with tokens in
    # <span class="..."> using Pygments' short class names (k, s, c, ...).
    html: str | None = None


@dataclass(frozen=True, kw_only=True)
class MarkdownPreview(Preview):
    """Markdown source; the frontend renders it to (sanitized) HTML."""

    kind: ClassVar[str] = "markdown"
    text: str


@dataclass(frozen=True, kw_only=True)
class TablePreview(Preview):
    kind: ClassVar[str] = "table"
    columns: list[str]
    rows: list[list[Any]]
    dtypes: list[str] | None = None


def jsonable(value: Any) -> Any:
    """A cell value the frontend can receive: dates, decimals, numpy scalars etc. become JSON types."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if callable(getattr(value, "tolist", None)):  # numpy scalar or array
        return jsonable(value.tolist())
    return str(value)


@dataclass(frozen=True, kw_only=True)
class TreePreview(Preview):
    """Collapsible view of JSON-like data."""

    kind: ClassVar[str] = "tree"
    value: Any


@dataclass(frozen=True, kw_only=True)
class InstallPreview(Preview):
    """Shown instead of a preview when the packages to read the format are missing."""

    kind: ClassVar[str] = "install"
    format: str  # e.g. "Delta Lake table"
    # One per set of requirements that could preview it, most preferred first:
    # {"packages": "polars + deltalake", "command": "%pip install -q polars\n..."}.
    options: list[dict[str, str]]


@dataclass(frozen=True, kw_only=True)
class MediaPreview(Preview):
    """Content the browser renders natively (image, PDF, audio, video), chosen by ``mime``.

    Exactly one of ``data`` (bytes sent to the browser) or ``src`` (e.g. a
    signed URL the browser fetches itself) is set.
    """

    kind: ClassVar[str] = "media"
    mime: str
    data: bytes | None = None
    src: str | None = None


# --- Loading in a notebook --------------------------------------------------


class Requirement:
    """A package needed to load the data.

    Subclasses declare ``package``, ``import_name`` and ``preferred_names``.
    """

    package: ClassVar[str]  # pip name, e.g. "scikit-learn"
    # Top-level module the package provides, e.g. "sklearn". Not dotted:
    # finding "a.b" imports "a".
    import_name: ClassVar[str]
    # Names the package is usually imported as, most preferred first,
    # e.g. ("pl", "polars") for Polars. Empty for packages that are only
    # installed, never imported, because another package uses them (e.g.
    # deltalake for polars).
    preferred_names: ClassVar[tuple[str, ...]] = ()

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

    @property
    def install_command(self) -> str:
        """Notebook line that installs the package into the running kernel.

        Override for extras, version pins, or packages not on PyPI.
        """
        return f"%pip install -q {self.package}"

    @property
    def import_command(self) -> str | None:
        """Line that imports the package under the most preferred name, e.g. ``import polars as pl``.

        None for packages that are never imported. Override when the preferred
        name refers to a submodule (``import matplotlib.pyplot as plt``).
        """
        if not self.preferred_names:
            return None
        name = self.preferred_names[0]
        return (
            f"import {self.import_name}"
            if name == self.import_name
            else f"import {self.import_name} as {name}"
        )

    @property
    def setup_code(self) -> str:
        """The install and import lines still needed in the notebook, possibly none.

        The install line is left out if the package is installed, and the
        import line if it is already imported (or never imported).
        """
        lines = []
        if not self.is_installed():
            lines.append(self.install_command)
        if self.import_command and self.get_module_name() is None:
            lines.append(self.import_command)
        return "\n".join(lines)

    def get_module_name(self, namespace: Mapping[str, Any] | None = None) -> str | None:
        """The name the package can be used as in the notebook, or None if not imported.

        Returns the first of ``preferred_names`` bound to this package or one
        of its submodules; names bound to anything else (e.g. a user's own
        ``pl`` variable) are skipped. ``namespace`` defaults to the notebook's
        variables.
        """
        if namespace is None:
            namespace = _user_namespace()
        for name in self.preferred_names:
            obj = namespace.get(name)
            if isinstance(obj, types.ModuleType) and (
                obj.__name__ == self.import_name
                or obj.__name__.startswith(self.import_name + ".")
            ):
                return name
        return None

    def code_name(self, namespace: Mapping[str, Any] | None = None) -> str:
        """The name generated code should use: the one already imported, else the most preferred."""
        return self.get_module_name(namespace) or self.preferred_names[0]


def _user_namespace() -> Mapping[str, Any]:
    """The notebook's variables, or an empty mapping outside IPython."""
    shell = get_ipython()
    return shell.user_ns if shell is not None else {}


Requirements: TypeAlias = tuple[type[Requirement], ...]


@dataclass(frozen=True, kw_only=True)
class Recipe:
    """One way to load the data in a notebook, e.g. with polars or with pandas."""

    library: str  # label shown to the user, e.g. "polars"
    # %pip lines for the packages not installed yet; empty when all are installed.
    install: str
    code: str  # import lines still needed, then the loading code


def format_args(*args: Any, **kwargs: Any) -> str:
    """Python source for call arguments; keyword arguments that are None are left out.

    >>> format_args("data.csv", sep=";", storage_options=None)
    "'data.csv', sep=';'"
    """
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in kwargs.items() if v is not None]
    return ", ".join(parts)


# --- Formats ----------------------------------------------------------------


class DataFormat(abc.ABC):
    """How to recognise, preview and load one kind of file or directory.

    File formats usually only set ``extensions``. Directory formats (Delta
    Lake tables, Spark output, Hive-partitioned datasets, ...) override
    ``matches`` and inspect ``target.children``.
    """

    name: ClassVar[str]  # shown to the user, e.g. "Delta Lake table"
    # When several formats match (a Delta table is also a directory of Parquet
    # files), the one with the highest priority wins.
    priority: ClassVar[int] = 0
    extensions: ClassVar[tuple[str, ...]] = ()  # lower case, e.g. (".parquet",)
    # Sets of packages that can read this format, most preferred first,
    # e.g. ((Polars, DeltaLake), (Pandas,)). Each set yields one recipe.
    preferred_requirements: ClassVar[tuple[Requirements, ...]] = ()
    # Packages needed to query the data interactively (the data browser,
    # "Query data"), e.g. (Polars, DeltaLake). Empty: the format cannot be queried.
    query_requirements: ClassVar[Requirements] = ()

    def matches(self, target: Target) -> bool:
        """Whether ``target`` is in this format. Must be cheap: called on every click."""
        return not target.is_dir and target.name.lower().endswith(self.extensions)

    @abc.abstractmethod
    def preview(self, target: Target, limits: PreviewLimits) -> list[Preview]:
        """Sections to show in the preview pane.

        Implementations typically pick a library with ``installed_requirements``
        and return ``install_hint()`` when none is installed.
        """

    def can_query(self) -> bool:
        """Whether the data browser can query this format: its packages are installed."""
        return bool(self.query_requirements) and all(
            r().is_installed() for r in self.query_requirements
        )

    def scan(self, url: str) -> Any:
        """A polars LazyFrame over the data at ``url``, for the data browser.

        ``url`` is a location polars reads itself: a local path or a cloud URL
        (e.g. "s3://bucket/key"), with credentials from the environment. Only
        called when ``can_query()``. Should read lazily where the format
        allows, as the browser only fetches the rows it shows.
        """
        raise NotImplementedError(f"{self.name} cannot be queried")

    def installed_requirements(self) -> Requirements | None:
        """The first of ``preferred_requirements`` whose packages are all installed."""
        for requirements in self.preferred_requirements:
            if all(r().is_installed() for r in requirements):
                return requirements
        return None

    def install_hint(self) -> list[Preview]:
        """Preview telling the user what to install to see this format, with the commands."""
        options = []
        for requirements in self.preferred_requirements:
            missing = [r() for r in requirements if not r().is_installed()]
            options.append(
                {
                    "packages": " + ".join(r.package for r in missing),
                    "command": "\n".join(r.install_command for r in missing),
                }
            )
        return [InstallPreview(format=self.name, options=options)]

    @abc.abstractmethod
    def load_code(
        self,
        target: Target,
        requirements: Requirements,
        storage_options: Mapping[str, Any],
    ) -> str:
        """Code that loads ``target`` with one set of ``preferred_requirements``.

        Refer to packages by ``Requirement.code_name()``; their install and
        import lines are added by ``recipes``. ``storage_options`` are the
        browser's fsspec options with secrets already removed. Libraries that
        do not use fsspec (e.g. delta-rs via polars) may need them translated
        to their own option names. Build calls with ``format_args``.
        """

    def recipes(
        self, target: Target, storage_options: Mapping[str, Any]
    ) -> list[Recipe]:
        """Ways to load ``target`` in a notebook, one per set of ``preferred_requirements``."""
        recipes = []
        for requirements in self.preferred_requirements:
            instances = [r() for r in requirements]
            install = [r.install_command for r in instances if not r.is_installed()]
            imports = [
                r.import_command
                for r in instances
                if r.import_command and r.get_module_name() is None
            ]
            code = self.load_code(target, requirements, storage_options)
            recipes.append(
                Recipe(
                    library=requirements[0].package,
                    install="\n".join(install),
                    code="\n".join([*imports, "", code]).strip(),
                )
            )
        return recipes


def matching_formats(target: Target, formats: Iterable[DataFormat]) -> list[DataFormat]:
    """All formats that match ``target``, highest priority first (ties keep their order)."""
    return sorted((f for f in formats if f.matches(target)), key=lambda f: -f.priority)


def detect(target: Target, formats: Iterable[DataFormat]) -> DataFormat | None:
    """The highest-priority format that matches ``target``, if any.

    On a tie, the format listed first wins.
    """
    best = None
    for fmt in formats:
        if not fmt.matches(target):
            continue
        if best is None or fmt.priority > best.priority:
            best = fmt
    return best
