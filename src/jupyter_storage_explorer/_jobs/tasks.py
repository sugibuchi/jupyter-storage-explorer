"""File operations planned for ``StorageExplorer``: move, delete, paste, upload, download.

Each is planned by a ``FileTasks`` method on the kernel's main thread: checks
(folders only in unsafe mode, never into themselves, ...) and the files that
already exist, to ask the user about. The result is a reply for the
frontend (e.g. {"conflicts": [...]}), or a ``Task`` to run: its
``work(progress)`` does the operation in a job's worker thread (see runner.py)
through the operations objects (see filesystems/operation.py), and records what it
changed on the task (files moved or removed, folders whose listing changed),
for the explorer to show as the job goes and once it has ended.

Planning reads the filesystem (exists, isdir), but nothing here touches the
widget, so the tasks can be tested and run without one.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import tempfile
import threading
from typing import TYPE_CHECKING, Any, TypeVar

from fsspec.implementations.local import LocalFileSystem

from jupyter_storage_explorer import _paths
from jupyter_storage_explorer._jobs import properties
from jupyter_storage_explorer.filesystems.mapper import MapperChain
from jupyter_storage_explorer.filesystems.mappers import default_mappers
from jupyter_storage_explorer.filesystems.operation import (
    OperationCancelled,
    Progress,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from fsspec import AbstractFileSystem

    from jupyter_storage_explorer.filesystems.operation import OperationChain


@dataclasses.dataclass
class Task:
    """An operation planned, to run as a job (see ``StorageExplorer._start``).

    ``work(progress)`` does it (in a worker thread) and returns its result:
    lists of names (e.g. {"moved": [...], "skipped": [...], "errors": [...]}),
    with "cancelled": True and "incomplete": a name if the user cancelled.
    Meanwhile it records (``record``) what changed on ``fs``, the filesystem
    it changes, as each item is done: ``moved`` (source, target) pairs,
    ``removed`` paths, ``changed`` folders, whose listings are to be shown
    again, among them ``added_to``, those that got new items; and in
    ``moved_away``, (filesystem, path) of files and folders moved from other
    filesystems (cut and pasted). The explorer shows them as the job goes
    (``changes``, from the main thread) and once it has ended.
    ``cleanup()``, if any, runs once the job has ended, whatever the outcome
    (e.g. to delete a temporary file even if the job was cancelled before
    starting).
    """

    kind: str  # "move", "delete", "paste", "upload", "download" or "properties"
    title: str  # e.g. "Moving a.csv to data", shown with its progress
    fs: AbstractFileSystem
    work: Callable[[Progress], dict[str, Any]] = lambda progress: {}
    cleanup: Callable[[], None] | None = None
    moved: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    removed: list[str] = dataclasses.field(default_factory=list)
    changed: set[str] = dataclasses.field(default_factory=set)
    added_to: set[str] = dataclasses.field(default_factory=set)
    additions: int = 0  # items added to ``added_to`` folders so far
    moved_away: list[tuple[AbstractFileSystem, str]] = dataclasses.field(
        default_factory=list
    )
    # Guards the records above: the worker thread adds, the main thread reads.
    _lock: threading.Lock = dataclasses.field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def record(
        self,
        *,
        moved: tuple[str, str] | None = None,
        removed: str | None = None,
        moved_away: tuple[AbstractFileSystem, str] | None = None,
        changed: Iterable[str] = (),
        added_to: str | None = None,
    ) -> None:
        """Record an item done (in the worker thread): see the class docstring.
        ``added_to`` is also a changed folder."""
        with self._lock:
            if moved is not None:
                self.moved.append(moved)
            if removed is not None:
                self.removed.append(removed)
            if moved_away is not None:
                self.moved_away.append(moved_away)
            self.changed.update(changed)
            if added_to is not None:
                self.added_to.add(added_to)
                self.changed.add(added_to)
                self.additions += 1

    def changes(self) -> Changes:
        """Copies of what has been recorded so far, safe to read while the
        worker thread records more."""
        with self._lock:
            return Changes(
                moved=list(self.moved),
                removed=list(self.removed),
                moved_away=list(self.moved_away),
                changed=set(self.changed),
                added_to=set(self.added_to),
                additions=self.additions,
            )


@dataclasses.dataclass
class Changes:
    """What a task has changed so far (see ``Task.changes``)."""

    moved: list[tuple[str, str]]
    removed: list[str]
    moved_away: list[tuple[AbstractFileSystem, str]]
    changed: set[str]
    added_to: set[str]
    additions: int


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

    ``check(source_fs, source, target_fs, target)``, if given, tells why a
    transfer may not happen (the explorer's transfer policy, see
    transfer_policy.py), or returns None: items it refuses are left out,
    with that error. Transfers are copies and moves between filesystems:
    within one (as ``mappers`` tell, default the default mappers), e.g.
    moves, nothing is checked. A
    filesystem None is the Jupyter server's disk as JupyterLab's file
    browser shows it (uploads from it, downloads to it), with a local path:
    always a transfer.
    """

    def __init__(
        self,
        fs: AbstractFileSystem,
        root: str,
        operations: OperationChain,
        check: Callable[
            [AbstractFileSystem | None, str, AbstractFileSystem | None, str],
            str | None,
        ]
        | None = None,
        mappers: MapperChain | None = None,
    ) -> None:
        self.fs = fs
        self.root = root
        self.ops = operations
        self.check = check
        self.same_filesystem = (
            mappers or MapperChain(default_mappers())
        ).same_filesystem

    def _refused(
        self,
        source_fs: AbstractFileSystem | None,
        source: str,
        target_fs: AbstractFileSystem | None,
        target: str,
    ) -> str | None:
        """Why ``check`` refuses an item, or None (always, within a filesystem)."""
        if self.check is None:
            return None
        if (
            source_fs is not None
            and target_fs is not None
            and self.same_filesystem(source_fs, target_fs)
        ):
            return None  # not a transfer
        return self.check(source_fs, source, target_fs, target)

    def measure(self, fs: AbstractFileSystem, path: str) -> tuple[int, int]:
        """Files and bytes at ``path``, for the progress bar; (1, 0) if unknown."""
        try:
            measurement = self.ops.measure(fs, path)
            return measurement.files, measurement.bytes
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
                ops.move(fs, source, fs, target, progress, same=True)
                task.record(
                    moved=(source, target),
                    changed=[_paths.parent(source, fs)],
                    added_to=dest,
                )

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
            # Within the filesystem: not a transfer, so the policy does not apply.
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

    # --- Rename: a move within the item's folder ---

    def rename(self, path: str, name: str, folders: bool = False) -> Plan:
        """Rename ``path`` to ``name`` (a name, not a path) with the operations'
        ``move``, e.g. a rename in one step on Azure Data Lake Gen2.

        Result: {"renamed": [name], "errors"}. Or, before any job, {"error":
        reason}: a name that cannot be used or is taken (nothing is replaced),
        or a folder without ``folders``, or the top folder.
        """
        if (error := _paths.name_error(name)) is not None:
            return {"error": error}
        parent = _paths.parent(path, self.fs)
        target = _paths.join(parent, name)
        if _paths.norm(target) == _paths.norm(path):
            return {"error": "that is its name already"}
        is_dir = self.fs.isdir(path)
        if is_dir and not folders:
            return {"error": "folders are renamed only in unsafe mode"}
        if is_dir and _paths.norm(path) == _paths.norm(self.root):
            return {"error": "the top folder is not renamed"}
        if self.fs.exists(target):
            return {"error": f"{name} already exists"}
        fs, ops = self.fs, self.ops
        task = Task("move", f"Renaming {_paths.basename(path)} to {name}", fs)

        def work(progress: Progress) -> dict[str, Any]:
            failed: list[str] = []

            def rename(item: tuple[str, str, bool]) -> None:
                ops.move(fs, path, fs, target, progress, same=True)
                task.record(moved=(path, target), changed=[parent], added_to=parent)

            size = self.measure(fs, path) if is_dir else (1, 0)
            stop = _do_each(progress, [(path, target, is_dir)], [size], rename, failed)
            return _outcome(stop, renamed=[name] if task.moved else [], errors=failed)

        task.work = work
        return task

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
                task.record(removed=item[0], changed=[_paths.parent(item[0], fs)])

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
            same = self.same_filesystem(source_fs, self.fs)
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
        plans = self._plan_copies(
            copies, dest, folders, verb, errors, from_jupyterlab=kind == "upload"
        )
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
                # As the explorer's mappers tell, for the operations to know.
                same = self.same_filesystem(plan.fs, fs)
                if kind != "move":
                    ops.copy(plan.fs, plan.source, fs, plan.target, progress, same=same)
                else:
                    if plan.target in existing:
                        # Renaming onto an existing file fails on some systems.
                        ops.delete(fs, plan.target, progress)
                    ops.move(plan.fs, plan.source, fs, plan.target, progress, same=same)
                    if same:
                        task.record(
                            moved=(plan.source, plan.target),
                            changed=[_paths.parent(plan.source, fs)],
                        )
                    else:
                        task.record(moved_away=(plan.fs, plan.source))
                done.append(_paths.basename(plan.target))
                task.record(added_to=dest)

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
        *,
        from_jupyterlab: bool = False,
    ) -> list[_Copy]:
        """What to copy into ``dest`` (see ``_copy_into``); adds to ``errors``
        for the rest. ``from_jupyterlab``: the sources are on the Jupyter
        server's disk, dragged from JupyterLab's file browser (for ``check``)."""
        plans = []
        for source_fs, source, name in copies:
            try:
                target = _paths.join(dest, _paths.safe_name(name))
                is_folder = source_fs.isdir(source)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            refused = self._refused(
                None if from_jupyterlab else source_fs, source, self.fs, target
            )
            if refused is not None:
                errors.append(f"{name}: {refused}")
            elif is_folder and not folders:
                errors.append(
                    f"{name}: folders are not {verb} (turn on unsafe mode first)"
                )
            elif (
                is_folder
                and self.same_filesystem(source_fs, self.fs)
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
                task.record(added_to=dest)

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
        local = LocalFileSystem()
        for path in paths:
            name = _paths.safe_name(_paths.basename(path))
            target = os.path.join(dest, name)
            refused = self._refused(self.fs, path, None, local._strip_protocol(target))
            if refused is not None:
                errors.append(f"{name}: {refused}")
            elif self.fs.isdir(path):
                errors.append(f"{name}: folders are not downloaded")
            else:
                files.append((path, target))
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

    # --- Properties: totals of files and folders, changing nothing ---

    def properties(self, paths: Sequence[str]) -> Task:
        """Count the files and folders of ``paths`` with the operations'
        ``measure`` (see ``properties.scan``): a job, as large folders take
        long. Records no changes."""
        fs, ops = self.fs, self.ops
        task = Task("properties", f"Counting {_describe(paths)}", fs)
        task.work = lambda progress: properties.scan(ops, fs, paths, progress)
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
