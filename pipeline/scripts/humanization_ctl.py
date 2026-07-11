#!/usr/bin/env python3
"""Prepare, apply, validate, and roll back bounded report prose edits."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from prose_fidelity import audit_text, extract_protected


CHANGE_RATE_WARN = {"light": 0.15, "standard": 0.30, "strong": 0.45}
MAX_ROUNDS = 3


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _paths(workspace: Path) -> dict[str, Path]:
    bundle = workspace.resolve() / "bundle"
    return {
        "bundle": bundle,
        "content": bundle / "content.md",
        "raw": bundle / "content.raw.md",
        "report": bundle / "humanization_report.json",
        "fidelity": bundle / "prose_fidelity.json",
        "ai_review": bundle / "ai_tell_review.json",
    }


def _blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    return normalized.rstrip("\n").split("\n\n") if normalized.strip() else []


def _paragraphs(text: str) -> list[dict[str, object]]:
    paragraphs = []
    section = "body"
    for index, block in enumerate(_blocks(text), start=1):
        heading = re.match(r"^#{1,6}\s+(.+)$", block.strip())
        if heading:
            section = _section_name(heading.group(1))
        paragraphs.append({
            "paragraph_id": f"p{index:04d}",
            "sha256": _hash(block),
            "section": section,
            "protected_spans": _protected_spans(block),
            "text": block,
        })
    return paragraphs


def _section_name(heading: str) -> str:
    lowered = heading.lower()
    groups = {
        "motivation": ("동기", "목적", "서론", "introduction", "motivation"),
        "theory": ("이론", "배경", "원리", "theory", "background"),
        "method": ("방법", "과정", "절차", "method", "procedure"),
        "results": ("결과", "분석", "내용", "result", "analysis"),
        "conclusion": ("결론", "느낀", "한계", "conclusion", "limitation"),
    }
    for name, needles in groups.items():
        if any(needle in lowered for needle in needles):
            return name
    return "body"


def _protected_spans(text: str) -> list[dict[str, str]]:
    spans = []
    seen = set()
    for kind, values in extract_protected(text).items():
        if kind == "headings":
            iterable = values
        elif isinstance(values, dict):
            iterable = values.keys()
        elif isinstance(values, list):
            iterable = values
        else:
            continue
        for value in iterable:
            value = str(value)
            key = (kind, value)
            if value and key not in seen:
                seen.add(key)
                spans.append({"type": kind, "text": value})
    return spans


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(workspace: Path, force: bool = False) -> dict[str, object]:
    paths = _paths(workspace)
    if not paths["content"].is_file():
        raise ValueError("bundle/content.md does not exist")
    if paths["raw"].exists() and not force:
        raise ValueError("bundle/content.raw.md already exists; use --force to replace it")
    text = paths["content"].read_text(encoding="utf-8")
    paths["raw"].write_text(text, encoding="utf-8")
    payload = {
        "schema": "report-pipeline/humanization-v2",
        "status": "prepared",
        "original_sha256": _hash(text),
        "paragraphs": _paragraphs(text),
        "policy": {
            "detector_is_advisory": True,
            "inspect_all_prose_paragraphs": True,
            "default_strength": "light",
            "max_rounds": MAX_ROUNDS,
        },
        "instructions": (
            "After a REWORK decision, inspect every prose paragraph rather than selecting "
            "targets from a detector score. Return only changed paragraphs and preserve "
            "every protected span."
        ),
    }
    _write_json(paths["report"], payload)
    return payload


def _load_changes(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("changes file must be a JSON object")
    schema = payload.get("schema")
    allowed = {
        None,
        "report-pipeline/humanization-changes-v1",
        "report-pipeline/humanization-changes-v2",
    }
    if schema not in allowed:
        raise ValueError(f"unsupported changes schema: {schema}")
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list):
        raise ValueError("changes file must contain {\"changes\": [...]}")
    return payload, changes


def _change_rate(before: str, after: str) -> float:
    return round(1.0 - difflib.SequenceMatcher(None, before, after).ratio(), 6)


def _extreme_hedge_warnings(text: str) -> list[dict[str, str]]:
    warnings = []
    measured = re.compile(r"(?:측정|기록|복잡도|결과)[^.\n]{0,60}(?:경향을\s*보였|것으로\s*관찰되)")
    inferred = re.compile(r"(?:이는|따라서)[^.\n]{0,60}(?:항상|반드시|필수적이다)")
    if measured.search(text):
        warnings.append({"kind": "measured_result_softened", "action": "review_only"})
    if inferred.search(text):
        warnings.append({"kind": "inference_overstated", "action": "review_only"})
    return warnings


def _declared_spans_preserved(change: dict[str, object], before: str, after: str) -> list[str]:
    changed = []
    spans = change.get("protected_spans") or []
    if not isinstance(spans, list):
        raise ValueError("protected_spans must be a list")
    for span in spans:
        if not isinstance(span, dict) or not isinstance(span.get("text"), str):
            raise ValueError("each protected span must contain text")
        value = span["text"]
        if before.count(value) != after.count(value):
            changed.append(value)
    return changed


def apply_changes(workspace: Path, changes_path: Path) -> tuple[dict[str, object], int]:
    paths = _paths(workspace)
    if not paths["raw"].is_file() or not paths["content"].is_file():
        raise ValueError("run prepare before apply")
    current = paths["content"].read_text(encoding="utf-8")
    original = paths["raw"].read_text(encoding="utf-8")
    payload, changes = _load_changes(changes_path)
    if (payload.get("schema") == "report-pipeline/humanization-changes-v2"
            and not isinstance(payload.get("gate"), dict)):
        raise ValueError("v2 changes require a gate object")
    gate = payload.get("gate") if isinstance(payload.get("gate"), dict) else {}
    gate_verdict = str(gate.get("verdict") or "REWORK").upper()
    skipped = bool(gate.get("skipped"))
    if gate_verdict not in {"PASS", "REWORK"}:
        raise ValueError(f"unknown gate verdict: {gate_verdict}")
    if gate_verdict == "PASS" and not skipped:
        raise ValueError("PASS gate must set gate.skipped=true")
    strength = str(payload.get("strength") or "light").lower()
    if strength not in CHANGE_RATE_WARN:
        raise ValueError(f"unknown strength: {strength}")
    round_number = int(payload.get("round") or 1)
    if not 1 <= round_number <= MAX_ROUNDS:
        raise ValueError(f"round must be between 1 and {MAX_ROUNDS}")

    if skipped:
        if gate_verdict != "PASS" or changes:
            raise ValueError("gate.skipped requires PASS and an empty changes array")
        fidelity = audit_text(original, current)
        if not fidelity["pass"]:
            shutil.copyfile(paths["raw"], paths["content"])
        _write_json(paths["fidelity"], fidelity)
        final_text = paths["content"].read_text(encoding="utf-8")
        report = {
            "schema": "report-pipeline/humanization-v2",
            "status": "skipped" if fidelity["pass"] else "rolled_back",
            "gate": {"verdict": "PASS", "skipped": True},
            "round": round_number,
            "original_sha256": _hash(original),
            "final_sha256": _hash(final_text),
            "change_rate": 0.0,
            "warnings": _extreme_hedge_warnings(final_text),
            "fidelity_pass": fidelity["pass"],
            "fidelity_report": "bundle/prose_fidelity.json",
        }
        _write_json(paths["report"], report)
        return report, 0 if fidelity["pass"] else 1

    blocks = _blocks(current)
    applied = []
    rejected = []
    seen_paragraphs = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each change must be an object")
        paragraph_id = str(change.get("paragraph_id", ""))
        if not paragraph_id.startswith("p") or not paragraph_id[1:].isdigit():
            raise ValueError(f"invalid paragraph_id: {paragraph_id!r}")
        index = int(paragraph_id[1:]) - 1
        if index < 0 or index >= len(blocks):
            raise ValueError(f"paragraph_id out of range: {paragraph_id}")
        if paragraph_id in seen_paragraphs:
            raise ValueError(f"duplicate paragraph_id: {paragraph_id}")
        seen_paragraphs.add(paragraph_id)
        before = change.get("before")
        after = change.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ValueError(f"{paragraph_id}: before and after must be strings")
        if "\n\n" in after.replace("\r\n", "\n"):
            raise ValueError(f"{paragraph_id}: after text cannot create a new paragraph boundary")
        if blocks[index] != before:
            raise ValueError(f"{paragraph_id}: before text does not match current content")
        if (payload.get("schema") == "report-pipeline/humanization-changes-v2"
                and "reviewer_verdict" not in change):
            raise ValueError(f"{paragraph_id}: v2 change requires an independent reviewer_verdict")
        reviewer_verdict = str(change.get("reviewer_verdict") or "accept").lower()
        if reviewer_verdict not in {"accept", "rewrite", "rollback"}:
            raise ValueError(f"{paragraph_id}: unknown reviewer_verdict: {reviewer_verdict}")
        paragraph_fidelity = audit_text(before, after)
        changed_spans = _declared_spans_preserved(change, before, after)
        if reviewer_verdict in {"rewrite", "rollback"} or not paragraph_fidelity["pass"] or changed_spans:
            rejected.append({
                "paragraph_id": paragraph_id,
                "reason": ("reviewer_" + reviewer_verdict
                           if reviewer_verdict in {"rewrite", "rollback"}
                           else "protected_content_changed"),
                "fidelity_changes": [item["kind"] for item in paragraph_fidelity["changes"]],
                "declared_spans_changed": len(changed_spans),
            })
            continue
        blocks[index] = after
        applied.append({
            "paragraph_id": paragraph_id,
            "section": change.get("section"),
            "reasons": change.get("reasons") or change.get("detected_patterns") or [],
            "reviewer_verdict": reviewer_verdict,
        })
    candidate = "\n\n".join(blocks) + ("\n" if current.endswith("\n") else "")
    paths["content"].write_text(candidate, encoding="utf-8")
    fidelity = audit_text(original, candidate)
    _write_json(paths["fidelity"], fidelity)
    if not fidelity["pass"]:
        shutil.copyfile(paths["raw"], paths["content"])
        status = "rolled_back"
        code = 1
    elif rejected:
        status = "hold_and_report" if round_number >= MAX_ROUNDS else "needs_retry"
        code = 1
    else:
        status = "accepted"
        code = 0
    final_text = paths["content"].read_text(encoding="utf-8")
    change_rate = _change_rate(original, final_text)
    warnings = _extreme_hedge_warnings(final_text)
    if change_rate > CHANGE_RATE_WARN[strength]:
        warnings.append({
            "kind": "change_rate",
            "action": "review_overcorrection",
            "value": change_rate,
            "threshold": CHANGE_RATE_WARN[strength],
        })
    supplied_warnings = payload.get("extreme_hedge_warnings") or []
    if not isinstance(supplied_warnings, list):
        raise ValueError("extreme_hedge_warnings must be a list")
    warnings.extend({"kind": "adapter_warning", "action": "review_only"}
                    for _ in supplied_warnings)
    report = {
        "schema": "report-pipeline/humanization-v2",
        "status": status,
        "gate": {"verdict": gate_verdict, "skipped": False},
        "strength": strength,
        "round": round_number,
        "original_sha256": _hash(original),
        "candidate_sha256": _hash(candidate),
        "final_sha256": _hash(final_text),
        "change_rate": change_rate,
        "change_rate_warning": change_rate > CHANGE_RATE_WARN[strength],
        "applied": applied,
        "rejected": rejected,
        "retry_paragraph_ids": [item["paragraph_id"] for item in rejected],
        "warnings": warnings,
        "fidelity_pass": fidelity["pass"],
        "fidelity_report": "bundle/prose_fidelity.json",
    }
    _write_json(paths["report"], report)
    return report, code


def validate(workspace: Path) -> tuple[dict[str, object], int]:
    paths = _paths(workspace)
    if not paths["raw"].is_file() or not paths["content"].is_file():
        raise ValueError("run prepare before validate")
    result = audit_text(paths["raw"].read_text(encoding="utf-8"), paths["content"].read_text(encoding="utf-8"))
    _write_json(paths["fidelity"], result)
    return result, 0 if result["pass"] else 1


def rollback(workspace: Path) -> dict[str, object]:
    paths = _paths(workspace)
    if not paths["raw"].is_file():
        raise ValueError("bundle/content.raw.md does not exist")
    shutil.copyfile(paths["raw"], paths["content"])
    report = {"schema": "report-pipeline/humanization-v2", "status": "rolled_back", "final_sha256": _hash(paths["content"].read_text(encoding="utf-8"))}
    _write_json(paths["report"], report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "validate", "rollback"):
        item = sub.add_parser(name)
        item.add_argument("workspace", type=Path)
        if name == "prepare":
            item.add_argument("--force", action="store_true")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("workspace", type=Path)
    apply_parser.add_argument("--changes", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result, code = prepare(args.workspace, args.force), 0
        elif args.command == "apply":
            result, code = apply_changes(args.workspace, args.changes)
        elif args.command == "validate":
            result, code = validate(args.workspace)
        else:
            result, code = rollback(args.workspace), 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
