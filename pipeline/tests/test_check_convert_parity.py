from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import zipfile

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import check_convert_parity  # noqa: E402
import content_extract  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


def _rewrite_member(path: Path, member: str, transform) -> None:
    with zipfile.ZipFile(path) as archive:
        rows = [(item.filename, archive.read(item), item.compress_type)
                for item in archive.infolist()]
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload, compression in rows:
            if name == member:
                payload = transform(payload.decode("utf-8")).encode("utf-8")
            archive.writestr(name, payload, compress_type=compression)


def _rewrite_section(path: Path, transform) -> None:
    _rewrite_member(path, "Contents/section0.xml", transform)


def _add_second_section(path: Path, *, reverse_spine: bool) -> None:
    """Add a distinct section, optionally reversing only its OPF spine."""
    with zipfile.ZipFile(path) as archive:
        rows = [(item.filename, archive.read(item), item.compress_type)
                for item in archive.infolist()]
    updated: list[tuple[str, bytes, int]] = []
    for name, payload, compression in rows:
        if name == "Contents/content.hpf":
            text = payload.decode("utf-8")
            text = text.replace(
                '<opf:item id="section0" href="Contents/section0.xml" '
                'media-type="application/xml"/>',
                '<opf:item id="section0" href="Contents/section0.xml" '
                'media-type="application/xml"/>'
                '<opf:item id="section1" href="Contents/section1.xml" '
                'media-type="application/xml"/>',
            )
            old_spine = '<opf:spine><opf:itemref idref="section0"/></opf:spine>'
            first, second = (("section1", "section0") if reverse_spine
                             else ("section0", "section1"))
            text = text.replace(
                old_spine,
                f'<opf:spine><opf:itemref idref="{first}"/>'
                f'<opf:itemref idref="{second}"/></opf:spine>',
            )
            payload = text.encode("utf-8")
        updated.append((name, payload, compression))
    section0 = next(payload for name, payload, _compression in updated
                    if name == "Contents/section0.xml")
    section1 = section0.replace(b"Introduction", b"Second section", 1)
    updated.append(("Contents/section1.xml", section1, zipfile.ZIP_STORED))
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload, compression in updated:
            archive.writestr(name, payload, compress_type=compression)


def test_convert_parity_passes_matching_extract_and_assembly(tmp_path: Path) -> None:
    assembled = write_hwpx(tmp_path / "assembled.hwpx")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(assembled, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 0, verdict
    assert verdict["before"] == verdict["after"]


def test_convert_parity_hard_fails_text_drift(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", body="Original body.")
    drifted = write_hwpx(tmp_path / "drifted.hwpx", body="Changed body.")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, drifted)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_content_drift"


def test_convert_parity_hard_fails_equation_script_drift(tmp_path: Path) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx", inline_equation_script="x sub 1")
    drifted = write_hwpx(
        tmp_path / "drifted.hwpx", inline_equation_script="x sub 2")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, drifted)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_equation_drift"]


def test_convert_parity_fails_closed_on_unparsed_brace_spelling(tmp_path: Path) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx", inline_equation_script="x^2")
    assembled = write_hwpx(
        tmp_path / "assembled.hwpx", inline_equation_script="x^{2}")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_equation_drift"]


def test_convert_parity_preserves_equation_whitespace_boundaries(tmp_path: Path) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx", inline_equation_script="sin x")
    assembled = write_hwpx(
        tmp_path / "assembled.hwpx", inline_equation_script="sinx")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_equation_drift"]


def test_convert_parity_hard_fails_opf_spine_order_drift(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", body="First section.")
    assembled = write_hwpx(tmp_path / "assembled.hwpx", body="First section.")
    _add_second_section(source, reverse_spine=False)
    _add_second_section(assembled, reverse_spine=True)
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert any(item["code"] == "convert_section_order_drift"
               for item in verdict["hard"])


def test_convert_parity_hard_fails_equation_only_spine_order_drift(
    tmp_path: Path,
) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx", body="Same body.", inline_equation_script="x")
    assembled = write_hwpx(
        tmp_path / "assembled.hwpx", body="Same body.", inline_equation_script="x")
    _add_second_section(source, reverse_spine=False)
    _add_second_section(assembled, reverse_spine=True)
    for path in (source, assembled):
        _rewrite_member(
            path,
            "Contents/section1.xml",
            lambda xml: xml.replace("Second section", "Introduction")
            .replace("<hp:script>x</hp:script>",
                     "<hp:script>y</hp:script>"),
        )
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert any(item["code"] == "convert_section_order_drift"
               for item in verdict["hard"])


def test_convert_parity_refuses_duplicate_script_loss(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", inline_equation_script="x")
    _rewrite_section(
        source,
        lambda xml: xml.replace(
            "</hp:equation>",
            "<hp:script>REMOVED</hp:script></hp:equation>",
            1,
        ),
    )
    assembled = write_hwpx(tmp_path / "assembled.hwpx", inline_equation_script="x")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_equation_envelope_invalid"]
    assert verdict["hard"][0]["reason"] == "equation_script_count_invalid"


def test_convert_parity_rebinds_source_after_snapshot_fingerprint(
    tmp_path: Path, monkeypatch,
) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", inline_equation_script="x")
    replacement = write_hwpx(
        tmp_path / "replacement.hwpx", inline_equation_script="changed").read_bytes()
    assembled = write_hwpx(tmp_path / "assembled.hwpx", inline_equation_script="x")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0
    original = check_convert_parity.hwp_equation_diagnostic.equation_presence
    calls = 0

    def mutate_live_source_after_snapshot(path):
        nonlocal calls
        result = original(path)
        calls += 1
        if calls == 1:
            source.write_bytes(replacement)
        return result

    monkeypatch.setattr(
        check_convert_parity.hwp_equation_diagnostic, "equation_presence",
        mutate_live_source_after_snapshot,
    )
    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_input_changed"]


def test_convert_parity_rebinds_assembled_after_snapshot_fingerprint(
    tmp_path: Path, monkeypatch,
) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", inline_equation_script="x")
    assembled = write_hwpx(tmp_path / "assembled.hwpx", inline_equation_script="x")
    replacement = write_hwpx(
        tmp_path / "replacement.hwpx", inline_equation_script="changed").read_bytes()
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0
    original = check_convert_parity.hwp_equation_diagnostic.equation_presence
    calls = 0

    def mutate_live_assembled_after_snapshot(path):
        nonlocal calls
        result = original(path)
        calls += 1
        if calls == 2:
            assembled.write_bytes(replacement)
        return result

    monkeypatch.setattr(
        check_convert_parity.hwp_equation_diagnostic, "equation_presence",
        mutate_live_assembled_after_snapshot,
    )
    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_input_changed"]


def test_convert_parity_binds_captured_source_to_extraction_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", inline_equation_script="x")
    assembled = write_hwpx(tmp_path / "assembled.hwpx", inline_equation_script="x")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0
    original = check_convert_parity.source_hwpx

    def mutate_metadata_after_manifest_read(path):
        result = original(path)
        _rewrite_member(
            source, "Contents/content.hpf",
            lambda xml: xml.replace('content="test"', 'content="evil"'),
        )
        return result

    monkeypatch.setattr(
        check_convert_parity, "source_hwpx", mutate_metadata_after_manifest_read)

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_source_binding_invalid"]
    assert verdict["hard"][0]["reason"] == "source_manifest_hash_mismatch"


def test_convert_parity_also_uses_independent_hwpx_fingerprints(
    tmp_path: Path, monkeypatch,
) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", picture_in_cell=True)
    assembled = write_hwpx(tmp_path / "assembled.hwpx")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0
    blind_fingerprint = {
        "normalized_text_sha256": "same",
        "counts": {"paragraphs": 0, "tables": 0, "pictures": 0,
                   "equations": 0},
        "equation_scripts": [],
    }
    monkeypatch.setattr(
        check_convert_parity, "input_fingerprint",
        lambda _path: blind_fingerprint,
    )

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_content_drift"
    assert verdict["source_before"]["counts"]["pictures"] == 2
    assert verdict["source_after"]["counts"]["pictures"] == 1


# ---------------------------------------------------------------------------
# W6.2 (XC-1 §2 formalized): .hwp source leg — raw conversion parity via COM
# ---------------------------------------------------------------------------

def _fake_hwp(tmp_path: Path) -> Path:
    src = tmp_path / "form.hwp"
    src.write_bytes(b"\xd0\xcf\x11\xe0 synthetic OLE stand-in")
    return src


def _allow_synthetic_hwp_preflight(monkeypatch) -> None:
    """Limit legacy COM-mock tests to behavior after the strict T89 gate."""
    monkeypatch.setattr(
        check_convert_parity.hwp_source_coverage,
        "_preflight",
        lambda _data: (object(), (object(), object())),
    )


def test_hwp_leg_unavailable_is_an_explicit_nonpass(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: False)

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 3
    assert verdict["verdict"] == "skip"
    assert verdict["warn"][0]["code"] == "hwp_source_leg_unavailable"


def test_hwp_leg_rejects_malformed_input_before_com_or_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    entered: list[str] = []

    @contextmanager
    def forbidden_guard():
        entered.append("guard")
        yield

    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    monkeypatch.setattr(
        check_convert_parity.hwp_ingress, "_com_serial_guard", forbidden_guard)
    monkeypatch.setattr(
        check_convert_parity, "_com_inspect",
        lambda _path: entered.append("inspect"),
    )

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_input_invalid"
    assert entered == []


def test_hwp_leg_rejects_protected_preflight_before_com_or_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    entered: list[str] = []

    def protected(_data):
        raise check_convert_parity.hwp_source_coverage.CoverageError(
            "protected_properties")

    @contextmanager
    def forbidden_guard():
        entered.append("guard")
        yield

    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    monkeypatch.setattr(
        check_convert_parity.hwp_source_coverage, "_preflight", protected)
    monkeypatch.setattr(
        check_convert_parity.hwp_ingress, "_com_serial_guard", forbidden_guard)
    monkeypatch.setattr(
        check_convert_parity, "_com_inspect",
        lambda _path: entered.append("inspect"),
    )

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_input_invalid"
    assert verdict["hard"][0]["reason"] == "protected_properties"
    assert entered == []


def test_hwp_leg_passes_on_matching_structural_counts(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    counts = content_extract.semantic_fingerprint(assembled)["counts"]
    fake_com = {
        "ok": True,
        "text_chars_total": 999,  # advisory only — must not gate
        "tables": counts["tables"],
        "pictures": counts["pictures"],
        "equations": [{"index": i} for i in range(counts["equations"])],
        "pages": 1,
    }
    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    _allow_synthetic_hwp_preflight(monkeypatch)
    monkeypatch.setattr(check_convert_parity, "_com_inspect", lambda _p: fake_com)

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 0, verdict
    assert verdict["mode"] == "hwp_conversion"
    assert verdict["src_counts"] == verdict["converted_counts"]
    # text-char divergence is recorded but never a finding (XC-1 §2)
    assert verdict["text_chars"]["hwp_com_raw"] == 999
    assert verdict["hard"] == []


def test_com_inspect_uses_t85_bounded_privacy_safe_argv_and_timeout(
    tmp_path: Path, monkeypatch,
) -> None:
    snapshot = tmp_path / "snapshot.hwp"
    snapshot.write_bytes(b"snapshot")
    seen: dict[str, object] = {}

    def fake_ingress(argv, *, timeout):
        seen["argv"] = list(argv)
        seen["timeout"] = timeout
        return {
            "text_sha256": "a" * 64,
            "text_chars_total": 7,
            "counts": {
                "tables": 1, "pictures": 2, "equations": 3,
                "shapes": 4, "pages": 5, "controls_total": 6,
                "field_count": 0,
            },
        }

    monkeypatch.setattr(check_convert_parity.hwp_ingress,
                        "_com_inspect", fake_ingress)
    payload = check_convert_parity._com_inspect(snapshot)

    assert seen["argv"] == [
        sys.executable, str(check_convert_parity.ENGINE_COM_BACKEND), "inspect",
        "--file", str(snapshot), "--preview-chars", "0", "--privacy-safe",
    ]
    assert seen["timeout"] == check_convert_parity.COM_INSPECT_TIMEOUT
    assert payload["equations"] == 3
    assert payload["text_sha256"] == "a" * 64
    assert "script" not in payload


def test_hwp_leg_enters_t85_com_serial_guard(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    counts = content_extract.semantic_fingerprint(assembled)["counts"]
    fake_com = {
        "ok": True, "text_chars_total": 0,
        "tables": counts["tables"], "pictures": counts["pictures"],
        "equations": counts["equations"], "pages": 1,
    }
    entered: list[str] = []

    @contextmanager
    def guard():
        entered.append("entered")
        yield

    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    _allow_synthetic_hwp_preflight(monkeypatch)
    monkeypatch.setattr(check_convert_parity, "_com_inspect", lambda _p: fake_com)
    monkeypatch.setattr(check_convert_parity.hwp_ingress,
                        "_com_serial_guard", guard)

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 0, verdict
    assert entered == ["entered"]


def test_hwp_leg_maps_ingress_com_failure_to_closed_hard_reason(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")

    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    _allow_synthetic_hwp_preflight(monkeypatch)

    def fail(_path):
        raise check_convert_parity.hwp_ingress.IngressError(
            "hancom_counts_missing", "private child diagnostics")

    monkeypatch.setattr(check_convert_parity, "_com_inspect", fail)

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_com_inspect_invalid"
    assert verdict["hard"][0]["reason"] == "hancom_counts_missing"
    assert "private child diagnostics" not in str(verdict)


def test_hwp_leg_runs_com_on_snapshot_and_rebinds_live_source(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    original = src.read_bytes()
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    counts = content_extract.semantic_fingerprint(assembled)["counts"]
    fake_com = {
        "ok": True,
        "text_chars_total": 0,
        "tables": counts["tables"],
        "pictures": counts["pictures"],
        "equations": [{"index": i} for i in range(counts["equations"])],
        "pages": 1,
    }
    seen = {}

    def mutate_live_source(snapshot):
        seen["snapshot"] = Path(snapshot)
        assert Path(snapshot).read_bytes() == original
        src.write_bytes(b"CHANGED")
        return fake_com

    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    _allow_synthetic_hwp_preflight(monkeypatch)
    monkeypatch.setattr(check_convert_parity, "_com_inspect", mutate_live_source)

    verdict, code = check_convert_parity.check(src, assembled)

    assert seen["snapshot"] != src
    assert code == 3
    assert [item["code"] for item in verdict["hard"]] == [
        "convert_input_changed"]


def test_hwp_leg_hard_fails_structural_drift(
    tmp_path: Path, monkeypatch,
) -> None:
    src = _fake_hwp(tmp_path)
    assembled = write_hwpx(tmp_path / "converted.hwpx")
    counts = content_extract.semantic_fingerprint(assembled)["counts"]
    fake_com = {
        "ok": True,
        "text_chars_total": 0,
        "tables": counts["tables"] + 1,  # one table lost in conversion
        "pictures": counts["pictures"],
        "equations": [{"index": i} for i in range(counts["equations"])],
        "pages": 1,
    }
    monkeypatch.setattr(check_convert_parity, "com_leg_available", lambda: True)
    _allow_synthetic_hwp_preflight(monkeypatch)
    monkeypatch.setattr(check_convert_parity, "_com_inspect", lambda _p: fake_com)

    verdict, code = check_convert_parity.check(src, assembled)

    assert code == 3
    assert verdict["hard"][0]["code"] == "convert_structural_drift"
