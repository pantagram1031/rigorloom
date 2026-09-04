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


@pytest.fixture()
def without_tier3(monkeypatch):
    """Tier 3 off, so the honest-absence half of this file stays under test.

    An HWPX now normally gets a page: ``rt_own`` draws one and grades it
    ``own-uncertified``. That is the point of tier 3 and it retires nothing —
    ``needs_conversion`` is still the answer on a machine where our own
    renderer cannot run either, and that answer has to keep naming a way out.

    The switch is the renderer's PATH, not a flag, so the tests below travel
    through the same refusal wiring a real install with a stripped bundle would
    (``own.reason == "script_missing"``) rather than through a branch that only
    exists for tests.
    """
    import rt_own

    monkeypatch.setattr(rt_own, "own_render_script",
                        lambda tools=None: tmp_path_missing())


def tmp_path_missing():
    from pathlib import Path

    return Path(__file__).resolve().parent / "_no_such_own_render.py"


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

def test_an_hwpx_has_no_page_image_and_says_exactly_why(core, tmp_path,
                                                        without_tier3):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_render(session)
    assert result["available"] is False
    # and the third tier's own refusal rides along, so the user is not told
    # only about the Hancom they do not have
    assert result["unavailable"]["own"]["reason"] == "script_missing"
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
    """The Desktop renders this state; it must arrive as a response.

    Driven over the WIRE, so tier 3 cannot be monkeypatched out of a server in
    another process. The subject is therefore an opaque file rather than an
    HWPX: an HWPX now gets a tier-3 page, and the property under test here is
    the envelope, not which document reaches which tier.
    """
    root = tmp_path / "root"
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    session = run_cli(root, "open", "--path", str(notes)).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        result = client.ok("document/render", {"sessionId": session})
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "no_rasterizable_artifact"
    assert result["capability"]["converter"]["state"] == "no"


def test_every_unavailable_result_names_a_reason_from_the_closed_set(
        core, tmp_path, monkeypatch, without_tier3):
    """No branch may answer "no page" without saying which no.

    Prompted by a real misread: an integrator looked for the reason at
    ``result.reason`` and got ``None``, because it lives at
    ``result.unavailable.reason``. The field was set — but a rule that only
    holds because of an internal assert is a rule nobody can check from
    outside, so this walks every branch through the public API instead.
    """
    cases = {}

    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    cases["needs_conversion"] = core.document_render(session)

    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    opaque = core.open_path(str(notes))["sessionId"]
    cases["no_rasterizable_artifact"] = core.document_render(opaque)

    pdf = tmp_path / "doc.pdf"
    if HAVE_RASTERIZER:
        _pdf(tmp_path, name="doc.pdf")
    else:
        pdf.write_bytes(b"%PDF-1.4\n%stub\n")
    pdf_session = core.open_path(str(pdf))["sessionId"]
    monkeypatch.setattr(rt_render, "rasterizer_module", lambda: None)
    cases["rasterizer_missing"] = core.document_render(pdf_session)
    monkeypatch.undo()

    for expected, result in cases.items():
        assert result["available"] is False, expected
        unavailable = result["unavailable"]
        assert unavailable["reason"] == expected
        assert unavailable["reason"] in rt_render.UNAVAILABLE_REASONS
        assert unavailable["detail"].strip(), f"{expected} gave no detail"
        # the closed set travels with the answer, so a client can switch on it
        assert (result["capability"]["unavailableReasons"]
                == list(rt_render.UNAVAILABLE_REASONS))
        # and the reason is NOT at the top level, which is where it was looked
        # for; if that ever changes, this is the test that should be updated
        assert "reason" not in result

    assert set(cases) < set(rt_render.UNAVAILABLE_REASONS)


def test_the_artifact_missing_branch_also_names_its_reason(core, tmp_path):
    """The fourth reason, reached by deleting a published candidate's bytes."""
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    handle = core.store.get(session)
    handle.ensure_dirs()
    run_dir = handle.candidates_dir / ("a" * 32)
    run_dir.mkdir(parents=True)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render(session, run_id="a" * 32)
    # no receipt at all is an artifact_missing REFUSAL from the receipt reader,
    # which is a different and louder thing than an unavailable render
    assert excinfo.value.code == "artifact_missing"


def test_no_fabricated_image_is_ever_returned(core, tmp_path, without_tier3):
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


# --- tier 3, our own renderer ------------------------------------------------
#
# What a FRESH INSTALL sees. The packaged sidecar carries no pyhwpx, so
# `renderPrepare` answers `needs_hancom` on every machine that has not installed
# the office suite; before this tier the whole page view was a refusal card
# there. The property under test is not "there is a picture" — it is that the
# picture never claims to be Hancom's and always says what it left out.

HAVE_PILLOW = importlib.util.find_spec("PIL") is not None
needs_pillow = pytest.mark.skipif(
    not HAVE_PILLOW,
    reason="our own renderer needs Pillow, which is an optional dependency")


@needs_pillow
def test_an_hwpx_is_drawn_by_our_own_renderer_and_labelled_as_ours(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_render(session, dpi=96)
    assert result["available"] is True
    # THE LABEL. Three ways of saying the same thing, because the Desktop
    # switches on one, prints another and shows the third.
    assert result["grade"] == "own-uncertified"
    assert result["tier"] == 3
    assert result["renderer"]["certified"] is False
    assert "NOT certified" in result["gradeMeaning"]
    # and it never wears the grade that belongs to Hancom. The word itself DOES
    # appear, in `gradeMeaning`, saying this render was not checked against a
    # Hancom one — which is the opposite of a claim and must not be forbidden.
    assert result["grade"] != "hancom"
    assert result["source"]["kind"] == "own_render"
    assert "pdf" not in result["source"]["kind"]
    assert result["source"]["producedBy"] == "engine/scripts/own_render.py"
    assert base64.b64decode(result["image"]["data"])[:4] == b"\x89PNG"


@needs_pillow
def test_the_own_render_says_what_it_could_not_draw(core, tmp_path):
    """A renderer that quietly omits a border and one that draws it look the
    same in a screenshot. The list is the whole difference."""
    import json

    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_render(session, dpi=96)
    skipped = result["elementsSkipped"]
    assert isinstance(skipped, list)
    for entry in skipped:
        assert entry["element"] and entry["reason"] and entry["count"] >= 1
    # verbatim from the sidecar, not summarised on the way through
    handle = core.store.get(session)
    record = next(iter(handle.meta["ownRenders"].values()))
    sidecar = json.loads((handle.dir / record["sidecar"]).read_text(encoding="utf-8"))
    assert skipped == sidecar["elements_skipped"]
    assert result["fonts"]["state"] == "read"


@needs_pillow
def test_a_pdf_still_outranks_our_own_renderer(core, tmp_path):
    """Tier order, asserted rather than assumed: a real PDF is never displaced."""
    if not HAVE_RASTERIZER:
        pytest.skip("PyMuPDF is optional")
    session = core.open_path(str(_pdf(tmp_path, pages=2)))["sessionId"]
    result = core.document_render(session, dpi=72)
    assert result["available"] is True
    assert result["grade"] == "pdf"
    assert result["tier"] == 2
    assert result["elementsSkipped"] == []


@needs_pillow
def test_a_second_request_reuses_the_render_instead_of_redrawing(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    first = core.document_render(session, dpi=96)
    handle = core.store.get(session)
    record = next(iter(handle.meta["ownRenders"].values()))
    stamp = record["producedUtc"]
    second = core.document_render(session, dpi=96)
    assert second["image"]["sha256"] == first["image"]["sha256"]
    handle = core.store.get(session)
    assert next(iter(handle.meta["ownRenders"].values()))["producedUtc"] == stamp


@needs_pillow
def test_a_render_is_bound_to_the_bytes_it_was_drawn_from(core, tmp_path):
    """The same rule ``existing_pdf`` enforces. Drawing the page ourselves does
    not make it acceptable to serve it for a different document."""
    import rt_own

    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    core.document_render(session, dpi=96)
    handle = core.store.get(session)
    assert rt_own.existing_own(handle, subject_sha256="0" * 64, dpi=96) is None


@needs_pillow
def test_geometry_on_an_own_rendered_page_has_rects_and_claims_no_addresses(
        core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    core.document_render(session, dpi=96)
    geometry = core.document_page_geometry(session, page=0)
    assert geometry["available"] is True
    assert geometry["geometrySource"] == "own"
    assert geometry["grade"] == "own-uncertified"
    assert len(geometry["spans"]) > 0
    for span in geometry["spans"]:
        # real rectangles...
        assert 0.0 <= span["rect"][0] <= span["rect"][2] <= 1.0
        assert 0.0 <= span["rect"][1] <= span["rect"][3] <= 1.0
        # ...and not one invented address
        assert span["address"] is None
        assert span["confidence"] == "unmapped"
        assert "charX" not in span
    assert geometry["seats"] == []
    assert geometry["mapping"]["state"] == "unavailable"
    assert geometry["charOffsets"]["state"] == "unavailable"


def test_geometry_never_starts_a_render_of_its_own(core, tmp_path):
    """Geometry reads the cache only. A geometry call that drew its own page
    could hand back boxes for a page nobody is looking at."""
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    geometry = core.document_page_geometry(session, page=0)
    assert geometry["available"] is False
    assert geometry["unavailable"]["reason"] == "needs_conversion"
    assert "ownRenders" not in core.store.get(session).meta


def test_the_capability_row_says_the_renderer_is_not_certified(core):
    render = core.capability_snapshot(methods=[])["render"]
    assert render["own"]["certified"] is False
    assert render["own"]["grade"] == "own-uncertified"
    assert render["grades"] == list(__import__("rt_own").RENDER_GRADES)


def test_the_capability_row_reads_the_engine_root_it_was_given(tmp_path):
    """The frozen-bundle defect, caught at the level it actually occurs.

    A packaged sidecar finds its scripts through ``--engine-root``, which
    becomes ``RuntimeCore(engine_root=...)`` and then ``EngineTools.root``.
    ``render_capability`` used to build the tier-3 row without that, falling
    back to a path derived from ``rt_engine.__file__`` — correct in a checkout,
    and pointing outside the bundle in a frozen build. The symptom would have
    been a shipped install advertising ``own.state: "no"`` while carrying the
    renderer perfectly well, which no test that only ever runs from a checkout
    can see. So: point a core at a root that has no engine, and require the
    capability to say so.
    """
    empty = tmp_path / "not-an-engine-root"
    empty.mkdir()
    blind = RuntimeCore(tmp_path / "root", engine_root=empty)
    assert blind.capability_snapshot(methods=[])["render"]["own"]["state"] == "no"

    real = RuntimeCore(tmp_path / "root2")
    assert real.capability_snapshot(methods=[])["render"]["own"]["state"] == "yes"


# --- the CLI mirror ---------------------------------------------------------

def _opaque(tmp_path):
    """A subject no tier can draw. Out-of-process, so tier 3 cannot be patched
    off — the CLI runs in a child and only the DOCUMENT can choose the branch."""
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    return notes


def test_the_cli_reports_unavailable_as_a_success(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_opaque(tmp_path))).result["sessionId"]
    result = run_cli(root, "render", "--session", session)
    assert result.code == 0
    assert result.result["available"] is False


def test_require_render_turns_unavailable_into_a_refusal(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_opaque(tmp_path))).result["sessionId"]
    result = run_cli(root, "render", "--session", session, "--require-render")
    assert result.code == 3
    assert (result.payload["result"]["unavailable"]["reason"]
            == "no_rasterizable_artifact")
