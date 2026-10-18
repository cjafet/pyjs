"""Import hook: lets `import models` find and load `models.pyjs`."""
import importlib.machinery
import importlib.util
import sys

from .transpiler import transpile

SUFFIX = ".pyjs"

__all__ = ["PyJSLoader", "install", "uninstall"]


class PyJSLoader(importlib.machinery.SourceFileLoader):
    """Loads a .pyjs file: transpile in memory, then compile as usual."""

    def get_code(self, fullname):
        # No bytecode cache: the generated code depends on the transpiler version.
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)

    def source_to_code(self, data, path, *, _optimize=-1):
        source = importlib.util.decode_source(data)
        python = transpile(source, filename=str(path), validate=False)
        return compile(python, str(path), "exec", dont_inherit=True, optimize=_optimize)


def _make_hook():
    # `.pyjs` is added as one more module suffix next to the standard ones, so
    # packages, submodules and sys.path order all behave like normal Python.
    # The standard loaders come first: a plain .py wins over a .pyjs file.
    details = [
        (importlib.machinery.ExtensionFileLoader, importlib.machinery.EXTENSION_SUFFIXES),
        (importlib.machinery.SourceFileLoader, importlib.machinery.SOURCE_SUFFIXES),
        (importlib.machinery.SourcelessFileLoader, importlib.machinery.BYTECODE_SUFFIXES),
        (PyJSLoader, [SUFFIX]),
    ]
    return importlib.machinery.FileFinder.path_hook(*details)


_hook = _make_hook()


def install():
    """Register the hook (idempotent)."""
    if _hook in sys.path_hooks:
        return
    sys.path_hooks.insert(0, _hook)
    sys.path_importer_cache.clear()  # folders already seen must be re-scanned
    importlib.invalidate_caches()


def uninstall():
    while _hook in sys.path_hooks:
        sys.path_hooks.remove(_hook)
    sys.path_importer_cache.clear()
