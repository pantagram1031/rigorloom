#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed Stage 5.7 final-panel scorecard checker.

Exit 0 = pass, 3 = HARD finding, 2 = usage error. Output is a findings JSON
object compatible with verify_content.py's hard/warn/counts/verdict shape.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
VISUAL_RUBRIC_KEYS = {
    "mid_bottom_void",
    "density_uniformity",
    "table_proportion",
    "heading_plus_void",
}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


def _contact_sheet_entries(contexts):
    """Collect declared contact-sheet path/hash pairs from rubric contexts."""
    entries = []
    found = False
    seen_sources = set()
    for context in contexts:
        if not isinstance(context, dict):
            continue
        sources = [context]
        if isinstance(context.get("provenance"), dict):
            sources.append(context["provenance"])
        for source in sources:
            if id(source) in seen_sources:
                continue
            seen_sources.add(id(source))

            if "contact_sheet_path" in source:
                found = True
                entries.append({
                    "path": source.get("contact_sheet_path"),
                    "sha256": (
                        source.get("sha256")
                        or source.get("contact_sheet_sha256")
                        or source.get("contact_sheet_hash")
                    ),
                })
            for key in (
                "contact_sheet_sha256",
                "contact_sheet_hash",
                "contact_sheet_hashes",
            ):
                if key not in source:
                    continue
                found = True
                value = source[key]
                values = value if isinstance(value, list) else [value]
                if "contact_sheet_path" not in source:
                    entries.extend({"path": None, "sha256": item} for item in values)
            contact_sheet = source.get("contact_sheet")
            if isinstance(contact_sheet, dict):
                found = True
                entries.append({
                    "path": contact_sheet.get("contact_sheet_path"),
                    "sha256": contact_sheet.get("sha256"),
                })
            contact_sheets = source.get("contact_sheets")
            if isinstance(contact_sheets, list):
                found = True
                for item in contact_sheets:
                    entries.append({
                        "path": item.get("contact_sheet_path") if isinstance(item, dict) else None,
                        "sha256": item.get("sha256") if isinstance(item, dict) else item,
                    })
    unique = []
    seen_entries = set()
    for entry in entries:
        marker = (entry.get("path"), entry.get("sha256"))
        if marker not in seen_entries:
            seen_entries.add(marker)
            unique.append(entry)
    return found, unique


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contact_sheet_hash_errors(workspace: Path, contexts) -> tuple[bool, list[str]]:
    found, entries = _contact_sheet_entries(contexts)
    if not found:
        return False, []
    if not entries:
        return True, ["contact-sheet attestation is empty"]

    root = workspace.resolve()
    errors = []
    for entry in entries:
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not relative.strip():
            errors.append("contact-sheet sha256 has no contact_sheet_path")
            continue
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            errors.append(f"contact-sheet sha256 is invalid: {relative}")
            continue
        declared = Path(relative)
        if declared.is_absolute():
            errors.append(f"contact_sheet_path must be workspace-relative: {relative}")
            continue
        candidate = (root / declared).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"contact_sheet_path escapes workspace: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"contact sheet missing: {relative}")
            continue
        try:
            actual = _sha256_file(candidate)
        except OSError as exc:
            errors.append(f"contact sheet unreadable: {relative}: {exc}")
            continue
        if actual.casefold() != expected.casefold():
            errors.append(f"contact sheet sha256 mismatch: {relative}")
    return True, errors


def _has_judge_identity(contexts) -> bool:
    for context in contexts:
        if not isinstance(context, dict):
            continue
        sources = [context]
        if isinstance(context.get("provenance"), dict):
            sources.append(context["provenance"])
        for source in sources:
            for key in ("judge_id", "judge_identity"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return True
            judge = source.get("judge")
            if isinstance(judge, str) and judge.strip():
                return True
            if isinstance(judge, dict):
                for key in ("id", "judge_id", "identity", "name"):
                    value = judge.get(key)
                    if isinstance(value, str) and value.strip():
                        return True
    return False


def _visual_rubric_sections(payload):
    """Yield visual claim mappings plus contexts that may attest them."""
    sections = []
    seen = set()

    def add(path, section, parent):
        if not isinstance(section, dict):
            return
        rubric = section
        for key in ("rubric", "claims"):
            candidate = section.get(key)
            if (isinstance(candidate, dict)
                    and VISUAL_RUBRIC_KEYS & set(candidate)):
                rubric = candidate
                break
        if not VISUAL_RUBRIC_KEYS & set(rubric) or id(rubric) in seen:
            return
        seen.add(id(rubric))
        sections.append((path, rubric, [rubric, section, parent]))

    for obj_path, obj in _walk(payload):
        for key in ("visual_rubric", "visual-rubric"):
            if key in obj:
                add(f"{obj_path}.{key}", obj.get(key), obj)
        visual = obj.get("visual")
        if isinstance(visual, dict):
            add(f"{obj_path}.visual", visual, obj)
        identity = " ".join(
            str(obj.get(key, "")) for key in ("name", "role", "type")
        ).lower()
        if "vision" in identity:
            add(f"{obj_path}.rubric", obj.get("rubric"), obj)
    return sections


def _visual_attestation_findings(payload, rel, workspace):
    findings = []
    for section_path, rubric, contexts in _visual_rubric_sections(payload):
        for key in sorted(VISUAL_RUBRIC_KEYS & set(rubric)):
            claim = rubric[key]
            asserted = claim is True or (
                isinstance(claim, dict)
                and any(claim.get(field) is True
                        for field in ("value", "pass", "passed"))
            )
            if not asserted:
                continue
            claim_contexts = ([claim] if isinstance(claim, dict) else []) + contexts
            found_hashes, hash_errors = _contact_sheet_hash_errors(
                workspace, claim_contexts
            )
            if found_hashes and hash_errors:
                findings.append({
                    "code": "visual_hash_mismatch",
                    "msg": "; ".join(hash_errors),
                    "at": f"{rel}:{section_path}.{key}",
                })
                continue
            if found_hashes and _has_judge_identity(claim_contexts):
                continue
            findings.append({
                "code": "visual_rubric_unattested",
                "msg": (
                    "true visual rubric claim requires a rehashable contact-sheet "
                    f"path/hash pair and judge identity: {key}"
                ),
                "at": f"{rel}:{section_path}.{key}",
            })
    return findings


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

        hard.extend(_visual_attestation_findings(payload, rel, ws))

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
