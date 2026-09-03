#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OperationPlan, PlanValidation, ApprovalRequest/ApprovalRecord.

A plan declares its backend (orchestrator decision D9). This slice can execute
``preedit`` only; ``xml`` and ``com`` plans are refused with
``unsupported_backend`` that NAMES the backend which would serve them, so the
refusal is a routing answer rather than a wall.

WHAT "validate without executing" ACTUALLY MEANS HERE — recorded, because the
design doc promised more than the code can give:

``preedit``'s own refusals are raised from inside its execution path
(``ScriptAnomalyError`` at engine/scripts/preedit.py:136,
``AmbiguousCellRunError`` at :180, ``AmbiguousReplaceKeyError`` at :221 are all
thrown while the edit walks the document), and it ships no ``--dry-run``.
There is no way to reach that validator without either executing or editing
``engine/``, which this slice may not do.

So validation is derived from the SAME FACTS the engine uses, taken from
``form_inspect``'s preflight instead of from preedit's exception path:

  * ``table_map[*].cells[*].script_anomaly`` / ``charpr_suggested`` — the T30
    preflight, engine/scripts/form_inspect.py:620;
  * ``table_map[*].cells[*].color_anomaly`` — T127, same place;
  * ``--full-text`` run records — engine/scripts/form_inspect.py:913, whose run
    index is deliberately the same enumeration ``preedit --at-cell ROW,COL#RUN``
    edits (engine/scripts/form_inspect.py:122-125).

That reproduces the two refusals that matter (T30 anomaly, ambiguous cell run)
with the same code names preedit emits. Anything it cannot reach is listed in
``preflight.deferred`` rather than silently assumed clean, and preedit's own
refusal payload is passed through verbatim at apply.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    APPROVAL_DECISIONS,
    IMPL_VERSION,
    KNOWN_BACKENDS,
    PLAN_SCHEMA,
    SUPPORTED_BACKENDS,
    RpcError,
)
from rt_jsonl import canonical_bytes  # noqa: E402
from rt_session import full_text_spec, now_utc  # noqa: E402

# --- op kinds ---------------------------------------------------------------
#: What this backend can execute, mapped onto the preedit subcommand that does
#: it (engine/scripts/preedit.py:2425, :2464, :2479, :2520).
PREEDIT_OP_KINDS: dict[str, str] = {
    "fill_cell": "fill-cells",
    "replace_at_cell": "replace",
    "set_run": "set-runs",
    "delete_guides": "delete-guides",
}
#: A real preedit subcommand this slice deliberately does not expose: its
#: contract is a header-level charPr rewrite with a post-check
#: (engine/scripts/preedit.py:2526, guards.assert_no_dangling_charpr at
#: engine/scripts/guards.py:142), which needs its own plan shape.
PREEDIT_NOT_IMPLEMENTED = ("normalize_clones",)

#: engine/scripts/xml_backend.py:27
XML_OP_KINDS = frozenset({
    "goto_text", "insert_text", "insert_equation", "insert_table",
    "page_binding", "replace_all", "insert_blank_before", "insert_picture",
    "set_line_spacing",
})
#: engine/scripts/com_backend.py:1598 (22 entries, verified against the source)
COM_OP_KINDS = frozenset({
    "replace_all", "put_field", "goto_text", "find_delete", "move",
    "insert_text", "insert_equation", "edit_equation", "insert_table",
    "insert_picture", "set_cell", "set_char_color", "delete_ctrls",
    "collapse_empty_paragraphs", "delete_blank_after", "delete_blank_before",
    "set_para_align", "insert_blank_before", "insert_hyperlink",
    "page_binding", "set_line_spacing", "page_break_before",
})

#: Refusals only the engine can raise, listed so a clean validation is never
#: read as "apply cannot refuse".
DEFERRED_REFUSALS = (
    "replace_key_ambiguous",
    "at_cell_expect_mismatch",
    "xml_wellformedness",
)

_OP_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # kind: (required, optional)
    "fill_cell": (("row", "col"),
                  ("table", "text", "lines", "charPr", "paraPr", "overwrite")),
    "replace_at_cell": (("row", "col", "text"),
                        ("table", "run", "mode", "expect", "charPr")),
    "set_run": (("atPara", "run", "text"), ()),
    "delete_guides": ((), ("color", "charPrIds")),
}


def _finding(code: str, msg: str, at: str, **extra) -> dict:
    row = {"code": code, "msg": msg, "at": at}
    row.update(extra)
    return row


def _check_int(value, name, at, hard):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        hard.append(_finding("op_field_invalid",
                             f"{name} must be a non-negative integer", at))
        return None
    return value


class OperationPlan:
    def __init__(self, payload: dict):
        self.payload = payload

    @property
    def id(self) -> str:
        return self.payload["planId"]

    @property
    def hash(self) -> str:
        return self.payload["planHash"]

    @property
    def state(self) -> str:
        return self.payload["state"]

    @state.setter
    def state(self, value: str) -> None:
        self.payload["state"] = value

    def public(self) -> dict:
        return dict(self.payload)


def _classify_foreign_kind(kind: str) -> str | None:
    if kind in XML_OP_KINDS and kind in COM_OP_KINDS:
        return "xml or com"
    if kind in XML_OP_KINDS:
        return "xml"
    if kind in COM_OP_KINDS:
        return "com"
    return None


def build_plan(*, session_id: str, backend: str, ops: list, proposer: str,
               bound_sha256: str, base: dict | None = None,
               reverses: dict | None = None) -> OperationPlan:
    """Create a plan. Refuses an unservable backend or op kind before anything else.

    ``base`` is the published candidate these ops are chained onto, or ``None``
    for the session source. ``bound_sha256`` is that subject's digest either
    way, so a plan on a candidate binds the candidate's bytes and ``opsHash``
    separates two identical edits made at different points in the chain — the
    Phase 2 parity property survives unchanged because the subject is still one
    digest.

    ``reverses`` names the candidate this plan undoes, when it undoes one. The
    runtime records the claim; it does not derive it. What makes the claim
    checkable is ``candidate/compare`` after the apply, not this field.
    """
    if backend not in SUPPORTED_BACKENDS:
        known = backend in KNOWN_BACKENDS
        raise RpcError(
            "unsupported_backend",
            (f"backend {backend!r} is declared by the protocol but this build "
             f"executes only {', '.join(SUPPORTED_BACKENDS)}")
            if known else f"unknown backend {backend!r}",
            declared=backend, supported=list(SUPPORTED_BACKENDS),
            known=list(KNOWN_BACKENDS))
    if not isinstance(ops, list) or not ops:
        raise RpcError("invalid_params", "ops must be a non-empty array")

    normalised = []
    seen_ids: set[str] = set()
    for index, op in enumerate(ops):
        at = f"ops[{index}]"
        if not isinstance(op, dict):
            raise RpcError("invalid_params", f"{at} must be an object")
        kind = op.get("kind")
        if not isinstance(kind, str):
            raise RpcError("invalid_params", f"{at}.kind must be a string")
        if kind not in PREEDIT_OP_KINDS:
            owner = _classify_foreign_kind(kind)
            if owner is not None:
                raise RpcError(
                    "unsupported_backend",
                    f"op kind {kind!r} is served by the {owner} backend, which "
                    "this build does not execute",
                    at=at, kind=kind, servedBy=owner,
                    supported=list(SUPPORTED_BACKENDS))
            raise RpcError(
                "unknown_op_kind",
                f"op kind {kind!r} is not known to the "
                f"{', '.join(SUPPORTED_BACKENDS)} backend",
                at=at, kind=kind, knownKinds=sorted(PREEDIT_OP_KINDS),
                notImplemented=list(PREEDIT_NOT_IMPLEMENTED))
        required, optional = _OP_FIELDS[kind]
        allowed = set(required) | set(optional) | {"kind", "opId"}
        unknown = sorted(set(op) - allowed)
        if unknown:
            raise RpcError("unknown_field",
                           f"{at} carries fields this op kind does not define",
                           at=at, kind=kind, unknown=unknown,
                           allowed=sorted(allowed))
        missing = [name for name in required if name not in op]
        if missing:
            raise RpcError("invalid_params", f"{at} is missing required fields",
                           at=at, kind=kind, missing=missing)
        op_id = op.get("opId") or f"op-{index + 1}"
        if not isinstance(op_id, str) or op_id in seen_ids:
            raise RpcError("invalid_params",
                           f"{at}.opId must be a string unique within the plan",
                           at=at, opId=op_id)
        seen_ids.add(op_id)
        params = {key: value for key, value in op.items()
                  if key not in ("kind", "opId")}
        normalised.append({"opId": op_id, "kind": kind, "params": params})

    payload = {
        "schema": PLAN_SCHEMA,
        "planId": uuid.uuid4().hex,
        "sessionId": session_id,
        "backend": backend,
        "boundSha256": bound_sha256,
        "base": dict(base) if base else None,
        "reverses": dict(reverses) if reverses else None,
        "createdUtc": now_utc(),
        "proposer": proposer,
        "implVersion": IMPL_VERSION,
        "ops": normalised,
        "state": "proposed",
    }
    payload["opsHash"] = ops_hash(backend, bound_sha256, normalised)
    payload["planHash"] = hashlib.sha256(
        canonical_bytes(payload, omit=("state",))).hexdigest()
    return OperationPlan(payload)


def ops_hash(backend: str, bound_sha256: str, ops: list) -> str:
    """Hash the INTENT: this document, this backend, these operations.

    Two hashes, two jobs, and conflating them is how a parity claim turns into
    a tautology:

      * ``planHash`` covers the whole object, identity and timestamp included.
        That is what an approval binds to, and it must differ between two
        proposals of the same edit — otherwise approving one would approve the
        other (``resolve_approval`` below).
      * ``opsHash`` covers only what the caller asked for against the bytes it
        asked against. It is identical whenever the document, the target and
        the operation are identical, no matter which front end proposed it or
        when. That is the Phase 2 exit property, and
        ``tests/test_runtime_parity.py`` measures it.
    """
    return hashlib.sha256(canonical_bytes({
        "backend": backend,
        "boundSha256": bound_sha256,
        "ops": ops,
    })).hexdigest()


# --- validation -------------------------------------------------------------

def _cell_index(profile: dict) -> dict[tuple[int, int, int], dict]:
    index: dict[tuple[int, int, int], dict] = {}
    for table in profile.get("table_map", []):
        for cell in table.get("cells", []):
            addr = cell.get("addr") or {}
            try:
                key = (int(table.get("index")), int(addr["row"]), int(addr["col"]))
            except (TypeError, ValueError, KeyError):
                continue
            index[key] = cell
    return index


def wanted_full_text(plan: OperationPlan) -> list[str]:
    """--full-text specs the profile-derived checks need, deduplicated."""
    specs: list[str] = []
    for op in plan.payload["ops"]:
        kind, params = op["kind"], op["params"]
        entry = None
        if kind == "replace_at_cell":
            entry = {"table": params.get("table", 0),
                     "row": params.get("row"), "col": params.get("col")}
        elif kind == "set_run":
            entry = {"atPara": params.get("atPara")}
        if entry is None:
            continue
        try:
            spec = full_text_spec(entry)
        except (TypeError, ValueError, KeyError):
            continue
        if spec not in specs:
            specs.append(spec)
    return specs


def _full_text_lookup(profile: dict) -> tuple[dict, dict]:
    """(cells_by_addr, paras_by_at_para) from a profile's opt-in full_text."""
    cells: dict[tuple[int, int, int], dict] = {}
    paras: dict[int, dict] = {}
    # Shapes are form_inspect's own: a paragraph request answers with
    # ``at_para``/``runs`` and a cell request with ``table``/``addr``/``runs``
    # (engine/scripts/form_inspect.py:965-1039).
    for entry in profile.get("full_text", []) or []:
        if "at_para" in entry:
            try:
                paras[int(entry["at_para"])] = entry
            except (TypeError, ValueError):
                continue
            continue
        addr = entry.get("addr") or {}
        try:
            cells[(int(entry.get("table", 0)), int(addr["row"]),
                   int(addr["col"]))] = entry
        except (TypeError, ValueError, KeyError):
            continue
    return cells, paras


def safe_full_text_specs(specs: list[str], base_profile: dict) -> list[str]:
    """Drop cell specs the base profile says do not exist.

    ``--full-text`` on a missing cell is a usage exit from form_inspect
    (engine/scripts/form_inspect.py:1032-1037), which would take the whole
    validation down instead of producing a ``cell_address_unknown`` finding.
    Paragraph specs cannot be pre-checked (``at_para`` addresses every
    paragraph, not just anchors), so they are attempted and the caller falls
    back if the child refuses.
    """
    cells = _cell_index(base_profile)
    keep: list[str] = []
    for spec in specs:
        if spec.startswith("PARA:"):
            keep.append(spec)
            continue
        try:
            table_text, _, addr_text = spec.partition(":")
            row_text, _, col_text = addr_text.partition(",")
            key = (int(table_text), int(row_text), int(col_text))
        except (TypeError, ValueError):
            continue
        if key in cells:
            keep.append(spec)
    return keep


def validate_plan(plan: OperationPlan, *, profile: dict,
                  current_sha256: str) -> dict:
    """PlanValidation (§3.7). Never executes anything."""
    hard: list[dict] = []
    warn: list[dict] = []
    stale = plan.payload["boundSha256"] != current_sha256
    if stale:
        hard.append(_finding(
            "plan_stale",
            "the session source changed after this plan was proposed; re-propose "
            "against the current bytes",
            "plan",
            boundSha256=plan.payload["boundSha256"],
            currentSha256=current_sha256))

    cells = _cell_index(profile)
    ft_cells, ft_paras = _full_text_lookup(profile)

    for op in plan.payload["ops"]:
        at = f"ops[{op['opId']}]"
        kind, params = op["kind"], op["params"]

        if kind in ("fill_cell", "replace_at_cell"):
            table = params.get("table", 0)
            row, col = params.get("row"), params.get("col")
            if (_check_int(table, "table", at, hard) is None
                    or _check_int(row, "row", at, hard) is None
                    or _check_int(col, "col", at, hard) is None):
                continue
            cell = cells.get((int(table), int(row), int(col)))
            if cell is None:
                hard.append(_finding(
                    "cell_address_unknown",
                    f"table {table} has no cell at ({row},{col}) in this document",
                    at, table=table, row=row, col=col))
                continue
            classification = cell.get("classification")
            if classification != "fill_target":
                warn.append(_finding(
                    "cell_not_fill_target",
                    f"cell ({row},{col}) is classified {classification!r}, not a "
                    "fill target; the form scan does not expect a value here",
                    at, classification=classification))
            if cell.get("script_anomaly") and not params.get("charPr"):
                suggested = cell.get("charpr_suggested")
                hard.append(_finding(
                    "fill_charpr_script_anomaly",
                    "preserving this run's charPr means printing smaller or "
                    "narrower than the body baseline (T30); declare charPr",
                    at, charPr=cell.get("charpr"), charPrSuggested=suggested,
                    preeditFlag=["--charpr-per-cell", f"{row},{col}={suggested}"]))
            if cell.get("color_anomaly") and not params.get("charPr"):
                warn.append(_finding(
                    "fill_charpr_color_anomaly",
                    "this run's charPr is not black/auto, so the fill would take "
                    "the guide colour (T127); declare charPr to override",
                    at, colorValue=cell.get("color_value")))

        if kind == "fill_cell":
            has_text = isinstance(params.get("text"), str)
            lines = params.get("lines")
            has_lines = isinstance(lines, list) and all(
                isinstance(item, str) for item in lines)
            if has_text == has_lines:
                hard.append(_finding(
                    "op_field_invalid",
                    "fill_cell needs exactly one of text (a string) or lines (an "
                    "array of strings)", at))

        elif kind == "replace_at_cell":
            mode = params.get("mode", "replace")
            if mode not in ("replace", "append"):
                hard.append(_finding("op_field_invalid",
                                     "mode must be 'replace' or 'append'", at,
                                     mode=mode))
            if not isinstance(params.get("text"), str):
                hard.append(_finding("op_field_invalid", "text must be a string", at))
            if params.get("run") is None:
                key = (int(params.get("table", 0)), int(params["row"]),
                       int(params["col"]))
                entry = ft_cells.get(key)
                runs = (entry or {}).get("runs") or []
                if len(runs) > 1:
                    hard.append(_finding(
                        "at_cell_run_ambiguous",
                        f"cell ({params['row']},{params['col']}) has "
                        f"{len(runs)} text runs; name one with run",
                        at, runs=[{"index": r.get("index"), "text": r.get("text"),
                                   "charpr": r.get("charpr")} for r in runs]))
                elif entry is None:
                    warn.append(_finding(
                        "run_inventory_unavailable",
                        "the run inventory for this cell could not be read, so "
                        "run ambiguity was not checked here", at))

        elif kind == "set_run":
            at_para = _check_int(params.get("atPara"), "atPara", at, hard)
            run_index = _check_int(params.get("run"), "run", at, hard)
            if at_para is None or run_index is None:
                continue
            if not isinstance(params.get("text"), str):
                hard.append(_finding("op_field_invalid", "text must be a string", at))
            entry = ft_paras.get(at_para)
            if entry is None:
                warn.append(_finding(
                    "run_inventory_unavailable",
                    f"paragraph {at_para} was not returned by the run inventory, "
                    "so its run addresses were not checked", at))
            else:
                indexes = {r.get("index") for r in (entry.get("runs") or [])}
                if run_index not in indexes:
                    hard.append(_finding(
                        "run_address_unknown",
                        f"paragraph {at_para} has no run {run_index}",
                        at, available=sorted(i for i in indexes if i is not None)))

        elif kind == "delete_guides":
            if not params.get("color") and not params.get("charPrIds"):
                hard.append(_finding(
                    "op_field_invalid",
                    "delete_guides needs color or charPrIds; deleting every "
                    "coloured paragraph unasked is not an option", at))

    return {
        "planId": plan.id,
        "planHash": plan.hash,
        "backend": plan.payload["backend"],
        "boundSha256": plan.payload["boundSha256"],
        "currentSha256": current_sha256,
        "stale": stale,
        "ok": not hard,
        "verdict": "pass" if not hard else "fail",
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn), "ops": len(plan.payload["ops"])},
        "preflight": {
            "level": "structural+profile",
            "source": "engine/scripts/form_inspect.py preflight fields",
            "deferred": list(DEFERRED_REFUSALS),
            "note": ("preedit raises its own refusals from inside its edit path "
                     "and ships no dry run; a clean validation is not a promise "
                     "that apply cannot refuse"),
        },
    }


# --- approvals --------------------------------------------------------------

class ApprovalRecord:
    def __init__(self, payload: dict):
        self.payload = payload

    @property
    def id(self) -> str:
        return self.payload["approvalId"]

    @property
    def state(self) -> str:
        return self.payload["state"]

    def public(self) -> dict:
        return dict(self.payload)


def request_approval(plan: OperationPlan, requested_by: str) -> ApprovalRecord:
    return ApprovalRecord({
        "approvalId": uuid.uuid4().hex,
        "planId": plan.id,
        "planHash": plan.hash,
        "state": "pending",
        "requestedUtc": now_utc(),
        "requestedBy": requested_by,
        "resolvedUtc": None,
        "approver": None,
        "decision": None,
    })


def resolve_approval(record: ApprovalRecord, *, plan_id: str, plan_hash: str,
                     decision: str, approver: str) -> ApprovalRecord:
    """Bind the decision to an exact plan id AND plan hash, or refuse.

    The Runtime never fabricates approval and never approves something other
    than what was shown — the same rule ``pipeline_ctl gate`` enforces by
    refusing to resolve a human gate without a matching APPROVALS.md line
    (modules/report/scripts/pipeline_ctl.py:1159).
    """
    if decision not in APPROVAL_DECISIONS:
        raise RpcError("invalid_params",
                       f"decision must be one of {list(APPROVAL_DECISIONS)}",
                       decision=decision)
    if record.state != "pending":
        raise RpcError("approval_already_resolved",
                       f"approval is already {record.state}",
                       approvalId=record.id, state=record.state)
    if plan_id != record.payload["planId"] or plan_hash != record.payload["planHash"]:
        raise RpcError(
            "approval_binding_mismatch",
            "this approval names a different plan than the one being approved",
            approvalId=record.id,
            boundPlanId=record.payload["planId"],
            boundPlanHash=record.payload["planHash"],
            offeredPlanId=plan_id, offeredPlanHash=plan_hash)
    record.payload["state"] = decision
    record.payload["decision"] = decision
    record.payload["approver"] = approver
    record.payload["resolvedUtc"] = now_utc()
    return record
