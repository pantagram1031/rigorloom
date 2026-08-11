# -*- coding: utf-8 -*-
"""Form-scan auto-derived residue gate for final artifacts.

The anchor/removable-guide inventory recorded by the form scan
(form_profile.json) IS the forbidden list for the final artifact —
auto-derivation instead of a hand-written residue vocabulary (variant-audit
"Gate architecture" row:
"스캔이 아는 것 = 게이트가 검사하는 것"). Anchors that legitimately remain in
a filled report (section headings such as "I.  서론" / "1.  연구설계") are
excluded via an explicit keep-list: a regex pattern (default matches Roman or
Arabic numbered headings) plus optional exact keep strings.

Placeholder names/ids from the form (e.g. the 20101/김선덕 family) are part of
the anchor inventory and therefore count as residue when they survive into a
final. Removable guide text follows the same rule; reader-facing guide text
that is absent from ``removal_targets`` is retained form content, not residue.

``--fill-map`` covers the shape a keep-list cannot express. Filling a labeled
field semantically means keeping the label as a prefix — a URL field goes
``" http://"`` -> ``" http://hanbit.example.kr"``, a zip field keeps its
``" 우(     -     )"`` skeleton and appends the address — so the key text
SURVIVES inside the value by construction. With the fill map declared, every
occurrence of a forbidden string that lies wholly inside an occurrence of a
declared value is attributed to that value's span instead of counted as
residue. Attribution is per-occurrence, never a global suppression of the
string: a second, genuinely unfilled occurrence of the same key elsewhere
still HARDs, and its offset plus surrounding context is reported. A removable
guide target is never attributable — instruction prose is not something a fill
keeps; retained reader-facing guide text is not forbidden in the first place.

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
from collections import Counter
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
# removable-guide/placeholder material that must not survive into the final;
# reader-facing guide text is excluded by the profile's removal policy.
DEFAULT_KEEP_PATTERN = r"^[IVX]+\.|^\d+\."

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_MISSING_POLICY = object()

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


def _validated_removal_policy(guide_entries, raw_policy):
    """Return target paragraph ids, or ``None`` for legacy fail-closed mode.

    A policy is only trustworthy when the diagnostic guide inventory itself is
    paragraph-addressed and both sides are unique, non-negative integer ids.
    This deliberately treats string/partial guide entries and malformed target
    references as legacy input rather than silently relaxing residue checks.
    """
    if (not isinstance(guide_entries, list)
            or raw_policy is _MISSING_POLICY
            or not isinstance(raw_policy, list)):
        return None
    guide_ids = set()
    for entry in guide_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            return None
        para_idx = entry.get("para_idx")
        if (isinstance(para_idx, bool) or not isinstance(para_idx, int)
                or para_idx < 0 or para_idx in guide_ids):
            return None
        guide_ids.add(para_idx)
    target_ids = set()
    for target in raw_policy:
        if not isinstance(target, dict):
            return None
        para_idx = target.get("para_idx")
        if (isinstance(para_idx, bool) or not isinstance(para_idx, int)
                or para_idx < 0 or para_idx in target_ids):
            return None
        target_ids.add(para_idx)
    if not target_ids <= guide_ids:
        return None
    return target_ids


def _validated_anchor_records(profile):
    """Return address-bound anchors, or ``None`` for legacy fail-closed mode.

    ``anchor_records`` is an additive field: old profiles keep their
    text-only ``anchors`` behavior.  Identity mode is enabled only when every
    record has a unique non-negative legacy ``para_idx``, a section, and a
    text whose multiset exactly matches the legacy anchor list.  A present
    ``at_para`` is the newer preedit address and is validated independently;
    T47 residue identity continues to use legacy ``para_idx``.
    """
    anchors = profile.get("anchors", _MISSING_POLICY)
    records = profile.get("anchor_records", _MISSING_POLICY)
    if (not isinstance(anchors, list) or not isinstance(records, list)
            or any(not isinstance(anchor, str) for anchor in anchors)):
        return None
    seen_para = set()
    seen_at_para = set()
    record_texts = []
    for record in records:
        if not isinstance(record, dict):
            return None
        text = record.get("text")
        section = record.get("section")
        para_idx = record.get("para_idx")
        at_para = record.get("at_para")
        if (not isinstance(text, str) or not isinstance(section, str)
                or not section or isinstance(para_idx, bool)
                or not isinstance(para_idx, int) or para_idx < 0
                or para_idx in seen_para):
            return None
        # ``para_idx`` remains the legacy T47 identity.  When the additive
        # preedit address is present, validate it too; malformed or duplicate
        # addresses fail closed instead of becoming a trusted scope hint.
        if at_para is not None:
            if (isinstance(at_para, bool) or not isinstance(at_para, int)
                    or at_para < 0 or at_para in seen_at_para):
                return None
            seen_at_para.add(at_para)
        seen_para.add(para_idx)
        record_texts.append(text)
    if Counter(record_texts) != Counter(anchors):
        return None
    return records


def _profile_inventory(profile: dict) -> list[dict]:
    """Flatten the *forbidden* form-scan inventory into rows.

    ``guide_text`` is a diagnostic inventory, not an assertion that every
    guide paragraph must be deleted.  The form scanner's explicit
    ``removal_targets`` policy is the authority for which guide entries are
    forbidden.  With a valid explicit policy, a guide entry without a matching
    ``para_idx`` is retained reader-facing text. Missing/malformed policy is
    treated as legacy and keeps the old all-guide behavior, so a broken
    profile cannot silently relax the gate.
    """
    rows: list[dict] = []
    raw_guides = profile.get("guide_text") or []
    guide_entries = raw_guides if isinstance(raw_guides, list) else [raw_guides]
    removal_para_idxs = _validated_removal_policy(
        raw_guides if isinstance(raw_guides, list) else None,
        profile.get("removal_targets", _MISSING_POLICY))
    anchor_records = _validated_anchor_records(profile)
    # Paragraph identity is trusted only when all three inventories validate.
    # Otherwise preserve the legacy fail-closed behavior: every anchor and
    # every guide remains forbidden, regardless of a partial policy.
    if removal_para_idxs is None or anchor_records is None:
        removal_para_idxs = None

    if anchor_records is not None and removal_para_idxs is not None:
        retained_para_idxs = {
            entry["para_idx"] for entry in guide_entries
            if entry["para_idx"] not in removal_para_idxs
        }
        for record in anchor_records:
            if record["para_idx"] in retained_para_idxs:
                continue
            rows.append({"text": record["text"], "source": "anchor"})
    else:
        for anchor in profile.get("anchors") or []:
            if isinstance(anchor, str):
                rows.append({"text": anchor, "source": "anchor"})
    for entry in guide_entries:
        if isinstance(entry, str):
            if removal_para_idxs is not None:
                # A string guide entry has no paragraph identity to match
                # against removal_targets. Under an explicit, valid policy it
                # is retained; legacy fallback above keeps it fail-closed.
                continue
            rows.append({"text": entry, "source": "guide_text"})
        elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
            if (removal_para_idxs is not None
                    and entry.get("para_idx") not in removal_para_idxs):
                continue
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
    entries are compared after whitespace normalization.  For a profile with
    a valid ``removal_targets`` list, only named guide entries are in the
    inventory; retained reader-facing guide text is never made residue merely
    because it was detected. Legacy/malformed profiles retain the historical
    all-guide fallback.
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


#: What a SCOPED fill-map value object may carry — the **union** of both
#: halves, on purpose. One file serves ``preedit replace --map`` and
#: ``--fill-map`` alike (T35), so each side accepts the other's members and
#: interprets only its own. The engine half is
#: ``engine/scripts/preedit.py``'s ``MAP_SCOPE_MEMBERS``; if either side
#: rejected the other's members as unknown, "one file for both" would break.
FILL_SCOPE_MEMBERS = ("text", "at_para", "all_occurrences",
                      "other_occurrences")

#: The only member this side interprets, and its two legal answers (T41). A
#: bare label that repeats — 성명 three times on a 민원 form — leaves the keep
#: derivation with a question only the operator can answer: are the
#: occurrences you did NOT fill form text, or unfilled seats? Both answers are
#: honest; guessing either one is not.
OTHER_OCCURRENCES = ("form_text", "seats")


def normalize_fill_map(payload) -> tuple[dict | None, str | None]:
    """``(mapping, error)`` for an already-decoded ``--fill-map`` payload.

    THE shape rule for the flag, in one place: a wrapper (an object with a
    ``fill_map`` member) is unwrapped; any other object IS the map. A wrapper
    whose ``fill_map`` member is not an object is a usage error rather than
    being read as a bare map — otherwise an expectations file with
    ``"fill_map": null`` would silently be scanned as ``{base_pt: 10, ...}``.

    Scoped values are FLATTENED here: ``{"text": v, ...}`` becomes ``v``, so
    every downstream consumer (``value_spans``, the fill-value presence check,
    each module's declared-value privacy rules) keeps seeing a plain string
    and none of them had to learn the scope vocabulary. Read the scope itself
    with :func:`fill_map_scopes`.
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
        payload = inner
    flat, error = {}, None
    for key, value in payload.items():
        if not isinstance(value, dict):
            flat[key] = value
            continue
        unknown = sorted(set(value) - set(FILL_SCOPE_MEMBERS))
        if unknown:
            return None, (f"--fill-map[{key!r}]: unknown scope member(s) "
                          f"{unknown}; allowed: {list(FILL_SCOPE_MEMBERS)}")
        if "text" not in value:
            return None, (f"--fill-map[{key!r}]: a scoped value object needs "
                          f"a 'text' member (the value you wrote)")
        other = value.get("other_occurrences")
        if other is not None and other not in OTHER_OCCURRENCES:
            return None, (f"--fill-map[{key!r}]: other_occurrences must be "
                          f"one of {list(OTHER_OCCURRENCES)}, got {other!r}")
        flat[key] = value["text"]
    return flat, error


def fill_map_scopes(payload) -> dict:
    """``{key: other_occurrences}`` for the keys that declared one.

    Only the member THIS side interprets. Shape errors are not re-reported
    here: :func:`normalize_fill_map` runs first on the same payload and is the
    single place that refuses a malformed scope.
    """
    if isinstance(payload, dict) and isinstance(payload.get("fill_map"), dict):
        payload = payload["fill_map"]
    if not isinstance(payload, dict):
        return {}
    return {key: value["other_occurrences"]
            for key, value in payload.items()
            if isinstance(value, dict)
            and value.get("other_occurrences") in OTHER_OCCURRENCES}


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


def load_fill_scopes(path: str | Path) -> dict:
    """:func:`fill_map_scopes` for a file, ``{}`` when it cannot be read.

    A separate read rather than a second return value from
    :func:`load_fill_map`: every existing consumer wants the flattened map and
    nothing else, and only the keep derivation needs the scope.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return fill_map_scopes(payload)


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


#: Public alias, for the same reason ``normalize_text`` is one: whatever
#: decides that a form label is "repeated" must count occurrences EXACTLY the
#: way this gate does, or the ambiguity refusal and the gate disagree (T41).
occurrences = _occurrences


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
        # Removable guide text is never attributable, the same reason it is
        # never keepable: a correct fill REPLACES instruction prose, it never
        # keeps it as a prefix, so a declared value containing guide text is a
        # leak. Reader-facing guide text never reached ``forbidden`` above.
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
        help=("form scan JSON (form_profile.json: form_hash + anchors + "
              "removal_targets + guide_text + placeholders)"),
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
        help="exact anchor text to keep (repeatable). A value that STARTS WITH "
             "'-' must use the '=' form — write --keep=-- , never --keep -- , "
             "because argparse reads a bare '--' as its end-of-options marker "
             "and the value never arrives (T116). Real forms print '--' as a "
             "placeholder, so this is not hypothetical",
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
