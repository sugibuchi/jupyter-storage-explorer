"""What extends the explorer from outside its package, loaded when an
explorer is created, without the widget.

- plugins.py: the plugins installed (``StorageExplorerPlugin``), from their
  entry points, with their options.
- user_actions.py: the actions of the user's own files, in Jupyter's
  configuration directories.
- actions_template.py: the commented example the user's ``actions.py`` is
  created from.
"""
