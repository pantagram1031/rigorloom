# -*- coding: utf-8 -*-
"""Report-module gating helpers for repo-level tests (imported by name, NOT a conftest: the plain module name avoids colliding with modules/report/tests/conftest.py in sys.modules) (v0.16 W3-S2b).

bootstrap's smoke run, new_report's scaffolder, and studio's stage-graph /
gate-action tests drive the report pipeline, whose stage machine is report
distribution-module payload. Core-only runs (no modules/enabled.yaml, or
'report' not listed) skip those tests — absence is not failure — and run the
complementary refusal tests instead. Enablement is read through the
registry's typed accessor, never by peeking at module names elsewhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
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


REPORT_MODULE_ENABLED = _report_enabled()

requires_report_module = pytest.mark.skipif(
    not REPORT_MODULE_ENABLED,
    reason="distribution module 'report' is not enabled — the report "
           "pipeline is module payload; write modules/enabled.yaml "
           "(python pipeline/scripts/module_registry.py write-enabled "
           "--all) to run this test")

core_only = pytest.mark.skipif(
    REPORT_MODULE_ENABLED,
    reason="core-only refusal path: distribution module 'report' is enabled")
