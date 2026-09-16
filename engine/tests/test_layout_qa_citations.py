"""layout_qa citation_marker: resolve [N] against the bibliography.

Synthetic PyMuPDF PDFs (ASCII "References" heading — Helvetica cannot
embed Hangul) plus pure regex checks for 참고문헌 / 참고 문헌.
`python -m pytest engine/tests -k "layout_qa or caption or citation" -q`.
"""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

pytest.importorskip("fitz")
import fitz  # noqa: E402
import layout_qa  # noqa: E402

PAGE_W, PAGE_H = 595, 842


def _write_pdf(tmp_path, name, pages):
    """pages: list of list of str (one string per inserted line)."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=10)
            y += 16
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


def _citation_markers(checks):
    return [v for v in checks["body_markers"] if v["kind"] == "citation_marker"]


def test_bib_heading_re_accepts_korean_and_english_forms():
    assert layout_qa.BIB_HEADING_RE.match("VI.  참고문헌")
    assert layout_qa.BIB_HEADING_RE.match("참고문헌")
    assert layout_qa.BIB_HEADING_RE.match("참고 문헌")
    assert layout_qa.BIB_HEADING_RE.match("References")
    assert layout_qa.BIB_HEADING_RE.match("REFERENCES")


def test_resolved_citation_with_13_entries_not_flagged(tmp_path):
    """[13] in body + bibliography with 13+ numbered entries → no violation."""
    bib = ["VI.  References"] + [f"[{i}] Author {i}. Title {i}." for i in range(1, 14)]
    path = _write_pdf(tmp_path, "resolved13.pdf", [
        ["See the algorithm in prior work [13] for the proof."],
        bib,
    ])
    assert _citation_markers(layout_qa.run_new_checks(path)) == []


def test_unresolved_citation_flagged(tmp_path):
    """[3] in body + bibliography with 2 entries → unresolved, number 3."""
    path = _write_pdf(tmp_path, "unresolved.pdf", [[
        "The claim [3] is not in the list.",
        "References",
        "1. First paper.",
        "2. Second paper.",
    ]])
    cits = _citation_markers(layout_qa.run_new_checks(path))
    assert len(cits) == 1
    assert cits[0]["kind"] == "citation_marker"
    assert cits[0]["reason"] == "unresolved"
    assert cits[0]["number"] == 3


def test_no_bibliography_flagged(tmp_path):
    """[2] in body, no bibliography section → no_bibliography."""
    path = _write_pdf(tmp_path, "nobib.pdf", [[
        "Abandoned draft marker [2] remains.",
    ]])
    cits = _citation_markers(layout_qa.run_new_checks(path))
    assert len(cits) == 1
    assert cits[0]["kind"] == "citation_marker"
    assert cits[0]["reason"] == "no_bibliography"
    assert cits[0]["number"] == 2


def test_marker_inside_bibliography_not_flagged(tmp_path):
    """[1] inside the bibliography section → no violation."""
    path = _write_pdf(tmp_path, "bibonly.pdf", [[
        "References",
        "[1] Author. Title of the paper.",
    ]])
    assert _citation_markers(layout_qa.run_new_checks(path)) == []


class _FakePage:
    number = 0

    class rect:
        height = 842.0


def test_korean_heading_resolves_via_stubbed_line_records(monkeypatch):
    """참고문헌 heading (Hangul) + 13 numbered entries resolve body [13]."""
    records = [
        (50.0, 62.0, 10, "본문 [13] 인용"),
        (400.0, 414.0, 12, "VI.  참고문헌"),
    ]
    records += [
        (420.0 + i * 12, 430.0 + i * 12, 10, f"[{i}] item {i}")
        for i in range(1, 14)
    ]
    monkeypatch.setattr(layout_qa, "_text_line_records", lambda page: records)
    page = _FakePage()
    bib = layout_qa.collect_bibliography([page])
    assert bib["has_section"] is True
    assert 13 in bib["numbers"]
    cits = [v for v in layout_qa.check_body_markers(page, bibliography=bib)
            if v["kind"] == "citation_marker"]
    assert cits == []
