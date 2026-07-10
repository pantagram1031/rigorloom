"""Tests for pipeline_ctl.py — run offline with `python test_pipeline_ctl.py`
or `pytest test_pipeline_ctl.py`. Uses tmp dirs only; no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def init_ws(self, mode="autonomous"):
        payload, code = run(
            "init", str(self.ws),
            "--slug", "test-slug", "--mode", mode,
            "--subject", "earth-science", "--topic", "테스트 주제",
            "--form", "templates/form.hwpx",
        )
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
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

    def test_advance_allowed_autonomous_despite_pending_gate(self):
        # In autonomous mode a pending gate on an earlier stage does not by
        # itself block (only 'rejected' blocks universally); pending only
        # blocks in supervised mode per contract §2 rule 4.
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        payload, code = run("advance", str(self.ws), "3", "--status", "in_progress")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])


class TestGate(PipelineCtlTestCase):
    def test_gate_approved_only_via_approvals_md(self):
        self.init_ws(mode="supervised")
        # no APPROVALS.md yet -> supervised refuses
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
        self.assertEqual(sorted(payload["reset_stages"]), sorted(["3", "4", "5", "5.5", "5.7", "6"]))

        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        self.assertIn('"0":', header_part)
        # stage 0/1/2 should remain done
        for s in ["0", "1", "2"]:
            line = [l for l in header_part.splitlines() if f'"{s}":' in l][0]
            self.assertIn("status: done", line)
        # stage 3 and later should be pending
        for s in ["3", "4", "5", "5.5", "5.7", "6"]:
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
    """Config loader: present / missing / corrupt stages.yaml."""

    def _reload_with_config_at(self, tmp_root: Path, script_dir: Path):
        """Import pipeline_ctl fresh (subprocess, to dodge the module-level
        Windows UTF-8 re-exec guard) with the script living at script_dir, so
        load_stages_config() looks for <script_dir>/../references/stages.yaml."""
        script = (
            "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
            "print(pc.load_stages_config(r'%s'))"
        ) % (str(SCRIPT.parent), str(script_dir / "pipeline_ctl.py"))
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
        )
        return proc

    def test_present_config_parses_all_rows(self):
        real_cfg = SCRIPT.parent.parent / "references" / "stages.yaml"
        self.assertTrue(real_cfg.exists(), "references/stages.yaml must exist")
        import importlib.util
        spec = importlib.util.spec_from_file_location("pipeline_ctl_probe", SCRIPT)
        # Avoid triggering the module-level re-exec guard during import by
        # asserting the env flag first (subprocess already sets it for the
        # rest of this test class; for this in-process probe we only touch
        # pure functions that don't run at import-time re-exec branches).
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, r'%s'); import pipeline_ctl as pc; "
                 "rows = pc.load_stages_config(); "
                 "ids = [r['id'] for r in rows]; "
                 "assert ids == ['0','1','2','2.5','3','4','5','5.5','5.7','6'], ids; "
                 "print('OK', len(rows))" % str(SCRIPT.parent)],
                capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "_PIPELINE_CTL_UTF8_REEXEC": "1"},
            )
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("OK 10", proc.stdout)

    def test_missing_config_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            # no references/ dir at all next to fake_scripts's parent
            proc = self._reload_with_config_at(root, fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("'id': '2.5'", proc.stdout)
            self.assertIn("'id': '5.7'", proc.stdout)

    def test_corrupt_config_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text(
                "this is not: [valid, {yaml stages\n???", encoding="utf-8"
            )
            proc = self._reload_with_config_at(root, fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("'id': '2.5'", proc.stdout)
            self.assertIn("'id': '5.7'", proc.stdout)

    def test_empty_stages_list_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_refs = root / "references"
            fake_refs.mkdir()
            (fake_refs / "stages.yaml").write_text("version: \"0.6\"\nstages:\n", encoding="utf-8")
            proc = self._reload_with_config_at(root, fake_scripts)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIn("'id': '0'", proc.stdout)


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


class TestScriptGate(PipelineCtlTestCase):
    """gate <ws> <name> --script-exit <code>: 0 -> auto_approved (script),
    nonzero -> rejected + reason. Never touches APPROVALS.md."""

    def test_script_exit_zero_auto_approves(self):
        self.init_ws(mode="autonomous")
        run("advance", str(self.ws), "0", "--status", "done")
        run("advance", str(self.ws), "1", "--status", "done")
        run("advance", str(self.ws), "2", "--status", "done")
        run("gate", str(self.ws), "design", "--mode", "autonomous")
        payload, code = run("gate", str(self.ws), "layout", "--script-exit", "0")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")
        self.assertEqual(payload["by"], "script")
        self.assertEqual(payload.get("detail"), "script")

    def test_script_exit_nonzero_rejects_with_reason(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "sane", "--script-exit", "1")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "rejected")
        self.assertIn("1", payload["reason"])
        self.assertEqual(payload["by"], "script")

    def test_script_gate_never_writes_approved(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "sane", "--script-exit", "0")
        self.assertEqual(code, 0, payload)
        self.assertNotEqual(payload["state"], "approved")
        self.assertEqual(payload["state"], "auto_approved")

    def test_script_gate_ignores_approvals_md(self):
        # even if APPROVALS.md has a rejection line, --script-exit 0 wins —
        # script gates are resolved purely by exit code, never by human text.
        self.init_ws(mode="autonomous")
        (self.ws / "APPROVALS.md").write_text("sane: rejected — do not trust\n", encoding="utf-8")
        payload, code = run("gate", str(self.ws), "sane", "--script-exit", "0")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")

    def test_script_gate_persisted_in_header(self):
        self.init_ws(mode="autonomous")
        run("gate", str(self.ws), "sane", "--script-exit", "7")
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        line = [l for l in header_part.splitlines() if '"3":' in l][0]
        self.assertIn("state: rejected", line)
        self.assertIn("by: script", line)

    def test_gate_missing_mode_and_script_exit_is_usage_error(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "design")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])

    def test_script_exit_refused_on_human_gate_design(self):
        # BLOCK: --script-exit must never bypass a human gate (design/draft/
        # understand are type "human" per stages.yaml/FALLBACK_STAGES_CONFIG).
        # Without the guard, a script call could silently auto_approve a gate
        # meant to require an APPROVALS.md line from a person.
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "design", "--script-exit", "0")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("human gate", payload["error"])
        self.assertIn("script-exit", payload["error"])

        # must not have mutated the gate state at all
        text = (self.ws / "PIPELINE.md").read_text(encoding="utf-8")
        header_part = text.split("```")[1]
        line = [l for l in header_part.splitlines() if '"2":' in l][0]
        self.assertNotIn("auto_approved", line)

    def test_script_exit_refused_on_human_gate_draft(self):
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "draft", "--script-exit", "1")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])

    def test_script_exit_still_works_on_script_gates_layout_and_sane(self):
        # Regression guard: the human-gate refusal must not collaterally
        # break the legitimate script-gate path (layout/sane are type "script").
        self.init_ws(mode="autonomous")
        payload, code = run("gate", str(self.ws), "sane", "--script-exit", "0")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")

        payload, code = run("gate", str(self.ws), "layout", "--script-exit", "0")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "auto_approved")


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


if __name__ == "__main__":
    unittest.main()
