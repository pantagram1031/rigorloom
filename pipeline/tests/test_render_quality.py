"""Synthetic, privacy-safe regressions for the Hangul render checker."""
from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import render_quality as quality  # noqa: E402


def _source(path: Path, text: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            f'<hp:sec xmlns:hp="urn:test"><hp:p><hp:run>'
            f'<hp:t>{text}</hp:t></hp:run></hp:p></hp:sec>',
        )
    return path


class _Page:
    def __init__(self, font_name: str, text: str):
        self._font_name = font_name
        self._text = text

    def get_text(self, kind):
        assert kind == "rawdict"
        chars = [{"c": char} for char in self._text]
        return {"blocks": [{"type": 0, "lines": [{
            "spans": [{"font": self._font_name, "chars": chars}]
        }]}]}


class _Document:
    page_count = 1

    def __init__(self, *, text: str, font_name="SubsetFont", rows=None,
                 font_type="TrueType", ext="ttf", buffer=b"font",
                 glyph_count=100):
        self.page = _Page(font_name, text)
        self.rows = rows or [(5, "ttf", font_type, font_name, font_name,
                              "Identity-H", 0)]
        self.font_type = font_type
        self.ext = ext
        self.buffer = buffer
        self.glyph_count = glyph_count

    def __getitem__(self, index):
        assert index == 0
        return self.page

    def get_page_fonts(self, index, full=False):
        assert index == 0 and full
        return self.rows

    def extract_font(self, xref, info_only=0):
        assert info_only == 0
        return ("private font name", self.ext, self.font_type, self.buffer)

    def close(self):
        pass


def _fake_fitz(monkeypatch, document: _Document):
    class Font:
        def __init__(self, *, fontbuffer):
            assert fontbuffer == b"font"
            self.glyph_count = document.glyph_count

    monkeypatch.setitem(
        sys.modules,
        "fitz",
        types.SimpleNamespace(open=lambda path: document, Font=Font),
    )


def test_insufficient_embedded_capacity_is_missing_glyphs(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "한글가")
    pdf = (tmp_path / "rendered.pdf")
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(
        monkeypatch,
        _Document(text="한글가", glyph_count=2),
    )
    result = quality.inspect(source, pdf)
    assert result["state"] == "failed"
    assert result["reason_code"] == "missing_hangul_glyphs"
    assert result["pdf_hangul_count"] == 3
    assert result["max_unique_hangul_per_xref"] == 3
    assert result["min_glyph_capacity"] == 2


def test_partial_pdf_hangul_coverage_is_ambiguous_before_font_capacity(
    tmp_path, monkeypatch
):
    source = _source(tmp_path / "source.hwpx", "한글가나다")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, _Document(text="한글가", glyph_count=1000))
    result = quality.inspect(source, pdf)
    # The section-run scan is intentionally conservative: a missing syllable
    # may be deleted/hidden source text rather than a renderer omission.  It
    # must never pass, but remains unknown until a visibility-aware parser is
    # available.
    assert result["state"] == "unknown"
    assert result["reason_code"] == "source_visibility_ambiguous"
    assert result["source_hangul_count"] == 5
    assert result["pdf_hangul_count"] == 3


def test_embedded_korean_subset_with_enough_capacity_passes(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "한글가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, _Document(text="한글가", glyph_count=8))
    result = quality.inspect(source, pdf)
    assert quality.is_passed(result)
    assert result["checked_font_xrefs"] == 1
    assert result["mapped_font_xrefs"] == 1


def test_duplicate_font_name_mapping_is_unknown(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "한글")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    rows = [
        (5, "ttf", "TrueType", "SubsetFont", "SubsetFont", "Identity-H", 0),
        (9, "ttf", "TrueType", "SubsetFont", "SubsetFont", "Identity-H", 0),
    ]
    _fake_fitz(monkeypatch, _Document(text="한글", rows=rows))
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == "ambiguous_font_mapping"


@pytest.mark.parametrize(
    ("font_type", "ext", "buffer", "reason"),
    [
        ("Type3", "n/a", b"font", "type3_font"),
        ("TrueType", "n/a", b"", "nonembedded_font"),
        ("TrueType", "ttf", b"", "font_buffer_unavailable"),
    ],
)
def test_type3_and_nonembedded_fonts_never_pass(
    tmp_path, monkeypatch, font_type, ext, buffer, reason
):
    source = _source(tmp_path / "source.hwpx", "한글")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(
        monkeypatch,
        _Document(text="한글", font_type=font_type, ext=ext, buffer=buffer),
    )
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == reason


def test_source_hangul_with_zero_pdf_hangul_is_failed(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "한글")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, _Document(text="ASCII"))
    result = quality.inspect(source, pdf)
    assert result["state"] == "failed"
    assert result["reason_code"] == "missing_hangul_glyphs"
    assert result["pdf_hangul_count"] == 0


def test_ascii_source_is_not_applicable_without_auto_promotion(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "ASCII only")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, _Document(text="ASCII"))
    result = quality.inspect(source, pdf)
    assert result["state"] == "not_applicable"
    assert result["reason_code"] == "source_ascii_only"
    assert not quality.is_passed(result)


def test_header_and_nonsection_hangul_do_not_expand_visible_source_scope(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.hwpx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "Contents/header.xml",
            '<header><title>숨은 머리말</title></header>',
        )
        archive.writestr(
            "Contents/content.hpf",
            '<meta>메타데이터</meta>',
        )
        archive.writestr(
            "Contents/section0.xml",
            '<hp:sec xmlns:hp="urn:test"><hp:p><hp:run>'
            '<hp:t>ASCII only</hp:t></hp:run></hp:p></hp:sec>',
        )
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, _Document(text="ASCII"))
    result = quality.inspect(source, pdf)
    assert result["state"] == "not_applicable"
    assert result["reason_code"] == "source_ascii_only"


def test_layout_gate_closes_quality_without_mutating_private_data():
    base = {
        "schema": quality.QUALITY_SCHEMA,
        "checker": quality.CHECKER_ID,
        "version": quality.QUALITY_VERSION,
        "artifact_sha256": "a" * 64,
        "artifact_bytes": 10,
        "state": "passed",
        "reason_code": "passed",
        "source_hangul_count": 3,
        "pdf_hangul_count": 3,
        "page_count": 1,
        "mapped_font_xrefs": 1,
        "checked_font_xrefs": 1,
        "max_unique_hangul_per_xref": 3,
        "min_glyph_capacity": 8,
    }
    failed = quality.apply_layout_gate(
        base, converged=False, hard_checks=True, style_clean=True)
    assert failed["state"] == "failed"
    assert failed["reason_code"] == "layout_hard_failed"
    pending = quality.apply_layout_gate(
        base, converged=True, hard_checks=True, style_clean=True,
        advisory_hold=True,
    )
    assert pending["state"] == "failed"
    assert pending["reason_code"] == "visual_quality_gate_pending"
    encoded = json.dumps(pending, ensure_ascii=False)
    assert "private font name" not in encoded
    assert str(Path("source.hwpx")) not in encoded
