"""E3.1 round-trip proof for the canonical OWPML writer (hwpx_write.py).

The claim under test: parse → serialize reproduces what Hancom wrote, member
for member, on every HWPX in ``tests/corpus/forms``.  Where byte identity is
provably out of reach, the weaker claim is named and measured rather than
quietly dropped:

* ``byte_identical``   emitted bytes == source bytes.
* ``canonical_equal``  re-parsing the emission yields the same model, so the
                       information survived even though the spelling did not.
* ``idempotent``       emitting the re-parsed emission reproduces it (fixed
                       point — repeated saves do not drift).

The single measured exception is XML 1.0 §2.11 line-end normalization: three
corpus parts carry a literal CR inside character data, which EVERY conforming
parser turns into LF.  Those parts are canonical-equal and idempotent, not
byte-identical, and the test asserts exactly that split by name.

NOT proven here: that Hancom opens the written files without a repair dialog.
That is E3.2, it needs COM, and no test in this file may be read as evidence
for it.

    python -m pytest engine/tests/test_hwpx_roundtrip.py -q
"""
import hashlib
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import form_inspect  # noqa: E402
import hwpx_inventory  # noqa: E402
import hwpx_write as W  # noqa: E402
import xml_backend  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms")

#: The corpus parts whose source carries a literal CR in character data, so
#: byte identity is impossible through any conforming XML parser.  Named, not
#: counted, so a NEW non-byte-identical part fails the suite instead of hiding
#: inside a ratio.
CR_PARTS = {
    ("jeongbo-gonggae-cheongguseo", "Contents/section0.xml"),
    ("jumin-deungchobon-sinchengseo", "Contents/section0.xml"),
    ("nrf-gyeolgwa-bogoseo-yangsik", "Contents/content.hpf"),
}

#: Measured over the 12-form corpus: 96 XML members, 93 byte-identical.
EXPECTED_XML_PARTS = 96
EXPECTED_BYTE_IDENTICAL = 93


def _corpus_files():
    if not os.path.isdir(CORPUS):
        return []
    found = []
    for base, _dirs, names in os.walk(CORPUS):
        for name in sorted(names):
            if name.endswith(".hwpx"):
                found.append(os.path.join(base, name))
    return sorted(found)


CORPUS_FILES = _corpus_files()
SLUGS = [os.path.splitext(os.path.basename(p))[0] for p in CORPUS_FILES]

corpus_required = pytest.mark.skipif(
    not CORPUS_FILES,
    reason="form corpus (tests/corpus/forms/**/*.hwpx) not present on this machine",
)


def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _slug(path):
    return os.path.splitext(os.path.basename(path))[0]


def _structural_summary(package):
    """Element counts per member plus the document's text runs, in order."""
    summary = {"members": package.names(), "elements": {}, "text": []}
    for part in package.parts:
        if not part.is_xml:
            continue
        parsed = W.parse_xml_part(part.bytes())
        counts = {}
        for node in parsed.root.iter():
            counts[node.qname] = counts.get(node.qname, 0) + 1
        summary["elements"][part.name] = counts
        if part.name.startswith("Contents/section"):
            summary["text"] = summary["text"] + [
                node.text or "" for node in parsed.root.iter_local("t")]
    return summary


def _reader_summary(path):
    """The repo's own HWPX reader's view, minus the whole-file hash."""
    profile, baseline = form_inspect.analyze(path, want_baseline=True)
    keep = lambda payload: {  # noqa: E731
        key: value for key, value in payload.items()
        if key not in ("form_hash", "file")}
    return keep(profile), keep(baseline or {})


# --------------------------------------------------------------------------
# corpus round-trip
# --------------------------------------------------------------------------

@corpus_required
@pytest.mark.parametrize("path", CORPUS_FILES, ids=SLUGS)
class TestCorpusRoundTrip:

    def test_part_list_and_metadata_preserved(self, path, tmp_path):
        source = W.HwpxPackage.read(path)
        source.materialize()
        out = tmp_path / "rewritten.hwpx"
        source.write(out)

        with zipfile.ZipFile(path) as original, zipfile.ZipFile(out) as rewritten:
            before = original.infolist()
            after = rewritten.infolist()
            assert [i.filename for i in before] == [i.filename for i in after]
            for left, right in zip(before, after):
                assert (left.compress_type, left.date_time, left.create_system,
                        left.external_attr, left.flag_bits) == \
                       (right.compress_type, right.date_time, right.create_system,
                        right.external_attr, right.flag_bits), left.filename

    def test_part_bytes_identical_or_canonical_equal(self, path):
        package = W.HwpxPackage.read(path)
        report = package.roundtrip_report()
        slug = _slug(path)
        for row in report["parts"]:
            if not row["xml"]:
                continue
            key = (slug, row["name"])
            if row["byte_identical"]:
                continue
            assert key in CR_PARTS, (
                "%s/%s is not byte-identical and is not a known line-end "
                "normalization case; diff=%r" % (slug, row["name"], row.get("diff")))
            assert row["source_had_cr"], (
                "%s/%s lost byte identity for a reason other than the CR "
                "normalization it is listed for; diff=%r"
                % (slug, row["name"], row.get("diff")))
            assert row["canonical_equal"], "%s/%s lost information" % key
            assert row["idempotent"], "%s/%s does not reach a fixed point" % key

    def test_every_part_is_canonical_equal_and_idempotent(self, path):
        report = W.HwpxPackage.read(path).roundtrip_report()
        assert report["canonical_equal"] == report["xml_parts"]
        assert report["idempotent"] == report["xml_parts"]

    def test_repo_readers_see_the_same_document(self, path, tmp_path):
        out = tmp_path / "rewritten.hwpx"
        W.HwpxPackage.read(path).materialize().write(out)
        assert _reader_summary(str(out)) == _reader_summary(path)

    def test_xml_backend_opens_the_rewritten_file(self, path, tmp_path):
        out = tmp_path / "rewritten.hwpx"
        W.HwpxPackage.read(path).materialize().write(out)
        document = xml_backend.HwpxDocument(out)
        assert document.sections
        assert document.header is not None

    def test_source_is_never_touched(self, path, tmp_path):
        before = _sha256(path)
        W.HwpxPackage.read(path).materialize().write(tmp_path / "out.hwpx")
        assert _sha256(path) == before


@corpus_required
def test_corpus_byte_identical_ratio_is_exactly_what_was_measured():
    """The headline number, asserted rather than described."""
    xml_parts = byte_identical = canonical = idempotent = 0
    misses = []
    for path in CORPUS_FILES:
        report = W.HwpxPackage.read(path).roundtrip_report()
        xml_parts += report["xml_parts"]
        byte_identical += report["byte_identical"]
        canonical += report["canonical_equal"]
        idempotent += report["idempotent"]
        for row in report["parts"]:
            if row["xml"] and not row["byte_identical"]:
                misses.append((_slug(path), row["name"]))
    assert xml_parts == EXPECTED_XML_PARTS
    assert byte_identical == EXPECTED_BYTE_IDENTICAL
    assert canonical == xml_parts
    assert idempotent == xml_parts
    assert set(misses) == CR_PARTS
    assert byte_identical / xml_parts == pytest.approx(93 / 96)


@corpus_required
def test_whole_archive_identity_is_reported_honestly():
    """Archive-level identity, which deflate makes weaker than part identity.

    Hancom compresses with zlib level 2 (general-purpose flag bits 0b10), and
    the writer reproduces that.  Two large sections still come out with a
    different compressed *encoding* of identical content — the member CRC
    matches, the compressed length does not — because deflate output is not
    specified to be reproducible across implementations.  So the honest claim
    is per-member CRC, not archive bytes.
    """
    identical_archives = 0
    for path in CORPUS_FILES:
        rewritten = W.HwpxPackage.read(path).materialize().tobytes()
        with open(path, "rb") as handle:
            original = handle.read()
        if rewritten == original:
            identical_archives += 1
            continue
        with zipfile.ZipFile(path) as left:
            before = {i.filename: i.CRC for i in left.infolist()}
        import io
        with zipfile.ZipFile(io.BytesIO(rewritten)) as right:
            after = {i.filename: i.CRC for i in right.infolist()}
        assert set(before) == set(after)
        for name in before:
            if before[name] == after[name]:
                continue
            # The only members allowed to differ in content are the CR ones.
            assert (_slug(path), name) in CR_PARTS, (path, name)
    assert identical_archives == 7, (
        "measured: 7 of 12 corpus archives reproduce byte-for-byte; 3 differ "
        "by the CR normalization and 2 by deflate encoding of identical "
        "content (CRC matches)")


# --------------------------------------------------------------------------
# mutation through the model
# --------------------------------------------------------------------------

@corpus_required
class TestMutationThroughTheModel:
    """A change made through the model must land, and nothing else may move.

    These are structural assertions only.  Whether Hancom accepts the mutated
    file is E3.2 and is NOT tested here.
    """

    @pytest.fixture
    def form(self):
        return CORPUS_FILES[0]

    def test_run_text_change_is_the_only_change(self, form, tmp_path):
        package = W.HwpxPackage.read(form).materialize()
        before = _structural_summary(package)

        section = package.part(package.section_names()[0]).tree()
        target = next(node for node in section.root.iter_local("t") if node.text)
        original_text = target.text
        target.text = "리고르룸 편집 표지"

        out = tmp_path / "mutated.hwpx"
        package.write(out)
        after = _structural_summary(W.HwpxPackage.read(out))

        assert after["members"] == before["members"]
        assert after["elements"] == before["elements"]
        changed = [(index, left, right)
                   for index, (left, right) in enumerate(
                       zip(before["text"], after["text"])) if left != right]
        assert len(changed) == 1
        assert changed[0][1] == original_text
        assert changed[0][2] == "리고르룸 편집 표지"

    def test_added_paragraph_moves_exactly_one_count(self, form, tmp_path):
        package = W.HwpxPackage.read(form).materialize()
        before = _structural_summary(package)
        section_name = package.section_names()[0]
        section = package.part(section_name).tree()

        paragraph = next(node for node in section.root.children
                         if node.local == "p")
        clone = W.parse_xml_part(
            W.XML_DECLARATION + _node_bytes(paragraph)).root
        clone.set("id", "999999")
        section.root.children.append(clone)

        out = tmp_path / "added.hwpx"
        package.write(out)
        after = _structural_summary(W.HwpxPackage.read(out))

        assert after["members"] == before["members"]
        before_counts = before["elements"][section_name]
        after_counts = after["elements"][section_name]
        assert set(after_counts) == set(before_counts)
        for qname, count in before_counts.items():
            delta = after_counts[qname] - count
            expected = _count_in(clone, qname)
            assert delta == expected, (qname, delta, expected)

    def test_cell_text_change_is_the_only_change(self, tmp_path):
        form = next((path for path in CORPUS_FILES
                     if _has_table(path)), None)
        if form is None:
            pytest.skip("no corpus form carries a table")
        package = W.HwpxPackage.read(form).materialize()
        before = _structural_summary(package)

        section = package.part(package.section_names()[0]).tree()
        table = section.root.find_local("tbl")
        cell = table.find_local("tc")
        target = next(node for node in cell.iter_local("t"))
        target.text = "채워 넣은 값"

        out = tmp_path / "cell.hwpx"
        package.write(out)
        after = _structural_summary(W.HwpxPackage.read(out))

        assert after["elements"] == before["elements"]
        changed = [index for index, (left, right)
                   in enumerate(zip(before["text"], after["text"]))
                   if left != right]
        assert len(changed) == 1
        assert after["text"][changed[0]] == "채워 넣은 값"

    def test_untouched_parts_stay_byte_identical_after_a_mutation(
            self, form, tmp_path):
        package = W.HwpxPackage.read(form).materialize()
        section_name = package.section_names()[0]
        target = next(node for node in package.part(section_name).tree()
                      .root.iter_local("t") if node.text)
        target.text = "변경"
        out = tmp_path / "mutated.hwpx"
        package.write(out)

        slug = _slug(form)
        with zipfile.ZipFile(form) as left, zipfile.ZipFile(out) as right:
            for name in left.namelist():
                if name == section_name or (slug, name) in CR_PARTS:
                    continue
                assert left.read(name) == right.read(name), name


def _node_bytes(node):
    out = bytearray()
    W._serialize(node, out)
    return bytes(out)


def _count_in(node, qname):
    return sum(1 for item in node.iter() if item.qname == qname)


def _has_table(path):
    package = W.HwpxPackage.read(path)
    section = package.part(package.section_names()[0]).tree()
    return section.root.find_local("tbl") is not None


# --------------------------------------------------------------------------
# new-document path
# --------------------------------------------------------------------------

class TestBlankDocument:
    """The smallest document the writer can build from the model alone.

    Hancom acceptance is NOT claimed: E3.2 owns that and needs COM.
    """

    def test_member_list_and_compression_match_the_ocf_layout(self, tmp_path):
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)
        with zipfile.ZipFile(out) as archive:
            infos = archive.infolist()
            assert [i.filename for i in infos] == W.BLANK_MEMBER_ORDER
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            assert archive.read("mimetype") == W.MIMETYPE
            assert archive.getinfo("version.xml").compress_type == zipfile.ZIP_STORED

    def test_every_part_uses_the_hancom_declaration(self, tmp_path):
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)
        with zipfile.ZipFile(out) as archive:
            for name in archive.namelist():
                if not name.endswith(W.XML_MEMBER_SUFFIXES):
                    continue
                assert archive.read(name).startswith(W.XML_DECLARATION), name

    def test_round_trips_byte_for_byte(self, tmp_path):
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)
        report = W.HwpxPackage.read(out).roundtrip_report()
        assert report["xml_parts"] == 8
        assert report["byte_identical"] == report["xml_parts"]
        assert report["idempotent"] == report["xml_parts"]

    def test_is_byte_deterministic(self, tmp_path):
        first = W.blank_package().tobytes()
        second = W.blank_package().tobytes()
        assert first == second

    def test_the_repo_readers_accept_it(self, tmp_path):
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)

        profile, _baseline = form_inspect.analyze(str(out))
        assert profile["ok"] is True
        assert profile["format_hints"]["table_count"] == 0
        assert profile["page_metrics"]["width"] == 59528

        document = xml_backend.HwpxDocument(out)
        assert list(document.sections) == ["Contents/section0.xml"]

    def test_carries_one_section_and_one_paragraph(self, tmp_path):
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)
        package = W.HwpxPackage.read(out)
        section = package.part("Contents/section0.xml").tree()
        assert section.root.local == "sec"
        paragraphs = [node for node in section.root.children if node.local == "p"]
        assert len(paragraphs) == 1
        assert paragraphs[0].text_content() == ""

    def test_part_content_hashes_are_pinned(self):
        """The fixture is the generator plus these pins, not a committed blob.

        engine's privacy gate makes every ``.hwpx`` a HARD finding unless it is
        sha256-pinned in the corpus manifest (pipeline/scripts/privacy_scan.py),
        and the corpus manifest documents provenance and licence for official
        government forms — a Rigorloom-authored blank does not belong in it.
        So the blank ships as a deterministic builder, pinned here on the
        UNCOMPRESSED bytes of each member: deflate output can vary with the
        zlib build, member content cannot.
        """
        expected = {
            "mimetype":
                "5ab5230b5af04f78947736bf8dd1a269aa684e234f7f4a392efb85289d1655c2",
            "version.xml":
                "e4c5e60e84f7a0f756639719bd5acc70bd7f17dc81c23ef33160cc6440b5b13d",
            "Contents/header.xml":
                "bda2a5b38f91455930b35932eff6d02de858904b64833fd8a2bfd295e6edc3ac",
            "Contents/section0.xml":
                "e4392aae938c016ac26d19c6f76605163c3cca4a6baa7f9e82531a114fc6d4b3",
            "Preview/PrvText.txt":
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "settings.xml":
                "677fc367cfa775597d38d4e3fdeefe67d74d5129b13c9d0e6552c28e65345756",
            "META-INF/container.rdf":
                "0cfd814c20595c841e48e62fbf7591829f13c177fa92af634c8199f85ecf3a89",
            "Contents/content.hpf":
                "3b6fa2ec22d6a432f33379fae7695a73b717bd919ec1c21587150d68f9cdc27b",
            "META-INF/container.xml":
                "5109d3a9249ec1058177fedab574c5d9616058aa92ebefcd33249ebb36a20f61",
            "META-INF/manifest.xml":
                "2b4b155c1bb6a9ccc212fef113c4831d2f558e67cf1260eb314ce54f26fd32ea",
        }
        actual = {part.name: hashlib.sha256(part.bytes()).hexdigest()
                  for part in W.blank_package().parts}
        assert actual == expected

    def test_matches_its_committed_inventory(self, tmp_path):
        committed = os.path.join(ENGINE, "references",
                                 "owpml-blank-inventory.json")
        if not os.path.exists(committed):
            pytest.skip("engine/references/owpml-blank-inventory.json absent")
        import json
        with open(committed, encoding="utf-8") as handle:
            reference = json.load(handle)
        out = tmp_path / "blank-document.hwpx"
        W.blank_package().write(out)
        fresh = hwpx_inventory.collect([out])
        assert fresh["summary"] == reference["summary"]
        assert fresh["elements"] == reference["elements"]
        assert fresh["members"].keys() == reference["members"].keys()

    def test_inventory_of_the_blank_is_a_subset_of_the_corpus_surface(
            self, tmp_path):
        """A new document must not invent elements the corpus never showed."""
        if not CORPUS_FILES:
            pytest.skip("form corpus not present on this machine")
        out = tmp_path / "blank.hwpx"
        W.blank_package().write(out)
        blank = hwpx_inventory.collect([out])
        corpus = hwpx_inventory.collect(CORPUS_FILES)
        unknown = set(blank["elements"]) - set(corpus["elements"])
        assert unknown == set(), sorted(unknown)


# --------------------------------------------------------------------------
# the serializer itself
# --------------------------------------------------------------------------

class TestSerializer:

    def test_empty_element_form_survives(self):
        source = W.XML_DECLARATION + b'<r><a/><b></b><c x="1"/></r>'
        assert W.parse_xml_part(source).tobytes() == source

    def test_unused_namespace_declarations_survive(self):
        source = (W.XML_DECLARATION
                  + b'<a:r xmlns:a="urn:a" xmlns:unused="urn:z"><a:c/></a:r>')
        assert W.parse_xml_part(source).tobytes() == source

    def test_attribute_order_survives(self):
        source = W.XML_DECLARATION + b'<r z="1" a="2" m="3"/>'
        part = W.parse_xml_part(source)
        assert part.root.attr_names() == ["z", "a", "m"]
        assert part.tobytes() == source

    def test_per_element_namespace_declaration_stays_where_it_was(self):
        source = (W.XML_DECLARATION
                  + b'<r xmlns:a="urn:a"><a:c xmlns:b="urn:b"><b:d/></a:c></r>')
        assert W.parse_xml_part(source).tobytes() == source

    def test_entities_round_trip(self):
        source = W.XML_DECLARATION + b'<r a="x&amp;y">1 &lt; 2 &amp; 3 &gt; 0</r>'
        assert W.parse_xml_part(source).tobytes() == source

    def test_namespace_scope_resolves_prefixes(self):
        part = W.parse_xml_part(
            W.XML_DECLARATION + b'<r xmlns:a="urn:a"><a:c/></r>')
        child = part.root.children[0]
        assert W.qualified_name(part, child) == "{urn:a}c"
        assert W.namespace_scope(part)["a"] == "urn:a"

    def test_iter_with_scope_matches_namespace_scope(self):
        part = W.parse_xml_part(
            W.XML_DECLARATION
            + b'<r xmlns:a="urn:a"><a:c xmlns:b="urn:b"><b:d/></a:c></r>')
        for node, scope in W.iter_with_scope(part):
            assert scope == W.namespace_scope(part, node)

    def test_cr_in_text_is_normalized_and_named(self):
        source = W.XML_DECLARATION + b"<r>a\r\nb</r>"
        part = W.parse_xml_part(source)
        assert part.source_had_cr is True
        assert part.tobytes() != source
        assert part.root.text == "a\nb"

    def test_rejects_a_package_without_the_mimetype_sentinel(self, tmp_path):
        broken = tmp_path / "broken.hwpx"
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("Contents/header.xml", W.XML_DECLARATION + b"<h/>")
        with pytest.raises(W.HwpxWriteError):
            W.HwpxPackage.read(broken)

    def test_compression_level_is_recovered_from_the_flag_bits(self):
        package = W.blank_package()
        header = package.part("Contents/header.xml")
        assert header.compress_type == zipfile.ZIP_DEFLATED
        assert header.compresslevel == W.HANCOM_DEFLATE_LEVEL
        assert package.part("mimetype").compresslevel is None


class TestElementTreeBridge:
    """xml_backend edits ElementTree trees; its output must stay canonical."""

    @corpus_required
    def test_elementtree_reserialization_matches_the_source(self):
        """Measured: 81 of 96 corpus parts survive the ElementTree round trip.

        The 12 misses are all ``META-INF/container.rdf``, whose per-element
        ``xmlns:ns0`` declarations ElementTree hoists to the root and renames;
        the other 3 are the CR parts.  ``xml_backend`` parses header, sections,
        content.hpf and manifest.xml — never container.rdf — so on the parts it
        can actually write, only the CR cases miss.
        """
        edited_members = ("Contents/header.xml", "Contents/content.hpf",
                          "META-INF/manifest.xml")
        total = identical = 0
        for path in CORPUS_FILES:
            slug = _slug(path)
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if not (name in edited_members
                            or name.startswith("Contents/section")):
                        continue
                    data = archive.read(name)
                    tree = xml_backend.parse_xml(data)
                    out = W.canonical_from_elementtree(
                        tree.getroot(), W.root_ns_declarations(data))
                    total += 1
                    if out == data:
                        identical += 1
                    else:
                        assert (slug, name) in CR_PARTS, (slug, name)
        assert total == 48
        assert identical == 48 - len(CR_PARTS)

    @corpus_required
    def test_xml_backend_save_writes_the_hancom_declaration(self, tmp_path):
        source = CORPUS_FILES[0]
        document = xml_backend.HwpxDocument(source)
        name = sorted(document.sections)[0]
        document.dirty.add(name)
        out = tmp_path / "saved.hwpx"
        document.save(out)
        with zipfile.ZipFile(out) as archive:
            written = archive.read(name)
        assert written.startswith(W.XML_DECLARATION)
        assert b"<?xml version='1.0'" not in written

    @corpus_required
    def test_xml_backend_save_keeps_every_namespace_declaration(self, tmp_path):
        source = CORPUS_FILES[0]
        document = xml_backend.HwpxDocument(source)
        name = sorted(document.sections)[0]
        document.dirty.add(name)
        out = tmp_path / "saved.hwpx"
        document.save(out)
        with zipfile.ZipFile(source) as archive:
            expected = W.root_ns_declarations(archive.read(name))
        with zipfile.ZipFile(out) as archive:
            actual = W.root_ns_declarations(archive.read(name))
        assert actual == expected
        assert len(expected) == 15

    @corpus_required
    def test_xml_backend_save_is_byte_identical_when_nothing_changed(
            self, tmp_path):
        """An untouched-but-reserialized section must come back unchanged."""
        source = next(path for path in CORPUS_FILES
                      if all((_slug(path), member) not in CR_PARTS
                             for member in ("Contents/section0.xml",)))
        document = xml_backend.HwpxDocument(source)
        name = sorted(document.sections)[0]
        document.dirty.add(name)
        out = tmp_path / "saved.hwpx"
        document.save(out)
        with zipfile.ZipFile(source) as left, zipfile.ZipFile(out) as right:
            assert right.read(name) == left.read(name)


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

@corpus_required
class TestInventory:

    def test_matches_the_committed_reference(self):
        committed = os.path.join(ENGINE, "references", "owpml-inventory.json")
        if not os.path.exists(committed):
            pytest.skip("engine/references/owpml-inventory.json not present")
        import json
        with open(committed, encoding="utf-8") as handle:
            reference = json.load(handle)
        fresh = hwpx_inventory.collect(CORPUS_FILES)
        assert fresh["summary"] == reference["summary"]
        assert set(fresh["elements"]) == set(reference["elements"])

    def test_records_no_values(self):
        """The inventory must never carry corpus content into the repo."""
        import json
        payload = hwpx_inventory.collect(CORPUS_FILES[:1])
        text = json.dumps(payload, ensure_ascii=False)
        assert "lastsaveby" not in text or '"lastsaveby"' not in text.split(
            '"attributes"')[0]
        for record in payload["elements"].values():
            for attribute in record["attributes"].values():
                assert set(attribute) == {"count", "forms"}
                assert isinstance(attribute["forms"], int)

    def test_the_writer_emits_every_element_the_inventory_found(self):
        """Completeness, stated as the round trip rather than a hand-kept list."""
        inventory = hwpx_inventory.collect(CORPUS_FILES)
        emitted = set()
        for path in CORPUS_FILES:
            package = W.HwpxPackage.read(path)
            for part in package.parts:
                if not part.is_xml:
                    continue
                for node in W.parse_xml_part(part.bytes()).root.iter():
                    emitted.add(node.qname)
        assert emitted == set(inventory["elements"])
        assert len(emitted) == inventory["summary"]["distinct_elements"]
