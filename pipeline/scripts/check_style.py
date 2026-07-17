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
  report_structure.title_format mismatch vs title metadata, falling back
    to the first heading (best-effort)
"""
import sys, os, re, json, argparse
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import personalization_ctl  # noqa: E402  (stdlib-only sibling module)
import claim_extraction  # noqa: E402
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)

_DEFAULTS_DIR = _SCRIPTS_DIR.parent / "references" / "preference_packs" / "defaults"
DEFAULT_PROSE_PACK = _DEFAULTS_DIR / "prose_rules.json"
DEFAULT_GLOSS_PACK = _DEFAULTS_DIR / "gloss_allowlist.json"

# in-text parenthetical citation, e.g. "(김철수, 2020)" or "(Smith, 2019)".
CITATION_PAREN_RE = re.compile(r"\([가-힣A-Za-z .]+,\s*\d{4}\)")
DEFAULT_TITLE_METADATA_KEYS = ("title", "제목")


def _title_metadata_re(additional_keys=None):
    keys = list(DEFAULT_TITLE_METADATA_KEYS)
    if isinstance(additional_keys, list):
        keys.extend(
            key.strip()
            for key in additional_keys
            if isinstance(key, str) and key.strip()
        )
    key_pattern = "|".join(re.escape(key) for key in dict.fromkeys(keys))
    return re.compile(
        rf"^\s*(?:{key_pattern})\s*[:：]\s*(?P<title>\S.*)\s*$",
        re.I,
    )


TITLE_METADATA_RE = _title_metadata_re()


def read(p):
    return open(p, encoding="utf-8", errors="ignore").read() if os.path.exists(p) else None


def find_body(md):
    """content.md minus the [[...]] build tags (so tag internals don't false-positive).
    Same approach as verify_content.find_body."""
    return re.sub(r"\[\[.*?\]\]", " ", md, flags=re.S)


def first_heading(md):
    m = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", md)
    return m.group(1).strip() if m else None


def metadata_title(md, additional_keys=None):
    """Return a recognized title metadata value before the first heading."""
    matcher = (
        _title_metadata_re(additional_keys)
        if additional_keys
        else TITLE_METADATA_RE
    )
    for line in md.splitlines():
        if re.match(r"^\s*#{1,6}(?:\s+|$)", line):
            break
        match = matcher.match(line)
        if match:
            return match.group("title").strip()
    return None


def _default_gloss_terms():
    pack = personalization_ctl.load_pack_file(DEFAULT_GLOSS_PACK)
    terms = pack.get("terms", []) if isinstance(pack, dict) else []
    return {term for term in terms if isinstance(term, str) and term}


def _gloss_match_is_allowed(matched, allowed):
    """Use exact parenthetical terms so short unit symbols cannot over-exempt."""
    parenthetical = [
        value.strip()
        for value in re.findall(r"\(([^()]*)\)", matched)
        if value.strip()
    ]
    return any(value in allowed for value in parenthetical)


def _title_format_to_regex(title_format):
    """Turn a title_format template ('An Inquiry into {topic}') into a loose
    regex by escaping literals and replacing {placeholder} runs with '.+'."""
    parts = re.split(r"\{[^}]*\}", title_format)
    return "^" + ".+".join(re.escape(p) for p in parts) + "$"


def check(ws, prose_pack=None, structure_pack=None, allow_terms=None):
    hard, warn = [], []
    md = read(os.path.join(ws, "bundle", "content.md"))
    if md is None:
        return usage_error(ws, None, "bundle/content.md not found", minimal=True)
    body = find_body(md)
    operator_allow_terms = set(allow_terms or [])
    unit_terms = {
        alias
        for alias, (canonical, dimension) in (
            claim_extraction.UNION_UNIT_ALIASES.items()
        )
        if dimension != "count" and alias == canonical
    }
    unit_terms.update(
        canonical
        for canonical, dimension in claim_extraction.UNION_UNIT_ALIASES.values()
        if dimension != "count"
    )
    gloss_allow_terms = (
        operator_allow_terms | _default_gloss_terms() | unit_terms
    )

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
            # Gloss matches use exact parenthetical terms. Unit symbols come
            # from claim_extraction's dictionary; public and operator gloss
            # packs are additive. Other ban ids retain the legacy substring
            # exemption for explicitly supplied operator terms.
            if (
                pid == "gloss-english"
                and _gloss_match_is_allowed(matched, gloss_allow_terms)
            ) or (
                pid != "gloss-english"
                and any(
                    term and term in matched
                    for term in operator_allow_terms
                )
            ):
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
        heading = metadata_title(
            md, structure_pack.get("title_metadata_keys")
        ) or first_heading(md)
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

    verdict = verdict_skeleton(
        ws, "check_style", hard=hard, warn=warn
    )
    return verdict, exit_code(hard=hard)


def _load_pack(path, default_path):
    src = Path(path) if path else Path(default_path)
    return personalization_ctl.load_pack_file(src)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="deterministic prose/structure style gate"
    )
    parser.add_argument(
        "workspace", help="report workspace dir (…/workspaces/report-<slug>)"
    )
    parser.add_argument(
        "--pack", default=None,
        help=("prose_rules pack file (JSON or YAML subset); "
              "default = neutral public prose_rules.json"),
    )
    parser.add_argument(
        "--structure-pack", default=None,
        help="report_structure pack file (optional; enables citation/title checks)",
    )
    parser.add_argument(
        "--allowlist", default=None,
        help=("one-term-per-line file; a banned-pattern match containing "
              "an allowlisted term is exempted (units/symbols/proper nouns)"),
    )
    parser.add_argument("--out", default=None, help="write verdict JSON here")

    def invoke(args):
        prose_pack = _load_pack(args.pack, DEFAULT_PROSE_PACK)
        structure_pack = (
            personalization_ctl.load_pack_file(Path(args.structure_pack))
            if args.structure_pack else None
        )
        allow_terms = []
        if args.allowlist:
            raw = read(args.allowlist)
            if raw is None:
                return usage_error(
                    args.workspace,
                    None,
                    f"allowlist not found: {args.allowlist}",
                    minimal=True,
                )
            allow_terms = [
                line.strip()
                for line in raw.splitlines()
                if line.strip() and not line.startswith("#")
            ]
        return check(
            args.workspace,
            prose_pack=prose_pack,
            structure_pack=structure_pack,
            allow_terms=allow_terms,
        )

    return cli_main(parser, invoke, argv)


if __name__ == "__main__":
    raise SystemExit(main())
