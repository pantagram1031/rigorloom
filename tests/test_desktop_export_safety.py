# -*- coding: utf-8 -*-
"""Card 1: export safety on the writer + export_candidate pair.

These cases fail on the #333 tip (`export_candidate` copies onto dest then
deletes dest when the receipt copy fails) and pass after dest-preserving
pair publish. They do not exercise own_render IoU or rematch.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
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
    assert "publish_export_pair_hold" in text
    assert "park_for_force_quit" in text
    assert "normalize_windows_path_text" in text
    assert "copy_durable" in text
    # dest is replaced last, after the receipt sidecar
    dest_replace = text.index("atomic_replace(&dest_tmp, dest)")
    receipt_replace = text.index("atomic_replace(&receipt_tmp, &receipt_dest)")
    landed = text.index("let (landed_sha, landed_bytes)")
    bak_gone = text.rindex("remove_if_exists(&dest_bak)")
    assert receipt_replace < dest_replace
    assert dest_replace < landed < bak_gone


def test_writer_replaces_dest_only_after_a_complete_temp():
    text = WRITE_PY.read_text(encoding="utf-8")
    start = text.index("    def write(self, path):")
    end = text.index("    def tobytes(self):", start)
    body = text[start:end]
    assert "os.replace" in body
    assert "os.fsync" in body
    assert "shutil.move(" not in body


HARNESS = Path(__file__).resolve().parent / "desktop_export_safety_harness.rs"


def test_export_safety_rust_matrix(tmp_path):
    rustc = shutil.which("rustc")
    if rustc is None:
        pytest.skip("rustc is not installed")
    binary = tmp_path / "export_safety"
    compiled = subprocess.run(
        [rustc, "--test", "--edition", "2021", "-o", str(binary), str(HARNESS)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if compiled.returncode != 0:
        sys.stderr.write(compiled.stdout)
        sys.stderr.write(compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    completed = subprocess.run(
        [str(binary), "--test-threads=1"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
