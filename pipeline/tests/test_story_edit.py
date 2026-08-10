"""Red-contract tests for the bounded T80 story-scoped edit surface.

These fixtures use the public OWPML namespaces and the same nested ``hp:ctrl``
story shape as the T79 inventory tests.  They deliberately carry canary IDs,
member names, and source text so a receipt/output assertion can prove that the
public surface remains structural and privacy-safe.
"""
from __future__ import annotations

import json
import hashlib
import io
import subprocess
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import story_graph  # noqa: E402
import story_edit  # noqa: E402


EDIT_SCHEMA = "rigorloom/hwpx-story-edit/v1"
SELECTOR_SCHEMA = "rigorloom/hwpx-story-edit-selector/v1"
HP, HS, HC, OPF, OCF = (
    story_graph.PARAGRAPH_NS,
    story_graph.SECTION_NS,
    story_graph.CORE_NS,
    story_graph.OPF_NS,
    story_graph.OCF_NS,
)


def _hpf() -> str:
    return (
        f'<opf:package xmlns:opf="{OPF}" id="" unique-identifier="" version="">'
        '<opf:metadata><opf:title/><opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="private-author"/></opf:metadata>'
        '<opf:manifest>'
        '<opf:item id="header-definition" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section-definition" href="Contents/section0.xml" media-type="application/xml"/>'
        '<opf:item id="style-resource" href="BinData/styles.bin" '
        'media-type="application/octet-stream" isEmbeded="1"/>'
        '</opf:manifest><opf:spine><opf:itemref idref="section-definition"/></opf:spine>'
        '</opf:package>'
    )


def _section(*, story_text: str = "SOURCE-STORY-CANARY", with_lineseg: bool = False,
             story_local: str = "header", multiple_text: bool = False,
             leading_empty_run: bool = False, no_text: bool = False,
             second_text_run: bool = False, self_closing_lineseg: bool = False,
             pi_canary: bool = False) -> str:
    # This is actual HWPX nesting: a header owner is under hp:ctrl/hp:run,
    # and its story paragraph/run lives under hp:subList.
    owner_attrs = (
        'id="RAW-CONTROL-CANARY" applyPageType="BOTH"'
        if story_local in {"header", "footer"}
        else 'instId="RAW-NOTE-CANARY"'
    )
    text_xml = "" if no_text else f"<hp:t>{story_text}</hp:t>"
    return (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}" xmlns:hc="{HC}">'
        + ('<?story-edit-pi fake="<hp:header id=\"PI-CONTROL-CANARY\"><hp:t>PI-TEXT-CANARY</hp:t>"?>'
           if pi_canary else '')
        + '<hp:p><hp:run charPrIDRef="77"><hp:t>MAIN-BODY-CANARY</hp:t>'
        + f'<hp:ctrl><hp:{story_local} {owner_attrs}>'
        + f'<hp:subList><hp:p>'
        + ('<hp:run/>' if leading_empty_run else '')
        + f'<hp:run charPrIDRef="77">{text_xml}'
        + (f'<hp:t>{story_text}-SECOND</hp:t>' if multiple_text else '')
        + '</hp:run>'
        + (f'<hp:run><hp:t>{story_text}-OTHER</hp:t></hp:run>' if second_text_run else '')
        + (('<hp:linesegarray/>' if self_closing_lineseg else '<hp:linesegarray><hp:lineseg/></hp:linesegarray>')
           if with_lineseg else '')
        + f'</hp:p></hp:subList></hp:{story_local}></hp:ctrl>'
        '</hp:run></hp:p><hp:secPr/></hs:sec>'
    )


def _container() -> str:
    return (
        f'<ocf:container xmlns:ocf="{OCF}"><ocf:rootfiles>'
        '<ocf:rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/>'
        '</ocf:rootfiles></ocf:container>'
    )


def _document(path: Path, *, story_text: str = "SOURCE-STORY-CANARY", with_lineseg: bool = False,
              story_local: str = "header", multiple_text: bool = False,
              leading_empty_run: bool = False, no_text: bool = False,
              second_text_run: bool = False,
              self_closing_lineseg: bool = False,
              pi_canary: bool = False,
              archive_comment: bytes = b"",
              compression: int = zipfile.ZIP_STORED) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", _hpf())
        archive.writestr(
            "Contents/header.xml",
            f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"/>',
        )
        archive.writestr("BinData/styles.bin", b"STYLE-RESOURCE-CANARY")
        archive.writestr(
            "Contents/section0.xml",
            _section(
                story_text=story_text, with_lineseg=with_lineseg, story_local=story_local,
                multiple_text=multiple_text,
                leading_empty_run=leading_empty_run,
                no_text=no_text,
                second_text_run=second_text_run,
                self_closing_lineseg=self_closing_lineseg,
                pi_canary=pi_canary,
            ),
            compress_type=compression,
            compresslevel=6,
        )
        archive.comment = archive_comment
    return path


def _nested_table_document(path: Path) -> Path:
    inner = (
        '<hp:tbl><hp:pos treatAsChar="1"/><hp:tr><hp:tc>'
        '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:subList><hp:p><hp:run>'
        '<hp:ctrl><hp:header id="RAW-NESTED-CONTROL" applyPageType="BOTH">'
        '<hp:subList><hp:p><hp:run><hp:t>NESTED-SOURCE-CANARY</hp:t></hp:run></hp:p>'
        '</hp:subList></hp:header></hp:ctrl></hp:run></hp:p></hp:subList>'
        '</hp:tc></hp:tr></hp:tbl>'
    )
    section = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}" xmlns:hc="{HC}">'
        '<hp:p><hp:run><hp:tbl><hp:pos treatAsChar="1"/><hp:tr><hp:tc>'
        '<hp:cellAddr rowAddr="0" colAddr="0"/><hp:subList><hp:p><hp:run>'
        f'{inner}'
        '</hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
        '</hs:sec>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", _hpf())
        archive.writestr("Contents/header.xml", f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"/>')
        archive.writestr("BinData/styles.bin", b"STYLE-RESOURCE-CANARY")
        archive.writestr("Contents/section0.xml", section)
    return path


def _selector(document: Path, *, address: str | None = None, role: str = "header",
              **extra: object) -> dict[str, object]:
    graph = story_graph.inspect_story_graph(document)
    story = next(
        story
        for member in graph["members"]
        for story in member.get("stories", [])
        if story["role"] == role
    )
    payload: dict[str, object] = {
        "schema": SELECTOR_SCHEMA,
        "address": address or f'{story["address"]}/paragraph[0]',
    }
    payload.update(extra)
    return payload


def _op(document: Path, *, selector: dict[str, object] | None = None, replacement: str = "REPLACED-STORY") -> dict[str, object]:
    return {
        "schema": EDIT_SCHEMA,
        "expected_input_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
        "selector": selector or _selector(document),
        "replacement": replacement,
    }


def _run_cli(document: Path, ops: Path, output: Path, receipt: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "story_edit.py"),
            str(document),
            "--ops-file",
            str(ops),
            "--out",
            str(output),
            "--receipt",
            str(receipt),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def test_t80_edits_one_story_run_and_keeps_body_resources_and_input_unchanged(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    before = source.read_bytes()
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source)), encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"

    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    assert output.is_file() and receipt.is_file()

    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
        assert edited.read("Contents/header.xml") == original.read("Contents/header.xml")
        assert edited.read("BinData/styles.bin") == original.read("BinData/styles.bin")
        assert b"MAIN-BODY-CANARY" in edited.read("Contents/section0.xml")
        assert b"SOURCE-STORY-CANARY" not in edited.read("Contents/section0.xml")
        assert b"REPLACED-STORY" in edited.read("Contents/section0.xml")

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload["schema"] == EDIT_SCHEMA
    assert payload["status"] == "passed"
    assert payload["address"] == _selector(source)["address"]
    for forbidden in (
        "SOURCE-STORY-CANARY",
        "REPLACED-STORY",
        "RAW-CONTROL-CANARY",
        "private-author",
        "Contents/section0.xml",
        str(tmp_path),
        "https://",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "mutator",
    [
        lambda selector: {**selector, "text": "SOURCE-STORY-CANARY"},
        lambda selector: {**selector, "control_id": "RAW-CONTROL-CANARY"},
        lambda selector: {key: value for key, value in selector.items() if key != "address"},
        lambda selector: {**selector, "address": selector["address"] + "/run[0]"},
    ],
)
def test_t80_refuses_text_first_raw_id_ambiguous_and_address_mismatch_selectors(
    tmp_path: Path, mutator,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    selector = mutator(_selector(source))
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source, selector=selector)), encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"

    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 3
    assert not output.exists()
    assert not receipt.exists()
    assert "SOURCE-STORY-CANARY" not in result.stdout + result.stderr
    assert "RAW-CONTROL-CANARY" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


@pytest.mark.parametrize("rewrite", [
    lambda address: address.replace("section[0]", "section[00]", 1),
    lambda address: address.replace("story[header,0]", "story[header,00]", 1),
    lambda address: address.replace("paragraph[0]", "paragraph[00]", 1),
])
def test_t80_rejects_noncanonical_zero_padded_addresses(tmp_path: Path, rewrite) -> None:
    source = _document(tmp_path / "input.hwpx")
    selector = _selector(source, address=rewrite(_selector(source)["address"]))
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source, selector=selector)), encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 3
    assert not output.exists() and not receipt.exists()


def test_t80_rejects_noncanonical_zero_padded_table_ancestry(tmp_path: Path) -> None:
    source = _nested_table_document(tmp_path / "nested.hwpx")
    address = _selector(source)["address"]
    assert "/container[1/0/0/2/1/0]/" in address
    selector = _selector(source, address=address.replace("/container[1/0/0/2/1/0]/",
                                                        "/container[01/0/0/2/1/0]/"))
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source, selector=selector)), encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 3
    assert not output.exists() and not receipt.exists()


def test_t80_rejects_multiple_ops_unknown_top_level_keys_and_in_place_output(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    for operation in (
        [_op(source)],
        {**_op(source), "extra": "refuse"},
    ):
        ops = tmp_path / "operation.json"
        ops.write_text(json.dumps(operation), encoding="utf-8")
        result = _run_cli(source, ops, output, receipt)
        assert result.returncode == 3
        assert '"extra"' not in result.stdout + result.stderr
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source)), encoding="utf-8")
    result = _run_cli(source, ops, source, receipt)
    assert result.returncode == 3
    assert source.is_file()


@pytest.mark.parametrize("duplicate_json", ["top_level", "selector"])
def test_t80_rejects_duplicate_json_keys_at_any_object_level(
    tmp_path: Path, duplicate_json: str,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    selector = _selector(source)
    selector_json = json.dumps(selector, ensure_ascii=False, separators=(",", ":"))
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    if duplicate_json == "top_level":
        operation_json = (
            "{"
            f'"schema":{json.dumps(EDIT_SCHEMA)},'
            f'"expected_input_sha256":{json.dumps(expected)},'
            f'"selector":{selector_json},'
            '"replacement":"A","replacement":"B"'
            "}"
        )
    else:
        address = json.dumps(selector["address"], ensure_ascii=False)
        duplicate_selector = (
            "{"
            f'"schema":{json.dumps(SELECTOR_SCHEMA)},'
            f'"address":{address},"address":{address}'
            "}"
        )
        operation_json = (
            "{"
            f'"schema":{json.dumps(EDIT_SCHEMA)},'
            f'"expected_input_sha256":{json.dumps(expected)},'
            f'"selector":{duplicate_selector},'
            '"replacement":"B"'
            "}"
        )
    ops = tmp_path / "operation.json"
    ops.write_text(operation_json, encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    result = _run_cli(source, ops, output, receipt)
    rendered = result.stdout + result.stderr
    assert result.returncode == 3
    assert not output.exists() and not receipt.exists()
    assert "Traceback" not in rendered
    assert str(tmp_path) not in rendered


def test_t80_refuses_structurally_identical_stale_source_sha(tmp_path: Path) -> None:
    original = _document(tmp_path / "original.hwpx")
    changed = _document(tmp_path / "changed.hwpx", story_text="DIFFERENT-SOURCE-CANARY")
    assert story_graph.inspect_story_graph(original) == story_graph.inspect_story_graph(changed)
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(original)), encoding="utf-8")
    result = _run_cli(changed, ops, tmp_path / "edited.hwpx", tmp_path / "receipt.json")
    assert result.returncode == 3
    assert not (tmp_path / "edited.hwpx").exists()
    assert not (tmp_path / "receipt.json").exists()
    assert "DIFFERENT-SOURCE-CANARY" not in result.stdout + result.stderr


def test_t80_removes_only_target_paragraph_lineseg_cache(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", with_lineseg=True)
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source)), encoding="utf-8")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
        assert b"linesegarray" in original.read("Contents/section0.xml")
        assert b"linesegarray" not in edited.read("Contents/section0.xml")


def test_t80_removes_self_closing_target_lineseg_cache(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", with_lineseg=True, self_closing_lineseg=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    story_edit.apply_story_edit(source, operation, output, receipt)
    with zipfile.ZipFile(output) as edited:
        assert b"<hp:linesegarray/>" not in edited.read("Contents/section0.xml")


def test_t80_processing_instruction_markup_cannot_hijack_story_target(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", pi_canary=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed"
    with zipfile.ZipFile(output) as edited:
        section = edited.read("Contents/section0.xml")
        assert b"PI-CONTROL-CANARY" in section and b"PI-TEXT-CANARY" in section
        assert b"REPLACED-STORY" in section


def test_t80_doctype_and_entity_declarations_refuse_closed_without_outputs(tmp_path: Path) -> None:
    source = _document(tmp_path / "source.hwpx")
    with zipfile.ZipFile(source) as archive:
        section = archive.read("Contents/section0.xml")
    dtd = b'<!DOCTYPE hs:sec [<!ENTITY injected "DOCTYPE-TEXT-CANARY">]>'
    bad = tmp_path / "doctype.hwpx"
    story_edit._rewrite_zip(source.read_bytes(), bad, "Contents/section0.xml", dtd + section)
    operation = _op(bad)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError):
        story_edit.apply_story_edit(bad, operation, output, receipt)
    assert not output.exists() and not receipt.exists()
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(operation), encoding="utf-8")
    result = _run_cli(bad, ops, output, receipt)
    assert result.returncode == 3
    assert "Traceback" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


def _document_with_declaration(tmp_path: Path, declaration: bytes) -> Path:
    source = _document(tmp_path / "source.hwpx")
    with zipfile.ZipFile(source) as archive:
        section = archive.read("Contents/section0.xml")
    target = tmp_path / "declared.hwpx"
    story_edit._rewrite_zip(source.read_bytes(), target, "Contents/section0.xml", declaration + section)
    return target


def test_t80_explicit_utf8_declaration_passes(tmp_path: Path) -> None:
    source = _document_with_declaration(tmp_path, b'<?xml version="1.0" encoding="UTF-8"?>')
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed"


def test_t80_utf8_bom_is_consistently_accepted(tmp_path: Path) -> None:
    base = _document(tmp_path / "base.hwpx")
    with zipfile.ZipFile(base) as archive:
        section = archive.read("Contents/section0.xml")
    source = tmp_path / "bom.hwpx"
    story_edit._rewrite_zip(
        base.read_bytes(), source, "Contents/section0.xml",
        b"\xef\xbb\xbf<?xml version=\"1.0\" encoding=\"UTF-8\"?>" + section,
    )
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed"


@pytest.mark.parametrize("encoding", [b"ISO-8859-1", b"UTF-16"])
def test_t80_non_utf8_declaration_refuses_without_outputs(tmp_path: Path, encoding: bytes) -> None:
    base = _document(tmp_path / "base.hwpx")
    selector = _selector(base)
    source = _document_with_declaration(tmp_path, b'<?xml version="1.0" encoding="' + encoding + b'"?>')
    operation = _op(source, selector=selector)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code in {"input_encoding", "input_refused", "input_package"}
    assert not output.exists() and not receipt.exists()


@pytest.mark.parametrize(
    ("source_fragment", "replacement", "changed"),
    [
        (b"&#65;", "A", False),
        (b"&#x41;", "A", False),
        (b"&amp;", "&", False),
        (b"<![CDATA[A]]>", "A", False),
    ],
)
def test_t80_semantic_noop_entity_and_cdata_values_keep_exact_archive(
    tmp_path: Path, source_fragment: bytes, replacement: str, changed: bool,
) -> None:
    source = _document(tmp_path / "source.hwpx")
    with zipfile.ZipFile(source) as archive:
        section = archive.read("Contents/section0.xml")
    section = section.replace(b"SOURCE-STORY-CANARY", source_fragment)
    mutated = tmp_path / "mutated.hwpx"
    story_edit._rewrite_zip(source.read_bytes(), mutated, "Contents/section0.xml", section)
    before = mutated.read_bytes()
    operation = _op(mutated, replacement=replacement)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(mutated, operation, output, receipt)
    assert payload["changed"] is changed
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    "source_fragment",
    [
        b"A<!--T-INNER-COMMENT-CANARY-->",
        b"A<?private-pi T-INNER-PI-CANARY?>",
    ],
)
def test_t80_comment_or_pi_inside_text_seat_refuses_without_leak_or_outputs(
    tmp_path: Path, source_fragment: bytes,
) -> None:
    source = _document(tmp_path / "source.hwpx")
    with zipfile.ZipFile(source) as archive:
        section = archive.read("Contents/section0.xml")
    section = section.replace(b"SOURCE-STORY-CANARY", source_fragment)
    mutated = tmp_path / "mutated.hwpx"
    story_edit._rewrite_zip(source.read_bytes(), mutated, "Contents/section0.xml", section)
    operation = _op(mutated)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(mutated, operation, output, receipt)
    assert excinfo.value.code == "unsupported_target_run"
    assert not output.exists() and not receipt.exists()

    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(operation), encoding="utf-8")
    result = _run_cli(mutated, ops, output, receipt)
    rendered = result.stdout + result.stderr
    assert result.returncode == 3
    assert "T-INNER" not in rendered
    assert "Traceback" not in rendered
    assert str(tmp_path) not in rendered
    assert not output.exists() and not receipt.exists()


@pytest.mark.parametrize(
    ("story_local", "story_role"),
    [("header", "header"), ("footer", "footer"), ("footNote", "footnote"), ("endNote", "endnote")],
)
def test_t80_matches_exact_owpml_note_locals(tmp_path: Path, story_local: str, story_role: str) -> None:
    source = _document(tmp_path / f"{story_role}.hwpx", story_local=story_local)
    selector = _selector(source, role=story_role)
    ops = tmp_path / f"{story_role}.json"
    ops.write_text(json.dumps(_op(source, selector=selector)), encoding="utf-8")
    output, receipt = tmp_path / f"{story_role}-edited.hwpx", tmp_path / f"{story_role}-receipt.json"
    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(output) as edited:
        payload = edited.read("Contents/section0.xml")
        assert b"REPLACED-STORY" in payload


def test_t80_matches_two_level_table_cell_story_ancestry_without_coordinates(tmp_path: Path) -> None:
    source = _nested_table_document(tmp_path / "nested.hwpx")
    graph = story_graph.inspect_story_graph(source)
    assert graph["status"] == "passed", graph
    story = next(story for member in graph["members"] for story in member.get("stories", []))
    assert story["address"].startswith("section[0]/container[1/0/0/2/1/0]/story[header,0]")
    selector = _selector(source)
    ops = tmp_path / "nested.json"
    ops.write_text(json.dumps(_op(source, selector=selector)), encoding="utf-8")
    output, receipt = tmp_path / "nested-edited.hwpx", tmp_path / "nested-receipt.json"
    result = _run_cli(source, ops, output, receipt)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rowAddr" not in receipt.read_text(encoding="utf-8")


def test_t80_uses_one_immutable_source_snapshot_under_path_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _document(tmp_path / "input.hwpx")
    original_bytes = source.read_bytes()
    swapped_bytes = original_bytes.replace(b"MAIN-BODY-CANARY", b"SWAPPED-BODY-CANARY")
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source)), encoding="utf-8")
    original_snapshot = story_edit._snapshot_graph

    def swap_path(snapshot: bytes):
        source.write_bytes(swapped_bytes)
        return original_snapshot(snapshot)

    monkeypatch.setattr(story_edit, "_snapshot_graph", swap_path)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, json.loads(ops.read_text(encoding="utf-8")), output, receipt)
    assert payload["status"] == "passed"
    with zipfile.ZipFile(output) as edited:
        section = edited.read("Contents/section0.xml")
        assert b"MAIN-BODY-CANARY" in section
        assert b"SWAPPED-BODY-CANARY" not in section


def test_t80_receipt_failure_publishes_neither_output_nor_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)

    def fail_receipt(_path: Path, _payload: dict[str, object]) -> None:
        raise story_edit.EditError("receipt_write")

    monkeypatch.setattr(story_edit, "_write_receipt", fail_receipt)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError):
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert not output.exists()
    assert not receipt.exists()


def test_t80_semantic_noop_copies_source_bytes_without_lineseg_removal(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", with_lineseg=True)
    before = source.read_bytes()
    operation = _op(source, replacement="SOURCE-STORY-CANARY")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed" and payload["changed"] is False
    assert output.read_bytes() == before
    assert b"linesegarray" in output.read_bytes()


def test_t80_multiple_text_nodes_in_one_run_refuse_without_outputs(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", multiple_text=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "unsupported_target_run"
    assert not output.exists() and not receipt.exists()


def test_t80_multi_text_run_plus_single_text_run_refuses_without_outputs(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", multiple_text=True, second_text_run=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "unsupported_target_run"
    assert not output.exists() and not receipt.exists()


def test_t80_run_ordinal_counts_only_direct_text_bearing_runs(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", leading_empty_run=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed"
    with zipfile.ZipFile(output) as edited:
        section = edited.read("Contents/section0.xml")
        assert b"REPLACED-STORY" in section


def test_t80_zero_text_run_refuses_explicitly(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", leading_empty_run=True, no_text=True)
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code in {"unsupported_target_run", "address_mismatch"}
    assert not output.exists() and not receipt.exists()


def test_t80_zero_seat_cli_is_closed_and_traceback_free(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", leading_empty_run=True, no_text=True)
    ops = tmp_path / "operation.json"
    ops.write_text(json.dumps(_op(source)), encoding="utf-8")
    result = _run_cli(source, ops, tmp_path / "edited.hwpx", tmp_path / "receipt.json")
    assert result.returncode == 3
    assert "Traceback" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


def test_t80_raw_carriage_return_replacement_refuses_without_outputs(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source, replacement="LINE\rBREAK")
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "replacement_cr"
    assert not output.exists() and not receipt.exists()


def test_t80_preserves_unrelated_zip_member_payloads_and_metadata_exactly(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    story_edit.apply_story_edit(source, operation, output, receipt)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
        assert original.namelist() == edited.namelist()
        target = "Contents/section0.xml"
        fields = (
            "filename", "date_time", "compress_type", "compresslevel", "comment", "extra",
            "create_system", "create_version", "extract_version", "flag_bits", "volume",
            "internal_attr", "external_attr",
        )
        for name in original.namelist():
            if name == target:
                continue
            left, right = original.getinfo(name), edited.getinfo(name)
            assert all(getattr(left, field, None) == getattr(right, field, None) for field in fields), name
            assert original.read(name) == edited.read(name), name


def test_t80_preserves_archive_comment_exactly(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx", archive_comment=b"ARCHIVE-COMMENT-CANARY")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    story_edit.apply_story_edit(source, operation, output, receipt)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
        assert edited.comment == original.comment == b"ARCHIVE-COMMENT-CANARY"


def _document_with_inter_record_gap(tmp_path: Path) -> Path:
    source = _document(tmp_path / "source.hwpx")
    raw = source.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        central_offset = int(archive.start_dir)
    gap = b"GAP-ORIGINAL"
    eocd = raw.rfind(b"PK\x05\x06")
    shifted = bytearray(raw[:central_offset] + gap + raw[central_offset:])
    struct.pack_into("<L", shifted, eocd + len(gap) + 16, central_offset + len(gap))
    target = tmp_path / "gapped.hwpx"
    target.write_bytes(shifted)
    return target


def _swap_local_records(path: Path, left_name: str, right_name: str) -> None:
    raw = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        central_start = int(archive.start_dir)
    bounds = [story_edit._local_bounds(raw, info) for info in infos]
    left = next(index for index, info in enumerate(infos) if info.filename == left_name)
    right = next(index for index, info in enumerate(infos) if info.filename == right_name)
    order = list(range(len(infos)))
    order[left], order[right] = order[right], order[left]
    prefix = raw[:bounds[0][0]]
    local_area = bytearray(prefix)
    new_starts: dict[int, int] = {}
    for index in order:
        new_starts[index] = len(local_area)
        local_area.extend(raw[bounds[index][0]:bounds[index][2]])
    local_area.extend(raw[bounds[-1][2]:central_start])
    central_cursor = central_start
    central = bytearray()
    for index, _info in enumerate(infos):
        fields = struct.unpack_from("<4s6H3L5H2L", raw, central_cursor)
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        record_end = central_cursor + 46 + name_len + extra_len + comment_len
        record = bytearray(raw[central_cursor:record_end])
        struct.pack_into("<L", record, 42, new_starts[index])
        central.extend(record)
        central_cursor = record_end
    eocd = raw.rfind(b"PK\x05\x06")
    eocd_record = bytearray(raw[eocd:])
    struct.pack_into("<L", eocd_record, 16, len(local_area))
    path.write_bytes(bytes(local_area) + bytes(central) + bytes(eocd_record))


@pytest.mark.parametrize("fault", ["gap", "comment", "eocd_offset"])
def test_t80_preservation_verifier_refuses_physical_envelope_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    if fault == "gap":
        source = _document_with_inter_record_gap(tmp_path)
    elif fault == "comment":
        source = _document(tmp_path / "input.hwpx", archive_comment=b"ARCHIVE-COMMENT")
    else:
        source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    original_rewrite = story_edit._rewrite_zip

    def corrupt_writer(source_bytes: bytes, stage_path: Path, target_name: str, target_payload: bytes) -> None:
        original_rewrite(source_bytes, stage_path, target_name, target_payload)
        raw = bytearray(stage_path.read_bytes())
        if fault == "gap":
            assert b"GAP-ORIGINAL" in raw
            raw[raw.index(b"GAP-ORIGINAL"):raw.index(b"GAP-ORIGINAL") + len(b"GAP-ORIGINAL")] = b"GAP-MUTATED"
        elif fault == "comment":
            assert b"ARCHIVE-COMMENT" in raw
            raw[raw.index(b"ARCHIVE-COMMENT"):raw.index(b"ARCHIVE-COMMENT") + len(b"ARCHIVE-COMMENT")] = b"ARCHIVE-CHANGED"
        else:
            eocd = raw.rfind(b"PK\x05\x06")
            central_offset = struct.unpack_from("<L", raw, eocd + 16)[0]
            struct.pack_into("<L", raw, eocd + 16, central_offset + 1)
        stage_path.write_bytes(raw)

    monkeypatch.setattr(story_edit, "_rewrite_zip", corrupt_writer)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError):
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert not output.exists() and not receipt.exists()


def test_t80_preservation_verifier_refuses_swapped_physical_local_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    original_rewrite = story_edit._rewrite_zip

    def corrupt_writer(source_bytes: bytes, stage_path: Path, target_name: str, target_payload: bytes) -> None:
        original_rewrite(source_bytes, stage_path, target_name, target_payload)
        _swap_local_records(stage_path, "META-INF/container.xml", "Contents/content.hpf")

    monkeypatch.setattr(story_edit, "_rewrite_zip", corrupt_writer)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError):
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert not output.exists() and not receipt.exists()


def test_t80_target_member_changes_only_selected_text_and_lineseg_spans(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    story_edit.apply_story_edit(source, operation, output, receipt)
    selector, _ = story_edit._validate_operation(operation)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as edited:
        before = original.read("Contents/section0.xml")
        after = edited.read("Contents/section0.xml")
    (start, end), line_spans = story_edit._scan_text_span(before, selector)
    assert not line_spans
    replacement = b"REPLACED-STORY"
    assert before[:start] == after[:start]
    assert before[end:] == after[start + len(replacement):]


@pytest.mark.parametrize("fault", ["body", "unrelated", "wrong_story"])
def test_t80_explicit_preservation_verifier_refuses_fault_injected_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    original_rewrite = story_edit._rewrite_zip

    def corrupt_writer(source_bytes: bytes, stage_path: Path, target_name: str, target_payload: bytes) -> None:
        original_rewrite(source_bytes, stage_path, target_name, target_payload)
        if fault == "unrelated":
            with zipfile.ZipFile(io.BytesIO(stage_path.read_bytes())) as archive:
                styles = archive.read("BinData/styles.bin")
            original_rewrite(
                stage_path.read_bytes(), stage_path, "BinData/styles.bin",
                styles.replace(b"STYLE-RESOURCE-CANARY", b"STYLE-ALTERED-CANARY"),
            )
            return
        altered = stage_path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(altered)) as archive:
            section = archive.read(target_name)
        marker = {
            "body": (b"MAIN-BODY-CANARY", b"ALTERED-BODY-CANARY"),
            "wrong_story": (b"REPLACED-STORY", b"WRONG-STORY-CANARY"),
        }[fault]
        altered_section = section.replace(*marker)
        original_rewrite(altered, stage_path, target_name, altered_section)

    monkeypatch.setattr(story_edit, "_rewrite_zip", corrupt_writer)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "preservation_failed"
    assert not output.exists() and not receipt.exists()


def test_t80_preservation_rejects_same_payload_different_valid_deflate_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _document(tmp_path / "input.hwpx", compression=zipfile.ZIP_DEFLATED)
    operation = _op(source)
    original_rewrite = story_edit._rewrite_zip
    original_compress = story_edit._compress

    def alternate_compress(info: zipfile.ZipInfo, payload: bytes) -> bytes:
        if info.compress_type != zipfile.ZIP_DEFLATED:
            return original_compress(info, payload)
        compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=-15,
                                       strategy=zlib.Z_FILTERED)
        return compressor.compress(payload) + compressor.flush()

    def corrupt_writer(source_bytes: bytes, stage_path: Path, target_name: str, target_payload: bytes) -> None:
        original_rewrite(source_bytes, stage_path, target_name, target_payload)
        monkeypatch.setattr(story_edit, "_compress", alternate_compress)
        try:
            # Keep payload and metadata valid while changing only the DEFLATE
            # representation; the preservation verifier must still refuse it.
            original_rewrite(stage_path.read_bytes(), stage_path, target_name, target_payload)
        finally:
            monkeypatch.setattr(story_edit, "_compress", original_compress)

    monkeypatch.setattr(story_edit, "_rewrite_zip", corrupt_writer)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "preservation_failed"
    assert not output.exists() and not receipt.exists()


def test_t81_deflate_fast_flag_uses_fast_level_one(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("section.xml")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits = 0x0004
    payload = (b"DEFLATE-FAST-CANARY" * 20)
    expected_compressor = zlib.compressobj(level=1, method=zlib.DEFLATED, wbits=-15)
    expected = expected_compressor.compress(payload) + expected_compressor.flush()
    assert story_edit._compress(info, payload) == expected


def test_t80_never_overwrites_preexisting_final_output(tmp_path: Path) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    output.write_bytes(b"PREEXISTING-OUTPUT")
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "output_exists"
    assert output.read_bytes() == b"PREEXISTING-OUTPUT"
    assert not receipt.exists()


def test_t80_staged_unlink_failure_does_not_turn_publication_into_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    original_unlink = Path.unlink

    def fail_staged_unlink(path: Path, missing_ok: bool = False) -> None:
        if path.name in {"artifact.hwpx", "receipt.json"} and path.parent.name.startswith(".story-edit-"):
            raise OSError("injected staging cleanup failure")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_staged_unlink)
    payload = story_edit.apply_story_edit(source, operation, output, receipt)
    assert payload["status"] == "passed"
    assert output.exists() and receipt.exists()


def test_t80_rollback_does_not_delete_swapped_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _document(tmp_path / "input.hwpx")
    operation = _op(source)
    output, receipt = tmp_path / "edited.hwpx", tmp_path / "receipt.json"
    original_publish = story_edit._publish_exclusive

    def publish_then_swap(staged: Path, final: Path) -> tuple[int, int]:
        identity = original_publish(staged, final)
        if final == output:
            final.unlink()
            final.write_bytes(b"ATTACKER-SWAPPED-FINAL")
        else:
            raise story_edit.EditError("receipt_publish")
        return identity

    monkeypatch.setattr(story_edit, "_publish_exclusive", publish_then_swap)
    with pytest.raises(story_edit.EditError) as excinfo:
        story_edit.apply_story_edit(source, operation, output, receipt)
    assert excinfo.value.code == "receipt_publish"
    assert output.read_bytes() == b"ATTACKER-SWAPPED-FINAL"
    assert not receipt.exists()
