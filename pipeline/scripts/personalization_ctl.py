#!/usr/bin/env python3
"""Manage a private, auditable personalization store for report-pipeline.

This controller deliberately uses only the Python standard library.  Profile
roots are local state: they are never a required part of a report workspace or
of the public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "report-pipeline/personalization-v1"
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / ".local" / "personalization"

PACK_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "references" / "preference_packs"
PACK_DEFAULTS_DIR = PACK_SCHEMA_DIR / "defaults"
PACK_TYPES = ["prose_rules", "figure_style", "report_structure", "saeteuk",
              "gloss_allowlist", "backends", "policy_floors"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


# --- Minimal YAML reader (documented subset) --------------------------------
# Supported subset: full-line comments (`#`) and blank lines are skipped; block
# mappings (`key: value`) with 2-or-more-space indentation for nesting; block
# sequences (`- item`) indented under their key; scalar values are parsed as
# JSON when possible (so `["a","b"]`, `{"k":1}`, numbers, booleans, null, and
# double-quoted strings are exact), otherwise treated as a bare string. Author
# any value containing YAML-special characters (`:`, `#`, `[`, `{`, regex meta)
# as a double-quoted JSON string or an inline JSON flow value. This is not a
# general YAML parser; it exists so packs can be authored in .yaml without a
# third-party dependency.
def _yaml_scalar(token: str) -> Any:
    token = token.strip()
    if token == "":
        return None
    try:
        return json.loads(token)
    except Exception:
        return token


def parse_yaml(text: str) -> Any:
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        rows.append((len(raw) - len(stripped), stripped))
    pos = 0

    def block(min_indent: int) -> Any:
        nonlocal pos
        if pos >= len(rows):
            return None
        indent, content = rows[pos]
        if content.startswith("- "):
            seq: list[Any] = []
            while pos < len(rows):
                indent2, content2 = rows[pos]
                if indent2 != indent or not content2.startswith("- "):
                    break
                pos += 1
                seq.append(_yaml_scalar(content2[2:]))
            return seq
        mapping: dict[str, Any] = {}
        while pos < len(rows):
            indent2, content2 = rows[pos]
            if indent2 != indent or content2.startswith("- "):
                break
            key, _sep, val = content2.partition(":")
            key = key.strip()
            val = val.strip()
            pos += 1
            if val == "":
                if pos < len(rows) and rows[pos][0] > indent:
                    mapping[key] = block(rows[pos][0])
                else:
                    mapping[key] = None
            else:
                mapping[key] = _yaml_scalar(val)
        return mapping

    return block(0)


def load_pack_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            return json.loads(text)
        except Exception:
            return parse_yaml(text)
    try:
        return json.loads(text)
    except Exception:
        return parse_yaml(text)


# --- Minimal JSON Schema subset validator -----------------------------------
# Supported keywords: type, required, properties, items, enum,
# additionalProperties (boolean). `type` accepts object/array/string/number/
# integer/boolean/null. A schema node without `type` accepts any value. All
# other JSON Schema keywords are ignored. Draft 2020-12 meta keywords
# ($schema/$id/title/description) are ignored.
_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def validate_instance(instance: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        check = _TYPE_CHECKS.get(expected)
        if check and not check(instance):
            errors.append(f"{where}: expected type {expected}, got {type(instance).__name__}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{where}: value {instance!r} not in enum {schema['enum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{where}: missing required property '{key}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{where}: additional property '{key}' not allowed")
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate_instance(instance[key], sub, f"{where}.{key}"))
    if isinstance(instance, list) and "items" in schema:
        for idx, item in enumerate(instance):
            errors.extend(validate_instance(item, schema["items"], f"{where}[{idx}]"))
    return errors


def pack_schema(pack_type: str) -> dict[str, Any]:
    return json.loads((PACK_SCHEMA_DIR / f"{pack_type}.schema.json").read_text(encoding="utf-8"))


def pack_default(pack_type: str) -> Any:
    return json.loads((PACK_DEFAULTS_DIR / f"{pack_type}.json").read_text(encoding="utf-8"))


def deep_merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        merged = dict(base)
        for key, value in over.items():
            merged[key] = deep_merge(base.get(key), value) if key in base else value
        return merged
    return over


def _get_dotted(obj: Any, dotted: str) -> tuple[bool, Any]:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _set_dotted(obj: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def register_pack(root: Path, pack_type: str, file: Path) -> dict[str, Any]:
    if pack_type not in PACK_TYPES:
        raise ValueError(f"unknown pack type: {pack_type} (known: {', '.join(PACK_TYPES)})")
    content = load_pack_file(file)
    if not isinstance(content, dict):
        raise ValueError(f"pack file did not parse to a mapping: {file}")
    declared = content.get("pack_type")
    if declared is not None and declared != pack_type:
        raise ValueError(f"pack_type mismatch: file declares {declared!r}, --type is {pack_type!r}")
    errors = validate_instance(content, pack_schema(pack_type))
    if errors:
        raise ValueError("pack failed schema validation:\n  - " + "\n  - ".join(errors))
    store = root / "packs" / f"{pack_type}.json"
    write_json(store, content)
    digest = sha256_bytes(canonical_bytes(content))
    return {"ok": True, "pack_type": pack_type, "name": content.get("name"),
            "version": content.get("version"), "sha256": digest, "stored": str(store.resolve())}


def stored_pack(root: Path, pack_type: str) -> Any | None:
    path = root / "packs" / f"{pack_type}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def show_pack(root: Path, pack_type: str) -> dict[str, Any]:
    if pack_type not in PACK_TYPES:
        raise ValueError(f"unknown pack type: {pack_type}")
    content = stored_pack(root, pack_type)
    source = "profile"
    if content is None:
        content = pack_default(pack_type)
        source = "public-default"
    return {"ok": True, "pack_type": pack_type, "source": source,
            "sha256": sha256_bytes(canonical_bytes(content)), "content": content}


def list_packs(root: Path) -> dict[str, Any]:
    rows = []
    for pack_type in PACK_TYPES:
        content = stored_pack(root, pack_type)
        if content is None:
            content = pack_default(pack_type)
            source = "public-default"
        else:
            source = "profile"
        rows.append({"pack_type": pack_type, "source": source, "name": content.get("name"),
                     "version": content.get("version"),
                     "sha256": sha256_bytes(canonical_bytes(content))})
    return {"ok": True, "packs": rows}


def resolve_packs(root: Path, subject: str | None, form_digest: str | None) -> dict[str, Any]:
    """Merge packs by precedence (defaults < global < subject < form), then apply
    policy_floors LAST. Floor keys win unconditionally; a differing higher-precedence
    value is refused and recorded as a warning. Returns hash-only records plus the
    floor-warning list. Resolved rule CONTENT is never returned to the lock."""
    resolved: dict[str, Any] = {}
    source: dict[str, str] = {}
    for pack_type in PACK_TYPES:
        merged = pack_default(pack_type)
        src = "public-default"
        glob = stored_pack(root, pack_type)
        if glob is not None:
            merged = deep_merge(merged, glob)
            src = "global"
        if subject:
            sub = root / "academics" / "subjects" / subject / "packs" / f"{pack_type}.json"
            if sub.exists():
                merged = deep_merge(merged, json.loads(sub.read_text(encoding="utf-8")))
                src = "subject"
        if form_digest:
            frm = root / "forms" / form_digest / "packs" / f"{pack_type}.json"
            if frm.exists():
                merged = deep_merge(merged, json.loads(frm.read_text(encoding="utf-8")))
                src = "form"
        resolved[pack_type] = merged
        source[pack_type] = src

    floor_warnings: list[dict[str, Any]] = []
    floors_pack = resolved.get("policy_floors", {})
    for entry in floors_pack.get("floors", []):
        target_type = entry.get("pack")
        key = entry.get("key")
        floor_value = entry.get("value")
        target = resolved.get(target_type)
        if not isinstance(target, dict) or key is None:
            continue
        present, current = _get_dotted(target, key)
        if present and current != floor_value:
            floor_warnings.append({"pack": target_type, "key": key,
                                   "attempted_value": current, "floor_value": floor_value,
                                   "severity": entry.get("severity", "hard")})
        _set_dotted(target, key, floor_value)

    records = []
    for pack_type in PACK_TYPES:
        content = resolved[pack_type]
        records.append({"pack_type": pack_type, "source": source[pack_type],
                        "name": content.get("name"), "version": content.get("version"),
                        "sha256": sha256_bytes(canonical_bytes(content))})
    return {"packs": records, "floor_warnings": floor_warnings}


def profile_paths(root: Path) -> dict[str, Path]:
    return {
        "manifest": root / "manifest.json",
        "identity": root / "identity.json",
        "writing": root / "writing" / "profile.json",
        "rules": root / "writing" / "rules.json",
        "layout": root / "layout" / "profile.json",
        "academics": root / "academics" / "profile.json",
        "forms": root / "forms" / "index.json",
        "candidates": root / "feedback" / "candidates.jsonl",
        "events": root / "feedback" / "events.jsonl",
    }


def init(root: Path) -> dict[str, Any]:
    paths = profile_paths(root)
    root.mkdir(parents=True, exist_ok=True)
    defaults: dict[str, Any] = {
        "manifest": {"schema": SCHEMA, "version": 1, "created_at": now(), "redact_logs": True,
                     "generated_report_style_evidence": "forbidden"},
        "identity": {"schema": "report-pipeline/identity-v1", "enabled": False, "fields": {}},
        "writing": {"schema": "report-pipeline/writing-profile-v1", "language": "ko",
                    "academic_level": "high-school", "register": "formal-student-report",
                    "first_person": "reflection-only", "advanced_terms": "explain-or-remove",
                    "avoid_patterns": [], "protected": ["numbers", "units", "source_ids", "equations", "document_tags", "headings", "uncertainty", "negation", "logical_direction"]},
        "rules": {"schema": "report-pipeline/writing-rules-v1", "rules": []},
        "layout": {"schema": "report-pipeline/layout-profile-v1", "conventions": []},
        "academics": {"schema": "report-pipeline/academic-profile-v1", "subjects": [], "trajectory": []},
        "forms": {"schema": "report-pipeline/forms-index-v1", "forms": {}},
    }
    for key, value in defaults.items():
        if not paths[key].exists():
            write_json(paths[key], value)
    for relative in ("academics/subjects", "forms", "sources", "troubleshooting", "feedback", "snapshots"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return {"ok": True, "profile_root": str(root.resolve()), "schema": SCHEMA}


def form_record(root: Path, form: Path, form_profile: Path | None, subject: str | None) -> dict[str, Any]:
    init(root)
    form = form.resolve()
    digest = sha256(form)
    paths = profile_paths(root)
    index = read_json(paths["forms"], {"schema": "report-pipeline/forms-index-v1", "forms": {}})
    entry = index["forms"].get(digest, {})
    entry.update({"schema": "report-pipeline/form-record-v1", "sha256": digest, "filename": form.name,
                  "last_seen_path": str(form), "subject": subject, "registered_at": entry.get("registered_at", now()),
                  "updated_at": now()})
    target = root / "forms" / digest
    target.mkdir(parents=True, exist_ok=True)
    if form_profile and form_profile.exists():
        data = read_json(form_profile, {})
        write_json(target / "profile.json", data)
        conditions = {"schema": "report-pipeline/form-conditions-v1", "form_sha256": digest,
                      "constraints": data.get("constraints", {}), "format_hints": data.get("format_hints", {}),
                      "guide_text": data.get("guide_text", []), "source": str(form_profile.resolve())}
        write_json(target / "conditions.json", conditions)
        entry["inspected"] = True
    else:
        entry.setdefault("inspected", False)
    index["forms"][digest] = entry
    write_json(paths["forms"], index)
    return entry


def _request_values(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    # request.yaml is intentionally simple; preserve only safe style overrides.
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("  style:"):
            values["style"] = line.split(":", 1)[1].strip().strip('"')
    return values


def resolve(root: Path, workspace: Path, form: Path | None, subject: str | None, request: Path | None,
            form_profile: Path | None) -> dict[str, Any]:
    init(root)
    paths = profile_paths(root)
    form_entry = form_record(root, form, form_profile, subject) if form else None
    form_digest = form_entry["sha256"] if form_entry else None
    form_conditions = read_json(root / "forms" / str(form_digest) / "conditions.json", {}) if form_digest else {}
    overrides = read_json(root / "forms" / str(form_digest) / "overrides.json", {}) if form_digest else {}
    academic = read_json(paths["academics"], {})
    subject_data = read_json(root / "academics" / "subjects" / f"{subject}.json", {}) if subject else {}
    writing = read_json(paths["writing"], {})
    request_values = _request_values(request)
    safe_form_conditions = {key: value for key, value in form_conditions.items() if key != "source"}
    effective = {
        "writing": writing,
        "academic": subject_data or academic,
        "layout": read_json(paths["layout"], {}),
        "form_conditions": safe_form_conditions,
        "request_overrides": request_values,
        "precedence": ["request explicit", "form user override", "form extracted conditions", "subject profile", "global profile", "public defaults"],
    }
    if overrides:
        effective["form_overrides"] = overrides
    pack_resolution = resolve_packs(root, subject, str(form_digest) if form_digest else None)
    # The private feedback log keeps full floor-override values (it never leaves
    # the profile root); the workspace lock, by contrast, must carry NO values.
    for warning in pack_resolution["floor_warnings"]:
        append_jsonl(paths["events"], {"schema": "report-pipeline/floor-override-warning-v1",
                                       "at": now(), "workspace": workspace.name, **warning})

    # The full resolved ("effective") configuration is written to the PRIVATE
    # profile side only — never embedded in the workspace lock, which stays safe
    # to keep inside a (public) workspace because it leaks no taste text.
    resolved_rel = f"resolved/{workspace.name}.json"
    write_json(root / "resolved" / f"{workspace.name}.json", effective)
    effective_sha256 = sha256_bytes(canonical_bytes(effective))

    def _redact(value: Any) -> str:
        return "sha256:" + sha256_bytes(canonical_bytes(value))[:16]

    # floor_warnings in the lock keep only key paths + severity; the attempted
    # and floor VALUES are replaced by sha256 prefixes (never the raw content).
    redacted_warnings = [
        {"pack": w.get("pack"), "key": w.get("key"),
         "severity": w.get("severity", "hard"),
         "attempted_sha256": _redact(w.get("attempted_value")),
         "floor_sha256": _redact(w.get("floor_value"))}
        for w in pack_resolution["floor_warnings"]
    ]

    lock = {"schema": "report-pipeline/personalization-lock-v1", "lock_version": 3, "generated_at": now(),
            "profile_schema": SCHEMA, "profile_root_hint": root.name, "form_sha256": form_digest,
            "subject": subject, "identity_enabled": bool(read_json(paths["identity"], {}).get("enabled")),
            "effective_sha256": effective_sha256,
            "resolved_path_hint": resolved_rel,
            "packs": pack_resolution["packs"],
            "floor_warnings": redacted_warnings,
            "sources": {"writing": "global-writing-profile", "subject": f"subject:{subject}" if subject else None,
                        "form": f"sha256:{form_digest}" if form_digest else None},
            "lock_hash": ""}
    # Paths are useful locally but never identity values; hash the complete stable payload.
    canonical = json.dumps(lock, ensure_ascii=False, sort_keys=True).encode("utf-8")
    lock["lock_hash"] = hashlib.sha256(canonical).hexdigest()
    write_json(workspace / ".pipeline" / "personalization.lock.json", lock)
    return {"ok": True, "lock": str((workspace / ".pipeline" / "personalization.lock.json").resolve()),
            "form_sha256": form_digest, "lock_hash": lock["lock_hash"],
            "resolved": str((root / "resolved" / f"{workspace.name}.json").resolve())}


def import_legacy(root: Path, legacy: Path) -> dict[str, Any]:
    init(root)
    result = {"ok": True, "imported": {"style_files": 0, "layout_files": 0, "subject_files": 0, "forms": 0},
              "identity_imported": False, "note": "Identity is never inferred from legacy reports or filenames."}
    rules = read_json(profile_paths(root)["rules"], {"schema": "report-pipeline/writing-rules-v1", "rules": []})
    layout = read_json(profile_paths(root)["layout"], {"schema": "report-pipeline/layout-profile-v1", "conventions": []})
    for path in sorted((legacy / "kb" / "style").glob("*.md")) if (legacy / "kb" / "style").exists() else []:
        text = path.read_text(encoding="utf-8")
        item = {"id": f"legacy-{sha256(path)[:12]}", "status": "candidate", "scope": "global",
                "provenance": "legacy-import", "source_path": str(path), "source_sha256": sha256(path),
                "summary": text[:4000]}
        if "layout" in path.name.lower() or "레이아웃" in path.name:
            layout.setdefault("conventions", []).append(item); result["imported"]["layout_files"] += 1
        else:
            rules.setdefault("rules", []).append(item); result["imported"]["style_files"] += 1
    write_json(profile_paths(root)["rules"], rules); write_json(profile_paths(root)["layout"], layout)
    curriculum = legacy / "kb" / "curriculum"
    if curriculum.exists():
        for path in sorted(curriculum.glob("*.md")):
            slug = path.stem.replace("과목-", "")
            write_json(root / "academics" / "subjects" / f"{slug}.json", {"schema": "report-pipeline/subject-profile-v1", "subject": slug,
                "status": "legacy-import", "source_path": str(path), "source_sha256": sha256(path), "notes": path.read_text(encoding="utf-8")[:12000]})
            result["imported"]["subject_files"] += 1
    templates = legacy / "templates"
    if templates.exists():
        for path in sorted([*templates.glob("*.hwp"), *templates.glob("*.hwpx")]):
            form_record(root, path, None, None); result["imported"]["forms"] += 1
    return result


def collect_feedback(root: Path, workspace: Path) -> dict[str, Any]:
    init(root)
    event = {"schema": "report-pipeline/feedback-event-v1", "at": now(), "workspace": workspace.name,
             "files": [name for name in ("APPROVALS.md", "TROUBLES.md", "output/scorecard.json") if (workspace / name).exists()],
             "generated_prose_used": False}
    append_jsonl(profile_paths(root)["events"], event)
    trouble = workspace / "TROUBLES.md"
    candidates = 0
    if trouble.exists():
        for line in trouble.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
            is_header = cells[:3] in (["issue", "observed", "repair"], ["symptom", "cause", "action"])
            if line.lstrip().startswith("|") and "---" not in line and not is_header and len(line.split("|")) >= 4:
                append_jsonl(profile_paths(root)["candidates"], {"schema": "report-pipeline/feedback-candidate-v1", "at": now(),
                    "id": hashlib.sha256(f"{workspace.name}:{line}".encode("utf-8")).hexdigest()[:16], "status": "candidate", "kind": "troubleshooting", "summary": line.strip()[:800], "source": workspace.name,
                    "requires_human_review": True})
                candidates += 1
    return {"ok": True, "event": event, "candidates_added": candidates}


def candidates(root: Path, status: str | None = None) -> list[dict[str, Any]]:
    path = profile_paths(root)["candidates"]
    if not path.exists(): return []
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [item for item in values if status is None or item.get("status") == status]


def decide(root: Path, candidate_id: str, decision: str) -> dict[str, Any]:
    init(root)
    matches = [item for item in candidates(root) if item.get("id") == candidate_id]
    if not matches:
        raise ValueError(f"candidate not found: {candidate_id}")
    record = {"schema": "report-pipeline/feedback-decision-v1", "at": now(), "candidate_id": candidate_id,
              "decision": decision, "requires_human_review": False}
    append_jsonl(root / "feedback" / "decisions.jsonl", record)
    return {"ok": True, "decision": record}


def backup(root: Path, output: Path) -> dict[str, Any]:
    init(root); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(root))
    return {"ok": True, "backup": str(output.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    p = sub.add_parser("register-form"); p.add_argument("--form", required=True, type=Path); p.add_argument("--form-profile", type=Path); p.add_argument("--subject")
    p = sub.add_parser("resolve"); p.add_argument("--workspace", required=True, type=Path); p.add_argument("--form", type=Path); p.add_argument("--subject"); p.add_argument("--request", type=Path); p.add_argument("--form-profile", type=Path)
    p = sub.add_parser("register-pack"); p.add_argument("--type", required=True, choices=PACK_TYPES); p.add_argument("--file", required=True, type=Path)
    p = sub.add_parser("show-pack"); p.add_argument("--type", required=True, choices=PACK_TYPES)
    sub.add_parser("list-packs")
    p = sub.add_parser("import-legacy"); p.add_argument("--legacy-root", required=True, type=Path)
    p = sub.add_parser("collect-feedback"); p.add_argument("--workspace", required=True, type=Path)
    p = sub.add_parser("candidates"); p.add_argument("--status")
    p = sub.add_parser("approve"); p.add_argument("--id", required=True)
    p = sub.add_parser("reject"); p.add_argument("--id", required=True)
    p = sub.add_parser("export-backup"); p.add_argument("--output", required=True, type=Path)
    p = sub.add_parser("restore-backup"); p.add_argument("--input", required=True, type=Path)
    sub.add_parser("doctor")
    args = parser.parse_args(); root = args.profile_root.expanduser().resolve()
    if args.command == "init": result = init(root)
    elif args.command == "register-form": result = form_record(root, args.form, args.form_profile, args.subject)
    elif args.command == "resolve": result = resolve(root, args.workspace, args.form, args.subject, args.request, args.form_profile)
    elif args.command == "register-pack": init(root); result = register_pack(root, args.type, args.file)
    elif args.command == "show-pack": result = show_pack(root, args.type)
    elif args.command == "list-packs": result = list_packs(root)
    elif args.command == "import-legacy": result = import_legacy(root, args.legacy_root.resolve())
    elif args.command == "collect-feedback": result = collect_feedback(root, args.workspace.resolve())
    elif args.command == "candidates": result = {"ok": True, "candidates": candidates(root, args.status)}
    elif args.command == "approve": result = decide(root, args.id, "approved")
    elif args.command == "reject": result = decide(root, args.id, "rejected")
    elif args.command == "export-backup": result = backup(root, args.output)
    elif args.command == "restore-backup":
        init(root)
        with zipfile.ZipFile(args.input) as archive: archive.extractall(root)
        result = {"ok": True, "restored_to": str(root)}
    else:
        init(root); result = {"ok": True, "profile_root": str(root), "warnings": [], "identity_enabled": read_json(profile_paths(root)["identity"], {}).get("enabled", False)}
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0



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
