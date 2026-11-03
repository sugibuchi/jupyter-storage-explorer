"""Formats recognised by file names, and given to an explorer without actions:
``DataFormat.name_patterns`` and ``StorageExplorer``'s ``formats``."""

from __future__ import annotations

import re

import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer.formats import DataFormat, Json, Text
from jupyter_storage_explorer.views import TreeView


class NamedJson(Json):
    name = "named-json"
    label = "JSON by name"
    extensions = ()
    name_patterns = (r"settings\.conf", r".*\.manifest")


class TestNamePatterns:
    @pytest.mark.parametrize("path", ["/settings.conf", "/a/app.manifest"])
    def test_matching_names(self, make_item, path):
        assert NamedJson().matches(make_item(path, b"{}"))

    @pytest.mark.parametrize(
        "path", ["/my-settings.conf", "/settings.conf.bak", "/settingsxconf", "/a.json"]
    )
    def test_whole_names_only(self, make_item, path):
        assert not NamedJson().matches(make_item(path, b"{}"))

    @pytest.mark.parametrize("path", ["/Settings.conf", "/a/APP.Manifest"])
    def test_case_matters(self, make_item, path):
        assert not NamedJson().matches(make_item(path, b"{}"))

    def test_case_ignored_by_the_pattern(self, make_item):
        class AnyCase(DataFormat):
            name = "any-case"
            label = "Any case"
            name_patterns = (r"(?i)readme",)

        assert AnyCase().matches(make_item("/README", b""))
        assert AnyCase().matches(make_item("/readme", b""))

    def test_besides_the_extensions(self, make_item):
        class Both(DataFormat):
            name = "both"
            label = "Both"
            extensions = (".both",)
            name_patterns = (r"both_\d+",)

        assert Both().matches(make_item("/a.both", b""))
        assert Both().matches(make_item("/both_12", b""))
        assert not Both().matches(make_item("/both_x", b""))

    def test_extensions_inherited(self, make_item):
        class AlsoNamed(Json):
            name = "also-named"
            label = "Also named"
            name_patterns = (r"settings\.conf",)

        assert AlsoNamed().matches(make_item("/a.json", b"{}"))

    def test_patterns_inherited(self, make_item):
        class Further(NamedJson):
            name = "further"

        assert Further().matches(make_item("/settings.conf", b"{}"))

    def test_never_a_folder(self, memfs, make_item):
        memfs.mkdir("/settings.conf")
        memfs.pipe("/settings.conf/a", b"")
        assert not NamedJson().matches(make_item("/settings.conf"))

    def test_invalid_pattern_refused_when_defined(self):
        with pytest.raises(re.error):

            class Invalid(DataFormat):
                name_patterns = ("(",)

    def test_one_string_refused(self):
        with pytest.raises(TypeError, match="must be a tuple"):

            class Invalid(DataFormat):
                name_patterns = r"settings\.conf"


class TestGivenFormats:
    @pytest.fixture
    def explorer(self, memfs):
        memfs.pipe("/d/settings.conf", b'{"a": 1}')
        memfs.pipe("/d/other.conf", b"a = 1")
        memfs.pipe("/d/plain.json", b'{"b": 2}')
        return StorageExplorer("/d", fs=memfs, formats=[NamedJson])

    def detected(self, explorer, path):
        return explorer._detection(path, explorer._fs).result()

    def test_detected_without_an_action(self, explorer):
        item = self.detected(explorer, "/d/settings.conf")
        assert type(item.formats[0]) is NamedJson
        assert "named-json" in explorer._format_labels

    def test_other_files_keep_their_formats(self, explorer):
        assert self.detected(explorer, "/d/other.conf").formats[0].name == "conf"
        assert self.detected(explorer, "/d/plain.json").formats[0].name == "json"

    def test_has_the_actions_of_its_base(self, explorer):
        item = self.detected(explorer, "/d/settings.conf")
        fmt = item.formats[0]
        view = explorer._actions.view(fmt, item.ctx, explorer._view_limits, None)
        assert isinstance(view, TreeView)
        assert view.value == {"a": 1}
        recipes = explorer._actions.recipes(fmt, item.ctx)
        assert "Load the JSON value" in [r.title for r in recipes]

    def test_one_preview_entry_for_its_views(self, explorer):
        item = self.detected(explorer, "/d/settings.conf")
        info = explorer._menu_info(item.formats, [], item.ctx, None)
        assert info["view"]["format"] == "named-json"
        labels = [entry["label"] for entry in info["views"]]
        assert labels.count(Json.label) == 1
        assert NamedJson.label not in labels

    def test_text_format(self, explorer):
        assert "named-json" in explorer._text_formats

    def test_a_tie_needs_a_higher_priority(self, memfs):
        """Formats of actions come first among those of one priority."""

        class Tied(Text):
            name = "tied"
            label = "Tied"
            name_patterns = (r"special\.csv",)

        class Above(Tied):
            name = "above"
            priority = 1

        memfs.pipe("/d/special.csv", b"a\n1\n")
        for given, name in ((Tied, "csv"), (Above, "above")):
            explorer = StorageExplorer("/d", fs=memfs, formats=[given])
            assert self.detected(explorer, "/d/special.csv").formats[0].name == name

    def test_kept_when_actions_are_reloaded(self, explorer):
        assert NamedJson in [type(f) for f in explorer._chain_of([]).formats]

    def test_a_name_taken_is_refused(self, memfs):
        class Another(Json):
            name = "json"

        with pytest.raises(ValueError, match="json"):
            StorageExplorer("/", fs=memfs, formats=[Another])

    def test_object_refused(self, memfs):
        with pytest.raises(TypeError, match="not a format"):
            StorageExplorer("/", fs=memfs, formats=[NamedJson()])
