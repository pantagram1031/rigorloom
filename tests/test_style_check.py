# -*- coding: utf-8 -*-
"""``rigorloom style check`` (runtime/scripts/rt_style.py).

Every rule has one sentence it must flag and one close sentence it must leave
alone. The negative examples are the human phrasings each pattern is most
likely to catch by mistake.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_style  # noqa: E402

CLI = REPO / "runtime" / "scripts" / "cli.py"

#: rule id -> (must flag, must not flag)
EXAMPLES = {
    "ko.double-passive": ("이 방법은 널리 사용되어지고 있다.",
                          "이 방법은 널리 사용되고 있다."),
    "ko.e-isseoseo": ("교육에 있어서는 신뢰가 가장 중요하다.",
                      "그날은 집에 있어서 행사에 못 갔다."),
    "ko.e-dareum-anida": ("이는 포기에 다름 아니다.",
                          "이는 포기나 다름없다."),
    "ko.ji-anhumyeon-an-doenda": ("기한 안에 제출하지 않으면 안 된다.",
                                  "기한 안에 제출해야 한다."),
    "ko.hayeogeum": ("참가자로 하여금 직접 고르게 했다.",
                     "참가자가 직접 고르도록 했다."),
    "ko.e-uihae": ("이 장치는 연구진에 의해 개발되었다.",
                   "이 장치는 연구진이 개발했다."),
    "ko.gajigo-itda": ("이 재료는 높은 강도를 가지고 있다.",
                       "그는 우산을 가지고 나갔다."),
    "ko.geot-i-pilyohada": ("측정값을 다시 확인하는 것이 필요하다.",
                            "측정값을 다시 확인해야 한다."),
    "ko.para-opener-summary": ("결론적으로 두 방법의 차이는 작았다.",
                               "두 방법의 차이는 결론에서 다시 다룬다."),
    "ko.filler-opener": ("또한 응답자의 절반은 같은 답을 골랐다.",
                         "응답자의 절반은 또한 같은 답을 골랐다."),
    "ko.contrast-frame": ("문제는 비용이 아니라 시간이다.",
                          "비용은 문제가 되지 않았다."),
    "ko.md-bold": ("이 단계는 **반드시** 지켜야 한다.",
                   "이 단계는 반드시 지켜야 한다."),
    "ko.exclamation": ("결과가 기대보다 좋았다!",
                       "결과가 기대보다 좋았다."),
}


def _rule(rule_id):
    return [r for r in rt_style.RULES if r.id == rule_id]


def test_every_rule_has_a_positive_and_a_negative_example():
    assert set(EXAMPLES) == {r.id for r in rt_style.RULES}


@pytest.mark.parametrize("rule_id", sorted(EXAMPLES))
def test_rule_flags_its_positive_example(rule_id):
    hits = rt_style.check_text([EXAMPLES[rule_id][0]], _rule(rule_id))
    assert [h["rule"] for h in hits] == [rule_id]


@pytest.mark.parametrize("rule_id", sorted(EXAMPLES))
def test_rule_leaves_its_negative_example_alone(rule_id):
    assert rt_style.check_text([EXAMPLES[rule_id][1]], _rule(rule_id)) == []


@pytest.mark.parametrize("rule_id", sorted(EXAMPLES))
def test_negative_examples_trip_no_rule_at_all(rule_id):
    hits = rt_style.check_text([EXAMPLES[rule_id][1]], list(rt_style.RULES))
    assert hits == [], hits


def test_doc_lists_every_rule_with_both_examples():
    doc = (REPO / "docs" / "korean-style-rules.md").read_text(encoding="utf-8")
    assert rt_style.RULESET in doc
    for rule_id, (bad, good) in EXAMPLES.items():
        assert f"`{rule_id}`" in doc, rule_id
        assert bad in doc and good in doc, rule_id


def test_only_the_double_passive_is_an_error():
    # Notices are questions for a person. Promoting one to an error is a
    # ruleset change and needs a new RULESET version and this test updated.
    assert {r.id for r in rt_style.RULES if r.severity == "error"} == {"ko.double-passive"}
    assert rt_style.RULESET == "ko-style/1"


def test_doc_type_filters_rules():
    gongmun = {r.id for r in rt_style.rules_for("gongmun")}
    assert "ko.para-opener-summary" not in gongmun
    assert "ko.double-passive" in gongmun
    with pytest.raises(rt_style.StyleInputError):
        rt_style.rules_for("novel")


def test_code_fences_are_skipped(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("```\n사용되어진 값\n```\n바깥은 사용되어진다.\n", encoding="utf-8")
    result = rt_style.check(f)
    assert [(x["line"], x["rule"]) for x in result["findings"]] == [(4, "ko.double-passive")]


def test_line_and_column_point_at_the_match(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("첫 줄\n둘째 줄은 사용되어진다.\n", encoding="utf-8")
    (hit,) = rt_style.check(f)["findings"]
    assert (hit["line"], hit["col"]) == (2, 9)
    assert hit["match"] == "되어진"


def test_hwpx_is_checked_per_paragraph(tmp_path):
    section = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
               'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
               '<hp:p><hp:run><hp:t>깨끗한 문단.</hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>이 값은 사용되어진다.</hp:t></hp:run></hp:p>'
               '</hs:sec>')
    f = tmp_path / "a.hwpx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", section)
    result = rt_style.check(f)
    assert result["unit"] == "paragraph"
    assert [(x["line"], x["rule"]) for x in result["findings"]] == [(2, "ko.double-passive")]


def _cli(*args):
    proc = subprocess.run([sys.executable, str(CLI), "style", "check", *args],
                          capture_output=True, check=False,
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return proc.returncode, proc.stdout.decode("utf-8")


def test_cli_exit_codes_and_shapes(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text("측정값을 다시 확인해야 한다.\n", encoding="utf-8")
    notice = tmp_path / "notice.md"
    notice.write_text("교육에 있어서는 신뢰가 중요하다.\n", encoding="utf-8")
    error = tmp_path / "error.md"
    error.write_text("널리 사용되어진다.\n", encoding="utf-8")

    code, out = _cli(str(clean))
    body = json.loads(out)
    assert code == 0 and body["ok"] is True and body["result"]["findings"] == []
    assert body["result"]["ruleset"] == rt_style.RULESET

    code, out = _cli(str(notice))
    assert code == 0 and json.loads(out)["result"]["counts"] == {"error": 0, "notice": 1}

    code, out = _cli(str(error), "--format", "text")
    assert code == 3
    assert out.splitlines()[0].startswith(f"{error}:1:")
    assert "ko.double-passive" in out

    code, out = _cli(str(tmp_path / "missing.md"))
    assert code == 2 and json.loads(out)["error"]["code"] == "invalid_params"


def test_results_name_the_file_not_its_path(tmp_path):
    f = tmp_path / "private" / "a.md"
    f.parent.mkdir()
    f.write_text("사용되어진다.\n", encoding="utf-8")
    assert "private" not in json.dumps(rt_style.check(f), ensure_ascii=False)


def test_rules_are_for_korean_text_only():
    english = ["**Agent bootstrap:** run the setup once!", "It is used **only** here."]
    assert rt_style.check_text(english, list(rt_style.RULES)) == []
