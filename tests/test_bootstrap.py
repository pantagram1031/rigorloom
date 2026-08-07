from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

from _module_gating import requires_report_module
from scripts import bootstrap


REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _run(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--profile-root", str(tmp_path / "prof"),
            "--workspace-root", str(tmp_path / "ws"),
            *extra,
        ],
        capture_output=True, text=True, encoding="utf-8",
    )


@requires_report_module
def test_bootstrap_clone_and_go_exits_zero(tmp_path: Path):
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "bootstrap: OK" in proc.stdout


@requires_report_module
def test_bootstrap_creates_smoke_artifacts(tmp_path: Path):
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout

    # Profile: every public default pack registered into the private store.
    # DERIVED from the pack-type registry, not a filename list: which pack
    # types exist depends on which distribution modules are enabled, so a new
    # work-type module must not require an edit here (modules/README.md's
    # "adding a module later requires no core change").
    personalization = _load(
        "personalization_ctl_for_bootstrap_tests",
        REPO_ROOT / "pipeline" / "scripts" / "personalization_ctl.py",
    )
    expected = sorted(f"{pack_type}.json"
                      for pack_type in personalization.default_pack_files())
    # Non-vacuity: the core pack types are always among them.
    assert {"backends.json", "figure_style.json", "policy_floors.json",
            "prose_rules.json"} <= set(expected)

    packs = tmp_path / "prof" / "packs"
    assert packs.is_dir()
    names = sorted(p.name for p in packs.glob("*.json"))
    assert names == expected

    # Smoke workspace with the passing gate checker and the resolved gate.
    ws = tmp_path / "ws" / "report-bootstrap-smoke"
    assert (ws / "sim" / "gates.py").is_file()
    assert (ws / "PIPELINE.md").is_file()

    receipts = ws / ".pipeline" / "gate_checks.jsonl"
    assert receipts.is_file()
    last = [ln for ln in receipts.read_text(encoding="utf-8").splitlines() if ln.strip()][-1]
    receipt = json.loads(last)
    assert receipt["gate"] == "sane"
    assert receipt["exit"] == 0


@requires_report_module
def test_bootstrap_is_idempotent(tmp_path: Path):
    first = _run(tmp_path)
    assert first.returncode == 0, first.stderr or first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0, second.stderr or second.stdout
    assert "bootstrap: OK" in second.stdout


def test_bootstrap_skip_smoke(tmp_path: Path):
    proc = _run(tmp_path, "--skip-smoke")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "skipped (--skip-smoke)" in proc.stdout
    # Profile is still set up, but no smoke workspace is created.
    assert (tmp_path / "prof" / "packs").is_dir()
    assert not (tmp_path / "ws" / "report-bootstrap-smoke").exists()


def test_render_probe_failure_is_informational(monkeypatch, capsys):
    broken_probe = types.SimpleNamespace(
        probe=lambda: (_ for _ in ()).throw(OSError("probe failed")),
        format_table=lambda result: str(result),
    )
    monkeypatch.setitem(sys.modules, "render_probe", broken_probe)

    bootstrap._print_render_capabilities()

    assert "Render capability matrix: unavailable (probe failed)" in capsys.readouterr().out
