"""The harness of the StorageExplorer tests: the widget driven by the messages
its frontend sends, and what it shows."""

from __future__ import annotations

from typing import Any

from jupyter_storage_explorer import StorageExplorer, _paths
from jupyter_storage_explorer._explorer.states import ExplorerStates


class Explorer(StorageExplorer):
    """Keeps what would be sent to the frontend in ``sent``, as (content, buffers)."""

    def send(self, content: dict[str, Any], buffers: Any = None) -> None:
        self.__dict__.setdefault("sent", []).append((content, buffers))

    def message(self, content: dict[str, Any], buffers: Any = None) -> None:
        """Send a message as the frontend does."""
        self._on_custom_msg(self, content, buffers)

    def request(self, content: dict[str, Any], buffers: Any = None) -> dict[str, Any]:
        """Send a message as the frontend does; the last message sent back.

        For a request that started a job ({"job": id}), its result instead:
        without a kernel loop, jobs run at once (see _jobs/runner.py), so the job has
        ended by then.
        """
        self.message(content, buffers)
        reply = self.sent[-1][0]
        if "job" in reply:
            return {
                **self.job(reply["job"])["result"],
                "type": "reply",
                "rid": reply.get("rid"),
            }
        return reply

    def job(self, job_id: str) -> dict[str, Any]:
        """The last message about job ``job_id``."""
        return [
            c for c, _ in self.sent if c.get("type") == "job" and c["id"] == job_id
        ][-1]


def make(*args: Any, **kwargs: Any) -> Explorer:
    kwargs.setdefault("states", ExplorerStates())
    return Explorer(*args, **kwargs)


def entries(explorer: Explorer) -> list[dict[str, Any]]:
    """The items of ``_listing`` as the frontend decodes them (listedEntries)."""
    listing = explorer._listing
    no_url = set(listing["no_url"])
    return [
        {
            "name": name,
            "path": listing["paths"][i]
            if listing["paths"] is not None
            else _paths.join(listing["dir"], name),
            "type": "directory" if listing["is_dir"][i] else "file",
            "size": listing["sizes"][i],
            "mtime": listing["mtimes"][i],
            "format": listing["formats"][listing["format"][i]],
            "no_url": i in no_url,
        }
        for i, name in enumerate(listing["names"])
    ]


def path_of(explorer: Explorer, name: str) -> str:
    return next(e["path"] for e in entries(explorer) if e["name"] == name)


def without_ids(reply):
    return {k: v for k, v in reply.items() if k not in ("type", "rid")}
