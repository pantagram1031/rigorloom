"""오프라인 회귀 테스트 — 한글(COM) 없이 순수 함수만 검증.

감사(BUG7)에서 회귀 방어가 0이라 지적됨. build_report의 ops 방출, eqn 변환,
_validate_ops 스키마 검사를 고정한다. `python -m pytest tests/ -q`.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_report as br          # noqa: E402
import com_backend as cb           # noqa: E402
from eqn import latex_to_hwpeqn, hwpeqn_sanity_check  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "regen-brake")
CONTENT = os.path.join(FIX, "content.md")
EXPECTED = os.path.join(FIX, "expected_ops.json")


def _build():
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    ops = br.build_ops(meta, secs, FIX)
    for o in ops:                      # 절대 그림 경로 → basename (머신 독립)
        if o.get("op") == "insert_picture":
            o["path"] = os.path.basename(o["path"])
    return meta, secs, ops


# ── build_report ops 방출 골든 ──────────────────────────────────────────

def test_ops_match_baseline():
    _, secs, ops = _build()
    expected = json.load(open(EXPECTED, encoding="utf-8"))
    assert [s["anchor"] for s in secs] == expected["anchors"]
    assert ops == expected["ops"]


def test_counts():
    _, secs, ops = _build()
    counts = {
        "sections": len(secs),
        "eq": sum(1 for o in ops if o["op"] == "insert_equation"),
        "fig": sum(1 for o in ops if o["op"] == "insert_picture"),
        "table": sum(1 for o in ops if o["op"] == "insert_table"),
    }
    assert counts == {"sections": 6, "eq": 3, "fig": 3, "table": 1}


# ── eqn 변환 배터리 ─────────────────────────────────────────────────────

def test_eqn_frac_sqrt():
    assert "over" in latex_to_hwpeqn(r"\frac{a}{b}")[0]
    assert "sqrt" in latex_to_hwpeqn(r"\sqrt{x}")[0]


def test_eqn_matrix_rowsep():   # BUG1: 행 구분 \\ → #
    out, _ = latex_to_hwpeqn(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
    assert "#" in out
    assert "\\\\" not in out and "\\" not in out
    ok, _ = hwpeqn_sanity_check(out)
    assert ok


def test_eqn_matrix_rowsep_compact_no_spaces():
    # Regression: row separator directly abutting the next cell's letter
    # (no space after \\) used to be swallowed by the double-backslash
    # de-escape normalizer BEFORE _matrix_rowsep() ran, since the normalizer's
    # lookahead treats "\\c" (letter after \\) as an over-escaped command and
    # folds it to "\c" — leaving nothing for _matrix_rowsep to recognize as a
    # row break. Both rows (both letters on each side) must survive, for both
    # bmatrix and pmatrix.
    for env in ("bmatrix", "pmatrix"):
        out, warnings = latex_to_hwpeqn(
            "\\begin{%s}a&b\\\\c&d\\end{%s}" % (env, env))
        assert "#" in out, f"{env}: missing row separator in {out!r}"
        assert "a" in out and "b" in out and "c" in out and "d" in out
        assert not warnings, f"{env}: unexpected warnings {warnings}"
        ok, msg = hwpeqn_sanity_check(out)
        assert ok, f"{env}: sanity check failed: {msg} ({out!r})"


def test_eqn_cases():
    out, _ = latex_to_hwpeqn(r"\begin{cases} x & a \\ y & b \end{cases}")
    assert "#" in out


def test_sanity_fails_on_unsupported():   # BUG1: 미지원 토큰 FAIL
    out, _ = latex_to_hwpeqn(r"\binom{n}{k}")
    ok, msg = hwpeqn_sanity_check(out)
    assert not ok


def test_sanity_fails_on_leftover_backslash():
    ok, _ = hwpeqn_sanity_check(r"a \\ b")
    assert not ok


# ── _validate_ops 스키마 검사 (BUG4) ────────────────────────────────────

def test_validate_ops_accepts_wrapper_and_list():
    good = [{"op": "goto_text", "text": "X"},
            {"op": "insert_text", "text": "hi"}]
    assert cb._validate_ops(good) == good
    assert cb._validate_ops({"schema": 1, "ops": good}) == good


def test_validate_ops_rejects_unknown_op():
    with pytest.raises(SystemExit):
        cb._validate_ops([{"op": "no_such_op"}])


def test_validate_ops_rejects_missing_required_key():
    with pytest.raises(SystemExit):
        cb._validate_ops([{"op": "replace_all", "find": "x"}])  # replace 없음


def test_validate_ops_rejects_non_dict_item():
    with pytest.raises(SystemExit):
        cb._validate_ops(["not a dict"])


# ── delete_texts (build.yaml) → find_delete ops ─────────────────────────

def _write_build_yaml(tmp_path, extra_lines):
    p = tmp_path / "build.yaml"
    p.write_text(
        "base_pt: 10\ncaption_pt: 9\n" + "\n".join(extra_lines) + "\n",
        encoding="utf-8",
    )
    return p


def test_parse_build_yaml_delete_texts_block_list(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "delete_texts:",
        '  - "안내문 1, 콤마 포함"',
        '  - "안내문 2"',
    ])
    cfg = br.parse_build_yaml(p)
    assert cfg["delete_texts"] == ["안내문 1, 콤마 포함", "안내문 2"]


def test_delete_texts_absent_is_zero_ops():
    _, secs, ops = _build()
    assert not any(o["op"] == "find_delete" for o in ops)


def test_delete_texts_emits_find_delete_ops_in_correct_position(tmp_path):
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["delete_texts"] = ["안내문 A", "안내문 B"]
    ops = br.build_ops(meta, secs, FIX)

    find_delete_ops = [o for o in ops if o["op"] == "find_delete"]
    assert len(find_delete_ops) == 2
    assert [o["text"] for o in find_delete_ops] == ["안내문 A", "안내문 B"]
    for o in find_delete_ops:
        assert o["all"] is True
        assert o["required"] is False

    # 위치: delete_ctrls(초록 표 제거, abstract off일 때) 바로 뒤, 섹션 삽입
    # (goto_text/insert_text 등) 이전에 와야 한다.
    op_names = [o["op"] for o in ops]
    fd_idx = op_names.index("find_delete")
    first_section_op_idx = min(
        i for i, o in enumerate(ops)
        if o["op"] in ("goto_text", "insert_blank_before")
    )
    assert fd_idx < first_section_op_idx


def test_delete_texts_after_abstract_delete_ctrls(tmp_path):
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["abstract"] = "false"
    meta["delete_texts"] = ["안내문 A"]
    ops = br.build_ops(meta, secs, FIX)
    op_names = [o["op"] for o in ops]
    assert op_names.index("delete_ctrls") < op_names.index("find_delete")


def test_merge_meta_carries_delete_texts():
    merged = br.merge_meta({}, {"delete_texts": ["x", "y"]})
    assert merged["delete_texts"] == ["x", "y"]


def test_merge_meta_no_delete_texts_key_when_absent():
    merged = br.merge_meta({}, {})
    assert "delete_texts" not in merged


# ── tidy_blank_before/after (build.yaml) → anchor-targeted blank cleanup ──
# T7: COM 기반 blank-paragraph 정리(delete_blank_before/after COM ops)는 제목
# charPr 오염·문단 병합을 일으켜 폐기됐다. build_report.py는 이제 이 두 키를
# ops로 변환하지 않는다(build_ops에서 zero emission) — 키 자체는 parse_build_yaml/
# merge_meta에서 계속 파싱·병합되어 meta에 남고, 실제 정리는 fill_report.py가
# tidy_hwpx.py(오프라인 XML 편집)로 COM edit 이후 수행한다.

def test_parse_build_yaml_tidy_blank_before_block_list(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "tidy_blank_before:",
        '  - "I.  서론"',
        '  - "II. 본론, 실험"',
    ])
    cfg = br.parse_build_yaml(p)
    assert cfg["tidy_blank_before"] == ["I.  서론", "II. 본론, 실험"]


def test_parse_build_yaml_tidy_blank_after_block_list(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "tidy_blank_after:",
        '  - "그림 1. 캡션"',
    ])
    cfg = br.parse_build_yaml(p)
    assert cfg["tidy_blank_after"] == ["그림 1. 캡션"]


def test_tidy_blank_before_after_absent_is_zero_ops():
    _, secs, ops = _build()
    assert not any(o["op"] in ("delete_blank_before", "delete_blank_after") for o in ops)


def test_tidy_blank_before_emits_no_com_ops():
    """T7 폐기: tidy_blank_before는 더 이상 delete_blank_before/insert_blank_before
    COM op을 만들지 않는다 — fill_report.py가 tidy_hwpx.py로 오프라인 처리한다."""
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["tidy_blank_before"] = ["I.  서론"]
    ops = br.build_ops(meta, secs, FIX)

    op_names = [o["op"] for o in ops]
    assert "delete_blank_before" not in op_names
    # insert_blank_before는 여전히 나올 수 있다(섹션 제목 앞 기본 1개 보장 로직,
    # tidy_blank_before와 무관) — 여기서 금지하는 건 tidy 전용 delete뿐.


def test_tidy_blank_after_emits_no_com_ops():
    """T7 폐기: tidy_blank_after는 더 이상 delete_blank_after COM op을 만들지
    않는다 — fill_report.py가 tidy_hwpx.py로 오프라인 처리한다."""
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["tidy_blank_after"] = ["그림 1. 캡션"]
    ops = br.build_ops(meta, secs, FIX)

    assert not any(o["op"] == "delete_blank_after" for o in ops)


def test_tidy_blank_keys_pass_through_meta_without_ops():
    """tidy_blank_before/after 키 자체는 meta에 남아(merge_meta가 병합) 다음
    단계(fill_report.py)가 읽을 수 있어야 한다 — build_ops만 소비하지 않는다."""
    merged = br.merge_meta({}, {"tidy_blank_before": ["I.  서론"],
                                 "tidy_blank_after": ["그림 1. 캡션"]})
    assert merged["tidy_blank_before"] == ["I.  서론"]
    assert merged["tidy_blank_after"] == ["그림 1. 캡션"]

    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta.update(merged)
    ops = br.build_ops(meta, secs, FIX)
    assert not any(o["op"] in ("delete_blank_before", "delete_blank_after") for o in ops)


def test_collapse_blank_runs_still_emits_standalone_without_tidy_keys():
    """collapse_blank_runs 노브는 tidy_blank_* 없이도 독립적으로 계속 동작한다
    (구 동작 회귀 방지 — tidy_blank_*는 대체 옵션이지 필수 전제조건이 아님)."""
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["collapse_blank_runs"] = "true"
    ops = br.build_ops(meta, secs, FIX)
    assert any(o["op"] == "collapse_empty_paragraphs" for o in ops)


def test_collapse_blank_runs_absent_emits_nothing():
    _, secs, ops = _build()
    assert not any(o["op"] == "collapse_empty_paragraphs" for o in ops)


def test_merge_meta_carries_tidy_blank_before_and_after():
    merged = br.merge_meta({}, {"tidy_blank_before": ["a"], "tidy_blank_after": ["b"]})
    assert merged["tidy_blank_before"] == ["a"]
    assert merged["tidy_blank_after"] == ["b"]


def test_merge_meta_no_tidy_blank_keys_when_absent():
    merged = br.merge_meta({}, {})
    assert "tidy_blank_before" not in merged
    assert "tidy_blank_after" not in merged


# ── _resolve_post_field_pos (BUG1: hyperlink tail-loss position math) ──────
# COM 자체는 유닛 테스트 불가(실제 GetPos()는 살아있는 한글 인스턴스 필요) —
# 여기서는 "어느 좌표가 신뢰 가능한가"라는 순수 로직만 고정한다. e2e(실제
# insert_hyperlink 8자 유실 재현)는 Stage-5 shepherd가 라이브 한글로 검증.

def test_resolve_post_field_pos_returns_post_field_value():
    pre = (0, 3, 40)   # 필드 삽입 전 스냅샷(스테일 — 그대로 쓰면 BUG1 재현)
    post = (0, 3, 48)  # InsertHyperlink 실행 후 재획득한 진짜 끝
    assert cb._resolve_post_field_pos(pre, post) == post


def test_resolve_post_field_pos_never_returns_pre_field_value():
    pre = (0, 5, 12)
    post = (0, 5, 20)
    result = cb._resolve_post_field_pos(pre, post)
    assert result != pre


# ── page_break_before (build.yaml, T11) → op emission ──────────────────────

def test_parse_build_yaml_page_break_before_block_list(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "page_break_before:",
        '  - "I.  서론"',
    ])
    cfg = br.parse_build_yaml(p)
    assert cfg["page_break_before"] == ["I.  서론"]


def test_page_break_before_absent_is_zero_ops():
    _, secs, ops = _build()
    assert not any(o["op"] == "page_break_before" for o in ops)


def test_page_break_before_emits_ops_in_correct_position(tmp_path):
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["delete_texts"] = ["안내문 A"]
    meta["page_break_before"] = ["I.  서론"]
    ops = br.build_ops(meta, secs, FIX)

    pb_ops = [o for o in ops if o["op"] == "page_break_before"]
    assert len(pb_ops) == 1
    assert pb_ops[0]["text"] == "I.  서론"
    assert pb_ops[0]["required"] is False

    # 위치: delete_texts(find_delete) 바로 뒤, 섹션 삽입(goto_text/insert_blank_before)
    # 이전에 와야 한다.
    op_names = [o["op"] for o in ops]
    fd_idx = op_names.index("find_delete")
    pb_idx = op_names.index("page_break_before")
    first_section_op_idx = min(
        i for i, o in enumerate(ops)
        if o["op"] in ("goto_text", "insert_blank_before")
    )
    assert fd_idx < pb_idx < first_section_op_idx


def test_merge_meta_carries_page_break_before():
    merged = br.merge_meta({}, {"page_break_before": ["I.  서론"]})
    assert merged["page_break_before"] == ["I.  서론"]


def test_merge_meta_no_page_break_before_key_when_absent():
    merged = br.merge_meta({}, {})
    assert "page_break_before" not in merged


def test_validate_ops_accepts_page_break_before():
    ops = [{"op": "page_break_before", "text": "I.  서론"}]
    assert cb._validate_ops(ops) == ops


def test_validate_ops_rejects_page_break_before_missing_text():
    with pytest.raises(SystemExit):
        cb._validate_ops([{"op": "page_break_before"}])


# ── fake-Hwp COM harness — records HAction.Run/Run() action names ──────────
# 실제 GetPos()/find() 등은 라이브 한글 인스턴스가 필요해 유닛 테스트 불가하지만
# (위 _resolve_post_field_pos 주석 참고), op_goto_text의 T8/T10 가드와
# op_page_break_before처럼 "어떤 액션을 어떤 순서로 Run했는가"만 검증하면 되는
# 로직은 최소 페이크로 고정할 수 있다 — COM 반환값 의미는 만들지 않고 호출
# 시퀀스만 기록한다.

class _FakeGotoHwp:
    """op_goto_text/op_page_break_before가 필요로 하는 최소 COM 표면만 흉내.

    이름 주의: 아래(파일 뒷부분) op_delete_blank_after/before 테스트가 별도의
    `_FakeHwp`를 정의한다(모듈 스코프에서 나중 정의가 앞 정의를 가린다) —
    충돌을 피하려고 이 클래스는 `_FakeGotoHwp`로 이름을 다르게 둔다.
    """

    def __init__(self, para_text_after_move="요약문"):
        self.actions = []          # Run()으로 실행된 액션 이름 순서
        self._para_text = para_text_after_move
        self._pos = (0, 0, 0)

    def MoveDocBegin(self):
        self.actions.append("MoveDocBegin")

    def find(self, text):
        self.actions.append(f"find:{text}")
        return True

    def Cancel(self):
        self.actions.append("Cancel")

    def Run(self, action):
        self.actions.append(action)
        return True

    def get_pos(self):
        return self._pos

    def set_pos(self, *args):
        self._pos = args

    def get_selected_text(self):
        return self._para_text

    def TableLowerCell(self):
        self.actions.append("TableLowerCell")
        return True


def test_goto_text_t8_guard_runs_justify_after_break():
    """T10: T8 가드가 문단을 쪼갠 뒤 반드시 ParagraphShapeAlignJustify를 Run해야
    한다 — 안 그러면 라벨의 CENTER paraPr이 새 본문 문단에 그대로 상속된다."""
    hwp = _FakeGotoHwp(para_text_after_move="요약문")  # MoveNextParaBegin이 no-op된 상황 재현
    result = cb.op_goto_text(hwp, {"text": "요약문", "next_para": True})
    assert result["t8_break"] is True
    # 순서: MoveNextParaBegin -> (가드 판독 중 MoveParaBegin/MoveSelParaEnd) ->
    # MoveParaEnd -> BreakPara -> ParagraphShapeAlignJustify
    assert "BreakPara" in hwp.actions
    assert "ParagraphShapeAlignJustify" in hwp.actions
    assert hwp.actions.index("BreakPara") < hwp.actions.index("ParagraphShapeAlignJustify")


def test_goto_text_no_guard_when_next_para_moves_away():
    """가드가 오탐하지 않아야 한다 — MoveNextParaBegin이 실제로 다음 문단으로
    이동했으면(앵커 문구가 더 이상 커서 문단에 없으면) justify를 Run하지 않는다."""
    hwp = _FakeGotoHwp(para_text_after_move="본문이 정상적으로 다음 문단에 있음")
    result = cb.op_goto_text(hwp, {"text": "요약문", "next_para": True})
    assert "t8_break" not in result
    assert "ParagraphShapeAlignJustify" not in hwp.actions


def test_page_break_before_runs_moveparabegin_then_breakpage():
    hwp = _FakeGotoHwp()
    result = cb.op_page_break_before(hwp, {"text": "I.  서론"})
    assert result == {"page_break_before": "I.  서론", "found": True}
    assert "MoveParaBegin" in hwp.actions
    assert "BreakPage" in hwp.actions


# ── T12: goto_text cell_below (표 라벨 셀 → 다음 행 fill_target 셀 이동) ──────

def test_goto_text_cell_below_uses_tablelowercell_not_breakpara():
    """cell_below:true면 next_para의 same-cell BreakPara 분기를 타지 않고
    TableLowerCell로 표 셀 자체를 이동해야 한다(라벨 셀이 늘어나며 본문을
    삼키는 버그의 근본 수정 — T8 가드는 다른 문제를 겨냥한 것이라 이 경로에서
    쓰면 안 됨)."""
    hwp = _FakeGotoHwp(para_text_after_move="요약문")
    result = cb.op_goto_text(hwp, {"text": "요약문", "next_para": True,
                                    "cell_below": True})
    assert result == {"found": True, "cell_below": True}
    assert "TableLowerCell" in hwp.actions
    assert "BreakPara" not in hwp.actions
    assert "MoveNextParaBegin" not in hwp.actions
    assert "MoveParaBegin" in hwp.actions
    # find -> Cancel -> TableLowerCell -> MoveParaBegin 순서.
    assert hwp.actions.index("TableLowerCell") < hwp.actions.index("MoveParaBegin")


def test_goto_text_cell_below_raises_when_tablelowercell_unavailable():
    class _NoCellHop(_FakeGotoHwp):
        TableLowerCell = None
    hwp = _NoCellHop()
    with pytest.raises(RuntimeError, match="TableLowerCell"):
        cb.op_goto_text(hwp, {"text": "요약문", "cell_below": True})


# ── T12: build_report label-cell anchor detection + wiring ──────────────────

_SUMMARY_FORM_PROFILE = {
    "table_map": [
        {
            "index": 0,
            "cells": [
                {"addr": {"row": 0, "col": 0}, "shaded": True,
                 "text_preview": "작성요령", "classification": "static"},
                {"addr": {"row": 1, "col": 0}, "shaded": False,
                 "text_preview": "안내문", "classification": "guide"},
                {"addr": {"row": 2, "col": 0}, "shaded": True,
                 "text_preview": "요약문", "classification": "static"},
                {"addr": {"row": 3, "col": 0}, "shaded": False,
                 "text_preview": "", "classification": "fill_target"},
            ],
        },
    ],
}

_SUMMARY_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: 요약문

첫 문장.

둘째 문장.
"""


def test_find_label_cell_anchors_picks_static_shaded_cell_above_fill_target():
    anchors = br.find_label_cell_anchors(_SUMMARY_FORM_PROFILE)
    assert anchors == {"요약문"}
    # "작성요령"은 shaded+static이지만 바로 아래(row1)가 guide(fill_target 아님) — 제외.


def test_find_label_cell_anchors_empty_when_no_profile():
    assert br.find_label_cell_anchors(None) == set()
    assert br.find_label_cell_anchors({}) == set()


def test_build_ops_sets_cell_below_for_label_cell_anchor(tmp_path):
    meta, secs = br.parse_content(_SUMMARY_CONTENT)
    anchors = br.find_label_cell_anchors(_SUMMARY_FORM_PROFILE)
    ops = br.build_ops(meta, secs, tmp_path, label_cell_anchors=anchors)
    goto_ops = [o for o in ops if o["op"] == "goto_text" and o["text"] == "요약문"]
    assert len(goto_ops) == 1
    assert goto_ops[0]["cell_below"] is True


def test_build_ops_omits_cell_below_without_form_profile(tmp_path):
    """label_cell_anchors 생략(기존 호출부, --form-profile 없음) — cell_below
    키 자체가 안 생겨야 한다(하위호환, 기존 next_para 경로 그대로)."""
    meta, secs = br.parse_content(_SUMMARY_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    goto_ops = [o for o in ops if o["op"] == "goto_text" and o["text"] == "요약문"]
    assert len(goto_ops) == 1
    assert "cell_below" not in goto_ops[0]


def test_build_ops_summary_section_emits_separate_break_after_paragraphs(tmp_path):
    """빈 줄로 구분된 두 문장은 별도 insert_text 블록이 되고, 각각
    break_after(BreakPara)로 문단을 끊어야 한다(리터럴 "\\r\\n" 금지 — T12)."""
    meta, secs = br.parse_content(_SUMMARY_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert [o["text"] for o in text_ops] == ["첫 문장.", "둘째 문장."]
    assert all(o["break_after"] is True for o in text_ops)
    assert all("\r\n" not in o["text"] for o in text_ops)


def test_load_form_profile_missing_path_returns_none(tmp_path):
    assert br.load_form_profile(None) is None
    assert br.load_form_profile(str(tmp_path / "nope.json")) is None


def test_load_form_profile_reads_json(tmp_path):
    p = tmp_path / "form_profile.json"
    p.write_text(json.dumps(_SUMMARY_FORM_PROFILE), encoding="utf-8")
    assert br.load_form_profile(str(p)) == _SUMMARY_FORM_PROFILE


# ── T12: com_backend op_insert_text break_after (BreakPara vs literal \r\n) ──

class _FakeInsertTextHwp:
    """op_insert_text의 break_after 경로 검증용 최소 페이크.

    실제 CharShape/select_text 부작용은 무시(반환값만 고정) — 여기서 검증할
    불변식은 "break_after일 때 BreakPara Run이 불리는가"와 "text에 리터럴
    개행을 넣지 않아도 되는가" 뿐이다.
    """

    def __init__(self):
        self.actions = []
        self.inserted = []
        self._pos = (0, 0, 0)

    def insert_text(self, text):
        self.inserted.append(text)

    def get_pos(self):
        return self._pos

    def set_pos(self, *args):
        self._pos = args

    def select_text(self, *args):
        return False  # 선택 실패 취급 — CharShape 적용 스킵, break_after만 검증

    def Run(self, action):
        self.actions.append(action)
        return True


def test_op_insert_text_break_after_runs_breakpara_no_pt():
    hwp = _FakeInsertTextHwp()
    result = cb.op_insert_text(hwp, {"text": "본문", "break_after": True})
    assert hwp.inserted == ["본문"]
    assert hwp.actions == ["BreakPara"]
    assert result["break_after"] is True


def test_op_insert_text_break_after_runs_breakpara_with_pt():
    hwp = _FakeInsertTextHwp()
    result = cb.op_insert_text(hwp, {"text": "본문", "pt": 10, "break_after": True})
    assert hwp.inserted == ["본문"]
    assert "BreakPara" in hwp.actions
    assert result["break_after"] is True


def test_op_insert_text_without_break_after_no_breakpara_backward_compat():
    hwp = _FakeInsertTextHwp()
    result = cb.op_insert_text(hwp, {"text": "본문\r\n", "pt": 10})
    assert "BreakPara" not in hwp.actions
    assert result["break_after"] is False


def test_op_insert_text_segments_break_after_runs_breakpara_once():
    hwp = _FakeInsertTextHwp()
    result = cb.op_insert_text(hwp, {
        "text": "일반 굵게",
        "segments": [{"text": "일반 ", "bold": False}, {"text": "굵게", "bold": True}],
        "pt": 10, "break_after": True,
    })
    assert hwp.actions.count("BreakPara") == 1
    assert result["break_after"] is True


def test_page_break_before_not_required_skips_when_anchor_missing():
    class _NotFoundHwp(_FakeGotoHwp):
        def find(self, text):
            self.actions.append(f"find:{text}")
            return False

    hwp = _NotFoundHwp()
    result = cb.op_page_break_before(hwp, {"text": "없는 앵커"})
    assert result == {"page_break_before": "없는 앵커", "found": False}
    assert "BreakPage" not in hwp.actions


def test_page_break_before_required_raises_when_anchor_missing():
    class _NotFoundHwp(_FakeGotoHwp):
        def find(self, text):
            self.actions.append(f"find:{text}")
            return False

    hwp = _NotFoundHwp()
    with pytest.raises(RuntimeError):
        cb.op_page_break_before(hwp, {"text": "없는 앵커", "required": True})


def test_resolve_post_field_pos_requires_both_positions():
    with pytest.raises(ValueError):
        cb._resolve_post_field_pos(None, (0, 0, 0))
    with pytest.raises(ValueError):
        cb._resolve_post_field_pos((0, 0, 0), None)


# ── _yaml_scalar / _yaml_list (BUG2: quoted items + inline-comment-in-bracket) ──

def test_yaml_scalar_strips_surrounding_quotes():
    assert br._yaml_scalar('"hello"') == "hello"
    assert br._yaml_scalar("'hello'") == "hello"
    assert br._yaml_scalar("hello") == "hello"


def test_yaml_scalar_strips_inline_comment_outside_brackets():
    assert br._yaml_scalar('10  # base pt') == "10"
    assert br._yaml_scalar('"book"  # binding mode') == "book"


def test_yaml_scalar_does_not_eat_bracket_list_as_comment():
    # BUG2(b): '#FF0000' after the comma must survive — it is not a comment.
    assert br._yaml_scalar("[#0000FF, #FF0000]") == "[#0000FF, #FF0000]"


def test_yaml_list_quoted_items_strip_literal_quotes():
    # BUG2(a): quoted items must not keep the quote characters.
    assert br._yaml_list('["#0000FF", "#FF0000"]') == ["#0000FF", "#FF0000"]
    assert br._yaml_list("['#0000FF', '#FF0000']") == ["#0000FF", "#FF0000"]


def test_yaml_list_unquoted_with_spaces():
    assert br._yaml_list("[ #0000FF ,  #FF0000 ]") == ["#0000FF", "#FF0000"]


def test_yaml_list_inline_unquoted_form():
    assert br._yaml_list("[#0000FF, #FF0000]") == ["#0000FF", "#FF0000"]


def test_yaml_list_int_elements_still_parsed_as_int():
    assert br._yaml_list("[1, 999]") == [1, 999]


# ── style_diff allowance normalization (BUG2c) ──────────────────────────

def test_style_diff_allow_colors_accepts_quoted_and_unquoted_and_bracket_forms():
    import style_diff as sd

    baseline = {"fonts": [], "sizes_pt": [], "colors": [], "line_spacings": []}
    for allow_colors in (
        ["#0000FF", "#FF0000"],
        ['"#0000FF"', '"#FF0000"'],
        ["'#0000FF'", "'#FF0000'"],
    ):
        allow = sd.build_allowances(baseline, {"allow_colors": allow_colors})
        assert allow["colors"] == {"#0000FF", "#FF0000"}, allow_colors


# ── _repeat_delete_while_progress (anchor-targeted blank-run "all" mode) ──
# pure loop logic — no COM. Metric is now a monotone counter (total newline
# count of the doc text), not "count of blank RUNS" — a run's length can
# shrink by one blank (e.g. 6->5) while the run count itself stays at 1,
# which previously read as "no progress" and stopped the loop after round 1
# (live repro: delete_blank_before all:true deleted only 1 of 6 blanks).

def test_repeat_delete_while_progress_stops_when_blanks_exhausted():
    blanks = [3, 2, 1, 0, 0]  # 3 adjacent blanks, 1 per round, then plateaus at 0
    calls = []

    def delete_once():
        calls.append(1)

    def count_metric():
        return blanks[len(calls)]

    rounds, progressed = cb._repeat_delete_while_progress(delete_once, count_metric)
    # 3 productive rounds + 1 confirming round that sees no further progress (0->0).
    assert rounds == 4
    assert progressed is True


def test_repeat_delete_while_progress_stops_immediately_on_no_progress():
    calls = []

    def delete_once():
        calls.append(1)

    def count_metric():
        return 0  # never any adjacent blanks — first round makes no progress

    rounds, progressed = cb._repeat_delete_while_progress(delete_once, count_metric)
    assert rounds == 1          # tries once, sees no improvement, stops
    assert progressed is True   # rounds > 0 (a delete was attempted)


def test_repeat_delete_while_progress_respects_max_rounds_guard():
    calls = []

    def delete_once():
        calls.append(1)

    def count_metric():
        return max(0, 100 - len(calls))  # "progress" every round, never reaches 0

    rounds, _ = _rounds_with_cap(delete_once, count_metric)
    assert rounds == 50


def _rounds_with_cap(delete_once, count_metric):
    return cb._repeat_delete_while_progress(delete_once, count_metric, max_rounds=50)


def test_repeat_delete_while_progress_six_blank_run_shrinks_one_at_a_time():
    """Models the live bug: a SINGLE contiguous run of 6 blank paragraphs.
    A run-count metric sees this as "1 run" no matter how many blanks remain
    inside it, so it never detects progress. A monotone counter (here: a fake
    total-newline count 6->5->4->3->2->1->0->0) must correctly drive the loop
    through all 6 deletions instead of stopping after round 1."""
    counts = [6, 5, 4, 3, 2, 1, 0, 0]
    calls = []

    def delete_once():
        calls.append(1)

    def count_metric():
        return counts[len(calls)]

    rounds, progressed = cb._repeat_delete_while_progress(delete_once, count_metric)
    assert rounds == 7  # 6 productive rounds + 1 confirming plateau round (0->0)
    assert progressed is True
    assert len(calls) == 7


# ── op_delete_blank_after / op_delete_blank_before: "all" + required:false ──
# Fake Hwp simulating a text buffer with an anchor and N adjacent blank
# paragraphs. Each Delete()/Run("DeleteBack") consumes one adjacent blank
# paragraph (mirrors the real COM "eat one paragraph-end mark" semantics).

class _FakeHwp:
    def __init__(self, before_blanks=0, after_blanks=0, anchor="ANCHOR"):
        self.anchor = anchor
        self.before_blanks = before_blanks
        self.after_blanks = after_blanks
        self.found = False
        self.moved_para_begin = False

    def MoveDocBegin(self):
        self.found = False

    def find(self, text):
        self.found = (text == self.anchor)
        return self.found

    def Cancel(self):
        pass

    def Delete(self):
        # op_delete_blank_after: consumes one adjacent blank paragraph *after* anchor.
        if self.after_blanks > 0:
            self.after_blanks -= 1

    def Run(self, action):
        if action == "MoveParaBegin":
            self.moved_para_begin = True
        elif action == "DeleteBack":
            # op_delete_blank_before: consumes one adjacent blank paragraph *before* anchor.
            if self.before_blanks > 0:
                self.before_blanks -= 1

    def get_text_file(self, *a, **k):
        # op_delete_blank_after/before now drive their "all" loop off
        # _count_newlines (total \n count in the doc), not _count_blank_runs
        # (run count) — a run's length can shrink while its run-count stays
        # at 1, which is exactly the live bug this fix addresses. Emit 3
        # newlines per remaining adjacent blank paragraph so the total
        # newline count decreases monotonically per successful delete round,
        # then plateaus once all remaining blanks are consumed.
        n = self.before_blanks + self.after_blanks
        return "X\n\n\n".join([""] * (n + 1))


def test_op_delete_blank_after_all_mode_deletes_until_none_adjacent():
    hwp = _FakeHwp(after_blanks=3, anchor="CAP")
    result = cb.op_delete_blank_after(hwp, {"text": "CAP", "all": True})
    assert result["found"] is True
    assert hwp.after_blanks == 0
    assert result["deleted"] == result["rounds"]


def test_op_delete_blank_before_all_mode_deletes_until_none_adjacent():
    hwp = _FakeHwp(before_blanks=3, anchor="TITLE")
    result = cb.op_delete_blank_before(hwp, {"text": "TITLE", "all": True})
    assert result["found"] is True
    assert hwp.before_blanks == 0
    assert hwp.moved_para_begin is True
    assert result["deleted"] == result["rounds"]


def test_op_delete_blank_before_all_mode_six_blank_run_live_repro():
    """Live repro fixed: delete_blank_before all:true deleted only 1 of 6
    adjacent blank paragraphs, because the old progress metric
    (_count_blank_runs) counts RUNS of 3+ newlines, not their length — a
    single contiguous run of 6 blanks is still "1 run" whether it shrinks to
    5 or 0, so the loop misread round 1 as no-progress and stopped early.
    With the fix (_count_newlines, a monotone total-newline counter), all 6
    adjacent blanks must be fully consumed."""
    hwp = _FakeHwp(before_blanks=6, anchor="TITLE")
    result = cb.op_delete_blank_before(hwp, {"text": "TITLE", "all": True})
    assert result["found"] is True
    assert hwp.before_blanks == 0
    assert result["deleted"] == result["rounds"]


def test_op_delete_blank_after_required_false_no_raise_when_anchor_missing():
    """m1 audit: op_delete_blank_after historically raised & aborted the batch
    regardless of required. Fixed: must return {"deleted":0,"found":False}."""
    hwp = _FakeHwp(anchor="PRESENT")
    result = cb.op_delete_blank_after(hwp, {"text": "MISSING", "required": False})
    assert result == {"deleted": 0, "found": False}


def test_op_delete_blank_after_required_true_still_raises_when_anchor_missing():
    hwp = _FakeHwp(anchor="PRESENT")
    with pytest.raises(RuntimeError):
        cb.op_delete_blank_after(hwp, {"text": "MISSING"})  # required defaults True


def test_op_delete_blank_before_required_false_no_raise_when_anchor_missing():
    hwp = _FakeHwp(anchor="PRESENT")
    result = cb.op_delete_blank_before(hwp, {"text": "MISSING", "required": False})
    assert result["deleted"] == 0
    assert result["found"] is False


def test_op_delete_blank_before_required_true_still_raises_when_anchor_missing():
    hwp = _FakeHwp(anchor="PRESENT")
    with pytest.raises(RuntimeError):
        cb.op_delete_blank_before(hwp, {"text": "MISSING"})  # required defaults True


# ── keep_with_next (build.yaml) → table caption orphan fix ─────────────────
# 표 캡션("표 1. …")이 페이지 하단에 고아로 남고 표 본문이 다음 페이지로 밀리는
# 문제의 근본 수정. tidy_blank_*/page_break_before와 동일 패턴: build_report.py는
# COM op으로 변환하지 않는다(build_ops zero emission) — 키 자체는 parse_build_yaml/
# merge_meta에서 계속 파싱·병합되고, 실제 patch는 fill_report.py가 COM edit(hwpx
# save) 이후 tidy_hwpx.py(오프라인, --keep-with-next)로 수행한다.

def test_parse_build_yaml_keep_with_next_block_list(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "keep_with_next:",
        '  - "표 1."',
        '  - "표 2."',
    ])
    cfg = br.parse_build_yaml(p)
    assert cfg["keep_with_next"] == ["표 1.", "표 2."]


def test_keep_with_next_absent_is_zero_ops():
    _, secs, ops = _build()
    assert not any("keep_with_next" in json.dumps(o) for o in ops)


def test_keep_with_next_emits_no_com_ops():
    """keep_with_next는 COM op을 만들지 않는다 — fill_report.py가 tidy_hwpx.py로
    오프라인 처리한다(캡션 프리픽스는 COM find 대상이 아님)."""
    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta["keep_with_next"] = ["표 1."]
    ops = br.build_ops(meta, secs, FIX)

    op_names = [o["op"] for o in ops]
    assert "keep_with_next" not in op_names
    assert "set_keep_with_next" not in op_names


def test_keep_with_next_keys_pass_through_meta_without_ops():
    """keep_with_next 키 자체는 meta에 남아(merge_meta가 병합) 다음 단계
    (fill_report.py)가 읽을 수 있어야 한다 — build_ops만 소비하지 않는다."""
    merged = br.merge_meta({}, {"keep_with_next": ["표 1.", "표 2."]})
    assert merged["keep_with_next"] == ["표 1.", "표 2."]

    text = open(CONTENT, encoding="utf-8").read()
    meta, secs = br.parse_content(text)
    meta = dict(meta)
    meta.update(merged)
    ops = br.build_ops(meta, secs, FIX)
    assert not any(o["op"] == "keep_with_next" for o in ops)


def test_merge_meta_carries_keep_with_next():
    merged = br.merge_meta({}, {"keep_with_next": ["표 1.", "표 2."]})
    assert merged["keep_with_next"] == ["표 1.", "표 2."]


def test_merge_meta_no_keep_with_next_key_when_absent():
    merged = br.merge_meta({}, {})
    assert "keep_with_next" not in merged


# ── [[TABLE cols= pt=]] — column width ratios + cell font size ─────────────

def test_parse_col_ratios_normalizes_to_sum_one():
    ratios = br._parse_col_ratios("10,16,12,9,10,43", 0)
    assert ratios == pytest.approx([0.10, 0.16, 0.12, 0.09, 0.10, 0.43])
    assert sum(ratios) == pytest.approx(1.0)


def test_parse_col_ratios_none_when_attr_absent():
    assert br._parse_col_ratios(None, 0) is None
    assert br._parse_col_ratios("", 0) is None


def test_parse_col_ratios_rejects_non_numeric():
    with pytest.raises(SystemExit):
        br._parse_col_ratios("a,b,c", 0)


def test_parse_col_ratios_rejects_zero_sum():
    with pytest.raises(SystemExit):
        br._parse_col_ratios("0,0,0", 0)


def test_parse_col_ratios_rejects_zero_value_even_if_sum_positive():
    # BUG: "50,0,50" used to pass (sum=100 > 0) even though one column has
    # a zero width, which HWP renders as a degenerate/invisible column.
    with pytest.raises(SystemExit):
        br._parse_col_ratios("50,0,50", 0)


def test_parse_col_ratios_rejects_negative_value_even_if_sum_positive():
    with pytest.raises(SystemExit):
        br._parse_col_ratios("50,-10,60", 0)


_TABLE_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

[[TABLE caption="표 1." cols=10,16,12,9,10,43 pt=9]]
| a | b | c | d | e | f |
| 1 | 2 | 3 | 4 | 5 | 6 |
[[/TABLE]]
"""

_TABLE_CONTENT_NO_ATTRS = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

[[TABLE caption="표 1."]]
| a | b |
| 1 | 2 |
[[/TABLE]]
"""


def test_table_tag_with_cols_and_pt_emits_col_ratios_and_font_pt(tmp_path):
    meta, secs = br.parse_content(_TABLE_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    table_ops = [o for o in ops if o["op"] == "insert_table"]
    assert len(table_ops) == 1
    op = table_ops[0]
    assert op["col_ratios"] == pytest.approx([0.10, 0.16, 0.12, 0.09, 0.10, 0.43])
    assert op["font_pt"] == 9


def test_table_tag_without_cols_pt_omits_keys_backward_compat(tmp_path):
    """cols/pt 없는 구 태그는 col_ratios/font_pt 키 자체가 안 생겨야 한다
    (com_backend op_insert_table의 optional-key 계약, 구동작 그대로)."""
    meta, secs = br.parse_content(_TABLE_CONTENT_NO_ATTRS)
    ops = br.build_ops(meta, secs, tmp_path)
    table_ops = [o for o in ops if o["op"] == "insert_table"]
    assert len(table_ops) == 1
    assert "col_ratios" not in table_ops[0]
    assert "font_pt" not in table_ops[0]


def test_table_tag_cols_count_mismatch_dies(tmp_path):
    bad = _TABLE_CONTENT.replace("cols=10,16,12,9,10,43", "cols=10,16,12")
    meta, secs = br.parse_content(bad)
    with pytest.raises(SystemExit):
        br.build_ops(meta, secs, tmp_path)


def test_validate_ops_accepts_insert_table_with_col_ratios_and_font_pt():
    ops = [{"op": "insert_table", "data": [["a", "b"]],
            "col_ratios": [0.4, 0.6], "font_pt": 9}]
    assert cb._validate_ops(ops) == ops


def test_op_insert_table_col_ratios_length_mismatch_raises_before_any_com_call():
    """col_ratios 길이가 열 개수와 다르면 COM(hwp) 호출 전에 즉시 raise한다 —
    hwp=None을 넘겨도 이 가드에서 죽어야 하므로 COM 없이 테스트 가능."""
    o = {"data": [["a", "b", "c"]], "col_ratios": [0.5, 0.5]}  # 2개 vs 열 3개
    with pytest.raises(RuntimeError, match="col_ratios"):
        cb.op_insert_table(None, o)


# ── [[EQ]] inline default flip ──────────────────────────────────────────

_EQ_BARE_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

본문.

[[EQ latex="\\frac{1}{2}mv^2"]]

본문 뒤.
"""

_EQ_DISPLAY_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

본문.

[[EQ display latex="\\frac{1}{2}mv^2"]]

본문 뒤.
"""


def test_eq_bare_tag_defaults_to_inline():
    meta, secs = br.parse_content(_EQ_BARE_CONTENT)
    eq_blocks = [b for b in secs[0]["blocks"] if b["kind"] == "eq"]
    assert len(eq_blocks) == 1
    assert eq_blocks[0]["display"] is False


def test_eq_display_flag_keeps_old_display_behavior():
    meta, secs = br.parse_content(_EQ_DISPLAY_CONTENT)
    eq_blocks = [b for b in secs[0]["blocks"] if b["kind"] == "eq"]
    assert len(eq_blocks) == 1
    assert eq_blocks[0]["display"] is True


def test_eq_bare_emits_insert_equation_op_with_display_false(tmp_path):
    meta, secs = br.parse_content(_EQ_BARE_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    eq_ops = [o for o in ops if o["op"] == "insert_equation"]
    assert len(eq_ops) == 1
    assert eq_ops[0]["display"] is False


def test_eq_display_emits_insert_equation_op_with_display_true(tmp_path):
    meta, secs = br.parse_content(_EQ_DISPLAY_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    eq_ops = [o for o in ops if o["op"] == "insert_equation"]
    assert len(eq_ops) == 1
    assert eq_ops[0]["display"] is True


def test_eq_bare_appends_build_warning_when_flipped_to_inline(tmp_path):
    meta, secs = br.parse_content(_EQ_BARE_CONTENT)
    warnings = []
    br.build_ops(meta, secs, tmp_path, warnings=warnings)
    assert len(warnings) == 1
    assert "인라인" in warnings[0]


def test_eq_display_emits_no_build_warning(tmp_path):
    meta, secs = br.parse_content(_EQ_DISPLAY_CONTENT)
    warnings = []
    br.build_ops(meta, secs, tmp_path, warnings=warnings)
    assert warnings == []


def test_build_ops_warnings_param_optional_backward_compat(tmp_path):
    """warnings 인자를 안 주는 기존 호출부(테스트의 _build() 헬퍼 등)는
    그대로 동작해야 한다 — 반환 시그니처(ops 단일 값)는 바뀌지 않는다."""
    meta, secs = br.parse_content(_EQ_BARE_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)  # warnings 생략
    assert isinstance(ops, list)


def test_fixture_content_still_all_display_true_after_default_flip():
    """regen-brake 픽스처는 모두 [[EQ display ...]]를 명시하므로, 기본값이
    뒤집혀도(bare=inline) 골든 ops(expected_ops.json)의 display:true 3건은
    그대로 유지되어야 한다(회귀 방지)."""
    _, secs, ops = _build()
    eq_ops = [o for o in ops if o["op"] == "insert_equation"]
    assert len(eq_ops) == 3
    assert all(o["display"] is True for o in eq_ops)


# ── golden ops JSON for a small [[TABLE cols= pt=]] content.md ─────────────

_GOLDEN_CONTENT = """---
title: 작은 표 테스트
title_anchor: "TITLE_HERE"
base_pt: 10
caption_pt: 9
---

## SECTION: I.  서론

표 1은 다음과 같다.

[[TABLE caption="표 1. 결과" cols=10,16,12,9,10,43 pt=9]]
| 시간 | 값A | 값B | 값C | 값D | 값E |
| 1 | 2 | 3 | 4 | 5 | 6 |
[[/TABLE]]

수식은 인라인으로 낀다.

[[EQ latex="E = mc^2"]]

여기까지.
"""

_GOLDEN_EXPECTED_OPS = [
    {"op": "replace_all", "find": "TITLE_HERE", "replace": "작은 표 테스트"},
    {"op": "goto_text", "text": "I.  서론", "next_para": True},
    {"op": "insert_text", "text": "표 1은 다음과 같다.", "pt": 10, "break_after": True},
    # Rule 2: (blank) -> 표 -> 캡션 -> (blank) -> 본문.
    {"op": "insert_text", "text": "", "pt": 10, "break_after": True},
    {"op": "insert_table",
     "data": [["시간", "값A", "값B", "값C", "값D", "값E"],
              ["1", "2", "3", "4", "5", "6"]],
     "treat_as_char": True,
     "col_ratios": [0.10, 0.16, 0.12, 0.09, 0.10, 0.43],
     "font_pt": 9},
    {"op": "insert_text", "text": "표 1. 결과", "pt": 9, "break_after": True},
    {"op": "insert_text", "text": "", "pt": 10, "break_after": True},
    {"op": "insert_text", "text": "수식은 인라인으로 낀다.", "pt": 10, "break_after": True},
    {"op": "insert_equation", "base_pt": 10, "display": False,
     "hwpeqn": "E = mc^{2}"},
    {"op": "insert_text", "text": "여기까지.", "pt": 10, "break_after": True},
]


def test_golden_ops_json_for_small_table_cols_pt_content(tmp_path):
    meta, secs = br.parse_content(_GOLDEN_CONTENT)
    warnings = []
    ops = br.build_ops(meta, secs, tmp_path, warnings=warnings)

    assert ops == pytest.approx(_GOLDEN_EXPECTED_OPS)  # col_ratios float 비교 허용
    # 인라인으로 뒤집힌 수식 1건 → 경고 1건.
    assert len(warnings) == 1


# ── Rule 2(operator): caption BELOW object, (blank)->object->caption->(blank) ──

_TABLE_CAPTION_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
caption_pt: 9
---

## SECTION: I.  서론

[[TABLE caption="표 1. 결과"]]
| a | b |
| 1 | 2 |
[[/TABLE]]
"""


def test_table_op_sequence_is_blank_table_caption_blank(tmp_path):
    meta, secs = br.parse_content(_TABLE_CAPTION_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    # goto_text 이후부터 표 관련 op만 슬라이스.
    kinds = [o["op"] for o in ops]
    table_idx = kinds.index("insert_table")
    assert ops[table_idx - 1] == {"op": "insert_text", "text": "", "pt": 10,
                                   "break_after": True}
    assert ops[table_idx + 1] == {"op": "insert_text", "text": "표 1. 결과",
                                   "pt": 9, "break_after": True}
    assert ops[table_idx + 2] == {"op": "insert_text", "text": "", "pt": 10,
                                   "break_after": True}


_TABLE_NO_CAPTION_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

[[TABLE]]
| a | b |
| 1 | 2 |
[[/TABLE]]
"""


def test_table_without_caption_omits_caption_ops_but_keeps_blanks(tmp_path):
    """P3: 빈 캡션은 생략하지만, 앞뒤 blank 발행은 캡션 유무와 무관하게
    항상 정확히 하나씩(결정론)."""
    meta, secs = br.parse_content(_TABLE_NO_CAPTION_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    kinds = [o["op"] for o in ops]
    table_idx = kinds.index("insert_table")
    assert ops[table_idx - 1] == {"op": "insert_text", "text": "", "pt": 10,
                                   "break_after": True}
    # 캡션 없음 -> 표 바로 다음 op은 캡션 텍스트가 아니어야 함(있다면 문서 끝).
    assert table_idx + 1 >= len(ops) or ops[table_idx + 1].get("text") != "표 1. 결과"


_FIG_CAPTION_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
caption_pt: 9
---

## SECTION: I.  서론

[[FIG file="a.png" caption="그림 1. 결과"]]
"""


def test_fig_op_sequence_is_blank_picture_caption_blank(tmp_path):
    meta, secs = br.parse_content(_FIG_CAPTION_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    kinds = [o["op"] for o in ops]
    fig_idx = kinds.index("insert_picture")
    assert ops[fig_idx - 1] == {"op": "insert_text", "text": "", "pt": 10,
                                 "break_after": True}
    assert ops[fig_idx + 1] == {"op": "insert_text", "text": "그림 1. 결과",
                                 "pt": 9, "break_after": True}
    assert ops[fig_idx + 2] == {"op": "insert_text", "text": "", "pt": 10,
                                 "break_after": True}


def test_fig_without_caption_still_gets_blank_before(tmp_path):
    content = _FIG_CAPTION_CONTENT.replace(' caption="그림 1. 결과"', "")
    meta, secs = br.parse_content(content)
    ops = br.build_ops(meta, secs, tmp_path)
    kinds = [o["op"] for o in ops]
    fig_idx = kinds.index("insert_picture")
    assert ops[fig_idx - 1] == {"op": "insert_text", "text": "", "pt": 10,
                                 "break_after": True}
    # 캡션 없으면 그림 다음에 caption_pt 텍스트 op이 없어야 함.
    assert fig_idx + 1 >= len(ops) or ops[fig_idx + 1]["op"] != "insert_text" \
        or ops[fig_idx + 1].get("pt") != 9


def test_multiple_tables_each_get_own_blank_pair(tmp_path):
    """연속 두 표가 있어도 각자 정확히 (blank, table, caption, blank) 4-슬롯을
    받아야 한다(이중 공백 없이, 서로 간섭 없이)."""
    content = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
caption_pt: 9
---

## SECTION: I.  서론

[[TABLE caption="표 1."]]
| a |
| 1 |
[[/TABLE]]

[[TABLE caption="표 2."]]
| b |
| 2 |
[[/TABLE]]
"""
    meta, secs = br.parse_content(content)
    ops = br.build_ops(meta, secs, tmp_path)
    table_indices = [i for i, o in enumerate(ops) if o["op"] == "insert_table"]
    assert len(table_indices) == 2
    for idx in table_indices:
        assert ops[idx - 1]["op"] == "insert_text" and ops[idx - 1]["text"] == ""
        assert ops[idx + 2]["op"] == "insert_text" and ops[idx + 2]["text"] == ""


# ── `**굵게**` 마크다운 bold span 지원 ───────────────────────────────────
# split_bold_segments: 순수 파싱 함수. ** 없으면 None(구동작 폴백), 있으면
# [{"text":..,"bold":bool}] 세그먼트 리스트(빈 세그먼트는 제거).

def test_split_bold_segments_returns_none_when_no_marker():
    assert br.split_bold_segments("일반 텍스트, 별표 없음") is None


def test_split_bold_segments_single_bold_span_middle():
    segs = br.split_bold_segments("일반 **굵게** 일반")
    assert segs == [
        {"text": "일반 ", "bold": False},
        {"text": "굵게", "bold": True},
        {"text": " 일반", "bold": False},
    ]


def test_split_bold_segments_bold_at_start():
    segs = br.split_bold_segments("**굵게**시작")
    assert segs == [
        {"text": "굵게", "bold": True},
        {"text": "시작", "bold": False},
    ]


def test_split_bold_segments_bold_at_end():
    segs = br.split_bold_segments("끝**굵게**")
    assert segs == [
        {"text": "끝", "bold": False},
        {"text": "굵게", "bold": True},
    ]


def test_split_bold_segments_entire_text_bold():
    segs = br.split_bold_segments("**전부굵게**")
    assert segs == [{"text": "전부굵게", "bold": True}]


def test_split_bold_segments_multiple_spans():
    segs = br.split_bold_segments("A **B** C **D** E")
    assert segs == [
        {"text": "A ", "bold": False},
        {"text": "B", "bold": True},
        {"text": " C ", "bold": False},
        {"text": "D", "bold": True},
        {"text": " E", "bold": False},
    ]


def test_split_bold_segments_no_empty_segments_when_adjacent_spans():
    # "**A****B**" — 두 굵게 스팬이 바로 붙어 사이 일반 세그먼트가 빈 문자열.
    segs = br.split_bold_segments("**A****B**")
    assert segs == [
        {"text": "A", "bold": True},
        {"text": "B", "bold": True},
    ]


_BOLD_PARA_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: 요약문

일반 **굵게** 일반.
"""

_PLAIN_PARA_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: 요약문

별표 없는 그냥 본문.
"""


def test_build_ops_para_with_bold_emits_segments_key(tmp_path):
    meta, secs = br.parse_content(_BOLD_PARA_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert len(text_ops) == 1
    op = text_ops[0]
    assert op["segments"] == [
        {"text": "일반 ", "bold": False},
        {"text": "굵게", "bold": True},
        {"text": " 일반.", "bold": False},
    ]
    # "text" 폴백은 ** 마커가 벗겨진 순수 텍스트여야 한다(segments 미지원
    # 소비자가 별표를 문서에 그대로 찍지 않도록). 줄바꿈은 더 이상 리터럴
    # "\r\n"이 아니라 break_after(BreakPara Run)로 건다(T12 — charShape 오염 방지).
    assert op["text"] == "일반 굵게 일반."
    assert op["break_after"] is True
    assert op["pt"] == 10


def test_build_ops_para_without_bold_omits_segments_key_backward_compat(tmp_path):
    """** 없는 문단은 segments 키 자체가 생기지 않아야 한다(하위호환 —
    기존 소비자/골든 ops 비교가 깨지지 않게)."""
    meta, secs = br.parse_content(_PLAIN_PARA_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert len(text_ops) == 1
    assert "segments" not in text_ops[0]
    assert text_ops[0]["text"] == "별표 없는 그냥 본문."
    assert text_ops[0]["break_after"] is True


def test_fixture_content_has_no_bold_markers_ops_unchanged():
    """regen-brake 골든 픽스처(expected_ops.json)에는 ** 마커가 없으므로,
    bold 세그먼트 기능 추가 후에도 골든 ops가 그대로여야 한다(회귀 방지 —
    이미 test_ops_match_baseline이 전체를 고정하지만, segments 부재를 여기서
    명시적으로도 확인)."""
    _, _, ops = _build()
    assert not any("segments" in o for o in ops if o["op"] == "insert_text")


# ── com_backend op_insert_text: segments → per-run CharShape(Bold) ─────────
# 실제 CharShape.Bold 반영은 라이브 한글(COM)만 검증 가능(hwp-com-charshape-quirks
# 메모: insert-then-select이 유일하게 검증된 결정론적 패턴) — 여기서는 그 패턴을
# 따라 "어떤 순서로 무엇을 호출했는가"만 페이크로 고정한다. 실측 unzip 검증은
# 별도 COM 스모크 테스트(스크래치패드)로 수행.

class _FakeSegHwp:
    """op_insert_text(segments=)가 필요로 하는 최소 COM 표면.

    insert_text 호출마다 커서를 전진시키고, select_text/CharShape Execute를
    기록한다. HParameterSet.HCharShape/HAction.GetDefault/Execute는 진짜
    pyhwpx ParameterSet이 아니라 속성 기록용 더미로 흉내낸다.
    """

    class _CharShapeSet:
        def __init__(self):
            self.Height = None
            self.TextColor = None
            self.Bold = None
        # HSet 프로퍼티는 자기 자신을 가리키는 핸들 역할(pyhwpx 관습 흉내).

        @property
        def HSet(self):
            return self

    class _HParameterSet:
        def __init__(self):
            self.HCharShape = _FakeSegHwp._CharShapeSet()

    class _HAction:
        def __init__(self, log):
            self._log = log

        def GetDefault(self, kind, hset):
            self._log.append(("GetDefault", kind))

        def Execute(self, kind, hset):
            pset = hset  # HSet property returns the set itself
            self._log.append(("Execute", kind, pset.Height, pset.TextColor, pset.Bold))

    def __init__(self):
        self.log = []
        self._para = 0
        self._pos = 0
        self.text_written = ""
        self.HParameterSet = self._HParameterSet()
        self.HAction = self._HAction(self.log)

    def get_pos(self):
        return (0, self._para, self._pos)

    def set_pos(self, *args):
        self._para, self._pos = args[1], args[2]

    def insert_text(self, text):
        self.text_written += text
        self._pos += len(text)
        self.log.append(("insert_text", text))

    def select_text(self, spara, spos, epara, epos, slist):
        self.log.append(("select_text", spara, spos, epara, epos))
        return True

    def Cancel(self):
        self.log.append(("Cancel",))


def test_op_insert_text_segments_inserts_each_run_in_order():
    hwp = _FakeSegHwp()
    o = {"op": "insert_text", "text": "일반 굵게 일반\r\n", "pt": 10,
         "segments": [{"text": "일반 ", "bold": False},
                      {"text": "굵게", "bold": True},
                      {"text": " 일반\r\n", "bold": False}]}
    result = cb.op_insert_text(hwp, o)
    assert hwp.text_written == "일반 굵게 일반\r\n"
    assert result["segments"] == 3
    assert result["inserted_chars"] == len("일반 굵게 일반\r\n")


def test_op_insert_text_segments_bold_run_sets_bold_1_in_charshape_execute():
    hwp = _FakeSegHwp()
    o = {"op": "insert_text", "text": "일반 굵게 일반\r\n", "pt": 10,
         "segments": [{"text": "일반 ", "bold": False},
                      {"text": "굵게", "bold": True},
                      {"text": " 일반\r\n", "bold": False}]}
    cb.op_insert_text(hwp, o)
    execs = [e for e in hwp.log if e[0] == "Execute"]
    # 3개 세그먼트 모두 pt=10이 강제되므로 CharShape Execute가 3회 있어야 하고,
    # 매 런마다 Bold를 명시적으로 1 또는 0으로 못박는다(None으로 "건드리지
    # 않음" 방식은 채택하지 않음 — GetDefault가 직전 굵게 런의 pending 상태를
    # 반영해 바로 뒤 일반 런에 굵기가 새어들 위험이 있어, 항상 명시 설정한다).
    assert len(execs) == 3
    bolds = [e[4] for e in execs]
    assert bolds == [0, 1, 0]
    heights = [e[2] for e in execs]
    assert heights == [1000, 1000, 1000]  # 10pt * 100 HwpUnit


def test_op_insert_text_no_segments_key_still_uses_legacy_single_run_path():
    """segments 키가 없으면(구 ops, 하위호환) 기존 단일-런 pt-강제 경로 그대로."""
    hwp = _FakeSegHwp()
    o = {"op": "insert_text", "text": "그냥 본문\r\n", "pt": 10}
    result = cb.op_insert_text(hwp, o)
    assert hwp.text_written == "그냥 본문\r\n"
    assert "segments" not in result
    execs = [e for e in hwp.log if e[0] == "Execute"]
    assert len(execs) == 1
    assert execs[0][4] is None  # bold 미지정 — 건드리지 않음


def test_validate_ops_accepts_insert_text_with_segments():
    ops = [{"op": "insert_text", "text": "일반 굵게 일반\r\n", "pt": 10,
            "segments": [{"text": "일반 ", "bold": False},
                         {"text": "굵게", "bold": True},
                         {"text": " 일반\r\n", "bold": False}]}]
    assert cb._validate_ops(ops) == ops


# ── split_inline_para: 인라인 [[EQ]]/[[URL]] quote-aware 스캔 (latex_leak 회귀) ──
# 실사고 evidence(report-aliasing-sampling/bundle/content.md): latex="x[n] = ..."
# 처럼 속성값 안에 `]`가 있으면 옛 파서가 태그를 조기 종료시켜 태그 꼬리가
# 리터럴 본문 텍스트로 새어나갔다(latex_leak). quote-aware 스캐너로 고침.

def test_split_inline_para_no_tag_returns_single_text_segment():
    segs = br.split_inline_para("그냥 평범한 문장입니다.")
    assert segs == [{"kind": "text", "text": "그냥 평범한 문장입니다."}]


def test_split_inline_para_eq_with_bracket_in_latex_not_truncated():
    """latex 속성값 안의 `x[n]`이 태그를 조기 종료시키면 안 된다."""
    text = '이는 다음 수열 [[EQ latex="x[n] = \\sin( \\frac{2\\pi f n}{f_s} )"]] 이 된다.'
    segs = br.split_inline_para(text)
    kinds = [s["kind"] for s in segs]
    assert kinds == ["text", "eq", "text"]
    assert segs[1]["latex"] == "x[n] = \\sin( \\frac{2\\pi f n}{f_s} )"
    # 태그 꼬리가 리터럴 텍스트로 남지 않아야 함(핵심 회귀 확인).
    assert "EQ latex" not in segs[2]["text"]
    assert "]]" not in segs[2]["text"]
    assert segs[2]["text"] == " 이 된다."
    assert segs[0]["text"] == "이는 다음 수열 "


def test_split_inline_para_eq_with_frac_braces():
    text = '식은 [[EQ latex="\\frac{2\\pi (f + m f_s) n}{f_s}"]] 이다.'
    segs = br.split_inline_para(text)
    eq = [s for s in segs if s["kind"] == "eq"][0]
    assert eq["latex"] == "\\frac{2\\pi (f + m f_s) n}{f_s}"


def test_split_inline_para_two_inline_eq_in_one_paragraph():
    text = ('처음 식 [[EQ latex="a[0] = 1"]] 그리고 두번째 식 '
            '[[EQ latex="b[1] = 2"]] 끝.')
    segs = br.split_inline_para(text)
    kinds = [s["kind"] for s in segs]
    assert kinds == ["text", "eq", "text", "eq", "text"]
    assert segs[1]["latex"] == "a[0] = 1"
    assert segs[3]["latex"] == "b[1] = 2"
    assert segs[0]["text"] == "처음 식 "
    assert segs[2]["text"] == " 그리고 두번째 식 "
    assert segs[4]["text"] == " 끝."


def test_split_inline_para_stray_double_bracket_not_eaten():
    """`]]`만 있고 여는 `[[TAG`가 없는 평범한 텍스트는 그대로 보존."""
    text = "배열 표기에서 array]] 같은 문구는 태그가 아니다."
    segs = br.split_inline_para(text)
    assert segs == [{"kind": "text", "text": text}]


def test_split_inline_para_url_tag_extracted():
    text = '참고자료는 [[URL href="https://example.com" text="링크"]] 를 보라.'
    segs = br.split_inline_para(text)
    kinds = [s["kind"] for s in segs]
    assert kinds == ["text", "url", "text"]
    assert segs[1]["url"] == "https://example.com"
    assert segs[1]["text"] == "링크"


def test_split_inline_para_fig_mid_paragraph_dies():
    """FIG/TABLE은 문단 중간 삽입 미지원 — 우회 없이 명시적으로 중단."""
    text = '그림 참고 [[FIG file="a.png"]] 이어지는 문장.'
    with pytest.raises(SystemExit):
        br.split_inline_para(text)


# ── parse_content 통합: 인라인 EQ가 문단을 여러 블록으로 쪼갠다 ─────────────

_INLINE_EQ_CONTENT = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

앞부분 [[EQ latex="x[n] = \\sin(n)"]] 뒷부분입니다.
"""


def test_parse_content_inline_eq_splits_into_three_blocks():
    meta, secs = br.parse_content(_INLINE_EQ_CONTENT)
    blocks = secs[0]["blocks"]
    kinds = [b["kind"] for b in blocks]
    assert kinds == ["para", "eq", "para"]
    assert blocks[0]["text"] == "앞부분 "
    assert blocks[0].get("para_end") is False
    assert blocks[1].get("para_end") is False
    assert blocks[2]["text"] == " 뒷부분입니다."
    assert blocks[2].get("para_end", True) is True


def test_build_ops_inline_eq_no_latex_leak_and_correct_eq_count(tmp_path):
    meta, secs = br.parse_content(_INLINE_EQ_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert not any("[[EQ" in o["text"] for o in text_ops)
    assert not any("]]" in o["text"] for o in text_ops)
    eq_ops = [o for o in ops if o["op"] == "insert_equation"]
    assert len(eq_ops) == 1


def test_build_ops_inline_eq_middle_fragment_has_no_trailing_crlf(tmp_path):
    """EQ 앞 리드인 조각은 break_after를 달면 안 된다(같은 줄에 EQ가 이어붙어야 함)."""
    meta, secs = br.parse_content(_INLINE_EQ_CONTENT)
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert text_ops[0]["text"] == "앞부분 "
    assert not text_ops[0]["text"].endswith("\r\n")
    assert "break_after" not in text_ops[0]
    assert text_ops[-1].get("break_after") is True


def test_build_ops_plain_paragraph_without_inline_tags_unaffected(tmp_path):
    """태그 없는 일반 문단은 기존과 동일하게 단일 insert_text + break_after."""
    content = """---
title: T
title_anchor: "T_ANCHOR"
base_pt: 10
---

## SECTION: I.  서론

평범한 문단입니다.
"""
    meta, secs = br.parse_content(content)
    blocks = secs[0]["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["kind"] == "para"
    assert "para_end" not in blocks[0]
    ops = br.build_ops(meta, secs, tmp_path)
    text_ops = [o for o in ops if o["op"] == "insert_text"]
    assert text_ops[0]["text"] == "평범한 문단입니다."
    assert text_ops[0]["break_after"] is True


# ── com_backend._col_widths_for_target: 표 폭 inset 보정 (table_too_wide 회귀) ──
# 실사고 evidence: HTableCreation(WidthType=2)로 ColWidth.SetItem(i, w)를 그대로
# 주면, 저장된 hwpx의 <hp:cellSz width>는 w + 1020(HwpUnit, 셀 좌우 안쪽여백
# 3.6mm 상당)이 된다 — 열마다 이 오프셋이 누적돼 저장폭 합계가 텍스트 컬럼
# 폭을 초과한다(5열 표 실측: 527pt vs 484.9pt, ~8.7% 초과). 아래는 COM 없이
# 그 역보정 산수만 고정하는 순수 함수 테스트.

def test_col_widths_for_target_saved_sum_matches_target_within_rounding():
    """SetItem에 준 값 + inset(모든 열)의 합이 target_total과 거의 같아야 한다
    (반올림 오차만 허용, 열 개수 이내)."""
    target = 47624  # 실측 s1_base.hwpx 텍스트 컬럼 폭(HwpUnit)
    ratios = [0.10, 0.16, 0.12, 0.09, 0.10, 0.43]
    widths, clamped = cb._col_widths_for_target(target, ratios)
    assert not clamped
    saved_sum = sum(w + cb.CELL_INSET_HWU for w in widths)
    assert abs(saved_sum - target) <= len(ratios)  # 반올림 오차 열당 최대 1


def test_col_widths_for_target_five_col_ratios_30_22_14_17_17():
    """과제 명세 5열 비율(30,22,14,17,17)로 실측한 것과 동일한 케이스."""
    target = 48490  # 예: 484.9pt 텍스트 컬럼(HwpUnit 환산은 케이스에 따라 다름)
    ratios_raw = [30, 22, 14, 17, 17]
    total = sum(ratios_raw)
    ratios = [r / total for r in ratios_raw]
    widths, clamped = cb._col_widths_for_target(target, ratios)
    assert not clamped
    saved_sum = sum(w + cb.CELL_INSET_HWU for w in widths)
    assert abs(saved_sum - target) <= len(ratios)
    # 이전(버그) 방식이라면 saved_sum == target + len(ratios)*inset이 되어
    # 초과했을 것 — 그 초과분이 실제로 제거되었는지 확인.
    buggy_saved_sum = sum(round(target * r) for r in ratios) + len(ratios) * cb.CELL_INSET_HWU
    assert saved_sum < buggy_saved_sum


def test_col_widths_for_target_preserves_ratio_order_larger_ratio_wider_col():
    target = 47624
    ratios = [0.10, 0.16, 0.12, 0.09, 0.10, 0.43]
    widths, _ = cb._col_widths_for_target(target, ratios)
    # 비율 순서를 절대폭 순서가 그대로 따라야 한다(inset은 전 열 동일 상수라
    # 순서를 뒤집지 않음).
    order_by_ratio = sorted(range(len(ratios)), key=lambda i: ratios[i])
    order_by_width = sorted(range(len(widths)), key=lambda i: widths[i])
    assert order_by_ratio == order_by_width


def test_col_widths_for_target_clamps_when_ratio_too_small_for_inset():
    """작은 target/많은 열/한쪽으로 쏠린 비율이면 내용폭이 inset보다 작아질
    수 있다 — min_width로 clamp되고 clamped=True가 떠야 한다(표가 안 깨짐)."""
    target = 5000  # 아주 좁은 표
    ratios = [0.05, 0.05, 0.05, 0.05, 0.80]  # 앞 4열이 극단적으로 좁음
    widths, clamped = cb._col_widths_for_target(target, ratios)
    assert clamped is True
    assert all(w >= cb.MIN_COL_CONTENT_HWU for w in widths)


def test_col_widths_for_target_no_clamp_when_ratios_generous():
    target = 47624
    ratios = [0.10, 0.16, 0.12, 0.09, 0.10, 0.43]
    _widths, clamped = cb._col_widths_for_target(target, ratios)
    assert clamped is False


def test_col_widths_for_target_matches_empirical_smoke_test_deltas():
    """실측 COM 스모크(colwidth_spike2.py, s1_base.hwpx): SetItem에 준 값
    [4762,7620,5715,4286,4762,20478]에 대해 저장된 cellSz는
    [5782,8640,6735,5306,5782,21498] — 델타가 6열 모두 정확히 1020이었다.
    이 상수가 코드의 CELL_INSET_HWU와 일치하는지 고정."""
    intended_setitem = [4762, 7620, 5715, 4286, 4762, 20478]
    saved_cellsz = [5782, 8640, 6735, 5306, 5782, 21498]
    deltas = [s - i for s, i in zip(saved_cellsz, intended_setitem)]
    assert deltas == [cb.CELL_INSET_HWU] * 6
