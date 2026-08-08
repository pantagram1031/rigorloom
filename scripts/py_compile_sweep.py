#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-agnostic byte-compile sweep over every shipped Python surface.

Why this exists: CI used to inline the sweep as

    python -m py_compile pipeline/scripts/*.py scripts/*.py studio/main.py \
        modules/report/scripts/*.py modules/style/scripts/*.py \
        modules/gongmun/scripts/*.py

— a hardcoded per-module list, so adding a distribution module required a core
edit. That contradicts ``modules/README.md`` rule 4 ("adding a module later
requires no core change"). The pattern set below names no module: the single
``modules/*/scripts/*.py`` entry covers every module present, including ones
that do not exist yet.

The sweep is a script rather than a shell one-liner for two reasons: the glob
expansion no longer depends on the runner's shell (the old line needed
``shell: bash`` so pwsh would not pass literal patterns to py_compile), and the
property "a brand-new module's scripts are covered" becomes testable — see
``pipeline/tests/test_module_registry.py::TestHarnessIsModuleAgnostic``.

Exit codes follow the repo convention: 0 = everything compiled, 2 = usage
refusal (nothing matched at all — a silent no-op sweep is worse than a
failure), 3 = at least one file failed to compile.
"""
from __future__ import annotations

import argparse
import json
import py_compile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Root-relative glob patterns. Add a pattern here only for a NEW core surface;
# never for a module (``modules/*/scripts/*.py`` already covers those).
PATTERNS: tuple[str, ...] = (
    "engine/scripts/*.py",
    "pipeline/scripts/*.py",
    "scripts/*.py",
    "studio/main.py",
    "modules/*/scripts/*.py",
)


def collect(root: Path, patterns: tuple[str, ...] = PATTERNS) -> list[Path]:
    """Every file the sweep covers under ``root``, deduplicated and sorted."""
    found: dict[Path, None] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                found[path.resolve()] = None
    return list(found)


def sweep(root: Path, patterns: tuple[str, ...] = PATTERNS) -> tuple[dict, int]:
    root = Path(root).resolve()
    targets = collect(root, patterns)
    failures = []
    for path in targets:
        try:
            py_compile.compile(str(path), doraise=True, quiet=1)
        except py_compile.PyCompileError as exc:
            failures.append({"file": path.relative_to(root).as_posix(),
                             "error": str(exc).strip()})
    report = {
        "root": str(root),
        "patterns": list(patterns),
        "compiled": [p.relative_to(root).as_posix() for p in targets],
        "count": len(targets),
        "failures": failures,
        "ok": not failures,
    }
    if not targets:
        report["ok"] = False
        report["detail"] = ("no Python file matched any sweep pattern — "
                            "the sweep would have passed vacuously")
        return report, 2
    return report, (0 if report["ok"] else 3)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Byte-compile every shipped Python surface. Module-"
                    "agnostic: modules/*/scripts/*.py needs no per-module "
                    "entry, ever.")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repo root to sweep (default: this checkout)")
    parser.add_argument("--json", action="store_true",
                        help="emit the full report instead of a summary line")
    args = parser.parse_args(argv)

    report, code = sweep(Path(args.root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"py_compile sweep: {report['count']} file(s), "
              f"{len(report['failures'])} failure(s)")
        for row in report["failures"]:
            print(f"  FAIL {row['file']}: {row['error']}", file=sys.stderr)
        if report.get("detail"):
            print(f"  {report['detail']}", file=sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
