#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score.py — scorecards and the cross-tier comparison table (v0.17 item 4).

One clean-room run produces two artifacts: the machine-check results
(``cleanroom.py check`` -> ``checks.json``) and a **run record** written by
whoever launched the agent (``evals/run_record.schema.json``). This tool joins
them into a per-run scorecard, and folds several scorecards into the
pass/retries/steps/tokens/failure-mode table that
``docs/research/model-routing.md`` will be built from.

Usage
-----

    python evals/score.py score --run run.json --checks checks.json \
        --task evals/tasks/A1-pps-recognize-fill.yaml --out scorecard.json

    python evals/score.py compare opus.json sonnet.json haiku.json
    python evals/score.py --compare a.json b.json        # same thing

``compare`` accepts scorecards or raw run records (a run record without checks
scores as machine-unknown, and says so rather than assuming a pass).

Exit codes: 0 ok, 2 usage/validation refusal, 3 the scored run FAILED (so a
CI step can gate on ``score``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent
RUN_SCHEMA = "rigorloom-eval-run/v1"
CHECKS_SCHEMA = "rigorloom-eval-checks/v1"
SCORECARD_SCHEMA = "rigorloom-eval-scorecard/v1"
_LAUNCHER_KINDS = {"task-tool", "cli", "sdk", "operator", "other"}
_VERDICTS = {"pass", "fail", "unclear"}


class ScoreError(Exception):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate_run_record(record: Any, source: str = "<run>") -> dict:
    """Stdlib validation of the run-record contract. Every miss is loud."""

    def fail(message: str) -> None:
        raise ScoreError(f"{source}: {message}")

    if not isinstance(record, dict):
        fail("run record must be a JSON object")
    if record.get("schema") != RUN_SCHEMA:
        fail(f"schema must be {RUN_SCHEMA!r} (got {record.get('schema')!r})")
    for field in ("run_id", "task_id"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            fail(f"{field} is required and must be a non-empty string")

    tier = record.get("tier")
    if not isinstance(tier, dict) or not isinstance(tier.get("label"), str):
        fail("tier.label is required (the comparison table's column header)")

    launcher = record.get("launcher")
    if not isinstance(launcher, dict):
        fail("launcher is required — a run must say HOW the agent was started")
    if launcher.get("kind") not in _LAUNCHER_KINDS:
        fail(f"launcher.kind must be one of {sorted(_LAUNCHER_KINDS)} "
             f"(got {launcher.get('kind')!r})")

    outcome = record.get("outcome")
    if not isinstance(outcome, dict) or not isinstance(
            outcome.get("completed"), bool):
        fail("outcome.completed (bool) is required")

    transcript = record.get("transcript")
    if not isinstance(transcript, dict):
        fail("transcript is required")
    if not isinstance(transcript.get("steps"), int) or transcript["steps"] < 0:
        fail("transcript.steps must be a non-negative integer")
    tokens = transcript.get("tokens")
    if tokens is not None and not isinstance(tokens, dict):
        fail("transcript.tokens must be an object or null")

    for entry in record.get("judgment") or []:
        if not isinstance(entry, dict) or entry.get("verdict") not in _VERDICTS:
            fail(f"judgment entries need a verdict in {sorted(_VERDICTS)}")
    return record


def _load_json(path: Path | str) -> Any:
    path = Path(path)
    if not path.is_file():
        raise ScoreError(f"file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScoreError(f"{path.name}: not valid JSON: {exc}")


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score_run(record: dict, checks: dict | None = None,
              task: dict | None = None) -> dict:
    """Join a run record with its machine-check results into a scorecard."""
    validate_run_record(record)
    if checks is not None:
        if checks.get("schema") != CHECKS_SCHEMA:
            raise ScoreError(
                f"checks file schema must be {CHECKS_SCHEMA!r} "
                f"(got {checks.get('schema')!r})")
        if checks.get("task_id") != record["task_id"]:
            raise ScoreError(
                f"checks are for task {checks.get('task_id')!r} but the run "
                f"record is for {record['task_id']!r}")

    counts = (checks or {}).get("counts") or {}
    machine = {
        "known": checks is not None,
        "pass": counts.get("pass", 0),
        "fail": counts.get("fail", 0),
        "skipped": counts.get("skipped", 0),
        "total": counts.get("total", 0),
        "failed_ids": [row["id"] for row in (checks or {}).get("checks", [])
                       if row.get("status") == "fail"],
        "skipped_ids": [row["id"] for row in (checks or {}).get("checks", [])
                        if row.get("status") == "skipped"],
    }

    verdicts = [entry["verdict"] for entry in record.get("judgment") or []]
    rubric_total = len(task["expected_behavior"]) if task else None
    judgment = {
        "scored": len(verdicts),
        "rubric_total": rubric_total,
        "pass": verdicts.count("pass"),
        "fail": verdicts.count("fail"),
        "unclear": verdicts.count("unclear"),
        "complete": rubric_total is None or len(verdicts) == rubric_total,
    }

    outcome = record["outcome"]
    blockers: list[str] = []
    if not outcome.get("completed"):
        blockers.append("agent did not complete the task")
    if outcome.get("operator_intervened"):
        blockers.append("operator intervened — not a clean-room result")
    if checks is None:
        blockers.append("machine checks were never run")
    elif machine["fail"]:
        blockers.append(f"{machine['fail']} machine check(s) failed")
    if judgment["fail"]:
        blockers.append(f"{judgment['fail']} rubric line(s) judged fail")

    transcript = record["transcript"]
    tokens = transcript.get("tokens") or {}
    return {
        "schema": SCORECARD_SCHEMA,
        "run_id": record["run_id"],
        "task_id": record["task_id"],
        "family": (task or {}).get("family") or (checks or {}).get("family"),
        "tier": record["tier"],
        "launcher": record["launcher"],
        "passed": not blockers,
        "blockers": blockers,
        "machine": machine,
        "judgment": judgment,
        "efficiency": {
            "steps": transcript.get("steps"),
            "tool_calls": transcript.get("tool_calls"),
            "retries": transcript.get("retries"),
            "wall_seconds": transcript.get("wall_seconds"),
            "tokens_total": tokens.get("total"),
            "tokens_input": tokens.get("input"),
            "tokens_output": tokens.get("output"),
            "tokens_skill_loaded": tokens.get("skill_loaded"),
        },
        "failure_mode": record.get("failure_mode"),
        "artifacts": record.get("artifacts") or [],
        "notes": record.get("notes"),
    }


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def _as_scorecard(document: Any, source: str) -> dict:
    if isinstance(document, dict) and document.get("schema") == SCORECARD_SCHEMA:
        return document
    if isinstance(document, dict) and document.get("schema") == RUN_SCHEMA:
        return score_run(document)
    raise ScoreError(
        f"{source}: expected a scorecard ({SCORECARD_SCHEMA}) or a run record "
        f"({RUN_SCHEMA}), got schema {document.get('schema')!r}"
        if isinstance(document, dict) else f"{source}: not a JSON object")


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    return str(value)


def compare(scorecards: list[dict]) -> dict:
    """Cross-tier comparison: one row per scorecard, grouped by task."""
    rows = []
    for card in scorecards:
        machine = card["machine"]
        rows.append({
            "task_id": card["task_id"],
            "tier": card["tier"].get("label"),
            "run_id": card["run_id"],
            "skill_loaded": card["launcher"].get("skill_loaded"),
            "passed": card["passed"],
            "machine": (f"{machine['pass']}/{machine['total']}"
                        if machine["known"] else "unknown"),
            "machine_skipped": machine["skipped"],
            "judgment": (f"{card['judgment']['pass']}/"
                         f"{card['judgment']['scored']}"
                         if card["judgment"]["scored"] else "—"),
            "retries": card["efficiency"]["retries"],
            "steps": card["efficiency"]["steps"],
            "tool_calls": card["efficiency"]["tool_calls"],
            "tokens": card["efficiency"]["tokens_total"],
            "failure_mode": card["failure_mode"],
        })
    rows.sort(key=lambda row: (row["task_id"], str(row["tier"])))

    tasks = sorted({row["task_id"] for row in rows})
    tiers = sorted({str(row["tier"]) for row in rows})
    by_tier = {}
    for tier in tiers:
        tier_rows = [row for row in rows if str(row["tier"]) == tier]
        scored = [row for row in tier_rows if row["tokens"] is not None]
        by_tier[tier] = {
            "runs": len(tier_rows),
            "passed": sum(1 for row in tier_rows if row["passed"]),
            "tokens_total": sum(row["tokens"] for row in scored) or None
            if scored else None,
            "steps_total": sum(row["steps"] for row in tier_rows
                               if row["steps"] is not None) or None,
        }
    return {"schema": "rigorloom-eval-comparison/v1",
            "tasks": tasks, "tiers": tiers, "rows": rows, "by_tier": by_tier}


_COLUMNS = (
    ("task_id", "task"), ("tier", "tier"), ("passed", "result"),
    ("machine", "machine"), ("judgment", "judgment"), ("retries", "retries"),
    ("steps", "steps"), ("tool_calls", "tools"), ("tokens", "tokens"),
    ("failure_mode", "failure mode"),
)


def comparison_markdown(comparison: dict) -> str:
    header = "| " + " | ".join(label for _key, label in _COLUMNS) + " |"
    divider = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    lines = [header, divider]
    for row in comparison["rows"]:
        lines.append("| " + " | ".join(_cell(row[key]) for key, _ in _COLUMNS)
                     + " |")
    lines.append("")
    lines.append("| tier | runs | passed | steps (sum) | tokens (sum) |")
    lines.append("|---|---|---|---|---|")
    for tier, summary in comparison["by_tier"].items():
        lines.append(
            f"| {tier} | {summary['runs']} | {summary['passed']} | "
            f"{_cell(summary['steps_total'])} | "
            f"{_cell(summary['tokens_total'])} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_task(path: str | None) -> dict | None:
    if not path:
        return None
    sys.path.insert(0, str(HARNESS_ROOT))
    import cleanroom  # noqa: E402  (harness-local import, never from a sandbox)
    return cleanroom.load_task(path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Documented alias: `score.py --compare a.json b.json` == `compare a b`.
    if argv and argv[0] == "--compare":
        argv = ["compare", *argv[1:]]

    parser = argparse.ArgumentParser(
        description="Score clean-room eval runs and build the cross-tier "
                    "routing comparison table.")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("score", help="join a run record with its checks")
    one.add_argument("--run", required=True, metavar="RUN_JSON")
    one.add_argument("--checks", default=None, metavar="CHECKS_JSON")
    one.add_argument("--task", default=None, metavar="TASK_YAML")
    one.add_argument("--out", default=None)

    cmp_ = sub.add_parser("compare", help="cross-tier comparison table")
    cmp_.add_argument("files", nargs="+", metavar="SCORECARD_OR_RUN")
    cmp_.add_argument("--format", choices=("md", "json"), default="md")
    cmp_.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    try:
        if args.command == "score":
            record = _load_json(args.run)
            checks = _load_json(args.checks) if args.checks else None
            card = score_run(record, checks, _load_task(args.task))
            payload = json.dumps(card, ensure_ascii=False, indent=2) + "\n"
            if args.out:
                Path(args.out).write_text(payload, encoding="utf-8")
            print(payload, end="")
            return 0 if card["passed"] else 3
        if args.command == "compare":
            cards = [_as_scorecard(_load_json(path), Path(path).name)
                     for path in args.files]
            comparison = compare(cards)
            if args.format == "json":
                payload = json.dumps(comparison, ensure_ascii=False,
                                     indent=2) + "\n"
            else:
                payload = comparison_markdown(comparison)
            if args.out:
                Path(args.out).write_text(payload, encoding="utf-8")
            print(payload, end="")
            return 0
    except ScoreError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return exc.exit_code
    return 2  # pragma: no cover


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
