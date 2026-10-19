"""Excel workbooks (.xlsx)."""

from __future__ import annotations

from jupyter_storage_explorer.formats.base import DataFormat


class Excel(DataFormat):
    name = "excel"
    label = "Excel workbook"
    extensions = (".xlsx", ".xlsm")
    file_icon = "spreadsheet"
