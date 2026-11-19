"""The guard on Sol's 55 before/after pairs from the T180 review.

Every guard rule is measured on the same pairs instead of examples written for
the rule. A pair whose fact is unchanged, or whose token the guard leaves alone
on purpose, must pass: a new false alarm fails this file. A pair the guard
still misses carries the name of the T181 rule meant to catch it and runs as a
strict xfail, so the PR that closes it has to delete the gap as well.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "runtime" / "scripts" / "cli.py"
PAIRS = json.loads((REPO / "tests" / "fixtures" / "guard_pairs" / "sol-t180-pairs.json")
                   .read_text(encoding="utf-8"))["pairs"]
GAPS = {"order", "magnitude-unit", "numbers-in-words", "fractions", "ranges",
        "phone-account-id", "list-labels", "leading-decimal"}


@pytest.fixture(scope="module")
def flagged(tmp_path_factory) -> dict[int, list[str]]:
    # One guard run over all pairs, one pair per paragraph: the guard compares
    # paragraph by paragraph, so this is the same verdict as 55 separate runs.
    folder = tmp_path_factory.mktemp("pairs")
    before, after = folder / "before.txt", folder / "after.txt"
    before.write_text("\n\n".join(p["before"] for p in PAIRS) + "\n", encoding="utf-8")
    after.write_text("\n\n".join(p["after"] for p in PAIRS) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "guard", str(before), str(after)],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["paragraphs"] == {"before": len(PAIRS), "after": len(PAIRS)}
    return {c["paragraph"]: c["kinds"] for c in result["changed"]}


def test_the_pairs_are_well_formed():
    assert len(PAIRS) == 55
    assert len({p["case"] for p in PAIRS}) == len(PAIRS)
    for p in PAIRS:
        assert "\n" not in p["before"] + p["after"], p["case"]
        assert p["fact"] in {"changed", "same"}, p["case"]
        assert p.get("scope", "in") in {"in", "out"}, p["case"]
        assert p.get("gap") is None or p["gap"] in GAPS, p["case"]
        # A gap is a change the guard should catch, never one it should pass.
        assert not p.get("gap") or (p["fact"] == "changed" and p.get("scope", "in") == "in"), p["case"]


CASES = [pytest.param(i, p, id=p["case"],
                      marks=[pytest.mark.xfail(strict=True, reason=f"T181 {p['gap']}")] if p.get("gap") else [])
         for i, p in enumerate(PAIRS, start=1)]


@pytest.mark.parametrize("paragraph,pair", CASES)
def test_the_guard_flags_a_pair_only_when_a_fact_changed(flagged, paragraph, pair):
    should_flag = pair["fact"] == "changed" and pair.get("scope", "in") == "in"
    assert (paragraph in flagged) == should_flag, (pair["before"], pair["after"], flagged.get(paragraph))
