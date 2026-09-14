#!/usr/bin/env python3
"""Checkout convenience shim for the report module's new-report command."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"


def _module_cli_script(command: str) -> Path:
    if str(PIPELINE_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(PIPELINE_SCRIPTS))
    from module_registry import ModuleError, ModuleRegistry
    try:
        rows = ModuleRegistry().enabled_cli()
    except ModuleError as exc:
        raise RuntimeError(str(exc)) from exc
    for row in rows:
        if row["command"] == command:
            return Path(row["script"]).resolve()
    raise RuntimeError(
        "the report pipeline requires the report distribution module — enable "
        "it in modules/enabled.yaml (python pipeline/scripts/module_registry.py "
        "write-enabled --all)"
    )


def _has_option(argv: list[str], name: str) -> bool:
    return any(token == name or token.startswith(name + "=") for token in argv)


def _default_workspace_root() -> Path:
    workspace = (Path.home() / ".rigorloom" / "workspaces").resolve()
    repo = REPO_ROOT.resolve()
    if workspace == repo or repo in workspace.parents:
        raise RuntimeError(
            f"default workspace root {workspace} must remain outside checkout {repo}"
        )
    return workspace


def _default_profile_root() -> Path:
    profile = (Path.home() / ".rigorloom" / "personalization").resolve()
    repo = REPO_ROOT.resolve()
    if profile == repo or repo in profile.parents:
        raise RuntimeError(
            f"default profile root {profile} must remain outside checkout {repo}"
        )
    return profile


def main(argv: list[str] | None = None) -> int:
    forwarded = list(sys.argv[1:] if argv is None else argv)
    try:
        script = _module_cli_script("new-report")
        if not _has_option(forwarded, "--workspace-root"):
            forwarded += ["--workspace-root", str(_default_workspace_root())]
        if not _has_option(forwarded, "--profile-root"):
            forwarded += ["--profile-root", str(_default_profile_root())]
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    completed = subprocess.run([sys.executable, str(script), *forwarded])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
