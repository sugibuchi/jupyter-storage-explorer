"""The explorer's logs: the records of its loggers ("jupyter_storage_explorer.*"),
written to the console or to files of one day each.

Logging is the kernel's, not an explorer's: the explorers of a kernel share
the package's logger, so the last setting made applies to them all
(``configure``).

An explorer in a notebook logs to the console, the kernel's stderr, which
JupyterLab shows under the cell. The launcher's explorers log to files
instead, in ``storage-explorer/logs`` in the user's Jupyter configuration
directory: one a day for each kernel, ``storage-explorer.<date>.<pid>.log``.
The launcher's tabs and its side panel are kernels of their own, so no two
processes write to one file. A kernel moves to the next day's file at local
midnight. No file is ever renamed, as Windows cannot rename a file another
kernel has open: the files of the oldest days beyond the backups kept are
deleted instead.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import pathlib
import re
import sys
import threading
from typing import IO, Any

from jupyter_core.paths import jupyter_config_dir

LOGGER_NAME = "jupyter_storage_explorer"
log = logging.getLogger(__name__)

# The levels users choose from, by name, and "disabled": no records at all.
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
DISABLED = "disabled"
# Other names accepted for levels, in upper case.
_ALIASES = {"WARN": "WARNING"}

# In the user's Jupyter configuration directory.
LOG_DIR = pathlib.Path("storage-explorer", "logs")
_FILE_NAME = re.compile(r"storage-explorer\.(\d{4}-\d{2}-\d{2})\.\d+\.log")

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def level_name(value: Any, name: str = "logging_level") -> str:
    """``value`` as one of ``LEVELS`` or ``DISABLED``: level names in any
    case, and "WARN", are accepted. ValueError for others, naming the
    argument ``name``."""
    if isinstance(value, str):
        upper = value.upper()
        upper = _ALIASES.get(upper, upper)
        if upper in LEVELS:
            return upper
        if upper == DISABLED.upper():
            return DISABLED
    raise ValueError(
        f'{name} must be "{DISABLED}" or one of {", ".join(LEVELS)}, not {value!r}'
    )


def log_folder() -> pathlib.Path:
    """Where the launcher's explorers write their logs: in the user's Jupyter
    configuration directory (``~/.jupyter`` unless ``JUPYTER_CONFIG_DIR`` is
    set)."""
    return pathlib.Path(jupyter_config_dir(), LOG_DIR)


def log_file(
    day: dt.date | None = None,
    folder: pathlib.Path | None = None,
    pid: int | None = None,
) -> pathlib.Path:
    """The log file of ``day``, by default today's (local time), of the
    process ``pid``, by default this kernel's, in ``folder``, by default
    ``log_folder()``."""
    day = day or dt.date.today()
    pid = os.getpid() if pid is None else pid
    name = f"storage-explorer.{day.isoformat()}.{pid}.log"
    return (folder or log_folder()) / name


class DailyFileHandler(logging.Handler):
    """Writes records to this kernel's file of their day, in ``folder``,
    keeping the files of ``backups`` days before today (see the module's
    docstring).

    The file is opened for appending, as the process id of a kernel gone may
    come back, and flushed after each record, so that it can be read at once.
    """

    def __init__(self, folder: pathlib.Path, backups: int) -> None:
        super().__init__()
        self.folder = folder
        self.backups = backups
        self._day: dt.date | None = None
        self._stream: IO[str] | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = dt.date.fromtimestamp(record.created)
            if day != self._day or self._stream is None:
                self._open(day)
            assert self._stream is not None
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _open(self, day: dt.date) -> None:
        """Move to ``day``'s file, and delete the files of the days before
        beyond ``backups``."""
        self._close_stream()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._stream = log_file(day, self.folder).open("a", encoding="utf-8")
        self._day = day
        self._delete_old(day)

    def _delete_old(self, day: dt.date) -> None:
        """Delete every kernel's files of the days before ``day`` but the
        ``backups`` latest days. Another kernel may still have one open, e.g.
        on Windows: it is then deleted another time."""
        older: dict[str, list[pathlib.Path]] = {}
        for path in self.folder.iterdir():
            match = _FILE_NAME.fullmatch(path.name)
            if match and match.group(1) < day.isoformat():
                older.setdefault(match.group(1), []).append(path)
        days = sorted(older)
        for old in days[: max(len(days) - self.backups, 0)]:
            for path in older[old]:
                with contextlib.suppress(OSError):
                    path.unlink()

    def _close_stream(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(OSError):
                self._stream.close()
            self._stream = None

    def close(self) -> None:
        self.acquire()
        try:
            self._close_stream()
        finally:
            self.release()
        super().close()


class _ConsoleHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes records to ``sys.stderr`` as it is when they are written, as
    the kernel may replace it, e.g. for each cell."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> Any:  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, value: Any) -> None:
        pass


# The handler configure() added, if any, and what it writes to: "console",
# or the folder and backups of the files.
_lock = threading.Lock()
_handler: logging.Handler | None = None
_target: tuple[Any, ...] | None = None


def configure(level: str, backups: int | None) -> None:
    """Log the package's records of ``level`` (of ``LEVELS``) and above: to
    the day's file, keeping the files of ``backups`` days before, or to the
    console with ``backups`` None. ``DISABLED`` logs nothing, not even
    through Python's last-resort handler, which would write warnings to
    stderr. Replaces the kernel's previous setting.

    The records still go on to the root logger's handlers, as libraries'
    do: none in a kernel, unless the notebook configures logging."""
    global _handler, _target  # noqa: PLW0603
    logger = logging.getLogger(LOGGER_NAME)
    target = ("console",) if backups is None else ("files", log_folder(), backups)
    with _lock:
        if _handler is not None and (level == DISABLED or target != _target):
            logger.removeHandler(_handler)
            _handler.close()
            _handler, _target = None, None
        if level == DISABLED:
            logger.setLevel(logging.CRITICAL + 1)
            return
        if _handler is None:
            _handler = (
                _ConsoleHandler()
                if backups is None
                else DailyFileHandler(log_folder(), backups)
            )
            _handler.setFormatter(logging.Formatter(_FORMAT))
            logger.addHandler(_handler)
            _target = target
        logger.setLevel(level)


def reset() -> None:
    """Undo ``configure``: the package's logger as Python makes it. For
    tests."""
    global _handler, _target
    logger = logging.getLogger(LOGGER_NAME)
    with _lock:
        if _handler is not None:
            logger.removeHandler(_handler)
            _handler.close()
            _handler, _target = None, None
        logger.setLevel(logging.NOTSET)
