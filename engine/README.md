> Absorbed into rigorloom as core engine (Wave 2, 2026-08-06); history preserved.

# hwp-master

> 한글(HWP/HWPX) 문서를 AI 에이전트가 "사람처럼" 편집하게 하는 듀얼 백엔드 Agent Skill.
> Claude Code · OpenAI Codex · Claude Cowork · claude.ai 공용.

## 무엇을 하나

| 요구사항 | 구현 |
|---|---|
| 기존 양식(글꼴·문단모양·쪽설정) 보존 | COM 백엔드가 한컴오피스를 직접 구동 — 사람이 편집하는 것과 동일 |
| 실시간 편집 검증 | 매 편집 후 PDF 내보내기 + 구조 요약(inspect) 회귀 확인 루프 |
| 그림 삽입 | `insert_picture` (크기 mm 지정, 글자처럼 취급/오버레이) |
| 표 삽입 | `insert_table` (2차원 배열 → 표), 기존 표 셀 수정(`set_cell`) |
| **한글 수식 자동 삽입** | LaTeX → HwpEqn 변환기 내장 + `EquationCreate` 네이티브 삽입 |
| 토큰/시간 효율 | 전체 본문 덤프 금지 — 구조 요약 JSON(inspect) + 배치 ops 편집 |
| .hwp(구형 바이너리) 지원 | COM 경로로 직접 편집/변환 (XML 백엔드는 .hwpx 전용) |

## 빠른 시작 (Windows + 한컴오피스)

```powershell
pip install pyhwpx pywin32

# 1) 문서 구조 파악
python scripts/com_backend.py inspect --file 보고서.hwp

# 2) 편집 (ops.json에 작업 목록 작성)
python scripts/com_backend.py edit --file 보고서.hwp --ops ops.json `
    --save-as 보고서_v2.hwpx --export-pdf verify.pdf
```

ops.json 예시:
```json
[
  {"op": "put_field", "name": "작성자", "value": "홍길동"},
  {"op": "goto_text", "text": "3. 실험 결과"},
  {"op": "insert_equation", "latex": "L_p = 10 \\log \\frac{p^2}{p_0^2}"},
  {"op": "insert_table", "data": [["주파수(Hz)","측정값(dB)"],["500","42.1"]]},
  {"op": "insert_picture", "path": "C:/work/그래프.png", "width_mm": 100}
]
```

## 에이전트에 설치

```powershell
# Claude Code (개인 스킬)
git clone https://github.com/pantagram1031/hwp-master %USERPROFILE%\.claude\skills\hwp-master

# OpenAI Codex
git clone https://github.com/pantagram1031/hwp-master %USERPROFILE%\.agents\skills\hwp-master
```
프로젝트 단위로는 `<프로젝트>/.claude/skills/` 또는 `<프로젝트>/.agents/skills/`에 클론.
자세한 환경별 안내(Cowork, claude.ai 포함)는 [INSTALL.md](INSTALL.md).

## 아키텍처

```
요청 → SKILL.md 의사결정 트리
        ├─ Windows + 한컴오피스 → COM 백엔드 (pyhwpx)
        │    inspect → ops 편집 → save-as → PDF 검증 → 통과 시에만 채택
        └─ 리눅스/샌드박스 → XML 백엔드 (바이트 보존 HWPX 편집, 별도 스킬)
```

핵심 원칙: **원본 비파괴**(항상 `--save-as`), **검증 게이트 통과 전 채택 금지**,
**전체 XML/본문을 LLM 컨텍스트에 덤프하지 않음**.

## 수식 변환기 단독 사용

```bash
python scripts/eqn.py "\frac{-b \pm \sqrt{b^2-4ac}}{2a}"
# → {"ok": true, "contract": "rigorloom/hwpeqn/v1", "warnings": [], ...}
```
순수 파이썬이라 어느 환경에서나 동작. 문법은 [references/hwpeqn_cheatsheet.md](references/hwpeqn_cheatsheet.md).

## 요구 환경
- COM 백엔드: Windows + 한컴오피스(한글 2020+, 2022 권장) + Python 3.11/3.12 + pyhwpx
- eqn.py: Python 3.8+ (의존성 없음)

## Editing engines

| Engine | Environment | Output / proof |
|---|---|---|
| `com` (default) | Windows + Hancom Office | Print-grade native editing and Hancom PDF proof. Existing behavior is unchanged. |
| `xml` | Any OS with Python; input must be `.hwpx` | COM-free core text/equation/table editing. XML structure and paragraph formats are verified; PDF proof is advisory and available only when `--pdf-cmd` supplies a renderer such as LibreOffice with H2Orestart. Without one, the verdict records `proof_unavailable` without treating it as a failure. |

Example renderer template: `--engine xml --pdf-cmd 'soffice --headless --convert-to pdf --outdir {out_dir} {input}'`.

## 알려진 한계
- COM 백엔드는 한컴오피스 라이선스 필요, GUI 프로세스 기반이라 대량 배치엔 느릴 수 있음
- 암호화된 문서 미지원
- LaTeX→HwpEqn conversion is bounded by the T92 lexical contract; unsupported
  commands and conversion warnings refuse the operation rather than degrade.
- T92 contract note: unknown commands, unsupported environments, malformed
  arguments, raw HwpEqn punctuation in the LaTeX lane, and any conversion
  warning are terminal refusals (CLI 0=warning-free, 2=usage, 3=refusal).
  `base_pt` is shared/quantized to 0.1pt with the conservative contract bound
  1≤pt≤100.
  Warning-free conversion proves only a bounded lexical envelope; it is not
  HwpEqn semantic validity, native/render/layout/PDF parity, or proof.

### Equation contract (T92)

`scripts/eqn.py` implements `rigorloom/hwpeqn/v1`: a bounded lexical
preflight shared by the COM and XML backends. Unknown LaTeX commands,
unsupported environments, malformed required arguments, unmatched delimiters,
controls, and conversion warnings are terminal refusals. CLI exits are 0 for
warning-free conversion, 2 for usage, and 3 for refusal; refusal JSON never
contains source equation text or generated HwpEqn. This is not an HwpEqn
semantic, native-render, layout, PDF, or parity proof.

## License
MIT
