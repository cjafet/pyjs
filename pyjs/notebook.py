"""
Notebook support: makes every IPython/Jupyter cell understand `j{...}`.

`import pyjs` registers this automatically when it runs inside IPython, and
`%load_ext pyjs` does the same. Cell magics such as `%%time` are turned into
string arguments by IPython before this hook runs, so `j{}` inside the body of
a cell magic is not rewritten.
"""
import sys

from .transpiler import PREFIX, transpile

__all__ = [
    "load_ipython_extension",
    "register",
    "register_if_active",
    "unload_ipython_extension",
    "unregister",
]

TRANSFORMER_NAME = "pyjs_cell_transformer"


def pyjs_cell_transformer(lines):
    """IPython input transformer: list of lines in, list of lines out."""
    source = "".join(lines)
    if PREFIX + "{" not in source:
        return lines
    # IPython compiles the cell itself (and allows top-level await), so skip
    # our own validation. Syntax errors in @{} propagate and IPython shows them.
    result = transpile(source, filename="<cell>", validate=False)
    return result.splitlines(keepends=True)


def register(ip):
    """Add the transformer to an IPython shell (idempotent)."""
    unregister(ip)
    ip.input_transformers_post.append(pyjs_cell_transformer)


def unregister(ip):
    ip.input_transformers_post[:] = [
        t
        for t in ip.input_transformers_post
        if getattr(t, "__name__", "") != TRANSFORMER_NAME
    ]


def register_if_active():
    """Register on the running IPython shell, if there is one."""
    ipython = sys.modules.get("IPython")  # not imported means not in a notebook
    if ipython is None:
        return False
    shell = ipython.get_ipython()
    if shell is None:
        return False
    register(shell)
    return True


def load_ipython_extension(ip):
    register(ip)


def unload_ipython_extension(ip):
    unregister(ip)
