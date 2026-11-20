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

import json
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_apply import (  # noqa: E402
    _execute_preedit_steps,
    apply_plan,
    candidate_artifact,
    input_snapshot,
    list_candidates,
    read_receipt,
    verification_report,
)
from rt_apply_once import apply_once, session_lock
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
    atomic_write_bytes,
    read_events,
    bound_region_result,
    document_graph,
    document_summary,
    editable_regions,
    forbidden_inventory,
    full_text_spec,
    load_profile,
    now_utc,
    region_runs_with_faces,
    sha256_file,
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
    "document/pageView",
)

METHODS: tuple[str, ...] = (AGENT_METHODS + PROTOCOL_ONLY_METHODS
                            + HOST_ONLY_METHODS)

#: ``forbidden`` is opt-in and deliberately NOT in the default set: it answers
#: a different question from the other three ("what will be held against me",
#: not "what is here"), it is the larger payload, and every existing caller
#: must keep getting exactly the document it got before.
INCLUDE_SECTIONS = ("summary", "graph", "regions", "forbidden")

#: What ``inspect`` answers with when a caller names nothing. Unchanged, and
#: separate from the valid set on purpose: widening what a caller MAY ask for
#: must never widen what an existing caller GETS.
DEFAULT_INCLUDE_SECTIONS = ("summary", "graph", "regions")


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



def _hwp_engine_status() -> dict:
    """Whether the optional HWP engine is configured. Never runs it, and
    leaves out the engine's path, which may name a private directory."""
    import rt_kit
    found = rt_kit.detect()
    return {"available": found["available"],
            "reason": found.get("reason"),
            "env": rt_kit.ENGINE_ENV}

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
            "render": render_capability(self.tools),
            "geometry": geometry_capability(),
            "modules": module_capability(self.tools.root),
            "childPython": child_python_facts(),
            "deferredRefusals": list(DEFERRED_REFUSALS),
            "hwpEngine": _hwp_engine_status(),
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
        include = list(include) if include else list(DEFAULT_INCLUDE_SECTIONS)
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
        if "forbidden" in include:
            out["forbidden"] = forbidden_inventory(profile, session)
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

    def _declaration_inventory(self, session) -> dict:
        """Folded inventory texts, so a keep entry can be checked before approval.

        Read from the session's own base profile — the same document the gate
        will judge — so "this keep names nothing" is a fact about THIS form and
        not a guess. Only loaded when a plan actually declares a keep list, so
        an ordinary propose still costs no extra profile read.
        """
        profile = load_profile(self.tools, session, tag="base")
        inventory = forbidden_inventory(profile, session)
        keepable = {" ".join(str(entry["text"]).split())
                    for entry in inventory["anchors"] + inventory["placeholders"]
                    if isinstance(entry.get("text"), str)}
        guide = {" ".join(str(entry["text"]).split())
                 for entry in inventory["removalTargets"]
                 if isinstance(entry.get("text"), str)}
        return {"keepable": keepable, "guide": guide}

    def plan_propose(self, session_id, backend, ops, proposer,
                     base_run_id=None, reverses=None, declares=None,
                     provenance=None, replaces=None) -> dict:
        """Build a plan against the session source, or onto a published candidate.

        ``baseRunId`` is the chain. Without it every apply starts from the
        source, which made two consecutive applies two siblings rather than a
        history — the second one silently missing the first one's edit. With
        it, a plan binds the candidate's digest and the apply chains onto its
        bytes.

        ``reverses`` is a claim, recorded next to the bytes that will back it:
        this plan undoes that candidate. It is checked afterwards with
        ``candidate/compare``, never taken on trust here.

        ``provenance`` is NOT a caller field. It is the identity of the
        connection the plan arrived on (``serve.py --provider-identity mock``
        for the bundled test agents), passed in by the front end. A plain
        ``proposer`` string no longer decides it. A plan that carries any op a
        test agent proposed in this session stays ``mock`` even when a client
        rebuilds and re-proposes it (``_inherited_mock_ops``). Such a plan
        names, in ``mockOps``, exactly which of its ops repeat a test value;
        the others (the person's own typing) stay the person's, and only ops
        that arrived on the test agent's own connection are remembered as test
        values for later plans.

        ``replaces`` names a queued plan this proposal explicitly replaces. Its
        pending or unconsumed approval is revoked under the session lock, in
        the same step that records the new plan, so the replaced plan cannot be
        approved or applied afterwards.
        """
        session = self.store.get(session_id)
        if provenance not in (None, "mock"):
            raise RpcError("invalid_params", "unknown provenance", provenance=provenance)
        with session_lock(self.store.root, session.id):
            return self._plan_propose_locked(session, backend, ops, proposer,
                                             base_run_id, reverses, declares,
                                             provenance, replaces)

    def _plan_propose_locked(self, session, backend, ops, proposer, base_run_id,
                             reverses, declares, provenance, replaces) -> dict:
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
        replaced = None
        if replaces is not None:
            replaced = self.plan(self._bare_run_id(replaces))
            if replaced.payload.get("sessionId") != session.id:
                raise RpcError("unknown_plan",
                               "the replaced plan belongs to another session",
                               planId=replaced.id, sessionId=session.id)
        inventory = None
        if isinstance(declares, dict) and declares.get("keep"):
            inventory = self._declaration_inventory(session)
        # Only a plan that arrived on the test agent's own connection is a test
        # agent's plan; every op in it is a test value and is remembered. A
        # plan that merely repeats some of those values is labelled mock (the
        # safe direction) with the repeating ops named, and remembers nothing:
        # the person's own typing in it never becomes a "test value".
        from_test_agent = provenance == "mock"
        mock_ops = None
        if provenance is None:
            mock_ops = self._inherited_mock_ops(session, ops) or None
            if mock_ops:
                provenance = "mock"
        plan = build_plan(session_id=session.id, backend=backend, ops=ops,
                          proposer=proposer, bound_sha256=bound,
                          base=base, reverses=reversal, declares=declares,
                          inventory=inventory, provenance=provenance,
                          mock_ops=mock_ops)
        self.save_plan(plan)
        if from_test_agent:
            self._remember_mock_ops(session, plan.payload["ops"])
        append_event(session, "plan.proposed", planId=plan.id,
                     opsHash=plan.payload["opsHash"], backend=backend,
                     proposer=proposer, ops=len(plan.payload["ops"]),
                     provenance=plan.payload.get("provenance"),
                     baseRunId=(base or {}).get("runId"),
                     reversesRunId=(reversal or {}).get("runId"),
                     **({"replaces": replaced.id} if replaced is not None else {}))
        answer = {"plan": plan.public()}
        if replaced is not None:
            revoked = self._retire_approvals(
                session, lambda candidate: candidate.id == replaced.id,
                superseded_by=plan.id)
            answer["replaced"] = {"planId": replaced.id,
                                  "state": self.plan(replaced.id).state,
                                  "revokedApprovals": revoked}
        return answer

    # -- provenance -----------------------------------------------------------
    @staticmethod
    def _op_identity(kind, params) -> str | None:
        """What an op does, independent of how a client spelled it.

        Target address plus the value written. Op ids, ``lines`` versus
        ``text`` and incidental fields (``overwrite``, ``charPr``) are left out
        on purpose: a client that rebuilds a test agent's op keeps its target
        and value, and that is what makes it the test agent's value.
        """
        if not isinstance(params, dict):
            return None
        text = params.get("text")
        if isinstance(params.get("lines"), list):
            text = "\n".join(str(line) for line in params["lines"])
        if kind in ("fill_cell", "replace_at_cell"):
            key = ["cell", params.get("table", 0), params.get("row"), params.get("col")]
        elif kind == "set_run":
            key = ["para", params.get("atPara"), params.get("run")]
        else:
            return None
        return json.dumps(key + [text], ensure_ascii=False, sort_keys=True)

    def _mock_index_path(self, session) -> Path:
        return self.store.root / "provenance" / f"{session.id}.json"

    def _mock_identities(self, session) -> set[str]:
        path = self._mock_index_path(session)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        rows = loaded.get("mockOps") if isinstance(loaded, dict) else None
        return {row for row in rows if isinstance(row, str)} if isinstance(rows, list) else set()

    def _remember_mock_ops(self, session, normalised_ops) -> None:
        known = self._mock_identities(session)
        for op in normalised_ops:
            ident = self._op_identity(op.get("kind"), op.get("params"))
            if ident is not None:
                known.add(ident)
        path = self._mock_index_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, (json.dumps({"mockOps": sorted(known)},
                                             ensure_ascii=False) + "\n").encode("utf-8"))

    def _inherited_mock_ops(self, session, ops) -> list[str]:
        """The op ids (as ``build_plan`` assigns them) that repeat a test agent's op."""
        if not isinstance(ops, list):
            return []
        known = self._mock_identities(session)
        if not known:
            return []
        hits: list[str] = []
        for index, op in enumerate(ops):
            if not isinstance(op, dict):
                continue
            params = {k: v for k, v in op.items() if k not in ("kind", "opId")}
            if self._op_identity(op.get("kind"), params) in known:
                op_id = op.get("opId") or f"op-{index + 1}"
                if isinstance(op_id, str):
                    hits.append(op_id)
        return hits

    def plan(self, plan_id) -> OperationPlan:
        payload = self.store.load_record("plans", plan_id)
        if payload is None:
            raise RpcError("unknown_plan", "no such plan under this root",
                           planId=plan_id)
        return OperationPlan(payload)

    def save_plan(self, plan: OperationPlan) -> None:
        self.store.save_record("plans", plan.id, plan.payload)

    def validated(self, plan: OperationPlan, *, snapshot=None) -> dict:
        """Validate against the plan's OWN subject — source, or its base candidate.

        A plan chained onto a candidate must be checked against that
        candidate's cell classifications and run inventory, not the source's:
        the second edit of a paragraph addresses runs the first edit produced.
        And `current_sha256` is that subject's digest, so a candidate-based
        plan is never stale — a published candidate is immutable, which is the
        honest reason rather than an exemption.

        ``snapshot`` (an ``rt_apply.InputSnapshot``) is the apply path's
        private copy of that subject: when given, the profile is taken from
        the copy and its digest is the current one, so the apply validates the
        very bytes it then executes.
        """
        session = self.store.get(plan.payload["sessionId"])
        if snapshot is None:
            subject, current = self.plan_subject(session, plan)
        else:
            subject, current = snapshot.path, snapshot.sha256
        tag = ("base" if not plan.payload.get("base")
               else f"cand-{plan.payload['base']['runId'][:12]}")
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
        report = validate_plan(plan, profile=profile, current_sha256=current)
        behind = self.behind_head(session, plan)
        if behind is not None:
            report["hard"].append(behind)
            report["ok"] = False
            report["verdict"] = "fail"
            report["counts"]["hard"] = len(report["hard"])
        return report

    # -- the head -------------------------------------------------------------
    @staticmethod
    def head_run_id(session) -> str | None:
        """The newest published candidate of a session, or ``None``.

        The runtime keeps parents, not a head (§15.7), and a person can still
        look at any candidate. But what a NEW plan may be applied onto is not a
        matter of taste: applying onto anything older than the newest
        candidate publishes a file that silently lacks the newest one's
        changes. So for that one question the newest candidate is the head.
        """
        rows = list_candidates(session)
        return rows[-1]["runId"] if rows else None

    def behind_head(self, session, plan) -> dict | None:
        """The ``plan_behind_head`` finding, when the plan predates the head.

        A plan that was already applied is exempt: it IS the history, and its
        base is older than the candidate it produced by construction.
        """
        if plan.state == "applied":
            return None
        head = self.head_run_id(session)
        if head is None:
            return None
        base = plan.payload.get("base") or None
        base_run = base.get("runId") if isinstance(base, dict) else None
        if base_run == head:
            return None
        return {
            "code": "plan_behind_head",
            "msg": ("this plan was computed against "
                    + ("the source" if base_run is None else f"candidate {base_run}")
                    + f", but candidate {head} is newer; applying it would drop "
                    "that candidate's changes. Re-propose on the head."),
            "at": "plan",
            "baseRunId": base_run,
            "headRunId": head,
        }

    def _retire_approvals(self, session, select, *, superseded_by: str) -> list[str]:
        """Revoke the open approvals of the selected plans of this session.

        Open means pending, or approved and not yet consumed by an apply. The
        record is resolved as returned (never approved) by the runtime, with
        ``reasonCode: superseded_by_newer_candidate`` and ``supersededBy``, and
        the matching ``approval.resolved`` event is written next to it. Callers
        hold the session lock, so the record and its event cannot disagree with
        a concurrent writer.
        """
        approvals_dir = self.store.root / "approvals"
        if not approvals_dir.is_dir():
            return []
        retired: list[str] = []
        # A plan with a published candidate consumed its approval, whatever
        # its state field says now (plan/validate rewrites that field).
        published = {row.get("planId") for row in list_candidates(session)}
        for path in sorted(approvals_dir.glob("*.json")):
            payload = self.store.load_record("approvals", path.stem)
            if not payload or payload.get("state") not in ("pending", "approved"):
                continue
            plan_id = payload.get("planId")
            plan_payload = self.store.load_record("plans", plan_id) if isinstance(plan_id, str) else None
            if not plan_payload or plan_payload.get("sessionId") != session.id:
                continue
            plan = OperationPlan(plan_payload)
            if plan.state == "applied" or plan.id in published or not select(plan):
                continue
            record = ApprovalRecord(payload)
            previous = record.state
            if previous == "pending":
                resolve_approval(record, plan_id=plan_id,
                                 plan_hash=payload.get("planHash"),
                                 decision="rejected", approver=None,
                                 reason_code="superseded_by_newer_candidate")
            else:
                # An approval nobody has applied yet is revoked, not re-decided:
                # the person's decision stays on the record beside the reason
                # it can no longer be used.
                record.payload["state"] = "rejected"
                record.payload["reasonCode"] = "superseded_by_newer_candidate"
                record.payload["revokedFrom"] = previous
                record.payload["revokedUtc"] = now_utc()
            record.payload["resolvedBy"] = "runtime"
            record.payload["supersededBy"] = superseded_by
            self.save_approval(record)
            plan.state = "rejected"
            self.save_plan(plan)
            append_event(session, "approval.resolved", planId=plan_id,
                         approvalId=record.id, state="rejected",
                         approver=None,
                         reasonCode="superseded_by_newer_candidate",
                         supersededBy=superseded_by,
                         **({"revokedFrom": previous} if previous != "pending" else {}))
            retired.append(record.id)
        return retired

    def _supersede_invalidated(self, session, applied_plan_id: str) -> list[str]:
        """After a publication: retire approvals whose base is no longer the head.

        Only plans the committed transition invalidated — those computed
        against anything but the current head. A plan proposed on the new head
        (even one proposed while reconciliation was still running) keeps its
        approval. The head is read from the published candidates, never taken
        from the run being reconciled, so reconciling an older publication
        cannot retire approvals on a newer head.
        """
        head = self.head_run_id(session)
        if head is None:
            return []

        def invalidated(plan) -> bool:
            if plan.id == applied_plan_id:
                return False
            base = plan.payload.get("base") or None
            base_run = base.get("runId") if isinstance(base, dict) else None
            return base_run != head

        return self._retire_approvals(session, invalidated, superseded_by=head)

    def plan_validate(self, plan_id) -> dict:
        plan = self.plan(plan_id)
        report = self.validated(plan)
        # An applied plan stays applied: validation is a read, and the state
        # field is what supersession and replay consult.
        if plan.state != "applied":
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
        session = self.store.get(plan.payload["sessionId"])
        with session_lock(self.store.root, session.id):
            plan = self.plan(plan_id)
            record = request_approval(plan, requested_by)
            self.save_approval(record)
            append_event(session, "approval.requested", planId=plan.id,
                         approvalId=record.id, requestedBy=requested_by)
        return {"approval": record.public()}

    def approval_get(self, approval_id) -> dict:
        return {"approval": self.approval(approval_id).public()}

    def approval_resolve(self, approval_id, plan_id, plan_hash, decision,
                         approver, reason=None) -> dict:
        plan = self.plan(plan_id)
        session = self.store.get(plan.payload["sessionId"])
        # The head check, the record replacement and its event are one step:
        # another host's publication cannot land between them.
        with session_lock(self.store.root, session.id):
            return self._approval_resolve_locked(approval_id, plan_id, plan_hash,
                                                 decision, approver, reason)

    def _approval_resolve_locked(self, approval_id, plan_id, plan_hash, decision,
                                 approver, reason) -> dict:
        record = self.approval(approval_id)
        plan = self.plan(plan_id)
        report = self.validated(plan)
        if report["stale"]:
            raise RpcError("plan_stale",
                           "the source changed after this plan was proposed; it "
                           "cannot be approved",
                           planId=plan.id, boundSha256=plan.payload["boundSha256"],
                           currentSha256=report["currentSha256"])
        if decision == "approved":
            # Returning an outdated plan stays possible; approving one does not.
            behind = next((row for row in report["hard"]
                           if row["code"] == "plan_behind_head"), None)
            if behind is not None:
                raise RpcError("plan_behind_head", behind["msg"],
                               planId=plan.id, baseRunId=behind["baseRunId"],
                               headRunId=behind["headRunId"])
        resolve_approval(record, plan_id=plan_id, plan_hash=plan_hash,
                         decision=decision, approver=approver, reason=reason)
        plan.state = "approved" if record.state == "approved" else "rejected"
        self.save_approval(record)
        self.save_plan(plan)
        append_event(self.store.get(plan.payload["sessionId"]),
                     "approval.resolved", planId=plan.id,
                     approvalId=record.id, state=record.state,
                     approver=approver,
                     **({"reason": reason} if reason is not None else {}))
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
        session = self.store.get(plan.payload["sessionId"])
        # From the head check to the receipt, one writer per session: across
        # threads and across host processes on this root.
        with session_lock(self.store.root, session.id):
            # Re-read under the lock: a transition that finished while this
            # call waited may have applied this plan or revoked its approval.
            plan = self.plan(plan_id)
            record = self.approval(approval_id)
            if record.state != "approved":
                # Revoked because a newer candidate exists: say THAT, it is
                # the actionable answer (re-propose on the head).
                behind = (self.behind_head(session, plan)
                          if record.payload.get("reasonCode") == "superseded_by_newer_candidate"
                          else None)
                if behind is not None:
                    raise RpcError("plan_behind_head", behind["msg"],
                                   planId=plan.id, baseRunId=behind["baseRunId"],
                                   headRunId=behind["headRunId"])
                raise RpcError("plan_not_approved",
                               f"the approval for this plan is {record.state}",
                               planId=plan.id, approvalId=record.id, state=record.state)
            return self._plan_apply_locked(session, plan, record, checkpoint)

    def _plan_apply_locked(self, session, plan, record, checkpoint) -> dict:
        def reconcile(result, *, emit_events):
            candidate = result["candidate"]
            if plan.state != "applied":
                plan.state = "applied"
                self.save_plan(plan)
            if emit_events:
                append_event(session, "plan.applied", planId=plan.id,
                             runId=candidate["runId"])
                append_event(session, "candidate.published", runId=candidate["runId"],
                             sha256=candidate["candidate"]["sha256"],
                             acceptance=candidate["checks"]["acceptance"],
                             ranAll=candidate["checks"]["ranAll"])
            # Only approvals whose base this publication invalidated. A
            # replay of a completed apply never gets here (rt_apply_once).
            self._supersede_invalidated(session, plan.id)

        def execute(run_id):
            # One private copy of the input, hashed against the plan's binding
            # (refused as plan_stale otherwise), then validated, executed and
            # graded from that copy alone. The runtime's own copy can change
            # after this line without reaching the candidate.
            with input_snapshot(session, plan, run_id) as snapshot:
                report = self.validated(plan, snapshot=snapshot)
                if report["stale"]:
                    raise RpcError("plan_stale",
                                   "the source changed after this plan was approved",
                                   planId=plan.id, boundSha256=plan.payload["boundSha256"],
                                   currentSha256=report["currentSha256"])
                behind = next((row for row in report["hard"]
                               if row["code"] == "plan_behind_head"), None)
                if behind is not None:
                    raise RpcError("plan_behind_head", behind["msg"],
                                   planId=plan.id, baseRunId=behind["baseRunId"],
                                   headRunId=behind["headRunId"])
                if not report["ok"]:
                    raise RpcError("plan_invalid",
                                   "this plan does not validate against the current document",
                                   planId=plan.id, hard=report["hard"])
                result = apply_plan(self.tools, session, plan, record, checkpoint=checkpoint,
                                    run_id=run_id, snapshot=snapshot)
            response = {"candidate": result}
            reconcile(response, emit_events=True)
            return response

        return apply_once(self.store.root, session, plan, record, execute, reconcile)

    def plan_preview(self, session_id, plan_id, *, out_path=None) -> dict:
        """Read-only plan validation and step preview without mutating runtime state."""
        session = self.store.get(session_id)
        plan = self.plan(plan_id)
        if plan.payload.get("sessionId") != session.id:
            raise RpcError(
                "unknown_plan",
                f"plan {plan.id} does not belong to session {session.id}",
                planId=plan.id,
                sessionId=session.id,
            )
        if plan.payload.get("backend") != "preedit":
            raise RpcError(
                "unsupported_backend",
                f"backend {plan.payload.get('backend')!r} does not support preedit preview",
                planId=plan.id,
                backend=plan.payload.get("backend"),
            )
        # The same discipline as an apply: one private copy, hashed against
        # the binding (plan_stale otherwise), and every read below is of it.
        with input_snapshot(session, plan, f"preview-{uuid.uuid4().hex}",
                            when="proposed") as snapshot, \
                tempfile.TemporaryDirectory(prefix="rigorloom-plan-preview-") as tmp:
            origin, current = snapshot.path, snapshot.sha256
            tmp_dir = Path(tmp)
            base_profile_path = tmp_dir / "profile-base.json"
            self.tools.profile(origin, base_profile_path)
            base = json.loads(base_profile_path.read_text(encoding="utf-8"))
            profile = base
            specs = safe_full_text_specs(wanted_full_text(plan), base)
            if specs:
                try:
                    ft_profile_path = tmp_dir / "profile-ft.json"
                    self.tools.profile(origin, ft_profile_path, full_text=specs)
                    profile = json.loads(ft_profile_path.read_text(encoding="utf-8"))
                except RpcError:
                    profile = base

            report = validate_plan(plan, profile=profile, current_sha256=current)
            if report["stale"]:
                raise RpcError(
                    "plan_stale",
                    "the source changed after this plan was proposed",
                    planId=plan.id,
                    boundSha256=plan.payload["boundSha256"],
                    currentSha256=report["currentSha256"],
                )
            if not report["ok"]:
                raise RpcError(
                    "plan_invalid",
                    "this plan does not validate against the current document",
                    planId=plan.id,
                    hard=report["hard"],
                )

            work_dir = tmp_dir / "work"
            work_dir.mkdir()
            ops = plan.payload["ops"]
            if not ops:
                final_path, steps = origin, []
            else:
                final_path, steps = _execute_preedit_steps(
                    self.tools, ops, origin, work_dir, origin.suffix,
                )
            preview_sha, preview_bytes = sha256_file(final_path)
            written_out = None
            if out_path is not None:
                dst = Path(out_path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(dst, final_path.read_bytes())
                written_out = str(dst)

        return {
            "sessionId": session.id,
            "planId": plan.id,
            "planHash": plan.hash,
            "base": plan.payload.get("base"),
            "validation": report,
            "steps": steps,
            "preview": {"sha256": preview_sha, "bytes": preview_bytes},
            "outPath": written_out,
        }

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
        """Real text positions, mapped against the SAME document revision.

        ``runId`` names the published candidate whose page is on screen.
        The mapping profile is loaded from that candidate — never from the
        session source while geometry reads the candidate — and a missing
        candidate identity is refused rather than silently falling back.
        ``subject`` is the document digest; ``source.sha256`` remains the
        PDF/raster artifact digest when those differ.
        """
        session = self.store.get(session_id)
        session.ensure_dirs()
        subject = None
        subject_facts = {"kind": "session_source",
                         "sha256": session.meta["sourceSha256"]}
        if run_id is not None:
            # Resolve BEFORE the profile try/except: an invalid runId must
            # not be swallowed into unmapped source geometry.
            subject, receipt = candidate_artifact(
                session, self._bare_run_id(run_id))
            subject_facts = {"kind": "candidate", "runId": run_id,
                             "sha256": receipt["candidate"]["sha256"]}
        try:
            tag = "base" if run_id is None else f"geom-{run_id[:12]}"
            profile = load_profile(self.tools, session, tag=tag,
                                   subject=subject)
        except RpcError:
            # The positions are real whether or not this revision is a form
            # the scanner can read. A genuine profile failure costs the
            # mapping, not the geometry, and page_geometry says which.
            profile = None
        result = page_geometry(session, page=page, run_id=run_id,
                               profile=profile, cache=self._geometry_cache,
                               tools=self.tools)
        if isinstance(result, dict):
            result["subject"] = subject_facts
        return result

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
            # A proof covers every address it was asked about. One unreadable
            # region and the answer is "not proven" (null), never "equal".
            "regionsEqual": ((all(row["equal"] for row in rows)
                              if len(compared) == len(rows) else None)
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
        # The declaration comes from the RECEIPT, never from this call. A
        # candidate that passed under a declared keep list must be re-checkable
        # under the same one, and letting a re-check supply its own policy would
        # make "verify" mean "verify against whatever I now claim".
        recorded = receipt.get("exemptions") or {}
        declaration = recorded.get("declares") or None
        checks = verification_report(self.tools, profile, artifact, declaration)
        return {"sessionId": session.id, "runId": run_id,
                "candidate": receipt["candidate"], "checks": checks}
