#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared, behavior-neutral frame helpers for deterministic checkers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, MutableMapping, Sequence


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


#: The declared-mode value that means "trust the derived state".
STATE_MODE_AUTO = "auto"


def resolve_state(classification: MutableMapping[str, Any],
                  mode: str) -> Mapping[str, Any] | None:
    """Apply a declared ``--mode`` over a derived state, loudly (T103).

    Every work-type checker derives a document state and then lets ``--mode``
    force it. All four recorded the override in ``state_used`` and none of them
    ever said the two DISAGREED, so a declared mode that contradicts the
    evidence was visible only to a reader who thought to compare two sibling
    keys — and ``document.state`` is the obvious one to read.

    That silence has teeth. Declaring ``final`` on a document the checker reads
    as ``blank`` makes every "you left the form's own guidance in the packet"
    rule fire on content the blank form shipped with; declaring ``blank`` on a
    filled one suppresses those rules instead. Neither is a defect of the
    document, so neither is HARD — it is a declaration disagreeing with the
    evidence, which is a WARN that names both values.

    Mutates ``classification`` to carry ``mode`` and ``state_used`` as before,
    and returns the contradiction row to append, or ``None``.
    """
    derived = classification.get("state")
    state = derived if mode == STATE_MODE_AUTO else mode
    classification["mode"] = mode
    classification["state_used"] = state
    if mode == STATE_MODE_AUTO or mode == derived:
        return None
    classification["state_declaration_conflict"] = True
    return {
        "code": "document_state_declared_against_evidence",
        "msg": ("--mode declared %r but this document reads as %r (%s), and the "
                "declared value is what gates the state-dependent rules — so "
                "findings below may name content the form itself shipped with, "
                "or may be suppressed on a document that is further along than "
                "declared" % (mode, derived,
                              classification.get("state_basis") or "no basis")),
        "declared_mode": mode,
        "derived_state": derived,
        "state_basis": classification.get("state_basis"),
    }


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
    """Parse arguments, invoke a checker adapter, and emit its strict JSON.

    The cp949 guard runs HERE, before ``parse_args``, because ``parse_args``
    is where ``--help`` prints and exits: an em-dash in a parser description
    killed ``--help`` with ``UnicodeEncodeError`` on a Korean-locale Windows
    console. Every checker that routes through ``cli_main`` is covered by
    construction; the ones with a hand-rolled main call ``_utf8_stdio()``
    themselves (swept and pinned by ``tests/test_cli_cp949_help.py``).
    """
    _utf8_stdio()
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
