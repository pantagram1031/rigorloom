# -*- coding: utf-8 -*-
"""T30 사전 점검(pre-flight) — 채우기 전에 charPr 이상을 잡는다.

T30은 두 번째 클린룸 교차모델 런(Opus tier)에서 나온 결함이다. `preedit
fill-cells`는 "런의 charPr을 보존한다"고 문서마다 안전 동작으로 적혀 있는데,
PPS 양식 (10,2) 셀의 빈 런은 본문과 **동일한** charPr에 `<hh:supscript/>`만
붙은 클론을 지고 있었다 — 올바르게 보이는 채우기가 ~6.35pt 올려찍힘으로
렌더됐고, nominal height는 그대로여서 charpr_check도 style_diff도 통과했다.
사후에 `visual_verify`만이 잡았다. 게다가 올바른 `--charpr` id를 찾으려면
에이전트가 header.xml을 손으로 읽어야 했는데, 배포된 계약("구조만 보고 본문은
덤프하지 말 것")은 바로 그것을 막고 있었다.

여기 고정하는 계약:
  1. form_inspect가 fill_target 셀마다 charpr / script_anomaly /
     charpr_suggested를 보고한다(baseline id는 상단에 한 번 더).
  2. --charpr(또는 --charpr-per-cell) 없이 script_anomaly 셀을 채우려 하면
     fill-cells가 **큰 소리로** 거부한다(exit 3) — 조용한 6pt 채우기 금지.
  3. --charpr-per-cell로 셀마다 다른 id를 줄 수 있다(--charpr는 배치 전체에만
     적용되는 제약 — T32).
  4. 정상 문서에는 오탐이 없고, 의도적으로 위첨자인 **비대상** 런은 절대
     플래그되지 않는다.
  5. (T34) 주소 키 치환 `replace --at-cell`도 **같은** 사전 점검을 진다 —
     자리표를 고쳐 넣은 값도 사후 게이트가 같은 다섯 속성으로 보므로, 새 경로가
     T30을 우회하는 뒷문이 되면 안 된다. 거부는 `--at-cell-charpr` 플래그를
     이름 붙여 알려주고, 그 플래그는 그대로 붙여넣으면 통해야 한다.
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import charpr_script  # noqa: E402
import form_inspect  # noqa: E402
from hwpx_tables import find_cell, scan_tables  # noqa: E402
import preedit  # noqa: E402
from preedit import (  # noqa: E402
    ScriptAnomalyError,
    fill_cells,
    fill_target_run_charpr,
)

PREEDIT = ROOT / "scripts" / "preedit.py"
FORM_INSPECT = ROOT / "scripts" / "form_inspect.py"

LINESEG = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"'
           ' horzsize="12980"/></hp:linesegarray>')

#: 본문 baseline이 되는 charPr(가장 많은 본문 텍스트를 지는 id)과 그 클론들.
#: 7 = 정상 빈 셀 런, 9 = 함정(본문 + supscript), 10 = 함정(relSz 축소),
#: 8 = 진짜 각주 표식(비대상 런 — 절대 플래그 금지),
#: 11 = 정상적으로 큰 셀 서식(script 없음) — 셀마다 다른 id가 필요한 이유.
CHARPRS = (
    '<hh:charPr id="0" height="1000" textColor="#000000"/>',
    '<hh:charPr id="7" height="1000" textColor="#000000"/>',
    '<hh:charPr id="8" height="1000" textColor="#000000">'
    '<hh:supscript/></hh:charPr>',
    '<hh:charPr id="9" height="1000" textColor="#000000">'
    '<hh:supscript/></hh:charPr>',
    '<hh:charPr id="10" height="1000" textColor="#000000">'
    '<hh:relSz hangul="65" latin="65"/></hh:charPr>',
    '<hh:charPr id="11" height="1200" textColor="#000000"/>',
)


def header_xml(charprs=CHARPRS):
    return ('<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">'
            '<hh:refList>'
            f'<hh:charProperties itemCnt="{len(charprs)}">'
            + "".join(charprs) +
            '</hh:charProperties>'
            '<hh:paraProperties itemCnt="1">'
            '<hh:paraPr id="34" tabPrIDRef="0"/>'
            '</hh:paraProperties></hh:refList></hh:head>')


def R(cid, text):
    return f'<hp:run charPrIDRef="{cid}"><hp:t>{text}</hp:t></hp:run>'


def P(*runs):
    return '<hp:p paraPrIDRef="34">' + "".join(runs) + '</hp:p>'


def EMPTY_P(cid):
    """양식의 '진짜 빈 셀' 표준형 — hp:t가 아예 없는 자기닫힘 런 하나."""
    return (f'<hp:p paraPrIDRef="34"><hp:run charPrIDRef="{cid}"/>'
            f'{LINESEG}</hp:p>')


def TC(row, col, inner, *, row_span=1, col_span=1):
    return (f'<hp:tc borderFillIDRef="5"><hp:subList>{inner}</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>'
            f'<hp:cellSz width="1000" height="500"/></hp:tc>')


def SEC(*paras):
    return ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            + "".join(paras) + '</hs:sec>')


#: 본문 산문 — baseline이 charPr 0이 되도록 충분한 무게를 준다.
BODY = " ".join(f"본문 문장 {i} 은 표준 서식으로 작성한 일반 서술 문단이다."
                for i in range(6))


def pps_form(tmp_path, *, name="pps.hwpx", target_charprs=(7, 9, 10),
             footnote=True, charprs=CHARPRS):
    """PPS 양식의 형태: 라벨 열 + 빈 셀 3개.

    target_charprs: 세 빈 셀 (0,2)/(1,2)/(2,1)의 런 charPr. 기본값은 실사고
    형태 — 정상 하나(7)와 이상 둘(9=supscript, 10=relSz)이 섞여 있다.
    footnote: 의도적으로 위첨자인 **비대상** 런(charPr 8)을 본문에 둔다.
    """
    a, b, c = target_charprs
    tbl = (
        '<hp:tbl id="9" rowCnt="3" colCnt="3"><hp:tr>'
        + TC(0, 0, P(R(0, "신 청 인")), row_span=2)
        + TC(0, 1, P(R(0, "협업제품명")))
        + TC(0, 2, EMPTY_P(a))
        + TC(1, 1, P(R(0, "생년월일")))
        + TC(1, 2, EMPTY_P(b))
        + TC(2, 0, P(R(0, "주 소")))
        + TC(2, 1, EMPTY_P(c), col_span=2)
        + '</hp:tr></hp:tbl>'
    )
    marker = P(R(0, "각주 대상 문구"), R(8, "1)")) if footnote else ""
    section = SEC(
        P(R(0, "I.  서론")),
        f'<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>',
        P(R(0, BODY)),
        marker,
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", header_xml(charprs))
        z.writestr("Contents/section0.xml", section)
    return path


def section_of(path):
    with zipfile.ZipFile(path) as z:
        return z.read("Contents/section0.xml").decode("utf-8")


def cell_at(profile, row, col, table=0):
    for c in profile["table_map"][table]["cells"]:
        if c["addr"] == {"row": row, "col": col}:
            return c
    raise AssertionError(f"no cell at ({row},{col})")


# ---------------------------------------------------------------------------
# 1) form_inspect — 사전 점검 필드
# ---------------------------------------------------------------------------

class TestFormInspectPreflight:
    def test_reports_baseline_once_at_top_level(self, tmp_path):
        profile, _ = form_inspect.analyze(pps_form(tmp_path))
        baseline = profile["body_baseline_charpr"]
        # 본문 산문을 가장 많이 지는 charPr이 baseline이다(빈 셀 런이 아니다)
        assert baseline["id"] == "0"
        assert baseline["height_pt"] == 10.0
        assert baseline["signature"]["supscript"] is False
        assert baseline["signature"]["relSz"] is None

    def test_flags_the_anomalous_target_with_the_suggested_id(self, tmp_path):
        """실사고 형태: 정상 대상들 사이에 이상 대상 하나 — 그것만 플래그되고,
        무엇을 대신 써야 하는지가 같이 나온다(header.xml 손 판독 불필요)."""
        profile, _ = form_inspect.analyze(pps_form(tmp_path))

        normal = cell_at(profile, 0, 2)
        assert normal["classification"] == "fill_target"
        assert normal["charpr"] == "7"
        assert normal["script_anomaly"] is False
        assert normal["charpr_suggested"] == "0"

        trap = cell_at(profile, 1, 2)
        assert trap["classification"] == "fill_target"
        assert trap["charpr"] == "9"
        assert trap["script_anomaly"] is True
        assert trap["script_differing"] == ["supscript"]
        assert trap["charpr_suggested"] == "0"
        # 사고의 핵심: nominal 10pt인데 렌더는 ~6.35pt
        assert trap["nominal_height_pt"] == 10.0
        assert trap["rendered_pt_estimate"] == pytest.approx(6.35, abs=0.01)

    def test_scaling_trap_counts_too_and_claims_no_render_estimate(
            self, tmp_path):
        """함정은 위첨자 전용이 아니다 — relSz/ratio/offset도 height를 건드리지
        않고 런을 줄인다. script flag가 아니므로 렌더 pt 추정은 주장하지 않는다."""
        profile, _ = form_inspect.analyze(pps_form(tmp_path))
        scaled = cell_at(profile, 2, 1)
        assert scaled["script_anomaly"] is True
        assert scaled["script_differing"] == ["relSz"]
        assert "rendered_pt_estimate" not in scaled

    def test_anomaly_targets_summary_lists_only_the_anomalies(self, tmp_path):
        profile, _ = form_inspect.analyze(pps_form(tmp_path))
        summary = profile["script_anomaly_targets"]
        assert [(t["addr"]["row"], t["addr"]["col"]) for t in summary] == [
            (1, 2), (2, 1)]
        assert {t["charpr_suggested"] for t in summary} == {"0"}

    def test_clean_form_flags_nothing(self, tmp_path):
        """오탐 금지: 대상이 전부 정상인 문서는 영향받지 않는다."""
        profile, _ = form_inspect.analyze(
            pps_form(tmp_path, target_charprs=(7, 7, 7)))
        assert profile["script_anomaly_targets"] == []
        for addr in ((0, 2), (1, 2), (2, 1)):
            assert cell_at(profile, *addr)["script_anomaly"] is False

    def test_intentional_superscript_on_a_non_target_is_never_flagged(
            self, tmp_path):
        """charPr 8의 각주 표식 '1)'은 진짜 위첨자이고 채우기 대상이 아니다.
        사전 점검은 fill_target 셀만 본다 — 비대상 런은 비교조차 하지 않는다."""
        src = pps_form(tmp_path, target_charprs=(7, 7, 7), footnote=True)
        assert 'charPrIDRef="8"' in section_of(src)  # 위첨자 런은 문서에 있다
        profile, _ = form_inspect.analyze(src)
        assert profile["script_anomaly_targets"] == []
        # 비대상 셀·문단에는 사전 점검 필드 자체가 붙지 않는다
        label = cell_at(profile, 0, 1)
        assert label["classification"] == "static"
        assert "script_anomaly" not in label

    def test_cli_summary_names_the_baseline_and_the_count(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "profile.json"
        proc = subprocess.run(
            [sys.executable, str(FORM_INSPECT), str(src), "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr
        assert "body_baseline_charpr=0" in proc.stdout
        assert "script_anomaly_targets=2" in proc.stdout
        assert json.loads(out.read_text(encoding="utf-8"))[
            "body_baseline_charpr"]["id"] == "0"


# ---------------------------------------------------------------------------
# 2) 사전 점검과 실제 채우기는 같은 런을 본다
# ---------------------------------------------------------------------------

def test_preflight_and_fill_agree_on_which_run_is_written(tmp_path):
    """form_inspect가 보고하는 charpr는 fill_cells가 실제로 상속할 그 런이다 —
    두 도구가 어긋날 수 있으면 사전 점검은 없는 것보다 나쁘다."""
    src = pps_form(tmp_path, target_charprs=(7, 7, 7))
    profile, _ = form_inspect.analyze(src)
    xml = section_of(src)
    table = scan_tables(xml)[0]
    for row, col in ((0, 2), (1, 2), (2, 1)):
        cell = find_cell(table, row, col)
        body = xml[cell["body_start"]:cell["body_end"]]
        assert cell_at(profile, row, col)["charpr"] == \
            fill_target_run_charpr(body)


def test_shared_comparison_logic_is_the_same_module(tmp_path):
    """form_inspect와 visual_verify가 같은 판정을 쓰는지 — 같은 함수인지로
    확인한다(값 비교가 아니라 동일성). 갈라지면 이 테스트가 먼저 깨진다."""
    sys.path.insert(0, str(ROOT.parent / "pipeline" / "scripts"))
    import visual_verify
    assert visual_verify._script_signature is charpr_script.signature
    assert visual_verify._SCRIPT_FLAG_TAGS is charpr_script.SCRIPT_FLAG_TAGS
    assert visual_verify._SCRIPT_SCALE_TAGS is charpr_script.SCRIPT_SCALE_TAGS


# ---------------------------------------------------------------------------
# 3) fill-cells — 거부와 --charpr-per-cell
# ---------------------------------------------------------------------------

class TestFillCellsRefusal:
    def test_refuses_anomalous_target_without_explicit_charpr(self, tmp_path):
        """failing-before: 이 호출은 조용히 성공해서 ~6.35pt 올려찍힌 값을
        만들었다. 이제는 거부하고 아무것도 쓰지 않는다."""
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(ScriptAnomalyError) as exc:
            fill_cells(src, out, [(1, 2, "2026-08-08")])
        assert not out.exists()
        assert exc.value.exit_code == 3
        (anomaly,) = exc.value.anomalies
        assert anomaly["addr"] == [1, 2]
        assert anomaly["charpr"] == "9"
        assert anomaly["charpr_suggested"] == "0"
        assert anomaly["differing"] == ["supscript"]

    def test_refusal_message_names_cell_charpr_suggestion_and_flag(
            self, tmp_path):
        """거부를 읽고 header.xml을 손으로 뒤져야 한다면 사전 점검이 아니다."""
        src = pps_form(tmp_path)
        with pytest.raises(ScriptAnomalyError) as exc:
            fill_cells(src, tmp_path / "o.hwpx", [(1, 2, "값")])
        msg = str(exc.value)
        assert "1,2" in msg                       # 어느 셀인가
        assert "charPr=9" in msg                  # 무엇이 이상한가
        assert "charPr=0" in msg                  # 무엇을 대신 쓸까
        assert "--charpr-per-cell 1,2=0" in msg   # 정확히 넘길 플래그
        assert "6.35" in msg                      # 무슨 일이 벌어졌을까
        # nominal은 baseline과 나란히 — 코퍼스에서 1~2pt 간격용 런이 대상으로
        # 잡히는 경우가 있고, 그때 "nominal 2.0pt" 단독으로는 판단이 안 된다
        assert "nominal 10.0pt vs baseline 10.0pt" in msg
        # 기계적으로 되먹일 수 있는 플래그 목록
        assert exc.value.suggested_flags == ["--charpr-per-cell", "1,2=0"]

    def test_normal_targets_are_unaffected_no_false_refusal(self, tmp_path):
        """정상 대상만 있는 배치는 --charpr 없이도 그대로 성공한다."""
        src = pps_form(tmp_path, target_charprs=(7, 7, 7))
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(0, 2, "이하율"), (1, 2, "2010-03-01"),
                                       (2, 1, "서울")])
        assert result["filled"] == 3
        assert result["body_baseline_charpr_id"] == "0"
        xml = section_of(out)
        assert '<hp:run charPrIDRef="7"><hp:t>이하율</hp:t></hp:run>' in xml
        ET.fromstring(xml)

    def test_a_normal_target_beside_an_anomalous_one_still_refuses(
            self, tmp_path):
        """배치가 원자적이라는 기존 계약과 결합: 한 셀이 이상하면 정상 셀도
        쓰이지 않는다."""
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(ScriptAnomalyError) as exc:
            fill_cells(src, out, [(0, 2, "정상"), (1, 2, "함정")])
        assert not out.exists()
        assert [a["addr"] for a in exc.value.anomalies] == [[1, 2]]

    def test_explicit_charpr_silences_the_refusal(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(1, 2, "2026-08-08")], charpr="0")
        assert result["filled"] == 1
        assert result["cells"][0]["charpr"] == "0"
        xml = section_of(out)
        assert '<hp:run charPrIDRef="0"><hp:t>2026-08-08</hp:t></hp:run>' in xml
        assert 'charPrIDRef="9"' not in xml


class TestCharprPerCell:
    """--charpr는 **배치 전체**에 적용된다(T32). 대상들이 서로 다른 id를
    필요로 하면 한 번의 호출로는 표현할 수 없었다 — 문서화되지 않은 제약이다."""

    def test_batch_wide_charpr_cannot_express_two_different_ids(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        # (1,2)는 본문 서식(0), (2,1)은 정상적으로 큰 셀 서식(11)이어야 한다.
        # --charpr 0은 둘 다 0으로 만든다 = (2,1)이 조용히 본문 크기로 납작해짐.
        fill_cells(src, out, [(1, 2, "값A"), (2, 1, "값B")], charpr="0")
        xml = section_of(out)
        assert '<hp:run charPrIDRef="0"><hp:t>값A</hp:t></hp:run>' in xml
        assert '<hp:run charPrIDRef="0"><hp:t>값B</hp:t></hp:run>' in xml
        assert 'charPrIDRef="11"' not in xml

    def test_per_cell_gives_each_target_its_own_id(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        result = fill_cells(src, out, [(1, 2, "값A"), (2, 1, "값B")],
                            charpr_per_cell={(1, 2): "0", (2, 1): "11"})
        assert result["filled"] == 2
        assert [c["charpr"] for c in result["cells"]] == ["0", "11"]
        xml = section_of(out)
        assert '<hp:run charPrIDRef="0"><hp:t>값A</hp:t></hp:run>' in xml
        assert '<hp:run charPrIDRef="11"><hp:t>값B</hp:t></hp:run>' in xml
        ET.fromstring(xml)

    def test_per_cell_overrides_the_batch_wide_charpr(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        fill_cells(src, out, [(1, 2, "값A"), (2, 1, "값B")], charpr="0",
                   charpr_per_cell={(2, 1): "11"})
        xml = section_of(out)
        assert '<hp:run charPrIDRef="0"><hp:t>값A</hp:t></hp:run>' in xml
        assert '<hp:run charPrIDRef="11"><hp:t>값B</hp:t></hp:run>' in xml

    def test_per_cell_covers_only_one_of_two_anomalies_still_refuses(
            self, tmp_path):
        """부분 지정은 부분 거부다 — 남은 이상 셀만 이름 불러 거부한다."""
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(ScriptAnomalyError) as exc:
            fill_cells(src, out, [(1, 2, "값A"), (2, 1, "값B")],
                       charpr_per_cell={(1, 2): "0"})
        assert not out.exists()
        assert [a["addr"] for a in exc.value.anomalies] == [[2, 1]]

    def test_per_cell_address_not_in_the_fill_list_is_a_typo(self, tmp_path):
        src = pps_form(tmp_path)
        with pytest.raises(Exception, match="charpr-per-cell"):
            fill_cells(src, tmp_path / "o.hwpx", [(0, 2, "값")],
                       charpr_per_cell={(9, 9): "0"})

    def test_dangling_charpr_guard_still_runs_for_per_cell(self, tmp_path):
        """T22: 정의 없는 id로 재지정하면 출력 전에 터진다."""
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(Exception):
            fill_cells(src, out, [(1, 2, "값")],
                       charpr_per_cell={(1, 2): "999"})


# ---------------------------------------------------------------------------
# 4) CLI 계약 — exit 3 + 기계 판독 가능한 거부
# ---------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, str(PREEDIT), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")


class TestFillCellsCli:
    def test_refusal_exits_3_with_machine_readable_anomalies(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out, "--cell", "1,2=값")
        assert proc.returncode == 3, proc.stdout
        assert not out.exists()
        payload = json.loads(proc.stdout)
        assert payload["ok"] is False
        assert payload["code_name"] == "fill_charpr_script_anomaly"
        (anomaly,) = payload["anomalies"]
        assert anomaly["addr"] == [1, 2]
        assert anomaly["charpr_suggested"] == "0"
        assert payload["suggested_flags"] == ["--charpr-per-cell", "1,2=0"]
        assert "--charpr-per-cell 1,2=0" in payload["error"]

    def test_the_suggested_flag_from_the_refusal_actually_works(self, tmp_path):
        """거부가 알려준 플래그를 그대로 붙여넣으면 통과한다 — 사전 점검의
        전부는 이 왕복이 사람 판독 없이 닫히는 것이다."""
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        refused = json.loads(_cli("fill-cells", src, "--out", out,
                                  "--cell", "1,2=값").stdout)
        addr = refused["anomalies"][0]["addr"]
        flag = f"{addr[0]},{addr[1]}={refused['anomalies'][0]['charpr_suggested']}"
        proc = _cli("fill-cells", src, "--out", out, "--cell", "1,2=값",
                    "--charpr-per-cell", flag)
        assert proc.returncode == 0, proc.stdout
        assert json.loads(proc.stdout)["filled"] == 1
        assert '<hp:run charPrIDRef="0"><hp:t>값</hp:t></hp:run>' in \
            section_of(out)

    def test_two_targets_two_ids_through_the_cli(self, tmp_path):
        src = pps_form(tmp_path)
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out,
                    "--cell", "1,2=값A", "--cell", "2,1=값B",
                    "--charpr-per-cell", "1,2=0",
                    "--charpr-per-cell", "2,1=11")
        assert proc.returncode == 0, proc.stdout
        assert [c["charpr"] for c in json.loads(proc.stdout)["cells"]] == \
            ["0", "11"]

    def test_malformed_per_cell_spec_is_a_usage_error(self, tmp_path):
        src = pps_form(tmp_path)
        proc = _cli("fill-cells", src, "--out", tmp_path / "o.hwpx",
                    "--cell", "0,2=값", "--charpr-per-cell", "0,2")
        assert proc.returncode == 2
        assert "ROW,COL=ID" in json.loads(proc.stdout)["error"]

    def test_duplicate_per_cell_spec_is_a_usage_error(self, tmp_path):
        src = pps_form(tmp_path)
        proc = _cli("fill-cells", src, "--out", tmp_path / "o.hwpx",
                    "--cell", "0,2=값",
                    "--charpr-per-cell", "0,2=0",
                    "--charpr-per-cell", "0,2=11")
        assert proc.returncode == 2
        assert "중복" in json.loads(proc.stdout)["error"]

    def test_clean_form_cli_still_exits_0(self, tmp_path):
        src = pps_form(tmp_path, target_charprs=(7, 7, 7))
        out = tmp_path / "out.hwpx"
        proc = _cli("fill-cells", src, "--out", out, "--cell", "0,2=이하율")
        assert proc.returncode == 0, proc.stdout


# ---------------------------------------------------------------------------
# 5) 코퍼스 실측 — 거부의 규모와 탈출구
# ---------------------------------------------------------------------------

CORPUS = ROOT.parent / "tests" / "corpus" / "forms" / "converted"
#: 코퍼스 실측(2026-08-08): 이상 대상이 한 양식에 최대 18개까지 나온다. 대부분은
#: `ratio`(장평) 2~5%p 차이 — 양식 자신의 타이포그래피다. 그래도 사후 게이트
#: (visual_verify의 fill_charpr_script_mismatch)가 **같은 비교**로 HARD를 내므로,
#: 사전 점검이 이것들을 통과시키면 "사전 점검은 통과했는데 게이트가 막는" 최악의
#: 조합이 된다. 그래서 거부는 유지하고, 대신 한 번에 전부 이름 부르고 붙여넣을
#: 플래그를 함께 낸다. 완화하려면 두 반쪽을 동시에 재조정해야 한다(홀드아웃 필요).
BUSIEST_FORM = CORPUS / "jeongbo-gonggae-cheongguseo.hwpx"


@pytest.mark.skipif(not BUSIEST_FORM.exists(), reason="corpus absent")
def test_corpus_form_anomalies_are_named_all_at_once(tmp_path):
    """실제 양식에서 거부가 나면, 이상 대상 전부와 그대로 쓸 플래그가 한 번에
    나와야 한다 — 셀마다 다시 실행하게 만들면 사전 점검이 숙제가 된다."""
    profile, _ = form_inspect.analyze(BUSIEST_FORM)
    anomalies = profile["script_anomaly_targets"]
    assert len(anomalies) >= 5, len(anomalies)   # 코퍼스 실측: 18
    # 같은 표의 이상 대상들을 한 배치로 채우려 하면
    table = anomalies[0]["table"]
    same_table = [a for a in anomalies if a["table"] == table][:4]
    fills = [(a["addr"]["row"], a["addr"]["col"], "값") for a in same_table]
    with pytest.raises(ScriptAnomalyError) as exc:
        fill_cells(BUSIEST_FORM, tmp_path / "out.hwpx", fills, table=table)
    assert len(exc.value.anomalies) == len(same_table)
    # 붙여넣을 플래그가 대상마다 정확히 한 쌍
    assert exc.value.suggested_flags.count("--charpr-per-cell") == \
        len(same_table)
    assert not (tmp_path / "out.hwpx").exists()


@pytest.mark.skipif(not BUSIEST_FORM.exists(), reason="corpus absent")
def test_corpus_suggested_flags_close_the_loop(tmp_path):
    """거부가 낸 플래그를 그대로 되먹이면 통과한다 — 실제 양식에서도."""
    profile, _ = form_inspect.analyze(BUSIEST_FORM)
    target = profile["script_anomaly_targets"][0]
    row, col = target["addr"]["row"], target["addr"]["col"]
    out = tmp_path / "out.hwpx"
    result = fill_cells(BUSIEST_FORM, out, [(row, col, "값")],
                        table=target["table"],
                        charpr_per_cell={(row, col): target["charpr_suggested"]})
    assert result["filled"] == 1
    assert result["cells"][0]["charpr"] == target["charpr_suggested"]


@pytest.mark.skipif(not CORPUS.is_dir(), reason="corpus absent")
def test_corpus_forms_with_no_anomaly_are_never_refused(tmp_path):
    """오탐 상한: 이상 대상이 0개로 보고된 양식은 --charpr 없이 채워진다.
    코퍼스 실측으로 그런 양식이 여럿 있다(admrul/gianmun-2ho/moel 2013·2025)."""
    clean = []
    for form in sorted(CORPUS.glob("*.hwpx")):
        profile, _ = form_inspect.analyze(form)
        if profile["script_anomaly_targets"]:
            continue
        targets = [(t["index"], c) for t in profile["table_map"]
                   for c in t["cells"]
                   if c.get("classification") == "fill_target" and c["addr"]]
        if targets:
            clean.append((form, targets[0]))
    assert len(clean) >= 3, [f.name for f, _ in clean]
    for form, (table, cell) in clean:
        out = tmp_path / f"{form.stem}.out.hwpx"
        result = fill_cells(form, out, [(cell["addr"]["row"],
                                         cell["addr"]["col"], "값")],
                            table=table)
        assert result["filled"] == 1, form.name
        assert result["cells"][0]["charpr"] is None   # charPr 보존


# ---------------------------------------------------------------------------
# 5) replace --at-cell 도 같은 사전 점검을 진다 (T34가 T30을 우회하지 않는다)
#
# 자리표를 고쳐 넣은 값도 사후 게이트(visual_verify
# fill_charpr_script_mismatch)가 같은 다섯 속성으로 본다. 사전 점검이
# 통과시킨 것을 게이트가 막으면 최악이므로, 주소 키 치환도 이상 런을 거부하고
# 넘어갈 플래그를 이름 붙여 알려준다.
# ---------------------------------------------------------------------------

def seat_form(tmp_path, *, name="seat.hwpx", seat_charprs=(7, 9)):
    """자리표가 인쇄된 셀 둘 — 하나는 정상 charPr, 하나는 이상(supscript)."""
    a, b = seat_charprs
    tbl = (
        '<hp:tbl id="9" rowCnt="2" colCnt="2"><hp:tr>'
        + TC(0, 0, P(R(0, "홈페이지")))
        + TC(0, 1, P(R(a, " http://")))
        + TC(1, 0, P(R(0, "협 업 기 간")))
        + TC(1, 1, P(R(b, "20   .    .    .  ~  20   .    .    .   (     개월)")))
        + '</hp:tr></hp:tbl>'
    )
    section = SEC(
        P(R(0, "I.  서론")),
        f'<hp:p paraPrIDRef="34"><hp:run charPrIDRef="0">{tbl}</hp:run></hp:p>',
        P(R(0, BODY)),
        P(R(0, "각주 대상 문구"), R(8, "1)")),
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", header_xml())
        z.writestr("Contents/section0.xml", section)
    return path


class TestAtCellPreflight:
    def test_normal_seat_run_is_not_refused(self, tmp_path):
        src = seat_form(tmp_path)
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(
            src, out, [(0, 1, None, "host.kr", "append")])
        assert result["replaced"] == 1
        assert result["cells"][0]["charpr"] is None      # charPr 보존

    def test_anomalous_seat_run_is_refused_naming_the_at_cell_flag(
            self, tmp_path):
        """거부 메시지의 플래그가 fill-cells의 것이 아니라 --at-cell-charpr
        이어야 한다 — 붙여넣으면 그대로 통해야 의미가 있다."""
        src = seat_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(ScriptAnomalyError) as exc:
            preedit.replace_at_cells(src, out, [(1, 1, None, "6개월",
                                                 "replace")])
        assert not out.exists()
        assert exc.value.suggested_flags == ["--at-cell-charpr", "1,1#0=0"]
        assert "--at-cell-charpr 1,1#0=0" in str(exc.value)

    def test_suggested_flag_closes_the_loop(self, tmp_path):
        src = seat_form(tmp_path)
        out = tmp_path / "out.hwpx"
        result = preedit.replace_at_cells(
            src, out, [(1, 1, None, "6개월", "replace")],
            charpr_at_cell={(1, 1, None): "0"})
        assert result["cells"][0]["charpr"] == "0"
        assert '<hp:run charPrIDRef="0"><hp:t>6개월</hp:t></hp:run>' \
            in section_of(out)

    def test_dangling_charpr_guard_still_runs(self, tmp_path):
        """T22: 정의 없는 id로 재지정하면 출력 전에 터진다."""
        src = seat_form(tmp_path)
        out = tmp_path / "out.hwpx"
        with pytest.raises(Exception):
            preedit.replace_at_cells(
                src, out, [(0, 1, None, "값", "replace")],
                charpr_at_cell={(0, 1, None): "999"})

    def test_intentional_superscript_run_is_out_of_scope(self, tmp_path):
        """비대상 런(진짜 각주 표식)은 애초에 비교 대상이 아니다 — 그 런을
        **명시적으로** 고치겠다고 할 때만 사전 점검에 걸린다."""
        src = seat_form(tmp_path)
        out = tmp_path / "out.hwpx"
        preedit.replace_at_cells(src, out, [(0, 1, None, "x", "append")])
        assert '<hp:run charPrIDRef="8"><hp:t>1)</hp:t></hp:run>' \
            in section_of(out)


class TestAtCellCli:
    def test_map_and_at_cell_are_mutually_exclusive(self, tmp_path):
        src = seat_form(tmp_path)
        mp = tmp_path / "m.json"
        mp.write_text('{"a": "b"}', encoding="utf-8")
        proc = _cli("replace", src, "--out", tmp_path / "o.hwpx",
                    "--map", mp, "--at-cell", "0,1=x")
        assert proc.returncode == 2, proc.stdout
        assert "함께 쓸 수 없음" in proc.stdout

    def test_neither_map_nor_at_cell_is_a_usage_error(self, tmp_path):
        src = seat_form(tmp_path)
        proc = _cli("replace", src, "--out", tmp_path / "o.hwpx")
        assert proc.returncode == 2, proc.stdout

    def test_ambiguous_cell_exits_2_with_machine_readable_runs(self, tmp_path):
        """다중 런 셀의 거부는 기계 판독 가능해야 한다 — 이 payload만 읽고
        #RUN을 골라야 section XML을 열 이유가 없다."""
        src = seat_form(tmp_path)
        multi = tmp_path / "multi.hwpx"
        xml = section_of(src).replace(
            R(0, "홈페이지"), R(0, "홈") + R(0, "페이지"))
        with zipfile.ZipFile(src) as z, \
                zipfile.ZipFile(multi, "w", zipfile.ZIP_DEFLATED) as w:
            for info in z.infolist():
                data = (xml.encode("utf-8")
                        if info.filename.endswith("section0.xml")
                        else z.read(info.filename))
                w.writestr(info, data)
        out = tmp_path / "o.hwpx"
        proc = _cli("replace", multi, "--out", out, "--at-cell", "0,0=값")
        assert proc.returncode == 2, proc.stdout
        assert not out.exists()
        payload = json.loads(proc.stdout)
        assert payload["code_name"] == "at_cell_run_ambiguous"
        assert payload["addr"] == [0, 0]
        assert [r["text"] for r in payload["runs"]] == ["홈", "페이지"]
        assert payload["suggested_flags"][:2] == ["--at-cell", "0,0#0=<TEXT>"]

    def test_anomaly_refusal_exits_3_with_at_cell_flags(self, tmp_path):
        src = seat_form(tmp_path)
        out = tmp_path / "o.hwpx"
        proc = _cli("replace", src, "--out", out, "--at-cell", "1,1=6개월")
        assert proc.returncode == 3, proc.stdout
        assert not out.exists()
        payload = json.loads(proc.stdout)
        assert payload["code_name"] == "fill_charpr_script_anomaly"
        assert payload["suggested_flags"] == ["--at-cell-charpr", "1,1#0=0"]
        # 그대로 붙여넣으면 통한다
        ok = _cli("replace", src, "--out", out, "--at-cell", "1,1=6개월",
                  *payload["suggested_flags"])
        assert ok.returncode == 0, ok.stdout
        assert json.loads(ok.stdout)["replaced"] == 1

    def test_at_cell_map_accepts_string_and_object_values(self, tmp_path):
        src = seat_form(tmp_path)
        mp = tmp_path / "at.json"
        mp.write_text(json.dumps({
            "0,1": {"text": "host.kr", "mode": "append"},
            "1,1#0": "6개월",
        }, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "o.hwpx"
        proc = _cli("replace", src, "--out", out, "--at-cell-map", mp,
                    "--at-cell-charpr", "1,1#0=0")
        assert proc.returncode == 0, proc.stdout
        result = json.loads(proc.stdout)
        assert result["replaced"] == 2
        modes = {tuple(c["addr"]): c["mode"] for c in result["cells"]}
        assert modes == {(0, 1): "append", (1, 1): "replace"}

    def test_bad_address_spec_is_a_usage_error(self, tmp_path):
        src = seat_form(tmp_path)
        for spec in ("0-1=x", "0,1#x=v", "0,1"):
            proc = _cli("replace", src, "--out", tmp_path / "o.hwpx",
                        "--at-cell", spec)
            assert proc.returncode == 2, (spec, proc.stdout)

    def test_expect_flag_refuses_before_writing(self, tmp_path):
        src = seat_form(tmp_path)
        out = tmp_path / "o.hwpx"
        proc = _cli("replace", src, "--out", out,
                    "--at-cell-append", "0,1=host.kr",
                    "--at-cell-expect", "0,1=협업기간")
        assert proc.returncode == 1, proc.stdout
        assert not out.exists()
        ok = _cli("replace", src, "--out", out,
                  "--at-cell-append", "0,1=host.kr",
                  "--at-cell-expect", "0,1=http://")
        assert ok.returncode == 0, ok.stdout
