import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


extension_pack = _load("extension_pack", REPO_ROOT / "scripts" / "extension_pack.py")
personalization = _load(
    "personalization_ctl_for_extension_tests",
    REPO_ROOT / "pipeline" / "scripts" / "personalization_ctl.py",
)
humanization = _load(
    "humanization_ctl_for_extension_tests",
    REPO_ROOT / "pipeline" / "scripts" / "humanization_ctl.py",
)
# The content_audit fail-closed integration test moved to
# modules/report/tests/test_content_audit.py (v0.16 W3-S3): the behavior
# under test is content_audit's, which is report-module payload.


def _prose_pack(name: str, marker: str) -> dict:
    return {
        "schema": "report-pipeline/preference-pack/prose_rules-v1",
        "pack_type": "prose_rules",
        "name": name,
        "version": 1,
        "banned_patterns": [
            {
                "id": f"marker-{name}",
                "regex": marker,
                "severity": "hard",
                "description": "synthetic extension marker",
            }
        ],
    }


def _extension(
    root: Path,
    *,
    extension_id: str = "example.report-style",
    version: str = "1.0.0",
    priority: int = 100,
    marker: str = "EXTENSION_MARKER",
) -> Path:
    packs = root / "packs"
    packs.mkdir(parents=True)
    (packs / "prose_rules.json").write_text(
        json.dumps(_prose_pack(extension_id, marker), ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "rigorloom/extension-pack-v1",
                "id": extension_id,
                "version": version,
                "kind": "data-pack",
                "rigorloom_api": 1,
                "priority": priority,
                "description": "synthetic test extension",
                "packs": {"prose_rules": "packs/prose_rules.json"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_validate_and_dry_run_do_not_write_profile(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"

    validated = extension_pack.validate_pack(source)
    planned = extension_pack.install_pack(source, profile, dry_run=True)

    assert validated["ok"] is True
    assert validated["id"] == "example.report-style"
    assert planned["action"] == "install"
    assert planned["dry_run"] is True
    assert not profile.exists()


def test_list_and_doctor_missing_profile_are_read_only(tmp_path: Path) -> None:
    profile = tmp_path / "missing-profile"

    assert extension_pack.list_installed(profile)["extensions"] == []
    assert extension_pack.doctor(profile)["ok"] is True
    assert not profile.exists()


def test_install_list_and_doctor_are_receipt_backed(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"

    result = extension_pack.install_pack(source, profile)
    rows = extension_pack.list_installed(profile)["extensions"]
    health = extension_pack.doctor(profile)

    installed = Path(result["installed"])
    assert installed == profile / "extensions" / "example.report-style" / "1.0.0"
    assert (installed / ".receipt.json").is_file()
    assert rows == [
        {
            "id": "example.report-style",
            "version": "1.0.0",
            "priority": 100,
            "active": True,
            "receipt_sha256": result["receipt_sha256"],
        }
    ]
    assert health["ok"] is True
    assert health["errors"] == []


def test_same_version_is_immutable_but_identical_install_is_idempotent(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    first = extension_pack.install_pack(source, profile)
    second = extension_pack.install_pack(source, profile)
    assert second["action"] == "already-installed"
    assert second["receipt_sha256"] == first["receipt_sha256"]

    pack_path = source / "packs" / "prose_rules.json"
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    payload["banned_patterns"][0]["regex"] = "CHANGED_WITHOUT_VERSION_BUMP"
    pack_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="immutable version"):
        extension_pack.install_pack(source, profile)


def test_reinstall_never_reblesses_a_tampered_receipt(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    result = extension_pack.install_pack(source, profile)
    installed = Path(result["installed"])
    pack_path = installed / "packs" / "prose_rules.json"
    tampered_pack = json.loads(pack_path.read_text(encoding="utf-8"))
    tampered_pack["banned_patterns"][0]["regex"] = "TAMPERED_BUT_VALID"
    pack_path.write_text(json.dumps(tampered_pack), encoding="utf-8")

    receipt_path = installed / ".receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["files"]["packs/prose_rules.json"] = personalization.sha256(pack_path)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    registry_path = profile / "extensions" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["extensions"]["example.report-style"]["versions"]["1.0.0"][
        "receipt_sha256"
    ] = personalization.sha256_bytes(personalization.canonical_bytes(receipt))
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(ValueError, match="immutable version"):
        extension_pack.install_pack(source, profile)


def test_manifest_refuses_executable_fields_and_path_escape(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entrypoints"] = {"checker": "evil:run"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="entrypoints"):
        extension_pack.validate_pack(source)

    manifest.pop("entrypoints")
    manifest["packs"]["prose_rules"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes extension root"):
        extension_pack.validate_pack(source)


def test_invalid_preference_pack_is_rejected_before_install(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    pack_path = source / "packs" / "prose_rules.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    del pack["banned_patterns"]
    pack_path.write_text(json.dumps(pack), encoding="utf-8")

    with pytest.raises(ValueError, match="schema validation"):
        extension_pack.validate_pack(source)


@pytest.mark.parametrize("pack_type", ["backends", "policy_floors", "constants_allowlist"])
def test_manifest_refuses_trust_sensitive_pack_types(
    tmp_path: Path, pack_type: str
) -> None:
    # constants_allowlist is the v0.13.1 policy boundary: profile-level only,
    # never installable via an extension (checker relaxation vector).
    source = _extension(tmp_path / "source")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packs"] = {pack_type: "packs/prose_rules.json"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="not allowed in a data-only extension"):
        extension_pack.validate_pack(source)


@pytest.mark.parametrize("pack_type", ["backends", "policy_floors", "constants_allowlist"])
def test_install_refuses_trust_sensitive_pack_types(
    tmp_path: Path, pack_type: str
) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packs"] = {pack_type: "packs/prose_rules.json"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="not allowed in a data-only extension"):
        extension_pack.install_pack(source, profile)
    assert not profile.exists()


def test_doctor_detects_installed_pack_tampering(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    result = extension_pack.install_pack(source, profile)
    installed = Path(result["installed"])
    (installed / "packs" / "prose_rules.json").write_text("{}", encoding="utf-8")

    health = extension_pack.doctor(profile)
    assert health["ok"] is False
    assert any("sha256 mismatch" in error for error in health["errors"])


def test_doctor_detects_unexpected_installed_file(tmp_path: Path) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    result = extension_pack.install_pack(source, profile)
    installed = Path(result["installed"])
    (installed / "not-declared.bin").write_bytes(b"unexpected")

    health = extension_pack.doctor(profile)
    assert health["ok"] is False
    assert any("unexpected installed file" in error for error in health["errors"])


def test_doctor_reports_malformed_registry_instead_of_crashing(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    registry_path = profile / "extensions" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps({
            "schema": "rigorloom/extension-registry-v1",
            "api": 1,
            "extensions": {"bad": None},
        }),
        encoding="utf-8",
    )

    health = extension_pack.doctor(profile)

    assert health["ok"] is False
    assert any("invalid extension registry entry" in error for error in health["errors"])


def test_runtime_rejects_registry_path_traversal(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    registry_path = profile / "extensions" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps({
            "schema": "rigorloom/extension-registry-v1",
            "api": 1,
            "extensions": {
                "../escape": {"active_version": "1.0.0", "priority": 0, "versions": {}}
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid extension id"):
        personalization.resolve_pack_content(profile, "prose_rules")


@pytest.mark.parametrize("pack_type", ["policy_floors", "constants_allowlist"])
def test_runtime_rejects_trust_sensitive_pack_even_with_forged_registry(
    tmp_path: Path, pack_type: str
) -> None:
    profile = tmp_path / "profile"
    target = profile / "extensions" / "example.forged" / "1.0.0"
    pack_relative = f"packs/{pack_type}.json"
    pack_path = target / "packs" / f"{pack_type}.json"
    pack_path.parent.mkdir(parents=True)
    forged_pack = personalization.pack_default(pack_type)
    pack_path.write_text(json.dumps(forged_pack), encoding="utf-8")
    manifest_path = target / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    files = {
        "manifest.json": personalization.sha256(manifest_path),
        pack_relative: personalization.sha256(pack_path),
    }
    receipt = {
        "schema": "rigorloom/extension-receipt-v1",
        "id": "example.forged",
        "version": "1.0.0",
        "priority": 0,
        "rigorloom_api": 1,
        "installed_at": "2026-07-19T00:00:00+00:00",
        "content_sha256": "forged",
        "files": files,
        "packs": [{
            "pack_type": pack_type,
            "path": pack_relative,
            "sha256": files[pack_relative],
            "content_sha256": personalization.sha256_bytes(
                personalization.canonical_bytes(forged_pack)
            ),
        }],
    }
    receipt_path = target / ".receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    registry = {
        "schema": "rigorloom/extension-registry-v1",
        "api": 1,
        "extensions": {
            "example.forged": {
                "active_version": "1.0.0",
                "priority": 0,
                "versions": {
                    "1.0.0": {
                        "installed_at": receipt["installed_at"],
                        "receipt_sha256": personalization.sha256_bytes(
                            personalization.canonical_bytes(receipt)
                        ),
                    }
                },
            }
        },
    }
    (profile / "extensions" / "registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="not allowed in a data-only extension"):
        personalization.resolve_pack_content(profile, "prose_rules")


def test_install_rehashes_staged_bytes_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _extension(tmp_path / "source")
    profile = tmp_path / "profile"
    real_copyfile = extension_pack.shutil.copyfile

    def mutating_copy(source_path, destination_path):
        result = real_copyfile(source_path, destination_path)
        if Path(source_path).name == "prose_rules.json":
            Path(destination_path).write_bytes(Path(destination_path).read_bytes() + b" ")
        return result

    monkeypatch.setattr(extension_pack.shutil, "copyfile", mutating_copy)

    with pytest.raises(ValueError, match="source changed while installing"):
        extension_pack.install_pack(source, profile)
    assert not (profile / "extensions" / "example.report-style" / "1.0.0").exists()


def test_extension_precedence_is_default_then_priority_then_global(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    low = _extension(
        tmp_path / "low",
        extension_id="example.low",
        priority=10,
        marker="LOW_MARKER",
    )
    high = _extension(
        tmp_path / "high",
        extension_id="example.high",
        priority=20,
        marker="HIGH_MARKER",
    )
    extension_pack.install_pack(high, profile)
    extension_pack.install_pack(low, profile)

    content, metadata = personalization.resolve_pack_content(
        profile, "prose_rules"
    )
    assert content["name"] == "example.high"
    assert [row["id"] for row in metadata["extensions"]] == [
        "example.low",
        "example.high",
    ]

    global_pack = tmp_path / "global.json"
    global_pack.write_text(
        json.dumps(_prose_pack("global-profile", "GLOBAL_MARKER")),
        encoding="utf-8",
    )
    personalization.register_pack(profile, "prose_rules", global_pack)
    content, metadata = personalization.resolve_pack_content(
        profile, "prose_rules"
    )
    assert content["name"] == "global-profile"
    assert metadata["source"] == "global"


def test_humanization_consumes_the_canonical_extension_resolution(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    source = _extension(tmp_path / "source", marker="HUMANIZE_EXTENSION_MARKER")
    extension_pack.install_pack(source, profile)

    resolved = humanization._merged_pack(profile, "prose_rules")

    assert resolved["name"] == "example.report-style"
    assert resolved["banned_patterns"][0]["regex"] == "HUMANIZE_EXTENSION_MARKER"


def test_activate_switches_versions_without_deleting_previous_install(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    v1 = _extension(tmp_path / "v1", version="1.0.0", marker="V1")
    v2 = _extension(tmp_path / "v2", version="2.0.0", marker="V2")
    extension_pack.install_pack(v1, profile)
    extension_pack.install_pack(v2, profile)

    changed = extension_pack.activate(profile, "example.report-style", "1.0.0")
    rows = extension_pack.list_installed(profile)["extensions"]

    assert changed["active_version"] == "1.0.0"
    assert {row["version"] for row in rows} == {"1.0.0", "2.0.0"}
    assert next(row for row in rows if row["version"] == "1.0.0")["active"] is True
    assert next(row for row in rows if row["version"] == "2.0.0")["active"] is False
