# -*- coding: utf-8 -*-
"""bundle_spec v2 budget comments are annotation, never body text."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import build_report  # noqa: E402


def _paras(sections):
    return [b["text"] for s in sections for b in s["blocks"] if b["kind"] == "para"]


def test_whole_line_html_comment_is_skipped_and_does_not_split_paragraphs():
    text = (
        "## SECTION: Ⅰ. 서론\n"
        "<!-- budget: 16 lines -->\n"
        "첫 문장이다.\n"
        "<!-- 중간 주석 -->\n"
        "같은 문단의 둘째 문장이다.\n"
        "\n"
        "둘째 문단이다.\n"
    )
    _meta, sections = build_report.parse_content(text)
    paras = _paras(sections)
    assert paras == ["첫 문장이다. 같은 문단의 둘째 문장이다.", "둘째 문단이다."]
    assert not any("<!--" in p for p in paras)


def test_inline_comment_inside_a_sentence_is_left_alone():
    text = "## SECTION: Ⅰ. 서론\n\n각도 <!-- not a whole-line comment --> 표기.\n"
    _meta, sections = build_report.parse_content(text)
    assert _paras(sections) == ["각도 <!-- not a whole-line comment --> 표기."]
