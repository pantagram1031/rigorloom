# -*- coding: utf-8 -*-
"""Coverage, single-language purity, and doc-parity tests for UI vocabulary."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
VOCAB_TS = REPO / "desktop" / "src" / "i18n" / "vocabulary.ts"
VOCAB_MD = REPO / "docs" / "ui" / "vocabulary.md"
TSC_DIR = REPO / "desktop" / "node_modules" / "typescript"

if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_codes  # noqa: E402
import rt_plan  # noqa: E402

FORBIDDEN_SUBSTRINGS = (
    "정확도 100%",
    "Claude 기반",
    "AI 탐지 회피",
    "AI 티 제거",
    "Astra",
    "Herdr",
    "F:/",
    "리걸룸",
    "홍길동",
)

ADDENDUM_KEYS = (
    "guard_pill_kept",
    "guard_pill_changed",
    "guard_list_header",
    "guard_added_numbers",
    "guard_not_run_invalid",
    "approve_dialog_effect",
    "approve_dialog_guard_skipped",
    "page_label_review",
    "page_label_fill",
    "page_omitted_object",
    "fill_long_value",
    "fill_counter",
    "open_pending_badge",
    "open_sample_form_label",
    "history_title_note",
    "history_pending_link",
    "history_undo_scope",
    "history_approval_method_direct",
    "settings_folder_locked",
    "settings_language_note",
    "settings_theme_note",
    "settings_folder_note",
    "print_view_grade_hancom",
    "print_view_grade_pdf",
    "print_view_grade_own",
)


def _load_vocab_bundle(tmp_path: Path) -> dict:
    if not TSC_DIR.is_dir():
        pytest.skip("desktop TypeScript is not installed")
    node = shutil.which("node") or "node"
    script = tmp_path / "inspect_vocab.cjs"
    script.write_text(
        f"""
"use strict";
const fs = require("node:fs");
const ts = require({json.dumps(str(TSC_DIR))});
const src = fs.readFileSync({json.dumps(str(VOCAB_TS))}, "utf8");
const js = ts.transpileModule(src, {{
  compilerOptions: {{ target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }}
}}).outputText;
const mod = {{ exports: {{}} }};
new Function("exports", "module", "require", js)(mod.exports, mod, require);
const v = mod.exports;
const samples = {{
  approve_ko: v.t("approve_dialog_effect", "ko", [4]),
  approve_en: v.t("approve_dialog_effect", "en", [4]),
  fill_ko: v.t("fill_counter", "ko", [2, 9]),
  fill_en: v.t("fill_counter", "en", [2, 9]),
  blank_ko: v.t("field_blank_fallback", "ko", [3]),
  blank_en: v.t("field_blank_fallback", "en", [3]),
  append_ko: v.opKindLabel("replace_at_cell", "ko", "append"),
  append_en: v.opKindLabel("replace_at_cell", "en", "append"),
  replace_ko: v.opKindLabel("replace_at_cell", "ko", "replace"),
  unknown_op_ko: v.opKindLabel("nonexistent_op_kind", "ko"),
  unknown_err_ko: v.errorCodeMessage("nonexistent_error_code", "ko"),
  unknown_err_en: v.errorCodeMessage("nonexistent_error_code", "en"),
  cancelled_ko: v.errorCodeMessage("cancelled", "ko"),
  proto_ko: v.errorCodeMessage("protocol_version_unsupported", "ko"),
}};
process.stdout.write(JSON.stringify({{
  maps: {{
    OP_KIND_VOCAB: v.OP_KIND_VOCAB,
    OP_KIND_MODE_VOCAB: v.OP_KIND_MODE_VOCAB,
    PLAN_STATE_VOCAB: v.PLAN_STATE_VOCAB,
    RULE_STATE_VOCAB: v.RULE_STATE_VOCAB,
    CHECK_STATE_VOCAB: v.CHECK_STATE_VOCAB,
    APPROVAL_STATE_VOCAB: v.APPROVAL_STATE_VOCAB,
    RENDER_GRADE_VOCAB: v.RENDER_GRADE_VOCAB,
    CELL_CLASS_VOCAB: v.CELL_CLASS_VOCAB,
    GUARD_CATEGORY_VOCAB: v.GUARD_CATEGORY_VOCAB,
    ERROR_CODE_VOCAB: v.ERROR_CODE_VOCAB,
    VOCABULARY: v.VOCABULARY,
  }},
  samples,
}}));
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node, str(script)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def _parse_markdown_rows(md_text: str) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$")
    for raw_line in md_text.splitlines():
        m = row_re.match(raw_line.strip())
        if not m:
            continue
        key = m.group(1)
        ko = m.group(2).replace("\\|", "|")
        en = m.group(3).replace("\\|", "|")
        rows[key] = (ko, en)
    return rows


def test_vocabulary_covers_all_runtime_op_kinds_codes_and_states(tmp_path: Path):
    bundle = _load_vocab_bundle(tmp_path)
    maps = bundle["maps"]

    all_op_kinds = (
        set(rt_plan.PREEDIT_OP_KINDS)
        | set(rt_plan.PREEDIT_NOT_IMPLEMENTED)
        | set(rt_plan.XML_OP_KINDS)
        | set(rt_plan.COM_OP_KINDS)
    )
    assert len(all_op_kinds) == 27
    for kind in sorted(all_op_kinds):
        entry = maps["OP_KIND_VOCAB"].get(kind)
        assert entry is not None, f"Missing op kind in OP_KIND_VOCAB: {kind}"
        assert entry["ko"].strip() and entry["en"].strip()

    for code in sorted(rt_codes.ERROR_CODES):
        entry = maps["ERROR_CODE_VOCAB"].get(code)
        assert entry is not None, f"Missing error code in ERROR_CODE_VOCAB: {code}"
        assert entry["ko"].strip() and entry["en"].strip()

    for state in sorted(rt_codes.RULE_STATES):
        entry = maps["RULE_STATE_VOCAB"].get(state)
        assert entry is not None, f"Missing rule state: {state}"
        assert entry["ko"].strip() and entry["en"].strip()

    for state in sorted(rt_codes.CHECK_STATES):
        entry = maps["CHECK_STATE_VOCAB"].get(state)
        assert entry is not None, f"Missing check state: {state}"
        assert entry["ko"].strip() and entry["en"].strip()

    for state in sorted(rt_codes.APPROVAL_STATES):
        entry = maps["APPROVAL_STATE_VOCAB"].get(state)
        assert entry is not None, f"Missing approval state: {state}"
        assert entry["ko"].strip() and entry["en"].strip()

    for state in ("proposed", "validated", "invalid", "approved", "rejected", "applied"):
        entry = maps["PLAN_STATE_VOCAB"].get(state)
        assert entry is not None, f"Missing plan state: {state}"
        assert entry["ko"].strip() and entry["en"].strip()

    for grade in ("hancom", "pdf", "own-uncertified"):
        entry = maps["RENDER_GRADE_VOCAB"].get(grade)
        assert entry is not None, f"Missing render grade: {grade}"
        assert entry["ko"].strip() and entry["en"].strip()

    for key in ADDENDUM_KEYS:
        entry = maps["VOCABULARY"].get(key)
        assert entry is not None, f"Missing addendum key in VOCABULARY: {key}"
        assert entry["ko"].strip() and entry["en"].strip()

    check_vocab = maps["CHECK_STATE_VOCAB"]
    assert len({check_vocab[s]["ko"] for s in ("skipped", "not_run", "unavailable")}) == 3
    assert len({check_vocab[s]["en"] for s in ("skipped", "not_run", "unavailable")}) == 3


def test_korean_values_contain_no_latin_letters(tmp_path: Path):
    bundle = _load_vocab_bundle(tmp_path)
    for map_name, mapping in bundle["maps"].items():
        for key, entry in mapping.items():
            ko = entry["ko"]
            assert re.search(r"[A-Za-z]", ko) is None, (
                f"Latin character leaked into ko string {map_name}.{key}: {ko!r}"
            )
            assert entry["en"].strip(), f"Empty en string at {map_name}.{key}"


def test_runtime_helpers_format_and_sanitize_fallbacks(tmp_path: Path):
    samples = _load_vocab_bundle(tmp_path)["samples"]
    assert "4" in samples["approve_ko"] and "4" in samples["approve_en"]
    assert "9" in samples["fill_ko"] and "2" in samples["fill_ko"]
    assert samples["fill_en"] == "2 of 9 blanks filled"
    assert samples["blank_ko"] == "빈칸 3"
    assert samples["blank_en"] == "Blank 3"
    assert samples["append_ko"] != samples["replace_ko"]
    assert samples["append_en"] == "Append to cell"
    assert "nonexistent" not in samples["unknown_op_ko"]
    assert "nonexistent" not in samples["unknown_err_ko"]
    assert "nonexistent" not in samples["unknown_err_en"]
    assert samples["cancelled_ko"] != samples["proto_ko"]


def test_markdown_table_parity_and_no_forbidden_substrings(tmp_path: Path):
    assert VOCAB_MD.is_file(), f"Missing {VOCAB_MD}"
    md_text = VOCAB_MD.read_text(encoding="utf-8")
    ts_text = VOCAB_TS.read_text(encoding="utf-8")

    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in md_text, f"Forbidden substring {bad!r} in vocabulary.md"
        assert bad not in ts_text, f"Forbidden substring {bad!r} in vocabulary.ts"

    md_rows = _parse_markdown_rows(md_text)
    maps = _load_vocab_bundle(tmp_path)["maps"]
    expected: dict[str, tuple[str, str]] = {}
    for mapping in maps.values():
        for key, entry in mapping.items():
            expected[key] = (entry["ko"], entry["en"])

    assert set(md_rows.keys()) == set(expected.keys())
    for key, pair in expected.items():
        assert md_rows[key] == pair, f"Parity mismatch for {key}: md={md_rows[key]} ts={pair}"
