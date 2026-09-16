"""WindPath-bundle LaTeX → HwpEqn mappings: \\arg / argmin / argmax."""

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

WINDPATH_CONTENT = Path(r"C:\Users\user\dev\reproduce-windpath\bundle\content.md")
_EQ_DISPLAY_LATEX = re.compile(
    r'\[\[EQ\s+display\s+latex="([^"]*)"',
)


def _convert(source):
    script, warnings = latex_to_hwpeqn(source)
    assert warnings == [], (source, warnings, script)
    assert hwpeqn_sanity_check(script)[0], script
    return script


def test_arg_min_maps_to_spaced_function_names():
    assert _convert(r"\arg\min_{r}f(r)") == "arg min_{r}f(r)"


def test_arg_max_maps_to_spaced_function_names():
    assert _convert(r"\arg\max") == "arg max"


@pytest.mark.parametrize("source, expected", [
    (r"\argmin_{r}f(r)", "arg min_{r}f(r)"),
    (r"\argmax_{q}", "arg max_{q}"),
    (r"\operatorname{argmin}", '"argmin"'),
    (r"\operatorname*{argmin}", '"argmin"'),
])
def test_argmin_argmax_and_operatorname_variants(source, expected):
    assert _convert(source) == expected


@pytest.mark.skipif(
    not WINDPATH_CONTENT.is_file(),
    reason="WindPath bundle content.md is absent",
)
def test_windpath_display_equations_pass_preflight():
    text = WINDPATH_CONTENT.read_text(encoding="utf-8")
    latex_list = _EQ_DISPLAY_LATEX.findall(text)
    assert latex_list, "no [[EQ display latex=...]] markers in WindPath bundle"
    for latex in latex_list:
        script, warnings, ok, reason = validate_equation_operation(
            {"op": "insert_equation", "latex": latex, "display": True})
        assert ok and not warnings, (latex, script, warnings, reason)
