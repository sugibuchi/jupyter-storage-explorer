"""StorageExplorer's logs: to the console in notebooks; with logging_menu, to
the day's file, at the level chosen in the settings menu's Logging."""

from __future__ import annotations

import datetime as dt
import logging

import pytest
import traitlets
from explorers import make

from jupyter_storage_explorer import _logs
from jupyter_storage_explorer._explorer.states import ExplorerStates

log = logging.getLogger("jupyter_storage_explorer.tests")


class Stderr:
    """What the test wrote to stderr so far, through pytest's capture: a
    fixture's own sys.stderr would be replaced by pytest's after the
    fixtures are set up."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self._text = ""

    def getvalue(self) -> str:
        self._text += self._capsys.readouterr().err
        return self._text


@pytest.fixture
def stderr(capsys) -> Stderr:
    return Stderr(capsys)


class TestInANotebook:
    def test_warnings_to_the_console(self, memfs, stderr):
        explorer = make("/", fs=memfs)
        log.info("hidden")
        log.warning("shown")
        assert "shown" in stderr.getvalue()
        assert "hidden" not in stderr.getvalue()
        assert not explorer._logging_menu
        assert "log" not in explorer._config_paths
        assert not _logs.log_folder().exists()

    def test_a_level(self, memfs, stderr):
        make("/", fs=memfs, logging_level="debug")
        log.debug("details")
        assert "DEBUG jupyter_storage_explorer.tests: details" in stderr.getvalue()

    def test_disabled(self, memfs, stderr):
        make("/", fs=memfs, logging_level="disabled")
        log.error("nothing")
        assert stderr.getvalue() == ""

    def test_the_level_not_set_by_the_page(self, memfs, stderr):
        # Without the menu, the explorer logs as it was created.
        explorer = make("/", fs=memfs)
        explorer._logging_level = "DEBUG"
        log.debug("hidden")
        assert stderr.getvalue() == ""


class TestWithTheMenu:
    def test_nothing_until_chosen(self, memfs, stderr):
        # As the launcher creates its explorers.
        explorer = make("/", fs=memfs, logging_menu="enabled", logging_level="disabled")
        log.error("nothing")
        assert explorer._logging_menu
        assert explorer._logging_level == "disabled"
        assert not _logs.log_file().exists()
        assert stderr.getvalue() == ""

    def test_the_level_chosen(self, memfs, stderr):
        states = ExplorerStates()
        explorer = make(
            "/",
            fs=memfs,
            states=states,
            logging_menu="enabled",
            logging_level="disabled",
        )
        explorer._logging_level = "INFO"  # chosen in the menu
        log.info("to the file")
        text = _logs.log_file().read_text("utf-8")
        assert "Logging at INFO" in text  # the file, created at once
        assert "to the file" in text
        assert stderr.getvalue() == ""
        # Remembered: the next explorer starts with it.
        assert states.logging_level == "INFO"
        again = make(
            "/",
            fs=memfs,
            states=states,
            logging_menu="enabled",
            logging_level="disabled",
        )
        assert again._logging_level == "INFO"

    def test_a_remembered_level_edited_by_hand(self, memfs, tmp_path):
        path = tmp_path / "states.json"
        path.write_text('{"logging_level": "loud"}', encoding="utf-8")
        explorer = make(
            "/",
            fs=memfs,
            states=str(path),
            logging_menu="enabled",
            logging_level="ERROR",
        )
        assert explorer._logging_level == "ERROR"

    def test_a_level_refused(self, memfs):
        explorer = make("/", fs=memfs, logging_menu="enabled")
        with pytest.raises(traitlets.TraitError, match="logging_level must be"):
            explorer._logging_level = "loud"

    def test_the_log_file_opened_read_only(self, memfs):
        explorer = make("/", fs=memfs, logging_menu="enabled", logging_level="ERROR")
        assert explorer._config_paths["log"] == str(_logs.log_folder())
        open_ = {"type": "settings_open", "rid": 1, "file": "log"}
        # Not created: nothing was logged yet.
        assert explorer.request({**open_, "create": True}) == {
            "type": "reply",
            "rid": 1,
            "missing": True,
        }
        log.error("a line")
        reply = explorer.request(open_)
        assert reply["name"] == _logs.log_file().name
        get = {"type": "jupyterlab_get", "rid": 2, "settings": "log", "format": "text"}
        model = explorer.request(get)["model"]
        assert "a line" in model["content"]
        assert model["writable"] is False
        save = {
            "type": "jupyterlab_save",
            "rid": 3,
            "settings": "log",
            "content": "",
            "format": "text",
        }
        assert "only read" in explorer.request(save)["error"]
        assert "a line" in _logs.log_file().read_text("utf-8")

    def test_backups(self, memfs):
        folder = _logs.log_folder()
        folder.mkdir(parents=True)
        for day in range(1, 5):
            _logs.log_file(dt.date(2020, 1, day), pid=1).write_text("old\n", "utf-8")
        make(
            "/",
            fs=memfs,
            logging_menu="enabled",
            logging_level="INFO",
            log_file_backup=2,
        )
        log.info("today")
        assert sorted(p.name for p in folder.iterdir()) == [
            "storage-explorer.2020-01-03.1.log",
            "storage-explorer.2020-01-04.1.log",
            _logs.log_file().name,
        ]


@pytest.fixture
def records(caplog):
    """The package's records of DEBUG and above, from now on: the level set
    after the explorer is created, which sets its own."""

    def messages(level=logging.DEBUG):
        return [r.getMessage() for r in caplog.records if r.levelno >= level]

    caplog.set_level(logging.DEBUG, logger=_logs.LOGGER_NAME)
    return messages


class TestRecords:
    """What the explorer logs, by level: INFO what the user does, WARNING
    what goes wrong, DEBUG the details."""

    def test_created(self, memfs, caplog):
        caplog.set_level(logging.INFO)
        make("/", fs=memfs, logging_level="INFO")
        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("Plugins loaded: ") for m in messages)
        created = next(m for m in messages if "created in" in m)
        assert "storages default (memory)" in created

    def test_messages_and_listings(self, mem_explorer, records):
        mem_explorer._current_dir = "/data"
        mem_explorer.message({"type": "refresh"})
        assert any(m.startswith("Listed /data: 3 items") for m in records())
        assert any(m.startswith("Message refresh from the page") for m in records())

    def test_a_job(self, mem_explorer, records):
        mem_explorer.message(
            {"type": "move", "rid": 1, "paths": ["/data/a.csv"], "dest": "/other"}
        )
        info = records(logging.INFO)
        assert any(m.endswith("started: Moving a.csv into other") for m in info)
        done = next(m for m in info if " done in " in m)
        assert "1 moved, 1 files" in done

    def test_a_job_with_errors(self, mem_explorer, records):
        mem_explorer.message(
            {"type": "delete", "rid": 1, "paths": ["/data/a.csv", "/data/gone.csv"]}
        )
        warnings = records(logging.WARNING)
        assert any(": 1 errors, the first: gone.csv" in m for m in warnings)

    def test_a_view(self, mem_explorer, records):
        mem_explorer._open_preview("/data/notes.md")
        info = records(logging.INFO)
        assert any(m.startswith("Viewed /data/notes.md as markdown with") for m in info)
        assert any(m.startswith("Detected /data/notes.md in") for m in records())

    def test_a_view_failing(self, mem_explorer, records):
        mem_explorer._open_preview("/data/a.csv", "image")
        warnings = records(logging.WARNING)
        assert any(m.startswith("/data/a.csv cannot be previewed:") for m in warnings)

    def test_a_transfer_refused(self, memfs, records):
        memfs.pipe_file("/d/a.txt", b"a")
        explorer = make("/", fs=memfs, transfer_policy=[{"rule": "deny"}])
        explorer.request({"type": "move", "rid": 1, "paths": ["/d/a.txt"], "dest": "/"})
        warnings = records(logging.WARNING)
        assert any(m.endswith("refused by transfer_policy rule 0") for m in warnings)


class TestArguments:
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"logging_menu": "on"}, "logging_menu must be one of"),
            ({"logging_level": "loud"}, "logging_level must be"),
            ({"log_file_backup": -1}, "log_file_backup must be"),
            ({"log_file_backup": 1.5}, "log_file_backup must be"),
            ({"log_file_backup": True}, "log_file_backup must be"),
        ],
    )
    def test_refused(self, memfs, kwargs, message):
        with pytest.raises(ValueError, match=message):
            make("/", fs=memfs, **kwargs)
