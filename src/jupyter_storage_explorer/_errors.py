"""Errors as users read them: what the explorer's widgets, its jobs and its
loads show when something fails. And as the logs hold them: ``log_failure``."""

from __future__ import annotations

import logging
import re
import traceback

# Py4J's errors (Spark's) start with the call that failed, e.g. "An error
# occurred while calling o57.parquet.": the Java exception is on the next line.
_PY4J_CALL = re.compile(r"An error occurred while calling [\w.$]+\.?$")

# The longest first line of an error; a longer one is cut there.
SUMMARY_CHARS = 300

# What users meet in everyday use, rather than a storage failing: a file gone,
# a folder they have no access to, the explorer's own refusals (ValueError).
_EXPECTED = (
    ValueError,
    FileNotFoundError,
    FileExistsError,
    PermissionError,
    IsADirectoryError,
    NotADirectoryError,
)

# Secrets in the URLs of errors, e.g. aiohttp's holds the whole signed URL: a
# query's value by its name, and the password of "scheme://user:password@host".
_URL_SECRETS = re.compile(
    r"(?i)([?&](?:sig|signature|x-amz-signature|x-amz-credential"
    r"|x-amz-security-token|x-goog-signature|x-goog-credential|sas_token"
    r"|access_token|token|code|key|password|secret|client_secret|api_key)=)"
    r"[^&\s'\"]+"
    r"|(://[^/\s:@]+:)[^/\s@]+(?=@)"
)


def reason(exc: BaseException) -> str:
    """Why something failed, after a name: "a.csv: <reason>". Never empty, as
    e.g. ``TimeoutError()`` has no message: its type then says it."""
    return str(exc).strip() or type(exc).__name__


def is_expected(exc: BaseException) -> bool:
    """Whether ``exc`` is an everyday condition, not a failure of the storage
    or of a library."""
    return isinstance(exc, _EXPECTED)


def redacted(text: str) -> str:
    """``text`` without the secrets of URLs in it, for the logs."""
    return _URL_SECRETS.sub(lambda m: f"{m[1] or m[2]}***", text)


def log_failure(
    log: logging.Logger, exc: BaseException, message: str, *args: object
) -> None:
    """Log a failure the user sees too: as an ERROR with its stack trace, or
    for an expected one a WARNING, with its stack trace at DEBUG only.

    The record holds the formatted text, not ``exc_info``, so that no handler
    can write the secrets of a chained exception's message.
    """
    level = logging.WARNING if is_expected(exc) else logging.ERROR
    text = message % args
    if level == logging.ERROR or log.isEnabledFor(logging.DEBUG):
        text = f"{text}\n{''.join(traceback.format_exception(exc)).rstrip()}"
    log.log(level, "%s", redacted(text))


def error_text(exc: Exception) -> str:
    """An error for users: the explorer's own refusals (ValueError) as they
    are, others with their type, e.g. "FileNotFoundError: ...".

    Its first line says what went wrong: the frontend shows it, and the rest
    under "Details". So a long error (e.g. Spark's, with the Java stack
    trace) starts with a line of its own: for Py4J's, the Java exception
    rather than the call; for a single line too long, its beginning."""
    message = str(exc)
    if not message.strip():
        return type(exc).__name__  # e.g. TimeoutError(), which has no message
    text = message if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = lines[0]
    if _PY4J_CALL.search(summary) and len(lines) > 1:
        summary = lines[1].removeprefix(":").strip()
    if len(summary) > SUMMARY_CHARS:
        summary = summary[: SUMMARY_CHARS - 1] + "…"
    return text if summary == text.splitlines()[0] else f"{summary}\n{text}"
