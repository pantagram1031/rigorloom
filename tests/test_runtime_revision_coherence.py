# -*- coding: utf-8 -*-
"""document/pageGeometry must profile the named revision, not the source.

PR #254 showed that ``RuntimeCore.document_page_geometry(run_id=...)``
forwarded the candidate to geometry but loaded the mapping profile from the
source. With source paragraphs ``[ALPHA, BETA]`` and candidate ``[BETA, BETA]``
the PDF-style mapper then called the candidate's first line a unique hit on
paragraph 1.

These cases fail on the desktop-own-render tip (PR #221) before the routing
fix and pass after. They do not exercise Hancom, own_render IoU probes, or a
full apply.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_core  # noqa: E402
import rt_geometry  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

import shutil


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


def _profile(texts):
    return {"anchor_records": [{"at_para": i, "text": t} for i, t in enumerate(texts)],
            "table_map": []}


def _scene(texts):
    return [{"text": t, "bbox": [20, 20 + 40 * i, 180, 40 + 40 * i], "sizePt": 12}
            for i, t in enumerate(texts)]


def _route(core, tmp_path, monkeypatch, *, run_id, source_texts, candidate_texts,
           scene_texts, candidate_ok=True):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    calls = []
    candidate_path = Path("synthetic-candidate.hwpx")

    def load_profile(tools, actual_session, **kwargs):
        subject = kwargs.get("subject")
        calls.append({"subject": "candidate" if subject == candidate_path else "source",
                      "tag": kwargs.get("tag")})
        return _profile(candidate_texts if subject == candidate_path else source_texts)

    def candidate_artifact(actual_session, requested):
        if not candidate_ok or requested != run_id:
            raise rt_codes.RpcError("artifact_missing", "candidate unavailable",
                                    runId=requested)
        return candidate_path, {"candidate": {"sha256": "c" * 64, "path": "artifact.hwpx"}}

    def page_geometry(actual_session, *, page, run_id, profile, cache, tools):
        normalize = rt_geometry.normalizer()
        if profile is None:
            spans = [{"confidence": "unmapped", "address": None, "text": line["text"]}
                     for line in _scene(scene_texts)]
        else:
            targets, _ = rt_geometry.build_targets(profile, normalize)
            spans = rt_geometry.map_spans(_scene(scene_texts), targets, normalize, 600, 800)
        return {
            "available": True,
            "source": {"kind": "candidate_prepared_pdf", "sha256": "p" * 64,
                       "runId": run_id, "candidateSha256": "c" * 64},
            "spans": spans,
        }

    monkeypatch.setattr(rt_core, "load_profile", load_profile)
    monkeypatch.setattr(rt_core, "candidate_artifact", candidate_artifact)
    monkeypatch.setattr(rt_core, "page_geometry", page_geometry)
    result = core.document_page_geometry(session, page=0, run_id=run_id)
    return result, calls


def test_page_geometry_profiles_the_named_candidate_not_the_source(core, tmp_path,
                                                                   monkeypatch):
    result, calls = _route(
        core, tmp_path, monkeypatch, run_id="a" * 32,
        source_texts=["ALPHA", "BETA"], candidate_texts=["GAMMA", "BETA"],
        scene_texts=["GAMMA", "BETA"])
    assert calls, "the mapping profile must be loaded"
    assert calls[0]["subject"] == "candidate"
    assert result["spans"][0]["confidence"] == "unique"
    assert result["spans"][0]["address"]["atPara"] == 0


def test_candidate_collision_is_not_a_false_unique_on_the_source_profile(
        core, tmp_path, monkeypatch):
    """The #254 ALPHA/BETA → BETA/BETA counterexample."""
    result, calls = _route(
        core, tmp_path, monkeypatch, run_id="a" * 32,
        source_texts=["ALPHA", "BETA"], candidate_texts=["BETA", "BETA"],
        scene_texts=["BETA", "BETA"])
    assert calls[0]["subject"] == "candidate"
    assert [span["confidence"] for span in result["spans"]] == ["ambiguous", "ambiguous"]
    assert all(span["address"] is None for span in result["spans"])


def test_geometry_subject_is_the_document_not_the_pdf_artifact(core, tmp_path,
                                                               monkeypatch):
    result, _ = _route(
        core, tmp_path, monkeypatch, run_id="a" * 32,
        source_texts=["ALPHA"], candidate_texts=["GAMMA"],
        scene_texts=["GAMMA"])
    assert result["subject"]["kind"] == "candidate"
    assert result["subject"]["runId"] == "a" * 32
    assert result["subject"]["sha256"] == "c" * 64
    assert result["source"]["sha256"] == "p" * 64
    assert result["subject"]["sha256"] != result["source"]["sha256"]


def test_missing_candidate_does_not_fall_back_to_the_source_profile(core, tmp_path,
                                                                    monkeypatch):
    with pytest.raises(rt_codes.RpcError) as excinfo:
        _route(
            core, tmp_path, monkeypatch, run_id="a" * 32,
            source_texts=["ALPHA", "BETA"], candidate_texts=["BETA", "BETA"],
            scene_texts=["BETA", "BETA"], candidate_ok=False)
    assert excinfo.value.code == "artifact_missing"
