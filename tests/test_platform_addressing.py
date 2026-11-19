"""The platform's verbs on the shared addressing fixture.

doc-core-api.md, ruling 2026-11-19 04:30Z: only top-level tables count as
``t<N>``, a nested table goes through its cell (``t0/r2/c1/t0``), a covered
cell answers at its anchor, an address that does not resolve is
``bad_address`` with ``at`` and ``candidates``, and place ids hash an identity
that filling cannot change. #388's own tests check rt_doc against
tests/fixtures/doc_core/addressing.{hwpx,json}. These check what the platform
builds on it, through the tool registry that the CLI and MCP serve: read,
edit and fill by those addresses and ids, and the refusal an agent or a person
gets for an address that is not there.

They need the real rt_doc and the fixture, and skip with the reason when
either is missing. The fake document layer reads its own text format, not
HWPX, so it is not run here.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "scripts"))
FX = ROOT / "tests" / "fixtures" / "doc_core"

import rt_tools  # noqa: E402
import rt_toolset  # noqa: E402,F401 - registers the tools
from rt_cli_render import person_error  # noqa: E402
from rt_drafts import DraftStore  # noqa: E402
from rt_paths import Roots  # noqa: E402
from rt_tools import Context, call  # noqa: E402


def _real_layer():
    if not (FX / "addressing.hwpx").exists():
        return None, "the shared fixture tests/fixtures/doc_core/addressing.hwpx is not in this checkout"
    try:
        import rt_doc
    except Exception as exc:  # noqa: BLE001 - absent or broken: say which
        return None, f"rt_doc is not importable here ({type(exc).__name__})"
    return rt_doc, None


RT_DOC, WHY = _real_layer()
pytestmark = pytest.mark.skipif(RT_DOC is None, reason=WHY or "")
WANT = json.loads((FX / "addressing.json").read_text("utf-8")) if RT_DOC else {}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home, work = tmp_path / "state", tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("RIGORLOOM_HOME", str(home))
    monkeypatch.delenv("RIGORLOOM_DEBUG", raising=False)
    monkeypatch.setattr(rt_tools, "load_doc", lambda: RT_DOC)
    doc = work / "addressing.hwpx"
    shutil.copyfile(FX / "addressing.hwpx", doc)

    def ctx(**kw):
        base = dict(client="mcp:test", roots=Roots.of([work]), source="draft",
                    _doc=RT_DOC, _drafts=DraftStore(home))
        base.update(kw)
        return Context(**base)

    return SimpleNamespace(home=home, work=work, doc=doc, ctx=ctx)


def ok(envelope):
    assert envelope["ok"], envelope.get("error")
    return envelope["result"]


def err(envelope, code):
    assert not envelope["ok"], envelope.get("result")
    assert envelope["error"]["code"] == code, envelope["error"]
    return envelope["error"]


def read_text(env, at, **kw):
    blocks = ok(call(env.ctx(**kw), "read", {"path": str(env.doc), "at": at}))["blocks"]
    assert blocks, at
    return blocks[0]["text"]


def cell_ids(env):
    opened = ok(call(env.ctx(), "open", {"path": str(env.doc)}))
    return {p["at"]: p["id"] for p in opened["places"] + opened["personOnly"]}


@pytest.mark.parametrize("at", sorted(WANT.get("text", {})))
def test_read_reaches_nested_tables_through_their_cell(env, at):
    assert read_text(env, at) == WANT["text"][at]


def test_open_lists_only_top_level_tables(env):
    tables = ok(call(env.ctx(), "open", {"path": str(env.doc)}))["tables"]
    top = [t["at"] for t in WANT["tables"] if "/" not in t["at"]]
    assert [t["at"] for t in tables if "/" not in t["at"]] == top


def test_a_covered_cell_reads_at_its_anchor(env):
    for at, anchor in WANT["covered"].items():
        blocks = ok(call(env.ctx(), "read", {"path": str(env.doc), "at": at}))["blocks"]
        assert blocks and blocks[0]["at"].startswith(anchor + "/"), (at, blocks)


@pytest.mark.parametrize("at", WANT.get("bad_address", []))
def test_an_unknown_address_is_bad_address_for_the_agent_and_the_person(env, at):
    e = err(call(env.ctx(), "read", {"path": str(env.doc), "at": at}), "bad_address")
    assert e["at"] == at and e["candidates"], e
    for candidate in e["candidates"]:
        ok(call(env.ctx(), "read", {"path": str(env.doc), "at": candidate}))
    message, _ = person_error(e, str(env.doc))
    assert at in message and any("가" <= ch <= "힣" for ch in message), message


def test_edit_a_nested_cell_in_the_draft(env):
    rev = ok(call(env.ctx(), "open", {"path": str(env.doc)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(env.doc), "base": rev, "ops": [
        {"op": "set", "at": "t0/r2/c1/t0/r0/c1", "text": "010-0000-0000"}]}))
    assert read_text(env, "t0/r2/c1/t0/r0/c1") == "010-0000-0000"
    assert read_text(env, "t0/r2/c1/t0/r0/c0") == WANT["text"]["t0/r2/c1/t0/r0/c0"]
    assert read_text(env, "t1/r0/c0") == WANT["text"]["t1/r0/c0"]
    assert read_text(env, "t0/r2/c1/t0/r0/c1", source="disk") == ""  # the file is untouched


def test_fill_by_id_moves_no_other_id_and_reaches_the_right_form(env):
    want = {p["at"]: p["id"] for p in WANT["cell_places"]}
    before = cell_ids(env)
    assert {at: before.get(at) for at in want} == want
    first, second = want["t0/r0/c1"], want["t2/r0/c1"]  # two 성명 seats, two forms
    r = ok(call(env.ctx(), "fill", {"path": str(env.doc), "values": {f"place:{first}": "홍길동"}}))
    assert f"place:{second}" in r["unfilled"] and f"place:{first}" not in r["unfilled"]
    assert cell_ids(env) == before
    ok(call(env.ctx(), "fill", {"path": str(env.doc), "values": {f"place:{second}": "김철수"}}))
    assert read_text(env, "t0/r0/c1") == "홍길동" and read_text(env, "t2/r0/c1") == "김철수"
    assert cell_ids(env) == before


def _filled_elsewhere(env, tmp_path, monkeypatch, ops):
    """Fill the file as another program would: no lineage knows the seats."""
    monkeypatch.setenv("RIGORLOOM_DOC_CACHE", str(tmp_path / "elsewhere"))
    rev = RT_DOC.outline(str(env.doc))["rev"]
    assert RT_DOC.edit(str(env.doc), ops, base=rev, in_place=True)["ok"]
    monkeypatch.setenv("RIGORLOOM_DOC_CACHE", str(tmp_path / "here"))
    monkeypatch.setattr(RT_DOC, "_LINEAGE", {})


def test_fill_reaches_a_seat_filled_elsewhere_by_its_id(env, tmp_path, monkeypatch):
    # Amendment 05:50Z: a filled cell is a text cell, so it drops off the list,
    # but place:<id> still names it and fill passes the id on.
    first = {p["at"]: p["id"] for p in WANT["cell_places"]}["t0/r0/c1"]
    _filled_elsewhere(env, tmp_path, monkeypatch, [{"op": "set", "at": "t0/r0/c1", "text": "홍길동"}])
    assert first not in cell_ids(env).values()
    r = ok(call(env.ctx(), "fill", {"path": str(env.doc), "values": {f"place:{first}": "김영희"}}))
    assert r["filled"] == [{"place": f"place:{first}", "text": "김영희"}]
    assert read_text(env, "t0/r0/c1") == "김영희"
    e = err(call(env.ctx(), "fill", {"path": str(env.doc), "values": {"place:000000000000": "x"}}),
            "bad_address")
    assert e["at"] == "place:000000000000" and e["candidates"], e


def test_a_signature_seat_filled_elsewhere_is_still_left_for_the_person(env, tmp_path, monkeypatch):
    # The words beside an unlisted cell label it as they would a blank one.
    first = {p["at"]: p["id"] for p in WANT["cell_places"]}["t0/r0/c1"]
    _filled_elsewhere(env, tmp_path, monkeypatch, [{"op": "set", "at": "t0/r0/c0", "text": "신청인 서명"},
                                                   {"op": "set", "at": "t0/r0/c1", "text": "홍길동 (인)"}])
    e = err(call(env.ctx(), "fill", {"path": str(env.doc), "values": {f"place:{first}": "김영희"}}),
            "person_only_seat")
    assert e["candidates"] == [f"place:{first}"]
    assert read_text(env, "t0/r0/c1") == "홍길동 (인)"
