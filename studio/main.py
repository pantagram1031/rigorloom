from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pathlib import Path
import html as _html
import json
import os
import re

app = FastAPI(title="Rigorloom Studio", version="0.7")

_env_root = os.environ.get("STUDIO_WORKSPACE_ROOT")
if _env_root:
    WORKSPACE_ROOT = Path(_env_root)
else:
    _base = Path(__file__).parent.parent / "workspaces"
    WORKSPACE_ROOT = _base if _base.exists() else Path.home() / "rigorloom-workspaces"

_SLUG_RE = re.compile(r"report-[A-Za-z0-9_-]+")


def safe_workspace(slug: str) -> Path:
    """Resolve slug to a workspace dir, refusing traversal (contract §8)."""
    if not _SLUG_RE.fullmatch(slug):
        raise HTTPException(status_code=400, detail="bad slug")
    root = WORKSPACE_ROOT.resolve()
    p = (WORKSPACE_ROOT / slug).resolve()
    if not (p == root or root in p.parents):
        raise HTTPException(status_code=400, detail="out of root")
    return p


def _slugs():
    root = WORKSPACE_ROOT
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and _SLUG_RE.fullmatch(p.name)
    )


# ── PIPELINE.md v0.4 YAML-header parser (contract §2, stdlib only) ────

_STAGE_LABELS = {
    "0": "양식 분석", "1": "근거 조사", "2": "탐구 설계",
    "2.5": "레이아웃 계획", "3": "데이터·검증", "4": "집필",
    "5": "조립·검수", "5.5": "이해 확인",
    "5.7": "평가 패널", "6": "반환·축적",
}
_STATUS_ENUM = {"pending", "in_progress", "awaiting_gate", "done", "blocked"}
_GATE_ENUM = {"pending", "approved", "auto_approved", "rejected"}


def _strip_q(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        if s[0] == '"':
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
        return s[1:-1]
    return s


def _strip_inline_comment(s: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(s):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in "\"'":
            quote = None if quote == char else char if quote is None else quote
            continue
        if char == "#" and quote is None and index > 0 and s[index - 1].isspace():
            return s[:index].rstrip()
    return s.strip()


def _parse_inline_map(s: str) -> dict:
    """Parse a flat inline YAML map like {name: draft, state: pending}."""
    s = s.strip()
    if s in ("", "null", "~", "{}"):
        return {}
    if s.startswith("{"):
        s = s[1:]
    if s.endswith("}"):
        s = s[:-1]
    out = {}
    for part in s.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip()] = _strip_q(v)
    return out


def _extract_yaml_block(text: str):
    """Return the body of the first ```yaml fenced block whose first
    non-empty line declares `# pipeline-state: v0.4`, else None."""
    m = re.search(r"```ya?ml\s*\n(.*?)\n```", text, re.S)
    if not m:
        return None
    body = m.group(1)
    for line in body.splitlines():
        if line.strip():
            if re.match(r"#\s*pipeline-state:\s*v0\.4", line.strip()):
                return body
            return None
    return None


def _parse_yaml_header(body: str) -> dict:
    """Hand-rolled parser for the known-flat v0.4 checkpoint structure."""
    top = {}
    stages = {}
    in_stages = False
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^stages:\s*$", line):
            in_stages = True
            continue
        if in_stages and re.match(r"^\s+", line):
            m = re.match(r'^\s+"?([\d.]+)"?\s*:\s*(.*)$', line)
            if m:
                num = m.group(1)
                inner = _parse_inline_map(m.group(2))
                status = inner.get("status", "pending")
                if status not in _STATUS_ENUM:
                    status = "pending"
                gate_raw = m.group(2)
                gm = re.search(r"gate\s*:\s*(\{[^}]*\}|null|~)", gate_raw)
                gate = None
                if gm and gm.group(1) not in ("null", "~"):
                    gm2 = _parse_inline_map(gm.group(1))
                    gstate = gm2.get("state", "pending")
                    if gstate not in _GATE_ENUM:
                        gstate = "pending"
                    gate = {"name": gm2.get("name", ""), "state": gstate,
                            "by": gm2.get("by") or None, "at": gm2.get("at") or None}
                stages[num] = {"status": status, "gate": gate}
            continue
        in_stages = False
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            top[m.group(1)] = _strip_q(_strip_inline_comment(m.group(2)))
    top["stages"] = stages
    return top


def _load_stage_order() -> list[str]:
    """Read stage ids from the kernel config, with a safe embedded fallback."""
    fallback = ["0", "1", "2", "2.5", "3", "4", "5", "5.5", "5.7", "6"]
    config = Path(__file__).parent.parent / "pipeline" / "references" / "stages.yaml"
    try:
        ids = []
        for line in config.read_text(encoding="utf-8").splitlines():
            match = re.match(r'^\s*-\s*\{id:\s*"([\d.]+)"', line)
            if match:
                ids.append(match.group(1))
        return ids or fallback
    except Exception:
        return fallback


_STAGE_ORDER = _load_stage_order()


def _pipeline_from_yaml(hdr: dict) -> dict:
    mode = hdr.get("mode", "autonomous")
    stages_map = hdr.get("stages", {})
    order = [n for n in _STAGE_ORDER if n in stages_map]
    for n in stages_map:
        if n not in order:
            order.append(n)

    stages, gate_waiting, resume = [], False, None
    done_count = 0
    for num in order:
        st = stages_map[num]
        status = st["status"]
        gate = st.get("gate")
        if status == "done":
            done_count += 1
        if resume is None and status in ("pending", "in_progress", "awaiting_gate", "blocked"):
            resume = num
        is_gate = gate is not None
        gate_state = gate["state"] if gate else None
        if status == "awaiting_gate":
            gate_waiting = True
        if mode == "supervised" and gate and gate_state == "pending":
            gate_waiting = True
        # UI status: map to viewer vocabulary + warn on auto_approved
        if status == "done":
            ui = "done"
        elif status in ("awaiting_gate", "in_progress"):
            ui = "active"
        elif status == "blocked":
            ui = "blocked"
        else:
            ui = "pending"
        warn_auto = gate_state == "auto_approved"
        stages.append({
            "num": num, "label": _STAGE_LABELS.get(num, num),
            "status": ui, "done": status == "done", "gate": is_gate,
            "gate_name": gate["name"] if gate else "",
            "gate_state": gate_state, "auto_approved": warn_auto,
            "raw_status": status, "artifacts": "",
        })

    return {
        "format": "v0.4", "mode": mode,
        "subject": hdr.get("subject", ""), "topic": hdr.get("topic", ""),
        "canonical_output": "" if hdr.get("canonical_output") in (None, "null", "~") else hdr.get("canonical_output"),
        "stage": done_count, "total": len(stages), "stages": stages,
        "gate_waiting": gate_waiting, "resume": resume,
    }


# ── legacy fallback parser (prose table / checkboxes) ────────────────

def _status_from(raw: str) -> str:
    if "✅" in raw:
        return "done"
    if "🔄" in raw or "진행" in raw or "대기" in raw:
        return "active"
    return "pending"


def _pipeline_legacy(text: str) -> dict:
    stages = []
    for m in re.finditer(r"^- \[([ xX])\] (.+)", text, re.M):
        done = m.group(1).strip().lower() == "x"
        label = m.group(2).strip()
        is_gate = "[GATE]" in label
        label = label.replace("[GATE]", "").strip()
        stages.append({"num": str(len(stages)), "label": label,
                       "status": "done" if done else "pending",
                       "done": done, "gate": is_gate, "gate_name": "",
                       "gate_state": None, "auto_approved": False,
                       "raw_status": "done" if done else "pending",
                       "artifacts": ""})

    if not stages:
        row = re.compile(
            r"^\|\s*([\d.]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$",
            re.M)
        for m in row.finditer(text):
            num, label, raw, arts = (g.strip() for g in m.groups())
            status = _status_from(raw)
            gate = "게이트" in label or "gate" in label.lower()
            stages.append({"num": num, "label": label, "status": status,
                           "done": status == "done", "gate": gate,
                           "gate_name": "", "gate_state": None,
                           "auto_approved": False, "raw_status": status,
                           "artifacts": arts})

    gate_waiting = any(s["status"] == "active" and s["gate"] for s in stages)
    done = sum(1 for s in stages if s["done"])
    return {"format": "legacy", "mode": "", "subject": "", "topic": "",
            "canonical_output": "", "stage": done, "total": len(stages),
            "stages": stages, "gate_waiting": gate_waiting, "resume": None}


def _parse_pipeline(base: Path) -> dict:
    f = base / "PIPELINE.md"
    if not f.exists():
        return {"format": "none", "mode": "", "subject": "", "topic": "",
                "canonical_output": "", "stage": 0, "total": 0, "stages": [],
                "gate_waiting": False, "resume": None}
    text = f.read_text(encoding="utf-8")
    body = _extract_yaml_block(text)
    if body is not None:
        return _pipeline_from_yaml(_parse_yaml_header(body))
    return _pipeline_legacy(text)


# ── markdown → html (stdlib only, offline) ───────────────────────────

def _inline(s: str) -> str:
    s = _html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def _render_table(rows) -> str:
    parsed = []
    for r in rows:
        s = r.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        parsed.append([c.strip() for c in s.split("|")])
    sep_idx = None
    for idx, cols in enumerate(parsed):
        if cols and all(re.match(r"^:?-+:?$", c) for c in cols if c.strip()):
            sep_idx = idx
            break
    out = ["<table>"]
    for idx, cols in enumerate(parsed):
        if idx == sep_idx:
            continue
        is_head = sep_idx is not None and idx < sep_idx
        tag = "th" if is_head else "td"
        out.append("<tr>" + "".join(
            "<%s>%s</%s>" % (tag, _inline(c), tag) for c in cols) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _md_to_html(text: str) -> str:
    lines = text.split("\n")
    out, para, list_stack = [], [], []
    in_code, code_buf = False, []
    i, n = 0, len(lines)

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def close_lists():
        while list_stack:
            out.append("</%s>" % list_stack.pop())

    while i < n:
        line = lines[i]
        if re.match(r"^```", line):
            flush_para(); close_lists()
            if not in_code:
                in_code, code_buf = True, []
            else:
                out.append("<pre><code>" +
                           _html.escape("\n".join(code_buf)) + "</code></pre>")
                in_code = False
            i += 1; continue
        if in_code:
            code_buf.append(line); i += 1; continue

        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            flush_para(); close_lists()
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i]); i += 1
            out.append(_render_table(tbl)); continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush_para(); close_lists()
            lv = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lv, _inline(m.group(2).strip()), lv))
            i += 1; continue

        if re.match(r"^---+\s*$", line):
            flush_para(); close_lists()
            out.append("<hr>"); i += 1; continue

        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            flush_para()
            if not list_stack or list_stack[-1] != "ul":
                close_lists(); out.append("<ul>"); list_stack.append("ul")
            out.append("<li>" + _inline(m.group(1)) + "</li>")
            i += 1; continue

        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            flush_para()
            if not list_stack or list_stack[-1] != "ol":
                close_lists(); out.append("<ol>"); list_stack.append("ol")
            out.append("<li>" + _inline(m.group(1)) + "</li>")
            i += 1; continue

        if stripped == "":
            flush_para(); close_lists(); i += 1; continue

        close_lists()
        para.append(stripped)
        i += 1

    if in_code:
        out.append("<pre><code>" + _html.escape("\n".join(code_buf)) +
                   "</code></pre>")
    flush_para(); close_lists()
    return "\n".join(out)


# ── per-panel readers ────────────────────────────────────────────────

def _figure_names(base: Path):
    names = []
    for sub in ("figures", "bundle/figures"):
        d = base / sub
        if d.exists():
            for p in sorted(d.glob("*.png")):
                if p.name not in names:
                    names.append(p.name)
    return names


def _output_listing(base: Path):
    d = base / "output"
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".pdf", ".hwpx"))


_KNOWN_TAGS = {"EQ", "FIG", "TABLE", "URL"}


def _render_content(base: Path) -> dict:
    f = base / "bundle" / "content.md"
    text = f.read_text(encoding="utf-8")
    text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)

    fig_files = set(_figure_names(base))
    warnings, open_tables = [], 0
    for m in re.finditer(r"\[\[\s*(/?[A-Za-z]+)([^\]]*)\]\]", text):
        name = m.group(1)
        bare = name.lstrip("/").upper()
        if bare not in _KNOWN_TAGS:
            warnings.append("미지 태그: [[%s…]]" % name)
        if bare == "FIG":
            fm = re.search(r'file\s*=\s*"([^"]+)"', m.group(2))
            if fm and fm.group(1) not in fig_files:
                warnings.append("그림 파일 없음: %s" % fm.group(1))
        if name.upper() == "TABLE":
            open_tables += 1
        elif name == "/TABLE":
            open_tables -= 1
    if open_tables != 0:
        warnings.append("TABLE 여닫음 불일치 (%+d)" % open_tables)

    body = re.sub(r"^##\s*SECTION:\s*", "## ", text, flags=re.M)
    h = _md_to_html(body)

    toc, counter = [], [0]

    def _id(m):
        i = counter[0]; counter[0] += 1
        title = re.sub("<[^>]+>", "", m.group(1))
        toc.append({"id": "sec-%d" % i, "title": title})
        return '<h2 id="sec-%d">%s</h2>' % (i, m.group(1))

    h = re.sub(r"<h2>(.*?)</h2>", _id, h)

    def _hl(m):
        inner = m.group(1)
        first = re.match(r"\s*/?[A-Za-z]+", inner)
        bare = first.group(0).strip().lstrip("/").upper() if first else ""
        cls = "ctag" if bare in _KNOWN_TAGS else "ctag ctag-warn"
        return '<span class="%s">[[%s]]</span>' % (cls, inner)

    h = re.sub(r"\[\[(.+?)\]\]", _hl, h)
    return {"html": h, "toc": toc, "warnings": warnings}


def _parse_questions(text: str):
    qs = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*]|Q\d*[.):]?)\s*(.+)$", line)
        if m:
            qs.append(m.group(1).strip())
    if not qs:
        qs = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return qs


def _parse_structure(base: Path) -> dict:
    f = base / "bundle" / "content.md"
    if not f.exists():
        return {"sections": [], "eq_count": 0, "fig_count": 0,
                "table_count": 0, "available": False}
    text = f.read_text(encoding="utf-8")
    sections = re.findall(r"^(#{1,3} .+)", text, re.M)
    sections = [re.sub(r"SECTION:\s*", "", s) for s in sections]
    eq_count = len(re.findall(r"\[\[\s*EQ", text))
    fig_count = len(re.findall(r"\[\[\s*FIG", text))
    table_count = len(re.findall(r"\[\[\s*TABLE", text))
    return {"sections": sections, "eq_count": eq_count, "fig_count": fig_count,
            "table_count": table_count, "available": True}


# ── build.yaml (contract §4) — flat + nested `fill:` block ────────────

def _parse_build_yaml(base: Path) -> dict:
    f = base / "build.yaml"
    if not f.exists():
        return {"available": False, "config": {}, "fill": {}}
    cfg, fill = {}, {}
    in_fill = False
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^fill:\s*$", line):
            in_fill = True
            continue
        m = re.match(r"^(\s*)([A-Za-z_]+):\s*(.*)$", line)
        if not m:
            in_fill = False
            continue
        indent, key, val = m.group(1), m.group(2), m.group(3).split(" #")[0].strip()
        if in_fill and indent:
            fill[key] = val
        else:
            in_fill = False
            if val != "":
                cfg[key] = val
    return {"available": True, "config": cfg, "fill": fill}


# ── research pack (contract §6) ──────────────────────────────────────

def _research(base: Path) -> dict:
    rdir = base / "research"
    ev = rdir / "evidence.md"
    src = rdir / "sources.json"
    ev_parts = [ev] if ev.exists() else sorted(rdir.glob("evidence_R*.md"))
    src_parts = [src] if src.exists() else sorted(rdir.glob("sources_R*.json"))
    if not ev_parts and not src_parts:
        return {"available": False, "evidence_html": "", "sources": []}
    evidence_html = ""
    if ev_parts:
        try:
            chunks = []
            for part in ev_parts:
                if len(ev_parts) > 1:
                    chunks.append(f"## {part.stem}")
                chunks.append(part.read_text(encoding="utf-8"))
            evidence_html = _md_to_html("\n\n".join(chunks))
        except Exception as e:
            evidence_html = "<p class='ph'>evidence 렌더 실패: " + _html.escape(str(e)) + "</p>"
    sources = []
    for part in src_parts:
        try:
            data = json.loads(part.read_text(encoding="utf-8"))
            if isinstance(data, list):
                sources.extend(data)
        except Exception:
            continue
    return {"available": True, "evidence_html": evidence_html, "sources": sources}


def _pdf_stems(base: Path):
    out = base / "output"
    if not out.exists():
        return []
    return sorted(p.stem for p in out.glob("*.pdf"))


def _verify_pdf_stem(base: Path, canonical: str):
    """Prefer canonical_output's matching verify PDF, else latest verify_*."""
    stems = _pdf_stems(base)
    if not stems:
        return None
    verifies = [s for s in stems if s.lower().startswith("verify")]
    if canonical:
        cstem = Path(canonical).stem
        m = re.search(r"(v\d+)$", cstem)
        if m:
            for s in verifies:
                if s.endswith(m.group(1)):
                    return s
    if verifies:
        return sorted(verifies)[-1]
    return stems[-1]


# ── stage → artifact map for the ledger ──────────────────────────────

_STAGE_FILES = {
    "1": ("research/evidence.md", "research"),
    "2": ("01_design.md", "md"),
    "2.5": ("bundle/layout_plan.json", "json"),
    "3": ("sim/VERIFY.md", "verify"),
    "4": ("bundle/content.md", "content"),
    "5": (None, "link"),
    "5.5": ("output/QUESTIONS.md", "questions"),
    "5.7": ("output/scorecard.json", "json"),
}


@app.get("/workspaces")
def list_workspaces():
    return {"slugs": _slugs()}


@app.get("/workspace/{slug}/state")
def workspace_state(slug: str):
    base = safe_workspace(slug)
    pipeline = _parse_pipeline(base)
    structure = _parse_structure(base)
    build = _parse_build_yaml(base)

    stem = _verify_pdf_stem(base, pipeline.get("canonical_output", ""))
    pdf_pages, page_count = [], 0
    if stem:
        try:
            import fitz
            pdf_path = base / "output" / f"{stem}.pdf"
            doc = fitz.open(str(pdf_path))
            page_count = len(doc)
            for i in range(page_count):
                pdf_pages.append(f"/workspace/{slug}/pdf/{stem}/{i}")
            doc.close()
        except Exception:
            pdf_pages, page_count = [], 0

    fill_status = _fill_status(build, page_count, structure)
    return {**pipeline, "structure": structure, "pdf_pages": pdf_pages,
            "pdf_stem": stem, "page_count": page_count,
            "fill": fill_status}


def _fill_status(build: dict, page_count: int, structure: dict):
    """Fill-loop status line: only when build.yaml fill targets exist AND a PDF rendered."""
    fill = build.get("fill", {})
    if not build.get("available") or not fill or page_count == 0:
        return {"available": False}
    tp = fill.get("target_pages", "")
    lo = hi = None
    m = re.findall(r"\d+", tp)
    if len(m) >= 2:
        lo, hi = int(m[0]), int(m[1])
    min_figs = int(re.sub(r"\D", "", fill.get("min_figures", "0")) or 0)
    fig_count = structure.get("fig_count", 0)
    pages_ok = (lo is None) or (lo <= page_count <= hi)
    figs_ok = fig_count >= min_figs
    return {"available": True, "page_count": page_count,
            "target_lo": lo, "target_hi": hi, "pages_ok": pages_ok,
            "fig_count": fig_count, "min_figures": min_figs, "figs_ok": figs_ok,
            "converged": pages_ok and figs_ok}


@app.get("/workspace/{slug}/ledger")
def ledger(slug: str):
    base = safe_workspace(slug)
    pipe = _parse_pipeline(base)
    items, sig = [], []
    for st in pipe["stages"]:
        num = st["num"]
        entry = {"num": num, "label": st["label"], "status": st["status"],
                 "gate": st.get("gate", False), "gate_name": st.get("gate_name", ""),
                 "gate_state": st.get("gate_state"),
                 "auto_approved": st.get("auto_approved", False),
                 "artifacts": st.get("artifacts", ""), "available": False,
                 "kind": "info", "html": "", "mtime": None,
                 "toc": [], "warnings": [], "figures": [],
                 "questions": [], "outputs": [], "sources": []}
        sig.append("%s:%s" % (num, st["status"]))
        spec = _STAGE_FILES.get(num)
        if spec:
            relfile, kind = spec
            entry["kind"] = kind
            if kind == "link":
                entry["outputs"] = _output_listing(base)
                entry["available"] = bool(entry["outputs"])
            elif kind == "research":
                r = _research(base)
                entry["available"] = r["available"]
                entry["html"] = r["evidence_html"]
                entry["sources"] = r["sources"]
                ev = base / relfile
                evidence_files = [ev] if ev.exists() else sorted((base / "research").glob("evidence_R*.md"))
                if evidence_files:
                    entry["mtime"] = max(path.stat().st_mtime for path in evidence_files)
                    sig.append("%s:%.0f" % (num, entry["mtime"]))
            elif relfile:
                f = base / relfile
                if f.exists():
                    entry["available"] = True
                    mt = f.stat().st_mtime
                    entry["mtime"] = mt
                    sig.append("%s:%.0f" % (num, mt))
                    try:
                        if kind == "content":
                            c = _render_content(base)
                            entry.update(html=c["html"], toc=c["toc"],
                                         warnings=c["warnings"])
                        elif kind == "questions":
                            entry["questions"] = _parse_questions(
                                f.read_text(encoding="utf-8"))
                        elif kind == "json":
                            parsed = json.loads(f.read_text(encoding="utf-8"))
                            entry["html"] = "<pre><code>" + _html.escape(
                                json.dumps(parsed, ensure_ascii=False, indent=2)
                            ) + "</code></pre>"
                        else:
                            entry["html"] = _md_to_html(
                                f.read_text(encoding="utf-8"))
                            if kind == "verify":
                                entry["figures"] = _figure_names(base)
                    except Exception as e:
                        entry["html"] = ("<p class='ph'>렌더 실패: " +
                                         _html.escape(str(e)) + "</p>")
        items.append(entry)
    return {"stages": items, "sig": "|".join(sig)}


@app.get("/workspace/{slug}/buildconfig")
def buildconfig(slug: str):
    base = safe_workspace(slug)
    return _parse_build_yaml(base)


@app.get("/workspace/{slug}/research")
def research(slug: str):
    base = safe_workspace(slug)
    return _research(base)


@app.get("/workspace/{slug}/figure/{name}")
def figure(slug: str, name: str):
    base = safe_workspace(slug)
    if any(c in name for c in ("/", "\\", "..")):
        return Response(status_code=400)
    for sub in ("figures", "bundle/figures"):
        p = base / sub / name
        if p.exists():
            return FileResponse(str(p), headers={"Cache-Control": "no-cache"})
    return Response(status_code=404)


@app.get("/workspace/{slug}/pdf/{stem}/{page}")
def pdf_page_render(slug: str, stem: str, page: int):
    base = safe_workspace(slug)
    if any(c in stem for c in ("/", "\\", "..")):
        return Response(status_code=400)
    pdf_file = base / "output" / f"{stem}.pdf"
    if not pdf_file.exists():
        return Response(status_code=404)
    doc = None
    try:
        import fitz
        doc = fitz.open(str(pdf_file))
        if not (0 <= page < len(doc)):
            return Response(status_code=404)
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        return Response(content=pix.tobytes("png"), media_type="image/png",
                        headers={"Cache-Control": "no-cache"})
    except Exception:
        return Response(status_code=404)
    finally:
        if doc is not None:
            doc.close()


def _read_jsonl_tail(f: Path, after: int):
    """Parse JSON lines from `f` starting at offset `after` (0-based line
    index). Returns (events, next_offset). Missing file -> ([], after)."""
    if not f.exists():
        return [], after
    lines = f.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[after:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events, len(lines)


def _read_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _normalize_fill_anomalies(events: list[dict]) -> list[dict]:
    """Expose actionable fill/proof state without copying document content."""
    items = []
    for event in events:
        iteration = event.get("iter") or event.get("proof_iter")
        verdict = event.get("verdict")
        if isinstance(verdict, dict):
            state = str(verdict.get("state") or "unknown")
            converged = bool(verdict.get("converged")) or state == "converged"
            needs = verdict.get("needs") if isinstance(verdict.get("needs"), list) else []
            reason = verdict.get("reason") or state
            items.append({
                "kind": "fill", "status": "fixed" if converged else "open",
                "iteration": iteration,
                "symptom": "FILL 검증 수렴" if converged else f"FILL 검증: {state}",
                "detail": str(reason), "count": len(needs),
            })
            style = verdict.get("style_anomalies")
            if isinstance(style, list) and style:
                items.append({
                    "kind": "style", "status": "open", "iteration": iteration,
                    "symptom": f"스타일 이상 {len(style)}건", "detail": "스타일 검토 필요",
                    "count": len(style),
                })
            tidy = verdict.get("tidy_warnings")
            if isinstance(tidy, list) and tidy:
                items.append({
                    "kind": "tidy", "status": "open", "iteration": iteration,
                    "symptom": f"자동 정리 경고 {len(tidy)}건",
                    "detail": "일부 정리 앵커를 안전하게 건너뜀", "count": len(tidy),
                })

        result = event.get("result")
        if isinstance(result, dict) and event.get("phase") == "proof":
            status = str(result.get("status") or "unknown")
            resolved = status in {"pass", "passed", "approved", "converged"}
            items.append({
                "kind": "proof", "status": "fixed" if resolved else "open",
                "iteration": iteration,
                "symptom": "시각 검수 통과" if resolved else "시각 검수 확인 필요",
                "detail": status, "count": 0,
            })

        symptom = event.get("symptom") or event.get("anomaly")
        if symptom:
            items.append({
                "kind": "legacy", "status": "fixed" if event.get("fixed") else "open",
                "iteration": iteration, "symptom": str(symptom),
                "detail": "legacy fill event", "count": 1,
            })
    latest = {}
    for item in items:
        kind = item["kind"]
        latest.pop(kind, None)
        latest[kind] = item
    return list(latest.values())[-6:]


@app.get("/workspace/{slug}/events")
def workspace_events(slug: str, after: int = 0):
    base = safe_workspace(slug)
    events, nxt = _read_jsonl_tail(base / "events.jsonl", after)
    return {"events": events, "next": nxt}


def _find_heartbeat_file(base: Path):
    for name in ("heartbeat", "heartbeat.txt", "HEARTBEAT"):
        p = base / name
        if p.exists():
            return p
    return None


@app.get("/workspace/{slug}/heartbeat")
def workspace_heartbeat(slug: str):
    base = safe_workspace(slug)
    f = _find_heartbeat_file(base)
    if f is None:
        return {"ts": None, "stale_seconds": None}
    ts_text = f.read_text(encoding="utf-8").strip()
    stale = None
    try:
        import datetime
        ts_parsed = datetime.datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
        now = datetime.datetime.now(ts_parsed.tzinfo) if ts_parsed.tzinfo else datetime.datetime.now()
        stale = (now - ts_parsed).total_seconds()
    except Exception:
        try:
            stale = __import__("time").time() - f.stat().st_mtime
        except Exception:
            stale = None
    return {"ts": ts_text, "stale_seconds": stale}


@app.get("/workspace/{slug}/fill")
def workspace_fill(slug: str):
    base = safe_workspace(slug)
    events, nxt = _read_jsonl_tail(base / "output" / "fill_events.jsonl", 0)
    preview_dir = base / "output" / "preview"
    iters = []
    if preview_dir.exists():
        for p in sorted(preview_dir.glob("iter_*.pdf")):
            match = re.fullmatch(r"iter_(\d+)\.pdf", p.name)
            if not match:
                continue
            page_count = 0
            try:
                import fitz
                with fitz.open(str(p)) as doc:
                    page_count = len(doc)
            except Exception:
                page_count = 0
            iters.append({
                "name": p.name,
                "iteration": int(match.group(1)),
                "page_count": page_count,
                "mtime": p.stat().st_mtime,
            })
    return {"events": events, "next": nxt, "iterations": iters,
            "anomalies": _normalize_fill_anomalies(events)}


@app.get("/workspace/{slug}/personalization")
def workspace_personalization(slug: str):
    """Return the redacted per-run personalization lock, never identity data."""
    base = safe_workspace(slug)
    path = base / ".pipeline" / "personalization.lock.json"
    if not path.exists():
        return {"available": False}
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "invalid": True}
    effective = lock.get("effective") or {}
    writing = effective.get("writing") or {}
    academic = effective.get("academic") or {}
    form = effective.get("form_conditions") or {}
    return {
        "available": True,
        "lock_hash": lock.get("lock_hash"),
        "subject": lock.get("subject"),
        "form_sha256": lock.get("form_sha256"),
        "identity_enabled": bool(lock.get("identity_enabled")),
        "writing": {
            "language": writing.get("language"),
            "academic_level": writing.get("academic_level"),
            "register": writing.get("register"),
            "advanced_terms": writing.get("advanced_terms"),
            "avoid_count": len(writing.get("avoid_patterns") or []),
        },
        "academic_profile": bool(academic),
        "form_conditions": bool(form),
        "precedence": effective.get("precedence") or [],
    }


@app.get("/workspace/{slug}/preview-pdf/{iter}/{page}")
def preview_pdf_page(slug: str, iter: str, page: int):
    base = safe_workspace(slug)
    if not re.fullmatch(r"\d+", iter):
        return Response(status_code=400)
    pdf_file = base / "output" / "preview" / f"iter_{int(iter)}.pdf"
    if not pdf_file.exists():
        return Response(status_code=404)
    doc = None
    try:
        import fitz
        doc = fitz.open(str(pdf_file))
        if not (0 <= page < len(doc)):
            return Response(status_code=404)
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        return Response(content=pix.tobytes("png"), media_type="image/png",
                        headers={"Cache-Control": "no-cache"})
    except Exception:
        return Response(status_code=404)
    finally:
        if doc is not None:
            doc.close()


@app.get("/workspace/{slug}/provenance")
def workspace_provenance(slug: str):
    base = safe_workspace(slug)
    f = base / "bundle" / "provenance.json"
    if not f.exists():
        return Response(status_code=404)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return Response(status_code=404)


@app.get("/workspace/{slug}/scorecard")
def workspace_scorecard(slug: str):
    base = safe_workspace(slug)
    f = base / "output" / "scorecard.json"
    if not f.exists():
        return Response(status_code=404)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return Response(status_code=404)


@app.get("/workspace/{slug}/draft")
def workspace_draft(slug: str):
    base = safe_workspace(slug)
    f = base / "bundle" / "content.md"
    content = f.read_text(encoding="utf-8") if f.exists() else None
    profile = None
    pf = base / "form_profile.json"
    if pf.exists():
        try:
            profile = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            profile = None
    return {"content": content, "profile": profile}


def _resume_command(base: Path) -> str:
    command = _read_json_dict(base / ".pipeline" / "handoff.json").get("resume_command")
    if command:
        return command
    return f'python pipeline/scripts/pipeline_ctl.py resume "{base.resolve()}"'


@app.get("/workspace/{slug}/readiness")
def workspace_readiness(slug: str):
    base = safe_workspace(slug)
    handoff = _read_json_dict(base / ".pipeline" / "handoff.json")
    if not handoff:
        pipeline = _parse_pipeline(base)
        next_stage = pipeline.get("resume")
        next_record = next(
            (item for item in pipeline.get("stages", []) if item.get("num") == next_stage),
            {},
        )
        return {
            "available": False, "readiness": "legacy", "next_stage": next_stage,
            "next_status": next_record.get("raw_status"),
            "next_gate": ({"name": next_record.get("gate_name"),
                           "state": next_record.get("gate_state")}
                          if next_record.get("gate") else None),
            "playbook": (f"pipeline/references/playbooks/stage-{next_stage}.md"
                         if next_stage else None),
            "work_dir": (f"work/stage-{next_stage}" if next_stage else None),
            "missing_inputs": [], "missing_outputs": [],
            "expected_outputs": [], "resume_command": _resume_command(base),
            "personalization_lock": None, "generated_at": None, "archived_count": 0,
        }

    missing_inputs = handoff.get("missing_inputs") or []
    next_status = handoff.get("next_status")
    next_stage = handoff.get("next_stage")
    if next_stage is None:
        readiness = "complete"
    elif missing_inputs:
        readiness = "missing_inputs"
    elif next_status == "awaiting_gate":
        readiness = "waiting_gate"
    elif next_status == "blocked":
        readiness = "blocked"
    else:
        readiness = "ready"
    return {
        "available": True,
        "readiness": readiness,
        "next_stage": next_stage,
        "next_status": next_status,
        "next_gate": handoff.get("next_gate"),
        "playbook": handoff.get("playbook"),
        "work_dir": handoff.get("work_dir"),
        "missing_inputs": missing_inputs,
        "missing_outputs": handoff.get("missing_outputs") or [],
        "expected_outputs": handoff.get("expected_outputs") or [],
        "resume_command": handoff.get("resume_command") or _resume_command(base),
        "personalization_lock": handoff.get("personalization_lock"),
        "generated_at": handoff.get("generated_at"),
        "archived_count": len(handoff.get("archived") or []),
    }


@app.get("/workspace/{slug}/yourmove")
def workspace_yourmove(slug: str):
    base = safe_workspace(slug)
    pipeline = _parse_pipeline(base)
    readiness = workspace_readiness(slug)

    if pipeline["format"] == "none":
        return {"kind": "blocked", "gate": None, "approval_line": None,
                "reason": "PIPELINE.md 없음 — 아직 시작되지 않았습니다.",
                "resume_command": _resume_command(base)}

    if pipeline["format"] == "legacy":
        return {"kind": "stale", "gate": None, "approval_line": None,
                "reason": "구형 포맷(legacy) 워크스페이스 — YAML 헤더가 없어 자동 판정할 수 없습니다.",
                "resume_command": _resume_command(base)}

    # v0.4/v0.5 YAML format
    stages = pipeline["stages"]
    blocked_stage = next((s for s in stages if s["raw_status"] == "blocked"), None)
    if blocked_stage:
        return {"kind": "blocked", "gate": None, "approval_line": None,
                "reason": f"Stage {blocked_stage['num']} ({blocked_stage['label']}) 차단됨 — "
                          f"PIPELINE.md와 TROUBLES.md를 확인하세요.",
                "resume_command": _resume_command(base)}

    gate_stage = next((s for s in stages if s["raw_status"] == "awaiting_gate"), None)
    if gate_stage and pipeline["mode"] == "supervised":
        gate_name = gate_stage.get("gate_name") or gate_stage["label"]
        approval_line = f"{gate_name}: approved by=<name> at={_now_iso()}"
        gate_command = (f'python pipeline/scripts/pipeline_ctl.py gate "{base.resolve()}" '
                        f'"{gate_name}" --mode {pipeline["mode"]}')
        return {"kind": "gate_wait", "gate": gate_name, "approval_line": approval_line,
                "reason": f"Stage {gate_stage['num']} ({gate_stage['label']}) 게이트 승인 대기 중.",
                "gate_command": gate_command,
                "resume_command": readiness["resume_command"]}

    if pipeline["resume"] is None and pipeline["stage"] == pipeline["total"] and pipeline["total"] > 0:
        return {"kind": "done", "gate": None, "approval_line": None,
                "reason": "모든 단계 완료.", "resume_command": _resume_command(base)}

    if readiness["available"] and readiness["next_stage"] is not None:
        reason = (f"Stage {readiness['next_stage']} 준비됨 — "
                  f"{readiness['playbook'] or 'playbook'} 기준으로 진행하세요.")
    else:
        reason = "자율 실행 진행 중."
    return {"kind": "running", "gate": None, "approval_line": None,
            "reason": reason, "resume_command": readiness["resume_command"]}


def _now_iso():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


@app.get("/startprompt")
def start_prompt(topic: str, subject: str = "", form: str = "", conditions: str = ""):
    parts = [f"Rigorloom 보고서 워크플로우를 시작한다. 주제: {topic}"]
    if subject:
        parts.append(f"과목: {subject}")
    if form:
        parts.append(f"양식: {form}")
    if conditions:
        parts.append(f"조건: {conditions}")
    parts.append("현재 워크스페이스의 NEXT_TASK.md와 단계 playbook을 기준으로 진행하고, 상태는 pipeline_ctl로만 변경한다")
    return {"prompt": ". ".join(parts) + "."}


@app.get("/")
def root():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    print(f"Workspace root: {WORKSPACE_ROOT}")
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
