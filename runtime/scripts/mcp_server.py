#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP stdio adapter — the agent-safe subset, and nothing else.

    python runtime/scripts/mcp_server.py --root <dir> [--engine-root <dir>]

FRAMING: newline-delimited JSON-RPC 2.0, which is what the MCP stdio transport
specifies — "messages are delimited by newlines and MUST NOT contain embedded
newlines". The ``Content-Length`` header framing people reach for is the
Language Server Protocol's, not MCP's; MCP's other transport is HTTP, not a
header-framed pipe. So this adapter reuses the Runtime's own line reader
(``rt_jsonl.read_raw_frame``) unchanged, including its size cap and its
duplicate-key and non-finite refusals.

SURFACE: derived, never rostered. The tool list is
``rt_core.AGENT_METHODS`` minus ``initialize`` (MCP has its own handshake), so
``approval/resolve``, ``plan/apply`` and ``workspace/openPath`` are absent by
construction rather than by a filter someone could later loosen. Adding an
agent method without a tool schema raises at import; adding a schema for a
method that is not agent-safe raises at import too.

A tool therefore cannot open a document, approve a plan, or apply one. An MCP
client inspects, proposes, validates and asks for approval; a human on the
host CLI or the host connection does the rest. Sessions come from the shared
``--root`` store, which is why ``--root`` is required and has no default.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    EXIT_OK,
    EXIT_USAGE,
    IMPL_VERSION,
    MAX_FRAME_BYTES,
    SUPPORTED_BACKENDS,
    RpcError,
)
from rt_core import AGENT_METHODS, HOST_ONLY_METHODS, METHODS, RuntimeCore  # noqa: E402
from rt_jsonl import (  # noqa: E402
    READ_EOF,
    READ_LINE,
    READ_OVERSIZE,
    StrictJsonError,
    decode_frame,
    dumps_frame,
    log,
)

SERVER_NAME = "rigorloom-runtime"
#: MCP revisions this adapter understands. A client asking for one of these
#: gets it back; anything else gets our preferred version, which the spec's
#: negotiation allows the client to accept or hang up on.
SUPPORTED_MCP_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PREFERRED_MCP_VERSION = SUPPORTED_MCP_VERSIONS[0]

CLIENT = "mcp-client"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: MCP tool names allow letters, digits, underscore and dash — not slashes.
#: One deterministic mapping, both directions, so nothing is hand-maintained.
def tool_name(method: str) -> str:
    return method.replace("/", "_")


#: The tool surface: every agent method except the MCP-shadowed handshake.
EXPOSED_METHODS: tuple[str, ...] = tuple(
    method for method in AGENT_METHODS if method != "initialize")

_SESSION = {"sessionId": {"type": "string",
                          "description": "session id from the host's open"}}
_PLAN = {"planId": {"type": "string", "description": "plan id"}}

TOOL_SCHEMAS: dict[str, dict] = {
    "capabilities/list": {
        "description": "What this Runtime build can do: methods, backends, op "
                       "kinds, limits, and what is explicitly unavailable.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "session/list": {
        "description": "List the document sessions under this Runtime root. "
                       "Sessions are opened by a host, not by this adapter.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "document/inspect": {
        "description": "Structure of the document in a session: summary, "
                       "paragraph/table graph, and the editable regions with "
                       "their charPr preflight. Carries no body text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "include": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": ["summary", "graph", "regions"]},
                    "description": "subset to return; default all three",
                },
            },
            "required": ["sessionId"],
        },
    },
    "document/readRegion": {
        "description": "Exact text and run records for named cells or "
                       "paragraphs. Opt-in and bounded: it refuses rather than "
                       "truncating when the result is too large.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "regions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "table": {"type": "integer"},
                            "row": {"type": "integer"},
                            "col": {"type": "integer"},
                            "atPara": {"type": "integer"},
                        },
                    },
                    "description": "each entry is {table,row,col} or {atPara}",
                },
            },
            "required": ["sessionId", "regions"],
        },
    },
    "plan/propose": {
        "description": "Build an OperationPlan against the session's current "
                       "bytes. Proposing does not edit anything; a host must "
                       "approve and apply it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "backend": {"type": "string", "enum": list(SUPPORTED_BACKENDS),
                            "description": "which engine backend serves the ops"},
                "ops": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "object"},
                    "description": "typed operations, e.g. {\"kind\":\"fill_cell\","
                                   "\"table\":0,\"row\":5,\"col\":1,\"text\":\"…\"}",
                },
                "proposer": {"type": "string"},
            },
            "required": ["sessionId", "backend", "ops"],
        },
    },
    "plan/validate": {
        "description": "Validate a plan against the document without executing "
                       "it. Reports hard findings, warnings, staleness, and "
                       "which refusals are deferred to apply.",
        "inputSchema": {"type": "object", "properties": dict(_PLAN),
                        "required": ["planId"]},
    },
    "plan/get": {
        "description": "Read a plan back, including its state and hashes.",
        "inputSchema": {"type": "object", "properties": dict(_PLAN),
                        "required": ["planId"]},
    },
    "approval/request": {
        "description": "Open an approval request bound to a plan id and plan "
                       "hash. Only a host can resolve it.",
        "inputSchema": {
            "type": "object",
            "properties": {**_PLAN, "requestedBy": {"type": "string"}},
            "required": ["planId"],
        },
    },
    "approval/get": {
        "description": "Read an approval back: pending, approved or rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {"approvalId": {"type": "string"}},
            "required": ["approvalId"],
        },
    },
    "candidate/list": {
        "description": "Published candidates for a session. A run without a "
                       "receipt is not listed.",
        "inputSchema": {"type": "object", "properties": dict(_SESSION),
                        "required": ["sessionId"]},
    },
    "document/render": {
        "description": "A page image of the document, when one is possible. "
                       "Returns a PNG (inline base64 when small, always a "
                       "session-relative path) plus page count and page size; "
                       "when no page image is possible it returns a structured "
                       "unavailable state naming exactly what is missing, never "
                       "an approximation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "page": {"type": "integer", "minimum": 0,
                         "description": "0-based page index"},
                "dpi": {"type": "integer", "minimum": 24, "maximum": 400},
                "runId": {"type": "string",
                          "description": "render a published candidate instead "
                                         "of the session source"},
                "inline": {"type": "boolean",
                           "description": "inline the PNG as base64 when it fits"},
            },
            "required": ["sessionId"],
        },
    },
    "document/pageGeometry": {
        "description": "Text positions on a rendered page, mapped to editable "
                       "addresses. Rects are fractions of the page, origin "
                       "top-left. A span maps to one address, to several "
                       "candidates when the text is genuinely ambiguous, or to "
                       "none. Empty fill seats carry a rect and the method it "
                       "was derived by.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "page": {"type": "integer", "minimum": 0},
                "runId": {"type": "string",
                          "description": "read a published candidate instead "
                                         "of the session source"},
            },
            "required": ["sessionId"],
        },
    },
    "event/poll": {
        "description": "Read the session's event log from a sequence number. "
                       "Request/response, for a client that cannot be pushed "
                       "to; the JSONL protocol offers event/subscribe instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SESSION,
                "after": {"type": "integer",
                          "description": "return events with seq > after; -1 "
                                         "replays from the beginning"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["sessionId"],
        },
    },
    "receipt/read": {
        "description": "Read a candidate's receipt. Refuses if the candidate "
                       "bytes or the receipt body no longer match their hashes.",
        "inputSchema": {
            "type": "object",
            "properties": {**_SESSION, "runId": {"type": "string"}},
            "required": ["sessionId", "runId"],
        },
    },
}

# Loud at import, both directions — a surface nobody can drift.
_missing = sorted(set(EXPOSED_METHODS) - set(TOOL_SCHEMAS))
assert not _missing, f"agent methods with no MCP tool schema: {_missing}"
_extra = sorted(set(TOOL_SCHEMAS) - set(EXPOSED_METHODS))
assert not _extra, f"MCP tool schemas for non-agent methods: {_extra}"
_forbidden = sorted(set(TOOL_SCHEMAS) & set(HOST_ONLY_METHODS))
assert not _forbidden, f"host-only methods exposed as MCP tools: {_forbidden}"

TOOL_TO_METHOD: dict[str, str] = {tool_name(m): m for m in EXPOSED_METHODS}
assert len(TOOL_TO_METHOD) == len(EXPOSED_METHODS), "tool name collision"


def tool_definitions() -> list[dict]:
    return [
        {
            "name": tool_name(method),
            "description": TOOL_SCHEMAS[method]["description"],
            "inputSchema": TOOL_SCHEMAS[method]["inputSchema"],
        }
        for method in EXPOSED_METHODS
    ]


class McpAdapter:
    """JSON-RPC 2.0 over stdio, dispatching onto the shared domain core."""

    def __init__(self, *, root: Path, engine_root: Path | None = None,
                 stdin=None, stdout=None):
        self.core = RuntimeCore(root, engine_root)
        self._in = stdin if stdin is not None else sys.stdin.buffer
        self._out = stdout if stdout is not None else sys.stdout.buffer
        self.initialized = False
        self.negotiated_version = PREFERRED_MCP_VERSION

    # -- dispatch -----------------------------------------------------------
    def call_tool(self, name: str, arguments: dict) -> dict:
        method = TOOL_TO_METHOD.get(name)
        if method is None:
            raise RpcError("unknown_method",
                           f"no such tool {name!r}; this adapter exposes the "
                           "agent-safe subset only",
                           tool=name, known=sorted(TOOL_TO_METHOD),
                           knownOnHostEntry=name in
                           {tool_name(m) for m in HOST_ONLY_METHODS})
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            raise RpcError("invalid_params", "tool arguments must be an object")
        core = self.core
        if method == "capabilities/list":
            return core.capabilities(entry="agent", methods=list(EXPOSED_METHODS))
        if method == "session/list":
            return core.session_list()
        if method == "document/inspect":
            return core.document_inspect(arguments.get("sessionId"),
                                         arguments.get("include"))
        if method == "document/readRegion":
            return core.document_read_region(arguments.get("sessionId"),
                                             arguments.get("regions"))
        if method == "plan/propose":
            return core.plan_propose(arguments.get("sessionId"),
                                     arguments.get("backend"),
                                     arguments.get("ops"),
                                     arguments.get("proposer") or CLIENT)
        if method == "plan/validate":
            return core.plan_validate(arguments.get("planId"))
        if method == "plan/get":
            return core.plan_get(arguments.get("planId"))
        if method == "approval/request":
            return core.approval_request(arguments.get("planId"),
                                         arguments.get("requestedBy") or CLIENT)
        if method == "approval/get":
            return core.approval_get(arguments.get("approvalId"))
        if method == "candidate/list":
            return core.candidate_list(arguments.get("sessionId"))
        if method == "receipt/read":
            return core.receipt_read(arguments.get("sessionId"),
                                     arguments.get("runId"))
        if method == "document/render":
            inline = arguments.get("inline", True)
            if not isinstance(inline, bool):
                raise RpcError("invalid_params", "inline must be a boolean")
            return core.document_render(arguments.get("sessionId"),
                                        page=arguments.get("page", 0),
                                        dpi=arguments.get("dpi"),
                                        run_id=arguments.get("runId"),
                                        inline=inline)
        if method == "document/pageGeometry":
            return core.document_page_geometry(arguments.get("sessionId"),
                                               page=arguments.get("page", 0),
                                               run_id=arguments.get("runId"))
        if method == "event/poll":
            return core.event_poll(arguments.get("sessionId"),
                                   after=arguments.get("after", -1),
                                   limit=arguments.get("limit"))
        raise RpcError("unknown_method", f"unrouted tool {name!r}", tool=name)

    # -- JSON-RPC -----------------------------------------------------------
    def handle(self, message: dict) -> dict | None:
        """Return a response object, or None for a notification."""
        message_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            if is_notification:
                return None
            return self._error(message_id, INVALID_REQUEST,
                               "not a JSON-RPC 2.0 request")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return None if is_notification else self._error(
                message_id, INVALID_PARAMS, "params must be an object")

        if method == "initialize":
            requested = params.get("protocolVersion")
            self.negotiated_version = (
                requested if requested in SUPPORTED_MCP_VERSIONS
                else PREFERRED_MCP_VERSION)
            self.initialized = True
            return self._result(message_id, {
                "protocolVersion": self.negotiated_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": IMPL_VERSION},
                "instructions": (
                    "Agent-safe Runtime surface. You can inspect a document, "
                    "propose an OperationPlan, validate it and request "
                    "approval. Opening documents, approving and applying are "
                    "host actions and are not exposed here."),
            })
        if method.startswith("notifications/"):
            return None
        if is_notification:
            return None
        if not self.initialized:
            return self._error(message_id, INVALID_REQUEST,
                               "initialize before any other method")
        if method == "ping":
            return self._result(message_id, {})
        if method == "tools/list":
            return self._result(message_id, {"tools": tool_definitions()})
        if method == "tools/call":
            return self._tools_call(message_id, params)
        return self._error(message_id, METHOD_NOT_FOUND,
                           f"unsupported MCP method {method!r}")

    def _tools_call(self, message_id, params: dict):
        name = params.get("name")
        if not isinstance(name, str):
            return self._error(message_id, INVALID_PARAMS,
                               "tools/call needs a string name")
        try:
            result = self.call_tool(name, params.get("arguments") or {})
        except RpcError as exc:
            # A domain refusal is a TOOL error, not a protocol error: the model
            # must see the payload. The engine's refusals carry the whole escape
            # hatch (engine/scripts/preedit.py:2694-2717) and flattening them to
            # a sentence is what sends a caller into section.xml.
            return self._result(message_id, self._content(
                {"ok": False, "error": exc.to_frame_error()}, is_error=True))
        except Exception:  # noqa: BLE001
            log("mcp adapter internal error:\n" + traceback.format_exc())
            return self._error(message_id, INTERNAL_ERROR,
                               "the adapter failed to serve this tool call")
        return self._result(message_id, self._content({"ok": True,
                                                       "result": result}))

    @staticmethod
    def _content(payload: dict, *, is_error: bool = False) -> dict:
        return {
            "content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False,
                                            indent=2, sort_keys=True,
                                            allow_nan=False)}],
            "isError": is_error,
        }

    @staticmethod
    def _result(message_id, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error(message_id, code: int, message: str, data=None) -> dict:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": message_id, "error": error}

    # -- loop ---------------------------------------------------------------
    def _send(self, payload: dict) -> None:
        self._out.write(dumps_frame(payload))
        self._out.flush()

    def serve(self) -> int:
        from rt_jsonl import read_raw_frame
        while True:
            kind, raw = read_raw_frame(self._in, MAX_FRAME_BYTES)
            if kind == READ_EOF:
                return EXIT_OK
            if kind == READ_OVERSIZE:
                self._send(self._error(None, INVALID_REQUEST,
                                       "message exceeded the frame cap and was "
                                       "refused without being parsed"))
                continue
            assert kind == READ_LINE
            if not raw.strip():
                continue
            try:
                message = decode_frame(raw)
            except StrictJsonError as exc:
                self._send(self._error(None, PARSE_ERROR, exc.detail))
                continue
            response = self.handle(message)
            if response is not None:
                self._send(response)


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime/scripts/mcp_server.py",
        description="MCP stdio adapter over the Runtime's agent-safe surface. "
                    "Newline-delimited JSON-RPC 2.0.")
    parser.add_argument("--root", required=True,
                        help="the Runtime session-store root. Required: this "
                             "adapter never guesses where your documents are.")
    parser.add_argument("--engine-root", default=None,
                        help="repo root holding engine/scripts and "
                             "pipeline/scripts (default: this checkout)")
    parser.add_argument("--list-tools", action="store_true",
                        help="print the tool surface as JSON and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.list_tools:
        sys.stdout.write(json.dumps(
            {"tools": tool_definitions(),
             "exposedMethods": list(EXPOSED_METHODS),
             "notExposed": sorted(set(METHODS) - set(EXPOSED_METHODS))},
            ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    root = Path(args.root).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"--root is not usable: {exc}")
        return EXIT_USAGE
    adapter = McpAdapter(root=root, engine_root=args.engine_root)
    log(f"{SERVER_NAME} mcp adapter ready: {len(EXPOSED_METHODS)} tools, "
        f"impl {IMPL_VERSION}")
    return adapter.serve()


if __name__ == "__main__":
    raise SystemExit(main())
