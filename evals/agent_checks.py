#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine checks for the four P7 agent evaluation tasks (ruling-1.md §4).

Every check inspects documents exclusively through the document layer
(``rt_doc`` or the fake document layer in CI replay) and ``rt_fidelity`` /
``rt_style`` / ``rt_toolset`` — never by string-grepping XML.

Tri-state outcomes follow ruling-1 §2:
    * ``pass``        — verified true;
    * ``fail``        — verified false (or artifact missing/unreadable);
    * ``unavailable`` — the required capability (e.g. page layout without the
                        HWP engine) could not run; NEVER rendered as a pass.

Pass-rule mapping (ruling-1.md §4)
----------------------------------
T1 fill a 신청서:
    * ``seats_hold_values``          -> :func:`check_t1_seats_hold_values`
    * ``diff_confined_to_seats``     -> :func:`check_t1_diff_confined_to_seats`
    * ``signature_seats_untouched``  -> :func:`check_t1_signature_seats_untouched`
    * ``page_count_unchanged``       -> :func:`check_t1_page_count_unchanged`

T2 table in a 20-page 보고서:
    * ``target_cells_correct``       -> :func:`check_t2_target_cells_correct`
    * ``sum_consistent``             -> :func:`check_t2_sum_consistent`
    * ``diff_confined_to_table``     -> :func:`check_t2_diff_confined_to_table`
    * ``no_new_layout_signal``       -> :func:`check_t2_no_new_layout_signal`

T3 보고서 from notes:
    * ``required_headings_present``  -> :func:`check_t3_required_headings_present`
    * ``notes_facts_verbatim``       -> :func:`check_t3_notes_facts_verbatim`
    * ``no_error_check_finding``     -> :func:`check_t3_no_error_check_finding`
    * ``no_lone_heading``            -> :func:`check_t3_no_lone_heading`

T4 convert and check a .hwp:
    * ``output_valid``               -> :func:`check_t4_output_valid`
    * ``paragraph_text_equals_source`` -> :func:`check_t4_paragraph_text_equals_source`
    * ``lossy_and_approx_reported``  -> :func:`check_t4_lossy_and_approx_reported`
"""
from __future__ import annotations

import re
import sys
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

HARNESS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_ROOT.parent
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
ENGINE_SCRIPTS = REPO_ROOT / "engine" / "scripts"

for _p in (str(RUNTIME_SCRIPTS), str(ENGINE_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hwpx_write  # noqa: E402
import rt_fidelity  # noqa: E402
import rt_style  # noqa: E402
import rt_tools  # noqa: E402
import rt_toolset  # noqa: E402
from rt_drafts import DraftStore  # noqa: E402

CHECKS_SCHEMA = "rigorloom-eval-checks/v1"

_UNAVAILABLE_CODES = frozenset({
    "capability_unavailable",
    "engine_unavailable",
    "engine_timeout",
    "unsupported_format",
    "unsupported",
})

_WS_RE = re.compile(r"\s+")
_NUM_EXTRACT_RE = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _result(cid: str, rule: str, status: str, detail: str | None = None,
            evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": cid,
        "rule": rule,
        "status": status,
        "ok": True if status == "pass" else (False if status == "fail" else None),
    }
    if detail:
        out["detail"] = detail
    if evidence is not None:
        out["evidence"] = evidence
    return out


def _err_code(resp: dict | None) -> str:
    if not isinstance(resp, dict):
        return "internal"
    err = resp.get("error") or {}
    return str(err.get("code") or "internal")


def _err_msg(resp: dict | None) -> str:
    if not isinstance(resp, dict):
        return "unexpected non-dict response"
    err = resp.get("error") or {}
    return str(err.get("message") or _err_code(resp))


def _is_unavailable(resp: dict | None) -> bool:
    return isinstance(resp, dict) and not resp.get("ok") and _err_code(resp) in _UNAVAILABLE_CODES


def _need_output(cid: str, rule: str, output_path: Path | None) -> dict[str, Any] | None:
    if output_path is None or not Path(output_path).is_file():
        return _result(cid, rule, "fail",
                       f"output artifact missing: {output_path}")
    if Path(output_path).stat().st_size == 0:
        return _result(cid, rule, "fail",
                       f"output artifact is empty: {output_path}")
    return None


def _read_addr_text(doc_mod: Any, path: Path, at: str) -> tuple[bool, str | None, dict]:
    resp = doc_mod.read(str(path), at=at)
    if not resp.get("ok"):
        return False, None, resp
    blocks = resp.get("blocks") or []
    joined = "\n".join(str(b.get("text") or "") for b in blocks).strip()
    return True, joined, resp


def _read_table_grid(doc_mod: Any, path: Path, table_at: str) -> tuple[bool, list[list[str]] | None, dict]:
    resp = doc_mod.read(str(path), at=table_at)
    if not resp.get("ok"):
        return False, None, resp
    blocks = resp.get("blocks") or []
    if not blocks:
        return False, None, {"ok": False, "error": {"code": "not_found", "message": f"no block at {table_at}"}}
    block = blocks[0]
    cells = block.get("cells") or block.get("grid")
    if isinstance(cells, list):
        return True, [[str(c) for c in row] for row in cells], resp
    text = str(block.get("text") or "")
    rows = [line.split("\t") for line in text.split("\n")] if text else []
    return True, rows, resp


def _all_block_texts(doc_mod: Any, path: Path) -> tuple[bool, list[str], dict]:
    """Ordered text units from ``doc_mod.read(path)`` (paragraphs + table cells)."""
    resp = doc_mod.read(str(path))
    if not resp.get("ok"):
        return False, [], resp
    units: list[str] = []
    for block in resp.get("blocks") or []:
        cells = block.get("cells") or block.get("grid")
        if block.get("kind") == "table" and isinstance(cells, list):
            for row in cells:
                for cell in row:
                    units.append(str(cell))
        elif block.get("kind") == "table":
            for line in str(block.get("text") or "").split("\n"):
                for cell in line.split("\t"):
                    units.append(cell)
        else:
            units.append(str(block.get("text") or ""))
    return True, units, resp


def _page_count(doc_mod: Any, path: Path) -> tuple[str, int | None, str | None]:
    """Return ``('ok', count, None)`` | ``('unavailable', None, reason)`` | ``('fail', None, reason)``."""
    pages_fn = getattr(doc_mod, "pages", None)
    if callable(pages_fn):
        resp = pages_fn(str(path))
        if resp.get("ok") and isinstance(resp.get("count"), int):
            return "ok", resp["count"], None
        if not _is_unavailable(resp) and not resp.get("ok"):
            return "fail", None, _err_msg(resp)
    opened = doc_mod.open(str(path))
    if opened.get("ok") and isinstance(opened.get("pages"), int):
        return "ok", opened["pages"], None
    if not opened.get("ok") and not _is_unavailable(opened):
        return "fail", None, _err_msg(opened)
    return "unavailable", None, "page layout unavailable without engine"


def _layout_signals(doc_mod: Any, path: Path) -> tuple[str, list[dict[str, Any]], str | None]:
    """Return non-``approx`` layout signals from ``doc_mod.pages(path)``."""
    pages_fn = getattr(doc_mod, "pages", None)
    if not callable(pages_fn):
        return "unavailable", [], "doc layer has no pages()"
    resp = pages_fn(str(path))
    if not resp.get("ok"):
        if _is_unavailable(resp):
            return "unavailable", [], _err_msg(resp)
        return "fail", [], _err_msg(resp)
    signals: list[dict[str, Any]] = []
    for pg in resp.get("pages") or []:
        pnum = pg.get("n")
        for sig in pg.get("signals") or []:
            kind = sig if isinstance(sig, str) else sig.get("kind")
            if kind == "approx":
                continue
            at = None if isinstance(sig, str) else sig.get("at")
            signals.append({"page": pnum, "kind": str(kind), "at": at})
    return "ok", signals, None


def _parse_number(cell_text: str) -> Decimal | None:
    m = _NUM_EXTRACT_RE.search(cell_text.strip())
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _normalize_place_id(raw: str) -> str:
    return raw[len("place:"):] if raw.startswith("place:") else raw


def _addr_in_allowed(addr: str | None, allowed: set[str]) -> bool:
    if not addr:
        return False
    if addr in allowed:
        return True
    # Cell-paragraph addresses like t0/r0/c1/p0 belong to cell t0/r0/c1.
    for base in allowed:
        if addr.startswith(base + "/p"):
            return True
    return False


# --------------------------------------------------------------------------- #
# T1: Fill a 신청서
# --------------------------------------------------------------------------- #
def check_t1_seats_hold_values(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    expected_seats: dict[str, str],
    *,
    cid: str = "t1_seats_hold_values",
) -> dict[str, Any]:
    """T1 pass rule 1: every expected seat holds its expected value."""
    missing = _need_output(cid, "seats_hold_values", output_path)
    if missing:
        return missing
    assert output_path is not None

    src_outline = doc_mod.outline(str(source_path))
    if not src_outline.get("ok"):
        return _result(cid, "seats_hold_values", "fail",
                       f"source outline failed: {_err_msg(src_outline)}")
    by_id = {p["id"]: p for p in src_outline.get("places") or []}

    mismatches: dict[str, dict[str, Any]] = {}
    checked: dict[str, dict[str, Any]] = {}
    for raw_key, expected in expected_seats.items():
        pid = _normalize_place_id(raw_key)
        place = by_id.get(pid)
        if place is None:
            mismatches[pid] = {"at": None, "expected": expected, "actual": None,
                               "error": "place not in source outline"}
            continue
        at = place["at"]
        ok_read, actual, resp = _read_addr_text(doc_mod, output_path, at)
        if not ok_read:
            mismatches[pid] = {"at": at, "expected": expected, "actual": None,
                               "error": _err_msg(resp)}
            continue
        checked[pid] = {"at": at, "expected": expected, "actual": actual}
        if _norm_ws(actual or "") != _norm_ws(str(expected)):
            mismatches[pid] = {"at": at, "expected": expected, "actual": actual}

    if mismatches:
        return _result(cid, "seats_hold_values", "fail",
                       f"{len(mismatches)} seat(s) missing or mismatched",
                       {"mismatches": mismatches, "checked": checked})
    return _result(cid, "seats_hold_values", "pass",
                   evidence={"checked": checked})


def check_t1_diff_confined_to_seats(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    seat_ids: Iterable[str],
    *,
    cid: str = "t1_diff_confined_to_seats",
) -> dict[str, Any]:
    """T1 pass rule 2: diff between source and output is confined to expected seats."""
    missing = _need_output(cid, "diff_confined_to_seats", output_path)
    if missing:
        return missing
    assert output_path is not None

    src_outline = doc_mod.outline(str(source_path))
    if not src_outline.get("ok"):
        return _result(cid, "diff_confined_to_seats", "fail",
                       f"source outline failed: {_err_msg(src_outline)}")
    by_id = {p["id"]: p for p in src_outline.get("places") or []}
    wanted = [_normalize_place_id(s) for s in seat_ids]
    allowed_addrs = {by_id[pid]["at"] for pid in wanted if pid in by_id}

    diff_resp = doc_mod.diff(str(source_path), str(output_path))
    if not diff_resp.get("ok"):
        return _result(cid, "diff_confined_to_seats", "fail",
                       f"diff failed: {_err_msg(diff_resp)}")
    changes = diff_resp.get("changes") or []
    if not changes and wanted:
        return _result(cid, "diff_confined_to_seats", "fail",
                       "no changes detected between source and output (vacuous fill)",
                       {"allowed": sorted(allowed_addrs), "changes": []})

    outside = [ch for ch in changes if not _addr_in_allowed(ch.get("at"), allowed_addrs)]
    if outside:
        return _result(cid, "diff_confined_to_seats", "fail",
                       f"{len(outside)} change(s) outside expected seats",
                       {"allowed": sorted(allowed_addrs), "outside": outside})
    return _result(cid, "diff_confined_to_seats", "pass",
                   evidence={"allowed": sorted(allowed_addrs), "change_count": len(changes)})


def check_t1_signature_seats_untouched(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    signature_seat_ids: Iterable[str] | None = None,
    *,
    cid: str = "t1_signature_seats_untouched",
) -> dict[str, Any]:
    """T1 pass rule 3: every signature/seal seat remains untouched."""
    missing = _need_output(cid, "signature_seats_untouched", output_path)
    if missing:
        return missing
    assert output_path is not None

    src_outline = doc_mod.outline(str(source_path))
    if not src_outline.get("ok"):
        return _result(cid, "signature_seats_untouched", "fail",
                       f"source outline failed: {_err_msg(src_outline)}")
    places = src_outline.get("places") or []
    explicit = {_normalize_place_id(s) for s in (signature_seat_ids or ())}
    sig_places = [
        p for p in places
        if rt_toolset.is_person_only(p) or p.get("id") in explicit
    ]
    if not sig_places:
        return _result(cid, "signature_seats_untouched", "fail",
                       "no signature/seal seats found in source outline (vacuous check)")

    touched: list[dict[str, Any]] = []
    for p in sig_places:
        at = p["at"]
        ok_s, before, _ = _read_addr_text(doc_mod, source_path, at)
        ok_o, after, resp_o = _read_addr_text(doc_mod, output_path, at)
        if not ok_s or not ok_o:
            touched.append({"id": p["id"], "at": at, "error": _err_msg(resp_o)})
            continue
        if _norm_ws(before or "") != _norm_ws(after or "") or _norm_ws(after or ""):
            touched.append({"id": p["id"], "at": at, "before": before, "after": after})

    diff_resp = doc_mod.diff(str(source_path), str(output_path))
    if diff_resp.get("ok"):
        sig_addrs = {p["at"] for p in sig_places}
        for ch in diff_resp.get("changes") or []:
            if _addr_in_allowed(ch.get("at"), sig_addrs):
                if not any(t.get("at") == ch.get("at") for t in touched):
                    touched.append({"at": ch.get("at"), "before": ch.get("before"),
                                    "after": ch.get("after")})

    if touched:
        return _result(cid, "signature_seats_untouched", "fail",
                       f"{len(touched)} signature/seal seat(s) were modified",
                       {"touched": touched, "checked_seats": [p["id"] for p in sig_places]})
    return _result(cid, "signature_seats_untouched", "pass",
                   evidence={"checked_seats": [p["id"] for p in sig_places]})


def check_t1_page_count_unchanged(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    *,
    cid: str = "t1_page_count_unchanged",
) -> dict[str, Any]:
    """T1 pass rule 4: page count unchanged between source and output."""
    missing = _need_output(cid, "page_count_unchanged", output_path)
    if missing:
        return missing
    assert output_path is not None

    st_a, pages_a, msg_a = _page_count(doc_mod, source_path)
    if st_a != "ok":
        return _result(cid, "page_count_unchanged", st_a, msg_a)
    st_b, pages_b, msg_b = _page_count(doc_mod, output_path)
    if st_b != "ok":
        return _result(cid, "page_count_unchanged", st_b, msg_b)

    if pages_a != pages_b:
        return _result(cid, "page_count_unchanged", "fail",
                       f"page count changed: {pages_a} -> {pages_b}",
                       {"before": pages_a, "after": pages_b})
    return _result(cid, "page_count_unchanged", "pass",
                   evidence={"before": pages_a, "after": pages_b})


# --------------------------------------------------------------------------- #
# T2: Edit a table in a 20-page 보고서
# --------------------------------------------------------------------------- #
def check_t2_target_cells_correct(
    doc_mod: Any,
    output_path: Path | None,
    table_at: str,
    expected_cells: list[dict[str, Any]],
    *,
    cid: str = "t2_target_cells_correct",
) -> dict[str, Any]:
    """T2 pass rule 1: every target cell holds its expected value."""
    missing = _need_output(cid, "target_cells_correct", output_path)
    if missing:
        return missing
    assert output_path is not None

    ok_grid, grid, resp = _read_table_grid(doc_mod, output_path, table_at)
    if not ok_grid or grid is None:
        return _result(cid, "target_cells_correct", "fail",
                       f"could not read table {table_at}: {_err_msg(resp)}")

    mismatches: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    for spec in expected_cells:
        r, c = int(spec["row"]), int(spec["col"])
        expected = str(spec["expected"])
        at = f"{table_at}/r{r}/c{c}"
        if r >= len(grid) or c >= len(grid[r]):
            mismatches.append({"at": at, "expected": expected, "actual": None,
                               "error": "cell out of range"})
            continue
        actual = grid[r][c]
        row_info = {"at": at, "expected": expected, "actual": actual}
        checked.append(row_info)
        if _norm_ws(actual) != _norm_ws(expected):
            mismatches.append(row_info)

    if mismatches:
        return _result(cid, "target_cells_correct", "fail",
                       f"{len(mismatches)} target cell(s) mismatched in {table_at}",
                       {"mismatches": mismatches, "checked": checked})
    return _result(cid, "target_cells_correct", "pass",
                   evidence={"table": table_at, "checked": checked})


def check_t2_sum_consistent(
    doc_mod: Any,
    output_path: Path | None,
    table_at: str,
    sum_row: int,
    addend_rows: list[int],
    sum_cols: list[int],
    *,
    label_col: int = 0,
    label_expected: str = "합계",
    cid: str = "t2_sum_consistent",
) -> dict[str, Any]:
    """T2 pass rule 2: 합계 row equals the arithmetic sum of its addend rows."""
    missing = _need_output(cid, "sum_consistent", output_path)
    if missing:
        return missing
    assert output_path is not None

    ok_grid, grid, resp = _read_table_grid(doc_mod, output_path, table_at)
    if not ok_grid or grid is None:
        return _result(cid, "sum_consistent", "fail",
                       f"could not read table {table_at}: {_err_msg(resp)}")
    if sum_row >= len(grid) or label_col >= len(grid[sum_row]):
        return _result(cid, "sum_consistent", "fail",
                       f"sum row r{sum_row} missing in {table_at}")
    label_actual = _norm_ws(grid[sum_row][label_col])
    if label_expected and label_expected not in label_actual:
        return _result(cid, "sum_consistent", "fail",
                       f"sum row label at {table_at}/r{sum_row}/c{label_col} "
                       f"expected {label_expected!r}, got {label_actual!r}")

    failures: list[dict[str, Any]] = []
    columns_checked: list[dict[str, Any]] = []
    for col in sum_cols:
        addends: list[Decimal] = []
        raw_addends: list[str] = []
        parse_err = None
        for r in addend_rows:
            if r >= len(grid) or col >= len(grid[r]):
                parse_err = f"addend cell {table_at}/r{r}/c{col} out of range"
                break
            raw = grid[r][col]
            raw_addends.append(raw)
            num = _parse_number(raw)
            if num is None:
                parse_err = f"non-numeric addend at {table_at}/r{r}/c{col}: {raw!r}"
                break
            addends.append(num)
        if parse_err:
            failures.append({"col": col, "error": parse_err})
            continue
        if col >= len(grid[sum_row]):
            failures.append({"col": col, "error": f"sum cell {table_at}/r{sum_row}/c{col} out of range"})
            continue
        raw_sum = grid[sum_row][col]
        reported = _parse_number(raw_sum)
        expected_sum = sum(addends, Decimal(0))
        entry = {
            "col": col,
            "addends": [str(a) for a in addends],
            "raw_addends": raw_addends,
            "expected_sum": str(expected_sum),
            "reported_sum": str(reported) if reported is not None else None,
            "raw_sum": raw_sum,
        }
        columns_checked.append(entry)
        if reported is None or reported != expected_sum:
            failures.append(entry)

    if failures:
        return _result(cid, "sum_consistent", "fail",
                       f"합계 inconsistent in {len(failures)} column(s) of {table_at}",
                       {"failures": failures, "columns": columns_checked})
    return _result(cid, "sum_consistent", "pass",
                   evidence={"table": table_at, "columns": columns_checked})


def check_t2_diff_confined_to_table(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    table_at: str,
    *,
    cid: str = "t2_diff_confined_to_table",
) -> dict[str, Any]:
    """T2 pass rule 3: diff between source and output is confined to the target table."""
    missing = _need_output(cid, "diff_confined_to_table", output_path)
    if missing:
        return missing
    assert output_path is not None

    diff_resp = doc_mod.diff(str(source_path), str(output_path))
    if not diff_resp.get("ok"):
        return _result(cid, "diff_confined_to_table", "fail",
                       f"diff failed: {_err_msg(diff_resp)}")
    changes = diff_resp.get("changes") or []
    if not changes:
        return _result(cid, "diff_confined_to_table", "fail",
                       f"no changes detected in {table_at} (vacuous edit)")

    prefix = table_at + "/"
    outside = [
        ch for ch in changes
        if not (isinstance(ch.get("at"), str)
                and (ch["at"] == table_at or ch["at"].startswith(prefix)))
    ]
    if outside:
        return _result(cid, "diff_confined_to_table", "fail",
                       f"{len(outside)} change(s) outside {table_at}",
                       {"table": table_at, "outside": outside})
    return _result(cid, "diff_confined_to_table", "pass",
                   evidence={"table": table_at, "change_count": len(changes)})


def check_t2_no_new_layout_signal(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    *,
    cid: str = "t2_no_new_layout_signal",
) -> dict[str, Any]:
    """T2 pass rule 4: no new layout signal introduced compared to source."""
    missing = _need_output(cid, "no_new_layout_signal", output_path)
    if missing:
        return missing
    assert output_path is not None

    st_a, sig_a, msg_a = _layout_signals(doc_mod, source_path)
    if st_a != "ok":
        return _result(cid, "no_new_layout_signal", st_a, msg_a)
    st_b, sig_b, msg_b = _layout_signals(doc_mod, output_path)
    if st_b != "ok":
        return _result(cid, "no_new_layout_signal", st_b, msg_b)

    cnt_a = Counter((s["kind"], s.get("at")) for s in sig_a)
    cnt_b = Counter((s["kind"], s.get("at")) for s in sig_b)
    new_sigs = []
    for key, count in cnt_b.items():
        if count > cnt_a.get(key, 0):
            new_sigs.append({"kind": key[0], "at": key[1],
                             "before": cnt_a.get(key, 0), "after": count})
    if new_sigs:
        return _result(cid, "no_new_layout_signal", "fail",
                       f"{len(new_sigs)} new layout signal(s) appeared after edit",
                       {"new_signals": new_sigs, "before": sig_a, "after": sig_b})
    return _result(cid, "no_new_layout_signal", "pass",
                   evidence={"before_count": len(sig_a), "after_count": len(sig_b)})


# --------------------------------------------------------------------------- #
# T3: Write a 보고서 from notes
# --------------------------------------------------------------------------- #
def check_t3_required_headings_present(
    doc_mod: Any,
    output_path: Path | None,
    required_headings: list[str],
    *,
    cid: str = "t3_required_headings_present",
) -> dict[str, Any]:
    """T3 pass rule 1: every required heading appears in ``rt_doc.outline()``."""
    missing_file = _need_output(cid, "required_headings_present", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    out = doc_mod.outline(str(output_path))
    if not out.get("ok"):
        return _result(cid, "required_headings_present", "fail",
                       f"outline failed: {_err_msg(out)}")
    found = [_norm_ws(str(h.get("text") or "")) for h in out.get("headings") or []]
    missing = [h for h in required_headings if _norm_ws(h) not in found]
    if missing:
        return _result(cid, "required_headings_present", "fail",
                       f"{len(missing)} required heading(s) missing",
                       {"missing": missing, "found": found})
    return _result(cid, "required_headings_present", "pass",
                   evidence={"required": required_headings, "found": found})


def _verbatim_token_present(token: str, haystack: str) -> bool:
    tok = token.strip()
    if not tok:
        return True
    # Guard numeric boundaries so e.g. "18" cannot match "18.5" or "218".
    prefix = r"(?<!\d)" if tok[0].isdigit() else ""
    suffix = r"(?![\d.])" if tok[-1].isdigit() else ""
    return re.search(prefix + re.escape(tok) + suffix, haystack) is not None


def check_t3_notes_facts_verbatim(
    doc_mod: Any,
    output_path: Path | None,
    notes_text: str,
    *,
    required_names: list[str] | None = None,
    required_dates: list[str] | None = None,
    required_numbers: list[str] | None = None,
    cid: str = "t3_notes_facts_verbatim",
) -> dict[str, Any]:
    """T3 pass rule 2: every number, date and name from notes appears verbatim.

    Uses ``rt_doc.read()`` for document text and ``rt_fidelity.extract_protected()``
    to harvest protected numbers and dates directly from ``notes_text``, plus
    explicit required names/dates/numbers declared on the task.
    """
    missing_file = _need_output(cid, "notes_facts_verbatim", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    ok_rd, units, resp = _all_block_texts(doc_mod, output_path)
    if not ok_rd:
        return _result(cid, "notes_facts_verbatim", "fail",
                       f"read failed: {_err_msg(resp)}")
    doc_text = "\n".join(units)

    notes_prot = rt_fidelity.extract_protected(notes_text)
    doc_prot = rt_fidelity.extract_protected(doc_text)

    missing_dates: list[str] = []
    for dt in dict.fromkeys(list(notes_prot.get("dates") or {}) + list(required_dates or ())):
        if not _verbatim_token_present(dt, doc_text):
            missing_dates.append(dt)

    missing_numbers: list[str] = []
    doc_num_counts = doc_prot.get("numbers") or {}
    for num in (notes_prot.get("numbers") or {}):
        if num not in doc_num_counts and not _verbatim_token_present(num, doc_text):
            missing_numbers.append(num)
    for num in (required_numbers or ()):
        if not _verbatim_token_present(num, doc_text) and num not in missing_numbers:
            missing_numbers.append(num)

    missing_names: list[str] = []
    for name in (required_names or ()):
        if name not in doc_text:
            missing_names.append(name)

    if missing_dates or missing_numbers or missing_names:
        return _result(
            cid, "notes_facts_verbatim", "fail",
            f"missing verbatim facts from notes "
            f"(numbers={len(missing_numbers)}, dates={len(missing_dates)}, "
            f"names={len(missing_names)})",
            {
                "missing_numbers": missing_numbers,
                "missing_dates": missing_dates,
                "missing_names": missing_names,
            },
        )
    return _result(
        cid, "notes_facts_verbatim", "pass",
        evidence={
            "checked_numbers": sorted(set(notes_prot.get("numbers") or {}) | set(required_numbers or ())),
            "checked_dates": sorted(set(notes_prot.get("dates") or {}) | set(required_dates or ())),
            "checked_names": list(required_names or ()),
        },
    )


def check_t3_no_error_check_finding(
    doc_mod: Any,
    output_path: Path | None,
    *,
    pack: str | None = None,
    cid: str = "t3_no_error_check_finding",
) -> dict[str, Any]:
    """T3 pass rule 3: zero error-level findings from ``check`` (and ``rt_style``)."""
    missing_file = _need_output(cid, "no_error_check_finding", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    errors: list[dict[str, Any]] = []
    # Run the registered `check` tool on the output document (allowing .fdoc when fake).
    orig_in = rt_toolset.FORMATS_IN
    suffix = output_path.suffix.lower().lstrip(".")
    added_suffix = False
    if suffix and suffix not in rt_toolset.FORMATS_IN:
        rt_toolset.FORMATS_IN = rt_toolset.FORMATS_IN + (suffix,)
        added_suffix = True
    try:
        with tempfile.TemporaryDirectory(prefix="rigorloom-eval-check-") as td:
            ctx = rt_tools.Context(
                client="eval", roots=None, source="disk",
                _doc=doc_mod, _drafts=DraftStore(Path(td)),
            )
            req: dict[str, Any] = {
                "path": str(output_path),
                "only": ["style", "layout", "fonts"],
            }
            if pack:
                req["pack"] = pack
            env = rt_tools.call(ctx, "check", req)
    finally:
        if added_suffix:
            rt_toolset.FORMATS_IN = orig_in

    if not env.get("ok"):
        code = (env.get("error") or {}).get("code")
        if code in _UNAVAILABLE_CODES:
            return _result(cid, "no_error_check_finding", "unavailable",
                           (env.get("error") or {}).get("message"))
        return _result(cid, "no_error_check_finding", "fail",
                       f"check tool refused: {env.get('error')}")

    res = env["result"]
    for finding in res.get("findings") or []:
        if finding.get("severity") == "error":
            errors.append(finding)

    # Also evaluate rt_style's Korean report rules over rt_doc.read() blocks so
    # fake doc layers (whose stub style() only emits notices) still enforce real
    # error-severity Korean style rules (e.g. ko.double-passive).
    ok_rd, units, _ = _all_block_texts(doc_mod, output_path)
    if ok_rd:
        style_rules = rt_style.rules_for("report")
        seen = {(e.get("rule"), e.get("match")) for e in errors}
        for f in rt_style.check_text(units, style_rules):
            if f.get("severity") == "error":
                key = (f.get("rule"), f.get("match"))
                if key not in seen:
                    seen.add(key)
                    errors.append({"check": "style", **f})

    if errors:
        return _result(cid, "no_error_check_finding", "fail",
                       f"{len(errors)} error-level check finding(s)",
                       {"errors": errors})
    if res.get("pass") is None and not ok_rd:
        return _result(cid, "no_error_check_finding", "unavailable",
                       "no check could run on output")
    return _result(cid, "no_error_check_finding", "pass",
                   evidence={"checks": res.get("checks"), "error_count": 0})


def check_t3_no_lone_heading(
    doc_mod: Any,
    output_path: Path | None,
    *,
    cid: str = "t3_no_lone_heading",
) -> dict[str, Any]:
    """T3 pass rule 4: zero ``lone_heading`` signals across all pages."""
    missing_file = _need_output(cid, "no_lone_heading", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    st, sigs, msg = _layout_signals(doc_mod, output_path)
    if st != "ok":
        return _result(cid, "no_lone_heading", st, msg)
    lones = [s for s in sigs if s.get("kind") == "lone_heading"]
    if lones:
        return _result(cid, "no_lone_heading", "fail",
                       f"{len(lones)} lone_heading signal(s) found",
                       {"lone_headings": lones})
    return _result(cid, "no_lone_heading", "pass",
                   evidence={"lone_headings": []})


# --------------------------------------------------------------------------- #
# T4: Convert and check a .hwp
# --------------------------------------------------------------------------- #
def check_t4_output_valid(
    doc_mod: Any,
    output_path: Path | None,
    *,
    cid: str = "t4_output_valid",
) -> dict[str, Any]:
    """T4 pass rule 1: converted output is a valid, readable document."""
    missing_file = _need_output(cid, "output_valid", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    if output_path.suffix.lower() == ".hwpx":
        try:
            pkg = hwpx_write.HwpxPackage.read(output_path)
            pkg.validate()
        except Exception as exc:  # noqa: BLE001
            return _result(cid, "output_valid", "fail",
                           f"invalid HWPX package: {exc}")

    opened = doc_mod.open(str(output_path))
    if not opened.get("ok"):
        status = "unavailable" if _is_unavailable(opened) else "fail"
        return _result(cid, "output_valid", status,
                       f"open failed: {_err_msg(opened)}")
    rd = doc_mod.read(str(output_path))
    if not rd.get("ok"):
        status = "unavailable" if _is_unavailable(rd) else "fail"
        return _result(cid, "output_valid", status,
                       f"read failed: {_err_msg(rd)}")
    blocks = rd.get("blocks") or []
    if not blocks:
        return _result(cid, "output_valid", "fail",
                       "converted output contains zero readable blocks")
    return _result(cid, "output_valid", "pass",
                   evidence={"format": opened.get("format"), "blocks": len(blocks)})


def check_t4_paragraph_text_equals_source(
    doc_mod: Any,
    source_path: Path,
    output_path: Path | None,
    *,
    cid: str = "t4_paragraph_text_equals_source",
) -> dict[str, Any]:
    """T4 pass rule 2: paragraph text of output equals the source."""
    missing_file = _need_output(cid, "paragraph_text_equals_source", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    ok_a, units_a, resp_a = _all_block_texts(doc_mod, source_path)
    if not ok_a:
        status = "unavailable" if _is_unavailable(resp_a) else "fail"
        return _result(cid, "paragraph_text_equals_source", status,
                       f"source read failed: {_err_msg(resp_a)}")
    ok_b, units_b, resp_b = _all_block_texts(doc_mod, output_path)
    if not ok_b:
        status = "unavailable" if _is_unavailable(resp_b) else "fail"
        return _result(cid, "paragraph_text_equals_source", status,
                       f"output read failed: {_err_msg(resp_b)}")

    norm_a = [_norm_ws(u) for u in units_a if _norm_ws(u)]
    norm_b = [_norm_ws(u) for u in units_b if _norm_ws(u)]
    if norm_a != norm_b:
        return _result(cid, "paragraph_text_equals_source", "fail",
                       f"paragraph text differs (source={len(norm_a)} blocks, "
                       f"output={len(norm_b)} blocks)",
                       {"source_blocks": norm_a[:20], "output_blocks": norm_b[:20]})
    return _result(cid, "paragraph_text_equals_source", "pass",
                   evidence={"block_count": len(norm_b)})


def _collect_lossy_and_approx(
    doc_mod: Any,
    output_path: Path,
    transcript_events: list[dict[str, Any]] | None,
    extra_lossy: Iterable[str] | None,
    extra_approx: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    lossy: list[str] = []
    approx: list[str] = []

    def add_lossy(item: Any) -> None:
        s = str(item).strip()
        if s and s not in lossy:
            lossy.append(s)

    def add_approx(item: Any) -> None:
        if isinstance(item, dict):
            want = str(item.get("want") or "").strip()
            got = str(item.get("got") or "").strip()
            label = f"{want}→{got}" if want and got else (want or got)
        else:
            label = str(item).strip()
        if label and label not in approx:
            approx.append(label)

    for item in extra_lossy or ():
        add_lossy(item)
    for item in extra_approx or ():
        add_approx(item)

    for ev in transcript_events or ():
        sc = ev.get("structured") or ev.get("result") or {}
        if not isinstance(sc, dict):
            continue
        for item in sc.get("lossy") or ():
            add_lossy(item)
        fonts = sc.get("fonts") or {}
        if isinstance(fonts, dict):
            for sub in fonts.get("substituted") or ():
                add_approx(sub)
        for sig in sc.get("signals") or ():
            if isinstance(sig, dict) and sig.get("kind") == "approx":
                for f in sig.get("fonts") or ():
                    add_approx(f)
                if not sig.get("fonts"):
                    add_approx("approx")
        for finding in sc.get("findings") or ():
            if isinstance(finding, dict) and finding.get("rule") == "fonts.substituted":
                msg = str(finding.get("message") or "")
                m = re.match(r"^(\S+)\s+글꼴이 없어\s+(\S+)로", msg)
                if m:
                    add_approx(f"{m.group(1)}→{m.group(2)}")

    opened = doc_mod.open(str(output_path))
    if opened.get("ok"):
        for sub in (opened.get("fonts") or {}).get("substituted") or ():
            add_approx(sub)
    pages_fn = getattr(doc_mod, "pages", None)
    if callable(pages_fn):
        pg = pages_fn(str(output_path))
        if pg.get("ok"):
            for item in pg.get("approx") or ():
                add_approx(item)

    return lossy, approx


def _approx_mentioned(item: str, answer_lower: str) -> bool:
    if item.lower() in answer_lower:
        return True
    if "→" in item:
        want, got = (part.strip().lower() for part in item.split("→", 1))
        if want and want in answer_lower and (not got or got in answer_lower or "대체" in answer_lower or "approx" in answer_lower or "substitut" in answer_lower):
            return True
    return False


def check_t4_lossy_and_approx_reported(
    doc_mod: Any,
    output_path: Path | None,
    final_answer: str,
    *,
    transcript_events: list[dict[str, Any]] | None = None,
    expected_lossy: Iterable[str] | None = None,
    expected_approx: Iterable[str] | None = None,
    cid: str = "t4_lossy_and_approx_reported",
) -> dict[str, Any]:
    """T4 pass rule 3: when ``lossy`` or ``approx`` is present, final answer reports it."""
    missing_file = _need_output(cid, "lossy_and_approx_reported", output_path)
    if missing_file:
        return missing_file
    assert output_path is not None

    lossy, approx = _collect_lossy_and_approx(
        doc_mod, output_path, transcript_events, expected_lossy, expected_approx
    )
    answer = str(final_answer or "")
    answer_lower = answer.lower()

    missing_lossy = [item for item in lossy if item.lower() not in answer_lower]
    missing_approx = [item for item in approx if not _approx_mentioned(item, answer_lower)]

    if missing_lossy or missing_approx:
        return _result(
            cid, "lossy_and_approx_reported", "fail",
            f"unreported conversion caveats (missing_lossy={missing_lossy}, "
            f"missing_approx={missing_approx})",
            {
                "lossy": lossy,
                "approx": approx,
                "missing_lossy": missing_lossy,
                "missing_approx": missing_approx,
            },
        )
    return _result(
        cid, "lossy_and_approx_reported", "pass",
        evidence={"lossy": lossy, "approx": approx},
    )


# --------------------------------------------------------------------------- #
# Rule dispatcher for a task YAML
# --------------------------------------------------------------------------- #
def evaluate_task_checks(
    task: dict[str, Any],
    doc_mod: Any,
    *,
    task_dir: Path,
    source_path: Path | None,
    output_path: Path | None,
    final_answer: str = "",
    transcript_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run every declared ``pass_rule`` for an agent-eval task definition."""
    results: list[dict[str, Any]] = []
    for spec in task.get("pass_rules") or []:
        cid = spec["id"]
        rule = spec["rule"]
        if rule == "seats_hold_values":
            assert source_path is not None
            row = check_t1_seats_hold_values(
                doc_mod, source_path, output_path, spec["seats"], cid=cid)
        elif rule == "diff_confined_to_seats":
            assert source_path is not None
            row = check_t1_diff_confined_to_seats(
                doc_mod, source_path, output_path, spec["seat_ids"], cid=cid)
        elif rule == "signature_seats_untouched":
            assert source_path is not None
            row = check_t1_signature_seats_untouched(
                doc_mod, source_path, output_path,
                spec.get("signature_seat_ids"), cid=cid)
        elif rule == "page_count_unchanged":
            assert source_path is not None
            row = check_t1_page_count_unchanged(
                doc_mod, source_path, output_path, cid=cid)
        elif rule == "target_cells_correct":
            row = check_t2_target_cells_correct(
                doc_mod, output_path, spec["table"], spec["cells"], cid=cid)
        elif rule == "sum_consistent":
            row = check_t2_sum_consistent(
                doc_mod, output_path, spec["table"],
                sum_row=int(spec["sum_row"]),
                addend_rows=[int(r) for r in spec["addend_rows"]],
                sum_cols=[int(c) for c in spec["sum_cols"]],
                label_col=int(spec.get("label_col", 0)),
                label_expected=str(spec.get("label_expected", "합계")),
                cid=cid)
        elif rule == "diff_confined_to_table":
            assert source_path is not None
            row = check_t2_diff_confined_to_table(
                doc_mod, source_path, output_path, spec["table"], cid=cid)
        elif rule == "no_new_layout_signal":
            assert source_path is not None
            row = check_t2_no_new_layout_signal(
                doc_mod, source_path, output_path, cid=cid)
        elif rule == "required_headings_present":
            row = check_t3_required_headings_present(
                doc_mod, output_path, list(spec["headings"]), cid=cid)
        elif rule == "notes_facts_verbatim":
            notes_file = Path(task_dir) / spec.get("notes_file", "notes.md")
            notes_text = notes_file.read_text(encoding="utf-8") if notes_file.is_file() else ""
            row = check_t3_notes_facts_verbatim(
                doc_mod, output_path, notes_text,
                required_names=list(spec.get("required_names") or ()),
                required_dates=list(spec.get("required_dates") or ()),
                required_numbers=list(spec.get("required_numbers") or ()),
                cid=cid)
        elif rule == "no_error_check_finding":
            row = check_t3_no_error_check_finding(
                doc_mod, output_path, pack=spec.get("pack"), cid=cid)
        elif rule == "no_lone_heading":
            row = check_t3_no_lone_heading(doc_mod, output_path, cid=cid)
        elif rule == "output_valid":
            row = check_t4_output_valid(doc_mod, output_path, cid=cid)
        elif rule == "paragraph_text_equals_source":
            assert source_path is not None
            row = check_t4_paragraph_text_equals_source(
                doc_mod, source_path, output_path, cid=cid)
        elif rule == "lossy_and_approx_reported":
            row = check_t4_lossy_and_approx_reported(
                doc_mod, output_path, final_answer,
                transcript_events=transcript_events, cid=cid)
        else:  # pragma: no cover - guarded by validate_agent_task
            row = _result(cid, rule, "fail", f"unknown pass rule: {rule!r}")
        results.append(row)

    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    unavailable = sum(1 for r in results if r["status"] == "unavailable")
    if failed > 0:
        overall: bool | None = False
    elif unavailable > 0:
        overall = None
    else:
        overall = passed > 0

    return {
        "schema": CHECKS_SCHEMA,
        "task_id": task["id"],
        "counts": {
            "pass": passed,
            "fail": failed,
            "skipped": skipped,
            "unavailable": unavailable,
            "total": len(results),
        },
        "ok": overall,
        "checks": results,
    }
