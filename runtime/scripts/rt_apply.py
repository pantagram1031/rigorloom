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

E1.4 ADDS A FOURTH, AND IT CLOSES A REAL DEFECT.

Until this slice every apply started from ``session.source``, so two applies in
a row produced two SIBLINGS of the source rather than a chain: the second
candidate silently did not contain the first edit, and exporting it lost work
the user had already approved. There was no lineage to walk and therefore
nothing an undo could be the inverse OF.

4. **A candidate names its parent.** A plan may declare a ``base`` — a
   published candidate of the same session — and then the ops are chained onto
   THAT artifact and the receipt records ``base: {runId, sha256}``. A plan with
   no base still starts from the source and records ``base: null``, which is
   the root of the chain. A plan may additionally declare ``reverses``, the
   candidate whose effect it undoes; that too lands in the receipt, so "which
   candidate reverses which" is a runtime fact rather than something a client
   remembered. Nothing is ever deleted or rewritten: history is append-only and
   an undo is one more candidate.
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


def candidate_artifact(session, run_id: str) -> tuple[Path, dict]:
    """(path, receipt) for a published candidate, verified before it is handed out.

    Every caller that wants to READ a candidate — profile it, chain onto it,
    compare it — goes through here rather than composing a path, because
    ``read_receipt`` re-hashes the artifact against its binding and refuses on
    drift. A path built by hand would skip that check silently.
    """
    receipt = read_receipt(session, run_id)
    path = _candidate_path(session, run_id, receipt["candidate"])
    return path, receipt


def _candidate_path(session, run_id: str, candidate: dict) -> Path:
    """Return the one leaf this Runtime can publish, never a receipt-chosen path.

    ``bodySha256`` detects accidental drift; it is not authentication. A local
    writer can recompute it, so a receipt path must not become filesystem
    authority. ``apply_plan`` always publishes exactly ``artifact<suffix>`` in
    the run directory. Every reader requires that canonical spelling and never
    echoes a forged path in the refusal.
    """
    if not isinstance(candidate, dict):
        raise RpcError("receipt_body_mismatch",
                       "receipt candidate descriptor is not an object",
                       runId=run_id)
    expected = f"artifact{session.source.suffix or '.bin'}"
    if candidate.get("path") != expected:
        raise RpcError("path_escape",
                       "receipt candidate path is not the canonical run artifact",
                       runId=run_id)
    return session.candidates_dir / run_id / expected


def apply_plan(tools, session, plan, approval, *, checkpoint=None) -> dict:
    """Run the plan, publish the candidate, return the CandidateArtifact.

    The first step reads the plan's BASE — a published candidate when the plan
    declared one, the session source otherwise — and every later step chains
    through ``work/``. The source is never an output either way.
    """
    ops = plan.payload["ops"]
    base = plan.payload.get("base") or None
    run_id = uuid.uuid4().hex
    run_dir = session.candidates_dir / run_id
    work_dir = session.work_dir / run_id
    suffix = session.source.suffix or ".bin"

    if base is None:
        origin = session.source
    else:
        # Re-verified here even though plan/propose already read it: an apply
        # may happen long after the proposal, and the check costs one hash.
        origin, _ = candidate_artifact(session, str(base["runId"]))

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
    current = origin
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
            # THE LINEAGE. `null` is the root of the chain — this candidate was
            # built from the session source — and anything else names the exact
            # candidate its ops were chained onto.
            "base": dict(base) if base else None,
            # Which candidate this one undoes, when the plan declared one. Never
            # inferred from the ops: a client says what it is reversing and the
            # runtime records the claim beside the bytes that back it.
            "reverses": (dict(plan.payload["reverses"])
                         if plan.payload.get("reverses") else None),
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
        "base": receipt["base"],
        "reverses": receipt["reverses"],
        "checks": checks,
        "receipt": f"{run_id}/{RECEIPT_NAME}",
        "canonical": True,
    }


def list_candidates(session) -> list[dict]:
    """Only runs whose receipt landed. A bare artifact is not a candidate.

    Each row carries the lineage fields — ``base``, ``reverses``, the candidate
    digest and the creation stamp — read out of the receipt on disk, so a
    history view is one call rather than one call per candidate. This read does
    NOT re-hash the artifact: that is ``receipt/read``'s job and its refusal
    (``candidate_hash_mismatch``) is the one that matters, so ``verified:
    false`` is stated on every row rather than implied. Ordered by
    ``createdUtc``, with the run id breaking ties, because a directory listing
    is alphabetical by a random hex id and that is not history.
    """
    rows = []
    if not session.candidates_dir.is_dir():
        return rows
    for run_dir in sorted(session.candidates_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        receipt_path = run_dir / RECEIPT_NAME
        if not receipt_path.is_file():
            continue
        row = {"runId": run_dir.name,
               "receipt": f"{run_dir.name}/{RECEIPT_NAME}",
               "verified": False}
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            candidate = payload.get("candidate") or {}
            row.update({
                "sha256": candidate.get("sha256"),
                "bytes": candidate.get("bytes"),
                "createdUtc": payload.get("createdUtc"),
                "planId": payload.get("planId"),
                "base": payload.get("base"),
                "reverses": payload.get("reverses"),
                "acceptance": (payload.get("checks") or {}).get("acceptance"),
                "opKinds": [step.get("kind") for step in payload.get("steps") or []],
            })
        rows.append(row)
    rows.sort(key=lambda row: (str(row.get("createdUtc") or ""), row["runId"]))
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
    candidate = payload.get("candidate")
    artifact = _candidate_path(session, run_id, candidate)
    if not artifact.is_file():
        raise RpcError("artifact_missing", "the bound candidate is gone",
                       runId=run_id, path=artifact.name)
    actual_sha, actual_bytes = sha256_file(artifact)
    if actual_sha != candidate.get("sha256") or actual_bytes != candidate.get("bytes"):
        raise RpcError("candidate_hash_mismatch",
                       "the candidate bytes changed after the receipt was written",
                       runId=run_id, declared=candidate.get("sha256"),
                       actual=actual_sha)
    return payload
