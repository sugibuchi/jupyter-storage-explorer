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

if TYPE_CHECKING:
    from collections.abc import Callable

    from fsspec import AbstractFileSystem


class JupyterLabFilesMixin:
    """Files opened in JupyterLab's own editors and viewers, read and saved
    through the launcher's drive ("jupyterlab_get", "jupyterlab_save").

    The launcher's tabs also open their settings file this way (the toolbar's
    settings button): it is on the kernel's disk, but usually outside what
    JupyterLab's file browser serves (``~/.jupyter`` is hidden).
    """

    def _offer_settings(
        self, path: str | os.PathLike[str], create: Callable[[], Any]
    ) -> None:
        """Show the settings button, which opens the file ``path`` in
        JupyterLab, calling ``create()`` first (it creates the file if it is
        missing). Only the launcher calls it: explorers in notebooks have no
        settings file."""
        self._settings_file = (os.fspath(path), create)
        self._settings_path = os.fspath(path)

    def _settings_open(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "settings_open": the settings file exists, so it can be opened
        in JupyterLab; {}, or {"missing": True} if it does not and "create" is
        not set (the user is asked first), or {"error"}. With "create", a
        missing file is created."""
        if self._settings_file is None:
            return {"error": "this explorer has no settings file"}
        path, create = self._settings_file
        try:
            if not os.path.exists(path):
                if not content.get("create"):
                    return {"missing": True}
                create()
        except Exception as exc:
            return {"error": error_text(exc)}
        return {}

    def _jupyterlab_file(
        self, content: dict[str, Any]
    ) -> tuple[AbstractFileSystem, str]:
        """The storage and path of a file opened in JupyterLab: by the storage's
        name, as the file may stay open there while another storage is shown;
        or with "settings", the settings file (see _offer_settings), and no
        other, whatever the path."""
        if content.get("settings"):
            if self._settings_file is None:
                raise ValueError("this explorer has no settings file")
            return LocalFileSystem(), self._settings_file[0]
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
                    f"(over {jupyterlab_files.MAX_BYTES // (1024 * 1024)} MB)"
                )
            data = self._read_bytes(path, fs)
            model = jupyterlab_files.contents_model(
                path,
                data,
                info,
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=content.get("content", True),
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
