"""Focused regression tests for the shared child evidence extension."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnostic_candidate_core as core  # noqa: E402


def test_run_child_capture_evidence_is_hash_and_count_only() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(bytes((118,101,114,115,105,111,110,10))); "
        "sys.stderr.buffer.write(bytes((110,111,105,115,101,10)))"
    )
    result = core.run_child_capture(
        [sys.executable, "-c", script], timeout=5.0,
        return_evidence=True,
    )
    code, timed_out, overflow, evidence = result
    assert code == 0
    assert timed_out is False
    assert overflow is False
    assert evidence == {
        "output": {"sha256": hashlib.sha256(b"version\n").hexdigest(),
                   "bytes": len(b"version\n")},
        "error": {"sha256": hashlib.sha256(b"noise\n").hexdigest(),
                  "bytes": len(b"noise\n")},
    }
    assert core.run_child_capture(
        [sys.executable, "-c", "pass"], timeout=5.0
    ) == (0, False, False)
