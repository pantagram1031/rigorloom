#!/usr/bin/env python3
"""pipeline_ctl.py — state-machine CLI enforcement layer for report-pipeline.

Implements CONTRACT_v0.4.md sections 2-3 as executable code instead of prose
rules. Stdlib only (no pyyaml) — the PIPELINE.md YAML header is a constrained
subset (flat top-level keys + a `stages:` map of inline dicts) and is parsed
and rewritten by hand, matching studio/main.py's reader.

Every subcommand prints exactly one JSON object to stdout.
Exit codes: 0 = ok, 1 = refusal / contract violation, 2 = usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def _reexec_utf8_if_needed() -> None:
    """On Windows, a non-UTF-8 console codepage (e.g. cp949) can cause CPython
    to decode sys.argv with the wrong codec, silently mangling non-ASCII args
    (Korean topics, etc.) before the script ever sees them. Python's UTF-8
    mode (PEP 540) fixes this at the interpreter level. If it isn't already
    active, relaunch ourselves once with it forced on. (os.execv is unreliable
    here: Windows has no real exec(), and CPython's emulation can lose the
    child's stdio under some shells/ptys — a plain subprocess relaunch is
    safer.)

    Must only run when this module is executed as the CLI entry point (see
    `if __name__ == "__main__":` at the bottom) — importing pipeline_ctl as a
    library (e.g. from tests or studio/main.py) must never spawn a subprocess
    or call sys.exit() as a side effect of the import.
    """
    if sys.platform == "win32" and sys.flags.utf8_mode == 0 and os.environ.get("_PIPELINE_CTL_UTF8_REEXEC") != "1":
        import subprocess as _subprocess
        _env = dict(os.environ, _PIPELINE_CTL_UTF8_REEXEC="1")
        _proc = _subprocess.run(
            [sys.executable, "-X", "utf8", os.path.abspath(__file__), *sys.argv[1:]],
            env=_env,
        )
        sys.exit(_proc.returncode)

PIPELINE_VERSION = "0.6"


class StagesConfigError(Exception):
    """Raised when references/stages.yaml is missing or unparsable.

    The stage graph has NO embedded fallback: a broken or absent config is a
    hard error, never a silent default. A wrong stage graph could quietly drop
    a gate (e.g. a script gate) and let a run sail past it, so the CLI refuses
    to operate on a graph it cannot trust."""


STATUS_ENUM = {"pending", "in_progress", "awaiting_gate", "done", "blocked"}
GATE_ENUM = {"pending", "approved", "auto_approved", "rejected"}
MODE_ENUM = {"autonomous", "supervised", "night"}


# ── stages.yaml config loader ───────────────────────────────────────
#
# stages.yaml is a flat YAML list of inline-map records:
#   - {id: "2.5", name: "layout_plan", gate: {name: "layout", type: "script", checker: null}, playbook: "..."}
#   - {id: "3",   name: "sim",         gate: {name: "sane",  type: "script",
#        checker: ["python", "{WS}/sim/gates.py"]}, playbook: "..."}
# Parsed by hand (stdlib only, no pyyaml), reusing the same inline-map helpers
# as the PIPELINE.md header parser below. Gate `checker` is an argv ARRAY (never
# a shell string). A missing or unparsable file is a HARD ERROR — there is no
# embedded fallback stage graph (a silently-wrong graph could drop a gate).

_STAGE_ROW_RE = re.compile(r"^\s*-\s*\{(.*)\}\s*$")


def _split_top_commas(s: str) -> list:
    """Split `s` on top-level commas only: commas inside {..}, [..], or quotes
    do not split. Quote-aware so a `{`/`}` or `[`/`]` inside a quoted scalar
    (e.g. the placeholder "{WS}") never perturbs nesting depth."""
    parts = []
    buf = []
    depth = 0
    quote = None
    esc = False
    for ch in s:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and quote == '"':
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "{[":
            depth += 1
            buf.append(ch)
        elif ch in "}]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_scalar_or_container(v: str):
    """Parse a single YAML inline value: nested map {..}, array [..], null, or
    quoted/plain scalar."""
    v = v.strip()
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1]
        if inner.strip() in ("", "null", "~"):
            return None
        return _parse_inline_map_nested(inner)
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        return [_strip_q(it.strip()) for it in _split_top_commas(inner) if it.strip() != ""]
    if v in ("null", "~", ""):
        return None
    return _strip_q(v)


def _parse_inline_map_nested(s: str) -> dict:
    """Parse an inline map, tolerating nested {..} maps and [..] arrays as
    values (e.g. gate: {name: sane, type: script, checker: ["python", "..."]}).
    Splits top-level commas only.

    STRICT (stage-graph path): a top-level part without a ':' key/value
    separator is a HARD ERROR, never a silent skip. Silently dropping a
    colon-less part (e.g. a row where 'gate {name: ...}' is missing the colon
    after 'gate') would let malformed content parse into a bogus key and the
    stage silently lose its gate. This helper feeds both the stage list and
    nested gate values, so raising here protects both. The tolerant PIPELINE.md
    header parser uses the SEPARATE `_parse_inline_map` (workspace state, not the
    stage graph)."""
    out_map = {}
    for part in _split_top_commas(s):
        if part.strip() == "":
            continue
        if ":" not in part:
            raise StagesConfigError(
                f"inline map part has no ':' key/value separator: {part.strip()!r}")
        k, v = part.split(":", 1)
        out_map[k.strip()] = _parse_scalar_or_container(v)
    return out_map


_ALLOWED_STAGE_KEYS = {"id", "name", "gate", "playbook"}


def _validate_stage_row(rec: dict, line: str, seen_ids: set, seen_gate_names: set) -> None:
    """STRICT per-row validation. Raises StagesConfigError on any violation:
    unexpected top-level key, missing 'gate' key, missing required field
    (id/name/playbook), duplicate id, malformed gate (must be null or
    {name, type[, checker]}), gate type not in {script,human}, unexpected gate
    key, or duplicate gate name."""
    for key in rec:
        if key not in _ALLOWED_STAGE_KEYS:
            raise StagesConfigError(
                f"stages.yaml row has unexpected top-level key {key!r} "
                f"(allowed: id, name, gate, playbook): {line!r}")
    # 'gate' MUST be present explicitly (gate: null is allowed for a gate-less
    # stage). A row with NO gate key is a hard error, not an implicit gate:null —
    # otherwise a malformed row that lost its 'gate' key (see the missing-colon
    # probe) would silently become gate-less.
    if "gate" not in rec:
        raise StagesConfigError(
            f"stages.yaml row missing required 'gate' key "
            f"(use 'gate: null' for a gate-less stage): {line!r}")
    for req in ("id", "name", "playbook"):
        if req not in rec or rec.get(req) in (None, ""):
            raise StagesConfigError(
                f"stages.yaml row missing required field {req!r}: {line!r}")
    sid = str(rec["id"])
    if sid in seen_ids:
        raise StagesConfigError(f"stages.yaml duplicate stage id {sid!r}: {line!r}")
    seen_ids.add(sid)
    gate = rec.get("gate")
    if gate is None:
        return
    if not isinstance(gate, dict):
        raise StagesConfigError(f"stages.yaml gate must be null or a map: {line!r}")
    for key in gate:
        if key not in ("name", "type", "checker"):
            raise StagesConfigError(
                f"stages.yaml gate has unexpected key {key!r} "
                f"(allowed: name, type, checker): {line!r}")
    gname = gate.get("name")
    if not gname:
        raise StagesConfigError(f"stages.yaml gate missing 'name': {line!r}")
    gtype = gate.get("type")
    if gtype not in ("script", "human"):
        raise StagesConfigError(
            f"stages.yaml gate 'type' must be 'script' or 'human' "
            f"(got {gtype!r}): {line!r}")
    if gname in seen_gate_names:
        raise StagesConfigError(f"stages.yaml duplicate gate name {gname!r}: {line!r}")
    seen_gate_names.add(gname)


def _parse_stages_yaml_text(text: str) -> list:
    """Parse the flat `stages:` list in stages.yaml with STRICT validation.

    Every non-comment, non-blank line INSIDE the stages list must parse as a
    `- {...}` inline-map stage row — a line that fails to match is a hard error,
    never a silent skip (a dropped row could silently drop a gate). Each row is
    validated for required fields, gate shape, and id/gate-name uniqueness.
    Raises StagesConfigError on any malformed / empty input (no fallback)."""
    rows = []
    seen_ids: set = set()
    seen_gate_names: set = set()
    in_stages = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^stages:\s*$", line):
            in_stages = True
            continue
        if not in_stages:
            # Tolerate flat top-level scalar keys (e.g. `version: "0.6"`) that
            # precede the stages list; anything else up here is malformed.
            if re.match(r'^[A-Za-z_][\w-]*:\s', line) or re.match(r'^[A-Za-z_][\w-]*:$', line):
                continue
            raise StagesConfigError(
                f"stages.yaml: unexpected line before 'stages:': {line!r}")
        m = _STAGE_ROW_RE.match(line)
        if not m:
            raise StagesConfigError(
                f"stages.yaml: malformed stage row "
                f"(expected '- {{...}}' inline map): {line!r}")
        inner = m.group(1)
        rec = _parse_inline_map_nested(inner)
        _validate_stage_row(rec, line, seen_ids, seen_gate_names)
        rows.append(rec)
    if not rows:
        raise StagesConfigError("stages.yaml has no stage rows")
    return rows


def load_stages_config(script_path: Path = None) -> list:
    """Return the stage list (each: {id, name, gate, playbook}) loaded from
    references/stages.yaml relative to this script.

    HARD ERROR: if the file is missing or unparsable, raise StagesConfigError.
    There is no embedded fallback — the CLI must never operate on a silently
    substituted stage graph."""
    base = Path(script_path) if script_path else Path(__file__).resolve()
    cfg_path = base.parent.parent / "references" / "stages.yaml"
    if not cfg_path.exists():
        raise StagesConfigError(f"stages.yaml not found at {cfg_path}")
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise StagesConfigError(f"stages.yaml unreadable ({cfg_path}): {exc}")
    try:
        return _parse_stages_yaml_text(text)
    except StagesConfigError:
        raise
    except Exception as exc:
        raise StagesConfigError(f"stages.yaml unparsable ({cfg_path}): {exc}")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _print_json(obj: dict) -> None:
    # Windows consoles often default to a non-UTF-8 codepage (e.g. cp949);
    # force UTF-8 bytes on stdout so non-ASCII (Korean topics, etc.) never
    # raises UnicodeEncodeError.
    data = json.dumps(obj, ensure_ascii=False) + "\n"
    try:
        sys.stdout.write(data)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(data.encode("utf-8"))
    sys.stdout.flush()


def out(obj: dict, code: int = 0) -> None:
    _print_json(obj)
    sys.exit(code)


def fail(error: str, **extra) -> None:
    out({"ok": False, "error": error, **extra}, 1)


def usage_error(msg: str) -> None:
    _print_json({"ok": False, "error": msg})
    sys.exit(2)


# ── YAML header parse (kept compatible with studio/main.py) ────────────

_YAML_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.S)


def _escape_dq(s: str) -> str:
    """Escape a scalar for embedding inside a double-quoted YAML string.
    Backslash must be escaped first so a literal '\\' in the input doesn't
    get mistaken for (or collide with) the escape we add for '"'."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _unescape_dq(s: str) -> str:
    """Inverse of _escape_dq: unescape \\" -> " and \\\\ -> \\."""
    out_chars = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in ('"', "\\"):
            out_chars.append(s[i + 1])
            i += 2
        else:
            out_chars.append(s[i])
            i += 1
    return "".join(out_chars)


def _strip_q(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        if s[0] == '"':
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return _unescape_dq(s[1:-1])
        return s[1:-1]
    return s


def _strip_inline_comment(s: str) -> str:
    """Remove a YAML-style inline comment without cutting quoted text."""
    quote = None
    escaped = False
    for index, char in enumerate(s):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in "\"'":
            quote = None if quote == char else char if quote is None else quote
            continue
        if char == "#" and quote is None and index > 0 and s[index - 1].isspace():
            return s[:index].rstrip()
    return s.strip()


def _quote_if_needed(s: str) -> str:
    """Quote a scalar for YAML output if it contains ':' or non-ascii-safe
    characters that would otherwise need quoting, or is empty."""
    if s == "":
        return '""'
    if re.search(r"[:#]", s) or s != s.strip():
        return '"' + _escape_dq(s) + '"'
    return s


def _parse_inline_map(s: str) -> dict:
    s = s.strip()
    if s in ("", "null", "~", "{}"):
        return {}
    if s.startswith("{"):
        s = s[1:]
    if s.endswith("}"):
        s = s[:-1]
    out_map = {}
    for part in s.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out_map[k.strip()] = _strip_q(v)
    return out_map


# ── module-level stage-graph derivation ─────────────────────────────
#
# Loaded once at import. A broken/absent stages.yaml is a HARD ERROR, but the
# error is captured here (not raised at import) so `import pipeline_ctl` stays
# side-effect-free; main() surfaces it as a clean JSON hard error + nonzero
# exit before dispatching any subcommand.
try:
    _STAGES_CONFIG = load_stages_config()
    _STAGES_CONFIG_ERROR = None
except StagesConfigError as _cfg_exc:
    _STAGES_CONFIG = None
    _STAGES_CONFIG_ERROR = str(_cfg_exc)

if _STAGES_CONFIG is not None:
    # STAGE_ORDER: ids in config file order (drives resume/advance/invalidate
    # iteration). STAGE_GATE_NAMES: id -> gate name. STAGE_GATE_TYPES: id ->
    # gate type. STAGE_GATE_TYPES_BY_NAME: gate name -> type (used when only a
    # gate name is available, e.g. from a header record without a type field).
    STAGE_ORDER = [str(r["id"]) for r in _STAGES_CONFIG]
    STAGE_GATE_NAMES = {
        str(r["id"]): r["gate"]["name"]
        for r in _STAGES_CONFIG if r.get("gate")
    }
    STAGE_GATE_TYPES = {
        str(r["id"]): r["gate"].get("type", "human")
        for r in _STAGES_CONFIG if r.get("gate")
    }
    STAGE_GATE_TYPES_BY_NAME = {
        r["gate"]["name"]: r["gate"].get("type", "human")
        for r in _STAGES_CONFIG if r.get("gate")
    }
else:
    STAGE_ORDER = []
    STAGE_GATE_NAMES = {}
    STAGE_GATE_TYPES = {}
    STAGE_GATE_TYPES_BY_NAME = {}


def find_yaml_fence(text: str):
    """Return (start, end, body) span of the first ```yaml fence whose
    first non-empty line declares `# pipeline-state: v0.4`, else None.
    start/end are character offsets of the fence markers themselves
    (the ``` lines), so callers can splice the whole block including the
    fence markers.
    """
    for m in re.finditer(r"```ya?ml\s*\n(.*?)\n```", text, re.S):
        body = m.group(1)
        first_line = None
        for line in body.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if first_line and re.match(r"#\s*pipeline-state:\s*v0\.4", first_line):
            return m.start(), m.end(), body
    return None


def parse_yaml_header(body: str) -> dict:
    top: dict = {}
    stages: dict = {}
    in_stages = False
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^stages:\s*$", line):
            in_stages = True
            continue
        if in_stages and re.match(r"^\s+", line):
            m = re.match(r'^\s+"?([\d.]+)"?\s*:\s*(.*)$', line)
            if m:
                num = m.group(1)
                inner = _parse_inline_map(m.group(2))
                status = inner.get("status", "pending")
                if status not in STATUS_ENUM:
                    status = "pending"
                gate_raw = m.group(2)
                gm = re.search(r"gate\s*:\s*(\{[^}]*\}|null|~)", gate_raw)
                gate = None
                if gm and gm.group(1) not in ("null", "~"):
                    gm2 = _parse_inline_map(gm.group(1))
                    gstate = gm2.get("state", "pending")
                    if gstate not in GATE_ENUM:
                        gstate = "pending"
                    gate = {
                        "name": gm2.get("name", ""),
                        "state": gstate,
                        "by": gm2.get("by") or None,
                        "at": gm2.get("at") or None,
                    }
                stages[num] = {"status": status, "gate": gate}
            continue
        in_stages = False
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            top[m.group(1)] = _strip_q(_strip_inline_comment(m.group(2)))
    top["stages"] = stages
    return top


def render_gate(gate) -> str:
    if not gate:
        return "null"
    name = gate.get("name", "")
    state = gate.get("state", "pending")
    by = gate.get("by")
    at = gate.get("at")
    by_s = by if by else "null"
    at_s = at if at else "null"
    return "{name: %s, state: %s, by: %s, at: %s}" % (name, state, by_s, at_s)


def render_yaml_body(hdr: dict) -> str:
    """Render the full header dict back into the fenced-block body text
    (without the ``` markers), matching CONTRACT §2 layout."""
    # NOTE: the `# pipeline-state: v0.4` fence marker is a compatibility
    # anchor read verbatim by studio/main.py's independent hand-rolled
    # parser (out of scope for this change) — it must never be renamed.
    # `pipeline_version` is a separate top-level field carrying the actual
    # stages.yaml schema version (v0.6+), read by pipeline_ctl.py only.
    lines = ["# pipeline-state: v0.4"]
    top_keys = ["pipeline_version", "slug", "mode", "subject", "topic", "form",
                "updated", "canonical_output"]
    for k in top_keys:
        if k not in hdr:
            continue
        v = hdr[k]
        if v in (None, ""):
            if k == "canonical_output":
                lines.append(f"{k}: null")
            else:
                lines.append(f"{k}: {_quote_if_needed('')}")
            continue
        lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    lines.append("stages:")
    stages = hdr.get("stages", {})
    for num in STAGE_ORDER:
        if num not in stages:
            continue
        st = stages[num]
        status = st.get("status", "pending")
        gate = st.get("gate")
        lines.append(f'  "{num}":   {{status: {status}, gate: {render_gate(gate)}}}')
    return "\n".join(lines)


# ── workspace helpers ────────────────────────────────────────────────

def pipeline_path(ws: Path) -> Path:
    return ws / "PIPELINE.md"


def load_header(ws: Path):
    """Return (full_text, fence_start, fence_end, header_dict) or None if
    PIPELINE.md is missing or has no v0.4 fence."""
    f = pipeline_path(ws)
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    span = find_yaml_fence(text)
    if span is None:
        return None
    start, end, body = span
    hdr = parse_yaml_header(body)
    return text, start, end, hdr


def save_header(ws: Path, text: str, start: int, end: int, hdr: dict) -> None:
    """Rewrite only the YAML fence span, preserving everything before and
    after (in particular the human-readable table after the closing fence)."""
    new_body = render_yaml_body(hdr)
    new_fence = "```yaml\n" + new_body + "\n```"
    new_text = text[:start] + new_fence + text[end:]
    pipeline_path(ws).write_text(new_text, encoding="utf-8")


def append_event(ws: Path, ev_type: str, stage: str | None, detail: str) -> None:
    ev = {"ts": now_iso(), "type": ev_type, "stage": stage, "detail": detail}
    events_path = ws / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def write_heartbeat(ws: Path) -> None:
    (ws / "heartbeat").write_text(now_iso(), encoding="utf-8")


def refresh_handoff(
    ws: Path,
    hdr: dict,
    completed_stage: str | None = None,
    archive_transients: bool = False,
) -> None:
    """Refresh derived handoff files without weakening state enforcement."""
    try:
        from workspace_organizer import organize_workspace
        organize_workspace(
            ws, hdr, STAGE_ORDER,
            completed_stage=completed_stage,
            archive_transients=archive_transients,
        )
    except Exception as exc:
        append_event(ws, "organize_warning", completed_stage, str(exc))


def _gate_type_for(stage_id: str, gate_name: str) -> str:
    """Resolve a gate's declared type ("script" | "human") from the stage
    graph. Prefer the stage-id binding; fall back to name lookup; default to
    "human" for an unknown gate (the conservative choice — human gates only
    block supervised, so an unknown gate never over-blocks night/autonomous)."""
    return (
        STAGE_GATE_TYPES.get(stage_id)
        or STAGE_GATE_TYPES_BY_NAME.get(gate_name)
        or "human"
    )


def stage_gate_blocks(hdr: dict, stage: str, mode: str):
    """Check whether an EARLIER-ordered stage's gate blocks starting `stage`.
    Returns (blocked: bool, reason: str|None).

    - A `rejected` predecessor gate blocks in ALL modes.
    - A `pending` predecessor SCRIPT gate blocks in ALL modes (night/autonomous
      must not sail past an unresolved deterministic checker).
    - A `pending` predecessor HUMAN gate blocks only in supervised mode
      (night/autonomous record auto_approved via the `gate` subcommand)."""
    stages = hdr.get("stages", {})
    try:
        idx = STAGE_ORDER.index(stage)
    except ValueError:
        return False, None
    for earlier in STAGE_ORDER[:idx]:
        st = stages.get(earlier)
        if not st:
            continue
        gate = st.get("gate")
        if not gate:
            continue
        gname = gate.get("name")
        gstate = gate.get("state")
        if gstate == "rejected":
            return True, f"predecessor stage {earlier} gate '{gname}' is rejected"
        if gstate == "pending":
            gtype = _gate_type_for(earlier, gname)
            if gtype == "script":
                return True, (f"predecessor stage {earlier} script gate '{gname}' "
                              f"is pending (blocks all modes — run: check)")
            if mode == "supervised":
                return True, f"predecessor stage {earlier} gate '{gname}' is pending (supervised)"
    return False, None


# ── subcommands ─────────────────────────────────────────────────────

def cmd_resume(args) -> None:
    ws = Path(args.workspace)
    loaded = load_header(ws)
    if loaded is None:
        fail("PIPELINE.md missing or has no v0.4 header", workspace=str(ws))
        return
    text, start, end, hdr = loaded
    mode = hdr.get("mode", "autonomous")
    stages = hdr.get("stages", {})

    resume_stage = None
    for num in STAGE_ORDER:
        st = stages.get(num)
        if not st:
            continue
        if st["status"] in ("pending", "in_progress", "awaiting_gate"):
            resume_stage = num
            break

    if resume_stage is None:
        out({"ok": True, "next_stage": None, "reason": "all stages done",
             "mode": mode, "blocked": False})
        return

    st = stages[resume_stage]
    status = st["status"]
    gate = st.get("gate")

    # blocked by a rejected/pending predecessor gate
    blocked, reason = stage_gate_blocks(hdr, resume_stage, mode)
    if blocked:
        out({"ok": True, "next_stage": resume_stage, "reason": reason,
             "mode": mode, "blocked": True})
        return

    if status == "awaiting_gate" and gate:
        gstate = gate.get("state")
        if gstate == "rejected":
            out({"ok": True, "next_stage": resume_stage,
                 "reason": f"gate '{gate.get('name')}' rejected",
                 "mode": mode, "blocked": True,
                 "gate": gate})
            return
        if mode == "supervised":
            if gstate == "pending":
                out({"ok": True, "next_stage": resume_stage,
                     "reason": f"awaiting_gate: '{gate.get('name')}' pending human approval",
                     "mode": mode, "blocked": True, "gate": gate})
                return
            # already approved/auto_approved but stage not advanced yet
            out({"ok": True, "next_stage": resume_stage,
                 "reason": f"gate '{gate.get('name')}' resolved ({gstate}); ready to advance",
                 "mode": mode, "blocked": False, "gate": gate})
            return
        # autonomous / night
        if gstate == "pending":
            gtype = _gate_type_for(resume_stage, gate.get("name"))
            if gtype == "script":
                # A pending SCRIPT gate must be resolved by RUNNING its checker
                # (`check`), never auto_approved — so night/autonomous is blocked
                # until the deterministic verdict is produced.
                out({"ok": True, "next_stage": resume_stage,
                     "reason": (f"gate '{gate.get('name')}' is a pending script gate; "
                                f"run: check <workspace> {gate.get('name')}"),
                     "mode": mode, "blocked": True, "gate": gate,
                     "action_needed": "check"})
                return
            out({"ok": True, "next_stage": resume_stage,
                 "reason": f"gate '{gate.get('name')}' needs auto_approved recording",
                 "mode": mode, "blocked": False, "gate": gate,
                 "action_needed": "gate"})
            return
        out({"ok": True, "next_stage": resume_stage,
             "reason": f"gate '{gate.get('name')}' resolved ({gstate}); ready to advance",
             "mode": mode, "blocked": False, "gate": gate})
        return

    out({"ok": True, "next_stage": resume_stage, "reason": "first pending",
         "mode": mode, "blocked": False})


def cmd_gate(args) -> None:
    ws = Path(args.workspace)
    gate_name = args.gate_name
    mode = args.mode
    # --script-exit is RETIRED: a caller-supplied exit code let a gate be
    # auto_approved/rejected with no checker ever run (defect). Script gates are
    # now resolved only by the `check` subcommand, which RUNS the bound checker
    # itself and records provenance. The flag stays registered so old callers
    # get a clear redirect instead of an argparse "unrecognized argument".
    if args.script_exit is not None:
        usage_error("gate --script-exit is retired — use: "
                    "pipeline_ctl.py check <workspace> <gate_name>")
        return
    if mode is None:
        usage_error("gate requires --mode (autonomous|supervised|night)")
        return
    # A SCRIPT gate must NEVER be resolved by `gate` (which would auto_approve
    # it in night/autonomous with no checker ever run). Look up the declared
    # type from the stage graph and refuse — script gates resolve only via
    # `check`, which RUNS the bound checker and records provenance.
    found_cfg, cfg_gate_type, _cfg_checker = _resolve_gate_checker(gate_name)
    if found_cfg and cfg_gate_type == "script":
        usage_error(f"gate '{gate_name}' is a script gate — resolve via: "
                    f"check <workspace> {gate_name}")
        return
    loaded = load_header(ws)
    if loaded is None:
        fail("PIPELINE.md missing or has no v0.4 header", workspace=str(ws))
        return
    text, start, end, hdr = loaded
    stages = hdr.get("stages", {})

    target_num = None
    for num, st in stages.items():
        gate = st.get("gate")
        if gate and gate.get("name") == gate_name:
            target_num = num
            break
    if target_num is None:
        fail(f"no stage has a gate named '{gate_name}'")
        return

    approvals_path = ws / "APPROVALS.md"
    approved_line = None
    rejected_line = None
    if approvals_path.exists():
        approvals_text = approvals_path.read_text(encoding="utf-8")
        for line in approvals_text.splitlines():
            m = re.match(rf"^{re.escape(gate_name)}:\s*approved\b(.*)$", line.strip())
            if m:
                approved_line = m.group(0)
                continue
            m2 = re.match(rf"^{re.escape(gate_name)}:\s*rejected\b(.*)$", line.strip())
            if m2:
                rejected_line = m2

    stages_ref = hdr["stages"]
    gate_obj = stages_ref[target_num]["gate"]

    if rejected_line:
        reason = rejected_line.group(1).strip(" :,-")
        gate_obj["state"] = "rejected"
        gate_obj["by"] = "operator"
        gate_obj["at"] = now_iso()
        save_header(ws, text, start, end, hdr)
        append_event(ws, "gate", target_num, f"gate '{gate_name}' rejected: {reason}")
        write_heartbeat(ws)
        refresh_handoff(ws, hdr)
        out({"ok": True, "gate": gate_name, "state": "rejected",
             "stage": target_num, "reason": reason})
        return

    if approved_line:
        # Accept both documented `at=<ISO>` and legacy `at <ISO>` records.
        ts_m = re.search(r"\bat(?:=|\s+)(\S+)", approved_line)
        at_val = ts_m.group(1) if ts_m else now_iso()
        gate_obj["state"] = "approved"
        gate_obj["by"] = "operator"
        gate_obj["at"] = at_val
        save_header(ws, text, start, end, hdr)
        append_event(ws, "gate", target_num, f"gate '{gate_name}' approved by operator")
        write_heartbeat(ws)
        refresh_handoff(ws, hdr)
        out({"ok": True, "gate": gate_name, "state": "approved",
             "stage": target_num, "by": "operator", "at": at_val})
        return

    # no matching line in APPROVALS.md
    if mode == "supervised":
        fail("gate pending; human must edit APPROVALS.md",
             gate=gate_name, stage=target_num)
        return

    # autonomous / night: record auto_approved
    gate_obj["state"] = "auto_approved"
    gate_obj["by"] = mode
    gate_obj["at"] = now_iso()
    save_header(ws, text, start, end, hdr)
    append_event(ws, "gate", target_num, f"gate '{gate_name}' auto_approved ({mode})")
    write_heartbeat(ws)
    refresh_handoff(ws, hdr)
    out({"ok": True, "gate": gate_name, "state": "auto_approved",
         "stage": target_num, "by": mode, "at": gate_obj["at"]})


def _resolve_gate_checker(gate_name: str):
    """Look up a gate's declared type + checker argv template from the stage
    graph. Returns (found, gate_type, checker) where checker is the argv list
    or None. `found` is False when no gate by that name exists."""
    for st_cfg in _STAGES_CONFIG or []:
        cfg_gate = st_cfg.get("gate")
        if cfg_gate and cfg_gate.get("name") == gate_name:
            return True, cfg_gate.get("type"), cfg_gate.get("checker")
    return False, None, None


def _substitute_checker_argv(checker: list, ws: Path) -> list:
    """Substitute {WS} and {PIPELINE_SCRIPTS} placeholders in each argv token.
    {WS} = workspace absolute path; {PIPELINE_SCRIPTS} = this script's dir."""
    ws_abs = str(ws.resolve())
    scripts_dir = str(Path(__file__).resolve().parent)
    argv = []
    for tok in checker:
        s = str(tok).replace("{WS}", ws_abs).replace("{PIPELINE_SCRIPTS}", scripts_dir)
        argv.append(s)
    return argv


def _append_gate_check_receipt(ws: Path, gate_name: str, stage: str,
                               provenance: dict, exit_code: int) -> None:
    """Append the check provenance to <ws>/.pipeline/gate_checks.jsonl. The
    PIPELINE.md header gate scalar stays name/state/by/at (a compat contract
    read verbatim by studio/main.py), so full provenance lives in this audit
    trail + the emitted JSON + events.jsonl."""
    try:
        d = ws / ".pipeline"
        d.mkdir(parents=True, exist_ok=True)
        rec = {"ts": provenance.get("checked_at"), "gate": gate_name,
               "stage": stage, "exit": exit_code, **provenance}
        with (d / "gate_checks.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cmd_check(args) -> None:
    """Resolve a SCRIPT gate by RUNNING its bound checker (from stages.yaml).

    exit 0  -> auto_approved (detail "checker")
    nonzero -> rejected (reason includes the exit code)
    Records provenance {checker_argv, exit, stdout_sha256, checked_at} into the
    emitted JSON, events.jsonl, and .pipeline/gate_checks.jsonl. A null/missing
    checker, a non-script gate, or an unknown gate is a usage error — never a
    pass (a gate with no runnable checker must NOT silently auto_approve)."""
    ws = Path(args.workspace)
    gate_name = args.gate_name

    found, gate_type, checker = _resolve_gate_checker(gate_name)
    if not found:
        usage_error(f"check: no gate named '{gate_name}' in stages.yaml")
        return
    if gate_type != "script":
        usage_error(f"check: gate '{gate_name}' is a {gate_type} gate, not a script "
                    f"gate — checkers only run on script gates")
        return
    if not checker:
        usage_error(f"check: gate '{gate_name}' has no checker bound (null) — "
                    f"register a checker argv in stages.yaml before running check")
        return
    if not isinstance(checker, list) or not all(isinstance(t, str) for t in checker):
        usage_error(f"check: gate '{gate_name}' checker must be an argv array of strings")
        return

    loaded = load_header(ws)
    if loaded is None:
        fail("PIPELINE.md missing or has no v0.4 header", workspace=str(ws))
        return
    text, start, end, hdr = loaded
    stages = hdr.get("stages", {})

    target_num = None
    for num, st in stages.items():
        gate = st.get("gate")
        if gate and gate.get("name") == gate_name:
            target_num = num
            break
    if target_num is None:
        fail(f"gate '{gate_name}' not present in this PIPELINE.md header")
        return

    argv = _substitute_checker_argv(checker, ws)
    # Never trust an ambient "python" on PATH — bind the checker's interpreter
    # to the exact interpreter running this CLI (sys.executable) at spawn time.
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=600, env=env)
    except FileNotFoundError as exc:
        fail(f"check: checker not runnable: {exc}", gate=gate_name, checker_argv=argv)
        return
    except subprocess.TimeoutExpired:
        fail("check: checker timed out after 600s", gate=gate_name, checker_argv=argv)
        return

    exit_code = proc.returncode
    stdout_text = proc.stdout or ""
    checked_at = now_iso()
    provenance = {
        "checker_argv": argv,
        "exit": exit_code,
        "stdout_sha256": hashlib.sha256(stdout_text.encode("utf-8", "replace")).hexdigest(),
        "checked_at": checked_at,
    }

    gate_obj = hdr["stages"][target_num]["gate"]
    if exit_code == 0:
        gate_obj["state"] = "auto_approved"
        gate_obj["by"] = "script"
        gate_obj["at"] = checked_at
        save_header(ws, text, start, end, hdr)
        _append_gate_check_receipt(ws, gate_name, target_num, provenance, exit_code)
        append_event(ws, "gate_check", target_num,
                     f"gate '{gate_name}' auto_approved (checker exit 0)")
        write_heartbeat(ws)
        refresh_handoff(ws, hdr)
        out({"ok": True, "gate": gate_name, "state": "auto_approved",
             "stage": target_num, "by": "script", "detail": "checker",
             "at": checked_at, **provenance})
        return

    reason = f"checker exited {exit_code}"
    gate_obj["state"] = "rejected"
    gate_obj["by"] = "script"
    gate_obj["at"] = checked_at
    save_header(ws, text, start, end, hdr)
    _append_gate_check_receipt(ws, gate_name, target_num, provenance, exit_code)
    append_event(ws, "gate_check", target_num,
                 f"gate '{gate_name}' rejected: {reason}")
    write_heartbeat(ws)
    refresh_handoff(ws, hdr)
    out({"ok": True, "gate": gate_name, "state": "rejected",
         "stage": target_num, "reason": reason, "by": "script", **provenance})


# Legal status transitions per CONTRACT §2. `blocked` is reachable from any
# status (safety valve); `done` is terminal — it can only be undone via
# `invalidate`, never by advancing back to an earlier status.
LEGAL_TRANSITIONS = {
    # "done"/"awaiting_gate" are included here (in addition to the CONTRACT
    # §2 in_progress stop) as a pragmatic fast-forward allowance: skipping
    # the explicit in_progress step is not itself a gate bypass since
    # GATE_CHECKED_STATUSES still validates both against predecessor gates
    # below (and awaiting_gate's own gate resolution is handled by resume).
    "pending": {"in_progress", "awaiting_gate", "done", "blocked"},
    "in_progress": {"awaiting_gate", "done", "blocked"},
    "awaiting_gate": {"in_progress", "done", "blocked"},
    "done": set(),
    "blocked": {"in_progress"},
}

# Statuses that move a stage forward and therefore must respect an earlier
# stage's gate. `blocked` is intentionally excluded — it's a safety valve
# that must always be settable regardless of predecessor gate state.
GATE_CHECKED_STATUSES = {"in_progress", "awaiting_gate", "done"}


def cmd_advance(args) -> None:
    ws = Path(args.workspace)
    stage = args.stage
    status = args.status
    reason = args.reason or ""

    if stage not in STAGE_ORDER:
        fail(f"unknown stage '{stage}'; must be one of {STAGE_ORDER}")
        return
    if status not in STATUS_ENUM:
        fail(f"unknown status '{status}'; must be one of {sorted(STATUS_ENUM)}")
        return

    loaded = load_header(ws)
    if loaded is None:
        fail("PIPELINE.md missing or has no v0.4 header", workspace=str(ws))
        return
    text, start, end, hdr = loaded
    mode = hdr.get("mode", "autonomous")
    stages = hdr.get("stages", {})

    if stage not in stages:
        fail(f"stage '{stage}' not present in PIPELINE.md header")
        return

    current_status = stages[stage]["status"]
    if status != current_status:
        legal_targets = LEGAL_TRANSITIONS.get(current_status, set())
        if status not in legal_targets:
            fail(f"illegal transition for stage {stage}: {current_status} -> {status}"
                 f" (legal targets: {sorted(legal_targets) or 'none — use invalidate'})",
                 stage=stage, from_status=current_status, to_status=status)
            return

    if status in GATE_CHECKED_STATUSES:
        blocked, block_reason = stage_gate_blocks(hdr, stage, mode)
        if blocked:
            fail(f"refuse to move stage {stage} to {status}: {block_reason}",
                 stage=stage)
            return

    stages[stage]["status"] = status
    hdr["updated"] = now_iso()
    save_header(ws, text, start, end, hdr)
    detail = f"stage {stage} -> {status}"
    if reason:
        detail += f" ({reason})"
    append_event(ws, "advance", stage, detail)
    write_heartbeat(ws)
    refresh_handoff(
        ws, hdr,
        completed_stage=stage if status in {"done", "blocked"} else None,
        archive_transients=status in {"done", "blocked"},
    )
    out({"ok": True, "stage": stage, "status": status, "reason": reason})


def cmd_invalidate(args) -> None:
    ws = Path(args.workspace)
    from_stage = args.from_stage
    if from_stage not in STAGE_ORDER:
        fail(f"unknown stage '{from_stage}'; must be one of {STAGE_ORDER}")
        return

    loaded = load_header(ws)
    if loaded is None:
        fail("PIPELINE.md missing or has no v0.4 header", workspace=str(ws))
        return
    text, start, end, hdr = loaded
    stages = hdr.get("stages", {})

    idx = STAGE_ORDER.index(from_stage)
    reset_stages = [n for n in STAGE_ORDER[idx:] if n in stages]
    for num in reset_stages:
        st = stages[num]
        st["status"] = "pending"
        gate = st.get("gate")
        if gate:
            gate["state"] = "pending"
            gate["by"] = None
            gate["at"] = None
        try:
            num_idx = STAGE_ORDER.index(num)
        except ValueError:
            num_idx = 999
        if num_idx <= STAGE_ORDER.index("5"):
            hdr["canonical_output"] = None

    hdr["updated"] = now_iso()
    save_header(ws, text, start, end, hdr)
    reason = args.reason or ""
    detail = f"invalidated from stage {from_stage}: {reset_stages}"
    if reason:
        detail += f" ({reason})"
    append_event(ws, "invalidate", from_stage, detail)
    write_heartbeat(ws)
    refresh_handoff(ws, hdr)
    out({"ok": True, "from_stage": from_stage, "reset_stages": reset_stages,
         "reason": reason})


def cmd_trouble(args) -> None:
    ws = Path(args.workspace)
    if not ws.exists():
        fail(f"workspace does not exist: {ws}")
        return

    at = now_iso()
    row = (f"| {at} | {args.stage} | {args.role} | {args.model} | "
           f"{args.failure_class} | {args.evidence} |")
    header = "| at | stage | role | model | failure | evidence |\n" \
             "|---|---|---|---|---|---|"

    # Single open handle in append mode, header decided by f.tell() == 0
    # right after opening — avoids the exists()-then-write TOCTOU race where
    # two concurrent first-writers could both see "missing" and each emit a
    # header. Cross-process locking is out of scope (single orchestrator);
    # this only removes the redundant existence check that widened the race
    # window, it doesn't add a real lock.
    troubles_path = ws / "TROUBLES.md"
    with troubles_path.open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(header + "\n")
        f.write(row + "\n")

    if args.kb_root:
        kb_root = Path(args.kb_root)
    else:
        # Keep run-specific model/provider observations inside the ignored
        # workspace by default. A shared knowledge base is explicit opt-in via
        # --kb-root, preventing private runtime data from appearing in source.
        kb_root = ws / "archive" / "knowledge"
    kb_root.mkdir(parents=True, exist_ok=True)
    model_log_path = kb_root / "model-log.md"
    with model_log_path.open("a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(header + "\n")
        f.write(row + "\n")

    append_event(ws, "trouble", args.stage,
                 f"role={args.role} model={args.model} failure={args.failure_class} evidence={args.evidence}")
    write_heartbeat(ws)
    loaded = load_header(ws)
    if loaded is not None:
        refresh_handoff(ws, loaded[3])
    out({"ok": True, "troubles_md": str(troubles_path),
         "model_log": str(model_log_path)})


def cmd_heartbeat(args) -> None:
    ws = Path(args.workspace)
    if not ws.exists():
        fail(f"workspace does not exist: {ws}")
        return
    write_heartbeat(ws)
    out({"ok": True})


def cmd_init(args) -> None:
    ws = Path(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    pf = pipeline_path(ws)
    if pf.exists():
        fail(f"PIPELINE.md already exists at {pf}")
        return

    stages = {}
    for num in STAGE_ORDER:
        gate = None
        if num in STAGE_GATE_NAMES:
            gate = {"name": STAGE_GATE_NAMES[num], "state": "pending",
                    "by": None, "at": None}
        stages[num] = {"status": "pending", "gate": gate}

    hdr = {
        "pipeline_version": PIPELINE_VERSION,
        "slug": args.slug,
        "mode": args.mode,
        "subject": args.subject,
        "topic": args.topic,
        "form": args.form,
        "updated": now_iso(),
        "canonical_output": None,
        "stages": stages,
    }

    body = render_yaml_body(hdr)
    content = (
        "```yaml\n" + body + "\n```\n\n"
        f"# {args.slug}\n\n"
        "| stage | label | status | gate | artifacts |\n"
        "|---|---|---|---|---|\n"
    )
    pf.write_text(content, encoding="utf-8")
    append_event(ws, "init", "0", f"initialized slug={args.slug} mode={args.mode}")
    write_heartbeat(ws)
    refresh_handoff(ws, hdr)
    out({"ok": True, "pipeline_md": str(pf), "slug": args.slug, "mode": args.mode})


# ── argument parsing ────────────────────────────────────────────────

class JsonArgumentParser(argparse.ArgumentParser):
    """argparse normally prints a usage message to stderr and exits 2 on bad
    args. We keep exit code 2 for usage errors but still emit the required
    single JSON object on stdout instead of a plain-text stderr message."""

    def error(self, message):
        usage_error(f"usage error: {message}")


def build_parser() -> argparse.ArgumentParser:
    p = JsonArgumentParser(
        prog="pipeline_ctl.py",
        description="State-machine enforcement CLI for Rigorloom PIPELINE.md (CONTRACT v0.4).",
    )
    sub = p.add_subparsers(dest="command", parser_class=JsonArgumentParser)

    p_resume = sub.add_parser("resume", help="Determine the resume point per CONTRACT §2 resume rule.")
    p_resume.add_argument("workspace")
    p_resume.set_defaults(func=cmd_resume)

    p_gate = sub.add_parser("gate", help="Resolve a HUMAN gate by reading APPROVALS.md (never fabricates human approval). Script gates use `check`, not `gate`.")
    p_gate.add_argument("workspace")
    p_gate.add_argument("gate_name")
    p_gate.add_argument("--mode", required=False, default=None, choices=sorted(MODE_ENUM))
    p_gate.add_argument("--script-exit", dest="script_exit", type=int, default=None,
                         help="RETIRED — use `check <ws> <gate>` instead. Kept only to emit a clear redirect for old callers; any value is a usage error.")
    p_gate.set_defaults(func=cmd_gate)

    p_check = sub.add_parser("check", help="Resolve a SCRIPT gate by running its bound checker (from stages.yaml): exit 0 -> auto_approved, nonzero -> rejected. Records provenance.")
    p_check.add_argument("workspace")
    p_check.add_argument("gate_name")
    p_check.set_defaults(func=cmd_check)

    p_advance = sub.add_parser("advance", help="Advance a stage's status, refusing illegal transitions.")
    p_advance.add_argument("workspace")
    p_advance.add_argument("stage")
    p_advance.add_argument("--status", required=True,
                            choices=["in_progress", "done", "awaiting_gate", "blocked"])
    p_advance.add_argument("--reason", default="")
    p_advance.set_defaults(func=cmd_advance)

    p_inval = sub.add_parser("invalidate", help="Reset a stage and all later stages to pending.")
    p_inval.add_argument("workspace")
    p_inval.add_argument("--from", dest="from_stage", required=True)
    p_inval.add_argument("--reason", default="")
    p_inval.set_defaults(func=cmd_invalidate)

    p_trouble = sub.add_parser("trouble", help="Log a failure to TROUBLES.md and the shared kb/model-log.md.")
    p_trouble.add_argument("workspace")
    p_trouble.add_argument("--stage", required=True)
    p_trouble.add_argument("--role", required=True)
    p_trouble.add_argument("--model", required=True)
    p_trouble.add_argument("--failure-class", required=True)
    p_trouble.add_argument("--evidence", required=True)
    p_trouble.add_argument("--kb-root", default=None)
    p_trouble.set_defaults(func=cmd_trouble)

    p_hb = sub.add_parser("heartbeat", help="Write current timestamp to <workspace>/heartbeat.")
    p_hb.add_argument("workspace")
    p_hb.set_defaults(func=cmd_heartbeat)

    p_init = sub.add_parser("init", help="Create a new PIPELINE.md with the full v0.4 YAML header template.")
    p_init.add_argument("workspace")
    p_init.add_argument("--slug", required=True)
    p_init.add_argument("--mode", required=True, choices=sorted(MODE_ENUM))
    p_init.add_argument("--subject", required=True)
    p_init.add_argument("--topic", required=True)
    p_init.add_argument("--form", required=True)
    p_init.set_defaults(func=cmd_init)

    return p


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # Hard error (not a silent fallback) if the stage graph failed to load.
    # Surfaced here as a clean JSON + nonzero exit rather than an import-time
    # traceback, so callers still get a single parseable object.
    if _STAGES_CONFIG_ERROR is not None:
        usage_error(f"stages.yaml load failed (hard error, no fallback): {_STAGES_CONFIG_ERROR}")
        return
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(2)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as e:  # unexpected — still a controlled JSON exit
        usage_error(f"internal error: {e}")


if __name__ == "__main__":
    _reexec_utf8_if_needed()
    main()
