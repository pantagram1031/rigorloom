"""preedit.py 회귀 테스트 — 감사 승자 선처리 오퍼레이션의 고정 계약.

전부 오프라인(합성 zip 픽스처, COM·한글 실행 없음). 픽스처는 test_guards.py의
합성 XML 스타일 — 실제 hwpx의 hp:/hh:/hs: 접두사와 구조를 축소 재현한다.

핵심 failing-before 시나리오:
  - hawkes sim 결함: ">텍스트<" 정확일치가 런 텍스트의 trailing space에
    조용히 실패(무보고 no-op) → strip-비교 tier가 잡는다 + 0-hit는 ERROR.
  - T18: 표/개체 문단은 가이드 색이어도 절대 삭제되지 않는다.
  - T22: 정의 없는 charPr 재지정은 내장 사후검사가 출력 전에 잡는다.
  - 멱등성: 자기 출력에 재적용해도 content-identical.
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PREEDIT = ROOT / "scripts" / "preedit.py"


def _cli(*args):
    """CLI를 하위 프로세스로 — 종료코드와 JSON payload가 계약의 일부다."""
    return subprocess.run([sys.executable, str(PREEDIT), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")

import preedit  # noqa: E402
from hwpx_tables import find_cell, scan_tables  # noqa: E402
from preedit import (  # noqa: E402
    PreeditError,
    fill_cells,
    content_fingerprint,
    delete_guide_paragraphs,
    normalize_clones,
    replace_placeholders,
)


# ---------------------------------------------------------------------------
# 합성 픽스처 빌더
# ---------------------------------------------------------------------------

CP_BLACK = '<hh:charPr id="0" height="1000" textColor="#000000"/>'
CP_BLUE = '<hh:charPr id="5" height="1000" textColor="#0000FF"/>'
CP_NAVY = '<hh:charPr id="6" height="1000" textColor="#1F3F9F"/>'  # 파랑 계열
CP_CELL = '<hh:charPr id="7" height="1000" textColor="#000000"/>'  # 빈 셀 런


def make_header(charprs, item_cnt=None):
    cnt = item_cnt if item_cnt is not None else len(charprs)
    return ('<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
            '<hh:refList>'
            f'<hh:charProperties itemCnt="{cnt}">' + "".join(charprs)
            + '</hh:charProperties>'
            '<hh:paraProperties itemCnt="1">'
            '<hh:paraPr id="34" tabPrIDRef="0"/>'  # T22 오탐 함정 재현용
            '</hh:paraProperties></hh:refList></hh:head>')


def R(cid, text):
    return f'<hp:run charPrIDRef="{cid}"><hp:t>{text}</hp:t></hp:run>'


def P(*runs):
    return '<hp:p paraPrIDRef="34">' + "".join(runs) + '</hp:p>'


def TBL_P(cell_paras):
    """표 하나를 담은 top-level 문단(T18 보호 대상)."""
    return ('<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">'
            '<hp:tbl id="9" rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:subList>'
            + cell_paras +
            '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')


def SEC(*paras):
    # 실제 hwpx처럼 네임스페이스를 선언한다 — 사후 well-formed 불변식이
    # 수정된 섹션을 ET로 파싱하므로 픽스처도 파싱 가능해야 한다.
    return ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            + "".join(paras) + '</hs:sec>')


def make_hwpx(tmp_path, header_xml, section_xml, name="fixture.hwpx"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", header_xml)
        z.writestr("Contents/section0.xml", section_xml)
    return path


def section_xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read("Contents/section0.xml").decode("utf-8")


def header_xml_of(path):
    with zipfile.ZipFile(path) as z:
        return z.read("Contents/header.xml").decode("utf-8")


# ---------------------------------------------------------------------------
# 1) replace_placeholders
# ---------------------------------------------------------------------------

class TestReplacePlaceholders:
    def test_basic_hits_reported_and_original_untouched(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "20101")), P(R(0, "20101")),
                            P(R(0, "제목 자리"))))
        before = content_fingerprint(src)
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"20101": "20822",
                                                 "제목 자리": "진짜 제목"})
        assert result["hits"] == {"20101": 2, "제목 자리": 1}
        assert "20822" in section_xml(out)
        assert "진짜 제목" in section_xml(out)
        assert content_fingerprint(src) == before  # 원본 비파괴

    def test_trailing_space_run_matched_failing_before(self, tmp_path):
        """failing-before(hawkes sim 결함): 저자표 런에 trailing space가 있으면
        sim의 ">키<" 정확일치는 조용히 실패했다. strip-비교 tier는 잡고,
        결과 런에는 잔여 공백도 남지 않아야 한다."""
        key, val = "10101 김선덕", "20822 이하율"
        sec = SEC(TBL_P(P(R(0, key + " "))))  # 표 셀 안, trailing space
        src = make_hwpx(tmp_path, make_header([CP_BLACK]), sec)
        assert f">{key}<" not in sec  # sim 방식은 여기서 무보고 no-op였다
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {key: val})
        assert result["hits"] == {key: 1}
        assert f"<hp:t>{val}</hp:t>" in section_xml(out)  # 공백 잔여 없음
        assert key not in section_xml(out)

    def test_leading_whitespace_also_matched(self, tmp_path):
        key = "(초록: 논문의 주요 내용의 요약)"
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, " " + key))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {key: "초록"})
        assert result["hits"] == {key: 1}
        assert "<hp:t>초록</hp:t>" in section_xml(out)

    def test_zero_hit_key_raises_and_no_output(self, tmp_path):
        """0-hit 키 = ERROR (sim의 무보고 no-op 결함 금지). 출력 파일 미생성."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "본문"))))
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="없는키"):
            replace_placeholders(src, out, {"없는키": "x"})
        assert not out.exists()

    def test_zero_hit_ignore_mode(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "본문"))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"없는키": "x"},
                                      on_zero_hits="ignore")
        assert result["hits"] == {"없는키": 0}
        assert content_fingerprint(out) == content_fingerprint(src)

    def test_empty_value_erases_placeholder(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "빨간색 글씨는 지우고 작성 "))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"빨간색 글씨는 지우고 작성": ""})
        assert result["hits"] == {"빨간색 글씨는 지우고 작성": 1}
        assert "<hp:t></hp:t>" in section_xml(out)

    def test_double_run_content_identical(self, tmp_path):
        """멱등성 계약: 자기 출력에 재적용(0-hit ignore) = content-identical."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "20101 ")), P(R(0, "제목 자리"))))
        out1 = tmp_path / "out1.hwpx"
        out2 = tmp_path / "out2.hwpx"
        mapping = {"20101": "20822", "제목 자리": "진짜 제목"}
        replace_placeholders(src, out1, mapping)
        replace_placeholders(out1, out2, mapping, on_zero_hits="ignore")
        assert content_fingerprint(out1) == content_fingerprint(out2)

    def test_empty_key_rejected(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK]), SEC(P(R(0, "x"))))
        with pytest.raises(PreeditError):
            replace_placeholders(src, tmp_path / "o.hwpx", {"  ": "y"})


# ---------------------------------------------------------------------------
# 2) delete_guide_paragraphs
# ---------------------------------------------------------------------------

class TestDeleteGuideParagraphs:
    def test_plain_guide_para_deleted_black_stays(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(P(R(5, "이곳에 동기를 기술합니다.")),
                            P(R(0, "남아야 할 본문"))))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["deleted"] == 1
        assert result["protected_skipped"] == 0
        assert "동기를 기술" not in section_xml(out)
        assert "남아야 할 본문" in section_xml(out)

    def test_protected_para_survives_t18(self, tmp_path):
        """T18: 표를 담은 문단은 가이드 런이 섞여 있어도 절대 삭제 금지."""
        prot = ('<hp:p paraPrIDRef="34">'
                + R(5, "파란 안내문")
                + '<hp:run charPrIDRef="0"><hp:tbl id="2" rowCnt="1" colCnt="1">'
                  '<hp:tr><hp:tc><hp:subList>'
                + P(R(0, "표 내용 보존"))
                + '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(prot, P(R(5, "삭제될 안내"))))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["deleted"] == 1
        assert result["protected_skipped"] == 1
        assert "표 내용 보존" in section_xml(out)
        assert "파란 안내문" in section_xml(out)  # 보호 문단은 통째로 불가침
        assert "삭제될 안내" not in section_xml(out)

    def test_mixed_para_guide_runs_removed_para_kept(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(P(R(0, "제목: "), R(5, "(여기에 제목 기재)"))))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["deleted"] == 0
        assert result["mixed_runs_removed"] == 1
        assert "제목: " in section_xml(out)
        assert "여기에 제목 기재" not in section_xml(out)

    def test_whitespace_only_run_does_not_block_deletion(self, tmp_path):
        """결함 클래스 수정: 공백뿐인 비가이드 런이 섞여 있어도 '혼합' 오판 없이
        문단 전체가 삭제돼야 한다(sim이라면 mixed로 남겼을 케이스)."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(P(R(5, "안내문"), R(0, "  "))))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["deleted"] == 1
        assert "안내문" not in section_xml(out)

    def test_table_interior_guide_preserved(self, tmp_path):
        """표 셀 내부의 가이드 텍스트는 top-level이 아니므로 불가침
        (초록 표 구조 보존 — sim의 in_tbl 배제와 동등, T18 카운트로 보고)."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(TBL_P(P(R(5, "셀 안 파란 텍스트")))))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["deleted"] == 0
        assert result["protected_skipped"] == 1
        assert "셀 안 파란 텍스트" in section_xml(out)

    def test_explicit_charpr_ids_and_blue_family(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE, CP_NAVY]),
                        SEC(P(R(5, "순수 파랑")), P(R(6, "네이비 계열")),
                            P(R(0, "본문"))))
        # 명시 id: 5만
        out_ids = tmp_path / "out_ids.hwpx"
        r1 = delete_guide_paragraphs(src, out_ids, charpr_ids=["5"])
        assert r1["deleted"] == 1
        assert "네이비 계열" in section_xml(out_ids)
        # blue 계열 휴리스틱: 5와 6 모두
        out_blue = tmp_path / "out_blue.hwpx"
        r2 = delete_guide_paragraphs(src, out_blue, color="blue")
        assert r2["guide_charpr_ids"] == ["5", "6"]
        assert r2["deleted"] == 2
        assert "본문" in section_xml(out_blue)

    def test_requires_criteria(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK]), SEC(P(R(0, "x"))))
        with pytest.raises(ValueError):
            delete_guide_paragraphs(src, tmp_path / "o.hwpx")

    def test_double_run_content_identical(self, tmp_path):
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(P(R(5, "안내")), P(R(0, "본문"), R(5, "혼합 안내")),
                            TBL_P(P(R(5, "셀 보존")))))
        out1 = tmp_path / "out1.hwpx"
        out2 = tmp_path / "out2.hwpx"
        delete_guide_paragraphs(src, out1, color="#0000FF")
        delete_guide_paragraphs(out1, out2, color="#0000FF")
        assert content_fingerprint(out1) == content_fingerprint(out2)


# ---------------------------------------------------------------------------
# 3) normalize_clones
# ---------------------------------------------------------------------------

BYLINE = "20822 이하율"


def _clone_fixture(tmp_path, header_charprs=None, item_cnt=None):
    header = make_header(header_charprs or [CP_BLACK, CP_BLUE],
                         item_cnt=item_cnt)
    sec = SEC(P(R(5, BYLINE + " ")),   # trailing space — 관용 매칭 대상
              P(R(5, "초록")),
              P(R(0, "본문")))
    return make_hwpx(tmp_path, header, sec)


class TestNormalizeClones:
    def test_clone_repoint_itemcnt(self, tmp_path):
        src = _clone_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = normalize_clones(
            src, out, [("5", "9")], clone_attrs={"textColor": "#000000"},
            repoints=[("5", "9", BYLINE)])
        header = header_xml_of(out)
        sec = section_xml(out)
        clones9 = [m for m in header.split("<hh:charPr")
                   if m.startswith(' id="9"')]
        assert len(clones9) == 1
        assert 'id="9" height="1000" textColor="#000000"' in header
        assert result["item_cnt"] == 3
        assert 'itemCnt="3"' in header
        # trailing space가 있어도 strip-비교로 재지정된다(결함 클래스 수정)
        assert result["repointed"][0]["count"] == 1
        assert f'<hp:run charPrIDRef="9"><hp:t>{BYLINE} </hp:t>' in sec
        # 다른 파란 런("초록")은 그대로
        assert '<hp:run charPrIDRef="5"><hp:t>초록</hp:t>' in sec

    def test_stale_duplicate_clones_removed(self, tmp_path):
        """정규화 계약: 기존 클론이 몇 개든(중복 포함) 전부 걷어내고 정확히
        하나로 재생성 + itemCnt는 실측으로 재계산(입력의 7은 거짓값)."""
        dup = '<hh:charPr id="9" height="1000" textColor="#123456"/>'
        src = _clone_fixture(tmp_path,
                             header_charprs=[CP_BLACK, CP_BLUE, dup, dup],
                             item_cnt=7)
        out = tmp_path / "out.hwpx"
        result = normalize_clones(
            src, out, [("5", "9")], clone_attrs={"textColor": "#000000"})
        assert result["stale_clones_removed"] == 2
        header = header_xml_of(out)
        assert header.count('id="9"') == 1
        assert "#123456" not in header
        assert result["item_cnt"] == 3
        assert 'itemCnt="3"' in header

    def test_double_run_content_identical(self, tmp_path):
        src = _clone_fixture(tmp_path)
        out1 = tmp_path / "out1.hwpx"
        out2 = tmp_path / "out2.hwpx"
        kwargs = dict(clone_attrs={"textColor": "#000000"},
                      repoints=[("5", "9", BYLINE)])
        normalize_clones(src, out1, [("5", "9")], **kwargs)
        r2 = normalize_clones(out1, out2, [("5", "9")], **kwargs)
        assert content_fingerprint(out1) == content_fingerprint(out2)
        assert r2["repointed"][0]["count"] == 0  # 이미 재지정 — 0건이 정상

    def test_dangling_check_fires_on_bad_postedit(self, tmp_path):
        """T22 내장 사후검사: 정의를 만들지 않은 id로 재지정하면 출력 전에
        AssertionError — 출력 파일은 생기지 않는다."""
        src = _clone_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(AssertionError, match="99"):
            normalize_clones(src, out, [("5", "9")],
                             clone_attrs={"textColor": "#000000"},
                             repoints=[("5", "99", None)])
        assert not out.exists()

    def test_missing_src_raises(self, tmp_path):
        src = _clone_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="42"):
            normalize_clones(src, out, [("42", "9")])
        assert not out.exists()

    def test_self_clone_rejected(self, tmp_path):
        src = _clone_fixture(tmp_path)
        with pytest.raises(ValueError):
            normalize_clones(src, tmp_path / "o.hwpx", [("5", "5")])

    def test_repoint_without_text_repoints_all(self, tmp_path):
        src = _clone_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = normalize_clones(
            src, out, [("5", "9")], clone_attrs={"textColor": "#000000"},
            repoints=[("5", "9", None)])
        assert result["repointed"][0]["count"] == 2  # byline + 초록 전부
        assert 'charPrIDRef="5"' not in section_xml(out)


# ---------------------------------------------------------------------------
# 4) 자기닫힘 <hp:t/> 사고 + 사후 well-formed 불변식
# ---------------------------------------------------------------------------

class TestSelfClosedTAndInvariant:
    def test_incident_chain_selfclosed_t(self, tmp_path):
        """failing-before(실사격 사고, 2026 공식 양식): ctrl 보호 문단 안의
        자기닫힘 <hp:t/>(가이드 charPr) 뒤에 자리표시자 런 — 구버전 치환은
        <hp:t/>를 여는 태그로 오인해 다음 요소의 진짜 여는 태그를 집어삼켜
        '<hp:t/>제목…</hp:t>'(짝 없는 닫는 태그)를 만들었고, 한컴은 문서
        전체를 백지로 렌더했다. delete-guides → replace 체인 재현."""
        title = "가중 그래프 최단경로 알고리즘을 이용한 경로 설계"
        para = ('<hp:p paraPrIDRef="34">'
                '<hp:run charPrIDRef="5"><hp:ctrl>'
                '<hp:colPr type="NEWSPAPER" colCount="1"/></hp:ctrl></hp:run>'
                '<hp:run charPrIDRef="5"><hp:t/></hp:run>'
                '<hp:run charPrIDRef="0"><hp:t>제목</hp:t></hp:run></hp:p>')
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]), SEC(para))
        mid = tmp_path / "mid.hwpx"
        out = tmp_path / "out.hwpx"

        r_del = delete_guide_paragraphs(src, mid, color="#0000FF")
        # ctrl 문단은 보호(T18) — 빈 <hp:t/> 런도 그대로 살아있어야 사고 조건
        assert r_del["protected_skipped"] == 1
        assert "<hp:t/>" in section_xml(mid)

        r_rep = replace_placeholders(mid, out, {"제목": title})
        assert r_rep["hits"] == {"제목": 1}
        sec = section_xml(out)
        ET.fromstring(sec)  # well-formed — 사고에서는 여기서 mismatched tag
        assert f"<hp:t>{title}</hp:t>" in sec       # 제대로 된 짝 태그에 삽입
        assert f"<hp:t/>{title}" not in sec          # 사고 패턴 부재
        assert "<hp:t/>" in sec                      # 빈 런은 불가침

    def test_selfclosed_t_space_variant_untouched(self, tmp_path):
        """'<hp:t />'(공백+자기닫힘) 변형도 여는 태그로 오인되지 않는다."""
        para = ('<hp:p paraPrIDRef="34">'
                '<hp:run charPrIDRef="0"><hp:t /></hp:run>'
                + R(0, "키") + '</hp:p>')
        src = make_hwpx(tmp_path, make_header([CP_BLACK]), SEC(para))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"키": "값"})
        assert result["hits"] == {"키": 1}
        sec = section_xml(out)
        ET.fromstring(sec)
        assert "<hp:t />" in sec
        assert "<hp:t>값</hp:t>" in sec

    def test_invariant_blocks_corrupting_writer_replace(self, monkeypatch,
                                                        tmp_path):
        """고의로 손상시키는 가짜 writer 경로(치환 값이 깨진 마크업)를 사후
        불변식이 출력 전에 잡는다 — 출력 파일 미생성."""
        monkeypatch.setattr(preedit, "escape", lambda s: "<hp:broken>")
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "제목"))))
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="well-formed"):
            replace_placeholders(src, out, {"제목": "x"})
        assert not out.exists()

    def test_invariant_blocks_corrupting_writer_normalize(self, monkeypatch,
                                                          tmp_path):
        """normalize_clones의 writer 경로(_tag_set_attr)가 손상을 내면
        well-formed 불변식이 T22 검사보다 먼저 잡는다."""
        monkeypatch.setattr(preedit, "_tag_set_attr",
                            lambda tag, name, value: "<hh:broken>")
        src = _clone_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="well-formed"):
            normalize_clones(src, out, [("5", "9")])
        assert not out.exists()

    def test_invariant_helper_direct(self):
        preedit._assert_members_well_formed(
            {"x.xml": b"<a><b/></a>"}, {"x.xml"})  # 정상 — 예외 없음
        with pytest.raises(PreeditError, match="x.xml"):
            preedit._assert_members_well_formed(
                {"x.xml": b"<a><b></a>"}, {"x.xml"})


# ---------------------------------------------------------------------------
# 5) stale-lineseg(P0) — 텍스트 바뀐 문단의 캐시 레이아웃 제거
# ---------------------------------------------------------------------------

LINESEG = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' textheight="1000" baseline="850" spacing="600" horzpos="0"'
           ' horzsize="42520" flags="393216"/></hp:linesegarray>')


def PL(*runs):
    """실제 한컴 직렬화처럼 linesegarray가 붙은 문단."""
    return '<hp:p paraPrIDRef="34">' + "".join(runs) + LINESEG + '</hp:p>'


class TestStaleLineseg:
    def test_replace_strips_modified_para_only(self, tmp_path):
        """failing-before(실사격 후속 사고): 치환된 문단에 linesegarray가
        남으면 한컴이 옛 좌표에 겹쳐 그린다(제목 overprint). 바뀐 문단만
        lineseg를 잃고, 안 바뀐 문단은 바이트 그대로여야 한다."""
        untouched = PL(R(0, "그대로 본문"))
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(PL(R(0, "제목 자리")), untouched))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"제목 자리": "진짜 제목"})
        assert result["hits"] == {"제목 자리": 1}
        sec = section_xml(out)
        ET.fromstring(sec)
        # 바뀐 문단: lineseg 없음, 텍스트는 교체됨
        assert ('<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">'
                '<hp:t>진짜 제목</hp:t></hp:run></hp:p>') in sec
        # 안 바뀐 문단: linesegarray 포함 바이트 그대로
        assert untouched in sec
        assert sec.count("<hp:linesegarray") == 1

    def test_replace_nested_cell_precision(self, tmp_path):
        """표 셀 문단만 바뀌면 셀 문단의 lineseg만 제거 — 바깥(표를 담은)
        문단 자신의 텍스트는 안 바뀌었으므로 그 lineseg는 보존."""
        cell = PL(R(0, "셀 자리표시자"))
        outer = ('<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">'
                 '<hp:tbl id="9" rowCnt="1" colCnt="1"><hp:tr><hp:tc>'
                 '<hp:subList>' + cell + '</hp:subList></hp:tc></hp:tr>'
                 '</hp:tbl></hp:run>' + LINESEG + '</hp:p>')
        src = make_hwpx(tmp_path, make_header([CP_BLACK]), SEC(outer))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"셀 자리표시자": "값"})
        assert result["hits"] == {"셀 자리표시자": 1}
        sec = section_xml(out)
        ET.fromstring(sec)
        # 셀 문단: lineseg 제거 + 텍스트 교체
        assert ('<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">'
                '<hp:t>값</hp:t></hp:run></hp:p>') in sec
        # 바깥 문단 자신의 lineseg는 그대로(표 닫힘 직후 위치 불변)
        assert '</hp:tbl></hp:run>' + LINESEG + '</hp:p>' in sec
        assert sec.count("<hp:linesegarray") == 1

    def test_delete_mixed_run_strips_lineseg(self, tmp_path):
        """혼합 문단에서 가이드 런 제거 = 텍스트 변경 → lineseg도 제거.
        무관 문단의 lineseg는 바이트 그대로."""
        unrelated = PL(R(0, "무관 문단"))
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(PL(R(0, "유지 본문"), R(5, "파란 안내")),
                            unrelated))
        out = tmp_path / "out.hwpx"
        result = delete_guide_paragraphs(src, out, color="#0000FF")
        assert result["mixed_runs_removed"] == 1
        sec = section_xml(out)
        ET.fromstring(sec)
        assert "유지 본문" in sec
        assert "파란 안내" not in sec
        assert unrelated in sec
        assert sec.count("<hp:linesegarray") == 1  # 혼합 문단 것만 사라짐

    def test_double_run_idempotent_with_linesegs(self, tmp_path):
        """멱등성: lineseg 제거 포함 2회차 실행도 content-identical —
        1회차에 이미 제거됐고 2회차는 무변경이라 재제거도 없다."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE]),
                        SEC(PL(R(0, "제목 자리")),
                            PL(R(0, "유지"), R(5, "안내")),
                            PL(R(0, "그대로"))))
        mapping = {"제목 자리": "진짜 제목"}
        r1 = tmp_path / "r1.hwpx"
        r2 = tmp_path / "r2.hwpx"
        replace_placeholders(src, r1, mapping)
        replace_placeholders(r1, r2, mapping, on_zero_hits="ignore")
        assert content_fingerprint(r1) == content_fingerprint(r2)
        d1 = tmp_path / "d1.hwpx"
        d2 = tmp_path / "d2.hwpx"
        delete_guide_paragraphs(r2, d1, color="#0000FF")
        delete_guide_paragraphs(d1, d2, color="#0000FF")
        assert content_fingerprint(d1) == content_fingerprint(d2)


# ---------------------------------------------------------------------------
# 6) 스코프 재지정(분할 런 저자표 검정 전환) + id↔위치 진단
# ---------------------------------------------------------------------------

def _split_byline_fixture(tmp_path, with_lineseg=False):
    """form_final2 감식 재현: 저자표 셀 문단이 '학번 런(파랑 5) + 이름 런
    (네이비 6) + 개체 런'으로 쪼개져 있다. 바깥에 무관 파란 문단 하나."""
    cell_runs = ('<hp:run charPrIDRef="5"><hp:t>20822 </hp:t></hp:run>'
                 '<hp:run charPrIDRef="6"><hp:t>이하율</hp:t></hp:run>'
                 '<hp:run charPrIDRef="5"><hp:pic id="77"/></hp:run>')
    cell_para = ('<hp:p paraPrIDRef="34">' + cell_runs
                 + (LINESEG if with_lineseg else "") + '</hp:p>')
    sec = SEC(TBL_P(cell_para), P(R(5, "무관 파란 문단")))
    return make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE, CP_NAVY]), sec)


class TestScopedRepoint:
    def test_split_run_byline_both_black(self, tmp_path):
        """failing-before(form_final2 실사격): 텍스트 매치 repoint는 학번
        런만 잡고 이름 런(다른 charPr)은 파랑으로 남았다. 스코프 재지정은
        앵커 문단(표 셀)의 텍스트 런 '전부'를 검정 클론으로 — 개체 런은
        불가침. 앵커는 분할 런·공백에 관용(공백 제거 부분일치)."""
        src = _split_byline_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        # 새 id "3" = 현재 def 개수(0,5,6 → 3번째 위치) — id==위치 유지 지침
        result = normalize_clones(
            src, out, [("5", "3")], clone_attrs={"textColor": "#000000"},
            scope_repoints=[("3", "20822 이하율")])
        assert result["scope_repointed"] == [
            {"to": "3", "anchor": "20822 이하율", "paragraphs": 1, "runs": 2}]
        sec = section_xml(out)
        ET.fromstring(sec)
        assert '<hp:run charPrIDRef="3"><hp:t>20822 </hp:t></hp:run>' in sec
        assert '<hp:run charPrIDRef="3"><hp:t>이하율</hp:t></hp:run>' in sec
        # 개체 런은 원래 charPr 그대로
        assert '<hp:run charPrIDRef="5"><hp:pic id="77"/></hp:run>' in sec
        # 스코프 밖 문단은 불가침
        assert '<hp:run charPrIDRef="5"><hp:t>무관 파란 문단</hp:t>' in sec

    def test_scope_zero_match_raises(self, tmp_path):
        src = _split_byline_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="없는사람"):
            normalize_clones(src, out, [("5", "3")],
                             clone_attrs={"textColor": "#000000"},
                             scope_repoints=[("3", "없는사람")])
        assert not out.exists()

    def test_scope_idempotent_and_second_run_zero(self, tmp_path):
        src = _split_byline_fixture(tmp_path)
        o1 = tmp_path / "o1.hwpx"
        o2 = tmp_path / "o2.hwpx"
        kwargs = dict(clone_attrs={"textColor": "#000000"},
                      scope_repoints=[("3", "20822 이하율")])
        normalize_clones(src, o1, [("5", "3")], **kwargs)
        r2 = normalize_clones(o1, o2, [("5", "3")], **kwargs)
        assert content_fingerprint(o1) == content_fingerprint(o2)
        # 2회차: 문단은 여전히 매치(텍스트 불변), 바꾼 런은 0 — 멱등 보고
        assert r2["scope_repointed"][0]["paragraphs"] == 1
        assert r2["scope_repointed"][0]["runs"] == 0

    def test_scope_does_not_strip_lineseg(self, tmp_path):
        """스코프 재지정은 텍스트를 바꾸지 않으므로 linesegarray 불가침
        (stale-lineseg 조건 아님 — 색만 바뀌고 메트릭 불변)."""
        src = _split_byline_fixture(tmp_path, with_lineseg=True)
        out = tmp_path / "out.hwpx"
        normalize_clones(src, out, [("5", "3")],
                         clone_attrs={"textColor": "#000000"},
                         scope_repoints=[("3", "20822 이하율")])
        sec = section_xml(out)
        assert LINESEG in sec  # 바이트 그대로

    def test_clone_appended_at_end_with_position_diagnostic(self, tmp_path):
        """form_final2 원흉 재발 방지: 클론은 배열 끝 append(중간 삽입
        금지). id↔위치 진단 — 연속 id 입력 + 위치==id 클론이면 빈 목록,
        희소 id 입력이면 불일치가 보고된다."""
        # (a) 연속 id 0,1 + 클론 id 2 → 불일치 없음
        cp0 = '<hh:charPr id="0" height="1000" textColor="#000000"/>'
        cp1 = '<hh:charPr id="1" height="1000" textColor="#0000FF"/>'
        clean = make_hwpx(tmp_path, make_header([cp0, cp1]),
                          SEC(P(R(1, "저자명"))), name="clean.hwpx")
        out_a = tmp_path / "a.hwpx"
        ra = normalize_clones(clean, out_a, [("1", "2")],
                              clone_attrs={"textColor": "#000000"})
        assert ra["id_position_mismatch"] == []
        header_a = header_xml_of(out_a)
        ids = __import__("re").findall(r'<hh:charPr\b[^>]*?\bid="(\d+)"',
                                       header_a)
        assert ids == ["0", "1", "2"]  # 끝 append — id==위치 보존
        # (b) 희소 id(0,5,6) 입력 → desync가 진단에 잡힌다
        sparse = _split_byline_fixture(tmp_path)
        out_b = tmp_path / "b.hwpx"
        rb = normalize_clones(sparse, out_b, [("5", "3")],
                              clone_attrs={"textColor": "#000000"},
                              scope_repoints=[("3", "이하율")])
        assert {"pos": 1, "id": "5"} in rb["id_position_mismatch"]
        assert {"pos": 2, "id": "6"} in rb["id_position_mismatch"]
        # 클론 id 3은 위치 3 — 스스로는 불일치를 만들지 않는다
        assert {"pos": 3, "id": "3"} not in rb["id_position_mismatch"]

    def test_scope_without_clones_targets_existing_charpr(self, tmp_path):
        """clones 없이 scope_repoints만으로 기존 검정 charPr(0)로 재지정."""
        src = _split_byline_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = normalize_clones(
            src, out, scope_repoints=[("0", "이하율")])
        assert result["clones"] == []
        assert result["scope_repointed"][0]["runs"] == 2
        assert '<hp:run charPrIDRef="0"><hp:t>이하율</hp:t></hp:run>' \
            in section_xml(out)


# ---------------------------------------------------------------------------
# 4) D1 — 값이 키를 포함하면 tier B가 tier A 결과 위에 또 치환(double-apply)
#
# 첫 클린룸 교차모델 런(Sonnet·Opus 독립 재현). operations.md가 스스로 문서화한
# 예제를 그대로 따라 하면 셀이 망가졌다:
#   {" http://": " http://example.kr"}  ->  " http://example.krexample.kr"
#   (hits=2 — tier A 1 + tier B 1)
# ---------------------------------------------------------------------------

CELL_HTTP = " http://"


class TestValueContainsKeyDoubleApply:
    def test_documented_http_example_applies_once(self, tmp_path):
        """failing-before: hits=2 + ' http://example.krexample.kr'."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(TBL_P(P(R(0, CELL_HTTP)))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(
            src, out, {CELL_HTTP: " http://example.kr"})
        assert result["hits"] == {CELL_HTTP: 1}
        xml = section_xml(out)
        assert "<hp:t> http://example.kr</hp:t>" in xml
        assert "example.krexample" not in xml

    def test_value_contains_key_in_table_cell(self, tmp_path):
        """표 셀 안 부분문자열 키 — 값이 키를 품어도 정확히 한 번."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(TBL_P(P(R(0, "담당자: 홍길동 (내선)")))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"홍길동": "홍길동 외 2인"})
        assert result["hits"] == {"홍길동": 1}
        xml = section_xml(out)
        assert "담당자: 홍길동 외 2인 (내선)" in xml
        assert "홍길동 외 2인 외 2인" not in xml

    def test_rerun_is_content_identical(self, tmp_path):
        """멱등성 계약: 값이 키를 품어도 재실행이 바이트를 바꾸면 안 된다.

        failing-before: 2회차에 tier B가 최종값 안의 키를 또 잡아
        ' http://example.krexample.kr'로 자랐다."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(TBL_P(P(R(0, CELL_HTTP)))))
        first = tmp_path / "a.hwpx"
        second = tmp_path / "b.hwpx"
        replace_placeholders(src, first, {CELL_HTTP: " http://example.kr"})
        again = replace_placeholders(
            first, second, {CELL_HTTP: " http://example.kr"},
            on_zero_hits="ignore")
        assert again["hits"] == {CELL_HTTP: 0}
        assert content_fingerprint(first) == content_fingerprint(second)

    def test_independent_occurrences_still_both_replaced(self, tmp_path):
        """과잉 보호 방지: 겹치지 않는 두 occurrence는 여전히 둘 다 바뀐다."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "코드 AB 그리고 코드 AB 끝"))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"AB": "AB-99"})
        assert result["hits"] == {"AB": 2}
        assert "코드 AB-99 그리고 코드 AB-99 끝" in section_xml(out)

    def test_later_key_does_not_eat_earlier_value(self, tmp_path):
        """키 사이 연쇄 치환 금지 — 앞 키가 쓴 값은 뒤 키의 대상이 아니다."""
        src = make_hwpx(tmp_path, make_header([CP_BLACK]),
                        SEC(P(R(0, "X")), P(R(0, "Y 자리"))))
        out = tmp_path / "out.hwpx"
        result = replace_placeholders(src, out, {"X": "Y", "Y": "Z"})
        assert result["hits"] == {"X": 1, "Y": 1}
        xml = section_xml(out)
        assert "<hp:t>Y</hp:t>" in xml       # X->Y 가 다시 Z가 되지 않는다
        assert "<hp:t>Z 자리</hp:t>" in xml   # 원래의 Y는 정상 치환


# ---------------------------------------------------------------------------
# 5) D2 — fill_cells: cellAddr로 '진짜 빈' 셀 채우기 (T27)
# ---------------------------------------------------------------------------

def TC(row, col, inner, *, row_span=1, col_span=1, bf="5"):
    return (f'<hp:tc borderFillIDRef="{bf}"><hp:subList>{inner}</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
            f'<hp:cellSz width="1000" height="500"/></hp:tc>')


LINESEG = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' horzsize="12980"/></hp:linesegarray>')


def EMPTY_P(cid=7):
    """양식의 '진짜 빈 셀' 표준형 — hp:t가 아예 없는 자기닫힘 런 하나."""
    return (f'<hp:p paraPrIDRef="34"><hp:run charPrIDRef="{cid}"/>'
            f'{LINESEG}</hp:p>')


def TBL(cells, *, tid="9", rows=3, cols=3):
    return (f'<hp:tbl id="{tid}" rowCnt="{rows}" colCnt="{cols}"><hp:tr>'
            + "".join(cells) + '</hp:tr></hp:tbl>')


def TBL_WRAP(tbl):
    return f'<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>'


def _form_fixture(tmp_path, name="form.hwpx"):
    """rowspan 라벨 열 + 빈 셀(자기닫힘 런) — 정부 양식의 표준 형태."""
    tbl = TBL([
        TC(0, 0, P(R(0, "신 청 인")), row_span=2),
        TC(0, 1, P(R(0, "성 명"))),
        TC(0, 2, EMPTY_P()),
        TC(1, 1, P(R(0, "생년월일"))),
        TC(1, 2, EMPTY_P()),
        TC(2, 0, P(R(0, "주 소"))),
        TC(2, 1, EMPTY_P(), col_span=2),
    ])
    return make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE, CP_CELL]),
                     SEC(TBL_WRAP(tbl)), name=name)


class TestFillCells:
    def test_fills_empty_selfclosing_run(self, tmp_path):
        """failing-before(T27): 빈 셀에는 hp:t가 없어 replace가 도달 불가."""
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 2, "이하율")])
        assert result["filled"] == 1
        assert result["cells"][0]["addr"] == [0, 2]
        assert result["cells"][0]["hits"] == 1
        xml = section_xml(out)
        # charPr 보존 + 짝 있는 hp:t 생성(자기닫힘 <hp:t/>는 만들지 않는다)
        assert '<hp:run charPrIDRef="7"><hp:t>이하율</hp:t></hp:run>' in xml
        assert "<hp:t/>" not in xml
        ET.fromstring(xml)

    def test_empty_cell_is_unreachable_by_replace(self, tmp_path):
        """T27의 근거: 빈 셀에는 키로 삼을 텍스트가 아예 없다."""
        src = _form_fixture(tmp_path)
        xml = section_xml(src)
        assert '<hp:run charPrIDRef="7"/>' in xml   # hp:t 없음
        with pytest.raises(PreeditError):            # 잡을 문자열이 없다
            replace_placeholders(src, tmp_path / "no.hwpx", {"[성명]": "이하율"})

    def test_refuses_non_empty_cell_and_writes_nothing(self, tmp_path):
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="비어 있지 않음"):
            fill_cells(src, out, [(0, 1, "덮어쓰기")])
        assert not out.exists()

    def test_overwrite_flag_replaces_label_text(self, tmp_path):
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 1, "이름")], overwrite=True)
        assert result["cells"][0]["action"] == "overwritten"
        assert result["cells"][0]["previous"] == "성 명"
        assert "<hp:t>이름</hp:t>" in section_xml(out)

    def test_batch_write_is_atomic_on_refusal(self, tmp_path):
        """한 셀이라도 거부되면 배치 전체가 쓰이지 않는다(부분 편집 금지)."""
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError):
            fill_cells(src, out, [(0, 2, "정상"), (2, 0, "라벨파괴")])
        assert not out.exists()

    def test_strips_stale_linesegarray(self, tmp_path):
        """T24: 텍스트가 바뀐 문단의 캐시 레이아웃은 제거 — 아니면 overprint."""
        src = _form_fixture(tmp_path)
        assert "linesegarray" in section_xml(src)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 2, "값"), (1, 2, "값2"), (2, 1, "값3")])
        assert "linesegarray" not in section_xml(out)

    def test_untouched_cells_keep_their_linesegarray(self, tmp_path):
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 2, "값")])
        # 나머지 두 빈 셀의 lineseg는 바이트 그대로(byte-fidelity)
        assert section_xml(out).count("<hp:linesegarray>") == 2

    def test_idempotent_under_overwrite(self, tmp_path):
        src = _form_fixture(tmp_path)
        first, second = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
        fill_cells(src, first, [(0, 2, "이하율")])
        again = fill_cells(first, second, [(0, 2, "이하율")], overwrite=True)
        assert again["filled"] == 0
        assert content_fingerprint(first) == content_fingerprint(second)

    def test_rowspan_addressing_skips_covered_coordinates(self, tmp_path):
        """병합이 덮은 좌표(1,0)에는 셀이 없다 — 조용한 오작성 대신 오류."""
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="cellAddr"):
            fill_cells(src, out, [(1, 0, "값")])
        assert not out.exists()

    def test_duplicate_address_rejected(self, tmp_path):
        src = _form_fixture(tmp_path)
        with pytest.raises(PreeditError, match="중복"):
            fill_cells(src, tmp_path / "o.hwpx", [(0, 2, "a"), (0, 2, "b")])

    def test_missing_table_index_reports_total(self, tmp_path):
        src = _form_fixture(tmp_path)
        with pytest.raises(PreeditError, match="표는 1개"):
            fill_cells(src, tmp_path / "o.hwpx", [(0, 2, "값")], table=3)

    def test_charpr_override_and_no_dangling_ref(self, tmp_path):
        """charPr 재지정 시 T22 사후검사가 함께 돈다."""
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 2, "값")], charpr="5")
        assert '<hp:run charPrIDRef="5"><hp:t>값</hp:t></hp:run>' \
            in section_xml(out)
        with pytest.raises(AssertionError):
            fill_cells(src, tmp_path / "bad.hwpx", [(0, 2, "값")], charpr="99")

    def test_nested_table_has_its_own_index_and_cells(self, tmp_path):
        """중첩 표는 자기 index를 갖고, 바깥 셀의 '빈 여부'를 오염시키지 않는다.

        failing-before(옛 비탐욕 정규식): 바깥 표의 여는 태그가 안쪽 표의 닫는
        태그와 짝지어져 표 수·셀 수가 틀렸다(코퍼스 12개 중 6개에서 실측)."""
        inner = TBL([TC(0, 0, P(R(0, "안쪽"))), TC(0, 1, EMPTY_P())],
                    tid="20", rows=1, cols=2)
        outer = TBL([
            TC(0, 0, P(R(0, "바깥 라벨"))),
            TC(0, 1, TBL_WRAP(inner)),
            TC(1, 0, EMPTY_P()),
            TC(1, 1, EMPTY_P()),
        ], tid="10", rows=2, cols=2)
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE, CP_CELL]),
                        SEC(TBL_WRAP(outer)))
        tables = scan_tables(section_xml(src))
        assert [t["depth"] for t in tables] == [0, 1]
        assert len(tables[0]["cells"]) == 4 and len(tables[1]["cells"]) == 2
        # 바깥 표의 (1,1)과 안쪽 표의 (0,1)은 서로 다른 셀 — 색인으로 구분된다
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(1, 1, "바깥값")], table=0)
        inner_out = tmp_path / "inner.hwpx"
        fill_cells(out, inner_out, [(0, 1, "안쪽값")], table=1)
        xml = section_xml(inner_out)
        assert "바깥값" in xml and "안쪽값" in xml
        tables2 = scan_tables(xml)
        assert find_cell(tables2[0], 1, 1) is not None
        # 중첩 표를 품은 바깥 셀 (0,1)의 '자기 텍스트'는 비어 있다
        cell = find_cell(tables2[0], 0, 1)
        own = preedit._fragment_text(xml[cell["body_start"]:cell["body_end"]])
        assert own.strip() == ""

    def test_writes_into_cell_that_has_empty_paired_t(self, tmp_path):
        """비어 있지만 <hp:t></hp:t>가 이미 있는 셀도 같은 경로로 채운다."""
        tbl = TBL([TC(0, 0, P(R(7, "")))], tid="9", rows=1, cols=1)
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_BLUE, CP_CELL]),
                        SEC(TBL_WRAP(tbl)))
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 0, "값")])
        assert '<hp:run charPrIDRef="7"><hp:t>값</hp:t></hp:run>' \
            in section_xml(out)


# ---------------------------------------------------------------------------
# 8) replace --at-cell — 주소로 잡는 치환 ('seat text' 클래스, T34)
#
# failing-before: 양식이 인쇄해 둔 자리표를 고치려면 문자열 키가 런의 내부
# 공백까지 정확해야 했고, 그 문자열을 제품 안에서 얻을 경로가 없었다
# (text_preview는 30자 무표시 잘림, 스켈레톤은 anchors에 없음). 3라운드
# 클린룸에서 두 티어 모두 Contents/section0.xml을 손으로 읽었다 — 배포된
# 스킬이 금지한 바로 그 접촉. 여기서 고정하는 것은 '정확한 문자열이 아예
# 필요 없다'는 계약이다.
# ---------------------------------------------------------------------------

SEAT_ZIP = " 우(     -     )"
SEAT_URL = " http://"
SEAT_PERIOD = "20   .    .    .  ~  20   .    .    .   (     개월)"
SEAT_DATE = "                                               년      월      일"


def _seat_fixture(tmp_path, name="seat.hwpx"):
    """자리표가 인쇄된 양식 표 — T34의 대상 형태.

    (0,1) 우편번호 스켈레톤 · (1,1) http 접두 · (2,1) 협업기간 스켈레톤(30자
    초과) · (3,1) 한 셀 안 여러 런(그 중 하나가 신청일 줄) · (4,1) 진짜 빈 셀.
    """
    tbl = TBL([
        TC(0, 0, P(R(0, "주    소"))),
        TC(0, 1, PL(R(0, SEAT_ZIP))),
        TC(1, 0, P(R(0, "홈페이지"))),
        TC(1, 1, PL(R(0, SEAT_URL))),
        TC(2, 0, P(R(0, "협 업 기 간"))),
        TC(2, 1, PL(R(0, SEAT_PERIOD))),
        TC(3, 0, P(R(0, "신청"))),
        TC(3, 1, PL(R(0, "규정에 따라 신청합니다."), R(0, SEAT_DATE),
                    R(6, "신청인"))),
        TC(4, 0, P(R(0, "서명"))),
        TC(4, 1, EMPTY_P()),
    ], rows=5, cols=2)
    return make_hwpx(tmp_path,
                     make_header([CP_BLACK, CP_BLUE, CP_NAVY, CP_CELL]),
                     SEC(TBL_WRAP(tbl)), name=name)


def _geometry_skeleton(xml):
    """텍스트 내용과 캐시 레이아웃을 뺀 XML — 표/셀 기하만 남는다.

    이게 같으면 '텍스트 말고는 아무것도 안 바뀌었다'가 바이트로 증명된다
    (셀 수·주소·병합·borderFill·cellSz·문단 구조 전부 포함)."""
    return preedit.T_FULL_RE.sub(
        lambda m: m.group(1) + m.group(3), preedit.LINESEG_RE.sub("", xml))


def _cell_runs_at(path, addr, table=0):
    xml = section_xml(path)
    cell = find_cell(scan_tables(xml)[table], *addr)
    return preedit.cell_text_runs(xml[cell["body_start"]:cell["body_end"]])


class TestReplaceAtCells:
    def test_seat_text_replaced_without_knowing_its_whitespace(self, tmp_path):
        """failing-before: 이 값을 쓰려면 30자 넘는 스켈레톤을 공백까지 정확히
        키로 써야 했다. 주소만으로 대상을 잡고, 정확한 이전 텍스트는 결과가
        되돌려준다."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(
            src, out, [(2, 1, None, "2026. 3. 1. ~ 2026. 8. 31. (6개월)",
                        "replace")])
        assert result["replaced"] == 1
        cell = result["cells"][0]
        assert cell["addr"] == [2, 1] and cell["run"] == 0
        assert cell["action"] == "replaced"
        assert cell["before"] == SEAT_PERIOD          # 정확한 자리표를 보고
        assert cell["after"] == "2026. 3. 1. ~ 2026. 8. 31. (6개월)"
        xml = section_xml(out)
        ET.fromstring(xml)
        assert SEAT_PERIOD not in xml
        assert "<hp:t>2026. 3. 1. ~ 2026. 8. 31. (6개월)</hp:t>" in xml

    def test_geometry_is_byte_identical(self, tmp_path):
        """기하 불변: 텍스트와 (바뀐 문단의) lineseg 말고는 한 바이트도
        달라지지 않는다."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(src, out, [
            (0, 1, None, "서울 강남구", "append"),
            (2, 1, None, "6개월", "replace"),
            (3, 1, 1, "2026 년 3 월 1 일", "replace"),
        ])
        assert _geometry_skeleton(section_xml(out)) \
            == _geometry_skeleton(section_xml(src))
        before = scan_tables(section_xml(src))[0]["cells"]
        after = scan_tables(section_xml(out))[0]["cells"]
        assert [(c["addr"], c["span"], c["attrs"]) for c in before] \
            == [(c["addr"], c["span"], c["attrs"]) for c in after]

    def test_append_preserves_the_printed_prefix(self, tmp_path):
        """T31의 정상 형태: 라벨 필드는 접두를 남기고 값을 이어붙인다."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(
            src, out, [(1, 1, None, "hanbit.example.kr", "append")])
        assert result["cells"][0]["action"] == "appended"
        assert result["cells"][0]["after"] == " http://hanbit.example.kr"
        assert "<hp:t> http://hanbit.example.kr</hp:t>" in section_xml(out)

    def test_replace_mode_discards_the_prefix(self, tmp_path):
        """모드는 명시된다 — 같은 셀에 replace를 주면 접두가 사라진다.
        추측하지 않는다는 계약을 두 모드의 관측 가능한 차이로 고정."""
        src = _seat_fixture(tmp_path)
        a, b = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
        preedit.replace_at_cells(src, a, [(1, 1, None, "X", "append")])
        preedit.replace_at_cells(src, b, [(1, 1, None, "X", "replace")])
        assert "<hp:t> http://X</hp:t>" in section_xml(a)
        assert "<hp:t>X</hp:t>" in section_xml(b)
        assert " http://" not in section_xml(b)

    def test_multi_run_cell_refuses_and_lists_every_run(self, tmp_path):
        """다중 런 셀: 조용히 첫 런을 고르지도, 셀 텍스트 전체를 밀지도
        않는다. 거부 payload가 모든 런의 **정확한** 문자열을 들고 있으므로
        그것만 읽고 #RUN을 골라 다시 부르면 된다."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(preedit.AmbiguousCellRunError) as exc:
            preedit.replace_at_cells(src, out, [(3, 1, None, "값", "replace")])
        assert not out.exists()
        runs = exc.value.runs
        assert [r["index"] for r in runs] == [0, 1, 2]
        assert runs[1]["text"] == SEAT_DATE      # 정확한 공백까지
        assert runs[2]["charpr"] == "6"
        assert exc.value.suggested_flags[:2] == ["--at-cell", "3,1#0=<TEXT>"]

    def test_named_run_edits_only_that_run(self, tmp_path):
        """#RUN을 주면 그 런만 바뀌고 같은 셀의 다른 런은 바이트 그대로."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(
            src, out, [(3, 1, 1, "2026 년   3 월   1 일", "replace")])
        assert result["cells"][0]["before"] == SEAT_DATE
        xml = section_xml(out)
        assert ('<hp:run charPrIDRef="0"><hp:t>규정에 따라 신청합니다.</hp:t>'
                '</hp:run>') in xml
        assert '<hp:run charPrIDRef="6"><hp:t>신청인</hp:t></hp:run>' in xml
        assert SEAT_DATE not in xml

    def test_truly_empty_cell_is_routed_to_fill_cells(self, tmp_path):
        """자리표가 없는 셀에는 고칠 텍스트가 없다 — T27의 경계."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="fill-cells"):
            preedit.replace_at_cells(src, out, [(4, 1, None, "값", "replace")])
        assert not out.exists()

    def test_run_index_out_of_range_reports_the_count(self, tmp_path):
        src = _seat_fixture(tmp_path)
        with pytest.raises(PreeditError, match="범위 밖"):
            preedit.replace_at_cells(src, tmp_path / "o.hwpx",
                                     [(3, 1, 9, "값", "replace")])

    def test_duplicate_target_rejected(self, tmp_path):
        src = _seat_fixture(tmp_path)
        with pytest.raises(PreeditError, match="중복"):
            preedit.replace_at_cells(src, tmp_path / "o.hwpx", [
                (2, 1, None, "a", "replace"), (2, 1, None, "b", "replace")])
        # 같은 런을 다른 표기로 두 번 가리키는 경우도 조용한 마지막-승리 금지
        with pytest.raises(PreeditError, match="두 번"):
            preedit.replace_at_cells(src, tmp_path / "o2.hwpx", [
                (2, 1, None, "a", "replace"), (2, 1, 0, "b", "replace")])

    def test_expect_precondition_is_whitespace_tolerant(self, tmp_path):
        """운영자는 자리표의 공백을 볼 수 없다 — 사전조건은 공백을 전부 뺀
        부분일치로 본다. 편집은 주소로, 확인은 관용적으로."""
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(src, out, [(0, 1, None, "서울", "append")],
                                 expects={(0, 1, None): "우(-)"})
        assert "<hp:t> 우(     -     )서울</hp:t>" in section_xml(out)

    def test_expect_mismatch_writes_nothing(self, tmp_path):
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(PreeditError, match="사전조건 불일치"):
            preedit.replace_at_cells(src, out, [(0, 1, None, "X", "append")],
                                     expects={(0, 1, None): "홈페이지"})
        assert not out.exists()

    def test_expect_target_must_be_in_the_edit_list(self, tmp_path):
        src = _seat_fixture(tmp_path)
        with pytest.raises(PreeditError, match="편집 목록에 없음"):
            preedit.replace_at_cells(
                src, tmp_path / "o.hwpx", [(0, 1, None, "X", "append")],
                expects={(1, 1, None): "http"})

    def test_idempotent_in_both_modes(self, tmp_path):
        """이미 최종값인 런은 no-op — append가 값을 두 번 붙이지 않는다
        (T26과 같은 원리, 재실행이 content-identical)."""
        src = _seat_fixture(tmp_path)
        a, b = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
        edits = [(1, 1, None, "host.kr", "append"),
                 (2, 1, None, "6개월", "replace")]
        preedit.replace_at_cells(src, a, edits)
        again = preedit.replace_at_cells(a, b, edits)
        assert again["replaced"] == 0
        assert [c["action"] for c in again["cells"]] == ["noop", "noop"]
        assert content_fingerprint(a) == content_fingerprint(b)
        assert section_xml(b).count("host.kr") == 1

    def test_strips_lineseg_of_edited_paragraph_only(self, tmp_path):
        """T24: 바뀐 문단만 캐시 레이아웃을 잃는다."""
        src = _seat_fixture(tmp_path)
        assert section_xml(src).count("<hp:linesegarray") == 5
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(src, out, [(2, 1, None, "6개월", "replace")])
        assert section_xml(out).count("<hp:linesegarray") == 4

    def test_multi_t_run_keeps_the_tab_between_the_texts(self, tmp_path):
        """분할 런(탭을 사이에 둔 hp:t 둘): replace는 첫 hp:t에 쓰고 나머지를
        비우되 탭은 보존하고, append는 마지막 hp:t 뒤에 붙는다."""
        run = ('<hp:run charPrIDRef="0"><hp:t>좌</hp:t><hp:tab/>'
               '<hp:t>우</hp:t></hp:run>')
        tbl = TBL([TC(0, 0, '<hp:p paraPrIDRef="34">' + run + '</hp:p>')],
                  rows=1, cols=1)
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_CELL]),
                        SEC(TBL_WRAP(tbl)))
        assert [r["text"] for r in _cell_runs_at(src, (0, 0))] == ["좌우"]

        rep, app = tmp_path / "rep.hwpx", tmp_path / "app.hwpx"
        preedit.replace_at_cells(src, rep, [(0, 0, None, "값", "replace")])
        assert '<hp:t>값</hp:t><hp:tab/><hp:t></hp:t>' in section_xml(rep)
        preedit.replace_at_cells(src, app, [(0, 0, None, "!", "append")])
        assert '<hp:t>좌</hp:t><hp:tab/><hp:t>우!</hp:t>' in section_xml(app)

    def test_nested_table_runs_belong_to_the_inner_table(self, tmp_path):
        """중첩 표를 담은 셀의 '자기' 텍스트 런에 안쪽 표의 런이 섞이지
        않는다 — fill-cells와 같은 귀속 규약."""
        inner = TBL([TC(0, 0, P(R(0, "안쪽 자리표")))],
                    tid="20", rows=1, cols=1)
        outer = TBL([TC(0, 0, TBL_WRAP(inner)), TC(0, 1, PL(R(0, SEAT_URL)))],
                    tid="10", rows=1, cols=2)
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_CELL]),
                        SEC(TBL_WRAP(outer)))
        assert _cell_runs_at(src, (0, 0)) == []
        # 안쪽 표는 자기 색인으로 도달한다
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(src, out, [(0, 0, None, "값", "replace")],
                                 table=1)
        assert "<hp:t>값</hp:t>" in section_xml(out)

    def test_missing_cell_and_table_report_real_addresses(self, tmp_path):
        src = _seat_fixture(tmp_path)
        with pytest.raises(PreeditError, match="cellAddr"):
            preedit.replace_at_cells(src, tmp_path / "o.hwpx",
                                     [(9, 9, None, "값", "replace")])
        with pytest.raises(PreeditError, match="표는 1개"):
            preedit.replace_at_cells(src, tmp_path / "o.hwpx",
                                     [(2, 1, None, "값", "replace")], table=7)

    def test_value_is_xml_escaped_and_output_well_formed(self, tmp_path):
        src = _seat_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(
            src, out, [(2, 1, None, "A & B <주의>", "replace")])
        xml = section_xml(out)
        ET.fromstring(xml)
        assert "<hp:t>A &amp; B &lt;주의&gt;</hp:t>" in xml

    def test_two_runs_in_one_paragraph_both_edited(self, tmp_path):
        """같은 문단 안 두 런을 한 호출에 — 편집이 서로의 오프셋을 밀지 않고,
        그 문단의 lineseg는 한 번만 사라진다."""
        para = ('<hp:p paraPrIDRef="34">' + R(0, "A(  )") + R(0, "B(  )")
                + LINESEG + '</hp:p>')
        tbl = TBL([TC(0, 0, para)], rows=1, cols=1)
        src = make_hwpx(tmp_path, make_header([CP_BLACK, CP_CELL]),
                        SEC(TBL_WRAP(tbl)))
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(src, out, [
            (0, 0, 0, "X", "append"), (0, 0, 1, "Y", "replace")])
        assert result["replaced"] == 2
        xml = section_xml(out)
        ET.fromstring(xml)
        assert "<hp:t>A(  )X</hp:t>" in xml and "<hp:t>Y</hp:t>" in xml
        assert "linesegarray" not in xml

    def test_empty_append_text_rejected(self, tmp_path):
        src = _seat_fixture(tmp_path)
        with pytest.raises(PreeditError, match="빈 텍스트"):
            preedit.replace_at_cells(src, tmp_path / "o.hwpx",
                                     [(1, 1, None, "", "append")])


# ---------------------------------------------------------------------------
# 9) fill-cells 다문단 (T39)
#
# failing-before: fill-cells는 셀의 문단 **하나**에만 쓰고 나머지를 비웠다.
# 공문 본문은 규정상 1. / 가. / 1) / 가)가 각각 자기 문단이라, 클린룸
# 에이전트는 기안문 별지에 '1.' 한 항목만 넣고 끝낼 수밖에 없었다(더 깊이
# 가려면 XML 손편집이 필요한데 스킬이 금지한다).
# ---------------------------------------------------------------------------

CP_SUP = ('<hh:charPr id="9" height="1000" textColor="#000000">'
          '<hh:supscript/></hh:charPr>')       # T30 함정: 본문 + 위첨자


def BLANK_P(cid=7, ppr=34):
    """양식이 예약해 둔 빈 문단(자기닫힘 런 + 캐시 레이아웃)."""
    return (f'<hp:p paraPrIDRef="{ppr}"><hp:run charPrIDRef="{cid}"/>'
            f'{LINESEG}</hp:p>')


def _body_cell_fixture(tmp_path, slots=4, *, tail="", name="body.hwpx",
                       charprs=None, extra_parapr=False):
    """기안문 본문 셀의 축소형: 예약된 빈 문단 여러 개 + (선택) 그 뒤 중첩 표.

    실측 형태 그대로다 — 기안문 별지 제1호서식 (2,0)은 빈 문단 18개 다음에
    직인·발신명의를 담은 중첩 표 문단이 오고, 그 뒤에 또 빈 문단이 있다.
    """
    header = make_header(charprs or [CP_BLACK, CP_BLUE, CP_CELL])
    if extra_parapr:
        header = header.replace(
            '<hh:paraPr id="34" tabPrIDRef="0"/>',
            '<hh:paraPr id="34" tabPrIDRef="0"/>'
            '<hh:paraPr id="35" tabPrIDRef="0"/>')
    tbl = TBL([TC(0, 0, "".join(BLANK_P() for _ in range(slots)) + tail)],
              tid="9", rows=1, cols=1)
    return make_hwpx(tmp_path, header, SEC(TBL_WRAP(tbl)), name=name)


def _cell_paragraphs(path, addr=(0, 0), table=0):
    xml = section_xml(path)
    cell = find_cell(scan_tables(xml)[table], *addr)
    return preedit._find_paragraphs(xml[cell["body_start"]:cell["body_end"]])


def _cell_texts(path, addr=(0, 0), table=0):
    """그 셀 문단들의 자기 텍스트(중첩 표 제외) — 문서 순서."""
    return [preedit._fragment_text(p) for _s, _e, p in
            _cell_paragraphs(path, addr, table)]


def _cell_geometry(xml):
    """표/셀 기하만 — 주소·병합·크기·테두리. 다문단이 늘려도 절대 안 바뀐다."""
    return ([[(c["addr"], c["span"], c["attrs"]) for c in t["cells"]]
             for t in scan_tables(xml)],
            re.findall(r'<hp:cellSz[^>]*/?>', xml),
            re.findall(r'<hp:cellAddr[^>]*/?>', xml),
            re.findall(r'<hp:cellSpan[^>]*/?>', xml))


class TestFillCellsMultiline:
    def test_writes_one_paragraph_per_line(self, tmp_path):
        """failing-before: 값의 개행은 아무 의미도 없었고 둘째 줄부터 사라졌다."""
        src = _body_cell_fixture(tmp_path, slots=4)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 0, "1. 첫째\n  가. 둘째\n    1) 셋째")])
        assert result["cells"][0]["paragraphs"] == 3
        assert _cell_texts(out)[:4] == ["1. 첫째", "  가. 둘째", "    1) 셋째", ""]
        ET.fromstring(section_xml(out))

    def test_newline_string_and_list_are_the_same_value(self, tmp_path):
        """개행 문자열과 배열은 같은 문단 목록의 두 표기다 — 결과가 같아야 한다."""
        src = _body_cell_fixture(tmp_path, slots=4)
        a, b = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
        fill_cells(src, a, [(0, 0, "1. 가\n2. 나")])
        fill_cells(src, b, [(0, 0, ["1. 가", "2. 나"])])
        assert content_fingerprint(a) == content_fingerprint(b)
        assert preedit.split_fill_lines("가\r\n나\r다") == ["가", "나", "다"]

    def test_reuses_the_blank_paragraphs_the_form_reserved(self, tmp_path):
        """양식이 예약한 자리를 먼저 쓴다 — 무조건 새로 만들면 셀이 예약분만큼
        통째로 길어져 표가 자라고 페이지가 늘어난다(실측: 기안문 본문 셀의
        빈 문단 18개)."""
        src = _body_cell_fixture(tmp_path, slots=6)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 0, "가\n나\n다")])
        assert (result["cells"][0]["paragraphs_reused"],
                result["cells"][0]["paragraphs_created"]) == (3, 0)
        assert len(_cell_paragraphs(out)) == len(_cell_paragraphs(src)) == 6

    def test_clones_the_target_paragraph_when_slots_run_out(self, tmp_path):
        """자리가 모자라면 target 문단을 복제한다 — paraPr(들여쓰기·정렬)과
        런 charPr이 양식 자신의 설계 그대로여야 한다."""
        src = _body_cell_fixture(tmp_path, slots=2)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 0, "가\n나\n다\n라")])
        assert (result["cells"][0]["paragraphs_reused"],
                result["cells"][0]["paragraphs_created"]) == (2, 2)
        paras = [p for _s, _e, p in _cell_paragraphs(out)]
        assert len(paras) == 4
        assert _cell_texts(out) == ["가", "나", "다", "라"]
        # 복제 문단은 target과 같은 paraPr·charPr을 진다(기본 서식 날조 금지)
        assert all('paraPrIDRef="34"' in p for p in paras)
        assert all('charPrIDRef="7"' in p for p in paras)

    def test_created_paragraphs_carry_no_linesegarray(self, tmp_path):
        """T24: 새 문단이 남의 캐시 좌표를 물고 나오면 그게 겹쳐 찍힘이다."""
        src = _body_cell_fixture(tmp_path, slots=1)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 0, "가\n나\n다")])
        assert "linesegarray" not in section_xml(out)

    def test_slots_stop_at_a_nested_table(self, tmp_path):
        """중첩 표(직인·발신명의)를 건너뛰고 그 **뒤** 빈 문단까지 자리로 세면
        본문 한 줄이 발신명의 아래에 찍힌다. 자리는 연속 구간까지다."""
        inner = TBL([TC(0, 0, P(R(0, "발신명의")))], tid="20", rows=1, cols=1)
        tail = TBL_WRAP(inner) + BLANK_P() + BLANK_P()
        src = _body_cell_fixture(tmp_path, slots=2, tail=tail)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 0, "가\n나\n다\n라")])
        assert result["cells"][0]["paragraphs_created"] == 2
        texts = _cell_texts(out)
        # 네 줄이 중첩 표 문단 **앞**에 연속으로 놓인다
        assert texts[:4] == ["가", "나", "다", "라"]
        assert "발신명의" in section_xml(out)
        assert texts[4].strip() == ""      # 중첩 표를 품은 문단의 자기 텍스트

    def test_geometry_is_byte_identical_after_a_multiline_fill(self, tmp_path):
        """문단을 새로 만들어도 셀 주소·병합·크기·테두리는 한 바이트도 안 바뀐다."""
        src = _body_cell_fixture(tmp_path, slots=1)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 0, "가\n나\n다\n라\n마")])
        assert _cell_geometry(section_xml(out)) == \
            _cell_geometry(section_xml(src))
        assert header_xml_of(out) == header_xml_of(src)

    def test_single_paragraph_path_is_unchanged(self, tmp_path):
        """음성 대조군: 한 줄 채우기는 T39 이전과 바이트 단위로 같은 일을 한다 —
        문단을 만들지도, 없애지도, 옮기지도 않는다."""
        src = _form_fixture(tmp_path)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 2, "이하율")])
        cell = result["cells"][0]
        assert (cell["paragraphs"], cell["paragraphs_reused"],
                cell["paragraphs_created"]) == (1, 1, 0)
        xml = section_xml(out)
        assert '<hp:run charPrIDRef="7"><hp:t>이하율</hp:t></hp:run>' in xml
        assert _cell_geometry(xml) == _cell_geometry(section_xml(src))
        # 문단 수·문단 여는 태그가 그대로 = 구조 변경 없음
        assert (preedit.P_OPEN_RE.findall(xml)
                == preedit.P_OPEN_RE.findall(section_xml(src)))
        # 손대지 않은 두 빈 셀의 lineseg는 바이트 그대로
        assert xml.count("<hp:linesegarray>") == 2

    def test_idempotent_under_overwrite(self, tmp_path):
        """2회차는 1회차가 만든 문단을 '예약된 자리'로 그대로 다시 쓴다."""
        src = _body_cell_fixture(tmp_path, slots=2)
        first, second = tmp_path / "a.hwpx", tmp_path / "b.hwpx"
        fill_cells(src, first, [(0, 0, "가\n나\n다\n라")])
        again = fill_cells(first, second, [(0, 0, "가\n나\n다\n라")],
                           overwrite=True)
        assert again["filled"] == 0
        assert again["cells"][0]["paragraphs_created"] == 0
        assert content_fingerprint(first) == content_fingerprint(second)

    def test_t30_preflight_sees_every_paragraph_it_will_write(self, tmp_path):
        """두 번째 자리가 supscript 클론이면 두 번째 줄이 6.35pt 올려찍힌다 —
        첫 줄만 검사하는 사전 점검은 T30을 한 문단 아래에서 그대로 재현한다."""
        cell = BLANK_P(7) + BLANK_P(9) + BLANK_P(7)
        tbl = TBL([TC(0, 0, cell), TC(0, 1, P(R(0, "본문 텍스트가 여기 많다")))],
                  tid="9", rows=1, cols=2)
        src = make_hwpx(tmp_path,
                        make_header([CP_BLACK, CP_BLUE, CP_CELL, CP_SUP]),
                        SEC(TBL_WRAP(tbl)))
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(0, 0, "한 줄")])          # 첫 자리는 정상
        with pytest.raises(preedit.ScriptAnomalyError) as exc:
            fill_cells(src, tmp_path / "no.hwpx", [(0, 0, "가\n나")])
        assert not (tmp_path / "no.hwpx").exists()
        assert [a["charpr"] for a in exc.value.anomalies] == ["9"]
        assert exc.value.anomalies[0]["addr"] == [0, 0]
        # 셀 단위 재지정 하나로 그 셀의 모든 문단이 함께 정상화된다
        ok = fill_cells(src, tmp_path / "ok.hwpx", [(0, 0, "가\n나")],
                        charpr_per_cell={(0, 0): "0"})
        assert ok["filled"] == 1
        written = [p for _s, _e, p in _cell_paragraphs(tmp_path / "ok.hwpx")]
        assert [preedit._para_first_run_charpr(p) for p in written] == \
            ["0", "0", "7"]

    def test_parapr_per_cell_repoints_only_the_written_paragraphs(self,
                                                                  tmp_path):
        """양식이 빈 문단에 걸어 둔 문단서식이 본문용이 아닐 때의 탈출구.
        쓰지 않은 문단은 그대로 둔다."""
        src = _body_cell_fixture(tmp_path, slots=3, extra_parapr=True)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 0, "가\n나")],
                            parapr_per_cell={(0, 0): "35"})
        assert result["cells"][0]["parapr"] == "35"
        paras = [p for _s, _e, p in _cell_paragraphs(out)]
        assert ['paraPrIDRef="35"' in p for p in paras] == [True, True, False]

    def test_dangling_parapr_is_caught_before_writing(self, tmp_path):
        """T22의 자매 단언 — 정의 없는 paraPr id로 재지정하면 출력 전에 터진다."""
        src = _body_cell_fixture(tmp_path, slots=2)
        out = tmp_path / "out.hwpx"
        with pytest.raises(AssertionError, match="paraPr"):
            fill_cells(src, out, [(0, 0, "가\n나")],
                       parapr_per_cell={(0, 0): "999"})

    def test_unknown_parapr_address_is_rejected(self, tmp_path):
        src = _body_cell_fixture(tmp_path, slots=2)
        with pytest.raises(PreeditError, match="--parapr-per-cell"):
            fill_cells(src, tmp_path / "o.hwpx", [(0, 0, "가")],
                       parapr_per_cell={(3, 3): "34"})


class TestFillCellsMultilineCli:
    def test_cell_line_stacks_paragraphs_in_order(self, tmp_path):
        """PowerShell에서 개행 없이 계층 본문을 쓰는 표기 — 준 순서가 문단 순서."""
        src = _body_cell_fixture(tmp_path, slots=4)
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out,
                    "--cell-line", "0,0=1. 자료 제출 요청",
                    "--cell-line", "0,0=  가. 제출 기한: 2026. 9. 30.",
                    "--cell-line", "0,0=    1) 전자문서시스템 첨부")
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["cells"][0]["paragraphs"] == 3
        assert _cell_texts(out)[:3] == [
            "1. 자료 제출 요청", "  가. 제출 기한: 2026. 9. 30.",
            "    1) 전자문서시스템 첨부"]

    def test_cell_and_cell_line_on_one_address_is_a_usage_error(self, tmp_path):
        """두 플래그의 상대 순서는 정의되지 않는다 — 조용히 한 쪽을 앞세우지 않는다."""
        src = _body_cell_fixture(tmp_path, slots=4)
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out,
                    "--cell", "0,0=가", "--cell-line", "0,0=나")
        assert proc.returncode == 2
        assert not out.exists()
        assert "--cell-line" in json.loads(proc.stdout)["error"]

    def test_map_accepts_a_list_of_paragraphs(self, tmp_path):
        src = _body_cell_fixture(tmp_path, slots=4)
        cells = tmp_path / "cells.json"
        cells.write_text(json.dumps({"0,0": ["1. 가", "  가. 나"]},
                                    ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out, "--map", cells)
        assert proc.returncode == 0, proc.stdout
        assert _cell_texts(out)[:2] == ["1. 가", "  가. 나"]

    def test_parapr_per_cell_through_the_cli(self, tmp_path):
        src = _body_cell_fixture(tmp_path, slots=3, extra_parapr=True)
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out,
                    "--cell-line", "0,0=가", "--cell-line", "0,0=나",
                    "--parapr-per-cell", "0,0=35")
        assert proc.returncode == 0, proc.stdout
        assert json.loads(proc.stdout)["cells"][0]["parapr"] == "35"
