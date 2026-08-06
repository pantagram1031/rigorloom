"""_patch_parapr_block regression tests (offline, no live-fixture dependency).

Covers the breakSetting keepWithNext/widowOrphan patch path in isolation with
synthetic paraPr XML — unlike test_tidy_hwpx.py, these don't need the real
report-aliasing-sampling fixture, so they always run.

`python -m pytest tests/test_patch_parapr_block.py -q`.
"""
import os
import re
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import tidy_hwpx  # noqa: E402


def _breaksetting_attrs(block_xml):
    m = re.search(r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", block_xml)
    assert m is not None, f"no breakSetting tag found in {block_xml!r}"
    return m.group(1)


# ── breakSetting present, missing the target attribute ──────────────────

BLOCK_BREAKSETTING_NO_KWN_NO_WIDOW = (
    '<hh:paraPr id="5" tabPrIDRef="0">'
    '<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>'
    '<hh:breakSetting breakLatinWord="KEEP_WORD" lineWrap="BREAK"/>'
    '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
    '</hh:paraPr>'
)


def test_breaksetting_missing_keep_with_next_attr_gets_added():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_BREAKSETTING_NO_KWN_NO_WIDOW, new_id=99, keep_with_next="1")
    attrs = _breaksetting_attrs(patched)
    assert tidy_hwpx._attr_value(attrs, "keepWithNext") == "1"
    # untouched sibling attr preserved
    assert "breakLatinWord=\"KEEP_WORD\"" in patched


def test_breaksetting_missing_widow_orphan_attr_gets_added():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_BREAKSETTING_NO_KWN_NO_WIDOW, new_id=99, widow_orphan="1")
    attrs = _breaksetting_attrs(patched)
    assert tidy_hwpx._attr_value(attrs, "widowOrphan") == "1"


def test_breaksetting_missing_both_attrs_both_get_added():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_BREAKSETTING_NO_KWN_NO_WIDOW, new_id=99,
        keep_with_next="1", widow_orphan="1")
    attrs = _breaksetting_attrs(patched)
    assert tidy_hwpx._attr_value(attrs, "keepWithNext") == "1"
    assert tidy_hwpx._attr_value(attrs, "widowOrphan") == "1"


# ── breakSetting present, attribute already there (existing REPLACE path) ─

BLOCK_BREAKSETTING_WITH_ATTRS = (
    '<hh:paraPr id="5">'
    '<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>'
    '<hh:breakSetting widowOrphan="0" keepWithNext="0"/>'
    '</hh:paraPr>'
)


def test_breaksetting_existing_attrs_still_replaced():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_BREAKSETTING_WITH_ATTRS, new_id=99,
        keep_with_next="1", widow_orphan="1")
    attrs = _breaksetting_attrs(patched)
    assert tidy_hwpx._attr_value(attrs, "keepWithNext") == "1"
    assert tidy_hwpx._attr_value(attrs, "widowOrphan") == "1"


# ── breakSetting element entirely absent ─────────────────────────────────

BLOCK_NO_BREAKSETTING = (
    '<hh:paraPr id="5" tabPrIDRef="0">'
    '<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>'
    '<hh:heading type="NONE" idRef="0" level="0"/>'
    '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
    '</hh:paraPr>'
)


def test_missing_breaksetting_element_gets_created():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_NO_BREAKSETTING, new_id=99, keep_with_next="1", widow_orphan="1")
    m = re.search(r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", patched)
    assert m is not None, f"breakSetting element was not created: {patched!r}"
    assert tidy_hwpx._attr_value(m.group(1), "keepWithNext") == "1"
    assert tidy_hwpx._attr_value(m.group(1), "widowOrphan") == "1"
    # sibling elements untouched
    assert "<hh:heading" in patched
    assert "<hh:autoSpacing" in patched
    # new element uses the same namespace prefix as its siblings (hh)
    assert re.search(r"<hh:breakSetting\b", patched)


def test_missing_breaksetting_element_no_heading_falls_back_to_after_align():
    block = (
        '<hh:paraPr id="5">'
        '<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>'
        '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
        '</hh:paraPr>'
    )
    patched = tidy_hwpx._patch_parapr_block(block, new_id=99, keep_with_next="1")
    m = re.search(r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", patched)
    assert m is not None
    assert tidy_hwpx._attr_value(m.group(1), "keepWithNext") == "1"
    # inserted after align, before autoSpacing
    assert patched.index("breakSetting") > patched.index("align")
    assert patched.index("breakSetting") < patched.index("autoSpacing")


# ── single-quoted attribute values ───────────────────────────────────────

BLOCK_SINGLE_QUOTED = (
    "<hh:paraPr id='5'>"
    "<hh:align horizontal='JUSTIFY' vertical='BASELINE'/>"
    "<hh:breakSetting widowOrphan='0' keepWithNext='0'/>"
    "</hh:paraPr>"
)


def test_single_quoted_breaksetting_attrs_get_replaced():
    patched = tidy_hwpx._patch_parapr_block(
        BLOCK_SINGLE_QUOTED, new_id=99, keep_with_next="1", widow_orphan="1")
    assert "keepWithNext='1'" in patched
    assert "widowOrphan='1'" in patched
    # quote style preserved (single), not converted to double
    assert 'keepWithNext="1"' not in patched


def test_single_quoted_id_still_replaced():
    patched = tidy_hwpx._patch_parapr_block(BLOCK_SINGLE_QUOTED, new_id=42)
    assert "id='42'" in patched or 'id="42"' in patched


# ── idempotence: patching an already-patched (attr-added) block twice ────

def test_idempotent_reapplying_same_patch_is_byte_stable_after_first_add():
    once = tidy_hwpx._patch_parapr_block(
        BLOCK_BREAKSETTING_NO_KWN_NO_WIDOW, new_id=99,
        keep_with_next="1", widow_orphan="1")
    twice = tidy_hwpx._patch_parapr_block(
        once, new_id=99, keep_with_next="1", widow_orphan="1")
    assert once == twice


def test_idempotent_reapplying_after_element_creation_is_byte_stable():
    once = tidy_hwpx._patch_parapr_block(
        BLOCK_NO_BREAKSETTING, new_id=99, keep_with_next="1", widow_orphan="1")
    twice = tidy_hwpx._patch_parapr_block(
        once, new_id=99, keep_with_next="1", widow_orphan="1")
    assert once == twice
