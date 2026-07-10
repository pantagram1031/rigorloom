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
import json
import os
import re
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

# Embedded fallback — identical to references/stages.yaml — used when the
# config file is missing or fails to parse, so the CLI never hard-depends on
# an external file being present/well-formed.
FALLBACK_STAGES_CONFIG = [
    {"id": "0",   "name": "form_intake", "gate": None,
     "playbook": "playbooks/stage-0.md"},
    {"id": "1",   "name": "research",    "gate": None,
     "playbook": "playbooks/stage-1.md"},
    {"id": "2",   "name": "design",      "gate": {"name": "design", "type": "human"},
     "playbook": "playbooks/stage-2.md"},
    {"id": "2.5", "name": "layout_plan", "gate": {"name": "layout", "type": "script"},
     "playbook": "playbooks/stage-2.5.md"},
    {"id": "3",   "name": "sim",         "gate": {"name": "sane", "type": "script"},
     "playbook": "playbooks/stage-3.md"},
    {"id": "4",   "name": "write",       "gate": {"name": "draft", "type": "human"},
     "playbook": "playbooks/stage-4.md"},
    {"id": "5",   "name": "assemble",    "gate": None,
     "playbook": "playbooks/stage-5.md"},
    {"id": "5.5", "name": "understand",  "gate": {"name": "understand", "type": "human"},
     "playbook": "playbooks/stage-5.5.md"},
    {"id": "5.7", "name": "final_panel", "gate": None,
     "playbook": "playbooks/stage-5.7.md"},
    {"id": "6",   "name": "return",      "gate": None,
     "playbook": "playbooks/stage-6.md"},
]

STATUS_ENUM = {"pending", "in_progress", "awaiting_gate", "done", "blocked"}
GATE_ENUM = {"pending", "approved", "auto_approved", "rejected"}
MODE_ENUM = {"autonomous", "supervised", "night"}


# ── stages.yaml config loader ───────────────────────────────────────
#
# stages.yaml is a flat YAML list of inline-map records:
#   - {id: "2.5", name: "layout_plan", gate: {name: "layout", type: "script"}, playbook: "..."}
# Parsed by hand (stdlib only, no pyyaml), reusing the same inline-map
# helpers as the PIPELINE.md header parser below. Missing or corrupt file
# silently falls back to FALLBACK_STAGES_CONFIG so the CLI never hard-depends
# on the file being present.

_STAGE_ROW_RE = re.compile(r"^\s*-\s*\{(.*)\}\s*$")


def _parse_stages_yaml_text(text: str) -> list:
    """Parse the flat `stages:` list in stages.yaml. Raises on malformed
    input (caller decides fallback behavior)."""
    rows = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^version:\s*", line) or re.match(r"^stages:\s*$", line):
            continue
        m = _STAGE_ROW_RE.match(line)
        if not m:
            continue
        inner = m.group(1)
        rec = _parse_inline_map_nested(inner)
        if "id" not in rec:
            raise ValueError(f"stages.yaml row missing 'id': {line!r}")
        rows.append(rec)
    if not rows:
        raise ValueError("stages.yaml has no stage rows")
    return rows


def _parse_inline_map_nested(s: str) -> dict:
    """Like _parse_inline_map, but tolerates one level of nested {..} as a
    value (e.g. gate: {name: design, type: human}). Splits top-level commas
    only (commas inside a nested {} do not split)."""
    parts = []
    depth = 0
    buf = []
    for ch in s:
        if ch == "{":
            depth += 1
            buf.append(ch)
        elif ch == "}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))

    out_map = {}
    for part in parts:
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip()
        v = v.strip()
        if v.startswith("{") and v.endswith("}"):
            inner = v[1:-1]
            if inner.strip() in ("", "null", "~"):
                out_map[k] = None
            else:
                out_map[k] = _parse_inline_map_nested(inner)
        elif v in ("null", "~", ""):
            out_map[k] = None
        else:
            out_map[k] = _strip_q(v)
    return out_map


def load_stages_config(script_path: Path = None) -> list:
    """Return the stage list (each: {id, name, gate, playbook}) loaded from
    references/stages.yaml relative to this script, or the embedded fallback
    if the file is missing or fails to parse. Never raises."""
    base = Path(script_path) if script_path else Path(__file__).resolve()
    cfg_path = base.parent.parent / "references" / "stages.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
        rows = _parse_stages_yaml_text(text)
        return rows
    except Exception:
        return [dict(r) for r in FALLBACK_STAGES_CONFIG]


_STAGES_CONFIG = load_stages_config()

# STAGE_ORDER: ids in config file order (drives resume/advance/invalidate
# iteration). STAGE_GATE_NAMES: id -> gate name (only for stages with a
# gate). STAGE_GATE_TYPES: id -> gate type ("human" | "script").
STAGE_ORDER = [str(r["id"]) for r in _STAGES_CONFIG]
STAGE_GATE_NAMES = {
    str(r["id"]): r["gate"]["name"]
    for r in _STAGES_CONFIG if r.get("gate")
}
STAGE_GATE_TYPES = {
    str(r["id"]): r["gate"].get("type", "human")
    for r in _STAGES_CONFIG if r.get("gate")
}


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


def stage_gate_blocks(hdr: dict, stage: str, mode: str):
    """Check whether an EARLIER-ordered stage's gate blocks starting `stage`.
    Returns (blocked: bool, reason: str|None)."""
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
        gstate = gate.get("state")
        if gstate == "rejected":
            return True, f"predecessor stage {earlier} gate '{gate.get('name')}' is rejected"
        if gstate == "pending" and mode == "supervised":
            return True, f"predecessor stage {earlier} gate '{gate.get('name')}' is pending (supervised)"
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
    if args.script_exit is None and mode is None:
        usage_error("gate requires --mode (or --script-exit for script-type gates)")
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

    # Script gates (e.g. stage 2.5 'layout', stage 3 'sane') are resolved by
    # a caller-supplied exit code from a deterministic checker script, never
    # by APPROVALS.md/human text. 0 -> auto_approved (detail "script");
    # nonzero -> rejected + reason. This formalizes the pre-existing stage-3
    # hard-gate behavior (code emits sim/gate_result.json; the CLI never
    # fabricates or edits the verdict) under the same `gate` subcommand used
    # for human gates, instead of leaving it entirely outside pipeline_ctl.
    script_exit = args.script_exit
    if script_exit is not None:
        # Refuse script-exit on a human gate (design/draft/understand) — a
        # script call must never be able to auto_approve/reject a gate that's
        # supposed to require a human's APPROVALS.md line. Look up the gate's
        # declared type from the loaded stages config (module-level cache,
        # same source cmd_resume/etc. use — resolved relative to this script,
        # not the workspace).
        gate_type = None
        for st_cfg in _STAGES_CONFIG:
            cfg_gate = st_cfg.get("gate")
            if cfg_gate and cfg_gate.get("name") == gate_name:
                gate_type = cfg_gate.get("type")
                break
        if gate_type != "script":
            usage_error(f"gate '{gate_name}' is a human gate — script-exit 금지")
            return

        stages_ref = hdr["stages"]
        gate_obj = stages_ref[target_num]["gate"]
        if script_exit == 0:
            gate_obj["state"] = "auto_approved"
            gate_obj["by"] = "script"
            gate_obj["at"] = now_iso()
            save_header(ws, text, start, end, hdr)
            append_event(ws, "gate", target_num,
                         f"gate '{gate_name}' auto_approved (script, exit 0)")
            write_heartbeat(ws)
            refresh_handoff(ws, hdr)
            out({"ok": True, "gate": gate_name, "state": "auto_approved",
                 "stage": target_num, "by": "script", "detail": "script",
                 "at": gate_obj["at"]})
            return
        reason = f"script exited {script_exit}"
        gate_obj["state"] = "rejected"
        gate_obj["by"] = "script"
        gate_obj["at"] = now_iso()
        save_header(ws, text, start, end, hdr)
        append_event(ws, "gate", target_num,
                     f"gate '{gate_name}' rejected: {reason}")
        write_heartbeat(ws)
        refresh_handoff(ws, hdr)
        out({"ok": True, "gate": gate_name, "state": "rejected",
             "stage": target_num, "reason": reason, "by": "script"})
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
        # try to pull a timestamp like "approved by operator at 2026-07-06T09:10"
        ts_m = re.search(r"\bat\s+(\S+)", approved_line)
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

    p_gate = sub.add_parser("gate", help="Resolve a gate by reading APPROVALS.md (never fabricates human approval), or by a script's exit code for script-type gates.")
    p_gate.add_argument("workspace")
    p_gate.add_argument("gate_name")
    p_gate.add_argument("--mode", required=False, default=None, choices=sorted(MODE_ENUM))
    p_gate.add_argument("--script-exit", dest="script_exit", type=int, default=None,
                         help="Resolve a script-type gate from a checker script's exit code (0=auto_approved, nonzero=rejected). Bypasses APPROVALS.md/--mode.")
    p_gate.set_defaults(func=cmd_gate)

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
