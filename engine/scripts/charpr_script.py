#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charpr_script.py — the ONE definition of the T30 script/scale/offset trap.

T30 (clean-room cross-model run, PPS 협업제품명 cell): a fill inherited a
``charPr`` identical to body text except for a trailing ``<hh:supscript/>``.
Nominal ``height`` never changed, so every height/colour-based offline proof
passed while Hancom rendered the value at ~6.35pt raised off the baseline.

Two tools now need the SAME comparison:

  * ``engine/scripts/form_inspect.py`` — PRE-flight. Flags a fill target whose
    run already carries the anomaly, so ``preedit fill-cells`` can be told the
    right ``charPr`` id BEFORE the fill (T30 becomes preventable).
  * ``pipeline/scripts/visual_verify.py`` — POST-flight. HARDs on a
    fill-modified run whose charPr differs from the body baseline (T30 stays
    detectable).

They must not be able to disagree, so the profile extraction, the signature,
the baseline choice and the difference test all live here and are imported by
both. This module owns NO policy — it never decides that a difference is a
refusal; that is the caller's contract.

Import direction: ``engine/scripts`` is self-contained (nothing here imports
``pipeline/``), and ``visual_verify`` already puts ``engine/scripts`` on
``sys.path``. So this module can be shared without any import cycle.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

#: OWPML ``hh:charPr`` children that move or resize a run WITHOUT changing its
#: nominal ``height``. ``supscript``/``subscript`` are presence-only flags;
#: ``ratio``/``relSz``/``offset`` carry per-language percentages/offsets. A run
#: that inherits any of these differently from body text renders at a
#: different size or baseline while every height-based proof still passes.
SCRIPT_FLAG_TAGS = ("supscript", "subscript")
SCRIPT_SCALE_TAGS = ("ratio", "relSz", "offset")

#: Every key a script signature carries, in a stable order.
SIGNATURE_KEYS = (*SCRIPT_FLAG_TAGS, *SCRIPT_SCALE_TAGS)

#: Hancom renders a supscript/subscript run at roughly this fraction of the
#: nominal height. Reported as evidence, never used as a threshold.
SCRIPT_RENDER_FACTOR = 0.635

_NS = r"[A-Za-z0-9]+"
#: A self-closing element (``<hp:run .../>``, ``<hp:t/>``) owns no body text.
#: ``[^>]*?`` (lazy) followed by the ``/>`` | ``>...</ns:tag>`` alternation
#: recognises the self-close as a complete match with no body, instead of
#: letting a naive ``[^>]*>(.*?)</ns:tag>`` swallow the ``/>`` as ordinary
#: attribute text and keep scanning into the FOLLOWING sibling element for
#: the closing tag (T37 — see docs/trouble-table.md).
#:
#: The namespace prefix stays NON-capturing on purpose. Binding the closing
#: tag with a ``\1`` backreference would be marginally stricter, but it costs
#: a group, and a module-level pattern's group COUNT is part of its public
#: interface: ``findall`` silently changes shape and every ``.group(n)`` in
#: every caller shifts by one. That is how the first attempt at this fix
#: crashed ``check_gongmun`` and silently fed ``style_diff`` an attribute
#: string where it wanted a body. Arity is preserved here for that reason;
#: a mismatched ``<hp:t>…</hh:t>`` is not a shape HWPX produces.
_RUN_RE = re.compile(
    r"<" + _NS + r":run\b[^>]*\bcharPrIDRef=\"(\d+)\"[^>]*?"
    r"(?:/>|>(.*?)</" + _NS + r":run>)", re.S)
_RUN_TEXT_RE = re.compile(
    r"<" + _NS + r":t\b[^>]*?(?:/>|>(.*?)</" + _NS + r":t>)", re.S)


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def norm(text: str) -> str:
    """Whitespace-free comparison form (same convention as visual_verify)."""
    return re.sub(r"\s+", "", text or "")


def profiles_from_header(header_xml) -> dict:
    """``charPr id -> script/scale/offset profile`` from a header.xml body.

    ``header_xml`` is the raw ``Contents/header.xml`` bytes or text. Returns
    ``{}`` on anything unparseable — a caller that cannot read the header must
    say so out loud rather than treat the document as clean.
    """
    try:
        root = ET.fromstring(header_xml)
    except (ET.ParseError, UnicodeDecodeError, TypeError, ValueError):
        return {}
    profiles = {}
    for node in root.iter():
        if localname(node.tag) != "charPr":
            continue
        cid = node.get("id")
        if cid is None:
            continue
        profile = {tag: False for tag in SCRIPT_FLAG_TAGS}
        for tag in SCRIPT_SCALE_TAGS:
            profile[tag] = None
        height = node.get("height")
        profile["height_pt"] = (
            int(height) / 100.0 if height and height.isdigit() else None)
        for child in node:
            name = localname(child.tag)
            if name in SCRIPT_FLAG_TAGS:
                profile[name] = True
            elif name in SCRIPT_SCALE_TAGS:
                profile[name] = {k: v for k, v in sorted(child.attrib.items())}
        profiles[cid] = profile
    return profiles


def iter_runs(section_xml: str):
    """``[(charPrIDRef, text)]`` for every run in ``section_xml`` that carries
    visible text, in document order. Text-less runs (the empty-cell
    self-closing run a fill writes into) are not body text and are excluded —
    weighting the baseline by them would let a form's blanks outvote its prose.
    """
    out = []
    for cid, body in _RUN_RE.findall(section_xml):
        if not body:
            # Self-closing run (``<hp:run charPrIDRef="..."/>``): no body,
            # so by construction it carries no text — skip without even
            # looking for ``hp:t`` children (there cannot be any).
            continue
        text = "".join(_RUN_TEXT_RE.findall(body))
        text = re.sub(r"<[^>]+>", "", text)
        if text.strip():
            out.append((cid, text))
    return out


def signature(profile) -> dict:
    """The comparable part of a profile (``height_pt`` is NOT comparable — the
    whole point of T30 is that the nominal height is identical)."""
    return {key: (profile or {}).get(key) for key in SIGNATURE_KEYS}


def differing_keys(profile, baseline_profile) -> list:
    """Sorted signature keys on which ``profile`` departs from the baseline."""
    own, base = signature(profile), signature(baseline_profile)
    return sorted(key for key in SIGNATURE_KEYS if own[key] != base[key])


def body_baseline_id(weights):
    """The document's own body-baseline charPr id, or None.

    ``weights`` maps charPr id -> body-text weight (character count). The
    heaviest id wins; ties break on the smallest id string, which is what
    visual_verify has always done — the tie-break is arbitrary but it must be
    the SAME arbitrary choice in both tools.
    """
    if not weights:
        return None
    top = max(weights.values())
    return min(cid for cid, weight in weights.items() if weight == top)


def rendered_pt_estimate(profile):
    """~pt Hancom draws a script run at, or None when no script flag is set."""
    if not profile:
        return None
    height = profile.get("height_pt")
    if not height:
        return None
    if not (profile.get("supscript") or profile.get("subscript")):
        return None
    return round(height * SCRIPT_RENDER_FACTOR, 2)
