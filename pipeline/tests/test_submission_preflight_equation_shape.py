# -*- coding: utf-8 -*-
"""Hancom-shaped hp:equation (sz/pos/outMargin/shapeComment + one script) is a WARN only on the native route."""
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import submission_preflight as sp  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402

HANCOM_EQUATION = (
    '<hp:equation id="1" numberingType="EQUATION" font="HancomEQN">'
    '<hp:sz width="6155" widthRelTo="ABSOLUTE" height="1327" heightRelTo="ABSOLUTE" protect="0"/>'
    '<hp:pos treatAsChar="1" vertRelTo="PARA" horzRelTo="PARA"/>'
    '<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
    '<hp:shapeComment>수식입니다.</hp:shapeComment>'
    '<hp:script>T_{0}= 2 pi sqrt{L/g}</hp:script></hp:equation>'
)
MINIMAL_EQUATION = '<hp:equation id="10"><hp:script>x over y</hp:script></hp:equation>'
ORPHAN_SCRIPT = '<hp:script>x</hp:script>'
EXTRA_CHILD = HANCOM_EQUATION.replace('</hp:equation>', '<hp:unknown/></hp:equation>')
EMPTY_SCRIPT = HANCOM_EQUATION.replace('T_{0}= 2 pi sqrt{L/g}', ' ')


def _hwpx(path: Path, control: str) -> Path:
    """A strict-spine package whose inline equation is replaced by ``control``."""
    write_hwpx(path)
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    section = items["Contents/section0.xml"].decode("utf-8")
    assert MINIMAL_EQUATION in section
    items["Contents/section0.xml"] = section.replace(MINIMAL_EQUATION, control).encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for name, data in items.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
    return path


def _native_receipt(ws: Path) -> None:
    p = ws / sp.document_evidence.RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema": "rigorloom/document-evidence/v1", "proof_grade": "hancom",
        "evidence_class": "native_render",
        "execution": {"backend": "native_hancom_windows", "state": "succeeded", "exit_code": 0},
    }), encoding="utf-8")


def test_hancom_shape_is_recognised_and_other_shapes_are_not(tmp_path):
    assert sp._hancom_shaped_equations(_hwpx(tmp_path / "ok.hwpx", HANCOM_EQUATION)) is True
    assert sp._hancom_shaped_equations(_hwpx(tmp_path / "orphan.hwpx", ORPHAN_SCRIPT)) is False
    assert sp._hancom_shaped_equations(_hwpx(tmp_path / "extra.hwpx", EXTRA_CHILD)) is False
    assert sp._hancom_shaped_equations(_hwpx(tmp_path / "empty.hwpx", EMPTY_SCRIPT)) is False
    assert sp._hancom_shaped_equations(_hwpx(tmp_path / "none.hwpx", "")) is False


def _ws(tmp_path: Path, control: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "output").mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(
        '---\nschema: rigorloom/pipeline/v0.6\ncanonical_output: "output/submission.hwpx"\n---\n', encoding="utf-8")
    (ws / "request.yaml").write_text('output_filename: "submission.hwpx"\n', encoding="utf-8")
    _hwpx(ws / "output" / "submission.hwpx", control)
    return ws


def _equation_p3(verdict) -> bool:
    return any(item["code"] == "P3" and "equation_script" in item["msg"] for item in verdict["hard"])


def test_native_route_downgrades_hancom_shape_to_warn(tmp_path):
    ws = _ws(tmp_path, HANCOM_EQUATION)
    _native_receipt(ws)
    verdict, _code = sp.check(ws)
    assert not _equation_p3(verdict), verdict
    assert any(item["code"] == "equation_diagnostic_strict_shape" for item in verdict["warn"]), verdict
    assert verdict.get("document_has_equations") is True


def test_without_native_receipt_hancom_shape_stays_p3(tmp_path):
    ws = _ws(tmp_path, HANCOM_EQUATION)
    verdict, code = sp.check(ws)
    assert code == 3 and _equation_p3(verdict), verdict


def test_native_route_keeps_p3_for_non_hancom_shape(tmp_path):
    ws = _ws(tmp_path, EXTRA_CHILD)
    _native_receipt(ws)
    verdict, code = sp.check(ws)
    assert code == 3 and _equation_p3(verdict), verdict


def test_native_route_keeps_p3_for_orphan_script(tmp_path):
    ws = _ws(tmp_path, ORPHAN_SCRIPT)
    _native_receipt(ws)
    verdict, code = sp.check(ws)
    assert code == 3 and _equation_p3(verdict), verdict
