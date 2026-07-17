"""Tests for research-time write-through DOI/ISBN cache records."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_sources  # noqa: E402
import source_fetch  # noqa: E402


NOW = "2026-07-17T01:02:03+00:00"
CONTENT_SHA256 = "a" * 64


def test_record_doi_matches_check_sources_cache_schema(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    doi = "10." + "1234/source-fetch-schema"
    hostile_title = "Stored " + chr(34) + " title" + chr(10) + "history: []"

    record, path = source_fetch.record_source(
        profile_root=profile, doi=doi, title=hostile_title,
        container="Journal of Synthetic Evidence", year=2024,
        retrieved_from="https://example.invalid/record",
        content_sha256=CONTENT_SHA256, now=NOW,
    )

    loaded, error, authoritative = check_sources._load_cache_record(
        path, "doi", doi
    )
    assert error is None
    assert loaded == record
    assert authoritative is True
    assert record["writer"] == "source_fetch"
    assert record["verification"] == {
        "retrieved_from": "https://example.invalid/record",
        "content_sha256": CONTENT_SHA256,
        "retrieved_at": NOW,
    }
    assert path.name == check_sources._doi_slug(doi) + ".json"


def test_record_isbn_normalizes_to_isbn13(tmp_path: Path) -> None:
    profile = tmp_path / "profile"

    record, path = source_fetch.record_source(
        profile_root=profile, isbn="0-306-40615-2",
        title="Synthetic Book", now=NOW,
    )

    assert record["isbn"] == "9780306406157"
    assert record["verification"] is None
    assert path.name == "9780306406157.json"
    loaded, error, authoritative = check_sources._load_cache_record(
        path, "isbn", "9780306406157"
    )
    assert error is None
    assert loaded == record
    assert authoritative is False


def test_record_then_check_sources_is_a_verified_round_trip(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    ws = tmp_path / "workspace"
    (ws / "bundle").mkdir(parents=True)
    doi = "10." + "1234/verified-round-trip"
    title = "Verified Round Trip Evidence"
    source_fetch.record_source(
        profile_root=profile, doi=doi, title=title,
        retrieved_from="https://example.invalid/verified-round-trip",
        content_sha256=CONTENT_SHA256, now=NOW,
    )
    (ws / "bundle" / "content.md").write_text(
        "# References\n\n"
        f"- Doe (2024). {title}. Journal. DOI: {doi}\n",
        encoding="utf-8",
    )

    verdict, code = check_sources.check(ws, profile_root=profile)

    assert code == 0, verdict
    assert verdict["warn"] == []


def test_record_without_retrieval_metadata_remains_unverified(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    ws = tmp_path / "workspace"
    (ws / "bundle").mkdir(parents=True)
    doi = "10." + "1234/self-authored-round-trip"
    title = "Self Authored Round Trip Evidence"
    record, _ = source_fetch.record_source(
        profile_root=profile, doi=doi, title=title, now=NOW,
    )
    (ws / "bundle" / "content.md").write_text(
        "# References\n\n"
        f"- Doe (2024). {title}. Journal. DOI: {doi}\n",
        encoding="utf-8",
    )

    verdict, code = check_sources.check(ws, profile_root=profile)

    assert record["verification"] is None
    assert code == 0, verdict
    assert {item["code"] for item in verdict["warn"]} == {
        "source_selfauthored", "source_unverified",
    }


def test_different_title_refuses_overwrite_unless_forced(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    doi = "10." + "1234/poison-guard"
    _, path = source_fetch.record_source(
        profile_root=profile, doi=doi,
        title="Original Source Title", now=NOW,
    )

    with pytest.raises(source_fetch.SourceFetchError):
        source_fetch.record_source(
            profile_root=profile, doi=doi,
            title="Unrelated Replacement Work",
            now="2026-07-17T02:00:00+00:00",
        )

    assert json.loads(path.read_text(encoding="utf-8"))["title"] == (
        "Original Source Title"
    )

    forced, _ = source_fetch.record_source(
        profile_root=profile, doi=doi,
        title="Unrelated Replacement Work",
        now="2026-07-17T03:00:00+00:00", force=True,
    )

    assert forced["title"] == "Unrelated Replacement Work"
    history = forced["history"]
    assert history[-1]["warning"] == "forced_title_overwrite"
    assert history[-1]["previous_title"] == "Original Source Title"


def test_force_records_history_when_replacing_invalid_cache_record(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    doi = "10." + "1234/invalid-existing-record"
    path = (
        profile / "cache" / "sources" / "doi"
        / (check_sources._doi_slug(doi) + ".json")
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"doi": doi}), encoding="utf-8")

    with pytest.raises(source_fetch.SourceFetchError):
        source_fetch.record_source(
            profile_root=profile, doi=doi, title="Recovered Title", now=NOW,
        )

    forced, _ = source_fetch.record_source(
        profile_root=profile, doi=doi, title="Recovered Title",
        now=NOW, force=True,
    )

    assert forced["history"][-1]["warning"] == (
        "forced_invalid_record_overwrite"
    )
