"""
PyJS core: rewrite `j{...}` object literals into plain Python dicts,
and `j{...} = expr` destructuring into individual assignments.

Object literals:

    j{name, age}                  -> {'name': name, 'age': age}
    j{name, active: True}         -> {'name': name, 'active': True}
    j{email: address}             -> {'email': address}
    j{"Content-Type": ct}         -> {"Content-Type": ct}
    j{[key]: value}               -> {key: value}               (computed key)
    j{**defaults, debug: True}    -> {**defaults, 'debug': True}
    j{id: j{name, age}}           -> nested literals work

Destructuring:

    j{name, age} = user           -> name, age = (_t := user)['name'], _t['age']
    j{email: mail} = user         -> mail = (_t := user)['email']
    j{role = "guest"} = user      -> role = (_t := user).get('role', "guest")
    j{address: j{city}} = user    -> city = (_t := user)['address']['city']
    j{name, **rest} = user        -> name, rest = ..., {k: v for ...}

Only braces introduced by the `j` marker are touched. Everything else (sets,
dicts, f-strings, strings, comments) is left exactly as written, and the
output has the same number of lines as the input, so tracebacks line up.
"""
import io
import keyword
import tokenize

__all__ = ["PREFIX", "PyJSSyntaxError", "transpile"]

PREFIX = "j"

IGNORED = {
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.COMMENT,
    tokenize.ENCODING,
}
OPENERS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = set(OPENERS.values())
CONSTANTS = {"True", "False", "None"}
_STMT_STARTERS = {
    tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
}
_AUGMENTED_OPS = {
    "+=", "-=", "*=", "/=", "//=", "%=", "**=", "@=",
    ">>=", "<<=", "&=", "|=", "^=",
}


class PyJSSyntaxError(SyntaxError):
    """Invalid PyJS syntax. Carries the filename, line and column."""


def _line_text(source, row):
    lines = source.split("\n")
    return lines[row - 1] if 0 < row <= len(lines) else ""


def transpile(source, filename="<pyjs>", validate=True):
    """
    Return `source` with every `j{...}` literal rewritten as a Python dict
    and every `j{...} = expr` destructuring rewritten as assignments.

    validate=True compiles the result to make sure it is valid Python. Pass
    False when the caller compiles it anyway (or when the code is only valid
    in a special context, such as a notebook cell with top-level `await`).
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError as error:
        message, (row, col) = error.args
        raise PyJSSyntaxError(
            message, (filename, row, col + 1, _line_text(source, row))
        ) from None

    # ---- source offsets -------------------------------------------------
    offsets = [0]
    for line in io.StringIO(source).readlines():
        offsets.append(offsets[-1] + len(line))

    def start_of(i):
        row, col = tokens[i].start
        return offsets[row - 1] + col

    def end_of(i):
        row, col = tokens[i].end
        return offsets[row - 1] + col

    def fail(i, message):
        row, col = tokens[i].start
        raise PyJSSyntaxError(
            message, (filename, row, col + 1, _line_text(source, row))
        )

    # ---- bracket matching (all kinds, so we can skip over them) ---------
    match = {}
    stack = []
    for i, t in enumerate(tokens):
        if t.type != tokenize.OP:
            continue
        if t.string in OPENERS:
            stack.append(i)
        elif t.string in CLOSERS:
            if not stack:
                fail(i, "Unmatched {!r}".format(t.string))
            j = stack.pop()
            match[j] = i
            match[i] = j
    if stack:
        fail(stack[-1], "Unmatched {!r}".format(tokens[stack[-1]].string))

    # ---- find j{ markers -------------------------------------------------
    def prev_token(i):
        """Previous token, looking past NL and COMMENT tokens."""
        i -= 1
        while i >= 0 and tokens[i].type in (tokenize.NL, tokenize.COMMENT):
            i -= 1
        return i

    def next_significant(i):
        """Next token after i, skipping NL and COMMENT."""
        i += 1
        while i < len(tokens) and tokens[i].type in (tokenize.NL, tokenize.COMMENT):
            i += 1
        return i

    markers = {}  # index of 'j' NAME -> index of '{'
    for i, t in enumerate(tokens):
        if t.type != tokenize.NAME or t.string != PREFIX:
            continue
        if i + 1 >= len(tokens):
            continue
        nxt = tokens[i + 1]
        if nxt.type != tokenize.OP or nxt.string != "{" or nxt.start != t.end:
            continue  # 'j' and '{' must touch
        p = prev_token(i)
        if p >= 0 and tokens[p].type == tokenize.OP and tokens[p].string == ".":
            continue  # `obj.j{...}` is attribute access, not a marker
        markers[i] = i + 1

    if not markers:
        return source

    # ---- helpers over token ranges --------------------------------------
    def top_level(lo, hi):
        """Yield indexes in [lo, hi) that are not inside nested brackets."""
        i = lo
        while i < hi:
            yield i
            t = tokens[i]
            if t.type == tokenize.OP and t.string in OPENERS and i in match:
                i = match[i]
            i += 1

    def trimmed(lo, hi):
        while lo < hi and tokens[lo].type in IGNORED:
            lo += 1
        while hi > lo and tokens[hi - 1].type in IGNORED:
            hi -= 1
        return lo, hi

    def split_commas(lo, hi):
        """Split [lo, hi) on top-level commas, ignoring lambda parameter lists."""
        segments, seg_start, lambdas = [], lo, 0
        for i in top_level(lo, hi):
            t = tokens[i]
            if t.type == tokenize.NAME and t.string == "lambda":
                lambdas += 1
            elif t.type == tokenize.OP and t.string == ":" and lambdas:
                lambdas -= 1
            elif t.type == tokenize.OP and t.string == "," and not lambdas:
                segments.append((seg_start, i))
                seg_start = i + 1
        segments.append((seg_start, hi))
        out = []
        for a, b in segments:
            a, b = trimmed(a, b)
            if a < b:
                out.append((a, b))
        return out

    def find_colon(lo, hi):
        lambdas = 0
        for i in top_level(lo, hi):
            t = tokens[i]
            if t.type == tokenize.NAME and t.string == "lambda":
                lambdas += 1
            elif t.type == tokenize.OP and t.string == ":":
                if lambdas:
                    lambdas -= 1
                else:
                    return i
        return None

    def find_eq(lo, hi):
        """Find a top-level '=' OP in [lo, hi)."""
        for i in top_level(lo, hi):
            t = tokens[i]
            if t.type == tokenize.OP and t.string == "=":
                return i
        return None

    def has_top_level_for(lo, hi):
        return any(
            tokens[i].type == tokenize.NAME and tokens[i].string == "for"
            for i in top_level(lo, hi)
        )

    def find_rhs_end(start):
        """Find NEWLINE, ENDMARKER, or top-level ';' ending the RHS."""
        i = start
        while i < len(tokens):
            t = tokens[i]
            if t.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                return i
            if t.type == tokenize.OP:
                if t.string in OPENERS and i in match:
                    i = match[i] + 1
                    continue
                if t.string == ";":
                    return i
            i += 1
        return len(tokens) - 1

    def expand(i):
        """Rendered text of the literal whose 'j' is token i, and its closing index."""
        close = match[markers[i]]
        rendered = render(markers[i], close)
        # `f"{j{a}}"` must not become `f"{{...}}"`, which means an escaped brace.
        p = prev_token(i)
        if p >= 0 and tokens[p].type == tokenize.OP and tokens[p].string == "{":
            rendered = " " + rendered
        return rendered, close

    def text(lo, hi):
        """Source for tokens [lo, hi) with every nested j{} literal rewritten."""
        lo, hi = trimmed(lo, hi)
        if lo >= hi:
            return ""
        out, cursor, i = [], start_of(lo), lo
        while i < hi:
            if i in markers and i not in destructures:
                rendered, close = expand(i)
                out.append(source[cursor:start_of(i)])
                out.append(rendered)
                cursor = end_of(close)
                i = close + 1
            else:
                i += 1
        out.append(source[cursor:end_of(hi - 1)])
        return "".join(out)

    def render_property(a, b):
        first = tokens[a]

        # Spread: **mapping
        if first.type == tokenize.OP and first.string == "**":
            if a + 1 >= b:
                fail(a, "Expected an expression after '**'")
            return "**" + text(a + 1, b)

        colon = find_colon(a, b)

        if colon is None:
            # Shorthand: a single bare identifier.
            if b - a == 1 and first.type == tokenize.NAME:
                if keyword.iskeyword(first.string):
                    fail(
                        a,
                        "{!r} is a Python keyword, so it can't be used as a "
                        "shorthand property".format(first.string),
                    )
                return "{!r}: {}".format(first.string, first.string)
            fail(a, "Expected 'name', 'key: value' or '**mapping'")

        k_lo, k_hi = trimmed(a, colon)
        v_lo, v_hi = trimmed(colon + 1, b)
        if k_lo >= k_hi:
            fail(colon, "Missing key before ':'")
        if v_lo >= v_hi:
            fail(colon, "Missing value after ':'")

        k_first = tokens[k_lo]
        # Computed key: [expr]: value
        if (
            k_first.type == tokenize.OP
            and k_first.string == "["
            and match.get(k_lo) == k_hi - 1
        ):
            key = text(k_lo + 1, k_hi - 1)
            if not key:
                fail(k_lo, "Empty computed key")
        # Bare identifier key becomes a string, like in JavaScript.
        elif (
            k_hi - k_lo == 1
            and k_first.type == tokenize.NAME
            and k_first.string not in CONSTANTS
        ):
            if keyword.iskeyword(k_first.string):
                fail(
                    k_lo,
                    "{!r} is a Python keyword; write it as a quoted key: "
                    '"{}": ...'.format(k_first.string, k_first.string),
                )
            key = repr(k_first.string)
        # Anything else (strings, numbers, True/None...) is kept verbatim.
        else:
            key = text(k_lo, k_hi)

        return "{}: {}".format(key, text(v_lo, v_hi))

    def render(open_i, close_i):
        """Rewrite one literal, keeping every property on its original line."""
        open_row = tokens[open_i].start[0]
        close_row = tokens[close_i].start[0]
        lo, hi = trimmed(open_i + 1, close_i)
        if lo >= hi:
            return "{" + "\n" * (close_row - open_row) + "}"

        if has_top_level_for(lo, hi):
            fail(
                lo,
                "Comprehensions are not supported inside j{}; "
                "use a regular {k: v for ...} instead",
            )

        out = ["{"]
        newlines = 0

        def emit(chunk):
            nonlocal newlines
            out.append(chunk)
            newlines += chunk.count("\n")

        for n, (a, b) in enumerate(split_commas(lo, hi)):
            if n:
                emit(",")
            gap = tokens[a].start[0] - (open_row + newlines)
            emit("\n" * gap if gap > 0 else (" " if n else ""))
            emit(render_property(a, b))

        emit("\n" * max(0, (close_row - open_row) - newlines) + "}")
        return "".join(out)

    # ---- detect destructuring patterns ----------------------------------
    destructures = {}  # marker j-idx -> (eq_idx, rhs_end_idx)

    for i in sorted(markers):
        close = match[markers[i]]
        nxt = next_significant(close)
        if nxt >= len(tokens):
            continue
        nxt_tok = tokens[nxt]
        if nxt_tok.type != tokenize.OP:
            continue

        p = prev_token(i)
        at_start = (p < 0
                    or tokens[p].type in _STMT_STARTERS
                    or (tokens[p].type == tokenize.OP
                        and tokens[p].string == ";"))

        if nxt_tok.string == "=":
            if at_start:
                destructures[i] = (nxt, find_rhs_end(nxt + 1))
            else:
                fail(i,
                     "j{} destructuring cannot appear in a chained "
                     "assignment; extract into a separate statement")
        elif nxt_tok.string in _AUGMENTED_OPS and at_start:
            fail(i,
                 "j{{}} destructuring does not support augmented "
                 "assignment ({!r})".format(nxt_tok.string))

    # ---- destructuring helpers ------------------------------------------
    def _parse_destr_field(a, b):
        """Parse one field of a destructuring pattern.

        Returns one of:
          ('shorthand', key, target)
          ('default',   key, target, default_text)
          ('rename',    key, target)
          ('nested',    key, sub_fields)
          ('rest',      target)
        """
        first = tokens[a]

        # **rest
        if first.type == tokenize.OP and first.string == "**":
            inner_lo, inner_hi = trimmed(a + 1, b)
            if (inner_lo >= inner_hi
                    or inner_hi - inner_lo != 1
                    or tokens[inner_lo].type != tokenize.NAME):
                fail(a, "Expected a single name after '**'")
            return ("rest", tokens[inner_lo].string)

        # key: target  /  key: j{...}
        colon = find_colon(a, b)
        if colon is not None:
            k_lo, k_hi = trimmed(a, colon)
            v_lo, v_hi = trimmed(colon + 1, b)
            if k_lo >= k_hi:
                fail(colon, "Missing key before ':'")
            if v_lo >= v_hi:
                fail(colon, "Missing target after ':'")
            k_first = tokens[k_lo]
            if (k_hi - k_lo != 1
                    or k_first.type != tokenize.NAME
                    or k_first.string in CONSTANTS):
                fail(k_lo, "Destructuring key must be a bare name")
            if keyword.iskeyword(k_first.string):
                fail(
                    k_lo,
                    "{!r} is a Python keyword; write it as a quoted key: "
                    '"{}": ...'.format(k_first.string, k_first.string),
                )
            key_name = k_first.string

            # Nested j{...}?
            v_first = tokens[v_lo]
            if (v_first.type == tokenize.NAME
                    and v_first.string == PREFIX
                    and v_lo in markers):
                nested_open = markers[v_lo]
                nested_close = match[nested_open]
                rest_lo, rest_hi = trimmed(nested_close + 1, v_hi)
                if rest_lo < rest_hi:
                    fail(rest_lo, "Unexpected tokens after nested pattern")
                sub = _parse_destr_fields(nested_open + 1, nested_close)
                return ("nested", key_name, sub)

            # Plain rename — target must be a single name
            if v_hi - v_lo != 1 or v_first.type != tokenize.NAME:
                fail(v_lo, "Destructuring target must be a name")
            if keyword.iskeyword(v_first.string):
                fail(v_lo,
                     "{!r} is a Python keyword and cannot be used as "
                     "a destructuring target".format(v_first.string))
            return ("rename", key_name, v_first.string)

        # name = default
        eq = find_eq(a, b)
        if eq is not None:
            k_lo, k_hi = trimmed(a, eq)
            d_lo, d_hi = trimmed(eq + 1, b)
            if (k_lo >= k_hi
                    or k_hi - k_lo != 1
                    or tokens[k_lo].type != tokenize.NAME):
                fail(a, "Expected a single name before '='")
            key_name = tokens[k_lo].string
            if keyword.iskeyword(key_name):
                fail(
                    k_lo,
                    "{!r} is a Python keyword, so it can't be used as "
                    "a shorthand property".format(key_name),
                )
            if d_lo >= d_hi:
                fail(eq, "Missing default value after '='")
            return ("default", key_name, key_name, text(d_lo, d_hi))

        # Shorthand: bare name
        if b - a == 1 and first.type == tokenize.NAME:
            if keyword.iskeyword(first.string):
                fail(
                    a,
                    "{!r} is a Python keyword, so it can't be used as "
                    "a shorthand property".format(first.string),
                )
            return ("shorthand", first.string, first.string)

        fail(a, "Expected 'name', 'key: target', 'name = default', "
                "or '**rest'")

    def _parse_destr_fields(lo, hi):
        """Parse all comma-separated fields inside a destructuring j{...}."""
        segments = split_commas(lo, hi)
        fields = []
        rest_count = 0
        for a, b in segments:
            field = _parse_destr_field(a, b)
            if field[0] == "rest":
                rest_count += 1
                if rest_count > 1:
                    fail(a, "Only one '**rest' is allowed in a "
                            "destructuring pattern")
            fields.append((field, a))  # keep token index for errors

        # **rest must be last
        for idx, (field, tok_i) in enumerate(fields):
            if field[0] == "rest" and idx != len(fields) - 1:
                fail(tok_i, "'**rest' must be the last field in a "
                            "destructuring pattern")

        return [f for f, _ in fields]

    def _flatten_destr(fields, path):
        """Flatten nested fields into (target, key_path, default, is_rest, sibling_keys)."""
        sibling_keys = [f[1] for f in fields if f[0] != "rest"]
        results = []
        for f in fields:
            kind = f[0]
            if kind == "rest":
                results.append((f[1], list(path), None, True, list(sibling_keys)))
            elif kind == "nested":
                results.extend(_flatten_destr(f[2], path + [f[1]]))
            elif kind == "default":
                results.append((f[2], path + [f[1]], f[3], False, None))
            else:  # shorthand or rename
                results.append((f[2], path + [f[1]], None, False, None))
        return results

    def _render_destructure(marker_i, eq_idx, rhs_end_idx):
        """Render a destructuring pattern as Python assignment(s).

        Returns (code, cursor_end_position).
        """
        close_brace = match[markers[marker_i]]
        lo, hi = trimmed(markers[marker_i] + 1, close_brace)

        if lo >= hi:
            fail(marker_i, "Destructuring pattern has no targets")

        fields = _parse_destr_fields(lo, hi)
        if not fields:
            fail(marker_i, "Destructuring pattern has no targets")

        flat = _flatten_destr(fields, [])

        # RHS text (nested j{} literals are expanded by text())
        rhs_lo, rhs_hi = trimmed(eq_idx + 1, rhs_end_idx)
        rhs_source = text(rhs_lo, rhs_hi)

        tmp = "_pyjs_tmp"
        targets = []
        exprs = []

        for idx, (target, key_path, default, is_rest, sibling_keys) in enumerate(flat):
            targets.append(target)
            base = "({} := {})".format(tmp, rhs_source) if idx == 0 else tmp

            if is_rest:
                for key in key_path:
                    base += "[{!r}]".format(key)
                if sibling_keys:
                    excluded = ", ".join(repr(k) for k in sibling_keys)
                    expr = (
                        "{_pyjs_k: _pyjs_v for _pyjs_k, _pyjs_v in "
                        + base + ".items() if _pyjs_k not in ("
                        + excluded + ",)}"
                    )
                else:
                    expr = "dict(" + base + ")"
                exprs.append(expr)
            else:
                for ki, key in enumerate(key_path):
                    if ki == len(key_path) - 1 and default is not None:
                        base += ".get({!r}, {})".format(key, default)
                    else:
                        base += "[{!r}]".format(key)
                exprs.append(base)

        if len(targets) == 1:
            code = "{} = {}".format(targets[0], exprs[0])
        else:
            code = "{} = {}".format(", ".join(targets), ", ".join(exprs))

        # Pad newlines so the output spans the same number of lines.
        span_end_tok = rhs_hi - 1 if rhs_lo < rhs_hi else eq_idx
        j_row = tokens[marker_i].start[0]
        end_row = tokens[span_end_tok].end[0]
        needed = end_row - j_row
        code += "\n" * max(0, needed - code.count("\n"))

        return code, end_of(span_end_tok)

    # ---- rewrite every top-level marker ---------------------------------
    out, cursor, i = [], 0, 0
    while i < len(tokens):
        if i in destructures:
            eq_idx, rhs_end_idx = destructures[i]
            code, span_end = _render_destructure(i, eq_idx, rhs_end_idx)
            out.append(source[cursor:start_of(i)])
            out.append(code)
            cursor = span_end
            i = rhs_end_idx
        elif i in markers:
            rendered, close = expand(i)
            out.append(source[cursor:start_of(i)])
            out.append(rendered)
            cursor = end_of(close)
            i = close + 1
        else:
            i += 1
    out.append(source[cursor:])
    result = "".join(out)

    if validate:
        try:
            compile(result, filename, "exec")
        except SyntaxError as error:
            raise PyJSSyntaxError(
                "Generated invalid Python: {}".format(error.msg),
                (filename, error.lineno, error.offset, error.text),
            ) from error
    return result
