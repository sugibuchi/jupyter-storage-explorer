# Storage Explorer actions: yours.
#
# Views and code of your own, for every explorer: in notebooks, the launcher's
# tabs and the side panel. Each function decorated with @view or @code below
# is an action. Uncomment the example and edit it, then create the explorer
# again (run its cell again, or open a new tab) to apply the changes; a file
# with an error is left out, with a warning.
#
# See https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/storage-explorer.md#actions-of-your-own
# and, for the rules, https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/docs/development-plugin.md#actions

# from jupyter_storage_explorer.formats import Text, TextView
# from jupyter_storage_explorer.formats.actions import view
# from jupyter_storage_explorer.formats.python import PythonEngine
#
#
# # A second view of text files, in upper case: your actions add to the
# # explorer's, so "Preview as" offers it after the explorer's own view.
# @view(format=Text, engine=PythonEngine, label="Shout")
# def shout(fmt, ctx, options, limits):
#     return TextView(text=ctx.head_text(limits.max_bytes)[0].upper())
