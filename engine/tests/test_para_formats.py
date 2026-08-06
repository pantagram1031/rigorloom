"""form_inspect.para_formats / style_diff.check_para_formats 회귀 테스트.

문단 서식(정렬/줄간격/글자크기) 시각적 보존 검증. 실제 픽스처:
templates/대수_추가탐구기록지_양식.hwpx(pristine baseline)와
reports/report-aliasing-sampling/output/out.hwpx(조립 결과) — 없으면 skip.
합성 hwpx(정렬 파싱 단위 테스트)는 tmp_path에 직접 zip 생성.
`python -m pytest tests/ -q`.
"""
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402
import style_diff  # noqa: E402

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
FORM = os.path.join(_WS, "templates", "대수_추가탐구기록지_양식.hwpx") if _WS else ""
OUT = os.path.join(_WS, "reports", "report-aliasing-sampling", "output", "out.hwpx") if _WS else ""

pytestmark = pytest.mark.skipif(
    not (os.path.exists(FORM) and os.path.exists(OUT)),
    reason="real fixtures (baseline form / assembled output) not present on this machine",
)


# ---------------------------------------------------------------------------
# baseline extraction shape
# ---------------------------------------------------------------------------

def test_para_formats_shape():
    _, baseline = form_inspect.analyze(FORM, want_baseline=True)
    assert "para_formats" in baseline
    entries = baseline["para_formats"]
    assert len(entries) > 0
    for e in entries:
        assert set(e.keys()) == {
            "text_head", "para_idx", "align", "line_spacing", "char_pt", "bold",
        }
        assert e["align"] in ("left", "center", "right", "justify", "distribute", None)
        if e["line_spacing"] is not None:
            assert set(e["line_spacing"].keys()) == {"type", "value"}


def test_para_formats_cover_title_is_right_and_headings_are_center():
    # 실제 픽스처 회귀값: 표지 상단은 right, 대단원 제목(Ⅰ~Ⅵ)은 center.
    _, baseline = form_inspect.analyze(FORM, want_baseline=True)
    by_head = {e["text_head"]: e for e in baseline["para_formats"]}
    assert by_head["함수·수열(대수) 모델 구상 및 비판"]["align"] == "right"
    assert by_head["Ⅰ. 서 론"]["align"] == "center"
    assert by_head["II.  이론적 배경"]["align"] == "center"


def test_para_formats_only_covers_anchor_heading_placeholder_paragraphs():
    profile, baseline = form_inspect.analyze(FORM, want_baseline=True)
    heads = {e["text_head"] for e in baseline["para_formats"]}
    # 일반 본문 안내문(guide_text, 앵커/제목 아님)은 para_formats에 없어야 함.
    plain_guide = [g for g in profile["guide_text"]
                   if g["text"].strip()[:20] not in heads and len(g["text"].strip()) > 20]
    assert len(plain_guide) > 0  # 이런 문단이 실제로 존재함(대조군)


# ---------------------------------------------------------------------------
# alignment parsed correctly (synthetic XML)
# ---------------------------------------------------------------------------

def test_align_map_parses_center_right_justify(tmp_path):
    header = (
        '<hh:paraPr id="0"><hh:align horizontal="CENTER" vertical="BASELINE"/></hh:paraPr>'
        '<hh:paraPr id="1"><hh:align horizontal="RIGHT" vertical="BASELINE"/></hh:paraPr>'
        '<hh:paraPr id="2"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/></hh:paraPr>'
        '<hh:paraPr id="3"><hh:align horizontal="LEFT" vertical="BASELINE"/></hh:paraPr>'
    )
    align_map = form_inspect._align_map(header)
    assert align_map == {"0": "center", "1": "right", "2": "justify", "3": "left"}


def test_align_map_unknown_value_passthrough_lowercased():
    header = '<hh:paraPr id="0"><hh:align horizontal="DISTRIBUTE" vertical="BASELINE"/></hh:paraPr>'
    align_map = form_inspect._align_map(header)
    assert align_map["0"] == "distribute"


def test_bold_map_detects_empty_tag_marker():
    header = (
        '<hh:charPr id="1" height="1600"><hh:bold/>'
        '<hh:underline type="NONE"/></hh:charPr>'
        '<hh:charPr id="2" height="1000">'
        '<hh:underline type="NONE"/></hh:charPr>'
    )
    bold_map = form_inspect._bold_map(header)
    assert bold_map == {"1": True, "2": False}


# ---------------------------------------------------------------------------
# changed-alignment flagged / new-paragraph mass not flagged
# ---------------------------------------------------------------------------

def _build_hwpx(tmp_path, name, header_xml, section_xml):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header_xml)
        z.writestr("Contents/section0.xml", section_xml)
    return str(path)


def _header_with_two_parapr(align_a, align_b):
    return (
        '<hh:paraPr id="0"><hh:align horizontal="%s" vertical="BASELINE"/>'
        '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:paraPr id="1"><hh:align horizontal="%s" vertical="BASELINE"/>'
        '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:charPr id="9" height="1600" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    ) % (align_a, align_b)


def test_changed_alignment_is_flagged(tmp_path):
    form_header = _header_with_two_parapr("CENTER", "LEFT")
    form_section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="9">'
        '<hp:t>Ⅰ. 서 론</hp:t></hp:run></hp:p>'
    )
    form_path = _build_hwpx(tmp_path, "form.hwpx", form_header, form_section)

    # out: 같은 텍스트지만 paraPr이 LEFT(id=1)로 바뀜 — align 변경.
    out_header = _header_with_two_parapr("CENTER", "LEFT")
    out_section = (
        '<hp:p paraPrIDRef="1"><hp:run charPrIDRef="9">'
        '<hp:t>Ⅰ. 서 론</hp:t></hp:run></hp:p>'
    )
    out_path = _build_hwpx(tmp_path, "out.hwpx", out_header, out_section)

    result = style_diff.check_para_formats(form_path, out_path)
    align_anomalies = [a for a in result["anomalies"] if a["field"] == "align"]
    assert any(a["text_head"] == "Ⅰ. 서 론" for a in align_anomalies)
    assert not result["ok"]


def test_new_paragraph_mass_not_flagged(tmp_path):
    form_header = _header_with_two_parapr("CENTER", "JUSTIFY")
    form_section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="9">'
        '<hp:t>Ⅰ. 서 론</hp:t></hp:run></hp:p>'
    )
    form_path = _build_hwpx(tmp_path, "form.hwpx", form_header, form_section)

    # out: 원래 anchor 문단은 그대로 유지 + 새 본문 문단(justify) 다수 추가.
    out_header = _header_with_two_parapr("CENTER", "JUSTIFY")
    body_paras = "".join(
        '<hp:p paraPrIDRef="1"><hp:run charPrIDRef="9">'
        f'<hp:t>새로 추가된 본문 {i}</hp:t></hp:run></hp:p>'
        for i in range(5)
    )
    out_section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="9">'
        '<hp:t>Ⅰ. 서 론</hp:t></hp:run></hp:p>' + body_paras
    )
    out_path = _build_hwpx(tmp_path, "out.hwpx", out_header, out_section)

    result = style_diff.check_para_formats(form_path, out_path)
    assert result["ok"]
    assert result["anomalies"] == []
    # 히스토그램에는 mass 증가가 보이지만(정보용) anomaly는 아님.
    assert result["align_histogram"]["out"]["justify"] > result["align_histogram"]["form"].get("justify", 0)


# ---------------------------------------------------------------------------
# real fixture: line-spacing regressions (200%/180% collapsed to 160%)
# ---------------------------------------------------------------------------

def test_line_spacing_regression_flagged_synthetic(tmp_path):
    """T9 회귀 감지 — 라이브 워크스페이스 대신 합성 손상 사본으로 자립 검증.

    (원래는 실제 out.hwpx의 11건 평탄화를 단언했으나 restore-formats 배선 후
    라이브 파일이 치유되어 fixture 표류 — 형제 테스트들과 같은 방식으로 전환.)
    """
    import shutil, zipfile, re
    damaged = tmp_path / "damaged.hwpx"
    shutil.copyfile(FORM, damaged)
    with zipfile.ZipFile(FORM) as z:
        header = z.read("Contents/header.xml").decode("utf-8")
        section = z.read("Contents/section0.xml").decode("utf-8")
    # 모든 lineSpacing 값을 160으로 평탄화한 header를 가진 사본 생성(전면 평탄화 모사)
    flat_header = re.sub(r'(<hh:lineSpacing[^>]*value=")\d+(")', r"\g<1>160\g<2>", header)
    with zipfile.ZipFile(FORM) as zin, zipfile.ZipFile(damaged, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Contents/header.xml":
                data = flat_header.encode("utf-8")
            zout.writestr(item, data)
    result = style_diff.check_para_formats(FORM, str(damaged))
    assert not result["ok"]
    ls = [a for a in result["anomalies"] if a["field"] == "line_spacing"]
    assert len(ls) >= 5  # 200%/180% 문단들이 평탄화로 전부 잡혀야 함
    flagged_heads = {a["text_head"] for a in ls}
    assert "Ⅰ. 서 론" in flagged_heads


def test_pristine_form_vs_itself_is_clean():
    result = style_diff.check_para_formats(FORM, FORM)
    assert result["ok"]
    assert result["anomalies"] == []
