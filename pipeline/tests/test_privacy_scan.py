"""Tests for privacy_scan.py — public-repo privacy gate.

Runs the script as a subprocess (matches the convention in
test_pipeline_ctl.py) so exit codes and stdout formatting are exercised
exactly as a CI step would see them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "privacy_scan.py"


def run(root: Path, *extra_args: str) -> tuple[dict, int]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--json", *extra_args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        raise AssertionError(
            f"non-JSON stdout\nargs={extra_args}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return payload, proc.returncode


def rules(payload: dict) -> list[str]:
    return [f["rule"] for f in payload["findings"]]


def test_clean_tree_exits_zero(tmp_path: Path):
    (tmp_path / "readme.md").write_text("nothing sensitive here\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 0
    assert payload["findings"] == []
    assert payload["summary"] == {"hard": 0, "warn": 0, "total": 0}


def test_binary_document_extension_is_hard(tmp_path: Path):
    (tmp_path / "report.hwpx").write_bytes(b"not really an hwpx but that's fine")

    payload, code = run(tmp_path)

    assert code == 3
    assert "binary_document_ext" in rules(payload)


def test_denylist_hit_in_content_is_hard(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("secret token: sk-fake-12345\n", encoding="utf-8")
    denylist = tmp_path.parent / "denylist.txt"
    denylist.write_text("sk-fake-12345\n", encoding="utf-8")

    payload, code = run(tmp_path, "--denylist", str(denylist))

    assert code == 3
    assert "denylist_content" in rules(payload)


def test_denylist_hit_in_filename_is_hard(tmp_path: Path):
    (tmp_path / "sk-fake-99999-dump.txt").write_text("harmless body\n", encoding="utf-8")
    denylist = tmp_path.parent / "denylist2.txt"
    denylist.write_text("sk-fake-99999\n", encoding="utf-8")

    payload, code = run(tmp_path, "--denylist", str(denylist))

    assert code == 3
    assert "denylist_name" in rules(payload)


def test_denylist_file_inside_root_is_usage_error(tmp_path: Path):
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("whatever\n", encoding="utf-8")

    payload_proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--denylist", str(denylist), "--json"],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert payload_proc.returncode == 2
    assert payload_proc.stdout.strip() == ""


def test_windows_user_profile_path_is_hard(tmp_path: Path):
    # assembled at runtime so this source file itself never contains the
    # literal user-path pattern (the repo self-scan must stay clean)
    hostile = "loaded config from C:\\Users\\" + "gildonghong\\AppData\\thing\n"
    (tmp_path / "log.txt").write_text(hostile, encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "user_profile_path" in rules(payload)


def test_windows_user_profile_placeholder_is_exempt(tmp_path: Path):
    (tmp_path / "log.txt").write_text(
        r"loaded config from C:\Users\<user>\AppData\Local\thing" + "\n",
        encoding="utf-8",
    )

    payload, code = run(tmp_path)

    assert code == 0
    assert "user_profile_path" not in rules(payload)


def test_email_address_is_hard(tmp_path: Path):
    (tmp_path / "contact.txt").write_text("reach me at pantagram-fake@" + "gmail.com\n", encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "email_address" in rules(payload)


def test_noreply_email_passes(tmp_path: Path):
    (tmp_path / "contact.txt").write_text(
        "bot address: noreply@example-service.com\n"
        "gh bot: 12345+someone@users.noreply.github.com\n",
        encoding="utf-8",
    )

    payload, code = run(tmp_path)

    assert code == 0
    assert "email_address" not in rules(payload)


def test_korean_student_id_proximity_is_warn_only(tmp_path: Path):
    (tmp_path / "roster.txt").write_text("12345 홍길동 배정완료\n", encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 0
    assert "korean_student_id_proximity" in rules(payload)
    warn_findings = [f for f in payload["findings"] if f["rule"] == "korean_student_id_proximity"]
    assert all(f["severity"] == "WARN" for f in warn_findings)


def test_undecodable_binary_blob_with_bin_extension_passes(tmp_path: Path):
    (tmp_path / "blob.bin").write_bytes(bytes(range(256)))

    payload, code = run(tmp_path)

    assert code == 0
    assert payload["findings"] == []


def test_large_file_is_warn_only(tmp_path: Path):
    (tmp_path / "big.txt").write_bytes(b"x" * (1024 * 1024 + 1))

    payload, code = run(tmp_path)

    assert code == 0
    assert "large_file" in rules(payload)


def test_large_file_with_denylist_term_is_hard(tmp_path: Path):
    # A >1MiB file must still be content-scanned (streaming), so a planted
    # denylist term buried past the size threshold is a HARD finding — the
    # large_file WARN is kept alongside it.
    body = (b"x" * (1024 * 1024)) + b"\nleaked secret: sk-fake-BIGLEAK-777\n"
    (tmp_path / "big.txt").write_bytes(body)
    denylist = tmp_path.parent / "denylist_big.txt"
    denylist.write_text("sk-fake-BIGLEAK-777\n", encoding="utf-8")

    payload, code = run(tmp_path, "--denylist", str(denylist))

    assert code == 3
    assert "denylist_content" in rules(payload)
    assert "large_file" in rules(payload)


def test_large_file_with_user_path_is_hard(tmp_path: Path):
    body = (b"x" * (1024 * 1024)) + b"\nloaded from C:\\Users\\realperson\\AppData\\x\n"
    (tmp_path / "big2.txt").write_bytes(body)

    payload, code = run(tmp_path)

    assert code == 3
    assert "user_profile_path" in rules(payload)
    assert "large_file" in rules(payload)


def test_user_path_past_window_in_long_line_normal(tmp_path: Path):
    # A user path at char >15k in a single long line must still be caught: the
    # old blunt 10k truncation missed it; windowing does not. (< 1MiB -> normal
    # path.) Doubled backslashes keep this SOURCE file itself self-scan-clean.
    hostile = ("x" * 20000) + "C:\\Users\\" + "farperson\\AppData\\thing\n"
    (tmp_path / "long.txt").write_text(hostile, encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "user_profile_path" in rules(payload)


def test_user_path_past_window_in_long_line_large(tmp_path: Path):
    # Same, but for the STREAMING (>1MiB) path: path at char 20k inside one huge
    # line, padded past the size threshold.
    line = ("x" * 20000) + "C:\\Users\\" + "farperson\\AppData\\thing" + ("z" * (1024 * 1024))
    (tmp_path / "biglong.txt").write_bytes(line.encode("utf-8") + b"\n")

    payload, code = run(tmp_path)

    assert code == 3
    assert "user_profile_path" in rules(payload)
    assert "large_file" in rules(payload)


def test_cp949_large_file_with_denylist_term_is_hard(tmp_path: Path):
    # A >1MiB cp949-encoded file: the old data.decode('utf-8', errors='ignore')
    # always 'succeeded' and mangled the cp949 text so the term was never seen.
    # The strict utf-8 -> strict cp949 ladder decodes it correctly.
    term = "비밀단어"  # 비밀단어
    body = ("가" * (1024 * 1024)) + "\n유출: " + term + "\n"
    (tmp_path / "big_cp949.txt").write_bytes(body.encode("cp949"))
    denylist = tmp_path.parent / "dl_cp949.txt"
    denylist.write_text(term + "\n", encoding="utf-8")

    payload, code = run(tmp_path, "--denylist", str(denylist))

    assert code == 3
    assert "denylist_content" in rules(payload)


def test_denylist_term_straddling_chunk_boundary_is_hard(tmp_path: Path):
    # A 5000-char denylist term straddling the 1MiB read boundary: a 4096-byte
    # overlap would be shorter than the term and miss it; the 4*term-length
    # text-domain carry catches it whole.
    term = "A" * 5000
    head = "x" * (1024 * 1024 - 2500)   # term's first 2500 chars land in chunk 1
    body = head + term + ("y" * 2500) + "\n"
    (tmp_path / "straddle.txt").write_bytes(body.encode("utf-8"))
    denylist = tmp_path.parent / "dl_straddle.txt"
    denylist.write_text(term + "\n", encoding="utf-8")

    payload, code = run(tmp_path, "--denylist", str(denylist))

    assert code == 3
    assert "denylist_content" in rules(payload)


def test_user_path_me_placeholder_is_exempt(tmp_path: Path):
    # C:\Users\me is a generic doc placeholder — must NOT be flagged.
    (tmp_path / "log.txt").write_text(
        "cfg from C:\\Users\\" + "me\\AppData\\Local\\x\n", encoding="utf-8"
    )

    payload, code = run(tmp_path)

    assert code == 0
    assert "user_profile_path" not in rules(payload)


def test_default_excludes_git_and_node_modules(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret.hwpx").write_bytes(b"junk")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "leftover.pdf").write_bytes(b"junk")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cache.pdf").write_bytes(b"junk")

    payload, code = run(tmp_path)

    assert code == 0
    assert payload["findings"] == []


# --- v0.16 W4.1: profile-store leak markers ----------------------------------

def test_profile_store_manifest_json_is_hard(tmp_path: Path):
    (tmp_path / "leaked.json").write_text(
        '{"schema": "rigorloom/personalization-v1", "version": 1}',
        encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "profile_store_content" in rules(payload)


def test_legacy_profile_store_manifest_is_hard(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(
        '{"schema": "report-pipeline/personalization-v1", "version": 1}',
        encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "profile_store_content" in rules(payload)


def test_extension_pack_registry_id_is_hard(tmp_path: Path):
    (tmp_path / "registry.json").write_text(
        '{"schema": "rigorloom/extension-registry-v1", "api": 1, "extensions": {}}',
        encoding="utf-8")
    (tmp_path / "receipt.json").write_text(
        '{"schema": "rigorloom/extension-receipt-v1", "id": "x", "version": "1.0.0"}',
        encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert rules(payload).count("profile_store_content") == 2


def test_profile_store_jsonl_feedback_log_is_hard(tmp_path: Path):
    (tmp_path / "events.jsonl").write_text(
        '{"schema": "report-pipeline/feedback-event-v1", "at": "t"}\n'
        '{"schema": "report-pipeline/feedback-candidate-v1", "at": "t"}\n',
        encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "profile_store_content" in rules(payload)


def test_profile_store_path_layout_is_hard_even_with_clean_content(tmp_path: Path):
    nested = tmp_path / "artifact" / ".local" / "personalization" / "packs"
    nested.mkdir(parents=True)
    (nested / "innocuous.json").write_text('{"terms": []}', encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "profile_store_path" in rules(payload)


def test_store_schema_string_in_source_code_is_not_a_marker(tmp_path: Path):
    # Structural, not substring: naming the schema in code/docs stays clean.
    (tmp_path / "ctl.py").write_text(
        'SCHEMA = "rigorloom/personalization-v1"' + chr(10), encoding="utf-8")
    (tmp_path / "notes.md").write_text(
        "the store lives at `.local/personalization` and uses "
        "rigorloom/personalization-v1" + chr(10), encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 0
    assert payload["findings"] == []


def test_public_preference_pack_default_is_not_a_marker(tmp_path: Path):
    (tmp_path / "prose_rules.json").write_text(
        '{"schema": "report-pipeline/preference-pack/prose_rules-v1", '
        '"pack_type": "prose_rules", "name": "neutral-default", "version": 1}',
        encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 0
    assert payload["findings"] == []


def test_large_jsonl_store_log_is_still_detected(tmp_path: Path):
    line = ('{"schema": "report-pipeline/feedback-event-v1", "at": "t", '
            '"pad": "%s"}' + chr(10))
    body = "".join(line % ("x" * 200) for _ in range(8000))
    assert len(body.encode("utf-8")) > 1024 * 1024
    (tmp_path / "events.jsonl").write_text(body, encoding="utf-8")

    payload, code = run(tmp_path)

    assert code == 3
    assert "profile_store_content" in rules(payload)


# --- Corpus binary allowlist (W5.2 privacy ruling) ---------------------------
# Relaxation: manifest-listed, sha256-pinned binaries pass binary_document_ext.
# Still-catches #1: unlisted binary / hash drift stays HARD.
# Still-catches #2: PII inside an allowlisted binary stays HARD.

import hashlib
import zipfile


def _write_manifest(manifest_path: Path, entries: list[tuple[str, bytes]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    docs = [{"path": rel, "sha256": hashlib.sha256(data).hexdigest()}
            for rel, data in entries]
    manifest_path.write_text(
        json.dumps({"schema_version": 1, "documents": docs}), encoding="utf-8")


def _write_hwpx(path: Path, section_xml: str) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section_xml)
    return path.read_bytes()


def test_allowlisted_pinned_binary_passes(tmp_path: Path):
    form = tmp_path / "blank.hwpx"
    data = _write_hwpx(form, "<hs:sec>성명 (서명 또는 인)</hs:sec>")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("blank.hwpx", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 0
    assert "binary_document_ext" not in rules(payload)


def test_unlisted_binary_is_still_hard(tmp_path: Path):
    listed = tmp_path / "blank.hwpx"
    data = _write_hwpx(listed, "<hs:sec>blank</hs:sec>")
    (tmp_path / "stray.hwpx").write_bytes(b"unlisted binary")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("blank.hwpx", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 3
    hard = [f for f in payload["findings"] if f["severity"] == "HARD"]
    assert [f["file"] for f in hard] == ["stray.hwpx"]
    assert hard[0]["rule"] == "binary_document_ext"


def test_allowlisted_binary_hash_drift_is_hard(tmp_path: Path):
    form = tmp_path / "blank.hwpx"
    data = _write_hwpx(form, "<hs:sec>blank</hs:sec>")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("blank.hwpx", data)])
    # Tamper after pinning: substitution must be HARD (still-catches #1).
    _write_hwpx(form, "<hs:sec>tampered</hs:sec>")

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 3
    assert "binary_allowlist_hash_mismatch" in rules(payload)


def test_allowlisted_hwpx_with_rrn_is_hard(tmp_path: Path):
    form = tmp_path / "filled.hwpx"
    data = _write_hwpx(
        form, "<hs:sec>주민등록번호 900101-2345678 홍길동</hs:sec>")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("filled.hwpx", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 3
    assert "binary_pii_rrn" in rules(payload)


def test_allowlisted_hwpx_with_filled_phone_is_hard(tmp_path: Path):
    form = tmp_path / "filled.hwpx"
    data = _write_hwpx(form, "<hs:sec>연락처: 010-1234-5678</hs:sec>")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("filled.hwpx", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 3
    assert "binary_pii_phone" in rules(payload)


def test_allowlisted_hwp_utf16_pii_is_hard(tmp_path: Path):
    # A fake .hwp whose bytes carry a UTF-16LE RRN run — the stdlib harvest
    # must surface it even without a CFB parser.
    form = tmp_path / "filled.hwp"
    data = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
            + "성명 김철수 900101-1234567".encode("utf-16-le") + b"\x00" * 16)
    form.write_bytes(data)
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("filled.hwp", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 3
    assert "binary_pii_rrn" in rules(payload)


def test_corpus_manifest_is_autodetected_at_repo_root(tmp_path: Path):
    corpus = tmp_path / "tests" / "corpus" / "forms" / "fam"
    corpus.mkdir(parents=True)
    form = corpus / "blank.hwpx"
    data = _write_hwpx(form, "<hs:sec>blank template</hs:sec>")
    _write_manifest(tmp_path / "tests" / "corpus" / "forms" / "manifest.json",
                    [("fam/blank.hwpx", data)])

    payload, code = run(tmp_path)  # no --binary-allowlist flag

    assert code == 0
    assert "binary_document_ext" not in rules(payload)


def test_blank_form_labels_do_not_false_positive(tmp_path: Path):
    # Blank-form placeholder shapes (unfilled label + digit ruler) must not
    # trip the PII nets — only *filled* values do.
    form = tmp_path / "blank.hwpx"
    data = _write_hwpx(
        form,
        "<hs:sec>전화번호(또는 휴대전화번호):      주민등록번호: - "
        "생년월일(성별) (    )</hs:sec>")
    manifest = tmp_path / "corpus.json"
    _write_manifest(manifest, [("blank.hwpx", data)])

    payload, code = run(tmp_path, "--binary-allowlist", str(manifest))

    assert code == 0


def test_malformed_allowlist_manifest_is_usage_error(tmp_path: Path):
    (tmp_path / "blank.hwpx").write_bytes(b"binary")
    manifest = tmp_path / "corpus.json"
    manifest.write_text('{"documents": [{"path": "blank.hwpx"}]}', encoding="utf-8")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--json",
         "--binary-allowlist", str(manifest)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )

    assert proc.returncode == 2
