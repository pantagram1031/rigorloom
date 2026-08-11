"""Red contract tests for the quarantine-only renderer runtime v2 lane.

The runtime owns its run directory and source/output layout.  These tests are
deliberately written before the implementation so a generic caller-supplied
command or output path cannot accidentally satisfy the contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
TESTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import renderer_runtime_v2 as runtime  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


RUN_ID = "0123456789abcdef"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _output_root(workspace: Path) -> Path:
    return workspace / "output" / "proof" / "renderer-runtime-v2"


def _fixture(tmp_path: Path):
    binary = tmp_path / "renderer.bin"
    binary.write_bytes(b"renderer-runtime-v2\n")
    workspace = tmp_path / "workspace"
    source = workspace / "output" / "out.hwpx"
    write_hwpx(source, body="Runtime fixture")
    # The T150 lane is deliberately equation-free.  Keep the shared fixture's
    # otherwise useful package structure, replacing its synthetic equation
    # control with ordinary text while preserving the physical mimetype entry.
    members: list[tuple[zipfile.ZipInfo, bytes]] = []
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "Contents/section0.xml":
                data = data.replace(
                    b'<hp:equation id="10"><hp:script>x over y</hp:script></hp:equation>',
                    b'<hp:t>formula omitted</hp:t>')
            members.append((info, data))
    tmp_source = source.with_suffix(".rewritten.hwpx")
    with zipfile.ZipFile(tmp_source, "w") as archive:
        for info, data in members:
            archive.writestr(info, data)
    tmp_source.replace(source)
    _output_root(workspace).mkdir(parents=True)
    certificate = tmp_path / "certificate.json"
    certificate.write_bytes(b"opaque-certificate\n")
    return binary, source, certificate, workspace


def _run_args(binary: Path, source: Path, output: Path) -> tuple[list[str], list[str]]:
    return (
        [str(binary), "--version"],
        [str(binary), "export-pdf", str(source), "-o", str(output)],
    )


def _evidence(data: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _install_success_renderer(monkeypatch, fitz):
    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        if "--version" in argv:
            stdout, stderr = b"rhwp 0.0-test\n", b""
        else:
            document = fitz.open()
            document.new_page()
            Path(argv[-1]).write_bytes(document.tobytes())
            document.close()
            stdout, stderr = b"", b""
        result = (0, False, False)
        if return_evidence:
            return result + ({"output": _evidence(stdout),
                              "error": _evidence(stderr)},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)


def test_runtime_receipt_binds_staged_execution_and_all_artifacts(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)
    calls: list[list[str]] = []
    fitz = pytest.importorskip("fitz")
    version_output = b"rhwp 0.0-test\n"

    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        calls.append(list(argv))
        if "--version" not in argv:
            output = Path(argv[-1]) if argv[-2] == "-o" else Path(argv[-1])
            document = fitz.open()
            document.new_page()
            output.write_bytes(document.tobytes())
            document.close()
            stdout, stderr = b"", b""
        else:
            stdout, stderr = version_output, b""
        result = (0, False, False)
        if return_evidence:
            return result + ({"output": _evidence(stdout),
                              "error": _evidence(stderr)},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)
    payload = runtime.execute_runtime(
        workspace=workspace,
        run_id=RUN_ID,
        renderer_id="rhwp_pdf",
        binary=binary,
        binary_sha256=_sha(binary),
        certificate_path=certificate,
        certificate_sha256=_sha(certificate),
        timeout=5.0,
    )

    run_dir = _output_root(workspace) / RUN_ID
    output = run_dir / "artifact.pdf"
    assert payload["schema"] == runtime.SCHEMA
    assert payload["status"] == "analyzed"
    assert payload["proof_grade"] == "none"
    assert payload["submission_grade"] is False
    assert payload["promotion"] == "not_run"
    assert payload["dependency_closure"] == "unknown"
    assert payload["execution"]["state"] == "succeeded"
    assert payload["execution"]["binary_sha256"] == _sha(binary)
    assert payload["execution"]["argv_sha256"]
    assert payload["execution"]["version_probe"]["state"] == "succeeded"
    assert payload["execution"]["version_probe"]["stdout"] == _evidence(version_output)
    assert payload["input"]["sha256"] == _sha(source)
    assert payload["input"]["format"] == "hwpx"
    assert payload["output"]["sha256"] == _sha(output)
    assert payload["output"]["format"] == "pdf"
    assert payload["output"]["pages"] >= 1
    assert payload["certificate"]["sha256"] == _sha(certificate)
    assert payload["certificate"]["validation"] == "not_run"
    assert payload["render"]["state"] == "not_run"
    assert calls[0][1:] == ["--version"]
    assert calls[1][1] == "export-pdf"
    assert calls[1][3] == "-o"
    assert Path(calls[0][0]).name != binary.name
    assert Path(calls[1][0]).name == Path(calls[0][0]).name
    assert Path(calls[1][2]).name == "input.hwpx"
    assert Path(calls[1][4]).name == "artifact.pdf"
    with fitz.open(output) as document:
        assert document.page_count >= 1
    receipt = run_dir / "receipt.json"
    raw = receipt.read_text(encoding="utf-8")
    assert str(tmp_path) not in raw
    assert json.loads(raw) == payload
    assert output.stat().st_nlink == 1
    assert receipt.stat().st_nlink == 1


def test_runtime_creates_fresh_owned_run_dir_and_rejects_stale_output(tmp_path):
    binary, source, certificate, workspace = _fixture(tmp_path)
    run_dir = _output_root(workspace) / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "artifact.pdf").write_bytes(b"stale")
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace,
            run_id=RUN_ID,
            renderer_id="rhwp_pdf",
            binary=binary,
            binary_sha256=_sha(binary),
            certificate_path=certificate,
            certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "run_exists"
    assert not (run_dir / "receipt.json").exists()


def test_runtime_rebinds_source_after_publication(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)
    fitz = pytest.importorskip("fitz")

    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        if "--version" not in argv:
            output = Path(argv[-1])
            document = fitz.open()
            document.new_page()
            output.write_bytes(document.tobytes())
            document.close()
            stdout = b""
        else:
            stdout = b"rhwp 0.0-test\n"
        result = (0, False, False)
        return result + ({"output": _evidence(stdout), "error": _evidence(b"")},) if return_evidence else result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)
    runtime.execute_runtime(
        workspace=workspace,
        run_id=RUN_ID,
            renderer_id="rhwp_pdf",
        binary=binary,
        binary_sha256=_sha(binary),
        certificate_path=certificate,
        certificate_sha256=_sha(certificate),
        timeout=5.0,
    )
    source.write_bytes(b"source-mutated-after-run")
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.verify_runtime(
            workspace=workspace,
            run_id=RUN_ID,
            binary=binary,
            certificate_path=certificate,
        )
    assert exc.value.reason in {"input_changed", "artifact_changed"}


def test_runtime_refuses_equation_bearing_input_before_child(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)
    # Replace the equation-free source with the shared helper's real equation
    # control.  The refusal must occur before any renderer invocation.
    write_hwpx(source, body="Equation fixture")
    calls: list[list[str]] = []
    monkeypatch.setattr(runtime, "_run_child_capture",
                        lambda argv, **kwargs: calls.append(list(argv)))
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace,
            run_id=RUN_ID,
            renderer_id="rhwp_pdf",
            binary=binary,
            binary_sha256=_sha(binary),
            certificate_path=certificate,
            certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "equation_input_unsupported"
    assert calls == []
    assert not (_output_root(workspace) / RUN_ID).exists()


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"binary_sha256": "0" * 64}, "binary_hash_mismatch"),
        ({"certificate_sha256": "f" * 64}, "certificate_hash_mismatch"),
        ({"renderer_id": "unknown"}, "renderer_id_invalid"),
    ],
)
def test_runtime_closed_pins_refuse_without_receipt(tmp_path, kwargs, reason):
    binary, source, certificate, workspace = _fixture(tmp_path)
    args = {
        "workspace": workspace,
        "run_id": RUN_ID,
        "renderer_id": "rhwp_pdf",
        "binary": binary,
        "binary_sha256": _sha(binary),
        "certificate_path": certificate,
        "certificate_sha256": _sha(certificate),
        "timeout": 5.0,
    }
    args.update(kwargs)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(**args)
    assert exc.value.reason == reason
    assert not (_output_root(workspace) / RUN_ID).exists()


def test_runtime_refuses_hardlinked_binary_before_child(tmp_path):
    binary, source, certificate, workspace = _fixture(tmp_path)
    alias = tmp_path / "renderer-alias.bin"
    alias.hardlink_to(binary)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace,
            run_id=RUN_ID,
            renderer_id="rhwp_pdf",
            binary=alias,
            binary_sha256=_sha(binary),
            certificate_path=certificate,
            certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "binary_unavailable"
    assert not (_output_root(workspace) / RUN_ID).exists()


@pytest.mark.parametrize("drift", ["source", "binary", "certificate"])
def test_runtime_rebinds_each_live_dependency_before_publication(
    tmp_path, monkeypatch, drift,
):
    binary, source, certificate, workspace = _fixture(tmp_path)
    fitz = pytest.importorskip("fitz")
    calls = []

    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        calls.append(list(argv))
        if len(calls) == 1:
            if drift == "source":
                source.write_bytes(b"source drift")
            elif drift == "binary":
                binary.write_bytes(b"binary drift")
            else:
                certificate.write_bytes(b"certificate drift")
            stdout = b"rhwp 0.0-test\n"
        else:
            document = fitz.open()
            document.new_page()
            Path(argv[-1]).write_bytes(document.tobytes())
            document.close()
            stdout = b""
        result = (0, False, False)
        if return_evidence:
            return result + ({"output": _evidence(stdout),
                              "error": _evidence(b"")},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=binary, binary_sha256=_sha(binary),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == {
        "source": "input_changed", "binary": "binary_changed",
        "certificate": "certificate_changed",
    }[drift]
    assert not (_output_root(workspace) / RUN_ID).exists()


def test_runtime_refuses_invalid_pdf_and_leaves_no_receipt(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)

    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        stdout = b"rhwp 0.0-test\n" if "--version" in argv else b""
        if "--version" not in argv:
            Path(argv[-1]).write_bytes(b"not a pdf")
        result = (0, False, False)
        if return_evidence:
            return result + ({"output": _evidence(stdout),
                              "error": _evidence(b"")},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=binary, binary_sha256=_sha(binary),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "artifact_invalid"
    assert not (_output_root(workspace) / RUN_ID).exists()


def test_runtime_refuses_timeout_before_publication(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)

    def timeout_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del argv, timeout, cwd, env
        result = (0, True, False)
        if return_evidence:
            return result + ({"output": _evidence(b""),
                              "error": _evidence(b"")},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", timeout_run)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=binary, binary_sha256=_sha(binary),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "version_timeout"
    assert not (_output_root(workspace) / RUN_ID).exists()


def test_runtime_rejects_root_overlap_and_symlink_root(tmp_path):
    binary, source, certificate, workspace = _fixture(tmp_path)
    root = _output_root(workspace)
    inside = root / "renderer.bin"
    inside.write_bytes(binary.read_bytes())
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=inside, binary_sha256=_sha(inside),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "paths_not_distinct"
    assert not (root / RUN_ID).exists()
    inside.unlink()

    outside = tmp_path / "outside"
    outside.mkdir()
    root.rmdir()
    try:
        root.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=binary, binary_sha256=_sha(binary),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "runtime_root_invalid"


def test_runtime_verify_rejects_forged_promotion_and_receipt_extra_file(
    tmp_path, monkeypatch,
):
    binary, source, certificate, workspace = _fixture(tmp_path)
    fitz = pytest.importorskip("fitz")

    def fake_run(argv, *, timeout, cwd=None, env=None, return_evidence=False):
        del timeout, cwd, env
        stdout = b"rhwp 0.0-test\n" if "--version" in argv else b""
        if "--version" not in argv:
            document = fitz.open()
            document.new_page()
            Path(argv[-1]).write_bytes(document.tobytes())
            document.close()
        result = (0, False, False)
        if return_evidence:
            return result + ({"output": _evidence(stdout),
                              "error": _evidence(b"")},)
        return result

    monkeypatch.setattr(runtime, "_run_child_capture", fake_run)
    runtime.execute_runtime(
        workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
        binary=binary, binary_sha256=_sha(binary),
        certificate_path=certificate, certificate_sha256=_sha(certificate),
        timeout=5.0,
    )
    receipt = _output_root(workspace) / RUN_ID / "receipt.json"
    forged = json.loads(receipt.read_text(encoding="utf-8"))
    forged["proof_grade"] = "certified"
    receipt.write_text(json.dumps(forged, sort_keys=True) + "\n",
                       encoding="utf-8")
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.verify_runtime(workspace=workspace, run_id=RUN_ID,
                               binary=binary, certificate_path=certificate)
    assert exc.value.reason in {"receipt_state_invalid", "receipt_changed",
                                "receipt_not_canonical"}
    (receipt.parent / "unexpected").write_bytes(b"x")
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.verify_runtime(workspace=workspace, run_id=RUN_ID,
                               binary=binary, certificate_path=certificate)
    assert exc.value.reason == "receipt_layout_invalid"


def test_verify_final_receipt_seam_mutating_artifact_is_refused(tmp_path, monkeypatch):
    binary, source, certificate, workspace = _fixture(tmp_path)
    fitz = pytest.importorskip("fitz")
    _install_success_renderer(monkeypatch, fitz)
    runtime.execute_runtime(
        workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
        binary=binary, binary_sha256=_sha(binary),
        certificate_path=certificate, certificate_sha256=_sha(certificate),
        timeout=5.0,
    )
    artifact = _output_root(workspace) / RUN_ID / "artifact.pdf"
    original_read = runtime._read_receipt
    calls = {"count": 0}

    def read_then_mutate(path, *, allow_hardlink=False, run_id=None):
        result = original_read(path, allow_hardlink=allow_hardlink,
                               run_id=run_id)
        calls["count"] += 1
        if calls["count"] == 2:
            replacement = fitz.open()
            replacement.new_page()
            replacement.new_page()
            with artifact.open("wb") as stream:
                stream.write(replacement.tobytes())
            replacement.close()
        return result

    monkeypatch.setattr(runtime, "_read_receipt", read_then_mutate)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.verify_runtime(workspace=workspace, run_id=RUN_ID,
                               binary=binary, certificate_path=certificate)
    assert calls["count"] == 2
    assert exc.value.reason in {"receipt_changed", "artifact_changed"}


def test_output_binding_blocks_check_to_open_parent_swap(tmp_path, monkeypatch):
    _, source, _, workspace = _fixture(tmp_path)
    layout = runtime._prepare_layout(workspace)
    output_binding = layout[-2]
    root_binding = layout[-1]
    output = workspace / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "out.hwpx").write_bytes(b"outside-source")
    moved = workspace / "output.moved"
    original_check = output_binding.check
    original_open = output_binding.open_file
    swapped = {"value": False}

    def no_op_check():
        return None

    def swap_then_open(name, flags, mode=0o600):
        try:
            output.rename(moved)
            output.symlink_to(outside, target_is_directory=True)
            swapped["value"] = True
        except (OSError, NotImplementedError):
            return original_open(name, flags, mode)
        try:
            return original_open(name, flags, mode)
        finally:
            output.unlink()
            moved.rename(output)

    output_binding.check = no_op_check
    output_binding.open_file = swap_then_open
    try:
        if swapped["value"]:
            with pytest.raises(runtime.RuntimeRefusal):
                runtime._capture_file(
                    source, runtime.MAX_INPUT_BYTES, "input_changed",
                    binding=output_binding, relative_name="out.hwpx")
        else:
            captured = runtime._capture_file(
                source, runtime.MAX_INPUT_BYTES, "input_changed",
                binding=output_binding, relative_name="out.hwpx")
            assert captured["data"] == source.read_bytes()
    finally:
        output_binding.check = original_check
        output_binding.open_file = original_open
        output_binding.close()
        root_binding.close()
        if moved.exists() and not output.exists():
            moved.rename(output)
    assert (outside / "out.hwpx").read_bytes() == b"outside-source"


@pytest.mark.parametrize("raise_before_cleanup", [False, True])
def test_postcommit_cleanup_fault_does_not_retract_public_pair(
    tmp_path, monkeypatch, raise_before_cleanup,
):
    binary, source, certificate, workspace = _fixture(tmp_path)
    fitz = pytest.importorskip("fitz")
    _install_success_renderer(monkeypatch, fitz)
    real_temporary_directory = tempfile.TemporaryDirectory

    class FaultyTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.inner = real_temporary_directory(*args, **kwargs)

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, exc_type, exc, tb):
            if raise_before_cleanup:
                raise OSError("injected cleanup fault")
            self.inner.__exit__(exc_type, exc, tb)
            raise OSError("injected cleanup fault")

    monkeypatch.setattr(
        runtime, "tempfile",
        types.SimpleNamespace(TemporaryDirectory=FaultyTemporaryDirectory),
    )
    payload = runtime.execute_runtime(
        workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
        binary=binary, binary_sha256=_sha(binary),
        certificate_path=certificate, certificate_sha256=_sha(certificate),
        timeout=5.0,
    )
    run_dir = _output_root(workspace) / RUN_ID
    assert payload["status"] == "analyzed"
    assert (run_dir / "artifact.pdf").stat().st_nlink == 1
    assert (run_dir / "receipt.json").stat().st_nlink == 1
    monkeypatch.setattr(runtime, "tempfile",
                        types.SimpleNamespace(
                            TemporaryDirectory=real_temporary_directory))
    assert runtime.verify_runtime(
        workspace=workspace, run_id=RUN_ID,
        binary=binary, certificate_path=certificate)["status"] == "analyzed"


def test_failed_stale_run_preserves_unrelated_foreign_files(tmp_path):
    binary, source, certificate, workspace = _fixture(tmp_path)
    run_dir = _output_root(workspace) / RUN_ID
    run_dir.mkdir(parents=True)
    foreign_artifact = b"foreign-artifact"
    foreign_receipt = b"foreign-receipt"
    (run_dir / "artifact.pdf").write_bytes(foreign_artifact)
    (run_dir / "receipt.json").write_bytes(foreign_receipt)
    with pytest.raises(runtime.RuntimeRefusal) as exc:
        runtime.execute_runtime(
            workspace=workspace, run_id=RUN_ID, renderer_id="rhwp_pdf",
            binary=binary, binary_sha256=_sha(binary),
            certificate_path=certificate, certificate_sha256=_sha(certificate),
            timeout=5.0,
        )
    assert exc.value.reason == "run_exists"
    assert (run_dir / "artifact.pdf").read_bytes() == foreign_artifact
    assert (run_dir / "receipt.json").read_bytes() == foreign_receipt


def test_cli_help_usage_and_refusal_are_closed_under_cp949(tmp_path):
    script = SCRIPTS / "renderer_runtime_v2.py"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp949"
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, encoding="cp949", env=env,
    )
    assert help_result.returncode == 0
    assert "renderer-runtime-v2" in help_result.stdout
    assert "Traceback" not in help_result.stderr

    secret = str(tmp_path / "PRIVATE" / "secret.hwpx")
    usage = subprocess.run(
        [sys.executable, str(script), "--not-a-real-option", secret],
        capture_output=True, text=True, encoding="cp949", env=env,
    )
    assert usage.returncode == runtime.EXIT_USAGE
    assert secret not in usage.stdout
    assert secret not in usage.stderr
    assert str(script.parent) not in usage.stderr
    assert "invalid arguments" in usage.stderr

    refusal = subprocess.run(
        [
            sys.executable, str(script), "inspect", secret,
            "--run-id", RUN_ID, "--renderer-id", "rhwp_pdf",
            "--binary", secret, "--binary-sha256", "0" * 64,
            "--certificate", secret, "--certificate-sha256", "0" * 64,
        ],
        capture_output=True, text=True, encoding="cp949", env=env,
    )
    assert refusal.returncode == runtime.EXIT_REFUSED
    payload = json.loads(refusal.stdout)
    assert payload["status"] == "refused"
    assert payload["proof_grade"] == "none"
    assert payload["submission_grade"] is False
    assert secret not in refusal.stdout
    assert secret not in refusal.stderr
    assert "Traceback" not in refusal.stderr


def test_cli_analyzed_result_still_uses_quarantine_exit_three(
    monkeypatch, capsys,
):
    analyzed = {
        "schema": runtime.SCHEMA,
        "status": "analyzed",
        "proof_grade": "none",
        "submission_grade": False,
        "promotion": "not_run",
    }
    monkeypatch.setattr(runtime, "execute_runtime", lambda **kwargs: analyzed)
    code = runtime.main([
        "inspect", "workspace", "--run-id", RUN_ID,
        "--renderer-id", "rhwp_pdf", "--binary", "renderer",
        "--binary-sha256", "0" * 64, "--certificate", "certificate",
        "--certificate-sha256", "0" * 64,
    ])
    assert code == runtime.EXIT_REFUSED
    assert json.loads(capsys.readouterr().out) == analyzed
