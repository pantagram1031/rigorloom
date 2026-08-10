from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from _module_gating import core_only, requires_report_module


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "new_report.py"
SPEC = importlib.util.spec_from_file_location("new_report", MODULE_PATH)
new_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(new_report)


def _ingress_pair(tmp_path: Path) -> tuple[Path, Path]:
    form = tmp_path / "converted.hwpx"
    with zipfile.ZipFile(form, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
            'media-type="application/hwpml-package+xml"/></ocf:rootfiles>'
            '</ocf:container>',
        )
        archive.writestr(
            "Contents/content.hpf",
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
            '<opf:manifest><opf:item id="section0" href="section0.xml" '
            'media-type="application/xml"/></opf:manifest><opf:spine>'
            '<opf:itemref idref="section0"/></opf:spine></opf:package>',
        )
        archive.writestr("Contents/section0.xml", "<sec><p><t>FIXTURE</t></p></sec>")
    data = form.read_bytes()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "schema": "rigorloom/hwp-ingress/v1", "status": "converted",
        "reason": "converted", "proof_grade": "none",
        "source": {
            "format": "hwp", "version": "5.0.0.0", "bytes": 512,
            "sha256": "a" * 64, "compressed": True, "security_flags": [],
        },
        "execution": {"state": "succeeded", "adapter": "hancom"},
        "comparison": {
            "state": "passed", "method": "same_com_extractor",
            "text_hash_match": True, "text_chars_match": True,
            "aggregate_counts_match": True, "control_counts_match": True,
        },
        "output": {
            "state": "published", "format": "hwpx", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "counts": {"tables": 0, "pictures": 0, "equations": 0},
        },
    }, sort_keys=True), encoding="utf-8")
    return form, receipt


def test_slug_cannot_escape_workspace_root(tmp_path: Path):
    for value in ("../outside", "x/../../../outside", "has space", ""):
        try:
            new_report._assert_safe_workspace(tmp_path, value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe slug accepted: {value!r}")


def test_yaml_string_handles_quotes_and_newlines():
    encoded = new_report._yaml_string('question "one"\nquestion two')
    assert '\\n' in encoded
    assert '\\"one\\"' in encoded


def test_scaffolder_refuses_binary_hwp_before_creating_workspace(tmp_path: Path):
    form = tmp_path / "candidate.hwp"
    form.write_bytes(b"synthetic-not-a-real-form")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "hwp-refusal",
            "--subject", "science", "--topic", "topic", "--form", str(form),
            "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert "hwp_ingress.py" in proc.stderr
    assert not root.exists()


def test_scaffolder_refuses_claimed_hwp_ingress_without_valid_receipt(tmp_path: Path):
    form = tmp_path / "claimed.hwpx"
    form.write_bytes(b"not-a-valid-hwpx")
    receipt = tmp_path / "story-edit-receipt.json"
    receipt.write_text(json.dumps({
        "schema": "rigorloom/hwpx-story-edit/v1", "status": "passed",
        "render": "not_run",
    }), encoding="utf-8")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "hwp-ingress-refusal",
            "--subject", "science", "--topic", "topic", "--form", str(form),
            "--ingress-receipt", str(receipt), "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert proc.stderr.strip() == "error: ingress receipt is invalid or stale"
    assert not root.exists()


def test_scaffolder_rejects_foreign_diagnostic_receipt_without_workspace(
        tmp_path: Path):
    """T86 quarantine receipts are not canonical Stage-0 ingress claims."""
    form, receipt = _ingress_pair(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["schema"] = "rigorloom/hwp-diagnostic-candidate/v1"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "foreign-diagnostic",
            "--subject", "science", "--topic", "topic", "--form", str(form),
            "--ingress-receipt", str(receipt), "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert proc.stderr.strip() == "error: ingress receipt is invalid or stale"
    assert not root.exists()


def test_scaffolder_rejects_raw_quarantined_diagnostic_candidate(
        tmp_path: Path):
    form, _ = _ingress_pair(tmp_path)
    diagnostic_form = (
        tmp_path / "work" / "stage-0" / "scratch" / "hwp-diagnostic"
        / "0123456789abcdef0123456789abcdef" / "candidate.hwpx"
    )
    diagnostic_form.parent.mkdir(parents=True)
    diagnostic_form.write_bytes(form.read_bytes())
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "raw-diagnostic",
            "--subject", "science", "--topic", "topic", "--form",
            str(diagnostic_form), "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert proc.stderr.strip() == (
        "error: diagnostic candidate is quarantined and cannot enter a report workspace"
    )
    assert not root.exists()


def test_scaffolder_rejects_raw_java_diagnostic_candidate(
        tmp_path: Path):
    form, _ = _ingress_pair(tmp_path)
    diagnostic_form = (
        tmp_path / "work" / "stage-0" / "scratch" / "hwp-java-diagnostic"
        / "0123456789abcdef0123456789abcdef" / "candidate.hwpx"
    )
    diagnostic_form.parent.mkdir(parents=True)
    diagnostic_form.write_bytes(form.read_bytes())
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "raw-java-diagnostic",
            "--subject", "science", "--topic", "topic", "--form",
            str(diagnostic_form), "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert proc.stderr.strip() == (
        "error: diagnostic candidate is quarantined and cannot enter a report workspace"
    )
    assert not root.exists()


def test_scaffolder_rejects_java_diagnostic_receipt_without_workspace(
        tmp_path: Path):
    form, receipt = _ingress_pair(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["schema"] = "rigorloom/hwp-java-diagnostic-candidate/v1"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "foreign-java-diagnostic",
            "--subject", "science", "--topic", "topic", "--form", str(form),
            "--ingress-receipt", str(receipt), "--workspace-root", str(root),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 3
    assert proc.stderr.strip() == "error: ingress receipt is invalid or stale"
    assert not root.exists()


def test_scaffolder_retains_verified_ingress_pair_and_canonical_path(tmp_path: Path, monkeypatch):
    form, receipt = _ingress_pair(tmp_path)
    stub = tmp_path / "stub.py"
    stub.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "if len(sys.argv)>1 and sys.argv[1]=='init':\n"
        " ws=Path(sys.argv[2]); value=sys.argv[sys.argv.index('--form')+1]\n"
        " (ws/'PIPELINE.md').write_text('form: '+value, encoding='utf-8')\n"
        "print('{}')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(new_report, "_module_cli_script", lambda command: stub)
    monkeypatch.setattr(new_report, "PERSONALIZATION_CTL", stub)
    root = tmp_path / "runs"
    monkeypatch.setattr(sys, "argv", [
        str(MODULE_PATH), "--slug", "verified", "--subject", "science",
        "--topic", "topic", "--form", str(form),
        "--ingress-receipt", str(receipt), "--workspace-root", str(root),
        "--profile-root", str(tmp_path / "profiles"),
    ])
    assert new_report.main() == 0
    workspace = root / "report-verified"
    canonical = workspace / "output" / "form_copy.hwpx"
    retained = workspace / "output" / "proof" / "ingress" / "receipt.json"
    assert canonical.read_bytes() == form.read_bytes()
    assert retained.read_bytes() == receipt.read_bytes()
    assert str(canonical) in (workspace / "PIPELINE.md").read_text(encoding="utf-8")
    request_form = next(
        line.split(":", 1)[1].strip()
        for line in (workspace / "request.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("form:")
    )
    assert json.loads(request_form) == str(canonical)


@core_only
def test_scaffolder_refuses_clearly_without_report_module(tmp_path: Path):
    """Core-only: the scaffolder must name the missing report module, not
    crash on a dangling path (v0.16 W3-S2b decision 6)."""
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"fixture")
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "demo",
            "--subject", "science", "--topic", "topic", "--form", str(form),
            "--workspace-root", str(tmp_path / "runs"),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode != 0
    assert "report distribution module" in (proc.stderr + proc.stdout)


@requires_report_module
def test_scaffolder_initializes_atomically(tmp_path: Path):
    form = tmp_path / "form #1.hwpx"
    form.write_bytes(b"fixture")
    root = tmp_path / "runs"
    proc = subprocess.run(
        [
            sys.executable, str(MODULE_PATH), "--slug", "demo", "--subject", "science: one",
            "--topic", "line one # literal\nline two", "--form", str(form),
            "--workspace-root", str(root),
            # Pin the personalization store to tmp_path: new_report falls back
            # to REPO_ROOT/.local/personalization when --profile-root is
            # omitted, so this test wrote into the repo checkout (issue #12).
            "--profile-root", str(tmp_path / "personalization"),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    workspace = Path(payload["workspace"])
    assert workspace == root / "report-demo"
    assert (workspace / "PIPELINE.md").exists()
    assert (workspace / "NEXT_TASK.md").exists()
    assert (workspace / "WORKSPACE_INDEX.md").exists()
    assert (workspace / ".pipeline" / "artifacts.json").exists()
    assert (workspace / "work" / "stage-0" / "scratch").is_dir()
    handoff = json.loads((workspace / ".pipeline" / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["workspace"] == str(workspace.resolve())
    assert not list(root.glob(".creating-*"))
