"""Guard against hardcoded Hangul literals in kept desktop TypeScript sources
and verify the legacy UI deletion candidates have zero live imports.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SRC = REPO_ROOT / "desktop" / "src"

HANGUL_RE = re.compile(r"[\uAC00-\uD7A3]")
IMPORT_SPEC_RE = re.compile(
    r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)"""
)

# Legacy UI modules marked for removal in WP10c: kept files must never import
# them, and once deleted via `git rm` this test continues checking the rest of src/.
PENDING_OLD_UI_DELETIONS: frozenset[str] = frozenset(
    {
        "views/DocumentView.tsx",
        "views/AgentView.tsx",
        "components/ReviewQueue.tsx",
        "components/VerificationBar.tsx",
        "components/EditorToolbar.tsx",
        "components/TaskPacks.tsx",
        "components/StructureTree.tsx",
        "components/DocumentContext.tsx",
        "components/ContextPanel.tsx",
        "components/Welcome.tsx",
        "components/History.tsx",
        "components/Settings.tsx",
        "components/GuardDiffPanel.tsx",
        "components/ReceiptPanel.tsx",
        "components/PagePreview.tsx",
        "components/PageOverlay.tsx",
        "components/Timeline.tsx",
        "components/Conversation.tsx",
        "components/SessionList.tsx",
        "components/Composer.tsx",
        "components/Findings.tsx",
        "components/TextView.tsx",
        "components/Tag.tsx",
    }
)

REGEX_PREFIX_TOKENS = frozenset(
    {
        "",
        "=",
        "(",
        ",",
        ":",
        "[",
        "!",
        "&",
        "|",
        "?",
        ";",
        "{",
        "}",
        "~",
        "^",
        "+",
        "-",
        "*",
        "/",
        "%",
        "<",
        ">",
        "=>",
        "return",
        "case",
        "throw",
        "typeof",
        "void",
        "delete",
        "in",
        "of",
        "instanceof",
        "new",
        "else",
        "await",
        "yield",
    }
)


def _strip_js_comments(source: str) -> str:
    """Strip // and /* */ comments while preserving strings, templates, and regex literals."""
    out: list[str] = []
    i = 0
    n = len(source)
    prev_token = ""

    def read_escaped_until(quote: str, start: int) -> int:
        j = start + 1
        out.append(source[start])
        while j < n:
            ch = source[j]
            out.append(ch)
            if ch == "\\" and j + 1 < n:
                out.append(source[j + 1])
                j += 2
                continue
            if ch == quote:
                return j + 1
            j += 1
        return j

    def read_regex(start: int) -> int:
        j = start + 1
        in_class = False
        out.append("/")
        while j < n:
            ch = source[j]
            out.append(ch)
            if ch == "\\" and j + 1 < n:
                out.append(source[j + 1])
                j += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]" and in_class:
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                while j < n and source[j].isalpha():
                    out.append(source[j])
                    j += 1
                return j
            elif ch == "\n":
                return j + 1
            j += 1
        return j

    def read_template(start: int) -> int:
        j = start + 1
        out.append("`")
        while j < n:
            ch = source[j]
            if ch == "\\":
                out.append(ch)
                if j + 1 < n:
                    out.append(source[j + 1])
                    j += 2
                    continue
                j += 1
                continue
            if ch == "`":
                out.append(ch)
                return j + 1
            if ch == "$" and j + 1 < n and source[j + 1] == "{":
                out.append("${")
                j += 2
                depth = 1
                inner_prev = ""
                while j < n and depth > 0:
                    c = source[j]
                    nx = source[j + 1] if j + 1 < n else ""
                    if c == "/" and nx == "/":
                        while j < n and source[j] != "\n":
                            j += 1
                        continue
                    if c == "/" and nx == "*":
                        j += 2
                        while j + 1 < n and not (source[j] == "*" and source[j + 1] == "/"):
                            if source[j] == "\n":
                                out.append("\n")
                            j += 1
                        j = min(n, j + 2)
                        continue
                    if c in ('"', "'"):
                        j = read_escaped_until(c, j)
                        inner_prev = "literal"
                        continue
                    if c == "`":
                        j = read_template(j)
                        inner_prev = "literal"
                        continue
                    if c == "/" and inner_prev in REGEX_PREFIX_TOKENS:
                        j = read_regex(j)
                        inner_prev = "literal"
                        continue
                    out.append(c)
                    if c == "{":
                        depth += 1
                        inner_prev = "{"
                    elif c == "}":
                        depth -= 1
                        inner_prev = "}"
                    elif c.isalnum() or c in ("_", "$"):
                        tok_start = j
                        j += 1
                        while j < n and (source[j].isalnum() or source[j] in ("_", "$")):
                            out.append(source[j])
                            j += 1
                        inner_prev = source[tok_start:j]
                        continue
                    elif not c.isspace():
                        inner_prev = c
                    j += 1
                continue
            out.append(ch)
            j += 1
        return j

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            i = min(n, i + 2)
            continue
        if ch in ('"', "'"):
            i = read_escaped_until(ch, i)
            prev_token = "literal"
            continue
        if ch == "`":
            i = read_template(i)
            prev_token = "literal"
            continue
        if ch == "/" and prev_token in REGEX_PREFIX_TOKENS:
            i = read_regex(i)
            prev_token = "literal"
            continue

        out.append(ch)
        if ch.isalnum() or ch in ("_", "$"):
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] in ("_", "$")):
                out.append(source[i])
                i += 1
            prev_token = source[start:i]
            continue
        if ch == "=" and nxt == ">":
            out.append(">")
            prev_token = "=>"
            i += 2
            continue
        if not ch.isspace():
            prev_token = ch
        i += 1

    return "".join(out)


def _is_allowlisted(rel_posix: str) -> bool:
    if rel_posix in PENDING_OLD_UI_DELETIONS:
        return True
    if rel_posix in {"devMock.ts", "smoke.ts"}:
        return True
    if rel_posix.startswith("i18n/"):
        return True
    if "/__tests__/" in f"/{rel_posix}/":
        return True
    return False


def _resolve_relative_import(importer: Path, spec: str) -> str | None:
    if not spec.startswith("."):
        return None
    base = (importer.parent / spec).resolve()
    candidates = [
        base,
        Path(f"{base}.ts"),
        Path(f"{base}.tsx"),
        base / "index.ts",
        base / "index.tsx",
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.relative_to(DESKTOP_SRC.resolve()).as_posix()
            except ValueError:
                return None
        try:
            rel = candidate.relative_to(DESKTOP_SRC.resolve()).as_posix()
        except ValueError:
            continue
        if rel in PENDING_OLD_UI_DELETIONS:
            return rel
    return None


def test_pending_old_ui_deletions_have_zero_live_imports() -> None:
    """No kept file in desktop/src may import any of the 23 legacy UI modules."""
    violations: list[str] = []
    for path in sorted(DESKTOP_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        if rel in PENDING_OLD_UI_DELETIONS:
            continue
        text = _strip_js_comments(path.read_text(encoding="utf-8"))
        for match in IMPORT_SPEC_RE.finditer(text):
            spec = match.group(1) or match.group(2)
            if not spec:
                continue
            target = _resolve_relative_import(path, spec)
            if target in PENDING_OLD_UI_DELETIONS:
                violations.append(f"{rel} imports legacy module {target} via {spec!r}")
    assert not violations, "\n".join(violations)


def test_no_hangul_literals_outside_i18n_and_allowlist() -> None:
    """Every kept desktop/src TypeScript module must route Hangul copy via i18n."""
    violations: list[str] = []
    for path in sorted(DESKTOP_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        if _is_allowlisted(rel):
            continue
        stripped = _strip_js_comments(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(stripped.splitlines(), start=1):
            if HANGUL_RE.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Hardcoded Hangul found outside i18n:\n" + "\n".join(violations)
