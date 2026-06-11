#!/usr/bin/env python3
"""레이아웃 QA — PDF 페이지별 공백/간격을 수치로 측정해 임계 초과를 flag.

미적 판단("공백이 너무 많다")을 결정론적 게이트로 바꾼다. 편집 루프에서
collapse_empty_paragraphs 같은 보정을 돌린 뒤 이 도구로 통과/실패를 가린다.

    python layout_qa.py --file verify.pdf [--bottom 25] [--gap 3]

페이지별 출력:
  - content_bbox      : 텍스트+이미지 블록의 합집합 bbox [x0,y0,x1,y1]
  - bottom_white_pct  : 콘텐츠 하단~페이지 끝 공백 / 페이지 높이 (%)
  - max_gap_lines     : 세로로 인접한 블록 사이 최대 간격 (본문 줄높이 배수)
  - flags             : 임계 초과 사유

기본 임계: 하단 공백 ≤ 25%(마지막 쪽 제외), 블록 간 간격 ≤ 3줄.
임계는 인자로만 바꾼다 — 코드에 하드코딩된 값을 임의 조정하지 말 것.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

import fitz  # pymupdf


def _blocks(page):
    """(x0,y0,x1,y1, kind) 블록 목록. kind: 'text' | 'image'. 빈 블록 제외."""
    out = []
    d = page.get_text("dict")
    for b in d.get("blocks", []):
        x0, y0, x1, y1 = b["bbox"]
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        if b.get("type") == 1:
            out.append((x0, y0, x1, y1, "image"))
        else:
            has_text = any(
                s.get("text", "").strip()
                for ln in b.get("lines", [])
                for s in ln.get("spans", [])
            )
            if has_text:
                out.append((x0, y0, x1, y1, "text"))
    return out


def _line_height(page):
    """본문 한 줄 높이의 중앙값(pt). 텍스트 줄 bbox 높이 기준."""
    hs = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") == 1:
            continue
        for ln in b.get("lines", []):
            ly0, ly1 = ln["bbox"][1], ln["bbox"][3]
            if ly1 - ly0 > 1:
                hs.append(ly1 - ly0)
    return statistics.median(hs) if hs else 12.0


def analyze(pdf_path, bottom_thr=25.0, gap_thr=3.0):
    doc = fitz.open(pdf_path)
    pages, n = [], doc.page_count
    for i, page in enumerate(doc):
        H = page.rect.height
        blks = _blocks(page)
        lh = _line_height(page)
        rec = {"page": i + 1, "line_height_pt": round(lh, 2)}
        if not blks:
            rec.update(content_bbox=None, bottom_white_pct=100.0,
                       max_gap_lines=0.0, flags=["empty_page"])
            pages.append(rec)
            continue
        x0 = min(b[0] for b in blks)
        y0 = min(b[1] for b in blks)
        x1 = max(b[2] for b in blks)
        y1 = max(b[3] for b in blks)
        bottom_white = (H - y1) / H * 100.0

        # 간격은 '빈 문단 구멍'만 잡아야 한다. 그림은 PNG 흰 여백+도형으로 본질적
        # 세로 공간을 차지하므로 그림이 낀 간격은 오탐이다. 따라서 (1) 양쪽이 모두
        # 텍스트이고 (2) 그 세로 구간을 어떤 이미지도 점유하지 않는 간격만 센다.
        # (inline 중앙정렬 그림 옆에 캡션 줄이 와도 그림 y범위와 겹치면 제외됨.)
        # 임계값(3줄)은 불변 — 무엇을 '간격'으로 볼지만 바로잡는다.
        img_spans = [(b[1], b[3]) for b in blks if b[4] == "image"]

        def _hits_image(y0, y1):
            return any(iy0 < y1 and iy1 > y0 for iy0, iy1 in img_spans)

        ordered = sorted(blks, key=lambda b: b[1])
        max_gap, gap_at = 0.0, None
        for a, b in zip(ordered, ordered[1:]):
            if a[4] != "text" or b[4] != "text":
                continue                 # 그림 인접 간격 제외
            if _hits_image(a[3], b[1]):
                continue                 # 그림이 점유한 세로 구간 제외
            gap = b[1] - a[3]            # next.y0 - cur.y1
            if gap > max_gap:
                max_gap, gap_at = gap, round(a[3], 1)
        max_gap_lines = round(max_gap / lh, 2) if lh else 0.0

        flags = []
        is_last = (i == n - 1)
        if not is_last and bottom_white > bottom_thr:
            flags.append(f"bottom_white {bottom_white:.1f}% > {bottom_thr}%")
        if max_gap_lines > gap_thr:
            flags.append(f"max_gap {max_gap_lines} lines > {gap_thr}")

        rec.update(
            content_bbox=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
            bottom_white_pct=round(bottom_white, 1),
            max_gap_lines=max_gap_lines,
            max_gap_at_y=gap_at,
            n_blocks=len(blks),
            flags=flags,
        )
        pages.append(rec)
    doc.close()
    flagged = [p["page"] for p in pages if p.get("flags")]
    return {
        "ok": True,
        "file": str(pdf_path),
        "page_count": n,
        "thresholds": {"bottom_white_pct": bottom_thr, "max_gap_lines": gap_thr},
        "flagged_pages": flagged,
        "pass": not flagged,
        "pages": pages,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--bottom", type=float, default=25.0,
                    help="하단 공백 임계(%%), 마지막 쪽 제외")
    ap.add_argument("--gap", type=float, default=3.0,
                    help="블록 간 최대 간격 임계(줄 배수)")
    ap.add_argument("--out", help="JSON 출력 파일(생략 시 stdout)")
    args = ap.parse_args()
    res = analyze(args.file, args.bottom, args.gap)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: pass={res['pass']} flagged={res['flagged_pages']}")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
