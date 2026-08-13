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
        # color_anomaly is False, not absent: this fixture's charPr carries a
        # readable colour, so the verdict was made (T128). Absence would mean
        # "could not judge", which is a different claim.
        "runs": [{"index": 0, "text": "selected", "charpr": "0",
                  "color_anomaly": False}],
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


# --------------------------------------------------------------------------- #
# T112 — a form's blank is a RULED run, and the value has to land on the rule.
# --------------------------------------------------------------------------- #

def _pps_runs(at_para):
    profile = form_inspect.analyze(
        str(PPS_SIGNATURE_FORM), full_text=[("para", at_para)])[0]
    return profile["full_text"][0]["runs"]


@pytest.mark.parametrize("at_para,ruled_indexes", [
    (18, [2]),   # 주소: leading spaces, label run, ruled blank run
    (20, [1]),   # 업체명(성명): label run, then the rule fused with (인)
    (64, []),    # 본인 성명: one run, no rule at all
])
def test_ruled_runs_are_named_on_the_real_form(at_para, ruled_indexes):
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    runs = _pps_runs(at_para)
    assert [r["index"] for r in runs if r.get("ruled")] == ruled_indexes
    # `ruled` is present only when true, so the run-record shape asserted by
    # the CLI test above is unchanged for every ordinary run. `color_anomaly`
    # is different on purpose (T128): it is present whenever the colour COULD
    # be read, because absence has to keep meaning "not judged" — the whole
    # point of T127 was that reporting an unexamined property as clean is not
    # a check. `color_value` rides along only when the verdict is true.
    for run in runs:
        assert set(run) <= {"index", "text", "charpr", "ruled",
                            "color_anomaly", "color_value"}


def test_ruled_is_a_narrow_signal_not_a_blanket():
    """Non-vacuity in both directions: if every charPr looked ruled the flag
    would carry no information, and if none did the seat would be unfindable."""
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    with zipfile.ZipFile(PPS_SIGNATURE_FORM) as z:
        header = "".join(
            z.read(n).decode("utf-8") for n in z.namelist()
            if "header" in n.lower())
    defs = form_inspect._charpr_defs(header)
    ruled = {cid for cid in defs if form_inspect._is_ruled(defs, cid)}
    assert 0 < len(ruled) < len(defs) // 4, (len(ruled), len(defs))


def test_a_short_charpr_does_not_inherit_its_neighbours_rule():
    """The body bound is the charPr boundary, not a fixed window.

    Measured: a real charPr body is 649 chars with `underline` at offset 462,
    so a 400-char window cannot see it — but searching the rest of the header
    would attribute a neighbour's rule to a short definition. Both directions
    are wrong, and this pins the second one.
    """
    header = (
        '<hh:charPr id="1" height="1000"><hh:fontRef hangul="1"/></hh:charPr>'
        '<hh:charPr id="2" height="1000"><hh:fontRef hangul="1"/>'
        '<hh:underline type="BOTTOM" shape="SOLID" color="#000000"/>'
        '</hh:charPr>'
        '<hh:charPr id="3" height="1000"/>'
    )
    defs = form_inspect._charpr_defs(header)
    assert defs["1"]["underline"] in (None, "NONE")
    assert defs["2"]["underline"] == "BOTTOM"
    assert not form_inspect._is_ruled(defs, "1")
    assert form_inspect._is_ruled(defs, "2")
    # A self-closing definition has no body at all.
    assert not form_inspect._is_ruled(defs, "3")


def test_extending_the_label_run_leaves_the_value_off_the_rule(tmp_path):
    """The finding T112 records, asserted rather than described.

    The T52 pattern above writes the value into the LABEL run and shortens the
    marker run's padding. That preserves every charPr id and paragraph identity
    — which is all T52 asserts — but the value then sits in a run with no rule
    while the ruled run survives beside it. On A2's accepted artifact the
    address line rendered exactly that way: the value on one line and an
    orphaned rule below it, and both the deterministic checks and the vision
    pass let it through.
    """
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    runs = _pps_runs(18)
    label, blank = runs[1], runs[2]
    assert not label.get("ruled") and blank.get("ruled")

    wrong = tmp_path / "label-run.hwpx"
    preedit.replace_placeholders(
        str(PPS_SIGNATURE_FORM), wrong,
        {label["text"]: {"text": label["text"] + "서울특별시 강남구", "at_para": 18}})
    after = form_inspect.analyze(
        str(wrong), full_text=[("para", 18)])[0]["full_text"][0]["runs"]
    carrying = [r for r in after if "서울특별시" in r["text"]]
    assert carrying and not any(r.get("ruled") for r in carrying), (
        "the value must be off the rule for this to be the defect it is")
    assert any(r.get("ruled") and not r["text"].strip() for r in after), (
        "the ruled blank survives as an orphan")

    # `replace` still cannot reach this seat, and that refusal is correct: the
    # rule is a whitespace-only run, and tier A compares run text stripped, so a
    # whitespace-only key is a wildcard over every whitespace-only run. Scoping
    # to one paragraph does not save it — this paragraph has two such runs, the
    # indent and the rule.
    with pytest.raises(preedit.PreeditError):
        preedit.replace_placeholders(
            str(PPS_SIGNATURE_FORM), tmp_path / "unreachable.hwpx",
            {blank["text"]: {"text": "서울특별시 강남구" + " " * 20,
                             "at_para": 18}})

    # T115 closes it with an ADDRESS instead of a key: the value lands in the
    # ruled run, so the rule runs under it, and no charPr id moves.
    fixed = tmp_path / "on-the-rule.hwpx"
    result = preedit.set_runs(
        str(PPS_SIGNATURE_FORM), fixed,
        [(18, blank["index"], "서울특별시 강남구 테헤란로 100" + " " * 8)])
    assert result["written"] == 1
    assert result["runs"][0]["charpr"] == blank["charpr"]
    on_rule = form_inspect.analyze(
        str(fixed), full_text=[("para", 18)])[0]["full_text"][0]["runs"]
    carrying = [r for r in on_rule if "서울특별시" in r["text"]]
    assert carrying and all(r.get("ruled") for r in carrying), on_rule
    assert [r["charpr"] for r in on_rule] == [r["charpr"] for r in runs]


def test_a_rule_fused_with_a_marker_can_be_written_on(tmp_path):
    """The seat that IS reachable, and the pattern to use on it.

    at_para 20's rule shares its run with the `(인)` marker, so the key has a
    non-whitespace anchor and the value can be written ONTO the rule with the
    marker reproduced verbatim. charPr ids, run count and the marker all hold.
    """
    if not PPS_SIGNATURE_FORM.is_file():
        pytest.skip("PPS corpus absent")
    runs = _pps_runs(20)
    blank = runs[1]
    assert blank.get("ruled") and blank["text"].rstrip().endswith("(인)")

    out = tmp_path / "onto-the-rule.hwpx"
    preedit.replace_placeholders(
        str(PPS_SIGNATURE_FORM), out,
        {blank["text"]: {"text": "   테스트상사" + " " * 24 + "(인)",
                         "at_para": 20}})
    after = form_inspect.analyze(
        str(out), full_text=[("para", 20)])[0]["full_text"][0]["runs"]
    carrying = [r for r in after if "테스트상사" in r["text"]]
    assert carrying and all(r.get("ruled") for r in carrying)
    assert [r["charpr"] for r in after] == [r["charpr"] for r in runs]
    assert sum(r["text"].count("(인)") for r in after) == 1
