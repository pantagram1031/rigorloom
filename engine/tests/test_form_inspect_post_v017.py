"""Focused regressions for post-v0.17 form-inspection contracts."""

import html
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import form_inspect
import preedit


ROOT = Path(__file__).parents[1]
PPS_FORM = ROOT.parent / "tests" / "corpus" / "forms" / "grant" / \
    "pps-hyeopeop-seungin-sinchengseo.hwpx"
PPS_SIGNATURE_FORM = ROOT.parent / "tests" / "corpus" / "forms" / "grant" / \
    "pps-jeongbogonggae-donguiseo.hwpx"


def _build_hwpx(tmp_path, paragraphs):
    """Build a minimal HWPX with paragraph ``runs`` in document order."""
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    body = []
    for runs in paragraphs:
        body.append('<hp:p paraPrIDRef="0">')
        for text in runs:
            body.append(
                '<hp:run charPrIDRef="0"><hp:t>'
                + html.escape(text)
                + '</hp:t></hp:run>'
            )
        body.append('</hp:p>')
    path = tmp_path / "synthetic-post-v017.hwpx"
    section = '<hp:sec xmlns:hp="urn:hp">' + "".join(body) + "</hp:sec>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
    return path


def _build_nested_hwpx(tmp_path):
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    section = (
        '<hp:sec xmlns:hp="urn:hp">'
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="0"><hp:t>outer-before</hp:t>'
        '<hp:tbl><hp:tr><hp:tc>'
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="0"><hp:t>inner</hp:t></hp:run>'
        '</hp:p>'
        '</hp:tc></hp:tr></hp:tbl>'
        '<hp:t>outer-after</hp:t></hp:run>'
        '</hp:p>'
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="0"><hp:t>next</hp:t></hp:run>'
        '</hp:p>'
        '</hp:sec>'
    )
    path = tmp_path / "nested-post-v017.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
    return path


def _build_multisection_drift_hwpx(tmp_path):
    """Build nested/multi-section XML where legacy and preedit orders differ."""
    section0 = (
        '<hp:sec xmlns:hp="urn:hp">'
        # Legacy form_inspect skips this paragraph (no paraPrIDRef), while
        # preedit still assigns it at_para=0.
        '<hp:p><hp:run charPrIDRef="0"><hp:t>ignored</hp:t></hp:run></hp:p>'
        # The legacy regex stops at the nested paragraph's close tag.  Its
        # text therefore belongs to INNER, not to this outer table paragraph.
        '<hp:p paraPrIDRef="0"><hp:tbl><hp:tr><hp:tc>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>INNER</hp:t>'
        '</hp:run></hp:p>'
        '</hp:tc></hp:tr></hp:tbl></hp:p>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>DUP</hp:t>'
        '</hp:run></hp:p>'
        '</hp:sec>'
    )
    section1 = (
        '<hp:sec xmlns:hp="urn:hp">'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>DUP</hp:t>'
        '</hp:run></hp:p>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>TAIL</hp:t>'
        '</hp:run></hp:p>'
        '</hp:sec>'
    )
    path = tmp_path / "multisection-drift.hwpx"
    header = (
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="1"/></hh:charPr>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section0)
        z.writestr("Contents/section1.xml", section1)
    return path


def test_long_trailing_signature_seat_is_an_anchor(tmp_path):
    seat = "업체명(성명) : " + (" " * 48) + "(인)"
    path = _build_hwpx(tmp_path, [[seat]])

    assert len(seat.strip()) > 40
    profile, _ = form_inspect.analyze(str(path), want_baseline=False)

    assert seat.strip() in profile["anchors"]
    record = next(r for r in profile["anchor_records"]
                  if r["text"] == seat.strip())
    assert record["para_idx"] == 0
    assert record["at_para"] == 0
    assert profile["removal_targets"] == []


def test_long_arbitrary_prose_is_still_not_an_anchor():
    prose = "This is arbitrary long prose " + ("x" * 35) + " (인)"
    assert len(prose) > 40
    assert not form_inspect._looks_like_anchor(prose, None, set())


def test_korean_long_arbitrary_prose_is_still_not_an_anchor():
    prose = "다음 사항을 참고하여 작성하는 일반 안내 문장입니다 " + ("가" * 30) + " (인)"
    assert len(prose) > 40
    assert not form_inspect._looks_like_anchor(prose, None, set())


def test_real_pps_signature_anchor_when_fixture_contains_seat():
    if not PPS_FORM.is_file():
        pytest.skip("PPS corpus absent")
    with zipfile.ZipFile(PPS_FORM) as z:
        xml = "".join(
            z.read(name).decode("utf-8")
            for name in z.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        )
    if "업체명" not in xml:
        # The checked-in fixture is an older PPS revision; retain a corpus
        # assertion for its existing signature-shaped 신청인 seat.
        profile, _ = form_inspect.analyze(str(PPS_FORM), want_baseline=False)
        assert any(anchor.startswith("신청인:")
                   and anchor.endswith("(서명 또는 인)")
                   for anchor in profile["anchors"])
        return
    profile, _ = form_inspect.analyze(str(PPS_FORM), want_baseline=False)
    assert any("업체명(성명)" in anchor and anchor.endswith("(인)")
               for anchor in profile["anchors"])


def test_real_pps_anchor_at_para_round_trips_exact_run_when_fixture_contains_seat(
        tmp_path):
    """The unmodified PPS corpus proves address->run->scoped replacement."""
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    with zipfile.ZipFile(PPS_SIGNATURE_FORM) as z:
        xml = "".join(
            z.read(name).decode("utf-8")
            for name in z.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        )
    if "업체명(성명)" not in xml:
        pytest.skip("unmodified PPS fixture has no 업체명(성명) signature seat")

    profile, _ = form_inspect.analyze(str(PPS_SIGNATURE_FORM), want_baseline=False)
    record = next(
        r for r in profile["anchor_records"]
        if "업체명(성명)" in r["text"] and r.get("at_para") is not None
    )
    selected = form_inspect.analyze(
        str(PPS_SIGNATURE_FORM), full_text=[("para", record["at_para"])]
    )[0]["full_text"][0]
    assert selected["at_para"] == record["at_para"]
    assert selected["text"].strip() == record["text"]
    runs = [run for run in selected["runs"] if run["text"]]
    assert len(runs) >= 2
    key = runs[0]["text"]
    assert "(인)" in runs[-1]["text"]

    out = tmp_path / (PPS_SIGNATURE_FORM.stem + ".t51-scoped.hwpx")
    result = preedit.replace_placeholders(
        str(PPS_SIGNATURE_FORM), out,
        {key: {"text": "T51_VALUE", "at_para": record["at_para"]}},
    )
    assert result["hits"][key] == 1
    with zipfile.ZipFile(out) as z:
        output_xml = "".join(
            z.read(name).decode("utf-8")
            for name in z.namelist()
            if name.startswith("Contents/section")
        )
    assert output_xml.count("T51_VALUE") == 1
    assert "(인)" in output_xml


def test_real_pps_signature_padding_is_scoped_per_run_at_same_para(tmp_path):
    """T52: compact fixed padding in the marker run with the label edit."""
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    with zipfile.ZipFile(PPS_SIGNATURE_FORM) as z:
        xml = "".join(
            z.read(name).decode("utf-8")
            for name in z.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        )
    if "업체명(성명)" not in xml:
        pytest.skip("unmodified PPS fixture has no 업체명(성명) signature seat")

    profile, _ = form_inspect.analyze(
        str(PPS_SIGNATURE_FORM), want_baseline=False
    )
    record = next(
        r for r in profile["anchor_records"]
        if "업체명(성명)" in r["text"] and r.get("at_para") is not None
    )
    selected = form_inspect.analyze(
        str(PPS_SIGNATURE_FORM), full_text=[("para", record["at_para"])]
    )[0]["full_text"][0]
    assert selected["at_para"] == record["at_para"] == 20
    runs = [run for run in selected["runs"] if run["text"]]
    assert len(runs) == 2
    label_key, marker_key = (run["text"] for run in runs)
    assert marker_key.endswith("(인)")
    original_paragraphs = {}
    original_members = {}
    with zipfile.ZipFile(PPS_SIGNATURE_FORM) as z:
        for name in z.namelist():
            data = z.read(name)
            original_members[name] = data
            if name.startswith("Contents/section") and name.endswith(".xml"):
                xml_text = data.decode("utf-8")
                for at_para, (_start, _end, p_xml) in enumerate(
                        preedit._iter_document_paragraphs(xml_text)):
                    original_paragraphs[(name, at_para)] = "".join(
                        run["text"] for run in preedit.paragraph_text_runs(p_xml)
                    )

    out = tmp_path / (PPS_SIGNATURE_FORM.stem + ".t52-padding.hwpx")
    result = preedit.replace_placeholders(
        str(PPS_SIGNATURE_FORM), out,
        {
            label_key: {
                "text": "업체명(성명) : 테스트상사",
                "at_para": record["at_para"],
            },
            marker_key: {
                "text": " " * 24 + "(인)",
                "at_para": record["at_para"],
            },
        },
    )
    assert result["hits"] == {label_key: 1, marker_key: 1}
    assert result["occurrences"] == {label_key: 1, marker_key: 1}

    output_profile, _ = form_inspect.analyze(
        str(out), full_text=[("para", record["at_para"])]
    )
    output_runs = output_profile["full_text"][0]["runs"]
    assert output_runs[0]["text"] == "업체명(성명) : 테스트상사"
    assert output_runs[0]["charpr"] == runs[0]["charpr"]
    assert output_runs[1]["text"].endswith("(인)")
    assert output_runs[1]["text"].count("(인)") == 1
    assert len(output_runs[1]["text"]) < len(marker_key)
    assert output_runs[1]["charpr"] == runs[1]["charpr"]

    with zipfile.ZipFile(out) as z:
        for name, original in original_members.items():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                continue
            assert z.read(name) == original
        output_paragraphs = {}
        for name in z.namelist():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                xml_text = z.read(name).decode("utf-8")
                for at_para, (_start, _end, p_xml) in enumerate(
                        preedit._iter_document_paragraphs(xml_text)):
                    output_paragraphs[(name, at_para)] = "".join(
                        run["text"] for run in preedit.paragraph_text_runs(p_xml)
                    )
    assert output_paragraphs.keys() == original_paragraphs.keys()
    target = (selected["section"], record["at_para"])
    for address, p_xml in original_paragraphs.items():
        if address != target:
            assert output_paragraphs[address] == p_xml


def test_full_text_para_is_exact_and_round_trips_to_scoped_replace(tmp_path):
    path = _build_hwpx(tmp_path, [["before"], ["seat", " text"], ["after"]])
    profile, _ = form_inspect.analyze(str(path), full_text=[("para", 1)])

    selected = profile["full_text"]
    assert len(selected) == 1
    assert selected[0]["at_para"] == 1
    assert selected[0]["para_idx"] == 1
    assert selected[0]["text"] == "seat text"
    assert [run["index"] for run in selected[0]["runs"]] == [0, 1]
    assert "before" not in json.dumps(selected, ensure_ascii=False)
    assert "after" not in json.dumps(selected, ensure_ascii=False)

    out = tmp_path / "scoped-replace.hwpx"
    result = preedit.replace_placeholders(
        str(path), out, {"seat": {"text": "VALUE", "at_para": 1}}
    )
    assert result["hits"]["seat"] == 1
    with zipfile.ZipFile(out) as z:
        section = z.read("Contents/section0.xml").decode("utf-8")
    assert "before" in section
    assert "VALUE" in section
    assert "after" in section


def test_full_text_nested_paragraphs_match_preedit_order_and_own_runs(tmp_path):
    path = _build_nested_hwpx(tmp_path)
    profile, _ = form_inspect.analyze(
        str(path), full_text=[("para", 0), ("para", 1), ("para", 2)]
    )
    selected = profile["full_text"]
    assert [entry["at_para"] for entry in selected] == [0, 1, 2]
    assert [entry["para_idx"] for entry in selected] == [0, 1, 2]
    assert [entry["text"] for entry in selected] == [
        "outer-beforeouter-after", "inner", "next"
    ]
    assert [[run["text"] for run in entry["runs"]] for entry in selected] == [
        ["outer-beforeouter-after"], ["inner"], ["next"]
    ]
    assert selected[0]["runs"][0]["charpr"] == "0"
    assert "inner" not in selected[0]["text"]
    assert "outer-before" not in selected[1]["text"]

    out = tmp_path / "nested-scoped-replace.hwpx"
    result = preedit.replace_placeholders(
        str(path), out,
        {
            "outer-before": {"text": "OUTER", "at_para": 0},
            "outer-after": {"text": "AFTER", "at_para": 0},
            "inner": {"text": "INNER", "at_para": 1},
            "next": {"text": "NEXT", "at_para": 2},
        },
    )
    assert result["hits"] == {
        "outer-before": 1, "outer-after": 1, "inner": 1, "next": 1,
    }
    with zipfile.ZipFile(out) as z:
        section = z.read("Contents/section0.xml").decode("utf-8")
    assert "OUTER" in section and "AFTER" in section
    assert "INNER" in section and "NEXT" in section


def test_anchor_records_bind_legacy_rows_to_global_depth_first_at_para(tmp_path):
    path = _build_multisection_drift_hwpx(tmp_path)
    profile, _ = form_inspect.analyze(str(path), want_baseline=False)

    records = profile["anchor_records"]
    inner = next(r for r in records if r["text"] == "INNER")
    dups = [r for r in records if r["text"] == "DUP"]
    tail = next(r for r in records if r["text"] == "TAIL")
    assert inner["para_idx"] == 0
    assert inner["at_para"] == 2
    assert [r["at_para"] for r in dups] == [3, 4]
    assert [r["para_idx"] for r in dups] == [1, 2]
    assert tail["at_para"] == 5

    selected = form_inspect.analyze(
        str(path), full_text=[("para", 2), ("para", 3), ("para", 4),
                              ("para", 5)]
    )[0]["full_text"]
    assert [entry["at_para"] for entry in selected] == [2, 3, 4, 5]
    assert [entry["text"] for entry in selected] == [
        "INNER", "DUP", "DUP", "TAIL"
    ]

    with pytest.raises(preedit.AmbiguousReplaceKeyError):
        preedit.replace_placeholders(
            str(path), tmp_path / "ambiguous.hwpx", {"DUP": "X"}
        )
    scoped = tmp_path / "scoped.hwpx"
    result = preedit.replace_placeholders(
        str(path), scoped, {"DUP": {"text": "SCOPED", "at_para": 3}}
    )
    assert result["hits"]["DUP"] == 1
    with zipfile.ZipFile(scoped) as z:
        text = z.read("Contents/section0.xml").decode("utf-8")
        other = z.read("Contents/section1.xml").decode("utf-8")
    assert "SCOPED" in text and "<hp:t>DUP</hp:t>" in other


def test_full_text_para_cli_and_bad_addresses_are_fail_closed(tmp_path):
    path = _build_hwpx(tmp_path, [["before"], ["selected"], ["after"]])
    script = ROOT / "scripts" / "form_inspect.py"

    good = subprocess.run(
        [sys.executable, str(script), str(path), "--full-text", "PARA:1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert good.returncode == 0
    payload = json.loads(good.stdout)
    assert payload["full_text"] == [{
        "at_para": 1,
        "para_idx": 1,
        "section": "Contents/section0.xml",
        "text": "selected",
        "runs": [{"index": 0, "text": "selected", "charpr": "0"}],
    }]

    for spec in ("PARA:nope", "PARA:99"):
        out = tmp_path / (spec.replace(":", "-") + ".json")
        bad = subprocess.run(
            [sys.executable, str(script), str(path), "--full-text", spec,
             "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert bad.returncode == 2, (spec, bad.stdout, bad.stderr)
        assert not out.exists()
