"""TDD contract for the receipt-only T90 DocInfo coverage scanner."""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hwp_docinfo_coverage as coverage  # noqa: E402
import hwp_ingress as ingress  # noqa: E402
import hwp_source_coverage as source  # noqa: E402


def _entry(name: str, typ: int, *, child: int = ingress.FREESECT,
           left: int = ingress.FREESECT,
           right: int = ingress.FREESECT,
           start: int = ingress.ENDOFCHAIN, size: int = 0) -> bytes:
    out = bytearray(128)
    encoded = name.encode("utf-16le") + b"\x00\x00"
    out[:len(encoded)] = encoded
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
    return struct.pack("<I", header) + (
        struct.pack("<I", len(payload)) if extended else b"") + payload


ID_KEYS = [
    "bin_data", "face_name.kor", "face_name.eng", "face_name.han",
    "face_name.jpn", "face_name.other", "face_name.symbol", "face_name.user",
    "border_fill", "char_shape", "tab_def", "numbering", "bullet",
    "para_shape", "style", "memo_shape", "track_change", "track_change_author",
]


def _id_payload(counts: list[int]) -> bytes:
    return struct.pack("<18i", *counts)


def _props() -> bytes:
    return b"\x00" * 26


def _body(*, para_shape: int = 0, style: int = 0, charshape: int = 0,
         positions: list[tuple[int, int]] | None = None,
         char_count: int = 1, charshape_count: int = 1) -> bytes:
    positions = positions if positions is not None else [(0, charshape)]
    header = bytearray(24)
    struct.pack_into("<I", header, 0, char_count)
    struct.pack_into("<H", header, 8, para_shape)
    header[10] = style
    struct.pack_into("<H", header, 12, charshape_count)
    text = b"a\x00" * char_count
    refs = b"".join(struct.pack("<II", pos, shape) for pos, shape in positions)
    return (_record(source.TAG_PARA_HEADER, bytes(header), level=0)
            + _record(source.TAG_PARA_TEXT, text, level=1)
            + _record(source.TAG_PARA_CHAR_SHAPE, refs, level=1))


def _docinfo(*, counts: list[int] | None = None,
             records: list[bytes] | None = None,
             version_tail: bytes = b"") -> bytes:
    if counts is None:
        counts = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0]
    if records is not None:
        return b"".join(records)
    out = [_record(source.TAG_DOCUMENT_PROPERTIES, _props()),
           _record(source.TAG_ID_MAPPINGS, _id_payload(counts) + version_tail)]
    for index in range(1, 8):
        out.append(_record(source.TAG_FACE_NAME, b"\x00", level=1))
    for tag, payload, count in (
            (source.TAG_BORDER_FILL, b"\x00" * 4, counts[8]),
            (source.TAG_CHAR_SHAPE, b"\x00" * 72, counts[9]),
            (source.TAG_TAB_DEF, b"\x00" * 14, counts[10]),
            (source.TAG_NUMBERING, b"\x00" * 4, counts[11]),
            (source.TAG_BULLET, b"\x00" * 10, counts[12]),
            (source.TAG_PARA_SHAPE, b"\x00" * 54, counts[13]),
            (source.TAG_STYLE, b"\x00" * 4, counts[14]),
    ):
        out.extend(_record(tag, payload, level=1) for _ in range(count))
    return b"".join(out)


def _hwp(path: Path, *, docinfo: bytes | None = None,
         body: bytes | None = None, compressed: bool = False,
         section_raw: bytes | None = None) -> Path:
    sector = 512
    file_header = bytearray(256)
    file_header[:32] = b"HWP Document File" + b"\x00" * 15
    file_header[32:36] = bytes((0, 0, 1, 5))
    struct.pack_into("<I", file_header, 36, 1 if compressed else 0)
    docinfo = _docinfo() if docinfo is None else docinfo
    body = _body() if body is None else body
    streams = [bytes(file_header), docinfo, body if section_raw is None else section_raw]
    if compressed:
        packed: list[bytes] = [streams[0]]
        for item in streams[1:]:
            encoder = zlib.compressobj(wbits=-15)
            packed.append(encoder.compress(item) + encoder.flush())
        streams = packed
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
    entries = [
        _entry("Root Entry", 5, child=1, start=4, size=root_size),
        _entry("FileHeader", 2, right=2, start=starts[0], size=256),
        _entry("DocInfo", 2, right=3, start=starts[1], size=len(streams[1])),
        _entry("BodyText", 1, child=4),
        _entry("Section0", 2, start=starts[2], size=len(streams[2])),
    ]
    directory = b"".join(entries).ljust(sector * 2, b"\x00")
    fat = [ingress.FREESECT] * (sector // 4)
    fat[0] = 1
    fat[1] = ingress.ENDOFCHAIN
    fat[2] = ingress.FATSECT
    fat[3] = ingress.ENDOFCHAIN
    for i in range(root_sectors):
        sid = 4 + i
        fat[sid] = sid + 1 if i + 1 < root_sectors else ingress.ENDOFCHAIN
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
    path.write_bytes(bytes(cfb_header) + directory + fat_sector + mini_fat_sector
                     + bytes(mini_stream).ljust(root_size, b"\x00"))
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / coverage.ROOT_LEAF
    root.mkdir()
    return root


def test_t90_contract_constants_are_closed():
    assert coverage.SCHEMA == "rigorloom/hwp-docinfo-coverage/v1"
    assert coverage.ROOT_LEAF == "hwp-docinfo-coverage"
    assert coverage.CLAIM_SCOPE == "docinfo_record_cardinality_and_bodytext_reference_bounds_v1"


def test_t90_never_claims_eligibility():
    assert coverage.EXIT_OK == 0
    assert coverage.EXIT_USAGE == 2
    assert coverage.EXIT_REFUSED == 3


def test_t90_not_scanned_tokens_are_explicit_and_closed():
    assert set(coverage.NOT_SCANNED_TOKENS) == {
        "definition.payload_semantics", "definition.char_shape_semantics",
        "definition.face_name_bstr", "definition.style_names",
        "definition.style_redirects", "definition.para_shape_semantics",
        "definition.numbering_formats", "definition.bullet_glyphs",
        "definition.generated_numbering_state",
        "definition.versioned_payload_tails", "definition.track_change_graph",
        "paragraph.split_state", "paragraph.char_shape_position_semantics",
    }


def test_valid_docinfo_receipt_is_unknown_and_closed(tmp_path: Path):
    source_path = _hwp(tmp_path / "valid.hwp")
    result = coverage.inspect_path(source_path)
    assert result["status"] == "analyzed"
    assert result["eligibility"] == "unknown"
    assert result["coverage"]["scope"] == coverage.CLAIM_SCOPE
    assert result["coverage"]["docinfo_records"] == 14
    assert result["coverage"]["definition_counts"] == {
        "bin_data": 0,
        "face_name.kor": 1,
        "face_name.eng": 1,
        "face_name.han": 1,
        "face_name.jpn": 1,
        "face_name.other": 1,
        "face_name.symbol": 1,
        "face_name.user": 1,
        "face_name.total": 7,
        "border_fill": 1,
        "char_shape": 1,
        "tab_def": 1,
        "numbering": 0,
        "bullet": 0,
        "para_shape": 1,
        "style": 1,
        "memo_shape": 0,
        "track_change": 0,
        "track_change_author": 0,
    }
    assert result["coverage"]["bodytext_sections"] == 1
    assert result["coverage"]["bodytext_paragraphs"] == 1
    assert result["coverage"]["bodytext_para_shape_refs"] == 1
    assert result["coverage"]["bodytext_style_refs"] == 1
    assert result["coverage"]["bodytext_char_shape_refs"] == 1
    assert result["coverage"]["bodytext_char_shape_position_refs"] == 1
    assert result["coverage"]["blocking_tokens"] == []
    assert result["comparison"] == {"state": "unknown"}
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert set(result) == {
        "schema", "status", "source", "scanner", "coverage",
        "eligibility", "comparison", "render", "proof_grade",
        "submission_grade",
    }
    encoded = json.dumps(result)
    assert "Section0" not in encoded
    assert "DocInfo" not in encoded
    assert '"a"' not in encoded
    assert "stdout" not in encoded and "stderr" not in encoded


def test_count_zero_plus_zero_based_reference_is_refused(tmp_path: Path):
    counts = [0] * 18
    docinfo = _docinfo(counts=counts)
    path = _hwp(tmp_path / "zero.hwp", docinfo=docinfo,
                body=_body(para_shape=0, style=0, charshape=0))
    result = coverage.inspect_path(path)
    assert result["status"] == "refused"
    assert result["eligibility"] == "unknown"


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered"])
def test_definition_group_cardinality_and_order_refuse(tmp_path: Path,
                                                        mutation: str):
    valid = _docinfo()
    records = []
    offset = 0
    while offset < len(valid):
        header = struct.unpack_from("<I", valid, offset)[0]
        offset += 4
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", valid, offset)[0]
            offset += 4
        end = offset + size
        records.append(valid[offset - (8 if ((header >> 20) & 0xFFF) == 0xFFF else 4):end])
        offset = end
    # Keep the exact properties and IDMappings prefix; mutate the reviewed
    # physical definition sequence only.
    if mutation == "missing":
        records.pop(2)
    elif mutation == "extra":
        records.insert(2, _record(source.TAG_FACE_NAME, b"\x00", level=1))
    else:
        records[9], records[10] = records[10], records[9]
    result = coverage.inspect_path(_hwp(tmp_path / f"{mutation}.hwp",
                                        docinfo=b"".join(records)))
    assert result["status"] == "refused"


def test_idmappings_duplicate_and_reordered_refuse(tmp_path: Path):
    valid = _docinfo()
    props = _record(source.TAG_DOCUMENT_PROPERTIES, _props())
    ids = _record(source.TAG_ID_MAPPINGS, _id_payload(
        [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0]))
    tail = valid[len(props) + len(ids):]
    duplicate = props + ids + ids + tail
    assert coverage.inspect_path(_hwp(tmp_path / "duplicate.hwp",
                                      docinfo=duplicate))["status"] == "refused"
    reordered = ids + props + tail
    assert coverage.inspect_path(_hwp(tmp_path / "reordered.hwp",
                                      docinfo=reordered))["status"] == "refused"


@pytest.mark.parametrize("kind", ["para_shape", "style", "char_shape", "position",
                                   "nonmonotonic"])
def test_body_reference_bounds_refuse(tmp_path: Path, kind: str):
    counts = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0]
    kwargs: dict[str, object] = {}
    if kind == "para_shape":
        kwargs["para_shape"] = 1
    elif kind == "style":
        kwargs["style"] = 1
    elif kind == "char_shape":
        kwargs["charshape"] = 1
    elif kind == "position":
        kwargs["positions"] = [(1, 0)]
    else:
        counts[9] = 2
        kwargs["positions"] = [(1, 0), (0, 1)]
        kwargs["char_count"] = 2
        kwargs["charshape_count"] = 2
    path = _hwp(tmp_path / f"{kind}.hwp", docinfo=_docinfo(counts=counts),
                body=_body(**kwargs))
    assert coverage.inspect_path(path)["status"] == "refused"


def test_char_shape_position_is_not_bounded_by_visible_text_count(tmp_path: Path):
    counts = [0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 0, 0, 1, 1, 0, 0, 0]
    path = _hwp(tmp_path / "control_units.hwp", docinfo=_docinfo(counts=counts),
                body=_body(char_count=1, charshape_count=2,
                           positions=[(0, 0), (9, 0)]))
    result = coverage.inspect_path(path)
    assert result["status"] == "analyzed"
    assert result["coverage"]["bodytext_char_shape_position_refs"] == 2


def test_idmappings_version_tail_and_unknown_docinfo_refuse(tmp_path: Path):
    short_version = _hwp(tmp_path / "short.hwp",
                         docinfo=_docinfo(version_tail=b"\x00\x00\x00\x00"))
    assert coverage.inspect_path(short_version)["status"] == "refused"
    unknown = _docinfo() + _record(0x1D, b"x", level=0)
    unknown_path = _hwp(tmp_path / "unknown.hwp", docinfo=unknown)
    assert coverage.inspect_path(unknown_path)["status"] == "refused"


@pytest.mark.parametrize("mapping_bytes", [60, 64])
def test_short_idmappings_prefix_is_refused(tmp_path: Path, mapping_bytes: int):
    props = _record(source.TAG_DOCUMENT_PROPERTIES, _props())
    full_ids = _record(source.TAG_ID_MAPPINGS, _id_payload(
        [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0]))
    valid = _docinfo()
    tail = valid[len(props) + len(full_ids):]
    docinfo = props + _record(source.TAG_ID_MAPPINGS,
                               b"\x00" * mapping_bytes) + tail
    result = coverage.inspect_path(_hwp(tmp_path / f"short-{mapping_bytes}.hwp",
                                        docinfo=docinfo))
    assert result["status"] == "refused"


@pytest.mark.parametrize("counts", [
    [-1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0],
    [0, 1_000_001, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0],
])
def test_negative_or_huge_definition_counts_refuse(tmp_path: Path,
                                                    counts: list[int]):
    path = _hwp(tmp_path / "bad-counts.hwp", docinfo=_docinfo(counts=counts))
    assert coverage.inspect_path(path)["status"] == "refused"


def test_extended_and_truncated_docinfo_record_envelope(tmp_path: Path):
    props = _record(source.TAG_DOCUMENT_PROPERTIES, _props(), extended=True)
    ids_payload = _id_payload(
        [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0])
    ids = _record(source.TAG_ID_MAPPINGS, ids_payload, extended=True)
    valid = _docinfo()
    tail = valid[len(_record(source.TAG_DOCUMENT_PROPERTIES, _props()))
                 + len(_record(source.TAG_ID_MAPPINGS, ids_payload)):]
    extended = _hwp(tmp_path / "extended.hwp", docinfo=props + ids + tail)
    assert coverage.inspect_path(extended)["status"] == "analyzed"

    truncated = props + ids[:-1] + tail
    bad = _hwp(tmp_path / "truncated.hwp", docinfo=truncated)
    assert coverage.inspect_path(bad)["status"] == "refused"


def test_memo_shape_physical_cardinality_is_exact(tmp_path: Path):
    memo = _record(getattr(source, "TAG_MEMO_SHAPE", 0x5C),
                   b"\x00" * 22, level=1)
    zero_extra = _hwp(tmp_path / "memo-extra.hwp", docinfo=_docinfo() + memo)
    assert coverage.inspect_path(zero_extra)["status"] == "refused"
    counts = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0]
    exact = _hwp(tmp_path / "memo-exact.hwp",
                 docinfo=_docinfo(counts=counts) + memo)
    assert coverage.inspect_path(exact)["status"] == "analyzed"
    duplicate = _hwp(tmp_path / "memo-duplicate.hwp",
                     docinfo=_docinfo(counts=counts) + memo + memo)
    assert coverage.inspect_path(duplicate)["status"] == "refused"


def test_receipt_duplicate_and_unknown_nested_fields_refuse(tmp_path: Path):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    raw = receipt.read_text(encoding="utf-8")
    duplicate = raw.replace('"status":"analyzed"',
                            '"status":"analyzed","status":"analyzed"', 1)
    receipt.write_text(duplicate, encoding="utf-8")
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    payload = coverage.inspect_path(path)
    payload["coverage"]["unknown"] = 1
    receipt.write_bytes(coverage._json_bytes(payload))
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_hardlink_receipt_is_refused(tmp_path: Path):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    duplicate = tmp_path / "receipt-hardlink.json"
    try:
        os.link(receipt, duplicate)
    except OSError:
        pytest.skip("hard links unavailable")
    try:
        assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                              "--run-id", run_id]) == 3
    finally:
        duplicate.unlink(missing_ok=True)


def test_before_commit_source_mutation_rolls_back_publication(tmp_path: Path,
                                                               monkeypatch):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    original = coverage._read_input_once
    calls = 0

    def rebound(target: Path) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            # Mutate the source before the callback's second snapshot.
            target.write_bytes(target.read_bytes() + b"x")
        return original(target)

    monkeypatch.setattr(coverage, "_read_input_once", rebound)
    with pytest.raises(coverage.CoverageError):
        coverage.inspect_and_publish(path, coverage_root=root, run_id=run_id)
    assert not (root / run_id).exists()


@pytest.mark.parametrize("when", ["before_delete", "after_delete"])
def test_publication_cleanup_exception_does_not_split_receipt(tmp_path: Path,
                                                               monkeypatch,
                                                               when: str):
    path = _hwp(tmp_path / f"{when}.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    original = coverage.tempfile.TemporaryDirectory
    held: list[object] = []

    class RaisingTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = original(*args, **kwargs)
            if when == "before_delete":
                held.append(self.inner)

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, *args):
            if when == "after_delete":
                self.inner.__exit__(*args)
            raise OSError("injected staging cleanup failure")

    monkeypatch.setattr(coverage.tempfile, "TemporaryDirectory",
                        RaisingTemporaryDirectory)
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    assert receipt.is_file()
    assert receipt.stat().st_nlink == 1
    assert coverage.verify_path(path, coverage_root=root, run_id=run_id)["status"] == "analyzed"
    for item in held:
        cleanup = getattr(item, "cleanup", None)
        if cleanup is not None:
            cleanup()


def test_verify_rebinds_source_after_initial_read(tmp_path: Path, monkeypatch):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    original = coverage._read_input_once
    calls = 0

    def rebound(target: Path) -> bytes:
        nonlocal calls
        calls += 1
        data = original(target)
        if calls == 1:
            target.write_bytes(target.read_bytes() + b"x")
        return data

    monkeypatch.setattr(coverage, "_read_input_once", rebound)
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_verify_rebinds_receipt_after_initial_read(tmp_path: Path, monkeypatch):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    original = coverage._read_receipt
    calls = 0

    def rebound(target: Path, *, allow_hardlink: bool = False):
        nonlocal calls
        calls += 1
        result = original(target, allow_hardlink=allow_hardlink)
        if calls == 1:
            forged = dict(result[0])
            forged["eligibility"] = "ineligible"
            target.write_bytes(coverage._json_bytes(forged))
        return result

    monkeypatch.setattr(coverage, "_read_receipt", rebound)
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_physical_cfb_trailing_bytes_refuse(tmp_path: Path):
    path = _hwp(tmp_path / "compressed.hwp", compressed=True)
    data = path.read_bytes()
    path.write_bytes(data + b"x")
    assert coverage.inspect_path(path)["status"] == "refused"


def test_strict_raw_deflate_eof_trailer_and_bounded_output(monkeypatch):
    raw_data = b"docinfo-wire"
    encoder = zlib.compressobj(wbits=-15)
    packed = encoder.compress(raw_data) + encoder.flush()
    with pytest.raises(source.CoverageError):
        source._inflate(packed[:-1])
    with pytest.raises(source.CoverageError):
        source._inflate(packed + b"x")
    bad_crc = packed + struct.pack("<II", zlib.crc32(raw_data) ^ 1,
                                   len(raw_data))
    with pytest.raises(source.CoverageError):
        source._inflate(bad_crc)
    bad_size = packed + struct.pack("<II", zlib.crc32(raw_data),
                                    len(raw_data) + 1)
    with pytest.raises(source.CoverageError):
        source._inflate(bad_size)
    old_limit = source.MAX_DECOMPRESSED_BYTES
    monkeypatch.setattr(source, "MAX_DECOMPRESSED_BYTES", 8)
    encoder = zlib.compressobj(wbits=-15)
    bomb = encoder.compress(b"x" * 64) + encoder.flush()
    with pytest.raises(source.CoverageError):
        source._inflate(bomb)
    monkeypatch.setattr(source, "MAX_DECOMPRESSED_BYTES", old_limit)


def test_receipt_publication_and_verify_source_mutation(tmp_path: Path):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    assert coverage.main(["inspect", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    receipt = root / run_id / "receipt.json"
    assert receipt.is_file()
    direct = coverage._read_receipt(receipt)[0]
    assert direct["status"] == "analyzed"
    assert coverage.verify_path(path, coverage_root=root, run_id=run_id) == direct
    with pytest.raises(coverage.CoverageError):
        coverage.inspect_and_publish(path, coverage_root=root, run_id=run_id)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["eligibility"] = "eligible"
    receipt.write_bytes(coverage._json_bytes(payload))
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3
    path.write_bytes(path.read_bytes() + b"x")
    assert coverage.main(["verify", str(path), "--coverage-root", str(root),
                          "--run-id", run_id]) == 3


def test_incomplete_body_envelope_refuses(tmp_path: Path):
    header = bytearray(24)
    struct.pack_into("<H", header, 8, 0)
    struct.pack_into("<H", header, 12, 0)
    path = _hwp(tmp_path / "incomplete.hwp",
                body=_record(source.TAG_PARA_HEADER, bytes(header)))
    result = coverage.inspect_path(path)
    assert result["status"] == "refused"


@pytest.mark.parametrize("header_size", [22, 23, 25, 26])
def test_only_detailed_24_byte_paraheader_enters_reference_coverage(
        tmp_path: Path, header_size: int):
    header = bytearray(header_size)
    struct.pack_into("<I", header, 0, 1)
    struct.pack_into("<H", header, 8, 0)
    header[10] = 0
    struct.pack_into("<H", header, 12, 1)
    body = (_record(source.TAG_PARA_HEADER, bytes(header), level=0)
            + _record(source.TAG_PARA_TEXT, b"a\x00", level=1)
            + _record(source.TAG_PARA_CHAR_SHAPE,
                      struct.pack("<II", 0, 0), level=1))
    result = coverage.inspect_path(_hwp(tmp_path / f"header-{header_size}.hwp",
                                        body=body))
    assert result["status"] == "refused"


def test_root_overlap_and_symlink_refuse_without_public_run(tmp_path: Path):
    path = _hwp(tmp_path / "valid.hwp")
    root = _root(tmp_path)
    assert coverage.main(["inspect", str(root), "--coverage-root", str(root),
                          "--run-id", "0123456789abcdef"]) == 3
    link = tmp_path / "linked.hwp"
    try:
        os.symlink(path, link)
    except OSError:
        pytest.skip("file symlinks unavailable")
    try:
        assert coverage.main(["inspect", str(link), "--coverage-root", str(root),
                              "--run-id", "0123456789abcdef"]) == 3
    finally:
        link.unlink(missing_ok=True)


def test_docinfo_case_alias_refuses_after_t85_preflight(tmp_path: Path):
    path = _hwp(tmp_path / "alias.hwp")
    data = bytearray(path.read_bytes())
    offset = 512 + 2 * 128
    data[offset:offset + 128] = b"\x00" * 128
    encoded = "docinfo".encode("utf-16le") + b"\x00\x00"
    data[offset:offset + len(encoded)] = encoded
    struct.pack_into("<H", data, offset + 64, len(encoded))
    path.write_bytes(bytes(data))
    result = coverage.inspect_path(path)
    assert result["status"] == "refused"


def test_root_and_run_symlink_swaps_refuse_without_clobber(tmp_path: Path):
    path = _hwp(tmp_path / "valid.hwp")
    real_root = _root(tmp_path)
    root_link = tmp_path / "hwp-docinfo-coverage-link"
    try:
        os.symlink(real_root, root_link, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    try:
        assert coverage.main(["inspect", str(path), "--coverage-root",
                              str(root_link), "--run-id", "0123456789abcdef"]) == 3
    finally:
        root_link.unlink(missing_ok=True)

    run_id = "fedcba9876543210"
    run_target = tmp_path / "run-target"
    run_target.mkdir()
    run_link = real_root / run_id
    try:
        os.symlink(run_target, run_link, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    try:
        assert coverage.main(["inspect", str(path), "--coverage-root",
                              str(real_root), "--run-id", run_id]) == 3
        assert run_link.is_symlink()
        assert not (run_target / "receipt.json").exists()
    finally:
        run_link.unlink(missing_ok=True)


def test_public_manifest_outcome_inventory_is_privacy_safe():
    manifest = Path(__file__).parents[2] / "tests" / "corpus" / "forms" / "manifest.json"
    if not manifest.is_file():
        pytest.skip("public HWP corpus is not present in this checkout")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    root = manifest.parent
    documents = [item for item in manifest_data.get("documents", [])
                 if item.get("format") == "hwp"]
    assert documents
    for item in documents:
        result = coverage.inspect_path(root / item["path"])
        assert (result["status"], result.get("reason")) == (
            "refused", "bodytext.envelope_incomplete")
