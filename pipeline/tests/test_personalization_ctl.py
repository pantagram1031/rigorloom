import importlib.util
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "personalization_ctl.py"
SPEC = importlib.util.spec_from_file_location("personalization_ctl", MODULE_PATH)
personalization = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(personalization)


@pytest.fixture
def report_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the report distribution module ENABLED for this test, regardless of
    which CI matrix point (core-only / all-modules) is running. The env
    override is read per call by personalization_ctl and inherited by any
    subprocess it spawns."""
    enabled = tmp_path / "enabled-for-test.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\nenabled: [report, style]\n",
        encoding="utf-8")
    monkeypatch.setenv("RIGORLOOM_ENABLED_FILE", str(enabled))


@pytest.fixture
def core_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin a core-only view (no distribution modules enabled)."""
    monkeypatch.setenv(
        "RIGORLOOM_ENABLED_FILE", str(tmp_path / "enabled-absent.yaml"))


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


def test_global_gloss_pack_adds_terms_without_removing_public_defaults(tmp_path: Path, report_module) -> None:
    root = tmp_path / "profile"
    default_terms = personalization.pack_default("gloss_allowlist")["terms"]
    operator_pack = {
        "schema": "report-pipeline/preference-pack/gloss_allowlist-v1",
        "pack_type": "gloss_allowlist",
        "name": "operator-gloss",
        "version": 1,
        "terms": ["ENSO"],
    }
    personalization.register_pack(
        root, "gloss_allowlist", _write(tmp_path / "gloss.json", operator_pack)
    )

    resolved, _metadata = personalization.resolve_pack_content(root, "gloss_allowlist")

    assert set(default_terms).issubset(resolved["terms"])
    assert "ENSO" in resolved["terms"]


def test_global_constants_pack_adds_entries_without_removing_public_defaults(tmp_path: Path, report_module) -> None:
    root = tmp_path / "profile"
    defaults = personalization.pack_default("constants_allowlist")
    operator_entry = {"value": 42, "unit": "answer", "label": "synthetic constant"}
    personalization.register_pack(
        root,
        "constants_allowlist",
        _write(tmp_path / "constants.json", [operator_entry]),
    )

    resolved, _metadata = personalization.resolve_pack_content(root, "constants_allowlist")

    assert all(entry in resolved for entry in defaults)
    assert operator_entry in resolved


def test_invalid_pack_rejected(tmp_path: Path, report_module) -> None:
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


def test_constants_allowlist_is_a_validated_list_pack(tmp_path: Path, report_module) -> None:
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


def test_constants_allowlist_rejects_missing_label(tmp_path: Path, report_module) -> None:
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


def test_floor_override_is_refused_and_warned(tmp_path: Path, report_module) -> None:
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


def test_lock_carries_no_effective_content_and_redacts_floor_values(tmp_path: Path, report_module) -> None:
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


# --- v0.16 W4.1: general/report pack-type split ------------------------------

def test_core_only_pack_types_are_general(core_only) -> None:
    assert personalization.PACK_TYPES == list(personalization.CORE_PACK_TYPES)
    assert personalization.PACK_TYPES == [
        "prose_rules", "figure_style", "backends", "policy_floors"]
    assert personalization.DATA_EXTENSION_PACK_TYPES == (
        "prose_rules", "figure_style")


def test_enabled_report_module_extends_pack_types(report_module) -> None:
    types = personalization.PACK_TYPES
    assert set(types) == {
        "prose_rules", "figure_style", "backends", "policy_floors",
        "saeteuk", "report_structure", "gloss_allowlist",
        "constants_allowlist", "tone_rules"}
    data_ext = personalization.DATA_EXTENSION_PACK_TYPES
    # trust-sensitive types never become extension-installable (tone_rules
    # included per the W4.1 ruling: it configures thresholds/severities of a
    # deterministic checker, the constants_allowlist relaxation-vector class)
    for trust_sensitive in personalization.TRUST_SENSITIVE_PACK_TYPES:
        assert trust_sensitive not in data_ext
    assert set(data_ext) == {
        "prose_rules", "figure_style", "saeteuk", "report_structure",
        "gloss_allowlist"}


def test_report_pack_type_on_core_only_names_missing_module(
        tmp_path: Path, core_only) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    pack_file = _write(tmp_path / "sae.json", {"pack_type": "saeteuk"})
    for operation in (
            lambda: personalization.register_pack(root, "saeteuk", pack_file),
            lambda: personalization.show_pack(root, "saeteuk"),
            lambda: personalization.resolve_pack_content(root, "saeteuk"),
            lambda: personalization.pack_schema("saeteuk"),
            lambda: personalization.pack_default("saeteuk")):
        with pytest.raises(ValueError) as caught:
            operation()
        message = str(caught.value)
        assert "'report'" in message and "not enabled" in message


def test_unknown_pack_type_lists_known_types(tmp_path: Path, core_only) -> None:
    with pytest.raises(ValueError) as caught:
        personalization.register_pack(
            tmp_path / "profile", "no_such_pack",
            _write(tmp_path / "x.json", {}))
    message = str(caught.value)
    assert "unknown pack type" in message and "prose_rules" in message


def test_resolve_lock_omits_module_pack_types_on_core_only(
        tmp_path: Path, core_only) -> None:
    root = tmp_path / "profile"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    personalization.init(root)
    result = personalization.resolve(root, workspace, None, None, None, None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    assert [row["pack_type"] for row in lock["packs"]] == list(
        personalization.CORE_PACK_TYPES)


# --- v0.16 W4.1: schema rename with read-compat ------------------------------

def test_init_writes_current_schema_and_lock_schema(tmp_path: Path) -> None:
    root = tmp_path / "profile"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    personalization.init(root)
    manifest = personalization.read_json(root / "manifest.json", {})
    assert manifest["schema"] == "rigorloom/personalization-v1"
    result = personalization.resolve(root, workspace, None, None, None, None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    assert lock["schema"] == "rigorloom/personalization-lock-v1"
    assert lock["profile_schema"] == "rigorloom/personalization-v1"


def test_legacy_profile_schema_accepted_with_single_warning(
        tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "profile"
    personalization.init(root)
    manifest = personalization.read_json(root / "manifest.json", {})
    manifest["schema"] = "report-pipeline/personalization-v1"
    personalization.write_json(root / "manifest.json", manifest)
    personalization._WARNED_ONCE.clear()

    first = personalization.export_store(root, tmp_path / "one.zip")
    second = personalization.export_store(root, tmp_path / "two.zip")
    assert first["ok"] and second["ok"]

    err = capsys.readouterr().err
    assert err.count("legacy personalization schema") == 1
    assert "report-pipeline/personalization-v1" in err


def test_lock_schema_read_compat() -> None:
    personalization._WARNED_ONCE.clear()
    assert personalization.accept_lock_schema(
        "rigorloom/personalization-lock-v1", "t") is True
    assert personalization.accept_lock_schema(
        "report-pipeline/personalization-lock-v1", "t") is True
    assert personalization.accept_lock_schema("something/else", "t") is False


# --- v0.16 W4.1: store portability (export / import) -------------------------

def _populated_store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    personalization.init(root)
    personalization.register_pack(
        root, "prose_rules", _write(tmp_path / "prose.json", _valid_prose_pack()))
    (root / personalization.DENYLIST_FILENAME).write_text(
        "SECRET-NAME\n", encoding="utf-8")
    return root


def test_export_import_round_trip_excludes_denylist(tmp_path: Path) -> None:
    root = _populated_store(tmp_path)
    archive = tmp_path / "store.zip"
    result = personalization.export_store(root, archive)
    assert result["ok"] and result["denylist_excluded"] is True

    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
        blob = b"".join(handle.read(name) for name in names)
    assert personalization.EXPORT_MANIFEST_NAME in names
    assert not any(
        Path(name).name == personalization.DENYLIST_FILENAME for name in names)
    # denylist CONTENT never travels either
    assert b"SECRET-NAME" not in blob

    target = tmp_path / "machine-b" / "store"
    imported = personalization.import_store(target, archive)
    assert imported["ok"] and imported["files"] == result["files"]
    # identical pack content and identical file trees (minus the denylist)
    assert (personalization.stored_pack(target, "prose_rules")
            == personalization.stored_pack(root, "prose_rules"))
    source_files = {
        p.relative_to(root).as_posix() for p in root.rglob("*")
        if p.is_file() and p.name != personalization.DENYLIST_FILENAME}
    target_files = {
        p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    assert target_files == source_files
    assert personalization.list_packs(target) == personalization.list_packs(root)


def test_import_refuses_non_empty_target(tmp_path: Path) -> None:
    root = _populated_store(tmp_path)
    archive = tmp_path / "store.zip"
    personalization.export_store(root, archive)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty profile root"):
        personalization.import_store(target, archive)
    # target untouched
    assert (target / "existing.txt").read_text(encoding="utf-8") == "x"


def test_import_refuses_tampered_archive(tmp_path: Path) -> None:
    root = _populated_store(tmp_path)
    archive = tmp_path / "store.zip"
    personalization.export_store(root, archive)

    # tamper 1: modify a manifested file's bytes
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "packs/prose_rules.json":
                data = data.replace(b"test-prose", b"evil-prose")
            dst.writestr(name, data)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        personalization.import_store(tmp_path / "t1", tampered)
    assert not (tmp_path / "t1").exists()

    # tamper 2: smuggle an extra file the manifest never listed
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(extra, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("packs/smuggled.json", "{}")
    with pytest.raises(ValueError, match="absent from"):
        personalization.import_store(tmp_path / "t2", extra)

    # tamper 3: an archive claiming to carry a denylist is refused
    with_denylist = tmp_path / "denylist.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(with_denylist, "w") as dst:
        manifest = json.loads(src.read(personalization.EXPORT_MANIFEST_NAME))
        denylist_body = b"SECRET-NAME\n"
        manifest["files"][personalization.DENYLIST_FILENAME] = (
            personalization.sha256_bytes(denylist_body))
        dst.writestr(personalization.EXPORT_MANIFEST_NAME,
                     json.dumps(manifest))
        for name in src.namelist():
            if name != personalization.EXPORT_MANIFEST_NAME:
                dst.writestr(name, src.read(name))
        dst.writestr(personalization.DENYLIST_FILENAME, denylist_body)
    with pytest.raises(ValueError, match="denylist"):
        personalization.import_store(tmp_path / "t3", with_denylist)


def test_export_refuses_uninitialized_root(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-store"
    empty.mkdir()
    with pytest.raises(ValueError, match="manifest.json"):
        personalization.export_store(empty, tmp_path / "out.zip")


def test_import_refuses_zip_slip_member(tmp_path: Path) -> None:
    evil = tmp_path / "evil.zip"
    body = b"owned"
    manifest = {
        "schema": personalization.EXPORT_SCHEMA,
        "exported_at": "2026-08-07T00:00:00+00:00",
        "profile_schema": personalization.SCHEMA,
        "excluded": [],
        "files": {"../escape.txt": personalization.sha256_bytes(body)},
    }
    with zipfile.ZipFile(evil, "w") as dst:
        dst.writestr(personalization.EXPORT_MANIFEST_NAME, json.dumps(manifest))
        dst.writestr("../escape.txt", body)
    with pytest.raises(ValueError, match="escapes the profile root"):
        personalization.import_store(tmp_path / "victim", evil)
    assert not (tmp_path / "escape.txt").exists()
