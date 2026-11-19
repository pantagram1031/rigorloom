# -*- coding: utf-8 -*-
"""The eleven document tools, run against the fake document layer.

What these pin down is the platform's own promises, not document handling
(that is rt_doc's contract test): the person's file is untouched until
``save``; edits build on the draft and refuse stale bases; budgets hold and a
``read`` cursor walks a whole document with no loss and no repeat; signature
seats are never filled; ``save`` creates, re-saves its own file, or asks a
person, and a "no" is final for those bytes; the CLI and the registry give the
same result for the same request.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import _fake_rt_doc as fake  # noqa: E402
import rt_cli_product  # noqa: E402
import rt_tools  # noqa: E402
import rt_toolset  # noqa: E402
from rt_drafts import DraftStore  # noqa: E402
from rt_paths import Roots, sha256_file  # noqa: E402
from rt_tools import REGISTRY, Context, call  # noqa: E402

TOOLS = ("open", "read", "find", "edit", "fill", "new", "preview", "check", "save",
         "changes", "guide")

FORM = """\
# 출장 신청서

신청인은 아래와 같이 출장을 신청합니다.

| 항목 | 내용 |
|---|---|
| 기간 | 2026. 11. 3. ~ 11. 5. |
| 금액 | 450,000원 |

[[place:성명|성명]]

[[place:소속|소속]]

[[place:서명|신청인 서명 (인)]]
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A work folder, a state dir, and the fake as the document layer."""
    home = tmp_path / "state"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("RIGORLOOM_HOME", str(home))
    monkeypatch.delenv("RIGORLOOM_DEBUG", raising=False)
    monkeypatch.setattr(rt_toolset, "FORMATS_IN", rt_toolset.FORMATS_IN + ("fdoc",))
    monkeypatch.setattr(rt_toolset, "FORMATS_OUT", rt_toolset.FORMATS_OUT + ("fdoc",))
    monkeypatch.setattr(fake, "NATIVE_SUFFIX", ".fdoc", raising=False)
    monkeypatch.setattr(rt_tools, "load_doc", lambda: fake)

    class Env:
        pass

    e = Env()
    e.home, e.work = home, work

    def doc(name="신청서.fdoc", text=FORM):
        path = work / name
        path.write_text(text, encoding="utf-8")
        return path

    def ctx(**kw):
        base = dict(client="mcp:test", roots=Roots.of([work]), source="draft",
                    _doc=fake, _drafts=DraftStore(home))
        base.update(kw)
        return Context(**base)

    e.doc, e.ctx = doc, ctx
    return e


def ok(envelope):
    assert envelope["ok"], envelope.get("error")
    return envelope["result"]


def err(envelope, code):
    assert not envelope["ok"], envelope.get("result")
    assert envelope["error"]["code"] == code, envelope["error"]
    return envelope["error"]


# -- the registry ---------------------------------------------------------------

def test_eleven_tools_with_closed_schemas():
    assert sorted(REGISTRY) == sorted(TOOLS)
    for tool in REGISTRY.values():
        schema = tool.input_schema
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema.get("required", [])) <= set(schema["properties"])
        hangul = sum("가" <= ch <= "힣" for ch in tool.description)
        assert hangul < len(tool.description) * 0.2, tool.name  # model-facing: English
        assert len(tool.description) < 700, tool.name
        assert not tool.title.isascii(), tool.name     # people-facing title is Korean
        ann = tool.annotations()
        assert ann["readOnlyHint"] == tool.read_only
    assert [t.name for t in REGISTRY.values() if t.destructive] == ["save"]


def test_call_never_raises(env, monkeypatch):
    err(call(env.ctx(), "no_such_tool", {}), "unknown_tool")
    err(call(env.ctx(), "open", {}), "invalid_params")
    err(call(env.ctx(), "open", {"path": "x", "extra": 1}), "invalid_params")

    def boom(ctx, args):
        raise RuntimeError("bug")

    frozen = REGISTRY["guide"]  # Tool is frozen; swap the registry entry
    monkeypatch.setitem(REGISTRY, "guide", rt_tools.Tool(**{
        **{f: getattr(frozen, f) for f in frozen.__dataclass_fields__}, "run": boom}))
    e = err(call(env.ctx(), "guide", {}), "internal")
    assert "trace" not in (e.get("data") or {})  # local paths stay local
    monkeypatch.setenv("RIGORLOOM_DEBUG", "1")
    e = err(call(env.ctx(), "guide", {}), "internal")
    assert "RuntimeError" in e["data"]["trace"]


# -- open, read, find -----------------------------------------------------------

def test_open_lists_places_and_keeps_signature_seats_for_the_person(env):
    path = env.doc()
    r = ok(call(env.ctx(), "open", {"path": str(path)}))
    assert r["rev"] == sha256_file(path)[:12] and r["source"] == "disk"
    assert [p["id"] for p in r["places"]] == ["성명", "소속"]
    assert [p["id"] for p in r["personOnly"]] == ["서명"]
    assert r["headings"][0]["text"] == "출장 신청서"
    text = rt_tools.render_text(REGISTRY["open"], r)
    assert "place:성명" in text and "person-only seats (never fill): place:서명" in text


def test_open_stays_inside_its_budget(env):
    body = "\n\n".join(f"## {i}번째 절 제목을 조금 길게 적어 봅니다" for i in range(600))
    path = env.doc("긴문서.fdoc", "# 긴 문서\n\n" + body + "\n")
    r = ok(call(env.ctx(), "open", {"path": str(path)}))
    text = rt_tools.render_text(REGISTRY["open"], r)
    assert len(text) <= rt_toolset.OPEN_BUDGET_CHARS
    assert r["omitted"]["headings"] + len(r["headings"]) == 601
    assert "omitted for size" in text


def test_read_cursor_walks_everything_once(env):
    paras = [f"{i:03d} " + "가나다라마바사아자차카타파하 " * (3 + i % 40) for i in range(120)]
    path = env.doc("본문.fdoc", "\n\n".join(paras) + "\n")
    whole = ok(call(env.ctx(), "read", {"path": str(path), "max_chars": 20000}))
    assert whole.get("next")  # too big for one call even at the maximum
    pieces: dict[str, str] = {}
    cursor, calls = None, 0
    while True:
        req = {"path": str(path), "max_chars": 500}
        if cursor:
            req["cursor"] = cursor
        r = ok(call(env.ctx(), "read", req))
        calls += 1
        assert sum(len(b["text"]) for b in r["blocks"]) <= 500
        for b in r["blocks"]:
            frm = b.get("part", {}).get("from", 0)
            assert len(pieces.get(b["at"], "")) == frm, "gap or repeat at " + b["at"]
            pieces[b["at"]] = pieces.get(b["at"], "") + b["text"]
        cursor = r.get("next")
        if not cursor:
            break
        assert calls < 1000
    full = fake.read(str(path))["blocks"]
    assert [pieces[b["at"]] for b in full] == [b["text"] for b in full]


def test_read_cursor_refuses_a_changed_document(env):
    path = env.doc("본문.fdoc", "\n\n".join("문단 " * 200 for _ in range(10)) + "\n")
    first = ok(call(env.ctx(), "read", {"path": str(path), "max_chars": 500}))
    path.write_text(path.read_text(encoding="utf-8") + "\n덧붙임\n", encoding="utf-8")
    e = err(call(env.ctx(), "read", {"path": str(path), "cursor": first["next"]}), "stale")
    assert e["retryable"] is True


def test_document_text_cannot_drive_the_terminal(env):
    path = env.doc("나쁜.fdoc", "# 제목\x1b[2J\n\n본문‮뒤집기\x07\n")
    r = ok(call(env.ctx(), "read", {"path": str(path)}))
    text = rt_tools.render_text(REGISTRY["read"], r)
    assert "\x1b" not in text and "‮" not in text and "\x07" not in text
    o = rt_tools.render_text(REGISTRY["open"], ok(call(env.ctx(), "open", {"path": str(path)})))
    assert "\x1b" not in o


def test_find_hits_are_readable_addresses(env):
    path = env.doc()
    r = ok(call(env.ctx(), "find", {"path": str(path), "query": "출장"}))
    assert r["total"] >= 2
    for hit in r["hits"]:
        assert ok(call(env.ctx(), "read", {"path": str(path), "at": hit["at"]}))["blocks"]


# -- the path gate ----------------------------------------------------------------

def test_paths_outside_the_roots_are_refused(env, tmp_path):
    outside = tmp_path / "밖.fdoc"
    outside.write_text("# x\n", encoding="utf-8")
    e = err(call(env.ctx(), "open", {"path": str(outside)}), "outside_roots")
    assert "--allow" in e["hint"]
    path = env.doc()
    err(call(env.ctx(), "save", {"path": str(path), "to": str(outside)}), "outside_roots")


def test_markdown_pictures_must_be_local_and_inside(env, tmp_path):
    err(call(env.ctx(), "new", {"markdown": "![a](https://example.com/x.png)"}),
        "invalid_params")
    err(call(env.ctx(), "new", {"markdown": f"![a]({tmp_path / 'x.png'})"}), "outside_roots")


def test_unknown_format_is_refused(env):
    path = env.work / "a.xyz"
    path.write_text("x", encoding="utf-8")
    err(call(env.ctx(), "open", {"path": str(path)}), "unsupported_format")


# -- edit and the draft ---------------------------------------------------------------

def test_edit_stages_and_leaves_the_file_alone(env):
    path = env.doc()
    before = path.read_bytes()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    r = ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "신청인은 아래와 같이 출장을 다시 신청합니다."}]}))
    assert r["source"] == "draft" and r["revision"] == 1 and r["saved"] is False
    assert path.read_bytes() == before
    # agents see the draft; the person's CLI sees the file and hears about the draft
    seen = ok(call(env.ctx(), "read", {"path": str(path), "at": "p1"}))
    assert "다시" in seen["blocks"][0]["text"] and seen["rev"] == r["rev"]
    disk = ok(call(env.ctx(source="disk"), "open", {"path": str(path)}))
    assert disk["rev"] == rev0 and disk["draft"]["revision"] == 1
    assert "draft exists: revision 1, not saved" in rt_tools.render_text(REGISTRY["open"], disk)
    # a second edit builds on the first
    r2 = ok(call(env.ctx(), "edit", {"path": str(path), "base": r["rev"], "ops": [
        {"op": "replace", "find": "450,000원", "with": "480,000원"}]}))
    assert r2["revision"] == 2 and r2["revBefore"] == r["rev"]


def test_edit_on_an_old_rev_is_stale(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "하나"}]}))
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "둘"}]}), "stale")
    assert e["retryable"] is True


def test_edit_refuses_when_the_source_changed_under_the_draft(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    r = ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "하나"}]}))
    path.write_text(FORM + "\n한컴에서 덧붙인 줄\n", encoding="utf-8")
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": r["rev"], "ops": [
        {"op": "set", "at": "p1", "text": "둘"}]}), "source_changed")
    assert "discard" in e["hint"]


def test_bad_ops_are_named(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0,
                                     "ops": [{"op": "sett", "at": "p1"}]}), "invalid_params")
    assert e["at"] == "ops[0]" and "set" in e["candidates"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0,
                                     "ops": [{"op": "set", "at": "p1"}]}), "invalid_params")
    assert e["at"] == "ops[0].text"


def test_ambiguous_replace_keeps_the_candidates(env):
    path = env.doc("두번.fdoc", "같은 말\n\n같은 말\n")
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "같은 말", "with": "다른 말"}]}), "ambiguous_match")
    assert len(e["candidates"]) == 2


# -- fill -------------------------------------------------------------------------

def test_fill_skips_signature_seats_and_reports_what_is_left(env):
    path = env.doc()
    # Ruling F: the person's seats are skipped and listed; the rest is filled.
    r = ok(call(env.ctx(), "fill", {"path": str(path), "values": {
        "place:성명": "김철수", "place:서명": "홍길동"}}))
    assert r["skipped"] == ["place:서명"] and r["personOnly"] == ["place:서명"]
    seat = ok(call(env.ctx(), "read", {"path": str(path), "at": "place:서명"}))
    assert "홍길동" not in seat["blocks"][0]["text"]
    # Only the person's seats asked for: nothing to do, so a refusal.
    e = err(call(env.ctx(), "fill", {"path": str(path), "values": {"place:서명": "홍"}}),
            "person_only_seat")
    assert e["candidates"] == ["place:서명"]
    e = err(call(env.ctx(), "fill", {"path": str(path), "values": {"place:셩명": "x"}}),
            "bad_address")
    assert "place:성명" in e["candidates"]
    r = ok(call(env.ctx(), "fill", {"path": str(path), "values": {"성명": "홍길동"}}))
    assert r["personOnly"] == ["place:서명"] and r["unfilled"] == ["place:소속"]
    assert r["skipped"] == []
    seen = ok(call(env.ctx(), "read", {"path": str(path), "at": "place:성명"}))
    assert seen["blocks"][0]["text"] == "홍길동"


# -- new and save -----------------------------------------------------------------

def test_new_then_save_creates_and_then_resaves_its_own_file(env):
    r = ok(call(env.ctx(), "new", {"markdown": "# 회의록\n\n안건은 둘입니다.\n"}))
    draft = r["path"]
    assert draft.startswith("draft:") and r["revision"] == 1
    assert ok(call(env.ctx(), "read", {"path": draft}))["blocks"][0]["text"] == "회의록"
    target = env.work / "회의록.fdoc"
    s = ok(call(env.ctx(), "save", {"path": draft, "to": str(target)}))
    assert s["acceptedVia"] == "policy:new-file" and s["replaced"] is False
    assert sha256_file(target) == s["sha256"]
    err(call(env.ctx(), "save", {"path": draft, "to": str(target)}), "no_draft")
    head = ok(call(env.ctx(), "open", {"path": draft}))["rev"]
    ok(call(env.ctx(), "edit", {"path": draft, "base": head, "ops": [
        {"op": "set", "at": "p1", "text": "안건은 셋입니다."}]}))
    s2 = ok(call(env.ctx(), "save", {"path": draft, "to": str(target)}))
    assert s2["acceptedVia"] == "policy:own-file" and s2["replaced"] is True


def test_a_foreign_write_after_the_ownership_check_is_not_replaced(env, monkeypatch):
    # Fable #389 item 1: own-file must compare against the bytes the ownership
    # check matched, so a write that lands just after it fails as target_changed.
    import rt_commit
    draft = ok(call(env.ctx(), "new", {"markdown": "# 회의록\n\n안건은 둘입니다.\n"}))["path"]
    target = env.work / "회의록.fdoc"
    ok(call(env.ctx(), "save", {"path": draft, "to": str(target)}))
    head = ok(call(env.ctx(), "open", {"path": draft}))["rev"]
    ok(call(env.ctx(), "edit", {"path": draft, "base": head, "ops": [
        {"op": "set", "at": "p1", "text": "안건은 셋입니다."}]}))
    real = rt_commit.owned_sha256

    def check_then_someone_writes(*a, **kw):
        result = real(*a, **kw)
        target.write_bytes(b"someone else")
        return result

    monkeypatch.setattr(rt_commit, "owned_sha256", check_then_someone_writes)
    err(call(env.ctx(), "save", {"path": draft, "to": str(target)}), "target_changed")
    assert target.read_bytes() == b"someone else"


def test_save_over_a_persons_file_needs_the_person(env):
    path = env.doc()
    before = path.read_bytes()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    e = err(call(env.ctx(), "save", {"path": str(path)}), "needs_person")
    assert f'rigorloom save "{path}"' in e["hint"]
    assert e["data"]["undo"] == f'rigorloom undo "{path}"'
    assert path.read_bytes() == before


def test_a_no_is_final_for_those_bytes(env):
    path = env.doc()
    before = path.read_bytes()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    asked = []

    def no(question, detail):
        asked.append(detail)
        return False

    err(call(env.ctx(ask=no), "save", {"path": str(path)}), "declined_by_person")
    assert len(asked) == 1 and asked[0]["changedPages"] is not None
    err(call(env.ctx(ask=no), "save", {"path": str(path)}), "declined_by_person")
    assert len(asked) == 1  # not asked again for the same bytes and target
    assert path.read_bytes() == before
    # nobody answering is not a "no"
    err(call(env.ctx(ask=lambda q, d: None), "save", {"path": str(path), "to": str(
        env.doc("다른.fdoc"))}), "needs_person")


def test_a_yes_replaces_keeps_history_and_undo_restores(env):
    path = env.doc()
    before = path.read_bytes()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    s = ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
    assert s["acceptedVia"] == "person:elicitation" and s["replaced"] is True
    assert s["unreviewed"] == 1
    assert path.read_bytes() != before
    # the next read works: the draft now sits on the saved bytes
    again = ok(call(env.ctx(), "open", {"path": str(path)}))
    assert again["rev"] == s["sha256"][:12]
    hist = ok(call(env.ctx(), "changes", {"action": "show", "path": str(path)}))
    assert [c["status"] for c in hist["changesets"]] == ["applied"]
    import rt_commit
    rt_commit.undo(path, by="test")
    assert path.read_bytes() == before


def test_save_converts_by_target_suffix(env):
    path = env.doc()
    out = env.work / "신청서.md"
    s = ok(call(env.ctx(), "save", {"path": str(path), "to": str(out)}))
    assert s["format"] == "md" and out.read_text(encoding="utf-8").startswith("# 출장 신청서")


def test_nothing_to_save_without_edits(env):
    path = env.doc()
    err(call(env.ctx(), "save", {"path": str(path)}), "no_draft")


# -- check ------------------------------------------------------------------------

def test_check_is_tri_state(env, monkeypatch):
    path = env.doc("문체.fdoc", "# 보고\n\n예산에 대해 설명합니다. 금액은 100원입니다.\n")
    r = ok(call(env.ctx(), "check", {"path": str(path)}))
    assert r["checks"]["style"]["state"] == "passed"  # a notice is not a failure
    assert any(f["rule"] == fake.EDAE_RULE for f in r["findings"])
    rev0 = r["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "100원", "with": "1000원"}]}))
    r = ok(call(env.ctx(), "check", {"path": str(path)}))
    assert r["checks"]["guard"]["state"] == "failed" and r["pass"] is False

    def unavailable(path):
        return {"ok": False, "error": {"code": "capability_unavailable",
                                       "message": "쪽 배치는 엔진이 있어야 합니다",
                                       "retryable": False}}

    monkeypatch.setattr(fake, "pages", unavailable)
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["layout"]}))
    assert r["checks"]["layout"]["state"] == "unavailable" and r["pass"] is None


# -- changes and guide ----------------------------------------------------------------

def test_changes_lists_drafts(env):
    path = env.doc()
    assert ok(call(env.ctx(), "changes", {}))["drafts"] == []
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "x"}]}))
    drafts = ok(call(env.ctx(), "changes", {}))["drafts"]
    assert len(drafts) == 1 and drafts[0]["pending"] == 1


# -- one request, one result: CLI and registry ----------------------------------------

def _cli(argv, monkeypatch, stdin=""):
    out, errs = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", errs)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = rt_cli_product.main(argv)
    return code, out.getvalue(), errs.getvalue()


_VOLATILE = {"changeset", "created", "updated", "at", "id"}


def _stable(value):
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


@pytest.mark.parametrize("argv,tool,request_", [
    (["open", "{p}"], "open", {"path": "{p}"}),
    (["read", "{p}", "--at", "t0"], "read", {"path": "{p}", "at": "t0"}),
    (["read", "{p}", "--max-chars", "500"], "read", {"path": "{p}", "max_chars": 500}),
    (["find", "{p}", "출장", "--limit", "1"], "find", {"path": "{p}", "query": "출장", "limit": 1}),
    (["check", "{p}", "--only", "style"], "check", {"path": "{p}", "only": ["style"]}),
    (["preview", "{p}", "--page", "1"], "preview", {"path": "{p}", "pages": [1]}),
    (["changes"], "changes", {"action": "list"}),
])
def test_cli_and_registry_agree_on_reads(env, monkeypatch, argv, tool, request_):
    path = str(env.doc())
    argv = [a.replace("{p}", path) for a in argv] + ["--json"]
    request_ = {k: (v.replace("{p}", path) if isinstance(v, str) else v)
                for k, v in request_.items()}
    code, out, _ = _cli(argv, monkeypatch)
    assert code == 0, out
    got = json.loads(out)
    assert got["ok"] and got["command"] == argv[0]
    direct = ok(call(Context(client="cli", source="disk", _doc=fake), tool, request_))
    assert _stable(got["result"]) == _stable(direct)


def test_cli_and_registry_agree_on_writes(env, monkeypatch, tmp_path):
    path = env.doc()
    op = {"op": "set", "at": "p1", "text": "같은 요청"}
    code, out, _ = _cli(["edit", str(path), "--op", json.dumps(op, ensure_ascii=False),
                         "--json"], monkeypatch)
    assert code == 0, out
    via_cli = json.loads(out)["result"]
    # the same request through the registry, on a copy with its own state dir
    other = tmp_path / "copy"
    other.mkdir()
    copy = other / path.name
    copy.write_bytes(path.read_bytes())
    monkeypatch.setenv("RIGORLOOM_HOME", str(tmp_path / "state2"))
    rev0 = sha256_file(copy)[:12]
    direct = ok(call(Context(client="cli", source="disk", _doc=fake), "edit",
                     {"path": str(copy), "base": rev0, "ops": [op]}))
    assert via_cli["rev"] == direct["rev"] and via_cli["revBefore"] == rev0
    assert _stable({k: v for k, v in via_cli.items() if k != "path"}) == \
        _stable({k: v for k, v in direct.items() if k != "path"})


def test_cli_fill_with_out_saves_a_new_file(env, monkeypatch):
    path = env.doc()
    out = env.work / "신청서-작성.fdoc"
    code, stdout, errs = _cli(["fill", str(path), "--set", "성명=홍길동", "-o", str(out)],
                              monkeypatch)
    assert code == 0, errs
    assert "홍길동" in out.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8") == FORM
    assert stdout.startswith("새 파일로 저장했습니다: ")
    assert "검토하지 않은" not in stdout  # the person made this change themselves


def test_cli_errors_are_two_short_korean_lines(env, monkeypatch):
    code, out, errs = _cli(["open", str(env.work / "없음.fdoc")], monkeypatch)
    assert code == 2 and out == ""
    lines = errs.strip().splitlines()
    assert 1 <= len(lines) <= 3 and not lines[0].isascii()


def test_undo_needs_a_person_at_a_terminal(env, monkeypatch):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
    saved = path.read_bytes()
    code, out, _ = _cli(["undo", str(path), "--json"], monkeypatch, stdin="y\n")
    assert code == 3 and json.loads(out)["error"]["code"] == "needs_person"
    assert path.read_bytes() == saved


def test_legacy_argv_never_reaches_the_product_verbs():
    assert rt_cli_product.is_product(["open", "a.hwpx"])
    assert not rt_cli_product.is_product(["--root", "/w", "open", "--path", "a.hwpx"])
    assert not rt_cli_product.is_product(["--root=/w", "open"])
    assert not rt_cli_product.is_product(["guard", "a", "b"])
    assert not rt_cli_product.is_product(["capabilities"])


def test_check_without_the_layers_own_style_and_guard(env, monkeypatch):
    """The real rt_doc has no style()/guard(): rt_style and rt_fidelity run over
    its blocks, so every finding still carries a document address."""
    monkeypatch.delattr(fake, "style")
    monkeypatch.delattr(fake, "guard")
    path = env.doc("문체.fdoc", "# 보고\n\n예산에 의해 결정되었다. 금액은 100원이다.\n\n덧붙일 곳\n")
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["style"]}))
    hits = [f for f in r["findings"] if f["rule"] == "ko.e-uihae"]
    assert hits and hits[0]["at"] == "p1" and hits[0]["match"].startswith("에 의해")
    rev0 = r["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "100원", "with": "120원"},
        {"op": "insert_after", "at": "p2", "markdown": "새 문단은 2026년 계획이다."}]}))
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["guard"]}))
    kinds = {(f["at"], f["rule"]) for f in r["findings"]}
    assert ("p1", "guard.fact_changed") in kinds
    assert any(rule == "guard.fact_added" for _, rule in kinds)
    assert r["checks"]["guard"]["state"] == "failed"
    # only an added paragraph: worth reading, not a failure
    path2 = env.doc("둘.fdoc", "# 보고\n\n그대로 둔다.\n")
    rev = ok(call(env.ctx(), "open", {"path": str(path2)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path2), "base": rev, "ops": [
        {"op": "insert_after", "at": "p1", "markdown": "2026년 11월에 시작한다."}]}))
    r = ok(call(env.ctx(), "check", {"path": str(path2), "only": ["guard"]}))
    assert r["checks"]["guard"]["state"] == "passed" and r["findings"]


def test_check_tells_numbers_that_traded_places_from_a_changed_number(env, monkeypatch):
    """A swap carries the words that name each number on both sides, so an
    agent does not take it for one changed number and "fix" the wrong one."""
    monkeypatch.delattr(fake, "guard")
    path = env.doc("수당.fdoc", "# 보고\n\n기본급은 300만원, 수당은 50만원이다.\n\n교통비는 7만원이다.\n")
    rev = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev, "ops": [
        {"op": "replace", "find": "기본급은 300만원, 수당은 50만원",
         "with": "기본급은 50만원, 수당은 300만원"},
        {"op": "replace", "find": "7만원", "with": "8만원"}]}))
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["guard"]}))
    found = {f["at"]: f for f in r["findings"] if f["rule"] == "guard.fact_changed"}
    assert found["p1"]["swapped"] == {"before": ["기본급은 300만원", "수당은 50만원"],
                                      "after": ["기본급은 50만원", "수당은 300만원"]}
    assert "swapped" not in found["p2"]


def test_cli_dash_o_is_one_shot_and_never_replaces_without_force(env, monkeypatch):
    path = env.doc()
    # an agent has a draft in progress on the same file
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    agent = ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "에이전트가 고친 문장"}]}))
    out = env.work / "사람.fdoc"
    op = json.dumps({"op": "replace", "find": "450,000원", "with": "500,000원"},
                    ensure_ascii=False)
    code, _, errs = _cli(["edit", str(path), "--op", op, "-o", str(out)], monkeypatch)
    assert code == 0, errs
    made = out.read_text(encoding="utf-8")
    assert "500,000원" in made and "에이전트가 고친 문장" not in made  # built on the file
    drafts = ok(call(env.ctx(), "changes", {}))["drafts"]
    assert len(drafts) == 1 and drafts[0]["rev"] == agent["rev"]  # agent's draft intact
    # -o onto an existing file: refused, nothing written, no draft left behind
    code, stdout, errs = _cli(["edit", str(path), "--op", op, "-o", str(out), "--json"],
                              monkeypatch)
    assert code == 3 and json.loads(stdout)["error"]["code"] == "target_exists"
    assert out.read_text(encoding="utf-8") == made
    assert len(ok(call(env.ctx(), "changes", {}))["drafts"]) == 1
    # --force replaces (the old bytes go to history), still built on the file
    code, _, errs = _cli(["edit", str(path), "--op", json.dumps(
        {"op": "replace", "find": "450,000원", "with": "520,000원"}, ensure_ascii=False),
        "-o", str(out), "--force"], monkeypatch)
    assert code == 0, errs
    assert "520,000원" in out.read_text(encoding="utf-8")
    kept = list((env.home / "history").rglob("*.fdoc"))
    assert any(k.read_text(encoding="utf-8") == made for k in kept)


def test_changes_clean_all_removes_only_our_folders(env, monkeypatch):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "x"}]}))
    keep = env.home / "notes.txt"
    keep.write_text("not ours", encoding="utf-8")
    code, out, _ = _cli(["changes", "clean", "--all", "--json"], monkeypatch)
    assert code == 3 and json.loads(out)["error"]["code"] == "needs_person"
    assert (env.home / "drafts").exists()
    code, out, _ = _cli(["changes", "clean", "--all", "--yes", "--json"], monkeypatch)
    assert code == 0 and not (env.home / "drafts").exists()
    assert keep.read_text(encoding="utf-8") == "not ours"


def test_changes_clean_keeps_recent_state_and_unsaved_work(env, monkeypatch):
    import os
    import time
    unsaved, saved = env.doc("남김.fdoc"), env.doc("저장함.fdoc")
    for path in (unsaved, saved):
        rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
        ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
            {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(saved)}))
    code, out, _ = _cli(["changes", "clean", "--yes", "--json"], monkeypatch)
    assert code == 0 and json.loads(out)["result"]["removed"] == []  # all recent
    old = time.time() - 40 * 86400
    # Windows has no utime(follow_symlinks=False); there are no links here to skip.
    nofollow = os.utime in os.supports_follow_symlinks
    for entry in env.home.rglob("*"):
        if nofollow:
            os.utime(entry, (old, old), follow_symlinks=False)
        elif not entry.is_symlink():
            os.utime(entry, (old, old))
    code, out, _ = _cli(["changes", "clean", "--yes", "--json"], monkeypatch)
    r = json.loads(out)["result"]
    assert code == 0 and r["keptUnsaved"] == 1
    drafts = [p.name for p in (env.home / "drafts").iterdir()]
    assert len(drafts) == 1  # the unsaved one
    assert not (env.home / "history").exists() or not any((env.home / "history").iterdir())


def test_a_mock_proposal_stays_mock_in_the_receipt_and_history(env):
    import rt_commit
    path = env.doc()
    rev0 = ok(call(env.ctx(provenance={"agent": "replay", "mock": True}), "open",
                   {"path": str(path)}))["rev"]
    staged = ok(call(env.ctx(provenance={"agent": "replay", "mock": True}), "edit", {
        "path": str(path), "base": rev0, "ops": [{"op": "set", "at": "p1", "text": "x"}]}))
    shown = ok(call(env.ctx(), "changes", {"action": "show", "path": str(path)}))
    assert [c["provenance"]["mock"] for c in shown["changesets"]] == [True]
    s = ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
    assert s["provenance"]["mock"] is True and s["provenance"]["agents"] == ["replay"]
    assert rt_commit.last_commit(path, env.home)["provenance"]["mock"] is True
    assert staged["changeset"]


def test_a_second_writer_gets_draft_busy_not_a_fork(env):
    import time

    import rt_drafts
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    store = DraftStore(env.home)
    ref = store.ref(path)
    lock = store.lock(ref)
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with lock:
        e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
            {"op": "set", "at": "p1", "text": "x"}]}), "draft_busy")
    assert e["retryable"] is True
    assert time.monotonic() - started < rt_drafts.LOCK_TIMEOUT_S + 1.5


def test_document_text_is_clean_in_errors_and_findings(env):
    path = env.doc("더러움.fdoc", "같은\x1b[31m 말\u202e\n\n같은\x1b[31m 말\u202e\n")
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "말", "with": "다른 말"}]}), "ambiguous_match")
    blob = json.dumps(e, ensure_ascii=False)
    assert "\x1b" not in blob and "\u202e" not in blob
    found = call(env.ctx(), "check", {"path": str(path)})
    blob = json.dumps(found, ensure_ascii=False)
    assert "\x1b" not in blob and "\u202e" not in blob


def test_people_read_korean_and_agents_read_english(env, monkeypatch):
    """Every verb prints Korean to a person; the agent text never leaks into it."""
    path = str(env.doc())
    runs = [
        ["open", path], ["read", path, "--max-chars", "500"], ["find", path, "출장"],
        ["fill", path, "--set", "성명=홍길동"], ["check", path, "--source", "draft"],
        ["preview", path, "--page", "1"], ["changes"], ["changes", "show", path],
        ["save", path, "--to", str(env.work / "사본.fdoc")],
    ]
    agent_words = ("staged in draft", "when done", "saved (", "headings:", "hits for",
                   "change set(s)", "layout signals")
    for argv in runs:
        code, out, errs = _cli(argv, monkeypatch)
        assert code in (0, 3), (argv, errs)
        assert out.strip(), argv
        assert any("가" <= ch <= "힣" for ch in out), (argv, out)
        for word in agent_words:
            assert word not in out, (argv, word, out)


# -- attack review (Sol, P0) ---------------------------------------------------------

def test_new_never_reads_a_file_named_by_a_one_line_body(env):
    # Sol H6: a one-line body naming a file is text, not that file.
    secret = env.work / "비밀.md"
    secret.write_text("# 비밀 내용\n", encoding="utf-8")
    r = ok(call(env.ctx(), "new", {"markdown": str(secret)}))
    text = ok(call(env.ctx(), "read", {"path": r["path"]}))["blocks"][0]["text"]
    assert "비밀 내용" not in text


def _layer_sees(monkeypatch, name):
    """What the document layer's ``name`` receives: (markdown or source text, kwargs)."""
    seen = []
    real = getattr(fake, name)

    def spy(src, out, **kw):
        text = Path(src).read_text(encoding="utf-8") if "\n" not in str(src) else src
        seen.append(text)
        return real(src, out, **kw)

    monkeypatch.setattr(fake, name, spy)
    return seen


def test_new_checks_the_pictures_the_converter_reads(env, tmp_path):
    # The report dialect: a line that is only a picture, or a [그림 n] line.
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    for body in (f"![a]({outside})\n", f"  ![a](<{outside}> \"제목\")\n",
                 f"[그림 1] 시험 ({outside})\n"):
        err(call(env.ctx(), "new", {"dialect": "report", "markdown": body}), "outside_roots")
    inside = env.work / "그림.png"
    inside.write_bytes(b"x")
    ok(call(env.ctx(), "new", {"dialect": "report", "markdown": "![a](그림.png)\n", "base_dir": str(env.work)}))
    err(call(env.ctx(), "new", {"dialect": "report", "markdown": "![a](그림.png)\n", "base_dir": str(tmp_path)}),
        "outside_roots")


def test_a_picture_the_converter_cannot_open_is_refused_not_dropped(env):
    # Sol's re-check (with N5): a picture the converter would not embed must
    # not go missing without a word. In a .md file, ![a](그림(1).png) is text
    # to the converter (a destination holds no brackets), and a folder named
    # as a picture cannot be opened; the agent is told either way.
    (env.work / "그림(1).png").write_bytes(b"x")
    (env.work / "폴더").mkdir()
    source = env.work / "본문.md"
    for body, message in (
            ("본문 ![a](그림(1).png) 끝\n",
             "다음 줄을 그림으로 읽을 수 없어 문서 생성을 중단했습니다(본문 ![a](그림(1).png) 끝)."),
            ("**굵게 ![a](그림(1).png)**\n",
             "다음 줄을 그림으로 읽을 수 없어 문서 생성을 중단했습니다(굵게 ![a](그림(1).png))."),
            ("![a](폴더)\n", "이 그림 경로는 사용할 수 없습니다(폴더).")):
        source.write_text(body, encoding="utf-8")
        e = err(call(env.ctx(), "save", {"path": str(source), "to": str(env.work / "a.hwpx")}),
                "invalid_params")
        assert e["message"] == message
        assert not (env.work / "a.hwpx").exists()
    # in a code span it is code
    source.write_text("문법은 `![a](그림(1).png)` 처럼 쓴다\n", encoding="utf-8")
    ok(call(env.ctx(), "save", {"path": str(source), "to": str(env.work / "a.hwpx")}))


def test_a_long_run_of_unclosed_openers_is_scanned_in_linear_time(env):
    # The converter's pattern bounds every span (md2spec on engine main): the old
    # copy here tried each "[a" against the rest of the text.
    source = env.work / "긴글.md"
    source.write_text("[a" * 200_000 + "\n", encoding="utf-8")
    started = time.perf_counter()
    assert list(rt_toolset._picture_spans(source.read_text("utf-8"), commonmark=True)) == []
    assert time.perf_counter() - started < 5


def test_many_pictures_and_one_the_converter_cannot_open_are_scanned_in_linear_time(env):
    # Fable's review of #396: each opener was looked up in the list of matches
    # from its start, so 40,000 pictures on one line took 40 s.
    text = "![a](b) " * 40_000 + "![z](그림(1).png)\n"
    started = time.perf_counter()
    spans = list(rt_toolset._picture_spans(text, commonmark=True))
    assert time.perf_counter() - started < 5
    assert [kind for *_, kind in spans].count("unread") == 1
    assert [kind for *_, kind in spans].count("image") == 40_000


def test_a_picture_line_the_converter_would_not_read_is_refused(env):
    # Sol's re-check (with N5): "[그림 1] 캡션 (sample (a).png)" and
    # "![표지](sample (a).png)" are text to the converter, so the document got
    # the markdown instead of the picture and nobody was told.
    (env.work / "sample (a).png").write_bytes(b"x")
    (env.work / "사진.PNG").write_bytes(b"x")
    for line in ("![표지](sample (a).png)", "[그림 1] 캡션 (sample (a).png)",
                 "[그림 2] 캡션 (사진.PNG)", "[그림 3] 캡션 (<사진.png>)",
                 "![가](사진.PNG) ![나](사진.PNG)"):
        e = err(call(env.ctx(), "new", {"dialect": "report", "markdown": f"# 제목\n\n{line}\n",
                                        "base_dir": str(env.work)}), "invalid_params")
        assert e["message"] == f"다음 줄을 그림으로 읽을 수 없어 문서 생성을 중단했습니다({line})."
    # in a code block it is code, and from the command line it stays text
    ok(call(env.ctx(), "new", {"dialect": "report", "markdown": "```\n![표지](sample (a).png)\n```\n",
                               "base_dir": str(env.work)}))
    ok(call(env.ctx(roots=None), "new", {"dialect": "report", "markdown": "![표지](sample (a).png)\n",
                                         "base_dir": str(env.work)}))


def test_text_that_is_not_a_picture_is_passed_on_as_written(env, tmp_path, monkeypatch):
    # Sol's re-check N4: the check rewrote every image-like name in brackets,
    # prose and links included. Only what the converter reads as a picture is
    # checked; everything else reaches the layer unchanged.
    seen = _layer_sees(monkeypatch, "new")
    outside = tmp_path / "밖.png"
    outside.write_bytes(b"x")
    for body in (f"![a][r]\n\n[r]: {outside}\n",
                 f'<img src="{outside}">\n',
                 f"참고 그림은 ![a]({outside})에 있습니다.\n",  # mid-sentence: text in plain mode
                 f"```\n![a]({outside})\n```\n",
                 f"출처는 부록입니다 (부록 {outside})\n",
                 "[링크](../../밖.png)\n"):
        ok(call(env.ctx(), "new", {"dialect": "report", "markdown": body}))
        assert seen[-1] == body


def test_a_checked_picture_reaches_the_layer_as_a_copy_of_its_bytes(env, monkeypatch):
    seen = _layer_sees(monkeypatch, "new")
    folder = env.work / "새 폴더 (2)"
    folder.mkdir()
    (folder / "그림.png").write_bytes(b"\x89PNG first")
    body = "# 제목\n\n본문 (괄호) 그대로\n\n![설명](그림.png)\n\n[그림 1] 배치도 (그림.png)\n"
    ok(call(env.ctx(), "new", {"dialect": "report", "markdown": body, "base_dir": str(folder)}))
    sent = seen[-1]
    assert "본문 (괄호) 그대로" in sent and str(folder) not in sent
    copies = [line[line.index("(") + 1:-1] for line in sent.splitlines() if line.endswith(".png)")]
    assert len(copies) == 2 and all(")" not in c for c in copies)
    # the copies were the checked bytes, and are gone once the document is made
    assert not any(Path(c).exists() for c in copies)
    assert not any((env.home / "pictures").glob("*/*"))


def test_a_state_folder_with_brackets_still_takes_pictures(env, tmp_path, monkeypatch):
    # The copies go where the converter can read their path back; a state
    # folder inside a profile named "홍길동 (회사)" cannot be one of those places.
    seen = _layer_sees(monkeypatch, "new")
    (env.work / "그림.png").write_bytes(b"x")
    ctx = env.ctx(_drafts=DraftStore(tmp_path / "상태 (회사)"))
    ok(call(ctx, "new", {"dialect": "report", "markdown": "[그림 1] 배치도 (그림.png)\n", "base_dir": str(env.work)}))
    copy = seen[-1].rsplit("(", 1)[1].rstrip(")\n")
    assert copy.endswith(".png") and "상태" not in copy


def test_a_picture_the_check_did_not_see_stops_the_build(env, tmp_path, monkeypatch):
    # Sol's re-check N3: a syntax the converter reads and this check does not
    # (here the layer reads <img src>) cannot put an unchecked file in the
    # document: the package's pictures must be the checked bytes.
    import re
    import zipfile
    secret = tmp_path / "비밀.png"
    secret.write_bytes(b"secret bytes")
    inside = env.work / "그림.png"
    inside.write_bytes(b"checked bytes")
    real = fake.new

    def new(src, out, **kw):
        r = real(src, out, **kw)
        text = str(src)
        pics = [m.group(1) for m in re.finditer(r'(?:!\[[^\]]*\]\(|<img src=")([^)"]+)', text)]
        Path(out).unlink()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("Contents/section0.xml", "<sec/>")
            for i, pic in enumerate(pics, 1):
                z.writestr(f"BinData/image{i}.png", Path(pic).read_bytes())
        return r

    monkeypatch.setattr(fake, "new", new)
    ok(call(env.ctx(), "new", {"dialect": "report", "markdown": f"![a]({inside})\n"}))
    before = sorted(p.name for p in (env.home / "drafts").glob("*")) \
        if (env.home / "drafts").exists() else []
    e = err(call(env.ctx(), "new", {"dialect": "report", "markdown": f'![a]({inside})\n\n<img src="{secret}">\n'}),
            "invalid_params")
    assert e["at"] == "BinData/image2.png"
    after = sorted(p.name for p in (env.home / "drafts").glob("*")) \
        if (env.home / "drafts").exists() else []
    assert len(after) <= len(before) + 1
    assert not any(p.read_bytes() == b"secret bytes" for p in env.home.rglob("*") if p.is_file())


def _markdown_converter(monkeypatch, *, also=r"(?!)"):
    """The fake's convert, plus what the real one does with pictures: each
    ![](path) (and anything ``also`` matches) goes into the package."""
    import re
    import zipfile
    real = fake.convert
    calls = []

    def convert(src, out, *, to):
        calls.append((Path(src).suffix, to))
        if Path(src).suffix == ".hwpx":  # the fake cannot read a package: copy it
            Path(out).write_bytes(Path(src).read_bytes())
            return {"ok": True, "out": str(out), "lossy": []}
        r = real(src, out, to=to)
        if to == "hwpx" and Path(src).suffix == ".md":
            text = Path(src).read_text(encoding="utf-8")
            pics = [next(g for g in m.groups() if g) for m in
                    re.finditer(r"!\[[^\]]*\]\(([^)]+)\)|" + also, text)]
            with zipfile.ZipFile(out, "a") as z:
                for i, pic in enumerate(pics, 1):
                    z.writestr(f"BinData/image{i}.png", Path(pic).read_bytes())
        return r

    monkeypatch.setattr(fake, "convert", convert)
    return calls


def _pictures_in(package):
    import zipfile
    with zipfile.ZipFile(package) as z:
        return [z.read(n) for n in z.namelist() if n.startswith("BinData/")]


def test_a_replaced_picture_is_converted_again(env, monkeypatch):
    # Sol's re-check N5: the converted file was kept per revision of the
    # markdown alone, so a picture replaced on disk was saved stale.
    calls = _markdown_converter(monkeypatch)
    picture = env.work / "그림.png"
    picture.write_bytes(b"first")
    source = env.work / "본문.md"
    source.write_text("# 제목\n\n본문 ![그림](그림.png) 끝\n", encoding="utf-8")
    ok(call(env.ctx(), "save", {"path": str(source), "to": str(env.work / "1.hwpx")}))
    assert _pictures_in(env.work / "1.hwpx") == [b"first"]
    picture.write_bytes(b"second")
    ok(call(env.ctx(), "save", {"path": str(source), "to": str(env.work / "2.hwpx")}))
    assert _pictures_in(env.work / "2.hwpx") == [b"second"]
    assert calls == [(".md", "hwpx"), (".md", "hwpx")]
    # unchanged pictures: the kept file is used
    ok(call(env.ctx(), "save", {"path": str(source), "to": str(env.work / "3.hwpx")}))
    assert len(calls) == 2


def test_saving_markdown_converts_through_a_checked_package(env, tmp_path, monkeypatch):
    calls = _markdown_converter(monkeypatch, also=r'<img src="([^"]+)">')
    (env.work / "그림.png").write_bytes(b"inside")
    source = env.work / "본문.md"
    source.write_text("# 제목\n\n![그림](그림.png)\n", encoding="utf-8")
    target = env.work / "본문.md.hwpx"
    ok(call(env.ctx(), "save", {"path": str(source), "to": str(target)}))
    assert calls == [(".md", "hwpx")] and _pictures_in(target) == [b"inside"]
    secret = tmp_path / "비밀.png"
    secret.write_bytes(b"secret")
    source.write_text(f'# 제목\n\n![그림](그림.png)\n\n<img src="{secret}">\n', encoding="utf-8")
    other = env.work / "다른.hwpx"
    e = err(call(env.ctx(), "save", {"path": str(source), "to": str(other)}), "invalid_params")
    assert e["at"].startswith("BinData/")
    assert not other.exists()
    exports = env.home / "exports"
    assert not any(p.read_bytes() == b"secret" for p in exports.rglob("*") if p.is_file())


def test_edit_cannot_write_a_signature_seat(env):
    # Sol M14: what fill may not do, edit may not either.
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    for op in ({"op": "fill", "place": "서명", "text": "홍길동"},
               {"op": "set", "at": "place:서명", "text": "홍길동"}):
        e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [op]}),
                "person_only_seat")
        assert e["candidates"] == ["place:서명"]


def test_a_cursor_only_resumes_the_read_it_came_from(env):
    # Sol M8: a cursor from a whole-document read does not resume a read of one block.
    path = env.doc("긴글.fdoc", "\n\n".join(f"문단 {i} " + "가" * 300 for i in range(40)))
    first = ok(call(env.ctx(), "read", {"path": str(path), "max_chars": 1000}))
    err(call(env.ctx(), "read", {"path": str(path), "at": "p3", "cursor": first["next"]}),
        "invalid_params")
    rev = first["rev"]
    err(call(env.ctx(), "read", {"path": str(path), "cursor": f"{rev}:{first['next'].split(':')[1]}:999:0"}),
        "invalid_params")


def test_layout_without_pages_is_not_a_pass(env, monkeypatch):
    # Sol M6: no page list is no evidence.
    path = env.doc()
    monkeypatch.setattr(fake, "pages", lambda p: {"ok": True, "pages": []})
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["layout"]}))
    assert r["checks"]["layout"]["state"] == "unavailable" and r["pass"] is None


def test_guard_against_a_draft_compares_with_that_draft(env):
    # Sol M7: `against: draft:<id>` is that draft's head, not this file's source.
    path = env.doc()
    other = ok(call(env.ctx(), "new", {"markdown": "# 전혀 다른 문서\n\n금액 1원\n"}))
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    r = ok(call(env.ctx(), "check", {"path": str(path), "only": ["guard"],
                                      "against": other["path"]}))
    assert r["checks"]["guard"]["against"] != str(path)


def test_cli_usage_errors_are_json_when_asked(env, monkeypatch):
    # Sol L1: --json means stdout is one JSON document, even for a bad command line.
    for argv in (["open", "--json"], ["edit", str(env.doc()), "--json"]):
        code, out, _ = _cli(argv, monkeypatch)
        assert code == 2 and json.loads(out)["error"]["code"] == "invalid_params"


def test_cli_convert_checks_the_format_against_the_name(env, monkeypatch):
    # Sol M10: --to pdf -o x.hwpx is a mistake, said as one.
    path = env.doc()
    code, out, _ = _cli(["convert", str(path), "--to", "pdf", "-o",
                         str(env.work / "x.fdoc"), "--json"], monkeypatch)
    assert code == 2 and json.loads(out)["error"]["code"] == "invalid_params"


def test_cli_dash_o_keeps_the_edit_when_the_save_fails(env, monkeypatch):
    # Sol M12: a failed save does not throw away the one-shot edit.
    path = env.doc()
    blocked = env.work / "없는폴더" / "out.fdoc"
    code, out, _ = _cli(["edit", str(path), "--op",
                         json.dumps({"op": "set", "at": "p1", "text": "남길 문장"}),
                         "-o", str(blocked), "--json"], monkeypatch)
    e = json.loads(out)["error"]
    assert code != 0 and Path(e["data"]["kept"]).exists()


def test_dash_o_is_create_only_all_the_way_to_the_commit(env):
    # Sol M3: the CLI checks OUT is absent, then sets create_only; a file
    # that appears in between is refused, not asked about.
    path = env.doc()
    target = env.work / "나중.fdoc"
    ctx = env.ctx(client="cli", roots=None, ask=lambda q, d: True)
    ctx.create_only = True
    rev0 = ok(call(ctx, "open", {"path": str(path)}))["rev"]
    ok(call(ctx, "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "x"}]}))
    target.write_text("someone else's", encoding="utf-8")  # appeared after the check
    err(call(ctx, "save", {"path": str(path), "to": str(target)}), "target_exists")
    assert target.read_text(encoding="utf-8") == "someone else's"


def test_save_rechecks_the_draft_after_asking(env):
    # Sol H4: an edit that lands while the person decides is not lost or saved unseen.
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "처음 고침"}]}))

    def meanwhile(question, detail):
        head = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
        ok(call(env.ctx(), "edit", {"path": str(path), "base": head, "ops": [
            {"op": "set", "at": "p1", "text": "그사이 고침"}]}))
        return True

    before = path.read_bytes()
    e = err(call(env.ctx(ask=meanwhile), "save", {"path": str(path)}), "stale")
    assert e["data"]["reason"] == "superseded_by_newer_candidate"
    assert path.read_bytes() == before
    shown = ok(call(env.ctx(), "changes", {"action": "show", "path": str(path)}))
    assert len(shown["changesets"]) == 2


def test_clean_refuses_a_folder_that_is_not_ours(env, monkeypatch, tmp_path):
    # Sol M13: RIGORLOOM_HOME pointed at the wrong folder must not lose its "drafts".
    other = tmp_path / "someone"
    (other / "drafts").mkdir(parents=True)
    (other / "drafts" / "keep.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("RIGORLOOM_HOME", str(other))
    code, out, _ = _cli(["changes", "clean", "--all", "--yes", "--json"], monkeypatch)
    assert code == 2 and (other / "drafts" / "keep.txt").exists()


def test_a_client_lists_only_drafts_inside_its_roots(env, tmp_path):
    # Sol M5: one state folder, two differently scoped clients.
    mine = env.doc()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    theirs = elsewhere / "남의.fdoc"
    theirs.write_text(FORM, encoding="utf-8")
    for path, roots in ((mine, Roots.of([env.work])), (theirs, Roots.of([elsewhere]))):
        ctx = env.ctx(roots=roots)
        rev0 = ok(call(ctx, "open", {"path": str(path)}))["rev"]
        ok(call(ctx, "edit", {"path": str(path), "base": rev0, "ops": [
            {"op": "set", "at": "p1", "text": "x"}]}))
    listed = ok(call(env.ctx(), "changes", {}))["drafts"]
    assert [Path(d["source"]).name for d in listed] == [mine.name]


def test_disk_view_says_when_the_file_moved_under_the_draft(env):
    # Sol M9: status comes from the file as it is now.
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "x"}]}))
    path.write_text(FORM + "\n밖에서 고침\n", encoding="utf-8")
    seen = ok(call(env.ctx(source="disk"), "open", {"path": str(path)}))
    assert seen["draft"]["sourceChanged"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_state_folder_is_owner_only(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "x"}]}))
    for folder in (env.home, env.home / "drafts"):
        assert folder.stat().st_mode & 0o077 == 0, oct(folder.stat().st_mode)


# -- what a person at the terminal sees (the P0 UX review) ------------------------

def test_changes_with_just_a_file_shows_that_file(env, monkeypatch):
    path = env.doc()
    _cli(["fill", str(path), "--set", "성명=홍길동"], monkeypatch)
    code, out, errs = _cli(["changes", str(path)], monkeypatch)
    assert code == 0, errs
    assert "초안 1판" in out and "초안 편집 기록" in out


def test_a_mistyped_command_gets_a_korean_line_not_the_protocol_parser(monkeypatch):
    import cli
    out, errs = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", errs)
    assert cli.main(["opn", "a.hwpx"]) == 2
    assert out.getvalue() == ""
    assert "알 수 없는 명령입니다: opn" in errs.getvalue() and "open" in errs.getvalue()
    assert "capabilities" not in errs.getvalue()
    assert rt_cli_product.is_unknown(["opn"], {"guard"})
    assert not rt_cli_product.is_unknown(["guard"], {"guard"})
    assert not rt_cli_product.is_unknown(["--root", "/w", "bogus"], {"guard"})


@pytest.mark.parametrize("verb", ["open", "read", "find", "edit", "fill", "new", "preview",
                                  "check", "save", "changes", "undo", "convert", "guide"])
def test_every_verb_help_is_korean_with_examples(verb, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert rt_cli_product.main([verb, "--help"]) == 0
    text = out.getvalue()
    assert text.startswith("사용법: rigorloom " + verb)
    assert "옵션:" in text and "show this help" not in text and "options:" not in text
    assert f"예:\n  rigorloom {verb}" in text
    if verb in ("save", "undo", "guide", "changes", "edit", "fill", "new", "convert"):
        assert "--source" not in text  # only verbs that read take it


def test_a_person_at_the_terminal_may_say_yes_after_a_no(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    answers = [False, True]
    asked = []

    def person(question, detail):
        asked.append(question)
        return answers.pop(0)

    e = err(call(env.ctx(client="cli", ask=person), "save", {"path": str(path)}),
            "declined_by_person")
    assert "--to" in e["hint"] and "(to)" not in e["hint"]
    # An agent may not ask again for these bytes...
    err(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}), "declined_by_person")
    # ...but the person who said no may run save again and say yes.
    ok(call(env.ctx(client="cli", ask=person), "save", {"path": str(path)}))
    assert len(asked) == 2 and "고친 문장" in path.read_text(encoding="utf-8")


def test_undo_says_there_is_nothing_before_asking(env, monkeypatch):
    path = env.doc()
    asked = []
    monkeypatch.setattr(rt_cli_product, "confirm", lambda *a, **k: asked.append(a) or True)
    code, out, errs = _cli(["undo", str(path)], monkeypatch)
    assert code == 2 and asked == []
    assert "되돌릴 저장 기록이 없습니다" in errs


def test_a_second_fill_lists_only_seats_still_empty(env, monkeypatch):
    path = env.doc()
    _cli(["fill", str(path), "--set", "성명=홍길동"], monkeypatch)
    code, out, errs = _cli(["fill", str(path), "--set", "소속=총무과", "--json"], monkeypatch)
    assert code == 0, errs
    r = json.loads(out)["result"]
    assert r["unfilled"] == [] and r["filled"] == [{"place": "place:소속", "text": "총무과"}]
    code, out, _ = _cli(["fill", str(path), "--set", "소속=기획과"], monkeypatch)
    assert code == 0 and "채운 칸: place:소속" in out


def test_a_misnamed_op_field_names_the_right_one(env):
    path = env.doc()
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "출장", "new": "파견"}]}), "invalid_params")
    assert "'new' 대신 'with'" in e["message"] and '"with"' in e["hint"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "replace", "find": "출장"}]}), "invalid_params")
    assert "'with'" in e["message"] and e["hint"].startswith("예: ")


def test_reading_the_file_says_a_draft_is_waiting(env, monkeypatch):
    path = env.doc()
    _cli(["fill", str(path), "--set", "성명=홍길동"], monkeypatch)
    code, out, errs = _cli(["read", str(path), "--at", "place:성명"], monkeypatch)
    assert code == 0 and "저장 안 한 초안(1판)" in errs and "--source draft" in errs
    code, out, errs = _cli(["read", str(path), "--source", "draft"], monkeypatch)
    assert code == 0 and errs == ""


def test_document_layer_english_becomes_korean_for_people():
    from rt_cli_render import candidates_line, person_error
    msg, hint = person_error({"code": "capability_unavailable",
                              "message": ".hwp files need the HWP engine; only .hwpx is "
                                         "supported without it"}, "a.hwp")
    assert msg.startswith("'.hwp' 파일은") and "doctor" in hint
    msg, hint = person_error({"code": "bad_address", "at": "p999",
                              "message": "the document has 3 top-level paragraphs (p0..p2)"},
                             "a.hwpx")
    assert "p0부터 p2까지" in msg and "--at p2" in hint
    msg, hint = person_error({"code": "invalid_params", "message":
                              "a markdown file is not a document here; use new() or convert()"},
                             "초안.md")
    assert "rigorloom new" in hint and "new()" not in msg + hint
    assert person_error({"code": "stale", "message": "이미 한국어"}) == ("이미 한국어", None)
    msg, _ = person_error({"code": "ambiguous_match",
                           "message": "'근로' occurs 2 times; narrow it with at"})
    assert msg.startswith("찾는 말이 여러 곳에")
    assert candidates_line([f"t0/r{i}" for i in range(11)]) == "t0/r0 ~ t0/r10 (11개)"
    # Past the end is bad_address with a range (doc-core-api ruling 2026-11-19).
    assert person_error({"code": "bad_address", "at": "page:9", "range": [1, 3],
                         "message": "page 9 is out of range"}) == (
        "page:9: 문서에 없는 쪽입니다.", "1쪽부터 3쪽까지 있습니다.")
    assert person_error({"code": "bad_address", "at": "p2:40", "range": [0, 12],
                         "message": "offset 40 is out of range"}) == (
        "p2:40: 범위를 벗어난 위치입니다.", "위치는 0부터 12까지 지정할 수 있습니다.")
    assert person_error({"code": "locked", "message": "file is locked", "retryable": True}) == (
        "다른 프로그램에서 이 파일을 열어 두었습니다.", "파일을 열어 둔 프로그램에서 닫은 뒤 다시 실행하세요.")


def test_a_narrow_find_keeps_the_word_in_view():
    from rt_cli_render import around
    text = "가" * 40 + "임금" + "나" * 40
    cut = around(text, "임금", 30)
    assert "임금" in cut
    from rt_term import width
    assert width(cut) <= 30


def test_long_findings_wrap_instead_of_losing_the_end():
    from rt_cli_render import show_check
    from rt_term import Term
    out = io.StringIO()
    term = Term(stream=out, color=False, columns=60, interactive=False)
    tail = "끝에서 바뀐 말 제18조"
    show_check(term, {"path": "a.hwpx", "source": "disk", "pass": False,
                      "checks": {"guard": {"state": "failed"}},
                      "findings": [{"severity": "warning", "at": "p2",
                                    "message": "숫자가 바뀌었습니다: " + "앞부분 " * 12 + tail}]})
    joined = " ".join(line.strip() for line in out.getvalue().splitlines())
    assert tail in joined and "…" not in out.getvalue()



# -- Sol re-check of the save path (83005c8..d9caf52) -----------------------------

def _edited(env, name="신청서.fdoc"):
    path = env.doc(name)
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "고친 문장"}]}))
    return path


def test_force_is_recorded_as_force_not_as_a_terminal_yes(env, monkeypatch):
    # F1: --force without a terminal used to land in history as person:tty.
    path = _edited(env)
    code, out, errs = _cli(["save", str(path), "--force", "--json"], monkeypatch)
    assert code == 0, errs
    assert json.loads(out)["result"]["acceptedVia"] == "person:force"


def test_force_does_not_override_a_no(env, monkeypatch):
    # F1: a "no" given for these bytes is undone only by answering again.
    path = _edited(env)
    before = path.read_bytes()
    err(call(env.ctx(ask=lambda q, d: False), "save", {"path": str(path)}),
        "declined_by_person")
    code, out, errs = _cli(["save", str(path), "--force", "--json"], monkeypatch)
    assert code == 3 and json.loads(out)["error"]["code"] == "declined_by_person"
    assert path.read_bytes() == before


def test_a_new_draft_on_the_same_path_does_not_own_the_old_drafts_file(env, monkeypatch):
    # F2: discard, edit again, save --to the file the old draft created: ask.
    path = _edited(env)
    copy = env.work / "사본.fdoc"
    assert ok(call(env.ctx(), "save", {"path": str(path), "to": str(copy)}))[
        "acceptedVia"] == "policy:new-file"
    code, _, errs = _cli(["changes", "discard", str(path)], monkeypatch)
    assert code == 0, errs
    rev0 = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev0, "ops": [
        {"op": "set", "at": "p1", "text": "다시 고친 문장"}]}))
    asked = []
    err(call(env.ctx(ask=lambda q, d: asked.append(q) or None), "save",
             {"path": str(path), "to": str(copy)}), "needs_person")
    assert len(asked) == 1


def test_undo_reverses_only_the_save_the_person_was_shown(env, monkeypatch):
    # F3: a save that lands while the question is open is not the one undone.
    import rt_commit
    path = _edited(env)
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))

    def meanwhile(*a, **k):
        rev = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
        ok(call(env.ctx(), "edit", {"path": str(path), "base": rev, "ops": [
            {"op": "set", "at": "p1", "text": "그사이 고친 문장"}]}))
        ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
        return True

    monkeypatch.setattr(rt_cli_product, "confirm", meanwhile)
    code, out, errs = _cli(["undo", str(path), "--json"], monkeypatch)
    assert code != 0 and json.loads(out)["error"]["code"] == "stale"
    assert "그사이 고친 문장" in path.read_text(encoding="utf-8")
    assert not rt_commit.last_commit(path).get("undone")


def test_undo_of_a_created_file_puts_back_bytes_that_are_not_ours(env, monkeypatch):
    # F3: the removal branch checks what it moved and puts foreign bytes back.
    import rt_commit
    path = _edited(env)
    new = env.work / "새파일.fdoc"
    ok(call(env.ctx(), "save", {"path": str(path), "to": str(new)}))
    real = rt_commit._last_undoable

    def check_then_someone_writes(*a, **k):
        entry = real(*a, **k)
        new.write_bytes(b"someone else")
        return entry

    monkeypatch.setattr(rt_commit, "_last_undoable", check_then_someone_writes)
    with pytest.raises(rt_tools.ToolError) as caught:
        rt_commit.undo(new, by="test")
    assert caught.value.code == "target_changed"
    assert new.read_bytes() == b"someone else"


def test_the_undo_question_shows_the_name_exactly(env, monkeypatch):
    # F5: "review  copy" must not be shown as "review copy".
    path = _edited(env, "검토  사본.fdoc")
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
    asked = []
    monkeypatch.setattr(rt_cli_product, "confirm", lambda q, **k: asked.append(q) or False)
    monkeypatch.chdir(env.work)
    _cli(["undo", str(path)], monkeypatch)
    assert asked and '"검토  사본.fdoc"' in asked[0]


def test_an_empty_save_path_is_refused_not_read_as_the_source(env, monkeypatch):
    # F6: --to '' used to drop the argument and save over the source.
    path = _edited(env)
    before = path.read_bytes()
    for argv in (["save", str(path), "--to", "", "--force"],
                 ["edit", str(path), "--op", '{"op":"set","at":"p1","text":"x"}', "-o", ""]):
        code, _, errs = _cli(argv, monkeypatch)
        assert code == 2 and "저장할 경로가 비어 있습니다" in errs, argv
    assert path.read_bytes() == before


def test_a_no_on_record_is_asked_again_even_over_the_drafts_own_file(env):
    # F1, round 2: decline, put the draft's own bytes back, save again: ask.
    path = _edited(env)
    copy = env.work / "사본.fdoc"
    ok(call(env.ctx(), "save", {"path": str(path), "to": str(copy)}))
    mine = copy.read_bytes()
    head = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": head, "ops": [
        {"op": "set", "at": "p1", "text": "또 고친 문장"}]}))
    copy.write_bytes(b"someone else")
    err(call(env.ctx(client="cli", ask=lambda q, d: False), "save",
             {"path": str(path), "to": str(copy)}), "declined_by_person")
    copy.write_bytes(mine)
    asked = []
    err(call(env.ctx(client="cli", ask=lambda q, d: asked.append(q) or None), "save",
             {"path": str(path), "to": str(copy)}), "needs_person")
    assert asked and copy.read_bytes() == mine


def test_a_draft_replaced_while_saving_is_not_saved_as_the_old_one(env, monkeypatch):
    # F2, round 2: the instance checked for ownership must still be the draft
    # under the lock.
    path = _edited(env)
    copy = env.work / "사본.fdoc"
    ok(call(env.ctx(), "save", {"path": str(path), "to": str(copy)}))
    head = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": head, "ops": [
        {"op": "set", "at": "p1", "text": "또 고친 문장"}]}))
    before = copy.read_bytes()
    real = DraftStore.input_for

    def swapped(self, ref, **kw):
        result = real(self, ref, **kw)
        record = self.load(ref)
        record["instance"] = "someone-else"
        self.write(ref, record)
        return result

    monkeypatch.setattr(DraftStore, "input_for", swapped)
    err(call(env.ctx(), "save", {"path": str(path), "to": str(copy)}), "stale")
    assert copy.read_bytes() == before


def test_a_draft_without_an_instance_never_owns_what_it_saved(env):
    # F2, round 2: records from before the instance id (and plain conversions)
    # are asked about every time.
    path = _edited(env)
    ctx = env.ctx()
    ref = rt_toolset.resolve(ctx, str(path))
    record = ctx.drafts.load(ref)
    record.pop("instance")
    ctx.drafts.write(ref, record)
    copy = env.work / "사본.fdoc"
    ok(call(env.ctx(), "save", {"path": str(path), "to": str(copy)}))
    head = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    ok(call(env.ctx(), "edit", {"path": str(path), "base": head, "ops": [
        {"op": "set", "at": "p1", "text": "또 고친 문장"}]}))
    asked = []
    err(call(env.ctx(ask=lambda q, d: asked.append(q) or None), "save",
             {"path": str(path), "to": str(copy)}), "needs_person")
    assert len(asked) == 1


def test_undo_reports_a_file_error_as_json(env, monkeypatch):
    # F3, round 2: an OS error during undo is an error envelope, not a traceback.
    import rt_commit
    path = _edited(env)
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))
    monkeypatch.setattr(rt_cli_product, "confirm", lambda *a, **k: True)

    def denied(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(rt_commit, "undo", denied)
    code, out, _ = _cli(["undo", str(path), "--json"], monkeypatch)
    assert code == 4 and json.loads(out)["error"]["code"] == "internal"


def test_a_draft_discarded_while_saving_is_not_saved(env, monkeypatch):
    # F2, round 3: a discard during the question leaves nothing to publish and
    # must not bring the draft record back.
    path = _edited(env)
    copy = env.work / "사본.fdoc"
    copy.write_bytes(b"theirs")
    ctx = env.ctx(client="cli")

    def person(question, detail):
        ref = rt_toolset.resolve(ctx, str(path))
        ctx.drafts.remove(ref)
        return True

    ctx.ask = person
    err(call(ctx, "save", {"path": str(path), "to": str(copy)}), "stale")
    assert copy.read_bytes() == b"theirs"
    assert ctx.drafts.load(rt_toolset.resolve(ctx, str(path))) is None


def test_undo_says_where_the_file_is_when_the_record_cannot_be_written(env, monkeypatch):
    # F3, round 3: undo finished; only the history write failed.
    import rt_commit
    path = _edited(env)
    new = env.work / "새파일.fdoc"
    ok(call(env.ctx(), "save", {"path": str(path), "to": str(new)}))
    real = rt_commit._save_index

    def full(folder, entries):
        if any(e.get("undone") for e in entries):
            raise OSError(28, "No space left on device")
        return real(folder, entries)

    monkeypatch.setattr(rt_commit, "_save_index", full)
    with pytest.raises(rt_tools.ToolError) as caught:
        rt_commit.undo(new, by="test")
    kept = Path(caught.value.data["kept"])
    assert not new.exists() and kept.exists()
    assert str(kept) in caught.value.hint


def test_undo_reports_an_unreadable_file_before_asking(env, monkeypatch):
    # F3, round 3: a read error before the question is a JSON error too.
    import rt_commit
    path = _edited(env)
    ok(call(env.ctx(ask=lambda q, d: True), "save", {"path": str(path)}))

    def unreadable(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(rt_commit, "undoable", unreadable)
    code, out, _ = _cli(["undo", str(path), "--json"], monkeypatch)
    assert code == 4 and json.loads(out)["error"]["code"] == "internal"


# -- new reads CommonMark unless asked for the report dialect (P7 round 1) ------

def _new_calls(monkeypatch):
    """Each call to the layer's new: (source given, markdown it read, kwargs, files beside it)."""
    seen = []
    real = fake.new

    def spy(src, out, **kw):
        path = Path(src) if "\n" not in str(src) else None
        text = path.read_text(encoding="utf-8") if path else src
        beside = sorted(p.name for p in path.parent.iterdir()) if path else []
        seen.append((str(src), text, kw, beside))
        return real(src, out, **kw)

    monkeypatch.setattr(fake, "new", spy)
    return seen


def test_new_reads_commonmark_from_a_file_beside_its_pictures(env, monkeypatch):
    # In round 0 every agent that wrote a report put a GFM table and a list in
    # new's markdown and got their pipes and dashes back as text. CommonMark is
    # read from a .md file, and the converter takes pictures only from its folder.
    seen = _new_calls(monkeypatch)
    (env.work / "그림.png").write_bytes(b"\x89PNG x")
    body = ("# 1. 개요\n\n- 첫째\n- 둘째\n\n| 구분 | 내용 |\n|---|---|\n| 가 | 나 |\n\n"
            "![배치도](그림.png)\n")
    ok(call(env.ctx(), "new", {"markdown": body, "base_dir": str(env.work)}))
    src, text, kw, beside = seen[-1]
    assert kw == {"commonmark": True} and src.endswith("content.md")
    assert text.startswith("# 1. 개요\n\n- 첫째\n- 둘째\n\n| 구분 | 내용 |\n|---|---|\n| 가 | 나 |")
    assert "![배치도](1.png)" in text and beside == ["1.png", "content.md"]
    assert not Path(src).exists()  # the file and the copies are gone once the draft is made


def test_new_in_commonmark_checks_a_picture_inside_a_sentence(env, tmp_path):
    # Text in the report dialect, a picture in CommonMark: so it is checked.
    outside = tmp_path / "밖.png"
    outside.write_bytes(b"x")
    err(call(env.ctx(), "new", {"markdown": f"참고 그림은 ![a]({outside})에 있습니다.\n"}),
        "outside_roots")
    ok(call(env.ctx(), "new", {"markdown": f"참고 그림은 ![a]({outside})에 있습니다.\n",
                               "dialect": "report"}))


def test_new_reads_the_report_dialect_when_asked(env, monkeypatch):
    seen = _new_calls(monkeypatch)
    ok(call(env.ctx(), "new", {"markdown": "□ 개요\n", "dialect": "report"}))
    src, text, kw, _ = seen[-1]
    assert src == "□ 개요\n" and "commonmark" not in kw


def test_a_form_takes_only_the_report_dialect(env):
    form = env.doc()
    e = err(call(env.ctx(), "new", {"markdown": "# 제목\n", "form": str(form),
                                    "dialect": "commonmark"}), "invalid_params")
    assert e["message"] == "양식으로 문서를 만들 때는 보고서 문법(report)만 사용할 수 있습니다."


def test_the_cli_passes_the_dialect(env):
    (env.work / "보고서.md").write_text("□ 개요\n", encoding="utf-8")
    args = rt_cli_product._parser().parse_args(
        ["new", str(env.work / "보고서.md"), "--dialect", "report"])
    assert rt_cli_product.request_for(args)[1]["dialect"] == "report"


# -- messages an agent tripped on in round 0 -----------------------------------

def test_an_op_named_as_a_key_is_told_where_the_name_goes(env):
    path = env.doc()
    rev = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev, "ops": [
        {"insert_after": {"at": "p1", "markdown": "x"}}]}), "invalid_params")
    assert e["message"] == "ops[0]: 작업 이름을 지정하는 'op' 항목이 없습니다."
    assert e["hint"] == "예: " + rt_toolset.OP_EXAMPLES["insert_after"]


def test_insert_after_refuses_a_table_it_would_write_as_text(env):
    path = env.doc()
    rev = ok(call(env.ctx(), "open", {"path": str(path)}))["rev"]
    e = err(call(env.ctx(), "edit", {"path": str(path), "base": rev, "ops": [
        {"op": "insert_after", "at": "p1",
         "markdown": "| 구분 | 결과 |\n| --- | --- |\n| 시료 | 42건 |"}]}), "invalid_params")
    assert e["message"].startswith("ops[0]: insert_after는 각 줄을 일반 문단으로 넣습니다.")
    # a line with a dash in it is not a table
    ok(call(env.ctx(), "edit", {"path": str(path), "base": rev, "ops": [
        {"op": "insert_after", "at": "p1", "markdown": "기간: 11. 3. - 11. 5."}]}))


def test_guide_names_only_the_topics_it_has(monkeypatch, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setattr(rt_toolset, "KNOWLEDGE_DIR", empty)
    assert rt_toolset._guide_description() == (
        "Korean document conventions. This build has no guides installed, "
        "so there is nothing to read here.")
    (empty / "gongmun.md").write_text("# 공문\n", encoding="utf-8")
    (empty / "extra.md").write_text("# 기타\n", encoding="utf-8")
    assert rt_toolset._guide_description() == (
        "Korean document conventions with sources: extra, gongmun (공문 항목 기호, 날짜 표기, "
        "‘끝.’ 표시, 붙임). Read the one that fits before writing.")


def test_a_substituted_font_is_named_or_called_another_font():
    assert rt_toolset._face(None) == "다른 글꼴로"
    assert rt_toolset._face("Noto Serif CJK KR") == "Noto Serif CJK KR로"
    assert rt_toolset._face("나눔명조") == "나눔명조로"
    assert rt_toolset._face("본고딕") == "본고딕으로"
    assert rt_toolset._fonts_line({"substituted": [{"want": "함초롬바탕", "got": None}]}) == \
        "fonts substituted: 함초롬바탕→? (page breaks may differ from Hancom)"
