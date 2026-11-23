# -*- coding: utf-8 -*-
"""doc_core (runtime/scripts/rt_doc.py).

Two worlds. Without an engine (CI): the built-in .hwpx path reads, finds and
edits text on rigorloom's own fixtures, and everything else is a structured
``capability_unavailable``. With an engine (``RIGORLOOM_HWP_ENGINE`` pointing
at a kit_api folder): the same calls go through one long-lived worker, and the
numbering is checked against the engine's own ``hnc_edit`` paragraphs. Engine
fixtures are read from the engine folder at test time and never copied here.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_doc as D  # noqa: E402

GUARD = REPO / "examples" / "guard" / "before.hwpx"          # 154 paragraphs, 7 tables, form cells
JUMIN = REPO / "tests" / "corpus" / "forms" / "converted" / "jumin-deungchobon-sinchengseo.hwpx"
REPORT = REPO / "tests" / "corpus" / "forms" / "converted" / "nrf-gyeolgwa-bogoseo-yangsik.hwpx"
ENGINE_DIR = os.environ.get("RIGORLOOM_HWP_ENGINE", "").strip()
HAS_ENGINE = bool(ENGINE_DIR) and (Path(ENGINE_DIR) / "kit_api.py").is_file()


@pytest.fixture(autouse=True)
def _private_cache(tmp_path_factory, monkeypatch):
    """Place ids carried across edits live in a cache; keep the tests' own out of the user's."""
    monkeypatch.setenv(D.CACHE_ENV, str(tmp_path_factory.mktemp("doc-cache")))
    D._LINEAGE.clear()
    yield
    D._LINEAGE.clear()                  # nor leave them in memory for the next test module


@pytest.fixture
def no_engine(monkeypatch):
    """The built-in path, whatever the environment says."""
    D.close()
    monkeypatch.delenv(D.ENGINE_ENV, raising=False)
    monkeypatch.setattr(D, "_engine_dir", lambda env=None: (None, "engine_not_configured"))
    yield
    D.close()


def _copy(src, tmp_path, name=None):
    dst = tmp_path / (name or src.name)
    shutil.copyfile(src, dst)
    return dst


# ============================================================================ addresses
@pytest.mark.parametrize("addr,want", [
    ("p12", {"kind": "para", "p": 12}),
    ("t3", {"kind": "table", "t": 3}),
    ("t3/r2", {"kind": "row", "t": 3, "r": 2}),
    ("t3/r2/c1", {"kind": "cell", "t": 3, "r": 2, "c": 1}),
    ("t3/r2/c1/p0", {"kind": "cellpara", "t": 3, "r": 2, "c": 1, "k": 0}),
    ('h:"추진 배경"', {"kind": "heading", "text": "추진 배경"}),
    ("h:추진 배경", {"kind": "heading", "text": "추진 배경"}),
    ("place:성명", {"kind": "place", "id": "성명"}),
    ("page:4", {"kind": "page", "page": 4}),
    ("p12:5-18", {"kind": "para", "p": 12, "range": (5, 18)}),
])
def test_parse_address(addr, want):
    assert D.parse_address(addr) == want


@pytest.mark.parametrize("addr", ["", "q1", "p", "t1/c2", "p1:9-2", "page:x", None, 3])
def test_parse_address_refuses(addr):
    with pytest.raises(D.DocError) as exc:
        D.parse_address(addr)
    assert exc.value.code == "bad_address"


def test_rev_is_sha256_prefix():
    assert D.rev_of(GUARD) == hashlib.sha256(GUARD.read_bytes()).hexdigest()[:12]


def place_of(src, key):
    """The outline place whose label reads `key` (numbering and spaces aside)."""
    pls = [p for p in D.outline(src)["places"] if D._heading_key(p["label"] or "") == key]
    assert len(pls) == 1, pls
    return pls[0]


# ============================================================================ built-in read path
def test_open_outline_without_engine(no_engine):
    o = D.open(GUARD)
    assert o["ok"] and o["format"] == "hwpx" and o["sections"] == 1
    assert o["paragraphs"] == 154 and o["tables"] == 7
    assert o["rev"] == D.rev_of(GUARD)
    assert o["engine"] == {"available": False, "reason": "engine_not_configured"}
    assert "pages" not in o and "바탕" in o["fonts"]["used"]
    ol = D.outline(GUARD)
    assert [t["at"] for t in ol["tables"]] == ["t%d" % i for i in range(7)]
    assert ol["tables"][5] == {"at": "t5", "rows": 20, "cols": 6, "in": "p152"}
    t5 = D._load(GUARD).by_addr["t5"]
    assert {"id": D.place_id("cell", t5.id, 13, 2), "at": "t5/r13/c2", "label": "2. 취업 장소", "kind": "cell",
            "value": "", "filled": False} in ol["places"]


def test_outline_headings_and_heading_address(no_engine):
    ol = D.outline(REPORT)
    texts = [h["text"] for h in ol["headings"]]
    assert "Ⅰ. 연구 목적 및 방법" in texts
    h1 = next(h for h in ol["headings"] if h["text"] == "Ⅰ. 연구 목적 및 방법")
    assert h1["level"] == 1
    r = D.read(REPORT, 'h:"Ⅰ. 연구 목적"')          # unique prefix
    assert r["ok"] and r["blocks"][0]["at"] == h1["at"]
    nxt = next(h for h in ol["headings"] if h["level"] <= 1 and h["at"] != h1["at"]
               and int(h["at"][1:]) > int(h1["at"][1:]))
    assert r["blocks"][-1]["at"] == "p%d" % (int(nxt["at"][1:]) - 1)     # up to the next heading


def test_read_blocks_and_tables(no_engine):
    r = D.read(GUARD)
    assert r["ok"] and r["rev"] == D.rev_of(GUARD)
    assert r["blocks"][0] == {"at": "p0", "kind": "para", "text": "", "style": "바탕글", "objects": ["hp:tbl"]}
    assert r["blocks"][1]["at"] == "t0" and r["blocks"][1]["cells"] == [["표준근로계약서"]]
    p2 = D.read(GUARD, "p2", with_runs=True)["blocks"]
    assert p2[0]["text"].startswith("1. 근로계약기간") and p2[0]["runs"][0]["text"]
    cell = D.read(GUARD, "t5/r13/c1")["blocks"]
    assert cell[0]["at"].startswith("t5/r13/c")
    assert D.read(GUARD, "t0/r0/c0/p0")["blocks"][0]["text"] == "표준근로계약서"


def test_unresolved_addresses_give_candidates(no_engine):
    e = D.read(GUARD, "p999")["error"]
    assert e["code"] == "bad_address" and e["candidates"][0] == "p153" and e["retryable"] is False
    e = D.read(GUARD, "t9")["error"]
    assert e["code"] == "bad_address" and "t0" in e["candidates"]
    e = D.read(GUARD, "place:취업장")["error"]       # a label is not an id; the label's place is offered
    assert e["code"] == "bad_address" and "place:%s" % place_of(GUARD, "취업장소")["id"] in e["candidates"]
    e = D.read(REPORT, 'h:"연구 목적"')["error"]
    assert e["code"] == "bad_address" and any("연구 목적" in c for c in e["candidates"])
    assert D.read(GUARD, "page:1")["error"]["code"] == "capability_unavailable"


def test_find(no_engine):
    r = D.find(GUARD, "근로계약기간")
    assert r["ok"] and r["hits"][0] == {"at": "p2", "start": 3, "end": 9, "text": "근로계약기간"}
    assert all(h["text"] == "근로계약기간" for h in r["hits"])
    rx = D.find(GUARD, r"\d+\. 근로", regex=True)
    assert rx["hits"] and rx["hits"][0]["at"] == "p2"
    sc = D.find(GUARD, "표준근로계약서", scope="t0")
    assert [h["at"] for h in sc["hits"]] == ["t0/r0/c0/p0"]
    assert D.find(GUARD, "(", regex=True)["error"]["code"] == "bad_input"


def test_missing_and_foreign_files(no_engine, tmp_path):
    assert D.open(tmp_path / "nope.hwpx")["error"]["code"] == "not_found"
    junk = tmp_path / "x.hwpx"
    junk.write_bytes(b"hello")
    assert D.open(junk)["error"]["code"] == "bad_input"
    hwp = tmp_path / "x.hwp"
    hwp.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    e = D.open(hwp)["error"]
    assert e["code"] == "capability_unavailable" and e["reason"] == "hwp_binary_unsupported"


# ============================================================================ built-in edits
def test_text_edits_without_engine(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    before = src.read_bytes()
    rev = D.rev_of(src)
    out = tmp_path / "out.hwpx"
    r = D.edit(src, [
        {"op": "set", "at": "p2", "text": "새 문장 & <b>", "expect": D.read(src, "p2")["blocks"][0]["text"]},
        {"op": "replace", "at": "t0/r0/c0/p0:0-7", "find": "표준근로계약서", "with": "계약서"},
        {"op": "replace", "at": "p1", "find": "근로", "with": "N", "all": True},
        {"op": "table.set_cells", "at": "t5/r13/c2", "grid": [["강남구"]]},
        {"op": "fill", "place": place_of(src, "근로자Worker")["id"], "text": "홍길동"},
    ], base=rev, out=out)
    assert r["ok"], r
    assert src.read_bytes() == before                       # input untouched
    assert r["rev_before"] == rev and r["rev"] == D.rev_of(out) and r["out"] == str(out)
    assert [a["i"] for a in r["applied"]] == [0, 1, 2, 3, 4]
    assert r["remap"] == [] and r["changed_pages"] == [] and r["signals"] == [] and r["engine"] is False
    assert D.read(out, "p2")["blocks"][0]["text"] == "새 문장 & <b>"
    assert D.read(out, "t0")["blocks"][0]["cells"] == [["계약서"]]
    p1 = D.read(out, "p1")["blocks"][0]["text"]
    assert "근로" not in p1 and "N계약" in p1
    assert D.read(out, "t5/r13/c2")["blocks"][0]["text"] == "강남구"
    worker = place_of(src, "근로자Worker")
    seat = worker["at"]
    assert D.read(out, seat)["blocks"][0]["text"] == "홍길동"
    filled = {p["id"]: p for p in D.outline(out)["places"]}[worker["id"]]    # a filled seat keeps its id
    assert filled["at"] == seat and filled["value"] == "홍길동" and filled["filled"] is True
    # the package: same members in the same order, mimetype first and stored, XML well-formed
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert [i.filename for i in a.infolist()] == [i.filename for i in b.infolist()]
        assert b.infolist()[0].filename == "mimetype" and b.infolist()[0].compress_type == zipfile.ZIP_STORED
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert changed == ["Contents/section0.xml"]
    # the edited paragraph lost its cached line layout; untouched ones kept theirs
    doc = D._load(out)
    assert doc.top[2].lineseg is None and doc.top[3].lineseg is not None
    # diff names exactly what changed
    ch = D.diff(src, out)["changes"]
    assert {"p1", "p2", "t0/r0/c0", "t5/r13/c2"} <= {c["at"] for c in ch} and len(ch) == 5



def test_expect_on_a_cell_names_where_the_expected_text_is(no_engine, tmp_path):
    # P7 round 3: an agent counted rows from 1 (t1/r3/c2 for the row at r2).
    # The document had not changed, so the refusal says where the expected
    # text is when exactly one other cell of the same table holds it.
    src = tmp_path / "a.hwpx"
    shutil.copyfile(REPO / "tests" / "fixtures" / "doc_core" / "addressing.hwpx", src)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def refused(op):
        e = D.edit(src, [op], base=rev, out=out)["error"]
        assert e["code"] == "expect_mismatch" and not out.exists()
        return e
    e = refused({"op": "set", "at": "t0/r2/c0", "text": "주소지", "expect": "주소"})
    assert (e["at"], e["actual"], e["found_at"]) == ("t0/r2/c0", "연락", "t0/r1/c0")
    e = refused({"op": "delete", "at": "t0/r0/c2", "expect": "끝"})
    assert e["found_at"] == "t0/r2/c2"
    e = refused({"op": "char_shape", "at": "t0/r0/c0", "set": {"bold": True}, "expect": "연락"})
    assert e["found_at"] == "t0/r2/c0"      # checked before the engine is needed
    e = refused({"op": "numbering", "at": "t0/r0/c0", "set": {"kind": "bullet"}, "expect": "연락"})
    assert e["found_at"] == "t0/r2/c0"
    # Nowhere in the table, or in more than one cell (the empty ones): no guess.
    assert "found_at" not in refused({"op": "set", "at": "t0/r0/c0", "text": "x", "expect": "없는 글"})
    assert "found_at" not in refused({"op": "set", "at": "t0/r0/c0", "text": "x", "expect": ""})


def test_edit_refusals(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev = D.rev_of(src)
    out = tmp_path / "o.hwpx"
    e = D.edit(src, [{"op": "set", "at": "p2", "text": "x"}], base="0" * 12, out=out)["error"]
    assert e["code"] == "stale" and e["rev"] == rev
    e = D.edit(src, [{"op": "set", "at": "p2", "text": "x", "expect": "nope"}], base=rev, out=out)["error"]
    assert e["code"] == "expect_mismatch" and e["at"] == "p2" and e["i"] == 0
    e = D.edit(src, [{"op": "replace", "find": "근로계약기간", "with": "x"}], base=rev, out=out)["error"]
    assert e["code"] == "ambiguous_match" and len(e["candidates"]) == e["total"] > 1
    assert e["candidates"][0] == "p2:3-9"
    e = D.edit(src, [{"op": "replace", "find": "없는 말", "with": "x"}], base=rev, out=out)["error"]
    assert e["code"] == "not_found"
    e = D.edit(src, [{"op": "set", "at": "p2", "text": "a"}, {"op": "set", "at": "p2", "text": "b"}],
               base=rev, out=out)["error"]
    assert e["code"] == "conflict"
    e = D.edit(src, [{"op": "set", "at": "p0", "text": "x"}], base=rev, out=out)["error"]
    assert e["code"] == "bad_input" and "object" in e["message"]
    e = D.edit(src, [{"op": "frobnicate"}], base=rev, out=out)["error"]
    assert e["code"] == "bad_input"
    e = D.edit(src, [{"op": "insert_after", "at": "p2", "markdown": "새 문단"}], base=rev, out=out)["error"]
    assert e["code"] == "capability_unavailable" and e["reason"] == "structural_edit_unsupported"
    e = D.edit(src, [{"op": "set", "at": "p2", "text": "두\n줄"}], base=rev, out=out)["error"]
    assert e["code"] == "capability_unavailable"
    e = D.edit(src, [{"op": "set", "at": "p2", "text": "x"}], base=rev, out=src)["error"]
    assert e["code"] == "bad_input"
    e = D.edit(src, [{"op": "table.set_cells", "at": "t5/r13/c1", "grid": [[None, "x", "y"]]}],
               base=rev, out=out)["error"]
    assert e["code"] == "bad_address"
    assert not out.exists()


def test_in_place_and_default_out(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    r = D.edit(src, [{"op": "set", "at": "p2", "text": "하나"}], base=D.rev_of(src))
    assert r["ok"] and r["out"] == str(tmp_path / "before.edited.hwpx")
    r = D.edit(src, [{"op": "set", "at": "p2", "text": "둘"}], base=D.rev_of(src), in_place=True)
    assert r["ok"] and r["out"] == str(src.resolve()) and D.read(src, "p2")["blocks"][0]["text"] == "둘"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".rtdoc-")]


def test_engine_only_functions_without_engine(no_engine, tmp_path):
    for res in (D.render(GUARD, 1), D.pages(GUARD), D.geometry(GUARD, 1), D.hit_test(GUARD, 1, 10, 10),
                D.caret_rect(GUARD, "p2", 0), D.new("# 제목", tmp_path / "n.hwpx"),
                D.convert(GUARD, tmp_path / "x.pdf", to="pdf"), D.convert(GUARD, tmp_path / "x.md", to="md")):
        assert res["ok"] is False
        assert res["error"]["code"] == "capability_unavailable" and res["error"]["retryable"] is False
    c = D.convert(GUARD, tmp_path / "copy.hwpx", to="hwpx")
    assert c["ok"] and (tmp_path / "copy.hwpx").read_bytes() == GUARD.read_bytes()


def test_engine_error_keeps_fields():
    env = {"ok": False, "error": {"code": "bad_input", "message": "step 3 (goto): IndexError: x", "step": 3,
                                  "done": [{"op": "goto", "result": None}]}}
    e = D._engine_error(env, "edit", at="p4", i=1).to_error()
    assert e["code"] == "bad_input" and e["message"].startswith("step 3") and e["step"] == 3
    assert e["done"] and e["at"] == "p4" and e["i"] == 1 and e["retryable"] is False
    miss = D._engine_error({"ok": False, "error": {"code": "unsupported", "message": "no such function: png"}},
                           "png").to_error()
    assert miss["code"] == "capability_unavailable" and miss["reason"] == "engine_function_missing"


def test_equation_op_converts_latex(no_engine):
    doc = D._load(GUARD)
    acts = D._plan(doc, [{"op": "insert_equation", "at": "p2", "latex": r"\frac{a}{b}", "base_pt": 11}])
    step = acts[0].steps[-1]
    assert step[0] == "insert_equation" and step[1] == "{a}over{b}"
    assert any(w.startswith("base_pt_ignored") for w in acts[0].info["warnings"])
    with pytest.raises(D.DocError) as exc:
        D._plan(doc, [{"op": "insert_equation", "at": "p2", "latex": "x", "hwpeqn": "x"}])
    assert exc.value.code == "bad_input"


# ============================================================================ with the engine
engine = pytest.mark.skipif(not HAS_ENGINE, reason="RIGORLOOM_HWP_ENGINE is not set to an engine")


def _standin_fonts(root: Path):
    """Without Hancom's fonts the engine's layout stops; a box-glyph stand-in named 함초롬바탕/돋움 keeps it
    running (approximate geometry: these tests check structure, not positions)."""
    ft = pytest.importorskip("fontTools.fontBuilder")
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    root.mkdir(parents=True, exist_ok=True)
    for fam, fn in (("함초롬바탕", "a.ttf"), ("함초롬돋움", "b.ttf")):
        fb = ft.FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "space", "box"])
        cmap = {0x20: "space"}
        for cp in list(range(0x21, 0x7F)) + list(range(0xAC00, 0xD7A4)) + list(range(0x3131, 0x318F)):
            cmap[cp] = "box"
        fb.setupCharacterMap(cmap)

        def box():
            p = TTGlyphPen(None)
            p.moveTo((50, 0)), p.lineTo((50, 700)), p.lineTo((450, 700)), p.lineTo((450, 0)), p.closePath()
            return p.glyph()
        fb.setupGlyf({".notdef": box(), "space": TTGlyphPen(None).glyph(), "box": box()})
        fb.setupHorizontalMetrics({".notdef": (500, 50), "space": (250, 0), "box": (500, 50)})
        fb.setupHorizontalHeader(ascent=880, descent=-120)
        fb.setupNameTable({"familyName": fam, "styleName": "Regular"})
        fb.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120)
        fb.setupPost()
        fb.save(str(root / fn))
    conf = root / "fonts.conf"
    conf.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                    '<include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>%s</dir>'
                    '<cachedir>%s</cachedir></fontconfig>' % (root, root / "cache"), encoding="utf-8")
    return conf


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    D.close()
    old = os.environ.get("FONTCONFIG_FILE")
    try:
        fams = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    except OSError:
        fams = ""
    if "함초롬바탕" not in fams:
        os.environ["FONTCONFIG_FILE"] = str(_standin_fonts(tmp_path_factory.mktemp("fonts")))
    yield Path(ENGINE_DIR)
    D.close()
    if old is None:
        os.environ.pop("FONTCONFIG_FILE", None)
    else:
        os.environ["FONTCONFIG_FILE"] = old


def _features(kit):
    return sorted((kit / "tests" / "features").glob("*.hwpx")) + [kit / "forms" / "blank_a4.hwpx"]


@engine
def test_numbering_matches_engine_paragraphs(kit):
    """pN / tN / cell paragraphs and their text are what hnc_edit.Doc sees, document by document."""
    e = D._engine()
    for f in _features(kit):
        doc = D._load(f)
        r = e.call("edit", str(f), [["paragraphs", si] for si in range(len(doc.secs))])
        assert r["ok"], r
        assert [len(s["result"]) for s in r["steps"]] == [len(ps) for ps in doc.sec_paras], f.name
        steps = [["text", p.k, p.si] for p in doc.paras]
        t = e.call("edit", str(f), steps)
        assert [s["result"] for s in t["steps"]] == [p.text for p in doc.paras], f.name
        cells = [["cell_paragraphs", t.lt, c.row, c.col, t.si] for t in doc.tables for c in t.cells]
        if cells:
            c = e.call("edit", str(f), cells)
            assert [s["result"] for s in c["steps"]] == [[p.k for p in cc.paras] for t in doc.tables
                                                         for cc in t.cells], f.name


@engine
def test_engine_open_outline_pages(kit):
    f = kit / "tests" / "features" / "feat_tables.hwpx"
    o = D.open(f)
    assert o["ok"] and o["engine"]["available"] and o["pages"] >= 1
    ol = D.outline(f)
    assert [t["at"] for t in ol["tables"]] == ["t0", "t1"] and all("page" in t for t in ol["tables"])
    pg = D.pages(f)
    assert pg["ok"] and pg["count"] == len(pg["pages"]) and pg["pages"][0]["starts_with"] == "p0"
    for p in pg["pages"]:
        for s in p["signals"]:
            assert s["kind"] in ("lone_heading", "bottom_heading", "table_split", "caption_split", "widow",
                                 "orphan", "top_blank")
    r = D.read(f, "page:1")
    assert r["ok"] and r["blocks"][0]["at"] == "p0"


@engine
def test_engine_structural_edit(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    rev = D.rev_of(f)
    third = D.read(f, "p3")["blocks"][0]["text"]
    out = tmp_path / "e.hwpx"
    r = D.edit(f, [
        {"op": "set", "at": "p0", "text": "첫 문단"},
        {"op": "insert_after", "at": "p0", "markdown": "- 하나\n- 둘"},
        {"op": "table.set_cells", "at": "t1/r1/c0", "grid": [["A", "B"]]},
        {"op": "table.add_row", "at": "t0", "after": 1, "values": ["n1", "n2"]},
        {"op": "table.delete_row", "at": "t1/r3"},
        {"op": "delete", "at": "p7"},
        {"op": "insert_table", "at": "p2", "data": [["h1", "h2"], ["v1", "v2"]]},
    ], base=rev, out=out)
    assert r["ok"], r
    assert r["changed_pages"] and all(isinstance(n, int) for n in r["changed_pages"])
    assert "remap_approx" not in r
    moved = {m["from"]: m["to"] for m in r["remap"]}
    assert moved["p3"] == "p7" and moved["p7"] is None and moved["t1"] == "t2"
    assert moved["t0/r2"] == "t0/r3" and moved["t1/r3"] is None
    assert D.read(out, moved["p3"])["blocks"][0]["text"] == third
    assert [b["text"] for b in D.read(out)["blocks"][:3]] == ["첫 문단", "하나", "둘"]
    assert D.read(out, "t1")["blocks"][0]["cells"] == [["h1", "h2"], ["v1", "v2"]]
    assert D.read(out, "t0/r2/c0")["blocks"][0]["text"] == "n1"
    assert D.read(out, "t2/r1/c0")["blocks"][0]["text"] == "A"
    assert D.read(out, "t2")["blocks"][0]["rows"] == 29
    assert f.read_bytes() and D.rev_of(f) == rev


@engine
def test_engine_preview_signals_and_errors(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    rev = D.rev_of(f)
    r = D.edit(f, [{"op": "set", "at": "p3", "text": "짧게"}], base=rev, preview=True)
    assert r["ok"] and r["changed"] == [{"i": 0, "page": 1, "rect": None}]
    assert not (tmp_path / "feat_tables.edited.hwpx").exists()
    assert any(s["kind"] == "table_split" for s in r["signals"]) or r["signals"] == []
    e = D.edit(f, [{"op": "style", "at": "p3", "style": "없는 스타일"}], base=rev, out=tmp_path / "x.hwpx")
    assert e["error"]["code"] == "bad_input" and e["error"]["candidates"]


@engine
def test_engine_render_png(kit, tmp_path):
    pytest.importorskip("pypdfium2")
    f = kit / "tests" / "features" / "feat_paragraphs.hwpx"
    r = D.render(f, [1], scale=1.0, out_dir=tmp_path)
    assert r["ok"], r
    pg = r["pages"][0]
    assert pg["n"] == 1 and Path(pg["file"]).is_file() and pg["px_w"] > 100
    assert 590 < pg["width_pt"] < 600                     # A4
    assert Path(pg["file"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@engine
def test_engine_missing_functions_light_up_later(kit):
    f = kit / "tests" / "features" / "feat_paragraphs.hwpx"
    for res in (D.geometry(f, 1), D.hit_test(f, 1, 100, 100), D.caret_rect(f, "p0", 0)):
        if not res["ok"]:
            assert res["error"]["code"] == "capability_unavailable"
            assert res["error"]["reason"] == "engine_function_missing"


@engine
def test_engine_new_and_convert(kit, tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# 제목\n\n## 배경\n\n본문 문단입니다.\n", encoding="utf-8")
    r = D.new(md, tmp_path / "n.hwpx")
    assert r["ok"], r
    assert any("본문 문단" in b["text"] for b in D.read(tmp_path / "n.hwpx")["blocks"])
    c = D.convert(tmp_path / "n.hwpx", tmp_path / "n.pdf", to="pdf")
    assert c["ok"] and (tmp_path / "n.pdf").read_bytes()[:5] == b"%PDF-"


@engine
def test_engine_new_reads_commonmark_tables_lists_and_written_numbers(kit, tmp_path):
    # P7 round 0: agents write GFM tables and lists, and number their headings
    # themselves; the report dialect gave them pipes, one merged paragraph and
    # "1. 1. 개요".
    md = "## 1. 개요\n\n- 첫째\n- 둘째\n\n| 구분 | 내용 |\n|---|---|\n| 시료 | 42건 |\n"
    r = D.new(md, tmp_path / "c.hwpx", commonmark=True)
    assert r["ok"], r
    blocks = D.read(tmp_path / "c.hwpx")["blocks"]
    assert [b["text"] for b in blocks if b["kind"] == "heading"] == ["1. 개요"]
    assert [b["text"] for b in blocks if b["kind"] == "para" and b["text"]] == ["첫째", "둘째"]
    tables = [b for b in blocks if b["kind"] == "table"]
    assert len(tables) == 1 and tables[0]["cells"] == [["구분", "내용"], ["시료", "42건"]]
    # That the heading style adds no number of its own is read on the drawn
    # page by evals/agent_checks.py; this module's stand-in fonts draw no Hangul.
    assert D.new(md, tmp_path / "f.hwpx", form=str(tmp_path / "c.hwpx"),
                 commonmark=True)["error"]["code"] == "bad_input"


def test_fonts_reads_the_engines_measured_with_note():
    class _Doc:
        fonts = ["함초롬바탕", "돋움"]
    note = "font 함초롬바탕 measured with the system face Noto Serif CJK KR (no Hancom font installed)"
    assert D._fonts(_Doc(), [note, "함초롬바탕", "돋움"]) == {
        "used": ["함초롬바탕", "돋움"],
        "substituted": [{"want": "함초롬바탕", "got": "Noto Serif CJK KR"},
                        {"want": "돋움", "got": None}]}
    assert D._fonts(_Doc(), ["바탕 → 나눔명조"])["substituted"] == [{"want": "바탕", "got": "나눔명조"}]


@engine
def test_engine_reads_and_edits_hwp(kit, tmp_path):
    f = _copy(kit / "tests" / "hwp5" / "written" / "kit_feat_lists.hwp", tmp_path)
    before = f.read_bytes()
    o = D.open(f)
    assert o["ok"] and o["format"] == "hwp"
    first = D.read(f, "p0")["blocks"][0]
    assert first["text"]
    r = D.edit(f, [{"op": "set", "at": "p0", "text": "바뀜", "expect": first["text"]}], base=D.rev_of(f))
    assert r["ok"] and r["out"].endswith("kit_feat_lists.edited.hwpx")
    assert D.read(r["out"], "p0")["blocks"][0]["text"] == "바뀜"
    assert f.read_bytes() == before

# ============================================================================ shared addressing fixture
# tests/fixtures/doc_core/addressing.{hwpx,json} (doc-core-api.md, ruling 2026-11-19 04:30Z), the fixture
# rt_doc and the engine both run: only top-level tables count as t<N>, a nested table goes through its cell, a
# covered cell answers at its anchor, the unused hp:switch branch has no address, place ids hash an identity
# filling cannot change, unresolved addresses are bad_address with at and candidates, ranges count code points,
# and a locked file is `locked`.
FX_DIR = REPO / "tests" / "fixtures" / "doc_core"
FX_DOC = FX_DIR / "addressing.hwpx"
FX_WANT = json.loads((FX_DIR / "addressing.json").read_text("utf-8"))


def _fx_copy(tmp_path, name="doc.hwpx"):
    return shutil.copyfile(FX_DOC, tmp_path / name)


def _fx_text(f, at):
    r = D.read(f, at)
    assert r["ok"], r
    return r["blocks"][0]["text"]


def _fx_cells(f):
    return {p["at"]: p for p in D.outline(f)["places"] if p["kind"] == "cell"}


# ---------------------------------------------------------------------------- the addressing fixture
def test_addressing_fixture_matches_its_builder():
    sys.path.insert(0, str(FX_DIR))
    try:
        import build_addressing as B
    finally:
        sys.path.remove(str(FX_DIR))
    assert B.expected() == FX_WANT, "addressing.json is stale; run tests/fixtures/doc_core/build_addressing.py"
    for p in FX_WANT["cell_places"] + FX_WANT["label_lines"]:
        assert D.place_id(*p["parts"]) == p["id"]


# ============================================================================ tables
def test_only_top_level_tables_count_and_nested_ones_go_through_their_cell(no_engine):
    ol = D.outline(FX_DOC)
    assert [(t["at"], t["rows"], t["cols"]) for t in ol["tables"]] == \
        [(t["at"], t["rows"], t["cols"]) for t in FX_WANT["tables"]]
    doc = D._load(FX_DOC)
    assert {a: t.id for a, t in doc.by_addr.items()} == {t["at"]: t["id"] for t in FX_WANT["tables"]}
    assert [t.id for t in doc.tables if t.addr is None] == ["5004"]        # the hp:default branch


@pytest.mark.parametrize("at", sorted(FX_WANT["text"]))
def test_addresses_read_back(no_engine, at):
    assert _fx_text(FX_DOC, at) == FX_WANT["text"][at]


def test_a_covered_cell_answers_at_its_anchor(no_engine):
    for at, anchor in FX_WANT["covered"].items():
        r = D.read(FX_DOC, at)
        assert r["ok"] and r["blocks"][0]["at"].startswith(anchor + "/"), r


@pytest.mark.parametrize("at", FX_WANT["bad_address"])
def test_unresolved_addresses_are_bad_address_with_at_and_candidates(no_engine, at):
    e = D.read(FX_DOC, at)["error"]
    assert e["code"] == "bad_address" and e["at"] == at and e["candidates"], e
    for c in e["candidates"]:
        assert D.read(FX_DOC, c)["ok"], c                                   # every candidate resolves


def test_full_read_blocks_read_back_alone(no_engine):
    for b in D.read(FX_DOC)["blocks"]:
        assert D.read(FX_DOC, b["at"])["ok"], b


def test_edit_a_nested_cell(no_engine, tmp_path):
    src = _fx_copy(tmp_path)
    out = tmp_path / "out.hwpx"
    r = D.edit(src, [{"op": "set", "at": "t0/r2/c1/t0/r0/c1", "text": "010-0000-0000"},
                     {"op": "table.set_cells", "at": "t2/r1/c1", "grid": [["서울"]]}],
               base=D.rev_of(src), out=out)
    assert r["ok"], r
    assert r["remap"] == []
    assert _fx_text(out, "t0/r2/c1/t0/r0/c1") == "010-0000-0000" and _fx_text(out, "t2/r1/c1") == "서울"
    assert _fx_text(out, "t0/r1/c1") == "" and _fx_text(out, "t1/r0/c0") == "분류"


# ============================================================================ place ids
def test_cell_place_ids_hash_table_id_row_and_column(no_engine):
    got = _fx_cells(FX_DOC)
    for p in FX_WANT["cell_places"]:
        assert got[p["at"]]["id"] == p["id"] and got[p["at"]]["label"] == p["label"], (p, got.get(p["at"]))
    assert len({p["id"] for p in got.values()}) == len(got)               # the two 성명 cells differ


def test_filling_one_form_moves_no_id_of_the_other(no_engine, tmp_path):
    src = _fx_copy(tmp_path)
    before = _fx_cells(src)
    first = before["t0/r0/c1"]["id"]
    out = tmp_path / "filled.hwpx"
    r = D.edit(src, [{"op": "fill", "place": first, "text": "홍길동"}], base=D.rev_of(src), out=out)
    assert r["ok"], r
    after = _fx_cells(out)
    assert {a: p["id"] for a, p in after.items()} == {a: p["id"] for a, p in before.items()}
    assert after["t0/r0/c1"]["value"] == "홍길동" and after["t0/r0/c1"]["filled"] is True
    assert after["t0/r1/c1"]["label"] == "주소"                            # not relabelled by the typed value
    assert after["t2/r0/c1"]["filled"] is False
    # an outside copy (no lineage): every seat still empty there keeps the same id
    D._LINEAGE.clear()
    os.environ[D.CACHE_ENV] = str(tmp_path / "fresh-cache")
    outside = {a: p["id"] for a, p in _fx_cells(out).items()}
    assert outside == {a: p["id"] for a, p in before.items() if a != "t0/r0/c1"}
    # filling the second form's 성명 by its id writes there, not into the first
    r2 = D.edit(out, [{"op": "fill", "place": before["t2/r0/c1"]["id"], "text": "김철수"}], base=D.rev_of(out),
                out=tmp_path / "again.hwpx")
    assert r2["ok"] and _fx_text(r2["out"], "t2/r0/c1") == "김철수" and _fx_text(r2["out"], "t0/r0/c1") == "홍길동"


# ============================================================================ errors and offsets
@pytest.fixture(params=["builtin", pytest.param("engine", marks=pytest.mark.skipif(
    not HAS_ENGINE, reason="RIGORLOOM_HWP_ENGINE is not set to an engine"))])
def either(request):
    """Run the test on the built-in path and, when an engine is set, on the engine."""
    if request.param == "engine":
        request.getfixturevalue("kit")
        D.close()
    else:
        request.getfixturevalue("no_engine")
    return request.param


def test_offsets_count_code_points(either, tmp_path):
    src = _fx_copy(tmp_path)
    out = tmp_path / "cp.hwpx"
    r = D.edit(src, [{"op": "set", "at": "p3", "text": "a😀b한c"}], base=D.rev_of(src), out=out)
    assert r["ok"], r
    hit = D.find(out, "b한")["hits"][0]
    assert (hit["at"], hit["start"], hit["end"]) == ("p3", 2, 4)
    r = D.edit(out, [{"op": "replace", "at": "p3:1-2", "find": "😀", "with": "X"}], base=D.rev_of(out),
               out=tmp_path / "cp2.hwpx")
    assert r["ok"] and _fx_text(r["out"], "p3") == "aXb한c"
    e = D.read(out, "p3:0-9")["error"]
    assert e["code"] == "bad_address" and e["range"] == [0, 5]


def test_a_locked_file_is_locked_and_retryable(no_engine, tmp_path):
    src = _fx_copy(tmp_path)
    real = D._bopen

    def deny(path, *a, **k):
        if Path(path) == Path(src):
            raise PermissionError(13, "The process cannot access the file because it is being used")
        return real(path, *a, **k)
    with patch.object(D, "_bopen", side_effect=deny):
        e = D.outline(src)["error"]
    assert e["code"] == "locked" and e["retryable"] is True


# ============================================================================ with the engine
@engine
def test_engine_agrees_on_tables_and_place_ids(kit):
    D.close()
    ol = D.outline(FX_DOC)
    assert ol["ok"], ol
    assert [t["at"] for t in ol["tables"]] == [t["at"] for t in FX_WANT["tables"]]
    want = {p["at"]: p["id"] for p in FX_WANT["cell_places"] + FX_WANT["label_lines"]}
    got = {p["at"]: p["id"] for p in ol["places"]}
    # the engine's outline (hwp-engine #7) lists seats inside nested tables too, addressed through their cell
    assert set(got) == set(want), got
    for at, pid in got.items():
        assert pid == want[at], (at, pid)
    assert "t0/r2/c1" not in got                    # a cell holding a table is no seat


@engine
def test_engine_edit_of_a_nested_cell_and_remap_through_it(kit, tmp_path):
    D.close()
    src = _fx_copy(tmp_path)
    out = tmp_path / "ins.hwpx"
    r = D.edit(src, [{"op": "insert_table", "at": "p0", "data": [["새", "표"]]},
                     {"op": "set", "at": "t0/r2/c1/t0/r1/c1", "text": "a@b"}], base=D.rev_of(src), out=out)
    assert r["ok"], r
    assert not r.get("remap_approx"), r
    assert D.follow_remap(r["remap"], "t0") == "t1"
    assert D.follow_remap(r["remap"], "t0/r2/c1/t0/r1/c1") == "t1/r2/c1/t0/r1/c1"
    assert _fx_text(out, "t1/r2/c1/t0/r1/c1") == "a@b" and _fx_text(out, "t1/r2/c1/t0/r0/c0") == "전화"
    assert _fx_text(out, "t3/r0/c0") == "성명"


@engine
def test_engine_page_out_of_range_is_bad_address_with_range(kit):
    D.close()
    n = D.pages(FX_DOC)
    assert n["ok"], n
    e = D.render(FX_DOC, [n["count"] + 1])["error"]
    assert e["code"] == "bad_address" and e["range"] == [1, n["count"]]


def test_builtin_lists_blank_label_lines(no_engine):
    ol = D.outline(FX_DOC)
    got = {p["at"]: p for p in ol["places"]}
    for p in FX_WANT["label_lines"]:
        assert got[p["at"]]["id"] == p["id"] and got[p["at"]]["label"] == "성명", got.get(p["at"])
    assert ol["places_complete"] is True


@pytest.mark.parametrize("line, filled", [("성명: ", "성명: 둘째"), ("성명:", "성명: 둘째"), ("성명:  ___", "성명:  둘째"),
                                          ("성명: 첫째", "성명: 둘째")])
def test_label_line_fill_types_after_the_blank(either, tmp_path, line, filled):
    src = _fx_copy(tmp_path)
    mid = tmp_path / "mid.hwpx"
    r = D.edit(src, [{"op": "set", "at": "p5", "text": line}], base=D.rev_of(src), out=mid)
    assert r["ok"], r
    pid = D.place_id("field", "성명", 0)        # the line's id does not depend on what it holds
    assert pid in {p["id"] for p in D.outline(mid)["places"]}
    out = tmp_path / "out.hwpx"
    r = D.edit(mid, [{"op": "fill", "place": pid, "text": "둘째"}], base=D.rev_of(mid), out=out)
    assert r["ok"], r
    assert _fx_text(out, "p5") == filled


def test_label_line_rule():
    ll = D.label_line
    assert ll("  성 명 : 홍길동 ") == {"label": "성 명", "key": "성명", "at": 8, "value": "홍길동", "blank": False}
    assert ll("성명：")["blank"] is True and ll("Name: __")["blank"] is True
    assert ll("주민등록번호: 1")["key"] == "주민등록번호"
    for no in ("1. 성명: x", ": x", "아주아주아주아주아주아주아주아주: x", "성명 x", "(성명): x", "성명-1: x"):
        assert ll(no) is None, no


def test_heading_key_rule():
    hk = D._heading_key
    assert hk("Ⅰ. 연구 목적 및 방법") == "연구목적및방법"
    assert hk("1.2. 추진 배경") == hk("가. 추진 배경") == hk("(3) 추진 배경") == "추진배경"
    assert hk("IV. 결론: 요약") == "결론요약"
    assert hk("Item 1") == "Item1"


@engine
def test_engine_unverified_removal_is_refused_not_reported(kit, tmp_path):
    """advisor review of #388, item 2: removing the hp:switch table must be done or refused, never reported done."""
    D.close()
    src = _fx_copy(tmp_path)
    for i, op in enumerate([{"op": "delete", "at": "t1"}, {"op": "table.delete_row", "at": "t1/r0"}]):
        out = tmp_path / ("del%d.hwpx" % i)
        r = D.edit(src, [op], base=D.rev_of(src), out=out)
        if r["ok"]:                     # an engine that does remove it: the output shows exactly that
            assert not r.get("remap_approx"), r
            assert len(D.outline(out)["tables"]) == (3 if op["op"] == "delete" else 4), r
        else:
            assert r["error"]["code"] == "internal" and r["error"]["written"] is False, r
            assert not out.exists()
    out = tmp_path / "del-t2.hwpx"     # an ordinary removal still goes through, with its exact remap
    r = D.edit(src, [{"op": "delete", "at": "t2"}], base=D.rev_of(src), out=out)
    assert r["ok"] and r["remap"] == [{"from": "t2", "to": None}] and not r.get("remap_approx"), r
    assert [t["at"] for t in D.outline(out)["tables"]] == ["t0", "t0/r2/c1/t0", "t1"]


@pytest.mark.parametrize("op", [{"op": "delete", "at": "t1"}, {"op": "table.delete_row", "at": "t2/r0"},
                                {"op": "delete", "at": "p3"}])
def test_unverified_removal_is_refused(no_engine, op):
    """An output that does not show a planned removal is refused, never published as done."""
    doc = D._load(FX_DOC)
    acts = D._plan(doc, [op])
    with patch.object(D, "_verify", return_value=False):
        with pytest.raises(D.DocError) as exc:
            D._remap_result(doc, doc, acts)
    assert exc.value.code == "internal" and exc.value.extra["written"] is False
    with patch.object(D, "_verify", return_value=False):        # without a removal: a flagged guess, as before
        _remap, approx = D._remap_result(doc, doc, D._plan(doc, [{"op": "set", "at": "p3", "text": "x"}]))
    assert approx is True


# ---------------------------------------------------------------------------- amendment 2026-11-19 05:50Z
def test_place_id_resolves_for_every_cell_listed_or_not(no_engine):
    listed = {p["id"] for p in D.outline(FX_DOC)["places"]}
    label_cell = D.place_id("cell", "5001", 0, 0)                # a text cell: no seat, still addressable
    assert label_cell not in listed
    r = D.read(FX_DOC, "place:%s" % label_cell)
    assert r["ok"] and r["blocks"][0]["text"] == "성명"


def test_a_cell_filled_elsewhere_is_unlisted_but_still_fillable_by_id(no_engine, tmp_path):
    src = _fx_copy(tmp_path)
    pid = D.place_id("cell", "5005", 0, 1)
    out = tmp_path / "filled.hwpx"
    assert D.edit(src, [{"op": "fill", "place": pid, "text": "홍길동"}], base=D.rev_of(src), out=out)["ok"]
    listed = {p["id"]: p for p in D.outline(out)["places"]}
    assert listed[pid]["filled"] is True and listed[pid]["label"] == "성명"     # known: this module filled it
    D._LINEAGE.clear()
    os.environ[D.CACHE_ENV] = str(tmp_path / "fresh-cache")              # another machine: nothing is known
    listed = {p["id"]: p for p in D.outline(out)["places"]}
    assert pid not in listed                                            # without lineage only empty seats
    assert _fx_text(out, "place:%s" % pid) == "홍길동"
    r = D.edit(out, [{"op": "fill", "place": pid, "text": "김철수"}], base=D.rev_of(out),
               out=tmp_path / "again.hwpx")
    assert r["ok"] and _fx_text(r["out"], "t2/r0/c1") == "김철수"


def test_a_known_filled_cell_is_never_a_label(no_engine, tmp_path):
    src = _fx_copy(tmp_path)
    out = tmp_path / "out.hwpx"
    # empty t2/r1/c0 (주소) so that t2/r1/c1 could only be labelled from above, the filled 성명 seat
    r = D.edit(src, [{"op": "fill", "place": D.place_id("cell", "5005", 0, 1), "text": "홍길동"},
                     {"op": "table.set_cells", "at": "t2/r1/c0", "grid": [[""]]}], base=D.rev_of(src), out=out)
    assert r["ok"], r
    places = D.outline(out)["places"]
    assert all(p["label"] != "홍길동" for p in places), places
    seat = next(p for p in places if p["at"] == "t2/r1/c1")         # carried: labelled as when it was blank
    assert seat["label"] == "주소"


class _OutlineEngine:
    """A stub engine: outline(known=...) when `known_ok`, else it rejects the argument."""

    def __init__(self, known_ok):
        self.known_ok, self.seen = known_ok, []

    def call(self, fn, *args, **kw):
        self.seen.append((fn, kw))
        if fn == "pages":
            return {"ok": True, "page_starts": [{"para": 0}], "pages": 1}
        if fn == "outline":
            if not self.known_ok:
                return {"ok": False, "error": {"code": "bad_input", "message": "unexpected keyword 'known'",
                                               "retryable": False}}
            return {"ok": True, "places": [
                {"id": D.place_id("cell", "5005", 0, 1), "at": "t2/r0/c1", "label": "성명", "kind": "cell",
                 "value": "홍길동", "filled": True},
                {"id": "x", "at": "t0/r2/c1", "label": "연락", "kind": "cell"},          # holds a table: dropped
                {"id": "y", "at": "t9/r0/c0", "label": "?", "kind": "cell"}]}            # does not resolve
        if fn == "analyze":
            return {"ok": True, "places": [], "headings": []}
        return {"ok": False, "error": {"code": "capability_unavailable", "message": fn, "retryable": False}}


@pytest.mark.parametrize("known_ok", [True, False])
def test_outline_known_is_feature_detected(no_engine, tmp_path, known_ok):
    src = _fx_copy(tmp_path)
    doc = D._load(src, meta=False)
    D._lineage_put(doc.sha, [{"id": "abc", "at": "t2/r0/c1"}, {"id": "def", "at": "p5"}])
    e = _OutlineEngine(known_ok)
    D._ensure_meta(doc, e)
    assert ("outline", {"known": ["abc", "def"]}) in e.seen               # the lineage ids are passed
    pls = D._places(doc)
    if known_ok:
        assert [p["at"] for p in pls if p["kind"] == "cell"] == ["t2/r0/c1"]     # from the engine's outline
        assert doc.engine_outline is not None
    else:
        assert doc.engine_outline is None and doc.engine_places == []      # today's analyze() path


def test_bottom_heading_is_not_a_finding_on_the_last_page():
    # a short final section ("## 4. 향후 계획" and one bullet) is short because the document ends, not because the
    # page breaks: the same heading on an earlier page, with the text continuing overleaf, is still reported
    bh = {"para": 7, "chain_para": 7, "text": "4. 향후 계획", "kind": "outline", "lines_after": 1}
    one = D._signals([{"page": 1, "bottom_heading": dict(bh)}])
    assert [s for s in one if s["kind"] == "bottom_heading"] == []
    two = D._signals([{"page": 1, "bottom_heading": dict(bh)}, {"page": 2}])
    assert [(s["page"], s["at"], s["lines_after"]) for s in two if s["kind"] == "bottom_heading"] == [(1, "p7", 1)]
    last = D._signals([{"page": 1}, {"page": 2, "bottom_heading": dict(bh)}], pages={2})
    assert [s for s in last if s["kind"] == "bottom_heading"] == []


def _prv(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().startswith("preview/prvimage")]
        return z.read(names[0]) if names else None


def test_preview_edits_are_drafts_and_older_engines_are_asked_without(kit, tmp_path, monkeypatch):
    # a preview copy is never handed to the user: an engine with edit(draft=True) keeps the source's thumbnail
    # there instead of drawing page 1 again; one without the option answers bad_input and is asked again without it
    src = tmp_path / "a.hwpx"
    shutil.copy(FX_DOC, src)
    rev = D.open(str(src))["rev"]
    monkeypatch.setattr(D, "_NO_OPT", set())
    calls = []
    real = D._Engine.call

    def spy(self, fn, *a, **kw):
        if fn == "edit":
            calls.append("draft" in kw)
        return real(self, fn, *a, **kw)
    assert _prv(src) is not None
    with patch.object(D._Engine, "call", spy):
        r = D.edit(str(src), [{"op": "set", "at": "p0", "text": "신청서 양식 (안)"}], base=rev, preview=True)
    assert r.get("ok", True) is not False and Path(r["out"]).exists()
    old_engine = calls == [True, False]
    if not old_engine:                          # the engine took draft: the source's thumbnail, not redrawn
        assert calls == [True] and _prv(r["out"]) == _prv(src)
    else:                                       # an older engine: asked again without draft, once per engine
        assert ((D._ENGINE_KEY or ""), "edit", ("draft",)) in D._NO_OPT
    calls.clear()
    with patch.object(D._Engine, "call", spy):
        b = D.edit(str(src), [{"op": "set", "at": "p0", "text": "신청서 양식 (안)"}], base=rev,
                   out=str(tmp_path / "b.hwpx"))
    assert calls == [False]                     # a real edit is never a draft
    assert _prv(b["out"]) != _prv(src)          # and it draws the changed page 1 into its thumbnail
    if not old_engine:                          # the preview differs from the real output only by that thumbnail
        with zipfile.ZipFile(r["out"]) as za, zipfile.ZipFile(b["out"]) as zb:
            na = [n for n in za.namelist() if not n.lower().startswith("preview/prvimage")]
            assert na == [n for n in zb.namelist() if not n.lower().startswith("preview/prvimage")]
            assert all(za.read(n) == zb.read(n) for n in na if n.lower().endswith(".xml"))


def test_older_engine_without_draft_is_asked_once(kit, tmp_path, monkeypatch):
    src = tmp_path / "a.hwpx"
    shutil.copy(FX_DOC, src)
    rev = D.open(str(src))["rev"]
    monkeypatch.setattr(D, "_NO_OPT", set())
    real, calls = D._Engine.call, []

    def old_engine(self, fn, *a, **kw):
        if fn == "edit":
            calls.append("draft" in kw)
            if "draft" in kw:
                return {"ok": False, "error": {"code": "bad_input", "message": "edit: unknown option(s) draft; "
                                                "options: path, script, out, pdf, pdf_pages, since, layout, page_hash"}}
        return real(self, fn, *a, **kw)
    with patch.object(D._Engine, "call", old_engine):
        for t in ("가", "나"):
            D.edit(str(src), [{"op": "set", "at": "p0", "text": t}], base=rev, preview=True)
    assert calls == [True, False, False]


@pytest.mark.parametrize("scale", [2.0, 1.37])
def test_render_png_through_the_engine_matches_the_pdf_path_pixel_for_pixel(kit, tmp_path, scale):
    PIL = pytest.importorskip("PIL.Image")
    src = shutil.copyfile(FX_DOC, tmp_path / "doc.hwpx")
    a = D.render(str(src), [1], scale=scale, out_dir=str(tmp_path / "a"))
    assert a["via"] == "engine_png"             # the engine has png(): the new path ran, not the fallback twice
    with patch.object(D, "_engine_png", lambda *a_, **k: None):
        b = D.render(str(src), [1], scale=scale, out_dir=str(tmp_path / "b"))
    assert b["via"] == "engine_pdf+pypdfium2"
    pa, pb = a["pages"][0], b["pages"][0]
    assert {k: pa[k] for k in ("n", "width_pt", "height_pt", "px_w", "px_h")} == \
        {k: pb[k] for k in ("n", "width_pt", "height_pt", "px_w", "px_h")}
    ia, ib = PIL.open(pa["file"]).convert("RGB"), PIL.open(pb["file"]).convert("RGB")
    assert ia.size == ib.size and ia.tobytes() == ib.tobytes()


def test_older_engine_png_without_notes_is_asked_once(kit, tmp_path, monkeypatch):
    src = shutil.copyfile(FX_DOC, tmp_path / "doc.hwpx")
    monkeypatch.setattr(D, "_NO_OPT", set())
    real, calls = D._Engine.call, []

    def old_engine(self, fn, *a, **kw):
        if fn == "png":
            calls.append(kw.get("notes"))
            if "notes" in kw:
                return {"ok": False, "error": {"code": "bad_input", "message": "png: unknown option(s) notes; "
                                                "options: hwpx, out_dir, pages, scale"}}
        return real(self, fn, *a, **kw)
    with patch.object(D._Engine, "call", old_engine):
        a = D.render(str(src), [1], out_dir=str(tmp_path / "a"))
        b = D.render(str(src), [1], out_dir=str(tmp_path / "b"))
    assert calls == ["layout", None, None] and a["via"] == b["via"] == "engine_png"


def test_render_and_geometry_of_a_preview_copy_skip_the_form_analysis(kit, tmp_path):
    # render/geometry take page numbers, not addresses: a fresh preview copy is not sent through outline/analyze
    src = shutil.copyfile(FX_DOC, tmp_path / "doc.hwpx")
    rev = D.open(str(src))["rev"]
    r = D.edit(str(src), [{"op": "set", "at": "p0", "text": "신청서 (안)"}], base=rev, preview=True)
    real, calls = D._Engine.call, []

    def spy(self, fn, *a, **kw):
        calls.append(fn)
        return real(self, fn, *a, **kw)
    with patch.object(D._Engine, "call", spy):
        D.render(r["out"], [1])
        D.geometry(r["out"], 1)
    assert "analyze" not in calls and "outline" not in calls
    with patch.object(D._Engine, "call", spy):
        D.read(r["out"])                        # an address-resolving call still loads the form analysis
    assert "analyze" in calls


# ============================================================================ engine results of style and insert_picture
def _png(path, w=40, h=20):
    """A small solid PNG written with the standard library."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x30\x60\x90" * w for _ in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


@engine
def test_engine_style_apply_changes_the_paragraph_style(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    rev = D.rev_of(f)
    text = D.read(f, "p3")["blocks"][0]["text"]
    assert D.read(f, "p3")["blocks"][0]["style"] == "바탕글"
    out = tmp_path / "st.hwpx"
    r = D.edit(f, [{"op": "style", "at": "p3", "style": "개요 1"}], base=rev, out=out)
    assert r["ok"], r
    b = D.read(out, "p3")["blocks"][0]
    assert b["style"] == "개요 1" and b["text"] == text
    assert D.read(out, "p4")["blocks"][0]["style"] == "바탕글"
    assert r["remap"] == []


@engine
def test_engine_insert_picture_adds_a_picture_and_its_image(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    rev = D.rev_of(f)
    img = _png(tmp_path / "fig.png")
    out = tmp_path / "pic.hwpx"
    r = D.edit(f, [{"op": "insert_picture", "at": "p2", "path": str(img), "width_mm": 30}], base=rev, out=out)
    assert r["ok"], r
    with zipfile.ZipFile(f) as z0, zipfile.ZipFile(out) as z:
        before = z0.read("Contents/section0.xml").decode("utf-8").count("<hp:pic ")
        sec = z.read("Contents/section0.xml").decode("utf-8")
        assert sec.count("<hp:pic ") == before + 1
        bins = [n for n in z.namelist() if n.startswith("BinData/")]
        assert any(z.read(n) == img.read_bytes() for n in bins), bins
        # 30 mm wide in HWPUNIT (7200 per inch), the 2:1 image's height kept in proportion
        m = re.findall(r'<hp:pic [^>]*>.*?<hp:orgSz width="(\d+)" height="(\d+)"', sec, re.S)
        assert any(abs(int(w) - 30 * 7200 / 25.4) < 5 and abs(int(w) - 2 * int(h)) < 5 for w, h in m), m


# ============================================================================ 글자 모양 / 문단 모양
def test_shape_ops_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(op):
        return D.edit(src, [op], base=rev, out=out)["error"]
    e = err({"op": "char_shape", "at": "p2", "set": {"bolt": True}})
    assert e["code"] == "bad_input" and "bold" in e["candidates"]
    assert err({"op": "char_shape", "at": "p2", "set": {}})["code"] == "bad_input"
    assert err({"op": "char_shape", "at": "p2", "set": {"size": 0}})["code"] == "bad_input"
    assert err({"op": "char_shape", "at": "p2", "set": {"ratio": 300}})["code"] == "bad_input"
    assert err({"op": "char_shape", "at": "p2", "set": {"color": "red"}})["code"] == "bad_input"
    assert err({"op": "char_shape", "at": "p2", "set": {"bold": 1}})["code"] == "bad_input"
    assert err({"op": "char_shape", "at": "p2", "set": {"sup": True, "sub": True}})["code"] == "bad_input"
    assert err({"op": "para_shape", "at": "p2", "set": {"align": "middle"}})["code"] == "bad_input"
    assert err({"op": "para_shape", "at": "p2", "set": {"line_spacing": {"type": "FIXED"}}})["code"] == "bad_input"
    assert err({"op": "para_shape", "at": "p2:0-3", "set": {"align": "CENTER"}})["code"] == "bad_address"
    text = D.read(src, "p2")["blocks"][0]["text"]
    assert err({"op": "char_shape", "at": "p2", "set": {"bold": True}, "expect": text + "x"})["code"] == \
        "expect_mismatch"
    e = err({"op": "char_shape", "at": "p2", "set": {"bold": True}, "expect": text})
    assert e["code"] == "capability_unavailable"           # valid, but only the engine shapes text
    e = D.edit(src, [{"op": "char_shape", "at": "p2:0-4", "set": {"bold": True}},
                     {"op": "set", "at": "p2:2-6", "text": "x"}], base=rev, out=out)["error"]
    assert e["code"] == "conflict"
    assert not out.exists()


def _char_pr(z, text, near=None):
    """The charPr element of the run that starts with `text` (in the paragraph that holds `near`, when given),
    the paraPr of its paragraph, and the XML from that run on."""
    sec = z.read("Contents/section0.xml").decode("utf-8")
    head = z.read("Contents/header.xml").decode("utf-8")
    lo = 0
    if near:
        at = sec.index(near)
        lo = sec.rindex("<hp:p ", 0, at)
    m = re.compile(r'<hp:run charPrIDRef="(\d+)"[^>]*><hp:t>(?:<hp:markpenBegin[^>]*/>)?'
                   + re.escape(text)).search(sec, lo)
    assert m, text
    cp = re.search(r'<hh:charPr id="%s".*?</hh:charPr>' % m.group(1), head, re.S).group(0)
    pid = re.findall(r'<hp:p [^>]*paraPrIDRef="(\d+)"', sec[:m.start()])[-1]
    pp = re.search(r'<hh:paraPr id="%s".*?</hh:paraPr>' % pid, head, re.S).group(0)
    return cp, pp, sec[m.start():m.start() + 300]


@engine
def test_engine_char_and_para_shape(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    rev = D.rev_of(f)
    text = D.read(f, "p3")["blocks"][0]["text"]
    out = tmp_path / "s.hwpx"
    r = D.edit(f, [
        {"op": "char_shape", "at": "p3:0-4", "set": {"bold": True, "size": 14, "color": "#C00000",
                                                     "markpen": "#FFFF00"}, "expect": text[:4]},
        {"op": "para_shape", "at": "p3", "set": {"align": "center", "before": 6,
                                                 "line_spacing": {"type": "fixed", "value": 20}}},
        {"op": "char_shape", "at": "t0", "set": {"italic": True}},
        {"op": "set", "at": "p3:6-8", "text": "XY"},
    ], base=rev, out=out)
    assert r["ok"], r
    assert r["remap"] == [] and r["changed_pages"]
    assert D.read(out, "p3")["blocks"][0]["text"] == text[:6] + "XY" + text[8:]
    with zipfile.ZipFile(out) as z:
        near = "<hp:markpenBegin"            # the paragraph repeats; the marked copy is p3
        cp, pp, run = _char_pr(z, text[:4], near)
        assert 'height="1400"' in cp and 'textColor="#C00000"' in cp and "<hh:bold/>" in cp
        assert '<hp:markpenBegin color="#FFFF00"/>' + text[:4] + "<hp:markpenEnd/>" in run
        assert 'horizontal="CENTER"' in pp and '<hc:prev value="600"' in pp and 'type="FIXED"' in pp
        rest, _, _ = _char_pr(z, text[4:6], near)
        assert "<hh:bold/>" not in rest and 'height="1400"' not in rest
        cell = D.read(out, "t0/r0/c0")["blocks"][0]["text"]
        if cell:
            assert "<hh:italic/>" in _char_pr(z, cell[:2])[0]
    assert D.rev_of(f) == rev
    # null takes the 형광펜 off again
    rev2 = D.rev_of(out)
    out2 = tmp_path / "s2.hwpx"
    r = D.edit(out, [{"op": "char_shape", "at": "p3:0-4", "set": {"markpen": None}}], base=rev2, out=out2)
    assert r["ok"], r
    with zipfile.ZipFile(out2) as z:
        sec = z.read("Contents/section0.xml").decode("utf-8")
        assert "markpenBegin" not in sec and "markpenEnd" not in sec
        assert 'height="1400"' in _char_pr(z, text[:4], "XY" + text[8:12])[0]


# ============================================================================ 개요 번호 / 문단 번호 / 글머리표
def test_numbering_is_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(op):
        return D.edit(src, [op] if isinstance(op, dict) else op, base=rev, out=out)["error"]
    e = err({"op": "numbering", "at": "p2", "set": {"kind": "roman"}})
    assert e["code"] == "bad_input" and "outline" in e["candidates"]
    assert err({"op": "numbering", "at": "p2"})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "number", "level": 8}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "number", "level": True}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "bullet", "char": "ab"}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "outline", "char": "*"}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "none", "level": 2}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "number", "start": 0}})["code"] == "bad_input"
    assert err({"op": "numbering", "at": "p2", "set": {"kind": "number", "start": 3, "restart": True}})["code"] \
        == "bad_input"
    assert err({"op": "numbering", "at": "p2:0-3", "set": {"kind": "number"}})["code"] == "bad_address"
    e = err([{"op": "numbering", "at": "p2", "set": {"kind": "number"}}, {"op": "style", "at": "p2", "style": "본문"}])
    assert e["code"] == "conflict"


@engine
def test_engine_numbering_sets_the_list_state(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    out, out2 = tmp_path / "n.hwpx", tmp_path / "n2.hwpx"
    texts = {a: D.read(f, a)["blocks"][0]["text"] for a in ("p3", "p4", "p6")}
    r = D.edit(f, [
        {"op": "numbering", "at": "p3", "set": {"kind": "number", "level": 2}},
        {"op": "numbering", "at": "p4", "set": {"kind": "bullet", "char": "■", "level": 3}},
        {"op": "numbering", "at": "p5", "set": {"kind": "outline", "level": 2}},
        {"op": "numbering", "at": "p6", "set": {"kind": "number", "start": 5}},
    ], base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert r["remap"] == []

    def state(path, a):
        d = D._load(path)
        q = D.resolve(d, a)["para"]
        return d.para_heading.get(q.pr, ("NONE", 0)), (d.styles.get(q.style) or {}).get("engName"), q.text
    assert state(out, "p3") == (("NUMBER", 1), "Normal", texts["p3"])     # level 2 = the XML's level 1
    assert state(out, "p4")[0] == ("BULLET", 2)
    assert state(out, "p5")[:2] == (("OUTLINE", 1), "Outline 2")
    assert state(out, "p6")[0] == ("NUMBER", 0) and state(out, "p6")[2] == texts["p6"]
    assert state(out, "p7")[0] == ("NONE", 0)
    with zipfile.ZipFile(out) as z:
        head = z.read("Contents/header.xml").decode("utf-8")
        assert re.search(r'<hh:paraHead start="5" level="1"', head)
        assert "■" in head
    # an op that finds the paragraph already there adds no step; none takes each list off; number -> bullet
    r = D.edit(out, [
        {"op": "numbering", "at": "p3", "set": {"kind": "number", "level": 2}},
        {"op": "numbering", "at": "p4", "set": {"kind": "none"}},
        {"op": "numbering", "at": "p5", "set": {"kind": "none"}},
        {"op": "numbering", "at": "p6", "set": {"kind": "bullet"}},
    ], base=D.rev_of(out), out=out2)
    assert r["ok"], r
    assert state(out2, "p3")[0] == ("NUMBER", 1)
    assert state(out2, "p4")[0][0] == "NONE"
    assert state(out2, "p5")[:2] == (("NONE", 0), "Normal")
    assert state(out2, "p6")[0][0] == "BULLET" and state(out2, "p6")[2] == texts["p6"]

    # outline -> number, and bullet -> number restarted (새 번호로 시작: a numbering of its own from 1)
    out3 = tmp_path / "n3.hwpx"
    r = D.edit(out, [
        {"op": "numbering", "at": "p5", "set": {"kind": "number"}},
        {"op": "numbering", "at": "p4", "set": {"kind": "number", "restart": True}},
    ], base=D.rev_of(out), out=out3)
    assert r["ok"], r
    assert state(out3, "p5")[0][0] == "NUMBER" and state(out3, "p5")[1] != "Outline 2"
    assert state(out3, "p4")[0][0] == "NUMBER"

    def num_ref(path, a):
        d = D._load(path)
        q = D.resolve(d, a)["para"]
        with zipfile.ZipFile(path) as z:
            head = z.read("Contents/header.xml").decode("utf-8")
        pp = re.search(r'<hh:paraPr id="%s".*?</hh:paraPr>' % q.pr, head, re.S).group(0)
        ref = re.search(r'<hh:heading type="NUMBER" idRef="(\d+)"', pp).group(1)
        return ref, re.search(r'<hh:numbering id="%s"[^>]*\bstart="(\d+)"' % ref, head).group(1)
    assert num_ref(out3, "p4")[0] != num_ref(out3, "p5")[0]
    assert num_ref(out3, "p4")[1] == "1"


# ============================================================================ 표 구조: 셀 합치기·나누기, 칸, 크기
def test_table_shape_ops_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(op):
        return D.edit(src, [op] if isinstance(op, dict) else op, base=rev, out=out)["error"]
    assert err({"op": "table.merge", "at": "t5/r4/c0"})["code"] == "bad_input"                 # no to
    assert err({"op": "table.merge", "at": "t5/r4/c0", "to": "t6/r0/c0"})["code"] == "bad_address"
    assert err({"op": "table.merge", "at": "t5", "to": "t5/r1/c0"})["code"] == "bad_address"
    assert err({"op": "table.merge", "at": "t5/r4/c0", "to": "t5/r5/c0"})["code"] == "bad_input"  # one cell
    e = err({"op": "table.merge", "at": "t5/r4/c0", "too": "t5/r4/c1"})
    assert e["code"] == "bad_input" and e["candidates"] == ["to"]
    assert err({"op": "table.split", "at": "t5/r0/c5"})["code"] == "bad_input"               # 1 x 1
    assert err({"op": "table.split", "at": "t5/r0/c5", "cols": 21})["code"] == "bad_input"
    assert err({"op": "table.split", "at": "t5/r0/c5", "rows": True})["code"] == "bad_input"
    e = err({"op": "table.split", "at": "t5/r4/c0", "rows": 2})                                # spans 3 rows
    assert e["code"] == "bad_input" and e["candidates"] == [1, 3]
    assert err({"op": "table.add_col", "at": "t5"})["code"] == "bad_address"                  # no after
    assert err({"op": "table.add_col", "at": "t5", "after": 6})["code"] == "bad_address"
    assert err({"op": "table.add_col", "at": "t5", "after": 0, "like": 2})["code"] == "bad_input"
    assert err({"op": "table.add_col", "at": "t5", "after": 1})["code"] == "bad_address"      # no lone cell
    assert err({"op": "table.delete_col", "at": "t5", "col": 1})["code"] == "bad_address"
    assert err({"op": "table.delete_col", "at": "t0", "col": 0})["code"] == "bad_input"        # one column
    assert err({"op": "table.delete_col", "at": "t5/r0/c5", "expect": "x"})["code"] == "expect_mismatch"
    assert err({"op": "table.size", "at": "t5"})["code"] == "bad_input"
    assert err({"op": "table.size", "at": "t5", "width_mm": 20})["code"] == "bad_address"
    assert err({"op": "table.size", "at": "t5/r4/c1", "width_mm": 20})["code"] == "bad_address"  # spans 2
    assert err({"op": "table.size", "at": "t5/r0/c5", "width_mm": 0})["code"] == "bad_input"
    assert err({"op": "table.size", "at": "t5", "col_widths_mm": [10] * 7})["code"] == "bad_input"
    assert err({"op": "table.size", "at": "t5", "row_heights_mm": [None, "5"]})["code"] == "bad_input"
    assert err({"op": "table.size", "at": "t5/r0/c0:0-2", "height_mm": 5})["code"] == "bad_address"
    e = err({"op": "table.size", "at": "t5/r0/c5", "col_widths_mm": [10]})       # lists go on the table
    assert e["code"] == "bad_address" and e["candidates"] == ["t5"]
    assert err({"op": "table.size", "at": "t5/r1", "row_heights_mm": [10]})["code"] == "bad_address"
    # a shape op owns its table: any other op on it, or a second shape op, is a conflict
    assert err([{"op": "table.size", "at": "t5", "col_widths_mm": [10]},
                {"op": "table.set_cells", "at": "t5/r0/c5", "grid": [["x"]]}])["code"] == "conflict"
    assert err([{"op": "table.split", "at": "t5/r0/c5", "cols": 2},
                {"op": "table.add_row", "at": "t5", "after": 1}])["code"] == "conflict"
    assert err([{"op": "table.size", "at": "t6", "col_widths_mm": [10]},
                {"op": "table.size", "at": "t6", "row_heights_mm": [10]}])["code"] == "conflict"
    # valid, but only the engine changes a table's shape
    assert err({"op": "table.size", "at": "t5/r0/c5", "height_mm": 12})["code"] == "capability_unavailable"
    assert not out.exists()


def test_table_shape_ops_on_an_older_engine_write_nothing(no_engine, tmp_path, monkeypatch):
    """An engine that predates an edit step answers 'unknown hnc_edit operation': the op is unavailable on it
    (engine_function_missing), and nothing is written."""
    class Old:
        def call(self, fn, *a, **k):
            if fn == "edit":
                return {"ok": False, "error": {"code": "bad_input", "step": 1,
                                               "message": "step 1: unknown hnc_edit operation 'merge_cells'"}}
            return {"ok": True, "pages": [], "count": 0}
    monkeypatch.setattr(D, "_engine", lambda: Old())
    src = _copy(GUARD, tmp_path)
    out = tmp_path / "o.hwpx"
    r = D.edit(src, [{"op": "table.merge", "at": "t5/r4/c0", "to": "t5/r4/c1"}], base=D.rev_of(src), out=out)
    e = r["error"]
    assert e["code"] == "capability_unavailable" and e["reason"] == "engine_function_missing", e
    assert e["fn"] == "merge_cells" and e["written"] is False and e["retryable"] is False
    assert not out.exists()


def _cells(path, g=0):
    t = D._load(path).tables[g]
    return sorted((c.row, c.col, c.rs, c.cs) for c in t.cells), t.rows, t.cols


def _tc_xml(z):
    sec = z.read("Contents/section0.xml").decode("utf-8")
    tbl = sec[sec.index("<hp:tbl "):]
    return tbl[:tbl.index("</hp:tbl>")]


@engine
def test_engine_table_merge_and_split(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    texts = {a: D.read(f, a)["blocks"][0]["text"] for a in ("t0/r1/c0", "t0/r1/c1", "t0/r2/c0", "t0/r2/c1")}
    out = tmp_path / "m.hwpx"
    r = D.edit(f, [{"op": "table.merge", "at": "t0/r1/c0", "to": "t0/r2/c1"}], base=D.rev_of(f), out=out)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out)
    assert (rows, cols, len(cells)) == (4, 4, 12) and (1, 0, 2, 2) in cells
    with zipfile.ZipFile(out) as z:
        assert '<hp:cellAddr colAddr="0" rowAddr="1"/><hp:cellSpan colSpan="2" rowSpan="2"/>' in _tc_xml(z)
    assert [b["text"] for b in D.read(out, "t0/r1/c0")["blocks"]] == [
        texts["t0/r1/c0"], texts["t0/r1/c1"], texts["t0/r2/c0"], texts["t0/r2/c1"]]
    remap = {m["from"]: m["to"] for m in r["remap"]}
    assert remap["t0/r1/c1"] is None and remap["t0/r2/c1/p0"] == "t0/r1/c0/p3"
    assert D.follow_remap(r["remap"], "t0/r2/c0/p0") == "t0/r1/c0/p2"
    # 셀 나누기: a 1 x 1 cell into 2 x 2 adds a grid row and a grid column; the cells after them move
    out2 = tmp_path / "s.hwpx"
    r = D.edit(f, [{"op": "table.split", "at": "t0/r1/c1", "rows": 2, "cols": 2}], base=D.rev_of(f), out=out2)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out2)
    assert (rows, cols, len(cells)) == (5, 5, 15 + 3)
    assert {(1, 1, 1, 1), (1, 2, 1, 1), (2, 1, 1, 1), (2, 2, 1, 1), (1, 0, 2, 1), (1, 3, 2, 1)} <= set(cells)
    assert D.read(out2, "t0/r1/c1")["blocks"][0]["text"] == texts["t0/r1/c1"]
    assert D.read(out2, "t0/r2/c2")["blocks"][0]["text"] == ""
    assert D.follow_remap(r["remap"], "t0/r2/c3") == "t0/r3/c4"
    assert D.read(out2, "t0/r3/c4")["blocks"][0]["text"].startswith("R2C3")


@engine
def test_engine_table_columns_and_sizes(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    out = tmp_path / "c.hwpx"
    r = D.edit(f, [{"op": "table.add_col", "at": "t0", "after": 1}], base=D.rev_of(f), out=out)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out)
    assert (rows, cols, len(cells)) == (4, 5, 19) and (0, 0, 1, 2) in cells
    assert D.follow_remap(r["remap"], "t0/r2/c3/p0") == "t0/r2/c4/p0"
    assert D.read(out, "t0/r2/c4")["blocks"][0]["text"].startswith("R2C3")
    assert D.read(out, "t0/r2/c2")["blocks"][0]["text"] == ""
    col = D.read(f, "t0")["blocks"][0]["cells"]
    out2 = tmp_path / "d.hwpx"
    r = D.edit(f, [{"op": "table.delete_col", "at": "t0/r1/c2",
                    "expect": "\n".join(col[k][2] for k in range(4))}], base=D.rev_of(f), out=out2)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out2)
    assert (rows, cols, len(cells)) == (4, 3, 11)
    remap = {m["from"]: m["to"] for m in r["remap"]}
    assert remap["t0/r1/c2"] is None and remap["t0/r1/c3"] == "t0/r1/c2"
    assert "R1C2" not in D.read(out2, "t0")["blocks"][0]["text"]
    # a column inside the merged (0,0) cell (columns 0-1): the merged cell widens, then narrows again
    head = D.read(f, "t0/r0/c0")["blocks"][0]["text"]
    out4, out5 = tmp_path / "w.hwpx", tmp_path / "n.hwpx"
    r = D.edit(f, [{"op": "table.add_col", "at": "t0", "after": 0}], base=D.rev_of(f), out=out4)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out4)
    assert (rows, cols, len(cells)) == (4, 5, 15 + 3) and (0, 0, 1, 3) in cells
    assert D.read(out4, "t0/r0/c0")["blocks"][0]["text"] == head
    assert D.follow_remap(r["remap"], "t0/r0/c2") == "t0/r0/c3"
    assert D.follow_remap(r["remap"], "t0/r1/c1") == "t0/r1/c2"
    r = D.edit(f, [{"op": "table.delete_col", "at": "t0", "col": 0}], base=D.rev_of(f), out=out5)
    assert r["ok"] and not r.get("remap_approx"), r
    cells, rows, cols = _cells(out5)
    assert (rows, cols, len(cells)) == (4, 3, 15 - 3) and (0, 0, 1, 1) in cells
    remap = {m["from"]: m["to"] for m in r["remap"]}
    assert remap["t0/r1/c0"] is None and remap.get("t0/r0/c0", "t0/r0/c0") == "t0/r0/c0"
    assert D.read(out5, "t0/r0/c0")["blocks"][0]["text"] == head
    assert D.follow_remap(r["remap"], "t0/r1/c1") == "t0/r1/c0"
    # 셀 크기: grid column widths and one row's height, in HWPUNIT (7200 per inch)
    out3 = tmp_path / "z.hwpx"
    r = D.edit(f, [{"op": "table.size", "at": "t0", "col_widths_mm": [20, None, 30], "row_heights_mm": [None, 15]}],
               base=D.rev_of(f), out=out3)
    assert r["ok"] and r["remap"] == [] and not r.get("remap_approx"), r
    hu = lambda mm: int(round(mm * 7200 / 25.4))       # noqa: E731
    with zipfile.ZipFile(f) as z0, zipfile.ZipFile(out3) as z:
        before, after = _tc_xml(z0), _tc_xml(z)

    def size(xml, row, col):
        m = re.search(r'<hp:cellAddr colAddr="%d" rowAddr="%d"/><hp:cellSpan [^>]*/><hp:cellSz width="(\d+)" '
                      r'height="(\d+)"' % (col, row), xml)
        return int(m.group(1)), int(m.group(2))
    assert size(after, 1, 0)[0] == hu(20) and size(after, 1, 2)[0] == hu(30)
    assert size(after, 1, 1)[0] == size(before, 1, 1)[0]
    assert size(after, 0, 0)[0] == hu(20) + size(before, 1, 1)[0]       # the merged cell spans columns 0 and 1
    assert size(after, 1, 3)[1] == hu(15) and size(after, 0, 2)[1] == size(before, 0, 2)[1]
    assert D.read(out3, "t0")["blocks"][0]["cells"] == D.read(f, "t0")["blocks"][0]["cells"]


# ============================================================================ 편집 용지 / 다단 / 쪽·단·구역 나누기
SECTIONS3 = REPO / "tests" / "corpus" / "render-check" / "render-check-01.hwpx"     # 3 sections: p0, p100, p102


def test_page_ops_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(ops, f=src, base=None):
        ops = [ops] if isinstance(ops, dict) else ops
        return D.edit(f, ops, base=base or rev, out=out)["error"]
    e = err({"op": "page_setup", "at": "p0", "set": {"papre": "A4"}})
    assert e["code"] == "bad_input" and "paper" in e["candidates"]
    assert err({"op": "page_setup", "at": "p0", "set": {}})["code"] == "bad_input"
    e = err({"op": "page_setup", "at": "p0", "set": {"paper": "A6"}})
    assert e["code"] == "bad_input" and "A4" in e["candidates"]
    assert err({"op": "page_setup", "at": "p0", "set": {"paper": "A4", "width_mm": 200}})["code"] == "bad_input"
    assert err({"op": "page_setup", "at": "p0", "set": {"height_mm": 20}})["code"] == "bad_input"
    assert err({"op": "page_setup", "at": "p0", "set": {"landscape": "yes"}})["code"] == "bad_input"
    assert err({"op": "page_setup", "at": "p0", "set": {"width_mm": True}})["code"] == "bad_input"
    # margins that leave no room on the paper are refused, with the paper of this op or of the section
    e = err({"op": "page_setup", "at": "p0", "set": {"paper": "A5", "margins": {"left": 80, "right": 70}}})
    assert e["code"] == "bad_input" and "across" in e["message"]
    e = err({"op": "page_setup", "at": "p0", "set": {"margins": {"top": 150, "bottom": 150}}})
    assert e["code"] == "bad_input" and "down" in e["message"]
    e = err({"op": "page_setup", "at": "p0", "set": {"paper": "A4", "landscape": True,
                                                    "margins": {"top": 100, "bottom": 100}}})
    assert e["code"] == "bad_input" and "down" in e["message"]     # landscape A4 is 210 mm down
    e = err({"op": "page_setup", "at": "p0", "set": {"margins": {"lefft": 20}}})
    assert e["code"] == "bad_input" and "left" in e["candidates"]
    assert err({"op": "page_setup", "at": "p0", "set": {"margins": {"top": 501}}})["code"] == "bad_input"
    assert err({"op": "page_setup", "at": "p0", "set": {"gutter_type": "RIGHT"}})["code"] == "bad_input"
    assert err({"op": "page_setup", "at": "p0", "set": {"paper": "A4"}, "expect": "x"})["code"] == "bad_input"
    assert err({"op": "columns", "at": "p0", "set": {"gap_mm": 5}})["code"] == "bad_input"
    assert err({"op": "columns", "at": "p0", "set": {"count": 0}})["code"] == "bad_input"
    assert err({"op": "columns", "at": "p0", "set": {"count": 2, "gap_mm": 101}})["code"] == "bad_input"
    assert err({"op": "columns", "at": "p0", "set": {"count": 2, "line": "SOLID"}})["code"] == "bad_input"
    assert err({"op": "columns", "at": "p0", "set": {"count": 2, "kind": "magazine"}})["code"] == "bad_input"
    e = err({"op": "break", "at": "p3", "kind": "line"})
    assert e["code"] == "bad_input" and "page" in e["candidates"]
    assert err({"op": "break", "at": "p3:0-2", "kind": "page"})["code"] == "bad_address"
    assert err({"op": "break", "at": "t0/r0/c0", "kind": "page"})["code"] == "bad_address"
    assert err({"op": "break", "at": "p3", "kind": "page", "expect": "아님"})["code"] == "expect_mismatch"
    # one owner per section setting, one section break per edit, nothing else on what a section break moves
    assert err([{"op": "page_setup", "at": "p0", "set": {"paper": "A4"}},
                {"op": "page_setup", "at": "p5", "set": {"landscape": True}}])["code"] == "conflict"
    assert err([{"op": "columns", "at": "p0", "set": {"count": 2}},
                {"op": "break", "at": "p9", "kind": "section"}])["code"] == "conflict"
    assert err([{"op": "break", "at": "p9", "kind": "section"},
                {"op": "break", "at": "p20", "kind": "section"}])["code"] == "conflict"
    assert err([{"op": "break", "at": "p9", "kind": "section"},
                {"op": "set", "at": "p30", "text": "x"}])["code"] == "conflict"
    assert err([{"op": "break", "at": "p9", "kind": "page"},
                {"op": "break", "at": "p9", "kind": "column"}])["code"] == "conflict"
    # the engine puts a new section after the last one, so a section break goes in the last section
    many = _copy(SECTIONS3, tmp_path)
    e = err({"op": "break", "at": "p5", "kind": "section"}, f=many, base=D.rev_of(many))
    assert e["code"] == "bad_address" and "last section" in e["message"]
    assert err({"op": "break", "at": "p102", "kind": "section"}, f=many, base=D.rev_of(many))["code"] == \
        "bad_address"                                              # it starts its section already
    e = err({"op": "page_setup", "at": "p0", "set": {"paper": "A4"}})
    assert e["code"] == "capability_unavailable"                   # valid, but only the engine does it
    assert not out.exists()


def _hu(mm):
    return int(mm * 7200 / 25.4)


@engine
def test_engine_page_setup_columns_and_breaks(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    out = tmp_path / "pg.hwpx"
    r = D.edit(f, [
        {"op": "page_setup", "at": "p0", "set": {"paper": "B5", "landscape": True, "gutter_type": "left_right",
                                                "margins": {"left": 25, "right": 20, "header": 12, "gutter": 5}}},
        {"op": "columns", "at": "p2", "set": {"count": 2, "gap_mm": 8, "line": True}},
        {"op": "break", "at": "p3", "kind": "page"},
        {"op": "break", "at": "p4", "kind": "column"},
    ], base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert r["remap"] == [] and not r.get("remap_approx")
    with zipfile.ZipFile(f) as z0, zipfile.ZipFile(out) as z:
        s0 = z0.read("Contents/section0.xml").decode("utf-8")
        sec = z.read("Contents/section0.xml").decode("utf-8")
    pp = re.search(r"<hp:pagePr [^>]*>", sec).group(0)
    assert 'landscape="NARROWLY"' in pp and 'gutterType="LEFT_RIGHT"' in pp
    assert 'width="%d"' % _hu(182) in pp and 'height="%d"' % _hu(257) in pp
    mg = re.search(r"<hp:margin [^>]*/>", sec).group(0)
    for k, v in (("left", 25), ("right", 20), ("header", 12), ("gutter", 5)):
        assert '%s="%d"' % (k, _hu(v)) in mg, (k, mg)
    old = re.search(r"<hp:margin [^>]*/>", s0).group(0)            # the margins not named stay as they were
    for k in ("top", "bottom", "footer"):
        assert re.search(r'\b%s="\d+"' % k, old).group(0) in mg
    col = re.search(r"<hp:colPr [^>]*>(?:<hp:colLine [^>]*/>)?", sec).group(0)
    assert 'colCount="2"' in col and 'sameGap="%d"' % _hu(8) in col and "<hp:colLine " in col
    d = D._load(out)
    heads = {a: d.top[int(a[1:])].head for a in ("p3", "p4", "p5")}
    assert 'pageBreak="1"' in heads["p3"] and 'columnBreak="1"' in heads["p4"]
    assert 'pageBreak="1"' not in heads["p5"] and 'columnBreak="1"' not in heads["p5"]
    assert [q.text for q in d.top] == [q.text for q in D._load(f).top]
    # set and break on one paragraph in one edit: both land
    out2 = tmp_path / "pg2.hwpx"
    r = D.edit(f, [{"op": "set", "at": "p3", "text": "새 쪽의 첫 문단"}, {"op": "break", "at": "p3", "kind": "page"}],
               base=D.rev_of(f), out=out2)
    assert r["ok"], r
    d = D._load(out2)
    assert d.top[3].text == "새 쪽의 첫 문단" and 'pageBreak="1"' in d.top[3].head


@engine
def test_engine_landscape_page_is_drawn_wide(kit, tmp_path):
    pytest.importorskip("pypdfium2")
    f = _copy(kit / "tests" / "features" / "feat_paragraphs.hwpx", tmp_path)
    out = tmp_path / "land.hwpx"
    r = D.edit(f, [{"op": "page_setup", "at": "p0", "set": {"paper": "A4", "landscape": True}}],
               base=D.rev_of(f), out=out)
    assert r["ok"], r
    before = D.render(f, [1], scale=0.5, out_dir=tmp_path / "a")["pages"][0]
    after = D.render(out, [1], scale=0.5, out_dir=tmp_path / "b")["pages"][0]
    assert before["width_pt"] < before["height_pt"]
    assert after["width_pt"] > after["height_pt"] and after["px_w"] > after["px_h"]
    assert abs(after["width_pt"] - before["height_pt"]) < 1 and abs(after["height_pt"] - before["width_pt"]) < 1


@engine
def test_engine_section_break_moves_the_rest_into_a_new_section(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    base = D._load(f)
    assert len(base.secs) == 1
    out = tmp_path / "sec.hwpx"
    r = D.edit(f, [
        {"op": "break", "at": "p6", "kind": "section", "expect": base.top[6].text},
        {"op": "set", "at": "p2", "text": "앞"},
        {"op": "insert_after", "at": "p5", "text": "새 문단"},
    ], base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert not r.get("remap_approx")
    assert {m["from"]: m["to"] for m in r["remap"]}["p6"] == "p7"
    with zipfile.ZipFile(out) as z:
        assert "Contents/section1.xml" in z.namelist()
        assert "section1.xml" in z.read("Contents/content.hpf").decode("utf-8")
        s1 = z.read("Contents/section1.xml").decode("utf-8")
    assert s1.count("<hp:secPr") == 1
    d = D._load(out)
    assert len(d.secs) == 2
    assert [q.si for q in d.top] == [0] * 7 + [1] * (len(base.top) - 6)
    assert [q.text for q in d.top if q.si == 1] == [q.text for q in base.top[6:]]
    assert d.top[6].text == "새 문단" and d.top[2].text == "앞"


# ============================================================================ 머리말·꼬리말, 쪽 번호
def test_header_ops_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(ops, f=src, base=None):
        ops = [ops] if isinstance(ops, dict) else ops
        return D.edit(f, ops, base=base or rev, out=out)["error"]
    e = err({"op": "header", "at": "p0", "txt": "x"})
    assert e["code"] == "bad_input" and "text" in e["candidates"]
    assert err({"op": "header", "at": "p0"})["code"] == "bad_input"                          # no text
    e = err({"op": "header", "at": "p0", "kind": "top", "text": "x"})
    assert e["code"] == "bad_input" and "HEADER" in e["candidates"]
    e = err({"op": "header", "at": "p0", "apply": "all", "text": "x"})
    assert e["code"] == "bad_input" and "BOTH" in e["candidates"]
    assert err({"op": "header", "at": "p0", "text": 3})["code"] == "bad_input"
    assert err({"op": "header", "at": "p0", "text": "a\x01b"})["code"] == "bad_input"
    assert err({"op": "header", "at": "p0", "text": "가" * 1001})["code"] == "bad_input"
    assert err({"op": "header", "at": "p0:0-2", "text": "x"})["code"] == "bad_address"
    assert err({"op": "header", "at": "t0/r0/c0/p0", "text": "x"})["code"] == "bad_address"
    assert err({"op": "header", "at": "p0", "text": "x", "expect": "있는 머리말"})["code"] == "expect_mismatch"
    e = err({"op": "page_number", "at": "p0", "pos": "middle"})
    assert e["code"] == "bad_input" and "BOTTOM_CENTER" in e["candidates"]
    assert err({"op": "page_number", "at": "p0", "format": "arabic"})["code"] == "bad_input"
    assert err({"op": "page_number", "at": "p0", "side_char": "--"})["code"] == "bad_input"
    assert err({"op": "page_number", "at": "p0", "expect": "1"})["code"] == "bad_input"     # no expect
    # one header per section, kind and apply; one page_number per section; none beside a section break there
    two = [{"op": "header", "at": "p0", "text": "a"}, {"op": "header", "at": "p3", "text": "b"}]
    assert err(two)["code"] == "conflict"
    assert err([{"op": "header", "at": "p0", "text": "a"},
                {"op": "header", "at": "p3", "kind": "footer", "text": "b"},
                {"op": "header", "at": "p4", "apply": "odd", "text": "c"}])["code"] == "capability_unavailable"
    assert err([{"op": "page_number", "at": "p0"}, {"op": "page_number", "at": "p9"}])["code"] == "conflict"
    sec3 = _copy(SECTIONS3, tmp_path)
    e = err([{"op": "page_number", "at": "p103"}, {"op": "break", "at": "p104", "kind": "section"}],
            f=sec3, base=D.rev_of(sec3))
    assert e["code"] == "conflict"
    e = err({"op": "header", "at": "p0", "text": "a"}, f=sec3, base=D.rev_of(sec3))
    assert e["code"] == "capability_unavailable" and e["reason"] == "engine_needs_style"    # no 머리말 style
    e = err({"op": "header", "at": "p0", "text": "a"})
    assert e["code"] == "capability_unavailable"                   # valid, but only the engine writes it
    assert e["reason"] != "engine_needs_style"
    assert not out.exists()


def test_header_ops_on_an_engine_without_replace_write_nothing(no_engine, tmp_path, monkeypatch):
    """An engine from before hwp-engine #23 has insert_header without replace=: the op is unavailable on it,
    names the engine it needs, and nothing is written."""
    class Old:
        def call(self, fn, *a, **k):
            if fn == "edit":
                return {"ok": False, "error": {"code": "bad_input", "step": 1, "message":
                        "step 1 (insert_header): TypeError: EditOps.insert_header() got an unexpected keyword "
                        "argument 'replace'"}}
            return {"ok": True, "pages": [], "count": 0}
    monkeypatch.setattr(D, "_engine", lambda: Old())
    src = _copy(GUARD, tmp_path)
    out = tmp_path / "o.hwpx"
    r = D.edit(src, [{"op": "header", "at": "p0", "text": "머리말"}], base=D.rev_of(src), out=out)
    e = r["error"]
    assert e["code"] == "capability_unavailable" and e["reason"] == "engine_function_missing", e
    assert e["fn"] == "insert_header" and e["keyword"] == "replace" and "2077774" in e["needs"]
    assert e["written"] is False and e["retryable"] is False
    assert not out.exists()


def _hf_xml(path, si=0):
    with zipfile.ZipFile(path) as z:
        return z.read("Contents/section%d.xml" % si).decode("utf-8")


@engine
def test_engine_header_footer_and_page_number(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_header_footer.hwpx", tmp_path)
    base = D._load(f)
    old = [q.text for _t, ps in D._hf_controls(base, base.top[0], "header", "BOTH") for q in ps]
    assert old == ["머리말: 2학년 탐구 보고서"]
    out = tmp_path / "hf.hwpx"
    r = D.edit(f, [
        {"op": "header", "at": "p0", "text": "보고서 머리말\n둘째 줄", "expect": old[0]},
        {"op": "header", "at": "p1", "kind": "footer", "apply": "odd", "text": "홀수 쪽 꼬리말"},
        {"op": "page_number", "at": "p0", "pos": "top_right", "format": "roman_small", "side_char": ""},
        {"op": "set", "at": "p0", "text": "첫 문단"},
    ], base=D.rev_of(f), out=out)
    assert r["ok"] and not r.get("remap_approx"), r
    assert r["remap"] == []
    sec = _hf_xml(out)
    assert len(re.findall(r'<hp:header id="\d+" applyPageType="BOTH"', sec)) == 1          # replaced, not added
    assert len(re.findall(r'<hp:footer id="\d+" applyPageType="BOTH"', sec)) == 1          # the old footer kept
    assert len(re.findall(r'<hp:footer id="\d+" applyPageType="ODD"', sec)) == 1
    pn = re.findall(r"<hp:pageNum\b[^>]*>", sec)
    assert pn == ['<hp:pageNum pos="TOP_RIGHT" formatType="ROMAN_SMALL" sideChar=""/>']
    d = D._load(out)
    assert [q.text for _t, ps in D._hf_controls(d, d.top[0], "header", "BOTH") for q in ps] == ["보고서 머리말", "둘째 줄"]
    assert [q.text for _t, ps in D._hf_controls(d, d.top[0], "footer", "ODD") for q in ps] == ["홀수 쪽 꼬리말"]
    assert d.top[0].text == "첫 문단" and [q.text for q in d.top[1:]] == [q.text for q in base.top[1:]]
    # a document without the 머리말 style: the engine cannot write one there, so nothing is written
    nohdr = _copy(SECTIONS3, tmp_path)
    e = D.edit(nohdr, [{"op": "header", "at": "p0", "text": "x"}], base=D.rev_of(nohdr), out=tmp_path / "n.hwpx")
    assert e["error"]["code"] == "capability_unavailable" and e["error"]["reason"] == "engine_needs_style"
    assert not (tmp_path / "n.hwpx").exists()
    # again: still one of each, with the new text
    out2 = tmp_path / "hf2.hwpx"
    r = D.edit(out, [{"op": "header", "at": "p0", "text": "다시", "expect": "보고서 머리말\n둘째 줄"},
                     {"op": "page_number", "at": "p0"}], base=D.rev_of(out), out=out2)
    assert r["ok"], r
    sec = _hf_xml(out2)
    assert len(re.findall(r'<hp:header id="\d+" applyPageType="BOTH"', sec)) == 1 and ">다시<" in sec
    assert re.findall(r"<hp:pageNum\b[^>]*>", sec) == ['<hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/>']


@engine
def test_engine_header_goes_in_the_paragraphs_section(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_page_setup.hwpx", tmp_path)          # 2 sections
    base = D._load(f)
    out = tmp_path / "s.hwpx"
    p = next(q for q in base.top if q.si == 1)
    r = D.edit(f, [{"op": "header", "at": "p%d" % p.gp, "text": "둘째 구역 머리말"}], base=D.rev_of(f), out=out)
    assert r["ok"] and not r.get("remap_approx"), r
    assert ">둘째 구역 머리말<" in _hf_xml(out, 1) and ">둘째 구역 머리말<" not in _hf_xml(out, 0)
    d = D._load(out)
    assert [q.text for q in d.top] == [q.text for q in base.top]
    # a header and a section break in the same section, in one edit: a conflict, nothing written
    out2 = tmp_path / "s2.hwpx"
    e = D.edit(f, [{"op": "header", "at": "p13", "kind": "footer", "text": "x"},
                   {"op": "break", "at": "p15", "kind": "section"}], base=D.rev_of(f), out=out2)["error"]
    assert e["code"] == "conflict" and not out2.exists()


# ============================================================================ 표·셀 꾸미기: 테두리, 배경, 정렬, 여백, 제목 줄
def test_table_style_ops_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(op):
        return D.edit(src, [op] if isinstance(op, dict) else op, base=rev, out=out)["error"]
    cs = "table.cell_style"
    e = err({"op": cs, "at": "t5/r0"})
    assert e["code"] == "bad_input" and "fill" in e["candidates"]                          # no set
    e = err({"op": cs, "at": "t5/r0", "set": {"colour": "#FF0000"}})
    assert e["code"] == "bad_input" and "fill" in e["candidates"]
    assert err({"op": cs, "at": "t5/r0", "set": {"fill": "grey"}})["code"] == "bad_input"
    e = err({"op": cs, "at": "t5/r0", "set": {"valign": "MIDDLE"}})
    assert e["code"] == "bad_input" and e["candidates"] == ["TOP", "CENTER", "BOTTOM"]
    assert err({"op": cs, "at": "t5/r0", "set": {"margin_mm": 51}})["code"] == "bad_input"
    assert err({"op": cs, "at": "t5/r0", "set": {"margin_mm": {"inner": 1}}})["code"] == "bad_input"
    assert err({"op": cs, "at": "t5/r0", "set": {"header": 1}})["code"] == "bad_input"
    e = err({"op": cs, "at": "t5/r0", "set": {"border": {"width": 0.33}}})
    assert e["code"] == "bad_input" and 0.3 in e["candidates"]                             # Hancom's widths only
    e = err({"op": cs, "at": "t5/r0", "set": {"border": {"type": "THIN"}}})
    assert e["code"] == "bad_input" and "THICK_SLIM" in e["candidates"]           # nearest names first
    assert err({"op": cs, "at": "t5/r0", "set": {"border": {"color": "black"}}})["code"] == "bad_input"
    assert err({"op": cs, "at": "t5/r0", "set": {"border": {"all": "none", "width": 1}}})["code"] == "bad_input"
    assert err({"op": cs, "at": "t5/r0", "to": "t5/r1/c0", "set": {"fill": "#FFFFFF"}})["code"] == "bad_input"
    assert err({"op": cs, "at": "t5/r0/c0", "to": "t6/r1/c0", "set": {"fill": "#FFFFFF"}})["code"] == \
        "bad_address"
    assert err({"op": cs, "at": "t5/r0", "expect": "x", "set": {"fill": "#FFFFFF"}})["code"] == "bad_input"
    assert err({"op": cs, "at": "p2", "set": {"fill": "#FFFFFF"}})["code"] == "bad_address"
    e = err({"op": "table.style", "at": "t5", "set": {"repeat_header": "yes"}})
    assert e["code"] == "bad_input"
    e = err({"op": "table.style", "at": "t5", "set": {"page_break": "ROW"}})
    assert e["code"] == "bad_input" and e["candidates"] == ["CELL", "TABLE", "NONE"]
    assert err({"op": "table.style", "at": "t5/r0", "set": {"repeat_header": True}})["code"] == "bad_address"
    # conflicts: overlapping blocks; touching blocks when one sets a border; a row added in the same table;
    # a shape op on the table; two table.style ops
    fill = {"fill": "#EEEEEE"}
    line = {"border": {"type": "SOLID"}}
    assert err([{"op": cs, "at": "t5/r1", "set": fill},
                {"op": cs, "at": "t5/r1/c0", "to": "t5/r2/c0", "set": fill}])["code"] == "conflict"
    assert err([{"op": cs, "at": "t5/r1", "set": line}, {"op": cs, "at": "t5/r2", "set": fill}])["code"] == \
        "conflict"
    assert err([{"op": cs, "at": "t5/r1", "set": fill},
                {"op": "table.add_row", "at": "t5", "after": 3}])["code"] == "conflict"
    assert err([{"op": "table.style", "at": "t5", "set": {"repeat_header": True}},
                {"op": "table.add_row", "at": "t5", "after": 3}])["code"] == "conflict"
    assert err([{"op": "table.size", "at": "t5", "row_heights_mm": [10]},
                {"op": cs, "at": "t5/r1", "set": fill}])["code"] == "conflict"
    assert err([{"op": "table.style", "at": "t5", "set": {"repeat_header": True}},
                {"op": "table.style", "at": "t5", "set": {"page_break": "TABLE"}}])["code"] == "conflict"
    # valid, but only the engine styles a table
    e = err([{"op": cs, "at": "t5/r1", "set": fill}, {"op": cs, "at": "t5/r3", "set": line},
             {"op": "table.style", "at": "t5", "set": {"repeat_header": True}},
             {"op": "table.set_cells", "at": "t5/r2/c0", "grid": [["x"]]}])
    assert e["code"] == "capability_unavailable"
    assert not out.exists()


def _cells_xml(z, k=0):
    """(tbl open tag, [(row, col, tc open tag, subList open tag, cellMargin tag)]) of the k-th table, and the
    header XML."""
    sec = z.read("Contents/section0.xml").decode("utf-8")
    head = z.read("Contents/header.xml").decode("utf-8")
    a = [m.start() for m in re.finditer("<hp:tbl ", sec)][k]
    t = sec[a:sec.index("</hp:tbl>", a)]          # a table with no table inside it
    assert "<hp:tbl " not in t[1:]
    open_ = t[:t.index(">") + 1]
    cells = []
    for m in re.finditer(r'(<hp:tc [^>]*>).*?(<hp:subList [^>]*>)', t, re.S):
        body = t[m.start():t.index("</hp:tc>", m.start())]
        addr = re.search(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"', body)
        mg = re.search(r"<hp:cellMargin [^>]*>", body)
        cells.append((int(addr.group(2)), int(addr.group(1)), m.group(1), m.group(2), mg.group(0) if mg else ""))
    return open_, cells, head


def _border_fill(head, tc):
    i = re.search(r'borderFillIDRef="(\d+)"', tc).group(1)
    bf = re.search(r'<hh:borderFill id="%s".*?</hh:borderFill>' % i, head, re.S).group(0)
    sides = {m.group(1): (m.group(2), m.group(3), m.group(4))
             for m in re.finditer(r'<hh:(\w+)Border type="(\w+)" width="([^"]+)" color="([^"]+)"', bf)}
    face = re.search(r'faceColor="([^"]+)"', bf)
    return sides, face.group(1) if face else None


def test_style_create_is_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(GUARD, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(ops):
        return D.edit(src, ops if isinstance(ops, list) else [ops], base=rev, out=out)["error"]
    sc = "style.create"
    assert err({"op": sc})["code"] == "bad_input"                                          # no name
    for bad in ("", " 본문2", "a\tb", "x" * 65, "12"):
        assert err({"op": sc, "name": bad})["code"] == "bad_input", bad
    for taken in ("본문", "Body"):                          # a name or an English name the document has
        e = err({"op": sc, "name": taken})
        assert e["code"] == "bad_input" and "already has" in e["message"], taken
    assert err({"op": sc, "name": "새 스타일", "eng_name": "Outline 1"})["code"] == "bad_input"
    e = err({"op": sc, "name": "새 스타일", "based_on": "개요1"})
    assert e["code"] == "bad_input" and "개요 1" in e["candidates"]
    e = err({"op": sc, "name": "새 스타일", "char": {"colour": "#FF0000"}})
    assert e["code"] == "bad_input" and "color" in e["candidates"]
    assert "markpen" in err({"op": sc, "name": "새 스타일", "char": {"markpen": "#FFFF00"}})["message"]
    assert err({"op": sc, "name": "새 스타일", "char": {"size": 0}})["code"] == "bad_input"
    assert err({"op": sc, "name": "새 스타일", "para": {"align": "MIDDLE"}})["code"] == "bad_input"
    assert err({"op": sc, "name": "새 스타일", "kind": "char", "para": {"align": "LEFT"}})["code"] == "bad_input"
    assert err({"op": sc, "name": "새 스타일", "kind": "table"})["code"] == "bad_input"
    e = err({"op": sc, "name": "새 스타일", "at": "p1"})
    assert e["code"] == "bad_input" and "no at" in e["message"]
    e = err({"op": sc, "name": "새 스타일", "expect": "x"})
    assert e["code"] == "bad_input" and "expect" in e["message"]
    e = err({"op": sc, "name": "새 스타일", "base": "본문"})
    assert e["code"] == "bad_input" and "based_on" in e["candidates"]
    # two ops that make one style, by name or English name
    assert err([{"op": sc, "name": "새 스타일"}, {"op": sc, "name": "새 스타일"}])["code"] == "conflict"
    assert err([{"op": sc, "name": "가", "eng_name": "Alpha"}, {"op": sc, "name": "Alpha"}])["code"] == "conflict"
    # a style op of the same edit cannot use the new style yet: it is applied in a later edit
    e = err([{"op": sc, "name": "새 스타일"}, {"op": "style", "at": "p1", "style": "새 스타일"}])
    assert e["code"] == "bad_input" and e["i"] == 1 and "later edit" in e["message"]
    # a well-formed op needs the engine: the built-in path has no 스타일 추가
    e = err({"op": sc, "name": "새 스타일", "char": {"bold": True}, "para": {"align": "CENTER"}})
    assert e["code"] == "capability_unavailable"
    assert not out.exists()


@engine
def test_engine_style_create_writes_the_style(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    out = tmp_path / "sc.hwpx"
    before = [b["text"] for b in D.read(f)["blocks"] if b.get("text") is not None]
    r = D.edit(f, [
        {"op": "style.create", "name": "보고서 본문", "eng_name": "Report Body", "based_on": "바탕글",
         "char": {"size": 11.5, "bold": True, "color": "#1F3864"}, "para": {"align": "center", "before": 4}},
        {"op": "style.create", "name": "강조", "kind": "char", "char": {"italic": True}},
    ], base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert r["remap"] == [] and not r.get("remap_approx")
    assert [b["text"] for b in D.read(out)["blocks"] if b.get("text") is not None] == before
    with zipfile.ZipFile(out) as z:
        head = z.read("Contents/header.xml").decode("utf-8")
    body = re.search(r'<hh:style [^>]*name="보고서 본문"[^>]*/>', head).group(0)
    assert 'type="PARA"' in body and 'engName="Report Body"' in body
    cp = re.search(r'<hh:charPr id="%s"[^>]*>.*?</hh:charPr>' % re.search(r'charPrIDRef="(\d+)"', body).group(1),
                   head, re.S).group(0)
    assert 'height="1150"' in cp and 'textColor="#1F3864"' in cp and "<hh:bold/>" in cp
    pp = re.search(r'<hh:paraPr id="%s"[^>]*>.*?</hh:paraPr>' % re.search(r'paraPrIDRef="(\d+)"', body).group(1),
                   head, re.S).group(0)
    assert '<hh:align horizontal="CENTER"' in pp
    em = re.search(r'<hh:style [^>]*name="강조"[^>]*/>', head).group(0)
    assert 'type="CHAR"' in em
    cp2 = re.search(r'<hh:charPr id="%s"[^>]*>.*?</hh:charPr>' % re.search(r'charPrIDRef="(\d+)"', em).group(1),
                    head, re.S).group(0)
    assert "<hh:italic/>" in cp2
    # the check reads the values back: an output without them is not taken for done
    base, got = D._load(f, meta=False), D._load(out, meta=False)
    acts = D._plan(base, [{"op": "style.create", "name": "보고서 본문", "eng_name": "Report Body",
                           "char": {"size": 11.5, "bold": True}, "para": {"align": "CENTER"}},
                          {"op": "style.create", "name": "강조", "kind": "char", "char": {"italic": True}}])
    assert D._verify_styles(base, got, acts)
    acts[0].new_style["char"]["size"] = 12.0
    assert not D._verify_styles(base, got, acts)
    acts[0].new_style["char"]["size"] = 11.5
    acts[1].new_style["char"]["italic"] = False
    assert not D._verify_styles(base, got, acts)
    # the new styles are the document's own from here on: a later edit applies them
    out2 = tmp_path / "sc2.hwpx"
    r = D.edit(out, [{"op": "style", "at": "p3", "style": "보고서 본문"},
                     {"op": "style.create", "name": "보고서 본문"}], base=D.rev_of(out), out=out2)
    assert r["error"]["code"] == "bad_input" and r["error"]["i"] == 1          # the name is taken now
    r = D.edit(out, [{"op": "style", "at": "p3", "style": "보고서 본문"}], base=D.rev_of(out), out=out2)
    assert r["ok"], r
    assert D.read(out2, "p3")["blocks"][0]["style"] == "보고서 본문"


@engine
def test_engine_table_cell_and_table_style(kit, tmp_path):
    f = _copy(kit / "tests" / "features" / "feat_tables.hwpx", tmp_path)
    out = tmp_path / "st.hwpx"
    before = D.read(f, "t0")["blocks"][0]
    r = D.edit(f, [
        {"op": "table.cell_style", "at": "t0/r0", "set": {
            "fill": "#D9D9D9", "valign": "top", "header": True,
            "border": {"bottom": {"type": "DOUBLE_SLIM", "width": 0.5, "color": "#1F3864"}}}},
        {"op": "table.cell_style", "at": "t0/r2/c0", "to": "t0/r3/c1", "set": {"margin_mm": 2}},
        {"op": "table.cell_style", "at": "t0/r2/c3", "set": {"border": "none", "valign": "BOTTOM"}},
        {"op": "table.style", "at": "t0", "set": {"repeat_header": True, "page_break": "TABLE"}},
        {"op": "table.set_cells", "at": "t0/r1/c0", "grid": [["값"]]},
    ], base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert r["remap"] == [] and not r.get("remap_approx")
    after = D.read(out, "t0")["blocks"][0]
    assert after["cells"][1][0] == "값" and after["cells"][0] == before["cells"][0]
    with zipfile.ZipFile(out) as z:
        open_, cells, head = _cells_xml(z)
    assert 'repeatHeader="1"' in open_ and 'pageBreak="TABLE"' in open_
    by = {(rr, cc): (tc, sub, mg) for rr, cc, tc, sub, mg in cells}
    for (rr, cc), (tc, sub, mg) in by.items():
        sides, face = _border_fill(head, tc)
        if rr == 0:             # 제목 줄: header cells, gray, top-aligned, a double line under them
            assert 'header="1"' in tc and 'vertAlign="TOP"' in sub and face == "#D9D9D9"
            assert sides["bottom"] == ("DOUBLE_SLIM", "0.5 mm", "#1F3864")
        else:
            assert 'header="0"' in tc
        if rr == 1 and (0, cc) in by and (1, cc) in by:
            assert sides["top"] == ("DOUBLE_SLIM", "0.5 mm", "#1F3864")     # the shared edge, as Hancom
        if rr in (2, 3) and cc in (0, 1):
            assert 'hasMargin="1"' in tc and 'left="566"' in mg and 'top="566"' in mg   # 2 mm in HWPUNIT
        if (rr, cc) == (2, 3):
            assert all(v[0] == "NONE" for v in sides.values()) and 'vertAlign="BOTTOM"' in sub
    # repeat_header off again; nothing else changes
    out2 = tmp_path / "st2.hwpx"
    r = D.edit(out, [{"op": "table.style", "at": "t0", "set": {"repeat_header": False}}],
               base=D.rev_of(out), out=out2)
    assert r["ok"], r
    with zipfile.ZipFile(out2) as z:
        open2, cells2, _ = _cells_xml(z)
    assert 'repeatHeader="0"' in open2 and 'pageBreak="TABLE"' in open2
    assert [c[2] for c in cells2] == [c[2] for c in cells]


# ============================================================================ 각주·미주 (note), 표 캡션 (caption)
BASIC = REPO / "tests" / "fixtures" / "rt_doc_contract" / "basic.hwpx"


def test_note_and_caption_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(BASIC, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(ops):
        return D.edit(src, ops if isinstance(ops, list) else [ops], base=rev, out=out)["error"]

    # note: fields, kind, text bounds, address, expect, after
    e = err({"op": "note", "at": "p1", "txt": "x"})
    assert e["code"] == "bad_input" and "text" in e["candidates"]
    assert err({"op": "note", "at": "p1"})["code"] == "bad_input"
    e = err({"op": "note", "at": "p1", "kind": "side", "text": "x"})
    assert e["code"] == "bad_input" and "FOOT" in e["candidates"] and "END" in e["candidates"]
    for bad_text in ("", "   ", 123, "a\x01b", "가" * 2001):
        assert err({"op": "note", "at": "p1", "text": bad_text})["code"] == "bad_input", bad_text
    assert err({"op": "note", "at": "p1:0-3", "text": "x"})["code"] == "bad_address"
    assert err({"op": "note", "at": "t0", "text": "x"})["code"] == "bad_address"
    assert err({"op": "note", "at": "p99", "text": "x"})["code"] == "bad_address"
    assert err({"op": "note", "at": "p1", "text": "x", "expect": "다른 문장"})["code"] == "expect_mismatch"
    for bad_after in ("", 12, "a\nb", "a\x01b"):
        assert err({"op": "note", "at": "p1", "text": "x", "after": bad_after})["code"] == "bad_input", bad_after
    e = err({"op": "note", "at": "p1", "text": "x", "after": "2027년"})
    assert e["code"] == "bad_input" and e.get("candidates")
    e = err({"op": "note", "at": "p4", "text": "x", "after": "11월"})
    assert e["code"] == "bad_input" and len(e.get("candidates") or []) >= 2
    assert err({"op": "note", "at": "p4", "text": "x", "after": e["candidates"][0]})["code"] == "capability_unavailable"

    # caption: fields, side, text bounds, table address
    e = err({"op": "caption", "at": "t0", "txt": "x"})
    assert e["code"] == "bad_input" and "text" in e["candidates"]
    assert err({"op": "caption", "at": "t0"})["code"] == "bad_input"
    assert err({"op": "caption", "at": "t0", "text": "x", "expect": "x"})["code"] == "bad_input"
    e = err({"op": "caption", "at": "t0", "side": "middle", "text": "x"})
    assert e["code"] == "bad_input" and "BOTTOM" in e["candidates"]
    for bad_text in ("", "   ", 123, "첫 줄\n둘째 줄", "a\x01b", "가" * 501):
        assert err({"op": "caption", "at": "t0", "text": bad_text})["code"] == "bad_input", bad_text
    e = err({"op": "caption", "at": "t9", "text": "x"})
    assert e["code"] == "bad_address" and "t0" in e["candidates"]
    assert err({"op": "caption", "at": "p1", "text": "x"})["code"] == "bad_address"
    assert err({"op": "caption", "at": "t0/r0/c0", "text": "x"})["code"] == "bad_address"

    # conflicts: two ops on the same target, or with delete / text / shape ops on that target
    assert err([{"op": "note", "at": "p1", "text": "가"},
                {"op": "note", "at": "p1", "kind": "end", "after": "2026년", "text": "나"}])["code"] == "conflict"
    assert err([{"op": "note", "at": "p1", "text": "가"},
                {"op": "delete", "at": "p1"}])["code"] == "conflict"
    assert err([{"op": "delete", "at": "p1"},
                {"op": "note", "at": "p1", "text": "가"}])["code"] == "conflict"
    assert err([{"op": "note", "at": "p1", "text": "가"},
                {"op": "set", "at": "p1", "text": "나"}])["code"] == "conflict"
    assert err([{"op": "note", "at": "t0/r0/c0/p0", "text": "가"},
                {"op": "delete", "at": "t0"}])["code"] == "conflict"
    assert err([{"op": "caption", "at": "t0", "text": "가"},
                {"op": "caption", "at": "t0", "side": "top", "text": "나"}])["code"] == "conflict"
    assert err([{"op": "caption", "at": "t0", "text": "가"},
                {"op": "delete", "at": "t0"}])["code"] == "conflict"
    assert err([{"op": "delete", "at": "t0"},
                {"op": "caption", "at": "t0", "text": "가"}])["code"] == "conflict"
    assert err([{"op": "caption", "at": "t0", "text": "가"},
                {"op": "delete", "at": "p5"}])["code"] == "conflict"
    assert err([{"op": "caption", "at": "t0", "text": "가"},
                {"op": "table.add_row", "at": "t0", "after": 0}])["code"] == "conflict"
    assert err([{"op": "caption", "at": "t0", "text": "가"},
                {"op": "table.style", "at": "t0", "set": {"repeat_header": True}}])["code"] == "conflict"

    # valid ops without engine: capability_unavailable and nothing written
    e = err([{"op": "note", "at": "p1", "after": "2026년", "text": "각주"},
             {"op": "caption", "at": "t0", "side": "top", "text": "표 제목"}])
    assert e["code"] == "capability_unavailable"
    assert not out.exists()

    # follow-up c: style.create of 각주/미주/캡션 together with a note/caption that needs it in the same edit
    for sname, eng, op2 in (
        ("각주", None, {"op": "note", "at": "p1", "text": "가"}),
        ("내각주", "Footnote", {"op": "note", "at": "p1", "text": "가"}),
        ("미주", None, {"op": "note", "at": "p1", "kind": "end", "text": "가"}),
        ("내미주", "Endnote", {"op": "note", "at": "p1", "kind": "end", "text": "가"}),
        ("캡션", None, {"op": "caption", "at": "t0", "text": "가"}),
        ("내캡션", "Caption", {"op": "caption", "at": "t0", "text": "가"}),
    ):
        sc = {"op": "style.create", "name": sname, **({"eng_name": eng} if eng else {})}
        assert err([sc, op2])["code"] == "conflict", (sname, eng)
        assert err([op2, sc])["code"] == "conflict", (sname, eng)


@engine
def test_engine_note_and_caption(tmp_path, monkeypatch):
    f = _copy(BASIC, tmp_path)
    base = D._load(f, meta=False)
    out = tmp_path / "nc.hwpx"
    ops = [
        {"op": "note", "at": "p1", "after": "2026년 3월", "text": "각주 설명",
         "expect": "본 사업은 2026년 3월에 시작한다."},
        {"op": "note", "at": "p2", "kind": "end", "text": "미주 첫줄\n미주 둘째줄"},
        {"op": "caption", "at": "t0", "side": "top", "text": "예산 현황"},
    ]
    r = D.edit(f, ops, base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert r["remap"] == [] and not r.get("remap_approx")
    for idx, want_style in ((0, "각주 (Footnote)"), (1, "미주 (Endnote)"), (2, "캡션 (Caption)")):
        assert any(want_style in w for w in (r["applied"][idx].get("warnings") or [])), r["applied"][idx]
    got = D._load(out, meta=False)
    assert [p.text for p in got.top] == [p.text for p in base.top]
    assert D._notes_in(got, 0, "footNote", got.top[1]) == ["각주 설명"]
    assert D._notes_in(got, 0, "endNote", got.top[2]) == ["미주 첫줄\n미주 둘째줄"]
    assert D._table_captions(got, got.tables[0]) == [("TOP", "1", "표 ", " 예산 현황")]

    # a second caption on a table that now has one is refused with bad_input
    out2 = tmp_path / "nc2.hwpx"
    e = D.edit(out, [{"op": "caption", "at": "t0", "text": "두 번째 캡션"}],
               base=D.rev_of(out), out=out2)["error"]
    assert e["code"] == "bad_input" and "already has a caption" in e["message"]
    assert not out2.exists()

    # verifier refuses hand-broken outputs (wrong note text, wrong caption side/text, altered body text, missing auto style)
    acts = D._plan(base, ops)
    assert D._verify(base, got, acts)
    raw_sec = got.zip.read("Contents/section0.xml").decode("utf-8")
    for broken_xml in (
        raw_sec.replace("각주 설명", "다른 각주"),
        raw_sec.replace('side="TOP"', 'side="BOTTOM"'),
        raw_sec.replace("예산 현황", "다른 캡션"),
        raw_sec.replace("세부 계획", "바뀐 본문"),
    ):
        broken_bytes = got.zip.rewrite({"Contents/section0.xml": broken_xml.encode("utf-8")})
        broken_doc = D.Doc(out, broken_bytes, "hwpx")
        assert not D._verify(base, broken_doc, acts)
    raw_hdr = got.zip.read("Contents/header.xml").decode("utf-8")
    broken_hdr_doc = D.Doc(out, got.zip.rewrite({
        "Contents/header.xml": raw_hdr.replace('name="각주"', 'name="다른각주"').encode("utf-8")}), "hwpx")
    assert not D._verify_styles(base, broken_hdr_doc, acts)
    assert not D._verify(base, broken_hdr_doc, acts)

    # end-to-end: if the engine produces a broken output, edit fails and nothing is written
    bad_bytes = got.zip.rewrite({"Contents/section0.xml": raw_sec.replace("각주 설명", "깨진 각주").encode("utf-8")})
    monkeypatch.setattr(D, "_engine_apply", lambda *a, **k: (bad_bytes, {}, None))
    out_bad = tmp_path / "bad.hwpx"
    res_bad = D.edit(f, ops, base=D.rev_of(f), out=out_bad)
    assert not res_bad["ok"] and res_bad["error"]["code"] == "internal"
    assert res_bad["error"]["written"] is False and not out_bad.exists()


# ============================================================================ 책갈피 (bookmark), 하이퍼링크 (link), 차례 (toc)
def test_bookmark_link_and_toc_are_checked_before_anything_runs(no_engine, tmp_path):
    src = _copy(BASIC, tmp_path)
    rev, out = D.rev_of(src), tmp_path / "o.hwpx"

    def err(ops, doc_path=src, base_rev=None):
        return D.edit(doc_path, ops if isinstance(ops, list) else [ops],
                      base=base_rev or rev, out=out)["error"]

    # bookmark: fields, name bounds, address, expect, after
    e = err({"op": "bookmark", "at": "p1", "nm": "앞"})
    assert e["code"] == "bad_input" and "name" in e["candidates"]
    assert err({"op": "bookmark", "at": "p1"})["code"] == "bad_input"
    assert err({"op": "bookmark", "at": "p1", "name": "앞", "expect": "x"})["code"] == "bad_input"
    for bad_name in ("", "   ", " 앞", "앞 ", 123, "a\nb", "a\tb", "a\x01b", "가" * 65):
        assert err({"op": "bookmark", "at": "p1", "name": bad_name})["code"] == "bad_input", bad_name
    assert err({"op": "bookmark", "at": "p1:0-3", "name": "앞"})["code"] == "bad_address"
    assert err({"op": "bookmark", "at": "t0", "name": "앞"})["code"] == "bad_address"
    assert err({"op": "bookmark", "at": "p99", "name": "앞"})["code"] == "bad_address"
    for bad_after in ("", 12, "a\nb", "a\x01b"):
        assert err({"op": "bookmark", "at": "p1", "name": "앞", "after": bad_after})["code"] == "bad_input", bad_after
    e = err({"op": "bookmark", "at": "p1", "name": "앞", "after": "2027년"})
    assert e["code"] == "bad_input" and e.get("candidates")
    e = err({"op": "bookmark", "at": "p4", "name": "앞", "after": "11월"})
    assert e["code"] == "bad_input" and len(e.get("candidates") or []) >= 2

    # duplicate bookmark name: in the same edit, or already in the document
    assert err([{"op": "bookmark", "at": "p1", "name": "앞"},
                {"op": "bookmark", "at": "p2", "name": "앞"}])["code"] == "bad_input"
    base_doc = D._load(src, meta=False)
    sec_with_bm = base_doc.secs[0].replace(
        "<hp:t>사업 개요</hp:t>", '<hp:t>사업 개요</hp:t><hp:ctrl><hp:bookmark name="기존"/></hp:ctrl>', 1)
    has_bm = tmp_path / "has_bm.hwpx"
    has_bm.write_bytes(base_doc.zip.rewrite({"Contents/section0.xml": sec_with_bm.encode("utf-8")}))
    assert err({"op": "bookmark", "at": "p1", "name": "기존"},
               doc_path=has_bm, base_rev=D.rev_of(has_bm))["code"] == "bad_input"

    # link: fields, phrase not found or ambiguous, bad target, unknown bookmark target
    e = err({"op": "link", "at": "p1", "phrase": "2026년", "url": "https://www.hancom.com"})
    assert e["code"] == "bad_input" and "target" in e["candidates"]
    assert err({"op": "link", "at": "p1", "phrase": "2026년"})["code"] == "bad_input"
    assert err({"op": "link", "at": "p1", "phrase": "2026년", "target": "https://www.hancom.com",
                "expect": "x"})["code"] == "bad_input"
    assert err({"op": "link", "at": "p1:0-3", "phrase": "본", "target": "https://www.hancom.com"})["code"] \
        == "bad_address"
    assert err({"op": "link", "at": "t0", "phrase": "항목", "target": "https://www.hancom.com"})["code"] \
        == "bad_address"
    for bad_phrase in ("", 12, "a\nb", "a\x01b"):
        assert err({"op": "link", "at": "p1", "phrase": bad_phrase,
                    "target": "https://www.hancom.com"})["code"] == "bad_input", bad_phrase
    e = err({"op": "link", "at": "p1", "phrase": "2027년", "target": "https://www.hancom.com"})
    assert e["code"] == "bad_input" and e.get("candidates")
    e = err({"op": "link", "at": "p4", "phrase": "11월", "target": "https://www.hancom.com"})
    assert e["code"] == "bad_input" and len(e.get("candidates") or []) >= 2
    for bad_target in ("", "   ", 123, "http://", "https://", "mailto:", "mailto:user", "ftp://example.com/a",
                       "javascript:alert(1)", "file:///etc/passwd", "www.hancom.com", "https://example.com/a b",
                       "#", "#없는책갈피", "https://example.com/\x01"):
        assert err({"op": "link", "at": "p1", "phrase": "2026년",
                    "target": bad_target})["code"] == "bad_input", bad_target
    # bookmark created later in the same edit is not yet available to an earlier link
    assert err([{"op": "link", "at": "p2", "phrase": "메타데이터", "target": "#나중"},
                {"op": "bookmark", "at": "p1", "name": "나중"}])["code"] == "bad_input"

    # toc: fields, levels, leader, address, second toc, document that already has a TABLEOFCONTENTS field
    e = err({"op": "toc", "at": "p0", "level": 2})
    assert e["code"] == "bad_input" and "levels" in e["candidates"]
    assert err({"op": "toc", "at": "p0", "expect": "사업 개요"})["code"] == "bad_input"
    for bad_levels in (0, 4, -1, True, "2", 1.5):
        assert err({"op": "toc", "at": "p0", "levels": bad_levels})["code"] == "bad_input", bad_levels
    e = err({"op": "toc", "at": "p0", "leader": "wave"})
    assert e["code"] == "bad_input" and "DASH" in e["candidates"] and "DOT" in e["candidates"]
    assert err({"op": "toc", "at": "p0:0-2"})["code"] == "bad_address"
    assert err({"op": "toc", "at": "t0"})["code"] == "bad_address"
    assert err({"op": "toc", "at": "t0/r0/c0"})["code"] == "bad_address"
    assert err({"op": "toc", "at": "t0/r0/c0/p0"})["code"] == "bad_address"
    assert err([{"op": "toc", "at": "p0"}, {"op": "toc", "at": "p3"}])["code"] == "bad_input"
    sec_with_toc = base_doc.secs[0].replace(
        "<hp:t>사업 개요</hp:t>",
        '<hp:ctrl><hp:fieldBegin id="99" type="TABLEOFCONTENTS" name="" editable="1" dirty="0" '
        'zorder="-1" fieldid="628387683"/></hp:ctrl><hp:t>사업 개요</hp:t>'
        '<hp:ctrl><hp:fieldEnd beginIDRef="99" fieldid="628387683"/></hp:ctrl>', 1)
    has_toc = tmp_path / "has_toc.hwpx"
    has_toc.write_bytes(base_doc.zip.rewrite({"Contents/section0.xml": sec_with_toc.encode("utf-8")}))
    assert err({"op": "toc", "at": "p0"}, doc_path=has_toc, base_rev=D.rev_of(has_toc))["code"] == "bad_input"

    # conflicts: two ops on the same target, delete of target, text edit with bookmark/link/toc, toc auto-style
    assert err([{"op": "bookmark", "at": "p1", "name": "가"},
                {"op": "bookmark", "at": "p1", "after": "2026년", "name": "나"}])["code"] == "conflict"
    assert err([{"op": "link", "at": "p1", "phrase": "사업", "target": "https://www.hancom.com"},
                {"op": "link", "at": "p1", "phrase": "2026년", "target": "mailto:a@b.kr"}])["code"] == "conflict"
    assert err([{"op": "bookmark", "at": "p1", "name": "가"},
                {"op": "link", "at": "p1", "phrase": "2026년", "target": "#가"}])["code"] == "conflict"
    assert err([{"op": "bookmark", "at": "p1", "name": "가"},
                {"op": "delete", "at": "p1"}])["code"] == "conflict"
    assert err([{"op": "link", "at": "p1", "phrase": "2026년", "target": "https://www.hancom.com"},
                {"op": "delete", "at": "p1"}])["code"] == "conflict"
    assert err([{"op": "toc", "at": "p0"},
                {"op": "delete", "at": "p0"}])["code"] == "conflict"
    assert err([{"op": "toc", "at": "p0"},
                {"op": "toc", "at": "p0"}])["code"] == "conflict"
    assert err([{"op": "toc", "at": "p0"},
                {"op": "insert_after", "at": "p0", "markdown": "추가"}])["code"] == "conflict"
    assert err([{"op": "bookmark", "at": "p1", "name": "가"},
                {"op": "set", "at": "p1", "text": "나"}])["code"] == "conflict"
    assert err([{"op": "link", "at": "p1", "phrase": "2026년", "target": "https://www.hancom.com"},
                {"op": "replace", "at": "p1", "find": "3월", "with": "4월"}])["code"] == "conflict"
    assert err([{"op": "bookmark", "at": "t0/r0/c0/p0", "name": "가"},
                {"op": "delete", "at": "t0"}])["code"] == "conflict"
    assert err([{"op": "style.create", "name": "차례 제목"},
                {"op": "toc", "at": "p0"}])["code"] == "conflict"

    # valid ops without engine: capability_unavailable and nothing written
    e = err([{"op": "bookmark", "at": "p1", "after": "2026년 3월", "name": "시작"},
             {"op": "link", "at": "p2", "phrase": "보존 포맷 메타데이터", "target": "#시작"},
             {"op": "link", "at": "p4", "phrase": "11월 18일", "target": "https://www.hancom.com"},
             {"op": "toc", "at": "p0", "levels": 2, "leader": "dot"}])
    assert e["code"] == "capability_unavailable"
    assert not out.exists()


@engine
def test_engine_bookmark_link_and_toc(tmp_path, monkeypatch):
    f = _copy(BASIC, tmp_path)
    base = D._load(f, meta=False)
    out = tmp_path / "blt.hwpx"
    ops = [
        {"op": "bookmark", "at": "p1", "after": "2026년 3월", "name": "시작"},
        {"op": "bookmark", "at": "p7", "name": "회신"},
        {"op": "link", "at": "p2", "phrase": "보존 포맷 메타데이터", "target": "#시작"},
        {"op": "link", "at": "p4", "phrase": "11월 18일", "target": "https://www.hancom.com"},
        {"op": "toc", "at": "p0", "levels": 2, "leader": "dot"},
    ]
    r = D.edit(f, ops, base=D.rev_of(f), out=out)
    assert r["ok"], r
    assert not r.get("remap_approx")
    # toc after p0 adds 5 paragraphs (<제목 차례>, 3 outline headings up to level 2, closing fieldEnd paragraph)
    assert r["remap"] == [{"from": "p%d" % k, "to": "p%d" % (k + 5)} for k in range(1, len(base.top))]
    # follow-up a warning is present on the op that triggered _auto_styles
    toc_applied = next(a for a in r["applied"] if a["op"] == "toc")
    assert any("차례 제목 (TOC Heading)" in w for w in (toc_applied.get("warnings") or [])), toc_applied

    got = D._load(out, meta=False)
    assert len(got.top) == len(base.top) + 5
    assert got.top[0].text == base.top[0].text
    assert [p.text for p in got.top[6:]] == [p.text for p in base.top[1:]]
    assert got.top[1].text == "<제목 차례>"
    assert D._bookmarks_in(got, 0, got.top[6], with_before=True) == [("시작", "본 사업은 2026년 3월")]
    assert D._bookmarks_in(got, 0, got.top[12], with_before=True) == [("회신", base.top[7].text)]
    assert D._links_in(got.top[7]) == [("?시작;0;0;0;", "보존 포맷 메타데이터")]
    assert D._links_in(got.top[9]) == [("https://www.hancom.com;1;0;0;", "11월 18일")]
    assert len(D._toc_fields(got)) == 1

    # duplicate bookmark name or a second toc on the edited document is refused with bad_input
    out2 = tmp_path / "blt2.hwpx"
    e = D.edit(out, [{"op": "bookmark", "at": "p6", "name": "시작"}], base=D.rev_of(out), out=out2)["error"]
    assert e["code"] == "bad_input"
    e = D.edit(out, [{"op": "toc", "at": "p0"}], base=D.rev_of(out), out=out2)["error"]
    assert e["code"] == "bad_input"
    assert not out2.exists()

    # verifiers refuse hand-broken outputs for bookmark, link and toc
    acts = D._plan(base, ops)
    assert D._verify(base, got, acts)
    raw_sec = got.zip.read("Contents/section0.xml").decode("utf-8")
    for broken_xml in (
        raw_sec.replace('name="시작"', 'name="다른이름"'),
        raw_sec.replace("?시작;0;0;0;", "?없는이름;0;0;0;"),
        raw_sec.replace("보존 포맷 메타데이터", "바뀐 링크 문구"),
        raw_sec.replace("https://www.hancom.com;1;0;0;", "https://example.org;1;0;0;"),
        raw_sec.replace('type="TABLEOFCONTENTS"', 'type="CLICK_HERE"'),
        raw_sec.replace("ContentsLevel:int:2", "ContentsLevel:int:3"),
        raw_sec.replace("세부 계획", "바뀐 본문 제목"),
    ):
        broken_bytes = got.zip.rewrite({"Contents/section0.xml": broken_xml.encode("utf-8")})
        broken_doc = D.Doc(out, broken_bytes, "hwpx")
        assert not D._verify(base, broken_doc, acts)

    # end-to-end: if the engine produces a broken bookmark/link/toc output, edit fails and nothing is written
    bad_bytes = got.zip.rewrite({"Contents/section0.xml": raw_sec.replace('name="시작"', 'name="깨짐"').encode("utf-8")})
    monkeypatch.setattr(D, "_engine_apply", lambda *a, **k: (bad_bytes, {}, None))
    out_bad = tmp_path / "bad_blt.hwpx"
    res_bad = D.edit(f, ops, base=D.rev_of(f), out=out_bad)
    assert not res_bad["ok"] and res_bad["error"]["code"] == "internal"
    assert res_bad["error"]["written"] is False and not out_bad.exists()
