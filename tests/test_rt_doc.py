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
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

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
    assert {"id": "취업장소", "at": "t5/r13/c2", "label": "2. 취업 장소", "kind": "cell", "value": "",
            "filled": False} in ol["places"]


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
    e = D.read(GUARD, "place:취업장")["error"]
    assert e["code"] == "bad_address" and "place:취업장소" in e["candidates"]
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
        {"op": "fill", "place": "근로자Worker", "text": "홍길동"},
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
    seat = next(p["at"] for p in D.outline(src)["places"] if p["id"] == "근로자Worker")
    assert D.read(out, seat)["blocks"][0]["text"] == "홍길동"
    filled = {p["id"]: p for p in D.outline(out)["places"]}["근로자Worker"]    # a filled seat keeps its id
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
