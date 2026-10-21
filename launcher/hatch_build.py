"""The launcher's dependencies, with jupyter-storage-explorer at its own version,
and the explorer's extras (its plugins, e.g. "polars"), so that
``pip install "jupyter-storage-explorer-launcher[polars]"`` installs them too.

The two packages are released together, with the same version (from the git
tags), and the launcher uses the explorer's internals (e.g.
``StorageExplorer._restore_view``): any other version of the explorer may not
work with it. Hatchling has resolved the version when it runs this hook.
"""

from __future__ import annotations

from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.version import Version

DEPENDENCIES = ["jupyter-core>=5"]

# The plugins of the repository, as the explorer's hatch_build.py has them.
PLUGINS = ("abfs", "pandas", "polars", "pyspark")


class LauncherMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        # Without the local part (+g<commit>.d<date>) of development builds,
        # which "==" ignores, so an editable explorer of the same commit matches.
        version = Version(metadata["version"]).public
        metadata["dependencies"] = [
            *DEPENDENCIES,
            f"jupyter-storage-explorer=={version}",
        ]
        extras = [e for name in PLUGINS for e in (name, f"{name}-support")]
        metadata["optional-dependencies"] = {
            extra: [f"jupyter-storage-explorer[{extra}]=={version}"] for extra in extras
        }
