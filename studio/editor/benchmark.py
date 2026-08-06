"""Measure byte-local edit, soffice render, and PyMuPDF raster latency."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .render import discover_soffice, environment_summary
from .session import DocumentSession


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def _summary(values: list[float]) -> dict:
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999) - 1))
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "mean": round(statistics.mean(values), 3),
        "p95_nearest_rank": round(ordered[rank], 3),
        "max": round(max(values), 3),
    }


def _soffice_version(renderer_name: str | None) -> str | None:
    if not renderer_name:
        return None
    argv = (
        ["wsl", "-e", "soffice", "--version"]
        if renderer_name == "soffice_wsl"
        else ["soffice", "--version"]
    )
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return next((line.strip() for line in completed.stdout.splitlines() if line.strip()), None)


def run(document: Path, data_root: Path, *, iterations: int, warmup: int) -> dict:
    renderer, probe = discover_soffice(REPO_ROOT)
    if renderer is None:
        raise RuntimeError(f"soffice unavailable: {probe}")
    session = DocumentSession(document, data_root / f"benchmark-{time.time_ns()}")
    target = next(
        (
            item for item in session.paragraphs()
            if item.editable and "비식별 합성 문장" in item.text
        ),
        next(item for item in session.paragraphs() if item.editable and item.text.strip()),
    )
    base_text = target.text
    rows = []
    total_runs = warmup + iterations
    for index in range(total_runs):
        proposed = f"{base_text} [preview revision {index + 1}]"
        started = time.perf_counter()
        edit_started = time.perf_counter()
        edit = session.edit(
            paragraph_id=target.id,
            new_text=proposed,
            expected_revision=session.revision,
        )
        edit_ms = (time.perf_counter() - edit_started) * 1000
        preview = renderer.render(
            edit.document_path,
            session.session_dir / "benchmark-preview" / f"run-{index + 1:02d}",
        )
        cycle_ms = (time.perf_counter() - started) * 1000
        row = {
            "run": index + 1,
            "warmup": index < warmup,
            "revision": edit.revision,
            "edit_ms": round(edit_ms, 3),
            "render_ms": preview.render_ms,
            "raster_ms": preview.raster_ms,
            "cycle_ms": round(cycle_ms, 3),
            "fidelity_ok": edit.edit_result.fidelity.ok,
            "changed_members": list(edit.edit_result.fidelity.changed_members),
        }
        rows.append(row)
    measured = [row for row in rows if not row["warmup"]]
    try:
        display_document = document.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display_document = document.name
    payload = {
        "command": (
            "python -m studio.editor.benchmark "
            f"--iterations {iterations} --warmup {warmup}"
        ),
        "environment": {
            **environment_summary(renderer),
            "soffice_version": _soffice_version(renderer.name),
            "document": display_document,
            "document_bytes": document.stat().st_size,
            "document_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
            "capability_probe": probe,
        },
        "warmup_runs": warmup,
        "measured_runs": iterations,
        "runs": rows,
        "summary_ms": {
            key: _summary([row[key] for row in measured])
            for key in ("edit_ms", "render_ms", "raster_ms", "cycle_ms")
        },
        "under_3s_count": sum(row["cycle_ms"] < 3000 for row in measured),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document",
        type=Path,
        default=HERE / "sample_data" / "sanitized-editable.hwpx",
    )
    parser.add_argument("--data-root", type=Path, default=HERE / "results" / "runtime")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.iterations < 1 or args.warmup < 0:
        parser.error("--iterations must be >= 1 and --warmup must be >= 0")
    payload = run(
        args.document.resolve(),
        args.data_root.resolve(),
        iterations=args.iterations,
        warmup=args.warmup,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
