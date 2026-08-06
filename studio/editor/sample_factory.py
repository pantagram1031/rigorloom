"""Create a small, fully synthetic HWPX fixture for unit tests.

The browser PoC ships a separate sanitized Hancom-generated sample for render
measurements.  This stdlib-only fixture keeps tests independent of Hancom.
"""
from __future__ import annotations

import argparse
import os
import re
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"


def write_synthetic_hwpx(path: Path) -> Path:
    """Write a non-personal HWPX with one safe and one equation paragraph."""
    header = (
        f'<hh:head xmlns:hh="{HH}"><hh:refList>'
        '<hh:paraProperties itemCnt="1"><hh:paraPr id="0">'
        '<hh:align horizontal="JUSTIFY"/></hh:paraPr></hh:paraProperties>'
        '<hh:charProperties itemCnt="1"><hh:charPr id="0" height="1000"/>'
        '</hh:charProperties></hh:refList></hh:head>'
    ).encode("utf-8")
    section = (
        f'<hp:sec xmlns:hp="{HP}">'
        '<hp:p id="1" paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:secPr><hp:pagePr width="59527" height="84189"><hp:margin '
        'left="4251" right="4251" top="5669" bottom="5669" header="0" '
        'footer="0" gutter="0"/></hp:pagePr></hp:secPr>'
        '<hp:t>Studio editor synthetic sample</hp:t></hp:run></hp:p>'
        '<hp:p id="2" paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>Editable sample paragraph.</hp:t></hp:run></hp:p>'
        '<hp:p id="3" paraPrIDRef="0"><hp:run charPrIDRef="0">'
        '<hp:t>Equation hazard: </hp:t><hp:equation id="10">'
        '<hp:script>E={mc^2}</hp:script></hp:equation>'
        '<hp:t/></hp:run><hp:run charPrIDRef="0">'
        '<hp:t> is protected.</hp:t></hp:run></hp:p>'
        '</hp:sec>'
    ).encode("utf-8")
    content = (
        f'<opf:package xmlns:opf="{OPF}"><opf:metadata>'
        '<opf:title>Studio editor synthetic sample</opf:title>'
        '<opf:meta name="creator" content="text">rigorloom-sample</opf:meta>'
        '</opf:metadata><opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        '</opf:manifest><opf:spine><opf:itemref idref="header"/>'
        '<opf:itemref idref="section0"/></opf:spine></opf:package>'
    ).encode("utf-8")
    manifest = (
        f'<manifest:manifest xmlns:manifest="{ODF_MANIFEST}">'
        '<manifest:file-entry manifest:media-type="application/xml" '
        'manifest:full-path="Contents/header.xml"/>'
        '<manifest:file-entry manifest:media-type="application/xml" '
        'manifest:full-path="Contents/section0.xml"/>'
        '</manifest:manifest>'
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("Contents/header.xml", header)
        archive.writestr("Contents/section0.xml", section)
        archive.writestr("Contents/content.hpf", content)
        archive.writestr("META-INF/manifest.xml", manifest)
        archive.writestr("BinData/untouched.bin", b"\x00unchanged\xff")
    return path


_TEXT_MEMBERS = (".xml", ".hpf", ".txt", ".rdf")


def sanitize_hancom_sample(source: Path, output: Path, *, title: str) -> Path:
    """Copy a generic form-derived HWPX while removing author metadata.

    This helper exists only to reproduce the checked-in sanitized PoC samples.
    It never edits the supplied source in place.
    """
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise ValueError("source and output must differ")
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) != len({item.filename for item in infos}):
            raise ValueError("sample has duplicate ZIP member names")
        members = {item.filename: archive.read(item) for item in infos}
    if "Contents/content.hpf" not in members:
        raise ValueError("sample has no Contents/content.hpf metadata")
    metadata = members["Contents/content.hpf"].decode("utf-8")
    private_values = set(re.findall(
        r'<opf:meta\b[^>]*\bname="(?:creator|lastsaveby)"[^>]*>(.*?)</opf:meta>',
        metadata,
        flags=re.DOTALL,
    ))
    safe_title = escape(title)
    metadata = re.sub(
        r"(<opf:title>).*?(</opf:title>)",
        lambda match: match.group(1) + safe_title + match.group(2),
        metadata,
        flags=re.DOTALL,
    )
    replacements = {
        "creator": "rigorloom-sample",
        "lastsaveby": "rigorloom-sample",
        "CreatedDate": "2026-01-01T00:00:00Z",
        "ModifiedDate": "2026-01-01T00:00:00Z",
        "date": "2026-01-01",
    }
    for name, value in replacements.items():
        metadata = re.sub(
            rf'(<opf:meta\b[^>]*\bname="{re.escape(name)}"[^>]*>).*?(</opf:meta>)',
            lambda match, replacement=value: match.group(1) + replacement + match.group(2),
            metadata,
            flags=re.DOTALL,
        )
    members["Contents/content.hpf"] = metadata.encode("utf-8")
    if "Preview/PrvText.txt" in members:
        members["Preview/PrvText.txt"] = (
            f"{title}\n\nThis is a non-personal document generated for the "
            "Rigorloom Studio editor spike.\n"
        ).encode("utf-8")

    forbidden = {value for value in private_values if value.strip()}
    for name, payload in members.items():
        if not name.lower().endswith(_TEXT_MEMBERS):
            continue
        text = payload.decode("utf-8", errors="replace")
        leaked = sorted(value for value in forbidden if value in text)
        if leaked:
            raise ValueError(f"sample sanitization failed in {name}: {leaked}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".hwpx", dir=str(output.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w") as archive:
            for info in infos:
                archive.writestr(info, members[info.filename])
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or sanitize Studio editor samples")
    sub = parser.add_subparsers(dest="command", required=True)
    synthetic = sub.add_parser("synthetic")
    synthetic.add_argument("output", type=Path)
    sanitize = sub.add_parser("sanitize")
    sanitize.add_argument("source", type=Path)
    sanitize.add_argument("output", type=Path)
    sanitize.add_argument("--title", required=True)
    args = parser.parse_args(argv)
    if args.command == "synthetic":
        result = write_synthetic_hwpx(args.output)
    else:
        result = sanitize_hancom_sample(args.source, args.output, title=args.title)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
