"""Frame-level contracts shared by deterministic checker CLIs."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "checker_base.py"
_spec = importlib.util.spec_from_file_location("checker_base", SCRIPT)
checker_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker_base)


def test_verdict_skeleton_and_exit_mapping_are_stable():
    hard = [{"code": "H", "msg": "broken"}]
    verdict = checker_base.verdict_skeleton(
        "report",
        "synthetic",
        hard=hard,
        warn=[{"code": "W", "msg": "advisory"}],
        extra={"checked": 2},
    )

    assert verdict == {
        "ok": False,
        "workspace": "report",
        "checker": "synthetic",
        "checked": 2,
        "hard": hard,
        "warn": [{"code": "W", "msg": "advisory"}],
        "counts": {"hard": 1, "warn": 1},
        "verdict": "fail",
    }
    assert checker_base.exit_code(hard=[]) == 0
    assert checker_base.exit_code(usage=True) == 2
    assert checker_base.exit_code(hard=hard) == 3


def test_usage_error_supports_full_and_legacy_minimal_shapes():
    full, full_code = checker_base.usage_error(
        "report", "synthetic", "bad input"
    )
    minimal, minimal_code = checker_base.usage_error(
        "report", "synthetic", "bad input", minimal=True
    )

    assert full_code == minimal_code == 2
    assert full == {
        "ok": False,
        "workspace": "report",
        "checker": "synthetic",
        "error": "bad input",
        "hard": [],
        "warn": [],
        "counts": {"hard": 0, "warn": 0},
        "verdict": "usage_error",
    }
    assert minimal == {"ok": False, "error": "bad input"}


def test_dump_json_is_utf8_and_rejects_non_finite_numbers():
    assert json.loads(checker_base.dump_json({"text": "한글"})) == {
        "text": "한글"
    }
    with pytest.raises(ValueError):
        checker_base.dump_json({"value": math.nan})


def test_cli_main_adds_out_prints_and_writes_identical_json(tmp_path, capsys):
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace")
    target = tmp_path / "verdict.json"

    code = checker_base.cli_main(
        parser,
        lambda args: (
            checker_base.verdict_skeleton(
                args.workspace, "synthetic", extra={"text": "한글"}
            ),
            0,
        ),
        ["report", "--out", str(target)],
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == json.loads(
        target.read_text(encoding="utf-8")
    )
