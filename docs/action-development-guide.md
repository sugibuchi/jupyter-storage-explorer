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
editor, and creates it from a commented example if it is missing. Without the launcher's JupyterLab extension, which
`jupyter-storage-explorer-launcher` installs, edit the file in any editor.

In addition, you can store actions in Python files under `~/.jupyter/storage-explorer/actions/`:

```
~/.jupyter/storage-explorer/
  actions.py
  actions/
    action-1.py
    action-2.py
    ...
```

## A first action

This action gives code pretty-printing a JSON file:

```python
from jupyter_storage_explorer.formats import Json
from jupyter_storage_explorer.formats.actions import code

PRETTY_PRINT = """
import json

import fsspec

with fsspec.open({url!r}) as f:
    print(json.dumps(json.load(f), indent=4))
""".strip()


@code(format=Json)
def pretty_print_json(url):
    return PRETTY_PRINT.format(url=url)
```

Save it in your actions file, and create the explorer again: run its cell again, or open a new tab. Right-click a file named `*.json`: **Python code** now
offers "Pretty print json".

The template is a multi-line string, with `{url!r}` where the file's URL goes, in quotes. `.strip()` removes the
blank lines around it.

## Action basics

### Views and code

An action is a function decorated with one of these:

- `@view` makes a view, offered in **Preview as** and **View in new tab as**;
- `@code` makes a code snippet, offered in **Python code**.

Both are in `jupyter_storage_explorer.formats.actions`.

### Formats

The first argument of `@view` and `@code` is the format of the files the action is offered for. The explorer's formats
are in `jupyter_storage_explorer.formats`:

| Format      | Files                                                                  |
|-------------|------------------------------------------------------------------------|
| `Text`      | Text and code, e.g. `.txt`, `.log`, `.py`, `.sql`, `.yaml`, `.xml`     |
| `Markdown`  | `.md`, `.markdown`                                                     |
| `Json`      | `.json`                                                                |
| `JsonLines` | `.jsonl`, `.ndjson`                                                    |
| `Csv`       | `.csv`, `.tsv`                                                         |
| `Parquet`   | `.parquet`, `.parq`                                                    |
| `DeltaLake` | Folders of Delta Lake tables                                           |
| `Excel`     | `.xlsx`, `.xlsm`                                                       |
| `Image`     | `.png`, `.jpg`, `.gif`, `.webp`, `.svg` and other images               |

Plugins add others, in their packages. An action is also offered for the subclasses of its format, e.g. a `Text`
action for Markdown files.

For files no format covers, make a format of your own with `file_format`, from `jupyter_storage_explorer.formats`:

```python
from jupyter_storage_explorer.formats import file_format
from jupyter_storage_explorer.formats.actions import code

READ_AVRO = """
import fastavro
import fsspec

with fsspec.open({url!r}, "rb") as f:
    records = list(fastavro.reader(f))
""".strip()


@code(format=file_format(".avro"))
def read_avro_records(url):
    return READ_AVRO.format(url=url)
```

`file_format` names the files in several ways:

```python
file_format(".abc")                            # files named *.abc
file_format([".yml", ".yaml"])                 # either ending
file_format(names="Dockerfile")                # files of that name
file_format(names="*.zarr", is_dir=True)       # folders, by name
file_format(".log", label="Logs", name="logs") # with a label and a name of your own
```

Case is ignored.

### The action function

The function takes the parameters it names, in any order, of these:

- `url`: where libraries read the item, its URL or a local file's plain path;
- `name`: the item's name, e.g. `"a.csv"`;
- `path`: its path in its storage;
- `size`: its size in bytes, if known;
- `is_dir`: whether it is a folder;
- `fs`: the explorer's fsspec filesystem the item is on, with its credentials;
- `ctx`: the item, with all of the above and methods reading it, such as `ctx.head_text(n)`;
- `fmt`: the format it was detected as;
- `options`: its options, see [Engines and options](#engines-and-options);
- `limits`: for views only, how much to read and show.

Any other parameter needs a default, which it keeps.

A code action returns its snippet, a `str`. The code must run as it is in a new notebook, with its imports first.
Never put secrets in it: code gets copied and shared.

A view returns what to show:

| Returned                           | Shown                                                         |
|------------------------------------|---------------------------------------------------------------|
| A `str`                            | As text.                                                      |
| A `dict` or a `list`               | As a collapsible tree.                                        |
| A dataframe                        | In the data browser, to page, sort and filter. Best lazy.     |
| A view object                      | As the object says: see [Views](#views).                      |

For example, this view shows text files in upper case:

```python
from jupyter_storage_explorer.formats import Text
from jupyter_storage_explorer.formats.actions import view


@view(Text, label="Shout")
def shout(ctx, limits):
    text, _ = ctx.head_text(limits.max_bytes)
    return text.upper()
```

## Advanced actions

### Views

A view object shows more than plain data, e.g. highlighted text. The view classes are in
`jupyter_storage_explorer.formats`:

| View                                  | Shows                                                       |
|---------------------------------------|-------------------------------------------------------------|
| `TextView(text=...)`                  | Text; with `language`, e.g. `"sql"`, highlighted.           |
| `MarkdownView(text=...)`              | Markdown, rendered.                                         |
| `TreeView(value=...)`                 | A JSON-like value, as a collapsible tree.                   |
| `QueryView(data=...)`                 | A dataframe, in the data browser.                           |
| `TableView(columns=..., rows=...)`    | A small table of values, without the data browser.          |
| `MediaView(mime=..., data=...)`       | An image, from its bytes.                                   |
| `TableSetView(nodes=..., loader=...)` | Several tables, e.g. a database's, in a tree or on tabs.    |

Each also takes a `title`, shown above the view, and a `note`, shown under it.

A view reading much, e.g. a whole large file, should ask the user first. It returns a question, which shows a message
and a button where the view would be:

- `ViewWithConfirmation` makes the view once the user clicks the button;
- `ViewWithChoice` offers choices, and makes the view of the one chosen;
- `ViewWithInput` asks for a text, e.g. a password, and makes the view of it.

Each takes a `message` and a `factory`, the function making the view of the answer. The factory returns a view
object, not plain data.

```python
from jupyter_storage_explorer.formats import Csv, TextView, ViewWithChoice, ViewWithConfirmation
from jupyter_storage_explorer.formats.actions import view


@view(format=Csv, label="Whole file")
def whole_file(fs, path, size):
    def read():
        return TextView(text=fs.cat_file(path).decode())

    return ViewWithConfirmation(message=f"This reads the whole file ({size:,} bytes).", factory=read)


@view(format=Csv, label="Head")
def head(fs, path):
    def read(n):
        return TextView(text=fs.cat_file(path, start=0, end=n).decode(errors="replace"))

    return ViewWithChoice(
        message="How much to read?",
        choices={"1 KB": 1024, "1 MB": 1024**2},
        factory=read,
        style="button",
    )
```

- `button` is the button's label, "View" by default.
- `ViewWithChoice`'s `style` is `"radio"`, `"dropdown"` or `"button"`, a button for each choice.
- `with_cancel=True` adds a **Cancel** button to a choice, which shows nothing.
- The answers are kept: when the data browser reads the data again, it asks no more.

### Labels

The label is what you see in the menus:

- a view's label shows in **Preview as** and **View in new tab as**, when its engine has several views of the item;
- a code action's label is its title in **Python code**.

Give one with `label=...`, or keep the default. `{format}` and `{engine}` in a label are replaced by the labels of the
format and the engine.

Two actions of one kind, format, engine and label are an error: you could not tell them apart in the menus. Give
yours a label of its own.

### Engines and options

The second argument of `@view` and `@code` is the engine: the library the action uses, as the explorer's engine menu
shows it. Each engine plugin has its own, e.g. `PolarsEngine` from polars-support. Without one, it is `PythonEngine`,
Python alone.

```python
from jupyter_storage_explorer.formats import Parquet
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer_polars_support import PolarsEngine


@view(Parquet, PolarsEngine, label="Latest orders ({engine})")
def latest_orders(url):
    import polars as pl

    return pl.scan_parquet(url).sort("order_date", descending=True)
```

- The action is offered only when its engine's packages are installed.
- Import libraries inside the function, as above. Your file is read by every explorer, also in kernels without them.
- **Python code** shows code under its engine, so a code action's label needs not name it.

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
- `PythonEngine`'s key is `"python"`. A format of yours is named by its `name`.
- An engine's options also reach the plugin's actions of that format. A field of the same name must have the same type
  there.
- Mark a credential with `secret_field()` or `secret_dict_field()`, from `jupyter_storage_explorer.util`.
- Code shows options only through `options.code_value(name)`, which leaves secrets out.

### Preconditions

By default, an action is offered for every item of its format. `check` narrows it down:

```python
def _small(fmt, ctx, options):
    return ctx.size is not None and ctx.size < 1024 * 1024


@view(Text, label="Shout", check=_small)
def shout(ctx, limits):
    return ctx.head_text(limits.max_bytes)[0].upper()
```

`check` always takes `(fmt, ctx, options)`. It runs for each item you click, so it decides from what is known: the
format, the name, the path, the size and the options. It never reads the file.

## When something goes wrong

- A file that cannot be read, e.g. with a syntax error, is left out with a warning, under the explorer's cell. The
  explorer still opens, with the other files' actions.
- A file with an action of the same label as another one is left out too: give it another label.
- What a view raises is shown in the preview panel as the item's error.
- What a code action raises is shown in **Python code** in place of its snippet.

## How the files are read

- Every explorer reads the files when it is created, in notebooks, the launcher's tabs and the side panel.
- It reads `actions.py` first, then the folder's files by name.
- Files whose names start with `_` are not read, so they can hold code the others share.
- A file gives every action defined in it, in order. A list named `ACTIONS` gives only the actions it names.
- The same files can go in the other configuration directories, which `jupyter --paths` lists under "config". Files
  there serve every user of the environment or the system, after yours.

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
