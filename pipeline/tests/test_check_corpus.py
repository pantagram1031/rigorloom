"""Synthetic tests for the optional Stage 6 corpus consistency checker."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_corpus.py"
_spec = importlib.util.spec_from_file_location("check_corpus", SCRIPT)
check_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_corpus)


def _write_report(
    root: Path,
    workspace_name: str,
    content: str,
    *,
    student_id: str | None = "student-a",
    student_name: str | None = None,
) -> Path:
    workspace = root / workspace_name
    bundle = workspace / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "content.md").write_text(content, encoding="utf-8")
    identity_lines = []
    if student_id is not None:
        identity_lines.append(f'student_id: "{student_id}"')
    if student_name is not None:
        identity_lines.append(f'student_name: "{student_name}"')
    if identity_lines:
        (workspace / "request.yaml").write_text(
            "\n".join(identity_lines) + "\n", encoding="utf-8"
        )
    return workspace


def _codes(verdict: dict) -> set[str]:
    return {finding["code"] for finding in verdict["warn"]}


def test_constant_conflict_across_synthetic_reports_is_warn(tmp_path):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nSpring constant = 10.0 N/m.\n",
    )
    _write_report(
        corpus,
        "report-prior",
        "# Earlier synthetic result\nSpring constant = 12.0 N/m.\n",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    conflicts = [
        item for item in verdict["warn"]
        if item["code"] == "cross_report_constant_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["source_workspace"] == "report-prior"


def test_consistent_constant_is_clean(tmp_path):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nOscillation period = 2.00 s.\n",
    )
    _write_report(
        corpus,
        "report-prior",
        "# Earlier synthetic result\nOscillation period = 2.01 s.\n",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    assert "cross_report_constant_conflict" not in _codes(verdict)


def test_reused_twelve_token_passage_is_warn_with_source(tmp_path):
    corpus = tmp_path / "private-corpus"
    shared = (
        "Careful measurements revealed a stable pattern across repeated trials "
        "under identical laboratory conditions each morning"
    )
    current = _write_report(
        tmp_path,
        "report-current",
        f"# Analysis\n{shared} before the final comparison.\n",
    )
    _write_report(
        corpus,
        "report-source",
        f"# Findings\nThe earlier discussion noted that {shared} in the dataset.\n",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    reused = [item for item in verdict["warn"] if item["code"] == "reused_passage"]
    assert len(reused) == 1
    assert reused[0]["source_workspace"] == "report-source"
    assert "stable pattern" in reused[0]["snippet"]


def test_no_corpus_root_is_optional_noop(tmp_path, monkeypatch):
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic report\nA generic observation was recorded for review.\n",
    )
    monkeypatch.delenv("RIGORLOOM_CORPUS_ROOT", raising=False)

    verdict, code = check_corpus.check(current)

    assert code == 0
    assert verdict["hard"] == []
    assert verdict["warn"] == []
    assert verdict["verdict"] == "skipped"
    assert "optional" in verdict["note"].lower()


def test_career_track_conflict_is_warn(tmp_path):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Reflection\nCareer: materials engineering\n",
    )
    _write_report(
        corpus,
        "report-prior",
        "# Reflection\nCareer: ecological modeling\n",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    conflicts = [
        item for item in verdict["warn"]
        if item["code"] == "career_track_conflict"
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["source_workspace"] == "report-prior"


def test_environment_corpus_root_fallback(tmp_path, monkeypatch):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nReference level = 25.0 dB.\n",
    )
    _write_report(
        corpus,
        "report-prior",
        "# Earlier synthetic result\nReference level = 30.0 dB.\n",
    )
    monkeypatch.setenv("RIGORLOOM_CORPUS_ROOT", str(corpus))

    verdict, code = check_corpus.check(current)

    assert code == 0
    assert verdict["hard"] == []
    assert "cross_report_constant_conflict" in _codes(verdict)


def test_stage_6_wires_optional_advisory_corpus_check():
    playbook = (
        Path(__file__).parents[1] / "references" / "playbooks" / "stage-6.md"
    ).read_text(encoding="utf-8")

    assert "check_corpus.py <WS> --corpus-root <root>" in playbook
    assert "RIGORLOOM_CORPUS_ROOT" in playbook
    assert "WARN" in playbook
    assert playbook.index("check_corpus.py") < playbook.index("wiki_entry_template.md")


def test_different_student_prior_workspace_is_not_compared(tmp_path):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nSpring constant = 10.0 N/m.\n",
        student_id="student-a",
    )
    _write_report(
        corpus,
        "report-other-student",
        "# Earlier synthetic result\nSpring constant = 12.0 N/m.\n",
        student_id="student-b",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    assert "cross_report_constant_conflict" not in _codes(verdict)
    assert verdict["counts"]["prior_workspaces"] == 0


def test_current_workspace_without_identity_warns_and_compares_none(tmp_path):
    corpus = tmp_path / "private-corpus"
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nSpring constant = 10.0 N/m.\n",
        student_id=None,
    )
    _write_report(
        corpus,
        "report-prior",
        "# Earlier synthetic result\nSpring constant = 12.0 N/m.\n",
    )

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    assert "corpus_identity_unknown" in _codes(verdict)
    assert "cross_report_constant_conflict" not in _codes(verdict)
    assert verdict["counts"]["prior_workspaces"] == 0


def test_symlinked_child_outside_corpus_root_is_skipped(tmp_path):
    corpus = tmp_path / "private-corpus"
    corpus.mkdir()
    current = _write_report(
        tmp_path,
        "report-current",
        "# Synthetic result\nSpring constant = 10.0 N/m.\n",
    )
    outside = _write_report(
        tmp_path / "outside",
        "report-prior",
        "# Earlier synthetic result\nSpring constant = 12.0 N/m.\n",
    )
    linked = corpus / "linked-prior"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    verdict, code = check_corpus.check(current, corpus)

    assert code == 0
    assert verdict["hard"] == []
    assert "cross_report_constant_conflict" not in _codes(verdict)
    assert verdict["counts"]["prior_workspaces"] == 0
