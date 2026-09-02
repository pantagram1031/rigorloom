"""E3.x — tidy_hwpx.py / preedit.py archive assembly routed through hwpx_write.

Both scripts used to reassemble their output archives with a bare
``zipfile.ZipFile(..., "w", zipfile.ZIP_DEFLATED)`` — default deflate level 6,
general-purpose flag bits 0, whatever ``zipfile`` happens to pick for
stored/deflated per member. ``tidy_hwpx._write_hwpx`` and
``preedit._write_zip`` now both delegate to ``hwpx_write.write_members``, so
their output carries the Hancom archive shape measured in
``engine/references/owpml-writer-notes.md`` §2: member metadata
(date_time 1980-01-01, create_system 11), the stored/deflated split, deflate
level 2 / flag bits 0x4 for deflated members.

Unlike the canonical writer's round trip (``test_hwpx_roundtrip.py``), this
seam never parses or re-serializes XML — it writes whatever bytes the caller
hands it — so an identity edit (unchanged content, same member set) is a
*pure* archive-metadata change: every member byte-identical, every member
CRC unchanged, no XML-canonicalization loss (the CR_PARTS caveat in
``owpml-writer-notes.md`` does not apply here). Archive-container bytes still
differ on 2 of 12 forms, matching the known non-reproducible-deflate-encoding
case in owpml-writer-notes.md §5 (member CRC matches; compressed length
differs by a few bytes on one large section).
"""
import os
import re
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

from test_hwpx_roundtrip import (  # noqa: E402
    CORPUS_FILES, SLUGS, corpus_required, _slug)

import hwpx_inventory  # noqa: E402
import hwpx_write as W  # noqa: E402
import preedit  # noqa: E402
import tidy_hwpx  # noqa: E402


#: Measured: writing every corpus form's members back out unchanged through
#: each script's writer seam is 132/132 member-byte-identical and
#: 132/132 CRC-equal (no XML reparse happens on this path, so the CR_PARTS
#: caveat that applies to the canonical writer's own round trip does not
#: apply here). Archive-container bytes match source on 10/12 forms; the
#: other 2 (kstartup-jiwon-sincheongseo-saeopgyehoekseo,
#: saeopja-deungnok-sinchengseo) differ only in deflate encoding of one large
#: section — member CRC still matches, matching owpml-writer-notes.md §5.
EXPECTED_TOTAL_MEMBERS = 132
NON_REPRODUCIBLE_DEFLATE = {
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo",
    "saeopja-deungnok-sinchengseo",
}


def _read_all(path):
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}
        crc = {i.filename: i.CRC for i in zin.infolist()}
    return names, contents, crc


class _InfoStub:
    """Stand-in for zipfile.ZipInfo carrying only what preedit._write_zip reads."""
    def __init__(self, filename):
        self.filename = filename


def _tidy_write(out_path, names, contents):
    tidy_hwpx._write_hwpx(out_path, names, contents)


def _preedit_write(out_path, names, contents):
    preedit._write_zip(out_path, [_InfoStub(n) for n in names], contents)


WRITERS = [
    pytest.param(_tidy_write, id="tidy_hwpx"),
    pytest.param(_preedit_write, id="preedit"),
]


# --------------------------------------------------------------------------
# identity edit: member-CRC equality + byte identity, per form
# --------------------------------------------------------------------------

@corpus_required
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("path", CORPUS_FILES, ids=SLUGS)
def test_identity_write_preserves_every_member(tmp_path, path, writer):
    slug = _slug(path)
    names, contents, src_crc = _read_all(path)
    out = tmp_path / "out.hwpx"
    writer(out, names, dict(contents))

    with zipfile.ZipFile(out) as zout:
        assert zout.namelist() == names
        for name in names:
            assert zout.read(name) == contents[name], (slug, name)
            assert zout.getinfo(name).CRC == src_crc[name], (slug, name)
            assert zout.getinfo(name).date_time == (1980, 1, 1, 0, 0, 0)
            assert zout.getinfo(name).create_system == 11
            if W.default_compress_type(name) == zipfile.ZIP_DEFLATED:
                assert zout.getinfo(name).flag_bits == 0x4, (slug, name)
            else:
                assert zout.getinfo(name).flag_bits == 0, (slug, name)

    archive_identical = out.read_bytes() == open(path, "rb").read()
    if slug in NON_REPRODUCIBLE_DEFLATE:
        assert not archive_identical, (
            slug + " was expected to differ only in deflate encoding — "
            "if this now matches, tighten NON_REPRODUCIBLE_DEFLATE and the "
            "module docstring instead of leaving this assertion stale")
    else:
        assert archive_identical, slug


@corpus_required
@pytest.mark.parametrize("writer", WRITERS)
def test_identity_write_total_member_count_is_what_was_measured(tmp_path, writer):
    total = 0
    for path in CORPUS_FILES:
        names, contents, _crc = _read_all(path)
        out = tmp_path / (_slug(path) + ".hwpx")
        writer(out, names, dict(contents))
        with zipfile.ZipFile(out) as zout:
            total += len(zout.namelist())
    assert total == EXPECTED_TOTAL_MEMBERS


# --------------------------------------------------------------------------
# content edit: the change lands, and only the change
# --------------------------------------------------------------------------

def _edit_one_text_run(section_bytes):
    """Append one ASCII char to the first <hp:t> run's text — smallest
    well-formed content edit; keeps the member valid UTF-8 XML."""
    text = section_bytes.decode("utf-8")
    m = re.search(r'(<[A-Za-z0-9]+:t>)([^<]*)(</[A-Za-z0-9]+:t>)', text)
    assert m, "no <*:t> text run found to edit"
    edited = text[:m.end(2)] + "X" + text[m.end(2):]
    return edited.encode("utf-8")


@corpus_required
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("path", CORPUS_FILES, ids=SLUGS)
def test_content_edit_changes_only_the_edited_member(tmp_path, path, writer):
    slug = _slug(path)
    names, contents, _crc = _read_all(path)
    section_name = next(n for n in names if n.startswith("Contents/section"))
    edited = dict(contents)
    edited[section_name] = _edit_one_text_run(contents[section_name])
    assert edited[section_name] != contents[section_name]

    out = tmp_path / "out.hwpx"
    writer(out, names, edited)

    with zipfile.ZipFile(out) as zout:
        assert zout.namelist() == names
        for name in names:
            if name == section_name:
                assert zout.read(name) == edited[section_name], slug
                assert zout.read(name) != contents[name], slug
            else:
                assert zout.read(name) == contents[name], (slug, name)


# --------------------------------------------------------------------------
# inventory guard: routing does not widen the emitted qname surface
# --------------------------------------------------------------------------

@corpus_required
def test_content_edit_stays_within_the_committed_inventory(tmp_path):
    inventory = hwpx_inventory.collect(CORPUS_FILES)
    known = set(inventory["elements"])
    assert known, "inventory collection returned nothing"

    for i, path in enumerate(CORPUS_FILES[:3]):  # representative subset — inventory itself is corpus-wide
        names, contents, _crc = _read_all(path)
        section_name = next(n for n in names if n.startswith("Contents/section"))
        edited = dict(contents)
        edited[section_name] = _edit_one_text_run(contents[section_name])

        for j, writer in enumerate((_tidy_write, _preedit_write)):
            out_path = tmp_path / ("guard-%d-%d.hwpx" % (i, j))
            writer(out_path, names, dict(edited))
            package = W.HwpxPackage.read(out_path)
            for part in package.xml_parts():
                for node in W.parse_xml_part(part.bytes()).root.iter():
                    assert node.qname in known, (
                        _slug(path), part.name, node.qname)
