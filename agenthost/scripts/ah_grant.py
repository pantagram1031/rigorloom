#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-scoped document context, granted by an OPERATOR and by nobody else.

The Agent Host can put document content into a provider prompt. That is a
network disclosure, so it is the one thing in this tree that needs a human's
explicit say-so, and the say-so has to be structural rather than a policy
somebody remembers to apply.

THE SHAPE OF THE AUTHORITY

  * A grant is created only from an operator channel: a ``--grant-*`` flag on
    the CLI, or a ``context/grant`` frame on the long-lived host's stdio
    control channel. Both are the operator's own process boundary.
  * The model has no way to ask for one. ``context/grant`` is in
    ``ah_codes.HOST_CONTROL_METHODS``, which ``ah_compile`` refuses by name
    with ``tool_forbidden`` — the same treatment as ``plan/apply``.
  * A grant names ADDRESSES. It never names "the document", and it cannot be
    widened by the thing it constrains.

AND WHAT IT DOES NOT CLAIM

  ``document/readRegion`` is an agent-safe Runtime method and has been since
  Phase 2: with the default ``--read-scope open`` a model can still read any
  region by ASKING FOR IT AS A TOOL, and the result lands in the history that
  goes back to the provider. A grant is therefore not, by itself, a
  confidentiality boundary over the document — it bounds what the host
  VOLUNTEERS without being asked.

  ``--read-scope granted`` makes it a boundary in the other direction too: the
  compile gate then refuses a ``document_readRegion`` for any address the
  operator did not grant, before the Runtime is asked. That is off by default
  because turning it on silently would be a behaviour change wearing a
  feature's clothes, and the Phase-2 surface is what the Desktop ships today.

PRIVACY

  A grant record names addresses and nothing else. The disclosure record
  (``context.included``) carries addresses, byte counts and a SHA-256 of what
  was sent — enough to prove later exactly what left the machine, and not one
  character of the document itself. The text exists in one request body and in
  no log, no event and no turn record. That is also why reattach re-fetches
  context from the Runtime instead of replaying it from the turn log: the log
  never had it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    GRANT_KINDS,
    GRANT_SCHEMA,
    READ_SCOPES,
    AgentHostError,
)

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_session import full_text_spec  # noqa: E402

#: The Runtime method a granted region is fetched with, and the tool name the
#: model would use for the same thing. Derived from the Runtime's spelling
#: rather than typed twice.
READ_REGION_METHOD = "document/readRegion"
READ_REGION_TOOL = READ_REGION_METHOD.replace("/", "_")

#: Where a grant came from. There is no "agent" member, on purpose.
GRANTED_BY = ("operator:cli", "operator:control-channel")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_region_spec(spec: str) -> dict:
    """``T:R,C`` / ``R,C`` / ``para:N`` -> a readRegion address.

    Deliberately the CLI's spelling (runtime/scripts/cli.py ``_parse_region``),
    so an operator types one address syntax for the whole program.
    """
    text = str(spec).strip()
    if text.lower().startswith("para:"):
        try:
            return {"atPara": int(text.split(":", 1)[1])}
        except ValueError as exc:
            raise AgentHostError("grant_invalid",
                                 f"grant {spec!r}: para:N needs an integer"
                                 ) from exc
    table = 0
    if ":" in text:
        head, _, text = text.partition(":")
        try:
            table = int(head)
        except ValueError as exc:
            raise AgentHostError("grant_invalid",
                                 f"grant {spec!r}: table index must be an integer"
                                 ) from exc
    row, comma, col = text.partition(",")
    if not comma:
        raise AgentHostError("grant_invalid",
                             f"grant {spec!r}: expected T:R,C, R,C or para:N")
    try:
        return {"table": table, "row": int(row), "col": int(col)}
    except ValueError as exc:
        raise AgentHostError("grant_invalid",
                             f"grant {spec!r}: row and col must be integers"
                             ) from exc


def address_key(address: dict) -> str:
    """One canonical spelling per address, so scope comparison is exact."""
    try:
        return full_text_spec(address)
    except (TypeError, ValueError, KeyError) as exc:
        raise AgentHostError("grant_invalid",
                             f"not a region address: {address!r}") from exc


@dataclass(frozen=True)
class GrantItem:
    """One thing an operator allowed into a prompt."""

    kind: str
    address: dict | None = None

    def __post_init__(self) -> None:
        if self.kind not in GRANT_KINDS:
            raise AgentHostError("grant_invalid",
                                 f"grant kind must be one of {list(GRANT_KINDS)}",
                                 offered=self.kind)
        if self.kind == "region" and not isinstance(self.address, dict):
            raise AgentHostError("grant_invalid",
                                 "a region grant needs an address")
        if self.kind == "summary" and self.address is not None:
            raise AgentHostError("grant_invalid",
                                 "a summary grant takes no address")

    @property
    def key(self) -> str:
        return "summary" if self.kind == "summary" else address_key(self.address)

    def public(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.address is not None:
            out["address"] = dict(self.address)
            out["spec"] = self.key
        return out


@dataclass(frozen=True)
class ContextGrant:
    """A closed set of addresses, and who opened it.

    Immutable on purpose: "widening" is not an operation, it is a NEW grant
    from an operator channel, which leaves its own record.
    """

    items: tuple = ()
    granted_by: str = GRANTED_BY[0]
    read_scope: str = "open"

    def __post_init__(self) -> None:
        if self.granted_by not in GRANTED_BY:
            raise AgentHostError("grant_invalid",
                                 f"grantedBy must be one of {list(GRANTED_BY)}",
                                 offered=self.granted_by)
        if self.read_scope not in READ_SCOPES:
            raise AgentHostError("grant_invalid",
                                 f"readScope must be one of {list(READ_SCOPES)}",
                                 offered=self.read_scope)
        seen: set = set()
        for item in self.items:
            if not isinstance(item, GrantItem):
                raise AgentHostError("grant_invalid",
                                     "a grant holds GrantItem values")
            if item.key in seen:
                raise AgentHostError("grant_invalid",
                                     f"the grant names {item.key!r} twice")
            seen.add(item.key)

    # -- construction --------------------------------------------------------
    @classmethod
    def empty(cls, read_scope: str = "open") -> "ContextGrant":
        return cls(items=(), granted_by=GRANTED_BY[0], read_scope=read_scope)

    @classmethod
    def from_public(cls, payload: dict, granted_by: str) -> "ContextGrant":
        """Rebuild from a control frame or a journal record. Strict."""
        if not isinstance(payload, dict):
            raise AgentHostError("grant_invalid", "a grant must be an object")
        raw_items = payload.get("items")
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise AgentHostError("grant_invalid", "grant items must be an array")
        items = []
        for entry in raw_items:
            if isinstance(entry, str):
                items.append(GrantItem("summary") if entry == "summary"
                             else GrantItem("region", parse_region_spec(entry)))
                continue
            if not isinstance(entry, dict):
                raise AgentHostError("grant_invalid",
                                     "a grant item is a string or an object")
            kind = entry.get("kind")
            if kind == "summary":
                items.append(GrantItem("summary"))
            elif kind == "region":
                address = entry.get("address")
                if address is None and isinstance(entry.get("spec"), str):
                    address = parse_region_spec(entry["spec"])
                items.append(GrantItem("region", address))
            else:
                raise AgentHostError(
                    "grant_invalid",
                    f"grant kind must be one of {list(GRANT_KINDS)}",
                    offered=kind)
        scope = payload.get("readScope", "open")
        return cls(items=tuple(items), granted_by=granted_by,
                   read_scope=scope if isinstance(scope, str) else "open")

    # -- identity ------------------------------------------------------------
    @property
    def keys(self) -> tuple:
        return tuple(item.key for item in self.items)

    @property
    def grant_id(self) -> str:
        """A hash of WHAT was granted, not of when or by whom.

        Two operators granting the same addresses produce the same id, which
        is what makes a reattach able to say "the same grant is still in
        force" rather than "a grant that looks similar".
        """
        body = json.dumps({"items": [item.public() for item in self.items],
                           "readScope": self.read_scope},
                          ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def is_empty(self) -> bool:
        return not self.items

    def public(self) -> dict:
        return {"schema": GRANT_SCHEMA, "grantId": self.grant_id,
                "grantedBy": self.granted_by, "readScope": self.read_scope,
                "items": [item.public() for item in self.items]}

    # -- the scope check -----------------------------------------------------
    def allows_region(self, address: dict) -> bool:
        try:
            key = address_key(address)
        except AgentHostError:
            return False
        return key in self.keys

    def check_read(self, method: str, params: dict) -> None:
        """Refuse a document read the operator did not authorise.

        Called by the compile gate, so the refusal happens before the Runtime
        is asked — the same posture as ``tool_forbidden``. Under the default
        ``open`` scope this is a no-op, and says so rather than pretending to
        have checked something.
        """
        if method != READ_REGION_METHOD or self.read_scope == "open":
            return
        if self.read_scope == "none":
            raise AgentHostError(
                "grant_scope_exceeded",
                "this host reads no document regions on the agent's behalf "
                "(readScope 'none')",
                method=method, readScope=self.read_scope)
        regions = (params or {}).get("regions")
        if not isinstance(regions, list) or not regions:
            raise AgentHostError("grant_scope_exceeded",
                                 "a scoped read must name the regions it wants",
                                 method=method, readScope=self.read_scope,
                                 granted=list(self.keys))
        outside = []
        for entry in regions:
            if not isinstance(entry, dict) or not self.allows_region(entry):
                outside.append(entry if isinstance(entry, dict) else repr(entry))
        if outside:
            raise AgentHostError(
                "grant_scope_exceeded",
                "the agent asked for document context outside the operator's "
                "grant; a grant can only be widened by an operator",
                method=method, readScope=self.read_scope,
                granted=list(self.keys), refused=outside)


@dataclass
class Disclosure:
    """What actually went into one prompt. Addresses and hashes, never text."""

    rows: list = field(default_factory=list)
    bytes_sent: int = 0

    def add(self, kind: str, spec: str | None, text: str) -> None:
        self.rows.append({"kind": kind, "spec": spec,
                          "bytes": len(text.encode("utf-8")),
                          "sha256": _digest(text)})
        self.bytes_sent += len(text.encode("utf-8"))

    def public(self) -> dict:
        return {"items": list(self.rows), "bytes": self.bytes_sent,
                "count": len(self.rows)}


def materialize(door, session_id: str, grant: ContextGrant) -> tuple[dict, Disclosure]:
    """Fetch the granted context from the Runtime, ready for a prompt.

    Returns ``(block, disclosure)``. ``block`` goes into the provider request
    and nowhere else; ``disclosure`` is the part that is safe to record.

    A Runtime refusal here is NOT swallowed: an operator who granted an
    address that does not exist should be told, not quietly given a prompt
    with less in it than they authorised.
    """
    disclosure = Disclosure()
    if grant.is_empty():
        return {}, disclosure

    block: dict = {"grantId": grant.grant_id, "grantedBy": grant.granted_by}
    if any(item.kind == "summary" for item in grant.items):
        result = door.call("document/inspect",
                           {"sessionId": session_id, "include": ["summary"]})
        summary = (result or {}).get("summary")
        if summary is not None:
            block["documentSummary"] = summary
            disclosure.add("summary", None,
                           json.dumps(summary, ensure_ascii=False,
                                      sort_keys=True, allow_nan=False))

    addresses = [item.address for item in grant.items if item.kind == "region"]
    if addresses:
        result = door.call(READ_REGION_METHOD,
                           {"sessionId": session_id, "regions": addresses})
        regions = (result or {}).get("regions") or []
        block["regions"] = regions
        for index, region in enumerate(regions):
            spec = (region.get("spec") if isinstance(region, dict) else None)
            if spec is None and index < len(addresses):
                spec = address_key(addresses[index])
            text = json.dumps(region, ensure_ascii=False, sort_keys=True,
                              allow_nan=False)
            disclosure.add("region", spec, text)
    return block, disclosure
