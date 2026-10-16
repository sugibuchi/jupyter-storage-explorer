"""Files the browser sends in pieces ("Upload from the user's computer").

The frontend sends each file in pieces small enough for one message, each
acknowledged before the next. ``IncomingFiles`` gathers them into local
temporary files: a failed or abandoned upload never leaves a partial file in
the storage, which only receives the whole file afterwards (see
``FileTasks.upload_file``).
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


@dataclasses.dataclass
class Incoming:
    """A file being received: its pieces so far in ``path`` (``size`` bytes),
    to be copied to ``target`` on ``fs`` (kept, as the user may switch to
    another filesystem meanwhile)."""

    path: str
    target: str
    fs: AbstractFileSystem
    size: int = 0


class IncomingFiles:
    """Files being received, by the id the frontend gives each; at most
    ``max_bytes`` each (None for no limit)."""

    def __init__(self, max_bytes: int | None) -> None:
        self.max_bytes = max_bytes
        self._files: dict[str, Incoming] = {}

    def add(
        self, upload_id: str, piece: bytes | None, target: str, fs: AbstractFileSystem
    ) -> Incoming:
        """Append ``piece`` to file ``upload_id``, started with ``target`` and
        ``fs`` on its first piece. Raises ValueError past ``max_bytes`` (the
        frontend checks too; this guards against a file larger than it said)."""
        incoming = self._files.get(upload_id)
        if incoming is None:
            handle, path = tempfile.mkstemp(prefix="jse-upload-")
            # Opened per piece below, so none stays open between messages.
            os.close(handle)
            incoming = self._files[upload_id] = Incoming(path, target, fs)
        if piece:
            incoming.size += len(piece)
            if self.max_bytes is not None and incoming.size > self.max_bytes:
                raise ValueError(
                    f"too large to upload (over {format_size(self.max_bytes)})"
                )
            with open(incoming.path, "ab") as f:
                f.write(piece)
        return incoming

    def pop(self, upload_id: str) -> Incoming:
        """File ``upload_id``, complete: the caller now owns its temporary file."""
        return self._files.pop(upload_id)

    def discard(self, upload_id: str) -> None:
        """Forget file ``upload_id`` and delete what was received of it."""
        incoming = self._files.pop(upload_id, None)
        if incoming is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(incoming.path)


def format_size(size: float) -> str:
    """E.g. "10 MB" or "1.5 GB", as shown to users."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:g} {unit}" if size == int(size) else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")
