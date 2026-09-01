#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A deterministic agent that drives the agent surface, for repeatable tests.

    python runtime/scripts/mock_agent.py --root <dir> [--session <id>]
                                         [--scenario propose-one]
                                         [--door protocol|mcp] [--redact]

WHICH DOOR, AND WHY. The default is ``protocol``: the mock spawns
``serve.py --entry agent`` and speaks JSONL over its stdio. That is the door
docs/desktop-architecture.md §1 puts the Agent Host on — "an Agent Host
connects to the Runtime the same way the Desktop shell does, but on an
agent-authority connection" — so a Desktop test that embeds this mock is
exercising the transport Desktop will actually embed. ``--door mcp`` drives the
same scenarios through ``mcp_server.py`` instead, because the two surfaces are
supposed to be interchangeable for an agent and a fixture that can prove it is
worth more than one that assumes it.

WHAT IT DOES. Inspect the document, pick one target region deterministically,
propose a typed plan carrying a fixed marker, validate it, request approval,
then read plan, approval and candidate status back. It stops there. It does
not approve and it does not apply — not by choice but by construction: the
methods are absent from an agent connection's registry, and
``--probe-authority`` makes the mock attempt them anyway and record the
refusals, so a Desktop test can show the boundary rather than trust it.

DETERMINISM. No randomness and no clock reads anywhere in the decision path:

  * the target is the FIRST editable region in document order whose charPr
    preflight needs no declaration — ``scriptAnomaly`` not true and
    ``colorAnomaly`` not true. If there is no such seat the mock refuses and
    says so; it does not silently fall back to a seat that would print wrong;
  * the value written is ``--marker``, a fixed string, never a timestamp;
  * a session is chosen by sorting ``session/list`` and taking the first, so
    one store gives one answer.

Two runs against byte-identical sources therefore agree on ``opsHash`` and, with
``--redact``, on the whole output document byte for byte. ``--redact`` blanks
the fields that cannot be stable — ids and timestamps — which is what makes
this usable as a golden file for a UI test.

Output is ONE JSON document on stdout; diagnostics go to stderr. Exit codes
match the CLI's: 0 the scenario completed as specified, 2 usage, 3 the scenario
did not hold (its own expectation failed, or the surface refused), 4 internal.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_USAGE,
    IMPL_VERSION,
    PROTOCOL_VERSION,
    RpcError,
)
from rt_core import HOST_ONLY_METHODS  # noqa: E402
from rt_jsonl import log  # noqa: E402

HERE = Path(__file__).resolve().parent
SERVE = HERE / "serve.py"
MCP = HERE / "mcp_server.py"

AGENT_NAME = "rigorloom-mock-agent"
EXIT_INTERNAL = 4

DEFAULT_MARKER = "MOCK-AGENT-0001"
#: The address ``propose-invalid`` aims at. Far outside any real table, and
#: fixed, so the refusal it provokes is the same one every run.
INVALID_ADDRESS = {"table": 0, "row": 9999, "col": 9999}

SCENARIOS = ("propose-one", "propose-invalid", "propose-then-wait")
DOORS = ("protocol", "mcp")

#: Identity and time — the only things that CANNOT repeat between two runs.
#: ``--redact`` replaces each with a constant so the rest of the document is a
#: golden file. Content hashes are deliberately NOT in here: ``opsHash``,
#: ``boundSha256`` and ``documentHash`` are stable for byte-identical sources,
#: and blanking them would throw away the part of the golden worth checking.
#: ``planHash`` is derived from ``planId`` and ``createdUtc``, so it goes.
VOLATILE_KEYS = frozenset({
    "sessionId", "planId", "planHash", "approvalId", "runId",
    "createdUtc", "openedUtc", "requestedUtc", "resolvedUtc",
})
REDACTED = "<redacted>"


class DoorRefusal(Exception):
    """A refusal that came back over the wire, with its payload intact."""

    def __init__(self, code: str, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data or {}
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.data:
            out["data"] = self.data
        return out


class _ChildDoor:
    """Shared plumbing: spawn a server, write lines, read lines."""

    #: Generous. tests/test_subprocess_bounds.py measured a cold repo-script
    #: spawn at a loaded median of 9.00s; the child then spawns its own
    #: form_inspect children inside a single call.
    TIMEOUT = 180.0

    def __init__(self, argv: list[str], stderr_path: Path | None):
        self._stderr = stderr_path.open("wb") if stderr_path else subprocess.DEVNULL
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._stderr, env=env)
        self._lines: "queue.Queue[bytes | None]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _send(self, message: dict) -> None:
        self.proc.stdin.write(
            (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _recv(self) -> dict:
        line = self._lines.get(timeout=self.TIMEOUT)
        if line is None:
            raise DoorRefusal("door_closed",
                              "the runtime closed its output before answering")
        return json.loads(line.decode("utf-8"))

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=30)
        if self._stderr is not subprocess.DEVNULL:
            try:
                self._stderr.close()
            except (OSError, ValueError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class ProtocolDoor(_ChildDoor):
    """``serve.py --entry agent`` — the door a Desktop Agent Host uses."""

    name = "protocol"

    def __init__(self, root: Path, engine_root: Path | None, stderr_path=None):
        argv = [sys.executable, str(SERVE), "--entry", "agent", "--root", str(root)]
        if engine_root is not None:
            argv += ["--engine-root", str(engine_root)]
        super().__init__(argv, stderr_path)
        self._next = 0
        self.handshake = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "client": {"name": AGENT_NAME, "version": IMPL_VERSION},
            "unknownFieldPolicy": "reject",
        })

    def _request(self, method: str, params: dict) -> dict:
        self._next += 1
        self._send({"kind": "request", "id": f"a{self._next}",
                    "method": method, "params": params})
        frame = self._recv()
        if frame.get("kind") == "error":
            error = frame["error"]
            raise DoorRefusal(error["code"], error["message"], error.get("data"))
        return frame["result"]

    def call(self, method: str, params: dict | None = None) -> dict:
        return self._request(method, params or {})

    def surface(self) -> list[str]:
        return sorted(self.handshake["capabilities"]["methods"])


class McpDoor(_ChildDoor):
    """``mcp_server.py`` — the same agent surface, as MCP tools."""

    name = "mcp"

    def __init__(self, root: Path, engine_root: Path | None, stderr_path=None):
        argv = [sys.executable, str(MCP), "--root", str(root)]
        if engine_root is not None:
            argv += ["--engine-root", str(engine_root)]
        super().__init__(argv, stderr_path)
        self._next = 0
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": AGENT_NAME, "version": IMPL_VERSION},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._tools = [tool["name"]
                       for tool in self._rpc("tools/list", {})["tools"]]

    def _rpc(self, method: str, params: dict) -> dict:
        self._next += 1
        self._send({"jsonrpc": "2.0", "id": self._next, "method": method,
                    "params": params})
        message = self._recv()
        if "error" in message:
            error = message["error"]
            raise DoorRefusal("mcp_error", error.get("message", ""),
                              {"jsonrpcCode": error.get("code")})
        return message["result"]

    def call(self, method: str, params: dict | None = None) -> dict:
        tool = method.replace("/", "_")
        result = self._rpc("tools/call", {"name": tool,
                                          "arguments": params or {}})
        payload = json.loads(result["content"][0]["text"])
        if payload.get("ok") is not True:
            error = payload["error"]
            raise DoorRefusal(error["code"], error["message"], error.get("data"))
        return payload["result"]

    def surface(self) -> list[str]:
        return sorted(self._tools)


def open_door(door: str, root: Path, engine_root: Path | None,
              stderr_path: Path | None = None):
    if door == "protocol":
        return ProtocolDoor(root, engine_root, stderr_path)
    if door == "mcp":
        return McpDoor(root, engine_root, stderr_path)
    raise RpcError("invalid_params", f"unknown door {door!r}", known=list(DOORS))


# --- deterministic choices --------------------------------------------------

def choose_session(door, requested: str | None) -> str:
    """The named session, or the first of the sorted list. One store, one answer."""
    if requested:
        return requested
    rows = door.call("session/list")["sessions"]
    if not rows:
        raise DoorRefusal("no_session",
                          "no session under this root; a host must open a "
                          "document first (the agent surface cannot)")
    return sorted(row["sessionId"] for row in rows)[0]


def choose_target(regions: list[dict]) -> dict:
    """First editable seat, document order, whose preflight needs no charPr.

    ``regions`` arrives in table-then-cell order from the form scan
    (engine/scripts/form_inspect.py:802), so "first" is a document fact rather
    than a dictionary accident. A seat carrying ``scriptAnomaly`` or
    ``colorAnomaly`` is skipped rather than filled with a guessed charPr: those
    are exactly the seats that print smaller, narrower or in the guide colour
    (T30 / T127), and a fixture that quietly writes one would be manufacturing
    the defect it exists to catch.
    """
    for index, region in enumerate(regions):
        if region.get("scriptAnomaly") is True:
            continue
        if region.get("colorAnomaly") is True:
            continue
        return {
            "kind": region.get("kind", "cell"),
            "table": region.get("table"),
            "row": region.get("row"),
            "col": region.get("col"),
            "charPr": region.get("charPr"),
            "documentIndex": index,
            "selectedBy": ("first editable region in document order with no "
                           "charPr anomaly"),
        }
    raise DoorRefusal(
        "no_clean_seat",
        "every editable region needs a declared charPr; this fixture will not "
        "guess one",
        {"regionsConsidered": len(regions)})


def build_op(target: dict, marker: str) -> dict:
    return {"kind": "fill_cell", "table": target["table"], "row": target["row"],
            "col": target["col"], "text": marker}


# --- output -----------------------------------------------------------------

def redact(value):
    """Blank the fields that cannot be stable, recursively."""
    if isinstance(value, dict):
        return {key: (REDACTED if key in VOLATILE_KEYS and isinstance(
            item, str) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def emit(payload: dict, code: int, *, do_redact: bool) -> int:
    document = redact(payload) if do_redact else payload
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2,
                                sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()
    return code


# --- the run ----------------------------------------------------------------

def run_scenario(door, args) -> tuple[dict, int]:
    steps: list[dict] = []

    def record(name: str, detail=None) -> None:
        row = {"step": name}
        if detail is not None:
            row["detail"] = detail
        steps.append(row)

    session_id = choose_session(door, args.session)
    record("session/list" if not args.session else "session (given)")

    inspected = door.call("document/inspect",
                          {"sessionId": session_id, "include": ["regions"]})
    regions = inspected["regions"]["regions"]
    record("document/inspect", {"regions": len(regions)})

    if args.scenario == "propose-invalid":
        target = {
            "kind": "cell", **INVALID_ADDRESS, "charPr": None,
            "documentIndex": None,
            "selectedBy": "fixed out-of-range address (propose-invalid)",
        }
    else:
        target = choose_target(regions)
    record("target", target)

    op = build_op(target, args.marker)
    plan = door.call("plan/propose", {
        "sessionId": session_id, "backend": "preedit", "ops": [op],
        "proposer": AGENT_NAME})["plan"]
    record("plan/propose", {"opsHash": plan["opsHash"]})

    validation = door.call("plan/validate", {"planId": plan["planId"]})["validation"]
    record("plan/validate", {"verdict": validation["verdict"]})

    expects_valid = args.scenario != "propose-invalid"
    expectation = ("validation passes" if expects_valid
                   else "validation refuses the target")
    met = validation["ok"] is expects_valid

    approval = None
    if met and expects_valid:
        approval = door.call("approval/request", {
            "planId": plan["planId"], "requestedBy": AGENT_NAME})["approval"]
        record("approval/request", {"state": approval["state"]})

    def observe() -> dict:
        return {
            "plan": door.call("plan/get", {"planId": plan["planId"]})["plan"],
            "approval": (
                door.call("approval/get",
                          {"approvalId": approval["approvalId"]})["approval"]
                if approval else None),
            "candidates": door.call("candidate/list",
                                    {"sessionId": session_id})["candidates"],
        }

    # Re-reading is a POLL, not a wait: no sleep, no clock. A Desktop test
    # driving "the agent is parked on a pending approval" needs to see that
    # two consecutive reads agree, which is what stableAcrossPolls reports.
    attempts = args.poll_attempts
    if attempts is None:
        attempts = 2 if args.scenario == "propose-then-wait" else 1
    seen = [observe() for _ in range(max(1, attempts))]
    observed = seen[-1]
    stable = all(row == seen[0] for row in seen)
    record("observe", {"planState": observed["plan"]["state"],
                       "candidates": len(observed["candidates"]),
                       "pollAttempts": len(seen), "stable": stable})

    probes = []
    if args.probe_authority:
        for method in HOST_ONLY_METHODS:
            try:
                door.call(method, {})
            except DoorRefusal as exc:
                probes.append({"method": method, "code": exc.code,
                               "knownOnHostEntry":
                                   exc.data.get("knownOnHostEntry")})
            else:  # pragma: no cover - would be a real authority failure
                probes.append({"method": method, "code": None,
                               "reached": True})
        record("probe-authority", {"attempted": len(probes)})

    payload = {
        "ok": met,
        "agent": AGENT_NAME,
        "implVersion": IMPL_VERSION,
        "door": door.name,
        "scenario": args.scenario,
        "marker": args.marker,
        "sessionId": session_id,
        "documentHash": inspected.get("documentHash"),
        "regionsConsidered": len(regions),
        "target": target,
        "plan": plan,
        "validation": validation,
        "approval": approval,
        "observed": observed,
        "pollAttempts": len(seen),
        "stableAcrossPolls": stable,
        "waitingOn": ({"approvalId": approval["approvalId"],
                       "state": observed["approval"]["state"],
                       "resolvedBy": "a host; this agent cannot"}
                      if approval and args.scenario == "propose-then-wait"
                      else None),
        "expectation": expectation,
        "expectationMet": met,
        "authorityProbes": probes,
        "surface": door.surface(),
        "steps": steps,
        "neverCalled": list(HOST_ONLY_METHODS),
    }
    return payload, EXIT_OK if met else EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime/scripts/mock_agent.py",
        description="Deterministic agent-surface driver for repeatable tests. "
                    "Proposes and requests approval; never approves, never "
                    "applies.")
    parser.add_argument("--root", required=True,
                        help="the Runtime session-store root a host opened into")
    parser.add_argument("--session", default=None,
                        help="session id (default: first of the sorted list)")
    parser.add_argument("--scenario", default=SCENARIOS[0], choices=list(SCENARIOS))
    parser.add_argument("--door", default=DOORS[0], choices=list(DOORS),
                        help="protocol = serve.py --entry agent (what a Desktop "
                             "Agent Host embeds); mcp = the MCP adapter")
    parser.add_argument("--marker", default=DEFAULT_MARKER,
                        help="fixed value the proposed op writes")
    parser.add_argument("--engine-root", default=None)
    parser.add_argument("--poll-attempts", type=int, default=None,
                        help="how many times to re-read plan/approval/"
                             "candidate status (no sleeping; default 1, "
                             "or 2 for propose-then-wait)")
    parser.add_argument("--probe-authority", action="store_true",
                        help="attempt each host-only method and record the "
                             "refusal, so a test can show the boundary")
    parser.add_argument("--redact", action="store_true",
                        help="blank ids and timestamps so the output is a "
                             "stable golden document")
    parser.add_argument("--stderr-log", default=None,
                        help="write the child runtime's stderr here")
    return parser


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        return emit({"ok": False, "agent": AGENT_NAME, "scenario": args.scenario,
                     "error": {"code": "invalid_params",
                               "message": f"--root does not exist: {root}"}},
                    EXIT_USAGE, do_redact=args.redact)
    stderr_path = Path(args.stderr_log) if args.stderr_log else None
    door = None
    try:
        door = open_door(args.door, root, args.engine_root, stderr_path)
        payload, code = run_scenario(door, args)
    except DoorRefusal as exc:
        return emit({"ok": False, "agent": AGENT_NAME, "door": args.door,
                     "scenario": args.scenario, "error": exc.as_dict()},
                    EXIT_REFUSED, do_redact=args.redact)
    except RpcError as exc:
        return emit({"ok": False, "agent": AGENT_NAME, "scenario": args.scenario,
                     "error": exc.to_frame_error()},
                    EXIT_USAGE, do_redact=args.redact)
    except Exception as exc:  # noqa: BLE001 - a bug must not look like a verdict
        log("mock agent internal error:\n" + traceback.format_exc())
        return emit({"ok": False, "agent": AGENT_NAME, "scenario": args.scenario,
                     "error": {"code": "internal_error",
                               "message": f"{type(exc).__name__}: see stderr"}},
                    EXIT_INTERNAL, do_redact=args.redact)
    finally:
        if door is not None:
            door.close()
    return emit(payload, code, do_redact=args.redact)


if __name__ == "__main__":
    raise SystemExit(main())
