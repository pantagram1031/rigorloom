# -*- coding: utf-8 -*-
"""check_style.py — deterministic prose/structure style gate for a workspace.

Recompute-based (does NOT trust any manifest): reads bundle/content.md body
text and applies a prose_rules preference pack (banned patterns + signature
phrase caps) and, optionally, a report_structure pack (title-format hint +
citation-style enforcement). Emits a JSON verdict + an exit code shaped like
verify_content.py.

Exit 0 = pass (no HARD violations). Exit 3 = HARD violation(s). Exit 2 = usage.
WARN findings never fail the gate (reported for the orchestrator to weigh).

Packs are loaded via personalization_ctl.load_pack_file (JSON, or the documented
YAML subset). With no --pack given the neutral public default prose_rules pack
is used; --structure-pack is optional and defaults to no structure checks.

HARD rules:
  banned_patterns[*] with severity "hard" that match the body   -> exit 3
  signature_phrases[*] whose match count exceeds max_count       -> exit 3
  report_structure.citation_style.in_text == "narrative" AND an
    in-text parenthetical (저자, 연도) citation is present         -> exit 3
WARN rules:
  banned_patterns[*] with severity "warn" that match the body
  report_structure.title_format mismatch vs the first heading (best-effort)
"""
import sys, os, re, json, argparse
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import personalization_ctl  # noqa: E402  (stdlib-only sibling module)

_DEFAULTS_DIR = _SCRIPTS_DIR.parent / "references" / "preference_packs" / "defaults"
DEFAULT_PROSE_PACK = _DEFAULTS_DIR / "prose_rules.json"

# in-text parenthetical citation, e.g. "(김철수, 2020)" or "(Smith, 2019)".
CITATION_PAREN_RE = re.compile(r"\([가-힣A-Za-z .]+,\s*\d{4}\)")


def read(p):
    return open(p, encoding="utf-8", errors="ignore").read() if os.path.exists(p) else None


def find_body(md):
    """content.md minus the [[...]] build tags (so tag internals don't false-positive).
    Same approach as verify_content.find_body."""
    return re.sub(r"\[\[.*?\]\]", " ", md, flags=re.S)


def first_heading(md):
    m = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", md)
    return m.group(1).strip() if m else None


def _title_format_to_regex(title_format):
    """Turn a title_format template ('An Inquiry into {topic}') into a loose
    regex by escaping literals and replacing {placeholder} runs with '.+'."""
    parts = re.split(r"\{[^}]*\}", title_format)
    return "^" + ".+".join(re.escape(p) for p in parts) + "$"


def check(ws, prose_pack=None, structure_pack=None, allow_terms=None):
    hard, warn = [], []
    md = read(os.path.join(ws, "bundle", "content.md"))
    if md is None:
        return {"ok": False, "error": "bundle/content.md not found"}, 2
    body = find_body(md)
    allow_terms = allow_terms or []

    # --- prose_rules ---------------------------------------------------------
    banned = prose_pack.get("banned_patterns", []) if isinstance(prose_pack, dict) else []
    for entry in banned:
        pid = entry.get("id", "?")
        regex = entry.get("regex", "")
        severity = entry.get("severity", "warn")
        try:
            rx = re.compile(regex, re.M)
        except re.error as exc:
            warn.append({"code": "PACK?", "msg": f"bad banned regex {pid!r}: {exc}", "at": regex[:40]})
            continue
        for m in rx.finditer(body):
            matched = m.group(0)
            # allowlisted terms (units/symbols/proper nouns) exempt a match —
            # e.g. a gloss rule hitting "거리(dB)" when dB is allowlisted
            if any(t and t in matched for t in allow_terms):
                continue
            hit = {"code": f"BAN:{pid}", "msg": entry.get("description", "banned pattern"),
                   "at": matched[:60]}
            (hard if severity == "hard" else warn).append(hit)

    for entry in (prose_pack.get("signature_phrases", []) if isinstance(prose_pack, dict) else []):
        regex = entry.get("regex", "")
        max_count = entry.get("max_count", 0)
        try:
            rx = re.compile(regex, re.M)
        except re.error as exc:
            warn.append({"code": "PACK?", "msg": f"bad signature regex: {exc}", "at": regex[:40]})
            continue
        n = len(rx.findall(body))
        if n > max_count:
            hard.append({"code": "SIG", "msg": f"signature phrase over cap ({n} > {max_count})",
                         "at": regex[:40]})

    # --- report_structure (optional) ----------------------------------------
    if isinstance(structure_pack, dict):
        cite = structure_pack.get("citation_style", {})
        if isinstance(cite, dict) and cite.get("in_text") == "narrative":
            for m in CITATION_PAREN_RE.finditer(body):
                hard.append({"code": "CITE", "msg": "in-text parenthetical citation but "
                             "citation_style.in_text is narrative", "at": m.group(0)[:40]})
        title_format = structure_pack.get("title_format")
        heading = first_heading(md)
        # In this pipeline's build grammar the document title never appears in
        # content.md — headings are '## SECTION: <anchor>' markers. Skip the
        # title check when that convention is detected (title lives in the form).
        if heading and re.match(r"^SECTION\s*:", heading):
            heading = None
        if title_format and heading:
            try:
                if not re.match(_title_format_to_regex(title_format), heading):
                    warn.append({"code": "TITLE", "msg": f"first heading does not match "
                                 f"title_format {title_format!r}", "at": heading[:50]})
            except re.error:
                pass

    verdict = {
        "ok": len(hard) == 0,
        "workspace": ws,
        "checker": "check_style",
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, (0 if not hard else 3)


def _load_pack(path, default_path):
    src = Path(path) if path else Path(default_path)
    return personalization_ctl.load_pack_file(src)


def main():
    ap = argparse.ArgumentParser(description="deterministic prose/structure style gate")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--pack", default=None, help="prose_rules pack file (JSON or YAML subset); "
                    "default = neutral public prose_rules.json")
    ap.add_argument("--structure-pack", default=None,
                    help="report_structure pack file (optional; enables citation/title checks)")
    ap.add_argument("--allowlist", default=None,
                    help="one-term-per-line file; a banned-pattern match containing "
                    "an allowlisted term is exempted (units/symbols/proper nouns)")
    ap.add_argument("--out", default=None, help="write verdict JSON here")
    a = ap.parse_args()

    prose_pack = _load_pack(a.pack, DEFAULT_PROSE_PACK)
    structure_pack = personalization_ctl.load_pack_file(Path(a.structure_pack)) if a.structure_pack else None
    allow_terms = []
    if a.allowlist:
        raw = read(a.allowlist)
        if raw is None:
            print(json.dumps({"ok": False, "error": f"allowlist not found: {a.allowlist}"}))
            sys.exit(2)
        allow_terms = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]

    v, code = check(a.workspace, prose_pack=prose_pack, structure_pack=structure_pack,
                    allow_terms=allow_terms)
    js = json.dumps(v, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(js)
    print(js)
    sys.exit(code)



def _utf8_stdio():
    """Windows consoles/CI default to a legacy codepage; JSON/finding output is
    UTF-8. Reconfigure stdio so printing Korean text never dies with a
    UnicodeEncodeError (no-op where already UTF-8 or unsupported)."""
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    main()
