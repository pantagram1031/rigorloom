# HwpEqn (한글 수식 스크립트) 치트시트

한글 수식 편집기(Ctrl+N,M)의 스크립트 입력창에 들어가는 문법.
LaTeX와 유사하나 **백슬래시 없음**, 분수는 `over`, 그룹은 `{}`.

## 기본 구조
| 의미 | HwpEqn | 예시 |
|---|---|---|
| 분수 | `{A} over {B}` | `{1} over {2}` |
| 제곱근 | `sqrt {X}` | `sqrt {b^2 -4ac}` |
| n제곱근 | `root {n} of {X}` | `root {3} of {x}` |
| 위첨자 | `^` | `x^{2}` |
| 아래첨자 | `_` | `a_{n}` |
| 위·아래 동시 | `_{}^{}` | `int _{0} ^{inf}` |
| 리터럴 텍스트 | `"..."` | `"속도" = v` |
| 로만체 | `rm {X}` / 이탤릭 `it {X}` | `rm {dB}` |
| 수식 내 공백 | `` ` `` (백틱, 1/4칸) `~` (1칸) | `dx` 앞 `` ` `` |
| 줄바꿈 | `#` | 다단 수식 |
| 정렬 탭 | `&` | eqalign에서 = 정렬 |

## 연산자/기호
`+-`(±) `-+`(∓) `times` `div` `cdot` `leq` `geq` `neq` `approx` `equiv`
`prop`(∝) `inf`(∞) `partial` `del`(∇) `therefore` `because` `angle`
`rarrow`(→) `larrow`(←) `lrarrow`(↔) `RARROW`(⇒) `LRARROW`(⇔)
`in` `notin` `subset` `cup` `cap` `forall` `exist` `emptyset`
`cdots` `ldots` `vdots` `ddots` `prime` `hbar`

## 그리스 문자
소문자 그대로: `alpha beta gamma delta epsilon theta lambda mu pi rho sigma tau phi omega`
대문자는 첫 글자 대문자: `Gamma Delta Theta Sigma Omega`

## 큰 연산자 (첨자는 _ ^)
`int`(∫) `dint`(∬) `tint`(∭) `oint`(∮) `sum` `prod` `lim`
예: `lim _{n rarrow inf} {1} over {n} = 0`

## 장식
`vec {a}` `bar {x}` `hat {y}` `dot {x}` `ddot {x}` `tilde {a}` `under {x}`

## 괄호 자동 크기
`left ( ... right )` / `left { ... right }` / `left | ... right |`
한쪽만: `left ( ... right .` (마침표 = 빈 괄호)

## 행렬/케이스
```
pmatrix{a & b # c & d}     ( ) 행렬
bmatrix{a & b # c & d}     [ ] 행렬
dmatrix{a & b # c & d}     | | 행렬식
cases{x & (x>0) # -x & (x<0)}
eqalign{y &= ax+b # &= 2x+1}    & 위치에서 정렬
```

## 자주 쓰는 완성 예시
```
이차방정식 해:  x = {-b +- sqrt {b^{2} -4ac}} over {2a}
가우스 적분:    int _{0} ^{inf} e^{-x^{2}} `dx = {sqrt {pi}} over {2}
음압 레벨:      L_{p} = 10 log {p^{2}} over {p_{0}^{2}} ~rm{[dB]}
운동에너지:     E_{k} = {1} over {2} mv^{2}
미분 정의:      f'(x) = lim _{h rarrow 0} {f(x+h)-f(x)} over {h}
```

## LaTeX→HwpEqn 자동 변환
`python scripts/eqn.py "<latex>"` — warnings가 비어 있으면 그대로 사용 가능.
warnings가 있으면 해당 부분만 이 치트시트로 수동 보정.

## 주의
- 글꼴 기본값은 HancomEQN. `EqFontName`으로 HYhwpEQ 등 변경 가능.
- BaseUnit은 HwpUnit(1pt=100) — 본문 10pt 문서에는 1000~1100이 자연스럽다.
- 중괄호 짝과 `"` 짝이 안 맞으면 수식 전체가 깨진다 (eqn.py의 sanity check 활용).
- `log{A}over{B}` 형태에서 over는 직전 그룹에만 적용되어 log가 분자에 묶이지 않음 (2026-06-11 PDF 검증 완료).
