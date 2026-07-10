# Report Bundle 명세 v2

Stage 4(집필)의 출력이자 Stage 5(조립)의 입력. `build_report.py`가 이 형식을 파싱해
hwp-master ops JSON을 **결정론적으로** 생성한다. 사람이 읽기에도 자연스러워야 한다.

**v2 변경(CONTRACT_v0.6 §N/§O):** ①`[[TABLE cols= pt=]]` 열비율·글자크기 지정 추가
②`[[EQ]]` **기본값이 inline으로 전환**(display는 opt-in) ③cast-off 결과인
`layout_plan.json`이 bundle/에 추가(Stage 2.5) ④section budget 주석 규약.
그 외 태그(FIG/URL/META/SECTION)·규칙은 v1.1과 동일.

## 디렉토리

```
bundle/
├── content.md         # 본문 전체 (아래 형식) — 텍스트 + 태그만
├── layout_plan.json   # (v2 NEW) Stage 2.5 cast-off 결과 (CONTRACT §N). Stage 5가 참조.
├── anchors.json       # (선택) inspect로 확정한 SECTION 앵커 동결분
└── figures/           # PNG 원본 (content.md의 FIG가 참조)
```
- `layout_plan.json`은 **집필 전에** 확정된 copyfit 결정(섹션 line budget·표 열계획·
  그림 배치·수식 배치·요약 계획). 스키마는 CONTRACT_v0.6 §N. `layout_plan_check.py`가
  Stage 2.5 스크립트 게이트로 검증(exit 0/1).
- **stale sibling 금지**: `content.md.v2bak` 등 `.v2bak`/버전 백업 형제 파일을 bundle/에
  남기지 말 것. 두 개의 앵커 규약이 공존하면 재개 세션이 어느 쪽이 유효한지 알 수 없다(감사 F2).
  구버전은 폐기하거나 output/archive/로 옮긴다.

## content.md 형식

### 섹션 앵커
```
## SECTION: Ⅰ. 서론
```
- `## SECTION: ` 뒤 문자열은 **양식의 항목 제목과 글자 단위로 동일**해야 한다
  (조립 시 goto_text 앵커로 사용). Stage 5 시작 전에 inspect로 양식의 실제 제목을
  확인하고 불일치 시 content.md를 고친다 — 양식을 고치는 게 아니다.
- 섹션 본문은 일반 문단. 빈 줄 1개 = 문단 구분. 연속 빈 줄 금지.
- **budget 주석(v2, 선택)**: 섹션 앵커 줄 뒤에 `<!-- budget: 40 lines -->` 형태의
  주석으로 `layout_plan.json`의 line_budget을 인간 가독용으로 병기할 수 있다. 빌더는
  주석을 무시(파싱 안 함); 진실 소스는 `layout_plan.json`이다. 조립 후 rubric FAIL 시
  `rewrite_para(anchor, ±lines)`가 이 예산을 ±1–2줄 조정한다(새 노브 금지, CONTRACT §P).

### 수식 (v2: inline이 기본 — 태그 규약 변경)
```
[[EQ latex="T_0 = \frac{mv_0^2}{P}"]]           ← (v2 기본) 문장 속 inline
[[EQ display latex="\frac{1}{2}mv^2"]]          ← display는 opt-in (큰 행렬·유도만)
[[EQ inline hwpeqn="T_0 = {mv_0^2} over {P}"]]  ← inline 명시도 허용(동일 의미)
```
- **v2 기본값 = inline** (CONTRACT_v0.6 §O, S1 검증: COM `EquationCreate` 문장 중간
  `treatAsChar="1"`). 예시 편집 관습 = 수식이 문장 흐름에 붙음. `display` 키워드가 있을 때만
  자기 문단(가운데) 블록. (v1.1은 display가 기본이었음 — 반대로 뒤집혔다.)
- latex 또는 hwpeqn 중 하나. latex면 eqn.py 변환 + sanity check를 거친다.
- inline 식은 한 줄에 확실히 들어가는 짧은 식이어야 자연스럽다(집필 책임).
- display를 쓸 때 앞 문장은 "...다음과 같다." 류로 끝나야 자연스럽다 (집필 시 책임).

### 그림
```
[[FIG file="graph1.png" width=110 caption="[그림 1] 제동 시간에 따른 ..."]]
```
- 조립 규칙(고정): 그림 단독 문단(가운데, width mm, 높이 종횡비 자동) → 캡션 문단 아래(caption_pt=9, 가운데). width 미지정 시 110mm 기본.
- 빈 캡션(`caption=""`)이면 캡션 문단 생략.
- file은 bundle/figures/ 기준 상대경로.

### 표 (v2: cols= pt= 추가)
```
[[TABLE cols=10,16,12,9,10,43 pt=9 caption="표 1. 제동 시간에 따른 시뮬레이션 결과"]]
| 제동 시간(초) | 감속도(m/s²) | 회수율(%) |
| 1 | 16.7 | 18.6 |
[[/TABLE]]
```
- **cols=** (v2 NEW): 열 너비 백분율, 합 ≈100. `<hp:cellSz width>`로 반영(S2 검증:
  오프라인 XML 편집이 COM PDF 라운드트립 후에도 유지). `layout_plan.json.tables[].cols_pct`와
  일치해야 한다. 미지정 시 균등폭.
- **pt=** (v2 NEW): 셀 글자 크기(기본 base_pt-1, 관례 9). 미지정 시 base_pt-1.
- 목적: 행이 **≈1줄**로 떨어지게(rubric 검사 `table_proportion`). 검증된 계획: cols `[10,16,12,9,10,43]%`.
- 첫 행 = 헤더. 마크다운 구분선(|---|) 없음 — 모든 행이 데이터로 취급되므로 넣지 말 것.
- 인덱스 열 금지 (조립기는 받은 그대로 plain 삽입).

### 하이퍼링크 (참고문헌 URL)
```
[[URL href="https://doi.org/10.1000/xyz"]]        ← 명시 태그 (표시문구 = url)
[[URL href="https://..." text="해당 논문 링크"]]   ← 표시문구 지정
```
- 또는 **URL만 있는 단독 줄**(`^https?://...$`)은 자동으로 링크로 처리된다(태그 불필요).
- 조립 시 `insert_hyperlink` op으로 진짜 HYPERLINK 필드 + 링크 서식(파랑 #0000FF·밑줄,
  본문 크기)으로 들어간다. 한글 GUI의 '스페이스→자동 링크화'는 COM에서 안 되므로 필드로 삽입.
- 참고문헌은 "저자·제목 줄" 다음 "URL 단독 줄"로 쪼개 둘 것(URL 줄이 링크가 됨).

### 메타 (파일 머리, YAML)
> **우선순위(v0.4):** 이 build 노브들의 진실 소스는 `report-<slug>/build.yaml`이다(CONTRACT §4).
> build.yaml에 있는 키는 content.md front-matter를 **덮어쓴다**(build.yaml wins). content.md
> front-matter는 build.yaml이 없을 때의 폴백일 뿐이며, 신규 보고서는 build.yaml만 쓰고
> content.md는 텍스트+태그만 담는 것을 권장한다.

```yaml
---
title: 제동 시간에 따른 전기 자동차 회생 제동 에너지 회수율 분석
form: 물리학_보고서_양식.hwp       # Downloads 기준 파일명
title_anchor: "보고서 제목"        # 양식에서 제목이 들어갈 placeholder 문구 (없으면 생략)
base_pt: 10                        # 본문 글자 크기(기본 10). 본문·수식·URL에 강제 적용(앵커 제목 등 상속 금지).
caption_pt: 9                      # 캡션 글자 크기(기본 9). FIG/TABLE 캡션에 적용. 미지정 시 9.
line_spacing: 160                  # 줄간격(%). 미지정 시 양식 기본값 유지. 지정 시 양식 기본을 덮어씀.
binding: submit                    # book(기본,제본용 미러여백) | submit(제출용 좌우대칭)
abstract: false                    # true(기본) | false → 양식의 초록 표를 통째로 제거
abstract_table_index: 1            # abstract:false일 때 지울 표 index(기본 1=초록표)
---
```
- **base_pt**: 본문/수식/URL을 이 크기로 **강제**(insert-then-select). 제목은 양식 원본 크기 보존. 수식 BaseUnit도 base_pt로.
- **caption_pt**: FIG·TABLE 캡션 글자 크기(기본 9pt). 예시 편집 관습 — 캡션은 본문보다 1pt 작게.
- **line_spacing**: 본문 줄간격(%). **미지정 시 양식 기본값을 그대로 유지**하고, 값이 있으면
  조립 시 본문 문단에 강제 적용해 양식 기본을 덮어쓴다. 기본양식은 180. (v3→v5 재작업의 핵심 노브.)
- **binding**: `submit`이면 조립 시 `page_binding` op으로 좌우 여백을 대칭화(인쇄폭 동일).
- **abstract**: `false`면 `delete_ctrls`(tbl, abstract_table_index)로 초록 표 제거 →
  I.서론부터 시작. content.md에 초록 섹션을 아예 빼면 된다.

## build_report.py 의무 동작
1. content.md 파싱 → 섹션/수식/그림/표/URL 추출 (정규식 기반, 미지 태그는 에러)
2. 양식 inspect 결과와 SECTION 앵커 대조 — 하나라도 불일치면 **중단·보고** (우회 금지)
3. ops JSON 생성(순서 보존):
   - binding:submit → `page_binding`(맨 앞), abstract:false → `delete_ctrls`(초록표)
   - 섹션마다 `insert_blank_before`(제목 앞 빈 문단 1개 보장) → `goto_text`(next_para,
     제목 문단 안 쪼개고 다음 문단으로) → 본문/수식/그림/표
   - 본문·캡션·URL `insert_text`/`insert_hyperlink`에 `pt=base_pt`(글자크기 강제+검정),
     수식 base_pt=base_pt, URL은 링크 서식
4. 생성한 ops를 stdout JSON으로 출력. `com_backend edit --ops`는 {ok,...,ops} 래퍼와
   순수 리스트를 모두 받는다.
5. `--dry-run`: ops만 출력하고 한글 미실행 (단위 테스트용)

## 검증 (조립 후, hwp-master 절차에 추가)
- post_inspect: 수식 = EQ 개수, 그림 = FIG 개수, 표 = TABLE 개수(초록 off면 -1)
- **charPr 수치**(.hwpx unzip): 본문·수식·캡션·URL = base_pt, 본문 검정, URL 파랑·밑줄,
  제목은 양식 원본 크기 보존
- binding:submit → 전 페이지 좌우 여백 대칭(PDF text bbox left≈right_gap)
- 제목마다 앞 빈 문단 1개, 연속 빈 문단 2개 이상 없음
- layout QA 수치 게이트 + PDF 시각 이중 게이트 (글자색·고립 텍스트·자간 포함)
