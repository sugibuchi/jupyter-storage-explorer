# Storage Explorer launcher settings: yours.
#
# This file configures the Storage Explorer tabs of JupyterLab's launcher.
# Every function is optional: uncomment and edit the ones you need. Reload the
# web browser, then open the explorer tab again to apply the changes; a tab
# shows the error if this file cannot be used.
#
# See https://github.com/sugibuchi/jupyter-storage-explorer/blob/main/launcher/README.md#configuration


# The storages offered, by name: a URL, or an fsspec filesystem for options
# such as credentials. "." is the folder the tab opens on. Empty, it changes
# nothing.
def filesystems():
    # import fsspec

    return {
        # "Here": ".",
        # "Data lake": "abfs://lake@myaccount.dfs.core.windows.net",
        # "Raw (S3)": fsspec.filesystem("s3", profile="analytics"),
    }


# The plugins' options, by plugin key: every plugin installed is used unless
# "enabled" is False; "priority" puts one before the others.
#
# def plugin_options():
#     return {
#         "pandas-support": {"enabled": False},
#         "abfs-support": {"concurrency": 16},
#     }


# Options of the libraries reading the data for previews, the data browser
# and code, by library, then format ("*": all formats). See "Format options"
# in docs/storage-explorer.md.
#
# def format_options():
#     return {
#         "polars": {
#             "*": {"storage_options": {"aws_region": "eu-west-1"}},
#             "delta": {"use_pyarrow": True},
#         },
#     }


# Where files may be copied or moved: the first rule whose src and dest
# patterns both match a file's URLs decides; files go anywhere else.
# "browser:///..." is your computer, "jupyterlab://..." the Jupyter server's
# file browser.
#
# def transfer_policy():
#     return [
#         {"rule": "deny", "src": r"abfs://lake@.*", "dest": r"browser:///.*"},
#     ]


# Other StorageExplorer arguments (see "StorageExplorer options" in
# docs/storage-explorer.md).
#
# def parameters():
#     return {
#         "engine_preference": ["pandas", "polars"],
#         "preview_panel": "open",
#         "max_upload_bytes": 100 * 1024 * 1024,
#     }


# --- For development: extending the explorer in Python, tried before the
# defaults (see the project's docs/development-plugin.md). ---

# Formats and the libraries handling their data (FormatSupport subclasses).
#
# def supports():
#     from my_supports import ParquetByDuckDB
#
#     return [ParquetByDuckDB]


# File operations (FileSystemOperations subclasses), e.g. server-side copies
# for a storage of your own.
#
# def operations():
#     from my_operations import MyStorageOperations
#
#     return [MyStorageOperations()]


# How filesystems the defaults do not know are told apart, and their URLs
# (FileSystemMapper subclasses).
#
# def filesystem_mappers():
#     from my_mappers import MyStorageMapper
#
#     return [MyStorageMapper()]
