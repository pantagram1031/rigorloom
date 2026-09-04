# -*- coding: utf-8 -*-
"""child_env(): the allowlist a bounded child actually gets (T130).

DCOM local-server activation for Hancom's ``HWPFrame.HwpObject`` fails with
``CO_E_SERVER_EXEC_FAILURE`` under the allowlist that existed before this
test, even though the exact same ``com_backend.py convert`` call succeeds
run directly from a normal shell. Bisected on an operator bench: the
allowlist alone reproduces the failure every time; adding ONLY
``ProgramData`` back onto it makes the same convert succeed every time.
``USERNAME``, ``USERDOMAIN``, ``SESSIONNAME``, ``ProgramFiles``,
``ProgramFiles(x86)``, ``HOMEDRIVE`` and ``HOMEPATH`` were each tried too and
are not required for this activation to succeed.

This is a regression guard, not a retest of the live COM leg — that lives in
``tests/test_runtime_render_prepare.py`` and stays substituted there because
the suite may not start Hancom.
"""
from __future__ import annotations

import sys

from _runtime_client import runtime_scripts_on_path

runtime_scripts_on_path()

import rt_engine  # noqa: E402


def test_program_data_is_in_the_windows_allowlist():
    """T130: without it, Hancom's local-server activation fails."""
    assert "ProgramData" in rt_engine._ENV_KEYS_WINDOWS


def test_the_allowlist_comment_explains_why_program_data_is_there():
    """The reason has to survive the next person's edit, not just this test."""
    source = open(rt_engine.__file__, encoding="utf-8").read()
    body = source.split("_ENV_KEYS_WINDOWS = (", 1)[1].split("_ENV_KEYS_POSIX", 1)[0]
    assert "ProgramData" in body
    assert "CO_E_SERVER_EXEC_FAILURE" in body


def test_child_env_carries_program_data_through_on_windows(monkeypatch):
    monkeypatch.setattr(rt_engine.os, "name", "nt", raising=False)
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    env = rt_engine.child_env()
    assert env.get("ProgramData") == r"C:\ProgramData"


def test_child_env_without_program_data_set_simply_omits_it(monkeypatch):
    """Allowlisted but absent from os.environ is not an error (T25 shape)."""
    monkeypatch.setattr(rt_engine.os, "name", "nt", raising=False)
    monkeypatch.delenv("ProgramData", raising=False)
    env = rt_engine.child_env()
    assert "ProgramData" not in env
