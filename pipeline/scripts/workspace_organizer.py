#!/usr/bin/env python3
"""Create a deterministic handoff and archive safe transient files.

The organizer never moves canonical pipeline artifacts. It only archives
explicit scratch directories, temporary root files, and known run logs.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


CANONICAL_DIRS = (
    "research", "bundle", "bundle/figures", "sim", "figures", "output",
    "refs", "archive", ".pipeline",
)
ROOT_TRANSIENT_PATTERNS = ("*.tmp", "*.bak", "*.old")
OUTPUT_TRANSIENT_PATTERNS = (
    "loop*_stderr.log", "loop*_stdout.json", "loop*_err.txt",
    "loop*_run.log",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _next_stage(hdr: dict, stage_order: list[str]) -> tuple[str | None, dict | None]:
    stages = hdr.get("stages", {})
    for stage in stage_order:
        state = stages.get(stage)
        if state and state.get("status") in {"pending", "in_progress", "awaiting_gate", "blocked"}:
            return stage, state
    return None, None


def _archive_transients(ws: Path, stage: str | None) -> list[str]:
    candidates: list[Path] = []
    for name in ("scratch", "tmp"):
        path = ws / name
        if path.exists():
            candidates.append(path)
    for pattern in ROOT_TRANSIENT_PATTERNS:
        candidates.extend(path for path in ws.glob(pattern) if path.is_file())
    output = ws / "output"
    if output.exists():
        for pattern in OUTPUT_TRANSIENT_PATTERNS:
            candidates.extend(path for path in output.glob(pattern) if path.is_file())

    if not candidates:
        return []

    bucket = ws / "archive" / "stages" / f"stage-{stage or 'manual'}" / _stamp()
    bucket.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for source in sorted(set(candidates)):
        destination = bucket / source.name
        counter = 1
        while destination.exists():
            destination = bucket / f"{source.stem}-{counter}{source.suffix}"
            counter += 1
        shutil.move(str(source), str(destination))
        moved.append(str(destination.relative_to(ws)).replace("\\", "/"))
    return moved


def organize_workspace(
    ws: Path,
    hdr: dict,
    stage_order: list[str],
    completed_stage: str | None = None,
    archive_transients: bool = True,
) -> dict:
    ws = ws.resolve()
    for relative in CANONICAL_DIRS:
        (ws / relative).mkdir(parents=True, exist_ok=True)

    archived = _archive_transients(ws, completed_stage) if archive_transients else []
    next_stage, next_state = _next_stage(hdr, stage_order)
    next_gate = next_state.get("gate") if next_state else None
    playbook = (
        f"pipeline/references/playbooks/stage-{next_stage}.md"
        if next_stage is not None else None
    )
    handoff = {
        "schema": "report-pipeline-handoff/v1",
        "workspace": str(ws),
        "pipeline_version": hdr.get("pipeline_version", "0.6"),
        "mode": hdr.get("mode", "autonomous"),
        "completed_stage": completed_stage,
        "next_stage": next_stage,
        "next_status": next_state.get("status") if next_state else None,
        "next_gate": next_gate,
        "playbook": playbook,
        "resume_command": f'python pipeline/scripts/pipeline_ctl.py resume "{ws}"',
        "archived": archived,
        "generated_at": _now(),
    }
    _atomic_json(ws / ".pipeline" / "handoff.json", handoff)

    if next_stage is None:
        action = "Workflow complete. Review output/, then retain the workspace as an immutable record."
    elif next_state and next_state.get("status") == "awaiting_gate":
        gate_name = (next_gate or {}).get("name", "human")
        action = f"Resolve the `{gate_name}` gate, then resume Stage {next_stage}."
    elif next_state and next_state.get("status") == "blocked":
        action = f"Read TROUBLES.md, resolve the blocker, then resume Stage {next_stage}."
    else:
        action = f"Open `{playbook}` and continue Stage {next_stage}."

    next_task = f"""# Next task

Generated automatically at {handoff['generated_at']}.

- Completed stage: `{completed_stage or 'none'}`
- Next stage: `{next_stage or 'complete'}`
- Status: `{handoff['next_status'] or 'done'}`
- Action: {action}

```sh
{handoff['resume_command']}
```

Canonical artifacts remain in their normal directories. Safe transient files
were preserved under `archive/stages/`; see `.pipeline/handoff.json` for details.
"""
    (ws / "NEXT_TASK.md").write_text(next_task, encoding="utf-8")
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize a report-pipeline workspace")
    parser.add_argument("workspace")
    parser.add_argument("--completed-stage")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()

    # Lazy import avoids a cycle when pipeline_ctl invokes this module.
    import pipeline_ctl

    ws = Path(args.workspace)
    loaded = pipeline_ctl.load_header(ws)
    if loaded is None:
        parser.error("PIPELINE.md missing or invalid")
    hdr = loaded[3]
    result = organize_workspace(
        ws, hdr, pipeline_ctl.STAGE_ORDER,
        completed_stage=args.completed_stage,
        archive_transients=not args.no_archive,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
