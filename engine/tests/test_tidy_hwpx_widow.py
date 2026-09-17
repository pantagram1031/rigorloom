"""T16: typeset defaults preserve the form's widowOrphan unless build.yaml opts in.

Synthetic hwpx only — no live fixture, no COM."""
import os
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_report  # noqa: E402
import fill_report as fr  # noqa: E402
import tidy_hwpx  # noqa: E402


def _breaksetting_attrs(defs, pid):
    m = tidy_hwpx.re.search(
        r"<" + tidy_hwpx.NS + r":breakSetting\b([^/>]*)/>", defs[pid][2])
    assert m is not None
    return {
        "widowOrphan": tidy_hwpx._attr_value(m.group(1), "widowOrphan"),
        "keepWithNext": tidy_hwpx._attr_value(m.group(1), "keepWithNext"),
    }


def _header_defs(path):
    with zipfile.ZipFile(path) as z:
        header = z.read("Contents/header.xml").decode("utf-8")
    return tidy_hwpx._parapr_defs_by_id(header)


def _section_xml(path, name="Contents/section0.xml"):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def _build_body_hwpx(tmp_path, widow_orphan, name="body.hwpx"):
    """One body paragraph pointing at paraPr 0 with an explicit widowOrphan."""
    header = (
        '<hh:head><hh:refList><hh:fontfaces/><hh:borderFills/>'
        '<hh:charProperties itemCnt="1">'
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="0"/></hh:charPr>'
        '</hh:charProperties>'
        '<hh:paraProperties itemCnt="1">'
        '<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/>'
        f'<hh:breakSetting widowOrphan="{widow_orphan}" keepWithNext="0"/>'
        '</hh:paraPr>'
        '</hh:paraProperties>'
        '</hh:refList></hh:head>'
    )
    section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>본문 한 줄</hp:t></hp:run></hp:p>'
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
    return path


def _body_widow(path):
    defs = _header_defs(path)
    xml = _section_xml(path)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    pid = tidy_hwpx._attr_value(paras[0][4], "paraPrIDRef")
    return _breaksetting_attrs(defs, pid)["widowOrphan"]


def test_typeset_defaults_widow_orphan_0_stays_0(tmp_path):
    src = _build_body_hwpx(tmp_path, "0")
    result = tidy_hwpx.apply_typeset_defaults(src, [], out_path=src)
    assert result["ok"] is True
    assert result["patched"] == []
    assert _body_widow(src) == "0"


def test_typeset_defaults_widow_orphan_1_stays_1(tmp_path):
    src = _build_body_hwpx(tmp_path, "1")
    result = tidy_hwpx.apply_typeset_defaults(src, [], out_path=src)
    assert result["ok"] is True
    assert result["patched"] == []
    assert _body_widow(src) == "1"


def test_typeset_defaults_widow_orphan_true_forces_1_on_zero_form(tmp_path):
    src = _build_body_hwpx(tmp_path, "0")
    result = tidy_hwpx.apply_typeset_defaults(
        src, [], out_path=src, widow_orphan=True)
    assert result["ok"] is True
    assert result["patched"]
    assert all(r["widow_orphan"] is True for r in result["patched"])
    assert _body_widow(src) == "1"


def test_typeset_defaults_widow_orphan_false_forces_0_on_one_form(tmp_path):
    src = _build_body_hwpx(tmp_path, "1")
    result = tidy_hwpx.apply_typeset_defaults(
        src, [], out_path=src, widow_orphan=False)
    assert result["ok"] is True
    assert result["patched"]
    assert all(r["widow_orphan"] is False for r in result["patched"])
    assert _body_widow(src) == "0"


def test_build_yaml_widow_orphan_true_on_zero_form_yields_1(tmp_path):
    src = _build_body_hwpx(tmp_path, "0")
    yaml_path = tmp_path / "build.yaml"
    yaml_path.write_text("base_pt: 10\nwidow_orphan: true\n", encoding="utf-8")
    cfg = build_report.parse_build_yaml(yaml_path)
    assert cfg["widow_orphan"] == "true"
    flag = fr.read_widow_orphan(str(yaml_path))
    assert flag is True
    tidy_hwpx.apply_typeset_defaults(src, [], out_path=src, widow_orphan=flag)
    assert _body_widow(src) == "1"


def test_build_yaml_absent_widow_orphan_is_none(tmp_path):
    yaml_path = tmp_path / "build.yaml"
    yaml_path.write_text("base_pt: 10\n", encoding="utf-8")
    assert "widow_orphan" not in build_report.parse_build_yaml(yaml_path)
    assert fr.read_widow_orphan(str(yaml_path)) is None


def test_typeset_defaults_keep_with_next_clone_keeps_source_widow(tmp_path):
    """Heading clone for keepWithNext must not rewrite widowOrphan=0 to 1."""
    header = (
        '<hh:head><hh:refList><hh:fontfaces/><hh:borderFills/>'
        '<hh:charProperties itemCnt="1">'
        '<hh:charPr id="0" height="1000" textColor="#000000">'
        '<hh:fontRef hangul="0"/></hh:charPr>'
        '</hh:charProperties>'
        '<hh:paraProperties itemCnt="1">'
        '<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/>'
        '<hh:breakSetting widowOrphan="0" keepWithNext="0"/>'
        '</hh:paraPr>'
        '</hh:paraProperties>'
        '</hh:refList></hh:head>'
    )
    section = (
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>Ⅰ. 서 론</hp:t></hp:run></hp:p>'
        '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>본문</hp:t></hp:run></hp:p>'
    )
    path = tmp_path / "heading.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", section)
    tidy_hwpx.apply_typeset_defaults(path, ["Ⅰ. 서 론"], out_path=path)
    defs = _header_defs(path)
    xml = _section_xml(path)
    paras = tidy_hwpx._find_top_level_paragraphs_with_prattrs(xml)
    heading_pid = tidy_hwpx._attr_value(paras[0][4], "paraPrIDRef")
    body_pid = tidy_hwpx._attr_value(paras[1][4], "paraPrIDRef")
    heading = _breaksetting_attrs(defs, heading_pid)
    body = _breaksetting_attrs(defs, body_pid)
    assert heading["keepWithNext"] == "1"
    assert heading["widowOrphan"] == "0"
    assert body["keepWithNext"] == "0"
    assert body["widowOrphan"] == "0"
    assert heading_pid != body_pid
