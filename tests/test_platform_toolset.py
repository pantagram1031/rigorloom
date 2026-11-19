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
    assert "초안 있음: 수정본 1" in rt_tools.render_text(REGISTRY["open"], disk)
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

def test_fill_refuses_signature_seats_and_reports_what_is_left(env):
    path = env.doc()
    e = err(call(env.ctx(), "fill", {"path": str(path), "values": {
        "place:성명": "홍길동", "place:서명": "홍길동"}}), "person_only_seat")
    assert e["candidates"] == ["place:서명"]
    e = err(call(env.ctx(), "fill", {"path": str(path), "values": {"place:셩명": "x"}}),
            "not_found")
    assert "place:성명" in e["candidates"]
    r = ok(call(env.ctx(), "fill", {"path": str(path), "values": {"성명": "홍길동"}}))
    assert r["personOnly"] == ["place:서명"] and r["unfilled"] == ["place:소속"]
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
    assert r["checks"]["layout"]["state"] == "unavailable" and r["pass"] is True


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
    assert "saved (created)" in stdout


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
