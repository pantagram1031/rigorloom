# -*- coding: utf-8 -*-
"""Focused contract tests for the read-only installed-product doctor."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from _runtime_client import runtime_scripts_on_path

runtime_scripts_on_path()

import cli  # noqa: E402
import doctor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def _invoke(*argv: str) -> tuple[int, dict, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = cli.main(list(argv))
    payload = json.loads(stdout.getvalue())
    return code, payload, stdout.getvalue(), stderr.getvalue()


def _argparse_failure(*argv: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(list(argv))
    return int(excinfo.value.code), stdout.getvalue(), stderr.getvalue()


def _engine_fixture(tmp_path: Path, *, probe_source: bytes | None = None) -> Path:
    root = tmp_path / "installed-engine"
    (root / "engine" / "scripts").mkdir(parents=True)
    (root / "pipeline" / "scripts").mkdir(parents=True)
    (root / "modules" / "style").mkdir(parents=True)
    (root / "engine" / "scripts" / "form_inspect.py").write_text(
        "# marker", encoding="utf-8"
    )
    payload = {
        "schema": doctor.PROBE_SCHEMA,
        "platform": sys.platform,
        "render": {
            "hancom_com": False,
            "soffice": False,
            "renderers": [],
            "pdf_capable": False,
        },
        "modules": {"enabled": ["style"]},
        "backends": "unconfigured",
    }
    source = probe_source or (
        "import json\n"
        f"print(json.dumps({payload!r}, separators=(',', ':')))\n"
    ).encode("utf-8")
    (root / "engine" / "scripts" / "probe.py").write_bytes(source)
    (root / "pipeline" / "scripts" / "module_registry.py").write_text(
        "# marker", encoding="utf-8"
    )
    (root / "pipeline" / "scripts" / "privacy_scan.py").write_text(
        "# marker", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        "[project]\nname='rigorloom'\nversion='0.17.0'\n", encoding="utf-8"
    )
    (root / "modules" / "enabled.yaml").write_text(
        f"schema: {doctor.ENABLED_SCHEMA}\nenabled: [style]\n", encoding="utf-8"
    )
    (root / "modules" / "style" / "module.yaml").write_text(
        "schema: rigorloom-module/v1\n", encoding="utf-8"
    )
    return root


def _check(payload: dict, check_id: str) -> dict:
    return next(row for row in payload["result"]["checks"] if row["id"] == check_id)


def test_wheel_only_no_root_is_successful_and_leaks_no_checkout_path(tmp_path):
    site = tmp_path / "site"
    package = site / "rigorloom_runtime"
    shutil.copytree(
        REPO_ROOT / "runtime" / "scripts",
        package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONSTARTUP", doctor.CHILD_PYTHON_ENV):
        environment.pop(key, None)
    environment["PYTHONPATH"] = str(site)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from rigorloom_runtime.cli import main; raise SystemExit(main(['doctor']))",
        ],
        cwd=str(tmp_path),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    code = completed.returncode
    stdout = completed.stdout
    payload = json.loads(stdout)

    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "doctor"
    assert payload["result"]["schema"] == doctor.DOCTOR_SCHEMA
    assert payload["result"]["requiredPassed"] is True
    engine = _check(payload, "engine")
    assert engine["state"] == "unavailable"
    assert engine["required"] is False
    assert engine["reason"]["code"] == "engine_root_not_configured"
    assert str(REPO_ROOT) not in stdout
    decoded, end = json.JSONDecoder().raw_decode(stdout)
    assert decoded == payload
    assert stdout[end:].strip() == ""


def test_recognized_installed_engine_reports_modules_and_observed_render(tmp_path):
    engine_root = _engine_fixture(tmp_path)

    code, payload, _stdout, _stderr = _invoke(
        "doctor", "--engine-root", str(engine_root)
    )

    assert code == 0
    assert payload["result"]["requiredPassed"] is True
    engine = _check(payload, "engine")
    assert engine["state"] == "pass"
    assert all(engine["facts"]["markers"].values())
    assert engine["facts"]["enabledModules"] == ["style"]
    assert engine["facts"]["enabledState"] == "configured"
    assert engine["facts"]["probeSchema"] == doctor.PROBE_SCHEMA
    assert engine["facts"]["render"]["hancom_com"] is False
    assert engine["facts"]["render"]["pdf_capable"] is False


def test_missing_engine_marker_is_typed_required_failure(tmp_path):
    engine_root = _engine_fixture(tmp_path)
    (engine_root / "pipeline" / "scripts" / "privacy_scan.py").unlink()

    code, payload, _stdout, _stderr = _invoke(
        "doctor", "--engine-root", str(engine_root)
    )

    assert code == 3
    assert payload["ok"] is False
    assert payload["result"]["requiredPassed"] is False
    engine = _check(payload, "engine")
    assert engine["state"] == "fail"
    assert engine["reason"]["code"] == "engine_markers_missing"
    assert engine["facts"]["markers"]["pipeline/scripts/privacy_scan.py"] is False


def test_doctor_usage_error_is_exit_two_and_one_json_document():
    code, payload, stdout, stderr = _invoke("doctor", "--engine-root")

    assert code == 2
    assert payload["ok"] is False
    assert payload["command"] == "doctor"
    assert payload["error"]["code"] == "invalid_params"
    assert "expected one argument" in stderr
    decoded, end = json.JSONDecoder().raw_decode(stdout)
    assert decoded == payload
    assert stdout[end:].strip() == ""


@pytest.mark.parametrize(
    ("argv", "diagnostic"),
    [
        (("capabilities", "doctor"), "unrecognized arguments: doctor"),
        (("--root", "doctor"), "required: command"),
        (
            ("install", "--engine-root", "doctor"),
            "required: --bundles-dir",
        ),
    ],
)
def test_non_doctor_parse_failures_are_not_mislabeled(argv, diagnostic):
    code, stdout, stderr = _argparse_failure(*argv)

    assert code == 2
    assert stdout == ""
    assert diagnostic in stderr
    assert '"command": "doctor"' not in stdout


def test_doctor_bogus_argument_is_typed_usage_and_one_json_document():
    code, payload, stdout, stderr = _invoke("doctor", "--bogus")

    assert code == 2
    assert payload["ok"] is False
    assert payload["command"] == "doctor"
    assert payload["error"]["code"] == "invalid_params"
    assert "unrecognized arguments: --bogus" in stderr
    decoded, end = json.JSONDecoder().raw_decode(stdout)
    assert decoded == payload
    assert stdout[end:].strip() == ""


@pytest.mark.parametrize("equals_form", [False, True])
def test_global_options_reach_doctor_without_creating_runtime_root(
    tmp_path, equals_form
):
    runtime_root = tmp_path / "must-not-be-created"
    engine_root = tmp_path / "missing-engine"
    argv = (
        [
            f"--root={runtime_root}",
            f"--engine-root={engine_root}",
            "doctor",
        ]
        if equals_form
        else [
            "--root", str(runtime_root),
            "--engine-root", str(engine_root),
            "doctor",
        ]
    )

    code, payload, _stdout, _stderr = _invoke(*argv)

    assert code == 3
    assert payload["command"] == "doctor"
    assert _check(payload, "engine")["reason"]["code"] == "engine_markers_missing"
    assert not runtime_root.exists()


def test_malformed_utf8_probe_output_is_typed_failure(tmp_path):
    source = (
        b"import sys\n"
        b"sys.stdout.buffer.write(b'{\"schema\":\"rigorloom-capability-probe/v1\","
        b"\"render\":\\xff}')\n"
    )
    engine_root = _engine_fixture(tmp_path, probe_source=source)

    code, payload, stdout, _stderr = _invoke(
        "doctor", "--engine-root", str(engine_root)
    )

    assert code == 3
    assert payload["ok"] is False
    engine = _check(payload, "engine")
    assert engine["reason"]["code"] == "engine_probe_output_invalid"
    assert "\ufffd" in engine["reason"]["message"]
    assert "internal_error" not in stdout


def test_broken_child_python_is_typed_required_failure(tmp_path):
    missing = tmp_path / "missing-python.exe"
    with patch.dict(os.environ, {doctor.CHILD_PYTHON_ENV: str(missing)}):
        code, payload, _stdout, _stderr = _invoke("doctor")

    assert code == 3
    child = _check(payload, "child_python")
    assert child["required"] is True
    assert child["state"] == "fail"
    assert child["reason"]["code"] == "child_python_not_executable"


def test_runtime_interpreter_floor_is_required():
    supported = doctor._runtime_python_check((3, 10, 0))
    unsupported = doctor._runtime_python_check((3, 9, 18))

    assert supported["state"] == "pass"
    assert unsupported["state"] == "fail"
    assert unsupported["required"] is True
    assert unsupported["reason"]["code"] == "python_version_unsupported"


def test_builder_absence_is_informational_not_consumer_failure():
    row = doctor._builder_check({
        "setuptools": "69.5.1",
        "wheel": None,
    })

    assert row["required"] is False
    assert row["state"] == "unavailable"
    assert row["reason"]["code"] == "wheel_toolchain_unavailable"


def test_doctor_spawns_only_python_facts_and_installed_probe(tmp_path):
    engine_root = _engine_fixture(tmp_path)
    calls: list[list[str]] = []
    child_payload = {
        "schema": "rigorloom-child-python/v1",
        "version": [3, 12, 0],
        "implementation": "cpython",
        "setuptools": None,
        "wheel": None,
    }
    probe_payload = {
        "schema": doctor.PROBE_SCHEMA,
        "render": {"hancom_com": False, "renderers": [], "pdf_capable": False},
    }

    def fake_run(argv, **_kwargs):
        command = [str(item) for item in argv]
        calls.append(command)
        payload = child_payload if "-c" in command else probe_payload
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload).encode("utf-8"),
            stderr=b"",
        )

    with patch("doctor.subprocess.run", side_effect=fake_run):
        result, code = doctor.run_doctor(str(engine_root), environ={})

    assert code == 0
    assert result["requiredPassed"] is True
    assert len(calls) == 2
    assert calls[0][1] == "-c"
    assert Path(calls[1][1]).resolve() == (
        engine_root / "engine" / "scripts" / "probe.py"
    ).resolve()
    assert calls[1][2] == "--json"
    flattened = "\n".join(" ".join(call) for call in calls).lower()
    for forbidden in (
        "com_backend", "hwpframe", "pyhwpx", "soffice",
        "render_probe", "win32com",
    ):
        assert forbidden not in flattened
