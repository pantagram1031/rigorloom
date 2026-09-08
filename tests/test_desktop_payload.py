"""A freeze cannot absorb ignored developer data or Python caches."""
import importlib.util
from pathlib import Path
import subprocess
import pytest

HELPER = Path(__file__).resolve().parents[1] / "desktop/sidecar/stage_payload.py"
spec = importlib.util.spec_from_file_location("desktop_stage_payload", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_payload_contains_only_tracked_distribution_source(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    paths = {"runtime/scripts/serve.py": "print('serve')", "modules/example/module.yaml": "name: example",
             "modules/enabled.yaml": "enabled: [example]", "engine/scripts/__pycache__/stale.pyc": "cache"}
    for relative, content in paths.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", *paths], check=True)
    (tmp_path / "modules/private-note.txt").write_text("local only", encoding="utf-8")
    destination = tmp_path / "desktop/sidecar/build/payload"
    copied = module.stage_payload(tmp_path, destination)
    assert set(copied) == {"runtime/scripts/serve.py", "modules/example/module.yaml"}
    assert (destination / "runtime/scripts/serve.py").read_text(encoding="utf-8") == "print('serve')"
    assert not (destination / "modules/enabled.yaml").exists()
    assert not (destination / "modules/private-note.txt").exists()
    assert not (destination / "engine/scripts/__pycache__").exists()


def test_payload_destination_cannot_escape_its_build_directory(tmp_path):
    with pytest.raises(ValueError, match="sidecar build directory"):
        module.stage_payload(tmp_path, tmp_path / "outside")
