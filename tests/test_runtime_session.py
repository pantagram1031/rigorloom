# -*- coding: utf-8 -*-
"""Session class: bounded ingress, source immutability, the read-only views."""
from __future__ import annotations

import hashlib
import shutil
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
