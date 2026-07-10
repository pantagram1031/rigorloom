from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
FIDELITY_PATH = ROOT / "pipeline" / "scripts" / "prose_fidelity.py"
HUMANIZE_PATH = ROOT / "pipeline" / "scripts" / "humanization_ctl.py"
SPEC = importlib.util.spec_from_file_location("prose_fidelity", FIDELITY_PATH)
fidelity = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fidelity)


def test_identical_protected_facts_pass_after_style_edit():
    before = "## 결과\n\n[SRC-2] 측정값은 약 18.6%였고 감소하지 않았다. [[EQ latex=\"x=2\"]]"
    after = "## 결과\n\n[SRC-2] 측정값은 약 18.6%였으며 감소하지 않았다. [[EQ latex=\"x=2\"]]"
    result = fidelity.audit_text(before, after)
    assert result["pass"]
    assert result["changes"] == []


def test_number_tag_heading_and_qualifier_changes_fail():
    before = "## 결과\n\n최소 18.6%이며 감소하지 않았다. [[FIG file=\"a.png\"]]"
    after = "## 결론\n\n약 20%이며 감소했다. [[FIG file=\"b.png\"]]"
    result = fidelity.audit_text(before, after)
    assert not result["pass"]
    assert {item["kind"] for item in result["changes"]} >= {"numbers", "tags", "headings", "qualifiers"}


def test_humanization_apply_accepts_safe_change(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    content = bundle / "content.md"
    content.write_text("## 결과\n\n측정값은 18.6%였다.\n", encoding="utf-8")
    prep = subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], capture_output=True, text=True)
    assert prep.returncode == 0, prep.stderr
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({"changes": [{
        "paragraph_id": "p0002", "before": "측정값은 18.6%였다.",
        "after": "측정한 값은 18.6%로 나타났다.", "reasons": ["sentence rhythm"]
    }]}, ensure_ascii=False), encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert "측정한 값은 18.6%" in content.read_text(encoding="utf-8")
    assert json.loads((bundle / "prose_fidelity.json").read_text(encoding="utf-8"))["pass"]


def test_humanization_apply_rolls_back_unsafe_change(tmp_path: Path):
    ws = tmp_path / "report-demo"
    bundle = ws / "bundle"
    bundle.mkdir(parents=True)
    original = "## 결과\n\n측정값은 18.6%였다.\n"
    content = bundle / "content.md"
    content.write_text(original, encoding="utf-8")
    subprocess.run([sys.executable, str(HUMANIZE_PATH), "prepare", str(ws)], check=True, capture_output=True, text=True)
    changes = bundle / "changes.json"
    changes.write_text(json.dumps({"changes": [{
        "paragraph_id": "p0002", "before": "측정값은 18.6%였다.", "after": "측정값은 약 20%였다."
    }]}, ensure_ascii=False), encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, str(HUMANIZE_PATH), "apply", str(ws), "--changes", str(changes)],
        capture_output=True, text=True,
    )
    assert applied.returncode == 1
    assert content.read_text(encoding="utf-8") == original
    report = json.loads((bundle / "humanization_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "rolled_back"
