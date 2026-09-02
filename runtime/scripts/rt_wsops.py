#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Workspace write ops: the fix loop's write half (§15.6).

A workspace session opened, summarised and ran its checkers, and then stopped.
The checkers produce findings ABOUT FILES — ``bundle/content.md`` says X,
``claims.yaml`` cites a source id nothing defines — and there was no way to act
on one. So the loop had a read half and no write half: an agent could see the
finding and could not propose the fix.

THE OP SET IS CLOSED, AND SMALL ON PURPOSE. Three kinds, each one a change a
checker finding can actually ask for:

  * ``ws_replace_text`` — an anchored edit of a UTF-8 member. The anchor must
    match EXACTLY ONCE. Not "first match": a workspace is a person's report and
    the same sentence appears twice in it more often than not, and picking one
    silently is how an edit lands in the wrong section.
  * ``ws_set_yaml_key`` — one dotted key, one scalar, one line rewritten. The
    file keeps its comments, its order and its every other byte, which a
    load-and-dump through a YAML library would not.
  * ``ws_append_source`` — one record onto ``research/sources.json``, the
    vocabulary ``claims_ledger.source_identity_groups`` reads
    (modules/report/scripts/claims_ledger.py:325-336).

WHAT IS NOT HERE, RECORDED AS GAP RATHER THAN GUESSED AT. No create, no delete,
no rename. Every op above needs a member that already exists and leaves the
tree's shape untouched, so the tree hash moves for content and never for
membership. Creating a file is the organizer's job (a stage produces it) and
deleting one destroys a person's work; both want their own approval shape and
neither is smuggled in as a text edit. ``WS_NOT_IMPLEMENTED`` names them.

BINARY MEMBERS ARE NEVER OPERABLE. A member is operable only if it decodes as
UTF-8 and holds no NUL; ``bundle/figures/*.png`` therefore refuses, and it
refuses at pre-flight rather than after a half-written file. Nothing here has a
byte-editing mode and nothing should: an image is replaced by the tool that
made it.

READ-ONLY PARTS REFUSE. A module's ``read_only_paths`` (§15.1) declares the
paths a checker READS and no stage routes — ``.pipeline/handoff.json``,
``_saeteuk/``, the simulation's provenance. Writing one would be the Runtime
editing the evidence a checker is about to read. Core does not hold that list;
it comes from the declaration, the same way the layout does.

PRE-FLIGHT IS THE OPS, RUN. Validation copies the session workspace to scratch,
runs the ops on the copy, and deletes it. That is not an approximation of what
apply does — it is the same function over a different root, which is the only
way a "clean validation" means anything for ops whose second step depends on
the first one's output.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import RpcError  # noqa: E402

#: The backend a workspace plan declares. A plan declares its backend
#: (decision D9) and this one is served by this module, not by an engine
#: script: a report workspace is the Runtime's own object.
WS_BACKEND = "workspace"

#: kind: (required fields, optional fields)
WS_OP_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ws_replace_text": (("path", "old", "new"), ()),
    "ws_set_yaml_key": (("path", "key", "value"), ()),
    "ws_append_source": (("source",), ("path",)),
}
WS_OP_KINDS = tuple(WS_OP_FIELDS)

#: Op kinds a workspace fix loop will want and this slice does not have. Named
#: on the wire (``capabilities/list``) so a caller reads a gap rather than
#: inferring one from an ``unknown_op_kind``.
WS_NOT_IMPLEMENTED: tuple[str, ...] = (
    "ws_create_member",   # a stage produces a file; the organizer's job
    "ws_delete_member",   # destroys a person's work; wants its own approval
    "ws_rename_member",   # a delete and a create, with both problems
)

#: Every reason an op can be refused at pre-flight. Closed, and asserted
#: closed by the tests — the same discipline ``WORKSPACE_REJECT_REASONS``
#: applies to ingress. These are FINDING codes, not transport codes: a plan
#: that carries one does not validate, and ``plan/apply`` refuses it with
#: ``plan_invalid`` rather than a second vocabulary.
WS_REFUSAL_CODES: tuple[str, ...] = (
    "op_field_invalid",
    "path_not_relative",
    "member_missing",
    "member_not_text",
    "member_too_large",
    "member_read_only",
    "anchor_not_found",
    "anchor_ambiguous",
    "yaml_unparseable",
    "yaml_key_unknown",
    "yaml_key_ambiguous",
    "yaml_key_not_scalar",
    "yaml_inline_comment",
    "source_container_invalid",
    "source_duplicate_id",
)

#: One member this reads into memory whole. Well under the workspace bound —
#: a text member of a report is kilobytes, and a four-megabyte one is a
#: generated artifact nothing here should be rewriting by anchor.
MAX_MEMBER_BYTES = 4 * 1024 * 1024

DEFAULT_SOURCES_PATH = "research/sources.json"

#: What may be written without quotes: a plain ASCII token, nothing more.
#: A bare scalar with a space in it is legal YAML and still the wrong thing to
#: write — the next person appends " # note" to it, or a colon, and the file
#: changes meaning silently. Everything else goes out double-quoted, which is
#: what the product's own templates already do for prose values.
_BARE_SCALAR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./+-]*$")
_RESERVED_BARE = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_][A-Za-z0-9_.\-]*):"
                       r"(?P<rest>.*)$")


def finding(code: str, msg: str, at: str, **extra) -> dict:
    assert code in WS_REFUSAL_CODES, f"undeclared refusal code: {code!r}"
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


# --- addressing ---------------------------------------------------------------

def normalise_member(raw) -> str | None:
    """A workspace-relative posix path, or None if it is not one."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def read_only_matcher(layout: dict):
    """Which members a module declared read-only. Core holds no such list.

    The declaration's own vocabulary (§15.1): a ``read_only`` part is a file, a
    directory (everything under it) or a glob. Anything else in the layout is
    routed by a stage and is writable.
    """
    parts = [part for part in (layout or {}).get("parts", [])
             if part.get("source") == "read_only"]

    def matches(member: str) -> dict | None:
        for part in parts:
            path = part["path"]
            kind = part.get("kind")
            if kind == "directory":
                if member == path or member.startswith(path + "/"):
                    return part
            elif kind == "glob":
                if Path(member).match(path):
                    return part
            elif member == path:
                return part
        return None

    return matches


def _member(root: Path, raw, at: str) -> tuple[Path | None, str | None, dict | None]:
    member = normalise_member(raw)
    if member is None:
        return None, None, finding(
            "path_not_relative",
            "path must be a workspace-relative path with no '..' component and "
            "no drive or root", at, path=raw)
    path = root / member
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None, member, finding(
            "path_not_relative", "path resolves outside the workspace", at,
            path=member)
    return path, member, None


def _read_member(path: Path, member: str, at: str) -> tuple[str | None, dict | None]:
    if not path.is_file():
        return None, finding("member_missing",
                             "the workspace has no such file; this build creates "
                             "nothing", at, path=member,
                             notImplemented=list(WS_NOT_IMPLEMENTED))
    size = path.stat().st_size
    if size > MAX_MEMBER_BYTES:
        return None, finding("member_too_large",
                             "the member is larger than this build edits in one "
                             "piece", at, path=member, bytes=size,
                             limit=MAX_MEMBER_BYTES)
    data = path.read_bytes()
    if b"\x00" in data:
        return None, finding("member_not_text",
                             "the member holds NUL bytes, so it is not text; "
                             "binary members are never operable here", at,
                             path=member)
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, finding("member_not_text",
                             "the member is not valid UTF-8; binary members are "
                             "never operable here", at, path=member,
                             detail=str(exc)[:200])


def read_member(root: Path, raw, at: str = "path") -> tuple[str | None, str | None, dict | None]:
    """Resolve and read one workspace member, for a caller that only reads.

    ``_member`` then ``_read_member`` — the exact two steps a write op runs
    before it touches a byte — exposed on their own for ``workspace/readMember``
    (§15.8's first gap: an agent could propose an edit and could not read the
    member to aim it). Returns ``(text, member, refusal)``; a refusal is a
    finding dict from the same closed vocabulary a write op refuses with, so a
    caller sees one rule for "can this path be read" everywhere it is asked.
    """
    path, member, refusal = _member(root, raw, at)
    if refusal is not None:
        return None, member, refusal
    text, refusal = _read_member(path, member, at)
    if refusal is not None:
        return None, member, refusal
    return text, member, None


# --- the YAML scalar index ------------------------------------------------------

class _Unparseable(Exception):
    def __init__(self, line_no: int, detail: str):
        self.line_no = line_no
        self.detail = detail
        super().__init__(detail)


def scalar_index(text: str) -> dict[str, list[dict]]:
    """Dotted key -> the scalar lines that declare it.

    A hand-written scanner, and deliberately so: PyYAML is an OPTIONAL
    dependency in this repository (pipeline/scripts/backend_precheck.py:124),
    and a load-and-dump would rewrite a person's comments, key order and
    quoting to change one value. This models exactly the shape the product's
    own declarations use — block mappings of scalars, with sequences and
    block scalars recognised and declared un-addressable — and raises
    ``_Unparseable`` on anything else instead of guessing.
    """
    index: dict[str, list[dict]] = {}
    stack: list[tuple[int, str]] = []
    skip_below: int | None = None
    for line_no, raw in enumerate(text.splitlines()):
        if skip_below is not None:
            indent_here = len(raw) - len(raw.lstrip(" "))
            if raw.strip() and indent_here <= skip_below:
                skip_below = None
            else:
                continue
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise _Unparseable(line_no, "a tab in the indentation")
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw.strip()
        if body.startswith("-"):
            # A sequence item. Its contents are not addressed by a dotted key
            # here, so the whole block is skipped rather than half-indexed.
            skip_below = indent
            continue
        if body.startswith("---") or body.startswith("..."):
            raise _Unparseable(line_no, "a document marker")
        match = _KEY_LINE.match(raw)
        if match is None:
            raise _Unparseable(line_no, "a line this build does not model")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = match.group("key")
        rest = match.group("rest")
        dotted = ".".join([name for _, name in stack] + [key])
        value = rest.strip()
        if value in ("", "|", ">", "|-", ">-", "|+", ">+"):
            if value:
                # A block scalar: present, addressable, but not a one-line
                # scalar, so it is recorded as such and its body skipped.
                index.setdefault(dotted, []).append(
                    {"line": line_no, "indent": indent, "key": key,
                     "scalar": False, "reason": "block scalar"})
                skip_below = indent
                continue
            stack.append((indent, key))
            index.setdefault(dotted, []).append(
                {"line": line_no, "indent": indent, "key": key,
                 "scalar": False, "reason": "a nested block, not a scalar"})
            continue
        index.setdefault(dotted, []).append(
            {"line": line_no, "indent": indent, "key": key, "scalar": True,
             "value": value})
    return index


def format_scalar(value) -> str | None:
    """One YAML scalar, or None if this is not a scalar this build writes."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return repr(value)
    if not isinstance(value, str):
        return None
    if (value and value.casefold() not in _RESERVED_BARE
            and _BARE_SCALAR.match(value) and value == value.strip()
            and not _looks_numeric(value)):
        return value
    # JSON's double-quoted string is a valid YAML double-quoted scalar, and
    # ensure_ascii=False keeps Korean text readable in the file.
    return json.dumps(value, ensure_ascii=False)


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# --- the ops ---------------------------------------------------------------------

def _op_replace_text(root: Path, params: dict, at: str, member: str,
                     path: Path) -> tuple[dict | None, dict | None]:
    old, new = params.get("old"), params.get("new")
    if not isinstance(old, str) or not old:
        return None, finding("op_field_invalid",
                             "old must be a non-empty string anchor", at)
    if not isinstance(new, str):
        return None, finding("op_field_invalid", "new must be a string", at)
    if old == new:
        return None, finding("op_field_invalid",
                             "old and new are the same text, so this op would "
                             "write nothing", at)
    text, refusal = _read_member(path, member, at)
    if refusal is not None:
        return None, refusal
    occurrences = text.count(old)
    if occurrences == 0:
        return None, finding("anchor_not_found",
                             "the anchor text does not occur in this member", at,
                             path=member, anchorChars=len(old))
    if occurrences > 1:
        return None, finding(
            "anchor_ambiguous",
            f"the anchor occurs {occurrences} times; extend it until it names "
            "one place, because picking one is how an edit lands in the wrong "
            "section", at, path=member, occurrences=occurrences)
    updated = text.replace(old, new, 1)
    path.write_bytes(updated.encode("utf-8"))
    return {"occurrences": 1, "anchorChars": len(old)}, None


def _op_set_yaml_key(root: Path, params: dict, at: str, member: str,
                     path: Path) -> tuple[dict | None, dict | None]:
    key = params.get("key")
    if not isinstance(key, str) or not key.strip():
        return None, finding("op_field_invalid",
                             "key must be a non-empty dotted key", at)
    key = key.strip()
    formatted = format_scalar(params.get("value"))
    if formatted is None:
        return None, finding(
            "op_field_invalid",
            "value must be a scalar this build can write: a string, an integer, "
            "a finite float, a boolean or null", at, key=key)
    text, refusal = _read_member(path, member, at)
    if refusal is not None:
        return None, refusal
    try:
        index = scalar_index(text)
    except _Unparseable as exc:
        return None, finding("yaml_unparseable",
                             "this build does not model that file's YAML, so it "
                             "will not rewrite a line in it", at, path=member,
                             line=exc.line_no + 1, detail=exc.detail)
    rows = index.get(key)
    if not rows:
        return None, finding("yaml_key_unknown",
                             "the file declares no such key; this build sets an "
                             "existing key and never invents one", at,
                             path=member, key=key,
                             knownKeys=sorted(index)[:64])
    if len(rows) > 1:
        return None, finding("yaml_key_ambiguous",
                             f"the key is declared on {len(rows)} lines; nothing "
                             "here picks one", at, path=member, key=key,
                             lines=[row["line"] + 1 for row in rows])
    row = rows[0]
    if not row["scalar"]:
        return None, finding("yaml_key_not_scalar",
                             "the key holds %s, and this op sets a scalar"
                             % row.get("reason", "a structure"), at,
                             path=member, key=key, line=row["line"] + 1)
    if "#" in row["value"]:
        return None, finding(
            "yaml_inline_comment",
            "the line carries an inline comment; rewriting the value would "
            "either drop it or guess where it ends", at, path=member, key=key,
            line=row["line"] + 1)
    lines = text.splitlines(keepends=True)
    original = lines[row["line"]]
    ending = original[len(original.rstrip("\r\n")):]
    lines[row["line"]] = (" " * row["indent"] + row["key"] + ": " + formatted
                          + ending)
    path.write_bytes("".join(lines).encode("utf-8"))
    return {"key": key, "line": row["line"] + 1, "was": row["value"],
            "now": formatted}, None


def _op_append_source(root: Path, params: dict, at: str, member: str,
                      path: Path) -> tuple[dict | None, dict | None]:
    record = params.get("source")
    if not isinstance(record, dict):
        return None, finding("op_field_invalid",
                             "source must be an object", at)
    source_id = record.get("id")
    if not isinstance(source_id, str) or not source_id.strip():
        return None, finding("op_field_invalid",
                             "source.id must be a non-empty string; it is the id "
                             "a claim's evidence cites", at)
    text, refusal = _read_member(path, member, at)
    if refusal is not None:
        return None, refusal
    try:
        payload = json.loads(text)
    except ValueError as exc:
        return None, finding("source_container_invalid",
                             "the source list does not parse as JSON", at,
                             path=member, detail=str(exc)[:200])
    if not isinstance(payload, list):
        return None, finding(
            "source_container_invalid",
            "the source list must be a JSON array of records; that is the shape "
            "claims_ledger.source_identity_groups reads "
            "(modules/report/scripts/claims_ledger.py:330), and a record "
            "appended to any other shape would be invisible to every checker",
            at, path=member, found=type(payload).__name__)
    for existing in payload:
        if isinstance(existing, dict) and existing.get("id") == source_id:
            return None, finding("source_duplicate_id",
                                 "the source list already defines that id", at,
                                 path=member, sourceId=source_id)
    payload.append(record)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2)
                      + "\n").encode("utf-8"))
    return {"sourceId": source_id, "sources": len(payload)}, None


_OP_RUNNERS = {
    "ws_replace_text": _op_replace_text,
    "ws_set_yaml_key": _op_set_yaml_key,
    "ws_append_source": _op_append_source,
}


def run_ops(root: Path, ops: list, *, read_only) -> dict:
    """Execute the ops against ``root`` in order. One code path, two roots.

    Pre-flight calls this on a scratch copy and apply calls it on the candidate
    tree. Stops at the first op that refuses — a later op's anchor may only
    exist because an earlier one wrote it, so evaluating past a refusal would
    report findings about a tree nobody will have.
    """
    steps: list[dict] = []
    hard: list[dict] = []
    not_evaluated: list[str] = []
    for index, op in enumerate(ops):
        at = f"ops[{op['opId']}]"
        if hard:
            not_evaluated.append(op["opId"])
            continue
        kind, params = op["kind"], dict(op["params"])
        member_raw = params.get("path", DEFAULT_SOURCES_PATH
                                if kind == "ws_append_source" else None)
        path, member, refusal = _member(root, member_raw, at)
        if refusal is not None:
            hard.append(refusal)
            continue
        blocked = read_only(member)
        if blocked is not None:
            hard.append(finding(
                "member_read_only",
                "an enabled module declares this path read-only: a checker reads "
                "it and no stage routes it, so writing it would edit the evidence "
                "a checker is about to read", at, path=member,
                role=blocked.get("role"), declaredAs=blocked.get("path")))
            continue
        detail, refusal = _OP_RUNNERS[kind](root, params, at, member, path)
        if refusal is not None:
            hard.append(refusal)
            continue
        step = {"opId": op["opId"], "kind": kind, "path": member,
                "index": index}
        step.update(detail)
        steps.append(step)
    return {"steps": steps, "hard": hard, "notEvaluated": not_evaluated}


def preflight(workspace: Path, ops: list, *, read_only, scratch_parent: Path) -> dict:
    """Run the ops on a throwaway copy of the workspace. Never touches it."""
    from rt_workspace import copy_tree  # noqa: PLC0415

    scratch = scratch_parent / f"preflight-{uuid.uuid4().hex}"
    try:
        try:
            copy_tree(workspace, scratch / workspace.name)
        except OSError as exc:
            raise RpcError("capability_unavailable",
                           "could not stage a scratch copy of the workspace, so "
                           "the plan was not validated against anything",
                           detail=str(exc)[:400]) from exc
        return run_ops(scratch / workspace.name, ops, read_only=read_only)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
