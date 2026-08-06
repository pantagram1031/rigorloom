# -*- coding: utf-8 -*-
"""Form-scan auto-derived residue gate for final artifacts.

The anchor/guide-text inventory recorded by the form scan (form_profile.json)
IS the forbidden list for the final artifact — auto-derivation instead of a
hand-written residue vocabulary (variant-audit "Gate architecture" row:
"스캔이 아는 것 = 게이트가 검사하는 것"). Anchors that legitimately remain in
a filled report (section headings such as "I.  서론" / "1.  연구설계") are
excluded via an explicit keep-list: a regex pattern (default matches Roman or
Arabic numbered headings) plus optional exact keep strings.

Placeholder names/ids from the form (e.g. the 20101/김선덕 family) are part of
the anchor inventory and therefore count as residue when they survive into a
final.

Loud-failure contract (shared-miss #4): a missing pinned artifact is a HARD
error (exit 3, finding ``pinned_target_missing``), never a silent pass. A
missing or unparsable form profile is a usage error (exit 2).

Validity precedes text scanning: for an hwpx artifact, every
``Contents/section*.xml`` and ``header.xml`` member is XML-parsed BEFORE any
residue scan. A ParseError is a HARD finding (``artifact_malformed``) — a
malformed section renders blank in Hancom, so tag-strip-scanning its bytes
and reporting ``pass`` would certify an unopenable document (live-fire
finding, 2026-08). Plain-text-dump artifacts are exempt from XML validation.

Exit 0 = clean, 2 = usage/input error, 3 = residue found, target missing, or
artifact malformed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

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


CHECKER = "check_residue"

# Section-heading anchors that legitimately remain in a filled report:
# Roman-numeral headings ("I.  서론", "VI.  참고문헌") and Arabic numbered
# sub-headings ("1.  연구설계"). Everything else in the scan inventory is
# guide/placeholder material that must not survive into the final.
DEFAULT_KEEP_PATTERN = r"^[IVX]+\.|^\d+\."

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")

# Members whose well-formedness decides whether Hancom can render the
# document at all: every section body plus the style/metadata header.
_CRITICAL_MEMBER_RE = re.compile(
    r"^Contents/(?:section\d*|header)\.xml$", re.IGNORECASE
)


def _normalize(text: str) -> str:
    """Collapse whitespace runs so scan strings match reflowed XML text."""
    return _WS_RE.sub(" ", text).strip()


def _profile_inventory(profile: dict) -> list[dict]:
    """Flatten the form scan into (text, source) rows, in scan order."""
    rows: list[dict] = []
    for anchor in profile.get("anchors") or []:
        if isinstance(anchor, str):
            rows.append({"text": anchor, "source": "anchor"})
    for entry in profile.get("guide_text") or []:
        if isinstance(entry, str):
            rows.append({"text": entry, "source": "guide_text"})
        elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
            rows.append({"text": entry["text"], "source": "guide_text"})
    for entry in profile.get("placeholders") or []:
        if isinstance(entry, str):
            rows.append({"text": entry, "source": "placeholder"})
        elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
            rows.append({"text": entry["text"], "source": "placeholder"})
    return rows


def derive_forbidden(
    profile: dict,
    keep_pattern: str = DEFAULT_KEEP_PATTERN,
    keep_exact: tuple[str, ...] | list[str] = (),
) -> tuple[list[dict], list[str]]:
    """Split the scan inventory into (forbidden rows, kept strings).

    ``keep_pattern`` is matched against the raw scan string; ``keep_exact``
    entries are compared after whitespace normalization.
    """
    keep_re = re.compile(keep_pattern) if keep_pattern else None
    keep_normalized = {_normalize(item) for item in keep_exact}
    forbidden: list[dict] = []
    kept: list[str] = []
    seen: set[str] = set()
    for row in _profile_inventory(profile):
        normalized = _normalize(row["text"])
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if (keep_re and keep_re.match(row["text"].strip())) or (
            normalized in keep_normalized
        ):
            kept.append(row["text"])
            continue
        forbidden.append({
            "text": row["text"],
            "normalized": normalized,
            "source": row["source"],
        })
    return forbidden, kept


def _xml_entry_text(payload: bytes) -> str:
    """Extract visible text from one XML entry; tag-strip on parse failure.

    The fallback only ever runs for NON-critical members: every
    ``Contents/section*.xml`` / ``header.xml`` member has already passed
    :func:`malformed_members` by the time text extraction happens.
    """
    try:
        root = ElementTree.fromstring(payload)
        return " ".join(root.itertext())
    except ElementTree.ParseError:
        return _TAG_RE.sub(" ", payload.decode("utf-8", errors="replace"))


def malformed_members(path: Path) -> list[dict]:
    """XML-validate every render-critical member of an hwpx zip.

    Returns one ``{"member", "error"}`` row per Contents/section*.xml or
    header.xml member that fails to parse (the error string carries the
    parser's line/column position). Empty list = all critical members are
    well-formed. Non-zip paths never reach this function.
    """
    findings: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not _CRITICAL_MEMBER_RE.match(name.replace("\\", "/")):
                continue
            try:
                ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                findings.append({"member": name, "error": str(exc)})
    return findings


def artifact_text(path: Path) -> str:
    """Return normalized searchable text for an hwpx (zip) or a text dump."""
    if zipfile.is_zipfile(path):
        chunks: list[str] = []
        with zipfile.ZipFile(path) as archive:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith(".xml")
            ]
            section_names = [
                name for name in names
                if name.replace("\\", "/").startswith("Contents/")
            ]
            for name in sorted(section_names or names):
                chunks.append(_xml_entry_text(archive.read(name)))
        return _normalize(" ".join(chunks))
    return _normalize(path.read_text(encoding="utf-8"))


def check(
    form_profile: str | Path,
    artifact: str | Path,
    *,
    keep_pattern: str = DEFAULT_KEEP_PATTERN,
    keep: tuple[str, ...] | list[str] = (),
) -> tuple[dict, int]:
    profile_path = Path(form_profile)
    artifact_path = Path(artifact)

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return usage_error(
            str(artifact_path), CHECKER,
            f"form profile not found: {profile_path}",
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return usage_error(
            str(artifact_path), CHECKER,
            f"form profile unreadable: {exc}",
        )
    if not isinstance(profile, dict):
        return usage_error(
            str(artifact_path), CHECKER,
            "form profile must be a JSON object",
        )
    try:
        forbidden, kept = derive_forbidden(profile, keep_pattern, keep)
    except re.error as exc:
        return usage_error(
            str(artifact_path), CHECKER,
            f"invalid --keep-pattern: {exc}",
        )

    hard: list[dict] = []
    warn: list[dict] = []

    # Shared-miss #4: the pinned target going missing is a HARD finding —
    # a gate must never record a pass against a file that is not there.
    if not artifact_path.is_file():
        hard.append({
            "code": "pinned_target_missing",
            "msg": "pinned artifact path does not exist — refusing to pass "
                   "a residue gate against a missing target",
            "at": str(artifact_path),
        })
        verdict = verdict_skeleton(
            str(artifact_path), CHECKER,
            hard=hard, warn=warn,
            extra={
                "form_hash": profile.get("form_hash"),
                "artifact": str(artifact_path),
                "residue": [],
            },
            counts={
                "hard": len(hard), "warn": 0,
                "forbidden": len(forbidden), "kept": len(kept),
                "residue": 0,
            },
        )
        return verdict, exit_code(hard=hard)

    # Validity precedes text scanning (live-fire finding): a malformed
    # section renders BLANK in Hancom, so a text scan over its raw bytes
    # could report "pass" for a document that does not open. HARD-fail and
    # skip the residue scan entirely — its result would be meaningless.
    if zipfile.is_zipfile(artifact_path):
        try:
            broken = malformed_members(artifact_path)
        except (OSError, zipfile.BadZipFile) as exc:
            return usage_error(
                str(artifact_path), CHECKER,
                f"artifact unreadable: {exc}",
            )
        if broken:
            for row in broken:
                hard.append({
                    "code": "artifact_malformed",
                    "msg": (
                        f"render-critical member {row['member']} is not "
                        f"well-formed XML ({row['error']}) — document "
                        "renders blank; residue scan skipped"
                    ),
                    "at": row["member"],
                })
            verdict = verdict_skeleton(
                str(artifact_path), CHECKER,
                hard=hard, warn=warn,
                extra={
                    "form_hash": profile.get("form_hash"),
                    "artifact": str(artifact_path),
                    "residue": [],
                    "malformed_members": broken,
                },
                counts={
                    "hard": len(hard), "warn": len(warn),
                    "forbidden": len(forbidden), "kept": len(kept),
                    "residue": 0,
                },
            )
            return verdict, exit_code(hard=hard)

    try:
        haystack = artifact_text(artifact_path)
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        return usage_error(
            str(artifact_path), CHECKER,
            f"artifact unreadable: {exc}",
        )

    residue: list[dict] = []
    for row in forbidden:
        if row["normalized"] in haystack:
            residue.append({"text": row["text"], "source": row["source"]})
            hard.append({
                "code": "form_residue",
                "msg": f"form {row['source']} text survives in the final artifact",
                "at": row["text"],
            })

    verdict = verdict_skeleton(
        str(artifact_path), CHECKER,
        hard=hard, warn=warn,
        extra={
            "form_hash": profile.get("form_hash"),
            "artifact": str(artifact_path),
            "residue": residue,
        },
        counts={
            "hard": len(hard), "warn": len(warn),
            "forbidden": len(forbidden), "kept": len(kept),
            "residue": len(residue),
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="form-scan auto-derived residue gate for a final artifact"
    )
    parser.add_argument(
        "--form-profile", required=True,
        help="form scan JSON (form_profile.json: form_hash + anchors + guide_text)",
    )
    parser.add_argument(
        "--artifact", required=True,
        help="final artifact to scan (hwpx zip or plain-text dump)",
    )
    parser.add_argument(
        "--keep-pattern", default=DEFAULT_KEEP_PATTERN,
        help="regex for anchors that legitimately remain (default: numbered "
             "section headings)",
    )
    parser.add_argument(
        "--keep", action="append", default=[],
        help="exact anchor text to keep (repeatable)",
    )
    return cli_main(
        parser,
        lambda args: check(
            args.form_profile,
            args.artifact,
            keep_pattern=args.keep_pattern,
            keep=tuple(args.keep),
        ),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
