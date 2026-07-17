#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared, behavior-neutral frame helpers for deterministic checkers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


EXIT_PASS = 0
EXIT_USAGE = 2
EXIT_HARD = 3
VALID_EXIT_CODES = frozenset({EXIT_PASS, EXIT_USAGE, EXIT_HARD})


def _utf8_stdio() -> None:
    """Make Korean JSON safe on Windows consoles; no-op when unsupported."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def exit_code(*, hard: Sequence[Any] = (), usage: bool = False) -> int:
    """Map checker state to the repository's stable 0/2/3 exit contract."""
    if usage:
        return EXIT_USAGE
    return EXIT_HARD if hard else EXIT_PASS


def verdict_skeleton(
    workspace: Any,
    checker: str | None,
    *,
    hard: Sequence[Mapping[str, Any]] = (),
    warn: Sequence[Mapping[str, Any]] = (),
    counts: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    ok: bool | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """Build the common verdict shape while allowing checker-specific fields."""
    hard_items = list(hard)
    warn_items = list(warn)
    passed = not hard_items if ok is None else bool(ok)
    payload: dict[str, Any] = {"ok": passed, "workspace": workspace}
    if checker is not None:
        payload["checker"] = checker
    if extra:
        payload.update(extra)
    payload["hard"] = hard_items
    payload["warn"] = warn_items
    payload["counts"] = dict(
        counts
        if counts is not None
        else {"hard": len(hard_items), "warn": len(warn_items)}
    )
    payload["verdict"] = verdict or ("pass" if passed else "fail")
    return payload


def usage_error(
    workspace: Any,
    checker: str | None,
    message: str,
    *,
    counts: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    minimal: bool = False,
) -> tuple[dict[str, Any], int]:
    """Return a usage verdict, including a legacy-minimal compatibility mode."""
    if minimal:
        return {"ok": False, "error": message}, EXIT_USAGE
    payload = verdict_skeleton(
        workspace,
        checker,
        hard=(),
        warn=(),
        counts=counts,
        extra={"error": message, **dict(extra or {})},
        ok=False,
        verdict="usage_error",
    )
    return payload, EXIT_USAGE


def dump_json(payload: Mapping[str, Any]) -> str:
    """Render checker JSON strictly: UTF-8 text and no NaN/Infinity tokens."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def emit_verdict(
    verdict: Mapping[str, Any],
    code: int,
    out: str | Path | None = None,
    *,
    create_parent: bool = False,
) -> int:
    """Write/print one strict verdict and return its checker exit code."""
    rendered = dump_json(verdict)
    if out:
        target = Path(out)
        if create_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


def cli_main(
    parser: argparse.ArgumentParser,
    invoke: Callable[[argparse.Namespace], tuple[dict[str, Any], int]],
    argv: Sequence[str] | None = None,
    *,
    add_out: bool = True,
    create_out_parent: bool = False,
) -> int:
    """Parse arguments, invoke a checker adapter, and emit its strict JSON."""
    if add_out and not any(action.dest == "out" for action in parser._actions):
        parser.add_argument("--out", default=None, help="write verdict JSON here")
    args = parser.parse_args(argv)
    verdict, code = invoke(args)
    return emit_verdict(
        verdict,
        code,
        getattr(args, "out", None) if add_out else None,
        create_parent=create_out_parent,
    )
