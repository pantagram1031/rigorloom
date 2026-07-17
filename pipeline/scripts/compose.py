#!/usr/bin/env python3
"""Deterministically resolve typed modules into existing pipeline stages.

Applying a module plan to the build graph is intentionally stricter than the
module-to-stage projection. The applied header retains every registered gate
stage inside the selected execution span. Selecting Stage 2 also retains the
2.5 layout gate, and an execution span that enters Stage 5 retains the complete
post-assembly floor (5.3, 5.5, 5.7, and 6). A plan entering strictly at Stage 6
does not backfill earlier gates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import pipeline_ctl
import workflow_lint

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_MODULES = SCRIPT_PATH.parent.parent / "references" / "modules.yaml"
DEFAULT_ALIASES = SCRIPT_PATH.parent.parent / "references" / "aliases.yaml"
DEFAULT_MATRIX_DOC = REPO_ROOT / "docs" / "capability-matrix.md"
OS_ORDER = {"any": 0, "tiered": 1, "windows": 2}
STATUS_VALUES = {"active", "planned"}
STAGE_ID_RE = re.compile(r"^\d+(?:\.\d+)?$")

class ComposeError(ValueError):
    """A deterministic manifest, resolution, or intake usage error."""


def _flow_value(token: str):
    token = token.strip()
    if token.startswith("{") and token.endswith("}"):
        return _flow_map(token[1:-1])
    if token.startswith("[") and token.endswith("]"):
        return [
            _flow_value(part)
            for part in pipeline_ctl._split_top_commas(token[1:-1])
            if part.strip()
        ]
    if token in {"null", "~"}:
        return None
    if token in {"true", "false"}:
        return token == "true"
    return pipeline_ctl._strip_q(token)


def _flow_map(body: str) -> dict:
    payload = {}
    for part in pipeline_ctl._split_top_commas(body):
        if not part.strip():
            continue
        if ":" not in part:
            raise ComposeError(
                f"flow manifest entry has no key/value separator: {part.strip()!r}"
            )
        key, value = part.split(":", 1)
        payload[pipeline_ctl._strip_q(key)] = _flow_value(value)
    return payload


def _block_flow_yaml(text: str) -> dict:
    payload = {}
    sequence_key = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = pipeline_ctl._strip_inline_comment(raw)
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1].isspace():
            if sequence_key is None or not stripped.startswith("- "):
                raise ComposeError(
                    f"unsupported manifest structure at line {number}: {stripped!r}"
                )
            payload[sequence_key].append(_flow_value(stripped[2:]))
            continue
        if ":" not in stripped:
            raise ComposeError(
                f"manifest entry has no key/value separator at line {number}"
            )
        key, value = stripped.split(":", 1)
        key = pipeline_ctl._strip_q(key)
        value = value.strip()
        if value:
            payload[key] = _flow_value(value)
            sequence_key = None
        else:
            payload[key] = []
            sequence_key = key
    return payload


def _load_json_yaml(path: str | Path) -> dict:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ComposeError(f"manifest unreadable: {source}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        stripped = text.strip()
        try:
            payload = (
                _flow_map(stripped[1:-1])
                if stripped.startswith("{") and stripped.endswith("}")
                else _block_flow_yaml(text)
            )
        except (ComposeError, ValueError) as flow_exc:
            raise ComposeError(
                f"manifest is not valid JSON/flow YAML: {source}: {flow_exc}"
            ) from exc
    if not isinstance(payload, dict):
        raise ComposeError(f"manifest root must be a mapping: {source}")
    return payload


def _string_list(value, where: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ComposeError(f"{where} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise ComposeError(f"{where} must not be empty")
    if len(value) != len(set(value)):
        raise ComposeError(f"{where} contains duplicates")
    return list(value)


def load_module_catalog(path: str | Path = DEFAULT_MODULES) -> dict:
    catalog = _load_json_yaml(path)
    artifacts = _string_list(
        catalog.get("artifact_types"), "artifact_types", allow_empty=False
    )
    artifact_set = set(artifacts)
    modules = catalog.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ComposeError("modules must be a non-empty list")

    seen: set[str] = set()
    normalized = []
    required = {"id", "consumes", "produces", "stage", "gates", "os"}
    allowed = required | {"status", "graph"}
    for index, raw in enumerate(modules):
        where = f"modules[{index}]"
        if not isinstance(raw, dict):
            raise ComposeError(f"{where} must be a mapping")
        extra = set(raw) - allowed
        missing = required - set(raw)
        if missing:
            raise ComposeError(f"{where} missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise ComposeError(f"{where} has unexpected fields: {', '.join(sorted(extra))}")
        module_id = raw.get("id")
        if not isinstance(module_id, str) or not module_id:
            raise ComposeError(f"{where}.id must be a non-empty string")
        if module_id in seen:
            raise ComposeError(f"duplicate module id: {module_id}")
        seen.add(module_id)
        consumes = _string_list(raw["consumes"], f"{where}.consumes")
        produces = _string_list(
            raw["produces"], f"{where}.produces", allow_empty=False
        )
        unknown = sorted((set(consumes) | set(produces)) - artifact_set)
        if unknown:
            raise ComposeError(
                f"{where} uses artifacts outside the closed vocabulary: "
                f"{', '.join(unknown)}"
            )
        if not isinstance(raw["stage"], str) or not raw["stage"]:
            raise ComposeError(f"{where}.stage must be a non-empty string")
        gates = _string_list(raw["gates"], f"{where}.gates")
        if raw["os"] not in OS_ORDER:
            raise ComposeError(f"{where}.os must be one of: {', '.join(OS_ORDER)}")
        status = raw.get("status", "active")
        if status not in STATUS_VALUES:
            raise ComposeError(f"{where}.status must be active or planned")
        graph = raw.get("graph", "build")
        if graph not in pipeline_ctl.GRAPH_FILES:
            raise ComposeError(
                f"{where}.graph must be one of: "
                f"{', '.join(sorted(pipeline_ctl.GRAPH_FILES))}"
            )
        normalized.append({
            "id": module_id, "consumes": consumes, "produces": produces,
            "stage": raw["stage"], "gates": gates, "os": raw["os"],
            "status": status, "graph": graph,
        })
    return {
        "schema": catalog.get("schema"),
        "artifact_types": artifacts,
        "modules": normalized,
    }


def load_alias_catalog(
    path: str | Path = DEFAULT_ALIASES, module_catalog: dict | None = None
) -> dict:
    catalog = _load_json_yaml(path)
    aliases = catalog.get("aliases")
    if not isinstance(aliases, list) or not aliases:
        raise ComposeError("aliases must be a non-empty list")
    artifacts = (
        set(module_catalog["artifact_types"]) if module_catalog is not None else None
    )
    module_ids = (
        {module["id"] for module in module_catalog["modules"]}
        if module_catalog is not None else None
    )
    seen: set[str] = set()
    normalized = []
    required = {"id", "have", "want"}
    allowed = required | {"forced", "status"}
    for index, raw in enumerate(aliases):
        where = f"aliases[{index}]"
        if not isinstance(raw, dict):
            raise ComposeError(f"{where} must be a mapping")
        missing = required - set(raw)
        extra = set(raw) - allowed
        if missing:
            raise ComposeError(f"{where} missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise ComposeError(f"{where} has unexpected fields: {', '.join(sorted(extra))}")
        alias_id = raw["id"]
        if not isinstance(alias_id, str) or not alias_id:
            raise ComposeError(f"{where}.id must be a non-empty string")
        if alias_id in seen:
            raise ComposeError(f"duplicate alias id: {alias_id}")
        seen.add(alias_id)
        have = _string_list(raw["have"], f"{where}.have")
        want = raw["want"]
        if not isinstance(want, str) or not want:
            raise ComposeError(f"{where}.want must be a non-empty string")
        forced = _string_list(raw.get("forced", []), f"{where}.forced")
        status = raw.get("status", "active")
        if status not in STATUS_VALUES:
            raise ComposeError(f"{where}.status must be active or planned")
        if artifacts is not None:
            unknown = sorted((set(have) | {want}) - artifacts)
            if unknown:
                raise ComposeError(
                    f"{where} uses artifacts outside the closed vocabulary: "
                    f"{', '.join(unknown)}"
                )
        if module_ids is not None:
            unknown_modules = sorted(set(forced) - module_ids)
            if unknown_modules:
                raise ComposeError(
                    f"{where} forces unknown modules: {', '.join(unknown_modules)}"
                )
        normalized.append({
            "id": alias_id, "have": have, "want": want,
            "forced": forced, "status": status,
        })
    return {"schema": catalog.get("schema"), "aliases": normalized}


def _topological_modules(selected: set[str], modules: list[dict]) -> list[dict]:
    by_id = {module["id"]: module for module in modules}
    index = {module["id"]: position for position, module in enumerate(modules)}
    producers: dict[str, list[str]] = {}
    for module in modules:
        if module["id"] in selected:
            for artifact in module["produces"]:
                producers.setdefault(artifact, []).append(module["id"])

    outgoing = {module_id: set() for module_id in selected}
    indegree = {module_id: 0 for module_id in selected}
    for consumer_id in selected:
        for artifact in by_id[consumer_id]["consumes"]:
            for producer_id in producers.get(artifact, []):
                if producer_id == consumer_id or consumer_id in outgoing[producer_id]:
                    continue
                outgoing[producer_id].add(consumer_id)
                indegree[consumer_id] += 1

    ready = sorted(
        (module_id for module_id, degree in indegree.items() if degree == 0),
        key=index.__getitem__,
    )
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in sorted(outgoing[current], key=index.__getitem__):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=index.__getitem__)
    if len(ordered) != len(selected):
        cyclic = sorted(
            (module_id for module_id, degree in indegree.items() if degree),
            key=index.__getitem__,
        )
        raise ComposeError(f"cycle detected among modules: {', '.join(cyclic)}")
    return [by_id[module_id] for module_id in ordered]


def resolve_modules(
    catalog: dict,
    have: Iterable[str],
    want: str,
    forced: Iterable[str] = (),
    *,
    allow_planned: bool = False,
) -> list[dict]:
    artifacts = set(catalog["artifact_types"])
    have_list = list(dict.fromkeys(have))
    unknown = sorted((set(have_list) | {want}) - artifacts)
    if unknown:
        raise ComposeError(
            f"unknown artifact type(s): {', '.join(unknown)}; "
            f"closed vocabulary: {', '.join(catalog['artifact_types'])}"
        )
    modules = catalog["modules"]
    by_id = {module["id"]: module for module in modules}
    forced_list = list(dict.fromkeys(forced))
    unknown_forced = sorted(set(forced_list) - set(by_id))
    if unknown_forced:
        raise ComposeError(f"unknown forced module(s): {', '.join(unknown_forced)}")

    producers: dict[str, list[dict]] = {}
    for module in modules:
        for artifact in module["produces"]:
            producers.setdefault(artifact, []).append(module)

    available = set(have_list)
    selected: set[str] = set()
    resolving_artifacts: list[str] = []
    resolving_modules: list[str] = []

    def planned_error(items: list[dict], artifact: str | None = None) -> ComposeError:
        names = ", ".join(module["id"] for module in items)
        subject = f" for artifact '{artifact}'" if artifact else ""
        return ComposeError(
            f"planned module(s){subject} cannot be scheduled: {names}; "
            "a later wave must flip status to active"
        )

    def schedule(module: dict) -> None:
        module_id = module["id"]
        if module_id in selected:
            return
        if module["status"] == "planned" and not allow_planned:
            raise planned_error([module])
        if module_id in resolving_modules:
            start = resolving_modules.index(module_id)
            cycle = resolving_modules[start:] + [module_id]
            raise ComposeError(f"cycle detected among modules: {' -> '.join(cycle)}")
        resolving_modules.append(module_id)
        try:
            for consumed in module["consumes"]:
                resolve_artifact(consumed)
        finally:
            resolving_modules.pop()
        selected.add(module_id)
        available.update(module["produces"])

    def resolve_artifact(artifact: str) -> None:
        if artifact in available:
            return
        if artifact in resolving_artifacts:
            start = resolving_artifacts.index(artifact)
            cycle = resolving_artifacts[start:] + [artifact]
            raise ComposeError(f"cycle detected in artifacts: {' -> '.join(cycle)}")
        candidates = producers.get(artifact, [])
        if resolving_modules:
            consumer_graph = by_id[resolving_modules[-1]]["graph"]
            same_graph = [
                module for module in candidates
                if module["graph"] == consumer_graph
            ]
            if same_graph:
                candidates = same_graph
        active = [module for module in candidates if module["status"] == "active"]
        planned = [module for module in candidates if module["status"] == "planned"]
        if not allow_planned:
            ready_active = [
                module for module in active
                if set(module["consumes"]).issubset(available)
            ]
            ready_planned = [
                module for module in planned
                if set(module["consumes"]).issubset(available)
            ]
            if not ready_active and ready_planned:
                raise planned_error(ready_planned, artifact)
        if not active and allow_planned:
            active = planned
        if not active:
            if planned:
                raise planned_error(planned, artifact)
            raise ComposeError(f"no module produces required artifact '{artifact}'")

        satisfied = [
            module for module in active
            if set(module["consumes"]).issubset(available)
        ]
        if len(satisfied) == 1:
            chosen = satisfied[0]
        elif len(active) == 1:
            chosen = active[0]
        else:
            ambiguous = satisfied if len(satisfied) > 1 else active
            names = ", ".join(module["id"] for module in ambiguous)
            raise ComposeError(
                f"ambiguous active producers for artifact '{artifact}': {names}; "
                "their consumes are equally satisfied"
            )
        resolving_artifacts.append(artifact)
        try:
            schedule(chosen)
        finally:
            resolving_artifacts.pop()
        if artifact not in available:
            raise ComposeError(
                f"module '{chosen['id']}' did not provide requested artifact '{artifact}'"
            )

    for module_id in forced_list:
        schedule(by_id[module_id])
    resolve_artifact(want)
    return _topological_modules(selected, modules)


def derived_os(modules: Iterable[dict]) -> str:
    values = [module["os"] for module in modules]
    return max(values, key=OS_ORDER.__getitem__) if values else "any"


def build_plan(
    catalog: dict,
    have: Iterable[str],
    want: str,
    forced: Iterable[str] = (),
    *,
    alias: str | None = None,
    allow_planned: bool = False,
) -> dict:
    have_list = list(dict.fromkeys(have))
    modules = resolve_modules(
        catalog, have_list, want, forced, allow_planned=allow_planned
    )
    stages = []
    details = []
    for module in modules:
        stage = module["stage"]
        if stage not in stages:
            stages.append(stage)
        details.append({
            "module": module["id"], "stage": stage,
            "consumes": module["consumes"], "produces": module["produces"],
            "gates": module["gates"], "os": module["os"],
        })
    module_ids = [module["id"] for module in modules]
    summary = (
        f"{', '.join(have_list) or '(nothing)'} -> {want}: "
        f"{' -> '.join(module_ids) or '(already satisfied)'}"
    )
    return {
        "ok": True,
        "alias": alias,
        "have": have_list,
        "want": want,
        "modules": module_ids,
        "module_chain": module_ids,
        "stages": stages,
        "stage_plan": stages,
        "plan": details,
        "os_ceiling": derived_os(modules),
        "summary": summary,
    }


def resolve_alias(
    alias_id: str,
    catalog: dict,
    aliases: dict,
    *,
    allow_planned: bool = False,
) -> dict:
    by_id = {alias["id"]: alias for alias in aliases["aliases"]}
    if alias_id not in by_id:
        raise ComposeError(
            f"unknown alias '{alias_id}'; available: {', '.join(sorted(by_id))}"
        )
    alias = by_id[alias_id]
    if alias["status"] == "planned" and not allow_planned:
        raise ComposeError(
            f"alias '{alias_id}' is planned and cannot be scheduled; "
            "a later wave must flip status to active"
        )
    return build_plan(
        catalog, alias["have"], alias["want"], alias["forced"],
        alias=alias_id, allow_planned=allow_planned,
    )


def _top_level_request(path: Path) -> tuple[dict[str, str], set[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}, set()
    except (OSError, UnicodeError) as exc:
        raise ComposeError(f"request.yaml is unreadable: {exc}") from exc
    values: dict[str, str] = {}
    keys: set[str] = set()
    for number, raw in enumerate(lines, start=1):
        if (
            not raw.strip()
            or raw.lstrip().startswith("#")
            or raw.strip() in {"---", "..."}
            or raw[:1].isspace()
        ):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$", raw)
        if not match:
            raise ComposeError(
                f"request.yaml malformed at line {number}: expected key: value"
            )
        key, value = match.groups()
        if key in keys:
            raise ComposeError(
                f"request.yaml malformed at line {number}: duplicate key '{key}'"
            )
        keys.add(key)
        values[key] = pipeline_ctl._strip_q(
            pipeline_ctl._strip_inline_comment(value)
        )
    return values, keys


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _valid_json(path: Path) -> bool:
    if not _nonempty(path):
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return True


def _glob_file(ws: Path, patterns: Iterable[str]) -> bool:
    return any(
        _nonempty(path)
        for pattern in patterns
        for path in ws.glob(pattern)
    )


def _gate_passed(ws: Path, gate_name: str) -> bool:
    loaded = pipeline_ctl.load_header(ws)
    if loaded is None:
        return False
    graph_ctx = pipeline_ctl.graph_context_for_header(loaded[3])
    gate_stage = None
    checker = None
    for row in graph_ctx["rows"]:
        gate = row.get("gate")
        if gate and gate.get("name") == gate_name:
            gate_stage = str(row["id"])
            checker = gate.get("checker")
            break
    if gate_stage is None or not checker:
        return False
    expected_argv = pipeline_ctl._substitute_checker_argv(checker, ws)
    receipt = ws / ".pipeline" / "gate_checks.jsonl"
    try:
        lines = receipt.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        exit_code = record.get("exit")
        if (
            record.get("gate") == gate_name
            and str(record.get("stage")) == gate_stage
            and isinstance(exit_code, int)
            and not isinstance(exit_code, bool)
            and exit_code == 0
            and workflow_lint._receipt_satisfies_h1(record, expected_argv)
        ):
            return True
    return False


def artifact_present(workspace: str | Path, artifact: str) -> bool:
    ws = Path(workspace)
    request, request_keys = _top_level_request(ws / "request.yaml")
    if artifact == "topic":
        if request.get("topic"):
            return True
        loaded = pipeline_ctl.load_header(ws)
        return bool(loaded and loaded[3].get("topic"))
    if artifact == "constraints":
        return "constraints" in request_keys or _nonempty(ws / "constraints.yaml")
    if artifact == "evidence_pack":
        return (
            _nonempty(ws / "research" / "evidence.md")
            and _valid_json(ws / "research" / "sources.json")
        )
    if artifact == "claims":
        return _nonempty(ws / "claims.yaml")
    if artifact == "design":
        return _nonempty(ws / "01_design.md")
    if artifact == "data":
        return _valid_json(ws / "sim" / "gate_result.json")
    if artifact == "content_draft":
        return _nonempty(ws / "bundle" / "content.raw.md")
    if artifact == "content_md":
        return _nonempty(ws / "bundle" / "content.md")
    if artifact == "form":
        raw = request.get("form")
        if raw:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = ws / candidate
            if _nonempty(candidate):
                return True
        return _glob_file(
            ws, ("output/form_copy.*", "refs/*.hwp", "refs/*.hwpx", "refs/*.docx")
        )
    if artifact == "hwpx":
        return _glob_file(ws, ("output/out*.hwpx", "output/*.hwpx"))
    if artifact == "proof":
        for verdict in (ws / "output").glob("verdict*.json"):
            try:
                payload = json.loads(verdict.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("proof_grade"):
                return True
        return _glob_file(ws, ("output/proof/**/*",))
    if artifact == "verdict_45":
        return _gate_passed(ws, "content_audit")
    if artifact == "verdict_6":
        return _gate_passed(ws, "submission_preflight")
    if artifact == "report":
        return _glob_file(
            ws, ("output/*.*", "refs/*.hwp", "refs/*.hwpx", "refs/*.docx", "refs/*.pdf")
        )
    if artifact == "edit_request":
        return _nonempty(ws / "edit_request.yaml")
    if artifact == "edited_report":
        return _glob_file(ws, ("output/edited*.*", "output/revised*.*"))
    if artifact == "corpus":
        return _glob_file(ws, ("corpus/**/*", "refs/corpus/**/*"))
    if artifact == "form_template":
        return _glob_file(ws, ("form_template.*", "refs/form_template.*"))
    if artifact == "pack_draft":
        return _glob_file(ws, ("packs/draft/*.*", "bundle/packs/draft/*.*"))
    raise ComposeError(f"no workspace probe registered for artifact '{artifact}'")


def validate_intake(workspace: str | Path, plan: dict, catalog: dict) -> None:
    if not plan["modules"]:
        return
    by_id = {module["id"]: module for module in catalog["modules"]}
    first = by_id[plan["modules"][0]]
    missing = [
        artifact for artifact in first["consumes"]
        if not artifact_present(workspace, artifact)
    ]
    if missing:
        receipt_artifacts = sorted(
            set(missing) & {"verdict_45", "verdict_6"}
        )
        receipt_note = ""
        if receipt_artifacts:
            receipt_note = (
                "; gate receipt requirements: exit 0, the registered checker "
                "argv, and a 64-hex stdout_sha256"
            )
        raise ComposeError(
            f"workspace is missing artifacts consumed by first module "
            f"'{first['id']}': {', '.join(missing)}{receipt_note}"
        )


def _mandatory_stage_floor(stages: Iterable[str], graph_ctx: dict) -> list[str]:
    """Project module stages onto the graph without deleting mandatory gates."""
    order = graph_ctx["order"]
    selected = set(stages)
    if graph_ctx["name"] != "build" or not selected:
        return [stage for stage in order if stage in selected]

    indexes = [order.index(stage) for stage in selected]
    first, last = min(indexes), max(indexes)
    for stage in order[first:last + 1]:
        if stage in graph_ctx["gate_names"]:
            selected.add(stage)

    if "2" in selected and "2.5" in order:
        selected.add("2.5")

    stage_five = order.index("5")
    if first <= stage_five <= last:
        selected.update(
            stage for stage in ("5.3", "5.5", "5.7", "6")
            if stage in order
        )
    return [stage for stage in order if stage in selected]


def _unsafe_recompose_stages(old_stages: dict, retained: set[str]) -> list[str]:
    unsafe = []
    for stage, state in old_stages.items():
        if stage in retained:
            continue
        gate = state.get("gate") or {}
        gate_state = gate.get("state") or ""
        stage_state = state.get("status") or ""
        if gate_state not in {"", "pending"} or stage_state not in {
            "pending", "skipped",
        }:
            unsafe.append(stage)
    return unsafe


def apply_plan(
    workspace: str | Path,
    plan: dict,
    catalog: dict,
    *,
    force_recompose: bool = False,
    recompose_reason: str | None = None,
) -> list[str]:
    if force_recompose and not recompose_reason:
        raise ComposeError("--force-recompose requires --reason")
    ws = Path(workspace)
    if not ws.is_dir():
        raise ComposeError(f"workspace does not exist: {ws}")
    loaded = pipeline_ctl.load_header(ws)
    if loaded is None:
        raise ComposeError("PIPELINE.md missing or has no v0.4 header")
    text, start, end, header = loaded
    graph_ctx = pipeline_ctl.graph_context_for_header(header)
    by_id = {module["id"]: module for module in catalog["modules"]}
    selected = [by_id[module_id] for module_id in plan["modules"]]
    graphs = {module["graph"] for module in selected}
    if len(graphs) > 1:
        raise ComposeError(
            f"module plan spans incompatible stage graphs: {', '.join(sorted(graphs))}"
        )
    selected_graph = next(iter(graphs), graph_ctx["name"])
    if selected_graph != graph_ctx["name"]:
        raise ComposeError(
            f"module plan requires graph '{selected_graph}' but workspace uses "
            f"graph '{graph_ctx['name']}'"
        )
    numeric = [stage for stage in plan["stages"] if STAGE_ID_RE.fullmatch(stage)]
    non_stage = [stage for stage in plan["stages"] if stage not in numeric]
    if non_stage:
        raise ComposeError(
            f"active plan contains script mappings that cannot be projected into "
            f"PIPELINE.md: {', '.join(non_stage)}"
        )
    unknown = [stage for stage in numeric if stage not in graph_ctx["order"]]
    if unknown:
        raise ComposeError(
            f"module plan references stages absent from graph '{graph_ctx['name']}': "
            f"{', '.join(unknown)}"
        )

    projected = _mandatory_stage_floor(numeric, graph_ctx)
    old_stages = header.get("stages", {})
    unsafe = _unsafe_recompose_stages(old_stages, set(projected))
    if unsafe and not force_recompose:
        raise ComposeError(
            "recomposition would drop or reset non-pending stage/gate state at "
            f"stages {', '.join(unsafe)}; resolve the gate/state or pass "
            "--force-recompose --reason <operator-reason>"
        )

    updated = pipeline_ctl.now_iso()
    override = None
    if force_recompose:
        override = {
            "action": "force_recompose",
            "at": updated,
            "reason": recompose_reason,
            "affected_stages": unsafe,
        }
        header["compose_provenance"] = json.dumps(
            override, ensure_ascii=False, separators=(",", ":")
        )

    new_stages = {}
    for stage in graph_ctx["order"]:
        if stage not in projected:
            continue
        if stage in old_stages:
            new_stages[stage] = old_stages[stage]
            continue
        gate = None
        if stage in graph_ctx["gate_names"]:
            gate = {
                "name": graph_ctx["gate_names"][stage],
                "state": "pending", "by": None, "at": None,
            }
        new_stages[stage] = {"status": "pending", "gate": gate}
    header["stages"] = new_stages
    header["updated"] = updated
    pipeline_ctl.save_header(ws, text, start, end, header, graph_ctx)
    override_detail = ""
    if override is not None:
        override_detail = (
            f"; force_recompose reason={recompose_reason}; "
            f"affected={','.join(unsafe) or '(none)'}"
        )
    pipeline_ctl.append_event(
        ws, "compose", projected[0] if projected else None,
        f"modules={','.join(plan['modules'])}; stages={','.join(projected)}"
        f"{override_detail}",
    )
    pipeline_ctl.write_heartbeat(ws)
    pipeline_ctl.refresh_handoff(ws, header, graph_ctx=graph_ctx)
    return projected


def _csv(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    else:
        items = [str(item).strip() for item in value]
    return list(dict.fromkeys(item for item in items if item))


def compose_request(
    *,
    have: str | Iterable[str] | None = None,
    want: str | None = None,
    alias: str | None = None,
    forced: str | Iterable[str] | None = None,
    apply: str | Path | None = None,
    dry: bool = False,
    modules_path: str | Path = DEFAULT_MODULES,
    aliases_path: str | Path = DEFAULT_ALIASES,
    force_recompose: bool = False,
    recompose_reason: str | None = None,
) -> dict:
    if dry and apply is not None:
        raise ComposeError("--dry cannot be combined with --apply")
    if force_recompose and apply is None:
        raise ComposeError("--force-recompose requires --apply")
    if force_recompose and not recompose_reason:
        raise ComposeError("--force-recompose requires --reason")
    if recompose_reason and not force_recompose:
        raise ComposeError("--reason requires --force-recompose")
    catalog = load_module_catalog(modules_path)
    aliases = load_alias_catalog(aliases_path, catalog)
    have_list = _csv(have)
    forced_list = _csv(forced)

    if alias and (have_list or want or forced_list):
        raise ComposeError("--alias cannot be combined with --have, --want, or --force")
    if not alias and not have_list and want is None and apply is not None:
        request, _ = _top_level_request(Path(apply) / "request.yaml")
        request_mode = request.get("mode")
        alias_ids = {item["id"] for item in aliases["aliases"]}
        if request_mode in alias_ids:
            alias = request_mode
        else:
            raise ComposeError(
                "no composition specified and request.yaml mode is not a known alias"
            )
    if alias:
        plan = resolve_alias(alias, catalog, aliases)
    else:
        if not have_list or want is None:
            raise ComposeError("provide --alias or both --have and --want")
        plan = build_plan(catalog, have_list, want, forced_list)

    if apply is not None:
        validate_intake(apply, plan, catalog)
        applied_stages = apply_plan(
            apply, plan, catalog,
            force_recompose=force_recompose,
            recompose_reason=recompose_reason,
        )
        plan["stages"] = applied_stages
        plan["stage_plan"] = applied_stages
        plan["applied_workspace"] = str(Path(apply))
    return plan


def render_matrix(
    modules_path: str | Path = DEFAULT_MODULES,
    aliases_path: str | Path = DEFAULT_ALIASES,
) -> str:
    catalog = load_module_catalog(modules_path)
    aliases = load_alias_catalog(aliases_path, catalog)
    rows = []
    for alias in aliases["aliases"]:
        plan = resolve_alias(alias["id"], catalog, aliases, allow_planned=True)
        chain = " -> ".join(plan["modules"]) or "(already satisfied)"
        rows.append(
            f"| {alias['id']} | {alias['status']} | {chain} | "
            f"{plan['os_ceiling']} |"
        )
    return (
        "# Capability matrix\n\n"
        "Generated by pipeline/scripts/compose.py --matrix from the module "
        "and alias manifests. Do not edit this table by hand.\n\n"
        "The OS ceiling is the most restrictive module in the chain: any < "
        "tiered < windows. Tiered chains have a portable floor but need "
        "Windows/Hancom for their highest proof grade.\n\n"
        "| Alias | Status | Module chain | OS ceiling |\n"
        "|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


class ComposeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "error": f"usage error: {message}"}))
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = ComposeArgumentParser(
        description="deterministic typed-module pipeline resolver"
    )
    parser.add_argument("--have", help="comma-separated artifact types already held")
    parser.add_argument("--want", help="target artifact type")
    parser.add_argument("--alias", help="named saved composition")
    parser.add_argument("--force", help="comma-separated modules to include")
    parser.add_argument("--apply", metavar="WORKSPACE", help="write stage plan to PIPELINE.md")
    parser.add_argument(
        "--force-recompose", action="store_true",
        help="override non-pending state-loss protection (requires --reason)",
    )
    parser.add_argument("--reason", help="operator reason for --force-recompose")
    parser.add_argument("--dry", action="store_true", help="resolve without applying")
    parser.add_argument("--manifest", default=str(DEFAULT_MODULES))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument(
        "--matrix", action="store_true", help="emit capability matrix Markdown"
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.matrix:
            if any((args.have, args.want, args.alias, args.force, args.apply, args.dry)):
                raise ComposeError("--matrix cannot be combined with composition options")
            print(render_matrix(args.manifest, args.aliases), end="")
            return 0
        plan = compose_request(
            have=args.have, want=args.want, alias=args.alias, forced=args.force,
            apply=args.apply, dry=args.dry, modules_path=args.manifest,
            aliases_path=args.aliases, force_recompose=args.force_recompose,
            recompose_reason=args.reason,
        )
    except ComposeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(plan["summary"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
