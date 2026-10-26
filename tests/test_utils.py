"""util.py: the helpers for the explorer and its plugins."""

from __future__ import annotations

import pytest

import jupyter_storage_explorer
from jupyter_storage_explorer import actions
from jupyter_storage_explorer.util import format_size, get_logger


@pytest.mark.parametrize(
    ("name", "logger"),
    [
        # A user's actions file, as _extensions/user_actions.py names it.
        (
            "jupyter_storage_explorer_user_actions_0123456789ab_my_views",
            "jupyter_storage_explorer.user_actions.my_views",
        ),
        (
            "jupyter_storage_explorer.actions.base",
            "jupyter_storage_explorer.actions.base",
        ),
        ("jupyter_storage_explorer", "jupyter_storage_explorer"),
        (
            "jupyter_storage_explorer_polars_support.actions",
            "jupyter_storage_explorer.ext.jupyter_storage_explorer_polars_support.actions",
        ),
        ("__main__", "jupyter_storage_explorer.ext.__main__"),
    ],
)
def test_get_logger(name, logger):
    assert get_logger(name).name == logger


def test_get_logger_aliases():
    assert jupyter_storage_explorer.get_logger is get_logger
    assert actions.get_logger is get_logger


def test_format_size():
    assert format_size(10 * 1024 * 1024) == "10 MB"
    assert format_size(1536) == "1.5 KB"
    assert format_size(2048) == "2 KB"  # no ".0"
    assert format_size(586 * 1024 * 1024 + 1) == "586 MB"
    assert format_size(512) == "512 B"
    assert format_size(3 * 1024**5) == "3,072 TB"
