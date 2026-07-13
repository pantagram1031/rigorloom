# -*- coding: utf-8 -*-
"""bundle_backend — the zero-dependency document backend (the any-machine floor).

The deliverable IS the frozen bundle: content.md (validated build grammar),
figures/, provenance (if present), plus a single-file HTML preview rendered with
the standard library only. No HWP, no python-docx, no network. Stage 5 with this
backend is "package + render preview"; verify_format is skipped.

Output layout (under <out_dir>, default <WS>/output/deliverable):
    content.md          copied verbatim
    figures/*           copied verbatim
    provenance.json     copied if bundle/provenance.json exists
    preview.html        stdlib-rendered honest preview (equations shown as
                        literal source, never typeset)
    manifest.json       {generated_at, files:[{path, sha256, bytes}]}

Determinism: no timestamp appears in any file's CONTENT except manifest.json's
`generated_at` field, so preview.html + copied files are byte-stable for a given
bundle.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
from datetime import datetime, timezone

from . import EQ_INLINE_RE, URL_INLINE_RE, eq_text, url_parts, parse_blocks, parse_front_matter


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_inline(text: str) -> str:
    """Escape paragraph text, then substitute inline EQ/URL tags into HTML.

    EQ → <code class="eq">literal source</code> (honest — no typesetting).
    URL → <a href> anchor. Escaping happens first; the injected markup is built
    from already-escaped pieces so tag internals can never break out.
    """
    # Protect tag spans with placeholders before escaping, so their generated
    # HTML survives html.escape.
    tokens: list[str] = []

    def _stash(markup: str) -> str:
        tokens.append(markup)
        return f"\x00{len(tokens) - 1}\x00"

    def _eq(m):
        return _stash(f'<code class="eq">{html.escape(eq_text(m.group(1)))}</code>')

    def _url(m):
        href, disp = url_parts(m.group(1))
        return _stash(f'<a href="{html.escape(href, quote=True)}">{html.escape(disp)}</a>')

    tmp = EQ_INLINE_RE.sub(_eq, text)
    tmp = URL_INLINE_RE.sub(_url, tmp)
    escaped = html.escape(tmp)
    for idx, markup in enumerate(tokens):
        escaped = escaped.replace(f"\x00{idx}\x00", markup)
    return escaped


def _render_html(meta: dict, blocks: list) -> str:
    title = meta.get("title", "Report preview")
    parts = [
        "<!doctype html>",
        '<html lang="ko"><head><meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>",
        "<style>",
        "body{font-family:system-ui,'Malgun Gothic',sans-serif;max-width:820px;"
        "margin:2rem auto;padding:0 1rem;line-height:1.6}",
        "h1{font-size:1.6rem}h2{font-size:1.25rem;margin-top:2rem;"
        "border-bottom:1px solid #ccc;padding-bottom:.2rem}",
        "figure{margin:1.2rem 0;text-align:center}img{max-width:100%}",
        "figcaption{font-size:.9rem;color:#555;margin-top:.3rem}",
        "code.eq{background:#f3f3f3;padding:0 .25rem;border-radius:3px;"
        "font-family:ui-monospace,monospace}",
        "table{border-collapse:collapse;margin:1rem 0;font-size:.92rem}",
        "th,td{border:1px solid #999;padding:.25rem .5rem;text-align:left}",
        "caption{caption-side:top;font-size:.9rem;color:#555;margin-bottom:.3rem}",
        ".preview-note{color:#888;font-size:.8rem}",
        "</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        '<p class="preview-note">Bundle preview (stdlib render). Equations are '
        "shown as literal source, not typeset.</p>",
    ]
    for b in blocks:
        t = b["type"]
        if t == "section":
            parts.append(f"<h2>{html.escape(b['title'])}</h2>")
        elif t == "para":
            if b["text"]:
                parts.append(f"<p>{_render_inline(b['text'])}</p>")
        elif t == "fig":
            rel = "figures/" + b["file"].replace("\\", "/").lstrip("/")
            cap = b["caption"]
            parts.append("<figure>")
            parts.append(f'<img src="{html.escape(rel, quote=True)}" '
                         f'alt="{html.escape(cap)}">')
            if cap:
                parts.append(f"<figcaption>{html.escape(cap)}</figcaption>")
            parts.append("</figure>")
        elif t == "table":
            parts.append("<table>")
            if b["caption"]:
                parts.append(f"<caption>{html.escape(b['caption'])}</caption>")
            for r, row in enumerate(b["rows"]):
                cell = "th" if r == 0 else "td"
                cells = "".join(f"<{cell}>{html.escape(c)}</{cell}>" for c in row)
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def build(ws: str, out_dir: str | None = None):
    """Package the bundle deliverable + render preview.html + write manifest.

    Returns (result: dict, exit_code: int). exit_code 0 on success, 2 if the
    bundle/content.md floor is missing.
    """
    bundle = os.path.join(ws, "bundle")
    content_md = os.path.join(bundle, "content.md")
    if not os.path.isfile(content_md):
        return {"ok": False, "backend": "bundle",
                "error": "bundle/content.md not found", "workspace": ws}, 2

    deliverable = out_dir or os.path.join(ws, "output", "deliverable")
    os.makedirs(deliverable, exist_ok=True)

    # (b) copy content.md, figures/, provenance.json
    shutil.copyfile(content_md, os.path.join(deliverable, "content.md"))

    src_figs = os.path.join(bundle, "figures")
    if os.path.isdir(src_figs):
        dst_figs = os.path.join(deliverable, "figures")
        if os.path.isdir(dst_figs):
            shutil.rmtree(dst_figs)
        shutil.copytree(src_figs, dst_figs)

    prov = os.path.join(bundle, "provenance.json")
    if os.path.isfile(prov):
        shutil.copyfile(prov, os.path.join(deliverable, "provenance.json"))

    # (c) render single-file HTML preview
    md = open(content_md, encoding="utf-8").read()
    meta, body = parse_front_matter(md)
    blocks = parse_blocks(body)
    preview_path = os.path.join(deliverable, "preview.html")
    with open(preview_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_render_html(meta, blocks))

    # manifest: every deliverable file except the manifest itself, sorted for
    # a stable ordering across machines/filesystems.
    entries = []
    for root, _dirs, files in os.walk(deliverable):
        for fn in files:
            if fn == "manifest.json":
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, deliverable).replace("\\", "/")
            entries.append({"path": rel, "sha256": _sha256(full),
                            "bytes": os.path.getsize(full)})
    entries.sort(key=lambda e: e["path"])
    manifest = {
        "backend": "bundle",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    with open(os.path.join(deliverable, "manifest.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    result = {
        "ok": True,
        "backend": "bundle",
        "workspace": ws,
        "out_dir": deliverable,
        "preview": preview_path,
        "figures": sum(1 for b in blocks if b["type"] == "fig"),
        "tables": sum(1 for b in blocks if b["type"] == "table"),
        "sections": sum(1 for b in blocks if b["type"] == "section"),
        "files": len(entries),
    }
    return result, 0
