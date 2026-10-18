import importlib
import sys
import traceback

import pytest

import pyjs


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A temp folder on sys.path; modules imported from it are forgotten after."""
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    before = set(sys.modules)
    yield tmp_path
    for name in set(sys.modules) - before:
        del sys.modules[name]


def test_import_pyjs_module(project):
    (project / "pj_models.pyjs").write_text(
        "def make_user(name, age):\n    return @{name, age}\n"
    )
    module = importlib.import_module("pj_models")
    assert module.make_user("Ana", 30) == {"name": "Ana", "age": 30}


def test_import_package_with_relative_import(project):
    package = project / "pj_pkg"
    package.mkdir()
    (package / "__init__.pyjs").write_text("from .sub import build\n")
    (package / "sub.pyjs").write_text("def build(id):\n    return @{id, kind: 'x'}\n")
    module = importlib.import_module("pj_pkg")
    assert module.build(7) == {"id": 7, "kind": "x"}


def test_plain_python_module_wins_over_pyjs(project):
    (project / "pj_both.py").write_text("WHICH = 'py'\n")
    (project / "pj_both.pyjs").write_text("WHICH = 'pyjs'\n")
    assert importlib.import_module("pj_both").WHICH == "py"


def test_traceback_points_at_the_pyjs_file_and_right_line(project):
    path = project / "pj_boom.pyjs"
    path.write_text("a = 1\nr = @{\n    a,\n    b: 2,\n}\nraise ValueError('boom')\n")
    with pytest.raises(ValueError) as exc:
        importlib.import_module("pj_boom")
    last = traceback.extract_tb(exc.value.__traceback__)[-1]
    assert last.filename == str(path)
    assert last.lineno == 6


def test_syntax_error_in_imported_module_names_the_file(project):
    path = project / "pj_bad.pyjs"
    path.write_text("x = @{class: 1}\n")
    with pytest.raises(pyjs.PyJSSyntaxError) as exc:
        importlib.import_module("pj_bad")
    assert exc.value.args[1][0] == str(path)


def test_install_is_idempotent_and_uninstall_removes():
    from pyjs import importer

    pyjs.install()
    pyjs.install()
    assert sys.path_hooks.count(importer._hook) == 1
    pyjs.uninstall()
    assert importer._hook not in sys.path_hooks
    pyjs.install()
    assert sys.path_hooks.count(importer._hook) == 1


def test_modules_imported_before_install_still_work(project):
    # A folder already cached by Python's own finder must be re-scanned.
    import pyjs.importer as importer

    pyjs.uninstall()
    importlib.invalidate_caches()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pj_late")
    (project / "pj_late.pyjs").write_text("V = @{}\n")
    pyjs.install()
    assert importlib.import_module("pj_late").V == {}
    assert importer._hook in sys.path_hooks


def test_run_string_in_given_namespace():
    namespace = {"name": "Ana"}
    pyjs.run("greeting = @{name}", namespace=namespace)
    assert namespace["greeting"] == {"name": "Ana"}
