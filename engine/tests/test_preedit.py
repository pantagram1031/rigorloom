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
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import preedit  # noqa: E402
from preedit import (  # noqa: E402
    PreeditError,
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
