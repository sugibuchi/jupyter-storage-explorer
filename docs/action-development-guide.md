# Action development guide

Actions are what the explorer does with a file or a folder of a format:

- a **view** shows it, in the preview panel or a tab of its own;
- **code** gives a snippet of Python loading it, in the right-click menu's **Python code**.

You can add your own actions to the explorer.

This guide covers actions for your own use. To package them for others, see the
[Plugin development guide](plugin-development-guide.md).

## Your actions file

Your actions go in `~/.jupyter/storage-explorer/actions.py`. The ⚙ menu's **Edit actions** opens it in JupyterLab's
editor, and creates it from a commented example if it is missing.

<img src="figs/actions-menu.png" width="164" alt="The explorer's settings menu, open: Columns, Edit actions, Reload actions and About">

Without the launcher's JupyterLab extension, which `jupyter-storage-explorer-launcher` installs, edit the file in any
editor.

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

Save it in your actions file, and choose **Reload actions** in the explorer's ⚙ menu. Right-click a file named
`*.json`: **Python code** now offers "Pretty print json".

<img src="figs/actions-first.png" width="417" alt="A JSON file's right-click menu, Python code open: Pretty print json (Python) beside the built-in snippets">

The template is a multi-line string, with `{url!r}` where the file's URL goes, in quotes. `.strip()` removes the
blank lines around it.

## Action basics

### `@view` and `@code`

An action is a function decorated with one of these:

- `@view` makes a view, offered in **Preview as** and **View in new tab as**;
- `@code` makes a code snippet, offered in **Python code**.

Both are in `jupyter_storage_explorer.formats.actions`.

### Formats

The first argument of `@view` and `@code` is the format of the files the action is offered for. The explorer's formats
are in `jupyter_storage_explorer.formats`:

| Format                           | Files                                                       |
|----------------------------------|-------------------------------------------------------------|
| `Text`                           | Plain text, `.txt`, and the base of every text format below |
| `PythonScript`, `Sql`, `Yaml`, … | Code and configuration, e.g. `.py`, `.sql`, `.yaml`, `.log` |
| `Markdown`                       | `.md`, `.markdown`                                          |
| `Json`                           | `.json`                                                     |
| `JsonLines`                      | `.jsonl`, `.ndjson`                                         |
| `Csv`                            | `.csv`, `.tsv`                                              |
| `Parquet`                        | `.parquet`, `.parq`                                         |
| `DeltaLake`                      | Folders of Delta Lake tables                                |
| `Excel`                          | `.xlsx`, `.xlsm`                                            |
| `Image`                          | No file itself: the base of every image format below        |
| `Png`, `Jpeg`, `Gif`, …          | Images, e.g. `.png`, `.jpg`, `.gif`, `.webp`                |
| `Svg`                            | `.svg`: an `Image` and a `Text` format                      |

[Supported formats](storage-explorer.md#supported-formats) lists the code, configuration and image formats.

Plugins add others, in their packages.

An action is also offered for the subclasses of its format, unless they have actions of their own of the same kind:

- `Text`'s view previews Python scripts, which have no views of their own.
- An `Image` action does every kind of image, e.g. PNG and JPEG images.
- Markdown files are previewed by Markdown's own view. **Preview as** still offers Text's, under "Text".
- CSV files get CSV's code in **Python code**, not Text's.

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
file_format(".abc")  # files named *.abc
file_format([".yml", ".yaml"])  # either ending
file_format(names="Dockerfile")  # files of that name
file_format(names="*.zarr", is_dir=True)  # folders, by name
file_format(".log", label="Logs", name="logs")  # with a label and a name of your own
```

Case is ignored.

### The action function

The function takes the parameters it names, in any order, of these:

- `url`: the item's URL, e.g. `"s3://bucket/a.csv"`, which fsspec opens, also for a local file (`file://`);
- `url_or_local_path`: the item's URL, but a local file's plain path, which most libraries read, e.g. polars or pandas;
- `name`: the item's name, e.g. `"a.csv"`;
- `path`: its path in its storage;
- `size`: its size in bytes, if known;
- `is_dir`: whether it is a folder;
- `fs`: the explorer's fsspec filesystem the item is on, with its credentials;
- `ctx`: the item, with all of the above and methods reading it, see [The item](#the-item);
- `fmt`: the format it was detected as;
- `options`: its options, see [Engines and options](#engines-and-options);
- `limits`: for views only, how much to read and show, see [View limits](#view-limits).

Any other parameter needs a default, which it keeps.

A code action returns its snippet, a `str`. The code must run as it is in a new notebook, with its imports first.
Never put secrets in it: code gets copied and shared.

A view returns what to show:

| Returned                           | Shown                                                     |
|------------------------------------|-----------------------------------------------------------|
| A `str`                            | As text.                                                  |
| A `dict` or a `list`               | As a collapsible tree.                                    |
| A dataframe                        | In the data browser, to page, sort and filter. Best lazy. |
| A Jupyter widget, e.g. ipywidgets' | As it is, as a notebook shows it: see [Views](#views).    |
| A view object                      | As the object says: see [Views](#views).                  |

For example, this view shows text files in upper case:

```python
from jupyter_storage_explorer.formats import Text
from jupyter_storage_explorer.formats.actions import view


@view(format=Text, label="Upper case")
def upper_case(fs, path):
    with fs.open(path, "rt") as f:
        return f.read(10_000).upper()
```

## Advanced actions

### Views

A view object shows more than plain data, e.g. highlighted text. The view classes are in
`jupyter_storage_explorer.formats`:

| View                                  | Shows                                                    |
|---------------------------------------|----------------------------------------------------------|
| `TextView(text=...)`                  | Text; with `html`, Pygments' HTML of it, highlighted.    |
| `MarkdownView(text=...)`              | Markdown, rendered.                                      |
| `TreeView(value=...)`                 | A JSON-like value, as a collapsible tree.                |
| `QueryView(data=...)`                 | A dataframe, in the data browser.                        |
| `TableView(columns=..., rows=...)`    | A small table of values, without the data browser.       |
| `MediaView(mime=..., data=...)`       | An image, from its bytes.                                |
| `TableSetView(nodes=..., loader=...)` | Several tables, e.g. a database's, in a tree or on tabs. |
| `JupyterWidgetView(widget=...)`       | A Jupyter widget, e.g. a chart's or a map's.             |

Each also takes a `title`, shown above the view, and a `note`, shown under it.

A Jupyter widget is any `ipywidgets.DOMWidget`, anywidgets included. Returning one shows it in a `JupyterWidgetView`:

```python
import ipywidgets

from jupyter_storage_explorer.formats import Csv
from jupyter_storage_explorer.formats.actions import view


@view(format=Csv, label="Size")
def size_gauge(name, size):
    return ipywidgets.FloatProgress(value=size or 0, max=10_000_000, description=name)
```

- Create a new widget in the function, and never display it yourself.
- The view owns the widget: closing the view closes the widget.
- JupyterLab shows widgets in the explorer. Other front ends, e.g. some IDEs, may not, and show an error instead.

#### Views with inputs

A view reading much, e.g. a whole large file, should ask the user first. It returns a question, which shows a message
and a button where the view would be:

- `ViewWithConfirmation` makes the view once the user clicks the button;
- `ViewWithChoice` offers choices, and makes the view of the one chosen;
- `ViewWithInput` asks for a text, e.g. a password, and makes the view of it.

Each takes a `message` and a `factory`, the function making the view of the answer. The factory returns a view
object, not plain data. Its options are listed after the example.

```python
from jupyter_storage_explorer.formats import Csv, TextView, ViewWithChoice, ViewWithConfirmation
from jupyter_storage_explorer.formats.actions import view


@view(format=Csv, label="Whole file")
def whole_file(fs, path):
    def read():
        return TextView(text=fs.cat_file(path).decode())

    return ViewWithConfirmation(message="This reads the whole file.", factory=read)


@view(format=Csv, label="Head")
def head(fs, path):
    def read(n):
        return TextView(text=fs.cat_file(path, start=0, end=n).decode(errors="replace"))

    return ViewWithChoice(
        message="How much to read?",
        choices={"1 KB": 1024, "1 MB": 1024 ** 2},
        factory=read,
        style="button",
    )
```

All three take these options:

| Option    | Default  | What                                                          |
|-----------|----------|---------------------------------------------------------------|
| `message` | Required | The question, shown above the button.                         |
| `factory` | Required | The function making the view of the answer.                   |
| `button`  | `"View"` | The button's label.                                           |

`ViewWithConfirmation` calls `factory()`, with no argument, and has no other options.

`ViewWithChoice` calls `factory(value)` with the value of the choice made. Its other options:

| Option        | Default   | What                                                                    |
|---------------|-----------|-------------------------------------------------------------------------|
| `choices`     | Required  | A `dict` of the labels shown, in order, to the values given `factory`.  |
| `style`       | `"radio"` | `"radio"` buttons, a `"dropdown"` menu, or a `"button"` for each label. |
| `default`     | `None`    | The label chosen at first. By default, the first one.                   |
| `with_cancel` | `False`   | Whether to add a **Cancel** button, which shows nothing.                |

With `style="button"`, a click on a label answers at once, and `button` is not shown.

`ViewWithInput` calls `factory(text)` with the text entered. Its other options:

| Option        | Default | What                               |
|---------------|---------|------------------------------------|
| `value`       | `""`    | The text in the field at first.    |
| `placeholder` | `""`    | The hint shown in the empty field. |

The answers are kept: when the data browser reads the data again, it asks no more.

#### View limits

A view's `limits` parameter says how much to read and show:

- `max_bytes`: the bytes of a file to show as text, 64 KiB by default;
- `max_display_rows`: the rows of a table to show, 100 by default;
- `max_whole_file_bytes`: the largest file to read whole, 10 MiB by default.

```python
@view(format=Text, label="Upper case")
def upper_case(fs, path, limits):
    with fs.open(path, "rb") as f:
        return f.read(limits.max_bytes).decode(errors="replace").upper()
```

### Labels

The label is what you see in the menus:

- a view's label shows in **Preview as** and **View in new tab as**, when its engine has several views of the item;
- a code action's label is its title in **Python code**.

Give one with `label=...`, or keep the default. `{format}` and `{engine}` in a label are replaced by the labels of the
format and the engine.

Two views, or two code actions, with the same format, engine and label are an error: you could not tell them apart in
the menus. Give yours a label of its own.

### Engines and options

The second argument of `@view` and `@code` is the engine: the library the action uses, as the explorer's engine menu
shows it. Each engine plugin has its own, e.g. `PolarsEngine` from polars-support. Without one, it is `PythonEngine`,
Python alone.

```python
from jupyter_storage_explorer.formats import Parquet
from jupyter_storage_explorer.formats.actions import view
from jupyter_storage_explorer_polars_support import PolarsEngine


@view(Parquet, PolarsEngine, label="Latest orders ({engine})")
def latest_orders(url_or_local_path):
    import polars as pl

    return pl.scan_parquet(url_or_local_path).sort("order_date", descending=True)
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
class UpperCaseOptions(ActionOptions):
    characters: int = 10_000


@view(format=Text, label="Upper case")
def upper_case(fs, path, options: UpperCaseOptions):
    with fs.open(path, "rt") as f:
        return f.read(options.characters).upper()
```

```python
StorageExplorer("s3://bucket/notes", engine_options={"python": {"text": {"characters": 500}}})
```

- Each option has a default, as users may set none.
- Define the class at the top level of your file, not inside a function.
- `PythonEngine`'s key is `"python"`. A format of yours is named by its `name`.
- An engine's options also reach its other actions of that format, the explorer's or the plugins'. A field of the same
  name must have the same type there.
- Mark a credential with `secret_field()` or `secret_dict_field()`, from `jupyter_storage_explorer.util`.
- Code shows options only through `options.code_value(name)`, which leaves secrets out.

### The item

The `ctx` parameter is the item, an `ItemContext`. It has what the other parameters give, and more:

| `ctx.`                                                             | What                                                                                  |
|--------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `url`, `url_or_local_path`, `name`, `path`, `size`, `is_dir`, `fs` | As the parameters of the same names.                                                  |
| `location`                                                         | Where the item is, independently of fsspec, e.g. an S3 bucket and key.                |
| `info`                                                             | fsspec's info of the item, e.g. its modification time.                                |
| `children`                                                         | A folder's listing, as fsspec's entries; `None` for a file.                           |
| `child_names`                                                      | The names of a folder's items.                                                        |
| `head(n)`                                                          | The file's first `n` bytes.                                                           |
| `head_text(n)`                                                     | Its first `n` bytes as text, cut after the last whole line, and whether it is longer. |
| `read_whole(limits)`                                               | The whole file, or an error if it is larger than `limits.max_whole_file_bytes`.       |

`ctx.head` reads the file once for the item: detection and other actions often read the same beginning. On cloud
storages, each read is a round trip.

This view shows a folder's items, and the beginning of a file:

```python
from jupyter_storage_explorer.formats import Text, file_format
from jupyter_storage_explorer.formats.actions import view


@view(format=file_format(names="*.zarr", is_dir=True), label="Arrays")
def arrays(ctx):
    return sorted(ctx.child_names)


@view(format=Text, label="Beginning")
def beginning(ctx, limits):
    text, longer = ctx.head_text(limits.max_bytes)
    return text + ("..." if longer else "")
```

### Preconditions

By default, an action is offered for every item of its format. `check` narrows it down:

```python
def _small(fmt, ctx, options):
    return ctx.size is not None and ctx.size < 1024 * 1024


@view(format=Text, label="Upper case", check=_small)
def upper_case(fs, path):
    with fs.open(path, "rt") as f:
        return f.read().upper()
```

`check` always takes `(fmt, ctx, options)`. It runs for each item you click, so it never reads the file. It decides
from what is known:

- the format;
- the item's name, path and size, from `ctx`;
- the options.

## When something goes wrong

- A file that cannot be read, e.g. with a syntax error, is left out with a warning, under the explorer's cell. The
  explorer still opens, with the other files' actions.
- On **Reload actions**, the explorer shows such a file's error instead, and keeps the other files' actions.
- A file with an action of the same label as another one is left out too: give it another label.
- What a view raises is shown in the preview panel as the item's error.
- What a code action raises is shown in **Python code** in place of its snippet.

## How the files are read

- Every explorer reads the files when it is created, wherever it is.
- **Reload actions** reads them again, and lists the folder shown again. The preview open keeps its view until you open
  another.
- It reads `actions.py` first, then the folder's files by name.
- Files whose names start with `_` are not read, so they can hold code the others share.
- A file gives every action defined in it, in order. A list named `ACTIONS` gives only the actions it names.
- The same files can go in the other configuration directories, which `jupyter --paths` lists under "config". Files
  there serve every user of the environment or the system, after yours.

## Turning them off

`StorageExplorer(user_actions="disabled")` reads no actions files, and its menu has neither **Edit actions** nor
**Reload actions**.

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
