#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The long-lived Agent Host: one process, many turns, JSONL over stdio.

``host.py`` without ``--serve`` is one shot: build a provider, run a turn loop,
print a document, exit. A conversation was therefore N cold Python starts, each
paying for an interpreter, a provider construction and a Runtime child, and
each remembering nothing. ``--serve`` keeps the process, the door and the
history alive, and turns the event log into a live push channel — which is the
whole reason streaming is worth having.

THE FRAMING IS THE RUNTIME'S, NOT A NEW ONE

``rt_jsonl`` is imported, not reimplemented: one JSON object per line, UTF-8,
newline-terminated, oversize refused without being parsed, stdout frames only
and every diagnostic on stderr. A consumer that already speaks to
``runtime/scripts/serve.py`` needs no new transport code, only new method
names.

  ->  {"kind":"request","id":1,"method":"turn","params":{"instruction":"…"}}
  <-  {"kind":"event","event":{"seq":0,"kind":"run.started","detail":{…}}}
  <-  … one event frame per event, AS IT HAPPENS, streaming chunks included
  <-  {"kind":"response","id":1,"result":{ …the run payload… }}

Methods: ``initialize``, ``turn``, ``context/grant``, ``context/revoke``,
``session/state``, ``shutdown`` (``ah_codes.SERVE_METHODS``). All but
``initialize`` are operator authority and are refused by name if a model ever
asks for one as a tool (``ah_compile.HOST_CONTROL_TOOLS``).

SINGLE-THREADED ON PURPOSE

One turn at a time. The Runtime door is a child process with one stdio pair and
the session log is append-only; interleaving two turns would produce a
conversation whose order nobody can reconstruct. A request that arrives during
a turn waits in the pipe, which is the honest backpressure.
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    EXIT_OK,
    HOST_VERSION,
    SERVE_METHODS,
    SERVE_PROTOCOL_VERSION,
    AgentHostError,
)
from ah_events import EventLog  # noqa: E402
from ah_grant import ContextGrant  # noqa: E402
from ah_host import DEFAULT_MAX_TURNS, HOST_NAME, AgentHost, discover_session  # noqa: E402
from ah_session import DEFAULT_HISTORY_WINDOW, HostSession  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_codes import MAX_FRAME_BYTES  # noqa: E402
from rt_jsonl import (  # noqa: E402
    READ_EOF,
    READ_OVERSIZE,
    FrameWriter,
    StrictJsonError,
    decode_frame,
    read_raw_frame,
)

#: Only these members may appear on a request frame. Same posture as the
#: Runtime's: an unknown member is a refusal, not something to ignore.
REQUEST_MEMBERS = frozenset({"kind", "id", "method", "params"})


def _error_frame(frame_id, exc: AgentHostError) -> dict:
    return {"kind": "error", "id": frame_id, "error": exc.as_dict()}


class HostServer:
    """The frame loop. Owns stdout; every diagnostic goes to stderr."""

    def __init__(self, door, provider, root: Path, args,
                 stdin=None, stdout=None):
        self.door = door
        self.provider = provider
        self.root = Path(root)
        self.args = args
        self._in = stdin if stdin is not None else sys.stdin.buffer
        self._write_lock = threading.Lock()
        self.out = FrameWriter(stdout if stdout is not None else sys.stdout.buffer,
                               self._write_lock)
        self.session_id: str | None = None
        self.session: HostSession | None = None
        self.grant = ContextGrant.empty(read_scope=getattr(args, "read_scope",
                                                           "open"))
        self.running = True
        self.turns_served = 0
        self._seen_ids: set = set()

    # -- lifecycle -----------------------------------------------------------
    def attach(self) -> dict:
        """Bind to a session and reload whatever a previous process left."""
        self.session_id = (getattr(self.args, "session", None)
                           or discover_session(self.door))
        window = getattr(self.args, "history_window", DEFAULT_HISTORY_WINDOW)
        self.session = HostSession(self.root, self.session_id,
                                   history_window=window).load()
        # An operator's grant on THIS process's command line is a decision
        # made now, so it wins and is recorded like any other. Otherwise a
        # grant recorded by an earlier process is still in force: it survives
        # the process that carried it out, exactly as the turn log does.
        launched = getattr(self.args, "launch_grant", None)
        if launched is not None and not launched.is_empty():
            self.grant = launched
            self.session.append_grant(launched, action="grant")
        else:
            stored = self.session.current_grant(
                default_scope=getattr(self.args, "read_scope", "open"))
            if not stored.is_empty():
                self.grant = stored
        return self.state()

    def state(self) -> dict:
        return {
            "host": HOST_NAME,
            "hostVersion": HOST_VERSION,
            "protocolVersion": SERVE_PROTOCOL_VERSION,
            "methods": list(SERVE_METHODS),
            "sessionId": self.session_id,
            "provider": self.provider.capabilities().public(),
            "streamMode": getattr(self.args, "stream_mode", "auto"),
            "turnsServedThisProcess": self.turns_served,
            "session": self.session.public() if self.session else None,
            "grant": self.grant.public(),
        }

    # -- the loop ------------------------------------------------------------
    def serve(self) -> int:
        while self.running:
            kind, raw = read_raw_frame(self._in, MAX_FRAME_BYTES)
            if kind == READ_EOF:
                break
            if kind == READ_OVERSIZE:
                self.out.send(_error_frame(None, AgentHostError(
                    "config_invalid",
                    f"a request frame exceeded {MAX_FRAME_BYTES} bytes and was "
                    "refused without being parsed")))
                continue
            try:
                frame = decode_frame(raw)
            except StrictJsonError as exc:
                self.out.send(_error_frame(None, AgentHostError(
                    "config_invalid", f"frame did not parse: {exc.detail}",
                    strictCode=exc.code)))
                continue
            self._handle(frame)
        return EXIT_OK

    def _handle(self, frame: dict) -> None:
        frame_id = frame.get("id")
        if frame.get("kind") != "request":
            self.out.send(_error_frame(frame_id, AgentHostError(
                "config_invalid", "a client sends request frames",
                kind=frame.get("kind"))))
            return
        unknown = sorted(set(frame) - REQUEST_MEMBERS)
        if unknown:
            self.out.send(_error_frame(frame_id, AgentHostError(
                "config_invalid",
                "request frames carry only kind, id, method, params",
                unknown=unknown, allowed=sorted(REQUEST_MEMBERS))))
            return
        if not isinstance(frame_id, (str, int)) or isinstance(frame_id, bool):
            self.out.send(_error_frame(None, AgentHostError(
                "config_invalid", "id must be a string or an integer")))
            return
        if frame_id in self._seen_ids:
            # A replayed id would produce a second turn under the first turn's
            # name. Refuse rather than run it.
            self.out.send(_error_frame(frame_id, AgentHostError(
                "config_invalid", "that request id was already used",
                id=frame_id)))
            return
        self._seen_ids.add(frame_id)
        method = frame.get("method")
        params = frame.get("params") or {}
        if not isinstance(params, dict):
            self.out.send(_error_frame(frame_id, AgentHostError(
                "config_invalid", "params must be an object")))
            return
        if method not in SERVE_METHODS:
            self.out.send(_error_frame(frame_id, AgentHostError(
                "tool_unknown", f"no such host method {method!r}",
                known=list(SERVE_METHODS))))
            return
        try:
            result = self._dispatch(method, params, frame_id)
        except AgentHostError as exc:
            self.out.send(_error_frame(frame_id, exc))
            return
        except Exception as exc:  # noqa: BLE001 - a bug is not a verdict
            print("agent host internal error:\n" + traceback.format_exc(),
                  file=sys.stderr, flush=True)
            self.out.send(_error_frame(frame_id, AgentHostError(
                "host_internal_error", f"{type(exc).__name__}: see stderr")))
            return
        self.out.respond(frame_id, result)

    def _dispatch(self, method: str, params: dict, frame_id) -> dict:
        if method == "initialize":
            return self.state()
        if method == "session/state":
            return self.state()
        if method == "shutdown":
            self.running = False
            return {"ok": True, "turnsServedThisProcess": self.turns_served}
        if method == "context/grant":
            return self._grant(params)
        if method == "context/revoke":
            return self._revoke(params)
        if method == "turn":
            return self._turn(params, frame_id)
        raise AgentHostError("tool_unknown", f"unhandled method {method!r}")

    # -- operator actions ----------------------------------------------------
    def _grant(self, params: dict) -> dict:
        """An OPERATOR widening what may go into a prompt. Never the model.

        This method is reachable only from the control channel — the process's
        own stdin, which the operator owns. A model that asks for
        ``context_grant`` as a tool is refused by name at the compile gate
        before the Runtime is touched, and the refusal is recorded as
        ``context.refused``.
        """
        grant = ContextGrant.from_public(params, "operator:control-channel")
        if grant.read_scope == "open" and "readScope" not in params:
            # Keep whatever scope is already in force rather than silently
            # widening it back to the default.
            grant = ContextGrant(items=grant.items,
                                 granted_by=grant.granted_by,
                                 read_scope=self.grant.read_scope)
        self.grant = grant
        record = self.session.append_grant(grant, action="grant")
        return {"ok": True, "grant": grant.public(),
                "recordedAt": record["at"], "session": self.session.public()}

    def _revoke(self, params: dict) -> dict:
        scope = params.get("readScope")
        grant = ContextGrant.empty(
            read_scope=scope if isinstance(scope, str) else self.grant.read_scope)
        self.grant = grant
        record = self.session.append_grant(grant, action="revoke")
        return {"ok": True, "grant": grant.public(),
                "recordedAt": record["at"], "session": self.session.public()}

    # -- a turn --------------------------------------------------------------
    def _turn(self, params: dict, frame_id) -> dict:
        instruction = params.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise AgentHostError("config_invalid",
                                 "a turn needs a non-empty instruction")
        max_turns = params.get("maxTurns")
        if max_turns is None:
            max_turns = getattr(self.args, "max_turns", DEFAULT_MAX_TURNS)
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) \
                or max_turns < 1:
            raise AgentHostError("config_invalid",
                                 "maxTurns must be a positive integer",
                                 offered=max_turns)

        def sink(event: dict) -> None:
            # Pushed as it happens: this is what makes a streamed answer
            # visible to a UI mid-turn rather than at the end of it.
            self.out.send({"kind": "event", "id": frame_id, "event": event})

        mirror = getattr(self.args, "events", None)
        events = EventLog(mirror, sink=sink, append_mode=True)
        if not self.grant.is_empty():
            events.append("context.granted", **self.grant.public())
        host = AgentHost(self.door, self.provider, events,
                         max_turns=max_turns, session=self.session,
                         grant=self.grant,
                         stream_mode=getattr(self.args, "stream_mode", "auto"))
        payload = host.run(instruction, self.session_id)
        self.turns_served += 1
        return payload


def serve(door, provider, root, args, stdin=None, stdout=None) -> int:
    """Attach to the session, announce, then serve frames until EOF."""
    server = HostServer(door, provider, root, args, stdin=stdin, stdout=stdout)
    ready = server.attach()
    server.out.notify("host/ready", ready)
    return server.serve()
