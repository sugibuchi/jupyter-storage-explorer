"""formats/utils.py: the default formats and the explorers' format_options."""

from __future__ import annotations

import inspect

import pytest

from jupyter_storage_explorer.formats import (
    DEFAULT_FORMATS,
    FORMAT_OPTIONS,
    Csv,
    DeltaLake,
    Text,
    default_formats,
    explorer_formats,
)


def test_format_options_lists_exactly_what_the_formats_take():
    taken = {
        p.name
        for cls in DEFAULT_FORMATS
        for p in inspect.signature(cls).parameters.values()
        if p.kind is p.KEYWORD_ONLY
    }
    assert taken == set(FORMAT_OPTIONS)


def test_default_formats_are_new_objects():
    first, second = default_formats(), default_formats()
    assert [type(f) for f in first] == list(DEFAULT_FORMATS)
    assert all(a is not b for a, b in zip(first, second, strict=True))


def test_options_reach_the_formats_that_take_them():
    formats = {f.name: f for f in default_formats({"polars_storage_options": {"a": 1}})}
    assert formats["delta"].polars_storage_options == {"a": 1}
    assert formats["csv"].polars_storage_options == {"a": 1}
    assert not hasattr(formats["text"], "polars_storage_options")


def test_unknown_option():
    with pytest.raises(
        ValueError, match=r"unknown format_options \['polars_use_pyarrow'\]"
    ):
        default_formats({"polars_use_pyarrow": True})


class TestExplorerFormats:
    def test_given_formats(self):
        formats = [Csv()]
        assert explorer_formats(formats, None) == formats

    def test_default(self):
        assert [type(f) for f in explorer_formats(None, None)] == list(DEFAULT_FORMATS)

    def test_with_options(self):
        [delta] = [
            f
            for f in explorer_formats(None, {"polars_delta_use_pyarrow": True})
            if isinstance(f, DeltaLake)
        ]
        assert delta.polars_delta_use_pyarrow

    def test_both_given(self):
        with pytest.raises(TypeError, match="cannot be combined"):
            explorer_formats([Text()], {})
