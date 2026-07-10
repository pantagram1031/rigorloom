import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "personalization_ctl.py"
SPEC = importlib.util.spec_from_file_location("personalization_ctl", MODULE_PATH)
personalization = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(personalization)


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
    identity.update({"enabled": True, "fields": {"name": "PRIVATE NAME", "student_id": "1234"}})
    personalization.write_json(root / "identity.json", identity)

    result = personalization.resolve(root, workspace, form, "math", workspace / "request.yaml", None)
    lock = json.loads(Path(result["lock"]).read_text(encoding="utf-8"))
    assert lock["identity_enabled"] is True
    assert "PRIVATE NAME" not in json.dumps(lock, ensure_ascii=False)
    assert "1234" not in json.dumps(lock, ensure_ascii=False)
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
