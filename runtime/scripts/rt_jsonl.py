#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSONL framing and strict JSON for the Runtime transport.

Stdlib only, and deliberately a REIMPLEMENTATION rather than an import of
``engine/scripts/document_evidence.py``. The pattern is that module's
(``_reject_duplicate_json_pairs`` at :1940, ``_reject_nonfinite_json_constant``
at :1960, ``_parse_finite_json_float`` at :1968, wired at :1979); what is NOT
reusable is its error type, which raises ``EvidenceError`` carrying a receipt
code and the receipt's path. A duplicate member in a request frame is not a
receipt defect, and the Runtime must not import ``engine/`` to parse a frame.

Framing rules (docs/runtime-protocol-v0.md §1.1):

  * one JSON object per line, UTF-8, ``\\n``-terminated;
  * an oversized inbound line is refused as ``frame_too_large`` WITHOUT being
    parsed — the reader stops at the cap and drains to the next newline;
  * stdout carries frames only; every diagnostic goes to stderr;
  * the outbound side is bounded too: a result that would exceed the cap
    becomes a ``response_too_large`` error frame rather than a giant line.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, BinaryIO

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import MAX_FRAME_BYTES, RpcError  # noqa: E402


class StrictJsonError(ValueError):
    """Carries the transport code the caller should emit."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Decode one object, refusing a repeated member.

    ``json`` invokes this for every nested object before the containing object
    is returned, so the refusal is recursive without extra work — the property
    T155 pinned for receipts (docs/trouble-table.md:36).
    """
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise StrictJsonError("duplicate_key", f"repeated member {key!r}")
        out[key] = value
    return out


def _reject_nonfinite_constant(constant: str) -> None:
    raise StrictJsonError("nonfinite_number", f"non-finite JSON constant {constant}")


def _parse_finite_float(text: str) -> float:
    """Also catches an overflowing literal, not only the three constants."""
    value = float(text)
    if not math.isfinite(value):
        raise StrictJsonError("nonfinite_number", f"non-finite number {text}")
    return value


def loads_strict(text: str) -> Any:
    """Parse with duplicate-key and finite-number refusal. Raises StrictJsonError."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_parse_finite_float,
        )
    except json.JSONDecodeError as exc:
        raise StrictJsonError("frame_malformed", f"not valid JSON: {exc}") from exc


def dumps_frame(payload: dict) -> bytes:
    """Compact single-line UTF-8 bytes, newline terminated, never non-finite."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)
    return (text + "\n").encode("utf-8")


def canonical_bytes(payload: dict, *, omit: tuple[str, ...] = ()) -> bytes:
    """Deterministic bytes for anything that gets hashed.

    Same recipe as ``pipeline/scripts/receipt_sign.canonical_json_bytes``
    (pipeline/scripts/receipt_sign.py:36): sorted keys, no whitespace, finite
    numbers only, named top-level fields omitted so a self-hash can be written
    back into the object it covers.
    """
    if not isinstance(payload, dict):
        raise TypeError("canonical payload must be an object")
    body = {key: value for key, value in payload.items() if key not in omit}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


# --- inbound ---------------------------------------------------------------

READ_EOF = "eof"
READ_LINE = "line"
READ_OVERSIZE = "oversize"


def read_raw_frame(stream: BinaryIO,
                   max_bytes: int = MAX_FRAME_BYTES) -> tuple[str, bytes | None]:
    """Read one line, refusing an oversized one without parsing it.

    ``readline(limit)`` stops at the limit, so an attacker cannot make the
    Runtime materialise an unbounded string just to discover it is too long.
    When the cap is hit the rest of the line is drained in bounded chunks and
    discarded, so the NEXT frame still starts at a frame boundary.
    """
    line = stream.readline(max_bytes + 2)
    if not line:
        return READ_EOF, None
    if line.endswith(b"\n"):
        body = line[:-1]
        if len(body) > max_bytes:
            return READ_OVERSIZE, None
        return READ_LINE, body
    # No newline within the cap: either an oversized frame or a truncated tail.
    while True:
        chunk = stream.readline(65536)
        if not chunk or chunk.endswith(b"\n"):
            break
    return READ_OVERSIZE, None


def decode_frame(raw: bytes) -> dict:
    """Bytes -> a JSON object, strictly. Raises StrictJsonError."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise StrictJsonError("frame_malformed", "frame is not valid UTF-8") from exc
    value = loads_strict(text)
    if not isinstance(value, dict):
        raise StrictJsonError("frame_malformed", "frame must be a JSON object")
    return value


# --- outbound --------------------------------------------------------------

class FrameWriter:
    """Serialises frames onto one stream under a lock. stdout, and only frames."""

    def __init__(self, stream: BinaryIO, lock, max_bytes: int = MAX_FRAME_BYTES):
        self._stream = stream
        self._lock = lock
        self._max = max_bytes

    def send(self, frame: dict) -> None:
        data = dumps_frame(frame)
        if len(data) - 1 > self._max:
            frame_id = frame.get("id")
            data = dumps_frame({
                "kind": "error", "id": frame_id,
                "error": {
                    "code": "response_too_large",
                    "message": (f"result exceeds the {self._max}-byte frame cap; "
                                "narrow the request"),
                    "data": {"limit": self._max, "bytes": len(data) - 1},
                },
            })
        with self._lock:
            self._stream.write(data)
            self._stream.flush()

    def respond(self, request_id, result: dict) -> None:
        self.send({"kind": "response", "id": request_id, "result": result})

    def fail(self, request_id, error: RpcError) -> None:
        self.send({"kind": "error", "id": request_id,
                   "error": error.to_frame_error()})

    def notify(self, method: str, params: dict) -> None:
        self.send({"kind": "notification", "method": method, "params": params})


def log(message: str) -> None:
    """Diagnostics go to stderr. stdout is frames only, always."""
    print(message, file=sys.stderr, flush=True)
