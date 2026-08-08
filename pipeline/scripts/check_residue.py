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

``--fill-map`` covers the shape a keep-list cannot express. Filling a labeled
field semantically means keeping the label as a prefix — a URL field goes
``" http://"`` -> ``" http://hanbit.example.kr"``, a zip field keeps its
``" 우(     -     )"`` skeleton and appends the address — so the key text
SURVIVES inside the value by construction. With the fill map declared, every
occurrence of a forbidden string that lies wholly inside an occurrence of a
declared value is attributed to that value's span instead of counted as
residue. Attribution is per-occurrence, never a global suppression of the
string: a second, genuinely unfilled occurrence of the same key elsewhere
still HARDs, and its offset plus surrounding context is reported. Guide text
is never attributable — instruction prose is not something a fill keeps.

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


#: Public alias. Anything that decides what this gate will flag — notably
#: ``visual_verify``'s ``--fill-map`` keep derivation — must normalize text
#: EXACTLY the way the gate does, or the two disagree about presence.
normalize_text = _normalize


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


#: What ``--fill-map`` accepts, in one sentence. Every consumer's usage error
#: ends with this, so a caller who guessed the wrong shape is told BOTH shapes
#: instead of having to guess again (T35).
FILL_MAP_SHAPES = (
    "--fill-map accepts either shape: a BARE JSON object of {key: value} (the "
    "'preedit replace --map' shape), or a WRAPPER object carrying a 'fill_map' "
    "member whose value is that object (the visual_verify --expectations "
    "shape)")


def _json_typename(value) -> str:
    """The JSON type name of a decoded value, for a usage message."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def normalize_fill_map(payload) -> tuple[dict | None, str | None]:
    """``(mapping, error)`` for an already-decoded ``--fill-map`` payload.

    THE shape rule for the flag, in one place: a wrapper (an object with a
    ``fill_map`` member) is unwrapped; any other object IS the map. A wrapper
    whose ``fill_map`` member is not an object is a usage error rather than
    being read as a bare map — otherwise an expectations file with
    ``"fill_map": null`` would silently be scanned as ``{base_pt: 10, ...}``.
    """
    if not isinstance(payload, dict):
        return None, (f"--fill-map must be a JSON object, got "
                      f"{_json_typename(payload)}. {FILL_MAP_SHAPES}")
    if "fill_map" in payload:
        inner = payload["fill_map"]
        if not isinstance(inner, dict):
            return None, (
                f"--fill-map: the wrapper's 'fill_map' member must be a JSON "
                f"object, got {_json_typename(inner)}. {FILL_MAP_SHAPES}")
        return inner, None
    return payload, None


def load_fill_map(path: str | Path) -> tuple[dict | None, str | None]:
    """``{key: value}`` from a fill map, an expectations file, or either shape.

    Returns (mapping, error). Accepts a flat ``{"key": "value"}`` object (the
    ``preedit replace --map`` shape) or an object carrying a ``fill_map``
    member, so a caller can pass the file it already has. ONE loader, shared by
    every consumer of the flag — ``visual_verify``, ``check_residue`` and each
    module checker — so a single file works for all of them and one wrong shape
    cannot cost a retry against the next consumer (T35). It lives in core so a
    module payload can import it without a module->module import.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"--fill-map not found: {path}"
    except (OSError, UnicodeError, ValueError) as exc:
        return None, f"--fill-map unreadable: {exc}"
    return normalize_fill_map(payload)


def _occurrences(haystack: str, needle: str) -> list[int]:
    """Every start offset of ``needle`` in ``haystack``, overlaps included."""
    if not needle:
        return []
    out: list[int] = []
    start = haystack.find(needle)
    while start >= 0:
        out.append(start)
        start = haystack.find(needle, start + 1)
    return out


def value_spans(haystack: str, fill_map) -> list[dict]:
    """``[{key, value, start, end}]`` — where each declared value landed.

    A span is text the operator declared they WROTE. Anything wholly inside
    one is authored content by that declaration, so it is not residue even
    when it repeats a form label; anything outside every span is untouched
    form text. Overlapping/repeated values each get their own span.
    """
    spans: list[dict] = []
    for key, value in sorted((fill_map or {}).items(), key=lambda kv: str(kv[0])):
        needle = _normalize(str(value if value is not None else ""))
        if not needle:
            continue
        for start in _occurrences(haystack, needle):
            spans.append({"key": str(key), "value": needle,
                          "start": start, "end": start + len(needle)})
    return spans


def _attributed(start: int, end: int, spans: list[dict]) -> dict | None:
    """The declared-value span that wholly contains ``[start, end)``."""
    for span in spans:
        if span["start"] <= start and end <= span["end"]:
            return span
    return None


def _context(haystack: str, start: int, end: int, width: int = 40) -> str:
    """The residue occurrence with its neighbours, so the report names a
    LOCATION and not just a string that appears somewhere."""
    left = max(0, start - width)
    prefix = "…" if left > 0 else ""
    suffix = "…" if end + width < len(haystack) else ""
    return f"{prefix}{haystack[left:end + width]}{suffix}"


def scan_residue(
    forbidden: list[dict],
    haystack: str,
    spans: list[dict] = (),
) -> tuple[list[dict], dict]:
    """(residue rows, tally) — occurrences minus the attributable ones.

    Without ``spans`` this reduces exactly to "is the forbidden string
    present at all", the pre-``--fill-map`` behavior. ``tally`` counts every
    forbidden-string occurrence, including those of rows that were fully
    attributed and therefore produced no finding.
    """
    rows: list[dict] = []
    tally = {"occurrences": 0, "attributed": 0, "unattributed": 0}
    for row in forbidden:
        needle = row["normalized"]
        hits = _occurrences(haystack, needle)
        if not hits:
            continue
        # Guide text is never attributable, the same reason it is never
        # keepable: a correct fill REPLACES instruction prose, it never keeps
        # it as a prefix, so a declared value containing guide text is a leak.
        usable = list(spans) if row["source"] != "guide_text" else []
        unattributed = [
            start for start in hits
            if _attributed(start, start + len(needle), usable) is None
        ]
        tally["occurrences"] += len(hits)
        tally["attributed"] += len(hits) - len(unattributed)
        tally["unattributed"] += len(unattributed)
        if not unattributed:
            continue
        rows.append({
            "text": row["text"],
            "source": row["source"],
            "occurrences": len(hits),
            "attributed": len(hits) - len(unattributed),
            "at_offsets": unattributed,
            "context": [_context(haystack, start, start + len(needle))
                        for start in unattributed[:3]],
        })
    return rows, tally


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
    fill_map: dict | None = None,
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

    spans = value_spans(haystack, fill_map) if fill_map else []
    residue, tally = scan_residue(forbidden, haystack, spans)
    for row in residue:
        detail = ""
        if row["attributed"]:
            detail = (f" — {len(row['at_offsets'])} of {row['occurrences']} "
                      "occurrence(s) lie outside every declared fill value")
        hard.append({
            "code": "form_residue",
            "msg": (f"form {row['source']} text survives in the final "
                    f"artifact{detail}"),
            "at": row["text"],
            "at_offsets": row["at_offsets"],
            "context": row["context"][0] if row["context"] else None,
        })

    extra = {
        "form_hash": profile.get("form_hash"),
        "artifact": str(artifact_path),
        "residue": residue,
    }
    if fill_map is not None:
        extra["fill_attribution"] = {
            "keys": sorted(str(key) for key in fill_map),
            "value_spans": len(spans),
            **tally,
        }
    verdict = verdict_skeleton(
        str(artifact_path), CHECKER,
        hard=hard, warn=warn,
        extra=extra,
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
    parser.add_argument(
        "--fill-map", default=None,
        help="fill map JSON — either a bare {key: value} object or an object "
             "with a 'fill_map' member holding one -> occurrences of a "
             "forbidden string INSIDE a declared value are attributed to that "
             "value (prefix-preserving fills), occurrences outside every "
             "value still HARD",
    )

    def _invoke(args):
        fill_map = None
        if args.fill_map:
            fill_map, error = load_fill_map(args.fill_map)
            if error:
                return usage_error(args.artifact, CHECKER, error)
        return check(
            args.form_profile,
            args.artifact,
            keep_pattern=args.keep_pattern,
            keep=tuple(args.keep),
            fill_map=fill_map,
        )

    return cli_main(parser, _invoke, argv)


if __name__ == "__main__":
    raise SystemExit(main())
