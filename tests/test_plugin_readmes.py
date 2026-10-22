"""The plugins' READMEs keep one layout (docs/development-plugin.md, "The
README"): Installation with the full extra's libraries, Prerequisites, and
Plugin options with examples for StorageExplorer and launcher.py."""

from __future__ import annotations

import pathlib
import re
import tomllib

import pytest

PLUGINS = sorted((pathlib.Path(__file__).parents[1] / "plugins").glob("*-support"))


def sections(text: str) -> dict[str, str]:
    """Heading (without its #) -> the text under it, up to the next heading of
    the same or a higher level."""
    found = list(re.finditer(r"^(#+) (.+)$", text, re.MULTILINE))
    out = {}
    for i, m in enumerate(found):
        level = len(m.group(1))
        end = next(
            (n.start() for n in found[i + 1 :] if len(n.group(1)) <= level), len(text)
        )
        out[m.group(2).strip()] = text[m.end() : end]
    return out


@pytest.fixture(params=PLUGINS, ids=lambda p: p.name)
def plugin(request) -> pathlib.Path:
    return request.param


def readme(plugin: pathlib.Path) -> dict[str, str]:
    return sections((plugin / "README.md").read_text(encoding="utf-8"))


def test_the_plugins_are_found():
    assert {p.name for p in PLUGINS} >= {"polars-support", "abfs-support"}


def test_sections_in_order(plugin):
    text = (plugin / "README.md").read_text(encoding="utf-8")
    positions = [
        text.find(f"\n{heading}\n")
        for heading in ("## Installation", "### Prerequisites", "## Plugin options")
    ]
    assert -1 not in positions, positions
    assert positions == sorted(positions)


def test_installation_commands(plugin):
    name = plugin.name.removesuffix("-support")
    install = readme(plugin)["Installation"]
    assert f'pip install "jupyter-storage-explorer[{name}]"' in install
    assert f'pip install "jupyter-storage-explorer[{name}-support]"' in install


def test_the_full_extras_libraries_are_tabled(plugin):
    full = tomllib.loads((plugin / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]["full"]
    libraries = {re.split(r"[<>=!~\[ ;]", requirement)[0] for requirement in full}
    install = readme(plugin)["Installation"]
    rows = re.findall(r"^\| `([\w.-]+)`\s*\|\s*(.+?)\s*\|$", install, re.MULTILINE)
    assert {library for library, _ in rows} == libraries
    # What each is needed for; the engine's (or the storage's) first, mandatory.
    assert rows[0][1].startswith("Mandatory")


def test_prerequisites_say_what_the_environment_provides(plugin):
    assert readme(plugin)["Prerequisites"].strip().startswith("- ")


def test_plugin_options_have_both_examples(plugin):
    options = readme(plugin)["Plugin options"]
    key = plugin.name
    assert re.search(
        rf"```python\nStorageExplorer\(.*plugin_options=\{{\"{key}\"",
        options,
        re.DOTALL,
    )
    assert f'```python\ndef plugin_options():\n    return {{"{key}"' in options
    assert "| `enabled`" in options and "| `priority`" in options
