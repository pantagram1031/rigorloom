"""#61 — every value a task prompt names must be asserted or accounted for.

The gates verify the internal consistency of what an agent asserts; nothing
verified fidelity to what was *asked*. On the eval side the request IS
machine-readable — it is in the task's ``prompt`` — so the gap is closable here,
and the A2 run showed what it costs when it is not: the prompt supplied
``본인 성명: 김도현``, no check named it, the value was never written, and every
gate passed.

The capability was already there (``text_present``); it simply was not used for
the request. Measured before this guard: across 8 tasks the prompts named 39
values and 7 were asserted anywhere.

This guard does not invent a checker. It parses the prompt, and fails on any
value that is neither asserted by a ``text_present``/``text_absent`` check nor
listed in ``unasserted_prompt_values`` with a reason from a closed vocabulary.
``uncurated`` is one of those reasons on purpose: the debt stays countable
instead of invisible.
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import cleanroom  # noqa: E402

#: ``- 본인 성명: 김도현`` — the shape every task prompt uses for a supplied
#: value. Labels are bounded so a prose line with a mid-sentence colon does not
#: register as a field.
BULLET = re.compile(r"^\s*[-•]\s*([^:：\n]{1,24})[:：][ \t]*(\S.*?)\s*$", re.M)

WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return WS.sub(" ", text).strip()


def _tasks():
    paths = sorted((ROOT / "evals" / "tasks").glob("*.yaml"))
    assert paths, "no eval tasks found"
    return [(p.name, yaml.safe_load(p.read_text(encoding="utf-8")))
            for p in paths]


def _prompt_values(task) -> list[str]:
    return [_norm(m.group(2)) for m in BULLET.finditer(task.get("prompt") or "")]


def _asserted(task) -> dict[str, set[str]]:
    """kind -> normalized strings the task asserts about the artifact text."""
    out: dict[str, set[str]] = {"text_present": set(), "text_absent": set()}
    for check in task.get("machine_checks") or []:
        kind = check.get("kind")
        if kind in out:
            out[kind].update(_norm(s) for s in check.get("strings") or [])
    return out


def _listed(task) -> dict[str, str]:
    """normalized value -> reason, from ``unasserted_prompt_values``."""
    return {_norm(row["value"]): row["why"]
            for row in task.get("unasserted_prompt_values") or []}


ALL = _tasks()


def test_the_bullet_parser_still_matches():
    """Non-vacuity. If the prompt shape changes and this stops matching, every
    assertion below passes for every task at once — the failure mode of a guard
    that derives its own expectations."""
    total = sum(len(_prompt_values(task)) for _name, task in ALL)
    assert total >= 35, total
    named = {name: len(_prompt_values(task)) for name, task in ALL}
    assert sum(1 for count in named.values() if count) >= 6, named


@pytest.mark.parametrize("name,task", ALL, ids=[n for n, _t in ALL])
def test_every_prompt_value_is_asserted_or_accounted(name, task):
    asserted = _asserted(task)
    covered = asserted["text_present"] | asserted["text_absent"]
    listed = _listed(task)
    unaccounted = [v for v in _prompt_values(task)
                   if v not in covered and v not in listed]
    assert not unaccounted, (
        f"{name}: prompt names values that no check asserts and that are not "
        f"listed in unasserted_prompt_values: {unaccounted}")


@pytest.mark.parametrize("name,task", ALL, ids=[n for n, _t in ALL])
def test_no_stale_entry_silences_a_value_the_prompt_no_longer_names(name, task):
    """The other direction, which is the one that rots.

    A list of exemptions outlives the prompt it was written against. An entry
    naming a value the prompt does not contain silences nothing and hides that
    the real value is unchecked.
    """
    values = set(_prompt_values(task))
    stale = [v for v in _listed(task) if v not in values]
    assert not stale, (
        f"{name}: unasserted_prompt_values names values the prompt does not: "
        f"{stale}")


@pytest.mark.parametrize("name,task", ALL, ids=[n for n, _t in ALL])
def test_expected_absent_is_backed_by_a_text_absent_check(name, task):
    """``expected_absent`` must cost something, or it is a dodge.

    Claiming a value is deliberately not written is a real claim about the
    artifact, so the task has to assert it the same way it would assert any
    other: with ``text_absent``.
    """
    absent = _asserted(task)["text_absent"]
    missing = [v for v, why in _listed(task).items()
               if why == "expected_absent" and v not in absent]
    assert not missing, (
        f"{name}: declared expected_absent without a text_absent check: "
        f"{missing}")


def test_the_reason_vocabulary_is_closed_and_the_debt_is_countable():
    """Every reason used is in the vocabulary, and ``uncurated`` is reported.

    The count is the point: a number that has to go down is a different thing
    from a sentence saying the work is unfinished.
    """
    used = {why for _name, task in ALL for why in _listed(task).values()}
    assert used <= cleanroom.UNASSERTED_REASONS, sorted(
        used - cleanroom.UNASSERTED_REASONS)
    uncurated = {name: sum(1 for why in _listed(task).values()
                           if why == "uncurated")
                 for name, task in ALL}
    total = sum(uncurated.values())
    # Every value is curated from measurement, so the debt is zero. Pinned at 0
    # rather than left unasserted: a new task shipping `uncurated` entries has to
    # move this number on purpose.
    assert total == 0, {"total": total, "per_task": uncurated}


# --------------------------------------------------------------------------- #
# T118 - a rule NAME is never searched for as a substring of a verdict JSON.
#
# evals/README.md documented the convention "a rule name absent from the verdict
# JSON means it ran and passed". check_grant does not honour it: it writes a rule
# name as a finding, as a positive acknowledgment, AND as a permanent skipped row
# with a reason. A3 asserted 13 names absent and could never pass - not on a
# perfect fill, and not on the pristine corpus form that check_grant grades
# `pass`, because budget_total_mismatch is a permanent `skipped` row.
#
# Third instance of an eval check that cannot be satisfied (T106, T107), so the
# durable half is this guard rather than a third one-off repair.
# --------------------------------------------------------------------------- #


#: The instances of the name-search class still open, pinned so a NEW one fails
#: and a fixed one forces this list down on purpose - the same countable-debt
#: shape as `uncurated` in the prompt-value guard.
#:
#: Closing these needs `check_hr` and `check_minwon` to publish a `rules` outcome
#: map the way `check_grant` now does; the grant instances (A2, A3) are already
#: converted. Deliberately not done in one slice: two more checkers and two more
#: task rewrites is a different change, and a resisting slice is a signal.
KNOWN_NAME_SEARCH_DEBT = [
    "H1-labor-contract-fill.yaml:hr_version_rules_were_decided:"
    "template_version_changed",
    "H1-labor-contract-fill.yaml:hr_version_rules_were_decided:"
    "template_version_mixed",
    "P2-jeongbo-staff-seats.yaml:minwon_staff_rules_were_decided:"
    "staff_seat_filled",
    "P2-jeongbo-staff-seats.yaml:minwon_staff_rules_were_decided:"
    "staff_seat_removed",
]

def _rule_vocabulary() -> set:
    """Every rule name any shipped checker can emit, parsed from the source.

    Three shapes, because only ONE checker of fifteen declares a RULES tuple —
    measured, after a first version of this guard covered the grant module alone
    and silently missed H1 searching for check_hr rule names (T118).
    """
    names: set = set()
    for path in (ROOT / "modules").rglob("scripts/check_*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"^RULES\s*=\s*\((.*?)\)", text, re.M | re.S)
        if block:
            names.update(re.findall(r'"([a-z_]+)"', block.group(1)))
        names.update(re.findall(r'_finding\(\s*"([a-z_]+)"', text))
        names.update(re.findall(r'"rule":\s*"([a-z_]+)"', text))
    return names


def test_no_task_searches_for_a_rule_name_in_a_verdict_json():
    """Assert the rule's OUTCOME, never the presence of its name.

    A substring search over a serialized verdict cannot tell "fired" from "ran
    clean and said so" from "always skips for this document".
    """
    vocabulary = _rule_vocabulary()
    assert len(vocabulary) >= 15, sorted(vocabulary)  # non-vacuity
    offenders = []
    for name, task in ALL:
        for check in task.get("machine_checks") or []:
            if check.get("kind") not in ("text_present", "text_absent"):
                continue
            artifact = str(check.get("artifact") or "")
            if "verdict" not in artifact:
                continue
            for string in check.get("strings") or []:
                if string in vocabulary:
                    offenders.append(f"{name}:{check.get('id')}:{string}")
    assert sorted(offenders) == KNOWN_NAME_SEARCH_DEBT, {
        "new": sorted(set(offenders) - set(KNOWN_NAME_SEARCH_DEBT)),
        "fixed_but_still_pinned": sorted(
            set(KNOWN_NAME_SEARCH_DEBT) - set(offenders)),
    }


def test_the_rule_vocabulary_parser_still_finds_the_grant_rules():
    """Guards the parser, not the tasks: if RULES stops matching, the guard
    above passes for every task at once."""
    vocabulary = _rule_vocabulary()
    for expected in ("table_structure_lost", "budget_total_mismatch",
                     "consent_unmarked", "example_placeholder_retained"):
        assert expected in vocabulary, sorted(vocabulary)
