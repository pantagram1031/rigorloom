"""Tests for the Stage 5 workspace snapshot and restore utility."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ws_snapshot.py"
SPEC = importlib.util.spec_from_file_location("ws_snapshot", SCRIPT)
ws_snapshot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ws_snapshot)


def run(*args: str, as_json: bool = True) -> tuple[dict | str, int]:
    command = [sys.executable, str(SCRIPT), *args]
    if as_json:
        command.append("--json")
    proc = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if not as_json:
        return proc.stdout, proc.returncode
    try:
        return json.loads(proc.stdout.strip()), proc.returncode
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"non-JSON stdout\nargs={args}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        ) from exc


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "report-demo"
    (workspace / "bundle" / "figures").mkdir(parents=True)
    (workspace / "bundle" / "content.md").write_text("frozen draft\n", encoding="utf-8")
    (workspace / "bundle" / "figures" / "figure.txt").write_text("figure\n", encoding="utf-8")
    (workspace / "output").mkdir()
    (workspace / "output" / "form_copy.hwpx").write_bytes(b"form-copy")
    (workspace / "PIPELINE.md").write_text("pipeline: stage-5\n", encoding="utf-8")
    (workspace / ".pipeline").mkdir()
    (workspace / ".pipeline" / "handoff.json").write_text('{"stage":"5"}\n', encoding="utf-8")
    return workspace


def write_sidecar(archive: Path) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )


def test_snapshot_zip_sidecar_exclusions_and_rotation(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    (workspace / "bundle" / "draft.bak").write_text("exclude", encoding="utf-8")
    (workspace / "output" / "old.bak").mkdir()
    (workspace / "output" / "old.bak" / "secret.txt").write_text("exclude", encoding="utf-8")
    (workspace / "output" / ".snapshots").mkdir()
    (workspace / "output" / ".snapshots" / "nested.zip").write_bytes(b"exclude")

    first, code = run("snapshot", str(workspace), "--keep", "2")
    assert code == 0
    archive_path = Path(first["snapshot"])
    sidecar = Path(first["sidecar"])
    assert archive_path.is_file()
    assert sidecar.read_text(encoding="utf-8").split()[0] == first["sha256"]
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
    assert "bundle/content.md" in names
    assert "output/form_copy.hwpx" in names
    assert "PIPELINE.md" in names
    assert ".pipeline/handoff.json" in names
    assert not any(name.endswith(".bak") or ".bak/" in name for name in names)
    assert not any(".snapshots/" in name for name in names)

    for _ in range(3):
        _, code = run("snapshot", str(workspace), "--keep", "2")
        assert code == 0
    snapshot_dir = workspace / ".snapshots"
    assert len(list(snapshot_dir.glob("pre-assembly-*.zip"))) == 2
    assert len(list(snapshot_dir.glob("pre-assembly-*.zip.sha256"))) == 2


def test_restore_onto_emptied_subtrees(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    payload, code = run("snapshot", str(workspace))
    assert code == 0

    shutil.rmtree(workspace / "bundle")
    shutil.rmtree(workspace / "output")
    (workspace / "bundle").mkdir()
    (workspace / "output").mkdir()
    (workspace / "PIPELINE.md").write_text("changed\n", encoding="utf-8")
    (workspace / ".pipeline" / "handoff.json").write_text("changed\n", encoding="utf-8")

    restored, code = run(
        "restore", str(workspace), "--snapshot", Path(payload["snapshot"]).name
    )
    assert code == 0
    assert restored["sha256_verified"] is True
    assert (workspace / "bundle" / "content.md").read_text(encoding="utf-8") == "frozen draft\n"
    assert (workspace / "output" / "form_copy.hwpx").read_bytes() == b"form-copy"
    assert (workspace / "PIPELINE.md").read_text(encoding="utf-8") == "pipeline: stage-5\n"
    assert json.loads((workspace / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))["stage"] == "5"


def test_restore_refuses_non_empty_without_force(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    payload, code = run("snapshot", str(workspace))
    assert code == 0
    marker = workspace / "output" / "current.txt"
    marker.write_text("keep\n", encoding="utf-8")

    refused, code = run("restore", str(workspace), "--snapshot", Path(payload["snapshot"]).name)
    assert code == 2
    assert "non-empty" in refused["error"]
    assert marker.read_text(encoding="utf-8") == "keep\n"


def test_force_preserves_pre_restore_copy(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    payload, code = run("snapshot", str(workspace))
    assert code == 0
    (workspace / "bundle" / "content.md").write_text("current draft\n", encoding="utf-8")
    (workspace / "output" / "current.txt").write_text("current output\n", encoding="utf-8")

    restored, code = run(
        "restore", str(workspace), "--snapshot", Path(payload["snapshot"]).name, "--force"
    )
    assert code == 0
    pre_restore = Path(restored["pre_restore_backup"])
    assert pre_restore.parent == workspace
    assert (pre_restore / "bundle" / "content.md").read_text(encoding="utf-8") == "current draft\n"
    assert (pre_restore / "output" / "current.txt").read_text(encoding="utf-8") == "current output\n"
    assert (workspace / "bundle" / "content.md").read_text(encoding="utf-8") == "frozen draft\n"


def test_hash_mismatch_is_hard_refusal(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    payload, code = run("snapshot", str(workspace))
    assert code == 0
    Path(payload["sidecar"]).write_text("0" * 64 + "  tampered.zip\n", encoding="utf-8")

    refused, code = run("restore", str(workspace), "--force")
    assert code == 3
    assert "sha256 mismatch" in refused["error"]
    assert (workspace / "bundle" / "content.md").exists()
    assert not list(workspace.glob(".pre-restore-*"))


def test_symlink_member_is_refused(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    snapshot_dir = workspace / ".snapshots"
    snapshot_dir.mkdir()
    malicious = snapshot_dir / "pre-assembly-20260714T000000Z.zip"
    link = zipfile.ZipInfo("bundle/linked")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("bundle/", b"")
        archive.writestr("output/", b"")
        archive.writestr("PIPELINE.md", "pipeline\n")
        archive.writestr(link, "outside")
    write_sidecar(malicious)

    refused, code = run("restore", str(workspace), "--snapshot", malicious.name, "--force")
    assert code == 3
    assert "symlink" in refused["error"].lower()


def test_zip_slip_member_is_refused(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    snapshot_dir = workspace / ".snapshots"
    snapshot_dir.mkdir()
    malicious = snapshot_dir / "pre-assembly-20260714T000001Z.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("bundle/", b"")
        archive.writestr("output/", b"")
        archive.writestr("PIPELINE.md", "pipeline\n")
        archive.writestr("bundle/../../escaped.txt", "must stay contained")
    write_sidecar(malicious)

    refused, code = run("restore", str(workspace), "--snapshot", malicious.name, "--force")
    assert code == 3
    assert "unsafe zip entry path" in refused["error"].lower()
    assert not (tmp_path / "escaped.txt").exists()


def test_preexisting_symlink_parent_is_refused_or_contained(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    payload, code = run("snapshot", str(workspace))
    assert code == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(workspace / "bundle")
    try:
        (workspace / "bundle").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    refused, code = run(
        "restore", str(workspace), "--snapshot", Path(payload["snapshot"]).name, "--force"
    )
    assert code == 3
    assert any(text in refused["error"].lower()
               for text in ("symlink", "escapes", "unsafe zip target directory"))
    assert not (outside / "content.md").exists()


def test_extract_refuses_preexisting_symlink_parent_directly(tmp_path: Path):
    target = tmp_path / "restored"
    actual = target / "actual"
    actual.mkdir(parents=True)
    linked = target / "bundle"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    archive_path = tmp_path / "safe-name.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("bundle/payload.txt", "must not follow the link")

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(
            ws_snapshot.IntegrityError,
            match="symlink|escapes|unsafe zip target directory",
        ):
            ws_snapshot._extract_members(archive, target)
    assert not (actual / "payload.txt").exists()


def test_extract_refuses_simulated_reparse_point_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "restored"
    marked_parent = target / "bundle"
    marked_parent.mkdir(parents=True)
    archive_path = tmp_path / "safe-reparse-test.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("bundle/payload.txt", "must not cross the reparse point")

    real_predicate = ws_snapshot._is_reparse_point
    marked_absolute = Path(os.path.abspath(marked_parent))

    def fake_is_reparse_point(path: Path) -> bool:
        return Path(os.path.abspath(path)) == marked_absolute or real_predicate(path)

    monkeypatch.setattr(ws_snapshot, "_is_reparse_point", fake_is_reparse_point)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ws_snapshot.IntegrityError, match="reparse point"):
            ws_snapshot._extract_members(archive, target)
    assert not (marked_parent / "payload.txt").exists()


def test_list_json_and_text_output(tmp_path: Path):
    workspace = make_workspace(tmp_path)
    for _ in range(2):
        _, code = run("snapshot", str(workspace), "--keep", "10")
        assert code == 0

    payload, code = run("list", str(workspace))
    assert code == 0
    assert len(payload["snapshots"]) == 2
    assert all(row["sha256_status"] == "ok" for row in payload["snapshots"])

    text, code = run("list", str(workspace), as_json=False)
    assert code == 0
    assert "pre-assembly-" in text
    assert "sha256=ok" in text
