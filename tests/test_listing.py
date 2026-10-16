"""Filtering, sorting and paging large folders in the kernel (_explorer/listing.py)."""

from __future__ import annotations

from typing import Any

import pytest

from jupyter_storage_explorer._explorer.listing import Listing, name_key


def columns(items: list[tuple[str, bool, int | None, int | None]]) -> dict[str, Any]:
    """Columns as _make_listing's, of (name, is_dir, size, mtime) in /d."""
    return {
        "dir": "/d",
        "names": [n for n, *_ in items],
        "is_dir": [int(d) for _, d, *_ in items],
        "sizes": [s for _, _, s, _ in items],
        "mtimes": [t for *_, t in items],
        "ctimes": [None for _ in items],
        "formats": ["", "csv"],
        "format": [int(n.endswith(".csv")) for n, *_ in items],
        "paths": None,
        "no_url": [],
    }


def names(page: dict[str, Any]) -> list[str]:
    return page["listing"]["names"]


@pytest.fixture
def listing() -> Listing:
    return Listing(
        columns(
            [
                ("file10.csv", False, 30, 3),
                ("b", True, None, None),
                ("File2.csv", False, 10, None),
                ("file1.txt", False, 20, 1),
                ("A", True, None, 5),
            ]
        )
    )


def test_without(listing):
    listing.columns["no_url"] = [2, 4]  # File2.csv and A
    rest = listing.without({0, 2})
    assert rest.columns["names"] == ["b", "file1.txt", "A"]
    assert rest.columns["sizes"] == [None, 20, None]
    assert rest.columns["format"] == [0, 0, 0]
    assert rest.columns["no_url"] == [2]  # A, now third
    assert names(rest.query()) == ["A", "b", "file1.txt"]


class TestNameKey:
    def test_like_the_browser(self):
        # The order Intl.Collator(undefined, {numeric: true, sensitivity: "base"})
        # gives in Edge (checked with node), apart from ties.
        names = [
            "file10.csv",
            "file2.csv",
            "File1.csv",
            "z10",
            "Z",
            "z9",
            "_x",
            "a b",
            "a",
        ]
        assert sorted(names, key=name_key) == [
            "_x",
            "a",
            "a b",
            "File1.csv",
            "file2.csv",
            "file10.csv",
            "Z",
            "z9",
            "z10",
        ]

    def test_accents_and_case_are_ignored(self):
        assert name_key("Résumé") == name_key("resume")


class TestQuery:
    def test_folders_first_then_names(self, listing):
        page = listing.query()
        assert names(page) == ["A", "b", "file1.txt", "File2.csv", "file10.csv"]
        assert page["matching"] == page["total"] == 5
        assert page["page"] == 0

    def test_descending_keeps_folders_first(self, listing):
        assert names(listing.query(asc=False)) == [
            "b",
            "A",
            "file10.csv",
            "File2.csv",
            "file1.txt",
        ]

    def test_by_size_and_time(self, listing):
        assert names(listing.query(sort="size")) == [
            "b",
            "A",
            "File2.csv",
            "file1.txt",
            "file10.csv",
        ]
        # Missing times sort as the smallest.
        assert names(listing.query(sort="mtime")) == [
            "b",
            "A",
            "File2.csv",
            "file1.txt",
            "file10.csv",
        ]

    def test_text_filter_ignores_case(self, listing):
        page = listing.query(text="FILE1")
        assert names(page) == ["file1.txt", "file10.csv"]
        assert page["matching"] == 2 and page["total"] == 5

    def test_regex_filter(self, listing):
        assert names(listing.query(text=r"^file\d\.", regex=True)) == [
            "file1.txt",
            "File2.csv",
        ]

    def test_invalid_regex_filters_nothing(self, listing):
        page = listing.query(text="a(", regex=True)
        assert page["filter_error"].startswith("Invalid regular expression")
        assert page["matching"] == 5

    def test_pages(self, listing):
        assert names(listing.query(page=1, page_size=2)) == ["file1.txt", "File2.csv"]
        last = listing.query(page=9, page_size=2)
        assert last["page"] == 2 and names(last) == ["file10.csv"]

    def test_page_columns(self, listing):
        listing.columns["no_url"] = [3]  # file1.txt
        page = listing.query(text="file")["listing"]
        assert page["dir"] == "/d"
        assert page["names"] == ["file1.txt", "File2.csv", "file10.csv"]
        assert page["sizes"] == [20, 10, 30]
        assert [page["formats"][i] for i in page["format"]] == ["", "csv", "csv"]
        assert page["no_url"] == [0]
        assert page["paths"] is None

    def test_update(self, listing):
        assert names(listing.query(sort="size")) == [
            "b",
            "A",
            "File2.csv",
            "file1.txt",
            "file10.csv",
        ]
        listing.update(0, 1, 9)  # file10.csv
        assert names(listing.query(sort="size")) == [
            "b",
            "A",
            "file10.csv",
            "File2.csv",
            "file1.txt",
        ]
        assert listing.query(text="file10")["listing"]["mtimes"] == [9]

    def test_unknown_sort(self, listing):
        with pytest.raises(ValueError, match="cannot sort"):
            listing.query(sort="owner")
