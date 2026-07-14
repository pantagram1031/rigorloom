#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed Stage 5.7 final-panel scorecard checker.

Exit 0 = pass, 3 = HARD finding, 2 = usage error. Output is a findings JSON
object compatible with verify_content.py's hard/warn/counts/verdict shape.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


STOP_LINES = {
    "SENSITIVE_FRAMING",
    "LOAD_BEARING_DISPUTE",
    "UNSUPPORTED_NOVELTY",
}
OVERALL_DECISION_FIELDS = ("overall_decision", "decision", "verdict")
BLOCKING_VERDICTS = {
    "block", "blocked", "blocking", "fail", "failed", "reject", "rejected",
    "rework",
}
ACCEPTING_DECISIONS = {"accept", "pass", "approved"}


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _walk(value, path="$"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _nonempty(value) -> bool:
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return value is True


def check(workspace: str | Path) -> tuple[dict, int]:
    ws = Path(workspace)
    files = sorted((ws / "output").glob("scorecard*.json"))
    hard: list[dict] = []
    warn: list[dict] = []
    checked: list[str] = []

    if not files:
        hard.append({
            "code": "S0",
            "msg": "no output/scorecard*.json found (final panel fails closed)",
            "at": "output/scorecard*.json",
        })

    for path in files:
        rel = path.relative_to(ws).as_posix()
        checked.append(rel)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            hard.append({"code": "S0", "msg": f"scorecard malformed: {exc}", "at": rel})
            continue
        if not isinstance(payload, dict):
            hard.append({"code": "S0", "msg": "scorecard root must be a JSON object", "at": rel})
            continue

        stop_lines = payload.get("stop_lines")
        if not isinstance(stop_lines, dict):
            hard.append({
                "code": "S0",
                "msg": "scorecard stop_lines must be a JSON object",
                "at": f"{rel}:$.stop_lines",
            })
        else:
            missing_stop_lines = sorted(STOP_LINES - set(stop_lines))
            if missing_stop_lines:
                hard.append({
                    "code": "S0",
                    "msg": "scorecard schema is missing explicit final-panel stop-line fields",
                    "at": f"{rel}:$.stop_lines missing={missing_stop_lines}",
                })
            for key in sorted(STOP_LINES & set(stop_lines)):
                value = stop_lines[key]
                if not isinstance(value, bool):
                    hard.append({
                        "code": "S0",
                        "msg": f"stop-line field must be boolean: {key}",
                        "at": f"{rel}:$.stop_lines.{key}",
                    })
                elif value:
                    hard.append({
                        "code": "S1",
                        "msg": f"final-panel stop line is true: {key}",
                        "at": f"{rel}:$.stop_lines.{key}",
                    })

        decision_fields = [
            key for key in OVERALL_DECISION_FIELDS if key in payload
        ]
        if not decision_fields:
            hard.append({
                "code": "S0",
                "msg": "scorecard requires an explicit non-empty overall decision",
                "at": f"{rel}:$ expected one of {list(OVERALL_DECISION_FIELDS)}",
            })
        for decision_field in decision_fields:
            decision = payload.get(decision_field)
            if not isinstance(decision, str) or not decision.strip():
                hard.append({
                    "code": "S0",
                    "msg": "scorecard requires an explicit non-empty overall decision",
                    "at": f"{rel}:$.{decision_field}",
                })
            elif decision.strip().lower() not in ACCEPTING_DECISIONS:
                hard.append({
                    "code": "S3",
                    "msg": "scorecard overall decision is not an explicit accept value",
                    "at": f"{rel}:$.{decision_field} ({decision})",
                })

        panelists = payload.get("panelists")
        if not isinstance(panelists, list) or not panelists:
            hard.append({
                "code": "S0",
                "msg": "scorecard panelists must be a non-empty array",
                "at": f"{rel}:$.panelists",
            })
            continue

        for index, panelist in enumerate(panelists):
            panel_path = f"$.panelists[{index}]"
            if not isinstance(panelist, dict):
                hard.append({
                    "code": "S0",
                    "msg": "each panelist must be a JSON object",
                    "at": f"{rel}:{panel_path}",
                })
                continue
            panel_verdict = panelist.get("verdict")
            if not isinstance(panel_verdict, str) or not panel_verdict.strip():
                hard.append({
                    "code": "S0",
                    "msg": "each panelist requires a non-empty verdict",
                    "at": f"{rel}:{panel_path}.verdict",
                })
            elif panel_verdict.strip().lower() in BLOCKING_VERDICTS:
                hard.append({
                    "code": "S2",
                    "msg": "panelist verdict is blocking",
                    "at": f"{rel}:{panel_path}.verdict ({panel_verdict})",
                })

            for obj_path, obj in _walk(panelist, panel_path):
                blocking = obj.get("blocking") is True
                blocking = blocking or _nonempty(obj.get("blocking_findings"))
                finding_state = str(
                    obj.get("severity", obj.get("status", ""))).lower()
                blocking = blocking or (
                    "findings" in obj_path
                    and finding_state in {"block", "blocking"}
                )
                if blocking:
                    message = (
                        obj.get("message") or obj.get("msg") or obj.get("finding"))
                    hard.append({
                        "code": "S2",
                        "msg": "panelist reported a blocking finding",
                        "at": (
                            f"{rel}:{obj_path}"
                            + (f" ({message})" if message else "")
                        ),
                    })

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "scorecards": checked,
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="fail-closed final panel scorecard checker")
    parser.add_argument("workspace")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace)
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
