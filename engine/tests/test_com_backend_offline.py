"""com_backend offline regressions (W6.2, XC-1 §2/§4) — no COM, no Hancom.

Two mechanism fixes are locked here with pure-Python tests:

1. inspect() picture counting: CtrlID "gso" is the shared id of EVERY drawing
   object (rect/line/textbox included). Counting all gso as pictures reported
   pictures=5 on a document whose 5 gso controls are hp:rect shapes and whose
   XML contains zero hp:pic (kstartup, XC-1 §2). Pictures are now judged by
   UserDesc; other gso controls are counted separately as "shapes".
   (COM-verified 2026-08-07: kstartup pictures 5→0/shapes 5; jumin stays 1.)

2. convert→PDF print-method normalization: a document-stored
   PrintMethod != 0 (settings.xml PrintInfo; e.g. 4 = 2-up 모아찍기) makes
   Hancom SaveAs("PDF") emit print-imposition output — nrf's 4 portrait pages
   became a 2-page landscape 2-up PDF (XC-1 §4). The convert path stages a
   temp copy with PrintMethod normalized to 0 and reports page-count parity.
   (COM-verified 2026-08-07: nrf 2→4 pages, parity 4==4.)
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import com_backend  # noqa: E402


# ---------------------------------------------------------------------------
# inspect(): gso classification
# ---------------------------------------------------------------------------

class _Ctrl:
    def __init__(self, cid, desc, nxt=None):
        self.CtrlID = cid
        self.UserDesc = desc
        self.Next = nxt


class _FakeHwp:
    """Minimal duck-typed Hwp for inspect() — only the attributes it touches."""

    def __init__(self, ctrls):
        head = None
        for cid, desc in reversed(ctrls):
            head = _Ctrl(cid, desc, head)
        self.HeadCtrl = head
        self.PageCount = 1

    def get_text_file(self, fmt, arg):
        return "synthetic body"

    def get_field_list(self):
        return ""


def test_inspect_rect_gso_not_counted_as_picture():
    # kstartup regression: 5 rect shapes + 1 table, zero real pictures.
    hwp = _FakeHwp([("tbl", "표")] + [("gso", "사각형")] * 5)
    info = com_backend.inspect(hwp)
    assert info["tables"] == 1
    assert info["pictures"] == 0
    assert info["shapes"] == 5


def test_inspect_real_picture_still_counted():
    hwp = _FakeHwp([("gso", "그림"), ("gso", "글상자"), ("tbl", "표")])
    info = com_backend.inspect(hwp)
    assert info["pictures"] == 1
    assert info["shapes"] == 1
    assert info["tables"] == 1


# ---------------------------------------------------------------------------
# convert→PDF helpers: print-method normalization + page parity plumbing
# ---------------------------------------------------------------------------

SETTINGS_2UP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<ha:HWPApplicationSetting xmlns:ha="x" xmlns:config="c">'
    '<config:config-item-set name="PrintInfo">'
    '<config:config-item name="PrintMethod" type="short">4</config:config-item>'
    '<config:config-item name="ZoomX" type="short">100</config:config-item>'
    "</config:config-item-set></ha:HWPApplicationSetting>"
)


def _write_hwpx(path, settings=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", "<hh:head/>")
        z.writestr("Contents/section0.xml", "<hs:sec/>")
        if settings is not None:
            z.writestr("settings.xml", settings)
    return str(path)


def test_stage_normalizes_nonzero_print_method(tmp_path):
    src = _write_hwpx(tmp_path / "form.hwpx", settings=SETTINGS_2UP)
    staged, original = com_backend._stage_print_normalized_hwpx(src, tmp_path)
    assert original == 4
    assert staged is not None and staged != src
    with zipfile.ZipFile(staged) as z:
        settings = z.read("settings.xml").decode("utf-8")
        assert 'name="PrintMethod" type="short">0<' in settings
        assert 'name="ZoomX" type="short">100<' in settings  # untouched
        # all other members carried over byte-identically
        assert z.read("Contents/section0.xml") == b"<hs:sec/>"
        assert z.read("mimetype") == b"application/hwp+zip"
    # source untouched
    with zipfile.ZipFile(src) as z:
        assert 'type="short">4<' in z.read("settings.xml").decode("utf-8")


def test_stage_noop_when_print_method_already_normal(tmp_path):
    src = _write_hwpx(
        tmp_path / "form.hwpx",
        settings=SETTINGS_2UP.replace('type="short">4<', 'type="short">0<'))
    assert com_backend._stage_print_normalized_hwpx(src, tmp_path) == (None, None)


def test_stage_noop_without_settings_or_on_non_zip(tmp_path):
    src = _write_hwpx(tmp_path / "form.hwpx", settings=None)
    assert com_backend._stage_print_normalized_hwpx(src, tmp_path) == (None, None)
    hwp = tmp_path / "legacy.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0 not a zip")
    assert com_backend._stage_print_normalized_hwpx(hwp, tmp_path) == (None, None)


def test_pdf_page_count_counts_and_fails_closed(tmp_path):
    fitz = __import__("pytest").importorskip("fitz")
    pdf = tmp_path / "two.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()
    assert com_backend._pdf_page_count(pdf) == 2
    assert com_backend._pdf_page_count(tmp_path / "missing.pdf") is None


# ---------------------------------------------------------------------------
# 3. set_cell 주소 체계 (T28) — row/col은 cellAddr이 아니라 키 입력 횟수였다
#
# TableRightCell은 행 끝에서 다음 행으로 넘어가고 TableLowerCell은 rowSpan을
# 건너뛴다. 그래서 왼쪽 열에 rowspan 라벨이 있는 양식(= 정부 양식의 표준형)에서
# 옛 해석은 전혀 다른 셀을 가리켰다. 첫 클린룸 교차모델 런에서 두 에이전트
# 모두 첫 시도에 라벨 셀을 파괴했다. 아래 격자는 PPS 협업승인신청서
# (tests/corpus/forms/grant/pps-hyeopeop-seungin-sinchengseo.hwpx) 표 0의
# 실측 기하를 축약 재현한 것이다 — cellAddr (2,3)을 노린 옛 키 입력은
# (2,6) '법인등록번호' 라벨 셀에 도착한다.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


class _GridCursor:
    """한글 표 커서의 오프라인 모형 — cells: {(row,col): (rowSpan,colSpan,text)}.

    right(): 셀 주소의 행우선 순서로 한 칸(마지막에서 첫 칸으로 wrap) —
             TableRightCell의 줄바꿈 이동.
    down():  현재 셀의 아래(현재 rowSpan을 넘은 좌표)를 덮는 셀 —
             TableLowerCell이 rowSpan을 건너뛰는 동작.
    """

    def __init__(self, cells, start=None):
        self.cells = dict(cells)
        self.order = sorted(self.cells)
        self.pos = start if start is not None else self.order[0]
        self.moves = 0

    def addr(self):
        return self.pos

    def text(self):
        return self.cells[self.pos][2]

    def right(self):
        self.moves += 1
        self.pos = self.order[(self.order.index(self.pos) + 1) % len(self.order)]

    def down(self):
        self.moves += 1
        row, col = self.pos
        below = row + self.cells[self.pos][0]
        for (r, c), (rs, cs, _t) in self.cells.items():
            if r <= below < r + rs and c <= col < c + cs:
                self.pos = (r, c)
                return
        # 마지막 행에서는 움직이지 않는다(한글 동작)


# PPS 표 0의 상단 블록(실측): 왼쪽 열은 rowSpan 라벨, (2,3)은 colSpan 3.
PPS_HEAD = {
    (0, 0): (1, 9, "협업 승인 신청서"),
    (1, 0): (1, 9, ""),
    (2, 0): (5, 2, "협업 추진기업(신 청 기 업)"),
    (2, 2): (2, 1, "기 업 명"),
    (2, 3): (2, 3, ""),
    (2, 6): (1, 1, "법인등록번호"),
    (2, 7): (1, 2, ""),
    (3, 6): (1, 1, "사업자등록번호"),
    (3, 7): (1, 2, ""),
    (4, 2): (1, 1, "주    소"),
    (4, 3): (1, 6, "우(     -     )"),
}


def test_parse_cell_addr_excel_style():
    assert com_backend.parse_cell_addr("A1") == (0, 0)
    assert com_backend.parse_cell_addr("D3") == (2, 3)
    assert com_backend.parse_cell_addr("(B2)") == (1, 1)
    assert com_backend.parse_cell_addr("AA1") == (0, 26)


def test_parse_cell_addr_refuses_to_guess():
    """모르는 형태를 추측하면 곧바로 엉뚱한 셀 덮어쓰기다 — 소리나게 죽는다."""
    with pytest.raises(ValueError):
        com_backend.parse_cell_addr("")
    with pytest.raises(ValueError):
        com_backend.parse_cell_addr("1A")
    with pytest.raises(ValueError, match="tuple/list"):
        com_backend.parse_cell_addr((2, 3))


def test_legacy_keypress_counts_land_on_the_label_cell():
    """failing-before(D3 재현): (2,3)을 노린 옛 row/col이 라벨 셀을 덮어쓴다."""
    cursor = _GridCursor(PPS_HEAD)
    landed = com_backend.legacy_traversal_addr(cursor, 2, 3)
    assert landed == (2, 6)
    assert cursor.text() == "법인등록번호"


def test_celladdr_walk_reaches_the_intended_cell():
    cursor = _GridCursor(PPS_HEAD)
    steps, _visited = com_backend.walk_to_cell_addr(cursor, (2, 3))
    assert cursor.addr() == (2, 3)
    assert cursor.text() == ""
    assert steps == 4  # (0,0)->(1,0)->(2,0)->(2,2)->(2,3)


def test_celladdr_walk_is_immune_to_entry_drift():
    """nth-table drift(실측): get_into_nth_table 진입 셀이 흔들려도 목적지 동일.

    TableRightCell은 마지막 셀에서 첫 셀로 감기므로 어느 셀에서 출발해도
    같은 주소에 닿는다 — 그래서 진입점을 (0,0)으로 가정하지 않는다."""
    for start in [(0, 0), (3, 6), (4, 3)]:
        cursor = _GridCursor(PPS_HEAD, start=start)
        com_backend.walk_to_cell_addr(cursor, (2, 7))
        assert cursor.addr() == (2, 7)


def test_walk_refuses_a_coordinate_covered_by_a_merge():
    """(3,0)은 rowSpan 5짜리 라벨이 덮은 좌표 — 셀이 없다. 쓰지 않고 죽는다."""
    cursor = _GridCursor(PPS_HEAD)
    with pytest.raises(RuntimeError, match="한 바퀴"):
        com_backend.walk_to_cell_addr(cursor, (3, 0))


def test_walk_aborts_when_the_cursor_does_not_move():
    class _Stuck:
        def addr(self):
            return (0, 0)

        def right(self):
            pass

    with pytest.raises(RuntimeError, match="진행되지 않음"):
        com_backend.walk_to_cell_addr(_Stuck(), (5, 5))


# ---------------------------------------------------------------------------
# set_cell op — 스키마 검증 + 선행조건 가드
# ---------------------------------------------------------------------------

class _FakeCellHwp:
    """op_set_cell이 실제로 만지는 표면만 갖춘 가짜 한글."""

    def __init__(self, cells, entry=None):
        self.cursor = _GridCursor(cells, start=entry)
        self.written = []
        self.deleted = []

    # 표 진입/이동
    def get_into_nth_table(self, n):
        self.table = n

    def get_cell_addr(self):
        row, col = self.cursor.addr()
        return f"{chr(ord('A') + col)}{row + 1}"

    def TableRightCell(self):
        self.cursor.right()

    def TableLowerCell(self):
        self.cursor.down()

    # 내용 읽기/쓰기
    def get_cell_text(self):
        return self.cursor.text()

    def SelectAll(self):
        pass

    def Delete(self):
        self.deleted.append(self.cursor.addr())

    def insert_text(self, text):
        self.written.append((self.cursor.addr(), text))

    def MoveDocEnd(self):
        pass


def test_op_set_cell_writes_to_the_celladdr_target():
    hwp = _FakeCellHwp(PPS_HEAD)
    result = com_backend.op_set_cell(
        hwp, {"op": "set_cell", "table": 0, "addr": [2, 3],
              "text": "주식회사 리고룸", "expect_empty": True})
    assert hwp.written == [((2, 3), "주식회사 리고룸")]
    assert result["cell"] == [0, [2, 3]]
    assert result["mode"].startswith("cellAddr")


def test_op_set_cell_expect_empty_refuses_a_label_cell():
    """선행조건 가드: 내용이 어긋나면 Delete/insert 전에 죽는다."""
    hwp = _FakeCellHwp(PPS_HEAD)
    with pytest.raises(RuntimeError, match="비어 있지 않음"):
        com_backend.op_set_cell(
            hwp, {"op": "set_cell", "addr": [2, 6], "text": "파괴",
                  "expect_empty": True})
    assert hwp.written == [] and hwp.deleted == []


def test_op_set_cell_expect_text_must_match():
    hwp = _FakeCellHwp(PPS_HEAD)
    with pytest.raises(RuntimeError, match="기대와 다름"):
        com_backend.op_set_cell(
            hwp, {"op": "set_cell", "addr": [2, 6], "text": "새 라벨",
                  "expect": "기 업 명"})
    assert hwp.written == []
    ok = com_backend.op_set_cell(
        hwp, {"op": "set_cell", "addr": [2, 6], "text": "새 라벨",
              "expect": "법인등록번호"})
    assert hwp.written == [((2, 6), "새 라벨")]
    assert ok["previous"] == "법인등록번호"


def test_op_set_cell_legacy_mode_is_opt_in_and_documented():
    """레거시 모드는 명시해야만 열린다 — 옛 배치 재현용."""
    hwp = _FakeCellHwp(PPS_HEAD)
    result = com_backend.op_set_cell(
        hwp, {"op": "set_cell", "row": 2, "col": 3, "text": "값",
              "raw_traversal": True})
    assert result["mode"] == "raw_traversal"
    assert hwp.written == [((2, 6), "값")]   # 옛 동작 그대로(= 라벨 셀)
    assert "cellAddr이 **아니다**" in com_backend.legacy_traversal_addr.__doc__


def test_op_set_cell_requires_addr_without_legacy_flag():
    hwp = _FakeCellHwp(PPS_HEAD)
    with pytest.raises(RuntimeError, match="addr"):
        com_backend.op_set_cell(hwp, {"op": "set_cell", "row": 2, "col": 3,
                                      "text": "값"})
    assert hwp.written == []


def test_validate_ops_rejects_bare_row_col(monkeypatch):
    calls = []

    def _fake_die(msg, code=2):
        calls.append(msg)
        raise SystemExit(code)

    monkeypatch.setattr(com_backend, "_die", _fake_die)
    with pytest.raises(SystemExit):
        com_backend._validate_ops(
            [{"op": "set_cell", "table": 0, "row": 1, "col": 2, "text": "값"}])
    assert "T28" in calls[0]


def test_validate_ops_accepts_addr_form(monkeypatch):
    monkeypatch.setattr(com_backend, "_die",
                        lambda msg, code=2: (_ for _ in ()).throw(SystemExit(code)))
    ops = com_backend._validate_ops(
        [{"op": "set_cell", "table": 0, "addr": [2, 3], "text": "값",
          "expect_empty": True}])
    assert ops[0]["addr"] == [2, 3]


def test_validate_ops_rejects_malformed_addr_and_double_guard(monkeypatch):
    monkeypatch.setattr(com_backend, "_die",
                        lambda msg, code=2: (_ for _ in ()).throw(SystemExit(code)))
    for bad in ([{"op": "set_cell", "addr": "2,3", "text": "v"}],
                [{"op": "set_cell", "addr": [2], "text": "v"}],
                [{"op": "set_cell", "addr": [-1, 0], "text": "v"}],
                [{"op": "set_cell", "addr": [0, 0], "text": "v",
                  "expect_empty": True, "expect": "x"}]):
        with pytest.raises(SystemExit):
            com_backend._validate_ops(bad)


# ---------------------------------------------------------------------------
# 실사격(COM) 검증 — 한컴이 있는 기계에서만, 직렬로. 없으면 사유와 함께 skip.
# ---------------------------------------------------------------------------

PPS_FORM = os.path.join(
    os.path.dirname(ROOT), "tests", "corpus", "forms", "grant",
    "pps-hyeopeop-seungin-sinchengseo.hwpx")


def test_real_form_geometry_reproduces_the_defect():
    """실제 양식 기하로 D3 재현 — COM 없이 오프라인으로도 증거가 남는다."""
    if not os.path.exists(PPS_FORM):
        import pytest as _pytest
        _pytest.skip("corpus form not present")
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from hwpx_tables import scan_tables
    with zipfile.ZipFile(PPS_FORM) as z:
        xml = z.read("Contents/section0.xml").decode("utf-8")
    table = scan_tables(xml)[0]
    cells = {}
    for cell in table["cells"]:
        body = xml[cell["body_start"]:cell["body_end"]]
        text = re.sub(r"<[^>]+>", "", "".join(
            re.findall(r"<hp:t\b[^>]*>(.*?)</hp:t>", body, re.S))).strip()
        cells[cell["addr"]] = (cell["span"][0], cell["span"][1], text)
    cursor = _GridCursor(cells)
    assert com_backend.legacy_traversal_addr(cursor, 2, 3) == (2, 6)
    assert cursor.text() == "법인등록번호"      # 두 에이전트가 파괴한 그 셀
    cursor = _GridCursor(cells)
    com_backend.walk_to_cell_addr(cursor, (2, 3))
    assert cursor.addr() == (2, 3) and cursor.text() == ""
