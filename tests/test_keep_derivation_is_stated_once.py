# -*- coding: utf-8 -*-
"""One keep-list derivation, stated the same way wherever it appears (T132).

`operations.md` described the form-fill keep list twice and differently. The
section documenting the standalone `check_residue` call said to derive it from
`profile anchors minus the keys your fill consumed`; the `visual_verify` section
283 lines away gave `(anchors ∪ placeholders)` minus the consumed entries.

Anchors alone is not enough, and the gap is reachable: `_profile_inventory` puts
`placeholder`-sourced rows in the forbidden set, so a form's own cross-reference
to another attachment's 서식 number — classified as a placeholder — stays
forbidden under an anchors-only keep list. A clean-room run followed the narrower
sentence verbatim and got a HARD on text its fill never touched.

The routing table presents standalone `check_residue` as a legitimate use, so the
narrower sentence was not a hypothetical path. Same class as #18/#20/#42/#43/#65:
a keep-list derivation that is right in one place and incomplete in another.

The guard pins the two things that matter and nothing else. A first version tried
to assert that no derivation sentence mentions guide text, and its matcher
swallowed the neighbouring sentence about `guide_text: 0` — an assertion that
cannot isolate its own subject is worse than no assertion.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "skill" / "references" / "operations.md"

#: The canonical set, as written. Wrapped lines are joined before searching.
CANONICAL = "(anchors ∪ placeholders)"

#: The incomplete form the fix removed: a derivation naming anchors alone.
INCOMPLETE_RE = re.compile(r"profile anchors minus the|anchors minus the keys")


def _flat() -> str:
    text = OPERATIONS.read_text(encoding="utf-8")
    # The file wraps at ~79 columns, so a sentence can straddle source lines.
    return re.sub(r"\n\s+", " ", text)


def test_the_canonical_set_is_stated_on_both_paths():
    """Once where check_residue is documented, once where visual_verify derives
    it. Non-vacuity comes for free: a count is asserted, not a presence."""
    flat = _flat()
    assert flat.count(CANONICAL) >= 2, (
        "the keep-list set is stated %d time(s); both the standalone gate path "
        "and the visual_verify path must name the same set, or they drift"
        % flat.count(CANONICAL))


def test_no_derivation_names_anchors_alone():
    flat = _flat()
    found = INCOMPLETE_RE.findall(flat)
    assert not found, (
        "a keep-list derivation that says anchors without placeholders leaves a "
        "form's own placeholder-classified text forbidden, so a correct fill "
        "HARDs on text it never touched: %s" % found)


def test_the_two_paths_still_both_exist_to_be_compared():
    """If either section is renamed away, the count above could pass for the
    wrong reason — both consumers have to still be documented here."""
    flat = _flat()
    assert "check_residue" in flat
    assert "visual_verify --fill-map" in flat or "visual_verify" in flat
