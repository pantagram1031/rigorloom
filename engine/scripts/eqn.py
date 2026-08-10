#!/usr/bin/env python3
"""Bounded LaTeX-to-HwpEqn lexical conversion.

The converter implements ``rigorloom/hwpeqn/v1``: a deliberately small,
versioned lexical envelope shared by the COM and XML backends.  Ambiguous
commands, unsupported structures, malformed required operands, controls,
origin-ambiguous native tokens, and conversion warnings are terminal
refusals.  A warning-free result proves only this bounded envelope; it is not
HwpEqn semantic validity, native execution, render/layout, or parity proof.
"""

import re
import sys
import json
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

try:
    from cli_io import utf8_stdio
except ImportError:  # library use from a copied single-file bundle
    utf8_stdio = None


# ``HwpEqn`` is a separate language from LaTeX.  Keep this contract small and
# versioned so every backend can make the same bounded lexical decision before
# touching a document.  This is deliberately not a semantic equation parser.
HWPEQN_CONTRACT = "rigorloom/hwpeqn/v1"
HWPEQN_MAX_BYTES = 16 * 1024
HWPEQN_MAX_DEPTH = 64
LATEX_MAX_BYTES = 32 * 1024
LATEX_MAX_DEPTH = 128
BASE_PT_MAX = 100
BASE_PT_MIN = 1

# ---------------------------------------------------------------------------
# 단순 치환 테이블 (백슬래시 명령 -> HwpEqn 토큰)
# ---------------------------------------------------------------------------

GREEK = [
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta",
    "theta", "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
    "varpi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "varupsilon", "phi",
    "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon",
    "Phi", "Psi", "Omega", "Omicron", "omicron",
]

SIMPLE_MAP = {
    # 연산자/관계
    r"\pm": "+-",
    r"\mp": "-+",
    r"\times": "times",
    r"\div": "div",
    r"\cdot": "cdot",
    r"\le": "leq", r"\leq": "leq",
    r"\ge": "geq", r"\geq": "geq",
    r"\ne": "neq", r"\neq": "neq",
    r"\approx": "approx",
    r"\equiv": "equiv",
    r"\propto": "propto",
    r"\sim": "sim",
    r"\in": "in",
    r"\notin": "notin",
    r"\subset": "subset",
    r"\supset": "supset",
    # ``cup`` and ``nabla`` remain direct-HwpEqn vocabulary but are not
    # converter mappings until a native/source proof is available.
    r"\cap": "cap",
    r"\forall": "forall",
    r"\exists": "exist",
    r"\infty": "inf",
    r"\partial": "partial",
    r"\therefore": "therefore",
    r"\because": "because",
    r"\angle": "angle",
    r"\perp": "bot",
    r"\parallel": "parallel",
    r"\circ": "circ",
    r"\prime": "prime",
    r"\hbar": "hbar",
    r"\ell": "ell",
    r"\emptyset": "emptyset",
    r"\cdots": "cdots",
    r"\ldots": "ldots",
    r"\vdots": "vdots",
    r"\ddots": "ddots",
    # 화살표
    r"\rightarrow": "rarrow", r"\to": "rarrow",
    r"\leftarrow": "larrow", r"\gets": "larrow",
    r"\leftrightarrow": "lrarrow",
    r"\Rightarrow": "RARROW",
    r"\Leftarrow": "LARROW",
    r"\Leftrightarrow": "LRARROW",
    r"\uparrow": "uparrow",
    r"\downarrow": "downarrow",
    # 큰 연산자 (적분/합/극한 등 — 첨자는 _, ^ 그대로 사용 가능)
    r"\int": "int",
    r"\iint": "dint",
    r"\iiint": "tint",
    r"\oint": "oint",
    r"\sum": "sum",
    r"\prod": "prod",
    r"\lim": "lim",
    r"\max": "max",
    r"\min": "min",
    r"\log": "log",
    r"\ln": "ln",
    r"\exp": "exp",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan",
    r"\csc": "csc", r"\sec": "sec", r"\cot": "cot",
    r"\sinh": "sinh", r"\cosh": "cosh", r"\tanh": "tanh",
    r"\arcsin": "arcsin", r"\arccos": "arccos", r"\arctan": "arctan",
    # 천문/기타 기호
    r"\odot": "odot", r"\oplus": "oplus", r"\otimes": "otimes",
    # 공백
    r"\,": "`", r"\;": "``", r"\quad": "~", r"\qquad": "~~",
    r"\!": "",
}

# 장식 (한 인자) : \cmd{X} -> token {X}
ACCENT_MAP = {
    "vec": "vec", "bar": "bar", "hat": "hat", "dot": "dot",
    "ddot": "ddot", "tilde": "tilde", "overline": "bar",
    "underline": "under", "widehat": "hat", "widetilde": "tilde",
}

MATRIX_ENVS = {
    "pmatrix": "pmatrix", "bmatrix": "bmatrix", "vmatrix": "dmatrix",
    "matrix": "matrix", "cases": "cases", "aligned": "eqalign",
    "align": "eqalign", "align*": "eqalign",
}


# ---------------------------------------------------------------------------
# 중괄호 매칭 유틸
# ---------------------------------------------------------------------------

def _read_group(s, i):
    """s[i]가 '{'일 때, 매칭되는 '}'까지의 내용과 다음 인덱스를 반환."""
    assert s[i] == "{"
    depth = 0
    j = i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ValueError(f"중괄호가 닫히지 않음: ...{s[i:i+30]}")


def _read_arg(s, i):
    """\\frac 등의 인자 하나 읽기: {그룹} 또는 단일 토큰."""
    while i < len(s) and s[i] in " \t":
        i += 1
    if i >= len(s):
        # Missing required operands must not silently become an empty group.
        return None, i
    if s[i] == "{":
        try:
            return _read_group(s, i)
        except (ValueError, IndexError):
            return None, len(s)
    if s[i] == "\\":  # \alpha 같은 명령 하나
        m = re.match(r"\\[a-zA-Z]+", s[i:])
        if m:
            return m.group(0), i + m.end()
        return s[i:i + 2], i + 2
    return s[i], i + 1


# LaTeX and HwpEqn share a number of identifier-shaped tokens, but they do
# not share their origin or meaning.  A raw LaTeX word such as ``sin`` or
# ``over`` must therefore not silently enter the HwpEqn lane as if it had
# been emitted by an explicit ``\\sin``/``\\frac`` command.  This is an
# origin check only; direct ``hwpeqn`` callers are validated by
# ``preflight_hwpeqn`` and may use the native tokens.
_LATEX_TEXT_COMMANDS = frozenset(
    ("text", "mathrm", "textrm", "mbox", "operatorname"))
_LATEX_NATIVE_OPERATOR_SURFACES = (
    "<=>", "<->", "+-", "-+", "=>", "->", "<-", "!=", "==", "<=", ">=",
)
# Versioned *origin-refusal* vocabulary.  These are not an acceptance list:
# direct HwpEqn input still goes through the independent lexical preflight.
# Keep official vocabulary and engine-specific aliases separate so future
# converter edits cannot silently broaden this origin boundary.  Membership is
# ASCII case-folded; ordinary variables such as ``mv``, ``dx`` and ``K`` are
# deliberately absent.
# Source register (checked 2026-08-11): Hancom HwpEqn format revision 1.2,
# viewer P9-P13 / printed pp.6-10, plus the current Hancom equation help tables.
# https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_%EC%88%98%EC%8B%9D_revision1.2.pdf
# https://help.hancom.com/hoffice/multi/en_us/hwp/insert/equation/equation%28explanation%29.htm
# This inventory is only an origin-refusal boundary, never an acceptance or
# semantic-coverage claim.
_HWP_EQN_OFFICIAL_TOKENS = frozenset("""
    over root of sqrt atop choose binom left right eqalign matrix pmatrix
    bmatrix dmatrix cases
    pile lpile rpile col lcol rcol bigg BIGG small SMALL
    smallunion smallinter SMALLUNION SMALLINTER
    rm it bold rmbold size color
    vec bar hat dot ddot tilde under
    acute grave check arch dyad
    sin cos tan cot sec csc cosec sinh cosh tanh coth arcsin arccos arctan
    arc log ln lg lb exp lim Lim max min sup inf
    gcd lcm mod det dim deg arg Pr tr ker hom int dint tint oint ODINT OTINT
    sum prod
    in notin subset supset subseteq supseteq union inter cap forall
    exists exist emptyset le leq ge geq lt gt neq ne approx
    approxeq equiv sim simeq propto parallel perp
    not rel buildrel
    rarrow larrow lrarrow RARROW LARROW LRARROW uparrow downarrow
    nearrow searrow swarrow nwarrow to gets
    rightleftarrows leftrightarrows hookleft hookright udarrow UDARROW
    VERT
    pm mp plusminus minusplus times div cdot circ bullet ast star prime
    hbar ell partial del nabla therefore because angle cdots ldots vdots ddots
    COPROD SQCAP SQCUP OMINUS OSLASH VEE WEDGE OWNS
    UPLUS DIVIDE BIGCIRC DOTEQ CONG ASYMP DSUM LNOT
    SQSUBSET SQSUPSET SQSUBSETEQ SQSUPSETEQ SQEQUAL SQNOTEQUAL
    odot oplus otimes
    aleph angstrom att base benzene centigrade dagger ddagger diamond
    fahrenheit hleft hund identical imag image imath iso jmath laplace
    liter lll lslant mho models msangle prec reimage rslant rtangle sangle
    succ thou top triangle triangled varsigma vdash well wp xor
    if for and or
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta
    iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega
    Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu Nu Xi Omicron Pi
    Rho Sigma Tau Upsilon Phi Chi Psi Omega
""".split())

_HWP_EQN_ENGINE_ALIASES = frozenset("""
    frac dfrac tfrac begin end align array
    roman font face text overline underline widehat widetilde varnothing
    relation varrho varupsilon varepsilon vartheta varpi varphi
    hookrightarrow hookleftarrow longrightarrow longleftarrow longleftrightarrow
    bot SUB SUP cpile arcsec arccsc arccot cup equivalent prop mapsto
""".split())

_LATEX_ORIGIN_RESERVED_V1 = frozenset(
    token.casefold()
    for token in (_HWP_EQN_OFFICIAL_TOKENS | _HWP_EQN_ENGINE_ALIASES)
)


def _latex_origin_issue(source):
    """Return a closed warning code for ambiguous raw-LaTeX surfaces.

    The scanner intentionally does not parse LaTeX semantics.  It only
    rejects punctuation that is meaningful in the generated HwpEqn envelope,
    bare native-looking identifiers, and ``&`` outside a supported matrix /
    alignment environment.  Explicit backslash commands are skipped so their
    generated tokens retain a verifiable origin.  Text-command arguments are
    opaque for identifiers but still obey the punctuation boundary.
    """
    env_stack = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if any(source.startswith(surface, i)
               for surface in _LATEX_NATIVE_OPERATOR_SURFACES):
            return "unsupported_punctuation"
        if ch in "%#`\"'~":
            return "unsupported_punctuation"
        if ch == "&":
            if not env_stack or env_stack[-1] not in MATRIX_ENVS:
                return "ampersand_outside_matrix"
            i += 1
            continue
        if ch == "\\":
            # A row separator is a syntax unit, not a command.  Only the
            # canonical two-backslash form is permitted, and only in a
            # supported matrix/alignment body.
            if i + 1 < n and source[i + 1] == "\\":
                j = i + 2
                while j < n and source[j] == "\\":
                    j += 1
                if j - i != 2 or not env_stack or env_stack[-1] not in MATRIX_ENVS:
                    return "conversion_warning"
                i = j
                continue
            match = re.match(r"\\([A-Za-z]+\*?|[,;!])", source[i:])
            if not match:
                # Leave malformed/trailing backslashes for the converter and
                # lexical preflight, which return the closed ``backslash``
                # refusal without exposing source text.
                i += 1
                continue
            command = match.group(1)
            i += match.end()

            # Environment names are structural and must not be mistaken for
            # raw HwpEqn identifiers while we maintain the simple ``&`` gate.
            if command in ("begin", "end"):
                j = i
                while j < n and source[j] in " \t":
                    j += 1
                if j < n and source[j] == "{":
                    try:
                        env_name, end = _read_group(source, j)
                    except (AssertionError, ValueError, IndexError):
                        env_name, end = "", n
                    env_name = env_name.strip()
                    if command == "begin":
                        if env_stack:
                            return "unsupported_environment"
                        env_stack.append(env_name)
                    elif env_stack and env_stack[-1] == env_name:
                        env_stack.pop()
                    i = end
                continue

            # Text-like command arguments are opaque for reserved words, but
            # raw envelope punctuation remains disallowed.  This keeps
            # ``\\text{alpha}`` safe while refusing ``\\text{a&b}`` outside a
            # real matrix body.
            if command in _LATEX_TEXT_COMMANDS:
                j = i
                while j < n and source[j] in " \t":
                    j += 1
                if j < n and source[j] == "{":
                    try:
                        text_arg, end = _read_group(source, j)
                    except (AssertionError, ValueError, IndexError):
                        text_arg, end = "", n
                    # Quotes and HwpEqn envelope markers remain forbidden in
                    # text arguments; apostrophe/tilde are ordinary literal
                    # text and are allowed only because this group is opaque.
                    if any(token in text_arg for token in "%#`\""):
                        return "unsupported_punctuation"
                    if "&" in text_arg and (
                            not env_stack or env_stack[-1] not in MATRIX_ENVS):
                        return "ampersand_outside_matrix"
                    i = end
                continue
            continue
        # Restrict the command/identifier scanner to ASCII.  Non-ASCII
        # letters remain ordinary bounded variable text; ``str.isalpha``
        # would return true for them while the ASCII regex below cannot match,
        # leading to a ``None.group`` crash on otherwise harmless input.
        if ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            match = re.match(r"[A-Za-z]+", source[i:])
            token = match.group(0)
            if token.casefold() in _LATEX_ORIGIN_RESERVED_V1:
                return "reserved_identifier"
            i += len(token)
            continue
        i += 1
    return None


def _latex_max_nesting(source):
    """Return structural brace/bracket nesting, ignoring escaped/text content."""
    depth = 0
    maximum = 0
    i = 0
    while i < len(source):
        if source[i] == "\\":
            match = re.match(r"\\([A-Za-z]+\*?|[,;!])", source[i:])
            if match:
                command = match.group(1)
                i += match.end()
                if command in _LATEX_TEXT_COMMANDS:
                    j = i
                    while j < len(source) and source[j] in " \t":
                        j += 1
                    if j < len(source) and source[j] == "{":
                        try:
                            _text, end = _read_group(source, j)
                        except (AssertionError, ValueError, IndexError):
                            return maximum
                        i = end
                continue
            if i + 1 < len(source) and source[i + 1] in "{}[]":
                i += 2
                continue
        ch = source[i]
        if ch in "{[":
            depth += 1
            maximum = max(maximum, depth)
        elif ch in "}]" and depth:
            depth -= 1
        i += 1
    return maximum


# ---------------------------------------------------------------------------
# 구조 변환 (재귀)
# ---------------------------------------------------------------------------

def _matrix_rowsep(body):
    """Convert exactly two backslashes to the native ``#`` row separator."""
    scanned = _matrix_scan(body)
    if scanned is None:
        return body
    _rows, separators = scanned
    if not separators:
        return body
    out = []
    cursor = 0
    for start, end in separators:
        out.append(body[cursor:start])
        out.append(" # ")
        cursor = end
    out.append(body[cursor:])
    return "".join(out)


def _matrix_scan(body):
    """Scan a matrix body and record only top-level separators/cells.

    Row separators and ampersands below a brace, bracket, or quoted literal
    are rejected rather than interpreted as matrix structure.  This keeps the
    replacement pass tied to the exact positions proven by this scanner.
    """
    rows = []
    cells = []
    separators = []
    cell_start = 0
    brace_depth = 0
    bracket_depth = 0
    quoted = False
    i = 0

    def finish_cell(end):
        cell = body[cell_start:end].strip()
        if not cell:
            return False
        cells.append(cell)
        return True

    while i < len(body):
        ch = body[i]
        if quoted:
            if ch == "\\" and i + 1 < len(body) and body[i + 1] == "\\":
                run_end = i + 2
                while run_end < len(body) and body[run_end] == "\\":
                    run_end += 1
                return None
            if ch == "&":
                return None
            if ch == '"':
                quoted = False
            elif ch == "\\" and i + 1 < len(body):
                i += 2
                continue
            i += 1
            continue

        # Backslash escapes for delimiters are literal characters, not group
        # depth.  A run of backslashes is a candidate row separator.
        if ch == "\\":
            if i + 1 < len(body) and body[i + 1] == "\\":
                run_end = i + 2
                while run_end < len(body) and body[run_end] == "\\":
                    run_end += 1
                run_length = run_end - i
                if brace_depth or bracket_depth or run_length != 2:
                    return None
                if not finish_cell(i):
                    return None
                rows.append(cells)
                cells = []
                separators.append((i, run_end))
                cell_start = run_end
                i = run_end
                continue
            if i + 1 < len(body) and body[i + 1] in "{}[]\\\"":
                i += 2
                continue
            i += 1
            continue

        if ch == '"':
            quoted = True
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return None
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                return None
        elif ch == "&":
            if brace_depth or bracket_depth or not finish_cell(i):
                return None
            cell_start = i + 1
        i += 1

    if quoted or brace_depth or bracket_depth or not finish_cell(len(body)):
        return None
    rows.append(cells)
    return rows, separators


def _matrix_shape_ok(body, env):
    """Require non-empty rectangular rows in the closed matrix subset."""
    scanned = _matrix_scan(body)
    if scanned is None:
        return False
    rows, _separators = scanned
    if not rows or any(not row for row in rows):
        return False
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        return False
    if env == "cases" and widths != {2}:
        return False
    return True


def _convert_structures(s, warnings):
    """\\frac, \\sqrt, \\text, 장식, 행렬 환경 등 인자를 갖는 구조를 변환."""
    out = []
    i = 0
    n = len(s)
    delimiter_stack = []
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue

        m = re.match(r"\\([a-zA-Z]+\*?)", s[i:])
        if not m:
            out.append(s[i:i + 2])
            i += 2
            continue
        cmd = m.group(1)
        j = i + m.end()

        # 직전 출력이 영문자로 끝나면 공백을 넣어 토큰 병합 방지 (m\vec{a} -> m vec{a})
        if out and out[-1] and out[-1][-1].isalnum():
            out.append(" ")

        if cmd in ("frac", "dfrac", "tfrac"):
            try:
                num, j = _read_arg(s, j)
                den, j = _read_arg(s, j)
            except (ValueError, IndexError):
                num = den = None
            if not num or not den:
                warnings.append("missing_required_argument")
                out.append("\\" + cmd)
                i = j if j > i else i + m.end()
                continue
            out.append("{%s} over {%s}" % (
                _convert_structures(num, warnings),
                _convert_structures(den, warnings)))
            i = j
        elif cmd == "sqrt":
            # \sqrt[n]{x} -> root {n} of {x}
            try:
                if j < n and s[j] == "[":
                    k = s.index("]", j)
                    idx = s[j + 1:k]
                    arg, j2 = _read_arg(s, k + 1)
                    if not idx or not arg:
                        raise ValueError("missing sqrt operand")
                    out.append("root {%s} of {%s}" % (
                        _convert_structures(idx, warnings),
                        _convert_structures(arg, warnings)))
                    i = j2
                else:
                    arg, j2 = _read_arg(s, j)
                    if not arg:
                        raise ValueError("missing sqrt operand")
                    out.append("sqrt {%s}" % _convert_structures(arg, warnings))
                    i = j2
            except (ValueError, IndexError):
                warnings.append("missing_required_argument")
                out.append("\\" + cmd)
                i = j if j > i else i + m.end()
        elif cmd in ("text", "mathrm", "textrm", "mbox", "operatorname"):
            arg, j2 = _read_arg(s, j)
            if (not arg or any(ch in arg for ch in ('"', "\\", "\n", "\r"))):
                warnings.append("conversion_warning")
                out.append("\\" + cmd)
                i = j2 if j2 > i else i + m.end()
                continue
            i = j2
            out.append('"%s"' % arg)  # HwpEqn: 큰따옴표 = 리터럴 텍스트
        elif cmd in ACCENT_MAP:
            arg, j2 = _read_arg(s, j)
            if not arg:
                warnings.append("missing_required_argument")
                out.append("\\" + cmd)
                i = j2 if j2 > i else i + m.end()
                continue
            out.append("%s {%s}" % (ACCENT_MAP[cmd],
                                    _convert_structures(arg, warnings)))
            i = j2
        elif cmd == "begin":
            env, j2 = _read_arg(s, j)
            if env is None or not env:
                warnings.append("missing_environment_name")
                out.append("\\begin")
                i = j2 if j2 > i else i + m.end()
                continue
            end_tag = "\\end{%s}" % env
            k = s.find(end_tag, j2)
            if k == -1:
                warnings.append("unterminated_environment")
                out.append(s[i:])
                break
            body = s[j2:k]
            hwp_env = MATRIX_ENVS.get(env)
            if hwp_env is None:
                warnings.append("unsupported_environment")
                out.append(s[i:k + len(end_tag)])
                i = k + len(end_tag)
                continue
            else:
                if not _matrix_shape_ok(body, env):
                    warnings.append("invalid_matrix_shape")
                    out.append(s[i:k + len(end_tag)])
                    i = k + len(end_tag)
                    continue
                body = _convert_structures(_matrix_rowsep(body), warnings)
                out.append("%s{%s}" % (hwp_env, body.strip()))
            i = k + len(end_tag)
        elif cmd in ("left", "right"):
            # \left( -> left (   /  \left\{ -> left {
            delim = ""
            if j < n:
                if s[j] == "\\":
                    # Named/escaped delimiters need a real grammar; do not
                    # consume one character of ``\\langle`` as ``l``.
                    dm = re.match(r"\\([A-Za-z]+|.)", s[j:])
                    if dm and len(dm.group(1)) == 1:
                        delim = dm.group(1)
                        j += dm.end()
                    else:
                        warnings.append("conversion_warning")
                        out.append("\\" + cmd)
                        i = j
                        continue
                else:
                    delim = s[j]
                    j += 1
            if not delim:
                warnings.append("missing_required_argument")
                out.append("\\" + cmd)
                i = n
                continue
            if delim not in "()[]|.":
                warnings.append("conversion_warning")
                out.append("\\" + cmd)
                i = j
                continue
            if cmd == "left":
                delimiter_stack.append(delim)
            else:
                pair = {')': '(', ']': '[', '|': '|'}
                if not delimiter_stack or pair.get(delim) != delimiter_stack[-1]:
                    warnings.append("conversion_warning")
                    out.append("\\" + cmd)
                    i = j
                    continue
                delimiter_stack.pop()
            out.append("%s %s " % (cmd, delim if delim != "." else ""))
            i = j
        else:
            out.append("\\" + cmd)  # 다음 단계(SIMPLE_MAP/그리스)에서 처리
            i = i + m.end()
    if delimiter_stack:
        warnings.append("conversion_warning")
        out.append("\\left")
    return "".join(out)


def _brace_scripts(s):
    """Bare ^x / _x 를 ^{x} / _{x} 로 감싼다.

    HwpEqn의 ^ / _ 는 중괄호가 없으면 '다음 공백까지의 토큰 전체'를 첨자로
    삼는다. 그래서 `x^2)=D(x cdot x)` 같은 식에서 `x^` 뒤에 공백이 없으면
    `2)=D(x` 전체가 위첨자로 올라가 렌더가 깨진다(실측: 미적분 곱법칙 보고서
    p4 `D(x^2)=...`). 다음 단일 원자(문자/숫자, \\command, 또는 이미 있는
    {그룹})만 첨자가 되도록 명시적으로 감싼다. LaTeX 의미(`x^2`=x², `x^ab`=x²b)와
    동일하므로 무손실이고, 이미 `x^{k-1}`처럼 감싼 것은 그대로 둔다.
    """
    out = []
    i, n = 0, len(s)
    in_quote = False
    while i < n:
        c = s[i]
        out.append(c)
        if c == '"':
            in_quote = not in_quote
            i += 1
            continue
        if in_quote:
            i += 1
            continue
        if c in "^_":
            j = i + 1
            while j < n and s[j] == " ":  # ^ 와 인자 사이 공백 흡수
                j += 1
            if j >= n or s[j] == "{":       # 끝 또는 이미 {그룹} → 그대로
                i += 1
                continue
            if s[j] == "\\":                # \command 원자
                m = re.match(r"\\([a-zA-Z]+\*?|.)", s[j:])
                if not m:
                    out.append("\\")
                    i = j + 1
                    continue
                atom = m.group(0)
                out.append("{" + atom + "}")
                i = j + len(atom)
                continue
            out.append("{" + s[j] + "}")    # 단일 문자 원자
            i = j + 1
            continue
        i += 1
    return "".join(out)


_LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z]+|[,;!])")


def _replace_known_commands(s):
    """Replace only complete LaTeX command tokens."""
    greek = set(GREEK)
    simple = {key[1:]: value for key, value in SIMPLE_MAP.items()}

    def replace(match):
        command = match.group(1)
        token = "\\" + command
        if command in greek:
            return " %s " % command
        if command in simple:
            value = simple[command]
            return " %s " % value if value else ""
        return token

    parts = re.split('(\")', s)
    in_quote = False
    for index, part in enumerate(parts):
        if part == '"':
            in_quote = not in_quote
        elif not in_quote:
            parts[index] = _LATEX_COMMAND_RE.sub(replace, part)
    return "".join(parts)


def _normalize_script_spacing(s):
    """Normalize structural spacing without rewriting quoted literals."""
    parts = re.split('(\")', s)
    in_quote = False
    for index, part in enumerate(parts):
        if part == '"':
            in_quote = not in_quote
        elif not in_quote:
            part = re.sub(r"[ \t]+", " ", part)
            part = re.sub(r"\s*([{}^_])\s*", r"\1", part)
            parts[index] = re.sub(r"{ ", "{", part)
    return "".join(parts).strip()


def latex_to_hwpeqn(latex):
    """LaTeX 수식 문자열을 HwpEqn 스크립트로 변환.

    Returns:
        (script, warnings) 튜플.
    """
    warnings = []
    if not isinstance(latex, str):
        return "", ["invalid_input"]
    try:
        if len(latex.encode("utf-8")) > LATEX_MAX_BYTES:
            return "", ["too_large"]
    except UnicodeEncodeError:
        return "", ["encoding"]
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in latex):
        return "", ["control_character"]
    if _latex_max_nesting(latex) > LATEX_MAX_DEPTH:
        return "", ["too_deep"]
    origin_issue = _latex_origin_issue(latex)
    if origin_issue:
        return latex, [origin_issue]
    s = latex.strip()
    if "$" in s:
        if (len(s) >= 2 and s.startswith("$") and s.endswith("$")
                and not s.startswith("$$") and not s.endswith("$$")
                and "$" not in s[1:-1]):
            s = s[1:-1].strip()
        else:
            warnings.append("invalid_delimiter")
            return s, warnings
    s = s.strip("$")  # $...$ 허용

    # 1) 구조(인자 있는 명령) 변환
    try:
        s = _convert_structures(s, warnings)
    except RecursionError:
        return "", ["too_deep"]

    # 1.5) bare ^x/_x 를 ^{x}/_{x} 로 감싸 HwpEqn 첨자 과잉 스코프 방지
    s = _brace_scripts(s)

    # 2) 그리스 문자 (백슬래시 제거)
    s = _replace_known_commands(s)

    # 3) 단순 치환 (긴 명령 먼저)
    # Exact command replacement was performed above; do not use substring
    # replacement here, or prefixes such as ``\\pmfoo`` would be accepted.

    # 4) 남은 백슬래시 명령 -> 경고 후 백슬래시 제거
    leftover = sorted(set(re.findall(r"\\[a-zA-Z]+", s)))
    for _cmd in leftover:
        cmd = _cmd
        warnings.append("unknown_command")
        warnings.append(f"미지원 명령 통과: {cmd}")
        # Keep the unresolved command so the terminal preflight rejects it.

    # 5) 공백 정리 (백틱 ` 은 수식 공백이므로 유지)
    s = _normalize_script_spacing(s)
    _quoted = []
    def _hold_quote(match):
        _quoted.append(match.group(0))
        return "\x01Q%d\x02" % (len(_quoted) - 1)
    s = re.sub(r'"[^"]*"', _hold_quote, s)
    s = re.sub(r"\s*([{}^_])\s*", r"\1", s)  # 구조 문자 주변 압축
    s = re.sub(r"{ ", "{", s).strip()
    for _index, _quote in enumerate(_quoted):
        s = s.replace("\x01Q%d\x02" % _index, _quote)

    closed_warnings = []
    known_warning_codes = {
        "invalid_input", "invalid_delimiter", "missing_required_argument",
        "missing_environment_name", "unterminated_environment",
        "unsupported_environment", "unknown_command", "too_large", "encoding",
        "too_deep", "conversion_warning", "control_character",
        "reserved_identifier", "unsupported_punctuation",
        "ampersand_outside_matrix", "invalid_matrix_shape",
    }
    for warning in warnings:
        code = warning if warning in known_warning_codes else "conversion_warning"
        if code not in closed_warnings:
            closed_warnings.append(code)
    return s, closed_warnings


def resolve_equation_input(op):
    """Resolve an operation's ``latex``/``hwpeqn`` XOR contract.

    Returns ``(script, warnings, ok, reason)``.  The resolver is shared by
    COM-free XML and COM callers so neither backend accepts a different input
    surface.  It never places caller text in ``reason``.
    """
    if not isinstance(op, dict):
        return None, [], False, "source_count"
    has_hwpeqn = op.get("hwpeqn") is not None
    has_latex = op.get("latex") is not None
    if has_hwpeqn == has_latex:
        return None, [], False, "source_count"
    if has_hwpeqn:
        script, warnings = op.get("hwpeqn"), []
    else:
        script, warnings = latex_to_hwpeqn(op.get("latex"))
    if warnings:
        return script, warnings, False, "conversion_warning"
    ok, reason = preflight_hwpeqn(script)
    return script, warnings, ok, reason


def preflight_hwpeqn(script):
    """Return a closed, privacy-safe lexical decision for HwpEqn v1.

    This intentionally does not claim semantic equation validity.  It only
    protects the backends from malformed/LaTeX-bearing input and unbounded
    envelopes.  Reason codes never contain caller-provided text.
    """
    if not isinstance(script, str) or isinstance(script, bool):
        return False, "type"
    if not script.strip():
        return False, "empty"
    try:
        if len(script.encode("utf-8")) > HWPEQN_MAX_BYTES:
            return False, "too_large"
    except UnicodeEncodeError:
        return False, "encoding"

    stack = []
    in_quote = False
    quote_chars = []
    pending_script = False
    for char in script:
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            return False, "control_character"
        if char == "\\":
            return False, "backslash"
        if char == '"':
            if not in_quote and stack:
                stack[-1][1] = True
            if in_quote and not quote_chars:
                return False, "empty_literal"
            in_quote = not in_quote
            if not in_quote:
                if not "".join(quote_chars).strip():
                    return False, "empty_literal"
                quote_chars = []
            continue
        if in_quote:
            quote_chars.append(char)
            continue
        if pending_script:
            if char.isspace():
                continue
            if char in "^_}]":
                return False, "orphan_script"
            pending_script = False
        if char in "{[":
            if stack:
                stack[-1][1] = True
            stack.append([char, False])
            if len(stack) > HWPEQN_MAX_DEPTH:
                return False, "depth"
        elif char in "}]":
            expected = "{" if char == "}" else "["
            if not stack or stack[-1][0] != expected:
                return False, "unmatched_bracket"
            _opened, has_content = stack.pop()
            if not has_content:
                return False, "empty_group"
            if stack:
                stack[-1][1] = True
        elif char in "^_":
            pending_script = True
        elif stack and not char.isspace():
            stack[-1][1] = True

    if in_quote:
        return False, "unmatched_quote"
    if pending_script:
        return False, "orphan_script"
    if stack:
        return False, "unmatched_bracket"
    if script.strip() == "over":
        return False, "orphan_operator"
    return True, "ok"


_BASE_PT_UNSET = object()


def base_pt_to_hwpunit(value=_BASE_PT_UNSET, default=10):
    """Convert an equation point size to one shared HwpUnit integer.

    The COM and XML backends must not choose different float rounding.  The
    v1 policy accepts Hancom's 0.1-point quantum in the conservative product
    range [1, 100] pt, then emits exact 1/100-point HwpUnits.  ``Decimal(str
    (value))`` avoids binary-float half-way drift, while the integer path
    avoids converting very large integers to float before range checking.
    """
    if value is _BASE_PT_UNSET:
        value = default
    elif value is None:
        raise ValueError("base_pt")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("base_pt")
    if isinstance(value, int):
        if value < BASE_PT_MIN or value > BASE_PT_MAX:
            raise ValueError("base_pt")
        units = value * 100
    else:
        if (not math.isfinite(value) or value < BASE_PT_MIN
                or value > BASE_PT_MAX):
            raise ValueError("base_pt")
        try:
            decimal_value = Decimal(str(value))
            tenths = decimal_value * Decimal("10")
            if tenths != tenths.quantize(Decimal("1"), rounding=ROUND_HALF_UP):
                raise ValueError("base_pt")
            units = int((decimal_value * Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError, OverflowError):
            raise ValueError("base_pt") from None
    if units < 1:
        raise ValueError("base_pt")
    return units


def count_hweqn_identifier(script, identifier):
    """Count one native ASCII identifier outside quoted HwpEqn literals."""
    if not isinstance(script, str) or not isinstance(identifier, str):
        return 0
    pattern = re.compile(
        r"(?<![A-Za-z])" + re.escape(identifier) + r"(?![A-Za-z])",
        re.IGNORECASE)
    count = 0
    in_quote = False
    for part in re.split('(\")', script):
        if part == '"':
            in_quote = not in_quote
        elif not in_quote:
            count += len(pattern.findall(part))
    return count


def validate_equation_operation(op):
    """Validate equation operation envelope before backend/document work."""
    if not isinstance(op, dict):
        return None, [], False, "operation_type"
    operation = op.get("op")
    allowed_keys = {
        "insert_equation": frozenset(
            ("op", "latex", "hwpeqn", "display", "base_pt", "font")),
        "edit_equation": frozenset(
            ("op", "latex", "hwpeqn", "index")),
    }.get(operation)
    if allowed_keys is None:
        return None, [], False, "operation"
    if any(key not in allowed_keys for key in op):
        return None, [], False, "unknown_key"
    script, warnings, ok, reason = resolve_equation_input(op)
    if not ok:
        return script, warnings, False, reason
    if "display" in op and type(op["display"]) is not bool:
        return script, warnings, False, "display_type"
    if "font" in op and op["font"] not in (None, "HancomEQN"):
        return script, warnings, False, "font"
    if "base_pt" in op:
        try:
            base_pt_to_hwpunit(op["base_pt"])
        except ValueError:
            return script, warnings, False, "base_pt"
    if op.get("op") == "edit_equation":
        index = op.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            return script, warnings, False, "index"
    return script, warnings, True, "ok"


# Keep the historical API name used by existing callers while making every
# backend share the new bounded implementation above.
hwpeqn_sanity_check = preflight_hwpeqn


if __name__ == "__main__":
    if utf8_stdio is not None:
        utf8_stdio()
    if len(sys.argv) != 2:
        print(json.dumps({"ok": False, "contract": HWPEQN_CONTRACT,
                          "error": "usage"}, ensure_ascii=False))
        sys.exit(2)
    script, warns = latex_to_hwpeqn(sys.argv[1])
    ok, msg = hwpeqn_sanity_check(script)
    if warns or not ok:
        print(json.dumps({"ok": False, "contract": HWPEQN_CONTRACT,
                          "warnings": warns, "sanity": msg},
                         ensure_ascii=False, indent=2))
        sys.exit(3)
    print(json.dumps({"ok": True, "contract": HWPEQN_CONTRACT,
                      "hwpeqn": script, "warnings": [], "sanity": msg},
                     ensure_ascii=False, indent=2))
    sys.exit(0)
