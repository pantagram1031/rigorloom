from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import check_convert_parity  # noqa: E402
import content_extract  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


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


def test_convert_parity_canonicalizes_bare_script_braces(tmp_path: Path) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx", inline_equation_script="x^2")
    assembled = write_hwpx(
        tmp_path / "assembled.hwpx", inline_equation_script="x^{2}")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0

    verdict, code = check_convert_parity.check(out_dir, assembled)

    assert code == 0, verdict


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
