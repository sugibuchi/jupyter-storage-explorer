# DataExplorer

`DataExplorer` opens the data browser for a dataframe in your notebook: pandas, polars, PyArrow, DuckDB, Spark, and the
other libraries [narwhals](https://narwhals-dev.github.io/narwhals/) supports. It is the browser `StorageExplorer` opens
for tables ([Query data](storage-explorer.md#query-data)). For installation, see the [README](../README.md).

![DataExplorer showing a Delta Lake table in a notebook](../figs/data-explorer.png)

- [Opening data](#opening-data)
- [Using the data browser](#using-the-data-browser)
- [The result in code](#the-result-in-code)
- [Following the widget: on_change](#following-the-widget-on_change)
- [Settings in code: QuerySettings](#settings-in-code-querysettings)
- [DataExplorer options](#dataexplorer-options)

## Opening data

```python
import polars as pl
from jupyter_storage_explorer import DataExplorer, QuerySettings

DataExplorer(pl.scan_parquet("s3://my-bucket/lake/sales/*.parquet"))
DataExplorer(spark.table("sales"), mode="memory")  # read the first rows into memory
DataExplorer(orders_df, settings=QuerySettings(sort="date", descending=True))
```

Lazy data starts **Live**, eager data **In memory**. Pass a function (`lambda: pl.scan_parquet(url)`) for **⟳** to
read the data again.

## Using the data browser

- ◀ ▶ to page, click a column name to sort (again for descending, a third time to stop), its funnel to filter
  (*Null / empty*, *Range*, *Contains*, *Regex*). Active filters are listed in the toolbar: click one to edit it, × to
  remove it.
- **Select columns** to hide columns, drag a header's edge to resize (double-click for automatic widths), **Reset** to
  clear filters, **⟳** to reload.
- **Live** / **In memory** (top right): query the data itself, or read its first rows into memory once (100,000 by
  default) and query those (faster, but filters and sorting then apply to those rows only). Data of up to 1,000 rows is
  always kept in memory. Eager data, such as pandas', is always in memory, queried with polars when it is installed.

## The result in code

`explorer.result()` gives the data with the widget's filters, sort order and hidden columns applied, as a dataframe of
the same library (lazy data stays lazy), to continue your analysis in code; `result(all_columns=True)` keeps the
hidden columns. It covers all the data, also after **In memory**, where the widget shows the first rows only:

```python
explorer = DataExplorer(pl.scan_parquet("sales/*.parquet"))
# ... filter and sort in the widget ...
explorer.result().group_by("region").agg(pl.col("amount").sum()).collect()
```

## Following the widget: on_change

`explorer.on_change(function)` calls `function(explorer)` whenever `result()` changes in the widget (filters, sort
order, columns shown, ⟳), e.g. to redraw a chart; `on_change(function, remove=True)` stops it. Draw into an
`ipywidgets.Output` shown in a cell: what the function displays goes to no cell otherwise. It runs in the kernel, so the
widget waits for it; keep it quick.

```python
import ipywidgets
import matplotlib.pyplot as plt

chart = ipywidgets.Output()

def draw(explorer):
    df = explorer.result(all_columns=True).group_by("region").agg(pl.col("amount").sum()).collect()
    with chart:
        chart.clear_output(wait=True)
        plt.bar(df["region"], df["amount"])
        plt.show()

explorer.on_change(draw)
draw(explorer)
chart  # in another cell
```

## Settings in code: QuerySettings

`QuerySettings` sets the filters, sort order, hidden columns and widths to start with. To keep settings made in the
widget, print them as text and paste them into your code:

```python
explorer = DataExplorer(orders_df)
print(explorer.settings.to_json())  # after filtering and sorting in the widget

DataExplorer(orders_df, settings=QuerySettings.from_json("""
{
    "filters": {"price": {"op": "range", "min": "10", "max": ""}},
    "sort": {"column": "date", "descending": true},
    "hidden": ["comment"],
    "widths": {}
}
"""))
```

## DataExplorer options

| Option                     | Meaning                                                                                                                      |
|----------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `settings=QuerySettings()` | Filters, sort order, hidden columns and widths to start with (see above).                                                    |
| `mode="auto"`              | Where queries run first: `"auto"`, `"live"` (lazy data only) or `"memory"`; switch in the widget.                            |
| `max_live_rows=1000`       | Data up to this size is kept in memory; also the most rows a live query gives if the library cannot skip rows (e.g. Spark). |
| `max_memory_rows=100_000`  | The most rows read into memory.                                                                                              |
| `title=...`                | Shown above the table (default: the dataframe's type).                                                                       |
| `height="400px"`           | Height of the table area. `"fill"`: as tall as the container, e.g. a tab (not a notebook cell).                              |
