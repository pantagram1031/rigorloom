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
    candidate_artifact,
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
    PROTOCOL_VERSION,
    SUPPORTED_BACKENDS,
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
    wanted_full_text,
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
    region_runs_with_faces,
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
    "candidate/compare",
    "receipt/read",
    "document/render",
    "document/pageGeometry",
    "event/poll",
    "module/list",
    "module/check",
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
HOST_ONLY_METHODS: tuple[str, ...] = (
    "workspace/openPath",
    "approval/resolve",
    "plan/apply",
    "document/renderPrepare",
)

METHODS: tuple[str, ...] = (AGENT_METHODS + PROTOCOL_ONLY_METHODS
                            + HOST_ONLY_METHODS)

INCLUDE_SECTIONS = ("summary", "graph", "regions")


def _text_by_spec(profile: dict) -> dict:
    """{--full-text spec: text} out of a profile's opt-in ``full_text`` block.

    Keyed on the same spelling ``full_text_spec`` produces, so a comparison
    keeps the caller's own addresses and never has to re-derive them. An entry
    the profile did not return is simply absent — see ``candidate_compare`` on
    why absent must not read as equal.
    """
    out: dict[str, str] = {}
    for entry in profile.get("full_text", []) or []:
        try:
            if "at_para" in entry:
                key = f"PARA:{int(entry['at_para'])}"
            else:
                addr = entry.get("addr") or {}
                key = (f"{int(entry.get('table', 0))}:"
                       f"{int(addr['row'])},{int(addr['col'])}")
        except (TypeError, ValueError, KeyError):
            continue
        text = entry.get("text")
        if isinstance(text, str):
            out[key] = text
    return out


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

    def session_list(self) -> dict:
        return {"sessions": self.store.list()}

    # -- documents ----------------------------------------------------------
    def document_inspect(self, session_id, include=None) -> dict:
        session = self.store.get(session_id)
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

    @staticmethod
    def _region_specs(regions) -> list[str]:
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
        return specs

    def document_read_region(self, session_id, regions, run_id=None) -> dict:
        """Exact text for named addresses, in the source or in a candidate.

        ``runId`` is what makes an undo derivable rather than remembered: the
        value a reversal must restore is read out of the candidate the edit was
        made ON, through the runtime's own reader, not out of whatever a client
        happened to keep in memory. The candidate is resolved through its
        receipt, so its bytes were re-verified before anything read them.
        """
        session = self.store.get(session_id)
        specs = self._region_specs(regions)
        subject = None
        subject_facts = {"kind": "session_source",
                         "sha256": session.meta["sourceSha256"]}
        tag = f"region-{len(specs)}"
        if run_id is not None:
            subject, receipt = candidate_artifact(session, self._bare_run_id(run_id))
            subject_facts = {"kind": "candidate", "runId": run_id,
                             "sha256": receipt["candidate"]["sha256"]}
            tag = f"region-{run_id[:12]}-{len(specs)}"
        profile = load_profile(self.tools, session, tag=tag,
                               full_text=specs, subject=subject)
        return bound_region_result({
            "sessionId": session.id,
            "documentHash": profile.get("form_hash"),
            # WHICH DOCUMENT ANSWERED. A caller that asked for a candidate and
            # silently got the source would draw the wrong "before" and call it
            # proof, so the subject is stated on every answer, source included.
            "subject": subject_facts,
            # Each run carries the face its charPr resolves to (§14), joined
            # from the header the profile already read. A caret standing in a
            # run can then be told what it is set in instead of being handed
            # an integer.
            "regions": region_runs_with_faces(profile),
        })

    @staticmethod
    def _bare_run_id(run_id) -> str:
        if (not isinstance(run_id, str) or not run_id
                or "/" in run_id or "\\" in run_id):
            raise RpcError("invalid_params", "runId must be a bare identifier",
                           runId=run_id)
        return run_id

    # -- plans --------------------------------------------------------------
    def plan_subject(self, session, plan) -> tuple:
        """(path or None, digest) for the document a plan is computed against.

        ``None`` means the session source, which is what ``load_profile`` and
        ``apply_plan`` both default to — so the base-less path is byte-for-byte
        the path this build had before lineage existed.
        """
        base = plan.payload.get("base") or None
        if base is None:
            return None, session.current_source_sha256()
        path, receipt = candidate_artifact(session, str(base["runId"]))
        return path, receipt["candidate"]["sha256"]

    def plan_propose(self, session_id, backend, ops, proposer,
                     base_run_id=None, reverses=None) -> dict:
        """Build a plan against the session source, or onto a published candidate.

        ``baseRunId`` is the chain. Without it every apply starts from the
        source, which made two consecutive applies two siblings rather than a
        history — the second one silently missing the first one's edit. With
        it, a plan binds the candidate's digest and the apply chains onto its
        bytes.

        ``reverses`` is a claim, recorded next to the bytes that will back it:
        this plan undoes that candidate. It is checked afterwards with
        ``candidate/compare``, never taken on trust here.
        """
        session = self.store.get(session_id)
        if not isinstance(backend, str) or not backend:
            raise RpcError("invalid_params", "backend must be a non-empty string")
        base = None
        bound = session.current_source_sha256()
        if base_run_id is not None:
            _, base_receipt = candidate_artifact(session,
                                                 self._bare_run_id(base_run_id))
            base = {"runId": base_run_id,
                    "sha256": base_receipt["candidate"]["sha256"]}
            bound = base["sha256"]
        reversal = None
        if reverses is not None:
            reversal_id = reverses.get("runId") if isinstance(reverses, dict) else reverses
            _, reversed_receipt = candidate_artifact(session,
                                                     self._bare_run_id(reversal_id))
            reversal = {"runId": reversal_id,
                        "sha256": reversed_receipt["candidate"]["sha256"]}
        plan = build_plan(session_id=session.id, backend=backend, ops=ops,
                          proposer=proposer, bound_sha256=bound,
                          base=base, reverses=reversal)
        self.save_plan(plan)
        append_event(session, "plan.proposed", planId=plan.id,
                     opsHash=plan.payload["opsHash"], backend=backend,
                     proposer=proposer, ops=len(plan.payload["ops"]),
                     baseRunId=(base or {}).get("runId"),
                     reversesRunId=(reversal or {}).get("runId"))
        return {"plan": plan.public()}

    def plan(self, plan_id) -> OperationPlan:
        payload = self.store.load_record("plans", plan_id)
        if payload is None:
            raise RpcError("unknown_plan", "no such plan under this root",
                           planId=plan_id)
        return OperationPlan(payload)

    def save_plan(self, plan: OperationPlan) -> None:
        self.store.save_record("plans", plan.id, plan.payload)

    def validated(self, plan: OperationPlan) -> dict:
        """Validate against the plan's OWN subject — source, or its base candidate.

        A plan chained onto a candidate must be checked against that
        candidate's cell classifications and run inventory, not the source's:
        the second edit of a paragraph addresses runs the first edit produced.
        And `current_sha256` is that subject's digest, so a candidate-based
        plan is never stale — a published candidate is immutable, which is the
        honest reason rather than an exemption.
        """
        session = self.store.get(plan.payload["sessionId"])
        subject, current = self.plan_subject(session, plan)
        tag = "base" if subject is None else f"cand-{plan.payload['base']['runId'][:12]}"
        base = load_profile(self.tools, session, tag=tag, subject=subject)
        profile = base
        specs = safe_full_text_specs(wanted_full_text(plan), base)
        if specs:
            try:
                profile = load_profile(self.tools, session,
                                       tag=f"plan-{plan.id[:12]}", full_text=specs,
                                       subject=subject)
            except RpcError:
                # A paragraph address out of range makes form_inspect exit 2.
                # Degrade to the base profile; the validator then reports
                # run_inventory_unavailable rather than assuming clean.
                profile = base
        return validate_plan(plan, profile=profile, current_sha256=current)

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
                           "this plan does not validate against the current document",
                           planId=plan.id, hard=report["hard"])
        result = apply_plan(self.tools, session, plan, record, checkpoint=checkpoint)
        plan.state = "applied"
        self.save_plan(plan)
        append_event(session, "plan.applied", planId=plan.id,
                     runId=result["runId"])
        append_event(session, "candidate.published", runId=result["runId"],
                     sha256=result["candidate"]["sha256"],
                     acceptance=result["checks"]["acceptance"],
                     ranAll=result["checks"]["ranAll"])
        return {"candidate": result}

    # -- rendering ----------------------------------------------------------
    def document_render(self, session_id, *, page: int = 0,
                        dpi: int | None = None, run_id=None,
                        inline: bool = True) -> dict:
        session = self.store.get(session_id)
        session.ensure_dirs()
        from rt_codes import DEFAULT_RENDER_DPI
        return render_page(session, page=page,
                           dpi=DEFAULT_RENDER_DPI if dpi is None else dpi,
                           run_id=run_id, inline=inline, tools=self.tools)

    def document_render_prepare(self, session_id, *, run_id=None,
                                timeout: float | None = None) -> dict:
        """HOST ONLY. Convert the session copy — or a candidate — to a PDF.

        ``runId`` is what E1.2's 다시 그리기 needs: after an apply the page on
        screen is still the SOURCE's raster, and the only honest way to show
        the candidate is to render the candidate. Whether this machine can is a
        separate question, and the refusal (``needs_hancom`` / ``com_busy``) is
        the answer it gives here exactly as it does for the source.
        """
        from rt_convert import prepare_pdf

        session = self.store.get(session_id)
        session.ensure_dirs()
        candidate = None
        if run_id is not None:
            path, receipt = candidate_artifact(session, self._bare_run_id(run_id))
            candidate = {"runId": run_id, "path": path,
                         "sha256": receipt["candidate"]["sha256"]}
        result = prepare_pdf(session, self.tools, timeout=timeout,
                             candidate=candidate)
        if result.get("prepared"):
            append_event(session, "pdf.prepared",
                         sha256=result["pdf"]["sha256"],
                         bytes=result["pdf"]["bytes"],
                         producedBy=result["pdf"]["producedBy"],
                         runId=run_id)
        return result

    def document_page_geometry(self, session_id, *, page: int = 0,
                               run_id=None) -> dict:
        """Real text positions from the rendered PDF, mapped to addresses."""
        session = self.store.get(session_id)
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
                             profile=profile, cache=self._geometry_cache,
                             tools=self.tools)

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
        session = self.store.get(session_id)
        return {"sessionId": session.id, "candidates": list_candidates(session)}

    def receipt_read(self, session_id, run_id) -> dict:
        session = self.store.get(session_id)
        return {"receipt": read_receipt(session, run_id)}

    def candidate_compare(self, session_id, run_id, against=None,
                          regions=None) -> dict:
        """Compare two documents of this session at named addresses. Read-only.

        THIS IS WHERE AN UNDO IS PROVEN, and it is here rather than in a client
        because a client comparing two strings it fetched is comparing its own
        memory. Both sides are re-read through ``form_inspect`` from bytes that
        ``read_receipt`` re-verified against their binding, and the answer says
        per address whether the text is equal.

        ``against`` is ``{"runId": …}`` for another candidate or
        ``{"source": true}`` for the session copy; it defaults to the source.

        Two levels of equality, kept apart because they are different facts:

          * ``regionsEqual`` — the addresses asked about hold identical text.
            That is what "the undo restored the value" means, and it is what an
            inverse must satisfy.
          * ``artifactEqual`` — the two documents are the same bytes. An edit
            and its inverse WILL usually not reach this: preedit rewrites XML
            and rezips, so whitespace, member order and zip metadata move even
            when every character of text is restored. It is reported rather
            than hidden, and a ``false`` here beside a ``true`` above is the
            normal, honest outcome — never presented as a failure of the undo.
        """
        session = self.store.get(session_id)
        left_path, left_receipt = candidate_artifact(session,
                                                     self._bare_run_id(run_id))
        left_facts = {"kind": "candidate", "runId": run_id,
                      "sha256": left_receipt["candidate"]["sha256"]}

        if against is not None and not isinstance(against, dict):
            raise RpcError("invalid_params", "against must be an object")
        against = against or {"source": True}
        if against.get("runId") is not None:
            other = self._bare_run_id(against["runId"])
            right_path, right_receipt = candidate_artifact(session, other)
            right_facts = {"kind": "candidate", "runId": other,
                           "sha256": right_receipt["candidate"]["sha256"]}
        elif against.get("source") is True:
            right_path = None
            right_facts = {"kind": "session_source",
                           "sha256": session.meta["sourceSha256"]}
        else:
            raise RpcError("invalid_params",
                           "against must name a runId or set source: true",
                           against=against)

        rows: list[dict] = []
        if regions is not None:
            specs = self._region_specs(regions)
            left = load_profile(self.tools, session,
                                tag=f"cmp-l-{run_id[:12]}", full_text=specs,
                                subject=left_path)
            right = load_profile(self.tools, session,
                                 tag=f"cmp-r-{run_id[:12]}", full_text=specs,
                                 subject=right_path)
            left_text = _text_by_spec(left)
            right_text = _text_by_spec(right)
            for spec in specs:
                # ABSENT is not EMPTY. A cell the profile did not return is
                # `null` here and `equal` is null with it — the comparison did
                # not happen, and a caller must not read that as a match.
                a = left_text.get(spec)
                b = right_text.get(spec)
                rows.append({
                    "address": spec,
                    "left": a,
                    "right": b,
                    "equal": None if (a is None or b is None) else a == b,
                })

        compared = [row for row in rows if row["equal"] is not None]
        return {
            "sessionId": session.id,
            "left": left_facts,
            "right": right_facts,
            "artifactEqual": left_facts["sha256"] == right_facts["sha256"],
            "regions": rows,
            "regionsCompared": len(compared),
            "regionsEqual": (bool(compared) and all(row["equal"] for row in compared)
                             if rows else None),
            "regionsUnreadable": [row["address"] for row in rows
                                  if row["equal"] is None],
            "normalizer": "exact",
            "note": ("region text is compared byte-exact as form_inspect returns "
                     "it; artifactEqual compares whole-file digests and is "
                     "normally false between an edit and its inverse because "
                     "preedit rewrites and rezips the package"),
        }

    def candidate_verify(self, session_id, run_id) -> dict:
        """Re-run the offline checks against a published candidate.

        Domain, but NOT a v0 protocol method — it is absent from ``METHODS`` on
        purpose, so it does not silently widen the MCP tool surface. The CLI
        exposes it; the wire does not.

        The receipt is read first, which means the candidate bytes are
        re-verified against their binding before any checker is asked about
        them (``rt_apply.read_receipt``).
        """
        session = self.store.get(session_id)
        receipt = read_receipt(session, run_id)
        artifact = session.candidates_dir / run_id / receipt["candidate"]["path"]
        profile = session.profile_dir / f"verify-{run_id}-recheck.json"
        self.tools.profile(session.source, profile)
        checks = verification_report(self.tools, profile, artifact)
        return {"sessionId": session.id, "runId": run_id,
                "candidate": receipt["candidate"], "checks": checks}
