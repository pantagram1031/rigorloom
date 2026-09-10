# -*- coding: utf-8 -*-
"""DIST-PAYLOAD-02 — the installed CLI driving a ZIP product payload.

``tests/test_cli_distribution.py`` proves the wheel builds and installs.
``tests/test_cleanroom_evals.py`` proves the core/module ZIP bundles install
into a sandbox that cannot reach this checkout. Neither proves the thing a
buyer actually gets, which is *both at once*: a `rigorloom` command from the
wheel, pointed at an engine root that came out of the bundles, editing a
document, with nothing anywhere resolving back to the source tree.

That combination is what this file exercises, end to end and only once:

    wheel  -> fresh venv inside the sandbox            (the command)
    zips   -> cleanroom.prepare into the same sandbox  (the payload)
    then   capabilities -> open -> inspect -> propose -> request-approval
           -> approve -> apply -> verify

Three rules make the run mean something.

**The checkout is forbidden, not merely unused.** Every subprocess runs under
``cleanroom.Sandbox``'s scrubbed environment (no ``PYTHONPATH``,
``RIGORLOOM_ROOT`` repinned at the sandbox install, ``PATH`` pruned
element-wise), and containment is asserted twice — once by ``prepare`` before
the edit and once again by this file after it, because an edit publishes new
artifacts and a receipt, and those are exactly the files that could carry a
leaked path.

**The address comes from the document, not from a fixture.** The op is built
from whatever ``inspect`` reports as an editable region, so this test cannot
quietly depend on a corpus file's row/col the way a checkout-only test can.

**A skip is not a pass.** Building a wheel needs a toolchain this repository
must not download, so the fixtures skip loudly with the reason when it is
absent. Point ``RIGORLOOM_WHEEL_PYTHON`` at an interpreter carrying setuptools
>= 70.1 (or setuptools plus ``wheel``) to run them. `test_no_axis_was_silently_skipped`
fails if the flow itself was never executed.

What ``verify`` proves, and what it does not, is worth stating plainly because
the difference is easy to overclaim. ``verify`` exits 0, which is fail-closed
on RUNNABILITY: the residue gate genuinely ran, out of the installed core
bundle, against the published candidate. Its VERDICT is ``fail``, because
``check_residue`` measures a finished artifact and a Runtime plan fills cells
rather than finishing a document — the form's own anchor labels survive, and
the checker reports 25 of them. Both facts are asserted here. Neither is
softened: `test_the_residue_gate_reports_the_unfinished_form_instead_of_passing_it`
exists so a future reader cannot mistake "the gate ran" for "the document
passed", and so nobody is tempted to reach the second by weakening the first.

Non-native by construction: the only supported backend is ``preedit``, an
offline XML edit through ``engine/scripts/preedit.py``. No COM, no Hancom, no
renderer, no certificate.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


cleanroom = _load("_payload_cleanroom", REPO_ROOT / "evals" / "cleanroom.py")
package_module = _load("_payload_package_module",
                       REPO_ROOT / "scripts" / "package_module.py")

#: The bundles a buyer of the report product downloads. ``core`` carries the
#: engine, the pipeline scripts and the skill surface; ``report`` is the
#: distribution module whose checkers and CLI the registry then enables.
#:
#: ``style`` is here because ``modules/report/module.yaml:15`` declares
#: ``requires_modules: [style]`` and the registry enforces it at enablement —
#: content_audit composes style's check_style checker. A core+report payload
#: is refused, loudly, by the shipped registry CLI:
#:
#:   refusing to load distribution module 'report': it requires distribution
#:   module(s) ['style'] which are not enabled
#:
#: So the buyer's report payload is three zips, not two. That is a declared
#: product dependency, not a packaging gap.
BUNDLE_NAMES = ("core", "style", "report")

#: Installed as ``rigorloom_runtime`` by the wheel; see pyproject.toml.
WHEEL_PACKAGE = "rigorloom_runtime"

#: Engine/pipeline entrypoints the Runtime resolves under ``--engine-root``.
#: A wheel-only install cannot see any of them; a bundle install must see all.
ENGINE_TOOLS = ("form_inspect", "preedit", "check_residue")

#: PII-free filler. A blank government form plus a common noun: no name, no
#: number, no address. The installed privacy scanner checks this, it is not
#: asserted by eye.
FILL_TEXT = "검증"

#: How many of the document's own editable cells the flow fills. More than one
#: so the plan is a real multi-op plan rather than a single-step special case;
#: bounded so a form with dozens of regions does not turn one assertion into a
#: minutes-long edit campaign. Every address still comes from ``inspect``.
MAX_FILLED_CELLS = 3

#: Wheel exclusions restated here rather than imported from
#: tests/test_cli_distribution.py: this file must fail on its own if the
#: wheel ever widens to swallow the ZIP payload it is supposed to complement.
FORBIDDEN_IN_WHEEL_DIRS = (
    "engine", "pipeline", "modules", "skill", "evals", "qa", "tests",
    "scripts", "studio", "adapters", "agenthost", "archive", "desktop",
    "docs", "examples", "workspaces",
)
FORBIDDEN_IN_WHEEL_FILES = (
    "package_module.py", "sync_local.py", "cleanroom.py", "SKILL.md",
    "module.yaml", "enabled.yaml", "probe.py", "form_inspect.py",
    "preedit.py", "check_residue.py", "module_registry.py",
)
FORBIDDEN_IN_WHEEL_SUFFIXES = (
    ".hwp", ".hwpx", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".zip",
    ".jsonl", ".yaml", ".yml",
)

_TOOLCHAIN_PROBE = """
import importlib.util as u
if u.find_spec("setuptools") is None:
    print("no setuptools"); raise SystemExit(1)
import setuptools
version = tuple(int(p) for p in setuptools.__version__.split(".")[:2] if p.isdigit())
if version >= (70, 1) or u.find_spec("wheel") is not None:
    print(setuptools.__version__); raise SystemExit(0)
print("setuptools %s without the wheel package" % setuptools.__version__)
raise SystemExit(1)
"""

BUILD_TIMEOUT = 900

#: Filled by the payload fixture so the closing test can prove the heavy path
#: actually executed rather than skipping into a green run.
_EXECUTED: dict[str, object] = {}


def _plain_run(argv, timeout=BUILD_TIMEOUT):
    """A build-side subprocess. Sandbox subprocesses go through Sandbox.run."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=env, timeout=timeout)


def _wheel_python() -> str | None:
    candidates = []
    override = (os.environ.get("RIGORLOOM_WHEEL_PYTHON") or "").strip()
    if override:
        candidates.append(override)
    candidates.append(sys.executable)
    for candidate in candidates:
        try:
            probe = _plain_run([candidate, "-c", _TOOLCHAIN_PROBE], timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


def _export_clean_tree(dest: Path) -> Path:
    listing = _plain_run(["git", "-C", str(REPO_ROOT), "ls-files", "-z",
                          "--cached", "--others", "--exclude-standard"])
    if listing.returncode != 0:
        pytest.skip(f"git ls-files failed: {listing.stderr.strip()[:200]}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in listing.stdout.split("\0"):
        if not name:
            continue
        source = REPO_ROOT / name
        if not source.is_file():
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return dest


def _script_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _exe(venv: Path, name: str) -> Path:
    return _script_dir(venv) / (f"{name}.exe" if os.name == "nt" else name)


# --------------------------------------------------------------------------- #
# fixtures — build once, install once, drive once
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def wheel_python() -> str:
    interpreter = _wheel_python()
    if interpreter is None:
        pytest.skip(
            "no offline wheel toolchain on this interpreter (needs setuptools "
            ">= 70.1, or setuptools plus the wheel package). Set "
            "RIGORLOOM_WHEEL_PYTHON to one that has it; installing it here "
            "would be a dependency download, which DIST-PAYLOAD-02 forbids.")
    return interpreter


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory, wheel_python) -> Path:
    """The Runtime-only wheel, built offline from a clean export."""
    base = tmp_path_factory.mktemp("wheelbuild")
    source = _export_clean_tree(base / "source")
    house = base / "wheelhouse"
    house.mkdir()
    built = _plain_run([wheel_python, "-m", "pip", "wheel",
                        "--no-deps", "--no-build-isolation", "--no-index",
                        "--wheel-dir", str(house), str(source)])
    assert built.returncode == 0, (
        "offline wheel build failed:\n"
        f"{built.stdout[-4000:]}\n{built.stderr[-4000:]}")
    wheels = sorted(house.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def bundles(tmp_path_factory) -> list[Path]:
    """Real core + report ZIPs from the real packager."""
    out = tmp_path_factory.mktemp("dist")
    return [package_module.build_bundle(name, out) for name in BUNDLE_NAMES]


@pytest.fixture(scope="module")
def payload(tmp_path_factory, bundles, built_wheel) -> dict:
    """One sandbox holding both distributions, outside every checkout.

    Order matters: ``prepare`` refuses a non-empty root, so the ZIP payload is
    installed first and the venv is created inside the prepared sandbox
    afterwards. The wheel is COPIED into ``<sandbox>/wheelhouse`` before it is
    installed, for the same reason ``install_bundles`` copies the zips — a
    buyer installs from a file they have, and pip records the path it
    installed from in ``direct_url.json``, which containment then reads.
    """
    root = tmp_path_factory.mktemp("payload") / "sandbox"
    report, code = cleanroom.prepare(root, bundles, enable="all")
    assert code == 0, report["failures"]

    sandbox = cleanroom.Sandbox(Path(report["sandbox_root"]))
    house = sandbox.root / "wheelhouse"
    house.mkdir(parents=True, exist_ok=True)
    local_wheel = house / built_wheel.name
    shutil.copy2(built_wheel, local_wheel)

    venv = sandbox.root / "venv"
    created = _plain_run([sys.executable, "-m", "venv", str(venv)])
    assert created.returncode == 0, (
        f"venv creation failed:\n{created.stdout[-2000:]}\n{created.stderr[-2000:]}")
    venv_python = _exe(venv, "python")
    assert venv_python.is_file(), f"no interpreter at {venv_python}"

    if _plain_run([str(venv_python), "-m", "pip", "--version"]).returncode != 0:
        pytest.skip("the fresh venv has no pip; bootstrapping one would be a "
                    "dependency download")

    installed = _plain_run([str(venv_python), "-m", "pip", "install",
                            "--no-deps", "--no-index", str(local_wheel)])
    assert installed.returncode == 0, (
        f"wheel install failed:\n{installed.stdout[-4000:]}\n{installed.stderr[-4000:]}")

    rigorloom = _exe(venv, "rigorloom")
    assert rigorloom.is_file(), (
        f"the wheel installed no rigorloom command at {rigorloom}")

    runtime_root = sandbox.root / "runtime"
    documents = sandbox.root / "documents"
    documents.mkdir(parents=True, exist_ok=True)

    state = {
        "sandbox": sandbox,
        "install": sandbox.install,
        "prepare_report": report,
        "wheel": built_wheel,
        "local_wheel": local_wheel,
        "venv": venv,
        "rigorloom": rigorloom,
        "runtime_root": runtime_root,
        "documents": documents,
        "bundles": bundles,
    }
    _EXECUTED["payload"] = True
    return state


def _cli(payload: dict, *args: str, engine_root: Path | None | bool = None):
    """Run the INSTALLED command inside the sandbox. Never the checkout copy.

    ``engine_root=False`` deliberately omits ``--engine-root`` so a test can
    observe what the command falls back to with nothing pointed at it.
    """
    sandbox = payload["sandbox"]
    argv = [str(payload["rigorloom"]), "--root", str(payload["runtime_root"])]
    if engine_root is not False:
        argv += ["--engine-root", str(engine_root or payload["install"])]
    argv += list(args)
    proc = sandbox.run(argv, timeout=BUILD_TIMEOUT)
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{args[0] if args else '<no command>'} emitted non-JSON "
            f"({exc}):\nstdout={proc.stdout[-2000:]}\n"
            f"stderr={proc.stderr[-2000:]}") from exc
    return proc.returncode, parsed


@pytest.fixture(scope="module")
def document(payload) -> Path:
    """A PII-free blank form, copied wholly inside the sandbox before use."""
    source = (REPO_ROOT / "tests" / "corpus" / "forms" / "converted"
              / "gianmun-byeolji-1ho.hwpx")
    assert source.is_file(), f"corpus form missing: {source}"
    target = payload["documents"] / "form.hwpx"
    shutil.copyfile(source, target)
    return target


@pytest.fixture(scope="module")
def flow(payload, document) -> dict:
    """capabilities -> open -> inspect -> propose -> approve -> apply -> verify.

    One pass, recorded step by step, so each test reads an already-executed
    fact instead of re-running a four-minute install. Only ``verify``'s exit
    code is left unasserted here: what it should be is the subject of two
    tests below, not a precondition of the fixture that produced it.
    """
    steps: dict[str, dict] = {}

    code, capabilities = _cli(payload, "capabilities")
    steps["capabilities"] = {"code": code, "payload": capabilities}
    assert code == 0, capabilities

    code, opened = _cli(payload, "open", "--path", str(document))
    steps["open"] = {"code": code, "payload": opened}
    assert code == 0, opened
    session = opened["result"]["sessionId"]

    code, inspected = _cli(payload, "inspect", "--session", session)
    steps["inspect"] = {"code": code, "payload": inspected}
    assert code == 0, inspected

    regions = inspected["result"]["regions"]["regions"]
    usable = [r for r in regions
              if r.get("kind") == "cell" and not r.get("scriptAnomaly")
              and all(r.get(k) is not None for k in ("table", "row", "col"))]
    assert usable, (
        "inspect reported no anomaly-free editable cell; the flow refuses to "
        "invent an address rather than edit a cell the document did not offer")
    chosen = usable[:MAX_FILLED_CELLS]
    ops = [{"kind": "fill_cell", "table": r["table"], "row": r["row"],
            "col": r["col"], "text": FILL_TEXT} for r in chosen]
    steps["address"] = {"regions": chosen, "ops": ops}

    op_args: list[str] = []
    for op in ops:
        op_args += ["--op", json.dumps(op, ensure_ascii=False)]
    code, proposed = _cli(payload, "propose", "--session", session, *op_args)
    steps["propose"] = {"code": code, "payload": proposed}
    assert code == 0, proposed
    plan = proposed["result"]["plan"]

    code, requested = _cli(payload, "request-approval", "--plan", plan["planId"])
    steps["request-approval"] = {"code": code, "payload": requested}
    assert code == 0, requested
    approval = requested["result"]["approval"]

    code, approved = _cli(payload, "approve",
                          "--approval", approval["approvalId"],
                          "--plan", plan["planId"],
                          "--plan-hash", plan["planHash"],
                          "--approver", "dist-payload-02")
    steps["approve"] = {"code": code, "payload": approved}
    assert code == 0, approved

    code, applied = _cli(payload, "apply", "--plan", plan["planId"],
                         "--approval", approval["approvalId"])
    steps["apply"] = {"code": code, "payload": applied}
    assert code == 0, applied
    run_id = applied["result"]["candidate"]["runId"]

    code, verified = _cli(payload, "verify", "--session", session,
                          "--run", run_id)
    steps["verify"] = {"code": code, "payload": verified}

    steps["session"] = session
    steps["runId"] = run_id
    _EXECUTED["flow"] = sorted(
        k for k in steps if k not in ("address", "session", "runId"))
    return steps


# --------------------------------------------------------------------------- #
# 1. both distributions installed, from bundles and a wheel
# --------------------------------------------------------------------------- #
class TestPayloadInstall:
    def test_zip_payload_installs_green_with_no_acknowledged_gaps(self, payload):
        report = payload["prepare_report"]
        assert report["ok"] is True, report["failures"]
        assert report["failures"] == []
        assert report["gaps"] == []
        assert report["gaps_acknowledged"] == []

    def test_report_module_is_installed_and_enabled(self, payload):
        report = payload["prepare_report"]
        assert "report" in report["registry"]["discovered"]
        assert sorted(report["registry"]["enabled"]) == ["report", "style"]
        assert sorted(report["probe"]["modules"]["enabled"]) == ["report", "style"]
        for name in ("report", "style"):
            assert (payload["install"] / "modules" / name / "module.yaml").is_file()

    def test_skill_surface_installed_from_the_bundles_alone(self, payload):
        skill = payload["prepare_report"]["skill"]
        assert skill.get("gap") is None, skill
        assert skill["ok"] is True, skill
        installed = payload["sandbox"].skills
        assert installed.is_dir()
        assert any(installed.rglob("SKILL.md")), "no SKILL.md under the sandbox skills root"

    def test_bundle_verify_and_cli_smoke_are_green(self, payload):
        report = payload["prepare_report"]
        assert [row["bundle"] for row in report["verify"]] == [
            path.name for path in payload["bundles"]]
        assert all(row["ok"] for row in report["verify"]), report["verify"]
        assert [row for row in report["cli_smoke"] if not row["ok"]] == []

    def test_the_command_came_from_the_wheel_inside_the_sandbox(self, payload):
        rigorloom = payload["rigorloom"]
        assert cleanroom._is_within(rigorloom, payload["sandbox"].root), (
            f"{rigorloom} is not inside the sandbox")
        site = list((payload["venv"]).rglob(f"{WHEEL_PACKAGE}/cli.py"))
        assert site, "the venv holds no rigorloom_runtime/cli.py"
        assert site[0].read_bytes() == (
            REPO_ROOT / "runtime" / "scripts" / "cli.py").read_bytes(), (
            "the installed CLI is not the repository implementation")


# --------------------------------------------------------------------------- #
# 2. capabilities under the ZIP install (acceptance §5)
# --------------------------------------------------------------------------- #
class TestCapabilitiesOverThePayload:
    def test_engine_tools_resolve_inside_the_installed_payload(self, flow, payload):
        tools = flow["capabilities"]["payload"]["result"]["tools"]
        for name in ENGINE_TOOLS:
            row = tools[name]
            assert row["state"] == "available", (
                f"{name} is {row['state']} under an installed core bundle: "
                f"{row.get('reason')}")
            assert row["path"], f"{name} is available with no path"
            resolved = payload["install"] / row["path"]
            assert resolved.is_file(), f"{name} path does not resolve: {resolved}"

    def test_module_registry_is_found_and_report_is_enabled(self, flow):
        modules = flow["capabilities"]["payload"]["result"]["modules"]
        assert modules["state"] == "ready", modules.get("reason")
        assert "report" in modules["discovered"]
        assert sorted(modules["enabled"]) == ["report", "style"]

    def test_preedit_backend_is_available_and_is_the_only_supported_one(self, flow):
        result = flow["capabilities"]["payload"]["result"]
        assert result["supportedBackends"] == ["preedit"]
        assert result["backends"]["preedit"]["state"] == "available"

    def test_declared_but_unexecuted_backends_stay_unavailable_with_reasons(
            self, flow):
        """XML and COM are protocol vocabulary, not capability."""
        backends = flow["capabilities"]["payload"]["result"]["backends"]
        for name in ("xml", "com"):
            assert backends[name]["state"] == "unavailable"
            assert backends[name]["reason"], f"{name} unavailable with no reason"

    def test_nothing_negative_is_reported_without_a_reason(self, flow):
        negative = {"unavailable", "no", "not_established", "false"}
        unexplained = []

        def walk(node, path="result"):
            if isinstance(node, dict):
                state = node.get("state")
                if isinstance(state, str) and state in negative and not node.get("reason"):
                    unexplained.append(path)
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(flow["capabilities"]["payload"]["result"])
        assert not unexplained, f"negative state without a reason: {unexplained}"


# --------------------------------------------------------------------------- #
# 3. the edit flow (acceptance §4)
# --------------------------------------------------------------------------- #
class TestRuntimeFlowOverThePayload:
    def test_every_step_exited_zero(self, flow):
        codes = {name: flow[name]["code"] for name in
                 ("capabilities", "open", "inspect", "propose",
                  "request-approval", "approve", "apply", "verify")}
        assert codes == dict.fromkeys(codes, 0), codes

    def test_every_step_emitted_one_ok_json_document(self, flow):
        for name in ("capabilities", "open", "inspect", "propose",
                     "request-approval", "approve", "apply", "verify"):
            document = flow[name]["payload"]
            assert document["ok"] is True, (name, document)
            assert "result" in document, name

    def test_every_address_came_from_inspection_not_a_fixture(self, flow):
        reported = flow["inspect"]["payload"]["result"]["regions"]["regions"]
        chosen = flow["address"]["regions"]
        assert chosen, "the flow filled nothing"
        for region, op in zip(chosen, flow["address"]["ops"]):
            assert region in reported, (
                "the edited address is not one inspect reported")
            assert (op["table"], op["row"], op["col"]) == (
                region["table"], region["row"], region["col"])

    def test_the_plan_is_a_multi_op_plan_on_the_non_native_backend(self, flow):
        plan = flow["propose"]["payload"]["result"]["plan"]
        assert plan["backend"] == "preedit"
        kinds = [op["kind"] for op in plan["ops"]]
        assert kinds == ["fill_cell"] * len(flow["address"]["ops"]), kinds
        assert len(kinds) > 1, "a one-op plan is not a multi-op plan"

    def test_approval_binds_the_plan_hash(self, flow):
        plan = flow["propose"]["payload"]["result"]["plan"]
        approved = flow["approve"]["payload"]["result"]
        assert json.dumps(approved, ensure_ascii=False).find(plan["planHash"]) >= 0, (
            "the approval record does not carry the plan hash it bound")

    def test_apply_published_a_candidate_whose_checks_actually_ran(self, flow):
        checks = flow["apply"]["payload"]["result"]["candidate"]["checks"]
        assert checks["required"] == ["check_residue"], checks["required"]
        assert checks["ranAll"] is True, checks
        row = checks["checks"][0]
        assert row["checker"] == "check_residue"
        assert row["state"] == "ran", row
        assert row["counts"], "the checker returned no counts"

    def test_verify_passed_because_the_checker_ran_not_because_it_skipped(
            self, flow):
        """A skip is not a pass — this is the assertion that says so.

        ``verify`` is fail-closed on RUNNABILITY: it exits 3 when a required
        check could not run (runtime/scripts/cli.py:399). Exit 0 here therefore
        means the residue gate genuinely executed against the published
        candidate under the installed payload — not that it was absent, not
        that it was skipped, and not that its verdict was assumed.
        """
        assert flow["verify"]["code"] == 0, flow["verify"]["payload"]
        checks = flow["verify"]["payload"]["result"]["checks"]
        assert checks["ranAll"] is True, checks
        states = [row["state"] for row in checks["checks"]]
        assert states and set(states) == {"ran"}, checks["checks"]
        assert checks["checks"][0]["exitCode"] is not None

    def test_the_residue_gate_reports_the_unfinished_form_instead_of_passing_it(
            self, flow):
        """The gate is not a rubber stamp, and this test refuses to make it one.

        ``check_residue`` treats the form profile's anchor text as forbidden in
        a FINAL artifact. A Runtime edit fills cells; it does not finish a
        document, so the form's own labels are still present and the checker
        says so. ``acceptance`` is therefore False, truthfully.

        That is a statement about the DOCUMENT, not about the install: the
        checker ran, from the installed core bundle, and returned a real
        verdict with 25 surviving-anchor findings. Asserting
        ``acceptance is True`` would have required either faking a finished
        document or weakening the gate, and DIST-PAYLOAD-02 forbids both.
        Clearing those anchors is the assemble stage's job, not one plan's.
        """
        checks = flow["verify"]["payload"]["result"]["checks"]
        assert checks["acceptance"] is False, checks
        assert checks["reason"] == "a required check reported findings"
        row = checks["checks"][0]
        assert row["ok"] is False
        assert row["verdict"] == "fail"
        assert row["exitCode"] == 3
        assert row["counts"]["forbidden"] > len(flow["address"]["ops"])
        assert row["hard"], "a failing residue verdict with no finding listed"
        assert {finding["code"] for finding in row["hard"]} == {"form_residue"}, (
            "the residue findings are not the expected surviving-anchor class")

    def test_the_candidate_artifact_exists_inside_the_sandbox(self, flow, payload):
        artifact = (payload["runtime_root"] / "sessions" / flow["session"]
                    / "candidates" / flow["runId"] / "artifact.hwpx")
        assert artifact.is_file(), f"no artifact at {artifact}"
        assert cleanroom._is_within(artifact, payload["sandbox"].root)
        with zipfile.ZipFile(artifact) as archive:
            assert archive.namelist(), "the published artifact is an empty zip"

    def test_the_edit_is_readable_back_at_every_chosen_address(self, flow, payload):
        specs = [f"{r['table']}:{r['row']},{r['col']}"
                 for r in flow["address"]["regions"]]
        args: list[str] = []
        for spec in specs:
            args += ["--region", spec]
        code, read = _cli(payload, "read-region", "--session", flow["session"],
                          *args, "--run", flow["runId"])
        assert code == 0, read
        blob = json.dumps(read, ensure_ascii=False)
        assert blob.count(FILL_TEXT) >= len(specs), (
            f"the filled text is not readable back at all of {specs}")


# --------------------------------------------------------------------------- #
# 4. containment (acceptance §3 and §6)
# --------------------------------------------------------------------------- #
class TestContainmentAfterTheEdit:
    def test_prepare_reported_containment_before_the_edit(self, payload):
        assert payload["prepare_report"]["containment"]["contained"] is True

    def test_containment_holds_again_after_the_edit(self, flow, payload):
        """Re-run every axis: the edit published files prepare never saw."""
        report = cleanroom.containment_report(payload["sandbox"])
        assert report["contained"] is True, report["findings"]
        assert str(REPO_ROOT.resolve()) in report["forbidden_roots"]

    def test_the_environment_cannot_reach_the_checkout(self, payload):
        env = payload["sandbox"].env
        assert "PYTHONPATH" not in env
        assert "PYTHONHOME" not in env
        assert cleanroom._is_within(env["RIGORLOOM_ROOT"], payload["sandbox"].root)
        for entry in env.get("PATH", "").split(os.pathsep):
            if entry:
                assert not cleanroom._is_within(entry, REPO_ROOT), entry
        for name, value in env.items():
            if name in ("PATH", "TEMP", "TMP", "TMPDIR"):
                continue
            assert not cleanroom._is_within(value, REPO_ROOT), (name, value)

    def test_no_command_run_in_the_sandbox_named_the_checkout(self, payload):
        for record in payload["sandbox"].commands:
            for token in record["argv"]:
                assert not cleanroom._is_within(token, REPO_ROOT), record
            assert not cleanroom._is_within(record["cwd"], REPO_ROOT), record

    def test_the_checkout_cli_was_never_invoked(self, payload):
        """Requirement 3: the venv executable, never runtime/scripts/cli.py."""
        for record in payload["sandbox"].commands:
            joined = "/".join(record["argv"]).replace("\\", "/")
            assert "runtime/scripts/cli.py" not in joined, record
        assert any(str(payload["rigorloom"]) in record["argv"]
                   for record in payload["sandbox"].commands), (
            "no recorded command ran the installed rigorloom executable")

    def test_no_flow_output_path_resolves_to_the_checkout(self, flow, payload):
        for name in ("capabilities", "open", "inspect", "propose",
                     "request-approval", "approve", "apply", "verify"):
            blob = json.dumps(flow[name]["payload"], ensure_ascii=False)
            assert str(REPO_ROOT) not in blob, name
            assert str(REPO_ROOT).replace("\\", "/") not in blob, name

    def test_checkout_fallback_is_off_when_no_engine_root_is_given(self, payload):
        """The fallback is ``__file__``-derived; from site-packages it must
        find nothing, and it must never find this checkout."""
        code, bare = _cli(payload, "capabilities", engine_root=False)
        assert code == 0, bare
        result = bare["result"]
        for name in ENGINE_TOOLS:
            row = result["tools"][name]
            assert row["state"] == "unavailable", (
                f"with no --engine-root, {name} resolved anyway: {row}")
            assert row["reason"], name
            assert row["path"] is None, row
        assert result["modules"]["state"] == "unavailable"
        assert str(REPO_ROOT) not in json.dumps(bare, ensure_ascii=False)

    def test_the_document_and_every_artifact_live_inside_the_sandbox(
            self, flow, payload, document):
        root = payload["sandbox"].root
        assert cleanroom._is_within(document, root)
        assert cleanroom._is_within(payload["runtime_root"], root)
        assert cleanroom._is_within(payload["install"], root)
        assert cleanroom._is_within(payload["venv"], root)
        assert cleanroom._is_within(payload["local_wheel"], root)


# --------------------------------------------------------------------------- #
# 5. the document is PII-free, checked by the installed scanner
# --------------------------------------------------------------------------- #
class TestDocumentIsPiiFree:
    """The document is PII-free by evidence, not by assertion.

    ``privacy_scan`` has a categorical rule: an unlisted binary document is
    HARD wherever it sits, because a scanner cannot vouch for bytes nobody
    pinned. Pinning it is the documented way through (``--binary-allowlist``,
    the W5.2 corpus ruling), and a pinned file is NOT waved past — the content
    backstop still runs over the extracted hwpx text for resident registration
    numbers, filled phone numbers, e-mail addresses, user paths and the
    denylist. So the pin buys a real content scan, not a free pass.

    The manifest is synthesised INSIDE the sandbox over the sandbox's own copy,
    which keeps containment intact: handing the scanner the checkout's corpus
    manifest would have put a forbidden path into the sandbox to prove the
    sandbox has no forbidden paths.
    """

    def test_the_installed_privacy_scanner_clears_the_sandbox_document(
            self, payload, document):
        scanner = payload["install"] / "pipeline" / "scripts" / "privacy_scan.py"
        assert scanner.is_file(), "the core bundle ships no privacy_scan.py"

        digest = hashlib.sha256(document.read_bytes()).hexdigest()
        manifest = document.parent / "corpus-allowlist.json"
        manifest.write_text(json.dumps({
            "description": "sandbox-local binary allowlist for the copied "
                           "blank form; content scanning still applies",
            "documents": [{"path": document.name, "sha256": digest}],
        }, indent=2) + "\n", encoding="utf-8")

        proc = payload["sandbox"].run_python(
            scanner, [str(document.parent),
                      "--binary-allowlist", str(manifest)],
            timeout=BUILD_TIMEOUT)
        assert proc.returncode == 0, (
            "the installed privacy scanner reported findings on the document "
            f"copied into the sandbox (exit {proc.returncode}):\n"
            f"{(proc.stdout or '')[-3000:]}\n{(proc.stderr or '')[-1500:]}")
        assert "HARD=0" in (proc.stdout or ""), proc.stdout[-2000:]

    def test_an_unpinned_binary_would_have_been_refused(self, payload, document):
        """Non-vacuity: the clean result above is the pin, not a blind scanner."""
        proc = payload["sandbox"].run_python(
            payload["install"] / "pipeline" / "scripts" / "privacy_scan.py",
            [str(document.parent)], timeout=BUILD_TIMEOUT)
        assert proc.returncode == 3, (
            "an unpinned binary document passed the privacy gate; the clean "
            "verdict above would then prove nothing")
        assert "binary_document_ext" in (proc.stdout or "")


# --------------------------------------------------------------------------- #
# 6. the wheel stayed narrow (acceptance §7)
# --------------------------------------------------------------------------- #
class TestWheelStayedNarrow:
    def test_the_wheel_carries_only_the_runtime_package(self, built_wheel):
        with zipfile.ZipFile(built_wheel) as archive:
            names = archive.namelist()
        tops = {name.split("/")[0] for name in names}
        dist_info = {name for name in tops if name.endswith(".dist-info")}
        assert len(dist_info) == 1, dist_info
        assert tops == {WHEEL_PACKAGE} | dist_info, sorted(tops)

    def test_the_wheel_did_not_swallow_the_zip_payload(self, built_wheel):
        with zipfile.ZipFile(built_wheel) as archive:
            names = [name.lower() for name in archive.namelist()]
        for directory in FORBIDDEN_IN_WHEEL_DIRS:
            assert not any(part == directory
                           for name in names for part in name.split("/")[:-1]), (
                f"the wheel reaches into {directory}/")
        for filename in FORBIDDEN_IN_WHEEL_FILES:
            assert not any(name.endswith("/" + filename.lower())
                           for name in names), f"the wheel ships {filename}"
        for suffix in FORBIDDEN_IN_WHEEL_SUFFIXES:
            offenders = [name for name in names if name.endswith(suffix)]
            assert not offenders, f"the wheel ships {suffix}: {offenders[:5]}"

    def test_the_two_distributions_stayed_separate(self, payload):
        """The engine a buyer edits with came from the ZIP, not from the wheel."""
        venv = payload["venv"]
        assert not list(venv.rglob("form_inspect.py"))
        assert not list(venv.rglob("check_residue.py"))
        assert not list(venv.rglob("module_registry.py"))
        assert (payload["install"] / "engine" / "scripts" / "form_inspect.py").is_file()
        assert (payload["install"] / "pipeline" / "scripts" / "check_residue.py").is_file()


# --------------------------------------------------------------------------- #
# 7. a skip is not a pass
# --------------------------------------------------------------------------- #
def test_no_axis_was_silently_skipped(payload, flow):
    """Green here must mean the heavy path ran, not that it was skipped."""
    assert _EXECUTED.get("payload") is True
    assert _EXECUTED.get("flow") == [
        "apply", "approve", "capabilities", "inspect", "open", "propose",
        "request-approval", "verify"], _EXECUTED.get("flow")
