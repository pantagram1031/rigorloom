#!/usr/bin/env python3
"""charpr_check.py — .hwpx의 런별 글자크기/색을 결정론적으로 추출·판정 (오프라인).

한글(COM) 없이 .hwpx(zip)를 풀어 header.xml의 charPr 정의와 section*.xml의
charPrIDRef 분포를 대조한다. PDF를 눈으로 보지 않고도 "본문 10pt·검정, 캡션 9pt,
하이퍼링크 파랑, 제목 > 본문" 같은 서식 불변식을 수치로 증명한다(감사 M5/B1).

    python charpr_check.py --file out.hwpx [--base-pt 10] [--caption-pt 9]

출력(JSON): 런 목록 요약 + charPr 크기 집합 + 판정(verdict).
  - body_ok        : 본문 산문 런 다수가 base_pt·검정인가
  - caption_present: caption_pt 크기 런이 있는가
  - title_larger   : base_pt보다 큰(제목) 런이 있는가
  - link_blue      : 파란색(하이퍼링크) 런이 있는가 (있으면 True, 없으면 null)
"""
import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402

RUN_RE = re.compile(r'charPrIDRef="(\d+)"(.*?)>(.*?)</hp:run>', re.S)
T_RE = re.compile(r'<hp:t>(.*?)</hp:t>', re.S)


def _charpr_defs(header_xml):
    """charPr id -> {height_pt, color}. color는 textColor 속성(#RRGGBB) 또는 None."""
    defs = {}
    for m in re.finditer(r'<hh:charPr\b[^>]*\bid="(\d+)"[^>]*?>', header_xml):
        blob = m.group(0)
        cid = re.search(r'\bid="(\d+)"', blob).group(1)
        hm = re.search(r'\bheight="(\d+)"', blob)
        cm = re.search(r'\btextColor="(#?[0-9A-Fa-f]{6})"', blob)
        defs[cid] = {
            "height_pt": int(hm.group(1)) / 100.0 if hm else None,
            "color": (cm.group(1).upper() if cm else None),
        }
    return defs


def _runs(hwpx):
    z = zipfile.ZipFile(hwpx)
    header = z.read("Contents/header.xml").decode("utf-8")
    defs = _charpr_defs(header)
    names = sorted(n for n in z.namelist()
                   if re.match(r"Contents/section\d+\.xml", n))
    out = []
    for n in names:
        xml = z.read(n).decode("utf-8")
        for cid, _attrs, body in RUN_RE.findall(xml):
            txt = re.sub(r"<[^>]+>", "", "".join(T_RE.findall(body)))
            if txt.strip():
                d = defs.get(cid, {})
                out.append({"cid": cid, "pt": d.get("height_pt"),
                            "color": d.get("color"), "text": txt[:40]})
    return out, defs


def _is_blue(color):
    if not color:
        return False
    c = color.lstrip("#").upper()
    # 파랑 계열: B 성분이 크고 R·G가 작음. 순청(0000FF)·짙은파랑 포함.
    if len(c) != 6:
        return False
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return b > 120 and r < 100 and g < 100


def analyze(hwpx, base_pt=10.0, caption_pt=9.0):
    runs, defs = _runs(hwpx)
    prose = [r for r in runs if r["pt"] is not None]
    body = [r for r in prose if abs(r["pt"] - base_pt) < 0.5]
    body_black = [r for r in body if r["color"] in (None, "#000000", "#000000")]
    caption = [r for r in prose if abs(r["pt"] - caption_pt) < 0.5]
    title = [r for r in prose if r["pt"] > base_pt + 0.5]
    blue = [r for r in prose if _is_blue(r["color"])]
    sizes = sorted({r["pt"] for r in prose if r["pt"]})
    verdict = {
        "body_ok": len(body) > 0 and len(body_black) >= max(1, len(body) // 2),
        "caption_present": len(caption) > 0,
        "title_larger": len(title) > 0,
        "link_blue": (len(blue) > 0) if blue else None,
    }
    return {
        "ok": True,
        "file": str(hwpx),
        "sizes_pt": sizes,
        "n_runs": len(prose),
        "counts": {"body": len(body), "body_black": len(body_black),
                   "caption": len(caption), "title": len(title),
                   "blue": len(blue)},
        "size_histogram": dict(Counter(round(r["pt"], 1) for r in prose if r["pt"])),
        "verdict": verdict,
    }


def main():
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help=".hwpx 경로")
    ap.add_argument("--base-pt", type=float, default=10.0)
    ap.add_argument("--caption-pt", type=float, default=9.0)
    ap.add_argument("--out", help="JSON 출력 파일(생략 시 stdout)")
    args = ap.parse_args()
    res = analyze(args.file, args.base_pt, args.caption_pt)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: verdict={res['verdict']}")
    else:
        import sys
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
