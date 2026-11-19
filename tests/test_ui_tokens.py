# -*- coding: utf-8 -*-
"""Verification suite for Rigorloom editor v2 design tokens (WP1a / J1 §4–§5).

Covers:
1. Verbatim J1 §4 token sheet presence in desktop/src/tokens.css (and no legacy
   cobalt, teal, or success-green hexes left in tokens.css).
2. All 65 v1 custom property names still resolve with zero cycles or dangling
   var() references in light, dark, and auto (prefers-color-scheme) modes.
3. WCAG 2.1 AA (>= 4.5:1) contrast for every declared text pair on every chrome
   surface and paper/mark surface in both themes (including the 6% dark paper
   veil), plus >= 3.0:1 non-text contrast for --line-control.
4. No hex color literals and no deprecated v1 alias tokens in v2 directories.
5. Static enforcement of J1 §4 token usage rules (--fact, --accent, --raised,
   --shadow-float, [data-docked], primary button --ink fill) in v2 CSS.
6. Live Chromium cascade + contrast verification (with and without frozen v1
   styles.css) proving zero CSS custom property cycles across all theme modes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from _browser_gate import no_browser  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SRC = REPO_ROOT / "desktop" / "src"
TOKENS_CSS = DESKTOP_SRC / "tokens.css"
STYLES_CSS = DESKTOP_SRC / "styles.css"

# Exact J1 §4 token block (binding ruling, lines 229-347).
J1_SECTION_4_VERBATIM = """\
:root {
  /* type: chrome */
  --font-sans: "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Malgun Gothic", system-ui, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, "Cascadia Mono", monospace; /* 자세히, extensions */
  --text-xs: 11px;  --lh-xs: 14px;      /* keycaps and counters only */
  --text-sm: 12px;  --lh-sm: 16px;      /* status bar, tags, secondary */
  --text-base: 13px; --lh-base: 18px;
  --text-lg: 15px;  --lh-lg: 22px;      /* sheet and dialog titles */
  --text-display: 20px; --lh-display: 28px; /* Start only */
  --weight-regular: 400; --weight-semibold: 600;
  --leading-ui: 1.4;

  /* type: page (the document's own faces; Pretendard never on paper) */
  --font-page-serif: "함초롬바탕", "HCR Batang", "한컴바탕", "바탕", Batang, "Nanum Myeongjo", NanumMyeongjo, "Noto Serif CJK KR", serif;
  --font-page-sans: "함초롬돋움", "HCR Dotum", "맑은 고딕", "Malgun Gothic", "Nanum Gothic", NanumGothic, "Noto Sans CJK KR", sans-serif;
  --page-w: 793.7px; --page-h: 1122.5px;      /* A4 at 96 dpi, 100% */
  --page-pt: 1.3333px;                         /* multiply by zoom */
  --page-size-default: 10pt; --page-leading-default: 1.6; /* only when undeclared */

  /* spacing (pixel-named, cannot drift) */
  --s-4: 4px; --s-8: 8px; --s-12: 12px; --s-16: 16px; --s-24: 24px; --s-32: 32px; --s-48: 48px; --s-64: 64px;

  /* sizes */
  --h-titlebar: 36px; --h-strip: 32px; --h-tabrow: 32px; --h-status: 24px;
  --row-tree: 28px; --row: 32px; --row-change: 52px;
  --ctl: 28px; --ctl-lg: 32px; --ctl-touch: 44px;
  --w-left: 240px; --w-right: 360px;

  /* radii and borders */
  --radius-0: 0;        /* paper, approval box */
  --radius-sm: 4px;     /* controls, tags, keycaps */
  --radius-md: 6px;     /* floating layers */
  --divider: 1px;
  --border-hair: 1px solid var(--line);
  --border-strong-line: 1px solid var(--line-strong);

  /* motion */
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --dur-pop: 120ms; --dur-panel: 160ms; --dur-scroll: 180ms;
  --dur-mark-in: 240ms; --dur-mark-dry: 400ms; --dur-splash: 700ms;

  /* focus */
  --focus-width: 2px; --focus-offset: 1px;   /* outline: var(--focus-width) solid var(--focus) */

  /* paper and marks: never themed */
  --paper: #FFFFFF; --paper-ink: #111111; --seat: #F5F2E8;
  --mark-insert: #2A48A4;       --mark-insert-tint: rgba(42, 72, 164, .10);
  --mark-delete: #2A48A4;       --mark-delete-text: #66696F;
  --mark-accepted: #1B1B1A;                         /* ink underline or strike, no tint */
  --mark-fact: #B4232A;         --mark-fact-tint: rgba(180, 35, 42, .10);
  --mark-test: #B8860B;         --mark-test-tint: rgba(217, 162, 27, .18); /* 45deg hatch */
  --mark-stale: #B8860B;                            /* dashed, no tint */
  --mark-rejected: #CCC9C1;                         /* dotted margin bar */
  --mark-selected-tint: rgba(42, 72, 164, .16);     /* ring 1.5px in the state hue */
  --focus-paper: #2A48A4;
  --win-close-hover: #C42B1C;   /* platform convention; exempt from the crimson test */
}

:root, :root[data-theme="light"] {
  --desk: #DEDCD5;     /* behind the paper */
  --chrome: #ECEBE7;   /* title bar, status bar */
  --panel: #F4F3F0;    /* panes, strip, docked sheet */
  --field: #FBFBF9;    /* inputs, selected segment, before/after lines */
  --raised: #FFFFFF;   /* floating layers only */
  --ink: #1B1B1A; --on-ink: #FFFFFF;
  --text-2: #45443F; --text-3: #605E58; --text-disabled: #A3A099;
  --line: #E0DED8; --line-strong: #CCC9C1; --line-control: #86847D;
  --hover: rgba(27, 27, 26, .05); --selected: rgba(27, 27, 26, .08);
  --accent: #2A48A4; --accent-tint: #E7EBF6; --accent-line: #BFC9E8;  /* 쪽빛: agent proposal, focus */
  --focus: var(--accent);
  --fact: #B4232A; --fact-tint: #FBE9E9;                               /* changed fact only */
  --attn: #7A4F00; --attn-tint: #FAF0DC; --attn-line: #B8860B;         /* 확인, blocked, stale, 시험용 */
  --expected: #45443F; --expected-tint: #E8E7E2;                       /* neutral guard tag */
  --paper-veil: transparent;
  --scrim: rgba(27, 27, 26, .28);
  --shadow-paper: 0 0 0 1px rgba(27, 27, 26, .08), 0 1px 2px rgba(27, 27, 26, .06), 0 8px 24px rgba(27, 27, 26, .08);
  --shadow-float: 0 0 0 1px rgba(27, 27, 26, .06), 0 8px 28px rgba(27, 27, 26, .14);
}

:root[data-theme="dark"] {
  --desk: #0B0C0D; --chrome: #0F1012; --panel: #141518; --field: #1B1C20; --raised: #222327;
  --ink: #ECEBE7; --on-ink: #141518;
  --text-2: #C2C0BA; --text-3: #96948E; --text-disabled: #5F5D58;
  --line: #26272B; --line-strong: #36373D; --line-control: #74757C;
  --hover: rgba(236, 235, 231, .06); --selected: rgba(236, 235, 231, .10);
  --accent: #9FB4F0; --accent-tint: #1A2340; --accent-line: #33457A;
  --fact: #F0787C; --fact-tint: #3A1719;
  --attn: #E8B867; --attn-tint: #2E240F; --attn-line: #B98A1E;
  --expected: #C2C0BA; --expected-tint: #2A2B30;
  --paper-veil: rgba(0, 0, 0, .06);   /* overlay on the sheet; the paper's own background stays #FFFFFF */
  --scrim: rgba(0, 0, 0, .50);
  --shadow-paper: 0 0 0 1px rgba(255, 255, 255, .06);
  --shadow-float: 0 0 0 1px rgba(255, 255, 255, .08), 0 16px 40px rgba(0, 0, 0, .55);
}

/* v1 aliases: deprecated, removed in v3. Do not use in v2 directories. */
:root {
  --bg-app: var(--chrome); --bg-canvas: var(--desk); --bg-surface: var(--panel); --bg-subtle: var(--panel);
  --bg-control: var(--field); --bg-paper: var(--paper); --bg-seat-empty: var(--seat);
  --bg-hover: var(--hover); --bg-selected: var(--selected); --seg-track: var(--panel); --seg-thumb: var(--field);
  --fg-primary: var(--ink); --fg-secondary: var(--text-2); --fg-muted: var(--text-3);
  --fg-on-accent: var(--on-ink); --fg-on-ink: var(--on-ink);
  --border-subtle: var(--line); --border-strong: var(--line-strong); --border-print: var(--paper-ink);
  --accent-hover: var(--accent); --accent-soft: var(--accent-tint); --accent-marker-bg: var(--accent-tint);
  --focus-ring: var(--focus);
  --kept-fg: var(--text-2); --kept-bg: transparent; --kept-rail: var(--line-strong);
  --needs-look-fg: var(--attn); --needs-look-bg: var(--attn-tint); --needs-look-rail: var(--attn-line);
  --changed-fact-fg: var(--fact); --changed-fact-bg: var(--fact-tint); --changed-fact-rail: var(--fact); --changed-fact-border: var(--fact);
  --shadow-pop: var(--shadow-float);
  --space-1: 8px; --space-2: 16px; --space-3: 24px; --space-4: 32px; --space-5: 40px; --space-6: 48px; --space-8: 64px;
  --radius-lg: 8px;   /* site only; the app stops at 6 */
  --topbar-h: var(--h-titlebar); --row-compact-h: var(--row-tree); --row-h: var(--row);
  --leading-doc: 1.7;
  --duration-fast: var(--dur-pop); --duration-scroll: var(--dur-scroll); --duration-panel: var(--dur-panel);
}

@media (prefers-reduced-motion: reduce) {
  :root { --dur-panel: 0ms; --dur-scroll: 0ms; --dur-mark-in: 0ms; --dur-mark-dry: 120ms; --dur-splash: 0ms; }
}"""

# All 65 custom properties defined by v1 desktop/src/tokens.css.
V1_TOKEN_NAMES: tuple[str, ...] = (
    "--accent",
    "--accent-hover",
    "--accent-marker-bg",
    "--accent-soft",
    "--bg-app",
    "--bg-canvas",
    "--bg-control",
    "--bg-hover",
    "--bg-paper",
    "--bg-seat-empty",
    "--bg-selected",
    "--bg-subtle",
    "--bg-surface",
    "--border-print",
    "--border-strong",
    "--border-subtle",
    "--changed-fact-bg",
    "--changed-fact-border",
    "--changed-fact-fg",
    "--changed-fact-rail",
    "--divider",
    "--duration-fast",
    "--duration-panel",
    "--duration-scroll",
    "--ease-standard",
    "--fg-muted",
    "--fg-on-accent",
    "--fg-on-ink",
    "--fg-primary",
    "--fg-secondary",
    "--focus-ring",
    "--font-mono",
    "--font-sans",
    "--ink",
    "--kept-bg",
    "--kept-fg",
    "--kept-rail",
    "--leading-doc",
    "--leading-ui",
    "--needs-look-bg",
    "--needs-look-fg",
    "--needs-look-rail",
    "--radius-lg",
    "--radius-md",
    "--radius-sm",
    "--row-compact-h",
    "--row-h",
    "--seg-thumb",
    "--seg-track",
    "--shadow-paper",
    "--shadow-pop",
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
    "--space-5",
    "--space-6",
    "--space-8",
    "--text-base",
    "--text-display",
    "--text-lg",
    "--text-sm",
    "--topbar-h",
    "--weight-regular",
    "--weight-semibold",
)

# Deprecated v1-only aliases that must NOT be used in v2 directories.
DEPRECATED_V1_ALIASES: frozenset[str] = frozenset(
    {
        "--bg-app",
        "--bg-canvas",
        "--bg-surface",
        "--bg-subtle",
        "--bg-control",
        "--bg-paper",
        "--bg-seat-empty",
        "--bg-hover",
        "--bg-selected",
        "--seg-track",
        "--seg-thumb",
        "--fg-primary",
        "--fg-secondary",
        "--fg-muted",
        "--fg-on-accent",
        "--fg-on-ink",
        "--border-subtle",
        "--border-strong",
        "--border-print",
        "--accent-hover",
        "--accent-soft",
        "--accent-marker-bg",
        "--focus-ring",
        "--kept-fg",
        "--kept-bg",
        "--kept-rail",
        "--needs-look-fg",
        "--needs-look-bg",
        "--needs-look-rail",
        "--changed-fact-fg",
        "--changed-fact-bg",
        "--changed-fact-rail",
        "--changed-fact-border",
        "--shadow-pop",
        "--space-1",
        "--space-2",
        "--space-3",
        "--space-4",
        "--space-5",
        "--space-6",
        "--space-8",
        "--radius-lg",
        "--topbar-h",
        "--row-compact-h",
        "--row-h",
        "--leading-doc",
        "--duration-fast",
        "--duration-scroll",
        "--duration-panel",
    }
)

# Banned legacy colors (old cobalt, D1 draft teal, and success greens).
BANNED_TOKEN_HEXES: tuple[str, ...] = (
    "#1A56DB",
    "#1545B5",
    "#6BA1F8",
    "#8BB6FA",
    "#0A6C74",
    "#5CC4CB",
    "#166534",
    "#16A34A",
    "#4ADE80",
    "#22C55E",
)

# Frozen legacy v1 subdirectories under desktop/src. Every other subdirectory
# (including ui, brand, shell, canvas, panes, panel, history, narrow, model)
# is treated as a v2 directory.
LEGACY_V1_SUBDIRS: frozenset[str] = frozenset(
    {
        "agent",
        "assets",
        "components",
        "fixtures",
        "i18n",
        "views",
        "workspace",
    }
)

EXPLICIT_V2_SUBDIRS: tuple[str, ...] = (
    "ui",
    "brand",
    "shell",
    "canvas",
    "panes",
    "panel",
    "history",
    "narrow",
    "model",
)

VAR_REF_RE = re.compile(r"var\(\s*(--[a-zA-Z0-9_-]+)\s*(?:,\s*([^)]+))?\)")
CUSTOM_PROP_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;]+);")
HEX_COLOR_RE = re.compile(
    r"(?<![&\w-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F\w-])"
)
RGBA_RE = re.compile(
    r"^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*,\s*([0-9.]+))?\s*\)$",
    re.IGNORECASE,
)


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _strip_js_comments_keep_strings(src: str) -> str:
    """Strip // and /* */ comments while preserving string/template contents."""
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if ch in ('"', "'", "`"):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = src[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                if src[i] == "\n":
                    out.append("\n")
                i += 1
            i = min(n, i + 2)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _iter_css_rules(css: str) -> list[tuple[str | None, str, str]]:
    """Return list of (media_query_or_None, selector, declaration_body)."""
    cleaned = _strip_css_comments(css)
    rules: list[tuple[str | None, str, str]] = []

    def parse_region(text: str, media: str | None) -> None:
        i = 0
        n = len(text)
        while i < n:
            while i < n and text[i].isspace():
                i += 1
            if i >= n:
                break
            start = i
            while i < n and text[i] not in "{;":
                i += 1
            if i >= n:
                break
            header = text[start:i].strip()
            if text[i] == ";":
                i += 1
                continue
            # Matching brace for '{'
            depth = 1
            body_start = i + 1
            i += 1
            while i < n and depth > 0:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            body = text[body_start : i - 1].strip()
            if header.startswith(("@media", "@supports", "@layer", "@container", "@scope")):
                parse_region(body, header if header.startswith("@media") else media)
            elif header.startswith("@keyframes") or header.startswith("@-webkit-keyframes"):
                parse_region(body, header)
            elif header.startswith("@"):
                # @font-face, @property, etc.
                continue
            else:
                rules.append((media, header, body))

    parse_region(cleaned, None)
    return rules


def _parse_token_maps(css: str) -> dict[str, dict[str, str]]:
    """Extract light, dark, auto-dark, and reduced-motion token maps from tokens.css."""
    base: dict[str, str] = {}
    html_root_guard: dict[str, str] = {}
    light_only: dict[str, str] = {}
    dark_only: dict[str, str] = {}
    auto_dark_only: dict[str, str] = {}
    reduced_motion: dict[str, str] = {}

    for media, selector, body in _iter_css_rules(css):
        decls = {m.group(1): m.group(2).strip() for m in CUSTOM_PROP_RE.finditer(body)}
        if not decls:
            continue
        norm_sel = " ".join(selector.split())
        if media is None:
            if norm_sel == ":root":
                base.update(decls)
            elif norm_sel == "html:root":
                html_root_guard.update(decls)
            elif norm_sel in (':root, :root[data-theme="light"]', ':root[data-theme="light"]'):
                light_only.update(decls)
            elif norm_sel == ':root[data-theme="dark"]':
                dark_only.update(decls)
        elif "prefers-color-scheme: dark" in media:
            if norm_sel == ':root:not([data-theme="light"])':
                auto_dark_only.update(decls)
        elif "prefers-reduced-motion: reduce" in media:
            if norm_sel == ":root":
                reduced_motion.update(decls)

    light = {**base, **light_only}
    dark = {**base, **light_only, **dark_only}
    auto_dark = {**base, **light_only, **auto_dark_only}
    return {
        "light": light,
        "dark": dark,
        "auto_dark": auto_dark,
        "html_root_guard": html_root_guard,
        "dark_only": dark_only,
        "auto_dark_only": auto_dark_only,
        "reduced_motion": {**light, **reduced_motion},
    }


def _resolve_var(name: str, token_map: dict[str, str], seen: tuple[str, ...] = ()) -> str:
    if name in seen:
        raise AssertionError(f"CSS custom property cycle detected: {' -> '.join((*seen, name))}")
    if name not in token_map:
        raise AssertionError(f"Unresolved CSS custom property: {name}")
    raw = token_map[name]

    def repl(match: re.Match[str]) -> str:
        ref = match.group(1)
        fallback = match.group(2)
        if ref not in token_map and fallback is not None:
            return fallback.strip()
        return _resolve_var(ref, token_map, (*seen, name))

    return VAR_REF_RE.sub(repl, raw).strip()


def _parse_color(value: str) -> tuple[float, float, float, float]:
    v = value.strip()
    if v.lower() == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            r, g, b = (int(c * 2, 16) for c in h)
            return (float(r), float(g), float(b), 1.0)
        if len(h) == 4:
            r, g, b, a = (int(c * 2, 16) for c in h)
            return (float(r), float(g), float(b), a / 255.0)
        if len(h) == 6:
            return (float(int(h[0:2], 16)), float(int(h[2:4], 16)), float(int(h[4:6], 16)), 1.0)
        if len(h) == 8:
            return (
                float(int(h[0:2], 16)),
                float(int(h[2:4], 16)),
                float(int(h[4:6], 16)),
                int(h[6:8], 16) / 255.0,
            )
    m = RGBA_RE.match(v)
    if m:
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b, a)
    raise AssertionError(f"Unsupported color token value: {value!r}")


def _composite_over(
    fg: tuple[float, float, float, float],
    bg: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    a = fg[3]
    out_a = a + bg[3] * (1.0 - a)
    if out_a <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        (fg[0] * a + bg[0] * bg[3] * (1.0 - a)) / out_a,
        (fg[1] * a + bg[1] * bg[3] * (1.0 - a)) / out_a,
        (fg[2] * a + bg[2] * bg[3] * (1.0 - a)) / out_a,
        out_a,
    )


def _relative_luminance(rgb: tuple[float, float, float, float]) -> float:
    def channel(c: float) -> float:
        s = max(0.0, min(255.0, c)) / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def _contrast_ratio(
    c1: tuple[float, float, float, float],
    c2: tuple[float, float, float, float],
) -> float:
    l1 = _relative_luminance(c1)
    l2 = _relative_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _iter_v2_source_files() -> list[Path]:
    files: list[Path] = []
    if not DESKTOP_SRC.is_dir():
        return files
    v2_dirs: set[Path] = {DESKTOP_SRC / d for d in EXPLICIT_V2_SUBDIRS if (DESKTOP_SRC / d).is_dir()}
    for child in DESKTOP_SRC.iterdir():
        if child.is_dir() and child.name not in LEGACY_V1_SUBDIRS:
            v2_dirs.add(child)
    for d in sorted(v2_dirs):
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix not in {".css", ".ts", ".tsx"}:
                continue
            rel = p.relative_to(DESKTOP_SRC).as_posix()
            if "/__tests__/" in f"/{rel}/":
                continue
            files.append(p)
    return files


def _find_hex_literals_in_css(css_text: str, rel_label: str) -> list[str]:
    violations: list[str] = []
    for _media, selector, body in _iter_css_rules(css_text):
        for raw_decl in body.split(";"):
            raw_decl = raw_decl.strip()
            if ":" not in raw_decl:
                continue
            prop, val = raw_decl.split(":", 1)
            scrubbed = re.sub(r"url\([^)]*\)", "", val, flags=re.IGNORECASE)
            for m in HEX_COLOR_RE.finditer(scrubbed):
                violations.append(
                    f"{rel_label}: hex literal {m.group(0)!r} in {selector} {{ {prop.strip()}: {val.strip()} }}"
                )
    return violations


def _find_hex_literals_in_ts(ts_text: str, rel_label: str) -> list[str]:
    violations: list[str] = []
    cleaned = _strip_js_comments_keep_strings(ts_text)
    # Match quoted strings and multiline template literals across the whole file.
    str_re = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
    for sm in str_re.finditer(cleaned):
        content = sm.group(2)
        prefix = cleaned[max(0, sm.start() - 24) : sm.start()]
        # Exempt anchor href="#..." / xlink:href="#..." attribute strings only.
        if re.search(r"(?:href|xlink:href)\s*=\s*$", prefix) and content.startswith("#"):
            continue
        scrubbed = re.sub(r"url\(#[^)]*\)", "", content, flags=re.IGNORECASE)
        for hm in HEX_COLOR_RE.finditer(scrubbed):
            abs_pos = sm.start(2) + hm.start()
            lineno = cleaned.count("\n", 0, abs_pos) + 1
            violations.append(
                f"{rel_label}:{lineno}: hex literal {hm.group(0)!r}"
            )
    return violations


def _selector_subject(selector: str) -> str:
    """Return the subject (rightmost compound selector) of a CSS selector."""
    parts = re.split(r"[\s>+~]+", selector.strip())
    return parts[-1] if parts else selector.strip()


def _find_deprecated_aliases(text: str, suffix: str, rel_label: str) -> list[str]:
    cleaned = _strip_css_comments(text) if suffix == ".css" else _strip_js_comments_keep_strings(text)
    violations: list[str] = []
    for lineno, line in enumerate(cleaned.splitlines(), start=1):
        for m in VAR_REF_RE.finditer(line):
            var_name = m.group(1)
            if var_name in DEPRECATED_V1_ALIASES:
                violations.append(
                    f"{rel_label}:{lineno}: deprecated v1 token alias {var_name} in {line.strip()}"
                )
    return violations


def _find_css_usage_violations(css_text: str, rel_label: str) -> list[str]:
    """Enforce J1 §4 usage rules statically on v2 CSS files."""
    violations: list[str] = []
    for _media, selector_list, body in _iter_css_rules(css_text):
        selectors = [s.strip() for s in selector_list.split(",") if s.strip()]
        decls = []
        for raw_decl in body.split(";"):
            raw_decl = raw_decl.strip()
            if ":" not in raw_decl:
                continue
            prop, val = raw_decl.split(":", 1)
            decls.append((prop.strip().lower(), val.strip()))

        for prop, val in decls:
            # Rule 1: --fact / --fact-tint only inside [data-fact]
            if re.search(r"var\(\s*--fact(?:-tint)?\b", val):
                for sel in selectors:
                    if "[data-fact" not in sel:
                        violations.append(
                            f"{rel_label}: {prop} uses --fact outside [data-fact] on selector {sel!r}"
                        )

            # Rule 2: --accent / --accent-tint / --accent-line only on
            # [data-source="agent"], [data-accent], or focus selectors/outline.
            if re.search(r"var\(\s*--accent(?:-(?:tint|line))?\b", val):
                is_outline = prop in {"outline", "outline-color"}
                for sel in selectors:
                    allowed = (
                        is_outline
                        or '[data-source="agent"]' in sel
                        or "[data-source='agent']" in sel
                        or "[data-accent" in sel
                        or ":focus" in sel
                    )
                    if not allowed:
                        violations.append(
                            f"{rel_label}: {prop} uses --accent outside allowed scopes on selector {sel!r}"
                        )

            # Rule 3: [data-docked] elements carry no shadow and never use --raised / --shadow-float
            for sel in selectors:
                if "[data-docked" in _selector_subject(sel):
                    if prop == "box-shadow" and val.lower() not in {"none", "initial", "unset"}:
                        violations.append(
                            f"{rel_label}: [data-docked] selector {sel!r} declares box-shadow: {val}"
                        )
                    if re.search(r"var\(\s*--(?:raised|shadow-float)\b", val):
                        violations.append(
                            f"{rel_label}: [data-docked] selector {sel!r} uses floating token in {prop}: {val}"
                        )

            # Rule 4: --ink button fill only on [data-variant="primary"]
            if prop in {"background", "background-color"} and re.search(r"var\(\s*--ink\b", val):
                for sel in selectors:
                    subj = _selector_subject(sel)
                    is_pseudo = "::before" in subj or "::after" in subj
                    is_button = bool(re.search(r"(?:^|\.)(?:button|btn)\b|^button\b|\[role=['\"]button['\"]\]", subj))
                    is_primary = '[data-variant="primary"]' in subj or "[data-variant='primary']" in subj
                    if is_button and not is_pseudo and not is_primary:
                        violations.append(
                            f"{rel_label}: button selector {sel!r} fills with --ink without [data-variant=\"primary\"]"
                        )
    return violations


# ---------------------------------------------------------------------------
# Gate 1: J1 §4 block verbatim & no banned legacy palette hexes
# ---------------------------------------------------------------------------


def test_tokens_css_contains_j1_section_4_verbatim() -> None:
    assert TOKENS_CSS.is_file(), f"Missing {TOKENS_CSS}"
    css = TOKENS_CSS.read_text(encoding="utf-8")
    assert J1_SECTION_4_VERBATIM in css, (
        "desktop/src/tokens.css must contain the exact J1 §4 token block verbatim"
    )
    assert '@font-face' in css and 'Pretendard Variable' in css, (
        "desktop/src/tokens.css must keep the bundled Pretendard Variable @font-face"
    )
    cleaned = _strip_css_comments(css).upper()
    for banned in BANNED_TOKEN_HEXES:
        assert banned.upper() not in cleaned, (
            f"Banned legacy color {banned} still present in desktop/src/tokens.css"
        )


# ---------------------------------------------------------------------------
# Gate 2: All v1 names and v2 tokens resolve without cycles in all modes
# ---------------------------------------------------------------------------


def test_all_v1_and_v2_tokens_resolve_without_cycles() -> None:
    css = TOKENS_CSS.read_text(encoding="utf-8")
    maps = _parse_token_maps(css)

    # Auto dark media query stays in lockstep with explicit [data-theme="dark"]
    assert maps["auto_dark_only"] == maps["dark_only"], (
        "@media (prefers-color-scheme: dark) :root:not([data-theme=\"light\"]) "
        "must mirror :root[data-theme=\"dark\"]"
    )
    # html:root guard against frozen v1 styles.css may only repeat exact J1 §4 light/root values
    for guard_k, guard_v in maps["html_root_guard"].items():
        assert maps["light"].get(guard_k) == guard_v, (
            f"html:root guard token {guard_k}={guard_v!r} drifts from J1 §4 ({maps['light'].get(guard_k)!r})"
        )

    for theme_name in ("light", "dark", "auto_dark"):
        tmap = maps[theme_name]
        # Every v1 token name must resolve cleanly
        for name in V1_TOKEN_NAMES:
            assert name in tmap, f"Missing v1 token alias {name} in {theme_name}"
            resolved = _resolve_var(name, tmap)
            assert resolved and "var(" not in resolved, (
                f"v1 token {name} failed to resolve in {theme_name}: {resolved!r}"
            )
        # Every declared token in tokens.css must resolve cleanly without cycles
        for name in sorted(tmap):
            resolved = _resolve_var(name, tmap)
            assert resolved and "var(" not in resolved, (
                f"Token {name} failed to resolve in {theme_name}: {resolved!r}"
            )

    # Paper and ink invariants across both themes
    for theme_name in ("light", "dark", "auto_dark"):
        tmap = maps[theme_name]
        assert _resolve_var("--paper", tmap).upper() == "#FFFFFF"
        assert _resolve_var("--bg-paper", tmap).upper() == "#FFFFFF"
        assert _resolve_var("--paper-ink", tmap).upper() == "#111111"
        assert _resolve_var("--seat", tmap).upper() == "#F5F2E8"
        assert _resolve_var("--text-xs", tmap) == "11px"
        assert _resolve_var("--text-sm", tmap) == "12px"
        assert _resolve_var("--text-base", tmap) == "13px"
        assert _resolve_var("--text-lg", tmap) == "15px"
        assert _resolve_var("--text-display", tmap) == "20px"
        assert _resolve_var("--weight-regular", tmap) == "400"
        assert _resolve_var("--weight-semibold", tmap) == "600"
        assert _resolve_var("--radius-0", tmap) == "0"
        assert _resolve_var("--radius-sm", tmap) == "4px"
        assert _resolve_var("--radius-md", tmap) == "6px"

    # Reduced motion overrides
    rm = maps["reduced_motion"]
    assert _resolve_var("--dur-panel", rm) == "0ms"
    assert _resolve_var("--dur-scroll", rm) == "0ms"
    assert _resolve_var("--dur-mark-in", rm) == "0ms"
    assert _resolve_var("--dur-mark-dry", rm) == "120ms"
    assert _resolve_var("--dur-splash", rm) == "0ms"


# ---------------------------------------------------------------------------
# Gate 3: WCAG 2.1 contrast (>= 4.5:1 text, >= 3.0:1 --line-control)
# ---------------------------------------------------------------------------


def test_declared_chrome_text_pairs_meet_wcag_aa_contrast() -> None:
    maps = _parse_token_maps(TOKENS_CSS.read_text(encoding="utf-8"))
    surfaces = ("--desk", "--chrome", "--panel", "--field", "--raised")
    text_tokens = ("--ink", "--text-2", "--text-3", "--accent", "--fact", "--attn", "--expected")
    failures: list[str] = []

    for theme_name in ("light", "dark"):
        tmap = maps[theme_name]
        color = lambda tok: _parse_color(_resolve_var(tok, tmap))

        # Every text token on every solid surface
        for txt in text_tokens:
            for surf in surfaces:
                ratio = _contrast_ratio(color(txt), color(surf))
                if ratio < 4.5:
                    failures.append(f"{theme_name}: {txt} on {surf} = {ratio:.2f}:1 (< 4.5)")

        # Text on --hover and --selected over docked chrome/panel surfaces
        for state_tok in ("--hover", "--selected"):
            state_rgba = color(state_tok)
            for base_surf in ("--chrome", "--panel"):
                eff_bg = _composite_over(state_rgba, color(base_surf))
                for txt in text_tokens:
                    ratio = _contrast_ratio(color(txt), eff_bg)
                    if ratio < 4.5:
                        failures.append(
                            f"{theme_name}: {txt} on {state_tok}({base_surf}) = {ratio:.2f}:1 (< 4.5)"
                        )

        # Primary button and semantic chip pairs
        paired = (
            ("--on-ink", "--ink"),
            ("--accent", "--accent-tint"),
            ("--fact", "--fact-tint"),
            ("--attn", "--attn-tint"),
            ("--expected", "--expected-tint"),
        )
        for fg_tok, bg_tok in paired:
            ratio = _contrast_ratio(color(fg_tok), color(bg_tok))
            if ratio < 4.5:
                failures.append(f"{theme_name}: {fg_tok} on {bg_tok} = {ratio:.2f}:1 (< 4.5)")

    assert not failures, "WCAG AA (4.5:1) chrome contrast failures:\n" + "\n".join(failures)


def test_line_control_meets_non_text_contrast() -> None:
    maps = _parse_token_maps(TOKENS_CSS.read_text(encoding="utf-8"))
    failures: list[str] = []

    for theme_name in ("light", "dark"):
        tmap = maps[theme_name]
        fg = _parse_color(_resolve_var("--line-control", tmap))
        for surf in ("--chrome", "--panel", "--field", "--raised"):
            bg = _parse_color(_resolve_var(surf, tmap))
            ratio = _contrast_ratio(fg, bg)
            if ratio < 3.0:
                failures.append(f"{theme_name}: --line-control on {surf} = {ratio:.2f}:1 (< 3.0)")

    assert not failures, "WCAG non-text (3.0:1) --line-control failures:\n" + "\n".join(failures)


def test_paper_text_and_mark_styles_meet_contrast_in_both_themes() -> None:
    """Advisor Ruling §D: verify every text style on paper >= 4.5:1 in light and dark veil."""
    maps = _parse_token_maps(TOKENS_CSS.read_text(encoding="utf-8"))
    failures: list[str] = []

    for theme_name in ("light", "dark"):
        tmap = maps[theme_name]
        color = lambda tok: _parse_color(_resolve_var(tok, tmap))
        paper = color("--paper")
        veil = color("--paper-veil")

        def veiled(surface_rgba: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
            return _composite_over(veil, surface_rgba)

        paper_bg = veiled(paper)
        seat_bg = veiled(color("--seat"))
        tints = {
            "--mark-insert-tint": veiled(_composite_over(color("--mark-insert-tint"), paper)),
            "--mark-fact-tint": veiled(_composite_over(color("--mark-fact-tint"), paper)),
            "--mark-test-tint": veiled(_composite_over(color("--mark-test-tint"), paper)),
            "--mark-selected-tint": veiled(_composite_over(color("--mark-selected-tint"), paper)),
        }

        paper_ink = color("--paper-ink")
        for label, bg in (("--paper", paper_bg), ("--seat", seat_bg), *tints.items()):
            ratio = _contrast_ratio(paper_ink, bg)
            if ratio < 4.5:
                failures.append(f"{theme_name}: --paper-ink on {label} = {ratio:.2f}:1 (< 4.5)")

        # Deleted text & margin number hues on paper (with dark veil when dark)
        for fg_tok in ("--mark-delete-text", "--mark-insert", "--mark-fact", "--mark-accepted"):
            ratio = _contrast_ratio(color(fg_tok), paper_bg)
            if ratio < 4.5:
                failures.append(f"{theme_name}: {fg_tok} on --paper = {ratio:.2f}:1 (< 4.5)")

        # Selected filled margin tags (paper white text on mark hue fill)
        for tag_bg_tok in ("--mark-insert", "--mark-fact", "--mark-accepted"):
            ratio = _contrast_ratio(paper, veiled(color(tag_bg_tok)))
            if ratio < 4.5:
                failures.append(
                    f"{theme_name}: --paper text on {tag_bg_tok} tag = {ratio:.2f}:1 (< 4.5)"
                )

    assert not failures, "WCAG AA (4.5:1) paper contrast failures:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Gate 4 & 5: No hex literals, no v1 aliases, and usage rules in v2 directories
# ---------------------------------------------------------------------------


def test_no_hex_color_literals_outside_tokens_in_v2_dirs() -> None:
    violations: list[str] = []
    for path in _iter_v2_source_files():
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            violations.extend(_find_hex_literals_in_css(text, rel))
        else:
            violations.extend(_find_hex_literals_in_ts(text, rel))
    assert not violations, "Hex color literals found in v2 directories:\n" + "\n".join(violations)


def test_no_deprecated_v1_aliases_in_v2_dirs() -> None:
    violations: list[str] = []
    for path in _iter_v2_source_files():
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        violations.extend(_find_deprecated_aliases(text, path.suffix, rel))
    assert not violations, "Deprecated v1 token aliases found in v2 directories:\n" + "\n".join(
        violations
    )


def test_v2_css_token_usage_rules() -> None:
    violations: list[str] = []
    for path in _iter_v2_source_files():
        if path.suffix != ".css":
            continue
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        violations.extend(_find_css_usage_violations(path.read_text(encoding="utf-8"), rel))
    assert not violations, "J1 §4 CSS token usage rule violations:\n" + "\n".join(violations)


CSS_CLASS_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_-]*)")


def _v1_class_names() -> set[str]:
    """Classes the v1 stylesheet (styles.css) styles; `?ui=v1` renders with these."""
    names: set[str] = set()
    for _media, selector, _body in _iter_css_rules(STYLES_CSS.read_text(encoding="utf-8")):
        for part in selector.split(","):
            names.update(CSS_CLASS_RE.findall(part))
    return names


def _find_v1_leaks(css_text: str, rel_label: str, v1_classes: set[str]) -> list[str]:
    """v2 rules that select a v1 class without a v2-only ancestor."""
    leaks: list[str] = []
    for media, selector, _body in _iter_css_rules(css_text):
        if media and media.startswith(("@keyframes", "@-webkit-keyframes")):
            continue
        for part in selector.split(","):
            part = part.strip()
            if not any(c in v1_classes for c in CSS_CLASS_RE.findall(part)):
                continue
            lead = re.split(r"\s*[\s>+~]\s*", part, maxsplit=1)[0]
            lead_classes = CSS_CLASS_RE.findall(lead)
            if "shell-v2" in lead_classes or any(c not in v1_classes for c in lead_classes):
                continue
            leaks.append(f"{rel_label}: {part}")
    return leaks


def test_v2_styles_do_not_restyle_the_v1_ui() -> None:
    """`?ui=v1` keeps its own look: a v2 stylesheet that restyles a class the
    v1 stylesheet also styles (the toast) must scope it to the v2 shell."""
    v1_classes = _v1_class_names()
    assert "toast" in v1_classes
    leaks: list[str] = []
    for path in _iter_v2_source_files():
        if path.suffix != ".css":
            continue
        rel = path.relative_to(DESKTOP_SRC).as_posix()
        leaks.extend(_find_v1_leaks(path.read_text(encoding="utf-8"), rel, v1_classes))
    assert not leaks, "v2 rules restyle the v1 UI:\n" + "\n".join(leaks)
    # The detector itself: an unscoped override is caught, a scoped one is not.
    assert _find_v1_leaks("body .toast { color: red; }", "probe", v1_classes) == ["probe: body .toast"]
    assert _find_v1_leaks(".shell-v2 .toast { color: red; }", "probe", v1_classes) == []


def test_token_lint_detectors_catch_violations_and_allow_valid_v2() -> None:
    # Hex detector catches single-line, multi-line, and @keyframes CSS hexes; ignores comments & url(#id)
    bad_css = (
        "/* #1A56DB */\n"
        ".chip { color: #2A48A4; background: url(#clip0); }\n"
        ".ml {\n  border-color:\n    #B4232A;\n}\n"
        "@keyframes fade { from { color: #fff; } to { color: var(--ink); } }\n"
    )
    css_hits = _find_hex_literals_in_css(bad_css, "ui/sample.css")
    assert len(css_hits) == 3, css_hits
    assert any("#2A48A4" in h for h in css_hits)
    assert any("#B4232A" in h for h in css_hits)
    assert any("#fff" in h for h in css_hits)

    # TSX detector catches inline, same-line-with-href, and multiline template hexes; allows href="#abc" & url(#id)
    bad_tsx = (
        '// #111111\n'
        'const a = "url(#grad0)";\n'
        'const okLink = <a href="#abc">ok</a>;\n'
        'const sneaky = <a href="#abc" style={{ color: "#1A56DB" }}>x</a>;\n'
        'const tmpl = `\n  background: #fff;\n`;\n'
    )
    ts_hits = _find_hex_literals_in_ts(bad_tsx, "ui/sample.tsx")
    assert len(ts_hits) == 2, ts_hits
    assert any("#1A56DB" in h for h in ts_hits)
    assert any("#fff" in h for h in ts_hits)

    # Deprecated alias detector catches v1 aliases while allowing v2 tokens
    alias_hits = _find_deprecated_aliases(
        ".a { color: var(--ink); background: var(--bg-surface); }", ".css", "ui/a.css"
    )
    assert len(alias_hits) == 1 and "--bg-surface" in alias_hits[0]

    # Usage rules catch violations (including inside @supports / @layer)
    bad_usage = """
    .row { color: var(--fact); }
    .badge { color: var(--accent); }
    .pane[data-docked] { background: var(--raised); box-shadow: var(--shadow-float); }
    button.secondary { background: var(--ink); }
    @supports (display: grid) { .sneaky { color: var(--fact); } }
    """
    usage_hits = _find_css_usage_violations(bad_usage, "ui/bad.css")
    assert any("--fact outside [data-fact]" in h and ".row" in h for h in usage_hits), usage_hits
    assert any("--fact outside [data-fact]" in h and ".sneaky" in h for h in usage_hits), usage_hits
    assert any("--accent outside allowed scopes" in h for h in usage_hits), usage_hits
    assert any("declares box-shadow" in h for h in usage_hits), usage_hits
    assert any("uses floating token in background" in h for h in usage_hits), usage_hits
    assert any("fills with --ink without [data-variant=\"primary\"]" in h for h in usage_hits), usage_hits

    # Valid v2 CSS passes all usage rules (including floating popover nested in [data-docked])
    good_usage = """
    .row[data-fact] { color: var(--fact); background: var(--fact-tint); }
    .row[data-source="agent"] { border-left: 2px solid var(--accent); }
    .tab-pill[data-accent] { color: var(--accent); background: var(--accent-tint); }
    .input:focus-visible { outline: var(--focus-width) solid var(--accent); }
    .pane[data-docked] { background: var(--panel); box-shadow: none; }
    .pane[data-docked] .popover { background: var(--raised); box-shadow: var(--shadow-float); }
    .popover { background: var(--raised); box-shadow: var(--shadow-float); }
    button[data-variant="primary"] { background: var(--ink); color: var(--on-ink); }
    button.tab[aria-selected="true"]::after { background: var(--ink); }
    """
    assert _find_css_usage_violations(good_usage, "ui/good.css") == []


# ---------------------------------------------------------------------------
# Gate 6: Live Chromium cascade & contrast test (standalone + with styles.css)
# ---------------------------------------------------------------------------


def test_tokens_resolve_in_chromium_without_cycles_and_meet_contrast() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        no_browser(f"playwright unavailable: {exc}")

    tokens_text = TOKENS_CSS.read_text(encoding="utf-8")
    styles_text = STYLES_CSS.read_text(encoding="utf-8")
    # Remove @import "./tokens.css"; since we inline tokens.css first in the test harness.
    styles_body = re.sub(r'@import\s+["\']\.\/tokens\.css["\']\s*;', "", styles_text, count=1)

    all_token_names = sorted(_parse_token_maps(tokens_text)["light"].keys())

    harness_html = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <style id="tokens-css"></style>
  <style id="styles-css"></style>
</head>
<body>
  <div id="paper" style="background: var(--paper); color: var(--paper-ink);">문서 본문</div>
  <div id="swatch-root"></div>
</body>
</html>"""

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:
            no_browser(f"headless Chromium unavailable: {exc}")
        try:
            for include_styles in (False, True):
                mode_label = "tokens+styles" if include_styles else "tokens-only"
                for theme_attr, media_scheme, expect_dark in (
                    ("light", "light", False),
                    ("dark", "dark", True),
                    (None, "light", False),
                    (None, "dark", True),
                    ("light", "dark", False),
                ):
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        color_scheme=media_scheme,
                    )
                    page = context.new_page()
                    page.set_content(harness_html)
                    page.evaluate(
                        """([tCss, sCss, attr]) => {
                            document.getElementById("tokens-css").textContent = tCss;
                            document.getElementById("styles-css").textContent = sCss;
                            if (attr === null) {
                                document.documentElement.removeAttribute("data-theme");
                            } else {
                                document.documentElement.setAttribute("data-theme", attr);
                            }
                        }""",
                        [tokens_text, styles_body if include_styles else "", theme_attr],
                    )

                    result = page.evaluate(
                        """(names) => {
                            const cs = getComputedStyle(document.documentElement);
                            const empty = [];
                            const values = {};
                            for (const name of names) {
                                const v = cs.getPropertyValue(name).trim();
                                values[name] = v;
                                if (!v) empty.push(name);
                            }
                            const paperBg = getComputedStyle(document.getElementById("paper")).backgroundColor;
                            const paperFg = getComputedStyle(document.getElementById("paper")).color;

                            const swatchRoot = document.getElementById("swatch-root");
                            swatchRoot.innerHTML = "";
                            const pairs = [
                                ["--ink", "--desk"], ["--ink", "--chrome"], ["--ink", "--panel"],
                                ["--ink", "--field"], ["--ink", "--raised"],
                                ["--text-2", "--desk"], ["--text-2", "--chrome"], ["--text-2", "--panel"],
                                ["--text-2", "--field"], ["--text-2", "--raised"],
                                ["--text-3", "--desk"], ["--text-3", "--chrome"], ["--text-3", "--panel"],
                                ["--text-3", "--field"], ["--text-3", "--raised"],
                                ["--accent", "--panel"], ["--accent", "--accent-tint"],
                                ["--fact", "--panel"], ["--fact", "--fact-tint"],
                                ["--attn", "--panel"], ["--attn", "--attn-tint"],
                                ["--expected", "--panel"], ["--expected", "--expected-tint"],
                                ["--on-ink", "--ink"],
                                ["--paper-ink", "--paper"], ["--paper-ink", "--seat"],
                                ["--mark-delete-text", "--paper"], ["--mark-insert", "--paper"],
                                ["--mark-fact", "--paper"], ["--mark-accepted", "--paper"],
                            ];
                            const computedPairs = [];
                            for (const [fg, bg] of pairs) {
                                const el = document.createElement("span");
                                el.style.color = `var(${fg})`;
                                el.style.backgroundColor = `var(${bg})`;
                                el.textContent = "가";
                                swatchRoot.appendChild(el);
                                const ecs = getComputedStyle(el);
                                computedPairs.push([fg, bg, ecs.color, ecs.backgroundColor]);
                            }
                            const lineControlPairs = [];
                            for (const bg of ["--chrome", "--panel", "--field", "--raised"]) {
                                const el = document.createElement("span");
                                el.style.borderColor = "var(--line-control)";
                                el.style.backgroundColor = `var(${bg})`;
                                swatchRoot.appendChild(el);
                                const ecs = getComputedStyle(el);
                                lineControlPairs.push(["--line-control", bg, ecs.borderTopColor, ecs.backgroundColor]);
                            }
                            return { empty, values, paperBg, paperFg, computedPairs, lineControlPairs };
                        }""",
                        all_token_names,
                    )
                    assert result["empty"] == [], (
                        f"{mode_label} (data-theme={theme_attr!r}, scheme={media_scheme}): "
                        f"empty/cyclic custom properties: {result['empty']}"
                    )
                    assert result["paperBg"] == "rgb(255, 255, 255)", (
                        f"{mode_label}: paper background drifted: {result['paperBg']}"
                    )
                    assert result["paperFg"] == "rgb(17, 17, 17)"
                    for fg_tok, bg_tok, fg_css, bg_css in result["computedPairs"]:
                        ratio = _contrast_ratio(_parse_color(fg_css), _parse_color(bg_css))
                        assert ratio >= 4.5, (
                            f"{mode_label} (dark={expect_dark}): {fg_tok}({fg_css}) on "
                            f"{bg_tok}({bg_css}) = {ratio:.2f}:1 (< 4.5)"
                        )
                    for fg_tok, bg_tok, fg_css, bg_css in result["lineControlPairs"]:
                        ratio = _contrast_ratio(_parse_color(fg_css), _parse_color(bg_css))
                        assert ratio >= 3.0, (
                            f"{mode_label} (dark={expect_dark}): {fg_tok}({fg_css}) on "
                            f"{bg_tok}({bg_css}) = {ratio:.2f}:1 (< 3.0)"
                        )
                    vals = result["values"]
                    assert vals["--text-xs"] == "11px", f"{mode_label}: --text-xs={vals['--text-xs']}"
                    if expect_dark:
                        assert vals["--line"].upper() == "#26272B"
                        assert vals["--border-subtle"].upper() == "#26272B"
                        assert vals["--accent"].upper() == "#9FB4F0"
                        assert vals["--focus"].upper() == "#9FB4F0"
                    else:
                        assert vals["--line"].upper() == "#E0DED8"
                        assert vals["--border-subtle"].upper() == "#E0DED8"
                        assert vals["--accent"].upper() == "#2A48A4"
                        assert vals["--focus"].upper() == "#2A48A4"
                    context.close()

            # Reduced motion media query verification
            rm_ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                reduced_motion="reduce",
            )
            rm_page = rm_ctx.new_page()
            rm_page.set_content(harness_html)
            rm_page.evaluate(
                "(tCss) => { document.getElementById('tokens-css').textContent = tCss; }",
                tokens_text,
            )
            durs = rm_page.evaluate(
                """() => {
                    const cs = getComputedStyle(document.documentElement);
                    return {
                        panel: cs.getPropertyValue("--dur-panel").trim(),
                        scroll: cs.getPropertyValue("--dur-scroll").trim(),
                        markIn: cs.getPropertyValue("--dur-mark-in").trim(),
                        markDry: cs.getPropertyValue("--dur-mark-dry").trim(),
                        splash: cs.getPropertyValue("--dur-splash").trim(),
                    };
                }"""
            )
            assert durs == {
                "panel": "0ms",
                "scroll": "0ms",
                "markIn": "0ms",
                "markDry": "120ms",
                "splash": "0ms",
            }, durs
            rm_ctx.close()
        finally:
            browser.close()
