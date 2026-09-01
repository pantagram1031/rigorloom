#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Runtime dispatcher: two entrypoints, one plan path, no self-declared authority.

AUTHORITY IS THE REGISTRY. The agent entrypoint does not build the host methods
at all — ``plan/apply`` on an agent connection is ``unknown_method`` because it
is genuinely absent, not because a permission check said no (orchestrator
decision D8/§3). A ``client_role`` (or any other) member in a request is a
field the protocol does not define and is refused as ``unknown_field``; under
the ``ignore`` policy it is dropped. Neither path can reach a host method.

The design doc worried that registry-absence loses the distinction between
"this build cannot" and "you may not" (docs/runtime-protocol-v0.md §4). It is
recovered without a permission check: an ``unknown_method`` error names
``knownOnHostEntry`` when the method exists in the host table.

This module owns transport only. Every operation lives in ``rt_core`` so the
CLI and the MCP adapter reach the same objects (Phase 2).
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import Cancelled  # noqa: E402
from rt_codes import (  # noqa: E402
    IMPL_VERSION,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    RpcError,
)
from rt_core import AGENT_METHODS, HOST_ONLY_METHODS, RuntimeCore  # noqa: E402
from rt_jsonl import (  # noqa: E402
    READ_EOF,
    READ_LINE,
    READ_OVERSIZE,
    FrameWriter,
    StrictJsonError,
    decode_frame,
    log,
    read_raw_frame,
)

ENTRIES = ("host", "agent")
UNKNOWN_FIELD_POLICIES = ("reject", "ignore")

_REQUEST_MEMBERS = {"kind", "id", "method", "params"}
_CANCEL_MEMBERS = {"kind", "id"}


def _object(value, allowed: set[str], *, required: tuple[str, ...] = (),
            where: str = "params", policy: str = "reject") -> dict:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise RpcError("invalid_params", f"{where} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        if policy == "reject":
            raise RpcError("unknown_field",
                           f"{where} carries fields this method does not define",
                           where=where, unknown=unknown, allowed=sorted(allowed))
        value = {key: item for key, item in value.items() if key in allowed}
    missing = [name for name in required if name not in value]
    if missing:
        raise RpcError("invalid_params", f"{where} is missing required fields",
                       where=where, missing=missing)
    return value


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    return value


class RuntimeServer:
    def __init__(self, *, entry: str, root: Path, engine_root: Path | None = None,
                 stdin=None, stdout=None):
        if entry not in ENTRIES:
            raise ValueError(f"entry must be one of {ENTRIES}")
        self.entry = entry
        self.core = RuntimeCore(root, engine_root)
        self._in = stdin if stdin is not None else sys.stdin.buffer
        self._write_lock = threading.Lock()
        self.out = FrameWriter(stdout if stdout is not None else sys.stdout.buffer,
                               self._write_lock)
        self.initialized = False
        self.unknown_field_policy = "reject"
        self.client = None
        self._seen_ids: set = set()
        self._cancelled: set = set()
        self._state_lock = threading.Lock()
        self._methods = self._build_registry()

    # -- registries ---------------------------------------------------------
    def _agent_methods(self) -> dict:
        methods = {
            "initialize": self._m_initialize,
            "capabilities/list": self._m_capabilities,
            "session/list": self._m_session_list,
            "document/inspect": self._m_document_inspect,
            "document/readRegion": self._m_document_read_region,
            "plan/propose": self._m_plan_propose,
            "plan/validate": self._m_plan_validate,
            "plan/get": self._m_plan_get,
            "approval/request": self._m_approval_request,
            "approval/get": self._m_approval_get,
            "candidate/list": self._m_candidate_list,
            "receipt/read": self._m_receipt_read,
        }
        # One roster (rt_core.AGENT_METHODS). Adding a handler without listing
        # it there — or the reverse — must be loud, because the MCP adapter
        # derives its whole tool surface from that tuple.
        assert set(methods) == set(AGENT_METHODS), (
            "agent handler map and rt_core.AGENT_METHODS disagree: "
            f"{sorted(set(methods) ^ set(AGENT_METHODS))}")
        return methods

    def _host_only_methods(self) -> dict:
        methods = {
            "workspace/openPath": self._m_open_path,
            "approval/resolve": self._m_approval_resolve,
            "plan/apply": self._m_plan_apply,
        }
        assert set(methods) == set(HOST_ONLY_METHODS), (
            "host handler map and rt_core.HOST_ONLY_METHODS disagree: "
            f"{sorted(set(methods) ^ set(HOST_ONLY_METHODS))}")
        return methods

    def _build_registry(self) -> dict:
        methods = self._agent_methods()
        if self.entry == "host":
            methods.update(self._host_only_methods())
        return methods

    def host_method_names(self) -> list[str]:
        return sorted(self._host_only_methods())

    # backwards-compatible accessors for the modules and tests that had them
    @property
    def store(self):
        return self.core.store

    @property
    def tools(self):
        return self.core.tools

    # -- loop ---------------------------------------------------------------
    def _read_loop(self, inbox: "queue.Queue") -> None:
        while True:
            kind, raw = read_raw_frame(self._in, MAX_FRAME_BYTES)
            if kind == READ_EOF:
                inbox.put(("eof", None))
                return
            if kind == READ_OVERSIZE:
                inbox.put(("bad", None, RpcError(
                    "frame_too_large",
                    f"a frame exceeded the {MAX_FRAME_BYTES}-byte cap and was "
                    "refused without being parsed",
                    limit=MAX_FRAME_BYTES)))
                continue
            assert kind == READ_LINE
            try:
                frame = decode_frame(raw)
            except StrictJsonError as exc:
                inbox.put(("bad", None, RpcError(exc.code, exc.detail)))
                continue
            if frame.get("kind") == "cancel":
                unknown = sorted(set(frame) - _CANCEL_MEMBERS)
                if unknown:
                    inbox.put(("bad", frame.get("id"), RpcError(
                        "unknown_field", "cancel frames carry only kind and id",
                        unknown=unknown)))
                    continue
                with self._state_lock:
                    self._cancelled.add(frame.get("id"))
                continue
            inbox.put(("frame", frame))

    def serve(self) -> int:
        inbox: "queue.Queue" = queue.Queue()
        reader = threading.Thread(target=self._read_loop, args=(inbox,), daemon=True)
        reader.start()
        while True:
            item = inbox.get()
            if item[0] == "eof":
                break
            if item[0] == "bad":
                self.out.fail(item[1], item[2])
                continue
            self._handle(item[1])
        return 0

    # -- one request --------------------------------------------------------
    def _handle(self, frame: dict) -> None:
        frame_id = frame.get("id")
        if frame.get("kind") != "request":
            self.out.fail(frame_id, RpcError(
                "frame_malformed",
                "a client sends only request and cancel frames",
                kind=frame.get("kind")))
            return
        unknown = sorted(set(frame) - _REQUEST_MEMBERS)
        if unknown:
            self.out.fail(frame_id, RpcError(
                "unknown_field", "request frames carry only kind, id, method, params",
                unknown=unknown, allowed=sorted(_REQUEST_MEMBERS)))
            return
        if not isinstance(frame_id, (str, int)) or isinstance(frame_id, bool):
            self.out.fail(None, RpcError("frame_malformed",
                                         "id must be a string or an integer"))
            return
        method = frame.get("method")
        if not isinstance(method, str):
            self.out.fail(frame_id, RpcError("frame_malformed",
                                             "method must be a string"))
            return
        with self._state_lock:
            if frame_id in self._seen_ids:
                self.out.fail(frame_id, RpcError(
                    "duplicate_request_id",
                    "this id was already used on this connection", id=frame_id))
                return
            self._seen_ids.add(frame_id)
            already_cancelled = frame_id in self._cancelled

        try:
            if already_cancelled:
                raise Cancelled()
            if not self.initialized and method != "initialize":
                raise RpcError("not_initialized",
                               "send initialize before any other method",
                               method=method)
            handler = self._methods.get(method)
            if handler is None:
                raise RpcError(
                    "unknown_method", f"this build has no method {method!r}",
                    method=method, entry=self.entry,
                    known=sorted(self._methods),
                    knownOnHostEntry=method in HOST_ONLY_METHODS)
            params = frame.get("params")
            if params is not None and not isinstance(params, dict):
                raise RpcError("invalid_params", "params must be an object")
            result = handler(params or {}, frame_id)
        except Cancelled:
            self.out.fail(frame_id, RpcError("cancelled",
                                             "request cancelled by the client",
                                             id=frame_id))
        except RpcError as exc:
            self.out.fail(frame_id, exc)
        except Exception:  # noqa: BLE001 - one bug must not kill the connection
            log("runtime internal error:\n" + traceback.format_exc())
            self.out.fail(frame_id, RpcError("internal_error",
                                             "the Runtime failed to serve this "
                                             "request; see stderr"))
        else:
            self.out.respond(frame_id, result)

    def _checkpoint(self, request_id):
        def tick():
            with self._state_lock:
                cancelled = request_id in self._cancelled
            if cancelled:
                raise Cancelled()
        return tick

    # -- methods: parameter validation, then straight to the core ------------
    def _m_initialize(self, params: dict, _id) -> dict:
        if self.initialized:
            raise RpcError("already_initialized",
                           "this connection is already initialized")
        params = _object(params, {"protocolVersion", "client", "unknownFieldPolicy"},
                         required=("protocolVersion",), where="initialize.params",
                         policy="reject")
        version = params["protocolVersion"]
        if version != PROTOCOL_VERSION:
            raise RpcError("protocol_version_unsupported",
                           f"this Runtime speaks protocol {PROTOCOL_VERSION!r} only",
                           offered=version, supported=[PROTOCOL_VERSION])
        policy = params.get("unknownFieldPolicy", "reject")
        if policy not in UNKNOWN_FIELD_POLICIES:
            raise RpcError("invalid_params",
                           f"unknownFieldPolicy must be one of "
                           f"{list(UNKNOWN_FIELD_POLICIES)}", offered=policy)
        client = _object(params.get("client"), {"name", "version"},
                         where="initialize.params.client", policy="reject")
        self.unknown_field_policy = policy
        self.client = client
        self.initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "implVersion": IMPL_VERSION,
            "entry": self.entry,
            "unknownFieldPolicy": policy,
            "capabilities": self.core.capability_snapshot(
                methods=list(self._methods)),
        }

    def _capability_snapshot(self) -> dict:
        """Kept for callers that used it before the core existed."""
        return self.core.capability_snapshot(methods=list(self._methods))

    def _m_capabilities(self, params: dict, _id) -> dict:
        _object(params, set(), where="capabilities/list.params",
                policy=self.unknown_field_policy)
        return self.core.capabilities(entry=self.entry, methods=list(self._methods))

    def _m_open_path(self, params: dict, _id) -> dict:
        params = _object(params, {"path"}, required=("path",),
                         where="workspace/openPath.params",
                         policy=self.unknown_field_policy)
        return self.core.open_path(params["path"])

    def _m_session_list(self, params: dict, _id) -> dict:
        _object(params, set(), where="session/list.params",
                policy=self.unknown_field_policy)
        return self.core.session_list()

    def _m_document_inspect(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "include"}, required=("sessionId",),
                         where="document/inspect.params",
                         policy=self.unknown_field_policy)
        include = params.get("include")
        if include is not None and not isinstance(include, list):
            raise RpcError("invalid_params", "include must be an array")
        return self.core.document_inspect(params["sessionId"], include)

    def _m_document_read_region(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "regions"},
                         required=("sessionId", "regions"),
                         where="document/readRegion.params",
                         policy=self.unknown_field_policy)
        regions = params["regions"]
        if isinstance(regions, list):
            regions = [
                _object(entry, {"table", "row", "col", "atPara"},
                        where=f"regions[{index}]",
                        policy=self.unknown_field_policy)
                if isinstance(entry, dict) else entry
                for index, entry in enumerate(regions)
            ]
        return self.core.document_read_region(params["sessionId"], regions)

    def _m_plan_propose(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "backend", "ops", "proposer"},
                         required=("sessionId", "backend", "ops"),
                         where="plan/propose.params",
                         policy=self.unknown_field_policy)
        return self.core.plan_propose(
            params["sessionId"], _text(params["backend"], "backend"),
            params["ops"], params.get("proposer") or f"{self.entry}-client")

    def _m_plan_validate(self, params: dict, _id) -> dict:
        params = _object(params, {"planId"}, required=("planId",),
                         where="plan/validate.params",
                         policy=self.unknown_field_policy)
        return self.core.plan_validate(params["planId"])

    def _m_plan_get(self, params: dict, _id) -> dict:
        params = _object(params, {"planId"}, required=("planId",),
                         where="plan/get.params", policy=self.unknown_field_policy)
        return self.core.plan_get(params["planId"])

    def _m_approval_request(self, params: dict, _id) -> dict:
        params = _object(params, {"planId", "requestedBy"}, required=("planId",),
                         where="approval/request.params",
                         policy=self.unknown_field_policy)
        return self.core.approval_request(
            params["planId"], params.get("requestedBy") or f"{self.entry}-client")

    def _m_approval_get(self, params: dict, _id) -> dict:
        params = _object(params, {"approvalId"}, required=("approvalId",),
                         where="approval/get.params",
                         policy=self.unknown_field_policy)
        return self.core.approval_get(params["approvalId"])

    def _m_approval_resolve(self, params: dict, _id) -> dict:
        params = _object(params, {"approvalId", "planId", "planHash", "decision",
                                  "approver"},
                         required=("approvalId", "planId", "planHash", "decision"),
                         where="approval/resolve.params",
                         policy=self.unknown_field_policy)
        return self.core.approval_resolve(
            params["approvalId"], _text(params["planId"], "planId"),
            _text(params["planHash"], "planHash"),
            _text(params["decision"], "decision"),
            params.get("approver") or "host-operator")

    def _m_plan_apply(self, params: dict, request_id) -> dict:
        params = _object(params, {"planId", "approvalId"},
                         required=("planId", "approvalId"),
                         where="plan/apply.params",
                         policy=self.unknown_field_policy)
        return self.core.plan_apply(params["planId"], params["approvalId"],
                                    checkpoint=self._checkpoint(request_id))

    def _m_candidate_list(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId"}, required=("sessionId",),
                         where="candidate/list.params",
                         policy=self.unknown_field_policy)
        return self.core.candidate_list(params["sessionId"])

    def _m_receipt_read(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "runId"},
                         required=("sessionId", "runId"),
                         where="receipt/read.params",
                         policy=self.unknown_field_policy)
        return self.core.receipt_read(params["sessionId"], params["runId"])
