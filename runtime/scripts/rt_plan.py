#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OperationPlan, PlanValidation, ApprovalRequest/ApprovalRecord.

A plan declares its backend (orchestrator decision D9). This slice executes
``preedit`` always, ``xml`` when ``engine/scripts/xml_backend.py`` resolves
under the engine root, and ``com`` when the host capability is available.
``xml`` plans are accepted at propose when ``capabilities.backends.xml`` is
``available``; apply runs one ``xml_backend.py edit`` batch (see
``rt_engine.xml_edit_run``). ``com`` plans are accepted at propose when
``capabilities.backends.com`` is ``available`` (Hancom probe plus
``engine/scripts/com_backend.py``); apply runs one ``com_backend.py edit``
batch (see ``rt_engine.com_edit_run``).
Op kinds those backends own, mixed into a preedit plan, are refused with
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
import re
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
#: First wave = intersection of xml_backend.SUPPORTED_OPS with what the plan
#: layer already knows. Order follows the task spec (requirement 1).
XML_FIRST_WAVE: tuple[str, ...] = (
    "goto_text", "insert_text", "replace_all", "insert_blank_before",
    "set_line_spacing", "page_binding", "insert_table",
    "insert_picture", "insert_equation",
)
XML_FIRST_WAVE_SET = frozenset(XML_FIRST_WAVE)
#: engine/scripts/com_backend.py:1902 (24 entries, verified against OPS)
COM_OP_KINDS = frozenset({
    "replace_all", "put_field", "goto_text", "find_delete", "move",
    "insert_text", "insert_equation", "edit_equation", "insert_table",
    "insert_picture", "set_cell", "set_char_color", "delete_ctrls",
    "collapse_empty_paragraphs", "delete_blank_after", "delete_blank_before",
    "set_para_align", "insert_blank_before", "insert_hyperlink",
    "page_binding", "set_line_spacing", "page_break_before",
    "page_numbers", "set_header",
})
#: First wave the Runtime will propose when the COM capability is available.
#: Order is the capability catalog order (docs/plans/stage3-cli-com-wiring.md).
COM_FIRST_WAVE: tuple[str, ...] = (
    "replace_all", "goto_text", "insert_text", "set_cell",
    "insert_equation", "insert_picture", "insert_hyperlink",
)
COM_FIRST_WAVE_SET = frozenset(COM_FIRST_WAVE)
COM_DEFERRED_OP_KINDS = frozenset(COM_OP_KINDS - COM_FIRST_WAVE_SET)

#: Refusals only the engine can raise, listed so a clean validation is never
#: read as "apply cannot refuse".
DEFERRED_REFUSALS = (
    "replace_key_ambiguous",
    "at_cell_expect_mismatch",
    "xml_wellformedness",
)
#: COM apply-time refusals this slice does not preflight (Hancom is not started).
COM_DEFERRED_REFUSALS = (
    "equation_preflight",
    "set_cell_expect_mismatch",
    "anchor_not_found",
)
#: XML apply-time refusals the plan layer does not preflight. Boxed display
#: equations are structurally refused by xml_backend with
#: ``equation_box_unsupported_xml``; well-formedness is the child's job.
XML_DEFERRED_REFUSALS = (
    "equation_box_unsupported_xml",
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

#: Closed first-wave COM schemas. ``set_cell`` requires ``text`` here; ``addr``
#: is required after row/col translation and ``raw_traversal`` is never allowed.
_COM_OP_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "replace_all": (("find", "replace"), ("regex",)),
    "goto_text": (("text",), ("after", "line_end", "cell_below", "next_para")),
    "insert_text": (("text",), ("pt", "segments", "break_after", "align")),
    "set_cell": (("text",), ("addr", "row", "col", "table",
                             "expect_empty", "expect")),
    "insert_equation": ((), ("latex", "hwpeqn", "display", "boxed",
                             "base_pt", "font", "box_height_mm")),
    "insert_picture": (("path",), ("width_mm", "height_mm",
                                   "treat_as_char", "own_paragraph")),
    "insert_hyperlink": (("url",), ("text", "pt")),
}

#: Closed first-wave XML schemas — the intersection of xml_backend.SUPPORTED_OPS
#: with the plan layer's field definitions. ``boxed`` equations are structurally
#: refused by the engine with ``equation_box_unsupported_xml``; the plan layer
#: lets them through so the engine's own named reason surfaces at apply time.
_XML_OP_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "goto_text": (("text",), ("after", "line_end", "cell_below", "next_para")),
    "insert_text": (("text",), ("pt", "segments", "break_after", "align")),
    "replace_all": (("find", "replace"), ("regex",)),
    "insert_blank_before": (("text",), ()),
    "set_line_spacing": ((), ("ratio", "unit", "value")),
    "page_binding": ((), ("mode",)),
    "insert_table": ((), ("rows", "cols", "width_mm", "header_rows", "caption")),
    "insert_picture": (("path",), ("width_mm", "height_mm",
                                   "treat_as_char", "own_paragraph")),
    "insert_equation": ((), ("latex", "hwpeqn", "display", "boxed",
                             "base_pt", "font", "box_height_mm")),
}


#: The declaration a plan may carry beside its ops. Exactly the three inputs
#: ``check_residue`` already accepts — this adds no policy vocabulary of its
#: own, it stops the Runtime from withholding the three it had.
DECLARES_FIELDS = ("fillMap", "keep", "keepPattern")

#: ``check_residue.fill_map_scopes`` interprets exactly these two answers to
#: "what are the OTHER occurrences of a key that claims several strings".
FILL_MAP_SCOPES = ("form_text", "seats")


def _fold(text: str) -> str:
    """Whitespace-fold for comparing CALLER INPUT against the inventory.

    Deliberately not a second copy of the gate's matching rule: nothing here
    decides residue. It exists so ``"수 신"`` and ``"수신"`` in a hand-written
    declaration are recognised as naming the same inventory entry, the same
    tolerance ``check_residue._normalize`` applies before it compares. If the
    two ever disagree the consequence is a refusal at propose time, never a
    silent exemption at verify time — the safe direction.
    """
    return " ".join(str(text).split())


def _declared_value(entry, key: str):
    """``(text, scope)`` for one fill-map entry, or a loud refusal.

    Two shapes, both ``check_residue``'s (``normalize_fill_map`` flattens the
    scoped one for every downstream consumer): a bare string, or
    ``{"text": V, "other_occurrences": "form_text"|"seats"}`` for a key that
    claims more than one inventory string and needs to say what the rest are.
    """
    if isinstance(entry, str):
        return entry, None
    if isinstance(entry, dict):
        text = entry.get("text")
        scope = entry.get("other_occurrences")
        unknown = sorted(set(entry) - {"text", "other_occurrences"})
        if unknown:
            raise RpcError("unknown_field",
                           f"declares.fillMap[{key!r}] carries fields a scoped "
                           "value does not define",
                           key=key, unknown=unknown,
                           allowed=["text", "other_occurrences"])
        if not isinstance(text, str) or not text:
            raise RpcError("invalid_params",
                           f"declares.fillMap[{key!r}].text must be a non-empty "
                           "string", key=key)
        if scope is not None and scope not in FILL_MAP_SCOPES:
            raise RpcError("invalid_params",
                           f"declares.fillMap[{key!r}].other_occurrences must be "
                           f"one of {list(FILL_MAP_SCOPES)}",
                           key=key, offered=scope,
                           allowed=list(FILL_MAP_SCOPES))
        return text, scope
    raise RpcError("invalid_params",
                   f"declares.fillMap[{key!r}] must be a string, or an object "
                   'with "text" and optional "other_occurrences"', key=key)


def written_texts(ops: list) -> set:
    """Every string the plan's operations actually put into the document.

    This is what makes a declaration a RECORD rather than a request. A fill map
    tells the residue gate "an occurrence inside this value is text I wrote, not
    form text I left behind" — a claim that is only true if the plan wrote it.
    Without this binding the mechanism is a wildcard: declaring
    ``{"수신": "수신"}`` would lay a value span over the form's own label and
    attribute the label to itself, exempting it document-wide while changing
    nothing. Every value is therefore checked against the ops here, before the
    plan exists to be approved.
    """
    written: set = set()
    for op in ops:
        params = op.get("params") or {}
        text = params.get("text")
        if isinstance(text, str):
            written.add(_fold(text))
        lines = params.get("lines")
        if isinstance(lines, list):
            for line in lines:
                if isinstance(line, str):
                    written.add(_fold(line))
            if all(isinstance(line, str) for line in lines):
                written.add(_fold(" ".join(lines)))
    return written


def normalise_declares(declares, ops: list, *, inventory: dict | None = None):
    """Validate a plan's residue declaration, or refuse it. ``None`` stays None.

    ``inventory`` — ``{"keepable": {...}, "guide": {...}}`` of folded inventory
    strings — enables the checks that need to know what the form actually
    contains. It is optional so the binding rules can be exercised without a
    profile; when it is absent those two checks simply do not run, and the
    caller has not been told anything untrue.

    What this refuses, and why each one is a way the gate could have been
    turned off rather than informed:

    * a value the ops never wrote — the wildcard above;
    * a ``keepPattern`` that keeps everything — a gate with an empty forbidden
      list proves nothing, and ``.*`` is the shortest way to write that;
    * a ``keep`` entry that names no inventory entry — ``check_residue``
      compares a keep against the WHOLE normalized entry, so a prefix keeps
      nothing and does it silently; silence is the defect;
    * a ``keep`` entry that names a removal target — instruction prose is never
      keepable, and a caller who tries should be told, not quietly ignored.

    Everything it accepts is still subject to the gate itself: keeping an entry
    only removes it from the forbidden list, and attribution remains per
    occurrence.
    """
    if declares is None:
        return None
    if not isinstance(declares, dict):
        raise RpcError("invalid_params", "declares must be an object")
    unknown = sorted(set(declares) - set(DECLARES_FIELDS))
    if unknown:
        raise RpcError("unknown_field",
                       "declares carries fields it does not define",
                       unknown=unknown, allowed=list(DECLARES_FIELDS))
    if not any(declares.get(name) for name in DECLARES_FIELDS):
        raise RpcError(
            "invalid_params",
            "declares is empty; omit it rather than declaring nothing — an "
            "empty declaration and no declaration must not grade differently",
            allowed=list(DECLARES_FIELDS))

    written = written_texts(ops)
    out: dict = {}

    raw_map = declares.get("fillMap")
    if raw_map is not None:
        if not isinstance(raw_map, dict):
            raise RpcError("invalid_params", "declares.fillMap must be an object")
        fill_map: dict = {}
        for key, entry in raw_map.items():
            if not isinstance(key, str) or not key.strip():
                raise RpcError("invalid_params",
                               "declares.fillMap keys must be non-empty strings",
                               key=key)
            text, scope = _declared_value(entry, key)
            if _fold(text) not in written:
                raise RpcError(
                    "invalid_params",
                    f"declares.fillMap[{key!r}] declares a value this plan does "
                    "not write; a fill map records what the operations put in "
                    "the document, and a value the plan never writes would "
                    "exempt form text on no authority",
                    key=key, value=text)
            fill_map[key] = ({"text": text, "other_occurrences": scope}
                             if scope is not None else text)
        out["fillMap"] = fill_map

    raw_keep = declares.get("keep")
    if raw_keep is not None:
        if not isinstance(raw_keep, list):
            raise RpcError("invalid_params", "declares.keep must be an array")
        keep: list = []
        for index, entry in enumerate(raw_keep):
            if not isinstance(entry, str) or not entry.strip():
                raise RpcError("invalid_params",
                               f"declares.keep[{index}] must be a non-empty "
                               "string", at=f"declares.keep[{index}]")
            folded = _fold(entry)
            if inventory is not None:
                if folded in inventory.get("guide", ()):
                    raise RpcError(
                        "invalid_params",
                        f"declares.keep[{index}] names a guide removal target; "
                        "instruction prose is never keepable, because a correct "
                        "fill REPLACES it rather than keeping it as a prefix",
                        at=f"declares.keep[{index}]", text=entry)
                if folded not in inventory.get("keepable", ()):
                    raise RpcError(
                        "invalid_params",
                        f"declares.keep[{index}] names no inventory entry; a "
                        "keep is matched against the WHOLE entry, so a prefix "
                        "or an invented string keeps nothing and would do it "
                        "silently",
                        at=f"declares.keep[{index}]", text=entry)
            keep.append(entry)
        out["keep"] = keep

    pattern = declares.get("keepPattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise RpcError("invalid_params",
                           "declares.keepPattern must be a string")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise RpcError("invalid_params",
                           f"declares.keepPattern is not a valid regex: {exc}",
                           pattern=pattern) from exc
        # A pattern that matches at position 0 of the empty string matches the
        # start of EVERY entry, so ``check_residue``'s ``keep_re.match`` keeps
        # the whole inventory and the gate is left with nothing to judge. That
        # is a disabled gate wearing a policy's clothes.
        if compiled.match("") is not None:
            raise RpcError(
                "invalid_params",
                "declares.keepPattern matches every inventory entry, which "
                "would leave the residue gate with an empty forbidden list; "
                "name the entries that legitimately survive instead",
                pattern=pattern)
        out["keepPattern"] = pattern

    return out


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


def _foreign_owner(kind: str, backend: str) -> str | None:
    """Which other backend owns this kind, from this plan's point of view."""
    if backend == "com":
        if kind in PREEDIT_OP_KINDS:
            return "preedit"
        if kind in XML_OP_KINDS and kind not in COM_OP_KINDS:
            return "xml"
        return None
    if backend == "xml":
        if kind in XML_FIRST_WAVE_SET:
            return None  # xml's own kind
        if kind in PREEDIT_OP_KINDS:
            return "preedit"
        if kind in COM_OP_KINDS:
            return "com"
        return None
    return _classify_foreign_kind(kind)


def _is_nonneg_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _normalise_com_set_cell(params: dict, at: str) -> dict:
    """Require cellAddr; translate row/col to addr; never accept raw_traversal."""
    if "raw_traversal" in params:
        raise RpcError(
            "invalid_params",
            "set_cell on the com backend never accepts raw_traversal (T28); "
            "use addr:[row,col]",
            at=at, kind="set_cell", field="raw_traversal")
    out = dict(params)
    addr = out.get("addr")
    if addr is None:
        row, col = out.get("row"), out.get("col")
        if _is_nonneg_int(row) and _is_nonneg_int(col):
            out["addr"] = [row, col]
            out.pop("row", None)
            out.pop("col", None)
        else:
            raise RpcError("invalid_params", f"{at} is missing required fields",
                           at=at, kind="set_cell", missing=["addr"])
    else:
        if (not isinstance(addr, (list, tuple)) or len(addr) != 2
                or not all(_is_nonneg_int(value) for value in addr)):
            raise RpcError(
                "invalid_params",
                f"{at}.addr must be [row, col] non-negative integers",
                at=at, kind="set_cell")
        out["addr"] = [int(addr[0]), int(addr[1])]
        out.pop("row", None)
        out.pop("col", None)
    return out


def _normalise_com_equation(params: dict, at: str) -> dict:
    has_latex = isinstance(params.get("latex"), str) and params["latex"]
    has_hwpeqn = isinstance(params.get("hwpeqn"), str) and params["hwpeqn"]
    if has_latex == has_hwpeqn:
        raise RpcError(
            "invalid_params",
            f"{at} insert_equation needs exactly one of latex or hwpeqn",
            at=at, kind="insert_equation", missing=["latex|hwpeqn"])
    return params


def _refuse_unservable_kind(kind: str, backend: str, at: str) -> None:
    owner = _foreign_owner(kind, backend)
    if owner is not None:
        if backend == "preedit":
            message = (f"op kind {kind!r} is served by the {owner} backend, which "
                       "this build does not execute")
        else:
            message = (f"op kind {kind!r} is served by the {owner} backend, "
                       f"not {backend}")
        raise RpcError(
            "unsupported_backend", message,
            at=at, kind=kind, servedBy=owner,
            supported=list(SUPPORTED_BACKENDS))
    if backend == "com" and kind in COM_DEFERRED_OP_KINDS:
        raise RpcError(
            "unknown_op_kind",
            f"op kind {kind!r} is deferred on the com backend in this wave",
            at=at, kind=kind, servedBy="com",
            knownKinds=list(COM_FIRST_WAVE),
            notImplemented=sorted(COM_DEFERRED_OP_KINDS))
    if backend == "preedit":
        known = sorted(PREEDIT_OP_KINDS)
        not_implemented = list(PREEDIT_NOT_IMPLEMENTED)
    elif backend == "xml":
        known = list(XML_FIRST_WAVE)
        not_implemented = []
    else:
        known = list(COM_FIRST_WAVE)
        not_implemented = sorted(COM_DEFERRED_OP_KINDS)
    raise RpcError(
        "unknown_op_kind",
        f"op kind {kind!r} is not known to the "
        f"{backend} backend",
        at=at, kind=kind, knownKinds=known,
        notImplemented=not_implemented)



def _normalise_ops(backend: str, ops: list) -> list:
    if backend == "preedit":
        field_table = _OP_FIELDS
        accepted = PREEDIT_OP_KINDS
    elif backend == "xml":
        field_table = _XML_OP_FIELDS
        accepted = XML_FIRST_WAVE_SET
    else:
        field_table = _COM_OP_FIELDS
        accepted = COM_FIRST_WAVE_SET
    normalised = []
    seen_ids: set[str] = set()
    for index, op in enumerate(ops):
        at = f"ops[{index}]"
        if not isinstance(op, dict):
            raise RpcError("invalid_params", f"{at} must be an object")
        kind = op.get("kind")
        if not isinstance(kind, str):
            raise RpcError("invalid_params", f"{at}.kind must be a string")
        if kind not in accepted:
            _refuse_unservable_kind(kind, backend, at)
        required, optional = field_table[kind]
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
        if backend == "com" and kind == "set_cell":
            params = _normalise_com_set_cell(params, at)
        elif backend == "com" and kind == "insert_equation":
            params = _normalise_com_equation(params, at)
        normalised.append({"opId": op_id, "kind": kind, "params": params})
    return normalised


def build_plan(*, session_id: str, backend: str, ops: list, proposer: str,
               bound_sha256: str, base: dict | None = None,
               reverses: dict | None = None, declares=None,
               inventory: dict | None = None,
               com_capability: dict | None = None,
               xml_capability: dict | None = None) -> OperationPlan:
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

    ``com_capability`` is the produced ``backends.com`` snapshot. A ``com``
    plan is accepted only when that snapshot's ``state`` is ``available``.

    ``xml_capability`` is the produced ``backends.xml`` snapshot. An ``xml``
    plan is accepted only when that snapshot's ``state`` is ``available``
    (i.e. ``engine/scripts/xml_backend.py`` is present under the engine root).
    """
    if backend not in KNOWN_BACKENDS:
        raise RpcError(
            "unsupported_backend",
            f"unknown backend {backend!r}",
            declared=backend, supported=list(SUPPORTED_BACKENDS),
            known=list(KNOWN_BACKENDS))
    if backend == "com":
        cap = com_capability or {}
        if cap.get("state") != "available":
            reason = cap.get("reason") or (
                "the com backend is not available on this host")
            data = {"backend": "com", "state": "unavailable",
                    "facts": dict(cap.get("facts") or {})}
            if cap.get("missing") is not None:
                data["missing"] = cap["missing"]
            raise RpcError("capability_unavailable", reason, **data)
    elif backend == "xml":
        cap = xml_capability or {}
        if cap.get("state") != "available":
            reason = cap.get("reason") or (
                "the xml backend is not available on this host")
            raise RpcError("capability_unavailable", reason,
                           backend="xml", state="unavailable")
    elif backend not in SUPPORTED_BACKENDS:
        raise RpcError(
            "unsupported_backend",
            (f"backend {backend!r} is declared by the protocol but this build "
             f"executes only {', '.join(SUPPORTED_BACKENDS)}"),
            declared=backend, supported=list(SUPPORTED_BACKENDS),
            known=list(KNOWN_BACKENDS))
    if not isinstance(ops, list) or not ops:
        raise RpcError("invalid_params", "ops must be a non-empty array")

    normalised = _normalise_ops(backend, ops)

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
        # The residue declaration rides BESIDE the ops, never inside them, and
        # ``opsHash`` is computed over ``ops`` alone — so two identical edits
        # still hash identically whether or not one of them declared a keep
        # list, and the Phase 2 parity property survives untouched
        # (tests/test_runtime_parity.py). ``planHash`` covers the whole payload
        # and therefore DOES move, which is the point: an approval binds the
        # exemptions as tightly as it binds the edits.
        "declares": normalise_declares(declares, normalised,
                                       inventory=inventory),
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

    if plan.payload.get("backend") == "xml":
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
            "counts": {"hard": len(hard), "warn": len(warn),
                       "ops": len(plan.payload["ops"])},
            "preflight": {
                "level": "structural+backend-schema",
                "source": "runtime XML first-wave schema; xml_backend is not executed",
                "deferred": list(XML_DEFERRED_REFUSALS),
                "note": ("XML validation does not open the archive; boxed "
                         "equations and well-formedness are apply-time "
                         "refusals listed in deferred"),
            },
        }

    if plan.payload.get("backend") == "com":
        for op in plan.payload["ops"]:
            at = f"ops[{op['opId']}]"
            kind, params = op["kind"], op["params"]
            if kind == "set_cell":
                if params.get("raw_traversal"):
                    hard.append(_finding(
                        "op_field_invalid",
                        "set_cell never accepts raw_traversal (T28); use addr",
                        at))
                addr = params.get("addr")
                if (not isinstance(addr, list) or len(addr) != 2
                        or not all(_is_nonneg_int(value) for value in addr)):
                    hard.append(_finding(
                        "op_field_invalid",
                        "set_cell needs addr:[row,col] non-negative integers",
                        at))
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
            "counts": {"hard": len(hard), "warn": len(warn),
                       "ops": len(plan.payload["ops"])},
            "preflight": {
                "level": "structural+backend-schema",
                "source": "runtime COM first-wave schema; Hancom is not started",
                "deferred": list(COM_DEFERRED_REFUSALS),
                "note": ("COM validation does not start Hancom; equation "
                         "preflight, set_cell expect, and missing anchors are "
                         "apply-time refusals listed in deferred"),
            },
        }

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
