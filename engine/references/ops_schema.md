# ops.json schema — com_backend.py edit 입력 계약

`com_backend.py edit --ops X.json` 이 받는 편집 op 배치의 형식. build_report.py가
방출하는 `{ok, counts, anchors, ops:[...]}` 래퍼와 순수 `[...]` 리스트를 모두 받는다
(선택 최상위 `"schema": 1` 필드는 무시). 실행 **전** `_validate_ops`가 op 이름과
필수 키를 검사해 배치 중간 실패로 문서가 절반만 변형되는 것을 막는다.

각 op = `{"op": <name>, ...keys}`. 아래 표의 R=필수, O=선택.

| op | 필수 키 | 선택 키 | 효과 |
|---|---|---|---|
| `replace_all` | find, replace | | 문서 전체 문자열 치환 |
| `put_field` | name, text | | 누름틀/필드 값 채우기 |
| `goto_text` | text | next_para, cell_below | 문구로 커서 이동(next_para=다음 문단 앞, cell_below=표 라벨 셀 앵커일 때 TableLowerCell로 다음 행 셀로 이동 — next_para보다 우선) |
| `find_delete` | find | required(기본 true) | 문구 문단 삭제. required:false면 미발견 시 skip |
| `move` | | to(doc_end/doc_start/line_end) | 커서 이동 |
| `insert_text` | text | pt, break_after | 커서 위치에 텍스트 삽입(pt=글자크기 강제, break_after=삽입 뒤 BreakPara로 새 문단 — 리터럴 "\r\n"과 달리 인접 서식 오염 없음) |
| `insert_equation` | | latex/hwpeqn, display, base_pt | 수식 삽입(latex→HwpEqn 변환) |
| `edit_equation` | | index, hwpeqn | 기존 수식 편집 |
| `insert_table` | data | treat_as_char, caption, col_ratios, font_pt | 표 삽입(data=행렬 리스트). col_ratios=정규화 비율 리스트(합=1.0, len==열개수) — HTableCreation WidthType=2 직접 경로. font_pt=셀 텍스트 크기(insert-then-select) |
| `insert_picture` | path | width_mm, own_paragraph | 그림 삽입 |
| `set_cell` | | row, col, text | 표 셀 값 |
| `set_char_color` | | color(기본 0=검정), all(기본 true) | 글자색. **all:true는 하이퍼링크도 덮음** — 링크 삽입 후 실행 금지 |
| `delete_ctrls` | | types, index | 컨트롤(표/그림/수식) 삭제 |
| `collapse_empty_paragraphs` | | | 연속 빈 문단 축소. **제목 글자크기 오염 위험** — 자동 사용 금지 |
| `delete_blank_after` | text | count, required | 앵커 문단 뒤 빈 문단 제거 |
| `delete_blank_before` | text | count, required(기본 true) | 앵커 문단 앞 빈 문단 제거. required:false면 미발견 시 skip |
| `set_para_align` | | align, all | 문단 정렬 |
| `insert_blank_before` | text | | 앵커 앞 빈 문단 1개 보장(멱등) |
| `insert_hyperlink` | url | text, pt | 하이퍼링크 삽입(파란색). set_char_color all:true 앞에 두지 말 것 |
| `page_binding` | | mode(submit/book) | 여백 대칭/제본 전환 |
| `set_line_spacing` | | percent(기본 160), all(기본 true) | 줄간격 % 설정 |

## 검증 규칙 (`_validate_ops`)
1. 페이로드는 리스트 또는 `{"ops":[...]}` 래퍼.
2. 각 항목은 dict이고 `"op"` 키 보유.
3. `op` 값은 OPS 레지스트리에 존재.
4. 위 표의 R(필수) 키 전부 존재.
위반 시 첫 위반 index를 담아 `_die`(exit 2). 이 검사는 한글 실행 전에 돈다.

## 비파괴 규칙 (main)
`edit --save-as` / `convert --to` 의 대상 경로가 입력 `--file`과 같으면 `_die`.
원본 양식·제출본은 절대 덮어쓰지 않는다.
