#!/usr/bin/env python3
"""fill_report.py — 조립된 보고서가 양식을 '빈공간 없이' 채웠는지 측정·판정.

CONTRACT_v0.4 §5(form-fill loop)의 헤드리스 오케스트레이터. 본문 텍스트를
지어내지 않는다 — layout_qa로 PDF를 측정하고, build.yaml의 fill 목표와 대조해
결정론적 verdict(JSON)를 방출한다. 무엇을 바꿔야 하는지는 순서화된 "needs"
리스트로 writer/assembler에게 지시할 뿐, 코드가 분량을 채우지 않는다.

세 모드:

  (A) 측정만(오프라인, COM 불필요):
      python fill_report.py --measure --pdf verify.pdf --build-yaml build.yaml
                            [--fig-count N] [--out verdict.json]

  (B) 조립 1회 반복(COM 필요, 한글 실행):
      python fill_report.py --assemble --form FORM.hwpx --content content.md
                            --out-dir DIR [--build-yaml build.yaml]
                            [--kill-stale] [--max-iters N] [--out verdict.json]
      build_report → com_backend edit(save-as/export-pdf) → 모드(A) 측정.
      1회 반복이다. 루프(needs→writer 재작성→재조립, 최대 4회)는 호출자 몫.
      --max-iters는 '같은 content.md'를 재조립해 verdict 동일성(멱등성)만 검증.

  (C) FILL 루프 오케스트레이션(COM 필요, 한글 실행):
      python fill_report.py --loop --form FORM.hwpx --content content.md
                            --out-dir DIR [--build-yaml build.yaml]
                            [--max-loops 4] [--baseline form_baseline.json]
                            [--trouble-table TROUBLE.md] [--kill-stale]
                            [--fig-count N] [--out verdict.json]
      매 반복: pristine FORM에서 assemble → layout_qa(신규 체크 포함) →
      (--baseline 있으면) style_diff 병합 → DIR/preview/iter_N.pdf 저장 →
      DIR/fill_events.jsonl에 1줄 append. CONTRACT §5: pass+페이지창 내+
      그림수 충족 → converged. 아니면 STOP하고 needs(순서화된 지시)를
      verdict로 방출 — 본문 재작성은 호출자(writer agent) 몫이며 이 루프는
      내용을 스스로 채우지 않는다. --trouble-table로 kb 시그니처가 매치되면
      동일 content로 1회 재시도 후 verdict에 known_trouble 주석(실제 수정
      오퍼레이션은 미래 작업).

T7(COM 기반 blank-paragraph 정리가 제목 charPr 오염·문단 병합을 일으킴) 이후:
build.yaml에 tidy_blank_before/tidy_blank_after 블록-리스트가 있으면, 매 반복
COM edit는 save-as hwpx까지만 하고(--export-pdf 생략) tidy_hwpx.py(오프라인
XML 편집)로 앵커 앞/뒤 빈 문단을 정리한 뒤, 그 결과 hwpx를 COM convert로
PDF 변환한다(edit → tidy_hwpx → convert 순서). 두 키가 모두 없으면 기존
한 방(edit+export-pdf 동시) 경로 그대로.

자동 앵커 유도: build.yaml에 tidy_blank_before/after가 둘 다 없고
--form-profile FORM_PROFILE.json이 주어지면, form_inspect.py가 뽑은
anchors 목록을 tidy_blank_before로 유도해 쓴다(explicit build.yaml 키가
항상 우선). verdict에 derived_tidy_anchors로 기록되고, 유도 앵커는
모호/미매치를 fatal 대신 per-anchor skip+warning으로 처리한다
(tidy_warnings).

  (D) PROOF 단계(--loop v2, COM 필요):
      python fill_report.py --loop --form FORM.hwpx --content content.md
                            --out-dir DIR --proof [--max-proof-iters 3]
                            [--form-profile form_profile.json]
                            [--proof-needs needs.json] [--build-yaml build.yaml]
      phase-1(위 FILL 루프)이 converged로 끝나면, --proof가 설정된 경우 최종
      verify PDF(out_pdf)에 contact_sheet.py를 서브프로세스로 돌려 컨택트시트
      PNG를 만든다. verdict에 phase:"proof", contact_sheets:[경로들],
      proof_iter:N, 그리고 rubric(4개의 null 이진 체크 —
      mid_bottom_void/density_uniformity/table_proportion/heading_plus_void)이
      추가된다. rubric 값 채우기는 호출자(vision judge)의 몫 — 이 스크립트는
      절대 채우지 않는다.

      재진입: 호출자가 --proof-needs needs.json을 주면(형식:
      [{"type":"rewrite_para","anchor":"...","delta_lines":-2,"reason":"..."},
       {"type":"resize_table","index":1,"cols":"10,16,12,9,10,43"}]) 스키마를
      검증하고(불량 → exit 1), DIR/fill_events.jsonl에 proof_iter와 함께
      기록한다 — fill_report는 content.md를 절대 재작성하지 않는다(본문 작성은
      writer/caller 몫). proof_iter는 fill_events.jsonl을 스캔해 영속화되며,
      max-proof-iters를 넘으면 status:"escalate_human"과 reason을 verdict에
      담는다 — 이때 converged는 False로 내려가고(자기모순 쌍 금지, rigorloom
      verdict_schema와 호환) phase-1 수렴 사실은 phase1_converged:true로
      보존된다. 모든 proof 이벤트는 {ts, iter, phase:"proof", proof_iter,
      result|needs} 형태로 append된다.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_PIPELINE_SCRIPTS = HERE.parents[1] / "pipeline" / "scripts"
if _PIPELINE_SCRIPTS.is_dir():
    sys.path.insert(0, str(_PIPELINE_SCRIPTS))
from cli_io import utf8_stdio  # noqa: E402
import layout_qa  # noqa: E402
import build_report  # noqa: E402
import tidy_hwpx  # noqa: E402
import document_evidence  # noqa: E402
import render_quality  # noqa: E402

# fill 기본값: build.yaml에 fill 블록이 없을 때만 사용(임계는 인자/파일로만).
FILL_DEFAULTS = {
    "min_figures": 0,
    "target_pages": [1, 999],
    "bottom_white_max": 25,
    "max_gap_lines": 3,
}


def load_guide_strings(guide_file):
    """--guide-file JSON(문자열 리스트)을 로드. 생략 시 None(기존 동작 그대로)."""
    if not guide_file:
        return None
    return json.loads(Path(guide_file).read_text(encoding="utf-8"))


def die(msg, code=2):
    sys.stdout.buffer.write(
        json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode("utf-8"))
    sys.exit(code)


def _emit(obj, out=None):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    sys.stdout.buffer.write(text.encode("utf-8"))


def read_fill(build_yaml):
    """build.yaml의 fill 블록을 읽어 목표를 반환(누락 키는 기본값)."""
    fill = dict(FILL_DEFAULTS)
    if build_yaml and Path(build_yaml).exists():
        cfg = build_report.parse_build_yaml(build_yaml)
        for k, v in (cfg.get("fill") or {}).items():
            fill[k] = v
    tp = fill.get("target_pages") or FILL_DEFAULTS["target_pages"]
    if not (isinstance(tp, list) and len(tp) == 2):
        die(f"build.yaml fill.target_pages는 [lo,hi]여야 함: {tp!r}")
    fill["target_pages"] = [int(tp[0]), int(tp[1])]
    fill["min_figures"] = int(fill["min_figures"])
    fill["bottom_white_max"] = float(fill["bottom_white_max"])
    fill["max_gap_lines"] = float(fill["max_gap_lines"])
    return fill


def count_figures(pdf_path):
    """PDF 전 페이지의 이미지 블록(layout_qa._blocks kind=='image') 합계."""
    import fitz
    doc = fitz.open(pdf_path)
    total = 0
    for page in doc:
        total += sum(1 for b in layout_qa._blocks(page) if b[4] == "image")
    doc.close()
    return total


def build_verdict(pdf_path, fill, fig_count_override=None, guide_strings=None,
                   spacing_skip_pages=None, gap_skip_pages=None,
                   bottom_skip_pages=None, qa_result=None):
    """PDF + fill 목표 → 결정론 verdict. 본문 생성 없음, 측정·지시만."""
    bwm = fill["bottom_white_max"]
    mgl = fill["max_gap_lines"]
    lo, hi = fill["target_pages"]
    min_fig = fill["min_figures"]

    qa = qa_result or layout_qa.analyze(
        pdf_path, bottom_thr=bwm, gap_thr=mgl,
        guide_strings=guide_strings,
        spacing_skip_pages=spacing_skip_pages,
        gap_skip_pages=gap_skip_pages,
        bottom_skip_pages=bottom_skip_pages)
    page_count = qa["page_count"]
    pages = qa["pages"]

    fig_count = (int(fig_count_override) if fig_count_override is not None
                 else count_figures(pdf_path))

    # 최악 하단 공백: 마지막 쪽 제외(마지막 쪽은 임계 면제).
    # bottom_skip_pages(§P: 양식 구조 공백 페이지)도 layout_qa flags와 동일하게
    # 제외 — 아니면 qa.pass는 통과인데 needs(expand)만 잡는 phantom이 생긴다.
    worst_bw = {"page": None, "pct": 0.0}
    for p in pages:
        if p["page"] == page_count:
            continue
        if bottom_skip_pages and p["page"] in bottom_skip_pages:
            continue
        pct = p.get("bottom_white_pct") or 0.0
        if pct > worst_bw["pct"]:
            worst_bw = {"page": p["page"], "pct": round(pct, 1)}

    # 최악 문단 간격. gap_skip_pages로 면제된 페이지는 layout_qa.analyze의 flags
    # 계산과 동일하게 여기서도 제외한다 — 안 그러면 qa["pass"]는 통과인데
    # worst_gap/gaps_ok/needs(remove_gap)만 그 페이지를 잡아 phantom need가 생긴다.
    worst_gap = {"page": None, "lines": 0.0}
    gappy_pages = []
    for p in pages:
        if gap_skip_pages and p["page"] in gap_skip_pages:
            continue
        g = p.get("max_gap_lines") or 0.0
        if g > mgl:
            gappy_pages.append(p["page"])
        if g > worst_gap["lines"]:
            worst_gap = {"page": p["page"], "lines": g}

    in_window = lo <= page_count <= hi
    figs_ok = fig_count >= min_fig
    bottom_ok = worst_bw["pct"] <= bwm
    gaps_ok = worst_gap["lines"] <= mgl
    converged = bool(qa["pass"] and in_window and figs_ok)

    # 상태: 우선순위 converged > overfilled > underfilled > gappy.
    if converged:
        state = "converged"
    elif page_count > hi:
        state = "overfilled"
    elif (page_count < lo) or (not figs_ok) or (not bottom_ok):
        state = "underfilled"
    elif not gaps_ok:
        state = "gappy"
    else:
        # pass는 아니지만 위 분기에 안 걸림(예: flagged지만 임계 내) → gappy 취급.
        state = "gappy"

    # needs: 결정론적·순서화된 지시. figures → expand/tighten → gaps.
    needs = []
    if fig_count < min_fig:
        n = min_fig - fig_count
        needs.append({
            "kind": "add_figures", "count": n,
            "directive": f"add {n} figures (have {fig_count}, need {min_fig})",
        })
    if page_count < lo or not bottom_ok:
        cite = worst_bw["page"]
        why = (f"page_count {page_count} < {lo}" if page_count < lo
               else f"bottom_white {worst_bw['pct']}% > {bwm}% on page {cite}")
        needs.append({
            "kind": "expand", "page": cite,
            "directive": ("expand: deepen section / add worked example / "
                          f"add figure or table ({why})"),
        })
    if page_count > hi:
        needs.append({
            "kind": "tighten", "page": None,
            "directive": (f"tighten: merge/trim, move detail into figure/table "
                          f"(page_count {page_count} > {hi})"),
        })
    if worst_gap["lines"] > mgl:
        needs.append({
            "kind": "remove_gap", "page": worst_gap["page"],
            "directive": (f"remove empty paragraphs near page {worst_gap['page']} "
                          f"(gap {worst_gap['lines']} lines > {mgl})"),
        })

    return {
        "ok": True,
        "converged": converged,
        "page_count": page_count,
        "target_pages": [lo, hi],
        "fig_count": fig_count,
        "min_figures": min_fig,
        "bottom_white_worst": worst_bw,
        "gaps_worst": worst_gap,
        "gappy_pages": gappy_pages,
        "flagged_pages": list(qa.get("flagged_pages", [])),
        "state": state,
        "needs": needs,
        "thresholds": {"bottom_white_max": bwm, "max_gap_lines": mgl},
        "pdf": str(pdf_path),
    }


def load_calibration(path):
    """Load advisory-renderer threshold relaxations from JSON."""
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"invalid --calibration JSON: {exc}")
    if not isinstance(payload, dict):
        die("--calibration must contain a JSON object")
    allowed = {
        "bottom_white_tolerance_pt", "bottom_white_tolerance_pct",
        "max_gap_scale", "max_gap_tolerance_lines",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        die(f"unsupported --calibration keys: {unknown}")
    result = {}
    for key, value in payload.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            die(f"--calibration {key} must be numeric")
        minimum = 1.0 if key == "max_gap_scale" else 0.0
        if number < minimum:
            die(f"--calibration {key} must be >= {minimum:g} (relaxations only)")
        result[key] = number
    return result


def _advisory_fill(fill, pdf_path, proof_grade, calibration):
    """Return effective FILL thresholds and the applied calibration record."""
    effective = dict(fill)
    if proof_grade != "advisory" or not calibration:
        return effective, None

    applied = dict(calibration)
    tolerance_pct = calibration.get("bottom_white_tolerance_pct", 0.0)
    tolerance_pt = calibration.get("bottom_white_tolerance_pt", 0.0)
    if tolerance_pt:
        import fitz
        doc = fitz.open(pdf_path)
        heights = [page.rect.height for page in doc if page.rect.height > 0]
        doc.close()
        if not heights:
            raise ValueError("renderer produced a PDF without measurable pages")
        # One global layout_qa threshold must cover every page.  The smallest
        # page converts the point allowance to the largest percentage allowance.
        converted = tolerance_pt / min(heights) * 100.0
        tolerance_pct += converted
        applied["bottom_white_tolerance_pct_applied"] = round(tolerance_pct, 4)
    effective["bottom_white_max"] += tolerance_pct
    effective["max_gap_lines"] *= calibration.get("max_gap_scale", 1.0)
    effective["max_gap_lines"] += calibration.get("max_gap_tolerance_lines", 0.0)
    applied["effective_thresholds"] = {
        "bottom_white_max": effective["bottom_white_max"],
        "max_gap_lines": effective["max_gap_lines"],
    }
    return effective, applied


def measure_rendered_pdf(pdf_path, fill, proof_grade, fig_count_override=None,
                         guide_strings=None, spacing_skip_pages=None,
                         gap_skip_pages=None, bottom_skip_pages=None,
                         calibration=None):
    """Run layout_qa once and build the shared COM/XML measured verdict."""
    effective_fill, applied = _advisory_fill(
        fill, pdf_path, proof_grade, calibration)
    qa = layout_qa.analyze(
        pdf_path, bottom_thr=effective_fill["bottom_white_max"],
        gap_thr=effective_fill["max_gap_lines"],
        guide_strings=guide_strings,
        spacing_skip_pages=spacing_skip_pages,
        gap_skip_pages=gap_skip_pages,
        bottom_skip_pages=bottom_skip_pages)
    verdict = build_verdict(
        pdf_path, effective_fill, fig_count_override, guide_strings,
        spacing_skip_pages=spacing_skip_pages,
        gap_skip_pages=gap_skip_pages,
        bottom_skip_pages=bottom_skip_pages,
        qa_result=qa)
    verdict["checks"] = qa.get("checks", {})
    verdict["proof_grade"] = proof_grade
    if applied:
        verdict["calibration"] = applied
    return verdict


def run_build_report(content, form, build_yaml, ops_out, form_profile=None):
    """build_report.py를 서브프로세스로 실행해 ops JSON 파일을 생성."""
    cmd = [sys.executable, str(HERE / "build_report.py"),
           "--content", str(content), "--dry-run"]
    if build_yaml:
        cmd += ["--build-yaml", str(build_yaml)]
    if form_profile:
        # 라벨 셀 앵커(요약문 등) 자동 감지 → goto_text cell_below 배선.
        cmd += ["--form-profile", str(form_profile)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        die(f"build_report 출력 파싱 실패: {raw[:300]}")
    if not payload.get("ok"):
        die(f"build_report 실패: {payload.get('error')}")
    Path(ops_out).write_text(
        json.dumps(payload["ops"], ensure_ascii=False), encoding="utf-8")
    return payload


def run_com_edit(form, ops_path, out_hwpx, out_pdf, kill_stale):
    """com_backend.py edit를 서브프로세스로 실행(양식은 비파괴, save-as로 복사).

    out_pdf가 None이면 --export-pdf를 생략한다(tidy_hwpx 경로: hwpx 저장까지만
    하고 PDF 변환은 tidy 이후 run_com_convert가 별도로 담당)."""
    cmd = [sys.executable, str(HERE / "com_backend.py"), "edit",
           "--file", str(form), "--ops", str(ops_path),
           "--save-as", str(out_hwpx)]
    if out_pdf:
        cmd += ["--export-pdf", str(out_pdf)]
    if kill_stale:
        cmd.append("--kill-stale")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        die(f"com_backend edit 출력 파싱 실패: {raw[:300]}\nstderr: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    if not payload.get("ok"):
        die(f"com_backend edit 실패: {payload.get('error')}")
    return payload


def run_com_convert(src_hwpx, dst_pdf):
    """com_backend.py convert를 서브프로세스로 실행해 hwpx -> pdf 변환."""
    cmd = [sys.executable, str(HERE / "com_backend.py"), "convert",
           "--file", str(src_hwpx), "--to", str(dst_pdf)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        die(f"com_backend convert 출력 파싱 실패: {raw[:300]}\nstderr: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    if not payload.get("ok"):
        die(f"com_backend convert 실패: {payload.get('error')}")
    return payload


def run_xml_edit(form, ops_path, out_hwpx):
    """Run the stdlib-only HWPX editor without importing the COM backend."""
    cmd = [sys.executable, str(HERE / "xml_backend.py"), "edit",
           "--file", str(form), "--ops", str(ops_path),
           "--save-as", str(out_hwpx), "--json"]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        die(f"xml_backend edit output parse failed: {raw[:300]}\nstderr: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    if proc.returncode != 0 or not payload.get("ok"):
        die("xml_backend edit failed: "
            f"unsupported={payload.get('unsupported', [])} "
            f"anchors_missing={payload.get('anchors_missing', [])}")
    return payload


def run_pdf_command(argv_template, src_hwpx, dst_pdf, timeout=120.0):
    """Render HWPX with a shell-free argv template.

    Placeholders: {in}/{input}, {out}/{output}, {out_dir}/{outdir}, and {stem}.
    A string
    is split with shlex; callers may also pass an already-tokenized list/tuple.
    Runtime failures are returned to the caller so loop mode can emit an honest
    ``renderer_failed`` verdict instead of exiting with a generic CLI error.
    """
    if isinstance(argv_template, str):
        argv = shlex.split(argv_template, posix=True)
    elif isinstance(argv_template, (list, tuple)):
        argv = list(argv_template)
    else:
        die("--pdf-cmd must be an argv template string or list")
    if not argv:
        die("--pdf-cmd must not be empty")
    src_hwpx = Path(src_hwpx)
    dst_pdf = Path(dst_pdf)
    values = {"in": str(src_hwpx), "out": str(dst_pdf),
              "input": str(src_hwpx), "output": str(dst_pdf),
              "out_dir": str(dst_pdf.parent), "outdir": str(dst_pdf.parent),
              "stem": src_hwpx.stem}
    try:
        argv = [token.format(**values) for token in argv]
    except (KeyError, ValueError) as exc:
        die(f"invalid --pdf-cmd placeholder: {exc}")
    if dst_pdf.exists():
        dst_pdf.unlink()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            argv, capture_output=True, env=env, timeout=float(timeout), shell=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False, "state": "renderer_failed", "argv": argv,
            "pdf": str(dst_pdf), "error": f"renderer timed out after {exc.timeout}s",
        }
    except OSError as exc:
        return {
            "ok": False, "state": "renderer_failed", "argv": argv,
            "pdf": str(dst_pdf), "error": f"renderer could not start: {exc}",
        }
    if proc.returncode != 0 or not dst_pdf.is_file():
        return {
            "ok": False, "state": "renderer_failed", "argv": argv,
            "pdf": str(dst_pdf), "returncode": proc.returncode,
            "error": (f"renderer failed (exit {proc.returncode}, output={dst_pdf}): "
                      f"{proc.stderr.decode('utf-8', 'replace')[:300]}"),
        }
    return {"ok": True, "argv": argv, "pdf": str(dst_pdf)}


def read_tidy_anchors(build_yaml, form_profile=None, content_path=None):
    """build.yaml의 tidy_blank_before/tidy_blank_after 블록-리스트를 읽는다.

    T7 이후: build_report.py는 이 두 키를 더 이상 COM op으로 만들지 않는다 —
    fill_report.py가 여기서 직접 읽어 tidy_hwpx.py(오프라인)에 넘긴다. 둘 다
    없으면 (None, None) — 호출자는 이걸 '기존 경로 유지' 신호로 쓴다.

    자동 앵커 유도(§2): build.yaml에 두 키가 모두 없고 form_profile(경로)이
    주어지면, form_profile.json의 anchors 목록(form_inspect.py가 Stage-0에서
    뽑은 동일 문자열)을 tidy_blank_before로 사용한다. 명시적 build.yaml 키는
    항상 우선한다(P7-style precedence) — 하나라도 명시돼 있으면 유도하지 않고
    그대로 반환. 반환된 (before, after)가 유도된 것인지는 이 함수의 반환값
    만으로는 알 수 없으므로, 호출자가 필요하면 read_tidy_anchors_with_source를
    쓴다."""
    before, after, _derived, _keep_map = read_tidy_anchors_with_source(
        build_yaml, form_profile, content_path)
    return before, after


def _anchor_is_filled_section(anchor, section_anchors):
    """anchor(form_profile의 form-native anchor 문자열)가 content.md의 어느
    SECTION과 매치되는지(= 그 섹션이 채워질 예정인지) 판정.

    tidy_hwpx._is_heading와 동일 관례(§ apply_typeset_defaults가 제목 문단을
    판정하는 방식 그대로 재사용) — whitespace 정규화 후 SECTION 텍스트가
    anchor 문자열과 정확히 같거나 그 문자열로 시작하면 매치."""
    a_stripped = (anchor or "").strip()
    if not a_stripped:
        return False
    for sec_anchor in section_anchors:
        norm = tidy_hwpx._normalize_ws(sec_anchor or "")
        if norm and (norm == a_stripped or norm.startswith(a_stripped)):
            return True
    return False


def _derive_keep_map(anchors, blanks_before, section_anchors):
    """Rule 1 refinement: form_profile의 blanks_before 그대로 쓰지 않고,
    각 anchor 바로 앞의 '가장 가까운 이전 form anchor'가 채워질 SECTION인지로
    분기한다.

    form의 blank 문단 무리는 그 앞 섹션(anchor)의 '집필 여백'이다 — 이전
    섹션이 채워지면(content.md에 해당 SECTION이 있으면) 그 여백은 소비된
    것이므로 keep_n=1로 접어야 한다. 이전 섹션이 안 채워졌으면(제목 페이지
    필드처럼 SECTION이 아예 없는 구조적 앵커) 여백은 여전히 '쓰지 않은
    공간'이므로 form-native 값(blanks_before, 없으면 1)을 그대로 보존한다.

    anchors: form_profile.json의 anchors 리스트(문서 순서, form_inspect.py가
    문단을 순회하며 append하므로 이미 정렬돼 있음).
    section_anchors: content.md SECTION 텍스트 리스트(문서 순서 무관, 매치만
    본다) — None/빈 리스트면 이전 동작과 동일(전부 baseline)."""
    if not section_anchors:
        return {a: blanks_before.get(a, 1) for a in anchors}
    keep_map = {}
    filled_prev = False  # 가장 가까운 '이전' form anchor가 채워질 섹션인지.
    for a in anchors:
        keep_map[a] = 1 if filled_prev else blanks_before.get(a, 1)
        filled_prev = _anchor_is_filled_section(a, section_anchors)
    return keep_map


def read_tidy_anchors_with_source(build_yaml, form_profile=None, content_path=None):
    """read_tidy_anchors와 동일하지만 (before, after, derived_anchors, keep_map)을
    반환. derived_anchors는 form_profile에서 유도했을 때만 그 리스트(아니면
    None) — verdict의 derived_tidy_anchors 필드용.

    keep_map(Rule 1, refined): 유도된 anchor들에 한해 {anchor: keep_n}을 채운다.
    기본은 form_profile의 anchors_blanks_before(form_inspect.py가 뽑은
    pristine-form 빈 문단 개수, 없으면 1) — 단 content_path(content.md)가
    주어지면, anchor 바로 앞의 '가장 가까운 이전 form anchor'가 content.md의
    채워질 SECTION과 매치될 때 그 blanks는 이미 소비된 여백이므로 keep_n=1로
    접는다(_derive_keep_map 참고). content_path가 없으면(하위호환) 기존처럼
    baseline 그대로. explicit build.yaml 앵커 경로는 keep_map=None(호출자가
    기존처럼 단일 keep=1을 씀)."""
    explicit_before = explicit_after = None
    if build_yaml and Path(build_yaml).exists():
        cfg = build_report.parse_build_yaml(build_yaml)
        explicit_before = cfg.get("tidy_blank_before") or None
        explicit_after = cfg.get("tidy_blank_after") or None
    if explicit_before or explicit_after:
        return explicit_before, explicit_after, None, None
    if form_profile and Path(form_profile).exists():
        try:
            profile = json.loads(Path(form_profile).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None, None, None, None
        anchors = profile.get("anchors") or []
        if anchors:
            blanks_before = profile.get("anchors_blanks_before") or {}
            section_anchors = None
            if content_path and Path(content_path).exists():
                try:
                    text = Path(content_path).read_text(encoding="utf-8")
                    _meta, sections = build_report.parse_content(text)
                    section_anchors = [s["anchor"] for s in sections]
                except (OSError, UnicodeDecodeError):
                    section_anchors = None
            keep_map = _derive_keep_map(list(anchors), blanks_before, section_anchors)
            return list(anchors), None, list(anchors), keep_map
    return None, None, None, None


def read_keep_with_next(build_yaml):
    """build.yaml의 keep_with_next 블록-리스트(표 캡션 프리픽스 등)를 읽는다.
    없으면 None — 호출자는 이걸 '적용 안 함' 신호로 쓴다."""
    if not build_yaml or not Path(build_yaml).exists():
        return None
    cfg = build_report.parse_build_yaml(build_yaml)
    return cfg.get("keep_with_next") or None


def _call_tidy_hwpx_quiet(hwpx_path, before_anchors, after_anchors, keep_map=None):
    """tidy_hwpx.tidy_hwpx를 stdout 잠근 채 1회 호출. 성공 시 result dict,
    실패 시 SystemExit을 그대로 전파(호출자가 처리).

    keep_map(Rule 1, 선택): {anchor: keep_n} — 주어지면 anchor별로 그 개수만큼
    빈 문단을 보존한다(form_inspect.anchors_blanks_before 유래). 없는 anchor
    또는 keep_map 자체가 None이면 기존처럼 keep=1(하위호환)."""
    class _NullBuffer:
        def write(self, _data):
            pass

    class _NullStdout:
        buffer = _NullBuffer()

    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        return tidy_hwpx.tidy_hwpx(hwpx_path, before_anchors or [], after_anchors or [],
                                    keep=1, out_path=hwpx_path, keep_map=keep_map)
    finally:
        sys.stdout = saved_stdout


def run_tidy_hwpx(hwpx_path, before_anchors, after_anchors, soft=False, keep_map=None):
    """tidy_hwpx.py를 프로세스 내에서 직접 호출(순수 stdlib, COM 불필요).

    soft=False(기본, 명시적 build.yaml 앵커): 실패(앵커 없음/모호) 시 die()로
    중단 — 조용히 넘어가지 않는다(결정론 유지). tidy_hwpx.tidy_hwpx는 실패 시
    자체 die()(JSON stdout + sys.exit(1))를 쓰는데, in-process 호출이라 그
    stdout write가 fill_report 자신의 출력과 섞인다 — 그래서 호출 동안만
    stdout을 잠가 fill_report의 JSON 에러 포맷으로 통일한다.

    soft=True(§2: --form-profile 자동 유도 앵커 전용): 앵커 없음/모호는 전체
    실패가 아니라 "그 앵커만 스킵 + warning"으로 처리한다 — form_inspect가
    뽑은 anchors 목록은 tidy 안전(0 또는 2+매치)을 보장하지 않으므로, 유도된
    리스트 전체를 한 번에 넘기면 첫 모호 앵커에서 파이프라인이 죽는다. 앵커를
    하나씩 개별 호출해 실패한 것만 건너뛴다(우연히도 순서 유지). 반환값에
    "warnings": [{"anchor":..., "reason":...}] 키가 추가된다(성공 결과와 병합).

    keep_map(Rule 1, 선택): {anchor: keep_n} — read_tidy_anchors_with_source가
    유도한 anchor별 form-native blanks_before. soft 경로는 앵커를 하나씩
    개별 호출하므로 keep_map[anchor]를 그때마다 넘긴다."""
    keep_map = keep_map or {}
    if not soft:
        try:
            return _call_tidy_hwpx_quiet(hwpx_path, before_anchors, after_anchors, keep_map=keep_map)
        except SystemExit as e:
            die(f"tidy_hwpx 실패(exit {e.code}): 앵커 없음/모호 — before={before_anchors} "
                f"after={after_anchors}")

    removed = {}
    warnings = []
    for anchor in (before_anchors or []):
        try:
            r = _call_tidy_hwpx_quiet(hwpx_path, [anchor], [], keep_map=keep_map)
            removed.update(r.get("removed", {}))
        except SystemExit:
            warnings.append({"anchor": anchor, "direction": "before",
                              "reason": "not found or ambiguous — skipped (auto-derived)"})
    for anchor in (after_anchors or []):
        try:
            r = _call_tidy_hwpx_quiet(hwpx_path, [], [anchor], keep_map=keep_map)
            removed.update(r.get("removed", {}))
        except SystemExit:
            warnings.append({"anchor": anchor, "direction": "after",
                              "reason": "not found or ambiguous — skipped (auto-derived)"})
    return {"ok": True, "removed": removed, "warnings": warnings}


def run_keep_with_next(hwpx_path, prefixes):
    """tidy_hwpx.apply_keep_with_next를 프로세스 내에서 직접 호출(순수 stdlib,
    COM 불필요). 실패(프리픽스 매치 0건) 시 die()로 중단 — 조용히 넘어가지
    않는다(결정론 유지). in-process 호출 중 stdout을 잠가 tidy_hwpx 자체
    die()의 stdout write가 fill_report의 출력과 섞이지 않게 한다(run_tidy_hwpx
    와 동일 패턴)."""
    class _NullBuffer:
        def write(self, _data):
            pass

    class _NullStdout:
        buffer = _NullBuffer()

    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        result = tidy_hwpx.apply_keep_with_next(hwpx_path, prefixes or [], out_path=hwpx_path)
    except SystemExit as e:
        sys.stdout = saved_stdout
        die(f"apply_keep_with_next 실패(exit {e.code}): 프리픽스 매치 없음 — "
            f"prefixes={prefixes}")
    finally:
        sys.stdout = saved_stdout
    return result


def read_profile_anchors(form_profile):
    """form_profile.json의 anchors 목록. 부재/파싱 실패는 조용히 [] (루프를 막지 않음)."""
    if not form_profile or not Path(form_profile).exists():
        return []
    try:
        profile = json.loads(Path(form_profile).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(profile.get("anchors") or [])


def run_typeset_defaults(hwpx_path, anchors):
    """tidy_hwpx.apply_typeset_defaults를 프로세스 내에서 직접 호출 (§O).

    조판 기본값: 전 본문 widowOrphan=1, 제목(anchors)+캡션 keepWithNext=1.
    패스 순서 규약(tidy_hwpx docstring)대로 keep_with_next/restore 이후, PDF
    변환 직전에 실행한다. 멱등이므로 반복 루프에서 매번 호출해도 안전.
    실패는 die()로 중단 — run_keep_with_next와 동일 패턴(stdout 잠금)."""
    class _NullBuffer:
        def write(self, _data):
            pass

    class _NullStdout:
        buffer = _NullBuffer()

    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        result = tidy_hwpx.apply_typeset_defaults(hwpx_path, anchors or [],
                                                  out_path=hwpx_path)
    except SystemExit as e:
        sys.stdout = saved_stdout
        die(f"apply_typeset_defaults 실패(exit {e.code}): anchors={anchors}")
    finally:
        sys.stdout = saved_stdout
    return result


def baseline_has_para_formats(baseline):
    """--baseline JSON에 para_formats 항목이 있으면 True(복원 대상 존재).
    baseline 부재/파일 없음/파싱 실패는 조용히 False(복원 스킵, 루프를 막지 않음)."""
    if not baseline or not Path(baseline).exists():
        return False
    try:
        cfg = json.loads(Path(baseline).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(cfg.get("para_formats"))


def run_restore_para_formats(hwpx_path, baseline):
    """tidy_hwpx.restore_para_formats를 프로세스 내에서 직접 호출.

    set_line_spacing(전역 SelectAll+ParagraphShape)이 뭉갠 양식 소유 제목/라벨
    문단의 line_spacing(180~200%)을 baseline para_formats 값으로 복원한다.
    tidy(빈 문단 정리) 이후, PDF 변환 이전에 실행 — run_tidy_hwpx와 동일하게
    실패 시 die()로 중단(결정론 유지), stdout은 호출 동안 잠근다."""
    class _NullBuffer:
        def write(self, _data):
            pass

    class _NullStdout:
        buffer = _NullBuffer()

    saved_stdout = sys.stdout
    sys.stdout = _NullStdout()
    try:
        result = tidy_hwpx.restore_para_formats(hwpx_path, baseline, out_path=hwpx_path)
    except SystemExit as e:
        sys.stdout = saved_stdout
        die(f"restore_para_formats 실패(exit {e.code}): baseline={baseline}")
    finally:
        sys.stdout = saved_stdout
    return result


def run_style_diff(out_hwpx, baseline, build_yaml):
    """style_diff.py를 서브프로세스로 실행해 anomalies 목록을 반환.
    baseline/hwpx 부재나 실행 오류 시 빈 목록(best-effort, 루프를 막지 않음)."""
    if not baseline or not Path(baseline).exists() or not Path(out_hwpx).exists():
        return []
    cmd = [sys.executable, str(HERE / "style_diff.py"), str(out_hwpx),
           "--baseline", str(baseline)]
    if build_yaml:
        cmd += ["--build-yaml", str(build_yaml)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    return payload.get("anomalies", [])


def run_para_format_check(out_hwpx, baseline_form):
    """Run the strict form-vs-output paragraph-format verification."""
    cmd = [sys.executable, str(HERE / "style_diff.py"), str(out_hwpx),
           "--baseline-form", str(baseline_form), "--check-para-formats"]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except Exception:
        die(f"style_diff --check-para-formats output parse failed: {raw[:300]}\n"
            f"stderr: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    if proc.returncode not in (0, 1) or "ok" not in payload or "anomalies" not in payload:
        die(f"style_diff --check-para-formats failed (exit {proc.returncode})")
    return payload


def xml_only_verdict(out_hwpx, verification, iteration=1):
    """Return the XML-only verdict JSON.

    ``status=xml_verified_no_proof`` is intentionally explicit: ``converged``
    means the available XML checks passed, while ``proof_unavailable`` means no
    rendered PDF proof was produced.  Downstream consumers must not treat this
    status as equivalent to a proof-backed convergence verdict.
    """
    anomalies = verification.get("anomalies", [])
    return {
        "status": "xml_verified_no_proof",
        "converged": not anomalies,
        "iterations": iteration,
        "engine": "xml",
        "phase": "xml",
        "proof_grade": "none",
        "proof_unavailable": True,
        "reason": ("XML-level verification complete; PDF proof unavailable"
                   if not anomalies else "XML paragraph-format verification failed"),
        "checks": {},
        "style_anomalies": anomalies,
        "needs": [],
        "hwpx": str(Path(out_hwpx).resolve()),
        "pdf": None,
        "preview_pdf": None,
    }


def _evidence_workspace(form, out_dir):
    """Infer the report workspace root from form/output paths.

    Canonical runs place both under ``<WS>/output``.  Unit and direct engine
    runs often use a temporary directory with a sibling ``fill`` output; the
    common-path fallback keeps those runs receipt-capable without inventing
    absolute paths in the receipt itself.
    """
    paths = []
    for value in (form, out_dir):
        try:
            paths.append(str(Path(value).expanduser().resolve()))
        except OSError:
            continue
    if not paths:
        return None
    try:
        common = Path(os.path.commonpath(paths))
    except ValueError:
        return None
    return common.parent if common.name.casefold() == "output" else common


def _renderer_backend(renderer_id=None, engine="xml"):
    """Map an executed renderer name to the closed evidence backend enum."""
    if engine != "xml":
        return "native_hancom_windows", "native_render"
    name = str(renderer_id or "").casefold()
    if "rhwp" in name:
        return "oss_preview_rhwp", "diagnostic_render"
    if "soffice" in name or "libreoffice" in name:
        return "oss_preview_libreoffice", "advisory_render"
    if "certif" in name:
        return "certified_renderer", "certified_render"
    return "xml_only", "structural_only"


def _apply_render_quality(verdict, source_hwpx, rendered_pdf):
    """Attach quality evidence and close the grade on quality/layout gates."""
    quality = render_quality.inspect(source_hwpx, rendered_pdf)
    quality = render_quality.apply_layout_gate(
        quality,
        converged=verdict.get("converged") is True,
        hard_checks=not bool(verdict.get("checks") or {}),
        style_clean=not bool(verdict.get("style_anomalies") or []),
        advisory_hold=(
            verdict.get("proof_grade") == "advisory"
            and not document_evidence.ADVISORY_PROOF_RELEASE_ENABLED
        ),
    )
    verdict["render_quality"] = dict(quality)
    if quality.get("state") != "passed":
        # Native Hancom's receipt is renderer provenance.  The Hangul checker
        # intentionally cannot classify every native font (for example
        # Type3), so an unknown/not-applicable result is diagnostic only and
        # must not erase a successful native grade.  A confirmed failed
        # quality result still downgrades, as do all non-native proof routes.
        native_unknown = (
            verdict.get("proof_grade") == "hancom"
            and quality.get("state") in {"unknown", "not_applicable"}
        )
        if not native_unknown:
            verdict["proof_grade"] = "none"
            verdict["proof_unavailable"] = True
        verdict["quality_reason"] = quality.get("reason_code")
    return quality


def _infer_renderer_id(pdf_cmd, explicit=None):
    if explicit:
        return str(explicit)
    if isinstance(pdf_cmd, str):
        try:
            tokens = shlex.split(pdf_cmd, posix=True)
        except ValueError:
            tokens = []
    elif isinstance(pdf_cmd, (list, tuple)):
        tokens = [str(item) for item in pdf_cmd]
    else:
        tokens = []
    return Path(tokens[0]).name if tokens else None


def _write_evidence_receipt(
    form,
    out_dir,
    out_hwpx,
    out_pdf=None,
    *,
    engine="xml",
    renderer_id=None,
    terminal_state="succeeded",
    exit_code=None,
    reason_code=None,
    reproducible_here=None,
    capability_facts=None,
    quality=None,
):
    """Persist one generic receipt; return it or ``None`` for non-canonical paths."""
    workspace = _evidence_workspace(form, out_dir)
    if workspace is None:
        return None
    backend, evidence_class = _renderer_backend(renderer_id, engine)
    input_path = out_hwpx if out_pdf is not None else form
    output_path = out_pdf if out_pdf is not None else out_hwpx
    try:
        receipt = document_evidence.build_receipt(
            workspace,
            backend=backend,
            evidence_class=evidence_class,
            terminal_state=terminal_state,
            input_path=input_path,
            output_path=output_path,
            input_role="assembled_hwpx" if out_pdf is not None else "source_form",
            output_role="rendered_pdf" if out_pdf is not None else "assembled_hwpx",
            exit_code=exit_code,
            reason_code=reason_code,
            renderer_id=renderer_id,
            reproducible_here=reproducible_here,
            capability_facts=capability_facts,
            quality=quality,
        )
        document_evidence.write_receipt(workspace, receipt)
        return receipt
    except document_evidence.EvidenceError:
        # A caller may intentionally assemble from a form outside a report
        # workspace in an operator scratch run.  Do not turn that path error
        # into a false proof claim; the verdict remains truthful and the
        # submission preflight will require a valid receipt for any grade.
        return None


def _invalidate_evidence_receipt(form, out_dir):
    """Remove a prior run's receipt before a new terminal execution.

    If COM/XML setup fails before it can emit a verdict, a previous successful
    receipt must not remain eligible for that new run.  The next preflight will
    then fail closed on a non-`none` stale verdict instead of accepting old
    bytes as current evidence.
    """
    workspace = _evidence_workspace(form, out_dir)
    if workspace is None:
        return
    target = workspace / document_evidence.RECEIPT_REL
    try:
        if target.is_file() or target.is_symlink():
            target.unlink()
    except OSError as exc:
        # A failed cleanup leaves a previous terminal receipt eligible for a
        # new attempt.  Stop before execution rather than allowing stale
        # evidence to survive behind a fresh verdict.
        raise RuntimeError(
            f"could not invalidate prior evidence receipt: {target}"
        ) from exc


def renderer_failed_verdict(out_hwpx, iteration, render_result):
    """Return the measured-loop contract for an unusable external render."""
    error = render_result.get("error") or "external renderer failed"
    return {
        "ok": False,
        "status": "renderer_failed",
        "state": "renderer_failed",
        "converged": False,
        "escalate": True,
        "iterations": iteration,
        "page_count": None,
        "target_pages": None,
        "fig_count": None,
        "min_figures": None,
        "bottom_white_worst": {"page": None, "pct": None},
        "gaps_worst": {"page": None, "lines": None},
        "gappy_pages": [],
        "flagged_pages": [],
        "thresholds": {},
        "checks": {},
        "style_anomalies": [],
        "needs": [{"kind": "renderer_failed", "directive": error}],
        "reason": error,
        "proof_grade": "none",
        "proof_unavailable": True,
        "engine": "xml",
        "hwpx": str(Path(out_hwpx).resolve()),
        "pdf": None,
        "preview_pdf": None,
        "renderer": render_result,
    }


def finalize_loop_verdict(final, engine, max_loops):
    """Build the shared final FILL-loop JSON shape for COM and XML."""
    converged = bool(
        final.get("converged")
        and not any((final.get("checks") or {}).values())
        and not final.get("style_anomalies"))
    out_obj = {
        "converged": converged,
        "state": final.get("state"),
        "escalate": bool(not converged and final.get("iterations", 0) >= max_loops),
        "iterations": final["iterations"],
        "page_count": final["page_count"],
        "target_pages": final.get("target_pages"),
        "fig_count": final["fig_count"],
        "min_figures": final.get("min_figures"),
        "bottom_white_worst": final["bottom_white_worst"],
        "gaps_worst": final["gaps_worst"],
        "gappy_pages": final.get("gappy_pages", []),
        "flagged_pages": final.get("flagged_pages", []),
        "thresholds": final.get("thresholds", {}),
        "checks": final.get("checks", {}),
        "style_anomalies": final.get("style_anomalies", []),
        "needs": final.get("needs", []),
        "reason": final.get("reason"),
        "proof_grade": final.get("proof_grade", "hancom"),
        "hwpx": final.get("hwpx"),
        "pdf": final.get("pdf"),
        "preview_pdf": final.get("preview_pdf"),
    }
    if engine == "xml":
        out_obj["engine"] = "xml"
    for key in ("known_trouble", "calibration", "derived_tidy_anchors",
                "derived_keep_map", "tidy_warnings"):
        if key in final:
            out_obj[key] = final[key]
    return out_obj


def parse_trouble_table(path):
    """kb trouble-table 마크다운의 시그니처 키워드를 {code: [keywords]}로 파싱.
    표 형식이 다르거나 파일이 없으면 빈 dict(무음 스킵) — 미래 작업 훅이라
    부재를 에러로 취급하지 않는다."""
    if not path or not Path(path).exists():
        return {}
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        code = cells[0]
        if not re.match(r"^T\d+$", code):
            continue
        keywords = [c for c in cells[1:] if c]
        if keywords:
            out.setdefault(code, []).extend(keywords)
    return out


# ── PROOF 단계(--loop v2) ────────────────────────────────────────────────

RUBRIC_KEYS = (
    "mid_bottom_void", "density_uniformity", "table_proportion",
    "heading_plus_void",
)

PROOF_NEED_TYPES = {"rewrite_para", "resize_table"}


def build_proof_rubric():
    """4개 이진 체크의 null rubric 템플릿. 값 채우기는 호출자(vision judge)
    몫 — fill_report는 절대 채우지 않는다(측정·오케스트레이션만)."""
    return {k: None for k in RUBRIC_KEYS}


def count_proof_iter(events_path):
    """fill_events.jsonl을 스캔해 phase=='proof' 이벤트 중 최대 proof_iter를
    반환(없으면 0). 재진입 시 이 값 + 1이 현재 proof_iter가 된다 — 프로세스
    간 상태를 파일로만 영속화(메모리 상태 없음)."""
    path = Path(events_path)
    if not path.exists():
        return 0
    best = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("phase") == "proof":
            best = max(best, int(ev.get("proof_iter") or 0))
    return best


def validate_proof_needs(needs):
    """--proof-needs 스키마 검증. 유효하면 (True, None), 아니면
    (False, 이유). 형식: 리스트, 각 원소는 dict에 "type" in
    {rewrite_para, resize_table}.
      rewrite_para: anchor(str), delta_lines(int), reason(str) 필수.
      resize_table: index(int), cols(str, 콤마구분 정수) 필수."""
    if not isinstance(needs, list):
        return False, "proof-needs는 리스트여야 함"
    if not needs:
        return False, "proof-needs가 비어 있음"
    for i, item in enumerate(needs):
        if not isinstance(item, dict):
            return False, f"needs[{i}]는 dict여야 함"
        t = item.get("type")
        if t not in PROOF_NEED_TYPES:
            return False, f"needs[{i}].type 미지원: {t!r} (허용: {sorted(PROOF_NEED_TYPES)})"
        if t == "rewrite_para":
            if not isinstance(item.get("anchor"), str) or not item["anchor"]:
                return False, f"needs[{i}](rewrite_para).anchor는 비지 않은 str이어야 함"
            if not isinstance(item.get("delta_lines"), int):
                return False, f"needs[{i}](rewrite_para).delta_lines는 int여야 함"
            if not isinstance(item.get("reason"), str) or not item["reason"]:
                return False, f"needs[{i}](rewrite_para).reason은 비지 않은 str이어야 함"
        elif t == "resize_table":
            if not isinstance(item.get("index"), int):
                return False, f"needs[{i}](resize_table).index는 int여야 함"
            cols = item.get("cols")
            if not isinstance(cols, str) or not cols:
                return False, f"needs[{i}](resize_table).cols는 비지 않은 str이어야 함"
            parts = [p.strip() for p in cols.split(",")]
            if not all(p.isdigit() for p in parts):
                return False, f"needs[{i}](resize_table).cols는 콤마구분 정수여야 함: {cols!r}"
    return True, None


def load_proof_needs(path):
    """--proof-needs JSON 파일을 로드·검증. 실패 시 die(exit 1)."""
    p = Path(path)
    if not p.exists():
        die(f"--proof-needs 파일 없음: {p}", code=1)
    try:
        needs = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"--proof-needs JSON 파싱 실패: {e}", code=1)
    ok, reason = validate_proof_needs(needs)
    if not ok:
        die(f"--proof-needs 스키마 위반: {reason}", code=1)
    return needs


CONTACT_SHEET_REQUIRED_KEYS = ("pages", "sheets", "cell_size")


def run_contact_sheet(pdf_path, out_dir):
    """contact_sheet.py를 서브프로세스로 실행해 컨택트시트 PNG를 만든다.
    반환: {"pages":N, "sheets":[...], "cell_size":[w,h]}. 실패 시 die()."""
    cmd = [sys.executable, str(HERE / "contact_sheet.py"),
           "--pdf", str(pdf_path), "--out-dir", str(out_dir)]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, env=env)
    raw = proc.stdout.decode("utf-8", "replace")
    # A crashed contact_sheet.py commonly produces empty stdout, which used
    # to parse as {} and be treated as a successful (but keyless) payload.
    # Check the exit code first so a crash always dies loudly.
    if proc.returncode != 0:
        die(f"contact_sheet 비정상 종료 (exit {proc.returncode})\nstderr: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    try:
        payload = json.loads(raw.strip().splitlines()[-1]) if raw.strip() else {}
    except Exception:
        die(f"contact_sheet 출력 파싱 실패: {raw[:300]}\nstderr: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    if payload.get("ok") is False:
        die(f"contact_sheet 실패: {payload.get('error')}")
    missing = [k for k in CONTACT_SHEET_REQUIRED_KEYS if k not in payload]
    if missing:
        die(f"contact_sheet 출력에 필수 키 누락: {missing} — payload={raw[:300]}")
    return payload


def run_proof_phase(out_pdf, out_dir, events_path, max_proof_iters, proof_needs_path):
    """phase-1 FILL 루프가 converged된 뒤 실행하는 PROOF 단계.

    contact_sheet.py로 최종 PDF의 컨택트시트를 만들고, proof_iter(fill_events
    스캔으로 영속화)를 계산해 verdict 조각을 만든다. --proof-needs가 주어지면
    스키마 검증 후 이벤트 로그에 기록(재작성은 caller 몫, 여기선 안 함).
    proof_iter > max_proof_iters면 status를 escalate_human으로 바꾼다.
    반환: verdict에 병합할 dict 조각(phase, contact_sheets, proof_iter, rubric,
    status 등)."""
    proof_dir = Path(out_dir) / "proof"
    sheets_info = run_contact_sheet(out_pdf, proof_dir)

    prev_iter = count_proof_iter(events_path)
    proof_iter = prev_iter + 1

    proof_frag = {
        "phase": "proof",
        "contact_sheets": sheets_info.get("sheets", []),
        "proof_iter": proof_iter,
        "rubric": build_proof_rubric(),
    }

    needs = None
    if proof_needs_path:
        needs = load_proof_needs(proof_needs_path)
        proof_frag["needs"] = needs

    if proof_iter > max_proof_iters:
        proof_frag["status"] = "escalate_human"
        proof_frag["reason"] = (
            f"proof_iter {proof_iter} > max_proof_iters {max_proof_iters} — "
            "수렴 실패, 사람 검토 필요")
    else:
        proof_frag["status"] = "awaiting_judge" if needs is None else "needs_applied"

    event = {
        "ts": time.time(), "iter": proof_iter, "phase": "proof",
        "proof_iter": proof_iter,
    }
    if needs is not None:
        event["needs"] = needs
    else:
        event["result"] = {"contact_sheets": proof_frag["contact_sheets"],
                            "rubric": proof_frag["rubric"],
                            "status": proof_frag["status"]}
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return proof_frag


# 사람 개입을 요구하는 terminal status — converged:true와 논리적으로 양립 불가.
# rigorloom pipeline/scripts/verdict_schema.py의 ESCALATION_STATUSES와 짝을 맞춘다.
ESCALATION_STATUSES = frozenset({"escalate_human"})


def merge_proof_fragment(out_obj, proof_frag):
    """PROOF 단계 조각을 phase-1 FILL 루프 verdict에 병합한다(내부 일관성 보장).

    shared-miss #5 근본 원인: 예전엔 plain ``out_obj.update(proof_frag)``라서
    proof 단계가 status:"escalate_human"을 얹어도 phase-1의 converged:True가
    그대로 남아 자기모순 verdict(converged:true + escalate_human)가 방출됐다 —
    rigorloom verdict_schema가 read-time에 HARD finding으로 거부하는 쌍.

    수정: escalation status가 병합되면 converged를 False로 내리고 escalate를
    True로 맞춘다. phase-1 수렴 사실은 phase1_converged로 따로 보존한다
    (정보 손실 없음 — proof 재진입 시 FILL 루프를 다시 돌 필요가 없다는 근거)."""
    out_obj.update(proof_frag)
    status = str(out_obj.get("status") or "").strip().lower()
    if status in ESCALATION_STATUSES and out_obj.get("converged"):
        out_obj["phase1_converged"] = True
        out_obj["converged"] = False
        out_obj["escalate"] = True
    return out_obj


def match_trouble(verdict, checks, style_anomalies, trouble_map):
    """verdict/checks/anomalies 텍스트에서 trouble_map 시그니처 키워드가
    등장하는 첫 코드를 반환(없으면 None). 실제 수정 오퍼레이션은 미래 작업 —
    여기서는 verdict에 known_trouble만 주석 단다."""
    if not trouble_map:
        return None
    haystack_parts = [json.dumps(checks, ensure_ascii=False),
                       json.dumps(style_anomalies, ensure_ascii=False),
                       json.dumps(verdict.get("needs", []), ensure_ascii=False)]
    haystack = " ".join(haystack_parts)
    for code, keywords in trouble_map.items():
        for kw in keywords:
            if kw and kw in haystack:
                return code
    return None


def mode_loop(args):
    for req, name in ((args.form, "--form"), (args.content, "--content"),
                      (args.out_dir, "--out-dir")):
        if not req:
            die(f"--loop에 {name} 필요")
    form = Path(args.form)
    content = Path(args.content)
    if not form.exists():
        die(f"양식 없음: {form}")
    if not content.exists():
        die(f"content.md 없음: {content}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _invalidate_evidence_receipt(form, out_dir)
    preview_dir = out_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)

    ops_path = out_dir / "ops.json"
    out_hwpx = out_dir / "out.hwpx"
    out_pdf = out_dir / "out.pdf"
    events_path = out_dir / "fill_events.jsonl"
    engine = getattr(args, "engine", "com") or "com"
    pdf_cmd = getattr(args, "pdf_cmd", None)
    renderer_id = _infer_renderer_id(pdf_cmd, getattr(args, "renderer_id", None))
    proof_grade = "advisory" if engine == "xml" else "hancom"
    calibration = (load_calibration(getattr(args, "calibration", None))
                   if proof_grade == "advisory" else None)
    pdf_timeout = float(getattr(args, "pdf_timeout", 120.0) or 120.0)

    fill = read_fill(args.build_yaml)
    max_loops = max(1, int(args.max_loops or 4))
    trouble_map = parse_trouble_table(args.trouble_table)
    guide_strings = load_guide_strings(args.guide_file)
    spacing_skip_pages = layout_qa.parse_skip_pages(args.spacing_skip_pages)
    gap_skip_pages = layout_qa.parse_skip_pages(args.gap_skip_pages)
    bottom_skip_pages = layout_qa.parse_skip_pages(
        getattr(args, "bottom_skip_pages", None))
    form_profile = getattr(args, "form_profile", None)
    tidy_before, tidy_after, derived_tidy_anchors, tidy_keep_map = read_tidy_anchors_with_source(
        args.build_yaml, form_profile, content)
    keep_with_next = read_keep_with_next(args.build_yaml)
    use_restore = baseline_has_para_formats(args.baseline)
    use_tidy = bool(tidy_before or tidy_after) or use_restore or bool(keep_with_next)
    tidy_soft = bool(derived_tidy_anchors)  # 유도 앵커는 모호/없음을 fatal 대신 skip.

    result = None
    quality = None
    prev_sig = None
    trouble_retried = False
    for i in range(1, max_loops + 1):
        # 매 반복 pristine FORM에서 시작(FORM 제자리 편집 금지).
        run_build_report(content, form, args.build_yaml, ops_path,
                         form_profile=form_profile)
        tidy_warnings = []
        xml_para_verification = None
        if engine == "xml":
            run_xml_edit(form, ops_path, out_hwpx)
            tidy_result = run_tidy_hwpx(out_hwpx, tidy_before, tidy_after, soft=tidy_soft,
                                        keep_map=tidy_keep_map)
            tidy_warnings = (tidy_result or {}).get("warnings", [])
            if use_restore:
                run_restore_para_formats(out_hwpx, args.baseline)
            if keep_with_next:
                run_keep_with_next(out_hwpx, keep_with_next)
            xml_para_verification = run_para_format_check(out_hwpx, form)
            if not pdf_cmd:
                verdict = xml_only_verdict(out_hwpx, xml_para_verification, i)
                if derived_tidy_anchors:
                    verdict["derived_tidy_anchors"] = derived_tidy_anchors
                if tidy_keep_map:
                    verdict["derived_keep_map"] = tidy_keep_map
                if tidy_warnings:
                    verdict["tidy_warnings"] = tidy_warnings
                event = {"iter": i, "ts": time.time(), "verdict": verdict}
                with open(events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                _write_evidence_receipt(
                    form, out_dir, out_hwpx, engine=engine,
                    renderer_id=renderer_id, exit_code=0,
                    reason_code="xml_verified_no_proof",
                    capability_facts=getattr(args, "capability_facts", None))
                _emit(verdict, args.out or str(out_dir / "verdict_v06.json"))
                return
            render_result = run_pdf_command(
                pdf_cmd, out_hwpx, out_pdf, timeout=pdf_timeout)
            if not render_result.get("ok"):
                failed = renderer_failed_verdict(out_hwpx, i, render_result)
                if derived_tidy_anchors:
                    failed["derived_tidy_anchors"] = derived_tidy_anchors
                if tidy_keep_map:
                    failed["derived_keep_map"] = tidy_keep_map
                if tidy_warnings:
                    failed["tidy_warnings"] = tidy_warnings
                event = {"iter": i, "ts": time.time(), "verdict": failed}
                with open(events_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                _write_evidence_receipt(
                    form, out_dir, out_hwpx, out_pdf,
                    engine=engine, renderer_id=renderer_id,
                    terminal_state="failed", exit_code=render_result.get("returncode"),
                    reason_code="renderer_failed",
                    capability_facts=getattr(args, "capability_facts", None))
                _emit(failed, args.out or str(out_dir / "verdict_v06.json"))
                return
        elif use_tidy:
            # edit(save hwpx만, PDF 아직 아님) -> tidy_hwpx(오프라인) ->
            # restore_para_formats(오프라인) -> keep_with_next(오프라인) ->
            # convert(hwpx->pdf).
            run_com_edit(form, ops_path, out_hwpx, None, args.kill_stale)
            tidy_result = run_tidy_hwpx(out_hwpx, tidy_before, tidy_after, soft=tidy_soft,
                                        keep_map=tidy_keep_map)
            tidy_warnings = (tidy_result or {}).get("warnings", [])
            if use_restore:
                run_restore_para_formats(out_hwpx, args.baseline)
            if keep_with_next:
                run_keep_with_next(out_hwpx, keep_with_next)
            run_com_convert(out_hwpx, out_pdf)
        else:
            # 기존 경로: edit 한 방에 save-as + export-pdf.
            run_com_edit(form, ops_path, out_hwpx, out_pdf, args.kill_stale)

        try:
            verdict = measure_rendered_pdf(
                out_pdf, fill, proof_grade, args.fig_count, guide_strings,
                spacing_skip_pages=spacing_skip_pages,
                gap_skip_pages=gap_skip_pages,
                bottom_skip_pages=bottom_skip_pages,
                calibration=calibration)
        except Exception as exc:
            if engine != "xml":
                raise
            render_result = {
                "ok": False, "state": "renderer_failed", "pdf": str(out_pdf),
                "error": f"renderer output could not be measured: {exc}",
            }
            failed = renderer_failed_verdict(out_hwpx, i, render_result)
            event = {"iter": i, "ts": time.time(), "verdict": failed}
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            _write_evidence_receipt(
                form, out_dir, out_hwpx, out_pdf,
                engine=engine, renderer_id=renderer_id,
                terminal_state="failed", reason_code="renderer_output_unmeasurable",
                capability_facts=getattr(args, "capability_facts", None))
            _emit(failed, args.out or str(out_dir / "verdict_v06.json"))
            return

        style_anomalies = run_style_diff(out_hwpx, args.baseline, args.build_yaml)
        if xml_para_verification is not None:
            style_anomalies = style_anomalies + xml_para_verification.get("anomalies", [])
        verdict["style_anomalies"] = style_anomalies
        if derived_tidy_anchors:
            verdict["derived_tidy_anchors"] = derived_tidy_anchors
        if tidy_keep_map:
            verdict["derived_keep_map"] = tidy_keep_map
        if tidy_warnings:
            verdict["tidy_warnings"] = tidy_warnings

        quality = _apply_render_quality(verdict, out_hwpx, out_pdf)

        iter_pdf = preview_dir / f"iter_{i}.pdf"
        shutil.copyfile(out_pdf, iter_pdf)

        # studio 정체 배너 오탐 방지: 워크스페이스 heartbeat를 반복마다 갱신
        # (pipeline_ctl 미호출 구간에서도 "달리고 있음"이 보이도록).
        try:
            hb = out_dir.parent / "heartbeat"
            if hb.parent.exists():
                import datetime
                hb.write_text(datetime.datetime.now().isoformat(timespec="seconds"),
                              encoding="utf-8")
        except Exception:
            pass

        checks_pass = not any((verdict["checks"] or {}).values())
        style_pass = not style_anomalies
        state = verdict["state"]
        if verdict["converged"] and checks_pass and style_pass:
            reason = "converged: pass + pages-in-window + figs>=min + checks clean"
        elif not checks_pass or not style_pass:
            reason = f"anomalies present (layout_qa/style_diff) — state={state}"
        else:
            reason = f"state={state}"
        verdict["reason"] = reason
        verdict["iter"] = i

        code = match_trouble(verdict, verdict["checks"], style_anomalies, trouble_map)
        if code:
            verdict["known_trouble"] = code

        event = {"iter": i, "ts": time.time(), "verdict": verdict}
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

        result = verdict
        result["hwpx"] = str(out_hwpx.resolve())
        result["pdf"] = str(out_pdf.resolve())
        result["preview_pdf"] = str(iter_pdf.resolve())
        result["iterations"] = i

        converged = bool(verdict["converged"] and checks_pass and style_pass)
        if converged:
            break

        sig = (verdict["converged"], verdict["page_count"], verdict["fig_count"],
               state, checks_pass, style_pass)
        if code and not trouble_retried:
            # kb trouble-table 시그니처 매치 — 동일 content로 1회만 재시도.
            trouble_retried = True
            prev_sig = sig
            continue
        if sig == prev_sig:
            # 동일 content 재조립은 결과가 안 바뀐다 — needs를 caller(writer)에게 넘긴다.
            break
        prev_sig = sig

    final = dict(result)
    final.setdefault("needs", result.get("needs", []))
    out_obj = finalize_loop_verdict(final, engine, max_loops)
    if quality is not None:
        out_obj["render_quality"] = dict(quality)

    # PROOF 단계: phase-1이 converged로 끝났고 --proof가 설정된 경우에만.
    # 미수렴 상태에서 컨택트시트를 만들어봐야 needs가 이미 phase-1에서
    # 나와 있으므로 무의미 — writer가 먼저 그 needs를 처리해야 한다.
    if getattr(args, "proof", False):
        if out_obj["converged"]:
            max_proof_iters = max(1, int(getattr(args, "max_proof_iters", 3) or 3))
            proof_needs_path = getattr(args, "proof_needs", None)
            proof_frag = run_proof_phase(
                final["pdf"], out_dir, events_path, max_proof_iters, proof_needs_path)
            merge_proof_fragment(out_obj, proof_frag)
        else:
            out_obj["phase"] = "fill"
            out_obj["proof_skipped_reason"] = "phase-1 not converged — resolve needs first"

    _write_evidence_receipt(
        form, out_dir, out_hwpx, out_pdf,
        engine=engine, renderer_id=renderer_id,
        exit_code=0,
        reason_code=("fill_loop_complete" if out_obj.get("converged")
                     else (quality.get("reason_code") if quality
                           and quality.get("state") != "passed"
                           else "fill_loop_not_converged")),
        capability_facts=getattr(args, "capability_facts", None),
        quality=quality)
    _emit(out_obj, args.out or str(out_dir / "verdict_v06.json"))


def mode_measure(args):
    if not Path(args.pdf).exists():
        die(f"PDF 없음: {args.pdf}")
    fill = read_fill(args.build_yaml)
    proof_grade = ("advisory"
                   if (getattr(args, "engine", "com") or "com") == "xml"
                   else "hancom")
    calibration = (load_calibration(getattr(args, "calibration", None))
                   if proof_grade == "advisory" else None)
    guide_strings = load_guide_strings(args.guide_file)
    spacing_skip_pages = layout_qa.parse_skip_pages(args.spacing_skip_pages)
    gap_skip_pages = layout_qa.parse_skip_pages(args.gap_skip_pages)
    bottom_skip_pages = layout_qa.parse_skip_pages(
        getattr(args, "bottom_skip_pages", None))
    verdict = measure_rendered_pdf(
        args.pdf, fill, proof_grade, args.fig_count, guide_strings,
        spacing_skip_pages=spacing_skip_pages,
        gap_skip_pages=gap_skip_pages,
        bottom_skip_pages=bottom_skip_pages,
        calibration=calibration)
    _emit(verdict, args.out)


def mode_assemble(args):
    for req, name in ((args.form, "--form"), (args.content, "--content"),
                      (args.out_dir, "--out-dir")):
        if not req:
            die(f"--assemble에 {name} 필요")
    form = Path(args.form)
    content = Path(args.content)
    if not form.exists():
        die(f"양식 없음: {form}")
    if not content.exists():
        die(f"content.md 없음: {content}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _invalidate_evidence_receipt(form, out_dir)

    ops_path = out_dir / "ops.json"
    out_hwpx = out_dir / "out.hwpx"   # 단일 정규 이름(버전 누적 금지, 항상 덮어씀).
    out_pdf = out_dir / "out.pdf"
    engine = getattr(args, "engine", "com") or "com"
    pdf_cmd = getattr(args, "pdf_cmd", None)
    renderer_id = _infer_renderer_id(pdf_cmd, getattr(args, "renderer_id", None))
    proof_grade = "advisory" if engine == "xml" else "hancom"
    calibration = (load_calibration(getattr(args, "calibration", None))
                   if proof_grade == "advisory" else None)
    pdf_timeout = float(getattr(args, "pdf_timeout", 120.0) or 120.0)

    fill = read_fill(args.build_yaml)
    iters = max(1, int(args.max_iters or 1))
    form_profile = getattr(args, "form_profile", None)
    tidy_before, tidy_after, derived_tidy_anchors, tidy_keep_map = read_tidy_anchors_with_source(
        args.build_yaml, form_profile, content)
    tidy_soft = bool(derived_tidy_anchors)
    keep_with_next = read_keep_with_next(args.build_yaml)
    use_restore = baseline_has_para_formats(getattr(args, "baseline", None))
    use_tidy = (bool(tidy_before or tidy_after) or use_restore
                or bool(keep_with_next) or bool(form_profile))
    verdicts = []
    quality = None
    for _ in range(iters):
        # 매 반복 pristine FORM에서 시작(FORM 제자리 편집 금지; save-as≠file 가드).
        run_build_report(content, form, args.build_yaml, ops_path,
                         form_profile=form_profile)
        xml_para_verification = None
        if engine == "xml":
            run_xml_edit(form, ops_path, out_hwpx)
            run_tidy_hwpx(out_hwpx, tidy_before, tidy_after, soft=tidy_soft,
                          keep_map=tidy_keep_map)
            if use_restore:
                run_restore_para_formats(out_hwpx, args.baseline)
            if keep_with_next:
                run_keep_with_next(out_hwpx, keep_with_next)
            if form_profile:
                run_typeset_defaults(out_hwpx, read_profile_anchors(form_profile))
            xml_para_verification = run_para_format_check(out_hwpx, form)
            if not pdf_cmd:
                verdicts.append(xml_only_verdict(out_hwpx, xml_para_verification,
                                                  len(verdicts) + 1))
                continue
            render_result = run_pdf_command(
                pdf_cmd, out_hwpx, out_pdf, timeout=pdf_timeout)
            if not render_result.get("ok"):
                # Assemble is the optional-measure path.  Only its first failed
                # render may fall back to the explicit XML no-proof result.
                if not verdicts:
                    failed = xml_only_verdict(
                        out_hwpx, xml_para_verification, len(verdicts) + 1)
                    failed["renderer_error"] = render_result.get("error")
                    failed["renderer_attempted"] = True
                else:
                    failed = renderer_failed_verdict(
                        out_hwpx, len(verdicts) + 1, render_result)
                verdicts.append(failed)
                break
        elif use_tidy:
            run_com_edit(form, ops_path, out_hwpx, None, args.kill_stale)
            run_tidy_hwpx(out_hwpx, tidy_before, tidy_after, soft=tidy_soft,
                          keep_map=tidy_keep_map)
            if use_restore:
                run_restore_para_formats(out_hwpx, args.baseline)
            if keep_with_next:
                run_keep_with_next(out_hwpx, keep_with_next)
            # §O 조판 기본값 — form_profile이 주어지면 적용(멱등). 패스 순서 규약 준수.
            if form_profile:
                run_typeset_defaults(out_hwpx, read_profile_anchors(form_profile))
            run_com_convert(out_hwpx, out_pdf)
        else:
            run_com_edit(form, ops_path, out_hwpx, out_pdf, args.kill_stale)
        try:
            v = measure_rendered_pdf(
                out_pdf, fill, proof_grade, args.fig_count,
                calibration=calibration)
        except Exception as exc:
            if engine != "xml":
                raise
            render_result = {
                "ok": False, "state": "renderer_failed", "pdf": str(out_pdf),
                "error": f"renderer output could not be measured: {exc}",
            }
            if not verdicts:
                v = xml_only_verdict(
                    out_hwpx, xml_para_verification, len(verdicts) + 1)
                v["renderer_error"] = render_result["error"]
                v["renderer_attempted"] = True
            else:
                v = renderer_failed_verdict(
                    out_hwpx, len(verdicts) + 1, render_result)
            verdicts.append(v)
            break
        if xml_para_verification is not None:
            v["engine"] = "xml"
            v["style_anomalies"] = xml_para_verification.get("anomalies", [])
            v["converged"] = bool(v.get("converged") and not v["style_anomalies"])
        v["hwpx"] = str(out_hwpx.resolve())
        v["pdf"] = str(out_pdf.resolve())
        if derived_tidy_anchors:
            v["derived_tidy_anchors"] = derived_tidy_anchors
        if tidy_keep_map:
            v["derived_keep_map"] = tidy_keep_map
        quality = _apply_render_quality(v, out_hwpx, out_pdf)
        verdicts.append(v)

    result = verdicts[-1]
    if iters > 1:
        # 멱등성 증명: 동일 입력 재조립 시 verdict 핵심 필드 동일해야 함.
        keys = (("converged", "style_anomalies") if engine == "xml" and not pdf_cmd
                else ("converged", "page_count", "fig_count", "state"))
        sigs = [tuple(v[k] for k in keys) for v in verdicts]
        result["idempotent"] = all(s == sigs[0] for s in sigs)
        result["iterations"] = iters
    if pdf_cmd and result.get("renderer_attempted"):
        terminal_state = "failed"
        reason_code = "renderer_failed"
    elif pdf_cmd and not result.get("pdf"):
        terminal_state = "failed"
        reason_code = "renderer_output_missing"
    else:
        terminal_state = "succeeded"
        reason_code = (
            quality.get("reason_code")
            if quality and quality.get("state") != "passed"
            else ("assembly_render_succeeded" if pdf_cmd or engine != "xml"
                  else "xml_assembly_succeeded")
        )
    receipt_output = out_pdf if pdf_cmd or engine != "xml" else None
    _write_evidence_receipt(
        form, out_dir, out_hwpx, receipt_output,
        engine=engine, renderer_id=renderer_id,
        terminal_state=terminal_state, reason_code=reason_code,
        exit_code=(0 if terminal_state == "succeeded" else None),
        capability_facts=getattr(args, "capability_facts", None),
        quality=quality)
    _emit(result, args.out or str(out_dir / "verdict_v06.json"))


def main():
    # cp949 콘솔 안전(--help의 em-dash 포함) — parse_args보다 먼저.
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true", help="측정 모드(오프라인)")
    ap.add_argument("--assemble", action="store_true", help="조립 1회(COM 필요)")
    ap.add_argument("--loop", action="store_true",
                    help="FILL 루프 오케스트레이션(COM 필요)")
    ap.add_argument("--pdf", help="(measure) 측정할 PDF")
    ap.add_argument("--form", help="(assemble/loop) 양식 .hwpx/.hwp")
    ap.add_argument("--content", help="(assemble/loop) bundle/content.md")
    ap.add_argument("--out-dir", help="(assemble/loop) 산출물 디렉터리")
    ap.add_argument("--build-yaml", help="build.yaml(fill 목표) 경로")
    ap.add_argument("--engine", choices=("com", "xml"), default="com",
                    help="(assemble/loop) 편집 엔진. 기본 com; xml은 COM-free HWPX 전용")
    ap.add_argument("--pdf-cmd",
                    help="(xml) 선택적 PDF 렌더러 argv 템플릿. {input}, {output}, "
                         "{out_dir}, {stem} 사용 가능; 예: 'soffice --headless "
                         "--convert-to pdf --outdir {out_dir} {input}'")
    ap.add_argument("--pdf-timeout", type=float, default=120.0,
                    help="(xml --pdf-cmd) renderer timeout in seconds (default 120)")
    ap.add_argument("--renderer-id",
                    help="(xml --pdf-cmd) named runtime for evidence routing "
                         "(soffice_local, rhwp_svg, certified_renderer)")
    ap.add_argument("--calibration",
                    help="(xml advisory proof) JSON threshold relaxations, e.g. "
                         "bottom_white_tolerance_pt and max_gap_scale")
    ap.add_argument("--guide-file",
                    help="(measure/loop) layout_qa로 전달할 안내문 원문 JSON 목록. "
                         "생략 시 기존 동작 그대로")
    ap.add_argument("--bottom-skip-pages",
                    help="(measure/loop) bottom_white 체크를 건너뛸 1-based 페이지 "
                         "번호, 콤마 구분(예: \"2\"). 요약처럼 양식 고정 셀이 하단 "
                         "공백을 강제하는 구조 페이지용(§P: 양식 구조 공백은 결함 "
                         "아님). 생략 시 기존 동작 그대로")
    ap.add_argument("--spacing-skip-pages",
                    help="(measure/loop) line_spacing_uniformity 체크를 건너뛸 "
                         "1-based 페이지 번호, 콤마 구분(예: \"1,2\"). 표지/요약 등 "
                         "의도된 여백 페이지용. 생략 시 기존 동작 그대로")
    ap.add_argument("--gap-skip-pages",
                    help="(measure/loop) max_gap_lines(구멍) 체크를 건너뛸 1-based "
                         "페이지 번호, 콤마 구분(예: \"1,2\"). 양식 설계상 박스 내부/"
                         "표지처럼 구조적으로 큰 간격이 의도된 페이지용. 생략 시 "
                         "기존 동작 그대로")
    ap.add_argument("--fig-count", type=int, default=None,
                    help="이미지 개수 수동 지정(생략 시 PDF에서 계수)")
    ap.add_argument("--kill-stale", action="store_true",
                    help="(assemble/loop) 잔존 한글 프로세스 정리")
    ap.add_argument("--max-iters", type=int, default=1,
                    help="(assemble) 동일 content 재조립 횟수(멱등성 검증용)")
    ap.add_argument("--max-loops", type=int, default=4,
                    help="(loop) 최대 반복 횟수")
    ap.add_argument("--baseline", help="(assemble/loop) form_baseline.json — style_diff 병합용 "
                                        "+ para_formats 있으면 tidy 이후 line_spacing/align 복원")
    ap.add_argument("--trouble-table", help="(loop) kb trouble-table 마크다운 경로")
    ap.add_argument("--form-profile",
                    help="(loop) form_inspect.py profile JSON — build.yaml에 "
                         "tidy_blank_before/after가 둘 다 없을 때 anchors 목록을 "
                         "tidy_blank_before로 자동 유도(explicit build.yaml 키가 항상 우선)")
    ap.add_argument("--proof", action="store_true",
                    help="(loop) phase-1 FILL 루프 수렴 후 PROOF 단계 실행: "
                         "contact_sheet.py로 컨택트시트 생성 + rubric 템플릿 방출")
    ap.add_argument("--max-proof-iters", type=int, default=3,
                    help="(loop --proof) PROOF 재진입 최대 횟수(기본 3). 초과 시 "
                         "status=escalate_human")
    ap.add_argument("--proof-needs",
                    help="(loop --proof) 재진입 시 caller가 주는 needs JSON 경로 — "
                         "스키마 위반이면 exit 1. fill_report는 이 needs로 content를 "
                         "재작성하지 않는다(writer 몫), fill_events.jsonl에만 기록")
    ap.add_argument("--out", help="verdict JSON 출력 파일(생략 시 stdout)")
    args = ap.parse_args()

    modes = [args.measure, args.assemble, args.loop]
    if sum(bool(m) for m in modes) != 1:
        die("정확히 하나의 모드(--measure, --assemble, --loop 중)를 지정하세요")
    if args.measure:
        if not args.pdf:
            die("--measure에 --pdf 필요")
        mode_measure(args)
    elif args.assemble:
        mode_assemble(args)
    else:
        mode_loop(args)


if __name__ == "__main__":
    main()
