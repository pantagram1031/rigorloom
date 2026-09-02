#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A conversation that survives the process that had it.

Before this, a conversation with the Agent Host was N cold Python starts: each
``host.py`` invocation built a provider, ran one turn loop, printed a document
and forgot everything. The model's memory of turn 3 was whatever the operator
retyped into turn 4.

A ``HostSession`` is the fix, and it is deliberately a FILE rather than a
process. In-process history is fast and convenient and dies with a crash; the
append-only turn log is what makes "reattach" mean something. A new host on the
same root and session id reads the log, replays the exchanges and continues —
after a clean shutdown, after a kill, after a machine restart.

WHERE IT LIVES

``<root>/agenthost/<sessionId>/`` — beside the Runtime's session store, never
inside it. The Runtime owns ``<root>/sessions/``; the host owns its own tree,
so neither can corrupt the other's idea of what a directory contains.

HOW IT APPENDS

Through ``rt_session.append_line``, which is the Runtime's primitive and not a
second copy of it. ``open(path, "ab")`` is NOT an atomic append on Windows —
CPython's ``O_APPEND`` goes through the CRT, which seeks then writes, so two
writers land on the same offset and one silently wins. That was measured in
this repository (four threads, fifty lines each, 167 of 200 survived). A host
that loses turns is a host that lies about the conversation.

WHAT IT REFUSES TO STORE

Document text. Not the granted regions, not the DocumentSummary, not a tool
result's payload. A turn record holds the instruction, the model's reply, which
transport ran, which tools were called and whether they succeeded, plus the
grant's ID and a hash of what was disclosed. Reattach re-fetches granted
context from the Runtime; the log never had it to leak.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    GRANT_SCHEMA,
    SESSION_SCHEMA,
    TRUNCATION_POLICIES,
    TURN_SCHEMA,
    AgentHostError,
)
from ah_grant import ContextGrant  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_jsonl import StrictJsonError, loads_strict  # noqa: E402
from rt_session import append_line, now_utc  # noqa: E402

TURNS_FILE = "turns.jsonl"
GRANTS_FILE = "grants.jsonl"

#: How many prior exchanges are resent to the provider. Bounded because a
#: conversation is unbounded and a context window is not; DECLARED because a
#: silently forgotten exchange is a model that contradicts itself for reasons
#: the operator cannot see.
DEFAULT_HISTORY_WINDOW = 12

#: The only policy implemented. Named in every turn record it applied to.
DEFAULT_TRUNCATION_POLICY = TRUNCATION_POLICIES[0]


def _line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def read_records(path: Path) -> tuple[list[dict], int]:
    """Every parseable record, and how many lines were not.

    A half-written trailing line is skipped rather than guessed at — the same
    posture as ``rt_session.read_events`` — and the skip is COUNTED, so a
    caller can report "11 turns, 1 unreadable" instead of quietly presenting a
    conversation with a hole in it.
    """
    if not path.exists():
        return [], 0
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AgentHostError("session_log_unreadable",
                             f"the session log could not be read: {exc}",
                             path=str(path)) from exc
    records: list[dict] = []
    skipped = 0
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            value = loads_strict(text)
        except StrictJsonError:
            skipped += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            skipped += 1
    return records, skipped


@dataclass
class Truncation:
    """What the window dropped, and by which rule."""

    policy: str
    kept: int
    dropped: int

    def public(self) -> dict:
        return {"policy": self.policy, "kept": self.kept,
                "dropped": self.dropped}


class HostSession:
    """The persistent half of a conversation: turns, grants, and reattach."""

    def __init__(self, root: Path | str, session_id: str,
                 history_window: int = DEFAULT_HISTORY_WINDOW):
        if not isinstance(session_id, str) or not session_id:
            raise AgentHostError("config_invalid",
                                 "a host session needs a session id")
        if not isinstance(history_window, int) or history_window < 1:
            raise AgentHostError("config_invalid",
                                 "historyWindow must be a positive integer",
                                 offered=history_window)
        self.root = Path(root)
        self.session_id = session_id
        self.history_window = history_window
        self.dir = self.root / "agenthost" / session_id
        self.turns_path = self.dir / TURNS_FILE
        self.grants_path = self.dir / GRANTS_FILE
        self._turns: list[dict] = []
        self._grant_records: list[dict] = []
        self.turns_skipped = 0
        self.grants_skipped = 0
        self.attached = False

    # -- lifecycle -----------------------------------------------------------
    def load(self) -> "HostSession":
        """Read what a previous process left. Idempotent, and never creates."""
        self._turns, self.turns_skipped = read_records(self.turns_path)
        self._grant_records, self.grants_skipped = read_records(self.grants_path)
        self.attached = bool(self._turns) or bool(self._grant_records)
        return self

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- turns ---------------------------------------------------------------
    def turns(self) -> list[dict]:
        return list(self._turns)

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    def next_turn_number(self) -> int:
        return len(self._turns) + 1

    def append_turn(self, record: dict) -> dict:
        """Append one turn. Raises on an I/O failure: this log IS the state."""
        stamped = {"schema": TURN_SCHEMA, "at": now_utc(),
                   "sessionId": self.session_id, **record}
        try:
            append_line(self.turns_path, _line(stamped))
        except OSError as exc:
            raise AgentHostError(
                "session_log_unreadable",
                f"the turn could not be persisted: {exc}. The conversation is "
                "not durable and continuing would invent a memory that is not "
                "on disk", path=str(self.turns_path)) from exc
        self._turns.append(stamped)
        return stamped

    # -- the bounded window --------------------------------------------------
    def conversation(self) -> tuple[tuple, Truncation | None]:
        """The exchanges to resend, plus what the window dropped.

        ``recent-exchanges``: keep the newest ``history_window`` exchanges,
        oldest-first within that. Nothing is summarised — a summary of a
        conversation is a claim about it, and this host does not make claims
        it cannot show the evidence for.
        """
        exchanges = [{"instruction": row.get("instruction") or "",
                      "reply": row.get("reply")}
                     for row in self._turns
                     if row.get("instruction")]
        total = len(exchanges)
        if total <= self.history_window:
            return tuple(exchanges), None
        kept = exchanges[-self.history_window:]
        return tuple(kept), Truncation(policy=DEFAULT_TRUNCATION_POLICY,
                                       kept=len(kept), dropped=total - len(kept))

    # -- grants --------------------------------------------------------------
    def grant_records(self) -> list[dict]:
        return list(self._grant_records)

    def append_grant(self, grant: ContextGrant, action: str = "grant") -> dict:
        """Record an operator's decision. Addresses only, never text.

        ``at`` lives HERE and not in the event log: the event log is
        deliberately clock-free so two identical runs produce identical bytes,
        while an audit record that cannot say when is not an audit record.
        """
        if action not in ("grant", "revoke"):
            raise AgentHostError("grant_invalid",
                                 "a grant record is a grant or a revoke",
                                 offered=action)
        record = {"schema": GRANT_SCHEMA, "at": now_utc(),
                  "sessionId": self.session_id, "action": action,
                  **grant.public()}
        try:
            append_line(self.grants_path, _line(record))
        except OSError as exc:
            raise AgentHostError(
                "session_log_unreadable",
                f"the grant could not be persisted: {exc}. A disclosure this "
                "host cannot record is a disclosure it will not make",
                path=str(self.grants_path)) from exc
        self._grant_records.append(record)
        return record

    def current_grant(self, default_scope: str = "open") -> ContextGrant:
        """The grant in force: the last operator decision, or nothing.

        Last-writer-wins over the append-only log, which is why a revoke is a
        record rather than a deletion — an audit trail that can be shortened
        is not one.
        """
        for record in reversed(self._grant_records):
            if record.get("action") == "revoke":
                return ContextGrant.empty(
                    read_scope=record.get("readScope") or default_scope)
            if record.get("action") == "grant":
                granted_by = record.get("grantedBy") or "operator:cli"
                return ContextGrant.from_public(record, granted_by)
        return ContextGrant.empty(read_scope=default_scope)

    # -- reporting -----------------------------------------------------------
    def public(self) -> dict:
        exchanges, truncation = self.conversation()
        return {
            "schema": SESSION_SCHEMA,
            "sessionId": self.session_id,
            "dir": str(self.dir),
            "turns": self.turn_count,
            "attached": self.attached,
            "historyWindow": self.history_window,
            "truncationPolicy": DEFAULT_TRUNCATION_POLICY,
            "exchangesResent": len(exchanges),
            "truncation": truncation.public() if truncation else None,
            "unreadableTurnLines": self.turns_skipped,
            "unreadableGrantLines": self.grants_skipped,
            "grant": self.current_grant().public(),
        }
