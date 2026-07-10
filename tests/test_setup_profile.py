from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "setup_profile.py"


def test_noninteractive_profile_is_local_and_machine_readable(tmp_path: Path):
    output = tmp_path / ".local" / "user-profile" / "writing_preferences.json"
    proc = subprocess.run([
        sys.executable, str(SCRIPT), "--non-interactive", "--output", str(output),
        "--language", "ko", "--level", "high-school", "--register", "formal-student-report",
        "--avoid", "generic growth narrative", "--avoid", "repeated transitions",
    ], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    profile = json.loads(output.read_text(encoding="utf-8"))
    assert profile["language"] == "ko"
    assert profile["academic_level"] == "high-school"
    assert profile["avoid_patterns"] == ["generic growth narrative", "repeated transitions"]
    assert "numbers" in profile["protected"]
