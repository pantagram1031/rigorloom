# -*- coding: utf-8 -*-
"""H5 structural gate: bold-subhead density on bundle/content.md.

The confirmed shared miss (variant-audit "Humanization transformation" row,
shared-miss #1): every instrument scored 0 coverage on the windpath pre-fix
state where AI drafting had sprinkled 18 bold pseudo-subheads over ~40k chars.
The manual H5 fix cut them to 6. This gate makes that lesson mechanical.

Metric: subhead count per 10k UTF-8 bytes of content.md, where a subhead is
a markdown bold-only line (``**소제목**``) or a deep heading (``###`` and
deeper — ``#``/``## SECTION:`` are the form's own structure and never count).
The denominator is the file's UTF-8 byte length, NOT unicode chars: the
corpus calibration points were measured on file size (windpath content.md =
43,508 bytes ≈ "40k"), and only the byte unit keeps all three points
consistent (unicode chars would shift Korean text ~3x denser).

Thresholds (parameterizable; defaults calibrated on real corpus points):
- WARN at >= 3.0 / 10k bytes
- HARD at >= 4.5 / 10k bytes
Calibration: windpath pre-fix ~18/40k = 4.5 (must be caught — the bound is
inclusive so the still-catches case cannot sit on an open boundary), windpath
post-fix 6/43508B = 1.38 and hawkes 10/56k = 1.8 both acceptable.

Also flags form-guide-label echoes used as subheads (결과 요약 / 결과의 의미 /
한계 및 제언 as bold lines) at WARN — those are the form's guide vocabulary
leaking into the report's own structure.

Exit 0 = pass (WARN allowed), 2 = usage/input error, 3 = HARD density.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)


CHECKER = "check_density"
DEFAULT_WARN_PER_10K = 3.0
DEFAULT_HARD_PER_10K = 4.5

BOLD_LINE_RE = re.compile(r"^\s*\*\*([^*].*?)\*\*\s*$")
DEEP_HEADING_RE = re.compile(r"^\s*#{3,}\s+(.+?)\s*$")

# Guide labels from the form's V-section instructions (결과 요약 / 결과의
# 의미(논의) / 한계점 및 제언). A report echoing them verbatim as its own
# subheads is reproducing form scaffolding, not writing structure.
DEFAULT_GUIDE_LABELS = (
    "결과 요약",
    "결과의 의미",
    "의미",
    "한계 및 제언",
    "한계점 및 제언",
)


def _subhead_lines(text: str) -> list[tuple[int, str]]:
    """Return (line_number, inner_text) for every subhead-shaped line."""
    found: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        bold = BOLD_LINE_RE.match(line)
        if bold:
            found.append((line_number, bold.group(1).strip()))
            continue
        heading = DEEP_HEADING_RE.match(line)
        if heading:
            found.append((line_number, heading.group(1).strip()))
    return found


def _is_guide_label_echo(inner: str, labels: tuple[str, ...]) -> bool:
    normalized = inner.strip().strip(":.").strip()
    for label in labels:
        if normalized == label or normalized.startswith(label + ":"):
            return True
    return False


def check(
    ws: str | Path,
    *,
    content: str | Path | None = None,
    warn_per_10k: float = DEFAULT_WARN_PER_10K,
    hard_per_10k: float = DEFAULT_HARD_PER_10K,
    guide_labels: tuple[str, ...] = DEFAULT_GUIDE_LABELS,
) -> tuple[dict, int]:
    content_path = Path(content) if content else Path(ws) / "bundle" / "content.md"
    try:
        text = content_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return usage_error(
            str(ws), CHECKER, f"content not found: {content_path}",
        )
    except (OSError, UnicodeError) as exc:
        return usage_error(
            str(ws), CHECKER, f"content unreadable: {exc}",
        )
    size = len(text.encode("utf-8"))
    if size == 0:
        return usage_error(str(ws), CHECKER, "content is empty")
    if not (0 < warn_per_10k <= hard_per_10k):
        return usage_error(
            str(ws), CHECKER,
            "thresholds must satisfy 0 < warn_per_10k <= hard_per_10k",
        )

    subheads = _subhead_lines(text)
    density = len(subheads) * 10000.0 / size

    hard: list[dict] = []
    warn: list[dict] = []
    if density >= hard_per_10k:
        hard.append({
            "code": "subhead_density_hard",
            "msg": (
                f"subhead density {density:.2f}/10k bytes >= HARD threshold "
                f"{hard_per_10k:.2f} — structural AI-tell (H5 class)"
            ),
            "at": f"{len(subheads)} subheads / {size} utf8 bytes",
        })
    elif density >= warn_per_10k:
        warn.append({
            "code": "subhead_density_warn",
            "msg": (
                f"subhead density {density:.2f}/10k bytes >= WARN threshold "
                f"{warn_per_10k:.2f}"
            ),
            "at": f"{len(subheads)} subheads / {size} utf8 bytes",
        })

    echoes = []
    for line_number, inner in subheads:
        if _is_guide_label_echo(inner, guide_labels):
            echoes.append(inner)
            warn.append({
                "code": "guide_label_echo",
                "msg": "form guide label used verbatim as a subhead",
                "at": inner,
                "line": line_number,
            })

    verdict = verdict_skeleton(
        str(ws), CHECKER,
        hard=hard, warn=warn,
        extra={
            "content": str(content_path),
            "density_per_10k": round(density, 3),
            "thresholds": {
                "warn_per_10k": warn_per_10k,
                "hard_per_10k": hard_per_10k,
            },
            "guide_label_echoes": echoes,
        },
        counts={
            "hard": len(hard), "warn": len(warn),
            "utf8_bytes": size, "subheads": len(subheads),
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="H5 bold-subhead density gate on bundle/content.md"
    )
    parser.add_argument(
        "workspace", help="report workspace dir (.../workspaces/report-<slug>)"
    )
    parser.add_argument(
        "--content", default=None,
        help="explicit content.md path (default: <workspace>/bundle/content.md)",
    )
    parser.add_argument(
        "--warn-per-10k", type=float, default=DEFAULT_WARN_PER_10K,
        help=f"WARN threshold, subheads per 10k UTF-8 bytes (default {DEFAULT_WARN_PER_10K})",
    )
    parser.add_argument(
        "--hard-per-10k", type=float, default=DEFAULT_HARD_PER_10K,
        help=f"HARD threshold, subheads per 10k UTF-8 bytes (default {DEFAULT_HARD_PER_10K})",
    )
    parser.add_argument(
        "--label", action="append", default=[],
        help="additional guide label to flag when echoed as a subhead (repeatable)",
    )
    return cli_main(
        parser,
        lambda args: check(
            args.workspace,
            content=args.content,
            warn_per_10k=args.warn_per_10k,
            hard_per_10k=args.hard_per_10k,
            guide_labels=DEFAULT_GUIDE_LABELS + tuple(args.label),
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
