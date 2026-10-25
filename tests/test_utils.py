"""util.py: the helpers for the explorer and its plugins."""

from __future__ import annotations

from jupyter_storage_explorer.util import format_size


def test_format_size():
    assert format_size(10 * 1024 * 1024) == "10 MB"
    assert format_size(1536) == "1.5 KB"
    assert format_size(2048) == "2 KB"  # no ".0"
    assert format_size(586 * 1024 * 1024 + 1) == "586 MB"
    assert format_size(512) == "512 B"
    assert format_size(3 * 1024**5) == "3,072 TB"
