# PyJS

JavaScript-style object literals for Python. Stop writing every key and value twice.

```python
# Plain Python
payload = {"name": name, "email": email, "address": address}

# With PyJS
payload = j{name, email, address}
```

PyJS is a small transpiler. It rewrites `j{...}` literals into ordinary Python dicts before your code runs and leaves everything else exactly as you wrote it. It works in notebooks, in scripts, and in imported modules.

## Install

```bash
pip install git+https://github.com/cjafet/pyjs.git
```

In a notebook:

```python
%pip install git+https://github.com/cjafet/pyjs.git
```

Pin a release by adding a tag, for example `...<repo>.git@v0.2.0`.

Requires Python 3.9 or newer. It is developed and tested on Python 3.13. Using `j{}` inside f-string fields needs Python 3.12 or newer.

## Quick start

### In a notebook (Jupyter / IPython)

Run this once, in the first cell:

```python
import pyjs
```

Every cell after that understands `j{}`:

```python
n_estimators = 200
max_depth = 8

params = j{n_estimators, max_depth}
# {'n_estimators': 200, 'max_depth': 8}

param_grid = j{n_estimators: [100, 200], max_depth: [4, 8]}
# {'n_estimators': [100, 200], 'max_depth': [4, 8]}

requests.post(url, json=j{name, version, params})
```

`%load_ext pyjs` does the same thing if you prefer the extension style.

### In scripts: `.pyjs` files

Python reads a whole file before running anything, so `j{}` cannot appear in a regular `.py` file. Put code that uses it in `.pyjs` files instead.

```python
# models.pyjs
def make_user(name, email, age):
    return j{name, email, age, active: True}
```

Run a `.pyjs` file directly:

```bash
pyjs main.pyjs
```

Or import `.pyjs` modules from regular Python:

```python
# app.py (regular Python)
import pyjs                 # registers the import hook once

import models               # loads models.pyjs
print(models.make_user("Ana", "ana@example.com", 30))
```

## Syntax

| You write | You get |
|---|---|
| `j{name, age}` | `{'name': name, 'age': age}` |
| `j{name, active: True}` | `{'name': name, 'active': True}` |
| `j{email: address}` | `{'email': address}` |
| `j{"Content-Type": ct}` | `{"Content-Type": ct}` |
| `j{[key]: value}` | `{key: value}` (computed key) |
| `j{**defaults, debug: True}` | `{**defaults, 'debug': True}` (spread) |
| `j{user: j{name, age}}` | `{'user': {'name': name, 'age': age}}` (nesting) |

Values can be any expression: lists, lambdas, f-strings, function calls, and so on.

### Rules

- **A bare name used as a key becomes a string**, exactly like JavaScript. `j{active: True}` means `{'active': True}`.
- **Quoted keys, numbers, and `True`/`False`/`None` are kept as written.**
- **Python keywords can't be bare keys.** Write `j{"class": "x"}`, not `j{class: "x"}`. PyJS tells you when you forget.
- **Comprehensions use plain braces.** `j{k: v for ...}` is rejected; write `{k: v for k, v in pairs}` as usual.
- **Everything without the `j` marker is untouched.** Sets, dicts, f-strings, strings, and comments behave exactly as in Python.
- **`obj.j{...}` is attribute access, not a literal.** The marker only counts where `j` is not preceded by a dot.

## Command line

```bash
pyjs FILE [ARGS...]           # run a .pyjs file (same as: pyjs run FILE)
pyjs build PATH... [-o OUT]   # write .py files next to the .pyjs sources
pyjs show FILE                # print the generated Python
```

`pyjs build` is useful when you want to ship plain Python. `pyjs show` helps you see what a literal turns into.

## Python API

```python
import pyjs

pyjs.transpile("d = j{x, y: 2}")             # "d = {'x': x, 'y': 2}"
pyjs.run("print(j{x})", namespace={"x": 1})   # run a snippet in a namespace
pyjs.run_file("main.pyjs", args=["--fast"])   # run a file as the main script
pyjs.install() / pyjs.uninstall()             # the .pyjs import hook
```

Syntax mistakes raise `pyjs.PyJSSyntaxError`, a `SyntaxError` that carries the file, line, and column.

## How it works

PyJS tokenizes your source with Python's own tokenizer, finds the `j{` markers, and rewrites only those literals. It never searches text, so strings and comments are safe.

- **Line numbers are preserved.** The generated code has the same number of lines as your source, so tracebacks point at the right line.
- **Imports are transpiled in memory.** No generated files are written, and nothing is cached.
- **A plain `.py` module wins over a `.pyjs` module with the same name in the same folder.**

## Limitations

- `j{}` only works in `.pyjs` files and notebook cells, not in regular `.py` files.
- Editors, linters, and formatters don't understand `j{}` yet. A notebook may highlight it as an error even though the cell runs.
- In notebooks, `j{}` inside the body of a cell magic such as `%%time` is not rewritten, because IPython turns that body into a string first.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the transpiler, the import hook, the command line, and the notebook support (against a real IPython).

## Roadmap

Planned, with the exact syntax still to be decided:

- Destructuring, like `const {name, age} = user` in JavaScript
- Optional chaining, like `user?.address?.city`
- Dot access on objects, like `user.name`, through a small runtime library

## License

_To be decided. Add a `LICENSE` file and update this section._
