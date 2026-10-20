"""formats/support.py: which support does what, and the supports' options
(format_options)."""

from __future__ import annotations

import dataclasses
from typing import get_args

import polars as pl
import pytest
from items import local_item

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.filesystems import AbfsLocation
from jupyter_storage_explorer.formats import (
    Capability,
    Csv,
    DeltaLake,
    FormatSupport,
    Parquet,
    PythonPackage,
    QueryView,
    SupportOptions,
    ViewLimits,
    default_formats,
    default_supports,
    secret_dict_field,
    secret_field,
)
from jupyter_storage_explorer.formats.support import SupportChain
from jupyter_storage_explorer.formats.supports import (
    CsvByPandas,
    CsvByPolars,
    DeltaLakeByPolars,
    DeltaLakeByPolarsOptions,
    ExcelByPolars,
    ExcelByPolarsOptions,
    FsspecOptions,
    PandasOptions,
    ParquetByPolars,
    PolarsOptions,
    TextByFsspec,
    TextByPython,
)
from jupyter_storage_explorer.formats.utils import DEFAULT_FORMATS, DEFAULT_SUPPORTS
from jupyter_storage_explorer.formats.view import InstallView

LIMITS = ViewLimits(max_display_rows=2)


class Missing(PythonPackage):
    package = "not-a-package"
    import_name = "not_a_package"


def support(fmt=Csv, engine=None, capabilities=("view",), **methods):
    """A support class of ``capabilities``, its methods ``methods``."""
    attributes = {"format": fmt, "engine": engine, "capabilities": capabilities}
    return type("Fake", (FormatSupport,), {**attributes, **methods})


# Where an item is, for options that depend on it.
ACCOUNT_A = AbfsLocation(account_name="a", container_name="c", path="x")
ACCOUNT_B = AbfsLocation(account_name="b", container_name="c", path="x")
ACCOUNT_KEYS = {"a": "key-a", "b": "key-b"}


def options_by_class(format_options=None, location=ACCOUNT_A):
    """The default supports' options for ``location``, by class, made from
    ``format_options``."""
    chain = SupportChain(DEFAULT_SUPPORTS, format_options)
    return {type(s): chain.options_of(s, location) for s in chain.supports}


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
        expected = PolarsOptions(storage_options={"y": 2})
        assert [chain.options_of(s, ACCOUNT_A) for s in chain.supports] == [
            expected,
            expected,
        ]

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

    def test_option_names(self):
        assert SupportOptions.option_names() == frozenset()
        assert PolarsOptions.option_names() == {
            "storage_options",
            "credential_provider",
        }
        assert DeltaLakeByPolarsOptions.option_names() >= {
            "use_pyarrow",
            "storage_options",
        }

    def test_not_a_support(self):
        with pytest.raises(TypeError, match="not a FormatSupport"):
            SupportChain([Csv])


class TestOptionsByLocation:
    """Options may be a function of the item's location."""

    def format_options(self):
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
            options = options_by_class(self.format_options(), location)
            assert options[CsvByPolars].storage_options == {"account_key": key}
            # A format's dict over the function for all formats.
            delta = options[DeltaLakeByPolars]
            assert (delta.storage_options, delta.use_pyarrow) == (
                {"account_key": key},
                True,
            )

    def test_a_format_function_over_the_dict_for_all(self):
        options = options_by_class(
            {
                "polars": {
                    "*": {"storage_options": {"region": "eu"}, "use_pyarrow": False},
                    "delta": lambda location: {"use_pyarrow": True},
                }
            }
        )
        delta = options[DeltaLakeByPolars]
        assert (delta.storage_options, delta.use_pyarrow) == ({"region": "eu"}, True)

    def test_unknown_options_returned(self):
        chain = SupportChain(
            DEFAULT_SUPPORTS, {"polars": {"csv": lambda location: {"use_pyarrow": 1}}}
        )
        [csv] = [s for s in chain.supports if isinstance(s, CsvByPolars)]
        with pytest.raises(ValueError, match=r"\(.*abfs://c@a.*\): unknown options"):
            chain.options_of(csv, ACCOUNT_A)

    def test_format_names_checked_at_once(self):
        with pytest.raises(ValueError, match="unknown format"):
            SupportChain(DEFAULT_SUPPORTS, {"polars": {"parq": lambda location: {}}})

    def test_the_items_location(self, make_item):
        seen = []
        recording = support(
            engine=Missing,
            capabilities=("recipe",),
            recipe=lambda self, fmt, ctx, options: seen.append(options) or {},
        )
        recording.options_model = FsspecOptions
        chain = SupportChain(
            [recording],
            {
                "not-a-package": {
                    "*": lambda location: {"storage_options": {"at": location.url}}
                }
            },
        )
        chain.recipes(Csv(), make_item("/a.csv", b"", location=ACCOUNT_B))
        assert seen == [FsspecOptions(storage_options={"at": ACCOUNT_B.url})]


@dataclasses.dataclass(frozen=True, kw_only=True)
class SecretOptions(SupportOptions):
    password: str | None = secret_field(default=None)
    storage_options: dict | None = secret_dict_field(
        default=None, secret_keys=["shared_key"]
    )
    version: int = 1
    engine: object = None


class TestSecrets:
    """Options marked secret never reach generated code (``code_value``)."""

    def test_secret_field(self):
        options = SecretOptions(password="hunter2")
        assert options.code_value("password") is None
        assert "hunter2" not in repr(options)  # nor tracebacks and logs

    def test_secret_keys_at_any_depth(self):
        options = SecretOptions(
            storage_options={
                "shared_key": "s1",
                "account_name": "acct",
                "client_kwargs": {"shared_key": "s2", "endpoint_url": "http://e"},
            }
        )
        assert options.code_value("storage_options") == {
            "account_name": "acct",
            "client_kwargs": {"endpoint_url": "http://e"},
        }

    def test_credential_like_keys_left_out_anyway(self):
        # Not declared, but named like a credential.
        options = SecretOptions(storage_options={"sas_token": "t", "shared_key": "k"})
        assert options.code_value("storage_options") is None  # nothing left

    def test_plain_values(self):
        options = SecretOptions(version=2, engine=object())
        assert options.code_value("version") == 2
        assert options.code_value("engine") is None  # not plain data

    def test_metadata_kept(self):
        [field] = [
            f for f in dataclasses.fields(SecretOptions) if f.name == "storage_options"
        ]
        assert field.metadata["secret_keys"] == ("shared_key",)

    def test_predefined_storage_options(self, make_item):
        chain = SupportChain(
            DEFAULT_SUPPORTS,
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
