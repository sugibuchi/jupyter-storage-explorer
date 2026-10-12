"""Data explorer widget: the data browser ("Query data") for one dataframe."""

from __future__ import annotations

from typing import Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static
from jupyter_storage_explorer.query import (
    DataQuery,
    QuerySettings,
    QuerySettingsStore,
    normalize_settings,
)

# The key DataExplorer's settings are kept under, in its own store.
_KEY = "data"

# Names shown for libraries whose narwhals name is not the usual one.
_LIBRARY_LABELS = {
    "pyarrow": "PyArrow",
    "duckdb": "DuckDB",
    "pyspark": "Spark",
    "pyspark[connect]": "Spark Connect",
    "sqlframe": "SQLFrame",
}


class DataExplorer(anywidget.AnyWidget):
    """The data browser for one dataframe: page through it, sort, filter and
    choose columns, as "Query data" does in ``StorageExplorer``.

    ``data`` is any dataframe narwhals supports, lazy (polars LazyFrame,
    DuckDB, Spark, Dask, Ibis, ...) or eager (pandas, polars DataFrame,
    PyArrow, ...), or a function returning one, called again by the reload
    button (e.g. ``lambda: pl.scan_parquet(url)``, to read a file again).
    E.g.::

        DataExplorer(pl.scan_parquet("s3://bucket/sales/*.parquet"))
        DataExplorer(spark.table("sales"), mode="memory")
        DataExplorer(pandas_df, settings=QuerySettings(sort="date", descending=True))

    Queries run on the data itself ("live") or on its first rows read into
    memory (see ``DataQuery``), switched in the widget. ``mode`` is the mode to
    start in: "auto" (live for lazy data, unless it has at most
    ``max_live_rows`` rows), "live" (for lazy data only) or "memory".
    ``max_live_rows`` is also the most rows a live query gives when the
    data's library cannot skip rows (e.g. Spark); ``max_memory_rows`` the most
    rows read into memory.

    ``settings`` (a ``QuerySettings``) are the filters, sort order, hidden
    columns and widths to start with; ``settings`` (the property) gives those
    of the widget, as changed by the user. ``title`` is shown above the table
    (default: the dataframe's type). ``height`` is the height of the table
    area; ``"fill"`` makes the widget as tall as its container (e.g. a tab,
    not a notebook cell).
    """

    _esm = _static.esm("data_explorer")
    _css = _static.css("data_explorer")

    # Shown above the table: the title, and the data's library.
    title = traitlets.Unicode().tag(sync=True)
    library = traitlets.Unicode().tag(sync=True)
    # The data's columns, settings and mode: {"columns", "settings", "mode"}.
    query = traitlets.Dict().tag(sync=True)
    height = traitlets.Unicode("400px").tag(sync=True)

    def __init__(
        self,
        data: Any,
        *,
        settings: QuerySettings | None = None,
        mode: str = "auto",
        max_live_rows: int = 1000,
        max_memory_rows: int = 100_000,
        title: str | None = None,
        height: str = "400px",
    ) -> None:
        if isinstance(data, str):
            raise TypeError(
                "DataExplorer takes a dataframe, not a location: read it first, "
                'e.g. DataExplorer(pl.scan_parquet("...")), or browse it with '
                "StorageExplorer"
            )
        # Settings live in this explorer only: a dataframe has no location to
        # remember them by, unlike files in StorageExplorer.
        self._store = QuerySettingsStore()
        if settings is not None:
            self._store.set(_KEY, settings.to_dict())
        try:
            self._data = DataQuery(
                data,
                _KEY,
                self._store,
                mode=mode,
                max_live_rows=max_live_rows,
                max_memory_rows=max_memory_rows,
            )
        except TypeError as exc:
            if "Unsupported dataframe type" not in str(exc):
                raise
            raise TypeError(
                f"DataExplorer needs a dataframe narwhals supports (pandas, polars, "
                f"PyArrow, DuckDB, Spark, ...) or a function returning one, not "
                f"{type(data).__name__}"
            ) from exc
        library = self._data.implementation.value
        super().__init__(
            title=title if title is not None else self._data.type_name,
            library=_LIBRARY_LABELS.get(library, library),
            query=self._data.opening(),
            height=height,
        )
        self.on_msg(self._on_custom_msg)

    @property
    def settings(self) -> QuerySettings:
        """The filters, sort order, hidden columns and widths in use, e.g. to
        open other data with them."""
        settings = normalize_settings(self._store.get(_KEY), self._data.schema)
        return QuerySettings.from_dict(settings)

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the data browser's requests, matched by their "rid"."""
        reply = self._data.handle(content)
        if reply is not None:
            self.send({"type": "reply", "rid": content["rid"], **reply})
