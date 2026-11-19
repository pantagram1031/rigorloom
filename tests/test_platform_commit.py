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
import rt_paths  # noqa: E402
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
                               expected=rt_commit.ABSENT, by="test", policy="policy:new-file",
                               draft="d1")
    assert receipt["replaced"] is None and target.read_bytes() == b"new"
    assert rt_commit.owned(target, draft="d1")
    assert not rt_commit.owned(target, draft="d2") and not rt_commit.owned(target)
    result = rt_commit.undo(target, by="test")
    assert result["removed"] and not target.exists()


def test_a_persons_yes_is_for_that_save_alone(tmp_path, home):
    # Sol H1: an approved replacement must not make the file "ours" for later saves.
    target = tmp_path / "theirs.hwpx"
    target.write_bytes(b"person")
    rt_commit.commit(_candidate(tmp_path, b"v2"), target, expected=sha256_file(target),
                     by="mcp:x", policy="person:elicitation", draft="d1")
    assert target.read_bytes() == b"v2"
    assert not rt_commit.owned(target, draft="d1")


def test_only_the_approved_bytes_are_published(tmp_path, home):
    # Sol H3: the candidate changed after approval: refuse, write nothing.
    target = tmp_path / "new.hwpx"
    candidate = _candidate(tmp_path, b"approved")
    approved = sha256_file(candidate)
    candidate.write_bytes(b"swapped")
    with pytest.raises(ToolError) as exc:
        rt_commit.commit(candidate, target, expected=rt_commit.ABSENT, by="t",
                         policy="policy:new-file", candidate_sha256=approved)
    assert exc.value.code == "stale" and not target.exists()


def test_a_crash_after_publish_is_still_in_history(tmp_path, home, monkeypatch):
    # Sol H5: the history entry is written before the file, so a crash right
    # after publishing still leaves an undoable record.
    target = tmp_path / "보고서.hwpx"
    target.write_bytes(b"old")
    real = rt_commit._save_index
    calls = []

    def flaky(folder, entries):
        calls.append([e.get("state") for e in entries])
        if len(calls) == 2:  # the "done" write after publishing
            raise KeyboardInterrupt("killed")
        return real(folder, entries)

    monkeypatch.setattr(rt_commit, "_save_index", flaky)
    with pytest.raises(KeyboardInterrupt):
        rt_commit.commit(_candidate(tmp_path, b"new"), target, expected=sha256_file(target),
                         by="t", policy="person:tty")
    monkeypatch.setattr(rt_commit, "_save_index", real)
    assert target.read_bytes() == b"new"
    assert rt_commit.last_commit(target)["newSha256"] == sha256_file(target)
    rt_commit.undo(target, by="t")
    assert target.read_bytes() == b"old"


def test_a_decline_is_shared_by_every_draft(tmp_path, home):
    # Sol M1: finality is per {bytes, target}, not per draft record.
    target = tmp_path / "a.hwpx"
    assert not rt_commit.declined(target, "ab" * 32)
    rt_commit.record_decline(target, "ab" * 32, by="mcp:x")
    assert rt_commit.declined(target, "ab" * 32) and not rt_commit.declined(target, "cd" * 32)


def test_undo_keeps_the_bytes_it_displaces(tmp_path, home):
    # Sol M3: undo is a write too; what it replaces goes to history.
    target = tmp_path / "b.hwpx"
    target.write_bytes(b"old")
    rt_commit.commit(_candidate(tmp_path, b"new"), target, expected=sha256_file(target),
                     by="t", policy="person:tty")
    rt_commit.undo(target, by="t")
    kept = [p.read_bytes() for p in (home / "history").rglob("*-undone-*")]
    assert kept == [b"new"]


def test_a_long_target_name_still_saves(tmp_path, home):
    # Sol L2: the temporary name no longer grows with the target's.
    target = tmp_path / ("x" * 243 + ".hwpx")
    rt_commit.commit(_candidate(tmp_path, b"long"), target, expected=rt_commit.ABSENT,
                     by="t", policy="policy:new-file")
    assert target.read_bytes() == b"long"


@pytest.mark.parametrize("name", ["보고서.hwpx.", "보고서.hwpx ", "폴더. /a.hwpx"])
def test_trailing_dots_and_spaces_are_refused(tmp_path, name):
    # Sol M11: Windows drops them, so they alias another name.
    with pytest.raises(rt_paths.PathRefused):
        rt_paths.canonical(str(tmp_path / name))


def test_a_failed_swap_leaves_no_empty_file(tmp_path, monkeypatch):
    # Sol M2: without hard links the name is reserved first; a failed swap
    # takes the empty placeholder back.
    target = tmp_path / "c.hwpx"
    temp = tmp_path / ".rl-temp.tmp"
    temp.write_bytes(b"data")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(rt_paths.os, "replace", boom)
    with pytest.raises(OSError):
        rt_paths._publish_without_link(temp, target)
    assert not target.exists()


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


# -- faults ---------------------------------------------------------------------

def test_a_crash_before_publish_leaves_the_target_and_the_candidate(tmp_path, home, monkeypatch):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"person")
    candidate = _candidate(tmp_path, b"agent")

    real_replace = os.replace

    def killed(src, dst, *args, **kw):
        if Path(dst) == target:
            raise OSError("simulated power loss")
        return real_replace(src, dst, *args, **kw)

    monkeypatch.setattr(os, "replace", killed)
    with pytest.raises(OSError):
        rt_commit.commit(candidate, target, expected=sha256_file(target),
                         by="test", policy="person:tty")
    assert target.read_bytes() == b"person"
    assert candidate.read_bytes() == b"agent"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_file_held_open_is_locked_not_half_written(tmp_path, home, monkeypatch):
    target = tmp_path / "a.hwpx"
    target.write_bytes(b"person")
    candidate = _candidate(tmp_path, b"agent")

    real_replace = os.replace

    def sharing_violation(src, dst, *args, **kw):
        if Path(dst) == target:
            raise PermissionError(13, "The process cannot access the file")
        return real_replace(src, dst, *args, **kw)

    monkeypatch.setattr(os, "replace", sharing_violation)
    with pytest.raises(ToolError) as err:
        rt_commit.commit(candidate, target, expected=sha256_file(target),
                         by="test", policy="person:tty")
    assert err.value.code == "locked"
    assert target.read_bytes() == b"person" and candidate.exists()


def test_create_new_on_a_filesystem_without_hard_links(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows publishes with rename")
    import errno

    def no_links(*_args, **_kw):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    target = tmp_path / KOREAN
    create_new(target, b"x")
    assert target.read_bytes() == b"x"
    with pytest.raises(PathRefused) as err:
        create_new(target, b"y")
    assert err.value.code == "target_exists" and target.read_bytes() == b"x"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_creation_settled_after_a_crash_is_not_ours(tmp_path, home, monkeypatch):
    # Sol re-check F4: after a crash, matching bytes cannot prove we published
    # them, so the file is not "ours" and undo will not remove it.
    target = tmp_path / "보고서.hwpx"
    real = rt_commit._save_index
    calls = []

    def flaky(folder, entries):
        calls.append(1)
        if len(calls) == 2:  # the "done" write after publishing
            raise KeyboardInterrupt("killed")
        return real(folder, entries)

    monkeypatch.setattr(rt_commit, "_save_index", flaky)
    with pytest.raises(KeyboardInterrupt):
        rt_commit.commit(_candidate(tmp_path, b"new"), target, expected=rt_commit.ABSENT,
                         by="t", policy="policy:new-file", draft="d1")
    monkeypatch.setattr(rt_commit, "_save_index", real)
    assert target.read_bytes() == b"new"
    assert not rt_commit.owned(target, draft="d1")
    with pytest.raises(ToolError) as caught:
        rt_commit.undo(target, by="t")
    assert caught.value.code == "target_changed" and target.read_bytes() == b"new"


def test_undo_puts_a_created_file_back_when_it_cannot_check_it(tmp_path, home, monkeypatch):
    # Sol re-check F3, round 2: a read error after the move must not strand the file.
    target = tmp_path / "보고서.hwpx"
    rt_commit.commit(_candidate(tmp_path, b"new"), target, expected=rt_commit.ABSENT,
                     by="t", policy="policy:new-file", draft="d1")
    real = rt_commit.sha256_file

    def unreadable(path):
        if "-created-" in Path(path).name:
            raise PermissionError("denied")
        return real(path)

    monkeypatch.setattr(rt_commit, "sha256_file", unreadable)
    with pytest.raises(ToolError) as caught:
        rt_commit.undo(target, by="t")
    assert caught.value.code == "target_changed" and target.read_bytes() == b"new"


def test_names_show_every_invisible_character():
    # Sol re-check F5, round 2: zero-width and other invisible characters are
    # escaped and listed; a name that only contains the text "\u0009" is not.
    from rt_term import invisible_in, path_text
    assert path_text("a​b\tc  d") == "a\\u200bb\\u0009c  d"
    assert invisible_in("a​b\tc ") == ["U+200B", "U+0009", "U+00A0"]
    assert path_text("a\\u0009") == "a\\u0009" and invisible_in("a\\u0009") == []
    # Round 3: a tab and the text "\u0009" swapped are still two different names,
    # and default-ignorable letters (U+034F, the Hangul filler) count as invisible.
    assert path_text("x\t\\u0009") != path_text("x\\u0009\t")
    assert invisible_in("a\u034fb\u3164") == ["U+034F", "U+3164"]
    assert path_text("a\U000e0100") == "a\\U000e0100"
