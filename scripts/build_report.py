#!/usr/bin/env python3
"""build_report.py — report bundle(content.md)을 hwp-master ops JSON으로 변환.

명세: report-pipeline/references/bundle_spec.md (Stage 4 출력 → Stage 5 입력).
content.md를 결정론적으로 파싱해 com_backend.py edit에 그대로 줄 수 있는 ops를
만든다. 미지 태그·SECTION 앵커 불일치·수식 sanity 실패는 우회 없이 중단한다.

    python build_report.py --content bundle/content.md [--form 양식.hwp] [--dry-run]

--dry-run: 한글(COM) 미실행, ops만 stdout. 양식 inspect 대조는 생략.

태그 예시:
    [[TABLE caption="표1" cols=10,16,12,9,10,43 pt=9]]   // 열 너비 비율(정규화됨) + 셀 글자크기
    | 헤더1 | 헤더2 | ...
    [[/TABLE]]
    cols/pt 생략 시 구동작(균등폭, pt 미지정=앵커 상속) 그대로 — 후방호환.

    [[EQ latex="..."]]           // bare = 인라인(본문 문단 중간, treatAsChar)
    [[EQ display latex="..."]]   // display 플래그 = 기존 동작(자기 문단, 가운데)
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eqn import latex_to_hwpeqn, hwpeqn_sanity_check  # noqa: E402

TAG_LINE = re.compile(r"^\[\[(/?[A-Za-z]+)(.*?)\]\]\s*$")
KNOWN_TAGS = {"EQ", "FIG", "TABLE", "/TABLE", "URL"}
URL_RE = re.compile(r"^https?://\S+$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# 인라인(문단 중간) [[TAG ...]] 스캐너: 태그 본문 안 큰따옴표로 감싼 속성값에
# `]`가 들어있어도(예: latex="x[n] = ...") 오탐 없이 진짜 `]]` 종료만 닫는다.
# 그룹1=태그명(EQ/URL 등), 그룹2=태그 본문(따옴표 안 내용 포함, parse_attrs로 재사용).
# `(?:"[^"]*"|[^\]"]|\](?!\]))*` — 따옴표 문자열 | 비-]-비-" 문자 | 단일 `]`(다음이
# `]`가 아닐 때만, lookahead로 진짜 종료 `]]`와 구분).
INLINE_TAG_RE = re.compile(
    r'\[\[([A-Za-z]+)((?:"[^"]*"|[^\]"]|\](?!\]))*)\]\]'
)
INLINE_TAG_NAMES = {"EQ", "URL"}  # 문단 중간에 허용하는 인라인 태그(FIG/TABLE은 줄 단위만)


def split_bold_segments(text):
    """`**굵게**` 스팬을 [{"text":..,"bold":bool}] 세그먼트로 분리.

    `**` 미포함 시 None을 돌려준다(호출부가 구동작 단일 insert_text로
    폴백 — ops 시그니처 하위호환 유지). 비어있지 않은 세그먼트만 남긴다.
    escape 규칙 없음(리터럴 `**`는 드묾 — 명세 가정).
    """
    if "**" not in text:
        return None
    segs = []
    pos = 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            segs.append({"text": text[pos:m.start()], "bold": False})
        if m.group(1):
            segs.append({"text": m.group(1), "bold": True})
        pos = m.end()
    if pos < len(text):
        segs.append({"text": text[pos:], "bold": False})
    return [s for s in segs if s["text"]]


def die(msg, code=2):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)


def split_inline_para(text, line_no=0):
    """문단 텍스트를 스캔해 인라인 [[EQ ...]]/[[URL ...]] 태그를 뽑아낸다.

    반환: [{'kind':'text','text':..} | {'kind':'eq',display,latex,hwpeqn}
           | {'kind':'url',url,text}] 순서 리스트. 태그가 하나도 없으면
           단일 text 세그먼트([{'kind':'text','text':원문}])를 돌려줘 호출부가
           구동작(단일 para 블록)과 동일하게 취급할 수 있게 한다.

    INLINE_TAG_RE는 quote-aware라 latex="x[n] = ..." 처럼 속성값 안에 `]`가
    있어도 그 지점에서 태그가 끊기지 않는다(진짜 종료는 `]]`만). FIG/TABLE은
    문단 중간 삽입을 지원하지 않으므로(자체 레이아웃 필요) 여기서 만나면
    바로 die — 우회하지 않고 명시적으로 실패시킨다.
    """
    segs = []
    pos = 0
    for m in INLINE_TAG_RE.finditer(text):
        name = m.group(1)
        if name not in INLINE_TAG_NAMES:
            if name in KNOWN_TAGS or f"/{name}" in KNOWN_TAGS:
                die(f"[[{name}]]은 문단 중간에 올 수 없음(줄 단위 태그): "
                    f"{text[m.start():m.end()][:80]!r} (line {line_no + 1})")
            continue  # 미지 대괄호 패턴은 일반 텍스트로 취급(오탐 방지)
        if m.start() > pos:
            segs.append({"kind": "text", "text": text[pos:m.start()]})
        attrs, flags = parse_attrs(m.group(2))
        if name == "EQ":
            segs.append({
                "kind": "eq",
                "display": "display" in flags,
                "latex": attrs.get("latex"),
                "hwpeqn": attrs.get("hwpeqn"),
            })
        elif name == "URL":
            href = attrs.get("href") or attrs.get("url")
            if not href:
                die(f"[[URL]] 태그에 href 없음 (line {line_no + 1})")
            segs.append({"kind": "url", "url": href, "text": attrs.get("text", "")})
        pos = m.end()
    if pos < len(text):
        segs.append({"kind": "text", "text": text[pos:]})
    if not segs:
        segs = [{"kind": "text", "text": text}]
    return segs


def parse_attrs(s):
    """key="val" / key=val / 단독 플래그(display|inline)를 추출."""
    attrs, flags = {}, []
    for m in re.finditer(r'(\w+)="([^"]*)"|(\w+)=(\S+)|([A-Za-z]+)', s):
        if m.group(1) is not None:
            attrs[m.group(1)] = m.group(2)
        elif m.group(3) is not None:
            attrs[m.group(3)] = m.group(4)
        elif m.group(5) is not None:
            flags.append(m.group(5))
    return attrs, flags


def _parse_col_ratios(cols_attr, line_no):
    """[[TABLE cols=10,16,12,9,10,43]] → 정규화된 비율 리스트(합=1.0).

    cols_attr 없으면 None(구동작 — 균등폭). 있으면 콤마 분리 후 각 항목을
    float로 파싱, 합으로 나눠 정규화한다(원값이 %든 임의 단위든 무관).
    """
    if not cols_attr:
        return None
    parts = [p.strip() for p in cols_attr.split(",") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        die(f"[[TABLE cols=]] 숫자 파싱 실패: {cols_attr!r} (line {line_no + 1})")
    bad = [n for n in nums if n <= 0]
    if bad:
        die(f"[[TABLE cols=]] 값은 모두 0보다 커야 함 (0 이하: {bad}): "
            f"{cols_attr!r} (line {line_no + 1})")
    total = sum(nums)
    if total <= 0:
        die(f"[[TABLE cols=]] 합이 0 이하: {cols_attr!r} (line {line_no + 1})")
    return [n / total for n in nums]


def parse_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        die("YAML front matter 종료 '---' 없음")
    fm, body = text[3:end], text[end + 4:]
    meta = {}
    for line in fm.splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()  # 인라인 주석 제거
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"')
    return meta, body


# build.yaml에서 meta로 병합할 빌드 노브(문자열/불리언 스칼라). fill 블록은 별도 처리.
BUILD_YAML_KEYS = {
    "base_pt", "caption_pt", "line_spacing", "binding", "abstract",
    "title", "title_anchor", "collapse_blank_runs",
}
# 리스트 값으로 파싱할 최상위 키(style_diff.py의 색 허용 목록 등).
# delete_texts: 삭제할 안내문 문자열 목록(양식 잔재 정리, find_delete op로 변환).
BUILD_YAML_LIST_KEYS = {"allow_colors", "delete_texts"}
FILL_KEYS = {"min_figures", "target_pages", "bottom_white_max", "max_gap_lines"}


def _strip_quotes(s):
    """둘러싼 작은/큰따옴표 1쌍을 제거(내부 문자는 건드리지 않음)."""
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _yaml_scalar(v):
    """flat build.yaml 값 파서(stdlib). 따옴표 제거, 인라인 주석 제거.

    `[#0000FF, #FF0000]` 같은 인라인 리스트에서 콤마 뒤 `#FF0000`을 주석으로
    오인해 통째로 잘라먹지 않도록, 대괄호로 감싸인 값은 주석 제거를 건너뛴다
    (리스트 안에 실제 YAML 주석을 쓰는 관습이 없으므로 안전).
    """
    stripped = v.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        v = re.sub(r"\s+#.*$", "", v).strip()
    else:
        v = stripped
    return _strip_quotes(v)


def _yaml_list(v):
    """[lo, hi] 형태의 flat 리스트만 파싱. 요소는 int 시도 후 원문.

    각 항목은 분리 후 따옴표를 벗긴다 — 그렇지 않으면 `["#0000FF"]` 같은
    quoted 항목이 리터럴 따옴표를 포함한 채(`'"#0000FF"'`) 남는다.
    """
    v = _yaml_scalar(v)
    inner = v.strip().lstrip("[").rstrip("]")
    out = []
    for part in inner.split(","):
        part = _strip_quotes(part.strip())
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            out.append(part)
    return out


# 콤마 포함 자유 텍스트 항목이 들어갈 수 있는 키 → block-list('- "..."') 전용.
# _yaml_list의 콤마 split은 이런 문구를 깨뜨리므로 별도 경로로 처리한다.
# tidy_blank_before/after: 앵커 지점의 빈 문단을 정확히 원하는 개수로 못박는
# anchor-targeted 정리(구 collapse_blank_runs 대체 — bundle-spec 헤딩 규칙).
# page_break_before: 앵커 문단이 새 페이지 맨 위에서 시작하도록 강제(T11). 주의:
# 같은 앵커를 tidy_blank_before에도 넣지 말 것 — tidy_blank_before(오프라인 XML
# 정리, tidy_hwpx.py)가 앵커 앞 문단을 정리하며 페이지 나누기가 걸린 빈 문단을
# 함께 먹어버릴 수 있다(두 키는 상호 배타적으로 같은 앵커를 공유해선 안 됨).
# keep_with_next: prefix로 시작하는 모든 문단(표 캡션 등)에 keepWithNext=1을
# 적용(오프라인 tidy_hwpx.py --keep-with-next). tidy_blank_*/page_break_before와
# 동일하게 COM op이 아니라 fill_report.py가 hwpx 저장 뒤 오프라인으로 처리한다.
BUILD_YAML_BLOCK_LIST_KEYS = {
    "delete_texts", "tidy_blank_before", "tidy_blank_after", "page_break_before",
    "keep_with_next",
}


def parse_build_yaml(path):
    """build.yaml(플랫 + fill: 블록)을 stdlib로 파싱. pyyaml 미사용.

    반환: {meta_knobs..., 'fill': {min_figures,target_pages,bottom_white_max,
    max_gap_lines}}. fill 하위는 들여쓰기 2칸으로 인식한다.

    BUILD_YAML_BLOCK_LIST_KEYS(예: delete_texts)는 flat `[a, b]` 대신
    들여쓰기된 `- "item"` 블록 리스트로만 파싱한다(항목에 콤마가 흔함).
    """
    text = Path(path).read_text(encoding="utf-8")
    result, fill = {}, {}
    in_fill = False
    in_block_list = None  # 현재 수집 중인 BUILD_YAML_BLOCK_LIST_KEYS 키 이름
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.strip().startswith("#"):
            i += 1
            continue
        indented = raw[:1].isspace()
        line = raw.strip()
        if in_block_list is not None and indented and line.startswith("-"):
            item = line[1:].strip()
            result.setdefault(in_block_list, []).append(_yaml_scalar(item))
            i += 1
            continue
        in_block_list = None  # 블록 리스트는 들여쓰기 끊기거나 '-' 아니면 종료
        if line.rstrip() == "fill:" or line.rstrip().startswith("fill:"):
            in_fill = True
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if in_fill and indented:
            if k in ("target_pages",):
                fill[k] = _yaml_list(v)
            elif k in ("min_figures", "bottom_white_max", "max_gap_lines"):
                sv = _yaml_scalar(v)
                try:
                    fill[k] = int(sv)
                except ValueError:
                    fill[k] = sv
            else:
                fill[k] = _yaml_scalar(v)
            i += 1
            continue
        # 최상위 키 → fill 블록 종료.
        in_fill = False
        # block-list 키 줄의 인라인 주석 허용: `tidy_blank_before:  # 설명` (run-9 사고)
        if k in BUILD_YAML_BLOCK_LIST_KEYS and not re.sub(r"#.*$", "", v).strip():
            in_block_list = k
            result.setdefault(k, [])
        elif k in BUILD_YAML_LIST_KEYS:
            result[k] = _yaml_list(v)
        elif k in BUILD_YAML_KEYS:
            result[k] = _yaml_scalar(v)
        i += 1
    if fill:
        result["fill"] = fill
    return result


def find_build_yaml(content_path):
    """content.md 옆(bundle) 또는 리포트 루트(상위)에서 build.yaml 탐색."""
    d = Path(content_path).resolve().parent
    for cand in (d / "build.yaml", d.parent / "build.yaml"):
        if cand.exists():
            return cand
    return None


def merge_meta(meta, build_cfg):
    """build.yaml이 content.md front-matter 위에 덮어쓴다(빌드 노브 한정)."""
    merged = dict(meta)
    for k in BUILD_YAML_KEYS:
        if k in build_cfg:
            merged[k] = build_cfg[k]
    if "fill" in build_cfg:
        merged["fill"] = build_cfg["fill"]
    if "delete_texts" in build_cfg:
        merged["delete_texts"] = build_cfg["delete_texts"]
    if "tidy_blank_before" in build_cfg:
        merged["tidy_blank_before"] = build_cfg["tidy_blank_before"]
    if "tidy_blank_after" in build_cfg:
        merged["tidy_blank_after"] = build_cfg["tidy_blank_after"]
    if "page_break_before" in build_cfg:
        merged["page_break_before"] = build_cfg["page_break_before"]
    if "keep_with_next" in build_cfg:
        merged["keep_with_next"] = build_cfg["keep_with_next"]
    return merged


def parse_content(text):
    """content.md → (meta, [sections]). sections[i] = {anchor, blocks}.

    blocks: {'kind':'para','text':..} | {'kind':'eq',..} | {'kind':'fig',..}
            | {'kind':'table','caption':..,'data':[[..]]}
    """
    meta, body = parse_front_matter(text)
    sections, cur, para = [], None, []
    lines = body.splitlines()
    i = 0

    def flush_para():
        if para:
            text_ = " ".join(p.strip() for p in para if p.strip())
            if text_ and cur is not None:
                # 인라인 [[EQ]]/[[URL]]이 문단 중간에 있으면 여러 블록으로
                # 쪼갠다(latex_leak 버그: 과거엔 태그가 그대로 리터럴 텍스트로
                # 새어나갔다). 태그가 없으면 segs == [{'kind':'text',...}]
                # 하나뿐이라 기존 단일 para 블록과 동일하게 동작(하위호환).
                segs = split_inline_para(text_, len(sections))
                emitted = []
                for s in segs:
                    if s["kind"] == "text":
                        if s["text"].strip():
                            emitted.append({"kind": "para", "text": s["text"]})
                    elif s["kind"] == "eq":
                        emitted.append(s)
                    elif s["kind"] == "url":
                        emitted.append(s)
                # 문단 줄바꿈(\r\n)은 이 문단을 이룬 조각들 중 "마지막" 것에만
                # 걸어야 한다 — 아니면 인라인 EQ 앞뒤 텍스트가 각자 별도
                # 문단으로 쪼개져 줄이 끊긴다. 태그 없는 기존 단일 조각 문단은
                # emitted가 1개뿐이라 그 하나가 그대로 마지막이 되어 구동작과
                # 동일(para_end 생략 시 build_ops가 True로 취급 — 하위호환).
                for idx, blk in enumerate(emitted):
                    if idx < len(emitted) - 1:
                        blk["para_end"] = False
                cur["blocks"].extend(emitted)
        para.clear()

    while i < len(lines):
        line = lines[i]
        sec = re.match(r"^##\s*SECTION:\s*(.+?)\s*$", line)
        if sec:
            flush_para()
            cur = {"anchor": sec.group(1), "blocks": []}
            sections.append(cur)
            i += 1
            continue
        tag = TAG_LINE.match(line.strip())
        if tag:
            flush_para()
            name = tag.group(1)
            base = name.lstrip("/")
            if base not in {"EQ", "FIG", "TABLE", "URL"}:
                die(f"미지 태그: [[{name}]] (line {i + 1})")
            if cur is None:
                die(f"SECTION 밖의 태그: [[{name}]] (line {i + 1})")
            attrs, flags = parse_attrs(tag.group(2))
            if name == "URL":
                href = attrs.get("href") or attrs.get("url")
                if not href:
                    die(f"[[URL]] 태그에 href 없음 (line {i + 1})")
                cur["blocks"].append({
                    "kind": "url", "url": href, "text": attrs.get("text", ""),
                })
            elif name == "EQ":
                # 기본값 뒤집힘: bare [[EQ ...]] = 인라인(본문 문단 중간,
                # treatAsChar="1") — 옛 "inline" 플래그는 이제 아무 효과 없음
                # (기본이 이미 인라인이므로 no-op). [[EQ display ...]]만 옛
                # 동작(자기 문단·가운데)을 유지한다.
                cur["blocks"].append({
                    "kind": "eq",
                    "display": "display" in flags,
                    "latex": attrs.get("latex"),
                    "hwpeqn": attrs.get("hwpeqn"),
                })
            elif name == "FIG":
                cur["blocks"].append({
                    "kind": "fig",
                    "file": attrs.get("file"),
                    "width": float(attrs.get("width", 0)) or None,
                    "caption": attrs.get("caption", ""),
                })
            elif name == "TABLE":
                rows, i = [], i + 1
                while i < len(lines) and not lines[i].strip().startswith("[[/TABLE]]"):
                    row = lines[i].strip()
                    if row.startswith("|"):
                        cells = [c.strip() for c in row.strip("|").split("|")]
                        if not all(set(c) <= set("-: ") for c in cells):  # 구분선 스킵
                            rows.append(cells)
                    i += 1
                if i >= len(lines):
                    die("[[TABLE]] 에 [[/TABLE]] 종료 없음")
                # cols=10,16,12,9,10,43: 열별 너비 비율(정규화 전 원값, 합 임의).
                # pt=9: 표 안 텍스트 크기. 둘 다 없으면 구동작(균등폭, 앵커 상속) 그대로.
                cur["blocks"].append({
                    "kind": "table", "caption": attrs.get("caption", ""), "data": rows,
                    "col_ratios": _parse_col_ratios(attrs.get("cols"), i - 1),
                    "font_pt": int(attrs["pt"]) if attrs.get("pt") else None,
                })
            i += 1
            continue
        if URL_RE.match(line.strip()):   # BUG5: URL 단독 줄 → 링크 블록(빈 줄 불필요)
            flush_para()
            if cur is not None:
                cur["blocks"].append({"kind": "url", "url": line.strip(),
                                      "text": ""})
            i += 1
            continue
        if line.strip() == "":
            flush_para()
        else:
            para.append(line)
        i += 1
    flush_para()
    return meta, sections


def _is_true(v, default=True):
    if v is None:
        return default
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def load_form_profile(path):
    """form_inspect.py profile JSON을 읽는다. 없거나 파싱 실패면 None(무음 스킵) —
    --form-profile은 선택 입력이라 부재를 에러로 취급하지 않는다."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_label_cell_anchors(form_profile):
    """table_map에서 '라벨 셀 텍스트 == 셀 전체 텍스트'이고(static·shaded)
    바로 다음 행(같은 열)이 fill_target인 셀들을 찾아 {anchor_text: True} 셋으로
    돌려준다(T12 — cell_below 대상 판별).

    build_report가 SECTION 앵커와 대조해, 앵커 문구가 이 집합에 있으면 그
    섹션의 goto_text에 cell_below를 건다. table_map이 없거나 형태가 다르면
    빈 dict(가드 미작동 — 기존 next_para/T8 경로로 폴백, 우회 아님 단순 비활성).
    """
    anchors = set()
    if not form_profile:
        return anchors
    for table in form_profile.get("table_map") or []:
        cells = table.get("cells") or []
        by_addr = {(c["addr"]["row"], c["addr"]["col"]): c for c in cells
                   if c.get("addr")}
        for (row, col), cell in by_addr.items():
            if cell.get("classification") != "static" or not cell.get("shaded"):
                continue
            text = (cell.get("text_preview") or "").strip()
            if not text:
                continue
            below = by_addr.get((row + 1, col))
            if below is not None and below.get("classification") == "fill_target":
                anchors.add(text)
    return anchors


def build_ops(meta, sections, bundle_dir, warnings=None, label_cell_anchors=None):
    """meta+sections → ops 리스트. warnings(선택, 리스트)를 주면 인라인으로
    뒤집힌 EQ 등 빌드 경고 문자열을 append한다(반환값 시그니처는 하위호환
    유지를 위해 ops 단일 값 그대로 — 리스트 in-place mutation으로 전달).

    label_cell_anchors(선택, set): find_label_cell_anchors()가 반환하는
    "표의 라벨 셀 텍스트" 집합. 섹션 앵커가 여기 있으면 goto_text에
    cell_below:true를 건다(T12 — 요약문류 1열 표 라벨 셀 버그 수정).
    """
    label_cell_anchors = label_cell_anchors or set()
    base_pt = int(meta.get("base_pt", 10))               # 본문 기본 10pt
    caption_pt = int(meta.get("caption_pt", 9))          # 캡션 9pt (제출본 실측 관습)
    binding = (meta.get("binding") or "book").strip().lower()
    abstract = _is_true(meta.get("abstract"), default=True)
    ops = []
    # BUG3: 제출용이면 좌우 대칭 여백으로 먼저 전환.
    if binding == "submit":
        ops.append({"op": "page_binding", "mode": "submit"})
    title, t_anchor = meta.get("title"), meta.get("title_anchor")
    if title and t_anchor:
        ops.append({"op": "replace_all", "find": t_anchor, "replace": title})
    # BUG6: 초록 off면 양식의 초록 표(캡션 포함)를 통째로 제거.
    if not abstract:
        ai = meta.get("abstract_table_index", 1)
        ops.append({"op": "delete_ctrls", "types": ["tbl"], "index": int(ai)})
    # delete_texts(build.yaml): 양식 안내문 잔재 제거. HR런 v4 find_delete 관습과
    # 동일 스키마(all/required:false) — 문서에 없어도 배치를 abort하지 않는다.
    for dt in meta.get("delete_texts") or []:
        ops.append({"op": "find_delete", "text": dt, "all": True, "required": False})
    # page_break_before(build.yaml, T11): 앵커 문단이 새 페이지 맨 위에서
    # 시작하도록 강제. delete_texts 직후, 섹션 삽입(goto_text 등) 이전에 배치
    # — 삭제로 문서가 짧아진 뒤 페이지 나누기를 걸어야 페이지 경계가 어긋나지
    # 않는다. 주의: 이 앵커는 tidy_blank_before에 있으면 안 된다(위 상수 주석 참고).
    for pb in meta.get("page_break_before") or []:
        ops.append({"op": "page_break_before", "text": pb, "required": False})
    figs_dir = Path(bundle_dir) / "figures"
    for si, sec in enumerate(sections):
        # BUG4: 제목 앞 빈 문단 1개 보장(이전 본문과 제목 분리). 단 첫 섹션은 앞에 분리할
        # 본문이 없고(머리말/초록 영역만 있음), 그 영역에 빈 문단을 넣으면 HWP가 인접
        # 글자크기를 첫 제목에 번지게 하므로 건너뛴다(첫 제목 원본 크기 보존).
        if si > 0:
            ops.append({"op": "insert_blank_before", "text": sec["anchor"]})
        # 제목 문단을 쪼개지 않고 다음 문단 맨 앞으로 가서 본문을 넣는다(제목 글자크기
        # 보존). 제목 끝에서 \r\n 분리하면 pending 크기가 제목에 번져 제목이 오염된다.
        goto_op = {"op": "goto_text", "text": sec["anchor"], "next_para": True}
        if sec["anchor"] in label_cell_anchors:
            # T12: 앵커가 1열 표의 라벨 셀 전체 텍스트(예: "요약문") — next_para의
            # 같은-셀 문단 분리(T8)로는 다음 행의 fill_target 셀에 닿지 못한다.
            # com_backend.op_goto_text가 cell_below를 보면 next_para 대신
            # TableLowerCell로 표 셀 자체를 이동한다.
            goto_op["cell_below"] = True
        ops.append(goto_op)
        for b in sec["blocks"]:
            if b["kind"] == "para":
                # para_end=False: 인라인 [[EQ]]/[[URL]] 분리로 생긴 문단 내부
                # 중간 조각(예: EQ 앞의 리드인 텍스트) — 줄바꿈 없이 이어붙여야
                # 뒤따르는 인라인 EQ가 같은 줄에 붙는다. 키 없으면(구동작·단일
                # 조각 문단) True로 취급해 기존과 동일하게 항상 줄바꿈.
                #
                # T12: 줄바꿈은 더 이상 텍스트에 리터럴 "\r\n"을 붙이지 않고
                # break_after(BreakPara Run)로 건다 — insert_text("\r\n")는
                # pending 글자크기를 다음 문단에 번지게 한다(hwp-com-charshape-
                # quirks 메모, 요약문 표 셀에서 문단이 하나로 뭉개지던 원인과
                # 동일 계열). BreakPara는 주변 서식을 오염 없이 상속한다.
                para_end = b.get("para_end", True)
                # BUG1+2: 본문은 앵커(제목) 서식 상속 금지 — base_pt 강제.
                if para_end and URL_RE.match(b["text"]):  # BUG5: URL 단독 문단 → 링크 필드.
                    ops.append({"op": "insert_hyperlink", "url": b["text"],
                                "pt": base_pt})
                    ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                                "break_after": True})
                else:
                    # `**굵게**` 마크다운 스팬 지원: ** 없으면 segments 키 자체를
                    # 생략해 구동작(단일 text 문자열) 그대로 유지(하위호환). 있으면
                    # "text"는 마커를 벗긴 순수 텍스트(segments 미지원 소비자용
                    # 폴백), "segments"가 실제 굵게 렌더링에 쓰인다.
                    segs = split_bold_segments(b["text"])
                    if segs is not None:
                        plain = "".join(s["text"] for s in segs)
                        op = {"op": "insert_text", "text": plain,
                              "pt": base_pt, "segments": segs}
                    else:
                        # ** 없으면 segments 키 자체를 생략 → com_backend의 단일-런
                        # 경로(하위호환). 골든 ops·backward-compat 테스트가 이 계약을
                        # 고정한다(com_backend op_insert_text 주석과 일치).
                        op = {"op": "insert_text", "text": b["text"],
                              "pt": base_pt}
                    if para_end:
                        op["break_after"] = True
                    ops.append(op)
            elif b["kind"] == "url":      # BUG5: 명시 [[URL]] 태그.
                para_end = b.get("para_end", True)
                ops.append({"op": "insert_hyperlink", "url": b["url"],
                            "text": b.get("text") or b["url"], "pt": base_pt})
                if para_end:
                    ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                                "break_after": True})
            elif b["kind"] == "eq":
                op = {"op": "insert_equation", "base_pt": base_pt,
                      "display": b["display"]}
                if not b["display"] and warnings is not None:
                    # 기본값 뒤집힘 경고: bare [[EQ ...]]는 이제 인라인이 기본이라
                    # 예전에 "자기 문단·가운데"로 조판되던 수식이 본문 중간에
                    # 낄 수 있다. 의도된 표시라면 [[EQ display ...]]로 명시할 것.
                    warnings.append(
                        f"EQ 인라인으로 조판됨(구 기본값=display였음): "
                        f"{(b.get('latex') or b.get('hwpeqn') or '')!r} "
                        f"(섹션 {sec['anchor']!r}) — display 유지하려면 "
                        f"[[EQ display ...]]로 명시")
                if b.get("hwpeqn"):
                    op["hwpeqn"] = b["hwpeqn"]
                elif b.get("latex"):
                    script, warns = latex_to_hwpeqn(b["latex"])
                    ok, msg = hwpeqn_sanity_check(script)
                    if not ok:
                        die(f"수식 sanity 실패({msg}): {b['latex']} -> {script}")
                    op["hwpeqn"] = script
                else:
                    die("EQ 태그에 latex/hwpeqn 둘 다 없음")
                ops.append(op)
            elif b["kind"] == "fig":
                # Rule 2(operator): 캡션은 객체와 붙어 그 아래에, 본문과는 앞뒤로
                # 빈 문단 1개 간격. 고정 순서: (blank) -> 그림 -> 캡션 -> (blank)
                # -> 본문. 빈 문단은 insert_text(text="", break_after=True)로
                # 명시 발행한다(기존 blank-line 관례, URL 블록과 동일 패턴) —
                # 주변이 이미 빈 문단을 제공하는지 추측하지 않고 항상 정확히
                # 하나씩 발행해 결정론을 유지한다(이중 공백 방지는 여기서 이
                # 하나만 내는 것으로 보장, 다른 데서 또 내지 않음).
                if not b["file"]:
                    die("FIG 태그에 file 없음")
                width = b["width"] or 110.0  # P4: 미지정 시 110mm (본문 150mm의 ~73%)
                ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                            "break_after": True})
                ops.append({"op": "insert_picture",
                            "path": str((figs_dir / b["file"]).resolve()),
                            "width_mm": width, "own_paragraph": True})
                if b["caption"]:  # P2: 빈 캡션 생략
                    ops.append({"op": "insert_text", "text": b["caption"],
                                "pt": caption_pt, "break_after": True})
                    ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                                "break_after": True})
            elif b["kind"] == "table":
                # Rule 2: 고정 순서 (blank) -> 표 -> 캡션 -> (blank) -> 본문.
                # 과거엔 캡션이 표 '위'에 있었다 — operator 지시로 표 아래로 이동.
                ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                            "break_after": True})
                table_op = {"op": "insert_table", "data": b["data"],
                            "treat_as_char": True}
                # col_ratios/font_pt: 없으면(구 태그) 키 자체를 생략해 후방호환 유지
                # (com_backend op_insert_table은 두 키 모두 optional).
                ratios = b.get("col_ratios")
                if ratios is not None:
                    ncols = len(b["data"][0]) if b["data"] else 0
                    if len(ratios) != ncols:
                        die(f"[[TABLE cols=]] 열 개수 불일치: cols={len(ratios)}개, "
                            f"표 데이터={ncols}개 (caption={b['caption']!r})")
                    table_op["col_ratios"] = ratios
                if b.get("font_pt"):
                    table_op["font_pt"] = b["font_pt"]
                ops.append(table_op)
                if b["caption"]:  # P3: 빈 캡션 생략
                    ops.append({"op": "insert_text", "text": b["caption"],
                                "pt": caption_pt, "break_after": True})
                    ops.append({"op": "insert_text", "text": "", "pt": base_pt,
                                "break_after": True})
    # BUG4: insert_blank_before가 멱등(앞에 빈 문단 있으면 건너뜀)이라 연속 빈 문단을
    # 만들지 않는다. collapse_empty_paragraphs는 제목 글자크기를 오염시키므로 자동
    # 추가하지 않는다(필요 시 수동 QA op로만 사용).
    # 줄간격: 삽입 본문이 양식 안내문 문단(180%)을 상속하므로 마지막에 문서 전체를
    # 기본세팅 줄간격(기본 160%)으로 못박는다. meta line_spacing 없으면 생략.
    ls = meta.get("line_spacing")
    if ls:
        ops.append({"op": "set_line_spacing", "percent": int(str(ls).rstrip("%"))})
    # tidy_blank_before/after (build.yaml): T7(COM 기반 blank-paragraph 정리가
    # 제목 charPr 오염·문단 병합을 일으킴) 이후 COM-op emission은 폐기.
    # 키 자체는 여기서 계속 파싱 가능하게 남겨두되(meta에 이미 병합됨), 실제
    # 정리는 fill_report.py가 tidy_hwpx.py(오프라인 XML 편집)로 hwpx 저장 뒤에
    # 수행한다 — COM edit → save-as hwpx → tidy_hwpx → COM export-pdf 순서.
    # collapse_blank_runs: 양식 잔재 빈 문단 런(삭제된 표/안내문 자리) 압축. 과거
    # 제목 크기 오염 사례로 기본 OFF — 켜면 반드시 style_diff로 제목 pt 불변을
    # 사후 검증할 것(FILL 루프가 자동 수행). 멀티페이지 커버 양식에서 페이지 구조
    # (표지 여백 등)를 깨뜨리는 사례가 run-4에서 확인됨 — 구조화 양식은 위
    # tidy_blank_* 앵커 지정 정리로 대체할 것. 맨 끝(tidy_blank_* 뒤)에 1회.
    if str(meta.get("collapse_blank_runs", "")).strip().lower() in ("true", "1", "yes"):
        ops.append({"op": "collapse_empty_paragraphs"})
    return ops


def check_form_anchors(form, sections):
    """양식 inspect 텍스트에 SECTION 앵커가 모두 있는지 대조. 불일치면 중단."""
    import os
    import subprocess
    cmd = [sys.executable, str(HERE / "com_backend.py"), "inspect",
           "--file", str(form), "--preview-chars", "4000"]
    # Windows 기본 콘솔 인코딩(cp949) 대신 자식 프로세스가 UTF-8로 출력하게 강제.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    out = subprocess.run(cmd, capture_output=True, env=env)
    raw_bytes = out.stdout
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw_bytes.decode("cp949", "replace")
    try:
        info = json.loads(raw)
    except Exception:
        die(f"inspect 출력 파싱 실패: {raw[:200]}")
    preview = info.get("text_preview", "")
    missing = [s["anchor"] for s in sections if s["anchor"] not in preview]
    if missing:
        die(f"양식에서 SECTION 앵커를 찾지 못함(우회 금지): {missing}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--content", required=True, help="bundle/content.md 경로")
    ap.add_argument("--form", help="양식 .hwp/.hwpx (inspect 앵커 대조용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="한글 미실행, ops만 출력(양식 대조 생략)")
    ap.add_argument("--build-yaml",
                    help="build.yaml 경로(생략 시 bundle/리포트 루트 자동 탐색)")
    ap.add_argument("--print-meta", action="store_true",
                    help="병합된 meta를 JSON으로 덤프하고 종료(디버그)")
    ap.add_argument("--form-profile",
                    help="form_inspect.py profile JSON 경로(T12: 표 라벨 셀 "
                         "앵커 감지용, 생략 시 cell_below 가드 비활성)")
    args = ap.parse_args()

    content_path = Path(args.content)
    if not content_path.exists():
        die(f"content.md 없음: {content_path}")
    text = content_path.read_text(encoding="utf-8")
    meta, sections = parse_content(text)

    # build.yaml 병합(가산·후방호환): 없으면 기존 동작 그대로.
    by_path = Path(args.build_yaml) if args.build_yaml else find_build_yaml(content_path)
    if by_path and Path(by_path).exists():
        meta = merge_meta(meta, parse_build_yaml(by_path))

    if args.print_meta:
        sys.stdout.buffer.write(json.dumps(
            {"ok": True, "build_yaml": str(by_path) if by_path else None,
             "meta": meta}, ensure_ascii=False, indent=2).encode("utf-8"))
        return

    if not sections:
        die("SECTION이 하나도 없음")

    if args.form and not args.dry_run:
        check_form_anchors(args.form, sections)

    label_cell_anchors = find_label_cell_anchors(load_form_profile(args.form_profile))
    warnings = []
    ops = build_ops(meta, sections, content_path.parent, warnings=warnings,
                     label_cell_anchors=label_cell_anchors)
    counts = {
        "sections": len(sections),
        "eq": sum(1 for o in ops if o["op"] == "insert_equation"),
        "fig": sum(1 for o in ops if o["op"] == "insert_picture"),
        "table": sum(1 for o in ops if o["op"] == "insert_table"),
    }
    result = {"ok": True, "counts": counts,
              "anchors": [s["anchor"] for s in sections], "ops": ops,
              "warnings": warnings}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))


if __name__ == "__main__":
    main()
