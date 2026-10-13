"""Transfer policies: the directions in which an explorer copies and moves files.

``StorageExplorer(policy=[...])`` takes a list of rules::

    [
        {"rule": "allow", "src": r"abfs://lake@acct\\.dfs\\.core\\.windows\\.net/curated/.*", "dest": ".*"},
        {"rule": "deny", "src": r"abfs://lake@.*", "dest": ".*"},
    ]

A transfer has a source URL and a destination URL (see ``TransferPolicy``).
Rules are tried in order: the first whose ``src`` and ``dest`` regular
expressions both match the whole URLs (``re.fullmatch``) decides; if none
does, the transfer is allowed. A pattern left out matches any URL.

This only keeps files from going where they are not meant to by mistake. It
is not a security boundary: users can still copy files with code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# The location of files on the user's computer, in the browser: uploads from
# it and "Download to local", e.g. "browser:///report.csv".
COMPUTER_URL = "browser:///"

_KEYS = frozenset({"rule", "src", "dest"})


def computer_url(name: str) -> str:
    """The URL rules see for file ``name`` on the user's computer."""
    return COMPUTER_URL + name


@dataclass(frozen=True)
class _Rule:
    allow: bool
    src: re.Pattern[str]
    dest: re.Pattern[str]


class TransferPolicy:
    """The rules of ``StorageExplorer``'s ``policy`` (see the module docstring).

    URLs are those the explorer shows (``StorageExplorer._url``, e.g. plain
    paths for local files), files copied in another explorer keeping the URL
    they were copied with; files on the Jupyter server's disk (JupyterLab's
    file browser) have their local path, and files on the user's computer
    ``browser:///<name>``. The destination is the item's new location (its
    folder joined with its name). A folder is checked as one item, by its own
    URL, not file by file.

    Raises ValueError for rules that are not of the form {"rule": "allow" or
    "deny", "src": pattern, "dest": pattern}, or patterns that are not
    regular expressions.
    """

    def __init__(self, rules: Sequence[Mapping[str, Any]] | None = None) -> None:
        if rules is None:
            rules = []
        if isinstance(rules, (str, bytes, Mapping)):
            raise ValueError("policy must be a list of rules")
        self.rules = [_rule(i, rule) for i, rule in enumerate(rules)]

    def allows(self, source: str, dest: str) -> bool:
        """Whether a file may go from URL ``source`` to URL ``dest``."""
        for rule in self.rules:
            if rule.src.fullmatch(source) and rule.dest.fullmatch(dest):
                return rule.allow
        return True

    def error(self, source: str, dest: str) -> str | None:
        """None if allowed, else why not, naming both URLs (to tell which
        rule applied)."""
        if self.allows(source, dest):
            return None
        return f"not allowed by the policy ({source} → {dest})"


def _rule(index: int, rule: Any) -> _Rule:
    where = f"policy rule {index}"
    if not isinstance(rule, Mapping):
        raise ValueError(
            f'{where}: must be a dict, e.g. {{"rule": "deny", "src": ".*", "dest": ".*"}}'
        )
    if unknown := set(rule) - _KEYS:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)} (rule, src, dest)")
    if rule.get("rule") not in ("allow", "deny"):
        raise ValueError(
            f'{where}: "rule" must be "allow" or "deny", not {rule.get("rule")!r}'
        )
    patterns = []
    for key in ("src", "dest"):
        pattern = rule.get(key, ".*")
        if not isinstance(pattern, str):
            raise ValueError(f"{where}: {key!r} must be a regular expression (a str)")
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(
                f"{where}: {key!r} is not a regular expression: {exc}"
            ) from exc
    return _Rule(rule["rule"] == "allow", *patterns)
