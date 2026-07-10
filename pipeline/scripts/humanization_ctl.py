#!/usr/bin/env python3
"""Prepare, apply, validate, and roll back bounded report prose edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from prose_fidelity import audit_text


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
    return [{"paragraph_id": f"p{index:04d}", "sha256": _hash(block), "text": block}
            for index, block in enumerate(_blocks(text), start=1)]


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
        "schema": "report-pipeline/humanization-v1",
        "status": "prepared",
        "original_sha256": _hash(text),
        "paragraphs": _paragraphs(text),
        "instructions": "Edit only listed paragraphs; preserve protected facts and return a changes array.",
    }
    _write_json(paths["report"], payload)
    return payload


def _load_changes(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list):
        raise ValueError("changes file must contain {\"changes\": [...]}")
    return changes


def apply_changes(workspace: Path, changes_path: Path) -> tuple[dict[str, object], int]:
    paths = _paths(workspace)
    if not paths["raw"].is_file() or not paths["content"].is_file():
        raise ValueError("run prepare before apply")
    current = paths["content"].read_text(encoding="utf-8")
    blocks = _blocks(current)
    applied = []
    for change in _load_changes(changes_path):
        paragraph_id = str(change.get("paragraph_id", ""))
        if not paragraph_id.startswith("p") or not paragraph_id[1:].isdigit():
            raise ValueError(f"invalid paragraph_id: {paragraph_id!r}")
        index = int(paragraph_id[1:]) - 1
        if index < 0 or index >= len(blocks):
            raise ValueError(f"paragraph_id out of range: {paragraph_id}")
        before = change.get("before")
        after = change.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ValueError(f"{paragraph_id}: before and after must be strings")
        if blocks[index] != before:
            raise ValueError(f"{paragraph_id}: before text does not match current content")
        blocks[index] = after
        applied.append({"paragraph_id": paragraph_id, "reasons": change.get("reasons", [])})
    candidate = "\n\n".join(blocks) + ("\n" if current.endswith("\n") else "")
    paths["content"].write_text(candidate, encoding="utf-8")
    original = paths["raw"].read_text(encoding="utf-8")
    fidelity = audit_text(original, candidate)
    _write_json(paths["fidelity"], fidelity)
    if not fidelity["pass"]:
        shutil.copyfile(paths["raw"], paths["content"])
        status = "rolled_back"
        code = 1
    else:
        status = "accepted"
        code = 0
    report = {
        "schema": "report-pipeline/humanization-v1",
        "status": status,
        "original_sha256": _hash(original),
        "candidate_sha256": _hash(candidate),
        "final_sha256": _hash(paths["content"].read_text(encoding="utf-8")),
        "applied": applied,
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
    report = {"schema": "report-pipeline/humanization-v1", "status": "rolled_back", "final_sha256": _hash(paths["content"].read_text(encoding="utf-8"))}
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
