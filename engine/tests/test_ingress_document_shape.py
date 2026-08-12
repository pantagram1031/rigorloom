# -*- coding: utf-8 -*-
"""Ingress refuses a file that is not a document, before COM (T123).

T25 closed the missing-input case with a note that says exactly why: Hwp opens a
blank document when the input is absent, and the blank artifact leaves as
`ok: true`. A file that EXISTS but is not a document has the identical failure
mode, and was not covered.

Measured on a bench with Hancom present, which is how this was found:

    printf '' > empty.hwp
    com_backend.py inspect --file empty.hwp --privacy-safe
    -> rc 0, {"ok": true, "pages": 1, "controls_total": 2, ...}

So a truncated or empty upload was indistinguishable from a real one-page
document on the machine-to-machine fingerprint surface. Every test here runs
offline: the refusal happens before `open_hwp` reaches pyhwpx, which is the
whole point of putting it there.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

import com_backend  # noqa: E402

REPO_ROOT = ROOT.parent
CORPUS = REPO_ROOT / "tests" / "corpus" / "forms"


# ---------------------------------------------------------------------------
# the sniffer, against real files and against the cases Hancom invents
# ---------------------------------------------------------------------------

def _corpus(suffix):
    return sorted(p for p in CORPUS.rglob("*" + suffix) if p.is_file())


@pytest.mark.skipif(not CORPUS.is_dir(), reason="corpus not present")
def test_every_real_corpus_document_is_accepted():
    """The half that matters: a guard that refuses real input is worse than none.

    Not a sample — every form in the corpus, both containers, asserted by count
    so that an empty glob cannot pass this vacuously.
    """
    hwp, hwpx = _corpus(".hwp"), _corpus(".hwpx")
    assert len(hwp) >= 10, [p.name for p in hwp]
    assert len(hwpx) >= 12, [p.name for p in hwpx]
    refused = {p.relative_to(REPO_ROOT).as_posix():
               com_backend.document_shape_reason(p)
               for p in hwp + hwpx
               if com_backend.document_shape_reason(p) is not None}
    assert not refused, refused


@pytest.mark.parametrize("payload,expected", [
    (b"", "empty_file"),
    (b"\xd0\xcf", "truncated_header"),
    # Shares the first two bytes of the OLE header and nothing else: pins the
    # full eight-byte signature, which a mutation shortening it would slip past.
    (b"\xd0\xcfNOTOLE!!", "unknown_container"),
    (b"not an hwp at all, just text", "unknown_container"),
    (b"%PDF-1.7\n%\xc7\xec\x8f\xa2", "unknown_container"),
    (b"PK\x05\x06" + b"\x00" * 18, "unknown_container"),   # empty zip archive
])
def test_a_non_document_is_named(tmp_path, payload, expected):
    path = tmp_path / "upload.hwp"
    path.write_bytes(payload)
    assert com_backend.document_shape_reason(path) == expected


def test_the_two_real_containers_are_accepted(tmp_path):
    """Synthetic headers, so this still holds in a checkout without the corpus."""
    ole = tmp_path / "ole.hwp"
    ole.write_bytes(com_backend.OLE_MAGIC + b"\x00" * 64)
    zipped = tmp_path / "owpml.hwpx"
    zipped.write_bytes(com_backend.ZIP_MAGIC + b"\x14\x00\x00\x00" + b"\x00" * 32)
    assert com_backend.document_shape_reason(ole) is None
    assert com_backend.document_shape_reason(zipped) is None


def test_every_reason_is_in_the_declared_set(tmp_path):
    """The vocabulary is closed, so a new token cannot appear unannounced."""
    seen = set()
    for payload in (b"", b"\xd0", b"junk-bytes-here"):
        path = tmp_path / "probe.hwp"
        path.write_bytes(payload)
        seen.add(com_backend.document_shape_reason(path))
    assert seen <= set(com_backend.NOT_A_DOCUMENT_REASONS), seen


def test_a_directory_is_refused_not_crashed(tmp_path):
    """`open()` on a directory raises OSError; the sniffer must name it."""
    target = tmp_path / "looks-like.hwp"
    target.mkdir()
    assert com_backend.document_shape_reason(target) == "unreadable"


# ---------------------------------------------------------------------------
# open_hwp: the choke point every subcommand goes through
# ---------------------------------------------------------------------------

def test_open_hwp_refuses_a_non_document_before_touching_com(monkeypatch,
                                                            capsys, tmp_path):
    """Proves the refusal precedes COM.

    A dummy pyhwpx is injected whose ``Hwp`` raises if it is ever constructed,
    so reaching COM is a loud failure rather than an inference from the error
    message. The import itself must succeed — otherwise this would pass for the
    wrong reason on a bench without pyhwpx installed.
    """
    empty = tmp_path / "TRUNCATED-UPLOAD.hwp"
    empty.write_bytes(b"")

    def _explode(*args, **kwargs):
        raise AssertionError("Hwp was constructed; the guard ran too late")

    fake = types.ModuleType("pyhwpx")
    fake.Hwp = _explode
    monkeypatch.setitem(sys.modules, "pyhwpx", fake)
    with pytest.raises(SystemExit) as exit_info:
        com_backend.open_hwp(str(empty))
    assert exit_info.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "empty_file" in payload["error"]


def test_open_hwp_still_refuses_a_missing_file(capsys, tmp_path):
    """T25's case must keep its own message; T123 must not absorb it."""
    with pytest.raises(SystemExit):
        com_backend.open_hwp(str(tmp_path / "absent.hwp"))
    assert "입력 파일 없음" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the privacy-safe surface
# ---------------------------------------------------------------------------

def test_privacy_safe_refuses_a_non_document_with_one_token(monkeypatch, capsys,
                                                            tmp_path):
    document = tmp_path / "PRIVATE-CANARY.hwp"
    document.write_bytes(b"")
    monkeypatch.setitem(sys.modules, "pyhwpx", types.ModuleType("pyhwpx"))

    def _never(*args, **kwargs):
        raise AssertionError("open_hwp was called on a non-document")

    monkeypatch.setattr(com_backend, "open_hwp", _never)
    monkeypatch.setattr(sys, "argv", [
        "com_backend.py", "inspect", "--file", str(document), "--privacy-safe"])

    with pytest.raises(SystemExit) as exit_info:
        com_backend.main()
    captured = capsys.readouterr()
    assert exit_info.value.code == 3
    assert json.loads(captured.out) == {
        "ok": False, "reason": com_backend.PRIVACY_SAFE_NOT_A_DOCUMENT}
    both = captured.out + captured.err
    assert "PRIVATE-CANARY" not in both
    assert "Traceback" not in both
    # The detailed vocabulary is for a human at the CLI; it must not reach here.
    for reason in com_backend.NOT_A_DOCUMENT_REASONS:
        assert reason not in both


class _BlockPyhwpx:
    """Meta-path finder that makes ``import pyhwpx`` fail, to model a bench
    without Hancom — the state of every CI runner and of macOS/Linux."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        if name == "pyhwpx" or name.startswith("pyhwpx."):
            raise ImportError("blocked: modelling a bench without pyhwpx")
        return None


@pytest.mark.parametrize("pyhwpx_present", [True, False])
def test_the_same_broken_upload_gets_the_same_token_either_way(
        monkeypatch, capsys, tmp_path, pyhwpx_present):
    """Order regression: the INPUT is judged before the HOST's capability.

    The first version of this slice checked pyhwpx availability first, so a
    0-byte file answered `source_not_a_document` on a Windows bench with Hancom
    and `inspect_failed` on all four CI runners — one input, two answers,
    decided by something the caller cannot see. CI caught it; this pins it.
    """
    empty = tmp_path / "PRIVATE-CANARY.hwp"
    empty.write_bytes(b"")
    if pyhwpx_present:
        monkeypatch.setitem(sys.modules, "pyhwpx", types.ModuleType("pyhwpx"))
    else:
        monkeypatch.delitem(sys.modules, "pyhwpx", raising=False)
        monkeypatch.setattr(sys, "meta_path", [_BlockPyhwpx, *sys.meta_path])
    monkeypatch.setattr(sys, "argv", [
        "com_backend.py", "inspect", "--file", str(empty), "--privacy-safe"])

    with pytest.raises(SystemExit) as exit_info:
        com_backend.main()
    captured = capsys.readouterr()
    assert exit_info.value.code == 3
    assert json.loads(captured.out) == {
        "ok": False, "reason": com_backend.PRIVACY_SAFE_NOT_A_DOCUMENT}
    assert "PRIVATE-CANARY" not in captured.out + captured.err


def test_a_missing_file_keeps_its_own_token(monkeypatch, capsys, tmp_path):
    """T25/T121's contract: absent is `inspect_failed`, not `not_a_document`.

    Without this, moving the shape check earlier would quietly reclassify a
    missing file, since opening one also fails.
    """
    monkeypatch.setitem(sys.modules, "pyhwpx", types.ModuleType("pyhwpx"))
    monkeypatch.setattr(sys, "argv", [
        "com_backend.py", "inspect", "--file",
        str(tmp_path / "absent.hwp"), "--privacy-safe"])
    with pytest.raises(SystemExit) as exit_info:
        com_backend.main()
    assert exit_info.value.code == 3
    assert json.loads(capsys.readouterr().out) == {
        "ok": False, "reason": "inspect_failed"}


def test_privacy_safe_cli_refuses_a_zero_byte_upload(tmp_path):
    """End to end through the real CLI, no COM: the reproduction from #73."""
    empty = tmp_path / "PRIVATE-CANARY.hwp"
    empty.write_bytes(b"")
    completed = subprocess.run(
        [sys.executable, com_backend.__file__, "inspect", "--file",
         str(empty), "--privacy-safe"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert completed.returncode == 3
    assert json.loads(completed.stdout) == {
        "ok": False, "reason": com_backend.PRIVACY_SAFE_NOT_A_DOCUMENT}
    assert "PRIVATE-CANARY" not in completed.stdout + completed.stderr
