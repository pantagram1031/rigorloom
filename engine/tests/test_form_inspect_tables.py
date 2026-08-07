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

픽스처는 커밋된 코퍼스 양식(tests/corpus/forms/) — 없으면 skip.
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
    targets = [c for c in table["cells"]
               if c["classification"] == "fill_target"]
    assert len(targets) == 19

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
