# -*- coding: utf-8 -*-
"""document/render: a real raster when one is possible, honesty when not.

The property that matters most here is the negative one. An HWPX with no
converter has no page image, and the Runtime must say so in a form the Desktop
can render — never an approximation drawn from page metrics, never a blank
placeholder passed off as the document.
"""
from __future__ import annotations

import base64
import importlib.util
import shutil

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_render  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

HAVE_RASTERIZER = any(importlib.util.find_spec(name) is not None
                      for name in rt_render.RASTERIZER_MODULES)
needs_rasterizer = pytest.mark.skipif(
    not HAVE_RASTERIZER,
    reason="PyMuPDF is an optional dependency and is not installed here; the "
           "unavailable-honesty tests cover the other half")


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _pdf(tmp_path, pages=2, name="doc.pdf"):
    """A real PDF, built with the same library that will read it back."""
    module = rt_render.rasterizer_module()
    assert module is not None
    target = tmp_path / name
    document = module.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 144), f"page {index}", fontsize=36)
        document.save(str(target))
    finally:
        document.close()
    return target


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


# --- capability honesty -----------------------------------------------------

def test_render_itself_never_claims_to_convert():
    """render reads a PDF; making one is renderPrepare's separate job."""
    capability = rt_render.render_capability()
    assert capability["converter"]["state"] == "no"
    assert "converts nothing" in capability["converter"]["reason"]
    assert "document/renderPrepare" in capability["converter"]["reason"]
    assert capability["evidence"]["proofGrade"] == "none"
    assert capability["evidence"]["class"] == "structural_only"
    # the prepare row is where a converter may or may not be reported
    assert capability["prepare"]["method"] == "document/renderPrepare"
    assert capability["prepare"]["state"] in ("yes", "no")


def test_the_rasterizer_row_is_a_find_spec_not_a_claim():
    facts = rt_render.rasterizer_facts()
    assert facts["state"] in ("yes", "no")
    if facts["state"] == "no":
        assert "optional dependency" in facts["reason"]
        assert facts["formats"] == []
    else:
        assert facts["module"] in rt_render.RASTERIZER_MODULES
        assert facts["formats"] == [".pdf"]


def test_the_evidence_class_is_one_the_engine_already_defines():
    """Reused vocabulary, not a new one (document_evidence.py:40)."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine" / "scripts"))
    import document_evidence

    assert (rt_render.render_capability()["evidence"]["class"]
            in document_evidence.EVIDENCE_CLASSES)


def test_capabilities_over_the_wire_carry_the_render_block(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        capabilities = client.initialize()["result"]["capabilities"]
    assert capabilities["render"]["converter"]["state"] == "no"
    assert capabilities["render"]["rasterizer"]["state"] in ("yes", "no")
    assert "renderProbe" in capabilities["unavailable"]


def test_the_machine_probe_is_opt_in_and_absent_by_default(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        plain = client.ok("capabilities/list", {})
        assert "machineProbe" not in plain["render"]
        probed = client.ok("capabilities/list", {"probeRenderers": True})
    assert "machineProbe" in probed["render"]
    machine = probed["render"]["machineProbe"]
    assert machine["state"] in ("probed", "unavailable")
    # even with a converter on the machine, this build still declines
    assert probed["render"]["converter"]["state"] == "no"


def test_probe_renderers_must_be_a_boolean(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        error = client.err("capabilities/list", {"probeRenderers": "yes"})
    assert error["code"] == "invalid_params"


# --- the unavailable half ---------------------------------------------------

def test_an_hwpx_has_no_page_image_and_says_exactly_why(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_render(session)
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "needs_conversion"
    assert result["unavailable"]["documentKind"] == "hwpx"
    # the detail names the way out, or says why there is not one on this
    # machine — never a shrug
    detail = result["unavailable"]["detail"]
    assert "a page image needs a PDF" in detail
    if result["unavailable"]["prepare"]["state"] == "yes":
        assert "document/renderPrepare" in detail
    else:
        assert "cannot make one" in detail
    # the answer is structured, and the reason comes from a closed set
    assert result["unavailable"]["reason"] in rt_render.UNAVAILABLE_REASONS
    assert "image" not in result


def test_an_opaque_file_is_no_rasterizable_artifact(core, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    session = core.open_path(str(notes))["sessionId"]
    result = core.document_render(session)
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "no_rasterizable_artifact"


def test_unavailable_is_a_result_not_an_error_over_the_wire(tmp_path):
    """The Desktop renders this state; it must arrive as a response."""
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_hwpx(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        result = client.ok("document/render", {"sessionId": session})
    assert result["available"] is False
    assert result["capability"]["converter"]["state"] == "no"


def test_no_fabricated_image_is_ever_returned(core, tmp_path):
    """Whatever the reason, an unavailable render carries no pixels."""
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_render(session)
    flat = repr(result)
    assert "image" not in result
    assert "base64" not in flat and "data" not in result


def test_a_missing_rasterizer_is_reported_not_worked_around(core, tmp_path,
                                                            monkeypatch):
    """Simulated at the import boundary, so the branch is covered either way."""
    if HAVE_RASTERIZER:
        target = _pdf(tmp_path)
    else:
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"%PDF-1.4\n%stub\n")
    session = core.open_path(str(target))["sessionId"]
    monkeypatch.setattr(rt_render, "rasterizer_module", lambda: None)
    result = core.document_render(session)
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "rasterizer_missing"
    assert "PyMuPDF" in result["unavailable"]["detail"]


# --- the available half -----------------------------------------------------

@needs_rasterizer
def test_a_pdf_session_renders_a_real_page(core, tmp_path):
    session = core.open_path(str(_pdf(tmp_path, pages=3)))["sessionId"]
    result = core.document_render(session, page=1, dpi=96)
    assert result["available"] is True
    assert result["pageCount"] == 3
    assert result["page"] == 1
    assert result["pageSize"]["widthPt"] > 100
    image = result["image"]
    assert image["mediaType"] == "image/png"
    assert image["widthPx"] > 100 and image["heightPx"] > 100
    assert image["inline"] is True
    raw = base64.b64decode(image["data"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "that is not a PNG"
    assert len(raw) == image["bytes"]


@needs_rasterizer
def test_the_raster_is_written_to_the_session_and_the_path_is_returned(
        core, tmp_path):
    session_id = core.open_path(str(_pdf(tmp_path)))["sessionId"]
    result = core.document_render(session_id)
    session = core.store.get(session_id)
    on_disk = session.dir / result["image"]["path"]
    assert on_disk.is_file()
    assert on_disk.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["image"]["path"].startswith("renders/")


@needs_rasterizer
def test_dpi_changes_the_pixel_size_and_is_bounded(core, tmp_path):
    session = core.open_path(str(_pdf(tmp_path)))["sessionId"]
    small = core.document_render(session, dpi=48)["image"]["widthPx"]
    large = core.document_render(session, dpi=150)["image"]["widthPx"]
    assert large > small
    for bad in (0, 12, 4000):
        with pytest.raises(rt_codes.RpcError) as excinfo:
            core.document_render(session, dpi=bad)
        assert excinfo.value.code == "invalid_params"


@needs_rasterizer
def test_a_page_past_the_end_is_refused_with_the_count(core, tmp_path):
    session = core.open_path(str(_pdf(tmp_path, pages=2)))["sessionId"]
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render(session, page=7)
    assert excinfo.value.code == "page_out_of_range"
    assert excinfo.value.data["pageCount"] == 2


@needs_rasterizer
def test_inline_can_be_declined_and_the_path_still_works(core, tmp_path):
    session = core.open_path(str(_pdf(tmp_path)))["sessionId"]
    result = core.document_render(session, inline=False)
    image = result["image"]
    assert image["inline"] is False and "data" not in image
    assert image["path"] and image["bytes"] > 0


@needs_rasterizer
def test_an_oversized_raster_reports_its_path_instead_of_inlining(
        core, tmp_path, monkeypatch):
    session = core.open_path(str(_pdf(tmp_path)))["sessionId"]
    monkeypatch.setattr(rt_render, "MAX_INLINE_IMAGE_BYTES", 128)
    result = core.document_render(session, dpi=150)
    image = result["image"]
    assert image["inline"] is False
    assert "data" not in image
    assert "lower dpi" in image["reason"]


@needs_rasterizer
def test_render_travels_over_the_wire_inside_one_frame(tmp_path):
    root = tmp_path / "root"
    pdf = _pdf(tmp_path)
    run_cli(root, "open", "--path", str(pdf))
    with RuntimeClient(root) as client:
        client.initialize()
        session = client.ok("session/list", {})["sessions"][0]["sessionId"]
        result = client.ok("document/render", {"sessionId": session, "dpi": 72})
    assert result["available"] is True
    assert base64.b64decode(result["image"]["data"])[:4] == b"\x89PNG"


@needs_rasterizer
def test_a_corrupt_pdf_is_a_render_failure_not_a_crash(core, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot really a pdf at all\n")
    session = core.open_path(str(broken))["sessionId"]
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render(session)
    assert excinfo.value.code == "render_failed"


# --- the CLI mirror ---------------------------------------------------------

def test_the_cli_reports_unavailable_as_a_success(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_hwpx(tmp_path))).result["sessionId"]
    result = run_cli(root, "render", "--session", session)
    assert result.code == 0
    assert result.result["available"] is False


def test_require_render_turns_unavailable_into_a_refusal(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_hwpx(tmp_path))).result["sessionId"]
    result = run_cli(root, "render", "--session", session, "--require-render")
    assert result.code == 3
    assert result.payload["result"]["unavailable"]["reason"] == "needs_conversion"
