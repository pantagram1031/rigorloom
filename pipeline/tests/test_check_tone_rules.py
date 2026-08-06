# -*- coding: utf-8 -*-
"""Tests for the H4 tone-rulepack regression check."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_tone_rules.py"
_spec = importlib.util.spec_from_file_location("check_tone_rules", SCRIPT)
check_tone_rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_tone_rules)


CLEAN_PROSE = (
    "## SECTION: IV.  결과 및 분석\n\n"
    "평균 실행 시간은 3.42초로 측정되었다. 노드 수를 두 배로 늘리자 "
    "탐색 횟수는 1,204회에서 2,391회로 증가했다.\n\n"
    "측정값의 표준편차는 0.08초였다. 이 결과는 이론 예측과 부합한다.\n"
)

HEDGED_MEASURED = (
    "## SECTION: IV.  결과 및 분석\n\n"
    "평균 실행 시간은 3.42초로 감소한 것으로 보인다. "
    "탐색 횟수는 약 1,204회로 추정된다.\n\n"
    "다만 편차가 커서 아마 0.1초 수준의 오차가 남는다.\n"
)


def pack(rules):
    return {
        "schema": "report-pipeline/preference-pack/tone_rules-v1",
        "pack_type": "tone_rules",
        "name": "test-pack",
        "version": 1,
        "rules": rules,
    }


class CheckToneRulesBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, text, **kwargs):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")
        return check_tone_rules.check(str(self.ws), **kwargs)


class HedgeOnMeasuredValueTests(CheckToneRulesBase):
    def test_hedged_measured_claims_warn(self):
        verdict, code = self.run_check(HEDGED_MEASURED)
        self.assertEqual(code, 0, verdict)  # WARN-only by default
        self.assertTrue(verdict["ok"])
        hits = [w for w in verdict["warn"] if w["code"] == "tone:hedge-on-measured"]
        self.assertEqual(len(hits), 3, verdict)
        self.assertEqual(verdict["hard"], [])
        self.assertEqual(
            verdict["metrics"]["hedge-on-measured"]["flagged_sentences"], 3
        )

    def test_clean_prose_passes_with_no_findings(self):
        verdict, code = self.run_check(CLEAN_PROSE)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["hard"], [])
        self.assertEqual(verdict["warn"], [])

    def test_hedge_without_numeral_is_not_flagged(self):
        text = "이 방식이 더 자연스러운 서술일 수 있다. 결과는 견고한 것으로 보인다.\n"
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["warn"], [])

    def test_numeral_without_hedge_is_not_flagged(self):
        text = "총 3회의 반복 측정에서 평균은 12.5였다.\n"
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["warn"], [])

    def test_build_tags_are_stripped_before_matching(self):
        text = "[[FIG:1 아마 3.42초인 것으로 보인다]]\n\n본문은 깨끗하다.\n"
        verdict, code = self.run_check(text)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["warn"], [])

    def test_pack_can_override_hedge_patterns(self):
        rules = [{
            "id": "custom-hedge",
            "kind": "hedge_on_measured_value",
            "patterns": ["듯하다"],
        }]
        verdict, code = self.run_check(
            "평균은 3.42초인 듯하다. 최댓값은 9.1초로 추정된다.\n",
            pack=pack(rules),
        )
        self.assertEqual(code, 0, verdict)
        hits = [w for w in verdict["warn"] if w["code"] == "tone:custom-hedge"]
        self.assertEqual(len(hits), 1, verdict)  # 추정된다 no longer matches


class ConclusionPivotDensityTests(CheckToneRulesBase):
    def test_pivot_inflation_warns(self):
        body = (
            "따라서 이 알고리즘이 더 빠르다. "
            "그러므로 캐시 효율이 원인이다. "
            "따라서 추가 실험이 필요하다. 본문 서술이 이어진다."
        )
        verdict, code = self.run_check(body + "\n")
        self.assertEqual(code, 0, verdict)
        hits = [w for w in verdict["warn"]
                if w["code"] == "tone:conclusion-pivot-inflation"]
        self.assertEqual(len(hits), 1, verdict)
        metrics = verdict["metrics"]["conclusion-pivot-inflation"]
        self.assertEqual(metrics["pivot_starts"], 3)
        self.assertGreaterEqual(metrics["density_per_10k"], 2.0)

    def test_density_is_reported_even_below_threshold(self):
        # One pivot in long prose: the regression metric must still be there.
        body = "따라서 결론이 나온다. " + ("측정 절차를 반복해 서술한다. " * 400)
        verdict, code = self.run_check(body + "\n")
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["warn"], [])
        metrics = verdict["metrics"]["conclusion-pivot-inflation"]
        self.assertEqual(metrics["pivot_starts"], 1)
        self.assertLess(metrics["density_per_10k"], 2.0)

    def test_mid_sentence_pivot_words_do_not_count_as_starts(self):
        body = "이 결과는 캐시 효율에 기인하며 그러므로라는 접속사는 쓰지 않았다. " \
               + ("본문 서술. " * 10)
        verdict, code = self.run_check(body + "\n")
        self.assertEqual(code, 0, verdict)
        metrics = verdict["metrics"]["conclusion-pivot-inflation"]
        self.assertEqual(metrics["pivot_starts"], 0)

    def test_threshold_is_pack_parameterizable(self):
        rules = [{
            "id": "strict-pivot",
            "kind": "conclusion_pivot_density",
            "params": {"warn_per_10k": 0.5},
        }]
        body = "따라서 결론이 나온다. " + ("본문 서술을 이어간다. " * 50)
        verdict, code = self.run_check(body + "\n", pack=pack(rules))
        self.assertEqual(code, 0, verdict)
        hits = [w for w in verdict["warn"] if w["code"] == "tone:strict-pivot"]
        self.assertEqual(len(hits), 1, verdict)


class SeverityAndScopeTests(CheckToneRulesBase):
    def test_pack_can_escalate_severity_to_hard(self):
        rules = [{
            "id": "hedge-hard",
            "kind": "hedge_on_measured_value",
            "severity": "hard",
        }]
        verdict, code = self.run_check(HEDGED_MEASURED, pack=pack(rules))
        self.assertEqual(code, 3, verdict)
        self.assertFalse(verdict["ok"])
        self.assertTrue(all(h["code"] == "tone:hedge-hard" for h in verdict["hard"]))

    def test_scope_limits_rule_to_named_section(self):
        text = (
            "## SECTION: IV.  결과 및 분석\n\n"
            "따라서 결과 절의 피벗은 스코프 밖이다.\n\n"
            "## SECTION: V.  결론\n\n"
            "따라서 최종 결론이 성립한다. 그러므로 후속 탐구가 필요하다.\n"
        )
        rules = [{
            "id": "conclusion-pivot",
            "kind": "conclusion_pivot_density",
            "scope": "conclusion",
            "params": {"warn_per_10k": 0.5},
        }]
        verdict, code = self.run_check(text, pack=pack(rules))
        self.assertEqual(code, 0, verdict)
        metrics = verdict["metrics"]["conclusion-pivot"]
        self.assertEqual(metrics["pivot_starts"], 2)  # results-section pivot excluded
        self.assertEqual(metrics["scope"], "conclusion")


class PackAndUsageTests(CheckToneRulesBase):
    def test_default_pack_file_is_valid_and_loads(self):
        loaded = check_tone_rules._load_pack(None)
        self.assertIsInstance(loaded, dict, loaded)
        self.assertEqual(loaded["name"], "neutral-default")
        kinds = {rule["kind"] for rule in loaded["rules"]}
        self.assertEqual(kinds, set(check_tone_rules.RULE_KINDS))
        # WARN-only by default: the shipped neutral pack must not escalate.
        for rule in loaded["rules"]:
            self.assertEqual(rule.get("severity", "warn"), "warn", rule)

    def test_pack_file_path_is_accepted(self):
        pack_path = self.ws / "tone.json"
        pack_path.write_text(json.dumps(pack([
            {"id": "p", "kind": "conclusion_pivot_density"},
        ]), ensure_ascii=False), encoding="utf-8")
        verdict, code = self.run_check(CLEAN_PROSE, pack=str(pack_path))
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["pack"]["name"], "test-pack")

    def test_unknown_rule_kind_is_usage_error(self):
        verdict, code = self.run_check(
            CLEAN_PROSE, pack=pack([{"id": "x", "kind": "made_up_kind"}])
        )
        self.assertEqual(code, 2, verdict)

    def test_duplicate_rule_id_is_usage_error(self):
        verdict, code = self.run_check(
            CLEAN_PROSE,
            pack=pack([
                {"id": "dup", "kind": "conclusion_pivot_density"},
                {"id": "dup", "kind": "hedge_on_measured_value"},
            ]),
        )
        self.assertEqual(code, 2, verdict)

    def test_invalid_regex_is_usage_error(self):
        verdict, code = self.run_check(
            CLEAN_PROSE,
            pack=pack([
                {"id": "bad", "kind": "hedge_on_measured_value",
                 "patterns": ["("]},
            ]),
        )
        self.assertEqual(code, 2, verdict)

    def test_invalid_threshold_is_usage_error(self):
        verdict, code = self.run_check(
            CLEAN_PROSE,
            pack=pack([
                {"id": "bad", "kind": "conclusion_pivot_density",
                 "params": {"warn_per_10k": -1}},
            ]),
        )
        self.assertEqual(code, 2, verdict)

    def test_missing_pack_file_is_usage_error(self):
        verdict, code = self.run_check(
            CLEAN_PROSE, pack=str(self.ws / "nope.json")
        )
        self.assertEqual(code, 2, verdict)

    def test_missing_content_is_usage_error(self):
        verdict, code = check_tone_rules.check(str(self.ws))
        self.assertEqual(code, 2, verdict)
        self.assertFalse(verdict["ok"])

    def test_empty_content_is_usage_error(self):
        verdict, code = self.run_check("")
        self.assertEqual(code, 2, verdict)


if __name__ == "__main__":
    unittest.main()
