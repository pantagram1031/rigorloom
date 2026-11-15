from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[3]
MODULE_ROOT = Path(__file__).parents[1]
FIDELITY_PATH = MODULE_ROOT / "scripts" / "prose_fidelity.py"
HUMANIZE_PATH = MODULE_ROOT / "scripts" / "humanization_ctl.py"
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


def _kinds(before: str, after: str) -> list[str]:
    return [change["kind"] for change in fidelity.audit_text(before, after)["changes"]]


def test_direction_flip_with_same_numbers_is_caught():
    assert _kinds("반응 시간이 약 18.6% 감소했다.", "반응 시간이 약 18.6% 증가했다.") == ["direction_words"]
    assert _kinds("값이 더 높은 편이다.", "값이 더 낮은 편이다.") == ["direction_words"]
    assert _kinds("The score rose by 3%.", "The score fell by 3%.") == ["direction_words"]


def test_direction_stems_ignore_words_that_only_contain_them():
    # 목적은 contains 적은 and 오늘 contains 늘; neither is a direction word.
    assert _kinds("연구의 목적은 분명하다.", "연구의 목적이 분명하다.") == []
    assert _kinds("오늘 측정했다.", "금일 측정했다.") == []
    assert _kinds("Furthermore, it held.", "Moreover, it held.") == []


def test_numbered_heading_rename_is_caught_but_list_sentences_are_not():
    assert _kinds("3. 실험 방법", "3. 연구 설계") == ["headings"]
    assert _kinds("1. 먼저 시료를 준비했다.", "1. 우선 시료를 준비했다.") == []


def test_tokens_no_longer_match_inside_other_words():
    # "Really" contains "all", 계약서 contains 약, 이상하다 contains 이상.
    assert _kinds("People miss most.", "People miss most. Really.") == []
    assert _kinds("계약서를 정리했다.", "계약서를 요약했다.") == []
    assert _kinds("결과가 이상하다.", "결과가 특이하다.") == []


def test_hedges_bounds_and_english_negation_still_caught():
    assert _kinds("약 30명이 참여했다.", "30명이 참여했다.") == ["qualifiers"]
    assert _kinds("30명 이상이 참여했다.", "30명이 참여했다.") == ["qualifiers"]
    assert _kinds("What it cannot do reliably.", "What it can do reliably.") == ["qualifiers"]
    assert _kinds("It didn’t hold.", "It did hold.") == ["qualifiers"]
    assert _kinds("Nothing changed.", "Something changed.") == ["qualifiers"]
    assert _kinds("No change was seen.", "A change was seen.") == ["qualifiers"]


def test_known_strictness_is_deliberate():
    """These reverts are on purpose: the checker would rather look twice than miss a flip.

    Change one of them only together with humanization_contract.md, not as a "bug fix".
    """
    # Direction nouns match as substrings, so 방향상 counts as 향상.
    assert _kinds("설계 방향상 문제가 있다.", "설계 측면에서 문제가 있다.") == ["direction_words"]
    # Everyday comparatives are protected too: 많은 -> 여러, "what is more" -> "also".
    assert _kinds("많은 사람이 왔다.", "여러 사람이 왔다.") == ["direction_words"]
    assert _kinds("What is more, it held.", "Also, it held.") == ["direction_words"]
    # A short numbered line without end punctuation is a heading, list items included.
    assert _kinds("1. 시료를 준비", "1. 시료 준비하기") == ["headings"]


def test_bound_after_spaced_unit_is_a_known_gap():
    """이상/이하 count only when the unit is attached: '30명 이상', not '30 명 이상'."""
    assert _kinds("참가자는 30명 이상이다.", "참가자는 30명이다.") == ["qualifiers"]
    assert _kinds("참가자는 30 명 이상이다.", "참가자는 30 명이다.") == []
