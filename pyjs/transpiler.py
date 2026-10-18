"""
PyJS core: rewrite `@{...}` object literals into plain Python dicts.

    @{name, age}                  -> {'name': name, 'age': age}
    @{name, active: True}         -> {'name': name, 'active': True}
    @{email: address}             -> {'email': address}
    @{"Content-Type": ct}         -> {"Content-Type": ct}
    @{[key]: value}               -> {key: value}               (computed key)
    @{**defaults, debug: True}    -> {**defaults, 'debug': True}
    @{id: @{name, age}}           -> nested literals work

Only braces introduced by the `@` marker are touched. Everything else (sets,
dicts, f-strings, strings, comments) is left exactly as written, and the
output has the same number of lines as the input, so tracebacks line up.
"""
import io
import keyword
import tokenize

__all__ = ["PyJSSyntaxError", "transpile"]

FSTRING_END = getattr(tokenize, "FSTRING_END", None)

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


class PyJSSyntaxError(SyntaxError):
    """Invalid PyJS syntax. Carries the filename, line and column."""


def _line_text(source, row):
    lines = source.split("\n")
    return lines[row - 1] if 0 < row <= len(lines) else ""


def transpile(source, filename="<pyjs>", validate=True):
    """
    Return `source` with every `@{...}` literal rewritten as a Python dict.

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

    # ---- find @{ markers ------------------------------------------------
    def prev_token(i):
        """Previous token, looking past line continuations inside brackets."""
        i -= 1
        while i >= 0 and tokens[i].type in (tokenize.NL, tokenize.COMMENT):
            i -= 1
        return i

    def is_operand_end(i):
        """True if token i ends an operand, which makes a following '@' matmul."""
        t = tokens[i]
        if t.type in (tokenize.NUMBER, tokenize.STRING):
            return True
        if FSTRING_END is not None and t.type == FSTRING_END:
            return True
        if t.type == tokenize.NAME:
            return not keyword.iskeyword(t.string) or t.string in CONSTANTS
        return t.type == tokenize.OP and t.string in CLOSERS

    # Literal text inside f-strings is FSTRING_MIDDLE, never an OP token, so a
    # literal "@{" in an f-string is not matched. Only real expression parts are.
    markers = {}  # index of '@' -> index of '{'
    for i, t in enumerate(tokens):
        if t.type != tokenize.OP or t.string != "@":
            continue
        if i + 1 >= len(tokens):
            continue
        nxt = tokens[i + 1]
        if nxt.type != tokenize.OP or nxt.string != "{" or nxt.start != t.end:
            continue  # '@' and '{' must touch
        p = prev_token(i)
        if p >= 0 and is_operand_end(p):
            continue  # `a @{b}` is plain matrix multiplication
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

    def has_top_level_for(lo, hi):
        return any(
            tokens[i].type == tokenize.NAME and tokens[i].string == "for"
            for i in top_level(lo, hi)
        )

    def expand(i):
        """Rendered text of the literal whose '@' is token i, and its closing index."""
        close = match[markers[i]]
        rendered = render(markers[i], close)
        # `f"{@{a}}"` must not become `f"{{...}}"`, which means an escaped brace.
        p = prev_token(i)
        if p >= 0 and tokens[p].type == tokenize.OP and tokens[p].string == "{":
            rendered = " " + rendered
        return rendered, close

    def text(lo, hi):
        """Source for tokens [lo, hi) with every nested @{} literal rewritten."""
        lo, hi = trimmed(lo, hi)
        if lo >= hi:
            return ""
        out, cursor, i = [], start_of(lo), lo
        while i < hi:
            if i in markers:
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
                "Comprehensions are not supported inside @{}; "
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

    # ---- rewrite every top-level marker ---------------------------------
    out, cursor, i = [], 0, 0
    while i < len(tokens):
        if i in markers:
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
