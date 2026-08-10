"""TDD contract for the receipt-only T89 source coverage scanner."""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hwp_ingress as ingress  # noqa: E402
import hwp_source_coverage as coverage  # noqa: E402


def _entry(name: str, typ: int, *, child: int = ingress.FREESECT,
           left: int = ingress.FREESECT, right: int = ingress.FREESECT,
           start: int = ingress.ENDOFCHAIN, size: int = 0) -> bytes:
    out = bytearray(128)
    encoded = name.encode("utf-16le") + b"\x00\x00"
    out[: len(encoded)] = encoded
    struct.pack_into("<H", out, 64, len(encoded))
    out[66] = typ
    out[67] = 1
    struct.pack_into("<III", out, 68, left, right, child)
    struct.pack_into("<I", out, 116, start)
    struct.pack_into("<Q", out, 120, size)
    return bytes(out)


def _record(tag: int, payload: bytes = b"", *, level: int = 0,
            extended: bool = False) -> bytes:
    size = 0xFFF if extended else len(payload)
    header = (tag & 0x3FF) | ((level & 0x3FF) << 10) | ((size & 0xFFF) << 20)
    out = struct.pack("<I", header)
    if extended:
        out += struct.pack("<I", len(payload))
    return out + payload


def _paragraph(text: str = "hello", *, level: int = 0) -> bytes:
    encoded = bytearray()
    units = 0
    control_mask = 0
    for char in text:
        code = ord(char)
        if code == 0x09:
            encoded += struct.pack("<H", code) + b"\x00" * 14
            control_mask = 1
            units += 7
        else:
            encoded += char.encode("utf-16le")
        units += 1
    header = bytearray(24)
    struct.pack_into("<I", header, 0, units)
    struct.pack_into("<I", header, 4, control_mask)
    struct.pack_into("<H", header, 12, 1)
    return (
        _record(coverage.TAG_PARA_HEADER, bytes(header), level=level)
        + _record(coverage.TAG_PARA_TEXT, bytes(encoded), level=level + 1)
        + _record(coverage.TAG_PARA_CHAR_SHAPE, b"\x00" * 8, level=level + 1)
    )


def _raw_paragraph_payload(text_payload: bytes, units: int, *,
                           control_mask: int = 0, level: int = 0,
                           extended_header: bool = False,
                           char_shape_count: int = 1,
                           line_count: int = 0,
                           range_count: int = 0) -> bytes:
    header = bytearray(24)
    struct.pack_into("<I", header, 0, units)
    struct.pack_into("<I", header, 4, control_mask)
    struct.pack_into("<H", header, 12, char_shape_count)
    struct.pack_into("<H", header, 14, range_count)
    struct.pack_into("<H", header, 16, line_count)
    out = _record(coverage.TAG_PARA_HEADER, bytes(header), level=level,
                  extended=extended_header)
    out += _record(coverage.TAG_PARA_TEXT, text_payload, level=level + 1)
    if char_shape_count:
        out += _record(coverage.TAG_PARA_CHAR_SHAPE,
                       b"\x00" * (8 * char_shape_count), level=level + 1)
    if line_count:
        out += _record(coverage.TAG_PARA_LINE_SEG,
                       b"\x00" * (36 * line_count), level=level + 1)
    if range_count:
        out += _record(coverage.TAG_PARA_RANGE_TAG,
                       b"\x00" * (12 * range_count), level=level + 1)
    return out


def _control_paragraph(code: int, *, payload_units: int = 8) -> bytes:
    payload = struct.pack("<H", code)
    if code not in (0x00, 0x0A, 0x0D, 0x18):
        payload += b"\x00" * 14
    return _raw_paragraph_payload(payload, payload_units,
                                  control_mask=1)


def _cfb_hwp_sections(sections: list[bytes], *, compressed: bool = False,
                      names: list[str] | None = None,
                      section_sizes: list[int] | None = None) -> bytes:
    """Minimal strict CFB v3 fixture with direct BodyText Section streams."""
    sector = 512
    header = bytearray(256)
    header[:32] = b"HWP Document File" + b"\x00" * 15
    header[32:36] = bytes((0, 0, 1, 5))
    struct.pack_into("<I", header, 36, 1 if compressed else 0)
    streams = [bytes(header)] + list(sections)
    mini_entries: list[int] = []
    mini_stream = bytearray()
    starts: list[int] = []
    for stream in streams:
        starts.append(len(mini_entries))
        count = max(1, (len(stream) + 63) // 64)
        mini_entries.extend([ingress.ENDOFCHAIN] * count)
        for i in range(count - 1):
            mini_entries[starts[-1] + i] = starts[-1] + i + 1
        mini_stream.extend(stream)
        mini_stream.extend(b"\x00" * ((-len(stream)) % 64))
    root_size = max(64, len(mini_stream))
    root_sectors = (root_size + sector - 1) // sector
    root_size = root_sectors * sector
    section_names = names or [f"Section{i}" for i in range(len(sections))]
    if len(section_names) != len(sections):
        raise ValueError("names")
    entries = [
        _entry("Root Entry", 5, child=1, start=4,
               size=root_size),
        _entry("FileHeader", 2, right=2, start=starts[0], size=256),
        _entry("DocInfo", 2, right=3),
        _entry("BodyText", 1, child=4),
    ]
    for i, name in enumerate(section_names):
        right = 5 + i if i + 1 < len(section_names) else ingress.FREESECT
        size = len(sections[i]) if section_sizes is None else section_sizes[i]
        entries.append(_entry(name, 2, right=right,
                              start=starts[i + 1] if size else ingress.ENDOFCHAIN,
                              size=size))
    directory = b"".join(entries).ljust(sector * 2, b"\x00")
    root_count = root_sectors
    fat = [ingress.FREESECT] * (sector // 4)
    fat[0] = 1
    fat[1] = ingress.ENDOFCHAIN
    fat[2] = ingress.FATSECT
    fat[3] = ingress.ENDOFCHAIN
    for i in range(root_count):
        sid = 4 + i
        fat[sid] = sid + 1 if i + 1 < root_count else ingress.ENDOFCHAIN
    fat_sector = struct.pack("<%dI" % (sector // 4), *fat)
    mini_fat = [ingress.FREESECT] * (sector // 4)
    for i, nxt in enumerate(mini_entries):
        mini_fat[i] = nxt
    mini_fat_sector = struct.pack("<%dI" % (sector // 4), *mini_fat)
    cfb_header = bytearray(sector)
    cfb_header[:8] = ingress.CFB_SIGNATURE
    struct.pack_into("<HHHH", cfb_header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", cfb_header, 32, 6)
    struct.pack_into("<IIIIIIII", cfb_header, 40,
                     0, 1, 0, 0, 4096, 3, 1, ingress.ENDOFCHAIN)
    for i in range(109):
        struct.pack_into("<I", cfb_header, 76 + 4 * i, ingress.FREESECT)
    struct.pack_into("<I", cfb_header, 76, 2)
    return (bytes(cfb_header) + directory + fat_sector + mini_fat_sector
            + bytes(mini_stream).ljust(root_size, b"\x00"))


def _write(path: Path, sections: list[bytes], **kwargs) -> Path:
    path.write_bytes(_cfb_hwp_sections(sections, **kwargs))
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "hwp-source-coverage"
    root.mkdir()
    return root


def test_simple_text_receipt_is_unknown_and_closed(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "unknown"
    assert result["coverage"]["scope"] == coverage.COVERAGE_SCOPE
    assert result["coverage"]["not_scanned_tokens"] == coverage.NOT_SCANNED_TOKENS
    assert result["coverage"]["state"] == "complete"
    assert result["comparison"] == {"state": "unknown"}
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert set(result) == {
        "schema", "status", "source", "scanner", "coverage",
        "eligibility", "comparison", "render", "proof_grade",
        "submission_grade",
    }
    encoded = json.dumps(result, ensure_ascii=False)
    assert "hello" not in encoded
    assert "Section0" not in encoded
    assert "stdout" not in encoded and "stderr" not in encoded
    assert result["scanner"] == {
        "name": "rigorloom_hwp5_record_coverage", "version": 1,
        "target": {
            "package": "syhwp", "version": "0.0.7",
            "commit": "d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed",
        },
        "execution": "independent_no_external_tool",
    }


def test_unsupported_controls_are_analyzed_ineligible_without_raw_ids(tmp_path: Path):
    source = _write(tmp_path / "table.hwp", [
        _paragraph("x") + _record(coverage.TAG_CTRL_HEADER, b"tbl "),
    ])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "ineligible"
    assert "ctrl.table" in result["coverage"]["blocking_tokens"]
    encoded = json.dumps(result)
    assert "tbl " not in encoded
    assert f'"tag": {coverage.TAG_CTRL_HEADER}' not in encoded


def test_unknown_record_is_unknown_and_coverage_complete(tmp_path: Path):
    source = _write(tmp_path / "future.hwp", [_paragraph() + _record(0x3FF, b"x")])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "unknown"
    assert result["coverage"]["state"] == "complete"
    assert "record.unknown" in result["coverage"]["blocking_tokens"]


@pytest.mark.parametrize("bad", [
    b"\x00",                         # partial header
    struct.pack("<I", 0xFFF00000),  # extended size with no extension
    _record(coverage.TAG_PARA_TEXT, b"\x00"),  # odd-byte payload
])
def test_record_truncation_odd_and_partial_refuse_without_public_run(
        tmp_path: Path, bad: bytes):
    source = _write(tmp_path / "bad.hwp", [bad], compressed=False)
    result = coverage.inspect_path(source)
    assert result["status"] == "refused"
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize("names", [["Section1"], ["Section0", "Section2"],
                                    ["Section0", "section0"]])
def test_section_gap_alias_and_missing_zero_refuse(tmp_path: Path, names: list[str]):
    source = _write(tmp_path / "sections.hwp", [_paragraph()] * len(names),
                    names=names)
    result = coverage.inspect_path(source)
    assert result["status"] == "refused"


def test_zero_length_section_is_not_a_false_pass(tmp_path: Path):
    source = _write(tmp_path / "empty.hwp", [b""], compressed=False,
                    section_sizes=[0])
    result = coverage.inspect_path(source)
    assert result["status"] == "refused"
    assert result["eligibility"] == "unknown"


def test_raw_deflate_requires_exact_termination(tmp_path: Path):
    compressed = zlib.compressobj(wbits=-15)
    raw = compressed.compress(_paragraph()) + compressed.flush()
    good = _write(tmp_path / "compressed.hwp", [raw], compressed=True)
    assert coverage.inspect_path(good)["eligibility"] == "unknown"
    trailing = _write(tmp_path / "trailing.hwp", [raw + b"x"], compressed=True)
    assert coverage.inspect_path(trailing)["status"] == "refused"


def test_raw_deflate_hwp_crc_size_trailer_is_checked(tmp_path: Path):
    compressed = zlib.compressobj(wbits=-15)
    plain = _paragraph()
    raw = compressed.compress(plain) + compressed.flush()
    trailer = struct.pack("<II", zlib.crc32(plain) & 0xFFFFFFFF, len(plain))
    good = _write(tmp_path / "trailer-good.hwp", [raw + trailer], compressed=True)
    assert coverage.inspect_path(good)["status"] == "analyzed"
    bad_crc = bytearray(trailer)
    bad_crc[0] ^= 1
    bad = _write(tmp_path / "trailer-bad-crc.hwp", [raw + bytes(bad_crc)], compressed=True)
    assert coverage.inspect_path(bad)["status"] == "refused"
    bad_size = bytearray(trailer)
    bad_size[4] ^= 1
    bad = _write(tmp_path / "trailer-bad-size.hwp", [raw + bytes(bad_size)], compressed=True)
    assert coverage.inspect_path(bad)["status"] == "refused"
    extra = _write(tmp_path / "trailer-extra.hwp", [raw + trailer + b"x"], compressed=True)
    assert coverage.inspect_path(extra)["status"] == "refused"


def test_receipt_publication_and_verify_bind_current_source(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    assert receipt.is_file()
    assert coverage.main(["verify", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    source.write_bytes(source.read_bytes() + b"x")
    assert coverage.main(["verify", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_ineligible_receipt_publishes_but_exits_three(tmp_path: Path):
    source = _write(tmp_path / "tab.hwp", [_paragraph("x\t")], compressed=False)
    root = _root(tmp_path)
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", "abcdef0123456789"]) == 3
    assert (root / "abcdef0123456789" / "receipt.json").is_file()


def test_publication_does_not_clobber_existing_run(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    before = receipt.read_bytes()
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    assert receipt.read_bytes() == before


def test_receipt_duplicate_and_unknown_field_verifier_refuse(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    raw = receipt.read_text(encoding="utf-8")
    receipt.write_text(raw.replace('"schema":', '"schema":"foreign", "schema":', 1),
                       encoding="utf-8")
    assert coverage.main(["verify", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt.write_text(raw, encoding="utf-8")
    payload = json.loads(raw)
    payload["unexpected"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert coverage.main(["verify", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    payload.pop("unexpected")
    payload["eligibility"] = "eligible"
    receipt.write_bytes(coverage._json_bytes(payload))
    with pytest.raises(coverage.CoverageError) as exc:
        coverage._read_receipt(receipt)
    assert exc.value.reason == "receipt_state_invalid"


def test_cli_help_is_cp949_safe_and_usage_is_two(tmp_path: Path):
    command = [sys.executable, str(SCRIPTS / "hwp_source_coverage.py"), "--help"]
    result = subprocess.run(command, capture_output=True, encoding="cp949",
                            errors="replace")
    assert result.returncode == 0
    assert "source coverage" in result.stdout.lower()
    assert subprocess.run([sys.executable, str(SCRIPTS / "hwp_source_coverage.py")],
                          capture_output=True).returncode == 2


def test_direct_api_invalid_path_types_fail_closed(tmp_path: Path):
    root = _root(tmp_path)
    inspected = coverage.inspect_path(None)
    assert inspected["status"] == "refused"
    assert inspected["reason"] == "input_unavailable"
    with pytest.raises(coverage.CoverageError) as inspect_exc:
        coverage.inspect_and_publish(
            None, coverage_root=root, run_id="0123456789abcdef")
    assert inspect_exc.value.reason == "input_unavailable"
    with pytest.raises(coverage.CoverageError) as verify_exc:
        coverage.verify_path(
            None, coverage_root=root, run_id="0123456789abcdef")
    assert verify_exc.value.reason == "input_unavailable"


def test_extended_record_size_positive_and_truncated_refuse():
    header = bytearray(24)
    struct.pack_into("<I", header, 0, 1)
    struct.pack_into("<H", header, 12, 1)
    raw = _raw_paragraph_payload(b"a\x00", 1, extended_header=True)
    assert coverage._scan_records(raw)["eligibility"] == "unknown"
    with pytest.raises(coverage.CoverageError):
        coverage._scan_records(_record(coverage.TAG_PARA_HEADER,
                                       bytes(header), extended=True)[:-1])


@pytest.mark.parametrize("size", [22, 23, 25, 26, 32])
def test_para_header_requires_exact_v1_wire_size(size: int):
    header = bytearray(size)
    struct.pack_into("<I", header, 0, 1)
    struct.pack_into("<H", header, 12, 1)
    raw = (
        _record(coverage.TAG_PARA_HEADER, bytes(header))
        + _record(coverage.TAG_PARA_TEXT, b"a\x00", level=1)
        + _record(coverage.TAG_PARA_CHAR_SHAPE, b"\x00" * 8, level=1)
    )
    with pytest.raises(coverage.CoverageError) as exc:
        coverage._scan_records(raw)
    assert exc.value.reason == "para_header_shape_unsupported"


def test_para_header_high_count_flag_is_not_silently_masked():
    header = bytearray(24)
    struct.pack_into("<I", header, 0, 0x80000001)
    struct.pack_into("<H", header, 12, 1)
    raw = (
        _record(coverage.TAG_PARA_HEADER, bytes(header))
        + _record(coverage.TAG_PARA_TEXT, b"a\x00", level=1)
        + _record(coverage.TAG_PARA_CHAR_SHAPE, b"\x00" * 8, level=1)
    )
    result = coverage._scan_records(raw)
    assert result["state"] == "incomplete"
    assert result["eligibility"] == "ineligible"
    assert "paragraph.header_high_flag" in result["blocking_tokens"]


@pytest.mark.parametrize("order", ["HCTL", "HLCT", "HCLT"])
def test_supported_paragraph_children_must_follow_canonical_order(order: str):
    header = bytearray(24)
    struct.pack_into("<I", header, 0, 1)
    struct.pack_into("<H", header, 12, 1)
    struct.pack_into("<H", header, 16, 1)
    parts = {
        "H": _record(coverage.TAG_PARA_HEADER, bytes(header)),
        "T": _record(coverage.TAG_PARA_TEXT, b"a\x00", level=1),
        "C": _record(coverage.TAG_PARA_CHAR_SHAPE, b"\x00" * 8, level=1),
        "L": _record(coverage.TAG_PARA_LINE_SEG, b"\x00" * 36, level=1),
    }
    result = coverage._scan_records(b"".join(parts[token] for token in order))
    assert result["state"] == "incomplete"
    assert "paragraph.child_order_mismatch" in result["blocking_tokens"]


def test_record_level_jump_refuses():
    with pytest.raises(coverage.CoverageError):
        coverage._scan_records(
            _record(coverage.TAG_PARA_HEADER, b"\x00" * 24)
            + _record(coverage.TAG_PARA_TEXT, b"a\x00", level=2))


def test_raw_deflate_truncation_refuses(tmp_path: Path):
    compressor = zlib.compressobj(wbits=-15)
    raw = compressor.compress(_paragraph()) + compressor.flush()
    source = _write(tmp_path / "truncated-deflate.hwp", [raw[:-1]], compressed=True)
    assert coverage.inspect_path(source)["status"] == "refused"


@pytest.mark.parametrize("text", [" a", "a ", "a  b"])
def test_lossy_whitespace_is_ineligible(tmp_path: Path, text: str):
    source = _write(tmp_path / "whitespace.hwp", [_paragraph(text)])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "ineligible"


def test_line_break_and_unpaired_surrogate_refuse_or_block(tmp_path: Path):
    line = _write(tmp_path / "line.hwp", [_control_paragraph(0x0A, payload_units=1)])
    result = coverage.inspect_path(line)
    assert result["eligibility"] == "ineligible"
    bad_payload = struct.pack("<H", 0xD800)
    surrogate = _write(tmp_path / "surrogate.hwp",
                       [_raw_paragraph_payload(bad_payload, 1)])
    assert coverage.inspect_path(surrogate)["status"] == "refused"
    zero_control = _write(tmp_path / "zero-control.hwp",
                          [_control_paragraph(0x00, payload_units=1)])
    zero_result = coverage.inspect_path(zero_control)
    assert zero_result["eligibility"] == "unknown"
    assert "control.unknown" in zero_result["coverage"]["blocking_tokens"]


@pytest.mark.parametrize("code,token", [
    (0x09, "control.tab"), (0x03, "control.field"),
    (0x02, "control.section"), (0x0B, "control.object"),
])
def test_embedded_control_families_are_ineligible(tmp_path: Path,
                                                  code: int, token: str):
    source = _write(tmp_path / f"control-{code:x}.hwp",
                    [_control_paragraph(code)])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "ineligible"
    assert token in result["coverage"]["blocking_tokens"]


def test_ctrl_header_wire_endianness_is_tokenized_without_raw_id(tmp_path: Path):
    # The UINT32 value is commonly observed on wire as reversed bytes.
    source = _write(tmp_path / "wire-table.hwp",
                    [_paragraph() + _record(coverage.TAG_CTRL_HEADER, b" lbt")])
    result = coverage.inspect_path(source)
    assert result["eligibility"] == "ineligible"
    assert "ctrl.table" in result["coverage"]["blocking_tokens"]
    assert " lbt" not in json.dumps(result)


def test_count_and_mask_mismatch_is_not_eligible(tmp_path: Path):
    source = _write(tmp_path / "mismatch.hwp",
                    [_raw_paragraph_payload(b"a\x00", 2, control_mask=1)])
    result = coverage.inspect_path(source)
    assert result["eligibility"] == "ineligible"
    assert "paragraph.text_count_mismatch" in result["coverage"]["blocking_tokens"]
    assert "paragraph.control_mask_mismatch" in result["coverage"]["blocking_tokens"]


def test_missing_declared_shape_child_is_incomplete(tmp_path: Path):
    raw = _raw_paragraph_payload(b"a\x00", 1, char_shape_count=1)
    source = _write(tmp_path / "missing-shape.hwp", [raw[:-12]])
    result = coverage.inspect_path(source)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "ineligible"
    assert result["coverage"]["state"] == "incomplete"
    assert "paragraph.char_shape_count_mismatch" in result["coverage"]["blocking_tokens"]


def test_record_and_document_limits_are_explicit(monkeypatch):
    monkeypatch.setattr(coverage, "MAX_RECORDS_PER_SECTION", 2)
    with pytest.raises(coverage.CoverageError) as exc:
        coverage._scan_records(_paragraph())
    assert exc.value.reason == "record_limit"


def test_refusal_leaves_no_public_run(tmp_path: Path):
    source = _write(tmp_path / "bad.hwp", [b"\x00"], compressed=False)
    root = _root(tmp_path)
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", "0123456789abcdef"]) == 3
    assert list(root.iterdir()) == []


def test_verify_rescans_and_rejects_forged_eligibility(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["coverage"]["blocking_tokens"] = ["control.tab"]
    payload["eligibility"] = "ineligible"
    receipt.write_bytes(coverage._json_bytes(payload))
    assert coverage.main(["verify", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_publication_rebinds_source_before_owner_commit(tmp_path: Path,
                                                        monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    original = coverage._read_input_once
    calls = {"n": 0}

    def mutate_after_capture(path):
        calls["n"] += 1
        if calls["n"] == 2:
            path.write_bytes(path.read_bytes() + b"x")
        return original(path)

    monkeypatch.setattr(coverage, "_read_input_once", mutate_after_capture)
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", "0123456789abcdef"]) == 3
    assert list(root.iterdir()) == []


def test_verify_rejects_same_inode_receipt_overwrite_after_first_read(
        tmp_path: Path, monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    original = coverage._read_receipt
    calls = {"n": 0}

    def overwrite(path, *, allow_hardlink=False):
        result = original(path, allow_hardlink=allow_hardlink)
        calls["n"] += 1
        if calls["n"] == 1:
            payload, _ = result
            payload["coverage"]["blocking_tokens"] = ["control.tab"]
            payload["eligibility"] = "ineligible"
            path.write_bytes(coverage._json_bytes(payload))
        return result

    monkeypatch.setattr(coverage, "_read_receipt", overwrite)
    with pytest.raises(coverage.CoverageError) as exc:
        coverage.verify_path(source, coverage_root=root, run_id=run_id)
    assert exc.value.reason in {"receipt_content_mismatch", "receipt_changed"}


def test_verify_rejects_source_overwrite_after_first_read(tmp_path: Path,
                                                          monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    original = coverage._read_input_once
    calls = {"n": 0}

    def overwrite(path):
        data = original(path)
        calls["n"] += 1
        if calls["n"] == 1:
            path.write_bytes(data + b"x")
        return data

    monkeypatch.setattr(coverage, "_read_input_once", overwrite)
    with pytest.raises(coverage.CoverageError) as exc:
        coverage.verify_path(source, coverage_root=root, run_id=run_id)
    assert exc.value.reason == "input_changed"


def test_verify_rejects_receipt_hardlink(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    link = tmp_path / "receipt-link"
    try:
        os.link(receipt, link)
    except OSError:
        pytest.skip("hardlinks unavailable")
    try:
        with pytest.raises(coverage.CoverageError) as exc:
            coverage.verify_path(source, coverage_root=root, run_id=run_id)
        assert exc.value.reason in {"receipt_invalid", "receipt_layout_invalid"}
    finally:
        link.unlink(missing_ok=True)


def test_verify_rejects_run_directory_swap(tmp_path: Path, monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    run_path = root / run_id
    original = coverage._read_receipt
    calls = {"n": 0}

    def swap(path, *, allow_hardlink=False):
        result = original(path, allow_hardlink=allow_hardlink)
        calls["n"] += 1
        if calls["n"] == 1:
            foreign = tmp_path / "foreign-swap"
            foreign.mkdir()
            shutil.copy2(path, foreign / "receipt.json")
            shutil.rmtree(run_path)
            foreign.rename(run_path)
        return result

    monkeypatch.setattr(coverage, "_read_receipt", swap)
    with pytest.raises(coverage.CoverageError) as exc:
        coverage.verify_path(source, coverage_root=root, run_id=run_id)
    assert exc.value.reason == "receipt_changed"


def test_verify_rejects_run_directory_symlink(tmp_path: Path):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    run_path = root / run_id
    backup = tmp_path / "run-backup"
    foreign = tmp_path / "foreign-run"
    foreign.mkdir()
    shutil.copy2(run_path / "receipt.json", foreign / "receipt.json")
    shutil.move(str(run_path), str(backup))
    try:
        try:
            os.symlink(str(foreign), str(run_path), target_is_directory=True)
        except OSError:
            shutil.move(str(backup), str(run_path))
            pytest.skip("directory symlinks unavailable")
        with pytest.raises(coverage.CoverageError) as exc:
            coverage.verify_path(source, coverage_root=root, run_id=run_id)
        assert exc.value.reason == "receipt_layout_invalid"
    finally:
        if run_path.is_symlink():
            run_path.unlink()


def test_public_receipt_mutation_during_before_commit_refuses_and_preserves_foreign(
        tmp_path: Path, monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    receipt = root / run_id / "receipt.json"
    original = coverage._read_input_once
    calls = {"n": 0}

    def mutate_receipt(path):
        data = original(path)
        calls["n"] += 1
        if calls["n"] == 2 and receipt.is_file():
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["coverage"]["blocking_tokens"] = ["control.tab"]
            payload["eligibility"] = "ineligible"
            receipt.write_bytes(coverage._json_bytes(payload))
        return data

    monkeypatch.setattr(coverage, "_read_input_once", mutate_receipt)
    assert coverage.main(["inspect", str(source), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    if receipt.exists():
        assert not any(p.name.startswith(".t89-owner-")
                       for p in (root / run_id).iterdir())


def test_publication_cleanup_fault_cannot_rewrite_committed_result(
        tmp_path: Path, monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    real = coverage.tempfile.TemporaryDirectory

    class FailingCleanup(real):
        def __exit__(self, exc_type, exc_value, traceback):
            result = super().__exit__(exc_type, exc_value, traceback)
            if Path(self.name).name.startswith(f".{coverage.ROOT_LEAF}-"):
                raise OSError("injected cleanup failure")
            return result

    monkeypatch.setattr(coverage.tempfile, "TemporaryDirectory", FailingCleanup)
    result = coverage.inspect_and_publish(
        source, coverage_root=root, run_id=run_id)
    assert result["status"] == "analyzed"
    receipt = root / run_id / "receipt.json"
    assert receipt.stat().st_nlink == 1
    checked = coverage.verify_path(source, coverage_root=root, run_id=run_id)
    assert checked == result


def test_publication_precleanup_fault_still_leaves_one_verifiable_link(
        tmp_path: Path, monkeypatch):
    source = _write(tmp_path / "simple.hwp", [_paragraph()])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    real = coverage.tempfile.TemporaryDirectory

    class NoCleanup(real):
        def __exit__(self, exc_type, exc_value, traceback):
            if Path(self.name).name.startswith(f".{coverage.ROOT_LEAF}-"):
                raise OSError("injected precleanup failure")
            return super().__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(coverage.tempfile, "TemporaryDirectory", NoCleanup)
    result = coverage.inspect_and_publish(
        source, coverage_root=root, run_id=run_id)
    assert result["status"] == "analyzed"
    receipt = root / run_id / "receipt.json"
    assert receipt.stat().st_nlink == 1
    checked = coverage.verify_path(source, coverage_root=root, run_id=run_id)
    assert checked == result


def test_input_parent_symlink_cannot_bypass_root_overlap(tmp_path: Path):
    root = _root(tmp_path)
    source = _write(root / "source.hwp", [_paragraph()])
    alias = tmp_path / "coverage-alias"
    try:
        os.symlink(str(root), str(alias), target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    run_id = "0123456789abcdef"
    with pytest.raises(coverage.CoverageError) as exc:
        coverage.inspect_and_publish(
            alias / source.name, coverage_root=root, run_id=run_id)
    assert exc.value.reason in {"input_root_overlap", "input_unavailable"}
    assert not (root / run_id).exists()


def test_public_manifest_is_never_a_semantic_pass():
    manifest_path = Path(__file__).parents[2] / "tests" / "corpus" / "forms" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base = manifest_path.parent
    observed = {}
    for document in manifest["documents"]:
        if document.get("format") != "hwp":
            continue
        result = coverage.inspect_path(base / document["path"])
        assert result["status"] == "analyzed"
        assert result["eligibility"] in {"ineligible", "unknown"}
        observed[result["eligibility"]] = observed.get(result["eligibility"], 0) + 1
    assert observed == {"ineligible": 8, "unknown": 2}
