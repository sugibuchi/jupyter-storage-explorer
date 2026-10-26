"""_logs.py: the package's records, to the console or to files of one day each."""

from __future__ import annotations

import datetime as dt
import io
import logging
import os
import time

import pytest

from jupyter_storage_explorer import _logs

log = logging.getLogger("jupyter_storage_explorer.tests")


def at(day: dt.date, message: str) -> logging.LogRecord:
    """A record of ``day``, at noon local time."""
    record = log.makeRecord(log.name, logging.WARNING, __file__, 0, message, (), None)
    record.created = time.mktime((day.year, day.month, day.day, 12, 0, 0, 0, 0, -1))
    return record


class TestLevelName:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("INFO", "INFO"),
            ("debug", "DEBUG"),
            ("WARN", "WARNING"),
            ("warn", "WARNING"),
            ("Critical", "CRITICAL"),
            ("disabled", "disabled"),
            ("DISABLED", "disabled"),
        ],
    )
    def test_accepted(self, value, expected):
        assert _logs.level_name(value) == expected

    @pytest.mark.parametrize("value", ["verbose", "", None, 20, "NOTSET"])
    def test_refused(self, value):
        with pytest.raises(ValueError, match="logging_level must be"):
            _logs.level_name(value)


class TestDailyFiles:
    def test_one_file_a_day(self, tmp_path):
        handler = _logs.DailyFileHandler(tmp_path, backups=14)
        handler.setFormatter(logging.Formatter("%(message)s"))
        first, second = dt.date(2026, 10, 25), dt.date(2026, 10, 26)
        handler.emit(at(first, "one"))
        handler.emit(at(first, "two"))
        handler.emit(at(second, "three"))  # after midnight: the next day's file
        handler.close()
        assert _logs.log_file(first, tmp_path).read_text("utf-8") == "one\ntwo\n"
        assert _logs.log_file(second, tmp_path).read_text("utf-8") == "three\n"

    def test_a_file_per_kernel(self, tmp_path):
        # Another kernel's file is left alone, and named by its process id.
        day = dt.date(2026, 10, 26)
        theirs = _logs.log_file(day, tmp_path, pid=1)
        theirs.write_text("theirs\n", "utf-8")
        handler = _logs.DailyFileHandler(tmp_path, backups=14)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(at(day, "mine"))
        handler.close()
        assert theirs.read_text("utf-8") == "theirs\n"
        mine = _logs.log_file(day, tmp_path)
        assert mine.name == f"storage-explorer.2026-10-26.{os.getpid()}.log"
        assert mine.read_text("utf-8") == "mine\n"

    def test_appended_to(self, tmp_path):
        # A process id may come back: what the gone kernel wrote stays.
        day = dt.date(2026, 10, 26)
        _logs.log_file(day, tmp_path).write_text("before\n", "utf-8")
        handler = _logs.DailyFileHandler(tmp_path, backups=14)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(at(day, "after"))
        handler.close()
        assert _logs.log_file(day, tmp_path).read_text("utf-8") == "before\nafter\n"

    def test_old_files_deleted(self, tmp_path):
        # By day, whichever kernels wrote them.
        for d in range(1, 11):
            for pid in (1, 2):
                path = _logs.log_file(dt.date(2026, 10, d), tmp_path, pid=pid)
                path.write_text("old\n", "utf-8")
        (tmp_path / "notes.txt").write_text("not a log", "utf-8")
        handler = _logs.DailyFileHandler(tmp_path, backups=3)
        handler.emit(at(dt.date(2026, 10, 11), "new"))
        handler.close()
        kept = sorted(p.name for p in tmp_path.iterdir())
        assert kept == [
            "notes.txt",
            "storage-explorer.2026-10-08.1.log",
            "storage-explorer.2026-10-08.2.log",
            "storage-explorer.2026-10-09.1.log",
            "storage-explorer.2026-10-09.2.log",
            "storage-explorer.2026-10-10.1.log",
            "storage-explorer.2026-10-10.2.log",
            _logs.log_file(dt.date(2026, 10, 11), tmp_path).name,
        ]

    def test_no_backups(self, tmp_path):
        old = _logs.log_file(dt.date(2026, 10, 1), tmp_path, pid=1)
        old.write_text("old\n", "utf-8")
        handler = _logs.DailyFileHandler(tmp_path, backups=0)
        handler.emit(at(dt.date(2026, 10, 2), "new"))
        handler.close()
        assert [p.name for p in tmp_path.iterdir()] == [
            _logs.log_file(dt.date(2026, 10, 2), tmp_path).name
        ]


class TestConfigure:
    def test_to_the_console(self, monkeypatch):
        stderr = io.StringIO()
        monkeypatch.setattr("sys.stderr", stderr)
        _logs.configure("INFO", None)
        log.debug("hidden")
        log.info("shown")
        assert "INFO jupyter_storage_explorer.tests: shown" in stderr.getvalue()
        assert "hidden" not in stderr.getvalue()

    def test_to_files(self, jupyter_config_dirs):
        _logs.configure("WARNING", 14)
        log.warning("in the file")
        text = _logs.log_file().read_text("utf-8")
        assert "WARNING jupyter_storage_explorer.tests: in the file" in text
        assert _logs.log_file().parent == _logs.log_folder()

    def test_disabled(self, monkeypatch, capsys):
        # Not even through Python's last-resort handler.
        _logs.configure("disabled", None)
        log.error("nothing")
        assert "nothing" not in capsys.readouterr().err

    def test_the_last_setting_wins(self, monkeypatch):
        stderr = io.StringIO()
        monkeypatch.setattr("sys.stderr", stderr)
        _logs.configure("ERROR", None)
        _logs.configure("INFO", None)
        log.info("once")
        assert stderr.getvalue().count("once") == 1
        _logs.configure("ERROR", 14)  # to files instead: none to the console
        log.error("in a file")
        assert "in a file" not in stderr.getvalue()
