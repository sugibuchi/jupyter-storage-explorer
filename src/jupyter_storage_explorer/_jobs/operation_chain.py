"""The explorer's file operations (``OperationChain``): each operation by the
first of its ``FileSystemOperations`` objects that does it (see
filesystems/operation.py), for the jobs (``FileTasks``) and the properties
scan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.filesystems.operation import FileSystemOperations

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class OperationChain:
    """Calls an operation on the first of ``operations`` that supports it
    (does not raise ``FileSystemOperations.NotSupported``), in the order
    given: which objects there are, defaults included, is up to the caller
    (e.g. ``StorageExplorer.default_operations``)."""

    def __init__(self, operations: Sequence[FileSystemOperations]) -> None:
        if not operations:
            raise ValueError("no operations objects given")
        self.operations = list(operations)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_") or not hasattr(FileSystemOperations, name):
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            for operations in self.operations:
                try:
                    return getattr(operations, name)(*args, **kwargs)
                except FileSystemOperations.NotSupported:
                    continue
            raise FileSystemOperations.NotSupported(
                f"no operations object does {name} on this filesystem"
            )

        return call
