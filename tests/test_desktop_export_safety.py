# -*- coding: utf-8 -*-
"""Card 1: export safety on the writer + export_candidate pair.

These cases fail on the #333 tip (`export_candidate` copies onto dest then
deletes dest when the receipt copy fails) and pass after dest-preserving
pair publish. They do not exercise own_render IoU or rematch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CARGO_TOML = REPO / "desktop" / "src-tauri" / "Cargo.toml"
EXPORT_RS = REPO / "desktop" / "src-tauri" / "src" / "export.rs"
MAIN_RS = REPO / "desktop" / "src-tauri" / "src" / "main.rs"
WRITE_PY = REPO / "engine" / "scripts" / "hwpx_write.py"


def test_export_candidate_no_longer_copies_then_deletes_dest():
    """The #333 command overwrote dest, then remove_file'd it on receipt fail."""
    text = MAIN_RS.read_text(encoding="utf-8")
    assert "export::publish_export_pair" in text
    assert "std::fs::copy(&artifact, &target)" not in text
    assert "std::fs::remove_file(&target)" not in text


def test_export_module_refuses_aliases_and_stages_first():
    text = EXPORT_RS.read_text(encoding="utf-8")
    assert "export_alias" in text
    assert "paths_are_aliases" in text
    assert "CrashAfter" in text
    assert "normalize_windows_path_text" in text
    assert "copy_durable" in text
    # dest is replaced last, after the receipt sidecar
    dest_replace = text.index("atomic_replace(&dest_tmp, dest)")
    receipt_replace = text.index("atomic_replace(&receipt_tmp, &receipt_dest)")
    assert receipt_replace < dest_replace


def test_writer_replaces_dest_only_after_a_complete_temp():
    text = WRITE_PY.read_text(encoding="utf-8")
    start = text.index("    def write(self, path):")
    end = text.index("    def tobytes(self):")
    body = text[start:end]
    assert "os.replace" in body
    assert "os.fsync" in body
    assert "shutil.move" not in body


def test_export_safety_rust_matrix():
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is not installed")
    env = os.environ.copy()
    env.setdefault("CARGO_TERM_COLOR", "never")
    completed = subprocess.run(
        [
            cargo,
            "test",
            "--manifest-path",
            str(CARGO_TOML),
            "--offline",
            "export::",
            "--",
            "--test-threads=1",
        ],
        cwd=str(REPO / "desktop" / "src-tauri"),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=env,
    )
    if completed.returncode != 0 and "offline" in (completed.stderr + completed.stdout):
        completed = subprocess.run(
            [
                cargo,
                "test",
                "--manifest-path",
                str(CARGO_TOML),
                "export::",
                "--",
                "--test-threads=1",
            ],
            cwd=str(REPO / "desktop" / "src-tauri"),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=env,
        )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
