"""Synthetic T88 bounded content/object agreement contract tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hwp_semantic_oracle as oracle  # noqa: E402
import hwp_diagnostic_candidate as rhwp  # noqa: E402
import hwp_java_diagnostic_candidate as java  # noqa: E402
from test_hwp_ingress import _hwpx  # noqa: E402


RUN_ID = "abcdef0123456789abcdef0123456789"
APPROVED_RHWP = "e38215daddf63b284cbe05322541b44f65efd727ce7f50b9b4ffd94930e7ab72"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
PARAGRAPH_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
OPF_NS = "http://www.idpf.org/2007/opf/"
OCF_NS = "urn:oasis:names:tc:opendocument:xmlns:container"


def _source() -> dict:
    return {
        "format": "hwp", "version": "5.0.3.2", "bytes": 123,
        "sha256": "1" * 64, "compressed": True, "security_flags": [],
    }


def _story_hwpx(path: Path, text: str = "SYNTHETIC") -> Path:
    """Small namespace-correct story-graph fixture for verifier snapshots."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("mimetype", b"application/hwp+zip")
        z.writestr("META-INF/container.xml", (
            f'<ocf:container xmlns:ocf="{OCF_NS}"><ocf:rootfiles>'
            '<ocf:rootfile full-path="Contents/content.hpf" '
            'media-type="application/hwpml-package+xml"/>'
            "</ocf:rootfiles></ocf:container>"))
        z.writestr("Contents/content.hpf", (
            f'<opf:package xmlns:opf="{OPF_NS}" id="pkg" '
            'unique-identifier="uid" version="3.0">'
            '<opf:metadata><opf:title>title</opf:title><opf:language>ko</opf:language>'
            '</opf:metadata><opf:manifest><opf:item id="section0" '
            'href="Contents/section0.xml" media-type="application/xml"/></opf:manifest>'
            '<opf:spine><opf:itemref idref="section0"/></opf:spine></opf:package>'))
        z.writestr("Contents/section0.xml", (
            f'<hp:sec xmlns:hp="{SECTION_NS}" xmlns:ha="{PARAGRAPH_NS}">'
            f'<ha:p><ha:run><ha:t>{text}</ha:t></ha:run></ha:p></hp:sec>'))
    return path


def _rewrite_member(path: Path, name: str, data: bytes) -> None:
    with zipfile.ZipFile(path) as source:
        members = {member: source.read(member) for member in source.namelist()}
    members[name] = data
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as output:
        for member, value in members.items():
            output.writestr(member, value)


def _two_section_hwpx(path: Path, *, reverse: bool = False) -> Path:
    order = ("section1", "section0") if reverse else ("section0", "section1")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("mimetype", b"application/hwp+zip")
        z.writestr("META-INF/container.xml", (
            f'<ocf:container xmlns:ocf="{OCF_NS}"><ocf:rootfiles>'
            '<ocf:rootfile full-path="Contents/content.hpf" '
            'media-type="application/hwpml-package+xml"/>'
            "</ocf:rootfiles></ocf:container>"))
        z.writestr("Contents/content.hpf", (
            f'<opf:package xmlns:opf="{OPF_NS}"><opf:manifest>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            '<opf:item id="section1" href="Contents/section1.xml" media-type="application/xml"/>'
            f'</opf:manifest><opf:spine><opf:itemref idref="{order[0]}"/>'
            f'<opf:itemref idref="{order[1]}"/></opf:spine></opf:package>'))
        z.writestr("Contents/section0.xml", b"<sec><p><t>A</t></p></sec>")
        z.writestr("Contents/section1.xml", b"<sec><p><t>B</t></p></sec>")
    return path


def _write_lane_pair(tmp_path: Path, *, left: Path | None = None,
                     right: Path | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left_run = left_root / RUN_ID
    right_run = right_root / RUN_ID
    left_run.mkdir(parents=True)
    right_run.mkdir(parents=True)
    left_candidate = left_run / "candidate.hwpx"
    right_candidate = right_run / "candidate.hwpx"
    if left is None:
        left = tmp_path / "left.hwpx"
        _story_hwpx(left)
    if right is None:
        right = tmp_path / "right.hwpx"
        _story_hwpx(right)
    left_candidate.write_bytes(left.read_bytes())
    right_candidate.write_bytes(right.read_bytes())
    def output(path: Path):
        raw = path.read_bytes()
        return {
            "state": "quarantined", "path": f"{RUN_ID}/candidate.hwpx",
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "counts": {"tables": 0, "pictures": 0, "equations": 0},
        }
    source = _source()
    left_payload = rhwp._base(
        status="candidate", reason="candidate_created", source=source,
        execution=rhwp._execution("succeeded", APPROVED_RHWP, 0),
        output=output(left_candidate))
    lock, lock_sha, _bridge = java._load_toolchain()
    right_payload = java._base(
        status="candidate", reason="candidate_created", source=source,
        execution=java._execution(
            "succeeded", java_sha256="2" * 64, lock_sha256=lock_sha,
            bridge_sha256=lock["bridge"]["sha256"],
            tool_sha256=lock["tool"]["sha256"]),
        output=output(right_candidate))
    (left_run / "receipt.json").write_text(
        json.dumps(left_payload, sort_keys=True), encoding="utf-8")
    (right_run / "receipt.json").write_text(
        json.dumps(right_payload, sort_keys=True), encoding="utf-8")
    oracle_root = tmp_path / oracle.ROOT_LEAF
    oracle_root.mkdir()
    return (left_run / "receipt.json", right_run / "receipt.json", oracle_root,
            left_candidate, right_candidate, source)


def test_t88_module_exposes_closed_schema_and_root_contract():
    assert oracle.SCHEMA == "rigorloom/hwp-semantic-oracle/v1"
    assert oracle.ADAPTER == "paired_converter"
    assert oracle.RUN_ID_RE.fullmatch(RUN_ID)
    assert oracle.ROOT_LEAF == "hwp-semantic-oracle"
    assert oracle.APPROVED_RHWP_SHA256 == APPROVED_RHWP
    assert oracle._approved_rhwp_sha256() == APPROVED_RHWP


def test_t88_empty_payload_is_receipt_only_and_not_proof():
    payload = oracle._base(status="refused", reason="source_unavailable")
    assert set(payload) == {
        "schema", "status", "reason", "adapter", "source", "execution",
        "inputs", "comparison", "render", "proof_grade", "submission_grade",
        "ceiling", "output",
    }
    assert payload["comparison"] == {
        "state": "unknown", "method": "none",
        "reason": "independent_source_oracle_not_run",
    }
    assert payload["render"] == {"state": "not_run"}
    assert payload["proof_grade"] == "none"
    assert payload["submission_grade"] is False
    assert payload["ceiling"] == "diagnostic_only"
    assert payload["output"] == {"state": "none"}


def test_bounded_content_object_normalizes_line_endings_but_preserves_whitespace(
        tmp_path: Path):
    left = tmp_path / "left.hwpx"
    right = tmp_path / "right.hwpx"
    _hwpx(left)
    _hwpx(right)
    for target, text in ((left, "A\r\nB"), (right, "A\nB")):
        with zipfile.ZipFile(target) as source:
            members = {name: source.read(name) for name in source.namelist()}
        members["Contents/section0.xml"] = (
            f"<sec><p><t>{text}</t></p><p><t>C</t></p></sec>".encode()
        )
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in members.items():
                output.writestr(name, data)
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["text"] is True


def test_bounded_content_object_does_not_collapse_ordinary_whitespace(
        tmp_path: Path):
    left = tmp_path / "left-space.hwpx"
    right = tmp_path / "right-space.hwpx"
    _hwpx(left)
    _hwpx(right)
    for target, text in ((left, "A B"), (right, "AB")):
        with zipfile.ZipFile(target) as source:
            members = {name: source.read(name) for name in source.namelist()}
        members["Contents/section0.xml"] = (
            f"<sec><p><t>{text}</t></p></sec>".encode())
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in members.items():
                output.writestr(name, data)
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["text"] is False


def test_indentation_is_not_bounded_text_content(tmp_path: Path):
    left = tmp_path / "left-indent.hwpx"
    right = tmp_path / "right-indent.hwpx"
    _hwpx(left)
    _hwpx(right)
    for target, section in (
            (left, b"<sec><p><t>A</t></p></sec>"),
            (right, b"<sec>\n  <p>\n    <t>A</t>\n  </p>\n</sec>")):
        with zipfile.ZipFile(target) as source:
            members = {name: source.read(name) for name in source.namelist()}
        members["Contents/section0.xml"] = section
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in members.items():
                output.writestr(name, data)
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["text"] is True


def test_nested_hc_img_binds_referenced_bindata_bytes(tmp_path: Path):
    left = tmp_path / "left-picture.hwpx"
    right = tmp_path / "right-picture.hwpx"
    _hwpx(left)
    _hwpx(right)
    for target, payload in ((left, b"one"), (right, b"two")):
        with zipfile.ZipFile(target) as source:
            members = {name: source.read(name) for name in source.namelist()}
        members["Contents/section0.xml"] = (
            b'<sec><pic><hc:img xmlns:hc="urn:test" '
            b'binaryItemID="BinData/image.bin"/></pic></sec>')
        members["BinData/image.bin"] = payload
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in members.items():
                output.writestr(name, data)
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["referenced_pictures"] is False


def test_picture_binary_item_id_ref_uses_opf_manifest_target(
        tmp_path: Path):
    left = tmp_path / "left-picture-id.hwpx"
    right = tmp_path / "right-picture-id.hwpx"
    _hwpx(left)
    _hwpx(right)
    for target, real_name, payload in (
            (left, "realL.bin", b"left-payload"),
            (right, "realR.bin", b"right-payload")):
        with zipfile.ZipFile(target) as source:
            members = {name: source.read(name) for name in source.namelist()}
        manifest_item = (
            f'<opf:item id="img1" href="BinData/{real_name}" '
            'media-type="image/png"/>').encode()
        members["Contents/content.hpf"] = members["Contents/content.hpf"].replace(
            b"</opf:manifest>", manifest_item + b"</opf:manifest>")
        members["Contents/section0.xml"] = (
            b'<sec><pic><hc:img xmlns:hc="urn:test" '
            b'binaryItemIDRef="img1"/></pic></sec>')
        members[f"BinData/{real_name}"] = payload
        # This decoy would make the old stem-only resolver falsely agree.
        members["BinData/img1.bin"] = b"same-decoy"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
            for name, data in members.items():
                output.writestr(name, data)
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["referenced_pictures"] is False


def test_picture_binary_item_id_ref_without_manifest_id_refuses_stem_decoy(
        tmp_path: Path):
    target = tmp_path / "picture-id-missing.hwpx"
    _hwpx(target)
    with zipfile.ZipFile(target) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["Contents/section0.xml"] = (
        b'<sec><pic><hc:img xmlns:hc="urn:test" '
        b'binaryItemIDRef="img1"/></pic></sec>')
    members["BinData/img1.bin"] = b"same-decoy"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
        for name, data in members.items():
            output.writestr(name, data)
    with pytest.raises(oracle.OracleError) as caught:
        oracle._fingerprint(target)
    assert caught.value.reason == "picture_reference_unavailable"


@pytest.mark.parametrize("control", ["tab", "fwSpace", "lineBreak"])
def test_explicit_text_controls_are_bounded_content_tokens(
        tmp_path: Path, control: str):
    left = tmp_path / f"left-{control}.hwpx"
    right = tmp_path / f"right-{control}.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    f"<sec><p><t>A</t><{control}/><t>B</t></p></sec>".encode())
    _rewrite_member(right, "Contents/section0.xml",
                    b"<sec><p><t>AB</t></p></sec>")
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["text"] is False


def test_table_topology_and_spans_are_bounded_content(tmp_path: Path):
    left = tmp_path / "left-table.hwpx"
    right = tmp_path / "right-table.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    b'<sec><tbl><tr><tc cellSpan="1"><p><t>A</t></p></tc>'
                    b'</tr></tbl></sec>')
    _rewrite_member(right, "Contents/section0.xml",
                    b'<sec><tbl><tr><tc cellSpan="2"><p><t>A</t></p></tc>'
                    b'</tr></tbl></sec>')
    assert oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right)
    )["story_table_topology"] is False


def test_opf_spine_order_is_bounded_content(tmp_path: Path):
    left = _two_section_hwpx(tmp_path / "left-order.hwpx")
    right = _two_section_hwpx(tmp_path / "right-order.hwpx", reverse=True)
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["text"] is False
    # Each section has the same topology; only its OPF spine position/content
    # differs.  Member paths are transport details, not structure identity.
    assert result["story_table_topology"] is True


def test_opf_spine_uses_section_root_not_filename(tmp_path: Path):
    target = tmp_path / "renamed-section.hwpx"
    _hwpx(target)
    with zipfile.ZipFile(target) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["Contents/bodyA.xml"] = members.pop("Contents/section0.xml")
    members["Contents/content.hpf"] = members["Contents/content.hpf"].replace(
        b"section0.xml", b"bodyA.xml")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
        for name, data in members.items():
            output.writestr(name, data)
    assert oracle._fingerprint(target)["text"]


def test_section_member_path_is_not_bounded_content_identity(tmp_path: Path):
    left = tmp_path / "left-section-path.hwpx"
    right = tmp_path / "right-section-path.hwpx"
    _hwpx(left)
    _hwpx(right)
    with zipfile.ZipFile(right) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["Contents/bodyA.xml"] = members.pop("Contents/section0.xml")
    members["Contents/content.hpf"] = members["Contents/content.hpf"].replace(
        b"section0.xml", b"bodyA.xml")
    with zipfile.ZipFile(right, "w", compression=zipfile.ZIP_STORED) as output:
        for name, data in members.items():
            output.writestr(name, data)
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["story_table_topology"] is True


def test_input_lane_roots_must_not_overlap_oracle_root(tmp_path: Path):
    left_receipt, right_receipt, _root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    overlap = left_receipt.parent / oracle.ROOT_LEAF
    overlap.mkdir()
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=overlap, run_id=RUN_ID)
    assert result["reason"] == "roles_not_distinct"


def test_equation_script_and_story_control_are_bounded_content(
        tmp_path: Path):
    left = tmp_path / "left-equation.hwpx"
    right = tmp_path / "right-equation.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    b"<sec><equation><script>x+y</script></equation>"
                    b"<header><p><t>H</t></p></header><ctrl/></sec>")
    _rewrite_member(right, "Contents/section0.xml",
                    b"<sec><equation><script>x-y</script></equation>"
                    b"<footer><p><t>H</t></p></footer><ctrl/></sec>")
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["equations"] is False
    assert result["story_table_topology"] is False
    assert result["explicit_controls"] is True


def test_run_segmentation_and_layout_cache_are_not_compared(tmp_path: Path):
    left = tmp_path / "left-layout.hwpx"
    right = tmp_path / "right-layout.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml", (
        b"<sec><p><run><t>A</t></run><run><t>B</t></run></p>"
        b"<linesegarray cache=\"one\"><lineseg x=\"1\"/></linesegarray>"
        b"<tbl><tr><tc><cellAddr colAddr=\"1\" rowAddr=\"2\"/>"
        b"<p><t>C</t></p></tc></tr></tbl></sec>"))
    _rewrite_member(right, "Contents/section0.xml", (
        b"<sec><p><run><t>AB</t></run></p>"
        b"<linesegarray cache=\"two\"><lineseg x=\"99\"/></linesegarray>"
        b"<tbl><tr><tc><cellAddr colAddr=\"1\" rowAddr=\"2\"/>"
        b"<p><t>C</t></p></tc></tr></tbl></sec>"))
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert all(result.values())


def test_cell_address_is_bound_in_table_topology(tmp_path: Path):
    left = tmp_path / "left-cell-address.hwpx"
    right = tmp_path / "right-cell-address.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    b"<sec><tbl><tr><tc><cellAddr colAddr=\"0\" rowAddr=\"0\"/>"
                    b"<p><t>A</t></p></tc></tr></tbl></sec>")
    _rewrite_member(right, "Contents/section0.xml",
                    b"<sec><tbl><tr><tc><cellAddr colAddr=\"1\" rowAddr=\"0\"/>"
                    b"<p><t>A</t></p></tc></tr></tbl></sec>")
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["story_table_topology"] is False


def test_style_and_new_numbering_are_outside_bounded_coverage(tmp_path: Path):
    left = tmp_path / "left-style.hwpx"
    right = tmp_path / "right-style.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    b"<sec><newNum value=\"1\"/><style id=\"left\"/>"
                    b"<p><t>A</t></p></sec>")
    _rewrite_member(right, "Contents/section0.xml",
                    b"<sec><newNum value=\"9\"/><style id=\"right\"/>"
                    b"<p><t>A</t></p></sec>")
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert all(result.values())


def test_table_cell_sublist_is_not_counted_as_story(tmp_path: Path):
    left = tmp_path / "left-sublist.hwpx"
    right = tmp_path / "right-sublist.hwpx"
    _hwpx(left)
    _hwpx(right)
    _rewrite_member(left, "Contents/section0.xml",
                    b"<sec><tbl><tr><tc><subList><p><t>C</t></p>"
                    b"</subList></tc></tr></tbl></sec>")
    _rewrite_member(right, "Contents/section0.xml",
                    b"<sec><tbl><tr><tc><subList><subList><p><t>C</t></p>"
                    b"</subList></subList></tc></tr></tbl></sec>")
    result = oracle._compare_fingerprints(
        oracle._fingerprint(left), oracle._fingerprint(right))
    assert result["story_table_topology"] is True


@pytest.mark.parametrize(("local", "reason"), [
    ("fieldBegin", "unsupported_field"),
    ("drawText", "unsupported_draw_text"),
    ("caption", "unsupported_caption"),
])
def test_known_unsupported_control_refuses(tmp_path: Path, local: str, reason: str):
    target = tmp_path / f"{local}.hwpx"
    _hwpx(target)
    _rewrite_member(target, "Contents/section0.xml",
                    f"<sec><{local}/></sec>".encode())
    with pytest.raises(oracle.OracleError) as caught:
        oracle._fingerprint(target)
    assert caught.value.reason == reason


def test_public_t79_passed_corpus_smoke_is_bounded_content_only():
    corpus = sorted(Path(__file__).parents[2].glob(
        "tests/corpus/forms/converted/*.hwpx"))
    if not corpus:
        pytest.skip("public corpus not checked out")
    passed = 0
    for document in corpus:
        try:
            oracle._fingerprint(document)
        except oracle.OracleError:
            continue
        passed += 1
    assert passed >= 1


def test_unknown_future_control_refuses(tmp_path: Path):
    target = tmp_path / "future.hwpx"
    _hwpx(target)
    with zipfile.ZipFile(target) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["Contents/section0.xml"] = b"<sec><futureCtrl/></sec>"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as output:
        for name, data in members.items():
            output.writestr(name, data)
    with pytest.raises(oracle.OracleError) as exc:
        oracle._fingerprint(target)
    assert exc.value.reason in {"unknown_control", "hwpx_grammar_unknown"}


def test_compare_runs_public_verifiers_and_verify_rebinds_inputs(tmp_path: Path):
    left_receipt, right_receipt, root, _left_candidate, _right_candidate, source = \
        _write_lane_pair(tmp_path)
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "diagnostic_agreement"
    assert result["source"] == source
    assert result["comparison"]["matches"] == {
        "text": True, "story_table_topology": True, "equations": True,
        "referenced_pictures": True, "explicit_controls": True,
    }
    assert result["comparison"]["method"] == \
        "paired_converter_bounded_content_object_v1"
    assert result["comparison"]["coverage"] == {
        "compared": [
            "text", "story_table_topology", "equations",
            "referenced_pictures", "explicit_controls",
        ],
        "not_compared": [
            "style_definitions", "paragraph_numbering",
            "layout_pagination", "metadata",
        ],
    }
    checked = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert checked["status"] == "diagnostic_agreement"
    missing = oracle.verify_diagnostic(root, RUN_ID)
    assert missing["reason"] == "verification_inputs_required"


def test_compare_refuses_bounded_content_object_mismatch(tmp_path: Path):
    left = _story_hwpx(tmp_path / "mismatch-left.hwpx", text="LEFT")
    right = _story_hwpx(tmp_path / "mismatch-right.hwpx", text="RIGHT")
    left_receipt, right_receipt, root, _left, _right, _ = _write_lane_pair(
        tmp_path / "mismatch", left=left, right=right)
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "refused"
    assert result["reason"] == "bounded_content_object_mismatch"


def test_verify_rejects_run_directory_symlink(tmp_path: Path):
    lane = _write_lane_pair(tmp_path / "lanes")
    left_receipt, right_receipt, source_root, _left, _right, _ = lane
    assert oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=source_root, run_id=RUN_ID)["status"] == \
        "diagnostic_agreement"
    root = tmp_path / "B" / oracle.ROOT_LEAF
    root.mkdir(parents=True)
    try:
        (root / RUN_ID).symlink_to(source_root / RUN_ID, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    result = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert result["status"] == "refused"
    assert result["reason"] == "receipt_layout_invalid"


def test_verify_rechecks_run_directory_after_input_load(tmp_path: Path,
                                                        monkeypatch):
    lane = _write_lane_pair(tmp_path)
    left_receipt, right_receipt, root, _left, _right, _ = lane
    assert oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)["status"] == \
        "diagnostic_agreement"
    original = oracle._load_current_inputs
    moved = tmp_path / "moved-run"
    calls = 0

    def load_then_swap(left: Path, right: Path):
        nonlocal calls
        current = original(left, right)
        if calls == 0:
            run_path = root / RUN_ID
            run_path.rename(moved)
            try:
                run_path.symlink_to(moved, target_is_directory=True)
            except (OSError, NotImplementedError):
                pytest.skip("directory symlinks unavailable")
        calls += 1
        return current

    monkeypatch.setattr(oracle, "_load_current_inputs", load_then_swap)
    result = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert result["status"] == "refused"
    assert result["reason"] == "receipt_layout_invalid"


def test_verify_rejects_candidate_drift_after_agreement(tmp_path: Path):
    left_receipt, right_receipt, root, left_candidate, _right_candidate, _source_value = \
        _write_lane_pair(tmp_path)
    assert oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)["status"] == "diagnostic_agreement"
    left_candidate.write_bytes(b"drift")
    result = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert result["status"] == "refused"
    assert result["reason"] in {"candidate_drift", "candidate_unavailable",
                                 "candidate_invalid", "hwpx_invalid",
                                 "candidate_verifier_refused"}


@pytest.mark.parametrize("variant", [
    "oracle_receipt", "rhwp_receipt", "java_receipt",
    "rhwp_candidate", "java_candidate",
])
def test_verify_rechecks_every_input_after_initial_load(
        tmp_path: Path, monkeypatch, variant: str):
    lane = _write_lane_pair(tmp_path)
    left_receipt, right_receipt, root, left_candidate, right_candidate, _ = lane
    assert oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)["status"] == "diagnostic_agreement"

    def overwrite_same_inode(path: Path, raw: bytes) -> None:
        # Published receipts can be read-only on POSIX; make the test's
        # same-inode attack explicit and owner-safe on every platform.
        try:
            path.chmod(0o600)
        except OSError:
            pass
        path.write_bytes(raw)

    original = oracle._load_current_inputs
    calls = 0

    def load_then_mutate(left: Path, right: Path):
        nonlocal calls
        current = original(left, right)
        if calls == 0:
            if variant == "oracle_receipt":
                oracle_path = root / RUN_ID / "receipt.json"
                overwrite_same_inode(oracle_path, oracle_path.read_bytes() + b" ")
            elif variant == "rhwp_receipt":
                overwrite_same_inode(left_receipt, left_receipt.read_bytes() + b" ")
            elif variant == "java_receipt":
                overwrite_same_inode(right_receipt, right_receipt.read_bytes() + b" ")
            elif variant == "rhwp_candidate":
                overwrite_same_inode(left_candidate, left_candidate.read_bytes() + b" ")
            else:
                overwrite_same_inode(right_candidate, right_candidate.read_bytes() + b" ")
        calls += 1
        return current

    monkeypatch.setattr(oracle, "_load_current_inputs", load_then_mutate)
    result = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert result["status"] == "refused"
    assert result["reason"] in {
        "input_drift", "candidate_drift", "candidate_unavailable",
        "candidate_invalid", "candidate_verifier_refused",
    }


def test_verify_rejects_a_different_agreeing_pair_for_same_source(tmp_path: Path):
    first = _write_lane_pair(tmp_path / "first")
    assert oracle.compare_diagnostic(
        rhwp_receipt=first[0], java_receipt=first[1],
        diagnostic_root=first[2], run_id=RUN_ID)["status"] == "diagnostic_agreement"
    left = _story_hwpx(tmp_path / "changed-left.hwpx", text="CHANGED")
    right = _story_hwpx(tmp_path / "changed-right.hwpx", text="CHANGED")
    second = _write_lane_pair(tmp_path / "second", left=left, right=right)
    assert oracle.compare_diagnostic(
        rhwp_receipt=second[0], java_receipt=second[1],
        diagnostic_root=second[2], run_id=RUN_ID)["status"] == "diagnostic_agreement"
    result = oracle.verify_diagnostic(
        first[2], RUN_ID, rhwp_receipt=second[0], java_receipt=second[1])
    assert result["status"] == "refused"
    assert result["reason"] == "input_drift"


@pytest.mark.parametrize(("field", "value"), [
    ("format", "doc"), ("version", "5.1.0.1"), ("bytes", 124),
    ("sha256", "2" * 64), ("compressed", False), ("security_flags", ["x"]),
])
def test_source_descriptor_fields_are_rebound_exactly(
        tmp_path: Path, field: str, value):
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    payload = json.loads(left_receipt.read_text(encoding="utf-8"))
    payload["source"][field] = value
    left_receipt.write_text(json.dumps(payload), encoding="utf-8")
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "refused"
    assert result["reason"] in {
        "source_descriptor_invalid", "source_descriptor_mismatch",
    }


def test_roles_same_candidate_foreign_schema_and_duplicate_receipt_refuse(tmp_path: Path):
    left_receipt, right_receipt, root, left_candidate, right_candidate, _source_value = \
        _write_lane_pair(tmp_path)
    same = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=left_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert same["reason"] == "roles_not_distinct"
    right_payload = json.loads(right_receipt.read_text(encoding="utf-8"))
    right_payload["schema"] = "foreign/v1"
    right_receipt.write_text(json.dumps(right_payload), encoding="utf-8")
    foreign = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert foreign["reason"] in {"receipt_schema_invalid", "receipt_state_invalid"}
    # Restore and reject a candidate with an external hard-link owner.
    right_payload["schema"] = java.SCHEMA
    right_receipt.write_text(json.dumps(right_payload), encoding="utf-8")
    owner = tmp_path / "candidate-owner.hwpx"
    owner.write_bytes(left_candidate.read_bytes())
    right_candidate.unlink()
    try:
        right_candidate.hardlink_to(owner)
    except (OSError, NotImplementedError):
        pytest.skip("hard links unavailable")
    linked = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert linked["status"] == "refused"
    assert linked["reason"] in {"candidate_invalid", "candidate_unavailable"}


def test_allowlist_and_java_lock_drift_refuse(tmp_path: Path, monkeypatch):
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    bad_allowlist = tmp_path / "bad-allowlist.json"
    bad_allowlist.write_text(json.dumps({"schema": "foreign"}), encoding="utf-8")
    monkeypatch.setattr(oracle, "ALLOWLIST_PATH", bad_allowlist)
    bad = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert bad["reason"] == "rhwp_allowlist_invalid"
    monkeypatch.setattr(oracle, "ALLOWLIST_PATH", oracle.Path(__file__).parents[1]
                        / "references" / "hwp_semantic_oracle" / "rhwp-allowlist.json")
    monkeypatch.setattr(java, "_load_toolchain",
                        lambda: (_ for _ in ()).throw(java.JavaDiagnosticError("drift")))
    drift = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert drift["reason"] == "java_toolchain_unavailable"


def test_receipt_duplicate_unknown_and_privacy_shape_refuse(tmp_path: Path):
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    duplicate = left_receipt.with_name("duplicate.json")
    duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    duplicate_result = oracle.compare_diagnostic(
        rhwp_receipt=duplicate, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert duplicate_result["reason"] == "receipt_duplicate_key"
    payload = json.loads(left_receipt.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    left_receipt.write_text(json.dumps(payload), encoding="utf-8")
    unknown = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert unknown["reason"] == "receipt_schema_invalid"
    # A successful receipt is intentionally path/text/stdout/stderr-free.
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path / "private-free")
    success = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    encoded = json.dumps(success, ensure_ascii=False)
    assert success["status"] == "diagnostic_agreement"
    assert "candidate.hwpx" not in encoded
    assert "stdout" not in encoded and "stderr" not in encoded


def test_receipt_hardlink_or_symlink_is_not_an_input_snapshot(tmp_path: Path):
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    owner = tmp_path / "receipt-owner.json"
    owner.write_bytes(left_receipt.read_bytes())
    left_receipt.unlink()
    try:
        left_receipt.hardlink_to(owner)
    except (OSError, NotImplementedError):
        pytest.skip("hard links unavailable")
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["reason"] == "receipt_invalid"


def test_publication_collision_and_cli_exit_contract(tmp_path: Path, capsys):
    left_receipt, right_receipt, root, _left, _right, _source_value = \
        _write_lane_pair(tmp_path)
    run = root / RUN_ID
    run.mkdir()
    sentinel = run / "sentinel"
    sentinel.write_bytes(b"foreign")
    collision = oracle.main([
        "compare", str(left_receipt), str(right_receipt),
        "--diagnostic-root", str(root), "--run-id", RUN_ID])
    assert collision == oracle.EXIT_REFUSED
    assert sentinel.read_bytes() == b"foreign"
    # A fresh pair demonstrates success and verify's required four-input CLI.
    fresh = _write_lane_pair(tmp_path / "fresh")
    assert oracle.main([
        "compare", str(fresh[0]), str(fresh[1]), "--diagnostic-root",
        str(fresh[2]), "--run-id", RUN_ID]) == oracle.EXIT_OK
    assert oracle.main([
        "verify", "--diagnostic-root", str(fresh[2]), "--run-id", RUN_ID,
        "--rhwp-receipt", str(fresh[0]), "--java-receipt", str(fresh[1]),
    ]) == oracle.EXIT_OK
    with pytest.raises(SystemExit) as usage:
        oracle.main([])
    assert usage.value.code == oracle.EXIT_USAGE


def test_publication_stage_uses_root_parent_same_device(tmp_path: Path,
                                                        monkeypatch):
    lane = _write_lane_pair(tmp_path)
    left_receipt, right_receipt, root, _left, _right, _ = lane
    seen: dict[str, str] = {}
    real = oracle.tempfile.TemporaryDirectory

    def capture_stage(*args, **kwargs):
        seen["dir"] = kwargs.get("dir", "")
        return real(*args, **kwargs)

    monkeypatch.setattr(oracle.tempfile, "TemporaryDirectory", capture_stage)
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "diagnostic_agreement"
    assert Path(seen["dir"]).resolve() == root.parent.resolve()


def test_publication_cleanup_fault_cannot_rewrite_success(tmp_path: Path,
                                                          monkeypatch):
    lane = _write_lane_pair(tmp_path)
    left_receipt, right_receipt, root, _left, _right, _ = lane
    real = oracle.tempfile.TemporaryDirectory

    class FailingCleanup(real):
        def __exit__(self, exc_type, exc_value, traceback):
            result = super().__exit__(exc_type, exc_value, traceback)
            if Path(self.name).name.startswith(f".{oracle.ROOT_LEAF}-"):
                raise OSError("injected cleanup failure")
            return result

    monkeypatch.setattr(oracle.tempfile, "TemporaryDirectory", FailingCleanup)
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "diagnostic_agreement"
    receipt = root / RUN_ID / "receipt.json"
    assert receipt.is_file()
    checked = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert checked["status"] == "diagnostic_agreement"


def test_publication_precleanup_fault_leaves_single_link_receipt(
        tmp_path: Path, monkeypatch):
    lane = _write_lane_pair(tmp_path)
    left_receipt, right_receipt, root, _left, _right, _ = lane
    real = oracle.tempfile.TemporaryDirectory

    class NoCleanup(real):
        def __exit__(self, exc_type, exc_value, traceback):
            if Path(self.name).name.startswith(f".{oracle.ROOT_LEAF}-"):
                raise OSError("injected precleanup failure")
            return super().__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(oracle.tempfile, "TemporaryDirectory", NoCleanup)
    result = oracle.compare_diagnostic(
        rhwp_receipt=left_receipt, java_receipt=right_receipt,
        diagnostic_root=root, run_id=RUN_ID)
    assert result["status"] == "diagnostic_agreement"
    receipt = root / RUN_ID / "receipt.json"
    assert receipt.stat().st_nlink == 1
    checked = oracle.verify_diagnostic(
        root, RUN_ID, rhwp_receipt=left_receipt, java_receipt=right_receipt)
    assert checked["status"] == "diagnostic_agreement"
