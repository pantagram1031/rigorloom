# -*- coding: utf-8 -*-
"""workspace/posterRun: fake poster children, success, missing, unavailable, warn."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from _runtime_client import RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_core  # noqa: E402
from rt_codes import RpcError  # noqa: E402

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

STUB_BUILD = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import argparse, json, sys
    from pathlib import Path

    PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--content", required=True)
        ap.add_argument("--figures", required=True)
        ap.add_argument("--form", required=True)
        ap.add_argument("--out", required=True)
        args = ap.parse_args()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK\x03\x04dummy-poster")
        png = out.with_suffix(".png")
        if png.name == "poster_v1.png" or True:
            png = out.parent / "poster_v1.png"
        png.write_bytes(PNG)
        sys.stdout.write(json.dumps({"ok": True, "out": str(out)}))
        sys.stdout.flush()

    if __name__ == "__main__":
        main()
''')

STUB_VERIFY = textwrap.dedent('''
    #!/usr/bin/env python3
    import argparse, json, sys

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--out", required=True)
        ap.add_argument("--form", required=True)
        ap.add_argument("--form-mtime", required=True)
        ap.add_argument("--no-numbers", action="store_true")
        args = ap.parse_args()
        gates = [
            {"name": "form mtime unchanged", "passed": True, "detail": args.form_mtime},
            {"name": "poster has a slide", "passed": True, "detail": ""},
        ]
        payload = {"ok": True, "gates": gates}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.flush()

    if __name__ == "__main__":
        main()
''')

STUB_VERIFY_WARN = textwrap.dedent('''
    #!/usr/bin/env python3
    import argparse, json, sys

    def main():
        ap = argparse.ArgumentParser()
        ap.add_argument("--out", required=True)
        ap.add_argument("--form", required=True)
        ap.add_argument("--form-mtime", required=True)
        ap.add_argument("--no-numbers", action="store_true")
        args = ap.parse_args()
        gates = [
            {"name": "form mtime unchanged", "passed": True, "detail": args.form_mtime},
            {"name": "poster has a slide", "passed": True, "detail": ""},
            {
                "name": "pictures >= 1",
                "passed": True,
                "detail": "pictures=1",
                "warn": [{"code": "pictures", "msg": "form logo counted"}],
            },
        ]
        payload = {"ok": True, "gates": gates}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.flush()

    if __name__ == "__main__":
        main()
''')

AURALAB_HEADER = """\
```yaml
# pipeline-state: v0.4
pipeline_version: "0.6"
graph: "build"
slug: "report-auralab-classroom"
mode: "autonomous"
subject: "physics"
form: "output/form_copy.hwpx"
updated: "2026-09-16T21:39:00"
canonical_output: "output/out.hwpx"
stages:
  "0":   {status: done, gate: {name: topic_pick, state: auto_approved, by: autonomous, at: 2026-09-16T18:13:13}}
  "5":   {status: done, gate: null}
```

# report-auralab-classroom
"""


def _workspace(tmp_path, *, complete=True):
    ws = tmp_path / "report-auralab-classroom"
    (ws / "poster" / "figures").mkdir(parents=True)
    (ws / "PIPELINE.md").write_text(AURALAB_HEADER, encoding="utf-8")
    if complete:
        (ws / "poster" / "poster_content.md").write_text(
            "# TITLE: t\n# AUTHORS: a\n## BOX: intro\nbody\n", encoding="utf-8")
        (ws / "poster" / "form.pptx").write_bytes(b"PK\x03\x04form")
        (ws / "poster" / "figures" / "plot.png").write_bytes(PNG)
    return ws


def _write_stubs(tmp_path) -> tuple[Path, Path]:
    build = tmp_path / "poster_build.py"
    verify = tmp_path / "poster_verify.py"
    build.write_text(STUB_BUILD, encoding="utf-8")
    verify.write_text(STUB_VERIFY, encoding="utf-8")
    return build, verify


@pytest.fixture()
def poster_stubs(tmp_path, monkeypatch):
    build, verify = _write_stubs(tmp_path)
    monkeypatch.setenv("RIGORLOOM_POSTER_BUILD", str(build))
    monkeypatch.setenv("RIGORLOOM_POSTER_VERIFY", str(verify))
    return build, verify


def test_finish_returns_state_paths_hashes_and_verify_rows(tmp_path, poster_stubs):
    ws = _workspace(tmp_path)
    core = rt_core.RuntimeCore(tmp_path / "root")
    result = core.workspace_poster_run(str(ws))
    assert result["state"] == "pass"
    roles = {row["role"] for row in result["outputs"]}
    assert {"pptx", "png"} <= roles
    for row in result["outputs"]:
        assert len(row["sha256"]) == 64
        assert row["bytes"] > 0
        assert Path(row["path"]).is_file()
    names = [row["name"] for row in result["verify"]]
    assert "form mtime unchanged" in names
    assert all(row["passed"] is True for row in result["verify"])
    assert result["preview"]["data"]
    assert result["preview"]["label"] == "미리보기 이미지, 증명 아님"


def test_cli_poster_run_matches_the_core(tmp_path, poster_stubs):
    ws = _workspace(tmp_path)
    root = tmp_path / "cli-root"
    cli = run_cli(root, "poster-run", "--workspace", str(ws))
    assert cli.code == 0, cli.stderr
    assert cli.payload["command"] == "poster-run"
    assert cli.result["state"] == "pass"
    core = rt_core.RuntimeCore(tmp_path / "core-root")
    wire = core.workspace_poster_run(str(ws))
    assert cli.result["state"] == wire["state"]
    assert [row["role"] for row in cli.result["outputs"]] == [
        row["role"] for row in wire["outputs"]]
    assert [row["name"] for row in cli.result["verify"]] == [
        row["name"] for row in wire["verify"]]


def test_missing_inputs_is_artifact_missing(tmp_path):
    ws = _workspace(tmp_path, complete=False)
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_poster_run(str(ws))
    assert caught.value.code == "artifact_missing"
    assert "poster/poster_content.md" in caught.value.data["missing"]
    assert "poster/form.pptx" in caught.value.data["missing"]


def test_module_unavailable_when_poster_cli_is_not_enabled(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\nenabled: []\n", encoding="utf-8")
    monkeypatch.setenv("RIGORLOOM_MODULES_ENABLED", str(enabled))
    monkeypatch.delenv("RIGORLOOM_POSTER_BUILD", raising=False)
    monkeypatch.delenv("RIGORLOOM_POSTER_VERIFY", raising=False)
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_poster_run(str(ws))
    assert caught.value.code == "module_unavailable"
    assert "poster" in caught.value.data["missing"]


def test_verify_warn_is_a_designed_state(tmp_path, poster_stubs, monkeypatch):
    warn = tmp_path / "poster_verify_warn.py"
    warn.write_text(STUB_VERIFY_WARN, encoding="utf-8")
    monkeypatch.setenv("RIGORLOOM_POSTER_VERIFY", str(warn))
    ws = _workspace(tmp_path)
    core = rt_core.RuntimeCore(tmp_path / "root")
    result = core.workspace_poster_run(str(ws))
    assert result["state"] == "warn"
    pictures = next(row for row in result["verify"] if row["checker"] == "pictures >= 1")
    assert pictures["ok"] is True
    assert pictures["counts"]["warn"] == 1
    assert pictures["warn"][0]["msg"] == "form logo counted"


def test_relative_workspace_is_invalid_params(tmp_path):
    core = rt_core.RuntimeCore(tmp_path / "root")
    with pytest.raises(RpcError) as caught:
        core.workspace_poster_run("report-auralab-classroom")
    assert caught.value.code == "invalid_params"


def test_poster_run_is_host_only(tmp_path):
    assert "workspace/posterRun" in rt_core.HOST_ONLY_METHODS
    assert "workspace/posterRun" not in rt_core.AGENT_METHODS
    with RuntimeClient(tmp_path / "agent", entry="agent") as agent:
        agent.initialize()
        error = agent.err("workspace/posterRun", {"workspace": str(tmp_path)})
    assert error["code"] == "unknown_method"
    assert error["data"]["knownOnHostEntry"] is True


def test_pipeline_status_reports_poster_inputs(tmp_path):
    ws = _workspace(tmp_path)
    core = rt_core.RuntimeCore(tmp_path / "root")
    result = core.pipeline_status(str(ws))
    assert result["posterInputs"]["complete"] is True
    assert result["posterInputs"]["contentPath"].endswith("poster_content.md")
    incomplete = _workspace(tmp_path / "other", complete=False)
    missing = core.pipeline_status(str(incomplete))
    assert missing["posterInputs"]["complete"] is False
    assert "poster/poster_content.md" in missing["posterInputs"]["missing"]
