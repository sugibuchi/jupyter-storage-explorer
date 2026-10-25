"""Actions (formats/actions.py): the decorators, ``register_actions``, and
how explorers use actions (``ActionChain``)."""

from __future__ import annotations

import dataclasses
import inspect
from typing import TYPE_CHECKING, Any

import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer.formats import (
    ActionOptions,
    Csv,
    Engine,
    Parquet,
    PythonPackage,
    TextView,
    ViewLimits,
)
from jupyter_storage_explorer.formats.actions import (
    CodeAction,
    ViewAction,
    code,
    register_actions,
    view,
)
from jupyter_storage_explorer.formats.python import PythonEngine
from jupyter_storage_explorer.util import secret_dict_field, secret_field

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
class DuckOptions(ActionOptions):
    threads: int = 1
    config: Mapping[str, Any] | None = secret_dict_field(
        default=None, secret_keys=["token"]
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class WidgetOptions(DuckOptions):
    rows: int = 10


@code(format=Csv, engine=Duck, label="Load as a duck")
def csv_code(fmt, ctx, options: DuckOptions):
    return f"duck.read({ctx.path!r}, threads={options.threads})"


@view(format=Csv, engine=Duck, code=csv_code)
def csv_view(fmt, ctx, options: DuckOptions, limits):
    return TextView(text=f"threads={options.threads}")


@view(format=Csv, engine=Duck, label="Widget for {format}")
def csv_widget(fmt, ctx, options: WidgetOptions, limits):
    return TextView(text=f"rows={options.rows}")


def text_of(view):
    return view.text


class TestDecorators:
    def test_fields(self):
        assert isinstance(csv_view, ViewAction)
        assert isinstance(csv_code, CodeAction)
        assert csv_view.label == "View as CSV (Duck)"  # the default
        assert csv_widget.label == "Widget for CSV"
        assert csv_view.options_model is DuckOptions
        assert csv_view.code is csv_code
        assert csv_view.engine.key == "duck"

    def test_ids(self):
        # Each action's own number, also after dataclasses.replace.
        assert len({csv_view.id, csv_code.id, csv_widget.id}) == 3
        copy = dataclasses.replace(csv_view)
        assert copy.id not in (csv_view.id, csv_code.id, csv_widget.id)

    def test_label_with_the_engine(self):
        @view(format=Csv, engine=Duck, label="{format} in a widget ({engine})")
        def widget(fmt, ctx, options, limits):
            return TextView(text="")

        assert widget.label == "CSV in a widget (Duck)"

    def test_reads_as_the_function(self):
        # Its name, docstring and signature, for help(), IDEs and errors.
        assert csv_view.__name__ == "csv_view"
        assert csv_view.__wrapped__ is csv_view.function
        assert list(inspect.signature(csv_view).parameters) == [
            "fmt",
            "ctx",
            "options",
            "limits",
        ]

    def test_called_as_the_function(self, make_item):
        item = make_item("/a.csv", b"")
        assert (
            csv_code(Csv(), item, DuckOptions(threads=2))
            == "duck.read('/a.csv', threads=2)"
        )

    def test_options_without_annotation(self):
        @view(format=Csv, engine=PythonEngine)
        def plain(fmt, ctx, options, limits):
            return TextView(text="")

        assert plain.options_model is ActionOptions
        assert plain.engine.key == "python"

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

        assert fine.label == "View as CSV (Duck)"

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"format": str}, "format must be a DataFormat class"),
            ({"engine": "duck"}, "engine must be an Engine class"),
            ({"requires": [MissingPackage()]}, "requires must be a tuple"),
            ({"check": True}, "check must be callable"),
            (
                {"label": "View {library}"},
                r"label may hold only \{format\} and \{engine\}",
            ),
            ({"label": None}, "label must be a str"),
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
        with pytest.raises(TypeError, match="ActionOptions subclass"):

            @view(format=Csv, engine=Duck)
            def broken(fmt, ctx, options: dict, limits):
                return TextView(text="")

    def test_code_of_another_pair(self):
        with pytest.raises(TypeError, match="another format or engine"):
            view(format=Parquet, engine=Duck, code=csv_code)(
                lambda fmt, ctx, options, limits: None
            )

    def test_code_taking_options_the_view_has_not(self):
        @code(format=Csv, engine=Duck, label="Widget code")
        def widget_code(fmt, ctx, options: WidgetOptions):
            return ""

        with pytest.raises(TypeError, match="neither DuckOptions nor one of its bases"):

            @view(format=Csv, engine=Duck, label="Other", code=widget_code)
            def other(fmt, ctx, options: DuckOptions, limits):
                return TextView(text="")

    def test_code_taking_a_base_of_the_views_options(self):
        @view(format=Csv, engine=Duck, label="Wide", code=csv_code)
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

    def test_two_actions_of_one_label(self):
        @view(format=Csv, engine=Duck)
        def again(fmt, ctx, options, limits):
            return TextView(text="")

        with pytest.raises(
            ValueError, match=r"two actions labelled 'View as CSV \(Duck\)'"
        ):
            register_actions(csv_view, csv_code, again)

    def test_one_label_for_a_view_and_a_code(self):
        @code(format=Csv, engine=Duck, label="View as CSV (Duck)")
        def labelled_as_the_view(fmt, ctx, options):
            return ""

        assert register_actions(csv_view, csv_code, labelled_as_the_view)

    def test_one_label_of_other_pairs(self):
        @view(format=Parquet, engine=Duck)
        def parquet(fmt, ctx, options, limits):
            return TextView(text="")

        @view(format=Csv, engine=PythonEngine)
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
            bases=(ActionOptions,),
            frozen=True,
            kw_only=True,
        )

        @view(format=Csv, engine=Duck, label="Clashing")
        def clashing(fmt, ctx, options, limits):
            return TextView(text="")

        clashing = dataclasses.replace(clashing, options_model=clash)
        with pytest.raises(
            ValueError, match="option 'threads' of CSV with duck differs"
        ):
            register_actions(csv_view, csv_code, clashing)

    def test_secret_keys_differing(self):
        @dataclasses.dataclass(frozen=True, kw_only=True)
        class OtherSecrets(ActionOptions):
            config: Mapping[str, Any] | None = secret_dict_field(
                default=None, secret_keys=["password"]
            )

        # A class of a function's own: annotations resolve in the module only.
        @view(format=Csv, engine=Duck, label="Other secrets")
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
        @view(format=Csv, engine=Duck, label="Refusing", check=lambda *args: False)
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
            label="Checking",
            check=lambda fmt, ctx, options: seen.append(options) or True,
        )
        def checking(fmt, ctx, options: DuckOptions, limits):
            return TextView(text="")

        chain = ActionChain([checking], {"duck": {"csv": {"threads": 3}}})
        chain.view(Csv(), make_item("/a.csv", b""), LIMITS, "duck")
        assert seen == [DuckOptions(threads=3)]

    def test_not_installed(self, make_item):
        @view(format=Csv, engine=Duck, label="Missing", requires=(MissingPackage(),))
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
        @code(format=Csv, engine=Duck, label="Load eagerly")
        def eager(fmt, ctx, options):
            return "eager"

        chain = ActionChain([csv_view, csv_code, eager])
        recipes = chain.recipes(Csv(), make_item("/a.csv", b""))
        assert [(r.title, r.code) for r in recipes] == [
            ("Load as a duck", "duck.read('/a.csv', threads=1)"),
            ("Load eagerly", "eager"),
        ]

    def test_a_code_action_failing(self, make_item):
        @code(format=Csv, engine=Duck, label="Failing")
        def failing(fmt, ctx, options):
            raise ValueError("no code")

        chain = ActionChain([failing, csv_code])
        recipes = chain.recipes(Csv(), make_item("/a.csv", b""))
        assert [(r.title, r.code, r.error) for r in recipes] == [
            ("Failing", "", "no code"),
            ("Load as a duck", "duck.read('/a.csv', threads=1)", ""),
        ]

    def test_two_sources_of_one_label(self):
        @view(format=Csv, engine=Duck)
        def mine(fmt, ctx, options, limits):
            return TextView(text="")

        with pytest.raises(
            ValueError, match=r"two actions labelled 'View as CSV \(Duck\)'"
        ):
            ActionChain([mine, csv_view, csv_code])


class TestExplorer:
    def test_actions_given_first(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_widget, csv_view, csv_code])
        assert "duck" in [e["key"] for e in explorer._engines]
        item = explorer._detect_now("/a.csv", memfs)
        assert text_of(explorer._actions.view(Csv(), item.ctx, LIMITS, "duck")) == (
            "rows=10"
        )

    def menu_views(self, explorer, path):
        item = explorer._detect_now(path, explorer._fs)
        info = explorer._menu_info(item.formats, [], item.ctx, "duck")
        return [(v["engine"], v.get("action"), v["label"]) for v in info["views"]]

    def test_views_by_label_in_the_menu(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_widget, csv_view, csv_code])
        duck = [v for v in self.menu_views(explorer, "/a.csv") if v[0] == "duck"]
        # An entry per view of an engine with several, by its id, labelled
        # with its label; the first is the default.
        assert duck == [
            ("duck", csv_widget.id, "Widget for CSV"),
            ("duck", csv_view.id, "View as CSV (Duck)"),
        ]

    def test_one_view_in_the_menu(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(fs=memfs, actions=[csv_view, csv_code])
        duck = [v for v in self.menu_views(explorer, "/a.csv") if v[0] == "duck"]
        assert duck == [("duck", None, "CSV (Duck)")]

    def test_preview_by_id(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, preview_panel="open", actions=[csv_widget, csv_view, csv_code]
        )
        explorer._open_preview("/a.csv", "csv", "duck", csv_view.id)
        assert explorer._preview["action"] == csv_view.id
        assert explorer._preview["sections"][0]["text"] == "threads=1"
        explorer._open_preview("/a.csv", "csv", "duck")
        assert explorer._preview["sections"][0]["text"] == "rows=10"

    def test_preview_by_an_id_not_viewing_it(self, memfs):
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, preview_panel="open", actions=[csv_widget, csv_view, csv_code]
        )
        explorer._open_preview("/a.csv", "csv", "duck", csv_code.id)  # not a view
        assert explorer._preview["error"] == (
            f"a.csv cannot be viewed by action {csv_code.id}"
        )

    def test_the_pages_id_taken_only_as_an_integer(self, memfs):
        # The default view for anything else the page sends.
        memfs.pipe_file("/a.csv", b"a\n1\n")
        explorer = StorageExplorer(
            fs=memfs, preview_panel="open", actions=[csv_widget, csv_view, csv_code]
        )
        for sent in (str(csv_view.id), True, None, [csv_view.id]):
            content = {
                "type": "preview",
                "path": "/a.csv",
                "format": "csv",
                "engine": "duck",
                "action": sent,
            }
            explorer._on_custom_msg(explorer, content, None)
            assert explorer._preview["sections"][0]["text"] == "rows=10"
