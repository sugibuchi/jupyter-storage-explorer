"""Errors as users read them: the first line says what went wrong."""

from __future__ import annotations

from jupyter_storage_explorer._errors import SUMMARY_CHARS, error_text


class Py4JJavaError(Exception):
    """As PySpark raises it: the call, then the Java exception and its stack."""


SPARK = (
    "An error occurred while calling o57.parquet.\n"
    ": java.lang.ClassNotFoundException: Class "
    "org.apache.hadoop.fs.azurebfs.SecureAzureBlobFileSystem not found\n"
    "\tat org.apache.hadoop.conf.Configuration.getClass(Configuration.java:2688)\n"
    "\tat org.apache.hadoop.fs.FileSystem.getFileSystemClass(FileSystem.java:3431)\n"
)


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
