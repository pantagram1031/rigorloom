#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime Protocol v0 server — JSONL over stdio.

    python runtime/scripts/serve.py --entry host  --root <dir>
    python runtime/scripts/serve.py --entry agent --root <dir>

Invocation shape follows the repository: every shipped surface is a script
called by path (``python engine/scripts/preedit.py ...``,
``python pipeline/scripts/check_residue.py ...``), and ``pyproject.toml``
declares no console scripts. A packaged executable is a Phase 2 decision — see
docs/desktop-architecture.md §6.

``--entry`` is the ONLY authority control. The host entry registers the
host-only methods; the agent entry does not build them. There is no flag, field
or header that promotes an agent connection.

``--root`` is required and has no default: the Runtime never guesses where it
may write. Sessions, work files and candidates live under it.

stdout carries protocol frames and nothing else; every diagnostic goes to
stderr. Exit codes are the repository's (pipeline/scripts/checker_base.py:13-16):
0 clean shutdown on EOF, 2 usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import EXIT_OK, EXIT_USAGE, IMPL_VERSION, PROTOCOL_VERSION  # noqa: E402
from rt_jsonl import log  # noqa: E402
from rt_server import ENTRIES, RuntimeServer  # noqa: E402


def utf8_stdio() -> None:
    """Before parse_args, for the cp949 reason at engine/scripts/cli_io.py:3."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime/scripts/serve.py",
        description="Runtime Protocol v0 over JSONL/stdio (offline preedit "
                    "backend only).")
    parser.add_argument("--entry", required=True, choices=list(ENTRIES),
                        help="authority surface: host registers the host-only "
                             "methods, agent does not build them")
    parser.add_argument("--root", required=True,
                        help="directory the Runtime may write under (sessions, "
                             "work files, candidates). No default, ever.")
    parser.add_argument("--engine-root", default=None,
                        help="repo root holding engine/scripts and "
                             "pipeline/scripts (default: this checkout)")
    parser.add_argument("--version", action="store_true",
                        help="print protocol and implementation version, exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.version:
        log(f"protocol {PROTOCOL_VERSION} impl {IMPL_VERSION}")
        return EXIT_OK
    root = Path(args.root).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(f"--root is not usable: {exc}")
        return EXIT_USAGE
    server = RuntimeServer(entry=args.entry, root=root,
                           engine_root=args.engine_root)
    log(f"runtime ready: entry={args.entry} protocol={PROTOCOL_VERSION} "
        f"impl={IMPL_VERSION}")
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
