# Developing plugins

How to extend Storage Explorer in Python: new formats, engines (libraries reading data), file operations and storages,
and how to package them as a **plugin** that every explorer uses once installed.

This guide is for developers, and is written to be followed by AI assistants generating plugin code and projects: the
rules are stated explicitly, and the templates are complete. When generating a plugin, follow the
[rules](#rules-for-generated-code) and the [checklist](#checklist).

- [What can be extended](#what-can-be-extended)
- [Rules for generated code](#rules-for-generated-code)
- [Formats](#formats)
- [Engines and packages](#engines-and-packages)
- [Format supports](#format-supports)
- [File operations](#file-operations)
- [Filesystem mappers](#filesystem-mappers)
- [Packaging a plugin](#packaging-a-plugin)
- [Testing](#testing)
- [Checklist](#checklist)
- [Plugins of this repository](#plugins-of-this-repository)

## What can be extended

| Component                | Base class (import from)                                         | What it does                                                                   |
|--------------------------|------------------------------------------------------------------|--------------------------------------------------------------------------------|
| Format                   | `DataFormat` (`jupyter_storage_explorer.formats`)                | Recognizes a kind of file or folder (e.g. Avro files, a DuckDB database).      |
| Engine                   | `Engine` (`jupyter_storage_explorer.formats`)                    | A library users choose to view data with (e.g. DuckDB), shown in the status bar. |
| Format support           | `FormatSupport` (`jupyter_storage_explorer.formats`)             | Views a format's data with an engine, and generates code loading it.           |
| File operations          | `FileSystemOperations` (`jupyter_storage_explorer.filesystems`)  | Moves, copies, deletes, uploads, downloads files for a storage, its own way.   |
| Filesystem mapper        | `FileSystemMapper` (`jupyter_storage_explorer.filesystems`)      | Gives a storage's paths their locations (URLs), and tells storages apart.       |
| Plugin                   | `StorageExplorerPlugin` (`jupyter_storage_explorer`)             | Packages the above, so that every explorer uses them.                         |

Each component can be tried on one explorer before packaging it, given as an argument:

```python
from jupyter_storage_explorer import StorageExplorer

StorageExplorer(
    "s3://bucket/data",
    supports=[ParquetByDuckDB],         # FormatSupport classes (their formats come with them)
    operations=[ServerSideCopy()],      # FileSystemOperations objects
    filesystem_mappers=[MyMapper()],    # FileSystemMapper objects
)
```

What an explorer is given comes first, then the plugins' components, then the defaults: for each job, the first that
can do it does it.

## Rules for generated code

1. **Never import the backend library at module level.** Plugins load whether or not their libraries are installed.
   Import them inside methods, through a `PythonPackage`'s `load()` (format supports), or lazily (operations).
2. **Never add the backend library to the package's dependencies.** It goes in the `full` extra and the `dev`
   dependency group (see [Packaging a plugin](#packaging-a-plugin)).
3. **Format supports take no `__init__` arguments.** Their options are the fields of their `options_model`, set
   through `format_options`. Explorers create them from their classes.
4. **List every implemented method in `capabilities`** (`"view"`, `"recipe"`), and implement every method listed. The
   explorer reads only `capabilities`: a method not listed is never called.
5. **Raise `NotSupported`** (`FormatSupport.NotSupported`, `FileSystemOperations.NotSupported`) for what a component
   cannot handle, so that the next one is tried. Never raise it for real errors: raise those as they are.
6. **Never put credentials in locations or generated code.** Locations are sent to the browser. Declare secret options
   with `secret_field` or `secret_dict_field`, and give code its options through `options.code_value(name)`.
7. **Use frozen, keyword-only dataclasses for options and locations**, each field with a default (options).
8. **Name things by convention:** supports `<Format>By<Library>` (e.g. `ParquetByDuckDB`), their options
   `<Library>Options`, engines `<Library>Engine`, plugins `<Name>Support`, packages
   `jupyter-storage-explorer-<name>-support`.
9. **Read files through the item's context** (`ctx.head_text`, `ctx.read_whole`) unless the library reads by URL
   itself (`ctx.library_url`), so that any storage the explorer reaches works.
10. **Write docstrings** for every public class and method, in numpy style (`Parameters`, `Returns`, `Raises`).

## Formats

A `DataFormat` only detects: it says whether an item (a file or a folder) is of its kind. Formats are cheap and called
on every click, so read nothing unless needed.

```python
from jupyter_storage_explorer.formats import DataFormat


class Avro(DataFormat):
    name = "avro"            # identifier: lower case, "-" between words; used in format_options and CSS
    label = "Avro"           # shown to users
    priority = 0             # the highest-priority match wins (Delta 20 > Parquet 10 > 0 > Text -10)
    extensions = (".avro",)  # the default matches() checks these (lower case)
    file_icon = "file"       # optional: one of FILE_ICONS, or (name, "<svg ...>") of its own
```

The default `matches(ctx)` checks `extensions`. A folder format (a table of files) overrides it and looks at the
folder's listing:

```python
class DuckDBDatabase(DataFormat):
    name = "duckdb"
    label = "DuckDB database"
    extensions = (".duckdb", ".db")

    def matches(self, ctx):
        # .db is shared with SQLite: read the file's first bytes (DuckDB's magic number).
        if ctx.is_dir or not super().matches(ctx):
            return False
        return ctx.head(12)[8:12] == b"DUCK"
```

`ctx` is an `ItemContext`: `ctx.location`, `ctx.fs`, `ctx.path`, `ctx.info`, `ctx.children` (a folder's listing, None
for a file), and `ctx.is_dir`, `ctx.name`, `ctx.child_names`, `ctx.size`, `ctx.head(n)`, `ctx.head_text(n)`. A format
keeps what detection found for its supports, by location (e.g. `Parquet.layout(ctx)`). Explorers detect the formats of
their supports: a new format comes with a support of it (or a plugin's `formats`). The standard formats (Delta Lake,
Parquet, CSV, JSON Lines, JSON, Excel, Markdown, text, images) are always detected; a support can handle one of them
with another engine.

## Engines and packages

A `PythonPackage` names a package a component needs, without importing it; an `Engine` is the library users choose,
made of packages:

```python
from jupyter_storage_explorer.formats import Engine, PythonPackage


class DuckDB(PythonPackage):
    package = "duckdb"      # the distribution, as pip installs it
    import_name = "duckdb"  # the module


class DuckDBEngine(Engine):
    key = "duckdb"          # in engine_preference and format_options
    label = "DuckDB"        # shown in the status bar's engine menu
    requirements = (DuckDB(),)  # all needed; alternatives: ((PySpark(),), (DatabricksConnect(),))
```

`DuckDB().is_installed()` checks without importing; `DuckDB().load()` imports it (`load("submodule")` a submodule).
An engine is defined once, by one plugin: another plugin using it imports its class (two classes of one key are an
error). The predefined ones are `PolarsEngine`, `PandasEngine` and `PySparkEngine`, from their plugins' packages
(`jupyter_storage_explorer_polars_support`, ...). The explorer offers the engines installed that view something.

## Format supports

A `FormatSupport` handles one format's data with one engine:

```python
from inspect import cleandoc

from jupyter_storage_explorer.formats import FormatSupport, Parquet, QueryView, format_kwargs


class ParquetByDuckDB(FormatSupport):
    """Parquet files and folders with DuckDB: the data browser, and code."""

    format = Parquet                   # matched with isinstance: subclasses too
    engine = DuckDBEngine
    additional_requirements = ()       # other PythonPackage instances it needs
    capabilities = ("view", "recipe")  # the methods below
    options_model = DuckDBOptions      # see "Options"; SupportOptions (none) by default

    def view(self, fmt, ctx, options, limits):
        duckdb = DuckDB().load()
        partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
        con = duckdb.connect(**options.connect_kwargs())
        relation = con.read_parquet(fmt.data_url(ctx), hive_partitioning=partitioned)
        view = QueryView(data=relation)
        view.on_close(lambda view: con.close())  # once the explorer no longer shows it
        return view

    relation_template = cleandoc("""
        import duckdb

        rel = duckdb.read_parquet({url}{kwargs})
        """)

    def recipe(self, fmt, ctx, options):
        kwargs = format_kwargs(hive_partitioning=True if ctx.is_dir else None)
        return {"Load as relation": self.relation_template.format(url=repr(fmt.data_url(ctx)), kwargs=kwargs)}
```

### `view(fmt, ctx, options, limits)`

Returns one view. A `QueryView` opens the data browser (filters, sort, pages); the others show what was read:

| View                               | Fields                                                                 | Shown as                          |
|------------------------------------|------------------------------------------------------------------------|-----------------------------------|
| `QueryView(data=..., more=False)`  | Any dataframe narwhals supports, best lazy; `more`: eager data cut short | The data browser                  |
| `TableView(columns, rows, ...)`    | `dtypes`, `more`, `total`, `unit` ("rows", "records")                  | A table, with a note of the counts |
| `TextView(text, language=None)`    | `html`: highlighted text (optional)                                    | Text                              |
| `MarkdownView(text)`               |                                                                        | Rendered Markdown (sanitized)     |
| `TreeView(value)`                  | A JSON-like value                                                      | A collapsible tree                |
| `MediaView(mime, data=None, src=None)` | The bytes, or a URL                                                | An image (`image/*`)              |

Every view has `title` and `note`. `limits` (`ViewLimits`) says how much to read: `max_bytes`, `max_display_rows`,
`max_whole_file_bytes`, `max_live_rows`, `max_memory_rows`. Lazy data (a polars LazyFrame, a DuckDB relation, a Spark
DataFrame) is queried as the browser pages; an eager library reads at most `max_memory_rows` rows and sets
`more=True` when there were more.

A view holding a resource (a connection, a temporary file) releases it in a function given to `view.on_close(f)`: the
explorer calls it once it no longer shows the view (another preview, the panel or tab closed, the kernel exiting).
Until then, a `QueryView`'s data must stay readable.

### `recipe(fmt, ctx, options)`

Returns code by title, e.g. `{"Load as DataFrame": "import duckdb\n..."}`, shown in the right-click menu's **Python
code**, with the engine's label. Titles say what the code does, not the library. The code runs as it is in a new
notebook: imports first. Write it as class attributes `*_template` (`inspect.cleandoc`, just before the method), filled
with `str.format`: `{url}` (`repr` of the location as the library reads it) and `{kwargs}` (`format_kwargs(...)`, which
leaves out `None` and gives `", a=1, b=2"`). Recipes are shown whether the engine is installed or not.

### Options

A support's options are the fields of its `options_model`: a frozen, keyword-only dataclass subclassing
`SupportOptions`, each field with a default. Users set them with `format_options`, by engine key, then format name or
`"*"`; a function of the item's `Location` may give them per storage:

```python
from dataclasses import dataclass
from typing import Any

from jupyter_storage_explorer.formats import SupportOptions, secret_dict_field, secret_field


@dataclass(frozen=True, kw_only=True)
class DuckDBOptions(SupportOptions):
    memory_limit: str | None = None
    token: str | None = secret_field(default=None)  # never shown in code
    config: dict[str, Any] | None = secret_dict_field(default=None, secret_keys=["s3_secret_access_key"])

    def connect_kwargs(self) -> dict[str, Any]:
        return {"config": {**(self.config or {}), **({"memory_limit": self.memory_limit} if self.memory_limit else {})}}
```

```python
StorageExplorer(format_options={"duckdb": {"*": {"memory_limit": "2GB"}, "parquet": {"config": {...}}}})
```

Recipes read options with `options.code_value(name)`: `None` for a secret field, and a mapping without its secret keys.
An option that no support of the engine has is an error, so typos are caught.

### Reading the item

| `ctx`                      | What                                                                                       |
|----------------------------|--------------------------------------------------------------------------------------------|
| `ctx.library_url`          | The location as libraries read it: a local file's plain path, else its URL                 |
| `ctx.location`             | Where it is (`AbfsLocation`, `S3Location`, `LocalLocation`, ...): `ctx.location.url`       |
| `ctx.fs`, `ctx.path`       | The explorer's fsspec filesystem (with its credentials) and the item's path in it         |
| `ctx.head(n)`, `ctx.head_text(n)` | The first bytes; the first text and whether it was cut                             |
| `ctx.read_whole(limits)`   | The whole file, refused over `limits.max_whole_file_bytes`                                 |
| `ctx.info`, `ctx.size`     | Its fsspec info; its size                                                                  |
| `ctx.children`, `ctx.child_names`, `ctx.is_dir` | A folder's listing, its names, whether it is a folder                 |

Libraries doing their own I/O (polars, DuckDB, Spark) read `ctx.library_url` with their own credentials (the
environment, or options); others read through `ctx.fs`, so that any storage the explorer reaches works.

## File operations

A `FileSystemOperations` does some operations for some storages and leaves the rest to the next, by raising
`NotSupported`. Override only what it does:

| Method                                                                      | Does                                          |
|-----------------------------------------------------------------------------|-----------------------------------------------|
| `move(source_fs, source, target_fs, target, progress, *, same)`             | Moves a file or folder                        |
| `copy(source_fs, source, target_fs, target, progress, *, same)`             | Copies a file or folder                       |
| `delete(fs, path, progress)`                                                | Deletes a file or folder                      |
| `download(fs, path, local_path, progress)`, `upload(local_path, fs, path, progress)` | To and from the kernel's disk         |
| `mkdir(fs, path)`                                                           | Creates a folder                              |
| `measure(fs, path, progress=None)`                                          | Counts files and bytes (`Measurement`)        |
| `_copy_file(...)`, `_move_file(...)`                                        | One file between filesystems                  |

`same` says whether the source and target are one storage, as the mappers tell.

```python
from jupyter_storage_explorer.filesystems import FileSystemOperations


class ServerSideCopy(FileSystemOperations):
    """Copies within one storage with its own API; everything else as by default."""

    def __init__(self, concurrency: int = 16) -> None:
        self.concurrency = concurrency

    def copy(self, source_fs, source, target_fs, target, progress, *, same):
        if not same or type(source_fs).__name__ != "MyFileSystem":
            raise self.NotSupported
        progress.working_on(source.rsplit("/", 1)[-1])
        source_fs.server_copy(source, target)
        progress.advance(files=1)
```

Operations run in a worker thread: report to `progress` (`advance`, `working_on`) and call `progress.check()` between
steps, which raises `OperationCancelled` when the user cancels. Import the storage's SDK lazily, and raise
`NotSupported` when it is missing, so that the defaults take over. `AzureDataLakeGen2Operation`
([plugins/abfs-support](plugins/abfs-support)) is a complete example.

## Filesystem mappers

A `FileSystemMapper` turns the paths of one fsspec implementation's filesystems into locations, and back. Locations are
where files are, independently of the implementation: their `url` is what "Copy URL", previews, recipes and the transfer
policy use, and how files copied from another kernel are found.

```python
import dataclasses

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems import FileSystemMapper


@dataclasses.dataclass(frozen=True, kw_only=True)
class MyLocation(Location):
    kind = "myfs"   # its name in JSON, unique
    server: str     # strings, integers and None only; never credentials
    path: str

    @property
    def url(self):
        return f"myfs://{self.server}/{self.path.lstrip('/')}"


class MyMapper(FileSystemMapper):
    classes = ("mypackage.MyFileSystem",)  # matched by qualified name, subclasses too: no import

    def to_location(self, fs, path):
        return MyLocation(server=fs.server.lower(), path=path)

    def path_of(self, fs, location):
        # None unless this instance reaches the location.
        if isinstance(location, MyLocation) and location.server == fs.server.lower():
            return location.path
        return None
```

Normalize locations when made (lower-case hosts, no trailing "/"): equal locations must name the same item. The
predefined mappers cover Azure, S3, Google Cloud Storage, SFTP, local disks and memory; other filesystems get fsspec's
URLs.

## Packaging a plugin

A plugin is a package registering a `StorageExplorerPlugin` subclass as an entry point. One plugin per engine (DuckDB,
PyArrow, ...) or per storage (Azure, S3, ...). Develop it with [uv](https://docs.astral.sh/uv/).

### Layout

```
jupyter-storage-explorer-duckdb-support/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── jupyter_storage_explorer_duckdb_support/
│       ├── __init__.py      # the plugin class and its options; exports
│       └── supports.py      # engine, packages, formats, supports, their options
└── tests/
    ├── conftest.py          # the explorer's test fixtures (see Testing)
    └── test_duckdb_supports.py
```

### `pyproject.toml`

```toml
[project]
name = "jupyter-storage-explorer-duckdb-support"
version = "0.1.0"
description = "DuckDB support for Storage Explorer"  # shown to users, in "About"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
# The explorer only: never the backend library (see "full").
dependencies = ["jupyter-storage-explorer>=0.14,<0.15"]

# The libraries it uses: installed only on request, so that installing the
# plugin never changes those of a shared environment.
[project.optional-dependencies]
full = ["duckdb>=1.0"]

# Explorers find the plugin by this entry point, named by its key.
[project.entry-points."jupyter_storage_explorer.plugins"]
duckdb-support = "jupyter_storage_explorer_duckdb_support:DuckDBSupport"

[dependency-groups]
dev = ["duckdb>=1.0", "pytest>=8"]  # the libraries, and what the tests need

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jupyter_storage_explorer_duckdb_support"]
```

- `name`: `jupyter-storage-explorer-<name>-support`; the module `jupyter_storage_explorer_<name>_support`.
- `description`: "<Name> support for Storage Explorer". It is the plugin's name for users ("About" shows it).
- `dependencies`: the explorer, within the minor version you test with (the plugin API may change between minor
  versions).
- `full`: the backend libraries. Users install `pip install "jupyter-storage-explorer-duckdb-support[full]"` to get
  them, or the plugin alone to use those already installed.
- The entry point's name is the plugin's `key`: `<name>-support`.

### The plugin class

```python
"""DuckDB support for Storage Explorer."""

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer_duckdb_support.supports import (
    DuckDBDatabase,
    DuckDBEngine,
    DuckDBOptions,
    ParquetByDuckDB,
    ServerSideCopy,
)


@dataclass(frozen=True, kw_only=True)
class DuckDBSupportOptions(StorageExplorerPluginOptions):
    """The plugin's options (plugin_options={"duckdb-support": {...}}): enabled,
    priority, and its own."""

    concurrency: int = 16


class DuckDBSupport(StorageExplorerPlugin):
    key = "duckdb-support"  # = the entry point's name
    options_model = DuckDBSupportOptions
    options: DuckDBSupportOptions

    @property
    def format_supports(self):  # FormatSupport classes (their options: format_options)
        return (ParquetByDuckDB,)

    @property
    def formats(self):  # DataFormat classes no support names (rare)
        return ()

    @property
    def filesystem_operations(self):  # objects, made with the plugin's options
        return (ServerSideCopy(concurrency=self.options.concurrency),)

    @property
    def filesystem_mappers(self):  # objects (or classes, created without arguments)
        return ()


__all__ = ["DuckDBEngine", "DuckDBOptions", "DuckDBSupport", "DuckDBSupportOptions", "ParquetByDuckDB"]
```

- Explorers create the plugin with its options, an `options_model` object (`self.options`), from
  `plugin_options={"duckdb-support": {"concurrency": 8}}` (in the launcher's tabs, `plugin_options()`). Every plugin
  has `enabled` (False: not used, not even imported) and `priority` (higher first; then by key). An option the model
  lacks is an error.
- Plugin options configure the components made with arguments (operations, mappers). Format supports get theirs from
  `format_options`, by engine key.
- `name`, `description` and `version` come from the package's metadata (`[project]`): the class does not repeat them.
- A plugin that cannot be imported or created is left out with a warning, and greyed out in "About".

### Develop and install

```bash
uv init --lib jupyter-storage-explorer-duckdb-support   # or copy the layout above
uv sync                      # the plugin (editable), the explorer, the dev group
uv run pytest
uv build                     # dist/: the wheel and sdist
uv publish                   # to PyPI (or --publish-url for another index)
```

`uv sync` installs the plugin editable, with its entry point: explorers in `uv run jupyter lab` use it at once. After
changing `pyproject.toml` (the description, the entry point), run `uv sync` again.

## Testing

A plugin's tests are in its own `tests/` and test its own code: its supports' views and code, their options, its
engine, operations and mappers, and its entry point. They need no browser: components get items as the explorer gives
them (`ItemContext`), made by `jupyter_storage_explorer.testing` on fsspec's memory filesystem, or local files for
libraries reading by URL. Its fixtures come through `tests/conftest.py`:

```python
"""Items as the explorer gives them to the plugin's supports."""

from jupyter_storage_explorer.testing import make_item, memfs  # noqa: F401
```

- `memfs`: fsspec's memory filesystem, emptied.
- `make_item(path, data=None, location=None)`: writes `data` there (or lists the folder) and returns the item;
  `location` gives it another, e.g. an `S3Location` for the code of an S3 file.
- `item_of(fs, path, location=None)` and `local_item(path)`: an item of any filesystem, or a local file (e.g. in
  `tmp_path`).

The tests' libraries go in the `dev` group, so that `uv run pytest` runs them with the plugin's dependencies only:

```python
from jupyter_storage_explorer.formats import FormatSupport, Parquet, QueryView, ViewLimits
from jupyter_storage_explorer.testing import local_item


def test_view(tmp_path):
    path = tmp_path / "a.parquet"
    ...  # write a Parquet file
    view = ParquetByDuckDB().view(Parquet(), local_item(path), DuckDBOptions(), ViewLimits())
    assert isinstance(view, QueryView)
    view.close()


def test_code(make_item):
    code = ParquetByDuckDB().recipe(Parquet(), make_item("/a.parquet", b""), DuckDBOptions())
    assert "read_parquet('memory:///a.parquet')" in code["Load as a relation"]


def test_capabilities_are_implemented():
    for name in ParquetByDuckDB.capabilities:
        assert getattr(ParquetByDuckDB, name) is not getattr(FormatSupport, name)


def test_plugin_registered():
    from importlib.metadata import entry_points

    [entry_point] = entry_points(group="jupyter_storage_explorer.plugins", name="duckdb-support")
    plugin = entry_point.load()()  # loads without the backend library
    assert plugin.key == "duckdb-support"
    assert plugin.description == "DuckDB support for Storage Explorer"
```

Try it in a browser with `uv run jupyter lab`: the plugin's engine is in the status bar's engine menu, and ⚙ → **About**
lists the plugin with its version.

## Checklist

- [ ] Package `jupyter-storage-explorer-<name>-support`, module `jupyter_storage_explorer_<name>_support`.
- [ ] `description = "<Name> support for Storage Explorer"`.
- [ ] `dependencies`: the explorer only; the backend libraries in the `full` extra and the `dev` group.
- [ ] Entry point in `jupyter_storage_explorer.plugins`, named by the plugin's `key`.
- [ ] No backend import at module level; packages through `PythonPackage.load()` inside methods.
- [ ] Supports: `format`, `engine`, `capabilities` matching the methods, `options_model`; no `__init__` arguments.
- [ ] Secrets declared with `secret_field` / `secret_dict_field`; code options through `options.code_value`.
- [ ] Views holding resources release them with `on_close`.
- [ ] Operations raise `NotSupported` for what they do not do, report progress and call `progress.check()`.
- [ ] Locations: frozen keyword-only dataclasses, normalized, without credentials.
- [ ] Tests in the plugin's `tests/`, of its own code, run with `uv run pytest`; the plugin loads from its entry point.
- [ ] README: what it adds, `pip install "<package>[full]"`, its options.

## Plugins of this repository

The plugins in [`plugins/`](plugins) (polars, pandas, pyspark, abfs) follow these conventions and are released with the
explorer, at its version: each requires the explorer of exactly its own version (its `hatch_build.py`), and the
explorer's extras install them (`polars`: with its libraries; `polars-support`: alone). To add one:

1. Copy one of them (e.g. `plugins/polars-support`), renaming the package, module, plugin class and entry point. Its
   tests are in its `tests/`, named `test_<name>_*.py` (pytest at the root runs every plugin's, and imports test files
   by name).
2. Add its name to `PLUGINS` in the root's and the launcher's `hatch_build.py` (the extras), and the package to the
   root's dev dependencies and `[tool.uv.sources]`.
3. Give it a release workflow, `.github/workflows/release-<plugin>.yaml` (a copy of another's), and its PyPI project a
   trusted publisher for it (see [One-time setup for PyPI](DEVELOPMENT.md#one-time-setup-for-pypi)).
4. List it in [docs/storage-explorer.md](docs/storage-explorer.md#plugins)'s table and the README's extras.
