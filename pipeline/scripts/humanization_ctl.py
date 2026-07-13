#!/usr/bin/env python3
"""Prepare, apply, validate, and roll back bounded report prose edits."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from prose_fidelity import audit_text, extract_protected

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import personalization_ctl as pctl  # noqa: E402  (stdlib-only sibling module)

CHECK_STYLE = _SCRIPTS_DIR / "check_style.py"

CHANGE_RATE_WARN = {"light": 0.15, "standard": 0.30, "strong": 0.45}
MAX_ROUNDS = 3

# Canonical humanization worker roles and the backends-pack seat aliases that
# resolve to each one. The pack seat `role` is matched case-insensitively.
_WORKER_ROLE_ALIASES = {
    "reviewer-ai-tell": ("reviewer-ai-tell", "ai-tell", "ai_tell", "reviewer",
                         "critic", "prose-pattern"),
    "humanizer-rewriter": ("humanizer-rewriter", "rewriter", "humanizer"),
    "reviewer-fidelity": ("reviewer-fidelity", "fidelity"),
    "reviewer-naturalness": ("reviewer-naturalness", "naturalness"),
}

_TAG_RE = re.compile(r"\[\[.*?\]\]", re.S)


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


# --- v3 pack-driven voice + deterministic pre-pass -------------------------
def _merged_pack(root: Path, pack_type: str, subject: str | None = None) -> dict[str, object]:
    """Resolve a pack at RUNTIME by precedence (default < global < subject).

    Never writes pack content into the workspace; the caller decides where the
    resolved content lands (private sidecar) and what (hash/pointer) the
    workspace payload carries.
    """
    merged = pctl.pack_default(pack_type)
    glob = pctl.stored_pack(root, pack_type)
    if glob is not None:
        merged = pctl.deep_merge(merged, glob)
    if subject:
        sub = root / "academics" / "subjects" / subject / "packs" / f"{pack_type}.json"
        if sub.exists():
            merged = pctl.deep_merge(merged, json.loads(sub.read_text(encoding="utf-8")))
    return merged if isinstance(merged, dict) else {}


def _voice_directives(prose_pack: dict, structure_pack: dict, doc_type: str | None) -> dict[str, object]:
    banned = []
    for entry in prose_pack.get("banned_patterns", []) if isinstance(prose_pack, dict) else []:
        if isinstance(entry, dict):
            banned.append({"id": entry.get("id", "?"), "regex": entry.get("regex", ""),
                           "severity": entry.get("severity", "warn"),
                           "description": entry.get("description", "")})
    endings = prose_pack.get("endings_policy", {}) if isinstance(prose_pack, dict) else {}
    endings = endings if isinstance(endings, dict) else {}
    style = endings.get("default_style")
    per_doc = endings.get("per_doc_type") if isinstance(endings.get("per_doc_type"), dict) else {}
    if doc_type and doc_type in per_doc:
        style = per_doc[doc_type]
    return {
        "banned_patterns": banned,
        "signature_phrases": prose_pack.get("signature_phrases", []) if isinstance(prose_pack, dict) else [],
        "endings_policy": {"doc_type": doc_type, "style": style, "full": endings},
        "advisory_notes": prose_pack.get("advisory_notes", []) if isinstance(prose_pack, dict) else [],
        "structure": {
            "citation_style": structure_pack.get("citation_style") if isinstance(structure_pack, dict) else None,
            "preferred_sections": structure_pack.get("preferred_sections") if isinstance(structure_pack, dict) else None,
            "max_hedge_caveats": structure_pack.get("max_hedge_caveats") if isinstance(structure_pack, dict) else None,
        },
    }


def _run_check_style(workspace: Path, prose_pack: dict, structure_pack: dict | None) -> list[dict[str, object]]:
    """Run check_style.py as a subprocess with the resolved packs written to a
    private temp dir (never the workspace) and return its flat findings list."""
    with tempfile.TemporaryDirectory() as td:
        prose_f = Path(td) / "prose_rules.json"
        prose_f.write_text(json.dumps(prose_pack, ensure_ascii=False), encoding="utf-8")
        argv = [sys.executable, str(CHECK_STYLE), str(workspace), "--pack", str(prose_f)]
        if isinstance(structure_pack, dict):
            struct_f = Path(td) / "report_structure.json"
            struct_f.write_text(json.dumps(structure_pack, ensure_ascii=False), encoding="utf-8")
            argv += ["--structure-pack", str(struct_f)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env)
        try:
            verdict = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            verdict = {}
    findings = []
    if isinstance(verdict, dict):
        for bucket in ("hard", "warn"):
            for hit in verdict.get(bucket, []) or []:
                if isinstance(hit, dict):
                    findings.append({"code": hit.get("code", ""), "msg": hit.get("msg", ""),
                                     "at": hit.get("at", ""), "severity": bucket})
    return findings


def _map_hints(findings: list[dict], paragraphs: list[dict]) -> list[dict[str, object]]:
    """Map each check_style finding's matched span to the paragraph containing it.

    Both sides strip `[[...]]` tags (check_style matches against the tag-stripped
    body), so the truncated `at` span is a substring of the stripped paragraph.
    """
    stripped = [(str(p["paragraph_id"]), _TAG_RE.sub(" ", str(p["text"]))) for p in paragraphs]
    hints = []
    for finding in findings:
        code = str(finding.get("code", ""))
        rule_id = code.split(":", 1)[1] if ":" in code else code
        at = str(finding.get("at", ""))
        paragraph_id = None
        if at:
            for para_id, body in stripped:
                if at in body:
                    paragraph_id = para_id
                    break
        hints.append({"paragraph_id": paragraph_id, "rule_id": rule_id, "matched": at,
                      "description": str(finding.get("msg", "")),
                      "severity": finding.get("severity", "warn")})
    return hints


def _resolve_workers(backends_pack: dict) -> dict[str, object]:
    """Resolve reviewer/rewriter/fidelity roles to argv arrays from pack seats.

    Configuration surface only: no subprocess LLM call is made here. When no
    backends pack is supplied the caller omits the workers section and the
    harness-run mode is unchanged.
    """
    seats = backends_pack.get("seats", []) if isinstance(backends_pack, dict) else []
    roles: dict[str, object] = {}
    for canonical, aliases in _WORKER_ROLE_ALIASES.items():
        for seat in seats:
            if not isinstance(seat, dict):
                continue
            if str(seat.get("role", "")).lower() in aliases:
                roles[canonical] = {"cli": seat.get("cli"), "args_argv": seat.get("args_argv", []),
                                    "model": seat.get("model"), "timeout_s": seat.get("timeout_s")}
                break
    return {"mode": "backends", "roles": roles,
            "unresolved_roles": [c for c in _WORKER_ROLE_ALIASES if c not in roles],
            "pack_name": backends_pack.get("name") if isinstance(backends_pack, dict) else None,
            "pack_version": backends_pack.get("version") if isinstance(backends_pack, dict) else None}


def _violation_set(hints: list[dict] | None) -> set[str]:
    result = set()
    for hint in hints or []:
        paragraph_id = hint.get("paragraph_id")
        rule_id = hint.get("rule_id")
        if paragraph_id and rule_id:
            result.add(f"{paragraph_id}|{rule_id}")
    return result


def _rounds_path(paths: dict[str, Path]) -> Path:
    return paths["bundle"] / "humanization_rounds.json"


def _record_round(paths: dict[str, Path], round_number: int, violations: set[str]) -> list[dict[str, object]]:
    path = _rounds_path(paths)
    history: dict[str, object] = {"schema": "report-pipeline/humanization-rounds-v1", "rounds": []}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                history = loaded
        except json.JSONDecodeError:
            pass
    rounds = [r for r in history.get("rounds", []) if isinstance(r, dict) and r.get("round") != round_number]
    rounds.append({"round": round_number, "violations": sorted(violations)})
    rounds.sort(key=lambda r: r.get("round", 0))
    history["rounds"] = rounds
    _write_json(path, history)
    return rounds


def _no_progress(rounds: list[dict], round_number: int) -> bool:
    current = next((r for r in rounds if r.get("round") == round_number), None)
    previous = next((r for r in rounds if r.get("round") == round_number - 1), None)
    if not current or not previous:
        return False
    current_v = set(current.get("violations") or [])
    previous_v = set(previous.get("violations") or [])
    return bool(current_v) and current_v == previous_v


def _load_round_hints(paths: dict[str, Path], hints_path: Path | None) -> list[dict[str, object]]:
    """Per-round violation hints, from an explicit --hints file or, failing that,
    the hints the most recent prepare wrote into humanization_report.json."""
    data: object = None
    if hints_path is not None:
        data = json.loads(Path(hints_path).read_text(encoding="utf-8"))
    elif paths["report"].exists():
        try:
            data = json.loads(paths["report"].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        hints = data.get("hints")
        return hints if isinstance(hints, list) else []
    return []


def prepare(workspace: Path, force: bool = False, profile_root: Path | None = None,
            backends: Path | None = None, subject: str | None = None,
            doc_type: str | None = None) -> dict[str, object]:
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

    workers_section = None
    if backends is not None:
        backends_pack = pctl.load_pack_file(Path(backends))
        workers_section = _resolve_workers(backends_pack if isinstance(backends_pack, dict) else {})
        payload["workers"] = workers_section

    if profile_root is not None:
        root = Path(profile_root).expanduser().resolve()
        prose_pack = _merged_pack(root, "prose_rules", subject)
        structure_pack = _merged_pack(root, "report_structure", subject)
        directives = _voice_directives(prose_pack, structure_pack, doc_type)
        full_hints = _map_hints(_run_check_style(workspace, prose_pack, structure_pack),
                                 payload["paragraphs"])
        sidecar = root / "resolved" / f"{workspace.resolve().name}.humanize.json"
        sidecar_doc: dict[str, object] = {
            "schema": "report-pipeline/humanization-voice-v1",
            "workspace": workspace.resolve().name,
            "generated_at": pctl.now(),
            "voice_directives": directives,
            "hints": full_hints,
        }
        if workers_section is not None:
            sidecar_doc["workers"] = workers_section
        _write_json(sidecar, sidecar_doc)
        # The workspace payload carries only a POINTER to the private directives
        # plus content-derived hint spans; operator taste text never lands in
        # bundle/ (which W1 ships as the deliverable).
        payload["voice"] = {
            "source": "profile",
            "directives_path": str(sidecar.resolve()),
            "directives_sha256": pctl.sha256_bytes(pctl.canonical_bytes(directives)),
            "note": ("Operator prose-rule content is private; read it from directives_path "
                     "and never commit it into bundle/."),
        }
        payload["hints"] = [{"paragraph_id": h["paragraph_id"], "rule_id": h["rule_id"],
                             "matched": h["matched"], "severity": h.get("severity")}
                            for h in full_hints]

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


def apply_changes(workspace: Path, changes_path: Path,
                  hints_path: Path | None = None) -> tuple[dict[str, object], int]:
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

    # v3 no-progress detector: if the same (paragraph, rule) violation set from
    # the deterministic pre-pass repeats in two consecutive REWORK rounds, hold
    # and report early. Extends — never replaces — the 3-round cap, and the hard
    # rolled_back invariant always wins.
    no_progress = False
    if hints_path is not None or _rounds_path(paths).exists() or _load_round_hints(paths, hints_path):
        rounds = _record_round(paths, round_number, _violation_set(_load_round_hints(paths, hints_path)))
        no_progress = _no_progress(rounds, round_number)
        if no_progress and status != "rolled_back" and status != "accepted":
            status = "hold_and_report"
            code = 1
    hold_reason = None
    if status == "hold_and_report":
        hold_reason = "no_progress" if no_progress else "round_cap"

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
        "no_progress": no_progress,
        "hold_reason": hold_reason,
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
            item.add_argument("--profile-root", type=Path, default=None,
                              help="private profile root; loads prose_rules/report_structure "
                                   "packs at runtime and injects voice directives + pre-pass hints")
            item.add_argument("--backends", type=Path, default=None,
                              help="backends preference pack; resolves worker roles to argv arrays")
            item.add_argument("--subject", default=None, help="subject slug for pack precedence")
            item.add_argument("--doc-type", default=None, help="doc type for the endings policy")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("workspace", type=Path)
    apply_parser.add_argument("--changes", type=Path, required=True)
    apply_parser.add_argument("--hints", type=Path, default=None,
                              help="per-round pre-pass hints (JSON list or a prepare payload "
                                   "with a hints key) for the no-progress detector")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result, code = prepare(args.workspace, args.force, args.profile_root,
                                   args.backends, args.subject, args.doc_type), 0
        elif args.command == "apply":
            result, code = apply_changes(args.workspace, args.changes, args.hints)
        elif args.command == "validate":
            result, code = validate(args.workspace)
        else:
            result, code = rollback(args.workspace), 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
