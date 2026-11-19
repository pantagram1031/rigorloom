"""The picture scanner's patterns are copies of the converter's.

``rt_toolset`` finds the pictures a markdown text names with copies of
md2spec's own patterns, so it checks a file exactly where the converter will
open one. When the converter changes a pattern, the copy has to change with
it; this test reads md2spec's source (it does not import the engine) and fails
on any difference. Without the engine it is skipped.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "runtime" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rt_toolset  # noqa: E402

#: md2spec's name -> the copy in rt_toolset
COPIES = {
    "CM_INLINE_RE": "_CM_INLINE",
    "FENCE_OPEN_RE": "_FENCE_OPEN",
    "FOOTNOTE_DEF": "_FOOTNOTE_DEF",
    "LINK_DEF_RE": "_LINK_DEF",
}


def _md2spec() -> Path | None:
    """md2spec.py in the configured engine folder or the installed package."""
    places = []
    raw = os.environ.get("RIGORLOOM_HWP_ENGINE", "").strip()
    if raw:
        places.append(Path(raw).expanduser())
    try:
        spec = importlib.util.find_spec("hwp_engine")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.submodule_search_locations:
        places.extend(Path(p) for p in spec.submodule_search_locations)
    for place in places:
        if (place / "md2spec.py").is_file():
            return place / "md2spec.py"
    return None


def _compiled(source: Path) -> dict[str, tuple[str, str]]:
    """Every module-level ``NAME = re.compile(literal[, flags])``: (pattern, flags)."""
    out = {}
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "compile" and call.args):
            continue
        try:
            pattern = ast.literal_eval(call.args[0])
        except ValueError:
            continue
        flags = " ".join(ast.unparse(a) for a in call.args[1:])
        out[node.targets[0].id] = (pattern, flags)
    return out


@pytest.fixture(scope="module")
def converter() -> dict[str, tuple[str, str]]:
    source = _md2spec()
    if source is None:
        pytest.skip("the HWP engine is not installed (set RIGORLOOM_HWP_ENGINE)")
    return _compiled(source)


@pytest.mark.parametrize("theirs, ours", sorted(COPIES.items()))
def test_the_scanner_uses_the_converters_own_pattern(converter, theirs, ours):
    assert theirs in converter, f"md2spec no longer defines {theirs}"
    pattern, flags = converter[theirs]
    copy = getattr(rt_toolset, ours)
    assert copy.pattern == pattern, f"{ours} differs from md2spec.{theirs}"
    assert flags == "", f"md2spec.{theirs} now has flags {flags}; {ours} has none"
