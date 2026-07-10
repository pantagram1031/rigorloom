#!/usr/bin/env python3
"""Create an initialized report workspace atomically."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_CTL = REPO_ROOT / "pipeline" / "scripts" / "pipeline_ctl.py"
PERSONALIZATION_CTL = REPO_ROOT / "pipeline" / "scripts" / "personalization_ctl.py"
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Rigorloom report workspace")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--form", required=True)
    parser.add_argument("--mode", choices=["supervised", "autonomous", "night"], default="supervised")
    parser.add_argument("--pages", nargs=2, type=int, metavar=("MIN", "MAX"), default=[5, 12])
    parser.add_argument("--min-figures", type=int, default=4)
    parser.add_argument("--workspace-root", default=str(REPO_ROOT / "workspaces"))
    parser.add_argument("--profile-root", help="Private personalization store (defaults to .local/personalization)")
    return parser.parse_args()


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _request_text(args: argparse.Namespace, form: Path) -> str:
    return f"""# Report job ticket
topic: {_yaml_string(args.topic)}
subject: {_yaml_string(args.subject)}
form: {_yaml_string(str(form))}
mode: {args.mode}
output_filename: "TBD"
length: standard-plus
constraints:
  pages: [{args.pages[0]}, {args.pages[1]}]
  min_figures: {args.min_figures}
  scope: "TBD"
  must_include: []
  avoid: []
  style: "Clear evidence-backed report prose"
notes: "TBD"
"""


def _build_text(args: argparse.Namespace) -> str:
    return f"""# Build declaration; update from form inspection and approved design.
base_pt: 10
caption_pt: 9
line_spacing: 160
binding: submit
abstract: false
title: "TBD"
fill:
  min_figures: {args.min_figures}
  target_pages: [{args.pages[0]}, {args.pages[1]}]
  bottom_white_max: 25
  max_gap_lines: 4
allow_colors: []
delete_texts: []
page_break_before: []
"""


def _approvals_text() -> str:
    return """# Human approvals

Only a human operator may add supervised approval or rejection lines:

`<gate>: approved by=<name> at=<ISO-8601>`
`<gate>: rejected <reason>`
"""


def _assert_safe_workspace(root: Path, slug: str) -> Path:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("slug must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    root = root.resolve()
    workspace = (root / f"report-{slug}").resolve()
    if root not in workspace.parents:
        raise ValueError("workspace resolved outside workspace root")
    return workspace


def main() -> int:
    args = parse_args()
    if args.pages[0] < 1 or args.pages[0] > args.pages[1]:
        print("error: --pages must be positive and MIN <= MAX", file=sys.stderr)
        return 2
    if args.min_figures < 0:
        print("error: --min-figures must be non-negative", file=sys.stderr)
        return 2
    try:
        workspace_root = Path(args.workspace_root).resolve()
        final = _assert_safe_workspace(workspace_root, args.slug)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    form = Path(args.form).expanduser().resolve()
    if not form.is_file():
        print(f"error: form does not exist: {form}", file=sys.stderr)
        return 2
    if final.exists():
        print(f"error: workspace already exists: {final}", file=sys.stderr)
        return 1
    if not PIPELINE_CTL.is_file():
        print(f"error: pipeline kernel missing: {PIPELINE_CTL}", file=sys.stderr)
        return 1

    workspace_root.mkdir(parents=True, exist_ok=True)
    staging = workspace_root / f".creating-{args.slug}-{uuid.uuid4().hex[:8]}"
    try:
        for relative in ("bundle/figures", "research", "sim", "figures", "output", "refs", "archive"):
            (staging / relative).mkdir(parents=True, exist_ok=True)
        (staging / "request.yaml").write_text(_request_text(args, form), encoding="utf-8")
        (staging / "build.yaml").write_text(_build_text(args), encoding="utf-8")
        (staging / "APPROVALS.md").write_text(_approvals_text(), encoding="utf-8")

        command = [
            sys.executable, str(PIPELINE_CTL), "init", str(staging),
            "--slug", f"report-{args.slug}", "--mode", args.mode,
            "--subject", args.subject, "--topic", args.topic, "--form", str(form),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
        profile_root = args.profile_root or str(REPO_ROOT / ".local" / "personalization")
        personal = subprocess.run([
                sys.executable, str(PERSONALIZATION_CTL), "--profile-root", profile_root, "resolve",
                "--workspace", str(staging), "--form", str(form), "--subject", args.subject,
                "--request", str(staging / "request.yaml"),
            ], capture_output=True, text=True, encoding="utf-8")
        if personal.returncode != 0:
            print(personal.stderr or personal.stdout, file=sys.stderr)
            return personal.returncode
        staging.replace(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    # The handoff was generated while the workspace had its staging path.
    # Regenerate it after the atomic rename so all paths are final.
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "pipeline" / "scripts" / "workspace_organizer.py"),
         str(final), "--no-archive"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "workspace": str(final),
        "next": f'python pipeline/scripts/pipeline_ctl.py resume "{final}"',
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
