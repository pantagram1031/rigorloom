# Stage 9 F0 — Desktop copy audit

Read-only. Source: `desktop/src/**/*.ts{,x}` excluding `smoke.ts` (harness, not product UI).
Principles from `docs/plans/stage9-product-feel.md`: short **합니다체**; human words on the chrome; `charPr` / hash / plan id / pid / forbidden / `structural_only` / runtime only in 기술 정보 or a tooltip; prose walls cut to one line or dropped when the UI already shows the fact.

Honesty (no render proof, approval is human, source never modified) is **kept**, but **once per surface**, one line. Fable edits proposals before apply.

Action key: **KEEP** / **SHORTEN** / **MOVE-TO-TOOLTIP** / **MOVE-TO-DETAILS** / **DROP** / **RENAME**.

`…` in current text is a runtime interpolation.


## home

Honesty (once): 사람이 승인합니다. 원본은 바뀌지 않습니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `App.tsx:67` | error | RENAME | 런타임을 시작하지 못했습니다 | 엔진을 시작하지 못했습니다 |
| `App.tsx:372` | label | KEEP | 여기에 놓으면 문서를 엽니다 | 여기에 놓으면 문서를 엽니다 |
| `components/ErrorBoundary.tsx:41` | label | KEEP | 화면을 그리지 못했습니다 | 화면을 그리지 못했습니다 |
| `components/ErrorBoundary.tsx:43` | prose | SHORTEN | 문서와 런타임은 그대로입니다. 창을 다시 열면 이어서 작업할 수 있습니다. | 문서와 엔진은 그대로입니다. |
| `components/ErrorBoundary.tsx:51` | label | KEEP | 자세히 | 자세히 |
| `components/Splash.tsx:48` | tooltip | KEEP | 눌러서 건너뛰기 | 눌러서 건너뛰기 |
| `components/Welcome.tsx:20` | toast | KEEP | 복사하지 못했습니다 | 복사하지 못했습니다 |
| `components/Welcome.tsx:24` | toast | KEEP | 경로를 복사했습니다 | 경로를 복사했습니다 |
| `components/Welcome.tsx:25` | toast | KEEP | 복사하지 못했습니다 | 복사하지 못했습니다 |
| `components/Welcome.tsx:33` | label | KEEP | 방금 | 방금 |
| `components/Welcome.tsx:34` | label | KEEP | …분 전 | …분 전 |
| `components/Welcome.tsx:40` | label | KEEP | 어제 | 어제 |
| `components/Welcome.tsx:41` | label | KEEP | …시간 전 | …시간 전 |
| `components/Welcome.tsx:76` | label | KEEP | 양식 | 양식 |
| `components/Welcome.tsx:82` | label | KEEP | 찾을 수 없음 | 찾을 수 없음 |
| `components/Welcome.tsx:128` | prose | SHORTEN | 문서를 열고, 에이전트가 제안한 편집을 사람이 승인하면, 런타임이 적용하고 | 문서를 열고, 사람이 승인하면 후보본과 영수증이 남습니다. |
| `components/Welcome.tsx:129` | prose | DROP | 영수증을 남깁니다. | — (lede 한 줄에 합침) |
| `components/Welcome.tsx:140` | label | KEEP | 문서 열기 | 문서 열기 |
| `components/Welcome.tsx:146` | tooltip | SHORTEN | 빈 양식이나 form_profile.json을 연결해 엽니다 | 빈 양식을 연결해 엽니다. |
| `components/Welcome.tsx:150` | label | KEEP | 양식 연결 | 양식 연결 |
| `components/Welcome.tsx:158` | label | RENAME | 파일을 끌어다 놓으세요 | 파일을 여기에 놓습니다 |
| `components/Welcome.tsx:169` | prose | SHORTEN | 처음이신가요? 양식 HWPX 파일 하나를 열면 시작됩니다 | 양식 파일 하나를 열면 시작합니다. |
| `components/Welcome.tsx:173` | label | KEEP | 최근 문서 | 최근 문서 |
| `components/Welcome.tsx:182` | label | KEEP | CLI 문서 | CLI 문서 |
| `components/Welcome.tsx:190` | tooltip | KEEP | … 복사 | … 복사 |
| `components/Welcome.tsx:193` | label | KEEP | 복사 | 복사 |
| `components/Welcome.tsx:206` | label | KEEP | 설정 | 설정 |
| `components/Welcome.tsx:126` | label | KEEP | Rigorloom | Rigorloom |
| `components/Splash.tsx:51` | label | KEEP | Rigorloom | Rigorloom |

## header

Honesty (once): — (home과 공유; 중복 금지)

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `App.tsx:50` | label | KEEP | 여는 중 | 여는 중 |
| `App.tsx:75` | label | KEEP | 다시 시도 | 다시 시도 |
| `App.tsx:288` | tooltip | KEEP | 홈 (Ctrl+Shift+H) | 홈 (Ctrl+Shift+H) |
| `App.tsx:289` | aria | KEEP | 홈 | 홈 |
| `App.tsx:307` | tooltip | KEEP | 문서로 돌아가기 | 문서로 돌아가기 |
| `App.tsx:322` | label | KEEP | 셸 오류 기록됨 | 셸 오류 기록됨 |
| `App.tsx:329` | label | RENAME | 런타임 끊김 | 엔진 끊김 |
| `App.tsx:332` | label | KEEP | 다시 시작 | 다시 시작 |
| `App.tsx:339` | label | KEEP | 문서 열기 | 문서 열기 |
| `App.tsx:344` | tooltip | SHORTEN | 빈 양식이나 form_profile.json을 연결해 엽니다 | 빈 양식을 연결해 엽니다. |
| `App.tsx:348` | label | KEEP | 양식 연결 | 양식 연결 |
| `App.tsx:353` | tooltip | KEEP | 에이전트 제공자 설정 | 에이전트 제공자 설정 |
| `App.tsx:357` | label | KEEP | 설정 | 설정 |
| `actions.ts:746` | tooltip | KEEP | 양식 연결 | 양식 연결 |
| `actions.ts:747` | label | KEEP | 양식 프로필 또는 빈 양식 | 양식 프로필 또는 빈 양식 |
| `actions.ts:758` | tooltip | KEEP | 한글 문서 열기 | 한글 문서 열기 |
| `actions.ts:759` | label | KEEP | 한글 문서 | 한글 문서 |
| `actions.ts:790` | toast | KEEP | 한글 문서(.hwpx, .hwp)만 열 수 있습니다 | 한글 문서(.hwpx, .hwp)만 열 수 있습니다 |
| `actions.ts:797` | toast | KEEP | …개 중 첫 문서만 열었습니다 | …개 중 첫 문서만 열었습니다 |
| `actions.ts:2203` | label | KEEP | 한글 문서 | 한글 문서 |
| `actions.ts:3137` | label | KEEP | 문서 전체 | 문서 전체 |
| `actions.ts:3297` | label | KEEP | 열린 문서를 찾는 중 | 열린 문서를 찾는 중 |
| `actions.ts:3315` | label | KEEP | 문서를 다시 읽는 중 | 문서를 다시 읽는 중 |
| `actions.ts:3747` | toast | KEEP | 문서를 먼저 열어야 검사를 돌립니다 | 문서를 먼저 열어야 검사를 돌립니다 |
| `App.tsx:299` | label | KEEP | Rigorloom | Rigorloom |
| `components/Logo.tsx:32` | aria | KEEP | Rigorloom | Rigorloom |

## toolbar

Honesty (once): 페이지 그림은 증거가 아닙니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `actions.ts:557` | toast | KEEP | 채우기를 멈췄습니다. | 채우기를 멈췄습니다. |
| `actions.ts:571` | toast | KEEP | 채우기를 멈추라고 알렸습니다. | 채우기를 멈추라고 알렸습니다. |
| `actions.ts:611` | toast | KEEP | 포스터 만들기를 멈췄습니다. | 포스터 만들기를 멈췄습니다. |
| `components/EditorToolbar.tsx:169` | label | KEEP | 한글 | 한글 |
| `components/EditorToolbar.tsx:170` | label | KEEP | 영문 | 영문 |
| `components/EditorToolbar.tsx:171` | label | KEEP | 한자 | 한자 |
| `components/EditorToolbar.tsx:172` | label | KEEP | 일어 | 일어 |
| `components/EditorToolbar.tsx:173` | label | KEEP | 기타 | 기타 |
| `components/EditorToolbar.tsx:174` | label | KEEP | 기호 | 기호 |
| `components/EditorToolbar.tsx:175` | label | KEEP | 사용자 | 사용자 |
| `components/EditorToolbar.tsx:255` | label | KEEP | 이 빌드는 글꼴 이름을 읽지 못했습니다 | 이 빌드는 글꼴 이름을 읽지 못했습니다 |
| `components/EditorToolbar.tsx:259` | aria | KEEP | 편집 도구 | 편집 도구 |
| `components/EditorToolbar.tsx:272` | tooltip | KEEP | 구조 레일 접기 (Ctrl+B) | 구조 레일 접기 (Ctrl+B) |
| `components/EditorToolbar.tsx:274` | aria | KEEP | 구조 레일 접기 | 구조 레일 접기 |
| `components/EditorToolbar.tsx:278` | label | KEEP | 구조 접기 | 구조 접기 |
| `components/EditorToolbar.tsx:283` | tooltip | KEEP | 문서 열기 (Ctrl+O) | 문서 열기 (Ctrl+O) |
| `components/EditorToolbar.tsx:287` | label | KEEP | 열기 | 열기 |
| `components/EditorToolbar.tsx:292` | tooltip | SHORTEN | 빈 양식이나 form_profile.json을 연결해 엽니다 | 빈 양식을 연결해 엽니다. |
| `components/EditorToolbar.tsx:296` | label | KEEP | 양식 연결 | 양식 연결 |
| `components/EditorToolbar.tsx:304` | label | KEEP | 후보본과 영수증을 함께 저장합니다 | 후보본과 영수증을 함께 저장합니다 |
| `components/EditorToolbar.tsx:305` | label | KEEP | 아직 내보낼 후보본이 없습니다. 편집을 승인해 적용하면 생깁니다. | 아직 내보낼 후보본이 없습니다. 편집을 승인해 적용하면 생깁니다. |
| `components/EditorToolbar.tsx:311` | label | KEEP | 내보내는 중… | 내보내는 중… |
| `components/EditorToolbar.tsx:317` | tooltip | KEEP | 되돌리기와 후보본 계보를 봅니다 | 되돌리기와 후보본 계보를 봅니다 |
| `components/EditorToolbar.tsx:321` | label | KEEP | 되돌리기 | 되돌리기 |
| `components/EditorToolbar.tsx:327` | tooltip | SHORTEN | 오프라인 검사를 돌립니다. 페이지 그림은 증거가 아닙니다. | 오프라인 검사를 돌립니다. |
| `components/EditorToolbar.tsx:333` | label | KEEP | 검사 중… | 검사 중… |
| `components/EditorToolbar.tsx:335` | label | KEEP | 검사 | 검사 |
| `components/EditorToolbar.tsx:337` | label | KEEP | 막힘 … | 막힘 … |
| `components/EditorToolbar.tsx:338` | label | KEEP | 검사 … | 검사 … |
| `components/EditorToolbar.tsx:347` | prose | SHORTEN | 승인 게이트가 열려 있습니다. 오른쪽 패널에서 결정합니다. | 승인 게이트가 열려 있습니다. |
| `components/EditorToolbar.tsx:349` | label | KEEP | 대기 중인 편집의 승인을 요청합니다 | 대기 중인 편집의 승인을 요청합니다 |
| `components/EditorToolbar.tsx:350` | prose | SHORTEN | 승인을 요청할 편집이 없습니다. 채움 자리에 값을 넣으면 대기열에 쌓입니다. | 승인을 요청할 편집이 없습니다. 채움 자리에 값을 넣으면 대기열에 쌓입니다. |
| `components/EditorToolbar.tsx:364` | label | KEEP | 승인 | 승인 |
| `components/EditorToolbar.tsx:373` | label | KEEP | 서식 | 서식 |
| `components/EditorToolbar.tsx:379` | label | KEEP | 글꼴 | 글꼴 |
| `components/EditorToolbar.tsx:386` | label | KEEP | 이 문서가 선언한 글꼴입니다 — … | 이 문서가 선언한 글꼴입니다 — … |
| `components/EditorToolbar.tsx:388` | label | KEEP | 글꼴 이름을 읽을 수 없었습니다 — … | 글꼴 이름을 읽을 수 없었습니다 — … |
| `components/EditorToolbar.tsx:390` | label | KEEP | 이 문서는 이 글자 모양에 쓸 글꼴 이름을 선언하지 않았습니다. | 이 문서는 이 글자 모양에 쓸 글꼴 이름을 선언하지 않았습니다. |
| `components/EditorToolbar.tsx:391` | label | KEEP | 선택한 곳이 없습니다. | 선택한 곳이 없습니다. |
| `components/EditorToolbar.tsx:398` | label | KEEP | 읽지 못함 | 읽지 못함 |
| `components/EditorToolbar.tsx:408` | label | KEEP | 글자 모양 | 글자 모양 |
| `components/EditorToolbar.tsx:409` | tooltip | KEEP | 선택한 곳이 없습니다 | 선택한 곳이 없습니다 |
| `components/EditorToolbar.tsx:417` | tooltip | MOVE-TO-DETAILS | 이 자리는 {name}(charPr {id}) 을 물려받는데, 서식 검사가 권하는 본문 모양은 {suggested}(charPr {id}) 입니다 | 본문은 {suggestedName}입니다. (charPr는 기술 정보) |
| `components/EditorToolbar.tsx:418` | label | MOVE-TO-DETAILS | 이 문서의 본문 모양은 charPr … 입니다 | 이 문서의 본문 모양은 글자 모양 … 입니다 |
| `components/EditorToolbar.tsx:422` | label | KEEP | 본문은 … | 본문은 … |
| `components/EditorToolbar.tsx:423` | label | KEEP | 본문과 다름 | 본문과 다름 |
| `components/EditorToolbar.tsx:441` | label | KEEP | 크기 | 크기 |
| `components/EditorToolbar.tsx:448` | tooltip | SHORTEN | 커서가 선 줄을 렌더러가 그린 크기입니다. 문서가 선언한 값이 아니라 지면에서 잰 값입니다. | 지면에서 잰 크기입니다. |
| `components/EditorToolbar.tsx:449` | label | KEEP | 이 문서가 본문 글자 모양에 선언한 크기입니다. | 이 문서가 본문 글자 모양에 선언한 크기입니다. |
| `components/EditorToolbar.tsx:454` | label | KEEP | 본문 기준 | 본문 기준 |
| `components/EditorToolbar.tsx:461` | aria | KEEP | 가운데 화면 모드 | 가운데 화면 모드 |
| `components/EditorToolbar.tsx:465` | tooltip | KEEP | 문서의 글과 표를 읽기 순서로 (Ctrl+1 은 화면 전환입니다) | 문서의 글과 표를 읽기 순서로 (Ctrl+1 은 화면 전환입니다) |
| `components/EditorToolbar.tsx:468` | label | KEEP | 본문 보기 | 본문 보기 |
| `components/EditorToolbar.tsx:476` | label | KEEP | 실제 페이지 그림 | 실제 페이지 그림 |
| `components/EditorToolbar.tsx:477` | tooltip | RENAME | 이 런타임에는 문서를 그림으로 그리는 방법이 아직 없습니다 | 이 엔진에는 페이지 그림이 없습니다 |
| `components/EditorToolbar.tsx:481` | label | KEEP | 페이지 보기 | 페이지 보기 |
| `components/EditorToolbar.tsx:491` | aria | KEEP | 문서 축소 | 문서 축소 |
| `components/EditorToolbar.tsx:500` | tooltip | KEEP | 100% 로 되돌립니다 | 100% 로 되돌립니다 |
| `components/EditorToolbar.tsx:507` | aria | KEEP | 문서 확대 | 문서 확대 |
| `components/EditorToolbar.tsx:520` | tooltip | KEEP | 아직 문서는 바뀌지 않았습니다 | 아직 문서는 바뀌지 않았습니다 |
| `components/EditorToolbar.tsx:521` | label | KEEP | 대기 {queued} | 대기 {queued} |
| `components/EditorToolbar.tsx:525` | tooltip | KEEP | 사람이 승인해야 다음으로 갑니다 | 사람이 승인해야 다음으로 갑니다 |
| `components/EditorToolbar.tsx:526` | label | KEEP | 승인 대기 | 승인 대기 |
| `components/EditorToolbar.tsx:531` | label | KEEP | 후보본 있음 | 후보본 있음 |
| `components/EditorToolbar.tsx:542` | label | KEEP | 화면 | 화면 |
| `components/EditorToolbar.tsx:546` | aria | KEEP | 화면 축소 | 화면 축소 |
| `components/EditorToolbar.tsx:556` | tooltip | KEEP | Ctrl+0 으로 되돌립니다 | Ctrl+0 으로 되돌립니다 |
| `components/EditorToolbar.tsx:564` | aria | KEEP | 화면 확대 | 화면 확대 |
| `components/EditorToolbar.tsx:572` | prose | MOVE-TO-TOOLTIP | 창 전체를 키웁니다. 문서만 키우려면 왼쪽의 문서 배율을 쓰십시오. Ctrl+= · Ctrl+− · Ctrl+0 | 창 전체를 키웁니다. |
| `components/PipelineStatus.tsx:27` | label | KEEP | 파이프라인 헤더를 읽지 못했습니다 | 파이프라인 헤더를 읽지 못했습니다 |
| `components/PipelineStatus.tsx:32` | tooltip | KEEP | 다시 읽기 | 다시 읽기 |
| `components/PipelineStatus.tsx:36` | label | KEEP | 다시 읽기 | 다시 읽기 |
| `components/PipelineStatus.tsx:51` | label | KEEP | {done}/{total} 단계 완료 | {done}/{total} 단계 완료 |
| `components/PipelineStatus.tsx:55` | label | KEEP | 없음 | 없음 |
| `components/PipelineStatus.tsx:66` | label | KEEP | 다시 읽기 | 다시 읽기 |
| `components/PipelineStatus.tsx:78` | prose | KEEP | 파이프라인 상태를 읽는 중입니다. | 파이프라인 상태를 읽는 중입니다. |
| `components/PipelineStatus.tsx:87` | label | KEEP | 다시 읽기 | 다시 읽기 |
| `components/PipelineStatus.tsx:96` | tooltip | KEEP | 보고서 작업 폴더가 아닙니다 | 보고서 작업 폴더가 아닙니다 |
| `components/PipelineStatus.tsx:97` | prose | SHORTEN | 이 문서 위쪽으로 PIPELINE.md가 없습니다. 보고서 워크스페이스를 열면 단계와 게이트가 여기에 펼쳐집니다. | 이 문서 위쪽으로 PIPELINE.md가 없습니다. 보고서 워크스페이스를… |
| `components/PipelineStatus.tsx:114` | label | KEEP | 다시 읽기 | 다시 읽기 |
| `components/VerificationBar.tsx:20` | tooltip | MOVE-TO-DETAILS | 페이지 그림은 보여줄 수 있어도 증거가 아닙니다. 런타임은 모든 렌더에 증명 없음(structural_only)을 붙입니다. | 페이지 그림은 증거가 아닙니다. |
| `components/VerificationBar.tsx:23` | prose | SHORTEN | 값을 넣도록 열린 칸입니다. 승인 전에는 파일이 바뀌지 않습니다. | 값을 넣도록 열린 칸입니다. |
| `components/VerificationBar.tsx:25` | prose | SHORTEN | 색·글꼴 등 서식 이상을 읽습니다. 제출용 검사가 아닙니다. | 색·글꼴 등 서식 이상을 읽습니다. |
| `components/VerificationBar.tsx:41` | label | KEEP | 연결된 양식 | 연결된 양식 |
| `components/VerificationBar.tsx:46` | tooltip | KEEP | 문서 자체 추정 | 문서 자체 추정 |
| `components/VerificationBar.tsx:52` | tooltip | SHORTEN | 서식 점검입니다. 색·글꼴 등 서식 이상을 읽습니다. 제출용 검사가 아니며, 페이지 그림은 증거가 아닙니다. | 서식 점검입니다. 제출용 검사가 아닙니다. |
| `components/VerificationBar.tsx:100` | label | KEEP | 검사 중 | 검사 중 |
| `components/VerificationBar.tsx:102` | label | KEEP | 주의 … | 주의 … |
| `components/VerificationBar.tsx:103` | label | KEEP | 검사 안 함 | 검사 안 함 |
| `components/VerificationBar.tsx:105` | label | KEEP | 실패 | 실패 |
| `components/VerificationBar.tsx:106` | label | KEEP | 실패 … | 실패 … |
| `components/VerificationBar.tsx:107` | label | KEEP | 일부 미실행 | 일부 미실행 |
| `components/VerificationBar.tsx:108` | label | KEEP | 주의 … | 주의 … |
| `components/VerificationBar.tsx:109` | label | KEEP | 통과 | 통과 |
| `components/VerificationBar.tsx:110` | label | KEEP | 실패 … | 실패 … |
| `components/VerificationBar.tsx:111` | label | KEEP | 주의 … | 주의 … |
| `components/VerificationBar.tsx:112` | label | KEEP | 통과 | 통과 |
| `components/VerificationBar.tsx:150` | label | KEEP | 선택 없음 | 선택 없음 |
| `components/VerificationBar.tsx:152` | label | KEEP | 표… (…,…) | 표… (…,…) |
| `components/VerificationBar.tsx:155` | label | SHORTEN | ? `문단 ${caret.atPara} · 덩어리 ${caret.run} · ${ | ? `문단 ${caret.atPara} · 덩어리 ${caret.run}… |
| `components/VerificationBar.tsx:156` | label | KEEP | 줄 앞 | 줄 앞 |
| `components/VerificationBar.tsx:158` | label | KEEP | 문단 … | 문단 … |
| `components/VerificationBar.tsx:159` | label | KEEP | 표… | 표… |
| `components/VerificationBar.tsx:170` | label | KEEP | 문서 없음 | 문서 없음 |
| `components/VerificationBar.tsx:182` | aria | KEEP | 닫기 | 닫기 |
| `components/VerificationBar.tsx:183` | tooltip | KEEP | 닫기 | 닫기 |
| `components/VerificationBar.tsx:189` | tooltip | KEEP | 문서 | 문서 |
| `components/VerificationBar.tsx:213` | prose | SHORTEN | 고른 곳의 주소입니다. 지금은 지면의 한 줄 안에 글자 단위 커서가 있습니다. | 고른 곳의 주소입니다. 지금은 지면의 한 줄 안에 글자 단위 커서가 있습… |
| `components/VerificationBar.tsx:214` | prose | SHORTEN | 고른 곳의 주소입니다. 커서가 놓인 줄이 없으면 칸 단위입니다. | 고른 곳의 주소입니다. |
| `components/VerificationBar.tsx:223` | label | KEEP | 입력 | 입력 |
| `components/VerificationBar.tsx:227` | label | SHORTEN | 지면의 줄 안에 커서가 있습니다. 이 편집기는 삽입만 하며 덮어쓰기 모드는 없습니다. | 지면의 줄 안에 커서가 있습니다. 이 편집기는 삽입만 하며 덮어쓰기 모드… |
| `components/VerificationBar.tsx:228` | prose | SHORTEN | 한글의 삽입/수정 표시에 해당하는 자리입니다. 커서가 놓인 줄이 없으면 표시하지 않습니다. | 한글의 삽입/수정 표시에 해당하는 자리입니다. 커서가 놓인 줄이 없으면… |
| `components/VerificationBar.tsx:232` | tooltip | KEEP | 글자 단위 커서가 열려 있습니다 | 글자 단위 커서가 열려 있습니다 |
| `components/VerificationBar.tsx:233` | label | KEEP | 삽입 | 삽입 |
| `components/VerificationBar.tsx:241` | label | KEEP | 지면 출처 | 지면 출처 |
| `components/VerificationBar.tsx:245` | label | SHORTEN | 이 지면은 자체 렌더러가 그렸습니다. 자리와 커서는 서식 스캔으로 같은 규칙에 따라 맞춘 것이고, 렌더러가 스스로 밝힌 주소는 그 스캔과 맞을 때만 확정으로 칩니다. 그림 자체는 검증되지 않았습니다. | 이 지면은 자체 렌더러가 그렸습니다. 자리와 커서는 서식 스캔으로 같은… |
| `components/VerificationBar.tsx:248` | label | KEEP | 본문 보기이거나 지면 좌표가 아직 없습니다. | 본문 보기이거나 지면 좌표가 아직 없습니다. |
| `components/VerificationBar.tsx:257` | label | KEEP | 한컴 PDF | 한컴 PDF |
| `components/VerificationBar.tsx:268` | label | KEEP | 지면 선택 | 지면 선택 |
| `components/VerificationBar.tsx:272` | prose | SHORTEN | 같은 글자를 가진 주소가 여럿입니다. 런타임도 이 앱도 그 중 하나를 고르지 않습니다. | 같은 글자를 가진 주소가 여럿입니다. 런타임도 이 앱도 그 중 하나를 고… |
| `components/VerificationBar.tsx:278` | label | SHORTEN | 이 줄은 주소가 잡혔지만, 고쳐 쓸 글 덩어리를 하나로 특정할 수 없어 커서를 놓지 않았습니다. | 이 줄은 주소가 잡혔지만, 고쳐 쓸 글 덩어리를 하나로 특정할 수 없어… |
| `components/VerificationBar.tsx:281` | label | KEEP | 지면에서 누른 곳이 가리키는 주소입니다. | 지면에서 누른 곳이 가리키는 주소입니다. |
| `components/VerificationBar.tsx:318` | tooltip | KEEP | 영수증을 엽니다 | 영수증을 엽니다 |
| `components/VerificationBar.tsx:324` | label | KEEP | 없음 | 없음 |
| `components/VerificationBar.tsx:331` | label | KEEP | {candidates.length}개 | {candidates.length}개 |
| `components/VerificationBar.tsx:338` | label | KEEP | 증명 없음 | 증명 없음 |
| `components/VerificationBar.tsx:343` | label | KEEP | 내보냄 | 내보냄 |
| `components/VerificationBar.tsx:346` | label | KEEP | 다시 열림 | 다시 열림 |
| `components/VerificationBar.tsx:351` | label | KEEP | 내보내기 | 내보내기 |
| `components/VerificationBar.tsx:354` | label | KEEP | 실패 | 실패 |
| `components/VerificationBar.tsx:358` | tooltip | KEEP | 검사 | 검사 |
| `components/VerificationBar.tsx:360` | label | KEEP | 적용 시 검사 | 적용 시 검사 |
| `components/VerificationBar.tsx:369` | label | KEEP | 실행 안 함 | 실행 안 함 |
| `components/VerificationBar.tsx:371` | label | KEEP | 일부 미실행 | 일부 미실행 |
| `components/VerificationBar.tsx:373` | label | KEEP | 적용 시 검사 통과 | 적용 시 검사 통과 |
| `components/VerificationBar.tsx:375` | label | KEEP | 적용 시 검사 걸림 | 적용 시 검사 걸림 |
| `components/VerificationBar.tsx:380` | label | KEEP | 대상 | 대상 |
| `components/VerificationBar.tsx:390` | label | KEEP | 실행 시각 | 실행 시각 |
| `components/VerificationBar.tsx:392` | tooltip | MOVE-TO-DETAILS | candidate/verify 가 검사를 끝낸 시각입니다. | candidate/verify 가 검사를 끝낸 시각입니다. |
| `components/VerificationBar.tsx:401` | label | KEEP | 검토 대기 | 검토 대기 |
| `components/VerificationBar.tsx:403` | tooltip | SHORTEN | 승인을 기다리는 작업. 아직 문서는 바뀌지 않았습니다. | 승인을 기다리는 작업. 아직 문서는 바뀌지 않았습니다. |
| `components/VerificationBar.tsx:419` | label | KEEP | 서식 점검 | 서식 점검 |
| `components/VerificationBar.tsx:421` | tooltip | KEEP | … 마지막 검사 … | … 마지막 검사 … |
| `components/VerificationBar.tsx:424` | label | KEEP | 읽는 중 | 읽는 중 |
| `components/VerificationBar.tsx:429` | label | KEEP | 미실행 | 미실행 |
| `components/VerificationBar.tsx:436` | label | KEEP | 걸림 없음 | 걸림 없음 |
| `components/VerificationBar.tsx:448` | label | KEEP | 끊김 | 끊김 |
| `components/VerificationBar.tsx:450` | label | KEEP | 준비 중 | 준비 중 |
| `components/VerificationBar.tsx:453` | label | KEEP | 개발 | 개발 |
| `components/VerificationBar.tsx:459` | label | KEEP | 종료 시 정리 | 종료 시 정리 |
| `components/VerificationBar.tsx:462` | label | KEEP | 보장됨 | 보장됨 |
| `components/VerificationBar.tsx:464` | label | KEEP | 실패 | 실패 |
| `components/VerificationBar.tsx:466` | label | KEEP | 확인 안 됨 | 확인 안 됨 |
| `components/VerificationBar.tsx:480` | label | KEEP | 영수증 보기 | 영수증 보기 |
| `components/VerificationBar.tsx:489` | label | KEEP | 내보내기 | 내보내기 |
| `components/VerificationBar.tsx:500` | label | KEEP | 내보낸 파일 열어 확인 | 내보낸 파일 열어 확인 |
| `components/VerificationBar.tsx:509` | label | KEEP | 결과 보기 | 결과 보기 |
| `components/VerificationBar.tsx:518` | label | KEEP | 검사 중… | 검사 중… |
| `components/VerificationBar.tsx:532` | label | KEEP | 끊김 | 끊김 |
| `components/VerificationBar.tsx:562` | label | KEEP | 끊김 | 끊김 |
| `pipelineStatus.ts:88` | label | KEEP | 없음 | 없음 |
| `pipelineStatus.ts:89` | label | KEEP | 자동 승인 | 자동 승인 |
| `pipelineStatus.ts:90` | label | KEEP | 승인 | 승인 |
| `pipelineStatus.ts:91` | label | KEEP | 대기 | 대기 |
| `pipelineStatus.ts:92` | label | KEEP | 거절 | 거절 |
| `pipelineStatus.ts:93` | label | KEEP | 없음 | 없음 |
| `pipelineStatus.ts:108` | label | KEEP | 없음 | 없음 |
| `pipelineStatus.ts:111` | label | KEEP | … · … · …/… 단계 완료 · 다음 게이트 … | … · … · …/… 단계 완료 · 다음 게이트 … |

## tree

Honesty (once): 입력 칸만 고칩니다. 금지는 기술 정보에 둡니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `components/SessionList.tsx:39` | tooltip | KEEP | 연 문서가 없습니다 | 연 문서가 없습니다 |
| `components/SessionList.tsx:40` | prose | KEEP | 문서를 열면 이 목록에 나타납니다. | 문서를 열면 이 목록에 나타납니다. |
| `components/SessionList.tsx:62` | label | KEEP | 문서 열기 | 문서 열기 |
| `components/SessionList.tsx:68` | tooltip | SHORTEN | 빈 양식이나 form_profile.json을 연결해 엽니다 | 빈 양식을 연결해 엽니다. |
| `components/SessionList.tsx:73` | label | KEEP | 양식 연결 | 양식 연결 |
| `components/SessionList.tsx:78` | label | KEEP | 작업 폴더 | 작업 폴더 |
| `components/SessionList.tsx:83` | label | KEEP | 연 문서는 이 폴더에 남습니다. 앱을 닫았다 열면 여기서 다시 찾습니다. | 연 문서는 이 폴더에 남습니다. 앱을 닫았다 열면 여기서 다시 찾습니다. |
| `components/SessionList.tsx:92` | aria | KEEP | 문서 목록 | 문서 목록 |
| `components/SessionList.tsx:94` | label | KEEP | 문서 | 문서 |
| `components/StructureTree.tsx:120` | label | KEEP | 금지 | 금지 |
| `components/StructureTree.tsx:128` | label | KEEP | (앵커) | (앵커) |
| `components/StructureTree.tsx:130` | label | KEEP | 주소 없음 | 주소 없음 |
| `components/StructureTree.tsx:135` | label | KEEP | 금지 | 금지 |
| `components/StructureTree.tsx:143` | label | KEEP | (자리표시) | (자리표시) |
| `components/StructureTree.tsx:146` | label | KEEP | 자리표시 | 자리표시 |
| `components/StructureTree.tsx:154` | label | KEEP | (제거 대상) | (제거 대상) |
| `components/StructureTree.tsx:161` | label | KEEP | 제거 대상 | 제거 대상 |
| `components/StructureTree.tsx:205` | label | KEEP | … 연산 …종 | … 연산 …종 |
| `components/StructureTree.tsx:206` | label | KEEP | 이 빌드에서 사용할 수 없습니다. | 이 빌드에서 사용할 수 없습니다. |
| `components/StructureTree.tsx:211` | label | KEEP | 선언되어 있으나 이 빌드에는 구현이 없습니다. | 선언되어 있으나 이 빌드에는 구현이 없습니다. |
| `components/StructureTree.tsx:222` | aria | KEEP | 문서 구조 | 문서 구조 |
| `components/StructureTree.tsx:233` | label | KEEP | 문단 … | 문단 … |
| `components/StructureTree.tsx:243` | label | KEEP | (빈 문단) | (빈 문단) |
| `components/StructureTree.tsx:255` | label | KEEP | 표 | 표 |
| `components/StructureTree.tsx:267` | label | KEEP | 표 … | 표 … |
| `components/StructureTree.tsx:268` | label | KEEP | …칸 · 채움 … | …칸 · 채움 … |
| `components/StructureTree.tsx:295` | label | KEEP | 색 이상 | 색 이상 |
| `components/StructureTree.tsx:296` | label | KEEP | 글자속성 이상 | 글자속성 이상 |
| `components/StructureTree.tsx:311` | label | KEEP | 입력 칸 | 입력 칸 |
| `components/StructureTree.tsx:317` | label | RENAME | 표 … R…C… | 표 … · …행 …열 |
| `components/StructureTree.tsx:318` | label | KEEP | 문단 … | 문단 … |
| `components/StructureTree.tsx:341` | label | KEEP | 색 이상 | 색 이상 |
| `components/StructureTree.tsx:343` | label | KEEP | 글자속성 이상 | 글자속성 이상 |
| `components/StructureTree.tsx:345` | label | KEEP | 채움 | 채움 |
| `components/StructureTree.tsx:358` | label | MOVE-TO-DETAILS | 프로토콜 문서와 MCP include 열거는 summary, graph, regions 뿐이고, 런타임 | 금지 구역은 이 응답에 없습니다. |
| `components/StructureTree.tsx:359` | label | SHORTEN | 코어·CLI는 선택적으로 금지 목록을 내놓을 수 있습니다. 칸이 없으면 앵커를 | 코어·CLI는 선택적으로 금지 목록을 내놓을 수 있습니다. 칸이 없으면… |
| `components/StructureTree.tsx:360` | prose | DROP | 만들지 않으며, 채움 자리만 편집 가능으로 표시합니다. | — (앞 줄과 한 문장) |
| `components/StructureTree.tsx:368` | label | KEEP | 안내문 | 안내문 |
| `components/StructureTree.tsx:376` | label | KEEP | (미리보기 없음) | (미리보기 없음) |
| `components/StructureTree.tsx:377` | label | RENAME | 표 … R…C… | 표 … · …행 …열 |
| `components/StructureTree.tsx:387` | label | KEEP | 이 빌드에서 불가 | 이 빌드에서 불가 |
| `components/StructureTree.tsx:391` | prose | KEEP | 런타임이 아직 능력 목록을 보내지 않았습니다. | 런타임이 아직 능력 목록을 보내지 않았습니다. |
| `components/StructureTree.tsx:400` | label | KEEP | 불가 | 불가 |
| `components/StructureTree.tsx:406` | label | SHORTEN | 런타임은 해석하지 못한 구조를 따로 알려 주지 않습니다. 위 목록은 이 빌드가 다룰 수 | 해석하지 못한 구조를 따로 알려 주지 않습니다. 위 목록은 다룰 수 |
| `components/StructureTree.tsx:407` | prose | DROP | 없는 것이지, 이 문서에 그런 구조가 없다는 뜻은 아닙니다. | — (앞 줄과 한 문장) |
| `components/TaskPacks.tsx:54` | prose | SHORTEN | 주제에서 제출본까지를 단계로 나눠 진행하고, 단계마다 아래 검사기를 게이트로 겁니다. 이 앱이 지금 돌릴 수 있는 것은 문서를 대상으로 하는 검사기뿐입니다. | 주제에서 제출본까지를 단계로 나눠 진행하고, 단계마다 |
| `components/TaskPacks.tsx:55` | label | KEEP | 공문 서식의 필수 항목과 표기 규칙을 채움 자리 검사에 얹습니다. | 공문 서식의 필수 항목과 표기 규칙을 채움 자리 검사에 얹습니다. |
| `components/TaskPacks.tsx:56` | label | KEEP | 지원 사업 양식의 분량 제한과 항목 누락을 제출 전에 잡습니다. | 지원 사업 양식의 분량 제한과 항목 누락을 제출 전에 잡습니다. |
| `components/TaskPacks.tsx:57` | label | KEEP | 인사 서식의 항목·표기 규칙을 검사에 얹습니다. | 인사 서식의 항목·표기 규칙을 검사에 얹습니다. |
| `components/TaskPacks.tsx:58` | label | KEEP | 민원 회신문의 구조와 어투를 검사에 얹습니다. | 민원 회신문의 구조와 어투를 검사에 얹습니다. |
| `components/TaskPacks.tsx:59` | label | KEEP | 본문 문체를 검사하고, 번역투를 걷어내는 윤문을 겁니다. | 본문 문체를 검사하고, 번역투를 걷어내는 윤문을 겁니다. |
| `components/TaskPacks.tsx:72` | prose | SHORTEN | 보고서 작업 폴더를 대상으로 하는 검사기입니다. 세션이 들고 있는 것은 문서 한 개라서, 돌리지 않고 건너뛰었습니다. | 보고서 작업 폴더를 대상으로 하는 검사기입니다. 세션이 들고 있는 것은… |
| `components/TaskPacks.tsx:74` | label | SHORTEN | 이 검사기는 무엇을 받는지 선언에 적혀 있지 않습니다. 문서를 넘겨도 되는지 알 수 없어 건너뛰었습니다. | 이 검사기는 무엇을 받는지 선언에 적혀 있지 않습니다. 문서를 넘겨도 되… |
| `components/TaskPacks.tsx:75` | label | KEEP | 검사기를 실행조차 하지 못했습니다. | 검사기를 실행조차 하지 못했습니다. |
| `components/TaskPacks.tsx:76` | label | KEEP | 제한 시간을 넘겨 강제로 끊었습니다. | 제한 시간을 넘겨 강제로 끊었습니다. |
| `components/TaskPacks.tsx:77` | label | KEEP | 이 기계에 없는 것을 불러오다 죽었습니다. | 이 기계에 없는 것을 불러오다 죽었습니다. |
| `components/TaskPacks.tsx:78` | label | KEEP | 검사기를 잘못된 방식으로 불렀습니다. | 검사기를 잘못된 방식으로 불렀습니다. |
| `components/TaskPacks.tsx:79` | label | KEEP | 실행은 됐지만 판정으로 읽을 만한 것을 내놓지 않았습니다. | 실행은 됐지만 판정으로 읽을 만한 것을 내놓지 않았습니다. |
| `components/TaskPacks.tsx:83` | label | KEEP | 막힘 | 막힘 |
| `components/TaskPacks.tsx:84` | label | KEEP | 주의 | 주의 |
| `components/TaskPacks.tsx:85` | label | KEEP | 판정 안 함 | 판정 안 함 |
| `components/TaskPacks.tsx:96` | label | KEEP | 표… (…,…) | 표… (…,…) |
| `components/TaskPacks.tsx:98` | label | KEEP | 문단 … | 문단 … |
| `components/TaskPacks.tsx:99` | label | KEEP | 주소 없음 | 주소 없음 |
| `components/TaskPacks.tsx:118` | tooltip | KEEP | 본문 보기에서 이 자리로 갑니다 | 본문 보기에서 이 자리로 갑니다 |
| `components/TaskPacks.tsx:124` | tooltip | KEEP | 런타임이 이 자리를 주소로 옮기지 못했습니다 | 런타임이 이 자리를 주소로 옮기지 못했습니다 |
| `components/TaskPacks.tsx:145` | tooltip | KEEP | 검사기가 내놓은 판정: … | 검사기가 내놓은 판정: … |
| `components/TaskPacks.tsx:151` | label | KEEP | 건너뜀 | 건너뜀 |
| `components/TaskPacks.tsx:158` | tooltip | KEEP | 선언한 입력 중 받지 못한 것: … | 선언한 입력 중 받지 못한 것: … |
| `components/TaskPacks.tsx:159` | label | KEEP | 입력 부족 | 입력 부족 |
| `components/TaskPacks.tsx:166` | label | RENAME | 런타임이 … 로 넘겼습니다. | 엔진이 … 로 넘겼습니다. |
| `components/TaskPacks.tsx:174` | label | DROP | 양식을 넘겨줄 수 없었고, 그래서 이 판정은 완전하지 않습니다. | — (앞 줄과 한 문장) |
| `components/TaskPacks.tsx:195` | label | KEEP | 통과 | 통과 |
| `components/TaskPacks.tsx:198` | label | SHORTEN | 검사기 {counts.selected} · 돌았음 {counts.ran} · 건너뜀 {counts.skipped} · 실행 못 함{" "} | 검사기 {counts.selected} · 돌았음 {counts.ran}… |
| `components/TaskPacks.tsx:214` | label | KEEP | 원본도 세션 사본도 검사기에 넘어가지 않습니다. | 원본도 세션 사본도 검사기에 넘어가지 않습니다. |
| `components/TaskPacks.tsx:239` | prose | SHORTEN | 이 팩은 켜져 있지 않습니다. 켜는 것은 enabled.yaml 에 적는 설치 시점의 일이고, 앱에서 할 수 있는 일이 아닙니다. | 이 팩은 켜져 있지 않습니다. 켜는 것은 enabled.yaml 에 적는… |
| `components/TaskPacks.tsx:241` | label | KEEP | 검사할 문서를 먼저 여십시오. | 검사할 문서를 먼저 여십시오. |
| `components/TaskPacks.tsx:242` | label | SHORTEN | 이 팩의 검사기를 지금 열려 있는 문서에 대해 돌립니다. 문서는 바뀌지 않습니다. | 이 팩의 검사기를 지금 열려 있는 문서에 대해 돌립니다. 문서는 바뀌지… |
| `components/TaskPacks.tsx:246` | label | KEEP | 실행 | 실행 |
| `components/TaskPacks.tsx:250` | label | KEEP | 꺼져 있는 팩은 아무도 돌릴 수 없습니다 | 꺼져 있는 팩은 아무도 돌릴 수 없습니다 |
| `components/TaskPacks.tsx:252` | label | KEEP | 문서를 열면 돌릴 수 있습니다 | 문서를 열면 돌릴 수 있습니다 |
| `components/TaskPacks.tsx:253` | prose | SHORTEN | 문서를 읽기만 합니다. 계획도 승인도 만들지 않습니다 | 문서를 읽기만 합니다. |
| `components/TaskPacks.tsx:260` | label | KEEP | 검사를 돌리지 못했습니다 | 검사를 돌리지 못했습니다 |
| `components/TaskPacks.tsx:280` | label | KEEP | 켜짐 | 켜짐 |
| `components/TaskPacks.tsx:284` | label | KEEP | 지금 이 설치본에 실제로 있는 것 | 지금 이 설치본에 실제로 있는 것 |
| `components/TaskPacks.tsx:287` | label | KEEP | 선언 상태:{" "} | 선언 상태:{" "} |
| `components/TaskPacks.tsx:290` | label | KEEP | 켜짐 | 켜짐 |
| `components/TaskPacks.tsx:294` | label | KEEP | 꺼짐 | 꺼짐 |
| `components/TaskPacks.tsx:302` | label | KEEP | 읽은 값이 다름 | 읽은 값이 다름 |
| `components/TaskPacks.tsx:303` | label | KEEP | 켜짐 | 켜짐 |
| `components/TaskPacks.tsx:304` | label | KEEP | 켜짐 | 켜짐 |
| `components/TaskPacks.tsx:305` | label | RENAME | 런타임 쪽을 따릅니다 | 엔진 쪽을 따릅니다 |
| `components/TaskPacks.tsx:311` | label | KEEP | — 그 팩이 꺼져 있으면 이 팩도 켜지지 않습니다 | — 그 팩이 꺼져 있으면 이 팩도 켜지지 않습니다 |
| `components/TaskPacks.tsx:315` | label | KEEP | 검사기 {pack.checkers.length}개 | 검사기 {pack.checkers.length}개 |
| `components/TaskPacks.tsx:321` | label | KEEP | 명령 {pack.cli.length}개 | 명령 {pack.cli.length}개 |
| `components/TaskPacks.tsx:328` | label | KEEP | 검사 | 검사 |
| `components/TaskPacks.tsx:331` | label | KEEP | 아직 없는 것 | 아직 없는 것 |
| `components/TaskPacks.tsx:333` | label | SHORTEN | 보고서 작업 폴더를 대상으로 하는 검사기는 여기서 돌릴 수 없습니다. 런타임에 작업 폴더라는 | 보고서 작업 폴더를 대상으로 하는 검사기는 여기서 돌릴 수 없습니다. 작… |
| `components/TaskPacks.tsx:334` | prose | SHORTEN | 개념 자체가 없어서, 문서 세션에 대고 부르면 건너뛰었다고 답합니다 — 통과가 아닙니다. | 개념 자체가 없어서, 문서 세션에 대고 부르면 건너뛰었다고 답합니다 |
| `components/TaskPacks.tsx:336` | label | KEEP | 고르는 방법도 아직 없어, 검사기는 각자의 기본값으로 돕니다. | 고르는 방법도 아직 없어, 검사기는 각자의 기본값으로 돕니다. |
| `components/TaskPacks.tsx:339` | label | KEEP | 닫기 | 닫기 |
| `components/TaskPacks.tsx:354` | label | KEEP | 작업 팩{" "} | 작업 팩{" "} |
| `components/TaskPacks.tsx:359` | prose | KEEP | 읽는 중입니다. | 읽는 중입니다. |
| `components/TaskPacks.tsx:362` | label | KEEP | 작업 팩 목록을 읽지 못했습니다. | 작업 팩 목록을 읽지 못했습니다. |
| `components/TaskPacks.tsx:376` | label | KEEP | · 꺼짐 | · 꺼짐 |
| `components/TaskPacks.tsx:389` | prose | SHORTEN | 것입니다. 켜져 있는 팩만 돌릴 수 있고, 켜는 것은 설치 시점의 일입니다. | 것입니다. 켜져 있는 팩만 돌릴 수 있고, 켜는 것은 설치 시점의 일입니다. |
| `views/DocumentView.tsx:39` | prose | MOVE-TO-TOOLTIP | 본문 보기 — 채움 자리를 눌러 값을 넣습니다. 승인 전에는 문서가 바뀌지 않습니다 | 승인 전에는 문서가 바뀌지 않습니다. |
| `views/DocumentView.tsx:40` | prose | MOVE-TO-TOOLTIP | 페이지 보기 — 실제로 그려진 지면입니다. 그림은 증거가 아닙니다 | 페이지 그림은 증거가 아닙니다. |
| `views/DocumentView.tsx:61` | label | KEEP | 문단 … · 표 … · 입력 칸 … | 문단 … · 표 … · 입력 칸 … |
| `views/DocumentView.tsx:62` | label | KEEP | 구조 | 구조 |
| `views/DocumentView.tsx:80` | aria | KEEP | 문서 구조 | 문서 구조 |
| `views/DocumentView.tsx:91` | aria | KEEP | 구조 레일 펼치기 | 구조 레일 펼치기 |
| `views/DocumentView.tsx:106` | label | KEEP | 구조 | 구조 |
| `views/DocumentView.tsx:108` | label | KEEP | …문단 · …표 | …문단 · …표 |
| `views/DocumentView.tsx:114` | tooltip | KEEP | 구조 레일 접기 (Ctrl+B) | 구조 레일 접기 (Ctrl+B) |
| `views/DocumentView.tsx:115` | aria | KEEP | 구조 레일 접기 | 구조 레일 접기 |
| `views/DocumentView.tsx:123` | prose | SHORTEN | 문서를 읽는 중입니다. 서식을 뜯어보는 데 몇 초 걸립니다. | 문서를 읽는 중입니다. |
| `views/DocumentView.tsx:126` | label | KEEP | 문서를 다시 읽지 못했습니다 | 문서를 다시 읽지 못했습니다 |
| `views/DocumentView.tsx:132` | prose | SHORTEN | 문서를 열면 구역, 표, 채움 자리가 여기에 펼쳐집니다. | 문서를 열면 구조가 여기에 나타납니다. |
| `views/DocumentView.tsx:136` | label | KEEP | 파이프라인 | 파이프라인 |
| `views/DocumentView.tsx:140` | label | KEEP | 문서 / 작업 팩 | 문서 / 작업 팩 |
| `views/DocumentView.tsx:151` | aria | KEEP | 문서 | 문서 |
| `components/TaskPacks.tsx:147` | label | RENAME | pass / fail (검사기 판정 원문) | 통과 / 실패 |

## document

Honesty (once): 승인 전에는 문서가 바뀌지 않습니다. 페이지 그림은 증거가 아닙니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `actions.ts:866` | toast | KEEP | 이 칸은 값을 넣는 자리가 아닙니다 | 이 칸은 값을 넣는 자리가 아닙니다 |
| `actions.ts:897` | label | KEEP | 이 줄에는 문단 주소가 없습니다 | 이 줄에는 문단 주소가 없습니다 |
| `actions.ts:899` | label | SHORTEN | 이 줄의 글이 여러 덩어리에 같이 들어 있어 어느 덩어리인지 고를 수 없습니다 | 이 줄의 글이 여러 덩어리에 같이 들어 있어 어느 덩어리인지 고를 수 없… |
| `actions.ts:901` | label | KEEP | 이 줄의 글을 한 덩어리 안에서 한곳으로 짚을 수 없습니다 | 이 줄의 글을 한 덩어리 안에서 한곳으로 짚을 수 없습니다 |
| `actions.ts:902` | label | KEEP | 런타임이 이 문단의 글 덩어리 목록을 돌려주지 못했습니다 | 런타임이 이 문단의 글 덩어리 목록을 돌려주지 못했습니다 |
| `actions.ts:904` | label | KEEP | 표시 중인 문서와 읽은 문서가 다릅니다. 이 줄에는 커서를 놓지 않습니다 | 표시 중인 문서와 읽은 문서가 다릅니다. 이 줄에는 커서를 놓지 않습니다 |
| `actions.ts:906` | label | KEEP | 이 고침은 여러 글 덩어리에 걸쳐 있습니다. 문단을 하나로 합치지 않습니다 | 이 고침은 여러 글 덩어리에 걸쳐 있습니다. 문단을 하나로 합치지 않습니다 |
| `actions.ts:1018` | label | KEEP | · 글자별 위치가 없어 줄 앞에 커서를 놓음 | · 글자별 위치가 없어 줄 앞에 커서를 놓음 |
| `actions.ts:1436` | label | KEEP | 이 후보본에는 되돌릴 방법이 없는 작업이 있습니다: | 이 후보본에는 되돌릴 방법이 없는 작업이 있습니다: |
| `actions.ts:1483` | label | KEEP | 되돌릴 이전 값을 런타임이 돌려주지 못한 자리가 있습니다. | 되돌릴 이전 값을 런타임이 돌려주지 못한 자리가 있습니다. |
| `actions.ts:1484` | label | KEEP | 빈 값으로 짐작해서 덮어쓰지 않습니다. | 빈 값으로 짐작해서 덮어쓰지 않습니다. |
| `actions.ts:1685` | error | KEEP | 같은 후보본끼리는 비교하지 않습니다. | 같은 후보본끼리는 비교하지 않습니다. |
| `actions.ts:2201` | tooltip | KEEP | 후보본 내보내기 | 후보본 내보내기 |
| `actions.ts:2225` | prose | SHORTEN | 내보낸 파일의 해시가 후보본과 다릅니다. 이 파일을 제출하지 마십시오. | 내보낸 파일의 해시가 후보본과 다릅니다. 이 파일을 제출하지 마십시오. |
| `actions.ts:2232` | toast | KEEP | 후보본과 영수증을 내보냈습니다 | 후보본과 영수증을 내보냈습니다 |
| `actions.ts:2434` | label | KEEP | 표… (…,…) | 표… (…,…) |
| `actions.ts:2437` | label | KEEP | 문단 … | 문단 … |
| `actions.ts:2439` | label | KEEP | 주소 없음 | 주소 없음 |
| `actions.ts:2474` | label | KEEP | … — 값을 넣는 자리가 아닙니다 | … — 값을 넣는 자리가 아닙니다 |
| `actions.ts:2498` | label | KEEP | 그려진 선으로 잡음 | 그려진 선으로 잡음 |
| `actions.ts:2502` | label | KEEP | 이름표에서 미루어 잡음 | 이름표에서 미루어 잡음 |
| `actions.ts:2541` | label | KEEP | 후보 …개 — 직접 선택 | 후보 …개 — 직접 선택 |
| `actions.ts:2568` | label | KEEP | …번째 줄 — 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다 | …번째 줄 — 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다 |
| `actions.ts:2603` | label | KEEP | … — 값을 넣는 자리가 아닙니다 | … — 값을 넣는 자리가 아닙니다 |
| `actions.ts:2673` | label | KEEP | … — 값을 넣는 자리가 아닙니다 | … — 값을 넣는 자리가 아닙니다 |
| `actions.ts:2683` | label | KEEP | … — 사용자가 고름 | … — 사용자가 고름 |
| `actions.ts:2725` | label | KEEP | … PDF를 만들었습니다 · … | … PDF를 만들었습니다 · … |
| `actions.ts:2726` | label | KEEP | 이미 준비되어 있습니다 | 이미 준비되어 있습니다 |
| `actions.ts:2925` | error | KEEP | 에이전트가 JSON을 내놓지 않았습니다. | 에이전트가 JSON을 내놓지 않았습니다. |
| `actions.ts:3062` | label | KEEP | 표 … R…C… | 표 … R…C… |
| `actions.ts:3099` | label | KEEP | 표 … R…C… #… | 표 … R…C… #… |
| `actions.ts:3100` | label | KEEP | 문단 … #… | 문단 … #… |
| `actions.ts:3111` | error | KEEP | 본문 기준과 다른 색(…)으로 쓰인 글이 있습니다: "…" | 본문 기준과 다른 색(…)으로 쓰인 글이 있습니다: "…" |
| `actions.ts:3117` | label | KEEP | 표 … R…C… | 표 … R…C… |
| `actions.ts:3188` | label | KEEP | 표 … R…C… | 표 … R…C… |
| `actions.ts:3192` | label | KEEP | 문단 … | 문단 … |
| `actions.ts:3196` | toast | KEEP | 복사할 글이 없습니다 | 복사할 글이 없습니다 |
| `actions.ts:3200` | toast | KEEP | … 복사됨 | … 복사됨 |
| `actions.ts:3267` | label | RENAME | 런타임을 시작하는 중 | 엔진을 시작하는 중 |
| `actions.ts:3284` | label | KEEP | 능력을 확인하는 중 | 능력을 확인하는 중 |
| `actions.ts:3327` | label | RENAME | 런타임을 다시 시작하는 중 | 엔진을 다시 시작하는 중 |
| `actions.ts:3552` | label | KEEP | 에이전트 작업이 덮어쓸 현재 값을 런타임이 돌려주지 못했습니다. | 에이전트 작업이 덮어쓸 현재 값을 런타임이 돌려주지 못했습니다. |
| `actions.ts:3677` | error | KEEP | 사람이 중간에 멈췄습니다. | 사람이 중간에 멈췄습니다. |
| `components/PageOverlay.tsx:101` | label | KEEP | 이 칸의 글자가 지면에서 그대로 발견된 자리입니다. | 이 칸의 글자가 지면에서 그대로 발견된 자리입니다. |
| `components/PageOverlay.tsx:102` | label | KEEP | 지면에 실제로 그려진 선을 따라 잡은 자리입니다. | 지면에 실제로 그려진 선을 따라 잡은 자리입니다. |
| `components/PageOverlay.tsx:103` | prose | SHORTEN | 같은 줄의 이름표에서 미루어 잡은 자리입니다. 선이 그려져 있지 않아 위치가 정확하지 않을 수 있습니다. | 같은 줄의 이름표에서 미루어 잡은 자리입니다. 선이 그려져 있지 않아 위… |
| `components/PageOverlay.tsx:165` | label | KEEP | 런타임이 이 자리를 어떻게 잡았는지 알 수 없습니다. | 런타임이 이 자리를 어떻게 잡았는지 알 수 없습니다. |
| `components/PageOverlay.tsx:166` | label | KEEP | / 후보본과 다름 — 이 그림은 원본 기준입니다 | / 후보본과 다름 — 이 그림은 원본 기준입니다 |
| `components/PageOverlay.tsx:169` | label | KEEP | 표… …행 …열 — 빈 자리, 눌러서 값 넣기 | 표… …행 …열 — 빈 자리, 눌러서 값 넣기 |
| `components/PageOverlay.tsx:170` | label | KEEP | 표… …행 …열 — 값을 넣는 자리가 아님 | 표… …행 …열 — 값을 넣는 자리가 아님 |
| `components/PageOverlay.tsx:229` | label | SHORTEN | 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다. 자체 렌더러는 어디서 그렸는지 알지만, 서식 스캔이 확인해 주지 않은 주소는 쓰지 않습니다. | 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다. 자체 렌더러는… |
| `components/PageOverlay.tsx:230` | label | KEEP | 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다. | 이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다. |
| `components/PageOverlay.tsx:299` | prose | SHORTEN | “…” — 같은 글자를 가진 주소가 …개입니다. 어느 것인지 런타임은 고르지 않습니다. | “…” — 같은 글자를 가진 주소가 …개입니다. 어느 것인지 고르지 않습… |
| `components/PageOverlay.tsx:302` | label | KEEP | / 이 줄은 글자별 위치가 없어 줄 앞으로 붙습니다. | / 이 줄은 글자별 위치가 없어 줄 앞으로 붙습니다. |
| `components/PageOverlay.tsx:305` | label | KEEP | …… | …… |
| `components/PageOverlay.tsx:362` | label | KEEP | 런타임은 이 중 하나를 고르지 않습니다 | 런타임은 이 중 하나를 고르지 않습니다 |
| `components/PageOverlay.tsx:365` | prose | SHORTEN | 같은 글자가 여러 주소에 있습니다. 어느 자리를 편집할지는 사람이 정합니다. 지금까지 | 같은 글자가 여러 주소에 있습니다. 어느 자리를 편집할지는 사람이 정합니… |
| `components/PageOverlay.tsx:366` | label | KEEP | 대기열에 올라간 것은 없습니다. | 대기열에 올라간 것은 없습니다. |
| `components/PageOverlay.tsx:399` | tooltip | SHORTEN | 자체 렌더러는 이 줄을 여기서 그렸다고 말합니다. 서식 스캔이 확인해 주지 않았으므로 자동으로 고르지는 않습니다. | 자체 렌더러는 이 줄을 여기서 그렸다고 말합니다. 서식 스캔이 확인해 주… |
| `components/PageOverlay.tsx:401` | label | KEEP | 렌더러 지목 | 렌더러 지목 |
| `components/PageOverlay.tsx:408` | tooltip | SHORTEN | 이 문단 줄에 커서를 놓습니다. 줄 앞에서 시작합니다. | 이 문단 줄에 커서를 놓습니다. 줄 앞에서 시작합니다. |
| `components/PageOverlay.tsx:409` | label | KEEP | 문단 줄 | 문단 줄 |
| `components/PageOverlay.tsx:412` | label | KEEP | 값 자리 아님 | 값 자리 아님 |
| `components/PageOverlay.tsx:420` | label | KEEP | 닫기 | 닫기 |
| `components/PageOverlay.tsx:448` | label | KEEP | 대응 없음 | 대응 없음 |
| `components/PageOverlay.tsx:450` | label | SHORTEN | 이 문서에는 대응시킬 서식 정보가 없어, 글자 위치는 있지만 주소가 없습니다. | 이 문서에는 대응시킬 서식 정보가 없어, 글자 위치는 있지만 주소가 없습… |
| `components/PageOverlay.tsx:458` | label | KEEP | 편집 가능 {editableSeats + editableSpans} | 편집 가능 {editableSeats + editableSpans} |
| `components/PageOverlay.tsx:461` | label | SHORTEN | 확정 {mapping.unique ?? 0} · 후보 {mapping.ambiguous ?? 0} · 대응 없음{" "} | 확정 {mapping.unique ?? 0} · 후보 {mapping.a… |
| `components/PageOverlay.tsx:462` | label | SHORTEN | {mapping.unmapped ?? 0} · 자리 {seats.length} | {mapping.unmapped ?? 0} · 자리 {seats.leng… |
| `components/PageOverlay.tsx:466` | label | SHORTEN | person sees that the knowledge was CHECKED rather than taken: 확인 | person sees that the knowledge was CHECK… |
| `components/PageOverlay.tsx:467` | label | SHORTEN | means both witnesses said the same thing, 불일치 means neither was | means both witnesses said the same thing… |
| `components/PageOverlay.tsx:468` | label | SHORTEN | used, 미확인 means the renderer knew and was not believed. */} | used, 미확인 means the renderer knew and wa… |
| `components/PageOverlay.tsx:473` | tooltip | SHORTEN | 자체 렌더러가 스스로 밝힌 주소를 서식 스캔과 대조한 결과입니다. 렌더러 말만으로 주소를 정하지는 않습니다. | 자체 렌더러가 스스로 밝힌 주소를 서식 스캔과 대조한 결과입니다. 렌더러… |
| `components/PageOverlay.tsx:475` | label | SHORTEN | 렌더러 대조 — 확인 {mapping.crossCheck.agree ?? 0} · 불일치{" "} | 렌더러 대조 — 확인 {mapping.crossCheck.agree ??… |
| `components/PageOverlay.tsx:476` | label | SHORTEN | {mapping.crossCheck.disagree ?? 0} · 미확인 {mapping.crossCheck.sidecarOnly ?? 0} | {mapping.crossCheck.disagree ?? 0} · 미확인… |
| `components/PageOverlay.tsx:481` | label | SHORTEN | 이 쪽에서 런타임이 값을 넣을 자리를 잡아 주지 못했습니다. 그런 자리는 본문 보기에서 | 이 쪽에서 값을 넣을 자리를 잡아 주지 못했습니다. 그런 자리는 본문 보… |
| `components/PageOverlay.tsx:482` | prose | RENAME | 편집하십시오 — 여기에 상자를 그리려면 위치를 지어내야 하고, 그러면 글자가 없는 곳에 | 편집합니다 — 여기에 상자를 그리려면 위치를 지어내야 하고, 그러면 글자가 없는 곳에 |
| `components/PageOverlay.tsx:483` | label | KEEP | 커서를 놓게 됩니다. | 커서를 놓게 됩니다. |
| `components/PagePreview.tsx:119` | aria | KEEP | 용지와 여백 치수 | 용지와 여백 치수 |
| `components/PagePreview.tsx:133` | label | SHORTEN | page geometry · {page}쪽 · {Math.round(zoom * 100)}% | page geometry · {page}쪽 · {Math.round(zo… |
| `components/PagePreview.tsx:156` | label | KEEP | 한컴 렌더 | 한컴 렌더 |
| `components/PagePreview.tsx:157` | label | KEEP | PDF 렌더 | PDF 렌더 |
| `components/PagePreview.tsx:158` | label | KEEP | 자체 렌더 · 미인증 | 자체 렌더 · 미인증 |
| `components/PagePreview.tsx:162` | prose | SHORTEN | 한컴이 만든 PDF를 그대로 이미지로 옮긴 지면입니다. | 한컴이 만든 PDF를 그대로 이미지로 옮긴 지면입니다. |
| `components/PagePreview.tsx:163` | prose | SHORTEN | 이 세션이 이미 가지고 있던 PDF를 이미지로 옮긴 지면입니다. 그 PDF를 누가 어떻게 짰는지는 이 빌드가 알 수 있는 것이 아닙니다. | 이 세션이 이미 가지고 있던 PDF를 이미지로 옮긴 지면입니다. 그 PD… |
| `components/PagePreview.tsx:165` | prose | SHORTEN | 한컴 없이 우리 렌더러가 직접 그린 지면입니다. 한컴이 그린 지면과 맞춰 검증한 적이 없습니다 — 아래 목록이 못 그린 것들입니다. | 한컴 없이 우리 렌더러가 직접 그린 지면입니다. 한컴이 그린 지면과 맞춰… |
| `components/PagePreview.tsx:203` | label | KEEP | 무엇을 못 그렸나{" "} | 무엇을 못 그렸나{" "} |
| `components/PagePreview.tsx:205` | label | KEEP | 없음 | 없음 |
| `components/PagePreview.tsx:209` | label | KEEP | 이 지면에서는 렌더러가 만난 것을 모두 그렸다고 보고했습니다. | 이 지면에서는 렌더러가 만난 것을 모두 그렸다고 보고했습니다. |
| `components/PagePreview.tsx:233` | label | KEEP | 글꼴 대체 … | 글꼴 대체 … |
| `components/PagePreview.tsx:238` | label | KEEP | … → …(…자) | … → …(…자) |
| `components/PagePreview.tsx:240` | label | KEEP | 문서가 선언한 글꼴 …종을 모두 이 기계에서 찾았습니다. | 문서가 선언한 글꼴 …종을 모두 이 기계에서 찾았습니다. |
| `components/PagePreview.tsx:266` | label | KEEP | 겹판 보류 | 겹판 보류 |
| `components/PagePreview.tsx:268` | label | SHORTEN | 이 지면을 그린 렌더러와 글줄 위치를 잰 렌더러가 서로 다릅니다. 한쪽의 자리를 다른 쪽 | 이 지면을 그린 렌더러와 글줄 위치를 잰 렌더러가 서로 다릅니다. 한쪽의… |
| `components/PagePreview.tsx:269` | label | SHORTEN | 그림 위에 얹으면 잰 것처럼 보이는 틀린 자리가 됩니다 — 그래서 아무것도 그리지 않습니다. | 그림 위에 얹으면 잰 것처럼 보이는 틀린 자리가 됩니다 |
| `components/PagePreview.tsx:285` | prose | SHORTEN | 런타임이 변환기에 닿지 못했습니다. 위에 적힌 이유가 실제 원인입니다. 한컴이 설치되고 변환기를 쓸 수 있는 기계에서 열거나, 이미 PDF인 문서를 여십시오. | 변환기에 닿지 못했습니다. 위에 적힌 이유가 실제 원인입니다. 한컴이 설… |
| `components/PagePreview.tsx:287` | prose | SHORTEN | 한컴이 이미 떠 있습니다. 그 창을 닫고 다시 누르십시오. 런타임은 남의 한컴을 대신 종료하지 않습니다 — 그렇게 했다가 서로의 작업을 죽인 적이 있습니다. | 한컴이 이미 떠 있습니다. 그 창을 닫고 다시 누르십시오. 남의 한컴을… |
| `components/PagePreview.tsx:289` | label | KEEP | 이 문서는 변환기가 받는 형식이 아닙니다. | 이 문서는 변환기가 받는 형식이 아닙니다. |
| `components/PagePreview.tsx:291` | prose | SHORTEN | 변환기가 실행됐지만 쓸 만한 PDF를 남기지 못했습니다. 한컴 COM 등록이 깨졌을 때 이렇게 보입니다. 한컴을 한 번 직접 실행해 초기화한 뒤 다시 시도해 보십시오. | 변환기가 실행됐지만 쓸 만한 PDF를 남기지 못했습니다. 한컴 COM 등… |
| `components/PagePreview.tsx:293` | label | RENAME | 런타임이 이 요청을 거절했습니다. | 엔진이 이 요청을 거절했습니다. |
| `components/PagePreview.tsx:302` | label | KEEP | 거절 | 거절 |
| `components/PagePreview.tsx:315` | label | KEEP | 변환기가 남긴 말 | 변환기가 남긴 말 |
| `components/PagePreview.tsx:320` | label | SHORTEN | 원본은 이 과정에 들어가지 않습니다. 변환은 세션이 가진 사본에만 일어납니다. | 원본은 이 과정에 들어가지 않습니다. 변환은 세션이 가진 사본에만 일어납… |
| `components/PagePreview.tsx:340` | label | KEEP | 겹판 없음 | 겹판 없음 |
| `components/PagePreview.tsx:374` | label | KEEP | 후보본과 다름 — 이 그림은 원본 기준 | 후보본과 다름 — 이 그림은 원본 기준 |
| `components/PagePreview.tsx:378` | label | KEEP | 승인한 편집이 담긴 후보본이 있지만, 이 지면 그림은 아직{" "} | 승인한 편집이 담긴 후보본이 있지만, 이 지면 그림은 아직{" "} |
| `components/PagePreview.tsx:384` | label | KEEP | 다른 후보본(…) | 다른 후보본(…) |
| `components/PagePreview.tsx:385` | label | KEEP | 원본 | 원본 |
| `components/PagePreview.tsx:386` | prose | DROP | 을 그린 것입니다. 후보본을 그리려면 한 번 더 변환해야 합니다. | — (앞 줄과 한 문장) |
| `components/PagePreview.tsx:389` | label | KEEP | 그림의 출처 {echo.rendered.kind} | 그림의 출처 {echo.rendered.kind} |
| `components/PagePreview.tsx:394` | label | KEEP | 달라진 자리 …곳: … | 달라진 자리 …곳: … |
| `components/PagePreview.tsx:395` | prose | SHORTEN | 달라진 자리 목록을 아직 읽지 못했습니다 — 영수증과 계획을 읽는 중입니다 | 달라진 자리 목록을 아직 읽지 못했습니다 |
| `components/PagePreview.tsx:398` | label | KEEP | 바뀐 글자를 이 그림 위에 그려 넣지는 않습니다. 그것은 편집기가 지어낸 | 바뀐 글자를 이 그림 위에 그려 넣지는 않습니다. 그것은 편집기가 지어낸 |
| `components/PagePreview.tsx:399` | label | KEEP | 지면이지 렌더러가 그린 지면이 아니기 때문입니다. | 지면이지 렌더러가 그린 지면이 아니기 때문입니다. |
| `components/PagePreview.tsx:408` | label | KEEP | 입력 조합이 끝나기 전에는 변환하지 않습니다 | 입력 조합이 끝나기 전에는 변환하지 않습니다 |
| `components/PagePreview.tsx:409` | label | KEEP | 후보본을 PDF로 바꿔 다시 그립니다. 원본은 건드리지 않습니다. | 후보본을 PDF로 바꿔 다시 그립니다. 원본은 건드리지 않습니다. |
| `components/PagePreview.tsx:416` | label | KEEP | 다시 그리기 | 다시 그리기 |
| `components/PagePreview.tsx:420` | label | MOVE-TO-DETAILS | document/renderPrepare 가 이 연결에 없습니다. 후보본을 그릴 방법이 | document/renderPrepare 가 이 연결에 없습니다. 후보본… |
| `components/PagePreview.tsx:421` | label | KEEP | 없습니다. | 없습니다. |
| `components/PagePreview.tsx:432` | label | KEEP | 이 문서는 아직 그림으로 만들 수 없습니다 | 이 문서는 아직 그림으로 만들 수 없습니다 |
| `components/PagePreview.tsx:433` | label | KEEP | PDF는 있지만 그릴 도구가 없습니다 | PDF는 있지만 그릴 도구가 없습니다 |
| `components/PagePreview.tsx:434` | label | KEEP | 여기에는 그림으로 만들 것이 없습니다 | 여기에는 그림으로 만들 것이 없습니다 |
| `components/PagePreview.tsx:435` | label | KEEP | 가리킨 파일이 사라졌습니다 | 가리킨 파일이 사라졌습니다 |
| `components/PagePreview.tsx:439` | label | SHORTEN | 아래 “페이지 그림 만들기”가 한컴을 불러 사본을 PDF로 바꿉니다. 원본은 건드리지 않습니다. | 아래 “페이지 그림 만들기”가 한컴을 불러 사본을 PDF로 바꿉니다. 원… |
| `components/PagePreview.tsx:441` | prose | SHORTEN | 이 런타임에 PyMuPDF가 없습니다. 선택 의존성이라 없을 수 있고, 없으면 없다고 말합니다. | 이 PyMuPDF가 없습니다. 선택 의존성이라 없을 수 있고, 없으면 없… |
| `components/PagePreview.tsx:442` | prose | SHORTEN | PDF인 문서를 열거나, 먼저 PDF를 만들어야 합니다. | PDF인 문서를 열거나, 먼저 PDF를 만들어야 합니다. |
| `components/PagePreview.tsx:443` | label | KEEP | 그 후보본의 바이트가 더 이상 디스크에 없습니다. | 그 후보본의 바이트가 더 이상 디스크에 없습니다. |
| `components/PagePreview.tsx:447` | label | KEEP | 페이지 그림이 없습니다 | 페이지 그림이 없습니다 |
| `components/PagePreview.tsx:462` | label | SHORTEN | 자체 렌더러도 그리지 못했습니다 ({render.unavailable.own.reason}) | 자체 렌더러도 그리지 못했습니다 |
| `components/PagePreview.tsx:560` | prose | KEEP | 페이지를 그리는 중입니다. | 페이지를 그리는 중입니다. |
| `components/PagePreview.tsx:563` | label | KEEP | 페이지를 그리지 못했습니다 | 페이지를 그리지 못했습니다 |
| `components/PagePreview.tsx:578` | label | KEEP | 이전 그림 | 이전 그림 |
| `components/PagePreview.tsx:584` | label | KEEP | 지금은 그릴 수 없음 | 지금은 그릴 수 없음 |
| `components/PagePreview.tsx:612` | tooltip | KEEP | …쪽 | …쪽 |
| `components/PagePreview.tsx:634` | prose | SHORTEN | 페이지 그림은 바이트가 무엇을 그리는지 보여 줄 뿐, 그 바이트가 옳다는 증거가 아닙니다. | 페이지 그림은 바이트가 무엇을 그리는지 보여 줄 뿐, 그 바이트가 옳다는… |
| `components/PagePreview.tsx:643` | label | KEEP | 그림이 너무 큽니다 | 그림이 너무 큽니다 |
| `components/PagePreview.tsx:644` | label | KEEP | 프레임에 담기에 큽니다. | 프레임에 담기에 큽니다. |
| `components/PagePreview.tsx:675` | tooltip | SHORTEN | 지금 문서의 페이지 그림을 요청합니다. 입력할 때마다 그리지 않습니다. | 지금 문서의 페이지 그림을 요청합니다. 입력할 때마다 |
| `components/PagePreview.tsx:678` | label | KEEP | 페이지 그림 요청 | 페이지 그림 요청 |
| `components/PagePreview.tsx:687` | label | KEEP | 입력 조합이 끝나기 전에는 변환하지 않습니다 | 입력 조합이 끝나기 전에는 변환하지 않습니다 |
| `components/PagePreview.tsx:688` | label | KEEP | 세션 사본을 PDF로 바꿉니다. 원본은 건드리지 않습니다. | 세션 사본을 PDF로 바꿉니다. 원본은 건드리지 않습니다. |
| `components/PagePreview.tsx:695` | label | KEEP | 한컴을 부르는 중… | 한컴을 부르는 중… |
| `components/PagePreview.tsx:705` | aria | KEEP | 이전 쪽 | 이전 쪽 |
| `components/PagePreview.tsx:712` | label | KEEP | {page}쪽 / 전체 {pageCount} | {page}쪽 / 전체 {pageCount} |
| `components/PagePreview.tsx:717` | aria | KEEP | 다음 쪽 | 다음 쪽 |
| `components/PagePreview.tsx:736` | tooltip | SHORTEN | 창 너비에 맞춥니다. 창 크기가 바뀌어도 계속 맞춥니다. | 창 너비에 맞춥니다. 창 크기가 바뀌어도 계속 맞춥니다. |
| `components/PagePreview.tsx:739` | label | KEEP | 폭 맞춤 | 폭 맞춤 |
| `components/PagePreview.tsx:745` | tooltip | KEEP | 한 쪽이 통째로 보이게 맞춥니다. | 한 쪽이 통째로 보이게 맞춥니다. |
| `components/PagePreview.tsx:748` | label | KEEP | 쪽 맞춤 | 쪽 맞춤 |
| `components/PagePreview.tsx:750` | aria | KEEP | 축소 | 축소 |
| `components/PagePreview.tsx:756` | tooltip | KEEP | 100% 로 되돌립니다 | 100% 로 되돌립니다 |
| `components/PagePreview.tsx:761` | aria | KEEP | 확대 | 확대 |
| `components/SeatEditor.tsx:90` | aria | KEEP | 이 자리에 넣을 값 | 이 자리에 넣을 값 |
| `components/Tag.tsx:23` | label | KEEP | 채움 | 채움 |
| `components/Tag.tsx:24` | label | KEEP | 안내 | 안내 |
| `components/Tag.tsx:25` | label | KEEP | 고정 | 고정 |
| `components/Tag.tsx:26` | label | KEEP | 여백 | 여백 |
| `components/TextView.tsx:93` | tooltip | KEEP | 본문 기준과 다른 색: … | 본문 기준과 다른 색: … |
| `components/TextView.tsx:136` | aria | KEEP | 값을 넣는 자리 | 값을 넣는 자리 |
| `components/TextView.tsx:304` | label | KEEP | <caption>표 {table.index}</caption> | <caption>표 {table.index}</caption> |
| `components/TextView.tsx:340` | tooltip | SHORTEN | R…C… · 채움 자리 — 눌러서 값을 넣습니다 | …행 …열 · 입력 칸 |
| `components/TextView.tsx:383` | label | KEEP | 표 밖의 문단 | 표 밖의 문단 |
| `components/TextView.tsx:412` | label | KEEP | 이 문서에서 읽어 온 글이 없습니다. | 이 문서에서 읽어 온 글이 없습니다. |
| `components/PagePreview.tsx:133` | label | MOVE-TO-DETAILS | page geometry · {n}쪽 | 쪽 {n} |
| `components/PagePreview.tsx:574` | label | MOVE-TO-DETAILS | revision unknown | 판 정보 없음 |

## 선택

Honesty (once): 이 칸의 값과 쓰기 가능 여부만.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `components/ContextPanel.tsx:49` | label | RENAME | 표 … R…C… | 표 … · …행 …열 |
| `components/ContextPanel.tsx:83` | label | KEEP | 가능 | 가능 |
| `components/ContextPanel.tsx:92` | label | KEEP | 자리 원문 | 자리 원문 |
| `components/ContextPanel.tsx:95` | label | KEEP | 주소 | 주소 |
| `components/ContextPanel.tsx:103` | label | KEEP | 쓰기 | 쓰기 |
| `components/ContextPanel.tsx:110` | prose | KEEP | 이 자리의 글을 읽는 중입니다. | 이 자리의 글을 읽는 중입니다. |
| `components/ContextPanel.tsx:117` | label | KEEP | 런타임이 이 자리의 글을 돌려주지 않았습니다. 없는 자리를 만들지 않습니다. | 런타임이 이 자리의 글을 돌려주지 않았습니다. 없는 자리를 만들지 않습니다. |
| `components/ContextPanel.tsx:122` | label | KEEP | (빈 자리) | (빈 자리) |
| `components/ContextPanel.tsx:131` | label | KEEP | (빈 자리) | (빈 자리) |
| `components/ContextPanel.tsx:146` | prose | KEEP | 이 주소의 칸을 문서 그래프에서 찾지 못했습니다. | 이 주소의 칸을 문서 그래프에서 찾지 못했습니다. |
| `components/ContextPanel.tsx:154` | label | RENAME | 표 … R…C… | 표 … · …행 …열 |
| `components/ContextPanel.tsx:157` | label | KEEP | 분류 | 분류 |
| `components/ContextPanel.tsx:164` | label | KEEP | 여백 형태 | 여백 형태 |
| `components/ContextPanel.tsx:166` | label | MOVE-TO-DETAILS | 권장 charPr | 권장 글자 모양 |
| `components/ContextPanel.tsx:172` | label | KEEP | (잘림) | (잘림) |
| `components/ContextPanel.tsx:178` | prose | SHORTEN | 전체 글자는 요청해야 옵니다. 구조만 보내는 것이 기본값입니다. | 전체 글자는 요청해야 옵니다. |
| `components/ContextPanel.tsx:185` | label | KEEP | 쓰기 전 확인 | 쓰기 전 확인 |
| `components/ContextPanel.tsx:189` | label | KEEP | 색 이상 | 색 이상 |
| `components/ContextPanel.tsx:192` | label | KEEP | 있음 | 있음 |
| `components/ContextPanel.tsx:194` | label | KEEP | 없음 | 없음 |
| `components/ContextPanel.tsx:196` | label | KEEP | 판단 불가 | 판단 불가 |
| `components/ContextPanel.tsx:201` | label | KEEP | 글자속성 이상 | 글자속성 이상 |
| `components/ContextPanel.tsx:204` | label | KEEP | 있음 | 있음 |
| `components/ContextPanel.tsx:206` | label | KEEP | 없음 | 없음 |
| `components/ContextPanel.tsx:208` | label | KEEP | 판단 불가 | 판단 불가 |
| `components/ContextPanel.tsx:215` | prose | SHORTEN | 이 칸은 값을 넣는 자리가 아닙니다. 쓰기 전 확인은 채움 자리에만 붙습니다. | 이 칸은 값을 넣는 자리가 아닙니다. 쓰기 전 확인은 채움 자리에만 붙습… |
| `components/ContextPanel.tsx:220` | label | KEEP | 글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다. | 글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다. |
| `components/ContextPanel.tsx:229` | label | KEEP | 이 자리에 값 넣기 | 이 자리에 값 넣기 |
| `components/ContextPanel.tsx:239` | prose | KEEP | 이 문단을 찾지 못했습니다. | 이 문단을 찾지 못했습니다. |
| `components/ContextPanel.tsx:244` | label | RENAME | 문단 at_para {n} | 문단 {n} |
| `components/ContextPanel.tsx:246` | label | KEEP | 구역 | 구역 |
| `components/ContextPanel.tsx:248` | label | KEEP | 삭제 후보 | 삭제 후보 |
| `components/ContextPanel.tsx:252` | label | KEEP | 본문 | 본문 |
| `components/ContextPanel.tsx:254` | label | KEEP | (빈 문단) | (빈 문단) |
| `components/ContextPanel.tsx:262` | label | KEEP | 선택 | 선택 |
| `components/ContextPanel.tsx:273` | prose | DROP | 왼쪽에서 문단이나 표의 칸을 고르면 그 자리에 대해 아는 것을 여기에 모아 | — (빈 선택은 단축키 한 줄이면 됨) |
| `components/ContextPanel.tsx:274` | prose | DROP | 보여 줍니다. | — |
| `components/ContextPanel.tsx:296` | label | KEEP | <h3>표 {selection.table}</h3> | <h3>표 {selection.table}</h3> |
| `components/ContextPanel.tsx:299` | label | KEEP | 칸 | 칸 |
| `components/ContextPanel.tsx:363` | aria | RENAME | 검사기 | 패널 |
| `components/ContextPanel.tsx:367` | aria | RENAME | 검사기 | 패널 |
| `components/ContextPanel.tsx:386` | tooltip | KEEP | 승인 대기 | 승인 대기 |
| `components/ContextPanel.tsx:428` | label | KEEP | 선택 항목 | 선택 항목 |
| `components/ContextPanel.tsx:445` | prose | SHORTEN | 이 문서는 완성본으로 보입니다. 양식을 연결하면 검사 판정이 정확해집니다 | 이 문서는 완성본으로 보입니다. 양식을 연결하면 검사 판정이 정확해집니다 |
| `components/ContextPanel.tsx:454` | label | KEEP | 양식 연결 | 양식 연결 |
| `components/ContextPanel.tsx:165` | label | MOVE-TO-DETAILS | charPr | 글자 모양 |
| `components/ContextPanel.tsx:247` | label | MOVE-TO-DETAILS | para_idx | 문단 번호 |

## 검토

Honesty (once): 승인은 사람이 합니다. 원본은 바뀌지 않습니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `actions.ts:1176` | toast | SHORTEN | 대기열에서 뺐습니다. 문서는 처음부터 바뀐 적이 없습니다. | 대기열에서 뺐습니다. |
| `actions.ts:1438` | label | MOVE-TO-DETAILS | 되돌리기는 이전 값을 읽어올 수 있는 작업(fill_cell, set_run)에만 만들 수 있습니다. | 되돌리기는 이전 값을 읽어올 수 있는 작업(fill_cell, set_r… |
| `actions.ts:1458` | error | KEEP | 이 계획의 작업들이 주소를 갖고 있지 않아 이전 값을 읽을 수 없습니다. | 이 계획의 작업들이 주소를 갖고 있지 않아 이전 값을 읽을 수 없습니다. |
| `actions.ts:1528` | toast | SHORTEN | 되돌리기를 제안했습니다. 승인해야 후보본이 하나 더 생깁니다. | 되돌리기를 제안했습니다. 승인해야 후보본이 하나 더 생깁니다. |
| `actions.ts:1861` | toast | KEEP | 계획을 거절했습니다. 문서는 그대로입니다. | 계획을 거절했습니다. 문서는 그대로입니다. |
| `actions.ts:1969` | toast | SHORTEN | 후보본을 만들었습니다 · … | 후보본을 만들었습니다. |
| `actions.ts:1976` | toast | SHORTEN | 적용을 멈추라고 알렸습니다. 진행 중인 한 단계는 끝납니다. | 적용을 멈추라고 알렸습니다. 진행 중인 한 단계는 끝납니다. |
| `actions.ts:2044` | error | KEEP | 복구 후보의 영수증이 중단된 적용 요청과 일치하지 않습니다. | 복구 후보의 영수증이 중단된 적용 요청과 일치하지 않습니다. |
| `actions.ts:2952` | label | SHORTEN | 제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 이 제안을 대기열에 넣지 않았습니다. | 제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 이 제안을 대기열에 넣… |
| `actions.ts:3553` | label | KEEP | 원본 값으로 짐작해서 검토 대기열을 만들지 않습니다. | 원본 값으로 짐작해서 검토 대기열을 만들지 않습니다. |
| `agent/planProjection.ts:77` | error | KEEP | 에이전트 작업 … (…)을 검토 대기열에 정확히 표시할 수 없습니다: … | 에이전트 작업 … (…)을 검토 대기열에 정확히 표시할 수 없습니다: … |
| `agent/planProjection.ts:100` | label | KEEP | 일부 작업 의미를 대기열이 보존할 수 없습니다. | 일부 작업 의미를 대기열이 보존할 수 없습니다. |
| `agent/planProjection.ts:117` | label | KEEP | 작업 필드의 형식이 대기열 표현과 맞지 않습니다. | 작업 필드의 형식이 대기열 표현과 맞지 않습니다. |
| `agent/planProjection.ts:128` | label | KEEP | 일부 작업 의미를 대기열이 보존할 수 없습니다. | 일부 작업 의미를 대기열이 보존할 수 없습니다. |
| `agent/planProjection.ts:143` | label | KEEP | 작업 필드의 형식이 대기열 표현과 맞지 않습니다. | 작업 필드의 형식이 대기열 표현과 맞지 않습니다. |
| `agent/planProjection.ts:159` | label | KEEP | 이 작업 종류는 아직 검토 대기열이 지원하지 않습니다. | 이 작업 종류는 아직 검토 대기열이 지원하지 않습니다. |
| `components/ContextPanel.tsx:263` | label | KEEP | 검토 | 검토 |
| `components/ContextPanel.tsx:430` | label | KEEP | 검토 | 검토 |
| `components/HunkCard.tsx:30` | toast | KEEP | 복사하지 못했습니다 | 복사하지 못했습니다 |
| `components/HunkCard.tsx:34` | toast | RENAME | 계획 지문을 복사했습니다 | 계획을 복사했습니다 |
| `components/HunkCard.tsx:35` | toast | KEEP | 복사하지 못했습니다 | 복사하지 못했습니다 |
| `components/HunkCard.tsx:115` | label | KEEP | 문서에서 이 자리를 찾습니다 | 문서에서 이 자리를 찾습니다 |
| `components/HunkCard.tsx:116` | label | KEEP | 이 작업은 다른 문서의 대기열에 있어 현재 문서에서는 찾을 수 없습니다 | 이 작업은 다른 문서의 대기열에 있어 현재 문서에서는 찾을 수 없습니다 |
| `components/HunkCard.tsx:126` | tooltip | KEEP | 제안: … | 제안: … |
| `components/HunkCard.tsx:127` | label | KEEP | 에이전트 제안 | 에이전트 제안 |
| `components/HunkCard.tsx:130` | label | KEEP | 내가 입력 | 내가 입력 |
| `components/HunkCard.tsx:133` | tooltip | KEEP | 이 자리에 쓸 글자 속성을 지정했습니다 | 이 자리에 쓸 글자 속성을 지정했습니다 |
| `components/HunkCard.tsx:141` | tooltip | SHORTEN | 이 작업을 대기열에서 뺍니다. 문서는 아직 아무것도 바뀌지 않았습니다. | 이 작업을 대기열에서 뺍니다. 문서는 아직 아무것도 바뀌지 않았습니다. |
| `components/HunkCard.tsx:144` | label | KEEP | 대기열에서 제거 | 대기열에서 제거 |
| `components/HunkCard.tsx:151` | label | KEEP | 원문 없음 | 원문 없음 |
| `components/HunkCard.tsx:183` | aria | KEEP | 넣을 값 | 넣을 값 |
| `components/HunkCard.tsx:213` | aria | KEEP | 이 항목 승인 | 이 항목 승인 |
| `components/HunkCard.tsx:217` | label | KEEP | 승인 | 승인 |
| `components/HunkCard.tsx:225` | aria | KEEP | 이 항목 거부 | 이 항목 거부 |
| `components/HunkCard.tsx:229` | label | RENAME | 거부 | 거절 |
| `components/HunkCard.tsx:240` | label | KEEP | 출처 | 출처 |
| `components/HunkCard.tsx:242` | label | KEEP | 세션 | 세션 |
| `components/HunkCard.tsx:244` | label | KEEP | 계획 | 계획 |
| `components/HunkCard.tsx:246` | label | RENAME | 지문 | 계획 |
| `components/HunkCard.tsx:254` | tooltip | RENAME | 계획 지문 전체 복사 | 계획 전체 복사 |
| `components/HunkCard.tsx:257` | label | KEEP | 복사 | 복사 |
| `components/HunkCard.tsx:261` | label | KEEP | 제안자 | 제안자 |
| `components/HunkCard.tsx:263` | label | KEEP | 백엔드 | 백엔드 |
| `components/HunkCard.tsx:265` | label | KEEP | 기준 후보 | 기준 후보 |
| `components/HunkCard.tsx:266` | label | KEEP | 원본 | 원본 |
| `components/HunkCard.tsx:267` | label | KEEP | 영수증 | 영수증 |
| `components/HunkCard.tsx:269` | label | KEEP | 있음 | 있음 |
| `components/HunkCard.tsx:277` | label | KEEP | 막힘 | 막힘 |
| `components/HunkCard.tsx:284` | label | KEEP | 주의 | 주의 |
| `components/HunkCard.tsx:297` | label | MOVE-TO-DETAILS | 권장 charPr {id} 지정 | 권장 글자 모양 쓰기 (id는 기술 정보) |
| `components/ReviewQueue.tsx:132` | label | KEEP | 입력 조합이 끝나기 전에는 승인하지 않습니다 | 입력 조합이 끝나기 전에는 승인하지 않습니다 |
| `components/ReviewQueue.tsx:134` | label | RENAME | 화면에 보이는 계획 지문에 승인을 기록합니다 | 화면에 보이는 계획에 승인을 기록합니다 |
| `components/ReviewQueue.tsx:135` | label | KEEP | 현재 문서와 정확히 일치하는 승인만 기록할 수 있습니다 | 현재 문서와 정확히 일치하는 승인만 기록할 수 있습니다 |
| `components/ReviewQueue.tsx:143` | label | KEEP | 입력 조합이 끝나기 전에는 승인하지 않습니다 | 입력 조합이 끝나기 전에는 승인하지 않습니다 |
| `components/ReviewQueue.tsx:144` | label | KEEP | 결과가 불명확하거나 이미 완료된 적용은 반복하지 않습니다 | 결과가 불명확하거나 이미 완료된 적용은 반복하지 않습니다 |
| `components/ReviewQueue.tsx:145` | label | KEEP | 현재 문서와 정확히 일치하는 승인만 기록할 수 있습니다 | 현재 문서와 정확히 일치하는 승인만 기록할 수 있습니다 |
| `components/ReviewQueue.tsx:146` | label | RENAME | 화면에 보이는 계획 지문에 승인을 기록합니다 | 화면에 보이는 계획에 승인을 기록합니다 |
| `components/ReviewQueue.tsx:168` | label | KEEP | 모두 승인 · … | 모두 승인 · … |
| `components/ReviewQueue.tsx:281` | tooltip | KEEP | 방금 대기열에서 뺀 작업을 그대로 다시 넣습니다 | 방금 대기열에서 뺀 작업을 그대로 다시 넣습니다 |
| `components/ReviewQueue.tsx:284` | label | KEEP | 다시 넣기 {redoCount} | 다시 넣기 {redoCount} |
| `components/ReviewQueue.tsx:294` | tooltip | KEEP | 검토할 수 없습니다 | 검토할 수 없습니다 |
| `components/ReviewQueue.tsx:305` | tooltip | KEEP | 검토할 것이 없습니다 | 검토할 것이 없습니다 |
| `components/ReviewQueue.tsx:306` | prose | KEEP | 문서에서 입력 칸을 누르면 값이 여기에 쌓입니다. | 문서에서 입력 칸을 누르면 값이 여기에 쌓입니다. |
| `components/ReviewQueue.tsx:314` | aria | KEEP | 검토 대기열 | 검토 대기열 |
| `components/ReviewQueue.tsx:316` | label | KEEP | 검토 대기열 | 검토 대기열 |
| `components/ReviewQueue.tsx:324` | label | KEEP | 거절됨 | 거절됨 |
| `components/ReviewQueue.tsx:335` | label | KEEP | 되돌리기 제안 | 되돌리기 제안 |
| `components/ReviewQueue.tsx:338` | prose | SHORTEN | 되돌리는 계획입니다. 그 후보본은 지워지지 않습니다 — 승인하면 되돌린 | 되돌리는 계획입니다. 그 후보본은 지워지지 않습니다 |
| `components/ReviewQueue.tsx:339` | label | KEEP | 결과가 담긴 후보본이 하나 더 생기고, 영수증에 무엇을 되돌렸는지가 | 결과가 담긴 후보본이 하나 더 생기고, 영수증에 무엇을 되돌렸는지가 |
| `components/ReviewQueue.tsx:340` | label | KEEP | 적힙니다. 적용한 뒤에는 런타임이 값이 실제로 되돌아갔는지 다시 읽어 | 적힙니다. 적용한 뒤에는 런타임이 값이 실제로 되돌아갔는지 다시 읽어 |
| `components/ReviewQueue.tsx:341` | label | KEEP | 확인합니다. | 확인합니다. |
| `components/ReviewQueue.tsx:345` | label | KEEP | 이어 붙일 후보본 {draft.baseRunId.slice(0, 12)} | 이어 붙일 후보본 {draft.baseRunId.slice(0, 12)} |
| `components/ReviewQueue.tsx:351` | label | KEEP | 이 대기열은 후보본{" "} | 이 대기열은 후보본{" "} |
| `components/ReviewQueue.tsx:353` | label | KEEP | 앞서 승인한 편집은 그대로 남습니다. | 앞서 승인한 편집은 그대로 남습니다. |
| `components/ReviewQueue.tsx:359` | label | KEEP | 이 셸이 낸 것 | 이 셸이 낸 것 |
| `components/ReviewQueue.tsx:360` | prose | SHORTEN | 에이전트가 받아 둔 승인은 더 이상 쓰이지 않습니다. 승인은 지금 보이는 계획에만 묶입니다. | 에이전트가 받아 둔 승인은 더 이상 쓰이지 않습니다. 승인은 지금 보이는… |
| `components/ReviewQueue.tsx:366` | label | KEEP | 계획이 낡음 | 계획이 낡음 |
| `components/ReviewQueue.tsx:369` | label | SHORTEN | 이 대기열은 지금 열려 있는 문서가 아니라 다른 문서의 바이트에 묶여 있습니다. 그대로 승인할 수 없습니다. | 이 대기열은 지금 열려 있는 문서가 아니라 다른 문서의 바이트에 묶여 있… |
| `components/ReviewQueue.tsx:370` | prose | SHORTEN | 계획을 낸 뒤 원본이 바뀌었습니다. 런타임이 승인을 거절합니다. | 계획을 낸 뒤 원본이 바뀌었습니다. |
| `components/ReviewQueue.tsx:373` | label | MOVE-TO-DETAILS | 묶인 해시 {staleness.boundSha256.slice(0, 16)} · 지금{" "} | 묶인 해시 {staleness.boundSha256.slice(0, 16… |
| `components/ReviewQueue.tsx:374` | label | KEEP | 알 수 없음 | 알 수 없음 |
| `components/ReviewQueue.tsx:381` | label | KEEP | 지금 문서로 다시 제안 | 지금 문서로 다시 제안 |
| `components/ReviewQueue.tsx:388` | label | KEEP | 거절됨 | 거절됨 |
| `components/ReviewQueue.tsx:431` | label | KEEP | 쓰기 전 확인 통과 | 쓰기 전 확인 통과 |
| `components/ReviewQueue.tsx:438` | tooltip | MOVE-TO-DETAILS | 이 계획의 지문 | 계획 (해시는 기술 정보) |
| `components/ReviewQueue.tsx:448` | label | KEEP | 막힘 | 막힘 |
| `components/ReviewQueue.tsx:453` | label | KEEP | 이 확인이 닿지 못하는 것 | 이 확인이 닿지 못하는 것 |
| `components/ReviewQueue.tsx:465` | label | KEEP | 계획 원본 | 계획 원본 |
| `components/ReviewQueue.tsx:470` | prose | KEEP | 계획을 확인하는 중입니다. | 계획을 확인하는 중입니다. |
| `components/ReviewQueue.tsx:474` | label | SHORTEN | The one place 단청 vermilion is spent. Everything above is teal. */} | The one place 단청 vermilion is spent. Eve… |
| `components/ReviewQueue.tsx:479` | label | KEEP | 승인됨 | 승인됨 |
| `components/ReviewQueue.tsx:482` | label | SHORTEN | 런타임에 승인 결정이 기록되었습니다. 현재 문서와 계획의 묶임을 다시 확인한 뒤 | 승인 결정이 기록되었습니다. 현재 문서와 계획의 묶임을 다시 확인한 뒤 |
| `components/ReviewQueue.tsx:483` | label | KEEP | 적용할 수 있습니다. | 적용할 수 있습니다. |
| `components/ReviewQueue.tsx:492` | label | KEEP | 입력 조합이 끝나기 전에는 적용하지 않습니다 | 입력 조합이 끝나기 전에는 적용하지 않습니다 |
| `components/ReviewQueue.tsx:494` | label | KEEP | 결과가 불명확하거나 이미 완료된 적용은 반복하지 않습니다 | 결과가 불명확하거나 이미 완료된 적용은 반복하지 않습니다 |
| `components/ReviewQueue.tsx:496` | label | KEEP | 승인된 이 계획을 적용합니다 | 승인된 이 계획을 적용합니다 |
| `components/ReviewQueue.tsx:497` | label | KEEP | 현재 문서와 정확히 일치하는 승인만 적용할 수 있습니다 | 현재 문서와 정확히 일치하는 승인만 적용할 수 있습니다 |
| `components/ReviewQueue.tsx:504` | label | KEEP | 적용하는 중… | 적용하는 중… |
| `components/ReviewQueue.tsx:512` | label | KEEP | 멈추기 | 멈추기 |
| `components/ReviewQueue.tsx:521` | label | RENAME | 승인을 기다리는 중 | 승인 대기 |
| `components/ReviewQueue.tsx:524` | prose | SHORTEN | 승인하면 이 계획 지문에 대한 결정만 런타임에 기록됩니다. 문서는 아직 바뀌지 | 승인해도 문서는 아직 바뀌지 않습니다. 다음이 적용입니다. |
| `components/ReviewQueue.tsx:525` | prose | SHORTEN | 않습니다. 적용은 승인이 기록된 뒤의 다음 단계입니다. 승인 기록은{" "} | 않습니다. 적용은 승인이 기록된 뒤의 다음 단계입니다. 승인 기록은{" "} |
| `components/ReviewQueue.tsx:527` | label | KEEP | 묶입니다. | 묶입니다. |
| `components/ReviewQueue.tsx:530` | label | KEEP | 요청자 | 요청자 |
| `components/ReviewQueue.tsx:532` | label | KEEP | 요청 시각 | 요청 시각 |
| `components/ReviewQueue.tsx:534` | label | KEEP | 작업 수 | 작업 수 |
| `components/ReviewQueue.tsx:548` | label | KEEP | 승인 | 승인 |
| `components/ReviewQueue.tsx:556` | label | KEEP | 입력 조합이 끝나기 전에는 거절하지 않습니다 | 입력 조합이 끝나기 전에는 거절하지 않습니다 |
| `components/ReviewQueue.tsx:558` | label | KEEP | 이 승인 요청을 거절합니다 | 이 승인 요청을 거절합니다 |
| `components/ReviewQueue.tsx:559` | label | KEEP | 현재 문서와 정확히 일치하는 승인만 거절할 수 있습니다 | 현재 문서와 정확히 일치하는 승인만 거절할 수 있습니다 |
| `components/ReviewQueue.tsx:566` | label | KEEP | 거절 | 거절 |
| `components/ReviewQueue.tsx:578` | label | KEEP | 사람이 승인해야 문서가 바뀝니다 | 사람이 승인해야 문서가 바뀝니다 |
| `components/ReviewQueue.tsx:579` | label | KEEP | 확인을 통과한 계획만 승인을 요청할 수 있습니다 | 확인을 통과한 계획만 승인을 요청할 수 있습니다 |
| `components/ReviewQueue.tsx:583` | label | KEEP | 승인 요청 | 승인 요청 |
| `components/ReviewQueue.tsx:587` | label | KEEP | 대기열 비우기 | 대기열 비우기 |
| `components/ReviewQueue.tsx:594` | label | KEEP | 승인 거절됨 | 승인 거절됨 |
| `components/ReviewQueue.tsx:599` | label | KEEP | 지금 문서로 다시 제안 | 지금 문서로 다시 제안 |
| `components/ReviewQueue.tsx:607` | label | KEEP | 적용하지 못했습니다 | 적용하지 못했습니다 |
| `components/ReviewQueue.tsx:614` | label | RENAME | 런타임이 보낸 그대로 | 엔진이 보낸 그대로 |
| `components/ReviewQueue.tsx:623` | label | RENAME | 적용 중에 런타임이 멈췄습니다 | 적용 중에 엔진이 멈췄습니다 |
| `components/ReviewQueue.tsx:626` | label | SHORTEN | 적용이 끝나기 전에 연결이 끊겼습니다. 후보본이 만들어졌는지는 목록을 다시 읽어야 알 수 있습니다 — 짐작하지 않습니다. | 적용이 끝나기 전에 연결이 끊겼습니다. 후보본이 만들어졌는지는 목록을 다… |
| `components/ReviewQueue.tsx:628` | label | KEEP | 확인했습니다. 후보본은 만들어졌고 영수증도 남아 있습니다. | 확인했습니다. 후보본은 만들어졌고 영수증도 남아 있습니다. |
| `components/ReviewQueue.tsx:629` | prose | SHORTEN | 확인했습니다. 후보본은 만들어지지 않았습니다. 문서는 그대로입니다. | 확인했습니다. 후보본은 만들어지지 않았습니다. 문서는 그대로입니다. |
| `components/ReviewQueue.tsx:641` | label | KEEP | 후보본이 생겼는지 확인 | 후보본이 생겼는지 확인 |
| `reviewHunk.ts:28` | label | KEEP | 대기 | 대기 |
| `reviewHunk.ts:29` | label | KEEP | 승인됨 | 승인됨 |
| `reviewHunk.ts:30` | label | RENAME | 거부됨 | 거절됨 |
| `reviewHunk.ts:31` | label | KEEP | 적용됨 | 적용됨 |
| `reviewHunk.ts:32` | label | KEEP | 오래됨 | 오래됨 |
| `reviewHunk.ts:52` | label | KEEP | 바꾸기 | 바꾸기 |
| `reviewHunk.ts:53` | label | KEEP | 값 넣기 | 값 넣기 |
| `reviewHunk.ts:55` | label | KEEP | 바꾸기 | 바꾸기 |
| `reviewHunk.ts:56` | label | KEEP | 모두 바꾸기 | 모두 바꾸기 |
| `reviewHunk.ts:57` | label | KEEP | 이동 | 이동 |
| `reviewHunk.ts:58` | label | KEEP | 삽입 | 삽입 |
| `reviewHunk.ts:62` | label | RENAME | 표 … R…C… | 표 … · …행 …열 |
| `reviewHunk.ts:63` | label | KEEP | 문단 … | 문단 … |
| `reviewHunk.ts:66` | label | KEEP | 삽입 | 삽입 |
| `components/HunkCard.tsx:134` | label | MOVE-TO-DETAILS | charPr {id} | 글자 모양 지정됨 |
| `components/ReviewQueue.tsx:168` | label | SHORTEN | 모두 승인 · {n} · {hash6} | 모두 승인 |

## 기록

Honesty (once): 원본은 바뀌지 않습니다. 되돌리기는 새 후보본입니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `components/ContextPanel.tsx:264` | label | KEEP | 기록 | 기록 |
| `components/ContextPanel.tsx:432` | label | KEEP | 기록 | 기록 |
| `components/History.tsx:46` | label | KEEP | 작업 없음 | 작업 없음 |
| `components/History.tsx:93` | tooltip | KEEP | 지금 이 후보본을 문서의 현재 상태로 보고 있습니다 | 지금 이 후보본을 문서의 현재 상태로 보고 있습니다 |
| `components/History.tsx:94` | label | KEEP | 현재 | 현재 |
| `components/History.tsx:98` | tooltip | KEEP | 되돌림 대상 … | 되돌림 대상 … |
| `components/History.tsx:99` | label | KEEP | 되돌리기 | 되돌리기 |
| `components/History.tsx:103` | tooltip | KEEP | … 이(가) 되돌렸습니다 | … 이(가) 되돌렸습니다 |
| `components/History.tsx:104` | label | KEEP | 되돌려짐 | 되돌려짐 |
| `components/History.tsx:108` | label | KEEP | 검사 통과 | 검사 통과 |
| `components/History.tsx:110` | label | KEEP | 검사 미통과 | 검사 미통과 |
| `components/History.tsx:112` | label | KEEP | 검사 결과 없음 | 검사 결과 없음 |
| `components/History.tsx:115` | label | KEEP | 영수증 있음 | 영수증 있음 |
| `components/History.tsx:123` | label | KEEP | 이전 … 위에 | 이전 … 위에 |
| `components/History.tsx:124` | label | KEEP | 원본에서 바로 | 원본에서 바로 |
| `components/History.tsx:135` | label | KEEP | 영수증 있음 | 영수증 있음 |
| `components/History.tsx:145` | label | KEEP | 자세히 | 자세히 |
| `components/History.tsx:151` | tooltip | SHORTEN | 이 후보본을 되돌리는 계획을 제안합니다. 승인하고 적용해야 후보본이 하나 더 생깁니다. 원본은 바꾸지 않습니다. | 이 후보본을 되돌리는 계획을 제안합니다. 승인하고 적용해야 후보본이 하나… |
| `components/History.tsx:155` | label | KEEP | 여기로 되돌리기 | 여기로 되돌리기 |
| `components/History.tsx:163` | label | KEEP | 비교 | 비교 |
| `components/History.tsx:174` | prose | DROP | 이 목록의 해시는 영수증에 적힌 값을 읽어 온 것입니다. 바이트를 다시 | 이 목록의 해시는 영수증에 적힌 값을 읽어 온 것입니다. 바이트를 다시 |
| `components/History.tsx:175` | prose | DROP | 확인하는 것은 영수증 읽기 쪽이고, 어긋나면 그쪽이 거절합니다. | — (앞 줄과 한 문장) |
| `components/History.tsx:184` | label | KEEP | 이 후보본을 현재로 | 이 후보본을 현재로 |
| `components/History.tsx:191` | label | KEEP | 이 후보본 내보내기 | 이 후보본 내보내기 |
| `components/History.tsx:224` | label | KEEP | 비교 | 비교 |
| `components/History.tsx:229` | prose | KEEP | 왼쪽 후보본 | 왼쪽 후보본 |
| `components/History.tsx:243` | prose | KEEP | 비교 대상 | 비교 대상 |
| `components/History.tsx:251` | label | KEEP | 원본 | 원본 |
| `components/History.tsx:274` | label | KEEP | 지금 고른 자리만 | 지금 고른 자리만 |
| `components/History.tsx:284` | label | KEEP | 비교 | 비교 |
| `components/History.tsx:290` | label | KEEP | 받아들일 수 없음 | 받아들일 수 없음 |
| `components/History.tsx:291` | prose | SHORTEN | acceptance: false 는 통과가 아닙니다. | acceptance: false 는 통과가 아닙니다. |
| `components/History.tsx:296` | label | MOVE-TO-DETAILS | 거절 exit 3 | 거절 exit 3 |
| `components/History.tsx:297` | prose | MOVE-TO-DETAILS | exit 3 은 성공으로 표시하지 않습니다. | exit 3 은 성공으로 표시하지 않습니다. |
| `components/History.tsx:302` | label | KEEP | 비교를 거절했습니다 | 비교를 거절했습니다 |
| `components/History.tsx:317` | label | KEEP | 자리 글자 일치 | 자리 글자 일치 |
| `components/History.tsx:319` | label | KEEP | 자리 글자 불일치 | 자리 글자 불일치 |
| `components/History.tsx:321` | label | KEEP | 자리를 비교하지 않음 | 자리를 비교하지 않음 |
| `components/History.tsx:325` | label | MOVE-TO-DETAILS | 파일 전체 해시 일치: {String(compare.artifactEqual)} · 비교 기준 {compare.normalizer} | 파일 전체 해시 일치: {String(compare.artifactEqu… |
| `components/History.tsx:329` | label | KEEP | 비교 응답 | 비교 응답 |
| `components/History.tsx:359` | tooltip | KEEP | 아직 후보본이 없습니다 | 아직 후보본이 없습니다 |
| `components/History.tsx:360` | prose | KEEP | 승인하고 적용할 때마다 여기에 하나씩 쌓입니다. | 승인하고 적용할 때마다 여기에 하나씩 쌓입니다. |
| `components/History.tsx:376` | label | KEEP | 기록 | 기록 |
| `components/History.tsx:378` | prose | SHORTEN | 원본과 후보본을 시간순으로 봅니다. 되돌리기는 원본을 고치는 일이 아니라, | 되돌리기는 새 후보본을 제안합니다. 원본은 바뀌지 않습니다. |
| `components/History.tsx:379` | prose | DROP | 되돌리는 계획을 제안한 뒤 승인하고 적용하는 일입니다. | — (위 한 줄과 중복) |
| `components/History.tsx:389` | label | KEEP | 원본 | 원본 |
| `components/History.tsx:411` | label | KEEP | <summary>이벤트 ({eventCount})</summary> | <summary>이벤트 ({eventCount})</summary> |
| `components/History.tsx:417` | label | KEEP | 되돌리기를 만들지 못했습니다 | 되돌리기를 만들지 못했습니다 |
| `components/History.tsx:430` | label | KEEP | 되돌리기 확인됨 | 되돌리기 확인됨 |
| `components/History.tsx:432` | label | KEEP | 되돌아가지 않았습니다 | 되돌아가지 않았습니다 |
| `components/History.tsx:434` | label | KEEP | 확인하지 못했습니다 | 확인하지 못했습니다 |
| `components/History.tsx:440` | label | KEEP | 런타임이 …개 자리를 다시 읽어 되돌리기 이전 값과 같음을 확인했습니다. | 런타임이 …개 자리를 다시 읽어 되돌리기 이전 값과 같음을 확인했습니다. |
| `components/History.tsx:442` | prose | SHORTEN | 다시 읽은 값이 되돌리기 이전 값과 다릅니다. 이 후보본은 되돌리기가 아닙니다. | 다시 읽은 값이 되돌리기 이전 값과 다릅니다. 이 후보본은 되돌리기가 아… |
| `components/History.tsx:443` | prose | SHORTEN | 비교할 수 있는 자리가 없었습니다. 이것은 통과가 아닙니다. | 비교할 수 있는 자리가 없었습니다. |
| `components/History.tsx:446` | label | MOVE-TO-DETAILS | 파일 전체 해시 일치: {String(proof.compare.artifactEqual)} · 비교 기준{" "} | 파일 전체 해시 일치: {String(proof.compare.artif… |
| `components/History.tsx:450` | label | KEEP | 글자는 되돌아가도 파일 바이트까지 같아지지는 않습니다. 편집기가 XML을 | 글자는 되돌아가도 파일 바이트까지 같아지지는 않습니다. 편집기가 XML을 |
| `components/History.tsx:451` | prose | SHORTEN | 다시 쓰고 다시 압축하기 때문이고, 되돌리기가 실패했다는 뜻이 아닙니다. | 다시 쓰고 다시 압축하기 때문이고, 되돌리기가 실패했다는 뜻이 아닙니다. |
| `components/History.tsx:454` | label | RENAME | 런타임이 비교한 자리 | 엔진이 비교한 자리 |
| `components/Timeline.tsx:35` | label | KEEP | 문서를 열었습니다 — … (…) | 문서를 열었습니다 — … (…) |
| `components/Timeline.tsx:37` | label | KEEP | 작업 …건을 제안했습니다 — … | 작업 …건을 제안했습니다 — … |
| `components/Timeline.tsx:40` | label | KEEP | 쓰기 전 확인을 통과했습니다 | 쓰기 전 확인을 통과했습니다 |
| `components/Timeline.tsx:41` | label | KEEP | 쓰기 전 확인에서 막혔습니다 — … | 쓰기 전 확인에서 막혔습니다 — … |
| `components/Timeline.tsx:42` | label | KEEP | 승인을 요청했습니다 — … | 승인을 요청했습니다 — … |
| `components/Timeline.tsx:45` | label | KEEP | …이(가) 승인했습니다 | …이(가) 승인했습니다 |
| `components/Timeline.tsx:46` | label | KEEP | …이(가) 거절했습니다 | …이(가) 거절했습니다 |
| `components/Timeline.tsx:47` | label | KEEP | 계획을 사본에 적용했습니다 | 계획을 사본에 적용했습니다 |
| `components/Timeline.tsx:49` | label | MOVE-TO-DETAILS | `후보본을 남겼습니다 — ${String(d.sha256 ?? "").slice(0, 12)} · 검사 ${ | `후보본을 남겼습니다 |
| `components/Timeline.tsx:50` | label | KEEP | 통과 | 통과 |
| `components/Timeline.tsx:52` | label | KEEP | 페이지 그림용 PDF를 만들었습니다 — … | 페이지 그림용 PDF를 만들었습니다 — … |
| `components/Timeline.tsx:86` | label | KEEP | 원본 기록 | 원본 기록 |
| `components/Timeline.tsx:96` | label | KEEP | 알림 | 알림 |
| `components/Timeline.tsx:111` | label | KEEP | 문서에 일어난 일 | 문서에 일어난 일 |
| `components/Timeline.tsx:113` | tooltip | KEEP | 구독 … | 구독 … |
| `components/Timeline.tsx:114` | label | KEEP | 실시간 | 실시간 |
| `components/Timeline.tsx:117` | label | KEEP | 끊김 | 끊김 |
| `components/Timeline.tsx:119` | label | KEEP | 대기 | 대기 |
| `components/Timeline.tsx:139` | label | KEEP | 사건 기록을 구독하지 못했습니다 | 사건 기록을 구독하지 못했습니다 |
| `components/Timeline.tsx:145` | prose | KEEP | 아직 이 문서에 일어난 일이 없습니다. | 아직 이 문서에 일어난 일이 없습니다. |
| `components/Timeline.tsx:151` | label | SHORTEN | <summary>이 셸과 런타임이 주고받은 것 ({activity.length})</summary> | <summary>이 셸과 주고받은 것 ({activity.length})… |
| `components/Timeline.tsx:153` | prose | SHORTEN | 위쪽은 문서에 일어난 일이고, 여기는 그 일을 하려고 오간 말입니다. 진단용입니다. | 위쪽은 문서에 일어난 일이고, 여기는 그 일을 하려고 오간 말입니다. 진… |
| `components/Timeline.tsx:80` | label | MOVE-TO-DETAILS | event.kind 영어 태그 (session.opened 등) | 한국어 SAID 한 줄만. kind는 기술 정보. |

## 에이전트

Honesty (once): 에이전트는 계획만 냅니다. 승인은 사람이 합니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `components/Composer.tsx:31` | label | KEEP | 설정 열기 | 설정 열기 |
| `components/Composer.tsx:37` | prose | SHORTEN | 문서를 먼저 열어야 합니다. 에이전트는 열려 있는 문서에만 손을 댑니다. | 문서를 먼저 열어야 합니다. 에이전트는 열려 있는 문서에만 손을 댑니다. |
| `components/Composer.tsx:43` | label | RENAME | 지정하십시오. | 지정합니다. |
| `components/Composer.tsx:47` | label | KEEP | 앞의 지시를 아직 처리하고 있습니다. 한 번에 하나만 돕니다. | 앞의 지시를 아직 처리하고 있습니다. 한 번에 하나만 돕니다. |
| `components/Composer.tsx:54` | label | KEEP | 열쇠 없이 유료 제공자를 부르지는 않습니다. {settings} | 열쇠 없이 유료 제공자를 부르지는 않습니다. {settings} |
| `components/Composer.tsx:60` | label | KEEP | 지금은 보낼 수 없습니다. | 지금은 보낼 수 없습니다. |
| `components/Composer.tsx:99` | label | KEEP | 문서에 시킬 일을 여기에 씁니다. Ctrl+Enter 로 보냅니다. | 문서에 시킬 일을 여기에 씁니다. Ctrl+Enter 로 보냅니다. |
| `components/Composer.tsx:100` | label | KEEP | 문서에 시킬 일을 여기에 씁니다. | 문서에 시킬 일을 여기에 씁니다. |
| `components/Composer.tsx:133` | label | KEEP | 입력 중 … | 입력 중 … |
| `components/Composer.tsx:144` | label | KEEP | 보내기 | 보내기 |
| `components/Composer.tsx:150` | prose | SHORTEN | 에이전트는 계획만 냅니다. 승인과 적용은 에이전트 연결에 아예 없는 기능이라, | 에이전트는 계획만 냅니다. 승인은 사람이 합니다. |
| `components/Composer.tsx:151` | prose | DROP | 사람이 대기열에서 직접 승인해야 문서에 닿습니다. | — (위 한 줄과 중복) |
| `components/ContextPanel.tsx:265` | label | KEEP | 에이전트 | 에이전트 |
| `components/ContextPanel.tsx:433` | label | KEEP | 에이전트 | 에이전트 |
| `components/Conversation.tsx:22` | label | KEEP | 지시를 받았습니다 | 지시를 받았습니다 |
| `components/Conversation.tsx:25` | label | KEEP | 모델 쪽 준비 — … … | 모델 쪽 준비 — … … |
| `components/Conversation.tsx:27` | label | KEEP | 모델에 물었습니다 (…번째) | 모델에 물었습니다 (…번째) |
| `components/Conversation.tsx:31` | label | KEEP | 모델이 답했습니다 | 모델이 답했습니다 |
| `components/Conversation.tsx:32` | label | KEEP | 모델이 …건을 하겠다고 했습니다 | 모델이 …건을 하겠다고 했습니다 |
| `components/Conversation.tsx:34` | label | KEEP | 모델 쪽이 실패했습니다 — … | 모델 쪽이 실패했습니다 — … |
| `components/Conversation.tsx:35` | label | KEEP | 모델이 글자를 흘려보내는 중 | 모델이 글자를 흘려보내는 중 |
| `components/Conversation.tsx:36` | label | KEEP | … 를 요청했습니다 | … 를 요청했습니다 |
| `components/Conversation.tsx:37` | label | KEEP | 막았습니다 — … | 막았습니다 — … |
| `components/Conversation.tsx:38` | label | KEEP | … 로 옮겼습니다 | … 로 옮겼습니다 |
| `components/Conversation.tsx:39` | label | KEEP | … 가 돌아왔습니다 | … 가 돌아왔습니다 |
| `components/Conversation.tsx:40` | label | RENAME | 런타임이 거절했습니다 — … | 엔진이 거절했습니다 — … |
| `components/Conversation.tsx:42` | label | KEEP | 지시를 마쳤습니다 | 지시를 마쳤습니다 |
| `components/Conversation.tsx:61` | label | KEEP | 에이전트 호스트를 띄우는 중… | 에이전트 호스트를 띄우는 중… |
| `components/Conversation.tsx:97` | label | KEEP | 계획 {count}개 편집 도착 → 검토 탭에서 승인 | 계획 {count}개 편집 도착 → 검토 탭에서 승인 |
| `components/Conversation.tsx:130` | label | KEEP | 일하는 중 | 일하는 중 |
| `components/Conversation.tsx:132` | label | KEEP | 모델 쪽 문제 | 모델 쪽 문제 |
| `components/Conversation.tsx:134` | label | KEEP | 돌리지 못했습니다 | 돌리지 못했습니다 |
| `components/Conversation.tsx:136` | label | KEEP | 제안 도착 | 제안 도착 |
| `components/Conversation.tsx:138` | label | KEEP | 제안 없음 | 제안 없음 |
| `components/Conversation.tsx:143` | label | KEEP | · …턴 | · …턴 |
| `components/Conversation.tsx:173` | prose | SHORTEN | 문서에 대한 판정이 아닙니다. 계획과 승인 상태는 그대로입니다. | 문서에 대한 판정이 아닙니다. |
| `components/Conversation.tsx:210` | label | KEEP | 받지 못한 채 | 받지 못한 채 |
| `components/Conversation.tsx:211` | label | KEEP | 직접 승인해야 합니다. | 직접 승인해야 합니다. |
| `components/Conversation.tsx:215` | label | KEEP | 못했습니다. | 못했습니다. |
| `components/Conversation.tsx:216` | label | KEEP | 합니다. | 합니다. |
| `components/Conversation.tsx:220` | label | KEEP | 대기열에는 넣지 않았습니다. | 대기열에는 넣지 않았습니다. |
| `components/Conversation.tsx:221` | label | KEEP | 현재 상태에서 다시 요청해야 합니다. | 현재 상태에서 다시 요청해야 합니다. |
| `components/Conversation.tsx:230` | label | KEEP | 이 연결에 아예 없는 기능:{" "} | 이 연결에 아예 없는 기능:{" "} |
| `components/Conversation.tsx:237` | label | SHORTEN | 무엇을 했는지 (n건) · 원본 기록 (m) | 단계 n |
| `components/Conversation.tsx:272` | tooltip | KEEP | 아직 시킨 일이 없습니다 | 아직 시킨 일이 없습니다 |
| `components/Conversation.tsx:273` | prose | SHORTEN | 아래 칸에 문서로 할 일을 쓰면 에이전트가 계획을 냅니다. | 아래 칸에 문서로 할 일을 쓰면 에이전트가 계획을 냅니다. |
| `components/Conversation.tsx:279` | tooltip | KEEP | 에이전트가 연결되어 있지 않습니다 | 에이전트가 연결되어 있지 않습니다 |
| `components/Conversation.tsx:280` | prose | SHORTEN | 설정에서 에이전트 호스트를 연결하면 지시를 보낼 수 있습니다. | 설정에서 에이전트 호스트를 연결하면 지시를 보낼 수 있습니다. |
| `components/Conversation.tsx:281` | label | KEEP | 설정 열기 | 설정 열기 |
| `components/Conversation.tsx:290` | label | KEEP | 멈추기 | 멈추기 |
| `components/Conversation.tsx:303` | label | KEEP | 에이전트 제안 받기 | 에이전트 제안 받기 |
| `components/Conversation.tsx:306` | label | SHORTEN | 지시 없이, 내장 목 에이전트가 뻔한 한 칸을 채워 봅니다. 위 대화와 같은 대기열로 | 지시 없이, 내장 목 에이전트가 뻔한 한 칸을 채워 봅니다. 위 대화와… |
| `components/Conversation.tsx:307` | label | KEEP | 들어갑니다. | 들어갑니다. |
| `components/Conversation.tsx:315` | label | KEEP | 제안 도착 | 제안 도착 |
| `components/Conversation.tsx:322` | label | SHORTEN | <strong>{agentRun.proposer}</strong>이(가) 계획{" "} | <strong>{agentRun.proposer}</strong>이(가)… |
| `components/Conversation.tsx:325` | label | KEEP | 받지 못한 채 | 받지 못한 채 |
| `components/Conversation.tsx:327` | prose | SHORTEN | 멈췄습니다. 오른쪽 검토 대기열에서 사람이 직접 승인해야 합니다. | 멈췄습니다. |
| `components/Conversation.tsx:337` | label | KEEP | 에이전트를 돌리지 못했습니다 | 에이전트를 돌리지 못했습니다 |
| `components/DocumentContext.tsx:32` | label | KEEP | 대기 | 대기 |
| `components/DocumentContext.tsx:33` | label | KEEP | 승인됨 | 승인됨 |
| `components/DocumentContext.tsx:34` | label | KEEP | 거절됨 | 거절됨 |
| `components/DocumentContext.tsx:35` | label | KEEP | 없음 | 없음 |
| `components/DocumentContext.tsx:39` | label | KEEP | 일부 미실행 | 일부 미실행 |
| `components/DocumentContext.tsx:40` | label | KEEP | 적용 시 검사 통과 | 적용 시 검사 통과 |
| `components/DocumentContext.tsx:41` | label | KEEP | 적용 시 검사 걸림 | 적용 시 검사 걸림 |
| `components/DocumentContext.tsx:42` | label | KEEP | 실행 안 함 | 실행 안 함 |
| `components/DocumentContext.tsx:58` | label | KEEP | 문서 정보 | 문서 정보 |
| `components/DocumentContext.tsx:60` | prose | KEEP | 문서를 열면 여기에 문서의 상태가 모입니다. | 문서를 열면 여기에 문서의 상태가 모입니다. |
| `components/DocumentContext.tsx:64` | label | KEEP | 원본 | 원본 |
| `components/DocumentContext.tsx:66` | label | KEEP | 이름 | 이름 |
| `components/DocumentContext.tsx:67` | label | KEEP | 종류 | 종류 |
| `components/DocumentContext.tsx:68` | label | KEEP | 크기 | 크기 |
| `components/DocumentContext.tsx:70` | label | KEEP | 연 시각 | 연 시각 |
| `components/DocumentContext.tsx:76` | label | KEEP | 구조 | 구조 |
| `components/DocumentContext.tsx:78` | label | KEEP | 표 | 표 |
| `components/DocumentContext.tsx:79` | label | KEEP | 문단 | 문단 |
| `components/DocumentContext.tsx:80` | label | KEEP | 채움 자리 | 채움 자리 |
| `components/DocumentContext.tsx:81` | label | KEEP | 여백 칸 | 여백 칸 |
| `components/DocumentContext.tsx:83` | label | KEEP | 수식 자리 | 수식 자리 |
| `components/DocumentContext.tsx:84` | label | KEEP | 있음 | 있음 |
| `components/DocumentContext.tsx:87` | label | KEEP | 쪽 크기 | 쪽 크기 |
| `components/DocumentContext.tsx:91` | label | KEEP | 한 줄 글자 | 한 줄 글자 |
| `components/DocumentContext.tsx:92` | label | KEEP | …자 · …줄 | …자 · …줄 |
| `components/DocumentContext.tsx:99` | label | KEEP | 선택 | 선택 |
| `components/DocumentContext.tsx:101` | label | KEEP | 위치 | 위치 |
| `components/DocumentContext.tsx:102` | label | KEEP | 쪽 | 쪽 |
| `components/DocumentContext.tsx:103` | label | KEEP | 배율 | 배율 |
| `components/DocumentContext.tsx:108` | label | KEEP | 작업과 증명 | 작업과 증명 |
| `components/DocumentContext.tsx:111` | label | KEEP | 이 문서 작업 | 이 문서 작업 |
| `components/DocumentContext.tsx:112` | label | KEEP | 0건 | 0건 |
| `components/DocumentContext.tsx:114` | label | KEEP | 승인 | 승인 |
| `components/DocumentContext.tsx:116` | label | KEEP | 후보본 | 후보본 |
| `components/DocumentContext.tsx:125` | label | KEEP | 제출 검사 | 제출 검사 |
| `components/DocumentContext.tsx:126` | label | KEEP | 렌더 증명 | 렌더 증명 |
| `components/DocumentContext.tsx:129` | prose | SHORTEN | 승인은 검토 탭에서만 합니다. 에이전트 연결에는 그 기능이 없습니다. | 승인은 검토 탭에서만 합니다. 에이전트 연결에는 그 기능이 없습니다. |
| `devMock.ts:139` | label | KEEP | 브라우저 미리보기는 구조만 확인합니다. | 브라우저 미리보기는 구조만 확인합니다. |
| `devMock.ts:170` | label | KEEP | 행정안전부 | 행정안전부 |
| `devMock.ts:199` | prose | SHORTEN | 한 칸을 채우는 계획을 냈습니다. 승인은 검토 탭에서 해 주십시오. | 한 칸을 채우는 계획을 냈습니다. 승인은 검토 탭에서 합니다. |
| `devMock.ts:369` | label | KEEP | 브라우저 미리보기에는 작업 팩 등록기가 없습니다. | 브라우저 미리보기에는 작업 팩 등록기가 없습니다. |
| `devMock.ts:378` | prose | SHORTEN | 브라우저 미리보기 — mock provider만 응답합니다. | 브라우저 미리보기 — mock provider만 응답합니다. |
| `devMock.ts:381` | label | KEEP | 브라우저 미리보기 | 브라우저 미리보기 |
| `devMock.ts:416` | label | KEEP | 브라우저 미리보기에는 사이드카가 없습니다 | 브라우저 미리보기에는 사이드카가 없습니다 |
| `components/DocumentContext.tsx:69` | label | MOVE-TO-DETAILS | sha256 | 원본 확인 값 |

## popover

Honesty (once): 페이지 그림은 증거가 아닙니다. 해·pid는 여기에만.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `actions.ts:908` | label | KEEP | 이 위치가 한 글자의 가운데를 가릅니다. 그 글자를 쪼개서 고치지 않습니다 | 이 위치가 한 글자의 가운데를 가릅니다. 그 글자를 쪼개서 고치지 않습니다 |
| `actions.ts:1019` | label | KEEP | · …번째 글자 앞 | · …번째 글자 앞 |
| `actions.ts:2500` | label | KEEP | 칸의 글자로 잡음 | 칸의 글자로 잡음 |
| `actions.ts:3027` | label | KEEP | 검사 … | 검사 … |
| `actions.ts:3029` | error | SHORTEN | 이 검사는 실행되지 않았습니다: …. 실행되지 않은 검사는 통과로 세지 않습니다. | 이 검사는 실행되지 않았습니다: …. 실행되지 않은 검사는 통과로 세지… |
| `actions.ts:3039` | label | KEEP | 검사 … | 검사 … |
| `actions.ts:3048` | label | KEEP | 검사 … | 검사 … |
| `actions.ts:3075` | error | KEEP | 글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다. | 글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다. |
| `actions.ts:3084` | error | MOVE-TO-DETAILS | 글자 속성이 본문 기준과 다릅니다. charPr … → … 권장. | 글자 모양이 본문과 다릅니다. |
| `actions.ts:3129` | error | MOVE-TO-DETAILS | 글자 속성 …이(가) 기준과 다릅니다. charPr … → …. | 글자 모양이 본문과 다릅니다. |
| `actions.ts:3139` | error | SHORTEN | 이 빌드가 볼 수 있는 범위에서는 걸리는 것이 없습니다. 렌더 증명과 제출 검사는 아직 실행할 수 없습니다. | 볼 수 있는 범위에서는 걸리는 것이 없습니다. 렌더 증명과 제출 검사는… |
| `components/FillResults.tsx:25` | label | KEEP | 쪽 … | 쪽 … |
| `components/FillResults.tsx:27` | label | KEEP | 위치 없음 | 위치 없음 |
| `components/FillResults.tsx:49` | label | KEEP | 채우기 실행 | 채우기 실행 |
| `components/FillResults.tsx:59` | label | KEEP | 멈추기 | 멈추기 |
| `components/FillResults.tsx:65` | label | KEEP | 채우는 중 | 채우는 중 |
| `components/FillResults.tsx:67` | label | KEEP | 반복 {progress?.iteration ?? "…"} | 반복 {progress?.iteration ?? "…"} |
| `components/FillResults.tsx:70` | label | KEEP | 상태 {progress?.state ?? "…"} | 상태 {progress?.state ?? "…"} |
| `components/FillResults.tsx:134` | label | KEEP | 막힘 {counts.hard} · 주의 {counts.warn} | 막힘 {counts.hard} · 주의 {counts.warn} |
| `components/FillResults.tsx:138` | label | KEEP | 이 검사는 실행되지 않았습니다. | 이 검사는 실행되지 않았습니다. |
| `components/Findings.tsx:27` | aria | KEEP | 검사 결과 | 검사 결과 |
| `components/Findings.tsx:29` | label | KEEP | 검사 결과 | 검사 결과 |
| `components/Findings.tsx:31` | label | KEEP | 읽는 중 | 읽는 중 |
| `components/Findings.tsx:33` | label | KEEP | 검사 불가 | 검사 불가 |
| `components/Findings.tsx:35` | label | KEEP | 실행 안 함 | 실행 안 함 |
| `components/Findings.tsx:40` | label | KEEP | 걸림 없음 | 걸림 없음 |
| `components/Findings.tsx:50` | label | KEEP | 닫기 | 닫기 |
| `components/Findings.tsx:56` | prose | KEEP | 문서를 다시 읽고 있습니다. | 문서를 다시 읽고 있습니다. |
| `components/Findings.tsx:59` | label | KEEP | 검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다. | 검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다. |
| `components/Findings.tsx:63` | label | KEEP | 아직 검사를 실행하지 않았습니다. | 아직 검사를 실행하지 않았습니다. |
| `components/Findings.tsx:67` | label | KEEP | 검사에서 걸린 항목이 없습니다. | 검사에서 걸린 항목이 없습니다. |
| `components/Findings.tsx:83` | label | KEEP | 막힘 | 막힘 |
| `components/Findings.tsx:89` | prose | SHORTEN | 여기 있는 것은 이 빌드가 문서 구조와 서식에서 직접 읽어 낸 검사 결과입니다. | 여기 있는 것은 문서 구조와 서식에서 직접 읽어 낸 검사 결과입니다. |
| `components/Findings.tsx:90` | label | KEEP | 렌더 증명이나 후보본 적용 시의 제출 검사 결과를 뜻하지 않습니다. | 렌더 증명이나 후보본 적용 시의 제출 검사 결과를 뜻하지 않습니다. |
| `components/PosterResults.tsx:24` | label | KEEP | 쪽 … | 쪽 … |
| `components/PosterResults.tsx:26` | label | KEEP | 위치 없음 | 위치 없음 |
| `components/PosterResults.tsx:47` | label | KEEP | 포스터 만들기 | 포스터 만들기 |
| `components/PosterResults.tsx:53` | label | KEEP | 포스터 만드는 중 | 포스터 만드는 중 |
| `components/PosterResults.tsx:100` | label | KEEP | 막힘 {counts.hard} · 주의 {counts.warn} | 막힘 {counts.hard} · 주의 {counts.warn} |
| `components/PosterResults.tsx:104` | label | KEEP | 이 검사는 실행되지 않았습니다. | 이 검사는 실행되지 않았습니다. |
| `components/VerificationBar.tsx:22` | prose | SHORTEN | 후보본을 만들 때 돌린 검사입니다. 지금 다시 돌리는 버튼은 없습니다. | 후보본을 만들 때 돌린 검사입니다. 지금 다시 돌리는 버튼은 없습니다. |
| `components/VerificationBar.tsx:26` | prose | SHORTEN | 문서 엔진 연결 상태입니다. 프로세스 번호는 자세히에서 봅니다. | 문서 엔진 연결 상태입니다. |
| `components/VerificationBar.tsx:27` | prose | SHORTEN | 창이 강제 종료돼도 엔진 자식 프로세스를 함께 끝낼 수 있는지입니다. | 창이 강제 종료돼도 엔진 자식 프로세스를 함께 끝낼 수 있는지입니다. |
| `components/VerificationBar.tsx:28` | prose | SHORTEN | 승인·적용 후 생긴 사본입니다. 원본 파일은 그대로입니다. | 승인·적용 후 생긴 사본입니다. |
| `components/VerificationBar.tsx:29` | prose | SHORTEN | 연 파일의 해시입니다. 이 앱은 원본을 고치지 않습니다. | 연 파일의 해시입니다. |
| `components/VerificationBar.tsx:31` | prose | SHORTEN | 완성된 문서에서 문서 자체로 추정한 목록은 휴리스틱입니다. 빈 양식을 연결하면 판정이 정확해집니다. | 완성된 문서에서 문서 자체로 추정한 목록은 휴리스틱입니다. 빈 양식을 연… |
| `components/VerificationBar.tsx:42` | tooltip | KEEP | 이 세션은 연 문서가 아니라 연결한 빈 양식의 목록으로 잔여를 판정합니다. | 이 세션은 연 문서가 아니라 연결한 빈 양식의 목록으로 잔여를 판정합니다. |
| `components/VerificationBar.tsx:177` | label | KEEP | 자세히 | 자세히 |
| `components/VerificationBar.tsx:191` | label | KEEP | 쪽 | 쪽 |
| `components/VerificationBar.tsx:195` | label | KEEP | 그려진 지면의 쪽 번호입니다. | 그려진 지면의 쪽 번호입니다. |
| `components/VerificationBar.tsx:196` | label | SHORTEN | 본문 보기에는 쪽이 없습니다. 런타임은 글이 몇 쪽에 놓이는지 알려주지 않습니다. | 본문 보기에는 쪽이 없습니다. 글이 몇 쪽에 놓이는지 알려주지 않습니다. |
| `components/VerificationBar.tsx:209` | label | KEEP | 위치 | 위치 |
| `components/VerificationBar.tsx:247` | prose | SHORTEN | 이 지면은 한컴이 만든 PDF에서 읽은 것입니다. 글자 위치는 그 PDF 자신의 것입니다. | 이 지면은 한컴이 만든 PDF에서 읽은 것입니다. 글자 위치는 그 PDF… |
| `components/VerificationBar.tsx:275` | prose | SHORTEN | 이 줄은 렌더러가 글자별 위치를 내주지 않아, 커서를 줄 앞에 놓았습니다. 누른 자리에 놓은 것이 아닙니다. | 이 줄은 렌더러가 글자별 위치를 내주지 않아, 커서를 줄 앞에 놓았습니다… |
| `components/VerificationBar.tsx:276` | label | SHORTEN | 누른 자리에 커서를 놓았습니다. 몇 번째 글자인지는 런타임이 지면에서 읽어 준 글자별 위치로 정해집니다. | 누른 자리에 커서를 놓았습니다. 몇 번째 글자인지는 지면에서 읽어 준 글… |
| `components/VerificationBar.tsx:280` | prose | SHORTEN | 지면에서 누른 곳이 가리키는 주소입니다. 이 자리의 위치는 … 로 잡혔습니다. | 지면에서 누른 곳이 가리키는 주소입니다. 이 자리의 위치는 … 로 잡혔습… |
| `components/VerificationBar.tsx:302` | label | KEEP | 원본 | 원본 |
| `components/VerificationBar.tsx:308` | label | KEEP | 후보본 | 후보본 |
| `components/VerificationBar.tsx:337` | label | KEEP | 그림 증명 | 그림 증명 |
| `components/VerificationBar.tsx:382` | tooltip | SHORTEN | 지금 다시 돌린 검사가 본 문서입니다. 원본이거나 후보본 한 건입니다. | 지금 다시 돌린 검사가 본 문서입니다. 원본이거나 후보본 한 건입니다. |
| `components/VerificationBar.tsx:407` | tooltip | KEEP | 입력 칸 | 입력 칸 |
| `components/VerificationBar.tsx:409` | label | KEEP | 판정 기준 | 판정 기준 |
| `components/VerificationBar.tsx:441` | tooltip | KEEP | 엔진 | 엔진 |
| `components/VerificationBar.tsx:443` | label | KEEP | 엔진 | 엔진 |
| `components/VerificationBar.tsx:486` | tooltip | KEEP | 후보본과 영수증을 함께 저장합니다 | 후보본과 영수증을 함께 저장합니다 |
| `components/VerificationBar.tsx:573` | tooltip | KEEP | 쪽, 위치, 원본, 후보본 등 자세한 상태 | 쪽, 위치, 원본, 후보본 등 자세한 상태 |
| `components/VerificationBar.tsx:577` | label | KEEP | 자세히 | 자세히 |
| `components/VerificationBar.tsx:584` | aria | KEEP | 검사 자세히 | 검사 자세히 |
| `components/VerifyResults.tsx:22` | label | KEEP | 쪽 … | 쪽 … |
| `components/VerifyResults.tsx:24` | label | KEEP | 위치 없음 | 위치 없음 |
| `components/VerifyResults.tsx:36` | aria | KEEP | 검사 결과 | 검사 결과 |
| `components/VerifyResults.tsx:38` | label | KEEP | 검사 결과 | 검사 결과 |
| `components/VerifyResults.tsx:39` | label | KEEP | 검사 중 | 검사 중 |
| `components/VerifyResults.tsx:51` | label | KEEP | 닫기 | 닫기 |
| `components/VerifyResults.tsx:57` | label | KEEP | 오프라인 검사를 실행하는 중입니다. | 오프라인 검사를 실행하는 중입니다. |
| `components/VerifyResults.tsx:61` | label | KEEP | 검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다. | 검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다. |
| `components/VerifyResults.tsx:64` | prose | KEEP | 검사기가 반환한 행이 없습니다. | 검사기가 반환한 행이 없습니다. |
| `components/VerifyResults.tsx:85` | label | KEEP | 막힘 {counts.hard} · 주의 {counts.warn} | 막힘 {counts.hard} · 주의 {counts.warn} |
| `components/VerifyResults.tsx:90` | label | KEEP | 이 검사는 실행되지 않았습니다. 실행되지 않은 검사는 통과로 세지 않습니다. | 이 검사는 실행되지 않았습니다. 실행되지 않은 검사는 통과로 세지 않습니다. |
| `components/VerifyResults.tsx:94` | label | KEEP | <summary>지적 {findings.length}건</summary> | <summary>지적 {findings.length}건</summary> |
| `fillReport.ts:8` | prose | SHORTEN | 접촉면의 증명 등급은 fill_report가 보고한 값입니다. 렌더링 증명이 아닙니다. | 접촉면의 증명 등급은 fill_report가 보고한 값입니다. 렌더링 증… |
| `fillReport.ts:11` | label | KEEP | 증명 등급: … | 증명 등급: … |
| `posterReport.ts:8` | prose | SHORTEN | 미리보기 이미지, 증명 아님. 게이트는 poster-verify가 보고한 값입니다. | 미리보기 이미지, 증명 아님. 게이트는 poster-verify가 보고한… |
| `posterReport.ts:10` | label | KEEP | 미리보기 이미지, 증명 아님 | 미리보기 이미지, 증명 아님 |
| `verifyReport.ts:9` | prose | SHORTEN | 이 검사는 바이트와 오프라인 규칙만 봅니다. 렌더링 증명이 아닙니다. | 이 검사는 바이트와 오프라인 규칙만 봅니다. 렌더링 증명이 아닙니다. |
| `verifyReport.ts:39` | label | KEEP | 통과 | 통과 |
| `verifyReport.ts:40` | label | KEEP | 주의 | 주의 |
| `verifyReport.ts:41` | label | KEEP | 실패 | 실패 |
| `verifyReport.ts:42` | label | KEEP | 미실행 | 미실행 |
| `verifyReport.ts:57` | label | KEEP | 원본 | 원본 |
| `verifyReport.ts:58` | label | KEEP | 후보본 … | 후보본 … |
| `verifyReport.ts:107` | label | KEEP | 안내 색 정의가 header.xml에 남아 있습니다. | 안내 색 정의가 header.xml에 남아 있습니다. |
| `verifyReport.ts:108` | label | KEEP | 본문 서식이 기준과 다릅니다. | 본문 서식이 기준과 다릅니다. |
| `components/VerificationBar.tsx:453` | label | MOVE-TO-DETAILS | pid {n} · 패키지/개발 | 연결됨 |

## settings

Honesty (once): 열쇠는 화면에 다시 나오지 않습니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `actions.ts:3444` | error | KEEP | 먼저 자격 증명 이름을 정해야 합니다. | 먼저 자격 증명 이름을 정해야 합니다. |
| `actions.ts:3454` | toast | KEEP | 자격 증명을 이 기계의 저장소에 넣었습니다 | 자격 증명을 이 기계의 저장소에 넣었습니다 |
| `actions.ts:3500` | error | KEEP | 에이전트 호스트가 exit … 로 끝났습니다. | 에이전트 호스트가 exit … 로 끝났습니다. |
| `components/Settings.tsx:39` | label | KEEP | 내장 목 | 내장 목 |
| `components/Settings.tsx:40` | label | KEEP | 네트워크도 시계도 없는 결정론 제공자. 같은 문서면 같은 요청을 냅니다. | 네트워크도 시계도 없는 결정론 제공자. 같은 문서면 같은 요청을 냅니다. |
| `components/Settings.tsx:44` | label | KEEP | 커스텀 라우터 | 커스텀 라우터 |
| `components/Settings.tsx:45` | label | KEEP | OpenAI 호환 엔드포인트. 주소와 모델 이름을 직접 넣습니다. | OpenAI 호환 엔드포인트. 주소와 모델 이름을 직접 넣습니다. |
| `components/Settings.tsx:50` | label | SHORTEN | 공식 Messages API. 실제 호출은 열쇠를 넣고 지시를 보낼 때만 일어납니다. | 공식 Messages API. 실제 호출은 열쇠를 넣고 지시를 보낼 때만… |
| `components/Settings.tsx:55` | label | KEEP | 한 칸 제안 | 한 칸 제안 |
| `components/Settings.tsx:56` | label | KEEP | 쓰기 전 확인에서 막히는 제안 | 쓰기 전 확인에서 막히는 제안 |
| `components/Settings.tsx:57` | label | KEEP | 제안하고 승인 대기 | 제안하고 승인 대기 |
| `components/Settings.tsx:58` | label | KEEP | 적용까지 시도 (문 앞에서 막히는 것을 봅니다) | 적용까지 시도 (문 앞에서 막히는 것을 봅니다) |
| `components/Settings.tsx:63` | label | KEEP | 글 생성 | 글 생성 |
| `components/Settings.tsx:64` | label | KEEP | 도구 호출 | 도구 호출 |
| `components/Settings.tsx:65` | label | KEEP | 토막 전송 | 토막 전송 |
| `components/Settings.tsx:66` | label | KEEP | 구조화 출력 | 구조화 출력 |
| `components/Settings.tsx:67` | label | KEEP | 모델 목록 | 모델 목록 |
| `components/Settings.tsx:68` | label | KEEP | 대화 이어받기 | 대화 이어받기 |
| `components/Settings.tsx:69` | label | KEEP | 그림 입력 | 그림 입력 |
| `components/Settings.tsx:73` | label | KEEP | 예 | 예 |
| `components/Settings.tsx:74` | label | KEEP | 아니오 | 아니오 |
| `components/Settings.tsx:75` | label | KEEP | 모름 | 모름 |
| `components/Settings.tsx:86` | label | KEEP | 설정됨 | 설정됨 |
| `components/Settings.tsx:87` | label | KEEP | 없음 | 없음 |
| `components/Settings.tsx:88` | label | KEEP | 필요 없음 | 필요 없음 |
| `components/Settings.tsx:89` | label | KEEP | 이 방식은 아직 안 됩니다 | 이 방식은 아직 안 됩니다 |
| `components/Settings.tsx:98` | label | KEEP | 열쇠가 필요 없습니다 | 열쇠가 필요 없습니다 |
| `components/Settings.tsx:99` | label | KEEP | 환경 변수 이름으로 참조합니다 | 환경 변수 이름으로 참조합니다 |
| `components/Settings.tsx:100` | label | KEEP | 운영체제 저장소 키로 참조합니다 | 운영체제 저장소 키로 참조합니다 |
| `components/Settings.tsx:101` | label | KEEP | 제공자 쪽이 인증을 갖고 있습니다 | 제공자 쪽이 인증을 갖고 있습니다 |
| `components/Settings.tsx:152` | label | KEEP | 설정 — 에이전트 제공자 | 설정 — 에이전트 제공자 |
| `components/Settings.tsx:155` | label | KEEP | 닫기 (Esc) | 닫기 (Esc) |
| `components/Settings.tsx:161` | label | KEEP | 에이전트 호스트 | 에이전트 호스트 |
| `components/Settings.tsx:164` | label | KEEP | 찾음 | 찾음 |
| `components/Settings.tsx:171` | label | KEEP | 없음 | 없음 |
| `components/Settings.tsx:175` | prose | DROP | 제공자와 이야기하는 것은 이 별도 프로세스뿐입니다. 문서를 뜯어보는 쪽은 네트워크를 | 제공자와 이야기하는 것은 이 별도 프로세스뿐입니다. 문서를 뜯어보는 쪽은… |
| `components/Settings.tsx:176` | label | KEEP | 모릅니다. | 모릅니다. |
| `components/Settings.tsx:181` | label | KEEP | 제공자 | 제공자 |
| `components/Settings.tsx:182` | aria | KEEP | 제공자 | 제공자 |
| `components/Settings.tsx:201` | label | KEEP | 어떤 대본을 돌릴지 | 어떤 대본을 돌릴지 |
| `components/Settings.tsx:216` | label | SHORTEN | 열쇠도 네트워크도 쓰지 않습니다. 같은 문서에 같은 대본이면 같은 요청이 나옵니다. | 열쇠도 네트워크도 쓰지 않습니다. 같은 문서에 같은 대본이면 같은 요청이… |
| `components/Settings.tsx:223` | label | KEEP | 라우터 | 라우터 |
| `components/Settings.tsx:225` | label | KEEP | 주소 | 주소 |
| `components/Settings.tsx:236` | label | KEEP | 모델 | 모델 |
| `components/Settings.tsx:246` | label | KEEP | 자격 증명 이름 | 자격 증명 이름 |
| `components/Settings.tsx:262` | label | KEEP | 모델 | 모델 |
| `components/Settings.tsx:267` | label | KEEP | 비워 두면 어댑터의 기본값 | 비워 두면 어댑터의 기본값 |
| `components/Settings.tsx:278` | label | KEEP | 자격 증명 이름 | 자격 증명 이름 |
| `components/Settings.tsx:291` | label | SHORTEN | 모델 이름을 비워 두면 어댑터가 고른 기본값을 씁니다. 여기에 기본값을 베껴 두면 | 모델 이름을 비워 두면 어댑터가 고른 기본값을 씁니다. 여기에 기본값을… |
| `components/Settings.tsx:292` | label | KEEP | 어댑터가 옮겨 갔을 때 이쪽만 낡습니다. | 어댑터가 옮겨 갔을 때 이쪽만 낡습니다. |
| `components/Settings.tsx:300` | label | KEEP | 설정 저장 | 설정 저장 |
| `components/Settings.tsx:307` | label | KEEP | 자격 증명 | 자격 증명 |
| `components/Settings.tsx:309` | label | SHORTEN | 값은 이 기계의 Windows 자격 증명 관리자에만 들어갑니다. 설정 파일에는 이름만 | 값은 이 기계의 Windows 자격 증명 관리자에만 들어갑니다. 설정 파… |
| `components/Settings.tsx:310` | label | KEEP | 적히고, 화면으로 다시 나오지 않습니다. | 적히고, 화면으로 다시 나오지 않습니다. |
| `components/Settings.tsx:313` | label | KEEP | 현재 상태:{" "} | 현재 상태:{" "} |
| `components/Settings.tsx:316` | label | KEEP | 저장됨 | 저장됨 |
| `components/Settings.tsx:318` | label | KEEP | {credential.key} · {credential.bytes}바이트 | {credential.key} · {credential.bytes}바이트 |
| `components/Settings.tsx:323` | label | KEEP | 없음 | 없음 |
| `components/Settings.tsx:324` | label | KEEP | 이름 없음 | 이름 없음 |
| `components/Settings.tsx:329` | label | KEEP | 값 붙여넣기 | 값 붙여넣기 |
| `components/Settings.tsx:336` | label | KEEP | 여기에 붙여넣으면 곧바로 저장소로 갑니다 | 여기에 붙여넣으면 곧바로 저장소로 갑니다 |
| `components/Settings.tsx:351` | label | KEEP | 저장소에 넣기 | 저장소에 넣기 |
| `components/Settings.tsx:359` | label | KEEP | 지우기 | 지우기 |
| `components/Settings.tsx:367` | label | KEEP | 연결 확인 | 연결 확인 |
| `components/Settings.tsx:375` | label | KEEP | 연결 확인 | 연결 확인 |
| `components/Settings.tsx:378` | label | SHORTEN | 어댑터에게 “무엇을 할 수 있나”만 묻습니다. 문서도 네트워크도 건드리지 않습니다. | 어댑터에게 “무엇을 할 수 있나”만 묻습니다. 문서도 네트워크도 건드리지… |
| `components/Settings.tsx:401` | label | KEEP | 자격 증명 참조:{" "} | 자격 증명 참조:{" "} |
| `components/Settings.tsx:431` | prose | DROP | 모름은 아니오가 아닙니다. 어댑터가 확인하지 않았다는 뜻이고, 확인되지 않은 | 모름은 아니오가 아닙니다. 어댑터가 확인하지 않았다는 뜻이고, 확인되지 않은 |
| `components/Settings.tsx:432` | label | KEEP | 기능은 시도하지 않습니다. | 기능은 시도하지 않습니다. |
| `components/Settings.tsx:436` | prose | DROP | 토막 전송이 “예”여도 이 슬라이스에서는 글이 한 번에 옵니다. 호스트의 턴 | — (프로토콜 메모. 표가 이미 모름/예를 보여 줌) |
| `components/Settings.tsx:437` | label | SHORTEN | 루프가 아직 어댑터의 stream() 을 부르지 않습니다 — 진행 상황만 실시간으로 | 루프가 아직 어댑터의 stream() 을 부르지 않습니다 |
| `components/Settings.tsx:438` | label | KEEP | 흐릅니다. | 흐릅니다. |
| `components/Settings.tsx:446` | label | KEEP | 이 제공자가 읽을 설정 파일 | 이 제공자가 읽을 설정 파일 |
| `components/Settings.tsx:452` | prose | DROP | 여기에 값이 들어 있지 않다는 것을 직접 보십시오. 이름뿐입니다. | — |

## receipt

Honesty (once): 원본은 바뀌지 않습니다. 해시는 기술 정보입니다.

| loc | class | action | current | rewrite |
|---|---|---|---|---|
| `components/ReceiptPanel.tsx:43` | label | KEEP | 검사 | 검사 |
| `components/ReceiptPanel.tsx:46` | label | KEEP | 받아들일 수 있음 | 받아들일 수 있음 |
| `components/ReceiptPanel.tsx:49` | label | KEEP | 받아들일 수 없음 | 받아들일 수 없음 |
| `components/ReceiptPanel.tsx:53` | label | KEEP | 필수 검사 모두 실행됨 | 필수 검사 모두 실행됨 |
| `components/ReceiptPanel.tsx:55` | label | KEEP | 실행되지 않은 필수 검사 있음 | 실행되지 않은 필수 검사 있음 |
| `components/ReceiptPanel.tsx:61` | label | KEEP | 판정 기준 | 판정 기준 |
| `components/ReceiptPanel.tsx:64` | label | KEEP | 연결된 양식${receipt.residue.sha256 ? | 연결된 양식${receipt.residue.sha256 ? |
| `components/ReceiptPanel.tsx:66` | label | KEEP | 문서 자체 추정 | 문서 자체 추정 |
| `components/ReceiptPanel.tsx:71` | label | KEEP | 남긴 항목 | 남긴 항목 |
| `components/ReceiptPanel.tsx:85` | label | KEEP | 걸림 없음 | 걸림 없음 |
| `components/ReceiptPanel.tsx:87` | label | KEEP | 걸림 있음 | 걸림 있음 |
| `components/ReceiptPanel.tsx:90` | label | KEEP | 실행 안 됨 | 실행 안 됨 |
| `components/ReceiptPanel.tsx:100` | prose | DROP | 이 판정은 후보본을 만들 때 런타임이 실제로 돌린 오프라인 검사 결과입니다. 지금 다시 | 이 판정은 후보본을 만들 때 실제로 돌린 오프라인 검사 결과입니다. 지금… |
| `components/ReceiptPanel.tsx:102` | label | KEEP | 없습니다. | 없습니다. |
| `components/ReceiptPanel.tsx:116` | aria | KEEP | 영수증 | 영수증 |
| `components/ReceiptPanel.tsx:118` | label | KEEP | 영수증 | 영수증 |
| `components/ReceiptPanel.tsx:126` | label | KEEP | 닫기 | 닫기 |
| `components/ReceiptPanel.tsx:133` | label | KEEP | 영수증을 읽지 못했습니다 | 영수증을 읽지 못했습니다 |
| `components/ReceiptPanel.tsx:137` | label | SHORTEN | 영수증은 자기가 묶어 둔 바이트가 그대로일 때만 내용을 내놓습니다. 읽히지 않는다는 | 영수증은 자기가 묶어 둔 바이트가 그대로일 때만 내용을 내놓습니다. 읽히… |
| `components/ReceiptPanel.tsx:138` | label | KEEP | 것은 그 자체로 답입니다. | 것은 그 자체로 답입니다. |
| `components/ReceiptPanel.tsx:142` | prose | KEEP | 영수증을 읽는 중입니다. | 영수증을 읽는 중입니다. |
| `components/ReceiptPanel.tsx:146` | label | KEEP | 바이트 | 바이트 |
| `components/ReceiptPanel.tsx:148` | label | KEEP | 원본 | 원본 |
| `components/ReceiptPanel.tsx:153` | label | KEEP | 후보본 | 후보본 |
| `components/ReceiptPanel.tsx:158` | label | KEEP | 역할 | 역할 |
| `components/ReceiptPanel.tsx:162` | prose | SHORTEN | 원본은 입력이었을 뿐 결과가 아닙니다. 모든 단계는 파일 하나를 읽고 다른 파일을 | 원본은 입력이었을 뿐 결과가 아닙니다. 모든 단계는 파일 하나를 읽고 다… |
| `components/ReceiptPanel.tsx:163` | label | KEEP | 씁니다. | 씁니다. |
| `components/ReceiptPanel.tsx:168` | label | KEEP | 계획 | 계획 |
| `components/ReceiptPanel.tsx:178` | label | KEEP | 거절 exit 3 | 거절 exit 3 |
| `components/ReceiptPanel.tsx:189` | label | KEEP | 거절 exit 3 | 거절 exit 3 |
| `components/ReceiptPanel.tsx:190` | prose | KEEP | 이 단계는 성공으로 표시하지 않습니다. | 이 단계는 성공으로 표시하지 않습니다. |
| `components/ReceiptPanel.tsx:196` | label | KEEP | 승인 | 승인 |
| `components/ReceiptPanel.tsx:198` | label | KEEP | 결정 | 결정 |
| `components/ReceiptPanel.tsx:201` | label | KEEP | 승인 | 승인 |
| `components/ReceiptPanel.tsx:204` | label | KEEP | 승인한 사람 | 승인한 사람 |
| `components/ReceiptPanel.tsx:206` | label | KEEP | 요청한 쪽 | 요청한 쪽 |
| `components/ReceiptPanel.tsx:208` | label | KEEP | 결정 시각 | 결정 시각 |
| `components/ReceiptPanel.tsx:210` | label | KEEP | 묶인 계획 | 묶인 계획 |
| `components/ReceiptPanel.tsx:220` | label | KEEP | 증거 등급 | 증거 등급 |
| `components/ReceiptPanel.tsx:227` | label | KEEP | 자세히 | 자세히 |

## Glossary — ten terms (same word everywhere)

| term | means | never on the primary surface |
|---|---|---|
| **후보본** | 승인·적용 뒤에 생긴 사본. 원본 옆의 새 파일. | artifact, candidate, 사본(alone) |
| **영수증** | 그 후보본이 어떻게 생겼는지의 기록. | receipt JSON as the story |
| **입력 칸** | 값을 넣도록 열린 칸. | 채움 자리 / seat / fill_target on chrome (채움 is a classification chip only) |
| **승인** | 사람이 계획에 동의함. 문서는 아직 그대로. | 게이트, approval_request, 지문에 대한 결정 |
| **적용** | 승인된 계획을 후보본으로 씀. | apply, plan/apply |
| **원본** | 연 파일. 이 앱은 고치지 않음. | source, 세션 사본 |
| **양식** | 빈 양식 또는 그 목록으로 판정하는 기준. | form_profile.json, bound_form |
| **계획** | 대기 중인 편집 묶음. | plan id, 지문, hash on buttons |
| **검사** | 오프라인 서식·규칙 점검. 제출 증명이 아님. | verify/*, candidate/verify, structural_only |
| **에이전트** | 계획을 내는 쪽. 승인 권한 없음. | 에이전트 호스트, agenthost-mock, host-operator |

Related chips (not the ten, but lock them): **거절** (not 거부), **엔진** (connection; 런타임 stays in 기술 정보), **막힘** / **주의** / **통과** (checker), **대기** (queued).

## Register rules

1. **합니다체 only.** No 하세요 / 하십시오 / 해 주십시오 / 넣으십시오 / 해 줍니다 / 보여 줍니다. Commands are the CTA noun (열기, 승인) or a 합니다 sentence.
2. **Human word on chrome; technical truth one click away.** charPr, hash, plan id, pid, forbidden, structural_only, runtime, exit N, MCP include → tooltip or 기술 정보. Never toast, never primary button.
3. **One honesty line per surface.** Repeats DROP. The three promises stay: 페이지 그림은 증거가 아닙니다 / 승인은 사람이 합니다 / 원본은 바뀌지 않습니다.
4. **Show, don't explain.** If the queue already lists ops, do not open with a paragraph about what a queue is. Empty state = one title + one sentence + optional action.
5. **Addresses are human.** `표 1 · 5행 2열`, not `R5C2` / `at_para 12` on the tree. Machine addresses in 기술 정보.
6. **Hashes never in toasts or 모두 승인.** Short hash only under 기술 정보, with 복사.
7. **거부 → 거절** everywhere (hunk footer, state chip). 거절됨 / 승인됨 / 적용됨 / 대기.
8. **연결 상태는 엔진.** 런타임 끊김 → 엔진 끊김. pid only in 자세히.
9. **입력 칸** for seats on chrome and tree group; **채움** only as the classification tag.
10. **검사기** is a checker row, not the inspector. Inspector aria: `문서 정보` or `패널`, never 검사기.

## Notes for F1–F5

- Toolbar still has two zoomers and a 서식 menu that prints `charPr {id}` when the face is missing — F1/F2.
- 모두 승인 currently concatenates count + hash; F3 should be 모두 승인 only.
- Agent thread prints every tool event and a protocol `neverCompiled` line; F4 collapses chatter.
- Home lede and composer footnote are the same product sentence twice; keep it on home, drop from composer after first-run.

## Counts (this note)

Rows: **1090** authored UI strings in the tables (Hangul inventory plus English/mixed extras). `smoke.ts` excluded.

| class | n |
|---|---|
| label | 833 |
| prose | 111 |
| tooltip | 75 |
| aria | 34 |
| toast | 22 |
| error | 16 |

| action | n |
|---|---|
| KEEP | 873 |
| SHORTEN | 141 |
| RENAME | 31 |
| MOVE-TO-DETAILS | 26 |
| DROP | 16 |
| MOVE-TO-TOOLTIP | 3 |

(KEEP is high because short CTAs — 열기, 닫기, 승인, 통과 — stay. The work is the prose walls and tech-on-chrome rows.)

### Five worst offenders

1. **검토 승인 대기 카드** (`ReviewQueue.tsx:517–536`) — orange prose wall: 지문, 요청자 id, “승인하면 이 계획 지문에 대한 결정만…”. Compact to 승인/거절 + one honesty line.
2. **구조 트리 forbidden 공백** (`StructureTree.tsx:356–361`) — `forbidden`, MCP include, protocol enum on the primary tree. One line in 기술 정보.
3. **기록 도입 + 비교 프로토콜** (`History.tsx:225–228`, `377–379`) — “원본과 후보본을 시간순으로…”, `candidate/compare`, `verify/*`, run hashes as row titles.
4. **에이전트 스레드** (`Composer.tsx:150` + `Conversation.tsx:206–237`) — protocol footnote, plan hash, `neverCompiled`, every tool event. Placeholder only; chatter under 단계.
5. **툴바 글자 모양** (`EditorToolbar.tsx:375–425`) — `charPr 11 → 23` on the strip; check tooltip still explains render proof. Face name on chrome, ids in 서식 메뉴.


