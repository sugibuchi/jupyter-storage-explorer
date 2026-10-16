"""File operations of ``StorageExplorer`` as jobs, without the widget: what
it plans and runs in the background, so testable on their own.

- tasks.py: ``FileTasks`` plans each operation (checks, conflicts to ask
  about) and gives the ``Task`` to run, which records what it changes.
- runner.py: ``JobRunner`` runs tasks in a worker thread, one at a time,
  reporting their progress on the kernel's main thread.
- incoming.py: files from the user's computer, received in pieces.
- properties.py: "Properties": a file's info, or the totals of a selection.
- transfer_policy.py: the rules of the directions files may be transferred in.

The operations themselves are done by ``fs_operations``.
"""
