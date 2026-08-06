#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detect report workspaces that were completed outside pipeline_ctl.

Exit 0 = clean (WARN findings are advisory), 3 = HARD finding, 2 = usage
error. The checker is stdlib-only and reads workspace state without mutating it.

HONESTY SCOPE — this lint is tamper-EVIDENCE, not tamper-PROOF. It raises the
cost and visibility of forging a passing state (a fabricated free-form receipt
no longer satisfies H1; deleting the event ledger no longer downgrades to a
WARN; a graph-switch shows up as a stage-set mismatch), but a determined
attacker with write access to the workspace can still craft internally
consistent forgeries. Full cryptographic attestation of gate provenance
(signed receipts chained to the checker binary) is DEFERRED BY DESIGN and out
of scope for this checker.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pipeline_ctl


EVENT_TYPES = {"advance", "gate", "check", "gate_check"}
TEN_MINUTES = 10 * 60
DAY = 24 * 60 * 60


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _epoch(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _jsonl(path: Path) -> list[dict]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _argv_matches(receipt_argv, expected_argv) -> bool:
    """True when a receipt's recorded checker argv matches the graph's
    registered checker argv (after placeholder substitution).

    The interpreter token is compared leniently: pipeline_ctl.cmd_check rebinds a
    leading "python"/"python3" to the concrete sys.executable at spawn time, so a
    receipt's argv[0] is a resolved interpreter path while the registered
    template still says "python". Everything AFTER the interpreter (the script
    path and its arguments) must match EXACTLY — that tail is the part an
    attacker would have to forge, and it is what H1 pins down."""
    if not isinstance(receipt_argv, list) or not receipt_argv:
        return False
    if len(receipt_argv) != len(expected_argv):
        return False
    if receipt_argv[1:] != expected_argv[1:]:
        return False
    r0, e0 = receipt_argv[0], expected_argv[0]
    if r0 == e0:
        return True
    if e0 in ("python", "python3"):
        return (r0 == sys.executable
                or Path(str(r0)).name.lower().startswith("python"))
    return False


def _receipt_satisfies_h1(record: dict, expected_argv: list) -> bool:
    """A gate_checks.jsonl receipt satisfies H1 only if it carries the graph's
    registered checker argv AND a well-formed (64-hex) stdout_sha256. A
    fabricated free-form receipt (wrong/absent argv, or empty/absent hash) does
    NOT satisfy H1."""
    sha = record.get("stdout_sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        return False
    return _argv_matches(record.get("checker_argv"), expected_argv)


def check(workspace: str | Path, now: datetime | None = None) -> tuple[dict, int]:
    ws = Path(workspace)
    loaded = pipeline_ctl.load_header(ws)
    if loaded is None:
        return {"ok": False, "error": "PIPELINE.md missing or invalid"}, 2
    hdr = loaded[3]
    try:
        graph_ctx = pipeline_ctl.graph_context_for_header(hdr)
    except pipeline_ctl.StagesConfigError as exc:
        return {"ok": False, "error": f"stage graph invalid: {exc}"}, 2

    hard: list[dict] = []
    warn: list[dict] = []
    stages = hdr.get("stages", {})
    rows_by_id = {str(row["id"]): row for row in graph_ctx["rows"]}

    # HARD (H4): the header must not carry a stage id the SELECTED graph does
    # not define — the graph-switch attack surface. A header claiming graph=edit
    # while carrying build-only ids (4.5/5.5/5.7/6), or claiming graph=build
    # while carrying edit-only ids (3.5), is flagged: each graph owns at least
    # one id the other lacks, so a build<->edit switch always surfaces here.
    # Legacy v0.5 headers are a strict SUBSET of the build graph (missing
    # 2.5/5.7), carry no foreign ids, and are deliberately tolerated.
    header_ids = {str(k) for k in stages}
    graph_ids = set(rows_by_id)
    foreign_ids = header_ids - graph_ids
    if foreign_ids:
        hard.append({
            "code": "H4",
            "msg": ("header stage-id set does not match the selected graph "
                    f"'{graph_ctx['name']}' (foreign stage ids: "
                    f"{sorted(foreign_ids)})"),
            "at": "PIPELINE.md stages",
        })

    receipts = _jsonl(ws / ".pipeline" / "gate_checks.jsonl")

    def _substituted_checker(gate_cfg: dict):
        checker = gate_cfg.get("checker")
        if not checker:
            return None
        # Substitute {WS}/{PIPELINE_SCRIPTS} but leave the "python" interpreter
        # token as-is; _argv_matches reconciles it against the concrete
        # sys.executable that cmd_check rebinds into a genuine receipt.
        return pipeline_ctl._substitute_checker_argv(checker, ws)

    # HARD (H1): a completed stage whose OWN header row carries the graph's
    # script gate must have a receipt that MATCHES the registered checker argv
    # AND carries a non-empty stdout_sha256. Legacy rows with gate:null do not
    # inherit gates added by a newer graph.
    # A receipt merely tagged with the right (stage, gate) no longer counts —
    # the argv + hash are what a forgery would have to reproduce.
    for stage_id, state in stages.items():
        header_gate = state.get("gate")
        row = rows_by_id.get(str(stage_id), {})
        gate_cfg = row.get("gate") or {}
        if (
            state.get("status") != "done"
            or not isinstance(header_gate, dict)
            or gate_cfg.get("type") != "script"
            or header_gate.get("name") != gate_cfg.get("name")
        ):
            continue
        gate_name = str(gate_cfg.get("name"))
        expected_argv = _substituted_checker(gate_cfg)
        matching = [
            record for record in receipts
            if str(record.get("stage")) == str(stage_id)
            and str(record.get("gate")) == gate_name
        ]
        if expected_argv is None:
            # No checker bound in the graph (e.g. external checker registered
            # null) — fall back to presence-only provenance: any receipt for
            # this (stage, gate) with a valid stdout_sha256 counts.
            ok = any(
                isinstance(r.get("stdout_sha256"), str)
                and _SHA256_RE.match(r.get("stdout_sha256"))
                for r in matching
            )
        else:
            ok = any(_receipt_satisfies_h1(r, expected_argv) for r in matching)
        if not ok:
            hard.append({
                "code": "H1",
                "msg": ("done script-gated stage has no gate check receipt "
                        "matching the registered checker argv + stdout hash"),
                "at": f"stage {stage_id} gate {gate_name}",
            })

    # HARD: delivery cannot coexist with an unresolved or rejected gate.
    canonical = hdr.get("canonical_output")
    canonical_set = canonical not in (None, "", "null", "~")
    if canonical_set:
        for stage_id, state in stages.items():
            gate = state.get("gate")
            if gate and gate.get("state") in {"pending", "rejected"}:
                hard.append({
                    "code": "H2",
                    "msg": "canonical_output is set while a gate is unresolved",
                    "at": f"stage {stage_id} gate {gate.get('name')}={gate.get('state')}",
                })

    # HARD (H5): the event ledger cannot be missing once the run has moved. If
    # ANY stage is past 'pending' but events.jsonl is absent, the ledger was
    # never written or was deleted to erase the trail — a HARD finding, not a
    # WARN. (Deleting the ledger previously only downgraded the freshness check
    # to a WARN, which let a tamperer hide by removing evidence.)
    events_path = ws / "events.jsonl"
    progressed = any(
        state.get("status") != "pending" for state in stages.values()
    )
    if progressed and not events_path.exists():
        hard.append({
            "code": "H5",
            "msg": "events.jsonl missing while stages show progress (ledger absent/deleted)",
            "at": "events.jsonl",
        })

    # HARD: output writes must be close to a state-machine event.
    output_files = [path for path in (ws / "output").rglob("*") if path.is_file()] \
        if (ws / "output").is_dir() else []

    if output_files and not events_path.exists():
        warn.append({
            "code": "W1",
            "msg": "events.jsonl missing; output delivery time cannot be reconciled",
            "at": "events.jsonl",
        })
    elif output_files:
        event_times = [
            _epoch(record.get("ts"))
            for record in _jsonl(events_path)
            if record.get("type") in EVENT_TYPES
        ]
        event_times = [value for value in event_times if value is not None]
        if not event_times:
            warn.append({
                "code": "W1",
                "msg": "no timestamped advance/gate/check event; output delivery time cannot be reconciled",
                "at": "events.jsonl",
            })
        else:
            last_event = max(event_times)
            for path in output_files:
                if path.stat().st_mtime > last_event + TEN_MINUTES:
                    hard.append({
                        "code": "H3",
                        "msg": "output file is more than 10 minutes newer than the last workflow event",
                        "at": str(path.relative_to(ws)),
                    })

    # WARN: supervised workspaces cannot honestly claim automatic human review.
    if hdr.get("mode") == "supervised":
        for stage_id, state in stages.items():
            row = rows_by_id.get(str(stage_id), {})
            gate_cfg = row.get("gate") or {}
            gate = state.get("gate") or {}
            if gate_cfg.get("type") == "human" and gate.get("state") == "auto_approved":
                warn.append({
                    "code": "W2",
                    "msg": "human gate is auto_approved in supervised mode",
                    "at": f"stage {stage_id} gate {gate.get('name')}",
                })

    # WARN (W4): autonomous/night understanding checks may validly pass with
    # answers_pending=true, but delivery must surface that fact. Prefer the
    # newest provenance whether it came from a future gate receipt or today's
    # explicit .pipeline/understanding_check.json sidecar.
    understanding_records = []
    for record in receipts:
        if record.get("gate") != "understand":
            continue
        pending = record.get("answers_pending")
        if pending is None and isinstance(record.get("provenance"), dict):
            pending = record["provenance"].get("answers_pending")
        if isinstance(pending, bool):
            understanding_records.append((
                _epoch(record.get("checked_at") or record.get("ts")) or 0,
                pending,
                ".pipeline/gate_checks.jsonl",
            ))
    understanding_path = ws / ".pipeline" / "understanding_check.json"
    try:
        understanding = json.loads(understanding_path.read_text(encoding="utf-8"))
        if isinstance(understanding, dict) and isinstance(understanding.get("answers_pending"), bool):
            understanding_records.append((
                _epoch(understanding.get("checked_at")) or understanding_path.stat().st_mtime,
                understanding["answers_pending"],
                ".pipeline/understanding_check.json",
            ))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if canonical_set and understanding_records:
        _, pending, source = max(understanding_records, key=lambda item: item[0])
        if pending:
            warn.append({
                "code": "W4",
                "msg": "canonical_output is set while understanding answers are pending",
                "at": source,
            })

    heartbeat = ws / "heartbeat"
    if heartbeat.exists():
        try:
            heartbeat_at = _epoch(heartbeat.read_text(encoding="utf-8"))
        except OSError:
            heartbeat_at = None
        if heartbeat_at is None:
            heartbeat_at = heartbeat.stat().st_mtime
        now_at = (now or datetime.now().astimezone()).timestamp()
        if now_at - heartbeat_at > DAY:
            warn.append({
                "code": "W3",
                "msg": "heartbeat is older than 24 hours",
                "at": "heartbeat",
            })

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def _print_human(verdict: dict) -> None:
    print(f"workflow_lint: {verdict['verdict'].upper()} "
          f"({verdict['counts']['hard']} HARD, {verdict['counts']['warn']} WARN)")
    for severity in ("hard", "warn"):
        for finding in verdict[severity]:
            print(f"{severity.upper()} {finding['code']}: {finding['msg']} [{finding.get('at', '')}]")


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="detect off-workflow report changes")
    parser.add_argument("workspace")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace)
    if args.as_json or code == 2:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        _print_human(verdict)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
