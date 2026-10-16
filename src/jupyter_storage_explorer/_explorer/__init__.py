"""The parts of ``StorageExplorer`` (storage_explorer.py): its features as
mixins of the class, one module each, what they share (common.py), and what
they use: what explorers remember, bookmarks and queries (states.py;
``DataExplorer`` keeps its settings in one too), large folders paged by
the kernel (listing.py), and the contents models of files opened in
JupyterLab (jupyterlab_files.py).

The mixins only hold methods; the state they work on (``self._fs``, the
traits, ...) is set up by the class. They are listed before
``anywidget.AnyWidget`` in its bases.
"""
