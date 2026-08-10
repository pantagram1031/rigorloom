import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/research/story-role-native-evidence.md"
CHANGED_DOCS = (
    ROOT / "CHANGELOG.md",
    ROOT / "docs/golden-path.md",
    ROOT / "docs/trouble-table.md",
    DOC,
    ROOT / "skill/references/operations.md",
)


def test_story_role_native_evidence_keeps_execution_and_semantics_separate() -> None:
    text = DOC.read_text(encoding="utf-8")
    required = {
        "synthetic-donor",
        "not Hancom-authored note controls",
        'render: "not_run"',
        "unknown/unsupported_graphics_state",
        "does **not** prove native note insertion",
        "non-reproducible operator-local audit record",
        "No `--kill-stale` recovery was used",
        "footer",
        "footnote",
        "endnote",
    }
    missing = sorted(fragment for fragment in required if fragment not in text)
    assert not missing, missing


def test_story_role_native_evidence_does_not_ship_runtime_paths() -> None:
    forbidden = ("C:" + "\\Users", "AppData", "rigorloom-story-role-proof-f1d94b9")
    for path in CHANGED_DOCS:
        text = path.read_text(encoding="utf-8")
        assert not [token for token in forbidden if token in text], path


def test_story_role_native_evidence_keeps_exact_hash_matrix() -> None:
    text = DOC.read_text(encoding="utf-8")
    hashes = re.findall(r"`([0-9a-f]{64})`", text)
    assert len(hashes) == 12
    assert len(set(hashes)) == 12

    expected = {"footer": "1", "footnote": "2", "endnote": "2"}
    for role, pages in expected.items():
        row = next(line for line in text.splitlines() if line.startswith(f"| {role} |"))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[0] == role
        assert len(re.findall(r"`[0-9a-f]{64}`", row)) == 4
        assert cells[5] == pages
        match = re.search(
            r"bbox `\(([0-9]+),([0-9]+),([0-9]+),([0-9]+)\)`, ([0-9]+) pixels",
            cells[6],
        )
        assert match
        x1, y1, x2, y2, pixels = map(int, match.groups())
        assert 0 <= x1 < x2 <= 1653
        assert 0 <= y1 < y2 <= 2337
        assert pixels > 0

    timestamps = re.findall(r"`(2026-08-10T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)`", text)
    assert len(timestamps) == 6
    assert len(set(timestamps)) == 6
    assert "All six recorded\n`source_print_method: null`" in text
    assert "checker nevertheless returned `unknown/unsupported_graphics_state` for all\nsix PDFs" in text


def test_story_role_native_evidence_pins_primary_source_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_urls = {
        "https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/HeaderFooterType.cpp",
        "https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/NoteType.cpp",
        "https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/SectionDefinitionType.cpp",
        "https://store.hancom.com/etc/hwpDownload.do",
        "https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D3.0_HWPML_revision1.2.pdf",
    }
    assert not [url for url in required_urls if url not in text]
