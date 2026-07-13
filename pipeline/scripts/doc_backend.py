# -*- coding: utf-8 -*-
"""doc_backend.py — pluggable document-backend dispatcher for Stage 5.

Usage:
    python pipeline/scripts/doc_backend.py <WS> [--backend bundle|docx|hwpx|hwp]
                                                [--out-dir <path>]

Backend resolution (first hit wins):
    1. explicit  --backend  flag
    2. build.yaml `doc_backend:` key (minimal line-scan; <WS>/build.yaml)
    3. default   "bundle"

Backends:
    bundle  zero-dependency deliverable (frozen bundle + stdlib HTML preview).
            Always available. Dispatches to pipeline/adapters_impl/bundle_backend.
    docx    optional python-docx render (`pip install python-docx`).
            Dispatches to pipeline/adapters_impl/docx_backend.
    hwpx    EXTERNAL adapter (hwp-master XML engine, any OS). Resolved through
            HWP_MASTER_SCRIPTS and dispatched to fill_report.py --engine xml.
    hwp     EXTERNAL adapter (hwp-master, Windows + Hancom). Not implemented
            here — prints the pointer instruction and exits 4.

Exit codes:
    0  success
    2  usage / bundle floor missing
    3  unknown backend
    4  requested external adapter unavailable — see printed pointer
    5  docx backend requested but python-docx not installed
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # pipeline/scripts
_PIPELINE_DIR = os.path.dirname(_HERE)                        # pipeline
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from adapters_impl import read_build_yaml_key  # noqa: E402

_HWP_POINTER = (
    "hwp backend is an EXTERNAL adapter (Windows + Hancom + hwp-master).\n"
    "It is not implemented in this repo. Run the hwp-master assembly loop:\n"
    "  python <HWP_MASTER_ROOT>/scripts/fill_report.py --loop \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output \\\n"
    "    --build-yaml <WS>/build.yaml --baseline <WS>/form_baseline.json \\\n"
    "    --form-profile <WS>/form_profile.json --proof --max-proof-iters 3\n"
    "See adapters/hwp/README.md (clone hwp-master beside this repo or set "
    "HWP_MASTER_ROOT)."
)

_HWPX_POINTER = (
    "hwpx backend is an EXTERNAL adapter (hwp-master XML engine; no Hancom/COM).\n"
    "Set HWP_MASTER_SCRIPTS to the hwp-master scripts directory containing\n"
    "fill_report.py, eqn.py, and xml_backend.py, then rerun this command.\n"
    "(All three files must be present — this is a misconfiguration guard, not\n"
    "a security check; HWP_MASTER_SCRIPTS is operator-trusted config.)\n"
    "The dispatcher will invoke:\n"
    "  python <HWP_MASTER_SCRIPTS>/fill_report.py --engine xml \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output"
)

# HWP_MASTER_SCRIPTS is operator-trusted config, not attacker input. This
# marker check just catches misconfiguration (e.g. the env var pointing at
# the wrong directory) — it is not a security boundary.
_HWP_MASTER_MARKERS = ("fill_report.py", "eqn.py", "xml_backend.py")


def _resolve_hwpx_fill_report() -> str | None:
    scripts = os.environ.get("HWP_MASTER_SCRIPTS", "").strip()
    if not scripts:
        return None
    base = os.path.abspath(os.path.expanduser(scripts))
    if not all(os.path.isfile(os.path.join(base, marker))
               for marker in _HWP_MASTER_MARKERS):
        return None
    return os.path.join(base, "fill_report.py")


def _run_hwpx_adapter(ws: str, out_dir: str | None) -> int:
    fill_report = _resolve_hwpx_fill_report()
    if fill_report is None:
        print(_HWPX_POINTER, file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "hwp-master XML adapter unavailable"}))
        return 4

    command = [
        sys.executable, fill_report,
        "--engine", "xml",
        "--form", os.path.join(ws, "output", "form_copy.hwpx"),
        "--content", os.path.join(ws, "bundle", "content.md"),
        "--out-dir", out_dir or os.path.join(ws, "output"),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"failed to launch hwp-master XML adapter: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "failed to launch hwp-master XML adapter"}))
        return 4
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def resolve_backend(ws: str, flag: str | None) -> str:
    if flag:
        return flag
    yaml_val = read_build_yaml_key(os.path.join(ws, "build.yaml"), "doc_backend")
    if yaml_val:
        return yaml_val
    return "bundle"


def main(argv=None):
    ap = argparse.ArgumentParser(description="pluggable document-backend dispatcher")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--backend", choices=["bundle", "docx", "hwpx", "hwp"], default=None,
                    help="override build.yaml doc_backend (default: bundle)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: <WS>/output/deliverable for bundle, "
                         "<WS>/output for docx/hwpx)")
    a = ap.parse_args(argv)

    ws = a.workspace
    if not os.path.isdir(ws):
        print(json.dumps({"ok": False, "error": f"workspace not found: {ws}"}), file=sys.stderr)
        return 2

    backend = resolve_backend(ws, a.backend)

    # --out-dir containment: deliverables only ever land inside the workspace's
    # output/ tree (the bundle backend deletes-and-recreates figure dirs at the
    # target, so an arbitrary path here would be destructive).
    if a.out_dir is not None:
        out_real = os.path.realpath(a.out_dir)
        allowed = os.path.realpath(os.path.join(ws, "output"))
        try:
            contained = os.path.commonpath([allowed, out_real]) == allowed
        except ValueError:  # different drives
            contained = False
        if not contained:
            print(json.dumps({"ok": False,
                              "error": f"--out-dir must stay under <WS>/output: {a.out_dir}"}),
                  file=sys.stderr)
            return 2

    if backend == "hwp":
        print(_HWP_POINTER, file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwp", "external": True,
                          "reason": "hwp is an external adapter (hwp-master)"}))
        return 4

    if backend == "hwpx":
        return _run_hwpx_adapter(ws, a.out_dir)

    if backend == "bundle":
        from adapters_impl import bundle_backend
        result, code = bundle_backend.build(ws, a.out_dir)
    elif backend == "docx":
        from adapters_impl import docx_backend
        result, code = docx_backend.build(ws, a.out_dir)
    else:
        print(json.dumps({"ok": False, "error": f"unknown backend: {backend}"}), file=sys.stderr)
        return 3

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
