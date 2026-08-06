#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report-module submission-preflight contribution (registry ``preflight``).

Core's ``submission_preflight`` keeps the artifact/proof half of the Stage 6
gate (P1/P2/P3/P5, form-structure hash, verdict_schema composition) and
subprocess-composes this script through the distribution-module registry
(v0.16 W3-S2b split). This contribution carries the workspace-vocabulary
half:

- **P0** — ``request.yaml`` must exist and parse (the deliberately small
  top-level scanner from core is reused as a library import; the parse
  *rules* stay single-sourced).
- **P4** — every declared ``required_fields`` identity value must be
  non-placeholder and appear in the rendered artifact text.
- **check_saeteuk composition** — the sibling checker's findings merge here
  source-tagged, exactly as core merged them in-process before the split: a
  provable saeteuk contradiction rejects the gate while unsupported anchors
  remain advisory.

Exit 0 = pass, 3 = HARD finding, 2 = usage error. JSON verdict on stdout
(checker_base contract); core re-tags/merges the findings and folds the exit
code into the composed gate verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

# Module-script import mechanism (see modules/README.md): sibling scripts via
# the module scripts dir, core helpers via the core pipeline/scripts dir.
SCRIPTS_DIR = Path(__file__).resolve().parent
_CORE_SCRIPTS_DIR = SCRIPTS_DIR.parents[2] / "pipeline" / "scripts"
for _dir in (_CORE_SCRIPTS_DIR, SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_saeteuk  # noqa: E402
import submission_preflight as _core_preflight  # noqa: E402


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _extracted_artifact_text(ws: Path, artifact, artifact_rel) -> str:
    """Best-effort rendered text of the canonical artifact for P4 matching.

    Reopen *failures* are core's P3 finding, not repeated here: an
    unreadable artifact simply yields empty text, so every required identity
    field reads as unfilled — fail-closed, matching the pre-split behavior."""
    if artifact is None or not artifact.is_file():
        return ""
    if not _core_preflight._within(ws / "output", artifact):
        return ""
    suffix = artifact.suffix.lower()
    if suffix not in _core_preflight.SUPPORTED_EXTENSIONS:
        return ""
    size = artifact.stat().st_size
    if size <= 0 or size > _core_preflight.MAX_ARTIFACT_BYTES:
        return ""
    try:
        if suffix == ".hwpx":
            return _core_preflight._hwpx_text(artifact)
        return _core_preflight._pdf_text(artifact)
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""


def check(workspace: str | Path) -> tuple[dict, int]:
    ws = Path(workspace)
    hard: list[dict] = []
    warn: list[dict] = []
    notes: list[str] = []

    # -- check_saeteuk composition (in-process, sibling) --------------------
    saeteuk_verdict, saeteuk_code = check_saeteuk.check(ws)
    raw_saeteuk_code = saeteuk_code
    valid_saeteuk_object = isinstance(saeteuk_verdict, dict)
    if not valid_saeteuk_object:
        saeteuk_verdict = {}
    if (
        not isinstance(saeteuk_code, int)
        or isinstance(saeteuk_code, bool)
        or saeteuk_code not in {0, 2, 3}
    ):
        saeteuk_code = 3
        hard.append({
            'source': 'check_saeteuk',
            'code': 'saeteuk_checker_failure',
            'msg': 'saeteuk sub-checker returned an unexpected exit code',
        })
    expected_child_state = {
        0: (True, 'pass'),
        2: (False, 'usage_error'),
        3: (False, 'fail'),
    }.get(saeteuk_code)
    child_hard = saeteuk_verdict.get('hard')
    child_warn = saeteuk_verdict.get('warn')
    child_inconsistent = (
        not valid_saeteuk_object
        or expected_child_state is None
        or saeteuk_verdict.get('ok') is not expected_child_state[0]
        or saeteuk_verdict.get('verdict') != expected_child_state[1]
        or not isinstance(child_hard, list)
        or not isinstance(child_warn, list)
        or (saeteuk_code == 0 and bool(child_hard))
    )
    if child_inconsistent:
        hard.append({
            'source': 'check_saeteuk',
            'code': 'saeteuk_checker_inconsistent',
            'msg': (
                'saeteuk child exit is inconsistent with its JSON verdict'
            ),
            'child_exit': raw_saeteuk_code,
        })
    for finding in child_hard if isinstance(child_hard, list) else []:
        hard.append({'source': 'check_saeteuk', **finding})
    for finding in child_warn if isinstance(child_warn, list) else []:
        warn.append({'source': 'check_saeteuk', **finding})
    if saeteuk_code == 2:
        hard.append({
            'source': 'check_saeteuk',
            'code': 'USAGE',
            'msg': saeteuk_verdict.get(
                'error', 'saeteuk sub-checker input error'),
        })

    # -- P0: request.yaml exists and parses ---------------------------------
    scalars, required_fields, request_error = _core_preflight._scan_request(
        ws / "request.yaml")
    if request_error:
        hard.append({
            "code": "P0",
            "msg": request_error,
            "at": "request.yaml",
        })
    pattern = scalars.get("output_filename")
    if not request_error and not pattern:
        notes.append(
            "request.yaml output_filename absent; filename match skipped")
    if not request_error and required_fields is None:
        notes.append(
            "request.yaml required_fields absent; identity checks skipped")

    # -- P4: required identity fields appear in the rendered artifact -------
    artifact, artifact_rel = _core_preflight._select_artifact(ws, pattern)
    if required_fields is not None:
        rendered = _core_preflight._normalized(
            _extracted_artifact_text(ws, artifact, artifact_rel))
        for field in required_fields:
            expected = scalars.get(field, "").strip()
            placeholder = expected.casefold() in {
                "", "null", "none", "todo", "tbd", "~"}
            if placeholder or _core_preflight._normalized(expected) not in rendered:
                hard.append({
                    "code": "P4",
                    "msg": f"required identity field not filled: {field}",
                    "at": artifact_rel or "request.yaml",
                })

    has_rule_hard = any(
        not (finding.get('source') == 'check_saeteuk'
             and finding.get('code') == 'USAGE')
        for finding in hard
    )
    code = (
        3 if saeteuk_code == 3 or has_rule_hard
        else (2 if saeteuk_code == 2 else 0)
    )
    verdict = {
        "ok": code == 0,
        "workspace": str(ws),
        "checker": "preflight_report",
        "artifact": artifact_rel,
        "saeteuk_exit": saeteuk_code,
        "saeteuk_files": saeteuk_verdict.get('saeteuk_files', []),
        "notes": notes,
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": ("pass" if code == 0
                    else ("fail" if code == 3 else "usage_error")),
    }
    return verdict, code


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="report-module submission-preflight contribution "
                    "(P0 request.yaml + P4 identity fields + saeteuk "
                    "composition)")
    parser.add_argument("workspace")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace)
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
