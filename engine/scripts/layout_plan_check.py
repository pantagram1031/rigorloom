"""layout_plan.json 검증기 — Stage 2.5 스크립트 게이트 (CONTRACT v0.6 §N).

캐스트오프(조판 전 분량 설계)의 결정론 검증: 섹션 줄 예산 합이 목표 쪽수 창
안에 들어가는지, 표 열폭 계획이 온전한지 검사한다. exit 0 = 게이트 통과.

사용:
  python layout_plan_check.py bundle/layout_plan.json \
      --form-profile form_profile.json [--figure-lines 14] [--lines-per-page N]

판정 규칙 (stage-2.5 playbook과 동일):
  planned = Σ section line_budget
          + Σ table (est_rows + CAPTION_LINES)
          + Σ display equation × EQ_DISPLAY_LINES   (inline은 0 — 문장 속에 흡수)
          + Σ figure × figure_lines                 (말미 그림 모음)
  capacity_max = target_pages[1] × lines_per_page
  capacity_min = target_pages[0] × lines_per_page
  fail if planned > capacity_max            (넘침 — 예산 축소 필요)
  fail if planned < capacity_min            (계획된 공백 — 미달)
  fail if any table cols_pct sum ∉ [95,105] or any col ≤ 0
  fail if schema 필수 키 누락 (target_pages, sections[].anchor/line_budget)

lines_per_page는 form_profile.json의 page_metrics.lines_per_page에서 읽고,
--lines-per-page로 덮어쓸 수 있다. 둘 다 없으면 exit 1.
출력: JSON verdict {"ok", "planned", "capacity": [min,max], "breakdown", "errors"}.
"""
import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CAPTION_LINES = 2      # 표 캡션+주변 여백의 줄 환산
EQ_DISPLAY_LINES = 2   # display 수식 1개의 줄 환산 (inline=0)


def die(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        die(f"{what} 없음: {path}")
    except json.JSONDecodeError as e:
        die(f"{what} JSON 파싱 실패: {e}")


def check(plan, lines_per_page, figure_lines):
    errors = []
    tp = plan.get("target_pages")
    if (not isinstance(tp, list) or len(tp) != 2
            or not all(isinstance(x, (int, float)) and x > 0 for x in tp)
            or tp[0] > tp[1]):
        errors.append("target_pages는 [min,max] 양수 쌍이어야 함")
        tp = None

    sections = plan.get("sections")
    sec_total = 0
    if not isinstance(sections, list) or not sections:
        errors.append("sections 누락/비어 있음")
    else:
        for i, s in enumerate(sections):
            if not isinstance(s, dict) or not s.get("anchor"):
                errors.append(f"sections[{i}]: anchor 누락")
                continue
            lb = s.get("line_budget")
            if not isinstance(lb, int) or lb <= 0:
                errors.append(f"sections[{i}] '{s.get('anchor')}': line_budget 양의 정수 아님")
                continue
            sec_total += lb

    tbl_total = 0
    for i, t in enumerate(plan.get("tables") or []):
        cols = t.get("cols_pct")
        if cols is not None:
            if (not isinstance(cols, list) or not cols
                    or any(not isinstance(c, (int, float)) or c <= 0 for c in cols)):
                errors.append(f"tables[{i}] '{t.get('id')}': cols_pct에 0 이하/비수치 값")
            elif not (95 <= sum(cols) <= 105):
                errors.append(f"tables[{i}] '{t.get('id')}': cols_pct 합 {sum(cols)} (95~105 밖)")
        rows = t.get("est_rows")
        if not isinstance(rows, int) or rows <= 0:
            errors.append(f"tables[{i}] '{t.get('id')}': est_rows 양의 정수 아님")
        else:
            tbl_total += rows + CAPTION_LINES

    eq_total = sum(EQ_DISPLAY_LINES for e in (plan.get("equations") or [])
                   if isinstance(e, dict) and e.get("mode") == "display")
    fig_total = figure_lines * len(plan.get("figures") or [])

    planned = sec_total + tbl_total + eq_total + fig_total
    breakdown = {"sections": sec_total, "tables": tbl_total,
                 "equations_display": eq_total, "figures": fig_total}

    capacity = None
    if tp and not errors:
        capacity = [int(tp[0] * lines_per_page), int(tp[1] * lines_per_page)]
        if planned > capacity[1]:
            errors.append(f"넘침: planned {planned}줄 > capacity_max {capacity[1]}줄 — 예산 축소 필요")
        if planned < capacity[0]:
            errors.append(f"미달(계획된 공백): planned {planned}줄 < capacity_min {capacity[0]}줄")
    elif tp:
        capacity = [int(tp[0] * lines_per_page), int(tp[1] * lines_per_page)]

    return {"ok": not errors, "planned": planned, "capacity": capacity,
            "lines_per_page": lines_per_page, "breakdown": breakdown,
            "errors": errors}


def main():
    ap = argparse.ArgumentParser(description="layout_plan.json 게이트 검증")
    ap.add_argument("plan", help="bundle/layout_plan.json")
    ap.add_argument("--form-profile", help="form_profile.json (page_metrics 출처)")
    ap.add_argument("--lines-per-page", type=int, default=None,
                    help="page_metrics 대신 직접 지정")
    ap.add_argument("--figure-lines", type=int, default=14,
                    help="그림 1개의 줄 환산 (기본 14)")
    args = ap.parse_args()

    lpp = args.lines_per_page
    if lpp is None:
        if not args.form_profile:
            die("--form-profile 또는 --lines-per-page 필요")
        prof = load_json(args.form_profile, "form_profile")
        lpp = (prof.get("page_metrics") or {}).get("lines_per_page")
        if not isinstance(lpp, int) or lpp <= 0:
            die("form_profile에 page_metrics.lines_per_page 없음 — "
                "form_inspect를 --base-pt/--line-spacing으로 재실행")

    plan = load_json(args.plan, "layout_plan")
    verdict = check(plan, lpp, args.figure_lines)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    sys.exit(0 if verdict["ok"] else 1)


if __name__ == "__main__":
    main()
