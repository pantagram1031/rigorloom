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
    "host.note",
)


def redact_headers(headers: dict | None) -> dict:
    """Every secret-shaped header value becomes a constant. Case-insensitive."""
    if not headers:
        return {}
    return {name: (REDACTED if name.lower() in SECRET_HEADERS else value)
            for name, value in headers.items()}


class EventLog:
    """Append-only, ordered, renderable. Optionally mirrored to JSONL."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._events: list[dict] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(b"")

    def append(self, kind: str, **detail) -> dict:
        if kind not in EVENT_KINDS:
            raise ValueError(f"undeclared event kind: {kind!r}")
        event = {"seq": len(self._events), "kind": kind}
        if detail:
            event["detail"] = detail
        self._events.append(event)
        if self.path is not None:
            with self.path.open("ab") as handle:
                handle.write((json.dumps(event, ensure_ascii=False,
                                         sort_keys=True, allow_nan=False)
                              + "\n").encode("utf-8"))
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
