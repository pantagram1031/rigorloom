#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The tool registry: every document capability, declared once.

A tool here is the whole contract of one capability: its typed request (a
small JSON-schema subset, validated before anything runs), its result
contract, how big its answer may get, its MCP annotations, and the function
that does the work through ``rt_doc``. The surfaces are views of this table:

* the CLI parses argv into a request and calls :func:`call`;
* the MCP server lists ``surface("mcp")`` and calls :func:`call`;
* the built-in agent sends ``surface("agent")`` schemas to the model.

So a capability behaves the same wherever it is reached, and the parity is
structural rather than a promise in three places.

Errors are one envelope everywhere (:class:`ToolError`): a stable English
``code``, a Korean ``message`` saying what happened, a Korean ``hint`` saying
what to do next, and, where they exist, ``at`` (address), ``done`` (ops already
applied), ``candidates`` (nearby addresses or names) and ``retryable``.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

#: code -> CLI exit code. 2 = the caller asked wrongly, 3 = the answer is no,
#: 4 = a bug here. The 0/2/3/4 contract is the repository's (cli.py docstring).
ERROR_EXIT: dict[str, int] = {
    "invalid_params": 2,
    "not_found": 2,
    "unknown_tool": 2,
    "ambiguous_match": 2,
    "page_out_of_range": 2,
    "bad_address": 2,
    "conflict": 2,
    "expect_mismatch": 3,
    "no_roots": 3,
    "outside_roots": 3,
    "declined_by_person": 3,
    "person_only_seat": 3,
    "stale": 3,
    "source_changed": 3,
    "target_exists": 3,
    "target_changed": 3,
    "locked": 3,
    "needs_person": 3,
    "no_draft": 3,
    "capability_unavailable": 3,
    "unsupported_format": 3,
    "too_large": 3,
    "engine_refused": 3,
    "source_rejected": 3,
    "engine_unavailable": 3,
    "internal": 4,
}


class ToolError(Exception):
    """A refusal or failure, carried the same way to every surface."""

    def __init__(self, code: str, message: str, *, hint: str | None = None,
                 at: str | None = None, done: int | None = None,
                 candidates: list[str] | None = None,
                 retryable: bool = False, data: dict | None = None):
        if code not in ERROR_EXIT:
            raise ValueError(f"unknown tool error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.at = at
        self.done = done
        self.candidates = candidates
        self.retryable = retryable
        self.data = data

    @property
    def exit_code(self) -> int:
        return ERROR_EXIT[self.code]

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"code": self.code, "message": self.message,
                               "retryable": self.retryable}
        for key in ("hint", "at", "done", "candidates", "data"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


# --------------------------------------------------------------------------
# Request validation: the subset of JSON Schema the tools use, nothing more.
# --------------------------------------------------------------------------

_TYPES: dict[str, tuple] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _type_ok(value: Any, kind: str | list) -> bool:
    kinds = kind if isinstance(kind, list) else [kind]
    for name in kinds:
        allowed = _TYPES[name]
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if isinstance(value, allowed):
            return True
    return False


def validate(schema: dict, value: Any, where: str = "") -> None:
    """Raise ``ToolError('invalid_params')`` naming the first bad field."""
    label = where or "요청"
    if "type" in schema and not _type_ok(value, schema["type"]):
        expected = schema["type"]
        raise ToolError("invalid_params",
                        f"{label}: 값이 {expected} 형식이어야 합니다.", at=where or None)
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError("invalid_params",
                        f"{label}: 허용한 값(" + ", ".join(map(str, schema["enum"])) + ")과 일치하지 않습니다.",
                        hint="목록에서 값 하나를 골라 입력하세요.",
                        at=where or None, candidates=[str(v) for v in schema["enum"]])
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ToolError("invalid_params", f"{label}: 비어 있습니다.", hint="이 항목에 내용을 더 입력하세요.",
                            at=where or None)
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolError("invalid_params",
                            f"{label}: {schema['maxLength']}자를 넘습니다.",
                            at=where or None)
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ToolError("invalid_params", f"{label}: 형식이 맞지 않습니다.",
                            at=where or None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolError("invalid_params",
                            f"{label}: {schema['minimum']} 이상이어야 합니다.",
                            at=where or None)
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolError("invalid_params",
                            f"{label}: {schema['maximum']} 이하여야 합니다.",
                            at=where or None)
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ToolError("invalid_params",
                            f"{label}: 항목이 {schema['maxItems']}개를 넘습니다.",
                            at=where or None)
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ToolError("invalid_params",
                            f"{label}: 항목이 {schema['minItems']}개 이상 필요합니다.",
                            at=where or None)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate(item_schema, item, f"{where}[{index}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                path = f"{where}.{key}" if where else key
                raise ToolError("invalid_params", f"{path}: 필수 항목이 빠졌습니다.", hint="이 항목에 값을 입력하세요.",
                                at=path)
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                path = f"{where}.{extra[0]}" if where else extra[0]
                raise ToolError("invalid_params", f"{path}: 사용할 수 없는 항목입니다.",
                                hint="요청에서 이 항목을 빼세요.",
                                at=path, candidates=sorted(props))
        for key, sub in props.items():
            if key in value:
                validate(sub, value[key], f"{where}.{key}" if where else key)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

SURFACES = ("cli", "mcp", "agent")


@dataclass(frozen=True)
class Tool:
    name: str
    title: str                      # Korean, for people (MCP title, CLI help)
    description: str                # for models: what it does, when to use it
    group: str                      # read | write | check | changes | help
    input_schema: dict
    output_schema: dict
    run: Callable[["Context", dict], dict]
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    surfaces: frozenset = frozenset(SURFACES)
    #: Characters the compact text rendering of a result may take. Results
    #: that would exceed it must page (``next``) or summarise, never truncate
    #: silently. Checked in tests against real fixtures.
    budget_chars: int = 8000
    #: Compact text an agent reads (MCP text block). Defaults to JSON.
    text: Callable[[dict], str] | None = None

    def annotations(self) -> dict:
        return {
            "title": self.title,
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": False,
        }


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in REGISTRY:
        raise ValueError(f"tool {tool.name!r} registered twice")
    if tool.input_schema.get("type") != "object":
        raise ValueError(f"{tool.name}: input schema must be an object")
    if tool.output_schema.get("type") != "object":
        raise ValueError(f"{tool.name}: output schema must be an object")
    REGISTRY[tool.name] = tool
    return tool


def surface(name: str) -> list[Tool]:
    if name not in SURFACES:
        raise ValueError(name)
    return [tool for tool in REGISTRY.values() if name in tool.surfaces]


def get(name: str) -> Tool:
    try:
        return REGISTRY[name]
    except KeyError:
        raise ToolError("unknown_tool", f"'{name}' 도구를 찾을 수 없습니다.", hint="도구 목록에서 이름을 확인하세요.",
                        candidates=sorted(REGISTRY)) from None


# --------------------------------------------------------------------------
# Calling
# --------------------------------------------------------------------------

def sibling(name: str):
    """Import a runtime module the same way this one was imported.

    Installed, the runtime is the package ``rigorloom_runtime``; in a checkout
    its folder is on ``sys.path`` and modules are top-level. Mixing the two
    would load a module twice (two registries, two error classes).
    """
    import importlib
    if __package__:
        return importlib.import_module(f"{__package__}.{name}")
    return importlib.import_module(name)


@dataclass
class Context:
    """Who is calling and what they may touch. Built once per surface."""

    client: str = "cli"                       # cli | mcp:<name> | agent
    #: Folders reads and writes are confined to. ``None`` = no confinement
    #: (a person on the CLI typed the path themselves).
    roots: Any = None
    #: Where agent edits go: "draft" (agent surfaces) or "direct" (CLI -o).
    write_mode: str = "draft"
    #: Read the draft head ("draft") or the file on disk ("disk").
    source: str = "draft"
    allow_overwrite: bool = False
    #: Non-empty: this caller's edits go to a private draft (CLI ``-o``).
    draft_scope: str = ""
    provenance: dict = field(default_factory=dict)
    #: ask(question, detail) -> bool. A person answers: MCP elicitation, a TTY
    #: prompt, or the UI. ``None`` = nobody can be asked.
    ask: Callable[[str, dict], bool] | None = None
    #: Lazily resolved document layer (rt_doc) and draft store.
    _doc: Any = None
    _drafts: Any = None

    @property
    def doc(self):
        if self._doc is None:
            self._doc = load_doc()
        return self._doc

    @property
    def drafts(self):
        if self._drafts is None:
            self._drafts = sibling("rt_drafts").DraftStore()
        return self._drafts


def load_doc():
    """The document layer, or a refusal that says what is missing."""
    try:
        rt_doc = sibling("rt_doc")
    except ImportError as exc:
        raise ToolError(
            "capability_unavailable",
            "문서 처리 기능을 불러오지 못했습니다.",
            hint="rigorloom doctor 명령으로 설치 상태를 확인하세요.",
            data={"reason": str(exc)}) from exc
    return rt_doc


def call(ctx: Context, name: str, args: dict | None) -> dict:
    """Validate, run, and wrap. Never raises; returns the envelope.

    ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": {...}}``.
    """
    args = {} if args is None else args
    try:
        tool = get(name)
        validate(tool.input_schema, args)
        result = tool.run(ctx, args)
        if not isinstance(result, dict):
            raise ToolError("internal", f"{name}: 도구가 잘못된 형식으로 결과를 보냈습니다.")
        return {"ok": True, "result": result}
    except ToolError as exc:
        return {"ok": False, "error": exc.to_dict()}
    except Exception as exc:  # noqa: BLE001 - a bug must not look like a verdict
        # The trace names local paths; it goes out only when a person asked.
        trace = None
        if os.environ.get("RIGORLOOM_DEBUG"):
            import traceback
            trace = {"trace": traceback.format_exc(limit=6)}
        return {"ok": False, "error": ToolError(
            "internal", f"{name}: 내부 오류가 났습니다({type(exc).__name__}).",
            hint="--debug로 다시 실행하면 자세한 내용이 나옵니다.",
            data=trace).to_dict()}


def doc_call(fn: Callable, *args, **kwargs) -> dict:
    """Call an rt_doc function and turn its error object into a ToolError.

    rt_doc returns ``{"ok": true, ...}`` or ``{"ok": false, "error": {...}}``
    (doc-core-api.md). Its message, address, step and candidates are kept, so
    an agent can recover instead of guessing.
    """
    out = fn(*args, **kwargs)
    if not isinstance(out, dict):
        raise ToolError("internal", "문서 처리 결과의 형식이 맞지 않습니다.")
    if out.get("ok", True):
        return out
    err = out.get("error") or {}
    code = err.get("code") or "engine_refused"
    mapped = {
        "stale": "stale",
        "not_found": "not_found",
        "ambiguous_match": "ambiguous_match",
        "expect_mismatch": "expect_mismatch",
        "bad_input": "invalid_params",
        "invalid_params": "invalid_params",
        "capability_unavailable": "capability_unavailable",
        "unsupported": "capability_unavailable",
        "refused": "engine_refused",
        "source_rejected": "source_rejected",
        "page_out_of_range": "page_out_of_range",
        "bad_address": "bad_address",
        "conflict": "conflict",
        "engine_timeout": "engine_unavailable",
        "engine_unavailable": "engine_unavailable",
        "internal": "internal",
        "internal_error": "internal",
    }.get(code, "engine_refused")
    raise ToolError(
        mapped, err.get("message") or "문서 처리를 마치지 못했습니다.",
        hint=err.get("hint"), at=err.get("at"),
        done=err.get("done"), candidates=err.get("candidates"),
        retryable=bool(err.get("retryable", False)),
        data={k: v for k, v in err.items()
              if k not in ("code", "message", "hint", "at", "done",
                           "candidates", "retryable")} or None)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=False)


def render_text(tool: Tool, result: dict) -> str:
    """The text an agent reads for a result (MCP text block, agent tool result)."""
    if tool.text is not None:
        return tool.text(result)
    return compact_json(result)
