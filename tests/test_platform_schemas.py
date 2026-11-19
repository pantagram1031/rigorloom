# -*- coding: utf-8 -*-
"""The change set and event schemas the UI thread codes against (ruling item A).

The schemas carry every field of UI 요구 1-7; P0 writes the required subset,
and what it writes must validate. jsonschema is installed in CI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "runtime" / "schemas"
sys.path.insert(0, str(ROOT / "runtime" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

jsonschema = pytest.importorskip("jsonschema")

from test_platform_toolset import env, ok  # noqa: E402,F401  (fixture)
from rt_tools import call  # noqa: E402


def _load(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _validator(name):
    from referencing import Registry, Resource
    schema = _load(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s))
        for s in (_load("changeset.schema.json"), _load("events.schema.json")))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_schemas_are_valid_and_versioned():
    assert _load("changeset.schema.json")["properties"]["schema"]["const"] == "rigorloom.changeset/1"
    assert _load("events.schema.json")["properties"]["schema"]["const"] == "rigorloom.events/1"
    _validator("changeset.schema.json")
    _validator("events.schema.json")


def test_every_ui_requirement_has_its_field():
    cs = _load("changeset.schema.json")
    props = cs["properties"]
    item = props["items"]["items"]["properties"]
    for field in ("item_id", "ops", "address", "kind", "before", "after", "page", "rects",
                  "status", "note"):
        assert field in item, field                                    # 요구 1
    assert set(item["status"]["enum"]) == {"pending", "accepted", "rejected"}
    assert {"kind", "revision", "sha256"} <= set(props["base"]["properties"])  # 요구 2
    assert set(props["base"]["properties"]["kind"]["enum"]) >= {"source", "candidate"}
    assert "superseded_by_newer_candidate" in cs["$defs"]["staleReason"]["enum"]
    assert {"agent", "provider", "mock"} <= set(cs["$defs"]["provenance"]["properties"])  # 3
    guard = props["checks"]["properties"]["guard"]["properties"]["items"]["items"]
    assert {"item_id", "pass", "category", "values"} <= set(guard["properties"])  # 요구 4
    assert {"returned_items", "supersedes"} <= set(props)                     # 요구 5
    ev = _load("events.schema.json")
    kinds = set(ev["properties"]["kind"]["enum"])
    assert {"message.delta", "change.rejected", "change.stale", "step",
            "approval.requested"} <= kinds                                    # 요구 6
    assert {"turn_id", "seq", "ts", "changeset_id"} <= set(ev["properties"])


def test_change_sets_written_today_validate(env):
    check = _validator("changeset.schema.json")
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    ok(call(env.ctx(), "fill", {"path": str(path), "values": {"place:성명": "홍길동"}}))
    new = ok(call(env.ctx(provenance={"agent": "replay", "mock": True}), "new",
                  {"markdown": "# 회의록\n"}))
    from rt_drafts import DraftStore
    store = DraftStore(env.home)
    sets = (store.load(store.ref(path))["changesets"]
            + store.load(store.ref(new["path"]))["changesets"])
    assert [c["kind"] for c in sets] == ["edit", "fill", "new"]
    for changeset in sets:
        errors = sorted(check.iter_errors(changeset), key=str)
        assert not errors, [e.message for e in errors]
    assert sets[1]["base"]["kind"] == "candidate" and len(sets[1]["base"]["sha256"]) == 64
    assert sets[2]["provenance"]["mock"] is True


def test_an_event_without_its_changeset_is_refused():
    check = _validator("events.schema.json")
    good = {"schema": "rigorloom.events/1", "seq": 0, "kind": "change.stale",
            "ts": "2026-11-19T03:00:00Z", "turn_id": "t1", "changeset_id": "cs-0002-abcdef",
            "reason": "superseded_by_newer_candidate"}
    assert not list(check.iter_errors(good))
    bad = dict(good)
    del bad["changeset_id"]
    assert list(check.iter_errors(bad))


#: Claims the product never makes (ruling item G). Checked over everything a
#: person or an agent reads: runtime (including the knowledge pack and the
#: built UI), the skill, docs and packaging metadata.
FORBIDDEN_CLAIMS = ("정확도 100%", "Claude 기반", "AI 탐지 회피", "AI 티 제거")
CLAIM_PLACES = ("runtime", "skill", "docs", "pyproject.toml", "README.md", "AGENTS.md")


def test_no_forbidden_claims_in_what_ships():
    hits = []
    for place in CLAIM_PLACES:
        root = ROOT / place
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            if path.suffix in (".png", ".jpg", ".hwpx", ".hwp", ".pdf", ".woff2", ".ttf",
                               ".otf", ".pyc", ".ico", ".zip"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            hits += [f"{path.relative_to(ROOT)}: {c}" for c in FORBIDDEN_CLAIMS if c in text]
    assert not hits, hits
