"""The guard on the reviewer's before/after pairs from the T180 and T183 reviews and
the re-check of the T183 fixes, and on the advisor's pairs from the reviews of the
T183 head and the label-words rule.

Every guard rule is measured on the same pairs instead of examples written for
the rule. A pair whose fact is unchanged, or whose token the guard leaves alone
on purpose, must pass: a new false alarm fails this file. A pair the guard
still gets wrong carries the name of the follow-up rule meant to fix it and
runs as a strict xfail, so the PR that fixes it has to delete the gap as well.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "runtime" / "scripts" / "cli.py"
FIXTURES = REPO / "tests" / "fixtures" / "guard_pairs"
#: fixture -> how many pairs it holds; T180's pairs are one line each, T183's
#: may hold a table or a list on several lines (one paragraph still).
SETS = {"sol-t180-pairs.json": 55, "sol-t183-pairs.json": 92, "sol-t183b-pairs.json": 79,
        "fable-t183-pairs.json": 15, "fable-t193-pairs.json": 3}
PAIRS = {name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pairs"] for name in SETS}
GAPS = {"numbers-in-words", "fractions", "ranges", "phone-account-id", "list-labels",
        "leading-decimal", "year-month", "time-units", "date-forms", "clock-times",
        "article-branches", "spaced-version", "table-columns", "each-list-count"}


@pytest.fixture(scope="module")
def flagged(tmp_path_factory) -> dict[str, dict[int, list[str]]]:
    # One guard run per set, one pair per paragraph: the guard compares
    # paragraph by paragraph, so this is the same verdict as separate runs.
    out = {}
    for name, pairs in PAIRS.items():
        folder = tmp_path_factory.mktemp("pairs")
        before, after = folder / "before.txt", folder / "after.txt"
        before.write_text("\n\n".join(p["before"] for p in pairs) + "\n", encoding="utf-8")
        after.write_text("\n\n".join(p["after"] for p in pairs) + "\n", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(CLI), "guard", str(before), str(after)],
                              capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode in (0, 3), proc.stdout + proc.stderr
        result = json.loads(proc.stdout)["result"]
        assert result["paragraphs"] == {"before": len(pairs), "after": len(pairs)}
        out[name] = {c["paragraph"]: c["kinds"] for c in result["changed"]}
    return out


@pytest.mark.parametrize("name", sorted(SETS))
def test_the_pairs_are_well_formed(name):
    pairs = PAIRS[name]
    assert len(pairs) == SETS[name]
    assert len({p["case"] for p in pairs}) == len(pairs)
    for p in pairs:
        text = p["before"] + "\n" + p["after"]
        assert "\n\n" not in text, p["case"]
        assert name != "sol-t180-pairs.json" or "\n" not in p["before"] + p["after"], p["case"]
        assert p["fact"] in {"changed", "same"}, p["case"]
        assert p.get("scope", "in") in {"in", "out"}, p["case"]
        assert p.get("gap") is None or p["gap"] in GAPS, p["case"]
        # A pair outside the guard's scope is passed on purpose, never a gap.
        assert not p.get("gap") or p.get("scope", "in") == "in", p["case"]


CASES = [pytest.param(name, i, p, id=f"{name.split('-')[1]}-{p['case']}",
                      marks=[pytest.mark.xfail(strict=True, reason=f"not right yet: {p['gap']}")]
                      if p.get("gap") else [])
         for name in sorted(SETS) for i, p in enumerate(PAIRS[name], start=1)]


@pytest.mark.parametrize("name,paragraph,pair", CASES)
def test_the_guard_flags_a_pair_only_when_a_fact_changed(flagged, name, paragraph, pair):
    should_flag = pair["fact"] == "changed" and pair.get("scope", "in") == "in"
    got = flagged[name]
    assert (paragraph in got) == should_flag, (pair["before"], pair["after"], got.get(paragraph))
