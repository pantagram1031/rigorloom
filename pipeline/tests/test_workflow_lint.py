"""Synthetic conformance tests for workflow_lint.py."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pipeline_ctl  # noqa: E402
import workflow_lint  # noqa: E402


class WorkflowLintTestCase(unittest.TestCase):
    NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-lint"
        self.ws.mkdir()
        rows = pipeline_ctl.load_stages_config()
        self.ctx = pipeline_ctl._make_graph_context(rows, "build")
        stages = {}
        for stage_id in self.ctx["order"]:
            gate = None
            if stage_id in self.ctx["gate_names"]:
                gate = {"name": self.ctx["gate_names"][stage_id],
                        "state": "pending", "by": None, "at": None}
            stages[stage_id] = {"status": "pending", "gate": gate}
        self.hdr = {
            "pipeline_version": "0.6", "graph": "build", "slug": "lint",
            "mode": "autonomous", "subject": "x", "topic": "x", "form": "x",
            "updated": self.NOW.isoformat(), "canonical_output": None,
            "stages": stages,
        }
        self.write_header()
        (self.ws / "heartbeat").write_text(self.NOW.isoformat(), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write_header(self):
        body = pipeline_ctl.render_yaml_body(self.hdr, self.ctx)
        (self.ws / "PIPELINE.md").write_text(
            f"```yaml\n{body}\n```\n", encoding="utf-8")

    def _gate_checker_for(self, stage):
        """The graph's registered checker argv for a stage's gate (or None)."""
        row = {str(r["id"]): r for r in self.ctx["rows"]}[str(stage)]
        return (row.get("gate") or {}).get("checker")

    def genuine_receipt_argv(self, stage):
        """Reproduce the argv a real cmd_check run would record for `stage`:
        placeholders substituted and a leading "python" rebound to
        sys.executable."""
        argv = pipeline_ctl._substitute_checker_argv(
            self._gate_checker_for(stage), self.ws)
        if argv and argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        return argv

    def add_receipt(self, stage, gate, *, checker_argv=None, stdout_sha256=None):
        """Append a gate_checks receipt. Defaults produce a GENUINE receipt
        (matching argv + a well-formed hash); pass explicit values to forge a
        bad one."""
        if checker_argv is None:
            checker_argv = self.genuine_receipt_argv(stage)
        if stdout_sha256 is None:
            stdout_sha256 = hashlib.sha256(b'{"ok": true}').hexdigest()
        target = self.ws / ".pipeline" / "gate_checks.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {"stage": stage, "gate": gate,
                  "checker_argv": checker_argv, "stdout_sha256": stdout_sha256}
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def add_events(self):
        """Write a minimal event ledger so H5 (missing-ledger) does not fire on
        workspaces that have advanced a stage."""
        (self.ws / "events.jsonl").write_text(json.dumps({
            "ts": self.NOW.isoformat(), "type": "advance", "stage": "0",
        }) + "\n", encoding="utf-8")

    def add_event_and_output(self, offset_seconds):
        (self.ws / "events.jsonl").write_text(json.dumps({
            "ts": self.NOW.isoformat(), "type": "advance", "stage": "5",
        }) + "\n", encoding="utf-8")
        output = self.ws / "output" / "out.pdf"
        output.parent.mkdir()
        output.write_bytes(b"synthetic")
        stamp = self.NOW.timestamp() + offset_seconds
        os.utime(output, (stamp, stamp))

    def lint(self):
        return workflow_lint.check(self.ws, now=self.NOW)


class TestScriptGateReceipt(WorkflowLintTestCase):
    def test_done_script_gate_without_receipt_is_hard(self):
        self.hdr["stages"]["3"]["status"] = "done"
        self.write_header()
        self.add_events()
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H1" for item in verdict["hard"]))

    def test_done_script_gate_with_genuine_receipt_is_clean(self):
        self.hdr["stages"]["3"]["status"] = "done"
        self.write_header()
        self.add_events()
        self.add_receipt("3", "sane")  # genuine argv + hash by default
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)

    def test_fabricated_receipt_wrong_argv_fails_h1(self):
        # A free-form receipt tagged with the right (stage, gate) but a bogus
        # checker_argv must NOT satisfy H1.
        self.hdr["stages"]["3"]["status"] = "done"
        self.write_header()
        self.add_events()
        self.add_receipt("3", "sane",
                         checker_argv=["python", "/tmp/totally-not-the-checker.py"])
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H1" for item in verdict["hard"]))

    def test_fabricated_receipt_empty_hash_fails_h1(self):
        # Right (stage, gate) and right argv, but an empty/absent stdout_sha256
        # must NOT satisfy H1.
        self.hdr["stages"]["3"]["status"] = "done"
        self.write_header()
        self.add_events()
        self.add_receipt("3", "sane", stdout_sha256="")
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H1" for item in verdict["hard"]))


class TestCanonicalGateState(WorkflowLintTestCase):
    def test_canonical_output_with_pending_gate_is_hard(self):
        self.hdr["canonical_output"] = "output/out.pdf"
        self.write_header()
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H2" for item in verdict["hard"]))

    def test_canonical_output_with_resolved_gates_is_clean(self):
        self.hdr["canonical_output"] = "output/out.pdf"
        for state in self.hdr["stages"].values():
            if state["gate"]:
                state["gate"]["state"] = "approved"
        self.write_header()
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)


class TestOutputEventFreshness(WorkflowLintTestCase):
    def test_output_over_ten_minutes_newer_is_hard(self):
        self.add_event_and_output(601)
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H3" for item in verdict["hard"]))

    def test_output_within_ten_minutes_is_clean(self):
        self.add_event_and_output(600)
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)

    def test_missing_events_is_warn_not_hard(self):
        output = self.ws / "output" / "out.pdf"
        output.parent.mkdir()
        output.write_bytes(b"synthetic")
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(item["code"] == "W1" for item in verdict["warn"]))

    def test_no_output_needs_no_event_warning(self):
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "W1" for item in verdict["warn"]))


class TestSupervisedAutoApproval(WorkflowLintTestCase):
    def test_auto_approved_human_gate_warns(self):
        self.hdr["mode"] = "supervised"
        self.hdr["stages"]["2"]["gate"]["state"] = "auto_approved"
        self.write_header()
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(item["code"] == "W2" for item in verdict["warn"]))

    def test_operator_approved_human_gate_does_not_warn(self):
        self.hdr["mode"] = "supervised"
        self.hdr["stages"]["2"]["gate"]["state"] = "approved"
        self.write_header()
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "W2" for item in verdict["warn"]))


class TestHeartbeatAge(WorkflowLintTestCase):
    def test_heartbeat_over_24_hours_warns(self):
        old = self.NOW - timedelta(hours=24, seconds=1)
        (self.ws / "heartbeat").write_text(old.isoformat(), encoding="utf-8")
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertTrue(any(item["code"] == "W3" for item in verdict["warn"]))

    def test_heartbeat_at_24_hours_does_not_warn(self):
        recent = self.NOW - timedelta(hours=24)
        (self.ws / "heartbeat").write_text(recent.isoformat(), encoding="utf-8")
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "W3" for item in verdict["warn"]))


class TestMissingEventLedger(WorkflowLintTestCase):
    """H5: deleting/omitting events.jsonl once a stage has progressed is HARD,
    not a downgrade to WARN."""

    def test_missing_events_with_progressed_stage_is_hard(self):
        self.hdr["stages"]["0"]["status"] = "done"
        self.write_header()
        # no events.jsonl written
        self.assertFalse((self.ws / "events.jsonl").exists())
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H5" for item in verdict["hard"]))

    def test_present_events_with_progressed_stage_is_clean(self):
        self.hdr["stages"]["0"]["status"] = "done"  # gate null, not script
        self.write_header()
        self.add_events()
        verdict, code = self.lint()
        self.assertEqual(code, 0, verdict)
        self.assertFalse(any(item["code"] == "H5" for item in verdict["hard"]))

    def test_missing_events_all_pending_does_not_fire_h5(self):
        # A freshly-initialized workspace (all stages pending) has not moved, so
        # a missing ledger is not yet an H5 tell.
        (self.ws / "events.jsonl").unlink(missing_ok=True)
        verdict, code = self.lint()
        self.assertFalse(any(item["code"] == "H5" for item in verdict["hard"]))


class TestHeaderGraphStageSetMismatch(WorkflowLintTestCase):
    """H4: a header carrying a stage id the selected graph does not define is a
    graph-switch tell (HARD)."""

    def _write_raw(self, graph, stage_lines):
        body_lines = [
            "# pipeline-state: v0.4",
            'pipeline_version: "0.6"',
            f'graph: "{graph}"',
            'slug: "lint"',
            "mode: autonomous",
            "subject: x", "topic: x", "form: x",
            "updated: 2026-07-13T12:00:00",
            "canonical_output: null",
            "stages:",
        ]
        body_lines.extend(stage_lines)
        (self.ws / "PIPELINE.md").write_text(
            "```yaml\n" + "\n".join(body_lines) + "\n```\n", encoding="utf-8")

    def test_build_header_with_edit_only_id_is_hard(self):
        # graph=build but carrying edit-only stage 3.5 -> foreign id -> H4.
        self._write_raw("build", [
            '  "0":   {status: pending, gate: null}',
            '  "3.5": {status: pending, gate: null}',
        ])
        self.add_events()
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H4" for item in verdict["hard"]))

    def test_edit_header_with_build_only_id_is_hard(self):
        # graph=edit but carrying build-only stage 5.7 -> foreign id -> H4.
        self._write_raw("edit", [
            '  "0":   {status: pending, gate: null}',
            '  "5.7": {status: pending, gate: null}',
        ])
        self.add_events()
        verdict, code = self.lint()
        self.assertEqual(code, 3)
        self.assertTrue(any(item["code"] == "H4" for item in verdict["hard"]))

    def test_matching_build_header_has_no_h4(self):
        # The default full-build workspace built in setUp must not trip H4.
        verdict, code = self.lint()
        self.assertFalse(any(item["code"] == "H4" for item in verdict["hard"]))
