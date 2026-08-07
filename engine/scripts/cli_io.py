#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli_io.py — the cp949-safe entry guard every shipped engine CLI calls.

``com_backend.py --help`` died with ``UnicodeEncodeError: 'cp949' codec can't
encode character '\\u2014'`` on a Korean-locale Windows console — the exact
platform the COM path exists for. argparse writes the parser description to
``sys.stdout`` directly, so an em-dash in a docstring is enough; subcommand
help happened to work only because those strings were ASCII. The whole class
is a *placement* bug: the guard must run BEFORE ``parse_args``, since that is
where ``--help`` prints and exits.

``utf8_stdio()`` is deliberately trivial and imports nothing but ``sys``:

  * it cannot create an import cycle — every engine CLI can import it,
    including the ones other engine CLIs import;
  * it degrades silently where ``reconfigure`` is unavailable (Python < 3.7
    streams, or a stdout that is not a ``TextIOWrapper`` — pytest's capture
    object, for instance).

``pipeline/scripts`` and ``modules/*/scripts`` have the same helper as
``checker_base._utf8_stdio``, which they already import for verdict output;
that copy stays where it is because a distribution-module bundle ships
``modules/`` against an installed core and must not reach into ``engine/``.
The two are byte-identical in behavior and both are covered by the single
cp949 ``--help`` sweep in ``tests/test_cli_cp949_help.py``.
"""
from __future__ import annotations

import sys


def utf8_stdio() -> None:
    """Make non-ASCII help/JSON safe on a cp949 console; no-op when unsupported."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
