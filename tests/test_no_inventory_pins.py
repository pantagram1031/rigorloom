# -*- coding: utf-8 -*-
"""Guard: a core test may not pin per-module or per-task INVENTORY as an integer.

Three separate v0.17 modules were blocked by one bug, and it was the same bug
each time — a core test asserting ``== N`` where a property belonged:

* **#68** — ``pyproject.toml`` ``testpaths`` and the CI ``py_compile`` step were
  per-module LISTS. Adding a work-type module meant editing core configuration.
  Fixed by globbing (``modules/*/tests``, ``modules/*/scripts/*.py``).
* **#26** — ``test_every_shipped_task_validates`` pinned ``len(tasks) == 7``.
  Shipping an eval task meant editing a core test. Fixed by deriving family
  coverage from ``tests/corpus/forms/manifest.json``, asserted both directions.
* **#27** — ``test_cleanroom_evals.py`` pinned A1's skipped-check count at 1, in
  two places. Every ``requires_module`` check skips by design in a core-only
  sandbox, so the grant module could not put its A1 checks on A1 and wired them
  onto A2/A3 instead. Fixed by deriving the expected skips from the task
  definition (``declared_skips``).

The rule the class keeps violating is contract rule 4 (modules/README.md):
*adding a distribution module requires no change to core*. A count is the
cheapest possible way to break it, because a count looks like a fact.

    Derive from discovery, never pin inventory.

WHAT THIS GUARD FLAGS
---------------------
An ``assert`` whose comparison is ``==`` against an integer literal, where the
other operand reads as inventory:

* a check tally — ``…["counts"]["skipped"]``, ``…["machine"]["pass"]`` and the
  rest of ``{pass, fail, skipped, total}``. This is the #27 shape exactly;
* ``len(X)`` or ``X.count(…)`` where ``X`` mentions an inventory identifier
  (modules, tasks, checks, packs, bundles, corpus, checkers, gate kinds, pack
  types, families, playbooks, panels, skills, inputs) or a DISCOVERY call
  (``glob``, ``rglob``, ``iterdir``, ``discover``, ``load_tasks``, ``walk``);
* a subscript whose last key is one of those inventory names —
  ``manifest["provides"]["playbooks"] == 1``.

``>=`` and ``<=`` are deliberately NOT flagged: a floor is the prescribed fix
(``assert len(tasks) >= MIN_SHIPPED_TASKS``), not the disease. Neither is
anything under ``modules/*/tests`` — a module's own tests may measure its own
corpus all they like; the contract only forbids core knowing.

The scan is over the syntax tree, not a regex over lines, so it does not
over-match on strings, comments or docstrings — including the ``len(tasks) ==
7`` quoted in the #26 test's own docstring.

WHEN IT FIRES ON YOU
--------------------
Two honest outcomes, and the guard is designed so choosing between them is the
whole cost:

1. the pin really is inventory-coupled → derive it (a discovery result, a
   ``len()`` of the definition) and add a non-vacuity floor so the derived scan
   cannot pass over an empty collection;
2. the integer is genuinely fixed arity that must not drift → add a row to
   ``ALLOWLIST`` below. A row carries a REASON, so the allowlist is the
   documentation. A row with no reason, or a reason that just says "existing",
   is refused by ``test_every_allowlist_row_carries_a_reason``.

Rows are matched on the exact source line, not a line number, so they survive
code moving and go stale the moment the assertion is rewritten.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = Path(__file__).name

#: The core test tree. ``modules/*/tests`` is out of scope on purpose (see
#: module docstring): those tests are the module's own payload.
SCAN_ROOTS = ("tests", "pipeline/tests")
SCAN_EXTRA = ("conftest.py",)

#: Keys that make a subscript a check/gate TALLY rather than a measurement of
#: some synthetic document.
TALLY_CONTAINERS = ("counts", "machine")
TALLY_KEYS = ("pass", "fail", "skipped", "total")

#: Identifiers that read as inventory: things the repo GROWS. Matched as whole
#: words against the source of the counted expression, so ``checked_numerals``
#: and ``exit_code`` do not trip it.
INVENTORY_WORDS = (
    "modules?", "tasks?", "checks?", "packs?", "pack_types?", "bundles?",
    "corpus", "checkers?", "gate_kinds?", "famil(?:y|ies)", "playbooks?",
    "panels?", "skills?", "inputs?", "documents?",
)
#: Calls that enumerate the filesystem or the registry — a ``len()`` over one of
#: these is a count of whatever happens to be on disk.
DISCOVERY_WORDS = ("glob", "rglob", "iterdir", "walk", "discover",
                   "load_tasks", "load_task", "enabled_")

# Case-insensitive on purpose: the inventory noun shows up capitalised inside
# rendered text too (``body.count("## Module: style")``), and a count of a
# per-module heading is exactly the shape worth a second look.
_INVENTORY_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])(?:" + "|".join(INVENTORY_WORDS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE)
_DISCOVERY_RE = re.compile("|".join(DISCOVERY_WORDS))


# --------------------------------------------------------------------------- #
# Allowlist: reasoned exceptions. A row is (file, source line, reason).
#
# The reason must say why the integer is NOT inventory-coupled — i.e. why no
# added module, task, corpus document or shipped pack can move it. "It has
# always been there" is not a reason and the meta-test below says so.
# --------------------------------------------------------------------------- #
ALLOWLIST: tuple[tuple[str, str, str], ...] = (
    (
        "tests/test_cleanroom_evals.py",
        'assert body.count("## Module: style") == 1',
        "Idempotency arity, not inventory: 1 means 'the fragment was merged "
        "once, not twice' on a re-install. It counts ONE NAMED module's "
        "heading, so installing a tenth module cannot move it.",
    ),
    (
        "tests/test_cleanroom_evals.py",
        'assert ran["counts"]["pass"] == 2 and ran["counts"]["skipped"] == 0',
        "Arity of ``_module_gated_task``, a two-check task this same file "
        "constructs in-process. No shipped task, module or corpus document "
        "feeds it; the literals are what make the 1-pass-1-skip arithmetic "
        "below readable.",
    ),
    (
        "tests/test_cleanroom_evals.py",
        'assert skipped["counts"]["pass"] == 1, (',
        "Same in-process ``_module_gated_task``: exactly one of its two checks "
        "is gated, so the pass count is 1 by construction.",
    ),
    (
        "tests/test_cleanroom_evals.py",
        'assert skipped["counts"]["skipped"] == 1',
        "Same in-process ``_module_gated_task``: exactly one gated check, so "
        "exactly one skip. This is the claim under test — that the skip lands "
        "in ``skipped`` and not in ``pass``.",
    ),
    (
        "tests/test_cleanroom_evals.py",
        'assert card["machine"]["pass"] == 1',
        "score.py's view of the same in-process two-check task; the tally is "
        "the fixture's arity, asserted to prove score.py does not read a skip "
        "as a pass.",
    ),
    (
        "tests/test_cleanroom_evals.py",
        'assert card["machine"]["skipped"] == 1',
        "score.py's view of the same in-process two-check task: one gated "
        "check, one skip, reported rather than swallowed.",
    ),
    (
        "tests/test_package_module.py",
        'assert manifest["provides"]["playbooks"] == 1',
        "Arity of the synthetic ``throwaway`` module that ``make_module`` "
        "writes into tmp_path in this test — one playbook, because the test "
        "declared one. It is not a count of the repo's modules or playbooks.",
    ),
    (
        "pipeline/tests/test_module_registry.py",
        "assert len(skills) == 1",
        "Arity of the synthetic ``throwaway`` module in tmp_path: one "
        "``provides.skill`` declaration, so the typed accessor must surface "
        "exactly one row. Real ``modules/`` is not read here.",
    ),
    (
        "pipeline/tests/test_ws_snapshot.py",
        'assert len(list(snapshot_dir.glob("pre-assembly-*.zip"))) == 2',
        "Glob over a tmp_path directory this test populated itself: the claim "
        "is snapshot ROTATION arity (two runs kept two snapshots), and no "
        "repo inventory reaches it.",
    ),
    (
        "pipeline/tests/test_ws_snapshot.py",
        'assert len(list(snapshot_dir.glob("pre-assembly-*.zip.sha256"))) == 2',
        "Same tmp_path rotation claim, on the sidecar digests: one sidecar per "
        "snapshot, so the two counts must agree.",
    ),
)

_BANNED_REASONS = ("existing", "legacy", "pre-existing", "grandfather",
                   "as before", "historical", "todo", "for now")


# --------------------------------------------------------------------------- #
# scanner
# --------------------------------------------------------------------------- #
def _core_test_files() -> list[Path]:
    found: list[Path] = []
    for root in SCAN_ROOTS:
        found += sorted((REPO_ROOT / root).glob("*.py"))
    for name in SCAN_EXTRA:
        path = REPO_ROOT / name
        if path.is_file():
            found.append(path)
    return [path for path in found if path.name != GUARD_FILE]


def _int_literal(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool))


def _subscript_keys(node: ast.AST) -> list[str]:
    """String keys of a subscript chain, outermost last."""
    keys: list[str] = []
    while isinstance(node, ast.Subscript):
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            keys.append(index.value)
        node = node.value
    keys.reverse()
    return keys


def _is_tally(node: ast.AST) -> bool:
    keys = _subscript_keys(node)
    return (len(keys) >= 2 and keys[-1] in TALLY_KEYS
            and any(key in TALLY_CONTAINERS for key in keys[:-1]))


def _counting_call(node: ast.AST) -> str | None:
    """Source of the counted expression for ``len(X)`` / ``X.count(...)``."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "len" and node.args:
        return ast.unparse(node.args[0])
    if isinstance(func, ast.Attribute) and func.attr == "count":
        return ast.unparse(node)
    return None


def _inventory_reason(node: ast.AST) -> str | None:
    """Why ``node`` reads as inventory, or None."""
    if _is_tally(node):
        return "check tally (counts/machine pass|fail|skipped|total)"
    counted = _counting_call(node)
    if counted is not None:
        if _INVENTORY_RE.search(counted):
            return "len()/count() over an inventory identifier"
        if _DISCOVERY_RE.search(counted):
            return "len()/count() over a discovery result"
        return None
    keys = _subscript_keys(node)
    if keys and _INVENTORY_RE.search(keys[-1]):
        return "subscript on an inventory key"
    return None


def _pins(path: Path) -> list[tuple[int, str, str]]:
    """``(lineno, source line, why)`` for every inventory-shaped ``== int``."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert):
            continue
        for compare in [n for n in ast.walk(node.test)
                        if isinstance(n, ast.Compare)]:
            operands = [compare.left, *compare.comparators]
            for op, left, right in zip(compare.ops, operands, operands[1:]):
                if not isinstance(op, ast.Eq):
                    continue
                for a, b in ((left, right), (right, left)):
                    if not _int_literal(b):
                        continue
                    why = _inventory_reason(a)
                    if why:
                        hits.append(
                            (node.lineno, lines[node.lineno - 1].strip(), why))
                        break
    # one row per assert statement, in source order
    seen: dict[int, tuple[int, str, str]] = {}
    for hit in hits:
        seen.setdefault(hit[0], hit)
    return [seen[key] for key in sorted(seen)]


def _allowed(relative: str) -> set[str]:
    return {line for path, line, _ in ALLOWLIST if path == relative}


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
class TestNoInventoryPins:
    def test_the_scan_is_not_vacuous(self):
        """A guard that scans nothing proves nothing."""
        files = _core_test_files()
        assert len(files) >= 20, f"only {len(files)} core test file(s) scanned"
        assert any(path.name == "test_cleanroom_evals.py" for path in files)

    def test_no_core_test_pins_inventory_as_an_integer(self):
        offenders: list[str] = []
        for path in _core_test_files():
            relative = path.relative_to(REPO_ROOT).as_posix()
            allowed = _allowed(relative)
            for lineno, line, why in _pins(path):
                if line in allowed:
                    continue
                offenders.append(f"{relative}:{lineno}: {line}   [{why}]")
        assert not offenders, (
            "core test(s) pin inventory as an integer — derive it from "
            "discovery (and add a non-vacuity floor), or add a REASONED row to "
            "ALLOWLIST in tests/test_no_inventory_pins.py:\n  "
            + "\n  ".join(offenders))

    def test_the_guard_catches_the_shape_it_exists_for(self, tmp_path):
        """Negative control. Each of these is a pin the guard must see; the
        first is #27's own assertion, verbatim."""
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            'def test_a(results):\n'
            '    assert results["counts"]["skipped"] == 1\n'
            'def test_b(tasks):\n'
            '    assert len(tasks) == 7\n'
            'def test_c(root):\n'
            '    assert len(list(root.glob("*/module.yaml"))) == 6\n'
            'def test_d(manifest):\n'
            '    assert manifest["provides"]["pack_types"] == 3\n'
            'def test_e(registry):\n'
            '    assert len(registry.discover()) == 6\n',
            encoding="utf-8")
        found = _pins(planted)
        assert [row[0] for row in found] == [2, 4, 6, 8, 10], found

    @pytest.mark.parametrize("source", [
        # a floor is the prescribed fix, never the disease
        'assert len(tasks) >= MIN_SHIPPED_TASKS\n',
        'assert len(tasks) >= 5\n',
        # measurements of a document the test itself built
        'assert manifest["counts"]["pictures"] == 2\n',
        'assert content.count("[[FIG ") == 2\n',
        'assert inventory["counts"]["slots"] == 2\n',
        # not a count at all
        'assert checker_base.exit_code(hard=hard) == 3\n',
        'assert verdict["checked_numerals"] == 1\n',
        'assert task[0]["page"] == 2\n',
        # the derived form the fix uses
        'assert results["counts"]["skipped"] == len(expected)\n',
        # a count named in a docstring or a string is not an assertion
        '"""The old form asserted len(tasks) == 7."""\n',
    ])
    def test_the_guard_does_not_over_match(self, tmp_path, source):
        planted = tmp_path / "test_ok.py"
        planted.write_text(source, encoding="utf-8")
        assert _pins(planted) == []

    def test_every_allowlist_row_carries_a_reason(self):
        """An allowlist entry documents itself or it is not an entry."""
        for relative, line, reason in ALLOWLIST:
            assert (REPO_ROOT / relative).is_file(), relative
            assert line.startswith("assert"), (relative, line)
            assert len(reason.split()) >= 12, (
                f"{relative}: reason too thin to be documentation: {reason!r}")
            lowered = reason.lower()
            for banned in _BANNED_REASONS:
                assert banned not in lowered, (
                    f"{relative}: {banned!r} is not a reason — say why the "
                    f"integer cannot be moved by an added module or task")

    def test_no_allowlist_row_is_stale(self):
        """A row whose assertion no longer exists is a lie about the code."""
        stale = []
        for relative, line, _ in ALLOWLIST:
            body = (REPO_ROOT / relative).read_text(encoding="utf-8")
            if not any(candidate.strip() == line
                       for candidate in body.splitlines()):
                stale.append(f"{relative}: {line}")
        assert not stale, (
            "ALLOWLIST rows no longer match any line in the file — the "
            "assertion was rewritten; drop the row:\n  " + "\n  ".join(stale))

    def test_every_allowlist_row_is_actually_flagged(self):
        """…and a row the guard would not have flagged is dead weight."""
        unnecessary = []
        for relative, line, _ in ALLOWLIST:
            flagged = {row[1] for row in _pins(REPO_ROOT / relative)}
            if line not in flagged:
                unnecessary.append(f"{relative}: {line}")
        assert not unnecessary, (
            "ALLOWLIST rows the guard does not flag — remove them:\n  "
            + "\n  ".join(unnecessary))
