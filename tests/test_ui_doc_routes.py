"""The editor page service through the guarded loopback bridge."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import threading
from urllib.parse import urlencode

import pytest

from _runtime_client import runtime_scripts_on_path

runtime_scripts_on_path()
import rt_apply  # noqa: E402
import rt_render  # noqa: E402
import rt_ui  # noqa: E402
import rt_ui_doc  # noqa: E402
from rt_jsonl import canonical_bytes  # noqa: E402
from rt_session import Session  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "tests" / "fixtures" / "rt_doc_contract" / "basic.hwpx"
GONGMUN = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def serving(tmp_path):
    server = rt_ui.create_bridge_server(
        root=tmp_path / "runtime", engine_root=REPO, port=0,
        prefs_path=tmp_path / "prefs.json",
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown_bridge()
        thread.join(timeout=5)


@pytest.fixture
def document(serving, tmp_path):
    original = tmp_path / "document.hwpx"
    shutil.copyfile(DOC, original)
    return Session.open_path(serving.bridge.current_root(), str(original)), original


def request(server, operation, params, *, headers=None, token=True, body=None):
    headers = {**({"X-Rigorloom-Token": server.token} if token else {}), **(headers or {})}
    path = f"/api/doc/{operation}"
    method = "POST" if operation in {"hit", "caret"} else "GET"
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body = json.dumps(params) if body is None else body
    else:
        path += "?" + urlencode(params, doseq=True)
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=20)
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        if response.getheader("Content-Type") != "image/png":
            data = json.loads(data)
        return response.status, dict(response.getheaders()), data
    finally:
        conn.close()


def binding(session):
    return {"sessionId": session.id, "rev": session.meta["sourceSha256"]}


def refuse(result, status, code):
    assert result[0] == status
    assert result[2]["error"]["code"] == code


def test_loopback_and_missing_token(serving, document):
    assert serving.server_address[0] == "127.0.0.1"
    refuse(request(serving, "pages", binding(document[0]), token=False), 403, "unauthorized")


def test_external_origin_is_refused(serving, document):
    refuse(request(serving, "pages", binding(document[0]),
                   headers={"Origin": "https://example.invalid"}), 403, "invalid_origin")


def test_external_host_is_refused(serving, document):
    refuse(request(serving, "pages", binding(document[0]),
                   headers={"Host": "example.invalid"}), 403, "invalid_host")


def test_wrong_revision_is_refused(serving, document):
    params = {**binding(document[0]), "rev": "0" * 64}
    refuse(request(serving, "pages", params), 409, "stale_rev")


@pytest.mark.parametrize("operation", ["render", "hit"])
def test_oversize_request_is_refused(serving, document, operation):
    params = {**binding(document[0]), "page": 1, "scale": 1}
    refuse(request(serving, operation, params,
                   body=b" " * (rt_ui.SMALL_JSON_BODY_BYTES + 1)), 413, "body_too_large")


def test_links_and_caller_supplied_paths_are_refused(serving, document):
    session, original = document
    refuse(request(serving, "pages", {**binding(session), "path": str(original)}), 400, "invalid_params")
    session.source.unlink()
    session.source.symlink_to(original)
    refuse(request(serving, "pages", binding(session)), 404, "not_found")


def test_overscale_is_refused(serving, document):
    params = {**binding(document[0]), "page": 1, "scale": rt_ui_doc.MAX_SCALE + 0.1}
    refuse(request(serving, "render", params), 400, "scale_limit")


@pytest.mark.parametrize("page_args", [{"page": [1, 2]}, {"page": "1,2"}, {"pages": "all"}])
def test_multiple_pages_are_refused(serving, document, page_args):
    params = {**binding(document[0]), **page_args, "scale": 1}
    refuse(request(serving, "render", params), 400, "page_limit")


@pytest.fixture
def fake_engine(monkeypatch):
    engine = rt_ui_doc.rt_doc
    seen = []

    def engine_result(path, **fields):
        seen.append(path)
        return {"ok": True, "rev": engine.rev_of(path), **fields}

    def render(path, page, *, scale, out_dir):
        png = Path(out_dir) / "page.png"
        png.write_bytes(PNG_SIGNATURE)
        return engine_result(path, pages=[{"n": page, "file": str(png),
                                           "width_pt": 600, "height_pt": 800}])

    monkeypatch.setattr(engine, "engine_status", lambda: {"available": True})
    monkeypatch.setattr(engine, "pages", lambda path: engine_result(path, count=2, pages=[], approx=["fallback"]))
    monkeypatch.setattr(engine, "render", render)
    monkeypatch.setattr(engine, "geometry", lambda path, page: engine_result(
        path, page=page, width_pt=600, height_pt=800, boxes=[]))
    monkeypatch.setattr(engine, "hit_test", lambda path, page, x, y: engine_result(path, at="p0", offset=1))
    monkeypatch.setattr(engine, "caret_rect", lambda path, at, offset: engine_result(path, page=1, rect=[0, 0, 1, 12]))
    return seen


def test_engine_responses_bind_to_the_private_copy(serving, document, fake_engine):
    session, original = document
    original.write_bytes(b"the user has changed the original")
    params = binding(session)
    seqs = []
    for operation, extra in [
        ("pages", {}), ("geometry", {"page": 1}), ("hit", {"page": 1, "x": 20, "y": 30}),
        ("caret", {"at": "p0", "offset": 1}),
    ]:
        status, _, payload = request(serving, operation, {**params, **extra})
        assert status == 200 and payload["rev"] == params["rev"]
        seqs.append(payload["seq"])
    status, headers, png = request(serving, "render", {**params, "page": 1, "scale": 1.5})
    assert status == 200 and png.startswith(PNG_SIGNATURE)
    assert headers["X-Rigorloom-Rev"] == params["rev"]
    assert headers["X-Rigorloom-Page"] == "1"
    assert headers["X-Rigorloom-Approx"] == "1"
    assert headers["Cache-Control"] == "no-store"
    seqs.append(int(headers["X-Rigorloom-Seq"]))
    assert seqs == sorted(set(seqs))
    assert fake_engine == [session.source] * 6
    assert original.read_bytes() == b"the user has changed the original"


def test_published_candidate_is_the_only_head(serving, document, fake_engine):
    session, _ = document
    run_dir = session.candidates_dir / "published"
    run_dir.mkdir()
    candidate = run_dir / "candidate.hwpx"
    shutil.copyfile(GONGMUN, candidate)
    rev = hashlib.sha256(candidate.read_bytes()).hexdigest()
    receipt = {"candidate": {"path": candidate.name, "sha256": rev, "bytes": candidate.stat().st_size}}
    receipt["bodySha256"] = hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    (run_dir / rt_apply.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")
    refuse(request(serving, "pages", binding(session)), 409, "stale_rev")
    status, _, body = request(serving, "pages", {**binding(session), "rev": rev})
    assert status == 200 and body["rev"] == rev
    assert fake_engine == [candidate]


def test_coalesces_to_the_newest_render(serving, document, fake_engine, monkeypatch):
    engine = rt_ui_doc.rt_doc
    render = engine.render
    started = threading.Event()
    release = threading.Event()
    scales = []
    gateway = rt_ui_doc.PageGateway()
    session = document[0]
    root = serving.bridge.current_root()
    tools = rt_ui_doc.EngineTools(REPO)
    key = (root, session.id)

    def slow(path, page, *, scale, out_dir):
        scales.append(scale)
        if scale == 1:
            started.set()
            assert release.wait(10)
        return render(path, page, scale=scale, out_dir=out_dir)

    monkeypatch.setattr(engine, "render", slow)
    params = {**binding(session), "page": 1}
    with ThreadPoolExecutor(max_workers=3) as pool:
        def submit(scale):
            return pool.submit(gateway.read, root, tools, "render", {**params, "scale": scale})

        try:
            first = submit(1)
            assert started.wait(5)
            second = submit(2)
            with gateway._ready:
                assert gateway._ready.wait_for(lambda: gateway._renders[key].latest == 2, timeout=5)
            third = submit(3)
            with gateway._ready:
                assert gateway._ready.wait_for(lambda: gateway._renders[key].latest == 3, timeout=5)
            with pytest.raises(rt_ui_doc.PageError, match="a newer render"):
                second.result(timeout=5)
        finally:
            release.set()
        with pytest.raises(rt_ui_doc.PageError, match="a newer render"):
            first.result(timeout=5)
        payload, png = third.result(timeout=5)
    assert payload["seq"] == 3 and png.startswith(PNG_SIGNATURE)
    assert scales == [1, 3]


@pytest.mark.parametrize("grade", ["pdf", "hancom"])
def test_prepared_pdf_tiers_use_the_shared_render_chain(serving, document, grade, monkeypatch):
    monkeypatch.setattr(rt_ui_doc.rt_doc, "engine_status", lambda: {"available": False})
    session, _ = document
    pdf = rt_render.rasterizer_module()
    if pdf is None:
        pytest.skip("PyMuPDF is unavailable")
    target = session.dir / "derived" / "prepared.pdf"
    target.parent.mkdir()
    with pdf.open() as synthetic:
        synthetic.new_page()
        synthetic.save(target)
    pdf_bytes = target.read_bytes()
    session.meta["derivedPdf"] = {
        "sourceSha256": session.meta["sourceSha256"],
        "path": target.relative_to(session.dir).as_posix(),
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(), "bytes": len(pdf_bytes),
        "producedBy": rt_render.HANCOM_PRODUCER if grade == "hancom" else "fixture",
    }
    session.meta_path.write_text(json.dumps(session.meta), encoding="utf-8")
    status, headers, png = request(serving, "render", {**binding(session), "page": 1, "scale": 1})
    assert status == 200 and png.startswith(PNG_SIGNATURE)
    assert headers["X-Rigorloom-Source"] == grade
    assert headers["X-Rigorloom-Page-Count"] == "1"


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
def test_installed_engine_renders_a_png(serving):
    session = Session.open_path(serving.bridge.current_root(), str(GONGMUN))
    params = binding(session)
    status, _, info = request(serving, "pages", params)
    assert status == 200 and info["source"] == "engine" and info["count"] > 0
    status, headers, png = request(serving, "render", {**params, "page": 1, "scale": 1})
    assert status == 200 and headers["X-Rigorloom-Source"] == "engine"
    assert png.startswith(PNG_SIGNATURE)


def test_own_render_then_projection(serving, monkeypatch):
    root = serving.bridge.current_root()
    session = Session.open_path(root, str(GONGMUN))
    params = {**binding(session), "page": 1, "scale": 1}
    monkeypatch.setattr(rt_ui_doc.rt_doc, "engine_status", lambda: {"available": False})
    status, headers, png = request(serving, "render", params)
    assert status == 200 and png.startswith(PNG_SIGNATURE)
    assert headers["X-Rigorloom-Source"] == "own-uncertified"

    monkeypatch.setattr(rt_render, "own_render_page", lambda *args, **kwargs: (None, None))
    status, _, payload = request(serving, "render", params)
    assert status == 200 and payload["source"] == "projection"
    assert payload["rev"] == params["rev"]


def test_a_prepared_pdf_outside_the_session_is_refused(serving, document, monkeypatch):
    session, original = document
    monkeypatch.setattr(rt_ui_doc.rt_doc, "engine_status", lambda: {"available": False})
    session.meta["derivedPdf"] = {"sourceSha256": session.meta["sourceSha256"], "path": str(original)}
    session.meta_path.write_text(json.dumps(session.meta), encoding="utf-8")
    refuse(request(serving, "render", {**binding(session), "page": 1, "scale": 1}), 404, "not_found")
