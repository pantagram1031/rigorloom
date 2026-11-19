# -*- coding: utf-8 -*-
"""The browser bridge records an approval only with the sheet's confirmation token.

Holding the bridge's host credential is not enough to approve: the approval
sheet asks `/api/approval/confirmation` for a single-use token bound to
(session, plan id, plan hash, base digest), and `approval/resolve` with any
decision other than `rejected` must carry it. The token is spent on first use,
expires, and works only for the plan it was issued for.
"""
from __future__ import annotations

import base64
import http.client
import json
from pathlib import Path
import sys
import threading

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
CORPUS_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_ui  # noqa: E402


class _Client:
    def __init__(self, server: rt_ui.BridgeHTTPServer) -> None:
        self.port = server.port
        self.token = server.token

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            conn.request("POST", path, body=raw, headers={
                "X-Rigorloom-Token": self.token,
                "Content-Type": "application/json",
            })
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    def rpc(self, method: str, params: dict) -> tuple[int, dict]:
        return self.post("/rpc", {"method": method, "params": params})

    def ok(self, method: str, params: dict) -> dict:
        status, data = self.rpc(method, params)
        assert status == 200 and data["ok"] is True, (status, data)
        return data["result"]


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
        yield srv, _Client(srv)
    finally:
        srv.shutdown_bridge()
        t.join(timeout=5)


def _session(client: _Client) -> str:
    b64 = base64.b64encode(CORPUS_FORM.read_bytes()).decode("ascii")
    status, opened = client.post("/api/open-upload", {"filename": "form.hwpx", "bytesBase64": b64})
    assert status == 200, opened
    return opened["sessionId"]


def _pending(client: _Client, session_id: str, value: str) -> tuple[dict, dict]:
    plan = client.ok("plan/propose", {
        "sessionId": session_id,
        "backend": "preedit",
        "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": value}],
    })["plan"]
    assert client.ok("plan/validate", {"planId": plan["planId"]})["validation"]["ok"] is True
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    return plan, approval


def _token(client: _Client, session_id: str, plan: dict) -> str:
    status, issued = client.post("/api/approval/confirmation", {
        "sessionId": session_id,
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "baseDigest": plan["boundSha256"],
    })
    assert status == 200, issued
    return issued["confirmationToken"]


def _approve(client: _Client, plan: dict, approval: dict, token: str | None) -> tuple[int, dict]:
    params = {
        "approvalId": approval["approvalId"],
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "decision": "approved",
        "approver": "host-operator",
    }
    if token is not None:
        params["confirmationToken"] = token
    return client.rpc("approval/resolve", params)


def _state(client: _Client, approval: dict) -> str:
    return client.ok("approval/get", {"approvalId": approval["approvalId"]})["approval"]["state"]


def test_approval_without_a_token_is_refused(bridge):
    _, client = bridge
    session_id = _session(client)
    plan, approval = _pending(client, session_id, "토큰없음")

    status, data = _approve(client, plan, approval, None)
    assert status == 403 and data["error"]["code"] == "confirmation_required", data
    status, data = _approve(client, plan, approval, "made-up-token")
    assert status == 403 and data["error"]["code"] == "confirmation_invalid", data
    # A decision spelled any other way is still an approval attempt.
    status, data = client.rpc("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "Approved",
    })
    assert status == 403 and data["error"]["code"] == "confirmation_required", data
    assert _state(client, approval) == "pending"

    # Returning a proposal records no approval and needs no token.
    returned = client.ok("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "rejected", "approver": "host-operator",
    })
    assert returned["approval"]["state"] == "rejected"


def test_a_token_for_another_binding_is_refused(bridge):
    _, client = bridge
    session_id = _session(client)
    plan_a, approval_a = _pending(client, session_id, "첫째안")
    plan_b, _ = _pending(client, session_id, "둘째안")

    # Issuing checks the binding against the runtime's plan record.
    for wrong in (
        {"planHash": plan_b["planHash"]},
        {"baseDigest": "0" * 64},
        {"sessionId": "S-elsewhere"},
    ):
        body = {
            "sessionId": session_id,
            "planId": plan_a["planId"],
            "planHash": plan_a["planHash"],
            "baseDigest": plan_a["boundSha256"],
            **wrong,
        }
        status, data = client.post("/api/approval/confirmation", body)
        assert status in (404, 409), (wrong, status, data)
        assert "confirmationToken" not in data

    # A token issued for plan B does not approve plan A, and is spent by trying.
    token_b = _token(client, session_id, plan_b)
    status, data = _approve(client, plan_a, approval_a, token_b)
    assert status == 403 and data["error"]["code"] == "confirmation_binding_mismatch", data
    assert _state(client, approval_a) == "pending"
    status, data = _approve(client, plan_a, approval_a, token_b)
    assert status == 403 and data["error"]["code"] == "confirmation_invalid", data


def test_a_token_works_once(bridge):
    srv, client = bridge
    session_id = _session(client)
    plan, approval = _pending(client, session_id, "한번만")

    token = _token(client, session_id, plan)
    status, data = _approve(client, plan, approval, token)
    assert status == 200 and data["ok"] is True, data
    assert data["result"]["approval"]["state"] == "approved"
    assert _state(client, approval) == "approved"

    # Reuse is refused by the bridge before the runtime sees it.
    plan2, approval2 = _pending(client, session_id, "다시")
    status, data = _approve(client, plan, approval, token)
    assert status == 403 and data["error"]["code"] == "confirmation_invalid", data

    # An expired token is refused too.
    token2 = _token(client, session_id, plan2)
    with srv.bridge._confirm_lock:
        srv.bridge._confirmations[token2]["expires"] = 0.0
    status, data = _approve(client, plan2, approval2, token2)
    assert status == 403 and data["error"]["code"] == "confirmation_expired", data
    assert _state(client, approval2) == "pending"

    # A fresh token for that plan approves it; the token never reaches the runtime.
    status, data = _approve(client, plan2, approval2, _token(client, session_id, plan2))
    assert status == 200 and data["ok"] is True, data
    receipt_plan = client.ok("plan/get", {"planId": plan2["planId"]})["plan"]
    assert receipt_plan["state"] == "approved"

