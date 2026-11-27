"""Measure editor v2 typing load on the gongmun walkthrough with the page engine."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time

import pytest

from _browser_gate import no_browser
from _editor_v2 import editor_v2_url
from _runtime_client import runtime_scripts_on_path
from _v1_identity import launch_browser, start_bridge

runtime_scripts_on_path()
import rt_doc  # noqa: E402
import rt_ui_doc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
GONGMUN_PLAN_PATH = REPO_ROOT / "examples" / "gongmun" / "expected" / "plan.json"


@dataclass(frozen=True)
class SeatStep:
    cell_key: str
    label: str
    text: str
    pause_after: int
    commit_key: str


def _build_walkthrough_steps() -> list[SeatStep]:
    plan = json.loads(GONGMUN_PLAN_PATH.read_text(encoding="utf-8"))
    by_cell: dict[tuple[int, int, int], str] = {}
    for op in plan["ops"]:
        params = op["params"]
        key = (params["table"], params["row"], params["col"])
        if op["kind"] == "replace_at_cell" and params.get("text"):
            by_cell.setdefault(key, params["text"])
        elif op["kind"] == "fill_cell":
            lines = params.get("lines")
            text = lines[0] if isinstance(lines, list) and lines else params.get("text")
            if text:
                by_cell.setdefault(key, text)

    return [
        SeatStep("c:0:2:0", "본문", by_cell[(0, 2, 0)], 6, "Enter"),
        SeatStep("c:0:4:0", "기안자", by_cell[(0, 4, 0)], 4, "Tab"),
        SeatStep("c:0:4:3", "검토자", by_cell[(0, 4, 3)], 4, "Tab"),
        SeatStep("c:0:4:9", "결재권자", by_cell[(0, 4, 9)], 3, "Enter"),
        SeatStep("c:0:5:1", "협조자 1", "기획조정실", 2, "Enter"),
        SeatStep("c:0:6:1", "시행일", by_cell[(0, 6, 1)], 6, "Enter"),
        SeatStep("c:0:7:0", "우", by_cell[(0, 7, 0)], 2, "Tab"),
        SeatStep("c:0:7:1", "도로명주소", by_cell[(0, 7, 1)], 4, "Enter"),
        SeatStep("c:0:7:7", "홈페이지 주소", by_cell[(0, 7, 7)], 8, "Enter"),
        SeatStep("c:0:8:0", "전화번호", by_cell[(0, 8, 0)], 5, "Tab"),
        SeatStep("c:0:8:2", "팩스번호", by_cell[(0, 8, 2)], 5, "Enter"),
        SeatStep("c:0:8:7", "전자우편주소", by_cell[(0, 8, 7)], 7, "Enter"),
        SeatStep("c:0:8:12", "공개 구분", by_cell[(0, 8, 12)], 2, "Enter"),
        SeatStep("c:2:0:0", "발신명의", by_cell[(2, 0, 0)], 4, "Enter"),
    ]


def _import_playwright():
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:
        no_browser(f"playwright Python package unavailable: {exc}")
    return sync_playwright, expect


def _list_preview_scratch(baseline: set[str]) -> list[str]:
    pdir = rt_doc._scratch() / "preview"
    if not pdir.is_dir():
        return []
    try:
        return sorted(
            ent.name
            for ent in os.scandir(pdir)
            if ent.is_file(follow_symlinks=False)
            and not ent.name.startswith(".")
            and ent.name not in baseline
        )
    except OSError:
        return []


def _server_page_gateway(server) -> rt_ui_doc.PageGateway:
    handler = server.extensions.post_routes["/api/doc/preview"]
    for cell in handler.__closure__ or ():
        if isinstance(cell.cell_contents, rt_ui_doc.PageGateway):
            return cell.cell_contents
    raise AssertionError("PageGateway not found on /api/doc/preview route")


@pytest.mark.skipif(
    not os.environ.get("RIGORLOOM_HWP_ENGINE"),
    reason="RIGORLOOM_HWP_ENGINE is unset",
)
def test_editor_v2_gongmun_walkthrough_typing_load(tmp_path: Path, monkeypatch) -> None:
    sync_playwright, expect = _import_playwright()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    steps = _build_walkthrough_steps()
    baseline_scratch = set(_list_preview_scratch(set()))
    scratch_lock = threading.Lock()
    scratch_seen: set[str] = set()
    scratch_peak = 0
    stop_sampling = threading.Event()

    def sample_scratch() -> int:
        nonlocal scratch_peak
        current = _list_preview_scratch(baseline_scratch)
        with scratch_lock:
            scratch_seen.update(current)
            if len(current) > scratch_peak:
                scratch_peak = len(current)
        return len(current)

    def sampler_loop() -> None:
        while not stop_sampling.is_set():
            sample_scratch()
            stop_sampling.wait(0.015)

    server, thread = start_bridge(tmp_path)
    sampler = threading.Thread(target=sampler_loop, name="scratch-sampler", daemon=True)
    sampler.start()
    try:
        with sync_playwright() as pw:
            try:
                browser = launch_browser(pw)
            except Exception as exc:
                no_browser(f"headless Chromium unavailable: {exc}")
            try:
                with browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light") as page:
                    # Wrap the real 300 ms SeatEditor idle timer without changing its delay or behaviour.
                    page.add_init_script(
                        """
                        window.__rlIdleCommits = 0;
                        const origSetTimeout = window.setTimeout.bind(window);
                        window.setTimeout = function(fn, delay, ...args) {
                            if (delay === 300 && typeof fn === 'function') {
                                return origSetTimeout(function(...cbArgs) {
                                    if (document.querySelector('[data-testid="seat-input"].rl-engine-edit')) {
                                        window.__rlIdleCommits += 1;
                                    }
                                    return fn.apply(this, cbArgs);
                                }, delay, ...args);
                            }
                            return origSetTimeout(fn, delay, ...args);
                        };
                        """
                    )

                    page_errors: list[str] = []
                    server_errors: list[tuple[int, str]] = []
                    rpc_all: Counter[str] = Counter()
                    rpc_typing: Counter[str] = Counter()
                    doc_all: Counter[str] = Counter()
                    doc_typing: Counter[str] = Counter()
                    preview_requests = 0
                    preview_ok_responses = 0
                    preview_superseded_responses = 0
                    preview_failed_responses: list[tuple[int, str]] = []
                    preview_addresses: list[str] = []
                    proposed_ops_snapshots: list[list[dict]] = []
                    typing_phase = False

                    def on_request(req) -> None:
                        nonlocal preview_requests
                        sample_scratch()
                        if req.url.endswith("/rpc") and req.post_data:
                            try:
                                payload = json.loads(req.post_data)
                                method = payload.get("method") or "unknown"
                            except json.JSONDecodeError:
                                payload = {}
                                method = "invalid_json"
                            rpc_all[method] += 1
                            if typing_phase:
                                rpc_typing[method] += 1
                            if method == "plan/propose":
                                ops = (payload.get("params") or {}).get("ops")
                                if isinstance(ops, list):
                                    proposed_ops_snapshots.append(ops)
                        elif "/api/doc/" in req.url:
                            op = req.url.split("/api/doc/", 1)[1].split("?", 1)[0]
                            doc_all[op] += 1
                            if typing_phase:
                                doc_typing[op] += 1
                            if op == "preview":
                                preview_requests += 1
                                if req.post_data:
                                    try:
                                        body = json.loads(req.post_data)
                                    except json.JSONDecodeError:
                                        body = {}
                                    for item in body.get("ops") or []:
                                        if isinstance(item, dict) and isinstance(item.get("at"), str):
                                            preview_addresses.append(item["at"])

                    def on_response(resp) -> None:
                        nonlocal preview_ok_responses, preview_superseded_responses
                        sample_scratch()
                        if resp.status >= 500:
                            server_errors.append((resp.status, resp.url))
                        if "/api/doc/preview" in resp.url:
                            if resp.status == 200:
                                preview_ok_responses += 1
                            elif resp.status == 409:
                                preview_superseded_responses += 1
                            elif resp.status >= 400:
                                preview_failed_responses.append((resp.status, resp.url))

                    page.on("pageerror", lambda err: page_errors.append(str(err)))
                    page.on("request", on_request)
                    page.on("response", on_response)

                    page.goto(editor_v2_url(server.url))
                    page.get_by_test_id("start-sample-0").click()
                    paper = page.get_by_test_id("paper")
                    expect(paper).to_have_attribute("data-engine-geometry", "true", timeout=20_000)
                    expect(page.get_by_test_id("page-raster")).to_be_visible(timeout=20_000)

                    typing_phase = True
                    t_start = time.monotonic()
                    characters_typed = 0
                    explicit_commits = 0
                    previous_commit_key: str | None = None

                    for step in steps:
                        if previous_commit_key != "Tab":
                            page.locator(f'[data-cell-key="{step.cell_key}"]').click()
                        seat = page.locator('[data-testid="seat-input"].rl-engine-edit')
                        expect(seat).to_be_visible(timeout=10_000)
                        expect(page.locator(f'[data-cell-key="{step.cell_key}"].rl-cell--editing')).to_have_count(1)

                        # Select any existing form guide text so the first keystroke replaces it.
                        seat.evaluate("el => el.select()")
                        first_chunk = step.text[: step.pause_after]
                        second_chunk = step.text[step.pause_after :]
                        assert first_chunk and second_chunk, step

                        idle_before = page.evaluate("window.__rlIdleCommits")
                        seat.press_sequentially(first_chunk, delay=25)
                        characters_typed += len(first_chunk)

                        # Wait for the real 300 ms SeatEditor idle timer to fire onIdleCommit.
                        page.wait_for_function(
                            "prev => window.__rlIdleCommits > prev",
                            arg=idle_before,
                            timeout=5_000,
                        )
                        sample_scratch()

                        seat.press_sequentially(second_chunk, delay=25)
                        characters_typed += len(second_chunk)

                        seat.press(step.commit_key)
                        explicit_commits += 1
                        previous_commit_key = step.commit_key
                        sample_scratch()

                    expect(page.get_by_test_id("seat-input")).to_have_count(0, timeout=10_000)
                    expect(page.get_by_test_id(f"change-row-{len(steps)}")).to_be_visible(timeout=20_000)
                    expect(page.get_by_test_id("engine-edit-pending")).to_have_count(0, timeout=20_000)
                    expect(page.get_by_test_id("page-render-failed")).to_have_count(0)
                    wall_time_s = round(time.monotonic() - t_start, 3)
                    typing_phase = False

                    idle_commits = int(page.evaluate("window.__rlIdleCommits"))
                    scratch_remaining = sample_scratch()
                    gateway = _server_page_gateway(server)
                    with gateway._ready:
                        live_previews = len(gateway._previews)
                    with scratch_lock:
                        scratch_total_created = len(scratch_seen)
                        peak_scratch = scratch_peak

                    approval_calls = sum(
                        count for method, count in rpc_all.items() if method.startswith("approval/")
                    )
                    other_rpc_calls = {
                        method: count
                        for method, count in sorted(rpc_all.items())
                        if method not in {"plan/propose", "plan/validate"}
                        and not method.startswith("approval/")
                    }

                    record = {
                        "document": "gianmun-byeolji-1ho.hwpx",
                        "seats_edited": len(steps),
                        "characters_typed": characters_typed,
                        "idle_commits": idle_commits,
                        "explicit_commits": explicit_commits,
                        "total_commits": idle_commits + explicit_commits,
                        "wall_time_s": wall_time_s,
                        "preview": {
                            "requests": preview_requests,
                            "responses_ok": preview_ok_responses,
                            "responses_superseded": preview_superseded_responses,
                            "responses_failed": len(preview_failed_responses),
                            "scratch_files_total_created": scratch_total_created,
                            "scratch_files_peak": peak_scratch,
                            "scratch_files_remaining": scratch_remaining,
                            "gateway_live_previews": live_previews,
                            "gateway_preview_limit": rt_ui_doc.PREVIEW_LIMIT,
                            "scratch_ttl_s": rt_doc.SCRATCH_TTL_S,
                        },
                        "doc_requests_all": dict(sorted(doc_all.items())),
                        "doc_requests_typing": dict(sorted(doc_typing.items())),
                        "rpc": {
                            "plan_propose": rpc_all["plan/propose"],
                            "plan_validate": rpc_all["plan/validate"],
                            "approval_total": approval_calls,
                            "others": other_rpc_calls,
                            "all_by_method": dict(sorted(rpc_all.items())),
                            "typing_by_method": dict(sorted(rpc_typing.items())),
                        },
                    }

                    out_path = tmp_path / "v2-gongmun-typing-load.json"
                    out_path.write_text(
                        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    print(json.dumps(record, ensure_ascii=False, indent=2))

                    total_commits = idle_commits + explicit_commits
                    assert page_errors == [], page_errors
                    assert server_errors == [], server_errors
                    assert preview_failed_responses == [], preview_failed_responses
                    assert preview_ok_responses > 0
                    assert len(steps) == 14
                    assert "t0/r2/c0" in preview_addresses
                    assert proposed_ops_snapshots, "Expected plan/propose calls"
                    body_op = next(
                        (
                            op for op in proposed_ops_snapshots[-1]
                            if op.get("table") == 0 and op.get("row") == 2 and op.get("col") == 0
                        ),
                        None,
                    )
                    assert body_op is not None and body_op.get("kind") == "fill_cell" and "at" not in body_op, body_op
                    assert characters_typed == sum(len(s.text) for s in steps)
                    assert idle_commits >= len(steps)
                    assert 1 <= preview_requests <= total_commits + preview_superseded_responses
                    assert 1 <= scratch_total_created <= preview_requests
                    assert 1 < peak_scratch <= scratch_total_created
                    assert 0 <= scratch_remaining < peak_scratch
                    assert 1 <= live_previews <= 1
                    assert scratch_remaining <= live_previews <= len(steps)
                    assert scratch_remaining <= rt_ui_doc.PREVIEW_LIMIT
                    assert 1 <= rpc_all["plan/propose"] <= total_commits
                    assert 1 <= rpc_all["plan/validate"] <= explicit_commits + 2
            finally:
                browser.close()
    finally:
        stop_sampling.set()
        sampler.join(timeout=2)
        server.shutdown_bridge()
        thread.join(timeout=5)
