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
4. **레이아웃 QA (수치 게이트 → 시각 이중 게이트)** — 빈 문단(엔터) 잔재로 인한
   과다 공백을 미적 판단이 아니라 수치로 가린다.
   - 수치 게이트: `python scripts/layout_qa.py --file verify.pdf` → 페이지별 하단 공백
     비율·블록 간 최대 간격(본문 줄높이 배수)을 JSON으로. 기본 임계 하단 ≤25%(마지막
     쪽 제외)·간격 ≤3줄. 간격은 '빈 문단 구멍'만 잡도록 그림이 점유한 세로 구간은
     제외(그림은 PNG 여백·도형으로 본질적 공간 차지). 임계는 인자로만 바꾼다.
   - 보정: 연속 빈 문단은 `collapse_empty_paragraphs`(^n^n^n→^n^n, 1빈줄은 보존).
     그림 캡션↔이미지 밀착은 `delete_blank_after`(캡션 앵커), 객체 앞 빈 문단은
     `delete_blank_before`(뒤 캡션 앵커). **과압축 금지** — 표·그림 앞뒤 1빈줄과 항목
     사이 구분 공백은 정상.
   - 시각 게이트: 수치 통과 후 `fitz`로 전 페이지 PNG 렌더해 직접 확인(헤딩 아래 간격,
     그림-캡션 밀착, 고아줄/반쪽 빈 페이지). 수치 통과인데 어색하면 근거와 함께 보고.
5. 문제 발견 시: 원본은 그대로이므로 ops를 수정해 재실행 (Ratchet — 통과 전까지 저장본 교체 금지).

### 인라인 객체 원칙 (큰 객체는 자기 문단)
- **그림·display 수식은 본문 문단에 끼우지 말고 자기 문단(가운데 정렬)에 단독으로 둔다.**
  고립 텍스트(캡션 줄이 그림 옆에 낌)·수식 줄 걸림·자간 과도 확장은 거의 전부 인라인
  객체 위반에서 나온다.
- 그림: `insert_picture`는 `own_paragraph`(기본 true)면 캡션 끝에서 새 문단을 만들고
  그림만 넣은 뒤 가운데 정렬한다. 호출 전 커서를 캡션 문단 끝(`goto_text` 캡션)에 둘 것.
- 수식: `insert_equation`에 `display: true`면 lead-in 문장 끝(커서)에서 새 문단을 만들고
  수식만 넣어 가운데 정렬. 인라인 수식은 짧은 것만.
- 정렬: `set_para_align`(align: justify/center/left/right). 본문은 `justify`(all),
  제목·그림·수식 문단은 `center`, URL/참고문헌 줄은 `left`(양쪽정렬 시 URL 자간이 벌어짐).
  순서 주의 — `all:justify`를 먼저 적용한 뒤 그림/수식을 삽입해야 self-center가 살아남는다.
- 참고문헌은 "저자·제목 줄 + URL 단독 줄"로 쪼개고 left 정렬.

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

### report bundle 조립 (build_report.py)
- report-pipeline의 Stage 4 출력(`bundle/content.md`)을 받아 ops JSON을 **결정론적으로**
  만든다. 형식 명세는 `report-pipeline/references/bundle_spec.md`를 **엄수**(SECTION 앵커,
  `[[EQ]]`/`[[FIG]]`/`[[TABLE]]` 태그, YAML 메타).
- 사용:
  ```bash
  python scripts/build_report.py --content bundle/content.md --form 양식.hwp > ops.json
  python scripts/com_backend.py edit --file 양식.hwp --ops ops.json \
      --save-as 최종.hwpx --export-pdf verify.pdf
  ```
  `--dry-run`은 한글 미실행, ops만 출력(단위 테스트). `--form`은 inspect로 SECTION 앵커를
  양식 항목 제목과 대조하고 **하나라도 불일치하면 중단**(우회 금지 — content.md를 고친다).
- 생성 규칙: 수식=`insert_equation`(display 기본, latex는 eqn.py+sanity), 그림=
  `insert_picture`(own_paragraph+width_mm), 표=`insert_table`(plain). 인라인 객체 원칙과
  동일. 조립 후 검증은 위의 레이아웃 QA + 시각 이중 게이트 그대로 적용.
- **v0.3.0 메타/동작**(bundle_spec 참고): `base_pt`(기본 10, 본문·수식·캡션·URL에 글자크기
  강제+검정 — 제목 서식 상속 안 함), `binding: book|submit`(submit=좌우대칭 여백),
  `abstract: true|false`(false=초록 표 제거). URL 단독 줄/`[[URL]]`은 링크 필드(파랑·밑줄).
  제목 앞 빈 문단 1개 자동 보장(`insert_blank_before`, 멱등). `com_backend edit --ops`는
  build_report의 {ok,...,ops} 래퍼를 그대로 받는다.
- 조립 후 **charPr 수치 검증**(.hwpx unzip → `<hh:charPr height/textColor>`): 본문·수식 =
  base_pt·검정, URL = base_pt·#0000FF·밑줄, 제목 = 양식 원본 크기.
- 회귀 픽스처: `tests/fixtures/regen-brake/`(회생제동 보고서를 bundle로 역변환). dry-run
  ops 개수(섹션·EQ·FIG·TABLE)와 앵커가 기준과 일치해야 한다.

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
| 그림이 지정 크기 무시·거대(native)로 삽입 | pyhwpx `insert_picture`의 width/height 단위는 **mm**(HwpUnit 아님). v0.1.2에서 mm 직접 전달로 수정. 구버전은 MiliToHwpUnit 변환 탓에 무시됐음 |
| 헤딩 아래·그림 주변 과다 공백 | 빈 문단(엔터) 잔재. `layout_qa.py`로 수치 측정 → `collapse_empty_paragraphs`+`delete_blank_after/before`로 보정. 1빈줄은 보존(과압축 금지) |
| layout_qa가 그림 페이지를 오탐 | 간격 지표는 그림이 점유한 세로 구간을 제외(v0.1.2). 그래도 뜨면 진짜 빈 문단 구멍 |
| 삽입 본문이 파란색(또는 안내문 색) | 색 안내문 위치 상속. `set_char_color`로 일괄 검정. PDF에서 색 글자 0 확인 |
| 표에 숫자 헤더·인덱스 열 오염 | DataFrame 경유 삽입. 순수 2D 리스트로 `insert_table`(plain). 기존 표는 `delete_ctrls`(tbl) 후 재삽입 |
| 콤마 든 문구가 일부만 지워짐(콤마 잔존) | `replace_all`이 콤마로 분리. `find_delete` 사용 |
| 수식이 깨져 보임 | HwpEqn 문법 오류. eqn.py 단독 실행으로 warnings 확인 후 hwpeqn 직접 작성 |
| 저장 후 한글에서 "복구" 경고 | XML 백엔드에서 DOM 재직렬화를 했을 가능성 — 바이트 보존 경로만 사용 |
| COM이 응답 없음 | 작업관리자에서 Hwp.exe 잔존 프로세스 종료 후 재시도 |
| 수식이 `\frac`·`≤ ft`처럼 raw로 렌더 | bundle latex 속성이 이중 백슬래시(`\\frac`). eqn.py가 v0.2.1부터 정규화하지만 content.md는 단일 백슬래시 권장 |
| 섹션 본문이 마지막 섹션(Ⅵ 참고문헌) 뒤로 밀림 | 옛 insert_table이 MoveDocEnd로 커서를 문서 끝으로 보냄. v0.2.1에서 표 바로 뒤로 복귀하도록 수정 |
| 제목과 본문이 한 줄에 붙음("Ⅵ.참고문헌David…") | build_report가 goto 후 본문을 같은 문단에 삽입. v0.2.1에서 제목 뒤 새 문단 분리 |
| 캡션이 그림과 떨어져 페이지가 갈림 | 객체 op의 leading `\r\n`이 캡션과 객체 사이 빈 문단을 만듦. v0.2.1에서 문단 맨 앞이면 생략(`_para_offset`) |
| set_char_color로 검정 적용이 무효 | set_font(TextColor=0)이 falsy 0을 스킵. v0.2.1에서 HParameterSet 경로로 항상 적용. 단 표지 셀 내부는 SelectAll이 못 잡아 문단 표적 처리 필요 |
| 삽입 본문이 제목 글자크기(15pt 등)를 상속 | v0.3.0: `insert_text`에 `pt` 주면 insert-then-select로 글자크기 강제(+검정). pending CharShape는 한 입력 밀려 불가. build_report가 base_pt(기본10)를 자동 부여 |
| 삽입 본문이 빨간색(안내문 자리 상속) | next_para 삽입이 빨간 안내문 문단 색을 상속. v0.3.0: pt 스탬프가 글자색도 검정으로 못박음 |
| 제목 글자크기가 본문값으로 바뀜 | `collapse_empty_paragraphs`(find_replace_all)·`insert_text("\r\n")`가 인접 제목 charPr를 갈아끼움. v0.3.0: 제목 분리는 `goto_text next_para`(제목 문단 안 쪼갬)+`insert_blank_before`(BreakPara, pending 미사용)로. collapse 자동삽입 중단 |
| 첫 섹션(I) 제목만 크기 축소(15→12 등) | 양식 첫 제목이 12pt 영역(초록표/머리말)과 인접. delete_ctrls·빈문단 삽입 시 HWP가 인접 12pt를 제목에 번지게 함. 이 pyhwpx는 기존 런 글자크기 재설정이 불가(get/set 모두 1500 반환)해 복원 불가 — 알려진 한계(제목 여전히 본문보다 큼) |
| 제출본인데 홀짝 여백이 미러링(제본용) | bundle `binding: submit` → `page_binding` op. 좌우=(좌+우+제본)/2, 제본=0. 인쇄폭 유지하며 좌우대칭 |
| 참고문헌 URL이 일반 텍스트(링크 아님) | 한글 '스페이스→자동링크'는 COM 미동작. v0.3.0 `insert_hyperlink`(텍스트 타이핑→선택→필드+파랑·밑줄). description="" 주면 글자 안 보이니 표시문구 필수 |
| 초록을 빼고 싶다 | bundle `abstract: false` → `delete_ctrls`(tbl, abstract_table_index 기본1=초록표). content.md에서 초록 섹션 제거 |

## 5. 참고 문서
- `references/hwpeqn_cheatsheet.md` — 한글 수식 스크립트 문법 전체
- `references/com_api_reference.md` — pyhwpx/HAction 패턴 모음
- `INSTALL.md` — Claude Code / Codex / Cowork / claude.ai 배포 방법
