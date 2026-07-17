# -*- coding: utf-8 -*-
"""check_layout.py — stage 2.5 layout gate delegate.

The cast-off checker (layout_plan_check.py) ships with the external
hwp-master project, so stages.yaml cannot reference it portably (checker
argv placeholders are limited to {WS}/{PIPELINE_SCRIPTS}). This thin
delegate locates it via the HWP_MASTER_SCRIPTS environment variable —
the same contract doc_backend uses for the hwpx XML engine — runs it on
the workspace's bundle/layout_plan.json + form_profile.json, and passes
the verdict through unchanged.

Exit 0 = plan fits, 3 = plan violates cast-off constraints, 2 = usage
(missing HWP_MASTER_SCRIPTS, missing plan/profile, or delegate crash).
"""
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from checker_base import cli_main, dump_json, usage_error  # noqa: E402


def _locate_delegate():
    root = os.environ.get("HWP_MASTER_SCRIPTS")
    if not root:
        return None, ("HWP_MASTER_SCRIPTS is not set — point it at the "
                      "hwp-master scripts directory containing "
                      "layout_plan_check.py")
    candidate = Path(root).expanduser() / "layout_plan_check.py"
    if not candidate.is_file():
        return None, f"layout_plan_check.py not found under: {root}"
    return candidate, None


def check(ws, plan=None, form_profile=None):
    ws_path = Path(ws)
    plan_path = Path(plan) if plan else ws_path / "bundle" / "layout_plan.json"
    profile_path = (Path(form_profile) if form_profile
                    else ws_path / "form_profile.json")
    if not plan_path.is_file():
        return usage_error(ws, "check_layout",
                             f"layout plan missing: {plan_path}")
    if not profile_path.is_file():
        return usage_error(ws, "check_layout",
                             f"form profile missing: {profile_path}")
    delegate, err = _locate_delegate()
    if err:
        return usage_error(ws, "check_layout", err)

    proc = subprocess.run(
        [sys.executable, str(delegate), str(plan_path),
         "--form-profile", str(profile_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    verdict = {
        "workspace": str(ws),
        "checker": "check_layout",
        "delegate": str(delegate),
        "delegate_exit": proc.returncode,
        "delegate_stdout": (proc.stdout or "")[:4000],
    }
    if proc.returncode == 0:
        verdict.update(ok=True, verdict="pass")
        return verdict, 0
    if proc.stderr:
        verdict["stderr"] = proc.stderr[:800]
    # Nonzero delegate exit = the plan fails cast-off constraints (hard).
    verdict.update(ok=False, verdict="fail")
    return verdict, 3


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="stage 2.5 layout gate delegate")
    ap.add_argument("workspace")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--form-profile", default=None)
    a = ap.parse_args(argv)
    verdict, code = check(a.workspace, plan=a.plan, form_profile=a.form_profile)
    print(dump_json(verdict))
    return code


if __name__ == "__main__":
    sys.exit(cli_main(main))
