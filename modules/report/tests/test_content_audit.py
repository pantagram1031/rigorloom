"""Tests for content_audit.py — the composite stage 4.5 gate.

Runs the REAL sub-checker chain (verify_content.py + check_style.py +
check_numbers.py + check_refs.py + check_figdata.py + check_sources.py +
check_units.py + advisory check_saeteuk.py + check_claims.py) against a
synthetic workspace. Synthetic fixtures ONLY
(홍길동-style fakes).
  - clean bundle/content.md            -> exit 0
  - planted '습니다' polite ending     -> exit 3 (via verify_content path)
  - planted '(김철수, 2020)' citation  -> exit 3 (via check_style path, with a
                                          narrative report_structure pack)
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "content_audit.py"
_spec = importlib.util.spec_from_file_location("content_audit", SCRIPT)
content_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(content_audit)


class ContentAuditTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = mock.patch.dict(os.environ, clear=False)
        self._env_patch.start()
        os.environ.pop("RIGORLOOM_PROFILE_ROOT", None)
        os.environ.pop("RIGORLOOM_REQUIRE_LEDGER", None)
        self.ws = Path(self._tmp.name) / "report-synthetic"
        (self.ws / "bundle" / "figures").mkdir(parents=True, exist_ok=True)
        figure = self.ws / "bundle" / "figures" / "plot.png"
        figure.write_bytes(b"\x89PNG\r\n")
        figure.with_name("plot.png.sha256").write_text(
            hashlib.sha256(figure.read_bytes()).hexdigest() + "  plot.png\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def write_content(self, text: str):
        (self.ws / "bundle" / "content.md").write_text(text, encoding="utf-8")

    def write_results(self, payload):
        (self.ws / "sim").mkdir(exist_ok=True)
        (self.ws / "sim" / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def make_profile_root_with_structure(self) -> Path:
        root = Path(self._tmp.name) / "profile"
        packs = root / "packs"
        packs.mkdir(parents=True, exist_ok=True)
        structure = {"schema": "x", "pack_type": "report_structure", "name": "t", "version": 1,
                     "title_format": "An Inquiry into {topic}",
                     "citation_style": {"sources": "papers_books_only", "in_text": "narrative"}}
        (packs / "report_structure.json").write_text(
            json.dumps(structure, ensure_ascii=False), encoding="utf-8")
        return root

    def make_profile_root_with_number_allowlist(self) -> Path:
        root = Path(self._tmp.name) / "profile-numbers"
        packs = root / "packs"
        packs.mkdir(parents=True, exist_ok=True)
        (packs / "numeral_allowlist.txt").write_text("12\n", encoding="utf-8")
        return root

    def _clean_body(self) -> str:
        return (
            "# 서론\n"
            "이 기록은 홍길동이 측정한 값을 정리한 글이다. 여러 조건에서 값이 안정적으로 나타났다.\n"
            '[[FIG file="plot.png"]]\n'
            "관측값은 표에 정리하였고 해석은 본문에서 이어서 다룬다.\n"
        )


class TestClean(ContentAuditTestCase):
    def test_clean_passes(self):
        self.write_content(self._clean_body())
        verdict, code = content_audit.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["counts"]["hard"], 0)
        self.assertEqual(
            set(verdict["sub_exit"]),
            {"verify_content", "check_style", "check_numbers", "check_refs",
             "check_figdata", "check_sources", "check_units", "check_saeteuk",
             "check_claims"},
        )

    def test_claim_checker_is_ninth_composed_gate(self):
        self.write_content(self._clean_body())
        missing_id = "local-" + "missing-evidence"
        (self.ws / "claims.yaml").write_text(
            json.dumps({
                "schema": "rigorloom-claims/v1",
                "claims": [{
                    "id": "unsupported-qualitative-claim",
                    "text": "Synthetic unsupported claim.",
                    "kind": "qualitative",
                    "evidence": [{
                        "source_id": missing_id,
                        "locator": "section 1",
                        "quote": "Synthetic quote.",
                    }],
                }],
            }),
            encoding="utf-8",
        )

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["sub_exit"]["check_claims"], 3)
        self.assertTrue(any(
            item.get("source") == "check_claims"
            and item.get("code") == "claim_source_missing"
            for item in verdict["hard"]
        ), verdict)

    def test_figdata_checker_is_fifth_composed_gate(self):
        self.write_content(self._clean_body())
        (self.ws / "bundle" / "figures" / "plot.png").write_bytes(b"changed")

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["sub_exit"]["check_figdata"], 3)
        self.assertTrue(any(
            item.get("source") == "check_figdata"
            and item.get("code") == "figure_data_drift"
            for item in verdict["hard"]
        ), verdict)

    def test_number_checker_is_third_composed_gate(self):
        self.write_content("# Result\nThe measured level was 7.654 dB.\n")
        self.write_results({"seed": 21, "level_db": 1.234})

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(
            item.get("source") == "check_numbers"
            and item.get("code") == "unbacked_numeral"
            for item in verdict["warn"]
        ))

    def test_truthy_require_ledger_environment_makes_unledgered_claim_hard(self):
        self.write_content("# Result\nThe measured level was 7.654 dB.\n")
        self.write_results({"seed": 21, "level_db": 1.234})
        (self.ws / "claims.yaml").write_text(
            json.dumps({"schema": "rigorloom-claims/v1", "claims": []}),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ, {"RIGORLOOM_REQUIRE_LEDGER": "yes"}, clear=False,
        ):
            verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item.get("source") == "check_claims"
            and item.get("code") == "claim_unledgered"
            for item in verdict["hard"]
        ), verdict)

    def test_ref_checker_is_fourth_composed_gate(self):
        self.write_content(
            "# Results\n표 2에서 합계를 확인한다.\n"
            '[[TABLE cols=50,50 caption="표 1. Synthetic table"]]\n'
            "| A | B |\n[[/TABLE]]\n"
        )
        verdict, code = content_audit.check(str(self.ws))
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["sub_exit"]["check_refs"], 0)
        self.assertTrue(any(
            item.get("source") == "check_refs"
            and item.get("code") == "dangling_xref"
            for item in verdict["warn"]
        ), verdict)

    def test_profile_number_allowlist_is_forwarded(self):
        self.write_content("# Method\nIn 2024, 12 trials used 3.25 ms each.\n")
        self.write_results({"seed": 21, "duration_ms": 3.25})
        root = self.make_profile_root_with_number_allowlist()

        verdict, code = content_audit.check(str(self.ws), profile_root=str(root))

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            h.get("source") == "check_numbers" for h in verdict["hard"]
        ))

    def test_valid_operator_pack_passes_schema_validation(self):
        self.write_content(self._clean_body())
        root = self.make_profile_root_with_structure()

        verdict, code = content_audit.check(
            str(self.ws), profile_root=str(root))

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])

    def test_neutral_defaults_pass_without_profile_validation(self):
        self.write_content(self._clean_body())

        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("RIGORLOOM_PROFILE_ROOT", None)
            verdict, code = content_audit.check(str(self.ws), profile_root=None)

        self.assertEqual(code, 0, verdict)
        self.assertTrue(verdict["ok"])

    def test_environment_profile_is_validated_and_forwarded(self):
        self.write_content(
            "# Method\nIn 2024, 12 trials used 3.25 ms each.\n"
            "선행 연구(김철수, 2020)는 이 현상을 다루었다.\n"
        )
        self.write_results({"seed": 21, "duration_ms": 3.25})
        root = self.make_profile_root_with_structure()
        (root / "packs" / "numeral_allowlist.txt").write_text(
            "12\n", encoding="utf-8"
        )

        with mock.patch.dict(
            os.environ, {"RIGORLOOM_PROFILE_ROOT": str(root)}, clear=False
        ):
            verdict, code = content_audit.check(str(self.ws), profile_root=None)

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item.get("source") == "check_style" and item.get("code") == "CITE"
            for item in verdict["hard"]
        ), verdict)
        self.assertFalse(any(
            item.get("source") == "check_numbers"
            and item.get("code") == "unbacked_numeral"
            for item in verdict["hard"] + verdict["warn"]
        ), verdict)

    def test_explicit_profile_precedes_environment_profile(self):
        self.write_content("# Method\nIn 2024, 12 trials used 3.25 ms each.\n")
        self.write_results({"seed": 21, "duration_ms": 3.25})
        environment_root = self.make_profile_root_with_structure()
        explicit_root = self.make_profile_root_with_number_allowlist()

        with mock.patch.dict(
            os.environ,
            {"RIGORLOOM_PROFILE_ROOT": str(environment_root)},
            clear=False,
        ):
            verdict, code = content_audit.check(
                str(self.ws), profile_root=str(explicit_root)
            )

        self.assertEqual(code, 0, verdict)


class TestSaeteukAdvisory(ContentAuditTestCase):
    def test_stage_45_demotes_saeteuk_hard_finding_to_warn(self):
        self.write_content("Sample A latency = 20 ms.\n")
        target = self.ws / "_saeteuk"
        target.mkdir()
        (target / "record.txt").write_text(
            "Sample A latency = 10 ms.\n", encoding="utf-8"
        )

        verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["sub_exit"]["check_saeteuk"], 3)
        self.assertFalse(any(
            item.get("source") == "check_saeteuk"
            for item in verdict["hard"]
        ), verdict)
        self.assertTrue(any(
            item.get("source") == "check_saeteuk"
            and item.get("code") == "saeteuk_number_contradiction"
            and item.get("severity") == "WARN"
            for item in verdict["warn"]
        ), verdict)

    def test_stage_45_saeteuk_crash_warns_instead_of_blocking(self):
        self.write_content("Sample A latency = 20 ms.\n")

        def boom(ws, **kwargs):
            raise RuntimeError("synthetic saeteuk mirror crash")

        with mock.patch.object(content_audit.check_saeteuk, "check", boom):
            verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(
            item.get("source") == "check_saeteuk"
            for item in verdict["hard"]
        ), verdict)
        self.assertTrue(any(
            item.get("source") == "check_saeteuk"
            and item.get("severity") == "WARN"
            and "synthetic saeteuk mirror crash" in str(item.get("msg", ""))
            for item in verdict["warn"]
        ), verdict)


class TestPackSchema(ContentAuditTestCase):
    def test_report_structure_accepts_optional_title_metadata_keys(self):
        root = self.make_profile_root_with_structure()
        pack_path = root / "packs" / "report_structure.json"
        payload = json.loads(pack_path.read_text(encoding="utf-8"))
        payload["title_metadata_keys"] = ["활동주제"]
        pack_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        findings = content_audit._validate_operator_packs(pack_path.parent)

        self.assertEqual(findings, [])

    def test_invalid_operator_pack_fails_closed_before_forwarding(self):
        self.write_content(self._clean_body())
        root = self.make_profile_root_with_structure()
        pack_path = root / "packs" / "report_structure.json"
        payload = json.loads(pack_path.read_text(encoding="utf-8"))
        payload["citations"] = payload.pop("citation_style")
        pack_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        verdict, code = content_audit.check(
            str(self.ws), profile_root=str(root))

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "pack_schema_invalid"
            for item in verdict["hard"]
        ), verdict)

    def test_environment_figure_pack_is_schema_validated(self):
        self.write_content(self._clean_body())
        root = Path(self._tmp.name) / "profile-figures"
        packs = root / "packs"
        packs.mkdir(parents=True)
        (packs / "figure_style.json").write_text(
            json.dumps({
                "schema": "x",
                "pack_type": "figure_style",
                "name": "incomplete",
                "version": 1,
            }),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ, {"RIGORLOOM_PROFILE_ROOT": str(root)}, clear=False
        ):
            verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(
            item["code"] == "pack_schema_invalid"
            and "figure_style" in item["msg"]
            for item in verdict["hard"]
        ), verdict)


class TestPoliteEnding(ContentAuditTestCase):
    def test_polite_ending_fails_via_verify_content(self):
        self.write_content(
            "# 서론\n실험을 진행하였고 결과를 확인하였습니다.\n"
            '[[FIG file="plot.png"]]\n'
        )
        verdict, code = content_audit.check(str(self.ws))
        self.assertEqual(code, 3)
        self.assertTrue(any(h.get("source") == "verify_content" and h.get("code") == "H2"
                            for h in verdict["hard"]))


class TestCitation(ContentAuditTestCase):
    def test_parenthetical_citation_fails_via_check_style(self):
        self.write_content(
            "# 서론\n선행 연구(김철수, 2020)는 이 현상을 다루었다.\n"
            '[[FIG file="plot.png"]]\n'
        )
        root = self.make_profile_root_with_structure()
        verdict, code = content_audit.check(str(self.ws), profile_root=str(root))
        self.assertEqual(code, 3)
        self.assertTrue(any(h.get("source") == "check_style" and h.get("code") == "CITE"
                            for h in verdict["hard"]))


class TestUsage(ContentAuditTestCase):
    def test_missing_content_md_is_nonzero(self):
        # no bundle/content.md -> the content-dependent sub-checkers are nonzero.
        verdict, code = content_audit.check(str(self.ws))
        self.assertNotEqual(code, 0)
        self.assertFalse(verdict["ok"])

    def test_worst_exit_prefers_hard_over_usage(self):
        self.write_content(self._clean_body())
        passed = {
            "ok": True, "verdict": "pass", "hard": [], "warn": [],
        }
        usage = {
            "ok": False, "error": "synthetic usage error",
            "verdict": "usage_error", "hard": [], "warn": [],
        }
        hard = {
            "ok": False, "verdict": "fail",
            "hard": [{"code": "figure_data_drift", "msg": "synthetic drift"}],
            "warn": [],
        }

        with (
            mock.patch.object(
                content_audit.verify_content, "check",
                return_value=(usage, 2),
            ),
            mock.patch.object(
                content_audit.check_style, "check",
                return_value=(passed, 0),
            ),
            mock.patch.object(
                content_audit.check_numbers, "check",
                return_value=(passed, 0),
            ),
            mock.patch.object(
                content_audit.check_refs, "check",
                return_value=(passed, 0),
            ),
            mock.patch.object(
                content_audit.check_figdata, "check",
                return_value=(hard, 3),
            ),
            mock.patch.object(
                content_audit.check_sources, "check",
                return_value=(passed, 0),
            ),
            mock.patch.object(
                content_audit.check_units, "check",
                return_value=(passed, 0),
            ),
            mock.patch.object(
                content_audit.check_saeteuk, "check",
                return_value=(passed, 0),
            ),
        ):
            verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["sub_exit"]["verify_content"], 2)
        self.assertEqual(verdict["sub_exit"]["check_figdata"], 3)
        self.assertEqual(verdict["verdict"], "fail")

    def test_in_process_exception_is_hard_with_truncated_traceback(self):
        self.write_content(self._clean_body())

        with mock.patch.object(
            content_audit.verify_content,
            "check",
            side_effect=RuntimeError("checker exploded"),
        ):
            verdict, code = content_audit.check(str(self.ws))

        self.assertEqual(code, 3, verdict)
        self.assertEqual(verdict["sub_exit"]["verify_content"], 3)
        finding = next(
            item for item in verdict["hard"]
            if item.get("source") == "verify_content"
            and item.get("code") == "USAGE"
        )
        self.assertIn("checker exploded", finding["msg"])
        self.assertIn("RuntimeError", finding["traceback"])
        self.assertLessEqual(len(finding["traceback"]), 1600)

    def test_malformed_sixth_checker_return_normalizes_its_exit_to_hard(self):
        self.write_content(self._clean_body())
        hostile_returns = (
            None,
            ([], 0),
            ({
                "ok": False, "verdict": "fail", "hard": [], "warn": [],
            }, 0),
            ({
                "ok": True, "verdict": "pass",
                "hard": [{"code": "synthetic"}], "warn": [],
            }, 0),
        )

        for return_value in hostile_returns:
            with self.subTest(return_value=return_value):
                with mock.patch.object(
                    content_audit.check_sources,
                    "check",
                    return_value=return_value,
                ):
                    verdict, code = content_audit.check(str(self.ws))

                self.assertEqual(code, 3, verdict)
                self.assertEqual(verdict["sub_exit"]["check_sources"], 3)
                self.assertEqual(verdict["sub_exit"]["check_units"], 0)
                self.assertTrue(any(
                    item.get("source") == "check_sources"
                    and item.get("code") == "USAGE"
                    for item in verdict["hard"]
                ), verdict)



if __name__ == "__main__":
    unittest.main()
