"""StorageExplorer's files opened in JupyterLab (a mixin of the class)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _jupyterlab_files
from jupyter_storage_explorer._explorer.common import (
    error_text,
    within_top,
)

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


class JupyterLabFilesMixin:
    """Files opened in JupyterLab's own editors and viewers, read and saved
    through the launcher's drive ("jupyterlab_get", "jupyterlab_save")."""

    def _jupyterlab_file(
        self, content: dict[str, Any]
    ) -> tuple[AbstractFileSystem, str]:
        """The storage and path of a file opened in JupyterLab: by the storage's
        name, as the file may stay open there while another storage is shown."""
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
        _jupyterlab_files.contents_model), or {"error"}."""
        try:
            fs, path = self._jupyterlab_file(content)
            info = self._info(path, fs)
            if info.get("type") == "directory":
                raise ValueError("folders cannot be opened in JupyterLab")
            size = info.get("size")
            if size is not None and size > _jupyterlab_files.MAX_BYTES:
                raise ValueError(
                    f"too large to open in JupyterLab "
                    f"(over {_jupyterlab_files.MAX_BYTES // (1024 * 1024)} MB)"
                )
            data = self._read_bytes(path, fs)
            model = _jupyterlab_files.contents_model(
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
            data = _jupyterlab_files.saved_bytes(
                content.get("content"), content.get("format"), current
            )
            self._write_bytes(path, data, fs)
            model = _jupyterlab_files.contents_model(
                path,
                data,
                self._info(path, fs),
                type_=content.get("contentType"),
                format_=content.get("format"),
                content=False,
            )
        except Exception as exc:
            return {"error": error_text(exc)}
        if content.get("filesystem") == self._filesystem:
            self._update_entry(path)
            if self._preview.get("path") == path:
                self._open_preview(path, self._preview.get("format"))
        return {"model": model}
