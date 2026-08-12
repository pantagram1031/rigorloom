# -*- coding: utf-8 -*-
"""Cross-lane reproduction of the private-capture custody claims (T126).

The other lane's PRs #134-#137 assert that a private measurement capture binds a
no-follow, ONE-LINK file generation and refuses a leaf that is a symlink, a
reparse point, or hardlinked. The joint objective says to reproduce the other
lane's claims rather than accept its record, and that a missing result never
counts as parity. This file is that reproduction, written from this side against
the shipped code, not derived from the PR description.

What is reproduced here:

* a clean one-link file is ACCEPTED and the capture returns an identity, a
  one-link count, and a sha256 over the exact bytes read;
* a hardlinked leaf is REFUSED — the mechanism is an explicit `nlink != 1`
  rejection after the bound read, so the check cannot be satisfied by racing the
  path;
* a symlinked leaf is REFUSED;
* a refusal carries NO path and NO platform detail. The implementation collapses
  every failure to `ValueError(reason)` on purpose, so a private pathful artifact
  cannot leak through a measurement record's failure text. That is a privacy
  property, which is this lane's business, and it is asserted rather than assumed.

What is NOT reproduced, and therefore not claimed: generation rebinding after
metrics, ownership-aware rollback across parent-swap races, and the post-key
manifest ordering. Those need a full renderer run and a race harness; the support
matrix says so in its own row rather than implying this file covers them.

A private function is exercised deliberately. Offline there is no public path to
the capture, and a custody guarantee nobody can test from outside is a guarantee
on trust. The alternative — not reproducing it at all — is worse.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_cert  # noqa: E402


def _can_symlink(tmp_path) -> bool:
    """Windows needs Developer Mode or elevation; skipping is a stated limit."""
    target = tmp_path / "_symlink_probe_target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "_symlink_probe_link"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):
        return False
    link.unlink()
    return True


def test_a_clean_one_link_file_is_captured(tmp_path):
    """The accept case needs its OWN file.

    Creating a hardlink raises the ORIGINAL's link count to 2, so reusing one
    file for both cases makes the accept case fail for the wrong reason — which
    is exactly what happened on the first attempt at this reproduction.
    """
    clean = tmp_path / "clean.json"
    clean.write_bytes(b'{"measurement": 1}')
    assert clean.stat().st_nlink == 1, "fixture is not one-link"

    captured = render_cert._capture_private_generation(clean, "t126-accept")

    assert captured["nlink"] == 1
    assert captured["bytes"] == len(b'{"measurement": 1}')
    assert captured["raw"] == b'{"measurement": 1}'
    assert captured["sha256"] == __import__("hashlib").sha256(
        b'{"measurement": 1}').hexdigest()
    assert captured["identity"] is not None


def test_a_hardlinked_leaf_is_refused(tmp_path):
    original = tmp_path / "original.json"
    original.write_bytes(b'{"measurement": 2}')
    hardlink = tmp_path / "hardlink.json"
    os.link(original, hardlink)
    assert hardlink.stat().st_nlink == 2, "fixture did not create a second link"

    for candidate in (hardlink, original):
        with pytest.raises(ValueError):
            render_cert._capture_private_generation(candidate, "t126-hardlink")


def test_a_symlinked_leaf_is_refused(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("symlink creation is unprivileged on this host "
                    "(Windows without Developer Mode); the refusal is therefore "
                    "unverified here rather than verified-absent")
    target = tmp_path / "target.json"
    target.write_bytes(b'{"measurement": 3}')
    link = tmp_path / "link.json"
    os.symlink(target, link)

    with pytest.raises(ValueError):
        render_cert._capture_private_generation(link, "t126-symlink")


def test_a_refusal_never_carries_the_private_path(tmp_path):
    """The reason token is the whole message, on purpose.

    A measurement record is a private pathful artifact; its FAILURE text must not
    become a second, public copy of that path. The implementation funnels every
    failure through `ValueError(reason)` for this, so the property is worth an
    assertion of its own.
    """
    canary = tmp_path / "PRIVATE-CANARY-CUSTODY.json"
    canary.write_bytes(b'{"measurement": 4}')
    hardlink = tmp_path / "second-link.json"
    os.link(canary, hardlink)

    with pytest.raises(ValueError) as caught:
        render_cert._capture_private_generation(canary, "t126-privacy")

    message = str(caught.value)
    assert message == "t126-privacy", message
    assert "PRIVATE-CANARY-CUSTODY" not in message
    assert str(tmp_path) not in message
    # The chained cause may exist, but must not carry the path either.
    assert "PRIVATE-CANARY-CUSTODY" not in str(caught.value.__cause__ or "")


def test_a_missing_leaf_is_refused_with_the_same_token(tmp_path):
    """Absent and untrustworthy must be indistinguishable to a record reader."""
    with pytest.raises(ValueError) as caught:
        render_cert._capture_private_generation(
            tmp_path / "never-existed.json", "t126-absent")
    assert str(caught.value) == "t126-absent"
