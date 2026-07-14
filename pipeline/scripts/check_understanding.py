#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate Stage 5.5 questions and supervised operator answers.

Exit 0 = pass, 3 = HARD finding, 2 = usage error. Autonomous/night runs still
require five questions and emit ``answers_pending`` provenance for delivery.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


QUESTION_RE = re.compile(r"(?ms)^\s*(\d+)[.)]\s+(.+?)(?=^\s*\d+[.)]\s+|\Z)")
ANSWER_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:\uB2F5|\uB2F5\uBCC0|answer)\s*[:\uFF1A]\s*(.*)$")
VALID_MODES = {"supervised", "autonomous", "night"}
PLACEHOLDER_QUESTIONS = {
    "", "?", "...", "todo", "tbd", "placeholder", "question", "질문", "미정",
}


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _scan_scalar(path: Path, key: str):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*([^#\r\n]+)", text)
    if not match:
        return None
    return match.group(1).strip().strip("\"'")


def _mode(ws: Path) -> str:
    return (_scan_scalar(ws / "PIPELINE.md", "mode")
            or _scan_scalar(ws / "request.yaml", "mode")
            or "supervised").lower()


def _answer_text(block: str) -> str:
    match = ANSWER_RE.search(block)
    if not match:
        return ""
    tail = match.group(1) + block[match.end():]
    tail = re.sub(r"[`*_>#\-]", " ", tail)
    return re.sub(r"\s+", " ", tail).strip()


def _question_text(block: str) -> str:
    answer = ANSWER_RE.search(block)
    question = block[:answer.start()] if answer else block
    question = re.sub(r"\[[^\]]+\]", " ", question)
    question = re.sub(r"[\`*_>#]", " ", question)
    return re.sub(r"\s+", " ", question).strip()


def _well_formed_question(block: str) -> bool:
    question = _question_text(block)
    normalized = re.sub(r"[^\w]+", " ", question, flags=re.UNICODE).strip().casefold()
    if normalized in PLACEHOLDER_QUESTIONS:
        return False
    if "?" not in question and "\uFF1F" not in question:
        return False
    visible = "".join(char for char in question if char.isalnum())
    return len(visible) >= 12


def check(workspace: str | Path) -> tuple[dict, int]:
    ws = Path(workspace)
    hard: list[dict] = []
    warn: list[dict] = []
    mode = _mode(ws)
    questions_path = ws / "output" / "QUESTIONS.md"
    try:
        text = questions_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        text = ""
        hard.append({"code": "U0", "msg": f"QUESTIONS.md unreadable: {exc}",
                     "at": "output/QUESTIONS.md"})

    matches = list(QUESTION_RE.finditer(text))
    numbers = [int(match.group(1)) for match in matches]
    if numbers != [1, 2, 3, 4, 5]:
        hard.append({
            "code": "U1",
            "msg": "QUESTIONS.md must contain exactly five numbered questions (1-5)",
            "at": f"output/QUESTIONS.md numbers={numbers}",
        })

    malformed_questions = [
        index + 1 for index, match in enumerate(matches)
        if not _well_formed_question(match.group(2))
    ]
    if malformed_questions:
        hard.append({
            "code": "U1",
            "msg": "questions must be substantive interrogative text, not placeholders",
            "at": f"output/QUESTIONS.md malformed questions={malformed_questions}",
        })

    answers = [_answer_text(match.group(2)) for match in matches]
    answer_count = sum(bool(answer) for answer in answers)
    answers_pending = answer_count < 5
    if mode not in VALID_MODES:
        hard.append({"code": "U0", "msg": f"unknown workspace mode: {mode!r}",
                     "at": "PIPELINE.md mode"})
    elif mode == "supervised" and answers_pending:
        missing = [index + 1 for index, answer in enumerate(answers[:5]) if not answer]
        missing.extend(range(len(answers) + 1, 6))
        hard.append({
            "code": "U2",
            "msg": "supervised understanding gate requires five non-empty answers",
            "at": f"output/QUESTIONS.md missing answers={sorted(set(missing))}",
        })

    verdict = {
        "ok": not hard,
        "workspace": str(ws),
        "mode": mode,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "question_count": len(matches),
        "well_formed_question_count": len(matches) - len(malformed_questions),
        "answer_count": answer_count,
        "answers_pending": answers_pending,
        "hard": hard,
        "warn": warn,
        "counts": {"hard": len(hard), "warn": len(warn)},
        "verdict": "pass" if not hard else "fail",
    }
    return verdict, 0 if not hard else 3


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description="validate five understanding questions and answers")
    parser.add_argument("workspace")
    parser.add_argument("--out", default=None,
                        help="write JSON provenance (normally .pipeline/understanding_check.json)")
    args = parser.parse_args(argv)
    verdict, code = check(args.workspace)
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
