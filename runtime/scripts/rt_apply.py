#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute an approved plan against a COPY, then publish a bound candidate.

Three properties this module owes the rest of the system:

1. **The source is never the subject.** Every step reads one file and writes
   another under ``work/``; the session's source copy is input to step 1 and is
   never an output. That is ``preedit``'s own rule
   (engine/scripts/preedit.py:2335) carried up one level.
2. **A candidate is canonical only once its receipt lands.** Publication is two
   renames — artifact, then receipt — and the run directory is removed if
   anything between them fails. A run directory without ``receipt.json`` is not
   a candidate, which is why ``list_candidates`` skips it. Same shape as
   ``rollback_publication`` in
   pipeline/scripts/diagnostic_candidate_core.py:26.
3. **A check that could not run is never a pass.** ``VerificationReport``
   carries ``unavailable`` as a first-class state and ``acceptance`` is false
   whenever a required check did not run — the rule ``visual_verify`` states at
   pipeline/scripts/visual_verify.py:42-47 ("acceptance is not nothing failed").
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import IMPL_VERSION, RECEIPT_SCHEMA, RpcError  # noqa: E402
from rt_jsonl import canonical_bytes  # noqa: E402
from rt_session import atomic_write_bytes, now_utc, sha256_file  # noqa: E402

RECEIPT_NAME = "receipt.json"
REQUIRED_CHECKS = ("check_residue",)


class Cancelled(Exception):
    """Raised by a checkpoint between steps. Cooperative, never a kill."""


def _argv_for(kind: str, params: dict, source: Path, target: Path) -> list[str]:
    """One preedit invocation per op. Chained by the caller through work files."""
    if kind == "fill_cell":
        table = int(params.get("table", 0))
        row, col = int(params["row"]), int(params["col"])
        argv = ["fill-cells", str(source), "--out", str(target),
                "--table", str(table)]
        if isinstance(params.get("lines"), list):
            for line in params["lines"]:
                argv += ["--cell-line", f"{row},{col}={line}"]
        else:
            argv += ["--cell", f"{row},{col}={params['text']}"]
        if params.get("charPr"):
            argv += ["--charpr-per-cell", f"{row},{col}={params['charPr']}"]
        if params.get("paraPr"):
            argv += ["--parapr-per-cell", f"{row},{col}={params['paraPr']}"]
        if params.get("overwrite"):
            argv.append("--overwrite")
        return argv

    if kind == "replace_at_cell":
        table = int(params.get("table", 0))
        row, col = int(params["row"]), int(params["col"])
        addr = f"{row},{col}"
        if params.get("run") is not None:
            addr += f"#{int(params['run'])}"
        flag = ("--at-cell-append" if params.get("mode") == "append"
                else "--at-cell")
        argv = ["replace", str(source), "--out", str(target),
                "--table", str(table), flag, f"{addr}={params['text']}"]
        if params.get("expect") is not None:
            argv += ["--at-cell-expect", f"{addr}={params['expect']}"]
        if params.get("charPr"):
            argv += ["--at-cell-charpr", f"{addr}={params['charPr']}"]
        return argv

    if kind == "set_run":
        return ["set-runs", str(source), "--out", str(target),
                "--run", f"{int(params['atPara'])},{int(params['run'])}="
                         f"{params['text']}"]

    if kind == "delete_guides":
        argv = ["delete-guides", str(source), "--out", str(target)]
        if params.get("color"):
            argv += ["--color", str(params["color"])]
        if params.get("charPrIds"):
            argv += ["--charpr-ids", ",".join(str(x) for x in params["charPrIds"])]
        return argv

    raise RpcError("unknown_op_kind", f"no preedit mapping for {kind!r}", kind=kind)


def _atomic_move(source: Path, target: Path) -> None:
    """Stream the finished work file into place, durably.

    The copy is written through a handle opened for WRITING so it can be
    fsynced: ``os.fsync`` on a read-only handle is ``EBADF`` on Windows, which
    is exactly the kind of platform detail a "just copy then fsync" shortcut
    hides until the first real run.
    """
    tmp = target.with_name(f".tmp-{uuid.uuid4().hex}-{target.name}")
    with source.open("rb") as reader, tmp.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    os.replace(tmp, target)


def _publish_receipt(run_dir: Path, receipt: dict) -> Path:
    """Write the receipt LAST. Its presence is what makes the run canonical."""
    body = dict(receipt)
    body["bodySha256"] = hashlib.sha256(
        canonical_bytes(receipt, omit=("bodySha256",))).hexdigest()
    target = run_dir / RECEIPT_NAME
    atomic_write_bytes(target, json.dumps(body, ensure_ascii=False, indent=2,
                                     sort_keys=True, allow_nan=False).encode("utf-8"))
    return target


def verification_report(tools, source_profile: Path, candidate: Path) -> dict:
    """Run the offline checkers we have; report the ones we do not as unavailable."""
    checks = [tools.residue(source_profile, candidate)]
    by_name = {row["checker"]: row for row in checks}
    ran_all = all(by_name.get(name, {}).get("state") == "ran"
                  for name in REQUIRED_CHECKS)
    clean = all(by_name.get(name, {}).get("ok") is True for name in REQUIRED_CHECKS)
    if not ran_all:
        reason = "a required check did not run"
    elif not clean:
        reason = "a required check reported findings"
    else:
        reason = None
    return {
        "required": list(REQUIRED_CHECKS),
        "ranAll": ran_all,
        "acceptance": bool(ran_all and clean),
        "reason": reason,
        "checks": checks,
        "note": ("acceptance asserts that every required check RAN and was "
                 "clean; a check that could not run is reported unavailable and "
                 "never counted as a pass"),
    }


def apply_plan(tools, session, plan, approval, *, checkpoint=None) -> dict:
    """Run the plan, publish the candidate, return the CandidateArtifact."""
    ops = plan.payload["ops"]
    run_id = uuid.uuid4().hex
    run_dir = session.candidates_dir / run_id
    work_dir = session.work_dir / run_id
    suffix = session.source.suffix or ".bin"

    def tick():
        if checkpoint is not None:
            checkpoint()

    try:
        work_dir.mkdir(parents=True, exist_ok=False)
        run_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise RpcError("publication_failed", "could not create the run directory",
                       detail=str(exc)) from exc

    steps: list[dict] = []
    current = session.source
    try:
        for index, op in enumerate(ops):
            tick()
            target = work_dir / f"step{index + 1}{suffix}"
            argv = _argv_for(op["kind"], op["params"], current, target)
            code, parsed, raw = tools.preedit_run(argv)
            step = {"opId": op["opId"], "kind": op["kind"],
                    "subcommand": argv[0], "exitCode": code}
            if code != 0:
                # Pass the engine's refusal through VERBATIM. It already carries
                # the escape hatch (engine/scripts/preedit.py:2694-2717); a
                # flattened message is what makes a caller open section.xml.
                raise RpcError(
                    "backend_refused",
                    (parsed or {}).get("error")
                    or f"preedit {argv[0]} refused this op (exit {code})",
                    opId=op["opId"], kind=op["kind"], exitCode=code,
                    backend="preedit", refusal=parsed,
                    raw=None if parsed else raw[:4000])
            step["result"] = parsed
            steps.append(step)
            current = target
        tick()

        artifact = run_dir / f"artifact{suffix}"
        _atomic_move(current, artifact)
        candidate_sha, candidate_bytes = sha256_file(artifact)

        source_profile = session.profile_dir / f"verify-{run_id}.json"
        tools.profile(session.source, source_profile)
        checks = verification_report(tools, source_profile, artifact)

        receipt = {
            "schema": RECEIPT_SCHEMA,
            "implVersion": IMPL_VERSION,
            "createdUtc": now_utc(),
            "runId": run_id,
            "sessionId": session.id,
            "planId": plan.id,
            "planHash": plan.hash,
            "backend": plan.payload["backend"],
            "source": {
                "name": session.meta["sourceName"],
                "sha256": session.meta["sourceSha256"],
                "bytes": session.meta["sourceBytes"],
            },
            "candidate": {
                "role": "assembled_hwpx",
                "path": artifact.name,
                "sha256": candidate_sha,
                "bytes": candidate_bytes,
            },
            "approval": approval.public(),
            "steps": steps,
            "checks": checks,
            "evidence": {
                "class": "structural_only",
                "note": ("no renderer ran; this receipt binds bytes and offline "
                         "checker results, and claims no render proof"),
            },
        }
        _publish_receipt(run_dir, receipt)
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    shutil.rmtree(work_dir, ignore_errors=True)
    return {
        "runId": run_id,
        "sessionId": session.id,
        "planId": plan.id,
        "candidate": receipt["candidate"],
        "checks": checks,
        "receipt": f"{run_id}/{RECEIPT_NAME}",
        "canonical": True,
    }


def workspace_verification_report() -> dict:
    """What apply verified about a workspace candidate: nothing, and it says so.

    A document candidate gets ``check_residue`` here. A workspace has no such
    offline gate at apply time — its verification is ``module/check`` against
    this candidate's ``runId``, which is a separate call because it runs a
    module's checkers and costs seconds per checker. So ``acceptance`` is false
    with the reason, never a pass nobody earned
    (pipeline/scripts/visual_verify.py:42-47).
    """
    return {
        "required": [],
        "ranAll": False,
        "acceptance": False,
        "reason": ("no checker ran at apply time; a workspace candidate is "
                   "verified by module/check with this runId"),
        "checks": [],
        "note": ("acceptance is never true here: this build verifies a "
                 "workspace candidate by running the modules' checkers against "
                 "it, and that is a call the caller makes"),
    }


def apply_workspace_plan(session, plan, approval, *, read_only,
                         checkpoint=None) -> dict:
    """Execute a workspace plan onto a CANDIDATE TREE, then publish a receipt.

    The document rule, one level up (rt_apply's property 1): the session's own
    workspace copy is input and never output. The candidate is a whole second
    tree under the run directory, and the session copy is re-hashed after the
    ops have run — if it moved, the run is destroyed rather than published,
    because a candidate whose source drifted is a candidate about nothing.
    """
    from rt_workspace import copy_tree, hash_tree  # noqa: PLC0415
    from rt_wsops import run_ops  # noqa: PLC0415

    run_id = uuid.uuid4().hex
    run_dir = session.candidates_dir / run_id
    name = session.meta["workspaceName"]
    source_tree = session.meta["workspaceTreeSha256"]

    def tick():
        if checkpoint is not None:
            checkpoint()

    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise RpcError("publication_failed", "could not create the run directory",
                       detail=str(exc)) from exc

    try:
        tick()
        copied = copy_tree(session.workspace, run_dir / name)
        if copied["treeSha256"] != source_tree:
            raise RpcError(
                "candidate_hash_mismatch",
                "the copy of the session workspace does not hash to the session "
                "copy; nothing is edited rather than something unidentified",
                expected=source_tree, got=copied["treeSha256"])
        tick()
        result = run_ops(run_dir / name, plan.payload["ops"], read_only=read_only)
        if result["hard"]:
            # Validation passed on a scratch copy and apply refused: the
            # workspace moved under us, or the copy differs. Either way the
            # engine's own answer goes back verbatim.
            raise RpcError("backend_refused",
                           "an op refused while applying it to the candidate "
                           "tree, after validating on a scratch copy",
                           backend="workspace", hard=result["hard"],
                           applied=result["steps"],
                           notEvaluated=result["notEvaluated"])
        tick()
        candidate = hash_tree(run_dir / name)
        after = hash_tree(session.workspace)
        if after["treeSha256"] != source_tree:
            raise RpcError(
                "candidate_hash_mismatch",
                "the session workspace changed while the plan was being applied "
                "to the candidate; the source is never the subject",
                expected=source_tree, got=after["treeSha256"])

        receipt = {
            "schema": RECEIPT_SCHEMA,
            "implVersion": IMPL_VERSION,
            "createdUtc": now_utc(),
            "runId": run_id,
            "sessionId": session.id,
            "planId": plan.id,
            "planHash": plan.hash,
            "backend": plan.payload["backend"],
            "source": {
                "name": name,
                "treeSha256": source_tree,
                "files": session.meta["workspaceFiles"],
                "bytes": session.meta["workspaceBytes"],
            },
            "candidate": {
                "role": "workspace_tree",
                "path": name,
                "treeSha256": candidate["treeSha256"],
                "files": candidate["files"],
                "bytes": candidate["bytes"],
            },
            "approval": approval.public(),
            "steps": result["steps"],
            "checks": workspace_verification_report(),
            "lineage": {
                # Lineage the way a document candidate records it: the plan
                # binds the source hash, the receipt names both ends, and
                # module/check --run walks forward from here.
                "kind": "workspace",
                "boundSha256": plan.payload["boundSha256"],
                "fromTreeSha256": source_tree,
                "toTreeSha256": candidate["treeSha256"],
                "approvalId": approval.id,
                "membershipChanged": candidate["files"] != copied["files"],
            },
            "evidence": {
                "class": "structural_only",
                "note": ("this receipt binds a source tree hash to a candidate "
                         "tree hash and the ops between them; no checker ran "
                         "here and it claims no verdict about the report"),
            },
        }
        _publish_receipt(run_dir, receipt)
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise

    return {
        "runId": run_id,
        "sessionId": session.id,
        "planId": plan.id,
        "candidate": receipt["candidate"],
        "checks": receipt["checks"],
        "steps": result["steps"],
        "receipt": f"{run_id}/{RECEIPT_NAME}",
        "canonical": True,
    }


def list_candidates(session) -> list[dict]:
    """Only runs whose receipt landed. A bare artifact is not a candidate."""
    rows = []
    if not session.candidates_dir.is_dir():
        return rows
    for run_dir in sorted(session.candidates_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (run_dir / RECEIPT_NAME).is_file():
            continue
        rows.append({"runId": run_dir.name,
                     "receipt": f"{run_dir.name}/{RECEIPT_NAME}"})
    return rows


def read_receipt(session, run_id: str) -> dict:
    """Load a receipt and REFUSE unless it still binds the bytes on disk."""
    if not isinstance(run_id, str) or not run_id or "/" in run_id or "\\" in run_id:
        raise RpcError("invalid_params", "runId must be a bare identifier",
                       runId=run_id)
    run_dir = session.candidates_dir / run_id
    receipt_path = run_dir / RECEIPT_NAME
    if not receipt_path.is_file():
        raise RpcError("artifact_missing", "no canonical candidate for that runId",
                       runId=run_id)
    try:
        raw = receipt_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RpcError("artifact_missing", "receipt is unreadable",
                       runId=run_id, detail=str(exc)) from exc
    from rt_jsonl import StrictJsonError, loads_strict
    try:
        payload = loads_strict(raw)
    except StrictJsonError as exc:
        raise RpcError("receipt_body_mismatch",
                       f"receipt does not parse strictly: {exc.detail}",
                       runId=run_id, strictCode=exc.code) from exc
    if not isinstance(payload, dict):
        raise RpcError("receipt_body_mismatch", "receipt is not an object",
                       runId=run_id)
    declared = payload.get("bodySha256")
    recomputed = hashlib.sha256(
        canonical_bytes(payload, omit=("bodySha256",))).hexdigest()
    if declared != recomputed:
        raise RpcError("receipt_body_mismatch",
                       "the receipt body does not match its own hash",
                       runId=run_id, declared=declared, recomputed=recomputed)
    candidate = payload.get("candidate") or {}
    artifact = run_dir / str(candidate.get("path") or "")
    if candidate.get("role") == "workspace_tree":
        # A tree, so the binding is the tree hash — the same re-verification a
        # document candidate gets, over the thing this candidate actually is.
        from rt_workspace import hash_tree  # noqa: PLC0415

        if not artifact.is_dir():
            raise RpcError("artifact_missing",
                           "the bound candidate workspace is gone",
                           runId=run_id, path=candidate.get("path"))
        actual = hash_tree(artifact)
        if actual["treeSha256"] != candidate.get("treeSha256"):
            raise RpcError("candidate_hash_mismatch",
                           "the candidate workspace changed after the receipt "
                           "was written",
                           runId=run_id, declared=candidate.get("treeSha256"),
                           actual=actual["treeSha256"])
        return payload
    if not artifact.is_file():
        raise RpcError("artifact_missing", "the bound candidate is gone",
                       runId=run_id, path=candidate.get("path"))
    actual_sha, actual_bytes = sha256_file(artifact)
    if actual_sha != candidate.get("sha256") or actual_bytes != candidate.get("bytes"):
        raise RpcError("candidate_hash_mismatch",
                       "the candidate bytes changed after the receipt was written",
                       runId=run_id, declared=candidate.get("sha256"),
                       actual=actual_sha)
    return payload
