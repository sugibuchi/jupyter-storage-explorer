"""Data explorer widget: the data browser ("Query data") for one dataset."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets
from fsspec.core import url_to_fs

from jupyter_storage_explorer import _static
from jupyter_storage_explorer._urls import default_url
from jupyter_storage_explorer.formats import (
    DEFAULT_FORMATS,
    DataFormat,
    Target,
    matching_formats,
)
from jupyter_storage_explorer.formats.requirements import Polars
from jupyter_storage_explorer.query import DataQuery, QuerySettingsStore
from jupyter_storage_explorer.query import default_store as default_query_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from jupyter_storage_explorer.formats.base import Requirement


def _missing_packages_error(
    needed_for: str, missing: Sequence[Requirement]
) -> ImportError:
    """An error saying which packages to install, with the notebook commands."""
    names = " and ".join(r.package for r in missing)
    commands = "\n".join(f"    {r.install_command}" for r in missing)
    return ImportError(
        f"{needed_for} needs {names}, not installed in this kernel. Install it "
        f"in a notebook cell, then run this again (no restart is needed):\n\n"
        f"{commands}"
    )


class DataExplorer(anywidget.AnyWidget):
    """The data browser for one dataset: page through it, sort, filter and
    choose columns, as "Query data" does in ``StorageExplorer``.

    ``url`` is the location of a Delta Lake table, a Parquet file or folder of
    Parquet files, a CSV, JSON Lines or Excel file, e.g.
    ``"s3://bucket/sales"`` or ``"data/orders.csv"``. Extra keyword arguments
    are passed to fsspec as storage options. ``format`` chooses one of the
    formats that match by name (e.g. "Parquet"); by default the best match is
    used. ``formats`` replaces the formats to choose from (default:
    ``DEFAULT_FORMATS``).

    Needs polars (plus deltalake for Delta Lake tables, fastexcel for Excel);
    if a package is missing, an ImportError says how to install it.

    Settings (filters, sort, hidden columns, widths) are remembered per
    dataset by ``query_settings``, shared with ``StorageExplorer`` (see
    there). ``height`` is the height of the table area; ``"fill"`` makes the
    widget as tall as its container (e.g. a tab, not a notebook cell).
    """

    _esm = _static.esm("data_explorer")
    _css = _static.css("data_explorer")

    # Shown above the table: the URL as given, and the format's name.
    title = traitlets.Unicode().tag(sync=True)
    format = traitlets.Unicode().tag(sync=True)
    # The data's columns and remembered settings: {"columns", "settings"}.
    query = traitlets.Dict().tag(sync=True)
    height = traitlets.Unicode("400px").tag(sync=True)

    def __init__(
        self,
        url: str,
        *,
        format: str | None = None,
        formats: Sequence[DataFormat] | None = None,
        height: str = "400px",
        query_settings: QuerySettingsStore | None = None,
        **storage_options: Any,
    ) -> None:
        # Checked first, so nothing is read without the package to show it.
        if not Polars().is_installed():
            raise _missing_packages_error("DataExplorer", [Polars()])
        self.fs, path = url_to_fs(url, **storage_options)
        fmt, target = self._open(path, format, formats)
        self._data = DataQuery(
            functools.partial(fmt.scan, target.url),
            target.url,
            query_settings or default_query_settings,
        )
        super().__init__(
            title=url, format=fmt.name, query=self._data.opening(), height=height
        )
        self.on_msg(self._on_custom_msg)

    def _open(
        self,
        path: str,
        format: str | None,
        formats: Sequence[DataFormat] | None,
    ) -> tuple[DataFormat, Target]:
        """The format to query ``path`` with, and the target to scan."""
        info = self.fs.info(path)
        children = None
        if info.get("type") == "directory":
            # Some backends include the directory itself in its own listing.
            children = [
                i
                for i in self.fs.ls(path, detail=True)
                if i["name"].rstrip("/") != path.rstrip("/")
            ]
        target = Target(
            fs=self.fs, path=path, url=self._url(path), info=info, children=children
        )
        matching = matching_formats(
            target, DEFAULT_FORMATS if formats is None else formats
        )
        if format is not None:
            matching = [f for f in matching if f.name == format]
        queryable = [f for f in matching if f.query_requirements]
        if not queryable:
            found = f" (it looks like {matching[0].name})" if matching else ""
            wanted = f"as {format}" if format is not None else "as a table"
            raise ValueError(f"{target.url} cannot be queried {wanted}{found}")
        fmt = queryable[0]
        missing = [r() for r in fmt.query_requirements if not r().is_installed()]
        if missing:
            raise _missing_packages_error(f"Querying {fmt.name}", missing)
        return fmt, target

    def _url(self, path: str) -> str:
        """Location of ``path``, used to read the data and to remember its settings.

        The same as ``StorageExplorer``'s, so settings are shared between the
        two. Override in a subclass to change it.
        """
        return default_url(self.fs, path)

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the data browser's requests, matched by their "rid"."""
        reply = self._data.handle(content)
        if reply is not None:
            self.send({"type": "reply", "rid": content["rid"], **reply})
