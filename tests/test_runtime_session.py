# -*- coding: utf-8 -*-
"""Session class: bounded ingress, source immutability, the read-only views."""
from __future__ import annotations

import hashlib
import os
import shutil
from types import SimpleNamespace
import zipfile

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_session  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    with RuntimeClient(tmp_path / "root") as handle:
        yield handle


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- ingress ----------------------------------------------------------------

def test_open_path_records_the_source_hash(client):
    client.initialize()
    result = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})
    assert result["source"]["sha256"] == _sha256(CORPUS_FORM)
    assert result["source"]["bytes"] == CORPUS_FORM.stat().st_size
    assert result["source"]["documentKind"] == "hwpx"


def test_the_program_owned_capture_anchor_is_retained_without_duplicate_bytes(
        tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"captured once")

    session = rt_session.Session.open_path(tmp_path / "root", str(source))

    anchors = list(session.source_dir.glob(".capture-*.tmp"))
    assert len(anchors) == 1
    assert anchors[0].read_bytes() == session.source.read_bytes()
    assert anchors[0].stat().st_ino == session.source.stat().st_ino
    assert session.source.stat().st_nlink == 2


def test_the_source_file_is_never_modified(client, tmp_path):
    """Byte identity of the ORIGINAL, across open + inspect + a full apply path."""
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    before = source.read_bytes()

    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(source)})["sessionId"]
    client.ok("document/inspect", {"sessionId": session})
    plan = client.ok("plan/propose", {
        "sessionId": session, "backend": "preedit",
        "ops": [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1,
                 "text": "값"}]})["plan"]
    client.ok("plan/validate", {"planId": plan["planId"]})
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    client.ok("approval/resolve", {
        "approvalId": approval["approvalId"], "planId": plan["planId"],
        "planHash": plan["planHash"], "decision": "approved",
        "approver": "test"})
    client.ok("plan/apply", {"planId": plan["planId"],
                             "approvalId": approval["approvalId"]})

    assert source.read_bytes() == before, "the Runtime modified the user's source"


def test_a_relative_path_is_refused(client):
    client.initialize()
    assert client.err("workspace/openPath", {"path": "form.hwpx"})["code"] == \
        "invalid_params"


def test_a_missing_path_is_refused(client, tmp_path):
    client.initialize()
    error = client.err("workspace/openPath", {"path": str(tmp_path / "nope.hwpx")})
    assert error["code"] == "source_rejected"


def test_a_directory_is_refused(client, tmp_path):
    client.initialize()
    error = client.err("workspace/openPath", {"path": str(tmp_path)})
    assert error["code"] == "source_rejected"


def test_a_zip_bomb_ratio_is_refused(tmp_path):
    bomb = tmp_path / "bomb.hwpx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/section0.xml", b"\0" * (4 * 1024 * 1024))
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.validate_source(bomb)
    assert excinfo.value.code == "source_rejected"
    assert "compression ratio" in excinfo.value.message


def test_a_traversing_zip_member_is_refused(tmp_path):
    evil = tmp_path / "evil.hwpx"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../escape.xml", "x")
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.validate_source(evil)
    assert excinfo.value.data["member"] == "../escape.xml"


def test_too_many_zip_members_are_refused(tmp_path, monkeypatch):
    many = tmp_path / "many.hwpx"
    with zipfile.ZipFile(many, "w") as archive:
        for index in range(12):
            archive.writestr(f"m{index}.xml", "x")
    monkeypatch.setattr(rt_session, "MAX_ZIP_MEMBERS", 5)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.validate_source(many)
    assert excinfo.value.data["members"] == 12


def test_an_oversized_source_is_refused(tmp_path, monkeypatch):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 4096)
    monkeypatch.setattr(rt_session, "MAX_SOURCE_BYTES", 1024)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.validate_source(big)
    assert excinfo.value.data["limit"] == 1024


def test_open_path_does_not_delegate_to_path_reopening_copyfile(tmp_path, monkeypatch):
    source = tmp_path / "source.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    original = source.read_bytes()

    def forbidden_reopen(*_args, **_kwargs):
        raise AssertionError("openPath reopened the source through shutil.copyfile")

    monkeypatch.setattr(shutil, "copyfile", forbidden_reopen)

    session = rt_session.Session.open_path(tmp_path / "root", str(source))

    assert session.source.read_bytes() == original
    assert session.meta["sourceSha256"] == hashlib.sha256(original).hexdigest()


def test_ctime_change_during_open_is_not_an_identity_mismatch(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"same bytes")
    before = path.lstat()
    opened = SimpleNamespace(
        st_dev=before.st_dev,
        st_ino=before.st_ino,
        st_nlink=before.st_nlink,
        st_size=before.st_size,
        st_mtime_ns=before.st_mtime_ns,
        st_ctime_ns=before.st_ctime_ns + 10,
    )

    assert rt_session._open_binding(before) == rt_session._open_binding(opened)
    assert rt_session._snapshot(before) != rt_session._snapshot(opened)


def test_an_open_handle_keeps_the_original_bytes_when_the_path_is_replaced(
        tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    replacement = tmp_path / "replacement.bin"
    source.write_bytes(b"opened bytes")
    replacement.write_bytes(b"replacement bytes")
    replacement_blocked = []

    def replace_path(step, path):
        if step == "opened":
            try:
                replacement.replace(path)
            except PermissionError:
                # CPython on Windows opens without FILE_SHARE_DELETE, so the
                # stable read handle itself can pin the directory entry.
                replacement_blocked.append(True)

    monkeypatch.setattr(rt_session, "_SOURCE_CAPTURE_CHECKPOINT", replace_path)

    session = rt_session.Session.open_path(tmp_path / "root", str(source))

    assert session.source.read_bytes() == b"opened bytes"
    assert session.meta["sourceSha256"] == hashlib.sha256(b"opened bytes").hexdigest()
    assert source.read_bytes() == (
        b"opened bytes" if replacement_blocked else b"replacement bytes")


def test_growth_through_the_open_handle_is_refused_and_cleans_the_session(
        tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"small")
    root = tmp_path / "root"
    monkeypatch.setattr(rt_session, "MAX_SOURCE_BYTES", 16)

    def grow_source(step, _path):
        if step == "opened":
            source.write_bytes(b"x" * 32)

    monkeypatch.setattr(rt_session, "_SOURCE_CAPTURE_CHECKPOINT", grow_source)

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.Session.open_path(root, str(source))

    assert excinfo.value.code == "source_rejected"
    sessions = list((root / "sessions").iterdir())
    assert sessions and all(not (path / "meta.json").exists() for path in sessions)
    assert all(rt_session.Session.load(root, path.name) is None for path in sessions)


def test_a_changed_owned_stage_is_refused_before_publication(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"stable source")
    root = tmp_path / "root"

    def change_stage(step, path):
        if step == "before_publish":
            path.write_bytes(b"changed stage")

    monkeypatch.setattr(rt_session, "_SOURCE_CAPTURE_CHECKPOINT", change_stage)

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.Session.open_path(root, str(source))

    assert excinfo.value.code == "source_rejected"
    sessions = list((root / "sessions").iterdir())
    assert sessions and all(not (path / "meta.json").exists() for path in sessions)
    assert all(rt_session.Session.load(root, path.name) is None for path in sessions)


def test_a_rebound_same_byte_stage_is_preserved_not_unlinked(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"same bytes")
    foreign = tmp_path / "foreign.bin"
    foreign.write_bytes(b"same bytes")
    root = tmp_path / "root"
    rebound = []

    def rebind_stage(step, path):
        if step == "before_publish":
            original = path.with_name("original-stage-held")
            path.replace(original)
            foreign.replace(path)
            rebound.extend([path, original])

    monkeypatch.setattr(rt_session, "_SOURCE_CAPTURE_CHECKPOINT", rebind_stage)

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.Session.open_path(root, str(source))

    assert excinfo.value.code == "publication_failed"
    assert len(rebound) == 2
    assert rebound[0].read_bytes() == b"same bytes"
    assert rebound[1].read_bytes() == b"same bytes"
    assert all(not (path / "meta.json").exists()
               for path in (root / "sessions").iterdir())


def test_a_foreign_stage_collision_is_never_deleted(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    stage = tmp_path / "stage.bin"
    stage.write_bytes(b"foreign bytes")

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session._capture_source(source, stage)

    assert excinfo.value.code == "publication_failed"
    assert stage.read_bytes() == b"foreign bytes"


def test_a_session_id_collision_preserves_the_existing_directory(tmp_path, monkeypatch):
    root = tmp_path / "root"
    session_id = "a" * 32
    existing = root / "sessions" / session_id
    existing.mkdir(parents=True)
    marker = existing / "foreign.txt"
    marker.write_bytes(b"keep me")
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")

    class FixedUuid:
        hex = session_id

    monkeypatch.setattr(rt_session.uuid, "uuid4", lambda: FixedUuid())

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.Session.open_path(root, str(source))

    assert excinfo.value.code == "publication_failed"
    assert marker.read_bytes() == b"keep me"


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX FIFO")
def test_a_fifo_swap_before_open_refuses_without_blocking(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes(b"regular")
    real_open = rt_session.os.open

    def swap_to_fifo(path, flags, *args):
        if path == source:
            source.unlink()
            os.mkfifo(source)
        return real_open(path, flags, *args)

    monkeypatch.setattr(rt_session.os, "open", swap_to_fifo)

    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.validate_source(source)

    assert excinfo.value.code == "source_rejected"


def test_an_opaque_non_zip_source_is_accepted_but_not_addressable(client, tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("hello", encoding="utf-8")
    client.initialize()
    result = client.ok("workspace/openPath", {"path": str(plain)})
    assert result["source"]["documentKind"] == "opaque"
    error = client.err("document/inspect", {"sessionId": result["sessionId"]})
    assert error["code"] == "backend_refused"


# --- views ------------------------------------------------------------------

def test_inspect_returns_summary_graph_and_regions(client):
    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]
    result = client.ok("document/inspect", {"sessionId": session})
    assert result["documentHash"]
    assert result["summary"]["fillTargetCount"] == 9
    assert len(result["graph"]["tables"]) == 3
    regions = result["regions"]["regions"]
    assert len(regions) == 9
    anomalous = [r for r in regions if r["scriptAnomaly"]]
    assert [(r["row"], r["col"], r["charPrSuggested"]) for r in anomalous] == \
        [(2, 0, "23")]


def test_inspect_honours_include(client):
    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]
    result = client.ok("document/inspect", {"sessionId": session,
                                            "include": ["summary"]})
    assert "graph" not in result and "regions" not in result


def test_an_unknown_session_is_refused(client):
    client.initialize()
    assert client.err("document/inspect", {"sessionId": "nope"})["code"] == \
        "unknown_session"


def test_read_region_returns_exact_runs(client):
    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]
    result = client.ok("document/readRegion", {
        "sessionId": session,
        "regions": [{"table": 0, "row": 5, "col": 1}]})
    region = result["regions"][0]
    assert region["addr"] == {"row": 5, "col": 1}
    assert isinstance(region["runs"], list)


def test_read_region_refuses_rather_than_truncates(monkeypatch):
    """The bound is a refusal — ``region_too_large``, never a silent short read.

    The shipped cap is 256 KiB; shrinking it here proves the branch without
    manufacturing a quarter-megabyte document.
    """
    payload = {"sessionId": "s", "regions": [{"text": "x" * 4096}]}
    assert rt_session.bound_region_result(payload) is payload

    monkeypatch.setattr(rt_session, "MAX_REGION_BYTES", 128)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_session.bound_region_result(payload)
    assert excinfo.value.code == "region_too_large"
    assert excinfo.value.data["limit"] == 128


def test_read_region_needs_an_address(client):
    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]
    error = client.err("document/readRegion", {"sessionId": session,
                                               "regions": [{"table": 0}]})
    assert error["code"] == "invalid_params"
