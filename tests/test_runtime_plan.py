# -*- coding: utf-8 -*-
"""Plan class: backend declaration, validation, staleness, approval binding."""
from __future__ import annotations

import shutil

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

CLEAN_OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "값"}
#: (2,0) carries script_anomaly with charpr_suggested 23 in this form — the T30
#: case ``engine/scripts/preedit.py:136`` refuses at apply.
ANOMALOUS_OP = {"kind": "fill_cell", "table": 0, "row": 2, "col": 0, "text": "X"}


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def client(tmp_path):
    with RuntimeClient(tmp_path / "root") as handle:
        yield handle


@pytest.fixture()
def session(client, source):
    client.initialize()
    return client.ok("workspace/openPath", {"path": str(source)})["sessionId"]


def _flip_last_byte(tmp_path, session):
    """Change the session's source copy so a bound plan goes stale."""
    copy = next((tmp_path / "root" / "sessions" / session / "source").iterdir())
    data = bytearray(copy.read_bytes())
    data[-1] = (data[-1] + 1) % 256
    copy.write_bytes(bytes(data))


def _propose(client, session, ops):
    return client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                      "ops": ops})["plan"]


# --- backend declaration (D9) ----------------------------------------------

def test_a_plan_carries_its_backend_and_a_hash_over_its_body(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    assert plan["backend"] == "preedit"
    assert plan["schema"] == "rigorloom/runtime-plan/v0"
    assert len(plan["planHash"]) == 64
    assert plan["ops"][0]["opId"] == "op-1"
    assert plan["state"] == "proposed"


def test_the_plan_hash_covers_the_ops(client, session):
    first = _propose(client, session, [CLEAN_OP])
    second = _propose(client, session, [dict(CLEAN_OP, text="다른값")])
    assert first["planHash"] != second["planHash"]


@pytest.mark.parametrize("backend", ["xml", "com"])
def test_a_declared_but_unserved_backend_is_refused_by_name(client, session, backend):
    error = client.err("plan/propose", {"sessionId": session, "backend": backend,
                                        "ops": [CLEAN_OP]})
    assert error["code"] == "unsupported_backend"
    assert error["data"]["declared"] == backend
    assert error["data"]["supported"] == ["preedit"]


def test_an_unknown_backend_is_refused(client, session):
    error = client.err("plan/propose", {"sessionId": session, "backend": "quill",
                                        "ops": [CLEAN_OP]})
    assert error["code"] == "unsupported_backend"
    assert error["data"]["known"] == ["preedit", "xml", "com"]


def test_a_foreign_op_kind_names_the_backend_that_would_serve_it(client, session):
    error = client.err("plan/propose", {
        "sessionId": session, "backend": "preedit",
        "ops": [{"kind": "insert_equation", "latex": "E=mc^2"}]})
    assert error["code"] == "unsupported_backend"
    assert error["data"]["servedBy"] == "xml or com"


def test_a_com_only_op_kind_names_com(client, session):
    error = client.err("plan/propose", {
        "sessionId": session, "backend": "preedit",
        "ops": [{"kind": "insert_hyperlink", "url": "x"}]})
    assert error["data"]["servedBy"] == "com"


def test_an_unknown_op_kind_lists_the_known_ones(client, session):
    error = client.err("plan/propose", {"sessionId": session, "backend": "preedit",
                                        "ops": [{"kind": "levitate"}]})
    assert error["code"] == "unknown_op_kind"
    assert error["data"]["knownKinds"] == ["delete_guides", "fill_cell",
                                           "replace_at_cell", "set_run"]
    assert error["data"]["notImplemented"] == ["normalize_clones"]


def test_unknown_op_fields_are_refused(client, session):
    error = client.err("plan/propose", {
        "sessionId": session, "backend": "preedit",
        "ops": [dict(CLEAN_OP, sneaky=1)]})
    assert error["code"] == "unknown_field"
    assert error["data"]["unknown"] == ["sneaky"]


def test_duplicate_op_ids_are_refused(client, session):
    error = client.err("plan/propose", {
        "sessionId": session, "backend": "preedit",
        "ops": [dict(CLEAN_OP, opId="a"), dict(CLEAN_OP, opId="a", col=2)]})
    assert error["code"] == "invalid_params"


def test_an_empty_plan_is_refused(client, session):
    assert client.err("plan/propose", {"sessionId": session, "backend": "preedit",
                                       "ops": []})["code"] == "invalid_params"


# --- validation -------------------------------------------------------------

def test_a_clean_plan_validates(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert report["ok"] is True and report["verdict"] == "pass"
    assert report["stale"] is False
    assert report["preflight"]["level"] == "structural+profile"
    assert "replace_key_ambiguous" in report["preflight"]["deferred"]


def test_validation_reproduces_the_t30_refusal_from_the_profile(client, session):
    """Same code name preedit emits (engine/scripts/preedit.py:2715)."""
    plan = _propose(client, session, [ANOMALOUS_OP])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert report["ok"] is False
    codes = [row["code"] for row in report["hard"]]
    assert "fill_charpr_script_anomaly" in codes
    row = next(r for r in report["hard"] if r["code"] == "fill_charpr_script_anomaly")
    assert row["charPrSuggested"] == "23"
    assert row["preeditFlag"] == ["--charpr-per-cell", "2,0=23"]


def test_declaring_the_suggested_charpr_clears_the_t30_finding(client, session):
    plan = _propose(client, session, [dict(ANOMALOUS_OP, charPr="23")])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert report["ok"] is True


def test_an_unknown_cell_address_is_a_finding_not_a_crash(client, session):
    plan = _propose(client, session, [{"kind": "fill_cell", "table": 0,
                                       "row": 999, "col": 999, "text": "x"}])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert [row["code"] for row in report["hard"]] == ["cell_address_unknown"]


def test_delete_guides_without_a_selector_is_refused(client, session):
    plan = _propose(client, session, [{"kind": "delete_guides"}])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert [row["code"] for row in report["hard"]] == ["op_field_invalid"]


def test_fill_cell_needs_exactly_one_of_text_or_lines(client, session):
    plan = _propose(client, session, [{"kind": "fill_cell", "table": 0, "row": 5,
                                       "col": 1, "text": "a", "lines": ["b"]}])
    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert "op_field_invalid" in [row["code"] for row in report["hard"]]


def test_an_unknown_plan_id_is_refused(client, session):
    assert client.err("plan/validate", {"planId": "nope"})["code"] == "unknown_plan"


# --- staleness --------------------------------------------------------------

def test_a_plan_goes_stale_when_the_session_source_changes(client, session, tmp_path):
    plan = _propose(client, session, [CLEAN_OP])
    assert client.ok("plan/validate",
                     {"planId": plan["planId"]})["validation"]["stale"] is False

    # Mutate the session's own copy behind the Runtime's back — the drift a
    # bound plan exists to notice.
    _flip_last_byte(tmp_path, session)

    report = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert report["stale"] is True
    assert report["ok"] is False
    assert "plan_stale" in [row["code"] for row in report["hard"]]
    assert report["boundSha256"] != report["currentSha256"]


def test_a_stale_plan_cannot_be_approved(client, session, tmp_path):
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    _flip_last_byte(tmp_path, session)
    error = client.err("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "approved"})
    assert error["code"] == "plan_stale"


# --- approvals --------------------------------------------------------------

def test_an_approval_binds_the_exact_plan_id_and_hash(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    assert approval["state"] == "pending"
    assert approval["planHash"] == plan["planHash"]
    assert approval["decision"] is None


def test_approving_a_different_plan_hash_is_refused(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    error = client.err("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": "0" * 64, "decision": "approved"})
    assert error["code"] == "approval_binding_mismatch"
    assert error["data"]["boundPlanHash"] == plan["planHash"]


def test_approving_a_different_plan_id_is_refused(client, session):
    first = _propose(client, session, [CLEAN_OP])
    second = _propose(client, session, [dict(CLEAN_OP, text="다른값")])
    approval = client.ok("approval/request", {"planId": first["planId"]})["approval"]
    error = client.err("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": second["planId"],
        "planHash": second["planHash"], "decision": "approved"})
    assert error["code"] == "approval_binding_mismatch"


def test_an_approval_resolves_only_once(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    args = {"approvalId": approval["approvalId"], "planId": plan["planId"],
            "planHash": plan["planHash"], "decision": "approved"}
    client.ok("approval/resolve", args)
    error = client.err("approval/resolve", args)
    assert error["code"] == "approval_already_resolved"


def test_auto_approved_cannot_be_declared_by_a_client(client, session):
    """The Runtime never fabricates approval (pipeline_ctl.py:1159's rule)."""
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    error = client.err("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "auto_approved"})
    assert error["code"] == "invalid_params"


def test_a_rejected_plan_cannot_be_applied(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    client.ok("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "rejected"})
    error = client.err("plan/apply", {"planId": plan["planId"],
                                      "approvalId": approval["approvalId"]})
    assert error["code"] == "plan_not_approved"
    assert error["data"]["state"] == "rejected"


def test_applying_without_any_approval_is_refused(client, session):
    plan = _propose(client, session, [CLEAN_OP])
    error = client.err("plan/apply", {"planId": plan["planId"],
                                      "approvalId": "nope"})
    assert error["code"] == "unknown_approval"


def test_an_approval_for_another_plan_cannot_apply_this_one(client, session):
    first = _propose(client, session, [CLEAN_OP])
    second = _propose(client, session, [dict(CLEAN_OP, text="다른값")])
    approval = client.ok("approval/request", {"planId": first["planId"]})["approval"]
    client.ok("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": first["planId"],
        "planHash": first["planHash"], "decision": "approved"})
    error = client.err("plan/apply", {"planId": second["planId"],
                                      "approvalId": approval["approvalId"]})
    assert error["code"] == "approval_binding_mismatch"
