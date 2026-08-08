# -*- coding: utf-8 -*-
"""T37 regression: self-closing runs/text elements must not steal a
sibling's body text.

Root cause (docs/trouble-table.md T37): a non-greedy body capture of the
shape ``<ns:tag\\b[^>]*>(.*?)</ns:tag>`` treats ``[^>]*>`` as "consume
attributes up to the tag's closing ``>``" — but for a self-closing element
(``<hp:run charPrIDRef="13"/>``) that ``[^>]*>`` swallows the ``/>`` as if
it were ordinary attribute text, and the ``(.*?)</ns:tag>`` that follows
then keeps scanning FORWARD past the self-close into the next paired
sibling, capturing that sibling's text and attributing it to the
self-closing element's id.

Four instances of this shape were found and fixed:
  * engine/scripts/charpr_script.py   — ``_RUN_RE``, ``_RUN_TEXT_RE``
  * engine/scripts/charpr_check.py    — ``RUN_RE``
  * engine/scripts/form_inspect.py    — ``RUN_TAG_RE``, ``T_RE``
  * engine/scripts/tidy_hwpx.py       — ``T_RE``

Each fixed pattern uses the ``/>`` | ``>(.*?)</ns:tag>`` alternation
already correctly used by ``preedit.RUN_RE`` (see its T34 self-close
comment) — a self-closing element is a complete match with no body.

The second half of T37 is about the FIX, not the bug: binding the closing
tag with a ``\\1`` backreference requires capturing the namespace prefix,
which adds a group, and a shared pattern's group COUNT is part of its public
interface — ``findall`` changes from strings to tuples and every
``.group(n)`` shifts. That broke two callers outside ``engine/``
(``check_gongmun`` crashed, ``style_diff`` would have silently read
attributes as a body). ``test_shared_pattern_group_counts_are_pinned``
below is the guard: it fails if anyone changes an arity again.
"""
import io
import os
import sys
import zipfile

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import charpr_check  # noqa: E402
import charpr_script  # noqa: E402
import form_inspect  # noqa: E402
import tidy_hwpx  # noqa: E402


# ---------------------------------------------------------------------------
# charpr_script.iter_runs (the originally-reported T30/T37 defect)
# ---------------------------------------------------------------------------

def test_iter_runs_self_closing_alone_yields_no_text():
    xml = '<hp:p><hp:run charPrIDRef="13"/></hp:p>'
    assert charpr_script.iter_runs(xml) == []


def test_iter_runs_self_closing_then_sibling_reported_case():
    """The exact reported shape: self-closing run 13 immediately followed
    by paired run 14 carrying real prose. Must NOT attribute 14's text to
    13, and 14's own text must survive."""
    xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="13"/>'
        '<hp:run charPrIDRef="14"><hp:t>진짜 본문 텍스트</hp:t></hp:run>'
        '</hp:p>'
    )
    runs = charpr_script.iter_runs(xml)
    assert ("13", "진짜 본문 텍스트") not in runs
    assert runs == [("14", "진짜 본문 텍스트")]


def test_iter_runs_several_self_closing_in_a_row():
    xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="1"/>'
        '<hp:run charPrIDRef="2"/>'
        '<hp:run charPrIDRef="3"/>'
        '<hp:run charPrIDRef="4"><hp:t>본문</hp:t></hp:run>'
        '</hp:p>'
    )
    assert charpr_script.iter_runs(xml) == [("4", "본문")]


def test_iter_runs_self_closing_run_text_element():
    """A paired run whose only child hp:t is itself self-closing
    (<hp:t/>) — the run has body but no text, and a sibling paired hp:t
    that follows must not have its text stolen either."""
    xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="5"><hp:t/></hp:run>'
        '<hp:run charPrIDRef="6"><hp:t>다음 런 텍스트</hp:t></hp:run>'
        '</hp:p>'
    )
    runs = charpr_script.iter_runs(xml)
    assert ("5", "다음 런 텍스트") not in runs
    assert runs == [("6", "다음 런 텍스트")]


# ---------------------------------------------------------------------------
# charpr_check.RUN_RE / _runs (offline size/color audit)
# ---------------------------------------------------------------------------

def _make_hwpx(tmp_path, section_xml, header_xml=None):
    header_xml = header_xml or (
        '<hh:charProperties>'
        '<hh:charPr id="0" height="1000" textColor="#000000"/>'
        '<hh:charPr id="13" height="1000" textColor="#000000"/>'
        '<hh:charPr id="14" height="1000" textColor="#000000"/>'
        '</hh:charProperties>'
    )
    path = tmp_path / "synthetic.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header_xml)
        z.writestr("Contents/section0.xml", section_xml)
    return path


def test_charpr_check_run_re_self_closing_then_sibling(tmp_path):
    """Distinct ids (13 vs 14, the reported T30 shape) so a mis-attribution
    would show up as the WRONG cid owning the text, not just wrong text."""
    section_xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="13"/>'
        '<hp:run charPrIDRef="14"><hp:t>본문 텍스트</hp:t></hp:run>'
        '</hp:p>'
    )
    path = _make_hwpx(tmp_path, section_xml)
    runs, _defs = charpr_check._runs(str(path))
    assert len(runs) == 1
    assert runs[0]["cid"] == "14"
    assert runs[0]["text"] == "본문 텍스트"


def test_charpr_check_run_re_several_self_closing_in_a_row(tmp_path):
    section_xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="0"/>'
        '<hp:run charPrIDRef="13"/>'
        '<hp:run charPrIDRef="0"/>'
        '<hp:run charPrIDRef="14"><hp:t>끝 텍스트</hp:t></hp:run>'
        '</hp:p>'
    )
    path = _make_hwpx(tmp_path, section_xml)
    runs, _defs = charpr_check._runs(str(path))
    assert len(runs) == 1
    assert runs[0]["cid"] == "14"
    assert runs[0]["text"] == "끝 텍스트"


def test_charpr_check_run_re_self_closing_alone(tmp_path):
    section_xml = '<hp:p><hp:run charPrIDRef="0"/></hp:p>'
    path = _make_hwpx(tmp_path, section_xml)
    runs, _defs = charpr_check._runs(str(path))
    assert runs == []


# ---------------------------------------------------------------------------
# form_inspect.RUN_TAG_RE / T_RE (via _paragraphs)
# ---------------------------------------------------------------------------

def test_form_inspect_paragraphs_self_closing_then_sibling():
    xml = (
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="13"/>'
        '<hp:run charPrIDRef="14"><hp:t>진짜 본문</hp:t></hp:run>'
        '</hp:p>'
    )
    paras = form_inspect._paragraphs(xml, {})
    assert len(paras) == 1
    assert paras[0]["text"] == "진짜 본문"
    # The self-closing run's own id must still be reported (T30 pre-flight
    # needs it — it may be the fill-target run) even though it owns no text.
    assert paras[0]["charPrs"] == ["13", "14"]


def test_form_inspect_paragraphs_self_closing_alone():
    xml = '<hp:p paraPrIDRef="0"><hp:run charPrIDRef="7"/></hp:p>'
    paras = form_inspect._paragraphs(xml, {})
    assert paras[0]["text"] == ""
    assert paras[0]["charPrs"] == ["7"]


def test_form_inspect_paragraphs_several_self_closing_in_a_row():
    xml = (
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="1"/>'
        '<hp:run charPrIDRef="2"/>'
        '<hp:run charPrIDRef="3"/>'
        '<hp:run charPrIDRef="4"><hp:t>본문</hp:t></hp:run>'
        '</hp:p>'
    )
    paras = form_inspect._paragraphs(xml, {})
    assert paras[0]["text"] == "본문"
    assert paras[0]["charPrs"] == ["1", "2", "3", "4"]


def test_form_inspect_top_level_paragraphs_self_closing_then_sibling():
    xml = (
        '<hp:p paraPrIDRef="0">'
        '<hp:run charPrIDRef="13"/>'
        '<hp:run charPrIDRef="14"><hp:t>진짜 본문</hp:t></hp:run>'
        '</hp:p>'
    )
    paras = form_inspect._find_top_level_paragraphs(xml)
    assert len(paras) == 1
    assert paras[0][2] == "진짜 본문"


# ---------------------------------------------------------------------------
# tidy_hwpx.T_RE / _para_text
#
# Note: _para_text's only consumer concatenates ALL hp:t text in a paragraph
# and then strips every complete `<...>` tag from the joined result. Because
# well-formed hwpx XML never has bare (unwrapped) text outside an hp:t, the
# "stolen" span the old regex captured across a self-closing hp:t always
# consisted of complete tags (later stripped) interleaved with the *same*
# real text that a correct parse would also have found, in the same order
# — so the corruption happened to be invisible through this specific flat
# string interface even on the old regex. It is still the same broken
# shape (kb/trouble-table.md T37) and is fixed here defensively, since nothing
# guarantees a future caller of T_RE stays limited to that safe interface.
# ---------------------------------------------------------------------------

def test_tidy_hwpx_para_text_self_closing_then_sibling():
    p_xml = (
        '<hp:p>'
        '<hp:run charPrIDRef="13"><hp:t/></hp:run>'
        '<hp:run charPrIDRef="14"><hp:t>다음 문단 텍스트</hp:t></hp:run>'
        '</hp:p>'
    )
    assert tidy_hwpx._para_text(p_xml) == "다음 문단 텍스트"


def test_tidy_hwpx_para_text_self_closing_alone():
    p_xml = '<hp:p><hp:run charPrIDRef="13"><hp:t/></hp:run></hp:p>'
    assert tidy_hwpx._para_text(p_xml) == ""


def test_tidy_hwpx_para_text_several_self_closing_in_a_row():
    p_xml = (
        '<hp:p>'
        '<hp:t/><hp:t/><hp:t/>'
        '<hp:t>본문</hp:t>'
        '</hp:p>'
    )
    assert tidy_hwpx._para_text(p_xml) == "본문"


# ---------------------------------------------------------------------------
# T37, second half: a shared pattern's group count is an interface
# ---------------------------------------------------------------------------

#: ``module attribute -> groups``, pinned at the arity every caller in the
#: TREE (not just in ``engine/``) already unpacks. Raising one of these is an
#: interface change: ``findall`` starts returning tuples instead of strings and
#: every ``.group(n)`` past the new group shifts by one. The T37 fix hit this
#: for real — ``modules/gongmun`` crashed on ``form_inspect.T_RE.findall`` and
#: ``engine/scripts/style_diff.py`` would have read attributes as a run body.
#: If a deliberate arity change is ever right, update this table in the SAME
#: commit as every caller, so the diff shows the blast radius.
SHARED_PATTERN_ARITY = (
    ("charpr_script", "_RUN_RE", 2),
    ("charpr_script", "_RUN_TEXT_RE", 1),
    ("charpr_check", "RUN_RE", 3),
    ("form_inspect", "RUN_TAG_RE", 2),
    ("form_inspect", "T_RE", 1),
    ("tidy_hwpx", "T_RE", 1),
)


def test_shared_pattern_group_counts_are_pinned():
    modules = {
        "charpr_script": charpr_script,
        "charpr_check": charpr_check,
        "form_inspect": form_inspect,
        "tidy_hwpx": tidy_hwpx,
    }
    actual = tuple(
        (mod, attr, getattr(modules[mod], attr).groups)
        for mod, attr, _ in SHARED_PATTERN_ARITY)
    assert actual == SHARED_PATTERN_ARITY


def test_self_closing_leaves_the_body_group_empty_not_absent():
    """The alternation must keep the body group PRESENT and falsy.

    Callers distinguish "self-closing, no text" from "paired, empty text" by
    truthiness, so both must be falsy — but the group has to exist, or
    ``findall`` would drop back to a bare-string shape for one branch and a
    tuple for the other.
    """
    xml = ('<hp:run charPrIDRef="13"/>'
           '<hp:run charPrIDRef="14"><hp:t>수신</hp:t></hp:run>')
    found = charpr_script._RUN_RE.findall(xml)
    assert found == [("13", ""), ("14", "<hp:t>수신</hp:t>")]
