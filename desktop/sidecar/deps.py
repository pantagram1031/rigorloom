#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compute the hidden imports the frozen sidecar needs. Prints one per line.

Why this exists. The engine and pipeline scripts ship in the bundle as **data**,
because ``rigorloomd.py`` executes them with ``runpy`` when the Runtime spawns
them as children. PyInstaller's analysis therefore never sees their ``import``
statements, and the first thing that breaks is not obvious: the build succeeds,
the server answers ``initialize``, and then ``document/inspect`` dies with
``ModuleNotFoundError: No module named 'xml'`` — a stdlib package nothing in
``rigorloomd.py``'s own graph happened to pull in.

Guessing the list by hand is how that regresses the next time an engine script
grows an import. So the list is derived: walk the repo-local dependency closure
of the three entrypoints the Runtime actually spawns
(``runtime/scripts/rt_engine.py:164-166``), collect every non-local import along
the way, and emit the top-level names.

Static AST only. No script is imported or executed to find this out — several of
them do real work at import time.

    python deps.py <repo-root>
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Everything the Runtime spawns as a child. The first three are what
#: EngineTools resolves (runtime/scripts/rt_engine.py:164-166); ``own_render``
#: is tier 3 (runtime/scripts/rt_own.py), spawned through the same interpreter
#: role, and it is the ONLY entrypoint here that pulls a third-party package
#: (Pillow) in from a lazy function-level import — which is exactly the shape
#: PyInstaller cannot see and this walk exists to find.
ENTRYPOINTS = (
    "engine/scripts/form_inspect.py",
    "engine/scripts/preedit.py",
    "pipeline/scripts/check_residue.py",
    "engine/scripts/own_render.py",
)

#: Where a bare `import foo` may resolve to a repo sibling rather than a package.
LOCAL_DIRS = ("engine/scripts", "pipeline/scripts")


def top_level_imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has no module; repo scripts do not use it, but
            # skipping is correct rather than crashing if one appears.
            if node.level == 0 and node.module:
                found.add(node.module)
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: deps.py <repo-root>\n")
        return 2
    root = Path(argv[0]).resolve()
    local_dirs = [root / d for d in LOCAL_DIRS]

    def resolve_local(name: str) -> Path | None:
        head = name.split(".")[0]
        for directory in local_dirs:
            candidate = directory / f"{head}.py"
            if candidate.is_file():
                return candidate
        return None

    seen: set[Path] = set()
    external: set[str] = set()
    queue = [root / entry for entry in ENTRYPOINTS]

    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            sys.stderr.write(f"deps.py: cannot parse {path}: {exc}\n")
            return 3
        for name in top_level_imports(tree):
            local = resolve_local(name)
            if local is not None:
                queue.append(local)
            else:
                # `xml.etree.ElementTree` -> freeze the submodule, not just `xml`:
                # PyInstaller needs the leaf to include the leaf.
                external.add(name)

    # __future__ is a compiler directive, not a module to freeze.
    external.discard("__future__")

    for name in sorted(external):
        print(name)
    sys.stderr.write(
        f"deps.py: {len(seen)} repo scripts reached, {len(external)} external imports\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
