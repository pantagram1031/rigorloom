# -*- coding: utf-8 -*-
"""Packaging marker for the Runtime layer. No behaviour lives here.

This file exists so ``pyproject.toml`` can hand this directory to setuptools as
one explicitly named package, installed as ``rigorloom_runtime``. Without it the
directory is a bare script folder and the only way to ship it would be
setuptools' flat-layout auto-discovery, which sees twelve importable top-level
directories in this repository and either refuses to build or sweeps all twelve
into the distribution.

It stays empty on purpose. The modules beside it resolve their siblings by
inserting their own directory on ``sys.path`` (``runtime/scripts/cli.py:54``),
which is what lets ``python runtime/scripts/cli.py`` and the installed
``rigorloom`` command run the same code. Re-exporting anything here would give
those modules a second import identity and two copies of module-level state.
"""
