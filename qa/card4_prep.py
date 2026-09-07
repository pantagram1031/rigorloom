#!/usr/bin/env python3
"""Card 4 (Korean mixed-format E2E) — PREP tooling. Never a PASS.

Card 4 requires a real Windows install of the desktop, a human (or a scan-code
driven IME) at the keyboard, and a Korean document that mixes character
formats, carries long wrapped paragraphs and at least one table. The loop is:

    open -> edit (mixed run + long paragraph + table cell)
         -> undo -> redo
         -> AI suggestion review (Agent Host proposal in the same queue)
         -> save (export candidate)
         -> reopen (cold process, same hash)

Nothing in this file can perform that loop. What it can do, deterministically
and on any machine:

    probe     check that a candidate fixture .hwpx meets the card's structural
              requirements (tables, mixed-charPr paragraphs, a long paragraph),
              and record its sha256.
    scaffold  write the evidence manifest skeleton the operator fills in while
              running the GUI steps in qa/cards/card4-korean-e2e.md.
    validate  check an operator-filled manifest for completeness: every step
              carries a status, every referenced artifact exists, every recorded
              hash matches the file on disk, and the reopen hash equals the
              save hash. The result is `EVIDENCE_COMPLETE` or `EVIDENCE_INCOMPLETE`
              — never PASS. PASS is a human verdict on the evidence.

Exit codes: 0 requirement met / evidence complete · 3 not met · 2 could not run.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from qa.approval import (
    ApprovalRecord,
    create_approval_request,
    resolve_approval,
)

CARD_ID = "c4"

# Structural thresholds a card-4 fixture must meet. A "long paragraph" on an A4
# body is roughly 45 Korean characters per line; 200 characters forces at least
# four wrapped lines, which is what the run-scoped edit on a wrapped run needs.
REQUIREMENTS = {
    "min_tables": 1,
    "min_mixed_paragraphs": 1,  # paragraphs with >1 distinct charPrIDRef
    "min_long_paragraph_chars": 200,
    "min_hangul_chars": 200,
}

# Checked-in fixture that meets the requirements (see `probe`). It is also the
# document the desktop smoke already uses as its seated corpus, so the shell is
# known to open it.
DEFAULT_FIXTURE = "tests/corpus/forms/converted/kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx"

# The loop, as ordered steps. Each step names the evidence the operator must
# leave behind. `hash_of` entries are files whose sha256 gets recorded and
# re-verified by `validate`.
STEPS: list[dict[str, Any]] = [
    {"id": "s0_install", "title": "Launch the INSTALLED desktop build, not `tauri dev`",
     "artifacts": ["install-manifest.json", "shot-00-entrance.png"],
     "hash_of": ["exe"]},
    {"id": "s1_open", "title": "Open the fixture; tree counts match runtime counts",
     "artifacts": ["shot-01-open.png"], "hash_of": ["fixture"]},
    {"id": "s2_edit_mixed", "title": "Edit ONE run inside a multi-charPr paragraph via the IME (scan codes, not Unicode injection)",
     "artifacts": ["shot-02-edit-mixed.png", "queue-02.json"]},
    {"id": "s3_edit_long", "title": "Edit a run on a wrapped line of a >=200-char paragraph",
     "artifacts": ["shot-03-edit-long.png", "queue-03.json"]},
    {"id": "s4_edit_table", "title": "Edit a table cell (own_cell / fill seat)",
     "artifacts": ["shot-04-edit-table.png", "queue-04.json"]},
    {"id": "s5_undo", "title": "Undo the last queued op (tier one) and one applied candidate (tier two, 되돌리기 제안)",
     "artifacts": ["shot-05-undo.png", "queue-05.json"]},
    {"id": "s6_redo", "title": "Redo; queue equals queue-04 again",
     "artifacts": ["shot-06-redo.png", "queue-06.json"]},
    {"id": "s7_ai_review", "title": "Type an instruction; Agent Host proposal lands in the SAME queue; human approves/rejects",
     "artifacts": ["shot-07-ai-proposal.png", "shot-07-ai-decision.png", "agenthost-events.jsonl"]},
    {"id": "s8_save", "title": "Apply + export candidate; receipt binds source hash (unmoved) and candidate hash",
     "artifacts": ["shot-08-receipt.png", "receipt.json"], "hash_of": ["fixture", "saved"]},
    {"id": "s9_reopen", "title": "Quit the process; relaunch cold; open the saved file; hash equals save hash; edits visible",
     "artifacts": ["shot-09-reopen.png"], "hash_of": ["saved_reopened"]},
]

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# --- probe -------------------------------------------------------------------

def probe_fixture(hwpx: Path) -> dict[str, Any]:
    """Structural probe of an HWPX: tables, mixed-charPr paragraphs, longest paragraph."""
    if not hwpx.exists():
        return {"fixture": str(hwpx), "exists": False, "eligible": False,
                "reason": "fixture file not found"}
    try:
        z = zipfile.ZipFile(hwpx)
    except zipfile.BadZipFile as exc:
        return {"fixture": str(hwpx), "exists": True, "eligible": False,
                "reason": f"not a zip container: {exc}"}

    sections = sorted(n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n))
    paras = tables = mixed = hangul = 0
    charprs: set[str] = set()
    longest = 0
    longest_preview = ""
    for name in sections:
        xml = z.read(name).decode("utf-8", "replace")
        tables += len(re.findall(r"<hp:tbl\b", xml))
        for p in re.findall(r"<hp:p\b.*?</hp:p>", xml, re.S):
            paras += 1
            runs = re.findall(r'<hp:run\b[^>]*charPrIDRef="(\d+)"', p)
            charprs.update(runs)
            if len(set(runs)) > 1:
                mixed += 1
            text = re.sub(r"<[^>]+>", "", "".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", p, re.S)))
            hangul += len(HANGUL.findall(text))
            if len(text) > longest:
                longest = len(text)
                longest_preview = text[:40]

    stats = {
        "sections": len(sections),
        "paragraphs": paras,
        "tables": tables,
        "distinct_charpr": len(charprs),
        "mixed_paragraphs": mixed,
        "longest_paragraph_chars": longest,
        "longest_paragraph_preview": longest_preview,
        "hangul_chars": hangul,
    }
    failed = []
    if tables < REQUIREMENTS["min_tables"]:
        failed.append("tables")
    if mixed < REQUIREMENTS["min_mixed_paragraphs"]:
        failed.append("mixed_paragraphs")
    if longest < REQUIREMENTS["min_long_paragraph_chars"]:
        failed.append("long_paragraph")
    if hangul < REQUIREMENTS["min_hangul_chars"]:
        failed.append("hangul_chars")

    return {
        "timestamp": _now(),
        "fixture": str(hwpx),
        "exists": True,
        "bytes": hwpx.stat().st_size,
        "sha256": sha256_of(hwpx),
        "requirements": REQUIREMENTS,
        "stats": stats,
        "eligible": not failed,
        "failed_requirements": failed,
        "reason": "meets card 4 structural requirements" if not failed
        else "fixture lacks: " + ", ".join(failed),
    }


# --- scaffold ----------------------------------------------------------------

def create_mock_approval_artifact(
    evidence_dir: Path,
    plan_id: str = "plan-c4-mock-001",
    plan_hash: str = "hash-c4-mock-001",
    requested_by: str = "agenthost-mock",
) -> Path:
    """Create a c4-mock-approval.json artifact using qa.approval wire contract."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    req = create_approval_request(plan_id=plan_id, plan_hash=plan_hash, requested_by=requested_by)
    resolved = resolve_approval(
        req,
        plan_id=plan_id,
        plan_hash=plan_hash,
        decision="approved",
        approver="mock_approved",
        mode="mock_approved",
    )
    artifact_path = evidence_dir / "c4-mock-approval.json"
    with artifact_path.open("w", encoding="utf-8") as f:
        json.dump(resolved.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")
    return artifact_path


def scaffold_manifest(
    evidence_dir: Path,
    fixture: Path,
    sha: str | None,
    workspace: Path | None = None,
    approval_mode: str = "human_approved",
) -> Path:
    """Write the manifest skeleton an operator fills in during the GUI run."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fixture_ref = str(fixture)
    if workspace is not None:
        try:
            fixture_ref = fixture.resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            pass

    is_mock = approval_mode == "mock_approved"
    steps = []
    for s in STEPS:
        step_dict = {
            "id": s["id"],
            "title": s["title"],
            "status": "NOT_RUN",
            "artifacts": list(s["artifacts"]),
            "note": None,
        }
        if s["id"] == "s7_ai_review":
            if is_mock:
                step_dict["artifacts"] = ["shot-07-ai-proposal.png", "c4-mock-approval.json", "agenthost-events.jsonl"]
                step_dict["note"] = (
                    "mock_approved mode: approval/resolve wired for unattended plan apply gating; "
                    "real human approval still required for certified PASS."
                )
            else:
                step_dict["note"] = (
                    "human_approved mode: real human operator approval required; "
                    "unattended mock approval not enabled."
                )
        steps.append(step_dict)

    manifest = {
        "schema": "rigorloom-qa-card4-evidence/v1",
        "card_id": CARD_ID,
        "created": _now(),
        "product_sha": sha,
        "approval_mode": approval_mode,
        "is_mock_approved": is_mock,
        "status": "NOT_RUN",
        "gui_ime_claimed": False,
        "fixture": {"path": fixture_ref, "sha256": sha256_of(fixture) if fixture.exists() else None},
        "operator": {"name": None, "machine": None, "started": None, "finished": None},
        "install": {"exe_path": None, "installer_path": None, "sidecar_path": None},
        "hashes": {"exe": None, "fixture": None, "saved": None, "saved_reopened": None},
        "files": {"saved": None},
        "steps": steps,
        "instructions": (
            "Follow qa/cards/card4-korean-e2e.md. Set each step status to DONE|FAILED|SKIPPED. "
            "Put artifacts next to this file. Run `python qa/card4_prep.py validate` afterwards. "
            "Note: mock_approved mode is only for unattended plan apply gating in tests; "
            "never claims human approval or GUI/IME PASS."
        ),
    }
    path = evidence_dir / "c4-manifest.json"
    if path.exists():
        return path  # never clobber an operator's filled manifest
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return path


# --- validate ----------------------------------------------------------------

def validate_manifest(manifest_path: Path, workspace: Path) -> dict[str, Any]:
    """Completeness check of operator-filled evidence. Never returns PASS."""
    problems: list[str] = []
    if not manifest_path.exists():
        return {"result": "EVIDENCE_INCOMPLETE", "problems": ["manifest missing"], "gui_ime_claimed": False}
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    ev = manifest_path.parent

    if m.get("schema") != "rigorloom-qa-card4-evidence/v1":
        problems.append("unknown manifest schema")
    if m.get("gui_ime_claimed") is not False:
        problems.append("gui_ime_claimed must be false; the harness never claims GUI success")
    if not m.get("product_sha"):
        problems.append("product_sha empty")
    if not (m.get("install") or {}).get("exe_path"):
        problems.append("install.exe_path empty (card 4 needs the installed build, not tauri dev)")

    expected_ids = [s["id"] for s in STEPS]
    seen = {s.get("id"): s for s in m.get("steps", [])}
    approval_mode = m.get("approval_mode", "human_approved")
    is_mock = approval_mode == "mock_approved"

    for sid in expected_ids:
        step = seen.get(sid)
        if step is None:
            problems.append(f"step {sid} missing")
            continue
        if step.get("status") != "DONE":
            problems.append(f"step {sid} status is {step.get('status')!r}, not DONE")
        for art in step.get("artifacts", []):
            art_path = ev / art
            if not art_path.exists():
                if sid == "s7_ai_review" and not is_mock:
                    problems.append(
                        f"step {sid}: artifact {art} not found in evidence dir "
                        "(real human operator approval required; mock_approved mode is off)"
                    )
                else:
                    problems.append(f"step {sid}: artifact {art} not found in evidence dir")
            elif sid == "s7_ai_review" and art == "c4-mock-approval.json":
                # Validate mock approval artifact content
                try:
                    mock_data = json.loads(art_path.read_text(encoding="utf-8"))
                    if not mock_data.get("is_mock_approved"):
                        problems.append("step s7_ai_review: c4-mock-approval.json is_mock_approved is not true")
                    if mock_data.get("is_human_approved"):
                        problems.append("step s7_ai_review: mock_approved artifact cannot claim is_human_approved: true")
                    if mock_data.get("gui_claimed"):
                        problems.append("step s7_ai_review: mock_approved artifact cannot claim gui_claimed: true")
                    if mock_data.get("approver") not in ("mock_approved", "qa-harness-mock", "agenthost-mock"):
                        problems.append(f"step s7_ai_review: invalid approver {mock_data.get('approver')!r} for mock_approved")
                except Exception as exc:
                    problems.append(f"step s7_ai_review: failed to parse c4-mock-approval.json: {exc}")

    hashes = m.get("hashes") or {}
    for key in ("exe", "fixture", "saved", "saved_reopened"):
        if not hashes.get(key):
            problems.append(f"hashes.{key} empty")

    # Re-hash the files we can reach and compare with what the operator wrote.
    def _check(label: str, rel: str | None) -> None:
        if not rel:
            return
        p = Path(rel)
        if not p.is_absolute():
            p = workspace / rel
        if not p.exists():
            problems.append(f"{label}: file {rel} not found")
            return
        actual = sha256_of(p)
        if hashes.get(label) and actual != hashes[label]:
            problems.append(f"{label}: recorded sha256 {hashes[label][:12]} != on-disk {actual[:12]}")

    _check("fixture", (m.get("fixture") or {}).get("path"))
    _check("saved", (m.get("files") or {}).get("saved"))
    _check("exe", (m.get("install") or {}).get("exe_path"))

    if hashes.get("saved") and hashes.get("saved_reopened") and hashes["saved"] != hashes["saved_reopened"]:
        problems.append("reopen hash differs from save hash")
    if hashes.get("fixture") and (m.get("fixture") or {}).get("sha256") and hashes["fixture"] != m["fixture"]["sha256"]:
        problems.append("fixture hash moved between scaffold and run (source must stay unmoved)")

    note = (
        "EVIDENCE_COMPLETE is not PASS. A human reads the screenshots and receipt and records the verdict. "
        + (
            "mock_approved mode active: approval/resolve wired for plan apply gating; "
            "real human approval and Windows GUI/IME still required for certified PASS."
            if is_mock
            else "human_approved mode active: real human approval required."
        )
    )

    return {
        "timestamp": _now(),
        "manifest": str(manifest_path),
        "result": "EVIDENCE_COMPLETE" if not problems else "EVIDENCE_INCOMPLETE",
        "problems": problems,
        "approval_mode": approval_mode,
        "is_mock_approved": is_mock,
        "gui_ime_claimed": False,
        "note": note,
    }


# --- CLI ---------------------------------------------------------------------

def _dump(obj: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="check a fixture against card 4 requirements")
    p.add_argument("--hwpx", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)

    s = sub.add_parser("scaffold", help="write the evidence manifest skeleton")
    s.add_argument("--evidence-dir", type=Path, required=True)
    s.add_argument("--hwpx", type=Path, default=None)
    s.add_argument("--sha", default=None, help="product tip SHA the operator will install")
    s.add_argument(
        "--approval-mode",
        default="human_approved",
        choices=["human_approved", "mock_approved"],
        help="approval resolution mode (default: human_approved; mock_approved for unattended QA gating)",
    )

    ma = sub.add_parser("mock-approve", help="generate c4-mock-approval.json artifact")
    ma.add_argument("--evidence-dir", type=Path, required=True)
    ma.add_argument("--plan-id", default="plan-c4-mock-001")
    ma.add_argument("--plan-hash", default="hash-c4-mock-001")
    ma.add_argument("--requested-by", default="agenthost-mock")

    v = sub.add_parser("validate", help="check an operator-filled manifest for completeness")
    v.add_argument("--manifest", type=Path, required=True)
    v.add_argument("--out", type=Path, default=None)

    a = ap.parse_args(argv)
    ws = a.workspace.resolve()

    try:
        if a.cmd == "probe":
            hwpx = (a.hwpx or Path(DEFAULT_FIXTURE))
            if not hwpx.is_absolute():
                hwpx = ws / hwpx
            r = probe_fixture(hwpx)
            _dump(r, a.out)
            return 0 if r["eligible"] else 3
        if a.cmd == "scaffold":
            hwpx = (a.hwpx or Path(DEFAULT_FIXTURE))
            if not hwpx.is_absolute():
                hwpx = ws / hwpx
            path = scaffold_manifest(a.evidence_dir.resolve(), hwpx, a.sha, ws, approval_mode=a.approval_mode)
            print(str(path))
            return 0
        if a.cmd == "mock-approve":
            path = create_mock_approval_artifact(
                a.evidence_dir.resolve(),
                plan_id=a.plan_id,
                plan_hash=a.plan_hash,
                requested_by=a.requested_by,
            )
            print(str(path))
            return 0
        if a.cmd == "validate":
            r = validate_manifest(a.manifest.resolve(), ws)
            _dump(r, a.out)
            return 0 if r["result"] == "EVIDENCE_COMPLETE" else 3
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"card4_prep: {exc}\n")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
