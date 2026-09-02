#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The event log a UI renders: everything the provider did, in order.

NO CLOCK. Events carry a monotonic ``seq`` and nothing else that varies between
two identical runs, because the mock provider's whole value is that two runs
produce the same bytes. A UI that wants arrival times stamps them itself, at
the moment it receives an event — which is the honest place for them anyway,
since a host-side timestamp says when the host wrote a line, not when anything
happened.

NO SECRETS. ``redact_headers`` is applied to anything header-shaped before it
reaches an event, and the credential value never enters this module at all —
only the NAME of the environment variable or store key it came from.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import EVENT_SCHEMA  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_session import append_line  # noqa: E402

#: Header names whose values are never written anywhere, in any casing.
SECRET_HEADERS = frozenset({"authorization", "x-api-key", "api-key",
                            "proxy-authorization", "cookie", "set-cookie"})
REDACTED = "<redacted>"

#: One closed set, so a UI can switch on it exhaustively.
EVENT_KINDS = (
    "run.started",
    "run.finished",
    "provider.selected",
    "provider.request",
    "provider.response",
    "provider.failed",
    "provider.stream.chunk",
    "tool.requested",
    "tool.refused",
    "tool.compiled",
    "runtime.result",
    "runtime.refused",
    # --- conversation with memory (host 0.2.0) ---
    #: a host process picked up an existing turn log and continued it
    "session.attached",
    #: one turn was appended to the persistent turn log
    "session.turn",
    #: history exceeded the window; carries the policy and the counts, so a
    #: dropped exchange is always visible as a dropped exchange
    "session.truncated",
    # --- operator-granted document context (host 0.2.0) ---
    #: an operator granted, or revoked, read-scoped document context
    "context.granted",
    "context.revoked",
    #: granted context was actually put in a prompt. ADDRESSES and sizes only:
    #: the whole point of the grant is that the text goes to the provider and
    #: nowhere else, and a log that copies it defeats that on the first turn
    "context.included",
    #: the agent reached past the grant and was refused
    "context.refused",
    "host.note",
)


def redact_headers(headers: dict | None) -> dict:
    """Every secret-shaped header value becomes a constant. Case-insensitive."""
    if not headers:
        return {}
    return {name: (REDACTED if name.lower() in SECRET_HEADERS else value)
            for name, value in headers.items()}


class EventLog:
    """Append-only, ordered, renderable. Optionally mirrored to JSONL.

    ``sink`` is how a long-lived host pushes events to its client AS THEY
    HAPPEN rather than at the end of the turn — which is the entire reason a
    streaming turn is worth having. It is called with the event dict, in
    order, from the thread that appended it; a sink that raises is a client
    problem and must not take the run down with it.

    ``append_mode`` keeps an existing mirror file: a one-shot run starts a
    fresh log (a golden document wants exactly its own events), a long-lived
    host adds to the one already there.
    """

    def __init__(self, path: Path | str | None = None, sink=None,
                 append_mode: bool = False):
        self.path = Path(path) if path else None
        self.sink = sink
        self._events: list[dict] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not append_mode:
                self.path.write_bytes(b"")

    def append(self, kind: str, **detail) -> dict:
        if kind not in EVENT_KINDS:
            raise ValueError(f"undeclared event kind: {kind!r}")
        event = {"seq": len(self._events), "kind": kind}
        if detail:
            event["detail"] = detail
        self._events.append(event)
        if self.path is not None:
            line = (json.dumps(event, ensure_ascii=False, sort_keys=True,
                               allow_nan=False) + "\n").encode("utf-8")
            # The Runtime's append primitive, imported rather than repeated:
            # ``open("ab")`` is NOT an atomic append on Windows, and that was
            # measured here (runtime/scripts/rt_session.append_line).
            try:
                append_line(self.path, line)
            except OSError:
                # A mirror is a projection. Losing a line of it must not take
                # down the run whose events it is mirroring.
                pass
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception:  # noqa: BLE001 - a client's problem, not the run's
                pass
        return event

    def events(self) -> list[dict]:
        return list(self._events)

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self._events]

    def of_kind(self, kind: str) -> list[dict]:
        return [event for event in self._events if event["kind"] == kind]

    def public(self) -> dict:
        return {"schema": EVENT_SCHEMA, "count": len(self._events),
                "events": self.events()}
