"""formats/support.py: which support does what, and the supports' options
(format_options)."""

from __future__ import annotations

import dataclasses
from typing import get_args

import polars as pl
import pytest
from items import local_item

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import (
    DEFAULT_FORMATS,
    DEFAULT_SUPPORTS,
    Capability,
    Csv,
    DeltaLake,
    FormatSupport,
    InstallView,
    Parquet,
    PythonPackage,
    QueryView,
    SupportChain,
    SupportOptions,
    ViewLimits,
    default_formats,
    default_supports,
)
from jupyter_storage_explorer.formats.supports import (
    CsvByPandas,
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    PandasOptions,
    ParquetByPolars,
    PolarsOptions,
    TextByFsspec,
    TextByPython,
)

LIMITS = ViewLimits(max_display_rows=2)


class Missing(PythonPackage):
    package = "not-a-package"
    import_name = "not_a_package"


def support(fmt=Csv, engine=None, capabilities=("view",), **methods):
    """A support class of ``capabilities``, its methods ``methods``."""
    attributes = {"format": fmt, "engine": engine, "capabilities": capabilities}
    return type("Fake", (FormatSupport,), {**attributes, **methods})


def options_by_class(format_options=None):
    """The default supports' options, by class, made from ``format_options``."""
    chain = SupportChain(DEFAULT_SUPPORTS, format_options)
    return {type(s): o for s, o in zip(chain.supports, chain.options, strict=True)}


def test_default_formats_are_new_objects():
    first, second = default_formats(), default_formats()
    assert [type(f) for f in first] == list(DEFAULT_FORMATS)
    assert all(a is not b for a, b in zip(first, second, strict=True))


@pytest.mark.parametrize("cls", DEFAULT_SUPPORTS)
def test_capabilities_are_the_methods_implemented(cls):
    # The rule FormatSupport states for subclasses, kept by the defaults.
    implemented = {
        method
        for method in get_args(Capability)
        if getattr(cls, method) is not getattr(FormatSupport, method)
    }
    assert implemented == set(cls.capabilities)


class TestOptions:
    def test_all_formats_then_one(self):
        options = options_by_class(
            {
                "polars": {
                    "*": {"storage_options": {"a": 1}},
                    "delta": {"storage_options": {"b": 2}, "use_pyarrow": True},
                }
            }
        )
        assert options[CsvByPolars] == PolarsOptions(storage_options={"a": 1})
        assert options[ParquetByPolars].storage_options == {"a": 1}
        delta = options[DeltaLakeByPolars]
        assert isinstance(delta, DeltaLakeByPolarsOptions)
        assert (delta.storage_options, delta.use_pyarrow) == ({"b": 2}, True)
        # Only the options a support's model has: Excel's code reads with fsspec.
        assert options[ExcelByPolars] == ExcelByPolarsOptions()
        assert options[CsvByPandas] == PandasOptions()  # pandas' own
        assert options[TextByPython] == SupportOptions()  # none

    def test_by_library(self):
        options = options_by_class(
            {"fsspec": {"text": {"storage_options": {"anon": True}}}}
        )
        assert options[TextByFsspec].storage_options == {"anon": True}

    @pytest.mark.parametrize(
        ("options", "error"),
        [
            ({"polar": {}}, r"unknown library 'polar'; choose from \[.*'polars'"),
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
            SupportChain(DEFAULT_SUPPORTS, options)

    def test_objects_get_options_as_classes(self):
        # Supports carry no options: objects given are used as they are, and
        # get theirs as classes do.
        given = CsvByPolars()
        chain = SupportChain(
            [given, CsvByPolars], {"polars": {"*": {"storage_options": {"y": 2}}}}
        )
        assert chain.supports[0] is given
        assert chain.options == [PolarsOptions(storage_options={"y": 2})] * 2

    def test_options_reach_the_methods(self, make_item):
        seen = []

        @dataclasses.dataclass(frozen=True, kw_only=True)
        class DuckOptions(SupportOptions):
            threads: int = 1

        duck = support(
            engine=Missing,
            capabilities=("recipe",),
            recipe=lambda self, fmt, ctx, options: seen.append(options) or {},
        )
        duck.options_model = DuckOptions
        chain = SupportChain([duck], {"not-a-package": {"*": {"threads": 4}}})
        chain.recipes(Csv(), make_item("/a.csv", b""))
        assert seen == [DuckOptions(threads=4)]

    def test_not_a_support(self):
        with pytest.raises(TypeError, match="not a FormatSupport"):
            SupportChain([Csv])

    def test_formats_of_the_explorer(self):
        # A format the explorer has, which no support's format names.
        avro = type("Avro", (Csv,), {"name": "avro"})
        explorer = StorageExplorer(
            fs=None,
            formats=[avro()],
            format_options={"polars": {"avro": {}}},
        )
        assert explorer._formats[0].name == "avro"


class TestChain:
    def view(self, chain, item):
        return chain.view(Csv(), item, LIMITS)

    def test_first_installed_views(self, make_item):
        missing = support(engine=Missing, view=lambda *a, **k: "missing")
        first = support(view=lambda *a, **k: "first")
        second = support(view=lambda *a, **k: "second")
        chain = SupportChain([missing(), first(), second()])
        assert self.view(chain, make_item("/a.csv", b"")) == "first"

    def test_not_supported_tries_the_next(self, make_item):
        def refuse(self, *args, **kwargs):
            raise self.NotSupported

        chain = SupportChain(
            [support(view=refuse)(), support(view=lambda *a, **k: "next")()]
        )
        assert self.view(chain, make_item("/a.csv", b"")) == "next"

    def test_only_its_capabilities(self, make_item):
        # A method not in capabilities is never called.
        chain = SupportChain(
            [
                support(capabilities=(), view=lambda *a, **k: "not listed")(),
                support(view=lambda *a, **k: "listed")(),
            ]
        )
        assert self.view(chain, make_item("/a.csv", b"")) == "listed"

    def test_install_hint(self, make_item, monkeypatch):
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        hint = self.view(SupportChain(default_supports()), make_item("/a.csv", b"a\n"))
        assert isinstance(hint, InstallView)
        assert hint.options == [["polars"], ["pandas"]]

    def test_none_can_view(self, make_item):
        with pytest.raises(ValueError, match="cannot be viewed as CSV"):
            self.view(SupportChain([]), make_item("/a.csv", b""))

    def test_format_subclasses(self, tmp_path):
        """A subclass of a format is viewed by its supports."""
        tsv = type("Tsv", (Csv,), {"name": "tsv"})
        path = tmp_path / "a.tsv"
        path.write_text("a\tb\n1\t2\n")
        view = SupportChain(default_supports()).view(tsv(), local_item(path), LIMITS)
        assert isinstance(view, QueryView)
        assert view.data.collect().columns == ["a", "b"]

    def test_recipes_of_every_support_installed_or_not(self, make_item, monkeypatch):
        monkeypatch.setattr(PythonPackage, "is_installed", lambda self: False)
        chain = SupportChain(default_supports())
        recipes = chain.recipes(Csv(), make_item("/a.csv", b"a\n"))
        assert [(r.requirements[0].package, r.title) for r in recipes] == [
            ("polars", "Load as DataFrame"),
            ("pandas", "Load as DataFrame"),
            ("pyspark", "Load as DataFrame"),
        ]

    def test_recipes_by_title(self, make_item):
        several = support(
            capabilities=("recipe",),
            recipe=lambda *a, **k: {"Load lazily": "lazy", "Load eagerly": "eager"},
        )
        recipes = SupportChain([several()]).recipes(Csv(), make_item("/a.csv", b""))
        assert [(r.title, r.code) for r in recipes] == [
            ("Load lazily", "lazy"),
            ("Load eagerly", "eager"),
        ]

    def test_recipes_name_their_packages(self, make_item, memfs):
        memfs.pipe_file("/t/_delta_log/00000000000000000000.json", b"{}")
        chain = SupportChain(default_supports())
        recipes = chain.recipes(DeltaLake(), make_item("/t"))
        packages = [[r.package for r in recipe.requirements] for recipe in recipes]
        assert packages == [
            ["polars", "deltalake"],
            ["polars", "deltalake"],
            ["pyspark", "delta-spark"],
        ]

    def test_query_view(self, tmp_path):
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1, 2]}).write_parquet(path)
        view = SupportChain(default_supports()).view(
            Parquet(), local_item(path), LIMITS
        )
        assert view.data.collect()["a"].to_list() == [1, 2]


class TestExplorer:
    """``supports`` are tried before the explorer's ``default_supports()``."""

    def test_given_first(self, make_item, mem_explorer):
        duck = support(
            fmt=Parquet,
            engine=Missing,
            capabilities=("recipe",),
            recipe=lambda *a, **k: {"Load as a duck": "duck"},
        )
        explorer = StorageExplorer(fs=mem_explorer._fs, supports=[duck])
        recipes = explorer._supports.recipes(Parquet(), make_item("/a.parquet", b""))
        assert (recipes[0].title, recipes[0].code) == ("Load as a duck", "duck")
        # and the defaults': polars (lazily and eagerly), pandas, pyspark.
        assert len(recipes) == 5

    def test_a_library_given_replaces_the_default_code(self, make_item):
        explorer = StorageExplorer(fs=None, supports=[CsvByPolars()])
        recipes = explorer._supports.recipes(Csv(), make_item("/a.csv", b"a\n"))
        # Its recipes replace the default CsvByPolars': one each.
        assert [r.requirements[0].package for r in recipes] == [
            "polars",
            "pandas",
            "pyspark",
        ]

    def test_defaults_overridden(self):
        class Explorer(StorageExplorer):
            @staticmethod
            def default_supports():
                return [CsvByPolars]

        explorer = Explorer(fs=None)
        assert [type(s) for s in explorer._supports.supports] == [CsvByPolars]
