"""The plugins' READMEs keep one layout (docs/plugin-development-guide.md, "The
README"): Installation with the full extra's libraries, Prerequisites, and
Plugin options with examples for StorageExplorer and launcher.py."""

from __future__ import annotations

import dataclasses
import importlib.util
import pathlib
import re
import tomllib

import pytest

from jupyter_storage_explorer import StorageExplorer, StorageExplorerPluginOptions
from jupyter_storage_explorer.util import DESCRIPTION

ROOT = pathlib.Path(__file__).parents[1]
PLUGINS = sorted((ROOT / "plugins").glob("*-support"))


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


def test_option_tables_up_to_date(capsys):
    # Written from the options' descriptions by docs/scripts/option_tables.py.
    spec = importlib.util.spec_from_file_location(
        "option_tables", ROOT / "docs" / "scripts" / "option_tables.py"
    )
    option_tables = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(option_tables)
    stale = option_tables.main(check=True)
    assert stale == 0, (
        f"{capsys.readouterr().out}run: uv run docs/scripts/option_tables.py"
    )


def test_the_explorers_options_described():
    # The plugins' are checked by check_plugin, in their tests.
    models = [StorageExplorerPluginOptions] + [
        a.options_model for a in StorageExplorer.default_actions()
    ]
    for model in models:
        for field in dataclasses.fields(model):
            assert DESCRIPTION in field.metadata, f"{model.__qualname__}.{field.name}"


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


@pytest.mark.parametrize(
    "path",
    [
        ROOT / "README.md",
        ROOT / "launcher" / "README.md",
        ROOT / "plugins" / "README.md",
    ]
    + [p / "README.md" for p in PLUGINS],
    ids=lambda p: p.parent.name,
)
def test_no_links_to_sections_of_the_same_page(path):
    # PyPI shows these READMEs, but gives their headings no anchors.
    text = path.read_text(encoding="utf-8")
    assert re.findall(r"\]\(#[^)]*\)", text) == []


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
