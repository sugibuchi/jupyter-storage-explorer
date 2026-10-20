"""The data browser, as ``DataExplorer`` and the previews of
``StorageExplorer`` show it: filters, sort order and hidden columns over a
dataframe.

The data can be any dataframe narwhals supports, lazy (polars LazyFrame,
DuckDB, Spark, ...) or eager (pandas, polars, PyArrow, ...); queries are
narwhals expressions, run by the data's own library. So some details follow
that library, e.g. the syntax of regular expressions.

- filters.py: the settings checked against the data's columns, and the
  expressions applying them.
- settings.py: ``QuerySettings``, written by users, and ``QueryState``, what
  ``ExplorerStates`` (_explorer/states.py) remembers of a dataset.
- data_query.py: ``DataQuery``, one dataset open in the data browser, and
  ``fetch_rows``.

Settings are plain JSON-like dicts, shared with the frontend and remembered
per dataset, with the mode::

    {
        "filters": {
            "price": {"op": "range", "min": "10", "max": ""},  # price >= 10
            "name": {"op": "contains", "value": "tea", "case_sensitive": False},
            "comment": {"op": "not_null"},
        },
        "sort": {"column": "date", "descending": True},  # or None
        "hidden": ["comment"],
        "widths": {"name": 180},  # px; empty: automatic widths
    }
"""
