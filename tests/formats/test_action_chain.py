"""_explorer/actions.py: which action does what to an item, and the actions'
options (engine_options), with the plugins' actions and small ones of the
tests'."""

from __future__ import annotations

import dataclasses

import polars as pl
import pytest
from all_actions import ALL_ACTIONS, NO_PLUGINS, all_actions, installed_only
from items import local_item
from jupyter_storage_explorer_dask_support import csv_view as csv_by_dask
from jupyter_storage_explorer_duckdb_support import csv_view as csv_by_duckdb
from jupyter_storage_explorer_pandas_support import CsvByPandasOptions
from jupyter_storage_explorer_pandas_support import csv_view as csv_by_pandas
from jupyter_storage_explorer_polars_support import (
    CsvByPolarsOptions,
    DeltaLakeByPolarsOptions,
    ExcelByPolarsOptions,
    csv_view,
    delta_view,
    excel_view,
    parquet_view,
)

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer.filesystems import AbfsLocation, S3Location
from jupyter_storage_explorer.formats import (
    ActionOptions,
    Csv,
    DeltaLake,
    Engine,
    Excel,
    Image,
    Json,
    JsonLines,
    Markdown,
    Parquet,
    PythonPackage,
    QueryView,
    Text,
    ViewLimits,
)
from jupyter_storage_explorer.formats.actions import code, view
from jupyter_storage_explorer.formats.defaults import DEFAULT_ACTIONS, DEFAULT_FORMATS
from jupyter_storage_explorer.formats.python import (
    FsspecOptions,
    PythonEngine,
    text_code,
    text_view,
)

LIMITS = ViewLimits(max_display_rows=2)


class MissingPackage(PythonPackage):
    package = "not-a-package"
    import_name = "not_a_package"


class Missing(Engine):
    """An engine whose package is not installed."""

    key = "not-a-package"
    label = "Missing"
    requirements = (MissingPackage(),)


class Duck(Engine):
    """An engine needing no package: always installed."""

    key = "duck"
    label = "Duck"
    requirements = ()


@dataclasses.dataclass(frozen=True, kw_only=True)
class ThreadsOptions(ActionOptions):
    threads: int = 1


def viewer(result, *, name, fmt=Csv, engine=PythonEngine, check=None):
    """A view action returning ``result`` as it is."""

    @view(format=fmt, engine=engine, label=name, check=check)
    def viewing(fmt, ctx, options, limits):
        return result

    return viewing


def coder(result, *, name, fmt=Csv, engine=PythonEngine):
    """A code action returning ``result`` as it is."""

    @code(format=fmt, engine=engine, label=name)
    def coding(fmt, ctx, options):
        return result

    return coding


# Where an item is, for options that depend on it.
ACCOUNT_A = AbfsLocation(account_name="a", container_name="c", path="x")
ACCOUNT_B = AbfsLocation(account_name="b", container_name="c", path="x")
ACCOUNT_KEYS = {"a": "key-a", "b": "key-b"}


def on_s3(key):
    """A location polars reads itself, for its code: not the memory filesystem's."""
    return S3Location(bucket="b", key=key)


def options_by_action(engine_options=None, location=ACCOUNT_A):
    """The options of all the actions for ``location``, by action, made from
    ``engine_options``."""
    chain = ActionChain(ALL_ACTIONS, engine_options)
    return {a: chain.options_of(a, location) for a in chain.actions}


def test_formats_are_the_actions():
    # One of each, in the actions' order: those given first.
    avro = type("Avro", (Csv,), {"name": "avro"})
    # The actions' formats, then those given (the standard ones, as the
    # explorer gives them, detected even without an action).
    chain = ActionChain(
        [viewer("", name="Avro", fmt=avro), *DEFAULT_ACTIONS],
        formats=DEFAULT_FORMATS,
    )
    assert [type(f) for f in chain.formats] == [
        avro,
        Json,
        Markdown,
        Text,
        Image,
        DeltaLake,
        Parquet,
        Csv,
        Excel,
        JsonLines,
    ]
    # Each chain has its own: formats keep what detection finds.
    other = ActionChain(ALL_ACTIONS).formats
    assert all(f not in other for f in chain.formats)


def test_one_format_class_per_name():
    # A name is what engine_options, previews and menus choose a format by.
    other_csv = type("OtherCsv", (Csv,), {})  # still named "csv"
    with pytest.raises(ValueError, match="format 'csv' is defined twice"):
        ActionChain(
            [viewer("", name="Other", fmt=other_csv), *DEFAULT_ACTIONS],
            formats=DEFAULT_FORMATS,
        )
    tsv = type("Tsv", (Csv,), {"name": "tsv"})
    assert ActionChain(
        [viewer("", name="TSV", fmt=tsv), *DEFAULT_ACTIONS], formats=DEFAULT_FORMATS
    )


def test_not_an_action():
    with pytest.raises(TypeError, match=r"not an action: .*decorate it with @view"):
        ActionChain([Csv])


class TestOptions:
    def test_all_formats_then_one(self):
        options = options_by_action(
            {
                "polars": {
                    "*": {"storage_options": {"a": 1}},
                    "delta": {"storage_options": {"b": 2}, "use_pyarrow": True},
                }
            }
        )
        assert options[csv_view] == CsvByPolarsOptions(storage_options={"a": 1})
        assert options[parquet_view].storage_options == {"a": 1}
        delta = options[delta_view]
        assert isinstance(delta, DeltaLakeByPolarsOptions)
        assert (delta.storage_options, delta.use_pyarrow) == ({"b": 2}, True)
        # Only the options an action's class has: Excel's code reads with fsspec.
        assert options[excel_view] == ExcelByPolarsOptions()
        assert options[csv_by_pandas] == CsvByPandasOptions()  # pandas' own
        assert options[text_code] == FsspecOptions()  # "python"'s

    def test_by_engine(self):
        # PythonEngine's actions take "python"'s.
        options = options_by_action(
            {"python": {"text": {"storage_options": {"anon": True}}}}
        )
        assert options[text_code].storage_options == {"anon": True}

    def test_python_is_no_engine_to_choose(self):
        with pytest.raises(ValueError, match=r"unknown engines \['python'\]"):
            ActionChain(all_actions(), engine_preference=["python"])

    @pytest.mark.parametrize(
        ("options", "error"),
        [
            ({"polar": {}}, r"unknown engine 'polar'; choose from \[.*'polars'"),
            ({"polars": {"parq": {}}}, r"\['polars'\]\['parq'\]: unknown format"),
            (
                {"polars": {"*": {"storge_options": 1}}},
                r"unknown options \['storge_options'\]",
            ),
            # Delta's option, not CSV's.
            (
                {"polars": {"csv": {"use_pyarrow": True}}},
                r"unknown options \['use_pyarrow'\]",
            ),
            ({"pyspark": {"*": {"anything": 1}}}, "unknown options"),
            ({"polars": {"*": 1}}, "must be a dict of options"),
            ({"polars": 1}, "must be a dict of format names"),
        ],
    )
    def test_unknown(self, options, error):
        with pytest.raises(ValueError, match=error):
            ActionChain(ALL_ACTIONS, options)

    def test_options_reach_the_actions(self, make_item):
        seen = []

        @code(format=Csv, engine=Duck, label="Record")
        def recording(fmt, ctx, options: ThreadsOptions):
            seen.append(options)
            return ""

        chain = ActionChain([recording], {"duck": {"*": {"threads": 4}}})
        chain.recipes(Csv(), make_item("/a.csv", b""))
        assert seen == [ThreadsOptions(threads=4)]


class TestOptionsByLocation:
    """Options may be a function of the item's location."""

    def engine_options(self):
        return {
            "polars": {
                "*": lambda location: {
                    "storage_options": {
                        "account_key": ACCOUNT_KEYS[location.account_name]
                    }
                },
                "delta": {"use_pyarrow": True},
            }
        }

    def test_by_account(self):
        for location, key in ((ACCOUNT_A, "key-a"), (ACCOUNT_B, "key-b")):
            options = options_by_action(self.engine_options(), location)
            assert options[csv_view].storage_options == {"account_key": key}
            # A format's dict over the function for all formats.
            delta = options[delta_view]
            assert (delta.storage_options, delta.use_pyarrow) == (
                {"account_key": key},
                True,
            )

    def test_a_format_function_over_the_dict_for_all(self):
        options = options_by_action(
            {
                "polars": {
                    "*": {"storage_options": {"region": "eu"}, "use_pyarrow": False},
                    "delta": lambda location: {"use_pyarrow": True},
                }
            }
        )
        delta = options[delta_view]
        assert (delta.storage_options, delta.use_pyarrow) == ({"region": "eu"}, True)

    def test_unknown_options_returned(self):
        chain = ActionChain(
            ALL_ACTIONS, {"polars": {"csv": lambda location: {"use_pyarrow": 1}}}
        )
        with pytest.raises(ValueError, match=r"\(.*abfs://c@a.*\): unknown options"):
            chain.options_of(csv_view, ACCOUNT_A)

    def test_format_names_checked_at_once(self):
        with pytest.raises(ValueError, match="unknown format"):
            ActionChain(ALL_ACTIONS, {"polars": {"parq": lambda location: {}}})

    def test_the_items_location(self, make_item):
        seen = []

        @code(format=Csv, engine=Duck, label="Record")
        def recording(fmt, ctx, options: FsspecOptions):
            seen.append(options)
            return ""

        chain = ActionChain(
            [recording],
            {"duck": {"*": lambda location: {"storage_options": {"at": location.url}}}},
        )
        chain.recipes(Csv(), make_item("/a.csv", b"", location=ACCOUNT_B))
        assert seen == [FsspecOptions(storage_options={"at": ACCOUNT_B.url})]


class TestSecretsInCode:
    def test_predefined_storage_options(self, make_item):
        chain = ActionChain(
            ALL_ACTIONS,
            {"pandas": {"*": {"storage_options": {"account_key": "k", "anon": True}}}},
        )
        [recipe] = [
            r
            for r in chain.recipes(Csv(), make_item("/a.csv", b"a\n"))
            if r.requirements[0].package == "pandas"
        ]
        assert "storage_options={'anon': True}" in recipe.code
        assert "account_key" not in recipe.code

    def test_formats_of_the_explorer(self):
        # The format of an action given, detected too, and its options.
        avro = type("Avro", (Csv,), {"name": "avro"})
        explorer = StorageExplorer(
            fs=None,
            actions=[viewer("", name="Avro", fmt=avro)],
            engine_options={"python": {"avro": {}}},
        )
        assert "avro" in [f.name for f in explorer._formats]


class TestChain:
    def view(self, chain, item):
        """The view by the first engine viewing CSV, else the built-in views."""
        engine = (chain.viewers(Csv(), item) or [None])[0]
        return chain.view(Csv(), item, LIMITS, engine)

    def test_first_installed_views(self, make_item):
        chain = ActionChain(
            [
                viewer("missing", name="Missing", engine=Missing),
                viewer("first", name="First"),
                viewer("second", name="Second"),
            ]
        )
        assert self.view(chain, make_item("/a.csv", b"")) == "first"

    def test_the_first_doing_the_item(self, make_item):
        def only_b(fmt, ctx, options):
            return ctx.name == "b.csv"

        chain = ActionChain(
            [
                viewer("b only", name="B only", check=only_b),
                viewer("any", name="Any"),
            ]
        )
        assert self.view(chain, make_item("/a.csv", b"")) == "any"
        assert self.view(chain, make_item("/b.csv", b"")) == "b only"

    def test_code_is_never_asked_to_view(self, make_item):
        chain = ActionChain([coder("", name="Read"), viewer("viewer", name="View")])
        assert self.view(chain, make_item("/a.csv", b"")) == "viewer"

    def test_errors_are_the_items(self, make_item):
        # Once an action does the item, no other is tried.
        @view(format=Csv, engine=PythonEngine, label="Failing")
        def failing(fmt, ctx, options, limits):
            raise ValueError("broken file")

        chain = ActionChain([failing, viewer("next", name="Next")])
        with pytest.raises(ValueError, match="broken file"):
            self.view(chain, make_item("/a.csv", b""))

    def test_of_lists_the_installed_only(self, make_item, monkeypatch):
        chain = ActionChain(all_actions())
        item = make_item("/a.csv", b"")
        # In the actions' order: the plugins', by key.
        assert chain.of(Csv(), item) == [
            csv_by_dask,
            csv_by_duckdb,
            csv_by_pandas,
            csv_view,
        ]
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        # None of the registered actions can.
        assert chain.of(Csv(), item) == []
        assert not chain.installed(Csv())

    def test_view_without_an_action_is_an_error_of_the_caller(self, make_item):
        # Callers check of() first: none at all is not the item's fault.
        with pytest.raises(RuntimeError, match=r"check viewers\(\) first"):
            self.view(ActionChain([]), make_item("/a.csv", b""))

    def test_a_recipe_failing(self, make_item):
        def failing(engine):
            @code(format=Csv, engine=engine, label="Fail")
            def fail(fmt, ctx, options):
                raise ValueError("no code")

            return fail

        chain = ActionChain(
            [failing(Missing), failing(Duck), coder("code", name="Read")]
        )
        recipes = chain.recipes(Csv(), make_item("/a.csv", b""))
        # Shown in place of its code; the others' still shown. Not installed:
        # not offered.
        assert [(r.title, r.code, r.error) for r in recipes] == [
            ("Read", "code", ""),
            ("Fail", "", "no code"),
        ]

    def test_format_subclasses(self, tmp_path):
        """A subclass of a format is viewed by its actions."""
        tsv = type("Tsv", (Csv,), {"name": "tsv"})
        path = tmp_path / "a.tsv"
        path.write_text("a\tb\n1\t2\n")
        view_ = ActionChain(all_actions()).view(
            tsv(), local_item(path), LIMITS, "polars"
        )
        assert isinstance(view_, QueryView)
        assert view_.data.collect().columns == ["a", "b"]

    def test_recipes_of_the_installed_actions_only(self, make_item, monkeypatch):
        # As for views: no code the kernel could not run.
        chain = ActionChain(all_actions())
        item = make_item("/a.csv", b"a\n", location=on_s3("a.csv"))

        def engines():
            return [r.requirements[0].package for r in chain.recipes(Csv(), item)]

        installed_only(monkeypatch, "polars", "pandas", "pyspark", "pyarrow")
        assert engines() == ["polars", "pandas", "pyspark"]
        installed_only(monkeypatch, "databricks-connect")
        assert engines() == ["databricks-connect"]  # its pyspark is not PySpark's
        installed_only(monkeypatch)
        assert engines() == []

    def test_recipes_name_their_packages(self, make_item, memfs, monkeypatch):
        memfs.pipe_file("/t/_delta_log/00000000000000000000.json", b"{}")
        chain = ActionChain(all_actions())

        def packages():
            recipes = chain.recipes(DeltaLake(), make_item("/t", location=on_s3("t")))
            return [[r.package for r in recipe.requirements] for recipe in recipes]

        installed_only(
            monkeypatch, "polars", "deltalake", "pyspark", "pyarrow", "delta-spark"
        )
        assert packages() == [
            ["polars", "deltalake"],
            ["polars", "deltalake"],
            ["pyspark", "pyarrow", "delta-spark"],
        ]
        installed_only(monkeypatch, "polars", "pyspark", "pyarrow")  # nor Delta Lake's
        assert packages() == []
        installed_only(monkeypatch, "databricks-connect")
        assert packages() == [["databricks-connect"]]  # Databricks has Delta Lake

    def test_query_view(self, tmp_path):
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1, 2]}).write_parquet(path)
        view_ = ActionChain(all_actions()).view(
            Parquet(), local_item(path), LIMITS, "polars"
        )
        assert view_.data.collect()["a"].to_list() == [1, 2]


class TestExplorer:
    """``actions`` are tried before the plugins' and ``default_actions()``."""

    def test_given_first(self, make_item, mem_explorer, monkeypatch):
        duck = coder("duck", name="Load as a duck", fmt=Parquet, engine=Duck)
        explorer = StorageExplorer(fs=mem_explorer._fs, actions=[duck])
        installed_only(monkeypatch, "polars", "pyspark", "pyarrow")
        recipes = explorer._actions.recipes(
            Parquet(), make_item("/a.parquet", b"", location=on_s3("a.parquet"))
        )
        # With the plugins' installed: polars (lazily and eagerly), pyspark;
        # its engine, not among engine_preference's, after polars', by key.
        assert [(r.engine.key, r.title) for r in recipes] == [
            ("polars", "Load as LazyFrame"),
            ("polars", "Load as DataFrame"),
            ("duck", "Load as a duck"),
            ("pyspark", "Load as DataFrame"),
        ]

    def test_defaults_overridden(self):
        class Explorer(StorageExplorer):
            @staticmethod
            def default_actions():
                return [text_view]

        explorer = Explorer(fs=None, plugin_options=NO_PLUGINS)
        assert explorer._actions.actions == [text_view]
