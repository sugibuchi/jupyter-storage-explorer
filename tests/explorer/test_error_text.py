"""Errors as users read them: the first line says what went wrong."""

from __future__ import annotations

import logging

import pytest

from jupyter_storage_explorer._errors import (
    SUMMARY_CHARS,
    error_text,
    log_failure,
    reason,
    redacted,
)


class Py4JJavaError(Exception):
    """As PySpark raises it: the call, then the Java exception and its stack."""


SPARK = (
    "An error occurred while calling o57.parquet.\n"
    ": java.lang.ClassNotFoundException: Class "
    "org.apache.hadoop.fs.azurebfs.SecureAzureBlobFileSystem not found\n"
    "\tat org.apache.hadoop.conf.Configuration.getClass(Configuration.java:2688)\n"
    "\tat org.apache.hadoop.fs.FileSystem.getFileSystemClass(FileSystem.java:3431)\n"
)


@pytest.mark.parametrize("exc", [TimeoutError(), ValueError(" "), OSError("")])
def test_errors_without_a_message_say_their_type(exc):
    assert error_text(exc) == type(exc).__name__
    assert reason(exc) == type(exc).__name__


def test_reason_is_the_message():
    assert reason(FileNotFoundError("a.csv")) == "a.csv"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (
            "403, url='https://a.blob.core.windows.net/c?sv=2024&sig=S3CRET'",
            "403, url='https://a.blob.core.windows.net/c?sv=2024&sig=***'",
        ),
        (
            "https://s3/k?X-Amz-Signature=S3CRET&a=1",
            "https://s3/k?X-Amz-Signature=***&a=1",
        ),
        ("sftp://me:S3CRET@host/a", "sftp://me:***@host/a"),
        ("https://host:8080/a?b=1", "https://host:8080/a?b=1"),
    ],
)
def test_secrets_of_urls_redacted(text, shown):
    assert redacted(text) == shown


class TestLogFailure:
    log = logging.getLogger("jupyter_storage_explorer.test_errors")

    def fail(self, exc):
        """``exc`` raised, with its stack trace, and a cause with a secret."""
        try:
            try:
                raise OSError("https://h/a?sig=S3CRET")
            except OSError as cause:
                raise exc from cause
        except Exception as raised:
            log_failure(self.log, raised, "Cannot list %s: %s", "/a", reason(raised))

    def test_a_storage_failing_is_an_error_with_its_stack_trace(self, caplog):
        caplog.set_level(logging.WARNING, logger=self.log.name)
        self.fail(TimeoutError())
        [record] = caplog.records
        assert record.levelname == "ERROR"
        assert record.getMessage().startswith("Cannot list /a: TimeoutError\n")
        assert "Traceback (most recent call last)" in record.getMessage()

    def test_stack_traces_hold_no_secrets(self, caplog):
        caplog.set_level(logging.WARNING, logger=self.log.name)
        self.fail(TimeoutError())
        assert "sig=***" in caplog.text
        assert "S3CRET" not in caplog.text
        assert caplog.records[0].exc_info is None

    @pytest.mark.parametrize(
        "exc",
        [FileNotFoundError("a"), PermissionError("a"), ValueError("too large")],
    )
    def test_everyday_conditions_are_warnings(self, caplog, exc):
        caplog.set_level(logging.WARNING, logger=self.log.name)
        self.fail(exc)
        [record] = caplog.records
        assert record.levelname == "WARNING"
        assert "Traceback" not in record.getMessage()

    def test_their_stack_traces_at_debug(self, caplog):
        caplog.set_level(logging.DEBUG, logger=self.log.name)
        self.fail(FileNotFoundError("a"))
        [record] = caplog.records
        assert record.levelname == "WARNING"
        assert "Traceback" in record.getMessage()


def test_short_errors_as_they_are():
    assert error_text(FileNotFoundError("a.csv")) == "FileNotFoundError: a.csv"
    assert error_text(ValueError("a.csv is gone")) == "a.csv is gone"


def test_spark_errors_start_with_the_java_exception():
    text = error_text(Py4JJavaError(SPARK))
    summary, rest = text.split("\n", 1)
    assert summary == (
        "java.lang.ClassNotFoundException: Class "
        "org.apache.hadoop.fs.azurebfs.SecureAzureBlobFileSystem not found"
    )
    assert rest == f"Py4JJavaError: {SPARK}"  # the whole, for "Details"


def test_other_multiline_errors_keep_their_first_line():
    text = error_text(RuntimeError("cannot read\nmore about it"))
    assert text == "RuntimeError: cannot read\nmore about it"


def test_a_line_too_long_is_cut_in_the_summary():
    long = "x" * 1000
    summary, rest = error_text(ValueError(long)).split("\n", 1)
    assert len(summary) == SUMMARY_CHARS
    assert summary.endswith("…")
    assert rest == long
