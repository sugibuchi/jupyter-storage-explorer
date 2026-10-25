# Storage Explorer actions: yours.
#
# Views and code of your own, for every explorer: in notebooks, the launcher's
# tabs and the side panel. Each function decorated with @view or @code below
# is an action. Uncomment the example and edit it, then create the explorer
# again (run its cell again, or open a new tab) to apply the changes; a file
# with an error is left out, with a warning.
#
# See "Action development guide":
# https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/action-development-guide.md

from jupyter_storage_explorer.formats import Text, file_format
from jupyter_storage_explorer.formats.actions import code, view

# # A second view of text files, in upper case: your actions add to the
# # explorer's, so "Preview as" offers it after the explorer's own view. The
# # function names the parameters it needs, and returns text to show.
# @view(Text, label="Shout")
# def shout(ctx, limits):
#     return ctx.head_text(limits.max_bytes)[0].upper()
#
#
# # Code reading files of a format of your own, in "Python code", labelled
# # with the function's name: "Read abc".
# @code(file_format(".abc"))
# def read_abc(url):
#     return f"import fsspec\n\ntext = fsspec.open({url!r}, 'rt').open().read()"
