# -*- coding: utf-8 -*-
"""Acceptance and adversarial refusal tests for `rigorloom demo gongmun`.

Designed to pass on a clean clone where `modules/enabled.yaml` does not exist;
never skips when distribution modules are not pre-enabled in the checkout.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
EXPECTED_DIR = REPO_ROOT / "examples" / "gongmun" / "expected"
DEFAULT_BRIEF = REPO_ROOT / "examples" / "gongmun" / "brief.json"
BLANK_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
CHECK_GONGMUN_PATH = REPO_ROOT / "modules" / "gongmun" / "scripts" / "check_gongmun.py"
README_PATH = REPO_ROOT / "README.md"
ENABLED_YAML = REPO_ROOT / "modules" / "enabled.yaml"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import cli  # noqa: E402
import rt_demo_gongmun  # noqa: E402


OUTPUT_FILES = ("filled.hwpx", "plan.json", "verdict.json", "approval.json")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_check_gongmun():
    spec = importlib.util.spec_from_file_location("wp1_check_gongmun", CHECK_GONGMUN_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _assert_matches_expected_outputs(out_dir: Path) -> None:
    for name in OUTPUT_FILES:
        actual = out_dir / name
        expected = EXPECTED_DIR / name
        assert actual.is_file(), f"missing demo output: {actual}"
        assert expected.is_file(), f"missing expected fixture: {expected}"

    # HWPX member-by-member XML and binary bytes match expected fixture.
    with zipfile.ZipFile(out_dir / "filled.hwpx", "r") as z_act, zipfile.ZipFile(
        EXPECTED_DIR / "filled.hwpx", "r"
    ) as z_exp:
        assert sorted(z_act.namelist()) == sorted(z_exp.namelist())
        for member in sorted(z_exp.namelist()):
            assert z_act.read(member) == z_exp.read(member), (
                f"filled.hwpx member differs from expected: {member}"
            )
    assert (out_dir / "filled.hwpx").read_bytes() == (EXPECTED_DIR / "filled.hwpx").read_bytes()

    for json_name in ("plan.json", "verdict.json", "approval.json"):
        assert (out_dir / json_name).read_bytes() == (EXPECTED_DIR / json_name).read_bytes(), (
            f"{json_name} differs from expected fixture"
        )


def _assert_nothing_published(out_dir: Path) -> None:
    assert not (out_dir / "filled.hwpx").exists()
    assert not (out_dir / "approval.json").exists()


def _rewrite_section0_xml(hwpx_path: Path, transform) -> None:
    tmp_path = hwpx_path.with_suffix(".tmp.hwpx")
    with zipfile.ZipFile(hwpx_path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Contents/section0.xml":
                xml = data.decode("utf-8")
                new_xml = transform(xml)
                assert new_xml != xml, "test fault transform did not alter section0.xml"
                data = new_xml.encode("utf-8")
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            zout.writestr(new_info, data)
    os.replace(tmp_path, hwpx_path)


def _extract_readme_try_it() -> tuple[str, str]:
    readme = README_PATH.read_text(encoding="utf-8")
    marker = "### Try it: 공문"
    start = readme.index(marker)
    next_heading = re.search(r"^#{2,3}\s+", readme[start + len(marker):], flags=re.M)
    section = (
        readme[start:]
        if next_heading is None
        else readme[start : start + len(marker) + next_heading.start()]
    )
    sh_match = re.search(r"```sh\n(.*?)\n```", section, flags=re.S)
    text_match = re.search(r"```text\n(.*?)\n```", section, flags=re.S)
    assert sh_match is not None, "README missing ```sh command under 'Try it: 공문'"
    assert text_match is not None, "README missing ```text output under 'Try it: 공문'"
    return sh_match.group(1).strip(), text_match.group(1) + "\n"


def test_demo_gongmun_cli_main_matches_expected_without_enabled_yaml(tmp_path: Path, capsys):
    enabled_existed_before = ENABLED_YAML.exists()
    out_dir = tmp_path / "demo-out"

    rc = cli.main(["demo", "gongmun", "--out", str(out_dir), "--deterministic"])
    captured = capsys.readouterr()

    assert rc == 0, f"stderr={captured.err}\nstdout={captured.out}"
    assert ENABLED_YAML.exists() == enabled_existed_before
    assert "rigorloom demo gongmun: PASS" in captured.out

    _assert_matches_expected_outputs(out_dir)

    verdict = json.loads((out_dir / "verdict.json").read_text(encoding="utf-8"))
    approval = json.loads((out_dir / "approval.json").read_text(encoding="utf-8"))

    filled_sha = _sha256_file(out_dir / "filled.hwpx")
    assert verdict["ranAll"] is True
    assert verdict["acceptance"] is True
    assert verdict["counts"]["hard"] == 0
    assert verdict["subject"]["sha256"] == filled_sha
    assert verdict["guard"]["ok"] is True
    assert verdict["guard"]["policy_i"]["allBriefValuesVerbatim"] is True
    assert verdict["guard"]["policy_i"]["untouchedBytesIdentical"] is True
    assert len(verdict["guard"]["paragraphDiff"]) >= 1
    assert verdict["guard"]["policy_ii"]["status"] == "skipped"
    assert approval["approver"] == "demo-operator"
    assert approval["decision"] == "approved"
    assert approval["state"] == "approved"

    # Direct verification via check_gongmun confirms 0 HARD findings on filled.hwpx.
    check_gongmun = _load_check_gongmun()
    report, code = check_gongmun.check(out_dir / "filled.hwpx", mode="auto", baseline=BLANK_FORM)
    assert code == 0, report
    assert report["ok"] is True
    assert report["verdict"] == "pass"
    assert report["hard"] == []


def test_demo_gongmun_subprocess_cli_and_module_package(tmp_path: Path):
    enabled_existed_before = ENABLED_YAML.exists()

    # 1. Direct script invocation from an external working directory
    out_cli = tmp_path / "sub-cli"
    proc_cli = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_SCRIPTS / "cli.py"),
            "demo",
            "gongmun",
            "--out",
            str(out_cli),
            "--deterministic",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc_cli.returncode == 0, proc_cli.stderr
    _assert_matches_expected_outputs(out_cli)

    # 2. Wheel-style package import (`python -m rigorloom_runtime.cli`) via symlinked pkg dir
    pkg_parent = tmp_path / "pkg_root"
    pkg_parent.mkdir()
    os.symlink(RUNTIME_SCRIPTS, pkg_parent / "rigorloom_runtime")
    out_pkg = tmp_path / "sub-pkg"
    env = {
        **os.environ,
        "PYTHONPATH": str(pkg_parent),
        "PYTHONIOENCODING": "utf-8",
    }
    proc_pkg = subprocess.run(
        [
            sys.executable,
            "-m",
            "rigorloom_runtime.cli",
            "--engine-root",
            str(REPO_ROOT),
            "demo",
            "gongmun",
            "--out",
            str(out_pkg),
            "--deterministic",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc_pkg.returncode == 0, proc_pkg.stderr
    assert proc_pkg.stdout == proc_cli.stdout
    _assert_matches_expected_outputs(out_pkg)
    assert ENABLED_YAML.exists() == enabled_existed_before


def test_demo_gongmun_deterministic_across_separate_temp_dirs(tmp_path: Path):
    out_a = tmp_path / "first-run"
    out_b = tmp_path / "second-run"
    out_env = tmp_path / "env-det-run"

    proc_a = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_SCRIPTS / "cli.py"),
            "demo",
            "gongmun",
            "--out",
            str(out_a),
            "--deterministic",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    proc_b = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_SCRIPTS / "cli.py"),
            "demo",
            "gongmun",
            "--out",
            str(out_b),
            "--deterministic",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    env_det = {**os.environ, rt_demo_gongmun.DETERMINISTIC_ENV: "1"}
    proc_env = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_SCRIPTS / "cli.py"),
            "demo",
            "gongmun",
            "--out",
            str(out_env),
        ],
        cwd=REPO_ROOT,
        env=env_det,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert proc_a.returncode == 0, proc_a.stderr
    assert proc_b.returncode == 0, proc_b.stderr
    assert proc_env.returncode == 0, proc_env.stderr
    assert proc_a.stdout == proc_b.stdout == proc_env.stdout

    for name in OUTPUT_FILES:
        bytes_a = (out_a / name).read_bytes()
        bytes_b = (out_b / name).read_bytes()
        bytes_env = (out_env / name).read_bytes()
        assert bytes_a == bytes_b == bytes_env, f"non-deterministic bytes in {name}"


def test_demo_gongmun_refuses_brief_changed_after_planning(tmp_path: Path, capsys):
    out_dir = tmp_path / "refused-brief-drift"

    def _mutate_brief(ctx: rt_demo_gongmun.DemoPostPlanContext) -> None:
        ctx.brief["기관명"] = "변경된기관명"

    with rt_demo_gongmun.post_plan_hook_context(_mutate_brief):
        rc = cli.main(["demo", "gongmun", "--out", str(out_dir), "--deterministic"])

    captured = capsys.readouterr()
    assert rc == 3
    assert "Policy (i)" in captured.err
    _assert_nothing_published(out_dir)


def test_demo_gongmun_refuses_deleted_seat_value(tmp_path: Path, capsys):
    out_dir = tmp_path / "refused-deleted-seat"

    def _delete_seat(ctx: rt_demo_gongmun.DemoPostPlanContext) -> None:
        _rewrite_section0_xml(
            ctx.candidate_path,
            lambda xml: xml.replace("원장 윤지현", "", 1),
        )

    with rt_demo_gongmun.post_plan_hook_context(_delete_seat):
        rc = cli.main(["demo", "gongmun", "--out", str(out_dir), "--deterministic"])

    captured = capsys.readouterr()
    assert rc == 3
    assert "Policy (i)" in captured.err
    _assert_nothing_published(out_dir)


@pytest.mark.parametrize("fault_kind", ["text", "lineseg"])
def test_demo_gongmun_refuses_changed_non_seat_paragraph(
    tmp_path: Path, capsys, fault_kind: str
):
    out_dir = tmp_path / f"refused-nonseat-{fault_kind}"

    def _mutate_non_seat(ctx: rt_demo_gongmun.DemoPostPlanContext) -> None:
        if fault_kind == "text":
            _rewrite_section0_xml(
                ctx.candidate_path,
                lambda xml: xml.replace("<hp:t>(경유)</hp:t>", "<hp:t>(경유변조)</hp:t>", 1),
            )
            return

        def _shift_lineseg(xml: str) -> str:
            marker = "<hp:t>(경유)</hp:t>"
            pos = xml.find(marker)
            assert pos != -1
            seg_pos = xml.find('vertpos="0"', pos)
            assert seg_pos != -1
            return xml[:seg_pos] + 'vertpos="99"' + xml[seg_pos + len('vertpos="0"'):]

        _rewrite_section0_xml(ctx.candidate_path, _shift_lineseg)

    with rt_demo_gongmun.post_plan_hook_context(_mutate_non_seat):
        rc = cli.main(["demo", "gongmun", "--out", str(out_dir), "--deterministic"])

    captured = capsys.readouterr()
    assert rc == 3
    assert "Policy (i)" in captured.err
    _assert_nothing_published(out_dir)


@pytest.mark.parametrize("tamper_mode", ["candidate_bytes", "verdict_sha256"])
def test_demo_gongmun_refuses_candidate_sha256_tamper(
    tmp_path: Path, capsys, tamper_mode: str
):
    out_dir = tmp_path / f"refused-sha256-{tamper_mode}"

    def _tamper(ctx: rt_demo_gongmun.DemoPostPlanContext) -> None:
        if tamper_mode == "candidate_bytes":
            # Alter package bytes (ZIP comment) without changing XML text so
            # Policy (i) still passes and the post-check SHA-256 gate catches it.
            tmp_hwpx = ctx.candidate_path.with_suffix(".tamper.hwpx")
            with zipfile.ZipFile(ctx.candidate_path, "r") as zin, zipfile.ZipFile(
                tmp_hwpx, "w"
            ) as zout:
                for info in zin.infolist():
                    new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                    new_info.compress_type = info.compress_type
                    new_info.external_attr = info.external_attr
                    zout.writestr(new_info, zin.read(info.filename))
                zout.comment = b"tampered-bytes"
            os.replace(tmp_hwpx, ctx.candidate_path)
            return

        ctx.verdict["subject"]["sha256"] = "0" * 64

    with rt_demo_gongmun.post_plan_hook_context(_tamper):
        rc = cli.main(["demo", "gongmun", "--out", str(out_dir), "--deterministic"])

    captured = capsys.readouterr()
    assert rc == 3
    assert "sha256 mismatch" in captured.err
    _assert_nothing_published(out_dir)


def test_demo_gongmun_policy_ii_polished_pass_and_refusals(tmp_path: Path, capsys):
    brief = json.loads(DEFAULT_BRIEF.read_text(encoding="utf-8"))
    faithful_text = "\n".join([
        brief["본문"][0],
        "2. 우리 원은 2026년도 생산 전자기록물의 보존 포맷 호환성을 점검하고자 합니다. 귀 기관은 아래 일정에 따라 소관 기록물을 점검하고 결과를 회신해 주시기 바랍니다.",
        brief["본문"][2],
        brief["본문"][3],
        brief["본문"][4],
        brief["본문"][5],
        brief["붙임"],
    ]) + "\n"
    faithful_file = tmp_path / "polished_ok.txt"
    faithful_file.write_text(faithful_text, encoding="utf-8")

    out_ok = tmp_path / "polished-pass"
    rc_ok = cli.main([
        "demo",
        "gongmun",
        "--out",
        str(out_ok),
        "--polished",
        str(faithful_file),
        "--deterministic",
    ])
    cap_ok = capsys.readouterr()
    assert rc_ok == 0, cap_ok.err
    assert "policies: form->filled PASS; draft->polished PASS" in cap_ok.out

    assert (out_ok / "filled.hwpx").read_bytes() == (EXPECTED_DIR / "filled.hwpx").read_bytes()
    assert (out_ok / "plan.json").read_bytes() == (EXPECTED_DIR / "plan.json").read_bytes()
    assert (out_ok / "approval.json").read_bytes() == (EXPECTED_DIR / "approval.json").read_bytes()

    verdict_ok = json.loads((out_ok / "verdict.json").read_text(encoding="utf-8"))
    verdict_exp = json.loads((EXPECTED_DIR / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_ok["guard"]["ok"] is True
    assert verdict_ok["guard"]["policy_ii"] == {
        "status": "pass",
        "ok": True,
        "policy": "draft->polished",
        "fidelityOk": True,
    }
    assert verdict_ok["guard"]["policy_i"] == verdict_exp["guard"]["policy_i"]
    assert verdict_ok["guard"]["paragraphDiff"] == verdict_exp["guard"]["paragraphDiff"]
    verdict_ok_rest = {k: v for k, v in verdict_ok.items() if k != "guard"}
    verdict_exp_rest = {k: v for k, v in verdict_exp.items() if k != "guard"}
    assert verdict_ok_rest == verdict_exp_rest

    bad_cases = [
        ("altered_date", faithful_text.replace("2026. 11. 27.(금)", "2026. 12. 05.(토)")),
        ("ungrounded_entity", faithful_text + "참고 규격: ISO-9001 적용.\n"),
        ("forbidden_claim", faithful_text + "(\uc815\ud655\ub3c4 100% 보장)\n"),
    ]
    for label, bad_text in bad_cases:
        bad_file = tmp_path / f"polished_{label}.txt"
        bad_file.write_text(bad_text, encoding="utf-8")
        out_bad = tmp_path / f"out-{label}"
        rc_bad = cli.main([
            "demo",
            "gongmun",
            "--out",
            str(out_bad),
            "--polished",
            str(bad_file),
            "--deterministic",
        ])
        cap_bad = capsys.readouterr()
        assert rc_bad == 3, f"{label} expected exit 3, got {rc_bad} ({cap_bad.out})"
        assert "Policy (ii)" in cap_bad.err
        _assert_nothing_published(out_bad)


def test_demo_gongmun_usage_error_exits_two_with_no_outputs(tmp_path: Path, capsys):
    bad_brief = tmp_path / "too_many_lines.json"
    brief = json.loads(DEFAULT_BRIEF.read_text(encoding="utf-8"))
    brief["본문"] = [f"{i}. 점검 항목 {i}" for i in range(1, 18)]
    bad_brief.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    out_dir = tmp_path / "usage-err-out"
    rc = cli.main([
        "demo",
        "gongmun",
        "--out",
        str(out_dir),
        "--brief",
        str(bad_brief),
        "--deterministic",
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "[USAGE]" in captured.err
    _assert_nothing_published(out_dir)


def test_readme_try_it_gongmun_matches_stdout_byte_for_byte(tmp_path: Path):
    cmd_line, expected_stdout = _extract_readme_try_it()
    tokens = shlex.split(cmd_line)
    assert tokens[:3] == ["python", "runtime/scripts/cli.py", "demo"]
    assert "/tmp/gongmun-demo" in tokens

    out_dir = tmp_path / "readme-gongmun-demo"
    patched_tokens = [str(out_dir) if tok == "/tmp/gongmun-demo" else tok for tok in tokens]
    proc = subprocess.run(
        [sys.executable, *patched_tokens[1:]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.encode("utf-8") == expected_stdout.encode("utf-8")
    _assert_matches_expected_outputs(out_dir)
