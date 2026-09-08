"""Real document retries across requests, server restarts, and interrupted commits."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from _runtime_client import RuntimeClient, runtime_scripts_on_path
from test_runtime_apply import _source, _sha256, drive, OPS_ONE

runtime_scripts_on_path()
from rt_core import RuntimeCore
from rt_codes import RpcError


def prepared(tmp_path):
    source = _source(tmp_path)
    root = tmp_path / "root"
    with RuntimeClient(root) as client:
        session, plan, approval = drive(client, source, OPS_ONE)
    return root, source, session, {"planId": plan["planId"], "approvalId": approval["approvalId"]}


def test_retry_revalidate_and_restart_reuse_one_verified_candidate(tmp_path):
    root, source, session, params = prepared(tmp_path)
    before = _sha256(source)
    with RuntimeClient(root) as client:
        client.initialize()
        first = client.ok("plan/apply", params)
        client.ok("plan/validate", {"planId": params["planId"]})
        assert client.ok("plan/apply", params) == first
    with RuntimeClient(root) as client:
        client.initialize()
        assert client.ok("plan/apply", params) == first
        assert len(client.ok("candidate/list", {"sessionId": session})["candidates"]) == 1
    assert _sha256(source) == before


def test_two_host_processes_cannot_publish_duplicate_candidates(tmp_path):
    root, source, session, params = prepared(tmp_path)
    with RuntimeClient(root) as a, RuntimeClient(root) as b:
        a.initialize()
        b.initialize()
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda c: c.call("plan/apply", params), [a, b]))
        successes = [r["result"] for r in replies if "result" in r]
        assert successes
        for r in replies:
            if "error" in r:
                assert r["error"]["code"] == "apply_in_progress"
        assert a.ok("plan/apply", params) == successes[0]
        assert len(a.ok("candidate/list", {"sessionId": session})["candidates"]) == 1


def test_receipt_recovers_publication_before_plan_state_save(tmp_path, monkeypatch):
    root, source, session, params = prepared(tmp_path)
    core = RuntimeCore(root)
    def interrupted(plan):
        raise OSError("simulated process interruption after receipt publication")
    monkeypatch.setattr(core, "save_plan", interrupted)
    with pytest.raises(OSError):
        core.plan_apply(params["planId"], params["approvalId"])
    recovered_core = RuntimeCore(root)
    recovered = recovered_core.plan_apply(params["planId"], params["approvalId"])
    assert recovered_core.plan(params["planId"]).state == "applied"
    with RuntimeClient(root) as client:
        client.initialize()
        rows = client.ok("candidate/list", {"sessionId": session})["candidates"]
        assert [r["runId"] for r in rows] == [recovered["candidate"]["runId"]]


def test_uncertain_attempt_without_receipt_cannot_be_reexecuted(tmp_path, monkeypatch):
    import rt_core
    root, source, session, params = prepared(tmp_path)
    def interrupted(*args, **kwargs):
        raise SystemExit("simulated crash before receipt")
    monkeypatch.setattr(rt_core, "apply_plan", interrupted)
    with pytest.raises(SystemExit):
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    monkeypatch.undo()
    with pytest.raises(RpcError) as error:
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    assert error.value.code == "apply_outcome_unknown"


def test_retry_reverifies_bytes_and_never_replaces_tampered_candidate(tmp_path):
    root, source, session, params = prepared(tmp_path)
    core = RuntimeCore(root)
    candidate = core.plan_apply(params["planId"], params["approvalId"])["candidate"]
    artifact = root / "sessions" / session / "candidates" / candidate["runId"] / candidate["candidate"]["path"]
    artifact.write_bytes(b"tampered")
    with pytest.raises(RpcError) as error:
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    assert error.value.code == "candidate_hash_mismatch"
    assert list(artifact.parent.parent.iterdir()) == [artifact.parent]


def test_legacy_candidate_without_a_journal_is_replayed(tmp_path):
    root, source, session, params = prepared(tmp_path)
    first = RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    # Model a publication by the pre-journal runtime in this test-owned root.
    (root / "apply-attempts" / f"{params['planId']}.json").unlink()
    assert RuntimeCore(root).plan_apply(params["planId"], params["approvalId"]) == first


def test_corrupt_journal_blocks_execution(tmp_path):
    root, source, session, params = prepared(tmp_path)
    journals = root / "apply-attempts"
    journals.mkdir(exist_ok=True)
    (journals / f"{params['planId']}.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(RpcError) as error:
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    assert error.value.code == "apply_outcome_unknown"


def test_handled_prepublication_refusal_can_retry(tmp_path, monkeypatch):
    import rt_core
    root, source, session, params = prepared(tmp_path)
    def refuse(*args, **kwargs):
        raise RpcError("plan_invalid", "test prepublication refusal")
    monkeypatch.setattr(rt_core, "apply_plan", refuse)
    with pytest.raises(RpcError):
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    monkeypatch.undo()
    result = RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    assert result["candidate"]["canonical"]


def test_os_lock_blocks_another_host_and_releases_after_process_death(tmp_path):
    import subprocess
    import sys
    from _runtime_client import RUNTIME_SCRIPTS
    root, source, session, params = prepared(tmp_path)
    script = ("import sys,time; from pathlib import Path; "
              "from rt_apply_once import plan_lock; "
              "lock=plan_lock(Path(sys.argv[1]),sys.argv[2]); "
              "lock.__enter__(); print('locked',flush=True); time.sleep(90)")
    child = subprocess.Popen([sys.executable, "-c", script, str(root), params["planId"]],
                             cwd=RUNTIME_SCRIPTS, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with RuntimeClient(root) as client:
            client.initialize()
            assert client.err("plan/apply", params)["code"] == "apply_in_progress"
    finally:
        child.terminate()
        child.wait(timeout=10)
        child.stdout.close()
    assert RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])["candidate"]["canonical"]


def test_new_approval_can_retry_only_a_proven_failed_attempt(tmp_path, monkeypatch):
    import rt_core
    root, source, session, params = prepared(tmp_path)
    def refuse(*args, **kwargs):
        raise RpcError("plan_invalid", "test prepublication refusal")
    monkeypatch.setattr(rt_core, "apply_plan", refuse)
    with pytest.raises(RpcError):
        RuntimeCore(root).plan_apply(params["planId"], params["approvalId"])
    monkeypatch.undo()
    with RuntimeClient(root) as client:
        client.initialize()
        plan = client.ok("plan/get", {"planId": params["planId"]})["plan"]
        approval = client.ok("approval/request", {"planId": params["planId"]})["approval"]
        client.ok("approval/resolve", {"approvalId": approval["approvalId"], "planId": plan["planId"],
                                      "planHash": plan["planHash"], "decision": "approved", "approver": "new-review"})
        new_params = {**params, "approvalId": approval["approvalId"]}
        result = client.ok("plan/apply", new_params)
        assert client.ok("plan/apply", new_params) == result
        assert client.err("plan/apply", params)["code"] == "approval_binding_mismatch"
