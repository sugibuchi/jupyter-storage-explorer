"""The plugin's dependencies: jupyter-storage-explorer at the plugin's own
version.

The two are released together, with the same version (from the git tags),
and the plugin may use the explorer's internals: any other version of the
explorer may not work with it. Its libraries are not dependencies (see the
"full" extra in pyproject.toml). Hatchling has resolved the version when it
runs this hook.
"""

from __future__ import annotations

from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.version import Version


class PluginMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        # Without the local part (+g<commit>.d<date>) of development builds,
        # which "==" ignores, so an editable explorer of the same commit matches.
        version = Version(metadata["version"]).public
        metadata["dependencies"] = [f"jupyter-storage-explorer=={version}"]
