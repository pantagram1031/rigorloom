# -*- coding: utf-8 -*-
"""Candidate lineage, reads on a candidate, and the proof an undo is an inverse.

E1.4. Three properties, and the first one is a DEFECT this file exists to keep
closed:

1. **Two applies in a row must not lose the first edit.** Before lineage every
   apply chained from ``session.source``, so a second candidate was a sibling of
   the first, not a child — the second one silently did not carry the first
   edit, and exporting it lost approved work. A plan computed against
   anything older than the newest candidate is now refused with
   ``plan_behind_head`` (``test_a_plan_behind_the_head_cannot_be_approved_or_
   applied``), and the base-run tests pin the fix.

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


def test_a_plan_behind_the_head_cannot_be_approved_or_applied(tmp_path):
    """The defect this file exists for, now refused rather than pinned.

    A plan that names no base is computed against the SOURCE. Once a candidate
    exists, applying it would publish a file without that candidate's edit —
    the review called this "an outdated proposal overwrites 수정본 1". The
    runtime now says so: validation carries the hard finding
    ``plan_behind_head``, approving is refused with the same code, and
    returning it stays possible.
    """
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        _, first = _apply(client, session, FIRST)
        plan = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                          "ops": SECOND})["plan"]
        validation = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
        assert validation["ok"] is False
        behind = [row for row in validation["hard"] if row["code"] == "plan_behind_head"]
        assert len(behind) == 1, validation["hard"]
        assert behind[0]["baseRunId"] is None
        assert behind[0]["headRunId"] == first["runId"]

        approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
        refused = client.err("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": plan["planId"],
            "planHash": plan["planHash"], "decision": "approved",
            "approver": "test-operator"})
        assert refused["code"] == "plan_behind_head", refused
        assert refused["data"]["headRunId"] == first["runId"]

        returned = client.ok("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": plan["planId"],
            "planHash": plan["planHash"], "decision": "rejected",
            "approver": "test-operator", "reason": "수신을 고쳐 주세요"})["approval"]
        assert returned["state"] == "rejected"
        # The reason is the reason; who decided stays who decided.
        assert returned["reason"] == "수신을 고쳐 주세요"
        assert returned["approver"] == "test-operator"

        # The same ops on the head are fine.
        _, second = _apply(client, session, SECOND, base=first["runId"])
        one, _ = _text(client, session, CELL, run_id=second["runId"])
        assert one == "처음", "a head-based second apply carries edit one"


def test_an_approved_plan_behind_the_head_is_refused_at_apply(tmp_path):
    """Approved before the head moved, applied after: still refused."""
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        late = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                          "ops": SECOND})["plan"]
        late_approval = client.ok("approval/request",
                                  {"planId": late["planId"]})["approval"]
        client.ok("approval/resolve", {
            "approvalId": late_approval["approvalId"], "planId": late["planId"],
            "planHash": late["planHash"], "decision": "approved",
            "approver": "test-operator"})
        _apply(client, session, FIRST)
        refused = client.err("plan/apply", {"planId": late["planId"],
                                            "approvalId": late_approval["approvalId"]})
        assert refused["code"] == "plan_behind_head", refused
        assert len(client.ok("candidate/list", {"sessionId": session})["candidates"]) == 1


def test_applying_a_plan_returns_other_pending_approvals_as_superseded(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        waiting = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                             "ops": SECOND})["plan"]
        waiting_approval = client.ok("approval/request",
                                     {"planId": waiting["planId"]})["approval"]
        _, first = _apply(client, session, FIRST)

        record = client.ok("approval/get",
                           {"approvalId": waiting_approval["approvalId"]})["approval"]
        assert record["state"] == "rejected"
        assert record["decision"] == "rejected"
        assert record["reasonCode"] == "superseded_by_newer_candidate"
        assert record["supersededBy"] == first["runId"]
        # Nobody approved anything on anyone's behalf.
        assert record["approver"] is None
        events = client.ok("event/poll", {"sessionId": session, "after": -1})["events"]
        superseded = [ev for ev in events if ev["kind"] == "approval.resolved"
                      and (ev.get("detail") or {}).get("reasonCode") == "superseded_by_newer_candidate"]
        assert len(superseded) == 1, events


def test_a_plan_from_a_person_carries_no_provenance(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        plan, candidate = _apply(client, session, FIRST)
        assert "provenance" not in plan
        receipt = client.ok("receipt/read", {"sessionId": session,
                                             "runId": candidate["runId"]})["receipt"]
        assert receipt["provenance"] is None
        assert receipt["proposer"] == plan["proposer"]


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


# --- T2: explicit replacement, provenance, complete proofs --------------------

def _events(client, session):
    return client.ok("event/poll", {"sessionId": session, "after": -1})["events"]


def test_an_explicit_replacement_revokes_the_replaced_plans_approval(tmp_path):
    """Re-proposing a queued plan as a replacement retires its open approval.

    Before, only the client forgot the old approval; the runtime still held a
    usable one for a plan on the same base.
    """
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        old = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                         "ops": FIRST})["plan"]
        pending = client.ok("approval/request", {"planId": old["planId"]})["approval"]
        answer = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                            "ops": FIRST + SECOND,
                                            "replaces": old["planId"]})
        new = answer["plan"]
        assert answer["replaced"]["planId"] == old["planId"]
        assert answer["replaced"]["revokedApprovals"] == [pending["approvalId"]]

        record = client.ok("approval/get", {"approvalId": pending["approvalId"]})["approval"]
        assert record["state"] == "rejected"
        assert record["reasonCode"] == "superseded_by_newer_candidate"
        assert record["supersededBy"] == new["planId"]
        assert record["approver"] is None
        refused = client.err("approval/resolve", {
            "approvalId": pending["approvalId"], "planId": old["planId"],
            "planHash": old["planHash"], "decision": "approved",
            "approver": "test-operator"})
        assert refused["code"] == "approval_already_resolved", refused
        events = [ev for ev in _events(client, session)
                  if ev["kind"] == "approval.resolved"
                  and (ev.get("detail") or {}).get("approvalId") == pending["approvalId"]]
        assert len(events) == 1
        assert events[0]["detail"]["supersededBy"] == new["planId"]


def test_a_replaced_plan_that_was_already_approved_cannot_be_applied(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        session = _open(client, tmp_path)
        old = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                         "ops": FIRST})["plan"]
        approval = client.ok("approval/request", {"planId": old["planId"]})["approval"]
        client.ok("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": old["planId"],
            "planHash": old["planHash"], "decision": "approved",
            "approver": "test-operator"})
        client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                   "ops": SECOND, "replaces": old["planId"]})
        record = client.ok("approval/get", {"approvalId": approval["approvalId"]})["approval"]
        assert record["state"] == "rejected"
        assert record["revokedFrom"] == "approved"
        refused = client.err("plan/apply", {"planId": old["planId"],
                                            "approvalId": approval["approvalId"]})
        assert refused["code"] == "plan_not_approved", refused
        assert client.ok("candidate/list", {"sessionId": session})["candidates"] == []


def test_a_caller_label_cannot_set_or_clear_test_provenance(tmp_path):
    """Provenance is the launched provider's identity, not ``proposer``.

    A host caller naming itself after a test agent gets no mock label; a
    runtime launched for the test agent marks its plans mock whatever they
    call themselves; and a client that rebuilds a test value and re-proposes
    it keeps the label all the way to the receipt.
    """
    import mock_agent

    root = tmp_path / "root"
    with RuntimeClient(root) as client:
        session = _open(client, tmp_path)
        posing = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                            "ops": SECOND,
                                            "proposer": "agenthost-mock"})["plan"]
        assert "provenance" not in posing

        with mock_agent.open_door("protocol", root, None, identity="mock") as door:
            agent_plan = door.call("plan/propose", {
                "sessionId": session, "backend": "preedit",
                "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1,
                         "text": "시험값"}],
                "proposer": "rigorloom-desktop"})["plan"]
        assert agent_plan["provenance"] == "mock"

        # The desktop rebuilds the queue: new op id, ``lines`` instead of
        # ``text``, one more op of its own. Still a test value.
        rebuilt = [{"opId": "u-1", "kind": "fill_cell", "table": 0, "row": 5,
                    "col": 1, "lines": ["시험값"]}] + SECOND
        plan, candidate = _apply(client, session, rebuilt)
        assert plan["provenance"] == "mock"
        receipt = client.ok("receipt/read", {"sessionId": session,
                                             "runId": candidate["runId"]})["receipt"]
        assert receipt["provenance"] == "mock"
        rows = client.ok("candidate/list", {"sessionId": session})["candidates"]
        assert rows[-1]["provenance"] == "mock"


def test_a_proof_needs_every_requested_region_to_be_readable(tmp_path, monkeypatch):
    """One region the profile did not return: the answer is "not proven".

    ``regionsEqual`` used to be computed over the readable subset, so an undo
    touching two cells could be reported equal when only one was read.
    """
    import rt_core

    root = tmp_path / "root"
    other = {"table": 0, "row": 5, "col": 2}
    with RuntimeClient(root) as client:
        session = _open(client, tmp_path)
        _, edit = _apply(client, session, FIRST)
    real = rt_core._text_by_spec

    def drops_one(profile):
        out = real(profile)
        out.pop("0:5,2", None)
        return out

    monkeypatch.setattr(rt_core, "_text_by_spec", drops_one)
    proof = rt_core.RuntimeCore(root).candidate_compare(
        session, edit["runId"], against={"runId": edit["runId"]},
        regions=[CELL, other])
    assert proof["regionsCompared"] == 1
    assert proof["regionsUnreadable"] == ["0:5,2"]
    assert proof["regionsEqual"] is None
