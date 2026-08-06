# -*- coding: utf-8 -*-
"""Enablement gate for the report distribution module's tests.

Core-only CI (no modules/enabled.yaml, or 'report' not listed) must still
*collect* this directory cleanly — every test is then marked skipped. An
all-modules run (enabled.yaml listing 'report') executes them normally.
Enablement is read through the registry's typed accessor, never by peeking at
module names elsewhere in core.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_CORE_SCRIPTS = _REPO_ROOT / "pipeline" / "scripts"
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from module_registry import ModuleError, ModuleRegistry  # noqa: E402


def _report_enabled() -> bool:
    try:
        return "report" in ModuleRegistry().enabled_names()
    except ModuleError:
        # A malformed enabled.yaml is loud in the registry's own tests; for
        # test gating it means "not enabled", not a collection crash.
        return False


_SKIP = pytest.mark.skip(
    reason="distribution module 'report' is not enabled — write "
           "modules/enabled.yaml (python pipeline/scripts/module_registry.py "
           "write-enabled --all) to run these tests")


def pytest_collection_modifyitems(config, items):
    if _report_enabled():
        return
    for item in items:
        try:
            in_module = item.path.is_relative_to(_HERE)
        except (AttributeError, ValueError):
            in_module = str(_HERE) in str(getattr(item, "fspath", ""))
        if in_module:
            item.add_marker(_SKIP)
