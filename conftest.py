# -*- coding: utf-8 -*-
"""Repo-root conftest: suite hygiene guard for the private personalization store.

``REPO_ROOT/.local/personalization`` is the OPERATOR's private profile root
(personalization_ctl DEFAULT_ROOT). No test may create it or modify it — a
test that needs a profile root pins one under ``tmp_path`` (see issue #12:
tests/test_setup_profile.py and tests/test_new_report.py invoked CLIs whose
default profile root is this directory, so every suite run silently wrote
into the checkout).

The guard is session-scoped and autouse: it snapshots the directory's file
inventory (relpath -> sha256) before any test runs and asserts after the
whole suite that the store is byte-identical — absent stays absent, existing
operator data stays untouched.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_PERSONALIZATION_ROOT = Path(__file__).resolve().parent / ".local" / "personalization"


def _store_snapshot(root: Path) -> dict[str, str] | None:
    """None if the store does not exist; else {relpath: sha256} for every file."""
    if not root.is_dir():
        return None
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return snapshot


@pytest.fixture(scope="session", autouse=True)
def _personalization_store_untouched():
    before = _store_snapshot(_PERSONALIZATION_ROOT)
    yield
    after = _store_snapshot(_PERSONALIZATION_ROOT)
    if before is None:
        assert after is None, (
            f"suite hygiene violation: a test created {_PERSONALIZATION_ROOT} "
            f"(files: {sorted(after)}). Pin the profile root to tmp_path "
            "(--profile-root) instead of the repo-default store."
        )
    else:
        assert after == before, (
            f"suite hygiene violation: a test modified the operator's private "
            f"personalization store at {_PERSONALIZATION_ROOT}. Pin the "
            "profile root to tmp_path (--profile-root) instead."
        )
