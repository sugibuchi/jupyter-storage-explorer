"""The data browser's settings for a dataset, as users write them
(``QuerySettings``) and as explorers remember them (``QueryState``)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from jupyter_storage_explorer._query.filters import as_text

DEFAULT_SETTINGS: dict[str, Any] = {
    "filters": {},
    "sort": None,
    "hidden": [],
    "widths": {},
}


@dataclass
class QuerySettings:
    """The data browser's settings for one dataset, to write in a notebook.

    Settings that do not fit the data (unknown columns, filters for another
    type) are left out when it opens. To keep settings made in the widget,
    print ``explorer.settings.to_json()`` and paste the text into your code,
    as ``DataExplorer``'s ``settings`` or ``QuerySettings.from_json(...)``.

    Attributes
    ----------
    filters : dict of str to dict
        Column name -> filter, e.g. ``{"op": "range", "min": 10}``. Filter
        types ("op"), as offered for the column's type in the data browser:
        "not_null", "null", "not_empty", "empty"; "contains" and "regex" with
        a "value" (and ``"case_sensitive": False`` to ignore case); "range"
        with "min" and/or "max" (both included; numbers, dates or text); "eq"
        (booleans) with a "value".
    sort : str or None
        The column to sort by, or None for the data's order.
    descending : bool
        Whether ``sort`` is descending. Missing values always come last.
    hidden : list of str
        Columns not shown.
    widths : dict of str to int
        Column widths (px); columns not listed are sized automatically.

    Examples
    --------
    >>> QuerySettings(
    ...     filters={
    ...         "price": {"op": "range", "min": 10},
    ...         "name": {"op": "contains", "value": "tea", "case_sensitive": False},
    ...         "comment": {"op": "not_null"},
    ...     },
    ...     sort="date",
    ...     descending=True,
    ...     hidden=["comment"],
    ... )
    """

    filters: dict[str, dict[str, Any]] = field(default_factory=dict)
    sort: str | None = None  # a column name
    descending: bool = False
    hidden: list[str] = field(default_factory=list)
    widths: dict[str, int] = field(default_factory=dict)  # px

    def to_dict(self) -> dict[str, Any]:
        """The settings in the form the data browser keeps them.

        Returns
        -------
        dict
            {"filters", "sort": {"column", "descending"} or None, "hidden",
            "widths"} (see the module docstring); copies, not the attributes.
        """
        return {
            "filters": copy.deepcopy(self.filters),
            "sort": None
            if self.sort is None
            else {"column": self.sort, "descending": self.descending},
            "hidden": list(self.hidden),
            "widths": dict(self.widths),
        }

    def to_json(self, indent: int | None = 4) -> str:
        """The settings as JSON text, e.g. to paste into a notebook cell.

        Parameters
        ----------
        indent : int or None, default 4
            Indentation, as for ``json.dumps``; None for a single line.

        Returns
        -------
        str
            ``to_dict()`` as JSON; dates in filters become ISO text.

        See Also
        --------
        from_json : The settings back from this text.
        """
        return json.dumps(self.to_dict(), indent=indent, default=as_text)

    @classmethod
    def from_json(cls, text: str) -> QuerySettings:
        """Settings from JSON text, as ``to_json`` gives.

        Parameters
        ----------
        text : str
            A JSON object in the form of ``to_dict()``.

        Returns
        -------
        QuerySettings

        Raises
        ------
        ValueError
            If ``text`` is not JSON, or not a JSON object.
        """
        settings = json.loads(text)
        if not isinstance(settings, dict):
            raise ValueError("query settings must be a JSON object")
        return cls.from_dict(settings)

    @classmethod
    def from_dict(cls, settings: dict[str, Any]) -> QuerySettings:
        """Settings from the form the data browser keeps them in.

        Parameters
        ----------
        settings : dict
            As ``to_dict()`` gives; missing parts are the defaults.

        Returns
        -------
        QuerySettings
        """
        sort = settings.get("sort") or {}
        return cls(
            filters=copy.deepcopy(settings.get("filters") or {}),
            sort=sort.get("column"),
            descending=bool(sort.get("descending")),
            hidden=list(settings.get("hidden") or []),
            widths=dict(settings.get("widths") or {}),
        )


@dataclass(frozen=True)
class QueryState:
    """How the data browser last showed one dataset.

    Attributes
    ----------
    url : str
        The dataset's location.
    settings : QuerySettings
        Its filters, sort order, hidden columns and widths.
    mode : {"auto", "live", "memory"}
        Where its queries ran: "live" or "memory" if the user chose, else
        "auto" (see ``DataExplorer``'s ``mode``).
    """

    url: str
    settings: QuerySettings = field(default_factory=QuerySettings)
    mode: str = "auto"
