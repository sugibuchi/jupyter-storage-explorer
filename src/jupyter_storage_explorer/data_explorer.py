"""Data explorer widget: the data browser ("Query data") for one dataframe."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

from jupyter_storage_explorer import _static
from jupyter_storage_explorer._query.data_query import DataQuery
from jupyter_storage_explorer._query.filters import normalize_settings
from jupyter_storage_explorer._query.settings import QuerySettings
from jupyter_storage_explorer.states import ExplorerStates

if TYPE_CHECKING:
    from collections.abc import Callable

    import narwhals as nw

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


def _query_settings(settings: Any) -> QuerySettings:
    """``DataExplorer``'s ``settings``, given in any of the forms it takes."""
    if isinstance(settings, QuerySettings):
        return settings
    if isinstance(settings, str):
        return QuerySettings.from_json(settings)
    if isinstance(settings, Mapping):
        return QuerySettings.from_dict(dict(settings))
    raise TypeError(
        f"settings must be a QuerySettings, a dict or JSON text, "
        f"not {type(settings).__name__}"
    )


class DataExplorer(anywidget.AnyWidget):
    """The data browser for one dataframe: page through it, sort, filter and
    choose columns, as "Query data" does in ``StorageExplorer``.

    Queries run on the data itself ("Live") or on its first rows read into
    memory ("In memory", queried with polars when installed), switched at the
    top right of the widget (see ``DataQuery``). ``settings`` gives the
    current filters, sort order, hidden columns and widths, ``result()`` the
    data with them applied, and ``on_change()`` calls a function when that
    result changes, e.g. to redraw a chart of it.

    Parameters
    ----------
    data : dataframe or callable
        Any dataframe narwhals supports: lazy (polars LazyFrame, DuckDB,
        Spark, Dask, Ibis, ...) or eager (pandas, polars DataFrame, PyArrow,
        ...). Or a function returning one, called again by the reload button,
        e.g. ``lambda: pl.scan_parquet(url)`` to read a file again.
    settings : QuerySettings, dict or str, optional
        The filters, sort order, hidden columns and widths to start with: a
        ``QuerySettings``, or the dict or JSON text it gives with
        ``to_dict()`` or ``to_json()``. Settings that do not fit the data
        (unknown columns, filters for another type) are left out.
    mode : {"auto", "live", "memory"}, default "auto"
        Where queries run first: "auto" is live for lazy data, unless it has
        at most ``max_live_rows`` rows (kept in memory then), and in memory
        for eager data; "live" is for lazy data only.
    max_live_rows : int, default 5000
        Data up to this size is kept in memory.
    max_memory_rows : int, default 100_000
        The most rows read into memory; filters and sorting then apply to
        those only. Also the most rows a live query gives, as libraries that
        cannot skip rows (e.g. Spark) read all rows before each page.
    fetch_rows : callable, optional
        Reads one page of a live query's result (on the data itself, not
        rows in memory), as ``fetch_rows(lf, offset, length)``, e.g. to skip
        rows in a library the default reads them all for; None to leave the
        page to the default, ``jupyter_storage_explorer.fetch_rows``, which
        has an example.
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
        (read it first, or browse it with ``StorageExplorer``), or
        ``settings`` is of another type.
    ValueError
        If ``mode`` is unknown, or "live" for eager data, or ``settings`` is
        text that is not a JSON object.

    See Also
    --------
    StorageExplorer : The file explorer, whose "Query data" is the same browser.
    QuerySettings : Settings written in code.
    fetch_rows : How pages are read by default.

    Examples
    --------
    >>> DataExplorer(pl.scan_parquet("s3://bucket/sales/*.parquet"))
    >>> DataExplorer(spark.table("sales"), mode="memory")
    >>> DataExplorer(df, settings=QuerySettings(sort="date", descending=True))
    >>> settings = '{"sort": {"column": "date", "descending": true}}'  # to_json()'s
    >>> DataExplorer(df, settings=settings)
    """

    _esm = _static.esm("data_explorer")
    _css = _static.css("data_explorer")

    # Shown above the table: the title, and the data's library (in a query
    # tab of StorageExplorer, the file's format instead).
    title = traitlets.Unicode().tag(sync=True)
    library = traitlets.Unicode().tag(sync=True)
    # The data's columns, settings and mode: {"columns", "settings", "mode"}.
    query = traitlets.Dict().tag(sync=True)
    height = traitlets.Unicode("400px").tag(sync=True)

    def __init__(
        self,
        data: Any,
        *,
        settings: QuerySettings | Mapping[str, Any] | str | None = None,
        mode: str = "auto",
        max_live_rows: int = 5000,
        max_memory_rows: int = 100_000,
        fetch_rows: Callable[[nw.LazyFrame, int, int], nw.DataFrame | None]
        | None = None,
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
        self._key = _KEY
        if settings is not None:
            self._states.remember_query(_KEY, _query_settings(settings))
        try:
            self._data = DataQuery(
                data,
                _KEY,
                self._states,
                mode=mode,
                max_live_rows=max_live_rows,
                max_memory_rows=max_memory_rows,
                fetch=fetch_rows,
            )
        except TypeError as exc:
            if "Unsupported dataframe type" not in str(exc):
                raise
            raise TypeError(
                f"DataExplorer needs a dataframe narwhals supports (pandas, polars, "
                f"PyArrow, DuckDB, Spark, ...) or a function returning one, not "
                f"{type(data).__name__}"
            ) from exc
        self._start(title, height)

    @classmethod
    def _of_query(
        cls,
        data: DataQuery,
        states: ExplorerStates,
        key: str,
        *,
        title: str,
        label: str,
        height: str,
    ) -> DataExplorer:
        """A data explorer of a query opened elsewhere: StorageExplorer's
        "Query data" in a tab of its own, whose settings stay remembered under
        ``key`` (the data's URL) in ``states``, as its previews' are. ``label``
        (the file's format, as the explorer's preview shows it) is shown
        beside the title instead of the data's library."""
        explorer = cls.__new__(cls)
        explorer._states, explorer._key, explorer._data = states, key, data
        explorer._start(title, height, label)
        return explorer

    def _start(self, title: str | None, height: str, label: str | None = None) -> None:
        """Set the widget up, once ``_states``, ``_key`` and ``_data`` are."""
        library = self._data.implementation.value
        super().__init__(
            title=title if title is not None else self._data.type_name,
            library=label or _LIBRARY_LABELS.get(library, library),
            query=self._data.opening(),
            height=height,
        )
        self._change_callbacks: list[Callable[[DataExplorer], Any]] = []
        # What result() was built from when on_change's functions last heard of it.
        self._result_basis = self._result_settings()
        self.on_msg(self._on_custom_msg)

    def result(self, all_columns: bool = False) -> Any:
        """The data with the widget's filters, sort order and hidden columns applied.

        Built on the data itself, so it covers all of it, also after In memory
        mode, where the widget showed the first rows only. Filters run in the
        data's library: details such as regex syntax may differ from what In
        memory mode (polars) showed.

        Parameters
        ----------
        all_columns : bool, default False
            Keep the columns hidden in the widget ("Select columns"): only the
            filters and the sort order are applied.

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
        >>> explorer.result(all_columns=True)  # the rows chosen, with every column
        """
        return self._data.result(all_columns=all_columns)

    @property
    def settings(self) -> QuerySettings:
        """The filters, sort order, hidden columns and widths in use.

        Returns
        -------
        QuerySettings
            A copy, as changed by the user in the widget, e.g. to open other
            data with them, or to keep them in code with ``to_json()``.
        """
        state = self._states.query(self._key)
        remembered = state.settings.to_dict() if state is not None else None
        return QuerySettings.from_dict(
            normalize_settings(remembered, self._data.schema)
        )

    def on_change(
        self, callback: Callable[[DataExplorer], Any], *, remove: bool = False
    ) -> None:
        """Call a function whenever ``result()`` changes in the widget.

        That is when the user changes a filter, the sort order or the columns
        shown, or reads the data again with the reload button; not for
        paging, column widths or switching between Live and In memory, which
        leave ``result()`` as it was. The function is called after the widget
        has its rows, in the kernel's main thread, so the widget waits for it
        before its next request: keep it quick, e.g. a chart of a small or
        aggregated result.

        Parameters
        ----------
        callback : callable
            Called with the explorer, as ``callback(explorer)``. What it prints
            or displays goes to no cell (the kernel answers the widget, not a
            cell): display into an ``ipywidgets.Output`` shown in a cell, as in
            the example. Errors are shown as tracebacks in the same place and
            do not stop the other functions.
        remove : bool, default False
            Stop calling ``callback`` instead.

        See Also
        --------
        result : The data with the widget's settings applied.

        Examples
        --------
        >>> import ipywidgets
        >>> import matplotlib.pyplot as plt
        >>> chart = ipywidgets.Output()
        >>> def redraw(explorer):
        ...     df = explorer.result().group_by("region").agg(pl.len()).collect()
        ...     with chart:
        ...         chart.clear_output(wait=True)
        ...         plt.bar(df["region"], df["len"])
        ...         plt.show()
        >>> explorer = DataExplorer(pl.scan_parquet("sales/*.parquet"))
        >>> explorer.on_change(redraw)
        >>> redraw(explorer)  # the first chart, before any change
        >>> chart  # in the cell that shows the chart
        """
        if remove:
            if callback in self._change_callbacks:
                self._change_callbacks.remove(callback)
        elif callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    def _result_settings(self) -> dict[str, Any]:
        """The settings ``result()`` depends on: not widths."""
        settings = self.settings.to_dict()
        return {key: settings[key] for key in ("filters", "sort", "hidden")}

    def _notify_change(self) -> None:
        """Call the ``on_change`` functions, each one even if another fails."""
        for callback in list(self._change_callbacks):
            try:
                callback(self)
            except Exception:
                from IPython import get_ipython  # noqa: PLC0415

                shell = get_ipython()
                if shell is None:
                    raise
                shell.showtraceback()

    def _on_custom_msg(
        self, _widget: Any, content: dict[str, Any], _buffers: Any
    ) -> None:
        """Answer the data browser's requests, matched by their "rid", then
        tell the ``on_change`` functions if ``result()`` changed: the reply
        goes first, so the widget does not wait for them to show its rows."""
        reply = self._data.handle(content)
        if reply is None:
            return
        self.send({"type": "reply", "rid": content["rid"], **reply})
        basis = self._result_settings()
        reloaded = content.get("type") == "query_reload" and "error" not in reply
        if basis != self._result_basis or reloaded:
            self._result_basis = basis
            self._notify_change()
