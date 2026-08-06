"""Tests for pipeline_ctl.py — run offline with `python test_pipeline_ctl.py`
or `pytest test_pipeline_ctl.py`. Uses tmp dirs only; no network.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from pipeline.scripts import pipeline_ctl as ctl

SCRIPT = Path(__file__).parents[1] / "scripts" / "pipeline_ctl.py"


def run(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        raise AssertionError(
            f"non-JSON stdout for args={args}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return payload, proc.returncode


class PipelineCtlTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "report-test-slug"

    def tearDown(self):
        self._tmp.cleanup()

    def init_ws(self, mode="autonomous", graph="build"):
        payload, code = run(
            "init", str(self.ws),
            "--slug", "test-slug", "--mode", mode,
            "--subject", "earth-science", "--topic", "테스트 주제",
            "--form", "templates/form.hwpx", "--graph", graph,
        )
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        if graph == "build":
            if mode == "supervised":
                (self.ws / "APPROVALS.md").write_text(
                    "topic_pick: approved by=<name> "
                    "at=2026-07-17T09:10:00+09:00\n",
                    encoding="utf-8",
                )
            gate_payload, gate_code = run(
                "gate", str(self.ws), "topic_pick", "--mode", mode,
            )
            self.assertEqual(gate_code, 0, gate_payload)
        return payload


class TestInitAndResume(PipelineCtlTestCase):
    def test_init_then_resume_returns_stage_0(self):
        self.init_ws()
        self.assertTrue((self.ws / "NEXT_TASK.md").exists())
        self.assertTrue((self.ws / ".pipeline" / "handoff.json").exists())
        self.assertTrue((self.ws / ".pipeline" / "artifacts.json").exists())
        self.assertTrue((self.ws / "WORKSPACE_INDEX.md").exists())
        self.assertTrue((self.ws / "work" / "stage-0" / "scratch").is_dir())
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["next_stage"], "0")
        self.assertFalse(payload["blocked"])

    def test_edit_graph_init_round_trips_and_resumes_at_intake(self):
        payload = self.init_ws(graph="edit")
        self.assertEqual(payload["graph"], "edit")
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        self.assertIn('graph: "edit"', text)
        self.assertIn('"3.5":', text)
        handoff = json.loads(
            (self.ws / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(handoff["playbook"],
                         "pipeline/references/playbooks/edit-stage-0.md")
        resumed, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["next_stage"], "0")

    def test_edit_graph_check_uses_content_audit_binding(self):
        self.init_ws(graph="edit")
        payload, code = run("check", str(self.ws), "content_audit")
        self.assertEqual(code, 0, payload)
        self.assertIn("content_audit.py", " ".join(payload["checker_argv"]))

    def test_init_refuses_if_pipeline_exists(self):
        self.init_ws()
        payload, code = run(
            "init", str(self.ws),
            "--slug", "test-slug", "--mode", "autonomous",
            "--subject", "x", "--topic", "y", "--form", "z",
        )
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_events_jsonl_grows(self):
        self.init_ws()
        events_path = self.ws / "events.jsonl"
        self.assertTrue(events_path.exists())
        n1 = len(events_path.read_text(encoding="utf-8").splitlines())
        run("advance", str(self.ws), "0", "--status", "in_progress")
        n2 = len(events_path.read_text(encoding="utf-8").splitlines())
        self.assertGreater(n2, n1)

    def test_done_transition_archives_safe_transients_and_updates_handoff(self):
        self.init_ws()
        (self.ws / "notes.tmp").write_text("temporary", encoding="utf-8")
        payload, code = run("advance", str(self.ws), "0", "--status", "done")
        self.assertEqual(code, 0, payload)
        self.assertFalse((self.ws / "notes.tmp").exists())
        archived = list((self.ws / "archive" / "stages" / "stage-0").rglob("notes.tmp"))
        self.assertEqual(len(archived), 1)
        handoff = json.loads((self.ws / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(handoff["next_stage"], "1")
        self.assertEqual(handoff["work_dir"], "work/stage-1")
        self.assertTrue(list((self.ws / ".pipeline" / "receipts").glob("stage-0-*.json")))


class TestAdvance(PipelineCtlTestCase):
    def test_advance_legal_path(self):
        self.init_ws()
        payload, code = run("advance", str(self.ws), "0", "--status", "in_progress")
        self.assertEqual(code, 0, payload)
        payload, code = run("advance", str(self.ws), "0", "--status", "done")
        self.assertEqual(code, 0, payload)
        payload, code = run("resume", str(self.ws))
        self.assertEqual(payload["next_stage"], "1")

    def test_advance_unknown_stage_refused(self):
        self.init_ws()
        payload, code = run("advance", str(self.ws), "99", "--status", "in_progress")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_advance_unknown_status_refused(self):
        self.init_ws()
        payload, code = run("advance", str(self.ws), "0", "--status", "bogus")
        # argparse choices restrict this -> usage error (exit 2)
        self.assertEqual(code, 2)

    def test_advance_refusal_supervised_pending_gate(self):
        # stage 2 has a 'design' gate; starting stage 3 must be refused while
        # stage 2's gate is still pending in supervised mode.
        self.init_ws(mode="supervised")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        # stage 2's design gate is still pending (never resolved)
        payload, code = run("advance", str(self.ws), "3", "--status", "in_progress")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("gate", payload["error"].lower())

    def test_advance_allowed_autonomous_despite_pending_human_gate(self):
        # In autonomous mode a pending HUMAN gate on an earlier stage does not
        # by itself block (only 'rejected' blocks universally; pending human
        # gates block only in supervised mode). Stage 2's design gate is human,
        # so advancing into 2.5 must be allowed while it is still pending.
        # (A pending SCRIPT gate, by contrast, blocks all modes — covered by
        # TestScriptGateBlocksAllModes.)
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        payload, code = run("advance", str(self.ws), "2.5", "--status", "in_progress")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])


class TestGate(PipelineCtlTestCase):
    def test_gate_approved_only_via_approvals_md(self):
        self.init_ws(mode="supervised")
        # No design approval line exists yet, so supervised refuses.
        payload, code = run("gate", str(self.ws), "design", "--mode", "supervised")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

        (self.ws / "APPROVALS.md").write_text(
            "design: approved by=<name> at=2026-07-06T09:10:00+09:00\n", encoding="utf-8"
        )
        payload, code = run("gate", str(self.ws), "design", "--mode", "supervised")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "approved")
        self.assertEqual(payload["by"], "operator")
        self.assertEqual(payload["at"], "2026-07-06T09:10:00+09:00")

        # verify persisted in header
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        self.assertIn("state: approved", text)
        self.assertIn("by: operator", text)

    def test_gate_auto_approved_in_autonomous(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "design", "--mode", "autonomous")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertEqual(payload["by"], "autonomous")

    def test_gate_rejected_propagates(self):
        self.init_ws(mode="supervised")
        (self.ws / "APPROVALS.md").write_text(
            "design: rejected — scope too broad, narrow to AFGKM\n", encoding="utf-8"
        )
        payload, code = run("gate", str(self.ws), "design", "--mode", "supervised")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertIn("scope too broad", payload["reason"])

        # resume should now report blocked once stage 2 is awaiting_gate
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        payload, code = run("resume", str(self.ws))
        self.assertTrue(payload["blocked"])

    def test_gate_never_writes_approved_without_line(self):
        # exhaustive-ish: for both modes, absent any APPROVALS.md line the
        # gate state written must never be 'approved'.
        for mode in ("autonomous", "supervised", "night"):
            ws = self.root / f"report-{mode}"
            run(
                "init", str(ws), "--slug", f"slug-{mode}", "--mode", mode,
                "--subject", "s", "--topic", "t", "--form", "f",
            )
            payload, code = run("gate", str(ws), "design", "--mode", mode)
            if mode == "supervised":
                self.assertEqual(code, 1)
                continue
            self.assertEqual(code, 0)
            self.assertNotEqual(payload["state"], "approved")
            self.assertEqual(payload["state"], "auto_approved")


class TestInvalidate(PipelineCtlTestCase):
    def test_invalidate_resets_downstream(self):
        self.init_ws(mode="autonomous")
        for s in ["0", "1", "2", "3", "4"]:
            run("advance", str(self.ws), s, "--status", "done")
        run("gate", str(self.ws), "design", "--mode", "autonomous")
        run("gate", str(self.ws), "draft", "--mode", "autonomous")

        payload, code = run("invalidate", str(self.ws), "--from", "3", "--reason", "bad sim data")
        self.assertEqual(code, 0, payload)
        self.assertEqual(sorted(payload["reset_stages"]), sorted(["3", "4", "4.5", "5", "5.3", "5.5", "5.7", "6"]))

        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        self.assertIn('"0":', header_part)
        # stage 0/1/2 should remain done
        for s in ["0", "1", "2"]:
            line = [l for l in header_part.splitlines() if f'"{s}":' in l][0]
            self.assertIn("status: done", line)
        # stage 3 and later should be pending
        for s in ["3", "4", "4.5", "5", "5.3", "5.5", "5.7", "6"]:
            line = [l for l in header_part.splitlines() if f'"{s}":' in l][0]
            self.assertIn("status: pending", line)
        # stage 4's draft gate should be reset to pending/null
        draft_line = [l for l in header_part.splitlines() if '"4":' in l][0]
        self.assertIn("state: pending", draft_line)
        self.assertIn("by: null", draft_line)

    def test_invalidate_nulls_canonical_output_for_early_stage(self):
        self.init_ws(mode="autonomous")
        loaded_before = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        run("invalidate", str(self.ws), "--from", "5")
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        self.assertIn("canonical_output: null", text)


class TestHeaderRewritePreservesTable(PipelineCtlTestCase):
    def test_trailing_human_table_preserved(self):
        self.init_ws()
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        marker = "\n\n## Notes\n\nHand-written operator notes should survive.\n"
        pf.write_text(text + marker, encoding="utf-8")

        run("advance", str(self.ws), "0", "--status", "in_progress")

        after = pf.read_text(encoding="utf-8")
        self.assertIn("Hand-written operator notes should survive.", after)
        self.assertIn("## Notes", after)


class TestTrouble(PipelineCtlTestCase):
    def test_trouble_writes_both_files(self):
        self.init_ws()
        evidence = self.root / "evidence.txt"
        evidence.write_text("stack trace here", encoding="utf-8")
        kb_root = self.root / "kb"

        payload, code = run(
            "trouble", str(self.ws),
            "--stage", "3", "--role", "sim-runner", "--model", "sonnet",
            "--failure-class", "timeout", "--evidence", str(evidence),
            "--kb-root", str(kb_root),
        )
        self.assertEqual(code, 0, payload)

        troubles = (self.ws / "TROUBLES.md").read_text(encoding="utf-8")
        self.assertIn("| at | stage | role | model | failure | evidence |", troubles)
        self.assertIn("sim-runner", troubles)

        model_log = (kb_root / "model-log.md").read_text(encoding="utf-8")
        self.assertIn("sim-runner", model_log)
        self.assertIn("timeout", model_log)

    def test_trouble_appends_on_second_call(self):
        self.init_ws()
        kb_root = self.root / "kb2"
        run("trouble", str(self.ws), "--stage", "1", "--role", "r1", "--model", "m1",
            "--failure-class", "f1", "--evidence", "e1", "--kb-root", str(kb_root))
        run("trouble", str(self.ws), "--stage", "2", "--role", "r2", "--model", "m2",
            "--failure-class", "f2", "--evidence", "e2", "--kb-root", str(kb_root))
        troubles = (self.ws / "TROUBLES.md").read_text(encoding="utf-8")
        self.assertEqual(troubles.count("r1"), 1)
        self.assertEqual(troubles.count("r2"), 1)
        # header appears exactly once
        self.assertEqual(troubles.count("| at | stage |"), 1)


class TestHeartbeat(PipelineCtlTestCase):
    def test_heartbeat_writes_file(self):
        self.init_ws()
        payload, code = run("heartbeat", str(self.ws))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        hb = (self.ws / "heartbeat").read_text(encoding="utf-8")
        self.assertTrue(hb.strip())


class TestResumeAwaitingGate(PipelineCtlTestCase):
    """BLOCKER 1: resume must not skip a stage sitting at awaiting_gate —
    it must be selected (not the next pending stage), and the existing
    gate-handling response must fire, in all three run modes."""

    def _advance_to_awaiting_gate(self):
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")

    def test_resume_returns_awaiting_gate_stage_supervised(self):
        self.init_ws(mode="supervised")
        self._advance_to_awaiting_gate()
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2")
        self.assertTrue(payload["blocked"])
        self.assertIn("gate", payload)

    def test_resume_returns_awaiting_gate_stage_autonomous(self):
        self.init_ws(mode="autonomous")
        self._advance_to_awaiting_gate()
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2")
        self.assertEqual(payload.get("action_needed"), "gate")
        self.assertFalse(payload["blocked"])

    def test_resume_returns_awaiting_gate_stage_night(self):
        self.init_ws(mode="night")
        self._advance_to_awaiting_gate()
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2")
        self.assertEqual(payload.get("action_needed"), "gate")
        self.assertFalse(payload["blocked"])

    def test_resume_does_not_skip_to_next_pending_stage(self):
        # regression guard for the exact gate-bypass bug: with stage 2
        # awaiting_gate, resume must not report stage 3 (the next pending
        # stage) as next_stage.
        self.init_ws(mode="supervised")
        self._advance_to_awaiting_gate()
        payload, code = run("resume", str(self.ws))
        self.assertNotEqual(payload["next_stage"], "3")


class TestAdvanceGateBypassAllStatuses(PipelineCtlTestCase):
    """BLOCKER 2: predecessor-gate validation must apply to every
    forward-moving status (in_progress, awaiting_gate, done), not just
    in_progress."""

    def test_advance_done_refused_when_predecessor_gate_rejected(self):
        self.init_ws(mode="supervised")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        (self.ws / "APPROVALS.md").write_text(
            "design: rejected — out of scope\n", encoding="utf-8"
        )
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        run("gate", str(self.ws), "design", "--mode", "supervised")
        # stage 2's design gate is now rejected; advancing stage 3 straight
        # to "done" must be refused, not just blocked for in_progress.
        payload, code = run("advance", str(self.ws), "3", "--status", "done")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("gate", payload["error"].lower())

    def test_advance_awaiting_gate_refused_when_predecessor_supervised_pending(self):
        self.init_ws(mode="supervised")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        # stage 2's design gate was never resolved -> still pending
        payload, code = run("advance", str(self.ws), "3", "--status", "awaiting_gate")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("gate", payload["error"].lower())

    def test_advance_blocked_always_allowed_despite_rejected_predecessor_gate(self):
        # `blocked` is a safety valve and must remain settable regardless of
        # predecessor gate state.
        self.init_ws(mode="supervised")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        (self.ws / "APPROVALS.md").write_text(
            "design: rejected — nope\n", encoding="utf-8"
        )
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        run("gate", str(self.ws), "design", "--mode", "supervised")
        payload, code = run("advance", str(self.ws), "3", "--status", "blocked")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])


class TestAdvanceLegalTransitionGuard(PipelineCtlTestCase):
    def test_done_to_in_progress_refused_must_use_invalidate(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        payload, code = run("advance", str(self.ws), "0", "--status", "in_progress")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("invalidate", payload["error"].lower())

    def test_done_to_awaiting_gate_refused(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "2", "--status", "done")
        payload, code = run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_blocked_to_done_refused(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "blocked")
        payload, code = run("advance", str(self.ws), "0", "--status", "done")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_blocked_to_in_progress_allowed(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "blocked")
        payload, code = run("advance", str(self.ws), "0", "--status", "in_progress")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])


class TestYamlScalarSafety(PipelineCtlTestCase):
    def test_topic_with_embedded_quotes_round_trips(self):
        topic = 'He said "hello" and used a \\ backslash \\" combo'
        payload, code = run(
            "init", str(self.ws),
            "--slug", "quote-slug", "--mode", "autonomous",
            "--subject", "x", "--topic", topic, "--form", "z",
        )
        self.assertEqual(code, 0, payload)

        # Round-trip check via a fresh subprocess (avoids importing
        # pipeline_ctl in-process, which would re-trigger its module-level
        # Windows UTF-8 re-exec guard against pytest's own argv).
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "from pathlib import Path; "
            "loaded = pc.load_header(Path(r'%s')); "
            "_, _, _, hdr = loaded; "
            "assert hdr['topic'] == %r, hdr['topic']; "
            "print('OK')"
        ) % (str(SCRIPT.parent), str(self.ws), topic)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_hash_colon_and_newline_scalars_round_trip(self):
        topic = "first line # not a comment\nsecond: line"
        subject = "science: advanced #1"
        form = r"C:\forms\form #1: final.hwpx"
        payload, code = run(
            "init", str(self.ws),
            "--slug", "scalar-slug", "--mode", "autonomous",
            "--subject", subject, "--topic", topic, "--form", form,
        )
        self.assertEqual(code, 0, payload)
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "from pathlib import Path; hdr=pc.load_header(Path(r'%s'))[3]; "
            "assert hdr['topic'] == %r; assert hdr['subject'] == %r; "
            "assert hdr['form'] == %r; print('OK')"
        ) % (str(SCRIPT.parent), str(self.ws), topic, subject, form)
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestTroubleSingleHeader(PipelineCtlTestCase):
    def test_trouble_called_twice_exactly_one_header_two_rows(self):
        self.init_ws()
        kb_root = self.root / "kb3"
        run("trouble", str(self.ws), "--stage", "1", "--role", "r1", "--model", "m1",
            "--failure-class", "f1", "--evidence", "e1", "--kb-root", str(kb_root))
        run("trouble", str(self.ws), "--stage", "2", "--role", "r2", "--model", "m2",
            "--failure-class", "f2", "--evidence", "e2", "--kb-root", str(kb_root))

        troubles = (self.ws / "TROUBLES.md").read_text(encoding="utf-8")
        self.assertEqual(troubles.count("| at | stage | role | model | failure | evidence |"), 1)
        self.assertEqual(troubles.count("|---|---|---|---|---|---|"), 1)
        self.assertEqual(len([l for l in troubles.splitlines() if "r1" in l]), 1)
        self.assertEqual(len([l for l in troubles.splitlines() if "r2" in l]), 1)

        model_log = (kb_root / "model-log.md").read_text(encoding="utf-8")
        self.assertEqual(model_log.count("| at | stage | role | model | failure | evidence |"), 1)
        self.assertEqual(len([l for l in model_log.splitlines() if "r1" in l]), 1)
        self.assertEqual(len([l for l in model_log.splitlines() if "r2" in l]), 1)


class TestStagesConfigLoader(unittest.TestCase):
    """Config loader: present config parses; missing / corrupt / empty
    stages.yaml is a HARD ERROR (StagesConfigError), never a silent fallback."""

    LOADER_PROBE = '''
import sys
sys.path.insert(0, r"{scriptdir}")
import pipeline_ctl as pc
try:
    rows = pc.load_stages_config(r"{cfgscript}")
    print("OK", len(rows), [r["id"] for r in rows])
except pc.StagesConfigError as e:
    print("HARDERR", e)
'''

    def _load_at(self, script_dir: Path):
        """Run load_stages_config in a fresh subprocess (dodging the module-level
        Windows UTF-8 re-exec guard) with the script living at script_dir, so it
        looks for <script_dir>/../references/stages.yaml."""
        code = self.LOADER_PROBE.format(
            scriptdir=str(SCRIPT.parent),
            cfgscript=str(script_dir / "pipeline_ctl.py"),
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )

    def test_present_config_parses_all_rows(self):
        real_cfg = SCRIPT.parent.parent / "references" / "stages.yaml"
        self.assertTrue(real_cfg.exists(), "references/stages.yaml must exist")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
             "rows = pc.load_stages_config(); "
             "ids = [r['id'] for r in rows]; "
             "assert ids == ['0','1','2','2.5','3','4','4.5','5','5.3','5.5','5.7','6'], ids; "
             "print('OK', len(rows))" % str(SCRIPT.parent)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK 12", proc.stdout)

    def test_missing_config_hard_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            # no references/ dir at all next to fake_scripts's parent
            proc = self._load_at(fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("HARDERR", proc.stdout)
            self.assertNotIn("OK", proc.stdout)

    def test_corrupt_config_hard_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            # a row that is a malformed inline map missing 'id'
            (fake_refs / "stages.yaml").write_text(
                "version: \"0.6\"\nstages:\n  - {name: nope, gate: null}\n",
                encoding="utf-8",
            )
            proc = self._load_at(fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("HARDERR", proc.stdout)

    def test_empty_stages_list_hard_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text("version: \"0.6\"\nstages:\n", encoding="utf-8")
            proc = self._load_at(fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("HARDERR", proc.stdout)

    def test_corrupt_edit_config_hard_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages-edit.yaml").write_text(
                'version: "0.6"\nstages:\n  - {id: "0", name: intake, gate: nope, playbook: p}\n',
                encoding="utf-8",
            )
            code = self.LOADER_PROBE.replace(
                'pc.load_stages_config(r"{cfgscript}")',
                'pc.load_stages_config(r"{cfgscript}", graph="edit")',
            ).format(scriptdir=str(SCRIPT.parent),
                     cfgscript=str(fake_scripts / "pipeline_ctl.py"))
            proc = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True,
                encoding="utf-8",
                env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("HARDERR", proc.stdout)
            self.assertIn("gate must be null or a map", proc.stdout)

    def _load_text(self, yaml_text: str):
        """Write yaml_text as <root>/references/stages.yaml and load it via a
        fresh subprocess, returning the CompletedProcess. Loader prints
        'OK ...' on success or 'HARDERR ...' on StagesConfigError."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text(yaml_text, encoding="utf-8")
            return self._load_at(fake_scripts)

    def test_missing_colon_gate_row_hard_errors(self):
        # The exact adversarial probe: 'gate {name: ...}' is missing the colon
        # after 'gate', so 'gate' never becomes a key and the stage would be
        # silently gate-less. Must be a HARD ERROR, not a silent drop.
        proc = self._load_text(
            'version: "0.6"\nstages:\n'
            '  - {id: "2.5", name: x, gate {name: layout, type: script}, playbook: p}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)
        self.assertNotIn("OK", proc.stdout)

    def test_unexpected_top_level_key_hard_errors(self):
        proc = self._load_text(
            'version: "0.6"\nstages:\n'
            '  - {id: "1", name: research, gate: null, playbook: p, bogus: x}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)
        self.assertNotIn("OK", proc.stdout)

    def test_row_without_gate_key_hard_errors(self):
        # A row with NO 'gate' key must NOT be treated as an implicit gate:null.
        proc = self._load_text(
            'version: "0.6"\nstages:\n'
            '  - {id: "1", name: research, playbook: p}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)
        self.assertNotIn("OK", proc.stdout)

    def test_explicit_gate_null_row_still_parses(self):
        # Guard the happy path: gate: null (explicit) is a valid gate-less stage.
        proc = self._load_text(
            'version: "0.6"\nstages:\n'
            '  - {id: "1", name: research, gate: null, playbook: p}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_checker_must_be_argv_array(self):
        proc = self._load_text(
            'version: "0.6"\nstages:\n'
            '  - {id: "1", name: audit, gate: {name: audit, type: script, checker: "python check.py"}, playbook: p}\n'
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("HARDERR", proc.stdout)
        self.assertIn("argv array", proc.stdout)

    def test_cli_hard_errors_when_config_broken(self):
        # End-to-end: a CLI invocation whose stages.yaml fails to load must emit
        # a clean JSON hard error + nonzero exit, not a traceback or a pass.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text("version: \"0.6\"\nstages:\n", encoding="utf-8")
            # copy the real script next to the broken config
            (fake_scripts / "pipeline_ctl.py").write_text(
                SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
            )
            proc = subprocess.run(
                [sys.executable, str(fake_scripts / "pipeline_ctl.py"), "resume", str(root)],
                capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout.strip())
            self.assertFalse(payload["ok"])
            self.assertIn("stages.yaml", payload["error"])


class TestStage25Ordering(PipelineCtlTestCase):
    """Stage 2.5 (layout_plan) must sit between 2 and 3 in resume/advance
    ordering, with its own script-type 'layout' gate."""

    def test_stage_order_includes_2_5_between_2_and_3(self):
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "i2 = pc.STAGE_ORDER.index('2'); i25 = pc.STAGE_ORDER.index('2.5'); "
            "i3 = pc.STAGE_ORDER.index('3'); "
            "assert i2 < i25 < i3, (i2, i25, i3); print('OK')"
        ) % str(SCRIPT.parent)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_stage_order_includes_4_5_between_4_and_5(self):
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "o = pc.STAGE_ORDER; "
            "assert '4.5' in o, o; "
            "assert o.index('4') < o.index('4.5') < o.index('5'), o; "
            "print('OK')"
        ) % str(SCRIPT.parent)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_stage_order_includes_5_3_between_5_and_5_5(self):
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "o = pc.STAGE_ORDER; "
            "assert '5.3' in o, o; "
            "assert o.index('5') < o.index('5.3') < o.index('5.5'), o; "
            "print('OK')"
        ) % str(SCRIPT.parent)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_resume_advances_through_2_5_before_3(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        run("gate", str(self.ws), "design", "--mode", "autonomous")
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2.5")

    def test_stage_2_5_has_layout_script_gate_pending_on_init(self):
        self.init_ws(mode="autonomous")
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        line = [l for l in header_part.splitlines() if '"2.5":' in l][0]
        self.assertIn("name: layout", line)
        self.assertIn("state: pending", line)

    def test_invalidate_from_3_resets_2_5_predecessor_untouched(self):
        # invalidating from stage 3 must not reset stage 2.5 (it precedes 3).
        self.init_ws(mode="autonomous")
        for s in ["0", "1", "2", "2.5"]:
            run("advance", str(self.ws), s, "--status", "done")
        payload, code = run("invalidate", str(self.ws), "--from", "3")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("2.5", payload["reset_stages"])
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        line = [l for l in header_part.splitlines() if '"2.5":' in l][0]
        self.assertIn("status: done", line)


class TestScriptExitRetired(PipelineCtlTestCase):
    """--script-exit recorded a caller-supplied verdict with no checker ever
    run (the defect). It is now a hard usage error for BOTH script and human
    gate names — script gates resolve only via `check`."""

    def test_script_exit_on_script_gate_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "sane", "--script-exit", "0")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("retired", payload["error"].lower())
        self.assertIn("check", payload["error"].lower())
        # must not have mutated the sane gate at all
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        line = [l for l in text.split("```")[1].splitlines() if '"3":' in l][0]
        self.assertNotIn("auto_approved", line)
        self.assertIn("state: pending", line)

    def test_script_exit_on_human_gate_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "design", "--script-exit", "1")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("retired", payload["error"].lower())

    def test_gate_missing_mode_and_script_exit_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "design")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])


class TestCheckSubcommand(PipelineCtlTestCase):
    """`check <ws> <gate>` RUNS the bound checker: exit 0 -> auto_approved,
    nonzero -> rejected. Records provenance. Null/unknown/human -> usage error,
    never a pass."""

    def _write_sim_gate(self, exit_code, stdout='{"ok": true}'):
        sim = self.ws / "sim"
        sim.mkdir(parents=True, exist_ok=True)
        (sim / "gates.py").write_text(
            "import sys\n"
            "print(%r)\n"
            "sys.exit(%d)\n" % (stdout, exit_code),
            encoding="utf-8",
        )

    def _write_understanding_questions(self, with_answers=False):
        output = self.ws / "output"
        output.mkdir(parents=True, exist_ok=True)
        blocks = []
        for number in range(1, 6):
            block = (
                f"{number}. Why does report mechanism {number} matter to the "
                "conclusion?"
            )
            if with_answers:
                block += "\n   Answer: I can explain this mechanism from the report."
            blocks.append(block)
        (output / "QUESTIONS.md").write_text(
            "\n\n".join(blocks) + "\n", encoding="utf-8")

    def test_check_happy_path_auto_approves_with_provenance(self):
        self.init_ws(mode="autonomous")
        self._write_sim_gate(0)
        payload, code = run("check", str(self.ws), "sane")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertEqual(payload["by"], "script")
        self.assertEqual(payload.get("detail"), "checker")
        for k in ("checker_argv", "exit", "stdout_sha256", "checked_at"):
            self.assertIn(k, payload)
        self.assertEqual(payload["exit"], 0)
        self.assertIsInstance(payload["checker_argv"], list)
        self.assertEqual(len(payload["stdout_sha256"]), 64)
        # persisted in header (scalar stays name/state/by/at)
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        line = [l for l in text.split("```")[1].splitlines() if '"3":' in l][0]
        self.assertIn("state: auto_approved", line)
        self.assertIn("by: script", line)
        # provenance audit trail written
        self.assertTrue((self.ws / ".pipeline" / "gate_checks.jsonl").exists())

    def test_check_surfaces_parseable_checker_hard_and_warn_counts(self):
        self.init_ws(mode="autonomous")
        checker_stdout = json.dumps({
            "ok": True,
            "verdict": "pass",
            "hard": [],
            "warn": [{"code": "synthetic_warning"}],
            "counts": {"hard": 0, "warn": 1, "extra": 99},
        })
        self._write_sim_gate(0, stdout=checker_stdout)

        payload, code = run("check", str(self.ws), "sane")

        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertEqual(payload["counts"], {"hard": 0, "warn": 1})
        receipt_path = self.ws / ".pipeline" / "gate_checks.jsonl"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(receipt["counts"], {"hard": 0, "warn": 1})

    def test_check_reject_on_nonzero_exit(self):
        self.init_ws(mode="autonomous")
        self._write_sim_gate(3)
        payload, code = run("check", str(self.ws), "sane")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertEqual(payload["by"], "script")
        self.assertIn("3", payload["reason"])
        self.assertEqual(payload["exit"], 3)
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        line = [l for l in text.split("```")[1].splitlines() if '"3":' in l][0]
        self.assertIn("state: rejected", line)

    def test_check_never_writes_approved(self):
        self.init_ws(mode="autonomous")
        self._write_sim_gate(0)
        payload, code = run("check", str(self.ws), "sane")
        self.assertNotEqual(payload["state"], "approved")
        self.assertEqual(payload["state"], "auto_approved")

    def test_check_null_checker_is_usage_error(self):
        # A script gate with checker: null must make `check` error, never pass.
        # The shipped graph no longer has one (layout is bound via
        # check_layout.py), so exercise the path with a synthetic graph on a
        # copied pipeline_ctl (stdlib-only, config resolved relative to the
        # script location).
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            shutil.copy2(SCRIPT, fake_scripts / "pipeline_ctl.py")
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text(
                'version: "0.6"\n'
                'stages:\n'
                '  - {id: "0", name: "intake", gate: null, playbook: "p0"}\n'
                '  - {id: "1", name: "plan", gate: {name: "orphan", '
                'type: "script", checker: null}, playbook: "p1"}\n',
                encoding="utf-8",
            )
            ws = root / "ws"
            fake = [sys.executable, str(fake_scripts / "pipeline_ctl.py")]
            env = {**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"}
            init = subprocess.run(
                [*fake, "init", str(ws), "--slug", "report-x",
                 "--mode", "autonomous", "--subject", "s", "--topic", "t",
                 "--form", "f.hwpx"],
                capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(
                json.loads(init.stdout.strip()).get("ok"), True, init.stdout)
            proc = subprocess.run(
                [*fake, "check", str(ws), "orphan"],
                capture_output=True, text=True, encoding="utf-8", env=env)
            payload = json.loads(proc.stdout.strip())
            self.assertEqual(proc.returncode, 2)
            self.assertFalse(payload["ok"])
            self.assertIn("orphan", payload["error"])
            text = (ws / "PIPELINE.md").read_text(encoding="utf-8")
            line = [l for l in text.split("```")[1].splitlines()
                    if '"1":' in l][0]
            self.assertIn("state: pending", line)

    def test_check_unknown_gate_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("check", str(self.ws), "does-not-exist")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])

    def test_check_human_gate_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("check", str(self.ws), "design")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("human", payload["error"].lower())

    def test_check_content_audit_gate_present_and_bound(self):
        # Stage 4.5 content_audit binds content_audit.py; running it against a
        # workspace with no bundle/content.md yields the composite checker's
        # usage exit (2) -> rejected (nonzero), never a silent pass.
        self.init_ws(mode="autonomous")
        payload, code = run("check", str(self.ws), "content_audit")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertIn("content_audit.py", " ".join(payload["checker_argv"]))

    def test_format_gate_requires_assembled_hwpx(self):
        self.init_ws(mode="autonomous")

        payload, code = run("check", str(self.ws), "format_check")

        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertEqual(payload["exit"], 3)
        self.assertIn("--require-output", payload["checker_argv"])

    def test_check_understand_night_requires_questions_and_records_pending(self):
        self.init_ws(mode="night")
        self._write_understanding_questions(with_answers=False)
        payload, code = run("check", str(self.ws), "understand")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertIn("check_understanding.py", " ".join(payload["checker_argv"]))
        provenance_path = self.ws / ".pipeline" / "understanding_check.json"
        self.assertTrue(provenance_path.exists())
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        self.assertTrue(provenance["answers_pending"])
        self.assertEqual(provenance["question_count"], 5)

    def test_check_understand_supervised_requires_answers(self):
        self.init_ws(mode="supervised")
        self._write_understanding_questions(with_answers=False)
        payload, code = run("check", str(self.ws), "understand")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertEqual(payload["exit"], 3)

        self._write_understanding_questions(with_answers=True)
        payload, code = run("check", str(self.ws), "understand")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        provenance = json.loads(
            (self.ws / ".pipeline" / "understanding_check.json").read_text(
                encoding="utf-8"))
        self.assertFalse(provenance["answers_pending"])


class TestScriptGateBlocksAllModes(PipelineCtlTestCase):
    """BLOCKER: a PENDING predecessor SCRIPT gate must block advancement in
    night/autonomous (not just supervised). Only human gates get the
    pending-blocks-supervised-only treatment."""

    def test_night_advance_past_pending_script_gate_refused(self):
        self.init_ws(mode="night")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        run("gate", str(self.ws), "design", "--mode", "night")  # human gate → auto
        run("advance", str(self.ws), "2.5", "--status", "done")
        # stage 2.5's 'layout' script gate is still pending (check never run);
        # advancing stage 3 in night must be refused.
        payload, code = run("advance", str(self.ws), "3", "--status", "in_progress")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("script gate", payload["error"].lower())

    def test_autonomous_advance_past_pending_script_gate_refused(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        run("gate", str(self.ws), "design", "--mode", "autonomous")
        run("advance", str(self.ws), "2.5", "--status", "done")
        payload, code = run("advance", str(self.ws), "3", "--status", "done")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("gate", payload["error"].lower())


class TestImportHasNoSideEffects(unittest.TestCase):
    """MAJOR fix: the Windows UTF-8 reexec used to run at import time (module
    top level), so `import pipeline_ctl` from another process/test relaunched
    the CLI as a subprocess and called sys.exit() as a side effect of the
    import — breaking any in-process use (e.g. studio/main.py or a future
    caller importing load_stages_config directly). The reexec must now only
    fire from `if __name__ == "__main__":`, never from a bare import.

    Runs in a fresh subprocess (not this test process's sys.modules) so the
    import is really exercised from a clean interpreter state, and asserts it
    completes fast and without spawning any child process."""

    def test_import_exposes_load_stages_config_without_side_effects(self):
        code = (
            "import sys, time; sys.path.insert(0, r'" + str(SCRIPT.parent) + "'); "
            "t0 = time.time(); "
            "import pipeline_ctl; "
            "elapsed = time.time() - t0; "
            "assert hasattr(pipeline_ctl, 'load_stages_config'), 'load_stages_config missing'; "
            "cfg = pipeline_ctl.load_stages_config(); "
            "assert isinstance(cfg, list) and cfg, 'load_stages_config returned empty/non-list'; "
            "assert elapsed < 5, f'import took {elapsed}s -- looks like it reexeced a subprocess'; "
            "print('OK')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": ""},  # force the reexec guard's env check to fail if reached
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        self.assertIn("OK", proc.stdout)

    def test_import_does_not_call_sys_exit(self):
        # A bare "import pipeline_ctl" must not raise SystemExit — if the
        # reexec block ran at import time it would sys.exit(returncode) right
        # inside the import statement.
        code = (
            "import sys; sys.path.insert(0, r'" + str(SCRIPT.parent) + "'); "
            "import pipeline_ctl; "
            "print('IMPORTED_OK')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        self.assertIn("IMPORTED_OK", proc.stdout)


class TestInitWritesPipelineVersion(PipelineCtlTestCase):
    def test_init_header_has_pipeline_version_0_6(self):
        self.init_ws(mode="autonomous")
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        self.assertIn('pipeline_version: "0.6"', header_part)
        # fence marker itself must stay v0.4 — studio/main.py reads it verbatim
        self.assertIn("# pipeline-state: v0.4", header_part)


class TestV05HeaderResumeCompat(PipelineCtlTestCase):
    """resume must keep working on pre-existing v0.5-shaped workspaces whose
    PIPELINE.md header has no pipeline_version key and no 2.5/5.7 stage rows
    (written before this kernel upgrade) — resume operates on the header's
    own rows, not the full v0.6 config's stage set."""

    V05_HEADER = '''```yaml
# pipeline-state: v0.4
slug: report-legacy-slug
mode: autonomous
subject: earth-science
topic: "레거시 주제"
form: templates/form.hwpx
updated: 2026-07-01T09:00:00
canonical_output: null
stages:
  "0":   {status: done, gate: null}
  "1":   {status: done, gate: null}
  "2":   {status: done, gate: {name: design, state: auto_approved, by: autonomous, at: 2026-07-01T09:01:00}}
  "3":   {status: in_progress, gate: null}
  "4":   {status: pending, gate: {name: draft, state: pending, by: null, at: null}}
  "5":   {status: pending, gate: null}
  "5.5": {status: pending, gate: {name: understand, state: pending, by: null, at: null}}
  "6":   {status: pending, gate: null}
```

# report-legacy-slug

| stage | label | status | gate | artifacts |
|---|---|---|---|---|
'''

    def _write_v05_ws(self):
        self.ws.mkdir(parents=True, exist_ok=True)
        (self.ws / "PIPELINE.md").write_text(self.V05_HEADER, encoding="utf-8")

    def test_resume_reports_stage_3_in_progress(self):
        self._write_v05_ws()
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["next_stage"], "3")
        self.assertFalse(payload["blocked"])

    def test_advance_stage_3_to_done_works_without_2_5_row(self):
        self._write_v05_ws()
        payload, code = run("advance", str(self.ws), "3", "--status", "done")
        self.assertEqual(code, 0, payload)
        payload, code = run("resume", str(self.ws))
        # stage 3 has no gate row in this legacy header (predates the script
        # gate), so resume should move straight to stage 4, not 2.5 (which
        # doesn't exist in this header at all) or fail.
        self.assertEqual(payload["next_stage"], "4")

    def test_invalidate_on_v05_header_does_not_crash_on_missing_2_5_5_7(self):
        self._write_v05_ws()
        payload, code = run("invalidate", str(self.ws), "--from", "3", "--reason", "legacy retest")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("2.5", payload["reset_stages"])
        self.assertNotIn("5.7", payload["reset_stages"])
        self.assertEqual(sorted(payload["reset_stages"]), sorted(["3", "4", "5", "5.5", "6"]))

    def test_gate_still_resolves_design_gate_on_v05_header(self):
        self._write_v05_ws()
        payload, code = run("gate", str(self.ws), "draft", "--mode", "autonomous")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")

    def test_header_missing_new_graph_gate_remains_legacy_tolerant(self):
        """A legacy Stage 6 gate:null is not awaiting the graph's new gate."""
        self._write_v05_ws()
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        text = text.replace('"3":   {status: in_progress, gate: null}',
                            '"3":   {status: done, gate: null}')
        text = text.replace(
            '"4":   {status: pending, gate: {name: draft, state: pending, by: null, at: null}}',
            '"4":   {status: done, gate: {name: draft, state: auto_approved, by: autonomous, at: 2026-07-01T09:02:00}}')
        text = text.replace('"5":   {status: pending, gate: null}',
                            '"5":   {status: done, gate: null}')
        text = text.replace(
            '"5.5": {status: pending, gate: {name: understand, state: pending, by: null, at: null}}',
            '"5.5": {status: done, gate: {name: understand, state: auto_approved, by: autonomous, at: 2026-07-01T09:03:00}}')
        pf.write_text(text, encoding="utf-8")

        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "6")
        self.assertFalse(payload["blocked"])
        payload, code = run("advance", str(self.ws), "6", "--status", "done")
        self.assertEqual(code, 0, payload)

    def test_header_without_5_3_resumes_directly_to_5_5(self):
        self._write_v05_ws()
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        text = text.replace('"3":   {status: in_progress, gate: null}',
                            '"3":   {status: done, gate: null}')
        text = text.replace(
            '"4":   {status: pending, gate: {name: draft, state: pending, by: null, at: null}}',
            '"4":   {status: done, gate: {name: draft, state: auto_approved, by: autonomous, at: 2026-07-01T09:02:00}}')
        text = text.replace('"5":   {status: pending, gate: null}',
                            '"5":   {status: done, gate: null}')
        pf.write_text(text, encoding="utf-8")

        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "5.5")
        self.assertNotIn('"5.3":', pf.read_text(encoding="utf-8"))


class TestGateRefusesScriptType(PipelineCtlTestCase):
    """BLOCKER 1: `gate <ws> <script_gate>` must be refused (usage error),
    never auto_approved — a script gate is only resolvable via `check`, which
    runs the bound checker. Applies in EVERY mode, including night."""

    def _assert_refused(self, gate_name, mode):
        payload, code = run("gate", str(self.ws), gate_name, "--mode", mode)
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertIn("script gate", payload["error"].lower())
        self.assertIn("check", payload["error"].lower())
        # the gate must remain pending — nothing auto_approved
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header = text.split("```")[1]
        for line in header.splitlines():
            if f"name: {gate_name}" in line:
                self.assertIn("state: pending", line)

    def test_gate_script_type_refused_night(self):
        self.init_ws(mode="night")
        self._assert_refused("sane", "night")

    def test_gate_script_type_refused_supervised(self):
        self.init_ws(mode="supervised")
        self._assert_refused("layout", "supervised")

    def test_gate_script_type_refused_autonomous(self):
        self.init_ws(mode="autonomous")
        self._assert_refused("content_audit", "autonomous")

    def test_gate_human_type_still_auto_approves_night(self):
        # regression guard: the script-gate refusal must not affect human gates.
        self.init_ws(mode="night")
        payload, code = run("gate", str(self.ws), "design", "--mode", "night")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")


class TestResumePendingScriptGateNight(PipelineCtlTestCase):
    """BLOCKER 2: resume on a stage sitting at awaiting_gate with a PENDING
    SCRIPT gate must return blocked:true + action_needed:'check' in
    night/autonomous (not blocked:false + action_needed:'gate')."""

    def _advance_to_2_5_awaiting(self, mode):
        self.init_ws(mode=mode)
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        # 2.5 has the 'layout' SCRIPT gate; move it to awaiting_gate
        run("advance", str(self.ws), "2.5", "--status", "awaiting_gate")

    def test_resume_night_pending_script_gate_blocked_needs_check(self):
        self._advance_to_2_5_awaiting("night")
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2.5")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload.get("action_needed"), "check")

    def test_resume_autonomous_pending_script_gate_blocked_needs_check(self):
        self._advance_to_2_5_awaiting("autonomous")
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2.5")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload.get("action_needed"), "check")

    def test_resume_night_pending_human_gate_still_needs_gate(self):
        # regression guard: a pending HUMAN gate keeps blocked:false + gate.
        self.init_ws(mode="night")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        payload, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["next_stage"], "2")
        self.assertFalse(payload["blocked"])
        self.assertEqual(payload.get("action_needed"), "gate")


class TestStagesConfigStrict(unittest.TestCase):
    """BLOCKER 3: STRICT stages.yaml parsing — a malformed row anywhere inside
    the stages list, or a duplicate id / gate name, is a HARD ERROR, never a
    silent skip that could drop a gate."""

    def _load_broken(self, yaml_text: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text(yaml_text, encoding="utf-8")
            code = (
                "import sys\n"
                f"sys.path.insert(0, r'{SCRIPT.parent}')\n"
                "import pipeline_ctl as pc\n"
                "try:\n"
                f"    rows = pc.load_stages_config(r'{fake_scripts / 'pipeline_ctl.py'}')\n"
                "    print('OK', [r['id'] for r in rows])\n"
                "except pc.StagesConfigError as e:\n"
                "    print('HARDERR', e)\n"
            )
            return subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
            )

    def test_mixed_valid_and_corrupt_rows_rejected(self):
        # A valid row followed by a line that is NOT an inline-map row must be
        # rejected (the old loader silently dropped the corrupt line, losing
        # every gate declared after it).
        proc = self._load_broken(
            'version: "0.6"\n'
            "stages:\n"
            '  - {id: "0", name: form_intake, gate: null, playbook: "playbooks/stage-0.md"}\n'
            "  this line is not a valid stage row\n"
            '  - {id: "1", name: research, gate: null, playbook: "playbooks/stage-1.md"}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)
        self.assertNotIn("OK", proc.stdout)

    def test_duplicate_stage_ids_rejected(self):
        proc = self._load_broken(
            'version: "0.6"\n'
            "stages:\n"
            '  - {id: "0", name: a, gate: null, playbook: "p"}\n'
            '  - {id: "0", name: b, gate: null, playbook: "p"}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)
        self.assertIn("duplicate", proc.stdout.lower())

    def test_duplicate_gate_names_rejected(self):
        proc = self._load_broken(
            'version: "0.6"\n'
            "stages:\n"
            '  - {id: "0", name: a, gate: {name: g, type: human}, playbook: "p"}\n'
            '  - {id: "1", name: b, gate: {name: g, type: human}, playbook: "p"}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)

    def test_bad_gate_type_rejected(self):
        proc = self._load_broken(
            'version: "0.6"\n'
            "stages:\n"
            '  - {id: "0", name: a, gate: {name: g, type: bogus}, playbook: "p"}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)

    def test_missing_playbook_rejected(self):
        proc = self._load_broken(
            'version: "0.6"\n'
            "stages:\n"
            '  - {id: "0", name: a, gate: null}\n'
        )
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("HARDERR", proc.stdout)

    def test_build_graph_registers_z1_script_gate_argv(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import pipeline_ctl
        rows = pipeline_ctl.load_stages_config()
        by_id = {str(row["id"]): row for row in rows}
        self.assertEqual(by_id["5.3"]["gate"], {
            "name": "format_check",
            "type": "script",
            "checker": [
                "python",
                "{PIPELINE_SCRIPTS}/verify_format.py",
                "{WS}",
                "--require-output",
            ],
        })
        self.assertEqual(by_id["5.5"]["gate"], {
            "name": "understand",
            "type": "script",
            "checker": [
                "python",
                "{REPORT_SCRIPTS}/check_understanding.py",
                "{WS}",
                "--out",
                "{WS}/.pipeline/understanding_check.json",
            ],
        })
        self.assertEqual(by_id["5.7"]["gate"], {
            "name": "final_panel",
            "type": "script",
            "checker": ["python", "{REPORT_SCRIPTS}/check_scorecard.py", "{WS}"],
        })
        self.assertEqual(by_id["6"]["gate"], {
            "name": "submission_preflight",
            "type": "script",
            "checker": ["python", "{PIPELINE_SCRIPTS}/submission_preflight.py", "{WS}"],
        })


class TestUnknownGraphRejectedOnLoad(PipelineCtlTestCase):
    """FINDING 1: a header `graph:` value outside {build, edit} is a HARD error
    on every load — never silently coerced to a default graph."""

    def _switch_graph(self, value):
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        self.assertIn('graph: "build"', text)
        pf.write_text(text.replace('graph: "build"', f'graph: "{value}"'),
                      encoding="utf-8")

    def test_resume_hard_errors_on_unknown_graph(self):
        self.init_ws(mode="autonomous")
        self._switch_graph("chaos")
        payload, code = run("resume", str(self.ws))
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("unknown graph", payload["error"].lower())
        self.assertIn("chaos", payload["error"])

    def test_advance_hard_errors_on_unknown_graph(self):
        self.init_ws(mode="autonomous")
        self._switch_graph("chaos")
        payload, code = run("advance", str(self.ws), "0", "--status", "in_progress")
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("unknown graph", payload["error"].lower())


class TestGateNotInGraphFailsClosed(PipelineCtlTestCase):
    """FINDING 2: a gate name present in the header but ABSENT from the selected
    graph must be refused (fail-closed) in gate/check/advance/resume — never
    treated as a human gate (which would let an autonomous run auto_approve a
    build script gate by switching the header to the edit graph)."""

    def _init_build_then_switch_to_edit(self, mode="autonomous"):
        self.init_ws(mode=mode)
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        self.assertIn('graph: "build"', text)
        pf.write_text(text.replace('graph: "build"', 'graph: "edit"'),
                      encoding="utf-8")

    def test_gate_on_gate_absent_from_graph_refused(self):
        # 'sane' is a build script gate; under graph=edit it does not exist.
        self._init_build_then_switch_to_edit()
        payload, code = run("gate", str(self.ws), "sane", "--mode", "autonomous")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertIn("not registered", payload["error"].lower())
        self.assertIn("edit", payload["error"])
        # gate must NOT have been auto_approved
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        line = [l for l in text.split("```")[1].splitlines() if "name: sane" in l][0]
        self.assertIn("state: pending", line)

    def test_check_on_gate_absent_from_graph_refused(self):
        self._init_build_then_switch_to_edit()
        payload, code = run("check", str(self.ws), "sane")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])

    def test_advance_fails_closed_when_predecessor_gate_absent_from_graph(self):
        # Header (build) stage 2 carries a pending 'design' gate; under graph=edit
        # stage 2 has no gate and 'design' is not a registered edit gate, so
        # resolving its type must fail-closed rather than default to human.
        self._init_build_then_switch_to_edit()
        payload, code = run("advance", str(self.ws), "2.5", "--status", "in_progress")
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("not registered", payload["error"].lower())

    def test_resume_fails_closed_when_awaiting_gate_absent_from_graph(self):
        # Put stage 2 at awaiting_gate on the build graph, then switch to edit:
        # resume reaches the pending 'design' gate whose type edit cannot resolve.
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "awaiting_gate")
        pf = self.ws / "PIPELINE.md"
        text = pf.read_text(encoding="utf-8")
        pf.write_text(text.replace('graph: "build"', 'graph: "edit"'),
                      encoding="utf-8")
        payload, code = run("resume", str(self.ws))
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("not registered", payload["error"].lower())


class TestCheckWorkspaceWithSpaces(PipelineCtlTestCase):
    """`check` must run the bound checker correctly when {WS} contains spaces
    (argv is passed as a list, not a shell string)."""

    def test_check_runs_with_spaces_in_workspace_path(self):
        spaced = self.root / "dir with spaces" / "report-spaced-slug"
        payload, code = run(
            "init", str(spaced),
            "--slug", "spaced-slug", "--mode", "autonomous",
            "--subject", "s", "--topic", "t", "--form", "f",
        )
        self.assertEqual(code, 0, payload)
        sim = spaced / "sim"
        sim.mkdir(parents=True, exist_ok=True)
        (sim / "gates.py").write_text(
            'print("{\\"ok\\": true}")\n', encoding="utf-8"
        )
        payload, code = run("check", str(spaced), "sane")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertIn("dir with spaces", " ".join(payload["checker_argv"]))


if __name__ == "__main__":
    unittest.main()


def _init_staleness_test_workspace(ws: Path) -> None:
    payload, code = run(
        'init', str(ws),
        '--slug', 'staleness-test', '--mode', 'autonomous',
        '--subject', 'test', '--topic', 'test', '--form', 'test.hwpx',
    )
    assert code == 0, payload


def _direct_resume_payload(monkeypatch, ws: Path) -> dict:
    captured = {}

    def capture_out(payload, code=0):
        captured.update(payload)
        raise SystemExit(code)

    monkeypatch.setattr(ctl, 'out', capture_out)
    with pytest.raises(SystemExit) as exc_info:
        ctl.cmd_resume(SimpleNamespace(workspace=str(ws)))
    assert exc_info.value.code == 0
    return captured


def test_resume_warns_when_installed_skills_are_stale(tmp_path, monkeypatch):
    ws = tmp_path / 'workspace'
    kernel_root = tmp_path / 'kernel'
    old_rev = '1111111111111111111111111111111111111111'
    new_rev = '2222222222222222222222222222222222222222'
    _init_staleness_test_workspace(ws)
    monkeypatch.setenv('RIGORLOOM_KERNEL_ROOT', str(kernel_root))
    monkeypatch.setattr(ctl, '_read_sync_receipt', lambda _root: {'kernel_rev': old_rev})
    monkeypatch.setattr(ctl, '_git_revision', lambda root: new_rev)

    payload = _direct_resume_payload(monkeypatch, ws)

    assert payload['warnings'] == [
        'WARN: skills copy synced from 1111111, kernel now at 2222222 '
        '— run sync_local.py to update'
    ]


def test_resume_has_no_staleness_warning_when_revisions_match(tmp_path, monkeypatch):
    ws = tmp_path / 'workspace'
    rev = '3333333333333333333333333333333333333333'
    _init_staleness_test_workspace(ws)
    monkeypatch.setenv('RIGORLOOM_KERNEL_ROOT', str(tmp_path / 'kernel'))
    monkeypatch.setattr(ctl, '_read_sync_receipt', lambda _root: {'kernel_rev': rev})
    monkeypatch.setattr(ctl, '_git_revision', lambda root: rev)

    payload = _direct_resume_payload(monkeypatch, ws)

    assert 'warnings' not in payload


@pytest.mark.parametrize('missing', ['receipt', 'kernel_root'])
def test_resume_staleness_check_is_noop_when_inputs_absent(
        tmp_path, monkeypatch, missing):
    ws = tmp_path / 'workspace'
    _init_staleness_test_workspace(ws)
    monkeypatch.setattr(
        ctl, '_read_sync_receipt',
        lambda _root: {} if missing == 'receipt' else {'kernel_rev': '1111111'},
    )
    if missing == 'receipt':
        monkeypatch.setenv('RIGORLOOM_KERNEL_ROOT', str(tmp_path / 'kernel'))
    else:
        monkeypatch.delenv('RIGORLOOM_KERNEL_ROOT', raising=False)

    def unexpected_git_lookup(root):
        raise AssertionError(f'unexpected git revision lookup: {root}')

    monkeypatch.setattr(ctl, '_git_revision', unexpected_git_lookup)

    payload = _direct_resume_payload(monkeypatch, ws)

    assert 'warnings' not in payload


# ── reopen / amend-close (post-done amendment transitions, design slice 1) ──


class AmendmentTestCase(PipelineCtlTestCase):
    """Shared fixture: a private profile root with an operator receipt key,
    plus header-fabrication helpers (tests fabricate done states directly —
    walking every real gate is the gates' own tests' job)."""

    def setUp(self):
        super().setUp()
        self.profile_root = self.root / "profile"
        (self.profile_root / "keys").mkdir(parents=True)
        self.key_path = self.profile_root / "keys" / "render_cert.key"
        self.key_path.write_bytes(b"test-amendment-receipt-key-32byt")
        os.chmod(self.key_path, 0o600)
        self._environment = mock.patch.dict(
            os.environ, {"RIGORLOOM_PROFILE_ROOT": str(self.profile_root)})
        self._environment.start()

    def tearDown(self):
        self._environment.stop()
        super().tearDown()

    def _hdr(self) -> dict:
        return ctl.load_header(self.ws)[3]

    def _edit(self, fn) -> None:
        text, start, end, hdr = ctl.load_header(self.ws)
        fn(hdr)
        ctl.save_header(self.ws, text, start, end, hdr)

    def _mark_done(self, stage, gate_at="2026-08-01T00:00:00"):
        def fn(hdr):
            st = hdr["stages"][stage]
            st["status"] = "done"
            if st.get("gate"):
                st["gate"].update(state="auto_approved", by="script", at=gate_at)
        self._edit(fn)

    def _mark_all_done(self):
        def fn(hdr):
            for st in hdr["stages"].values():
                st["status"] = "done"
                if st.get("gate"):
                    st["gate"].update(
                        state="auto_approved", by="script",
                        at="2026-08-01T00:00:00")
        self._edit(fn)

    def _set_canonical(self, rel="output/final.hwpx", content=b"final v1"):
        target = self.ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self._edit(lambda hdr: hdr.__setitem__("canonical_output", rel))
        return target

    def _write_sim_gate(self, exit_code=0):
        gates = self.ws / "sim" / "gates.py"
        gates.parent.mkdir(parents=True, exist_ok=True)
        gates.write_text(
            "import json, sys\n"
            "print(json.dumps({'ok': True, 'hard': [], 'warn': []}))\n"
            f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )

    def _reopen(self, stage="3", reason="operator: sim rework"):
        return run("reopen", str(self.ws), stage, "--reason", reason)

    def _open_receipt_paths(self, amend_id="A1"):
        return sorted((self.ws / ".pipeline" / "receipts").glob(
            f"amendment-{amend_id}-open-*.json"))


class TestReopen(AmendmentTestCase):
    def test_reopen_done_stage_opens_amendment_and_invalidates_pointer(self):
        self.init_ws()
        self._mark_done("3")
        self._set_canonical(content=b"final v1")
        payload, code = self._reopen()
        self.assertEqual(code, 0, payload)
        amend = payload["amendment"]
        self.assertEqual(amend["id"], "A1")
        self.assertEqual(amend["scope"], ["3"])
        self.assertEqual(amend["status"], "open")
        self.assertIsNone(amend["closed_at"])
        self.assertIsNone(amend["artifact_after"])
        self.assertEqual(amend["gates_rerun"], [])
        self.assertEqual(amend["artifact_before"],
                         hashlib.sha256(b"final v1").hexdigest())
        self.assertTrue(payload["canonical_invalidated"])

        hdr = self._hdr()
        self.assertEqual(hdr["stages"]["3"]["status"], "amending")
        self.assertEqual(hdr["stages"]["3"]["gate"]["state"], "pending")
        # append-only honesty: pointer value preserved, marker added
        self.assertEqual(hdr["canonical_output"], "output/final.hwpx")
        self.assertEqual(hdr["canonical_invalidated_by"], "A1")
        self.assertEqual(len(hdr["amendments"]), 1)
        self.assertEqual(hdr["amendments"][0]["reason"], "operator: sim rework")

        receipts = self._open_receipt_paths()
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        ok, why = ctl.verify_amendment_receipt(receipt)
        self.assertTrue(ok, why)

    def test_reopen_without_canonical_pointer_skips_invalidation(self):
        self.init_ws()
        self._mark_done("3")
        payload, code = self._reopen()
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["canonical_invalidated"])
        self.assertIsNone(payload["amendment"]["artifact_before"])
        self.assertNotIn("canonical_invalidated_by", self._hdr())

    def test_reopen_non_done_stage_is_usage_error(self):
        self.init_ws()
        payload, code = self._reopen("1")
        self.assertEqual(code, 2)
        self.assertIn("only done", payload["error"])

    def test_reopen_unknown_stage_is_usage_error(self):
        self.init_ws()
        payload, code = self._reopen("99")
        self.assertEqual(code, 2)

    def test_reopen_blank_reason_is_usage_error(self):
        self.init_ws()
        self._mark_done("3")
        payload, code = run("reopen", str(self.ws), "3", "--reason", "   ")
        self.assertEqual(code, 2)
        self.assertEqual(self._hdr()["stages"]["3"]["status"], "done")

    def test_reopen_double_open_on_same_stage_refused(self):
        self.init_ws()
        self._mark_done("3")
        _, code = self._reopen()
        self.assertEqual(code, 0)
        payload, code = self._reopen()
        self.assertEqual(code, 2)
        self.assertEqual(len(self._hdr()["amendments"]), 1)

    def test_reopen_ids_increment_across_amendments(self):
        self.init_ws()
        self._mark_done("3")
        self._mark_done("2.5")
        p1, c1 = self._reopen("3")
        p2, c2 = run("reopen", str(self.ws), "2.5", "--reason", "layout rework")
        self.assertEqual((c1, c2), (0, 0), (p1, p2))
        self.assertEqual(p1["amendment"]["id"], "A1")
        self.assertEqual(p2["amendment"]["id"], "A2")
        hdr = self._hdr()
        self.assertEqual([a["id"] for a in hdr["amendments"]], ["A1", "A2"])
        self.assertEqual(hdr["stages"]["2.5"]["status"], "amending")

    def test_reopen_without_key_mutates_nothing(self):
        self.init_ws()
        self._mark_done("3")
        with mock.patch.dict(os.environ):
            del os.environ["RIGORLOOM_PROFILE_ROOT"]
            payload, code = self._reopen()
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        hdr = self._hdr()
        self.assertEqual(hdr["stages"]["3"]["status"], "done")
        self.assertNotIn("amendments", hdr)
        self.assertEqual(self._open_receipt_paths(), [])


class TestAmendClose(AmendmentTestCase):
    def _reopen_stage3_with_canonical(self):
        self.init_ws()
        self._mark_done("3")
        target = self._set_canonical(content=b"final v1")
        payload, code = self._reopen()
        self.assertEqual(code, 0, payload)
        return target

    def _rerun_sane_green(self):
        self._write_sim_gate(0)
        payload, code = run("check", str(self.ws), "sane")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")

    def test_full_lifecycle_reopen_rerun_close(self):
        target = self._reopen_stage3_with_canonical()
        # rework: artifact changes, then the reopened stage's gate re-runs green
        target.write_bytes(b"final v2 reworked")
        self._rerun_sane_green()

        payload, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 0, payload)
        closed = payload["amendment"]
        self.assertEqual(closed["status"], "closed")
        self.assertIsNotNone(closed["closed_at"])
        self.assertEqual(closed["gates_rerun"], ["sane"])
        self.assertEqual(closed["artifact_after"],
                         hashlib.sha256(b"final v2 reworked").hexdigest())
        self.assertNotEqual(closed["artifact_after"], closed["artifact_before"])

        hdr = self._hdr()
        self.assertEqual(hdr["stages"]["3"]["status"], "done")
        self.assertNotIn("canonical_invalidated_by", hdr)
        self.assertEqual(hdr["amendments"][0]["status"], "closed")
        close_receipts = sorted((self.ws / ".pipeline" / "receipts").glob(
            "amendment-A1-close-*.json"))
        self.assertEqual(len(close_receipts), 1)
        receipt = json.loads(close_receipts[0].read_text(encoding="utf-8"))
        ok, why = ctl.verify_amendment_receipt(receipt)
        self.assertTrue(ok, why)

        # closing an already-closed amendment is a usage error
        payload, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 2)
        self.assertIn("already closed", payload["error"])

    def test_amend_close_unknown_id_is_usage_error(self):
        self.init_ws()
        payload, code = run("amend-close", str(self.ws), "A9")
        self.assertEqual(code, 2)
        self.assertIn("unknown amendment", payload["error"])

    def test_amend_close_refuses_until_gates_rerun_green(self):
        self._reopen_stage3_with_canonical()
        payload, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertTrue(any("sane" in f for f in payload["failures"]), payload)
        self.assertEqual(self._hdr()["amendments"][0]["status"], "open")

    def test_amend_close_refuses_green_recorded_before_reopen(self):
        self._reopen_stage3_with_canonical()

        def stale_green(hdr):
            hdr["stages"]["3"]["gate"].update(
                state="auto_approved", by="script", at="2020-01-01T00:00:00")
        self._edit(stale_green)
        payload, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertTrue(
            any("before the amendment opened" in f for f in payload["failures"]),
            payload)

    def test_amend_close_refuses_tampered_receipt(self):
        self._reopen_stage3_with_canonical()
        receipt_path = self._open_receipt_paths()[0]
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload["amendment"]["reason"] = "benign-looking edit"
        receipt_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("failed verification", result["error"])

    def test_amend_close_refuses_missing_receipt(self):
        self._reopen_stage3_with_canonical()
        self._open_receipt_paths()[0].unlink()
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("no signed open receipt", result["error"])

    def test_amend_close_refuses_postdated_header_amendment(self):
        self._reopen_stage3_with_canonical()

        def postdate(hdr):
            hdr["amendments"][0]["opened_at"] = "2030-01-01T00:00:00"
        self._edit(postdate)
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("does not match its signed open receipt", result["error"])

    def test_amend_close_requires_redesignated_pointer(self):
        self._reopen_stage3_with_canonical()
        self._rerun_sane_green()
        self._edit(lambda hdr: hdr.__setitem__("canonical_output", None))
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("re-designated", result["error"])

    def test_amend_close_refuses_missing_canonical_target(self):
        target = self._reopen_stage3_with_canonical()
        self._rerun_sane_green()
        target.unlink()
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("check_canonical", result["error"])

    def test_amend_close_refuses_contradictory_assembly_verdict(self):
        self._reopen_stage3_with_canonical()
        self._rerun_sane_green()
        verdict = self.ws / "output" / "verdict_v06.json"
        verdict.write_text(
            json.dumps({"converged": True, "status": "escalate_human"}),
            encoding="utf-8")
        result, code = run("amend-close", str(self.ws), "A1")
        self.assertEqual(code, 1)
        self.assertIn("verdict_schema", result["error"])


class TestAmendmentStateMachineInteractions(AmendmentTestCase):
    def test_resume_blocked_by_open_amendment(self):
        self.init_ws()
        self._mark_all_done()
        payload, code = self._reopen()
        self.assertEqual(code, 0, payload)
        resumed, code = run("resume", str(self.ws))
        self.assertEqual(code, 0, resumed)
        self.assertIsNone(resumed["next_stage"])
        self.assertTrue(resumed["blocked"])
        self.assertEqual(resumed["open_amendments"], ["A1"])

    def test_advance_refuses_amending_stage(self):
        self.init_ws()
        self._mark_done("3")
        self._reopen()
        payload, code = run("advance", str(self.ws), "3", "--status", "done")
        self.assertEqual(code, 1)
        self.assertIn("illegal transition", payload["error"])

    def test_invalidate_refuses_open_amendment_scope(self):
        self.init_ws()
        self._mark_done("3")
        self._reopen()
        payload, code = run("invalidate", str(self.ws), "--from", "2")
        self.assertEqual(code, 1)
        self.assertEqual(payload["open_amendments"], ["A1"])
        # invalidating strictly LATER stages (not covering "3") is still fine
        payload, code = run("invalidate", str(self.ws), "--from", "4")
        self.assertEqual(code, 0, payload)


class TestAmendmentSchemaUnit(unittest.TestCase):
    def test_amendment_yaml_round_trip(self):
        hdr = {
            "slug": "x", "mode": "night",
            "stages": {"0": {"status": "done", "gate": None}},
            "amendments": [
                {"id": "A1", "opened_at": "2026-08-06T01:00:00",
                 "reason": 'operator: subhead, "density" 재작업',
                 "scope": ["5"], "status": "open", "closed_at": None,
                 "artifact_before": "ab" * 32, "artifact_after": None,
                 "gates_rerun": []},
                {"id": "A2", "opened_at": "2026-08-06T02:00:00",
                 "reason": "figure restyle", "scope": ["2.5"],
                 "status": "closed", "closed_at": "2026-08-06T03:00:00",
                 "artifact_before": None, "artifact_after": "cd" * 32,
                 "gates_rerun": ["layout"]},
            ],
        }
        body = ctl.render_yaml_body(hdr, ctl._BUILD_GRAPH)
        parsed = ctl.parse_yaml_header(body)
        self.assertEqual(parsed["amendments"], hdr["amendments"])
        # and a second round trip is stable
        body2 = ctl.render_yaml_body(parsed, ctl._BUILD_GRAPH)
        self.assertEqual(body, body2)

    def test_header_without_amendments_has_no_amendments_key(self):
        hdr = {"slug": "x", "mode": "night",
               "stages": {"0": {"status": "pending", "gate": None}}}
        body = ctl.render_yaml_body(hdr, ctl._BUILD_GRAPH)
        self.assertNotIn("amendments", body)
        self.assertNotIn("amendments", ctl.parse_yaml_header(body))

    def test_unknown_amendment_status_coerces_to_open(self):
        # fail-closed: a mangled status must block (open), never read closed
        body = ("# pipeline-state: v0.4\nslug: x\nstages:\n"
                '  "0":   {status: done, gate: null}\n'
                "amendments:\n"
                '  - {id: A1, opened_at: "t", reason: "r", scope: ["0"], '
                "status: garbled, closed_at: null, artifact_before: null, "
                "artifact_after: null, gates_rerun: []}\n")
        parsed = ctl.parse_yaml_header(body)
        self.assertEqual(parsed["amendments"][0]["status"], "open")


class TestAmendmentReceiptUnit(unittest.TestCase):
    KEY = b"0123456789abcdef0123456789abcdef"

    def _signed(self):
        payload = {
            "schema": ctl.AMENDMENT_RECEIPT_SCHEMA,
            "transition": "open",
            "workspace_slug": "test-slug",
            "amendment": {"id": "A1", "opened_at": "2026-08-06T01:00:00",
                          "reason": "r", "scope": ["3"], "status": "open",
                          "closed_at": None, "artifact_before": None,
                          "artifact_after": None, "gates_rerun": []},
            "recorded_at": "2026-08-06T01:00:00",
        }
        return ctl.sign_amendment_receipt(payload, self.KEY)

    def test_signed_receipt_verifies(self):
        ok, why = ctl.verify_amendment_receipt(self._signed(), key=self.KEY)
        self.assertTrue(ok, why)

    def test_tampered_payload_fails_digest(self):
        receipt = self._signed()
        receipt["amendment"]["opened_at"] = "2030-01-01T00:00:00"
        ok, why = ctl.verify_amendment_receipt(receipt, key=self.KEY)
        self.assertFalse(ok)
        self.assertIn("digest", why)

    def test_digest_refix_without_key_fails_hmac(self):
        receipt_sign = ctl._sibling("receipt_sign")
        receipt = self._signed()
        receipt["amendment"]["opened_at"] = "2030-01-01T00:00:00"
        receipt[ctl.AMENDMENT_RECEIPT_DIGEST_FIELD] = hashlib.sha256(
            receipt_sign.canonical_json_bytes(
                receipt,
                omit_fields=(ctl.AMENDMENT_RECEIPT_DIGEST_FIELD,
                             ctl.AMENDMENT_RECEIPT_HMAC_FIELD))
        ).hexdigest()
        ok, why = ctl.verify_amendment_receipt(receipt, key=self.KEY)
        self.assertFalse(ok)
        self.assertIn("HMAC", why)

    def test_wrong_key_fails_hmac(self):
        ok, why = ctl.verify_amendment_receipt(
            self._signed(), key=b"another-key-entirely-32-bytes!!!")
        self.assertFalse(ok)
        self.assertIn("HMAC", why)

    def test_wrong_schema_rejected(self):
        receipt = self._signed()
        receipt["schema"] = "something-else/v9"
        ok, why = ctl.verify_amendment_receipt(receipt, key=self.KEY)
        self.assertFalse(ok)
        self.assertIn("schema", why)
