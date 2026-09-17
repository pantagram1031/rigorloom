# Quickstart — edit an HWPX with an approved plan, no Hancom needed

Every command below was run on Ubuntu (WSL, Python 3.12) on 2026-09-17 against this branch. Nothing here needs
Hancom Office: the `xml` backend edits the HWPX bytes directly and produces a `structural_only` receipt. What it
does **not** do is render pages or prove layout; that still needs Hancom on Windows (`com` backend).

## 1. Build the wheel and the engine payload (from a checkout)

```bash
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 -m pip wheel --no-deps --no-build-isolation --no-index . -w ~/rigorloom-dist
for b in core style report; do python3 scripts/package_module.py --module $b --out ~/rigorloom-dist; done
ls ~/rigorloom-dist
#   rigorloom-0.17.0-py3-none-any.whl  rigorloom-core-0.17.0.zip  rigorloom-style-0.17.0.zip  rigorloom-report-0.17.0.zip
```

`setuptools` and `wheel` must be importable by `python3` (they are on most systems; otherwise
`python3 -m pip install --user setuptools wheel`).

## 2. Install the command in a clean environment and the engine into its own directory

Leave the checkout first. The installer's containment probe refuses to run while the current directory is a
checkout on `sys.path`.

```bash
cd ~
python3 -m venv ~/rigorloom-venv || python3 -m virtualenv ~/rigorloom-venv   # use virtualenv where ensurepip is missing
~/rigorloom-venv/bin/pip install ~/rigorloom-dist/rigorloom-0.17.0-py3-none-any.whl
~/rigorloom-venv/bin/rigorloom install --engine-root ~/rigorloom-install --bundles-dir ~/rigorloom-dist
~/rigorloom-venv/bin/rigorloom --root ~/rigorloom-work --engine-root ~/rigorloom-install capabilities
```

Expected backend states on Linux:

```
com      unavailable  not Windows; Hancom COM is win32 only
preedit  available    (4 op kinds)
xml      available    (9 op kinds)
```

**macOS:** use the same commands with `python3 -m venv` (ensurepip is present on typical
installs). This project has not been tested on macOS today; expect the same backend picture
as Linux—Hancom is absent, so `com` is unavailable and `xml` is the backend. When something
fails, run `rigorloom doctor --engine-root ~/rigorloom-install` first; its `result.nextStep`
line tells you the next command (install payload, use `--backend xml`, or open a document).

## 3. Open a form, propose, approve, apply, read the receipt

Use any HWPX. The corpus forms under `tests/corpus/forms/converted/` all work; the example below uses the
기안문 form. Set `RL` and `ROOT` once:

```bash
RL="$HOME/rigorloom-venv/bin/rigorloom --root $HOME/rigorloom-work --engine-root $HOME/rigorloom-install"
$RL open --path ~/rigorloom/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx
#   → result.sessionId, result.source.sha256
$RL inspect --session <sessionId> --include forbidden
#   → anchors and placeholders the residue gate will look for
$RL propose --session <sessionId> --backend xml --proposer me \
  --op '{"kind":"goto_text","text":"행 정 기 관 명"}' \
  --op '{"kind":"insert_text","text":"newcomer smoke"}'
#   → result.plan.planId, result.plan.planHash
$RL request-approval --plan <planId> --requested-by me
#   → result.approvalId (state pending)
$RL approve --approval <approvalId> --plan <planId> --plan-hash <planHash> --approver me
$RL apply --plan <planId> --approval <approvalId>
#   → result.candidate.candidate.sha256, result.candidate.checks.acceptance
$RL receipt --session <sessionId> --run <runId>
```

What the receipt says for an xml apply (the CLI prints it under `result.receipt`):

```json
"backend": "xml",
"evidence": {
  "class": "structural_only",
  "xml": {"proofGrade": "structural", "wellFormed": true},
  "note": "no renderer ran; this receipt binds bytes and offline checker results, and claims no render proof"
},
"residue": {"profileSource": "self_derived", "sha256": "…", "declaration": null,
            "note": "inventory is heuristic: this document was profiled as its own form …"}
```

The candidate lives under `~/rigorloom-work/sessions/<sessionId>/candidates/<runId>/artifact.hwpx`. The source
file is never modified.

`checks.acceptance` is `false` on a blank form after a one-line insert: the residue gate reports the form's own
placeholders and guide text that are still there. That is the gate working. Fill the form completely, or edit a
finished document with `open --form-profile <blank form profile>` and a `--declares-file` keep list, to reach
`acceptance: true`.

Measured on the ten corpus forms: open → apply took 1.9–3.9 s each.

## 4. What is not covered here

- Rendering pages, PDF export and layout QA need Hancom on Windows (`--backend com`, `render-prepare`, `render`).
- The report pipeline (topic → simulation → draft → assembled report) is documented in
  `pipeline/references/playbooks/`.
- The desktop app is built separately (`desktop/`); this page is the CLI path only.

---

# 빠른 시작 — 한컴 없이 HWPX를 승인된 계획으로 편집하기

아래 명령은 2026-09-17에 Ubuntu(WSL, Python 3.12)에서 이 브랜치로 실제 실행한 것이다. 한컴오피스는 필요 없다.
`xml` 백엔드가 HWPX 바이트를 직접 고치고 `structural_only` 영수증을 남긴다. 페이지 렌더링이나 레이아웃 증명은 하지
않는다. 그 부분은 Windows의 한컴(`com` 백엔드)이 맡는다.

## 1. 체크아웃에서 휠과 엔진 페이로드 만들기

```bash
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 -m pip wheel --no-deps --no-build-isolation --no-index . -w ~/rigorloom-dist
for b in core style report; do python3 scripts/package_module.py --module $b --out ~/rigorloom-dist; done
```

## 2. 깨끗한 환경에 명령을 설치하고 엔진은 별도 디렉터리에 설치

먼저 체크아웃 밖으로 나간다. 현재 디렉터리가 체크아웃이면 설치기의 격리 검사가 실행을 거부한다.

```bash
cd ~
python3 -m venv ~/rigorloom-venv || python3 -m virtualenv ~/rigorloom-venv
~/rigorloom-venv/bin/pip install ~/rigorloom-dist/rigorloom-0.17.0-py3-none-any.whl
~/rigorloom-venv/bin/rigorloom install --engine-root ~/rigorloom-install --bundles-dir ~/rigorloom-dist
~/rigorloom-venv/bin/rigorloom --root ~/rigorloom-work --engine-root ~/rigorloom-install capabilities
```

Linux에서는 `com`이 `unavailable`(Windows 전용), `preedit`과 `xml`이 `available`로 나온다.

## 3. 양식 열기 → 제안 → 승인 → 적용 → 영수증

```bash
RL="$HOME/rigorloom-venv/bin/rigorloom --root $HOME/rigorloom-work --engine-root $HOME/rigorloom-install"
$RL open --path ~/rigorloom/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx
$RL inspect --session <sessionId> --include forbidden
$RL propose --session <sessionId> --backend xml --proposer me \
  --op '{"kind":"goto_text","text":"행 정 기 관 명"}' \
  --op '{"kind":"insert_text","text":"newcomer smoke"}'
$RL request-approval --plan <planId> --requested-by me
$RL approve --approval <approvalId> --plan <planId> --plan-hash <planHash> --approver me
$RL apply --plan <planId> --approval <approvalId>
$RL receipt --session <sessionId> --run <runId>
```

원본 파일은 절대 바뀌지 않는다. 후보본은 `~/rigorloom-work/sessions/<sessionId>/candidates/<runId>/artifact.hwpx`에
생긴다. 빈 양식에 한 줄만 넣으면 `checks.acceptance`는 `false`다. 양식의 자리표시자와 안내문이 남아 있다는 잔여
검사가 정상 작동한 것이다. 양식을 끝까지 채우거나, 완성 문서를 `open --form-profile`과 `--declares-file`로 열면
`acceptance: true`에 이른다.

## 4. 여기서 다루지 않는 것

- 페이지 렌더링·PDF·레이아웃 검사: Windows + 한컴(`--backend com`, `render-prepare`, `render`).
- 보고서 파이프라인: `pipeline/references/playbooks/`.
- 데스크톱 앱: `desktop/`.
