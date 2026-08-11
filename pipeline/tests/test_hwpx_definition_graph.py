"""RED contract tests for the T153 definition/reference graph lane."""
from __future__ import annotations

import json
import ast
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hwpx_definition_graph as graph  # noqa: E402
import feature_extract  # noqa: E402


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
CORE = "http://www.hancom.co.kr/hwpml/2011/core"


LANGUAGES = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")


def _header(*, font_binary: bool = True, subst_binary: bool = True,
            char_ref: int = 0, para_ref: int = 0,
            border_ref: int = 1, numbering_ref: int = 1,
            declared_fonts: int = 7,
            numbering_char_ref: int = 4294967295) -> str:
    faces = []
    for index, language in enumerate(LANGUAGES[:declared_fonts]):
        font_attrs = 'id="0" face="Face-{index}"'.format(index=index)
        if font_binary:
            font_attrs += ' isEmbedded="1" binaryItemIDRef="image1"'
        else:
            font_attrs += ' isEmbedded="0"'
        subst = ('<hh:substFont face="Fallback" '
                 'binaryItemIDRef="image1"/>' if subst_binary else "")
        faces.append(
            f'<hh:fontface lang="{language}" fontCnt="1">'
            f'<hh:font {font_attrs}>{subst}</hh:font></hh:fontface>'
        )
    return (
        f'<hh:head xmlns:hh="{HH}">'
        '<hh:refList>'
        f'<hh:fontfaces itemCnt="{declared_fonts}">' + "".join(faces)
        + "</hh:fontfaces>"
        f'<hh:charProperties itemCnt="1"><hh:charPr id="{char_ref}" '
        'height="1000" '
        f'borderFillIDRef="{border_ref}">'
        f'<hh:fontRef hangul="0" latin="0" '
        'hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
        '</hh:charPr></hh:charProperties>'
        f'<hh:paraProperties itemCnt="1"><hh:paraPr id="{para_ref}" '
        'tabPrIDRef="0"><hh:border borderFillIDRef="1"/>'
        '<hh:heading type="NUMBER" idRef="1"/></hh:paraPr>'
        '</hh:paraProperties>'
        '<hh:borderFills itemCnt="1"><hh:borderFill id="1" threeD="0">'
        '<hh:leftBorder type="NONE" width="0.1 mm" color="#000000"/>'
        '</hh:borderFill></hh:borderFills>'
        f'<hh:numberings itemCnt="1"><hh:numbering id="{numbering_ref}">'
        f'<hh:paraHead idRef="1" charPrIDRef="{numbering_char_ref}" '
        'numFormat="DIGIT">TEXT</hh:paraHead>'
        '</hh:numbering></hh:numberings>'
        '<hh:styles itemCnt="1"><hh:style id="0" paraPrIDRef="0" '
        'charPrIDRef="0" nextStyleIDRef="0"/></hh:styles>'
        '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" '
        'autoTabRight="0"/></hh:tabProperties>'
        '</hh:refList></hh:head>'
    )


def _section(*, char_ref: int = 0, para_ref: int = 0, border_ref: int = 1,
             style_ref: int = 0, include_edges: bool = True,
             include_img: bool = False) -> str:
    edges = ""
    if include_edges:
        edges = (
            f'<hp:tbl id="1" borderFillIDRef="{border_ref}"><hp:tr>'
            f'<hp:tc borderFillIDRef="{border_ref}"><hp:cellzoneList>'
            f'<hp:cellzone id="0" borderFillIDRef="{border_ref}"/>'
            '</hp:cellzoneList></hp:tc></hp:tr></hp:tbl>'
            f'<hp:pageBorderFill type="BOTH" borderFillIDRef="{border_ref}"/>'
        )
    img = (f'<hc:img binaryItemIDRef="image1" xmlns:hc="{CORE}"/>'
           if include_img else "")
    return (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
        f'<hp:p id="1" paraPrIDRef="{para_ref}" styleIDRef="{style_ref}">'
        f'<hp:run charPrIDRef="{char_ref}"><hp:t>opaque text</hp:t></hp:run>'
        f'{img}{edges}</hp:p></hs:sec>'
    )


def _hwpx(path: Path, *, header: str | None = None, section: str | None = None,
          opf_extra: str = "", binary_name: str = "BinData/image1.png",
          binary_id: str = "image1", binary: bytes = b"PNGDATA",
          binary_media: str = "image/png", binary_embedded: str | None = "1",
          include_binary: bool = True, second_section: str | None = None) -> Path:
    header = header or _header()
    section = section or _section()
    binary_item = (
        f'<opf:item id="{binary_id}" href="{binary_name}" '
        f'media-type="{binary_media}"'
        + (f' isEmbeded="{binary_embedded}"'
           if binary_embedded is not None else "")
        + '/>' if include_binary else ""
    )
    second_manifest = ('<opf:item id="section1" href="Contents/section1.xml" '
                       'media-type="application/xml"/>'
                       if second_section is not None else "")
    second_spine = ('<opf:itemref idref="section1"/>'
                    if second_section is not None else "")
    opf = (
        f'<opf:package xmlns:opf="{OPF}" id="package" '
        'unique-identifier="uid" version="1.0">'
        '<opf:metadata><opf:title/><opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="test"/></opf:metadata>'
        '<opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        + second_manifest
        + binary_item
        + f'{opf_extra}</opf:manifest><opf:spine><opf:itemref idref="section0"/>'
        + second_spine
        + '</opf:spine></opf:package>'
    )
    container = (
        f'<ocf:container xmlns:ocf="{OCF}"><ocf:rootfiles>'
        '<ocf:rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/>'
        '</ocf:rootfiles></ocf:container>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("Contents/content.hpf", opf)
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)
        if second_section is not None:
            archive.writestr("Contents/section1.xml", second_section)
        if include_binary:
            archive.writestr(binary_name, binary)
    return path


def _header_pair() -> str:
    """Two-definition header used for reference-rewire collision tests."""
    value = _header()
    value = value.replace('<hh:charProperties itemCnt="1">',
                          '<hh:charProperties itemCnt="2">')
    value = value.replace('<hh:paraProperties itemCnt="1">',
                          '<hh:paraProperties itemCnt="2">')
    value = value.replace('<hh:styles itemCnt="1">',
                          '<hh:styles itemCnt="2">')
    value = value.replace(
        '</hh:charProperties>',
        '<hh:charPr id="1" height="1100" borderFillIDRef="1">'
        '<hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" '
        'other="0" symbol="0" user="0"/></hh:charPr></hh:charProperties>',
    )
    value = value.replace(
        '</hh:paraProperties>',
        '<hh:paraPr id="1" tabPrIDRef="0"><hh:border '
        'borderFillIDRef="1"/><hh:heading type="OUTLINE" idRef="0"/>'
        '</hh:paraPr></hh:paraProperties>',
    )
    value = value.replace(
        '</hh:styles>',
        '<hh:style id="1" paraPrIDRef="1" charPrIDRef="1" '
        'nextStyleIDRef="0"/></hh:styles>',
    )
    value = value.replace('itemCnt="1"><hh:borderFill id="1"',
                          'itemCnt="2"><hh:borderFill id="1"')
    value = value.replace('</hh:borderFills>',
                          '<hh:borderFill id="2"/></hh:borderFills>')
    value = value.replace('</hh:tabProperties>',
                          '<hh:tabPr id="1" autoTabLeft="1" '
                          'autoTabRight="0"/></hh:tabProperties>')
    value = value.replace('<hh:tabProperties itemCnt="1">',
                          '<hh:tabProperties itemCnt="2">')
    return value


def test_definition_graph_positive_is_closed_and_pathless(tmp_path: Path):
    result = graph.inspect_path(_hwpx(tmp_path / "positive.hwpx"))
    assert result["schema"] == "rigorloom/hwpx-definition-graph/v1"
    assert result["status"] == "analyzed", result
    assert set(result["source"]) == {"sha256", "bytes"}
    assert result["source"]["bytes"] > 0
    assert len(result["source"]["sha256"]) == 64
    assert result["scope"] == (
        "selected_definition_reference_graph_snapshot_only")
    assert result["evidence_ceiling"] == result["scope"]
    assert result["blocking_tokens"] == []
    assert result["not_scanned_tokens"] == sorted(result["not_scanned_tokens"])
    assert result["eligibility"] == "unknown"
    assert result["comparison"] == {"state": "unknown"}
    assert result["render"] == {"state": "not_run"}
    assert result["proof_grade"] == "none"
    assert result["submission_grade"] is False
    assert result["promotion"] == "not_run"
    assert set(result) == {
        "schema", "status", "source", "scope", "counts", "graph_sha256",
        "blocking_tokens", "not_scanned_tokens", "evidence_ceiling", "eligibility",
        "comparison", "render", "proof_grade",
        "submission_grade", "promotion",
    }
    assert len(result["graph_sha256"]) == 64
    assert result["counts"]["nodes"]["fontface"] == 7
    assert result["counts"]["edges"]["substFont->BinData"] == 7
    rendered = json.dumps(result, ensure_ascii=False)
    assert "opaque text" not in rendered
    assert "Contents/" not in rendered
    assert "image1" not in rendered


def test_archive_order_and_zip_compression_do_not_change_graph_digest(tmp_path: Path):
    first = _hwpx(tmp_path / "first.hwpx")
    second = tmp_path / "second.hwpx"
    with zipfile.ZipFile(first) as source, zipfile.ZipFile(second, "w") as target:
        infos = source.infolist()
        # OCF requires the physical stored mimetype first; the remainder may
        # be reordered and compressed differently without changing the graph.
        ordered = [infos[0], *reversed(infos[1:])]
        for index, info in enumerate(ordered):
            target.writestr(info.filename, source.read(info.filename),
                            compress_type=(zipfile.ZIP_STORED if info.filename == "mimetype"
                                           else zipfile.ZIP_DEFLATED))
    left = graph.inspect_path(first)
    right = graph.inspect_path(second)
    assert left["status"] == right["status"] == "analyzed"
    assert left["graph_sha256"] == right["graph_sha256"]
    assert left["counts"] == right["counts"]


def test_scan_bytes_matches_one_path_capture_without_emitting_path(tmp_path: Path):
    source = _hwpx(tmp_path / "source.hwpx")
    raw = source.read_bytes()
    from_bytes = graph._scan_bytes(raw)
    from_path = graph.inspect_path(source)
    assert from_bytes == from_path
    assert str(source) not in json.dumps(from_bytes)


def test_missing_section_border_owner_refs_refuse(tmp_path: Path):
    cases = [
        ('<hp:tbl id="1" borderFillIDRef="1">', "tbl"),
        ('<hp:tc borderFillIDRef="1">', "tc"),
        ('<hp:cellzone id="0" borderFillIDRef="1"/>', "cellzone"),
        ('<hp:pageBorderFill type="BOTH" borderFillIDRef="1"/>', "pageBorderFill"),
    ]
    for fragment, label in cases:
        section = _section()
        if label == "tbl":
            section = section.replace(fragment, '<hp:tbl id="1">')
        elif label == "tc":
            section = section.replace(fragment, '<hp:tc>')
        elif label == "cellzone":
            section = section.replace(fragment, '<hp:cellzone id="0"/>')
        else:
            section = section.replace(fragment, '<hp:pageBorderFill type="BOTH"/>')
        result = graph.inspect_path(_hwpx(tmp_path / f"missing-{label}.hwpx",
                                          section=section))
        assert result["status"] == "refused"
        assert result["reason_code"] in graph.REFUSAL_REASONS


def test_heading_branch_and_parahead_sentinel_are_closed(tmp_path: Path):
    outline = _header().replace('type="NUMBER" idRef="1"',
                                'type="OUTLINE" idRef="0"')
    assert graph.inspect_path(_hwpx(tmp_path / "outline.hwpx",
                                    header=outline))["status"] == "analyzed"
    unsupported = _header().replace('type="NUMBER" idRef="1"',
                                    'type="FUTURE" idRef="1"')
    assert graph.inspect_path(_hwpx(tmp_path / "future-heading.hwpx",
                                    header=unsupported))["status"] == "refused"
    bad_sentinel = _header(numbering_char_ref=4294967294)
    assert graph.inspect_path(_hwpx(tmp_path / "bad-sentinel.hwpx",
                                    header=bad_sentinel))["status"] == "refused"
    valid_char = graph.inspect_path(_hwpx(
        tmp_path / "char-sentinel.hwpx", header=_header(numbering_char_ref=0)))
    assert valid_char["status"] == "analyzed", valid_char
    bad_none = _header().replace('type="NUMBER" idRef="1"',
                                 'type="NONE" idRef="9"')
    none_result = graph.inspect_path(_hwpx(
        tmp_path / "bad-none-ref.hwpx", header=bad_none))
    assert none_result["status"] == "refused"
    assert none_result["reason_code"] == "definition_reference_invalid"


def test_numbering_definition_has_one_node_and_ordered_parahead_edges(tmp_path: Path):
    multi = _header().replace(
        '<hh:paraHead idRef="1" charPrIDRef="4294967295" '
        'numFormat="DIGIT">TEXT</hh:paraHead>',
        '<hh:paraHead idRef="1" charPrIDRef="4294967295" '
        'numFormat="DIGIT">TEXT</hh:paraHead>'
        '<hh:paraHead idRef="2" charPrIDRef="0" '
        'numFormat="DIGIT">SECOND</hh:paraHead>',
    )
    result = graph.inspect_path(_hwpx(tmp_path / "multi-numbering.hwpx",
                                      header=multi))
    assert result["status"] == "analyzed", result
    assert result["counts"]["nodes"]["numbering"] == 1
    assert result["counts"]["edges"]["numbering->charPr"] == 1

    left = graph.inspect_path(_hwpx(
        tmp_path / "parahead-id-one.hwpx", header=_header()))
    right = graph.inspect_path(_hwpx(
        tmp_path / "parahead-id-two.hwpx",
        header=_header().replace(
            '<hh:paraHead idRef="1" charPrIDRef="4294967295"',
            '<hh:paraHead idRef="2" charPrIDRef="4294967295"', 1)))
    assert left["status"] == right["status"] == "analyzed", (left, right)
    assert left["graph_sha256"] != right["graph_sha256"]


def test_typed_collection_ids_bind_payload_swaps(tmp_path: Path):
    def with_border_payload(first: str, second: str) -> str:
        value = _header_pair().replace('color="#000000"',
                                       f'color="{first}"', 1)
        return value.replace(
            '<hh:borderFill id="2"/>',
            '<hh:borderFill id="2"><hh:leftBorder type="NONE" '
            f'width="0.1 mm" color="{second}"/></hh:borderFill>', 1)

    left = graph.inspect_path(_hwpx(
        tmp_path / "border-swap-left.hwpx",
        header=with_border_payload("#000000", "#FFFFFF")))
    right = graph.inspect_path(_hwpx(
        tmp_path / "border-swap-right.hwpx",
        header=with_border_payload("#FFFFFF", "#000000")))
    assert left["status"] == right["status"] == "analyzed", (left, right)
    assert left["graph_sha256"] != right["graph_sha256"]


def test_bullet_definition_branch_is_refused_without_partial_graph(tmp_path: Path):
    bullet = _header().replace(
        '</hh:refList>', '<hh:bullets itemCnt="1"><hh:bullet id="0"/>'
        '</hh:bullets></hh:refList>')
    result = graph.inspect_path(_hwpx(tmp_path / "bullet.hwpx", header=bullet))
    assert result["status"] == "refused"
    assert result["reason_code"] == "unsupported_definition_branch"
    assert "graph_sha256" not in result and "counts" not in result


def test_tab_definition_change_changes_graph_digest(tmp_path: Path):
    first = graph.inspect_path(_hwpx(tmp_path / "tab-a.hwpx"))
    changed_header = _header().replace('autoTabLeft="0"', 'autoTabLeft="1"')
    second = graph.inspect_path(_hwpx(tmp_path / "tab-b.hwpx",
                                      header=changed_header))
    assert first["status"] == second["status"] == "analyzed"
    assert first["graph_sha256"] != second["graph_sha256"]


@pytest.mark.parametrize("family, left_header, right_header, left_section, right_section", [
    ("font_face", _header(), _header().replace("Face-0", "Face-ALT"),
     _section(), _section()),
    ("charPr_height_bold", _header(),
     _header().replace('id="0" height="1000"', 'id="0" height="1100"')
     .replace('<hh:fontRef', '<hh:bold/><hh:fontRef'), _section(), _section()),
    ("paraPr_align", _header(),
     _header().replace('<hh:heading', '<hh:align horizontal="CENTER"/>'
                       '<hh:heading'), _section(), _section()),
    ("style_para_rewire", _header_pair(),
     _header_pair().replace('<hh:style id="0" paraPrIDRef="0"',
                            '<hh:style id="0" paraPrIDRef="1"'),
     _section(), _section()),
    ("numbering_format", _header(), _header().replace('numFormat="DIGIT"',
                                                       'numFormat="ROMAN_CAPITAL"'),
     _section(), _section()),
    ("border_color", _header(), _header().replace(
        'color="#000000"', 'color="#FFFFFF"'), _section(), _section()),
])
def test_definition_feature_collision_pairs_change_opaque_graph_digest(
        tmp_path: Path, family: str, left_header: str, right_header: str,
        left_section: str, right_section: str):
    first_path = _hwpx(tmp_path / f"{family}-a.hwpx", header=left_header,
                       section=left_section)
    second_path = _hwpx(tmp_path / f"{family}-b.hwpx", header=right_header,
                        section=right_section)
    first = graph.inspect_path(first_path)
    second = graph.inspect_path(_hwpx(
        tmp_path / f"{family}-b2.hwpx", header=right_header,
        section=right_section))
    assert first["status"] == second["status"] == "analyzed", second
    assert feature_extract.extract_feature_counts(first_path) == \
        feature_extract.extract_feature_counts(second_path)
    assert first["graph_sha256"] != second["graph_sha256"]


def test_zip_timestamp_variance_is_not_a_graph_edge(tmp_path: Path):
    first = _hwpx(tmp_path / "timestamp-a.hwpx")
    second = tmp_path / "timestamp-b.hwpx"
    with zipfile.ZipFile(first) as source, zipfile.ZipFile(second, "w") as target:
        for info in source.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=(2020, 1, 2, 3, 4, 6))
            clone.compress_type = (zipfile.ZIP_STORED if info.filename == "mimetype"
                                   else zipfile.ZIP_DEFLATED)
            target.writestr(clone, source.read(info.filename))
    left = graph.inspect_path(first)
    right = graph.inspect_path(second)
    assert left["status"] == right["status"] == "analyzed"
    assert left["graph_sha256"] == right["graph_sha256"]


def test_namespace_prefix_and_attribute_order_are_canonicalized(tmp_path: Path):
    header = _header()
    section = _section()
    renamed_header = (header.replace("hh:", "h:")
                      .replace("xmlns:hh=", "xmlns:h="))
    renamed_section = (section.replace("hs:", "s:").replace("hp:", "p:")
                       .replace("xmlns:hs=", "xmlns:s=")
                       .replace("xmlns:hp=", "xmlns:p="))
    reordered_header = header.replace(
        '<hh:charPr id="0" borderFillIDRef="1">',
        '<hh:charPr borderFillIDRef="1" id="0">')
    reordered_section = section.replace(
        '<hp:p id="1" paraPrIDRef="0" styleIDRef="0">',
        '<hp:p styleIDRef="0" paraPrIDRef="0" id="1">')
    first = graph.inspect_path(_hwpx(tmp_path / "canonical-a.hwpx",
                                      header=header, section=section))
    prefix = graph.inspect_path(_hwpx(tmp_path / "canonical-prefix.hwpx",
                                      header=renamed_header, section=renamed_section))
    attrs = graph.inspect_path(_hwpx(tmp_path / "canonical-attrs.hwpx",
                                     header=reordered_header,
                                     section=reordered_section))
    assert first["status"] == prefix["status"] == attrs["status"] == "analyzed"
    assert first["graph_sha256"] == prefix["graph_sha256"] == attrs["graph_sha256"]


def test_bounded_input_xml_and_graph_limits_refuse_without_partial_graph(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _hwpx(tmp_path / "bounded.hwpx")
    raw = source.read_bytes()
    monkeypatch.setattr(graph, "MAX_INPUT_BYTES", len(raw) - 1)
    assert graph._scan_bytes(raw)["reason_code"] == "input_too_large"

    monkeypatch.setattr(graph, "MAX_INPUT_BYTES", len(raw) + 1)
    monkeypatch.setattr(graph, "MAX_XML_NODES", 1)
    nodes = graph.inspect_path(source)
    assert nodes["status"] == "refused"
    assert nodes["reason_code"] == "graph_limit_exceeded"
    assert "graph_sha256" not in nodes and "counts" not in nodes

    monkeypatch.setattr(graph, "MAX_XML_NODES", 100000)
    monkeypatch.setattr(graph, "MAX_XML_DEPTH", 1)
    deep = graph.inspect_path(source)
    assert deep["status"] == "refused"
    assert deep["reason_code"] == "graph_limit_exceeded"


def test_zip_archive_closes_on_downstream_validation_refusal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _hwpx(tmp_path / "archive-close.hwpx")
    raw = source.read_bytes()
    real_zipfile = graph.zipfile.ZipFile
    closed: list[bool] = []

    class TrackingZipFile(real_zipfile):
        def close(self) -> None:
            closed.append(True)
            super().close()

    def refuse_definition(*_args, **_kwargs):
        raise graph._refusal("definition_member_invalid")

    monkeypatch.setattr(graph.zipfile, "ZipFile", TrackingZipFile)
    monkeypatch.setattr(graph, "_definition_graph", refuse_definition)
    result = graph._scan_bytes(raw)
    assert result == {
        "schema": graph.SCHEMA,
        "status": "refused",
        "reason_code": "definition_member_invalid",
    }
    assert closed


def test_repeated_deterministic_json_and_cp949_help_are_private(tmp_path: Path):
    source = _hwpx(tmp_path / "deterministic.hwpx")
    first = graph.inspect_path(source)
    second = graph.inspect_path(source)
    assert first == second
    command = [sys.executable, str(SCRIPTS / "hwpx_definition_graph.py"),
               "inspect", "--help"]
    completed = subprocess.run(command, text=True, capture_output=True,
                               check=False, timeout=20,
                               env={**dict(os.environ),
                                    "PYTHONIOENCODING": "cp949"})
    assert completed.returncode == 0
    assert "Traceback" not in completed.stdout + completed.stderr


def test_public_form_matrix_is_pathless_and_nonleaking():
    root = Path(__file__).parents[2] / "tests" / "corpus" / "forms"
    files = sorted(root.rglob("*.hwpx"))
    if not files:
        pytest.skip("public HWPX corpus unavailable")
    assert len(files) == 12
    for path in files:
        result = graph.inspect_path(path)
        assert result["status"] == "analyzed"
        rendered = json.dumps(result, ensure_ascii=False)
        assert path.name not in rendered
        assert str(path) not in rendered
        assert "Contents/" not in rendered


@pytest.mark.parametrize("header, section, expected", [
    (_header(), _section(char_ref=9), "section_reference_invalid"),
    (_header(), _section(para_ref=9), "section_reference_invalid"),
    (_header(border_ref=0), _section(border_ref=0), "definition_reference_invalid"),
    (_header(numbering_ref=0), _section(), "definition_id_position_mismatch"),
])
def test_definition_reference_collisions_and_dangling_refs_refuse(
        tmp_path: Path, header: str, section: str, expected: str):
    result = graph.inspect_path(_hwpx(tmp_path / "refused.hwpx",
                                      header=header, section=section))
    assert result["status"] == "refused"
    assert result["reason_code"] == expected


@pytest.mark.parametrize("header, section, expected", [
    (_header().replace('</hh:refList>', '<hh:charProperties itemCnt="0"/>'
                       '</hh:refList>'), _section(), "definition_collection_invalid"),
    (_header().replace('<hh:fontfaces itemCnt="7">',
                       '<hh:fontfaces itemCnt="6">'), _section(),
     "definition_count_mismatch"),
    (_header().replace('<hh:charPr id="0"', '<hh:charPr id="1"'), _section(),
     "definition_id_position_mismatch"),
    (_header().replace('<hh:charProperties itemCnt="1">',
                       '<hh:charProperties itemCnt="2">').replace(
                           '</hh:charProperties>',
                           '<hh:charPr id="0"/></hh:charProperties>'), _section(),
     "definition_collection_invalid"),
    (_header().replace('<hh:charProperties itemCnt="1">',
                       '<hh:charProperties itemCnt="1"><hh:paraPr id="0"/>'), _section(),
     "definition_member_invalid"),
    (_header().replace('</hh:refList>',
                       '<x:future xmlns:x="urn:foreign"/></hh:refList>'), _section(),
     "definition_member_invalid"),
    (_header().replace('</hh:head>', '<hh:charPr id="9"/></hh:head>'), _section(),
     "definition_member_invalid"),
    (_header().replace('</hh:refList>', '<hh:future/></hh:refList>'), _section(),
     "unsupported_definition_branch"),
])
def test_definition_collection_owner_type_and_position_errors_are_generic(
        tmp_path: Path, header: str, section: str, expected: str):
    result = graph.inspect_path(_hwpx(tmp_path / "definition-error.hwpx",
                                      header=header, section=section))
    assert result["status"] == "refused"
    assert result["reason_code"] == expected


@pytest.mark.parametrize("section", [
    _section(char_ref=9),
    _section().replace('<hp:run charPrIDRef="0">',
                       '<hp:run charPrIDRef="0"><x:foreign xmlns:x="urn:x"/>'),
    _section().replace('<hp:p id="1"', '<x:p xmlns:x="urn:x" id="1"'),
])
def test_section_reference_wrong_type_foreign_owner_and_dangling_refuse(
        tmp_path: Path, section: str):
    result = graph.inspect_path(_hwpx(tmp_path / "section-error.hwpx",
                                      section=section))
    assert result["status"] == "refused"
    assert result["reason_code"] in graph.REFUSAL_REASONS


def test_font_binary_reference_and_substfont_bin_data_are_typed(tmp_path: Path):
    no_embed = _header(font_binary=False, subst_binary=False)
    result = graph.inspect_path(_hwpx(tmp_path / "no-bin-edge.hwpx",
                                      header=no_embed))
    assert result["status"] == "analyzed", result

    invalid_font = _header().replace('isEmbedded="1"', 'isEmbedded="0"', 1)
    invalid = graph.inspect_path(_hwpx(tmp_path / "invalid-font.hwpx",
                                        header=invalid_font))
    assert invalid["status"] == "refused"
    assert invalid["reason_code"] in graph.REFUSAL_REASONS

    renamed = _hwpx(
        tmp_path / "renamed.hwpx", header=_header().replace("image1", "image-renamed"),
        binary_name="BinData/renamed.png", binary_id="image-renamed",
    )
    renamed_result = graph.inspect_path(renamed)
    original_result = graph.inspect_path(_hwpx(tmp_path / "original.hwpx"))
    assert renamed_result["status"] == "analyzed"
    assert renamed_result["graph_sha256"] == original_result["graph_sha256"]


def test_definition_feature_collision_bindata_payload_is_inside_graph_digest(
        tmp_path: Path):
    first_path = _hwpx(tmp_path / "one.hwpx", binary=b"PNGDATA")
    second_path = _hwpx(tmp_path / "two.hwpx", binary=b"PNG-DIFFERENT")
    first = graph.inspect_path(first_path)
    second = graph.inspect_path(second_path)
    assert first["status"] == second["status"] == "analyzed"
    assert feature_extract.extract_feature_counts(first_path) == \
        feature_extract.extract_feature_counts(second_path)
    assert first["graph_sha256"] != second["graph_sha256"]
    assert "PNGDATA" not in json.dumps(first)
    assert "image1" not in json.dumps(first)


def test_core_img_bin_data_edge_binds_payload_and_rejects_missing_target(
        tmp_path: Path):
    first = graph.inspect_path(_hwpx(
        tmp_path / "img-one.hwpx", section=_section(include_img=True),
        binary=b"IMG-ONE"))
    second = graph.inspect_path(_hwpx(
        tmp_path / "img-two.hwpx", section=_section(include_img=True),
        binary=b"IMG-TWO"))
    assert first["status"] == second["status"] == "analyzed", (first, second)
    assert first["counts"]["edges"]["img->BinData"] == 1
    assert first["graph_sha256"] != second["graph_sha256"]
    missing_section = _section(include_img=True).replace(
        'binaryItemIDRef="image1"', 'binaryItemIDRef="missing"')
    refused = graph.inspect_path(_hwpx(
        tmp_path / "img-missing.hwpx", section=missing_section))
    assert refused["status"] == "refused"
    assert refused["reason_code"] == "binary_reference_invalid"


def test_cross_section_owner_ordinal_distinguishes_reference_swap(tmp_path: Path):
    header = _header_pair()
    left = _section(char_ref=0, para_ref=0)
    right = _section(char_ref=1, para_ref=1)
    first = graph.inspect_path(_hwpx(
        tmp_path / "section-order-a.hwpx", header=header, section=left,
        second_section=right))
    swapped = graph.inspect_path(_hwpx(
        tmp_path / "section-order-b.hwpx", header=header, section=right,
        second_section=left))
    assert first["status"] == swapped["status"] == "analyzed", (first, swapped)
    assert first["graph_sha256"] != swapped["graph_sha256"]


@pytest.mark.parametrize("kwargs", [
    {"include_binary": False},
    {"binary_media": "application/xml"},
    {"binary_embedded": None},
    {"binary_embedded": "0"},
])
def test_binary_target_missing_xml_or_nonembedded_is_exact_refusal(
        tmp_path: Path, kwargs: dict):
    result = graph.inspect_path(_hwpx(tmp_path / "bad-binary.hwpx", **kwargs))
    assert result["status"] == "refused"
    assert result["reason_code"] == "binary_reference_invalid"


def test_embedded_font_reference_requires_target_and_substfont_empty_is_valid(
        tmp_path: Path):
    missing_font_ref = _header().replace(
        'isEmbedded="1" binaryItemIDRef="image1"', 'isEmbedded="1"', 1)
    result = graph.inspect_path(_hwpx(tmp_path / "missing-font-ref.hwpx",
                                      header=missing_font_ref))
    assert result["status"] == "refused"
    assert result["reason_code"] == "binary_reference_invalid"
    empty_subst = graph.inspect_path(_hwpx(
        tmp_path / "empty-subst.hwpx", header=_header(subst_binary=False)))
    assert empty_subst["status"] == "analyzed", empty_subst


def test_cli_privacy_exit_and_help_contract(tmp_path: Path):
    source = _hwpx(tmp_path / "CANARY-document.hwpx")
    command = [sys.executable, str(SCRIPTS / "hwpx_definition_graph.py"),
               "inspect", str(source)]
    completed = subprocess.run(command, text=True, capture_output=True,
                               check=False, timeout=20)
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["status"] == "analyzed"
    assert "CANARY" not in completed.stdout + completed.stderr
    help_result = subprocess.run([sys.executable, str(SCRIPTS / "hwpx_definition_graph.py"),
                                 "--help"], text=True,
                                 capture_output=True, check=False, timeout=20)
    assert help_result.returncode == 0
    usage = subprocess.run([sys.executable, str(SCRIPTS / "hwpx_definition_graph.py"),
                            "inspect", "--bad", "CANARY-ARG"], text=True,
                           capture_output=True, check=False, timeout=20)
    assert usage.returncode == 2
    assert "CANARY" not in usage.stdout + usage.stderr


def test_cli_stdout_write_failure_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _hwpx(tmp_path / "stdout-failure.hwpx")

    class BrokenStdout:
        def write(self, _value: str) -> int:
            raise BrokenPipeError("closed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(graph.sys, "stdout", BrokenStdout())
    assert graph.main(["inspect", str(source)]) == 3


def test_refusal_vocabulary_is_closed():
    assert set(graph.REFUSAL_REASONS) == {
        "input_unavailable", "input_too_large",
        "package_outside_supported_envelope", "definition_member_invalid",
        "definition_collection_invalid", "definition_count_mismatch",
        "definition_id_position_mismatch", "definition_reference_invalid",
        "definition_reference_unresolved", "section_reference_invalid",
        "binary_reference_invalid", "unsupported_definition_branch",
        "graph_limit_exceeded", "output_write_failed", "internal_error",
    }


def test_raised_reason_literals_are_declared_and_closed():
    source = (SCRIPTS / "hwpx_definition_graph.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    raised: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"GraphError", "_refusal"}:
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                raised.add(node.args[0].value)
    assert raised == set(graph.REFUSAL_REASONS)
