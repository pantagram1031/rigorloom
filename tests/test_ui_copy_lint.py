# -*- coding: utf-8 -*-
"""Copy-lint suite over desktop/src/i18n/vocabulary.ts, desktop/src/i18n/v2/*,
desktop/src, docs/ui/v2, and packaging metadata.

Enforces:
- CONTEXT translationese bans (`진행합니다/진행됩니다`, `하는 것이 가능`, `해당 `/`해당문서`,
  `에 대한`, `되어집/되어진`, `통해`)
- J1 §3.6: no Korean particle (조사) adjacent to any placeholder (`{0}을`, `{0}이(가)`,
  `‘{0}’을`, `{0})를`, `{0} 을`, etc.)
- J1 §3.11 / §3.3: no `결재` anywhere in UI copy; no `영수증` in v2 copy (`검증 기록`)
- J1 §3.13: Korean strings contain no Latin letters outside the allowlist
  (`Rigorloom`, file extensions, key names, `PDF`, `HWPX`, `A4`)
- No emoji and no exclamation marks (`!`, `！`)
- The Latin and `!` checks read the NFKC form, so full-width letters (`ＡＰＩ`) count
- `ko` and `en` non-empty parity with matching placeholder sets
- Advisor ruling G: forbidden-phrase grep across `desktop/src`, `docs/ui/v2`,
  and packaging metadata
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Mapping
import unicodedata

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SRC = REPO_ROOT / "desktop" / "src"
VOCAB_V1_TS = DESKTOP_SRC / "i18n" / "vocabulary.ts"
I18N_V2_DIR = DESKTOP_SRC / "i18n" / "v2"
TSC_DIR = REPO_ROOT / "desktop" / "node_modules" / "typescript"

FORBIDDEN_PHRASES = (
    "정확도 100%",
    "Claude 기반",
    "AI 탐지 회피",
    "AI 티 제거",
    "리걸룸",
    "홍길동",
)

TRANSLATIONESE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("translationese_jinhaeng", re.compile(r"진행(?:합니다|하겠|해\s*주세요|할\s*수|됩니다|됨|되었|돼|중입니다)")),
    ("translationese_ganeung", re.compile(r"는\s*것이\s*가능")),
    # `해당 칸`, `해당문서`; the verb (`해당하는`, `해당합니다`) is plain Korean.
    ("translationese_haedang", re.compile(r"해당(?:\s|(?![하합한할했되됩된될])[가-힣])")),
    ("translationese_daehan", re.compile(r"에\s*대(?:한|해)")),
    ("translationese_double_passive", re.compile(r"되어(?:집|진|지)")),
    ("translationese_tonghae", re.compile(r"통해")),
)

UNRESOLVED_JOSA_RE = re.compile(
    r"(?:이\(가\)|은\(는\)|을\(를\)|과\(와\)|\(으\)로|\(이\)라|\(이\)나)"
)

# A particle after a placeholder counts even past a closing quote or bracket
# (`‘{0}’을`, `{0})를`) or a space (`{0} 을`).
PLACEHOLDER_PARTICLE_RE = re.compile(
    r"\{(?:\d+|[A-Za-z_]\w*)\}"
    r"[’”」』)\]'\"]*[ \t]?"
    r"(?:이\(가\)|은\(는\)|을\(를\)|과\(와\)|\(으\)로|"
    r"으로서|으로써|으로부터|으로|에서|에게|께서|부터|까지|처럼|보다|이랑|이나|이란|이라|"
    r"(?:은|는|이|가|을|를|과|와|로|의|도|만|께|랑|나)(?=$|[\s,.·…:;)\]」』”’]))"
)

EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF"
    r"\u2600-\u27BF\uFE0F]"
)

BANNED_GYEOLJAE_RE = re.compile(r"결재")
BANNED_V2_RECEIPT_RE = re.compile(r"영수증")
PLACEHOLDER_INDEX_RE = re.compile(r"\{(\d+|[A-Za-z_]\w*)\}")

# J1 §3.13 Latin allowlist for Korean locale:
# Rigorloom, file extensions, key names (and key chords), PDF, HWPX, A4.
# Uses ASCII word boundaries so Hangul suffixes like `.hwpx로` or `PDF로` work
# while disallowed Latin words (e.g. `API`, `mock`, `myhwpx`) are rejected.
ALLOWED_KO_LATIN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"Rigorloom"
    r"|(?:Ctrl|Alt|Shift|Meta)(?:\+(?:Ctrl|Alt|Shift|Meta))*\+"
    r"(?:Enter|Esc|Tab|Space|Del|PgUp|PgDn|Home|End|F1[0-2]|F[1-9]|[A-Z0-9,./=+-])"
    r"|\.(?:hwpx|hwp|docx|md|pdf)"
    r"|(?:HWPX|HWP|DOCX|MD|PDF|A4|Ctrl|Alt|Shift|Esc|Enter|Tab|Space|PgUp|PgDn|F1[0-2]|F[1-9])"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

LATIN_LETTER_RE = re.compile(r"[A-Za-z]+")

# Frozen baseline of pre-existing v1 `vocabulary.ts` violations owned by WP7 for
# cleanup when v2 copy folds in. Zero exemptions apply to `desktop/src/i18n/v2/*`
# and any new violation in `vocabulary.ts` fails immediately.
LEGACY_V1_VOCAB_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("cell_address_unknown", "translationese_haedang"),
        ("review_date_change_preview", "placeholder_particle"),
        ("apply_done_toast", "placeholder_particle"),
        ("err_agent_host_exit", "placeholder_particle"),
        ("operator_turn_fault_note", "translationese_daehan"),
        ("operator_event_approved", "placeholder_particle"),
        ("operator_event_approved", "unresolved_josa"),
        ("operator_event_rejected", "placeholder_particle"),
        ("operator_event_rejected", "unresolved_josa"),
    }
)


@dataclass(frozen=True)
class CopyViolation:
    source: str
    key: str
    rule: str
    detail: str

    def format(self) -> str:
        return f"[{self.rule}] {self.source}:{self.key} — {self.detail}"


def _disallowed_latin_tokens(ko_text: str) -> list[str]:
    without_placeholders = PLACEHOLDER_INDEX_RE.sub("", ko_text)
    cleaned = ALLOWED_KO_LATIN_RE.sub("", without_placeholders)
    return LATIN_LETTER_RE.findall(cleaned)


def lint_copy_entry(
    source: str,
    key: str,
    ko: str,
    en: str,
    *,
    is_v2: bool = True,
) -> list[CopyViolation]:
    """Run all copy-lint rules against one `{ko, en}` entry."""
    violations: list[CopyViolation] = []

    if not isinstance(ko, str) or not ko.strip():
        violations.append(CopyViolation(source, key, "empty_ko", "Korean string is empty"))
        ko = ""
    if not isinstance(en, str) or not en.strip():
        violations.append(CopyViolation(source, key, "empty_en", "English string is empty"))
        en = ""

    ko_placeholders = set(PLACEHOLDER_INDEX_RE.findall(ko))
    en_placeholders = set(PLACEHOLDER_INDEX_RE.findall(en))
    if ko and en and ko_placeholders != en_placeholders:
        violations.append(
            CopyViolation(
                source,
                key,
                "placeholder_mismatch",
                f"ko placeholders {sorted(ko_placeholders)} != en placeholders {sorted(en_placeholders)}",
            )
        )

    for rule_name, rx in TRANSLATIONESE_PATTERNS:
        m = rx.search(ko)
        if m:
            violations.append(
                CopyViolation(source, key, rule_name, f"banned pattern {m.group(0)!r} in {ko!r}")
            )

    m_unres = UNRESOLVED_JOSA_RE.search(ko)
    if m_unres:
        violations.append(
            CopyViolation(
                source,
                key,
                "unresolved_josa",
                f"unresolved particle {m_unres.group(0)!r} in {ko!r}",
            )
        )

    m_part = PLACEHOLDER_PARTICLE_RE.search(ko)
    if m_part:
        violations.append(
            CopyViolation(
                source,
                key,
                "placeholder_particle",
                f"particle attached to placeholder {m_part.group(0)!r} in {ko!r}",
            )
        )

    if BANNED_GYEOLJAE_RE.search(ko):
        violations.append(
            CopyViolation(source, key, "banned_gyeoljae", f"'결재' is banned in UI copy: {ko!r}")
        )

    if is_v2 and BANNED_V2_RECEIPT_RE.search(ko):
        violations.append(
            CopyViolation(
                source,
                key,
                "banned_v2_receipt_term",
                f"use '검증 기록' instead of '영수증' in v2 copy: {ko!r}",
            )
        )

    for lang, raw_text in (("ko", ko), ("en", en)):
        # Full-width forms (`！`, `ＡＰＩ`) read as what they look like.
        text = unicodedata.normalize("NFKC", raw_text)
        if EMOJI_RE.search(raw_text):
            violations.append(
                CopyViolation(source, key, "no_emoji", f"emoji found in {lang}: {text!r}")
            )
        if "!" in text:
            violations.append(
                CopyViolation(
                    source,
                    key,
                    "no_exclamation",
                    f"exclamation mark '!' found in {lang}: {text!r}",
                )
            )
        for bad in FORBIDDEN_PHRASES:
            if bad in text:
                violations.append(
                    CopyViolation(
                        source,
                        key,
                        "forbidden_phrase",
                        f"forbidden phrase {bad!r} in {lang}: {text!r}",
                    )
                )

    bad_latin = _disallowed_latin_tokens(unicodedata.normalize("NFKC", ko))
    if bad_latin:
        violations.append(
            CopyViolation(
                source,
                key,
                "latin_outside_allowlist",
                f"disallowed Latin {bad_latin!r} in ko: {ko!r}",
            )
        )

    return violations


def lint_copy_map(
    source: str,
    entries: Mapping[str, Mapping[str, str]],
    *,
    is_v2: bool = True,
    legacy_baseline: frozenset[tuple[str, str]] = frozenset(),
) -> list[CopyViolation]:
    out: list[CopyViolation] = []
    for key, pair in entries.items():
        if not isinstance(pair, Mapping):
            continue
        found = lint_copy_entry(
            source,
            str(key),
            pair.get("ko", ""),
            pair.get("en", ""),
            is_v2=is_v2,
        )
        for v in found:
            if (v.key, v.rule) not in legacy_baseline:
                out.append(v)
    return out


def _extract_exported_vocab_maps(ts_path: Path, tmp_path: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Transpile a TS i18n module and extract all exported `{key: {ko, en}}` maps."""
    if not TSC_DIR.is_dir():
        pytest.skip("desktop TypeScript is not installed")
    node = shutil.which("node") or "node"
    script = tmp_path / f"extract_{ts_path.stem}.cjs"
    script.write_text(
        f"""
"use strict";
const fs = require("node:fs");
const ts = require({json.dumps(str(TSC_DIR))});
const src = fs.readFileSync({json.dumps(str(ts_path))}, "utf8");
const js = ts.transpileModule(src, {{
  compilerOptions: {{ target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }}
}}).outputText;
const mod = {{ exports: {{}} }};
const safeRequire = (spec) => {{
  // WP2's i18n/v2 loader: `defineStrings(wp, table)` hands back the table as-is.
  if (/(^|\/)index(\.ts)?$/.test(spec)) return {{ defineStrings: (_wp, table) => table }};
  if (spec.endsWith(".ts") || spec.startsWith(".")) return {{}};
  return require(spec);
}};
new Function("exports", "module", "require", js)(mod.exports, mod, safeRequire);
const out = {{}};
for (const [expName, expVal] of Object.entries(mod.exports)) {{
  if (!expVal || typeof expVal !== "object" || Array.isArray(expVal)) continue;
  const entries = Object.entries(expVal);
  if (entries.length === 0) continue;
  const looksLikeVocab = entries.every(
    ([, v]) => v && typeof v === "object" && typeof v.ko === "string" && typeof v.en === "string"
  );
  if (looksLikeVocab) {{
    out[expName] = expVal;
  }}
}}
process.stdout.write(JSON.stringify(out));
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node, str(script)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_v2_i18n_modules_pass_strict_copy_lint(tmp_path: Path) -> None:
    """Every file under desktop/src/i18n/v2/ must pass copy lint with zero exemptions."""
    assert I18N_V2_DIR.is_dir(), f"Missing {I18N_V2_DIR}"
    # Modules under i18n/v2 that are not UI string tables: WP2's loader and
    # WP3's form-matching tokens (words read from documents, never shown as copy).
    not_tables = {"index.ts", "wp3FormTokens.ts"}
    v2_files = sorted(p for p in I18N_V2_DIR.rglob("*.ts") if p.is_file() and p.name not in not_tables)
    assert v2_files, "Expected at least one v2 i18n module (e.g. desktop/src/i18n/v2/wps.ts)"

    violations: list[CopyViolation] = []
    for ts_file in v2_files:
        rel = ts_file.relative_to(REPO_ROOT).as_posix()
        maps = _extract_exported_vocab_maps(ts_file, tmp_path)
        assert maps, f"No exported {{ko, en}} vocabulary map found in {rel}"
        for map_name, mapping in maps.items():
            violations.extend(lint_copy_map(f"{rel}#{map_name}", mapping, is_v2=True))

    assert not violations, "v2 copy lint violations:\n" + "\n".join(v.format() for v in violations)


def test_v1_vocabulary_has_zero_new_copy_lint_violations(tmp_path: Path) -> None:
    """Legacy vocabulary.ts may not introduce any copy-lint violations beyond the frozen WP7 baseline."""
    maps = _extract_exported_vocab_maps(VOCAB_V1_TS, tmp_path)
    assert maps
    violations: list[CopyViolation] = []
    for map_name, mapping in maps.items():
        violations.extend(
            lint_copy_map(
                f"vocabulary.ts#{map_name}",
                mapping,
                is_v2=False,
                legacy_baseline=LEGACY_V1_VOCAB_BASELINE,
            )
        )
    assert not violations, "New vocabulary.ts copy lint violations:\n" + "\n".join(
        v.format() for v in violations
    )


def test_forbidden_phrases_absent_in_desktop_docs_v2_and_packaging_metadata() -> None:
    """Advisor ruling G: forbidden-phrase grep across desktop/src, docs/ui/v2, and packaging metadata."""
    scan_targets: list[Path] = []
    for path in sorted(DESKTOP_SRC.rglob("*")):
        if path.is_file() and path.suffix in {".ts", ".tsx", ".css", ".html", ".json"}:
            scan_targets.append(path)

    docs_v2 = REPO_ROOT / "docs" / "ui" / "v2"
    if docs_v2.is_dir():
        for path in sorted(docs_v2.rglob("*")):
            if path.is_file() and path.suffix in {".md", ".txt", ".json", ".html"}:
                scan_targets.append(path)

    for meta in (
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "desktop" / "package.json",
        REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json",
        REPO_ROOT / "desktop" / "src-tauri" / "Cargo.toml",
    ):
        if meta.is_file():
            scan_targets.append(meta)

    hits: list[str] = []
    for path in scan_targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for bad in FORBIDDEN_PHRASES:
            if bad in text:
                hits.append(f"{rel}: contains forbidden phrase {bad!r}")

    assert not hits, "Forbidden phrases found:\n" + "\n".join(hits)


def test_copy_lint_rules_catch_all_banned_patterns_and_accept_valid_copy() -> None:
    """Self-test proving every lint rule fires on real violations and permits valid C-copy/J1 copy."""
    bad_cases: list[tuple[str, str, str, str]] = [
        ("t1", "변경을 진행합니다.", "Applying changes.", "translationese_jinhaeng"),
        ("t2", "지금 내보내는 것이 가능합니다.", "You can export now.", "translationese_ganeung"),
        ("t3", "해당 칸을 찾을 수 없습니다.", "Cell not found.", "translationese_haedang"),
        ("t4", "문서에 대한 검토를 마쳤습니다.", "Review finished.", "translationese_daehan"),
        ("t5", "변경이 적용되어집니다.", "Changes apply.", "translationese_double_passive"),
        ("p1", "수정본 {0}을 만들었습니다.", "Created revision {0}.", "placeholder_particle"),
        ("p2", "{0}이(가) 승인했습니다.", "Approved by {0}.", "placeholder_particle"),
        ("p3", "종료 코드 {0}로 끝났습니다.", "Exited with code {0}.", "placeholder_particle"),
        ("p4", "{0}에서 {1}로 이동", "Move from {0} to {1}", "placeholder_particle"),
        ("p5", "{name}의 변경", "Changes of {name}", "placeholder_particle"),
        ("g1", "결재 완료", "Approval complete", "banned_gyeoljae"),
        ("r1", "영수증 확인됨", "Receipt verified", "banned_v2_receipt_term"),
        ("e1", "저장됨 ✅", "Saved ✅", "no_emoji"),
        ("x1", "승인했습니다!", "Approved!", "no_exclamation"),
        ("l1", "API 키가 필요합니다.", "API key required.", "latin_outside_allowlist"),
        ("l2", "mock 제안입니다.", "Mock proposal.", "latin_outside_allowlist"),
        ("m1", "변경 {0}건", "Changes {0} of {1}", "placeholder_mismatch"),
        ("f1", "정확도 100% 보장", "Guaranteed", "forbidden_phrase"),
        # Holes found by the integrated review (finding 9).
        ("p6", "‘{0}’을 열지 못했습니다.", "Could not open “{0}”.", "placeholder_particle"),
        ("p7", "{0})를 지웠습니다.", "Removed {0}).", "placeholder_particle"),
        ("p8", "{0} 을 지웠습니다.", "Removed {0}.", "placeholder_particle"),
        ("l3", "ＡＰＩ 키가 없습니다", "No API key", "latin_outside_allowlist"),
        ("t6", "에이전트를 통해 보냅니다.", "Sent via the agent.", "translationese_tonghae"),
        ("t7", "변경이 진행됩니다.", "Changes apply.", "translationese_jinhaeng"),
        ("t8", "해당문서가 없습니다", "No such document", "translationese_haedang"),
        ("x2", "완료했습니다！", "Done.", "no_exclamation"),
    ]
    for key, ko, en, expected_rule in bad_cases:
        found = lint_copy_entry("self-test", key, ko, en, is_v2=True)
        rules = {v.rule for v in found}
        assert expected_rule in rules, (
            f"Expected rule {expected_rule!r} for {key} ({ko!r}), got {rules}"
        )

    good_cases: list[tuple[str, str, str]] = [
        ("ok1", "{0} — Rigorloom", "{0} — Rigorloom"),
        ("ok2", "변경 {0}건 승인", "Approve {0} changes"),
        ("ok3", "수정본 {0} 생성 · 내보내기 Ctrl+E", "Revision {0} created · Export Ctrl+E"),
        ("ok4", "{0}월 {1}일 {2} {3}:{4}", "{0} {1}, {3}:{4} {2}"),
        ("ok5", "빈칸 {1}개 중 {0}개 입력", "{0} of {1} blanks filled"),
        ("ok6", "한글에서 .hwpx로 다시 저장한 뒤 열어 주세요.", "Save as .hwpx in Hancom Office, then reopen."),
        ("ok7", "PDF 내보내기 · A4 기준", "Export PDF · A4"),
        ("ok8", "검증 기록 일치", "Verification record matches"),
        ("ok9", "명령창 Ctrl+Shift+P", "Command palette Ctrl+Shift+P"),
        ("ok11", "‘{0}’ 문서를 열었습니다.", "Opened “{0}”."),
        ("ok12", "{0} 이후 변경 {1}건", "{1} changes after {0}"),
        ("ok13", "해당하는 변경이 없습니다.", "No matching changes."),
        ("ok10", "에이전트는 제안하고, 사람이 승인합니다. 승인한 변경만 새 수정본이 되고 원본은 바뀌지 않습니다.",
         "Agents propose and a person approves. Only approved changes become a new revision; the original never changes."),
    ]
    for key, ko, en in good_cases:
        found = lint_copy_entry("self-test", key, ko, en, is_v2=True)
        assert not found, f"Unexpected violations for valid copy {key} ({ko!r}): {found}"
