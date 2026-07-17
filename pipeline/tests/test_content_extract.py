from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import content_extract  # noqa: E402
from hwpx_test_utils import IMAGE, write_hwpx  # noqa: E402


def test_extract_round_trip_counts_text_objects_and_verify(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx")
    out_dir = tmp_path / "extract"

    verdict, code = content_extract.run_extract(source, out_dir)

    assert code == 0, verdict
    manifest = json.loads(
        (out_dir / "extraction_manifest.json").read_text(encoding="utf-8"))
    content = (out_dir / "content.md").read_text(encoding="utf-8")
    assert manifest["counts"] == {
        "paragraphs": 12, "tables": 1, "pictures": 1, "equations": 1}
    assert manifest["counts"] == manifest["content_semantic_fingerprint"]["counts"]
    assert manifest["semantic_fingerprint"]["normalized_text_sha256"] == (
        manifest["content_semantic_fingerprint"]["normalized_text_sha256"])
    assert "Alpha body." in content
    assert '[[EQ hwpeqn="x over y"]]' in content
    assert '[[TABLE caption="Table 1. Measurements"]]' in content
    assert "| C | 2 |" in content
    assert '[[FIG file="picture-001.png" binary_ref="image1" ' in content
    assert 'caption="Figure 1. Plot"' in content
    assert (out_dir / "figures" / "picture-001.png").read_bytes() == IMAGE

    verified, verify_code = content_extract.run_extract(
        source, out_dir, verify=True)
    assert verify_code == 0, verified
    assert verified["verified"] is True


def test_verify_hard_fails_tampered_extract(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx")
    out_dir = tmp_path / "extract"
    assert content_extract.run_extract(source, out_dir)[1] == 0
    content = out_dir / "content.md"
    content.write_text(content.read_text(encoding="utf-8") + "tampered\n",
                       encoding="utf-8")

    verdict, code = content_extract.run_extract(source, out_dir, verify=True)

    assert code == 3
    assert any(item["code"] == "extraction_infidelity"
               for item in verdict["hard"])


def test_picture_in_cell_round_trips_binary_counts_and_verify(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", picture_in_cell=True)
    out_dir = tmp_path / "extract"

    verdict, code = content_extract.run_extract(source, out_dir, verify=True)

    assert code == 0, verdict
    manifest = json.loads(
        (out_dir / "extraction_manifest.json").read_text(encoding="utf-8"))
    content = (out_dir / "content.md").read_text(encoding="utf-8")
    assert manifest["counts"] == manifest["content_semantic_fingerprint"]["counts"]
    assert manifest["counts"]["pictures"] == 2
    assert content.count("[[FIG ") == 2
    assert (out_dir / "figures" / "picture-001.png").read_bytes() == IMAGE
    assert (out_dir / "figures" / "picture-002.png").read_bytes() == IMAGE

    content_path = out_dir / "content.md"
    first_figure = next(
        line for line in content.splitlines() if line.startswith("[[FIG "))
    content_path.write_text(content.replace(first_figure, "", 1), encoding="utf-8")
    tampered, tampered_code = content_extract.run_extract(
        source, out_dir, verify=True)
    assert tampered_code == 3
    assert any(item["code"] == "extraction_infidelity"
               for item in tampered["hard"])


def test_equation_in_cell_round_trips_script_counts_and_verify(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", equation_in_cell=True)
    out_dir = tmp_path / "extract"

    verdict, code = content_extract.run_extract(source, out_dir, verify=True)

    assert code == 0, verdict
    manifest = json.loads(
        (out_dir / "extraction_manifest.json").read_text(encoding="utf-8"))
    content = (out_dir / "content.md").read_text(encoding="utf-8")
    assert manifest["counts"] == manifest["content_semantic_fingerprint"]["counts"]
    assert manifest["counts"]["equations"] == 2
    assert 'hwpeqn="cell sub 1"' in content

    content_path = out_dir / "content.md"
    cell_equation_line = next(
        line for line in content.splitlines() if 'hwpeqn="cell sub 1"' in line)
    content_path.write_text(
        content.replace(cell_equation_line, "", 1), encoding="utf-8")
    tampered, tampered_code = content_extract.run_extract(
        source, out_dir, verify=True)
    assert tampered_code == 3
    assert any(item["code"] == "extraction_infidelity"
               for item in tampered["hard"])


def test_bracketed_equation_round_trips_fingerprint_and_verify(tmp_path: Path) -> None:
    source = write_hwpx(
        tmp_path / "source.hwpx",
        inline_equation_script="sample = [left, right]",
    )
    out_dir = tmp_path / "extract"

    verdict, code = content_extract.run_extract(source, out_dir, verify=True)

    assert code == 0, verdict
    manifest = json.loads(
        (out_dir / "extraction_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["semantic_fingerprint"]["counts"]["equations"] == 1
    assert manifest["content_semantic_fingerprint"]["counts"]["equations"] == 1
    assert manifest["semantic_fingerprint"]["equation_scripts"] == (
        manifest["content_semantic_fingerprint"]["equation_scripts"]
    )


def test_nested_table_is_flattened_once_and_round_trips(tmp_path: Path) -> None:
    source = write_hwpx(tmp_path / "source.hwpx", nested_table=True)
    out_dir = tmp_path / "extract"

    verdict, code = content_extract.run_extract(source, out_dir, verify=True)

    assert code == 0, verdict
    manifest = json.loads(
        (out_dir / "extraction_manifest.json").read_text(encoding="utf-8"))
    content = (out_dir / "content.md").read_text(encoding="utf-8")
    assert manifest["counts"] == manifest["content_semantic_fingerprint"]["counts"]
    assert manifest["counts"]["tables"] == 2
    assert content.count("[[TABLE") == 2
    assert content.count("Inner A") == 1
    assert content.count("Inner B") == 1
    assert "| C | 2 |" in content
    assert manifest["structural_representation"]["nested_tables"] == (
        "flattened_sequential")

    content_path = out_dir / "content.md"
    table_openings = [
        line for line in content.splitlines() if line.startswith("[[TABLE")]
    content_path.write_text(
        content.replace(table_openings[1], "", 1), encoding="utf-8")
    tampered, tampered_code = content_extract.run_extract(
        source, out_dir, verify=True)
    assert tampered_code == 3
    assert any(item["code"] == "extraction_infidelity"
               for item in tampered["hard"])
