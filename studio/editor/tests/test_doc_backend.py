from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from studio.editor.doc_backend import (
    UnsafeEdit,
    apply_paragraph_edit,
    inspect_paragraphs,
)
from studio.editor.sample_factory import write_synthetic_hwpx


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_lists_plain_and_equation_paragraphs_with_explicit_safety(tmp_path: Path):
    sample = write_synthetic_hwpx(tmp_path / "sample.hwpx")

    paragraphs = inspect_paragraphs(sample)

    editable = next(item for item in paragraphs if item.text == "Editable sample paragraph.")
    equation = next(item for item in paragraphs if item.has_equation)
    assert editable.editable is True
    assert editable.hazards == ()
    assert equation.editable is False
    assert equation.protected_run_count == 1
    assert "equation" in equation.hazards
    assert equation.display_text == "Equation hazard: [equation] is protected."
    assert "</hp:run>" not in equation.display_text


def test_edit_changes_only_the_target_text_payload(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    output = tmp_path / "edited.hwpx"
    target = next(
        item for item in inspect_paragraphs(source)
        if item.text == "Editable sample paragraph."
    )
    before = _members(source)

    result = apply_paragraph_edit(
        source,
        output,
        paragraph_id=target.id,
        new_text="Edited & fidelity-checked <text>.",
        expected_old_text=target.text,
    )

    after = _members(output)
    assert result.fidelity.ok is True
    assert result.fidelity.changed_members == ("Contents/section0.xml",)
    assert result.fidelity.limited_to_text_payload is True
    assert before.keys() == after.keys()
    for name in before:
        if name != "Contents/section0.xml":
            assert after[name] == before[name]
    expected = before["Contents/section0.xml"].replace(
        b"Editable sample paragraph.",
        b"Edited &amp; fidelity-checked &lt;text&gt;.",
        1,
    )
    assert after["Contents/section0.xml"] == expected
    reparsed = {item.id: item for item in inspect_paragraphs(output)}
    assert reparsed[target.id].text == "Edited & fidelity-checked <text>."


def test_equation_paragraph_is_rejected_without_writing(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    output = tmp_path / "edited.hwpx"
    target = next(item for item in inspect_paragraphs(source) if item.has_equation)

    with pytest.raises(UnsafeEdit, match="equation"):
        apply_paragraph_edit(
            source,
            output,
            paragraph_id=target.id,
            new_text="Do not flatten the equation.",
            expected_old_text=target.text,
        )

    assert not output.exists()


def test_stale_expected_text_is_rejected(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    output = tmp_path / "edited.hwpx"
    target = next(item for item in inspect_paragraphs(source) if item.editable)

    with pytest.raises(UnsafeEdit, match="changed since it was read"):
        apply_paragraph_edit(
            source,
            output,
            paragraph_id=target.id,
            new_text="New text",
            expected_old_text="stale text",
        )

    assert not output.exists()


def test_nested_markup_inside_text_payload_is_protected(tmp_path: Path):
    source = write_synthetic_hwpx(tmp_path / "source.hwpx")
    rewritten = tmp_path / "nested.hwpx"
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(rewritten, "w") as after:
        for info in before.infolist():
            payload = before.read(info)
            if info.filename == "Contents/section0.xml":
                payload = payload.replace(
                    b"Editable sample paragraph.",
                    b"Editable <hp:markpenBegin/>sample paragraph.",
                    1,
                )
            after.writestr(info, payload)

    target = next(item for item in inspect_paragraphs(rewritten) if "Editable" in item.text)

    assert target.editable is False
    assert "nested-text-markup" in target.hazards
    assert "<hp:markpenBegin" not in target.display_text
