# Action development guide

Actions are what the explorer does with a file or a folder of a format:

- a **view** shows it, in the preview panel or a tab of its own;
- **code** gives a snippet of Python loading it, in the right-click menu's **Python code**.

The explorer has actions of its own, and plugins add others. You can add yours with a few functions in a file. They
are offered beside the others, in **Preview as** and **Python code**.

This guide covers actions for your own use. To package actions, engines or storages for others, see the
[Plugin development guide](plugin-development-guide.md).

## Your actions file

Your actions go in `~/.jupyter/storage-explorer/actions.py`. The ⚙ menu's **Edit actions** opens it in JupyterLab's
editor, and creates it from a commented example if it is missing.

- Every explorer reads it when it is created: in notebooks, the launcher's tabs and the side panel.
- A file gives every action defined in it, in order. A list `ACTIONS` in the file gives only those it names, in its
  order.
- After a change, create the explorer again: run its cell again, or open a new tab. The kernel needs no restart.
- More files can go in the folder `~/.jupyter/storage-explorer/actions/`, read by name after `actions.py`. Files
  whose names start with `_` are not read, so they can hold shared code.
- `jupyter --paths` lists the other configuration directories, under "config". Files there serve every user of the
  environment or the system, after yours.

**Edit actions** needs the launcher's JupyterLab extension, which `jupyter-storage-explorer-launcher` installs. Without
it, edit the file in any editor.

## A first action

An action is a function decorated with `@code` or `@view`, given the format it acts on:

```python
from jupyter_storage_explorer.formats import file_format
from jupyter_storage_explorer.formats.actions import code


@code(file_format(".abc"))
def pretty_print_json(url):
    return f"import json, fsspec\n\nwith fsspec.open({url!r}) as f:\n    print(json.dumps(json.load(f), indent=4))"
```

Right-click a file named `*.abc`: **Python code** now offers "Pretty print json", the function's name.

- The function names the parameters it needs, here `url`: see [Parameters](#parameters).
- The format is one of the explorer's or a plugin's, e.g. `Json` or `Parquet`, or one of yours: see
  [Formats](#formats).
- A view is the same, with `@view`, and returns what to show: see [Views](#views).

## Parameters

An action's function takes the parameters it names, in any order, of these:

| Parameter | What                                                                                         |
|-----------|----------------------------------------------------------------------------------------------|
| `url`     | Where libraries read the item: its URL, or a local file's plain path.                        |
| `name`    | The item's name, e.g. `"a.csv"`.                                                             |
| `path`    | Its path in its storage.                                                                     |
| `size`    | Its size in bytes, if known.                                                                 |
| `is_dir`  | Whether it is a folder.                                                                      |
| `fs`      | The explorer's fsspec filesystem the item is on, with its credentials.                      |
| `ctx`     | The item, an `ItemContext`: all of the above, and how to read it (see below).                |
| `fmt`     | The format it was detected as, e.g. a `Parquet`.                                             |
| `options` | Its options: see [Options](#options).                                                        |
| `limits`  | For views only: how much to read and show, a `ViewLimits`.                                   |

Any other parameter needs a default, which it keeps. `ctx` also reads the item:

| `ctx.`               | What                                                                               |
|----------------------|------------------------------------------------------------------------------------|
| `head_text(n)`       | Its first `n` bytes as text, and whether the file is longer.                       |
| `head(n)`            | Its first `n` bytes.                                                               |
| `read_whole(limits)` | The whole file, or an error if it is larger than `limits.max_whole_file_bytes`.    |

## Formats

The first argument of `@code` and `@view` is the format, a class:

- the explorer's, from `jupyter_storage_explorer.formats`: `Text`, `Markdown`, `Json`, `JsonLines`, `Csv`,
  `Parquet`, `DeltaLake`, `Excel` and `Image`;
- a plugin's, from its package;
- or yours, made by `file_format`, for files no format covers.

```python
file_format(".abc")                            # files named *.abc
file_format([".yml", ".yaml"])                 # either ending
file_format(names="Dockerfile")                # files of that name
file_format(names="*.zarr", is_dir=True)       # folders, by name
file_format(".log", label="Logs", name="logs") # with a label and a name of your own
```

- Case is ignored, and the same arguments give the same format, also in several files.
- Its label is its patterns by default, e.g. "Files (.abc)". Its name, for `engine_options`, is "user-format-1",
  "user-format-2" and so on, unless you give one.
- Yours rank below the explorer's and the plugins' formats. A file they recognise keeps their format, and yours is
  offered beside it in **Preview as**.

## Views

A view returns what to show, in the preview panel or a tab:

- a dataframe opens in the data browser, where you page, sort and filter it: best a lazy one, e.g. a polars
  LazyFrame;
- a `str` is shown as text;
- a `dict` or a `list` is shown as a collapsible tree;
- a view object shows more, e.g. highlighted text: see below.

```python
from jupyter_storage_explorer.formats import Parquet
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer_polars_support import PolarsEngine


@view(Parquet, PolarsEngine, label="Latest orders ({engine})")
def latest_orders(url):
    import polars as pl

    return pl.scan_parquet(url).sort("order_date", descending=True)
```

- The second argument is the engine: the library the view uses, as the explorer's engine menu shows it. Each engine
  plugin has its own, e.g. `PolarsEngine` from polars-support. Without one, it is `PythonEngine`, Python alone.
- Import libraries inside the function, as above. Your file is read by every explorer, also in kernels without them.
- The view is offered only when its engine's packages are installed.

The view objects:

| View                   | Shows                                                                                      |
|------------------------|--------------------------------------------------------------------------------------------|
| `QueryView(data=...)`  | A dataframe, in the data browser.                                                          |
| `TextView(text=...)`   | Text; with `language`, e.g. `"sql"`, highlighted.                                          |
| `MarkdownView(text=...)` | Markdown, rendered.                                                                      |
| `TreeView(value=...)`  | A JSON-like value, as a collapsible tree.                                                  |
| `TableView(columns=..., rows=...)` | A small table of values, without the data browser.                             |
| `MediaView(mime=..., data=...)` | An image, from its bytes.                                                         |
| `TableSetView(nodes=..., loader=...)` | Several tables, e.g. a database's, in a tree or on tabs.                    |

A view reading much, e.g. a whole large file, should ask first. Return a `ViewWithConfirmation`, `ViewWithChoice` or
`ViewWithInput`, whose function makes the view once the user answers. The
[Plugin development guide](plugin-development-guide.md#view-viewfmt-ctx-options-limits) has the details.

All views are in `jupyter_storage_explorer.formats`.

## Code snippets

A code action returns a snippet of Python, which **Python code** shows under its engine. For code of several lines, a
template reads best:

```python
from inspect import cleandoc

from jupyter_storage_explorer.formats import Csv
from jupyter_storage_explorer.formats.actions import code

READ_ROWS = cleandoc("""
    import csv

    import fsspec

    with fsspec.open({url}, "rt", newline="") as f:
        rows = list(csv.DictReader(f))
    """)


@code(Csv, label="Read as dicts")
def csv_as_dicts(url):
    return READ_ROWS.format(url=repr(url))
```

- The code must run as it is in a new notebook: its imports first.
- The label says what the code does, e.g. "Read as dicts". **Python code** shows the engine already.
- Never put secrets in the code: it gets copied and shared. With options, see [Options](#options).

## Labels and the menus

The label is what you see in the menus:

- a view's label shows in **Preview as** and **View in new tab as**, when its engine has several views of the item;
- a code action's label is its title in **Python code**.

`{format}` and `{engine}` in a label are replaced by the labels of the format and the engine. A view's default label is
`"View as {format} ({engine})"`, e.g. "View as CSV (Polars)". A code action's is its function's name, e.g.
"Read as dicts" for `read_as_dicts`.

Two actions of one kind, format, engine and label are an error: you could not tell them apart in the menus. Give
yours a label of its own.

Your actions come after those of the plugins and of the explorer. So the first view of an engine is the default one,
e.g. what a double-click previews, and yours are offered beside it. A view of yours is the default only for a format or
an engine nothing else views.

## Which items

By default, an action is offered for every item of its format, and its subclasses. `check` narrows it down:

```python
def _small(fmt, ctx, options):
    return ctx.size is not None and ctx.size < 1024 * 1024


@view(Text, label="Shout", check=_small)
def shout(ctx, limits):
    return ctx.head_text(limits.max_bytes)[0].upper()
```

`check` always takes `(fmt, ctx, options)`. It runs for each item you click, so it decides from what is known: the
format, the name, the path, the size and the options. It never reads the file.

## Options

An action can take options, which `engine_options` gives, by engine key and format name. Declare them as a frozen
dataclass subclassing `ActionOptions`, and annotate the `options` parameter with it:

```python
from dataclasses import dataclass

from jupyter_storage_explorer.formats import ActionOptions, Text
from jupyter_storage_explorer.formats.actions import view


@dataclass(frozen=True, kw_only=True)
class ShoutOptions(ActionOptions):
    exclamations: int = 1


@view(Text, label="Shout")
def shout(ctx, limits, options: ShoutOptions):
    text, _ = ctx.head_text(limits.max_bytes)
    return text.upper() + "!" * options.exclamations
```

```python
StorageExplorer("s3://bucket/notes", engine_options={"python": {"text": {"exclamations": 3}}})
```

- Each option has a default, as users may set none.
- Define the class at the top level of your file, not inside a function.
- `PythonEngine`'s key is `"python"`. An engine's options also reach the plugin's actions of that format: a field
  of the same name must have the same type there.
- Mark a credential with `secret_field()` or `secret_dict_field()`, from `jupyter_storage_explorer.util`. Code shows
  options only through `options.code_value(name)`, which leaves secrets out.

## When something goes wrong

- A file that cannot be read, e.g. with a syntax error, is left out with a warning, under the explorer's cell. The
  explorer still opens, with the other files' actions.
- A file with an action of the same label as another one is left out too: give it another label.
- What a view raises is shown in the preview panel as the item's error.
- What a code action raises is shown in **Python code** in place of its snippet.

## Turning them off

`StorageExplorer(user_actions="disabled")` reads no actions files, and its menu has no **Edit actions**.

In the launcher's tabs, an administrator can turn them off for everyone in a system `launcher.py`:

```python
def parameters():
    return {"user_actions": "disabled"}


def final():
    return ["user_actions"]
```

## Going further

The [Plugin development guide](plugin-development-guide.md) covers what actions can do beyond this guide:

- [the rules of actions](plugin-development-guide.md#actions), for views, code, checks and options;
- [formats of your own](plugin-development-guide.md#formats), detected by extension or content;
- [engines and packages](plugin-development-guide.md#engines-and-packages);
- packaging actions as a plugin, with tests and a README, e.g. written with an AI assistant.
