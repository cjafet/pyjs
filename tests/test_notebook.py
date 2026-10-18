import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("IPython")

import pyjs  # noqa: E402
from pyjs import notebook  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def shell(tmp_path, monkeypatch):
    monkeypatch.setenv("IPYTHONDIR", str(tmp_path / "ipython"))
    from IPython.core.interactiveshell import InteractiveShell

    InteractiveShell.clear_instance()
    ip = InteractiveShell.instance()
    notebook.register(ip)
    yield ip
    notebook.unregister(ip)
    InteractiveShell.clear_instance()


def test_cell_accepts_literal(shell):
    result = shell.run_cell("x = 1\nd = j{x, y: 2}")
    assert result.success, result.error_before_exec or result.error_in_exec
    assert shell.user_ns["d"] == {"x": 1, "y": 2}


def test_state_is_shared_between_cells(shell):
    shell.run_cell("name = 'Ana'")
    result = shell.run_cell("payload = j{name, tags: ['a']}")
    assert result.success
    assert shell.user_ns["payload"] == {"name": "Ana", "tags": ["a"]}


def test_line_magic_in_the_same_cell(shell):
    result = shell.run_cell("x = 1\n%pwd\nd = j{x}")
    assert result.success, result.error_before_exec or result.error_in_exec
    assert shell.user_ns["d"] == {"x": 1}


def test_cells_without_marker_are_untouched(shell):
    result = shell.run_cell("s = {1, 2}\nd = {'a': 1}\nt = f'{s}'")
    assert result.success
    assert shell.user_ns["d"] == {"a": 1}


def test_syntax_error_shows_pyjs_message(shell):
    result = shell.run_cell("d = j{class: 1}")
    assert not result.success
    assert isinstance(result.error_before_exec, pyjs.PyJSSyntaxError)
    assert "keyword" in result.error_before_exec.msg


def test_runtime_error_in_cell_reports_cell_line(shell):
    result = shell.run_cell("a = 1\nr = j{\n    a,\n    c: undefined_name,\n}")
    assert isinstance(result.error_in_exec, NameError)
    assert result.error_in_exec.__traceback__.tb_next.tb_lineno == 4


def test_registration_is_idempotent(shell):
    notebook.register(shell)
    notebook.register(shell)
    names = [t.__name__ for t in shell.input_transformers_post]
    assert names.count(notebook.TRANSFORMER_NAME) == 1


def test_load_ext_magic(shell):
    notebook.unregister(shell)
    assert not shell.run_cell("d = j{}").success
    shell.run_line_magic("load_ext", "pyjs")
    assert shell.run_cell("x = 1\nd = j{x}").success
    assert shell.user_ns["d"] == {"x": 1}


def test_plain_import_pyjs_in_a_fresh_notebook_process(tmp_path):
    code = textwrap.dedent(
        """
        from IPython.core.interactiveshell import InteractiveShell
        ip = InteractiveShell.instance()
        assert ip.run_cell("import pyjs").success
        result = ip.run_cell("x = 1\\nd = j{x, y: 2}")
        assert result.success, result.error_before_exec or result.error_in_exec
        assert ip.user_ns["d"] == {"x": 1, "y": 2}
        print("ok")
        """
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "IPYTHONDIR": str(tmp_path / "ipy")}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
