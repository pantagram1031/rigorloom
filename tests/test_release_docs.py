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
    readme_match = README_VERSION.search(readme)
    assert readme_match, "README must carry a parseable current release line"
    current = readme_match.group(1)

    record_path = ROOT / "docs" / f"release-{current}.md"
    assert record_path.is_file(), f"README names {current} but {record_path.name} is missing"
    record_match = RECORD_VERSION.search(record_path.read_text(encoding="utf-8"))
    assert record_match, "release record must carry a parseable version heading"
    assert record_match.group(1) == current

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert version and f"v{version.group(1)}" == current, "pyproject version must match the README release"

    current_line = readme[readme_match.start():
                          readme.find("\n", readme_match.start())]
    assert not PENDING_TAG.search(current_line)
