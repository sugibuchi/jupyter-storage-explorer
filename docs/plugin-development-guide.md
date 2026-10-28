# Plugin development guide

How to extend Storage Explorer in Python: new formats, engines (libraries reading data), file operations and storages,
and how to package them as a **plugin** that every explorer uses once installed.

For views and code snippets of your own use, a file of actions is enough: see the
[Action development guide](action-development-guide.md).

This guide is for developers, and is written to be followed by AI assistants generating plugin code and projects: the
rules are stated explicitly, and the templates are complete. When generating a plugin, follow the
[rules](#rules-for-generated-code), [how to work](#writing-a-plugin-with-an-ai-assistant) and the
[checklist](#checklist).

- [What can be extended](#what-can-be-extended)
- [Rules for generated code](#rules-for-generated-code)
- [Writing a plugin with an AI assistant](#writing-a-plugin-with-an-ai-assistant)
- [Formats](#formats)
- [Engines and packages](#engines-and-packages)
- [Actions](#actions)
- [File operations](#file-operations)
- [Filesystem mappers](#filesystem-mappers)
- [Packaging a plugin](#packaging-a-plugin)
- [Testing](#testing)
- [Checklist](#checklist)
- [Plugins of this repository](#plugins-of-this-repository)

## What can be extended

| Component                | Defined with (import from)                                       | What it does                                                                   |
|--------------------------|------------------------------------------------------------------|--------------------------------------------------------------------------------|
| Format                   | `DataFormat` (`jupyter_storage_explorer.formats`)                | Recognizes a kind of file or folder (e.g. Avro files, a DuckDB database).      |
| Engine                   | `Engine` (`jupyter_storage_explorer`)                            | A library users choose to view data with (e.g. DuckDB), shown in the status bar. |
| View action              | `@view` (`jupyter_storage_explorer.actions`)                     | A function viewing a format's data with an engine: the preview panel, a tab.   |
| Code action              | `@code` (`jupyter_storage_explorer.actions`)                     | A function giving code loading a format's data with an engine: "Python code".  |
| File operations          | `FileSystemOperations` (`jupyter_storage_explorer.filesystems`)  | Moves, copies, deletes, uploads, downloads files for a storage, its own way.   |
| Filesystem mapper        | `FileSystemMapper` (`jupyter_storage_explorer.filesystems`)      | Gives a storage's paths their locations (URLs), and tells storages apart.       |
| Plugin                   | `StorageExplorerPlugin` (`jupyter_storage_explorer`)             | Packages the above, so that every explorer uses them.                         |

Each component can be tried in an explorer before packaging it: see
[Trying components in an explorer](#trying-components-in-an-explorer).

## Rules for generated code

1. **Never import the backend library at module level.** Plugins load whether or not their libraries are installed.
   Import it inside the functions of actions, e.g. `import duckdb`, and lazily in operations.
2. **Never add the backend library to the package's dependencies.** It goes in the `full` extra and the `dev`
   dependency group (see [Packaging a plugin](#packaging-a-plugin)).
3. **Options are data.** An action's options are the fields of the class its `options` parameter is annotated with,
   set through `engine_options`. Write what an action does with them as functions taking them. Methods of options only
   give views of them, e.g. `code_value`.
4. **Refuse what a component cannot handle**, so that the next one is tried:
   - An action's `check` refuses the items its library cannot handle, without reading the storage. Once an action is
     chosen, no other is tried, and what it raises is the item's error.
   - File operations raise `FileSystemOperations.NotSupported`. Never raise it for real errors: raise those as they are.
5. **Ask before reading much.** A view reading a whole large file, or whose every query of the data browser does,
   returns a `ViewWithConfirmation` or a `ViewWithChoice`, which reads once the user answers.
6. **Never put credentials in locations or generated code.** Locations are sent to the browser. Declare secret options
   with `secret_field` or `secret_dict_field`, and give code its options through `options.code_value(name)`.
7. **Use frozen, keyword-only dataclasses for options and locations**, each field with a default (options).
8. **Name things by convention:**
   - views `<format>_view`, code `<format>_as_<what it loads>`, e.g. `parquet_view` and `parquet_as_relation`;
   - checks by what they decide, e.g. `_read_by_duckdb` or `_can_offer_recipe`;
   - options `<Library>Options`, and each format's `<Format>By<Library>Options`;
   - engines `<Library>Engine`, plugins `<Name>Support`, packages `jupyter-storage-explorer-<name>-support`.
9. **Reach any storage the explorer reaches.** Where the library cannot read the item's URL itself, hand it the
   explorer's filesystem, or read through the item's context: see [Reading the item](#reading-the-item).
10. **Write docstrings** for every public class and function, in numpy style (`Parameters`, `Returns`, `Raises`).

## Writing a plugin with an AI assistant

An AI assistant can write a plugin from this guide. Give it what a person would need:

- this guide, and CLAUDE.md when it works in this repository;
- the library, installed for development as [Packaging a plugin](#packaging-a-plugin) says;
- read access to a real storage or real data, e.g. public datasets;
- a scratch place it may write to, or none: then it must not write.

Point it at the plugin of this repository closest to the task, to copy:

| Plugin to write           | Closest example                                                                             |
|---------------------------|---------------------------------------------------------------------------------------------|
| An engine                 | [polars-support](../plugins/polars-support), [pandas-support](../plugins/pandas-support) or [duckdb-support](../plugins/duckdb-support) |
| An engine on a cluster    | [pyspark-support](../plugins/pyspark-support)                                               |
| File operations           | [abfs-support](../plugins/abfs-support)                                                     |
| A storage with locations  | [databricks-support](../plugins/databricks-support)                                         |

A prompt can be as short as this:

```text
Write a <name>-support plugin for Storage Explorer, for <library>. Follow docs/plugin-development-guide.md.
You may read <storage or data>. Never write to it.
```

The assistant works in this order:

1. **Probe the real library and storage** before writing code, as [Check the real filesystem first](#check-the-real-filesystem-first)
   says for storages. Libraries and storages behave in ways no guide can list. For an engine, measure on a large
   file, through a filesystem counting the bytes it reads, such as `CountingFileSystem` in dask-support's tests:
   - what each of the [ways of reading](#reading-the-item) reads to make the view;
   - what each query of the data browser reads: the first page, a filter, a sort, the count of rows (narwhals'
     `head`, `filter`, `sort`, `len` on the library's data);
   - whether the data made in one thread can be read in another, as the browser does;
   - what the data browser's memory mode collects the data into, through narwhals.
2. **Write the components**, following the [rules](#rules-for-generated-code).
3. **Test on fakes built from what the probes showed**, not from assumptions. A fake written from a guess only confirms
   the guess.
4. **Try it in an explorer**, as [Trying components in an explorer](#trying-components-in-an-explorer) says.
5. **Go through the [checklist](#checklist)**, and report what it guessed and what it could not test.

Review its result as any contribution. Look first at what it could not test, such as writes to a real storage.

## Formats

A `DataFormat` only detects: it says whether an item (a file or a folder) is of its kind. `matches()` is called for
every file of a listing, so it reads nothing: the name, or a folder's listing, only.

```python
from jupyter_storage_explorer.formats import DataFormat


class Avro(DataFormat):
    name = "avro"            # identifier: lower case, "-" between words, unique; used in engine_options and CSS
    label = "Avro"           # shown to users
    priority = 0             # the highest-priority match wins (Delta 20 > Parquet 10 > 0 > Text -10)
    extensions = (".avro",)  # the default matches() checks these (lower case)
    file_icon = "file"       # optional: one of FILE_ICONS, or (name, "<svg ...>") of its own
```

Give a format of your own an icon with `file_icon`: users tell files apart by it in the list.

Two format classes of one name are an error: explorers choose formats by name, in `engine_options`, previews and
menus. A subclass of a format, e.g. a TSV of `Csv`, takes a name of its own.

A format of text files subclasses `Text`, e.g. `class GeoJson(Text)`. Its files can then always be viewed as plain
text, in **Preview as**, and opened in JupyterLab's text editor. Its priority is 0 by default, not the fallback's -10.

The default `matches(ctx)` checks `extensions`. A folder format (a table of files) overrides it and looks at the
folder's listing (`ctx.children`, `ctx.child_names`).

A format whose files have a binary signature checks it with `sniff`, given the file's first `sniff_bytes` bytes. Give
it to every format that has one, above all for a common extension (`.db`: SQLite's and DuckDB's): it is checked
whenever the file is clicked, whichever formats are installed, as files in a storage need not be what installed plugins
expect. Listings never read files, so such files show no format there until clicked; folders are never sniffed.

```python
class DuckDBDatabase(DataFormat):
    name = "duckdb"
    label = "DuckDB database"
    extensions = (".duckdb", ".db")
    sniff_bytes = 12  # the first 12 bytes, read once for all formats sniffing the file

    def sniff(self, ctx, head):
        return head[8:12] == b"DUCK"  # DuckDB's magic number (fewer bytes if the file is shorter)
```

`ctx` is an `ItemContext`, with these:

- `ctx.location`, `ctx.fs`, `ctx.path` and `ctx.info`;
- `ctx.children`, a folder's listing, None for a file;
- `ctx.is_dir`, `ctx.name`, `ctx.child_names` and `ctx.size`;
- `ctx.head(n)` and `ctx.head_text(n)`.

A format keeps what detection found for its actions, by location, e.g. `Parquet.layout(ctx)`. Explorers detect the
formats of their actions: a new format comes with an action of it, or with a plugin's `formats`. The standard formats
are always detected: Delta Lake, Parquet, CSV, JSON Lines, JSON, Excel, Markdown, text and images. An action can handle
one of them with another engine.

A plugin's format may have code actions only. Its items then have no preview, and **Python code** offers their code.

## Engines and packages

A `PythonPackage` names a package a component needs, without importing it. An `Engine` is the library users choose,
made of packages:

```python
from jupyter_storage_explorer import Engine, PythonPackage


class DuckDB(PythonPackage):
    package = "duckdb"      # the distribution, as pip installs it
    import_name = "duckdb"  # the module


class DuckDBEngine(Engine):
    key = "duckdb"          # in engine_preference and engine_options
    label = "DuckDB"        # shown in the status bar's engine menu
    requirements = (DuckDB(),)  # all needed
```

`DuckDB().is_installed()` checks without importing. The explorer checks so before offering an engine or an action.
Actions import the library themselves, inside their functions.

An engine's `requirements` are every package its views need to run, not only the library's own. Dask's DataFrames, for
example, need pandas and PyArrow, which plain `dask` does not install. Otherwise the engine is offered where every view
fails.

A package whose module other packages may bring a copy of sets `own_distribution = True`. Its module then counts only
with the package's own distribution installed: pyspark-support's `PySpark` does so, as Databricks Connect brings a
pyspark module of its own.

An engine is defined once, by one plugin: another plugin using it imports its class. Two engine classes of one key are
an error. The predefined engines come from their plugins' packages, e.g. `jupyter_storage_explorer_polars_support`:

- `PolarsEngine`, `PandasEngine`, `DuckDBEngine` and `DaskEngine`;
- `PySparkEngine` and `DatabricksConnectEngine`.

`PythonEngine`, in `jupyter_storage_explorer.actions.python`, is the engine of the built-in actions: Python alone, with
the explorer's own packages. The explorer offers the engines installed that view something, never `PythonEngine`.

A library used only in generated code, e.g. Hugging Face's `datasets`, gets an engine of its own with code actions
only. The engine menu leaves it out, as it views nothing. **Python code** still shows its code, under its label.

Packages are defined where they belong: an engine's own (`Polars`, `Pandas`, `PySpark`, `DatabricksConnect`) and
the libraries only that engine uses (`Fastexcel` for polars, `DeltaSpark` for Spark) by the engine's plugin, beside
its `Engine`; the libraries several engines may use (`Fsspec`, `PyArrow`, `DeltaLake`, `Openpyxl`, and the
core's `Pillow`) by the core, in `jupyter_storage_explorer.packages`. A new plugin imports those, and defines
its own engine's and its engine-only libraries.

A package another engine's plugin defines, e.g. pandas-support's `Pandas`, may be defined again in yours: packages,
unlike engines, may be defined twice. Never import another plugin for it, which would make yours depend on it.

Where the library keeps global settings deciding how queries run, e.g. a Dask distributed `Client` or its scheduler,
never change them from an action. Use what is active, and say in the README how the user's settings apply.

## Actions

An action is a function doing one thing with one format's data and one engine. There are two kinds, each made by a
decorator of `jupyter_storage_explorer.actions`:

- `@view` makes a view, shown in the preview panel or a tab of its own;
- `@code` gives one snippet of Python loading the data, shown in the right-click menu's **Python code**.

A format and an engine may have any number of actions, e.g. Parquet with DuckDB viewed in the data browser and in a
widget. A plugin registers its actions in order with `register_actions`. Explorers try them in that order: the first
view doing an item is its default, and **Preview as** lists the others of its engine by their labels.

```python
from inspect import cleandoc

from jupyter_storage_explorer import ItemContext
from jupyter_storage_explorer.actions import code, register_actions, view
from jupyter_storage_explorer.filesystems.locations import LocalLocation
from jupyter_storage_explorer.formats import DataFormat, Parquet
from jupyter_storage_explorer.packages import PyArrow
from jupyter_storage_explorer.util import format_kwargs
from jupyter_storage_explorer.views import QueryView, View


def _read_by_duckdb(fmt: DataFormat, ctx: ItemContext, options: DuckDBOptions) -> bool:
    """Whether DuckDB reads the item: local files only. DuckDB reads cloud storage only with its extensions
    configured, and other storages through the explorer's filesystem (see "Reading the item")."""
    return isinstance(ctx.location, LocalLocation)


def _data_url(fmt: Parquet, ctx: ItemContext) -> str:
    url = fmt.data_url(ctx)  # a file's path, or a glob of a folder's data files
    if ctx.is_dir and fmt.layout(ctx).files == "*":
        # Data files without an extension (Hive's): not "_SUCCESS" or ".crc" checksums, which DuckDB would read.
        url = url.removesuffix("*") + "[!_.]*"
    return url


# The code's template: {url}, the location as DuckDB reads it, and {kwargs}, the keyword arguments.
_RELATION = cleandoc("""
    import duckdb

    rel = duckdb.read_parquet({url}{kwargs})
    """)


@code(format=Parquet, engine=DuckDBEngine, label="Load as relation", check=_read_by_duckdb)
def parquet_as_relation(fmt: Parquet, ctx: ItemContext, options: DuckDBOptions) -> str:
    """A Parquet file or folder, as a DuckDB relation."""
    kwargs = format_kwargs(hive_partitioning=True if ctx.is_dir else None)
    return _RELATION.format(url=repr(_data_url(fmt, ctx)), kwargs=kwargs)


@view(format=Parquet, engine=DuckDBEngine, requires=(PyArrow(),), check=_read_by_duckdb, code=parquet_as_relation)
def parquet_view(fmt: Parquet, ctx: ItemContext, options: DuckDBOptions) -> View:
    """A Parquet file or folder in the data browser."""
    import duckdb  # inside the function: the plugin loads without DuckDB

    partitioned = ctx.is_dir and bool(fmt.layout(ctx).keys)
    con = duckdb.connect(**connect_kwargs(options))
    relation = con.read_parquet(_data_url(fmt, ctx), hive_partitioning=partitioned)
    view = QueryView(data=relation)
    view.on_close(lambda view: con.close())  # once the explorer no longer shows it
    return view


# In the order tried.
DUCKDB_ACTIONS = register_actions(parquet_view, parquet_as_relation)
```

The decorators' arguments:

| Argument   | Of            | What                                                                                              |
|------------|---------------|---------------------------------------------------------------------------------------------------|
| `format`   | both          | The format, matched with `isinstance`: its subclasses too, unless they have actions of that kind of their own. Also positional, e.g. `@view(Parquet, DuckDBEngine)`. |
| `engine`   | both          | The engine; by default `PythonEngine`, Python alone. Also positional.                            |
| `label`    | both          | What users see; `{format}` and `{engine}` are replaced by their labels. A view's default is `"View as {format} ({engine})"`; a code action's, its function's name. |
| `requires` | both          | Packages needed besides the engine's, as instances. The action is offered only when they are installed. |
| `check`    | both          | `check(fmt, ctx, options) -> bool`: whether the action does an item. By default, every item of `format`. |
| `code`     | `@view` only  | The code action reproducing what the view shows, of the same format and engine.                    |

The rules for the functions:

- They take the parameters they name, in any order: `fmt`, `ctx`, `options`, and `limits` for a view, or parts of
  the item, `url`, `url_or_local_path`, `name`, `path`, `size`, `is_dir` and `fs`. The decorator checks them; another needs a default.
  Name only those the function uses, as this repository's plugins do.
- Whatever their functions name, explorers call actions by position: `view(fmt, ctx, options, limits)`,
  `code(fmt, ctx, options)` and `does(fmt, ctx, options)`. Call them so in tests too. `action.options_model()` gives
  an action's default options, `ActionOptions()` for one without an options class.
- Keep `options` with its annotation, used or not, when it names an options class: it is the action's options model,
  which a view and its code share.
- A view returns a `View`. A user's may also return other values, made views:
  - a dataframe, shown in the data browser;
  - a `str`, shown as text;
  - a `dict` or `list`, shown as a tree;
  - a Jupyter widget, shown as it is in a `JupyterWidgetView`.
- The class of `options` comes from the parameter's annotation, read when the function is decorated. Import that class
  at run time, not only for type checkers, and define it at the module's top level.
- A label is unique for its kind, format and engine, whatever plugin it comes from: two actions of one label are an
  error, as users could not tell them apart. Label a view by what it shows, e.g. "Sheets in a tree ({engine})".
- **Preview as** shows a view's label only when its engine has several views of an item; otherwise it shows the
  format and the engine, e.g. "CSV (Polars)".
- Explorers tell actions apart by their `id`, a number each action gets when it is made. The page sends it back to
  choose a view, so the label is free to change.
- `requires` lists the packages the action itself needs, besides the engine's:
  - for a code action, those its snippet imports, which **Python code** shows under it as "Needs ...";
  - for a view, also what the data browser needs. It collects each page of lazy data, in either mode, into the library
    narwhals collects it into, e.g. PyArrow for a DuckDB relation or a Spark DataFrame.
- An action reads as its function: `help()`, IDEs and errors show its name, docstring and signature.

### Checks

`check(fmt, ctx, options)` runs on the kernel's main thread, for each item clicked. It decides from the format, the
location, the path, the info and the options, never by reading the storage. Name it by what it decides, e.g.
`_read_by_duckdb`, and use the same function inside the actions when they choose how to read. Once an action is chosen,
no other is tried, and what it raises is the item's error.

### `@view`: `view(fmt, ctx, options, limits)`

Returns one view. A `QueryView` opens the data browser (filters, sort, pages). A `TableSetView` offers several tables,
and opens the data browser on the one chosen. The others show what was read:

| View                               | Fields                                                                 | Shown as                          |
|------------------------------------|------------------------------------------------------------------------|-----------------------------------|
| `QueryView(data=..., more=False, fetch=None)`  | Any dataframe narwhals supports, best lazy; `more`: only the item's first part (rows or bytes); `fetch`: how the browser reads rows of the data, see below | The data browser                  |
| `TableSetView(nodes, loader, selector="tree")` | `nodes`: tables (`Leaf(label, id)`), maybe in groups (`Node(label, children)`), each with an `icon` (`"folder"`, `"database"` or `"table"`); `loader(id)`: a table's dataframe, as `QueryView`'s `data` | The tables in a tree (`"tree"`) or on tabs (`"tab"`, tables only), and the data browser on the one chosen |
| `TableView(columns, rows, ...)`    | `dtypes`, `more`, `total`, `unit` ("rows", "records")                  | A table, with a note of the counts |
| `TextView(text, language=None)`    | `html`: highlighted text (optional)                                    | Text                              |
| `MarkdownView(text)`               |                                                                        | Rendered Markdown (sanitized)     |
| `TreeView(value)`                  | A JSON-like value                                                      | A collapsible tree                |
| `MediaView(mime, data=None, src=None)` | The bytes, or a URL                                                | An image (`image/*`)              |
| `JupyterWidgetView(widget)`        | An `ipywidgets.DOMWidget`, new for the view, which closes it           | The widget, by the page's widget manager |
| `ViewWithConfirmation(message, factory)` | `factory()`: the view; `button` ("View")                         | The message, Cancel and `button`  |
| `ViewWithChoice(message, choices, factory, style="radio")` | `choices`: labels to values; `factory(value)`: the view; `default`; `with_cancel` (False) | Radio buttons or a dropdown with `button`, or a button of each label (`"button"`); Cancel only `with_cancel` |
| `ViewWithInput(message, factory)`  | `factory(text)`: the view; `value`, `placeholder`                      | A text field and `button`         |

The data browser reads rows of lazy data with `fetch(lf, offset, length)`: the first rows when the data opens, and each
page of live queries. `lf` is a narwhals LazyFrame of the data with the browser's filters, sort and hidden columns
applied, and `fetch` returns rows `offset` to `offset + length` as a narwhals DataFrame, or None to pass them on:

1. the explorer's `fetch_rows`, the user's;
2. the view's `fetch`, an action's, for a library with a cheaper way than the default, e.g. pyspark-support's
   `spark_rows`, which skips rows with Spark's `offset`;
3. the core's default, which skips rows itself for polars and DuckDB, reads Dask partition by partition (sorted
   data in one pass), and reads all rows up to `offset + length` for others.

Every view has `title` and `note`. `limits` (`ViewLimits`) says how much to read: `max_bytes`, `max_display_rows`,
`max_whole_file_bytes`, `max_live_rows`, `max_memory_rows`. Lazy data (a polars LazyFrame, a DuckDB relation, a Spark
DataFrame) is queried as the browser pages; an eager library reads at most `max_memory_rows` rows and sets
`more=True` when there were more.

A view holding a resource (a connection, a temporary file) releases it in a function given to `view.on_close(f)`: the
explorer calls it once it no longer shows the view (another preview, the panel or tab closed, the kernel exiting).
Until then, a `QueryView`'s data must stay readable, as must a `TableSetView`'s tables: its `loader` is called each
time a table is chosen or read again, e.g. a database's tables from one connection, closed in `on_close`:

```python
con = duckdb.connect(path, read_only=True)  # a local file's path: DuckDB opens databases itself
tables = con.sql("select table_schema, table_name from information_schema.tables").fetchall()  # views too


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


# By SQL: con.table fails for a view named with its schema ("main"."v"), and for names needing quotes.
sql = {f"{s}.{t}": f"select * from {quoted(s)}.{quoted(t)}" for s, t in tables}
schemas = sorted({schema for schema, _ in tables})
view = TableSetView(
    nodes=[
        Node(
            label=s,
            children=[Leaf(label=t, id=f"{s}.{t}") for schema, t in tables if schema == s],
            icon="database",  # a schema; groups are folders by default
        )
        for s in schemas
    ],
    loader=lambda id: con.sql(sql[id]),
)
view.on_close(lambda view: con.close())
```

A `TableSetView` needs at least one table: show another view, e.g. a `TextView`, for an item without any.

The last three ask the user before the view is made, e.g. before reading a whole large file:

- The question shows where the view would be, in the preview panel or the tab.
- Once the user answers, the explorer calls `factory` in a worker thread, as it calls a view action. It may return
  another prompt.
- When the data browser reads the data again, the same answers are given without asking.
- The prompt is closed with the view of its answer, so its `on_close` may release what that view reads.

polars-support asks so for CSV and JSON Lines files on storages polars cannot read itself:

```python
return ViewWithChoice(
    message="Polars cannot read this storage itself: the file is read into memory, then queried there.",
    choices={"Its first 10 MB": 10 * 2**20, "The whole file (586 MB)": None},
    factory=read,  # read(first): a QueryView of the first bytes, or of the whole file
    style="button",
    with_cancel=True,  # not reading is a choice too
)
```

A view action runs in a worker thread, so that a slow view leaves the kernel free:

- The preview or tab shows "Loading…" until it returns.
- Views of other items may be made at the same time.
- It never touches widgets or displays anything.
- What the view holds is read later in other threads, one request at a time: the data browser's pages, a table chosen.
  A connection opened in the view must allow that, e.g. `sqlite3.connect(path, check_same_thread=False)`.

### `@code`: `code(fmt, ctx, options)`

Returns one snippet of Python, shown in the right-click menu's **Python code** under the engine's label. Its `label` is
its title, e.g. "Load as LazyFrame": it says what the code does, as the engine is shown already. Give several snippets as several
code actions, e.g. a LazyFrame and a DataFrame.

- The code runs as it is in a new notebook: its imports first, then what else it needs, e.g. a Spark session.
- Installing the packages and configuring access to the storage are left to the user.
- It reads the location as the library reads it. The two differ only for local files:
  - `ctx.url_or_local_path` for a library, as not every library reads `file://` URLs;
  - `ctx.url` where a URL is needed, e.g. to name fsspec's protocol, as `fsspec.url_to_fs` does.
- Write multi-line code as a module-level template made with `inspect.cleandoc`, filled with `str.format`, e.g.
  `{url}` (`repr` of the location) and `{kwargs}`. `format_kwargs(...)` gives `", a=1, b=2"`, leaving out `None`.
- The function runs in a worker thread. It reads the item only for what the code needs to know, e.g. a CSV file's
  separator.
- What it raises is shown in place of its code; the other snippets are still shown.

As with views, code is offered only when the action's packages are installed, and its check agrees.

### Options

An action's options are the fields of the class its `options` parameter is annotated with: a frozen, keyword-only
dataclass subclassing `ActionOptions`, each field with a default. Without an annotation, it gets `ActionOptions`, which
has none.

- Users set them with `engine_options`, by engine key, then format name or `"*"`.
- A function of the item's `Location` may give them per storage.
- The options of a format and an engine are those of all their actions' classes. A field of one name has one type in
  all of them, and is secret in all or none.
- An option no action of the engine takes is an error, so typos are caught.

Options are data. What an action does with them goes in functions taking them; methods only give views of them, e.g.
`code_value` or pyspark-support's `format_options()`.

```python
from dataclasses import dataclass
from typing import Any

from jupyter_storage_explorer.actions import ActionOptions
from jupyter_storage_explorer.util import secret_dict_field, secret_field


@dataclass(frozen=True, kw_only=True)
class DuckDBOptions(ActionOptions):
    memory_limit: str | None = None
    token: str | None = secret_field(default=None)  # never shown in code
    config: dict[str, Any] | None = secret_dict_field(default=None, secret_keys=["s3_secret_access_key"])


def connect_kwargs(options: DuckDBOptions) -> dict[str, Any]:
    """duckdb.connect's keyword arguments."""
    limit = {"memory_limit": options.memory_limit} if options.memory_limit else {}
    return {"config": {**(options.config or {}), **limit}}
```

```python
StorageExplorer(engine_options={"duckdb": {"*": {"memory_limit": "2GB"}, "parquet": {"config": {...}}}})
```

Code reads options with `options.code_value(name)`: `None` for a secret field, and a mapping without its secret keys.

**A reader's arguments.** Give each format its own model, `<Format>By<Library>Options`, subclassing the library's.

- Its fields are its reader's arguments, of the same names, from the library's API documentation, e.g. `read_parquet`'s.
- Each defaults to `LIBRARY_DEFAULT`: not passed, so the library's own default applies. `None` would not do, as some
  arguments take it as a value.
- Leave out the source, functions and arguments that change what the reader returns, e.g. iterators or chunks.
- An argument the code needs to return one dataframe is the exception: keep it, with the value that does. For example,
  `datasets`' `load_dataset` returns a `DatasetDict` of tables without `split`, so its model keeps `split="train"`.
- A reader passing arguments on to another library's, as Dask's `read_csv` does to pandas', takes those too, less
  those it refuses: check them with the installed library.
- A reader taking `**kwargs` shows none in its signature, and may take an unknown name given `None`: check each with a
  real value.
- Pass `options.arguments()`, those given, to the reader after the action's own defaults, e.g. a separator detected,
  so that the user's win.
- The code gets `format_arguments(options.code_arguments())`, which leaves out secrets and Python objects, e.g. data
  types, but keeps `None`.
- List them in the plugin's README, a table per format, their descriptions from the library's documentation.

```python
from jupyter_storage_explorer.util import LIBRARY_DEFAULT, LibraryDefault, format_arguments


@dataclass(frozen=True, kw_only=True)
class ParquetByDuckDBOptions(DuckDBOptions):
    """DuckDB's read_parquet arguments: unset ones are left to DuckDB."""

    binary_as_string: bool | LibraryDefault = LIBRARY_DEFAULT
    hive_partitioning: bool | LibraryDefault = LIBRARY_DEFAULT


relation = con.read_parquet(url, **options.arguments())  # in the view
code = f"con.read_parquet({url!r}{format_arguments(options.code_arguments())})"  # in the code
```

### Reading the item

| `ctx`                      | What                                                                                       |
|----------------------------|--------------------------------------------------------------------------------------------|
| `ctx.url_or_local_path`    | The location as libraries read it: a local file's plain path, else its URL                 |
| `ctx.url`                  | The location's URL, also a local file's (`file://`), as fsspec opens it: `ctx.location.url` |
| `ctx.location`             | Where it is (`AbfsLocation`, `S3Location`, `LocalLocation`, ...): `ctx.location.url`       |
| `ctx.fs`, `ctx.path`       | The explorer's fsspec filesystem (with its credentials) and the item's path in it         |
| `ctx.head(n)`, `ctx.head_text(n)` | The first bytes; the first text and whether it was cut                             |
| `ctx.read_whole(limits)`   | The whole file, refused over `limits.max_whole_file_bytes`                                 |
| `ctx.info`, `ctx.size`     | Its fsspec info; its size                                                                  |
| `ctx.children`, `ctx.child_names`, `ctx.is_dir` | A folder's listing, its names, whether it is a folder                 |

A library reads the item in one of five ways. Choose per storage in the check and the actions, as polars-support does:

| Way | When | Examples |
|---|---|---|
| By URL, `ctx.url_or_local_path` | The library reads the storage itself, with its own credentials: the environment, or options | polars on S3 (object_store) |
| The explorer's filesystem, `ctx.fs` | The library takes an fsspec filesystem and reads lazily through it | PyArrow's `FSSpecHandler` (polars-support's Parquet), DuckDB's `register_filesystem` |
| The explorer's filesystem by URL, `ctx.fs.unstrip_protocol(ctx.path)` with `storage_options=ctx.fs.storage_options` | The library takes only a URL and fsspec's `storage_options`: fsspec makes a filesystem like the explorer's from them | Dask's `read_csv` |
| Bytes, `ctx.head(n)`, `ctx.read_whole(limits)` | The library reads only a file object or bytes, so the file is read whole | pandas, polars' CSV elsewhere, images |
| A local copy, `local_file_cache().get(ctx)` | The library opens only local files | DuckDB and SQLite databases |

- Check what the library really reads before relying on it. Lazy through fsspec for one format may be whole for
  another: DuckDB reads Parquet lazily through fsspec, but reads a CSV or JSON Lines file again for each query.
  Read such a file from a local copy instead, as duckdb-support does.
- Let users say which storages the library reads itself, e.g. by an option listing URL schemes, as duckdb-support's
  `url_schemes`. A function of the location may set it per storage. One switch for all storages is too coarse.
- A library may spell a storage's URL its own way, e.g. DuckDB's `abfss://` for Azure, or Spark's (pyspark-support's
  `spark_url`). Convert the location's URL for it.
- Give a folder of data files as the glob of its files, `Parquet.data_url(ctx)`, never the folder. Libraries read a
  folder recursively, and fail or read wrong data in Spark's `_temporary` folders and `_SUCCESS` files.
- Handing `ctx.fs` over, pass `ctx.path`, the item's path in it, not `ctx.location.url`. The location's URL may not be
  the filesystem's: a `DirFileSystem`'s paths are relative, and a mapper's URL may name the storage otherwise (adlfs
  reads `abfs://container@account...` as `container/...`).
- A library registering filesystems by protocol, as DuckDB's `register_filesystem`, takes `ctx.fs` as it is: read
  `ctx.fs.unstrip_protocol(ctx.path)`, its own URL of the item. That works for a `DirFileSystem` too.
  - DuckDB calls `modified()`, and fails where the filesystem has none, e.g. fsspec's HTTP and zip filesystems. Refuse
    those in the check: `type(fs).modified is not AbstractFileSystem.modified`, for the filesystem a `DirFileSystem`
    wraps. s3fs, gcsfs and adlfs define it.
  - The library may also read that protocol itself, e.g. DuckDB's `s3://`. Check with the real filesystem which one
    reads it.
- By URL, the library has fsspec make a filesystem from the protocol and `storage_options`, in its own threads. Only
  some filesystems can be made again so:
  - arguments given by position are not in `storage_options`, e.g. a `DirFileSystem("/data", fs=...)`'s folder: then
    `ctx.fs.storage_args` is not empty;
  - a subclass not registered for its protocol comes back as its parent: then `fsspec.get_filesystem_class(protocol)`
    is not `type(ctx.fs)`.
- Decide so in the check without calling `fsspec.filesystem`, as dask-support's `_rebuilt_url` does. fsspec caches
  synchronous filesystems per thread, so in a worker thread it makes a new one, e.g. connecting to an SFTP server again.
- Lazy is not enough. Some lazy data reads all of the file, or of every partition, for each query of the data
  browser. Measure what each query reads. Give the view a `fetch` reading only what a page needs, if the library can;
  else ask first as for whole files.
- A library reading in partitions reads a whole partition for each page. Make them small for the data browser:
  - Dask reads a JSON Lines file whole, for each query, without a `blocksize`;
  - Dask makes a small Parquet file one partition, unless `split_row_groups=True` makes its row groups partitions.
- Leave the partitions to the library when the user sets an option deciding them, e.g. `blocksize`.
- Reading bytes whole, ask first above `limits.max_whole_file_bytes`, or when the size is unknown. Where the library
  can read a cut file, offer its first part too, as polars-support's `ViewWithChoice` above does. The data browser then
  says the data is partial, from `more=True`.

`local_file_cache()`, from `jupyter_storage_explorer.actions`, is the kernel's `LocalFileCache`. Views of one file share
its copy:

- `get(ctx)` downloads the file on demand, in a view's worker thread, and returns its local path. A local file is its
  own copy.
- A copy stays valid while the remote file's modification time is the same; `get` downloads a changed file again.
- `status(ctx)` says "cached", "invalid" (changed since) or "not_cached": ask before a large download unless "cached".
- `get` counts the view as a user; release it in `on_close` with `release(ctx.location, delay=...)`. The copy is
  deleted once no view uses it, after the delay, so that viewing the file again soon reuses it.
- Release it also when what follows `get` fails, e.g. opening the copy.
- Close what reads the copy before releasing it: on Windows, a file still open cannot be deleted. `on_close` calls
  its functions in the order given.
- Ask first also when the size is unknown (`ctx.size` is None).
- The copies are removed at the kernel's exit.

```python
cache = local_file_cache()


def open_copy():
    path = cache.get(ctx)
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:
        cache.release(ctx.location)  # get() counted this view
        raise
    view = TableSetView(...)
    view.on_close(lambda view: con.close())  # first
    view.on_close(lambda view: cache.release(ctx.location, delay=600))
    return view


large = ctx.size is None or ctx.size > limits.max_whole_file_bytes
if cache.status(ctx) != "cached" and large:
    return ViewWithConfirmation(message=f"Download {ctx.name} to view it?", factory=open_copy)
return open_copy()
```

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

The explorer calls an operation once per item the user chose, a folder's path included. The default operations then
work file by file:

- within a storage, a folder is moved or copied with one `fs.mv` or `fs.cp_file` per file;
- between storages, with one `_copy_file` or `_move_file` per file;
- a folder is deleted by passing its files' paths to `fs.rm`, in batches;
- uploads are one `fs.put_file` per file.

Override the operations of a storage where each call is costly, e.g. a commit. Do a whole folder in one call when the
library allows it.

On a storage where each write is a commit, such as the Hugging Face Hub:

- a move, copy or delete of a folder can be one commit, through the storage's own API;
- uploads stay one call of `upload` per file, so one commit each: the explorer has no upload of a folder.

After writing through the storage's own API rather than fsspec, call `fs.invalidate_cache(path)` for what changed.
Otherwise the filesystem's cached listings do not show the change.

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
([plugins/abfs-support](../plugins/abfs-support)) is a complete example.

## Filesystem mappers

### The challenge

A URL does not always say where a file is. `s3://sales/orders.parquet` names a bucket and a key, but not the server.
AWS, a MinIO server and another S3-compatible store can each have a bucket named "sales". So the same URL can name
different files on different servers.

Software working with one storage service at a time can ignore this. Storage Explorer cannot, as it is built to reach
several storage services at once.

What the URL leaves out is held by the client. An fsspec filesystem knows its S3 endpoint, or its Azure account, from
its settings.

### Our approach

Storage Explorer handles this with two classes:

- A `Location` names a file or folder uniquely across storage services. An `S3Location` holds the endpoint besides the
  bucket and the key, for example. Its `url` is the URL in its usual form, for libraries and users.
- A `FileSystemMapper` maps between locations and an fsspec filesystem with its paths. It gives a path's location, and
  the path of a location in a filesystem, if that filesystem reaches it.

### Check the real filesystem first

Before writing a mapper or operations, try the filesystem on a real storage, reading only. Answer these questions:

- **Can its top folder be listed?** Some cannot, e.g. a hub listing no repositories. Users then open the explorer
  below it, and levels only apply from there.
- **What do its paths hold besides folders?** Versions, revisions or encoded characters, e.g. `@refs%2Fpr%2F1`. Check
  that each real path listed gives a location whose path names the same item again.
- **Does one class reach several kinds of storage?** Then the location must tell them apart.
- **What does each write cost?** It could be a request, or a commit. Look for the library's calls that do many at once.
- **What does `info` give?** Note the names of the size, type and modified-time fields.
- **Do the engines read its URLs?** Try each engine's reader on real URLs, including their unusual forms.

Write the answers in the plugin's docstrings, and build the tests' fakes from them.

### Writing a mapper

A `FileSystemMapper` turns the paths of one fsspec implementation's filesystems into locations, and back. Locations are
where files are, independently of the implementation: their `url` is what "Copy URL", previews, "Python code" and the transfer
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

Normalize locations when they are made, e.g. lower-case hosts and no trailing "/". Equal locations must name the same
item.

A filesystem may take two spellings of one path, e.g. a revision URL-encoded or not. Both then give one location, in
the spelling the filesystem reads unambiguously. A path listed in the other spelling comes back in that one, which
names the same item.

`to_location` runs for every item listed, as `level` does. Decide from the path and the instance's settings, never by
reading the storage. It also runs for the filesystem's top folder, `""`, which `same_filesystem` compares. That folder
needs a location even where it cannot be listed.

The predefined mappers cover:

- Azure, S3 and Google Cloud Storage;
- SFTP, local disks and memory;
- Databricks, with [fsspec-databricks](https://github.com/sugibuchi/fsspec-databricks) and with fsspec's own
  filesystem. Their URLs are fsspec's, such as `dbfs://Volumes/...`.

Other filesystems get fsspec's URLs.

### Levels

`level(fs, path)` tells what a folder is when it is more than a folder, e.g. "container". The explorer uses it mainly to
show such folders differently from plain ones, such as with an icon of their own. See
[How its storages look](#how-its-storages-look).

```python
class MyMapper(FileSystemMapper):
    ...
    levels = ("server",)  # what the folders at each depth from the top are
```

- By default, `level` reads `levels`: a level per depth from the filesystem's top folder, e.g. adlfs's `("account",
  "container")`. "" stands for a depth of plain folders.
- Override `level` when the level depends on the path, not only on its depth. `DatabricksMapper`'s does, for
  `/Volumes/<catalog>/<schema>/<volume>` and `/Workspace/Repos/<user>/<repository>`.
- It is called for every folder listed. Decide from the path and the instance's settings, never by reading the
  storage.

### How its storages look

`css` is the CSS of the explorer while it shows one of the mapper's storages: e.g. icons for its levels, and the
storage's colour. Folders of a level without an icon keep the folder icon.

`level_icon_css(icons, color=None)` writes such CSS, from an SVG image per level. Each icon is drawn in one colour:
the storage's, else JupyterLab's grey, and white in selected rows. The predefined mappers' icons are made this way.

```python
from jupyter_storage_explorer.filesystems import level_icon_css

SERVER_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="..."/></svg>'


class MyMapper(FileSystemMapper):
    ...
    css = level_icon_css({"server": SERVER_SVG}, color="#7b1fa2")
```

Write CSS of your own for anything else. A folder's row has its level in `data-fs-level`, which CSS selects it by.

```python
class MyMapper(FileSystemMapper):
    css = """
    & { --jse-storage-color: #7b1fa2; }  /* the explorer itself */
    [data-fs-level="server"] .jse-icon svg { display: none; }
    [data-fs-level="server"] .jse-icon::before { content: "🖥️"; }
    """
```

- The explorer scopes it to its own element, while it shows one of the mapper's storages. So selectors start inside
  the explorer, e.g. at `[data-fs-level]`. `& { ... }` styles the explorer itself.
- The scope adds no weight to the selectors. So users' CSS starting with `.jse-browser` overrides it.
- Use the selectors in DEVELOPMENT.md's "Icons", such as `.jse-icon::before`. The explorer's other classes may change.
- Ship only icons you may ship: no cloud provider's logo, unless its licence allows it.
- Each mapper class's CSS is on the page once. Keep it the same for every instance: it is a class attribute.

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
│       ├── actions.py       # engine, packages, formats, options, actions: DUCKDB_ACTIONS
│       └── operations.py    # file operations, if any
└── tests/
    ├── conftest.py          # the explorer's test fixtures (see Testing)
    └── test_duckdb_actions.py
```

### `pyproject.toml`

```toml
[project]
name = "jupyter-storage-explorer-duckdb-support"
version = "0.1.0"
description = "DuckDB support for Storage Explorer"  # shown to users, in "About"
readme = "README.md"
license = "MIT"  # shown in "About", with the authors
authors = [{ name = "Your Name" }]
requires-python = ">=3.11"
# The explorer only: never the backend library (see "full").
dependencies = ["jupyter-storage-explorer>=0.27,<0.28"]

# The libraries it uses: installed only on request, so that installing the
# plugin never changes those of a shared environment.
[project.optional-dependencies]
full = ["duckdb>=1.0"]

# "About" links the plugin's name to its home page (http or https only).
[project.urls]
Homepage = "https://github.com/you/jupyter-storage-explorer-duckdb-support"

# Explorers find the plugin by this entry point, named by its key.
[project.entry-points."jupyter_storage_explorer.plugins"]
duckdb-support = "jupyter_storage_explorer_duckdb_support:DuckDBSupport"

[dependency-groups]
# The libraries, what the tests need, and JupyterLab to try the plugin in.
dev = ["duckdb>=1.0", "jupyterlab>=4", "pytest>=8"]

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
  versions). This guide describes the explorer's `main` branch, which may be ahead of its last release: see
  [Develop and install](#develop-and-install) to develop against it.
- `full`: the backend libraries. Users install `pip install "jupyter-storage-explorer-duckdb-support[full]"` to get
  them, or the plugin alone to use those already installed.
- The entry point's name is the plugin's `key`: `<name>-support`.

### The plugin class

This example shows every part a plugin may have. duckdb-support itself has neither options of its own nor file
operations.

```python
"""DuckDB support for Storage Explorer."""

from dataclasses import dataclass

from jupyter_storage_explorer import StorageExplorerPlugin, StorageExplorerPluginOptions
from jupyter_storage_explorer_duckdb_support.actions import (
    DUCKDB_ACTIONS,
    DuckDBEngine,
    DuckDBOptions,
    database_view,
    parquet_as_relation,
    parquet_view,
)
from jupyter_storage_explorer_duckdb_support.operations import ServerSideCopy


@dataclass(frozen=True, kw_only=True)
class DuckDBSupportOptions(StorageExplorerPluginOptions):
    """The plugin's options (plugin_options={"duckdb-support": {...}}): enabled,
    priority, and its own."""

    concurrency: int = 16
    databases: bool = True


class DuckDBSupport(StorageExplorerPlugin):
    key = "duckdb-support"  # = the entry point's name
    options_model = DuckDBSupportOptions
    options: DuckDBSupportOptions

    @property
    def actions(self):  # functions decorated with @view or @code, in the order tried
        if self.options.databases:
            return DUCKDB_ACTIONS
        return tuple(a for a in DUCKDB_ACTIONS if a is not database_view)

    @property
    def formats(self):  # DataFormat classes no action names (rare)
        return ()

    @property
    def filesystem_operations(self):  # objects, made with the plugin's options
        return (ServerSideCopy(concurrency=self.options.concurrency),)

    @property
    def filesystem_mappers(self):  # objects (or classes, created without arguments)
        return ()


__all__ = [
    "DUCKDB_ACTIONS",
    "DuckDBEngine",
    "DuckDBOptions",
    "DuckDBSupport",
    "DuckDBSupportOptions",
    "parquet_as_relation",
    "parquet_view",
]
```

- Explorers create the plugin with its options, an `options_model` object, `self.options`. Users give them with
  `plugin_options={"duckdb-support": {"concurrency": 8}}`, or `plugin_options()` in the launcher's tabs.
- Every plugin has `enabled` and `priority`. `enabled=False`: not used, not even imported. Plugins of a higher
  `priority` come first, then by key.
- An option the model lacks is an error.
- Plugin options configure the components made with arguments, such as operations and mappers. For actions, they only
  include or leave some out: actions get their own options from `engine_options`, by engine key.
- Export the actions, so that users and other plugins can import them, e.g. to give one before the others.
- `name`, `description` and `version` come from the package's metadata (`[project]`): the class does not repeat them.
- A plugin that cannot be imported or created is left out with a warning, and greyed out in "About".

### Logging

Each module of a plugin gets its logger with `get_logger(__name__)`. Import it from `jupyter_storage_explorer` or
`jupyter_storage_explorer.actions`, whichever the module imports from already:

```python
from jupyter_storage_explorer.actions import get_logger, view

log = get_logger(__name__)
```

- The logger is a child of the explorer's, e.g. `jupyter_storage_explorer.ext.jupyter_storage_explorer_duckdb_support.actions`.
  Its records go where the explorer's do, at the level users choose: see [Logs](storage-explorer.md#logs).
- `logging.getLogger(__name__)` would not work: a plugin's package is no child of `jupyter_storage_explorer`.
- Log at the levels the explorer does, which DEVELOPMENT.md's "Logs" lists. INFO is for what users do, with its
  time. WARNING is for what goes wrong for them, and DEBUG for the details.
- Never log credentials, storage options, options' values or the contents of files. Log a listing by its count of
  items.

### The README

Write the README in this layout, as this repository's plugins' are. Keep each part short: what users need to install
and configure, with links to the libraries' own documentation for the rest.

````markdown
# jupyter-storage-explorer-duckdb-support

DuckDB support for Storage Explorer,
the [Jupyter Storage Explorer](https://github.com/sugibuchi/jupyter-storage-explorer) plugin for
DuckDB as an engine: the data browser on Parquet files and DuckDB databases, and code loading them.

## Installation

```bash
pip install "jupyter-storage-explorer-duckdb-support[full]"  # the plugin and its libraries
pip install "jupyter-storage-explorer-duckdb-support"        # the plugin only, with the libraries you have
```

The libraries are not the plugin's dependencies, so that installing it never changes those of a shared environment.
The first command installs them:

| Library  | Needed for            |
|----------|-----------------------|
| `duckdb` | Mandatory: the engine |

### Prerequisites

- The plugin expects DuckDB to reach your storage already, as configured in the environment: DuckDB reads the data
  without options. You can still give options in
  [Engine options](https://github.com/me/jupyter-storage-explorer-duckdb-support/blob/main/README.md#engine-options).

## Plugin options

`plugin_options` gives the plugin's options:

```python
StorageExplorer(
    "s3://my-bucket/lake", plugin_options={"duckdb-support": {"priority": 10}}
)
```

In the launcher's tabs, `plugin_options()` in `launcher.py` gives them:

```python
def plugin_options():
    return {"duckdb-support": {"enabled": False}}
```

| Option     | Default | Meaning                                                                                                  |
|------------|---------|----------------------------------------------------------------------------------------------------------|
| `enabled`  | `True`  | Whether explorers use the plugin. `False`: not even imported.                                            |
| `priority` | lowest  | Plugins of a higher priority come first: their actions are tried before the others'. Equal ones by key.  |

## Engine options

The plugin's options, in `engine_options["duckdb"]` (by format, or `"*"` for all), with an example, then a table per
format: each option, its default and its meaning, from the library's documentation.
````

- **Installation** tables every library of the `full` extra, with what it is needed for. The engine's comes first,
  marked "Mandatory"; for a storage plugin, the storage's packages are.
- A library installed with an extra, e.g. `dask[dataframe]`, is listed by its name, `dask`. Say what the extra brings
  in "Needed for".
- **Prerequisites** say what the environment must already provide, e.g. the library's access to storage. Link the
  configuration reference of a library that does not use fsspec, as polars-support links object_store's. Say which
  storages it reads itself, and how it reads the others, e.g. through the explorer's filesystem.
- **Plugin options** shows one example for `StorageExplorer` and one for `launcher.py`, then the options' table.
- Links, also to the README's own sections, are absolute URLs: PyPI shows the README, but resolves neither relative
  paths nor `#` anchors of its headings.
- Code blocks are formatted as ruff formats Python, at its default line length of 88. `uvx ruff format` formats the
  README's blocks too, and `uvx ruff format --check` checks them.
- A note on how the data browser behaves with the library, e.g. what it reads, goes in a section of its own after
  Prerequisites.

This repository's plugins publish the extras through the explorer, e.g. `jupyter-storage-explorer[polars]`. Their
READMEs show those commands instead. `tests/test_plugin_readmes.py` checks this layout for them, and that the table
lists exactly the `full` extra's libraries. It is not part of the explorer's package: other plugins follow the layout
by hand.

### Develop and install

```bash
uv init --lib --build-backend hatch jupyter-storage-explorer-duckdb-support   # then edit pyproject.toml as above
uv sync                      # the plugin (editable), the explorer, the dev group
uv run pytest
uv build                     # dist/: the wheel and sdist
uv publish                   # to PyPI (or --publish-url for another index)
```

`uv init` sets `requires-python` to the Python it runs with: lower it to the explorer's, `>=3.11`.

`uv sync` installs the plugin editable, with its entry point: explorers in `uv run jupyter lab` use it at once. After
changing `pyproject.toml` (the description, the entry point), run `uv sync` again.

To develop against the explorer's `main` branch before its release, add a source to `pyproject.toml`:

```toml
# Until the release: remove this table before publishing, then run uv lock.
[tool.uv.sources]
jupyter-storage-explorer = { git = "https://github.com/sugibuchi/jupyter-storage-explorer" }
```

- Its version is the last release's with a suffix, e.g. `0.26.0.post8`. Until the release, widen the requirement to
  accept it, e.g. `>=0.26,<0.28`.
- This repository's plugins cannot be installed from git, and each requires the explorer of exactly its own version.
  Test against them with releases only.

Run the checks a plugin's CI needs on each pull request:

- `uvx ruff check` and `uvx ruff format --check`;
- `uv run pytest`, including the `check_plugin` test.

Publish from a version tag, e.g. with PyPI's
[trusted publishing](https://docs.pypi.org/trusted-publishers/), which needs no token: `uv publish` reads it from the
workflow.

## Testing

A plugin's tests are in its own `tests/` and test its own code:

- its actions: views, code and checks, with their options;
- its engine, operations and mappers;
- its entry point, with `check_plugin`.

Explorers leave out a plugin they cannot load, with a warning only, so that a broken package never keeps them from
opening. `check_plugin(key, options=None)`, from `jupyter_storage_explorer.testing`, fails instead. It loads the plugin
from its entry point, as explorers do, and checks:

- the entry point, the plugin's class and its `key`;
- its options model, created with `options`;
- its package's description;
- its components' types, and its actions registered together;
- its actions with the explorer's own and the other plugins installed, as an explorer checks them.

It returns the plugin, for checks of your own. Call it in one test:

```python
from jupyter_storage_explorer.testing import check_plugin


def test_plugin():
    plugin = check_plugin("duckdb-support")
    assert plugin.actions == DUCKDB_ACTIONS
```

They need no browser. Actions are called as their functions, with items as the explorer gives them, `ItemContext`.
`jupyter_storage_explorer.testing` makes those on fsspec's memory filesystem, or from local files for libraries reading
by URL. Its fixtures come through `tests/conftest.py`:

```python
"""Items as the explorer gives them to the plugin's actions."""

from jupyter_storage_explorer.testing import make_item, memfs  # noqa: F401
```

- `memfs`: fsspec's memory filesystem, emptied.
- `make_item(path, data=None, location=None, *, mappers=())`: writes `data` there (or lists the folder) and returns
  the item; `location` gives it another, e.g. an `S3Location` for the code of an S3 file.
- `item_of(fs, path, location=None, *, mappers=())` and `local_item(path)`: an item of any filesystem, or a local file
  (e.g. in `tmp_path`).
- `mappers` are tried before the default ones, as explorers try a plugin's. A storage plugin passes its own, so that
  its items get its locations.

A test needing what the library downloads on first use, e.g. a DuckDB extension, skips when it cannot get it. The tests
then run offline.

Test the views as explorers call them too: in a worker thread. What depends on the thread, such as fsspec's cache of
synchronous filesystems, differs there from the main thread.

The tests' libraries go in the `dev` group, so that `uv run pytest` runs them with the plugin's dependencies only:

```python
from jupyter_storage_explorer.formats import Parquet
from jupyter_storage_explorer.testing import local_item
from jupyter_storage_explorer.views import QueryView, ViewLimits


def test_view(tmp_path):
    path = tmp_path / "a.parquet"
    ...  # write a Parquet file
    view = parquet_view(Parquet(), local_item(path), DuckDBOptions(), ViewLimits())
    assert isinstance(view, QueryView)
    view.close()


def test_code(tmp_path):
    path = tmp_path / "a.parquet"
    ...  # write a Parquet file
    code = parquet_as_relation(Parquet(), local_item(path), DuckDBOptions())
    assert f"read_parquet({path.as_posix()!r})" in code


def test_what_duckdb_reads(tmp_path, make_item):
    # does(): of the action's format, and its check agrees.
    assert parquet_view.does(Parquet(), local_item(tmp_path), DuckDBOptions())
    assert not parquet_view.does(Parquet(), make_item("/a.parquet", b""), DuckDBOptions())
```

A storage plugin's tests need no real storage either:

- Mappers match classes by qualified name. So a fake filesystem only needs the real class's name and module, e.g. a
  subclass of fsspec's `AbstractFileSystem` whose `__module__` is set to the real one. databricks-support's tests fake
  fsspec-databricks this way.
- Fake the library's calls that operations make, e.g. a client recording the batches it gets. Check that a folder takes
  one call, and that a cancel stops between items.
- Take the fakes' paths and answers from real listings, as [Check the real filesystem first](#check-the-real-filesystem-first)
  says.

Try it in a browser with `uv run jupyter lab`:

- ⚙ → **About** lists the plugin with its version;
- an engine viewing something is in the status bar's engine menu;
- code actions are in an item's right-click menu, under **Python code**.

This repository's plugins also get a check in `tests/browser/smoke.py` for what users see:

- a storage plugin, such as a storage's levels and icons: `storage_levels` there shows how, on a fake filesystem;
- an engine plugin, its views in the preview panel: `dask_engine` and `duckdb_engine` there are lab checks of their
  own explorers, with the engine chosen by `engine_preference`.

A right-click menu grows when the item's views arrive from the kernel. Wait for **Preview as** before hovering an item
below it, such as **Python code**.

Checks opening view tabs need the launcher's JupyterLab extension built: `uv run jlpm install` and `uv run jlpm build`
in `launcher/labextension`, then `uv sync`.

Plugins outside this repository use only the public API, in these modules:

- the top level;
- `filesystems`, `filesystems.locations`, `filesystems.mappers` and `filesystems.operations`;
- `formats`;
- `actions` and `actions.python`;
- `views`, `engine` and `packages`;
- `util` and `testing`.

This repository's plugins may also use the explorer's internals, as they are released with it.

### Trying components in an explorer

A component can be tried in a browser before it is packaged, without a plugin or an entry point. `StorageExplorer`
takes components as arguments:

```python
from jupyter_storage_explorer import StorageExplorer
from my_components import MyMapper, ServerSideCopy, parquet_as_relation, parquet_view

StorageExplorer(
    "s3://bucket/data",
    actions=[parquet_view, parquet_as_relation],  # functions decorated with @view or @code: their formats come with them
    operations=[ServerSideCopy()],  # FileSystemOperations objects
    filesystem_mappers=[MyMapper()],  # FileSystemMapper objects
)
```

For each job, the first component that can do it does it, and the component tried leaves the rest to the others:

- an action, the items its `check` refuses;
- an operation, what it raises `NotSupported` for.

The order differs between actions and the other components:

- Operations and mappers given come first, then the plugins', then the defaults.
- Actions come in this order: the plugins', the explorer's own, those given, then those of the user's files. Plugins
  are installed to enrich or change the explorer, while actions given and the user's add to it.

The first view an item matches is its default. **Preview as** lists the others of its engine by their labels. To try
your view as the default of a format a plugin views, disable that plugin with `plugin_options`.

An action of the same kind, format, engine and label as a plugin's is an error. Give yours another label, or disable
that plugin.

Restart the kernel after changing the component's module: Python imports a module only once.

Actions can also go in `storage-explorer/actions.py`, or a file of `storage-explorer/actions/`, in a Jupyter
configuration directory. Every explorer reads them when it is created: see the
[Action development guide](action-development-guide.md). A changed file applies to the next explorer, without a
restart. **Actions > Reload**, in the ⚙ menu, applies it to an explorer already open.

The launcher's tab and side panel take the same components from functions of the same names in `launcher.py`:

```python
def actions():
    from my_components import parquet_as_relation, parquet_view

    return [parquet_view, parquet_as_relation]


def operations():
    from my_components import ServerSideCopy

    return [ServerSideCopy()]


def filesystem_mappers():
    from my_components import MyMapper

    return [MyMapper()]
```

- The module must be importable by the tab's kernel, e.g. installed in its environment or on `PYTHONPATH`.
- A later layer's components come before an earlier layer's. Operations and mappers come before the plugins' and the
  defaults, and actions after them, as above.
- Open a new tab after changing the module. A reloaded page keeps its kernel, and with it the module imported.

## Checklist

- [ ] Package `jupyter-storage-explorer-<name>-support`, module `jupyter_storage_explorer_<name>_support`.
- [ ] `description = "<Name> support for Storage Explorer"`; `license`, `authors` and `[project.urls]`'s `Homepage`,
  shown in "About" (`StorageExplorerPlugin.authors`, `license`, `urls`).
- [ ] `dependencies`: the explorer only; the backend libraries in the `full` extra and the `dev` group.
- [ ] Entry point in `jupyter_storage_explorer.plugins`, named by the plugin's `key`.
- [ ] No backend import at module level: actions import the library inside their functions.
- [ ] Actions made with `@view` and `@code`, registered in order with `register_actions` and given by the plugin's
      `actions` property; one code action per snippet.
- [ ] Each action's options class imported at run time and named in the `options` parameter's annotation; options
      classes are data, with what actions do with them in functions.
- [ ] Checks refuse the items their library cannot handle, without reading the storage, named by what they decide.
- [ ] Code text from module-level `inspect.cleandoc` templates, filled with `str.format`.
- [ ] Views reading a whole large file ask first, with a `ViewWithPrompt`.
- [ ] Secrets declared with `secret_field` / `secret_dict_field`; code options through `options.code_value`.
- [ ] Loggers from `get_logger(__name__)`, logging no credentials, options' values or file contents.
- [ ] A model per format whose fields are its reader's arguments (default `LIBRARY_DEFAULT`), passed with `arguments()`
      and `code_arguments()`, and tabled in the README with the library's descriptions.
- [ ] README: the plugin's options (`enabled`, `priority`, its own) and its components' parameters.
- [ ] Views holding resources release them with `on_close`.
- [ ] Operations raise `NotSupported` for what they do not do, report progress and call `progress.check()`.
- [ ] Operations do a folder in one call where each call of the library is costly.
- [ ] Locations: frozen keyword-only dataclasses, normalized, without credentials.
- [ ] Storage plugins: the questions of [Check the real filesystem first](#check-the-real-filesystem-first) answered on a
  real storage; real paths give locations whose paths name the same items again; the engines read the locations' URLs.
- [ ] Tests in the plugin's `tests/`, of its own code, run with `uv run pytest`.
- [ ] A test calling `check_plugin` with the plugin's key passes.
- [ ] README in the layout of [The README](#the-readme): Installation with the `full` extra's libraries,
  Prerequisites, Plugin options with both examples, and the engine options' tables.

## Plugins of this repository

The plugins in [`plugins/`](../plugins) (polars, pandas, duckdb, pyspark, dask, abfs, databricks) follow these conventions and are released with the
explorer, at its version: each requires the explorer of exactly its own version (its `hatch_build.py`: the version comes from git), and the
explorer's extras install them (`polars`: with its libraries; `polars-support`: alone). databricks-support also
requires pyspark-support of its own version, whose helpers its actions share. To add one:

1. Copy one of them (e.g. `plugins/polars-support`), renaming the package, module, plugin class and entry point. Its
   tests are in its `tests/`, named `test_<name>_*.py` (pytest at the root runs every plugin's, and imports test files
   by name).
2. Add its extras, `<name>` (the plugin's `full`) and `<name>-support` (the plugin alone), to
   `[project.optional-dependencies]` in the root's and the launcher's `pyproject.toml`, without versions: the plugin
   requires the explorer of exactly its own.
   - Add them to the root's `all` and `all-supports`. The launcher's delegate to the root's.
   - Add the package to the root's dev dependencies and `[tool.uv.sources]`.
   - The workspace shares one lock: the plugin's `dev` group must agree with the root's, e.g. the root keeps DuckDB
     below 2 for sqlframe.
   - `uv lock` checks that they agree. `uv.lock` itself is not committed.
3. Give it a release workflow, `.github/workflows/release-<plugin>.yaml` (a copy of another's), and its PyPI project a
   trusted publisher for it (see [One-time setup for PyPI](../DEVELOPMENT.md#one-time-setup-for-pypi)).
4. List it in [plugins/README.md](../plugins/README.md): in the table of its engine or storage, and in the extras'
   table.
5. Write its README as [The README](#the-readme) says, with the explorer's extras in its commands.
   `tests/test_plugin_readmes.py` checks it with the others.
6. Update the core's tests that list what is installed: `uv run pytest` at the root runs them with every plugin. They
   name the plugins, engines, formats and extras, and some use names that may now be taken, such as a sample format.
   Search them for another plugin's key, e.g. `polars-support`, and for the new engine's and formats' names. A new
   engine is offered after those of `engine_preference`, polars and pandas, by key.
   - With uncommitted changes, hatch-vcs may give the workspace's packages different versions, as they are built at
     different times, and `test_of_the_repository_plugins` then fails. Run `uv sync --reinstall-package <package>` for
     each of them, or commit first.
7. Add it to DEVELOPMENT.md's tables of the packages and of the PyPI projects. Add its engine, formats and engine
   options to [storage-explorer.md](storage-explorer.md), where it lists those.

A plugin is experimental when its library is, or when it is not tested where it is meant to run, e.g. Dask on a
cluster. An experimental plugin stays out of `all` and `all-supports`, as databricks-support and dask-support do.
[plugins/README.md](../plugins/README.md) marks its status in its tables.
