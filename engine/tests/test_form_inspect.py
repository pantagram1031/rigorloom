"""form_inspect / style_diff 회귀 테스트 (Codex-review 블로커 수정분).

실제 픽스처(templates/*.hwpx, work_v0.3/out.hwpx) 기반 — 없으면 skip.
합성 hwpx(attribute-order/quote-variant robustness)는 tmp_path에 직접 zip 생성.
`python -m pytest tests/ -q`.
"""
import os
import re
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
TEMPLATES_DIR = os.path.join(_WS, "templates") if _WS else ""
SONON_FORM = os.path.join(TEMPLATES_DIR, "소논문_기본양식.hwpx") if _WS else ""
DAESU_FORM = os.path.join(TEMPLATES_DIR, "대수_추가탐구기록지_양식.hwpx") if _WS else ""
OUT_HWPX = os.path.join(_WS, "work_v0.3", "out.hwpx") if _WS else ""

pytestmark = pytest.mark.skipif(
    not os.path.exists(SONON_FORM),
    reason="real fixture (소논문_기본양식.hwpx) not present on this machine",
)


# ---------------------------------------------------------------------------
# BLOCKER 3: colored real heading (also anchor) must NOT land in removal_targets
# ---------------------------------------------------------------------------

def test_colored_heading_not_removed():
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    anchor_set = set(profile["anchors"])
    removal_idx = {t["para_idx"] for t in profile["removal_targets"]}
    # 모든 guide_text 중 텍스트가 anchor 목록에도 있는 문단(실제 구조로도 잡힘)은
    # removal_targets에서 반드시 빠져야 한다.
    for g in profile["guide_text"]:
        if g["text"].strip() in anchor_set:
            assert g["para_idx"] not in removal_idx, (
                f"anchor paragraph {g['para_idx']!r} must not be a removal target"
            )


def test_removal_targets_have_confidence_and_policy():
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    assert "removal_policy" in profile
    assert isinstance(profile["removal_policy"], str) and profile["removal_policy"]
    for t in profile["removal_targets"]:
        assert set(t.keys()) == {"para_idx", "confidence"}
        assert t["confidence"] in ("high", "medium")


def test_removal_targets_shrunk_by_anchor_exclusion():
    """실제 픽스처 회귀값: anchor와 겹치는 5개 문단이 빠져 16 -> 11."""
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    guide_idx = {g["para_idx"] for g in profile["guide_text"]}
    removal_idx = {t["para_idx"] for t in profile["removal_targets"]}
    assert len(guide_idx) == 16
    assert len(removal_idx) == 11
    assert removal_idx < guide_idx


# ---------------------------------------------------------------------------
# BLOCKER 4: guide-only colors must not leak into baseline `colors`
# ---------------------------------------------------------------------------

def test_guide_only_color_flagged():
    _, baseline = form_inspect.analyze(SONON_FORM, want_baseline=True)
    assert "#FF0000" in baseline["guide_only_colors"]
    assert "#FF0000" not in baseline["colors"]


def test_style_diff_flags_leftover_guide_color(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import style_diff  # noqa: E402

    if not os.path.exists(OUT_HWPX):
        pytest.skip("real fixture (work_v0.3/out.hwpx) not present on this machine")

    _, baseline = form_inspect.analyze(SONON_FORM, want_baseline=True)
    result = style_diff.analyze(OUT_HWPX, baseline)
    kinds = {a["kind"]: a for a in result["anomalies"]}
    colors_flagged = {a["value"] for a in result["anomalies"] if a["kind"] == "color"}
    assert "#FF0000" in colors_flagged  # guide-only color leaked into output
    assert not result["ok"]


def test_style_diff_always_flags_hyperlink_blue():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import style_diff  # noqa: E402

    if not os.path.exists(OUT_HWPX):
        pytest.skip("real fixture (work_v0.3/out.hwpx) not present on this machine")

    _, baseline = form_inspect.analyze(SONON_FORM, want_baseline=True)
    # 설령 baseline.colors에 과거 버전 호환으로 #0000FF가 남아있어도 항상 flag.
    baseline = dict(baseline)
    baseline["colors"] = list(baseline["colors"]) + ["#0000FF"]
    result = style_diff.analyze(OUT_HWPX, baseline)
    colors_flagged = {a["value"] for a in result["anomalies"] if a["kind"] == "color"}
    assert "#0000FF" in colors_flagged


def test_style_diff_allow_colors_suppresses_hyperlink_blue():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import style_diff  # noqa: E402

    if not os.path.exists(OUT_HWPX):
        pytest.skip("real fixture (work_v0.3/out.hwpx) not present on this machine")

    _, baseline = form_inspect.analyze(SONON_FORM, want_baseline=True)
    result = style_diff.analyze(OUT_HWPX, baseline, build_cfg={"allow_colors": ["#0000FF"]})
    colors_flagged = {a["value"] for a in result["anomalies"] if a["kind"] == "color"}
    assert "#0000FF" not in colors_flagged


# ---------------------------------------------------------------------------
# Constraint keyword-context regex (MINOR)
# ---------------------------------------------------------------------------

def test_constraints_extracted_from_real_form():
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    c = profile["constraints"]
    assert c["base_pt"] == 10
    assert c["line_spacing_pct"] == 180
    assert c["max_pages"] == 20


def test_constraint_pt_requires_keyword_context():
    # "10명이 10pt 크기로 참여했다" 처럼 글자/폰트 문맥이 없는 숫자+pt는 오탐 금지.
    guide_texts = ["실험 참가자는 10명, 측정 오차는 10pt 였다"]
    c = form_inspect._parse_constraints(guide_texts)
    assert c["base_pt"] is None


def test_constraint_pt_matches_with_font_keyword():
    guide_texts = ["본문 글자크기 10포인트로 작성하세요"]
    c = form_inspect._parse_constraints(guide_texts)
    assert c["base_pt"] == 10


def test_constraint_spacing_requires_both_keywords():
    guide_texts = ["할인율은 180% 적용됩니다"]  # "줄"도 "간격"도 없음
    c = form_inspect._parse_constraints(guide_texts)
    assert c["line_spacing_pct"] is None


# ---------------------------------------------------------------------------
# BUG: regex XML fragility — attribute order / quote / namespace prefix
# ---------------------------------------------------------------------------

def _build_synthetic_hwpx(tmp_path, header_xml, section_xml):
    path = tmp_path / "synthetic.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header_xml)
        z.writestr("Contents/section0.xml", section_xml)
    return str(path)


def test_attribute_order_robustness(tmp_path):
    # charPr 속성 순서를 표준(id 먼저)과 반대로(속성 뒤섞기), run도 charPrIDRef가
    # 첫 속성이 아니게 구성 — 실제 다른 생산자가 만든 hwpx를 흉내.
    # textColor는 검정(비-guide 판정 유지)으로 둬 baseline 색 집계 대상이 되게 한다.
    header = (
        '<hh:charPr textColor="#000000" height="1200" id="5">'
        '<hh:fontRef latin="2" hangul="1"/></hh:charPr>'
    )
    section = (
        '<hp:p someattr="x" paraPrIDRef="0">'
        '<hp:run extra="z" charPrIDRef="5">'
        "<hp:t>reordered attrs</hp:t></hp:run></hp:p>"
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, baseline = form_inspect.analyze(path, want_baseline=True)
    assert profile["ok"]
    assert 12.0 in baseline["sizes_pt"]
    assert baseline["charpr_hist"] == {"5": 1}


def test_quote_variant_parsing(tmp_path):
    # 큰따옴표 대신 작은따옴표를 쓰는 생산자 대응.
    header = (
        "<hh:charPr id='9' height='1000' textColor='#000000'>"
        "<hh:fontRef hangul='3'/></hh:charPr>"
    )
    section = (
        "<hp:p paraPrIDRef='0'>"
        "<hp:run charPrIDRef='9'><hp:t>single quoted</hp:t></hp:run></hp:p>"
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, baseline = form_inspect.analyze(path, want_baseline=True)
    assert profile["ok"]
    assert 10.0 in baseline["sizes_pt"]
    assert profile["guide_text"] == []


def test_color_extraction_robust_to_attr_order_and_quotes():
    # 속성 순서 뒤섞기 + 작은따옴표 + 임의 prefix 조합에서도 color/height 추출.
    header = (
        "<zz:charPr textColor='#AA00BB' id='42' height='900'>"
        "</zz:charPr>"
    )
    defs = form_inspect._charpr_defs(header)
    assert defs["42"]["color"] == "#AA00BB"
    assert defs["42"]["height_pt"] == 9.0


# ---------------------------------------------------------------------------
# form_inspect v2: page_metrics / table_map / break_audit
# ---------------------------------------------------------------------------

def test_page_metrics_golden_numbers():
    # 손계산(소논문_기본양식.hwpx의 hp:pagePr/hp:margin 실측값 기준):
    # width=59528 height=84188, left=1417 right=4251 top=2834 bottom=2834
    # header=2834 footer=2834 gutter=5669.
    # usable_width = 59528-1417-4251 = 53860
    # usable_height = 84188-2834-2834-2834-2834 = 72852
    # line_height(base_pt=10, spacing=160%) = 10*100*160/100 = 1600
    # lines_per_page = floor(72852/1600) = 45
    # chars_per_line = floor(53860/1000) = 53
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    pm = profile["page_metrics"]
    assert pm["width"] == 59528
    assert pm["height"] == 84188
    assert pm["margin"] == {
        "left": 1417, "right": 4251, "top": 2834, "bottom": 2834,
        "header": 2834, "footer": 2834, "gutter": 5669,
    }
    assert pm["usable_width"] == 53860
    assert pm["usable_height"] == 72852
    assert pm["lines_per_page"] == 45
    assert pm["chars_per_line"] == 53
    assert pm["assumptions"]["base_pt"] == 10
    assert pm["assumptions"]["line_spacing_pct"] == 160


def test_page_metrics_respects_cli_args():
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False,
                                       base_pt=12, line_spacing_pct=200)
    pm = profile["page_metrics"]
    # line_height = 12*100*200/100 = 2400; lines_per_page = floor(72852/2400) = 30
    assert pm["assumptions"]["base_pt"] == 12
    assert pm["assumptions"]["line_spacing_pct"] == 200
    assert pm["lines_per_page"] == 30
    # chars_per_line = floor(53860/1200) = 44
    assert pm["chars_per_line"] == 44


def test_break_audit_counts_real_form():
    # 손계산(소논문_기본양식.hwpx header.xml, hh:breakSetting widowOrphan="1" 등
    # 문자열 카운트 실측): widowOrphan=3 keepWithNext=8 keepLines=0
    # pageBreakBefore=0, paraPr 총 46개.
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    ba = profile["break_audit"]
    assert ba == {
        "widowOrphan": 3,
        "keepWithNext": 8,
        "keepLines": 0,
        "pageBreakBefore": 0,
        "total_parapr": 46,
    }


@pytest.mark.skipif(not os.path.exists(DAESU_FORM),
                     reason="real fixture (대수_추가탐구기록지_양식.hwpx) not present")
def test_table_map_flags_shaded_cell_and_cellsz():
    # 대수_추가탐구기록지_양식.hwpx table[0] cell(row0,col0)은
    # borderFillIDRef=6 -> header.xml winBrush faceColor="#E0E0E0" (음영 있음).
    # cell(row1,col0)은 borderFillIDRef=5 (fillBrush 없음 -> 음영 없음).
    profile, _ = form_inspect.analyze(DAESU_FORM, want_baseline=False)
    tables = profile["table_map"]
    assert len(tables) == 2
    t0 = tables[0]
    assert t0["rowCnt"] == 4
    assert t0["colCnt"] == 1
    assert t0["pageBreak"] == "CELL"
    assert t0["repeatHeader"] == "1"
    cells_by_addr = {(c["addr"]["row"], c["addr"]["col"]): c for c in t0["cells"] if c["addr"]}
    shaded_cell = cells_by_addr[(0, 0)]
    assert shaded_cell["borderFillIDRef"] == "6"
    assert shaded_cell["shaded"] is True
    assert shaded_cell["width"] == 46199
    assert shaded_cell["height"] == 1848

    unshaded_cell = cells_by_addr[(1, 0)]
    assert unshaded_cell["borderFillIDRef"] == "5"
    assert unshaded_cell["shaded"] is False
    assert unshaded_cell["width"] == 46199
    assert unshaded_cell["height"] == 4297


@pytest.mark.skipif(not os.path.exists(DAESU_FORM),
                     reason="real fixture (대수_추가탐구기록지_양식.hwpx) not present")
def test_table_map_classifies_cells():
    profile, _ = form_inspect.analyze(DAESU_FORM, want_baseline=False)
    t0 = profile["table_map"][0]
    cells_by_addr = {(c["addr"]["row"], c["addr"]["col"]): c for c in t0["cells"] if c["addr"]}
    # (row1,col0)은 "~작성합니다" 류 지시어를 담은 안내문 셀.
    assert cells_by_addr[(1, 0)]["classification"] == "guide"
    # (row3,col0)은 빈 셀 -> 채워야 할 대상.
    assert cells_by_addr[(3, 0)]["classification"] == "fill_target"
    # (row0,col0) "작성요령" 은 안내문 키워드/색 매치 없음 -> static.
    assert cells_by_addr[(0, 0)]["classification"] == "static"


def test_table_map_covers_all_sections():
    profile, _ = form_inspect.analyze(SONON_FORM, want_baseline=False)
    assert len(profile["table_map"]) == profile["format_hints"]["table_count"]
    for i, t in enumerate(profile["table_map"]):
        assert t["index"] == i
        assert t["rowCnt"] * t["colCnt"] >= 1
        for c in t["cells"]:
            assert "text_preview" in c and len(c["text_preview"]) <= 30


def test_namespace_prefix_agnostic(tmp_path):
    # hp:/hh: 대신 임의 prefix(x:/y:)를 쓰는 생산자 대응.
    header = (
        '<y:charPr id="1" height="1100" textColor="#000000">'
        '<y:fontRef hangul="2"/></y:charPr>'
    )
    section = (
        '<x:p paraPrIDRef="0">'
        '<x:run charPrIDRef="1"><x:t>diff prefix</x:t></x:run></x:p>'
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, baseline = form_inspect.analyze(path, want_baseline=True)
    assert profile["ok"]
    assert 11.0 in baseline["sizes_pt"]
    assert profile["guide_text"] == []


# ---------------------------------------------------------------------------
# Rule 1: anchors_blanks_before (form-native blank paragraph preservation)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(DAESU_FORM),
                     reason="real fixture (대수_추가탐구기록지_양식.hwpx) not present")
def test_anchors_blanks_before_present_for_summary_heading():
    """Verify #1(operator): 대수 pristine form의 '대수 탐구 기록지 요약' 앵커는
    앞에 pristine-form 빈 문단이 다수 있어야 한다(표지-요약 페이지 분리 여백) —
    구 tidy(keep=1 전역)가 이걸 뭉개 요약을 1페이지로 끌어당기던 버그의 근거값."""
    profile, _ = form_inspect.analyze(DAESU_FORM, want_baseline=False)
    assert "anchors_blanks_before" in profile
    blanks = profile["anchors_blanks_before"]
    assert "대수 탐구 기록지 요약" in blanks
    assert blanks["대수 탐구 기록지 요약"] > 1  # keep=1로는 못 보존하는 규모


@pytest.mark.skipif(not os.path.exists(DAESU_FORM),
                     reason="real fixture (대수_추가탐구기록지_양식.hwpx) not present")
def test_anchors_blanks_before_covers_all_anchors_keys_subset():
    """anchors_blanks_before의 키는 모두 anchors 목록의 원소여야 한다(모호/미매치
    anchor는 조용히 생략되므로 부분집합 — 전체 커버리지를 강제하지 않음)."""
    profile, _ = form_inspect.analyze(DAESU_FORM, want_baseline=False)
    anchor_set = set(profile["anchors"])
    assert set(profile["anchors_blanks_before"].keys()) <= anchor_set


def test_blanks_before_map_counts_consecutive_empty_top_level_paragraphs(tmp_path):
    """합성 hwpx: anchor 앞에 정확히 3개의 빈 top-level 문단이 있으면
    blanks_before == 3이어야 한다."""
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    blank_p = '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p>'
    section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>머리말</hp:t></hp:run></hp:p>'
        + blank_p * 3 +
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>[앵커]</hp:t></hp:run></hp:p>'
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, _ = form_inspect.analyze(path, want_baseline=False)
    assert profile["anchors_blanks_before"].get("[앵커]") == 3


def test_blanks_before_zero_when_no_blank_paragraph_precedes(tmp_path):
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>본문 바로 앞</hp:t></hp:run></hp:p>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>[앵커2]</hp:t></hp:run></hp:p>'
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, _ = form_inspect.analyze(path, want_baseline=False)
    assert profile["anchors_blanks_before"].get("[앵커2]") == 0


def test_blanks_before_skipped_for_ambiguous_anchor_in_same_section(tmp_path):
    """같은 섹션에서 anchor 텍스트가 2번 나오면 그 섹션에서는 판정하지 않는다
    (모호함 — die 대신 조용히 생략, form_inspect는 진단 전용이라 안전 우선)."""
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    blank_p = '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p>'
    dup_p = ('<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
             '<hp:t>[중복앵커]</hp:t></hp:run></hp:p>')
    section = blank_p * 2 + dup_p + blank_p + dup_p
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, _ = form_inspect.analyze(path, want_baseline=False)
    assert "[중복앵커]" not in profile["anchors_blanks_before"]


def test_blanks_before_ignores_nested_table_cell_paragraphs(tmp_path):
    """표 셀 내부 문단은 top-level 판정에서 제외되어야 한다 — 표 앞에 빈
    top-level 문단이 없으면(표 자체가 non-empty 취급) blanks_before==0."""
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    table = (
        '<hp:tbl rowCnt="1" colCnt="1">'
        '<hp:tr><hp:tc>'
        '<hp:subList><hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p></hp:subList>'
        '</hp:tc></hp:tr></hp:tbl>'
    )
    section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">' + table + '</hp:run></hp:p>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>[표뒤앵커]</hp:t></hp:run></hp:p>'
    )
    path = _build_synthetic_hwpx(tmp_path, header, section)
    profile, _ = form_inspect.analyze(path, want_baseline=False)
    # 표를 담은 문단은 비어있지 않다고 취급되므로(그 안 빈 문단은 무관),
    # [표뒤앵커] 바로 앞 top-level 문단은 표-문단(비어있지 않음) -> blanks_before=0.
    assert profile["anchors_blanks_before"].get("[표뒤앵커]") == 0
