import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "personalization_ctl.py"
SPEC = importlib.util.spec_from_file_location("personalization_ctl", MODULE_PATH)
personalization = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(personalization)


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_init_and_resolve_are_private_and_reproducible(tmp_path: Path) -> None:
    root = tmp_path / "private-profile"
    workspace = tmp_path / "workspace"
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form bytes")
    workspace.mkdir()
    (workspace / "request.yaml").write_text('constraints:\n  style: "request style"\n', encoding="utf-8")
    (root / "identity.json").parent.mkdir(parents=True, exist_ok=True)
    personalization.init(root)
    identity = personalization.read_json(root / "identity.json", {})
    # student_id sentinel deliberately contains a non-hex char ('Z') so it can
    # never coincidentally match a substring of a SHA-256 digest in the lock.
    identity.update({"enabled": True, "fields": {"name": "PRIVATE NAME", "student_id": "SID-1234Z"}})
    personalization.write_json(root / "identity.json", identity)

    result = personalization.resolve(root, workspace, form, "math", workspace / "request.yaml", None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    assert lock["identity_enabled"] is True
    assert "PRIVATE NAME" not in json.dumps(lock, ensure_ascii=False)
    assert "SID-1234Z" not in json.dumps(lock, ensure_ascii=False)
    assert lock["form_sha256"] == personalization.sha256(form)
    assert lock["sources"]["writing"] == "global-writing-profile"


def test_import_legacy_does_not_infer_identity_or_copy_templates(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    (legacy / "kb" / "style").mkdir(parents=True)
    (legacy / "kb" / "curriculum").mkdir(parents=True)
    (legacy / "templates").mkdir(parents=True)
    (legacy / "kb" / "style" / "voice.md").write_text("approved style note", encoding="utf-8")
    (legacy / "kb" / "curriculum" / "과목-math.md").write_text("scope", encoding="utf-8")
    template = legacy / "templates" / "student_name_1234.hwpx"
    template.write_bytes(b"template")
    root = tmp_path / "profile"
    result = personalization.import_legacy(root, legacy)
    assert result["identity_imported"] is False
    assert result["imported"]["forms"] == 1
    assert not list((root / "forms").rglob("*.hwpx"))
    assert personalization.read_json(root / "identity.json", {})["enabled"] is False


def test_feedback_creates_review_only_candidates(tmp_path: Path) -> None:
    root = tmp_path / "profile"; workspace = tmp_path / "report-demo"; workspace.mkdir()
    (workspace / "TROUBLES.md").write_text("| issue | observed | repair |\n| long equation | overflow | display it |\n", encoding="utf-8")
    result = personalization.collect_feedback(root, workspace)
    items = personalization.candidates(root)
    assert result["candidates_added"] == 1
    assert items[0]["status"] == "candidate"
    assert items[0]["requires_human_review"] is True


DISTINCTIVE_REGEX = "ZZbannedZZ[0-9]+ pattern"


def _valid_prose_pack(name: str = "test-prose") -> dict:
    return {
        "schema": "report-pipeline/preference-pack/prose_rules-v1",
        "pack_type": "prose_rules",
        "name": name,
        "version": 1,
        "banned_patterns": [
            {"id": "distinctive", "regex": DISTINCTIVE_REGEX, "severity": "hard",
             "description": "distinctive marker for leak tests"}
        ],
    }


def test_register_pack_validates_and_stores(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    pack_file = _write(tmp_path / "prose.json", _valid_prose_pack())
    result = personalization.register_pack(root, "prose_rules", pack_file)
    assert result["ok"] is True
    assert result["name"] == "test-prose"
    stored = personalization.stored_pack(root, "prose_rules")
    assert stored["banned_patterns"][0]["regex"] == DISTINCTIVE_REGEX
    assert result["sha256"] == personalization.sha256_bytes(personalization.canonical_bytes(stored))


def test_invalid_pack_rejected(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    # missing required 'terms', and a bad enum value for good measure
    bad = {"schema": "x", "pack_type": "gloss_allowlist", "name": "bad", "version": "not-an-int"}
    pack_file = _write(tmp_path / "gloss.json", bad)
    with pytest.raises(ValueError) as exc:
        personalization.register_pack(root, "gloss_allowlist", pack_file)
    message = str(exc.value)
    assert "terms" in message and "version" in message


def test_pack_type_mismatch_rejected(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    pack_file = _write(tmp_path / "prose.json", _valid_prose_pack())
    with pytest.raises(ValueError):
        personalization.register_pack(root, "figure_style", pack_file)


def test_constants_allowlist_is_a_validated_list_pack(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    constants = [
        {"value": 9.81, "unit": "m/s^2", "label": "standard gravity"},
        {"value": 3.14159, "label": "pi approximation"},
    ]

    result = personalization.register_pack(
        root,
        "constants_allowlist",
        _write(tmp_path / "constants.json", constants),
    )

    assert result["ok"] is True
    assert personalization.stored_pack(root, "constants_allowlist") == constants
    assert personalization.validate_instance(
        constants,
        personalization.pack_schema("constants_allowlist"),
    ) == []


def test_constants_allowlist_rejects_missing_label(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)

    with pytest.raises(ValueError) as caught:
        personalization.register_pack(
            root,
            "constants_allowlist",
            _write(tmp_path / "constants.json", [{"value": 9.81}]),
        )

    assert "label" in str(caught.value)


def test_resolve_lock_is_hash_only(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    personalization.init(root)
    personalization.register_pack(root, "prose_rules", _write(tmp_path / "prose.json", _valid_prose_pack()))
    result = personalization.resolve(root, workspace, None, None, None, None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    blob = json.dumps(lock, ensure_ascii=False)
    # rule content must never appear in the lock; only name/version/sha256 do.
    assert DISTINCTIVE_REGEX not in blob
    assert "banned_patterns" not in blob
    prose_record = next(row for row in lock["packs"] if row["pack_type"] == "prose_rules")
    assert prose_record["source"] == "global"
    assert prose_record["name"] == "test-prose"
    assert len(prose_record["sha256"]) == 64
    assert set(prose_record) == {"pack_type", "source", "name", "version", "sha256"}


def test_floor_override_is_refused_and_warned(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    personalization.init(root)
    # A report_structure pack that tries to weaken the citation-source floor.
    weakening = {
        "schema": "report-pipeline/preference-pack/report_structure-v1",
        "pack_type": "report_structure", "name": "weak", "version": 1,
        "title_format": "{topic}", "citation_style": {"sources": "any", "in_text": "parenthetical"},
    }
    personalization.register_pack(root, "report_structure", _write(tmp_path / "rs.json", weakening))
    resolution = personalization.resolve_packs(root, None, None)
    warnings = resolution["floor_warnings"]
    assert any(w["key"] == "citation_style.sources" for w in warnings)
    # the floor value wins unconditionally over the weakened request
    warn = next(w for w in warnings if w["key"] == "citation_style.sources")
    assert warn["attempted_value"] == "any"
    assert warn["floor_value"] == "papers_books_only"
    # resolve() records the same warning into the lock and the feedback log
    result = personalization.resolve(root, workspace, None, None, None, None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    assert any(w["key"] == "citation_style.sources" for w in lock["floor_warnings"])
    events = (root / "feedback" / "events.jsonl").read_text(encoding="utf-8")
    assert "floor-override-warning" in events


def test_lock_carries_no_effective_content_and_redacts_floor_values(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    workspace = tmp_path / "ws-redact"
    workspace.mkdir()
    personalization.init(root)

    # Plant a distinctive Hangul marker deep in the resolved (effective) config
    # via the writing profile — it must appear in the PRIVATE resolved file but
    # never in the workspace lock.
    HANGUL_MARKER = "금지문구ZZ표식"
    writing = personalization.read_json(root / "writing" / "profile.json", {})
    writing["avoid_patterns"] = [HANGUL_MARKER]
    personalization.write_json(root / "writing" / "profile.json", writing)

    # A distinctive request style marker also flows into `effective`.
    (workspace / "request.yaml").write_text(
        'constraints:\n  style: "REQSTYLEZZ"\n', encoding="utf-8")

    # Force a floor override so floor_warnings is non-empty.
    weakening = {
        "schema": "report-pipeline/preference-pack/report_structure-v1",
        "pack_type": "report_structure", "name": "weak", "version": 1,
        "title_format": "{topic}", "citation_style": {"sources": "any", "in_text": "parenthetical"},
    }
    personalization.register_pack(root, "report_structure", _write(tmp_path / "rs.json", weakening))

    result = personalization.resolve(root, workspace, None, None, workspace / "request.yaml", None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    blob = json.dumps(lock, ensure_ascii=False)

    # No resolved content of any kind in the lock.
    assert "effective" not in lock
    assert "effective_sha256" in lock and len(lock["effective_sha256"]) == 64
    assert HANGUL_MARKER not in blob
    assert "REQSTYLEZZ" not in blob

    # floor_warnings carry key paths but NO raw values (redacted to sha256).
    assert lock["floor_warnings"], "expected a floor override warning"
    for w in lock["floor_warnings"]:
        assert "attempted_value" not in w
        assert "floor_value" not in w
        assert w["attempted_sha256"].startswith("sha256:")
        assert w["floor_sha256"].startswith("sha256:")
    # the raw floor value string must not appear anywhere in the lock
    assert "papers_books_only" not in blob
    assert any(w["key"] == "citation_style.sources" for w in lock["floor_warnings"])

    # The full resolved config IS written to the private profile side and DOES
    # contain the marker (so consumers can still fetch it).
    resolved_path = root / "resolved" / f"{workspace.name}.json"
    assert resolved_path.exists()
    resolved_blob = resolved_path.read_text(encoding="utf-8")
    assert HANGUL_MARKER in resolved_blob
    assert "REQSTYLEZZ" in resolved_blob


def test_pack_precedence_default_then_global(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    before = personalization.resolve_packs(root, None, None)
    prose_before = next(r for r in before["packs"] if r["pack_type"] == "prose_rules")
    assert prose_before["source"] == "public-default"
    assert prose_before["name"] == "neutral-default"
    personalization.register_pack(root, "prose_rules", _write(tmp_path / "prose.json", _valid_prose_pack("global-prose")))
    after = personalization.resolve_packs(root, None, None)
    prose_after = next(r for r in after["packs"] if r["pack_type"] == "prose_rules")
    assert prose_after["source"] == "global"
    assert prose_after["name"] == "global-prose"
    assert prose_after["sha256"] != prose_before["sha256"]


def test_yaml_subset_reader_roundtrip(tmp_path: Path) -> None:
    pack = _valid_prose_pack("yaml-prose")
    yaml_text = (
        "schema: report-pipeline/preference-pack/prose_rules-v1\n"
        "pack_type: prose_rules\n"
        "name: yaml-prose\n"
        "version: 1\n"
        "banned_patterns:\n"
        '  - {"id": "distinctive", "regex": "ZZbannedZZ[0-9]+ pattern", "severity": "hard", "description": "distinctive marker for leak tests"}\n'
    )
    path = tmp_path / "prose.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    loaded = personalization.load_pack_file(path)
    assert loaded == pack
