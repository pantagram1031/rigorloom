#!/usr/bin/env python3
"""build_report.py — report bundle(content.md)을 hwp-master ops JSON으로 변환.

명세: report-pipeline/references/bundle_spec.md (Stage 4 출력 → Stage 5 입력).
content.md를 결정론적으로 파싱해 com_backend.py edit에 그대로 줄 수 있는 ops를
만든다. 미지 태그·SECTION 앵커 불일치·수식 sanity 실패는 우회 없이 중단한다.

    python build_report.py --content bundle/content.md [--form 양식.hwp] [--dry-run]

--dry-run: 한글(COM) 미실행, ops만 stdout. 양식 inspect 대조는 생략.
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
KNOWN_TAGS = {"EQ", "FIG", "TABLE", "/TABLE"}


def die(msg, code=2):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)


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
                cur["blocks"].append({"kind": "para", "text": text_})
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
            if base not in {"EQ", "FIG", "TABLE"}:
                die(f"미지 태그: [[{name}]] (line {i + 1})")
            if cur is None:
                die(f"SECTION 밖의 태그: [[{name}]] (line {i + 1})")
            attrs, flags = parse_attrs(tag.group(2))
            if name == "EQ":
                cur["blocks"].append({
                    "kind": "eq",
                    "display": "inline" not in flags,
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
                cur["blocks"].append({
                    "kind": "table", "caption": attrs.get("caption", ""), "data": rows,
                })
            i += 1
            continue
        if line.strip() == "":
            flush_para()
        else:
            para.append(line)
        i += 1
    flush_para()
    return meta, sections


def build_ops(meta, sections, bundle_dir):
    base_pt = int(meta.get("base_pt", 11))
    ops = []
    title, t_anchor = meta.get("title"), meta.get("title_anchor")
    if title and t_anchor:
        ops.append({"op": "replace_all", "find": t_anchor, "replace": title})
    figs_dir = Path(bundle_dir) / "figures"
    for sec in sections:
        ops.append({"op": "goto_text", "text": sec["anchor"]})
        # 제목 끝에서 새 문단을 열어 본문이 제목에 붙지 않게 한다
        # ("VI.  참고문헌David Nash..."처럼 제목+본문이 한 문단에 붙는 것을 막는다).
        ops.append({"op": "insert_text", "text": "\r\n"})
        for b in sec["blocks"]:
            if b["kind"] == "para":
                ops.append({"op": "insert_text", "text": b["text"] + "\r\n"})
            elif b["kind"] == "eq":
                op = {"op": "insert_equation", "base_pt": base_pt,
                      "display": b["display"]}
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
                if not b["file"]:
                    die("FIG 태그에 file 없음")
                ops.append({"op": "insert_text", "text": b["caption"] + "\r\n"})
                ops.append({"op": "insert_picture",
                            "path": str((figs_dir / b["file"]).resolve()),
                            "width_mm": b["width"], "own_paragraph": True})
            elif b["kind"] == "table":
                ops.append({"op": "insert_text", "text": b["caption"] + "\r\n"})
                ops.append({"op": "insert_table", "data": b["data"],
                            "treat_as_char": True})
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
    args = ap.parse_args()

    content_path = Path(args.content)
    if not content_path.exists():
        die(f"content.md 없음: {content_path}")
    text = content_path.read_text(encoding="utf-8")
    meta, sections = parse_content(text)
    if not sections:
        die("SECTION이 하나도 없음")

    if args.form and not args.dry_run:
        check_form_anchors(args.form, sections)

    ops = build_ops(meta, sections, content_path.parent)
    counts = {
        "sections": len(sections),
        "eq": sum(1 for o in ops if o["op"] == "insert_equation"),
        "fig": sum(1 for o in ops if o["op"] == "insert_picture"),
        "table": sum(1 for o in ops if o["op"] == "insert_table"),
    }
    result = {"ok": True, "counts": counts,
              "anchors": [s["anchor"] for s in sections], "ops": ops}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))


if __name__ == "__main__":
    main()
