#!/usr/bin/env python3
"""Read-only structural checks over an already-built HWPX package.

This is deliberately separate from ``hwpx_write.py``: the writer is a
lexical serializer that must never silently change a document, so a rule
that *would* rewrite bytes belongs here, as a WARN-only report, not as a
mutation ``hwpx_write.py`` applies on its own.

Checks
------
``--section-order``
    Flags an ``hp:colPr`` control that a header or footer control precedes
    in the same section-head paragraph.  Measured on official Automation
    (Hwp 2024 13.0.0.2986, ten probe variants,
    ``docs/research/render-check-01.md`` note 4 on
    ``origin/claude/engine-e2-columns-f49``, PR #222): Hancom silently
    ignores such a column definition and renders the section full width —
    no repair dialog, no warning, `colCount` survives the round-trip
    unchanged.  Valid orders are ``secPr, colPr, …`` (furniture after) or
    ``colPr`` carried by the paragraph *following* the section head.  See
    ``engine/references/owpml-writer-notes.md`` §9 "Section head control
    order".

CLI
---
    python hwpx_lint.py --section-order FILE.hwpx [FILE.hwpx ...]

Exit code 0 when every checked file passes every selected check; 1 when any
warning is emitted; 2 on a file the writer's own reader cannot open.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402
from hwpx_write import HwpxPackage, HwpxWriteError  # noqa: E402

#: The controls the section-head order rule cares about.  Any other
#: hp:ctrl child (equation, table, shape, ...) is irrelevant to it.
_TRACKED = ("secPr", "colPr", "header", "footer")

#: Wrapper elements the walk descends into while looking for tracked
#: controls.  A tracked control's own subtree -- a header's hp:subList
#: paragraphs, for instance -- is never descended into: those belong to a
#: different document (the header's own content), not to more section-head
#: controls.
_DESCEND = ("run", "ctrl", "switch", "case", "default")


def section_head_order(section_root):
    """The tracked control tags of ``section_root``'s first paragraph.

    ``section_root`` is the parsed ``<hs:sec>`` :class:`~hwpx_write.XmlNode`.
    Returns ``None`` when the section has no paragraph at all (malformed).
    """
    head = section_root.find_local("p")
    if head is None:
        return None
    order = []

    def walk(node):
        for child in node.children:
            name = child.local
            if name in _TRACKED:
                order.append(name)
                continue
            if name in _DESCEND:
                walk(child)

    walk(head)
    return order


def colpr_shadowed(order):
    """True when a header/footer control precedes ``hp:colPr`` in ``order``."""
    if not order or "colPr" not in order:
        return False
    return any(name in ("header", "footer")
               for name in order[:order.index("colPr")])


def check_section_order(path):
    """Return one warning dict per section of ``path`` whose colPr is shadowed."""
    package = HwpxPackage.read(path)
    warnings = []
    for name in package.section_names():
        order = section_head_order(package.part(name).tree().root)
        if colpr_shadowed(order):
            warnings.append({
                "file": str(path),
                "part": name,
                "check": "section-order",
                "order": order,
                "message": (
                    "%s: hp:colPr is preceded by a header/footer control in "
                    "the section-head paragraph (order=%s) -- Hancom "
                    "ignores the column definition and renders the section "
                    "full width" % (name, order)),
            })
    return warnings


_CHECKS = {
    "section-order": check_section_order,
}


def lint(paths, checks):
    """Run the named ``checks`` over every path; return the warning list."""
    warnings = []
    for path in paths:
        for check_name in checks:
            warnings.extend(_CHECKS[check_name](path))
    return warnings


def main(argv=None):
    utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="hwpx_lint.py",
        description="Read-only structural lint checks over built HWPX files.")
    parser.add_argument("files", nargs="+", type=Path,
                        help="HWPX file(s) to check")
    parser.add_argument("--section-order", action="store_true",
                        help="flag hp:colPr shadowed by header/footer in a "
                             "section-head paragraph")
    args = parser.parse_args(argv)

    checks = [name for name in _CHECKS if getattr(
        args, name.replace("-", "_"))]
    if not checks:
        parser.error("no check selected -- pass e.g. --section-order")

    try:
        warnings = lint(args.files, checks)
    except HwpxWriteError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2

    for warning in warnings:
        sys.stdout.write("WARN %s: %s\n" % (warning["file"], warning["message"]))
    if warnings:
        sys.stderr.write("%d warning(s)\n" % len(warnings))
        return 1
    sys.stdout.write(
        "ok: %d file(s), %d check(s), no warnings\n"
        % (len(args.files), len(checks)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
