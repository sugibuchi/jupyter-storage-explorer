"""Actions (formats/actions.py): the decorators, ``register_actions``, and
how explorers use actions (``ActionChain``)."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._explorer.supports import ActionChain
from jupyter_storage_explorer.formats import (
    Csv,
    Engine,
    FormatSupport,
    Parquet,
    PythonPackage,
    SupportOptions,
    TextView,
    ViewLimits,
    secret_dict_field,
    secret_field,
)
from jupyter_storage_explorer.formats.actions import (
    CodeAction,
    ViewAction,
    code,
    register_actions,
    view,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

LIMITS = ViewLimits()


class Duck(Engine):
    """An engine needing no package: always installed."""

    key = "duck"
    label = "Duck"
    requirements = ()


class MissingPackage(PythonPackage):
    package = "not-a-package"
    import_name = "not_a_package"


@dataclasses.dataclass(frozen=True, kw_only=True)
class DuckOptions(SupportOptions):
    threads: int = 1
    config: Mapping[str, Any] | None = secret_dict_field(
        default=None, secret_keys=["token"]
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class WidgetOptions(DuckOptions):
    rows: int = 10


@code(format=Csv, engine=Duck, name="Load as a duck")
def csv_code(fmt, ctx, options: DuckOptions):
    return f"duck.read({ctx.path!r}, threads={options.threads})"


@view(format=Csv, engine=Duck, code=csv_code)
def csv_view(fmt, ctx, options: DuckOptions, limits):
    return TextView(text=f"threads={options.threads}")


@view(format=Csv, engine=Duck, name="Widget for {format}")
def csv_widget(fmt, ctx, options: WidgetOptions, limits):
    return TextView(text=f"rows={options.rows}")


def text_of(view):
    return view.text


class TestDecorators:
    def test_fields(self):
        assert isinstance(csv_view, ViewAction)
        assert isinstance(csv_code, CodeAction)
        assert csv_view.name == "View CSV"
        assert csv_widget.name == "Widget for CSV"
        assert csv_view.options_model is DuckOptions
        assert csv_view.code is csv_code
        assert csv_view.library == "duck"

    def test_called_as_the_function(self, make_item):
        item = make_item("/a.csv", b"")
        assert (
            csv_code(Csv(), item, DuckOptions(threads=2))
            == "duck.read('/a.csv', threads=2)"
        )

    def test_options_without_annotation(self):
        @view(format=Csv, engine=None)
        def plain(fmt, ctx, options, limits):
            return TextView(text="")

        assert plain.options_model is SupportOptions
        assert plain.library == "python"

    @pytest.mark.parametrize(
        "function",
        [
            lambda fmt, ctx, options: None,
            lambda fmt, ctx, options, limits, more: None,
            lambda fmt, ctx, options, *limits: None,
            lambda fmt, ctx, options, limits, **more: None,
        ],
    )
    def test_fixed_positional_parameters(self, function):
        with pytest.raises(TypeError, match="takes 4 positional parameters"):
            view(format=Csv, engine=Duck)(function)

    def test_keyword_only_parameters_with_defaults(self):
        @view(format=Csv, engine=Duck)
        def fine(fmt, ctx, options, limits, *, debug=False):
            return TextView(text="")

        assert fine.name == "View CSV"

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"format": str}, "format must be a DataFormat class"),
            ({"engine": "duck"}, "engine must be an Engine class or None"),
            ({"requires": [MissingPackage()]}, "requires must be a tuple"),
            ({"check": True}, "check must be callable"),
            ({"name": "View {library}"}, r"name may hold only \{format\}"),
        ],
    )
    def test_arguments_checked(self, arguments, message):
        with pytest.raises(TypeError, match=message):
            view(**{"format": Csv, "engine": Duck, **arguments})(
                lambda fmt, ctx, options, limits: None
            )

    def test_unresolved_options_annotation(self):
        with pytest.raises(TypeError, match="import its class at run time"):

            @view(format=Csv, engine=Duck)
            def broken(fmt, ctx, options: NotImported, limits):  # noqa: F821
                return TextView(text="")

    def test_options_annotation_of_another_type(self):
        with pytest.raises(TypeError, match="SupportOptions subclass"):

            @view(format=Csv, engine=Duck)
            def broken(fmt, ctx, options: dict, limits):
                return TextView(text="")

    def test_code_of_another_pair(self):
        with pytest.raises(TypeError, match="another format or engine"):
            view(format=Parquet, engine=Duck, code=csv_code)(
                lambda fmt, ctx, options, limits: None
            )

    def test_code_taking_options_the_view_has_not(self):
        @code(format=Csv, engine=Duck, name="Widget code")
        def widget_code(fmt, ctx, options: WidgetOptions):
            return ""

        with pytest.raises(TypeError, match="neither DuckOptions nor one of its bases"):

            @view(format=Csv, engine=Duck, name="Other", code=widget_code)
            def other(fmt, ctx, options: DuckOptions, limits):
                return TextView(text="")

    def test_code_taking_a_base_of_the_views_options(self):
        @view(format=Csv, engine=Duck, name="Wide", code=csv_code)
        def wide(fmt, ctx, options: WidgetOptions, limits):
            return TextView(text="")

        assert wide.code is csv_code


class TestRegister:
    def test_in_order(self):
        assert register_actions(csv_widget, csv_view, csv_code) == (
            csv_widget,
            csv_view,
            csv_code,
        )

    def test_not_an_action(self):
        with pytest.raises(TypeError, match="decorate it with @view or @code"):
            register_actions(lambda fmt, ctx, options, limits: None)

    def test_two_actions_of_one_name(self):
        @view(format=Csv, engine=Duck)
        def again(fmt, ctx, options, limits):
            return TextView(text="")

        with pytest.raises(ValueError, match="two actions named 'View CSV'"):
            register_actions(csv_view, csv_code, again)

    def test_one_name_for_a_view_and_a_code(self):
        @code(format=Csv, engine=Duck, name="View CSV")
        def named_as_the_view(fmt, ctx, options):
            return ""

        assert register_actions(csv_view, csv_code, named_as_the_view)

    def test_one_name_of_other_pairs(self):
        @view(format=Parquet, engine=Duck)
        def parquet(fmt, ctx, options, limits):
            return TextView(text="")

        @view(format=Csv, engine=None)
        def python(fmt, ctx, options, limits):
            return TextView(text="")

        assert register_actions(csv_view, csv_code, parquet, python)

    def test_code_not_registered(self):
        with pytest.raises(ValueError, match="its code csv_code is not registered"):
            register_actions(csv_view)

    def test_options_of_one_type_shared(self):
        # WidgetOptions has DuckOptions' fields: the same ones.
        assert register_actions(csv_view, csv_code, csv_widget)

    @pytest.mark.parametrize(
        "field",
        [
            dataclasses.field(default="1"),  # another type
            secret_field(default=1),  # a secret here only
        ],
    )
    def test_options_differing(self, field):
        clash = dataclasses.make_dataclass(
            "Clash",
            [("threads", int if field.default == 1 else str, field)],
            bases=(SupportOptions,),
            frozen=True,
            kw_only=True,
        )

        @view(format=Csv, engine=Duck, name="Clashing")
        def clashing(fmt, ctx, options, limits):
            return TextView(text="")

        clashing = dataclasses.replace(clashing, options_model=clash)
        with pytest.raises(
            ValueError, match="option 'threads' of CSV with duck differs"
        ):
            register_actions(csv_view, csv_code, clashing)

    def test_secret_keys_differing(self):
        @dataclasses.dataclass(frozen=True, kw_only=True)
        class OtherSecrets(SupportOptions):
            config: Mapping[str, Any] | None = secret_dict_field(
                default=None, secret_keys=["password"]
            )

        # A class of a function's own: annotations resolve in the module only.
        @view(format=Csv, engine=Duck, name="Other secrets")
        def other(fmt, ctx, options, limits):
            return TextView(text="")

        other = dataclasses.replace(other, options_model=OtherSecrets)
        with pytest.raises(ValueError, match="option 'config'"):
            register_actions(csv_view, csv_code, other)


class TestChain:
    def test_first_view_is_the_default(self, make_item):
        chain = ActionChain([csv_widget, csv_view, csv_code])
        view_ = chain.view(Csv(), make_item("/a.csv", b""), LIMITS, "duck")
        assert text_of(view_) == "rows=10"

    def test_a_check_refusing_leaves_it_to_the_next(self, make_item):
        @view(format=Csv, engine=Duck, name="Refusing", check=lambda *args: False)
        def refusing(fmt, ctx, options, limits):
            raise AssertionError("not called")

        chain = ActionChain([refusing, csv_view, csv_code])
        assert text_of(chain.view(Csv(), make_item("/a.csv", b""), LIMITS, "duck")) == (
            "threads=1"
        )

    def test_check_gets_the_options(self, make_item):
        seen = []

        @view(
            format=Csv,
            engine=Duck,
            name="Checking",
            check=lambda fmt, ctx, options: seen.append(options) or True,
        )
        def checking(fmt, ctx, options: DuckOptions, limits):
            return TextView(text="")

        chain = ActionChain([checking], {"duck": {"csv": {"threads": 3}}})
        chain.view(Csv(), make_item("/a.csv", b""), LIMITS, "duck")
        assert seen == [DuckOptions(threads=3)]

    def test_not_installed(self, make_item):
        @view(format=Csv, engine=Duck, name="Missing", requires=(MissingPackage(),))
        def missing(fmt, ctx, options, limits):
            raise AssertionError("not called")

        chain = ActionChain([missing, csv_view, csv_code])
        assert chain.of(Csv(), make_item("/a.csv", b"")) == [csv_view]

    def test_options_by_pair_for_each_class(self, make_item):
        options = {"duck": {"*": {"threads": 2}, "csv": {"rows": 5}}}
        chain = ActionChain([csv_widget, csv_view, csv_code], options)
        location = make_item("/a.csv", b"").location
        assert chain.options_of(csv_view, location) == DuckOptions(threads=2)
        assert chain.options_of(csv_widget, location) == WidgetOptions(
            threads=2, rows=5
        )

    def test_unknown_options_of_the_pair(self):
        # rows is WidgetOptions': not an option of the pair without it.
        with pytest.raises(ValueError, match=r"unknown options \['rows'\]"):
            ActionChain([csv_view, csv_code], {"duck": {"csv": {"rows": 5}}})

    def test_recipes_of_every_code_action(self, make_item):
        @code(format=Csv, engine=Duck, name="Load eagerly")
        def eager(fmt, ctx, options):
            return "eager"

        chain = ActionChain([csv_view, csv_code, eager])
        recipes = chain.recipes(Csv(), make_item("/a.csv", b""))
        assert [(r.title, r.code) for r in recipes] == [
            ("Load as a duck", "duck.read('/a.csv', threads=1)"),
            ("Load eagerly", "eager"),
        ]

    def test_a_code_action_failing(self, make_item):
        @code(format=Csv, engine=Duck, name="Failing")
        def failing(fmt, ctx, options):
            raise ValueError("no code")

        chain = ActionChain([failing, csv_code])
        recipes = chain.recipes(Csv(), make_item("/a.csv", b""))
        assert [(r.title, r.code, r.error) for r in recipes] == [
            ("Failing", "", "no code"),
            ("Load as a duck", "duck.read('/a.csv', threads=1)", ""),
        ]

    def test_two_sources_of_one_name(self):
        @view(format=Csv, engine=Duck)
        def mine(fmt, ctx, options, limits):
            return TextView(text="")

        with pytest.raises(ValueError, match="two actions named 'View CSV'"):
            ActionChain([mine, csv_view, csv_code])

    def test_with_supports_of_the_former_interface(self, make_item):
        old = type(
            "OldDuck",
            (FormatSupport,),
            {
                "format": Csv,
                "engine": Duck,
                "view": lambda self, *args: TextView(text="old"),
            },
        )
        chain = ActionChain([old, csv_view, csv_code])
        item = make_item("/a.csv", b"")
        assert text_of(chain.view(Csv(), item, LIMITS, "duck")) == "old"
        assert chain.of(Csv(), item)[1] is csv_view

    def test_a_support_given_replaces_the_engines_default(self, make_item):
        # Its view, named as the default view, hides the action of that name;
        # its recipes replace the engine's code actions.
        old = type(
            "OldDuck",
            (FormatSupport,),
            {
                "format": Csv,
                "engine": Duck,
                "view": lambda self, *args: TextView(text="old"),
                "recipe": lambda self, *args: {"Load the old way": "old"},
            },
        )
        chain = ActionChain([old, csv_view, csv_widget, csv_code])
        item = make_item("/a.csv", b"")
        assert chain.view_names(Csv(), item, "duck") == ["View CSV", "Widget for CSV"]
        assert text_of(chain.view(Csv(), item, LIMITS, "duck", "View CSV")) == "old"
        recipes = chain.recipes(Csv(), item)
        assert [(r.title, r.code) for r in recipes] == [("Load the old way", "old")]


class TestExplorer:
    def test_actions_given_first(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_widget, csv_view, csv_code])
        assert "duck" in [e["key"] for e in explorer._engines]
        item = explorer._detect_now("/a.csv", memfs)
        assert text_of(explorer._supports.view(Csv(), item.ctx, LIMITS, "duck")) == (
            "rows=10"
        )

    def menu_views(self, explorer, path):
        item = explorer._detect_now(path, explorer._fs)
        info = explorer._menu_info(item.formats, [], item.ctx, "duck")
        return [(v["engine"], v.get("action"), v["label"]) for v in info["views"]]

    def test_views_by_name_in_the_menu(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_widget, csv_view, csv_code])
        duck = [v for v in self.menu_views(explorer, "/a.csv") if v[0] == "duck"]
        # An entry per view of an engine with several, the first its default.
        assert duck == [
            ("duck", "Widget for CSV", "CSV (Duck): Widget for CSV"),
            ("duck", "View CSV", "CSV (Duck): View CSV"),
        ]

    def test_one_view_in_the_menu(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_view, csv_code])
        duck = [v for v in self.menu_views(explorer, "/a.csv") if v[0] == "duck"]
        assert duck == [("duck", None, "CSV (Duck)")]

    def test_preview_by_name(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, preview_panel="open", actions=[csv_widget, csv_view, csv_code]
        )
        explorer._open_preview("/a.csv", "csv", "duck", "View CSV")
        assert explorer._preview["action"] == "View CSV"
        assert explorer._preview["sections"][0]["text"] == "threads=1"
        explorer._open_preview("/a.csv", "csv", "duck")
        assert explorer._preview["sections"][0]["text"] == "rows=10"

    def test_preview_by_a_name_not_viewing_it(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, preview_panel="open", actions=[csv_widget, csv_view, csv_code]
        )
        explorer._open_preview("/a.csv", "csv", "duck", "Gone")
        assert explorer._preview["error"] == "a.csv cannot be viewed by 'Gone'"
