#!/usr/bin/env python3
"""contact_sheet.py — PDF를 컨택트시트 PNG(그리드 썸네일)로 렌더.

레이아웃 QA용 "한눈에 보기" 도구. 페이지를 낱장으로 열어보지 않고, 여러
페이지를 한 이미지에 격자로 모아 전체 구성(공백, 그림 배치, 표 위치)을
빠르게 훑어보기 위한 것 — layout_qa.py의 수치 검증을 보완하는 시각 보조.

    python contact_sheet.py --pdf verify.pdf --out-dir DIR [--dpi 70] [--per-sheet 6] [--max-width 1600]

동작:
  - 각 페이지를 --dpi로 래스터화.
  - --per-sheet(기본 6)장씩 묶어 2열 x 3행(row-major) 그리드로 배치.
  - 각 셀 좌상단에 1-based 페이지 번호를 빨간 글씨로 표기(가독성 확보).
  - 셀 사이 얇은 회색 테두리.
  - 시트 폭이 --max-width를 넘으면 비율 유지 축소.
  - DIR/contact_1.png, contact_2.png ... 로 저장.
  - stdout에 JSON 1줄: {"pages": N, "sheets": [...], "cell_size": [w, h]}

실패(파일 없음/열기 실패): {"ok": false, "error": ...} 출력 후 exit 1.
"""

import argparse
import json
import sys
from pathlib import Path

import fitz  # pymupdf
from PIL import Image, ImageDraw, ImageFont

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from cli_io import utf8_stdio  # noqa: E402

BORDER_COLOR = (160, 160, 160)
BORDER_WIDTH = 1
LABEL_COLOR = (220, 0, 0)
LABEL_MARGIN = 4


def die(msg, code=1):
    line = json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.exit(code)


def _label_font(size):
    """페이지 번호 라벨용 폰트. 시스템 TTF가 없으면 PIL 기본 비트맵 폰트로 폴백."""
    candidates = (
        "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "arial.ttf",
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_pages(pdf_path, dpi):
    """PDF의 각 페이지를 PIL Image로 렌더. (images, page_count) 반환."""
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        die(f"failed to open PDF: {e}")
    if doc.page_count == 0:
        die("PDF has no pages")
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    images = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    except Exception as e:
        die(f"failed to render page: {e}")
    finally:
        doc.close()
    return images, len(images)


def build_sheet(cell_images, cols, rows, cell_w, cell_h, max_width):
    """cell_images(각 (page_num, PIL.Image) 튜플, row-major 순서)를
    cols x rows 그리드 한 장으로 합성. 빈 칸은 흰 배경 유지.
    max_width 초과 시 비율 유지 축소. 완성 PIL.Image 반환."""
    sheet_w = cols * cell_w
    sheet_h = rows * cell_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = _label_font(max(14, cell_h // 20))

    for idx, (page_num, img) in enumerate(cell_images):
        col = idx % cols
        row = idx // cols
        x0 = col * cell_w
        y0 = row * cell_h

        thumb = img.copy()
        thumb.thumbnail((cell_w, cell_h), Image.LANCZOS)
        paste_x = x0 + (cell_w - thumb.width) // 2
        paste_y = y0 + (cell_h - thumb.height) // 2
        sheet.paste(thumb, (paste_x, paste_y))

        draw.rectangle(
            [x0, y0, x0 + cell_w - 1, y0 + cell_h - 1],
            outline=BORDER_COLOR, width=BORDER_WIDTH,
        )

        label = str(page_num)
        draw.text(
            (x0 + LABEL_MARGIN, y0 + LABEL_MARGIN), label,
            fill=LABEL_COLOR, font=font,
            stroke_width=2, stroke_fill=(255, 255, 255),
        )

    if sheet_w > max_width:
        scale = max_width / sheet_w
        new_size = (max_width, max(1, round(sheet_h * scale)))
        sheet = sheet.resize(new_size, Image.LANCZOS)

    return sheet


def make_contact_sheets(pdf_path, out_dir, dpi=70, per_sheet=6, max_width=1600,
                         cols=2):
    """PDF -> DIR/contact_N.png 여러 장. 반환: analyze()류 결과 dict."""
    images, page_count = render_pages(pdf_path, dpi)
    rows = -(-per_sheet // cols)  # ceil

    max_cell_w = max(img.width for img in images)
    max_cell_h = max(img.height for img in images)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets = []
    for start in range(0, page_count, per_sheet):
        chunk = images[start:start + per_sheet]
        cell_images = [(start + i + 1, img) for i, img in enumerate(chunk)]
        sheet = build_sheet(cell_images, cols, rows, max_cell_w, max_cell_h,
                             max_width)
        sheet_idx = len(sheets) + 1
        out_path = out_dir / f"contact_{sheet_idx}.png"
        sheet.save(out_path)
        sheets.append(str(out_path))

    return {
        "pages": page_count,
        "sheets": sheets,
        "cell_size": [max_cell_w, max_cell_h],
    }


def main():
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True, help="입력 PDF 경로")
    ap.add_argument("--out-dir", required=True, help="contact_N.png 출력 디렉터리")
    ap.add_argument("--dpi", type=float, default=70,
                     help="페이지 래스터화 해상도(기본 70)")
    ap.add_argument("--per-sheet", type=int, default=6,
                     help="시트 1장당 페이지 수(기본 6, 2열x3행)")
    ap.add_argument("--max-width", type=int, default=1600,
                     help="시트 최대 폭(px). 초과 시 비율 유지 축소(기본 1600)")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        die(f"PDF not found: {pdf_path}")
    if args.per_sheet < 1:
        die("--per-sheet must be >= 1")

    result = make_contact_sheets(
        str(pdf_path), args.out_dir, dpi=args.dpi,
        per_sheet=args.per_sheet, max_width=args.max_width,
    )
    text = json.dumps(result, ensure_ascii=False)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
