from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_t150_research_note_pins_the_closed_runtime_boundary():
    text = _read("docs/research/renderer-runtime-v2.md")
    for token in (
        "T150",
        "rigorloom/renderer-runtime-v2/v1",
        "renderer-runtime-v2",
        "rhwp_pdf",
        "export-pdf",
        "certificate.validation: not_run",
        "dependency_closure` is\n`unknown",
        "Equation-bearing HWPX is refused",
        "proof_grade` is `none",
        "submission_grade` is `false",
        "promotion` is `not_run",
        "CERTIFIED_PROOF_RELEASE_ENABLED",
        "certified_runtime_unbound",
        "new_report.py",
        "CP949",
        "windows_job_kill_on_close_v1",
        "posix_process_group_v1",
        "execution.descendant_containment",
        "execution.evidence_authentication",
        "not_established",
        "setsid()",
        "brokered",
        "filesystem",
        "network",
        "Receipt verification rebinds",
        "without authenticating",
        "child-process evidence",
        "producer host's local policy token",
        "accepts either\nclosed recorded token",
        "legacy `contained_child_v1` token is rejected",
    ):
        assert token in text
    lowered = text.casefold()
    for forbidden in (
        "c:\\users\\", "appdata", "tests/corpus", "private\\",
    ):
        assert forbidden not in lowered


def test_t150_routing_docs_repeat_quarantine_and_no_autoroute():
    paths = (
        "CHANGELOG.md",
        "docs/golden-path.md",
        "docs/trouble-table.md",
        "skill/SKILL.md",
        "skill/references/operations.md",
        "skill/references/platform-backends.md",
        "modules/report/references/playbooks/stage-5.md",
        "modules/report/references/playbooks/stage-6.md",
        "docs/research/renderer-runtime-v2.md",
    )
    combined = "\n".join(_read(path) for path in paths)
    for token in (
        "T150",
        "rigorloom/renderer-runtime-v2/v1",
        "renderer-runtime-v2",
        "rhwp_pdf",
        "dependency_closure",
        "equation_input_unsupported",
        "proof_grade",
        "submission_grade",
        "certified_runtime_unbound",
        "CERTIFIED_PROOF_RELEASE_ENABLED",
        "new_report",
        "no automatic",
    ):
        assert token in combined
    assert "proof_grade` is `none" in combined
    assert "submission_grade` is `false" in combined


def test_t154_docs_correct_platform_and_evidence_claims():
    research = _read("docs/research/renderer-runtime-v2.md")
    golden = _read("docs/golden-path.md")
    operations = _read("skill/references/operations.md")
    trouble = _read("docs/trouble-table.md")
    changelog = _read("CHANGELOG.md")
    combined = "\n".join((research, golden, operations, trouble, changelog))

    for token in (
        "windows_job_kill_on_close_v1",
        "posix_process_group_v1",
        "execution.descendant_containment",
        "execution.evidence_authentication",
        "not_established",
        "ordinary descendants",
        "setsid()",
        "brokered",
        "resource/filesystem/network",
        "does not authenticate",
        "proof `none`",
        "submission `false`",
        "promotion `not_run`",
    ):
        assert token in combined

    assert "process-tree containment" not in golden
    assert "process-tree containment" not in research
    assert "shared process-tree/TOCTOU" not in trouble
    assert "no source text/IDs/raw bytes/paths" in trouble
    assert trouble.index("| T154 |") < trouble.index("| T153 |")


def test_backend_table_does_not_promote_unreleased_advisory_proof():
    readme = _read("README.md")
    assert "Terminal grade is `none` for XML and LibreOffice" in readme
    assert "internal `advisory` candidate" in readme
    assert "`ADVISORY_PROOF_RELEASE_ENABLED` is false" in readme
    assert "`advisory` by default" not in readme

    skill = _read("skill/SKILL.md")
    assert "LOW — receipt-only execution binding" in skill
    assert "LOW ??receipt-only" not in skill


def test_t150_docs_do_not_ship_operator_artifacts_or_private_paths():
    # Historical routing docs legitimately mention the public corpus and the
    # old certificate interface. Keep this privacy/corpus gate focused on the
    # new research note rather than turning those historical references into
    # unrelated regressions.
    combined = _read("docs/research/renderer-runtime-v2.md").casefold()
    for forbidden in (
        "c:\\users\\", "appdata", "tests/corpus", "private\\",
        "candidate.pdf", "certificate.json",
    ):
        assert forbidden not in combined
