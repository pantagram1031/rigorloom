# -*- coding: utf-8 -*-
"""E3.2 acceptance harness — verdict schema, refusal, and comparison logic.

None of these tests drive real COM. The live Hancom leg is explicitly owed
(``engine/references/owpml-writer-notes.md`` sec. 8, and the plan this slice
implements): this file proves the harness's *policy* — what it refuses to do,
what shape it emits, and how it compares two already-written HWPX packages —
using mocks for the COM boundary and real corpus files for the structural
comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "engine" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hwpx_accept  # noqa: E402
import hwpx_write  # noqa: E402

CORPUS = REPO_ROOT / "tests" / "corpus" / "forms" / "converted"
FORM_A = CORPUS / "admrul-gajokdolbom-hyuga-sinchengseo.hwpx"
FORM_B = CORPUS / "gianmun-byeolji-1ho.hwpx"


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# tiny synthetic fixtures for edit_preserved / edit_preserved_text_export —
# a marker planted in the body, in a header control's own hp:subList, or
# nowhere at all. Built the same way test_hwpx_lint.py builds its
# section-head fixtures (raw hs:sec XML + hwpx_write's own part/package
# constructors), the minimal set hwpx_write.HwpxPackage.validate() requires:
# mimetype, Contents/header.xml (the style catalog, unrelated to the "hp:header"
# control tag below), Contents/section0.xml.
# ---------------------------------------------------------------------------

_BODY_MARKER_SECTION = (
    '<hs:sec' + hwpx_write._NS_ATTRS + '>'
    '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0"'
    ' merged="0"><hp:run charPrIDRef="0"><hp:t>%s</hp:t></hp:run></hp:p>'
    '</hs:sec>'
)

_HEADER_MARKER_SECTION = (
    '<hs:sec' + hwpx_write._NS_ATTRS + '>'
    '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0"'
    ' merged="0"><hp:run charPrIDRef="0">'
    '<hp:ctrl><hp:header id="1" applyPageType="BOTH"><hp:subList>'
    '<hp:p><hp:run><hp:t>%s</hp:t></hp:run></hp:p>'
    '</hp:subList></hp:header></hp:ctrl><hp:t/></hp:run></hp:p>'
    '</hs:sec>'
)

_NO_MARKER_SECTION = (
    '<hs:sec' + hwpx_write._NS_ATTRS + '>'
    '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0"'
    ' merged="0"><hp:run charPrIDRef="0"><hp:t>nothing relevant here</hp:t>'
    '</hp:run></hp:p></hs:sec>'
)


def _write_tiny_hwpx(path, section_xml):
    payloads = [
        ("mimetype", hwpx_write.MIMETYPE),
        ("Contents/header.xml", hwpx_write._xml_bytes(hwpx_write._BLANK_HEADER)),
        ("Contents/section0.xml", hwpx_write._xml_bytes(section_xml)),
    ]
    hwpx_write.hancom_package(payloads).write(path)
    return path


# ---------------------------------------------------------------------------
# verdict schema
# ---------------------------------------------------------------------------

def test_all_seven_checks_are_present_and_never_fabricated_pass(tmp_path):
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(True, "busy")):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert set(verdict["checks"]) == set(hwpx_accept.CHECK_NAMES)
    assert len(hwpx_accept.CHECK_NAMES) == 8
    for name, row in verdict["checks"].items():
        assert row["status"] in ("pass", "fail", "skipped"), (name, row)
        assert row["status"] != "pass"  # busy path: nothing can have actually run
    assert verdict["ok"] is False
    assert verdict["closed_reason"] == "com_busy"


def test_verdict_is_json_serializable_and_has_the_documented_top_level_keys(tmp_path):
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(True, "busy")):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    json.dumps(verdict)  # must not raise
    for key in ("ok", "exit_code", "source", "candidate", "source_sha256",
               "candidate_sha256", "edit_marker", "closed_reason", "checks",
               "notes"):
        assert key in verdict


def test_cli_writes_accept_json_and_always_exits_3(tmp_path):
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(True, "busy")):
        code = hwpx_accept.main(["--source", str(FORM_A), "--out", str(tmp_path)])
    assert code == 3
    out_file = tmp_path / "accept.json"
    assert out_file.exists()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["closed_reason"] == "com_busy"


# ---------------------------------------------------------------------------
# refusal — the harness must never touch a live Hwp.exe session
# ---------------------------------------------------------------------------

def test_refuses_and_skips_everything_when_hwp_process_is_running(tmp_path):
    with mock.patch.object(hwpx_accept, "hwp_process_busy",
                           return_value=(True, '"Hwp.exe","1234","Console","1","1 K"')), \
         mock.patch.object(hwpx_accept, "_open_session",
                           side_effect=AssertionError(
                               "must never open a session while busy")):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["closed_reason"] == "com_busy"
    for row in verdict["checks"].values():
        assert row["status"] == "skipped"
        assert row["reason"] == "com_busy"
    # never touched the source
    assert verdict["source_sha256"] == _sha256(FORM_A)
    assert verdict["candidate"] is None
    # no candidate file materialized anywhere under tmp_path
    assert list(tmp_path.rglob("*.hwpx")) == []


def test_treats_an_unresolvable_busy_check_as_refuse_not_as_not_busy(tmp_path):
    """If tasklist itself cannot be asked, this is NOT 'safe to proceed'."""
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(None, "boom")):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["closed_reason"] == "com_busy_check_unavailable"
    for row in verdict["checks"].values():
        assert row["status"] == "skipped"


def test_never_passes_kill_stale_anywhere_in_this_module():
    """Static guard: the harness's own source never spells the flag out."""
    source = (SCRIPTS / "hwpx_accept.py").read_text(encoding="utf-8")
    assert "kill_stale" not in source
    assert "kill-stale" not in source
    assert "taskkill" not in source


def test_hwp_process_busy_uses_exact_image_name_filter():
    """The tasklist invocation must filter, not substring-scan after the fact."""
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(stdout='"Hwp.exe","1","Console","1","1 K"',
                                     returncode=0)
        busy, _detail = hwpx_accept.hwp_process_busy()
    assert busy is True
    args = run.call_args[0][0]
    assert args[0] == "tasklist"
    assert "IMAGENAME eq Hwp.exe" in args


def test_hwp_process_busy_false_on_no_match():
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(
            stdout="INFO: No tasks are running which match the specified criteria.",
            returncode=1)
        busy, _detail = hwpx_accept.hwp_process_busy()
    assert busy is False


def test_hwp_process_busy_none_when_tasklist_cannot_run():
    with mock.patch("subprocess.run", side_effect=FileNotFoundError("no tasklist")):
        busy, detail = hwpx_accept.hwp_process_busy()
    assert busy is None
    assert detail


# ---------------------------------------------------------------------------
# skipped-not-pass when COM is unavailable (busy check clears, pyhwpx absent)
# ---------------------------------------------------------------------------

def test_skipped_not_pass_when_pyhwpx_unavailable(tmp_path):
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")):
        with mock.patch.dict(sys.modules, {"pyhwpx": None}):
            verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["closed_reason"] == "com_unavailable"
    for row in verdict["checks"].values():
        assert row["status"] == "skipped"
        assert row["status"] != "pass"


def test_open_check_fails_loud_not_skipped_for_a_non_document_source(tmp_path):
    bogus = tmp_path / "not_a_document.hwpx"
    bogus.write_bytes(b"not a real hwpx")
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")):
        verdict = hwpx_accept.run(str(bogus), str(tmp_path / "out"))
    assert verdict["checks"]["open_no_repair"]["status"] == "fail"
    assert verdict["checks"]["open_no_repair"]["reason"] == "source_not_a_document"
    # everything after open is skipped, specifically because open failed
    for name in hwpx_accept.CHECK_NAMES[1:]:
        assert verdict["checks"][name] == {"status": "skipped", "reason": "open_failed"}


def test_bogus_source_never_reaches_pyhwpx_import(tmp_path):
    """document_shape_reason must gate before COM availability is even asked."""
    bogus = tmp_path / "not_a_document.hwpx"
    bogus.write_bytes(b"\x00\x00\x00\x00")
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")):
        with mock.patch.dict(sys.modules, {"pyhwpx": None}):
            verdict = hwpx_accept.run(str(bogus), str(tmp_path / "out"))
    # a bad shape is reported as a real FAIL, not folded into com_unavailable
    assert verdict["checks"]["open_no_repair"]["status"] == "fail"
    assert verdict["closed_reason"] is None


# ---------------------------------------------------------------------------
# a mocked full run through the ordered check sequence
# ---------------------------------------------------------------------------

class _FakeHwp:
    """Enough of the pyhwpx surface for one open/save/quit/reopen cycle."""

    def __init__(self, path=None, title="문서 - 한글", text="hello edited world"):
        self._path = path
        self.title = title
        self._text = text
        self.quit_called = False

    def SetMessageBoxMode(self, _mode):
        pass

    def open(self, path):
        self._path = path
        return True

    @property
    def Title(self):
        return self.title

    def save_as(self, path, fmt=None):
        Path(path).write_bytes(Path(self._path).read_bytes())
        return True

    def get_text_file(self, _fmt, _option):
        return self._text

    def quit(self):
        self.quit_called = True


def test_full_mocked_run_marks_every_check_pass_with_a_matching_edit_marker(tmp_path):
    sessions = []
    marker = "hello edited"
    source = _write_tiny_hwpx(tmp_path / "src.hwpx", _BODY_MARKER_SECTION % marker)

    def _fake_open_session(path):
        h = _FakeHwp(path=path, text="%s world" % marker)
        sessions.append(h)
        return h, True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(source), str(tmp_path / "out"), edit_marker=marker)

    assert verdict["checks"]["open_no_repair"]["status"] == "pass"
    assert verdict["checks"]["save_new_path"]["status"] == "pass"
    assert verdict["checks"]["close"]["status"] == "pass"
    assert verdict["checks"]["reopen"]["status"] == "pass"
    assert verdict["checks"]["edit_preserved"]["status"] == "pass"
    assert verdict["checks"]["edit_preserved"]["kind"] == "body"
    assert verdict["checks"]["edit_preserved_text_export"]["status"] == "pass"
    # structures_preserved: candidate is a byte copy of the source here, so it
    # must trivially match.
    assert verdict["checks"]["structures_preserved"]["status"] == "pass"
    assert verdict["checks"]["bindings_valid"]["status"] == "pass"
    assert verdict["candidate_sha256"] == _sha256(source)
    assert len(sessions) == 2  # one open, one reopen
    assert sessions[0].quit_called


def test_header_anchored_marker_passes_lexically_export_reports_not_exported(tmp_path):
    """The gap hancom-acceptance-02.md run 02 (d) root-caused, now closed:
    a marker planted inside a hp:header control is found by the lexical
    reader (which sees every Contents/section*.xml paragraph flow) even
    though GetTextFile("TEXT", "") -- which does not export header/footer/
    footnote/endnote content -- never contained it."""
    marker = "RIGORLOOM-HEADER-MARKER"
    source = _write_tiny_hwpx(tmp_path / "src.hwpx", _HEADER_MARKER_SECTION % marker)

    def _fake_open_session(path):
        return _FakeHwp(path=path, text="body text without the marker"), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(source), str(tmp_path / "out"), edit_marker=marker)

    assert verdict["checks"]["edit_preserved"]["status"] == "pass"
    assert verdict["checks"]["edit_preserved"]["kind"] == "header"
    assert verdict["checks"]["edit_preserved_text_export"] == {
        "status": "skipped", "reason": "not_exported",
        "note": mock.ANY,
    }


def test_genuinely_lost_marker_fails_both_edit_preserved_checks(tmp_path):
    marker = "RIGORLOOM-NEVER-PLANTED-MARKER"
    source = _write_tiny_hwpx(tmp_path / "src.hwpx", _NO_MARKER_SECTION)

    def _fake_open_session(path):
        return _FakeHwp(path=path, text="nothing relevant here either"), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(source), str(tmp_path / "out"), edit_marker=marker)

    assert verdict["checks"]["edit_preserved"] == {
        "status": "fail", "reason": "edit_marker_not_found"}
    assert verdict["checks"]["edit_preserved_text_export"] == {
        "status": "fail", "reason": "edit_marker_not_found"}


def test_edit_preserved_is_skipped_not_fabricated_when_no_marker_given(tmp_path):
    def _fake_open_session(path):
        return _FakeHwp(path=path), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path), edit_marker=None)
    assert verdict["checks"]["edit_preserved"] == {"status": "skipped",
                                                    "reason": "no_edit_description"}
    assert verdict["checks"]["edit_preserved_text_export"] == {
        "status": "skipped", "reason": "no_edit_description"}


def test_edit_preserved_fails_when_marker_absent_from_reopened_text(tmp_path):
    def _fake_open_session(path):
        return _FakeHwp(path=path, text="nothing relevant here"), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path), edit_marker="not present")
    assert verdict["checks"]["edit_preserved"]["status"] == "fail"
    assert verdict["checks"]["edit_preserved"]["reason"] == "edit_marker_not_found"


def test_open_returned_false_is_a_fail_and_skips_the_rest(tmp_path):
    def _fake_open_session(path):
        return _FakeHwp(path=path), False

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["checks"]["open_no_repair"]["status"] == "fail"
    assert verdict["checks"]["open_no_repair"]["reason"] == "open_returned_false"
    for name in hwpx_accept.CHECK_NAMES[1:]:
        assert verdict["checks"][name]["status"] == "skipped"


def test_repair_title_marker_is_a_fail_not_a_silent_dismissal(tmp_path):
    def _fake_open_session(path):
        return _FakeHwp(path=path, title="문서(복구됨) - 한글"), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["checks"]["open_no_repair"]["status"] == "fail"
    assert verdict["checks"]["open_no_repair"]["reason"] == "repair_dialog_suspected"


def test_never_modifies_the_source_file_across_a_full_run(tmp_path):
    before = _sha256(FORM_A)

    def _fake_open_session(path):
        return _FakeHwp(path=path), True

    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_open_session", side_effect=_fake_open_session):
        hwpx_accept.run(str(FORM_A), str(tmp_path), edit_marker="hello edited")
    assert _sha256(FORM_A) == before


def test_candidate_naming_scheme_never_folds_back_onto_the_source(tmp_path):
    """The concatenation itself is not idempotent -- documents why the guard
    below is unreachable via any real filename, so it is tested directly."""
    candidate = hwpx_accept._candidate_path_for(FORM_A, tmp_path)
    assert candidate.resolve() != FORM_A.resolve()


def test_candidate_path_collision_guard_refuses_and_skips_everything(tmp_path):
    """If a future naming scheme ever did fold back onto the source, refuse."""
    with mock.patch.object(hwpx_accept, "hwp_process_busy", return_value=(False, "")), \
         mock.patch.dict(sys.modules, {"pyhwpx": mock.Mock()}), \
         mock.patch.object(hwpx_accept, "_candidate_path_for",
                           return_value=Path(FORM_A).resolve()):
        verdict = hwpx_accept.run(str(FORM_A), str(tmp_path))
    assert verdict["closed_reason"] == "candidate_path_collides_with_source"
    for row in verdict["checks"].values():
        assert row["status"] == "skipped"


# ---------------------------------------------------------------------------
# structural comparison — real corpus files, no COM
# ---------------------------------------------------------------------------

def test_compare_structures_passes_when_source_and_candidate_are_identical():
    result = hwpx_accept.compare_structures(FORM_A, FORM_A)
    assert result["status"] == "pass"
    body = result["body_structure"]
    assert body["status"] == "pass"
    assert body["source_tables"] == body["candidate_tables"]
    assert body["source_paragraphs"] == body["candidate_paragraphs"]
    assert body["source_table_cells"] == body["candidate_table_cells"]
    assert result["style_catalog_delta"]["qname_count_delta"] == {}
    assert "note" in result["style_catalog_delta"]


def test_compare_structures_fails_on_two_genuinely_different_forms():
    result = hwpx_accept.compare_structures(FORM_A, FORM_B)
    assert result["status"] == "fail"
    assert result["reason"] == "table_paragraph_or_cell_count_drift"
    assert result["body_structure"]["status"] == "fail"


def test_compare_structures_reports_table_and_paragraph_counts_matching_the_reader():
    pkg = hwpx_write.HwpxPackage.read(FORM_A)
    expected_tables = sum(
        1 for name in pkg.section_names()
        for _n in pkg.part(name).tree().iter_local("tbl"))
    expected_paras = sum(
        1 for name in pkg.section_names()
        for _n in pkg.part(name).tree().iter_local("p"))
    expected_cells = sum(
        1 for name in pkg.section_names()
        for _n in pkg.part(name).tree().iter_local("tc"))
    result = hwpx_accept.compare_structures(FORM_A, FORM_A)
    body = result["body_structure"]
    assert body["source_tables"] == expected_tables
    assert body["source_paragraphs"] == expected_paras
    assert body["source_table_cells"] == expected_cells


def test_compare_structures_style_catalog_delta_is_header_xml_scoped_and_ungated():
    """The style_catalog_delta is Contents/header.xml's own qname counts --
    not the whole-package delta -- and never flips the overall status."""
    result = hwpx_accept.compare_structures(FORM_A, FORM_B)
    source_pkg = hwpx_write.HwpxPackage.read(FORM_A)
    candidate_pkg = hwpx_write.HwpxPackage.read(FORM_B)
    source_counts = hwpx_accept._header_qname_counts(source_pkg)
    candidate_counts = hwpx_accept._header_qname_counts(candidate_pkg)
    delta = result["style_catalog_delta"]["qname_count_delta"]
    for qname, value in delta.items():
        assert candidate_counts.get(qname, 0) - source_counts.get(qname, 0) == value
    # the two forms are genuinely different documents, so their style
    # catalogs differ too -- but that must not be why status is "fail":
    # body_structure's own count mismatch already accounts for it.
    assert result["status"] == "fail"
    assert result["body_structure"]["status"] == "fail"


# ---------------------------------------------------------------------------
# sha256 helper
# ---------------------------------------------------------------------------

def test_sha256_file_matches_hashlib():
    import hashlib
    expected = hashlib.sha256(FORM_A.read_bytes()).hexdigest()
    assert hwpx_accept._sha256_file(FORM_A) == expected


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
