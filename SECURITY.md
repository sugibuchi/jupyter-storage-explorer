# Security policy

## Supported versions

Fixes go into the latest release only. All the packages of this repository are released together, at one version:
`jupyter-storage-explorer`, `jupyter-storage-explorer-launcher` and the plugins.

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's
[private vulnerability reporting](https://github.com/sugibuchi/jupyter-storage-explorer/security/advisories/new),
not in a public issue.

Include what you can of:

- the package and version;
- what an attacker can do, and what they need, e.g. a crafted file name on a storage, or a page in the same browser;
- the steps to reproduce it.

You should get an answer within a week. Once a fix is released, the advisory is published, with credit to you unless
you prefer otherwise.

## Scope

The explorer runs in the user's kernel, with the user's credentials. It can do what the user's own code can. These are
by design, not vulnerabilities:

- Unsafe mode and the transfer policy prevent mistakes; they are not security boundaries. Code in the kernel can do
  whatever its credentials allow.
- Settings that a user's `launcher.py` cannot change, through `final()`, do not stop that user from creating explorers
  of their own in notebooks.

What storages hold must never run in the browser, or act on the kernel's behalf. Names that hide characters,
Markdown or SVG running scripts, notebooks trusted without a signature, and transfers the transfer policy should
refuse are all in scope.
