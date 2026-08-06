from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

MODULE_SCRIPTS = Path(__file__).parents[1] / "scripts"
CORE_SCRIPTS = Path(__file__).parents[3] / "pipeline" / "scripts"
for _dir in (CORE_SCRIPTS, MODULE_SCRIPTS):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import personalization_ctl  # noqa: E402
import style_extract  # noqa: E402


@pytest.fixture
def report_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the report distribution module enabled (report_structure drafts
    need its pack schema) regardless of the CI matrix point."""
    enabled = tmp_path / "enabled-for-test.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\nenabled: [report, style]\n",
        encoding="utf-8")
    monkeypatch.setenv("RIGORLOOM_ENABLED_FILE", str(enabled))


@pytest.fixture
def core_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "RIGORLOOM_ENABLED_FILE", str(tmp_path / "enabled-absent.yaml"))


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


def test_mined_drafts_validate_and_carry_provenance(
        tmp_path: Path, report_module) -> None:
    corpus = _corpus(tmp_path)
    out_dir = tmp_path / "drafts"

    verdict, code = style_extract.mine(corpus, out_dir)

    assert code == 0, verdict
    assert verdict["skipped_pack_types"] == []
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


def test_core_only_mines_prose_and_skips_module_pack_types(
        tmp_path: Path, core_only) -> None:
    corpus = _corpus(tmp_path)
    out_dir = tmp_path / "drafts"

    verdict, code = style_extract.mine(corpus, out_dir)

    assert code == 0, verdict
    assert verdict["skipped_pack_types"] == ["report_structure"]
    assert (out_dir / "prose_rules.draft.json").is_file()
    assert not (out_dir / "report_structure.draft.json").exists()


def test_refuses_current_schema_profile_root_destination(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    profile = tmp_path / "renamed-profile"
    profile.mkdir()
    (profile / "manifest.json").write_text(
        json.dumps({"schema": "rigorloom/personalization-v1"}),
        encoding="utf-8")

    verdict, code = style_extract.mine(corpus, profile / "drafts")

    assert code == 2
    assert "refusing to write drafts" in verdict["error"]


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
