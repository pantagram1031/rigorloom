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
