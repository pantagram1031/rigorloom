"""Adversarial tests for the receipt-only HWPX equation diagnostic (T91)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hwp_equation_diagnostic as diagnostic  # noqa: E402
import doc_backend  # noqa: E402
import render_probe  # noqa: E402


HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"


def _hpf(section_hrefs: list[str]) -> str:
    items = [
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>',
    ]
    refs = []
    for index, href in enumerate(section_hrefs):
        identifier = f"section{index}"
        items.append(
            f'<opf:item id="{identifier}" href="{href}" media-type="application/xml"/>')
        refs.append(f'<opf:itemref idref="{identifier}"/>')
    return (
        f'<opf:package xmlns:opf="{OPF}" id="package" '
        'unique-identifier="uid" version="1.0">'
        '<opf:metadata><opf:title/><opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="test"/></opf:metadata>'
        f'<opf:manifest>{"".join(items)}</opf:manifest>'
        f'<opf:spine>{"".join(refs)}</opf:spine></opf:package>')


def _container() -> str:
    return (
        f'<ocf:container xmlns:ocf="{OCF}"><ocf:rootfiles>'
        '<ocf:rootfile full-path="Contents/content.hpf" '
        'media-type="application/hwpml-package+xml"/>'
        '</ocf:rootfiles></ocf:container>')


def _section(scripts: list[str], *, prefix: str = "hp") -> str:
    eqs = "".join(
        f'<{prefix}:equation><{prefix}:script>{script}</{prefix}:script></{prefix}:equation>'
        for script in scripts)
    return (
        f'<hs:sec xmlns:hs="{HS}" xmlns:{prefix}="{HP}">'
        f'<{prefix}:p><{prefix}:run>{eqs}</{prefix}:run></{prefix}:p>'
        '</hs:sec>')


def _package(path: Path, sections: list[str], *, hpf: str | None = None,
             extra: list[tuple[str, bytes | str]] | None = None) -> Path:
    hrefs = [f"Contents/section{i}.xml" for i in range(len(sections))]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip",
                         compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", _container())
        archive.writestr("Contents/content.hpf", hpf or _hpf(hrefs))
        archive.writestr("Contents/header.xml",
                         f'<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"/>')
        for href, section in zip(hrefs, sections):
            archive.writestr(href, section)
        for name, value in extra or []:
            archive.writestr(name, value)
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "hwp-equation-diagnostic"
    root.mkdir()
    return root


def test_valid_equations_are_counted_in_spine_order_without_script_text(tmp_path: Path):
    source = _package(tmp_path / "input.hwpx", [_section(["x over y", "sqrt {x}"]),
                                               _section(["a^{2}"])])
    payload = diagnostic.inspect_path(source)
    assert payload["schema"] == "rigorloom/hwp-equation-diagnostic/v1"
    assert payload["status"] == "analyzed"
    assert payload["structure"]["state"] == "complete"
    assert payload["equations"]["count"] == 3
    assert payload["equations"]["spine_ordinal_counts"] == [2, 1]
    assert payload["equations"]["script_semantics"] == "not_scanned"
    assert set(payload["equations"]) == {
        "count", "spine_ordinal_counts", "script_semantics"}
    rendered = json.dumps(payload, sort_keys=True)
    for secret in ("x over y", "sqrt {x}", "a^{2}", "section0.xml", str(tmp_path)):
        assert secret not in rendered


def test_missing_or_duplicate_script_is_refused(tmp_path: Path):
    missing = _package(
        tmp_path / "missing.hwpx",
        [_section([]).replace("<hp:run></hp:run>", "<hp:run><hp:equation/></hp:run>")],
    )
    duplicate = _package(
        tmp_path / "duplicate.hwpx",
        [_section(["x"]).replace(
            "</hp:equation>", "<hp:script>y</hp:script></hp:equation>")],
    )
    assert diagnostic.inspect_path(missing)["status"] == "refused"
    assert diagnostic.inspect_path(duplicate)["status"] == "refused"


def test_opaque_hwp_eqn_script_is_not_interpreted_or_emitted(tmp_path: Path):
    source = _package(tmp_path / "opaque.hwpx", [_section([r"\\frac{1}{2}"])])
    payload = diagnostic.inspect_path(source)
    assert payload["status"] == "analyzed"
    assert payload["equations"]["script_semantics"] == "not_scanned"
    assert r"\\frac" not in json.dumps(payload)


def test_exact_namespace_accepts_alternate_prefix_and_ignores_fake_or_comment(tmp_path: Path):
    alternate = _package(tmp_path / "alternate.hwpx", [_section(["x"], prefix="x")])
    fake = _package(
        tmp_path / "fake.hwpx",
        [_section([]).replace(
            "<hp:run></hp:run>",
            "<hp:run><!-- <hp:equation/> --><hp:equationFake/></hp:run>")],
    )
    assert diagnostic.inspect_path(alternate)["equations"]["count"] == 1
    assert diagnostic.inspect_path(fake)["equations"]["count"] == 0


def test_foreign_namespace_wrong_parent_and_nested_script_refuse(tmp_path: Path):
    foreign = _package(
        tmp_path / "foreign.hwpx",
        [_section([]).replace(
            "<hp:run></hp:run>",
            '<hp:run><z:equation xmlns:z="urn:foreign"/></hp:run>')],
    )
    wrong_parent = _package(
        tmp_path / "wrong-parent.hwpx",
        [_section([]).replace(
            "<hp:run></hp:run>",
            "<hp:run><hp:container><hp:equation><hp:script>x</hp:script>"
            "</hp:equation></hp:container></hp:run>")],
    )
    nested = _package(
        tmp_path / "nested.hwpx",
        [_section(["x"]).replace(
            "<hp:script>x</hp:script>",
            "<hp:container><hp:script>x</hp:script></hp:container>")],
    )
    for source in (foreign, wrong_parent, nested):
        assert diagnostic.inspect_path(source)["status"] == "refused"


def test_orphan_script_and_mixed_equation_content_refuse(tmp_path: Path):
    orphan = _package(
        tmp_path / "orphan.hwpx",
        [_section([]).replace(
            "<hp:run></hp:run>", "<hp:run><hp:script>x</hp:script></hp:run>")],
    )
    mixed_text = _package(
        tmp_path / "mixed-text.hwpx",
        [_section(["x"]).replace("<hp:equation>", "<hp:equation>raw")],
    )
    mixed_child = _package(
        tmp_path / "mixed-child.hwpx",
        [_section(["x"]).replace(
            "</hp:equation>", "<hp:t>extra</hp:t></hp:equation>")],
    )
    for source in (orphan, mixed_text, mixed_child):
        payload = diagnostic.inspect_path(source)
        assert payload["status"] == "refused"


def test_strict_ocf_and_spine_are_required(tmp_path: Path):
    bad = _package(tmp_path / "bad.hwpx", [_section(["x"])])
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(bad, "a") as archive:
            archive.writestr("META-INF/container.xml", b"<broken/>")
    payload = diagnostic.inspect_path(bad)
    assert payload["status"] == "refused"


def test_receipt_only_publish_and_verify_bind_current_source(tmp_path: Path):
    source = _package(tmp_path / "input.hwpx", [_section(["x"])])
    root = _root(tmp_path)
    run_id = "0123456789abcdef"
    result = diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)
    receipt = root / run_id / "receipt.json"
    assert result["status"] == "analyzed"
    assert receipt.is_file()
    assert diagnostic.verify_path(source, diagnostic_root=root, run_id=run_id)["status"] == "analyzed"
    source.write_bytes(source.read_bytes() + b"drift")
    with pytest.raises(diagnostic.CoverageError):
        diagnostic.verify_path(source, diagnostic_root=root, run_id=run_id)


def test_verify_rechecks_source_after_final_receipt_read(tmp_path: Path, monkeypatch):
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    replacement = _package(tmp_path / "replacement.hwpx", [_section(["y"])]).read_bytes()
    root = _root(tmp_path)
    run_id = "1111111111111111"
    diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)
    original = diagnostic._read_receipt
    calls = 0

    def mutate_after_final_read(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            source.write_bytes(replacement)
        return result

    monkeypatch.setattr(diagnostic, "_read_receipt", mutate_after_final_read)
    with pytest.raises(diagnostic.CoverageError, match="input_changed"):
        diagnostic.verify_path(source, diagnostic_root=root, run_id=run_id)


def test_publish_rechecks_source_after_final_public_receipt_validation(
    tmp_path: Path, monkeypatch,
):
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    replacement = _package(tmp_path / "replacement.hwpx", [_section(["y"])]).read_bytes()
    root = _root(tmp_path)
    run_id = "2222222222222222"
    original = diagnostic._read_receipt
    calls = 0

    def mutate_after_final_validation(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 3:
            source.write_bytes(replacement)
        return result

    monkeypatch.setattr(diagnostic, "_read_receipt", mutate_after_final_validation)
    with pytest.raises(diagnostic.CoverageError, match="input_changed"):
        diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)
    assert not (root / run_id).exists()


def test_publish_rechecks_receipt_after_final_source_commit(
    tmp_path: Path, monkeypatch,
) -> None:
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    root = _root(tmp_path)
    run_id = "2323232323232323"
    original = diagnostic._read_input_once
    calls = 0

    def mutate_receipt_during_final_source_read(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 3:
            receipt = root / run_id / "receipt.json"
            receipt.chmod(0o600)
            receipt.write_bytes(b'{"forged":true}')
        return result

    monkeypatch.setattr(
        diagnostic, "_read_input_once", mutate_receipt_during_final_source_read)

    with pytest.raises(diagnostic.CoverageError):
        diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)


def test_verify_rechecks_receipt_after_final_source_read(
    tmp_path: Path, monkeypatch,
) -> None:
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    root = _root(tmp_path)
    run_id = "2424242424242424"
    diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)
    original = diagnostic._read_input_once
    calls = 0

    def mutate_receipt_during_final_source_read(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 3:
            receipt = root / run_id / "receipt.json"
            receipt.chmod(0o600)
            receipt.write_bytes(b'{"forged":true}')
        return result

    monkeypatch.setattr(
        diagnostic, "_read_input_once", mutate_receipt_during_final_source_read)

    with pytest.raises(diagnostic.CoverageError):
        diagnostic.verify_path(source, diagnostic_root=root, run_id=run_id)


def test_publish_rechecks_receipt_after_final_root_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    root = _root(tmp_path)
    run_id = "2525252525252525"
    original = diagnostic._core.check_root_guard
    public_guards = 0

    def mutate_after_guard(*args, **kwargs):
        nonlocal public_guards
        result = original(*args, **kwargs)
        receipt = root / run_id / "receipt.json"
        if receipt.is_file():
            public_guards += 1
            if public_guards == 2:
                receipt.chmod(0o600)
                receipt.write_bytes(b'{"forged":true}')
        return result

    monkeypatch.setattr(diagnostic._core, "check_root_guard", mutate_after_guard)

    with pytest.raises(diagnostic.CoverageError):
        diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)


def test_verify_rechecks_receipt_after_final_root_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    source = _package(tmp_path / "input.hwpx", [_section(["x"])]).resolve()
    root = _root(tmp_path)
    run_id = "2626262626262626"
    diagnostic.inspect_and_publish(source, diagnostic_root=root, run_id=run_id)
    original = diagnostic._core.check_root_guard
    calls = 0

    def mutate_after_final_guard(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 3:
            receipt = root / run_id / "receipt.json"
            receipt.chmod(0o600)
            receipt.write_bytes(b'{"forged":true}')
        return result

    monkeypatch.setattr(
        diagnostic._core, "check_root_guard", mutate_after_final_guard)

    with pytest.raises(diagnostic.CoverageError):
        diagnostic.verify_path(source, diagnostic_root=root, run_id=run_id)


def test_receipt_states_keep_execution_and_proof_separate(tmp_path: Path):
    source = _package(tmp_path / "input.hwpx", [_section([])])
    payload = diagnostic.inspect_path(source)
    assert payload["equations"]["count"] == 0
    assert payload["execution"] == {"state": "not_run"}
    assert payload["diagnostic_artifact"] == {"state": "none"}
    assert payload["native"] == {"state": "not_run"}
    assert payload["render"] == {"state": "not_run"}
    assert payload["comparison"] == {"state": "unknown"}
    assert payload["proof_grade"] == "none"
    assert payload["submission_grade"] is False


def test_cli_usage_and_always_refused_exit_for_analyzed_receipt(tmp_path: Path):
    script = SCRIPTS / "hwp_equation_diagnostic.py"
    help_proc = subprocess.run([sys.executable, str(script), "--help"],
                               capture_output=True, text=True)
    assert help_proc.returncode == 0
    source = _package(tmp_path / "input.hwpx", [_section(["x"])])
    root = _root(tmp_path)
    proc = subprocess.run([
        sys.executable, str(script), "inspect", str(source),
        "--diagnostic-root", str(root), "--run-id", "0123456789abcdef",
    ], capture_output=True, text=True)
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["status"] == "analyzed"

    secret = str(tmp_path / "PRIVATE" / "secret.hwpx")
    usage = subprocess.run(
        [sys.executable, str(script), "--not-a-real-option", secret],
        capture_output=True, text=True,
    )
    assert usage.returncode == 2
    assert secret not in usage.stdout
    assert secret not in usage.stderr
    assert str(script.parent) not in usage.stderr
    assert "invalid arguments" in usage.stderr


def test_alt_prefix_equation_can_never_route_to_libreoffice_advisory(
    tmp_path: Path, monkeypatch,
):
    workspace = tmp_path / "workspace"
    (workspace / "output").mkdir(parents=True)
    (workspace / "bundle").mkdir()
    (workspace / "bundle" / "content.md").write_text("plain", encoding="utf-8")
    _package(workspace / "output" / "form_copy.hwpx", [_section(["x"], prefix="x")])
    monkeypatch.setattr(render_probe, "probe", lambda **_kwargs: {
        "capabilities": {"hancom_com": False},
        "renderers": [{"name": "soffice_local", "wsl": False,
                       "argv": ["soffice", "--headless"]}],
    })

    decision = doc_backend._hwpx_renderer_decision(str(workspace), None)

    assert decision["equations"] is True
    assert decision["selected"] is None
    assert decision["proof_grade"] == "none"
    assert decision["reason"] == "renderer_cannot_eqn"
