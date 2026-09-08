"""Stage only tracked distribution data; never copy local caches or settings."""
from pathlib import Path
import shutil
import subprocess
import sys

PAYLOAD_PATHS = ("engine/scripts", "pipeline/scripts", "runtime/scripts", "agenthost/scripts",
                 "modules", "pyproject.toml", "engine/references/fonts/family-map")


def stage_payload(repo: Path, destination: Path) -> list[str]:
    repo = repo.resolve(strict=True)
    destination = destination.resolve()
    if not destination.is_relative_to(repo / "desktop" / "sidecar" / "build"):
        raise ValueError("payload must remain inside this checkout's sidecar build directory")
    if destination.exists():
        raise ValueError("payload destination must be new")
    files = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z", "--", *PAYLOAD_PATHS])
    copied = []
    destination.mkdir(parents=True)
    for raw in files.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if ("__pycache__" in relative.parts or relative.suffix in {".pyc", ".pyo"}
                or relative.as_posix() == "modules/enabled.yaml"):
            continue
        source = (repo / relative).resolve(strict=True)
        if not source.is_relative_to(repo):
            raise ValueError(f"payload source escapes checkout: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative.as_posix())
    return copied


if __name__ == "__main__":
    copied = stage_payload(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"staged {len(copied)} tracked payload files")
