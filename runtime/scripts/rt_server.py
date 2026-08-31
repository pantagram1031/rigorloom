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
"""
from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import Cancelled, apply_plan, list_candidates, read_receipt  # noqa: E402
from rt_codes import (  # noqa: E402
    IMPL_VERSION,
    KNOWN_BACKENDS,
    MAX_FRAME_BYTES,
    MAX_REGION_BYTES,
    MAX_SOURCE_BYTES,
    PROTOCOL_VERSION,
    SUPPORTED_BACKENDS,
    RpcError,
)
from rt_engine import EngineTools  # noqa: E402
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
from rt_plan import (  # noqa: E402
    COM_OP_KINDS,
    ApprovalRecord,
    OperationPlan,
    DEFERRED_REFUSALS,
    PREEDIT_NOT_IMPLEMENTED,
    PREEDIT_OP_KINDS,
    XML_OP_KINDS,
    build_plan,
    request_approval,
    resolve_approval,
    safe_full_text_specs,
    validate_plan,
    wanted_full_text,
)
from rt_session import (  # noqa: E402
    SessionStore,
    bound_region_result,
    document_graph,
    document_summary,
    editable_regions,
    full_text_spec,
    load_profile,
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
        self.store = SessionStore(Path(root))
        self.tools = EngineTools(engine_root)
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
        return {
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

    def _host_only_methods(self) -> dict:
        return {
            "workspace/openPath": self._m_open_path,
            "approval/resolve": self._m_approval_resolve,
            "plan/apply": self._m_plan_apply,
        }

    def _build_registry(self) -> dict:
        methods = self._agent_methods()
        if self.entry == "host":
            methods.update(self._host_only_methods())
        return methods

    def host_method_names(self) -> list[str]:
        return sorted(self._host_only_methods())

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
                    knownOnHostEntry=method in self._host_only_methods())
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

    # -- methods ------------------------------------------------------------
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
            "capabilities": self._capability_snapshot(),
        }

    def _capability_snapshot(self) -> dict:
        tools = self.tools.availability()
        backends = {
            "preedit": {
                "state": tools["preedit"]["state"],
                "reason": tools["preedit"]["reason"],
                "opKinds": sorted(PREEDIT_OP_KINDS),
                "notImplemented": list(PREEDIT_NOT_IMPLEMENTED),
            },
            "xml": {"state": "unavailable",
                    "reason": "declared by the protocol; not executed by this build",
                    "opKinds": sorted(XML_OP_KINDS)},
            "com": {"state": "unavailable",
                    "reason": "declared by the protocol; not executed by this build",
                    "opKinds": sorted(COM_OP_KINDS)},
        }
        return {
            "methods": sorted(self._methods),
            "backends": backends,
            "supportedBackends": list(SUPPORTED_BACKENDS),
            "knownBackends": list(KNOWN_BACKENDS),
            "tools": tools,
            "limits": {
                "maxFrameBytes": MAX_FRAME_BYTES,
                "maxRegionBytes": MAX_REGION_BYTES,
                "maxSourceBytes": MAX_SOURCE_BYTES,
            },
            "deferredRefusals": list(DEFERRED_REFUSALS),
            "unavailable": {
                "renderProbe": "not wired in this slice; no renderer capability "
                               "is reported and none is claimed",
                "descendantContainment": "not_established",
            },
        }

    def _m_capabilities(self, params: dict, _id) -> dict:
        _object(params, set(), where="capabilities/list.params",
                policy=self.unknown_field_policy)
        return {"protocolVersion": PROTOCOL_VERSION, "implVersion": IMPL_VERSION,
                "entry": self.entry, **self._capability_snapshot()}

    def _m_open_path(self, params: dict, _id) -> dict:
        params = _object(params, {"path"}, required=("path",),
                         where="workspace/openPath.params",
                         policy=self.unknown_field_policy)
        session = self.store.open_path(params["path"])
        return session.summary()

    def _m_session_list(self, params: dict, _id) -> dict:
        _object(params, set(), where="session/list.params",
                policy=self.unknown_field_policy)
        return {"sessions": self.store.list()}

    def _m_document_inspect(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "include"}, required=("sessionId",),
                         where="document/inspect.params",
                         policy=self.unknown_field_policy)
        session = self.store.get(params["sessionId"])
        include = params.get("include") or ["summary", "graph", "regions"]
        if (not isinstance(include, list)
                or not all(item in ("summary", "graph", "regions") for item in include)):
            raise RpcError("invalid_params",
                           "include must be a subset of summary, graph, regions",
                           offered=include)
        profile = load_profile(self.tools, session, tag="base")
        out: dict = {"sessionId": session.id,
                     "documentHash": profile.get("form_hash")}
        if "summary" in include:
            out["summary"] = document_summary(profile, session)
        if "graph" in include:
            out["graph"] = document_graph(profile, session)
        if "regions" in include:
            out["regions"] = editable_regions(profile, session)
        return out

    def _m_document_read_region(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "regions"},
                         required=("sessionId", "regions"),
                         where="document/readRegion.params",
                         policy=self.unknown_field_policy)
        session = self.store.get(params["sessionId"])
        regions = params["regions"]
        if not isinstance(regions, list) or not regions:
            raise RpcError("invalid_params", "regions must be a non-empty array")
        specs = []
        for index, entry in enumerate(regions):
            entry = _object(entry, {"table", "row", "col", "atPara"},
                            where=f"regions[{index}]",
                            policy=self.unknown_field_policy)
            if "atPara" not in entry and not {"row", "col"} <= set(entry):
                raise RpcError("invalid_params",
                               f"regions[{index}] needs atPara, or row and col")
            try:
                spec = full_text_spec(entry)
            except (TypeError, ValueError, KeyError) as exc:
                raise RpcError("invalid_params",
                               f"regions[{index}] is not an address: {exc}") from exc
            if spec not in specs:
                specs.append(spec)
        profile = load_profile(self.tools, session, tag=f"region-{len(specs)}",
                               full_text=specs)
        return bound_region_result({
            "sessionId": session.id,
            "documentHash": profile.get("form_hash"),
            "regions": profile.get("full_text", []),
        })

    def _m_plan_propose(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "backend", "ops", "proposer"},
                         required=("sessionId", "backend", "ops"),
                         where="plan/propose.params",
                         policy=self.unknown_field_policy)
        session = self.store.get(params["sessionId"])
        plan = build_plan(
            session_id=session.id,
            backend=_text(params["backend"], "backend"),
            ops=params["ops"],
            proposer=params.get("proposer") or f"{self.entry}-client",
            bound_sha256=session.current_source_sha256(),
        )
        self._save_plan(plan)
        return {"plan": plan.public()}

    def _plan(self, plan_id) -> OperationPlan:
        payload = self.store.load_record("plans", plan_id)
        if payload is None:
            raise RpcError("unknown_plan", "no such plan under this root",
                           planId=plan_id)
        return OperationPlan(payload)

    def _save_plan(self, plan: OperationPlan) -> None:
        self.store.save_record("plans", plan.id, plan.payload)

    def _validated(self, plan) -> dict:
        session = self.store.get(plan.payload["sessionId"])
        base = load_profile(self.tools, session, tag="base")
        profile = base
        specs = safe_full_text_specs(wanted_full_text(plan), base)
        if specs:
            try:
                profile = load_profile(self.tools, session,
                                       tag=f"plan-{plan.id[:12]}", full_text=specs)
            except RpcError:
                # A paragraph address out of range makes form_inspect exit 2.
                # Degrade to the base profile; the validator then reports
                # run_inventory_unavailable rather than assuming clean.
                profile = base
        return validate_plan(plan, profile=profile,
                             current_sha256=session.current_source_sha256())

    def _m_plan_validate(self, params: dict, _id) -> dict:
        params = _object(params, {"planId"}, required=("planId",),
                         where="plan/validate.params",
                         policy=self.unknown_field_policy)
        plan = self._plan(params["planId"])
        report = self._validated(plan)
        plan.state = "validated" if report["ok"] else "invalid"
        self._save_plan(plan)
        return {"validation": report}

    def _m_plan_get(self, params: dict, _id) -> dict:
        params = _object(params, {"planId"}, required=("planId",),
                         where="plan/get.params", policy=self.unknown_field_policy)
        return {"plan": self._plan(params["planId"]).public()}

    def _m_approval_request(self, params: dict, _id) -> dict:
        params = _object(params, {"planId", "requestedBy"}, required=("planId",),
                         where="approval/request.params",
                         policy=self.unknown_field_policy)
        plan = self._plan(params["planId"])
        record = request_approval(plan, params.get("requestedBy")
                                  or f"{self.entry}-client")
        self._save_approval(record)
        return {"approval": record.public()}

    def _approval(self, approval_id) -> ApprovalRecord:
        payload = self.store.load_record("approvals", approval_id)
        if payload is None:
            raise RpcError("unknown_approval", "no such approval under this root",
                           approvalId=approval_id)
        return ApprovalRecord(payload)

    def _save_approval(self, record: ApprovalRecord) -> None:
        self.store.save_record("approvals", record.id, record.payload)

    def _m_approval_get(self, params: dict, _id) -> dict:
        params = _object(params, {"approvalId"}, required=("approvalId",),
                         where="approval/get.params",
                         policy=self.unknown_field_policy)
        return {"approval": self._approval(params["approvalId"]).public()}

    def _m_approval_resolve(self, params: dict, _id) -> dict:
        params = _object(params, {"approvalId", "planId", "planHash", "decision",
                                  "approver"},
                         required=("approvalId", "planId", "planHash", "decision"),
                         where="approval/resolve.params",
                         policy=self.unknown_field_policy)
        record = self._approval(params["approvalId"])
        plan = self._plan(params["planId"])
        report = self._validated(plan)
        if report["stale"]:
            raise RpcError("plan_stale",
                           "the source changed after this plan was proposed; it "
                           "cannot be approved",
                           planId=plan.id, boundSha256=plan.payload["boundSha256"],
                           currentSha256=report["currentSha256"])
        resolve_approval(record, plan_id=_text(params["planId"], "planId"),
                         plan_hash=_text(params["planHash"], "planHash"),
                         decision=_text(params["decision"], "decision"),
                         approver=params.get("approver") or "host-operator")
        plan.state = "approved" if record.state == "approved" else "rejected"
        self._save_approval(record)
        self._save_plan(plan)
        return {"approval": record.public()}

    def _m_plan_apply(self, params: dict, request_id) -> dict:
        params = _object(params, {"planId", "approvalId"},
                         required=("planId", "approvalId"),
                         where="plan/apply.params",
                         policy=self.unknown_field_policy)
        plan = self._plan(params["planId"])
        record = self._approval(params["approvalId"])
        if record.payload["planId"] != plan.id or record.payload["planHash"] != plan.hash:
            raise RpcError("approval_binding_mismatch",
                           "that approval does not bind this plan",
                           approvalId=record.id, planId=plan.id,
                           boundPlanId=record.payload["planId"],
                           boundPlanHash=record.payload["planHash"],
                           planHash=plan.hash)
        if record.state != "approved":
            raise RpcError("plan_not_approved",
                           f"the approval for this plan is {record.state}",
                           planId=plan.id, approvalId=record.id, state=record.state)
        session = self.store.get(plan.payload["sessionId"])
        report = self._validated(plan)
        if report["stale"]:
            raise RpcError("plan_stale",
                           "the source changed after this plan was approved",
                           planId=plan.id, boundSha256=plan.payload["boundSha256"],
                           currentSha256=report["currentSha256"])
        if not report["ok"]:
            raise RpcError("plan_invalid",
                           "this plan does not validate against the current "
                           "document",
                           planId=plan.id, hard=report["hard"])
        result = apply_plan(self.tools, session, plan, record,
                            checkpoint=self._checkpoint(request_id))
        plan.state = "applied"
        self._save_plan(plan)
        return {"candidate": result}

    def _m_candidate_list(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId"}, required=("sessionId",),
                         where="candidate/list.params",
                         policy=self.unknown_field_policy)
        session = self.store.get(params["sessionId"])
        return {"sessionId": session.id, "candidates": list_candidates(session)}

    def _m_receipt_read(self, params: dict, _id) -> dict:
        params = _object(params, {"sessionId", "runId"},
                         required=("sessionId", "runId"),
                         where="receipt/read.params",
                         policy=self.unknown_field_policy)
        session = self.store.get(params["sessionId"])
        return {"receipt": read_receipt(session, params["runId"])}
