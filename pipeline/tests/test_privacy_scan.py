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
