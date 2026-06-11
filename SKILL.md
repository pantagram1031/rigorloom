---
name: hwp-master
description: "**HWP/HWPX 통합 편집기 (듀얼 백엔드)**: 한글(Hancom) 문서를 사람처럼 편집한다. Windows에서는 pyhwpx COM 자동화로 한컴오피스를 직접 구동(양식 완전 보존, 수식·표·그림 네이티브 삽입, PDF 검증 루프), 리눅스/샌드박스에서는 기존 hwpx 스킬의 바이트 보존 XML 편집으로 폴백. LaTeX→한글 수식(HwpEqn) 자동 변환 내장. Claude Code·Codex·Cowork 공용.\n  - MANDATORY TRIGGERS: HWP, HWPX, .hwp, .hwpx, 한글, 한글파일, 한컴, Hancom, 수식 삽입, 한글 편집, 한글 자동화, pyhwpx"
---

# HWP Master — 듀얼 백엔드 한글 문서 편집

## 0. 백엔드 선택 (반드시 먼저 판단)

```
질문 1: 지금 Windows이고 한컴오피스가 설치되어 있는가?
  ├─ YES → [COM 백엔드] scripts/com_backend.py  ← 기본 선택
  │         (기존 양식 자동 보존, 수식/그림/표 네이티브, .hwp도 직접 편집 가능)
  └─ NO (리눅스/claude.ai 샌드박스/macOS)
       ├─ 파일이 .hwpx → [XML 백엔드] 기존 hwpx 스킬 (modify_hwpx.py / generate_hwpx.py)
       └─ 파일이 .hwp  → 편집 불가. 사용자에게 .hwpx로 다시 저장해 달라고 요청하거나,
                          Windows 환경(Claude Code/Codex 로컬)에서 convert 후 진행.
```

확인 방법: `python -c "import sys; print(sys.platform)"` → `win32`이고
`pip show pyhwpx`가 성공하면 COM 가능. pyhwpx 미설치 시:
`pip install pyhwpx pywin32` (한글 2022 + Python 3.11/3.12 권장).

## 1. COM 백엔드 워크플로우 (Windows)

**철칙: 원본을 직접 덮어쓰지 않는다. 항상 `--save-as`로 새 파일에 저장.**

### Step 1 — 구조 파악 (토큰 절약: 전체 본문을 절대 덤프하지 말 것)
```bash
python SKILL_DIR/scripts/com_backend.py inspect --file 보고서.hwp
```
→ 본문 미리보기, 필드(누름틀) 목록, 표/수식/그림 개수, 기존 수식 스크립트, 쪽수가
JSON으로 나온다. 이걸 기반으로 편집 계획을 세운다.

### Step 2 — ops JSON 작성 후 배치 편집
```bash
python SKILL_DIR/scripts/com_backend.py edit \
  --file 보고서.hwp --ops ops.json \
  --save-as 보고서_v2.hwpx --export-pdf verify.pdf
```

ops 예시 (위에서 아래로 순차 실행):
```json
[
  {"op": "put_field", "name": "작성자", "value": "홍길동"},
  {"op": "replace_all", "find": "{{날짜}}", "replace": "2026.06.11."},
  {"op": "goto_text", "text": "3. 실험 결과"},
  {"op": "move", "to": "line_end"},
  {"op": "insert_text", "text": "\r\n측정된 음압 레벨은 다음 식으로 계산하였다.\r\n"},
  {"op": "insert_equation", "latex": "L_p = 10 \\log \\frac{p^2}{p_0^2}", "base_pt": 11},
  {"op": "insert_table", "data": [["주파수(Hz)","측정값(dB)"],["500","42.1"],["1000","38.7"]]},
  {"op": "insert_picture", "path": "C:/work/그래프.png", "width_mm": 100}
]
```

### Step 3 — 검증 루프 (필수, 매 편집 후)
1. `edit` 출력의 `post_inspect`로 표/수식 개수가 의도대로 늘었는지 확인.
2. `verify.pdf`를 **직접 열어 시각 확인** (레이아웃 깨짐, 수식 렌더링, 표 정렬).
3. **글자색 상속 확인** — 파란/색 안내문 자리에 삽입한 본문은 그 색을 상속한다.
   PDF에서 의도치 않은 색 글자가 있으면 `set_char_color`(기본 all=true)로 일괄 검정 처리.
   `set_font(TextColor=...)` 경유라 크기·굵기 등 다른 속성은 불변.
4. 문제 발견 시: 원본은 그대로이므로 ops를 수정해 재실행 (Ratchet — 통과 전까지 저장본 교체 금지).

### 표·그림·문구 삭제 / 색
- 표는 항상 **순수 2차원 리스트**로 `insert_table`(plain 기본). pandas DataFrame을 넘기면
  숫자 헤더 행 + 인덱스 열(0,1,2…)이 셀에 박힌다. 인덱스 열 절대 금지.
- 그림은 `width_mm`만 줘도 원본 종횡비로 높이 자동(PIL→PNG 헤더 폴백).
- 콤마가 든 문구 삭제는 `find_delete`(find 기반, 분리 없음). `replace_all`은 FindString을
  콤마로 분리하므로 콤마 든 문구엔 쓰지 말 것.
- 표/그림만 지우고 캡션은 남기려면 `delete_ctrls`(types: tbl/gso) 후 캡션 앵커로 재삽입.

### 수식 (한글 수식 편집기 형식)
- `insert_equation`에 `latex`를 주면 내장 변환기(`scripts/eqn.py`)가 HwpEqn 스크립트로
  변환해 `EquationCreate` 액션으로 삽입한다. 글꼴은 기본 HancomEQN.
- 변환이 의심스러우면 먼저 단독 실행으로 확인:
  `python SKILL_DIR/scripts/eqn.py "\frac{1}{2}mv^2"` → warnings 비어 있는지 확인.
- 복잡한 수식은 `hwpeqn` 키로 스크립트를 직접 줄 것 (문법: references/hwpeqn_cheatsheet.md).
- 기존 수식 수정은 `edit_equation` + `index` (inspect 출력의 equations 배열 인덱스).

### 양식 보존 원칙 (COM)
- 텍스트는 가능하면 **필드(누름틀) 채우기(`put_field`)** > `replace_all` > 커서 삽입 순으로 선호.
- 새 문단 삽입 시 커서를 같은 스타일의 문단 끝에 두고 `insert_text` — 직전 문단 모양을 상속한다.
- 쪽 설정/스타일 정의는 절대 건드리지 않는다 (편집은 본문 내용에 한정).

## 2. XML 백엔드 워크플로우 (한컴 없는 환경)

기존 `hwpx` 스킬을 그대로 사용한다 (이 스킬과 공존):
- 새 문서 생성: `hwpx/scripts/generate_hwpx.py` (이노베이션아카데미 양식)
- 기존 .hwpx 편집: `hwpx/scripts/modify_hwpx.py` — **바이트 보존 원칙** 유지
  (etree.tostring 금지, 원본 바이트에 문자열 수술)
- 수식: HwpEqn 스크립트 텍스트가 필요하면 이 스킬의 `scripts/eqn.py`로 변환한 뒤
  XML의 수식 노드에 삽입. 단, 픽셀 퍼펙트가 필요하면 Windows COM으로 마무리할 것.
- 검증: 수정 후 `read_hwpx.py`로 구조 재독 + 가능하면 한컴독스/한글에서 열어 확인 요청.

## 3. 흔한 실수 (하지 말 것)

- ❌ inspect 없이 바로 편집 — 앵커 문구가 없으면 goto_text가 실패한다.
- ❌ 전체 본문 텍스트를 컨텍스트에 덤프 — `text_preview`와 컨트롤 요약만 사용.
- ❌ PDF 시각 검증 생략 — 수식 BaseUnit이 본문 글자 크기와 안 맞는 경우가 흔하다
  (본문 10pt면 `base_pt: 10~11`).
- ❌ .hwp를 XML 백엔드로 편집 시도 — XML 백엔드는 .hwpx 전용.
- ❌ 한글 창을 여러 개 띄운 채 실행 — 기존 한글 프로세스를 모두 닫고 시작.
- ❌ ops 한 번에 20개 이상 — 5~8개 단위로 끊고 매 단위마다 검증.

## 4. 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| 보안 승인 팝업에서 멈춤 | pyhwpx가 자동 등록하지만, 구버전 한글이면 한컴 보안모듈(FilePathCheckerModule) 수동 등록 필요 |
| `insert_picture` TypeError | pyhwpx 버전 차이 — 백엔드가 자동 폴백함. `pip install -U pyhwpx` 권장 |
| `insert_picture` ValueError (sizeoption=1 width/height) | 폭만 주면 pyhwpx가 둘 다 요구. v0.1.1부터 `width_mm`만 줘도 종횡비로 높이 자동 계산 |
| 삽입 본문이 파란색(또는 안내문 색) | 색 안내문 위치 상속. `set_char_color`로 일괄 검정. PDF에서 색 글자 0 확인 |
| 표에 숫자 헤더·인덱스 열 오염 | DataFrame 경유 삽입. 순수 2D 리스트로 `insert_table`(plain). 기존 표는 `delete_ctrls`(tbl) 후 재삽입 |
| 콤마 든 문구가 일부만 지워짐(콤마 잔존) | `replace_all`이 콤마로 분리. `find_delete` 사용 |
| 수식이 깨져 보임 | HwpEqn 문법 오류. eqn.py 단독 실행으로 warnings 확인 후 hwpeqn 직접 작성 |
| 저장 후 한글에서 "복구" 경고 | XML 백엔드에서 DOM 재직렬화를 했을 가능성 — 바이트 보존 경로만 사용 |
| COM이 응답 없음 | 작업관리자에서 Hwp.exe 잔존 프로세스 종료 후 재시도 |

## 5. 참고 문서
- `references/hwpeqn_cheatsheet.md` — 한글 수식 스크립트 문법 전체
- `references/com_api_reference.md` — pyhwpx/HAction 패턴 모음
- `INSTALL.md` — Claude Code / Codex / Cowork / claude.ai 배포 방법
