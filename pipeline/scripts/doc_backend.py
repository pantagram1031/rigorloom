# -*- coding: utf-8 -*-
"""doc_backend.py — pluggable document-backend dispatcher for Stage 5.

Usage:
    python pipeline/scripts/doc_backend.py <WS> [--backend bundle|docx|hwp]
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
    hwp     EXTERNAL adapter (hwp-master, Windows + Hancom). Not implemented
            here — prints the pointer instruction and exits 4.

Exit codes:
    0  success
    2  usage / bundle floor missing
    3  unknown backend
    4  hwp backend requested (external adapter — see printed pointer)
    5  docx backend requested but python-docx not installed
"""
from __future__ import annotations

import argparse
import json
import os
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
    ap.add_argument("--backend", choices=["bundle", "docx", "hwp"], default=None,
                    help="override build.yaml doc_backend (default: bundle)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: <WS>/output/deliverable for bundle, "
                         "<WS>/output for docx)")
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
