"""Capture the 0fa897a CLI oracle with the same probe builders as the tests."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "engine" / "tests"))
import test_report_xml_frozen_worker as probes


def main() -> None:
    archive = subprocess.run(["git", "archive", "--format=tar", "0fa897a", "engine", "pipeline"], cwd=REPO, check=True, capture_output=True).stdout
    # Put capture scratch in the authorized output tree when supplied by the caller.
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as temp:
        base = Path(temp)
        parent = base / "parent"
        parent.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(parent, filter="data")
            else:
                tf.extractall(parent)
        for case in probes._PARENT_CASES:
            data = probes._parent_probe(parent, base / case, case)
            (HERE / f"{case}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(case, flush=True)


if __name__ == "__main__":
    main()
