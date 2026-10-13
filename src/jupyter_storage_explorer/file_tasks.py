"""File operations planned for ``StorageExplorer``: move, delete, paste, upload, download.

Each is planned by a ``FileTasks`` method on the kernel's main thread: checks
(folders only in unsafe mode, never into themselves, ...) and the files that
already exist, to ask the user about. The result is a reply for the
frontend (e.g. {"conflicts": [...]}), or a ``Task`` to run: its
``work(progress)`` does the operation in a job's worker thread (see jobs.py)
through the operations objects (see operations.py), and records what it
changed on the task (files moved or removed, folders whose listing changed),
for the explorer to show once the job has ended.

Planning reads the filesystem (exists, isdir), but nothing here touches the
widget, so the tasks can be tested and run without one.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import tempfile
from typing import TYPE_CHECKING, Any, TypeVar

from fsspec.implementations.local import LocalFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer.operations import (
    OperationCancelled,
    Progress,
    same_filesystem,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.operations import OperationChain


@dataclasses.dataclass
class Task:
    """An operation planned, to run as a job (see ``StorageExplorer._start``).

    ``work(progress)`` does it (in a worker thread) and returns its result:
    lists of names (e.g. {"moved": [...], "skipped": [...], "errors": [...]}),
    with "cancelled": True and "incomplete": a name if the user cancelled.
    Meanwhile it records what changed on ``fs``, the filesystem it changes:
    ``moved`` (source, target) pairs, ``removed`` paths, and ``changed``
    folders, whose listings are to be shown again; and in ``moved_away``,
    (filesystem, path) of files and folders moved from other filesystems
    (cut and pasted). ``cleanup()``, if any, runs once the job has ended,
    whatever the outcome (e.g. to delete a temporary file even if the job
    was cancelled before starting).
    """

    kind: str  # "move", "delete", "paste", "upload" or "download"
    title: str  # e.g. "Moving a.csv to data", shown with its progress
    fs: AbstractFileSystem
    work: Callable[[Progress], dict[str, Any]] = lambda progress: {}
    cleanup: Callable[[], None] | None = None
    moved: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    removed: list[str] = dataclasses.field(default_factory=list)
    changed: set[str] = dataclasses.field(default_factory=set)
    moved_away: list[tuple[AbstractFileSystem, str]] = dataclasses.field(
        default_factory=list
    )


# What planning returns: a task to run, or a reply as it is (e.g. conflicts).
Plan = Task | dict[str, Any]

# Per kind of copy into a folder: the result's key for the names copied, the
# verb in messages, and the title's.
_COPY_WORDS = {
    "paste": ("pasted", "pasted", "Pasting"),
    "move": ("moved", "moved", "Moving"),  # cut and pasted
    "upload": ("copied", "uploaded", "Uploading"),
}


@dataclasses.dataclass
class _Copy:
    """A file or folder to copy: ``source`` on ``fs``, copied to ``target``."""

    fs: AbstractFileSystem
    source: str
    target: str


class FileTasks:
    """Plans operations on ``fs``, the filesystem an explorer shows (whose top
    folder is ``root``), done through ``operations``.

    ``if_exists`` (move, paste, upload, download) decides what happens to
    files already at the target: "ask" does nothing and returns
    {"conflicts": [names]} if there are any; "overwrite" replaces them;
    "skip" leaves them (and the file that would replace them). Folders are
    moved, copied and deleted only with ``folders`` (the widget's unsafe mode
    was on), never the top folder, never into themselves, and never onto
    anything that exists.
    """

    def __init__(
        self, fs: AbstractFileSystem, root: str, operations: OperationChain
    ) -> None:
        self.fs = fs
        self.root = root
        self.ops = operations

    def measure(self, fs: AbstractFileSystem, path: str) -> tuple[int, int]:
        """Files and bytes at ``path``, for the progress bar; (1, 0) if unknown."""
        try:
            return self.ops.measure(fs, path)
        except Exception:
            return 1, 0  # the operation itself reports what is wrong

    # --- Move: files (and folders) dragged onto a folder ---

    def move(
        self,
        paths: Sequence[str],
        dest: str,
        if_exists: str = "ask",
        folders: bool = False,
    ) -> Plan:
        """Move ``paths`` into folder ``dest``, each with the operations' ``move``.

        Result: {"moved", "skipped", "errors"}.
        """
        moves, errors = self._plan_moves(paths, dest, folders)
        existing = {target for _, target, _ in moves if self.fs.exists(target)}
        if if_exists == "ask" and existing:
            return _conflicts(existing)
        fs, ops = self.fs, self.ops
        title = f"Moving {_describe(t for _, t, _ in moves)} to {_paths.basename(dest)}"
        task = Task("move", title, fs)

        def work(progress: Progress) -> dict[str, Any]:
            sizes = [self.measure(fs, s) if f else (1, 0) for s, _, f in moves]
            skipped, failed = [], list(errors)

            def move(item: tuple[str, str, bool]) -> None:
                source, target, _ = item
                if target in existing and if_exists == "skip":
                    skipped.append(_paths.basename(target))
                    return
                if target in existing:
                    # Renaming onto an existing file fails on some systems.
                    ops.delete(fs, target, progress)
                ops.move(fs, source, fs, target, progress)
                task.moved.append((source, target))
                task.changed.update({dest, _paths.parent(source, fs)})

            stop = _do_each(progress, moves, sizes, move, failed)
            names = [_paths.basename(s) for s, _ in task.moved]
            return _outcome(stop, moved=names, skipped=skipped, errors=failed)

        task.work = work
        return task

    def _plan_moves(
        self, paths: Sequence[str], dest: str, folders: bool
    ) -> tuple[list[tuple[str, str, bool]], list[str]]:
        """(source, target, is folder) for the items to move, and errors for the rest."""
        moves, errors = [], []
        for path in paths:
            name = _paths.basename(path)
            target = _paths.join(dest, name)
            if _paths.norm(path) == _paths.norm(target):
                continue  # already in that folder
            if not self.fs.isdir(path):
                moves.append((path, target, False))
            elif not folders:
                errors.append(
                    f"{name}: folders are not moved (turn on unsafe mode first)"
                )
            elif _paths.norm(path) == _paths.norm(self.root):
                errors.append(f"{name}: the top folder is not moved")
            elif _paths.inside(dest, path):
                errors.append(f"{name}: a folder cannot be moved into itself")
            elif self.fs.exists(target):
                # Folders are never merged into, or replace, what is there.
                errors.append(f"{name}: already exists in that folder")
            else:
                moves.append((path, target, True))
        return moves, errors

    # --- Delete ---

    def delete(self, paths: Sequence[str], folders: bool = False) -> Plan:
        """Delete ``paths``, each with the operations' ``delete``.

        Result: {"deleted", "errors"}.
        """
        items, errors = self._plan_deletes(paths, folders)
        if not items:
            return {"deleted": [], "errors": errors}
        fs, ops = self.fs, self.ops
        task = Task("delete", f"Deleting {_describe(p for p, _ in items)}", fs)

        def work(progress: Progress) -> dict[str, Any]:
            # Counted by files only: deleting takes about as long whatever the size.
            sizes = [(self.measure(fs, p)[0] if f else 1, 0) for p, f in items]
            failed = list(errors)

            def delete(item: tuple[str, bool]) -> None:
                ops.delete(fs, item[0], progress)
                task.removed.append(item[0])
                task.changed.add(_paths.parent(item[0], fs))

            stop = _do_each(progress, items, sizes, delete, failed)
            names = [_paths.basename(p) for p in task.removed]
            return _outcome(stop, deleted=names, errors=failed)

        task.work = work
        return task

    def _plan_deletes(
        self, paths: Sequence[str], folders: bool
    ) -> tuple[list[tuple[str, bool]], list[str]]:
        """(path, is folder) for the items to delete, and errors for the rest."""
        items, errors = [], []
        for path in paths:
            name = _paths.basename(path)
            is_folder = self.fs.isdir(path)
            if is_folder and not folders:
                errors.append(
                    f"{name}: folders are not deleted (turn on unsafe mode first)"
                )
            elif is_folder and _paths.norm(path) == _paths.norm(self.root):
                errors.append(f"{name}: the top folder is not deleted")
            else:
                items.append((path, is_folder))
        return items, errors

    # --- Paste and upload: copies into a folder of ``fs`` ---

    def paste(
        self,
        sources: Sequence[tuple[AbstractFileSystem, str]],
        dest: str,
        if_exists: str = "ask",
        *,
        folders: bool = False,
        cut: bool = False,
        errors: Sequence[str] = (),
    ) -> Plan:
        """Copy (or with ``cut``, move) files copied in an explorer into folder
        ``dest``, with the operations' ``copy`` (``move``).

        ``sources`` are (filesystem, path): ``fs`` itself, another storage of
        the explorer, another explorer's, or one opened from a URL (see
        ``StorageExplorer._paste_sources``). ``errors`` are those found
        finding them. Nothing is pasted into the folder it is in. Result:
        {"pasted" (or "moved"), "skipped", "errors"}.
        """
        copies, errors = [], list(errors)
        for source_fs, source in sources:
            name = _paths.basename(source)
            same = same_filesystem(source_fs, self.fs)
            if same and _paths.parent(source, self.fs) == _paths.norm(dest):
                errors.append(f"{name}: already in that folder")
                continue
            copies.append((source_fs, source, name))
        return self._copy_into(
            copies,
            dest,
            if_exists=if_exists,
            folders=folders,
            errors=errors,
            kind="move" if cut else "paste",
        )

    def upload(
        self,
        local_paths: Sequence[str],
        dest: str,
        if_exists: str = "ask",
        folders: bool = False,
    ) -> Plan:
        """Copy files (and folders) of the kernel's machine into folder ``dest``,
        e.g. dropped from JupyterLab's file browser, which the kernel reaches
        when it runs where the Jupyter server does. Result: {"copied",
        "skipped", "errors"}."""
        local = LocalFileSystem()
        copies, errors = [], []
        for path in local_paths:
            name = os.path.basename(path.rstrip("/\\"))
            if not os.path.exists(path):
                # e.g. the kernel runs elsewhere than the Jupyter server (a remote kernel).
                errors.append(f"{name}: not found from the kernel")
            else:
                copies.append((local, local._strip_protocol(path), name))
        return self._copy_into(
            copies,
            dest,
            if_exists=if_exists,
            folders=folders,
            errors=errors,
            kind="upload",
        )

    def _copy_into(
        self,
        copies: list[tuple[AbstractFileSystem, str, str]],
        dest: str,
        *,
        if_exists: str,
        folders: bool,
        errors: list[str],
        kind: str,
    ) -> Plan:
        """Copy (filesystem, path, name) items into folder ``dest`` of ``fs``,
        with the operations' ``copy``; or ``move`` them, for ``kind`` "move".
        ``kind``: "paste", "move" or "upload" (see ``_COPY_WORDS``)."""
        key, verb, doing = _COPY_WORDS[kind]
        plans = self._plan_copies(copies, dest, folders, verb, errors)
        existing = {p.target for p in plans if self.fs.exists(p.target)}
        if if_exists == "ask" and existing:
            return _conflicts(existing)
        fs, ops = self.fs, self.ops
        title = (
            f"{doing} {_describe(p.target for p in plans)} into {_paths.basename(dest)}"
        )
        task = Task(kind, title, fs)

        def work(progress: Progress) -> dict[str, Any]:
            sizes = [self.measure(p.fs, p.source) for p in plans]
            done, skipped, failed = [], [], list(errors)

            def copy(plan: _Copy) -> None:
                if plan.target in existing and if_exists == "skip":
                    skipped.append(_paths.basename(plan.target))
                    return
                if kind != "move":
                    ops.copy(plan.fs, plan.source, fs, plan.target, progress)
                else:
                    if plan.target in existing:
                        # Renaming onto an existing file fails on some systems.
                        ops.delete(fs, plan.target, progress)
                    ops.move(plan.fs, plan.source, fs, plan.target, progress)
                    if same_filesystem(plan.fs, fs):
                        task.moved.append((plan.source, plan.target))
                        task.changed.add(_paths.parent(plan.source, fs))
                    else:
                        task.moved_away.append((plan.fs, plan.source))
                done.append(_paths.basename(plan.target))
                task.changed.add(dest)

            stop = _do_each(progress, plans, sizes, copy, failed)
            return _outcome(stop, **{key: done}, skipped=skipped, errors=failed)

        task.work = work
        return task

    def _plan_copies(
        self,
        copies: list[tuple[AbstractFileSystem, str, str]],
        dest: str,
        folders: bool,
        verb: str,
        errors: list[str],
    ) -> list[_Copy]:
        """What to copy into ``dest`` (see ``_copy_into``); adds to ``errors`` for the rest."""
        plans = []
        for source_fs, source, name in copies:
            try:
                target = _paths.join(dest, _paths.safe_name(name))
                is_folder = source_fs.isdir(source)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            if is_folder and not folders:
                errors.append(
                    f"{name}: folders are not {verb} (turn on unsafe mode first)"
                )
            elif (
                is_folder
                and same_filesystem(source_fs, self.fs)
                and _paths.inside(dest, source)
            ):
                errors.append(f"{name}: a folder cannot be {verb} into itself")
            elif is_folder and self.fs.exists(target):
                # Folders are never merged into, or replace, what is there.
                errors.append(f"{name}: already exists in that folder")
            else:
                plans.append(_Copy(source_fs, source, target))
        return plans

    def upload_file(self, local_path: str, target: str, cleanup: bool = True) -> Task:
        """Copy one local file to ``target`` with the operations' ``upload``,
        e.g. one received from the browser; with ``cleanup``, the local file is
        deleted once the job has ended. Result: {"copied", "errors"}."""
        fs, ops = self.fs, self.ops
        name, dest = _paths.basename(target), _paths.parent(target, fs)
        task = Task("upload", f"Uploading {name} into {_paths.basename(dest)}", fs)

        def work(progress: Progress) -> dict[str, Any]:
            failed: list[str] = []

            def upload(_: tuple[str]) -> None:
                ops.upload(local_path, fs, target, progress)
                task.changed.add(dest)

            size = os.path.getsize(local_path)
            stop = _do_each(progress, [(target,)], [(1, size)], upload, failed)
            copied = [name] if task.changed else []
            return _outcome(stop, copied=copied, errors=failed)

        def remove() -> None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(local_path)

        task.work = work
        task.cleanup = remove if cleanup else None
        return task

    # --- Download: files into a folder of the kernel's machine ---

    def download(self, paths: Sequence[str], dest: str, if_exists: str = "ask") -> Plan:
        """Copy files of ``fs`` into ``dest``, a folder on the kernel's machine,
        with the operations' ``download``: "Download to JupyterLab", or files
        dropped on JupyterLab's file browser (which the kernel reaches when it
        runs where the Jupyter server does). Folders are not downloaded.
        Result: {"copied", "skipped", "errors"}.
        """
        if not os.path.isdir(dest):
            # e.g. the kernel runs elsewhere than the Jupyter server (a remote kernel).
            raise ValueError(f"{dest}: folder not found from the kernel")
        files, errors = [], []
        for path in paths:
            name = _paths.safe_name(_paths.basename(path))
            if self.fs.isdir(path):
                errors.append(f"{name}: folders are not downloaded")
            else:
                files.append((path, os.path.join(dest, name)))
        existing = {target for _, target in files if os.path.exists(target)}
        if if_exists == "ask" and existing:
            return {"conflicts": sorted(os.path.basename(t) for t in existing)}
        fs, ops = self.fs, self.ops
        title = f"Downloading {_describe(s for s, _ in files)} to {os.path.basename(dest) or dest}"
        task = Task("download", title, fs)

        def work(progress: Progress) -> dict[str, Any]:
            sizes = [self.measure(fs, s) for s, _ in files]
            copied, skipped, failed = [], [], list(errors)

            def download(item: tuple[str, str]) -> None:
                source, target = item
                if target in existing and if_exists == "skip":
                    skipped.append(os.path.basename(target))
                    return
                # Into a temporary file next to the target first, so a failed copy
                # neither leaves a partial file nor spoils the file it would replace.
                handle, temp_path = tempfile.mkstemp(prefix=".jse-download-", dir=dest)
                os.close(handle)
                try:
                    ops.download(fs, source, temp_path, progress)
                    os.replace(temp_path, target)
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(temp_path)
                copied.append(os.path.basename(target))

            stop = _do_each(progress, files, sizes, download, failed)
            return _outcome(stop, copied=copied, skipped=skipped, errors=failed)

        task.work = work
        return task


# An item of a task: a _Copy, or a tuple whose first part is the path worked on.
_Item = TypeVar("_Item")


def _do_each(
    progress: Progress,
    items: Sequence[_Item],
    sizes: Sequence[tuple[int, int]],
    act: Callable[[_Item], None],
    errors: list[str],
) -> _Stop | None:
    """Do ``act(item)`` for each of a task's ``items`` (in its worker thread),
    whose files and bytes are ``sizes`` (see ``Progress``). Failures are added
    to ``errors`` ("name: reason") and the next item is done; a cancel stops
    at once. Returns None, or if the user cancelled, how it stopped."""
    progress.add_total(files=sum(n for n, _ in sizes), bytes=sum(b for _, b in sizes))
    for item, size in zip(items, sizes, strict=True):
        name = _paths.basename(item.source if isinstance(item, _Copy) else item[0])
        started = False
        try:
            progress.check()
            progress.begin_item(*size)
            started = True
            act(item)
            progress.end_item()
        except OperationCancelled:
            # Stopped during an item: e.g. a folder partly copied or deleted.
            return _Stop(incomplete=name if started else None)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return None


@dataclasses.dataclass
class _Stop:
    """How a cancelled task stopped: ``incomplete`` names the item it was
    working on (e.g. a folder partly copied), if any."""

    incomplete: str | None = None


def _outcome(stop: _Stop | None, **lists: list[str]) -> dict[str, Any]:
    """A task's result: its lists of names; if it was cancelled, "cancelled":
    True and "incomplete": the item it stopped in, if any."""
    if stop is None:
        return lists
    incomplete = {"incomplete": stop.incomplete} if stop.incomplete else {}
    return {**lists, "cancelled": True, **incomplete}


def _conflicts(targets: Iterable[str]) -> dict[str, list[str]]:
    """The reply asking about files that exist: {"conflicts": [names]}."""
    return {"conflicts": sorted(_paths.basename(t) for t in targets)}


def _describe(paths: Iterable[str]) -> str:
    """E.g. "a.csv", "a.csv and b.csv", "3 items"."""
    names = [_paths.basename(p) for p in paths]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{len(names)} items"
