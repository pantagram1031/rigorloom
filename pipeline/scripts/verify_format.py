# -*- coding: utf-8 -*-
"""verify_format.py — recompute-based format gate for an assembled .hwpx.

Reads <WS>/output/out.hwpx (a zip), parses Contents/header.xml, and measures
charPr font heights, charPr text colors, and paraPr line-spacing values. The
parser is namespace-agnostic: every element is matched by its XML local-name
(the part after '}'), so it does not care which hancom namespace prefix the
producer used.

Expectations come from --expect <json> or, failing that, from <WS>/build.yaml
(keys base_pt, line_spacing). Defaults: body 10pt (charPr height == 1000) and
160% line spacing. HWPX encodes a 10pt font as height="1000" (hundredths of a
point).

Exit 0 = pass (no HARD violations, or out.hwpx absent -> skipped).
Exit 3 = HARD violation(s). Exit 2 = usage error.

HARD rules:
  F1 no charPr with the expected body height exists at all
  F2 any charPr with a near-red text color (red text leaks a fill/edit marker)
WARN rules:
  W1 no paraPr carries the expected line-spacing value
  W2 distribution: share of charPr at the expected body height
  W3 stray bold: count of charPr carrying a bold child

LIMITATION (v1): heights/colors are counted across ALL charPr definitions in
header.xml; there is no anchor-scoped mapping of a charPr id to the body text
runs that reference it, so a title-only large height cannot yet be excluded
from the "body height present?" question. F1 only asserts the expected body
height EXISTS somewhere; it does not assert every body run uses it. This is a
presence/leak check, not a per-run conformance check.
"""
import sys, os, re, json, argparse, zipfile
import xml.etree.ElementTree as ET


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _iter(elem):
    yield elem
    for child in elem:
        yield from _iter(child)


def _is_near_red(color):
    """True if a #RRGGBB color reads as red: high R, low G and B."""
    if not color or not isinstance(color, str):
        return False
    m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", color.strip())
    if not m:
        return False
    r = int(m.group(1)[0:2], 16)
    g = int(m.group(1)[2:4], 16)
    b = int(m.group(1)[4:6], 16)
    return r >= 0xC8 and g <= 0x50 and b <= 0x50


def _read_header_xml(hwpx_path):
    with zipfile.ZipFile(hwpx_path) as z:
        name = None
        for cand in z.namelist():
            if cand.replace("\\", "/").lower().endswith("contents/header.xml"):
                name = cand
                break
        if name is None:
            return None
        return z.read(name)


def _load_expectations(ws, expect_path):
    exp = {"base_pt": 10, "line_spacing": 160}
    if expect_path and os.path.exists(expect_path):
        try:
            data = json.loads(open(expect_path, encoding="utf-8").read())
            if isinstance(data.get("base_pt"), (int, float)):
                exp["base_pt"] = int(data["base_pt"])
            if isinstance(data.get("line_spacing"), (int, float)):
                exp["line_spacing"] = int(data["line_spacing"])
        except Exception:
            pass
    else:
        build = os.path.join(ws, "build.yaml")
        if os.path.exists(build):
            text = open(build, encoding="utf-8", errors="ignore").read()
            m = re.search(r"(?m)^\s*base_pt:\s*(\d+)", text)
            if m:
                exp["base_pt"] = int(m.group(1))
            m = re.search(r"(?m)^\s*line_spacing:\s*(\d+)", text)
            if m:
                exp["line_spacing"] = int(m.group(1))
    exp["height"] = exp["base_pt"] * 100
    return exp


def check(ws, expect_path=None):
    hwpx = os.path.join(ws, "output", "out.hwpx")
    if not os.path.exists(hwpx):
        return {"ok": True, "workspace": ws, "checker": "verify_format", "skipped": True,
                "note": "output/out.hwpx not present (pre-assembly workspace)",
                "hard": [], "warn": [], "counts": {"hard": 0, "warn": 0},
                "verdict": "skipped"}, 0

    exp = _load_expectations(ws, expect_path)
    try:
        raw = _read_header_xml(hwpx)
    except (zipfile.BadZipFile, OSError) as exc:
        return {"ok": False, "error": f"cannot read out.hwpx: {exc}"}, 2
    if raw is None:
        return {"ok": False, "error": "Contents/header.xml not found in out.hwpx"}, 2
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"header.xml parse error: {exc}"}, 2

    heights = []
    red_runs = 0
    bold_runs = 0
    line_spacings = []
    for el in _iter(root):
        name = _local(el.tag)
        if name == "charPr":
            h = el.attrib.get("height")
            if h is not None:
                try:
                    heights.append(int(h))
                except ValueError:
                    pass
            if _is_near_red(el.attrib.get("textColor")):
                red_runs += 1
            if any(_local(c.tag) == "bold" for c in el):
                bold_runs += 1
        elif name == "lineSpacing":
            v = el.attrib.get("value")
            if v is not None:
                try:
                    line_spacings.append(int(v))
                except ValueError:
                    pass

    hard, warn = [], []
    body_h = exp["height"]
    n_body = sum(1 for h in heights if h == body_h)
    if n_body == 0:
        hard.append({"code": "F1", "msg": f"no charPr with expected body height {body_h} "
                     f"({exp['base_pt']}pt)", "at": f"heights={sorted(set(heights))[:12]}"})
    if red_runs > 0:
        hard.append({"code": "F2", "msg": "near-red text color present in charPr "
                     "(fill/edit-marker leak)", "at": f"x{red_runs}"})

    if exp["line_spacing"] not in line_spacings:
        warn.append({"code": "W1", "msg": f"expected line spacing {exp['line_spacing']}% not found",
                     "at": f"seen={sorted(set(line_spacings))[:12]}"})
    total_h = len(heights)
    share = (n_body / total_h) if total_h else 0.0
    warn.append({"code": "W2", "msg": "body-height charPr share",
                 "at": f"{n_body}/{total_h} = {share:.2f}"})
    if bold_runs > 0:
        warn.append({"code": "W3", "msg": "stray bold charPr", "at": f"x{bold_runs}"})

    verdict = {
        "ok": len(hard) == 0,
        "workspace": ws,
        "checker": "verify_format",
        "expected": {"base_pt": exp["base_pt"], "height": body_h, "line_spacing": exp["line_spacing"]},
        "measured": {"charPr_count": total_h, "body_height_count": n_body,
                     "red_runs": red_runs, "bold_runs": bold_runs,
                     "line_spacings": sorted(set(line_spacings))},
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, (0 if not hard else 3)


def main():
    ap = argparse.ArgumentParser(description="recompute-based .hwpx format gate")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--expect", default=None, help="JSON file with base_pt / line_spacing expectations")
    ap.add_argument("--out", default=None, help="write verdict JSON here")
    a = ap.parse_args()
    v, code = check(a.workspace, expect_path=a.expect)
    js = json.dumps(v, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js)
    print(js)
    sys.exit(code)



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    main()
