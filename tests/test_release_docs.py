"""Release-document invariants that do not require Git or network state."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
README_VERSION = re.compile(
    r"Current release:\s*\*\*(v\d+\.\d+\.\d+)\*\*",
    re.IGNORECASE,
)
RECORD_VERSION = re.compile(
    r"^#\s*Release record\b[^\n]*\b(v\d+\.\d+\.\d+)\b",
    re.IGNORECASE | re.MULTILINE,
)
PENDING_TAG = re.compile(r"\bpending\s+tag\b", re.IGNORECASE)


def test_current_release_line_matches_record_without_pending_marker():
    """The current README line must describe the existing release record."""

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    record = (ROOT / "docs" / "release-v0.17.0.md").read_text(encoding="utf-8")

    readme_match = README_VERSION.search(readme)
    record_match = RECORD_VERSION.search(record)
    assert readme_match, "README must carry a parseable current release line"
    assert record_match, "release record must carry a parseable version heading"
    assert readme_match.group(1) == record_match.group(1) == "v0.17.0"

    current_line = readme[readme_match.start():
                          readme.find("\n", readme_match.start())]
    assert not PENDING_TAG.search(current_line)
