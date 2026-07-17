"""Parity and compatibility tests for shared numeric-claim extraction."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "pipeline" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


claim_extraction = _load("claim_extraction")
check_saeteuk = _load("check_saeteuk")
check_units = _load("check_units")


def test_saeteuk_fixture_claim_parity_uses_f12_scale_and_subject():
    text = "Voltage = 1000000000 mV.\n"

    claims, checked = claim_extraction.extract_numeric_claims(
        text, source="bundle/content.md", policy="saeteuk"
    )

    assert checked == 1
    claim = claims[0]
    assert {
        key: claim[key]
        for key in (
            "value", "raw", "line", "source", "subject", "unit",
            "unit_raw", "unit_scale", "canonical_value", "snippet",
        )
    } == {
        "value": 1000000000.0,
        "raw": "1000000000",
        "line": 1,
        "source": "bundle/content.md",
        "subject": "voltage",
        "unit": "V",
        "unit_raw": "mV",
        "unit_scale": 1e-3,
        "canonical_value": 1000000.0,
        "snippet": "Voltage = 1000000000 mV.",
    }


def test_check_units_fixture_claim_parity_keeps_three_legacy_tags():
    text = (
        "# Results\n"
        "distance = 12 m.\n"
        "duration = 3 s.\n"
        "speed = 4 m/s.\n"
    )

    claims, checked = claim_extraction.extract_numeric_claims(
        text, policy="units"
    )

    assert checked == 3
    assert [
        {
            key: claim[key]
            for key in (
                "value", "raw", "line", "subject", "unit",
                "unit_raw", "dimension", "snippet",
            )
        }
        for claim in claims
    ] == [
        {
            "value": 12.0, "raw": "12", "line": 2,
            "subject": "distance", "unit": "m", "unit_raw": "m",
            "dimension": "length", "snippet": "distance = 12 m.",
        },
        {
            "value": 3.0, "raw": "3", "line": 3,
            "subject": "duration", "unit": "s", "unit_raw": "s",
            "dimension": "time", "snippet": "duration = 3 s.",
        },
        {
            "value": 4.0, "raw": "4", "line": 4,
            "subject": "speed", "unit": "m/s", "unit_raw": "m/s",
            "dimension": "speed", "snippet": "speed = 4 m/s.",
        },
    ]


def test_union_only_korean_tag_does_not_widen_saeteuk_comparison(tmp_path):
    text = "Sample length = 12.0 미터.\n"
    claims, checked = claim_extraction.extract_numeric_claims(
        text, source="_saeteuk/record.txt", policy="saeteuk"
    )
    assert checked == 1
    assert claims[0]["union_unit"]["canonical"] == "m"
    assert claims[0]["unit"] is None

    workspace = tmp_path / "report"
    (workspace / "bundle").mkdir(parents=True)
    (workspace / "_saeteuk").mkdir()
    (workspace / "bundle" / "content.md").write_text(
        "Sample length = 15.0 미터.\n", encoding="utf-8"
    )
    (workspace / "_saeteuk" / "record.txt").write_text(
        text, encoding="utf-8"
    )

    verdict, code = check_saeteuk.check(workspace)

    assert code == 0
    assert verdict["hard"] == []
    assert {item["code"] for item in verdict["warn"]} == {
        "saeteuk_unsupported"
    }


def test_union_only_count_tag_does_not_change_check_units_counts(tmp_path):
    assert claim_extraction.match_unit(" trials.")["dimension"] == "count"

    workspace = tmp_path / "report"
    (workspace / "bundle").mkdir(parents=True)
    (workspace / "bundle" / "content.md").write_text(
        "attempts = 12.0 trials.\n", encoding="utf-8"
    )

    verdict, code = check_units.check(workspace)

    assert code == 0
    assert verdict["checked_numerals"] == 1
    assert verdict["tagged_units"] == 0
    assert verdict["warn"] == []
