"""Tests for scripts/sync_local.py.

Everything happens under tmp_path -- these tests NEVER touch the real skills
directory or any absolute machine path.
"""

from __future__ import annotations

import json
import os
import sys

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
def test_apply_installs_and_writes_receipt(world, tmp_path):
    target = make_target(world)
    sl.run_target(target, world["checkout"], dry_run=False, force=False)
    inst = world["install"]
    assert read(os.path.join(inst, "SKILL.md")) == "# overlay skill\n"
    assert read(os.path.join(inst, "references", "agents.yaml")) == "agents: OVERLAY\n"
    receipt = json.loads(read(os.path.join(inst, sl.RECEIPT_NAME)))
    assert receipt["files"]["SKILL.md"]["origin"] == "overlay"
    assert receipt["files"]["scripts/ctl.py"]["origin"] == "base"
    # a backup was produced only if install pre-existed; fresh install -> empty bak
    baks = [d for d in os.listdir(world["tmp"]) if d.startswith("install.bak-")]
    assert baks  # backup of the lock-only dir


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
        # --force steals it
        forced = sl.InstallLock(world["install"], force=True)
        forced.acquire()
        forced.release()
    finally:
        lock.release()
