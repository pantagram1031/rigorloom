"""layout_qa 신규 체크(줄간격/그림배치/표/본문마커/수식누출) 회귀 테스트.

실제 픽스처(work_v0.3/out.pdf, probe15.pdf) 기반 — COM 불필요, 오프라인.
픽스처가 없으면(다른 머신) skip. `python -m pytest tests/ -q`.
"""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import layout_qa  # noqa: E402

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
FIXDIR = os.path.join(_WS, "work_v0.3") if _WS else ""
OUT_PDF = os.path.join(FIXDIR, "out.pdf") if _WS else ""
PROBE_PDF = os.path.join(FIXDIR, "probe15.pdf") if _WS else ""

pytestmark = pytest.mark.skipif(
    not (os.path.exists(OUT_PDF) and os.path.exists(PROBE_PDF)),
    reason="real fixtures (out.pdf/probe15.pdf) not present on this machine",
)


def test_analyze_backward_compatible_keys():
    res = layout_qa.analyze(OUT_PDF)
    for key in ("ok", "file", "page_count", "thresholds", "flagged_pages",
                "pass", "pages"):
        assert key in res
    assert "checks" in res
    for name in ("line_spacing_uniformity", "figure_placement", "tables",
                 "body_markers", "equations"):
        assert name in res["checks"]


def test_pass_is_and_of_old_and_new_checks():
    res = layout_qa.analyze(OUT_PDF)
    checks_pass = not any(res["checks"].values())
    old_pass = not res["flagged_pages"]
    assert res["pass"] == (old_pass and checks_pass)


def test_line_spacing_catches_t1_blank_paragraph_on_out_pdf():
    """T1: out.pdf page 1 has a stray large gap that must fire."""
    res = layout_qa.analyze(OUT_PDF)
    violations = res["checks"]["line_spacing_uniformity"]
    assert any(v["page"] == 1 for v in violations), (
        "expected check_line_spacing_uniformity to flag a violation on "
        f"out.pdf page 1; got {violations}"
    )


def test_line_spacing_exempts_section_heading_boundaries():
    """Known heading-boundary gaps (before 'I.'/'II.'/'III.' at ~15pt size)
    on out.pdf page 1 must NOT be flagged — they are legitimate section
    breaks, not blank-paragraph holes."""
    res = layout_qa.analyze(OUT_PDF)
    violations = res["checks"]["line_spacing_uniformity"]
    heading_at_y = {236.5, 378.5, 556.3}  # y0 of 'I.'/'II.'/'III.' headings
    for v in violations:
        # violation's at_y is the END of the line before the gap, so make
        # sure none of them immediately precede a heading start.
        assert not any(abs(v["at_y"] - hy) < 5 for hy in heading_at_y), (
            f"false-flagged a section-heading boundary: {v}"
        )


def test_line_spacing_probe15_no_false_positive_on_big_heading_gaps():
    res = layout_qa.analyze(PROBE_PDF)
    violations = res["checks"]["line_spacing_uniformity"]
    # The 106.9pt and 25.6pt gaps before size~15pt headings must be exempt.
    assert not any(v["gap_pt"] > 100 for v in violations)


def test_check_figure_placement_returns_list_shape():
    import fitz
    doc = fitz.open(OUT_PDF)
    for page in doc:
        violations = layout_qa.check_figure_placement(page)
        assert isinstance(violations, list)
        for v in violations:
            assert v["kind"] in ("figure_width", "caption_missing", "figure_overlap")
    doc.close()


def test_check_tables_no_false_positive_on_heading_text():
    """out.pdf page 1 has a 'III.' heading that older find_tables heuristics
    could misdetect as a 1x2 table — must be filtered as non-table noise."""
    import fitz
    doc = fitz.open(OUT_PDF)
    page = doc[0]
    violations = layout_qa.check_tables(page)
    assert violations == []
    doc.close()


def test_check_body_markers_shape():
    import fitz
    for path in (OUT_PDF, PROBE_PDF):
        doc = fitz.open(path)
        for page in doc:
            violations = layout_qa.check_body_markers(page)
            assert isinstance(violations, list)
            for v in violations:
                assert v["kind"] in ("citation_marker", "guide_remnant")
        doc.close()


def test_check_equations_no_latex_leak_in_fixtures():
    import fitz
    for path in (OUT_PDF, PROBE_PDF):
        doc = fitz.open(path)
        for page in doc:
            violations = layout_qa.check_equations(page)
            assert violations == []
        doc.close()


def test_run_new_checks_aggregates_all_pages():
    checks = layout_qa.run_new_checks(OUT_PDF)
    assert set(checks.keys()) == {
        "line_spacing_uniformity", "figure_placement", "tables",
        "body_markers", "equations",
    }
    assert all(isinstance(v, list) for v in checks.values())


# ── --guide-file / check_guide_file_remnants (pure function, no PDF needed) ──
# 픽스처 유무와 무관하게 항상 실행 — 위 pytestmark의 skip 대상이 아니다.

def test_check_guide_file_remnants_flags_synthetic_match():
    guide_strings = ["(연구의 필요성 및 목적, 연구를 수행하게 된 동기를 기술합니다.)"]
    page_text = "본문 여기\n(연구의 필요성 및 목적, 연구를 수행하게 된 동기를 기술합니다.)\n더 본문"
    violations = layout_qa.check_guide_file_remnants(page_text, guide_strings)
    assert len(violations) == 1
    assert violations[0]["kind"] == "guide_remnant"


def test_check_guide_file_remnants_normalizes_whitespace():
    guide_strings = ["안내문 첫 스무자 정도의 긴 문구입니다 더 길게"]
    page_text = "머리말\n안내문   첫\n스무자  정도의\t긴 문구입니다 더 길게 (본문 뒤이어짐)"
    violations = layout_qa.check_guide_file_remnants(page_text, guide_strings)
    assert len(violations) == 1


def test_check_guide_file_remnants_no_match_returns_empty():
    violations = layout_qa.check_guide_file_remnants("아무 상관없는 본문", ["전혀 다른 안내문 문구"])
    assert violations == []


def test_check_guide_file_remnants_absent_guide_strings_is_noop():
    assert layout_qa.check_guide_file_remnants("본문", None) == []
    assert layout_qa.check_guide_file_remnants("본문", []) == []


def test_run_new_checks_guide_strings_absent_unchanged():
    """guide_strings 생략 시 run_new_checks 결과가 기존과 동일해야 한다(가산적)."""
    checks_without = layout_qa.run_new_checks(OUT_PDF)
    checks_with_none = layout_qa.run_new_checks(OUT_PDF, guide_strings=None)
    assert checks_without == checks_with_none


# ── BUG3: --spacing-skip-pages + bottom-10% page-break exemption ──────────
# 픽스처 유무와 무관하게 항상 실행 — synthetic in-memory fitz 페이지만 쓴다
# (pytestmark의 skip 대상 fixtures를 참조하지 않음).

def _synthetic_page_with_bottom_gap():
    """정상 본문 6줄 + 페이지 하단 10%(842*0.9=757.8pt) 안에서 시작하는 큰 간격
    + 그 아래 흘러넘친 한 줄. 페이지 나눔 아티팩트를 흉내낸다."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 100
    for i in range(6):
        page.insert_text((50, y), f"line {i} of body text here", fontsize=10)
        y += 14
    page.insert_text((50, 770), "last body line near bottom", fontsize=10)   # a.y1 ~773 (>90%)
    page.insert_text((50, 830), "stray trailing line far below", fontsize=10)
    return doc, page


def test_synthetic_gap_at_95pct_page_height_not_flagged():
    doc, page = _synthetic_page_with_bottom_gap()
    violations = layout_qa.check_line_spacing_uniformity(page)
    # the gap whose start (a.y1) sits in the bottom 10% must be exempt.
    assert not any(v["at_y"] > 757.8 for v in violations)
    doc.close()


def test_synthetic_mid_page_gap_still_flagged_by_default():
    """하단 10% 밖의 진짜 간격은 기존처럼 계속 flag 되어야 한다(회귀 방지)."""
    doc, page = _synthetic_page_with_bottom_gap()
    violations = layout_qa.check_line_spacing_uniformity(page)
    assert any(v["at_y"] < 700 for v in violations)
    doc.close()


def test_spacing_skip_pages_honored_via_page_num():
    doc, page = _synthetic_page_with_bottom_gap()
    # without skip: mid-page gap flagged.
    assert layout_qa.check_line_spacing_uniformity(page, page_num=1) != []
    # with page 1 in spacing_skip_pages: check is skipped entirely.
    assert layout_qa.check_line_spacing_uniformity(
        page, page_num=1, spacing_skip_pages={1}) == []
    # a different page number not in the skip set behaves normally.
    assert layout_qa.check_line_spacing_uniformity(
        page, page_num=2, spacing_skip_pages={1}) != []
    doc.close()


def test_spacing_skip_pages_absent_is_default_behavior():
    """spacing_skip_pages 생략(None) 시 명시적으로 빈 집합을 준 것과 동일하지
    않음(빈 집합/None 모두 스킵 없음) — 기존 동작과 완전히 동일해야 한다."""
    doc, page = _synthetic_page_with_bottom_gap()
    default = layout_qa.check_line_spacing_uniformity(page)
    explicit_none = layout_qa.check_line_spacing_uniformity(page, spacing_skip_pages=None)
    assert default == explicit_none
    doc.close()


def test_run_new_checks_spacing_skip_pages_threads_through():
    """run_new_checks(spacing_skip_pages=...) 가 실제로 해당 페이지의
    line_spacing_uniformity 위반을 제거해야 한다."""
    checks_default = layout_qa.run_new_checks(OUT_PDF)
    default_pages = {v["page"] for v in checks_default["line_spacing_uniformity"]}
    assert default_pages, "expected out.pdf to have at least one flagged page (T1 fixture)"
    a_page = sorted(default_pages)[0]
    checks_skipped = layout_qa.run_new_checks(OUT_PDF, spacing_skip_pages={a_page})
    remaining_pages = {v["page"] for v in checks_skipped["line_spacing_uniformity"]}
    assert a_page not in remaining_pages


def test_parse_skip_pages_cli_helper():
    assert layout_qa.parse_skip_pages("1,2") == {1, 2}
    assert layout_qa.parse_skip_pages(" 1 , 2 ") == {1, 2}
    assert layout_qa.parse_skip_pages("") is None
    assert layout_qa.parse_skip_pages(None) is None


def test_analyze_spacing_skip_pages_default_unchanged():
    """analyze()에 spacing_skip_pages를 안 주면 결과가 기존과 완전히 동일."""
    res_default = layout_qa.analyze(OUT_PDF)
    res_explicit_none = layout_qa.analyze(OUT_PDF, spacing_skip_pages=None)
    assert res_default == res_explicit_none


# ── --gap-skip-pages: max_gap_lines(구멍) 체크 페이지 예외 ──────────────────
# 픽스처 유무와 무관하게 항상 실행 — synthetic in-memory PDF만 쓴다(module-level
# pytestmark의 skip 대상 fixtures를 참조하지 않음). spacing_skip_pages와 대칭
# 설계: 생략 시 기존 동작과 완전히 동일(가산적), 지정 페이지는 flags에서만 면제
# (max_gap_lines 측정값 자체는 계속 보존/보고된다).

def _write_synthetic_gap_pdf(tmp_path):
    """본문 2줄 + 아주 큰 중간 간격(구멍) + 본문 1줄 짜리 1쪽 PDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "top body line one", fontsize=10)
    page.insert_text((50, 114), "top body line two", fontsize=10)
    page.insert_text((50, 400), "isolated line far below (the gap)", fontsize=10)
    path = tmp_path / "synthetic_gap.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_synthetic_gap_page_flagged_by_default(tmp_path):
    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    res = layout_qa.analyze(pdf_path, gap_thr=3.0)
    assert res["pages"][0]["max_gap_lines"] > 3.0
    assert 1 in res["flagged_pages"]


def test_gap_skip_pages_exempts_page_from_flags(tmp_path):
    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    res = layout_qa.analyze(pdf_path, gap_thr=3.0, gap_skip_pages={1})
    assert 1 not in res["flagged_pages"]
    assert not any("max_gap" in f for f in res["pages"][0]["flags"])
    # measurement itself is preserved, only the flag is suppressed.
    assert res["pages"][0]["max_gap_lines"] > 3.0


def test_gap_skip_pages_only_exempts_listed_page(tmp_path):
    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    res = layout_qa.analyze(pdf_path, gap_thr=3.0, gap_skip_pages={2})
    assert 1 in res["flagged_pages"]  # page 1 not in the skip set — still flagged


def test_gap_skip_pages_absent_is_default_behavior(tmp_path):
    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    res_default = layout_qa.analyze(pdf_path, gap_thr=3.0)
    res_explicit_none = layout_qa.analyze(pdf_path, gap_thr=3.0, gap_skip_pages=None)
    assert res_default == res_explicit_none


# ── _is_footer_line / footer exclusion from max_gap_lines ──────────────────
# Scoped fix: page-number footers ("- 1 -") sitting in the bottom 8% of the
# page must not count as the "content" that ends a gap — an undeletable
# footer masks the true last-caption-to-page-end distance (page 11's 41-line
# "gap" was actually last-caption -> footer, not a real blank-paragraph hole).
# This filter applies ONLY to the max_gap_lines computation; bottom_white_pct
# and other checks are untouched (filtering footers there would newly flag
# designed cover pages with intentional bottom whitespace).

PAGE_H = 842.0  # A4-ish height used by the synthetic fixtures in this file


def test_is_footer_line_matches_dashed_page_number_in_bottom_margin():
    y0 = PAGE_H * 0.95  # well within bottom 8%
    assert layout_qa._is_footer_line("- 1 -", y0, PAGE_H) is True


def test_is_footer_line_matches_plain_number_and_em_dash_variants():
    y0 = PAGE_H * 0.95
    assert layout_qa._is_footer_line("1", y0, PAGE_H) is True
    assert layout_qa._is_footer_line("— 3 —", y0, PAGE_H) is True
    assert layout_qa._is_footer_line("  12  ", y0, PAGE_H) is True


def test_is_footer_line_mid_page_number_not_matched():
    """A page-number-shaped line sitting mid-page (e.g. a list item) is not
    a footer — only bottom-8% position + numeric form together qualify."""
    y0 = PAGE_H * 0.5
    assert layout_qa._is_footer_line("- 1 -", y0, PAGE_H) is False


def test_is_footer_line_non_numeric_bottom_line_not_matched():
    """A caption or copyright line at the bottom of the page is not a page
    number and must not be treated as a footer."""
    y0 = PAGE_H * 0.95
    assert layout_qa._is_footer_line("그림 3. 실험 장치", y0, PAGE_H) is False
    assert layout_qa._is_footer_line("(c) 2026 all rights reserved", y0, PAGE_H) is False


def test_is_footer_line_no_page_height_is_never_footer():
    assert layout_qa._is_footer_line("- 1 -", 800.0, 0) is False
    assert layout_qa._is_footer_line("- 1 -", 800.0, None) is False


def _write_synthetic_footer_gap_pdf(tmp_path):
    """Caption near the top, then nothing until a page-number footer
    ("- 1 -") deep in the bottom margin. Models page 11's 41-line 'gap':
    last-caption -> footer distance, which is undeletable by any paragraph
    cleanup and must NOT count as a max_gap_lines hole."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "top body line one", fontsize=10)
    page.insert_text((50, 114), "last caption line", fontsize=10)
    page.insert_text((50, 810), "- 1 -", fontsize=10)  # bottom ~96% of 842
    path = tmp_path / "synthetic_footer_gap.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_analyze_excludes_footer_from_max_gap_lines(tmp_path):
    pdf_path = _write_synthetic_footer_gap_pdf(tmp_path)
    res = layout_qa.analyze(pdf_path, gap_thr=3.0)
    # without the footer counted as content-ending-the-gap, there is no
    # trailing text block to form a large gap against on this single page.
    assert res["pages"][0]["max_gap_lines"] <= 3.0
    assert 1 not in res["flagged_pages"]


def test_analyze_gap_still_flagged_when_no_footer_present(tmp_path):
    """Regression guard: the ordinary blank-paragraph gap case (no footer
    involved) must still be flagged exactly as before."""
    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    res = layout_qa.analyze(pdf_path, gap_thr=3.0)
    assert res["pages"][0]["max_gap_lines"] > 3.0
    assert 1 in res["flagged_pages"]


def test_fill_report_build_verdict_threads_gap_skip_pages(tmp_path, monkeypatch):
    """fill_report.build_verdict(gap_skip_pages=...) 가 layout_qa.analyze로
    실제 전달되는지 확인(측정 모드 CLI --gap-skip-pages 배선의 핵심 지점)."""
    import fill_report

    pdf_path = _write_synthetic_gap_pdf(tmp_path)
    seen = {}
    real_analyze = layout_qa.analyze

    def spy_analyze(*args, **kwargs):
        seen["gap_skip_pages"] = kwargs.get("gap_skip_pages")
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(fill_report.layout_qa, "analyze", spy_analyze)
    fill = dict(fill_report.FILL_DEFAULTS)
    fill_report.build_verdict(pdf_path, fill, fig_count_override=0,
                              gap_skip_pages={1})
    assert seen["gap_skip_pages"] == {1}


def test_analyze_gap_skip_pages_does_not_affect_bottom_white_flag(tmp_path):
    """gap-skip은 max_gap flag만 면제한다 — bottom_white flag는 별개 체크로 불변."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "single top line, huge bottom white space",
                      fontsize=10)
    doc.new_page(width=595, height=842).insert_text(
        (50, 100), "second page so first page's bottom_white isn't last-page-exempt",
        fontsize=10)
    path = tmp_path / "bottom_white.pdf"
    doc.save(str(path))
    doc.close()
    res = layout_qa.analyze(str(path), bottom_thr=25.0, gap_skip_pages={1})
    assert any("bottom_white" in f for f in res["pages"][0]["flags"])

