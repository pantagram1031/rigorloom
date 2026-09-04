"""Section-head control order lint (``hwpx_lint.py --section-order``).

Measured on official Automation, ten probe variants
(``docs/research/render-check-01.md`` note 4, `origin/claude/engine-e2-columns-f49`,
``engine/tests/test_column_ctrl_order.py`` on that branch, PR #222): Hancom
silently ignores an ``hp:colPr`` control that a header or footer control
precedes in the same section-head paragraph, with no repair dialog and no
warning of its own.

This module proves three things:

1. ``section_head_order`` / ``colpr_shadowed`` read the rule correctly on a
   handful of the measured probe orders.
2. A synthetic bad/good pair — built on ``hwpx_write.blank_package()``, the
   one section-head builder this branch has — is told apart, both through
   the library call and through the CLI's exit code.
3. The corpus this branch ships (``tests/corpus/forms``) passes the lint,
   and the writer-line-adjacent evidence for the rule itself — the F49 fix
   commit and its pre-fix parent on `origin/claude/engine-e2-columns-f49` —
   is told apart by the same lint, fetched read-only via ``git show`` and
   skipped (not failed) when that ref is not available locally.

    python -m pytest engine/tests/test_hwpx_lint.py -q
"""
import glob
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
CORPUS_FORMS = os.path.join(ROOT, "tests", "corpus", "forms")

sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import hwpx_lint as L  # noqa: E402
import hwpx_write as W  # noqa: E402


# ---------------------------------------------------------------------------
# 1. The rule, read off a handful of the measured probe orders
# ---------------------------------------------------------------------------

def _section(order_xml):
    """Wrap a section-head paragraph's control run in a minimal ``hs:sec``."""
    return ('<hs:sec><hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0"'
            ' columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
            + order_xml + '</hp:run></hp:p></hs:sec>')


#: One control per case, minimal attributes -- the lint only reads the tag
#: name, never the control's own content.
_SEC_PR = '<hp:secPr id=""/>'
_COL_PR = '<hp:ctrl><hp:colPr id="" colCount="2"/></hp:ctrl>'
_HEADER = '<hp:ctrl><hp:header id="1" applyPageType="BOTH"/></hp:ctrl>'
_FOOTER = '<hp:ctrl><hp:footer id="2" applyPageType="BOTH"/></hp:ctrl>'


@pytest.mark.parametrize("case,xml,shadowed", [
    # P1: secPr, header, footer, colPr -> one column (shadowed)
    ("P1", _SEC_PR + _HEADER + _FOOTER + _COL_PR, True),
    # Q1: secPr, header, colPr, footer -> one column (shadowed)
    ("Q1", _SEC_PR + _HEADER + _COL_PR + _FOOTER, True),
    # Q3: secPr, footer, colPr -> one column (shadowed)
    ("Q3", _SEC_PR + _FOOTER + _COL_PR, True),
    # Q2: secPr, colPr -> two columns (not shadowed)
    ("Q2", _SEC_PR + _COL_PR, False),
    # P4/Q4: secPr, colPr, header, footer -> two columns (not shadowed)
    ("P4", _SEC_PR + _COL_PR + _HEADER + _FOOTER, False),
])
def test_rule_matches_the_measured_probe_orders(case, xml, shadowed):
    tree = W.parse_xml_part(_section(xml).encode("utf-8"))
    order = L.section_head_order(tree.root)
    assert L.colpr_shadowed(order) is shadowed, (case, order)


def test_p5_colpr_in_the_next_paragraph_is_not_shadowed():
    # P5: secPr, header, footer in the head paragraph; colPr carried by the
    # *next* paragraph -> two columns. The lint reads one paragraph at a
    # time, so the head paragraph's own order (no colPr in it at all) must
    # not be flagged -- there is nothing to shadow yet.
    xml = ('<hs:sec>'
           '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0"'
           ' columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
           + _SEC_PR + _HEADER + _FOOTER + '</hp:run></hp:p>'
           '<hp:p id="1" paraPrIDRef="0" styleIDRef="0" pageBreak="0"'
           ' columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
           + _COL_PR + '</hp:run></hp:p>'
           '</hs:sec>')
    tree = W.parse_xml_part(xml.encode("utf-8"))
    head_order = L.section_head_order(tree.root)
    assert head_order == ["secPr", "header", "footer"]
    assert L.colpr_shadowed(head_order) is False


def test_header_own_sublist_paragraphs_are_not_descended_into():
    # A header control carries its own hp:subList > hp:p, which itself may
    # carry hp:ctrl children. Those belong to the header's content, not to
    # more section-head controls, and must not be picked up.
    header_with_content = (
        '<hp:ctrl><hp:header id="1" applyPageType="BOTH">'
        '<hp:subList><hp:p><hp:run>'
        '<hp:ctrl><hp:colPr id="" colCount="9"/></hp:ctrl>'
        '</hp:run></hp:p></hp:subList></hp:header></hp:ctrl>')
    xml = _SEC_PR + header_with_content + _FOOTER + _COL_PR
    tree = W.parse_xml_part(_section(xml).encode("utf-8"))
    order = L.section_head_order(tree.root)
    assert order == ["secPr", "header", "footer", "colPr"], order
    assert L.colpr_shadowed(order) is True


def test_no_colpr_at_all_is_not_shadowed():
    tree = W.parse_xml_part(_section(_SEC_PR + _HEADER + _FOOTER).encode("utf-8"))
    order = L.section_head_order(tree.root)
    assert "colPr" not in order
    assert L.colpr_shadowed(order) is False


# ---------------------------------------------------------------------------
# 2. A synthetic bad/good pair, end to end (library call and CLI)
# ---------------------------------------------------------------------------

def _blank_with_furniture(order):
    """A ``blank_package()`` document whose section-head paragraph also
    carries a header and a footer control, placed according to ``order``
    ("bad" puts them before colPr; "good" puts them after)."""
    package = W.blank_package()
    section = package.part("Contents/section0.xml")
    data = section.data.decode("utf-8")
    assert "</hp:secPr><hp:ctrl><hp:colPr" in data, (
        "blank section shape changed -- update this test's assumption")
    furniture = _HEADER + _FOOTER
    if order == "bad":
        data = data.replace(
            "</hp:secPr><hp:ctrl><hp:colPr",
            "</hp:secPr>" + furniture + "<hp:ctrl><hp:colPr", 1)
    else:
        assert order == "good"
        data = data.replace(
            "sameGap=\"0\"/></hp:ctrl></hp:run>",
            "sameGap=\"0\"/></hp:ctrl>" + furniture + "</hp:run>", 1)
    section.set_bytes(data.encode("utf-8"))
    return package


@pytest.fixture
def bad_good_pair(tmp_path):
    bad = tmp_path / "bad.hwpx"
    good = tmp_path / "good.hwpx"
    _blank_with_furniture("bad").write(bad)
    _blank_with_furniture("good").write(good)
    return bad, good


def test_synthetic_bad_document_is_flagged(bad_good_pair):
    bad, _good = bad_good_pair
    warnings = L.check_section_order(bad)
    assert len(warnings) == 1
    assert warnings[0]["part"] == "Contents/section0.xml"
    assert warnings[0]["order"][:3] == ["secPr", "header", "footer"]


def test_synthetic_good_document_is_clean(bad_good_pair):
    _bad, good = bad_good_pair
    assert L.check_section_order(good) == []


def test_cli_exit_codes(bad_good_pair):
    bad, good = bad_good_pair
    script = os.path.join(ENGINE, "scripts", "hwpx_lint.py")

    ok = subprocess.run([sys.executable, script, "--section-order", str(good)],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "WARN" not in ok.stdout

    bad_run = subprocess.run([sys.executable, script, "--section-order", str(bad)],
                             capture_output=True, text=True)
    assert bad_run.returncode == 1, bad_run.stdout + bad_run.stderr
    assert "WARN" in bad_run.stdout

    both = subprocess.run(
        [sys.executable, script, "--section-order", str(good), str(bad)],
        capture_output=True, text=True)
    assert both.returncode == 1
    assert both.stdout.count("WARN") == 1  # only the bad file's section

    no_check = subprocess.run([sys.executable, script, str(good)],
                              capture_output=True, text=True)
    assert no_check.returncode == 2


# ---------------------------------------------------------------------------
# 3. The corpus, and the F49 evidence itself, read-only via git show
# ---------------------------------------------------------------------------

def test_corpus_forms_pass_the_lint():
    paths = sorted(glob.glob(os.path.join(CORPUS_FORMS, "**", "*.hwpx"),
                             recursive=True))
    assert paths, "no .hwpx forms found under %s" % CORPUS_FORMS
    warnings = L.lint(paths, ["section-order"])
    assert warnings == [], warnings


def _git_show(rev_path):
    result = subprocess.run(["git", "show", rev_path], cwd=ROOT,
                            capture_output=True)
    if result.returncode != 0:
        pytest.skip("git show %s failed (ref not fetched locally): %s"
                    % (rev_path, result.stderr.decode("utf-8", "replace")))
    return result.stdout


#: 350ee56 = "corpus: hp:colPr only counts before the section furniture"
#: (`origin/claude/engine-e2-columns-f49`, PR #222) -- the commit that made
#: ``build_render_check.sec_pr`` emit ``secPr, colPr, furniture``. Its
#: parent carries the pre-fix bytes, header/footer before colPr in every
#: section.
@pytest.mark.parametrize("rev_expr,label,expect_clean", [
    ("350ee56^", "pre-fix", False),
    ("350ee56", "post-fix", True),
])
def test_f49_evidence_before_and_after_the_fix(tmp_path, rev_expr, label,
                                               expect_clean):
    data = _git_show(
        "%s:tests/corpus/render-check/render-check-01.hwpx" % rev_expr)
    path = tmp_path / ("render-check-01-%s.hwpx" % label)
    path.write_bytes(data)

    warnings = L.check_section_order(path)
    if expect_clean:
        assert warnings == [], warnings
    else:
        assert warnings, "pre-fix render-check-01.hwpx should be flagged"
