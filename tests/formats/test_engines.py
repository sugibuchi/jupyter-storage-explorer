"""Engines (formats/engine.py, PythonEngine in formats/python.py, the others
in the plugins): which are offered, in which order, which views an item, and
the explorer's choice of one."""

from __future__ import annotations

import importlib

import pytest
import traitlets
from all_actions import all_actions
from explorers import make, path_of
from jupyter_storage_explorer_databricks_support import DatabricksConnect

from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer._explorer.states import ExplorerStates
from jupyter_storage_explorer.formats import (
    Csv,
    DeltaLake,
    Engine,
    Markdown,
    Parquet,
    PythonPackage,
    packages,
)
from jupyter_storage_explorer.formats.actions import code, view
from jupyter_storage_explorer.formats.packages import DeltaLake as DeltaLakePackage
from jupyter_storage_explorer.formats.python import PythonEngine


class Installed(PythonPackage):
    package = "pytest"
    import_name = "pytest"


class Missing(PythonPackage):
    package = "not-a-package"
    import_name = "not_a_package"


INSTALLED = (Installed(),)


def engine(key, requirements=INSTALLED):
    return type(
        f"{key}Engine",
        (Engine,),
        {"key": key, "label": key.title(), "requirements": requirements},
    )


def viewer(fmt, engine_, check=None):
    """A view action of ``fmt`` and ``engine_``."""

    @view(format=fmt, engine=engine_, check=check)
    def viewing(fmt, ctx, options, limits):
        return None

    return viewing


def coder(fmt, engine_):
    """A code action of ``fmt`` and ``engine_``."""

    @code(format=fmt, engine=engine_, label="Load")
    def coding(fmt, ctx, options):
        return ""

    return coding


class TestEngine:
    def test_packages_all_needed(self):
        assert engine("a").is_installed()
        assert not engine("b", (Installed(), Missing())).is_installed()

    def test_none_needed(self):
        assert engine("e", ()).is_installed()
        assert PythonEngine.is_installed()

    def test_dotted_import_names(self):
        # "databricks.connect": a missing parent is not installed, not an error.
        assert DatabricksConnect().is_installed() in (True, False)

    def test_one_probe_at_a_time(self, monkeypatch):
        # Views are read in worker threads, and two threads clearing the
        # import caches at once can raise a KeyError in one of them: probes
        # clear them holding a lock.
        held = []
        monkeypatch.setattr(
            importlib,
            "invalidate_caches",
            lambda: held.append(packages._probing.locked()),
        )
        assert Installed().is_installed()
        assert held == [True]


class TestOrder:
    def keys(self, actions, preference=None):
        return [
            e.key for e in ActionChain(actions, engine_preference=preference).engines
        ]

    def test_default_polars_then_pandas(self):
        # Then the others by key: dask, duckdb (pyspark is not installed).
        assert self.keys(all_actions()) == ["polars", "pandas", "dask", "duckdb"]

    def test_preference_then_the_others_by_key(self):
        actions = [viewer(Csv, engine(k)) for k in ("zeta", "alpha", "mid")]
        assert self.keys(actions, ["mid"]) == ["mid", "alpha", "zeta"]
        assert self.keys(actions, []) == ["alpha", "mid", "zeta"]

    def test_only_installed_engines_that_view(self):
        actions = [
            viewer(Csv, engine("viewer")),
            viewer(Csv, engine("absent", (Missing(),))),
            coder(Csv, engine("coder")),
        ]
        # Listed but not installed: left out; code only: no engine to choose.
        assert self.keys(actions, ["absent", "viewer"]) == ["viewer"]

    def test_unknown_engine_key(self):
        with pytest.raises(ValueError, match=r"unknown engines \['polar'\]"):
            ActionChain(all_actions(), engine_preference=["polar"])


class TestWhichEngineViews:
    chain = ActionChain(all_actions())

    @pytest.fixture
    def item(self, make_item):
        return make_item("/a.csv", b"a\n")

    def test_the_engine_chosen(self, item):
        assert self.chain.engine_for(Parquet(), item, "pandas") == "pandas"
        assert self.chain.engine_for(Parquet(), item, "polars") == "polars"

    def test_built_in_views_for_formats_the_engine_does_not_handle(self, item):
        assert self.chain.engine_for(Markdown(), item, "polars") is None

    def test_no_fallback_to_another_engine(self, item, monkeypatch):
        # Polars handles Delta tables, but needs deltalake: pandas, which
        # does not handle them, is not used instead.
        monkeypatch.setattr(DeltaLakePackage, "is_installed", lambda self: False)
        with pytest.raises(LookupError):
            self.chain.engine_for(DeltaLake(), item, "polars")

    def test_no_fallback_for_an_item_it_does_not_do(self, make_item):
        refusing = viewer(
            Csv, engine("picky"), check=lambda fmt, ctx, options: ctx.name != "b.csv"
        )
        chain = ActionChain([refusing, viewer(Csv, PythonEngine)])
        a, b = make_item("/a.csv", b""), make_item("/b.csv", b"")
        assert chain.engine_for(Csv(), a, "picky") == "picky"
        with pytest.raises(LookupError):
            chain.engine_for(Csv(), b, "picky")
        assert chain.viewers(Csv(), a) == ["picky", None]
        assert chain.viewers(Csv(), b) == [None]

    def test_viewers(self, item):
        assert self.chain.viewers(Csv(), item) == [
            "polars",
            "pandas",
            "dask",
            "duckdb",
        ]
        assert self.chain.viewers(Markdown(), item) == [None]


class TestExplorer:
    def test_engines_and_the_first_chosen(self, local):
        assert local._engines == [
            {"key": "polars", "label": "Polars"},
            {"key": "pandas", "label": "pandas"},
            {"key": "dask", "label": "Dask"},
            {"key": "duckdb", "label": "DuckDB"},
        ]
        assert local._engine == "polars"

    def test_preference(self, tmp_path):
        explorer = make(str(tmp_path), engine_preference=["pandas"])
        assert explorer._engine == "pandas"

    def test_choice_remembered(self, tmp_path):
        states = ExplorerStates(tmp_path / "states.json")
        first = make(str(tmp_path), states=states)
        assert states.engine is None  # the default is no choice
        first._engine = "pandas"
        assert ExplorerStates(tmp_path / "states.json").engine == "pandas"
        assert make(str(tmp_path), states=states)._engine == "pandas"

    def test_unknown_choice(self, local):
        with pytest.raises(traitlets.TraitError, match="unknown engine"):
            local._engine = "spark"

    def test_preview_with_the_engine_chosen(self, local):
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path})
        assert (local._preview["engine"], local._preview["engine_label"]) == (
            "polars",
            "Polars",
        )
        assert "query" in local._preview  # the data browser
        # Another engine: the preview open is viewed again with it.
        local._engine = "pandas"
        assert local._preview["engine"] == "pandas"
        assert "query" in local._preview  # the data browser, on pandas
        query = next(iter(local._queries.values()))
        assert query.implementation.is_pandas()

    def test_preview_as(self, local):
        local._engine = "pandas"
        path = path_of(local, "data.parquet")
        local.message({"type": "preview", "path": path, "engine": "polars"})
        assert local._preview["engine"] == "polars"
        local.message(
            {"type": "preview", "path": path, "format": "parquet", "engine": None}
        )
        assert "with the built-in views" in local._preview["error"]

    def test_menu_info(self, local):
        reply = local.request(
            {"type": "menu_info", "rid": 1, "path": path_of(local, "data.parquet")}
        )
        assert reply["view"] == {"format": "parquet", "engine": "polars"}
        assert [v["label"] for v in reply["views"]] == [
            "Parquet (Polars)",
            "Parquet (pandas)",
            "Parquet (Dask)",
            "Parquet (DuckDB)",
        ]
        assert {(r["title"], r["engine"]) for r in reply["recipes"]} >= {
            ("Load as LazyFrame", "Polars"),
            ("Load as DataFrame", "pandas"),
            ("Load as DataFrame", "Dask"),
            ("Load as relation", "DuckDB"),
        }
        text = local.request(
            {"type": "menu_info", "rid": 2, "path": path_of(local, "notes.txt")}
        )
        assert text["view"] == {"format": "text", "engine": None}  # the built-in view
        assert [v["label"] for v in text["views"]] == ["Text"]

    def test_not_viewable_with_the_engine_chosen(self, local, monkeypatch):
        def cannot(self, fmt, ctx, engine):
            raise LookupError(engine)

        # As when the engine chosen handles the format, but cannot view it.
        monkeypatch.setattr(type(local._actions), "engine_for", cannot)
        path = path_of(local, "data.parquet")
        local._selected = [path]
        assert local._selected_format == {
            "path": path,
            "format": "",
        }  # no Preview button
        reply = local.request({"type": "menu_info", "rid": 1, "path": path})
        assert reply["view"] is None  # "Preview Parquet" disabled
        local.message({"type": "preview", "path": path})
        assert 'choose another engine in "Preview as"' in local._preview["error"]
