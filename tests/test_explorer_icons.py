"""The icons of the formats' files in the explorer's list (_explorer/icons.py)."""

from __future__ import annotations

import pytest

from jupyter_storage_explorer import StorageExplorer
from jupyter_storage_explorer._explorer.icons import format_icons
from jupyter_storage_explorer.formats import FILE_ICONS, Csv, Text, default_formats


class TestFileIcons:
    """Each format's file_icon, sent to the frontend by format name; files of
    formats without one get their extension's icon there (icons.js)."""

    SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>'

    def avro(self, icon):
        return type("Avro", (Csv,), {"name": "avro", "file_icon": icon})()

    def test_default_formats(self):
        assert format_icons(default_formats()) == (
            {
                "parquet": "spreadsheet",
                "csv": "spreadsheet",
                "excel": "spreadsheet",
                "json": "json",
                "json-lines": "json",
                "markdown": "markdown",
                "image": "image",
            },  # not Text (Python, YAML, ... by extension), nor Delta (folders)
            {},
        )

    def test_one_of_jupyterlabs(self):
        explorer = StorageExplorer(fs=None, formats=[self.avro("file"), Text()])
        assert explorer._format_icons == {"avro": "file"}
        assert explorer._file_icon_svgs == {}

    def test_own_svg(self):
        explorer = StorageExplorer(fs=None, formats=[self.avro(("avro", self.SVG))])
        assert explorer._format_icons == {"avro": "avro"}
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
