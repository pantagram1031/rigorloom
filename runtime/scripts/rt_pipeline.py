#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only view of a report workspace's PIPELINE.md YAML header.

``workspace/pipelineStatus`` walks up from a document or directory, finds
``PIPELINE.md``, and returns the stage/gate records ``pipeline_ctl`` already
parsed. It does not advance, gate, check, or write. Verdicts are copied out of
the header; this module never re-decides them.

The grammar lives in ``modules/report/scripts/pipeline_ctl.py``. Importing its
parser (the way ``rt_module`` imports ``module_registry``) is the reuse; a
second inline-map reader here would drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import RpcError  # noqa: E402
from rt_engine import DEFAULT_ENGINE_ROOT  # noqa: E402

#: Start directory plus this many ancestors. ``output/out.hwpx`` is two hops
#: from a typical report workspace; four is the bound the GUI card named.
MAX_WALK_UP = 4

PIPELINE_FILENAME = "PIPELINE.md"

EMPTY_FILL_INPUTS = {
    "complete": False,
    "missing": [],
    "formPath": None,
    "contentPath": None,
    "buildYamlPath": None,
    "formProfilePath": None,
    "baselinePath": None,
}

EMPTY_POSTER_INPUTS = {
    "complete": False,
    "missing": [],
    "contentPath": None,
    "figuresPath": None,
    "formPath": None,
}

NOT_FOUND = {
    "found": False,
    "workspacePath": None,
    "slug": None,
    "mode": None,
    "subject": None,
    "updated": None,
    "canonicalOutput": None,
    "stages": [],
    "nextGate": None,
    "fillInputs": {
        "complete": False,
        "missing": [],
        "formPath": None,
        "contentPath": None,
        "buildYamlPath": None,
        "formProfilePath": None,
        "baselinePath": None,
    },
    "posterInputs": {
        "complete": False,
        "missing": [],
        "contentPath": None,
        "figuresPath": None,
        "formPath": None,
    },
}

FILL_REQUIRED = (
    ("build.yaml", "build.yaml"),
    ("bundle/content.md", "bundle/content.md"),
    ("form_profile.json", "form_profile.json"),
)


def _pipeline_ctl(engine_root: Path):
    """Import the report kernel's parser. No spawn, no CLI dispatch."""
    scripts = Path(engine_root) / "modules" / "report" / "scripts"
    path = scripts / "pipeline_ctl.py"
    if not path.is_file():
        raise RpcError(
            "capability_unavailable",
            "modules/report/scripts/pipeline_ctl.py is not importable, "
            "so this build cannot read a PIPELINE.md header",
            expected=str(path),
        )
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import pipeline_ctl  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise RpcError(
            "capability_unavailable",
            "modules/report/scripts/pipeline_ctl.py is not importable, "
            "so this build cannot read a PIPELINE.md header",
            detail=f"{type(exc).__name__}: {exc}",
            expected=str(path),
        ) from exc
    return pipeline_ctl


def _require_absolute_path(raw) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RpcError("invalid_params", "path must be a non-empty string")
    path = Path(raw)
    if not path.is_absolute():
        raise RpcError(
            "invalid_params",
            "path must be absolute; the Runtime has no ambient cwd",
        )
    try:
        return path.expanduser()
    except OSError as exc:
        raise RpcError("invalid_params", f"path is not usable: {exc}") from exc


def find_workspace(path: Path, *, max_levels: int = MAX_WALK_UP) -> Path | None:
    """Directory that contains PIPELINE.md, or None if none within the bound.

    A file starts at its parent; a directory starts at itself. Each step to a
    parent counts as one level. The starting directory is level 0.
    """
    current = path if path.is_dir() else path.parent
    for _ in range(max_levels + 1):
        if (current / PIPELINE_FILENAME).is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _nullish(value):
    """YAML null tokens → JSON null. Does not rewrite a real verdict string."""
    if value in (None, "", "null", "~"):
        return None
    return value


def _copy_gate(gate) -> dict | None:
    """Header gate record, field-for-field. None stays None."""
    if not gate:
        return None
    return {
        "name": gate.get("name", "") or "",
        "state": _nullish(gate.get("state")),
        "by": _nullish(gate.get("by")),
        "at": _nullish(gate.get("at")),
    }


def _stage_labels(ctl, hdr: dict) -> dict[str, str]:
    """id → stages.yaml ``name``. Labels only; never a substitute for status."""
    try:
        graph = ctl.graph_context_for_header(hdr)
    except Exception:  # noqa: BLE001 — a broken graph must not hide the header
        return {}
    labels: dict[str, str] = {}
    for row in graph.get("rows") or ():
        sid = str(row.get("id", ""))
        name = row.get("name")
        if sid and isinstance(name, str) and name:
            labels[sid] = name
    return labels


def _stage_order(ctl, hdr: dict, stages: dict) -> list[str]:
    """Graph order when it loads, then any header keys the graph omitted."""
    order: list[str] = []
    try:
        graph = ctl.graph_context_for_header(hdr)
        order = list(graph.get("order") or ())
    except Exception:  # noqa: BLE001
        order = []
    seen = set(order)
    extras = [key for key in stages if key not in seen]
    return [key for key in order if key in stages] + extras


def _next_gate(stage_rows: list[dict]) -> dict | None:
    """First stage whose header status is not done. Copied, not recomputed."""
    for row in stage_rows:
        if row.get("status") != "done":
            return {
                "stageId": row["id"],
                "status": row["status"],
                "gate": row.get("gate"),
            }
    return None


def _header_status(ctl, workspace: Path) -> dict:
    pipeline = workspace / PIPELINE_FILENAME
    try:
        text = pipeline.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise RpcError(
            "pipeline_header_unparsable",
            "PIPELINE.md is not valid UTF-8",
            workspacePath=str(workspace),
        ) from exc
    except OSError as exc:
        raise RpcError(
            "pipeline_header_unparsable",
            f"PIPELINE.md could not be read: {exc}",
            workspacePath=str(workspace),
        ) from exc

    span = ctl.find_yaml_fence(text)
    if span is None:
        raise RpcError(
            "pipeline_header_missing",
            "PIPELINE.md has no `# pipeline-state: v0.4` YAML fence",
            workspacePath=str(workspace),
        )

    _, _, body = span
    try:
        hdr = ctl.parse_yaml_header(body)
    except Exception as exc:  # noqa: BLE001
        raise RpcError(
            "pipeline_header_unparsable",
            f"PIPELINE.md YAML header could not be parsed: {exc}",
            workspacePath=str(workspace),
        ) from exc
    if not isinstance(hdr, dict):
        raise RpcError(
            "pipeline_header_unparsable",
            "PIPELINE.md YAML header did not parse as an object",
            workspacePath=str(workspace),
        )

    stages = hdr.get("stages") or {}
    if not isinstance(stages, dict):
        raise RpcError(
            "pipeline_header_unparsable",
            "PIPELINE.md stages map is not an object",
            workspacePath=str(workspace),
        )

    labels = _stage_labels(ctl, hdr)
    rows: list[dict] = []
    for stage_id in _stage_order(ctl, hdr, stages):
        record = stages[stage_id]
        if not isinstance(record, dict):
            raise RpcError(
                "pipeline_header_unparsable",
                f"PIPELINE.md stage {stage_id!r} is not an object",
                workspacePath=str(workspace),
            )
        row = {
            "id": str(stage_id),
            "status": record.get("status"),
            "gate": _copy_gate(record.get("gate")),
        }
        label = labels.get(str(stage_id))
        if label:
            row["label"] = label
        rows.append(row)

    canonical = _nullish(hdr.get("canonical_output"))

    return {
        "found": True,
        "workspacePath": str(workspace),
        "slug": _nullish(hdr.get("slug")),
        "mode": _nullish(hdr.get("mode")),
        "subject": _nullish(hdr.get("subject")),
        "updated": _nullish(hdr.get("updated")),
        "canonicalOutput": canonical,
        "stages": rows,
        "nextGate": _next_gate(rows),
        "fillInputs": fill_inputs(workspace, hdr),
        "posterInputs": poster_inputs(workspace),
    }


def resolve_form_path(workspace: Path, hdr: dict | None = None) -> Path | None:
    """Blank form the Stage 5 playbook fills: form_copy, else PIPELINE.md form."""
    copy = Path(workspace) / "output" / "form_copy.hwpx"
    try:
        if copy.is_file():
            return copy
    except OSError:
        pass
    raw = None
    if isinstance(hdr, dict):
        value = hdr.get("form")
        if isinstance(value, str) and value.strip():
            raw = value.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(workspace) / path
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _poster_form_path(workspace: Path) -> Path | None:
    """Blank poster PPTX. ``poster/form.pptx``, else one other pptx that is not the output."""
    named = Path(workspace) / "poster" / "form.pptx"
    try:
        if named.is_file():
            return named
    except OSError:
        pass
    poster_dir = Path(workspace) / "poster"
    try:
        if not poster_dir.is_dir():
            return None
        candidates = []
        for path in sorted(poster_dir.iterdir()):
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if path.suffix.lower() != ".pptx":
                continue
            if path.name.lower() in {"poster_v1.pptx", "form.pptx"}:
                continue
            candidates.append(path)
        if len(candidates) == 1:
            return candidates[0]
    except OSError:
        return None
    return None


def _poster_figures_path(workspace: Path) -> Path | None:
    for rel in ("poster/figures", "bundle/figures", "figures"):
        candidate = Path(workspace) / rel
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def poster_inputs(workspace: Path) -> dict:
    """Read-only: which poster CLI inputs exist. Never writes."""
    missing: list[str] = []
    content = Path(workspace) / "poster" / "poster_content.md"
    try:
        content_ok = content.is_file()
    except OSError:
        content_ok = False
    content_path = str(content) if content_ok else None
    if not content_ok:
        missing.append("poster/poster_content.md")

    figures = _poster_figures_path(workspace)
    figures_path = str(figures) if figures is not None else None
    if figures is None:
        missing.append("figures")

    form = _poster_form_path(workspace)
    form_path = str(form) if form is not None else None
    if form is None:
        missing.append("poster/form.pptx")

    return {
        "complete": not missing,
        "missing": missing,
        "contentPath": content_path,
        "figuresPath": figures_path,
        "formPath": form_path,
    }


def fill_inputs(workspace: Path, hdr: dict | None = None) -> dict:
    """Read-only: which fill_report --loop inputs exist. Never writes."""
    missing: list[str] = []
    paths: dict[str, str | None] = {
        "contentPath": None,
        "buildYamlPath": None,
        "formProfilePath": None,
        "baselinePath": None,
    }
    mapping = {
        "build.yaml": "buildYamlPath",
        "bundle/content.md": "contentPath",
        "form_profile.json": "formProfilePath",
    }
    for rel, label in FILL_REQUIRED:
        candidate = Path(workspace) / rel
        try:
            present = candidate.is_file()
        except OSError:
            present = False
        if present:
            paths[mapping[rel]] = str(candidate)
        else:
            missing.append(label)
    baseline = Path(workspace) / "form_baseline.json"
    try:
        if baseline.is_file():
            paths["baselinePath"] = str(baseline)
    except OSError:
        pass
    form = resolve_form_path(workspace, hdr)
    if form is None:
        missing.append("form")
    return {
        "complete": not missing,
        "missing": missing,
        "formPath": str(form) if form is not None else None,
        **paths,
    }


def pipeline_status(path, *, engine_root: Path | str | None = None) -> dict:
    """Host-only, read-only. Never writes; never calls pipeline_ctl advance."""
    start = _require_absolute_path(path)
    workspace = find_workspace(start)
    if workspace is None:
        return dict(NOT_FOUND)
    root = Path(engine_root) if engine_root is not None else DEFAULT_ENGINE_ROOT
    ctl = _pipeline_ctl(root)
    return _header_status(ctl, workspace)
