import traceback

import pytest

from pyjs import PyJSSyntaxError, transpile


def ev(src, **env):
    out = transpile(src)
    ns = dict(env)
    exec(out, ns)
    return ns


# ---- basic syntax ----------------------------------------------------------

def test_shorthand():
    assert ev("name='a'; age=1; r = @{name, age}")["r"] == {"name": "a", "age": 1}


def test_mixed_and_key_value():
    ns = ev("name='a'; address='x@y'; r = @{name, active: True, email: address}")
    assert ns["r"] == {"name": "a", "active": True, "email": "x@y"}


def test_string_and_number_keys():
    assert ev("r = @{'a-b': 1, 2: 3}")["r"] == {"a-b": 1, 2: 3}


def test_constant_keys_keep_python_meaning():
    assert ev("r = @{True: 1, None: 2}")["r"] == {True: 1, None: 2}


def test_computed_key_and_spread():
    ns = ev("k='z'; d={'a': 1}; r = @{[k]: 2, **d, b: 3}", b=0)
    assert ns["r"] == {"z": 2, "a": 1, "b": 3}


def test_nested():
    ns = ev("name='a'; r = @{user: @{name}, tags: [@{name}]}")
    assert ns["r"] == {"user": {"name": "a"}, "tags": [{"name": "a"}]}


def test_empty():
    assert ev("r = @{}")["r"] == {}


def test_lambda_values_and_slices():
    ns = ev("xs=[1,2,3]; r = @{f: lambda a, b: a + b, part: xs[0:2]}")
    assert ns["r"]["f"](1, 2) == 3 and ns["r"]["part"] == [1, 2]


def test_comprehension_inside_a_value_is_fine():
    ns = ev("xs=[1,2]; r = @{doubled: [x * 2 for x in xs]}")
    assert ns["r"] == {"doubled": [2, 4]}


def test_multiline_with_comments():
    src = "a=1\nb=2\nr = @{\n    a,  # first\n    b,\n}\n"
    assert ev(src)["r"] == {"a": 1, "b": 2}


def test_non_ascii_source():
    src = 'nome = "João"  # café\nr = @{nome, cidade: "São Paulo"}\n'
    assert ev(src)["r"] == {"nome": "João", "cidade": "São Paulo"}


# ---- leaving normal Python alone ------------------------------------------

def test_plain_python_untouched():
    src = 'a=1\ns = {a, 2}\nd = {"x": 1}\nf = f"{a}"\nm = {"k": {a}}\n'
    assert transpile(src) == src


def test_strings_and_comments_untouched():
    src = 'x = "@{name}"  # @{name}\n'
    assert transpile(src) == src


def test_matmul_not_confused():
    src = "import numpy as np\nm = np.eye(2)\nr = m @{1, 2}\n"
    assert transpile(src) == src


def test_marker_at_statement_start_is_not_matmul():
    assert transpile("a = 1\n@{a}.get('a')\n") == "a = 1\n{'a': a}.get('a')\n"


def test_marker_after_open_bracket_on_new_line():
    ns = ev("a = 1\nr = [\n    @{a},\n]\n")
    assert ns["r"] == [{"a": 1}]


# ---- f-strings -------------------------------------------------------------

def test_fstring_with_literal_inside_expression_part():
    ns = ev("name='a'; r = f'{name}-{len(@{name})}'")
    assert ns["r"] == "a-1"


def test_fstring_field_starting_with_literal():
    assert ev("a=1; r = f'{@{a}}'")["r"] == "{'a': 1}"


def test_fstring_literal_text_not_matched():
    src = "a=1\nr = f'@{a}'\n"
    assert transpile(src) == src


def test_fstring_escaped_braces_before_literal():
    assert ev("a=1; r = f'{{x}} {len(@{a})}'")["r"] == "{x} 1"


# ---- line numbers ----------------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "r = @{a, b}\n",
        "r = @{\n    a,\n    b,\n}\nx = 1\n",
        "r = @{\n\n    a,  # c\n\n    b\n\n}\n",
        "r = @{a,\n  b: [\n    1,\n    2,\n  ],\n  c: @{\n    d: 1,\n  }}\n",
        "r = @{\n}\n",
        "r = @{**\n  a, [\n  k]: 1}\n",
        "r = @{a:\n  1}\n",
    ],
)
def test_line_count_preserved(src):
    assert transpile(src).count("\n") == src.count("\n")


def test_error_rows_match_source():
    src = "a = 1\nr = @{\n    a,\n    c: undefined_name,\n}\n"
    code = compile(transpile(src), "<t>", "exec")
    with pytest.raises(NameError) as exc:
        exec(code, {})
    assert traceback.extract_tb(exc.value.__traceback__)[-1].lineno == 4


# ---- validation and errors -------------------------------------------------

def test_top_level_await_needs_validate_false():
    src = "r = @{a}\nawait f()\n"
    assert "{'a': a}" in transpile(src, validate=False)
    with pytest.raises(PyJSSyntaxError):
        transpile(src)


@pytest.mark.parametrize(
    "bad",
    [
        "x = @{1}",
        "x = @{a b}",
        "x = @{a: }",
        "x = @{: 1}",
        "x = @{class: 1}",
        "x = @{class}",
        "x = @{k: v for k, v in p}",
        "x = @{[]: 1}",
        "x = @{**}",
    ],
)
def test_errors(bad):
    with pytest.raises(PyJSSyntaxError):
        transpile(bad)


def test_keyword_key_message_says_what_to_do():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("x = @{class: 1}")
    assert "keyword" in exc.value.msg and "quoted" in exc.value.msg


def test_comprehension_message_points_to_plain_braces():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("x = @{k: v for k, v in p}")
    assert "Comprehensions" in exc.value.msg


def test_error_reports_line_and_column():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("a = 1\nx = @{a b}\n", filename="demo.pyjs")
    filename, line, column, _text = exc.value.args[1]
    assert (filename, line) == ("demo.pyjs", 2)
    assert column > 1


def test_unmatched_bracket():
    with pytest.raises(PyJSSyntaxError):
        transpile("x = @{a, b")
