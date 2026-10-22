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

    def view_tab(self, path: str, **content: Any) -> dict[str, Any]:
        """Ask for "View in a new tab" of ``path``: the reply, with the
        "view_tab" message sent once the view has loaded ({"model_id"} or
        {"error"}). Without a kernel loop, loads run at once (see
        _jobs/loader.py), so it has been sent by then."""
        reply = self.request({"type": "view_tab", "rid": 1, "path": path, **content})
        if "load_id" not in reply:
            return reply
        [loaded] = [
            c
            for c, _ in self.sent
            if c.get("type") == "view_tab" and c["load_id"] == reply["load_id"]
        ]
        return {**reply, **loaded}

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
            "level": listing["levels"][listing["level"][i]] or None,
            "no_url": i in no_url,
        }
        for i, name in enumerate(listing["names"])
    ]


def storage(explorer: Explorer, name: str | None = None) -> dict[str, Any]:
    """Storage ``name`` of ``explorer`` (default: the one shown) as files
    copied or dragged there name it: {"name"}."""
    return {"name": name or explorer._filesystem}


def copied(explorer: Explorer, path: str, name: str | None = None) -> dict[str, Any]:
    """File ``path`` of storage ``name`` of ``explorer`` (default: the one
    shown) as Copy puts it on the clipboard: {"path", "location"}."""
    fs = explorer._filesystems[name or explorer._filesystem].fs
    location = explorer._mappers.location_of(fs, path)
    return {"path": path, "location": location.to_json() if location else None}


def path_of(explorer: Explorer, name: str) -> str:
    return next(e["path"] for e in entries(explorer) if e["name"] == name)


def without_ids(reply):
    return {k: v for k, v in reply.items() if k not in ("type", "rid")}
