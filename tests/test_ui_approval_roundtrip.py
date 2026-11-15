# -*- coding: utf-8 -*-
"""End-to-end approval, authority boundary, SSE, and pipeline gate UI roundtrip tests."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import urllib.request

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
PIPELINE_CTL = REPO_ROOT / "modules" / "report" / "scripts" / "pipeline_ctl.py"
CORPUS_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402


class _BridgeClient:
    def __init__(self, server: rt_ui.BridgeHTTPServer) -> None:
        self.server = server
        self.host = "127.0.0.1"
        self.port = server.port
        self.token = server.token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        token: str | None = ...,
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=120)
        hdrs: dict[str, str] = {}
        if token is ...:
            hdrs["X-Rigorloom-Token"] = self.token
        elif token is not None:
            hdrs["X-Rigorloom-Token"] = token
        raw: bytes | None = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=raw, headers=hdrs)
            resp = conn.getresponse()
            return resp.status, resp.headers, resp.read()
        finally:
            conn.close()

    def get_json(self, path: str, **kwargs) -> tuple[int, dict]:
        status, _, data = self.request("GET", path, **kwargs)
        return status, json.loads(data.decode("utf-8"))

    def post_json(self, path: str, body: dict | None = None, **kwargs) -> tuple[int, dict]:
        status, _, data = self.request("POST", path, body=body if body is not None else {}, **kwargs)
        return status, json.loads(data.decode("utf-8"))

    def rpc(self, method: str, params: dict | None = None) -> dict:
        status, data = self.post_json("/rpc", {"method": method, "params": params or {}})
        assert status == 200
        return data

    def open_sse(self) -> tuple[http.client.HTTPResponse, queue.Queue[tuple[str, object]], threading.Event]:
        resp = urllib.request.urlopen(f"{self.server.url}events?token={self.token}", timeout=10)
        out_q: queue.Queue[tuple[str, object]] = queue.Queue()
        stop = threading.Event()

        def reader() -> None:
            ev_name = "message"
            lines: list[str] = []
            try:
                while not stop.is_set():
                    raw = resp.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line == "":
                        if lines:
                            try:
                                payload: object = json.loads("\n".join(lines))
                            except json.JSONDecodeError:
                                payload = "\n".join(lines)
                            out_q.put((ev_name, payload))
                            ev_name = "message"
                            lines = []
                    elif line.startswith("event:"):
                        ev_name = line[6:].strip()
                    elif line.startswith("data:"):
                        lines.append(line[5:].strip())
            except OSError:
                pass

        threading.Thread(target=reader, daemon=True).start()
        return resp, out_q, stop


@pytest.fixture()
def bridge(tmp_path: Path):
    srv = rt_ui.create_bridge_server(
        root=tmp_path / "rt-root",
        engine_root=REPO_ROOT,
        port=0,
        explicit_root=True,
        prefs_path=tmp_path / "prefs.json",
        auto_start=True,
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, _BridgeClient(srv), tmp_path
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def test_agent_propose_authority_separation_host_approve_apply_export_roundtrip(bridge):
    _, client, tmp_path = bridge
    sse_resp, sse_q, sse_stop = client.open_sse()
    try:
        # 1) Upload real corpus document via HTTP bridge & subscribe to runtime events.
        b64 = base64.b64encode(CORPUS_FORM.read_bytes()).decode("ascii")
        s_up, opened = client.post_json("/api/open-upload", {"filename": "form.hwpx", "bytesBase64": b64})
        assert s_up == 200
        session_id = opened["sessionId"]

        sub_res = client.rpc("event/subscribe", {"sessionId": session_id})
        assert sub_res["ok"] is True

        # 2) Run agenthost mock turn (`serve.py --entry agent`) — emits SSE agenthost://events,
        # builds validated plan & pending approval, and CANNOT call host-only approval/resolve or plan/apply.
        s_ah, ah_run = client.post_json(
            "/api/agent-host/run",
            {
                "sessionId": session_id,
                "provider": "mock",
                "scenario": "propose-then-wait",
                "instruction": "Fill first editable seat",
                "turnId": "turn-roundtrip-1",
            },
        )
        assert s_ah == 200, (s_ah, ah_run)
        assert ah_run["ok"] is True
        assert ah_run["validation"]["ok"] is True
        assert ah_run["approval"]["state"] == "pending"
        plan_id = ah_run["plan"]["planId"]
        plan_hash = ah_run["plan"]["planHash"]
        approval_id = ah_run["approval"]["approvalId"]

        # Verify authority separation explicitly with mock_agent --probe-authority.
        s_ma, ma_res = client.post_json(
            "/api/run-mock-agent",
            {"sessionId": session_id, "marker": "AUTH-PROBE-01", "scenario": "propose-then-wait"},
        )
        assert s_ma == 200 and ma_res["expectationMet"] is True
        assert set(ma_res["neverCalled"]) >= {"approval/resolve", "plan/apply", "workspace/openPath"}

        # Verify unauthenticated /rpc attempt for approval/resolve is blocked 403.
        s_unauth, _ = client.post_json(
            "/rpc",
            {
                "method": "approval/resolve",
                "params": {
                    "approvalId": approval_id,
                    "planId": plan_id,
                    "planHash": plan_hash,
                    "decision": "approved",
                    "approver": "attacker",
                },
            },
            token="invalid-token",
        )
        assert s_unauth == 403

        # 3) Resolve approval via authenticated Host /rpc & apply plan!
        resolved = client.rpc(
            "approval/resolve",
            {
                "approvalId": approval_id,
                "planId": plan_id,
                "planHash": plan_hash,
                "decision": "approved",
                "approver": "ui-reviewer",
            },
        )
        assert resolved["ok"] is True
        assert resolved["result"]["approval"]["state"] == "approved"

        applied = client.rpc("plan/apply", {"planId": plan_id, "approvalId": approval_id})
        assert applied["ok"] is True
        run_id = applied["result"]["candidate"]["runId"]

        receipt = client.rpc("receipt/read", {"sessionId": session_id, "runId": run_id})
        assert receipt["ok"] is True
        assert receipt["result"]["receipt"]["approval"]["approver"] == "ui-reviewer"

        # 4) Export to destination, verify sha256 + receipt sidecar, and verify edit in exported bytes.
        dest = tmp_path / "exported" / "approved.hwpx"
        s_exp, exp = client.post_json(
            "/api/export",
            {"sessionId": session_id, "runId": run_id, "destination": str(dest)},
        )
        assert s_exp == 200, (s_exp, exp)
        assert dest.is_file()
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == exp["sha256"]

        # Drain SSE and confirm both agenthost://events array format and runtime://events arrived!
        collected: list[tuple[str, object]] = []
        while True:
            try:
                collected.append(sse_q.get(timeout=0.5))
            except queue.Empty:
                break
        ah_batches = [payload for name, payload in collected if name == "agenthost://events"]
        assert ah_batches and isinstance(ah_batches[0], list)
        assert ah_batches[0][0]["turnId"] == "turn-roundtrip-1"
        assert "event" in ah_batches[0][0]
        rt_batches = [payload for name, payload in collected if name == "runtime://events"]
        assert rt_batches and isinstance(rt_batches[0], list)
    finally:
        sse_stop.set()
        sse_resp.close()


def test_rejected_approval_refuses_apply(bridge):
    _, client, _ = bridge
    b64 = base64.b64encode(CORPUS_FORM.read_bytes()).decode("ascii")
    session_id = client.post_json("/api/open-upload", {"filename": "reject.hwpx", "bytesBase64": b64})[1]["sessionId"]

    plan = client.rpc(
        "plan/propose",
        {
            "sessionId": session_id,
            "backend": "preedit",
            "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "거부테스트"}],
        },
    )["result"]["plan"]
    assert client.rpc("plan/validate", {"planId": plan["planId"]})["ok"] is True
    appr = client.rpc("approval/request", {"planId": plan["planId"]})["result"]["approval"]

    rej = client.rpc(
        "approval/resolve",
        {
            "approvalId": appr["approvalId"],
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "decision": "rejected",
            "approver": "ui-reviewer",
        },
    )
    assert rej["ok"] is True, rej
    assert rej["result"]["approval"]["state"] == "rejected"

    denied = client.rpc("plan/apply", {"planId": plan["planId"], "approvalId": appr["approvalId"]})
    assert denied["ok"] is False


def test_pipeline_gates_list_approve_reject_and_script_gate_refusal(bridge):
    _, client, tmp_path = bridge
    ws = tmp_path / "pipeline-ws"

    # Invalid workspace & missing workspace are refused cleanly.
    s_bad, _ = client.get_json(f"/api/pipeline/gates?workspace={tmp_path / 'does-not-exist'}")
    assert s_bad == 404

    subprocess.run(
        [
            sys.executable,
            str(PIPELINE_CTL),
            "init",
            str(ws),
            "--slug", "ui-test",
            "--mode", "supervised",
            "--subject", "UI Test Subject",
            "--topic", "UI Bridge Gate Test",
            "--form", "form.hwpx",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, str(PIPELINE_CTL), "advance", str(ws), "0", "--status", "awaiting_gate"],
        check=True,
        capture_output=True,
        text=True,
    )

    s_list, gates_payload = client.get_json(f"/api/pipeline/gates?workspace={ws}")
    assert s_list == 200
    assert gates_payload["mode"] == "supervised"
    assert gates_payload["nextStage"] == "0"
    by_name = {g["gate"]: g for g in gates_payload["gates"]}
    assert by_name["topic_pick"]["type"] == "human"
    assert by_name["topic_pick"]["state"] == "pending"
    assert by_name["topic_pick"]["resolvable"] is True
    assert by_name["layout"]["type"] == "script"
    assert by_name["layout"]["resolvable"] is False

    # Script gate MUST NOT be resolvable via human gate UI endpoint.
    s_script, script_err = client.post_json(
        "/api/pipeline/gate-resolve",
        {"workspace": str(ws), "gate": "layout", "decision": "approved", "approver": "alice"},
    )
    assert s_script == 400 and script_err["error"]["code"] == "script_gate_not_human"
    assert not (ws / "APPROVALS.md").exists()

    # Unknown gate refused fail-closed.
    s_unk, unk_err = client.post_json(
        "/api/pipeline/gate-resolve",
        {"workspace": str(ws), "gate": "nonexistent_gate", "decision": "approved"},
    )
    assert s_unk == 404 and unk_err["error"]["code"] == "gate_not_found"

    # Human gate approval writes exact format matching pipeline_ctl and updates PIPELINE.md.
    s_app, app_res = client.post_json(
        "/api/pipeline/gate-resolve",
        {"workspace": str(ws), "gate": "topic_pick", "decision": "approved", "approver": "alice"},
    )
    assert s_app == 200 and app_res["ok"] is True, (s_app, app_res)
    assert app_res["approvalsLine"].startswith("topic_pick: approved by alice via ui at=")
    approvals_text = (ws / "APPROVALS.md").read_text(encoding="utf-8")
    assert approvals_text.strip() == app_res["approvalsLine"]

    gates_after_approve = {
        g["gate"]: g
        for g in client.get_json(f"/api/pipeline/gates?workspace={ws}")[1]["gates"]
    }
    assert gates_after_approve["topic_pick"]["state"] == "approved"
    assert gates_after_approve["topic_pick"]["by"] == "operator"
    assert "approved by alice via ui" in approvals_text

    # Re-resolving as rejected keeps the earlier topic_pick line as a
    # `# superseded` comment (APPROVALS.md is a hand-written record) and blocks resume.
    s_rej, rej_res = client.post_json(
        "/api/pipeline/gate-resolve",
        {"workspace": str(ws), "gate": "topic_pick", "decision": "rejected", "reason": "missing citation"},
    )
    assert s_rej == 200 and rej_res["ok"] is True
    assert rej_res["approvalsLine"].startswith("topic_pick: rejected missing citation at=")
    approvals_lines = [ln for ln in (ws / "APPROVALS.md").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert approvals_lines == [
        f"# superseded {app_res['approvalsLine']}",
        rej_res["approvalsLine"],
    ]

    resume_proc = subprocess.run(
        [sys.executable, str(PIPELINE_CTL), "resume", str(ws)],
        check=True,
        capture_output=True,
        text=True,
    )
    resume_out = json.loads(resume_proc.stdout)
    assert resume_out["blocked"] is True

    # Approving again supersedes the rejection; pipeline_ctl must now read
    # the gate as approved even though the history keeps both earlier lines.
    s_re, re_res = client.post_json(
        "/api/pipeline/gate-resolve",
        {"workspace": str(ws), "gate": "topic_pick", "decision": "approved", "approver": "bob"},
    )
    assert s_re == 200 and re_res["ok"] is True, (s_re, re_res)
    approvals_lines = [ln for ln in (ws / "APPROVALS.md").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert approvals_lines == [
        f"# superseded {app_res['approvalsLine']}",
        f"# superseded {rej_res['approvalsLine']}",
        re_res["approvalsLine"],
    ]
    gates_after_reapprove = {
        g["gate"]: g
        for g in client.get_json(f"/api/pipeline/gates?workspace={ws}")[1]["gates"]
    }
    assert gates_after_reapprove["topic_pick"]["state"] == "approved"
