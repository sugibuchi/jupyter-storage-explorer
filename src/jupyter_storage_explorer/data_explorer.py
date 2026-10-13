"""Data explorer widget: the data browser ("Query data") for one dataframe."""

from __future__ import annotations

from typing import Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static
from jupyter_storage_explorer.query import DataQuery, QuerySettings, normalize_settings
from jupyter_storage_explorer.states import ExplorerStates

# The key DataExplorer's settings are kept under, in its own states.
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

    Queries run on the data itself ("Live") or on its first rows read into
    memory ("In memory", queried with polars when installed), switched at the
    top right of the widget (see ``DataQuery``). ``settings`` gives the
    current filters, sort order, hidden columns and widths, and ``result()``
    the data with them applied.

    Parameters
    ----------
    data : dataframe or callable
        Any dataframe narwhals supports: lazy (polars LazyFrame, DuckDB,
        Spark, Dask, Ibis, ...) or eager (pandas, polars DataFrame, PyArrow,
        ...). Or a function returning one, called again by the reload button,
        e.g. ``lambda: pl.scan_parquet(url)`` to read a file again.
    settings : QuerySettings, optional
        The filters, sort order, hidden columns and widths to start with.
        Settings that do not fit the data (unknown columns, filters for
        another type) are left out.
    mode : {"auto", "live", "memory"}, default "auto"
        Where queries run first: "auto" is live for lazy data, unless it has
        at most ``max_live_rows`` rows (kept in memory then), and in memory
        for eager data; "live" is for lazy data only.
    max_live_rows : int, default 1000
        Data up to this size is kept in memory. Also the most rows a live
        query gives when the data's library cannot skip rows (e.g. Spark).
    max_memory_rows : int, default 100_000
        The most rows read into memory; filters and sorting then apply to
        those only.
    title : str, optional
        Shown above the table. Default: the dataframe's type, e.g.
        "LazyFrame".
    height : str, default "400px"
        Height of the table area (CSS). ``"fill"``: as tall as the container,
        e.g. a tab (not a notebook cell).

    Raises
    ------
    TypeError
        If ``data`` is not a dataframe narwhals supports, e.g. a file location
        (read it first, or browse it with ``StorageExplorer``).
    ValueError
        If ``mode`` is unknown, or "live" for eager data.

    See Also
    --------
    StorageExplorer : The file explorer, whose "Query data" is the same browser.
    QuerySettings : Settings written in code.

    Examples
    --------
    >>> DataExplorer(pl.scan_parquet("s3://bucket/sales/*.parquet"))
    >>> DataExplorer(spark.table("sales"), mode="memory")
    >>> DataExplorer(df, settings=QuerySettings(sort="date", descending=True))
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
        self._states = ExplorerStates()
        if settings is not None:
            self._states.remember_query(_KEY, settings)
        try:
            self._data = DataQuery(
                data,
                _KEY,
                self._states,
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

    def result(self) -> Any:
        """The data with the widget's filters, sort order and hidden columns applied.

        Built on the data itself, so it covers all of it, also after In memory
        mode, where the widget showed the first rows only. Filters run in the
        data's library: details such as regex syntax may differ from what In
        memory mode (polars) showed.

        Returns
        -------
        dataframe
            Of the data's own library: lazy data stays lazy (e.g. a polars
            LazyFrame or a Spark DataFrame, not yet executed); eager data
            (e.g. pandas) is computed.

        Examples
        --------
        >>> explorer = DataExplorer(pl.scan_parquet("sales/*.parquet"))
        >>> # ... filter and sort in the widget ...
        >>> explorer.result().group_by("region").agg(pl.col("amount").sum()).collect()
        """
        return self._data.result()

    @property
    def settings(self) -> QuerySettings:
        """The filters, sort order, hidden columns and widths in use.

        Returns
        -------
        QuerySettings
            A copy, as changed by the user in the widget, e.g. to open other
            data with them, or to keep them in code with ``to_json()``.
        """
        state = self._states.query(_KEY)
        remembered = state.settings.to_dict() if state is not None else None
        return QuerySettings.from_dict(
            normalize_settings(remembered, self._data.schema)
        )

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the data browser's requests, matched by their "rid"."""
        reply = self._data.handle(content)
        if reply is not None:
            self.send({"type": "reply", "rid": content["rid"], **reply})
