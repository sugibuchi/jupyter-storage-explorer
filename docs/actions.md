# Writing actions

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

## A first view

A view is a function decorated with `@view`. It takes the item and returns what to show:

```python
from jupyter_storage_explorer.formats import Text, TextView
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer.formats.python import PythonEngine


@view(format=Text, engine=PythonEngine, label="Shout")
def shout(fmt, ctx, options, limits):
    text, _ = ctx.head_text(limits.max_bytes)
    return TextView(text=text.upper())
```

Right-click a text file: **Preview as** now offers "Shout" after the explorer's own view.

The function's four parameters are always given in this order:

- `fmt`, the format the item was detected as, here a `Text`;
- `ctx`, the item, an `ItemContext`, which reads it;
- `options`, its options (see [Options](#options));
- `limits`, how much to read and show, a `ViewLimits`.

`ctx` gives what a view needs of the item:

| `ctx.`                 | What                                                                                       |
|------------------------|--------------------------------------------------------------------------------------------|
| `name`, `path`, `size` | The item's name, its path in its storage, and its size in bytes, if known.                 |
| `is_dir`               | Whether it is a folder.                                                                    |
| `url_or_local_path`    | Where libraries read it: its URL, or a local file's plain path.                            |
| `head_text(n)`         | Its first `n` bytes as text, and whether the file is longer.                               |
| `head(n)`              | Its first `n` bytes.                                                                       |
| `read_whole(limits)`   | The whole file, or an error if it is larger than `limits.max_whole_file_bytes`.            |
| `fs`                   | The explorer's fsspec filesystem the item is on, with its credentials.                     |

## Views of data

A view of a dataframe opens the data browser, where you page, sort and filter it. Return a `QueryView` of any
dataframe the data browser reads, best a lazy one, e.g. a polars LazyFrame:

```python
from jupyter_storage_explorer.formats import Parquet, QueryView
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer_polars_support import PolarsEngine


@view(format=Parquet, engine=PolarsEngine, label="Latest orders ({engine})")
def latest_orders(fmt, ctx, options, limits):
    import polars as pl

    data = pl.scan_parquet(ctx.url_or_local_path).sort("order_date", descending=True)
    return QueryView(data=data)
```

- `engine` is the library the view uses, as the explorer's engine menu shows it. `PythonEngine` is for Python
  alone; each engine plugin has its own, e.g. `PolarsEngine` from polars-support.
- Import libraries inside the function, as above. Your file is read by every explorer, also in kernels without them.
- The view is offered only when its engine's packages are installed.

The other views:

| View                   | Shows                                                                                      |
|------------------------|--------------------------------------------------------------------------------------------|
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

A code action is a function decorated with `@code`. It returns a snippet of Python, which **Python code** shows under
its engine:

```python
from inspect import cleandoc

from jupyter_storage_explorer.formats import Csv
from jupyter_storage_explorer.formats.actions import code
from jupyter_storage_explorer.formats.python import PythonEngine

READ_ROWS = cleandoc("""
    import csv

    import fsspec

    with fsspec.open({url}, "rt", newline="") as f:
        rows = list(csv.DictReader(f))
    """)


@code(format=Csv, engine=PythonEngine, label="Read as dicts")
def csv_as_dicts(fmt, ctx, options):
    return READ_ROWS.format(url=repr(ctx.url_or_local_path))
```

- Its parameters are those of a view, without `limits`.
- The code must run as it is in a new notebook: its imports first.
- The label says what the code does, e.g. "Read as dicts". **Python code** shows the engine already.
- Never put secrets in the code: it gets copied and shared. With options, see [Options](#options).

## Labels and the menus

The label is what you see in the menus:

- a view's label shows in **Preview as** and **View in new tab as**, when its engine has several views of the item;
- a code action's label is its title in **Python code**.

`{format}` and `{engine}` in a label are replaced by the labels of the format and the engine. A view's default label is
`"View as {format} ({engine})"`, e.g. "View as CSV (Polars)". Code actions need a label.

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


@view(format=Text, engine=PythonEngine, label="Shout", check=_small)
def shout(fmt, ctx, options, limits):
    ...
```

`check(fmt, ctx, options)` runs for each item you click, so it decides from what is known: the format, the name, the
path, the size and the options. It never reads the file.

## Options

An action can take options, which `engine_options` gives, by engine key and format name. Declare them as a frozen
dataclass subclassing `ActionOptions`, and annotate the `options` parameter with it:

```python
from dataclasses import dataclass

from jupyter_storage_explorer.formats import ActionOptions, Text, TextView
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer.formats.python import PythonEngine


@dataclass(frozen=True, kw_only=True)
class ShoutOptions(ActionOptions):
    exclamations: int = 1


@view(format=Text, engine=PythonEngine, label="Shout")
def shout(fmt, ctx, options: ShoutOptions, limits):
    text, _ = ctx.head_text(limits.max_bytes)
    return TextView(text=text.upper() + "!" * options.exclamations)
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
