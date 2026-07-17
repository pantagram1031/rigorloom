from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

import form_extract  # noqa: E402
from hwpx_test_utils import write_hwpx  # noqa: E402


def test_same_form_yields_stable_skeleton_and_slot_inventory(tmp_path: Path) -> None:
    first = write_hwpx(tmp_path / "one.hwpx", body="First body.",
                       variable_cell="11")
    second = write_hwpx(tmp_path / "two.hwpx", body="Second body.",
                        variable_cell="22")
    out_dir = tmp_path / "template"

    verdict, code = form_extract.extract_forms([first, second], out_dir)

    assert code == 0, verdict
    assert verdict["warn"] == []
    record = json.loads(
        (out_dir / "form_template.json").read_text(encoding="utf-8"))
    assert record["skeleton_stable"] is True
    inventory = record["fill_slot_inventory"]
    assert inventory["counts"]["slots"] == 2
    assert {item["kind"] for item in inventory["slots"]} == {
        "paragraph", "cell"}
    assert inventory["counts"]["chrome"] > 0
    assert (out_dir / "form_template.summary.md").is_file()


def test_diverging_form_instance_is_warn_not_hard(tmp_path: Path) -> None:
    first = write_hwpx(tmp_path / "one.hwpx")
    diverged = write_hwpx(tmp_path / "diverged.hwpx", extra_structure=True)

    verdict, code = form_extract.extract_forms(
        [first, diverged], tmp_path / "template")

    assert code == 0
    assert verdict["skeleton_stable"] is False
    assert verdict["warn"][0]["code"] == "form_instances_diverge"
    assert len(verdict["warn"][0]["at"]) == 2
    record = json.loads(
        (tmp_path / "template" / "form_template.json").read_text(
            encoding="utf-8"))
    assert record["fill_slot_inventory"] is None
    assert record["fill_slot_inventory_reason"]


def test_row_count_divergence_warns_without_authoritative_inventory(
    tmp_path: Path,
) -> None:
    first = write_hwpx(tmp_path / "one.hwpx")
    diverged = write_hwpx(tmp_path / "diverged.hwpx", extra_table_row=True)
    out_dir = tmp_path / "template"

    verdict, code = form_extract.extract_forms([first, diverged], out_dir)

    assert code == 0
    assert verdict["warn"][0]["code"] == "form_instances_diverge"
    assert verdict["slot_counts"] is None
    record = json.loads(
        (out_dir / "form_template.json").read_text(encoding="utf-8"))
    assert record["skeleton_stable"] is False
    assert record["fill_slot_inventory"] is None
    assert "skeleton" in record["fill_slot_inventory_reason"]
