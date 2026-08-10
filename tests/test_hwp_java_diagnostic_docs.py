from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "docs" / "research" / "hwp-java-diagnostic-candidate.md"


def test_t87_research_pins_sources_tool_and_unbound_runtime():
    text = RESEARCH.read_text(encoding="utf-8")
    for token in (
        "https://github.com/neolord0/hwp2hwpx/tree/50ae71bbaf98ec7a00192f72492d6a130a755ac1",
        "https://github.com/neolord0/hwplib/tree/d9e073d6899d947f8f583492e00a5e1062381d7e",
        "https://github.com/neolord0/hwpxlib/tree/473d9d6aa82d8896f4f464b52d801e5691dc7cf3",
        "io.github.spah1879:hwp2hwpx:2026.6.25-jdk11",
        "https://central.sonatype.com/artifact/io.github.spah1879/hwp2hwpx/2026.6.25-jdk11",
        "06ba7071b9ee2f2256fa62398b5d32dc07496cb47cf764b4cf0b7c6119bd11cd",
        "runtime_binding: launcher_rehashed_runtime_unbound",
        "rigorloom/hwp-java-diagnostic-candidate/v1",
        "independent_source_oracle_not_run",
        "missing_aux_rootfiles_pruned",
    ):
        assert token in text


def test_t87_evidence_note_is_bounded_and_path_private():
    text = RESEARCH.read_text(encoding="utf-8")
    for token in (
        "JDK 24.0.1", "130,048", "15,069", "tables 2", "pictures 1",
        "equations 0", "exited 0", "verify", "deleted",
        "not Windows/macOS/Linux support", "rendering", "submission proof",
    ):
        assert token in text
    lowered = text.casefold()
    for forbidden in ("c:\\users\\", "appdata", "tests/corpus", "private\\"):
        assert forbidden not in lowered


def test_t87_routing_docs_repeat_the_quarantine_boundary():
    paths = (
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "golden-path.md",
        ROOT / "docs" / "trouble-table.md",
        ROOT / "skill" / "SKILL.md",
        ROOT / "skill" / "references" / "operations.md",
        ROOT / "skill" / "references" / "platform-backends.md",
        ROOT / "modules" / "report" / "references" / "playbooks" / "stage-0.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for token in (
        "T87", "hwp-java-diagnostic", "runtime", "unknown", "not_run",
        "proof", "new_report", "no JAR", "Stage 0",
    ):
        assert token in combined
