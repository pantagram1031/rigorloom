# -*- coding: utf-8 -*-
"""Runtime gap 16: the typeface NAME on the wire, where the document declares one.

`document/inspect` reported a seat's shape as a charPr ID and a height, and no
name for the face anywhere. So the Desktop editor toolbar had an id where a
글꼴 control belongs, and could not become a real one even read-only, because
filling in 맑은 고딕 because that is what toolbars usually say would be a
fabrication in the one place this application must not fabricate.

The header already carried both halves — `charPr/fontRef` names a font id per
language, `fontface` names the face for that id — and nothing joined them
except `--baseline`, whose answer is a document-wide SET of names and so can
never say what THIS run is set in.

The tests that matter here are the ones about what is NOT claimed: every name
on the wire is a name the document's own header contains, an id the header
says nothing about comes back null, and a profile with no mapping at all says
`unavailable` rather than a field full of nulls that could be read as "this
document names no fonts".
"""
from __future__ import annotations

import re
import shutil
import zipfile

import pytest

from _runtime_client import CORPUS_FORM, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_core  # noqa: E402
import rt_session  # noqa: E402

#: Every language a HWPX fontRef can name. Read from the document, not pinned.
_FACE_RE = re.compile(r'face="([^"]+)"')


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture()
def inspected(root, source):
    core = rt_core.RuntimeCore(root)
    session_id = core.open_path(str(source))["sessionId"]
    return core.document_inspect(session_id)


def declared_faces() -> set:
    """Every face name the corpus form's own header contains."""
    with zipfile.ZipFile(CORPUS_FORM) as archive:
        header = archive.read("Contents/header.xml").decode("utf-8")
    return set(_FACE_RE.findall(header))


# --- what the document declares ------------------------------------------------

def test_the_body_baseline_carries_the_face_the_document_names(inspected):
    baseline = inspected["summary"]["baselineCharPr"]
    assert baseline["id"]
    assert isinstance(baseline["face"], dict) and baseline["face"]
    # A real 기안문 is set in a real Korean face; the point of the field is that
    # this is the DOCUMENT's answer, so it is compared against the document.
    assert baseline["face"]["hangul"] in declared_faces()
    assert inspected["summary"]["blackCharPr"]["face"]["hangul"] in declared_faces()


def test_the_typeface_state_says_the_mapping_was_read(inspected):
    state = inspected["summary"]["typefaces"]
    assert state["state"] == "read"
    assert state["reason"] is None
    assert state["charPrsWithFace"] > 0
    assert "fontface" in state["source"]


def test_every_editable_region_carries_its_own_face(inspected):
    regions = inspected["regions"]["regions"]
    assert regions
    names = declared_faces()
    for region in regions:
        assert "charPrFace" in region
        assert "charPrSuggestedFace" in region
        if region["charPrFace"] is not None:
            assert region["charPrFace"]["hangul"] in names


def test_no_name_on_the_wire_is_one_the_document_does_not_contain(inspected):
    """The anti-fabrication assertion, and the reason this field is allowed."""
    names = declared_faces()
    seen = set()
    summary = inspected["summary"]
    for shape in (summary["baselineCharPr"], summary["blackCharPr"]):
        seen.update((shape["face"] or {}).values())
    for region in inspected["regions"]["regions"]:
        for key in ("charPrFace", "charPrSuggestedFace"):
            seen.update((region[key] or {}).values())
    assert seen
    assert seen <= names, sorted(seen - names)


def test_a_seat_may_differ_from_the_body_and_the_wire_now_shows_it(inspected):
    """The field is not decoration: on this form a seat and the baseline differ.

    charPr 11 (a fill seat) and charPr 23 (the body baseline this document
    suggests for it) are set in different faces. Before this the two were two
    integers, and no caller could see that filling the seat as-is would print
    in something other than the body face.
    """
    baseline = inspected["summary"]["baselineCharPr"]["face"]["hangul"]
    faces = {region["charPrFace"]["hangul"]
             for region in inspected["regions"]["regions"]
             if region["charPrFace"]}
    assert faces
    assert faces - {baseline}, (
        "no seat on the corpus form differs from the body face; if the form "
        "changed, pick another assertion rather than deleting this one")


# --- what is NOT claimed ----------------------------------------------------------

def test_an_id_the_header_says_nothing_about_is_null_not_invented():
    profile = {"charpr_faces": {"23": {"hangul": "한양중고딕"}},
               "body_baseline_charpr": {"id": "23", "height_pt": 10.0},
               "body_black_charpr": {"id": "99", "height_pt": 10.0},
               "table_map": [{"index": 0, "cells": [
                   {"addr": {"row": 1, "col": 2}, "classification": "fill_target",
                    "charpr": "99", "charpr_suggested": "23"}]}]}

    class _Session:
        id = "s"

    summary = rt_session.document_summary(profile, _Session())
    assert summary["baselineCharPr"]["face"] == {"hangul": "한양중고딕"}
    assert summary["blackCharPr"]["face"] is None
    region = rt_session.editable_regions(profile, _Session())["regions"][0]
    assert region["charPrFace"] is None
    assert region["charPrSuggestedFace"] == {"hangul": "한양중고딕"}


def test_a_profile_with_no_mapping_says_unavailable_rather_than_all_null():
    """Two different facts, and one null cannot carry both."""
    profile = {"body_baseline_charpr": {"id": "23"},
               "body_black_charpr": {"id": "23"}, "table_map": []}

    class _Session:
        id = "s"

    state = rt_session.document_summary(profile, _Session())["typefaces"]
    assert state["state"] == "unavailable"
    assert "predates" in state["reason"]
    assert state["charPrsWithFace"] == 0


def test_the_face_is_per_language_because_the_document_is(inspected):
    """Hangul's own font dialog has separate 한글 and 영문 faces, and this form
    declares a different face for `other` than for `hangul`. Collapsing the map
    to one name would be a guess about which declared truth the reader meant."""
    face = inspected["summary"]["baselineCharPr"]["face"]
    assert {"hangul", "latin"} <= set(face)
    assert len(set(face.values())) > 1, face


# --- the surfaces agree ------------------------------------------------------------

def test_the_cli_reports_the_same_faces(root, source, inspected):
    session_id = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    from_cli = run_cli(root, "inspect", "--session", session_id).result
    assert (from_cli["summary"]["baselineCharPr"]["face"]
            == inspected["summary"]["baselineCharPr"]["face"])
    assert (from_cli["regions"]["regions"][0]["charPrFace"]
            == inspected["regions"]["regions"][0]["charPrFace"])
