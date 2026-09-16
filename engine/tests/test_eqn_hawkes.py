"""Hawkes-bundle LaTeX → HwpEqn mappings: \\mid, primes, quad/qquad."""

import os
import re
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from eqn import (  # noqa: E402
    hwpeqn_sanity_check,
    latex_to_hwpeqn,
    validate_equation_operation,
)

HAWKES_CONTENT = Path(r"C:\Users\user\dev\reproduce-hawkes\bundle\content.md")
_EQ_DISPLAY_LATEX = re.compile(
    r'\[\[EQ\s+display\s+latex="([^"]*)"',
)


def _convert(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings == [], (source, warnings, script)
    assert hwpeqn_sanity_check(script)[0], script
    return script


def test_mid_maps_to_spaced_bar():
    assert _convert(r"x\mid y") == "x | y"


@pytest.mark.parametrize("source, expected", [
    (r"x'", "x^{prime}"),
    (r"x''", "x^{dprime}"),
    (r"f'(u)", "f^{prime}(u)"),
    (r"\prime", "prime"),
    (r"{x}'", "{x}^{prime}"),
    (r"(x)'", "(x)^{prime}"),
])
def test_primes_map_to_hwpeqn_prime_tokens(source, expected):
    assert _convert(source) == expected


@pytest.mark.parametrize("source, expected", [
    (r"x\quad y", "x ~ y"),
    (r"x\qquad y", "x ~~ y"),
])
def test_quad_and_qquad_map_to_tilde_spacing(source, expected):
    assert _convert(source) == expected


def test_stray_apostrophe_still_fails_preflight():
    for source in ("'x", "x ' y"):
        script, warnings = latex_to_hwpeqn(source)
        assert warnings
        _script, _warnings, ok, _reason = validate_equation_operation(
            {"op": "insert_equation", "latex": source})
        assert not ok, (source, script)


@pytest.mark.skipif(
    not HAWKES_CONTENT.is_file(),
    reason="Hawkes bundle content.md is absent",
)
def test_hawkes_display_equations_pass_preflight():
    text = HAWKES_CONTENT.read_text(encoding="utf-8")
    latex_list = _EQ_DISPLAY_LATEX.findall(text)
    assert latex_list, "no [[EQ display latex=...]] markers in Hawkes bundle"
    for latex in latex_list:
        script, warnings, ok, reason = validate_equation_operation(
            {"op": "insert_equation", "latex": latex, "display": True})
        assert ok and not warnings, (latex, script, warnings, reason)
