# -*- coding: utf-8 -*-
"""T106: an eval task's fixed floors must be true of the real corpus.

Each `evals/tasks/*.yaml` pins Bench-0 floors — `len(anchors) >= 28`,
`len(table_map) == 4` — against a specific corpus form. Those floors are
hand-written next to a detector that keeps changing, and nothing checked them
against the corpus, so they drift silently and surface to whoever replays the
task from a clean install.

A2 had drifted. Its `profile_blank` check asserted `len(table_map) == 3` while
`form_inspect.py` reports 4 on the byte-identical form. Established from
history rather than guessed: the assertion was last touched in #70 and
`table_map` semantics changed later in #76, so the detector moved and the
constant was never re-derived. #19 re-derived the recognition table after that
same change and missed this one.

Third instance of the class, after #26 (task count) and #27 (A1 skipped-check
count). Those fixes do not cover this one: they pinned counts inside test code,
while a task floor has to be true of a real file on disk.

The evaluator is `cleanroom.evaluate_assertions`, reused rather than
reimplemented — the harness already parses and evaluates these expressions when
it runs a task, and a second evaluator would be a second thing to keep in
agreement.

Scope, stated because it bounds what a pass here means: only checks that run a
profiler over an INPUT file are evaluated. Checks whose argv names a produced
artifact need an agent run and are out of scope; they are counted and reported,
never silently ignored.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import cleanroom  # noqa: E402

TASKS = sorted((ROOT / "evals" / "tasks").glob("*.yaml"))


def _input_backed_checks(task):
    """Checks whose argv reads only a task INPUT, so they need no agent run."""
    out = []
    for check in task.get("machine_checks") or []:
        if check.get("kind") != "python" or not check.get("assert_json"):
            continue
        argv = check.get("argv") or []
        if any("${WORK}" in str(a) and str(a).endswith((".hwpx", ".hwp", ".pdf"))
               for a in argv):
            continue
        if not any("${INPUTS}" in str(a) for a in argv):
            continue
        out.append(check)
    return out


def _resolve(argv, task, tmp_path):
    """Substitute the harness placeholders a floor check needs."""
    inputs = {Path(p).name: ROOT / p for p in task["input_files"]}
    resolved = []
    for item in argv:
        text = str(item)
        if "${INPUTS}/" in text:
            name = text.split("${INPUTS}/", 1)[1]
            resolved.append(str(inputs[name]))
        elif "${WORK}/" in text:
            resolved.append(str(tmp_path / text.split("${WORK}/", 1)[1]))
        else:
            resolved.append(str(ROOT / text) if text.endswith(".py") else text)
    return resolved


def test_there_are_tasks_with_input_backed_floors():
    """Non-vacuity floor: the rest passes trivially over an empty list."""
    assert TASKS, "no eval tasks found"
    total = sum(len(_input_backed_checks(cleanroom.load_task(t))) for t in TASKS)
    assert total >= 6, total


@pytest.mark.parametrize("task_path", TASKS, ids=lambda p: p.stem)
def test_task_floors_hold_against_the_real_corpus(task_path, tmp_path):
    """Run each input-backed profiler for real and evaluate its own floors.

    This is the guard the class needed. A detector change that invalidates a
    pinned floor now fails here, instead of reaching a buyer who replays the
    task from a clean bundle install.
    """
    task = cleanroom.load_task(task_path)
    checks = _input_backed_checks(task)
    if not checks:
        pytest.skip(f"{task_path.stem} pins no input-backed floors")
    for check in checks:
        argv = _resolve(check["argv"], task, tmp_path)
        completed = subprocess.run([sys.executable, *argv], capture_output=True,
                                   text=True, encoding="utf-8",
                                   errors="replace", cwd=str(ROOT))
        assert completed.returncode == check.get("expect_exit", 0), (
            check["id"], completed.returncode, completed.stderr[-400:])
        target = _resolve([check["json_file"]], task, tmp_path)[0]
        document = json.loads(Path(target).read_text(encoding="utf-8"))
        results = cleanroom.evaluate_assertions(document,
                                                check["assert_json"])
        failed = [r for r in results if not r["ok"]]
        assert failed == [], (task_path.stem, check["id"], failed)
