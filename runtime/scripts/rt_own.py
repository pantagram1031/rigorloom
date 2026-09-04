#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tier 3 — our own renderer, and the label that says it is ours.

WHY THIS EXISTS. ``rt_render`` can rasterise a PDF and nothing else, and
``rt_convert`` can only make a PDF where Hancom is installed and idle. On a
fresh install neither is true: the packaged sidecar carries no ``pyhwpx``, so
``document/renderPrepare`` answers ``needs_hancom`` and the whole 페이지 보기
surface is a refusal card. That is honest and it is also useless — the product
shows nothing on the machine most people will run it on.

``engine/scripts/own_render.py`` draws an OWPML document without Hancom. It is
not a substitute for one: it is Rigorloom's own reading of the format, it is
NOT certified against a Hancom reference render, and it knows which elements it
did not draw. So this module wires it in as a THIRD tier, under two rules that
are the whole point of the file:

1. **It never claims to be Hancom.** Every answer that came from here carries
   ``tier: 3`` and ``grade: "own-uncertified"``, and the sidecar's own
   ``grade_meaning`` travels with it. A grade is a closed vocabulary
   (:data:`RENDER_GRADES`) so the Desktop can switch on it instead of matching
   on prose, and the tier a page came from is on the page, not in a log.

2. **It says what it could not draw.** The sidecar's ``elements_skipped`` is
   forwarded verbatim, not summarised away. A renderer that quietly omits a
   border and a renderer that draws one are indistinguishable from a
   screenshot; the list is the difference.

The child is spawned exactly like every other engine child (``run_child``,
``child_python``, the environment allowlist, a bounded timeout), so the frozen
sidecar's interpreter role covers it and there is no second spawn convention.
Its output is cached under ``<session>/derived/own/<key>`` and BOUND to the
digest of the bytes it was drawn from, the same rule ``rt_convert.existing_pdf``
enforces: serving a page of some other document as this document's pages is the
worst failure a viewer has, and it does not become acceptable because we drew
the page ourselves.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import RpcError  # noqa: E402
from rt_engine import child_python, run_child  # noqa: E402
from rt_session import atomic_write_bytes, now_utc, sha256_file  # noqa: E402

#: Where a tier-3 render lands, under the session.
OWN_DIRNAME = "derived/own"

#: The renderer script, relative to the engine root.
OWN_RENDER_SCRIPT = ("engine", "scripts", "own_render.py")

#: What this renderer can read. It is an OWPML renderer; ``.hwp`` is the binary
#: format and is not one.
OWN_RENDERABLE_SUFFIXES = (".hwpx",)

#: Generous, because a first render of a long form measures every glyph, and a
#: bounded child that gets killed mid-page is a worse answer than a slow one.
OWN_RENDER_TIMEOUT_SECONDS = 300.0

#: How a page was drawn. CLOSED, so the Desktop switches instead of guessing.
#:
#:   hancom           a PDF this machine's Hancom produced (document/renderPrepare)
#:   pdf              a PDF that arrived as the document, or as a candidate
#:   own-uncertified  engine/scripts/own_render.py — ours, and not certified
RENDER_GRADES = ("hancom", "pdf", "own-uncertified")

#: The tier number each grade sits at, for the one place that wants an integer.
GRADE_TIER = {"hancom": 1, "pdf": 2, "own-uncertified": 3}

#: The grade of the own renderer, duplicated from ``own_render.GRADE`` rather
#: than imported: importing the renderer to read one constant would pull 7k
#: lines and Pillow into the server process. :func:`own_render` asserts the two
#: agree on every real render, so a drift is caught by the first page drawn.
OWN_GRADE = "own-uncertified"

#: Why tier 3 could not step in. Closed, and reported inside the existing
#: unavailable envelope rather than as a new shape.
OWN_UNAVAILABLE_REASONS = (
    "script_missing",       # own_render.py is not in this install
    "not_own_renderable",   # the subject is not an HWPX
    "renderer_unavailable",  # the renderer refused: no Pillow, no fonts (exit 3)
    "render_failed",        # it ran and did not produce a page
    "page_out_of_range",    # it drew fewer pages than the one asked for
)


def own_render_script(tools=None) -> Path:
    """``tools`` may be None: ``capabilities/list`` asks before a session exists."""
    if tools is None:
        from rt_engine import DEFAULT_ENGINE_ROOT

        root = Path(DEFAULT_ENGINE_ROOT)
    else:
        root = tools.root
    return root.joinpath(*OWN_RENDER_SCRIPT)


def own_capability(tools=None) -> dict:
    """``capabilities.render.own`` — is there a third tier on this machine?

    Cheap on purpose: a file test and a ``find_spec``, no spawn. The
    ``imaging`` row is explicitly THIS interpreter's answer and says so, because
    the child may be a different one (``RIGORLOOM_CHILD_PYTHON``) and the only
    authority on whether the renderer can run is the renderer's own exit code.
    """
    import importlib.util

    script = own_render_script(tools)
    present = script.is_file()
    pillow = importlib.util.find_spec("PIL") is not None
    return {
        "state": "yes" if present else "no",
        "reason": (None if present else
                   "engine/scripts/own_render.py is not in this install"),
        "method": "document/render",
        "tier": 3,
        "grade": OWN_GRADE,
        "backend": "engine/scripts/own_render.py",
        "renderableFrom": list(OWN_RENDERABLE_SUFFIXES),
        "certified": False,
        "note": ("Rigorloom's own OWPML renderer. It is NOT certified against a "
                 "Hancom reference render, it names the elements it did not "
                 "draw, and every page it produces is labelled "
                 f"grade={OWN_GRADE}"),
        "imaging": {
            "state": "yes" if pillow else "unknown",
            "module": "PIL",
            "note": ("this is the SERVER interpreter's answer; the renderer "
                     "runs in a child that may be a different interpreter, and "
                     "its own refusal is the authority"),
        },
        "unavailableReasons": list(OWN_UNAVAILABLE_REASONS),
    }


def own_unavailable(reason: str, detail: str, **extra) -> dict:
    """The ``own`` row that rides inside an existing unavailable answer."""
    assert reason in OWN_UNAVAILABLE_REASONS, reason
    return {"state": "no", "reason": reason, "detail": detail, **extra}


def _key(subject_sha256: str, dpi: int) -> str:
    return f"{subject_sha256[:16]}-{int(dpi)}dpi"


def existing_own(session, *, subject_sha256: str, dpi: int) -> dict | None:
    """A tier-3 render of THESE bytes at THIS dpi, or nothing.

    Bound the way ``rt_convert.existing_pdf`` binds a prepared PDF, and for the
    same reason. A root is a directory other things can touch.
    """
    renders = (session.meta or {}).get("ownRenders")
    if not isinstance(renders, dict):
        return None
    record = renders.get(_key(subject_sha256, dpi))
    if not isinstance(record, dict):
        return None
    if record.get("subjectSha256") != subject_sha256:
        return None
    sidecar_path = session.dir / str(record.get("sidecar") or "")
    if not sidecar_path.is_file():
        return None
    pages = record.get("pages")
    if not isinstance(pages, list) or not pages:
        return None
    directory = session.dir / str(record.get("dir") or "")
    for name in pages:
        if not (directory / str(name)).is_file():
            return None
    return dict(record)


def read_sidecar(session, record: dict) -> dict:
    path = session.dir / str(record.get("sidecar") or "")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RpcError("render_failed",
                       "the own renderer's sidecar could not be read",
                       detail=f"{type(exc).__name__}: {exc}"[:400]) from exc


def _write_record(session, key: str, record: dict) -> None:
    renders = session.meta.get("ownRenders")
    if not isinstance(renders, dict):
        renders = {}
    renders[key] = record
    session.meta["ownRenders"] = renders
    atomic_write_bytes(
        session.meta_path,
        json.dumps(session.meta, ensure_ascii=False, indent=2,
                   sort_keys=True, allow_nan=False).encode("utf-8"))


def run_own_render(tools, subject: Path, out_dir: Path, *, dpi: int,
                   timeout: float = OWN_RENDER_TIMEOUT_SECONDS) -> dict:
    """One bounded ``own_render.py`` child. Substituted wholesale in tests."""
    script = own_render_script(tools)
    argv = [child_python(), str(script), str(subject),
            "--out-dir", str(out_dir), "--dpi", str(int(dpi)), "--stem", "own"]
    result = run_child(argv, timeout=timeout)
    return {
        "argv": ["own_render.py"],
        "exitCode": result.returncode,
        "timedOut": result.timed_out,
        "stdout": result.text[:4000],
        "stderr": result.stderr.decode("utf-8", errors="replace")[:4000],
    }


def own_render(session, tools, *, subject: Path, subject_sha256: str,
               dpi: int) -> tuple[dict | None, dict | None]:
    """``(record, refusal)`` — never both, never neither.

    The refusal is a plain dict from :func:`own_unavailable`, not an exception,
    because "the third tier could not draw this either" is an ANSWER the page
    view has to show next to the first two tiers' reasons. An exception here
    would replace three honest sentences with one error toast.
    """
    script = own_render_script(tools)
    if not script.is_file():
        return None, own_unavailable(
            "script_missing",
            "engine/scripts/own_render.py is not in this install, so there is "
            "no renderer of our own to fall back to")
    if subject.suffix.lower() not in OWN_RENDERABLE_SUFFIXES:
        return None, own_unavailable(
            "not_own_renderable",
            f"our own renderer reads {', '.join(OWN_RENDERABLE_SUFFIXES)}; this "
            f"subject is {subject.suffix.lower() or 'extensionless'}",
            suffix=subject.suffix.lower())

    cached = existing_own(session, subject_sha256=subject_sha256, dpi=dpi)
    if cached is not None:
        return cached, None

    key = _key(subject_sha256, dpi)
    out_dir = session.dir / OWN_DIRNAME / key
    out_dir.mkdir(parents=True, exist_ok=True)
    outcome = run_own_render(tools, subject, out_dir, dpi=dpi)

    if outcome["timedOut"]:
        return None, own_unavailable(
            "render_failed",
            f"our own renderer did not finish within "
            f"{OWN_RENDER_TIMEOUT_SECONDS:.0f}s",
            timedOut=True, exitCode=outcome["exitCode"],
            stderr=outcome["stderr"][-1200:])
    # Exit 3 is the renderer's own ``RendererUnavailable`` — Pillow absent, or
    # no usable font on this machine. A different state from a crash, and the
    # user can do something about exactly one of them.
    if outcome["exitCode"] == 3:
        return None, own_unavailable(
            "renderer_unavailable",
            (outcome["stderr"].strip().splitlines() or
             ["our own renderer reported that it cannot run here"])[-1][:400],
            exitCode=3)
    sidecar_path = out_dir / "own.render.json"
    if outcome["exitCode"] != 0 or not sidecar_path.is_file():
        return None, own_unavailable(
            "render_failed",
            f"our own renderer exited {outcome['exitCode']} and left no page",
            exitCode=outcome["exitCode"], stderr=outcome["stderr"][-1200:])

    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, own_unavailable(
            "render_failed", f"the renderer's sidecar is unreadable: {exc}"[:400])
    pages = [str(name) for name in (sidecar.get("png_pages") or [])]
    if not pages or not all((out_dir / name).is_file() for name in pages):
        return None, own_unavailable(
            "render_failed",
            "the renderer reported pages that are not on disk",
            pages=pages)
    # The drift guard promised in the module docstring: if the engine ever
    # changes its grade word, a page stops being served rather than being
    # served under a label this module invented.
    if sidecar.get("grade") != OWN_GRADE:
        return None, own_unavailable(
            "render_failed",
            f"the renderer graded this page {sidecar.get('grade')!r}; this "
            f"build only serves {OWN_GRADE!r}",
            grade=sidecar.get("grade"))

    record = {
        "dir": f"{OWN_DIRNAME}/{key}",
        "sidecar": f"{OWN_DIRNAME}/{key}/own.render.json",
        "pages": pages,
        "dpi": int(dpi),
        "subjectSha256": subject_sha256,
        "producedBy": "engine/scripts/own_render.py",
        "producedUtc": now_utc(),
        "renderer": sidecar.get("renderer"),
        "rendererVersion": sidecar.get("renderer_version"),
        "grade": OWN_GRADE,
    }
    _write_record(session, key, record)
    return record, None


def font_summary(sidecar: dict) -> dict:
    """The substitution story, small enough to put in a badge tooltip.

    ``faces`` is kept whole for the ones that were SUBSTITUTED only: a person
    wants to know which typeface they are not looking at, and the resolved
    faces are the uninteresting majority.
    """
    fonts = sidecar.get("fonts")
    if not isinstance(fonts, dict):
        return {"state": "unavailable",
                "reason": "this render's sidecar carries no font report"}
    faces = fonts.get("faces") if isinstance(fonts.get("faces"), list) else []
    substituted = [f for f in faces if isinstance(f, dict) and not f.get("resolved")]
    return {
        "state": "read",
        "charactersResolved": fonts.get("characters_on_a_resolved_face"),
        "charactersSubstituted": fonts.get("characters_on_a_substituted_face"),
        "facesTotal": len(faces),
        "facesSubstituted": len(substituted),
        "substituted": [
            {"declared": f.get("declared"), "drawnWith": f.get("installed_family"),
             "slot": f.get("slot"), "characters": f.get("characters")}
            for f in substituted
        ],
    }


def elements_skipped(sidecar: dict) -> list:
    """Verbatim. Not summarised, not deduplicated, not sorted differently."""
    skipped = sidecar.get("elements_skipped")
    return skipped if isinstance(skipped, list) else []


def page_png(session, record: dict, page: int) -> Path | None:
    """The 0-based ``page``'s PNG, or None when the render drew fewer."""
    pages = record.get("pages") or []
    if page < 0 or page >= len(pages):
        return None
    return session.dir / str(record["dir"]) / str(pages[page])


def sidecar_page_size(sidecar: dict, page: int) -> tuple[int, int] | None:
    """Page size in device px for a 0-based page.

    Per-section where the sidecar carries sections (a document may change paper
    mid-way and the top-level pair is only section 0's), falling back to the
    top-level pair for a sidecar written before sections were emitted.
    """
    sections = sidecar.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            span = section.get("pages")
            size = section.get("page_size_px")
            if (isinstance(span, list) and len(span) == 2
                    and isinstance(size, list) and len(size) == 2
                    and int(span[0]) <= page + 1 <= int(span[1])):
                return int(size[0]), int(size[1])
    size = sidecar.get("page_size_px")
    if isinstance(size, list) and len(size) == 2:
        return int(size[0]), int(size[1])
    return None


def line_boxes_for_page(sidecar: dict, page: int) -> list:
    """The 0-based ``page``'s line boxes, in the sidecar's own order.

    The sidecar numbers pages from 1 (it is a human-facing report); the wire
    numbers them from 0. The conversion happens here, once.
    """
    boxes = sidecar.get("line_boxes")
    if not isinstance(boxes, list):
        return []
    return [box for box in boxes
            if isinstance(box, dict) and int(box.get("page") or 0) == page + 1]
