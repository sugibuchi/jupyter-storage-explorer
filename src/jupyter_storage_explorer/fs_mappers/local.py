"""Storages of the kernel's own machine or process: the local disk, and
fsspec's memory filesystem."""

from __future__ import annotations

import functools
import socket
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper

if sys.platform == "win32":
    import winreg

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem

# This process, for memory filesystems: a pid could be another process's later.
_PROCESS = uuid.uuid4().hex


class LocalMapper(FileSystemMapper):
    """fsspec's ``LocalFileSystem``: the disk of the kernel's machine.

    Its identifier is the machine, ``{"hostname", "machine_id"}`` (the id
    the system keeps, where there is one). Best effort: containers made from
    one image may share a machine id, so the hostname, a container's own,
    is part of it; and two machines sharing a volume are still two, their
    files copied rather than moved. URLs are plain paths, which every
    library reads.
    """

    protocol = "file"
    classes = ("fsspec.implementations.local.LocalFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        return _machine()

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        return path


class MemoryMapper(FileSystemMapper):
    """fsspec's ``MemoryFileSystem``, whose files are shared by its instances
    in one process: its identifier is the process, ``{"process": ...}``, so
    files copied in another kernel are never looked for in this one's memory."""

    protocol = "memory"
    classes = ("fsspec.implementations.memory.MemoryFileSystem",)

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        return {"process": _PROCESS}


@functools.cache
def _machine() -> dict[str, Any]:
    machine = {"hostname": socket.gethostname().lower()}
    if (machine_id := _machine_id()) is not None:
        machine["machine_id"] = machine_id
    return machine


def _machine_id() -> str | None:
    """The id the system gives the machine: systemd's or D-Bus's on Linux,
    Windows's MachineGuid; None elsewhere (e.g. macOS) or if unreadable."""
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0]).lower()
        except OSError:
            return None
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            if machine_id := Path(path).read_text(encoding="ascii").strip():
                return machine_id.lower()
        except (OSError, UnicodeDecodeError):
            continue
    return None
