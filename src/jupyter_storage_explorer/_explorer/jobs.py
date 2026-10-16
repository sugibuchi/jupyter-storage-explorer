"""StorageExplorer's jobs: running file operations and following them (a mixin of the class)."""

from __future__ import annotations

import dataclasses
import functools
import math
import time
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._explorer.common import error_text
from jupyter_storage_explorer._urls import default_url
from jupyter_storage_explorer.file_tasks import FileTasks, Plan, Task
from jupyter_storage_explorer.operations import same_filesystem
from jupyter_storage_explorer.transfer_policy import jupyterlab_url

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.jobs import Job


# While a job runs, what it has changed is shown at most this often (seconds):
# items gone leave the list at once, without asking the storage; new items
# show by listing their folder again, a request (for large folders on object
# stores, several), so less often.
_FOLLOW_INTERVAL = 1.0
_RELIST_INTERVAL = 3.0


@dataclasses.dataclass
class _Followed:
    """How much of a running task's changes the explorer has shown (see
    ``StorageExplorer._follow``): counts of its records shown, and when."""

    moved: int = 0
    removed: int = 0
    moved_away: int = 0
    additions: int = 0
    shown_at: float = -math.inf
    listed_at: float = -math.inf


class JobsMixin:
    """Runs the operations FileTasks plans as jobs, and shows what they change
    as they run and once they have ended."""

    # --- Jobs: move, delete, paste, upload and download run in the
    # background. Each is planned by FileTasks (file_tasks.py), its work runs
    # in a job's worker thread (jobs.py), and back on the main thread, _follow
    # shows what it has changed so far as it runs, and _finish all it changed
    # once it has ended ---

    def _tasks(self, urls: Mapping[tuple[int, str], str] | None = None) -> FileTasks:
        """Plans operations on the filesystem shown, within the policy.

        ``urls``: the URLs of files pasted, as copied, by (id of their
        filesystem, normalized path), for the policy (see ``_transfer_error``).
        """
        return FileTasks(
            self._fs,
            self._root,
            self._operations,
            check=functools.partial(self._transfer_error, urls=urls or {}),
        )

    def _transfer_error(
        self,
        source_fs: AbstractFileSystem | None,
        source: str,
        target_fs: AbstractFileSystem | None,
        target: str,
        urls: Mapping[tuple[int, str], str],
    ) -> str | None:
        """Why the policy refuses copying or moving ``source`` to ``target``, or
        None. A filesystem None is JupyterLab's side (see ``FileTasks``)."""
        if not self._transfer_policy.rules:
            return None
        source_url = urls.get((id(source_fs), _paths.norm(source)))
        if source_url is None:
            source_url = self._location(source_fs, source)
        return self._transfer_policy.error(
            source_url, self._location(target_fs, target)
        )

    def _location(self, fs: AbstractFileSystem | None, path: str) -> str:
        """``path``'s URL for the policy: ``_url``'s on the filesystem shown,
        else (another storage, files without a URL) ``default_url``'s; for
        fs None, the Jupyter server's disk through JupyterLab's file browser,
        ``jupyterlab_url``'s."""
        if fs is None:
            return jupyterlab_url(path)
        if same_filesystem(fs, self._fs) and (url := self._url(path)) is not None:
            return url
        return default_url(fs, path)

    def _start(self, plan: Plan) -> dict[str, Any]:
        """Run ``plan`` as a job: {"job": its id}; or the reply as it is if
        there is nothing to run (e.g. {"conflicts": [...]} to ask about)."""
        if isinstance(plan, dict):
            return plan
        followed = _Followed()
        job = self._jobs.submit(
            plan.kind,
            plan.title,
            plan.work,
            finish=lambda job: self._finish(plan),
            update=lambda job: self._follow(plan, followed),
        )
        return {"job": job.id}

    def _finish(self, task: Task) -> None:
        """After ``task``, whatever its outcome: follow what it moved or
        removed, and show the folders it changed."""
        if task.cleanup is not None:
            task.cleanup()
        for fs, path in task.moved_away:
            self._moved_away(fs, path)
        if not same_filesystem(task.fs, self._fs):
            task.fs.invalidate_cache()  # the user has switched filesystems
            return
        for source, target in task.moved:
            self._forget(source, moved_to=target)
        for path in task.removed:
            self._forget(path)
        for folder in task.changed:
            self._refresh_dir(folder)

    def _follow(self, task: Task, followed: _Followed) -> None:
        """While ``task`` runs, show what it has changed since last time
        (``followed``): items moved or deleted leave the list and the tree at
        once (they are only dropped, so this asks the storage nothing);
        folders that got new items are listed again, less often (see
        ``_FOLLOW_INTERVAL``, ``_RELIST_INTERVAL``). ``_finish`` shows
        everything once it has ended."""
        now = time.monotonic()
        if now - followed.shown_at < _FOLLOW_INTERVAL:
            return
        followed.shown_at = now
        changes = task.changes()
        shown = same_filesystem(task.fs, self._fs)  # else the user switched
        gone: list[tuple[str, str | None]] = []
        for fs, path in changes.moved_away[followed.moved_away :]:
            if same_filesystem(fs, self._fs):
                gone.append((path, None))
            else:
                fs.invalidate_cache(_paths.parent(path, fs))
        if shown:
            gone += changes.moved[followed.moved :]
            gone += [(path, None) for path in changes.removed[followed.removed :]]
        followed.moved_away = len(changes.moved_away)
        followed.moved = len(changes.moved)
        followed.removed = len(changes.removed)
        if gone:
            self._show_gone(gone)
        if (
            shown
            and changes.additions > followed.additions
            and now - followed.listed_at >= _RELIST_INTERVAL
        ):
            followed.additions = changes.additions
            followed.listed_at = now
            for folder in changes.added_to:
                self._invalidate_cache(folder)
                if folder == self._current_dir:
                    self._relist_current()
                elif folder in self._tree:
                    self._load_children(folder)

    def _show_gone(self, gone: Sequence[tuple[str, str | None]]) -> None:
        """Drop items moved (to the path paired with them) or deleted (None)
        from the list, the selection and the tree, without listing again."""
        for path, moved_to in gone:
            self._invalidate_cache(_paths.parent(path, self._fs))
            self._forget(path, moved_to=moved_to)  # e.g. leaves a folder deleted
        paths = {_paths.norm(path) for path, _ in gone}
        rows = {
            i for i, p in enumerate(self._listed_paths()) if _paths.norm(p) in paths
        }
        if rows:
            self._full_listing = self._full_listing.without(rows)
            self._send_listing()
        if any(_paths.norm(p) in paths for p in self._selected):
            self._selected = [p for p in self._selected if _paths.norm(p) not in paths]
        tree = {
            folder: [d for d in dirs if _paths.norm(d["path"]) not in paths]
            for folder, dirs in self._tree.items()
        }
        if tree != self._tree:
            self._tree = tree

    def _relist_current(self) -> None:
        """List the folder shown again, keeping the selection (unlike _list,
        for a folder newly shown): items appear while a job adds them."""
        path = self._current_dir
        try:
            infos = self._ls(path)
        except Exception:
            return  # the job's end lists it again, and reports errors
        self._set_children(path, infos)
        self._show_listing(self._make_listing(path, infos))
        listed = {_paths.norm(p) for p in self._listed_paths()}
        kept = [p for p in self._selected if _paths.norm(p) in listed]
        if kept != list(self._selected):
            self._selected = kept

    def _moved_away(self, fs: AbstractFileSystem, path: str) -> None:
        """Follow ``path`` of ``fs``, cut and pasted into another filesystem.

        If ``fs`` is shown, as if deleted; else (another of this explorer's
        storages, or another explorer's, whose frontend tells it: see
        ``_sources_changed``) its cached listing is dropped.
        """
        parent = _paths.parent(path, fs)
        if not same_filesystem(fs, self._fs):
            fs.invalidate_cache(parent)
            return
        self._forget(path)
        self._refresh_dir(parent)

    def _sources_changed(self, filesystem: str, paths: Sequence[str]) -> None:
        """Answer "changed": files of storage ``filesystem`` were cut here and
        pasted in another explorer, which may have moved some (or all) away."""
        storage = self._filesystems.get(filesystem)
        if storage is None:
            return
        fs = storage.fs
        parents = {_paths.parent(p, fs) for p in paths}
        if fs is not self._fs:
            for parent in parents:
                fs.invalidate_cache(parent)
            return
        for parent in parents:
            self._invalidate_cache(parent)
        for path in paths:
            if not self._exists(path):
                self._forget(path)
        for parent in parents:
            self._refresh_dir(parent)

    def _send_job(self, job: Job) -> None:
        """Tell the frontend how ``job`` is doing (see Job.snapshot)."""
        self.send({"type": "job", **job.snapshot()})

    def _cancel_job(self, content: dict[str, Any]) -> None:
        job_id = content.get("id", "")
        if not self._jobs.cancel(job_id):
            self._scans.cancel(job_id)

    def _plan_request(self, plan: Callable[[], Plan]) -> dict[str, Any]:
        """Answer a request for an operation: start ``plan()``, or say why not."""
        try:
            return self._start(plan())
        except Exception as exc:
            return {"errors": [error_text(exc)]}
