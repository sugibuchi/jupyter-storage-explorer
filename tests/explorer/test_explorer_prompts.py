"""Prompts before views (``ViewWithPrompt``): asked in the preview panel and
in view tabs, answered, cancelled, and given again on a reload."""

from __future__ import annotations

import polars as pl
import pytest
from explorers import make

from jupyter_storage_explorer._explorer.view_tab import ViewTab
from jupyter_storage_explorer.formats import (
    FormatSupport,
    QueryView,
    Text,
    TextView,
    ViewLimits,
    ViewWithChoice,
    ViewWithConfirmation,
    ViewWithInput,
)

# What the prompts did: "closed", and the answers' views made.
EVENTS: list[str] = []


class Asking(FormatSupport):
    """Asks how to show a text file's name; before the built-in views."""

    format = Text

    def view(self, fmt, ctx, options, limits):
        def make_view(case):
            if case is None:
                raise ValueError("no such case")
            EVENTS.append(f"made {case}")
            return TextView(text=getattr(ctx.name, case)())

        prompt = ViewWithChoice(
            message="Which case?",
            choices={"Upper": "upper", "Lower": "lower", "Broken": None},
            factory=make_view,
            style="button",
        )
        prompt.on_close(lambda view: EVENTS.append("closed"))
        return prompt


class Confirming(FormatSupport):
    """Data, once confirmed."""

    format = Text

    def view(self, fmt, ctx, options, limits):
        def read():
            EVENTS.append("read")
            return QueryView(data=pl.DataFrame({"a": [1, 2]}))

        return ViewWithConfirmation(message="Read it?", factory=read)


@pytest.fixture(autouse=True)
def events():
    EVENTS.clear()
    yield EVENTS


def explorer_of(memfs, support=Asking):
    memfs.pipe_file("/data/a.txt", b"a")
    memfs.pipe_file("/data/b.txt", b"b")
    return make("/data", fs=memfs, supports=[support])


def preview(explorer, path="/data/a.txt"):
    explorer.message({"type": "preview", "path": path})
    return explorer._preview


def answer(explorer, **content):
    prompt = explorer._preview["sections"][0]["prompt"]
    path = explorer._preview["path"]
    explorer.message(
        {"type": "preview_answer", "path": path, "prompt": prompt, **content}
    )
    return explorer._preview


class TestPreview:
    def test_the_prompt_shown(self, memfs):
        [section] = preview(explorer_of(memfs))["sections"]
        assert {k: v for k, v in section.items() if k != "prompt"} == {
            "kind": "choice",
            "title": "",
            "note": "",
            "message": "Which case?",
            "button": "View",
            # The labels only: the values and the function stay in the kernel.
            "choices": ["Upper", "Lower", "Broken"],
            "style": "button",
            "default": None,
            "with_cancel": False,
        }

    def test_answered(self, memfs, events):
        explorer = explorer_of(memfs)
        preview(explorer)
        [section] = answer(explorer, value="Upper")["sections"]
        assert (section["kind"], section["text"]) == ("text", "A.TXT")
        assert events == ["made upper"]  # the prompt stays open with its view
        preview(explorer, "/data/b.txt")
        assert events == ["made upper", "closed"]

    def test_cancelled(self, memfs, events):
        explorer = explorer_of(memfs)
        preview(explorer)
        [section] = answer(explorer, cancel=True)["sections"]
        assert section == {"kind": "notice", "text": "Not previewed", "again": True}
        assert events == ["closed"]

    def test_an_answer_to_another_prompt_is_ignored(self, memfs, events):
        explorer = explorer_of(memfs)
        shown = preview(explorer)
        explorer.message(
            {
                "type": "preview_answer",
                "path": "/data/a.txt",
                "prompt": -1,
                "value": "Upper",
            }
        )
        assert explorer._preview == shown
        assert events == []

    def test_the_answers_function_failing(self, memfs, events):
        explorer = explorer_of(memfs)
        preview(explorer)
        assert answer(explorer, value="Broken")["error"] == "no such case"
        assert events == ["closed"]

    def test_no_such_label(self, memfs, events):
        explorer = explorer_of(memfs)
        preview(explorer)
        assert "not one of the choices" in answer(explorer, value="Title")["error"]

    def test_a_reload_asks_nothing(self, memfs, events):
        explorer = explorer_of(memfs, Confirming)
        preview(explorer)
        assert answer(explorer)["query"]["columns"]
        reply = explorer.request(
            {"type": "query_reload", "rid": 1, "path": "/data/a.txt"}
        )
        assert "error" not in reply
        assert events == ["read", "read"]  # confirmed again, as the first time


class TestViewTab:
    @staticmethod
    def loaded(explorer):
        return [c for c, _ in explorer.sent if c.get("type") == "view_tab"]

    def test_asked_in_the_tab(self, memfs, events):
        explorer = explorer_of(memfs)
        explorer.request({"type": "view_tab", "rid": 1, "path": "/data/a.txt"})
        [asking] = self.loaded(explorer)
        assert asking["asking"] is True
        tab = explorer._view_tabs[asking["model_id"]]
        assert isinstance(tab, ViewTab)
        assert tab.view["kind"] == "choice"
        tab._on_custom_msg(
            tab,
            {"type": "answer", "prompt": tab.view["prompt"], "value": "Lower"},
            None,
        )
        # The view in a widget of its own, for the same tab.
        _, viewed = self.loaded(explorer)
        assert viewed["load_id"] == asking["load_id"]
        assert "asking" not in viewed
        view = explorer._view_tabs[viewed["model_id"]]
        assert view.view["text"] == "a.txt"
        # The tab lets the prompt's widget go: the prompt stays with the view.
        explorer.message({"type": "view_tab_closed", "model_id": asking["model_id"]})
        assert events == ["made lower"]
        explorer.message({"type": "view_tab_closed", "model_id": viewed["model_id"]})
        assert events == ["made lower", "closed"]

    def test_cancelled_in_the_tab(self, memfs, events):
        explorer = explorer_of(memfs)
        explorer.request({"type": "view_tab", "rid": 1, "path": "/data/a.txt"})
        [asking] = self.loaded(explorer)
        tab = explorer._view_tabs[asking["model_id"]]
        tab._on_custom_msg(
            tab, {"type": "answer", "prompt": tab.view["prompt"], "cancel": True}, None
        )
        assert tab.view == {"kind": "notice", "text": "Not viewed", "again": False}
        assert events == ["closed"]

    def test_an_error_after_the_answer(self, memfs):
        explorer = explorer_of(memfs)
        explorer.request({"type": "view_tab", "rid": 1, "path": "/data/a.txt"})
        [asking] = self.loaded(explorer)
        tab = explorer._view_tabs[asking["model_id"]]
        tab._on_custom_msg(
            tab,
            {"type": "answer", "prompt": tab.view["prompt"], "value": "Broken"},
            None,
        )
        assert tab.view == {"kind": "error", "text": "no such case"}
        assert len(self.loaded(explorer)) == 1  # the tab keeps the widget


class TestViews:
    def test_choice_checks(self):
        def make_view(value):
            return TextView(text=str(value))

        with pytest.raises(ValueError, match="at least one"):
            ViewWithChoice(message="", choices={}, factory=make_view)
        with pytest.raises(ValueError, match="style must be"):
            ViewWithChoice(message="", choices={"a": 1}, factory=make_view, style="x")
        with pytest.raises(ValueError, match="not one of the labels"):
            ViewWithChoice(message="", choices={"a": 1}, factory=make_view, default="b")

    def test_the_function_must_make_a_view(self):
        prompt = ViewWithConfirmation(message="", factory=lambda: "text")
        with pytest.raises(TypeError, match="returned no View"):
            prompt.answer()

    def test_input(self):
        prompt = ViewWithInput(message="", factory=lambda text: TextView(text=text))
        assert prompt.answer("abc").text == "abc"
        assert prompt.answer(None).text == ""


def test_the_first_part_said_in_the_data_browser(memfs):
    # polars on a storage it cannot read itself: the file's first KB, lazy.
    memfs.pipe_file("/data/large.csv", b"a\n" + b"1\n" * 3000)
    explorer = make(
        "/data", fs=memfs, view_limits=ViewLimits(max_whole_file_bytes=1024)
    )
    preview(explorer, "/data/large.csv")
    first = answer(explorer, value="Its first 1 KB")
    assert first["query"]["mode"]["partial"] is True
    preview(explorer, "/data/large.csv")
    whole = answer(explorer, value="The whole file (5.9 KB)")
    assert whole["query"]["mode"]["partial"] is False
