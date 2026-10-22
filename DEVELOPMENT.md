# Development

## Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) of packages. They are
released together, with one version taken from the git tag.

The launcher and the plugins require the explorer of exactly their own version, as they may use its internals. Their
`hatch_build.py` sets these dependencies, because the version comes from git.

The explorer's extras (`polars`, `polars-support`, ...) have no versions in its `pyproject.toml`. Each plugin pins the
explorer exactly, so an extra always installs the plugin of the explorer's version. The launcher has the same extras.

| Package                                   | Folder                    | Contents                                                                                              |
|-------------------------------------------|---------------------------|-------------------------------------------------------------------------------------------------------|
| `jupyter-storage-explorer`                | `.`                       | The widgets `StorageExplorer` and `DataExplorer`; pure Python, no build.                              |
| `jupyter-storage-explorer-launcher`       | `launcher/`               | The JupyterLab launcher item, and `launch()` run in the tab it opens.                                 |
| `jupyter-storage-explorer-<name>-support` | `plugins/<name>-support/` | The plugins: `polars`, `pandas`, `pyspark` (engines) and `abfs` (Azure Data Lake Storage operations). |

| Path                                                           | Contents                                                                                             |
|----------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `src/jupyter_storage_explorer/`                                | The widgets: `storage_explorer.py`, `data_explorer.py`.                                              |
| `src/jupyter_storage_explorer/filesystems/`                    | Filesystems' locations (mappers) and file operations: interfaces users extend, and the default ones. |
| `src/jupyter_storage_explorer/formats/`                        | The formats files are previewed, queried and loaded as.                                              |
| `src/jupyter_storage_explorer/_explorer/`                      | `StorageExplorer`'s features, as mixins of the class.                                                |
| `src/jupyter_storage_explorer/_jobs/`                          | File operations planned and run as jobs, without the widget.                                         |
| `src/jupyter_storage_explorer/_query/`                         | The data browser: filters, settings, and a dataset open in it.                                       |
| `src/jupyter_storage_explorer/static/`                         | The widgets' JavaScript and CSS, loaded at run time (no build step).                                 |
| `src/jupyter_storage_explorer/static/storage_explorer/`        | The storage explorer's JavaScript, a file per feature, joined at run time.                           |
| `launcher/src/jupyter_storage_explorer_launcher/`              | `launch()`, which merges the `storage-explorer/launcher.py` files (layers).                          |
| `launcher/labextension/`                                       | The JupyterLab extension (TypeScript).                                                               |
| `launcher/src/jupyter_storage_explorer_launcher/labextension/` | The extension built from `launcher/labextension/` (git-ignored).                                     |
| `notebooks/`                                                   | Demo notebooks and `make_samples.py`, which writes the sample data they use.                         |
| `tests/`                                                       | The Python tests, a folder per part of the package (`explorer/`, `formats/`, ...); shared helpers.   |
| `tests/browser/`                                               | Checks of the widgets' JavaScript, and their smoke test in a browser.                                |
| `docs/scripts/`                                                | Scripts making the docs' screenshots and the demo GIFs.                                              |
| `binder/`                                                      | The demo on mybinder.org (the README's "Try it" link): released packages, demo data.                 |

All Python commands go through [uv](https://docs.astral.sh/uv/). Node.js, for the extension and the JavaScript's checks,
comes with the dev dependencies (`nodejs-wheel`), so `uv run node`, `uv run npx` and `uv run jlpm` work without
installing it.

## Setup

```bash
uv sync                    # every package, editable, with the dev dependencies
cd launcher/labextension
uv run jlpm install        # the extension's build tools, into node_modules
uv run jlpm build          # builds the extension into launcher/src/jupyter_storage_explorer_launcher/labextension
cd ../..
uv sync                    # reinstalls the launcher package with the built extension
```

To try the widgets in a browser:

```bash
uv run jupyter lab
```

IntelliJ's notebook view runs the widgets too, but dragging files in or out of them only works in a browser.

## Tests

```bash
uv run pytest                                        # the Python side
uvx ruff check src launcher/src plugins tests docs/scripts   # lint
uv run npx --yes prettier@3.3.3 --check .            # formatting: the widgets' JS and CSS, the extension's TS
uv run tests/browser/check_js.py                     # their JavaScript: syntax, names undefined or unused
uv run --group docs tests/browser/smoke.py           # the widgets in a real JupyterLab
```

CI runs the first four and compiles the extension's TypeScript. It does not run the smoke test: run it yourself after
changing `static/` or the extension.

The JavaScript has no unit tests. Instead, `tests/browser/smoke.py` starts a JupyterLab of its own and clicks through
the main features in the installed Microsoft Edge: browsing, previews, the data browser, file operations, transfers and
the launcher's tab. Give check names to run only those. A failed check leaves a screenshot,
`tests/browser/smoke-<check>.png`.

For performance, `uv run tests/performance/benchmark.py` times what users wait for: opening large folders, clicks,
copies and scrolling the data browser. It runs on a memory filesystem with a latency per call, so that round trips
count as on cloud storages. Compare its timings before and after a change, on the same machine.

The packages support JupyterLab 4.0 or later, but the development environment has the latest. To run the smoke test on
an older JupyterLab, make an environment of its own, outside the repository. `uv run --with` would not do, as it does
not see the extensions installed in `.venv`.

```bash
uv export --group docs --group dev --no-hashes --no-emit-workspace -o ../req.txt
echo "jupyterlab==4.0.*" > ../override.txt
uv venv ../lab40
uv pip install --python ../lab40 -r ../req.txt --override ../override.txt -e . -e launcher
uv run --no-project --python ../lab40 tests/browser/smoke.py
```

After rebuilding the extension, install it there again:

```bash
uv pip install --python ../lab40 -e launcher --reinstall-package jupyter-storage-explorer-launcher
```

## Architecture

- **`StorageExplorer`** holds the widget's state and routes the frontend's messages. Each of its features is a mixin,
  in `_explorer/`.
- **Its frontend** is a JavaScript file per feature, in `static/storage_explorer/`. The kernel joins them into one
  module.
- **Storages** are fsspec filesystems. Locations say where their files are, independently of fsspec. Mappers, in
  `filesystems/`, make them.
- **File operations** are planned by `FileTasks` and run as jobs in a worker thread, both in `_jobs/`. A chain of
  `FileSystemOperations` objects does the work, and users can extend it.
- **The data browser** is `DataQuery`, in `_query/`. It works on any dataframe narwhals supports. `DataExplorer` shows
  it alone.
- **Formats**, in `formats/`, detect each kind of file. Supports preview, query and load it, one library each.

The sections below describe the widgets, the frontend, the storages and the file operations. CLAUDE.md describes the
other parts.

### Widgets

The widgets are `anywidget.AnyWidget` subclasses:

- `StorageExplorer`, in `storage_explorer.py`;
- `DataExplorer`, in `data_explorer.py`;
- `ViewTab` and `TableSetTab`, private, which "View in a new tab" opens.

They talk to the frontend in two ways:

- **Traits** hold the state shared with the browser: `traitlets` tagged `sync=True`. Their names start with an
  underscore, as a public trait would be public API.
- **Custom messages** carry everything else. `_on_custom_msg` dispatches them by their `type`.

A message is a request or a notice:

- A **request** carries an id, `rid`. Its handler is listed in `_requests()`. Its answer is a message of type `"reply"`
  with the same `rid`.
- A **notice** gets no answer, and its effects show in the traits. The exception is "download", answered by a message
  per file with the file's bytes attached.

Uploads carry the pieces of files in the messages' binary buffers. Values sent go through `_json.jsonable`.

A failed request's reply is `{"error": text}`. For the explorer's own refusals, which are `ValueError`s, the text
leaves out the exception's type. File operations reply with a list instead, `{"errors": [...]}`, as jobs do.

Users' callbacks are kept in `_callbacks.Callbacks`. The widget compares what it shows with what they last heard of, so
each is called once per change.

- `on_change` hears of the storage, the folder and the selection, from the traits' observers.
- `StorageExplorer.on_query_change` hears of the query in the preview panel and of its result settings. It is called
  after the data browser's replies and when the preview changes, but not while a preview loads.

`StorageExplorer` itself keeps:

- its state, set up in `__init__`;
- the routing of the messages;
- the traits' observers, which must be on the class itself;
- the locations of paths: `_location_of`, `_url`, and `_location_reply` for the frontend;
- the only calls to fsspec on the storage shown, in its last block, *File operations*.

Its features are mixins in `_explorer/`, listed before `AnyWidget` in its bases. They hold only methods. What they
share is in `_explorer/common.py`.

| Mixin                  | File            | Feature                                                                  |
|------------------------|-----------------|--------------------------------------------------------------------------|
| `FoldersMixin`         | `folders.py`    | The list and the tree.                                                   |
| `PreviewsMixin`        | `previews.py`   | Previews, the data browser, view tabs, and the formats in the menu.      |
| `BookmarksMixin`       | `bookmarks.py`  | Bookmarks.                                                               |
| `JupyterLabFilesMixin` | `jupyterlab.py` | Files opened in JupyterLab's editors.                                    |
| `JobsMixin`            | `jobs.py`       | Running file operations as jobs, and showing what they change.           |
| `FileRequestsMixin`    | `requests.py`   | The requests for file operations.                                        |
| `AboutMixin`           | `about.py`      | The settings menu's About: the versions of the explorer and the plugins. |

### Frontend

The frontend is plain ES modules in `static/`, with no bundler. anywidget cannot import neighbouring files, so the
kernel joins each widget's files into one module (`_static.esm`), in this order:

1. the shared files: `icons.js`, `common.js`, `query.js` for the data browser, and `sections.js` for views;
2. the widget's parts, the files of `static/<widget>/`, if any;
3. the widget's own file, `<widget>.js`, with `render` and the export.

All but the last only define functions and constants. The CSS is joined the same way, without parts.

The storage explorer's parts are in `static/storage_explorer/`, one feature each:

- `tree.js`, `list.js` and `preview.js`;
- `item_menu.js`, the right-click menu, and `shortcuts.js`, the list's keys;
- `operations.js`, with the clipboard;
- `transfers.js`: drag and drop, uploads and downloads;
- `jupyterlab.js`, `properties.js` and `jobs.js`;
- `toolbar.js`, with unsafe mode and bookmarks;
- `engine.js`, the engine chosen, and `about.js`, the settings menu's About;
- `overlays.js`, for the busy screen, dialogs and menus, and `util.js`.

Each part is a function `createX(x)` returning its elements and functions. `x` is the explorer, made in `render()`. It
holds what the features share, such as `model`, `request` and `navigate`. It also holds the features themselves, such
as `x.list`. A feature uses another when needed, not when made, so their order rarely matters.

Third-party code is vendored in `static/vendor/`. The kernel sends it when the frontend asks, e.g. marked for Markdown
views.

Two rules keep the frontend working:

- File names, paths and messages naming files are shown through `visible()`, in `common.js`. It shows control, bidi
  and invisible characters as `\uXXXX`.
- anywidget's `model` has only `get`, `set`, `save_changes`, `on`, `off` and `send`. Backbone methods such as
  `previous()` throw inside `set`, which silently breaks syncing.

### Storages

Every storage is an fsspec filesystem. A `StorageExplorer` can hold several, by name.

#### Locations

A `Location`, in `location.py`, says where an item is, independently of fsspec's implementations. So it can travel to
other kernels, and to libraries that do their own I/O.

- It is a frozen, keyword-only dataclass.
- It is normalized when made: hosts and accounts in lower case, endpoints as origins, no trailing "/". So equal
  locations name the same item, and can be dict keys.
- Whether the item is a folder is not part of it.
- A subclass gives only its fields, its `kind` and its `url`. The URL is the common form, which the fsspec
  implementation also reads.
- `to_json()` gives `{"kind", "url", ...fields}`, and `Location.from_json()` reads it back. Subclasses register by
  `kind`.
- An unknown kind is read as an `FsspecLocation`. For known kinds, the URL in the JSON is ignored.

A location does not say which storage it is on. What one fsspec instance reaches depends on the implementation: an
adlfs instance reaches all of an account's containers. Only mappers can tell.

The predefined locations are in `filesystems/locations.py`:

| Location         | Fields                                     | URL                                                  |
|------------------|--------------------------------------------|------------------------------------------------------|
| `AbfsLocation`   | Account, container, path, endpoint suffix. | `abfs://container@account.dfs.core.windows.net/path` |
| `S3Location`     | Bucket, key, endpoint or AWS partition.    | `s3://bucket/key`                                    |
| `GcsLocation`    | Bucket, key, endpoint.                     | `gs://bucket/key`                                    |
| `SftpLocation`   | Host, port, user, path.                    | `sftp://user@host:port/path`                         |
| `LocalLocation`  | Path, host name, machine id.               | `file:///path`                                       |
| `MemoryLocation` | Path, process.                             | `memory://path`                                      |
| `FsspecLocation` | URL.                                       | fsspec's URL, for filesystems no mapper knows.       |

With an emulator, an `AbfsLocation`'s URL is adlfs's own form, `abfs://container/path`. A `LocalLocation`'s `path` is
fsspec's, such as "C:/x" on Windows, and its `os_path` is the system's.

#### Mappers

A `FileSystemMapper`, in `filesystems/mapper.py`, maps the paths of one fsspec implementation:

- `to_location(fs, path)` gives a path's location, without credentials. "" gives the top folder. None means the item
  has no location.
- `path_of(fs, location)` is the reverse. It gives None unless `fs` reaches the location, which the mapper decides from
  the location's fields and the instance's settings.
- `level(fs, path)` says what the storage makes of a folder, such as "container". It gives folders their icons and
  their rows' `data-fs-level`.

By default, `level` reads `levels`, a name per depth from the top folder, e.g. adlfs's `("account", "container")`.
The explorer sends each folder's level with the tree and the listing. `LEVEL_ICONS`, in `icons.js`, gives each level
its icon.

A mapper matches filesystems by the qualified names of their classes and bases. So optional packages are never
imported. Tests fake s3fs, gcsfs, SFTP and Databricks classes by setting their `__module__`.

Locations are defined per kind of storage, not per implementation. So the mappers of fsspec's SFTP and of sshfs give
the same `SftpLocation`s.

The predefined mappers are in `filesystems/mappers.py`: Azure, S3, GCS, local, memory, SFTP, sshfs and Databricks.
`DatabricksMapper` maps both fsspec-databricks and fsspec's own DBFS, with URLs `dbfs://Volumes/...`. pyspark-support's
`spark_url` turns those into Databricks' `dbfs:/Volumes/...`.

#### The mapper chain

An explorer asks its mappers through a `MapperChain`. The chain has the explorer's `filesystem_mappers`, then the
defaults, and it falls back to `FsspecMapper`.

- `location_of(fs, path)` and `level_of(fs, path)` ask the filesystem's mapper.
- `path_in(fs, location)` gives the location's path in `fs`, or None.
- `same_filesystem(a, b)` tells whether each reaches the other's top folder. So the same storage opened with other
  credentials is one. Filesystems no mapper knows are compared as fsspec does.
- `locate(location, filesystems)` finds files pasted from another kernel. See below.

`DirFileSystem`s are not mapped. The chain unwraps them, so their locations are those of the filesystem they wrap.
`same_filesystem` also compares their folders.

`locate` tries the explorer's storages in order, and takes the first that reaches the location. Otherwise, it opens a
filesystem from the location's URL, with the user's credentials, and checks that this one reaches it. Else it refuses.
So another kernel's memory or another machine's disk is never read.

`locate` never opens an `FsspecLocation`'s URL, as nothing tells which storage such a URL is on. Otherwise a dropped
URL could make the kernel connect anywhere.

File operations need to know whether two filesystems are the same. `FileTasks` passes the explorer's chain to `move`
and `copy`, as their keyword `same`.

### File operations

`StorageExplorer` lists, reads and writes the storage shown through its own methods only, such as `_ls` and
`_read_bytes`. They are the last block of the class, *File operations*.

Moving, copying, deleting, downloading and creating folders go through operations objects instead, in
`filesystems/operation.py`. They form a chain of `FileSystemOperations`:

- Each method is tried on each object in order, until one does not raise `FileSystemOperations.NotSupported`.
- A library's own `NotImplementedError` is an error, not a refusal. That is why the chain has an exception of its own.
- The explorer's `operations=` come first, then `StorageExplorer.default_operations()`.

The default operations, in `filesystems/operations.py`:

| Operations              | Does                                                                                     |
|-------------------------|------------------------------------------------------------------------------------------|
| `AtomicMoveOperation`   | Moves within a filesystem whose `mv` renames a folder in one step: local and memory.     |
| `AsyncFsspecOperations` | Everything on async filesystems, such as s3fs, with up to 32 files running at a time.    |
| `FsspecOperations`      | Everything else, one file at a time.                                                     |

`AtomicMoveOperation` also takes a `DirFileSystem` over local or memory filesystems. The other two walk folders
themselves, moves included, so that they can report progress file by file. Their shared helpers are in
`filesystems/_common.py`.

`move` and `copy` take a source and a target filesystem, the same one or not. Between filesystems, each file goes
through `_copy_file` and `_move_file`, which subclasses can override.

- By default, a copy goes through a temporary file, so a failure leaves no partial file.
- A move copies, then deletes each file, so a cancel leaves each file in one place.
- The async class has `_copy_file_async` and `_move_file_async` instead.

A folder copy is refused before anything is written if a file's path in it has `.` or `..` parts. Object stores keep
such keys, and on a local disk they would land outside the target folder.

Object stores, such as S3 and GCS, have no empty folders. That matters when creating folders.

abfs-support adds `AzureDataLakeGen2Operation`, in `plugins/abfs-support`. On accounts with a hierarchical namespace,
it renames and creates folders with the Data Lake SDK. Within an account, it copies on the server with Copy Blob. Its
tests fake the SDK and adlfs, which the plugin imports on first use.

Tests use fsspec's `AsyncFileSystemWrapper` around a memory filesystem as an async filesystem.

### Jobs

These run in the background, as jobs:

- move, rename, delete and paste;
- uploads, from JupyterLab's file browser or from the user's computer;
- both downloads to JupyterLab.

A job goes through three steps:

1. **Planning**, on the main thread: a `FileTasks` method, in `_jobs/tasks.py`, checks the request without the widget.
   It returns the conflicts to ask the user about, or a `Task`.
2. **Work**, in the worker thread of a `JobRunner`, in `_jobs/runner.py`: the task's `work(progress)`. The runner runs
   one job at a time. The task records what it changes as each item is done.
3. **Showing the changes**, on the main thread: `JobsMixin` follows them as the job goes, and shows them all once it
   ends.

While the job goes, items gone are dropped from the list and the tree without listing, at most once a second. Folders
with new items are listed again, at most every 3 seconds, keeping the selection.

Work functions must not touch traits or call `send`. They report to the `Progress`, and stop when `progress.check()`
raises `OperationCancelled`.

The public `Progress`, in `filesystems/operation.py`, has only what operations use. The runner's `JobProgress`, in
`_jobs/progress.py`, adds the job's bookkeeping, such as totals, items and cancelling.

The main thread is reached through the kernel's asyncio loop. Without a running loop, as in tests, jobs run at once, so
tests see their result immediately.

A request answers `{"job": id}`. The kernel then sends `{"type": "job", ...}` messages as the job runs, and one with the
result when it ends. The frontend's `x.jobs.result()` waits for that one.

Uploads come in two kinds:

- A drop from JupyterLab's file browser is a copy from the kernel's local disk: `FileTasks.upload`.
- Files from the user's computer arrive in pieces, in `_jobs/incoming.py`. The last piece starts
  `FileTasks.upload_file`.

### Properties

Properties of one file are its fsspec info, answered at once. For folders or several items, `FileTasks.properties`
adds up the operations' `measure` of each item, as a job.

That job runs on a `JobRunner` of its own, so it never waits for a move. The frontend shows it in a dialog with
Cancel, not with the jobs above the status bar. It is not an operation, so it does not turn off unsafe mode.

`FileSystemOperations.measure` returns a `Measurement`: files, bytes, folders, oldest and newest files, errors, and
whether it is complete. The defaults measure in two ways:

- Without a `Progress`, for a job's progress bar, they make one recursive `find`.
- With one, they list folder by folder, reporting the files found. Unlistable folders go in `errors`. A cancel returns
  what was found, not complete.

They do not use `fs.walk`, whose `on_error` misses subfolders.

### Unsafe mode

Folder operations are offered only while the toolbar's "Unsafe mode" slider is on. They are move, copy, cut and paste,
rename and delete.

- In the frontend, every operation calls `x.unsafe.take()` as it starts, which turns the mode off. So it allows one
  operation at a time.
- The request says whether the mode was on, and the kernel refuses folders without it.

### Transfer policy

A `TransferPolicy`, in `_jobs/transfer_policy.py`, applies to every copy and move. That includes those within a
filesystem.

- Its rules are tried in order. The first whose `src` and `dest` patterns both match decides.
- A rule's patterns must have the same named groups, and they must capture the same text on both sides.
- Without a matching rule, the transfer is allowed.

The kernel checks it per item, as it plans. Refused items become errors, and the others go on.

The policy compares URLs: the item's location's, else fsspec's. Files pasted keep the URL of the location they were
copied with. Two other sides have URLs of their own:

- the user's computer, `browser:///<name>`;
- JupyterLab's file browser, `jupyterlab://<absolute path>`, unlike the explorer's own local storage, `file:///`.

The policy prevents mistakes. It is not a security boundary.

## Design

### Security

The explorer runs in the user's kernel, as their code does: it can do what their code can, and no more. Keep it so.

- **Credentials** come from the environment, as each storage's library finds them: an AWS profile, an Azure CLI login
  or managed identity, Google's default credentials. Options given to a storage work too.
- **The explorer never asks for secrets**, and never reads them from environment variables. Asking would happen in
  every kernel: each launcher tab, each notebook. Secrets in environment variables are a practice we do not support.
- **"Python code" leaves out credentials**: options declared secret, and options whose names look like credentials.
- **Nothing is added to the Jupyter server**: no server extension, no endpoints reaching storages. The launcher's
  JupyterLab extension only shows explorers and passes the frontend's requests to their kernels.
- **Unsafe mode and the transfer policy prevent mistakes**; they are not a security boundary: code in the kernel can
  do whatever its credentials allow.
- **Notebooks opened from a storage** (Edit) are untrusted unless signed, as JupyterLab's own are. Their outputs' HTML
  and scripts do not run until the user trusts them. The kernel checks signatures with nbformat's notary, as
  jupyter_server does, and signs a notebook saved while trusted.
- **What storages hold is shown, never run**:
  - names show control and invisible characters as `\uXXXX` (`visible()`);
  - Markdown is sanitized;
  - a format's own icon is shown as an image, in which scripts do not run.
- **Pages cannot name files**: drags carry only a random id, so drags from other browser tabs or sites are refused.
- **Files pasted from another kernel** are read with one of the explorer's storages. For the kinds of storage the
  mappers know (Azure, S3, Google Cloud Storage, SFTP), the explorer may also open one with the user's credentials.
  An unknown URL is never opened (`MapperChain.locate`).

## The JupyterLab extension

The extension is not built when the package is built: build it yourself with `jlpm` in `launcher/labextension/`. The
build output and `node_modules` are git-ignored. They stay on disk until removed.

| Command (in `launcher/labextension/`) | Run it again when                                                                                        |
|---------------------------------------|----------------------------------------------------------------------------------------------------------|
| `uv run jlpm install`                 | `node_modules` is missing (new clone or machine), or `package.json` dependencies or `yarn.lock` changed. |
| `uv run jlpm build`                   | `src/`, `style/` or `package.json` changed, or the build output is missing.                              |
| `uv run jlpm build:prod`              | Before every release (a production build, without source maps).                                          |

After a build, run `uv sync` in the repository folder. It reinstalls the launcher package, which copies the build to
`.venv/share/jupyter/labextensions`. Then restart JupyterLab and reload the page.

Changes to the Python code or to `src/jupyter_storage_explorer/static/` need no build: restart the kernel.

Commit `package.json`, `yarn.lock`, `.yarnrc.yml`, `tsconfig.json`, `src/` and `style/` of `launcher/labextension/`;
not `node_modules/`, `lib/` or `.yarn/`.

## Releasing

Releases are made by GitHub Actions: push a version tag from `main`,

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

The workflows, in `.github/workflows/`:

1. **Release explorer** (`release-explorer.yaml`) runs on the tag. It builds `jupyter-storage-explorer` and checks its
   version. It creates the GitHub release, with notes generated from the merged pull requests, and publishes the
   package to PyPI.
2. **Release launcher** (`release-launcher.yaml`) runs once the first has succeeded, so that the explorer it depends on
   is on PyPI. It builds the JupyterLab extension and the launcher, then checks the version, the extension in the
   wheel, and the dependency on `jupyter-storage-explorer==X.Y.Z`. It adds the packages to the release and publishes
   them.
3. **Release <plugin>** (`release-<plugin>.yaml`) also runs once the first has succeeded. There is one per plugin, as
   PyPI's trusted publishing takes one workflow per project; they share `_release-plugin.yaml`. Each builds its plugin,
   then checks the version, the dependency on the explorer, and the entry point. It adds the packages to the release
   and publishes them.

To retry the launcher's or a plugin's, run it by hand for the tag: *Actions ▸ Release launcher ▸ Run workflow*.

### Release notes

Once all the workflows have succeeded, replace the generated notes (`gh release edit vX.Y.Z --notes-file notes.md`).
Use these sections, leaving out those with nothing to say:

- **New**, **Changes**, **Fixes**: one item each, saying what users can now do or what behaves differently, with the
  option or function names.
- **Breaking changes**: what users must change in their code or `launcher.py`, and how.
- Links to the documentation of the new features (absolute GitHub URLs).
- **Install**: the `pip install -U` command for both packages. Say that the launcher requires the explorer of the same
  version, and that JupyterLab must be restarted after upgrading it.
- **What's Changed** and **Full Changelog**: kept at the end, as generated.

### One-time setup for PyPI

The workflows publish with PyPI's [trusted publishing](https://docs.pypi.org/trusted-publishers/), without a token:

1. On PyPI, add a trusted publisher for each project, with this GitHub repository's owner and name and the
   environment `pypi`. For a project not on PyPI yet, add it as a *pending publisher* under *Your account ▸
   Publishing*.

   | PyPI project                               | Workflow                       |
   |--------------------------------------------|--------------------------------|
   | `jupyter-storage-explorer`                 | `release-explorer.yaml`        |
   | `jupyter-storage-explorer-launcher`        | `release-launcher.yaml`        |
   | `jupyter-storage-explorer-abfs-support`    | `release-abfs-support.yaml`    |
   | `jupyter-storage-explorer-pandas-support`  | `release-pandas-support.yaml`  |
   | `jupyter-storage-explorer-polars-support`  | `release-polars-support.yaml`  |
   | `jupyter-storage-explorer-pyspark-support` | `release-pyspark-support.yaml` |

   Before its first release, a new plugin needs a workflow of its own (a copy of a `release-<plugin>.yaml`) and its
   trusted publisher.

2. On GitHub, create the environment `pypi` (*Settings ▸ Environments*). Optionally, require a reviewer there, so
   that publishing waits for approval.

### By hand

To build the packages locally, e.g. to publish them to another repository such as an internal Nexus:

```bash
cd launcher/labextension
uv run jlpm install        # only if package.json or yarn.lock changed
uv run jlpm build:prod
cd ../..
uv build --all-packages    # sdists and wheels of every package, in dist/
uv publish --publish-url <url> dist/*
```

`<url>` is the repository's upload URL, e.g. `https://nexus.example.com/repository/pypi-internal/`. `uv publish` asks
for the credentials, or reads them from `UV_PUBLISH_USERNAME` and `UV_PUBLISH_PASSWORD`.

Build from a clean checkout of the tag: uncommitted changes give a version like `X.Y.Z.post0+g<commit>.d<date>`.

`uv build` packages whatever extension was built last, so run `build:prod` just before it. Without a built extension,
`uv build` still succeeds, but the launcher's wheel has no launcher item.

## Documentation

The root `README.md` is the quick start and highlights. PyPI shows it too and cannot resolve relative paths, so its
links and images are absolute GitHub URLs.

The details are in `docs/` (`storage-explorer.md`, `data-explorer.md`). They are read on GitHub only, so they link to
each other and to the repository's files with relative paths.

The screenshots (`docs/figs/`, `launcher/figs/`) and the demo GIFs are made by the scripts in
[`docs/scripts/`](docs/scripts/README.md). They use Playwright and the installed Microsoft Edge, on a made-up data lake
in memory. Their packages are in the `docs` dependency group, which `uv sync` does not install:

```bash
uv run --group docs docs/scripts/make_all.py
```

## Customizing

Icons are changed with CSS (below). Formats, engines, file operations and storages are added in Python, as plugins
that every explorer uses once installed. See [development-plugin.md](docs/development-plugin.md), which also covers
this repository's plugins (`plugins/`).

### Icons

The icons are JupyterLab's file browser's, as SVG images (`.jse-icon svg`).

- **Files** get the icon of their format (its `file_icon`, one of `FILE_ICONS` in `formats/base.py`), else of their
  extension. A format can bring an icon of its own, `file_icon = ("avro", "<svg ...>...</svg>")`, shown as an image
  (`.jse-icon img`).
- **Folders that a storage makes more than folders** get icons of their own: Azure accounts and containers, S3 and
  GCS buckets, SFTP servers, local drives, the memory filesystem, and Databricks' catalogs, schemas, volumes and
  workspace folders. The filesystem's mapper tells which they are (`FileSystemMapper.level`, see
  [development-plugin.md](docs/development-plugin.md)).
- **Azure, S3, GCS and Databricks** icons are in their cloud's colour, the variable `--jse-storage-color`. For example,
  `.jse-browser[data-fs-protocol="s3"] { --jse-storage-color: green; }`, or `initial` for JupyterLab's grey.

The explorer and its rows carry attributes to select them by:

| Selector                                  | Rows                                                                                                   |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------|
| `.jse-browser`                            | The explorer. Every selector starts with it, so nothing else on the page changes.                      |
| `.jse-browser[data-fs-protocol="s3"]`     | The explorer while it shows a storage of that protocol: `abfs`, `s3`, `gs`, `dbfs`, `sftp`, `file`, …  |
| `[data-fs-level="container"]`             | Folders by what the storage makes of them: `account`, `container`, `endpoint`, `bucket`, `host`, `drive`, `memory` |
| `[data-fs-level="catalog"]`               | Databricks' folders: `workspace`, `volumes`, `catalog`, `schema`, `volume`, `workspace-files`, `repos`, `users`, `shared`, `user`, `repository`, `legacy` |
| `[data-depth="0"]`, `[data-depth="1"]`, … | Folders in the tree and the list, by their level: `0` the top folder, `1` the folders in it, …    |
| `[data-file-format]`                      | Files of a known format (not those of no known format, or without a URL)                          |
| `[data-file-format="parquet"]`            | Files of one format: `parquet`, `csv`, `json`, `json-lines`, `excel`, `markdown`, `text`, `image` |
| `.jse-icon svg`, `.jse-icon::before`      | In a row, the icon's image, and where to show something else instead                              |

To change an icon, hide its image and show something else in its `::before`, e.g. an emoji. This CSS shows the top
folder as 🗄️, the folders in it as 🗃️ (deeper ones keep the folder icon), and gives data files their own icons:

```css
/* Folders: an emoji per depth */
.jse-browser :is([data-depth="0"], [data-depth="1"]) .jse-icon svg {
    display: none;
}

.jse-browser [data-depth="0"] .jse-icon::before {
    content: "🗄️";
}

.jse-browser [data-depth="1"] .jse-icon::before {
    content: "🗃️";
}

/* Files: an emoji per format */
.jse-browser [data-file-format] .jse-icon svg {
    display: none;
}

.jse-browser [data-file-format] .jse-icon::before {
    content: "📄";
}

.jse-browser [data-file-format="csv"] .jse-icon::before,
.jse-browser [data-file-format="excel"] .jse-icon::before {
    content: "📊";
}

.jse-browser [data-file-format="parquet"] .jse-icon::before {
    content: "🧱";
}

.jse-browser [data-file-format="image"] .jse-icon::before {
    content: "🖼️";
}

.jse-browser [data-file-format="markdown"] .jse-icon::before {
    content: "📝";
}
```

The storages' own logos are not shipped, as they are their owners' trademarks. You can show logos you are allowed to
use, e.g. an image of yours for S3 buckets:

```css
.jse-browser[data-fs-protocol="s3"] [data-fs-level="bucket"] .jse-icon svg {
    display: none;
}

.jse-browser[data-fs-protocol="s3"] [data-fs-level="bucket"] .jse-icon::before {
    content: url("https://example.com/my-bucket-icon.svg");
}
```

#### Test in notebooks

Run the CSS in a notebook cell, before or after an explorer, inside `<style>`. It applies to the whole page (every
explorer in it) until the page is reloaded:

```python
from IPython.display import HTML

HTML("""<style>
.jse-browser [data-depth="0"] .jse-icon svg { display: none; }
.jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
</style>""")
```

`HTML(...)` must be the last line of the cell (or use `display(HTML(...))`).

#### Apply to all of JupyterLab

JupyterLab's custom CSS applies to every page: notebooks, consoles and the launcher's explorer tabs.

1. Save the CSS, without `<style>`, as `custom/custom.css` in Jupyter's configuration directory.
   `jupyter --config-dir` prints that directory: `~/.jupyter` by default (`%USERPROFILE%\.jupyter` on Windows), or
   `$JUPYTER_CONFIG_DIR` where it is set.

   JupyterLab reads the file from there only, not from the other configuration directories. For several users, set
   `JUPYTER_CONFIG_DIR`, or put the file in each user's directory. For example, `~/.jupyter/custom/custom.css`:

   ```css
   /* Storage Explorer: the top folder as 🗄️, Parquet files as 🧱 */
   .jse-browser [data-depth="0"] .jse-icon svg { display: none; }
   .jse-browser [data-depth="0"] .jse-icon::before { content: "🗄️"; }
   .jse-browser [data-file-format="parquet"] .jse-icon svg { display: none; }
   .jse-browser [data-file-format="parquet"] .jse-icon::before { content: "🧱"; }
   ```

2. Turn it on in a `jupyter_lab_config.py`, in any of Jupyter's configuration directories (`jupyter --paths`):
   - for one user, `~/.jupyter/jupyter_lab_config.py`;
   - for an environment, `<env>/etc/jupyter/jupyter_lab_config.py`;
   - for everyone, `/etc/jupyter/jupyter_lab_config.py`.

   ```python
   c.LabApp.custom_css = True
   ```

   or start JupyterLab with `jupyter lab --custom-css`.
3. Restart JupyterLab, then reload the page.
