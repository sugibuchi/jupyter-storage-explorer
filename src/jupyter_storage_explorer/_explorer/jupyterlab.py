"""StorageExplorer's files opened in JupyterLab (a mixin of the class)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fsspec.implementations.local import LocalFileSystem

from jupyter_storage_explorer._explorer import jupyterlab_files
from jupyter_storage_explorer._explorer.common import (
    error_text,
    within_top,
)
from jupyter_storage_explorer.util import format_size

if TYPE_CHECKING:
    from collections.abc import Callable

    from fsspec import AbstractFileSystem

    # A configuration file's path, or a function giving it when opened.
    _Path = str | os.PathLike[str] | Callable[[], str | os.PathLike[str]]


# The configuration files an explorer may offer in its settings menu, by key:
# the launcher's settings (its tabs only), the user's actions, and the day's
# log file (with the Logging menu), which is only read.
CONFIG_FILES = ("launcher", "actions", "log")
_READ_ONLY = frozenset({"log"})


class JupyterLabFilesMixin:
    """Files opened in JupyterLab's own editors and viewers, read and saved
    through the launcher's drive ("jupyterlab_get", "jupyterlab_save").

    The settings menu also opens configuration files this way (see
    ``CONFIG_FILES``): they are on the kernel's disk, but usually outside what
    JupyterLab's file browser serves (``~/.jupyter`` is hidden).
    """

    _config_files: dict[str, tuple[_Path, Callable[[], Any] | None]]
    _config_paths: dict[str, str]

    def _offer_config_file(
        self,
        key: str,
        path: _Path,
        create: Callable[[], Any] | None,
        shown: str | os.PathLike[str] | None = None,
    ) -> None:
        """Offer the configuration file ``key`` (of ``CONFIG_FILES``) in the
        settings menu, which opens the file ``path`` in JupyterLab, calling
        ``create()`` first (it creates the file if it is missing; None: a
        missing file is not created). ``path`` may be a function giving it
        when opened, e.g. the day's log file; ``shown`` is then what the menu
        shows of it, e.g. its folder."""
        if key not in CONFIG_FILES:
            raise ValueError(f"unknown configuration file {key!r}")
        self._config_files = {**self._config_files, key: (path, create)}
        shown = path if shown is None else shown
        self._config_paths = {**self._config_paths, key: os.fspath(shown)}  # type: ignore[arg-type]

    def _config_file(self, key: Any) -> tuple[str, Callable[[], Any] | None]:
        """The path and the function creating the configuration file ``key``,
        a key the page sent; ValueError if the explorer offers none of it."""
        if not isinstance(key, str) or key not in self._config_files:
            raise ValueError("this explorer has no such configuration file")
        path, create = self._config_files[key]
        return os.fspath(path() if callable(path) else path), create

    def _settings_open(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "settings_open": the configuration file of "file" exists, so
        it can be opened in JupyterLab; {"name": its name}, or {"missing": True} if it does
        not and "create" is not set (the user is asked first, unless it is
        never created), or {"error"}. With "create", a missing file is
        created."""
        try:
            path, create = self._config_file(content.get("file"))
        except ValueError as exc:
            return {"error": str(exc)}
        try:
            if not os.path.exists(path):
                if not content.get("create") or create is None:
                    return {"missing": True}
                create()
        except Exception as exc:
            return {"error": error_text(exc)}
        return {"name": os.path.basename(path)}

    def _jupyterlab_file(
        self, content: dict[str, Any]
    ) -> tuple[AbstractFileSystem, str]:
        """The storage and path of a file opened in JupyterLab: by the storage's
        name, as the file may stay open there while another storage is shown;
        or with "settings", the configuration file of that key (see
        _offer_config_file), and no other, whatever the path."""
        if content.get("settings"):
            return LocalFileSystem(), self._config_file(content["settings"])[0]
        storage = self._filesystems.get(content.get("filesystem"))
        path = content.get("path")
        if (
            storage is None
            or not isinstance(path, str)
            or not within_top(path, storage.root)
        ):
            raise ValueError("not a file of this explorer's storages")
        return storage.fs, path

    def _jupyterlab_get(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "jupyterlab_get": {"model": the file's contents model} (see
        jupyterlab_files.contents_model), or {"error"}."""
        try:
            fs, path = self._jupyterlab_file(content)
            info = self._info(path, fs)
            if info.get("type") == "directory":
                raise ValueError("folders cannot be opened in JupyterLab")
            size = info.get("size")
            if size is not None and size > jupyterlab_files.MAX_BYTES:
                raise ValueError(
                    f"too large to open in JupyterLab "
                    f"(over {format_size(jupyterlab_files.MAX_BYTES)})"
                )
            data = self._read_bytes(path, fs)
            model = jupyterlab_files.contents_model(
                path,
                data,
                info,
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=content.get("content", True),
                writable=content.get("settings") not in _READ_ONLY,
            )
        except Exception as exc:
            return {"error": error_text(exc)}
        return {"model": model}

    def _jupyterlab_save(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "jupyterlab_save": write the content JupyterLab saves to the
        file; {"model": its contents model, without content} or {"error"}.

        JupyterLab itself checks, with the hash, that the file has not been
        changed elsewhere since it was opened, before saving.
        """
        try:
            if content.get("settings") in _READ_ONLY:
                raise ValueError("this file is only read: it cannot be saved")
            fs, path = self._jupyterlab_file(content)
            current = self._read_bytes(path, fs) if self._exists(path, fs) else None
            data = jupyterlab_files.saved_bytes(
                content.get("content"), content.get("format"), current
            )
            self._write_bytes(path, data, fs)
            model = jupyterlab_files.contents_model(
                path,
                data,
                self._info(path, fs),
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=False,
            )
        except Exception as exc:
            return {"error": error_text(exc)}
        if (
            not content.get("settings")
            and content.get("filesystem") == self._filesystem
        ):
            self._update_entry(path)
            if self._preview.get("path") == path:
                # As it was previewed: the same format and engine.
                self._open_preview(
                    path, self._preview.get("format"), self._preview.get("engine", ...)
                )
        return {"model": model}
