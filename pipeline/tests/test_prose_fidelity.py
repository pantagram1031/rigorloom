from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
FIDELITY_PATH = ROOT / "pipeline" / "scripts" / "prose_fidelity.py"
HUMANIZE_PATH = ROOT / "pipeline" / "scripts" / "humanization_ctl.py"
SPEC = importlib.util.spec_from_file_location("prose_fidelity", FIDELITY_PATH)
fidelity = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fidelity)


def test_identical_protected_facts_pass_after_style_edit():
    before = "## 결과\n\n[SRC-2] 측정값은 약 18.6%였고 감소하지 않았다. [[EQ latex=\"x=2\"]]"
    after = "## 결과\n\n[SRC-2] 측정값은 약 18.6%였으며 감소하지 않았다. [[EQ latex=\"x=2\"]]"
    result = fidelity.audit_text(before, after)
    assert result["pass"]
    assert result["changes"] == []


def test_number_tag_heading_and_qualifier_changes_fail():
    before = "## 결과\n\n최소 18.6%이며 감소하지 않았다. [[FIG file=\"a.png\"]]"
    after = "## 결론\n\n약 20%이며 감소했다. [[FIG file=\"b.png\"]]"
    result = fidelity.audit_text(before, after)
    assert not result["pass"]
    assert {item["kind"] for item in result["changes"]} >= {"numbers", "tags", "headings", "qualifiers"}


def test_dates_quotes_math_quantifiers_and_causal_markers_are_protected():
    before = '2026-07-11에 “검증 완료”라고 기록했다. 모든 경우에 $x^2$이므로 결과가 증가한다.'
    after = '2026-07-12에 “검토 완료”라고 기록했다. 일부 경우에 $x^3$이므로 결과가 증가한다.'
    result = fidelity.audit_text(before, after)
    kinds = {item["kind"] for item in result["changes"]}
    assert {"dates", "direct_quotes", "inline_math", "quantifiers"} <= kinds


def test_humanization_apply_accepts_safe_change(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    content = bundle / "content.md"
    content.write_text("## 결과\n\n측정값은 18.6%였다.\n", encoding="utf-8")
    prep = subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], capture_output=True, text=True, encoding="utf-8")
    assert prep.returncode == 0, prep.stderr
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({"changes": [{
        "paragraph_id": "p0002", "before": "측정값은 18.6%였다.",
        "after": "측정한 값은 18.6%로 나타났다.", "reasons": ["sentence rhythm"]
    }]}, ensure_ascii=False), encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert applied.returncode == 0, applied.stderr
    assert "측정한 값은 18.6%" in content.read_text(encoding="utf-8")
    assert json.loads((bundle / "prose_fidelity.json").read_text(encoding="utf-8"))["pass"]


def test_humanization_apply_rolls_back_unsafe_change(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    original = "## 결과\n\n측정값은 18.6%였다.\n"
    content = bundle / "content.md"
    content.write_text(original, encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True, capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({"changes": [{
        "paragraph_id": "p0002", "before": "측정값은 18.6%였다.", "after": "측정값은 약 20%였다."
    }]}, ensure_ascii=False), encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert applied.returncode == 1
    assert content.read_text(encoding="utf-8") == original
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_retry"
    assert report["retry_paragraph_ids"] == ["p0002"]


def test_humanization_v2_pass_gate_skips_rewrite(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    original = "## 결과\n\n이미 자연스러운 보고서 문장이다.\n"
    content = bundle / "content.md"
    content.write_text(original, encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "PASS", "skipped": True},
        "changes": [],
    }), encoding="utf-8")

    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert applied.returncode == 0, applied.stderr
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "skipped"
    assert report["gate"] == {"verdict": "PASS", "skipped": True}
    assert content.read_text(encoding="utf-8") == original


def test_humanization_v2_rolls_back_only_unsafe_paragraph(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    content = bundle / "content.md"
    content.write_text(
        "## 결과\n\n첫 문장은 자연스럽게 다듬는다.\n\n측정값은 18.6%였다.\n",
        encoding="utf-8",
    )
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "REWORK", "skipped": False},
        "round": 1,
        "changes": [
            {"paragraph_id": "p0002", "before": "첫 문장은 자연스럽게 다듬는다.",
             "after": "첫 문장을 더 자연스럽게 다듬었다.", "reviewer_verdict": "accept"},
            {"paragraph_id": "p0003", "before": "측정값은 18.6%였다.",
             "after": "측정값은 20%였다.", "reviewer_verdict": "accept"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert applied.returncode == 1
    final = content.read_text(encoding="utf-8")
    assert "첫 문장을 더 자연스럽게 다듬었다." in final
    assert "측정값은 18.6%였다." in final
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_retry"
    assert report["retry_paragraph_ids"] == ["p0003"]
    assert report["fidelity_pass"] is True


def test_humanization_v2_warns_on_overcorrection_and_extreme_hedge(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    content = bundle / "content.md"
    before = "## 결과\n\n측정 결과는 경향을 보였다. 짧은 문장이다.\n"
    content.write_text(before, encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "REWORK", "skipped": False},
        "strength": "light",
        "changes": [{
            "paragraph_id": "p0002",
            "before": "측정 결과는 경향을 보였다. 짧은 문장이다.",
            "after": "측정 결과는 경향을 보였다. 원래 표현을 크게 바꾸어 길고 완전히 다른 설명 문장으로 다시 구성하였다.",
            "reviewer_verdict": "accept",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert applied.returncode == 0, applied.stderr
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["change_rate_warning"] is True
    assert {item["kind"] for item in report["warnings"]} >= {
        "change_rate", "measured_result_softened",
    }


def test_prepare_v2_labels_sections_and_protected_spans(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "content.md").write_text(
        "## 탐구 방법\n\n측정값은 18.6%였다. [SRC-2]\n", encoding="utf-8"
    )

    prepared = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    payload = json.loads(prepared.stdout)

    assert payload["schema"] == "report-pipeline/humanization-v2"
    assert payload["policy"]["detector_is_advisory"] is True
    assert payload["paragraphs"][1]["section"] == "method"
    protected = payload["paragraphs"][1]["protected_spans"]
    assert {item["type"] for item in protected} >= {"numbers", "source_ids"}


def test_round_three_unresolved_review_holds_original(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    original = "## 결론\n\n수정 후보 문장이다.\n"
    content = bundle / "content.md"
    content.write_text(original, encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "REWORK", "skipped": False},
        "round": 3,
        "changes": [{
            "paragraph_id": "p0002", "before": "수정 후보 문장이다.",
            "after": "수정된 후보 문장이다.", "reviewer_verdict": "rollback",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert applied.returncode == 1
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "hold_and_report"
    assert report["retry_paragraph_ids"] == ["p0002"]
    assert content.read_text(encoding="utf-8") == original


def test_v2_rejects_unreviewed_rewriter_output(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    content = bundle / "content.md"
    content.write_text("## 결과\n\n원문이다.\n", encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({
        "schema": "report-pipeline/humanization-changes-v2",
        "gate": {"verdict": "REWORK", "skipped": False},
        "changes": [{
            "paragraph_id": "p0002", "before": "원문이다.", "after": "고친 문장이다."
        }],
    }, ensure_ascii=False), encoding="utf-8")

    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert applied.returncode == 2
    assert "independent reviewer_verdict" in applied.stderr
    assert content.read_text(encoding="utf-8") == "## 결과\n\n원문이다.\n"


def test_local_worker_is_default_humanizer_and_v2_schema_is_valid_json():
    agents = (ROOT / "pipeline" / "references" / "agents.yaml").read_text(encoding="utf-8")
    assert 'humanizer-rewriter: ["agent.worker/high", "mcp.pantadex", "agent.interactive"]' in agents
    assert "reviewer-fidelity:" in agents
    assert "reviewer-naturalness:" in agents
    schema = json.loads(
        (ROOT / "pipeline" / "references" / "humanization_changes_v2.schema.json")
        .read_text(encoding="utf-8")
    )
    assert schema["$id"] == "report-pipeline/humanization-changes-v2"
