import sys
import traceback

import pytest

from pyjs import PyJSSyntaxError, transpile

needs_312 = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="f-string expression rewriting needs Python 3.12+",
)


def ev(src, **env):
    out = transpile(src)
    ns = dict(env)
    exec(out, ns)
    return ns


# ---- basic syntax ----------------------------------------------------------

def test_shorthand():
    assert ev("name='a'; age=1; r = j{name, age}")["r"] == {"name": "a", "age": 1}


def test_mixed_and_key_value():
    ns = ev("name='a'; address='x@y'; r = j{name, active: True, email: address}")
    assert ns["r"] == {"name": "a", "active": True, "email": "x@y"}


def test_string_and_number_keys():
    assert ev("r = j{'a-b': 1, 2: 3}")["r"] == {"a-b": 1, 2: 3}


def test_constant_keys_keep_python_meaning():
    assert ev("r = j{True: 1, None: 2}")["r"] == {True: 1, None: 2}


def test_computed_key_and_spread():
    ns = ev("k='z'; d={'a': 1}; r = j{[k]: 2, **d, b: 3}", b=0)
    assert ns["r"] == {"z": 2, "a": 1, "b": 3}


def test_nested():
    ns = ev("name='a'; r = j{user: j{name}, tags: [j{name}]}")
    assert ns["r"] == {"user": {"name": "a"}, "tags": [{"name": "a"}]}


def test_empty():
    assert ev("r = j{}")["r"] == {}


def test_lambda_values_and_slices():
    ns = ev("xs=[1,2,3]; r = j{f: lambda a, b: a + b, part: xs[0:2]}")
    assert ns["r"]["f"](1, 2) == 3 and ns["r"]["part"] == [1, 2]


def test_comprehension_inside_a_value_is_fine():
    ns = ev("xs=[1,2]; r = j{doubled: [x * 2 for x in xs]}")
    assert ns["r"] == {"doubled": [2, 4]}


def test_multiline_with_comments():
    src = "a=1\nb=2\nr = j{\n    a,  # first\n    b,\n}\n"
    assert ev(src)["r"] == {"a": 1, "b": 2}


def test_non_ascii_source():
    src = 'nome = "João"  # café\nr = j{nome, cidade: "São Paulo"}\n'
    assert ev(src)["r"] == {"nome": "João", "cidade": "São Paulo"}


# ---- leaving normal Python alone ------------------------------------------

def test_plain_python_untouched():
    src = 'a=1\ns = {a, 2}\nd = {"x": 1}\nf = f"{a}"\nm = {"k": {a}}\n'
    assert transpile(src) == src


def test_strings_and_comments_untouched():
    src = 'x = "j{name}"  # j{name}\n'
    assert transpile(src) == src


def test_j_variable_in_for_loop():
    src = "for j in range(3):\n    pass\n"
    assert transpile(src) == src


def test_j_in_set_literal():
    src = "j = 1\ns = {j}\n"
    assert transpile(src) == src


def test_j_in_list():
    src = "j = 1\nl = [j]\n"
    assert transpile(src) == src


def test_j_in_fstring():
    src = "j = 1\nr = f'{j}'\n"
    assert transpile(src) == src


def test_imaginary_literal():
    src = "c = 1j\n"
    assert transpile(src) == src


def test_j_as_dict_subscript():
    src = "j = 'k'\nd = {'k': 1}\nr = d[j]\n"
    assert transpile(src) == src


def test_dot_j_is_attribute_not_marker():
    src = "class C:\n    pass\nobj = C()\nobj.j = {1: 2}\n"
    assert transpile(src) == src


def test_other_name_before_brace():
    src = "d = 1\nr = d\ns = {1}\n"
    assert transpile(src) == src


def test_double_letter_prefix_not_marker():
    src = "jj = 1\nr = jj\ns = {1}\n"
    assert transpile(src) == src


def test_fstring_format_spec_with_j():
    src = "j = 2\nx = 3.14\nr = f'{x:j{x}}'\n"
    assert transpile(src) == src


def test_marker_at_statement_start():
    assert transpile("a = 1\nj{a}.get('a')\n") == "a = 1\n{'a': a}.get('a')\n"


def test_marker_after_open_bracket_on_new_line():
    ns = ev("a = 1\nr = [\n    j{a},\n]\n")
    assert ns["r"] == [{"a": 1}]


# ---- f-strings -------------------------------------------------------------

@needs_312
def test_fstring_with_literal_inside_expression_part():
    ns = ev("name='a'; r = f'{name}-{len(j{name})}'")
    assert ns["r"] == "a-1"


@needs_312
def test_fstring_field_starting_with_literal():
    assert ev("a=1; r = f'{j{a}}'")["r"] == "{'a': 1}"


def test_fstring_literal_text_not_matched():
    src = "a=1\nr = f'j{a}'\n"
    assert transpile(src) == src


@needs_312
def test_fstring_escaped_braces_before_literal():
    assert ev("a=1; r = f'{{x}} {len(j{a})}'")["r"] == "{x} 1"


# ---- line numbers ----------------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "r = j{a, b}\n",
        "r = j{\n    a,\n    b,\n}\nx = 1\n",
        "r = j{\n\n    a,  # c\n\n    b\n\n}\n",
        "r = j{a,\n  b: [\n    1,\n    2,\n  ],\n  c: j{\n    d: 1,\n  }}\n",
        "r = j{\n}\n",
        "r = j{**\n  a, [\n  k]: 1}\n",
        "r = j{a:\n  1}\n",
    ],
)
def test_line_count_preserved(src):
    assert transpile(src).count("\n") == src.count("\n")


def test_error_rows_match_source():
    src = "a = 1\nr = j{\n    a,\n    c: undefined_name,\n}\n"
    code = compile(transpile(src), "<t>", "exec")
    with pytest.raises(NameError) as exc:
        exec(code, {})
    assert traceback.extract_tb(exc.value.__traceback__)[-1].lineno == 4


# ---- validation and errors -------------------------------------------------

def test_top_level_await_needs_validate_false():
    src = "r = j{a}\nawait f()\n"
    assert "{'a': a}" in transpile(src, validate=False)
    with pytest.raises(PyJSSyntaxError):
        transpile(src)


@pytest.mark.parametrize(
    "bad",
    [
        "x = j{1}",
        "x = j{a b}",
        "x = j{a: }",
        "x = j{: 1}",
        "x = j{class: 1}",
        "x = j{class}",
        "x = j{k: v for k, v in p}",
        "x = j{[]: 1}",
        "x = j{**}",
    ],
)
def test_errors(bad):
    with pytest.raises(PyJSSyntaxError):
        transpile(bad)


def test_keyword_key_message_says_what_to_do():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("x = j{class: 1}")
    assert "keyword" in exc.value.msg and "quoted" in exc.value.msg


def test_comprehension_message_points_to_plain_braces():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("x = j{k: v for k, v in p}")
    assert "Comprehensions" in exc.value.msg


def test_error_reports_line_and_column():
    with pytest.raises(PyJSSyntaxError) as exc:
        transpile("a = 1\nx = j{a b}\n", filename="demo.pyjs")
    filename, line, column, _text = exc.value.args[1]
    assert (filename, line) == ("demo.pyjs", 2)
    assert column > 1


def test_unmatched_bracket():
    with pytest.raises(PyJSSyntaxError):
        transpile("x = j{a, b")


# ---- destructuring ---------------------------------------------------------

def test_destr_shorthand():
    ns = ev("user = {'name': 'Ana', 'age': 30}\nj{name, age} = user")
    assert ns["name"] == "Ana" and ns["age"] == 30


def test_destr_rename():
    ns = ev("user = {'email': 'a@b'}\nj{email: mail} = user")
    assert ns["mail"] == "a@b"


def test_destr_default_missing():
    ns = ev("user = {'name': 'Ana'}\nj{name, role = 'guest'} = user")
    assert ns["name"] == "Ana" and ns["role"] == "guest"


def test_destr_default_present():
    ns = ev("user = {'role': 'admin'}\nj{role = 'guest'} = user")
    assert ns["role"] == "admin"


def test_destr_nested():
    ns = ev("data = {'address': {'city': 'SP'}}\nj{address: j{city}} = data")
    assert ns["city"] == "SP"


def test_destr_nested_multiple():
    ns = ev("data = {'a': {'x': 1, 'y': 2}}\nj{a: j{x, y}} = data")
    assert ns["x"] == 1 and ns["y"] == 2


def test_destr_deep_nested():
    ns = ev("data = {'a': {'b': {'c': 42}}}\nj{a: j{b: j{c}}} = data")
    assert ns["c"] == 42


def test_destr_rest():
    ns = ev("d = {'name': 'Ana', 'age': 30, 'role': 'admin'}\nj{name, **rest} = d")
    assert ns["name"] == "Ana" and ns["rest"] == {"age": 30, "role": "admin"}


def test_destr_mixed():
    src = (
        "data = {'name': 'Ana', 'email': 'a@b', 'role': 'admin', 'x': 1}\n"
        "j{name, email: mail, role = 'guest', **rest} = data"
    )
    ns = ev(src)
    assert ns["name"] == "Ana"
    assert ns["mail"] == "a@b"
    assert ns["role"] == "admin"
    assert ns["rest"] == {"x": 1}


def test_destr_once_only():
    src = (
        "calls = 0\n"
        "def get():\n"
        "    global calls\n"
        "    calls += 1\n"
        "    return {'a': 1, 'b': 2}\n"
        "j{a, b} = get()\n"
    )
    ns = ev(src)
    assert ns["a"] == 1 and ns["b"] == 2 and ns["calls"] == 1


def test_destr_missing_key_raises():
    with pytest.raises(KeyError):
        ev("j{x} = {}")


def test_destr_single_target():
    ns = ev("d = {'x': 42}\nj{x} = d")
    assert ns["x"] == 42


def test_destr_in_function():
    src = (
        "def f(d):\n"
        "    j{name, age} = d\n"
        "    return name, age\n"
        "r = f({'name': 'Ana', 'age': 30})\n"
    )
    assert ev(src)["r"] == ("Ana", 30)


def test_destr_in_class_body():
    src = (
        "_data = {'x': 1, 'y': 2}\n"
        "class C:\n"
        "    j{x, y} = _data\n"
    )
    ns = ev(src)
    assert ns["C"].x == 1 and ns["C"].y == 2


def test_destr_rhs_is_literal():
    ns = ev("j{x} = j{x: 42}")
    assert ns["x"] == 42


def test_destr_stmt_start_no_eq_stays_literal():
    assert transpile("a = 1\nj{a}.get('a')\n") == "a = 1\n{'a': a}.get('a')\n"


# ---- destructuring line count preservation ---------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "j{name} = d\n",
        "j{name, age} = d\n",
        "j{\n    name,\n    age,\n} = d\n",
        "j{\n    name,\n    age,\n    **rest,\n} = d\n",
        "j{a: j{x}} = d\n",
    ],
)
def test_destr_line_count_preserved(src):
    assert transpile(src, validate=False).count("\n") == src.count("\n")


# ---- destructuring errors --------------------------------------------------

def test_destr_empty_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{} = x\n")


def test_destr_non_name_target_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{a: 1} = x\n")


def test_destr_rest_not_last_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{**rest, name} = x\n")


def test_destr_two_rests_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{**a, **b} = x\n")


def test_destr_augmented_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{name} += x\n")


def test_destr_chained_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("a = j{x} = y\n")


def test_destr_keyword_key_error():
    with pytest.raises(PyJSSyntaxError):
        transpile("j{class} = x\n")
