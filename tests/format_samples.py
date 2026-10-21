"""Formats confirmed by their files' signatures (``DataFormat.sniff``), for
formats/test_base.py and explorer/test_explorer_previews.py: two of ".db",
SQLite's and DuckDB's, and files of each."""

from __future__ import annotations

from jupyter_storage_explorer.formats import DataFormat


class SQLite(DataFormat):
    name = "sqlite"
    label = "SQLite database"
    extensions = (".db", ".sqlite")
    sniff_bytes = 16

    def sniff(self, ctx, head):
        return head.startswith(b"SQLite format 3\0")


class DuckDB(DataFormat):
    # Its signature is not at the start: sniff gets the bytes before it too.
    name = "duckdb"
    label = "DuckDB database"
    extensions = (".db", ".duckdb")
    sniff_bytes = 12

    def sniff(self, ctx, head):
        return head[8:12] == b"DUCK"


SQLITE_BYTES = b"SQLite format 3\0" + b"\0" * 100
DUCKDB_BYTES = b"\0" * 8 + b"DUCK" + b"\0" * 100
