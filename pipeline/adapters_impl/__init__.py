# -*- coding: utf-8 -*-
"""adapters_impl — in-tree document backends for the rigorloom pipeline.

These are the zero/low-dependency document backends that ship WITH the public
clone (the `bundle` floor and the optional `docx` extra). The `hwp` backend is
NOT here: it lives in the separate hwp-master repo and is dispatched to by
pipeline/scripts/doc_backend.py, which prints a pointer and exits.

This package module holds the shared content.md parser (the build grammar
defined in pipeline/references/bundle_spec.md) so both backends agree on how a
bundle is read. Parsing only — no rendering, no I/O side effects here.
"""
from __future__ import annotations

import re

# ── build grammar (bundle_spec.md v2) ───────────────────────────────────────
# SECTION anchor : "## SECTION: <title>"  (also plain "# .. #### .." headings)
# figure         : [[FIG file="x.png" width=110 caption="..."]]
# equation       : [[EQ latex="..."]] | [[EQ display latex="..."]] | [[EQ inline hwpeqn="..."]]
# table          : [[TABLE cols=10,16 pt=9 caption="..."]] \n |a|b| ... \n [[/TABLE]]
# hyperlink      : [[URL href="..." text="..."]]  (or a bare URL-only line)

_HEADING_RE = re.compile(r"^(#{1,4})\s*(?:SECTION:\s*)?(.*)$")
_FIG_RE = re.compile(r"^\s*\[\[\s*FIG\b([^\]]*)\]\]\s*$", re.I)
_TABLE_OPEN_RE = re.compile(r"^\s*\[\[\s*TABLE\b([^\]]*)\]\]\s*$", re.I)
_TABLE_CLOSE_RE = re.compile(r"^\s*\[\[\s*/\s*TABLE\s*\]\]\s*$", re.I)
_BARE_URL_RE = re.compile(r"^\s*(https?://\S+)\s*$")

# inline tags rendered by each backend (kept raw in paragraph text)
EQ_INLINE_RE = re.compile(r"\[\[\s*EQ\b([^\]]*)\]\]", re.I)
URL_INLINE_RE = re.compile(r"\[\[\s*URL\b([^\]]*)\]\]", re.I)


def _quoted_attr(body: str, key: str):
    """Return the value of key="..." from a tag body, or None."""
    m = re.search(rf'{key}\s*=\s*"([^"]*)"', body, re.I)
    return m.group(1) if m else None


def _int_attr(body: str, key: str):
    """Return int value of a bare key=NN attribute, or None."""
    m = re.search(rf'\b{key}\s*=\s*(\d+)', body, re.I)
    return int(m.group(1)) if m else None


def _cols_attr(body: str):
    """Return the cols=10,16,12 list as ints, or None."""
    m = re.search(r'\bcols\s*=\s*([\d,\s]+)', body, re.I)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


def eq_text(tag_body: str) -> str:
    """Extract the literal equation source from an EQ tag body.

    Prefers latex="..." then hwpeqn="..."; returns the raw source verbatim (no
    rendering — an honest preview shows the operator what was authored)."""
    return _quoted_attr(tag_body, "latex") or _quoted_attr(tag_body, "hwpeqn") or ""


def url_parts(tag_body: str):
    """Return (href, display_text) for a [[URL ...]] tag body."""
    href = _quoted_attr(tag_body, "href") or ""
    text = _quoted_attr(tag_body, "text") or href
    return href, text


def parse_front_matter(md: str):
    """Split a leading `---\\n...\\n---\\n` YAML block off the top of content.md.

    Returns (meta: dict[str, str], body: str). Minimal line-scan (no YAML dep):
    only flat `key: value` pairs are captured, quotes stripped. Absent block →
    ({}, md unchanged)."""
    meta: dict[str, str] = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md, re.S)
    if not m:
        return meta, md
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        meta[key.strip()] = val
    return meta, md[m.end():]


def parse_blocks(body: str):
    """Parse content.md body (front-matter already stripped) into blocks.

    Block shapes:
      {"type": "section", "level": int, "title": str}
      {"type": "para",    "text": str}          # may hold inline EQ/URL tags
      {"type": "fig",     "file": str, "width": int|None, "caption": str}
      {"type": "table",   "cols": list|None, "pt": int|None, "caption": str,
                          "rows": list[list[str]]}
    Paragraphs accumulate over consecutive non-blank lines; a blank line ends
    one. Inline EQ/URL tags stay embedded in paragraph text for the backend to
    render.
    """
    blocks = []
    para: list[str] = []
    lines = body.split("\n")
    i = 0

    def flush():
        if para:
            blocks.append({"type": "para", "text": " ".join(para).strip()})
            para.clear()

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if line == "":
            flush()
            i += 1
            continue

        # table block (multi-line, own state)
        mt = _TABLE_OPEN_RE.match(line)
        if mt:
            flush()
            tbody = mt.group(1)
            rows = []
            i += 1
            while i < len(lines) and not _TABLE_CLOSE_RE.match(lines[i].strip()):
                row = lines[i].strip()
                if row.startswith("|"):
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    # skip a markdown separator row if one slipped in
                    if not all(set(c) <= set("-: ") and c for c in cells):
                        rows.append(cells)
                i += 1
            i += 1  # consume the [[/TABLE]] line
            blocks.append({
                "type": "table",
                "cols": _cols_attr(tbody),
                "pt": _int_attr(tbody, "pt"),
                "caption": _quoted_attr(tbody, "caption") or "",
                "rows": rows,
            })
            continue

        # figure (self-contained line)
        mf = _FIG_RE.match(line)
        if mf:
            flush()
            fbody = mf.group(1)
            blocks.append({
                "type": "fig",
                "file": _quoted_attr(fbody, "file") or "",
                "width": _int_attr(fbody, "width"),
                "caption": _quoted_attr(fbody, "caption") or "",
            })
            i += 1
            continue

        # heading
        if line.startswith("#"):
            mh = _HEADING_RE.match(line)
            if mh:
                flush()
                blocks.append({
                    "type": "section",
                    "level": len(mh.group(1)),
                    "title": mh.group(2).strip(),
                })
                i += 1
                continue

        # bare URL-only line → treat as its own paragraph carrying a URL tag
        mu = _BARE_URL_RE.match(line)
        if mu:
            flush()
            blocks.append({"type": "para", "text": f'[[URL href="{mu.group(1)}"]]'})
            i += 1
            continue

        para.append(line)
        i += 1

    flush()
    return blocks


def read_build_yaml_key(path: str, key: str):
    """Minimal line-scan for a top-level `key: value` in build.yaml.

    No YAML dependency: matches an unindented `key:` line, strips quotes and a
    trailing `# comment`. Returns the string value or None. Used for the
    doc_backend selector and the document title.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                if raw.lstrip() != raw:  # indented → not a top-level key
                    continue
                line = raw.rstrip("\n")
                m = re.match(rf'^{re.escape(key)}\s*:\s*(.*)$', line)
                if not m:
                    continue
                val = m.group(1).strip()
                if val and val[0] not in "\"'":
                    val = val.split("#", 1)[0].strip()
                if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
                    val = val[1:-1]
                return val or None
    except OSError:
        return None
    return None
