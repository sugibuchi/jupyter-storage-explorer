"""The icons of the formats' files in the explorer's list (_explorer/icons.py)."""

from __future__ import annotations

import pytest
from all_actions import NO_PLUGINS

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._explorer.actions import ActionChain
from jupyter_storage_explorer._explorer.icons import format_icons
from jupyter_storage_explorer.formats import FILE_ICONS, Csv
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer.formats.defaults import DEFAULT_ACTIONS, DEFAULT_FORMATS
from jupyter_storage_explorer.formats.python import PythonEngine


class TestFileIcons:
    """Each format's file_icon, sent to the frontend by format name; files of
    formats without one get their extension's icon there (icons.js)."""

    SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>'

    def avro(self, icon):
        return type("Avro", (Csv,), {"name": "avro", "file_icon": icon})()

    def explorer(self, icon):
        """An explorer with an action of an Avro format: its format is the
        explorer's. Without plugins, whose formats have icons of their own."""

        @view(format=type(self.avro(icon)), engine=PythonEngine)
        def avro_view(fmt, ctx, options, limits):
            return None

        return StorageExplorer(fs=None, actions=[avro_view], plugin_options=NO_PLUGINS)

    def test_default_formats(self):
        assert format_icons(
            ActionChain(DEFAULT_ACTIONS, formats=DEFAULT_FORMATS).formats
        ) == (
            {
                "parquet": "spreadsheet",
                "csv": "spreadsheet",
                "excel": "spreadsheet",
                "json": "json",
                "json-lines": "json",
                "markdown": "markdown",
                "image": "image",
                "svg": "image",
                "png": "image",
                "jpeg": "image",
                "gif": "image",
                "webp": "image",
                "bmp": "image",
                "ico": "image",
                "avif": "image",
            },  # not Text (Python, YAML, ... by extension), nor Delta (folders)
            {},
        )

    def test_one_of_jupyterlabs(self):
        explorer = self.explorer("file")
        assert explorer._format_icons["avro"] == "file"
        assert explorer._file_icon_svgs == {}

    def test_own_svg(self):
        explorer = self.explorer(("avro", self.SVG))
        assert explorer._format_icons["avro"] == "avro"
        assert explorer._file_icon_svgs == {"avro": self.SVG}

    @pytest.mark.parametrize(
        ("icon", "error"),
        [
            ("avro", "unknown file_icon of format 'avro': 'avro'"),
            (("json", SVG), "name it other than"),
            (("avro", "<div/>"), "not SVG markup"),
        ],
    )
    def test_invalid(self, icon, error):
        assert "spreadsheet" in FILE_ICONS
        with pytest.raises(ValueError, match=error):
            format_icons([self.avro(icon)])

    def test_one_name_per_svg(self):
        other = type("Orc", (Csv,), {"name": "orc", "file_icon": ("avro", "<svg/>")})
        with pytest.raises(ValueError, match="another icon is named 'avro'"):
            format_icons([self.avro(("avro", self.SVG)), other()])
