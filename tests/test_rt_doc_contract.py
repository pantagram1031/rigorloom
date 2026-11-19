# -*- coding: utf-8 -*-
"""The rt_doc contract test: ONE file that the fake and the real ``rt_doc`` both pass.

Contract: doc-core-api.md (draft 1, 2026-11-19) plus ruling 1, section 2 item 7
(a non-unique ``replace`` without ``all`` refuses with candidates), as the real
``rt_doc`` implements it (docs/doc-core.md, PR #388). Where the two differ the
real layer wins: the engine thread owns rt_doc's API, and this file describes
only what the platform relies on. Every test
checks an invariant a caller relies on, never formatting, and never something
the contract leaves open. Where the contract is open, the test accepts every
reading (see ``_hit_agrees``) and the fake's own choice is pinned in
tests/test_fake_rt_doc.py instead.

Implementations are a list of ``Impl(name, load, make)``:

* ``fake`` (tests/_fake_rt_doc.py) is always present; ``make`` writes the spec
  as an ``.fdoc`` file.
* ``rt_doc`` is present only when ``import rt_doc`` works with runtime/scripts
  on ``sys.path``. ``make`` copies a committed fixture whose content is the
  spec's family (tests/fixtures/rt_doc_contract/<family>.hwpx; what each
  contains is written in tests/_rt_doc_contract_fixtures.py):
  - ``basic.hwpx``: headings 사업 개요 (1) / 추진 배경 (2) / 세부 계획 (2) on styles
    개요 1-2, four body paragraphs, one 3x2 table (항목|금액(천원), 인건비|7,000,
    재료비|5,000), a page break before 세부 계획, and two CLICK_HERE fill seats
    named ``applicant`` (신청인) and ``written_on`` (작성일).

When the real ``rt_doc`` answers ``capability_unavailable`` for a call a test
needs (it does so without the engine for render, pages and some edit ops), the
test is skipped for that implementation only, the reason names the call, and
the list is printed at the end of the module. The fake never skips: a fake
that answers ``capability_unavailable`` for a contract call fails.

Errors: the platform reads ``code``, ``message`` and ``retryable``, and ``at``
and ``candidates`` when present; those are checked and any other key is
allowed (the real rt_doc adds ``i``, ``step``, ``done``, ``reason``, ``rev``,
``total``, ``expected``, ``actual``). Codes are the real layer's:
``bad_address`` for an address that is malformed or does not resolve,
``bad_input`` for a malformed request, ``not_found`` for a missing file.

Known gaps (``KNOWN_GAPS``): where the real rt_doc without the engine silently
does less than the platform relies on, instead of answering
``capability_unavailable``, the test is a strict xfail for that implementation
only. It still runs; the day rt_doc does the thing, it XPASSes and the run
fails until the entry is removed. Each gap is reported to the engine thread.

Run:  python -m pytest -q tests/test_rt_doc_contract.py
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "runtime" / "scripts"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _rt_doc_contract_fixtures as fx  # noqa: E402

REV = re.compile(r"[0-9a-f]{12}")

#: gap -> what the real rt_doc, without the engine, does instead of what the platform needs.
#: None at the moment: #388 (baf5e10) lists CLICK_HERE fields as places without the engine,
#: which closed "fill_seats".
KNOWN_GAPS: dict[str, str] = {}
#: (implementation, test, gap) marked strict-xfail. Printed at module teardown.
GAPS: list[str] = []

#: (implementation, test, call) skipped because the implementation answered
#: capability_unavailable. Printed at module teardown, and each skip reason says it too.
SKIPPED: list[str] = []


# --------------------------------------------------------------------------- implementations
@dataclass(frozen=True)
class Impl:
    name: str
    load: Callable[[], object]
    make: Callable[[Path, dict], Path]

    @property
    def mod(self):
        return self.load()


def _load_fake():
    import _fake_rt_doc
    return _fake_rt_doc


def _make_fake(tmp_path: Path, spec: dict) -> Path:
    return fx.write_fdoc(tmp_path / "doc.fdoc", spec)


def _load_real():
    if str(RUNTIME) not in sys.path:
        sys.path.insert(0, str(RUNTIME))
    return importlib.import_module("rt_doc")


def _make_real(tmp_path: Path, spec: dict) -> Path:
    src = fx.committed_fixture(spec["family"])
    dst = tmp_path / "doc.hwpx"
    shutil.copyfile(src, dst)
    return dst


def _real_importable() -> bool:
    try:
        _load_real()
    except Exception:  # noqa: BLE001 - absent or broken: the real entry is simply not listed
        return False
    return True


IMPLS = [Impl("fake", _load_fake, _make_fake)]
if _real_importable():
    IMPLS.append(Impl("rt_doc", _load_real, _make_real))


@pytest.fixture(params=IMPLS, ids=[i.name for i in IMPLS])
def impl(request) -> Impl:
    return request.param


@pytest.fixture
def doc(impl: Impl, tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    return impl.make(src, fx.BASIC)


@pytest.fixture(scope="module", autouse=True)
def _print_engine_skips(request):
    yield
    lines = []
    if SKIPPED:
        lines += ["rt_doc contract: skipped on capability_unavailable:"] + [f"  {s}" for s in SKIPPED]
    if GAPS:
        lines += ["rt_doc contract: known gaps (strict xfail):"] + [f"  {s}" for s in GAPS]
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        for line in lines:
            reporter.write_line(line)


# --------------------------------------------------------------------------- helpers
def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_envelope(res) -> dict:
    assert isinstance(res, dict), f"result is not a dict: {res!r}"
    assert isinstance(res.get("ok"), bool), f"result has no boolean ok: {res!r}"
    json.dumps(res)  # CLI --json and MCP serialise it as is
    if res["ok"]:
        assert "error" not in res
        return res
    err = res.get("error")
    assert isinstance(err, dict), f"refusal without an error object: {res!r}"
    # What the platform reads. Other keys (i, step, done, reason, rev, ...) are allowed and not read.
    assert isinstance(err.get("code"), str) and err["code"], err
    assert isinstance(err.get("message"), str) and err["message"].strip(), err
    assert isinstance(err.get("retryable"), bool), err
    if err.get("at") is not None:
        assert isinstance(err["at"], str)
    if err.get("candidates") is not None:
        assert isinstance(err["candidates"], list)
        assert all(isinstance(c, str) for c in err["candidates"])
    return res


def call(impl: Impl, fn: str, *args, **kwargs) -> dict:
    """Call an rt_doc function. It must return an envelope, never raise."""
    return _check_envelope(getattr(impl.mod, fn)(*args, **kwargs))


def unless_unavailable(impl: Impl, res: dict, what: str, request) -> dict:
    """Skip when the real rt_doc lacks the capability; the fake may not lack it."""
    if not res["ok"] and res["error"]["code"] == "capability_unavailable":
        if impl.name == "fake":
            pytest.fail(f"the fake answered capability_unavailable for {what}: {res}")
        reason = res["error"].get("reason")
        SKIPPED.append(f"{impl.name} :: {request.node.originalname} :: {what}"
                       + (f" ({reason})" if reason else ""))
        pytest.skip(f"{impl.name}: capability_unavailable for {what}")
    return res


def need(impl: Impl, res: dict, what: str, request) -> dict:
    """The call must succeed, except that the real rt_doc may lack the capability."""
    unless_unavailable(impl, res, what, request)
    assert res["ok"], f"{what} refused: {res}"
    return res


def _engine_absent(impl: Impl) -> bool:
    status = getattr(impl.mod, "engine_status", None)
    return impl.name == "rt_doc" and (status is None or not status().get("available"))


def known_gap(impl: Impl, request, gap: str) -> None:
    """Mark the running test strict-xfail for the real rt_doc without the engine (see KNOWN_GAPS)."""
    if _engine_absent(impl):
        GAPS.append(f"{impl.name} :: {request.node.originalname} :: {gap}")
        request.node.add_marker(pytest.mark.xfail(reason=f"known gap {gap}: {KNOWN_GAPS[gap]}", strict=True))


def refused(res: dict, code: str) -> dict:
    assert res["ok"] is False, f"expected refusal {code}, got {res}"
    assert res["error"]["code"] == code, res["error"]
    return res["error"]


def text_at(impl: Impl, path: Path, at: str) -> str:
    res = call(impl, "read", path, at)
    assert res["ok"], f"read({at}) refused: {res}"
    assert res["blocks"], f"read({at}) returned no block"
    return res["blocks"][0]["text"]


def _hit_agrees(hit: dict, block_text: str, query: str, *, regex: bool = False) -> bool:
    """find's ``text`` is the matched span or the whole paragraph: the contract does not say.

    Either way ``start``/``end`` index the paragraph's text and that span matches the query.
    """
    span = block_text[hit["start"]:hit["end"]]
    matches = re.fullmatch(query, span) is not None if regex else span == query
    return matches and hit["text"] in (span, block_text)


def _mapped(remap: list[dict], at: str):
    """Where ``at`` is after an edit: remap entry for it (or its table), else unchanged."""
    table: dict = {m["from"]: m["to"] for m in remap}
    if at in table:
        return table[at]
    head, sep, rest = at.partition("/")
    if sep and head in table:
        return None if table[head] is None else f"{table[head]}/{rest}"
    return at


def _out(tmp_path: Path, doc: Path, name: str = "out") -> Path:
    d = tmp_path / "outs"
    d.mkdir(exist_ok=True)
    return d / f"{name}{doc.suffix}"


def _unique_hit(impl: Impl, doc: Path) -> dict:
    hits = call(impl, "find", doc, fx.UNIQUE_WORD)["hits"]
    assert len(hits) == 1, hits
    return hits[0]


# --------------------------------------------------------------------------- rev
def test_rev_is_12_hex_of_the_file_and_stable_across_reads(impl, doc):
    before = _sha(doc)
    revs = []
    for _ in range(2):
        revs.append(call(impl, "open", doc)["rev"])
        revs.append(call(impl, "outline", doc)["rev"])
        revs.append(call(impl, "read", doc)["rev"])
        revs.append(call(impl, "read", doc, "p0")["rev"])
        revs.append(call(impl, "find", doc, fx.UNIQUE_WORD)["rev"])
    assert len(set(revs)) == 1, revs
    assert REV.fullmatch(revs[0])
    assert revs[0] == before[:12], "rev is the first 12 hex of the document's sha256"
    assert _sha(doc) == before, "reading changed the file"


def test_open_reports_its_shape(impl, doc):
    res = call(impl, "open", doc)
    assert res["ok"], res
    for key in ("rev", "format", "sections", "fonts", "engine"):
        assert key in res, key
    assert isinstance(res["fonts"].get("used"), list)
    assert isinstance(res["fonts"].get("substituted"), list)


# --------------------------------------------------------------------------- addresses read back
def test_outline_addresses_read_back_with_the_same_text(impl, doc):
    out = call(impl, "outline", doc)
    assert out["ok"], out
    texts = [h["text"] for h in out["headings"]]
    for _, heading in fx.BASIC["headings"]:
        assert heading in texts, (heading, texts)
    for h in out["headings"]:
        assert text_at(impl, doc, h["at"]) == h["text"]
        if texts.count(h["text"]) == 1:
            assert text_at(impl, doc, f'h:"{h["text"]}"') == h["text"]
    assert len(out["tables"]) == 1
    t = out["tables"][0]
    grid = fx.BASIC["table"]
    assert (t["rows"], t["cols"]) == (len(grid), len(grid[0]))
    assert call(impl, "read", doc, t["at"])["ok"]
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            assert text_at(impl, doc, f"{t['at']}/r{r}/c{c}") == value
            assert text_at(impl, doc, f"{t['at']}/r{r}/c{c}/p0") == value


def test_outline_lists_the_fill_seats_and_they_read_back(impl, doc, request):
    places = call(impl, "outline", doc)["places"]
    assert len(places) == len(fx.BASIC["places"]), places
    for p in places:
        assert text_at(impl, doc, p["at"]) == text_at(impl, doc, f"place:{p['id']}")
    err = refused(call(impl, "read", doc, "place:no_such_seat"), "bad_address")
    offered = {p["id"] for p in places} | {f"place:{p['id']}" for p in places}   # bare ids or addresses
    assert set(err.get("candidates") or []) & offered, err


def test_every_block_of_a_full_read_reads_back_alone(impl, doc):
    blocks = call(impl, "read", doc)["blocks"]
    assert blocks
    for b in blocks:
        assert text_at(impl, doc, b["at"]) == b["text"], b


@pytest.mark.parametrize("query, at_least, at_most", [
    (fx.UNIQUE_WORD, 1, 1), (fx.REPEATED_WORD, 2, None), (fx.CELL_WORD, 1, 1)])
def test_find_hits_read_back(impl, doc, query, at_least, at_most):
    hits = call(impl, "find", doc, query)["hits"]
    assert len(hits) >= at_least and (at_most is None or len(hits) <= at_most), hits
    for hit in hits:
        assert 0 <= hit["start"] < hit["end"]
        assert _hit_agrees(hit, text_at(impl, doc, hit["at"]), query), hit


def test_find_regex_hits_read_back(impl, doc):
    hits = call(impl, "find", doc, r"\d+월", regex=True)["hits"]
    assert hits
    for hit in hits:
        assert _hit_agrees(hit, text_at(impl, doc, hit["at"]), r"\d+월", regex=True), hit


# --------------------------------------------------------------------------- edit
def test_edit_returns_a_new_rev_and_the_old_base_is_stale(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    src_sha = _sha(doc)
    at = _unique_hit(impl, doc)["at"]
    old = text_at(impl, doc, at)
    new = old.replace(fx.UNIQUE_WORD, "장기 보존 형식")
    out = _out(tmp_path, doc)
    res = need(impl, call(impl, "edit", doc, [{"op": "set", "at": at, "text": new, "expect": old}],
                          base=rev0, out=str(out)), "edit set", request)

    for key in ("rev_before", "rev", "out", "applied", "remap", "changed_pages", "signals"):
        assert key in res, key
    assert res["rev_before"] == rev0
    assert REV.fullmatch(res["rev"]) and res["rev"] != rev0
    assert Path(res["out"]).resolve() == out.resolve()
    assert _sha(out)[:12] == res["rev"]
    assert _sha(doc) == src_sha, "edit wrote over its input"
    assert [a["i"] for a in res["applied"]] == [0]
    assert all({"i", "op", "at"} <= set(a) for a in res["applied"])
    assert all({"from", "to"} <= set(m) for m in res["remap"])
    assert all(isinstance(p, int) and p >= 1 for p in res["changed_pages"])
    assert all({"page", "kind"} <= set(s) for s in res["signals"])
    assert call(impl, "read", out)["rev"] == res["rev"]
    assert text_at(impl, out, _mapped(res["remap"], at)) == new

    out_sha = _sha(out)
    again = _out(tmp_path, doc, "again")
    err = refused(call(impl, "edit", out, [{"op": "set", "at": at, "text": "x"}],
                       base=rev0, out=str(again)), "stale")
    assert err["retryable"] is True
    assert not again.exists() and _sha(out) == out_sha


def test_expect_mismatch_refuses_and_writes_nothing(impl, doc, tmp_path):
    rev0 = call(impl, "open", doc)["rev"]
    src_sha = _sha(doc)
    at = _unique_hit(impl, doc)["at"]
    out = _out(tmp_path, doc)
    err = refused(call(impl, "edit", doc,
                       [{"op": "set", "at": at, "text": "바꾼 글", "expect": "이 문단의 글이 아닙니다"}],
                       base=rev0, out=str(out)), "expect_mismatch")
    assert not out.exists() and _sha(doc) == src_sha

    # a valid op before the mismatching one: still nothing written
    first = call(impl, "outline", doc)["headings"][0]["at"]
    err = refused(call(impl, "edit", doc,
                       [{"op": "set", "at": first, "text": "먼저 바꾼 제목"},
                        {"op": "set", "at": at, "text": "바꾼 글", "expect": "이 문단의 글이 아닙니다"}],
                       base=rev0, out=str(out)), "expect_mismatch")
    assert not out.exists() and _sha(doc) == src_sha


def test_ambiguous_replace_refuses_with_candidates(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    out = _out(tmp_path, doc)
    err = refused(call(impl, "edit", doc, [{"op": "replace", "find": fx.REPEATED_WORD, "with": "검사"}],
                       base=rev0, out=str(out)), "ambiguous_match")
    cands = err.get("candidates")
    assert isinstance(cands, list) and len(cands) >= 2, err
    for c in cands:
        assert fx.REPEATED_WORD in text_at(impl, doc, c)
    assert not out.exists()

    res = need(impl, call(impl, "edit", doc,
                          [{"op": "replace", "find": fx.REPEATED_WORD, "with": "검사", "all": True}],
                          base=rev0, out=str(out)), "edit replace all", request)
    assert call(impl, "find", out, fx.REPEATED_WORD)["hits"] == []
    assert len(call(impl, "find", out, "검사")["hits"]) >= len(cands)
    assert res["rev"] == _sha(out)[:12]


def test_unknown_addresses_answer_bad_address_with_candidates(impl, doc, tmp_path):
    for at in ("p9999", "t99", 'h:"이런 제목은 문서에 없습니다"'):
        err = refused(call(impl, "read", doc, at), "bad_address")
        assert err.get("candidates"), (at, err)
    # candidates for a place need places to offer: checked in the fill-seat test
    refused(call(impl, "read", doc, "place:no_such_seat"), "bad_address")
    rev0 = call(impl, "open", doc)["rev"]
    out = _out(tmp_path, doc)
    err = refused(call(impl, "edit", doc, [{"op": "set", "at": "p9999", "text": "x"}],
                       base=rev0, out=str(out)), "bad_address")
    assert err.get("candidates"), err
    assert not out.exists()


def test_bad_input_returns_an_envelope_never_raises(impl, doc, tmp_path):
    rev0 = call(impl, "open", doc)["rev"]
    out = str(_out(tmp_path, doc))
    missing = doc.with_name("missing" + doc.suffix)
    refused(call(impl, "open", missing), "not_found")
    refused(call(impl, "read", missing), "not_found")
    refused(call(impl, "read", doc, "@@ 주소 아님 @@"), "bad_address")
    refused(call(impl, "edit", doc, "ops가 아님", base=rev0, out=out), "bad_input")
    refused(call(impl, "edit", doc, [{"op": "no_such_op"}], base=rev0, out=out), "bad_input")
    refused(call(impl, "edit", doc, [{"op": "set"}], base=rev0, out=out), "bad_input")
    assert call(impl, "edit", doc, [{"op": "set", "at": "p0", "text": "x"}],
                base="not-a-rev", out=out)["ok"] is False
    refused(call(impl, "find", doc, "(", regex=True), "bad_input")
    assert not Path(out).exists()


def test_out_equal_to_input_is_refused(impl, doc, tmp_path):
    rev0 = call(impl, "open", doc)["rev"]
    src_sha = _sha(doc)
    (doc.parent / "sub").mkdir()
    ops = [{"op": "set", "at": call(impl, "outline", doc)["headings"][0]["at"], "text": "덮어쓰기"}]
    for out in (doc, str(doc), doc.parent / "sub" / ".." / doc.name):
        refused(call(impl, "edit", doc, ops, base=rev0, out=out), "bad_input")
        assert _sha(doc) == src_sha


def test_remap_agrees_with_a_following_read(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    before = call(impl, "read", doc)["blocks"]
    first = call(impl, "outline", doc)["headings"][0]["at"]
    out = _out(tmp_path, doc)
    res = need(impl, call(impl, "edit", doc,
                          [{"op": "insert_after", "at": first, "markdown": "삽입한 문단입니다."}],
                          base=rev0, out=str(out)), "edit insert_after", request)
    assert res["remap"], "an inserted paragraph shifts the paragraphs after it"
    for b in before:
        now = _mapped(res["remap"], b["at"])
        assert now is not None, b
        assert text_at(impl, out, now) == b["text"], (b, now)
    assert call(impl, "find", out, "삽입한 문단입니다.")["hits"]


def test_remap_after_delete_agrees_with_a_following_read(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    before = call(impl, "read", doc)["blocks"]
    gone = _unique_hit(impl, doc)["at"]
    out = _out(tmp_path, doc)
    res = need(impl, call(impl, "edit", doc, [{"op": "delete", "at": gone}], base=rev0, out=str(out)),
               "edit delete", request)
    for b in before:
        if b["at"] == gone:
            continue
        now = _mapped(res["remap"], b["at"])
        assert now is not None, b
        assert text_at(impl, out, now) == b["text"], (b, now)
    assert call(impl, "find", out, fx.UNIQUE_WORD)["hits"] == []


def test_fill_every_place(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    places = call(impl, "outline", doc)["places"]
    assert len(places) == len(fx.BASIC["places"]), f"outline listed {places}"
    ops = [{"op": "fill", "place": p["id"], "text": f"값 {k}"} for k, p in enumerate(places)]
    out = _out(tmp_path, doc)
    res = need(impl, call(impl, "edit", doc, ops, base=rev0, out=str(out)), "edit fill", request)
    for k, p in enumerate(places):
        assert text_at(impl, out, f"place:{p['id']}") == f"값 {k}"
        assert text_at(impl, out, _mapped(res["remap"], p["at"])) == f"값 {k}"


def test_table_set_cells(impl, doc, tmp_path, request):
    rev0 = call(impl, "open", doc)["rev"]
    t = call(impl, "outline", doc)["tables"][0]["at"]
    out = _out(tmp_path, doc)
    need(impl, call(impl, "edit", doc, [{"op": "table.set_cells", "at": f"{t}/r1/c1", "grid": [["9,999"]]}],
                    base=rev0, out=str(out)), "edit table.set_cells", request)
    assert text_at(impl, out, f"{t}/r1/c1") == "9,999"
    assert text_at(impl, out, f"{t}/r2/c1") == fx.BASIC["table"][2][1]


# --------------------------------------------------------------------------- render / pages
def test_render_png(impl, doc, tmp_path, request):
    res = need(impl, call(impl, "render", doc, [1], out_dir=str(tmp_path / "png")), "render png", request)
    assert res["rev"] == _sha(doc)[:12]
    assert [p["n"] for p in res["pages"]] == [1]
    page = res["pages"][0]
    assert Path(page["file"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert page["width_pt"] > 0 and page["height_pt"] > 0 and page["px_w"] > 0 and page["px_h"] > 0


def test_render_pdf(impl, doc, tmp_path, request):
    res = need(impl, call(impl, "render", doc, [1], fmt="pdf", out_dir=str(tmp_path / "pdf")),
               "render pdf", request)
    files = {p["file"] for p in res["pages"]}
    assert len(files) == 1, "fmt=pdf writes one PDF"
    assert Path(files.pop()).read_bytes()[:5] == b"%PDF-"


def test_render_of_a_missing_page_is_refused_not_raised(impl, doc, tmp_path, request):
    res = unless_unavailable(impl, call(impl, "render", doc, [9999], out_dir=str(tmp_path / "png")),
                             "render of page 9999", request)
    assert res["ok"] is False, res


def test_pages(impl, doc, request):
    res = need(impl, call(impl, "pages", doc), "pages", request)
    assert res["rev"] == _sha(doc)[:12]
    assert res["count"] >= 1
    assert [p["n"] for p in res["pages"]] == list(range(1, res["count"] + 1))
    for p in res["pages"]:
        assert "starts_with" in p and isinstance(p["signals"], list)


# --------------------------------------------------------------------------- fixtures
def test_committed_hwpx_fixtures_match_their_specs():
    """The real rt_doc's fixtures are the fake's HWPX export of the same specs."""
    for family, spec in fx.SPECS.items():
        committed = fx.committed_fixture(family)
        assert committed.is_file(), f"run: python tests/_rt_doc_contract_fixtures.py ({committed})"
        assert fx.members(committed) == fx.members(fx.hwpx_bytes(spec)), (
            f"{committed.name} is stale; run: python tests/_rt_doc_contract_fixtures.py")
