# -*- coding: utf-8 -*-
"""verify_content.py — deterministic content gate for a report workspace.

Recompute-based (does NOT trust any manifest): reads bundle/content.md, the
assembled output/out.pdf (if present), bundle/figures/, and _saeteuk/, and emits
a JSON verdict + an exit code. This is the checker bound to the stage 4.5
`content_audit` script gate; `pipeline_ctl.py check <ws> content_audit` runs it
and records the verdict (never a caller-supplied exit code).

Exit 0 = pass (no HARD violations). Exit 3 = HARD violation(s). Exit 2 = usage error.
WARN findings never fail the gate (reported for the orchestrator to weigh).

HARD rules (unambiguous, fail-closed):
  H1 no web citation in body prose; recognized reference-section lines exempt
  H2 no '~습니다/~ㅂ니다' polite endings in body prose
  H3 every [[FIG file="x.png"]] resolves to bundle/figures/x.png
  H4 세특 files (if any) <= 1500 bytes each
  H5 assembled PDF (if present) leaks none of: '[[', 'latex=', 'left(', '\\frac', '\\sigma'
WARN rules (heuristic):
  W1 괄호-영어 gloss: Korean char + (Latin words) not in the allowlist
  W2 numbered [n] references in the bibliography (prefer author-year)
  W3 in-text (저자, 연도) whose surname has no matching bibliography entry

Allowlist: a small NEUTRAL builtin (units/symbols only) plus an optional
--allowlist file (one term per line, or a simple YAML list). Report-topic-
specific proper nouns are NOT builtin — pass them per report via --allowlist.
"""
import sys, os, re, json, argparse
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)
import check_sources  # noqa: E402

# Neutral builtin: units / symbols / generic method names only. NO
# report-topic-specific proper nouns (those belong in a per-report --allowlist).
BUILTIN_ALLOW_GLOSS = {"dB", "Hz", "kHz", "DOI", "RK4"}


def load_allowlist(path):
    """Read extra allowed gloss terms from a file: one term per line, or a
    simple YAML list (`- term`). Blank lines and '#' comments ignored. Returns
    a set (empty if path is None/unreadable)."""
    terms = set()
    if not path:
        return terms
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("- "):
                    line = line[2:].strip()
                if len(line) >= 2 and line[0] in "\"'" and line[-1] == line[0]:
                    line = line[1:-1]
                if line:
                    terms.add(line)
    except OSError:
        pass
    return terms


def read(p):
    return open(p, encoding="utf-8", errors="ignore").read() if os.path.exists(p) else None


def _within(base, target):
    """True iff realpath(target) is base itself or nested under base. Robust to
    ../ traversal and to absolute paths on a different drive (Windows)."""
    base = os.path.realpath(base)
    target = os.path.realpath(target)
    try:
        return os.path.commonpath([base, target]) == base
    except ValueError:
        # different drives / mixed abs+rel -> cannot be contained
        return False


def find_body(md):
    """content.md minus the [[...]] build tags (so tag internals don't false-positive)."""
    return re.sub(r"\[\[.*?\]\]", " ", md, flags=re.S)


def check(ws, allow_gloss=None):
    allow = set(BUILTIN_ALLOW_GLOSS)
    if allow_gloss:
        allow |= set(allow_gloss)
    hard, warn = [], []
    md = read(os.path.join(ws, "bundle", "content.md"))
    if md is None:
        return usage_error(ws, None, "bundle/content.md not found", minimal=True)
    body = find_body(md)

    # H1 no web citation in body prose. Bibliography URLs are source metadata,
    # not inline web citations; use check_sources' single section recognizer.
    _, reference_lines = check_sources.reference_section(md)
    reference_line_numbers = {line_number for line_number, _ in reference_lines}
    for line_number, line in enumerate(md.splitlines(), start=1):
        if line_number in reference_line_numbers:
            continue
        for m in re.finditer(r"(https?://|www\.)\S+", line):
            hard.append({
                "code": "H1",
                "msg": "web citation/URL in content.md",
                "at": m.group(0)[:60],
            })
    # H2 no polite endings
    for m in re.finditer(r"[가-힣](습니다|ㅂ니다|습니까)", body):
        hard.append({"code": "H2", "msg": "polite ending '~습니다' in body", "at": m.group(0)})
    # H3 figure files exist AND stay inside bundle/figures (no traversal/absolute)
    figdir = os.path.join(ws, "bundle", "figures")
    figdir_real = os.path.realpath(figdir)
    for m in re.finditer(r'\[\[FIG\s+file="([^"]+)"', md):
        fn = m.group(1)
        # Interpret the FIG path platform-agnostically: content.md may carry
        # Windows-style separators/drives even when the checker runs on POSIX
        # (where isabs/splitdrive would not recognize them).
        fn_norm = fn.replace("\\", "/")
        candidate = os.path.join(figdir, fn_norm)
        # Reject absolute paths, drive-qualified paths, and any ../ traversal that
        # escapes bundle/figures — these are HARD (a FIG must reference a bundled
        # figure, never an arbitrary filesystem location).
        if (os.path.isabs(fn_norm) or re.match(r"^[A-Za-z]:[\\/]", fn)
                or not _within(figdir_real, candidate)):
            hard.append({"code": "H3", "msg": "FIG path escapes bundle/figures (traversal/absolute)",
                         "at": fn[:60]})
            continue
        if not os.path.exists(candidate):
            hard.append({"code": "H3", "msg": "FIG file missing in bundle/figures", "at": fn})
    # H4 세특 byte cap
    for cand in [os.path.join(ws, "_saeteuk"),
                 os.path.join(os.path.dirname(ws.rstrip("/\\")), "_saeteuk")]:
        if os.path.isdir(cand):
            for f in os.listdir(cand):
                if f.endswith(".txt"):
                    b = len(read(os.path.join(cand, f)).encode("utf-8"))
                    if b > 1500:
                        hard.append({"code": "H4", "msg": f"세특 over 1500 byte ({b})", "at": f})
    # H5 assembled PDF leak check
    pdf = os.path.join(ws, "output", "out.pdf")
    if os.path.exists(pdf):
        try:
            import fitz
            txt = "".join(p.get_text() for p in fitz.open(pdf))
            for bad in ["[[", "latex=", "left(", "\\frac", "\\sigma", "\\alpha"]:
                if bad in txt:
                    hard.append({"code": "H5", "msg": f"LaTeX/tag leak in PDF: {bad!r}", "at": f"x{txt.count(bad)}"})
        except Exception as e:
            # Fail CLOSED: an assembled PDF that exists but cannot be
            # text-extracted (corrupt file, or fitz/PyMuPDF unavailable) is a
            # HARD finding — we must never pass a gate on a PDF we could not
            # inspect for LaTeX/tag leaks.
            hard.append({"code": "H5", "msg": f"pdf_uninspectable: {e}", "at": "out.pdf"})

    # W1 gloss
    for m in re.finditer(r"[가-힣]\s*\(([A-Za-z][A-Za-z ,.&'\-]*)\)", md):
        toks = re.findall(r"[A-Za-z]+", m.group(1))
        if toks and not any(t in allow for t in toks):
            warn.append({"code": "W1", "msg": "possible 괄호-영어 gloss", "at": m.group(0)[:40]})
    # W2 numbered refs
    if re.search(r"(?m)^\[\d+\]\s", md):
        warn.append({"code": "W2", "msg": "numbered [n] references (prefer author-year)"})
    # W3 in-text cite surname vs bibliography
    biblio = set(re.findall(r"(?m)^([A-Z][A-Za-z\-]+),\s", md))
    for m in re.finditer(r"([A-Z][A-Za-z\-]+)\s*\((?:19|20)\d{2}\)", body):
        if m.group(1) not in biblio:
            warn.append({"code": "W3", "msg": "in-text cite w/o bibliography match", "at": m.group(0)})

    verdict = verdict_skeleton(
        ws, None, hard=hard, warn=warn
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="deterministic content gate")
    parser.add_argument(
        "workspace", help="report workspace dir (…/workspaces/report-<slug>)"
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    parser.add_argument(
        "--allowlist", default=None,
        help=("file of extra allowed gloss terms (one per line or YAML list), "
              "merged over the neutral builtin"),
    )
    return cli_main(
        parser,
        lambda args: check(
            args.workspace, allow_gloss=load_allowlist(args.allowlist)
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
