"""Synthetic contract for the quarantined Java HWP diagnostic lane."""
from __future__ import annotations

import hashlib
import binascii
import json
import os
from pathlib import Path
import struct
import sys
import zipfile
import zlib

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from test_hwp_ingress import _cfb_hwp, _hwpx  # noqa: E402
import hwp_java_diagnostic_candidate as diagnostic  # noqa: E402


RUN_ID = "fedcba9876543210fedcba9876543210"


def _java_descriptor_zip(path: Path, rows: list[tuple[str, bytes]]) -> Path:
    body = bytearray()
    central_rows: list[bytes] = []
    for name, data in rows:
        raw_name = name.encode("utf-8")
        crc = binascii.crc32(data) & 0xFFFFFFFF
        compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
        compressed = compressor.compress(data) + compressor.flush()
        offset = len(body)
        body.extend(struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0x0808, 8, 0, 0,
            0, 0, 0, len(raw_name), 0))
        body.extend(raw_name)
        body.extend(compressed)
        body.extend(struct.pack(
            "<IIII", 0x08074B50, crc, len(compressed), len(data)))
        central_rows.append(struct.pack(
            "<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0808, 8,
            0, 0, crc, len(compressed), len(data), len(raw_name), 0, 0,
            0, 0, 0, offset) + raw_name)
    central_offset = len(body)
    for row in central_rows:
        body.extend(row)
    central_size = len(body) - central_offset
    body.extend(struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, len(rows), len(rows),
        central_size, central_offset, 0))
    path.write_bytes(body)
    return path


def _canonical_hwpx_text(path: Path, text: str) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
            'media-type="application/hwpml-package+xml"/>'
            '</ocf:rootfiles></ocf:container>')
        archive.writestr(
            "Contents/content.hpf",
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
            '<opf:manifest><opf:item id="section0" href="section0.xml" '
            'media-type="application/xml"/></opf:manifest><opf:spine>'
            '<opf:itemref idref="section0"/></opf:spine></opf:package>')
        archive.writestr(
            "Contents/section0.xml", f"<sec><p><t>{text}</t></p></sec>")
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "hwp-java-diagnostic"
    root.mkdir()
    return root


def _toolchain(monkeypatch: pytest.MonkeyPatch, *, tool: bytes = b"approved-fat-jar",
               bridge: bytes = b"public final class Hwp2HwpxBridge {}") -> dict:
    lock = {
        "schema": "rigorloom/hwp-java-toolchain-lock/v1",
        "adapter": "hwp2hwpx_java",
        "main_class": "Hwp2HwpxBridge",
        "runtime_binding": "launcher_rehashed_runtime_unbound",
        "bridge": {
            "path": "Hwp2HwpxBridge.java", "bytes": len(bridge),
            "sha256": hashlib.sha256(bridge).hexdigest(),
        },
        "tool": {
            "filename": "hwp2hwpx.jar", "bytes": len(tool),
            "sha256": hashlib.sha256(tool).hexdigest(),
            "coordinate": "synthetic:test:1",
        },
        "provenance": {
            "hwp2hwpx_upstream_commit": "1" * 40,
            "source_jar_sha256": "2" * 64,
            "source_mapping": "synthetic",
            "embedded_hwplib": {
                "coordinate": "synthetic:hwplib:1", "jar_sha256": "3" * 64,
                "upstream_commit": "4" * 40,
            },
            "embedded_hwpxlib": {
                "coordinate": "synthetic:hwpxlib:1", "jar_sha256": "5" * 64,
                "upstream_commit": "6" * 40,
            },
        },
    }
    monkeypatch.setattr(
        diagnostic, "_load_toolchain",
        lambda: (lock, "7" * 64, bridge),
    )
    return lock


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    java = tmp_path / ("java.exe" if os.name == "nt" else "java")
    java.write_bytes(b"synthetic-java-launcher")
    tool = tmp_path / "hwp2hwpx.jar"
    tool.write_bytes(b"approved-fat-jar")
    lock = _toolchain(monkeypatch, tool=tool.read_bytes())
    return source, java, tool, lock


def _success_child(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[list[str], dict[str, str], bytes, bytes]] = []

    def fake(argv, *, timeout, cwd=None, env=None):
        assert cwd is not None
        assert env is not None
        classpath_index = argv.index("-cp") + 1
        calls.append((list(argv), dict(env),
                      Path(argv[classpath_index]).read_bytes(),
                      Path(argv[classpath_index + 1]).read_bytes()))
        _hwpx(Path(argv[-1]))
        return 0, False, False

    monkeypatch.setattr(diagnostic, "_run_child_capture", fake)
    return calls


def test_success_is_separate_quarantined_unknown_and_exact_argv(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source, java, tool, lock = _inputs(tmp_path, monkeypatch)
    calls = _success_child(monkeypatch)
    root = _root(tmp_path)
    java_hash = hashlib.sha256(java.read_bytes()).hexdigest()

    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=java_hash, tool_jar=tool,
    )

    assert result["schema"] == "rigorloom/hwp-java-diagnostic-candidate/v1"
    assert result["status"] == "candidate"
    assert result["adapter"] == "hwp2hwpx_java"
    assert result["comparison"] == {
        "state": "unknown", "method": "none",
        "reason": "independent_source_oracle_not_run",
    }
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert result["execution"] == {
        "state": "succeeded", "exit_code": 0,
        "java_launcher_sha256": java_hash,
        "runtime_binding": "launcher_rehashed_runtime_unbound",
        "toolchain_lock_sha256": "7" * 64,
        "bridge_sha256": lock["bridge"]["sha256"],
        "main_class": "Hwp2HwpxBridge",
        "package_normalization": "zip_envelope_canonicalized",
        "missing_aux_rootfiles_pruned": 0,
        "classpath": [{"role": "hwp2hwpx_fat_jar",
                       "sha256": lock["tool"]["sha256"]}],
    }
    assert result["output"]["path"] == f"{RUN_ID}/candidate.hwpx"
    assert (root / RUN_ID / "candidate.hwpx").is_file()
    assert (root / RUN_ID / "receipt.json").is_file()
    assert calls
    argv, child_env, classpath_bytes, bridge_bytes = calls[0]
    assert argv[0] == str(java.resolve())
    assert argv[1:6] == [
        "-XX:-UsePerfData", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
        "-Duser.language=en", "-Duser.country=US",
    ]
    assert "-Duser.timezone=UTC" in argv
    assert "-Djava.io.tmpdir=" + str(Path(argv[-2]).parent) in argv
    assert argv[-3] == "convert"
    assert Path(argv[-2]).name == "input.hwp"
    assert Path(argv[-1]).name == "tool-output.hwpx"
    assert "-cp" in argv
    classpath = Path(argv[argv.index("-cp") + 1])
    assert classpath.name == "hwp2hwpx.jar"
    assert classpath_bytes == tool.read_bytes()
    bridge = Path(argv[argv.index("-cp") + 2])
    assert bridge.name == "Hwp2HwpxBridge.java"
    assert bridge_bytes == b"public final class Hwp2HwpxBridge {}"
    for key in ("CLASSPATH", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        assert key not in child_env
    encoded = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert "stdout" not in encoded and "stderr" not in encoded


@pytest.mark.parametrize(
    "pin,expected",
    [(None, "java_unpinned"), ("bad", "java_pin_invalid"), ("0" * 64, "java_hash_mismatch")],
)
def test_java_pin_is_closed_before_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         pin: str | None, expected: str):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    called: list[bool] = []
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: called.append(True))
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID, java=java,
        java_sha256=pin, tool_jar=tool,
    )
    assert result["status"] == "refused"
    assert result["reason"] == expected
    assert called == []


def test_unapproved_tool_jar_refuses_before_child(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    tool.write_bytes(b"different-tool")
    called: list[bool] = []
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: called.append(True))
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "refused"
    assert result["reason"] == "tool_hash_mismatch"
    assert called == []


@pytest.mark.parametrize(
    "child_result,reason",
    [((9, False, False), "java_failed"),
     ((-1, True, False), "java_timeout"),
     ((-1, False, True), "java_output_too_large"),
     ((False, [], {}), "java_failed")],
)
def test_child_failure_is_closed_and_leaves_no_publication(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, child_result, reason: str):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: child_result)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "refused"
    assert result["reason"] == reason
    assert not (root / RUN_ID).exists()


def test_protected_source_refuses_before_java(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    source.write_bytes(_cfb_hwp(flags=0x00000005))
    called: list[bool] = []
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: called.append(True))
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "refused"
    assert called == []
    assert result["reason"] in {"password_protected", "protected_hwp"}


def test_verify_rebinds_closed_receipt_and_current_candidate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    _success_child(monkeypatch)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "candidate"
    assert diagnostic.verify_diagnostic(root, RUN_ID)["status"] == "candidate"
    candidate = root / RUN_ID / "candidate.hwpx"
    candidate.chmod(0o600)
    candidate.write_bytes(b"drift")
    assert diagnostic.verify_diagnostic(root, RUN_ID) == {
        **diagnostic._base(status="refused", reason="receipt_output_mismatch"),
    }


def test_cli_help_and_closed_exit_contract():
    parser = diagnostic.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([])
    assert exc.value.code == 2


def test_shipped_toolchain_lock_rebinds_bridge_and_approved_fat_jar():
    lock, lock_sha256, bridge = diagnostic._load_toolchain()
    assert lock["schema"] == "rigorloom/hwp-java-toolchain-lock/v1"
    assert lock["adapter"] == "hwp2hwpx_java"
    assert lock["main_class"] == "Hwp2HwpxBridge"
    assert lock["runtime_binding"] == "launcher_rehashed_runtime_unbound"
    assert hashlib.sha256(bridge).hexdigest() == lock["bridge"]["sha256"]
    assert lock["tool"]["sha256"] == (
        "06ba7071b9ee2f2256fa62398b5d32dc07496cb47cf764b4cf0b7c6119bd11cd")
    assert lock_sha256 == diagnostic.EXPECTED_LOCK_SHA256


def test_verify_rejects_resealed_foreign_toolchain_receipt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    _success_child(monkeypatch)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "candidate"
    receipt = root / RUN_ID / "receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["execution"]["classpath"][0]["sha256"] = "9" * 64
    receipt.chmod(0o600)
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    refused = diagnostic.verify_diagnostic(root, RUN_ID)
    assert refused["status"] == "refused"
    assert refused["reason"] == "receipt_toolchain_mismatch"


def test_java_writer_envelope_is_canonicalized_and_missing_aux_is_pruned(
        tmp_path: Path):
    raw = tmp_path / "raw.hwpx"
    container = (
        '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/>'
        '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
        '</ocf:rootfiles></ocf:container>'
    )
    _java_descriptor_zip(raw, [
        ("mimetype", b"application/hwp+zip"),
        ("META-INF/container.xml", container.encode("utf-8")),
        ("Contents/content.hpf",
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
            '<opf:manifest><opf:item id="section0" href="section0.xml" '
            'media-type="application/xml"/></opf:manifest><opf:spine>'
            '<opf:itemref idref="section0"/></opf:spine></opf:package>'.encode("utf-8")),
        ("Contents/section0.xml", b"<sec><p><t>X</t></p></sec>"),
    ])
    normalized = tmp_path / "normalized.hwpx"
    result, pruned = diagnostic._normalize_tool_hwpx(raw, normalized)
    assert pruned == 1
    assert result["bytes"] == normalized.stat().st_size
    with zipfile.ZipFile(normalized) as archive:
        first = min(archive.infolist(), key=lambda row: row.header_offset)
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert b"Preview/PrvText.txt" not in archive.read("META-INF/container.xml")


@pytest.mark.parametrize(
    "mutation",
    ["trailer", "comment", "prefix", "flags", "dot_member", "orphan_local"],
)
def test_normalizer_refuses_raw_zip_anomalies_instead_of_salvaging(
        tmp_path: Path, mutation: str):
    raw = _hwpx(tmp_path / "raw.hwpx")
    if mutation == "trailer":
        raw.write_bytes(raw.read_bytes() + b"TRAILING-CANARY")
    elif mutation == "comment":
        with zipfile.ZipFile(raw, "a") as archive:
            archive.comment = b"COMMENT-CANARY"
    elif mutation == "prefix":
        raw.write_bytes(b"PREFIX-CANARY" + raw.read_bytes())
    elif mutation == "dot_member":
        with zipfile.ZipFile(raw, "a") as archive:
            archive.writestr("./private.txt", b"PRIVATE-CANARY")
    elif mutation == "orphan_local":
        data = bytearray(raw.read_bytes())
        eocd = data.rfind(b"PK\x05\x06")
        assert eocd >= 0
        central_offset = struct.unpack_from("<I", data, eocd + 16)[0]
        name = b"orphan.bin"
        orphan = struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
            0, 0, 0, len(name), 0,
        ) + name
        data[central_offset:central_offset] = orphan
        struct.pack_into(
            "<I", data, eocd + len(orphan) + 16,
            central_offset + len(orphan),
        )
        raw.write_bytes(data)
    else:
        data = bytearray(raw.read_bytes())
        local = data.find(b"PK\x03\x04")
        central = data.find(b"PK\x01\x02")
        assert local >= 0 and central >= 0
        data[local + 6:local + 8] = (0x800).to_bytes(2, "little")
        data[central + 8:central + 10] = (0x800).to_bytes(2, "little")
        raw.write_bytes(data)
    output = tmp_path / "normalized.hwpx"
    with pytest.raises(diagnostic.JavaDiagnosticError) as caught:
        diagnostic._normalize_tool_hwpx(raw, output)
    assert caught.value.reason == "hwpx_invalid"
    assert not output.exists()


def test_normalizer_uses_the_captured_snapshot_not_the_live_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured = _canonical_hwpx_text(tmp_path / "captured.hwpx", "CAPTURED")
    live = _canonical_hwpx_text(tmp_path / "live.hwpx", "LIVE-NOT-SNAPSHOT")
    captured_bytes = captured.read_bytes()
    original = diagnostic._core.read_regular_once

    def swapped(path: Path, max_bytes: int, reason: str):
        if Path(path) == live:
            return captured_bytes
        return original(Path(path), max_bytes, reason)

    monkeypatch.setattr(diagnostic._core, "read_regular_once", swapped)
    output = tmp_path / "normalized.hwpx"
    diagnostic._normalize_tool_hwpx(live, output)
    with zipfile.ZipFile(output) as archive:
        section = archive.read("Contents/section0.xml")
    assert b"CAPTURED" in section
    assert b"LIVE-NOT-SNAPSHOT" not in section


@pytest.mark.parametrize(
    "mutated,reason",
    [("java", "java_drift"), ("tool", "tool_drift"),
     ("source", "source_changed"), ("bridge", "toolchain_bridge_drift")],
)
def test_live_and_staged_snapshots_are_rehashed_after_child(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        mutated: str, reason: str):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)

    def fake(argv, *, timeout, cwd=None, env=None):
        target = {
            "java": java,
            "tool": tool,
            "source": source,
            "bridge": Path(argv[argv.index("-cp") + 2]),
        }[mutated]
        target.chmod(0o600)
        target.write_bytes(target.read_bytes() + b"drift")
        _hwpx(Path(argv[-1]))
        return 0, False, False

    monkeypatch.setattr(diagnostic, "_run_child_capture", fake)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "refused"
    assert result["reason"] == reason
    assert not (root / RUN_ID).exists()


def test_hardlinked_tool_and_role_collision_refuse_before_child(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    os.link(tool, tmp_path / "alias.jar")
    called: list[bool] = []
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: called.append(True))
    root = _root(tmp_path)
    refused = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert refused["status"] == "refused"
    assert refused["reason"] == "tool_unavailable"
    assert called == []
    collision = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=source,
        java_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert collision["reason"] == "paths_not_distinct"


def test_verify_duplicate_key_is_closed(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch):
    source, java, tool, _ = _inputs(tmp_path, monkeypatch)
    _success_child(monkeypatch)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID, java=java,
        java_sha256=hashlib.sha256(java.read_bytes()).hexdigest(), tool_jar=tool,
    )
    assert result["status"] == "candidate"
    receipt = root / RUN_ID / "receipt.json"
    raw = receipt.read_text(encoding="utf-8")
    receipt.chmod(0o600)
    receipt.write_text(raw[:-2] + ',"status":"candidate"}\n', encoding="utf-8")
    refused = diagnostic.verify_diagnostic(root, RUN_ID)
    assert refused["status"] == "refused"
    assert refused["reason"] == "json_duplicate_key"
