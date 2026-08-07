# -*- coding: utf-8 -*-
"""set_cell 실사격(COM) 검증 — 한컴이 설치된 기계에서 명시적으로만 돈다.

기본은 skip. 켜는 법(운영자 기계에서, 직렬로):

    RIGORLOOM_LIVE_COM=1 python -m pytest engine/tests/test_com_backend_live_cell.py

왜 기본 skip인가: CI(ubuntu/windows 러너)에 한컴이 없고, 있더라도 COM은
프로세스 전역 자원이라 병렬 테스트와 공존할 수 없다(T21 — 동시 세션이 서로를
죽인다). 이 파일은 **직렬**로만 돌고 `--kill-stale`을 절대 쓰지 않는다.

무엇을 증명하나 — 오프라인 단위 테스트(test_com_backend_offline.py)가 고정한
주소 변환이 실제 한컴 좌표계와 일치한다는 것: 양식의 빈 셀 cellAddr에 쓰면
그 셀에 들어가고, 라벨 셀은 expect_empty 가드가 막는다(T28).
실사격 확인(2026-08-08, PPS 협업승인신청서): cellAddr (2,3) 도달에
`steps=4`, 진입 주소 `A1` — 오프라인 모형의 예상 걸음 수와 일치했다.

관측된 잡음(T28): 한 파이썬 프로세스에서 Hwp()를 두 번째로 만들 때
`Windows fatal exception: code 0x80010105`(RPC_E_SERVERFAULT) 스택 덤프가
찍힌다. 테스트는 통과하지만, 이것이 '세션 하나에 셀 하나'를 권하는 이유의
일부다 — 한 프로세스가 COM 세션을 갈아끼우는 것 자체가 불안정하다.
"""
import os
import shutil
import sys
import zipfile

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import com_backend  # noqa: E402
from hwpx_tables import scan_tables  # noqa: E402

PPS_FORM = os.path.join(
    os.path.dirname(ROOT), "tests", "corpus", "forms", "grant",
    "pps-hyeopeop-seungin-sinchengseo.hwpx")

LIVE = os.environ.get("RIGORLOOM_LIVE_COM") == "1"


def _cell_text(path, table_index, addr):
    import re
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist()
                       if re.fullmatch(r"Contents/section\d+\.xml", n))
        index = 0
        for name in names:
            xml = z.read(name).decode("utf-8")
            for table in scan_tables(xml):
                if index == table_index:
                    for cell in table["cells"]:
                        if cell["addr"] == addr:
                            body = xml[cell["body_start"]:cell["body_end"]]
                            return re.sub(r"<[^>]+>", "", "".join(
                                re.findall(r"<hp:t\b[^>]*>(.*?)</hp:t>",
                                           body, re.S))).strip()
                    raise AssertionError(f"cellAddr {addr} 없음")
                index += 1
    raise AssertionError(f"표 {table_index} 없음")


pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="live Hancom COM test — set RIGORLOOM_LIVE_COM=1 on an operator "
           "machine with Hancom installed (serial only, never --kill-stale)")


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus form absent")
def test_live_set_cell_writes_the_addressed_cell(tmp_path):
    """cellAddr (2,3)에 쓰면 (2,3)에 들어간다 — 라벨 셀 (2,6)은 그대로."""
    src = tmp_path / "form.hwpx"
    shutil.copy2(PPS_FORM, src)
    out = tmp_path / "out.hwpx"
    hwp = com_backend.open_hwp(str(src))
    try:
        result = com_backend.op_set_cell(hwp, {
            "op": "set_cell", "table": 0, "addr": [2, 3],
            "text": "주식회사 리고룸", "expect_empty": True})
        hwp.save_as(str(out))
    finally:
        try:
            hwp.quit()
        except Exception:
            pass
    assert result["cell"] == [0, [2, 3]]
    assert _cell_text(out, 0, (2, 3)) == "주식회사 리고룸"
    assert _cell_text(out, 0, (2, 6)) == "법인등록번호"   # 라벨 셀 불변


@pytest.mark.skipif(not os.path.exists(PPS_FORM), reason="corpus form absent")
def test_live_expect_empty_refuses_the_label_cell(tmp_path):
    src = tmp_path / "form.hwpx"
    shutil.copy2(PPS_FORM, src)
    hwp = com_backend.open_hwp(str(src))
    try:
        with pytest.raises(RuntimeError, match="비어 있지 않음"):
            com_backend.op_set_cell(hwp, {
                "op": "set_cell", "table": 0, "addr": [2, 6],
                "text": "파괴", "expect_empty": True})
    finally:
        try:
            hwp.quit()
        except Exception:
            pass
