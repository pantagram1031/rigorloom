# -*- coding: utf-8 -*-
"""The one writer into a person's folder (rt_commit) and the path gate (rt_paths).

These are the promises an agent's `save` and a person's `undo` rest on:
nothing is replaced unless its bytes are the ones we expected, the old bytes
are kept first, undo only restores over our own bytes, and paths outside the
allowed folders are refused at use time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime" / "scripts"))

import rt_commit  # noqa: E402
from rt_paths import (  # noqa: E402
    PathRefused,
    Roots,
    canonical,
    create_new,
    replace_checked,
    sha256_bytes,
    sha256_file,
)
from rt_tools import ToolError  # noqa: E402

KOREAN = "보고서 최종 (수정).hwpx"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "state"
    monkeypatch.setenv("RIGORLOOM_HOME", str(h))
    return h


def _candidate(tmp_path: Path, data: bytes, name: str = "cand.hwpx") -> Path:
    path = tmp_path / "cands" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# -- create_new / replace_checked ---------------------------------------------

def test_create_new_writes_and_never_replaces(tmp_path):
    target = tmp_path / KOREAN
    create_new(target, b"one")
    assert target.read_bytes() == b"one"
    with pytest.raises(PathRefused) as err:
        create_new(target, b"two")
    assert err.value.code == "target_exists"
    assert target.read_bytes() == b"one"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_create_new_refuses_a_dangling_symlink(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink creation needs privileges on Windows")
    target = tmp_path / "link.hwpx"
    target.symlink_to(tmp_path / "elsewhere.hwpx")
    with pytest.raises(PathRefused) as err:
        create_new(target, b"x")
    assert err.value.code == "target_exists"
    assert not (tmp_path / "elsewhere.hwpx").exists()


def test_replace_checked_refuses_when_the_target_moved(tmp_path):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"theirs")
    with pytest.raises(PathRefused) as err:
        replace_checked(target, b"ours", sha256_bytes(b"what we saw"))
    assert err.value.code == "target_changed"
    assert target.read_bytes() == b"theirs"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_long_korean_path(tmp_path):
    deep = tmp_path
    while len(str(deep)) < 280:
        deep = deep / "아주긴폴더이름입니다"
    deep.mkdir(parents=True)
    target = deep / KOREAN
    create_new(target, b"x")
    assert target.read_bytes() == b"x"


# -- commit, history, undo ----------------------------------------------------

def test_commit_creates_and_undo_moves_our_file_away(tmp_path, home):
    target = tmp_path / KOREAN
    receipt = rt_commit.commit(_candidate(tmp_path, b"new"), target,
                               expected=rt_commit.ABSENT, by="test", policy="policy:new-file")
    assert receipt["replaced"] is None and target.read_bytes() == b"new"
    assert rt_commit.owned(target)
    result = rt_commit.undo(target, by="test")
    assert result["removed"] and not target.exists()


def test_commit_keeps_old_bytes_and_undo_restores_them(tmp_path, home):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"person")
    old = sha256_file(target)
    rt_commit.commit(_candidate(tmp_path, b"agent"), target, expected=old,
                     by="test", policy="person:tty")
    assert target.read_bytes() == b"agent"
    rt_commit.undo(target, by="test")
    assert target.read_bytes() == b"person"
    with pytest.raises(ToolError):
        rt_commit.undo(target, by="test")  # already undone


def test_commit_refuses_a_changed_target_and_writes_nothing(tmp_path, home):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"v1")
    seen = sha256_file(target)
    target.write_bytes(b"v2 saved in Hancom meanwhile")
    with pytest.raises(ToolError) as err:
        rt_commit.commit(_candidate(tmp_path, b"agent"), target, expected=seen,
                         by="test", policy="person:tty")
    assert err.value.code == "target_changed"
    assert target.read_bytes() == b"v2 saved in Hancom meanwhile"


def test_commit_absent_refuses_a_racing_file(tmp_path, home):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"someone else got here first")
    with pytest.raises(ToolError) as err:
        rt_commit.commit(_candidate(tmp_path, b"agent"), target,
                         expected=rt_commit.ABSENT, by="test", policy="policy:new-file")
    assert err.value.code == "target_exists"
    assert target.read_bytes() == b"someone else got here first"


def test_undo_refuses_over_bytes_we_did_not_write(tmp_path, home):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"person")
    rt_commit.commit(_candidate(tmp_path, b"agent"), target,
                     expected=sha256_file(target), by="test", policy="person:tty")
    target.write_bytes(b"person edited again")
    with pytest.raises(ToolError) as err:
        rt_commit.undo(target, by="test")
    assert err.value.code == "target_changed"
    assert target.read_bytes() == b"person edited again"


def test_history_lives_under_the_state_dir(tmp_path, home):
    target = tmp_path / "docs" / "a.hwpx"
    target.parent.mkdir()
    target.write_bytes(b"person")
    rt_commit.commit(_candidate(tmp_path, b"agent"), target,
                     expected=sha256_file(target), by="test", policy="person:tty")
    assert sorted(p.name for p in target.parent.iterdir()) == ["a.hwpx"]
    kept = list((home / "history").rglob("*.hwpx"))
    assert len(kept) == 1 and kept[0].read_bytes() == b"person"


# -- the path gate ------------------------------------------------------------

def test_roots_refuse_traversal(tmp_path):
    allowed = tmp_path / "work"
    allowed.mkdir()
    (tmp_path / "secret.hwpx").write_bytes(b"x")
    roots = Roots.of([allowed])
    with pytest.raises(PathRefused) as err:
        roots.check(str(allowed / ".." / "secret.hwpx"))
    assert err.value.code == "outside_roots"


def test_roots_refuse_a_symlink_out(tmp_path):
    if os.name == "nt":
        pytest.skip("symlink creation needs privileges on Windows")
    allowed = tmp_path / "work"
    allowed.mkdir()
    (tmp_path / "secret.hwpx").write_bytes(b"x")
    (allowed / "link.hwpx").symlink_to(tmp_path / "secret.hwpx")
    with pytest.raises(PathRefused):
        Roots.of([allowed]).check(str(allowed / "link.hwpx"))


def test_roots_allow_inside_and_reject_prefix_siblings(tmp_path):
    allowed = tmp_path / "work"
    allowed.mkdir()
    (tmp_path / "work2").mkdir()
    roots = Roots.of([allowed])
    assert roots.check(str(allowed / "a.hwpx")) == canonical(allowed / "a.hwpx")
    with pytest.raises(PathRefused):
        roots.check(str(tmp_path / "work2" / "a.hwpx"))


@pytest.mark.parametrize("name", ["CON", "nul.hwpx", "COM1.txt", "a.hwpx:stream", "LPT9"])
def test_windows_device_names_and_streams_are_refused_everywhere(tmp_path, name):
    with pytest.raises(PathRefused):
        canonical(str(tmp_path / name))


def test_empty_and_nul_paths_are_refused():
    for raw in ("", "   ", "a\x00b.hwpx"):
        with pytest.raises(PathRefused):
            canonical(raw)


def test_case_alias_on_windows(tmp_path):
    if os.name != "nt":
        pytest.skip("case-insensitive comparison is a Windows property")
    allowed = tmp_path / "Work"
    allowed.mkdir()
    roots = Roots.of([allowed])
    assert roots.contains(canonical(str(tmp_path / "WORK" / "a.hwpx")))


def test_empty_roots_allow_nothing(tmp_path):
    with pytest.raises(PathRefused) as err:
        Roots.of([]).check(str(tmp_path / "a.hwpx"))
    assert err.value.code == "outside_roots"
