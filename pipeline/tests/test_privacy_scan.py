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
    (tmp_path / "log.txt").write_text(
        r"loaded config from C:\Users\gildonghong\AppData\Local\thing" + "\n",
        encoding="utf-8",
    )

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
    (tmp_path / "contact.txt").write_text("reach me at pantagram-fake@gmail.com\n", encoding="utf-8")

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
