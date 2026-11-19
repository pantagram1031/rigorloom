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
    assert "an_existing_artifact_without_a_receipt_is_preserved_on_failure" in text
    assert "an_existing_receipt_without_an_artifact_is_preserved_on_failure" in text
    assert "a_destination_hard_linked_to_the_runtime_artifact_is_preserved" in text
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
    compiled = _run_to_files(
        [rustc, "--test", "--edition", "2021", "-o", str(binary), str(HARNESS)], tmp_path, "rustc")
    assert compiled[0] == 0, compiled[1]
    completed = _run_to_files([str(binary), "--test-threads=1"], tmp_path, "matrix")
    assert completed[0] == 0, completed[1]


def _run_to_files(cmd, tmp_path, name):
    """Run cmd with its output in files, not pipes.

    On Windows, rustc's MSVC linker can start vctip.exe (Visual Studio
    telemetry), which inherits the output handles and outlives the link.
    With pipes, subprocess then waits for that child to close them and the
    call times out although rustc finished long before. Files have no such
    wait, and VSCMD_SKIP_SENDTELEMETRY asks the linker not to start it.
    """
    env = dict(os.environ, VSCMD_SKIP_SENDTELEMETRY="1")
    out_path = tmp_path / f"{name}.out"
    with open(out_path, "wb") as out:
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=out, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, env=env, timeout=180, check=False)
    text = out_path.read_text(encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(text)
    return proc.returncode, text
