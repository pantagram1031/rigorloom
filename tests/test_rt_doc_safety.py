# -*- coding: utf-8 -*-
"""doc_core safety: regression tests for the review of PR #388 (review-388.md).

Each test turns one finding's reproduction into an assertion of the behaviour
we want (B = blocker, S = should-fix). Built-in tests run everywhere; engine
tests run when ``RIGORLOOM_HWP_ENGINE`` points at an engine folder.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import textwrap
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_doc as D  # noqa: E402

GUARD = REPO / "examples" / "guard" / "before.hwpx"
REPORT = REPO / "tests" / "corpus" / "forms" / "converted" / "nrf-gyeolgwa-bogoseo-yangsik.hwpx"
SECTION = "Contents/section0.xml"
ENGINE_DIR = os.environ.get("RIGORLOOM_HWP_ENGINE", "").strip()
HAS_ENGINE = bool(ENGINE_DIR) and (Path(ENGINE_DIR) / "kit_api.py").is_file()
E = Path(ENGINE_DIR) if HAS_ENGINE else None
engine = pytest.mark.skipif(not HAS_ENGINE, reason="RIGORLOOM_HWP_ENGINE is not set to an engine")


@pytest.fixture(autouse=True)
def _private_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv(D.CACHE_ENV, str(tmp_path_factory.mktemp("doc-cache")))
    D._LINEAGE.clear()


@pytest.fixture
def no_engine(monkeypatch):
    D.close()
    monkeypatch.delenv(D.ENGINE_ENV, raising=False)
    monkeypatch.setattr(D, "_engine_dir", lambda env=None: (None, "engine_not_configured"))
    yield
    D.close()


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    import runpy
    D.close()
    old = os.environ.get("FONTCONFIG_FILE")
    try:
        fams = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    except OSError:
        fams = ""
    if "함초롬바탕" not in fams:
        helpers = runpy.run_path(str(REPO / "tests" / "test_rt_doc.py"))
        os.environ["FONTCONFIG_FILE"] = str(helpers["_standin_fonts"](tmp_path_factory.mktemp("fonts")))
    yield E
    D.close()
    if old is None:
        os.environ.pop("FONTCONFIG_FILE", None)
    else:
        os.environ["FONTCONFIG_FILE"] = old


# ============================================================================ document builders
def _mini_section():
    """A one-paragraph section built from GUARD's own section properties (like the engine's blank_a4)."""
    with zipfile.ZipFile(GUARD) as z:
        s = z.read(SECTION).decode("utf-8")
    root = s[:s.index(">", s.index("<hs:sec")) + 1]
    a = s.index("<hp:secPr ")
    secpr = s[a:s.index("</hp:secPr>", a) + len("</hp:secPr>")]
    col = re.search(r"<hp:ctrl><hp:colPr[^>]*/></hp:ctrl>", s).group(0)
    return (root + '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            '<hp:run charPrIDRef="0">' + secpr + col + "</hp:run></hp:p></hs:sec>")


def rewrite(work, name, change, src=None, extra=None, section=None):
    src = src or GUARD
    out = work / name
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out, "w") as b:
        for info in a.infolist():
            data = a.read(info)
            if info.filename == SECTION:
                data = change(section if section is not None else data.decode()).encode()
            b.writestr(info, data)
        if extra:
            extra(b)
    return out


LSEG = ('<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" '
        'spacing="600" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>')


def para(value, i, lseg=False):
    return (f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0"><hp:t>{value}</hp:t></hp:run>{LSEG if lseg else ""}</hp:p>')


def make(work, name, first, *rest, lseg=False):
    def change(xml):
        end = xml.index("</hp:p>") + len("</hp:p>")
        p0 = xml[:end].replace("</hp:run>", f"<hp:t>{first}</hp:t></hp:run>", 1)
        return p0 + "".join(para(v, i, lseg) for i, v in enumerate(rest, 1)) + xml[end:]
    if HAS_ENGINE:
        return rewrite(work, name, change, src=E / "forms" / "blank_a4.hwpx")
    return rewrite(work, name, change, section=_mini_section())


def set_(at, value, **kw):
    return dict(op="set", at=at, text=value, **kw)


def replacement(find, value, **kw):
    return {"op": "replace", "find": find, "with": value, **kw}


def apply(src, ops, out):
    return D.edit(src, ops, base=D.rev_of(src), out=out)


def texts(src):
    r = D.read(src)
    assert r["ok"], r
    return [b["text"] for b in r["blocks"] if b["kind"] != "table"]


def text(src, at):
    r = D.read(src, at)
    assert r["ok"], r
    return r["blocks"][0]["text"]


def follow(remap, at):
    return D.follow_remap(remap, at)


def leftovers(folder):
    return sorted(p.name for p in Path(folder).iterdir() if p.name.startswith(".rtdoc-") or "rtdoc-lock" in p.name)


# ============================================================================ B1 concurrency / rev
def test_b1_two_in_place_edits_from_one_base_one_is_stale(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "abcdef", "next")
    base = D.rev_of(src)
    gate = threading.Barrier(2)
    results = {}
    real = D._before_publish

    def staged(dest):
        gate.wait(5)            # both edits have planned and staged from the same base
        real(dest)

    def run(i, value):
        results[i] = D.edit(src, [set_("p%d" % i, value)], base=base, in_place=True)

    with patch.object(D, "_before_publish", side_effect=staged):
        ts = [threading.Thread(target=run, args=x) for x in [(0, "winner"), (1, "second")]]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    oks = sorted(r["ok"] for r in results.values())
    assert oks == [False, True], results
    loser = next(r for r in results.values() if not r["ok"])
    assert loser["error"]["code"] == "stale" and loser["error"]["retryable"] is True
    winner = next(r for r in results.values() if r["ok"])
    assert D.rev_of(src) == winner["rev"]
    assert texts(src) in (["winner", "next"], ["abcdef", "second"])
    assert leftovers(tmp_path) == []


def test_b1_read_rev_matches_the_bytes_it_parsed(no_engine, tmp_path):
    src = make(tmp_path, "s.hwpx", "first")
    other = make(tmp_path, "o.hwpx", "second")
    real = D._read_bytes
    calls = []

    def swap(p):
        data = real(p)
        if not calls:               # the file is replaced right after it was read
            calls.append(1)
            shutil.copyfile(other, src)
        return data
    first_rev = D.rev_of(src)
    with patch.object(D, "_read_bytes", side_effect=swap):
        r = D.read(src)
    assert r["ok"], r
    assert r["rev"] == first_rev and r["blocks"][0]["text"] == "first"


def test_b1_lock_file_held_by_another_process_gives_busy(no_engine, tmp_path, monkeypatch):
    src = make(tmp_path, "s.hwpx", "abc")
    monkeypatch.setenv(D.LOCK_TIMEOUT_ENV, "0.3")
    lock = D._lock_path(src)
    lock.write_text("4242 other-host")
    r = D.edit(src, [set_("p0", "x")], base=D.rev_of(src), in_place=True)
    assert r["error"]["code"] == "busy" and r["error"]["retryable"] is True
    assert text(src, "p0") == "abc"
    old = time.time() - D.LOCK_STALE_S - 5          # a crashed holder's lock is broken
    os.utime(lock, (old, old))
    r = D.edit(src, [set_("p0", "x")], base=D.rev_of(src), in_place=True)
    assert r["ok"], r
    assert not lock.exists() and leftovers(tmp_path) == []


# ============================================================================ B2 output aliasing
def test_b2_outputs_that_alias_the_input_are_refused(no_engine, tmp_path):
    src = make(tmp_path, "input.hwpx", "abc")
    before = src.read_bytes()
    hard = tmp_path / "hard.hwpx"
    os.link(src, hard)
    soft = tmp_path / "soft.hwpx"
    soft.symlink_to(src)
    base = D.rev_of(src)
    for out in (hard, soft, tmp_path / "." / "input.hwpx"):
        r = D.edit(src, [set_("p0", "x")], base=base, out=out)
        assert r["error"]["code"] == "bad_input", (out, r)
        r = D.convert(src, out, to="hwpx")
        assert r["error"]["code"] == "bad_input", (out, r)
    assert src.read_bytes() == before
    dangling = tmp_path / "dangling.hwpx"
    dangling.symlink_to(tmp_path / "elsewhere.hwpx")
    assert D.edit(src, [set_("p0", "x")], base=base, out=dangling)["error"]["code"] == "bad_input"
    assert not (tmp_path / "elsewhere.hwpx").exists()


@engine
def test_b2_engine_writes_never_go_through_an_alias(kit, tmp_path):
    src = tmp_path / "input.hwpx"
    shutil.copyfile(kit / "tests" / "features" / "feat_paragraphs.hwpx", src)
    before = src.read_bytes()
    alias = tmp_path / "linked.pdf"
    os.link(src, alias)
    r = D.convert(src, alias, to="pdf")
    assert r["error"]["code"] == "bad_input" and src.read_bytes() == before
    od = tmp_path / "render"
    od.mkdir()
    (od / "input.pdf").symlink_to(src)
    r = D.render(src, [1], fmt="pdf", out_dir=od)
    assert r["error"]["code"] == "bad_input" and src.read_bytes() == before
    form = tmp_path / "form.hwpx"
    shutil.copyfile(kit / "forms" / "blank_a4.hwpx", form)
    t0 = time.time()
    r = D.new("# Test", form, form=form)
    assert r["error"]["code"] == "bad_input" and time.time() - t0 < 5


# ============================================================================ B3 concurrent exports
def test_b3_concurrent_exports_from_one_warm_doc_are_valid(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "abcdef", "next")
    D.read(src)                                     # warm cache
    gate = threading.Barrier(2)
    results = {}
    real = D._before_publish

    def staged(dest):
        gate.wait(5)
        real(dest)

    def export(name, value):
        results[name] = apply(src, [set_("p0", value)], tmp_path / (name + ".hwpx"))
    with patch.object(D, "_before_publish", side_effect=staged):
        ts = [threading.Thread(target=export, args=("one", "X" * 200)),
              threading.Thread(target=export, args=("two", "Z" * 1000))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    for name, want in (("one", "X" * 200), ("two", "Z" * 1000)):
        r = results[name]
        assert r["ok"], r
        with zipfile.ZipFile(r["out"]) as z:
            assert z.testzip() is None
        assert text(r["out"], "p0") == want
    assert D.read(src)["blocks"][0]["text"] == "abcdef"


# ============================================================================ B4 engine commit
@engine
def test_b4_metadata_failure_after_the_edit_does_not_report_failure(kit, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE", "NEXT")
    with patch.object(D, "_signals", side_effect=ValueError("mapping failed")):
        r = D.edit(src, [set_("p0", "CHANGED")], base=D.rev_of(src), in_place=True)
    assert r["ok"], r
    assert text(src, "p0") == "CHANGED" and r["rev"] == D.rev_of(src)
    assert any("signals" in w for w in r["warnings"])


def test_b4_publication_is_the_last_step(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    with patch.object(D, "_remap", side_effect=ValueError("boom")):
        r = D.edit(src, [set_("p0", "CHANGED")], base=D.rev_of(src), in_place=True)
    assert not r["ok"] and text(src, "p0") == "BASE"     # failed before anything was written
    assert r["error"].get("written") is False


# ============================================================================ B5 adjacent ops
@engine
@pytest.mark.parametrize("order", [0, 1])
def test_b5_adjacent_set_and_insert_after(kit, tmp_path, order):
    src = make(tmp_path, "source.hwpx", "BASE", "NEXT", "TAIL")
    ops = [set_("p1", "PATCH"), {"op": "insert_after", "at": "p0", "markdown": "ADDED"}]
    if order:
        ops.reverse()
    r = apply(src, ops, tmp_path / "out.hwpx")
    assert r["ok"], r
    assert texts(r["out"]) == ["BASE", "ADDED", "PATCH", "TAIL"]
    assert follow(r["remap"], "p1") == "p2" and follow(r["remap"], "p2") == "p3"
    assert "remap_approx" not in r


@engine
def test_b5_adjacent_cell_paragraphs(kit, tmp_path):
    f = tmp_path / "t.hwpx"
    shutil.copyfile(kit / "tests" / "features" / "feat_tables.hwpx", f)
    out = tmp_path / "o.hwpx"
    r = apply(f, [set_("t0/r0/c0/p0", "X")], out)
    assert r["ok"], r
    r = D.edit(out, [set_("t0/r0/c0/p0", "A\nB")], base=D.rev_of(out), out=tmp_path / "two.hwpx")
    assert r["ok"], r
    two = Path(r["out"])
    r = apply(two, [set_("t0/r0/c0/p1", "PATCH"),
                    {"op": "insert_after", "at": "t0/r0/c0/p0", "markdown": "ADDED"}], tmp_path / "three.hwpx")
    assert r["ok"], r
    rest = [b["text"] for b in D.read(two, "t0/r0/c0")["blocks"]][2:]
    assert [b["text"] for b in D.read(r["out"], "t0/r0/c0")["blocks"]] == ["A", "ADDED", "PATCH"] + rest
    assert follow(r["remap"], "t0/r0/c0/p1") == "t0/r0/c0/p2"


# ============================================================================ B6 overlapping spans
def test_b6_overlapping_replacements_conflict(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "abcdef")
    out = tmp_path / "out.hwpx"
    r = apply(src, [replacement("bcd", "X", at="p0"), replacement("cd", "ZZZ", at="p0")], out)
    assert r["error"]["code"] == "conflict" and r["error"]["i"] == 1
    assert not out.exists()
    r = apply(src, [replacement("ab", "X", at="p0"), replacement("ef", "Y", at="p0")], out)
    assert r["ok"] and text(out, "p0") == "XcdY"
    r = apply(src, [replacement("ab", "X", at="p0"), set_("p0:1-3", "Q")], out)
    assert r["error"]["code"] == "conflict"


def test_b6_structural_removal_of_a_target_conflicts(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "abcdef", "next")
    r = apply(src, [replacement("next", "X", at="p1"), {"op": "delete", "at": "p1"}], tmp_path / "o.hwpx")
    assert r["error"]["code"] == "conflict"


# ============================================================================ B7 preconditions
def test_b7_preconditions_cannot_be_bypassed(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "abcdef", "foo foo")
    out = tmp_path / "out.hwpx"
    r = apply(src, [replacement("foo", "ZZ", all=False, expect=2)], out)
    assert r["error"]["code"] == "ambiguous_match"
    r = apply(src, [replacement("foo", "ZZ", all=True, expect="wrong")], out)
    assert r["error"]["code"] == "bad_input"
    r = apply(src, [set_("p0:1-3", "q", expect="abcdef")], out)
    assert r["error"]["code"] == "expect_mismatch"
    assert not out.exists()
    r = apply(src, [set_("p0:1-3", "q", expect="bc")], out)
    assert r["ok"], r
    assert texts(out) == ["aqdef", "foo foo"]
    r = apply(src, [replacement("foo", "ZZ", all=True, expect=2)], out)
    assert r["ok"] and texts(out) == ["abcdef", "ZZ ZZ"]
    r = apply(src, [{"op": "insert_after", "at": "p0", "markdown": "x", "expect": "abcdef"}], out)
    assert r["error"]["code"] == "bad_input"
    r = apply(src, [set_("p0", "x", expect=3)], out)
    assert r["error"]["code"] == "bad_input"


def test_b7_paragraph_replace_is_scoped_to_its_own_text(no_engine, tmp_path):
    out = tmp_path / "out.hwpx"
    r = apply(GUARD, [replacement("표준근로계약서", "NEW", at="p0")], out)
    assert r["error"]["code"] == "not_found" and not out.exists()
    r = apply(GUARD, [replacement("표준근로계약서", "NEW", at="t0")], out)
    assert r["ok"] and text(out, "t0/r0/c0") == "NEW"
    r = apply(GUARD, [{"op": "delete", "at": "p2:1-3"}], out)
    assert r["error"]["code"] == "bad_address"


@engine
def test_b7_table_delete_checks_expect(kit, tmp_path):
    ft = kit / "tests" / "features" / "feat_tables.hwpx"
    r = apply(ft, [{"op": "delete", "at": "t0", "expect": "DELIBERATELY WRONG"}], tmp_path / "o.hwpx")
    assert r["error"]["code"] == "expect_mismatch"
    want = D.read(ft, "t0")["blocks"][0]["text"]
    r = apply(ft, [{"op": "delete", "at": "t0", "expect": want}], tmp_path / "o.hwpx")
    assert r["ok"] and follow(r["remap"], "t0") is None


# ============================================================================ B8 structural remaps
@engine
def test_b8_remaps_are_exact(kit, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE", "NEXT", "TAIL")
    r = apply(src, [set_("p1", "FIRST\nSECOND")], tmp_path / "a.hwpx")
    assert r["ok"] and texts(r["out"]) == ["BASE", "FIRST", "SECOND", "TAIL"]
    assert follow(r["remap"], "p1") == "p1" and follow(r["remap"], "p2") == "p3"
    assert "remap_approx" not in r

    ft = kit / "tests" / "features" / "feat_tables.hwpx"
    rows = D.read(ft, "t0")["blocks"][0]["rows"]
    r2 = D.read(ft, "t0/r2/c0")["blocks"][0]["text"]
    r = apply(ft, [{"op": "table.add_row", "at": "t0", "after": a} for a in (0, 1)], tmp_path / "b.hwpx")
    assert r["ok"], r
    assert [m for m in r["remap"] if m["from"] == "t0/r2"] == [{"from": "t0/r2", "to": "t0/r4"}]
    assert D.read(r["out"], "t0")["blocks"][0]["rows"] == rows + 2
    assert text(r["out"], follow(r["remap"], "t0/r2") + "/c0") == r2

    r = apply(ft, [{"op": "table.delete_row", "at": "t0/r1"}] * 2, tmp_path / "c.hwpx")
    assert r["error"]["code"] == "conflict"

    t1r3 = D.read(ft, "t1/r3/c0")["blocks"][0]["text"]
    r = apply(ft, [{"op": "table.delete_row", "at": "t1/r2"},
                   {"op": "insert_table", "at": "p2", "data": [["tnew"]]}], tmp_path / "d.hwpx")
    assert r["ok"], r
    assert follow(r["remap"], "t1") == "t2" and follow(r["remap"], "t1/r3") == "t2/r2"
    assert follow(r["remap"], "t1/r3/c0") == "t2/r2/c0"
    assert text(r["out"], "t2/r2/c0") == t1r3
    assert "remap_approx" not in r


# ============================================================================ B9 worker deadline
STUB_SILENT = "import time\ntime.sleep(30)\n"
STUB_PING_THEN_DEAF = textwrap.dedent("""
    import json, sys, time
    req = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
    sys.stdout.write(json.dumps({"id": req["id"], "api": 1, "ok": True, "fn": "ping"}) + "\\n")
    sys.stdout.flush()
    time.sleep(30)
""")
STUB_ECHO = textwrap.dedent("""
    import json, os, sys
    for line in sys.stdin:
        req = json.loads(line)
        fn = req["fn"]
        if fn == "ping":
            r = {"api": 1, "ok": True, "fn": fn, "pid": os.getpid()}
        elif fn == "die":
            os._exit(3)
        else:
            r = {"api": 1, "ok": False, "fn": fn, "error": {"code": "unsupported", "message": "no such function: " + fn}}
        r["id"] = req["id"]
        sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\\n")
        sys.stdout.flush()
""")


def _stub(tmp_path, body, name="worker"):
    d = tmp_path / name
    d.mkdir()
    (d / "kit_api.py").write_text(body, encoding="utf-8")
    return d


@pytest.mark.parametrize("body", [STUB_SILENT, STUB_PING_THEN_DEAF])
def test_b9_deadline_covers_start_write_and_wait(tmp_path, monkeypatch, body):
    monkeypatch.setenv(D.TIMEOUT_ENV, "0.5")
    eng = D._Engine(_stub(tmp_path, body))
    try:
        t0 = time.monotonic()
        r = eng.call("ping", "x" * (4 << 20))
        took = time.monotonic() - t0
        assert r["error"]["code"] in ("engine_timeout", "engine_unavailable") and r["error"]["retryable"] is True
        assert took < 3, took
        assert eng.worker is None
    finally:
        eng.reset(kill=True)


# ============================================================================ B10 render page identity
@engine
def test_b10_page_n_is_page_n_and_failures_publish_nothing(kit, tmp_path):
    pytest.importorskip("pypdfium2")
    ft = kit / "tests" / "features" / "feat_tables.hwpx"

    def draw(sel, name):
        return D.render(ft, sel, scale=0.3, out_dir=tmp_path / name)
    both = draw([2, 1], "both")
    assert both["ok"], both
    one, two = draw([1], "one")["pages"][0], draw([2], "two")["pages"][0]
    assert [x["n"] for x in both["pages"]] == [2, 1]
    png = lambda p: Path(p["file"]).read_bytes()  # noqa: E731
    assert png(both["pages"][0]) == png(two) and png(both["pages"][1]) == png(one)
    for sel in ([1, 1], [1, 99], [0]):
        r = draw(sel, "bad%d" % len(sel))
        assert r["error"]["code"] in ("bad_input", "bad_address"), r
        d = tmp_path / ("bad%d" % len(sel))
        assert not d.exists() or not list(d.iterdir())


# ============================================================================ B11 built-in XML fidelity
def test_b11_other_prefix_and_char_refs(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "x", "a &#x80; z", "b", lseg=True)
    renamed = rewrite(tmp_path, "renamed.hwpx",
                      lambda x: re.sub(r"(</?|xmlns:)hp(?=:|=)", r"\1other", x), src=src)
    assert D.open(renamed)["paragraphs"] == D.open(src)["paragraphs"] == 3
    assert texts(renamed) == ["x", "a \x80 z", "b"]
    r = apply(renamed, [replacement("z", "Z", at="p1")], tmp_path / "r-out.hwpx")
    assert r["ok"], r
    assert texts(r["out"]) == ["x", "a \x80 Z", "b"]
    with zipfile.ZipFile(r["out"]) as z:
        s = z.read(SECTION).decode()
    assert "<hp:" not in s and "<other:t>a &#x80; Z</other:t>" in s      # no hp: tags were invented
    r = apply(src, [replacement("z", "Z", at="p1")], tmp_path / "out.hwpx")
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(r["out"]) as b:
        sa, sb = a.read(SECTION).decode(), b.read(SECTION).decode()
    assert ascii(ET.fromstring(sb.encode()).findall(".//{*}t")[1].text) == ascii("a \x80 Z")
    # the one changed text node and that paragraph's own linesegarray; every other byte as it was
    assert sb == sa.replace("a &#x80; z</hp:t></hp:run>" + LSEG, "a &#x80; Z</hp:t></hp:run>")


def test_b11_comments_do_not_create_paragraphs(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "a", "b")
    commented = rewrite(tmp_path, "c.hwpx", lambda x: x.replace("</hs:sec>", "<!-- " + para("ghost", 9) + " --></hs:sec>"),
                        src=src)
    assert texts(commented) == ["a", "b"]


# ============================================================================ B12 / places
def _place_table(xml):
    def cell(r, c, value):
        return (f"<hp:tc><hp:subList>{para(value, 3 + r * 2 + c)}</hp:subList>"
                f'<hp:cellAddr rowAddr="{r}" colAddr="{c}"/></hp:tc>')
    rows = "".join("<hp:tr>" + cell(r, 0, name) + cell(r, 1, "") + "</hp:tr>"
                   for r, name in enumerate(["Alpha", "Beta"]))
    table = '<hp:tbl rowCnt="2" colCnt="2">' + rows + "</hp:tbl>"
    return xml.replace("</hp:p>", "</hp:p>" + para("", 1).replace("<hp:t></hp:t>", table), 1)


def _places(f):
    r = D.outline(f)
    assert r["ok"], r
    return {p["id"]: p["at"] for p in r["places"]}


def _by_label(f, key):
    pls = [p for p in D.outline(f)["places"] if D._heading_key(p["label"] or "") == key]
    assert len(pls) == 1, pls
    return pls[0]


def test_b12_editing_another_label_never_redirects_a_place(no_engine, tmp_path):
    src = make(tmp_path, "base.hwpx", "x")
    src = rewrite(tmp_path, "places.hwpx", _place_table, src=src)
    before = _places(src)
    assert sorted(before.values()) == ["t0/r0/c1", "t0/r1/c1"]
    r = apply(src, [set_("t0/r0/c0", "Beta")], tmp_path / "out.hwpx")
    assert r["ok"], r
    assert _places(r["out"]) == before                            # both labels read Beta; no id moved
    # an outside edit (no lineage) gives the same ids: they hash the cell, not its label
    D._LINEAGE.clear()
    os.environ[D.CACHE_ENV] = str(tmp_path / "empty-cache")
    assert _places(r["out"]) == before
    for pid, at in before.items():
        assert D.read(r["out"], "place:%s" % pid)["blocks"][0]["at"].startswith(at)


def test_b12_a_filled_place_keeps_its_id_and_shows_its_value(no_engine, tmp_path):
    src = shutil.copyfile(GUARD, tmp_path / "g.hwpx")
    before = _places(src)
    pid = _by_label(src, "취업장소")["id"]
    r = apply(src, [{"op": "fill", "place": pid, "text": "강남구"}], tmp_path / "f.hwpx")
    assert r["ok"], r
    after = D.outline(r["out"])["places"]
    rec = next(p for p in after if p["id"] == pid)
    assert rec["at"] == before[pid] and rec["value"] == "강남구" and rec["filled"] is True
    assert D.read(r["out"], "place:%s" % pid)["blocks"][0]["text"] == "강남구"
    assert {p["id"] for p in after} == set(before)
    r2 = D.edit(r["out"], [{"op": "fill", "place": pid, "text": "서초구"}], base=D.rev_of(r["out"]),
                out=tmp_path / "f2.hwpx")
    assert r2["ok"] and D.read(r2["out"], "place:%s" % pid)["blocks"][0]["text"] == "서초구"


# ============================================================================ S1 metadata
@engine
def test_s1_addresses_do_not_depend_on_call_order(kit):
    D.close()
    # (since hwp-engine #7 the engine labels a cell from its left neighbour first, so t1/r3/c1 reads 기본정보)
    pid = _by_label(REPORT, "연구과제명")["id"]
    D.close()
    r = D.find(REPORT, "abc", scope="place:%s" % pid)
    assert r["ok"], r


# ============================================================================ S2 worker generations
def test_s2_a_late_failure_never_kills_a_newer_worker(tmp_path):
    eng = D._Engine(_stub(tmp_path, STUB_ECHO))
    try:
        assert eng.call("ping")["ok"]
        old = eng.worker
        assert eng.call("die")["error"]["code"] == "engine_unavailable"
        assert eng.call("ping")["ok"]
        new = eng.worker
        assert new is not old
        eng._retire(old)                    # the old generation's delayed failure arrives now
        assert eng.worker is new and new.proc.poll() is None
        assert eng.call("ping")["ok"]
    finally:
        eng.reset(kill=True)


# ============================================================================ S3 transport
def test_s3_relative_engine_dir_and_utf8_pipes(tmp_path, monkeypatch):
    d = _stub(tmp_path, STUB_ECHO, "engine-base")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(D.ENGINE_ENV, "engine-base")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    D.close()
    try:
        assert D.engine_status()["available"] and D.engine_status()["dir"] == str(d)
        e = D._engine()
        assert e.call("ping")["ok"]
        msg = e.call("test가")["error"]["message"]
        assert msg == "no such function: test가"
    finally:
        D.close()


# ============================================================================ S4 temp files
def test_s4_preview_names_are_unique(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    gate = threading.Barrier(2)
    results = []
    real = D._before_publish

    def staged(dest):
        gate.wait(5)
        real(dest)

    def preview(v):
        results.append(D.edit(src, [set_("p0", v)], base=D.rev_of(src), preview=True))
    with patch.object(D, "_before_publish", side_effect=staged):
        ts = [threading.Thread(target=preview, args=(x,)) for x in ("FIRST", "SECOND")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert [r["ok"] for r in results] == [True, True]
    assert len({r["out"] for r in results}) == 2
    assert sorted(text(r["out"], "p0") for r in results) == ["FIRST", "SECOND"]


@engine
def test_s4_failed_png_publication_leaves_no_temp_files(kit, tmp_path):
    pytest.importorskip("pypdfium2")
    od = tmp_path / "png"
    src = kit / "tests" / "features" / "feat_paragraphs.hwpx"
    assert D.pages(src)["ok"]           # the engine's snapshot and page list exist: only publication fails
    with patch.object(D.os, "replace", side_effect=PermissionError(13, "sharing violation")):
        r = D.render(src, [1], scale=0.3, out_dir=od)
    assert r["error"]["code"] == "locked" and r["error"]["retryable"] is True
    assert leftovers(od) == []


# ============================================================================ S5 busy destination
def test_s5_locked_destination_is_retryable(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    base = D.rev_of(src)
    with patch.object(D.os, "replace", side_effect=PermissionError(13, "sharing violation")):
        r = D.edit(src, [set_("p0", "NEW")], base=base, in_place=True)
    assert r["error"]["code"] == "locked" and r["error"]["retryable"] is True
    assert D.rev_of(src) == base and leftovers(tmp_path) == []


# ============================================================================ S6 package fidelity
def _raw_members(path):
    """{name: raw local entry bytes (header + compressed data)}"""
    raw = Path(path).read_bytes()
    out = {}
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            h = raw[i.header_offset:i.header_offset + 30]
            n, x = struct.unpack("<HH", h[26:30])
            out[i.filename] = raw[i.header_offset:i.header_offset + 30 + n + x + i.compress_size]
    return out


def test_s6_untouched_members_are_byte_identical(no_engine, tmp_path):
    src = shutil.copyfile(GUARD, tmp_path / "g.hwpx")
    def extras(z):
        z.comment = b"archive comment"
    src = rewrite(tmp_path, "c.hwpx", lambda s: s, src=src, extra=extras)
    r = apply(src, [set_("p2", "x")], tmp_path / "o.hwpx")
    assert r["ok"], r
    a, b = _raw_members(src), _raw_members(r["out"])
    assert list(a) == list(b)
    assert [n for n in a if a[n] != b[n]] == [SECTION]
    with zipfile.ZipFile(src) as za, zipfile.ZipFile(r["out"]) as zb:
        assert zb.comment == b"archive comment"
        for x, y in zip(za.infolist(), zb.infolist()):
            assert (x.filename, x.date_time, x.compress_type, x.external_attr, x.create_system, x.extra) == \
                (y.filename, y.date_time, y.compress_type, y.external_attr, y.create_system, y.extra)


def test_s6_ambiguous_or_foreign_archives_are_refused(no_engine, tmp_path):
    import warnings
    warnings.simplefilter("ignore", UserWarning)

    def dup(z):
        z.writestr("extra/a", b"first")
        z.writestr("extra/a", b"second")
    src = rewrite(tmp_path, "duplicate.hwpx", lambda s: s, extra=dup)
    assert D.open(src)["error"]["code"] == "bad_input"
    assert apply(src, [set_("p2", "x")], tmp_path / "o.hwpx")["error"]["code"] == "bad_input"
    junk = tmp_path / "ordinary.hwpx"
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr("plain.txt", "plain text")
    assert D.open(junk)["error"]["code"] == "bad_input"


# ============================================================================ S7 contract
def test_s7_malformed_addresses_and_engine_errors(no_engine):
    assert D.read(GUARD, 1)["error"]["code"] == "bad_address"
    assert D.find(GUARD, "x", scope=5)["error"]["code"] == "bad_address"
    env = {"ok": False, "error": {"code": "bad_address", "message": "bad page", "at": "page:99", "retryable": False}}
    e = D._engine_error(env, "geometry").to_error()
    assert e["code"] == "bad_address" and e["at"] == "page:99" and e["retryable"] is False
    e = D._engine_error(env, "geometry", at="page:3").to_error()
    assert e["at"] == "page:3"


def test_s7_engine_results_are_validated(no_engine, tmp_path, monkeypatch):
    class Fake:
        def __init__(self, answer):
            self.answer = answer

        def call(self, fn, *a, **k):
            return dict(self.answer)
    monkeypatch.setattr(D, "_engine", lambda: Fake({"ok": True, "page": 1, "boxes": "nonsense"}))
    r = D.geometry(GUARD, 1)
    assert r["error"]["code"] == "engine_protocol"
    good = {"ok": True, "page": 1, "width_pt": 595.3, "height_pt": 841.9,
            "boxes": [{"at": "p0", "kind": "para", "rect": [1, 2, 3, 4]}]}
    monkeypatch.setattr(D, "_engine", lambda: Fake(good))
    r = D.geometry(GUARD, 1)
    assert r["ok"] and r["boxes"][0]["rect"] == [1, 2, 3, 4] and r["rev"] == D.rev_of(GUARD)


@engine
def test_s7_convert_png_and_pdf_records(kit, tmp_path):
    pytest.importorskip("pypdfium2")
    fp = kit / "tests" / "features" / "feat_paragraphs.hwpx"
    r = D.convert(fp, tmp_path / "named.png", to="png")
    assert r["ok"], r
    assert Path(r["out"]).is_file() and all(Path(p["file"]).is_file() for p in r["pages"])
    r = D.render(fp, [1], fmt="pdf", out_dir=tmp_path / "pdf")
    assert r["ok"] and Path(r["pages"][0]["file"]).is_file() and Path(r["file"]).is_file()
    assert D.read(fp, 1)["error"]["code"] == "bad_address"


# ============================================================================ N1: worker step failures
@engine
def test_n1_engine_step_failure_names_the_op(kit, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE", "NEXT")
    real = D._set_para_steps

    def steps(p, text):                         # op 1's paragraph gets a step the engine refuses
        return [["goto", 99999, 0, p.si]] if text == "BROKEN" else real(p, text)
    out = tmp_path / "o.hwpx"
    with patch.object(D, "_set_para_steps", side_effect=steps):
        r = apply(src, [set_("p1", "X"), set_("p0", "BROKEN")], out)
    assert not r["ok"], r
    err = r["error"]
    assert err["i"] == 1 and err["at"] == "p0" and isinstance(err.get("step"), int)
    assert err["done"] == [0] and err["retryable"] is False and err["written"] is False and not out.exists()


# ============================================================================ platform contract additions
def _field_para(i, fid, name, direction, inner="<hp:t/>", before=""):
    return (f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0">{before}<hp:ctrl><hp:fieldBegin id="{fid}" type="CLICK_HERE" name="{name}" '
            f'editable="1" dirty="0" zorder="-1" fieldid="{fid}"><hp:parameters cnt="1" name="">'
            f'<hp:stringParam name="Direction">{direction}</hp:stringParam></hp:parameters></hp:fieldBegin>'
            f'</hp:ctrl>{inner}<hp:ctrl><hp:fieldEnd beginIDRef="{fid}" fieldid="{fid}"/></hp:ctrl></hp:run>'
            f'{LSEG}</hp:p>')


def _fields_doc(tmp_path, extra=""):
    base = make(tmp_path, "base.hwpx", "신청서")

    def change(xml):
        end = xml.index("</hs:sec>")
        return xml[:end] + _field_para(1, 11, "applicant", "신청인") + \
            _field_para(2, 12, "date", "날짜", inner="<hp:t>여기에 입력</hp:t>", before="<hp:t>일자: </hp:t>") + \
            extra + xml[end:]
    return rewrite(tmp_path, "fields.hwpx", change, src=base)


def test_click_here_fields_are_fill_places(no_engine, tmp_path):
    src = _fields_doc(tmp_path)
    ol = D.outline(src)
    assert ol["ok"] and ol["places_complete"] is True and "places_reason" not in ol
    pl = {p["label"]: p for p in ol["places"]}
    applicant, date = D.place_id("click", "applicant", 0), D.place_id("click", "date", 0)
    assert pl["신청인"] == {"id": applicant, "at": "p1", "label": "신청인", "kind": "field", "value": "",
                          "filled": False}
    assert pl["날짜"]["at"] == "p2" and pl["날짜"]["value"] == "여기에 입력" and pl["날짜"]["id"] == date
    out = tmp_path / "filled.hwpx"
    r = apply(src, [{"op": "fill", "place": applicant, "text": "홍길동"},
                    {"op": "fill", "place": date, "text": "2026-11-19"}], out)
    assert r["ok"], r
    assert texts(out) == ["신청서", "홍길동", "일자: 2026-11-19"]
    with zipfile.ZipFile(out) as z:
        s = z.read(SECTION).decode()
    assert re.search(r'name="applicant".*?</hp:ctrl><hp:t>홍길동</hp:t><hp:ctrl><hp:fieldEnd', s)
    assert re.search(r'name="date".*?</hp:ctrl><hp:t>2026-11-19</hp:t><hp:ctrl><hp:fieldEnd', s)
    after = {p["id"]: p for p in D.outline(out)["places"]}
    assert after[applicant]["value"] == "홍길동" and after[applicant]["filled"] is True
    assert D.read(out, "place:%s" % date)["blocks"][0]["text"] == "일자: 2026-11-19"
    r2 = D.edit(out, [{"op": "fill", "place": applicant, "text": "김철수"}], base=D.rev_of(out),
                out=tmp_path / "again.hwpx")
    assert r2["ok"] and texts(r2["out"])[1] == "김철수"


def test_click_here_field_names_hash_as_the_document_means_them(no_engine, tmp_path):
    # the engine decodes XML references before hashing; a name with & < > " must give the same id here
    src = _fields_doc(tmp_path, extra=_field_para(3, 13, "a&amp;b &lt;c&gt; &quot;d&quot; &#xD55C;", "기타"))
    pl = {p["label"]: p for p in D.outline(src)["places"]}
    assert pl["기타"]["id"] == D.place_id("click", 'a&b <c> "d" 한', 0)


def test_outline_says_when_places_are_incomplete(no_engine, tmp_path):
    ctrl = ('<hp:p id="9" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            '<hp:run charPrIDRef="0"><hp:checkBtn caption="동의"/></hp:run></hp:p>')
    ol = D.outline(_fields_doc(tmp_path, extra=ctrl))
    assert ol["places_complete"] is False and any("checkBtn" in w for w in ol["places_reason"])


def test_outline_counts_paragraphs_and_titles_tables(no_engine):
    ol = D.outline(GUARD)
    assert ol["paragraphs"] == 154 and ol["paragraph_range"] == "p0..p153"
    assert ol["tables"][0]["title"] == "표준근로계약서"
    assert all(len(t.get("title", "")) <= 40 for t in ol["tables"])


def test_unresolved_addresses_always_offer_candidates(no_engine, tmp_path):
    src = make(tmp_path, "plain.hwpx", "only text", "more")
    for at in ("place:nothing", "t3", "p99", 'h:"없음"', "t0/r0/c0"):
        e = D.read(src, at)["error"]
        assert e["code"] == "bad_address" and e["candidates"], (at, e)


@pytest.mark.parametrize("call", [
    lambda t: D.open(None), lambda t: D.open(123), lambda t: D.outline(["x"]), lambda t: D.read(None),
    lambda t: D.find(GUARD, None), lambda t: D.find(None, "x"), lambda t: D.diff(None, GUARD),
    lambda t: D.edit(None, [], base="x"), lambda t: D.edit(GUARD, "ops", base=D.rev_of(GUARD)),
    lambda t: D.edit(GUARD, [{"op": "set", "at": "p2", "text": 5}], base=D.rev_of(GUARD), out=t / "o.hwpx"),
    lambda t: D.edit(GUARD, [{"op": "set", "at": "p2", "text": "x"}], base=None, out=t / "o.hwpx"),
    lambda t: D.edit(GUARD, [{"op": "set", "at": "p2", "text": "x"}], base=D.rev_of(GUARD), out=5),
    lambda t: D.edit(GUARD, [{"op": "replace", "find": "근로", "with": "x", "all": "yes"}], base=D.rev_of(GUARD),
                     out=t / "o.hwpx"),
    lambda t: D.convert(GUARD, None, to="hwpx"), lambda t: D.convert(GUARD, t / "x.hwpx", to=None),
    lambda t: D.new(None, t / "n.hwpx"), lambda t: D.render(None, 1), lambda t: D.pages(None),
    lambda t: D.geometry(None, 1),
])
def test_bad_arguments_are_bad_input_not_internal(no_engine, tmp_path, call):
    r = call(tmp_path)
    assert r["ok"] is False and r["error"]["code"] in ("bad_input", "bad_address"), r


def test_every_error_code_is_declared():
    import rt_codes
    src = (REPO / "runtime" / "scripts" / "rt_doc.py").read_text(encoding="utf-8")
    used = set(re.findall(r'DocError\(\s*"([a-z_]+)"', src)) | {"capability_unavailable"}
    assert used <= rt_codes.DOC_CORE_CODES | {"capability_unavailable"}
    assert rt_codes.DOC_CORE_CODES & rt_codes.TRANSPORT_CODES == frozenset()
    assert rt_codes.DOC_CORE_CODES <= rt_codes.ERROR_CODES


# ============================================================================ #388 review follow-ups
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_outputs_keep_the_destination_mode_or_the_umask(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    os.chmod(src, 0o664)
    r = D.edit(src, [set_("p0", "NEW")], base=D.rev_of(src), in_place=True)
    assert r["ok"], r
    assert os.stat(src).st_mode & 0o777 == 0o664
    out = tmp_path / "new.hwpx"
    old = os.umask(0o027)
    try:
        D._UMASK = None
        r = D.edit(src, [set_("p0", "NEWER")], base=D.rev_of(src), out=out)
    finally:
        os.umask(old)
        D._UMASK = None
    assert r["ok"] and os.stat(out).st_mode & 0o777 == 0o640


def test_worker_starts_without_a_console_window(tmp_path):
    seen = {}

    def fake_popen(*a, **k):
        seen.update(k)
        raise OSError("stop here")
    with patch.object(D.subprocess, "Popen", side_effect=fake_popen):
        with pytest.raises(OSError):
            D._Worker(tmp_path)
    want = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    assert seen["creationflags"] == want and (os.name != "nt" or want == 0x08000000)


def test_a_stale_lock_is_broken_by_rename_and_a_fresh_one_is_kept(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    lock = D._lock_path(src)
    lock.write_text("1 dead\n")
    old = time.time() - D.LOCK_STALE_S - 60
    os.utime(lock, (old, old))
    r = D.edit(src, [set_("p0", "NEW")], base=D.rev_of(src), in_place=True)
    assert r["ok"], r
    assert not lock.exists() and not list(tmp_path.glob("*.stale"))
    lock.write_text("2 alive\n")                   # a live writer's lock is never broken
    with patch.dict(os.environ, {D.LOCK_TIMEOUT_ENV: "0.2"}):
        r = D.edit(src, [set_("p0", "AGAIN")], base=D.rev_of(src), in_place=True)
    assert r["error"]["code"] == "busy" and lock.read_text() == "2 alive\n"


def test_staged_files_left_by_a_killed_writer_are_swept(no_engine, tmp_path):
    src = make(tmp_path, "source.hwpx", "BASE")
    dead, fresh = tmp_path / ".rtdoc-dead.tmp", tmp_path / ".rtdoc-busy.tmp"
    dead.write_bytes(b"x")
    fresh.write_bytes(b"y")
    old = time.time() - D.TMP_STALE_S - 60
    os.utime(dead, (old, old))
    r = D.edit(src, [set_("p0", "NEW")], base=D.rev_of(src), out=tmp_path / "out.hwpx")
    assert r["ok"], r
    assert not dead.exists() and fresh.exists()     # another writer's staged file is left alone


def test_the_lineage_cache_is_pruned(no_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "LINEAGE_MAX", 3)
    d = D._cache_dir() / "places"
    d.mkdir(parents=True, exist_ok=True)
    old = d / ("%s.json" % ("0" * 64))
    old.write_text("[]")
    t = time.time() - D.LINEAGE_MAX_AGE_S - 60
    os.utime(old, (t, t))
    for k in range(6):
        D._lineage_put(("%x" % k) * 64, [])
        time.sleep(0.01)
    left = sorted(x.name for x in d.glob("*.json"))
    assert len(left) == 3 and old.name not in left


@pytest.mark.skipif(os.name != "nt", reason="a real Windows sharing violation")
def test_windows_a_file_open_without_delete_sharing_is_locked(no_engine, tmp_path):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    GENERIC_READ, SHARE_READ, SHARE_WRITE, OPEN_EXISTING = 0x80000000, 1, 2, 3
    src = make(tmp_path, "source.hwpx", "BASE")
    base = D.rev_of(src)

    def hold(share):
        h = k32.CreateFileW(str(src), GENERIC_READ, share, None, OPEN_EXISTING, 0, None)
        assert h not in (None, wintypes.HANDLE(-1).value), ctypes.get_last_error()
        return h
    h = hold(SHARE_READ | SHARE_WRITE)                 # as Hancom holds an open document: no FILE_SHARE_DELETE
    try:
        r = D.edit(src, [set_("p0", "NEW")], base=base, in_place=True)
    finally:
        k32.CloseHandle(h)
    assert r["error"]["code"] == "locked" and r["error"]["retryable"] is True, r
    assert D.rev_of(src) == base and leftovers(tmp_path) == []
    h = hold(0)                                        # no sharing at all: even reading is refused
    try:
        e = D.outline(src)["error"]
    finally:
        k32.CloseHandle(h)
    assert e["code"] == "locked" and e["retryable"] is True
