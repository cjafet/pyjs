"""Run PyJS source from a string or a file."""
import importlib.util
import os
import sys
import types

from .importer import install
from .transpiler import transpile

__all__ = ["run", "run_file"]


def run(source, filename="<pyjs>", namespace=None):
    """
    Execute PyJS source. It runs in a fresh namespace unless one is given,
    for example `pyjs.run(src, namespace=globals())`. Returns the namespace.
    """
    code = compile(
        transpile(source, filename, validate=False),
        filename,
        "exec",
        dont_inherit=True,
    )
    if namespace is None:
        namespace = {"__name__": "__main__", "__file__": filename}
    exec(code, namespace)
    return namespace


def run_file(path, args=()):
    """Run a .pyjs file as the main script, like `python script.py args...`."""
    path = os.path.abspath(path)
    with open(path, "rb") as handle:
        source = importlib.util.decode_source(handle.read())
    install()
    code = compile(
        transpile(source, path, validate=False), path, "exec", dont_inherit=True
    )

    module = types.ModuleType("__main__")
    module.__dict__.update(__file__=path, __package__=None, __cached__=None)

    saved_argv = sys.argv
    saved_path = list(sys.path)
    saved_main = sys.modules.get("__main__")
    sys.argv = [path, *args]
    sys.path.insert(0, os.path.dirname(path))
    sys.modules["__main__"] = module
    try:
        exec(code, module.__dict__)
    finally:
        sys.argv = saved_argv
        sys.path[:] = saved_path
        if saved_main is None:
            sys.modules.pop("__main__", None)
        else:
            sys.modules["__main__"] = saved_main
