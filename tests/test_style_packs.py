"""Tests for document-type style rule packs (`runtime/style_packs/*.json`)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "runtime" / "scripts"
PACK_DIR = REPO_ROOT / "runtime" / "style_packs"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "style_packs"
DOCS_PATH = REPO_ROOT / "docs" / "korean-style-rules.md"
DEMO_HWPX = REPO_ROOT / "examples" / "gongmun" / "expected" / "filled.hwpx"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cli  # noqa: E402
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


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cli_arg = "runtime/scripts/cli.py" if cwd == REPO_ROOT else str(SCRIPTS_DIR / "cli.py")
    return subprocess.run(
        [sys.executable, "-B", cli_arg, *args],
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
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


@pytest.mark.parametrize(
    ("rel_path", "extra_args", "baseline_stem", "expected_rc"),
    [
        ("tests/fixtures/style_packs/with_findings.txt", (), "with_findings.any", 3),
        ("tests/fixtures/style_packs/with_findings.txt", ("--doc-type", "any"), "with_findings.any", 3),
        ("tests/fixtures/style_packs/with_findings.txt", ("--doc-type", "gongmun"), "with_findings.gongmun", 3),
        ("examples/gongmun/expected/filled.hwpx", (), "filled_hwpx.any", 0),
        ("examples/gongmun/expected/filled.hwpx", ("--doc-type", "any"), "filled_hwpx.any", 0),
    ],
)
def test_without_pack_output_byte_identical_to_baseline(
    rel_path: str, extra_args: tuple[str, ...], baseline_stem: str, expected_rc: int
):
    expected_json = (FIXTURES_DIR / f"{baseline_stem}.json").read_text(encoding="utf-8")
    expected_text = (FIXTURES_DIR / f"{baseline_stem}.txt").read_text(encoding="utf-8")

    proc_json = _run_cli("style", "check", rel_path, *extra_args, "--format", "json", cwd=REPO_ROOT)
    assert proc_json.returncode == expected_rc
    assert proc_json.stderr == ""
    assert proc_json.stdout == expected_json

    proc_text = _run_cli("style", "check", rel_path, *extra_args, "--format", "text", cwd=REPO_ROOT)
    assert proc_text.returncode == expected_rc
    assert proc_text.stderr == ""
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


def test_no_pack_rule_has_error_severity():
    error_rules = [rule["id"] for _, rule in _PACK_RULE_PARAMS if rule["severity"] == "error"]
    assert error_rules == []


@pytest.mark.parametrize(
    ("pack_name", "rule_id", "text"),
    [
        ("gongmun", "gongmun.saishiot-orthography", "기존 서식의 ‘갯수(수정 전)’ 항목을 ‘개수’로 변경합니다."),
        ("grant", "grant.rate-dueum-error", "입력 자료의 열 이름 ‘집행율(%)’은 원본과 동일하게 유지합니다."),
    ],
)
def test_quoted_counterexamples_exit_zero_without_findings(
    pack_name: str, rule_id: str, text: str, tmp_path: Path
):
    doc = tmp_path / "quoted.txt"
    doc.write_text(text + "\n", encoding="utf-8")

    result = rt_style.check(doc, pack=pack_name)
    assert result["counts"]["error"] == 0
    assert not any(f["rule"] == rule_id for f in result["findings"])

    proc = _run_cli("style", "check", str(doc), "--pack", pack_name)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["counts"] == {"error": 0, "notice": 0}
    assert payload["result"]["findings"] == []


@pytest.mark.parametrize(
    ("pack_name", "rule_id", "text"),
    [
        ("gongmun", "gongmun.submit-receive-confusion", "신청자가 제출한 서류는 담당자가 접수하여 처리합니다."),
        ("gongmun", "gongmun.attachment-label", "별첨 서식은 수정하지 말고 붙임과 같이 사용하시기 바랍니다."),
        ("gongmun", "gongmun.attachment-label", "별첨 서식은 별도로 수정하지 말고 붙임과 같이 사용하시기 바랍니다."),
        ("grant", "grant.e-hanhaeo-limit", "양식장 수조에 한해성 어류를 입식합니다."),
        ("gongmun", "gongmun.currency-no-korean", "금0원(금영원)으로 계약 금액을 확정합니다."),
        ("gongmun", "gongmun.amount-unit-awkward", "예산은 1억 2천 원으로 편성합니다."),
        ("gongmun", "gongmun.date-zero-pad", "관련: 교육지원과-1234(2026. 03. 05.)호."),
        (
            "gongmun",
            "gongmun.date-zero-pad",
            '행정안전부 정보공개과-1004 (2020. 03. 03., "2020년 행정업무편람 운영지침")호와 관련됩니다.',
        ),
        ("minwon", "minwon.vague-followup", "검토 결과는 2026. 5. 15.까지 추후 별도 안내드리겠습니다."),
        ("hr", "hr.rank-step-vague", "적정 호봉은 7호봉으로 확정되었습니다."),
        ("hr", "hr.rank-step-vague", "적정 호봉은 인사위원회 심의 결과 7호봉으로 확정되었습니다."),
    ],
)
def test_adversarial_counterexamples_do_not_fire(
    pack_name: str, rule_id: str, text: str, tmp_path: Path
):
    doc = tmp_path / "counterexample.txt"
    doc.write_text(text + "\n", encoding="utf-8")

    result = rt_style.check(doc, pack=pack_name)
    assert not any(f["rule"] == rule_id for f in result["findings"]), (
        f"{rule_id} unexpectedly matched {text!r}: {result['findings']}"
    )


def test_pack_rules_64kib_adversarial_performance():
    prose_unit = (
        "신청자가 제출한 서류는 담당자가 접수하여 처리합니다. "
        "예산은 1억 2천 원으로 편성합니다. "
        "별첨 서식은 수정하지 말고 붙임과 같이 사용하시기 바랍니다. "
        "기존 서식의 ‘갯수(수정 전)’ 항목을 ‘개수’로 변경합니다. "
        "99999999999999999999 "
    )
    prose_64k = (prose_unit * ((65536 // len(prose_unit)) + 2))[:65536] + "!"
    adversarial_inputs = {
        "digits-64k": "9" * 65536 + "!",
        "hangul-64k": "가" * 65536 + "!",
        "commas-64k": "999," * 16384 + "!",
        "prose-64k": prose_64k,
    }
    for label, text in adversarial_inputs.items():
        assert len(text.encode("utf-8")) >= 65536, label

    for pack_name in rt_style.PACK_NAMES:
        loaded = rt_style.load_pack(pack_name)
        for rule in loaded.rules:
            rx = rule.regex()
            for label, text in adversarial_inputs.items():
                start = time.perf_counter()
                list(rx.finditer(text))
                elapsed = time.perf_counter() - start
                assert elapsed < 0.5, f"{rule.id} on {label} took {elapsed:.3f}s (>= 0.5s)"


@pytest.mark.parametrize(
    "bad_pattern",
    [
        "^(a+)+$",
        "(a*)*",
        "(a+)*",
        "((a+))+",
        "(?:a+|b){2,}",
        "(?:a+?)+",
    ],
)
def test_loader_rejects_nested_quantifiers(bad_pattern: str, tmp_path: Path):
    name = "badpack"
    data = _valid_sample_pack(name)
    rule_id = f"{name}.nested"
    data["rules"][0].update(id=rule_id, pattern=bad_pattern, positive="a", negative="b")
    _write_pack(tmp_path, name, data)

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.load_pack(name, pack_dir=tmp_path)
    msg = str(exc_info.value)
    assert name in msg and rule_id in msg


def test_loader_and_cli_reject_regex_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    data = _valid_sample_pack("gongmun")
    rule_id = "gongmun.overflow-rule"
    data["rules"][0].update(id=rule_id, pattern="a{4294967296}", positive="a", negative="b")
    _write_pack(pack_dir, "gongmun", data)

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.load_pack("gongmun", pack_dir=pack_dir)
    msg = str(exc_info.value)
    assert "gongmun" in msg and rule_id in msg

    doc = tmp_path / "doc.txt"
    doc.write_text("정상 문장입니다.\n", encoding="utf-8")

    monkeypatch.setattr(rt_style, "_default_pack_dir", lambda: pack_dir)
    rc = cli.main(["style", "check", str(doc), "--pack", "gongmun"])
    captured = capsys.readouterr()
    assert rc == 2
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_params"
    assert "gongmun" in payload["error"]["message"]
    assert rule_id in payload["error"]["message"]

    sub_code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
        "import rt_style, cli; "
        f"rt_style._default_pack_dir = lambda: Path({str(pack_dir)!r}); "
        f"raise SystemExit(cli.main(['style', 'check', {str(doc)!r}, '--pack', 'gongmun']))"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", sub_code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2
    sub_payload = json.loads(proc.stdout)
    assert sub_payload["ok"] is False
    assert sub_payload["error"]["code"] == "invalid_params"


@pytest.mark.parametrize(
    ("pack_name", "bad_base"),
    [
        ("gongmun", "contract"),
        ("hr", "minwon"),
        ("minwon", "gongmun"),
        ("grant", "gongmun"),
    ],
)
def test_loader_enforces_pack_base_doc_type(pack_name: str, bad_base: str, tmp_path: Path):
    data = _valid_sample_pack(pack_name)
    data["baseDocType"] = bad_base
    _write_pack(tmp_path, pack_name, data)

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.load_pack(pack_name, pack_dir=tmp_path)
    assert pack_name in str(exc_info.value)


def test_loader_rejects_rule_id_with_trailing_newline(tmp_path: Path):
    data = _valid_sample_pack("gongmun")
    data["rules"][0]["id"] = "gongmun.date-zero-pad\n"
    _write_pack(tmp_path, "gongmun", data)

    with pytest.raises(rt_style.StyleInputError) as exc_info:
        rt_style.load_pack("gongmun", pack_dir=tmp_path)
    assert "gongmun" in str(exc_info.value)


@pytest.mark.parametrize(
    ("pattern", "positive", "negative"),
    [
        (r"(?:,\d{3}){1,5}", ",123,456", "123"),
        (r"^a(?:\s?(?:님|귀하))?$", "a 님", "b"),
        (r"^(?:(?!foo+)\w)+$", "bar", "foo"),
        (r"^(?:a+){0,1}$", "aaa", "bbb"),
    ],
)
def test_loader_allows_safe_bounded_and_lookaround_patterns(
    pattern: str, positive: str, negative: str, tmp_path: Path
):
    name = "safepack"
    data = _valid_sample_pack(name)
    data["rules"][0].update(pattern=pattern, positive=positive, negative=negative)
    _write_pack(tmp_path, name, data)

    pack = rt_style.load_pack(name, pack_dir=tmp_path)
    assert pack.rules[0].pattern == pattern


def test_conditional_notice_rules_ask_person_to_check():
    grant_rules = {r["id"]: r for r in _all_pack_data()["grant"]["rules"]}
    for rid in ("grant.bare-foreign-abbr", "grant.vague-impact-claim"):
        rule = grant_rules[rid]
        assert rule["severity"] == "notice"
        assert "확인" in rule["why"]
