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
