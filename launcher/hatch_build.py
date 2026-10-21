"""The launcher's dependencies, with jupyter-storage-explorer at its own version
(its extras, the plugins, are in pyproject.toml).

The two packages are released together, with the same version (from the git
tags), and the launcher uses the explorer's internals (e.g.
``StorageExplorer._restore_view``): any other version of the explorer may not
work with it. Hatchling has resolved the version when it runs this hook; a
static pyproject.toml cannot name it.
"""

from __future__ import annotations

from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.version import Version

DEPENDENCIES = ["jupyter-core>=5"]


class LauncherMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        # Without the local part (+g<commit>.d<date>) of development builds,
        # which "==" ignores, so an editable explorer of the same commit matches.
        version = Version(metadata["version"]).public
        metadata["dependencies"] = [
            *DEPENDENCIES,
            f"jupyter-storage-explorer=={version}",
        ]
