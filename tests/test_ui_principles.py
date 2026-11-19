# -*- coding: utf-8 -*-
"""Reusable Playwright UI principle-assertion harness and self-tests for editor v2.

Enforces all binding J1 §5, D1 §1, and advisor ruling D visual & structural
principles on any Playwright `Page`:

1. `single_primary_button`: at most one visible `[data-variant="primary"]` and
   at most one visually filled CTA button per window, rendered in neutral ink.
2. `paper_surface`: `[data-testid="paper"]` stays `rgb(255, 255, 255)` in both
   light and dark themes, has `0px` corner radius, never renders Pretendard
   body text, and no `[data-docked]` chrome surface is `#FFFFFF`.
3. `no_long_hex_hashes`: no visible text matches `[0-9a-f]{13,}` (including
   hashes split across inline elements).
4. `no_docked_shadow`: no `box-shadow` or `filter: drop-shadow(...)` on
   `[data-docked]` regions or their non-floating chrome descendants.
5. `reserved_hues`: crimson / `--fact` only inside `[data-fact]` (exempting
   `--win-close-hover` on `[data-win-close]`), `--accent` only inside
   `[data-source="agent"]`, `[data-accent]`, focus rings, or agent page marks,
   and no saturated green anywhere in chrome.
6. `chrome_typography`: visible chrome font sizes within `{11, 12, 13, 15, 20}`
   px and weights within `{400, 600}`.
7. `border_radius`: corner radii `<= 6px` in chrome and `0px` on paper.
8. `no_workspace_sentences`: in the default workspace, no visible text ending
   in `다.` outside `[data-testid="paper"]`, thread, and sheet.
9. `text_contrast`: WCAG 2.1 contrast `>= 4.5:1` for all enabled visible text
   across chrome and paper in both themes.
10. `no_horizontal_overflow`: `document.documentElement.scrollWidth <= window.innerWidth`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from _browser_gate import no_browser  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
# The base mockup the J1 §1 rules were written against is not in the repo.
# Point RL_BASE_MOCKUP_HTML at its 1440px workspace page to run the self-check.
BASE_MOCKUP_WORKSPACE = Path(os.environ.get("RL_BASE_MOCKUP_HTML") or "/nonexistent")
PRETENDARD_FONT = REPO_ROOT / "desktop" / "src" / "assets" / "fonts" / "PretendardVariable.woff2"
NANUM_FONT = REPO_ROOT / "engine" / "references" / "fonts" / "family-map" / "NanumMyeongjo-Regular.ttf"


@dataclass(frozen=True)
class PrincipleViolation:
    rule: str
    detail: str
    selector: str = ""

    def format(self) -> str:
        loc = f" ({self.selector})" if self.selector else ""
        return f"[{self.rule}]{loc}: {self.detail}"


@dataclass(frozen=True)
class PrincipleReport:
    violations: tuple[PrincipleViolation, ...]
    metrics: dict[str, Any]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def rules(self) -> set[str]:
        return {v.rule for v in self.violations}

    def summary(self) -> str:
        if self.ok:
            return "All UI principles passed (0 violations)."
        return "\n".join(v.format() for v in self.violations)


_EVAL_PRINCIPLES_JS = r"""
(opts) => {
  const violations = [];
  const add = (rule, detail, el) => {
    let sel = "";
    if (el && el.tagName) {
      const tag = el.tagName.toLowerCase();
      const tid = el.getAttribute && el.getAttribute("data-testid");
      const id = el.id;
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      sel = tid ? `${tag}[data-testid="${tid}"]` : id ? `${tag}#${id}` : cls ? `${tag}.${cls}` : tag;
    }
    violations.push({ rule, detail, selector: sel });
  };

  // --- Color parsing & WCAG contrast helpers ---
  const parseRgba = (str) => {
    if (!str || str === "transparent" || str === "none") return { r: 0, g: 0, b: 0, a: 0 };
    const m = str.match(/rgba?\(\s*([\d.]+)\s*[,\s]\s*([\d.]+)\s*[,\s]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)/i);
    if (!m) return null;
    return {
      r: Math.round(Number(m[1])),
      g: Math.round(Number(m[2])),
      b: Math.round(Number(m[3])),
      a: m[4] === undefined ? 1 : Number(m[4]),
    };
  };

  const compositeOver = (fg, bg) => {
    const a = fg.a;
    if (a >= 0.999) return { r: fg.r, g: fg.g, b: fg.b, a: 1 };
    const inv = 1 - a;
    return {
      r: Math.round(fg.r * a + bg.r * inv),
      g: Math.round(fg.g * a + bg.g * inv),
      b: Math.round(fg.b * a + bg.b * inv),
      a: 1,
    };
  };

  const relLum = (c) => {
    const ch = [c.r, c.g, c.b].map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };

  const contrastRatio = (c1, c2) => {
    const l1 = relLum(c1);
    const l2 = relLum(c2);
    const hi = Math.max(l1, l2);
    const lo = Math.min(l1, l2);
    return (hi + 0.05) / (lo + 0.05);
  };

  const resolveTokenRgb = (varName, fallback) => {
    const probe = document.createElement("span");
    probe.style.position = "fixed";
    probe.style.visibility = "hidden";
    probe.style.pointerEvents = "none";
    probe.style.color = `var(${varName}, ${fallback})`;
    document.body.appendChild(probe);
    const parsed = parseRgba(getComputedStyle(probe).color);
    probe.remove();
    return parsed || parseRgba(fallback);
  };

  const sameRgb = (a, b, tol = 10) => {
    if (!a || !b || a.a < 0.05 || b.a < 0.05) return false;
    return Math.abs(a.r - b.r) <= tol && Math.abs(a.g - b.g) <= tol && Math.abs(a.b - b.b) <= tol;
  };

  const isNeutral = (c) => Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b) <= 18;
  const isCrimsonHue = (c) => c && c.a >= 0.15 && c.r >= 150 && (c.r - c.g) >= 65 && (c.r - c.b) >= 65;
  const isBlueAccentHue = (c) => c && c.a >= 0.15 && c.b >= 130 && (c.b - c.r) >= 45 && (c.b - c.g) >= 25;
  const isGreenHue = (c) => c && c.a >= 0.15 && c.g >= 95 && (c.g - c.r) >= 25 && (c.g - c.b) >= 18;

  const isVisible = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const tag = el.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "TEMPLATE") return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) return false;
    // Closed <details> children (other than <summary>) are hidden.
    let cur = el;
    while (cur && cur !== document.body) {
      if (cur.parentElement && cur.parentElement.tagName === "DETAILS" && !cur.parentElement.open && cur.tagName !== "SUMMARY") {
        return false;
      }
      cur = cur.parentElement;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0.5 && rect.height > 0.5;
  };

  const effectiveBg = (el) => {
    const layers = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      const bg = parseRgba(getComputedStyle(cur).backgroundColor);
      if (bg && bg.a > 0.01) {
        layers.push(bg);
        if (bg.a >= 0.999) break;
      }
      cur = cur.parentElement;
    }
    let acc = { r: 255, g: 255, b: 255, a: 1 };
    const theme = document.documentElement.getAttribute("data-theme");
    if (theme === "dark") acc = { r: 15, g: 16, b: 18, a: 1 };
    for (let i = layers.length - 1; i >= 0; i -= 1) {
      acc = compositeOver(layers[i], acc);
    }
    return acc;
  };

  const hasDirectText = (el) => {
    for (const node of el.childNodes) {
      if (node.nodeType === 3 && node.nodeValue && node.nodeValue.trim().length > 0) {
        return true;
      }
    }
    return false;
  };

  const isDisabledEl = (el) => {
    let cur = el;
    while (cur && cur !== document.body) {
      if (
        cur.hasAttribute("disabled") ||
        cur.getAttribute("aria-disabled") === "true" ||
        cur.getAttribute("data-disabled") === "true"
      ) {
        return true;
      }
      cur = cur.parentElement;
    }
    return false;
  };

  const theme = document.documentElement.getAttribute("data-theme") || "light";
  const tokFact = resolveTokenRgb("--fact", theme === "dark" ? "#F0787C" : "#B4232A");
  const tokFactTint = resolveTokenRgb("--fact-tint", theme === "dark" ? "#3A1719" : "#FBE9E9");
  const tokAccent = resolveTokenRgb("--accent", theme === "dark" ? "#9FB4F0" : "#2A48A4");
  const tokAccentTint = resolveTokenRgb("--accent-tint", theme === "dark" ? "#1A2340" : "#E7EBF6");
  const tokAccentLine = resolveTokenRgb("--accent-line", theme === "dark" ? "#33457A" : "#BFC9E8");
  const tokWinClose = resolveTokenRgb("--win-close-hover", "#C42B1C");

  const allowedChromeSizes = [11, 12, 13, 15, 20];
  const allowedChromeWeights = new Set([400, 600]);
  const allEls = Array.from(document.body.querySelectorAll("*"));
  const paper = document.querySelector('[data-testid="paper"]');

  // 10. Horizontal overflow
  const scrollW = document.documentElement.scrollWidth;
  const innerW = window.innerWidth;
  if (scrollW > innerW + 1) {
    add("no_horizontal_overflow", `scrollWidth (${scrollW}) > innerWidth (${innerW})`, document.documentElement);
  }

  // 2. Paper surface & width
  if (opts.checkPaper) {
    if (!paper || !isVisible(paper)) {
      add("paper_surface", "missing visible [data-testid=\"paper\"]", document.body);
    } else {
      const pcs = getComputedStyle(paper);
      if (pcs.backgroundColor !== "rgb(255, 255, 255)") {
        add("paper_surface", `paper background is ${pcs.backgroundColor}, expected rgb(255, 255, 255)`, paper);
      }
      for (const prop of ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"]) {
        if (parseFloat(pcs[prop]) > 0.1) {
          add("border_radius", `paper ${prop} is ${pcs[prop]}, expected 0px`, paper);
        }
      }
      if (/pretendard|rl sans/i.test(pcs.fontFamily)) {
        add("paper_surface", `paper font-family must not use Pretendard: ${pcs.fontFamily}`, paper);
      }
      if (opts.checkPaperWidth && innerW >= 1400) {
        const prect = paper.getBoundingClientRect();
        const ratio = prect.width / innerW;
        if (ratio < 0.545) {
          add("paper_surface", `paper width ${Math.round(prect.width)}px is ${(ratio * 100).toFixed(1)}% of ${innerW}px (< 55%)`, paper);
        }
      }
    }
  }

  // 1. Primary buttons (explicit [data-variant="primary"] AND visual filled-button anti-cheat)
  const explicitPrimaries = Array.from(document.querySelectorAll('[data-variant="primary"]')).filter(isVisible);
  if (explicitPrimaries.length > 1) {
    add("single_primary_button", `found ${explicitPrimaries.length} visible [data-variant="primary"] buttons`, explicitPrimaries[1]);
  }
  const filledButtons = [];
  for (const el of allEls) {
    if (!isVisible(el)) continue;
    const isBtn =
      el.tagName === "BUTTON" ||
      el.getAttribute("role") === "button" ||
      el.hasAttribute("data-variant");
    if (!isBtn) continue;
    if (el.closest("[data-win-close]") || el.closest('[data-testid="paper"]')) continue;
    const cs = getComputedStyle(el);
    const bg = parseRgba(cs.backgroundColor);
    const rect = el.getBoundingClientRect();
    const isExplicitPrimary = el.getAttribute("data-variant") === "primary";
    if (isExplicitPrimary) {
      if (bg && bg.a >= 0.8 && !isNeutral(bg)) {
        add("single_primary_button", `primary button fill must be neutral ink, got ${cs.backgroundColor}`, el);
      }
      filledButtons.push(el);
      continue;
    }
    if (bg && bg.a >= 0.88 && rect.width >= 24 && rect.height >= 20) {
      const parentBg = effectiveBg(el.parentElement);
      const bgDiff = contrastRatio(bg, parentBg);
      const isSaturatedFill = !isNeutral(bg) && (isBlueAccentHue(bg) || isCrimsonHue(bg) || isGreenHue(bg));
      if (bgDiff >= 3.0 || isSaturatedFill) {
        filledButtons.push(el);
        if (isSaturatedFill) {
          add("single_primary_button", `button uses saturated filled background ${cs.backgroundColor} (only ink fill allowed)`, el);
        }
      }
    }
  }
  if (filledButtons.length > 1) {
    add("single_primary_button", `found ${filledButtons.length} visually filled buttons (max 1 per window)`, filledButtons[1]);
  }

  // 3. No visible text matching [0-9a-f]{13,} (including split spans)
  const HEX13_RE = /(?<![0-9a-fA-F])[0-9a-fA-F]{13,}(?![0-9a-fA-F])/;
  const isInExpandedDetails = (el) => {
    if (!opts.allowExpandedDetails) return false;
    return Boolean(el.closest("details[open], [data-details-expanded='true']"));
  };
  const checkedBlocks = new Set();
  for (const el of allEls) {
    if (!isVisible(el) || isInExpandedDetails(el)) continue;
    if (hasDirectText(el)) {
      const direct = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => n.nodeValue || "")
        .join("");
      const m = direct.match(HEX13_RE);
      if (m) {
        add("no_long_hex_hashes", `visible hex string >= 13 chars: ${m[0]}`, el);
      }
    }
    // Check concatenated inline text of leaf block containers to defeat split-span bypass.
    const cs = getComputedStyle(el);
    if (cs.display !== "inline" && el.children.length > 0 && el.children.length <= 8) {
      const allChildrenInline = Array.from(el.children).every((ch) => getComputedStyle(ch).display.startsWith("inline"));
      if (allChildrenInline && !checkedBlocks.has(el)) {
        checkedBlocks.add(el);
        const joined = (el.innerText || "").trim();
        const m = joined.match(HEX13_RE);
        if (m) {
          add("no_long_hex_hashes", `visible concatenated hex string >= 13 chars: ${m[0]}`, el);
        }
      }
    }
  }

  // Main per-element audit (docked shadows, hues, typography, radius, sentences, contrast)
  const checkColorForReservedHues = (el, prop, rgb, isFocusRing) => {
    if (!rgb || rgb.a < 0.05) return;
    const inPaper = Boolean(el.closest('[data-testid="paper"]'));
    const inFact = Boolean(el.closest("[data-fact]"));
    const inWinClose = Boolean(el.closest("[data-win-close]"));
    const inAgent = Boolean(
      el.closest('[data-source="agent"], [data-mark-source="agent"], [data-accent]')
    );

    // Crimson / --fact
    const matchesFact =
      sameRgb(rgb, tokFact, 12) ||
      (rgb.a >= 0.8 && sameRgb(rgb, tokFactTint, 8)) ||
      isCrimsonHue(rgb);
    if (matchesFact && !inFact) {
      if (!(inWinClose && sameRgb(rgb, tokWinClose, 12))) {
        add("reserved_hues", `crimson/--fact color (${rgb.r},${rgb.g},${rgb.b}) on ${prop} outside [data-fact]`, el);
      }
    }

    // Accent / --accent
    const matchesAccent =
      sameRgb(rgb, tokAccent, 12) ||
      (rgb.a >= 0.8 && sameRgb(rgb, tokAccentTint, 8)) ||
      (rgb.a >= 0.8 && sameRgb(rgb, tokAccentLine, 8)) ||
      isBlueAccentHue(rgb);
    if (matchesAccent && !inAgent && !isFocusRing) {
      add("reserved_hues", `accent color (${rgb.r},${rgb.g},${rgb.b}) on ${prop} outside [data-source="agent"]/[data-accent]/focus`, el);
    }

    // No green anywhere in chrome
    if (!inPaper && isGreenHue(rgb)) {
      add("reserved_hues", `green color (${rgb.r},${rgb.g},${rgb.b}) on ${prop} is banned in chrome`, el);
    }
  };

  let minContrast = 999;
  let checkedTextNodes = 0;

  for (const el of allEls) {
    if (!isVisible(el)) continue;
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const inPaper = Boolean(el.closest('[data-testid="paper"]'));
    const inFloating = Boolean(el.closest("[data-floating]"));
    const isDocked = el.hasAttribute("data-docked");
    const insideDocked = Boolean(el.closest("[data-docked]"));

    // 2b. No docked chrome surface is #FFFFFF
    if (isDocked && cs.backgroundColor === "rgb(255, 255, 255)") {
      add("paper_surface", "docked chrome surface must not be #FFFFFF", el);
    }

    // 4. No box-shadow or drop-shadow on [data-docked] (and non-floating chrome descendants)
    if (isDocked || (insideDocked && !inFloating && !inPaper && el !== paper)) {
      if (cs.boxShadow && cs.boxShadow !== "none") {
        add("no_docked_shadow", `unexpected box-shadow on docked element: ${cs.boxShadow}`, el);
      }
      if (cs.filter && /drop-shadow/i.test(cs.filter)) {
        add("no_docked_shadow", `unexpected drop-shadow filter on docked element: ${cs.filter}`, el);
      }
    }

    // 5. Reserved hues on active element properties
    const isFocused = document.activeElement === el;
    checkColorForReservedHues(el, "color", parseRgba(cs.color), false);
    checkColorForReservedHues(el, "backgroundColor", parseRgba(cs.backgroundColor), false);
    for (const side of ["Top", "Right", "Bottom", "Left"]) {
      if (parseFloat(cs[`border${side}Width`]) > 0 && cs[`border${side}Style`] !== "none") {
        checkColorForReservedHues(el, `border${side}Color`, parseRgba(cs[`border${side}Color`]), false);
      }
    }
    if (parseFloat(cs.outlineWidth) > 0 && cs.outlineStyle !== "none") {
      checkColorForReservedHues(el, "outlineColor", parseRgba(cs.outlineColor), isFocused);
    }
    if (cs.textDecorationLine && cs.textDecorationLine !== "none") {
      checkColorForReservedHues(el, "textDecorationColor", parseRgba(cs.textDecorationColor), false);
    }

    // Also inspect ::before and ::after pseudo-elements
    for (const pseudo of ["::before", "::after"]) {
      const pcs = getComputedStyle(el, pseudo);
      if (pcs && pcs.content && pcs.content !== "none" && pcs.content !== "normal") {
        const pw = parseFloat(pcs.width) || 0;
        const ph = parseFloat(pcs.height) || 0;
        if (pw > 0 || ph > 0) {
          checkColorForReservedHues(el, `${pseudo}.backgroundColor`, parseRgba(pcs.backgroundColor), false);
          checkColorForReservedHues(el, `${pseudo}.color`, parseRgba(pcs.color), false);
        }
      }
    }

    // Paper descendants must never render Pretendard (except margin tags / floating mark toolbar)
    if (inPaper && el !== paper && hasDirectText(el)) {
      const isMarginUi = Boolean(el.closest("[data-margin-mark], [data-mark-toolbar]"));
      if (!isMarginUi && /pretendard|rl sans/i.test(cs.fontFamily)) {
        add("paper_surface", `paper text element uses Pretendard: ${cs.fontFamily}`, el);
      }
    }

    // 6. Chrome typography (outside paper)
    if (!inPaper && hasDirectText(el)) {
      const fsize = parseFloat(cs.fontSize);
      const sizeOk = allowedChromeSizes.some((s) => Math.abs(fsize - s) <= 0.15);
      if (!sizeOk) {
        add("chrome_typography", `chrome font-size ${fsize}px not in {11,12,13,15,20}`, el);
      }
      const fweight = Number(cs.fontWeight);
      if (!allowedChromeWeights.has(fweight)) {
        add("chrome_typography", `chrome font-weight ${fweight} not in {400,600}`, el);
      }
    }

    // 7. Border radius <= 6px in chrome
    if (!inPaper) {
      const isTinyDot = rect.width <= 12 && rect.height <= 12;
      for (const prop of ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"]) {
        const rawR = cs[prop] || "0px";
        let pxR = 0;
        if (rawR.endsWith("%")) {
          const pct = parseFloat(rawR) / 100;
          pxR = Math.min(rect.width, rect.height) * pct;
        } else {
          pxR = parseFloat(rawR) || 0;
          if (isTinyDot) {
            pxR = Math.min(pxR, Math.min(rect.width, rect.height) / 2);
          }
        }
        if (pxR > 6.1) {
          add("border_radius", `chrome ${prop} is ${rawR} (${pxR.toFixed(1)}px > 6px)`, el);
          break;
        }
      }
    }

    // 8. No workspace sentences ending in `다.` outside paper, thread, and sheet
    if ((opts.mode === "workspace" || opts.mode === "start") && hasDirectText(el)) {
      const exemptSel =
        opts.mode === "start"
          ? '[data-testid="paper"], [data-testid="agent-thread"], [data-region="thread"], [data-testid="approve-sheet"], [data-region="sheet"], [data-testid="start-boundary"]'
          : '[data-testid="paper"], [data-testid="agent-thread"], [data-region="thread"], [data-testid="approve-sheet"], [data-region="sheet"]';
      if (!el.closest(exemptSel)) {
        const direct = Array.from(el.childNodes)
          .filter((n) => n.nodeType === 3)
          .map((n) => n.nodeValue || "")
          .join("")
          .trim();
        if (/(?:다\.(?:$|\s))/.test(direct)) {
          add("no_workspace_sentences", `declarative sentence ending in '다.' in chrome: ${direct}`, el);
        }
      }
    }

    // 9. WCAG 4.5:1 contrast check on visible enabled text
    if (opts.checkContrast && hasDirectText(el) && !isDisabledEl(el)) {
      const fgRaw = parseRgba(cs.color);
      if (fgRaw && fgRaw.a > 0.05) {
        let bgEff = effectiveBg(el);
        // Account for dark-mode 6% neutral paper veil if present inside paper
        if (inPaper && theme === "dark" && paper && paper.querySelector("[data-paper-veil]")) {
          const veilEl = paper.querySelector("[data-paper-veil]");
          const veilBg = parseRgba(getComputedStyle(veilEl).backgroundColor);
          if (veilBg && veilBg.a > 0.01) {
            bgEff = compositeOver(veilBg, bgEff);
          }
        }
        const fgEff = compositeOver(fgRaw, bgEff);
        const ratio = contrastRatio(fgEff, bgEff);
        checkedTextNodes += 1;
        if (ratio < minContrast) minContrast = ratio;
        if (ratio < 4.49) {
          add(
            "text_contrast",
            `contrast ${ratio.toFixed(2)}:1 < 4.5:1 (fg=${cs.color}, bg=rgb(${bgEff.r},${bgEff.g},${bgEff.b}))`,
            el
          );
        }
      }
    }
  }

  return {
    violations,
    metrics: {
      theme,
      viewportWidth: innerW,
      scrollWidth: scrollW,
      explicitPrimaryCount: explicitPrimaries.length,
      filledButtonCount: filledButtons.length,
      checkedTextNodes,
      minContrast: checkedTextNodes > 0 ? Number(minContrast.toFixed(2)) : null,
      paperBackground: paper ? getComputedStyle(paper).backgroundColor : null,
      paperWidth: paper ? Math.round(paper.getBoundingClientRect().width) : null,
    },
  };
}
"""


def check_ui_principles(
    page: Any,
    *,
    mode: str = "workspace",
    check_paper: bool = True,
    check_paper_width: bool = False,
    check_contrast: bool = True,
    allow_expanded_details: bool = False,
) -> PrincipleReport:
    """Evaluate all editor v2 UI principles on a loaded Playwright `page`."""
    raw = page.evaluate(
        _EVAL_PRINCIPLES_JS,
        {
            "mode": mode,
            "checkPaper": check_paper,
            "checkPaperWidth": check_paper_width,
            "checkContrast": check_contrast,
            "allowExpandedDetails": allow_expanded_details,
        },
    )
    violations = tuple(
        PrincipleViolation(
            rule=str(item["rule"]),
            detail=str(item["detail"]),
            selector=str(item.get("selector", "")),
        )
        for item in raw.get("violations", [])
    )
    return PrincipleReport(violations=violations, metrics=dict(raw.get("metrics") or {}))


def assert_ui_principles(page: Any, **kwargs: Any) -> PrincipleReport:
    """Assert zero principle violations on `page` and return the report."""
    report = check_ui_principles(page, **kwargs)
    assert report.ok, f"UI principle violations ({len(report.violations)}):\n{report.summary()}"
    return report


# ---------------------------------------------------------------------------
# J1 §4 Compliant Reference Harness HTML (used by self-tests & WPS screenshots)
# ---------------------------------------------------------------------------

def build_reference_workspace_html(
    *,
    theme: str = "light",
    viewport_width: int = 1440,
    extra_style: str = "",
    extra_body: str = "",
    paper_style: str = "",
    title_text: str = "기안문(별지 제1호서식) — Rigorloom",
    doc_stem: str = "기안문(별지 제1호서식)",
    doc_ext: str = ".hwpx",
    timestamp_text: str = "11월 19일 오후 2:31",
    short_time_text: str = "오후 2:13",
    export_sample: str = "기안문(별지 제1호서식)_수정본1.hwpx",
) -> str:
    """Build a J1 §1 + §4 compliant reference workspace DOM for principle & visual checks."""
    font_css = ""
    if PRETENDARD_FONT.is_file():
        font_css += (
            f'@font-face{{font-family:"Pretendard Variable";'
            f'src:url("file://{PRETENDARD_FONT}") format("woff2-variations");'
            f'font-weight:100 900;font-display:block;}}\n'
        )
    if NANUM_FONT.is_file():
        font_css += (
            f'@font-face{{font-family:"Nanum Myeongjo";'
            f'src:url("file://{NANUM_FONT}") format("truetype");'
            f'font-weight:400;font-display:block;}}\n'
        )

    is_narrow = viewport_width < 600
    show_left = viewport_width >= 1360

    return f"""<!doctype html>
<html lang="ko" data-theme="{theme}">
<head>
<meta charset="utf-8">
<title>{title_text}</title>
<style>
{font_css}
:root {{
  --font-sans: "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Malgun Gothic", system-ui, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, "Cascadia Mono", monospace;
  --text-xs: 11px; --lh-xs: 14px;
  --text-sm: 12px; --lh-sm: 16px;
  --text-base: 13px; --lh-base: 18px;
  --text-lg: 15px; --lh-lg: 22px;
  --text-display: 20px; --lh-display: 28px;
  --weight-regular: 400; --weight-semibold: 600;
  --font-page-serif: "Nanum Myeongjo", "Noto Serif CJK KR", Batang, serif;
  --radius-0: 0; --radius-sm: 4px; --radius-md: 6px;
  --paper: #FFFFFF; --paper-ink: #111111; --seat: #F5F2E8;
  --mark-insert: #2A48A4; --mark-insert-tint: rgba(42, 72, 164, .10);
  --mark-delete: #2A48A4; --mark-delete-text: #66696F;
  --mark-accepted: #1B1B1A;
  --mark-fact: #B4232A; --mark-fact-tint: rgba(180, 35, 42, .10);
  --win-close-hover: #C42B1C;
}}
:root, :root[data-theme="light"] {{
  --desk: #DEDCD5; --chrome: #ECEBE7; --panel: #F4F3F0; --field: #FBFBF9; --raised: #FFFFFF;
  --ink: #1B1B1A; --on-ink: #FFFFFF;
  --text-2: #45443F; --text-3: #605E58; --text-disabled: #A3A099;
  --line: #E0DED8; --line-strong: #CCC9C1; --line-control: #86847D;
  --hover: rgba(27, 27, 26, .05); --selected: rgba(27, 27, 26, .08);
  --accent: #2A48A4; --accent-tint: #E7EBF6; --accent-line: #BFC9E8;
  --focus: var(--accent);
  --fact: #B4232A; --fact-tint: #FBE9E9;
  --attn: #7A4F00; --attn-tint: #FAF0DC; --attn-line: #B8860B;
  --expected: #45443F; --expected-tint: #E8E7E2;
  --paper-veil: transparent;
  --shadow-paper: 0 0 0 1px rgba(27, 27, 26, .08), 0 1px 2px rgba(27, 27, 26, .06), 0 8px 24px rgba(27, 27, 26, .08);
  --shadow-float: 0 0 0 1px rgba(27, 27, 26, .06), 0 8px 28px rgba(27, 27, 26, .14);
}}
:root[data-theme="dark"] {{
  --desk: #0B0C0D; --chrome: #0F1012; --panel: #141518; --field: #1B1C20; --raised: #222327;
  --ink: #ECEBE7; --on-ink: #141518;
  --text-2: #C2C0BA; --text-3: #96948E; --text-disabled: #5F5D58;
  --line: #26272B; --line-strong: #36373D; --line-control: #74757C;
  --hover: rgba(236, 235, 231, .06); --selected: rgba(236, 235, 231, .10);
  --accent: #9FB4F0; --accent-tint: #1A2340; --accent-line: #33457A;
  --focus: var(--accent);
  --fact: #F0787C; --fact-tint: #3A1719;
  --attn: #E8B867; --attn-tint: #2E240F; --attn-line: #B98A1E;
  --expected: #C2C0BA; --expected-tint: #2A2B30;
  --paper-veil: rgba(0, 0, 0, .06);
  --shadow-paper: 0 0 0 1px rgba(255, 255, 255, .06);
  --shadow-float: 0 0 0 1px rgba(255, 255, 255, .08), 0 16px 40px rgba(0, 0, 0, .55);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: 100%; height: 100%; background: var(--chrome); color: var(--ink); font-family: var(--font-sans); font-size: var(--text-base); font-weight: var(--weight-regular); line-height: 1.4; overflow-x: hidden; }}
button {{ font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }}
.shell {{ width: 100%; height: 100vh; display: grid; grid-template-rows: {"48px 1fr 164px" if is_narrow else "36px 1fr 24px"}; overflow: hidden; }}
.titlebar {{ display: flex; align-items: center; gap: 8px; padding: 0 12px; background: var(--chrome); border-bottom: 1px solid var(--line); }}
.brand-word {{ font-size: var(--text-base); font-weight: var(--weight-semibold); color: var(--ink); }}
.tab {{ height: 28px; display: inline-flex; align-items: center; gap: 6px; padding: 0 10px; border-radius: var(--radius-md) var(--radius-md) 0 0; background: var(--panel); border: 1px solid var(--line); border-bottom: 0; font-size: var(--text-sm); font-weight: var(--weight-semibold); color: var(--ink); white-space: nowrap; }}
.tab-name {{ display: inline-flex; align-items: baseline; }}
.tab .ext {{ font-weight: var(--weight-regular); color: var(--text-3); font-family: var(--font-mono); }}
.pill {{ display: inline-flex; align-items: center; height: 18px; padding: 0 6px; border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: var(--weight-semibold); color: var(--accent); background: var(--accent-tint); font-variant-numeric: tabular-nums; }}
.cmd-field {{ margin-left: auto; height: 26px; padding: 0 8px; display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: var(--field); color: var(--text-3); font-size: var(--text-sm); }}
.kbd {{ display: inline-flex; align-items: center; padding: 0 4px; height: 18px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); font-size: var(--text-xs); color: var(--text-2); background: var(--panel); }}
.workspace {{ display: grid; grid-template-columns: {"1fr" if is_narrow else ("240px 1fr 360px" if show_left else "1fr 340px")}; min-height: 0; overflow: hidden; }}
.left-pane, .right-pane {{ background: var(--panel); display: flex; flex-direction: column; min-height: 0; overflow: hidden; }}
.left-pane {{ border-right: 1px solid var(--line); }}
.right-pane {{ border-left: 1px solid var(--line); }}
.tab-row {{ height: 32px; display: flex; align-items: stretch; gap: 12px; padding: 0 12px; border-bottom: 1px solid var(--line); }}
.tab-btn {{ font-size: var(--text-sm); font-weight: var(--weight-regular); color: var(--text-3); border-bottom: 2px solid transparent; display: inline-flex; align-items: center; gap: 4px; }}
.tab-btn.active {{ font-weight: var(--weight-semibold); color: var(--ink); border-bottom-color: var(--ink); }}
.pane-body {{ flex: 1; padding: 8px 10px; overflow: hidden; display: flex; flex-direction: column; gap: 4px; }}
.row-item {{ min-height: 28px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 8px; border-radius: var(--radius-sm); font-size: var(--text-sm); color: var(--text-2); }}
.row-item > span:first-child {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }}
.row-item > span:last-child {{ flex-shrink: 0; white-space: nowrap; color: var(--text-3); font-variant-numeric: tabular-nums; }}
.row-item.selected {{ background: var(--selected); color: var(--ink); font-weight: var(--weight-semibold); }}
.row-item.selected > span:last-child {{ color: var(--text-2); font-weight: var(--weight-regular); }}
.center-col {{ display: grid; grid-template-rows: 32px 1fr; min-width: 0; min-height: 0; }}
.doc-strip {{ display: flex; align-items: center; gap: 10px; padding: 0 12px; background: var(--panel); border-bottom: 1px solid var(--line); font-size: var(--text-sm); }}
.strip-grade {{ color: var(--text-3); }}
.seg-flat {{ display: inline-flex; gap: 2px; margin-left: auto; }}
.seg-flat button {{ height: 24px; padding: 0 8px; border-radius: var(--radius-sm); font-size: var(--text-sm); color: var(--text-2); }}
.seg-flat button.on {{ background: var(--field); border: 1px solid var(--line-strong); color: var(--ink); font-weight: var(--weight-semibold); }}
.btn-outline {{ height: 28px; padding: 0 10px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: var(--field); color: var(--ink); font-size: var(--text-sm); display: inline-flex; align-items: center; gap: 6px; }}
.btn-primary {{ height: 32px; padding: 0 14px; border-radius: var(--radius-sm); background: var(--ink); color: var(--on-ink); font-size: var(--text-sm); font-weight: var(--weight-semibold); display: inline-flex; align-items: center; gap: 6px; }}
.desk {{ background: var(--desk); padding: {"12px" if is_narrow else "20px 24px"}; display: flex; justify-content: center; align-items: flex-start; overflow: hidden; }}
.paper {{ position: relative; width: {"100%" if is_narrow else "792px"}; max-width: 792px; min-height: {"580px" if is_narrow else "760px"}; background: var(--paper); color: var(--paper-ink); font-family: var(--font-page-serif); font-size: 13px; line-height: 1.65; padding: {"20px 18px" if is_narrow else "40px 52px"}; border-radius: var(--radius-0); box-shadow: var(--shadow-paper); }}
.paper-veil {{ position: absolute; inset: 0; background: var(--paper-veil); pointer-events: none; }}
.paper-title {{ text-align: center; font-size: 18px; font-weight: 700; margin-bottom: 16px; }}
.form-tbl {{ width: 100%; border-collapse: collapse; border: 1px solid var(--paper-ink); }}
.form-tbl td {{ border: 1px solid var(--paper-ink); padding: 6px 10px; vertical-align: top; }}
.form-tbl td:first-child {{ white-space: nowrap; width: 1%; }}
.blank-seat {{ background: var(--seat); }}
.ins-mark {{ color: var(--paper-ink); background: var(--mark-insert-tint); border-bottom: 1px solid var(--mark-insert); }}
.del-mark {{ color: var(--mark-delete-text); text-decoration: line-through; text-decoration-color: var(--mark-delete); }}
.margin-num {{ position: absolute; left: 14px; font-family: var(--font-sans); font-size: var(--text-xs); font-weight: var(--weight-semibold); color: var(--mark-insert); font-variant-numeric: tabular-nums; }}
.change-row {{ padding: 8px 10px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 4px; }}
.change-row.selected {{ background: var(--selected); border-left: 2px solid var(--accent); }}
.row-head {{ display: flex; align-items: center; justify-content: space-between; font-size: var(--text-sm); }}
.row-title {{ font-weight: var(--weight-semibold); color: var(--ink); }}
.row-meta {{ color: var(--text-3); font-size: var(--text-sm); }}
.diff-line {{ background: var(--field); padding: 4px 8px; border-radius: var(--radius-sm); font-size: var(--text-sm); color: var(--text-2); }}
.approval-box {{ display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line-strong); border-radius: var(--radius-0); margin-bottom: 8px; }}
.approval-cell {{ border-right: 1px solid var(--line-strong); }}
.approval-cell:last-child {{ border-right: 0; }}
.approval-hd {{ height: 20px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid var(--line-strong); font-size: var(--text-sm); color: var(--text-3); white-space: nowrap; }}
.approval-bd {{ height: 36px; display: flex; align-items: center; justify-content: center; padding: 0 4px; font-size: var(--text-sm); color: var(--ink); white-space: nowrap; font-variant-numeric: tabular-nums; }}
.panel-foot {{ padding: 10px 12px; border-top: 1px solid var(--line); background: var(--panel); }}
.foot-actions {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.composer {{ padding: 8px 12px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 8px; }}
.composer-input {{ flex: 1; height: 28px; padding: 0 8px; border: 1px solid var(--line-control); border-radius: var(--radius-sm); background: var(--field); color: var(--ink); font-size: var(--text-sm); }}
.statusbar {{ display: flex; align-items: center; justify-content: space-between; padding: 0 12px; background: var(--chrome); border-top: 1px solid var(--line); font-size: var(--text-sm); color: var(--text-3); }}
.narrow-sheet {{ background: var(--panel); border-top: 1px solid var(--line); padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; }}
.narrow-actions {{ display: flex; align-items: center; gap: 8px; }}
.narrow-actions button {{ min-height: 44px; flex: 1; justify-content: center; }}
{extra_style}
</style>
</head>
<body>
<div class="shell">
  <header class="titlebar" data-docked>
    <span class="brand-word">Rigorloom</span>
    <div class="tab" data-testid="tab-active">
      <span class="tab-name">{doc_stem}<span class="ext">{doc_ext}</span></span>
      <span class="pill" data-accent>24</span>
    </div>
    {"" if is_narrow else '<div class="cmd-field"><span>명령, 문서, 빈칸 찾기</span><span class="kbd">Ctrl</span><span class="kbd">K</span></div>'}
  </header>
  <div class="workspace">
    {f'''<aside class="left-pane" data-docked>
      <div class="tab-row">
        <button class="tab-btn active">파일</button>
        <button class="tab-btn">개요</button>
        <button class="tab-btn">빈칸</button>
        <button class="tab-btn">찾기</button>
        <button class="tab-btn">기록</button>
      </div>
      <div class="pane-body">
        <div class="row-item selected"><span>{doc_stem}{doc_ext}</span><span>수정본 1</span></div>
        <div class="row-item"><span>협조요청_개요.md</span><span>{timestamp_text}</span></div>
        <div class="row-item"><span>{export_sample}</span><span>HWPX</span></div>
      </div>
    </aside>''' if show_left else ""}
    <main class="center-col">
      <div class="doc-strip" data-testid="doc-strip" data-docked>
        <span>원본 + 변경 24건</span>
        <span class="strip-grade">{"미리보기" if is_narrow else "미리보기 · 인쇄 결과와 다를 수 있습니다"}</span>
        {"" if is_narrow else '<div class="seg-flat"><button class="on">변경 표시</button><button>표시 없이</button><button>원본</button></div><button class="btn-outline">내보내기</button>'}
      </div>
      <div class="desk">
        <article class="paper" data-testid="paper" style="{paper_style}">
          <div class="paper-veil" data-paper-veil></div>
          <span class="margin-num" data-margin-mark data-source="agent">8</span>
          <h1 class="paper-title">기 안 문</h1>
          <table class="form-tbl">
            <tr>
              <td>행정기관명</td>
              <td><span class="del-mark" data-source="agent">행정기관명</span> <span class="ins-mark" data-source="agent">가온공공기록원</span></td>
            </tr>
            <tr>
              <td>수신</td>
              <td><span class="ins-mark" data-source="agent">협조기관장(기록관리과장)</span></td>
            </tr>
            <tr>
              <td>접수</td>
              <td class="blank-seat"></td>
            </tr>
            <tr>
              <td>본문</td>
              <td>귀 기관은 소관 기록물을 점검하고 결과를 회신하여 주시기 바랍니다.</td>
            </tr>
          </table>
        </article>
      </div>
    </main>
    {"" if is_narrow else f'''<aside class="right-pane" data-docked>
      <div class="tab-row">
        <button class="tab-btn active">변경 24</button>
        <button class="tab-btn">에이전트</button>
        <button class="tab-btn">점검 1</button>
      </div>
      <div class="pane-body">
        <div class="row-item" data-region="thread"><span>에이전트 · {short_time_text} · 변경 24건 제안</span><span>7f3a9c2e51b0</span></div>
        <div class="change-row" data-testid="change-row-5">
          <div class="row-head"><span class="row-title">5 행정기관명 · 빈칸 채움 · 에이전트</span><span class="row-meta">받아들임</span></div>
        </div>
        <div class="change-row selected" data-testid="change-row-8" data-source="agent">
          <div class="row-head"><span class="row-title">8 본문 · 빈칸 채움 · 에이전트</span><span class="row-meta">남음</span></div>
          <div class="diff-line">변경 전 · 본문</div>
          <div class="diff-line">변경 후 · 1. 관련: 기록정책과-88(2026. 10. 30.)</div>
          <div style="display:flex;gap:6px;margin-top:4px;">
            <button class="btn-outline">받아들이기 <span class="kbd">Y</span></button>
            <button class="btn-outline">빼기 <span class="kbd">N</span></button>
            <button class="btn-outline">고치기 <span class="kbd">E</span></button>
          </div>
        </div>
      </div>
      <div class="panel-foot">
        <div class="approval-box">
          <div class="approval-cell"><div class="approval-hd">제안</div><div class="approval-bd">에이전트 · 24건</div></div>
          <div class="approval-cell"><div class="approval-hd">점검</div><div class="approval-bd">확인 1</div></div>
          <div class="approval-cell"><div class="approval-hd">승인</div><div class="approval-bd"></div></div>
        </div>
        <div class="foot-actions">
          <button class="btn-outline" data-testid="return">돌려보내기 <span class="kbd">R</span></button>
          <button class="btn-primary" data-testid="approve" data-variant="primary">승인</button>
        </div>
      </div>
      <div class="composer" data-testid="composer">
        <input class="composer-input" type="text" placeholder="요청할 작업 입력" aria-label="요청할 작업 입력" />
        <button class="btn-outline">요청 보내기</button>
      </div>
    </aside>'''}
  </div>
  {'''<section class="narrow-sheet" data-docked>
    <div class="row-head"><span class="row-title">24 비고 · 안내문 지움 · 에이전트</span><span class="row-meta">24 / 24 · 남음 0</span></div>
    <div class="diff-line">변경 후 · 안내문 지움</div>
    <div class="narrow-actions">
      <button class="btn-outline">빼기</button>
      <button class="btn-outline">받아들이기</button>
      <button class="btn-primary" data-testid="approve" data-variant="primary">승인 · 24건</button>
    </div>
  </section>''' if is_narrow else f'''<footer class="statusbar" data-docked>
    <span>1 / 2쪽 · 수신 · 1쪽 · 표 1 2행 3열 · 글자 1,046</span>
    <span>확인 1 · 에이전트 연결됨 · 엔진 준비됨 · 저장됨 · 100%</span>
  </footer>'''}
</div>
{extra_body}
</body>
</html>"""


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        no_browser(f"playwright unavailable: {exc}")
    return sync_playwright


@pytest.fixture(scope="module")
def browser_instance():
    sync_playwright = _import_playwright()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover
            no_browser(f"headless Chromium unavailable: {exc}")
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize(
    "width,height,theme",
    [
        (1440, 900, "light"),
        (1440, 900, "dark"),
        (1280, 800, "light"),
        (1280, 800, "dark"),
        (390, 844, "light"),
        (390, 844, "dark"),
    ],
)
def test_compliant_reference_passes_all_principles_across_viewports_and_themes(
    browser_instance, width: int, height: int, theme: str
) -> None:
    page = browser_instance.new_page(viewport={"width": width, "height": height})
    try:
        html = build_reference_workspace_html(theme=theme, viewport_width=width)
        page.set_content(html, wait_until="domcontentloaded")
        report = assert_ui_principles(
            page,
            mode="workspace",
            check_paper=True,
            check_paper_width=(width >= 1440),
            check_contrast=True,
        )
        assert report.metrics["paperBackground"] == "rgb(255, 255, 255)"
        assert report.metrics["minContrast"] is not None and report.metrics["minContrast"] >= 4.5
    finally:
        page.close()


@pytest.mark.parametrize(
    "case_name,expected_rule,kwargs",
    [
        (
            "two_explicit_primary_buttons",
            "single_primary_button",
            {"extra_body": '<button class="btn-primary" data-variant="primary" style="position:fixed;top:8px;left:300px;">둘째</button>'},
        ),
        (
            "sneaky_unlabelled_second_filled_button",
            "single_primary_button",
            {"extra_body": '<button style="position:fixed;top:8px;left:300px;height:32px;padding:0 12px;background:#1B1B1A;color:#FFFFFF;border-radius:4px;">숨긴 강조</button>'},
        ),
        (
            "indigo_primary_button",
            "single_primary_button",
            {"extra_style": ".btn-primary{background:#2A48A4!important;color:#FFFFFF!important;}"},
        ),
        (
            "dark_paper_background",
            "paper_surface",
            {"theme": "dark", "paper_style": "background:#1E1E1C!important;"},
        ),
        (
            "cream_paper_background",
            "paper_surface",
            {"paper_style": "background:#FCFBF8!important;"},
        ),
        (
            "rounded_paper_corners",
            "border_radius",
            {"paper_style": "border-radius:4px!important;"},
        ),
        (
            "pretendard_on_paper",
            "paper_surface",
            {"paper_style": "font-family:'Pretendard Variable',sans-serif!important;"},
        ),
        (
            "white_docked_chrome",
            "paper_surface",
            {"extra_style": ".left-pane{background:#FFFFFF!important;}"},
        ),
        (
            "visible_13_char_hex_hash",
            "no_long_hex_hashes",
            {"extra_body": '<div style="position:fixed;bottom:32px;left:16px;font-size:12px;">7f3a9c2e51b0f</div>'},
        ),
        (
            "sneaky_split_span_hex_hash",
            "no_long_hex_hashes",
            {"extra_body": '<div style="position:fixed;bottom:32px;left:16px;font-size:12px;"><span>7f3a9c2e</span><span>51b0dead</span></div>'},
        ),
        (
            "docked_box_shadow",
            "no_docked_shadow",
            {"extra_style": ".right-pane{box-shadow:0 2px 8px rgba(0,0,0,.15)!important;}"},
        ),
        (
            "sneaky_docked_drop_shadow_filter",
            "no_docked_shadow",
            {"extra_style": ".left-pane{filter:drop-shadow(0 2px 6px rgba(0,0,0,.2))!important;}"},
        ),
        (
            "crimson_outside_data_fact",
            "reserved_hues",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;color:#B4232A;font-size:12px;">빨간 경고</span>'},
        ),
        (
            "hardcoded_red_strike_outside_data_fact",
            "reserved_hues",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;text-decoration:line-through;text-decoration-color:#C0392B;font-size:12px;">지운 글</span>'},
        ),
        (
            "accent_outside_allowed_attributes",
            "reserved_hues",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;color:#2A48A4;font-size:12px;">무단 강조</span>'},
        ),
        (
            "green_status_dot_in_chrome",
            "reserved_hues",
            {"extra_body": '<span style="position:fixed;bottom:6px;left:300px;width:8px;height:8px;background:#3F8F5F;border-radius:4px;"></span>'},
        ),
        (
            "disallowed_chrome_font_size_12_5",
            "chrome_typography",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;font-size:12.5px;">잘못된 크기</span>'},
        ),
        (
            "disallowed_chrome_font_weight_500",
            "chrome_typography",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;font-size:13px;font-weight:500;">중간 두께</span>'},
        ),
        (
            "pill_radius_over_6px",
            "border_radius",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;padding:2px 8px;border:1px solid #CCC9C1;border-radius:9px;font-size:12px;">알약</span>'},
        ),
        (
            "workspace_chrome_sentence_ending_in_da_dot",
            "no_workspace_sentences",
            {"extra_body": '<div style="position:fixed;top:40px;left:300px;font-size:12px;">숫자와 날짜만 점검합니다. </div>'},
        ),
        (
            "low_contrast_text_in_chrome",
            "text_contrast",
            {"extra_body": '<span style="position:fixed;top:40px;left:300px;color:#A3A099;background:#F4F3F0;font-size:12px;">흐린 글자</span>'},
        ),
        (
            "horizontal_overflow_at_390",
            "no_horizontal_overflow",
            {"viewport_width": 390, "extra_body": '<div style="position:absolute;top:0;left:0;width:520px;height:10px;"></div>'},
        ),
    ],
)
def test_principle_harness_catches_every_violation_and_anti_cheat_bypass(
    browser_instance, case_name: str, expected_rule: str, kwargs: dict[str, Any]
) -> None:
    vw = int(kwargs.get("viewport_width", 1440))
    vh = 844 if vw < 600 else 900
    page = browser_instance.new_page(viewport={"width": vw, "height": vh})
    try:
        html = build_reference_workspace_html(**kwargs)
        page.set_content(html, wait_until="domcontentloaded")
        report = check_ui_principles(page, mode="workspace", check_paper=True, check_contrast=True)
        assert not report.ok, f"Case {case_name!r} unexpectedly passed all principles"
        assert expected_rule in report.rules(), (
            f"Case {case_name!r}: expected rule {expected_rule!r}, got {report.rules()}:\n{report.summary()}"
        )
    finally:
        page.close()


def test_principle_harness_allows_fact_crimson_and_expanded_details_hash(browser_instance) -> None:
    """Confirm legitimate `[data-fact]` crimson and expanded `자세히` full hash are permitted."""
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    try:
        extra = (
            '<div data-fact style="position:fixed;top:44px;left:300px;padding:4px 8px;'
            'background:var(--fact-tint);border-left:2px solid var(--fact);color:var(--fact);'
            'font-size:12px;border-radius:4px;">바뀐 사실 1건</div>'
            '<details open style="position:fixed;top:80px;left:300px;font-size:12px;">'
            '<summary>자세히</summary>'
            '<code>7f3a9c2e51b0deadbeef0123456789abcdef</code>'
            '</details>'
        )
        page.set_content(build_reference_workspace_html(extra_body=extra), wait_until="load")
        # With allow_expanded_details=False (default workspace), full hash fails
        r_strict = check_ui_principles(page, mode="workspace", allow_expanded_details=False)
        assert "no_long_hex_hashes" in r_strict.rules()
        # With allow_expanded_details=True (explicit 자세히 check), both pass cleanly
        assert_ui_principles(page, mode="workspace", allow_expanded_details=True)
    finally:
        page.close()


def test_principle_harness_flags_documented_base_mockup_defects(browser_instance) -> None:
    """Run the harness against the raw base mockup HTML and confirm it catches J1 §1 defects."""
    if not BASE_MOCKUP_WORKSPACE.is_file():
        pytest.skip("base mockup HTML not present (set RL_BASE_MOCKUP_HTML)")
    page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(BASE_MOCKUP_WORKSPACE.as_uri(), wait_until="load")
        report = check_ui_principles(page, mode="workspace", check_paper=False, check_contrast=True)
        rules = report.rules()
        # The base mockup has documented J1 §1 defects: indigo primary button, red strike & green dot,
        # 12.5px / weight 500 typography, 9px pill radius, low-contrast --ink-4, guard sentence.
        for expected in (
            "single_primary_button",
            "reserved_hues",
            "chrome_typography",
            "border_radius",
            "no_workspace_sentences",
            "text_contrast",
        ):
            assert expected in rules, (
                f"Expected harness to catch base mockup defect {expected!r}, found rules={rules}"
            )
    finally:
        page.close()
