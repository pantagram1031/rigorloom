"""Shared synthetic HWPX fixture builder for transform-module tests."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import zipfile


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
IMAGE = b"\x89PNG\r\n\x1a\nsynthetic-image"


def _p(identifier: int, text: str, extra: str = "") -> str:
    return (
        f'<hp:p id="{identifier}" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{escape(text)}</hp:t>{extra}</hp:run>'
        "</hp:p>"
    )


def _cell(row: int, col: int, value: str, extra: str = "") -> str:
    return (
        '<hp:tc name="" header="0" borderFillIDRef="1">'
        '<hp:subList><hp:p id="0" paraPrIDRef="0" styleIDRef="0">'
        f'<hp:run charPrIDRef="0"><hp:t>{escape(value)}</hp:t>{extra}</hp:run>'
        "</hp:p></hp:subList>"
        f'<hp:cellAddr rowAddr="{row}" colAddr="{col}"/>'
        '<hp:cellSpan rowSpan="1" colSpan="1"/>'
        "</hp:tc>"
    )


def picture_control() -> str:
    """Return a picture control suitable for a paragraph or table cell."""
    return (
        f'<hp:pic id="30"><hc:img xmlns:hc="{HC}" '
        'binaryItemIDRef="image1"/></hp:pic>'
    )


def equation_control(script: str = "x over y", *, identifier: int = 10) -> str:
    """Return an equation control with a synthetic HwpEqn script."""
    return (
        f'<hp:equation id="{identifier}"><hp:script>{escape(script)}</hp:script>'
        "</hp:equation>"
    )


def nested_table_control() -> str:
    """Return a one-row table for nesting in the final outer-table cell."""
    return (
        '<hp:tbl id="21" rowCnt="1" colCnt="2" borderFillIDRef="1">'
        '<hp:tr>' + _cell(0, 0, "Inner A") + _cell(0, 1, "Inner B")
        + "</hp:tr></hp:tbl>"
    )


def write_hwpx(
    path: Path,
    *,
    body: str = "Alpha body.",
    variable_cell: str = "2",
    extra_structure: bool = False,
    picture_in_cell: bool = False,
    equation_in_cell: bool = False,
    nested_table: bool = False,
    extra_table_row: bool = False,
    inline_equation_script: str = "x over y",
) -> Path:
    header = (
        f'<hh:head xmlns:hh="{HH}">'
        '<hh:charProperties><hh:charPr id="0" height="1000">'
        '<hh:bold/></hh:charPr></hh:charProperties>'
        '<hh:paraProperties><hh:paraPr id="0">'
        '<hh:align horizontal="JUSTIFY"/></hh:paraPr></hh:paraProperties>'
        '<hh:borderFills><hh:borderFill id="1"/></hh:borderFills>'
        '<hh:binDataItems><hh:binData id="image1" '
        'href="BinData/image1.png"/></hh:binDataItems>'
        "</hh:head>"
    )
    first_cell_extra = ""
    if picture_in_cell:
        first_cell_extra += picture_control()
    if equation_in_cell:
        first_cell_extra += equation_control("cell sub 1", identifier=11)
    final_cell_extra = nested_table_control() if nested_table else ""
    extra_row = (
        '<hp:tr>' + _cell(2, 0, "Extra A") + _cell(2, 1, "Extra B")
        + "</hp:tr>"
        if extra_table_row else ""
    )
    table = (
        f'<hp:tbl id="20" rowCnt="{3 if extra_table_row else 2}" '
        'colCnt="2" borderFillIDRef="1">'
        '<hp:tr>' + _cell(0, 0, "A", first_cell_extra)
        + _cell(0, 1, "B") + "</hp:tr>"
        '<hp:tr>' + _cell(1, 0, "C")
        + _cell(1, 1, variable_cell, final_cell_extra) + "</hp:tr>"
        + extra_row + "</hp:tbl>"
    )
    equation = equation_control(inline_equation_script)
    picture = picture_control()
    extra = '<hp:ctrl type="extra"/>' if extra_structure else ""
    section = (
        f'<hp:section xmlns:hp="{HP}">'
        '<hp:secPr id="1"><hp:pagePr width="59528" height="84188"/></hp:secPr>'
        + _p(1, "Ⅰ. Introduction")
        + _p(2, body, extra)
        + (
            '<hp:p id="3" paraPrIDRef="0" styleIDRef="0">'
            '<hp:run charPrIDRef="0"><hp:t>Before </hp:t>'
            + equation + '<hp:t> after.</hp:t></hp:run></hp:p>'
        )
        + (
            '<hp:p id="4" paraPrIDRef="0" styleIDRef="0">'
            '<hp:run charPrIDRef="0">' + table + "</hp:run></hp:p>"
        )
        + _p(5, "Table 1. Measurements")
        + (
            '<hp:p id="6" paraPrIDRef="0" styleIDRef="0">'
            '<hp:run charPrIDRef="0">' + picture + "</hp:run></hp:p>"
        )
        + _p(7, "Figure 1. Plot")
        + _p(8, "Omega.")
        + "</hp:section>"
    )
    content_hpf = (
        '<opf:package xmlns:opf="urn:opf"><opf:manifest>'
        '<opf:item id="image1" href="BinData/image1.png" media-type="image/png"/>'
        "</opf:manifest></opf:package>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)
        archive.writestr("Contents/content.hpf", content_hpf)
        archive.writestr("BinData/image1.png", IMAGE)
    return path
