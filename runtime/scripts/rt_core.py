#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The domain layer. One implementation, three front ends.

Phase 2 adds a CLI and an MCP adapter beside the JSONL server. None of them
may fork document semantics, so the operations live here and the front ends
own only their own concerns:

  * ``rt_server``   — JSONL framing, the initialize handshake, the
                      unknown-field policy, cancellation, and WHICH methods a
                      connection can reach;
  * ``cli``         — argument parsing and process exit codes;
  * ``mcp_server``  — JSON-RPC 2.0 over stdio and the MCP tool envelope.

A plan proposed through the CLI and a plan proposed through the server differ
only in the ``proposer`` string the caller passes; the object, its hash and
its validation come from the same code. ``tests/test_runtime_parity.py``
proves that rather than asserting it here.

``METHODS`` is the one roster. ``rt_server`` asserts its handler map matches it
at construction, and the MCP adapter derives its tool surface from
``AGENT_METHODS`` — so adding an agent method surfaces it everywhere, and
adding one without a tool schema is a loud failure rather than a silent
omission.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import (  # noqa: E402
    apply_plan,
    apply_workspace_plan,
    list_candidates,
    read_receipt,
    verification_report,
)
from rt_codes import (  # noqa: E402
    IMPL_VERSION,
    KNOWN_BACKENDS,
    MAX_FRAME_BYTES,
    MAX_REGION_BYTES,
    MAX_SOURCE_BYTES,
    MAX_WORKSPACE_BYTES,
    MAX_WORKSPACE_DEPTH,
    MAX_WORKSPACE_FILES,
    PROTOCOL_VERSION,
    SESSION_KINDS,
    SUPPORTED_BACKENDS,
    WORKSPACE_REJECT_REASONS,
    RpcError,
)
from rt_engine import EngineTools, child_python_facts  # noqa: E402
from rt_plan import (  # noqa: E402
    COM_OP_KINDS,
    DEFERRED_REFUSALS,
    PREEDIT_NOT_IMPLEMENTED,
    PREEDIT_OP_KINDS,
    XML_OP_KINDS,
    ApprovalRecord,
    OperationPlan,
    build_plan,
    request_approval,
    resolve_approval,
    safe_full_text_specs,
    validate_plan,
    validate_workspace_plan,
    wanted_full_text,
)
from rt_wsops import (  # noqa: E402
    WS_BACKEND,
    WS_NOT_IMPLEMENTED,
    WS_OP_KINDS,
    WS_REFUSAL_CODES,
    read_member,
    read_only_matcher,
)
from rt_geometry import geometry_capability, page_geometry  # noqa: E402
from rt_module import (  # noqa: E402
    module_capability,
    module_list,
    run_module_checks,
)
from rt_render import render_capability, render_page  # noqa: E402
from rt_session import (  # noqa: E402
    MAX_EVENTS_PER_POLL_DEFAULT,
    SessionStore,
    append_event,
    read_events,
    bound_region_result,
    document_graph,
    document_summary,
    editable_regions,
    full_text_spec,
    load_profile,
)

#: Every method an agent connection may reach, ``initialize`` included.
AGENT_METHODS: tuple[str, ...] = (
    "initialize",
    "capabilities/list",
    "session/list",
    "document/inspect",
    "document/readRegion",
    "plan/propose",
    "plan/validate",
    "plan/get",
    "approval/request",
    "approval/get",
    "candidate/list",
    "receipt/read",
    "document/render",
    "document/pageGeometry",
    "event/poll",
    "module/list",
    "module/check",
    "workspace/inspect",
    "workspace/readMember",
    "workspace/listMembers",
)

#: Agent-safe by authority, but transport-shaped: they push notifications, and
#: an MCP tool call has nowhere to put one. Registered on both JSONL entries and
#: deliberately absent from the MCP tool surface, which offers ``event/poll``
#: instead — the same events, request/response, for a client that cannot be
#: pushed to.
PROTOCOL_ONLY_METHODS: tuple[str, ...] = (
    "event/subscribe",
    "event/unsubscribe",
)

#: Host authority. The agent registry does not BUILD these (decision D8).
#:
#: ``workspace/openDirectory`` is host-only for the same reason
#: ``workspace/openPath`` is, and more so: it takes an arbitrary absolute path
#: and reaches a whole TREE with it. Filesystem reach is the authority being
#: granted, and no agent-safe method should grant it. Once a host has opened
#: one, every agent-safe method operates on the session — never on a path.
#:
#: NAMING DEBT, recorded rather than papered over: ``workspace/openPath``
#: opens a DOCUMENT. The name predates there being a workspace session at all
#: and docs/runtime-protocol-v0.md §11.4 already records where the confusion
#: started. Renaming it to ``document/openPath`` is a wire break for every
#: client on this stack, so the new method takes a distinct name and the
#: rename is proposed in §15.8, not smuggled in here.
HOST_ONLY_METHODS: tuple[str, ...] = (
    "workspace/openPath",
    "workspace/openDirectory",
    "approval/resolve",
    "plan/apply",
    "document/renderPrepare",
)

METHODS: tuple[str, ...] = (AGENT_METHODS + PROTOCOL_ONLY_METHODS
                            + HOST_ONLY_METHODS)

INCLUDE_SECTIONS = ("summary", "graph", "regions")


class RuntimeCore:
    """Sessions, documents, plans, approvals and candidates under one root."""

    def __init__(self, root: Path | str, engine_root: Path | str | None = None):
        self.store = SessionStore(Path(root))
        self.tools = EngineTools(engine_root)
        self._render_probe: dict | None = None
        # Extractions keyed on the PDF hash and page, so re-opening a
        # page does not re-read every glyph position.
        self._geometry_cache: dict = {}

    # -- capabilities -------------------------------------------------------
    def capability_snapshot(self, *, methods: list[str]) -> dict:
        tools = self.tools.availability()
        backends = {
            "preedit": {
                "state": tools["preedit"]["state"],
                "reason": tools["preedit"]["reason"],
                "opKinds": sorted(PREEDIT_OP_KINDS),
                "notImplemented": list(PREEDIT_NOT_IMPLEMENTED),
                "subject": "document",
            },
            WS_BACKEND: {
                "state": "available",
                "reason": None,
                "opKinds": sorted(WS_OP_KINDS),
                "notImplemented": list(WS_NOT_IMPLEMENTED),
                "subject": "workspace",
                "refusalCodes": list(WS_REFUSAL_CODES),
            },
            "xml": {"state": "unavailable",
                    "reason": "declared by the protocol; not executed by this build",
                    "opKinds": sorted(XML_OP_KINDS)},
            "com": {"state": "unavailable",
                    "reason": "declared by the protocol; not executed by this build",
                    "opKinds": sorted(COM_OP_KINDS)},
        }
        return {
            "methods": sorted(methods),
            "backends": backends,
            "supportedBackends": list(SUPPORTED_BACKENDS),
            "knownBackends": list(KNOWN_BACKENDS),
            "tools": tools,
            "limits": {
                "maxFrameBytes": MAX_FRAME_BYTES,
                "maxRegionBytes": MAX_REGION_BYTES,
                "maxSourceBytes": MAX_SOURCE_BYTES,
                "maxWorkspaceBytes": MAX_WORKSPACE_BYTES,
                "maxWorkspaceFiles": MAX_WORKSPACE_FILES,
                "maxWorkspaceDepth": MAX_WORKSPACE_DEPTH,
            },
            "sessionKinds": {
                "kinds": list(SESSION_KINDS),
                "open": {"document": "workspace/openPath",
                         "workspace": "workspace/openDirectory"},
                "workspaceRejectReasons": list(WORKSPACE_REJECT_REASONS),
                "note": ("workspace/openPath opens a DOCUMENT; the name predates "
                         "the workspace kind and is kept because renaming a "
                         "shipped method breaks every client on this stack"),
            },
            "render": render_capability(),
            "geometry": geometry_capability(),
            "modules": module_capability(self.tools.root),
            "childPython": child_python_facts(),
            "deferredRefusals": list(DEFERRED_REFUSALS),
            "unavailable": {
                "renderProbe": ("not run unless capabilities/list is called "
                                "with probeRenderers:true; it costs seconds"),
                "descendantContainment": "not_established",
            },
        }

    def capability_snapshot_probed(self, *, methods: list[str]) -> dict:
        """The snapshot plus this machine's renderer inventory. Cached, slow."""
        snapshot = self.capability_snapshot(methods=methods)
        if self._render_probe is None:
            self._render_probe = self.tools.render_probe()
        snapshot["render"] = dict(snapshot["render"])
        snapshot["render"]["machineProbe"] = self._render_probe
        return snapshot

    def capabilities(self, *, entry: str, methods: list[str],
                     probe_renderers: bool = False) -> dict:
        snapshot = (self.capability_snapshot_probed(methods=methods)
                    if probe_renderers
                    else self.capability_snapshot(methods=methods))
        return {"protocolVersion": PROTOCOL_VERSION, "implVersion": IMPL_VERSION,
                "entry": entry, **snapshot}

    # -- sessions -----------------------------------------------------------
    def open_path(self, path) -> dict:
        session = self.store.open_path(path)
        append_event(session, "session.opened",
                     sourceName=session.meta["sourceName"],
                     sourceSha256=session.meta["sourceSha256"],
                     documentKind=session.meta["ingress"].get("documentKind"))
        return session.summary()

    def open_workspace(self, path) -> dict:
        """HOST ONLY. Validate, copy and hash a report workspace directory.

        The answer is the summary a caller needs before it does anything else:
        the copy's tree hash, its size, and which declared parts are there.
        """
        session = self.store.open_workspace(path)
        append_event(session, "workspace.opened",
                     workspaceName=session.meta["workspaceName"],
                     treeSha256=session.meta["workspaceTreeSha256"],
                     files=session.meta["workspaceFiles"],
                     bytes=session.meta["workspaceBytes"])
        return self._workspace_summary(session)

    def session_list(self) -> dict:
        return {"sessions": self.store.list()}

    # -- workspaces ---------------------------------------------------------
    def _declared_layout(self) -> dict:
        """Every enabled module's workspace layout, or an honest 'undeclared'.

        Read here by both the summary and the write path: which parts a module
        declares ``read_only`` is the same declaration that says which parts
        exist, and a second source for it would be a second contract.
        """
        from rt_module import load_registry, _module_registry
        from rt_workspace import declared_layout

        try:
            module_registry = _module_registry(self.tools.root)
            registry, _facts = load_registry(self.tools.root)
            return declared_layout(registry, module_registry)
        except RpcError as exc:
            return {"state": "undeclared", "reason": exc.message,
                    "declaredBy": [], "schemas": [], "parts": [],
                    "sources": [], "kinds": []}

    def _workspace_summary(self, session) -> dict:
        from rt_workspace import layout_report, scan_undeclared

        summary = session.summary()
        layout = self._declared_layout()
        root = session.workspace
        summary["layout"] = layout_report(root, layout)
        summary["undeclared"] = scan_undeclared(root, layout)
        summary["immutability"] = (
            "the operator's directory was read and copied; this session "
            "addresses the copy, and every checker addresses a scratch copy of "
            "the copy")
        summary["copy"] = session.meta.get("copy", {})
        summary["ingress"] = session.meta.get("ingress", {})
        return summary

    def workspace_inspect(self, session_id) -> dict:
        """Which declared parts this workspace session has, per part."""
        session = self.store.get(session_id).require_kind("workspace")
        return self._workspace_summary(session)

    def _workspace_read_root(self, session, run_id) -> tuple[Path, dict]:
        """The tree an agent-safe workspace READ addresses, and what it is.

        Never the operator's source path: with no ``runId`` it is the session
        copy every other workspace method already addresses; with one, it is a
        published candidate, and ``read_receipt`` re-verifies the candidate's
        tree hash before a byte of it is read — the same rule
        ``rt_module._resolve_subject`` already applies for ``module/check``.
        """
        if run_id is None:
            return session.workspace, {"kind": "workspace", "runId": None}
        receipt = read_receipt(session, run_id)
        candidate = receipt["candidate"]
        if candidate.get("role") != "workspace_tree":
            raise RpcError("artifact_missing",
                           "that runId names a document candidate, and this "
                           "session holds a workspace",
                           sessionId=session.id, runId=run_id,
                           role=candidate.get("role"))
        return session.candidates_dir / run_id / candidate["path"], {
            "kind": "candidate_workspace", "runId": run_id,
            "treeSha256": candidate["treeSha256"]}

    @staticmethod
    def _member_refusal(finding: dict) -> RpcError:
        """A workspace-ops finding, surfaced as the transport error it names.

        ``finding["code"]`` is one of the closed reasons ``rt_wsops`` already
        refuses a write op with; §15.8's read gap wants the identical refusal
        one layer up, not a second vocabulary invented for reading.
        """
        extra = {key: value for key, value in finding.items()
                 if key not in ("code", "msg")}
        return RpcError(finding["code"], finding["msg"], **extra)

    def workspace_read_member(self, session_id, path, run_id=None) -> dict:
        """UTF-8 text of one workspace member — the read half of the fix loop.

        Bounded exactly as a write op bounds it: over ``MAX_MEMBER_BYTES`` is
        ``member_too_large``, not UTF-8 is ``member_not_text``, outside the
        tree or not relative is ``path_not_relative``, absent is
        ``member_missing``. Reads the session copy, or a published candidate
        when ``runId`` is given — never the operator's directory.
        """
        session = self.store.get(session_id).require_kind("workspace")
        root, subject = self._workspace_read_root(session, run_id)
        text, member, refusal = read_member(root, path, "path")
        if refusal is not None:
            raise self._member_refusal(refusal)
        return {"sessionId": session.id, "subject": subject, "path": member,
                "text": text, "bytes": len(text.encode("utf-8"))}

    def workspace_list_members(self, session_id, run_id=None) -> dict:
        """Every member of the workspace copy: path, kind and a file's size.

        An agent cannot aim ``workspace/readMember`` at a path it cannot see,
        so this is the other half of the same gap (§15.8).
        """
        from rt_workspace import list_members

        session = self.store.get(session_id).require_kind("workspace")
        root, subject = self._workspace_read_root(session, run_id)
        members = list_members(root)
        return {"sessionId": session.id, "subject": subject,
                "members": members, "count": len(members)}

    # -- documents ----------------------------------------------------------
    def _document(self, session_id):
        return self.store.get(session_id).require_kind("document")

    def document_inspect(self, session_id, include=None) -> dict:
        session = self._document(session_id)
        include = list(include) if include else list(INCLUDE_SECTIONS)
        if not all(item in INCLUDE_SECTIONS for item in include):
            raise RpcError("invalid_params",
                           f"include must be a subset of {list(INCLUDE_SECTIONS)}",
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

    def document_read_region(self, session_id, regions) -> dict:
        session = self._document(session_id)
        if not isinstance(regions, list) or not regions:
            raise RpcError("invalid_params", "regions must be a non-empty array")
        specs: list[str] = []
        for index, entry in enumerate(regions):
            if not isinstance(entry, dict):
                raise RpcError("invalid_params", f"regions[{index}] must be an object")
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

    # -- plans --------------------------------------------------------------
    def _workspace_ops(self, session):
        """(the workspace root, the read-only matcher) for a workspace plan."""
        return session.workspace, read_only_matcher(self._declared_layout())

    def plan_propose(self, session_id, backend, ops, proposer) -> dict:
        if not isinstance(backend, str) or not backend:
            raise RpcError("invalid_params", "backend must be a non-empty string")
        # The backend decides which session kind the plan is about, and
        # ``require_kind`` names the mismatch rather than letting a workspace
        # reach a document validator and refuse about a file that is a
        # directory (rt_session.require_kind, §15.4).
        if backend == WS_BACKEND:
            session = self.store.get(session_id).require_kind("workspace")
            bound = self.workspace_tree_sha256(session)
        else:
            session = self._document(session_id)
            bound = session.current_source_sha256()
        plan = build_plan(session_id=session.id, backend=backend, ops=ops,
                          proposer=proposer, bound_sha256=bound)
        self.save_plan(plan)
        append_event(session, "plan.proposed", planId=plan.id,
                     opsHash=plan.payload["opsHash"], backend=backend,
                     proposer=proposer, ops=len(plan.payload["ops"]))
        return {"plan": plan.public()}

    def plan(self, plan_id) -> OperationPlan:
        payload = self.store.load_record("plans", plan_id)
        if payload is None:
            raise RpcError("unknown_plan", "no such plan under this root",
                           planId=plan_id)
        return OperationPlan(payload)

    def save_plan(self, plan: OperationPlan) -> None:
        self.store.save_record("plans", plan.id, plan.payload)

    def workspace_tree_sha256(self, session) -> str:
        """The session copy's tree hash, read now rather than trusted from meta.

        A plan binds bytes, and "the bytes I copied at open" is not the same
        claim as "the bytes that are there" — the staleness check is only worth
        anything if it re-reads.
        """
        from rt_workspace import hash_tree

        return hash_tree(session.workspace)["treeSha256"]

    def validated(self, plan: OperationPlan) -> dict:
        session = self.store.get(plan.payload["sessionId"])
        if plan.payload["backend"] == WS_BACKEND:
            session.ensure_dirs()
            workspace, read_only = self._workspace_ops(session)
            return validate_workspace_plan(
                plan, workspace=workspace,
                current_tree_sha256=self.workspace_tree_sha256(session),
                read_only=read_only, scratch_parent=session.work_dir)
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

    def plan_validate(self, plan_id) -> dict:
        plan = self.plan(plan_id)
        report = self.validated(plan)
        plan.state = "validated" if report["ok"] else "invalid"
        self.save_plan(plan)
        append_event(self.store.get(plan.payload["sessionId"]), "plan.validated",
                     planId=plan.id, verdict=report["verdict"], ok=report["ok"],
                     hard=[row["code"] for row in report["hard"]])
        return {"validation": report}

    def plan_get(self, plan_id) -> dict:
        return {"plan": self.plan(plan_id).public()}

    # -- approvals ----------------------------------------------------------
    def approval(self, approval_id) -> ApprovalRecord:
        payload = self.store.load_record("approvals", approval_id)
        if payload is None:
            raise RpcError("unknown_approval", "no such approval under this root",
                           approvalId=approval_id)
        return ApprovalRecord(payload)

    def save_approval(self, record: ApprovalRecord) -> None:
        self.store.save_record("approvals", record.id, record.payload)

    def approval_request(self, plan_id, requested_by) -> dict:
        plan = self.plan(plan_id)
        record = request_approval(plan, requested_by)
        self.save_approval(record)
        append_event(self.store.get(plan.payload["sessionId"]),
                     "approval.requested", planId=plan.id,
                     approvalId=record.id, requestedBy=requested_by)
        return {"approval": record.public()}

    def approval_get(self, approval_id) -> dict:
        return {"approval": self.approval(approval_id).public()}

    def approval_resolve(self, approval_id, plan_id, plan_hash, decision,
                         approver) -> dict:
        record = self.approval(approval_id)
        plan = self.plan(plan_id)
        report = self.validated(plan)
        if report["stale"]:
            raise RpcError("plan_stale",
                           "the source changed after this plan was proposed; it "
                           "cannot be approved",
                           planId=plan.id, boundSha256=plan.payload["boundSha256"],
                           currentSha256=report["currentSha256"])
        resolve_approval(record, plan_id=plan_id, plan_hash=plan_hash,
                         decision=decision, approver=approver)
        plan.state = "approved" if record.state == "approved" else "rejected"
        self.save_approval(record)
        self.save_plan(plan)
        append_event(self.store.get(plan.payload["sessionId"]),
                     "approval.resolved", planId=plan.id,
                     approvalId=record.id, state=record.state,
                     approver=approver)
        return {"approval": record.public()}

    # -- apply --------------------------------------------------------------
    def plan_apply(self, plan_id, approval_id, *, checkpoint=None) -> dict:
        plan = self.plan(plan_id)
        record = self.approval(approval_id)
        if (record.payload["planId"] != plan.id
                or record.payload["planHash"] != plan.hash):
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
        report = self.validated(plan)
        if report["stale"]:
            raise RpcError("plan_stale",
                           "the source changed after this plan was approved",
                           planId=plan.id, boundSha256=plan.payload["boundSha256"],
                           currentSha256=report["currentSha256"])
        if not report["ok"]:
            raise RpcError("plan_invalid",
                           "this plan does not validate against the current "
                           f"{session.kind}",
                           planId=plan.id, hard=report["hard"])
        if plan.payload["backend"] == WS_BACKEND:
            session.ensure_dirs()
            _workspace, read_only = self._workspace_ops(session)
            result = apply_workspace_plan(session, plan, record,
                                          read_only=read_only,
                                          checkpoint=checkpoint)
        else:
            result = apply_plan(self.tools, session, plan, record,
                                checkpoint=checkpoint)
        plan.state = "applied"
        self.save_plan(plan)
        append_event(session, "plan.applied", planId=plan.id,
                     runId=result["runId"])
        append_event(session, "candidate.published", runId=result["runId"],
                     sha256=result["candidate"].get("sha256")
                     or result["candidate"].get("treeSha256"),
                     acceptance=result["checks"]["acceptance"],
                     ranAll=result["checks"]["ranAll"])
        return {"candidate": result}

    # -- rendering ----------------------------------------------------------
    def document_render(self, session_id, *, page: int = 0,
                        dpi: int | None = None, run_id=None,
                        inline: bool = True) -> dict:
        session = self._document(session_id)
        session.ensure_dirs()
        from rt_codes import DEFAULT_RENDER_DPI
        return render_page(session, page=page,
                           dpi=DEFAULT_RENDER_DPI if dpi is None else dpi,
                           run_id=run_id, inline=inline)

    def document_render_prepare(self, session_id, *,
                                timeout: float | None = None) -> dict:
        """HOST ONLY. Convert the session copy to a PDF so render can raster it."""
        from rt_convert import prepare_pdf

        session = self._document(session_id)
        session.ensure_dirs()
        result = prepare_pdf(session, self.tools, timeout=timeout)
        if result.get("prepared"):
            append_event(session, "pdf.prepared",
                         sha256=result["pdf"]["sha256"],
                         bytes=result["pdf"]["bytes"],
                         producedBy=result["pdf"]["producedBy"])
        return result

    def document_page_geometry(self, session_id, *, page: int = 0,
                               run_id=None) -> dict:
        """Real text positions from the rendered PDF, mapped to addresses."""
        session = self._document(session_id)
        session.ensure_dirs()
        try:
            profile = load_profile(self.tools, session, tag="base")
        except RpcError:
            # The positions are real whether or not the SOURCE is a form
            # the scanner can read. A PDF opened directly has no form scan
            # and so nothing to map spans onto; that costs the mapping,
            # not the geometry, and page_geometry says which.
            profile = None
        return page_geometry(session, page=page, run_id=run_id,
                             profile=profile, cache=self._geometry_cache)

    # -- distribution modules -------------------------------------------------
    def module_list(self) -> dict:
        """Every declared distribution module and what it contributes here."""
        return module_list(self.tools.root)

    def module_check(self, session_id, module, *, checkers=None, run_id=None,
                     timeout=None) -> dict:
        """Run a module's declared checkers against this session's document.

        Agent-safe: the checker contract is read-only, the subject handed to a
        checker is a scratch copy that is deleted afterwards, and a module can
        only be reached at all if the operator enabled it. See ``rt_module``
        for the whole argument and its residual gap.
        """
        session = self.store.get(session_id)
        session.ensure_dirs()
        result = run_module_checks(session, engine_root=self.tools.root,
                                   module=module, checkers=checkers,
                                   run_id=run_id, timeout=timeout)
        append_event(session, "module.checked", module=module,
                     selected=result["counts"]["selected"],
                     ran=result["counts"]["ran"],
                     acceptance=result["acceptance"],
                     runId=result["subject"]["runId"])
        return result

    # -- events ---------------------------------------------------------------
    def event_poll(self, session_id, after: int = -1,
                   limit: int | None = None) -> dict:
        session = self.store.get(session_id)
        if not isinstance(after, int) or isinstance(after, bool):
            raise RpcError("invalid_params", "after must be an integer",
                           after=after)
        if limit is None:
            limit = MAX_EVENTS_PER_POLL_DEFAULT
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= MAX_EVENTS_PER_POLL_DEFAULT):
            raise RpcError("invalid_params",
                           f"limit must be between 1 and "
                           f"{MAX_EVENTS_PER_POLL_DEFAULT}", limit=limit)
        events, next_seq = read_events(session, after=after, limit=limit)
        return {"sessionId": session.id, "after": after, "events": events,
                "nextSeq": next_seq, "more": len(events) == limit}

    # -- candidates ---------------------------------------------------------
    def candidate_list(self, session_id) -> dict:
        # Either session kind: a candidate is a published run with a receipt,
        # and a workspace session publishes them the same way a document one
        # does. ``read_receipt`` re-verifies whichever thing the receipt binds.
        session = self.store.get(session_id)
        return {"sessionId": session.id, "candidates": list_candidates(session)}

    def receipt_read(self, session_id, run_id) -> dict:
        session = self.store.get(session_id)
        return {"receipt": read_receipt(session, run_id)}

    def candidate_verify(self, session_id, run_id) -> dict:
        """Re-run the offline checks against a published candidate.

        Domain, but NOT a v0 protocol method — it is absent from ``METHODS`` on
        purpose, so it does not silently widen the MCP tool surface. The CLI
        exposes it; the wire does not.

        The receipt is read first, which means the candidate bytes are
        re-verified against their binding before any checker is asked about
        them (``rt_apply.read_receipt``).
        """
        session = self._document(session_id)
        receipt = read_receipt(session, run_id)
        artifact = session.candidates_dir / run_id / receipt["candidate"]["path"]
        profile = session.profile_dir / f"verify-{run_id}-recheck.json"
        self.tools.profile(session.source, profile)
        checks = verification_report(self.tools, profile, artifact)
        return {"sessionId": session.id, "runId": run_id,
                "candidate": receipt["candidate"], "checks": checks}
