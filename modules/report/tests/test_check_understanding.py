"""Tests for substantive Stage 5.5 understanding checks."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_understanding  # noqa: E402


QUESTIONS_ONLY = """# Stage 5.5 questions

1. **[derive]** Why does the integer index matter?
   What breaks in continuous time?

2. **[verify]** Why separate expected and measured values?

3. **[control]** Which variable stays fixed, and why?

4. **[limits]** Why is equality a boundary case?

5. **[next]** What question follows from this result?
"""


class CheckUnderstandingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "report-understanding"
        (self.ws / "output").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def set_mode(self, mode):
        (self.ws / "PIPELINE.md").write_text(
            f"```yaml\nmode: {mode}\nstages:\n```\n", encoding="utf-8")

    def test_supervised_five_questions_and_answers_pass(self):
        self.set_mode("supervised")
        parts = []
        for block in QUESTIONS_ONLY.split("\n\n"):
            if block[:1].isdigit():
                block += "\n   Answer: This answer explains the report in my own words."
            parts.append(block)
        (self.ws / "output" / "QUESTIONS.md").write_text(
            "\n\n".join(parts), encoding="utf-8")
        verdict, code = check_understanding.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["question_count"], 5)
        self.assertEqual(verdict["answer_count"], 5)
        self.assertFalse(verdict["answers_pending"])

    def test_supervised_missing_answer_fails(self):
        self.set_mode("supervised")
        (self.ws / "output" / "QUESTIONS.md").write_text(
            QUESTIONS_ONLY, encoding="utf-8")
        verdict, code = check_understanding.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(verdict["answers_pending"])
        self.assertTrue(any(item["code"] == "U2" for item in verdict["hard"]))

    def test_night_accepts_current_multiline_question_shape_and_marks_pending(self):
        self.set_mode("night")
        (self.ws / "output" / "QUESTIONS.md").write_text(
            QUESTIONS_ONLY, encoding="utf-8")
        verdict, code = check_understanding.check(self.ws)
        self.assertEqual(code, 0, verdict)
        self.assertEqual(verdict["question_count"], 5)
        self.assertTrue(verdict["answers_pending"])

    def test_night_still_requires_exactly_five_questions(self):
        self.set_mode("night")
        text = QUESTIONS_ONLY.rsplit("\n5.", 1)[0]
        (self.ws / "output" / "QUESTIONS.md").write_text(text, encoding="utf-8")
        verdict, code = check_understanding.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "U1" for item in verdict["hard"]))

    def test_night_rejects_placeholder_numbered_blocks(self):
        self.set_mode("night")
        (self.ws / "output" / "QUESTIONS.md").write_text(
            "1. TBD\n\n2. placeholder\n\n3. ?\n\n4. Question 4\n\n5. TODO\n",
            encoding="utf-8",
        )
        verdict, code = check_understanding.check(self.ws)
        self.assertEqual(code, 3, verdict)
        self.assertTrue(any(item["code"] == "U1" for item in verdict["hard"]))


if __name__ == "__main__":
    unittest.main()
