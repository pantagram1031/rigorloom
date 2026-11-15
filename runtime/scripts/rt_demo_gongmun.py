#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-contained, Hancom-free 공문 end-to-end demo driven through RuntimeCore."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from html import unescape
from pathlib import Path
from typing import Any, Callable

try:
    from .rt_codes import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, RpcError
    from .rt_core import RuntimeCore
    from . import rt_apply, rt_apply_once, rt_engine, rt_module, rt_plan, rt_session
except ImportError:
    from rt_codes import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, RpcError
    from rt_core import RuntimeCore
    import rt_apply
    import rt_apply_once
    import rt_engine
    import rt_module
    import rt_plan
    import rt_session

EXIT_INTERNAL = 4

DETERMINISTIC_ENV = "RIGORLOOM_DETERMINISTIC"
FIXED_UTC = "2026-11-15T00:00:00Z"
MAX_BODY_LINES = 16
NORM_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)

DEFAULT_FORM_REL = Path("tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx")
DEFAULT_BRIEF_REL = Path("examples/gongmun/brief.json")

FORBIDDEN_CLAIMS = (
    "\uc815\ud655\ub3c4 \x31\x30\x30\x25",
    "\x43\x6c\x61\x75\x64\x65 \uae30\ubc18",
    "\x41\x49 \ud0d0\uc9c0 \ud68c\ud53c",
    "\x41\x49 \ud2f0 \uc81c\uac70",
)

_TOKEN_RE = re.compile(
    r"<!--[\s\S]*?-->|"
    r"<(?P<close>/)?(?:(?P<prefix>[A-Za-z0-9_]+):)?"
    r"(?P<local>p|tbl|tc|cellAddr|run|t)\b"
    r"(?P<attrs>(?:[^\"'>]|\"[^\"]*\"|'[^']*')*?)"
    r"(?P<self>/)?>",
    re.S,
)
_ATTR_INT_RE = {
    "rowAddr": re.compile(r'\browAddr\s*=\s*(["\'])(\d+)\1'),
    "colAddr": re.compile(r'\bcolAddr\s*=\s*(["\'])(\d+)\1'),
}
_QUOTE_RE = re.compile(
    r"(?:'[^'\n]{2,}'|「[^」\n]+」|『[^』\n]+』|《[^》\n]+》)"
)
_ASCII_ENTITY_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{1,}\b")


class DemoUsageError(Exception):
    """Raised when CLI arguments or input files are invalid (exit 2)."""


class DemoRefusalError(Exception):
    """Raised when a Runtime gate or blocking policy refuses (exit 3)."""


class DemoEnvironmentError(Exception):
    """Raised when engine/module prerequisites are missing or broken (exit 4)."""


@dataclass
class DemoPostPlanContext:
    """Mutable context exposed to post-plan fault-injection test hooks."""

    brief: dict[str, Any]
    form_path: Path
    candidate_path: Path
    out_dir: Path
    plan: dict[str, Any]
    approval: dict[str, Any]
    verdict: dict[str, Any]
    ops: list[dict[str, Any]]


_POST_PLAN_HOOK: Callable[[DemoPostPlanContext], None] | None = None


@contextmanager
def post_plan_hook_context(hook_fn: Callable[[DemoPostPlanContext], None] | None):
    """Temporarily install a post-plan hook for in-process refusal tests."""
    global _POST_PLAN_HOOK
    prev = _POST_PLAN_HOOK
    _POST_PLAN_HOOK = hook_fn
    try:
        yield
    finally:
        _POST_PLAN_HOOK = prev


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            # newline="\n": the README block and expected fixtures are LF;
            # Windows would otherwise print CRLF.
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # Bytes, not write_text: Windows text mode would turn \n into \r\n and
    # break the byte-for-byte match with examples/gongmun/expected.
    path.write_bytes(payload.encode("utf-8"))


@contextmanager
def _deterministic_runtime(enabled: bool):
    if not enabled:
        yield
        return

    counter = [0]
    orig_uuid4 = uuid.uuid4
    orig_rt_uuid4 = rt_apply_once.uuid.uuid4

    def _det_uuid4() -> uuid.UUID:
        counter[0] += 1
        raw = hashlib.sha256(
            f"rigorloom-demo-gongmun:{counter[0]}".encode("utf-8")
        ).digest()[:16]
        return uuid.UUID(bytes=raw, version=4)

    def _det_now_utc() -> str:
        return FIXED_UTC

    target_mod_names = {"rt_session", "rt_plan", "rt_apply", "rt_apply_once", "rt_module"}
    patched_now: list[tuple[Any, Any]] = []
    seen_mods: set[int] = set()

    for mod in [rt_session, rt_plan, rt_apply, rt_apply_once, rt_module]:
        seen_mods.add(id(mod))
        if hasattr(mod, "now_utc"):
            patched_now.append((mod, mod.now_utc))
            mod.now_utc = _det_now_utc
    for name, mod in list(sys.modules.items()):
        if mod is None or id(mod) in seen_mods:
            continue
        if name.rsplit(".", 1)[-1] in target_mod_names and hasattr(mod, "now_utc"):
            seen_mods.add(id(mod))
            patched_now.append((mod, mod.now_utc))
            mod.now_utc = _det_now_utc

    uuid.uuid4 = _det_uuid4
    rt_apply_once.uuid.uuid4 = _det_uuid4
    try:
        yield
    finally:
        uuid.uuid4 = orig_uuid4
        rt_apply_once.uuid.uuid4 = orig_rt_uuid4
        for mod, orig in patched_now:
            mod.now_utc = orig


@contextmanager
def _staged_modules_env(enabled_yaml: Path, modules_root: Path):
    old_enabled = os.environ.get(rt_module.MODULES_ENABLED_ENV)
    old_root = os.environ.get(rt_module.MODULES_ROOT_ENV)
    os.environ[rt_module.MODULES_ENABLED_ENV] = str(enabled_yaml)
    os.environ[rt_module.MODULES_ROOT_ENV] = str(modules_root)
    try:
        yield
    finally:
        if old_enabled is None:
            os.environ.pop(rt_module.MODULES_ENABLED_ENV, None)
        else:
            os.environ[rt_module.MODULES_ENABLED_ENV] = old_enabled
        if old_root is None:
            os.environ.pop(rt_module.MODULES_ROOT_ENV, None)
        else:
            os.environ[rt_module.MODULES_ROOT_ENV] = old_root


def _normalize_hwpx_if_needed(src: Path, dest: Path) -> Path:
    """Return a zip-timestamp-normalized copy only when src lacks fixed timestamps."""
    with zipfile.ZipFile(src, "r") as zin:
        infos = zin.infolist()
        if all(info.date_time == NORM_ZIP_DATETIME for info in infos):
            return src
        with zipfile.ZipFile(dest, "w") as zout:
            for info in infos:
                new_info = zipfile.ZipInfo(info.filename, date_time=NORM_ZIP_DATETIME)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, zin.read(info.filename))
    return dest


def _resolve_engine_and_modules(engine_root_arg: str | Path | None) -> tuple[Path, Path]:
    engine_root = (
        Path(engine_root_arg).expanduser().resolve()
        if engine_root_arg is not None
        else Path(rt_engine.DEFAULT_ENGINE_ROOT).resolve()
    )
    if not (engine_root / "engine" / "scripts" / "preedit.py").is_file():
        raise DemoEnvironmentError(
            f"engine scripts not found under engine root: {engine_root}"
        )
    if not (engine_root / "pipeline" / "scripts" / "check_residue.py").is_file():
        raise DemoEnvironmentError(
            f"pipeline scripts not found under engine root: {engine_root}"
        )
    env_modules = (os.environ.get(rt_module.MODULES_ROOT_ENV) or "").strip()
    modules_root = (
        Path(env_modules).expanduser().resolve()
        if env_modules and engine_root_arg is None
        else (engine_root / "modules").resolve()
    )
    if not (modules_root / "gongmun" / "scripts" / "check_gongmun.py").is_file():
        raise DemoEnvironmentError(
            f"gongmun module checker not found under modules root: {modules_root}"
        )
    return engine_root, modules_root


def _require_str(obj: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    if key not in obj or not isinstance(obj[key], str):
        raise DemoUsageError(f"brief field {key!r} must be a string")
    if not allow_empty and not obj[key].strip():
        raise DemoUsageError(f"brief field {key!r} must be non-empty")
    return obj[key]


def _get_postal(brief: dict[str, Any]) -> str:
    if "우" in brief:
        return _require_str(brief, "우")
    if "우편번호" in brief:
        return _require_str(brief, "우편번호")
    raise DemoUsageError("brief must define '우' (or '우편번호')")


def load_and_validate_brief(brief_path: Path) -> dict[str, Any]:
    if not brief_path.is_file():
        raise DemoUsageError(f"brief file not found: {brief_path}")
    try:
        raw = brief_path.read_text(encoding="utf-8")
        brief = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise DemoUsageError(f"invalid brief JSON ({brief_path}): {exc}") from exc
    if not isinstance(brief, dict):
        raise DemoUsageError("brief JSON must be an object")

    for req_key in (
        "기관명", "수신", "제목", "발신명의", "시행번호",
        "도로명주소", "홈페이지", "전화번호", "팩스번호", "이메일", "공개구분",
    ):
        _require_str(brief, req_key)
    _get_postal(brief)

    if "경유" in brief:
        val = _require_str(brief, "경유", allow_empty=False)
        if val != "(경유)":
            raise DemoUsageError(
                "brief field '경유' must stay '(경유)' so the blank template's (경유) paragraph stays untouched"
            )
    for opt_key in ("접수번호", "비고", "붙임"):
        if opt_key in brief and not isinstance(brief[opt_key], str):
            raise DemoUsageError(f"brief field {opt_key!r} must be a string")

    approvals = brief.get("결재")
    if not isinstance(approvals, dict):
        raise DemoUsageError("brief field '결재' must be an object")
    for role in ("기안자", "검토자", "결재권자"):
        _require_str(approvals, role)

    body = brief.get("본문")
    if not isinstance(body, list) or not body or not all(isinstance(x, str) for x in body):
        raise DemoUsageError("brief field '본문' must be a non-empty list of strings")
    if not any(line.strip() for line in body):
        raise DemoUsageError("brief field '본문' must contain at least one non-empty line")

    attach = brief.get("붙임", "")
    lines = list(body) + (["", attach] if attach else [])
    if len(lines) > MAX_BODY_LINES:
        raise DemoUsageError(
            f"brief body + 붙임 exceeds {MAX_BODY_LINES} lines ({len(lines)})"
        )
    return brief


def build_gongmun_plan(brief: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build deterministic OperationPlan ops and declarations for 별지 제1호서식."""
    postal = _get_postal(brief)
    attach = brief.get("붙임", "")
    body_lines = list(brief["본문"]) + (["", attach] if attach else [])
    reception = brief.get("접수번호", "")
    note = brief.get("비고", "")
    approvals = brief["결재"]

    ops: list[dict[str, Any]] = [
        # Clear Table 0 (0,0): [별지 제1호서식] and <개정 ...> guide text.
        {"kind": "replace_at_cell", "table": 0, "row": 0, "col": 0, "run": 0, "text": "", "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 0, "col": 0, "run": 1, "text": "", "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 0, "col": 0, "run": 2, "text": "", "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 0, "col": 0, "run": 3, "text": "", "mode": "replace"},
        # Table 0 (1,0): 두문 (leave run 2 '(경유)' untouched).
        {"kind": "replace_at_cell", "table": 0, "row": 1, "col": 0, "run": 0, "text": brief["기관명"], "mode": "replace", "charPr": "12"},
        {"kind": "replace_at_cell", "table": 0, "row": 1, "col": 0, "run": 1, "text": brief["수신"], "mode": "replace", "charPr": "14"},
        {"kind": "replace_at_cell", "table": 0, "row": 1, "col": 0, "run": 3, "text": brief["제목"], "mode": "replace", "charPr": "14"},
        # Table 2 (0,0): 발신명의.
        {"kind": "replace_at_cell", "table": 2, "row": 0, "col": 0, "run": 0, "text": brief["발신명의"], "mode": "replace", "charPr": "8"},
        # Table 0 (4,0), (4,3), (4,9): 결재란.
        {"kind": "replace_at_cell", "table": 0, "row": 4, "col": 0, "run": 0, "text": approvals["기안자"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 4, "col": 3, "run": 0, "text": approvals["검토자"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 4, "col": 9, "run": 0, "text": approvals["결재권자"], "mode": "replace"},
        # Table 0 (6,1), (6,8): 시행, 접수.
        {"kind": "replace_at_cell", "table": 0, "row": 6, "col": 1, "run": 0, "text": brief["시행번호"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 6, "col": 8, "run": 0, "text": reception, "mode": "replace"},
        # Table 0 (7,0), (7,1), (7,7): 우편번호, 주소, 홈페이지.
        {"kind": "replace_at_cell", "table": 0, "row": 7, "col": 0, "run": 0, "text": postal, "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 7, "col": 1, "run": 0, "text": brief["도로명주소"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 7, "col": 7, "run": 0, "text": brief["홈페이지"], "mode": "replace"},
        # Table 0 (8,0), (8,2), (8,7), (8,12): 전화, 팩스, 이메일, 공개구분.
        {"kind": "replace_at_cell", "table": 0, "row": 8, "col": 0, "run": 0, "text": brief["전화번호"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 8, "col": 2, "run": 0, "text": brief["팩스번호"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 8, "col": 7, "run": 0, "text": brief["이메일"], "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 8, "col": 12, "run": 0, "text": brief["공개구분"], "mode": "replace"},
        # Table 0 (10,0): 비고.
        {"kind": "replace_at_cell", "table": 0, "row": 10, "col": 0, "run": 0, "text": note, "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 10, "col": 0, "run": 1, "text": "", "mode": "replace"},
        {"kind": "replace_at_cell", "table": 0, "row": 10, "col": 0, "run": 2, "text": "", "mode": "replace"},
        # Table 0 (2,0): body + 붙임 applied last so body charPr=14 doesn't shift baseline.
        {"kind": "fill_cell", "table": 0, "row": 2, "col": 0, "lines": body_lines, "charPr": "14", "paraPr": "18"},
    ]

    fill_map: dict[str, Any] = {
        "행 정 기 관 명": brief["기관명"],
        "수신": brief["수신"],
        "제목": brief["제목"],
        "발신명의": brief["발신명의"],
        "기안자  직위(직급) 서명": approvals["기안자"],
        "검토자  직위(직급) 서명": approvals["검토자"],
        "결재권자  직위(직급) 서명": approvals["결재권자"],
        "처리과명-연도별 일련번호(시행일)": {"text": brief["시행번호"], "other_occurrences": "seats"},
        "도로명주소": brief["도로명주소"],
        "홈페이지 주소": brief["홈페이지"],
        "전화번호(   )": brief["전화번호"],
        "팩스번호(   )": brief["팩스번호"],
        "공무원의 전자우편주소": {"text": brief["이메일"], "other_occurrences": "seats"},
        "공개 구분": brief["공개구분"],
    }
    declares = {
        "fillMap": fill_map,
        "keep": [
            "(경유)",
            "직인",
            "협조자",
            "시행",
            "접수",
            "우",
            "/",
            "210㎜×297㎜(백상지 80g/㎡)",
        ],
    }
    return ops, declares


def _scan_hwpx_section(xml: str) -> dict[str, Any]:
    """Parse section XML into ordered paragraphs, tables, cells, and text runs."""
    paras: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    para_stack: list[dict[str, Any]] = []
    tbl_stack: list[dict[str, Any]] = []
    tc_stack: list[dict[str, Any]] = []
    run_stack: list[dict[str, Any] | None] = []
    t_stack: list[tuple[dict[str, Any] | None, int] | None] = []

    for tok in _TOKEN_RE.finditer(xml):
        local = tok.group("local")
        if local is None:
            continue
        is_close = bool(tok.group("close"))
        is_self = bool(tok.group("self"))
        attrs = tok.group("attrs") or ""

        if is_close:
            if local == "t":
                if t_stack:
                    item = t_stack.pop()
                    if item is not None:
                        owner_run, t_start = item
                        if owner_run is not None:
                            owner_run["t_spans"].append((t_start, tok.start()))
            elif local == "run":
                if run_stack:
                    run_info = run_stack.pop()
                    if run_info is not None and run_info["t_spans"]:
                        para = run_info["para"]
                        para["runs"].append(run_info)
            elif local == "p":
                if para_stack:
                    p = para_stack.pop()
                    p["end"] = tok.end()
            elif local == "tc":
                if tc_stack:
                    tc_stack.pop()["end"] = tok.end()
            elif local == "tbl":
                if tbl_stack:
                    tbl_stack.pop()["end"] = tok.end()
            continue

        if local == "p":
            parent = para_stack[-1] if para_stack else None
            if parent is not None:
                parent["has_child_para"] = True
            direct_tc = tc_stack[-1] if tc_stack else None
            # Direct child of tc.subList means top para inside current tc
            # (not inside a nested tbl whose own tc sits inside this para).
            in_direct_tc = (
                direct_tc is not None
                and (not tbl_stack or direct_tc["tbl_id"] == tbl_stack[-1]["id"])
                and (not para_stack or para_stack[-1]["start"] < direct_tc["start"])
            )
            p = {
                "id": len(paras),
                "start": tok.start(),
                "end": tok.end() if is_self else -1,
                "parent_id": parent["id"] if parent is not None else None,
                "has_child_para": False,
                "has_tbl": False,
                "runs": [],
            }
            paras.append(p)
            if in_direct_tc and direct_tc is not None:
                direct_tc["direct_para_ids"].append(p["id"])
            if not is_self:
                para_stack.append(p)
        elif local == "tbl":
            for anc in para_stack:
                anc["has_tbl"] = True
            tbl = {
                "id": len(tables),
                "start": tok.start(),
                "end": tok.end() if is_self else -1,
                "cells": [],
            }
            tables.append(tbl)
            if not is_self:
                tbl_stack.append(tbl)
        elif local == "tc":
            if not tbl_stack:
                continue
            cell = {
                "tbl_id": tbl_stack[-1]["id"],
                "start": tok.start(),
                "end": tok.end() if is_self else -1,
                "row": None,
                "col": None,
                "direct_para_ids": [],
            }
            tbl_stack[-1]["cells"].append(cell)
            if not is_self:
                tc_stack.append(cell)
        elif local == "cellAddr":
            if tc_stack and (not tbl_stack or tc_stack[-1]["tbl_id"] == tbl_stack[-1]["id"]):
                cell = tc_stack[-1]
                if cell["row"] is None:
                    rm = _ATTR_INT_RE["rowAddr"].search(attrs)
                    cm = _ATTR_INT_RE["colAddr"].search(attrs)
                    if rm and cm:
                        cell["row"] = int(rm.group(2))
                        cell["col"] = int(cm.group(2))
        elif local == "run":
            cur_para = para_stack[-1] if para_stack else None
            if is_self:
                continue
            if cur_para is not None:
                run_stack.append({"para": cur_para, "t_spans": []})
            else:
                run_stack.append(None)
        elif local == "t":
            if is_self:
                continue
            owner_run = None
            for rf in reversed(run_stack):
                if rf is not None:
                    owner_run = rf
                    break
            if owner_run is not None and para_stack and owner_run["para"] is para_stack[-1]:
                t_stack.append((owner_run, tok.end()))
            else:
                t_stack.append(None)

    for p in paras:
        p["is_leaf"] = (not p["has_child_para"]) and (not p["has_tbl"])
        raw_texts = []
        run_texts = []
        for r in p["runs"]:
            joined = "".join(re.sub(r"<[^>]+>", "", xml[s:e]) for s, e in r["t_spans"])
            text = unescape(joined)
            run_texts.append(text)
            raw_texts.append(text)
        p["run_texts"] = run_texts
        p["text"] = "".join(raw_texts)
    return {"paras": paras, "tables": tables}


def _find_cell(tables: list[dict[str, Any]], table_idx: int, row: int, col: int) -> dict[str, Any] | None:
    if table_idx < 0 or table_idx >= len(tables):
        return None
    for cell in tables[table_idx]["cells"]:
        if cell["row"] == row and cell["col"] == col:
            return cell
    return None


def _cell_run_records(scan: dict[str, Any], table_idx: int, row: int, col: int) -> list[tuple[int, str]]:
    """Return [(para_id, run_text), ...] matching preedit.cell_text_runs order."""
    cell = _find_cell(scan["tables"], table_idx, row, col)
    if cell is None:
        return []
    paras = scan["paras"]
    out: list[tuple[int, str]] = []
    for pid in cell["direct_para_ids"]:
        p = paras[pid]
        if p["has_tbl"]:
            continue
        for txt in p["run_texts"]:
            out.append((pid, txt))
    return out


def _cell_fill_slot_ids(scan: dict[str, Any], table_idx: int, row: int, col: int) -> tuple[list[int], list[int]]:
    """Return (contiguous_slot_para_ids, non_empty_other_leaf_para_ids) in cell."""
    cell = _find_cell(scan["tables"], table_idx, row, col)
    if cell is None:
        return [], []
    paras = scan["paras"]
    direct = cell["direct_para_ids"]
    first_non_tbl = next((i for i, pid in enumerate(direct) if not paras[pid]["has_tbl"]), None)
    if first_non_tbl is None:
        return [], []
    slots: list[int] = []
    for pid in direct[first_non_tbl:]:
        if paras[pid]["has_tbl"]:
            break
        slots.append(pid)
    blanked: list[int] = []
    for pid in direct:
        p = paras[pid]
        if p["has_tbl"]:
            continue
        if p["text"] != "":
            blanked.append(pid)
    return slots, blanked


def _mask_touched_leaves(xml: str, paras: list[dict[str, Any]], touched_ids: set[int]) -> str:
    spans = []
    for pid in touched_ids:
        p = paras[pid]
        if not p["is_leaf"]:
            raise DemoRefusalError(
                f"Policy (i) internal mismatch: paragraph {pid} is not a leaf paragraph"
            )
        spans.append((p["start"], p["end"], f"<TOUCHED:{pid}/>"))
    out = xml
    for start, end, token in sorted(spans, reverse=True):
        out = out[:start] + token + out[end:]
    return out


def _iter_brief_leaf_strings(brief: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect (field_label, non_empty_value) pairs for Policy (i) completeness."""
    items: list[tuple[str, str]] = []
    for key in (
        "기관명", "수신", "경유", "제목", "붙임", "발신명의",
        "시행번호", "접수번호", "우", "우편번호", "도로명주소",
        "홈페이지", "전화번호", "팩스번호", "이메일", "공개구분", "비고",
    ):
        val = brief.get(key)
        if isinstance(val, str) and val != "":
            items.append((key, val))
    approvals = brief.get("결재")
    if isinstance(approvals, dict):
        for role, val in approvals.items():
            if isinstance(val, str) and val != "":
                items.append((f"결재.{role}", val))
    body = brief.get("본문")
    if isinstance(body, list):
        for idx, line in enumerate(body):
            if isinstance(line, str) and line != "":
                items.append((f"본문[{idx}]", line))
    return items


def _expected_seat_checks(brief: dict[str, Any]) -> tuple[list[tuple[int, int, int, int, str, str]], list[str]]:
    postal = _get_postal(brief)
    approvals = brief["결재"]
    attach = brief.get("붙임", "")
    body_lines = list(brief["본문"]) + (["", attach] if attach else [])
    run_checks = [
        (0, 0, 0, 0, "", "Table 0 (0,0)#0"),
        (0, 0, 0, 1, "", "Table 0 (0,0)#1"),
        (0, 0, 0, 2, "", "Table 0 (0,0)#2"),
        (0, 0, 0, 3, "", "Table 0 (0,0)#3"),
        (0, 1, 0, 0, brief["기관명"], "기관명"),
        (0, 1, 0, 1, brief["수신"], "수신"),
        (0, 1, 0, 2, brief.get("경유", "(경유)"), "경유"),
        (0, 1, 0, 3, brief["제목"], "제목"),
        (2, 0, 0, 0, brief["발신명의"], "발신명의"),
        (0, 4, 0, 0, approvals["기안자"], "결재.기안자"),
        (0, 4, 3, 0, approvals["검토자"], "결재.검토자"),
        (0, 4, 9, 0, approvals["결재권자"], "결재.결재권자"),
        (0, 6, 1, 0, brief["시행번호"], "시행번호"),
        (0, 6, 8, 0, brief.get("접수번호", ""), "접수번호"),
        (0, 7, 0, 0, postal, "우"),
        (0, 7, 1, 0, brief["도로명주소"], "도로명주소"),
        (0, 7, 7, 0, brief["홈페이지"], "홈페이지"),
        (0, 8, 0, 0, brief["전화번호"], "전화번호"),
        (0, 8, 2, 0, brief["팩스번호"], "팩스번호"),
        (0, 8, 7, 0, brief["이메일"], "이메일"),
        (0, 8, 12, 0, brief["공개구분"], "공개구분"),
        (0, 10, 0, 0, brief.get("비고", ""), "비고#0"),
        (0, 10, 0, 1, "", "비고#1"),
        (0, 10, 0, 2, "", "비고#2"),
    ]
    return run_checks, body_lines


def verify_policy_i(
    form_path: Path,
    filled_path: Path,
    ops: list[dict[str, Any]],
    brief: dict[str, Any],
) -> dict[str, Any]:
    """Enforce blocking Policy (i): form -> filled verbatim + untouched byte-identity."""
    with zipfile.ZipFile(form_path, "r") as z0, zipfile.ZipFile(filled_path, "r") as z1:
        names0 = sorted(z0.namelist())
        names1 = sorted(z1.namelist())
        if names0 != names1:
            raise DemoRefusalError(
                "Policy (i) failed: filled package members differ from blank form"
            )

        section_names = [
            n for n in names0 if re.fullmatch(r"Contents/section\d+\.xml", n)
        ]
        if not section_names:
            raise DemoRefusalError("Policy (i) failed: no section XML found in HWPX")

        for name in names0:
            if name in section_names:
                continue
            if z0.read(name) != z1.read(name):
                raise DemoRefusalError(
                    f"Policy (i) failed: non-section package member changed ({name})"
                )

        # Currently all edits live in section0.xml; compare every section cleanly.
        cand_scan0: dict[str, Any] | None = None
        all_leaf_texts: list[str] = []
        paragraph_diff: list[dict[str, Any]] = []
        untouched_checked = 0
        touched_total = 0

        for sname in section_names:
            xml0 = z0.read(sname).decode("utf-8")
            xml1 = z1.read(sname).decode("utf-8")
            scan0 = _scan_hwpx_section(xml0)
            scan1 = _scan_hwpx_section(xml1)
            if len(scan0["paras"]) != len(scan1["paras"]):
                raise DemoRefusalError(
                    f"Policy (i) failed: paragraph count changed in {sname} "
                    f"({len(scan0['paras'])} -> {len(scan1['paras'])})"
                )
            for idx, (p0, p1) in enumerate(zip(scan0["paras"], scan1["paras"])):
                if p0["is_leaf"] != p1["is_leaf"]:
                    raise DemoRefusalError(
                        f"Policy (i) failed: paragraph structure changed at index {idx}"
                    )

            touched_ids: set[int] = set()
            if sname == "Contents/section0.xml":
                cand_scan0 = scan1
                for op in ops:
                    kind = op["kind"]
                    if kind == "replace_at_cell":
                        recs = _cell_run_records(
                            scan0, int(op["table"]), int(op["row"]), int(op["col"])
                        )
                        ridx = 0 if op.get("run") is None else int(op["run"])
                        if ridx < 0 or ridx >= len(recs):
                            raise DemoRefusalError(
                                f"Policy (i) failed: target run out of range in {op}"
                            )
                        touched_ids.add(recs[ridx][0])
                    elif kind == "fill_cell":
                        slots, blanked = _cell_fill_slot_ids(
                            scan0, int(op["table"]), int(op["row"]), int(op["col"])
                        )
                        lines = op.get("lines") or []
                        touched_ids.update(slots[: len(lines)])
                        touched_ids.update(blanked)
                    elif kind == "set_run":
                        touched_ids.add(int(op["atPara"]))

            masked0 = _mask_touched_leaves(xml0, scan0["paras"], touched_ids)
            masked1 = _mask_touched_leaves(xml1, scan1["paras"], touched_ids)
            if masked0 != masked1:
                first_bad = next(
                    (
                        i
                        for i, (p0, p1) in enumerate(zip(scan0["paras"], scan1["paras"]))
                        if p0["is_leaf"]
                        and i not in touched_ids
                        and xml0[p0["start"]:p0["end"]] != xml1[p1["start"]:p1["end"]]
                    ),
                    None,
                )
                detail = (
                    f"untouched leaf paragraph index {first_bad} modified"
                    if first_bad is not None
                    else "untouched wrapper/layout XML bytes modified"
                )
                raise DemoRefusalError(f"Policy (i) failed ({sname}): {detail}")

            if sname == "Contents/section0.xml":
                for pid in sorted(touched_ids):
                    before_text = scan0["paras"][pid]["text"]
                    after_text = scan1["paras"][pid]["text"]
                    if before_text != after_text:
                        paragraph_diff.append({
                            "paraIndex": pid,
                            "before": before_text,
                            "after": after_text,
                        })

            touched_total += len(touched_ids)
            untouched_checked += sum(
                1 for i, p in enumerate(scan0["paras"]) if p["is_leaf"] and i not in touched_ids
            )
            for p in scan1["paras"]:
                if p["is_leaf"]:
                    all_leaf_texts.append(p["text"])

    if cand_scan0 is None:
        raise DemoRefusalError("Policy (i) failed: missing Contents/section0.xml")

    combined_leaf_text = "\n".join(all_leaf_texts)
    brief_leaf_items = _iter_brief_leaf_strings(brief)
    for field_name, value in brief_leaf_items:
        if value not in combined_leaf_text:
            raise DemoRefusalError(
                f"Policy (i) failed: brief value for {field_name!r} missing verbatim in filled.hwpx"
            )

    run_checks, body_lines = _expected_seat_checks(brief)
    for t_idx, row, col, run_idx, expected_text, label in run_checks:
        recs = _cell_run_records(cand_scan0, t_idx, row, col)
        if run_idx >= len(recs):
            raise DemoRefusalError(
                f"Policy (i) failed: seat {label} ({t_idx}:{row},{col}#{run_idx}) missing"
            )
        actual_text = recs[run_idx][1]
        if actual_text != expected_text:
            raise DemoRefusalError(
                f"Policy (i) failed: seat {label} mismatch "
                f"(expected {expected_text!r}, got {actual_text!r})"
            )

    slots, _ = _cell_fill_slot_ids(cand_scan0, 0, 2, 0)
    if len(body_lines) > len(slots):
        raise DemoRefusalError(
            f"Policy (i) failed: body lines ({len(body_lines)}) exceed cell slots ({len(slots)})"
        )
    cand_paras = cand_scan0["paras"]
    for idx, expected_line in enumerate(body_lines):
        actual_line = cand_paras[slots[idx]]["text"]
        if actual_line != expected_line:
            raise DemoRefusalError(
                f"Policy (i) failed: body line {idx} mismatch "
                f"(expected {expected_line!r}, got {actual_line!r})"
            )

    return {
        "ok": True,
        "policy": "form->filled",
        "briefValuesChecked": len(brief_leaf_items),
        "allBriefValuesVerbatim": True,
        "touchedLeafParagraphs": touched_total,
        "untouchedLeafParagraphs": untouched_checked,
        "untouchedBytesIdentical": True,
        "paragraphDiff": paragraph_diff,
    }


def _load_prose_fidelity(modules_root: Path):
    script = modules_root / "style" / "scripts" / "prose_fidelity.py"
    if not script.is_file():
        raise DemoEnvironmentError(f"prose_fidelity module script not found: {script}")
    spec = importlib.util.spec_from_file_location("rigorloom_style_prose_fidelity", script)
    if spec is None or spec.loader is None:
        raise DemoEnvironmentError(f"unable to load prose_fidelity from: {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _collapse_ws_lower(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def verify_policy_ii(
    brief: dict[str, Any],
    polished_path: Path,
    modules_root: Path,
) -> dict[str, Any]:
    """Enforce blocking Policy (ii): draft -> polished fidelity + forbidden claims."""
    try:
        polished_text = polished_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DemoUsageError(f"unable to read --polished file ({polished_path}): {exc}") from exc

    if not polished_text.strip():
        raise DemoRefusalError("Policy (ii) failed: --polished file is empty")

    attach = brief.get("붙임", "")
    draft_lines = list(brief["본문"]) + ([attach] if attach else [])
    draft_text = "\n".join(draft_lines)

    prose_fidelity = _load_prose_fidelity(modules_root)
    audit = prose_fidelity.audit_text(draft_text, polished_text)
    if not audit.get("pass"):
        kinds = [c.get("kind") for c in (audit.get("changes") or [])]
        raise DemoRefusalError(
            f"Policy (ii) failed: prose_fidelity rejected ungrounded/altered facts ({kinds})"
        )

    polished_norm = _collapse_ws_lower(polished_text)
    for idx, phrase in enumerate(FORBIDDEN_CLAIMS, start=1):
        if _collapse_ws_lower(phrase) in polished_norm:
            raise DemoRefusalError(
                f"Policy (ii) failed: forbidden claim present (rule #{idx})"
            )

    brief_all_text = "\n".join(v for _, v in _iter_brief_leaf_strings(brief))
    for quote in _QUOTE_RE.findall(polished_text):
        if quote not in brief_all_text:
            raise DemoRefusalError(
                f"Policy (ii) failed: ungrounded quote introduced ({quote!r})"
            )

    brief_entities = {tok.lower() for tok in _ASCII_ENTITY_RE.findall(brief_all_text)}
    for entity in _ASCII_ENTITY_RE.findall(polished_text):
        if entity.lower() not in brief_entities:
            raise DemoRefusalError(
                f"Policy (ii) failed: ungrounded entity/identifier introduced ({entity!r})"
            )

    return {
        "status": "pass",
        "ok": True,
        "policy": "draft->polished",
        "fidelityOk": True,
    }


def _normalize_verdict(
    verdict: dict[str, Any],
    engine_root: Path,
    modules_root: Path,
    deterministic: bool,
) -> dict[str, Any]:
    out = json.loads(json.dumps(verdict, ensure_ascii=False))
    if not deterministic:
        return out
    out["enabledFile"] = "enabled.yaml"
    try:
        rel_mod = modules_root.resolve().relative_to(engine_root.resolve()).as_posix()
        out["modulesRoot"] = rel_mod or "modules"
    except ValueError:
        out["modulesRoot"] = "modules"
    for row in out.get("checks") or []:
        if isinstance(row, dict) and "durationMs" in row:
            row["durationMs"] = 0
    return out


def _atomic_publish_outputs(
    staging_out: Path,
    out_dir: Path,
    candidate_src: Path,
    plan_data: dict[str, Any],
    verdict_data: dict[str, Any],
    approval_data: dict[str, Any],
) -> str:
    staging_out.mkdir(parents=True, exist_ok=True)
    staged_hwpx = staging_out / "filled.hwpx"
    staged_plan = staging_out / "plan.json"
    staged_verdict = staging_out / "verdict.json"
    staged_approval = staging_out / "approval.json"

    shutil.copyfile(candidate_src, staged_hwpx)
    _write_json(staged_plan, plan_data)
    _write_json(staged_verdict, verdict_data)
    _write_json(staged_approval, approval_data)

    out_dir.mkdir(parents=True, exist_ok=True)
    for src, name in (
        (staged_hwpx, "filled.hwpx"),
        (staged_plan, "plan.json"),
        (staged_verdict, "verdict.json"),
        (staged_approval, "approval.json"),
    ):
        target = out_dir / name
        tmp = out_dir / f".tmp-{name}-{os.getpid()}"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
    return _sha256_file(out_dir / "filled.hwpx")


def run_demo_gongmun(
    *,
    out_dir: str | Path,
    brief_path: str | Path | None = None,
    form_path: str | Path | None = None,
    polished_path: str | Path | None = None,
    engine_root: str | Path | None = None,
    deterministic: bool = False,
) -> tuple[str, int]:
    """Run the full 공문 demo workflow and return (summary_stdout, exit_code)."""
    det = deterministic or os.environ.get(DETERMINISTIC_ENV, "").strip() == "1"

    out_p = Path(out_dir).expanduser()
    if out_p.exists() and not out_p.is_dir():
        raise DemoUsageError(f"--out exists and is not a directory: {out_p}")

    resolved_engine, modules_root = _resolve_engine_and_modules(engine_root)
    resolved_brief = (
        Path(brief_path).expanduser().resolve()
        if brief_path is not None
        else (resolved_engine / DEFAULT_BRIEF_REL).resolve()
    )
    resolved_form = (
        Path(form_path).expanduser().resolve()
        if form_path is not None
        else (resolved_engine / DEFAULT_FORM_REL).resolve()
    )
    if not resolved_form.is_file():
        raise DemoUsageError(f"form file not found: {resolved_form}")

    resolved_polished: Path | None = None
    if polished_path is not None:
        resolved_polished = Path(polished_path).expanduser().resolve()
        if not resolved_polished.is_file():
            raise DemoUsageError(f"polished file not found: {resolved_polished}")

    brief = load_and_validate_brief(resolved_brief)

    with tempfile.TemporaryDirectory(prefix="rigorloom-demo-gongmun-") as tmp_str:
        stage_root = Path(tmp_str)
        enabled_yaml = stage_root / "enabled.yaml"
        enabled_yaml.write_text(
            "schema: rigorloom-enabled-modules/v1\nenabled: [gongmun]\n",
            encoding="utf-8",
        )
        form_input = resolved_form
        if det:
            form_input = _normalize_hwpx_if_needed(
                resolved_form, stage_root / resolved_form.name
            )

        with _deterministic_runtime(det), _staged_modules_env(enabled_yaml, modules_root):
            try:
                core = RuntimeCore(stage_root / "rt", engine_root=resolved_engine)
                opened = core.open_path(str(form_input))
                sid = opened["sessionId"]

                ops, declares = build_gongmun_plan(brief)
                proposed = core.plan_propose(
                    sid, "preedit", ops, "demo-builder", declares=declares
                )
                plan_id = proposed["plan"]["planId"]
                plan_hash = proposed["plan"]["planHash"]

                val = core.plan_validate(plan_id)["validation"]
                if val.get("stale") or not val.get("ok"):
                    raise DemoRefusalError(
                        f"plan_validate refused plan ({val.get('verdict') or val.get('hard')})"
                    )

                req = core.approval_request(plan_id, "demo-builder")
                appr_id = req["approval"]["approvalId"]
                resolved_appr = core.approval_resolve(
                    appr_id, plan_id, plan_hash, "approved", "demo-operator"
                )
                approval_data = resolved_appr["approval"]

                applied = core.plan_apply(plan_id, appr_id)
                cand = applied["candidate"]
                run_id = cand["runId"]
                apply_checks = cand.get("checks") or {}
                res_counts = (
                    apply_checks.get("counts")
                    or ((apply_checks.get("checks") or [{}])[0].get("counts"))
                    or {}
                )
                if not apply_checks.get("ranAll") or not apply_checks.get("acceptance"):
                    raise DemoRefusalError(
                        f"apply residue check did not accept candidate: {res_counts or apply_checks.get('reason')}"
                    )

                raw_cand_path = Path(cand["candidate"]["path"])
                candidate_path = (
                    raw_cand_path
                    if raw_cand_path.is_absolute()
                    else (stage_root / "rt" / "sessions" / sid / "candidates" / run_id / raw_cand_path)
                )
                if not candidate_path.is_file():
                    raise DemoRefusalError("applied candidate artifact is missing")

                verdict = core.module_check(sid, "gongmun", run_id=run_id)
                plan_data = core.plan(plan_id).public()
            except RpcError as exc:
                raise DemoRefusalError(f"{exc.code}: {exc.message}") from exc

            counts = verdict.get("counts") or {}
            if (
                not verdict.get("ranAll")
                or not verdict.get("acceptance")
                or int(counts.get("hard", 1)) != 0
            ):
                raise DemoRefusalError(
                    f"gongmun module_check refused (ranAll={verdict.get('ranAll')}, "
                    f"acceptance={verdict.get('acceptance')}, hard={counts.get('hard')})"
                )

            if _POST_PLAN_HOOK is not None:
                hook_ctx = DemoPostPlanContext(
                    brief=brief,
                    form_path=form_input,
                    candidate_path=candidate_path,
                    out_dir=out_p,
                    plan=plan_data,
                    approval=approval_data,
                    verdict=verdict,
                    ops=ops,
                )
                _POST_PLAN_HOOK(hook_ctx)

            subj_sha = (verdict.get("subject") or {}).get("sha256")
            if not subj_sha:
                raise DemoRefusalError("gongmun verdict missing subject.sha256")

            policy_i_report = verify_policy_i(form_input, candidate_path, ops, brief)

            if resolved_polished is not None:
                policy_ii_report = verify_policy_ii(brief, resolved_polished, modules_root)
                polished_status = "PASS"
            else:
                policy_ii_report = {
                    "status": "skipped",
                    "ok": True,
                    "policy": "draft->polished",
                }
                polished_status = "skipped"

            actual_sha = _sha256_file(candidate_path)
            if subj_sha != actual_sha:
                raise DemoRefusalError(
                    f"candidate sha256 mismatch (verdict={subj_sha}, candidate={actual_sha})"
                )

            verdict_out = _normalize_verdict(verdict, resolved_engine, modules_root, det)
            verdict_out["guard"] = {
                "ok": True,
                "policy_i": policy_i_report,
                "policy_ii": policy_ii_report,
                "paragraphDiff": policy_i_report["paragraphDiff"],
            }
            published_sha = _atomic_publish_outputs(
                stage_root / "out",
                out_p,
                candidate_path,
                plan_data,
                verdict_out,
                approval_data,
            )

    summary = "\n".join([
        "rigorloom demo gongmun: PASS",
        f"form: {resolved_form.name}",
        f"brief: {resolved_brief.name}",
        (
            f"checks: residue hard={res_counts.get('hard', 0)} "
            f"(acceptance={'true' if apply_checks.get('acceptance') else 'false'}, "
            f"ranAll={'true' if apply_checks.get('ranAll') else 'false'}); "
            f"gongmun hard={counts.get('hard', 0)} warn={counts.get('warn', 0)} "
            f"(acceptance={'true' if verdict.get('acceptance') else 'false'}, "
            f"ranAll={'true' if verdict.get('ranAll') else 'false'})"
        ),
        f"policies: form->filled PASS; draft->polished {polished_status}",
        f"sha256: {published_sha}",
        "artifacts: filled.hwpx, plan.json, verdict.json, approval.json",
    ])
    return summary, EXIT_OK


def run_demo_cli(args) -> int:
    """CLI entrypoint called from runtime/scripts/cli.py."""
    _utf8_stdio()
    target = getattr(args, "demo_target", None)
    if target != "gongmun":
        print(f"[USAGE] unsupported demo target: {target!r}", file=sys.stderr)
        return EXIT_USAGE

    try:
        summary, code = run_demo_gongmun(
            out_dir=args.out,
            brief_path=args.brief,
            form_path=args.form,
            polished_path=args.polished,
            engine_root=args.engine_root,
            deterministic=bool(args.deterministic),
        )
    except DemoUsageError as exc:
        print(f"[USAGE] {exc}", file=sys.stderr)
        return EXIT_USAGE
    except DemoRefusalError as exc:
        print(f"[REFUSED] {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except DemoEnvironmentError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    print(summary)
    return code


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="rt_demo_gongmun.py")
    parser.add_argument("--engine-root", default=None)
    sub = parser.add_subparsers(dest="demo_target", required=True)
    p = sub.add_parser("gongmun")
    p.add_argument("--out", required=True)
    p.add_argument("--brief", default=None)
    p.add_argument("--form", default=None)
    p.add_argument("--polished", default=None)
    p.add_argument("--deterministic", action="store_true")
    args = parser.parse_args(argv)
    return run_demo_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
