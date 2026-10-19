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


# Options for the default formats' previews, data browser and code (see
# "Format options" in docs/storage-explorer.md).
#
# def format_options():
#     return {
#         "polars_storage_options": {"aws_region": "eu-west-1"},
#         "polars_delta_use_pyarrow": True,
#     }


# Formats of your own (DataFormat subclasses), tried before the defaults.
#
# def formats():
#     from my_formats import AvroFormat
#
#     return [AvroFormat()]


# File operations of your own, tried before the defaults: e.g. renames and
# copies on the server for Azure Data Lake Storage Gen2 accounts (needs
# `pip install "jupyter-storage-explorer[abfs]"`).
#
# def operations():
#     from jupyter_storage_explorer.filesystems.abfs import AzureDataLakeGen2Operation
#
#     return [AzureDataLakeGen2Operation()]


# How filesystems the defaults do not know are told apart, and their URLs
# (FileSystemMapper subclasses), tried before the defaults.
#
# def filesystem_mappers():
#     from my_mappers import MyStorageMapper
#
#     return [MyStorageMapper()]


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
#         "open_preview": True,
#         "max_browser_items": 50_000,
#         "max_upload_bytes": 100 * 1024 * 1024,
#     }
