"""fill_report.py PROOF 단계(--loop v2) 회귀 테스트 — 오프라인, COM 불필요.

커버:
  - proof verdict shape (tiny fitz-made PDF로 contact_sheet.py 실제 서브프로세스 실행)
  - proof_iter 영속화(임시 fill_events.jsonl 스캔)
  - --proof-needs 스키마 검증
  - derived-anchors precedence(§2: build.yaml 명시 키가 form_profile 유도보다 항상 우선)
  - max_proof_iters 초과 시 escalate_human

`python -m pytest tests/ -q`.
"""
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fill_report as fr  # noqa: E402


def _make_pdf(tmp_path, n_pages=2, name="verify.pdf"):
    import fitz
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((250, 400), f"PAGE {i + 1}", fontsize=24)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


# ── build_proof_rubric ──────────────────────────────────────────────────

def test_build_proof_rubric_has_four_null_binary_checks():
    rubric = fr.build_proof_rubric()
    assert set(rubric.keys()) == {
        "mid_bottom_void", "density_uniformity", "table_proportion",
        "heading_plus_void",
    }
    assert all(v is None for v in rubric.values())


# ── count_proof_iter (persistence via fill_events.jsonl) ────────────────

def test_count_proof_iter_absent_file_returns_zero(tmp_path):
    events = tmp_path / "fill_events.jsonl"
    assert fr.count_proof_iter(events) == 0


def test_count_proof_iter_ignores_non_proof_events(tmp_path):
    events = tmp_path / "fill_events.jsonl"
    lines = [
        {"iter": 1, "ts": time.time(), "verdict": {"converged": False}},
        {"iter": 2, "ts": time.time(), "verdict": {"converged": True}},
    ]
    events.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert fr.count_proof_iter(events) == 0


def test_count_proof_iter_returns_max_seen(tmp_path):
    events = tmp_path / "fill_events.jsonl"
    lines = [
        {"phase": "fill", "iter": 1, "ts": time.time()},
        {"phase": "proof", "proof_iter": 1, "ts": time.time()},
        {"phase": "proof", "proof_iter": 2, "ts": time.time()},
    ]
    events.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert fr.count_proof_iter(events) == 2


def test_count_proof_iter_survives_malformed_lines(tmp_path):
    events = tmp_path / "fill_events.jsonl"
    events.write_text(
        json.dumps({"phase": "proof", "proof_iter": 1}) + "\n"
        + "not json at all\n"
        + json.dumps({"phase": "proof", "proof_iter": 3}) + "\n",
        encoding="utf-8",
    )
    assert fr.count_proof_iter(events) == 3


# ── validate_proof_needs / load_proof_needs schema ───────────────────────

def test_validate_proof_needs_accepts_rewrite_para():
    needs = [{"type": "rewrite_para", "anchor": "Ⅰ. 서 론",
              "delta_lines": -2, "reason": "too long"}]
    ok, reason = fr.validate_proof_needs(needs)
    assert ok is True
    assert reason is None


def test_validate_proof_needs_accepts_resize_table():
    needs = [{"type": "resize_table", "index": 1, "cols": "10,16,12,9,10,43"}]
    ok, reason = fr.validate_proof_needs(needs)
    assert ok is True


def test_validate_proof_needs_rejects_non_list():
    ok, reason = fr.validate_proof_needs({"type": "rewrite_para"})
    assert ok is False
    assert reason


def test_validate_proof_needs_rejects_empty_list():
    ok, reason = fr.validate_proof_needs([])
    assert ok is False


def test_validate_proof_needs_rejects_unknown_type():
    ok, reason = fr.validate_proof_needs([{"type": "delete_everything"}])
    assert ok is False
    assert "type" in reason


def test_validate_proof_needs_rejects_missing_rewrite_para_fields():
    ok, reason = fr.validate_proof_needs([{"type": "rewrite_para", "anchor": "x"}])
    assert ok is False


def test_validate_proof_needs_rejects_bad_cols_format():
    ok, reason = fr.validate_proof_needs(
        [{"type": "resize_table", "index": 0, "cols": "10,abc,12"}])
    assert ok is False


def test_load_proof_needs_missing_file_dies(tmp_path):
    with pytest.raises(SystemExit) as ei:
        fr.load_proof_needs(tmp_path / "nope.json")
    assert ei.value.code == 1


def test_load_proof_needs_bad_schema_dies(tmp_path):
    p = tmp_path / "needs.json"
    p.write_text(json.dumps([{"type": "bogus"}]), encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        fr.load_proof_needs(p)
    assert ei.value.code == 1


def test_load_proof_needs_valid_roundtrips(tmp_path):
    p = tmp_path / "needs.json"
    needs = [{"type": "rewrite_para", "anchor": "A", "delta_lines": 1, "reason": "r"}]
    p.write_text(json.dumps(needs, ensure_ascii=False), encoding="utf-8")
    loaded = fr.load_proof_needs(p)
    assert loaded == needs


# ── run_proof_phase (real contact_sheet.py subprocess, tiny fitz PDF) ───

def test_run_proof_phase_shape(tmp_path):
    pdf = _make_pdf(tmp_path, n_pages=2)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"

    frag = fr.run_proof_phase(pdf, out_dir, events_path,
                               max_proof_iters=3, proof_needs_path=None)

    assert frag["phase"] == "proof"
    assert frag["proof_iter"] == 1
    assert isinstance(frag["contact_sheets"], list) and frag["contact_sheets"]
    assert all(os.path.exists(s) for s in frag["contact_sheets"])
    assert set(frag["rubric"].keys()) == {
        "mid_bottom_void", "density_uniformity", "table_proportion",
        "heading_plus_void",
    }
    assert all(v is None for v in frag["rubric"].values())
    assert frag["status"] == "awaiting_judge"

    # event appended
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["phase"] == "proof"
    assert ev["proof_iter"] == 1


def test_run_proof_phase_increments_iter_across_calls(tmp_path):
    pdf = _make_pdf(tmp_path, n_pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"

    frag1 = fr.run_proof_phase(pdf, out_dir, events_path, 3, None)
    frag2 = fr.run_proof_phase(pdf, out_dir, events_path, 3, None)
    assert frag1["proof_iter"] == 1
    assert frag2["proof_iter"] == 2


def test_run_proof_phase_with_needs_records_needs_and_status(tmp_path):
    pdf = _make_pdf(tmp_path, n_pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"
    needs_path = tmp_path / "needs.json"
    needs = [{"type": "rewrite_para", "anchor": "A", "delta_lines": -1, "reason": "r"}]
    needs_path.write_text(json.dumps(needs, ensure_ascii=False), encoding="utf-8")

    frag = fr.run_proof_phase(pdf, out_dir, events_path, 3, needs_path)
    assert frag["needs"] == needs
    assert frag["status"] == "needs_applied"

    ev = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert ev["needs"] == needs
    assert ev["proof_iter"] == 1


def test_run_proof_phase_bad_needs_schema_dies(tmp_path):
    pdf = _make_pdf(tmp_path, n_pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"
    needs_path = tmp_path / "needs.json"
    needs_path.write_text(json.dumps([{"type": "nonsense"}]), encoding="utf-8")

    with pytest.raises(SystemExit) as ei:
        fr.run_proof_phase(pdf, out_dir, events_path, 3, needs_path)
    assert ei.value.code == 1
    # bad needs must not be appended to the event log.
    assert not events_path.exists() or events_path.read_text(encoding="utf-8") == ""


def test_run_proof_phase_escalates_when_over_max(tmp_path):
    pdf = _make_pdf(tmp_path, n_pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"

    # pre-seed 3 prior proof events so the next call is proof_iter 4.
    with open(events_path, "a", encoding="utf-8") as f:
        for n in range(1, 4):
            f.write(json.dumps({"phase": "proof", "proof_iter": n, "ts": time.time()}) + "\n")

    frag = fr.run_proof_phase(pdf, out_dir, events_path, max_proof_iters=3,
                               proof_needs_path=None)
    assert frag["proof_iter"] == 4
    assert frag["status"] == "escalate_human"
    assert "reason" in frag
    assert "4" in frag["reason"]


# ── run_contact_sheet (crash / malformed-output handling) ───────────────

class _FakeCompletedProcess:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_contact_sheet_dies_on_nonzero_exit_with_empty_stdout(tmp_path, monkeypatch):
    """A crashed contact_sheet.py with empty stdout used to parse as {} and be
    treated as success. It must now die loudly instead."""
    def fake_run(cmd, capture_output, env):
        return _FakeCompletedProcess(returncode=1, stdout=b"", stderr=b"boom: traceback here")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as ei:
        fr.run_contact_sheet(tmp_path / "verify.pdf", tmp_path / "out")
    assert ei.value.code == 2
    assert ei.value.code != 0


def test_run_contact_sheet_dies_on_missing_required_keys(tmp_path, monkeypatch):
    """Exit 0 but the JSON payload lacks pages/sheets/cell_size must also die,
    not be silently treated as a valid (keyless) success payload."""
    def fake_run(cmd, capture_output, env):
        payload = json.dumps({"ok": True, "pages": 2})  # sheets/cell_size missing
        return _FakeCompletedProcess(returncode=0, stdout=payload.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as ei:
        fr.run_contact_sheet(tmp_path / "verify.pdf", tmp_path / "out")
    assert ei.value.code == 2


def test_run_contact_sheet_succeeds_with_all_required_keys(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, env):
        payload = json.dumps({"ok": True, "pages": 2, "sheets": ["a.png"], "cell_size": [100, 100]})
        return _FakeCompletedProcess(returncode=0, stdout=payload.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    result = fr.run_contact_sheet(tmp_path / "verify.pdf", tmp_path / "out")
    assert result["pages"] == 2
    assert result["sheets"] == ["a.png"]


# ── derived-anchors precedence (§2) ──────────────────────────────────────

def test_read_tidy_anchors_with_source_explicit_build_yaml_wins(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text(
        'tidy_blank_before:\n  - "명시 앵커"\n', encoding="utf-8")
    profile = tmp_path / "form_profile.json"
    profile.write_text(json.dumps({"anchors": ["유도 앵커1", "유도 앵커2"]},
                                   ensure_ascii=False), encoding="utf-8")

    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(profile))
    assert before == ["명시 앵커"]
    assert derived is None  # explicit key present -> not derived
    assert keep_map is None


def test_read_tidy_anchors_with_source_derives_from_profile_when_absent(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    profile = tmp_path / "form_profile.json"
    profile.write_text(json.dumps({"anchors": ["유도 앵커1", "유도 앵커2"]},
                                   ensure_ascii=False), encoding="utf-8")

    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(profile))
    assert before == ["유도 앵커1", "유도 앵커2"]
    assert after is None
    assert derived == ["유도 앵커1", "유도 앵커2"]
    # Rule 1: 프로파일에 anchors_blanks_before가 없으면(구 프로파일) keep_n=1 기본값.
    assert keep_map == {"유도 앵커1": 1, "유도 앵커2": 1}


def test_read_tidy_anchors_with_source_derives_keep_map_from_blanks_before(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    profile = tmp_path / "form_profile.json"
    profile.write_text(json.dumps({
        "anchors": ["유도 앵커1", "유도 앵커2"],
        "anchors_blanks_before": {"유도 앵커1": 3},
    }, ensure_ascii=False), encoding="utf-8")

    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(profile))
    # anchors_blanks_before에 있는 anchor는 그 값, 없는 anchor는 1(기본값).
    assert keep_map == {"유도 앵커1": 3, "유도 앵커2": 1}


def test_derive_keep_map_anchor_after_filled_section_collapses_to_one(tmp_path):
    # 폼 앵커 순서: [제목필드, 요약, 탐구방법]. content.md에 "배경지식"이라는
    # SECTION은 없지만 "요약"은 채워질 예정 -> "탐구방법" 앞 여백은 "요약"
    # 섹션의 소비된 writing-room이므로 1로 접힌다.
    anchors = ["제목필드", "요약", "탐구방법"]
    blanks_before = {"제목필드": 18, "요약": 18, "탐구방법": 15}
    section_anchors = ["요약", "탐구방법"]  # content.md에 채워질 SECTION들.
    keep_map = fr._derive_keep_map(anchors, blanks_before, section_anchors)
    # "요약" 앞의 이전 form anchor는 "제목필드"(채워질 섹션 아님) -> baseline 유지.
    assert keep_map["요약"] == 18
    # "탐구방법" 앞의 이전 form anchor는 "요약"(채워질 섹션) -> 1로 접힘.
    assert keep_map["탐구방법"] == 1


def test_derive_keep_map_anchor_after_unfilled_structure_keeps_baseline(tmp_path):
    # 이전 form anchor가 content.md SECTION과 매치되지 않으면(제목페이지 필드 등
    # 구조적 앵커) baseline(anchors_blanks_before, 없으면 1) 그대로 보존.
    anchors = ["이름", "학번", "대수 탐구 기록지 요약"]
    blanks_before = {"이름": 2, "학번": 2, "대수 탐구 기록지 요약": 18}
    section_anchors = ["대수 탐구 기록지 요약"]  # "이름"/"학번"은 SECTION이 아님.
    keep_map = fr._derive_keep_map(anchors, blanks_before, section_anchors)
    assert keep_map["학번"] == 2  # 이전 anchor "이름"은 채워질 섹션이 아님.
    assert keep_map["대수 탐구 기록지 요약"] == 18  # 이전 anchor "학번"도 아님.


def test_derive_keep_map_no_section_anchors_falls_back_to_baseline(tmp_path):
    # section_anchors가 None/빈 리스트면(content.md 못 읽음 등) 기존 동작과
    # 동일하게 전부 baseline(anchors_blanks_before, 없으면 1).
    anchors = ["a", "b"]
    blanks_before = {"a": 5}
    assert fr._derive_keep_map(anchors, blanks_before, None) == {"a": 5, "b": 1}
    assert fr._derive_keep_map(anchors, blanks_before, []) == {"a": 5, "b": 1}


def test_read_tidy_anchors_with_source_keep_map_collapses_after_filled_section(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    profile = tmp_path / "form_profile.json"
    profile.write_text(json.dumps({
        "anchors": ["요약", "탐구방법"],
        "anchors_blanks_before": {"요약": 18, "탐구방법": 15},
    }, ensure_ascii=False), encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text(
        "---\ntitle: t\n---\n\n## SECTION: 요약\n\n내용입니다.\n", encoding="utf-8")

    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(profile), str(content))
    assert before == ["요약", "탐구방법"]
    # "요약"은 content.md에서 채워지지만 그 앞엔 이전 form anchor가 없음(맨 처음)
    # -> baseline 유지.
    assert keep_map["요약"] == 18
    # "탐구방법" 앞의 이전 form anchor "요약"이 채워질 섹션 -> 1로 접힘.
    assert keep_map["탐구방법"] == 1


def test_read_tidy_anchors_with_source_keep_map_backward_compat_without_content(tmp_path):
    # content_path를 안 넘기면(기존 호출자) 기존 동작 그대로 — baseline 전부.
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    profile = tmp_path / "form_profile.json"
    profile.write_text(json.dumps({
        "anchors": ["요약", "탐구방법"],
        "anchors_blanks_before": {"요약": 18, "탐구방법": 15},
    }, ensure_ascii=False), encoding="utf-8")

    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(profile))
    assert keep_map == {"요약": 18, "탐구방법": 15}


def test_read_tidy_anchors_with_source_no_profile_no_build_yaml_keys(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(str(build_yaml), None)
    assert (before, after, derived, keep_map) == (None, None, None, None)


def test_read_tidy_anchors_with_source_missing_profile_file_is_none(tmp_path):
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text("base_pt: 10\n", encoding="utf-8")
    before, after, derived, keep_map = fr.read_tidy_anchors_with_source(
        str(build_yaml), str(tmp_path / "does_not_exist.json"))
    assert (before, after, derived, keep_map) == (None, None, None, None)


# ── merge_proof_fragment (shared-miss #5: converged:true + escalate_human) ─
#
# 옛 코드 경로는 mode_loop에서 plain ``out_obj.update(proof_frag)``였다:
# phase-1이 converged:True로 끝난 verdict 위에 proof 단계의
# status:"escalate_human"이 그대로 얹혀 자기모순 쌍(converged:true +
# escalate_human)이 방출됐고, rigorloom verdict_schema.py가 read-time에
# HARD finding으로 거부했다(sambal + pendulum 실워크스페이스 2건).

RIGORLOOM_SCHEMA = os.path.join(
    os.path.expanduser("~"), "dev", "rigorloom", "pipeline", "scripts",
    "verdict_schema.py")


def _load_rigorloom_schema():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rigorloom_verdict_schema", RIGORLOOM_SCHEMA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _phase1_converged_verdict():
    """finalize_loop_verdict가 converged로 끝났을 때의 핵심 필드 형태."""
    return {
        "converged": True,
        "state": "converged",
        "escalate": False,
        "iterations": 2,
        "page_count": 4,
        "reason": "converged: pass + pages-in-window + figs>=min + checks clean",
    }


def test_merge_proof_fragment_escalation_clears_converged():
    out_obj = _phase1_converged_verdict()
    frag = {"phase": "proof", "proof_iter": 4, "status": "escalate_human",
            "reason": "proof_iter 4 > max_proof_iters 3 — 수렴 실패, 사람 검토 필요"}
    merged = fr.merge_proof_fragment(out_obj, frag)
    # 내부 일관성: escalate_human이면 converged는 절대 True일 수 없다.
    assert merged["status"] == "escalate_human"
    assert merged["converged"] is False
    assert merged["escalate"] is True
    # phase-1 수렴 기록은 별도 필드로 보존(정보 손실 없음).
    assert merged["phase1_converged"] is True
    assert "수렴 실패" in merged["reason"]


def test_merge_proof_fragment_non_escalation_keeps_converged():
    out_obj = _phase1_converged_verdict()
    frag = {"phase": "proof", "proof_iter": 1, "status": "awaiting_judge"}
    merged = fr.merge_proof_fragment(out_obj, frag)
    assert merged["converged"] is True
    assert merged["status"] == "awaiting_judge"
    assert merged["escalate"] is False
    assert "phase1_converged" not in merged


def test_merge_proof_fragment_real_over_max_frag(tmp_path):
    """실제 run_proof_phase가 max 초과로 escalate_human 조각을 낸 뒤 병합해도
    verdict가 내부 일관성을 유지해야 한다(mode_loop 병합 지점과 동일 경로)."""
    pdf = _make_pdf(tmp_path, n_pages=1)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    events_path = out_dir / "fill_events.jsonl"
    with open(events_path, "a", encoding="utf-8") as f:
        for n in range(1, 4):
            f.write(json.dumps({"phase": "proof", "proof_iter": n,
                                "ts": time.time()}) + "\n")

    frag = fr.run_proof_phase(pdf, out_dir, events_path, max_proof_iters=3,
                               proof_needs_path=None)
    assert frag["status"] == "escalate_human"

    merged = fr.merge_proof_fragment(_phase1_converged_verdict(), frag)
    assert merged["converged"] is False
    assert merged["escalate"] is True
    assert merged["phase1_converged"] is True
    assert merged["contact_sheets"]  # proof 산출물은 그대로 유지.


@pytest.mark.skipif(not os.path.exists(RIGORLOOM_SCHEMA),
                    reason="rigorloom repo not present on this machine")
def test_merged_escalation_verdict_passes_rigorloom_validator(tmp_path):
    schema = _load_rigorloom_schema()
    frag = {"phase": "proof", "proof_iter": 4, "status": "escalate_human",
            "reason": "over max"}

    # 옛 경로(plain dict.update) 재현: validator가 모순 쌍을 HARD로 잡는다.
    old_shape = dict(_phase1_converged_verdict())
    old_shape.update(frag)
    old_findings = schema.contradiction_findings(old_shape)
    assert old_findings and old_findings[0]["code"] == "verdict_contradiction"

    # 새 writer 출력은 파일 기준으로도 깨끗해야 한다.
    merged = fr.merge_proof_fragment(_phase1_converged_verdict(), frag)
    vpath = tmp_path / "verdict.json"
    vpath.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    assert schema.validate_verdict_file(vpath) == []
