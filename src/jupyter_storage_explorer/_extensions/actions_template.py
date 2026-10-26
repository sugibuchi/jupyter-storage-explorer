# Storage Explorer actions: yours.
#
# Views and code of your own, for every explorer: in notebooks, the launcher's
# tabs and the side panel. Each function decorated with @view or @code below
# is an action. Uncomment the example and edit it, then choose "Reload
# actions" in the explorer's settings menu to apply the changes; a file with
# an error is left out, with its error.
#
# See "Action development guide":
# https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/action-development-guide.md

from jupyter_storage_explorer.actions import code, view
from jupyter_storage_explorer.formats import Json, Text

# # A second view of text files, in upper case: your actions add to the
# # explorer's, so "Preview as" offers it beside the explorer's own view. The
# # function names the parameters it needs, and returns the text to show.
# @view(format=Text, label="Upper case")
# def upper_case(fs, path):
#     with fs.open(path, "rt") as f:
#         return f.read(10_000).upper()
#
#
# # Code pretty-printing JSON files, in "Python code", labelled with the
# # function's name: "Pretty print json". {url!r} is the file's URL, quoted.
# PRETTY_PRINT = """
# import json
#
# import fsspec
#
# with fsspec.open({url!r}) as f:
#     print(json.dumps(json.load(f), indent=4))
# """.strip()
#
#
# @code(format=Json)
# def pretty_print_json(url):
#     return PRETTY_PRINT.format(url=url)
