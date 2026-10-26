"""Actions: what explorers do with an item of a format, with an engine.

An action is a function decorated with ``view`` or ``code``, with its
options, an ``ActionOptions`` subclass (base.py). ``actions.python`` has the
built-in ones, with their engine, ``PythonEngine``; the other engines' come
with their plugins. local_files.py has the cache of local copies of remote
files, for libraries reading only local files. defaults.py lists the actions
explorers use whatever plugins are installed.
"""

from jupyter_storage_explorer.actions.base import (
    Action,
    ActionOptions,
    CodeAction,
    ViewAction,
    code,
    register_actions,
    view,
)
from jupyter_storage_explorer.actions.local_files import (
    CacheStatus,
    LocalFileCache,
    local_file_cache,
)
from jupyter_storage_explorer.util import get_logger

__all__ = [
    "Action",
    "ActionOptions",
    "CacheStatus",
    "CodeAction",
    "LocalFileCache",
    "ViewAction",
    "code",
    "get_logger",
    "local_file_cache",
    "register_actions",
    "view",
]
