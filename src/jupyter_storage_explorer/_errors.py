"""Errors as users read them: what the explorer's widgets, its jobs and its
loads show when something fails."""

from __future__ import annotations

import re

# Py4J's errors (Spark's) start with the call that failed, e.g. "An error
# occurred while calling o57.parquet.": the Java exception is on the next line.
_PY4J_CALL = re.compile(r"An error occurred while calling [\w.$]+\.?$")

# The longest first line of an error; a longer one is cut there.
SUMMARY_CHARS = 300


def error_text(exc: Exception) -> str:
    """An error for users: the explorer's own refusals (ValueError) as they
    are, others with their type, e.g. "FileNotFoundError: ...".

    Its first line says what went wrong: the frontend shows it, and the rest
    under "Details". So a long error (e.g. Spark's, with the Java stack
    trace) starts with a line of its own: for Py4J's, the Java exception
    rather than the call; for a single line too long, its beginning."""
    text = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    summary = lines[0]
    if _PY4J_CALL.search(summary) and len(lines) > 1:
        summary = lines[1].removeprefix(":").strip()
    if len(summary) > SUMMARY_CHARS:
        summary = summary[: SUMMARY_CHARS - 1] + "…"
    return text if summary == text.splitlines()[0] else f"{summary}\n{text}"
