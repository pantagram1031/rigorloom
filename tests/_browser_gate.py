# -*- coding: utf-8 -*-
"""What a browser test does when it cannot get a browser.

Locally, a missing playwright package or headless Chromium skips the test
with its reason. With `RL_REQUIRE_BROWSER=1` (set in CI) it fails instead, so
a run with no browser cannot pass while checking none of the principles the
browser tests hold.
"""
from __future__ import annotations

import os

import pytest

REQUIRE_ENV = "RL_REQUIRE_BROWSER"


def browser_required() -> bool:
    return os.environ.get(REQUIRE_ENV, "").strip() == "1"


def no_browser(reason: str, *, module_level: bool = False) -> None:
    """Skip (default) or fail (`RL_REQUIRE_BROWSER=1`) for a missing browser."""
    if browser_required():
        pytest.fail(f"{reason} ({REQUIRE_ENV}=1)", pytrace=False)
    pytest.skip(reason, allow_module_level=module_level)
