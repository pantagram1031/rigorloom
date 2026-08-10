"""TDD contract for the bounded HWP5 ingress surface.

All fixtures below are synthetic CFB v3 containers; no corpus bytes or source
document text are embedded in the test suite.
"""
from __future__ import annotations

import json
import contextlib
import os
import struct
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hwp_ingress as ingress  # noqa: E402


def _entry(name: str, typ: int, *, child: int = ingress.FREESECT,
           left: int = ingress.FREESECT, right: int = ingress.FREESECT,
           start: int = ingress.ENDOFCHAIN, size: int = 0) -> bytes:
    out = bytearray(128)
    encoded = name.encode("utf-16le") + b"\x00\x00"
    out[: len(encoded)] = encoded[:64]
    struct.pack_into("<H", out, 64, min(len(encoded), 64))
    out[66] = typ
    out[67] = 1
    struct.pack_into("<III", out, 68, left, right, child)
    struct.pack_into("<I", out, 116, start)
    struct.pack_into("<Q", out, 120, size)
    return bytes(out)


def _cfb_hwp(*, name: str = "FileHeader", fileheader: bytes | None = None,
             decoy: bytes | None = None, flags: int = 1,
             version: tuple[int, int, int, int] = (5, 1, 0, 0),
             mini: bool = True, malformed: str | None = None,
             nested: bool = False) -> bytes:
    """Build a tiny valid-ish CFB v3 with a root and FileHeader stream."""
    sector = 512
    fh = bytearray(256 if fileheader is None else fileheader)
    if fileheader is None:
        fh[:32] = b"HWP Document File" + b"\x00" * 15
        fh[32:36] = bytes((version[3], version[2], version[1], version[0]))
        struct.pack_into("<I", fh, 36, flags)
        struct.pack_into("<I", fh, 44, 4)
    if len(fh) != 256:
        raise ValueError("synthetic FileHeader must be 256 bytes")

    # Sectors: 0-1 directory, 2 FAT, 3 mini-FAT, 4 root mini stream, 5
    # regular decoy stream.  The root is required to expose DocInfo and
    # BodyText/Section0 direct children in addition to FileHeader.
    streams = [fh]
    names = [name]
    mini_entries = []
    mini_stream = bytearray()
    for stream in streams:
        start = len(mini_entries)
        count = (len(stream) + 63) // 64
        start = len(mini_entries)
        mini_entries.extend([start + i + 1 for i in range(count)])
        mini_entries[-1] = ingress.ENDOFCHAIN
        mini_stream.extend(stream)
        mini_stream.extend(b"\x00" * ((-len(stream)) % 64))

    # Root sibling tree: FileHeader -> DocInfo -> BodyText; BodyText owns
    # Section0.  Nested mode puts FileHeader under an unrelated storage so a
    # recursive search cannot promote it.
    root_child = 1
    entries = [_entry("Root Entry", 5, child=root_child,
                      start=4, size=max(64, len(mini_stream)))]
    if nested:
        entries.extend([
            _entry("Storage", 1, child=2, right=3),
            _entry("FileHeader", 2, start=0, size=256),
            _entry("DocInfo", 2, right=4),
            _entry("BodyText", 1, child=5),
            _entry("Section0", 2),
        ])
    elif decoy is None:
        entries.extend([
            _entry(names[0], 2, right=2, start=0, size=256),
            _entry("DocInfo", 2, right=3),
            _entry("BodyText", 1, child=4),
            _entry("Section0", 2),
        ])
    else:
        # The valid FileHeader is reachable; a differently named orphan holds
        # a second signature and catches raw byte-search parsers.
        entries.extend([
            _entry("FileHeader", 2, right=2, start=0, size=256),
            _entry("DocInfo", 2, right=3),
            _entry("BodyText", 1, child=4),
            _entry("Section0", 2),
        ])
    directory = b"".join(entries).ljust(sector * 2, b"\x00")

    # FAT: two directory sectors, FAT, mini-FAT, mini-stream, regular stream.
    fat = [ingress.ENDOFCHAIN] * (sector // 4)
    fat[0] = 1
    fat[1] = ingress.ENDOFCHAIN
    fat[2] = ingress.FATSECT
    fat[3] = ingress.ENDOFCHAIN
    fat[4] = ingress.ENDOFCHAIN
    # Physical sector 5 is bounded padding, not an allocated stream.
    fat[5] = ingress.FREESECT
    if malformed == "orphan_fat":
        fat[5] = ingress.ENDOFCHAIN
    fat_sector = struct.pack("<%dI" % (sector // 4), *fat)
    mini_fat = [ingress.FREESECT] * (sector // 4)
    for i, nxt in enumerate(mini_entries):
        mini_fat[i] = nxt
    if malformed == "mini_cycle":
        mini_fat[0] = 0
    if malformed == "free_end":
        mini_fat[0] = ingress.FREESECT
    if malformed == "orphan_mini":
        mini_fat[10] = ingress.ENDOFCHAIN
    mini_fat_sector = struct.pack("<%dI" % (sector // 4), *mini_fat)

    header = bytearray(sector)
    header[:8] = ingress.CFB_SIGNATURE
    struct.pack_into("<HHHH", header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIII", header, 40,
                     0, 1, 0, 0, 4096, 3, 1, ingress.ENDOFCHAIN)
    for i in range(109):
        struct.pack_into("<I", header, 76 + 4 * i, ingress.FREESECT)
    struct.pack_into("<I", header, 76, 2)

    if malformed == "fat":
        struct.pack_into("<I", fat_sector, 0, 0x12345678)
    if malformed == "mini":
        struct.pack_into("<I", mini_fat_sector, 0, 123456)
    if malformed == "dir_fat":
        struct.pack_into("<I", header, 48, 2)
    filler = bytes(decoy).ljust(sector, b"\x00") if decoy is not None else bytes(fh).ljust(sector, b"\x00")
    return (bytes(header) + directory + fat_sector + mini_fat_sector
            + bytes(mini_stream).ljust(sector, b"\x00") + filler)


def _hwpx(path: Path, *, bad_crc: bool = False, auxiliary: bool = False) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("mimetype", b"application/hwp+zip")
        extra_rootfiles = (
            '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
            '<ocf:rootfile full-path="META-INF/container.rdf" media-type="application/rdf+xml"/>'
            if auxiliary else ""
        )
        z.writestr("META-INF/container.xml",
                   '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
                   'media-type="application/hwpml-package+xml"/>' + extra_rootfiles +
                   '</ocf:rootfiles></ocf:container>')
        if auxiliary:
            z.writestr("Preview/PrvText.txt", b"")
            z.writestr("META-INF/container.rdf", b"")
        z.writestr("Contents/content.hpf",
                   '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
                   '<opf:manifest><opf:item id="section0" href="section0.xml" '
                   'media-type="application/xml"/></opf:manifest><opf:spine>'
                   '<opf:itemref idref="section0"/></opf:spine></opf:package>')
        z.writestr("Contents/section0.xml", "<sec><p><t>SYNTHETIC</t></p></sec>")
    if bad_crc:
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF
        path.write_bytes(data)
    return path


def _fingerprint(*, text_hash: str = "a" * 64, text_chars: int = 9,
                 shapes: int = 0, pages: int = 1, controls: int = 0,
                 fields: int = 0, tables: int = 0, pictures: int = 0,
                 equations: int = 0) -> dict:
    return {
        "text_sha256": text_hash,
        "text_chars_total": text_chars,
        "counts": {
            "tables": tables, "pictures": pictures, "equations": equations,
            "shapes": shapes, "pages": pages,
            "controls_total": controls, "field_count": fields,
        },
    }


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / "hwp_ingress.py"), *args],
                          capture_output=True, text=True, encoding="utf-8")


def test_synthetic_mini_fat_candidate_and_closed_source_schema(tmp_path: Path):
    path = tmp_path / "candidate.hwp"
    path.write_bytes(_cfb_hwp())
    result = ingress.inspect_path(path)
    assert result["status"] == "candidate"
    assert result["proof_grade"] == "none"
    assert result["output"]["state"] == "none"
    assert set(result["source"]) == {"format", "version", "bytes", "sha256", "compressed", "security_flags"}
    assert not any(k in json.dumps(result).lower() for k in ("path", "stdout", "stderr", "text"))


def test_decoy_not_byte_searched(tmp_path: Path):
    path = tmp_path / "decoy.hwp"
    path.write_bytes(_cfb_hwp(decoy=b"FileHeader" + b"x" * 246))
    assert ingress.inspect_path(path)["status"] == "candidate"


def test_nested_fileheader_is_not_promoted_to_root(tmp_path: Path):
    path = tmp_path / "nested.hwp"
    path.write_bytes(_cfb_hwp(nested=True))
    result = ingress.inspect_path(path)
    assert result["status"] == "refused"
    assert result["reason"] == "fileheader_missing"


@pytest.mark.parametrize("malformed,reason", [
    ("dir_fat", "cfb_sector_overlap"),
    ("mini_cycle", "cfb_chain_invalid"),
    ("free_end", "cfb_chain_unterminated"),
    ("orphan_fat", "cfb_orphan_allocation"),
    ("orphan_mini", "minifat_orphan_allocation"),
])
def test_cfb_allocation_aliases_and_cycles_refuse(tmp_path: Path, malformed: str, reason: str):
    path = tmp_path / f"{malformed}.hwp"
    path.write_bytes(_cfb_hwp(malformed=malformed))
    result = ingress.inspect_path(path)
    assert result["status"] == "refused"
    assert result["reason"] == reason


@pytest.mark.parametrize("extra_id,next_sid", [
    (None, 5),
    (5, ingress.ENDOFCHAIN),
])
def test_difat_count_and_terminal_are_exact(extra_id: int | None, next_sid: int):
    cfb = object.__new__(ingress._Cfb)
    cfb.data = bytearray(512)
    cfb.sector_size = 512
    cfb.sector_count = 8
    cfb.num_fat_sectors = 1
    cfb.first_difat_sector = 4
    cfb.num_difat_sectors = 1
    for index in range(109):
        struct.pack_into("<I", cfb.data, 76 + index * 4, ingress.FREESECT)
    struct.pack_into("<I", cfb.data, 76, 2)
    sector = bytearray(512)
    for index in range(127):
        struct.pack_into("<I", sector, index * 4, ingress.FREESECT)
    if extra_id is not None:
        struct.pack_into("<I", sector, 0, extra_id)
    struct.pack_into("<I", sector, 508, next_sid)
    cfb._sector = lambda sid: bytes(sector)
    with pytest.raises(ingress.IngressError) as caught:
        cfb._read_difat()
    assert caught.value.reason in {"difat_chain_invalid", "fat_header_count_invalid"}


def test_directory_names_are_nul_terminated_and_docinfo_is_a_stream(tmp_path: Path):
    bad_name = bytearray(_cfb_hwp())
    fileheader_entry = 512 + 128
    name_len = struct.unpack_from("<H", bad_name, fileheader_entry + 64)[0]
    bad_name[fileheader_entry + name_len - 2:fileheader_entry + name_len] = b"XX"
    name_path = tmp_path / "bad-name.hwp"
    name_path.write_bytes(bad_name)
    assert ingress.inspect_path(name_path)["reason"] == "directory_name_invalid"

    bad_docinfo = bytearray(_cfb_hwp())
    bad_docinfo[512 + 2 * 128 + 66] = 1
    docinfo_path = tmp_path / "docinfo-storage.hwp"
    docinfo_path.write_bytes(bad_docinfo)
    assert ingress.inspect_path(docinfo_path)["reason"] == "docinfo_missing"


@pytest.mark.parametrize("flags", [2, 4, 8, 16, 32, 0x80000000])
def test_security_property_bits_refused(tmp_path: Path, flags: int):
    path = tmp_path / "protected.hwp"
    path.write_bytes(_cfb_hwp(flags=flags))
    result = ingress.inspect_path(path)
    assert result["status"] == "refused"
    assert result["reason"] == "protected_properties"


def test_bad_extension_and_truncation_refused(tmp_path: Path):
    bad = tmp_path / "x.bin"
    bad.write_bytes(_cfb_hwp())
    assert ingress.inspect_path(bad)["reason"] == "extension_not_hwp"
    truncated = tmp_path / "x.hwp"
    truncated.write_bytes(_cfb_hwp()[:100])
    assert ingress.inspect_path(truncated)["reason"] in {"input_too_small", "not_cfb"}


def test_cli_exit_codes_and_cp949_safe_help(tmp_path: Path):
    p = tmp_path / "candidate.hwp"
    p.write_bytes(_cfb_hwp())
    assert _run("inspect", str(p)).returncode == 0
    assert _run("inspect", str(tmp_path / "missing.hwp")).returncode == 3
    assert _run("--help").returncode == 0


def test_unsupported_adapter_refuses_before_publication(tmp_path: Path):
    p = tmp_path / "candidate.hwp"
    p.write_bytes(_cfb_hwp())
    out = tmp_path / "out.hwpx"
    manifest = tmp_path / "manifest.json"
    result = ingress.convert_path(p, adapter="rhwp", out=out, manifest=manifest)
    assert result["status"] == "refused"
    assert result["reason"] == "adapter_unsupported"
    assert result["execution"]["adapter"] is None
    assert not out.exists()


def test_invalid_hwpx_is_not_accepted(tmp_path: Path):
    invalid = tmp_path / "invalid.hwpx"
    invalid.write_bytes(b"not zip")
    with pytest.raises(ingress.IngressError):
        ingress._validate_hwpx(invalid)


def test_hwpx_accepts_only_proven_auxiliary_rootfiles(tmp_path: Path):
    accepted = _hwpx(tmp_path / "aux.hwpx", auxiliary=True)
    assert ingress._validate_hwpx(accepted)["format"] == "hwpx"
    conflict = tmp_path / "conflict.hwpx"
    with zipfile.ZipFile(conflict, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("mimetype", b"application/hwp+zip")
        z.writestr("META-INF/container.xml",
                   '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
                   'media-type="application/hwpml-package+xml"/>'
                   '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/html"/>'
                   '</ocf:rootfiles></ocf:container>')
        z.writestr("Contents/content.hpf", b"")
        z.writestr("Preview/PrvText.txt", b"")
    with pytest.raises(ingress.IngressError) as caught:
        ingress._validate_hwpx(conflict)
    assert caught.value.reason == "hwpx_rootfile_conflict"


@pytest.mark.parametrize("member, expected", [
    ("foreign_container", "hwpx_container_invalid"),
    ("foreign_opf", "hwpx_opf_invalid"),
    ("duplicate_id", "hwpx_opf_duplicate_id"),
])
def test_hwpx_expanded_qname_and_duplicate_id_grammar(tmp_path: Path, member: str, expected: str):
    path = _hwpx(tmp_path / f"{member}.hwpx")
    data = bytearray(path.read_bytes())
    # Rebuild the tiny archive to avoid mutating compressed offsets.  Every
    # probe keeps the fixed first mimetype member and changes only XML shape.
    with zipfile.ZipFile(path) as original:
        members = {name: original.read(name) for name in original.namelist()}
    if member == "foreign_container":
        members["META-INF/container.xml"] = (
            b'<evil:container xmlns:evil="urn:evil"><evil:rootfiles>'
            b'<evil:rootfile full-path="Contents/content.hpf" '
            b'media-type="application/hwpml-package+xml"/></evil:rootfiles></evil:container>')
    elif member == "foreign_opf":
        members["Contents/content.hpf"] = (
            b'<evil:package xmlns:evil="urn:evil"><evil:manifest/><evil:spine/>'
            b'</evil:package>')
    else:
        members["Contents/content.hpf"] = (
            b'<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
            b'<opf:manifest><opf:item id="section0" href="section0.xml" media-type="application/xml"/>'
            b'<opf:item id="SECTION0" href="other.xml" media-type="application/xml"/></opf:manifest>'
            b'<opf:spine><opf:itemref idref="section0"/></opf:spine></opf:package>')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as rebuilt:
        for name in ("mimetype", "META-INF/container.xml", "Contents/content.hpf", "Contents/section0.xml"):
            rebuilt.writestr(name, members[name])

    with pytest.raises(ingress.IngressError) as caught:
        ingress._validate_hwpx(path)
    assert caught.value.reason == expected


def test_hwpx_unspined_section_is_refused(tmp_path: Path):
    path = _hwpx(tmp_path / "extra-section.hwpx")
    with zipfile.ZipFile(path) as original:
        members = {name: original.read(name) for name in original.namelist()}
    members["Contents/section1.xml"] = b"<sec><p><t>EXTRA</t></p></sec>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as rebuilt:
        for name, value in members.items():
            rebuilt.writestr(name, value)
    with pytest.raises(ingress.IngressError) as caught:
        ingress._validate_hwpx(path)
    assert caught.value.reason == "hwpx_sections_coverage"


def test_hwpx_rejects_orphan_local_record_and_post_eocd_trailer(tmp_path: Path):
    orphan = _hwpx(tmp_path / "orphan.hwpx")
    data = bytearray(orphan.read_bytes())
    eocd = data.rfind(b"PK\x05\x06")
    central_offset = struct.unpack_from("<I", data, eocd + 16)[0]
    payload = b"X"
    name = b"orphan.bin"
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    local = (struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                         crc, 1, 1, len(name), 0) + name + payload)
    data[central_offset:central_offset] = local
    eocd += len(local)
    struct.pack_into("<I", data, eocd + 16, central_offset + len(local))
    orphan.write_bytes(data)
    with pytest.raises(ingress.IngressError) as caught:
        ingress._validate_hwpx(orphan)
    assert caught.value.reason == "hwpx_physical_invalid"

    trailer = _hwpx(tmp_path / "trailer.hwpx")
    trailer.write_bytes(trailer.read_bytes() + b"TRAILER")
    with pytest.raises(ingress.IngressError) as caught:
        ingress._validate_hwpx(trailer)
    assert caught.value.reason == "hwpx_physical_invalid"


def test_hancom_same_fingerprint_success_is_closed_and_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    calls: list[list[str]] = []
    prechecks: list[str] = []
    fingerprint = _fingerprint()

    def fake_inspect(argv, *, timeout):
        prechecks.append('tasklist | findstr /i hwp')
        calls.append(list(argv))
        return fingerprint

    def fake_run(argv, *, timeout):
        # The staged output is the argument following --to.
        target = Path(argv[argv.index("--to") + 1])
        _hwpx(target)
        return 0, False, False

    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_inspect", fake_inspect)
    monkeypatch.setattr(ingress, "_com_precheck", lambda: prechecks.append('tasklist | findstr /i hwp'))
    monkeypatch.setattr(ingress, "_wait_com_clear", lambda timeout: None)
    monkeypatch.setattr(ingress, "_run_child", fake_run)
    result = ingress.convert_path(source, adapter="hancom",
                                  out=tmp_path / "out.hwpx",
                                  manifest=tmp_path / "manifest.json")
    assert result["status"] == "converted"
    assert result["proof_grade"] == "none"
    assert result["output"]["state"] == "published"
    assert result["comparison"] == {
        "state": "passed", "method": "same_com_extractor",
        "text_hash_match": True, "text_chars_match": True,
        "aggregate_counts_match": True,
        "control_counts_match": True,
    }
    assert len(calls) == 2
    assert prechecks == ['tasklist | findstr /i hwp'] * 3
    assert all("--privacy-safe" in call and "--preview-chars" in call for call in calls)
    assert (tmp_path / "out.hwpx").is_file()
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["source"]["format"] == "hwp"
    assert "text_sha256" not in json.dumps(payload)
    assert ingress.verify_receipt(tmp_path / "out.hwpx", tmp_path / "manifest.json") == payload
    assert _run("verify", str(tmp_path / "out.hwpx"), "--manifest",
                str(tmp_path / "manifest.json")).returncode == 0


def test_receipt_verifier_rejects_unknown_duplicate_and_hash_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    fingerprint = _fingerprint()
    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_inspect", lambda argv, *, timeout: fingerprint)
    monkeypatch.setattr(ingress, "_com_precheck", lambda: None)
    monkeypatch.setattr(ingress, "_wait_com_clear", lambda timeout: None)
    monkeypatch.setattr(
        ingress, "_run_child",
        lambda argv, *, timeout: (_hwpx(Path(argv[argv.index("--to") + 1])) and (0, False, False)),
    )
    output = tmp_path / "out.hwpx"
    receipt = tmp_path / "receipt.json"
    assert ingress.convert_path(source, adapter="hancom", out=output,
                                manifest=receipt)["status"] == "converted"
    original = receipt.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["extra"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ingress.IngressError) as caught:
        ingress.verify_receipt(output, receipt)
    assert caught.value.reason == "receipt_schema_invalid"

    receipt.write_text(original.replace(
        '"status":"converted"', '"status":"converted","status":"refused"'),
        encoding="utf-8")
    with pytest.raises(ingress.IngressError) as caught:
        ingress.verify_receipt(output, receipt)
    assert caught.value.reason == "receipt_duplicate_key"

    payload = json.loads(original)
    payload["output"]["sha256"] = "0" * 64
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ingress.IngressError) as caught:
        ingress.verify_receipt(output, receipt)
    assert caught.value.reason == "receipt_output_mismatch"


def test_hancom_fingerprint_mismatch_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    values = iter((
        _fingerprint(),
        _fingerprint(text_hash="b" * 64),
    ))
    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_inspect", lambda argv, *, timeout: next(values))
    monkeypatch.setattr(ingress, "_com_precheck", lambda: None)
    monkeypatch.setattr(ingress, "_wait_com_clear", lambda timeout: None)
    def fake_run(argv, *, timeout):
        _hwpx(Path(argv[argv.index("--to") + 1]))
        return 0, False, False
    monkeypatch.setattr(ingress, "_run_child", fake_run)
    result = ingress.convert_path(source, adapter="hancom", out=tmp_path / "out.hwpx",
                                 manifest=tmp_path / "manifest.json")
    assert result["status"] == "refused"
    assert result["reason"] == "semantic_text_mismatch"
    assert not (tmp_path / "out.hwpx").exists()


def test_hancom_shape_or_page_loss_is_hard_even_when_xml_controls_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    values = iter((_fingerprint(shapes=1, pages=2, controls=1),
                   _fingerprint(shapes=0, pages=2, controls=0)))
    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_inspect", lambda argv, *, timeout: next(values))
    monkeypatch.setattr(ingress, "_com_precheck", lambda: None)
    monkeypatch.setattr(ingress, "_wait_com_clear", lambda timeout: None)
    def fake_run(argv, *, timeout):
        _hwpx(Path(argv[argv.index("--to") + 1]))
        return 0, False, False
    monkeypatch.setattr(ingress, "_run_child", fake_run)
    result = ingress.convert_path(source, adapter="hancom", out=tmp_path / "out.hwpx",
                                 manifest=tmp_path / "manifest.json")
    assert result["status"] == "refused"
    assert result["reason"] == "aggregate_counts_mismatch"
    assert not (tmp_path / "out.hwpx").exists()
    assert result["comparison"]["aggregate_counts_match"] is False


def test_hancom_mutex_busy_refuses_without_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())

    @contextlib.contextmanager
    def busy_guard():
        raise ingress.IngressError("hancom_mutex_busy")
        yield

    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_serial_guard", busy_guard)
    monkeypatch.setattr(ingress, "_com_inspect", lambda *args, **kwargs: pytest.fail("child spawned"))
    result = ingress.convert_path(source, adapter="hancom", out=tmp_path / "out.hwpx",
                                  manifest=tmp_path / "manifest.json")
    assert result["status"] == "refused"
    assert result["reason"] == "hancom_mutex_busy"
    assert not (tmp_path / "out.hwpx").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_same_process_threads_are_serialized_by_local_guard():
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first():
        with ingress._com_serial_guard():
            first_entered.set()
            release_first.wait(2)

    def second():
        first_entered.wait(2)
        with ingress._com_serial_guard():
            second_entered.set()

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    assert first_entered.wait(1)
    time.sleep(0.05)
    assert not second_entered.is_set()
    release_first.set()
    one.join(2)
    two.join(2)
    assert second_entered.is_set()


def test_com_child_natural_shutdown_is_polled_without_killing(monkeypatch: pytest.MonkeyPatch):
    states = iter((0, 0, 1))
    sleeps: list[float] = []
    monkeypatch.setattr(ingress, "_hwp_tasklist_code", lambda: next(states))
    monkeypatch.setattr(ingress.time, "sleep", lambda value: sleeps.append(value))
    ingress._wait_com_clear(1.0)
    assert sleeps == [0.1, 0.1]


def test_conversion_failure_manifest_keeps_safe_source_and_execution_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    fingerprint = _fingerprint()
    monkeypatch.setattr(ingress, "_com_available", lambda: True)
    monkeypatch.setattr(ingress, "_com_inspect", lambda argv, *, timeout: fingerprint)
    monkeypatch.setattr(ingress, "_com_precheck", lambda: None)
    monkeypatch.setattr(ingress, "_wait_com_clear", lambda timeout: None)
    monkeypatch.setattr(ingress, "_run_child", lambda argv, *, timeout: (7, True, False))
    result = ingress.convert_path(source, adapter="hancom", out=tmp_path / "out.hwpx",
                                 manifest=tmp_path / "manifest.json")
    assert result["status"] == "refused"
    assert result["reason"] == "timeout"
    assert result["source"]["format"] == "hwp"
    assert result["execution"] == {"state": "failed", "adapter": "hancom"}
    assert result["comparison"] == {"state": "unknown"}
    assert not (tmp_path / "out.hwpx").exists()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["source"]["format"] == "hwp"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 301])
def test_invalid_timeout_refuses_without_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: float):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    calls = []
    monkeypatch.setattr(ingress, "_com_available", lambda: calls.append(True))
    result = ingress.convert_path(source, adapter="hancom", out=tmp_path / "out.hwpx",
                                 manifest=tmp_path / "manifest.json", timeout=timeout)
    assert result["reason"] == "timeout_invalid"
    assert calls == []


def test_existing_output_refuses_before_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "candidate.hwp"
    source.write_bytes(_cfb_hwp())
    output = tmp_path / "out.hwpx"
    output.write_bytes(b"KEEP")
    called = []
    monkeypatch.setattr(ingress, "_com_available", lambda: called.append(True))
    result = ingress.convert_path(source, adapter="hancom", out=output,
                                 manifest=tmp_path / "manifest.json")
    assert result["reason"] == "output_exists"
    assert output.read_bytes() == b"KEEP"
    assert called == []


def test_publish_rollback_does_not_delete_swapped_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    staged = _hwpx(tmp_path / "staged.hwpx")
    output = tmp_path / "published.hwpx"
    manifest = tmp_path / "manifest.json"
    payload = {"output": {"sha256": ingress.sha256_file(staged)}}

    def fail_after_swap(staged_path, output_path):
        manifest.unlink()
        manifest.write_bytes(b"SWAPPED-BY-OTHER-WRITER")
        raise FileExistsError(output_path)

    monkeypatch.setattr(ingress.os, "link", fail_after_swap)
    with pytest.raises(ingress.IngressError):
        ingress._publish_pair(staged, output, manifest, payload)
    assert manifest.read_bytes() == b"SWAPPED-BY-OTHER-WRITER"
    assert not output.exists()
