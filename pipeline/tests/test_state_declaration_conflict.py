# -*- coding: utf-8 -*-
"""T103: a declared --mode that disagrees with the evidence says so.

Every work-type checker derives a document state and then lets ``--mode`` force
it. All four recorded the override in ``state_used`` and none ever said the two
DISAGREED, so the conflict was visible only to a reader who thought to compare
two sibling keys — while ``document.state`` is the obvious one to read.

The teeth: declaring ``final`` on a document the checker reads as ``blank``
makes the "you left the form's own guidance in the packet" rules fire, and
declaring ``blank`` on a filled one suppresses them. Measured on the untouched
kstartup blank form, ``--mode final`` produced two HARD findings while
``document.state`` still read ``blank``.

Not HARD: a declaration disagreeing with the evidence is not a defect of the
document, and an operator legitimately knows the intended state before the
seats are filled.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checker_base  # noqa: E402


def _classified(state="blank", basis="date_seat_only"):
    return {"state": state, "state_basis": basis}


def test_auto_trusts_the_derived_state_and_reports_no_conflict():
    classification = _classified()
    conflict = checker_base.resolve_state(classification, "auto")
    assert conflict is None
    assert classification["state_used"] == "blank"
    assert classification["mode"] == "auto"
    assert "state_declaration_conflict" not in classification


def test_a_mode_matching_the_derived_state_is_not_a_conflict():
    """Declaring what the evidence already says is agreement, not noise."""
    classification = _classified(state="final")
    assert checker_base.resolve_state(classification, "final") is None
    assert classification["state_used"] == "final"


def test_final_declared_over_a_blank_document_is_reported():
    """The measured case: this is the combination that fires residue rules."""
    classification = _classified()
    conflict = checker_base.resolve_state(classification, "final")
    assert conflict is not None
    assert conflict["code"] == "document_state_declared_against_evidence"
    assert conflict["declared_mode"] == "final"
    assert conflict["derived_state"] == "blank"
    assert conflict["state_basis"] == "date_seat_only"
    assert classification["state_declaration_conflict"] is True
    # The declared value still governs — the report does not change behaviour.
    assert classification["state_used"] == "final"


def test_blank_declared_over_a_filled_document_is_reported_too():
    """The suppressing direction matters as much as the accusing one.

    Declaring ``blank`` on a document that reads as ``final`` silences the
    rules that would have judged it, which is the quieter and more dangerous
    of the two mistakes.
    """
    classification = _classified(state="final", basis="seats_changed")
    conflict = checker_base.resolve_state(classification, "blank")
    assert conflict is not None
    assert conflict["declared_mode"] == "blank"
    assert conflict["derived_state"] == "final"
    assert classification["state_used"] == "blank"


def test_the_message_names_both_values_and_the_basis():
    """A reader must not have to cross-reference to understand the row."""
    conflict = checker_base.resolve_state(_classified(), "final")
    message = conflict["msg"]
    assert "final" in message and "blank" in message
    assert "date_seat_only" in message


def test_a_missing_basis_does_not_break_the_message():
    classification = {"state": "draft"}
    conflict = checker_base.resolve_state(classification, "final")
    assert conflict is not None
    assert "no basis" in conflict["msg"]
