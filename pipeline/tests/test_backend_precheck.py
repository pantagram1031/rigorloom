"""Tests for backend_precheck.py — config-driven model/CLI preflight.

Focus: a malformed, empty, or partial config must be a usage error (exit 2),
never a permissive parse that yields a misleading exit 0. Runs the script as a
subprocess so exit codes are exercised exactly as a CI/council step sees them.
Synthetic configs only (no real backend names).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "backend_precheck.py"
EXAMPLE = Path(__file__).parents[1] / "references" / "backends.example.yaml"


def run(*args: str) -> tuple[str, int]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return proc.stdout, proc.returncode


def test_shipped_example_config_is_valid(tmp_path: Path):
    # the generic example ships two well-formed backends -> exit 0 (informational)
    stdout, code = run("--config", str(EXAMPLE))
    assert code == 0, stdout
    payload = json.loads(stdout)
    assert len(payload["backends"]) == 2


def test_empty_backends_list_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("backends:\n", encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout
    assert json.loads(stdout)["ok"] is False


def test_missing_backends_key_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "nobackends.yaml"
    cfg.write_text("something_else: 1\n", encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout


def test_malformed_json_config_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "broken.json"
    cfg.write_text('{"backends": [ this is not json', encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout
    assert json.loads(stdout)["ok"] is False


def test_backend_missing_name_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "noname.json"
    cfg.write_text(json.dumps({"backends": [{"live_cmd": ["x", "-"]}]}), encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout


def test_backend_missing_live_cmd_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "nolive.json"
    cfg.write_text(json.dumps({"backends": [{"name": "a"}]}), encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout


def test_backend_live_cmd_not_a_list_is_usage_error(tmp_path: Path):
    cfg = tmp_path / "badlive.json"
    cfg.write_text(json.dumps({"backends": [{"name": "a", "live_cmd": "x -"}]}), encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 2, stdout


def run_no_yaml(cfg: Path) -> tuple[str, int]:
    """Run backend_precheck.main() in a subprocess with the `yaml` import forced
    to fail (sys.modules['yaml'] = None -> ImportError), so the no-PyYAML block
    parser is exercised regardless of whether pyyaml is installed here."""
    pycode = (
        "import sys\n"
        "sys.modules['yaml'] = None\n"
        f"sys.path.insert(0, r'{SCRIPT.parent}')\n"
        "import backend_precheck as bp\n"
        f"sys.argv = ['backend_precheck.py', '--config', r'{cfg}']\n"
        "bp.main()\n"
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, "-c", pycode],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return proc.stdout, proc.returncode


def test_block_parser_mixed_valid_corrupt_is_usage_error(tmp_path: Path):
    # A config with a valid backend followed by a corrupt (colon-less) line,
    # forced down the no-PyYAML fallback parser, must be a HARD usage error
    # (exit 2) — not a permissive parse that silently drops the corrupt line.
    cfg = tmp_path / "mixed.yaml"
    cfg.write_text(
        "backends:\n"
        "  - name: a\n"
        '    live_cmd: ["a-cli", "-"]\n'
        "    this line has no colon and is corrupt\n",
        encoding="utf-8",
    )
    stdout, code = run_no_yaml(cfg)
    assert code == 2, stdout
    assert json.loads(stdout)["ok"] is False


def test_block_parser_wellformed_config_passes_without_yaml(tmp_path: Path):
    # Guard the happy path: a well-formed config still parses under the fallback.
    cfg = tmp_path / "ok.yaml"
    cfg.write_text(
        "backends:\n"
        "  - name: a\n"
        '    live_cmd: ["a-cli", "-"]\n'
        '    expect: "PING_OK"\n',
        encoding="utf-8",
    )
    stdout, code = run_no_yaml(cfg)
    assert code == 0, stdout
    payload = json.loads(stdout)
    assert payload["backends"][0]["backend"] == "a"


def test_valid_json_config_passes(tmp_path: Path):
    cfg = tmp_path / "ok.json"
    cfg.write_text(json.dumps({"backends": [
        {"name": "a", "live_cmd": ["a-cli", "-"], "expect": "PING_OK"},
    ]}), encoding="utf-8")
    stdout, code = run("--config", str(cfg))
    assert code == 0, stdout
    payload = json.loads(stdout)
    assert payload["backends"][0]["backend"] == "a"
