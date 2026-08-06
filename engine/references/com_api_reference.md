# COM API 레퍼런스 (pyhwpx / HAction)

com_backend.py가 덮지 못하는 작업을 직접 코딩할 때 참고.

## 세션
```python
from pyhwpx import Hwp
hwp = Hwp(visible=False)        # 보안모듈(FilePathCheckDLL) 자동 등록
hwp.open(r"C:\문서.hwp")
...
hwp.save_as(r"C:\결과.hwpx")    # 확장자로 형식 추론; ("...pdf", "PDF")도 가능
hwp.quit()
```
raw COM 접근: `hwp.hwp` (win32com 객체). 임의 액션: `hwp.Run("ActionID")` 또는 `hwp.ActionID()`.

## HAction 3단 패턴 (모든 대화상자형 기능의 공통 골격)
```python
pset = hwp.HParameterSet.H<Set이름>
hwp.HAction.GetDefault("<ActionID>", pset.HSet)
pset.<파라미터> = 값
hwp.HAction.Execute("<ActionID>", pset.HSet)
```
파라미터 발견법: 한글에서 **Shift+Alt+H**로 GUI 동작을 스크립트 매크로로 녹화 → 그대로 번역.

## 수식
```python
# 삽입
pset = hwp.HParameterSet.HEqEdit
hwp.HAction.GetDefault("EquationCreate", pset.HSet)
pset.string = "x = {-b +- sqrt{b^2-4ac}} over {2a}"
pset.BaseUnit = 1000              # 10pt
pset.EqFontName = "HancomEQN"     # 선택
hwp.HAction.Execute("EquationCreate", pset.HSet)

# 기존 수식 순회/수정 (CtrlID == "eqed")
ctrl = hwp.HeadCtrl
while ctrl:
    if ctrl.CtrlID == "eqed":
        prop = ctrl.Properties
        print(prop.Item("String"))
        prop.SetItem("String", "E = mc^2"); ctrl.Properties = prop
    ctrl = ctrl.Next

# MathML 왕복
hwp.export_mathml("eq.mml") / hwp.import_mathml("eq.mml")
```

## 표
```python
hwp.create_table(rows, cols, treat_as_char=True)
hwp.table_from_data(df)                  # DataFrame/dict/list/CSV/Excel
hwp.get_into_nth_table(0)                # n번째 표 첫 셀로 진입
hwp.TableRightCell(); hwp.TableLowerCell()  # 셀 이동
df = hwp.table_to_df()                   # 표 → DataFrame
```

## 그림
```python
hwp.insert_picture(path, treat_as_char=True, embedded=True)
# 크기 지정: sizeoption=1, width=hwp.MiliToHwpUnit(mm), height=...
# 글 뒤 배치(도장/서명 오버레이):
hwp.insert_picture(path); hwp.FindCtrl()
ps = hwp.HParameterSet.HShapeObject
hwp.HAction.GetDefault("ShapeObjDialog", ps.HSet)
ps.TextWrap = 2; ps.TreatAsChar = 0
ps.HorzOffset = hwp.MiliToHwpUnit(139); ps.VertOffset = hwp.MiliToHwpUnit(196)
hwp.HAction.Execute("ShapeObjDialog", ps.HSet)
```

## 필드(누름틀) — 양식 보존 편집의 1순위
```python
hwp.get_field_list()                 # 필드 목록
hwp.put_field_text("성명", "홍길동")
hwp.get_field_text("성명")
hwp.fields_to_dict()                 # 전체 필드 → dict
```

## 텍스트/커서
```python
hwp.find("앵커 문구")                # 찾기 (커서 이동)
hwp.find_replace_all(a, b)           # 전체 치환 (regex= 지원)
hwp.insert_text("문장\r\n")          # 줄바꿈은 \r\n
hwp.MoveDocBegin() / MoveDocEnd() / MoveLineEnd()
hwp.get_selected_text()
hwp.GetTextFile("TEXT", "")          # 전체 텍스트 (토큰 주의 — inspect 우선)
```

## 검증/변환
```python
hwp.save_as("out.pdf", "PDF")        # 시각 검증용
hwp.PageCount                        # 쪽수
hwp.save_image(...) / save_all_pictures()
hwp.open_pdf("in.pdf")               # PDF → HWP
```

## 단위
1 pt = 100 HwpUnit, 1 mm ≈ 283.465 HwpUnit (`hwp.MiliToHwpUnit(mm)` 사용).
