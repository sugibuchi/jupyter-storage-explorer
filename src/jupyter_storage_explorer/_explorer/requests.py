"""StorageExplorer's requests for file operations (a mixin of the class)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import (
    _paths,
    properties,
)
from jupyter_storage_explorer._explorer.common import (
    error_text,
    explorers,
)
from jupyter_storage_explorer.file_tasks import FileTasks, Plan
from jupyter_storage_explorer.transfer_policy import computer_url

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fsspec import AbstractFileSystem


# Largest file that can be downloaded: it passes through kernel memory and the
# notebook's connection in one message.
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


class FileRequestsMixin:
    """Answers the frontend's requests for file operations: download, move,
    rename, delete, paste, upload, create a folder, properties, and the
    downloads to JupyterLab. Most are planned by FileTasks and run as jobs
    (see JobsMixin)."""

    # --- Download to local: the browser saves the files on the user's computer ---

    def _download(self, paths: list[str]) -> None:
        """Send each file to the browser, which saves it; one message per file."""
        for path in paths:
            reply: dict[str, Any] = {
                "type": "download",
                "path": path,
                "name": _paths.basename(path),
            }
            try:
                refused = self._transfer_policy.error(
                    self._location(self._fs, path),
                    computer_url(_paths.basename(path)),
                )
                if refused is not None:
                    raise PermissionError(refused)
                info = self._info(path)
                if info.get("type") == "directory":
                    raise ValueError("folders cannot be downloaded")
                size = info.get("size")
                if size is not None and size > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"too large to download (over {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB)"
                    )
                data = self._read_bytes(path)
            except Exception as exc:
                reply["error"] = f"{_paths.basename(path)}: {exc}"
                self.send(reply)
            else:
                self.send(reply, [data])

    # --- Move: files (and, in unsafe mode, folders) dragged onto a folder;
    # rename and delete: chosen in the right-click menu ---

    def _move_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().move(
                content["paths"],
                content["dest"],
                content.get("if_exists", "ask"),
                folders=bool(content.get("unsafe")),
            )
        )

    def _rename_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().rename(
                content["path"], content["name"], folders=bool(content.get("unsafe"))
            )
        )

    def _delete_request(self, content: dict[str, Any]) -> dict[str, Any]:
        return self._plan_request(
            lambda: self._tasks().delete(
                content["paths"], folders=bool(content.get("unsafe"))
            )
        )

    # --- Paste: files (and, in unsafe mode, folders) copied with "Copy" or
    # "Cut" (in any explorer, any storage), into a folder ---

    def _paste_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "paste": files copied (or with "cut", cut) in the explorer
        ``content["explorer"]``, from its storage ``content["filesystem"]``."""
        return self._plan_request(
            lambda: self._paste_plan(
                content["files"],
                content["dest"],
                content.get("if_exists", "ask"),
                explorer=content.get("explorer"),
                filesystem=content.get("filesystem"),
                folders=bool(content.get("unsafe")),
                cut=bool(content.get("cut")),
            )
        )

    def _paste_plan(
        self,
        files: Sequence[dict[str, Any]],
        dest: str,
        if_exists: str,
        *,
        explorer: str | None,
        filesystem: str | None,
        folders: bool,
        cut: bool,
    ) -> Plan:
        """Plan pasting ``files`` ({"path", "url"}, as copied) into ``dest``
        (see ``FileTasks.paste``)."""
        sources, errors, urls = self._paste_sources(files, explorer, filesystem, cut)
        return self._tasks(urls).paste(
            sources, dest, if_exists, folders=folders, cut=cut, errors=errors
        )

    def _paste_sources(
        self,
        files: Sequence[dict[str, Any]],
        explorer: str | None,
        filesystem: str | None,
        cut: bool = False,
    ) -> tuple[
        list[tuple[AbstractFileSystem, str]], list[str], dict[tuple[int, str], str]
    ]:
        """The (filesystem, path) of files copied in explorer ``explorer``, from
        its storage ``filesystem``, errors for those not found, and their URLs
        as copied (by their explorer's ``_url``), for the policy (see
        ``_tasks``).

        If that explorer is in this kernel, its filesystem object is used, as
        it is (credentials included). Otherwise it is in another kernel and
        only the files' URLs tell where they are (see ``_locate``).
        """
        source = explorers.get(explorer or "")
        entry = None if source is None else source._filesystems.get(filesystem or "")
        sources, errors, urls = [], [], {}
        for file in files:
            path, url = file.get("path"), file.get("url")
            try:
                if entry is not None:
                    fs, root = entry
                    if cut and _paths.norm(path) == _paths.norm(root):
                        raise ValueError("the top folder is not moved")
                elif url is None:
                    raise ValueError("its location is unknown")
                else:
                    fs, path = self._locate(url)
            except Exception as exc:
                errors.append(f"{_paths.basename(path or url or '')}: {exc}")
                continue
            sources.append((fs, path))
            if url is not None:
                urls[id(fs), _paths.norm(path)] = url
        return sources, errors, urls

    # --- Upload: files (and, in unsafe mode, folders) dragged in from
    # JupyterLab's file browser, which the kernel copies itself ---

    def _upload_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "upload": ``paths`` are relative to JupyterLab's server folder ``root``."""
        base = os.path.expanduser(content["root"])
        sources = [os.path.join(base, *p.split("/")) for p in content["paths"]]
        return self._plan_request(
            lambda: self._tasks().upload(
                sources,
                content["dest"],
                content.get("if_exists", "ask"),
                folders=bool(content.get("unsafe")),
            )
        )

    # --- Upload from the user's computer: the browser sends files in pieces
    # (see incoming.py); the last one starts a job copying the whole file ---

    def _upload_check(self, dest: str, names: list[str]) -> dict[str, Any]:
        """Which of ``names`` already exist in ``dest``."""
        return {
            "conflicts": [
                n for n in names if self._exists(_paths.join(dest, _paths.safe_name(n)))
            ]
        }

    def _upload_chunk(
        self, content: dict[str, Any], buffers: list[Any]
    ) -> dict[str, Any]:
        """Add one piece of a file; the last one starts a job copying the file
        to the storage: {"job": id}. The frontend stops sending a file after
        an error ({"error": ...})."""
        upload_id = content["id"]
        try:
            name = _paths.safe_name(content["name"])
            target = _paths.join(content["dest"], name)
            refused = self._transfer_policy.error(
                computer_url(name), self._location(self._fs, target)
            )
            if refused is not None:
                raise PermissionError(refused)
            piece = bytes(buffers[0]) if buffers else None
            self._incoming.add(upload_id, piece, target, self._fs)
            if not content["last"]:
                return {}
            incoming = self._incoming.pop(upload_id)
        except Exception as exc:
            self._incoming.discard(upload_id)
            return {"error": f"{_paths.basename(content['name'])}: {exc}"}
        tasks = FileTasks(incoming.fs, self._root, self._operations)
        return self._start(tasks.upload_file(incoming.path, incoming.target))

    # --- Create a folder: "Create a folder" in the right-click menu ---

    def _create_folder_request(self, content: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._create_folder(content["dest"], content["name"])
        except Exception as exc:
            return {"error": error_text(exc)}

    def _create_folder(self, dest: str, name: str) -> dict[str, Any]:
        """Create folder ``name`` (a name, not a path) in folder ``dest``, with
        the operations' ``mkdir`` (quick: not a job).

        Returns {"created": name}, with "hidden": True when the new folder does
        not show, as on object stores (S3, Google Cloud Storage), which have no
        empty folders; or {"error": reason}.
        """
        if (error := _paths.name_error(name)) is not None:
            return {"error": error}
        path = _paths.join(dest, name)
        if self._exists(path):
            return {"error": f"{name} already exists"}  # the dialog shows where
        self._operations.mkdir(self._fs, path)
        self._refresh_dir(dest)
        return {"created": name, "hidden": not self._isdir(path)}

    # --- Properties: "Properties" in the right-click menu ---

    def _properties_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "properties": for a single file, {"file": its properties}
        (see ``properties.file_properties``); otherwise {"job": id} of a job
        counting the files and folders (see ``FileTasks.properties``), on the
        runner of its own. Or {"error": reason}."""
        paths = content["paths"]
        try:
            if len(paths) == 1:
                info = self._info(paths[0])
                if info.get("type") != "directory":
                    url = self._url(_paths.norm(info["name"]))
                    return {"file": properties.file_properties(info, url)}
            task = self._tasks().properties(paths)
        except Exception as exc:
            return {"error": error_text(exc)}
        job = self._scans.submit(task.kind, task.title, task.work)
        return {"job": job.id}

    # --- Download to the Jupyter server: "Download to JupyterLab", and files
    # dropped on JupyterLab's file browser ---

    def _download_to_jupyterlab_request(
        self, content: dict[str, Any]
    ) -> dict[str, Any]:
        """Answer "download_to_jupyterlab": copy into ``download_to_jupyterlab_path``."""
        return self._plan_request(
            lambda: self._tasks().download(
                content["paths"],
                self._download_to_jupyterlab_path,
                content.get("if_exists", "ask"),
            )
        )

    def _download_to_server_request(self, content: dict[str, Any]) -> dict[str, Any]:
        """Answer "download_to_server": ``dest`` is relative to the server's folder ``root``."""
        dest = os.path.join(
            os.path.expanduser(content["root"]),
            *filter(None, content["dest"].split("/")),
        )
        return self._plan_request(
            lambda: self._tasks().download(
                content["paths"], dest, content.get("if_exists", "ask")
            )
        )
