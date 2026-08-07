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
import re
import statistics
import sys
from pathlib import Path

import fitz  # pymupdf

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402

CAPTION_RE = re.compile(r"^\s*(\[?그림|Fig)", re.IGNORECASE)
# 캡션 뒤 빈 줄 면제용 — 표/그림 캡션 줄 판정("표 1.", "[그림 2]", "그림 3" 등).
OBJECT_CAPTION_RE = re.compile(r"^\s*(표\s*\d|\[?그림\s*\d|Fig)", re.IGNORECASE)
CITATION_RE = re.compile(r"\[\d{1,2}\]")
GUIDE_RE = re.compile(r"(작성하세요|여기에\s*입력|예시\s*[):]|【안내|<안내)")
LATEX_LEAK_RE = re.compile(r"\\\\|pmatrix|\\frac")


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


def _block_text(b):
    """텍스트 블록(딕셔너리 원본)의 모든 줄을 이어붙인 문자열."""
    return "".join(
        s.get("text", "")
        for ln in b.get("lines", [])
        for s in ln.get("spans", [])
    )


def _footer_block_bboxes(page, page_height):
    """페이지 하단 8% 안의 '페이지번호 footer' 텍스트 블록 bbox 집합.

    max_gap_lines(구멍) 계산 전용 — bottom_white_pct/content_bbox 등 다른
    체크는 이 필터를 참조하지 않는다(footer를 거기서 제외하면 표지 페이지의
    의도된 하단 여백이 새로 flag될 수 있음, 스코프 밖).
    """
    out = set()
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") == 1:
            continue
        x0, y0, x1, y1 = b["bbox"]
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        text = _block_text(b)
        if not text.strip():
            continue
        if _is_footer_line(text, y0, page_height):
            out.add((x0, y0, x1, y1))
    return out


FOOTER_NUM_RE = re.compile(r"^[-–—\s]*\d{1,3}[-–—\s]*$")


def _is_footer_line(text, y0, page_height, frac=0.08):
    """페이지 번호 footer 줄인지 판정 (구멍/max_gap 계산 전용 필터).

    두 조건 모두 만족해야 footer로 본다:
      (a) 공백 트림 후 "- 1 -"/"1"/"— 3 —" 같은 페이지번호 형태
          (숫자 1~3자리, 앞뒤로 하이픈/엔대시/엠대시/공백만 허용)
      (b) 페이지 하단 frac(기본 8%) 구간에 위치(y0 기준)

    본문 중간의 숫자 한 줄(예: 목록 번호)이나, 하단이라도 숫자가 아닌 줄은
    footer로 보지 않는다 — 캡션/저작권 문구 등을 실수로 지워 하단 여백
    체크(bottom_white)를 새로 오염시키지 않기 위해 이 판정은 gap 계산에만
    쓰고 다른 체크에는 절대 연결하지 않는다.
    page_height가 없으면(0/None) 항상 False(면제 없음).
    """
    if not page_height:
        return False
    if y0 < page_height * (1 - frac):
        return False
    stripped = (text or "").strip()
    return bool(FOOTER_NUM_RE.match(stripped))


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


def _text_line_records(page):
    """페이지의 모든 텍스트 줄을 (y0, y1, size, text) 튜플 목록으로 평탄화.
    블록 내부 줄과 블록 간 첫/끝 줄을 동일 취급 — y0 기준 정렬해 페이지
    전체를 하나의 세로 흐름으로 본다(문단=블록 경계와 무관하게 간격을 본다)."""
    out = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") == 1:
            continue
        for ln in b.get("lines", []):
            y0, y1 = ln["bbox"][1], ln["bbox"][3]
            spans = ln.get("spans", [])
            text = "".join(s.get("text", "") for s in spans)
            if not text.strip():
                continue
            sizes = [s.get("size") for s in spans if s.get("text", "").strip()]
            size = max(sizes) if sizes else None
            out.append((y0, y1, size, text))
    out.sort(key=lambda r: r[0])
    return out


def _in_bottom_margin(y0, page_height, frac=0.12):
    """gap의 시작 y가 페이지 하단 frac(기본 12%) 구간에 있는지.

    pure 함수 — page-break 인접부의 자연스러운 공백(다음 페이지로 넘어가며
    생기는 하단 여백)을 구멍(T1 blank paragraph)과 구별하기 위한 판정만
    담당한다. page_height가 없으면(0/None) 항상 False(면제 없음, 기존 동작)."""
    if not page_height:
        return False
    return y0 >= page_height * (1 - frac)


def _table_bboxes(page):
    """페이지의 표 bbox 목록 [(y0, y1), ...]. check_tables()와 동일한
    find_tables() 탐지기를 재사용한다(오래된 PyMuPDF는 조용히 빈 목록)."""
    try:
        finder = page.find_tables()
    except AttributeError:
        return []
    out = []
    for tbl in getattr(finder, "tables", []):
        y0, y1 = tbl.bbox[1], tbl.bbox[3]
        if y1 - y0 < 15:
            continue  # check_tables()와 동일한 극소 bbox 오탐 필터
        out.append((y0, y1))
    return out


def check_line_spacing_uniformity(page, page_num=None, spacing_skip_pages=None):
    """줄 사이 세로 간격의 이상치를 검출 — 빈 문단(T1) 등 구멍을 잡는다.

    페이지 전체 텍스트 줄을 y0 순으로 흐름 하나로 보고, 인접 줄 간
    (next.y0 - prev.y1) 간격을 전부 모아 페이지 중앙값 대비 1.8배 초과를
    이상치로 본다. 단, 다음 줄의 글자 크기가 페이지 중앙값의 1.15배를
    넘으면(=섹션 제목 등 위계상 새 블록의 시작) 그 앞 간격은 면제한다.

    page_num(1-based, 생략 시 page.number+1)이 spacing_skip_pages에 있으면
    표지/요약 등 의도된 여백 페이지로 보고 이 체크를 통째로 건너뛴다(구조상
    통과 불가능한 표지 레이아웃 대응). spacing_skip_pages 생략 시 기존 동작과
    완전히 동일(가산적).

    페이지 skip 여부와 무관하게, gap의 시작 y가 페이지 높이 하단 10% 안에
    있으면 항상 면제한다(페이지 나눔 직전 여백은 구멍이 아니라 자연스러운
    page-break 아티팩트).

    세 가지 추가 면제(오탐 방지, 가산적 — 기존에 잡히던 진짜 구멍은 그대로 잡힘):
      (a) 그림 블록: 갭이 이미지 블록의 세로 범위와 겹치면 면제한다. 본문에
          그림을 끼워 넣으면 그 앞뒤로 텍스트 줄 사이 간격이 커지는데, 이는
          빈 문단 구멍이 아니라 그림이 차지하는 정상적인 공간이다.
      (b) footer 줄: 갭의 다음 줄(b)이 페이지번호 footer("- 1 -" 등, 이미
          _is_footer_line로 판정)면 면제한다 — 캡션 바로 아래 footer로
          이어지는 자연스러운 간격을 구멍으로 오인하지 않기 위함.
      (c) 표(table) 인접: 파이프라인이 표/그림 오브젝트 앞에 빈 줄 1개,
          캡션 뒤에 빈 줄 1개를 의도적으로 넣는 운영 규칙 때문에 그 갭이
          중앙값의 1.8배를 넘는 경우가 있다(gap_pt 19.8~26.2 vs median 6.0
          같은 실측 사례). check_tables()와 같은 find_tables() 탐지기로
          표 bbox를 구해, 갭의 y구간이 표 bbox와 겹치거나(overlap) 표
          bbox의 위/아래로 중앙값 줄높이(1줄) 이내에 닿아 있으면
          (touch — blank-before-table/caption-after-table 여백) 면제한다.
          순수 본문 중간의 동일 크기 갭은 표 bbox 근처가 아니므로 계속
          플래그된다(회귀 테스트로 고정).
    """
    if page_num is None:
        page_num = getattr(page, "number", None)
        if page_num is not None:
            page_num += 1
    if spacing_skip_pages and page_num in spacing_skip_pages:
        return []

    lines = _text_line_records(page)
    if len(lines) < 3:
        return []
    sizes = [r[2] for r in lines if r[2]]
    median_size = statistics.median(sizes) if sizes else 0.0
    page_height = page.rect.height
    img_spans = [(b[1], b[3]) for b in _blocks(page) if b[4] == "image"]
    table_spans = _table_bboxes(page)

    def _hits_image_span(y0, y1):
        return any(iy0 < y1 and iy1 > y0 for iy0, iy1 in img_spans)

    gaps = []
    for a, b in zip(lines, lines[1:]):
        gap = b[0] - a[1]
        gaps.append(gap)
    positive = [g for g in gaps if g > 0]
    if len(positive) < 2:
        return []
    median_gap = statistics.median(positive)
    if median_gap <= 0:
        return []

    line_heights = [r[1] - r[0] for r in lines if r[1] - r[0] > 1]
    median_line_height = statistics.median(line_heights) if line_heights else 12.0

    def _hits_table_span(y0, y1):
        tol = median_line_height
        return any(ty0 - tol < y1 and ty1 + tol > y0 for ty0, ty1 in table_spans)

    violations = []
    for (a, b), gap in zip(zip(lines, lines[1:]), gaps):
        if gap <= 0:
            continue
        if gap <= 1.8 * median_gap:
            continue
        next_size = b[2]
        if next_size and median_size and next_size > 1.15 * median_size:
            continue  # 섹션 제목 경계 — 면제
        if _in_bottom_margin(a[1], page_height):
            continue  # 페이지 하단 10% — page-break 아티팩트, 구멍 아님
        if _hits_image_span(a[1], b[0]):
            continue  # 그림이 차지하는 세로 구간 — 구멍 아님
        if _is_footer_line(b[3], b[0], page_height):
            continue  # 다음 줄이 페이지번호 footer — 구멍 아님
        if _hits_table_span(a[1], b[0]):
            continue  # 표 인접(blank-before/after) — 운영 규칙상 정상 여백
        if OBJECT_CAPTION_RE.match((a[3] or "").strip()):
            # (d) 직전 줄이 표/그림 캡션 — 캡션 뒤 빈 줄 1개는 운영 규칙상
            # 정상 여백(캡션은 표 bbox보다 1줄 아래라 (c)의 touch 허용창을
            # 벗어날 수 있어 별도 면제).
            continue
        violations.append({
            "page": None,  # analyze()에서 채움
            "gap_pt": round(gap, 1),
            "at_y": round(a[1], 1),
            "median_pt": round(median_gap, 1),
        })
    return violations


def check_figure_placement(page, col_width=None):
    """그림 배치 규칙: 폭 비율·캡션 존재·본문 겹침."""
    blks = _blocks(page)
    images = [b for b in blks if b[4] == "image"]
    if not images:
        return []
    texts = [b for b in blks if b[4] == "text"]
    if col_width is None:
        xs0 = [b[0] for b in blks]
        xs1 = [b[2] for b in blks]
        col_width = (max(xs1) - min(xs0)) if blks else page.rect.width

    lines = _text_line_records(page)
    violations = []
    for img in images:
        ix0, iy0, ix1, iy1, _ = img
        w = ix1 - ix0
        ratio = w / col_width if col_width else 0.0
        if not (0.45 <= ratio <= 0.95):
            violations.append({
                "page": None, "kind": "figure_width",
                "ratio": round(ratio, 2), "at_y": round(iy0, 1),
            })

        # 겹침: 텍스트 블록 bbox와 이미지 bbox가 겹치면 침범.
        for tx0, ty0, tx1, ty1, _ in texts:
            if ix0 < tx1 and ix1 > tx0 and iy0 < ty1 and iy1 > ty0:
                violations.append({
                    "page": None, "kind": "figure_overlap",
                    "at_y": round(iy0, 1),
                })
                break

        # 캡션: 이미지 아래 60pt 이내 첫 줄 또는 바로 위 줄이 캡션 형식인지.
        below = [ln for ln in lines if iy1 <= ln[0] <= iy1 + 60]
        above = [ln for ln in lines if ln[1] <= iy0]
        has_caption_below = bool(below) and bool(CAPTION_RE.match(below[0][3]))
        has_caption_above = bool(above) and bool(CAPTION_RE.match(above[-1][3]))
        if not has_caption_below and not has_caption_above:
            violations.append({
                "page": None, "kind": "caption_missing",
                "at_y": round(iy1, 1),
            })
    return violations


def check_tables(pdf_or_page):
    """표 규칙: 행별 열 개수 불일치(ragged), 헤더 셀 공백, 본문폭 초과.

    fitz.Page.find_tables()가 없는 오래된 PyMuPDF는 조용히 스킵(빈 목록)."""
    page = pdf_or_page
    try:
        finder = page.find_tables()
    except AttributeError:
        return []
    violations = []
    text_blks = [b for b in _blocks(page) if b[4] == "text"]
    col_width = (max(b[2] for b in text_blks) - min(b[0] for b in text_blks)
                 if text_blks else page.rect.width)
    for tbl in getattr(finder, "tables", []):
        try:
            rows = tbl.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue  # 1행짜리는 find_tables 오탐(일반 텍스트 줄) 가능성이 높음
        tb_h = tbl.bbox[3] - tbl.bbox[1]
        tb_w = tbl.bbox[2] - tbl.bbox[0]
        if tb_h < 15 or tb_w < 30:
            continue  # 극소 bbox — 표가 아니라 오탐
        col_counts = {len(r) for r in rows}
        if len(col_counts) > 1:
            violations.append({
                "page": None, "kind": "ragged",
                "col_counts": sorted(col_counts), "at_y": round(tbl.bbox[1], 1),
            })
        header = rows[0]
        if any((c is None or not str(c).strip()) for c in header):
            violations.append({
                "page": None, "kind": "header_cell_empty",
                "at_y": round(tbl.bbox[1], 1),
            })
        tw = tbl.bbox[2] - tbl.bbox[0]
        if col_width and tw > col_width * 1.02:
            violations.append({
                "page": None, "kind": "table_too_wide",
                "width_pt": round(tw, 1), "col_width_pt": round(col_width, 1),
                "at_y": round(tbl.bbox[1], 1),
            })
    return violations


def check_body_markers(page):
    """본문 청결 규칙: 방치된 인용 번호 `[N]`, 안내문 잔재 탐지."""
    violations = []
    for y0, y1, _size, text in _text_line_records(page):
        if CITATION_RE.search(text):
            violations.append({
                "page": None, "kind": "citation_marker",
                "at_y": round(y0, 1), "text": text[:80],
            })
        if GUIDE_RE.search(text):
            violations.append({
                "page": None, "kind": "guide_remnant",
                "at_y": round(y0, 1), "text": text[:80],
            })
    return violations


def _norm_ws(s):
    """공백류(개행/탭/연속 공백)를 단일 스페이스로 정규화하고 트림."""
    return re.sub(r"\s+", " ", s or "").strip()


def check_guide_file_remnants(page_text, guide_strings):
    """--guide-file로 준 안내문 원문 목록이 페이지 텍스트에 남아있는지 검사.

    page_text: 페이지 전체 텍스트(문자열, 이미 추출됨 — PDF 의존 없음, 순수 함수).
    guide_strings: 안내문 문자열 목록(JSON 파일에서 로드). 각 항목의 첫 20자를
    공백 정규화 후 substring 매칭한다 — 안내 문단은 길어서 20자면 충분히 특정적.

    반환: [{"kind": "guide_remnant", "text": <matched guide string 20자>}] 목록
    (page/at_y는 analyze()가 채움 — 여기선 page 단위 텍스트만 받으므로 생략).
    """
    if not guide_strings:
        return []
    norm_page = _norm_ws(page_text)
    violations = []
    for gs in guide_strings:
        needle = _norm_ws(gs)[:20]
        if needle and needle in norm_page:
            violations.append({"kind": "guide_remnant", "text": needle})
    return violations


def check_equations(page, expected_eq_count=0):
    """수식 규칙: 변환 안 된 LaTeX 문자열(`\\\\`, `pmatrix`, `\\frac`)이
    본문에 그대로 새어나오면 위반. expected_eq_count는 현재 미사용
    (글리프 런 판별이 신뢰불가라 스펙대로 스킵 — 첫 절반만 구현)."""
    violations = []
    for y0, y1, _size, text in _text_line_records(page):
        if LATEX_LEAK_RE.search(text):
            violations.append({
                "page": None, "kind": "latex_leak",
                "at_y": round(y0, 1), "text": text[:80],
            })
    return violations


def run_new_checks(pdf_path, expect_eq=0, guide_strings=None, spacing_skip_pages=None):
    """새 5개 체크를 문서 전체에 적용해 checks 딕셔너리를 만든다.

    guide_strings 생략(None/빈 목록) 시 기존 동작과 완전히 동일(가산적).
    지정 시 --guide-file 매치를 body_markers에 guide_remnant로 합류시킨다.
    spacing_skip_pages(1-based page 번호 집합) 생략 시 line_spacing_uniformity
    체크는 기존 동작과 완전히 동일(가산적) — 지정 시 해당 페이지를 건너뛴다.
    """
    doc = fitz.open(pdf_path)
    checks = {
        "line_spacing_uniformity": [],
        "figure_placement": [],
        "tables": [],
        "body_markers": [],
        "equations": [],
    }
    for i, page in enumerate(doc):
        pno = i + 1
        for v in check_line_spacing_uniformity(page, page_num=pno,
                                                spacing_skip_pages=spacing_skip_pages):
            v["page"] = pno
            checks["line_spacing_uniformity"].append(v)
        for v in check_figure_placement(page):
            v["page"] = pno
            checks["figure_placement"].append(v)
        for v in check_tables(page):
            v["page"] = pno
            checks["tables"].append(v)
        for v in check_body_markers(page):
            v["page"] = pno
            checks["body_markers"].append(v)
        if guide_strings:
            page_text = page.get_text("text")
            for v in check_guide_file_remnants(page_text, guide_strings):
                v["page"] = pno
                checks["body_markers"].append(v)
        for v in check_equations(page, expect_eq):
            v["page"] = pno
            checks["equations"].append(v)
    doc.close()
    return checks


def analyze(pdf_path, bottom_thr=25.0, gap_thr=3.0, expect_eq=0, guide_strings=None,
            spacing_skip_pages=None, gap_skip_pages=None, bottom_skip_pages=None):
    """gap_skip_pages(1-based page 번호 집합) 생략 시 max_gap_lines flag는 기존
    동작과 완전히 동일(가산적). 지정 시 해당 페이지는 max_gap_lines를 계산은
    하되(측정값은 보존) flags에 올리지 않는다 — 표지/양식 박스 내부처럼 구조상
    큰 간격이 의도된 페이지용(spacing_skip_pages와 대칭 설계).
    bottom_skip_pages: bottom_white flag 면제 페이지(측정값은 보존) — 요약처럼
    양식 고정 셀이 페이지 하단 공백을 강제하는 구조 페이지용(§P rubric: 양식
    구조 공백은 결함 아님). 마지막 쪽은 기존대로 항상 면제."""
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

        # 페이지번호 footer("- 1 -")는 콘텐츠가 아니라 undeletable 하단 상수라
        # gap 계산에서만 제외한다(content_bbox/bottom_white_pct는 무영향 —
        # 거기서 제외하면 표지 페이지 의도된 하단 여백이 새로 flag될 수 있음).
        footer_bboxes = _footer_block_bboxes(page, H)
        gap_blks = [b for b in blks
                    if not (b[4] == "text" and (b[0], b[1], b[2], b[3]) in footer_bboxes)]

        ordered = sorted(gap_blks, key=lambda b: b[1])
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

        pno = i + 1
        gap_exempt = bool(gap_skip_pages and pno in gap_skip_pages)

        flags = []
        is_last = (i == n - 1)
        if (not is_last and bottom_white > bottom_thr
                and not (bottom_skip_pages and (i + 1) in bottom_skip_pages)):
            flags.append(f"bottom_white {bottom_white:.1f}% > {bottom_thr}%")
        if max_gap_lines > gap_thr and not gap_exempt:
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

    checks = run_new_checks(pdf_path, expect_eq=expect_eq, guide_strings=guide_strings,
                             spacing_skip_pages=spacing_skip_pages)
    checks_pass = not any(checks.values())

    return {
        "ok": True,
        "file": str(pdf_path),
        "page_count": n,
        "thresholds": {"bottom_white_pct": bottom_thr, "max_gap_lines": gap_thr},
        "flagged_pages": flagged,
        "pass": (not flagged) and checks_pass,
        "pages": pages,
        "checks": checks,
    }


def parse_skip_pages(s):
    """'--spacing-skip-pages "1,2"' 형태 CLI 값 → {1, 2} int 집합.

    빈 문자열/None이면 None(면제 없음, 기존 동작 그대로 — 가산적)."""
    if not s:
        return None
    out = set()
    for part in str(s).split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out or None


def main():
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--bottom", type=float, default=25.0,
                    help="하단 공백 임계(%%), 마지막 쪽 제외")
    ap.add_argument("--gap", type=float, default=3.0,
                    help="블록 간 최대 간격 임계(줄 배수)")
    ap.add_argument("--expect-eq", type=int, default=0,
                    help="기대 수식 개수(현재 latex_leak 검사만 사용, 나머지 절반은 스킵)")
    ap.add_argument("--guide-file",
                    help="안내문 원문 목록 JSON(문자열 리스트). 생략 시 기존 동작 그대로 "
                         "— 지정 시 페이지 텍스트에 각 항목 첫 20자가 남아있으면 "
                         "guide_remnant로 flag")
    ap.add_argument("--spacing-skip-pages",
                    help="line_spacing_uniformity 체크를 건너뛸 1-based 페이지 번호, "
                         "콤마 구분(예: \"1,2\"). 표지/요약 등 의도된 여백 페이지용. "
                         "생략 시 기존 동작 그대로")
    ap.add_argument("--gap-skip-pages",
                    help="max_gap_lines(구멍) 체크를 건너뛸 1-based 페이지 번호, "
                         "콤마 구분(예: \"1,2\"). 양식 설계상 박스 내부/표지처럼 "
                         "구조적으로 큰 간격이 의도된 페이지용. 생략 시 기존 동작 그대로")
    ap.add_argument("--out", help="JSON 출력 파일(생략 시 stdout)")
    args = ap.parse_args()
    guide_strings = None
    if args.guide_file:
        guide_strings = json.loads(Path(args.guide_file).read_text(encoding="utf-8"))
    spacing_skip_pages = parse_skip_pages(args.spacing_skip_pages)
    gap_skip_pages = parse_skip_pages(args.gap_skip_pages)
    res = analyze(args.file, args.bottom, args.gap, expect_eq=args.expect_eq,
                  guide_strings=guide_strings, spacing_skip_pages=spacing_skip_pages,
                  gap_skip_pages=gap_skip_pages)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: pass={res['pass']} flagged={res['flagged_pages']}")
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
