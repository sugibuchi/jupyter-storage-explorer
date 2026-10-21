"""The explorer's extras: for each plugin of this repository (plugins/), at the
explorer's own version.

"<name>" installs the plugin with its libraries (its "full" extra), e.g.
``pip install "jupyter-storage-explorer[polars]"``; "<name>-support" the plugin
alone, using the libraries already installed. The plugins are released with
the explorer, with the same version (from the git tags). Hatchling has
resolved the version when it runs this hook.
"""

from __future__ import annotations

from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.version import Version

# The plugins of this repository, by name (plugins/<name>-support). The
# launcher offers the same extras (launcher/hatch_build.py).
PLUGINS = ("abfs", "pandas", "polars", "pyspark")


class ExplorerMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        # Without the local part (+g<commit>.d<date>) of development builds,
        # which "==" ignores, so editable plugins of the same commit match.
        version = Version(metadata["version"]).public
        extras: dict[str, list[str]] = {}
        for name in PLUGINS:
            plugin = f"jupyter-storage-explorer-{name}-support"
            extras[name] = [f"{plugin}[full]=={version}"]
            extras[f"{name}-support"] = [f"{plugin}=={version}"]
        metadata["optional-dependencies"] = extras
