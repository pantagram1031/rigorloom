"""layout_plan_check.py 게이트 검증기 테스트 (오프라인, COM 불필요)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "layout_plan_check.py"

sys.path.insert(0, str(SCRIPT.parent))
from layout_plan_check import check, CAPTION_LINES, EQ_DISPLAY_LINES  # noqa: E402


def good_plan():
    return {
        "target_pages": [2, 3],
        "sections": [
            {"anchor": "Ⅰ. 서론", "line_budget": 30},
            {"anchor": "Ⅱ. 본론", "line_budget": 40},
        ],
        "tables": [{"id": "표1", "cols_pct": [10, 16, 12, 9, 10, 43],
                    "est_rows": 7, "pt": 9}],
        "figures": [{"id": "그림1", "width_mm": 110}],
        "equations": [{"id": "eq1", "mode": "inline"},
                      {"id": "eq2", "mode": "display"}],
    }


LPP = 45  # 소논문 양식 실측치와 동일한 스케일


def test_good_plan_passes():
    v = check(good_plan(), LPP, figure_lines=14)
    # planned = 70 + (7+2) + 2 + 14 = 95 ∈ [90, 135]
    assert v["planned"] == 70 + 7 + CAPTION_LINES + EQ_DISPLAY_LINES + 14
    assert v["capacity"] == [90, 135]
    assert v["ok"], v["errors"]


def test_overflow_fails():
    p = good_plan()
    p["sections"][1]["line_budget"] = 200
    v = check(p, LPP, 14)
    assert not v["ok"] and any("넘침" in e for e in v["errors"])


def test_underfill_fails():
    p = good_plan()
    p["sections"] = [{"anchor": "Ⅰ", "line_budget": 5}]
    p["tables"] = []
    p["figures"] = []
    p["equations"] = []
    v = check(p, LPP, 14)
    assert not v["ok"] and any("미달" in e for e in v["errors"])


def test_bad_cols_pct_sum_fails():
    p = good_plan()
    p["tables"][0]["cols_pct"] = [50, 10, 10]  # 합 70
    v = check(p, LPP, 14)
    assert not v["ok"] and any("cols_pct 합" in e for e in v["errors"])


def test_nonpositive_col_fails():
    p = good_plan()
    p["tables"][0]["cols_pct"] = [0, 50, 50]
    v = check(p, LPP, 14)
    assert not v["ok"] and any("0 이하" in e for e in v["errors"])


def test_inline_equations_cost_zero():
    p = good_plan()
    p["equations"] = [{"id": "e", "mode": "inline"}] * 5
    v = check(p, LPP, 14)
    assert v["breakdown"]["equations_display"] == 0


def test_missing_sections_fails():
    v = check({"target_pages": [1, 2]}, LPP, 14)
    assert not v["ok"]


def test_bad_target_pages_fails():
    p = good_plan()
    p["target_pages"] = [5, 2]
    v = check(p, LPP, 14)
    assert not v["ok"]


def test_cli_exit_codes(tmp_path):
    plan = tmp_path / "layout_plan.json"
    prof = tmp_path / "form_profile.json"
    prof.write_text(json.dumps({"page_metrics": {"lines_per_page": LPP}}),
                    encoding="utf-8")

    plan.write_text(json.dumps(good_plan(), ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(plan),
                        "--form-profile", str(prof)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["ok"] is True

    bad = good_plan()
    bad["sections"][0]["line_budget"] = 999
    plan.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(plan),
                        "--form-profile", str(prof)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1
    assert json.loads(r.stdout)["ok"] is False


def test_cli_missing_lpp_dies(tmp_path):
    plan = tmp_path / "layout_plan.json"
    plan.write_text(json.dumps(good_plan()), encoding="utf-8")
    prof = tmp_path / "form_profile.json"
    prof.write_text(json.dumps({}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(plan),
                        "--form-profile", str(prof)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1
    assert "page_metrics" in json.loads(r.stdout)["error"]
