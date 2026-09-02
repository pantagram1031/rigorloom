# -*- coding: utf-8 -*-
"""Candidate lineage, reads on a candidate, and the proof an undo is an inverse.

E1.4. Three properties, and the first one is a DEFECT this file exists to keep
closed:

1. **Two applies in a row must not lose the first edit.** Before lineage every
   apply chained from ``session.source``, so a second candidate was a sibling of
   the first, not a child — the second one silently did not carry the first
   edit, and exporting it lost approved work. ``test_a_second_apply_without_a_
   base_drops_the_first_edit`` pins that behaviour where it is still correct
   (an explicitly source-based plan), and the base-run tests pin the fix.

2. **The value an undo restores is READ, not remembered.**
   ``document/readRegion`` with a ``runId`` answers out of a published
   candidate, so a client can derive the previous value from the chain.

3. **A reversal is proven by the runtime.** ``candidate/compare`` re-reads both
   documents from receipt-verified bytes and reports per-address equality. The
   whole-file digests are reported too, and are expected NOT to match — an
   edit and its inverse restore the text, not the zip.

Real corpus form, real ``preedit`` children, no fixtures of edited XML.
"""
from __future__ import annotations

import shutil

from _runtime_client import CORPUS_FORM, RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

CELL = {"table": 0, "row": 5, "col": 1}
FIRST = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "처음"}]
SECOND = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 2, "text": "다음"}]


def _source(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _apply(client, session, ops, *, base=None, reverses=None):
    """propose -> validate -> request -> approve -> apply. Returns the result."""
    params = {"sessionId": session, "backend": "preedit", "ops": ops}
    if base is not None:
        params["baseRunId"] = base
    if reverses is not None:
        params["reverses"] = {"runId": reverses}
    plan = client.ok("plan/propose", params)["plan"]
    validation = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert validation["ok"] is True, validation["hard"]
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    client.ok("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "approved",
        "approver": "test-operator"})
    result = client.ok("plan/apply", {"planId": plan["planId"],
                                      "approvalId": approval["approvalId"]})
    return plan, result["candidate"]


def _open(client, tmp_path):
    client.initialize()
    source = _source(tmp_path)
    return client.ok("workspace/openPath", {"path": str(source)})["sessionId"]


def _text(client, session, region, run_id=None):
    params = {"sessionId": session, "regions": [region]}
    if run_id is not None:
        params["runId"] = run_id
    answer = client.ok("document/readRegion", params)
    return answer["regions"][0]["text"], answer["subject"]


# --- lineage ----------------------------------------------------------------

def test_a_base_less_plan_records_a_null_base(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        plan, candidate = _apply(client, session, FIRST)
        assert plan["base"] is None
        assert plan["reverses"] is None
        receipt = client.ok("receipt/read", {"sessionId": session,
                                             "runId": candidate["runId"]})["receipt"]
        assert receipt["base"] is None
        assert receipt["reverses"] is None


def test_a_second_apply_without_a_base_drops_the_first_edit(tmp_path):
    """The pre-lineage behaviour, pinned where it is still what was asked for.

    A plan that names no base is computed against the SOURCE and applied to the
    source, so its candidate carries its own ops and nothing else. That is
    correct and it is also why `baseRunId` had to exist: a client that just
    kept editing got this silently.
    """
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        _, second = _apply(client, session, SECOND)
        text, subject = _text(client, session, CELL, run_id=second["runId"])
        assert subject["kind"] == "candidate"
        assert text != "처음", "a source-based second apply must not carry edit one"


def test_a_based_plan_chains_onto_the_candidate(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        plan, second = _apply(client, session, SECOND, base=first["runId"])

        assert plan["base"] == {"runId": first["runId"],
                                "sha256": first["candidate"]["sha256"]}
        # The plan binds the CANDIDATE's bytes, not the source's.
        assert plan["boundSha256"] == first["candidate"]["sha256"]
        assert second["base"]["runId"] == first["runId"]

        # Both edits are in the second candidate. This is the defect closed.
        one, _ = _text(client, session, CELL, run_id=second["runId"])
        two, _ = _text(client, session, {"table": 0, "row": 5, "col": 2},
                       run_id=second["runId"])
        assert one == "처음"
        assert two == "다음"


def test_candidate_list_carries_the_lineage_oldest_first(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        _, second = _apply(client, session, SECOND, base=first["runId"])
        rows = client.ok("candidate/list", {"sessionId": session})["candidates"]
        assert [row["runId"] for row in rows] == [first["runId"], second["runId"]]
        assert rows[0]["base"] is None
        assert rows[1]["base"]["runId"] == first["runId"]
        assert rows[0]["sha256"] == first["candidate"]["sha256"]
        # A listing does not re-hash the artifact and never claims it did.
        assert all(row["verified"] is False for row in rows)


def test_an_unknown_base_is_refused_before_a_plan_exists(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        error = client.err("plan/propose", {
            "sessionId": session, "backend": "preedit", "ops": FIRST,
            "baseRunId": "0" * 32})
        assert error["code"] == "artifact_missing"


def test_a_base_that_escapes_the_session_is_refused(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        error = client.err("plan/propose", {
            "sessionId": session, "backend": "preedit", "ops": FIRST,
            "baseRunId": "../../etc"})
        assert error["code"] == "invalid_params"


# --- reading a candidate ------------------------------------------------------

def test_read_region_says_which_document_answered(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        before, source_subject = _text(client, session, CELL)
        after, candidate_subject = _text(client, session, CELL,
                                         run_id=first["runId"])
        assert source_subject["kind"] == "session_source"
        assert candidate_subject == {"kind": "candidate",
                                     "runId": first["runId"],
                                     "sha256": first["candidate"]["sha256"]}
        assert after == "처음"
        assert before != after


# --- the inverse, and its proof -----------------------------------------------

def test_an_inverse_restores_the_value_and_the_runtime_proves_it(tmp_path):
    """Edit, then undo by proposing the inverse ON TOP of the edit.

    Nothing is deleted: the undo is a third document in the chain, and what
    makes it an undo is that `candidate/compare` finds the address equal to the
    pre-edit document.
    """
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        before, _ = _text(client, session, CELL)

        _, edit = _apply(client, session, FIRST)
        assert _text(client, session, CELL, run_id=edit["runId"])[0] == "처음"

        # The inverse: the SAME address, the value read back off the chain.
        inverse_ops = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1,
                        "text": before, "overwrite": True}]
        plan, undo = _apply(client, session, inverse_ops,
                            base=edit["runId"], reverses=edit["runId"])

        assert plan["reverses"]["runId"] == edit["runId"]
        receipt = client.ok("receipt/read", {"sessionId": session,
                                             "runId": undo["runId"]})["receipt"]
        assert receipt["reverses"]["runId"] == edit["runId"]
        assert receipt["base"]["runId"] == edit["runId"]

        proof = client.ok("candidate/compare", {
            "sessionId": session, "runId": undo["runId"],
            "against": {"source": True}, "regions": [CELL]})
        assert proof["regionsCompared"] == 1
        assert proof["regionsEqual"] is True
        assert proof["regions"][0]["left"] == proof["regions"][0]["right"] == before
        assert proof["right"]["kind"] == "session_source"
        # Text restored, bytes not: preedit rewrites and rezips the package.
        # Reported rather than hidden, and never read as a failed undo.
        assert proof["artifactEqual"] is False


def test_compare_reports_a_difference_as_a_difference(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, edit = _apply(client, session, FIRST)
        proof = client.ok("candidate/compare", {
            "sessionId": session, "runId": edit["runId"],
            "against": {"source": True}, "regions": [CELL]})
        assert proof["regionsEqual"] is False
        assert proof["regions"][0]["left"] == "처음"


def test_compare_between_two_candidates_names_both_sides(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        _, second = _apply(client, session, SECOND, base=first["runId"])
        proof = client.ok("candidate/compare", {
            "sessionId": session, "runId": second["runId"],
            "against": {"runId": first["runId"]}, "regions": [CELL]})
        assert proof["left"]["runId"] == second["runId"]
        assert proof["right"]["runId"] == first["runId"]
        # The chained edit touched a different cell, so this one is untouched.
        assert proof["regionsEqual"] is True


def test_compare_without_regions_compares_digests_only(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, edit = _apply(client, session, FIRST)
        proof = client.ok("candidate/compare", {"sessionId": session,
                                                "runId": edit["runId"]})
        assert proof["regions"] == []
        assert proof["regionsCompared"] == 0
        # No address was compared, so the answer is "not known", never True.
        assert proof["regionsEqual"] is None
        assert proof["artifactEqual"] is False


def test_compare_is_agent_safe_and_apply_is_not(tmp_path):
    """The authority line: an agent may check a reversal, never publish one."""
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, edit = _apply(client, session, FIRST)
    with RuntimeClient(tmp_path / "root", entry="agent") as agent:
        agent.initialize()
        proof = agent.ok("candidate/compare", {"sessionId": session,
                                               "runId": edit["runId"]})
        assert proof["left"]["runId"] == edit["runId"]
        error = agent.err("plan/apply", {"planId": "x", "approvalId": "y"})
        assert error["code"] == "unknown_method"
        assert error["data"]["knownOnHostEntry"] is True
