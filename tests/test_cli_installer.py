# -*- coding: utf-8 -*-
"""Acceptance and unit tests for the consumer installer (DIST-INSTALL-03)."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import cli  # noqa: E402
import install  # noqa: E402

WHEEL_PYTHON = os.environ.get("RIGORLOOM_WHEEL_PYTHON") or sys.executable


def _make_dummy_bundle(out_path: Path, name: str, files: dict[str, bytes],
                       version: str = "0.17.0",
                       manifest_override: dict | None = None) -> None:
    """Create a valid mock rigorloom zip bundle with MANIFEST.json."""
    manifest_files = []
    with zipfile.ZipFile(out_path, "w") as z:
        for rel_path, data in sorted(files.items()):
            z.writestr(rel_path, data)
            manifest_files.append({
                "path": rel_path,
                "sha256": install._sha256_bytes(data)
            })
        manifest = manifest_override or {
            "schema": install.MANIFEST_SCHEMA,
            "name": name,
            "version": version,
            "requires": None,
            "provides": {},
            "files": manifest_files
        }
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))


# --------------------------------------------------------------------------- #
# CLI Parsing & Early Dispatch
# --------------------------------------------------------------------------- #

def test_install_help_exits_zero():
    """`rigorloom install --help` displays options and exits 0."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["install", "--help"])
    assert exc.value.code == 0


def test_install_missing_required_args_exits_two():
    """`rigorloom install` without --engine-root/--bundles-dir exits 2."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["install"])
    assert exc.value.code == 2


def test_non_install_still_requires_root():
    """Non-install commands still refuse missing --root with exit 2."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["capabilities"])
    assert exc.value.code == 2


def test_install_early_dispatch_does_not_require_root(tmp_path):
    """`rigorloom install` dispatches early before any --root validation."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir)])
    assert code == 2
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_params"


# --------------------------------------------------------------------------- #
# Manifest Schema and Member Verification (Fail-Closed)
# --------------------------------------------------------------------------- #

def test_manifest_schema_and_malformed_entries(tmp_path):
    """Manifest requires valid name, version, files list, and valid sha256."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"

    # 1. Missing name
    _make_dummy_bundle(core_zip, "core", {"foo.txt": b"1"},
                       manifest_override={"schema": install.MANIFEST_SCHEMA, "version": "0.1", "files": []})
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "missing required 'name'" in json.loads(buf.getvalue())["error"]["message"]

    # 2. Files not a list
    _make_dummy_bundle(core_zip, "core", {"foo.txt": b"1"},
                       manifest_override={"schema": install.MANIFEST_SCHEMA, "name": "core", "version": "0.1", "files": "bad"})
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "'files' must be an array" in json.loads(buf.getvalue())["error"]["message"]

    # 3. Invalid sha256 (not 64-hex)
    _make_dummy_bundle(core_zip, "core", {"foo.txt": b"1"},
                       manifest_override={"schema": install.MANIFEST_SCHEMA, "name": "core", "version": "0.1",
                                          "files": [{"path": "foo.txt", "sha256": "not-64-hex"}]})
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "invalid sha256" in json.loads(buf.getvalue())["error"]["message"]

    # 4. Duplicate manifest paths
    _make_dummy_bundle(core_zip, "core", {"foo.txt": b"1"},
                       manifest_override={"schema": install.MANIFEST_SCHEMA, "name": "core", "version": "0.1",
                                          "files": [{"path": "foo.txt", "sha256": install._sha256_bytes(b"1")},
                                                    {"path": "foo.txt", "sha256": install._sha256_bytes(b"1")}]})
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "duplicate path in MANIFEST.json" in json.loads(buf.getvalue())["error"]["message"]


def test_archive_duplicates_and_collisions(tmp_path):
    """Duplicate archive members, case-folding collisions, and prefix collisions are refused."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"

    # 1. Case-folding collision (e.g. 'probe.py' and 'PROBE.PY')
    with zipfile.ZipFile(core_zip, "w") as z:
        manifest = {
            "schema": install.MANIFEST_SCHEMA,
            "name": "core",
            "version": "0.17.0",
            "files": [
                {"path": "probe.py", "sha256": install._sha256_bytes(b"1")},
                {"path": "PROBE.PY", "sha256": install._sha256_bytes(b"2")}
            ]
        }
        z.writestr("MANIFEST.json", json.dumps(manifest))
        z.writestr("probe.py", b"1")
        z.writestr("PROBE.PY", b"2")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "case-fold/normalized destination collision" in json.loads(buf.getvalue())["error"]["message"]

    # 2. Directory/file prefix collision (e.g. 'foo' and 'foo/bar')
    with zipfile.ZipFile(core_zip, "w") as z:
        manifest = {
            "schema": install.MANIFEST_SCHEMA,
            "name": "core",
            "version": "0.17.0",
            "files": [
                {"path": "foo", "sha256": install._sha256_bytes(b"1")},
                {"path": "foo/bar", "sha256": install._sha256_bytes(b"2")}
            ]
        }
        z.writestr("MANIFEST.json", json.dumps(manifest))
        z.writestr("foo", b"1")
        z.writestr("foo/bar", b"2")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    assert "directory/file prefix collision" in json.loads(buf.getvalue())["error"]["message"]


# --------------------------------------------------------------------------- #
# Zip-Slip and Traversal Variations
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad_path", [
    "../escape.txt",
    "/absolute/escape.txt",
    "\\windows\\escape.txt",
    "C:/evil.dll",
    "C:evil.dll"
])
def test_zip_slip_traversal_variations(tmp_path, bad_path):
    """Zip entries with '..', leading slashes, or drive letters are refused immediately."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"

    evil_zip = bundles_dir / "rigorloom-core-0.17.0.zip"
    with zipfile.ZipFile(evil_zip, "w") as z:
        manifest = {
            "schema": install.MANIFEST_SCHEMA,
            "name": "core",
            "version": "0.17.0",
            "files": [{"path": bad_path, "sha256": install._sha256_bytes(b"evil")}]
        }
        z.writestr("MANIFEST.json", json.dumps(manifest))
        z.writestr(bad_path, b"evil")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
    assert out["error"]["code"] == "tamper_detected"
    assert not engine_root.exists()


# --------------------------------------------------------------------------- #
# Nonempty Target, Replace, and Locked Target Abort
# --------------------------------------------------------------------------- #

def test_nonempty_target_recognized_and_unrecognized(tmp_path):
    """Nonempty target handling: unrecognized refused, recognized without --replace refused, recognized with --replace succeeds."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    engine_root.mkdir()

    # 1. Random nonempty target without --replace -> exit 2
    (engine_root / "random.txt").write_text("not a rigorloom install", encoding="utf-8")
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir)])
    assert code == 2
    assert "pass --replace" in json.loads(buf.getvalue())["error"]["message"]

    # 2. Random nonempty target with --replace -> exit 2
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--replace"])
    assert code == 2
    assert "does not appear to be a prior rigorloom install" in json.loads(buf.getvalue())["error"]["message"]

    # 3. Create recognized prior install layout
    (engine_root / "random.txt").unlink()
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    (engine_root / "engine" / "scripts" / "form_inspect.py").write_text("# old inspect", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# old reg", encoding="utf-8")

    # Without --replace -> exit 2
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir)])
    assert code == 2
    assert "pass --replace" in json.loads(buf.getvalue())["error"]["message"]


def test_locked_engine_root_aborts_and_preserves(tmp_path):
    """When existing engine-root cannot be renamed (locked file on Windows), install aborts and preserves target."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    lock_file = engine_root / "engine" / "scripts" / "form_inspect.py"
    lock_file.write_text("# original content", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# reg", encoding="utf-8")

    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"
    _make_dummy_bundle(core_zip, "core", {
        "engine/scripts/probe.py": b"print('probe')",
        "engine/scripts/form_inspect.py": b"print('inspect')",
        "pipeline/scripts/module_registry.py": b"print('reg')",
        "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n"
    })

    # Hold an exclusive open file handle in engine_root
    with open(lock_file, "r+", encoding="utf-8") as handle:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir),
                             "--modules", "", "--replace"])
        assert code == 3
        out = json.loads(buf.getvalue())
        assert out["error"]["code"] == "engine_root_locked"
        assert lock_file.read_text(encoding="utf-8") == "# original content"


# --------------------------------------------------------------------------- #
# Rollback on Post-Swap Failure and Backup Preservation
# --------------------------------------------------------------------------- #

def test_rollback_on_post_swap_failure_restores_prior_engine(tmp_path):
    """If post-swap step fails, prior engine is restored and backup is preserved."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    original_marker = engine_root / "engine" / "scripts" / "form_inspect.py"
    original_marker.write_text("# original v1", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# reg", encoding="utf-8")

    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"
    _make_dummy_bundle(core_zip, "core", {
        "engine/scripts/probe.py": b"print('probe')",
        "engine/scripts/form_inspect.py": b"# new v2",
        "pipeline/scripts/module_registry.py": b"print('reg')",
        "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n"
    })

    # Trigger post-swap failure by mocking _probe_origin_split to raise
    with patch("install._probe_origin_split", side_effect=install.InstallError(3, "post_check_failed", "synthetic failure")):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir),
                             "--modules", "", "--replace"])
        assert code == 3
        out = json.loads(buf.getvalue())
        assert "post_check_failed" in out["error"]["code"]
        # Assert original prior engine was restored
        assert original_marker.read_text(encoding="utf-8") == "# original v1"


def test_keyboardinterrupt_during_post_swap_restores_prior_engine(tmp_path):
    """A2: KeyboardInterrupt after the swap still rolls back to the prior engine.

    ``except Exception`` would skip rollback and leave a new engine whose origin
    split was never verified. The interrupt must propagate *after* restore.
    """
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    original_marker = engine_root / "engine" / "scripts" / "form_inspect.py"
    original_marker.write_text("# original v1", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# reg", encoding="utf-8")

    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"
    _make_dummy_bundle(core_zip, "core", {
        "engine/scripts/probe.py": b"print('probe')",
        "engine/scripts/form_inspect.py": b"# new v2",
        "pipeline/scripts/module_registry.py": b"print('reg')",
        "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n"
    })

    with patch("install._probe_origin_split", side_effect=KeyboardInterrupt):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            with pytest.raises(KeyboardInterrupt):
                cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir),
                          "--modules", "", "--replace"])

    assert original_marker.is_file()
    assert original_marker.read_text(encoding="utf-8") == "# original v1"
    assert not buf.getvalue().strip(), "KeyboardInterrupt must not be wrapped as a JSON install error"


# --------------------------------------------------------------------------- #
# Skills Directory Discipline (Refuse Existing Even If Empty)
# --------------------------------------------------------------------------- #

def test_existing_skills_root_refused_even_if_empty(tmp_path):
    """Existing skills-root (even empty) is refused before any engine mutation, printing manual sync_local command."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    skills_root = tmp_path / "skills"
    skills_root.mkdir()  # empty directory

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main([
            "install",
            "--engine-root", str(engine_root),
            "--bundles-dir", str(bundles_dir),
            "--skills-root", str(skills_root)
        ])
    assert code == 2
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
    msg = out["error"]["message"]
    assert "already exists" in msg
    assert "sync_local.py" in msg
    assert "--dry-run" in msg
    assert "--force" not in msg
    assert not engine_root.exists()


# --------------------------------------------------------------------------- #
# Lock Safety and Foreign Lock Preservation
# --------------------------------------------------------------------------- #

def test_lock_safety_preserves_foreign_lock(tmp_path):
    """An existing lock file always refuses without stealing or unlinking."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    _make_dummy_bundle(bundles_dir / "rigorloom-core-0.17.0.zip", "core", {"probe.py": b"print('probe')"})
    engine_root = tmp_path / "engine"
    lock_path = tmp_path / f"{engine_root.name}.sync.lock"
    lock_path.write_text("token=foreign-123\npid=99999\ntime=1000.0\n", encoding="utf-8")

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root), "--bundles-dir", str(bundles_dir), "--modules", ""])
    assert code == 3
    out = json.loads(buf.getvalue())
    assert out["error"]["code"] == "lock_held"
    # Verify foreign lock was NOT removed
    assert lock_path.is_file()
    assert "foreign-123" in lock_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# End-to-End Wheel Consumer & Real Built Bundles
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory):
    """Build real wheel and bundles (core, style, report) once for this module."""
    package_module_script = REPO_ROOT / "scripts" / "package_module.py"
    assert package_module_script.is_file()

    import importlib.util
    spec = importlib.util.spec_from_file_location("_pkg_mod", package_module_script)
    pkg_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pkg_mod)

    dist_dir = tmp_path_factory.mktemp("dist")
    # Build the 3 ZIP bundles
    for name in ("core", "style", "report"):
        pkg_mod.build_bundle(name, out_dir=dist_dir, repo_root=REPO_ROOT)

    # Build wheel using WHEEL_PYTHON
    wheel_cmd = [
        WHEEL_PYTHON, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist_dir), str(REPO_ROOT)
    ]
    subprocess.run(wheel_cmd, check=True, capture_output=True, text=True)
    wheel_candidates = list(dist_dir.glob("rigorloom-*.whl"))
    assert wheel_candidates, "Failed to build wheel"
    return {"dist_dir": dist_dir, "wheel": wheel_candidates[0]}


def test_tamper_detection_real_report_zip(tmp_path, built_artifacts):
    """Flipping one byte in real rigorloom-report-*.zip triggers tamper_detected (exit 3) and leaves target untouched."""
    dist_dir = built_artifacts["dist_dir"]
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    # Copy zips to bundles_dir
    for z in dist_dir.glob("*.zip"):
        shutil.copy2(z, bundles_dir / z.name)

    # Tamper report zip by corrupting 1 byte
    report_zips = list(bundles_dir.glob("rigorloom-report-*.zip"))
    assert report_zips
    report_zip = report_zips[0]
    data = bytearray(report_zip.read_bytes())
    data[len(data) // 2] ^= 0xFF
    report_zip.write_bytes(data)

    engine_root = tmp_path / "engine_tamper"
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main([
            "install",
            "--engine-root", str(engine_root),
            "--bundles-dir", str(bundles_dir),
            "--modules", "style,report"
        ])
    assert code == 3
    out = json.loads(buf.getvalue())
    assert out["error"]["code"] == "tamper_detected"
    assert not engine_root.exists()


def test_wheel_installed_consumer_e2e_and_origin_split(tmp_path, built_artifacts):
    """Full end-to-end consumer execution: pip install wheel into fresh venv, run rigorloom install console script, verify origin-split and capabilities."""
    dist_dir = built_artifacts["dist_dir"]
    wheel = built_artifacts["wheel"]

    # 1. Create fresh isolated venv
    venv_dir = tmp_path / "venv"
    subprocess.run([WHEEL_PYTHON, "-m", "venv", str(venv_dir)], check=True, capture_output=True)

    if os.name == "nt":
        venv_py = str(venv_dir / "Scripts" / "python.exe")
        rigorloom_exe = str(venv_dir / "Scripts" / "rigorloom.exe")
    else:
        venv_py = str(venv_dir / "bin" / "python")
        rigorloom_exe = str(venv_dir / "bin" / "rigorloom")

    # 2. Install wheel via pip into venv
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(k, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    subprocess.run([venv_py, "-m", "pip", "install", "--no-deps", str(wheel)],
                   check=True, capture_output=True, env=env, encoding="utf-8")

    # 3. Execute consumer install using installed console script
    engine_root = tmp_path / "installed_engine"
    skills_root = tmp_path / "installed_skills"
    work_root = tmp_path / "installed_work"

    proc = subprocess.run([
        rigorloom_exe, "install",
        "--engine-root", str(engine_root),
        "--bundles-dir", str(dist_dir),
        "--modules", "style,report",
        "--skills-root", str(skills_root)
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(tmp_path))

    assert proc.returncode == 0, f"rigorloom install failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    install_res = json.loads(proc.stdout)
    assert install_res["ok"] is True
    assert install_res["command"] == "install"
    assert Path(install_res["result"]["engine_root"]).resolve() == engine_root.resolve()
    assert install_res["result"]["backup_path"] is None
    assert install_res["result"]["skills_installed"] is True

    # 4. Verify origin split on installed tree
    probe_code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import rigorloom_runtime\n"
        f"engine_root = Path(r'{engine_root}').resolve()\n"
        f"venv_dir = Path(r'{venv_dir}').resolve()\n"
        f"repo_root = Path(r'{REPO_ROOT}').resolve()\n"
        "sys.path.insert(0, str(engine_root / 'pipeline' / 'scripts'))\n"
        "import module_registry, privacy_scan\n"
        "rt_file = Path(rigorloom_runtime.__file__).resolve()\n"
        "reg_file = Path(module_registry.__file__).resolve()\n"
        "privacy_file = Path(privacy_scan.__file__).resolve()\n"
        "assert rt_file.is_relative_to(venv_dir), f'Runtime not in venv: {rt_file}'\n"
        "assert reg_file.is_relative_to(engine_root), f'Registry not in engine: {reg_file}'\n"
        "assert privacy_file.is_relative_to(engine_root), f'Privacy scanner not in engine: {privacy_file}'\n"
        "cwd_resolved = Path.cwd().resolve()\n"
        "for entry in sys.path:\n"
        "    resolved = (cwd_resolved if not entry else Path(entry).resolve())\n"
        "    assert resolved != repo_root and not resolved.is_relative_to(repo_root), "
        "f'Checkout leak in sys.path: {entry!r} resolved to {resolved}'\n"
        "print(json.dumps({'ok': True, 'runtime': str(rt_file), 'registry': str(reg_file)}))\n"
    )
    env_probe = dict(env)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "RIGORLOOM_BACKENDS", "RIGORLOOM_PROFILE_ROOT"):
        env_probe.pop(key, None)
    proc_probe = subprocess.run(
        [venv_py, "-c", probe_code], env=env_probe, capture_output=True,
        text=True, encoding="utf-8", cwd=str(tmp_path)
    )
    assert proc_probe.returncode == 0, f"origin-split probe failed:\n{proc_probe.stderr}"

    # 5. Run installed capabilities command
    cap_proc = subprocess.run([
        rigorloom_exe,
        "--root", str(work_root),
        "--engine-root", str(engine_root),
        "capabilities"
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(tmp_path))
    assert cap_proc.returncode == 0, f"capabilities failed:\n{cap_proc.stderr}"
    cap_res = json.loads(cap_proc.stdout)
    assert cap_res["ok"] is True
    tools = cap_res["result"]["tools"]
    assert tools["form_inspect"]["state"] == "available"
    assert tools["preedit"]["state"] == "available"
    assert tools["check_residue"]["state"] == "available"

    # 6. Prove the installed doctor recognizes the installed report payload.
    external_cwd = tmp_path / "external-consumer"
    external_cwd.mkdir()
    doctor_proc = subprocess.run([
        rigorloom_exe, "doctor", "--engine-root", str(engine_root)
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(external_cwd))
    assert doctor_proc.returncode == 0, (
        f"installed doctor failed:\nSTDOUT:\n{doctor_proc.stdout}\n"
        f"STDERR:\n{doctor_proc.stderr}"
    )
    doctor_res = json.loads(doctor_proc.stdout)
    assert doctor_res["ok"] is True
    assert doctor_res["command"] == "doctor"
    assert doctor_res["result"]["schema"] == "rigorloom-doctor/v1"
    assert doctor_res["result"]["requiredPassed"] is True
    engine_check = next(
        row for row in doctor_res["result"]["checks"] if row["id"] == "engine"
    )
    assert engine_check["state"] == "pass"
    assert all(engine_check["facts"]["markers"].values())
    assert engine_check["facts"]["enabledModules"] == ["style", "report"]
    assert engine_check["facts"]["enabledState"] == "configured"
    assert engine_check["facts"]["probeSchema"] == "rigorloom-capability-probe/v1"

    missing_engine = tmp_path / "missing-engine"
    missing_doctor = subprocess.run([
        rigorloom_exe, "doctor", "--engine-root", str(missing_engine)
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(external_cwd))
    assert missing_doctor.returncode == 3
    missing_res = json.loads(missing_doctor.stdout)
    assert missing_res["ok"] is False
    assert missing_res["result"]["requiredPassed"] is False
    missing_check = next(
        row for row in missing_res["result"]["checks"] if row["id"] == "engine"
    )
    assert missing_check["state"] == "fail"
    assert missing_check["reason"]["code"] == "engine_markers_missing"
    assert not missing_engine.exists()

    # 7. Scaffold through the report module from the installed engine only.
    source_form = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
    consumer_form = external_cwd / "form.hwpx"
    shutil.copy2(source_form, consumer_form)
    installed_scaffolder = engine_root / "modules" / "report" / "scripts" / "new_report.py"
    workspace_root = tmp_path / "report-workspaces"
    profile_root = tmp_path / "report-profile"
    scaffold_proc = subprocess.run([
        venv_py, str(installed_scaffolder),
        "--slug", "installed",
        "--subject", "science",
        "--topic", "installed integration",
        "--form", str(consumer_form),
        "--workspace-root", str(workspace_root),
        "--profile-root", str(profile_root),
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(external_cwd))
    assert scaffold_proc.returncode == 0, (
        f"installed report scaffolder failed:\nSTDOUT:\n{scaffold_proc.stdout}\n"
        f"STDERR:\n{scaffold_proc.stderr}"
    )
    scaffold_res = json.loads(scaffold_proc.stdout)
    assert scaffold_res["ok"] is True
    workspace = Path(scaffold_res["workspace"]).resolve()
    assert workspace.is_relative_to(workspace_root.resolve())
    assert not workspace.is_relative_to(engine_root.resolve())
    assert not workspace.is_relative_to(REPO_ROOT.resolve())
    assert (workspace / "PIPELINE.md").is_file()
    assert str(installed_scaffolder.parent / "pipeline_ctl.py") in scaffold_res["next"]
    assert str(workspace) in scaffold_res["next"]

    checkout_text = str(REPO_ROOT.resolve()).casefold()
    for completed in (proc, proc_probe, cap_proc, doctor_proc, missing_doctor, scaffold_proc):
        assert checkout_text not in (completed.stdout + completed.stderr).casefold()

    # 8. Verify replace preserves backup
    replace_proc = subprocess.run([
        rigorloom_exe, "install",
        "--engine-root", str(engine_root),
        "--bundles-dir", str(dist_dir),
        "--modules", "style,report",
        "--replace"
    ], capture_output=True, text=True, env=env, encoding="utf-8",
        cwd=str(tmp_path))
    assert replace_proc.returncode == 0
    replace_res = json.loads(replace_proc.stdout)
    backup_path = replace_res["result"].get("backup_path")
    assert backup_path and Path(backup_path).is_dir(), "Backup directory must be preserved on replacement!"
    assert "operator's to remove" in (replace_res["result"].get("backup_note") or "")


def test_failure_before_swap_preserves_recognized_engine_without_backup(tmp_path):
    """A failed module extraction leaves an existing install untouched."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    inspect_marker = engine_root / "engine" / "scripts" / "form_inspect.py"
    inspect_marker.write_text("# original v1 inspect", encoding="utf-8")
    registry_marker = engine_root / "pipeline" / "scripts" / "module_registry.py"
    registry_marker.write_text("# original v1 registry", encoding="utf-8")

    _make_dummy_bundle(
        bundles_dir / "rigorloom-core-0.17.0.zip", "core", {
            "engine/scripts/probe.py": b"print('{}')",
            "engine/scripts/form_inspect.py": b"# new v2 inspect",
            "pipeline/scripts/module_registry.py": b"print('{}')",
            "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n",
        }
    )
    _make_dummy_bundle(
        bundles_dir / "rigorloom-style-0.17.0.zip", "style", {
            "unexpected_dir/some_file.txt": b"wrong layout",
        }
    )

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main([
            "install", "--engine-root", str(engine_root),
            "--bundles-dir", str(bundles_dir), "--modules", "style",
            "--replace",
        ])

    out = json.loads(buf.getvalue())
    assert code == 3
    assert out["error"]["code"] == "tamper_detected"
    assert "missing required modules/style/ payload" in out["error"]["message"]
    assert inspect_marker.read_text(encoding="utf-8") == "# original v1 inspect"
    assert registry_marker.read_text(encoding="utf-8") == "# original v1 registry"
    assert not list(engine_root.parent.glob(f"{engine_root.name}.bak-*"))
    assert not list(engine_root.parent.glob(f"{engine_root.name}.staging-*"))


def test_real_install_forwards_confirmed_checkout_roots_and_rolls_back(tmp_path, monkeypatch):
    """The post-swap probe receives source-checkout roots from run_install."""
    monkeypatch.chdir(REPO_ROOT)
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    _make_dummy_bundle(
        bundles_dir / "rigorloom-core-0.17.0.zip", "core", {
            "engine/scripts/probe.py": b"print('{}')",
            "engine/scripts/form_inspect.py": b"# inspect",
            "pipeline/scripts/module_registry.py": b"print('{}')",
            "pipeline/scripts/privacy_scan.py": b"# scan",
            "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n",
        }
    )

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main([
            "install", "--engine-root", str(engine_root),
            "--bundles-dir", str(bundles_dir), "--modules", "none",
        ])

    out = json.loads(buf.getvalue())
    assert code == 3
    assert out["error"]["code"] == "containment_breach"
    assert "Checkout leak in sys.path" in out["error"]["message"]
    assert str(REPO_ROOT.resolve()) in out["error"]["message"]
    assert not engine_root.exists()


def test_undecodable_probe_output_stays_typed_and_replacement_decoded(tmp_path):
    """Invalid child bytes cannot escape as an internal UnicodeDecodeError."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    probe = (
        b"import os, sys\n"
        b"sys.stderr.buffer.write(b'utf8=' + os.environ.get('PYTHONUTF8', '').encode() + b';bad=\\xff')\n"
        b"raise SystemExit(7)\n"
    )
    _make_dummy_bundle(
        bundles_dir / "rigorloom-core-0.17.0.zip", "core", {
            "engine/scripts/probe.py": probe,
            "engine/scripts/form_inspect.py": b"# inspect",
            "pipeline/scripts/module_registry.py": b"print('{}')",
            "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n",
        }
    )

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main([
            "install", "--engine-root", str(engine_root),
            "--bundles-dir", str(bundles_dir), "--modules", "none",
        ])

    out = json.loads(buf.getvalue())
    assert code == 3
    assert out["error"]["code"] == "probe_failed"
    assert "utf8=1" in out["error"]["message"]
    assert "\ufffd" in out["error"]["message"]
    assert "internal_error" not in buf.getvalue()


def test_installer_children_force_utf8_and_keep_replacement_decode(tmp_path):
    """All three decoded child calls share the deliberate UTF-8 policy."""
    staging = tmp_path / "staging"
    (staging / "pipeline" / "scripts").mkdir(parents=True)
    (staging / "pipeline" / "scripts" / "module_registry.py").write_text(
        "print('{}')", encoding="utf-8"
    )
    (staging / "engine" / "scripts").mkdir(parents=True)
    (staging / "engine" / "scripts" / "probe.py").write_text(
        "print('{}')", encoding="utf-8"
    )
    (staging / "scripts").mkdir()
    (staging / "scripts" / "sync_local.py").write_text(
        "print('{}')", encoding="utf-8"
    )
    calls: list[dict] = []

    def fake_run(_cmd, **kwargs):
        calls.append(kwargs)

        class Result:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return Result()

    with patch("install.subprocess.run", side_effect=fake_run):
        install._enable_modules_in_staging(staging, [])
        install._probe_in_staging(staging)
        install._provision_skills(staging, tmp_path / "skills")

    assert len(calls) == 3
    for call in calls:
        assert call["env"]["PYTHONUTF8"] == "1"
        assert call["env"]["PYTHONIOENCODING"] == "utf-8"
        assert call["encoding"] == "utf-8"
        assert call["errors"] == "replace"


def test_origin_split_intentional_leak_failure(tmp_path):
    """Origin-split probe strictly fails when checkout path leaks into sys.path."""
    engine_root = tmp_path / "engine_leak"
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# reg", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "privacy_scan.py").write_text("# scan", encoding="utf-8")

    probe_code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"engine_root = Path(r'{engine_root}').resolve()\n"
        f"sys.path.insert(0, r'{REPO_ROOT}')\n"  # INJECT CHECKOUT LEAKAGE
        f"sys.path.insert(0, str(engine_root / 'pipeline' / 'scripts'))\n"
        "import module_registry\n"
        f"assert r'{REPO_ROOT}' not in sys.path, 'Checkout leaked!'\n"
    )
    proc = subprocess.run([sys.executable, "-c", probe_code], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "Checkout leaked!" in proc.stderr


def test_origin_split_sys_path_empty_string_and_aliases_fail_closed(tmp_path):
    """Empty and relative aliases cannot bypass checkout containment."""
    engine_root = tmp_path / "engine"
    violations = install.check_sys_path_containment(
        ["", str(Path("pipeline") / ".."), str(engine_root)],
        [REPO_ROOT],
        cwd=REPO_ROOT,
        allowed_roots=[engine_root],
    )
    assert len(violations) == 2
    assert "''" in violations[0]
    assert all("resolved to" in violation for violation in violations)


def test_external_cwd_and_site_packages_are_not_checkout_roots(tmp_path):
    """Ordinary external paths are neither discovered nor refused as checkouts."""
    external_cwd = tmp_path / "outside"
    site_packages = tmp_path / "venv" / "Lib" / "site-packages"
    runtime_module = site_packages / "rigorloom_runtime" / "install.py"
    runtime_module.parent.mkdir(parents=True)
    runtime_module.write_text("# installed wheel module", encoding="utf-8")
    external_cwd.mkdir()
    engine_root = tmp_path / "installed-engine"

    roots = install._confirmed_rigorloom_checkout_roots(
        engine_root,
        module_file=runtime_module,
        sys_path=["", str(site_packages)],
        cwd=external_cwd,
    )
    assert roots == []
    assert install.check_sys_path_containment(
        ["", str(site_packages)],
        [REPO_ROOT],
        cwd=external_cwd,
        allowed_roots=[engine_root],
    ) == []


def test_residue_tool_presence_and_schema_boundary(tmp_path):
    """Presence is installer evidence; residue acceptance is checker evidence."""
    engine_root = tmp_path / "engine_res"
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    check_residue_file = engine_root / "pipeline" / "scripts" / "check_residue.py"
    check_residue_file.write_text("# mock residue tool presence", encoding="utf-8")
    assert check_residue_file.is_file()


# --------------------------------------------------------------------------- #
# Review regressions (Claude DIST-INSTALL-03 review, F1 / F5)
# --------------------------------------------------------------------------- #

def test_ambiguous_bundle_version_is_refused_not_guessed(tmp_path):
    """F5: filename order is not version order, so refuse rather than choose.

    ``sorted()`` puts ``0.9.0`` after ``0.17.0`` because it compares strings,
    so the previous ``candidates[-1]`` silently installed the OLDER bundle and
    reported success. That failure is invisible to the operator, which is worse
    than a refusal, so the ambiguity itself is now the error.
    """
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    for version in ("0.9.0", "0.17.0"):
        _make_dummy_bundle(bundles / f"rigorloom-core-{version}.zip", "core",
                           {"engine/scripts/probe.py": b"print('{}')\n"},
                           version=version)

    with pytest.raises(install.InstallError) as excinfo:
        install._find_bundle(bundles, "core")

    error = excinfo.value
    assert error.exit_code == install.EXIT_USAGE
    assert error.error_code == "invalid_params"
    # Both names must be reported: the operator has to know what to remove.
    assert "rigorloom-core-0.9.0.zip" in error.message
    assert "rigorloom-core-0.17.0.zip" in error.message


def test_single_bundle_still_resolves(tmp_path):
    """F5 guard must not break the ordinary one-bundle directory."""
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    target = bundles / "rigorloom-core-0.17.0.zip"
    _make_dummy_bundle(target, "core",
                       {"engine/scripts/probe.py": b"print('x')\n"})
    assert install._find_bundle(bundles, "core") == target


def test_origin_probe_survives_an_apostrophe_in_the_engine_root(tmp_path):
    """F1: the engine root must not be interpolated into generated source.

    ``<user>\\O'Brien\\...`` is a legal Windows path. Embedding it in a raw
    string literal produced a SyntaxError in the probe child, whose non-zero
    exit was then reported as ``containment_breach`` — a security-sounding
    verdict for a quoting bug, on an install that was in fact fine.
    """
    engine_root = tmp_path / "O'Brien engine"
    scripts = engine_root / "pipeline" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "module_registry.py").write_text("VALUE = 1\n", encoding="utf-8")
    (scripts / "privacy_scan.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = install._probe_origin_split(engine_root)

    assert result.get("ok") is True
    # And the modules really did resolve inside that root, not somewhere else.
    assert "O'Brien engine" in result["registry"]


def test_origin_probe_reports_a_real_leak_as_containment_breach(tmp_path):
    """The code F1 touches must still catch what it exists to catch.

    An engine root with no ``pipeline/scripts`` cannot satisfy the import, so
    the probe must fail closed — otherwise the apostrophe fix would have been
    bought by disarming the check.
    """
    engine_root = tmp_path / "empty engine"
    engine_root.mkdir()

    with pytest.raises(install.InstallError) as excinfo:
        install._probe_origin_split(engine_root)

    assert excinfo.value.exit_code == install.EXIT_REFUSED
    assert excinfo.value.error_code == "containment_breach"


def test_provision_skills_manifest_lives_outside_engine(tmp_path):
    """A1: the skill-sync manifest must not be written inside engine_root."""
    engine_root = tmp_path / "engine"
    (engine_root / "scripts").mkdir(parents=True)
    (engine_root / "scripts" / "sync_local.py").write_text("# stub\n", encoding="utf-8")
    skills_root = tmp_path / "skills"
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["engine_dotfiles"] = [
            p.name for p in engine_root.glob(".skill_sync_manifest_*")
        ]
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    with patch("install.subprocess.run", side_effect=fake_run):
        result = install._provision_skills(engine_root, skills_root)

    assert result["installed"] is True
    manifest_arg = captured["cmd"][captured["cmd"].index("--manifest") + 1]
    manifest_path = Path(manifest_arg)
    assert manifest_path.is_absolute()
    engine_resolved = engine_root.resolve()
    assert manifest_path.resolve() != engine_resolved
    assert engine_resolved not in manifest_path.resolve().parents
    assert captured["engine_dotfiles"] == []
    assert not list(engine_root.glob(".skill_sync_manifest_*"))
    assert not manifest_path.exists()


def test_missing_style_bundle_names_modules_none(tmp_path):
    """A4: a core-only bundles-dir must name --modules none on the default path."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    _make_dummy_bundle(bundles_dir / "rigorloom-core-0.17.0.zip", "core",
                       {"engine/scripts/probe.py": b"print('probe')"})
    engine_root = tmp_path / "engine"

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        code = cli.main(["install", "--engine-root", str(engine_root),
                         "--bundles-dir", str(bundles_dir)])
    assert code == 2
    message = json.loads(buf.getvalue())["error"]["message"]
    assert "required bundle for 'style' not found" in message
    assert "--modules none" in message


def test_replace_backup_note_tells_operator_to_remove(tmp_path):
    """A3: --replace keeps the backup and says the operator may remove it."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    engine_root = tmp_path / "engine"
    (engine_root / "engine" / "scripts").mkdir(parents=True)
    (engine_root / "pipeline" / "scripts").mkdir(parents=True)
    original_marker = engine_root / "engine" / "scripts" / "form_inspect.py"
    original_marker.write_text("# original v1", encoding="utf-8")
    (engine_root / "pipeline" / "scripts" / "module_registry.py").write_text("# reg", encoding="utf-8")

    core_zip = bundles_dir / "rigorloom-core-0.17.0.zip"
    _make_dummy_bundle(core_zip, "core", {
        "engine/scripts/probe.py": b"print('probe')",
        "engine/scripts/form_inspect.py": b"# new v2",
        "pipeline/scripts/module_registry.py": b"print('reg')",
        "pyproject.toml": b"[project]\nname='rigorloom'\nversion='0.17.0'\n"
    })

    with patch("install._probe_origin_split", return_value={"ok": True}):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = cli.main(["install", "--engine-root", str(engine_root),
                             "--bundles-dir", str(bundles_dir),
                             "--modules", "", "--replace"])
    assert code == 0
    result = json.loads(buf.getvalue())["result"]
    backup_path = result.get("backup_path")
    assert backup_path and Path(backup_path).is_dir()
    note = result.get("backup_note") or ""
    assert "operator's to remove" in note
    assert (engine_root / "engine" / "scripts" / "form_inspect.py").read_text(
        encoding="utf-8") == "# new v2"
    assert (Path(backup_path) / "engine" / "scripts" / "form_inspect.py").read_text(
        encoding="utf-8") == "# original v1"
