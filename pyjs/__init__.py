"""
PyJS: JavaScript-style object literals for Python.

    import pyjs               # once per program or notebook

    user = @{name, age}       # in a .pyjs file or a notebook cell

Importing pyjs registers two things:
  * an import hook, so `import models` also finds `models.pyjs`
  * in IPython/Jupyter, a cell transformer, so every later cell accepts `@{}`

Command line: `pyjs file.pyjs`, `pyjs build ...`, `pyjs show ...` (see --help).
"""
from . import notebook
from .importer import install, uninstall
from .notebook import load_ipython_extension, unload_ipython_extension
from .runner import run, run_file
from .transpiler import PyJSSyntaxError, transpile

__version__ = "0.2.0"
__all__ = [
    "PyJSSyntaxError",
    "install",
    "load_ipython_extension",
    "run",
    "run_file",
    "transpile",
    "uninstall",
    "unload_ipython_extension",
]

install()
notebook.register_if_active()
