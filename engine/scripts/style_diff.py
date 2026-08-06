#!/usr/bin/env python3
"""style_diff.py — 조립된 .hwpx의 서식 분포를 form_baseline.json과 대조.

form_inspect.py --baseline이 뽑아둔 양식의 정상 폰트/크기/색/줄간격 집합 대비,
조립 결과(work_v0.3/out.hwpx 등)의 본문에 그 집합에 없는 값이 남아 있으면
anomaly로 보고한다(예: 안내문 빨간색이 안 지워짐, 캡션 크기가 build.yaml에
없는 값으로 새어나감). build.yaml에 선언된 값(base_pt/caption_pt/line_spacing)
은 허용 목록에 추가된다.

    python style_diff.py OUT.hwpx --baseline form_baseline.json [--build-yaml build.yaml] [--out diff.json]

exit 0: anomaly 없음. exit 1: anomaly 있음. exit 2: 사용법/파일 오류.
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_report import parse_build_yaml  # noqa: E402
from form_inspect import (  # noqa: E402
    _charpr_defs, _fontfaces, _paraprops, _paragraphs, font_face, NS,
    P_TAG_RE, RUN_TAG_RE, T_RE, _attr, _align_map, analyze as form_analyze,
)

# 하이퍼링크 파랑 — build.yaml allow_colors에 명시적으로 없으면 항상 anomaly.
ALWAYS_FLAG_COLORS = {"#0000FF"}


def die(msg, code=2):
    line = json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.exit(code)


def _pt(v):
    return round(v, 1) if v is not None else v


def build_allowances(baseline, build_cfg):
    """baseline + build.yaml 선언값을 합친 허용 집합. 반환: dict of sets.

    guide_only_colors(안내문 전용 색)는 baseline.colors에 남아있어도(구버전 호환)
    절대 허용하지 않는다 — 안내문은 조립 시 삭제되므로 출력에 나오면 anomaly.
    하이퍼링크 파랑(#0000FF)도 build.yaml allow_colors에 명시되지 않는 한 항상 flag.
    """
    fonts = set(baseline.get("fonts", []))
    sizes = {round(s, 1) for s in baseline.get("sizes_pt", [])}
    colors = {c.upper() for c in baseline.get("colors", [])}
    line_spacings = {tuple(x) for x in baseline.get("line_spacings", [])}

    guide_only_colors = {c.upper() for c in baseline.get("guide_only_colors", [])}
    colors -= guide_only_colors
    colors -= ALWAYS_FLAG_COLORS

    allow_colors_cfg = set()
    if build_cfg and "allow_colors" in build_cfg:
        raw = build_cfg["allow_colors"]
        items = raw if isinstance(raw, list) else [raw]
        for v in items:
            v = str(v).strip()
            # 방어적 정규화: build_report._yaml_list가 이미 따옴표를 벗기지만,
            # allow_colors가 다른 경로(수동 dict 구성 등)로 주입될 수도 있으므로
            # 여기서도 남은 따옴표를 한 번 더 벗기고 대문자로 통일한다 — 그래야
            # '"#0000FF"'(quoted)와 #0000FF(unquoted)와 [#a, #b] 안 항목이 모두
            # 동일한 set 멤버십으로 매칭된다.
            if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
                v = v[1:-1].strip()
            if v:
                allow_colors_cfg.add(v.upper())
    colors |= allow_colors_cfg

    if build_cfg:
        for key, target in (("base_pt", sizes), ("caption_pt", sizes)):
            if key in build_cfg:
                try:
                    target.add(round(float(build_cfg[key]), 1))
                except (TypeError, ValueError):
                    pass
        if "line_spacing" in build_cfg:
            try:
                pct = int(str(build_cfg["line_spacing"]).rstrip("%"))
                line_spacings.add(("PERCENT", pct))
            except (TypeError, ValueError):
                pass

    return {"fonts": fonts, "sizes_pt": sizes, "colors": colors,
            "line_spacings": line_spacings, "guide_only_colors": guide_only_colors}


def analyze(out_path, baseline, build_cfg=None):
    allow = build_allowances(baseline, build_cfg)

    z = zipfile.ZipFile(out_path)
    header_xml = z.read("Contents/header.xml").decode("utf-8")
    defs = _charpr_defs(header_xml)
    fontref_map = _fontfaces(header_xml)
    parapr_ls = _paraprops(header_xml)

    section_names = sorted(n for n in z.namelist()
                            if re.match(r"Contents/section\d+\.xml", n))

    # anomaly_key -> {"kind":..., "value":..., "locations":[...], "sample_text":..., "count": n}
    anomalies = {}

    def record(kind, value, section, para_idx, sample_text):
        key = (kind, value)
        entry = anomalies.setdefault(key, {
            "kind": kind, "value": value, "locations": [],
            "sample_text": sample_text, "count": 0,
        })
        entry["count"] += 1
        if len(entry["locations"]) < 5:
            entry["locations"].append({"section": section, "para_idx": para_idx})

    global_para_idx = 0
    for sname in section_names:
        xml = z.read(sname).decode("utf-8")
        paras = _paragraphs(xml, defs)
        for p in paras:
            text = p["text"]
            para_pr = p["paraPr"]
            cids = p["charPrs"]

            if text.strip():
                for cid in cids:
                    d = defs.get(cid, {})
                    pt = d.get("height_pt")
                    color = d.get("color")
                    face = font_face(defs, fontref_map, cid, "hangul")

                    if pt is not None and _pt(pt) not in allow["sizes_pt"]:
                        record("size", _pt(pt), sname, global_para_idx, text[:60])
                    if color and color.upper() not in allow["colors"]:
                        record("color", color.upper(), sname, global_para_idx, text[:60])
                    if face and allow["fonts"] and face not in allow["fonts"]:
                        record("font", face, sname, global_para_idx, text[:60])

                ls = parapr_ls.get(para_pr)
                if ls and ls.get("value") is not None:
                    tup = (ls["type"], ls["value"])
                    if allow["line_spacings"] and tup not in allow["line_spacings"]:
                        record("line_spacing", f"{ls['type']}:{ls['value']}",
                               sname, global_para_idx, text[:60])

            global_para_idx += 1

    anomaly_list = sorted(anomalies.values(), key=lambda a: (a["kind"], str(a["value"])))
    return {"ok": len(anomaly_list) == 0, "anomalies": anomaly_list}


def _paragraphs_with_runs(xml, defs):
    """section xml -> [{"text":.., "runs":[(run_text, height_pt), ...]}].

    _paragraphs()(form_inspect)와 달리 런별 텍스트+height_pt를 보존한다 —
    heading-merge 판정에 앵커가 어느 런에 속하는지 알아야 하기 때문.
    """
    out = []
    for pm in P_TAG_RE.finditer(xml):
        p_attrs = pm.group(1)
        if _attr(p_attrs, "paraPrIDRef") is None:
            continue
        body = pm.group(2)
        runs = []
        for rm in RUN_TAG_RE.finditer(body):
            cid = _attr(rm.group(1), "charPrIDRef")
            if cid is None:
                continue
            run_text = re.sub(r"<[^>]+>", "", "".join(T_RE.findall(rm.group(2))))
            height = defs.get(cid, {}).get("height_pt")
            runs.append((run_text, height))
        text = "".join(r[0] for r in runs)
        out.append({"text": text, "runs": runs})
    return out


def _find_anchor_paragraph(paras, anchor):
    """anchor 텍스트를 포함하는 첫 문단을 찾아 (para, at_start, heights) 반환.

    at_start: 문단 텍스트를 strip한 뒤 anchor로 시작하면 True(정상 제목 문단).
    heights: anchor의 선두 부분과 겹치는 런들의 height_pt 집합(중복 없이,
    None 제외) — heading_merged 케이스에서도 실제 앵커 런의 크기를 보고하기
    위해 오프셋 기준으로 겹치는 런만 고른다.
    반환값 없으면 None(문단에 anchor 없음).
    """
    for p in paras:
        text = p["text"]
        idx = text.find(anchor)
        if idx == -1:
            continue
        stripped = text.strip()
        at_start = stripped.startswith(anchor)
        # anchor가 걸치는 [idx, idx+len(anchor)) 구간과 겹치는 런만 모은다.
        heights = []
        seen = set()
        cursor = 0
        anchor_end = idx + len(anchor)
        for run_text, height in p["runs"]:
            run_start = cursor
            run_end = cursor + len(run_text)
            if run_start < anchor_end and run_end > idx:
                if height is not None and height not in seen:
                    seen.add(height)
                    heights.append(height)
            cursor = run_end
        return {"text": text, "at_start": at_start, "heights": heights}
    return None


def check_headings(form_path, out_path, anchors):
    """anchors(제목 문자열 목록)를 baseline form과 out hwpx 양쪽에서 찾아
    charPr height(pt) 집합을 대조. 반환: anomaly 목록(kind: heading_pt|heading_merged).

    - heading_pt: 두 쪽 다 anchor가 문단 시작에 있지만 height 집합이 다름.
    - heading_merged: out에서 anchor 텍스트는 발견되지만 문단 시작이 아님
      (이전 문단에 병합됨 — T7 계열 손상).
    - 두 쪽 다 anchor를 못 찾으면(양식에도 없음) 조용히 스킵(오타 방지는
      호출자 책임 — 이 함수는 순수 대조만).
    """
    def _load(path):
        z = zipfile.ZipFile(path)
        header_xml = z.read("Contents/header.xml").decode("utf-8")
        defs = _charpr_defs(header_xml)
        section_names = sorted(n for n in z.namelist()
                                if re.match(r"Contents/section\d+\.xml", n))
        paras = []
        for sname in section_names:
            xml = z.read(sname).decode("utf-8")
            paras.extend(_paragraphs_with_runs(xml, defs))
        return paras

    form_paras = _load(form_path)
    out_paras = _load(out_path)

    anomalies = []
    for anchor in anchors:
        form_hit = _find_anchor_paragraph(form_paras, anchor)
        out_hit = _find_anchor_paragraph(out_paras, anchor)

        if out_hit is None:
            anomalies.append({
                "kind": "heading_merged", "anchor": anchor,
                "detail": "anchor not found in output at all",
            })
            continue

        if not out_hit["at_start"]:
            anomalies.append({
                "kind": "heading_merged", "anchor": anchor,
                "detail": "anchor text present but not at paragraph start",
                "out_text": out_hit["text"][:120],
            })
            continue

        if form_hit is None:
            continue  # 양식에도 없는 앵커 — 대조 불가, 스킵.

        form_pt = sorted(set(form_hit["heights"]))
        out_pt = sorted(set(out_hit["heights"]))
        if form_pt != out_pt:
            anomalies.append({
                "kind": "heading_pt", "anchor": anchor,
                "form_pt": form_pt, "out_pt": out_pt,
            })

    return anomalies


def _find_para_format_match(out_paras, text_head):
    """out_paras(_paragraphs() 결과)에서 text_head로 시작하는 첫 문단 반환."""
    for p in out_paras:
        if p["text"].strip().startswith(text_head):
            return p
    return None


def check_para_formats(form_path, out_path):
    """baseline form의 para_formats(제목/앵커/placeholder 문단)를 out과 대조.

    text_head로 매칭되는 문단이 out에 없으면 조용히 스킵한다 — 단, 그 문단이
    heading anchor 자체라면(=check_headings가 이미 heading_merged로 잡음)
    여기서 중복 보고하지 않는다(스킵과 동일 취급이라 별도 분기 불필요).
    발견된 문단은 align/line_spacing/char_pt 필드별로 diff → 값이 다르면
    anomaly 하나씩(kind="para_format"). 새 문단(out에만 있는) mass 추가는
    애초에 이 함수가 baseline 쪽 목록만 순회하므로 대상이 아니다(플래그 안 됨).

    반환: {"ok": bool, "anomalies": [...], "align_histogram": {"form": {...}, "out": {...}}}
    """
    _, form_baseline = form_analyze(form_path, want_baseline=True)
    form_formats = form_baseline["para_formats"]

    z = zipfile.ZipFile(out_path)
    out_header = z.read("Contents/header.xml").decode("utf-8")
    out_defs = _charpr_defs(out_header)
    out_section_names = sorted(n for n in z.namelist()
                                if re.match(r"Contents/section\d+\.xml", n))
    out_paras = []
    for sname in out_section_names:
        out_paras.extend(_paragraphs(z.read(sname).decode("utf-8"), out_defs))

    out_align_map = _align_map(out_header)

    anomalies = []
    for entry in form_formats:
        text_head = entry["text_head"]
        match = _find_para_format_match(out_paras, text_head)
        if match is None:
            continue  # out에 없음 — heading류는 check_headings가 별도 커버.

        out_align = out_align_map.get(match["paraPr"])
        if entry["align"] != out_align:
            anomalies.append({
                "kind": "para_format", "text_head": text_head, "field": "align",
                "form_value": entry["align"], "out_value": out_align,
            })

        out_ls_raw = _paraprops(out_header).get(match["paraPr"])
        out_ls = (
            {"type": out_ls_raw["type"], "value": out_ls_raw["value"]}
            if out_ls_raw and out_ls_raw.get("value") is not None else None
        )
        if entry["line_spacing"] != out_ls:
            anomalies.append({
                "kind": "para_format", "text_head": text_head, "field": "line_spacing",
                "form_value": entry["line_spacing"], "out_value": out_ls,
            })

        out_char_pt = sorted({
            out_defs.get(cid, {}).get("height_pt") for cid in match["charPrs"]
            if out_defs.get(cid, {}).get("height_pt") is not None
        })
        if entry["char_pt"] != out_char_pt:
            anomalies.append({
                "kind": "para_format", "text_head": text_head, "field": "char_pt",
                "form_value": entry["char_pt"], "out_value": out_char_pt,
            })

    # 전역 정렬 히스토그램(정보용) — 신규 문단 유입으로 인한 분포 변화는 flag
    # 대상이 아님(위 per-paragraph diff만 anomaly를 만든다). 가시성 확보용으로만 반환.
    def _histogram(path, header_xml):
        zz = zipfile.ZipFile(path)
        defs_local = _charpr_defs(header_xml)
        am = _align_map(header_xml)
        hist = {}
        section_names = sorted(n for n in zz.namelist()
                                if re.match(r"Contents/section\d+\.xml", n))
        for sname in section_names:
            for p in _paragraphs(zz.read(sname).decode("utf-8"), defs_local):
                if not p["text"].strip():
                    continue
                a = am.get(p["paraPr"], "unknown")
                hist[a] = hist.get(a, 0) + 1
        return hist

    form_header_xml = zipfile.ZipFile(form_path).read("Contents/header.xml").decode("utf-8")
    form_hist = _histogram(form_path, form_header_xml)
    out_hist = _histogram(out_path, out_header)

    return {
        "ok": len(anomalies) == 0,
        "anomalies": anomalies,
        "align_histogram": {"form": form_hist, "out": out_hist},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_file", help="조립된 .hwpx 경로")
    ap.add_argument("--baseline", help="form_baseline.json 경로(색/폰트/크기 anomaly 체크용)")
    ap.add_argument("--build-yaml", help="build.yaml 경로(있으면 허용값에 병합)")
    ap.add_argument("--check-headings",
                    help="제목 무결성 체크(T7류 손상 탐지): 앵커 문자열 JSON 배열 경로. "
                         "--baseline-form과 함께 사용")
    ap.add_argument("--baseline-form",
                    help="--check-headings용 원본(pristine) .hwpx 양식 경로")
    ap.add_argument("--check-para-formats", action="store_true",
                    help="문단 서식(정렬/줄간격/글자크기) 무결성 체크. "
                         "--baseline-form과 함께 사용(--check-headings와 동일한 원본 인자)")
    ap.add_argument("--out", help="diff.json 출력 경로(생략 시 stdout)")
    args = ap.parse_args()

    if not Path(args.out_file).exists():
        die(f"파일 없음: {args.out_file}")

    if args.check_headings:
        if not args.baseline_form:
            die("--check-headings에는 --baseline-form 필요")
        if not Path(args.check_headings).exists():
            die(f"anchors JSON 없음: {args.check_headings}")
        if not Path(args.baseline_form).exists():
            die(f"baseline form 없음: {args.baseline_form}")
        try:
            anchors = json.loads(Path(args.check_headings).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            die(f"anchors JSON 파싱 실패: {e}")
        try:
            heading_anomalies = check_headings(args.baseline_form, args.out_file, anchors)
        except KeyError as e:
            die(f"hwpx 구조 이상(필수 엔트리 없음): {e}")
        except zipfile.BadZipFile:
            die("유효한 zip(.hwpx)이 아님")

        result = {"ok": len(heading_anomalies) == 0, "anomalies": heading_anomalies}
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            kinds = sorted({a["kind"] for a in heading_anomalies})
            print(f"wrote {args.out}: ok={result['ok']} anomalies={len(heading_anomalies)} kinds={kinds}")
        else:
            sys.stdout.buffer.write(text.encode("utf-8"))
        sys.exit(0 if result["ok"] else 1)

    if args.check_para_formats:
        if not args.baseline_form:
            die("--check-para-formats에는 --baseline-form 필요")
        if not Path(args.baseline_form).exists():
            die(f"baseline form 없음: {args.baseline_form}")
        try:
            result = check_para_formats(args.baseline_form, args.out_file)
        except KeyError as e:
            die(f"hwpx 구조 이상(필수 엔트리 없음): {e}")
        except zipfile.BadZipFile:
            die("유효한 zip(.hwpx)이 아님")

        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}: ok={result['ok']} anomalies={len(result['anomalies'])}")
        else:
            sys.stdout.buffer.write(text.encode("utf-8"))
        sys.exit(0 if result["ok"] else 1)

    if not args.baseline:
        die("--baseline 필요(또는 --check-headings 사용)")
    if not Path(args.baseline).exists():
        die(f"baseline 없음: {args.baseline}")

    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"baseline JSON 파싱 실패: {e}")

    build_cfg = None
    if args.build_yaml:
        if not Path(args.build_yaml).exists():
            die(f"build.yaml 없음: {args.build_yaml}")
        build_cfg = parse_build_yaml(args.build_yaml)

    try:
        result = analyze(args.out_file, baseline, build_cfg)
    except KeyError as e:
        die(f"hwpx 구조 이상(필수 엔트리 없음): {e}")
    except zipfile.BadZipFile:
        die(f"유효한 zip(.hwpx)이 아님: {args.out_file}")

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        kinds = sorted({a["kind"] for a in result["anomalies"]})
        print(f"wrote {args.out}: ok={result['ok']} anomalies={len(result['anomalies'])} kinds={kinds}")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
