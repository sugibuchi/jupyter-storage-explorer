"""The predefined format supports, a module per library: polars.py,
pandas.py, pyspark.py, fsspec.py, pillow.py, and python.py for those needing
no package. Import them from ``jupyter_storage_explorer.formats``.

The modules are named after the libraries they use, but import them only
inside methods, absolutely (``import polars``), so the names never shadow the
libraries themselves."""
