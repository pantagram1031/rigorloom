# -*- coding: utf-8 -*-
"""verify_format.py — recompute-based format gate for an assembled .hwpx.

Reads <WS>/output/out.hwpx (a zip), parses Contents/header.xml and
Contents/section0.xml, and measures charPr font heights, charPr text colors,
paraPr line-spacing values, and secPr page margins. When output/out.pdf exists,
its page count is measured with PyMuPDF. XML parsing is namespace-agnostic.

Expectations come from form_profile.json, build.yaml, request.yaml, and optional
--expect JSON (later sources override earlier ones). Defaults: body 10pt and
160% line spacing. Margins and page bounds are enforced only when declared.
HWPX measurements use HWPUNIT values (1/100 point); explicit mm/cm/pt/in margin
values are converted before comparison.

Exit 0 = pass (no HARD violations, or out.hwpx absent -> skipped unless
``--require-output`` is set).
Exit 3 = HARD violation(s). Exit 2 = usage error.

HARD rules:
  F1 no charPr with the expected body height exists at all
  F2 any charPr with a near-red text color (red text leaks a fill/edit marker)
  F3 a declared page margin differs from the assembled section margin
  F4 assembled PDF page count is outside declared bounds
  F5 no paraPr carries the expected line-spacing value
WARN rules:
  W2 distribution: share of charPr at the expected body height
  W3 stray bold: count of charPr carrying a bold child
  W4 no margin expectation declared (measured values are reported)
  W5 page bounds declared but output/out.pdf is absent
  margin_expectation_unverifiable / page_bounds_unverifiable: a graded build
     omitted the named expectation

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


def _read_member_xml(hwpx_path, suffix):
    with zipfile.ZipFile(hwpx_path) as z:
        name = None
        for cand in z.namelist():
            if cand.replace("\\", "/").lower().endswith(suffix.lower()):
                name = cand
                break
        if name is None:
            return None
        return z.read(name)


def _strip_yaml_comment(value):
    quote = None
    for i, char in enumerate(value):
        if char in ('"', "'"):
            quote = None if quote == char else (char if quote is None else quote)
        elif char == "#" and quote is None and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value.strip()


def _parse_yaml_scalar(value):
    value = _strip_yaml_comment(value)
    if value in ("", "null", "Null", "NULL", "~"):
        return None
    if value.startswith("{") and value.endswith("}"):
        result = {}
        for item in value[1:-1].split(","):
            if ":" not in item:
                continue
            key, raw = item.split(":", 1)
            result[key.strip().strip('"').strip("'")] = _parse_yaml_scalar(raw.strip())
        return result
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except Exception:
            return [_parse_yaml_scalar(item) for item in value[1:-1].split(",")]
    if ((value.startswith('"') and value.endswith('"')) or
            (value.startswith("'") and value.endswith("'"))):
        return value[1:-1]
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return float(value)
    return value


def _load_simple_yaml(path):
    if not os.path.exists(path):
        return {}
    root = {}
    stack = [(-1, root)]
    text = open(path, encoding="utf-8", errors="ignore").read()
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("-") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().strip('"').strip("'")
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_yaml_scalar(value.strip())
    return root


def _load_json(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_value(data, keys):
    for mapping in _walk_dicts(data):
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
    return None


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(
            r"\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s*", value):
        return float(value)
    return None


def _to_hwpunits(value):
    if isinstance(value, dict) and "value" in value:
        unit = str(value.get("unit", ""))
        value = f"{value['value']}{unit}"
    number = _as_number(value)
    if number is not None:
        return int(round(number))
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(hwpunit|mm|cm|pt|in)\s*",
        value, re.I,
    )
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    factors = {"hwpunit": 1.0, "pt": 100.0, "in": 7200.0,
               "mm": 7200.0 / 25.4, "cm": 7200.0 / 2.54}
    return int(round(number * factors[unit]))


def _margin_values(mapping, nested=False):
    aliases = {
        "top": ("top", "margin_top", "top_margin") if nested else ("margin_top", "top_margin"),
        "bottom": (("bottom", "margin_bottom", "bottom_margin") if nested else
                   ("margin_bottom", "bottom_margin")),
        "left": ("left", "margin_left", "left_margin") if nested else ("margin_left", "left_margin"),
        "right": (("right", "margin_right", "right_margin") if nested else
                  ("margin_right", "right_margin")),
        "gutter": (("gutter", "binding", "margin_gutter", "margin_binding",
                    "gutter_margin", "binding_margin") if nested else
                   ("margin_gutter", "margin_binding", "gutter_margin", "binding_margin")),
    }
    result = {}
    for name, names in aliases.items():
        for key in names:
            if key in mapping:
                converted = _to_hwpunits(mapping[key])
                if converted is not None:
                    result[name] = converted
                    break
    return result


def _extract_margins(data):
    for mapping in _walk_dicts(data):
        for key in ("margins", "margin", "page_margins", "page_margin"):
            block = mapping.get(key)
            if isinstance(block, dict):
                result = _margin_values(block, nested=True)
                if result:
                    return result
    for mapping in _walk_dicts(data):
        result = _margin_values(mapping)
        if result:
            return result
    return None


def _extract_page_bounds(data):
    min_value = _as_number(_first_value(data, ("min_pages",)))
    max_value = _as_number(_first_value(data, ("max_pages",)))
    if min_value is not None or max_value is not None:
        return {"min": int(min_value) if min_value is not None else None,
                "max": int(max_value) if max_value is not None else None}
    for mapping in _walk_dicts(data):
        if "target_pages" not in mapping:
            continue
        target = mapping["target_pages"]
        if isinstance(target, (list, tuple)) and len(target) == 2:
            low, high = _as_number(target[0]), _as_number(target[1])
            if low is not None and high is not None:
                return {"min": int(low), "max": int(high)}
        target_number = _as_number(target)
        tolerance = _as_number(next(
            (mapping[key] for key in ("page_tolerance", "target_pages_tolerance", "tolerance")
             if key in mapping), None))
        if target_number is not None and tolerance is not None:
            return {"min": int(target_number - tolerance),
                    "max": int(target_number + tolerance)}
    return None


def _load_expectations(ws, expect_path):
    exp = {"base_pt": 10, "line_spacing": 160, "margins": None,
           "margin_source": None, "page_bounds": None, "page_source": None,
           "submission_grade": None, "graded": False}
    sources = [
        ("form_profile.json", _load_json(os.path.join(ws, "form_profile.json"))),
        ("build.yaml", _load_simple_yaml(os.path.join(ws, "build.yaml"))),
    ]
    request_data = _load_simple_yaml(os.path.join(ws, "request.yaml"))
    if expect_path:
        sources.append((os.path.basename(expect_path), _load_json(expect_path)))

    for source, data in sources:
        base_pt = _as_number(_first_value(data, ("base_pt",)))
        line_spacing = _as_number(_first_value(data, ("line_spacing",)))
        margins = _extract_margins(data)
        if base_pt is not None:
            exp["base_pt"] = int(base_pt) if base_pt.is_integer() else base_pt
        if line_spacing is not None:
            exp["line_spacing"] = int(line_spacing)
        if margins:
            exp["margins"] = margins
            exp["margin_source"] = source

    for source, data in (("form_profile.json", sources[0][1]),
                         ("build.yaml", sources[1][1]),
                         ("request.yaml", request_data)):
        page_bounds = _extract_page_bounds(data)
        if page_bounds:
            exp["page_bounds"] = page_bounds
            exp["page_source"] = source
    if expect_path:
        page_bounds = _extract_page_bounds(sources[-1][1])
        if page_bounds:
            exp["page_bounds"] = page_bounds
            exp["page_source"] = os.path.basename(expect_path)
    grade = _first_value(request_data, ("submission_grade",))
    if grade is None:
        grade = _first_value(sources[1][1], ("submission_grade",))
    if grade is not None:
        exp["submission_grade"] = str(grade).strip().lower()
        exp["graded"] = exp["submission_grade"] == "graded"
    exp["height"] = exp["base_pt"] * 100
    return exp


def _read_section_margins(raw):
    if raw is None:
        return []
    root = ET.fromstring(raw)
    measured = []
    for sec_pr in (element for element in _iter(root) if _local(element.tag) == "secPr"):
        for page_pr in (element for element in _iter(sec_pr)
                        if _local(element.tag) == "pagePr"):
            margin = next((element for element in _iter(page_pr)
                           if _local(element.tag) == "margin"), None)
            if margin is None:
                continue
            values = {}
            for key in ("top", "bottom", "left", "right", "gutter", "binding"):
                if key not in margin.attrib:
                    continue
                try:
                    values[key] = int(margin.attrib[key])
                except ValueError:
                    values[key] = margin.attrib[key]
            if "binding" in values and "gutter" not in values:
                values["gutter"] = values["binding"]
            measured.append(values)
    return measured


def _format_margin_measurements(margins):
    if not margins:
        return "Contents/section0.xml secPr/pagePr/margin not found"
    chunks = []
    for index, values in enumerate(margins):
        fields = ",".join(f"{key}={values[key]}" for key in
                          ("top", "bottom", "left", "right", "gutter", "binding")
                          if key in values)
        chunks.append(f"section[{index}] {fields}")
    return "; ".join(chunks)


def check(ws, expect_path=None, require_output=False):
    hwpx = os.path.join(ws, "output", "out.hwpx")
    if not os.path.exists(hwpx):
        if require_output:
            finding = {
                "code": "output_missing",
                "msg": "required assembled output/out.hwpx is missing",
                "at": hwpx,
            }
            return {
                "ok": False,
                "workspace": ws,
                "checker": "verify_format",
                "skipped": False,
                "hard": [finding],
                "warn": [],
                "counts": {"hard": 1, "warn": 0},
                "verdict": "fail",
            }, 3
        return {"ok": True, "workspace": ws, "checker": "verify_format", "skipped": True,
                "note": "output/out.hwpx not present (pre-assembly workspace)",
                "hard": [], "warn": [], "counts": {"hard": 0, "warn": 0},
                "verdict": "skipped"}, 0

    exp = _load_expectations(ws, expect_path)
    try:
        raw = _read_member_xml(hwpx, "contents/header.xml")
        section_raw = _read_member_xml(hwpx, "contents/section0.xml")
    except (zipfile.BadZipFile, OSError) as exc:
        return {"ok": False, "error": f"cannot read out.hwpx: {exc}"}, 2
    if raw is None:
        return {"ok": False, "error": "Contents/header.xml not found in out.hwpx"}, 2
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"header.xml parse error: {exc}"}, 2
    try:
        margins = _read_section_margins(section_raw)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"section0.xml parse error: {exc}"}, 2

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
    page_count = None
    pdf = os.path.join(ws, "output", "out.pdf")
    pdf_exists = os.path.exists(pdf)
    fitz_module = None
    if exp["page_bounds"] and not pdf_exists:
        hard.append({
            "code": "page_count_unverifiable",
            "msg": "declared page bounds cannot be checked because output/out.pdf is absent",
            "at": pdf,
        })
    elif exp["page_bounds"] or pdf_exists:
        try:
            import fitz as fitz_module
        except ImportError:
            if exp["page_bounds"]:
                hard.append({
                    "code": "page_count_unverifiable",
                    "msg": "declared page bounds cannot be checked because PyMuPDF is unavailable",
                    "at": pdf,
                })
    if pdf_exists and fitz_module is not None:
        try:
            with fitz_module.open(pdf) as document:
                page_count = len(document)
        except Exception as exc:
            return {"ok": False, "error": f"cannot read output/out.pdf: {exc}"}, 2

    body_h = exp["height"]
    n_body = sum(1 for h in heights if h == body_h)
    if n_body == 0:
        hard.append({"code": "F1", "msg": f"no charPr with expected body height {body_h} "
                     f"({exp['base_pt']}pt)", "at": f"heights={sorted(set(heights))[:12]}"})
    if red_runs > 0:
        hard.append({"code": "F2", "msg": "near-red text color present in charPr "
                     "(fill/edit-marker leak)", "at": f"x{red_runs}"})
    if exp["line_spacing"] not in line_spacings:
        hard.append({"code": "F5",
                     "msg": f"expected line spacing {exp['line_spacing']}% not found",
                     "at": f"seen={sorted(set(line_spacings))[:12]}"})

    expected_margins = exp["margins"]
    if expected_margins:
        if not margins:
            hard.append({"code": "F3", "msg": "declared margins cannot be verified",
                         "at": _format_margin_measurements(margins)})
        else:
            for index, measured in enumerate(margins):
                for name, expected in expected_margins.items():
                    actual = measured.get(name)
                    if not isinstance(actual, int) or abs(actual - expected) > 2:
                        hard.append({
                            "code": "F3",
                            "msg": f"section[{index}] {name} margin {actual} != expected {expected}",
                            "at": f"source={exp['margin_source']}",
                        })
    else:
        if exp["graded"]:
            warn.append({
                "code": "margin_expectation_unverifiable",
                "msg": ("graded build margins are unverifiable: neither build.yaml nor "
                        "form_profile.json declares margins"),
                "at": _format_margin_measurements(margins),
            })
        else:
            warn.append({"code": "W4", "msg": "no margin expectation declared",
                         "at": _format_margin_measurements(margins)})

    bounds = exp["page_bounds"]
    if exp["graded"] and not bounds:
        warn.append({
            "code": "page_bounds_unverifiable",
            "msg": ("graded build page bounds are unverifiable: neither build.yaml nor "
                    "form_profile.json declares page bounds"),
            "at": "build.yaml; form_profile.json",
        })
    if bounds and page_count is not None:
        below = bounds["min"] is not None and page_count < bounds["min"]
        above = bounds["max"] is not None and page_count > bounds["max"]
        if below or above:
            hard.append({
                "code": "F4",
                "msg": f"PDF page count {page_count} outside declared bounds "
                       f"[{bounds['min']}, {bounds['max']}]",
                "at": f"source={exp['page_source']}",
            })

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
        "expected": {"base_pt": exp["base_pt"], "height": body_h,
                     "line_spacing": exp["line_spacing"],
                     "margins": exp["margins"],
                     "margin_source": exp["margin_source"],
                     "page_bounds": exp["page_bounds"],
                     "page_source": exp["page_source"],
                     "submission_grade": exp["submission_grade"]},
        "measured": {"charPr_count": total_h, "body_height_count": n_body,
                     "red_runs": red_runs, "bold_runs": bold_runs,
                     "line_spacings": sorted(set(line_spacings)),
                     "margins": margins, "page_count": page_count},
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, (0 if not hard else 3)


def main():
    ap = argparse.ArgumentParser(description="recompute-based .hwpx format gate")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--expect", default=None,
                    help="JSON file overriding font, spacing, margin, or page expectations")
    ap.add_argument(
        "--require-output",
        action="store_true",
        help="fail closed when output/out.hwpx is missing (post-assembly gate mode)",
    )
    ap.add_argument("--out", default=None, help="write verdict JSON here")
    a = ap.parse_args()
    v, code = check(
        a.workspace,
        expect_path=a.expect,
        require_output=a.require_output,
    )
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
