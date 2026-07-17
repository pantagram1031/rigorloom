"""Contract tests for composable entry modes and deterministic resolution."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import compose  # noqa: E402
import pipeline_ctl  # noqa: E402


FULL_CHAIN = [
    "research", "design", "data_sim", "write", "humanize",
    "content_verify", "assemble", "render_proof", "submit_verify",
]


def _run_ctl(*args: str) -> tuple[dict, int]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "pipeline_ctl.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(proc.stdout), proc.returncode


def _module(module_id: str, consumes: list[str], produces: list[str]) -> dict:
    return {
        "id": module_id,
        "consumes": consumes,
        "produces": produces,
        "stage": "1",
        "gates": [],
        "os": "any",
        "status": "active",
    }


def _synthetic_catalog(
    tmp_path: Path, artifacts: list[str], modules: list[dict]
) -> dict:
    path = tmp_path / "modules.yaml"
    path.write_text(
        json.dumps({
            "schema": "synthetic/v1",
            "artifact_types": artifacts,
            "modules": modules,
        }),
        encoding="utf-8",
    )
    return compose.load_module_catalog(path)


def _init_workspace(
    tmp_path: Path, request_text: str, *, mode: str = "autonomous",
) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    form = ws / "refs" / "form.hwpx"
    form.parent.mkdir()
    form.write_bytes(b"synthetic form")
    (ws / "request.yaml").write_text(request_text, encoding="utf-8")
    payload, code = _run_ctl(
        "init", str(ws), "--slug", "synthetic", "--mode", mode,
        "--subject", "test", "--topic", "test topic", "--form", str(form),
    )
    assert code == 0, payload
    return ws


def test_catalog_has_sixteen_modules_and_only_w4_scripts_are_planned():
    catalog = compose.load_module_catalog()
    assert len(catalog["modules"]) == 16
    planned = {
        module["id"] for module in catalog["modules"]
        if module["status"] == "planned"
    }
    assert planned == {"content_extract", "form_extract", "style_extract"}


def test_full_chain_from_topic_is_minimal_and_ordered():
    catalog = compose.load_module_catalog()
    plan = compose.build_plan(catalog, ["topic", "form"], "verdict_6")
    assert plan["modules"] == FULL_CHAIN
    assert plan["stages"] == ["1", "2", "3", "4", "4.5", "5", "6"]
    assert plan["os_ceiling"] == "tiered"


def test_verify_only_given_content_is_short_chain():
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("verify-only", catalog, aliases)
    assert plan["modules"] == ["submit_verify"]
    assert plan["stages"] == ["6"]


def test_planned_module_is_refused_with_clear_name():
    catalog = compose.load_module_catalog()
    with pytest.raises(compose.ComposeError) as caught:
        compose.build_plan(catalog, ["corpus"], "form_template")
    message = str(caught.value)
    assert "planned" in message
    assert "form_extract" in message

    with pytest.raises(compose.ComposeError) as extraction:
        compose.build_plan(catalog, ["report"], "content_md")
    assert "planned" in str(extraction.value)
    assert "content_extract" in str(extraction.value)


def test_cycle_detection_uses_runtime_assembled_fixture(tmp_path):
    left = "left" + "_node"
    right = "right" + "_node"
    artifact_a = "artifact" + "_a"
    artifact_b = "artifact" + "_b"
    catalog = _synthetic_catalog(
        tmp_path,
        [artifact_a, artifact_b],
        [
            _module(left, [artifact_b], [artifact_a]),
            _module(right, [artifact_a], [artifact_b]),
        ],
    )
    with pytest.raises(compose.ComposeError) as caught:
        compose.build_plan(catalog, [], artifact_a)
    assert "cycle detected" in str(caught.value)


def test_ambiguity_error_lists_both_runtime_assembled_producers(tmp_path):
    target = "shared" + "_target"
    first = "producer" + "_one"
    second = "producer" + "_two"
    catalog = _synthetic_catalog(
        tmp_path,
        ["seed_one", "seed_two", target],
        [
            _module(first, ["seed_one"], [target]),
            _module(second, ["seed_two"], [target]),
        ],
    )
    with pytest.raises(compose.ComposeError) as caught:
        compose.build_plan(catalog, [], target)
    message = str(caught.value)
    assert "ambiguous" in message
    assert first in message and second in message


def test_ambiguity_prefers_only_producer_with_satisfied_consumes(tmp_path):
    catalog = _synthetic_catalog(
        tmp_path,
        ["ready", "missing", "target"],
        [
            _module("ready_path", ["ready"], ["target"]),
            _module("missing_path", ["missing"], ["target"]),
        ],
    )
    plan = compose.build_plan(catalog, ["ready"], "target")
    assert plan["modules"] == ["ready_path"]


def test_alias_is_equivalent_to_explicit_have_and_want():
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    saved = compose.resolve_alias("pre-researched", catalog, aliases)
    explicit = compose.build_plan(
        catalog,
        ["topic", "evidence_pack", "claims", "form"],
        "verdict_6",
    )
    assert saved["modules"] == explicit["modules"]
    assert saved["stages"] == explicit["stages"]


def test_w3_aliases_are_active_and_resolve_expected_chains():
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)

    conditions = compose.resolve_alias("conditions-only", catalog, aliases)
    backfill = compose.resolve_alias("backfill", catalog, aliases)

    assert conditions["modules"] == ["topic_select", *FULL_CHAIN]
    assert backfill["modules"] == [
        "claim_extract", "retro_research", "content_verify", "submit_verify",
    ]
    modules = {module["id"]: module for module in catalog["modules"]}
    assert modules["claim_extract"]["stage"].endswith(
        "claims_ledger.py claim_extract"
    )
    assert modules["retro_research"]["gates"] == ["check_claims"]


def test_conditions_only_has_enforced_human_topic_gate_before_research(
    tmp_path,
):
    ws = _init_workspace(
        tmp_path,
        "mode: conditions-only\ntopic: pending human choice\n"
        "form: refs/form.hwpx\n",
        mode="supervised",
    )
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("conditions-only", catalog, aliases)

    applied = compose.apply_plan(ws, plan, catalog)
    header = pipeline_ctl.load_header(ws)[3]
    graph = pipeline_ctl.graph_context_for_header(header)

    assert applied.index("0") < applied.index("1")
    assert header["stages"]["0"]["gate"]["name"] == "topic_pick"
    assert header["stages"]["0"]["gate"]["state"] == "pending"
    assert graph["gate_types"]["0"] == "human"

    advanced, advance_code = _run_ctl(
        "advance", str(ws), "0", "--status", "awaiting_gate",
    )
    assert advance_code == 0, advanced
    resumed, resume_code = _run_ctl("resume", str(ws))
    assert resume_code == 0, resumed
    assert resumed["blocked"] is True
    assert resumed["next_stage"] == "0"
    assert resumed["gate"]["name"] == "topic_pick"


def test_request_mode_intake_failure_lists_missing_first_consumes(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "mode: verify-only\ntopic: test\nform: refs/form.hwpx\n",
    )
    payload, code = _run_ctl("compose", "--apply", str(ws))
    assert code == 2
    assert payload["ok"] is False
    assert "submit_verify" in payload["error"]
    assert "hwpx" in payload["error"]
    assert "verdict_45" in payload["error"]


def test_apply_writes_pipeline_plan_readable_by_pipeline_ctl(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "mode: full-report\ntopic: test topic\nform: refs/form.hwpx\n",
    )
    payload, code = _run_ctl("compose", "--apply", str(ws))
    assert code == 0, payload
    assert payload["modules"] == FULL_CHAIN
    loaded = pipeline_ctl.load_header(ws)
    assert loaded is not None
    assert list(loaded[3]["stages"]) == payload["stages"]
    assert {"2.5", "5.3", "5.5", "5.7"}.issubset(payload["stages"])
    resumed, resume_code = _run_ctl("resume", str(ws))
    assert resume_code == 0, resumed
    assert resumed["next_stage"] == "1"
    assert resumed["blocked"] is False


def test_verify_entry_at_stage_6_does_not_backfill_understanding(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "topic: test topic\nform: refs/form.hwpx\n",
    )
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("verify-only", catalog, aliases)
    assert plan["stages"] == ["6"]

    applied = compose.apply_plan(ws, plan, catalog)

    assert applied == ["6"]
    assert "5.5" not in pipeline_ctl.load_header(ws)[3]["stages"]


def test_assemble_entry_retains_complete_post_assembly_floor(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "topic: test topic\nform: refs/form.hwpx\n",
    )
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("assemble-only", catalog, aliases)

    applied = compose.apply_plan(ws, plan, catalog)

    assert applied == ["5", "5.3", "5.5", "5.7", "6"]


def test_forged_gate_receipt_is_rejected_by_intake(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "topic: test topic\nform: refs/form.hwpx\n",
    )
    (ws / "bundle").mkdir(exist_ok=True)
    (ws / "bundle" / "content.md").write_text(
        "synthetic content\n", encoding="utf-8"
    )
    receipt = ws / ".pipeline" / "gate_checks.jsonl"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(
        '{"gate":"content_audit","stage":"4.5","exit":0}\n',
        encoding="utf-8",
    )

    with pytest.raises(compose.ComposeError) as caught:
        compose.compose_request(alias="assemble-only", apply=ws)

    message = str(caught.value)
    assert "registered checker argv" in message
    assert "64-hex stdout_sha256" in message


def _reject_understanding_gate(ws: Path) -> None:
    loaded = pipeline_ctl.load_header(ws)
    assert loaded is not None
    text, start, end, header = loaded
    header["stages"]["5.5"]["gate"]["state"] = "rejected"
    pipeline_ctl.save_header(
        ws, text, start, end, header,
        pipeline_ctl.graph_context_for_header(header),
    )


def test_recompose_refuses_to_launder_rejected_gate(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "topic: test topic\nform: refs/form.hwpx\n",
    )
    _reject_understanding_gate(ws)
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("verify-only", catalog, aliases)

    with pytest.raises(compose.ComposeError) as caught:
        compose.apply_plan(ws, plan, catalog)

    message = str(caught.value)
    assert "5.5" in message
    assert "resolve the gate/state" in message
    assert "--force-recompose" in message


def test_force_recompose_records_header_provenance(tmp_path):
    ws = _init_workspace(
        tmp_path,
        "topic: test topic\nform: refs/form.hwpx\n",
    )
    _reject_understanding_gate(ws)
    catalog = compose.load_module_catalog()
    aliases = compose.load_alias_catalog(module_catalog=catalog)
    plan = compose.resolve_alias("verify-only", catalog, aliases)

    compose.apply_plan(
        ws, plan, catalog,
        force_recompose=True,
        recompose_reason="operator accepted reset",
    )

    loaded = pipeline_ctl.load_header(ws)
    assert loaded is not None
    provenance = json.loads(loaded[3]["compose_provenance"])
    assert provenance["action"] == "force_recompose"
    assert provenance["reason"] == "operator accepted reset"
    assert provenance["affected_stages"] == ["5.5"]
    assert "force_recompose reason=operator accepted reset" in (
        ws / "events.jsonl"
    ).read_text(encoding="utf-8")


def test_module_stage_contract_matches_build_graph():
    catalog = compose.load_module_catalog()
    modules = {module["id"]: module for module in catalog["modules"]}
    assert modules["assemble"]["stage"] == "5"
    assert modules["assemble"]["gates"] == []
    assert modules["render_proof"]["stage"] == "5"
    assert pipeline_ctl.STAGE_GATE_NAMES["5.3"] == "format_check"


def test_matrix_document_matches_generator():
    assert compose.DEFAULT_MATRIX_DOC.read_text(
        encoding="utf-8"
    ) == compose.render_matrix()
