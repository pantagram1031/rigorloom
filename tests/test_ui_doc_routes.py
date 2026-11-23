"""The editor page service through the guarded loopback bridge."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import http.client
from io import BytesIO
import json
import os
from pathlib import Path
import random
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
from rt_core import RuntimeCore  # noqa: E402
from rt_jsonl import FrameWriter, canonical_bytes  # noqa: E402
from rt_session import Session  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "tests" / "fixtures" / "rt_doc_contract" / "basic.hwpx"
GONGMUN = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
ADMRUL = REPO / "tests" / "corpus" / "forms" / "converted" / "admrul-gajokdolbom-hyuga-sinchengseo.hwpx"
MOEL_2025 = REPO / "tests" / "corpus" / "forms" / "converted" / "moel-pyojun-geunrogyeyakseo-2025.hwpx"
KSTARTUP = REPO / "tests" / "corpus" / "forms" / "converted" / "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx"
RENDER_CHECK = REPO / "tests" / "corpus" / "render-check" / "render-check-01.hwpx"
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
    method = "POST" if operation == "preview" else "GET"
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


@pytest.mark.parametrize("operation", ["render", "preview"])
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
def fake_engine(monkeypatch, tmp_path):
    engine = rt_ui_doc.rt_doc
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    monkeypatch.setattr(engine, "_SCRATCH", str(scratch_dir))
    seen = []
    counter = 0

    def engine_result(path, **fields):
        seen.append(path)
        return {"ok": True, "rev": engine.rev_of(path), **fields}

    def render(path, page, *, scale, out_dir):
        png = Path(out_dir) / "page.png"
        png.write_bytes(PNG_SIGNATURE)
        return engine_result(path, pages=[{"n": page, "file": str(png),
                                           "width_pt": 600, "height_pt": 800}])

    def edit(path, ops, *, base, preview):
        nonlocal counter
        assert preview is True
        assert base == engine.rev_of(path)
        counter += 1
        output = engine._scratch_sub("preview") / f"preview-{counter}.hwpx"
        output.write_bytes(path.read_bytes() + json.dumps(ops).encode())
        seen.append(path)
        return {"ok": True, "rev_before": base, "rev": engine.rev_of(output), "out": str(output), "remap": [],
                "changed_pages": [2], "changed": [{"i": 0, "page": 2, "rect": None}]}

    monkeypatch.setattr(engine, "engine_status", lambda: {"available": True})
    monkeypatch.setattr(engine, "pages", lambda path: engine_result(path, count=2, pages=[], approx=["fallback"]))
    monkeypatch.setattr(engine, "render", render)
    monkeypatch.setattr(engine, "edit", edit)
    monkeypatch.setattr(engine, "geometry", lambda path, page: engine_result(
        path, page=page, width_pt=600, height_pt=800,
        boxes=[{"kind": "cell", "at": "t0/r0/c0", "rect": [20, 30, 40, 50]}]))
    return seen


def test_engine_responses_bind_to_the_private_copy(serving, document, fake_engine):
    session, original = document
    original.write_bytes(b"the user has changed the original")
    params = binding(session)
    seqs = []
    for operation, extra in [
        ("pages", {}), ("geometry", {"page": 1}),
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
    assert fake_engine == [session.source] * 4
    assert original.read_bytes() == b"the user has changed the original"


def test_preview_guards_and_only_renders_a_changed_page(serving, document, fake_engine):
    session, original = document
    base = binding(session)
    before = session.source.read_bytes()
    ops = [{"at": "t0/r0/c0", "text": "수정"}]
    params = {**base, "ops": ops}
    refuse(request(serving, "preview", params, token=False), 403, "unauthorized")
    refuse(request(serving, "preview", params,
                   headers={"Origin": "https://example.invalid"}), 403, "invalid_origin")
    refuse(request(serving, "preview", {**params, "rev": "0" * 64}), 409, "stale_rev")
    refuse(request(serving, "preview", {**params, "ops": [{**ops[0], "out": str(original)}]}),
           400, "invalid_params")
    assert fake_engine == []

    status, _, preview = request(serving, "preview", params)
    assert status == 200
    assert preview["rev"] == base["rev"]
    assert preview["previewRev"] != base["rev"][:12]
    assert preview["changedPages"] == [2]
    assert fake_engine[0] == session.source and fake_engine[1] != session.source
    preview_binding = {**base, "previewId": preview["previewId"]}
    refuse(request(serving, "render", {**preview_binding, "page": 1, "scale": 1}), 400, "page_unchanged")
    assert len(fake_engine) == 2
    other = Session.open_path(serving.bridge.current_root(), str(original))
    refuse(request(serving, "render", {**preview_binding, "sessionId": other.id, "page": 2, "scale": 1}),
           404, "preview_expired")

    status, _, geometry = request(serving, "geometry", {**preview_binding, "page": 2})
    assert status == 200 and geometry["previewRev"] == preview["previewRev"]
    assert geometry["changed"] == [{"i": 0, "page": 2, "rect": [20, 30, 40, 50]}]
    status, headers, png = request(serving, "render", {**preview_binding, "page": 2, "scale": 1})
    assert status == 200 and png.startswith(PNG_SIGNATURE)
    assert headers["X-Rigorloom-Preview-Id"] == preview["previewId"]
    assert headers["X-Rigorloom-Preview-Rev"] == preview["previewRev"]
    assert int(headers["X-Rigorloom-Seq"]) > geometry["seq"] > preview["seq"]
    assert session.source.read_bytes() == original.read_bytes() == before
    assert rt_apply.list_candidates(session) == []


def test_preview_refuses_a_linked_source(serving, document, fake_engine):
    session, original = document
    session.source.unlink()
    session.source.symlink_to(original)
    refuse(request(serving, "preview", {**binding(session), "ops": [{"at": "t0/r0/c0", "text": "x"}]}),
           404, "not_found")
    assert fake_engine == []


def test_preview_refuses_mismatched_queued_paragraph_run(serving, document, fake_engine):
    session, _ = document
    base = binding(session)
    addresses = rt_ui_doc.rt_doc.queue_addresses(session.source)["addresses"]
    queue_at = addresses["p0"]
    refuse(request(serving, "preview", {**base, "ops": [
        {"at": queue_at, "run": 0, "before": "문서와 다른 런 텍스트", "text": "수정"},
    ]}), 400, "bad_address")
    assert fake_engine == []


def test_native_page_image_can_exceed_inline_limit(serving, document, fake_engine, monkeypatch, tmp_path):
    from PIL import Image

    buffer = BytesIO()
    Image.frombytes("L", (900, 900), random.Random(42).randbytes(900 * 900)).save(buffer, "PNG")
    expected = buffer.getvalue()
    limit = rt_ui_doc.MAX_INLINE_IMAGE_BYTES
    assert len(expected) > limit
    gateway = rt_ui_doc.PageGateway()
    render = gateway._render

    def large_render(*args, **kwargs):
        info, _ = render(*args, **kwargs)
        return info, expected

    monkeypatch.setattr(gateway, "_render", large_render)
    monkeypatch.setattr(rt_ui_doc, "_native_gateway", gateway)
    root = serving.bridge.current_root()
    tools = rt_ui_doc.EngineTools(REPO)
    session, _ = document
    base = binding(session)
    response = rt_ui_doc.native_page_view(root, tools, {**base, "operation": "render", "page": 1, "scale": 3})
    assert "png" not in response and response["imageBytes"] == len(expected)

    payload = {**base, "operation": "image", "imageId": response["imageId"]}
    chunks = []
    for offset in range(0, response["imageBytes"], limit):
        chunk = rt_ui_doc.native_page_view(root, tools, {**payload, "offset": offset})
        frame = BytesIO()
        FrameWriter(frame, threading.Lock()).respond("test", chunk)
        assert json.loads(frame.getvalue())["kind"] == "response"
        chunks.append(base64.b64decode(chunk["png"]))
    assert b"".join(chunks) == expected

    outside = tmp_path / "outside.png"
    outside.write_bytes(expected)
    image_file, = (session.renders_dir / "page-view").glob("*.png")
    image_file.unlink()
    image_file.symlink_to(outside)
    with pytest.raises(rt_ui_doc.RpcError) as error:
        rt_ui_doc.native_page_view(root, tools, {**payload, "offset": 0})
    assert error.value.code == "not_found"


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


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
def test_installed_engine_previews_the_queued_paragraph_run(serving):
    session = Session.open_path(serving.bridge.current_root(), str(RENDER_CHECK))
    base = binding(session)
    status, _, geometry = request(serving, "geometry", {**base, "page": 1})
    assert status == 200
    line = next(box for box in geometry["boxes"] if box["at"] == "p1#L0")
    assert line["queueAddress"] == "p3#L0"
    text = "검토 제목"
    status, _, preview = request(serving, "preview", {**base, "ops": [
        {"at": "p3", "run": 0, "before": line["text"], "text": text},
    ]})
    assert status == 200 and 1 in preview["changedPages"]
    params = {**base, "previewId": preview["previewId"], "page": 1}
    status, _, geometry = request(serving, "geometry", params)
    assert status == 200 and geometry["changed"]
    assert next(box for box in geometry["boxes"] if box["at"] == "p1#L0")["text"] == text
    status, headers, png = request(serving, "render", {**params, "scale": 1})
    assert status == 200 and headers["X-Rigorloom-Preview-Rev"] == preview["previewRev"]
    assert png.startswith(PNG_SIGNATURE)


def test_changed_region_twin_matches_preedit_and_narrows_queued_run_edit():
    import sys

    engine_scripts = REPO / "engine" / "scripts"
    if str(engine_scripts) not in sys.path:
        sys.path.insert(0, str(engine_scripts))
    import preedit

    pairs = [
        ("", ""),
        ("", "새값"),
        ("기존", ""),
        ("동일", "동일"),
        ("aaa", "aa"),
        ("aa", "aaa"),
        ("ababa", "aba"),
        ("aXba", "aba"),
        ("본인은 가족 돌봄을 위하여 (□휴직, □휴가)을 하고자 하오니",
         "본인은 가족 돌봄을 위하여 (□휴직, □휴업)을 하고자 하오니"),
        ("※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 기재",
         "※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 작성"),
        ("앞 왼쪽오른쪽 뒤", "앞 좌측우측 뒤"),
        ("완전히 다른 옛날 문구", "새로 쓴 문구"),
    ]
    for old, new in pairs:
        assert rt_ui_doc.changed_region(old, new) == preedit.changed_region(old, new)

    core_fw = "본인은 가족 돌봄을 위하여 (□\u3000휴직, □\u3000휴가)을 하고자 하오니"
    c_start, c_end, repl = rt_ui_doc._queued_run_edit(
        core_fw, "본인은 가족 돌봄을 위하여 (□휴직, □휴업)을 하고자 하오니",
    )
    assert (c_start, c_end, repl) == (25, 26, "업")
    assert core_fw[:c_start] + repl + core_fw[c_end:] == (
        "본인은 가족 돌봄을 위하여 (□\u3000휴직, □\u3000휴업)을 하고자 하오니"
    )

    core_lb = "※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 기재\n"
    c_start, c_end, repl = rt_ui_doc._queued_run_edit(
        core_lb, "※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 작성",
    )
    assert repl == "작성"
    assert core_lb[:c_start] + repl + core_lb[c_end:] == (
        "※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 작성\n"
    )

    core_boundary = "\u3000삭제대상\n"
    for target, expected in [("새값", "\u3000새값\n"), ("", "\u3000\n")]:
        b_start, b_end, b_repl = rt_ui_doc._queued_run_edit(core_boundary, target)
        assert core_boundary[:b_start] + b_repl + core_boundary[b_end:] == expected


@pytest.mark.parametrize(
    "core_run, inner, value",
    [
        ("가나다", "가나다", "가\u3000나다"),
        ("가\u3000나다", "가<hp:fwSpace/>나다", "가나\t다"),
        ("가\u3000나다", "가<hp:fwSpace/>나다", "가나\n다라"),
    ],
    ids=["typed-fwspace", "typed-tab", "typed-linebreak"],
)
def test_queued_run_edit_keeps_inline_characters_typed_into_the_value(core_run, inner, value):
    import sys
    from html import unescape

    engine_scripts = REPO / "engine" / "scripts"
    if str(engine_scripts) not in sys.path:
        sys.path.insert(0, str(engine_scripts))
    import preedit

    p_xml = f'<hp:p><hp:run charPrIDRef="0"><hp:t>{inner}</hp:t></hp:run></hp:p>'
    run = preedit.paragraph_text_runs(p_xml)[0]
    written, _dropped = preedit._replace_t_spans_preserving_inline(
        p_xml, sorted(run["t_spans"]), value)
    written_inner = written.split("<hp:t>", 1)[1].rsplit("</hp:t>", 1)[0]
    applied = unescape(written_inner.replace("<hp:fwSpace/>", "\u3000"))

    c_start, c_end, repl = rt_ui_doc._queued_run_edit(core_run, value)
    assert core_run[:c_start] + repl + core_run[c_end:] == applied


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
@pytest.mark.parametrize(
    "form_path, page, core_at, queue_at, run_idx, needle, replacement_word, inline_char",
    [
        (ADMRUL, 1, "p9", "p13", 1, "휴가", "휴업", "\u3000"),
        (MOEL_2025, 1, "p20", "p21", 1, "기재", "작성", "\n"),
        (KSTARTUP, 22, "p141", "p753", 0, "2026.", "2027.", "\t"),
    ],
    ids=["fwSpace", "lineBreak", "tab"],
)
def test_installed_engine_previews_queued_run_with_inline_elements(
    serving, form_path, page, core_at, queue_at, run_idx, needle, replacement_word, inline_char,
):
    root = serving.bridge.current_root()
    session = Session.open_path(root, str(form_path))
    base = binding(session)
    status, _, geometry = request(serving, "geometry", {**base, "page": page})
    assert status == 200
    para_box = next(box for box in geometry["boxes"] if box["at"] == core_at)
    assert para_box["queueAddress"] == queue_at

    core = RuntimeCore(root, engine_root=REPO)
    at_para = int(queue_at[1:])
    region = core.document_read_region(session.id, [{"atPara": at_para}])["regions"][0]
    run = region["runs"][run_idx]
    at = f"p{region['at_para']}"
    assert at == queue_at
    assert needle in run["text"]
    replacement = run["text"].replace(needle, replacement_word, 1)

    refuse(request(serving, "preview", {**base, "ops": [
        {"at": at, "run": run["index"], "before": run["text"] + " 불일치", "text": replacement},
    ]}), 400, "bad_address")

    status, _, preview = request(serving, "preview", {**base, "ops": [
        {"at": at, "run": run["index"], "before": run["text"], "text": replacement},
    ]})
    assert status == 200, preview
    assert page in preview["changedPages"]
    params = {**base, "previewId": preview["previewId"], "page": page}
    status, _, geometry = request(serving, "geometry", params)
    assert status == 200 and geometry["changed"]

    # Apply the same queued set_run op and verify preview doc-core text equals saved doc-core text.
    plan = core.plan_propose(
        session.id,
        "preedit",
        [{"kind": "set_run", "atPara": at_para, "run": run_idx, "text": replacement}],
        "test-operator",
    )["plan"]
    validation = core.plan_validate(plan["planId"])["validation"]
    assert validation["ok"] is True, validation["hard"]
    approval = core.approval_request(plan["planId"], "test-operator")["approval"]
    core.approval_resolve(
        approval["approvalId"],
        plan["planId"],
        plan["planHash"],
        "approved",
        "test-operator",
    )
    applied = core.plan_apply(plan["planId"], approval["approvalId"])["candidate"]
    saved_path = (
        root / "sessions" / session.id / "candidates"
        / applied["runId"] / applied["candidate"]["path"]
    )

    c_start, c_end, repl_slice = rt_ui_doc._queued_run_edit(
        rt_ui_doc.rt_doc.read(session.source, core_at, with_runs=True)["blocks"][0]["runs"][run_idx]["text"],
        replacement,
    )
    base_runs = [
        r["text"]
        for r in rt_ui_doc.rt_doc.read(session.source, core_at, with_runs=True)["blocks"][0]["runs"]
    ]
    run_offset = sum(map(len, base_runs[:run_idx]))
    preview_edit = rt_ui_doc.rt_doc.edit(
        session.source,
        [{"op": "set", "at": f"{core_at}:{run_offset + c_start}-{run_offset + c_end}", "text": repl_slice}],
        base=base["rev"][:12],
        preview=True,
    )
    assert preview_edit["ok"], preview_edit
    preview_block = rt_ui_doc.rt_doc.read(preview_edit["out"], core_at, with_runs=True)["blocks"][0]
    saved_block = rt_ui_doc.rt_doc.read(saved_path, core_at, with_runs=True)["blocks"][0]

    assert inline_char in preview_block["text"]
    assert preview_block["text"] == saved_block["text"]
    assert [r["text"] for r in preview_block["runs"]] == [r["text"] for r in saved_block["runs"]]

    saved_geometry = rt_ui_doc.rt_doc.geometry(saved_path, page)
    assert saved_geometry["ok"], saved_geometry
    assert (
        next(box for box in geometry["boxes"] if box["at"] == core_at)["text"]
        == next(box for box in saved_geometry["boxes"] if box["at"] == core_at)["text"]
    )


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


def test_preview_addresses_lead_paragraphs_of_object_holding_cell(serving, fake_engine, monkeypatch):
    import sys

    engine_scripts = REPO / "engine" / "scripts"
    if str(engine_scripts) not in sys.path:
        sys.path.insert(0, str(engine_scripts))
    import preedit

    recorded_ops = []
    orig_edit = rt_ui_doc.rt_doc.edit

    def capture_edit(path, ops, *, base, preview):
        recorded_ops.append(list(ops))
        return orig_edit(path, ops, base=base, preview=preview)

    monkeypatch.setattr(rt_ui_doc.rt_doc, "edit", capture_edit)

    session = Session.open_path(serving.bridge.current_root(), str(GONGMUN))
    base = binding(session)
    has_obj, slots, blank_indices = preedit.cell_lead_paragraphs(session.source, 0, 2, 0)
    assert has_obj is True
    assert slots == list(range(20))
    assert blank_indices == [19]

    recorded_ops.clear()
    status, _, preview = request(serving, "preview", {
        **base,
        "ops": [{"at": "t0/r2/c0", "text": "붙임 자료를 보내 드립니다."}],
    })
    assert status == 200, preview
    assert recorded_ops == [[
        {"op": "set", "at": "t0/r2/c0/p0", "text": "붙임 자료를 보내 드립니다."},
        {"op": "set", "at": "t0/r2/c0/p19", "text": ""},
    ]]

    recorded_ops.clear()
    status, _, preview = request(serving, "preview", {
        **base,
        "ops": [{"at": "t0/r2/c0", "text": "첫째 줄\n둘째 줄"}],
    })
    assert status == 200, preview
    assert recorded_ops == [[
        {"op": "set", "at": "t0/r2/c0/p0", "text": "첫째 줄"},
        {"op": "set", "at": "t0/r2/c0/p1", "text": "둘째 줄"},
        {"op": "set", "at": "t0/r2/c0/p19", "text": ""},
    ]]

    # Too many lines (more than the 20 reserved slots) is refused by preview.
    recorded_ops.clear()
    too_many_lines = "\n".join(f"줄 {i}" for i in range(len(slots) + 1))
    refuse(
        request(serving, "preview", {
            **base,
            "ops": [{"at": "t0/r2/c0", "text": too_many_lines}],
        }),
        400,
        "bad_input",
    )
    assert recorded_ops == []

    # Leaf cell without objects keeps addressing the cell itself.
    recorded_ops.clear()
    status, _, preview = request(serving, "preview", {
        **base,
        "ops": [{"at": "t0/r5/c1", "text": "기획조정실"}],
    })
    assert status == 200, preview
    assert recorded_ops == [[{"op": "set", "at": "t0/r5/c1", "text": "기획조정실"}]]


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
def test_installed_engine_previews_object_holding_body_cell_at_lead_paragraph(serving):
    root = serving.bridge.current_root()
    session = Session.open_path(root, str(GONGMUN))
    base = binding(session)
    text = "붙임 자료를 보내 드립니다."

    status, _, preview = request(serving, "preview", {
        **base,
        "ops": [{"at": "t0/r2/c0", "text": text}],
    })
    assert status == 200, preview
    assert 1 in preview["changedPages"]

    params = {**base, "previewId": preview["previewId"], "page": 1}
    status, _, geometry = request(serving, "geometry", params)
    assert status == 200 and geometry["changed"]
    assert next(box for box in geometry["boxes"] if box["at"] == "t0/r2/c0/p0")["text"] == text
    assert next(box for box in geometry["boxes"] if box["at"] == "t0/r2/c0/p19")["text"] == ""
    assert any(box["at"] == "t0/r2/c0/t0" and box.get("text") == "직인" for box in geometry["boxes"])
    assert any(box["at"] == "t0/r2/c0/t1" and box.get("text") == "발신명의" for box in geometry["boxes"])

    core = RuntimeCore(root, engine_root=REPO)
    plan = core.plan_propose(
        session.id,
        "preedit",
        [{"kind": "fill_cell", "table": 0, "row": 2, "col": 0, "text": text, "charPr": "23"}],
        "test-operator",
    )["plan"]
    assert "at" not in plan["ops"][0]["params"]
    validation = core.plan_validate(plan["planId"])["validation"]
    assert validation["ok"] is True, validation["hard"]
    approval = core.approval_request(plan["planId"], "test-operator")["approval"]
    core.approval_resolve(
        approval["approvalId"],
        plan["planId"],
        plan["planHash"],
        "approved",
        "test-operator",
    )
    applied = core.plan_apply(plan["planId"], approval["approvalId"])["candidate"]
    saved_path = (
        root / "sessions" / session.id / "candidates"
        / applied["runId"] / applied["candidate"]["path"]
    )
    saved_block = rt_ui_doc.rt_doc.read(saved_path, "t0/r2/c0/p0")["blocks"][0]
    assert saved_block["text"] == text
    blanked_block = rt_ui_doc.rt_doc.read(saved_path, "t0/r2/c0/p19")["blocks"][0]
    assert blanked_block["text"] == ""


def test_preview_eviction_ttl_and_inflight_render_unlink_scratch_files(
    serving, document, fake_engine, monkeypatch, tmp_path,
):
    engine = rt_ui_doc.rt_doc
    base_render = engine.render
    gateway = rt_ui_doc.PageGateway()
    root = serving.bridge.current_root()
    tools = rt_ui_doc.EngineTools(REPO)
    _, original = document

    clock = [1000.0]
    monkeypatch.setattr(rt_ui_doc.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(rt_ui_doc, "PREVIEW_LIMIT", 2)

    def make_preview(session, text):
        payload, _ = gateway.read(root, tools, "preview", {
            **binding(session),
            "ops": [{"at": "t0/r0/c0", "text": text}],
        })
        preview_id = payload["previewId"]
        return preview_id, gateway._previews[preview_id].path

    # 1. Driving PREVIEW_LIMIT + 1 previews evicts the oldest and unlinks its file while live ones remain.
    s0 = Session.open_path(root, str(original))
    s1 = Session.open_path(root, str(original))
    s2 = Session.open_path(root, str(original))
    p0_id, p0_path = make_preview(s0, "세션 0")
    p1_id, p1_path = make_preview(s1, "세션 1")
    assert p0_path.is_file() and p1_path.is_file()
    clock[0] = 1100.0
    p2_id, p2_path = make_preview(s2, "세션 2")
    assert p0_id not in gateway._previews
    assert not p0_path.exists()
    assert p1_path.is_file() and p2_path.is_file()
    assert list(gateway._previews) == [p1_id, p2_id]

    # 2. Newer preview on the same session supersedes and unlinks the older preview for that session.
    p1_next_id, p1_next_path = make_preview(s1, "세션 1 교체")
    assert p1_id not in gateway._previews
    assert not p1_path.exists()
    assert p1_next_path.is_file() and p2_path.is_file()
    p1_id, p1_path = p1_next_id, p1_next_path
    clock[0] = 1150.0
    p2_id, p2_path = make_preview(s2, "세션 2 교체")

    # 3. TTL expiry drops the expired preview and unlinks its scratch file while live ones remain.
    clock[0] = 1100.0 + rt_ui_doc.PREVIEW_TTL + 10.0
    with pytest.raises(rt_ui_doc.PageError) as expired_err:
        gateway.read(root, tools, "render", {
            **binding(s1), "previewId": p1_id, "page": 2, "scale": 1,
        })
    assert expired_err.value.code == "preview_expired"
    assert p1_id not in gateway._previews
    assert not p1_path.exists()
    assert p2_id in gateway._previews and p2_path.is_file()

    # 4. Evicted while a render turn for that preview is in flight: file survives until render returns.
    started = threading.Event()
    release = threading.Event()

    def slow_render(path, page, *, scale, out_dir):
        if Path(path) == p2_path:
            started.set()
            assert release.wait(10)
            assert p2_path.is_file()
        return base_render(path, page, scale=scale, out_dir=out_dir)

    monkeypatch.setattr(engine, "render", slow_render)
    s3 = Session.open_path(root, str(original))
    s4 = Session.open_path(root, str(original))
    with ThreadPoolExecutor(max_workers=1) as pool:
        inflight = pool.submit(gateway.read, root, tools, "render", {
            **binding(s2), "previewId": p2_id, "page": 2, "scale": 1,
        })
        try:
            assert started.wait(5)
            p3_id, p3_path = make_preview(s3, "세션 3")
            p4_id, p4_path = make_preview(s4, "세션 4")
            assert p2_id not in gateway._previews
            assert p2_path.is_file()
        finally:
            release.set()
        payload, png = inflight.result(timeout=5)
    assert payload["previewId"] == p2_id and png.startswith(PNG_SIGNATURE)
    assert not p2_path.exists()
    assert p3_path.is_file() and p4_path.is_file()
    assert list(gateway._previews) == [p3_id, p4_id]

    # 5. Files outside the rt_doc preview scratch folder are never unlinked, and missing files are tolerated.
    outside = tmp_path / "outside-preview.hwpx"
    outside.write_bytes(b"outside")
    p3_path.unlink()
    gateway._previews[p3_id] = rt_ui_doc.Preview(
        p3_id, s3.dir, binding(s3)["rev"], outside, gateway._previews[p3_id].rev,
        2, frozenset({2}), [], [], {}, clock[0] + rt_ui_doc.PREVIEW_TTL,
    )
    s5 = Session.open_path(root, str(original))
    p5_id, p5_path = make_preview(s5, "세션 5")
    assert p3_id not in gateway._previews
    assert outside.is_file()
    assert p4_path.is_file() and p5_path.is_file()

