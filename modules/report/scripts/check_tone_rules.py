# -*- coding: utf-8 -*-
"""H4 tone-rulepack regression check on bundle/content.md prose.

Variant-audit outcome (docs/research/variant-audit.md, "Humanization
measurement" row): the corpus rulepack's rules provably track real humanizer
edits — bench 2b caught the humanizer removing a "따라서" conclusion pivot
(conclusion_pivot 1→0) while the score-based detector read 0.1→0.1 on the
same 25%-changed section. This checker makes the rulepack a mechanism: a
deterministic, pack-driven pre/post regression check over content.md.

Pack boundary (IMPORTANT): this repository ships only the tiny NEUTRAL
default pack (references/preference_packs/defaults/tone_rules.json). The
corpus-derived rulepack — the A-1/A-4 hedge classes and any operator-taste
rules calibrated on the private award corpus — is a profile/report-module
pack INSTANCE: register it with `personalization_ctl.py register-pack --type
tone_rules` into the private profile root, never into repository-tracked
files. This module defines the mechanism and schema only.

Pack schema (report-pipeline/preference-pack/tone_rules-v1; the canonical
schema file is references/preference_packs/tone_rules.schema.json; JSON or
the documented YAML subset accepted by personalization_ctl.load_pack_file):

    {
      "schema": "report-pipeline/preference-pack/tone_rules-v1",
      "pack_type": "tone_rules",
      "name": "<pack name>",
      "version": <int>,
      "rules": [
        {
          "id": "<unique rule id>",
          "kind": "hedge_on_measured_value" | "conclusion_pivot_density",
          "patterns": ["<regex>", ...],      # optional; overrides built-ins
          "scope": "body" | "<section>",     # optional; default "body"
          "severity": "warn" | "hard",       # optional; default "warn"
          "params": {"warn_per_10k": <num>}  # optional; density kinds only
        }, ...
      ]
    }

Built-in rule kinds:
  hedge_on_measured_value   hedge markers (것으로 보인다 / 일 수 있다 /
                            추정된다 / 생각된다 / 볼 수 있다 / 아마) in a
                            sentence that also carries an Arabic numeral —
                            softening a measured result. One finding per
                            flagged sentence.
  conclusion_pivot_density  density of 따라서/그러므로 sentence-starts per
                            10k unicode chars of scoped prose. One finding
                            when density >= warn_per_10k (default 2.0). The
                            measured density is always reported in the
                            verdict metrics so pre/post regression diffs work
                            even below threshold.

Scope: "body" (default) checks all prose; any other value checks only text
under headings classified into that section (motivation / theory / method /
results / conclusion — the same keyword classes stage 4 uses). Build tags
([[...]]) are stripped before matching, mirroring check_style.

Findings are WARN by default — the checker is a regression instrument, not a
blocker. A pack may escalate a rule to "hard" (exit 3) where the operator has
calibrated it.

Exit 0 = pass (WARN allowed), 2 = usage/input error, 3 = HARD finding(s).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Module-script import mechanism (see modules/README.md): sibling scripts via
# the module scripts dir, core helpers via the core pipeline/scripts dir.
SCRIPTS_DIR = Path(__file__).resolve().parent
CORE_SCRIPTS_DIR = SCRIPTS_DIR.parents[2] / "pipeline" / "scripts"
for _dir in (CORE_SCRIPTS_DIR, SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
import personalization_ctl  # noqa: E402  (stdlib-only sibling module)
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)


CHECKER = "check_tone_rules"
PACK_TYPE = "tone_rules"
# tone_rules is a report-module pack type (v0.16 W4.1 split); its public
# default ships as module payload, so the default path is module-relative.
DEFAULT_TONE_PACK = (
    SCRIPTS_DIR.parent / "references" / "preference_packs" / "defaults"
    / "tone_rules.json"
)

RULE_KINDS = ("hedge_on_measured_value", "conclusion_pivot_density")

# Built-in hedge markers: the bench A-1/A-4 class — softening language
# attached to a value that was actually measured.
DEFAULT_HEDGE_PATTERNS = (
    "것으로 보인다",
    "일 수 있다",
    "추정된다",
    "생각된다",
    "볼 수 있다",
    "아마",
)
# Built-in conclusion pivots: the humanizer provably removes these
# (bench 2b, conclusion_pivot 1→0).
DEFAULT_PIVOT_PATTERNS = ("따라서", "그러므로")
DEFAULT_PIVOT_WARN_PER_10K = 2.0

# Any Arabic numeral marks a sentence as carrying a measured/stated value.
# Deliberately broad (years and counts included): the default severity is
# WARN and the instrument favors recall for regression diffing.
NUMERAL_RE = re.compile(r"[0-9]")
TAG_RE = re.compile(r"\[\[.*?\]\]", re.S)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")

# Same heading-keyword classes as stage 4's paragraph labeler.
SECTION_GROUPS = {
    "motivation": ("동기", "목적", "서론", "introduction", "motivation"),
    "theory": ("이론", "배경", "원리", "theory", "background"),
    "method": ("방법", "과정", "절차", "method", "procedure"),
    "results": ("결과", "분석", "내용", "result", "analysis"),
    "conclusion": ("결론", "느낀", "한계", "conclusion", "limitation"),
}

def _section_name(heading: str) -> str:
    lowered = heading.lower()
    for name, needles in SECTION_GROUPS.items():
        if any(needle in lowered for needle in needles):
            return name
    return "body"


def _scoped_text(text: str, scope: str) -> str:
    """Return the prose a rule may see: everything for "body", otherwise only
    lines under headings classified into the named section."""
    if scope == "body":
        return text
    kept: list[str] = []
    current = "body"
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current = _section_name(heading.group(1))
            continue
        if current == scope:
            kept.append(line)
    return "\n".join(kept)


def _sentences(text: str) -> list[str]:
    pieces: list[str] = []
    for block in text.split("\n\n"):
        flattened = " ".join(
            line.strip() for line in block.splitlines() if line.strip()
        )
        if not flattened or HEADING_RE.match(block.strip()):
            continue
        for sentence in SENTENCE_SPLIT_RE.split(flattened):
            sentence = sentence.strip()
            if sentence:
                pieces.append(sentence)
    return pieces


def _compile_patterns(raw: list[str], rule_id: str) -> list[re.Pattern] | str:
    """Compile a pattern list; return an error string on the first bad regex."""
    compiled = []
    for pattern in raw:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            return f"rule {rule_id!r}: invalid pattern {pattern!r}: {exc}"
    return compiled


def _truncate(sentence: str, limit: int = 80) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 1] + "…"


def _run_hedge_rule(rule: dict, scoped: str) -> tuple[list[dict], dict]:
    patterns = _compile_patterns(
        list(rule.get("patterns") or DEFAULT_HEDGE_PATTERNS), rule["id"]
    )
    if isinstance(patterns, str):
        raise ValueError(patterns)
    findings = []
    flagged = 0
    for sentence in _sentences(scoped):
        if not NUMERAL_RE.search(sentence):
            continue
        hit = next(
            (p.pattern for p in patterns if p.search(sentence)), None
        )
        if hit is None:
            continue
        flagged += 1
        findings.append({
            "code": f"tone:{rule['id']}",
            "msg": (
                f"hedge marker {hit!r} in a sentence carrying a measured "
                "numeral — softened measured value (A-1/A-4 class)"
            ),
            "at": _truncate(sentence),
        })
    metrics = {"kind": rule["kind"], "flagged_sentences": flagged}
    return findings, metrics


def _run_pivot_rule(rule: dict, scoped: str) -> tuple[list[dict], dict]:
    patterns = _compile_patterns(
        list(rule.get("patterns") or DEFAULT_PIVOT_PATTERNS), rule["id"]
    )
    if isinstance(patterns, str):
        raise ValueError(patterns)
    params = rule.get("params") or {}
    threshold = params.get("warn_per_10k", DEFAULT_PIVOT_WARN_PER_10K)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) \
            or threshold <= 0:
        raise ValueError(
            f"rule {rule['id']!r}: params.warn_per_10k must be a positive number"
        )
    sentences = _sentences(scoped)
    starts = sum(
        1 for sentence in sentences
        if any(p.match(sentence) for p in patterns)
    )
    chars = len("".join(sentences))
    density = (starts * 10000.0 / chars) if chars else 0.0
    findings = []
    if chars and density >= threshold:
        findings.append({
            "code": f"tone:{rule['id']}",
            "msg": (
                f"conclusion-pivot sentence-start density {density:.2f}/10k "
                f"chars >= {threshold:.2f} — pivot inflation (the humanizer "
                "provably removes these)"
            ),
            "at": f"{starts} pivot starts / {chars} chars",
        })
    metrics = {
        "kind": rule["kind"],
        "pivot_starts": starts,
        "chars": chars,
        "density_per_10k": round(density, 3),
        "warn_per_10k": threshold,
    }
    return findings, metrics


_RULE_RUNNERS = {
    "hedge_on_measured_value": _run_hedge_rule,
    "conclusion_pivot_density": _run_pivot_rule,
}


def _load_pack(pack: dict | str | Path | None) -> dict | str:
    """Return the pack dict, or an error string for the usage verdict."""
    if isinstance(pack, dict):
        candidate = pack
        origin = "<inline>"
    else:
        path = Path(pack) if pack else DEFAULT_TONE_PACK
        origin = str(path)
        try:
            candidate = personalization_ctl.load_pack_file(path)
        except FileNotFoundError:
            return f"tone rulepack not found: {origin}"
        except (OSError, UnicodeError, ValueError) as exc:
            return f"tone rulepack unreadable: {origin}: {exc}"
    if not isinstance(candidate, dict):
        return f"tone rulepack must be a JSON/YAML object: {origin}"
    try:
        schema = personalization_ctl.pack_schema(PACK_TYPE)
    except (OSError, ValueError) as exc:
        return f"tone rulepack schema unavailable: {exc}"
    errors = personalization_ctl.validate_instance(candidate, schema)
    if errors:
        return f"tone rulepack invalid ({origin}): " + "; ".join(errors[:5])
    seen: set[str] = set()
    for rule in candidate["rules"]:
        if rule["id"] in seen:
            return f"tone rulepack invalid ({origin}): duplicate rule id {rule['id']!r}"
        seen.add(rule["id"])
    return candidate


def check(
    ws: str | Path,
    *,
    content: str | Path | None = None,
    pack: dict | str | Path | None = None,
) -> tuple[dict, int]:
    content_path = Path(content) if content else Path(ws) / "bundle" / "content.md"
    try:
        text = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return usage_error(str(ws), CHECKER, f"content not found: {content_path}")
    except (OSError, UnicodeError) as exc:
        return usage_error(str(ws), CHECKER, f"content unreadable: {exc}")
    if not text.strip():
        return usage_error(str(ws), CHECKER, "content is empty")

    loaded = _load_pack(pack)
    if isinstance(loaded, str):
        return usage_error(str(ws), CHECKER, loaded)

    body = TAG_RE.sub(" ", text)
    hard: list[dict] = []
    warn: list[dict] = []
    metrics: dict[str, dict] = {}
    for rule in loaded["rules"]:
        severity = rule.get("severity", "warn")
        scope = rule.get("scope", "body")
        scoped = _scoped_text(body, scope)
        try:
            findings, rule_metrics = _RULE_RUNNERS[rule["kind"]](rule, scoped)
        except ValueError as exc:
            return usage_error(str(ws), CHECKER, str(exc))
        rule_metrics["scope"] = scope
        rule_metrics["severity"] = severity
        rule_metrics["findings"] = len(findings)
        metrics[rule["id"]] = rule_metrics
        target = hard if severity == "hard" else warn
        target.extend(findings)

    verdict = verdict_skeleton(
        str(ws), CHECKER,
        hard=hard, warn=warn,
        extra={
            "content": str(content_path),
            "pack": {
                "name": loaded.get("name"),
                "version": loaded.get("version"),
                "rules": len(loaded["rules"]),
            },
            "metrics": metrics,
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="H4 tone-rulepack regression check on bundle/content.md"
    )
    parser.add_argument(
        "workspace", help="report workspace dir (.../workspaces/report-<slug>)"
    )
    parser.add_argument(
        "--content", default=None,
        help="explicit content.md path (default: <workspace>/bundle/content.md)",
    )
    parser.add_argument(
        "--pack", default=None,
        help=(
            "tone rulepack file, JSON or YAML subset (default: the neutral "
            f"built-in pack at {DEFAULT_TONE_PACK})"
        ),
    )
    return cli_main(
        parser,
        lambda args: check(args.workspace, content=args.content, pack=args.pack),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
