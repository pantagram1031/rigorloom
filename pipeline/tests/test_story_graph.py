"""Adversarial regressions for the bounded T79 story-inventory contract."""
from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import story_graph  # noqa: E402


HP, HS, HC, OPF = (story_graph.PARAGRAPH_NS, story_graph.SECTION_NS,
                   story_graph.CORE_NS, story_graph.OPF_NS)
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
HP10 = "http://www.hancom.co.kr/hwpml/2016/paragraph"
MASTER = "http://www.hancom.co.kr/hwpml/2011/master-page"


def _hpf(items: str, spine: str | None = None, *, metadata: str | None = None,
         package_attrs: str = 'id="" unique-identifier="" version=""') -> str:
    spine = '<opf:itemref idref="section"/>' if spine is None else spine
    metadata = metadata or '<opf:metadata><opf:title/><opf:language>ko</opf:language><opf:meta name="creator" content="text"/></opf:metadata>'
    return f'''<opf:package xmlns:opf="{OPF}" {package_attrs}>{metadata}<opf:manifest>{items}</opf:manifest><opf:spine>{spine}</opf:spine></opf:package>'''


def _default_items(section_href: str = "Contents/section0.xml") -> str:
    return (f'<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            f'<opf:item id="section" href="{section_href}" media-type="application/xml"/>')


def _container(rootfiles: str | None = None) -> str:
    rootfiles = rootfiles if rootfiles is not None else '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
    return f'<ocf:container xmlns:ocf="{OCF}"><ocf:rootfiles>{rootfiles}</ocf:rootfiles></ocf:container>'


def _section(*, body: str = "body", children: str = "", paragraph_id: str = "") -> str:
    attr = f' id="{paragraph_id}"' if paragraph_id else ""
    return f'''<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}" xmlns:hc="{HC}">
      <hp:p{attr}><hp:run><hp:t>{body}</hp:t>{children}</hp:run></hp:p>
    </hs:sec>'''


def _control(local: str, attrs: str = "", body: str = "story") -> str:
    return (f'<hp:ctrl><hp:{local} {attrs}><hp:subList><hp:p><hp:run><hp:t>{body}</hp:t>'
            f'</hp:run></hp:p></hp:subList></hp:{local}></hp:ctrl>')


def _header(page_type: str = "BOTH", body: str = "story") -> str:
    return _control("header", f'applyPageType="{page_type}" id="CANARY-CONTROL-ID"', body)


def _note(kind: str = "footNote", inst: str = "note-1") -> str:
    return _control(kind, f'instId="{inst}"', "note-private")


def _table(*, duplicate: bool = False, nested: bool = False, pos: str = ' treatAsChar="1"') -> str:
    second = "0" if duplicate else "1"
    nested_xml = ""
    if nested:
        nested_xml = ("<hp:p><hp:run><hp:tbl><hp:pos treatAsChar=\"1\"/><hp:tr><hp:tc>"
                      "<hp:cellAddr rowAddr=\"0\" colAddr=\"0\"/><hp:subList/></hp:tc>"
                      "</hp:tr></hp:tbl></hp:run></hp:p>")
    return (f'<hp:tbl><hp:pos{pos}/><hp:tr>'
            f'<hp:tc><hp:cellAddr rowAddr="0" colAddr="0"/><hp:subList>{nested_xml}</hp:subList></hp:tc>'
            f'<hp:tc><hp:cellAddr rowAddr="0" colAddr="{second}"/><hp:subList/></hp:tc>'
            f'</hp:tr></hp:tbl>')


def _package(path: Path, section: str, *, hpf: str | None = None,
             section_href: str = "Contents/section0.xml", extra: list[tuple[str, str | bytes]] | None = None,
             mimetype: bytes | None = b"application/hwp+zip", container: str | None = None,
             include_container: bool = True) -> Path:
    hpf = hpf or _hpf(_default_items(section_href))
    extra_names = {name for name, _value in extra or []}
    with zipfile.ZipFile(path, "w") as archive:
        if mimetype is not None:
            archive.writestr("mimetype", mimetype)
        if include_container:
            archive.writestr("META-INF/container.xml", _container() if container is None else container)
        archive.writestr("Contents/content.hpf", hpf)
        if "Contents/header.xml" in hpf and "Contents/header.xml" not in extra_names:
            archive.writestr("Contents/header.xml", f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"/>')
        archive.writestr(section_href, section)
        for name, value in extra or []:
            archive.writestr(name, value)
    return path


def _roles(payload: dict[str, object]) -> set[str]:
    return {row["role"] for row in payload["unknown"]}  # type: ignore[index]


def test_private_contract_uses_only_opaque_member_ids_and_structural_addresses(tmp_path: Path) -> None:
    canary = "CANARY-BODY-author@example.invalid-https://secret.invalid/Contents/secret-name.xml"
    document = _package(
        tmp_path / "CANARY-input.hwpx", _section(body=canary, children=_header(body=canary)),
        section_href="Contents/CANARY-member-name.xml",
        hpf=_hpf(_default_items("Contents/CANARY-member-name.xml")),
    )
    payload = story_graph.inspect_story_graph(document)
    assert payload["status"] == "passed", payload
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in ("CANARY", "author@example", "secret.invalid", "member-name", str(tmp_path)):
        assert forbidden not in rendered
    assert all(set(row) >= {"member_id", "order", "role", "hash"} for row in payload["manifest"])
    assert all("member" not in row for row in payload["members"])
    assert all("CANARY" not in row["address"] for row in payload["unknown"])


def test_default_output_is_not_linkable_to_member_or_document_bytes(tmp_path: Path) -> None:
    left = story_graph.inspect_story_graph(_package(
        tmp_path / "left.hwpx", _section(body="CANARY-LEFT"), section_href="Contents/left-secret.xml",
        hpf=_hpf(_default_items("Contents/left-secret.xml")),
    ))
    right = story_graph.inspect_story_graph(_package(
        tmp_path / "right.hwpx", _section(body="CANARY-RIGHT"), section_href="Contents/right-secret.xml",
        hpf=_hpf(_default_items("Contents/right-secret.xml")),
    ))
    assert left == right
    assert left["manifest"][0]["member_id"] == "member-0001"


@pytest.mark.parametrize("mimetype, container, include_container", [
    (None, _container(), True),
    (b"application/not-hwpx", _container(), True),
    (b"application/hwp+zip\n", _container(), True),
    (b"application/hwp+zip", None, False),
    (b"application/hwp+zip", _container('<ocf:rootfile full-path="Contents/other.hpf" media-type="application/hwpml-package+xml"/>'), True),
    (b"application/hwp+zip", _container('<ocf:rootfile full-path="Contents/content.hpf" media-type="text/plain"/>'), True),
    (b"application/hwp+zip", _container('<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'), True),
])
def test_ocf_mimetype_and_hpf_rootfile_contract_refuses(
    tmp_path: Path, mimetype: bytes | None, container: str | None, include_container: bool,
) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "ocf.hwpx", _section(), mimetype=mimetype, container=container, include_container=include_container))
    assert payload["status"] == "refused"


@pytest.mark.parametrize("first_name, compression, extra", [
    ("not-mimetype", zipfile.ZIP_STORED, b""),
    ("mimetype", zipfile.ZIP_DEFLATED, b""),
    ("mimetype", zipfile.ZIP_STORED, b"\x01\x00\x00\x00"),
])
def test_physical_mimetype_entry_contract_refuses(
    tmp_path: Path, first_name: str, compression: int, extra: bytes,
) -> None:
    path = tmp_path / "physical.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo(first_name)
        info.compress_type, info.extra = compression, extra
        archive.writestr(info, b"application/hwp+zip")
        if first_name != "mimetype":
            archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", _hpf(_default_items()))
        archive.writestr("Contents/header.xml", f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"/>')
        archive.writestr("Contents/section0.xml", _section())
    assert story_graph.inspect_story_graph(path)["status"] == "refused"


def test_local_mimetype_header_is_checked_not_just_central_directory(tmp_path: Path) -> None:
    path = _package(tmp_path / "local-header.hwpx", _section())
    raw = bytearray(path.read_bytes())
    assert raw[:4] == b"PK\x03\x04"
    struct.pack_into("<H", raw, 8, zipfile.ZIP_DEFLATED)  # central directory remains STORED
    path.write_bytes(raw)
    assert story_graph.inspect_story_graph(path)["status"] == "refused"


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_non_deflate_zip_members_refuse(tmp_path: Path, method: int) -> None:
    path = _package(tmp_path / f"method-{method}.hwpx", _section())
    with zipfile.ZipFile(path, "a", compression=method) as archive:
        archive.writestr("BinData/unsupported", b"x")
    assert story_graph.inspect_story_graph(path)["status"] == "refused"


def test_ocf_rootfiles_must_be_empty_safe_unique_and_present(tmp_path: Path) -> None:
    bad = _container('<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"><ocf:rootfile/></ocf:rootfile>')
    assert story_graph.inspect_story_graph(_package(tmp_path / "nested-rootfile.hwpx", _section(), container=bad))["status"] == "refused"
    missing_aux = _container(
        '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
        '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
    )
    assert story_graph.inspect_story_graph(_package(tmp_path / "missing-aux.hwpx", _section(), container=missing_aux))["status"] == "refused"


@pytest.mark.parametrize("container", [
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" extra="x"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>',
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">mixed<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>',
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container"><ocf:rootfiles>mixed<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>',
])
def test_ocf_container_grammar_rejects_unknown_attributes_and_mixed_text(tmp_path: Path, container: str) -> None:
    assert story_graph.inspect_story_graph(_package(tmp_path / "ocf-grammar.hwpx", _section(), container=container))["status"] == "refused"


def test_opf_order_uses_actual_section_roots_not_filename_regex(tmp_path: Path) -> None:
    first, second = "Contents/not-a-section.xml", "Contents/another-name.xml"
    hpf = _hpf(
        f'<opf:item id="a" href="{first}" media-type="application/xml"/>'
        f'<opf:item id="b" href="{second}" media-type="application/xml"/>',
        '<opf:itemref idref="b"/><opf:itemref idref="a"/>',
    )
    path = tmp_path / "ordered.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", hpf)
        archive.writestr(first, _section(body="first"))
        archive.writestr(second, _section(body="second"))
    payload = story_graph.inspect_story_graph(path)
    assert payload["status"] == "passed", payload
    sections = [row for row in payload["members"] if row["role"] == "section"]
    assert [row["topology"]["spine_order"] for row in sections] == [1, 0]


def test_spine_must_be_nonempty_and_cover_every_actual_section_once(tmp_path: Path) -> None:
    no_spine = story_graph.inspect_story_graph(_package(
        tmp_path / "no-spine.hwpx", _section(), hpf=_hpf(_default_items(), ""),
    ))
    assert no_spine["status"] == "refused"

    first, second = "Contents/one.xml", "Contents/two.xml"
    items = (f'<opf:item id="one" href="{first}" media-type="application/xml"/>'
             f'<opf:item id="two" href="{second}" media-type="application/xml"/>')
    only_one = story_graph.inspect_story_graph(_package(
        tmp_path / "missing-section.hwpx", _section(), section_href=first,
        hpf=_hpf(items, '<opf:itemref idref="one"/>'), extra=[(second, _section())],
    ))
    assert only_one["status"] == "refused"


def test_every_local_header_is_reconciled_and_zip_envelope_is_ascii_only(tmp_path: Path) -> None:
    mismatch = _package(tmp_path / "local-central-mismatch.hwpx", _section())
    with zipfile.ZipFile(mismatch) as archive:
        offset = archive.getinfo("Contents/header.xml").header_offset
    raw = bytearray(mismatch.read_bytes())
    raw[offset + 14] ^= 1  # local CRC no longer matches the central directory
    mismatch.write_bytes(raw)
    assert story_graph.inspect_story_graph(mismatch)["status"] == "refused"

    non_ascii = _package(tmp_path / "non-ascii-member.hwpx", _section())
    with zipfile.ZipFile(non_ascii, "a") as archive:
        archive.writestr("BinData/é.bin", b"x")
    assert story_graph.inspect_story_graph(non_ascii)["status"] == "refused"

    extra = _package(tmp_path / "member-extra.hwpx", _section())
    with zipfile.ZipFile(extra, "a") as archive:
        info = zipfile.ZipInfo("BinData/extra.bin")
        info.extra = b"\x01\x00\x00\x00"
        archive.writestr(info, b"x")
    assert story_graph.inspect_story_graph(extra)["status"] == "refused"


@pytest.mark.parametrize("field_offset", [4, 10, 12])
def test_every_local_header_version_and_dos_time_fields_match_central(tmp_path: Path, field_offset: int) -> None:
    document = _package(tmp_path / f"local-field-{field_offset}.hwpx", _section())
    with zipfile.ZipFile(document) as archive:
        offset = archive.getinfo("Contents/header.xml").header_offset
    raw = bytearray(document.read_bytes())
    previous = struct.unpack_from("<H", raw, offset + field_offset)[0]
    struct.pack_into("<H", raw, offset + field_offset, previous ^ 1)
    document.write_bytes(raw)
    assert story_graph.inspect_story_graph(document)["status"] == "refused"


def test_nested_story_owners_are_not_inventoried(tmp_path: Path) -> None:
    nested_story = (
        '<hp:ctrl><hp:header id="outer" applyPageType="BOTH"><hp:subList><hp:p><hp:run>'
        '<hp:ctrl><hp:footNote instId="inner"><hp:subList><hp:p><hp:run/></hp:p>'
        '</hp:subList></hp:footNote></hp:ctrl></hp:run></hp:p></hp:subList></hp:header></hp:ctrl>'
    )
    payload = story_graph.inspect_story_graph(_package(tmp_path / "nested-story.hwpx", _section(children=nested_story)))
    assert payload["status"] == "refused"
    assert "unsupported_nested_story_owner" in _roles(payload)

    nested_table_story = (
        '<hp:tbl><hp:pos treatAsChar="1"/><hp:tr><hp:tc><hp:cellAddr rowAddr="0" colAddr="0"/>'
        '<hp:subList><hp:p><hp:run><hp:ctrl><hp:header id="table" applyPageType="BOTH">'
        '<hp:subList><hp:p><hp:run/></hp:p></hp:subList></hp:header></hp:ctrl></hp:run></hp:p>'
        '</hp:subList></hp:tc></hp:tr></hp:tbl>'
    )
    table_payload = story_graph.inspect_story_graph(_package(tmp_path / "table-story.hwpx", _section(children=nested_table_story)))
    assert table_payload["status"] == "passed", table_payload
    story = table_payload["members"][1]["stories"][0]
    assert story["container_ancestry"] == [{"depth": 1, "table": 0, "cell": 0}]
    assert "/container[1/0/0]/" in story["address"]

    no_cell_scope = nested_table_story.replace('<hp:cellAddr rowAddr="0" colAddr="0"/>', "")
    invalid = story_graph.inspect_story_graph(_package(tmp_path / "table-story-no-cell.hwpx", _section(children=no_cell_scope)))
    assert "unsupported_nested_story_owner" in _roles(invalid)


def test_table_story_ancestry_is_coordinate_private_and_isomorphic(tmp_path: Path) -> None:
    def table_header(row: str, col: str) -> str:
        return (
            '<hp:tbl><hp:pos treatAsChar="1"/><hp:tr><hp:tc>'
            f'<hp:cellAddr rowAddr="{row}" colAddr="{col}"/><hp:subList><hp:p><hp:run><hp:ctrl>'
            '<hp:header id="private-control" applyPageType="BOTH"><hp:subList><hp:p><hp:run/>'
            '</hp:p></hp:subList></hp:header></hp:ctrl></hp:run></hp:p></hp:subList>'
            '</hp:tc></hp:tr></hp:tbl>'
        )

    first = story_graph.inspect_story_graph(_package(
        tmp_path / "rrn-coordinates.hwpx", _section(children=table_header("9901011234567", "01012345678")),
    ))
    second = story_graph.inspect_story_graph(_package(
        tmp_path / "renumbered-coordinates.hwpx", _section(children=table_header("42", "77")),
    ))
    assert first["status"] == second["status"] == "passed"
    assert first == second
    rendered = json.dumps(first, ensure_ascii=False)
    assert "9901011234567" not in rendered and "01012345678" not in rendered
    story = first["members"][1]["stories"][0]
    assert story["container_ancestry"] == [{"depth": 1, "table": 0, "cell": 0}]


@pytest.mark.parametrize("kind", ["settings", "binary"])
def test_spine_is_closed_to_definition_and_section_roles(tmp_path: Path, kind: str) -> None:
    if kind == "settings":
        item = '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
        extra = [("settings.xml", f'<ha:HWPApplicationSetting xmlns:ha="{story_graph.APP_NS}"/>')]
    else:
        item = '<opf:item id="image" href="BinData/image.png" media-type="image/png"/>'
        extra = [("BinData/image.png", b"png")]
    hpf = _hpf(
        _default_items() + item,
        '<opf:itemref idref="header"/><opf:itemref idref="section"/>'
        + ('<opf:itemref idref="settings"/>' if kind == "settings" else '<opf:itemref idref="image"/>'),
    )
    assert story_graph.inspect_story_graph(_package(tmp_path / f"spine-{kind}.hwpx", _section(), hpf=hpf, extra=extra))["status"] == "refused"


@pytest.mark.parametrize("hpf", [
    _hpf(_default_items(), package_attrs='id="" unique-identifier="" version="" extra="x"'),
    _hpf(_default_items(), metadata='<opf:metadata><x:story xmlns:x="urn:foreign"/></opf:metadata>'),
    _hpf(_default_items()).replace('</opf:metadata><opf:manifest>', '</opf:metadata><opf:spine><opf:itemref idref="section"/></opf:spine><opf:manifest>'),
    _hpf(_default_items(), '<opf:itemref idref="section" linear="maybe"/>'),
    _hpf(_default_items(), '<opf:itemref id="section" idref="section" linear="yes"/>'),
])
def test_opf_package_metadata_order_and_itemref_attributes_are_closed(tmp_path: Path, hpf: str) -> None:
    assert story_graph.inspect_story_graph(_package(tmp_path / "closed-opf.hwpx", _section(), hpf=hpf))["status"] == "refused"


def test_opf_optional_itemref_id_is_nonempty_unique_and_collision_safe(tmp_path: Path) -> None:
    hpf = _hpf(_default_items(), '<opf:itemref id="section-spine" idref="section" linear="no"/>')
    assert story_graph.inspect_story_graph(_package(tmp_path / "itemref-id.hwpx", _section(), hpf=hpf))["status"] == "passed"


def test_opf_proven_embedded_binary_flag_is_closed_but_accepted(tmp_path: Path) -> None:
    hpf = _hpf(
        _default_items()
        + '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>'
    )
    payload = story_graph.inspect_story_graph(_package(
        tmp_path / "embedded.hwpx", _section(), hpf=hpf, extra=[("BinData/image1.png", b"png")],
    ))
    assert payload["status"] == "passed", payload


@pytest.mark.parametrize("hpf, extra", [
    (_hpf('<opf:item id="a" href="Contents/section0.xml" media-type="application/xml"/>', metadata='<opf:metadata><opf:item id="x" href="x.xml" media-type="application/xml"/></opf:metadata>'), []),
    (_hpf(_default_items(), '<opf:itemref idref="header"/><opf:itemref idref="header"/>'), []),
    (_hpf('<opf:item id="a" href="Contents/section0.xml" media-type="text/plain"/>'), []),
    (_hpf('<opf:item id="a" href="Contents/../section0.xml" media-type="application/xml"/>'), []),
    (_hpf(_default_items()), [("Contents/future.xml", f'<hp:masterPage xmlns:hp="{HP}"><hp:subList/></hp:masterPage>')]),
])
def test_opf_package_grammar_alias_media_and_coverage_refuse(
    tmp_path: Path, hpf: str, extra: list[tuple[str, str]],
) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "bad.hwpx", _section(), hpf=hpf, extra=extra))
    assert payload["status"] == "refused"
    assert payload["unknown"][0]["role"] == "unreadable_package"


@pytest.mark.parametrize("items, spine", [
    ('<opf:item id="section" href="Contents/section0.xml" media-type="application/xml">mixed</opf:item>', ""),
    ('<opf:item id="section" href="Contents/section0.xml" media-type="application/xml"><opf:item/></opf:item>', ""),
    (_default_items(), '<opf:itemref idref="section">mixed</opf:itemref>'),
    (_default_items(), '<opf:itemref idref="section"><opf:itemref idref="section"/></opf:itemref>'),
])
def test_opf_item_and_itemref_are_empty(tmp_path: Path, items: str, spine: str) -> None:
    assert story_graph.inspect_story_graph(_package(tmp_path / "opf-empty.hwpx", _section(), hpf=_hpf(items, spine)))["status"] == "refused"


def test_declared_future_story_resource_and_spine_omission_refuse(tmp_path: Path) -> None:
    future = "Contents/future.xml"
    hpf = _hpf(
        _default_items() + f'<opf:item id="future" href="{future}" media-type="application/xml"/>',
        '<opf:itemref idref="header"/><opf:itemref idref="section"/>',
    )
    payload = story_graph.inspect_story_graph(_package(
        tmp_path / "future.hwpx", _section(), hpf=hpf,
        extra=[(future, f'<hp:masterPage xmlns:hp="{HP}"><hp:subList/></hp:masterPage>')],
    ))
    assert payload["status"] == "refused"
    assert "unsupported_story_resource" in _roles(payload)

    omission = story_graph.inspect_story_graph(_package(
        tmp_path / "spine-omission.hwpx", _section(),
        hpf=_hpf(_default_items(), '<opf:itemref idref="header"/>'),
    ))
    assert omission["status"] == "refused"


@pytest.mark.parametrize("namespace, local", [(HP10, "p"), (MASTER, "masterPage")])
def test_declared_paragraph10_and_master_page_roots_refuse(
    tmp_path: Path, namespace: str, local: str,
) -> None:
    future = "Contents/future.xml"
    hpf = _hpf(_default_items() + f'<opf:item id="future" href="{future}" media-type="application/xml"/>')
    payload = story_graph.inspect_story_graph(_package(
        tmp_path / "future-root.hwpx", _section(), hpf=hpf,
        extra=[(future, f'<x:{local} xmlns:x="{namespace}"/>')],
    ))
    assert payload["status"] == "refused"
    assert "unsupported_story_resource" in _roles(payload)


@pytest.mark.parametrize("member, content", [
    ("Contents/header.xml", '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"><x:future xmlns:x="urn:foreign"/></hh:head>'),
    ("Contents/header.xml", f'<hh:head xmlns:hh="{story_graph.HEAD_NS}" xmlns:hp="{HP}"><hp:p><hp:run/></hp:p></hh:head>'),
    ("settings.xml", '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"><x:future xmlns:x="urn:foreign"/></ha:HWPApplicationSetting>'),
])
def test_declared_definition_roots_reject_foreign_and_story_subtrees(
    tmp_path: Path, member: str, content: str,
) -> None:
    items = _default_items() + '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
    extra = [("settings.xml", '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"/>')]
    if member == "Contents/header.xml":
        extra.append((member, content))
    else:
        extra = [(member, content)]
    payload = story_graph.inspect_story_graph(_package(tmp_path / "declared-xml.hwpx", _section(), hpf=_hpf(items), extra=extra))
    assert payload["status"] == "refused"


@pytest.mark.parametrize("header", [
    f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"><hh:head/></hh:head>',
    f'<hh:head xmlns:hh="{story_graph.HEAD_NS}"><hh:bold/></hh:head>',
])
def test_definition_parent_pairs_are_closed(tmp_path: Path, header: str) -> None:
    assert story_graph.inspect_story_graph(_package(
        tmp_path / "header-parent.hwpx", _section(), extra=[("Contents/header.xml", header)],
    ))["status"] == "refused"


def test_section_core_vocabulary_is_closed_and_story_hashes_are_distinct(tmp_path: Path) -> None:
    bad = story_graph.inspect_story_graph(_package(
        tmp_path / "future-core.hwpx", _section(children='<hc:future/>'),
    ))
    assert bad["status"] == "refused"
    assert "unknown_xml_element" in _roles(bad)

    first, second = "Contents/one.xml", "Contents/two.xml"
    hpf = _hpf(
        f'<opf:item id="a" href="{first}" media-type="application/xml"/>'
        f'<opf:item id="b" href="{second}" media-type="application/xml"/>',
        '<opf:itemref idref="a"/><opf:itemref idref="b"/>',
    )
    path = tmp_path / "two-sections.hwpx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", hpf)
        archive.writestr(first, _section(children=_header()))
        archive.writestr(second, _section(children=_header()))
    payload = story_graph.inspect_story_graph(path)
    stories = [member["stories"][0] for member in payload["members"] if member["role"] == "section"]
    assert payload["status"] == "passed"
    assert stories[0]["hash"] != stories[1]["hash"]


def test_core_img_parent_pair_is_closed(tmp_path: Path) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "core-parent.hwpx", _section(children='<hc:img/>')))
    assert payload["status"] == "refused"
    assert "invalid_xml_parent" in _roles(payload)


def test_nested_section_and_header_identity_scope_refuse(tmp_path: Path) -> None:
    nested = f'<hs:sec xmlns:hs="{HS}"><hp:p xmlns:hp="{HP}"><hp:run/></hp:p></hs:sec>'
    nested_payload = story_graph.inspect_story_graph(_package(tmp_path / "nested-sec.hwpx", _section(children=nested)))
    assert nested_payload["status"] == "refused"
    assert "nested_section" in _roles(nested_payload)

    missing = story_graph.inspect_story_graph(_package(
        tmp_path / "header-missing.hwpx", _section(children=_control("header", 'applyPageType="BOTH"')),
    ))
    assert "missing_header_footer_id" in _roles(missing)
    duplicate = story_graph.inspect_story_graph(_package(
        tmp_path / "header-duplicate.hwpx", _section(children=_control("header", 'id="same" applyPageType="BOTH"') + _control("header", 'id="same" applyPageType="EVEN"')),
    ))
    assert "duplicate_header_footer_id" in _roles(duplicate)
    separate_types = story_graph.inspect_story_graph(_package(
        tmp_path / "header-footer-scope.hwpx",
        _section(children=_control("header", 'id="same" applyPageType="BOTH"') + _control("footer", 'id="same" applyPageType="BOTH"')),
    ))
    assert separate_types["status"] == "passed", separate_types


@pytest.mark.parametrize("children, role", [
    ('<hp:tbl><hp:pos treatAsChar="1"/><hp:pos treatAsChar="1"/></hp:tbl>', "invalid_object_position"),
    ('<hp:tbl/>', "invalid_object_position"),
    ('<hp:pic><x:pos xmlns:x="urn:foreign" treatAsChar="1"/></hp:pic>', "invalid_object_position"),
    ('<hp:tbl><hp:pos treatAsChar="1"/><hp:tr><hp:tc><hp:cellAddr rowAddr="-1" colAddr="0"/><hp:subList/></hp:tc></hp:tr></hp:tbl>', "invalid_cell_address"),
])
def test_object_positions_and_nonnegative_cells_refuse(tmp_path: Path, children: str, role: str) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "object.hwpx", _section(children=children)))
    assert payload["status"] == "refused"
    assert role in _roles(payload)


@pytest.mark.parametrize("children, expected", [
    (f'<hp:header xmlns:hp="{HP}" applyPageType="BOTH"><hp:subList/></hp:header>', "invalid_xml_parent"),
    ('<x:header xmlns:x="urn:foreign"/>', "foreign_namespace"),
    ('<hp:ctrl><hp:futureOwner><hp:subList/></hp:futureOwner></hp:ctrl>', "unknown_sublist_owner"),
    ('<hp:ctrl><hp:header applyPageType="BOTH"><hp:subList><hp:run/></hp:subList></hp:header></hp:ctrl>', "invalid_xml_parent"),
    ('<hp:ctrl><hp:tbl/></hp:ctrl>', "invalid_xml_parent"),
    ('<hp:cellAddr rowAddr="0" colAddr="0"/>', "invalid_xml_parent"),
])
def test_section_grammar_rejects_transplants_foreign_and_unknown_owners(
    tmp_path: Path, children: str, expected: str,
) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "bad-grammar.hwpx", _section(children=children)))
    assert payload["status"] == "refused"
    assert expected in _roles(payload)


def test_supported_controls_tables_and_nonidentity_paragraph_sentinels_pass(tmp_path: Path) -> None:
    nested = _table(nested=True)
    children = _header("BOTH") + _note("footNote", "fn-1") + nested
    payload = story_graph.inspect_story_graph(_package(tmp_path / "good.hwpx", _section(children=children, paragraph_id="0")))
    assert payload["status"] == "passed", payload
    assert payload["counts"]["headers"] == 1
    assert payload["counts"]["footnotes"] == 1
    assert payload["counts"]["tables"] == 2
    sentinel = story_graph.inspect_story_graph(_package(tmp_path / "sentinel.hwpx", _section(paragraph_id="2147483648")))
    assert sentinel["status"] == "passed", sentinel


@pytest.mark.parametrize("children, expected", [
    (_header("FIRST"), "invalid_apply_page_type"),
    (_note("footNote", "") , "missing_note_instance"),
    (_note("footNote", "same") + _note("endNote", "same"), "duplicate_note_instance"),
    (_table(duplicate=True), "duplicate_cell_address"),
    (_table(pos=' treatAsChar="maybe"'), "invalid_treat_as_char"),
    ('<hp:ctrl><hp:fieldBegin id="private-field"/></hp:ctrl>', "unsupported_field"),
    ('<hp:ctrl><hp:hiddenComment/></hp:ctrl>', "unsupported_hidden_comment"),
    ('<hp:ctrl><hp:drawText/></hp:ctrl>', "unsupported_draw_text"),
    ('<hp:ctrl><hp:caption/></hp:ctrl>', "unsupported_caption"),
    ('<hp:ctrl><hp:masterPage/></hp:ctrl>', "unsupported_master_page"),
])
def test_values_cardinality_identity_and_explicit_unsupported_scope_refuse(
    tmp_path: Path, children: str, expected: str,
) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "refused.hwpx", _section(children=children)))
    assert payload["status"] == "refused"
    assert expected in _roles(payload)


def test_nested_table_cell_scopes_are_independent(tmp_path: Path) -> None:
    payload = story_graph.inspect_story_graph(_package(tmp_path / "nested.hwpx", _section(children=_table(nested=True))))
    assert payload["status"] == "passed", payload
    tables = payload["members"][1]["topology"]["tables"]
    assert len(tables) == 2
    assert tables[1]["topology"]["depth"] == 2
    assert payload["counts"]["nested_table_max_depth"] == 2


def test_member_count_ratio_and_deep_xml_refuse_without_traceback(tmp_path: Path) -> None:
    many = tmp_path / "many.hwpx"
    with zipfile.ZipFile(many, "w") as archive:
        for index in range(story_graph.MAX_MEMBERS + 1):
            archive.writestr(f"x{index}", b"x")
    started = time.monotonic()
    assert story_graph.inspect_story_graph(many)["status"] == "refused"
    assert time.monotonic() - started < 5

    ratio = tmp_path / "ratio.hwpx"
    with zipfile.ZipFile(ratio, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/content.hpf", b"x" * (2 * 1024 * 1024))
    assert story_graph.inspect_story_graph(ratio)["status"] == "refused"

    deep = "<hp:p xmlns:hp=\"%s\">" % HP + "<hp:p>" * 1200 + "</hp:p>" * 1200 + "</hp:p>"
    payload = story_graph.inspect_story_graph(_package(tmp_path / "deep.hwpx", deep))
    assert payload["status"] == "refused"
    assert payload["unknown"][0]["role"] == "unreadable_package"
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "story_graph.py"), str(tmp_path / "deep.hwpx")],
        text=True, capture_output=True, check=False, timeout=20,
    )
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["status"] == "refused"
    assert "Traceback" not in completed.stderr


def test_zip_member_bounds_refuse_before_any_local_header_validator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "too-many-before-headers.hwpx"
    with zipfile.ZipFile(document, "w") as archive:
        for index in range(story_graph.MAX_MEMBERS + 1):
            archive.writestr(f"member-{index}", b"x")
    calls: list[str] = []
    monkeypatch.setattr(story_graph, "_validate_local_mimetype", lambda _path: calls.append("mimetype"))
    monkeypatch.setattr(story_graph, "_validate_local_headers", lambda _path, _infos: calls.append("headers"))
    assert story_graph.inspect_story_graph(document)["status"] == "refused"
    assert calls == []


def test_opf_known_root_attributes_accept_nonempty_private_values(tmp_path: Path) -> None:
    hpf = _hpf(_default_items(), package_attrs='id="opaque-package" unique-identifier="opaque-uid" version="1.0"')
    payload = story_graph.inspect_story_graph(_package(tmp_path / "opf-root-values.hwpx", _section(), hpf=hpf))
    assert payload["status"] == "passed"
    assert "opaque-" not in json.dumps(payload, ensure_ascii=False)


def test_zip_and_xml_aggregate_limits_have_direct_regressions(tmp_path: Path) -> None:
    def info(name: str, compressed: int, uncompressed: int) -> zipfile.ZipInfo:
        value = zipfile.ZipInfo(name)
        value.compress_size, value.file_size = compressed, uncompressed
        return value

    class FakeArchive:
        def __init__(self, infos: list[zipfile.ZipInfo]) -> None:
            self._infos = infos

        def infolist(self) -> list[zipfile.ZipInfo]:
            return self._infos

    with pytest.raises(story_graph.GraphError):
        story_graph._zip_members(FakeArchive([info("a", story_graph.MAX_COMPRESSED_BYTES + 1, 1)]))
    with pytest.raises(story_graph.GraphError):
        story_graph._zip_members(FakeArchive([info("a", 1, story_graph.MAX_UNCOMPRESSED_BYTES + 1)]))

    oversized = _package(tmp_path / "xml-bytes.hwpx", "x" * (story_graph.MAX_XML_BYTES + 1))
    assert story_graph.inspect_story_graph(oversized)["status"] == "refused"
    nodes = "<hp:p xmlns:hp=\"%s\">" % HP + "<hp:run/>" * (story_graph.MAX_XML_NODES + 1) + "</hp:p>"
    too_many = _package(tmp_path / "xml-nodes.hwpx", nodes)
    assert story_graph.inspect_story_graph(too_many)["status"] == "refused"


def test_all_public_corpus_files_have_declared_matrix_and_no_text_output() -> None:
    root = Path(__file__).parents[2] / "tests" / "corpus" / "forms"
    files = sorted(root.rglob("*.hwpx"))
    assert len(files) == 12
    matrix = {path.name: story_graph.inspect_story_graph(path) for path in files}
    expected_refusals = {
        "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx": {"unsupported_field", "unsupported_draw_text"},
        "moel-pyojun-geunrogyeyakseo-2013.hwpx": {"unsupported_field"},
    }
    assert {name for name, result in matrix.items() if result["status"] == "refused"} == set(expected_refusals)
    for name, result in matrix.items():
        roles = _roles(result)
        if name in expected_refusals:
            assert roles == expected_refusals[name]
        else:
            assert result["status"] == "passed", (name, roles)
        rendered = json.dumps(result, ensure_ascii=False).lower()
        assert "lastsaveby" not in rendered and "contents/section" not in rendered


def test_real_table_cell_header_has_closed_container_ancestry_without_text_output() -> None:
    fixture = next((Path(__file__).parents[2] / "tests" / "corpus" / "forms").rglob(
        "jeongbo-gonggae-cheongguseo.hwpx",
    ))
    first = story_graph.inspect_story_graph(fixture)
    second = story_graph.inspect_story_graph(fixture)
    assert first == second and first["status"] == "passed"
    stories = [story for member in first["members"] if member["role"] == "section" for story in member["stories"]]
    table_header = next(story for story in stories if story["role"] == "header" and "container_ancestry" in story)
    assert table_header["container_ancestry"]
    assert "/container[" in table_header["address"]
    assert "/story[header," in table_header["address"]
    assert "Contents/" not in json.dumps(table_header, ensure_ascii=False)


def test_cli_full_stream_is_private_and_has_only_0_2_3_contract(tmp_path: Path) -> None:
    canary = "CANARY-URL-https://private.invalid/author@example.invalid"
    document = _package(tmp_path / "CANARY-file.hwpx", _section(body=canary))
    command = [sys.executable, str(SCRIPTS / "story_graph.py"), str(document)]
    passed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=20)
    assert passed.returncode == 0
    assert json.loads(passed.stdout)["status"] == "passed"
    assert canary not in passed.stdout + passed.stderr
    assert str(document) not in passed.stdout + passed.stderr

    refused_doc = _package(tmp_path / "refused.hwpx", _section(children='<hp:ctrl><hp:caption/></hp:ctrl>'))
    refused = subprocess.run([*command[:-1], str(refused_doc)], text=True, capture_output=True, check=False, timeout=20)
    assert refused.returncode == 3
    assert json.loads(refused.stdout)["status"] == "refused"
    assert canary not in refused.stdout + refused.stderr

    usage = subprocess.run([*command, "--bad", "CANARY-ARGUMENT"], text=True, capture_output=True, check=False, timeout=20)
    assert usage.returncode == 2
    assert "CANARY" not in usage.stdout + usage.stderr

    out_error = subprocess.run(
        [*command, "--out", str(tmp_path / "CANARY-missing-parent" / "graph.json")],
        text=True, capture_output=True, check=False, timeout=20,
    )
    assert out_error.returncode == 2
    assert "CANARY" not in out_error.stdout + out_error.stderr
