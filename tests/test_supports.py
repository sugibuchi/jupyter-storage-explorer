"""formats/support.py and utils.py: which support does what, and the
supports' options (format_options)."""

from __future__ import annotations

from typing import get_args

import polars as pl
import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import (
    DEFAULT_FORMATS,
    DEFAULT_SUPPORTS,
    Capability,
    Csv,
    CsvByPandas,
    CsvByPolars,
    DeltaLake,
    DeltaLakeByPolars,
    ExcelByPolars,
    FormatSupport,
    InstallPreview,
    Parquet,
    ParquetByPolars,
    PreviewLimits,
    Requirement,
    SupportChain,
    Text,
    TextByFsspec,
    create_supports,
    default_formats,
    default_supports,
)

LIMITS = PreviewLimits(max_rows=2)


class Missing(Requirement):
    package = "not-a-package"
    import_name = "not_a_package"


def support(fmt=Csv, use=None, capabilities=("preview",), **methods):
    """A support class of ``capabilities``, its methods ``methods``."""
    attributes = {"format": fmt, "use": use, "capabilities": capabilities}
    return type("Fake", (FormatSupport,), {**attributes, **methods})


def by_class(supports):
    return {type(s): s for s in supports}


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
        supports = by_class(
            default_supports(
                {
                    "polars": {
                        "*": {"storage_options": {"a": 1}},
                        "delta": {"storage_options": {"b": 2}, "use_pyarrow": True},
                    }
                }
            )
        )
        assert supports[CsvByPolars].storage_options == {"a": 1}
        assert supports[ParquetByPolars].storage_options == {"a": 1}
        delta = supports[DeltaLakeByPolars]
        assert (delta.storage_options, delta.use_pyarrow) == ({"b": 2}, True)
        # Only the options a support takes: Excel's code reads with fsspec.
        assert not hasattr(supports[ExcelByPolars], "storage_options")
        assert supports[CsvByPandas].storage_options is None  # pandas' own

    def test_by_library(self):
        supports = by_class(
            default_supports({"fsspec": {"text": {"storage_options": {"anon": True}}}})
        )
        assert supports[TextByFsspec].storage_options == {"anon": True}

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
            default_supports(options)

    def test_objects_used_as_they_are(self):
        given = CsvByPolars(storage_options={"x": 1})
        [created, csv] = create_supports(
            [given, CsvByPolars], {"polars": {"*": {"storage_options": {"y": 2}}}}
        )
        assert created is given
        assert given.storage_options == {"x": 1}
        assert csv.storage_options == {"y": 2}

    def test_not_a_support(self):
        with pytest.raises(TypeError, match="not a FormatSupport"):
            create_supports([Csv])

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
    def test_first_installed_previews(self, make_target):
        missing = support(use=Missing, preview=lambda *a: "missing")
        first = support(preview=lambda *a: "first")
        second = support(preview=lambda *a: "second")
        chain = SupportChain([missing(), first(), second()])
        assert chain.preview(Csv(), make_target("/a.csv", b""), LIMITS) == "first"

    def test_not_supported_tries_the_next(self, make_target):
        def refuse(self, *args):
            raise self.NotSupported

        chain = SupportChain(
            [support(preview=refuse)(), support(preview=lambda *a: "next")()]
        )
        assert chain.preview(Csv(), make_target("/a.csv", b""), LIMITS) == "next"

    def test_only_its_jobs(self, make_target):
        # A method not in capabilities is never called.
        chain = SupportChain(
            [
                support(capabilities=(), preview=lambda *a: "not listed")(),
                support(preview=lambda *a: "listed")(),
            ]
        )
        assert chain.preview(Csv(), make_target("/a.csv", b""), LIMITS) == "listed"

    def test_install_hint(self, make_target, monkeypatch):
        monkeypatch.setattr(Requirement, "is_installed", lambda self: False)
        chain = SupportChain(default_supports())
        hint = chain.preview(Csv(), make_target("/a.csv", b"a\n"), LIMITS)
        assert isinstance(hint, InstallPreview)
        assert hint.options == [["polars"], ["pandas"]]
        assert not chain.can_query(Csv())

    def test_none_can_preview(self, make_target):
        with pytest.raises(ValueError, match="cannot be previewed as CSV"):
            SupportChain([]).preview(Csv(), make_target("/a.csv", b""), LIMITS)

    def test_format_subclasses(self, make_target):
        tsv = type("Tsv", (Csv,), {"name": "tsv"})
        chain = SupportChain(default_supports())
        assert chain.can_query(tsv())
        assert not chain.can_query(Text())

    def test_recipes_of_every_support_installed_or_not(self, make_target, monkeypatch):
        monkeypatch.setattr(Requirement, "is_installed", lambda self: False)
        chain = SupportChain(default_supports())
        recipes = chain.recipes(Csv(), make_target("/a.csv", b"a\n"))
        assert [r.requirements[0].package for r in recipes] == [
            "polars",
            "pandas",
            "pyspark",
        ]

    def test_recipes_name_their_packages(self, make_target, memfs):
        memfs.pipe_file("/t/_delta_log/00000000000000000000.json", b"{}")
        chain = SupportChain(default_supports())
        recipes = chain.recipes(DeltaLake(), make_target("/t"))
        packages = [[r.package for r in recipe.requirements] for recipe in recipes]
        assert packages == [["polars", "deltalake"], ["pyspark", "delta-spark"]]

    def test_query(self, tmp_path):
        path = tmp_path / "a.parquet"
        pl.DataFrame({"a": [1, 2]}).write_parquet(path)
        lf = SupportChain(default_supports()).query(Parquet(), str(path), False)
        assert lf.collect()["a"].to_list() == [1, 2]


class TestExplorer:
    """``supports`` are tried before the explorer's ``default_supports()``."""

    def test_given_first(self, make_target, mem_explorer):
        duck = support(
            fmt=Parquet, use=Missing, capabilities=("recipe",), recipe=lambda *a: "duck"
        )
        explorer = StorageExplorer(fs=mem_explorer._fs, supports=[duck])
        recipes = explorer._supports.recipes(Parquet(), make_target("/a.parquet", b""))
        assert recipes[0].code == "duck"
        assert len(recipes) == 4  # and the defaults' polars, pandas, pyspark

    def test_a_library_given_replaces_the_default_code(self, make_target):
        explorer = StorageExplorer(fs=None, supports=[CsvByPolars()])
        recipes = explorer._supports.recipes(Csv(), make_target("/a.csv", b"a\n"))
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
