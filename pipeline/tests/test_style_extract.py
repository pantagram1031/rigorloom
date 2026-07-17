from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import personalization_ctl  # noqa: E402
import style_extract  # noqa: E402


def _corpus(tmp_path: Path) -> list[Path]:
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    first.write_text(
        "## SECTION: Introduction\n\n"
        "Therefore the result remains stable. Therefore the result remains stable.\n\n"
        "## SECTION: Results\n\nThe value is useful.\n",
        encoding="utf-8")
    second.write_text(
        "## SECTION: Introduction\n\n"
        "Therefore the result remains stable. Another sentence ends here.\n\n"
        "## SECTION: Results\n\nThe second value is useful.\n",
        encoding="utf-8")
    return [first, second]


def test_mined_drafts_validate_and_carry_provenance(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    out_dir = tmp_path / "drafts"

    verdict, code = style_extract.mine(corpus, out_dir)

    assert code == 0, verdict
    for pack_type in ("prose_rules", "report_structure"):
        pack = json.loads(
            (out_dir / f"{pack_type}.draft.json").read_text(encoding="utf-8"))
        assert personalization_ctl.validate_instance(
            pack, personalization_ctl.pack_schema(pack_type)) == []
        assert pack["draft"] is True
        assert [item["path"] for item in pack["provenance"]["corpus"]] == [
            str(path.resolve()) for path in corpus]
        assert all(len(item["sha256"]) == 64
                   for item in pack["provenance"]["corpus"])
    prose = json.loads(
        (out_dir / "prose_rules.draft.json").read_text(encoding="utf-8"))
    assert prose["banned_patterns"]
    assert prose["mining_stats"]["paragraph_length_chars"]["count"] > 0


def test_refuses_profile_root_destination(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    profile = tmp_path / "private-profile"
    profile.mkdir()
    (profile / "manifest.json").write_text(
        json.dumps({"schema": "report-pipeline/personalization-v1"}),
        encoding="utf-8")

    verdict, code = style_extract.mine(corpus, profile / "drafts")

    assert code == 2
    assert "refusing to write drafts" in verdict["error"]
    assert not (profile / "drafts").exists()
