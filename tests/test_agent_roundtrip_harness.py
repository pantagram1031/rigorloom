"""Regression tests for the checkout-independent Agent Host round-trip harness."""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "desktop" / "scripts" / "agent_roundtrip.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("agent_roundtrip_harness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_pack_checks_use_private_enablement_without_mutating_checkout(tmp_path):
    harness = _load_harness()
    checkout_enablement = REPO / "modules" / "enabled.yaml"
    before = (checkout_enablement.read_bytes()
              if checkout_enablement.exists() else None)

    harness.checks.clear()
    harness.task_pack_checks(tmp_path)

    failed = [name for name, ok, _detail in harness.checks if not ok]
    assert failed == []
    assert (tmp_path / "modules-enabled.yaml").is_file()
    after = (checkout_enablement.read_bytes()
             if checkout_enablement.exists() else None)
    assert after == before
