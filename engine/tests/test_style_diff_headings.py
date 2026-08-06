"""style_diff.check_headings 회귀 테스트 (T7-class 손상 결정론 탐지).

실제 픽스처: pristine baseline form(templates/대수_추가탐구기록지_양식.hwpx)과
그 form으로 조립된 output(reports/report-aliasing-sampling/output/out.hwpx).
출력 픽스처는 이후 빌드에서 손상이 실제로 고쳐질 수 있으므로(라이브 워크스페이스
파일이라 결정론적 회귀 테스트 대상이 아님) 여기서는 out.hwpx를 tmp_path로 복사한
뒤 XML을 직접 편집해 T7-class 손상(heading_pt/heading_merged)을 합성 주입한다 —
라이브 파일 상태에 의존하지 않는다. `python -m pytest tests/ -q`.
"""
import os
import re
import shutil
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import style_diff  # noqa: E402
import tidy_hwpx  # noqa: E402

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
FORM = os.path.join(_WS, "templates", "대수_추가탐구기록지_양식.hwpx") if _WS else ""
OUT = os.path.join(_WS, "reports", "report-aliasing-sampling", "output", "out.hwpx") if _WS else ""
ANCHORS = ["Ⅰ. 서 론", "II.  이론적 배경", "III.  탐구방법", "IV.  탐구결과", "V.  참고문헌"]

pytestmark = pytest.mark.skipif(
    not (os.path.exists(FORM) and os.path.exists(OUT)),
    reason="real fixtures (baseline form / assembled output) not present on this machine",
)

NS = r"[A-Za-z0-9]+"


def _read(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def _write_section(path, xml_text):
    """zip 안 Contents/section0.xml만 교체한 새 zip을 같은 경로에 덮어씀."""
    with zipfile.ZipFile(path) as zin:
        items = {i.filename: (i, zin.read(i.filename)) for i in zin.infolist()}
    items["Contents/section0.xml"] = (items["Contents/section0.xml"][0], xml_text.encode("utf-8"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items.values():
            zout.writestr(info, data)


def _damage_heading_pt(xml, anchor_text, new_charpr_id):
    """anchor_text가 들어있는 run의 charPrIDRef를 new_charpr_id로 바꿔치기(1곳만).

    실제 T7 손상 재현: 제목 문단의 run이 본문 charPr(작은 pt)를 가리키게 됨.
    """
    m = re.search(r'(<' + NS + r':run charPrIDRef=")(\d+)(?="[^>]*><' + NS + r':t>[^<]*'
                  + re.escape(anchor_text.split()[0]) + r')', xml)
    assert m, f"anchor run not found for damage injection: {anchor_text!r}"
    return xml[:m.start(2)] + new_charpr_id + xml[m.end(2):]


def _damage_heading_merged(xml, anchor_text):
    """anchor_text를 담은 top-level 문단의 첫 run 앞에 이전 문단 텍스트가
    흡수된 것처럼 텍스트를 주입해 heading_merged(문단 텍스트는 있지만 문단
    시작이 anchor가 아님) 상태를 합성한다 — 실제 T7 병합 손상(이전 문단
    내용이 제목 문단에 흡수되어 앵커가 더 이상 문단 맨 앞이 아님)과 동일한
    관측 형태(check_headings의 at_start 판정 기준과 정확히 대응).

    문단 경계 자체를 지우는 대신(양쪽 다 빈 문단이면 병합해도 anchor가 여전히
    맨 앞이라 무의미) 앵커 문단의 첫 <hp:t> 내용 앞에 직접 문자열을 끼워
    넣는다 — top-level 판정은 tidy_hwpx._find_paragraphs()(표 셀 중첩 인지
    스택 스캐너) 재사용."""
    paras = tidy_hwpx._find_paragraphs(xml)
    target_idx = None
    for i, (_s, _e, p_xml) in enumerate(paras):
        if anchor_text in tidy_hwpx._para_text(p_xml):
            target_idx = i
            break
    assert target_idx is not None, f"anchor paragraph not found: {anchor_text!r}"
    p_start, p_end, p_xml = paras[target_idx]
    t_m = tidy_hwpx.T_RE.search(p_xml)
    assert t_m is not None, "anchor paragraph has no hp:t run"
    injected = p_xml[:t_m.start(1)] + "이전 내용 흡수됨" + p_xml[t_m.start(1):]
    return xml[:p_start] + injected + xml[p_end:]


@pytest.fixture()
def damaged_out(tmp_path):
    """out.hwpx를 tmp_path로 복사한 뒤 heading_pt(Ⅰ. 서 론) +
    heading_merged(V.  참고문헌) 손상을 합성 주입한 경로 반환."""
    dst = tmp_path / "damaged_out.hwpx"
    shutil.copyfile(OUT, dst)
    xml = _read(dst, "Contents/section0.xml")
    xml = _damage_heading_pt(xml, "Ⅰ. 서 론", "6")  # id=6 -> 10pt(charpr_hist에 존재)
    xml = _damage_heading_merged(xml, "V.  참고문헌")
    _write_section(dst, xml)
    return str(dst)


def test_heading_pt_mismatch_flagged(damaged_out):
    anomalies = style_diff.check_headings(FORM, damaged_out, ANCHORS)
    hp = [a for a in anomalies if a["kind"] == "heading_pt"]
    assert any(a["anchor"] == "Ⅰ. 서 론" for a in hp)
    a = next(a for a in hp if a["anchor"] == "Ⅰ. 서 론")
    assert a["form_pt"] == [16.0]
    assert a["out_pt"] == [10.0]


def test_heading_merged_flagged(damaged_out):
    anomalies = style_diff.check_headings(FORM, damaged_out, ANCHORS)
    merged = [a for a in anomalies if a["kind"] == "heading_merged"]
    assert any(a["anchor"] == "V.  참고문헌" for a in merged)


def test_both_damages_present(damaged_out):
    anomalies = style_diff.check_headings(FORM, damaged_out, ANCHORS)
    kinds = {a["kind"] for a in anomalies}
    assert kinds == {"heading_pt", "heading_merged"}


def test_undamaged_headings_clean(damaged_out):
    anomalies = style_diff.check_headings(FORM, damaged_out, ANCHORS)
    flagged_anchors = {a["anchor"] for a in anomalies}
    for a in ("II.  이론적 배경", "III.  탐구방법", "IV.  탐구결과"):
        assert a not in flagged_anchors


def test_pristine_form_vs_itself_is_clean():
    anomalies = style_diff.check_headings(FORM, FORM, ANCHORS)
    assert anomalies == []


def test_pristine_out_vs_form_is_clean():
    """손상 주입 전(현재 워크스페이스 out.hwpx)에는 anomaly가 없어야 한다 —
    회귀 시(향후 재발) 이 테스트가 먼저 깨져 원인을 구분해준다."""
    anomalies = style_diff.check_headings(FORM, OUT, ANCHORS)
    assert anomalies == []


def test_cli_exit_code(tmp_path, damaged_out):
    import json
    import subprocess

    anchors_path = tmp_path / "anchors.json"
    anchors_path.write_text(json.dumps(ANCHORS, ensure_ascii=False), encoding="utf-8")

    script = os.path.join(ROOT, "scripts", "style_diff.py")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, script, damaged_out, "--check-headings", str(anchors_path),
         "--baseline-form", FORM],
        capture_output=True, env=env,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is False
    assert len(payload["anomalies"]) == 2

    proc_clean = subprocess.run(
        [sys.executable, script, FORM, "--check-headings", str(anchors_path),
         "--baseline-form", FORM],
        capture_output=True, env=env,
    )
    assert proc_clean.returncode == 0
