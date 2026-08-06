#!/usr/bin/env python3
"""guards.py — 현장 교훈(T16/T18/T21/T22)을 재사용 가능한 가드 프리미티브로 고정.

kb/trouble-table.md 의 네 행을 엔진 수준 헬퍼로 인코딩한다. 전부 순수
파이썬/순수 XML — COM·한글 실행 없이 동작하고 테스트된다.

  - T16 pagedef_from_measurements : 인쇄면 실측 → 한컴 pagedef 값 변환
  - T18 is_protected_para         : 가이드텍스트 삭제에서 보호할 문단 판별
  - T22 charpr_id_present /
        assert_no_dangling_charpr : charPr id 가드·공중 참조 검출
  - T21 HwpInstanceLock           : 머신 단위 한글 COM 인스턴스 락

각 헬퍼의 docstring에 "가드 없던 시절의 실패(failing-before)"를 해당
T행 번호와 함께 기록한다 — 이 파일이 곧 회귀 방지 계약이다.
"""

import json
import math
import os
import re
import tempfile
import time

# tidy_hwpx.py 와 동일한 관용구: 네임스페이스 접두사는 hp:/hs: 등 가변이므로
# 로컬네임 기준으로 매칭한다.
NS = r'[A-Za-z0-9]+'


# ---------------------------------------------------------------------------
# T16 — 여백 산수: 인쇄면 실측 → 한컴 pagedef
# ---------------------------------------------------------------------------

def _round_mm(value):
    """mm 실측치를 정수 mm로 반올림(0.5는 항상 올림 — 파이썬 banker's rounding 회피)."""
    return int(math.floor(float(value) + 0.5))


def pagedef_from_measurements(body_top_mm, header_top_mm=None, *,
                              left_mm=None, right_mm=None, bottom_mm=None,
                              footer_mm=None, gutter_mm=None):
    """인쇄면에서 잰 위치(종이 위끝 기준 mm)를 한컴 pagedef 값으로 변환.

    T16 failing-before: 한글은 `본문 상단 = 위쪽 여백 + 머리말 높이`로 쌓는다.
    인쇄면에서 잰 본문 첫 행 위치(body_top_mm)를 그대로 '위쪽'에 넣으면
    머리말 높이만큼 이중 계산되어 본문이 의도보다 아래로 밀린다.

    올바른 산수(트러블테이블 T16): 실측 머리말 위치 → '위쪽', 머리말~본문
    간격 → '머리말'. 코퍼스 실측(머리말 14.6 / 본문 25.1)이면 위쪽 15 /
    머리말 10 이 된다.

    반올림 규약: 두 실측치를 각각 정수 mm로 먼저 반올림한 뒤 차를 취한다
    ('위쪽'+'머리말' == round(body_top_mm) 불변식이 유지되어 본문 시작
    위치가 실측과 1mm 이내로 일치).

    인자:
        body_top_mm   : 본문 첫 행의 실측 위치 (종이 위끝 기준 mm). 필수.
        header_top_mm : 머리말 첫 행의 실측 위치. None이면 머리말 없음
                        ('위쪽'=body_top, '머리말'=0).
        left_mm 등    : 스택 산수와 무관한 값들의 단순 패스스루(반올림만).

    반환: pyhwpx `hwp.set_pagedef()`에 바로 먹는 dict — 한글 키 + mm 단위
    (T15 행 참고: {'위쪽':…, '머리말':…, '왼쪽':…}).
    """
    body = _round_mm(body_top_mm)
    if header_top_mm is None:
        top, header = body, 0
    else:
        top = _round_mm(header_top_mm)
        header = body - top
        if header < 0:
            raise ValueError(
                f"body_top_mm({body_top_mm}) < header_top_mm({header_top_mm})"
                " — 본문이 머리말보다 위에 있을 수 없다")
    out = {"위쪽": top, "머리말": header}
    passthrough = {"왼쪽": left_mm, "오른쪽": right_mm, "아래쪽": bottom_mm,
                   "꼬리말": footer_mm, "제본여백": gutter_mm}
    for key, value in passthrough.items():
        if value is not None:
            out[key] = _round_mm(value)
    return out


# ---------------------------------------------------------------------------
# T18 — 보호 문단 판별 (가이드텍스트 삭제의 안전 울타리)
# ---------------------------------------------------------------------------

PROTECTED_TAG_RE = re.compile(r'<' + NS + r':(tbl|secPr|ctrl)\b')


def is_protected_para(para_xml):
    """charPr 색 기반 가이드텍스트 삭제에서 절대 지우면 안 되는 문단인지 판별.

    T18 failing-before: 2026 공식 양식 선처리에서 파란 charPr 문단을 XML
    삭제할 때 표(hp:tbl)·secPr·ctrl을 담은 문단을 보호하지 않으면 레이아웃이
    통째로 붕괴한다 — 실제 사고에서 21쪽 문서 + 20행 공백이 생겼다.

    보호 집합: 문단 조각 안에 <hp:tbl>, <hp:secPr>, <hp:ctrl> 중 하나라도
    있으면 True (접두사는 hp: 고정이 아니어도 매칭). 색이 파랗다는 이유만으로
    이런 문단을 지우면 표 전체·구역 정의·컨트롤(머리말 등)이 같이 날아간다.

    인자: para_xml — <hp:p>…</hp:p> 문단 XML 조각(문자열).
    반환: True면 삭제 금지.
    """
    return bool(PROTECTED_TAG_RE.search(para_xml))


# ---------------------------------------------------------------------------
# T22 — charPr id 가드 · 공중 참조(dangling ref) 검출
# ---------------------------------------------------------------------------

def charpr_id_present(header_xml, cpr_id):
    """header.xml에 charPr 정의 id가 실제로 존재하는지 — 요소 한정 정규식으로 판정.

    T22 failing-before: `'id="34"' not in header` 나이브 부분문자열 가드가
    paraPr id="34"에 오탐 → charPr 클론 추가 블록이 조용히 스킵 →
    section이 존재하지 않는 charPr(34/35)을 참조하는 공중 참조가 생겼다.
    검증도 같은 문자열 검사여서 통과로 오판했다.

    가드·검증 모두 반드시 이 요소 한정 형태를 쓴다:
        <hh:charPr\\b[^>]*\\bid="N"
    (접두사는 hh: 고정이 아니어도 매칭하되, charPr 요소의 id 속성만 본다.)
    """
    pattern = (r'<' + NS + r':charPr\b[^>]*\bid="'
               + re.escape(str(cpr_id)) + r'"')
    return bool(re.search(pattern, header_xml))


CHARPR_IDREF_RE = re.compile(r'\bcharPrIDRef="(\d+)"')


def dangling_charpr_refs(section_xml, header_xml):
    """section이 참조하는 charPrIDRef 중 header에 정의가 없는 id들(정렬 리스트).

    T22의 사고 형태(정의 없는 charPr 참조)를 결정론적으로 스캔한다.
    비었으면 공중 참조 없음.
    """
    used = set(CHARPR_IDREF_RE.findall(section_xml))
    return sorted((cid for cid in used
                   if not charpr_id_present(header_xml, cid)), key=int)


def assert_no_dangling_charpr(section_xml, header_xml):
    """section의 모든 charPrIDRef가 header에 정의돼 있음을 단언. 위반 시 AssertionError.

    T22 failing-before: 클론 스킵으로 생긴 공중 참조를 나이브 문자열 검증이
    통과로 오판 → Codex stop-gate에서야 적발. 조립 파이프라인은 저장 전
    이 단언을 통과해야 한다 (itemCnt 증가 여부는 별도 — 이 함수는 참조
    무결성만 본다).
    """
    dangling = dangling_charpr_refs(section_xml, header_xml)
    assert not dangling, (
        f"공중 charPr 참조 발견 (T22): section이 참조하나 header에 정의 없음"
        f" — id {dangling}")


# ---------------------------------------------------------------------------
# T21 — 머신 단위 한글 COM 인스턴스 락
# ---------------------------------------------------------------------------

def _pid_alive(pid):
    """pid의 프로세스가 살아있는지 — psutil 없이 stdlib만으로 판정.

    Windows: ctypes OpenProcess(QUERY_LIMITED) + GetExitCodeProcess(STILL_ACTIVE).
      주의: Windows의 os.kill(pid, 0)은 신호가 아니라 TerminateProcess를
      호출하므로(파괴적!) 절대 쓰지 않는다.
    POSIX: os.kill(pid, 0) — ProcessLookupError면 죽음, PermissionError면 살아있음.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        import ctypes.wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # 접근 거부 = 존재하지만 권한 없음(살아있음). 그 외(무효 pid 등)는 죽음.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True  # 핸들은 열렸는데 코드 조회 실패 — 보수적으로 살아있음 취급
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class HwpInstanceLock:
    """머신 단위 한글 COM 조립 락 — --kill-stale의 동시 세션 오사살을 막는 프리미티브.

    T21 failing-before: 같은 머신에서 두 세션이 동시에 COM 조립하면 각자의
    `--kill-stale`(taskkill /F /IM Hwp.exe)이 **상대 세션의 진행 중** Hwp
    인스턴스를 죽인다(kill은 이름 기준 전체) → RPC 오류(-2147023170/-2147023174)
    4연속 크래시. `Hwp(new=True)`로 인스턴스가 분리돼 있어도 소용없다.

    락 파일(%TEMP%/<name>, JSON): {"pid": …, "owner": …, "ts": …}.
    핵심 API는 `can_kill_stale()` — 살아있는 타 소유자의 락이 있으면
    (False, 이유)를 돌려 kill-stale을 거부하게 한다. 죽은 pid의 락(진짜
    좀비)만 stale로 간주한다. 판독 불가 락은 보수적으로 거부한다(오사살이
    락 고착보다 비싸다 — 수동 확인 후 파일 삭제).

    아직 com_backend --kill-stale에는 배선하지 않는다(후속 슬라이스) —
    여기서는 프리미티브와 회귀 테스트만 고정한다.
    """

    DEFAULT_NAME = "hwp-master-instance.lock"

    def __init__(self, lock_dir=None, name=None, self_pid=None):
        """self_pid는 테스트 주입용(기본 os.getpid())."""
        self.lock_dir = str(lock_dir) if lock_dir else tempfile.gettempdir()
        self.path = os.path.join(self.lock_dir, name or self.DEFAULT_NAME)
        self.self_pid = int(self_pid) if self_pid is not None else os.getpid()

    def read(self):
        """락 파일 내용(dict) 또는 None(없음). 판독 불가면 {"corrupt": True, …}."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {"corrupt": True, "path": self.path}
        if not isinstance(data, dict):
            return {"corrupt": True, "path": self.path}
        return data

    def can_kill_stale(self):
        """(허용여부, 이유). 살아있는 타 소유자 락이 있으면 (False, …) — T21 핵심 가드.

        True가 되는 경우: 락 없음 / 락이 우리 것 / 락 소유 pid가 죽어있음(진짜 stale).
        False: 살아있는 다른 pid가 락을 쥠, 또는 락 판독 불가(보수적 거부).
        """
        info = self.read()
        if info is None:
            return True, "락 없음 — kill-stale 허용"
        if info.get("corrupt"):
            return False, (f"락 파일 판독 불가({self.path}) — 소유자 확인 전"
                           " kill-stale 거부(수동 확인 후 삭제)")
        pid = info.get("pid")
        owner = info.get("owner", "?")
        if pid == self.self_pid:
            return True, f"락 소유자가 우리 자신(pid {pid}) — 허용"
        if _pid_alive(pid):
            return False, (f"살아있는 다른 세션(owner={owner}, pid={pid})이"
                           " 락 보유 — kill-stale 거부 (T21)")
        return True, f"stale 락(owner={owner}, pid={pid} 죽음) — 허용"

    def acquire(self, owner):
        """락 획득 시도. 성공 True / 살아있는 타 소유자가 있으면 False.

        죽은 pid의 stale 락은 덮어쓴다. 우리 자신이 이미 쥔 락은 재획득(갱신).
        판독 불가 락은 can_kill_stale과 같은 이유로 거부한다.
        """
        info = self.read()
        if info is not None:
            if info.get("corrupt"):
                return False
            pid = info.get("pid")
            if pid != self.self_pid and _pid_alive(pid):
                return False
        payload = {"pid": self.self_pid, "owner": str(owner),
                   "ts": time.time()}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        return True

    def release(self):
        """우리가 쥔 락만 해제(파일 삭제). 타 소유자 락은 건드리지 않는다.

        반환: 실제로 지웠으면 True.
        """
        info = self.read()
        if not info or info.get("corrupt"):
            return False
        if info.get("pid") != self.self_pid:
            return False
        try:
            os.remove(self.path)
        except FileNotFoundError:
            return False
        return True
