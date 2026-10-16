"""A folder's listing, filtered, sorted and paged in the kernel.

The file list normally does this in the browser, from the whole listing.
Folders with more items than ``StorageExplorer``'s ``max_browser_items`` are
handled here instead, and the browser receives one page at a time. The
results follow the browser's (see ``createList`` in static/storage_explorer/list.js) as
closely as Python allows.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

# A name's parts for sorting: digits, letters, or any other single character.
_PARTS = re.compile(r"(\d+)|([^\W\d_]+)|(.)", re.DOTALL)

SORT_KEYS = ("name", "size", "mtime")


def name_key(name: str) -> list[tuple[int, int, str]]:
    """Sort key for a name, close to the browser's ``Intl.Collator`` with
    ``numeric`` and ``sensitivity: "base"``.

    Numbers compare by value ("2" before "10"), letters ignoring case and
    accents, and other characters (spaces, punctuation) before digits, which
    come before letters. Characters other than these may order differently
    from the browser.
    """
    key = []
    for digits, letters, other in _PARTS.findall(name):
        if digits:
            key.append((1, int(digits), ""))
        elif letters:
            key.append((2, 0, _base_letters(letters)))
        else:
            key.append((0, ord(other), ""))
    return key


def _base_letters(text: str) -> str:
    """``text`` without accents, in lower case: "Résumé" -> "resume"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class Listing:
    """A folder's items as columns (see ``StorageExplorer._make_listing``).

    ``query`` returns a page of them; sort orders are computed once per
    listing, so filtering and paging only filter and slice them.
    """

    def __init__(self, columns: dict[str, Any]) -> None:
        self.columns = columns
        self._orders: dict[tuple[str, bool], list[int]] = {}
        self._lower_names: list[str] | None = None

    @property
    def dir(self) -> str:
        return self.columns["dir"]

    def __len__(self) -> int:
        return len(self.columns["names"])

    def update(self, i: int, size: int | None, mtime: int | None) -> None:
        """Set the size and modification time of the item at index ``i``."""
        # New lists and dict: a copy sent to the browser must compare unequal.
        sizes, mtimes = list(self.columns["sizes"]), list(self.columns["mtimes"])
        sizes[i], mtimes[i] = size, mtime
        self.columns = {**self.columns, "sizes": sizes, "mtimes": mtimes}
        self._orders = {k: v for k, v in self._orders.items() if k[0] == "name"}

    def without(self, indexes: set[int]) -> Listing:
        """This listing without the items at ``indexes`` (e.g. deleted)."""
        return Listing(self._subset([i for i in range(len(self)) if i not in indexes]))

    def query(
        self,
        *,
        text: str = "",
        regex: bool = False,
        sort: str = "name",
        asc: bool = True,
        page: int = 0,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """A page of the items whose names match ``text`` (a substring, or a
        regular expression with ``regex``; case is ignored), sorted by
        ``sort`` with folders first.

        Returns {"listing": the page's columns, as ``_make_listing``'s,
        "matching", "total", "page"}, the page number limited to those there
        are; and "filter_error" if ``text`` is not a valid regular expression,
        which then filters nothing, as in the browser.
        """
        if sort not in SORT_KEYS:
            raise ValueError(f"cannot sort by {sort!r}")
        order = self._order(sort, asc)
        out: dict[str, Any] = {}
        if text and regex:
            try:
                search = re.compile(text, re.IGNORECASE).search
            except re.error as exc:
                out["filter_error"] = f"Invalid regular expression: {exc}"
            else:
                names = self.columns["names"]
                order = [i for i in order if search(names[i])]
        elif text:
            needle, lower = text.lower(), self._lower()
            order = [i for i in order if needle in lower[i]]
        pages = max(1, math.ceil(len(order) / page_size))
        page = min(max(page, 0), pages - 1)
        indexes = order[page * page_size : (page + 1) * page_size]
        return {
            **out,
            "listing": self._subset(indexes),
            "matching": len(order),
            "total": len(self),
            "page": page,
        }

    def _order(self, sort: str, asc: bool) -> list[int]:
        """Indexes of the items in this order: folders first, each group sorted.

        Items comparing equal keep the listing's order, as the browser's
        (stable) sort does.
        """
        if (sort, asc) not in self._orders:
            column = self.columns["names" if sort == "name" else f"{sort}s"]
            if sort == "name":
                keys = [name_key(n) for n in column]
            else:
                # As in the browser, a missing value sorts as the smallest.
                keys = [-math.inf if v is None else v for v in column]
            is_dir = self.columns["is_dir"]
            groups = (
                [i for i in range(len(self)) if is_dir[i]],
                [i for i in range(len(self)) if not is_dir[i]],
            )
            self._orders[sort, asc] = [
                i
                for group in groups
                for i in sorted(group, key=keys.__getitem__, reverse=not asc)
            ]
        return self._orders[sort, asc]

    def _lower(self) -> list[str]:
        """The names in lower case, for text filters (as createFilter's)."""
        if self._lower_names is None:
            self._lower_names = [n.lower() for n in self.columns["names"]]
        return self._lower_names

    def _subset(self, indexes: list[int]) -> dict[str, Any]:
        """The columns of the items at ``indexes``, in that order."""
        c = self.columns
        no_url = set(c["no_url"])
        return {
            "dir": c["dir"],
            **{
                key: [c[key][i] for i in indexes]
                for key in ("names", "is_dir", "sizes", "mtimes", "ctimes", "format")
            },
            "formats": c["formats"],
            "paths": None if c["paths"] is None else [c["paths"][i] for i in indexes],
            "no_url": [j for j, i in enumerate(indexes) if i in no_url],
        }
