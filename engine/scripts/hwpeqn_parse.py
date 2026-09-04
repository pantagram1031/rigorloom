#!/usr/bin/env python3
"""hwpeqn_parse.py — HwpEqn script -> layout tree.

WHAT THIS IS, AND WHICH DIRECTION IT RUNS
    ``engine/scripts/eqn.py`` converts LaTeX *into* HwpEqn so a document can
    be authored.  This module runs the other way: it reads the HwpEqn script
    a ``<hp:equation>`` already carries in its ``<hp:script>`` child and
    builds the tree a renderer needs to draw the equation instead of boxing
    it.  Nothing here measures or draws — every node is metric-free, so the
    grammar can be tested without Pillow and the font work stays in
    ``own_render.py`` where the rest of the face machinery lives.

WHAT THE GRAMMAR IS TAKEN FROM
    The token vocabulary is ``eqn.py``'s ``_HWP_EQN_OFFICIAL_TOKENS`` /
    ``_HWP_EQN_ENGINE_ALIASES`` — the same closed list the authoring lane
    already refuses to step outside of — plus the surface forms that a
    Hancom-written ``hp:script`` actually uses: ``{..}over{..}``, ``_{..}``,
    ``^{..}``, ``sqrt{..}``, ``root{n}of{x}``, ``left ( .. right )``,
    ``"literal"``, and the backtick / tilde spacing atoms.

ONE READING HAD TO BE CHOSEN, AND IT IS DECLARED
    ``over`` is an infix operator whose numerator is the **immediately
    preceding primary**, not the whole preceding expression.  KS X 6101 does
    not publish HwpEqn's grammar and the two readings differ on unbraced
    input (``a+b over c``).  The preceding-primary reading is the one that
    renders every equation of the measured report correctly, because Hancom's
    own editor always emits ``{numerator}over{denominator}`` — where the two
    readings agree.  Callers get the reading named in the sidecar rather than
    a silent choice.

UNSUPPORTED IS NAMED, NEVER GUESSED
    A construct this module has no node for becomes a ``Raw`` node carrying
    its own token text, and its name is counted in the ``unsupported`` map the
    parser returns.  The renderer draws the raw text and declares the
    construct in ``elements_skipped``.  Nothing is dropped silently.
"""

from __future__ import annotations

import re

PARSER_VERSION = "hwpeqn-parse/0.1.0"

OVER_BINDING = (
    "over/atop take the immediately preceding primary as numerator, not the "
    "whole preceding expression; the two readings agree on the "
    "{numerator}over{denominator} form Hancom's editor emits"
)

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "varupsilon": "υ", "phi": "φ",
    "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Epsilon": "Ε",
    "Zeta": "Ζ", "Eta": "Η", "Theta": "Θ", "Iota": "Ι",
    "Kappa": "Κ", "Lambda": "Λ", "Mu": "Μ", "Nu": "Ν",
    "Xi": "Ξ", "Omicron": "Ο", "Pi": "Π", "Rho": "Ρ",
    "Sigma": "Σ", "Tau": "Τ", "Upsilon": "Υ", "Phi": "Φ",
    "Chi": "Χ", "Psi": "Ψ", "Omega": "Ω",
}

# HwpEqn name -> the character HWP draws for it.
SYMBOLS = {
    "pm": "±", "plusminus": "±", "mp": "∓",
    "minusplus": "∓", "times": "×", "div": "÷",
    "divide": "÷", "cdot": "⋅", "circ": "∘",
    "bullet": "∙", "ast": "*", "star": "⋆", "prime": "′",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "lt": "<", "gt": ">", "ne": "≠", "neq": "≠",
    "approx": "≈", "approxeq": "≈", "equiv": "≡",
    "identical": "≡", "sim": "∼", "simeq": "≃",
    "propto": "∝", "prop": "∝", "parallel": "∥",
    "perp": "⊥", "bot": "⊥", "top": "⊤",
    "in": "∈", "notin": "∉", "owns": "∋",
    "subset": "⊂", "supset": "⊃", "subseteq": "⊆",
    "supseteq": "⊇", "union": "∪", "cup": "∪",
    "inter": "∩", "cap": "∩", "emptyset": "∅",
    "varnothing": "∅", "forall": "∀", "exists": "∃",
    "exist": "∃", "partial": "∂", "del": "∇",
    "nabla": "∇", "inf": "∞", "infty": "∞",
    "hbar": "ℏ", "ell": "ℓ", "imath": "ı", "aleph": "ℵ",
    "angle": "∠", "therefore": "∴", "because": "∵",
    "cdots": "⋯", "ldots": "…", "vdots": "⋮",
    "ddots": "⋱", "dagger": "†", "ddagger": "‡",
    "diamond": "⋄", "triangle": "△", "odot": "⊙",
    "oplus": "⊕", "otimes": "⊗", "ominus": "⊖",
    "oslash": "⊘", "vee": "∨", "wedge": "∧",
    "lnot": "¬", "not": "¬", "cong": "≅", "asymp": "≍",
    "doteq": "≐", "prec": "≺", "succ": "≻",
    "models": "⊨", "vdash": "⊢", "xor": "⊕",
    "rarrow": "→", "to": "→", "larrow": "←",
    "gets": "←", "lrarrow": "↔", "RARROW": "⇒",
    "LARROW": "⇐", "LRARROW": "⇔", "uparrow": "↑",
    "downarrow": "↓", "udarrow": "↕", "UDARROW": "⇕",
    "nearrow": "↗", "searrow": "↘", "swarrow": "↙",
    "nwarrow": "↖", "mapsto": "↦",
    "longrightarrow": "⟶", "longleftarrow": "⟵",
    "longleftrightarrow": "⟷",
    "hookrightarrow": "↪", "hookleftarrow": "↩",
    "hookright": "↪", "hookleft": "↩",
    "angstrom": "Å", "centigrade": "℃", "fahrenheit": "℉",
    "liter": "ℓ", "mho": "℧", "wp": "℘", "imag": "ℑ",
    "image": "ℑ", "reimage": "ℜ", "real": "ℜ",
    "VERT": "|", "equivalent": "≡",
}

# Names HWP sets upright, as a word, on the equation face.
FUNCTIONS = frozenset("""
    sin cos tan cot sec csc cosec sinh cosh tanh coth arcsin arccos arctan
    arcsec arccsc arccot arc log ln lg lb exp gcd lcm mod det dim deg arg
    Pr tr ker hom if for and or
""".split())

# Names that carry limits.  ``over`` on the operator itself is not a thing;
# ``_``/``^`` after one of these is a limit, and where the limit is drawn is
# the only decision here — see LIMITS_BELOW.
BIG_OPERATORS = {
    "sum": "∑", "prod": "∏", "coprod": "∐",
    "COPROD": "∐", "int": "∫", "dint": "∬",
    "tint": "∭", "oint": "∮", "ODINT": "∯",
    "OTINT": "∰", "smallunion": "∪", "smallinter": "∩",
    "SMALLUNION": "⋃", "SMALLINTER": "⋂",
    "DSUM": "⊕", "SQCAP": "⊓", "SQCUP": "⊔",
    "VEE": "⋁", "WEDGE": "⋀", "BIGCIRC": "◯",
    "UPLUS": "⊎",
}

# Word-shaped operators that also take limits.
LIMIT_WORDS = frozenset("lim Lim max min sup inf lim_sup lim_inf".split())

# Which of the above stack their limits above/below rather than setting them
# as ordinary sub/superscripts.  Measured, not assumed: on the Hancom-rendered
# report used as ground truth, ``sum_{x}`` puts x under the sigma while
# ``int_{e}``, ``min_{s,m}`` and ``max_{q}`` all set their limit to the RIGHT
# of the operator.  So the split is "symbol operators stack, integrals and the
# word-shaped operators do not", and it is this renderer's reading of one
# reference render rather than a published rule.
LIMITS_BELOW = frozenset(BIG_OPERATORS) - {"int", "dint", "tint", "oint",
                                           "ODINT", "OTINT"}

# Accents carry their HwpEqn *name*, not a codepoint: a combining mark drawn
# through Pillow's BASIC layout engine does not compose onto the glyph before
# it (BASIC is pinned for determinism, see own_render's FontBook), so the
# renderer draws a spacing glyph — or, where no spacing glyph reads right, a
# rule it strokes itself.  ``None`` means "stroke a rule".
ACCENT_GLYPH = {
    "bar": None, "overline": None,
    "hat": "ˆ", "widehat": "ˆ",
    "tilde": "˜", "widetilde": "˜",
    "vec": "→", "dot": "˙", "ddot": "¨",
    "acute": "´", "grave": "`", "check": "ˇ",
    "arch": "⌒",
}
ACCENTS = frozenset(ACCENT_GLYPH)
UNDER_ACCENTS = frozenset({"under", "underline"})

GRIDS = {
    "matrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
    "dmatrix": ("|", "|"), "cases": ("{", ""), "eqalign": ("", ""),
    "pile": ("", ""), "lpile": ("", ""), "rpile": ("", ""),
    "cpile": ("", ""),
}
GRID_ALIGN = {"matrix": "c", "pmatrix": "c", "bmatrix": "c", "dmatrix": "c",
              "cases": "l", "eqalign": "c", "pile": "c", "lpile": "l",
              "rpile": "r", "cpile": "c"}

STYLE_WORDS = {"rm": "upright", "it": "italic", "bold": "bold",
               "rmbold": "bold", "roman": "upright", "font": "upright",
               "face": "upright", "text": "upright"}

DELIMITERS = frozenset("()[]{}|.<>")

# Spacing atoms, in em of the base size.  HwpEqn's ``~`` is a full space and
# ``` ` ``` a half one; the em fractions are this renderer's calibration of
# "a space" on a maths face and are declared, not read from the standard.
SPACE_EM = {"~": 0.32, "`": 0.16}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

class Node:
    kind = "node"
    __slots__ = ()

    def children(self):
        return ()


class Row(Node):
    kind = "row"
    __slots__ = ("items",)

    def __init__(self, items):
        self.items = list(items)

    def children(self):
        return tuple(self.items)


class Atom(Node):
    """One drawn token.  ``style`` decides the face, never the geometry."""
    kind = "atom"
    __slots__ = ("text", "style", "limits")

    def __init__(self, text, style="var", limits=False):
        self.text = text
        self.style = style
        self.limits = limits


class Space(Node):
    kind = "space"
    __slots__ = ("em",)

    def __init__(self, em):
        self.em = em


class Frac(Node):
    kind = "frac"
    __slots__ = ("num", "den", "rule")

    def __init__(self, num, den, rule=True):
        self.num = num
        self.den = den
        self.rule = rule

    def children(self):
        return (self.num, self.den)


class Script(Node):
    kind = "script"
    __slots__ = ("base", "sub", "sup", "limits")

    def __init__(self, base, sub=None, sup=None, limits=False):
        self.base = base
        self.sub = sub
        self.sup = sup
        self.limits = limits

    def children(self):
        return tuple(c for c in (self.base, self.sub, self.sup) if c)


class Radical(Node):
    kind = "radical"
    __slots__ = ("radicand", "index")

    def __init__(self, radicand, index=None):
        self.radicand = radicand
        self.index = index

    def children(self):
        return tuple(c for c in (self.radicand, self.index) if c)


class Fence(Node):
    kind = "fence"
    __slots__ = ("left", "right", "body")

    def __init__(self, left, right, body):
        self.left = left
        self.right = right
        self.body = body

    def children(self):
        return (self.body,)


class Accent(Node):
    kind = "accent"
    __slots__ = ("mark", "base", "below")

    def __init__(self, mark, base, below=False):
        self.mark = mark
        self.base = base
        self.below = below

    def children(self):
        return (self.base,)


class Grid(Node):
    kind = "grid"
    __slots__ = ("rows", "left", "right", "align")

    def __init__(self, rows, left="", right="", align="c"):
        self.rows = rows          # list[list[Node]]
        self.left = left
        self.right = right
        self.align = align

    def children(self):
        return tuple(cell for row in self.rows for cell in row)


class Styled(Node):
    kind = "styled"
    __slots__ = ("style", "base")

    def __init__(self, style, base):
        self.style = style
        self.base = base

    def children(self):
        return (self.base,)


class Raw(Node):
    """A construct with no node here.  Its own token text is what gets drawn."""
    kind = "raw"
    __slots__ = ("text", "construct")

    def __init__(self, text, construct):
        self.text = text
        self.construct = construct


# --------------------------------------------------------------------------
# Tokeniser
# --------------------------------------------------------------------------

def tokenize(script):
    """``(kind, text)`` pairs.  Kinds: word, num, str, op, brace, script,
    space, sep, end.  Whitespace separates and is otherwise dropped; HwpEqn's
    own spacing atoms (`` ` `` and ``~``) are tokens, because they are ink
    positions, not formatting noise."""
    out = []
    i, n = 0, len(script)
    while i < n:
        c = script[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = script.find('"', i + 1)
            if j == -1:
                out.append(("str", script[i + 1:]))
                break
            out.append(("str", script[i + 1:j]))
            i = j + 1
            continue
        if c in "{}":
            out.append(("brace", c))
            i += 1
            continue
        if c in "_^":
            out.append(("script", c))
            i += 1
            continue
        if c in "&#":
            out.append(("sep", c))
            i += 1
            continue
        if c in SPACE_EM:
            out.append(("space", c))
            i += 1
            continue
        m = _WORD_RE.match(script, i)
        if m:
            out.append(("word", m.group(0)))
            i = m.end()
            continue
        m = _NUM_RE.match(script, i)
        if m:
            out.append(("num", m.group(0)))
            i = m.end()
            continue
        out.append(("op", c))
        i += 1
    return out


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

_OP_GLYPHS = {"-": "−", "*": "∗"}


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.unsupported = {}
        self.constructs = {}

    # -- bookkeeping --
    def _note(self, name):
        self.constructs[name] = self.constructs.get(name, 0) + 1

    def _unsupported(self, name):
        self.unsupported[name] = self.unsupported.get(name, 0) + 1

    # -- token access --
    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else ("end", "")

    def next(self):
        tok = self.peek()
        if tok[0] != "end":
            self.i += 1
        return tok

    # -- grammar --
    def parse(self):
        row = self.expression(stop_words=())
        return row

    def expression(self, stop_words=()):
        items = []
        while True:
            kind, text = self.peek()
            if kind == "end":
                break
            if kind == "brace" and text == "}":
                break
            if kind == "sep":
                break
            if kind == "word" and text in stop_words:
                break
            if kind == "word" and text in ("over", "atop"):
                self.next()
                self._note(text)
                num = self._pop_primary(items)
                den = self.primary()
                items.append(Frac(num, den, rule=(text == "over")))
                continue
            if kind == "script":
                self.next()
                self._note("superscript" if text == "^" else "subscript")
                target = self._pop_primary(items)
                arg = self.primary()
                items.append(self._attach_script(target, text, arg))
                continue
            items.append(self.primary())
        return Row(items)

    def _pop_primary(self, items):
        if not items:
            return Row([])
        return items.pop()

    def _attach_script(self, target, which, arg):
        limits = isinstance(target, Atom) and target.limits
        if isinstance(target, Script):
            if which == "_" and target.sub is None:
                target.sub = arg
                return target
            if which == "^" and target.sup is None:
                target.sup = arg
                return target
        if which == "_":
            return Script(target, sub=arg, limits=limits)
        return Script(target, sup=arg, limits=limits)

    def primary(self):
        kind, text = self.next()
        if kind == "end":
            return Row([])
        if kind == "brace":
            if text == "{":
                inner = self.expression()
                closing = self.peek()
                if closing[0] == "brace" and closing[1] == "}":
                    self.next()
                return inner
            return Row([])
        if kind == "sep":
            return Row([])
        if kind == "space":
            return Space(SPACE_EM[text])
        if kind == "str":
            self._note("literal")
            return Atom(text, "text")
        if kind == "num":
            return Atom(text, "num")
        if kind == "op":
            return Atom(_OP_GLYPHS.get(text, text), "op")
        return self.word(text)

    def word(self, text):
        if text == "sqrt":
            self._note("sqrt")
            return Radical(self.primary())
        if text == "root":
            self._note("root")
            index = self.primary()
            nxt = self.peek()
            if nxt[0] == "word" and nxt[1] == "of":
                self.next()
            return Radical(self.primary(), index)
        if text == "of":
            return Row([])
        if text in ("left", "right"):
            return self.fence(text)
        if text in ACCENTS:
            self._note("accent:" + text)
            return Accent(text, self.primary())
        if text in UNDER_ACCENTS:
            self._note("accent:" + text)
            return Accent(text, self.primary(), below=True)
        if text in GRIDS:
            return self.grid(text)
        if text in STYLE_WORDS:
            self._note("style:" + text)
            return Styled(STYLE_WORDS[text], self.primary())
        if text in BIG_OPERATORS:
            self._note("bigop:" + text)
            return Atom(BIG_OPERATORS[text], "bigop",
                        limits=text in LIMITS_BELOW)
        if text in LIMIT_WORDS:
            self._note("bigop:" + text)
            return Atom(text, "func", limits=text in LIMITS_BELOW)
        if text in FUNCTIONS:
            self._note("function")
            return Atom(text, "func")
        if text in GREEK:
            self._note("greek")
            return Atom(GREEK[text], "sym")
        if text in SYMBOLS:
            self._note("symbol")
            return Atom(SYMBOLS[text], "sym")
        if text in _NEEDS_A_GRAMMAR:
            self._unsupported(text)
            return Raw(text, text)
        # An unknown word is a run of ordinary variables, exactly as HwpEqn
        # sets it: ``v_{sn}`` is v with two variable letters under it, not a
        # word called "sn".
        return Row([Atom(ch, "num" if ch.isdigit() else "var") for ch in text])

    def fence(self, which):
        delim = ""
        kind, text = self.peek()
        if kind in ("op", "brace") and text in DELIMITERS:
            self.next()
            delim = "" if text == "." else text
        elif kind == "word" and text in ("VERT", "vert"):
            self.next()
            delim = "|"
        if which == "right":
            # A ``right`` with no matching ``left`` — the caller consumed the
            # pair, so reaching here means the script is unbalanced.
            self._unsupported("right-without-left")
            return Raw(("right " + delim).strip(), "right-without-left")
        self._note("fence")
        body = self.expression(stop_words=("right",))
        close = ""
        nxt = self.peek()
        if nxt[0] == "word" and nxt[1] == "right":
            self.next()
            kind, text = self.peek()
            if kind in ("op", "brace") and text in DELIMITERS:
                self.next()
                close = "" if text == "." else text
            elif kind == "word" and text in ("VERT", "vert"):
                self.next()
                close = "|"
        else:
            self._unsupported("left-without-right")
        return Fence(delim, close, body)

    def grid(self, name):
        self._note("grid:" + name)
        nxt = self.peek()
        if not (nxt[0] == "brace" and nxt[1] == "{"):
            self._unsupported(name + "-without-body")
            return Raw(name, name)
        self.next()
        rows = [[]]
        while True:
            cell = self.expression()
            rows[-1].append(cell)
            kind, text = self.peek()
            if kind == "sep" and text == "&":
                self.next()
                continue
            if kind == "sep" and text == "#":
                self.next()
                rows.append([])
                continue
            if kind == "brace" and text == "}":
                self.next()
            break
        left, right = GRIDS[name]
        return Grid(rows, left, right, GRID_ALIGN.get(name, "c"))


# Constructs whose HwpEqn surface needs a grammar this tier does not have.
# Naming them here is what makes the renderer's declaration exhaustive: a
# token that reaches ``word()`` and is in this set is drawn as its own text.
_NEEDS_A_GRAMMAR = frozenset("""
    size color bigg BIGG small SMALL binom choose buildrel rel dyad
    col lcol rcol
""".split())


def parse(script):
    """``(tree, info)``.

    ``info`` carries ``constructs`` (what was laid out, by name and count) and
    ``unsupported`` (what was not, by name and count).  Both are how the
    renderer's sidecar stays exhaustive without the renderer knowing the
    grammar.
    """
    parser = _Parser(tokenize(script or ""))
    tree = parser.parse()
    return tree, {
        "parser": PARSER_VERSION,
        "constructs": dict(sorted(parser.constructs.items())),
        "unsupported": dict(sorted(parser.unsupported.items())),
        "over_binding": OVER_BINDING,
    }
