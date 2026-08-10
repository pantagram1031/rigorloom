"""Synthetic T86 rhwp diagnostic-candidate contract tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from test_hwp_ingress import _cfb_hwp, _hwpx  # noqa: E402
import hwp_diagnostic_candidate as diagnostic  # noqa: E402


RUN_ID = "0123456789abcdef0123456789abcdef"


def _root(tmp_path: Path, label: str = "") -> Path:
    base = tmp_path / label if label else tmp_path
    base.mkdir(parents=True, exist_ok=True)
    root = base / "hwp-diagnostic"
    root.mkdir(exist_ok=True)
    return root


def _binary(root: Path, data: bytes = b"synthetic-rhwp") -> tuple[Path, str]:
    path = root / "rhwp.exe"
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _success_child(monkeypatch: pytest.MonkeyPatch, *, mutate_source: Path | None = None):
    calls: list[list[str]] = []
    snapshots: list[tuple[bytes, bytes]] = []

    def fake(argv, *, timeout, cwd=None):
        calls.append(list(argv))
        assert cwd is not None and Path(cwd) == Path(argv[0]).parent
        assert argv[1:] == ["export-hwpx", argv[2], argv[3], "--verify", "--verify-pages"]
        snapshots.append((Path(argv[0]).read_bytes(), Path(argv[2]).read_bytes()))
        _hwpx(Path(argv[3]))
        if mutate_source is not None:
            mutate_source.write_bytes(_cfb_hwp(version=(5, 1, 0, 1)))
        return 0, False, False

    monkeypatch.setattr(diagnostic, "_run_child_capture", fake)
    return calls, snapshots


def test_success_is_quarantined_and_argv_is_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    calls, snapshots = _success_child(monkeypatch)
    root = _root(tmp_path)
    result = diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["status"] == "candidate"
    assert result["adapter"] == "rhwp"
    assert result["execution"] == {"state": "succeeded", "binary_sha256": digest,
                                    "exit_code": 0}
    assert result["comparison"] == {
        "state": "unknown", "method": "none",
        "reason": "independent_oracle_not_run",
    }
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert result["output"]["state"] == "quarantined"
    assert result["output"]["path"] == f"{RUN_ID}/candidate.hwpx"
    assert not Path(result["output"]["path"]).is_absolute()
    assert set(result) == {
        "schema", "status", "reason", "adapter", "source", "execution",
        "comparison", "render", "proof_grade", "submission_grade", "output",
    }
    assert (root / RUN_ID / "candidate.hwpx").is_file()
    assert (root / RUN_ID / "receipt.json").is_file()
    assert calls and calls[0][0] != str(binary)
    assert snapshots[0][0] == binary.read_bytes()
    assert hashlib.sha256(snapshots[0][0]).hexdigest() == digest
    assert snapshots[0][1] == source.read_bytes()
    assert Path(calls[0][2]) != source
    assert Path(calls[0][3]).suffix == ".hwpx"
    assert not list(root.glob(".t86-*"))
    assert "stdout" not in json.dumps(result)
    assert "stderr" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("pin, reason", [(None, "rhwp_unpinned"), ("0" * 64, "rhwp_hash_mismatch")])
def test_pin_refusal_never_runs_or_creates_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              pin: str | None, reason: str):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    called = []
    monkeypatch.setattr(diagnostic, "_run_child_capture", lambda *args, **kwargs: called.append(True))
    result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path), run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=pin)
    assert result["status"] == "refused"
    assert result["reason"] == reason
    assert called == []
    assert not (_root(tmp_path, "pin-check") / RUN_ID).exists()


@pytest.mark.parametrize("return_value, reason", [
    ((7, False, False), "rhwp_failed"),
    ((-1, True, False), "rhwp_timeout"),
    ((-1, False, True), "rhwp_output_too_large"),
    ((False, [], {}), "rhwp_failed"),
])
def test_child_failure_leaves_no_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         return_value, reason: str):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    monkeypatch.setattr(diagnostic, "_run_child_capture", lambda *args, **kwargs: return_value)
    result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path), run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["status"] == "refused"
    assert result["reason"] == reason
    assert not (_root(tmp_path, "child-failure-check") / RUN_ID).exists()


def test_real_child_timeout_kills_grandchild_before_return(tmp_path: Path):
    """The timeout boundary owns descendants, not just the direct adapter."""
    marker = tmp_path / "late-sidecar.txt"
    pid_file = tmp_path / "grandchild.pid"
    grandchild_code = (
        "import pathlib,sys,time; time.sleep(1.5); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='ascii')"
    )
    parent_code = (
        "import pathlib,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[1]]); "
        "pathlib.Path(sys.argv[2]).write_text(str(p.pid), encoding='ascii'); "
        "time.sleep(8)"
    )
    code, timed_out, overflow = diagnostic._run_child_capture(
        [sys.executable, "-c", parent_code, str(marker), str(pid_file),
         grandchild_code],
        timeout=0.8, cwd=tmp_path,
    )
    assert type(code) is int
    assert timed_out is True
    assert overflow is False
    # The parent has a short startup window; once its PID record exists, wait
    # past the grandchild's delayed write and prove the sidecar never appears.
    deadline = time.monotonic() + 1.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    time.sleep(1.9)
    assert not marker.exists()


def test_missing_or_corrupt_output_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)

    monkeypatch.setattr(diagnostic, "_run_child_capture", lambda *args, **kwargs: (0, False, False))
    missing = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path, "missing"), run_id=RUN_ID,
                                        rhwp=binary, rhwp_sha256=digest)
    assert missing["reason"] == "rhwp_output_missing"
    assert not (_root(tmp_path, "missing") / RUN_ID).exists()

    def corrupt(argv, *, timeout, cwd=None):
        Path(argv[3]).write_bytes(b"not-hwpx")
        return 0, False, False

    monkeypatch.setattr(diagnostic, "_run_child_capture", corrupt)
    bad = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path, "bad"), run_id=RUN_ID,
                                    rhwp=binary, rhwp_sha256=digest)
    assert bad["reason"] == "hwpx_invalid"
    assert not (_root(tmp_path, "bad") / RUN_ID).exists()


def test_source_and_binary_drift_refuse_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    _success_child(monkeypatch, mutate_source=source)
    result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path, "source-drift"), run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "source_changed"
    assert not (_root(tmp_path, "source-drift") / RUN_ID).exists()

    source.write_bytes(_cfb_hwp())
    _success_child(monkeypatch)
    def drifted(*args, **kwargs):
        _hwpx(Path(args[0][3]))
        binary.write_bytes(b"changed-binary")
        return 0, False, False
    monkeypatch.setattr(diagnostic, "_run_child_capture", drifted)
    result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path, "binary-drift"), run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "rhwp_binary_drift"
    assert not (_root(tmp_path, "binary-drift") / RUN_ID).exists()


@pytest.mark.skipif(os.name == "nt", reason="FIFO paths are POSIX-only")
@pytest.mark.parametrize("kind", ["source", "binary"])
def test_live_path_fifo_swap_is_bounded_refusal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str):
    """A post-child source/binary path swap to a FIFO cannot block or publish."""
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    _success_child(monkeypatch)
    swapped = [False]
    if kind == "source":
        original_hash = diagnostic._hash_source

        def fifo_source(path: Path):
            if path == source and not swapped[0]:
                swapped[0] = True
                source.unlink()
                os.mkfifo(source)
            return original_hash(path)

        monkeypatch.setattr(diagnostic, "_hash_source", fifo_source)
        expected = "source_changed"
    else:
        original_hash = diagnostic._hash_binary

        def fifo_binary(path: Path):
            if path == binary and not swapped[0]:
                swapped[0] = True
                binary.unlink()
                os.mkfifo(binary)
            return original_hash(path)

        monkeypatch.setattr(diagnostic, "_hash_binary", fifo_binary)
        expected = "rhwp_binary_drift"
    root = _root(tmp_path, f"fifo-{kind}")
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert swapped[0] is True
    assert result["status"] == "refused"
    assert result["reason"] == expected
    assert not (root / RUN_ID).exists()


def test_existing_run_and_canonical_sentinels_are_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    existing = root / RUN_ID
    existing.mkdir(parents=True)
    (existing / "receipt.json").write_bytes(b"KEEP")
    canonical = tmp_path / "output"
    sentinels = [canonical / "form_copy.hwpx", canonical / "proof" / "ingress" / "receipt.json",
                 canonical / "proof" / "backend" / "receipt.json"]
    for path in sentinels:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"CANONICAL")
    _success_child(monkeypatch)
    result = diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "run_exists"
    assert (existing / "receipt.json").read_bytes() == b"KEEP"
    assert all(path.read_bytes() == b"CANONICAL" for path in sentinels)


def test_receipt_collision_preserves_foreign_writer_and_no_candidate(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_link = diagnostic.os.link

    def collide(receipt_source, receipt_target):
        if Path(receipt_target).name == "receipt.json":
            Path(receipt_target).write_bytes(b"FOREIGN")
            raise FileExistsError(receipt_target)
        return original_link(receipt_source, receipt_target)

    monkeypatch.setattr(diagnostic.os, "link", collide)
    result = diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "run_exists"
    assert (root / RUN_ID / "receipt.json").read_bytes() == b"FOREIGN"
    assert not (root / RUN_ID / "candidate.hwpx").exists()


@pytest.mark.parametrize("target_name, foreign", [
    ("receipt.json", b"FOREIGN-IN-PLACE-RECEIPT"),
    ("candidate.hwpx", b"FOREIGN-IN-PLACE-CANDIDATE"),
])
def test_same_inode_post_link_overwrite_never_false_green(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        target_name: str, foreign: bytes):
    """A hard-linked target can be overwritten in place without changing ino."""
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_link = diagnostic.os.link

    def overwrite(source_path, target_path):
        original_link(source_path, target_path)
        if Path(target_path).name == target_name:
            target = Path(target_path)
            target.chmod(0o600)
            target.write_bytes(foreign)

    monkeypatch.setattr(diagnostic.os, "link", overwrite)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["status"] == "refused"
    assert result["reason"] == "diagnostic_publish_failed"
    target = root / RUN_ID / target_name
    assert target.read_bytes() == foreign
    other = root / RUN_ID / ("candidate.hwpx" if target_name == "receipt.json"
                             else "receipt.json")
    assert not other.exists()


@pytest.mark.parametrize("fault_name", ["receipt.json", "candidate.hwpx"])
def test_post_link_identity_fault_rolls_back_only_our_files(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch,
                                                             fault_name: str):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_identity = diagnostic._node_identity
    raised = [False]

    def fault(path: Path):
        # Target checks are after each successful hard-link; staging checks
        # must still run so rollback knows the expected inode.
        if (path.name == fault_name and path.parent == root / RUN_ID
                and not raised[0]):
            raised[0] = True
            raise diagnostic.DiagnosticError("diagnostic_publish_failed")
        return original_identity(path)

    monkeypatch.setattr(diagnostic, "_node_identity", fault)
    result = diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "diagnostic_publish_failed"
    assert not (root / RUN_ID / "receipt.json").exists()
    assert not (root / RUN_ID / "candidate.hwpx").exists()


def test_foreign_owner_token_is_preserved_on_final_commit_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A replaced ownership token must stop rollback from deleting its run dir."""
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_remove = diagnostic._remove_owned
    replaced = [False]

    def replace_token(path: Path, identity):
        if (path.parent == root / RUN_ID and path.name.startswith(".t86-owner-")
                and not replaced[0]):
            replaced[0] = True
            path.unlink()
            path.write_bytes(b"FOREIGN-TOKEN")
        return original_remove(path, identity)

    monkeypatch.setattr(diagnostic, "_remove_owned", replace_token)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["status"] == "refused"
    assert result["reason"] == "diagnostic_publish_failed"
    run_path = root / RUN_ID
    assert run_path.is_dir()
    assert not (run_path / "receipt.json").exists()
    assert not (run_path / "candidate.hwpx").exists()
    tokens = list(run_path.glob(".t86-owner-*"))
    assert len(tokens) == 1 and tokens[0].read_bytes() == b"FOREIGN-TOKEN"


def test_owner_token_creation_failure_keeps_only_empty_reservation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Without an ownership token, cleanup must preserve the empty directory."""
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_write = diagnostic._write_bytes

    def fail_token(path: Path, data: bytes):
        if path.parent == root / RUN_ID and path.name.startswith(".t86-owner-"):
            raise diagnostic.DiagnosticError("diagnostic_write_failed")
        return original_write(path, data)

    monkeypatch.setattr(diagnostic, "_write_bytes", fail_token)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["status"] == "refused"
    assert result["reason"] == "diagnostic_write_failed"
    run_path = root / RUN_ID
    assert run_path.is_dir()
    assert list(run_path.iterdir()) == []


def test_verify_binds_receipt_to_current_output_and_rejects_duplicate_or_foreign(tmp_path: Path,
                                                                                   monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    created = diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                                        rhwp=binary, rhwp_sha256=digest)
    assert diagnostic.verify_diagnostic(root, RUN_ID)["status"] == "candidate"
    output = root / RUN_ID / "candidate.hwpx"
    with zipfile.ZipFile(output) as original:
        members = {name: original.read(name) for name in original.namelist()}
    members["Contents/section0.xml"] = b"<sec><p><t>DRIFT</t></p></sec>"
    output.chmod(0o600)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as rebuilt:
        for name, value in members.items():
            rebuilt.writestr(name, value)
    assert diagnostic.verify_diagnostic(root, RUN_ID)["reason"] == "receipt_output_mismatch"

    receipt = root / RUN_ID / "receipt.json"
    receipt.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    assert diagnostic.verify_diagnostic(root, RUN_ID)["reason"] == "receipt_duplicate_key"


def test_receipt_nested_keysets_and_unknown_fields_are_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                              rhwp=binary, rhwp_sha256=digest)
    receipt = root / RUN_ID / "receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert set(payload["source"]) == {"format", "version", "bytes", "sha256", "compressed", "security_flags"}
    assert set(payload["execution"]) == {"state", "binary_sha256", "exit_code"}
    assert set(payload["comparison"]) == {"state", "method", "reason"}
    assert set(payload["output"]) == {"state", "path", "sha256", "bytes", "counts"}
    payload["foreign"] = True
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert diagnostic.verify_diagnostic(root, RUN_ID)["reason"] == "receipt_schema_invalid"


def test_output_drift_after_first_validation_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    calls, _ = _success_child(monkeypatch)
    original_validate = diagnostic._validate_hwpx_current
    count = [0]

    def mutate_after_validation(path: Path):
        result = original_validate(path)
        count[0] += 1
        if count[0] == 1:
            with zipfile.ZipFile(path) as original:
                members = {name: original.read(name) for name in original.namelist()}
            members["Contents/section0.xml"] = b"<sec><p><t>OUTPUT-DRIFT</t></p></sec>"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as rebuilt:
                for name, value in members.items():
                    rebuilt.writestr(name, value)
        return result

    monkeypatch.setattr(diagnostic, "_validate_hwpx_current", mutate_after_validation)
    result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path, "drift"), run_id=RUN_ID,
                                       rhwp=binary, rhwp_sha256=digest)
    assert result["reason"] == "rhwp_output_drift"
    assert not (_root(tmp_path, "drift") / RUN_ID).exists()


def test_cli_verify_success_then_drift_is_exit_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                              rhwp=binary, rhwp_sha256=digest)
    ok = subprocess.run([sys.executable, str(SCRIPTS / "hwp_diagnostic_candidate.py"), "verify",
                         "--diagnostic-root", str(root), "--run-id", RUN_ID],
                        capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["status"] == "candidate"
    output = root / RUN_ID / "candidate.hwpx"
    with zipfile.ZipFile(output) as original:
        members = {name: original.read(name) for name in original.namelist()}
    members["Contents/section0.xml"] = b"<sec><p><t>CLI-DRIFT</t></p></sec>"
    output.chmod(0o600)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as rebuilt:
        for name, value in members.items():
            rebuilt.writestr(name, value)
    drift = subprocess.run([sys.executable, str(SCRIPTS / "hwp_diagnostic_candidate.py"), "verify",
                            "--diagnostic-root", str(root), "--run-id", RUN_ID],
                           capture_output=True, text=True, encoding="utf-8")
    assert drift.returncode == 3
    assert json.loads(drift.stdout)["reason"] == "receipt_output_mismatch"


def test_run_id_is_opaque_and_cli_has_closed_usage(tmp_path: Path):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    for run_id in ("friendly-label", "../escape", ".", "ABCDEF0123456789"):
        result = diagnostic.run_diagnostic(source, diagnostic_root=_root(tmp_path), run_id=run_id,
                                           rhwp=binary, rhwp_sha256=digest)
        assert result["reason"] == "run_id_invalid"
    help_result = subprocess.run([sys.executable, str(SCRIPTS / "hwp_diagnostic_candidate.py"), "--help"],
                                 capture_output=True, text=True, encoding="utf-8")
    assert help_result.returncode == 0
    assert "rhwp" in help_result.stdout.lower()


def test_staged_binary_uses_fixed_non_special_mode(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    try:
        binary.chmod(0o4755)
    except OSError:
        pytest.skip("filesystem does not support chmod")
    observed: list[int] = []
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int, *args, **kwargs):
        if path.name.startswith("rhwp"):
            observed.append(mode)
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", record_chmod)

    def child(argv, *, timeout, cwd=None):
        _hwpx(Path(argv[3]))
        return 0, False, False

    monkeypatch.setattr(diagnostic, "_run_child_capture", child)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["status"] == "candidate"
    # Windows ACL-backed mode reporting can show 0777 even after chmod; the
    # security property is the fixed chmod request itself.
    assert observed == [0o700]


@pytest.mark.parametrize("bad_timeout", [0, -1, float("nan"), float("inf"), None, True])
def test_invalid_timeout_is_closed_refusal(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch,
                                           bad_timeout):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    called = []
    monkeypatch.setattr(diagnostic, "_run_child_capture",
                        lambda *args, **kwargs: called.append(True))
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest, timeout=bad_timeout,
    )
    assert result["status"] == "refused"
    assert result["reason"] == "timeout_invalid"
    assert called == []


@pytest.mark.parametrize("bad_input,bad_root,bad_binary", [(None, "x", "x"), ("x", None, "x"), ("x", "x", None)])
def test_invalid_direct_api_paths_are_closed_refusal(tmp_path: Path, bad_input, bad_root, bad_binary):
    result = diagnostic.run_diagnostic(
        bad_input, diagnostic_root=bad_root, run_id=RUN_ID,
        rhwp=bad_binary, rhwp_sha256="0" * 64,
    )
    assert result["status"] == "refused"
    assert result["reason"] in {"diagnostic_io_failed", "input_unavailable", "rhwp_binary_unavailable"}


def test_cli_refusal_is_exit_three(tmp_path: Path):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    result = subprocess.run([sys.executable, str(SCRIPTS / "hwp_diagnostic_candidate.py"), "run",
                             str(source), "--diagnostic-root", str(_root(tmp_path)),
                             "--run-id", RUN_ID, "--rhwp", str(tmp_path / "missing.exe"),
                             "--rhwp-sha256", "0" * 64], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "refused"
    assert "path" not in json.dumps(payload).lower()


def test_diagnostic_root_is_precreated_exact_leaf_and_not_output(tmp_path: Path):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    for root in (tmp_path / "not-created", tmp_path / "wrong-leaf"):
        if root.name == "wrong-leaf":
            root.mkdir()
        result = diagnostic.run_diagnostic(
            source, diagnostic_root=root, run_id=RUN_ID,
            rhwp=binary, rhwp_sha256=digest,
        )
        assert result["reason"] == "diagnostic_root_invalid"
    output_root = tmp_path / "output" / "hwp-diagnostic"
    output_root.mkdir(parents=True)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=output_root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] == "diagnostic_root_invalid"


def test_diagnostic_root_rejects_symlinked_ancestor(tmp_path: Path):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    link_parent = tmp_path / "link-parent"
    try:
        link_parent.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    root = link_parent / "hwp-diagnostic"
    root.mkdir()
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] == "diagnostic_root_invalid"


def test_root_swap_to_output_symlink_after_prepare_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    original_check = diagnostic._check_root_guard
    calls = [0]

    def swap_after_refresh(guard, *, refresh=False):
        result = original_check(guard, refresh=refresh)
        calls[0] += 1
        if calls[0] == 2:
            moved = tmp_path / "reserved-root"
            root.rename(moved)
            replacement = output / "hwp-diagnostic"
            replacement.mkdir()
            try:
                root.symlink_to(replacement, target_is_directory=True)
            except (OSError, NotImplementedError):
                moved.rename(root)
                pytest.skip("directory symlinks unavailable")
        return result

    monkeypatch.setattr(diagnostic, "_check_root_guard", swap_after_refresh)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] in {"diagnostic_root_changed", "diagnostic_write_failed"}
    assert not (output / "hwp-diagnostic" / RUN_ID).exists()


def test_root_swap_to_foreign_real_directory_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    original_check = diagnostic._check_root_guard
    calls = [0]

    def swap_after_refresh(guard, *, refresh=False):
        result = original_check(guard, refresh=refresh)
        calls[0] += 1
        if calls[0] == 2:
            moved = tmp_path / "reserved-real-root"
            root.rename(moved)
            root.mkdir()
        return result

    monkeypatch.setattr(diagnostic, "_check_root_guard", swap_after_refresh)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] in {"diagnostic_root_changed", "diagnostic_write_failed"}
    assert not (root / RUN_ID).exists()


def test_last_precommit_guard_failure_rolls_back_before_token_commit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    root = _root(tmp_path)
    _success_child(monkeypatch)
    original_check = diagnostic._check_root_guard
    calls = [0]

    def fail_last_guard(guard, *, refresh=False):
        calls[0] += 1
        if calls[0] == 7 and not refresh:
            raise diagnostic.DiagnosticError("diagnostic_root_changed")
        return original_check(guard, refresh=refresh)

    monkeypatch.setattr(diagnostic, "_check_root_guard", fail_last_guard)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] == "diagnostic_root_changed"
    assert not (root / RUN_ID).exists()


def test_source_binary_and_root_roles_are_distinct(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _success_child(monkeypatch)
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=_root(tmp_path), run_id=RUN_ID,
        rhwp=source, rhwp_sha256=digest,
    )
    assert result["reason"] == "paths_not_distinct"


def test_staged_source_rehash_before_commit_closes_mutation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    _success_child(monkeypatch)
    original_hash = diagnostic._hash_source
    mutated = [False]

    def mutate_staged(path: Path):
        result = original_hash(path)
        if path.name == "input.hwp" and not mutated[0]:
            mutated[0] = True
            path.write_bytes(_cfb_hwp(version=(5, 1, 0, 1)))
        return result

    monkeypatch.setattr(diagnostic, "_hash_source", mutate_staged)
    root = _root(tmp_path, "staged-source-drift")
    result = diagnostic.run_diagnostic(
        source, diagnostic_root=root, run_id=RUN_ID,
        rhwp=binary, rhwp_sha256=digest,
    )
    assert result["reason"] == "source_changed"
    assert not (root / RUN_ID).exists()


def test_verify_rejects_external_hardlink_alias(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    _success_child(monkeypatch)
    root = _root(tmp_path)
    diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                              rhwp=binary, rhwp_sha256=digest)
    alias = tmp_path / "receipt-alias.json"
    try:
        os.link(root / RUN_ID / "receipt.json", alias)
    except OSError:
        pytest.skip("hard links unavailable")
    assert diagnostic.verify_diagnostic(root, RUN_ID)["reason"] == "receipt_invalid"


def test_verify_rejects_receipt_symlink_without_following(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.hwp"
    source.write_bytes(_cfb_hwp())
    binary, digest = _binary(tmp_path)
    _success_child(monkeypatch)
    root = _root(tmp_path)
    diagnostic.run_diagnostic(source, diagnostic_root=root, run_id=RUN_ID,
                              rhwp=binary, rhwp_sha256=digest)
    receipt = root / RUN_ID / "receipt.json"
    foreign = tmp_path / "foreign-receipt.json"
    foreign.write_bytes(receipt.read_bytes())
    receipt.unlink()
    try:
        receipt.symlink_to(foreign)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks unavailable")
    assert diagnostic.verify_diagnostic(root, RUN_ID)["reason"] == "receipt_invalid"
