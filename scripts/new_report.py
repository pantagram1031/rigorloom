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
PERSONALIZATION_CTL = REPO_ROOT / "pipeline" / "scripts" / "personalization_ctl.py"
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
DIAGNOSTIC_RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")

MODULE_REQUIRED_MSG = (
    "the report pipeline requires the report distribution module — enable it "
    "in modules/enabled.yaml (python pipeline/scripts/module_registry.py "
    "write-enabled --all)"
)


def _module_cli_script(command: str) -> Path:
    """Resolve a report-module CLI payload path through the distribution-
    module registry (v0.16 W3-S2b: the stage-machine payload lives in
    modules/report/). A disabled/missing module is a clear refusal, never a
    stack trace from a dangling path."""
    core_scripts = REPO_ROOT / "pipeline" / "scripts"
    if str(core_scripts) not in sys.path:
        sys.path.insert(0, str(core_scripts))
    from module_registry import ModuleError, ModuleRegistry
    try:
        rows = ModuleRegistry().enabled_cli()
    except ModuleError as exc:
        raise SystemExit(f"error: {exc}")
    for row in rows:
        if row["command"] == command:
            return Path(row["script"])
    raise SystemExit(f"error: {MODULE_REQUIRED_MSG}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Rigorloom report workspace")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--form", required=True)
    parser.add_argument(
        "--ingress-receipt",
        help=("required when claiming that --form was canonically converted "
              "from binary HWP; validates exact schema and output hash"),
    )
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


def _is_quarantined_diagnostic_candidate(form: Path) -> bool:
    """Recognize schema-owned diagnostic layouts without opening receipts."""
    try:
        path = form.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return (
        path.name == "candidate.hwpx"
        and DIAGNOSTIC_RUN_ID_RE.fullmatch(path.parent.name) is not None
        and path.parent.parent.name.casefold()
        in {"hwp-diagnostic", "hwp-java-diagnostic", "hwp-semantic-oracle"}
    )


def _verify_ingress_claim(form: Path, receipt: Path) -> None:
    scripts = REPO_ROOT / "pipeline" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from hwp_ingress import verify_receipt
        verify_receipt(form, receipt)
    except Exception as exc:
        raise ValueError("ingress receipt is invalid or stale") from exc


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
    if _is_quarantined_diagnostic_candidate(form):
        print("error: diagnostic candidate is quarantined and cannot enter a report workspace",
              file=sys.stderr)
        return 3
    if form.suffix.casefold() == ".hwp":
        print(
            "error: binary .hwp must pass pipeline/scripts/hwp_ingress.py "
            "convert --adapter hancom before workspace creation; provide the "
            "published .hwpx and retain its ingress receipt",
            file=sys.stderr,
        )
        return 3
    ingress_receipt = None
    if args.ingress_receipt:
        ingress_receipt = Path(args.ingress_receipt).expanduser().resolve()
        if form.suffix.casefold() != ".hwpx" or not ingress_receipt.is_file():
            print("error: ingress receipt is invalid or stale", file=sys.stderr)
            return 3
        try:
            _verify_ingress_claim(form, ingress_receipt)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
    if final.exists():
        print(f"error: workspace already exists: {final}", file=sys.stderr)
        return 1
    # Registry lookup (v0.16 W3-S2b): the stage machine is report-module
    # payload; a disabled module is a clear refusal before anything is staged.
    pipeline_ctl = _module_cli_script("pipeline")

    workspace_root.mkdir(parents=True, exist_ok=True)
    staging = workspace_root / f".creating-{args.slug}-{uuid.uuid4().hex[:8]}"
    try:
        for relative in ("bundle/figures", "research", "sim", "figures", "output", "refs", "archive"):
            (staging / relative).mkdir(parents=True, exist_ok=True)
        pipeline_form = form
        personalization_form = form
        if ingress_receipt is not None:
            staged_form = staging / "output" / "form_copy.hwpx"
            try:
                shutil.copyfile(form, staged_form)
                receipt_copy = staging / "output" / "proof" / "ingress" / "receipt.json"
                receipt_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ingress_receipt, receipt_copy)
                _verify_ingress_claim(staged_form, receipt_copy)
            except (OSError, ValueError):
                print("error: ingress receipt is invalid after workspace copy",
                      file=sys.stderr)
                return 3
            pipeline_form = final / "output" / "form_copy.hwpx"
            personalization_form = staged_form
        (staging / "request.yaml").write_text(
            _request_text(args, pipeline_form), encoding="utf-8")
        (staging / "build.yaml").write_text(_build_text(args), encoding="utf-8")
        (staging / "APPROVALS.md").write_text(_approvals_text(), encoding="utf-8")

        command = [
            sys.executable, str(pipeline_ctl), "init", str(staging),
            "--slug", f"report-{args.slug}", "--mode", args.mode,
            "--subject", args.subject, "--topic", args.topic,
            "--form", str(pipeline_form),
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
        profile_root = args.profile_root or str(REPO_ROOT / ".local" / "personalization")
        personal = subprocess.run([
                sys.executable, str(PERSONALIZATION_CTL), "--profile-root", profile_root, "resolve",
                "--workspace", str(staging), "--form", str(personalization_form),
                "--subject", args.subject,
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
        [sys.executable, str(_module_cli_script("organize-workspace")),
         str(final), "--no-archive"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "workspace": str(final),
        "next": f'python modules/report/scripts/pipeline_ctl.py resume "{final}"',
    }, ensure_ascii=False))
    return 0



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; output may contain
    non-ASCII. Reconfigure stdio so printing never dies with UnicodeEncodeError
    (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
