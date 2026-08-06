"""guards.py 회귀 테스트 — T16/T18/T21/T22 현장 교훈의 고정 계약.

전부 오프라인(순수 XML/순수 파이썬) — COM·한글 실행 없음.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import guards  # noqa: E402
from guards import (  # noqa: E402
    HwpInstanceLock,
    assert_no_dangling_charpr,
    charpr_id_present,
    dangling_charpr_refs,
    is_protected_para,
    pagedef_from_measurements,
)


# ---------------------------------------------------------------------------
# T16 — pagedef_from_measurements
# ---------------------------------------------------------------------------

class TestPagedefFromMeasurements:
    def test_corpus_case_t16(self):
        """코퍼스 실측: 머리말 14.6 / 본문 25.1 → 위쪽 15 / 머리말 10 (T16)."""
        pd = pagedef_from_measurements(25.1, header_top_mm=14.6)
        assert pd["위쪽"] == 15
        assert pd["머리말"] == 10

    def test_stack_invariant(self):
        """'위쪽'+'머리말' == round(body_top) — 이중 계산 없음이 곧 이 불변식."""
        pd = pagedef_from_measurements(25.1, header_top_mm=14.6)
        assert pd["위쪽"] + pd["머리말"] == 25

    def test_naive_double_count_would_differ(self):
        """failing-before 재현: 실측 본문 위치를 그대로 '위쪽'에 넣으면(나이브)
        스택 결과가 25+10=35mm — 헬퍼 결과(25mm)와 다르다."""
        pd = pagedef_from_measurements(25.1, header_top_mm=14.6)
        naive_top = 25  # round(25.1) 을 그대로 '위쪽'에
        assert naive_top + pd["머리말"] != pd["위쪽"] + pd["머리말"]

    def test_no_header(self):
        pd = pagedef_from_measurements(20.0)
        assert pd == {"위쪽": 20, "머리말": 0}

    def test_body_above_header_rejected(self):
        with pytest.raises(ValueError):
            pagedef_from_measurements(10.0, header_top_mm=14.6)

    def test_passthrough_keys(self):
        pd = pagedef_from_measurements(25.1, header_top_mm=14.6,
                                       left_mm=27.4, right_mm=20.0,
                                       bottom_mm=15.0, footer_mm=10.0,
                                       gutter_mm=0)
        assert pd["왼쪽"] == 27
        assert pd["오른쪽"] == 20
        assert pd["아래쪽"] == 15
        assert pd["꼬리말"] == 10
        assert pd["제본여백"] == 0

    def test_half_mm_rounds_up_not_bankers(self):
        """0.5mm는 항상 올림 — round(14.5)==14 같은 banker's rounding 배제."""
        pd = pagedef_from_measurements(25.5, header_top_mm=14.5)
        assert pd["위쪽"] == 15
        assert pd["머리말"] == 26 - 15


# ---------------------------------------------------------------------------
# T18 — is_protected_para
# ---------------------------------------------------------------------------

PARA_WITH_TBL = (
    '<hp:p id="1" paraPrIDRef="3"><hp:run charPrIDRef="7">'
    '<hp:tbl id="9" rowCnt="2" colCnt="2"><hp:tr><hp:tc>'
    '<hp:subList><hp:p><hp:run charPrIDRef="7"><hp:t>셀</hp:t></hp:run>'
    '</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')

PARA_WITH_SECPR = (
    '<hp:p id="0" paraPrIDRef="0"><hp:run charPrIDRef="0">'
    '<hp:secPr id="" textDirection="HORIZONTAL"><hp:pagePr landscape="WIDELY"'
    ' width="59528" height="84188"/></hp:secPr></hp:run></hp:p>')

PARA_WITH_CTRL = (
    '<hp:p id="2" paraPrIDRef="0"><hp:run charPrIDRef="0">'
    '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" colCount="1"/></hp:ctrl>'
    '</hp:run></hp:p>')

PARA_PLAIN_BLUE = (
    '<hp:p id="5" paraPrIDRef="3"><hp:run charPrIDRef="34">'
    '<hp:t>이곳에 탐구 동기를 기술합니다.</hp:t></hp:run></hp:p>')


class TestIsProtectedPara:
    def test_table_para_protected(self):
        assert is_protected_para(PARA_WITH_TBL) is True

    def test_secpr_para_protected(self):
        assert is_protected_para(PARA_WITH_SECPR) is True

    def test_ctrl_para_protected(self):
        assert is_protected_para(PARA_WITH_CTRL) is True

    def test_plain_colored_guide_text_not_protected(self):
        """파란 가이드텍스트 문단(표/secPr/ctrl 없음)은 삭제 대상이 맞다."""
        assert is_protected_para(PARA_PLAIN_BLUE) is False

    def test_lookalike_text_not_protected(self):
        """본문 텍스트에 'tbl' 'ctrl' 단어가 있어도 태그가 아니면 비보호."""
        para = ('<hp:p><hp:run charPrIDRef="1">'
                '<hp:t>ctrl 키와 tbl 약어와 secPr 낱말</hp:t></hp:run></hp:p>')
        assert is_protected_para(para) is False


# ---------------------------------------------------------------------------
# T22 — charpr_id_present / assert_no_dangling_charpr
# ---------------------------------------------------------------------------

HEADER_PARAPR_ONLY = (
    '<hh:head><hh:refList>'
    '<hh:charProperties itemCnt="2">'
    '<hh:charPr id="0" height="1000" textColor="#000000"/>'
    '<hh:charPr id="7" height="1000" textColor="#0000FF"/>'
    '</hh:charProperties>'
    '<hh:paraProperties itemCnt="1">'
    '<hh:paraPr id="34" tabPrIDRef="0"/>'
    '</hh:paraProperties>'
    '</hh:refList></hh:head>')

HEADER_WITH_CHARPR_34 = HEADER_PARAPR_ONLY.replace(
    '</hh:charProperties>',
    '<hh:charPr id="34" height="1000" textColor="#000000"/>'
    '</hh:charProperties>')


class TestCharprIdPresent:
    def test_parapr_id_does_not_false_match(self):
        """failing-before(T22): 나이브 'id=\"34\"' in header 는 paraPr id=34에
        오탐한다. 요소 한정 가드는 False가 정답."""
        assert 'id="34"' in HEADER_PARAPR_ONLY  # 나이브 검사는 통과해버림
        assert charpr_id_present(HEADER_PARAPR_ONLY, 34) is False

    def test_present_when_charpr_defined(self):
        assert charpr_id_present(HEADER_WITH_CHARPR_34, 34) is True

    def test_string_or_int_id(self):
        assert charpr_id_present(HEADER_WITH_CHARPR_34, "34") is True

    def test_partial_id_no_match(self):
        """id="3" 질의가 id="34" 정의에 부분 일치하면 안 된다."""
        assert charpr_id_present(HEADER_WITH_CHARPR_34, 3) is False


SECTION_CLEAN = (
    '<hs:sec><hp:p><hp:run charPrIDRef="0"><hp:t>본문</hp:t></hp:run>'
    '<hp:run charPrIDRef="7"><hp:t>링크</hp:t></hp:run></hp:p></hs:sec>')

SECTION_DANGLING = (
    '<hs:sec><hp:p><hp:run charPrIDRef="0"><hp:t>본문</hp:t></hp:run>'
    '<hp:run charPrIDRef="34"><hp:t>저자명</hp:t></hp:run>'
    '<hp:run charPrIDRef="35"><hp:t>소속</hp:t></hp:run></hp:p></hs:sec>')


class TestDanglingCharpr:
    def test_clean_section_passes(self):
        assert dangling_charpr_refs(SECTION_CLEAN, HEADER_PARAPR_ONLY) == []
        assert_no_dangling_charpr(SECTION_CLEAN, HEADER_PARAPR_ONLY)

    def test_synthetic_dangling_ref_detected(self):
        """failing-before(T22): 클론 스킵으로 section이 charPr 34/35를 참조하나
        header에 정의가 없다 — paraPr id=34가 있어도 속으면 안 된다."""
        assert dangling_charpr_refs(
            SECTION_DANGLING, HEADER_PARAPR_ONLY) == ["34", "35"]
        with pytest.raises(AssertionError, match="34"):
            assert_no_dangling_charpr(SECTION_DANGLING, HEADER_PARAPR_ONLY)

    def test_dangling_fixed_by_clone(self):
        """34만 정의 추가하면 35만 남는다 — 부분 수리도 정확히 추적."""
        assert dangling_charpr_refs(
            SECTION_DANGLING, HEADER_WITH_CHARPR_34) == ["35"]


# ---------------------------------------------------------------------------
# T21 — HwpInstanceLock
# ---------------------------------------------------------------------------

UNLIKELY_DEAD_PID = 999999  # Windows pid는 4의 배수 관행 + 범위 밖 → 죽은 pid


class TestPidAlive:
    def test_current_pid_alive(self):
        assert guards._pid_alive(os.getpid()) is True

    def test_unlikely_pid_dead(self):
        assert guards._pid_alive(UNLIKELY_DEAD_PID) is False

    def test_garbage_pid_dead(self):
        assert guards._pid_alive(None) is False
        assert guards._pid_alive(-1) is False
        assert guards._pid_alive("x") is False


class TestHwpInstanceLock:
    def _lock(self, tmp_path, self_pid=None):
        return HwpInstanceLock(lock_dir=tmp_path, name="test.lock",
                               self_pid=self_pid)

    def test_no_lock_allows_kill_stale(self, tmp_path):
        ok, reason = self._lock(tmp_path).can_kill_stale()
        assert ok is True
        assert "락 없음" in reason

    def test_dead_pid_lock_is_stale(self, tmp_path):
        holder = self._lock(tmp_path, self_pid=UNLIKELY_DEAD_PID)
        assert holder.acquire("crashed-session") is True
        ok, reason = self._lock(tmp_path).can_kill_stale()
        assert ok is True
        assert "stale" in reason

    def test_live_foreign_owner_refuses_kill_stale(self, tmp_path):
        """failing-before(T21): 살아있는 상대 세션의 Hwp를 --kill-stale이 이름
        기준으로 오사살 → RPC 크래시. 살아있는 타 pid 락이면 반드시 거부."""
        holder = self._lock(tmp_path, self_pid=os.getpid())  # 살아있는 pid
        assert holder.acquire("session-A") is True
        # 우리(가짜 self_pid)는 다른 세션인 척
        we = self._lock(tmp_path, self_pid=os.getpid() + 1)
        ok, reason = we.can_kill_stale()
        assert ok is False
        assert str(os.getpid()) in reason
        assert "session-A" in reason

    def test_own_lock_allows(self, tmp_path):
        lock = self._lock(tmp_path)
        assert lock.acquire("me") is True
        ok, reason = lock.can_kill_stale()
        assert ok is True
        assert "우리 자신" in reason

    def test_acquire_refused_by_live_foreign_owner(self, tmp_path):
        holder = self._lock(tmp_path, self_pid=os.getpid())
        assert holder.acquire("session-A") is True
        we = self._lock(tmp_path, self_pid=os.getpid() + 1)
        assert we.acquire("session-B") is False
        # 락 내용은 원소유자 그대로
        assert we.read()["owner"] == "session-A"

    def test_acquire_overwrites_stale_lock(self, tmp_path):
        dead = self._lock(tmp_path, self_pid=UNLIKELY_DEAD_PID)
        assert dead.acquire("crashed") is True
        live = self._lock(tmp_path)
        assert live.acquire("fresh") is True
        info = live.read()
        assert info["owner"] == "fresh"
        assert info["pid"] == os.getpid()

    def test_release_only_own_lock(self, tmp_path):
        holder = self._lock(tmp_path, self_pid=os.getpid())
        holder.acquire("session-A")
        we = self._lock(tmp_path, self_pid=os.getpid() + 1)
        assert we.release() is False          # 타 소유자 락은 안 지움
        assert os.path.exists(holder.path)
        assert holder.release() is True       # 본인 락은 지움
        assert not os.path.exists(holder.path)
        assert holder.release() is False      # 이미 없음

    def test_corrupt_lock_refuses_conservatively(self, tmp_path):
        lock = self._lock(tmp_path)
        Path(lock.path).write_text("{not json", encoding="utf-8")
        ok, reason = lock.can_kill_stale()
        assert ok is False
        assert "판독 불가" in reason
        assert lock.acquire("me") is False
