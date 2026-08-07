"""W6.2 guide-text detector generalization — pattern classes, not per-file strings.

XC-1 (docs/research/xc1-conversion-bench.md §3) found guide_text = 0 on 4/12
corpus forms. Diagnosis showed the marks are structural conventions, all
black-colored (so the colored-run heuristic never fires):

  - note-prefix symbols  : ※ ☞ ◁ ▷ ＊ * 주N)   (moel-2025, both PPS forms)
  - inline example marks : "ㅇ (예시①) …"        (moel-2025)
  - polite imperatives   : "…하십시오/주십시오"    (pps-jeongbogonggae)
  - instructional 기재    : "…만 기재", "명확히 기재(…)" (moel-2013/2025)

Every pattern has (a) a motivating corpus hit (exact string from the corpus
file) and (b) a still-catches negative (report body prose that must NOT be
flagged). admrul-gajokdolbom-hyuga-sinchengseo is a documented BOUND, not a
pattern target: its only guide-like content is fill-target checkboxes and a
○○○ signature placeholder — deleting either would break the form, so the
correct guide_text count is 0 (locked below).
"""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402

CORPUS = os.path.join(os.path.dirname(ROOT), "tests", "corpus", "forms")


def classify(text):
    return form_inspect._classify_guide(text, colored=False)


# ---------------------------------------------------------------------------
# (a) motivating corpus hits — exact strings from the 4 formerly-missed files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # moel-pyojun-geunrogyeyakseo-2025 (hr): ※-prefixed 참고 notes
    "※ (참고) 적용(가입) 예외에 해당하는 경우에는 예외 사항 및 사유를 기재"
    "(예외 사유 해당 여부는 근로복지공단, 국민연금공단, 국민건강보험공단 누리집 참조)",
    "※ 주의사항",
    # moel-2025: ◁◁ … ▷▷ wrapper line
    "◁◁ 단시간근로자의 경우 “근로일 및 근로일별 근로시간”을 반드시 기재하여야 합니다.  "
    "다양한 사례가 있을 수 있어, 몇 가지 유형을 예시하오니 참고하시기 바랍니다. ▷▷",
    # pps-jeongbogonggae-donguiseo (grant): ※ / ☞ note lines
    "※ 위의 개인정보 수집ㆍ이용에 대한 동의를 거부할 권리가 있습니다. 그러나 동의를 "
    "거부할 경우 원활한 우수제품심사를 할 수 없어 공정조달시스템 이용이 제한됩니다.",
    "☞ 위와 같이 개인정보를 수집ㆍ이용하는데 동의하십니까? (예,  아니오)",
    # pps-hyeopeop-seungin-sinchengseo (grant): the single * footnote
    "* 본 협업승인 신청서는 1차 심사 통과기업에 한해 제출",
])
def test_note_prefix_hits(text):
    assert classify(text) == "note_prefix"


def test_example_mark_hit_moel2025():
    # moel-2025: example marker mid-line (not at paragraph start, so the old
    # startswith("(예") prefix check could never fire).
    assert classify("ㅇ (예시①) 주5일, 일 6시간(근로일별 근로시간 같음)") == "example"


def test_instruction_polite_imperative_hit_pps2():
    # pps-jeongbogonggae-donguiseo: instruction verb to the filler.
    assert classify(
        "조달청은 우수제품 심사를 위하여 아래와 같이 개인정보를 수집ㆍ이용 및 "
        "제3자에게 제공하고자 합니다.  내용을 자세히 읽으신 후 동의 여부를 "
        "결정하여 주십시오.") == "instruction"


def test_instruction_gijae_hit():
    # nrf front-matter cell text (also caught as colored in situ; the bare
    # classifier must catch the instructional 기재 form on its own).
    assert classify("과제번호반드시 기재") == "instruction"


# ---------------------------------------------------------------------------
# (b) still-catches negatives — report body prose must NOT be flagged
#     (snippets modeled on report-corpus content.md body style: 평서체,
#      실험/분석 서술. None of these may classify as guide text.)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # plain experimental prose
    "본 실험에서는 진자의 길이를 10 cm 간격으로 바꾸어 가며 주기를 측정하였다.",
    "ENSO 지수와 수온 편차의 상관을 분석하고 회귀 직선을 구하였다.",
    # 기재된/기재되어 (descriptive, not instructional) must not fire
    "논문에 기재된 표준 조건을 그대로 따라 시료를 준비하였다.",
    "선행 연구에 기재되어 있는 값과 비교하면 오차는 3 % 이내였다.",
    # 주요/주기 etc. must not be mistaken for a 주N) note prefix
    "주요 결과는 표 3에 정리하였다.",
    "주기가 길어질수록 감쇠가 뚜렷하게 나타났다.",
    # parenthetical starting with 예- that is NOT an example marker
    "실험 결과는 예상과 달리 온도가 상승하는 경향을 보였다(예상 오차 범위 밖).",
    # asterisk mid-sentence (statistics convention), not a note prefix
    "유의수준은 p<0.05(*)로 표시하였다.",
])
def test_still_catches_body_prose_not_flagged(text):
    assert classify(text) is None


# ---------------------------------------------------------------------------
# corpus integration — regression floors on the actual corpus files
# (files are sha256-pinned repo members; skip only if a checkout drops them)
# ---------------------------------------------------------------------------

def _corpus(path):
    full = os.path.join(CORPUS, path)
    if not os.path.exists(full):
        pytest.skip(f"corpus member missing: {path}")
    return full


@pytest.mark.parametrize("rel,floor", [
    ("grant/pps-hyeopeop-seungin-sinchengseo.hwpx", 1),
    ("grant/pps-jeongbogonggae-donguiseo.hwpx", 5),
    ("converted/moel-pyojun-geunrogyeyakseo-2025.hwpx", 16),
    ("converted/moel-pyojun-geunrogyeyakseo-2013.hwpx", 22),
])
def test_formerly_missed_forms_now_hit(rel, floor):
    profile, _ = form_inspect.analyze(_corpus(rel), want_baseline=False)
    assert len(profile["guide_text"]) >= floor, (
        f"guide_text regression on {rel}: "
        f"{len(profile['guide_text'])} < floor {floor}")


def test_admrul_bound_locked_at_zero():
    """Documented capability BOUND (xc1-conversion-bench §3, forms.md):
    admrul-gajokdolbom-hyuga-sinchengseo contains no removable guide text —
    only field labels, checkbox fill-targets ("[  ]가족돌봄 휴직") and the
    ○○○ signature placeholder, all of which must survive assembly. If this
    starts reporting hits, a pattern has over-generalized into form content."""
    profile, _ = form_inspect.analyze(
        _corpus("converted/admrul-gajokdolbom-hyuga-sinchengseo.hwpx"),
        want_baseline=False)
    assert len(profile["guide_text"]) == 0
