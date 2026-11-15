"""Tests for document-type style rule packs (`runtime/style_packs/*.json`)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "runtime" / "scripts"
PACK_DIR = REPO_ROOT / "runtime" / "style_packs"
DOCS_PATH = REPO_ROOT / "docs" / "korean-style-rules.md"
DEMO_HWPX = REPO_ROOT / "examples" / "gongmun" / "expected" / "filled.hwpx"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import rt_style  # noqa: E402


def _all_pack_data() -> dict[str, dict]:
    loaded: dict[str, dict] = {}
    for path in sorted(PACK_DIR.glob("*.json")):
        loaded[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _iter_pack_rules() -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for pack_name, data in sorted(_all_pack_data().items()):
        for rule in data["rules"]:
            items.append((pack_name, rule))
    return items


_PACK_RULE_PARAMS = _iter_pack_rules()
_PACK_RULE_IDS = [rule["id"] for _, rule in _PACK_RULE_PARAMS]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "cli.py"), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_pack_inventory_unique_ids_and_base_doc_types():
    packs = _all_pack_data()
    assert set(packs) == set(rt_style.PACK_NAMES)
    assert rt_style.RULESET == "ko-style/1"
    assert packs["hr"]["baseDocType"] == "gongmun"
    for name in ("gongmun", "minwon", "grant"):
        assert packs[name]["baseDocType"] == name

    base_ids = {r.id for r in rt_style.RULES}
    seen_ids: set[str] = set()
    for pack_name, data in packs.items():
        loaded = rt_style.load_pack(pack_name)
        assert loaded.pack == pack_name
        assert loaded.version == f"{pack_name}/1"
        assert len(data["rules"]) >= 1
        for rule in data["rules"]:
            rid = rule["id"]
            assert rid.startswith(f"{pack_name}.")
            assert rid not in base_ids
            assert rid not in seen_ids, f"duplicate pack rule id: {rid}"
            seen_ids.add(rid)


@pytest.mark.parametrize(("pack_name", "rule"), _PACK_RULE_PARAMS, ids=_PACK_RULE_IDS)
def test_pack_rule_positive(pack_name: str, rule: dict, tmp_path: Path):
    doc = tmp_path / "positive.txt"
    doc.write_text(rule["positive"] + "\n", encoding="utf-8")

    result = rt_style.check(doc, doc_type=None, pack=pack_name)
    assert result["ruleset"] == f"ko-style/1+{pack_name}/1"
    assert rule["id"] in result["rulesApplied"]

    matched = [f for f in result["findings"] if f["rule"] == rule["id"]]
    assert len(matched) >= 1, f"{rule['id']} failed to match positive example"
    assert matched[0]["severity"] == rule["severity"]
    assert result["pass"] == (result["counts"]["error"] == 0)


@pytest.mark.parametrize(("pack_name", "rule"), _PACK_RULE_PARAMS, ids=_PACK_RULE_IDS)
def test_pack_rule_negative(pack_name: str, rule: dict, tmp_path: Path):
    doc = tmp_path / "negative.txt"
    doc.write_text(rule["negative"] + "\n", encoding="utf-8")

    result = rt_style.check(doc, doc_type=None, pack=pack_name)
    matched = [f for f in result["findings"] if f["rule"] == rule["id"]]
    assert not matched, f"{rule['id']} matched its negative example: {matched}"


def test_unselected_pack_never_fires(tmp_path: Path):
    gongmun_data = _all_pack_data()["gongmun"]
    doc = tmp_path / "all_gongmun.txt"
    doc.write_text("\n".join(r["positive"] for r in gongmun_data["rules"]) + "\n", encoding="utf-8")

    with_gongmun = rt_style.check(doc, doc_type=None, pack="gongmun")
    gongmun_findings = {f["rule"] for f in with_gongmun["findings"] if f["rule"].startswith("gongmun.")}
    assert gongmun_findings == {r["id"] for r in gongmun_data["rules"]}

    without_pack = rt_style.check(doc, doc_type="gongmun")
    assert not any(f["rule"].startswith("gongmun.") for f in without_pack["findings"])
    assert not any(r.startswith("gongmun.") for r in without_pack["rulesApplied"])

    with_minwon = rt_style.check(doc, doc_type=None, pack="minwon")
    assert with_minwon["ruleset"] == "ko-style/1+minwon/1"
    assert not any(f["rule"].startswith("gongmun.") for f in with_minwon["findings"])
    assert not any(r.startswith("gongmun.") for r in with_minwon["rulesApplied"])

    cli_minwon = _run_cli("style", "check", str(doc), "--pack", "minwon")
    assert cli_minwon.returncode == 0
    cli_payload = json.loads(cli_minwon.stdout)
    assert not any(f["rule"].startswith("gongmun.") for f in cli_payload["result"]["findings"])


def test_without_pack_output_byte_identical_to_baseline():
    # Construct expected baseline result directly from ko-style/1 primitives
    unit, units = rt_style._units(DEMO_HWPX)
    rules = rt_style.rules_for("any")
    findings = rt_style.check_text(units, rules)
    errors = sum(1 for f in findings if f["severity"] == "error")
    baseline_result = {
        "schema": "rigorloom/style-check-v1",
        "ruleset": "ko-style/1",
        "file": DEMO_HWPX.name,
        "docType": "any",
        "unit": unit,
        "rulesApplied": [r.id for r in rules],
        "pass": errors == 0,
        "counts": {"error": errors, "notice": len(findings) - errors},
        "findings": findings,
    }
    expected_json = json.dumps(
        {"ok": errors == 0, "command": "style check", "result": baseline_result},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    expected_text = rt_style.format_lines(baseline_result, str(DEMO_HWPX))

    proc_json = _run_cli("style", "check", str(DEMO_HWPX), "--format", "json")
    assert proc_json.returncode in (0, 3)
    assert proc_json.stdout == expected_json

    proc_text = _run_cli("style", "check", str(DEMO_HWPX), "--format", "text")
    assert proc_text.returncode == proc_json.returncode
    assert proc_text.stdout == expected_text


def test_hr_base_doc_type_and_explicit_doc_type_override(tmp_path: Path):
    doc = tmp_path / "hr_notice.txt"
    doc.write_text(
        "결론적으로 당해 기관 인사 발령은 다음 달 반영된다.\n",
        encoding="utf-8",
    )

    assert rt_style.check(doc)["docType"] == "any"
    default_hr = rt_style.check(doc, pack="hr")
    assert default_hr["docType"] == "gongmun"
    assert default_hr["ruleset"] == "ko-style/1+hr/1"
    default_ids = {f["rule"] for f in default_hr["findings"]}
    assert "hr.danghae-jargon" in default_ids
    assert "ko.para-opener-summary" not in default_ids

    summary = rt_style.format_lines(default_hr, str(doc)).splitlines()[-1]
    assert summary.startswith("ko-style/1+hr/1 (gongmun, per line): ")

    override_hr = rt_style.check(doc, doc_type="report", pack="hr")
    assert override_hr["docType"] == "report"
    override_ids = {f["rule"] for f in override_hr["findings"]}
    assert "hr.danghae-jargon" in override_ids
    assert "ko.para-opener-summary" in override_ids


def _write_pack(pack_dir: Path, name: str, data: dict | str) -> None:
    content = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    (pack_dir / f"{name}.json").write_text(content, encoding="utf-8")


def _valid_sample_pack(name: str = "demo") -> dict:
    return {
        "pack": name,
        "version": f"{name}/1",
        "baseDocType": "gongmun",
        "note": "테스트 팩",
        "rules": [
            {
                "id": f"{name}.sample-rule",
                "pattern": "금번",
                "severity": "notice",
                "why": "쉬운 말로 고칩니다.",
                "suggest": "이번",
                "positive": "금번 회의는 취소합니다.",
                "negative": "이번 회의는 취소합니다.",
                "source": {
                    "title": "행정업무운영 편람",
                    "edition": "2025",
                    "section": "제2장 제1절",
                    "page": "39",
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing-file",
        "invalid-json",
        "missing-note",
        "bad-version",
        "bad-base-doc-type",
        "empty-rules",
        "missing-rule-field",
        "bad-rule-id-prefix",
        "duplicate-rule-id",
        "collides-with-base",
        "bad-severity",
        "bad-regex",
        "positive-miss",
        "negative-hit",
        "house-missing-in-note",
        "bad-source-dict",
    ],
)
def test_bad_pack_raises_style_input_error_with_pack_name(case: str, tmp_path: Path):
    name = "badpack"
    data = _valid_sample_pack(name)

    if case == "missing-file":
        pass
    elif case == "invalid-json":
        _write_pack(tmp_path, name, "{not valid json")
    else:
        if case == "missing-note":
            del data["note"]
        elif case == "bad-version":
            data["version"] = "badpack/99"
        elif case == "bad-base-doc-type":
            data["baseDocType"] = "any"
        elif case == "empty-rules":
            data["rules"] = []
        elif case == "missing-rule-field":
            del data["rules"][0]["suggest"]
        elif case == "bad-rule-id-prefix":
            data["rules"][0]["id"] = "other.sample-rule"
        elif case == "duplicate-rule-id":
            data["rules"].append(dict(data["rules"][0]))
        elif case == "collides-with-base":
            data["rules"][0]["id"] = "ko.double-passive"
        elif case == "bad-severity":
            data["rules"][0]["severity"] = "warning"
        elif case == "bad-regex":
            data["rules"][0]["pattern"] = "[unclosed"
        elif case == "positive-miss":
            data["rules"][0]["positive"] = "이번 회의는 취소합니다."
        elif case == "negative-hit":
            data["rules"][0]["negative"] = "금번 회의도 취소합니다."
        elif case == "house-missing-in-note":
            data["rules"][0]["source"] = "house"
        elif case == "bad-source-dict":
            del data["rules"][0]["source"]["page"]
        _write_pack(tmp_path, name, data)

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.load_pack(name, pack_dir=tmp_path)
    assert name in str(exc_info.value)


def test_unknown_pack_exits_two_matching_bad_doc_type(tmp_path: Path):
    doc = tmp_path / "doc.txt"
    doc.write_text("정상 문장입니다.\n", encoding="utf-8")

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.check(doc, doc_type=None, pack="nonexistent")
    assert "nonexistent" in str(exc_info.value)

    bad_doc_type = _run_cli("style", "check", str(doc), "--doc-type", "nonexistent")
    bad_pack = _run_cli("style", "check", str(doc), "--pack", "nonexistent")
    assert bad_doc_type.returncode == 2
    assert bad_pack.returncode == 2


def test_docs_list_all_pack_rules_and_disclaimers():
    docs = DOCS_PATH.read_text(encoding="utf-8")
    assert "question for a person" in docs
    assert "no claim" in docs

    for pack_name, data in _all_pack_data().items():
        assert f"### {pack_name}" in docs
        for rule in data["rules"]:
            assert rule["id"] in docs
            assert rule["severity"] in docs
            assert rule["positive"] in docs
            assert rule["negative"] in docs
            if rule["source"] == "house":
                assert "house" in docs
            else:
                assert rule["source"]["title"] in docs
                assert rule["source"]["page"] in docs
