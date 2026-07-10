from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "new_report.py"
SPEC = importlib.util.spec_from_file_location("new_report", MODULE_PATH)
new_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(new_report)


def test_slug_cannot_escape_workspace_root(tmp_path: Path):
    for value in ("../outside", "x/../../../outside", "has space", ""):
        try:
            new_report._assert_safe_workspace(tmp_path, value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe slug accepted: {value!r}")


def test_yaml_string_handles_quotes_and_newlines():
    encoded = new_report._yaml_string('question "one"\nquestion two')
    assert '\\n' in encoded
    assert '\\"one\\"' in encoded


def test_scaffolder_initializes_atomically(tmp_path: Path):
    form = tmp_path / "form #1.hwpx"
    form.write_bytes(b"fixture")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "demo", "--subject", "science: one",
            "--topic", "line one # literal\nline two", "--form", str(form),
            "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    workspace = Path(payload["workspace"])
    assert workspace == root / "report-demo"
    assert (workspace / "PIPELINE.md").exists()
    assert (workspace / "NEXT_TASK.md").exists()
    assert (workspace / "WORKSPACE_INDEX.md").exists()
    assert (workspace / ".pipeline" / "artifacts.json").exists()
    assert (workspace / "work" / "stage-0" / "scratch").is_dir()
    handoff = json.loads((workspace / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["workspace"] == str(workspace.resolve())
    assert not list(root.glob(".creating-*"))
