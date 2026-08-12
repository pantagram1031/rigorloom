# -*- coding: utf-8 -*-
"""The support matrix cannot claim more than the tree can show (T124).

The standing goal wants capabilities classified supported / partially /
unsupported / unknown **with reproducible evidence**. A markdown table can say
anything, so the value is entirely in the refusals: a `supported` row whose
pointers do not resolve must fail, and a new module or task must not be able to
go unclassified in silence.

These tests are therefore mostly negative. Each one plants the mistake the
generator is supposed to catch and asserts it is caught by name.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import package_module  # noqa: E402
import support_matrix as sm  # noqa: E402


@pytest.fixture(scope="module")
def claims():
    return sm.load_claims()


# ---------------------------------------------------------------------------
# the shipped claims, and the document
# ---------------------------------------------------------------------------

def test_every_shipped_claim_validates(claims):
    problems = sm.validate(claims)
    assert problems == [], problems


def test_the_document_matches_the_generator(claims):
    """Same contract the capability matrix has: a generated doc must not drift."""
    assert sm.MATRIX_DOC.read_text(encoding="utf-8") == sm.render_matrix(claims)


def test_the_document_table_is_not_ragged():
    defects = package_module.markdown_table_defects(
        sm.MATRIX_DOC.read_text(encoding="utf-8"))
    assert defects == [], defects


def test_the_claim_set_is_not_trivially_small(claims):
    """A file with two rows would pass every other test here."""
    assert len(claims) >= 12, len(claims)
    statuses = {c["status"] for c in claims}
    assert "supported" in statuses
    # If nothing is ever downgraded, the vocabulary is decoration.
    assert statuses & {"partially", "unsupported", "unknown"}, statuses


# ---------------------------------------------------------------------------
# refusals — one test per mistake the mechanism exists to stop
# ---------------------------------------------------------------------------

def _claim(**over):
    base = {"id": "probe-row", "capability": "something", "status": "supported",
            "evidence": ["eval:A1-pps-recognize-fill"]}
    base.update(over)
    return base


def _covering_claim():
    """A claim that satisfies coverage, so a test can isolate one failure."""
    return {
        "id": "coverage", "capability": "coverage", "status": "unknown",
        "reason": "fixture", "evidence": [],
        "covers": [f"module:{m}" for m in sm.installed_modules()]
                  + [f"eval:{t}" for t in sm.shipped_tasks()],
    }


def _problems(*claims):
    return sm.validate([_covering_claim(), *claims])


def test_supported_without_evidence_is_refused():
    problems = _problems(_claim(evidence=[]))
    assert any("no evidence pointer" in p for p in problems), problems


def test_a_downgrade_without_a_reason_is_refused():
    for status in ("partially", "unsupported", "unknown"):
        problems = _problems(_claim(status=status))
        assert any("must carry a reason" in p for p in problems), (status, problems)


def test_an_unresolvable_test_pointer_is_refused():
    problems = _problems(_claim(
        evidence=["test:engine/tests/test_preedit.py::test_does_not_exist_anywhere"]))
    assert any("does not define" in p for p in problems), problems


def test_a_pointer_to_a_missing_file_is_refused():
    problems = _problems(_claim(evidence=["test:engine/tests/test_nope.py::test_x"]))
    assert any("no such file" in p for p in problems), problems


def test_an_unresolvable_eval_pointer_is_refused():
    problems = _problems(_claim(evidence=["eval:Z9-not-a-task"]))
    assert any("no such eval task" in p for p in problems), problems


def test_a_doc_pointer_to_an_absent_heading_is_refused():
    problems = _problems(_claim(
        evidence=["doc:docs/trouble-table.md#no such heading exists here"]))
    assert any("has no heading text" in p for p in problems), problems


def test_a_probe_pointer_the_prober_never_emits_is_refused():
    problems = _problems(_claim(evidence=["probe:imaginary_backend"]))
    assert any("emits no capability" in p for p in problems), problems


def test_an_unknown_pointer_kind_is_refused():
    problems = _problems(_claim(evidence=["screenshot:looks-fine.png"]))
    assert any("unknown pointer kind" in p for p in problems), problems


def test_a_status_outside_the_vocabulary_is_refused():
    problems = _problems(_claim(status="mostly-works", reason="r"))
    assert any("not in" in p for p in problems), problems


def test_a_key_the_generator_never_reads_is_refused():
    """T120's lesson: a field nobody reads is an assertion that does nothing."""
    problems = _problems(_claim(confidence="high"))
    assert any("silently dead" in p for p in problems), problems


def test_a_duplicate_id_is_refused():
    problems = _problems(_claim(), _claim())
    assert any("duplicate id" in p for p in problems), problems


# ---------------------------------------------------------------------------
# coverage — derived, so a new module cannot go unclassified
# ---------------------------------------------------------------------------

def test_an_uncovered_module_is_refused(tmp_path):
    """The hardcoded-count defect class: a new module must announce itself."""
    problems = sm.validate([_claim(
        covers=[f"eval:{t}" for t in sm.shipped_tasks()])])
    assert any("no claim covers 'module:" in p for p in problems), problems


def test_an_uncovered_eval_task_is_refused():
    problems = sm.validate([_claim(
        covers=[f"module:{m}" for m in sm.installed_modules()])])
    assert any("no claim covers 'eval:" in p for p in problems), problems


def test_coverage_sets_are_derived_not_listed():
    """If these were hardcoded, adding a module would not change them."""
    assert sm.installed_modules() == sorted(
        p.name for p in (REPO_ROOT / "modules").iterdir()
        if p.is_dir() and (p / "scripts").is_dir())
    assert sm.shipped_tasks() == sorted(
        p.stem for p in (REPO_ROOT / "evals" / "tasks").glob("*.yaml"))


def test_the_readme_points_at_the_matrix_and_states_the_open_limits():
    """A limit stated only in a generated table is a limit users will not read.

    The product's own status section has to carry the pointer and the two limits
    that are not closable in this tree, or "every remaining limit stated" is true
    of an internal log and false of the product.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/support-matrix.md" in readme
    assert "per-task run record" in readme
    assert "unverified across lanes" in readme


def test_probe_keys_come_from_the_prober(tmp_path):
    keys = sm.probe_capability_keys()
    assert {"hancom_com", "soffice_path", "rhwp_path"} <= keys, sorted(keys)
    empty = tmp_path / "render_probe.py"
    empty.write_text("capabilities = {}\n", encoding="utf-8")
    with pytest.raises(sm.SupportMatrixError, match="no capabilities dict"):
        sm.probe_capability_keys(empty)
