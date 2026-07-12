#!/usr/bin/env python3
"""Clone-and-go bootstrap for Rigorloom.

Verifies the interpreter, creates a neutral private personalization profile,
registers the public default preference packs, and (unless --skip-smoke) proves
the pipeline runs end to end on a synthetic workspace: new_report -> resume ->
a passing script gate resolved via `check`. Standard library only; no network;
re-runnable (idempotent). Exits 0 only when every required step succeeds.

The default roots live under the repo's Git-ignored `.local/` and `workspaces/`.
Pass --profile-root / --workspace-root to redirect everything (tests use temp
dirs so a bootstrap run never touches real personalization or workspaces).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
PIPELINE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"
PERSONALIZATION_CTL = PIPELINE_SCRIPTS / "personalization_ctl.py"
PIPELINE_CTL = PIPELINE_SCRIPTS / "pipeline_ctl.py"
NEW_REPORT = SCRIPTS / "new_report.py"
SETUP_PROFILE = SCRIPTS / "setup_profile.py"
PACK_DEFAULTS = REPO_ROOT / "pipeline" / "references" / "preference_packs" / "defaults"

MIN_PYTHON = (3, 10)
SMOKE_SLUG = "bootstrap-smoke"

# A checker that always passes: stands in for the per-workspace sim harness the
# `sane` script gate binds to (["python", "{WS}/sim/gates.py"]). Emits a minimal
# gate_result and exits 0 so `check` records auto_approved.
FAKE_CHECKER = (
    "import json, sys\n"
    'print(json.dumps({"ok": True, "verdict": "pass", "source": "bootstrap-smoke"}))\n'
    "sys.exit(0)\n"
)


def _py(*args: object) -> list[str]:
    return [sys.executable, *[str(a) for a in args]]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _last_json(text: str) -> dict:
    """Parse the last non-empty stdout line as a JSON object (the CLIs emit one
    JSON object per invocation; setup_profile/new_report emit a single line)."""
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}


class BootstrapError(RuntimeError):
    pass


def check_python() -> str:
    if sys.version_info < MIN_PYTHON:
        raise BootstrapError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info.major}.{sys.version_info.minor}"
        )
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def create_profile(profile_root: Path) -> None:
    """Create the private profile skeleton via setup_profile.py --non-interactive.
    Idempotent: setup_profile / personalization_ctl init only write files that do
    not already exist, and the writing profile is rewritten deterministically."""
    output = profile_root / "user-profile" / "writing_preferences.json"
    proc = _run(_py(SETUP_PROFILE, "--non-interactive",
                    "--profile-root", profile_root, "--output", output))
    if proc.returncode != 0:
        raise BootstrapError(f"setup_profile failed ({proc.returncode}): "
                             f"{(proc.stderr or proc.stdout).strip()}")


def register_packs(profile_root: Path) -> tuple[int, int]:
    """Register every public default pack into the profile. register-pack
    overwrites, so re-runs are safe. Returns (registered, total)."""
    files = sorted(PACK_DEFAULTS.glob("*.json"))
    if not files:
        raise BootstrapError(f"no default packs found under {PACK_DEFAULTS}")
    registered = 0
    for pack in files:
        pack_type = pack.stem
        proc = _run(_py(PERSONALIZATION_CTL, "--profile-root", profile_root,
                        "register-pack", "--type", pack_type, "--file", pack))
        if proc.returncode != 0:
            raise BootstrapError(f"register-pack {pack_type} failed "
                                 f"({proc.returncode}): "
                                 f"{(proc.stderr or proc.stdout).strip()}")
        registered += 1
    return registered, len(files)


def _reset_workspace(workspace_root: Path) -> Path:
    ws = (workspace_root / f"report-{SMOKE_SLUG}").resolve()
    # Only ever remove a demo workspace that resolves directly under the given
    # root — never follow a slug or symlink outside it.
    if ws.exists() and ws.parent == workspace_root.resolve():
        shutil.rmtree(ws)
    return ws


def smoke(profile_root: Path, workspace_root: Path) -> dict:
    """new_report --mode night -> resume -> passing `sane` gate via `check`.
    Returns a step->status map; raises BootstrapError on the first failure."""
    workspace_root.mkdir(parents=True, exist_ok=True)
    ws = _reset_workspace(workspace_root)

    form = workspace_root / "_bootstrap_form.hwpx"
    form.write_bytes(b"bootstrap smoke synthetic form fixture\n")

    steps: dict[str, str] = {}

    proc = _run(_py(NEW_REPORT, "--slug", SMOKE_SLUG, "--subject", "smoke",
                    "--topic", "Does the pipeline run from a clean clone?",
                    "--form", form, "--mode", "night",
                    "--workspace-root", workspace_root,
                    "--profile-root", profile_root))
    created = _last_json(proc.stdout)
    if proc.returncode != 0 or not created.get("ok"):
        raise BootstrapError(f"new_report failed ({proc.returncode}): "
                             f"{(proc.stderr or proc.stdout).strip()}")
    steps["new_report"] = "ok"
    ws = Path(created.get("workspace", ws))
    # Containment guard: never trust the returned path blindly — everything the
    # smoke writes must stay under the caller-provided workspace root.
    ws_real = os.path.realpath(ws)
    root_real = os.path.realpath(workspace_root)
    if os.path.commonpath([root_real, ws_real]) != root_real:
        raise BootstrapError(
            f"new_report returned a workspace outside --workspace-root: {ws}")

    proc = _run(_py(PIPELINE_CTL, "resume", ws))
    resumed = _last_json(proc.stdout)
    if proc.returncode != 0 or not resumed.get("ok"):
        raise BootstrapError(f"resume failed ({proc.returncode}): "
                             f"{(proc.stderr or proc.stdout).strip()}")
    steps["resume"] = f"next_stage={resumed.get('next_stage')!r}"

    # Install the passing checker the `sane` gate will run, then resolve it.
    gates_py = ws / "sim" / "gates.py"
    gates_py.parent.mkdir(parents=True, exist_ok=True)
    gates_py.write_text(FAKE_CHECKER, encoding="utf-8")

    proc = _run(_py(PIPELINE_CTL, "check", ws, "sane"))
    checked = _last_json(proc.stdout)
    if proc.returncode != 0 or checked.get("state") != "auto_approved":
        raise BootstrapError(
            f"check sane did not auto_approve ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}")
    steps["check(sane)"] = f"{checked.get('state')} by={checked.get('by')}"

    steps["_workspace"] = str(ws)
    return steps


def optional_extras() -> list[tuple[str, str, bool, str]]:
    """(name, what it enables, importable now, install hint)."""
    def _has(mod: str) -> bool:
        import importlib.util
        return importlib.util.find_spec(mod) is not None

    return [
        ("docx", "content.md -> styled DOCX deliverable", _has("docx"),
         "pip install .[docx]"),
        ("studio", "local read-only workspace viewer (FastAPI + PyMuPDF)",
         _has("fastapi") and _has("fitz"), "pip install .[studio]"),
        ("hwp", "native .hwp output (Windows + Hancom + hwp-master)", False,
         "see README > HWP/HWPX output requirements"),
    ]


def _print_summary(py_version: str, profile_root: Path, packs: tuple[int, int],
                   smoke_result: dict | None) -> None:
    print("\nRigorloom bootstrap — summary")
    print("=" * 60)
    rows = [
        ("Python", f"{py_version} (>= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"),
        ("Profile root", str(profile_root)),
        ("Default packs", f"{packs[0]}/{packs[1]} registered"),
    ]
    if smoke_result is None:
        rows.append(("Smoke", "skipped (--skip-smoke)"))
    else:
        rows.append(("Smoke: new_report", smoke_result.get("new_report", "?")))
        rows.append(("Smoke: resume", smoke_result.get("resume", "?")))
        rows.append(("Smoke: check(sane)", smoke_result.get("check(sane)", "?")))
        rows.append(("Smoke: workspace", smoke_result.get("_workspace", "?")))
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label.ljust(width)}  {value}")

    print("\nOptional extras (the bundle backend needs none of these):")
    extras = optional_extras()
    name_w = max(len(n) for n, *_ in extras)
    for name, enables, available, hint in extras:
        mark = "available" if available else "not installed"
        print(f"  {name.ljust(name_w)}  [{mark:<13}] {enables}")
        print(f"  {' ' * name_w}  -> {hint}")
    print("=" * 60)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile-root", type=Path,
                        default=REPO_ROOT / ".local" / "personalization",
                        help="Private personalization store (default: .local/personalization)")
    parser.add_argument("--workspace-root", type=Path,
                        default=REPO_ROOT / "workspaces",
                        help="Where the smoke demo workspace is created (default: workspaces/)")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="Only set up the profile + packs; skip the end-to-end run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile_root = args.profile_root.expanduser().resolve()
    workspace_root = args.workspace_root.expanduser().resolve()
    try:
        py_version = check_python()
        create_profile(profile_root)
        packs = register_packs(profile_root)
        smoke_result = None if args.skip_smoke else smoke(profile_root, workspace_root)
    except BootstrapError as exc:
        print(f"bootstrap: FAILED — {exc}", file=sys.stderr)
        return 1
    _print_summary(py_version, profile_root, packs, smoke_result)
    print("bootstrap: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
