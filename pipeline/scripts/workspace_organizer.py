#!/usr/bin/env python3
"""Organize a workspace, inventory artifacts, and create deterministic handoffs."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


LAYOUT_PATH = Path(__file__).resolve().parent.parent / "references" / "workspace_layout.json"
ROOT_TRANSIENT_PATTERNS = ("*.tmp", "*.bak", "*.old")
OUTPUT_TRANSIENT_PATTERNS = (
    "loop*_stderr.log", "loop*_stdout.json", "loop*_err.txt", "loop*_run.log",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def _atomic_json(path: Path, payload: dict) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_layout(path: Path | None = None) -> dict:
    source = path or LAYOUT_PATH
    return json.loads(source.read_text(encoding="utf-8"))


def _next_stage(hdr: dict, stage_order: list[str]) -> tuple[str | None, dict | None]:
    stages = hdr.get("stages", {})
    for stage in stage_order:
        state = stages.get(stage)
        if state and state.get("status") in {"pending", "in_progress", "awaiting_gate", "blocked"}:
            return stage, state
    return None, None


def _matches(ws: Path, pattern: str) -> list[Path]:
    return sorted(path for path in ws.glob(pattern) if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(ws: Path, path: Path) -> dict:
    stat = path.stat()
    return {
        "path": path.relative_to(ws).as_posix(),
        "size": stat.st_size,
        "sha256": _sha256(path),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }


def _evaluate_entries(ws: Path, entries: list[dict]) -> list[dict]:
    evaluated = []
    for entry in entries:
        pattern = entry["pattern"]
        matches = _matches(ws, pattern)
        evaluated.append({
            "pattern": pattern,
            "required": bool(entry.get("required", False)),
            "present": bool(matches),
            "files": [_file_record(ws, path) for path in matches],
        })
    return evaluated


def build_inventory(ws: Path, hdr: dict, stage_order: list[str], layout: dict) -> dict:
    stages = hdr.get("stages", {})
    inventory_stages = {}
    for stage in ["-1", *stage_order]:
        spec = layout.get("stages", {}).get(stage, {})
        inputs = _evaluate_entries(ws, spec.get("inputs", []))
        outputs = _evaluate_entries(ws, spec.get("outputs", []))
        inventory_stages[stage] = {
            "name": spec.get("name", stage),
            "status": "done" if stage == "-1" else stages.get(stage, {}).get("status", "absent"),
            "inputs": inputs,
            "outputs": outputs,
            "missing_inputs": [item["pattern"] for item in inputs if item["required"] and not item["present"]],
            "missing_outputs": [item["pattern"] for item in outputs if item["required"] and not item["present"]],
        }
    return {
        "schema": "report-pipeline-artifacts/v1",
        "workspace": str(ws),
        "generated_at": _now(),
        "stages": inventory_stages,
    }


def _ensure_stage_workdir(ws: Path, stage: str | None, layout: dict) -> str | None:
    if stage is None:
        return None
    spec = layout.get("stages", {}).get(stage, {})
    workdir = ws / "work" / f"stage-{stage}"
    (workdir / "scratch").mkdir(parents=True, exist_ok=True)
    readme = workdir / "README.md"
    if not readme.exists():
        expected = [item["pattern"] for item in spec.get("outputs", [])]
        text = "# Stage work area\n\n"
        text += "Use `scratch/` for temporary files. Canonical outputs belong at:\n\n"
        text += "\n".join(f"- `{pattern}`" for pattern in expected) or "- No declared outputs"
        text += "\n\nThis directory is archived automatically when the stage is completed or blocked.\n"
        readme.write_text(text, encoding="utf-8")
    return workdir.relative_to(ws).as_posix()


def _archive_transients(ws: Path, stage: str | None) -> list[str]:
    candidates: list[tuple[Path, str]] = []
    for name in ("scratch", "tmp"):
        path = ws / name
        if path.exists():
            candidates.append((path, name))
    for pattern in ROOT_TRANSIENT_PATTERNS:
        candidates.extend((path, path.name) for path in ws.glob(pattern) if path.is_file())
    output = ws / "output"
    if output.exists():
        for pattern in OUTPUT_TRANSIENT_PATTERNS:
            candidates.extend((path, f"output-{path.name}") for path in output.glob(pattern) if path.is_file())
    if stage is not None:
        stage_work = ws / "work" / f"stage-{stage}"
        if stage_work.exists():
            candidates.append((stage_work, "work"))

    if not candidates:
        return []

    bucket = ws / "archive" / "stages" / f"stage-{stage or 'manual'}" / _stamp()
    bucket.mkdir(parents=True, exist_ok=True)
    moved = []
    seen = set()
    for source, preferred_name in candidates:
        resolved = source.resolve()
        if resolved in seen or not source.exists():
            continue
        seen.add(resolved)
        destination = bucket / preferred_name
        counter = 1
        while destination.exists():
            destination = bucket / f"{Path(preferred_name).stem}-{counter}{Path(preferred_name).suffix}"
            counter += 1
        shutil.move(str(source), str(destination))
        moved.append(destination.relative_to(ws).as_posix())
    return moved


def _stage_summary(inventory: dict, stage: str | None) -> dict:
    if stage is None:
        return {"inputs": [], "outputs": [], "missing_inputs": [], "missing_outputs": []}
    item = inventory["stages"].get(stage, {})
    return {
        "inputs": [entry["pattern"] for entry in item.get("inputs", [])],
        "outputs": [entry["pattern"] for entry in item.get("outputs", [])],
        "missing_inputs": item.get("missing_inputs", []),
        "missing_outputs": item.get("missing_outputs", []),
    }


def _write_receipt(ws: Path, stage: str, hdr: dict, inventory: dict, archived: list[str]) -> str:
    stage_inventory = inventory["stages"].get(stage, {})
    receipt = {
        "schema": "report-pipeline-stage-receipt/v1",
        "stage": stage,
        "status": hdr.get("stages", {}).get(stage, {}).get("status"),
        "artifacts": stage_inventory.get("outputs", []),
        "missing_outputs": stage_inventory.get("missing_outputs", []),
        "archived": archived,
        "recorded_at": _now(),
    }
    receipts = ws / ".pipeline" / "receipts"
    path = receipts / f"stage-{stage}-{_stamp()}.json"
    counter = 1
    while path.exists():
        path = receipts / f"stage-{stage}-{_stamp()}-{counter}.json"
        counter += 1
    _atomic_json(path, receipt)
    return path.relative_to(ws).as_posix()


def _workspace_index(inventory: dict, next_stage: str | None, workdir: str | None) -> str:
    rows = []
    for stage, item in inventory["stages"].items():
        outputs = sum(len(entry["files"]) for entry in item["outputs"])
        missing = ", ".join(item["missing_outputs"]) or "—"
        rows.append(f"| {stage} | {item['name']} | {item['status']} | {outputs} | {missing} |")
    return f"""# Workspace index

Generated automatically at {inventory['generated_at']}.

- Next stage: `{next_stage or 'complete'}`
- Active work area: `{workdir or 'none'}`
- Machine inventory: `.pipeline/artifacts.json`
- Machine handoff: `.pipeline/handoff.json`

| Stage | Name | State | Files | Missing required outputs |
|---|---|---|---:|---|
{chr(10).join(rows)}

Temporary work belongs under `work/stage-<id>/scratch/`. Canonical artifacts
belong only at the paths declared in `pipeline/references/workspace_layout.json`.
"""


def organize_workspace(
    ws: Path,
    hdr: dict,
    stage_order: list[str],
    completed_stage: str | None = None,
    archive_transients: bool = True,
    layout: dict | None = None,
) -> dict:
    ws = ws.resolve()
    layout = layout or load_layout()
    for relative in layout.get("canonical_dirs", []):
        (ws / relative).mkdir(parents=True, exist_ok=True)

    archived = _archive_transients(ws, completed_stage) if archive_transients else []
    next_stage, next_state = _next_stage(hdr, stage_order)
    workdir = _ensure_stage_workdir(ws, next_stage, layout)
    inventory = build_inventory(ws, hdr, stage_order, layout)
    _atomic_json(ws / ".pipeline" / "artifacts.json", inventory)
    _atomic_text(ws / "WORKSPACE_INDEX.md", _workspace_index(inventory, next_stage, workdir))

    receipt = None
    if completed_stage is not None:
        receipt = _write_receipt(ws, completed_stage, hdr, inventory, archived)

    next_gate = next_state.get("gate") if next_state else None
    playbook = f"pipeline/references/playbooks/stage-{next_stage}.md" if next_stage else None
    summary = _stage_summary(inventory, next_stage)
    handoff = {
        "schema": "report-pipeline-handoff/v2",
        "workspace": str(ws),
        "pipeline_version": hdr.get("pipeline_version", "0.6"),
        "mode": hdr.get("mode", "autonomous"),
        "completed_stage": completed_stage,
        "receipt": receipt,
        "next_stage": next_stage,
        "next_status": next_state.get("status") if next_state else None,
        "next_gate": next_gate,
        "playbook": playbook,
        "work_dir": workdir,
        "required_inputs": summary["inputs"],
        "expected_outputs": summary["outputs"],
        "missing_inputs": summary["missing_inputs"],
        "missing_outputs": summary["missing_outputs"],
        "inventory": ".pipeline/artifacts.json",
        "resume_command": f'python pipeline/scripts/pipeline_ctl.py resume "{ws}"',
        "archived": archived,
        "personalization_lock": ".pipeline/personalization.lock.json" if (ws / ".pipeline" / "personalization.lock.json").is_file() else None,
        "generated_at": _now(),
    }
    _atomic_json(ws / ".pipeline" / "handoff.json", handoff)

    if next_stage is None:
        action = "Workflow complete. Review output/ and the final stage receipt."
    elif next_state and next_state.get("status") == "awaiting_gate":
        action = f"Resolve the `{(next_gate or {}).get('name', 'human')}` gate, then resume."
    elif next_state and next_state.get("status") == "blocked":
        action = "Read TROUBLES.md and the stage receipt, resolve the blocker, then resume."
    elif summary["missing_inputs"]:
        action = "Restore or create the missing required inputs before starting the stage."
    else:
        action = f"Work in `{workdir}` and publish only the declared outputs."

    def bullets(values: list[str]) -> str:
        return "\n".join(f"- `{value}`" for value in values) if values else "- None"

    next_task = f"""# Next task

Generated automatically at {handoff['generated_at']}.

- Completed stage: `{completed_stage or 'none'}`
- Next stage: `{next_stage or 'complete'}`
- Status: `{handoff['next_status'] or 'done'}`
- Work area: `{workdir or 'none'}`
- Action: {action}

## Required inputs

{bullets(summary['inputs'])}

## Expected outputs

{bullets(summary['outputs'])}

## Missing required inputs

{bullets(summary['missing_inputs'])}

```sh
{handoff['resume_command']}
```

See `WORKSPACE_INDEX.md` for the complete inventory. Canonical artifacts remain
in place; completed-stage scratch work is preserved under `archive/stages/`.
"""
    _atomic_text(ws / "NEXT_TASK.md", next_task)
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize a Rigorloom workspace")
    parser.add_argument("workspace")
    parser.add_argument("--completed-stage")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--layout", type=Path)
    args = parser.parse_args()

    import pipeline_ctl

    ws = Path(args.workspace)
    loaded = pipeline_ctl.load_header(ws)
    if loaded is None:
        parser.error("PIPELINE.md missing or invalid")
    result = organize_workspace(
        ws, loaded[3], pipeline_ctl.STAGE_ORDER,
        completed_stage=args.completed_stage,
        archive_transients=not args.no_archive,
        layout=load_layout(args.layout) if args.layout else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
