# -*- coding: utf-8 -*-
"""The fake rt_doc's own choices, where doc-core-api.md leaves room.

tests/test_rt_doc_contract.py holds what the fake and the real rt_doc share;
this file pins what the layer above may rely on *from the fake* in its tests:
the .fdoc format, base-snapshot op resolution, error details, signals, and the
helper outputs (render, convert, new, diff, guard, style).
"""
from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
import zlib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "runtime" / "scripts"))

import _fake_rt_doc as fake  # noqa: E402
import rt_codes  # noqa: E402
import rt_guard  # noqa: E402

DOC = """# 개요

첫 문단은 2026년에 쓴다.
같은 문단의 둘째 줄.

## 배경

배경 문단에 대해 적는다.

| 항목 | 값 |
|---|---|
| 가 | 1 |
| 나 | 2 |

### 맺는 제목

---page---

[[place:name|성명]]

[[place:sign|서명|signature]]홍길동

## 배경 설명

끝 문단.
"""


@pytest.fixture(autouse=True)
def _contained(tmp_path: Path, monkeypatch):
    """Relative outs and the fake's temp dirs (preview, render without out_dir) stay in tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    p = tmp_path / "a.fdoc"
    p.write_text(DOC, encoding="utf-8")
    return p


def rev(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def text(path: Path, at: str) -> str:
    res = fake.read(path, at)
    assert res["ok"], res
    return res["blocks"][0]["text"]


def edit(path: Path, ops, out: Path, **kw) -> dict:
    return fake.edit(path, ops, base=rev(path), out=str(out), **kw)


# --------------------------------------------------------------------------- format
def test_fdoc_structure_and_addresses(doc):
    o = fake.outline(doc)
    assert [(h["at"], h["level"], h["text"], h["page"]) for h in o["headings"]] == [
        ("p0", 1, "개요", 1), ("p2", 2, "배경", 1), ("p4", 3, "맺는 제목", 1), ("p7", 2, "배경 설명", 2)]
    assert o["tables"] == [{"at": "t0", "rows": 3, "cols": 2, "page": 1}]
    assert o["places"] == [
        {"id": "name", "at": "p5", "label": "성명", "kind": "text", "page": 2,
         "value": "", "filled": False},
        {"id": "sign", "at": "p6", "label": "서명", "kind": "signature", "page": 2,
         "value": "홍길동", "filled": True}]
    assert text(doc, "p1") == "첫 문단은 2026년에 쓴다.\n같은 문단의 둘째 줄."
    assert text(doc, "t0/r0/c0") == "항목"          # the header row is row 0
    assert text(doc, "t0/r2/c1/p0") == "2"
    assert text(doc, "place:name") == "" and text(doc, "place:sign") == "홍길동"
    assert [b["kind"] for b in fake.read(doc)["blocks"]] == [
        "heading", "para", "heading", "para", "table", "heading", "place", "place", "heading", "para"]


def test_heading_address_exact_then_unique_prefix(doc):
    assert fake.read(doc, 'h:"배경"')["blocks"][0]["at"] == "p2"       # exact wins over prefix
    assert fake.read(doc, 'h:"맺는"')["blocks"][0]["at"] == "p4"       # unique prefix
    assert fake.read(doc, "h:개요")["blocks"][0]["at"] == "p0"         # quotes optional
    err = fake.read(doc, 'h:"배"')["error"]                           # shared prefix
    assert err["code"] == "bad_address" and err["candidates"] == ["p2", "p7"]
    err = fake.read(doc, 'h:"없는"')["error"]
    assert err["code"] == "bad_address" and len(err["candidates"]) <= 5
    assert set(err["candidates"]) <= {"개요", "배경", "맺는 제목", "배경 설명"}


def test_bad_address_candidates_are_nearest_and_at_most_five(doc):
    err = fake.read(doc, "p42")["error"]
    assert err == {"code": "bad_address", "message": err["message"], "at": "p42",
                   "candidates": ["p4", "p5", "p6", "p7", "p8"], "retryable": False}
    assert fake.read(doc, "t0/r9/c0")["error"]["candidates"][0] == "t0/r2/c0"
    assert fake.read(doc, "place:nam")["error"]["candidates"][0] == "name"
    assert fake.read(doc, "page:1")["error"]["code"] == "bad_address"


@pytest.mark.parametrize("value", [
    "# 제목 아님", "| 표 아님 |", "[[place:x|y]]", "---page---", "{style=굵게}", "\\역슬래시",
    "", "  ", "줄 하나\n\n빈 줄 뒤", "  들여쓴 줄"])
def test_text_that_looks_like_markup_round_trips(doc, tmp_path, value):
    out = tmp_path / "b.fdoc"
    res = edit(doc, [{"op": "set", "at": "p3", "text": value}], out)
    assert res["ok"], res
    assert text(out, "p3") == value
    assert [b["kind"] for b in fake.read(out)["blocks"]] == [b["kind"] for b in fake.read(doc)["blocks"]]


def test_cell_text_is_one_stripped_line_and_pipes_survive(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    assert edit(doc, [{"op": "set", "at": "t0/r1/c1", "text": " a|b\\c\nd "}], out)["ok"]
    assert text(out, "t0/r1/c1") == "a|b\\c d"
    assert fake.outline(out)["tables"][0]["rows"] == 3


# --------------------------------------------------------------------------- edit semantics
def test_ops_resolve_against_the_base_snapshot(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    res = edit(doc, [
        {"op": "insert_after", "at": "p0", "markdown": "새 문단 하나\n\n새 문단 둘"},
        {"op": "set", "at": "p3", "text": "바뀐 배경 문단", "expect": "배경 문단에 대해 적는다."},
        {"op": "delete", "at": "p1"},
        {"op": "set", "at": "p8", "text": "바뀐 끝 문단"},
    ], out)
    assert res["ok"], res
    assert [a["at"] for a in res["applied"]] == ["p0", "p3", "p1", "p8"]
    assert {"from": "p1", "to": None} in res["remap"]
    assert {"from": "p3", "to": "p4"} in res["remap"]
    assert {"from": "p8", "to": "p9"} in res["remap"]
    assert text(out, "p1") == "새 문단 하나" and text(out, "p2") == "새 문단 둘"
    assert text(out, "p4") == "바뀐 배경 문단" and text(out, "p9") == "바뀐 끝 문단"
    assert res["changed_pages"] == [1, 2]


def test_two_ops_on_one_paragraph_apply_in_order(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    res = edit(doc, [{"op": "set", "at": "p8", "text": "하나"},
                     {"op": "replace", "at": "p8", "find": "하나", "with": "둘", "expect": "하나"}], out)
    assert res["ok"], res
    assert text(out, "p8") == "둘"
    err = edit(doc, [{"op": "delete", "at": "p8"}, {"op": "set", "at": "p8", "text": "x"}], out)["error"]
    assert (err["code"], err["step"], err["done"]) == ("bad_input", 1, [0])


def test_expect_mismatch_details(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    err = edit(doc, [{"op": "set", "at": "p0", "text": "x"},
                     {"op": "delete", "at": "p8", "expect": "다른 글"}], out)["error"]
    assert err == {"code": "expect_mismatch", "message": err["message"], "at": "p8", "step": 1,
                   "done": [0], "data": {"actual": "끝 문단."}, "retryable": False}
    assert not out.exists()


def test_stale_says_the_current_rev(doc, tmp_path):
    err = fake.edit(doc, [{"op": "set", "at": "p0", "text": "x"}], base="0" * 12,
                    out=str(tmp_path / "b.fdoc"))["error"]
    assert err["code"] == "stale" and err["retryable"] is True and err["data"] == {"rev": rev(doc)}


def test_replace_scopes_and_refusals(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    err = edit(doc, [{"op": "replace", "find": "문단", "with": "단락"}], out)["error"]
    assert err["code"] == "ambiguous_match" and err["candidates"] == ["p1", "p3", "p8"]
    assert err["step"] == 0 and err["done"] == []
    res = edit(doc, [{"op": "replace", "find": "문단", "with": "단락", "at": "p3"}], out)
    assert res["ok"] and res["applied"][0] == {"i": 0, "op": "replace", "at": "p3", "count": 1}
    assert text(out, "p3") == "배경 단락에 대해 적는다."
    res = edit(doc, [{"op": "replace", "find": "문단", "with": "단락", "all": True}], out)
    assert res["ok"] and res["applied"][0]["count"] == 4 and fake.find(out, "문단")["hits"] == []
    assert edit(doc, [{"op": "replace", "find": "없는 말", "with": "x"}], out)["error"]["code"] == "not_found"
    res = edit(doc, [{"op": "replace", "find": "나", "with": "다", "at": "t0"}], out)
    assert res["ok"] and text(out, "t0/r2/c0") == "다"


def test_table_ops(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    res = edit(doc, [
        {"op": "table.add_row", "at": "t0", "after": -1, "values": ["맨 위"]},
        {"op": "table.add_row", "at": "t0", "after": 1, "values": ["가 뒤", "9"]},
        {"op": "table.delete_row", "at": "t0/r2/c0"},
        {"op": "table.set_cells", "at": "t0", "grid": [["머리", None], [None, "10"]]},
    ], out)
    assert res["ok"], res
    rows = fake.read(out, "t0")["blocks"][0]["text"].split("\n")
    assert rows == ["맨 위\t", "머리\t값", "가\t10", "가 뒤\t9"]
    err = edit(doc, [{"op": "table.set_cells", "at": "t0/r2/c1", "grid": [["a", "b"]]}], out)["error"]
    assert err["code"] == "bad_input"
    err = edit(doc, [{"op": "table.delete_row", "at": "t0/r0/c0"}, {"op": "table.delete_row", "at": "t0/r1/c0"},
                     {"op": "table.delete_row", "at": "t0/r2/c0"}], out)["error"]
    assert err["code"] == "bad_input" and err["step"] == 2


def test_fill_style_insert_table_and_engine_only_ops(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    res = edit(doc, [{"op": "fill", "place": "place:name", "text": "김하늘"},
                     {"op": "style", "at": "p8", "style": "강조"},
                     {"op": "insert_table", "at": "p8", "data": [["A", "B"], [1, 2]]}], out)
    assert res["ok"], res
    assert text(out, "place:name") == "김하늘"
    assert fake.read(out, "p8")["blocks"][0]["style"] == "강조"
    assert text(out, "t1/r1/c1") == "2"
    err = edit(doc, [{"op": "fill", "place": "nobody", "text": "x"}], out)["error"]
    assert err["code"] == "bad_address" and err["candidates"]
    err = edit(doc, [{"op": "set", "at": "p0", "text": "x"},
                     {"op": "insert_equation", "at": "p0", "latex": "x^2"}], out)["error"]
    assert (err["code"], err["step"], err["done"]) == ("capability_unavailable", 1, [0])
    assert edit(doc, [{"op": "sett", "at": "p0"}], out)["error"]["candidates"][0] == "set"


def test_out_rules(doc, tmp_path):
    ops = [{"op": "set", "at": "p0", "text": "x"}]
    assert fake.edit(doc, ops, base=rev(doc))["error"]["code"] == "bad_input"
    assert fake.edit(doc, ops, base=rev(doc), in_place=True)["error"]["code"] == "bad_input"
    existing = tmp_path / "exists.fdoc"
    existing.write_text("old", encoding="utf-8")
    assert edit(doc, ops, existing)["ok"] and text(existing, "p0") == "x"
    missing_dir = tmp_path / "nope" / "b.fdoc"
    assert edit(doc, ops, missing_dir)["error"]["code"] == "not_found"


def test_preview_writes_a_temp_copy_and_reports_changes(doc, tmp_path):
    res = fake.edit(doc, [{"op": "set", "at": "p0", "text": "x"}, {"op": "fill", "place": "name", "text": "y"}],
                    base=rev(doc), preview=True)
    assert res["ok"], res
    assert Path(res["out"]).is_file() and Path(res["out"]).parent.parent == tmp_path
    assert [(c["i"], c["page"]) for c in res["changed"]] == [(0, 1), (1, 2)]
    assert all(len(c["rect"]) == 4 for c in res["changed"])


# --------------------------------------------------------------------------- pages / render
def test_lone_heading_signal(doc, tmp_path):
    p = fake.pages(doc)
    assert p["count"] == 2
    assert p["pages"] == [{"n": 1, "starts_with": "p0", "signals": [{"kind": "lone_heading", "at": "p4"}]},
                          {"n": 2, "starts_with": "p5", "signals": []}]
    out = tmp_path / "b.fdoc"
    res = edit(doc, [{"op": "set", "at": "p4", "text": "제목"}], out)
    assert res["signals"] == [{"page": 1, "kind": "lone_heading"}]
    res = edit(doc, [{"op": "delete", "at": "p4"}], out)
    assert res["signals"] == [] and fake.pages(out)["pages"][0]["signals"] == []


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_render_png_and_pdf(doc, tmp_path):
    res = fake.render(doc, [2, "page:1"], scale=0.5, out_dir=str(tmp_path / "r"))
    assert [p["n"] for p in res["pages"]] == [2, 1]
    for p in res["pages"]:
        data = Path(p["file"]).read_bytes()
        w, h = _png_size(data)
        assert (w, h) == (p["px_w"], p["px_h"]) == (round(fake.PAGE_W_PT / 2), round(fake.PAGE_H_PT / 2))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        assert len(zlib.decompress(idat)) == (w + 1) * h
    pdf = fake.render(doc, None, fmt="pdf", out_dir=str(tmp_path / "p"))
    data = Path(pdf["pages"][0]["file"]).read_bytes()
    assert data.startswith(b"%PDF-1.4") and b"/Count 2" in data and data.rstrip().endswith(b"%%EOF")
    xref = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert data[xref:xref + 4] == b"xref"
    past = fake.render(doc, [3])["error"]
    assert (past["code"], past["at"], past["range"]) == ("bad_address", "page:3", [1, 2])
    assert fake.render(doc, [1], scale=0)["error"]["code"] == "bad_input"
    assert fake.render(doc, [1], fmt="svg")["error"]["code"] == "bad_input"


# --------------------------------------------------------------------------- convert / new / diff / guard / style
def test_convert(doc, tmp_path):
    md = fake.convert(doc, tmp_path / "a.md", to="md")
    assert md["ok"] and md["lossy"] == ["page_breaks", "places"]
    assert "| 가 | 1 |" in (tmp_path / "a.md").read_text(encoding="utf-8")
    hx = fake.convert(doc, tmp_path / "a.hwpx", to="hwpx")
    assert hx["ok"] and hx["lossy"] == []
    paras = rt_guard.read_paragraphs(tmp_path / "a.hwpx")
    for _, t, _ in fake._Doc(fake.parse(DOC)).units():
        assert t.replace("\n", "") in paras
    for to in ("docx", "pdf", "png", "hwp"):
        assert fake.convert(doc, tmp_path / f"a.{to}", to=to)["error"]["code"] == "capability_unavailable"
    assert fake.convert(doc, tmp_path / "a.x", to="odt")["error"]["code"] == "bad_input"
    assert fake.convert(doc, doc, to="md")["error"]["code"] == "bad_input"
    assert fake.convert(tmp_path / "a.hwpx", tmp_path / "b.md", to="md")["error"]["code"] == \
        "capability_unavailable"


def test_hwpx_export_is_deterministic(doc, tmp_path):
    assert fake.hwpx_bytes(DOC) == fake.hwpx_bytes(DOC)


def test_new_from_markdown_text_and_path(tmp_path):
    res = fake.new("# 제목\n\n#### 깊은 제목\n\n본문 2026.", tmp_path / "n.fdoc")
    assert res["ok"] and res["rev"] == rev(tmp_path / "n.fdoc")
    assert [(h["level"], h["text"]) for h in fake.outline(tmp_path / "n.fdoc")["headings"]] == [
        (1, "제목"), (3, "깊은 제목")]
    src = tmp_path / "in.md"
    src.write_text("본문만", encoding="utf-8")
    assert fake.new(str(src), tmp_path / "m.fdoc")["ok"] and text(tmp_path / "m.fdoc", "p0") == "본문만"
    assert fake.new(src, tmp_path / "m.hwpx")["error"]["code"] == "capability_unavailable"
    assert fake.new("x", tmp_path / "f.fdoc", form="양식.hwpx")["error"]["code"] == "capability_unavailable"
    assert fake.new(str(tmp_path / "missing.md"), tmp_path / "z.fdoc")["error"]["code"] == "not_found"


def test_diff_guard_style(doc, tmp_path):
    out = tmp_path / "b.fdoc"
    assert edit(doc, [{"op": "set", "at": "p1", "text": "첫 문단은 2027년에 쓴다."},
                      {"op": "set", "at": "t0/r1/c1", "text": "1"}], out)["ok"]
    assert fake.diff(doc, out) == {"ok": True, "changes": [
        {"at": "p1", "before": "첫 문단은 2026년에 쓴다.\n같은 문단의 둘째 줄.", "after": "첫 문단은 2027년에 쓴다."}]}
    g = fake.guard(doc, out)
    assert g["ok"] and g["pass"] is False and [(c["at"], c["kind"]) for c in g["changes"]] == [("p1", "numbers")]
    assert fake.guard(doc, doc) == {"ok": True, "pass": True, "changes": []}
    s = fake.style(doc)
    assert [(f["rule"], f["severity"], f["at"]) for f in s["findings"]] == [
        ("ko.translationese.edae", "notice", "p3")]
    assert fake.style(out)["findings"][0]["at"] == "p3"
    clean = tmp_path / "c.fdoc"
    clean.write_text("깨끗한 문장.\n", encoding="utf-8")
    assert fake.style(clean) == {"ok": True, "rev": rev(clean), "findings": []}


# --------------------------------------------------------------------------- envelope
def test_error_codes_are_declared():
    doc_core = {"stale", "expect_mismatch", "ambiguous_match", "not_found", "bad_address", "bad_input",
                "locked"}
    assert fake.DOC_CORE_CODES == doc_core
    shared = rt_codes.ERROR_CODES | doc_core
    assert fake.ERROR_CODES <= shared


GARBAGE = [None, "", 0, 1.5, True, [], {}, ["p0"], {"at": "p0"}, "p-1", "t0/r/c", "h:", "place:", "\x00",
           "page:0", "../../etc/passwd"]


def test_garbage_never_raises(doc, tmp_path):
    out = str(tmp_path / "g.fdoc")
    base = rev(doc)
    for g in GARBAGE:
        results = [
            fake.open(g), fake.outline(g), fake.pages(g), fake.style(g), fake.read(doc, g),
            fake.find(doc, g), fake.find(doc, "문단", scope=g), fake.render(doc, g),
            fake.render(doc, [1], scale=g), fake.convert(doc, g, to="md"), fake.convert(doc, out, to=g),
            fake.new(g, out), fake.diff(doc, g), fake.guard(g, doc),
            fake.edit(doc, g, base=base, out=out), fake.edit(doc, [g], base=base, out=out),
            fake.edit(doc, [{"op": "set", "at": g, "text": g}], base=base, out=out),
            fake.edit(doc, [{"op": "replace", "find": g, "with": g, "at": g}], base=base, out=out),
            fake.edit(doc, [{"op": "table.set_cells", "at": "t0", "grid": g}], base=base, out=out),
            fake.edit(doc, [{"op": "table.add_row", "at": "t0", "after": g, "values": g}], base=base, out=out),
            fake.edit(doc, [{"op": "insert_after", "at": "p0", "markdown": g, "like": g}], base=base, out=out),
            fake.edit(doc, [{"op": "fill", "place": g, "text": g}], base=base, out=out),
            fake.edit(doc, [{"op": "style", "at": "p0", "style": g}], base=base, out=out),
            fake.edit(doc, [{"op": "set", "at": "p0", "text": "x"}], base=g, out=out),
        ]
        for res in results:
            assert isinstance(res, dict) and isinstance(res["ok"], bool), (g, res)
            if not res["ok"]:
                assert res["error"]["code"] in fake.ERROR_CODES, (g, res)
                assert isinstance(res["error"]["retryable"], bool)
