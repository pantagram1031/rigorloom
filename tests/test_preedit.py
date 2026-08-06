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
    return ('<hh:head><hh:refList>'
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
    return '<hs:sec>' + "".join(paras) + '</hs:sec>'


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
        result = replace_placeholders(src, out, {"20101": "20999",
                                                 "제목 자리": "진짜 제목"})
        assert result["hits"] == {"20101": 2, "제목 자리": 1}
        assert "20999" in section_xml(out)
        assert "진짜 제목" in section_xml(out)
        assert content_fingerprint(src) == before  # 원본 비파괴

    def test_trailing_space_run_matched_failing_before(self, tmp_path):
        """failing-before(hawkes sim 결함): 저자표 런에 trailing space가 있으면
        sim의 ">키<" 정확일치는 조용히 실패했다. strip-비교 tier는 잡고,
        결과 런에는 잔여 공백도 남지 않아야 한다."""
        key, val = "10101 김새봄", "20999 김가상"
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
        mapping = {"20101": "20999", "제목 자리": "진짜 제목"}
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

BYLINE = "20999 김가상"


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
