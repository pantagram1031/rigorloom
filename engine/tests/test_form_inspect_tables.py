# -*- coding: utf-8 -*-
"""table_map 표/셀 색인 회귀 — 중첩 표 (T27 addressing contract).

`preedit fill-cells --table N` 은 `form_inspect` table_map이 보고하는 색인과
주소를 그대로 받는다. 두 도구가 다른 스캐너를 쓰면 `--table N` 은 조용히
엉뚱한 표를 가리키는 함정이 되므로, 여기서 **같은 스캐너를 쓴다**는 사실
자체를 고정한다.

failing-before: table_map은 비탐욕 `<hp:tbl>(.*?)</hp:tbl>` 로 표를 잘랐다.
표는 중첩된다(코퍼스 12개 양식 중 6개, 깊이 2) — 바깥 표의 여는 태그가 안쪽
표의 닫는 태그와 짝지어져 (a) 바깥 표 몸통에 안쪽 셀이 섞이고 (b) 안쪽 표
뒤에 오는 바깥 셀이 통째로 사라졌다. gianmun-byeolji-1ho 실측: 표 3→2,
셀 34→6.

T34(3라운드): 여기에 seat-text 계약도 함께 고정한다 — `text_preview`의
`truncated` 플래그, `--full-text`의 셀 단위 opt-in, 그리고 --full-text가 준
문자열이 `replace` 키로 정확히 한 번 맞는 **왕복**. 두 클린룸 티어가 이 구멍
때문에 독립적으로 Contents/section0.xml을 손으로 읽었다.

픽스처는 커밋된 코퍼스 양식(tests/corpus/forms/) — 없으면 skip.
"""
import json
import os
import re
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402
import preedit  # noqa: E402
from hwpx_tables import find_cell, scan_tables  # noqa: E402

CORPUS = os.path.join(os.path.dirname(ROOT), "tests", "corpus", "forms")
NESTED_FORM = os.path.join(CORPUS, "converted", "gianmun-byeolji-1ho.hwpx")
PPS_FORM = os.path.join(CORPUS, "grant",
                        "pps-hyeopeop-seungin-sinchengseo.hwpx")

SECTION_RE = re.compile(r"Contents/section\d+\.xml")


def _sections(path):
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if SECTION_RE.fullmatch(n)):
            yield name, z.read(name).decode("utf-8")


def _naive_tables(path):
    """옛 비탐욕 정규식 그대로 — failing-before를 이 파일 안에서 재현한다."""
    ns = r"[A-Za-z0-9]+"
    tables = 0
    cells = 0
    for _name, xml in _sections(path):
        for m in re.finditer(r"<" + ns + r":tbl\b([^>]*)>(.*?)</" + ns
                             + r":tbl>", xml, re.S):
            tables += 1
            cells += len(re.findall(r"<" + ns + r":tc\b[^>]*>", m.group(2)))
    return tables, cells


@pytest.mark.skipif(not os.path.exists(NESTED_FORM), reason="corpus absent")
def test_nested_tables_are_counted_separately():
    naive_tables, naive_cells = _naive_tables(NESTED_FORM)
    assert (naive_tables, naive_cells) == (2, 6)      # failing-before

    profile, _ = form_inspect.analyze(NESTED_FORM, want_baseline=False)
    tables = profile["table_map"]
    assert len(tables) == 3
    assert sum(len(t["cells"]) for t in tables) == 34
    # 바깥 표가 먼저, 중첩 표는 자기 색인과 depth를 갖는다
    assert [t["index"] for t in tables] == [0, 1, 2]
    assert max(t["depth"] for t in tables) == 1


@pytest.mark.skipif(not os.path.exists(NESTED_FORM), reason="corpus absent")
def test_table_map_index_matches_the_shared_scanner():
    """fill-cells가 쓰는 스캐너와 table_map의 색인·주소가 1:1이어야 한다."""
    profile, _ = form_inspect.analyze(NESTED_FORM, want_baseline=False)
    scanned = []
    for _name, xml in _sections(NESTED_FORM):
        for table in scan_tables(xml):
            scanned.append([c["addr"] for c in table["cells"]])
    assert len(scanned) == len(profile["table_map"])
    for entry, addrs in zip(profile["table_map"], scanned):
        mapped = [(c["addr"]["row"], c["addr"]["col"]) if c["addr"] else None
                  for c in entry["cells"]]
        assert mapped == addrs


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_pps_empty_fill_targets_have_no_text_element():
    """T27의 근거를 코퍼스에 고정: 빈 fill_target 셀에는 hp:t가 아예 없다.

    그래서 텍스트 키 기반의 `preedit replace`로는 구조적으로 도달할 수 없다 —
    `preedit fill-cells`가 있어야 하는 이유."""
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    table = profile["table_map"][0]
    # 빈 칸은 19개 그대로다. 그 중 6개는 격자용 spacer로 내려갔고(Q2),
    # 채우기 대상은 13개 — T27의 "hp:t가 없다"는 성질은 둘 다에 해당한다.
    targets = [c for c in table["cells"]
               if c["classification"] in ("fill_target", "spacer")]
    assert len(targets) == 19
    assert profile["fill_target_count"] == 13
    assert len(profile["spacer_cells"]) == 6

    _name, xml = next(iter(_sections(PPS_FORM)))
    scanned = scan_tables(xml)[0]
    for cell in targets:
        addr = (cell["addr"]["row"], cell["addr"]["col"])
        found = find_cell(scanned, *addr)
        body = xml[found["body_start"]:found["body_end"]]
        assert "<hp:t" not in body, f"{addr} 에 hp:t 가 있다"
        assert re.search(r"<hp:run\b[^>]*/>", body), f"{addr} 자기닫힘 런 없음"


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_merged_cells_report_their_span():
    """병합 정보가 프로파일에 나와야 주소가 왜 불연속인지 읽을 수 있다."""
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    by_addr = {(c["addr"]["row"], c["addr"]["col"]): c
               for c in profile["table_map"][0]["cells"] if c["addr"]}
    assert by_addr[(2, 0)]["span"] == {"row": 5, "col": 2}
    assert by_addr[(2, 3)]["span"] == {"row": 2, "col": 3}
    assert (3, 0) not in by_addr        # rowSpan이 덮은 좌표에는 셀이 없다


# ---------------------------------------------------------------------------
# T34 — 잘림은 말해야 하고, 정확한 문자열에는 이름 붙인 통로가 있어야 한다
#
# failing-before(3라운드 클린룸, 두 티어 독립 적중): `preedit replace` 의
# 문자열 키는 런의 내부 공백까지 정확해야 하는데,
#   · table_map.text_preview 는 text[:30] 이고 **잘림 표시가 없었다**,
#   · 자리표 스켈레톤은 30자를 넘고 anchors에도 없다,
#   · content_extract 는 공백을 접는다.
# 그래서 Sonnet 티어는 협업기간 스켈레톤 중간의 "(     개월)" 빈칸을 아예 못
# 보고 치환을 한 번 더 돌려야 했고, Opus 티어는 Contents/section0.xml을 손으로
# 읽어 키 두 개를 조립했다 — 배포된 스킬이 금지한 접촉.
# ---------------------------------------------------------------------------

PPS_SEATS = {
    (4, 3): " 우(     -     )",
    (5, 3): " http://",
    (11, 2): "20   .    .    .  ~  20   .    .    .   (     개월)",
}


def _geometry_skeleton(xml):
    """텍스트 내용과 캐시 레이아웃을 뺀 XML — 표/셀 기하만 남는다."""
    return preedit.T_FULL_RE.sub(
        lambda m: m.group(1) + m.group(3), preedit.LINESEG_RE.sub("", xml))


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_truncation_flag_is_present_exactly_when_text_was_cut():
    """`truncated` 는 30자 초과일 때만 True.

    독립 계산과 대조한다 — 같은 셀의 정확한 전문을 --full-text로 따로 뽑아
    길이를 비교하므로, text[:30] 로직을 그대로 베껴 쓴 자기충족 검사가 아니다.
    """
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    addrs = [(t["index"], c["addr"]["row"], c["addr"]["col"])
             for t in profile["table_map"] for c in t["cells"] if c["addr"]]
    full, _ = form_inspect.analyze(PPS_FORM, full_text=addrs)
    exact = {(e["table"], e["addr"]["row"], e["addr"]["col"]): e["text"]
             for e in full["full_text"]}

    cut = 0
    for table in profile["table_map"]:
        for cell in table["cells"]:
            assert "truncated" in cell            # 항상 말한다
            if not cell["addr"]:
                continue
            key = (table["index"], cell["addr"]["row"], cell["addr"]["col"])
            assert cell["truncated"] == (len(exact[key]) > 30), key
            assert cell["text_preview"] == exact[key][:30], key
            cut += bool(cell["truncated"])
    assert cut >= 1                               # 비어 있지 않은 대조

    by_addr = {(c["addr"]["row"], c["addr"]["col"]): c
               for c in profile["table_map"][0]["cells"] if c["addr"]}
    period = by_addr[(11, 2)]
    assert period["truncated"] is True
    # failing-before: 이 preview만 보고는 "(     개월)" 빈칸이 있는 줄 모른다
    assert period["text_preview"] == "20   .    .    .  ~  20   .   "
    assert "개월" not in period["text_preview"]
    assert by_addr[(5, 3)]["truncated"] is False       # " http://" 는 8자


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_full_text_is_opt_in_and_cell_scoped():
    """구조-전용 계약의 탈출구는 셀 단위 opt-in 이다 — 요청이 없으면 키 자체가
    없고, 요청한 셀 밖의 텍스트는 한 글자도 나오지 않는다."""
    plain, _ = form_inspect.analyze(PPS_FORM)
    assert "full_text" not in plain

    profile, _ = form_inspect.analyze(PPS_FORM, full_text=[(None, 11, 2)])
    assert [e["addr"] for e in profile["full_text"]] \
        == [{"row": 11, "col": 2}]
    entry = profile["full_text"][0]
    assert entry["text"] == PPS_SEATS[(11, 2)]
    assert entry["truncated_preview"] is True
    assert [r["index"] for r in entry["runs"]] == [0]
    # 다른 셀(홈페이지)의 자리표는 나오지 않는다
    assert PPS_SEATS[(5, 3)] not in json.dumps(profile["full_text"],
                                               ensure_ascii=False)


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_full_text_round_trips_into_a_string_keyed_replace(tmp_path):
    """구멍이 닫혔다는 증명: --full-text가 준 문자열을 그대로 `replace`의 키로
    쓰면 정확히 한 번 맞는다. 그 문자열을 얻으려고 section XML을 열 필요가
    없다 — 이것이 T34의 왕복 계약이다."""
    wanted = [(None, r, c) for (r, c) in sorted(PPS_SEATS)]
    wanted.append((None, 15, 0))       # 다중 런 셀(신청일 줄 포함)
    profile, _ = form_inspect.analyze(PPS_FORM, full_text=wanted)

    seen = 0
    for entry in profile["full_text"]:
        addr = (entry["addr"]["row"], entry["addr"]["col"])
        if addr in PPS_SEATS:
            assert entry["text"] == PPS_SEATS[addr]
        for run in entry["runs"]:
            if not run["text"].strip():
                continue           # 공백뿐인 런은 치환 대상이 아니다
            out = tmp_path / f"rt-{addr[0]}-{addr[1]}-{run['index']}.hwpx"
            result = preedit.replace_placeholders(
                PPS_FORM, out, {run["text"]: "VALUE"})
            assert result["hits"][run["text"]] == 1, (addr, run["index"])
            seen += 1
    assert seen >= 8               # 네 셀에서 실제로 왕복한 런의 수


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_full_text_run_indices_are_the_at_cell_run_indices(tmp_path):
    """--full-text 의 runs[].index 는 `replace --at-cell ROW,COL#RUN` 이
    편집하는 런과 같은 열거여야 한다(같은 함수를 쓴다는 사실을 고정)."""
    profile, _ = form_inspect.analyze(PPS_FORM, full_text=[(None, 15, 0)])
    runs = profile["full_text"][0]["runs"]
    date_run = next(r for r in runs if "년" in r["text"] and "월" in r["text"])
    out = tmp_path / "dated.hwpx"
    result = preedit.replace_at_cells(
        PPS_FORM, out, [(15, 0, date_run["index"], "2026 년 3 월 1 일",
                         "replace")])
    assert result["cells"][0]["before"] == date_run["text"]
    assert result["cells"][0]["run"] == date_run["index"]


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_at_cell_edits_every_pps_seat_without_a_string_key(tmp_path):
    """실물 네 자리표(협업기간·우편번호·http·신청일)를 한 호출에 — 정확한
    문자열 키 없이 주소만으로. 기하는 바이트 동일이어야 한다."""
    out = tmp_path / "filled.hwpx"
    result = preedit.replace_at_cells(PPS_FORM, out, [
        (11, 2, None, "2026. 3. 1. ~ 2026. 8. 31. (6개월)", "replace"),
        (4, 3, None, "서울특별시 강남구 …", "append"),
        (5, 3, None, "hanbit.example.kr", "append"),
        (15, 0, 2, "                    2026 년   3 월   1 일", "replace"),
    ], expects={(11, 2, None): "개월", (4, 3, None): "우(-)",
                (5, 3, None): "http://", (15, 0, 2): "년월일"})
    assert result["replaced"] == 4
    before = {tuple(c["addr"]): c["before"] for c in result["cells"]}
    for addr, seat in PPS_SEATS.items():
        assert before[addr] == seat

    _n, src_xml = next(iter(_sections(PPS_FORM)))
    _n2, out_xml = next(iter(_sections(out)))
    assert _geometry_skeleton(out_xml) == _geometry_skeleton(src_xml)
    src_cells = scan_tables(src_xml)[0]["cells"]
    out_cells = scan_tables(out_xml)[0]["cells"]
    assert [(c["addr"], c["span"], c["attrs"]) for c in src_cells] \
        == [(c["addr"], c["span"], c["attrs"]) for c in out_cells]
    # 값이 실제로 들어갔고, 접두 보존/교체가 모드대로다
    assert " 우(     -     )서울특별시 강남구 …" in out_xml
    assert " http://hanbit.example.kr" in out_xml
    assert PPS_SEATS[(11, 2)] not in out_xml


# ---------------------------------------------------------------------------
# Q2 — 구조용 빈 칸(spacer)은 채우기 대상이 아니다
#
# failing-before: PPS 양식의 (1,0)/(9,0)/(12,0)/(13,0)/(16,0)/(18,0) 여섯 칸이
# fill_target으로 잡혀서, Codex 하네스와 3라운드 Opus 런이 **각자** "이건 칸이
# 아니다"를 추론으로 걷어내야 했다. 분류가 할 일을 독자에게 떠넘긴 것이다.
# 판정 근거는 표 자신의 기하다 — 주소 목록이 아니다.
# ---------------------------------------------------------------------------

PPS_SPACERS = {(1, 0), (9, 0), (12, 0), (13, 0), (16, 0), (18, 0)}


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_pps_structural_spacers_are_not_fill_targets():
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    cells = profile["table_map"][0]["cells"]
    spacers = {(c["addr"]["row"], c["addr"]["col"]) for c in cells
               if c["classification"] == "spacer"}
    assert spacers == PPS_SPACERS
    fills = {(c["addr"]["row"], c["addr"]["col"]) for c in cells
             if c["classification"] == "fill_target"}
    assert not (fills & PPS_SPACERS)
    assert profile["fill_target_count"] == len(fills) == 13
    # 자기 부류로 보고된다 — 조용히 사라지지 않는다.
    reported = {(s["addr"]["row"], s["addr"]["col"]): s["pattern"]
                for s in profile["spacer_cells"]}
    assert set(reported) == PPS_SPACERS
    assert reported[(13, 0)] == "stub_head"          # 행렬 모서리
    assert reported[(1, 0)] == "full_width_band"     # 구분 띠
    # spacer에는 T30 사전 점검 필드가 붙지 않는다(채울 일이 없으므로).
    assert all("charpr_suggested" not in c for c in cells
               if c["classification"] == "spacer")


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_labelled_empty_cell_stays_a_fill_target():
    """still-catches: 라벨 이웃이 있는 진짜 빈 칸은 그대로 fill_target.

    PPS (2,7)은 (2,6) `법인등록번호` 바로 오른쪽의 빈 칸이다 — 비어 있고,
    행 전체가 얇지도 않고, 라벨이 이름을 붙여 준다."""
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    by_addr = {(c["addr"]["row"], c["addr"]["col"]): c
               for c in profile["table_map"][0]["cells"] if c["addr"]}
    assert by_addr[(2, 6)]["text_preview"].strip() == "법인등록번호"
    target = by_addr[(2, 7)]
    assert target["text_preview"] == ""
    assert target["classification"] == "fill_target"
    assert "charpr_suggested" in target      # 사전 점검 필드는 살아 있다


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus absent")
def test_spacer_criterion_is_geometric_not_addressed():
    """기준이 주소가 아니라 기하라는 것 자체를 고정한다.

    같은 표에서 라벨 이웃을 하나 심어 주면 그 칸은 다시 fill_target이 되고,
    반대로 격자의 filler 기하가 없으면 라벨이 없어도 spacer가 아니다."""
    profile, _ = form_inspect.analyze(PPS_FORM, want_baseline=False)
    cells = [dict(c) for c in profile["table_map"][0]["cells"]]
    col_cnt = profile["table_map"][0]["colCnt"]

    # (18,0)은 지금 full_width_band spacer다.
    fresh = [dict(c, classification=("fill_target"
                                     if c["classification"] == "spacer"
                                     else c["classification"]))
             for c in cells]
    marked = form_inspect._mark_spacers(fresh, col_cnt)
    assert (18, 0) in {(c["addr"]["row"], c["addr"]["col"]) for c in marked}

    # 같은 칸을 본문 행 높이로 키우면(= 한 줄이 들어가는 기하) 더 이상
    # filler가 아니고, 주소가 같아도 spacer로 내려가지 않는다.
    taller = [dict(c, classification=("fill_target"
                                      if c["classification"] == "spacer"
                                      else c["classification"]))
              for c in cells]
    for cell in taller:
        if (cell["addr"]["row"], cell["addr"]["col"]) == (18, 0):
            cell["height"] = 99999
    marked2 = form_inspect._mark_spacers(taller, col_cnt)
    assert (18, 0) not in {(c["addr"]["row"], c["addr"]["col"])
                           for c in marked2}
