"""Tests for scripts/sync_local.py.

Everything happens under tmp_path -- these tests NEVER touch the real skills
directory or any absolute machine path.
"""

from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import sync_local as sl  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def world(tmp_path):
    """A checkout + overlay + install triple under tmp_path."""
    checkout = tmp_path / "checkout"
    overlay = tmp_path / "overlay"
    install = tmp_path / "install"

    # checkout base tree
    write(str(checkout / "pipeline" / "scripts" / "ctl.py"), "print('base ctl')\n")
    write(str(checkout / "pipeline" / "scripts" / "helper.py"), "x = 1\n")
    write(str(checkout / "pipeline" / "references" / "stages.yaml"), "stages: [a, b]\n")
    write(str(checkout / "pipeline" / "references" / "playbooks" / "stage-0.md"), "# base stage0\n")
    # a base file that will get shadowed by the overlay
    write(str(checkout / "pipeline" / "references" / "agents.yaml"), "agents: base\n")
    # noise that must be excluded
    write(str(checkout / "pipeline" / "scripts" / "__pycache__" / "ctl.pyc"), "junk\n")

    # overlay tree (mirrors install-relative paths)
    write(str(overlay / "SKILL.md"), "# overlay skill\n")
    write(str(overlay / "references" / "agents.yaml"), "agents: OVERLAY\n")

    return {
        "checkout": str(checkout),
        "overlay": str(overlay),
        "install": str(install),
        "tmp": str(tmp_path),
    }


def make_target(world, **over):
    return sl.Target(
        name=over.get("name", "primary"),
        install_root=over.get("install_root", world["install"]),
        overlay_root=over.get("overlay_root", world["overlay"]),
        source_map=over.get("source_map", [
            {"from": "pipeline/scripts", "to": "scripts"},
            {"from": "pipeline/references", "to": "references"},
        ]),
        exclude=over.get("exclude", ["__pycache__", "*.pyc", ".pytest_cache", ".sync*"]),
    )


def plan_for(world, tmp_path, **over):
    target = make_target(world, **over)
    staging = str(tmp_path / "stg")
    os.makedirs(staging, exist_ok=True)
    return sl.make_plan(target, world["checkout"], staging), target


# --------------------------------------------------------------------------- #
# YAML parser
# --------------------------------------------------------------------------- #
def test_yaml_parser_basic():
    text = (
        'install_root: "C:\\\\Users\\\\me\\\\skill"\n'
        "overlay_root: /abs/overlay\n"
        "source_map:\n"
        "  - from: pipeline/scripts\n"
        "    to: scripts\n"
        "  - from: pipeline/references\n"
        "    to: references\n"
        "exclude: [__pycache__, '*.pyc']\n"
        "# trailing comment\n"
        "repo_targets:\n"
        "  - name: studio\n"
        "    install_root: /other/studio\n"
        "    source_map:\n"
        "      - from: studio\n"
        "        to: .\n"
    )
    cfg = sl.parse_yaml(text)
    # scalars are taken literally (no escape processing): the backslashes in the
    # source survive verbatim, which is exactly what Windows paths need.
    assert cfg["install_root"] == "C:\\\\Users\\\\me\\\\skill"
    assert cfg["source_map"] == [
        {"from": "pipeline/scripts", "to": "scripts"},
        {"from": "pipeline/references", "to": "references"},
    ]
    assert cfg["exclude"] == ["__pycache__", "*.pyc"]
    assert cfg["repo_targets"][0]["name"] == "studio"
    assert cfg["repo_targets"][0]["source_map"] == [{"from": "studio", "to": "."}]


def test_example_manifest_parses():
    manifest = os.path.join(SCRIPTS, "sync_manifest.example.yaml")
    targets = sl.load_manifest(manifest, ROOT)
    assert len(targets) == 1  # repo_targets is commented out
    t = targets[0]
    assert t.name == "primary"
    tos = {m["to"] for m in t.source_map}
    assert {"scripts", "references"} <= tos
    assert "__pycache__" in t.exclude


# --------------------------------------------------------------------------- #
# Dry-run action classification
# --------------------------------------------------------------------------- #
def test_dry_run_actions_fresh_install(world, tmp_path):
    plan, _ = plan_for(world, tmp_path)
    # base files -> add; overlay files -> overlay
    assert plan.actions["scripts/ctl.py"] == "add"
    assert plan.actions["references/stages.yaml"] == "add"
    assert plan.actions["references/playbooks/stage-0.md"] == "add"
    assert plan.actions["SKILL.md"] == "overlay"
    assert plan.actions["references/agents.yaml"] == "overlay"
    # excluded noise never staged
    assert not any("__pycache__" in r for r in plan.actions)
    assert not any(r.endswith(".pyc") for r in plan.actions)


def test_overlay_wins_over_base(world, tmp_path):
    plan, target = plan_for(world, tmp_path)
    # both base and overlay define references/agents.yaml -> overlay content wins
    assert plan.origins["references/agents.yaml"] == "overlay"
    staged = os.path.join(plan.staging_dir, "references", "agents.yaml")
    assert read(staged) == "agents: OVERLAY\n"


# --------------------------------------------------------------------------- #
# Full apply + receipt
# --------------------------------------------------------------------------- #
def test_apply_installs_and_writes_receipt(world, tmp_path, monkeypatch):
    kernel_rev = '0123456789abcdef0123456789abcdef01234567'

    def fake_git_run(argv, **kwargs):
        assert argv == ['git', '-C', world['checkout'], 'rev-parse', 'HEAD']
        return SimpleNamespace(returncode=0, stdout=kernel_rev + '\n')

    monkeypatch.setattr(sl.subprocess, 'run', fake_git_run)
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    inst = world["install"]
    assert read(os.path.join(inst, "SKILL.md")) == "# overlay skill\n"
    assert read(os.path.join(inst, "references", "agents.yaml")) == "agents: OVERLAY\n"
    receipt = json.loads(read(os.path.join(inst, sl.RECEIPT_NAME)))
    assert receipt['kernel_rev'] == kernel_rev
    assert receipt['synced_at']
    assert receipt["files"]["SKILL.md"]["origin"] == "overlay"
    assert receipt["files"]["scripts/ctl.py"]["origin"] == "base"
    # The lock is now a SIBLING of the install root, so a truly fresh install
    # (dir did not pre-exist) makes no backup; a subsequent re-sync does.
    baks = [d for d in os.listdir(world["tmp"]) if d.startswith("install.bak-")]
    assert not baks
    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    baks = [d for d in os.listdir(world["tmp"]) if d.startswith("install.bak-")]
    assert baks  # the re-sync backed up the now-existing install


def test_clock_failure_does_not_abort_sync_and_leaves_blank_timestamp(
    world, monkeypatch
):
    class BrokenDatetime:
        @classmethod
        def now(cls, *args, **kwargs):
            raise RuntimeError("clock unavailable")

    monkeypatch.setattr(sl, "datetime", BrokenDatetime)
    target = make_target(world)

    sl.run_target(target, world["checkout"], dry_run=False, force=False)

    receipt = json.loads(read(os.path.join(world["install"], sl.RECEIPT_NAME)))
    assert receipt["synced_at"] == ""
    assert receipt["generated_at"] == ""


# --------------------------------------------------------------------------- #
# Drift refusal
# --------------------------------------------------------------------------- #
def test_drift_refused_then_forced(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    # hand-edit a managed base file in the install
    ctl = os.path.join(world["install"], "scripts", "ctl.py")
    write(ctl, "print('HAND EDIT')\n")

    with pytest.raises(sl.DriftRefused) as ei:
        sl.run_target(target, world["checkout"], dry_run=False, force=False)
    assert "scripts/ctl.py" in ei.value.drifted

    # --force overwrites the local edit with the upstream version
    sl.run_target(target, world["checkout"], dry_run=False, force=True)
    assert read(ctl) == "print('base ctl')\n"


def test_dry_run_reports_drift_without_change(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    ctl = os.path.join(world["install"], "scripts", "ctl.py")
    write(ctl, "print('HAND EDIT')\n")
    # dry-run must NOT raise and must NOT modify
    plan, _ = plan_for(world, tmp_path)
    assert "scripts/ctl.py" in plan.drift
    assert read(ctl) == "print('HAND EDIT')\n"


# --------------------------------------------------------------------------- #
# Unmanaged preservation + stale deletion
# --------------------------------------------------------------------------- #
def test_unmanaged_preserved_and_stale_deleted(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)

    # add a never-synced local-only file
    local_only = os.path.join(world["install"], "scripts", "verify_content.py")
    write(local_only, "print('local only')\n")

    # remove a base source so it becomes stale on the next sync
    os.remove(os.path.join(world["checkout"], "pipeline", "scripts", "helper.py"))

    plan, _ = plan_for(world, tmp_path)
    assert "scripts/verify_content.py" in plan.unmanaged
    assert "scripts/helper.py" in plan.deletes

    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    # unmanaged survived, stale removed
    assert os.path.exists(local_only)
    assert not os.path.exists(os.path.join(world["install"], "scripts", "helper.py"))
    # unmanaged stays out of the receipt (still "never synced")
    receipt = json.loads(read(os.path.join(world["install"], sl.RECEIPT_NAME)))
    assert "scripts/verify_content.py" not in receipt["files"]


# --------------------------------------------------------------------------- #
# Atomic rollback on injected failure
# --------------------------------------------------------------------------- #
def test_atomic_rollback_on_injected_failure(world, tmp_path, monkeypatch):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)

    inst = world["install"]
    before = {}
    for dp, _dn, fns in os.walk(inst):
        for fn in fns:
            ap = os.path.join(dp, fn)
            before[os.path.relpath(ap, inst)] = read(ap)

    # make the checkout change so a real sync would alter the tree
    write(os.path.join(world["checkout"], "pipeline", "scripts", "ctl.py"),
          "print('NEW ctl')\n")

    boom = {"n": 0}

    def exploding_place(staging, install_root):
        boom["n"] += 1
        raise RuntimeError("injected mid-install failure")

    monkeypatch.setattr(sl, "_place_staged", exploding_place)

    with pytest.raises(RuntimeError):
        sl.run_target(target, world["checkout"], dry_run=False, force=True)

    assert boom["n"] == 1
    # original install restored byte-for-byte
    after = {}
    for dp, _dn, fns in os.walk(inst):
        for fn in fns:
            ap = os.path.join(dp, fn)
            after[os.path.relpath(ap, inst)] = read(ap)
    assert after == before
    assert "NEW ctl" not in after[os.path.join("scripts", "ctl.py")]


# --------------------------------------------------------------------------- #
# Path-escape safety
# --------------------------------------------------------------------------- #
def test_path_escape_in_source_map_refused(world, tmp_path):
    target = make_target(world, source_map=[
        {"from": "pipeline/scripts", "to": "../evil"},
    ])
    staging = str(tmp_path / "stg2")
    os.makedirs(staging, exist_ok=True)
    with pytest.raises(sl.PathEscape):
        sl.build_staged_tree(target, world["checkout"], staging)


def test_path_escape_in_overlay_refused(world, tmp_path):
    # an overlay file whose relative path escapes is rejected
    evil_overlay = tmp_path / "evil_overlay"
    write(str(evil_overlay / "ok.md"), "fine\n")
    target = make_target(world, overlay_root=str(evil_overlay), source_map=[])

    # normal overlay path is fine
    staging = str(tmp_path / "stg3")
    os.makedirs(staging, exist_ok=True)
    origins = sl.build_staged_tree(target, world["checkout"], staging)
    assert origins["ok.md"] == "overlay"

    # direct check that the normaliser refuses traversal
    with pytest.raises(sl.PathEscape):
        sl._norm_rel("../escape.md")


# --------------------------------------------------------------------------- #
# Lockfile
# --------------------------------------------------------------------------- #
def test_lock_blocks_second_holder(world, tmp_path):
    os.makedirs(world["install"], exist_ok=True)
    lock = sl.InstallLock(world["install"], force=False)
    lock.acquire()
    try:
        other = sl.InstallLock(world["install"], force=False)
        with pytest.raises(sl.LockHeld):
            other.acquire()
        # --force CANNOT steal from a LIVE holder: the holder keeps an open
        # fd on the lock file, so Windows sharing semantics block the remove.
        forced = sl.InstallLock(world["install"], force=True)
        with pytest.raises(sl.LockHeld):
            forced.acquire()
    finally:
        lock.release()
    # After the holder releases (fd closed, file gone), a fresh acquire works.
    again = sl.InstallLock(world["install"], force=False)
    again.acquire()
    again.release()


def test_force_steals_only_dead_lock(world, tmp_path):
    # A dead lock = file left behind by a crashed process (no open fd).
    os.makedirs(world["install"], exist_ok=True)
    dead_path = world["install"] + sl.LOCK_SUFFIX
    with open(dead_path, "w", encoding="utf-8") as fh:
        fh.write("pid=99999 uuid=deadbeef at=sometime\n")
    plain = sl.InstallLock(world["install"], force=False)
    with pytest.raises(sl.LockHeld):
        plain.acquire()
    forced = sl.InstallLock(world["install"], force=True)
    forced.acquire()
    forced.release()
    assert not os.path.exists(dead_path)


def test_two_sequential_acquires_without_release_refused(world, tmp_path):
    # Two acquires with no release between them: the second must be refused
    # (the O_CREAT|O_EXCL create is atomic, so no exists()-then-open race lets
    # both proceed).
    os.makedirs(world["install"], exist_ok=True)
    a = sl.InstallLock(world["install"], force=False)
    a.acquire()
    try:
        b = sl.InstallLock(world["install"], force=False)
        with pytest.raises(sl.LockHeld):
            b.acquire()
        assert not b.acquired
    finally:
        a.release()


def test_release_after_foreign_overwrite_does_not_unlink(world, tmp_path):
    # If a foreign holder overwrites the lock file (different token), our
    # release() must NOT unlink it — we no longer own it.
    os.makedirs(world["install"], exist_ok=True)
    a = sl.InstallLock(world["install"], force=False)
    a.acquire()
    # simulate a foreign holder replacing the lock file contents in place
    with open(a.path, "w", encoding="utf-8") as fh:
        fh.write("pid=99999 uuid=deadbeefdeadbeefdeadbeefdeadbeef at=foreign\n")
    a.release()
    # the foreign lock file is left intact — not deleted by our release
    assert os.path.exists(a.path)
    assert "deadbeef" in read(a.path)
    os.remove(a.path)


def test_normal_acquire_release_cycle_clean(world, tmp_path):
    os.makedirs(world["install"], exist_ok=True)
    a = sl.InstallLock(world["install"], force=False)
    a.acquire()
    assert os.path.exists(a.path)
    assert a.token in read(a.path)
    a.release()
    assert not a.acquired
    assert not os.path.exists(a.path)
    # a fresh acquire after a clean release succeeds
    b = sl.InstallLock(world["install"], force=False)
    b.acquire()
    assert os.path.exists(b.path)
    b.release()
    assert not os.path.exists(b.path)


def test_lock_is_sibling_outside_install_tree(world, tmp_path):
    lock = sl.InstallLock(world["install"], force=False)
    inst = os.path.abspath(world["install"])
    # the lock file must live NEXT TO the install root, never inside it, so it
    # survives the atomic rename swap.
    assert os.path.dirname(os.path.abspath(lock.path)) == os.path.dirname(inst)
    assert not os.path.abspath(lock.path).startswith(inst + os.sep)


# --------------------------------------------------------------------------- #
# Orphan garbage collection
# --------------------------------------------------------------------------- #
def test_gc_cli_removes_only_owned_orphans(world, tmp_path, capsys):
    install = world['install']
    basename = os.path.basename(install)
    orphan = tmp_path / f'{basename}.staging-XXXX'
    markerless = tmp_path / f'{basename}.staging-foreign'
    stale_lock = install + sl.LOCK_SUFFIX
    foreign = tmp_path / 'something.staging-not-ours'
    backup = tmp_path / f'{basename}.bak-20260714-120000'
    write(os.path.join(install, 'keep.txt'), 'installed\n')
    write(str(orphan / 'SKILL.md'), '# phantom\n')
    write(str(orphan / sl.STAGING_OWNER_MARKER), 'rigorloom.sync_local pid=99999\n')
    write(str(markerless / 'SKILL.md'), '# foreign staging\n')
    write(stale_lock, 'pid=99999 uuid=stale at=old\n')
    old = time.time() - sl.STALE_LOCK_SECONDS - 2
    os.utime(stale_lock, (old, old))
    write(str(foreign / 'SKILL.md'), '# foreign\n')
    write(str(backup / 'SKILL.md'), '# backup\n')
    manifest = tmp_path / 'manifest.yaml'
    write(str(manifest), f'install_root: {install}\nsource_map: []\n')
    argv = ['--gc', '--manifest', str(manifest),
            '--checkout-root', world['checkout']]

    assert sl.main(argv) == 0

    output = capsys.readouterr().out
    assert str(orphan) in output
    assert stale_lock in output
    assert not orphan.exists()
    assert markerless.is_dir()
    assert f'gc kept foreign staging {markerless}' in output
    assert not os.path.exists(stale_lock)
    assert read(os.path.join(install, 'keep.txt')) == 'installed\n'
    assert foreign.is_dir()
    assert backup.is_dir()
    write(stale_lock, 'pid=99999 uuid=fresh at=now\n')
    assert sl.main(argv) == 0
    assert os.path.exists(stale_lock)


def test_gc_keeps_staging_owned_by_a_live_process(world, tmp_path, capsys):
    # A marked staging dir whose owner PID is still alive must NOT be removed —
    # a concurrent live sync's staging tree must survive another run's auto-GC.
    install = world['install']
    basename = os.path.basename(install)
    live = tmp_path / f'{basename}.staging-LIVE'
    write(str(live / 'SKILL.md'), '# live staging\n')
    write(str(live / sl.STAGING_OWNER_MARKER),
          f'{sl.STAGING_OWNER_ID} pid={os.getpid()}\n')  # this test process is alive
    write(os.path.join(install, 'keep.txt'), 'installed\n')
    manifest = tmp_path / 'manifest.yaml'
    write(str(manifest), f'install_root: {install}\nsource_map: []\n')

    assert sl.main(['--gc', '--manifest', str(manifest),
                    '--checkout-root', world['checkout']]) == 0

    output = capsys.readouterr().out
    assert live.is_dir()  # not deleted
    assert f'gc kept staging {live}' in output


def test_sync_auto_gc_clears_prior_orphans_then_installs(world, tmp_path, capsys):
    target = make_target(world)
    basename = os.path.basename(world['install'])
    orphan = tmp_path / f'{basename}.staging-interrupted'
    stale_lock = world['install'] + sl.LOCK_SUFFIX
    write(str(orphan / 'SKILL.md'), '# phantom\n')
    write(str(orphan / sl.STAGING_OWNER_MARKER), 'rigorloom.sync_local pid=99999\n')
    write(stale_lock, 'pid=99999 uuid=stale at=old\n')
    old = time.time() - sl.STALE_LOCK_SECONDS - 2
    os.utime(stale_lock, (old, old))

    sl.run_target(target, world['checkout'], dry_run=False, force=False)

    output = capsys.readouterr().out
    assert str(orphan) in output
    assert stale_lock in output
    assert not orphan.exists()
    assert not os.path.exists(stale_lock)
    assert read(os.path.join(world['install'], 'SKILL.md')) == '# overlay skill\n'


def test_gc_keeps_live_flock_held_stale_lock(world, monkeypatch, capsys):
    target = make_target(world)
    stale_lock = world['install'] + sl.LOCK_SUFFIX
    write(stale_lock, 'pid=99999 uuid=live at=old\n')
    old = time.time() - sl.STALE_LOCK_SECONDS - 2
    os.utime(stale_lock, (old, old))
    monkeypatch.setattr(sl, '_foreign_lock_is_live', lambda path: True)

    cleared = sl.gc_target_orphans(target)

    output = capsys.readouterr().out
    assert stale_lock not in cleared
    assert os.path.exists(stale_lock)
    assert f'gc kept live lock {stale_lock}' in output


# --------------------------------------------------------------------------- #
# BLOCKER 5a: excluded install files must survive the atomic swap
# --------------------------------------------------------------------------- #
def test_excluded_install_files_preserved_across_apply(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)

    # plant a file the exclude patterns keep out of the managed set (matches
    # "__pycache__" and "*.pyc"); it was never synced and is not managed.
    excluded = os.path.join(world["install"], "scripts", "__pycache__", "local.pyc")
    write(excluded, "cached-bytes\n")

    plan, _ = plan_for(world, tmp_path)
    assert "scripts/__pycache__/local.pyc" in plan.excluded_preserved
    # it must NOT be miscategorised as a delete or a managed action
    assert "scripts/__pycache__/local.pyc" not in plan.deletes
    assert "scripts/__pycache__/local.pyc" not in plan.actions

    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    # the excluded file survived the tree swap untouched
    assert os.path.exists(excluded)
    assert read(excluded) == "cached-bytes\n"
    # and it stays out of the receipt (unmanaged, like never-synced files)
    receipt = json.loads(read(os.path.join(world["install"], sl.RECEIPT_NAME)))
    assert "scripts/__pycache__/local.pyc" not in receipt["files"]


# --------------------------------------------------------------------------- #
# BLOCKER 5b: the sibling lock blocks a concurrent second run through completion
# --------------------------------------------------------------------------- #
def test_sync_sibling_lock_blocks_concurrent_run(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)

    # a concurrent holder grabs the sibling lock and keeps it
    holder = sl.InstallLock(world["install"], force=False)
    holder.acquire()
    try:
        with pytest.raises(sl.LockHeld):
            sl.run_target(target, world["checkout"], dry_run=False, force=False)
        # the holder's lock was not stolen or removed by the blocked run
        assert os.path.exists(holder.path)
    finally:
        holder.release()
