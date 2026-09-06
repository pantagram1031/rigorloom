"""What the cache's own line ends say about ``breakNonLatinWord`` (#314).

#313 found the cache cutting INSIDE Hangul words in paragraphs that declare
``hh:breakSetting@breakNonLatinWord="KEEP_WORD"`` — ``moel-2013`` ¶261 between
``예금통장``/``에``, ``saeopja`` ¶189 between ``제61조제3``/``항`` — and measured
what happens when a syllable break is allowed everywhere: the break score goes
48/113 to 89/113 on the installed-face half and 21/47 to 10/47 on the rest.
Thirteen paragraphs the shipped tree reproduces stop being reproduced.

This probe asks the two questions that decides whether a narrower rule exists.

THE CUT-CLASS MATRIX (``--census``)
-----------------------------------
Path A, a cache read: no render, no reference PDF.  Every paragraph in the
public corpus is censused for what it DECLARES (``breakNonLatinWord``,
``breakLatinWord``, ``lineWrap``, ``condense``, ``widowOrphan``, alignment),
and every cached line end in a multi-line paragraph is classified by the two
characters it fell between:

``space``              one side is whitespace — an 어절 boundary;
``inside-cjk-word``    both sides are CJK cells inside one 어절 — a syllable
                       break, which ``KEEP_WORD`` is supposed to forbid;
``inside-latin-word``  both sides are Latin letters inside one word;
``inside-digit-group`` both sides are digits inside one number;
``script-change``      a word-internal boundary where the script changes
                       (Hangul against digit, say);
``punctuation``        at least one side is punctuation.

Crossed with the declared value, that table is the whole evidence about what
``KEEP_WORD`` means to the engine that wrote the cache.

THE NARROWINGS (``--candidates``, ``--regressions``)
----------------------------------------------------
Path B, our own flow pass re-laying the original out and scored against the
cache by ``advance_probe.break_scoreboard``.  Path C — an edited candidate
against licensed Hancom output — IS NOT RUN, here or anywhere in this repo.

``syllable`` is #313's rule: ``breakNonLatinWord`` read as ``BREAK_WORD`` on
every paragraph.  Because ``own_render.break_opportunities`` allows a break
wherever EITHER side is a CJK cell, that rule is broader than its name — it
also opens Hangul-against-Latin, Hangul-against-digit and
Hangul-against-punctuation boundaries.  The narrowings below cut it back along
exactly the seams the public documents name, so that "a syllable rule with a
Latin-word / digit-group / punctuation exception" is measured rather than
assumed.  ``--regressions`` then prints, for every paragraph a narrowing
loses, the cached cut, our cut, the character classes on both, and the
quantity the breaker actually compared: the line box MINUS the hanging indent,
with the trailing 자간 gap counted, against ``RIGHT_EDGE_TOLERANCE_HWP``.

Usage::

    python engine/scripts/syllable_break_probe.py --corpus --census
    python engine/scripts/syllable_break_probe.py --corpus --candidates
    python engine/scripts/syllable_break_probe.py --corpus --regressions
    python engine/scripts/syllable_break_probe.py --corpus --census \\
        --json out.json --no-text

This is measurement.  On its own it changes nothing in ``own_render.py``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import advance_probe  # noqa: E402
import layout_divergence  # noqa: E402
import lineseg_vs_pdf  # noqa: E402
import own_render  # noqa: E402
from cli_io import utf8_stdio  # noqa: E402

_iattr = own_render._iattr
_local = own_render._local

#: The paraPr fields the census reports, in the order it reports them.
DECLARED = ("break_non_latin", "break_latin", "line_wrap", "align",
            "condense", "widow_orphan")

CUT_CLASSES = ("space", "inside-cjk-word", "inside-latin-word",
               "inside-digit-group", "script-change", "punctuation")


# --------------------------------------------------------------------------
# Character classes
# --------------------------------------------------------------------------
# ``own_render.break_class`` reduces every character to SPACE / CJK / OBJECT /
# LATIN, because that is all ``hh:breakSetting`` distinguishes.  A cut has to
# be classified more finely than that -- "inside a Latin word" and "between a
# digit and a bracket" are different facts and the shipped class calls both
# LATIN -- so this is a second, finer partition used for reporting only.  It
# is derived from ``own_render.script_slot`` wherever that answers, so the two
# cannot drift apart on what counts as Hangul.

def char_class(ch):
    """The reporting class of ``ch``: Hangul, Latin, digit, punctuation, ..."""
    if ch is None:
        return "none"
    if ch in own_render.SPACE_CHARS:
        return "space"
    slot = own_render.script_slot(ch)
    if slot in ("hangul", "hanja", "japanese"):
        return {"hangul": "hangul", "hanja": "hanja",
                "japanese": "kana"}[slot]
    code = ord(ch)
    if 0x30 <= code <= 0x39:
        return "digit"
    if 0xFF10 <= code <= 0xFF19:
        return "fullwidth-digit"
    if slot == "latin":
        return "latin"
    if 0x3000 <= code <= 0x303F or 0xFF01 <= code <= 0xFF60:
        return "fullwidth-punct"
    return "punct"


#: The classes that are part of a word rather than a boundary.
WORD_CLASSES = frozenset(("hangul", "hanja", "kana", "digit",
                          "fullwidth-digit", "latin"))
CJK_CLASSES = frozenset(("hangul", "hanja", "kana"))
DIGIT_CLASSES = frozenset(("digit", "fullwidth-digit"))


def cut_class(prev, nxt):
    """How a line end that fell between ``prev`` and ``nxt`` should be read."""
    a, b = char_class(prev), char_class(nxt)
    if "space" in (a, b):
        return "space"
    if a in CJK_CLASSES and b in CJK_CLASSES:
        return "inside-cjk-word"
    if a == "latin" and b == "latin":
        return "inside-latin-word"
    if a in DIGIT_CLASSES and b in DIGIT_CLASSES:
        return "inside-digit-group"
    if a in WORD_CLASSES and b in WORD_CLASSES:
        return "script-change"
    return "punctuation"


# --------------------------------------------------------------------------
# The narrowings
# --------------------------------------------------------------------------
# Each predicate answers: beyond what the paragraph DECLARES, may a line break
# between ``a`` and ``b``?  ``own_render.break_opportunities``'s own filters --
# never before a space, ``BREAK_AFTER_ALWAYS``, and the 금칙 table -- are
# re-applied unchanged around every one of them, so a narrowing can differ
# from the shipped function in the word-integrity step and nowhere else.

def _cjk(ch):
    return own_render.break_class(ch) in ("CJK", "OBJECT")


def _alnum_latin(ch):
    return ch.isalnum() and not _cjk(ch)


def _digit(ch):
    return ch.isdigit() and not _cjk(ch)


NARROWINGS = {
    # #313's rule, restated as a predicate so it is scored the same way.
    "syllable": (
        "breakNonLatinWord read as BREAK_WORD everywhere (글자 단위): a break "
        "wherever EITHER side is a CJK cell",
        lambda a, b: _cjk(a) or _cjk(b)),
    "cjk-cjk": (
        "a break only where BOTH sides are CJK cells -- a syllable break and "
        "nothing else; Latin words, digit groups and punctuation keep the "
        "declared KEEP_WORD",
        lambda a, b: _cjk(a) and _cjk(b)),
    "cjk-cjk+alnum": (
        "the same, plus a script change against a Latin word or a digit "
        "group, which the cache does use -- but never INSIDE one",
        lambda a, b: ((_cjk(a) and _cjk(b))
                      or (_cjk(a) and _alnum_latin(b))
                      or (_alnum_latin(a) and _cjk(b)))),
    "cjk-cjk+digit": (
        "the same, but the script change is allowed only against a digit",
        lambda a, b: ((_cjk(a) and _cjk(b))
                      or (_cjk(a) and _digit(b))
                      or (_digit(a) and _cjk(b)))),
}

CANDIDATE_ORDER = ("shipped", "syllable", "cjk-cjk", "cjk-cjk+alnum",
                   "cjk-cjk+digit")


def narrowed(predicate):
    """``own_render.break_opportunities`` with ``predicate`` added.

    ``compute_lines`` calls the module-level function, so rebinding it is the
    break-opportunity seam: one function, both renderers, nothing else
    touched.
    """
    def rule(text, break_latin="KEEP_WORD", break_non_latin="KEEP_WORD"):
        ops = []
        for i in range(1, len(text)):
            a, b = text[i - 1], text[i]
            ca, cb = own_render.break_class(a), own_render.break_class(b)
            if cb == "SPACE":
                continue
            if ca == "SPACE":
                allowed = True
            elif a in own_render.BREAK_AFTER_ALWAYS:
                allowed = True
            elif ca in ("CJK", "OBJECT") or cb in ("CJK", "OBJECT"):
                allowed = (break_non_latin == "BREAK_WORD") or predicate(a, b)
            else:
                allowed = (break_latin == "BREAK_WORD")
            if not allowed:
                continue
            if (b in own_render.LINE_START_PROHIBITED
                    or a in own_render.LINE_END_PROHIBITED):
                continue
            ops.append(i)
        return ops
    return rule


@contextlib.contextmanager
def installed(name):
    """Run one measurement with candidate ``name`` in the real breaker."""
    if name == "shipped":
        yield
        return
    base = own_render.break_opportunities
    own_render.break_opportunities = narrowed(NARROWINGS[name][1])
    try:
        yield
    finally:
        own_render.break_opportunities = base


# --------------------------------------------------------------------------
# The census and the matrix (path A)
# --------------------------------------------------------------------------

def cached_cuts(para):
    """The cached line starts, in the breaker's own ``chars`` index space."""
    cells = lineseg_vs_pdf.character_cells(para)
    if _iattr(para.linesegs[-1], "textpos") > len(cells):
        return None
    out = []
    for _lo, hi in lineseg_vs_pdf.cached_split(para, cells)[:-1]:
        cut = len(para.chars)
        for index in range(len(para.chars)):
            if para.cell_start[index] >= hi:
                cut = index
                break
        out.append(cut)
    return out


def census(targets, repo_root):
    """What every corpus paragraph declares, and how every cached cut fell."""
    labels = layout_divergence.short_labels([Path(p).stem for p, _ in targets])
    declared = {field: Counter() for field in DECLARED}
    matrix = defaultdict(Counter)
    per_form = defaultdict(Counter)
    examples = defaultdict(list)
    paragraphs = 0
    scored = 0
    cuts = 0
    for path, _reference in targets:
        label = labels[Path(path).stem]
        renderer = own_render.OwnRenderer(path, repo_root=repo_root)
        for section in renderer.sections:
            for el in section.iter():
                if _local(el.tag) != "p":
                    continue
                para = own_render.Paragraph(el, renderer.defs["para_pr"])
                if not para.linesegs:
                    continue
                paragraphs += 1
                for field in DECLARED:
                    declared[field][str(para.para_pr.get(field))] += 1
                if len(para.linesegs) < 2 or para.objects:
                    continue
                positions = cached_cuts(para)
                if positions is None:
                    continue
                scored += 1
                value = para.para_pr.get("break_non_latin")
                address = renderer.paragraph_index.get(id(el))
                for cut in positions:
                    if not 0 < cut < len(para.chars):
                        continue
                    prev, nxt = para.text[cut - 1], para.text[cut]
                    kind = cut_class(prev, nxt)
                    cuts += 1
                    matrix[value][kind] += 1
                    per_form[label][kind] += 1
                    if len(examples[(value, kind)]) < 3:
                        examples[(value, kind)].append(
                            {"form": label, "paragraph": address, "cut": cut,
                             "prev": prev, "next": nxt,
                             "align": para.para_pr.get("align"),
                             "context": para.text[max(0, cut - 8):cut] + "|"
                                        + para.text[cut:cut + 8]})
    return {
        "paragraphs_with_lineseg": paragraphs,
        "multiline_paragraphs_scored": scored,
        "cached_cuts": cuts,
        "declared": {k: dict(v) for k, v in declared.items()},
        "matrix": {k: dict(v) for k, v in matrix.items()},
        "per_form": {k: dict(v) for k, v in per_form.items()},
        "examples": {f"{k[0]}/{k[1]}": v for k, v in sorted(examples.items())},
    }


# --------------------------------------------------------------------------
# The candidates and their regressions (path B)
# --------------------------------------------------------------------------

def score(targets, repo_root, name, dpi=144):
    totals = Counter()
    matched = set()
    detail = {}
    with installed(name):
        for path, _reference in targets:
            stem = Path(path).stem
            for row in advance_probe.break_scoreboard(path, dpi=dpi,
                                                      repo_root=repo_root):
                key = "installed" if row["installed"] else "other"
                totals[key] += 1
                if row["match"]:
                    totals[key + "_match"] += 1
                    matched.add((stem, row["address"]))
                detail[(stem, row["address"])] = {
                    "cache": list(row["cache_breaks"]),
                    "ours": list(row["computed_breaks"]),
                    "installed": row["installed"],
                }
    return {"candidate": name, "totals": dict(totals), "matched": matched,
            "detail": detail}


def candidate_report(targets, repo_root, dpi=144, order=CANDIDATE_ORDER):
    rows = [score(targets, repo_root, name, dpi=dpi) for name in order]
    base = rows[0]["matched"]
    out = []
    for row in rows:
        out.append({
            "candidate": row["candidate"],
            "basis": ("the tree as it stands" if row["candidate"] == "shipped"
                      else NARROWINGS[row["candidate"]][0]),
            "totals": row["totals"],
            "regressions": sorted(base - row["matched"]),
            "gains": sorted(row["matched"] - base),
        })
    return out, rows


def regression_report(targets, repo_root, name, baseline, candidate,
                      dpi=144):
    """Every paragraph ``name`` loses, in the breaker's own fit arithmetic.

    The excess reported is the quantity ``_line_fits`` actually compares: the
    line box less the hanging indent, plus what ``condense`` allows, against
    the span width with its trailing 자간 gap counted.  Reporting the raw
    ``@horzsize`` instead would overstate the room on every hanging paragraph
    in the corpus, which is all thirteen of them.
    """
    lost = {(stem, address) for stem, address
            in (set(baseline["matched"]) - set(candidate["matched"]))}
    rows = []
    base_fits = own_render.OwnRenderer._line_fits
    for path, _reference in targets:
        stem = Path(path).stem
        wanted = {a for s, a in lost if s == stem}
        if not wanted:
            continue
        trace = []

        def recorder(self, para, width_hwp, avail_hwp, slack_hwp, start, end,
                     trailing_gap_hwp=0.0):
            verdict = base_fits(self, para, width_hwp, avail_hwp, slack_hwp,
                                start, end, trailing_gap_hwp)
            trace.append({"el": id(para.el), "start": start, "end": end,
                          "w": width_hwp, "avail": avail_hwp,
                          "slack": slack_hwp, "gap": trailing_gap_hwp})
            return verdict

        own_render.OwnRenderer._line_fits = recorder
        try:
            with installed(name):
                renderer = advance_probe.BreakRecordingRenderer(
                    path, dpi=dpi, repo_root=repo_root,
                    layout_policy="computed")
                renderer.render()
        finally:
            own_render.OwnRenderer._line_fits = base_fits
        metrics = advance_probe.OurMetrics(renderer)
        labels = layout_divergence.short_labels(
            [Path(p).stem for p, _ in targets])
        for section in renderer.sections:
            for el in section.iter():
                if _local(el.tag) != "p":
                    continue
                address = renderer.paragraph_index.get(id(el))
                if address not in wanted:
                    continue
                para = own_render.Paragraph(el, renderer.defs["para_pr"])
                rows.append(_regression_row(
                    labels[stem], stem, address, para, el, metrics, trace,
                    baseline["detail"][(stem, address)],
                    candidate["detail"][(stem, address)]))
    rows.sort(key=lambda row: (row["form"], row["paragraph"]))
    return rows


def _regression_row(form, stem, address, para, el, metrics, trace,
                    before, after):
    text = para.text
    cache, ours = before["cache"], after["ours"]
    cached_cut = our_cut = None
    for index, position in enumerate(cache):
        if index >= len(ours) or ours[index] != position:
            cached_cut = position
            our_cut = ours[index] if index < len(ours) else None
            break
    line_start = 0
    for position in cache:
        if position == cached_cut:
            break
        line_start = position
    mine = [t for t in trace
            if t["el"] == id(el) and t["start"] == line_start]

    def fit(cut):
        """The fit record for the span that ends at ``cut``.

        A span is only ever presented to the fit test on a non-space
        character, so a cut that follows a space is looked up at its visible
        end -- the same strip ``compute_lines`` does.
        """
        if cut is None:
            return None
        visible = cut
        while (visible > line_start
               and text[visible - 1] in own_render.SPACE_CHARS):
            visible -= 1
        for record in mine:
            if record["end"] == visible:
                return record
        return None

    def excess(record):
        if record is None:
            return None
        return (record["w"] + record["gap"] - record["avail"]
                - record["slack"])

    def where(cut):
        if cut is None:
            return None
        prev = text[cut - 1] if cut > 0 else None
        nxt = text[cut] if cut < len(text) else None
        return {"cut": cut, "prev": prev, "next": nxt,
                "prev_class": char_class(prev), "next_class": char_class(nxt),
                "cut_class": cut_class(prev, nxt),
                "context": text[max(0, cut - 8):cut] + "|"
                           + text[cut:cut + 8]}

    cached_fit, our_fit = fit(cached_cut), fit(our_cut)
    sources = sorted({metrics.run(ch, cid)["source"]
                      for ch, cid in para.chars})
    return {
        "form": form, "stem": stem, "paragraph": address,
        "align": para.para_pr.get("align"),
        "break_non_latin": para.para_pr.get("break_non_latin"),
        "break_latin": para.para_pr.get("break_latin"),
        "condense": para.para_pr.get("condense"),
        "indent": para.para_pr.get("indent"),
        "faces": sources,
        "installed_only": sources == ["installed"],
        "spacings": sorted({metrics.run(ch, cid)["spacing"]
                            for ch, cid in para.chars}),
        "cache_breaks": cache, "our_breaks": ours,
        "cached_cut": where(cached_cut), "our_cut": where(our_cut),
        "avail_hwp": cached_fit["avail"] if cached_fit else None,
        "slack_hwp": cached_fit["slack"] if cached_fit else None,
        "cached_line_hwp": cached_fit["w"] if cached_fit else None,
        "cached_excess_hwp": excess(cached_fit),
        "our_line_hwp": our_fit["w"] if our_fit else None,
        "our_excess_hwp": excess(our_fit),
        "budget_hwp": own_render.RIGHT_EDGE_TOLERANCE_HWP,
    }


# --------------------------------------------------------------------------
# Text report
# --------------------------------------------------------------------------

def _print_census(block):
    print()
    print("what the corpus declares, per paragraph carrying an hp:lineseg")
    print(f"  {block['paragraphs_with_lineseg']} paragraphs, "
          f"{block['multiline_paragraphs_scored']} of them multi-line and "
          f"scored, {block['cached_cuts']} cached line ends")
    print()
    for field in DECLARED:
        values = block["declared"][field]
        row = "  ".join(f"{k}={v}" for k, v in
                        sorted(values.items(), key=lambda kv: -kv[1]))
        print(f"  {field:<18} {row}")
    print()
    print("every cached line end, by the characters it fell between")
    print()
    head = f"  {'breakNonLatinWord':<20}" + "".join(
        f"{name:>20}" for name in CUT_CLASSES)
    print(head)
    print("  " + "-" * (len(head) - 2))
    for value in sorted(block["matrix"]):
        counts = block["matrix"][value]
        print(f"  {value:<20}" + "".join(
            f"{counts.get(name, 0):>20}" for name in CUT_CLASSES))
    print()
    for key, rows in block["examples"].items():
        for row in rows[:2]:
            print(f"  {key:<34} {row['form']} P{row['paragraph']} "
                  f"align={row['align']} {row['context']!r}")
    print()


def _print_candidates(rows):
    print()
    print("cached break positions reproduced by our own breaker, "
          "multi-line paragraphs")
    print("(path B: our flow pass on the original.  Path C -- an edited "
          "candidate against licensed")
    print(" Hancom output -- IS NOT RUN.)")
    print()
    head = (f"  {'candidate':<16}{'installed':>14}{'other':>12}"
            f"{'regress':>9}{'gain':>6}")
    print(head)
    print("  " + "-" * (len(head) - 2))
    for row in rows:
        totals = row["totals"]
        print(f"  {row['candidate']:<16}"
              f"{totals.get('installed_match', 0):>7} /"
              f"{totals.get('installed', 0):>5}"
              f"{totals.get('other_match', 0):>6} /"
              f"{totals.get('other', 0):>4}"
              f"{len(row['regressions']):>9}{len(row['gains']):>6}")
    print()
    for row in rows[1:]:
        print(f"  {row['candidate']}: {row['basis']}")
    print()


def _print_regressions(rows):
    print()
    print("every paragraph the candidate loses, in the breaker's own "
          "arithmetic")
    print("(avail = line box MINUS the hanging indent; excess counts the "
          "trailing 자간 gap)")
    print()
    head = (f"  {'form':>11} {'para':>5} {'inst':>5} {'align':>8} "
            f"{'cached':>7} {'ours':>6} {'cut classes':>31} {'avail':>8} "
            f"{'cached':>9} {'ours':>9}")
    print(head)
    print("  " + "-" * (len(head) - 2))
    for row in rows:
        cached, ours = row["cached_cut"], row["our_cut"]
        classes = (f"{cached['prev_class']}|{cached['next_class']} -> "
                   f"{ours['prev_class']}|{ours['next_class']}")
        print(f"  {row['form']:>11} {row['paragraph']:>5} "
              f"{'yes' if row['installed_only'] else 'no':>5} "
              f"{row['align']:>8} {cached['cut']:>7} {ours['cut']:>6} "
              f"{classes:>31} {row['avail_hwp']:>8.0f} "
              f"{row['cached_excess_hwp']:>+9.1f} "
              f"{row['our_excess_hwp']:>+9.1f}")
    if rows:
        print()
        print(f"  right-edge budget {rows[0]['budget_hwp']:.0f} HWPUNIT: a "
              f"span fits while its excess is no more than that")
    print()
    for row in rows:
        cached, ours = row["cached_cut"], row["our_cut"]
        print(f"  {row['form']} P{row['paragraph']}  "
              f"faces={','.join(row['faces'])} 자간={row['spacings']} "
              f"indent={row['indent']} condense={row['condense']}")
        print(f"      cache {cached['context']!r}   ours {ours['context']!r}")
    print()


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hwpx", nargs="?", help="one .hwpx form")
    parser.add_argument("--corpus", action="store_true",
                        help="every converted corpus form")
    parser.add_argument("--census", action="store_true",
                        help="the declaration census and the cut-class "
                             "matrix (a cache read, no render)")
    parser.add_argument("--candidates", action="store_true",
                        help="score every narrowing on the real breaker")
    parser.add_argument("--regressions", action="store_true",
                        help="with --candidates, diagnose what each "
                             "narrowing loses, paragraph by paragraph")
    parser.add_argument("--only", metavar="NAME",
                        help="with --regressions, diagnose just this "
                             "candidate (default: every one that loses "
                             "something)")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--json", metavar="PATH",
                        help="write the full report as JSON")
    parser.add_argument("--no-text", action="store_true",
                        help="suppress the text report (use with --json)")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    targets = []
    if args.hwpx:
        targets.append((Path(args.hwpx), None))
    if args.corpus:
        targets.extend(layout_divergence.corpus_forms(repo_root))
    if not targets:
        build_parser().error("give a form, or --corpus")
    if not (args.census or args.candidates):
        build_parser().error("give --census, --candidates, or both")

    report = {}
    if args.census:
        report["census"] = census(targets, repo_root)
        if not args.no_text:
            _print_census(report["census"])
    if args.candidates:
        rows, scored = candidate_report(targets, repo_root, dpi=args.dpi)
        report["candidates"] = rows
        if not args.no_text:
            _print_candidates(rows)
        if args.regressions:
            by_name = {row["candidate"]: row for row in scored}
            report["regressions"] = {}
            for row in rows[1:]:
                if args.only and row["candidate"] != args.only:
                    continue
                if not row["regressions"]:
                    continue
                diagnosed = regression_report(
                    targets, repo_root, row["candidate"], scored[0],
                    by_name[row["candidate"]], dpi=args.dpi)
                report["regressions"][row["candidate"]] = diagnosed
                if not args.no_text:
                    print(f"=== {row['candidate']} ===")
                    _print_regressions(diagnosed)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"report": report}, ensure_ascii=False, indent=2,
                       sort_keys=True, default=_jsonable) + "\n",
            encoding="utf-8")
    return 0


def _jsonable(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(repr(value))


if __name__ == "__main__":
    raise SystemExit(main())
