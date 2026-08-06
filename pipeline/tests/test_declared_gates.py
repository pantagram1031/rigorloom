# -*- coding: utf-8 -*-
"""Tests for the declared-values gate runner.

Covers the ported reportkit semantics (kinds, dotted paths, missing input
= fail not crash, gate_result.json) plus the audit-mandated hardening:
canonical binding with loud target_missing, staleness records
(mtime+sha256), holdout enforcement (workspace_slug header), and registry
mechanism delegation (residue/density/canonical)."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "declared_gates.py"
_spec = importlib.util.spec_from_file_location("declared_gates", SCRIPT)
declared_gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(declared_gates)

SLUG = "report-synthetic"
HEADER = f"workspace_slug: {SLUG}\n"


def _canonical_delegate_available() -> bool:
    """True when an enabled distribution module registers the 'canonical'
    gate kind (v0.16 W3-S3: gate_kinds declaration in module.yaml; core-only
    runs must refuse canonical gates loudly instead of running them)."""
    try:
        registry = declared_gates.module_registry.ModuleRegistry()
        return any(row["kind"] == "canonical"
                   for row in registry.enabled_gate_kinds())
    except Exception:
        return False


CANONICAL_AVAILABLE = _canonical_delegate_available()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / SLUG
        self.ws.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_gates(self, body: str, header: str = HEADER) -> None:
        (self.ws / "gates.yaml").write_text(header + body, encoding="utf-8")

    def write_json(self, rel: str, payload) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def write_text(self, rel: str, text: str) -> Path:
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_all(self):
        return declared_gates.run_all(self.ws)

    def run_cli(self):
        """Invoke main() the way the CLI does; returns (exit_code, stdout)."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = declared_gates.main([str(self.ws)])
        return code, buffer.getvalue()

    def gate(self, result, gid):
        rows = [row for row in result["gates"] if row["id"] == gid]
        self.assertEqual(len(rows), 1, result)
        return rows[0]


# ── ported reportkit semantics ──────────────────────────────────────


class BuiltinKindTests(Base):
    def test_json_equals_pass_and_fail(self):
        self.write_json("sim/metrics.json", {"seed": 42, "ok": True})
        self.write_gates(
            "gates:\n"
            "  - id: seed_pinned\n"
            "    kind: json_equals\n"
            "    file: sim/metrics.json\n"
            "    path: seed\n"
            "    expect: 42\n"
            "  - id: wrong_value\n"
            "    kind: json_equals\n"
            "    file: sim/metrics.json\n"
            "    path: seed\n"
            "    expect: 7\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        self.assertFalse(result["all_pass"])
        self.assertTrue(self.gate(result, "seed_pinned")["pass"])
        row = self.gate(result, "wrong_value")
        self.assertFalse(row["pass"])
        self.assertEqual(row["got"], 42)
        self.assertEqual(row["expect"], 7)
        self.assertIn("comparison_failed", row["findings"])

    def test_json_lt_gt_and_type_mismatch_fails_not_crashes(self):
        self.write_json("sim/metrics.json",
                        {"rmse": {"value": 0.4}, "n": 100, "name": "x"})
        self.write_gates(
            "gates:\n"
            "  - id: rmse_bounded\n"
            "    kind: json_lt\n"
            "    file: sim/metrics.json\n"
            "    path: rmse.value\n"
            "    expect: 0.5\n"
            "  - id: enough_samples\n"
            "    kind: json_gt\n"
            "    file: sim/metrics.json\n"
            "    path: n\n"
            "    expect: 30\n"
            "  - id: type_mismatch\n"
            "    kind: json_lt\n"
            "    file: sim/metrics.json\n"
            "    path: name\n"
            "    expect: 5\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        self.assertTrue(self.gate(result, "rmse_bounded")["pass"])
        self.assertTrue(self.gate(result, "enough_samples")["pass"])
        self.assertFalse(self.gate(result, "type_mismatch")["pass"])

    def test_dotted_path_list_indexes(self):
        self.write_json("sim/runs.json",
                        {"runs": [{"rmse": 0.9}, {"rmse": 0.2}]})
        self.write_gates(
            "gates:\n"
            "  - id: second_run\n"
            "    kind: json_equals\n"
            "    file: sim/runs.json\n"
            "    path: runs.1.rmse\n"
            "    expect: 0.2\n"
            "  - id: last_run_negative_index\n"
            "    kind: json_equals\n"
            "    file: sim/runs.json\n"
            "    path: runs.-1.rmse\n"
            "    expect: 0.2\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        self.assertTrue(result["all_pass"])

    def test_json_path_missing_fails(self):
        self.write_json("sim/metrics.json", {"a": 1})
        self.write_gates(
            "gates:\n"
            "  - id: no_such_path\n"
            "    kind: json_equals\n"
            "    file: sim/metrics.json\n"
            "    path: b.c\n"
            "    expect: 1\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        row = self.gate(result, "no_such_path")
        self.assertIn("json_path_missing", row["findings"])
        self.assertIsNone(row["got"])

    def test_malformed_json_fails_not_crashes(self):
        self.write_text("sim/metrics.json", "{not json")
        self.write_gates(
            "gates:\n"
            "  - id: broken\n"
            "    kind: json_equals\n"
            "    file: sim/metrics.json\n"
            "    path: a\n"
            "    expect: 1\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        self.assertIn("target_unreadable",
                      self.gate(result, "broken")["findings"])

    def test_file_exists_pass(self):
        self.write_text("output/out.hwpx", "zip-ish bytes")
        self.write_gates(
            "gates:\n"
            "  - id: assembled\n"
            "    kind: file_exists\n"
            "    file: output/out.hwpx\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        self.assertTrue(result["all_pass"])

    def test_text_absent_pass_and_hit(self):
        # quoted numeric forbidden string must stay a string (windpath
        # "10101" student-id case)
        self.write_text("output/pdf_text.txt",
                        "본문 서술. 학번 10101 김선덕 예시가 남아 있다.")
        self.write_gates(
            "gates:\n"
            "  - id: forbidden_absent\n"
            "    kind: text_absent\n"
            "    file: output/pdf_text.txt\n"
            "    expect:\n"
            "      - \"10101\"\n"
            "      - \"김선덕\"\n"
            "      - \"chatgpt\"\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        row = self.gate(result, "forbidden_absent")
        self.assertEqual(row["got"], ["10101", "김선덕"])
        self.assertIn("forbidden_text_present", row["findings"])

        self.write_text("output/pdf_text.txt", "깨끗한 본문.")
        result, code = self.run_all()
        self.assertEqual(code, 0, result)

    def test_empty_gate_list_is_never_a_pass(self):
        self.write_gates("gates: []\n")
        result, code = self.run_all()
        self.assertEqual(code, 3)
        self.assertFalse(result["all_pass"])
        self.assertEqual(result["gates"], [])


# ── canonical binding: loud missing-target failure ──────────────────


class MissingTargetTests(Base):
    def test_vanished_pinned_target_is_hard_and_recorded(self):
        """The failing-before case: windpath's gate_result recorded
        file_exists=true for a file that had vanished. After the target
        vanishes, a re-run must record the miss loudly."""
        target = self.write_text("output/v5/out.hwpx", "artifact bytes")
        self.write_gates(
            "gates:\n"
            "  - id: assembled\n"
            "    kind: file_exists\n"
            "    file: output/v5/out.hwpx\n"
        )
        code, _ = self.run_cli()
        self.assertEqual(code, 0)
        first = json.loads(
            (self.ws / "gate_result.json").read_text(encoding="utf-8"))
        self.assertTrue(first["all_pass"])

        target.unlink()  # the artifact rots away
        code, _ = self.run_cli()
        self.assertEqual(code, 3)
        second = json.loads(
            (self.ws / "gate_result.json").read_text(encoding="utf-8"))
        self.assertFalse(second["all_pass"])
        row = second["gates"][0]
        self.assertFalse(row["pass"])
        self.assertIn("target_missing", row["findings"])
        self.assertFalse(row["targets"][0]["exists"])
        self.assertIsNone(row["targets"][0]["sha256"])

    def test_missing_json_target_is_target_missing(self):
        self.write_gates(
            "gates:\n"
            "  - id: metrics_gate\n"
            "    kind: json_lt\n"
            "    file: sim/never_written.json\n"
            "    path: rmse\n"
            "    expect: 0.5\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        row = self.gate(result, "metrics_gate")
        self.assertEqual(row["findings"], ["target_missing"])
        self.assertEqual(row["got"], {"missing": ["sim/never_written.json"]})

    def test_missing_text_target_is_target_missing(self):
        self.write_gates(
            "gates:\n"
            "  - id: absent_gate\n"
            "    kind: text_absent\n"
            "    file: output/pdf_text.txt\n"
            "    expect:\n"
            "      - \"금지어\"\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        self.assertIn("target_missing",
                      self.gate(result, "absent_gate")["findings"])


# ── result staleness records ────────────────────────────────────────


class StalenessTests(Base):
    def test_targets_record_mtime_and_sha256(self):
        content = "본문 텍스트 v1"
        target = self.write_text("output/pdf_text.txt", content)
        self.write_gates(
            "gates:\n"
            "  - id: clean\n"
            "    kind: text_absent\n"
            "    file: output/pdf_text.txt\n"
            "    expect:\n"
            "      - \"금지어\"\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        meta = self.gate(result, "clean")["targets"][0]
        self.assertEqual(meta["path"], "output/pdf_text.txt")
        self.assertTrue(meta["exists"])
        expected_sha = hashlib.sha256(
            content.encode("utf-8")).hexdigest()
        self.assertEqual(meta["sha256"], expected_sha)
        self.assertAlmostEqual(meta["mtime"], target.stat().st_mtime,
                               places=3)

    def test_rewritten_target_changes_recorded_hash(self):
        self.write_text("output/pdf_text.txt", "버전 1")
        self.write_gates(
            "gates:\n"
            "  - id: clean\n"
            "    kind: text_absent\n"
            "    file: output/pdf_text.txt\n"
            "    expect:\n"
            "      - \"금지어\"\n"
        )
        first, _ = self.run_all()
        self.write_text("output/pdf_text.txt", "버전 2 — 내용이 바뀌었다")
        second, _ = self.run_all()
        sha1 = self.gate(first, "clean")["targets"][0]["sha256"]
        sha2 = self.gate(second, "clean")["targets"][0]["sha256"]
        self.assertNotEqual(sha1, sha2)


# ── holdout enforcement ─────────────────────────────────────────────


class HoldoutTests(Base):
    BODY = (
        "gates:\n"
        "  - id: assembled\n"
        "    kind: file_exists\n"
        "    file: output/out.hwpx\n"
    )

    def test_slug_mismatch_refuses_to_run(self):
        """A gates.yaml copied wholesale from another report must fail
        loudly, citing the holdout rule — and must not write results."""
        self.write_text("output/out.hwpx", "bytes")
        self.write_gates(self.BODY,
                         header="workspace_slug: report-other-report\n")
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("holdout", str(ctx.exception))
        self.assertIn("report-other-report", str(ctx.exception))

        code, stdout = self.run_cli()
        self.assertEqual(code, 2)
        self.assertFalse((self.ws / "gate_result.json").exists(),
                         "a refusal must never write gate_result.json")
        self.assertIn("usage_error", stdout)

    def test_matching_slug_runs(self):
        self.write_text("output/out.hwpx", "bytes")
        self.write_gates(self.BODY)
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["workspace_slug"], SLUG)

    def test_missing_slug_header_refused(self):
        self.write_gates(self.BODY, header="")
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("workspace_slug", str(ctx.exception))

    def test_legacy_bare_list_format_refused(self):
        (self.ws / "gates.yaml").write_text(
            "- id: assembled\n"
            "  kind: file_exists\n"
            "  file: output/out.hwpx\n",
            encoding="utf-8")
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("header block", str(ctx.exception))

    def test_missing_gates_yaml_is_usage(self):
        with self.assertRaises(declared_gates.GatesConfigError):
            self.run_all()
        code, _ = self.run_cli()
        self.assertEqual(code, 2)


# ── declaration validation ──────────────────────────────────────────


class DeclarationValidationTests(Base):
    def test_absolute_path_rejected(self):
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        self.write_gates(
            "gates:\n"
            "  - id: abs_path\n"
            "    kind: file_exists\n"
            f"    file: \"{outside.as_posix()}\"\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("workspace-relative", str(ctx.exception))

    def test_escaping_path_rejected(self):
        self.write_gates(
            "gates:\n"
            "  - id: escape\n"
            "    kind: file_exists\n"
            "    file: ../other-report/out.hwpx\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("escapes the workspace", str(ctx.exception))

    def test_duplicate_gate_id_rejected(self):
        self.write_gates(
            "gates:\n"
            "  - id: twin\n"
            "    kind: file_exists\n"
            "    file: a.txt\n"
            "  - id: twin\n"
            "    kind: file_exists\n"
            "    file: b.txt\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("duplicate gate id", str(ctx.exception))

    def test_unknown_kind_rejected(self):
        self.write_gates(
            "gates:\n"
            "  - id: typo\n"
            "    kind: json_equal\n"
            "    file: sim/m.json\n"
            "    path: a\n"
            "    expect: 1\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("unknown kind", str(ctx.exception))

    def test_unexpected_key_rejected(self):
        self.write_gates(
            "gates:\n"
            "  - id: extra\n"
            "    kind: file_exists\n"
            "    file: a.txt\n"
            "    expect: true\n"  # file_exists takes no expect
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("unexpected keys", str(ctx.exception))

    def test_text_absent_requires_nonempty_expect(self):
        self.write_gates(
            "gates:\n"
            "  - id: hollow\n"
            "    kind: text_absent\n"
            "    file: a.txt\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError):
            self.run_all()

    def test_nonnumeric_threshold_rejected(self):
        self.write_gates(
            "gates:\n"
            "  - id: dens\n"
            "    kind: density\n"
            "    hard_per_10k: loose\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError):
            self.run_all()


# ── constrained YAML subset parser ──────────────────────────────────


class ParserTests(unittest.TestCase):
    def parse(self, text):
        return declared_gates.parse_gates_yaml(text)

    def test_scalar_coercion(self):
        config = self.parse(
            "workspace_slug: report-x\n"
            "gates:\n"
            "  - id: g\n"
            "    kind: json_equals\n"
            "    file: m.json\n"
            "    path: a\n"
            "    expect: 0.5\n"
        )
        self.assertEqual(config["gates"][0]["expect"], 0.5)

    def test_quoted_number_stays_string(self):
        config = self.parse(
            "workspace_slug: report-x\n"
            "gates:\n"
            "  - id: g\n"
            "    kind: text_absent\n"
            "    file: t.txt\n"
            "    expect:\n"
            "      - \"10101\"\n"
        )
        self.assertEqual(config["gates"][0]["expect"], ["10101"])

    def test_inline_list(self):
        config = self.parse(
            "workspace_slug: report-x\n"
            "gates:\n"
            "  - id: g\n"
            "    kind: text_absent\n"
            "    file: t.txt\n"
            "    expect: [\"a\", \"b, c\"]\n"
        )
        self.assertEqual(config["gates"][0]["expect"], ["a", "b, c"])

    def test_comments_stripped_but_not_inside_quotes(self):
        config = self.parse(
            "# full-line comment\n"
            "workspace_slug: report-x  # trailing comment\n"
            "gates:\n"
            "  - id: g  # another\n"
            "    kind: text_absent\n"
            "    file: t.txt\n"
            "    expect:\n"
            "      - \"has # hash inside\"\n"
        )
        self.assertEqual(config["workspace_slug"], "report-x")
        self.assertEqual(config["gates"][0]["id"], "g")
        self.assertEqual(config["gates"][0]["expect"],
                         ["has # hash inside"])

    def test_form_hash_header_parsed(self):
        config = self.parse(
            "workspace_slug: report-x\n"
            "form_hash: abc123\n"
            "gates: []\n"
        )
        self.assertEqual(config["form_hash"], "abc123")

    def test_unknown_top_level_key_rejected(self):
        with self.assertRaises(declared_gates.GatesConfigError):
            self.parse("workspace_slug: report-x\nslugg: oops\ngates: []\n")

    def test_missing_gates_key_rejected(self):
        with self.assertRaises(declared_gates.GatesConfigError):
            self.parse("workspace_slug: report-x\n")

    def test_same_indent_list_items_under_key(self):
        # YAML allows sequence items at the same indent as the mapping key
        config = self.parse(
            "workspace_slug: report-x\n"
            "gates:\n"
            "- id: g\n"
            "  kind: text_absent\n"
            "  file: t.txt\n"
            "  expect:\n"
            "  - \"a\"\n"
            "- id: h\n"
            "  kind: file_exists\n"
            "  file: u.txt\n"
        )
        self.assertEqual(config["gates"][0]["expect"], ["a"])
        self.assertEqual(config["gates"][1]["id"], "h")


# ── mechanism delegation (registry checkers, declared values) ───────


def dense_content(subheads: int, pad_bytes: int) -> str:
    lines = ["## SECTION: I.  서론", ""]
    for index in range(subheads):
        lines.append(f"**소제목 {index + 1}**")
        lines.append("")
    text = "\n".join(lines) + "\n"
    text += ("x" * 79 + "\n") * (pad_bytes // 80)
    return text


class DelegationTests(Base):
    def test_density_delegation_hard(self):
        self.write_text("bundle/content.md", dense_content(18, 1600))
        self.write_gates(
            "gates:\n"
            "  - id: subhead_density\n"
            "    kind: density\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "subhead_density")
        self.assertFalse(row["pass"])
        self.assertIn("subhead_density_hard", row["findings"])
        self.assertEqual(row["verdict"]["checker"], "check_density")

    def test_density_delegation_pass_with_declared_thresholds(self):
        self.write_text("bundle/content.md", dense_content(2, 40000))
        self.write_gates(
            "gates:\n"
            "  - id: subhead_density\n"
            "    kind: density\n"
            "    warn_per_10k: 3.0\n"
            "    hard_per_10k: 4.5\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        row = self.gate(result, "subhead_density")
        self.assertTrue(row["pass"])
        self.assertEqual(row["targets"][0]["path"], "bundle/content.md")
        self.assertTrue(row["targets"][0]["sha256"])

    def test_density_default_content_missing_is_target_missing(self):
        self.write_gates(
            "gates:\n"
            "  - id: subhead_density\n"
            "    kind: density\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3)
        row = self.gate(result, "subhead_density")
        self.assertEqual(row["findings"], ["target_missing"])
        self.assertNotIn("verdict", row, "no delegation on a missing pin")

    RESIDUE_GATES = (
        "gates:\n"
        "  - id: residue_clean\n"
        "    kind: residue\n"
        "    form_profile: refs/form_profile.json\n"
        "    artifact: output/final.txt\n"
    )

    def residue_profile(self, form_hash="hash-a"):
        self.write_json("refs/form_profile.json", {
            "form_hash": form_hash,
            "anchors": ["I.  서론"],
            "guide_text": ["여기에 탐구 동기를 서술하시오"],
        })

    def test_residue_delegation_catches_guide_text(self):
        self.residue_profile()
        self.write_text("output/final.txt",
                        "I.  서론 여기에 탐구 동기를 서술하시오")
        self.write_gates(self.RESIDUE_GATES)
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "residue_clean")
        self.assertIn("form_residue", row["findings"])
        self.assertEqual(row["verdict"]["checker"], "check_residue")

    def test_residue_delegation_clean_passes(self):
        self.residue_profile()
        self.write_text("output/final.txt",
                        "I.  서론 실제로 작성한 탐구 동기 본문이다.")
        self.write_gates(self.RESIDUE_GATES)
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        row = self.gate(result, "residue_clean")
        self.assertTrue(row["pass"])
        # both pinned files carry staleness records
        self.assertEqual(
            sorted(t["path"] for t in row["targets"]),
            ["output/final.txt", "refs/form_profile.json"])
        self.assertTrue(all(t["sha256"] for t in row["targets"]))

    def test_residue_vanished_artifact_short_circuits(self):
        self.residue_profile()
        self.write_gates(self.RESIDUE_GATES)
        result, code = self.run_all()
        self.assertEqual(code, 3)
        row = self.gate(result, "residue_clean")
        self.assertEqual(row["findings"], ["target_missing"])
        self.assertNotIn("verdict", row)

    def test_form_hash_mismatch_fails_residue_gate(self):
        """Holdout form binding: values declared for one form family must
        not silently run against another form's profile."""
        self.residue_profile(form_hash="hash-b")
        self.write_text("output/final.txt", "깨끗한 본문.")
        self.write_gates(self.RESIDUE_GATES,
                         header=HEADER + "form_hash: hash-a\n")
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "residue_clean")
        self.assertIn("form_hash_mismatch", row["findings"])

    def test_form_hash_match_passes(self):
        self.residue_profile(form_hash="hash-a")
        self.write_text("output/final.txt", "깨끗한 본문.")
        self.write_gates(self.RESIDUE_GATES,
                         header=HEADER + "form_hash: hash-a\n")
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["form_hash"], "hash-a")

    def canonical_workspace(self, pointer="output/final.hwpx"):
        self.write_json(".pipeline/handoff.json", {
            "canonical_output": pointer,
            "completed_stage": "6",
            "next_stage": None,
        })

    def test_canonical_without_providing_module_is_loud_refusal(self):
        """Core-only: a workspace declaring a canonical gate while no enabled
        module registers that kind must be a config refusal (exit 2 path) —
        an unknown kind with no provider, never a silent pass or a crash."""
        if CANONICAL_AVAILABLE:
            self.skipTest("a module registering gate kind 'canonical' is enabled")
        self.canonical_workspace()
        self.write_text("output/final.hwpx", "ship artifact")
        self.write_gates(
            "gates:\n"
            "  - id: final_pointer\n"
            "    kind: canonical\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError):
            self.run_all()
        code, stdout = self.run_cli()
        self.assertEqual(code, declared_gates.EXIT_USAGE)
        self.assertIn("unknown kind", stdout)
        self.assertIn("gate_kinds", stdout)
        # a refusal must never look like a run
        self.assertFalse((self.ws / "gate_result.json").exists())

    @unittest.skipUnless(
        CANONICAL_AVAILABLE,
        "no enabled distribution module provides check_canonical")
    def test_canonical_delegation_pass(self):
        self.canonical_workspace()
        self.write_text("output/final.hwpx", "ship artifact")
        self.write_gates(
            "gates:\n"
            "  - id: final_pointer\n"
            "    kind: canonical\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        row = self.gate(result, "final_pointer")
        self.assertTrue(row["pass"])
        self.assertEqual(row["verdict"]["checker"], "check_canonical")
        # the resolved pointer gets a staleness record too
        self.assertEqual(row["targets"][0]["path"], "output/final.hwpx")
        self.assertTrue(row["targets"][0]["sha256"])

    @unittest.skipUnless(
        CANONICAL_AVAILABLE,
        "no enabled distribution module provides check_canonical")
    def test_canonical_target_missing_fails(self):
        self.canonical_workspace(pointer="output/vanished.hwpx")
        self.write_gates(
            "gates:\n"
            "  - id: final_pointer\n"
            "    kind: canonical\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "final_pointer")
        self.assertIn("canonical_target_missing", row["findings"])
        self.assertFalse(row["targets"][0]["exists"])

    def test_delegate_usage_error_never_passes(self):
        # density with an empty content file: check_density usage-errors —
        # the gate must fail, not skip
        self.write_text("bundle/content.md", "")
        self.write_gates(
            "gates:\n"
            "  - id: subhead_density\n"
            "    kind: density\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "subhead_density")
        self.assertFalse(row["pass"])
        self.assertIn("delegate_usage_error", row["findings"])


# ── registry-registered gate kinds (v0.16 W3-S3 gate_kinds) ─────────

_CUSTOM_CHECKER = '''\
def check(ws, threshold=1):
    """Synthetic gate-kind delegate honouring the in-process contract."""
    hard = [] if threshold <= 1 else [{"code": "threshold_exceeded"}]
    verdict = {"checker": "check_custom", "verdict": "pass" if not hard else "fail",
               "hard": hard, "target": "output/final.txt"}
    return verdict, 0 if not hard else 3
'''

_CUSTOM_MANIFEST = """\
schema: rigorloom-module/v1
name: gatekit
requires: { rigorloom: ">=0.1" }
provides:
  checkers:
    - { name: check_custom, script: scripts/check_custom.py }
  gate_kinds:
    - { kind: custom, checker: check_custom }
"""


class RegistryGateKindTests(Base):
    """The kind vocabulary itself is registry-driven: a throwaway module's
    gate_kinds declaration lights a new kind up in declared_gates with no
    core change, and its declared params are signature-validated."""

    def setUp(self):
        super().setUp()
        modules_root = Path(self._tmp.name) / "modules"
        module = modules_root / "gatekit"
        (module / "scripts").mkdir(parents=True)
        (module / "scripts" / "check_custom.py").write_text(
            _CUSTOM_CHECKER, encoding="utf-8")
        (module / "module.yaml").write_text(_CUSTOM_MANIFEST, encoding="utf-8")
        (modules_root / "enabled.yaml").write_text(
            "schema: rigorloom-enabled-modules/v1\nenabled: [gatekit]\n",
            encoding="utf-8")
        real_registry = declared_gates.module_registry.ModuleRegistry
        self._registry_patch = mock.patch.object(
            declared_gates.module_registry, "ModuleRegistry",
            lambda *args, **kwargs: real_registry(
                modules_root, version="0.16.0"))
        self._registry_patch.start()
        declared_gates._MODULE_DELEGATE_CACHE.clear()

    def tearDown(self):
        self._registry_patch.stop()
        declared_gates._MODULE_DELEGATE_CACHE.clear()
        super().tearDown()

    def test_module_registered_kind_runs_with_declared_params(self):
        self.write_text("output/final.txt", "artifact")
        self.write_gates(
            "gates:\n"
            "  - id: custom_gate\n"
            "    kind: custom\n"
            "    threshold: 1\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 0, result)
        row = self.gate(result, "custom_gate")
        self.assertTrue(row["pass"])
        self.assertEqual(row["expect"], "pass")
        self.assertEqual(row["verdict"]["checker"], "check_custom")
        # the delegate-reported target gets a staleness record
        self.assertEqual(row["targets"][0]["path"], "output/final.txt")
        self.assertTrue(row["targets"][0]["sha256"])

    def test_module_registered_kind_failure_is_recorded(self):
        self.write_text("output/final.txt", "artifact")
        self.write_gates(
            "gates:\n"
            "  - id: custom_gate\n"
            "    kind: custom\n"
            "    threshold: 5\n"
        )
        result, code = self.run_all()
        self.assertEqual(code, 3, result)
        row = self.gate(result, "custom_gate")
        self.assertFalse(row["pass"])
        self.assertIn("threshold_exceeded", row["findings"])

    def test_param_typo_is_validation_refusal_not_midrun_crash(self):
        self.write_gates(
            "gates:\n"
            "  - id: custom_gate\n"
            "    kind: custom\n"
            "    thresold: 5\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("unexpected keys", str(ctx.exception))
        self.assertIn("check_custom", str(ctx.exception))

    def test_module_kind_may_not_shadow_core_kind(self):
        modules_root = Path(self._tmp.name) / "modules"
        (modules_root / "gatekit" / "module.yaml").write_text(
            _CUSTOM_MANIFEST.replace("kind: custom", "kind: density"),
            encoding="utf-8")
        self.write_gates(
            "gates:\n"
            "  - id: anything\n"
            "    kind: file_exists\n"
            "    file: a.txt\n"
        )
        with self.assertRaises(declared_gates.GatesConfigError) as ctx:
            self.run_all()
        self.assertIn("shadows a core-implemented kind", str(ctx.exception))


# ── CLI contract ────────────────────────────────────────────────────


class CliTests(Base):
    def test_cli_writes_result_and_exits_zero_on_pass(self):
        self.write_text("output/out.hwpx", "bytes")
        self.write_gates(
            "gates:\n"
            "  - id: assembled\n"
            "    kind: file_exists\n"
            "    file: output/out.hwpx\n"
        )
        code, stdout = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("PASS assembled", stdout)
        payload = json.loads(
            (self.ws / "gate_result.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_pass"])
        self.assertEqual(payload["checker"], "declared_gates")
        self.assertEqual(payload["workspace_slug"], SLUG)
        self.assertIn("checked_at", payload)

    def test_cli_exit_three_on_gate_failure(self):
        self.write_gates(
            "gates:\n"
            "  - id: assembled\n"
            "    kind: file_exists\n"
            "    file: output/never_built.hwpx\n"
        )
        code, stdout = self.run_cli()
        self.assertEqual(code, 3)
        self.assertIn("FAIL assembled", stdout)
        self.assertIn("target_missing", stdout)

    def test_cli_missing_workspace_is_usage(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = declared_gates.main(
                [str(Path(self._tmp.name) / "no-such-ws")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
