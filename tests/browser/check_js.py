"""Checks the widgets' JavaScript as the kernel joins it (see _static.py):
its syntax (``node --check``), and with ESLint, names used but defined in no
file, and names defined but never used (only for the storage explorer: the
data explorer uses some of the shared functions only).

The files are joined into one module per widget, so a typo in a name used
across files shows only here, or in a browser. Run by CI; locally, with the
Node.js of the dev dependencies:

    uv run tests/browser/check_js.py
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

from jupyter_storage_explorer import _static

ESLINT = "eslint@10.0.0"
# What the browser gives the widgets, besides JavaScript's own globals.
GLOBALS = (
    "document,navigator,setTimeout,clearTimeout,URL,Blob,CustomEvent,Node,Element,"
    "File,DataTransfer,DragEvent"
)
RULES = {
    "storage_explorer": ["no-undef: error", "no-unused-vars: [error, {args: none}]"],
    "data_explorer": ["no-undef: error"],
}


def tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        sys.exit(
            f"{name} not found: run this with uv run (Node.js is a dev dependency)"
        )
    return path


def main() -> int:
    node, npx = tool("node"), tool("npx")
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for widget, rules in RULES.items():
            module = pathlib.Path(tmp, f"{widget}.mjs")
            module.write_text(_static.esm(widget), encoding="utf-8")
            checks = [
                [node, "--check", module.name],
                [npx, "--yes", ESLINT, "--no-config-lookup", "--global", GLOBALS]
                + [arg for rule in rules for arg in ("--rule", rule)]
                + [module.name],
            ]
            ok = all(
                subprocess.run(command, cwd=tmp, check=False).returncode == 0
                for command in checks
            )
            failed = failed or not ok
            print(f"{widget}: {'ok' if ok else 'failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
