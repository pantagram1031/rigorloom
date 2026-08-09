"""Synthetic Type3 render-quality boundaries.

These fixtures intentionally model only the bounded PyMuPDF surface consumed by
the checker.  They contain no private or real-document paths and keep all PDF
content in small in-memory streams.
"""
from __future__ import annotations

import hashlib
import os
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
            '<hp:sec xmlns:hp="urn:test"><hp:p><hp:run>'
            f"<hp:t>{text}</hp:t></hp:run></hp:p></hp:sec>",
        )
    return path


def _cmap(*pairs: tuple[int, str]) -> bytes:
    rows = [
        b"/CIDInit /ProcSet findresource begin",
        b"12 dict begin begincmap",
        b"/CIDSystemInfo << /Registry (R) /Ordering (U) /Supplement 0 >> def",
        b"/CMapName /Synthetic def",
        b"/CMapType 2 def",
        f"{len(pairs)} begincodespacerange".encode(),
        b"<00> <FF>",
        b"endcodespacerange",
        f"{len(pairs)} beginbfchar".encode(),
    ]
    rows.extend(f"<{code:02X}> <{ord(char):04X}>".encode() for code, char in pairs)
    rows.extend([b"endbfchar", b"endcmap CMapName currentdict /CMap defineresource pop", b"end end"])
    return b"\n".join(rows)


def _font_object(*, cmap_xref: int = 6, encoding: str = "<< /Type /Encoding /Differences [0 /g0 1 /g1] >>", charprocs_xref: int = 8) -> str:
    return (
        "<< /Type /Font /Subtype /Type3 /Name /T3Font "
        f"/ToUnicode {cmap_xref} 0 R /Encoding {encoding} "
        f"/CharProcs {charprocs_xref} 0 R /FirstChar 0 /LastChar 255 "
        "/FontBBox [0 0 1000 1000] /FontMatrix [0.001 0 0 0.001 0 0] "
        "/Widths [500 500] >>"
    )


class _Page:
    def __init__(
        self,
        *,
        content: bytes,
        semantic: str,
        font_name: str = "T3Font",
        span_text: str | None = None,
        trace: list[dict] | None = None,
        bboxlog: list[tuple] | None = None,
    ):
        self.xref = 1
        self._content = content
        self._semantic = semantic
        self._font_name = font_name
        self._span_text = span_text
        self.rect = (0.0, 0.0, 1000.0, 1000.0)
        self.transformation_matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self._trace = list(trace or [])
        self._bboxlog = list(bboxlog or [])

    def get_text(self, kind):
        assert kind == "rawdict"
        return {
            "blocks": [{
                "type": 0,
                "lines": [{
                    "spans": [{
                        "font": self._font_name,
                        "chars": [{"c": char} for char in self._semantic],
                        **({"text": self._span_text}
                           if self._span_text is not None else {}),
                    }],
                }],
            }],
        }

    def get_contents(self):
        return [4]

    def read_contents(self):
        return self._content

    def get_texttrace(self):
        return self._trace

    def get_bboxlog(self):
        return self._bboxlog


class _Type3Document:
    page_count = 1

    def __init__(
        self,
        *,
        semantic: str = "가나",
        codes: bytes = b"\x00\x01",
        charprocs: dict[int, bytes] | None = None,
        extra_fonts: bool = False,
        content_prefix: bytes = b"",
        content_suffix: bytes = b"",
        font_name: str = "T3Font",
        span_text: str | None = None,
        font_type: str = "Type3",
        font_ext: str = "n/a",
        glyph_count: int = 500,
        resource_font_map: str | None = None,
        extra_objects: dict[int, str] | None = None,
        opaque_raw: bool = False,
        decoded_missing: bool = False,
        trace: list[dict] | None = None,
        bboxlog: list[tuple] | None = None,
    ):
        self.glyph_count = glyph_count
        self.font_type = font_type
        self.font_ext = font_ext
        self.opaque_raw = opaque_raw
        self.decoded_missing = decoded_missing
        self.page = _Page(
            content=(content_prefix + b"BT /F1 12 Tf " + codes_to_hex(codes) + b" Tj ET " + content_suffix),
            semantic=semantic,
            font_name=font_name,
            span_text=span_text,
            trace=trace,
            bboxlog=bboxlog,
        )
        self._font_rows = [
            (5, "n/a", font_type, font_name, "F1", "Identity-H", 1),
        ]
        self._objects: dict[int, str] = {
            1: "<< /Type /Page /Resources 2 0 R /Contents 4 0 R >>",
            2: "<< /Font 3 0 R >>",
            3: resource_font_map or "<< /F1 5 0 R >>",
            5: _font_object(),
            8: "<< /g0 9 0 R /g1 10 0 R >>",
        }
        self._streams: dict[int, bytes] = {
            4: self.page._content,
            6: _cmap((0, "가"), (1, "나")),
            9: b"500 0 d0 0 0 m 500 0 l 500 500 l 0 500 l h f",
            10: b"500 0 d0 0 0 m 500 0 l 500 500 l 0 500 l h 0 0 m 450 0 l h f",
        }
        if charprocs is not None:
            self._streams.update({9 + code: stream for code, stream in charprocs.items()})
        if extra_fonts:
            self._font_rows.append((6, "n/a", "Type3", "SymbolT3", "F2", "Identity-H", 1))
            self._objects[3] = "<< /F1 5 0 R /F2 6 0 R >>"
            self._objects[6] = _font_object()
        if extra_objects:
            self._objects.update(extra_objects)

    def __getitem__(self, index):
        assert index == 0
        return self.page

    def get_page_fonts(self, index, full=False):
        assert index == 0 and full
        return self._font_rows

    def extract_font(self, xref, info_only=0):
        assert info_only == 0
        return ("synthetic", self.font_ext, self.font_type, b"font")

    def xref_get_key(self, xref, key):
        value = self._objects.get(int(xref), "")
        if key == "Resources" and int(xref) == 1:
            return "xref", "2 0 R"
        if key == "Font" and int(xref) == 2:
            return "xref", "3 0 R"
        if key == "ExtGState" and int(xref) == 2:
            return "null", "null"
        # The real API returns a type/value pair; tests exercise only the
        # dictionaries required by the bounded checker.
        return _dict_key(value, key)

    def xref_object(self, xref, compressed=0, ascii=0):
        return self._objects.get(int(xref), "")

    def xref_stream(self, xref):
        if self.decoded_missing:
            return None
        return self._streams[int(xref)]

    def xref_stream_raw(self, xref):
        if self.opaque_raw:
            return b"\x78\x9c opaque encoded stream"
        return self._streams[int(xref)]

    def xref_length(self):
        return max([1, *self._objects.keys(), *self._streams.keys()]) + 1

    def close(self):
        pass


class _TwoPageAliasDocument(_Type3Document):
    """Same Type3 xref is F1 on page A and F2 on page B."""

    page_count = 2

    def __init__(self):
        super().__init__(semantic="가", codes=b"\x00")
        self._pages = [
            _Page(
                content=b"BT /F2 12 Tf <00> Tj ET",
                semantic="가",
                font_name="T3Font",
            ),
            _Page(
                content=b"BT /F2 12 Tf <00> Tj ET",
                semantic="가",
                font_name="T3Font",
            ),
        ]
        self._page_rows = [
            [(5, "n/a", "Type3", "T3Font", "F1", "Identity-H", 1)],
            [(5, "n/a", "Type3", "T3Font", "F2", "Identity-H", 1)],
        ]

    def __getitem__(self, index):
        return self._pages[index]

    def get_page_fonts(self, index, full=False):
        assert full
        return self._page_rows[index]


class _TwoSpanDocument(_Type3Document):
    def __init__(self):
        super().__init__(semantic="가나", codes=b"\x00\x01")
        self.page = _TwoSpanPage(
            content=b"BT /F1 12 Tf <0001> Tj ET",
            semantic="가나",
            font_name="T3Font",
        )

    def __getitem__(self, index):
        assert index == 0
        return self.page

    def get_page_fonts(self, index, full=False):
        assert index == 0 and full
        return self._font_rows

    def close(self):
        pass


class _TwoSpanPage(_Page):
    def get_text(self, kind):
        assert kind == "rawdict"
        return {
            "blocks": [{
                "type": 0,
                "lines": [{
                    "spans": [
                        {"font": "T3Font", "chars": [{"c": char} for char in "가나"]},
                        {"font": "T3Font", "chars": [{"c": "가"}]},
                    ],
                }],
            }],
        }


def codes_to_hex(codes: bytes) -> bytes:
    return b"<" + codes.hex().encode("ascii") + b">"


def _dict_key(value: str, key: str):
    marker = "/" + key
    index = value.find(marker)
    if index < 0:
        return "null", "null"
    tail = value[index + len(marker):].lstrip()
    if tail.startswith("<<"):
        end = tail.find(">>")
        return "dict", tail[: end + 2] if end >= 0 else tail
    parts = tail.split()
    if len(parts) >= 3 and parts[1:3] == ["0", "R"]:
        return "xref", " ".join(parts[:3])
    return "name", parts[0] if parts else ""


def _fake_fitz(monkeypatch, document: _Type3Document):
    class Font:
        def __init__(self, *, fontbuffer):
            assert fontbuffer == b"font"
            self.glyph_count = document.glyph_count

    monkeypatch.setitem(
        sys.modules,
        "fitz",
        types.SimpleNamespace(open=lambda path: document, Font=Font),
    )


def _run(tmp_path, monkeypatch, **kwargs):
    content = kwargs.pop("content", None)
    semantic = kwargs.pop("semantic", "가나")
    page_semantic = kwargs.pop("page_semantic", semantic)
    span_text = kwargs.pop("span_text", None)
    source = _source(tmp_path / "source.hwpx", semantic)
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    document = _Type3Document(
        semantic=page_semantic,
        span_text=span_text,
        **kwargs,
    )
    if content is not None:
        document.page._content = content
        document._streams[4] = content
    _fake_fitz(monkeypatch, document)
    return quality.inspect(source, pdf)


def test_good_type3_code_zero_differences_and_painted_charprocs_pass(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, codes=b"\x00\x01")
    assert quality.is_passed(result)
    assert result["checked_font_xrefs"] == 1
    assert result["mapped_font_xrefs"] == 1


def test_type3_prefers_decoded_streams_over_opaque_raw_streams(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, codes=b"\x00\x01", opaque_raw=True)
    assert quality.is_passed(result)


def test_type3_falls_back_to_raw_only_when_decoded_stream_is_unavailable(
    tmp_path, monkeypatch
):
    result = _run(tmp_path, monkeypatch, codes=b"\x00\x01", decoded_missing=True)
    assert quality.is_passed(result)


def test_type3_resource_aliases_are_scoped_to_each_page(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    document = _TwoPageAliasDocument()
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == "font_mapping_missing"


def test_type3_spans_share_one_page_identity_budget(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.hwpx", "가나")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    document = _TwoSpanDocument()
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "failed"
    assert result["reason_code"] == "glyph_identity_collapse"


def test_conflicting_chars_and_text_claims_are_unknown(tmp_path, monkeypatch):
    # Source/text claim is 나, while rawdict chars and code 00 claim 가.
    result = _run(
        tmp_path,
        monkeypatch,
        semantic="나",
        page_semantic="가",
        span_text="나",
        codes=b"\x00",
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "semantic_text_ambiguous"


def test_conflicting_multi_syllable_chars_and_text_claims_are_unknown(
    tmp_path, monkeypatch
):
    # Source/text claim is 다, while rawdict chars and codes 00/01 claim 가나.
    result = _run(
        tmp_path,
        monkeypatch,
        semantic="다",
        page_semantic="가나",
        span_text="다",
        codes=b"\x00\x01",
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "semantic_text_ambiguous"


def test_type3_unicode_code_charproc_hash_collapse_fails_closed(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, semantic="가나", codes=b"\x00")
    assert result["state"] == "failed"
    assert result["reason_code"] == "glyph_identity_collapse"


def test_type3_metrics_only_charproc_is_invisible(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        charprocs={0: b"500 0 d0", 1: b"500 0 d0"},
    )
    assert result["state"] == "failed"
    assert result["reason_code"] == "glyph_geometry_missing"


def test_type3_vertical_metric_vector_is_valid(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        charprocs={
            0: b"0 500 d0 0 0 m 500 0 l 500 500 l 0 500 l h f",
            1: b"0 500 d0 0 0 m 450 0 l 450 450 l 0 450 l h f",
        },
    )
    assert quality.is_passed(result)


@pytest.mark.parametrize(
    "charproc,reason",
    [
        (b"500 0 d0 0 0 m 500 0 l n f", "unsupported_graphics_state"),
        (b"500 0 d0 0 0 m 500 0 l f", "glyph_geometry_missing"),
        (b"500 0 d0 0 0 m 0 0 l S", "glyph_geometry_missing"),
        (b"500 0 d0 0 0 0 0 re f", "glyph_geometry_missing"),
    ],
    ids=["discarded_path", "open_zero_area_fill", "zero_length_stroke", "zero_width_rect"],
)
def test_type3_path_lifecycle_never_promotes_blank_geometry(
    tmp_path, monkeypatch, charproc, reason
):
    result = _run(tmp_path, monkeypatch, charprocs={0: charproc})
    assert result["reason_code"] == reason
    assert result["state"] in {"failed", "unknown"}


@pytest.mark.parametrize("operator", ["q", "Q", "cm", "W", "W*", "n"])
def test_type3_charproc_graphics_state_is_unknown(tmp_path, monkeypatch, operator):
    if operator == "cm":
        prefix = b"1 0 0 1 0 0 cm "
    elif operator in {"W", "W*"}:
        prefix = b"0 0 500 500 re " + operator.encode("ascii") + b" "
    else:
        prefix = operator.encode("ascii") + b" "
    result = _run(
        tmp_path,
        monkeypatch,
        charprocs={0: b"500 0 d0 " + prefix + b"0 0 m 500 0 l 500 500 l 0 500 l h f"},
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_type3_charproc_do_xobject_is_unknown(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, charprocs={0: b"500 0 d0 /X1 Do"})
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_charproc_state"


def test_symbol_only_type3_does_not_block_hangul_type3(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, extra_fonts=True)
    assert quality.is_passed(result)


def test_duplicate_resource_font_xrefs_are_unknown(tmp_path, monkeypatch):
    document = _Type3Document(semantic="가", codes=b"\x00")
    document._font_rows.append((6, "n/a", "Type3", "T3Font", "F1", "Identity-H", 1))
    document._objects[3] = "<< /F1 5 0 R >>"
    source = _source(tmp_path / "source.hwpx", "가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == "ambiguous_font_mapping"


def test_duplicate_tounicode_code_entries_are_unknown(tmp_path, monkeypatch):
    document = _Type3Document(semantic="가", codes=b"\x00")
    document._streams[6] = _cmap((0, "가"), (0, "가"))
    source = _source(tmp_path / "source.hwpx", "가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == "font_mapping_missing"


def test_same_charproc_program_for_two_codes_fails_identity(tmp_path, monkeypatch):
    document = _Type3Document(semantic="가나", codes=b"\x00\x01")
    document._objects[8] = "<< /g0 9 0 R /g1 9 0 R >>"
    source = _source(tmp_path / "source.hwpx", "가나")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "failed"
    assert result["reason_code"] == "glyph_identity_collapse"


def test_actualtext_many_hangul_over_one_code_fails_even_high_capacity(tmp_path, monkeypatch):
    semantic = "가나다라마바사아자차카타파하"
    result = _run(
        tmp_path,
        monkeypatch,
        semantic=semantic,
        page_semantic="가",
        span_text=semantic,
        codes=b"\x00",
        font_type="Type3",
        font_ext="n/a",
        glyph_count=10000,
    )
    assert result["state"] == "failed"
    assert result["reason_code"] == "glyph_identity_collapse"


@pytest.mark.parametrize(
    "prefix,suffix,extra_objects,reason",
    [
        (b"3 Tr ", b"", {}, "unsupported_graphics_state"),
        (b"7 Tr ", b"", {}, "unsupported_graphics_state"),
        (b"0 0 0 0 0 0 cm ", b"", {}, "unsupported_graphics_state"),
        (b"0 0 0 500 re W n ", b"", {}, "unsupported_graphics_state"),
        (b"/GS0 gs ", b"", {7: "<< /ca 0 /CA 0 >>"}, "unsupported_graphics_state"),
        (b"/OC /Layer BDC ", b" EMC", {}, "unsupported_graphics_state"),
    ],
)
def test_unsupported_graphics_states_fail_closed(
    tmp_path, monkeypatch, prefix, suffix, extra_objects, reason
):
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=prefix,
        content_suffix=suffix,
        extra_objects=extra_objects,
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == reason


def test_hidden_ocg_is_unknown(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, content_prefix=b"/OC /Layer BDC ", content_suffix=b" EMC")
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_page_polygon_clip_and_nonsingular_cm_are_boundedly_supported(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=(
            b"q 1 0 0 1 0 0 cm 0 0 m 500 0 l 500 500 l 0 500 l h W* n "
        ),
        content_suffix=b" Q",
        trace=[{
            "font": "T3Font",
            "text": "가나",
            "bbox": (100.0, 100.0, 300.0, 300.0),
            "opacity": 1.0,
            "type": 3,
            "seqno": 2,
        }],
        bboxlog=[
            ("fill-path", (100.0, 100.0, 300.0, 300.0)),
            ("stroke-path", (100.0, 100.0, 300.0, 300.0)),
                ("ignore-text", (100.0, 100.0, 300.0, 300.0)),
        ],
    )
    assert quality.is_passed(result)


def _geometry_evidence(
    *,
    text="가나",
    bbox=(100.0, 100.0, 300.0, 300.0),
    opacity=1.0,
    seqno=2,
    path_bbox=None,
    path_kinds=("fill-path", "stroke-path"),
    trace_font="T3Font",
):
    path_bbox = path_bbox or bbox
    return {
        "trace": [{
            "font": trace_font,
            "text": text,
            "bbox": bbox,
            "opacity": opacity,
            "type": 3,
            "seqno": seqno,
        }],
        "bboxlog": [
            (path_kinds[0], path_bbox),
            (path_kinds[1], path_bbox),
            ("ignore-text", bbox),
        ],
    }


def test_page_far_cm_is_unknown_even_with_positive_trace(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        semantic="가나",
        codes=b"\x00\x01",
        content_prefix=b"q 1 0 0 1 10000 10000 cm ",
        content_suffix=b" Q",
        **_geometry_evidence(),
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_page_far_clip_is_unknown_even_with_positive_trace(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        semantic="가나",
        codes=b"\x00\x01",
        content_prefix=(
            b"q 10000 10000 m 10500 10000 l 10500 10500 l 10000 10500 l h W* n "
        ),
        content_suffix=b" Q",
        **_geometry_evidence(),
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_page_zero_opacity_trace_is_unknown(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        **_geometry_evidence(opacity=0.0),
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_page_missing_trace_opacity_is_unknown(tmp_path, monkeypatch):
    evidence = _geometry_evidence()
    del evidence["trace"][0]["opacity"]
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        **evidence,
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_page_geometry_requires_trace_and_bboxlog(tmp_path, monkeypatch):
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


@pytest.mark.parametrize(
    "trace_type,text_kind",
    [(0, "fill-text"), (1, "stroke-text")],
    ids=["fill_trace", "stroke_trace"],
)
def test_page_fill_or_stroke_trace_does_not_need_type3_path_surrogate(
    tmp_path, monkeypatch, trace_type, text_kind
):
    evidence = {
        "trace": [{
            "font": "T3Font",
            "text": "가나",
            "bbox": (100.0, 100.0, 300.0, 300.0),
            "opacity": 1.0,
            "type": trace_type,
            "seqno": 0,
        }],
        "bboxlog": [(text_kind, (100.0, 100.0, 300.0, 300.0))],
    }
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        **evidence,
    )
    assert quality.is_passed(result)


def test_trace_tuple_unicode_values_do_not_remap_ascii_through_cmap(
    tmp_path, monkeypatch
):
    trace_bbox = (100.0, 100.0, 300.0, 300.0)
    document = _Type3Document(
        semantic="가",
        codes=b"\x00",
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        trace=[{
            "font": "T3Font",
            "chars": [
                (32, 0, trace_bbox, (100.0, 100.0)),
                (ord("가"), 0, trace_bbox, (100.0, 100.0)),
            ],
            "bbox": trace_bbox,
            "opacity": 1.0,
            "type": 0,
            "seqno": 0,
        }],
        bboxlog=[("fill-text", trace_bbox)],
    )
    document._streams[6] = _cmap((0, "가"), (32, "나"))
    source = _source(tmp_path / "source.hwpx", "가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert quality.is_passed(result)


def test_page_type3_ignore_trace_without_adjacent_paths_is_unknown(tmp_path, monkeypatch):
    evidence = {
        "trace": [{
            "font": "T3Font",
            "text": "가나",
            "bbox": (100.0, 100.0, 300.0, 300.0),
            "opacity": 1.0,
            "type": 3,
            "seqno": 0,
        }],
        "bboxlog": [("ignore-text", (100.0, 100.0, 300.0, 300.0))],
    }
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        **evidence,
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"path_kinds": ("fill-path", "fill-path")},
        {"path_bbox": (700.0, 700.0, 800.0, 800.0)},
        {"seqno": 3},
    ],
    ids=["missing_stroke", "nonoverlap_path", "late_path"],
)
def test_page_type3_path_evidence_is_adjacent_and_overlapping(
    tmp_path, monkeypatch, kwargs
):
    evidence = _geometry_evidence(**kwargs)
    if kwargs.get("seqno") == 3:
        evidence["bboxlog"].append(("ignore-text", evidence["trace"][0]["bbox"]))
    result = _run(
        tmp_path,
        monkeypatch,
        content_prefix=b"q 1 0 0 1 0 0 cm ",
        content_suffix=b" Q",
        **evidence,
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


def test_repeated_same_syllable_occurrence_is_bound_to_its_clip(
    tmp_path, monkeypatch
):
    content = (
        b"q 700 700 m 900 700 l 900 900 l 700 900 l h W* n "
        b"BT /F1 12 Tf <00> Tj ET Q "
        b"q 0 0 m 500 0 l 500 500 l 0 500 l h W* n "
        b"BT /F1 12 Tf <00> Tj ET Q"
    )
    result = _run(
        tmp_path,
        monkeypatch,
        semantic="가가",
        codes=b"\x00\x00",
        content=content,
        trace=[
            {"font": "T3Font", "text": "가", "bbox": (100.0, 100.0, 200.0, 200.0),
             "opacity": 1.0, "type": 3, "seqno": 2},
            {"font": "T3Font", "text": "가", "bbox": (100.0, 100.0, 200.0, 200.0),
             "opacity": 1.0, "type": 3, "seqno": 5},
        ],
        bboxlog=[
            ("fill-path", (100.0, 100.0, 200.0, 200.0)),
            ("stroke-path", (100.0, 100.0, 200.0, 200.0)),
            ("ignore-text", (100.0, 100.0, 200.0, 200.0)),
            ("fill-path", (100.0, 100.0, 200.0, 200.0)),
            ("stroke-path", (100.0, 100.0, 200.0, 200.0)),
            ("ignore-text", (100.0, 100.0, 200.0, 200.0)),
        ],
    )
    assert result["state"] == "unknown"
    assert result["reason_code"] == "unsupported_graphics_state"


@pytest.mark.parametrize(
    "content,reason",
    [
        (b"<00> Tj", "malformed_pdf_content"),
        (b"/F1 12 Tf BT <00> Tj ET", "malformed_pdf_content"),
        (b"<00> TJ", "malformed_pdf_content"),
        (b"ET BT /F1 12 Tf <00> Tj ET", "malformed_pdf_content"),
        (b"BT BT /F1 12 Tf <00> Tj ET ET", "malformed_pdf_content"),
        (b"BT /F1 12 Tf <00> Tj", "malformed_pdf_content"),
        (b"BT /F1 12 Tf <00> Tj ET", "passed"),
    ],
    ids=[
        "t_j_outside_bt", "tf_outside_bt", "tj_outside_bt", "leading_et",
        "nested_bt", "unclosed_bt", "balanced_bt_et",
    ],
)
def test_type3_text_operators_require_one_balanced_text_object(
    tmp_path, monkeypatch, content, reason
):
    result = _run(tmp_path, monkeypatch, semantic="가", codes=b"\x00", content=content)
    if reason == "passed":
        assert quality.is_passed(result)
    else:
        assert result["state"] == "unknown"
        assert result["reason_code"] == reason


@pytest.mark.parametrize(
    "content,reason",
    [
        pytest.param(b"BT /F1 12 Tf <00", "malformed_pdf_content", id="truncated_hex"),
        pytest.param(b"x" * (2 * 1024 * 1024), "pdf_content_unbounded", id="oversized"),
    ],
)
def test_malformed_or_pathological_content_refuses_boundedly(
    tmp_path, monkeypatch, content, reason
):
    document = _Type3Document(semantic="가", codes=b"\x00")
    document.page._content = content
    document._streams[4] = content
    source = _source(tmp_path / "source.hwpx", "가")
    pdf = tmp_path / "rendered.pdf"
    pdf.write_bytes(b"synthetic pdf")
    _fake_fitz(monkeypatch, document)
    result = quality.inspect(source, pdf)
    assert result["state"] == "unknown"
    assert result["reason_code"] == reason


def test_opt_in_real_fixture_diagnostic_is_skipped_without_env():
    fixture = os.environ.get("RIGORLOOM_TYPE3_FIXTURE")
    if not fixture:
        pytest.skip("set RIGORLOOM_TYPE3_FIXTURE=source.hwpx,pdf for local diagnostics")
    source, pdf = (Path(part) for part in fixture.split(",", 1))
    result = quality.inspect(source, pdf)
    assert result["schema"] == quality.QUALITY_SCHEMA
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == result["artifact_sha256"]
