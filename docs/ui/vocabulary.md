# 화면 용어 대응표 (UI Vocabulary)

이 문서는 `desktop/src/i18n/vocabulary.ts`와 1:1로 대응하는 한국어·영어 단일 언어 화면 문구 기준표입니다.

## 작성 및 표시 원칙

1. 한국어와 영어는 번역 대응표로 관리하며, 같은 화면 요소에 두 언어를 동시에 표시하지 않습니다.
2. 상태·안내·오류 문장은 합니다체를 사용하고, 버튼·제목·목록 항목 이름은 명사형으로 통일합니다.
3. 문장형 상태에는 마침표를 생략하고, 안내·오류·대화상자 본문에는 마침표를 씁니다.
4. 사람의 결정은 `승인`과 `돌려보내기`, 승인 전 내용은 `변경 제안`, 목록 건수는 `변경 {0}건`, 승인 후 반영은 `적용`, 저장된 결과는 `수정본`으로 통일합니다.
5. 한국어 문구에는 영문 알파벳을 섞지 않으며, 변수 치환에는 번호 자리표시자(`{0}`, `{1}`)를 사용합니다.
6. 내부 동작 이름·오류 코드·검증 세부 키는 기본 화면에 노출하지 않고 펼친 자세히 영역에만 둡니다.

## 1. 편집 작업 종류 (`OP_KIND_VOCAB` / `OP_KIND_MODE_VOCAB`)

문서 편집 계획의 작업 종류(`op.kind`)와 세부 방식(`mode`)을 화면 문구로 변환합니다.

| Key | Korean | English |
| :--- | :--- | :--- |
| `fill_cell` | 빈칸 채움 | Fill blank |
| `replace_at_cell` | 칸 문구 바꿈 | Replace cell text |
| `set_run` | 본문 문구 바꿈 | Replace body text |
| `delete_guides` | 안내문 지움 | Remove guide text |
| `normalize_clones` | 중복 글자 서식 정리 | Clean up duplicate text styles |
| `goto_text` | 문구 위치로 이동 | Jump to text |
| `insert_text` | 문구 넣기 | Insert text |
| `insert_equation` | 수식 넣기 | Insert equation |
| `insert_table` | 표 넣기 | Insert table |
| `page_binding` | 제본 여백 조정 | Set binding margin |
| `replace_all` | 문구 일괄 바꿈 | Replace all occurrences |
| `insert_blank_before` | 앞에 빈 줄 넣기 | Insert blank line above |
| `insert_picture` | 그림 넣기 | Insert image |
| `set_line_spacing` | 줄 간격 조정 | Adjust line spacing |
| `put_field` | 누름틀 값 채움 | Fill form field |
| `find_delete` | 문구 찾아 지움 | Find and remove text |
| `move` | 커서 이동 | Move cursor |
| `edit_equation` | 수식 고침 | Edit equation |
| `set_cell` | 표 칸 내용 입력 | Enter table cell content |
| `set_char_color` | 글자 색 바꿈 | Change text colour |
| `delete_ctrls` | 개체 삭제 | Remove objects |
| `collapse_empty_paragraphs` | 연속 빈 줄 합침 | Collapse blank lines |
| `delete_blank_after` | 뒤쪽 빈 줄 지움 | Remove blank line below |
| `delete_blank_before` | 앞쪽 빈 줄 지움 | Remove blank line above |
| `set_para_align` | 문단 정렬 바꿈 | Change paragraph alignment |
| `insert_hyperlink` | 웹 링크 넣기 | Insert web link |
| `page_break_before` | 앞쪽 쪽 나누기 | Insert page break before |
| `replace_at_cell:replace` | 칸 문구 바꿈 | Replace cell text |
| `replace_at_cell:append` | 칸 문구 덧붙임 | Append to cell |

## 2. 계획·규칙·점검·승인·화면 상태 (`PLAN_STATE_VOCAB` 외)

계획, 규칙 검증, 점검 결과, 승인 결정, 인쇄 등급, 칸 분류 상태를 단일 언어로 표시합니다.

| Key | Korean | English |
| :--- | :--- | :--- |
| `proposed` | 제안이 도착했습니다 | Proposed |
| `validated` | 검토 중입니다 | In review |
| `invalid` | 수정이 필요합니다 | Needs fixes |
| `approved` | 승인했습니다 | Approved |
| `rejected` | 돌려보냈습니다 | Returned |
| `applied` | 적용했습니다 | Applied |
| `clean` | 제출 전 점검을 통과했습니다 | Pre-submission check passed |
| `warn` | 추가 확인이 필요합니다 | Needs review |
| `hard` | 수정 후 적용할 수 있습니다 | Fix issues before applying |
| `skipped` | 점검하지 않았습니다 | Check skipped |
| `ran` | 점검을 마쳤습니다 | Check complete |
| `unavailable` | 지금은 점검할 수 없습니다 | Check unavailable |
| `not_run` | 아직 점검하지 않았습니다 | Not checked yet |
| `pass` | 제출 전 점검을 통과했습니다 | Pre-submission check passed |
| `partial` | 추가 확인이 필요합니다 | Needs review |
| `fail` | 수정 후 적용할 수 있습니다 | Fix issues before applying |
| `pending` | 승인을 기다리고 있습니다 | Awaiting approval |
| `auto_approved` | 규칙에 따라 자동 승인했습니다 | Automatically approved by rule |
| `hancom` | 한글 인쇄 화면 | Hancom print view |
| `pdf` | 인쇄 화면 | Print view |
| `own-uncertified` | 자체 미리보기 · 인쇄 결과와 대조하지 않았습니다. | Rigorloom preview · Not checked against printed output. |
| `fill_target` | 입력할 빈칸 | Blank to fill |
| `static` | 이 칸은 입력용 빈칸이 아닙니다. | This cell is not a fillable blank. |
| `guide` | 작성 안내문 | Form instructions |
| `spacer` | 여백용 칸 | Spacing cell |

## 3. 사실 변경 점검 범주 (`GUARD_CATEGORY_VOCAB`)

수정한 문단에서 숫자·날짜·인용문·부정 표현·증감 및 방향 표현 등 점검 대상 범주의 변경 여부를 표시합니다.

| Key | Korean | English |
| :--- | :--- | :--- |
| `paragraph_count_changed` | 문단 수가 바뀌었습니다 | Paragraph count changed |
| `numbers` | 바뀐 숫자 | Changed number |
| `dates` | 바뀐 날짜 | Changed date |
| `direct_quotes` | 바뀐 인용문 | Changed quotation |
| `qualifiers` | 바뀐 부정·한정 표현 | Changed negation or qualifier |
| `quantifiers` | 바뀐 수량 표현 | Changed quantity expression |
| `causal_markers` | 바뀐 인과 표현 | Changed causal phrasing |
| `direction_words` | 바뀐 증감·방향 표현 | Changed increase, decrease, or direction |
| `urls` | 바뀐 웹 주소 | Changed web address |
| `markdown_links` | 바뀐 웹 주소 | Changed web address |
| `citations` | 바뀐 출처 표기 | Changed citation |
| `source_ids` | 바뀐 출처 표기 | Changed citation |
| `inline_math` | 바뀐 수식 | Changed formula |
| `headings` | 바뀐 제목·태그·보호 문구 | Changed heading, tag, or protected text |
| `tags` | 바뀐 제목·태그·보호 문구 | Changed heading, tag, or protected text |
| `protected_spans` | 바뀐 제목·태그·보호 문구 | Changed heading, tag, or protected text |

## 4. 오류 및 거부 코드 (`ERROR_CODE_VOCAB`)

전송·도메인 오류 코드와 계획 검증 거부 코드를 사용자 안내 문장으로 바꿉니다. 내부 코드는 펼친 자세히 영역에만 표시합니다.

| Key | Korean | English |
| :--- | :--- | :--- |
| `protocol_version_unsupported` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `not_initialized` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `already_initialized` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `frame_too_large` | 문서나 선택 영역이 너무 커서 한 번에 불러올 수 없습니다. | The document or selection is too large to load at once. |
| `frame_malformed` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `duplicate_key` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `nonfinite_number` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `unknown_field` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `unknown_method` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `invalid_params` | 입력한 변경 내용을 확인해야 합니다. | Check the change details. |
| `duplicate_request_id` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `response_too_large` | 문서나 선택 영역이 너무 커서 한 번에 불러올 수 없습니다. | The document or selection is too large to load at once. |
| `cancelled` | 작업을 취소했습니다. | Task cancelled. |
| `internal_error` | 작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not complete the task. See details for the cause. |
| `unknown_session` | 열려 있던 문서를 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the open document. Reopen it. |
| `unknown_plan` | 변경 제안이나 승인 요청을 찾을 수 없습니다. | Could not find the proposed changes or approval request. |
| `unknown_approval` | 변경 제안이나 승인 요청을 찾을 수 없습니다. | Could not find the proposed changes or approval request. |
| `unknown_op_kind` | 현재 환경에서는 이 편집을 지원하지 않습니다. | This edit is not supported in the current environment. |
| `unsupported_backend` | 현재 환경에서는 이 편집을 지원하지 않습니다. | This edit is not supported in the current environment. |
| `plan_stale` | 문서가 바뀌었습니다. 최신 문서에 맞춰 변경 제안을 다시 만들어야 합니다. | The document has changed. Recreate the proposed changes using the latest version. |
| `plan_not_approved` | 승인 후 적용할 수 있습니다. | Approve the changes before applying them. |
| `apply_in_progress` | 변경 내용을 문서에 적용하고 있습니다. | Applying changes to the document. |
| `apply_outcome_unknown` | 적용을 마쳤는지 확인할 수 없습니다. 기록에서 적용 여부를 확인해야 합니다. | Could not confirm whether the changes were applied. Check history for the result. |
| `plan_invalid` | 수정할 항목이 있어 아직 적용할 수 없습니다. | Resolve the flagged items before applying the changes. |
| `approval_binding_mismatch` | 승인한 뒤 문서나 변경 제안이 바뀌었습니다. 다시 검토하고 승인해야 합니다. | The document or proposed changes have changed since approval. Review and approve them again. |
| `approval_already_resolved` | 이미 처리한 승인 요청입니다. | This approval request has already been resolved. |
| `region_too_large` | 문서나 선택 영역이 너무 커서 한 번에 불러올 수 없습니다. | The document or selection is too large to load at once. |
| `source_rejected` | 지원하지 않거나 변환할 수 없는 파일입니다. 지원하는 형식의 문서를 선택해야 합니다. | This file is unsupported or cannot be converted. Choose a supported document. |
| `path_escape` | 허용된 작업 폴더 밖의 파일은 열 수 없습니다. | Cannot access files outside the allowed workspace folder. |
| `artifact_missing` | 문서 파일을 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the document file. Reopen the document. |
| `candidate_hash_mismatch` | 저장된 수정본이나 검증 기록이 일치하지 않습니다. | The saved revision or verification record does not match. |
| `receipt_body_mismatch` | 저장된 수정본이나 검증 기록이 일치하지 않습니다. | The saved revision or verification record does not match. |
| `capability_unavailable` | 현재 환경에서는 이 편집을 지원하지 않습니다. | This edit is not supported in the current environment. |
| `publication_failed` | 작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not complete the task. See details for the cause. |
| `backend_refused` | 현재 환경에서는 이 편집을 지원하지 않습니다. | This edit is not supported in the current environment. |
| `child_python_invalid` | 작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not complete the task. See details for the cause. |
| `render_failed` | 요청한 인쇄 화면을 표시할 수 없습니다. | Cannot display the requested print view. |
| `page_out_of_range` | 요청한 인쇄 화면을 표시할 수 없습니다. | Cannot display the requested print view. |
| `unknown_subscription` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `subscription_limit` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `com_busy` | 한글에서 다른 작업을 처리하고 있습니다. 잠시 후 다시 시도할 수 있습니다. | Hancom Office is busy. Try again shortly. |
| `needs_hancom` | 파일을 변환할 수 없습니다. 한글에서 지원하는 형식으로 다시 저장한 뒤 열어야 합니다. | Could not convert the file. Save it as .hwpx in Hancom Office, then open it again. |
| `convert_failed` | 파일을 변환할 수 없습니다. 한글에서 지원하는 형식으로 다시 저장한 뒤 열어야 합니다. | Could not convert the file. Save it as .hwpx in Hancom Office, then open it again. |
| `not_convertible` | 지원하지 않거나 변환할 수 없는 파일입니다. 지원하는 형식의 문서를 선택해야 합니다. | This file is unsupported or cannot be converted. Choose a supported document. |
| `ambiguous_fill_keys` | 이름이 같은 빈칸이 여러 개 있습니다. 입력할 칸을 구분해야 합니다. | Multiple blanks have the same label. Identify the blank to fill. |
| `bad_input` | 입력한 변경 내용을 확인해야 합니다. | Check the change details. |
| `bad_address` | 문서에서 지정한 위치를 찾을 수 없습니다. | Could not find the specified location in the document. |
| `not_found` | 문서 파일을 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the document file. Reopen the document. |
| `stale` | 처음 읽은 뒤 문서가 바뀌었습니다. 문서를 다시 읽어야 합니다. | The document has changed since it was read. Read it again. |
| `busy` | 다른 작업이 이 문서를 쓰고 있습니다. 잠시 후 다시 시도할 수 있습니다. | Another task is writing this document. Try again shortly. |
| `locked` | 다른 프로그램에서 이 문서를 열고 있습니다. 그 프로그램에서 닫은 뒤 다시 시도할 수 있습니다. | Another program has this document open. Close it there, then try again. |
| `expect_mismatch` | 바꾸려는 문구가 예상한 내용과 다릅니다. | The text to change differs from what was expected. |
| `ambiguous_match` | 같은 문구가 여러 곳에 있어 바꿀 위치를 정할 수 없습니다. | The same text appears in more than one place. Could not tell which one to change. |
| `conflict` | 같은 곳을 고치는 변경이 서로 겹칩니다. 변경을 나눠야 합니다. | Some changes overlap at the same place. Split the changes. |
| `engine_timeout` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `engine_unavailable` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `engine_protocol` | 작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다. | There is a problem with the workspace connection. See details for the cause. |
| `internal` | 작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not complete the task. See details for the cause. |
| `cell_not_fill_target` | 이 칸은 입력용 빈칸이 아닙니다. | This cell is not a fillable blank. |
| `cell_address_unknown` | 양식에서 해당 칸을 찾을 수 없습니다. | Could not find this cell in the form. |
| `fill_charpr_color_anomaly` | 빈칸의 기본 글자색이 본문과 다릅니다. 확인이 필요합니다. | The blank’s default text colour differs from the body text. Check the colour. |
| `color_anomaly` | 빈칸의 기본 글자색이 본문과 다릅니다. 확인이 필요합니다. | The blank’s default text colour differs from the body text. Check the colour. |
| `fill_charpr_script_anomaly` | 위첨자나 아래첨자 서식이 있는 칸입니다. 글자 크기 확인이 필요합니다. | This blank uses superscript or subscript formatting. Check the text size. |
| `script_anomaly_target` | 위첨자나 아래첨자 서식이 있는 칸입니다. 글자 크기 확인이 필요합니다. | This blank uses superscript or subscript formatting. Check the text size. |
| `run_color_anomaly` | 바꾸려는 문구에 강조색이 있습니다. | The text to replace contains an emphasis colour. |
| `at_cell_expect_mismatch` | 처음 읽은 뒤 칸의 문구가 바뀌었습니다. | The cell text has changed since it was read. |
| `replace_key_ambiguous` | 같은 칸에 같은 문구가 여러 번 있어 바꿀 위치를 찾을 수 없습니다. | The same text appears more than once in this cell. Could not identify which occurrence to change. |
| `at_cell_run_ambiguous` | 같은 칸에 같은 문구가 여러 번 있어 바꿀 위치를 찾을 수 없습니다. | The same text appears more than once in this cell. Could not identify which occurrence to change. |
| `run_inventory_unavailable` | 이 문구의 위치나 서식 정보를 확인할 수 없어 직접 고칠 수 없습니다. | Could not find the text or its formatting information. Inline editing is unavailable. |
| `run_address_unknown` | 이 문구의 위치나 서식 정보를 확인할 수 없어 직접 고칠 수 없습니다. | Could not find the text or its formatting information. Inline editing is unavailable. |
| `op_field_invalid` | 입력한 변경 내용을 확인해야 합니다. | Check the change details. |
| `xml_wellformedness` | 문서 파일 구조에 문제가 있습니다. | There is a problem with the document’s file structure. |
| `artifact_malformed` | 문서 파일 구조에 문제가 있습니다. | There is a problem with the document’s file structure. |
| `form_residue` | 작성 안내문이 남아 있습니다. | Form instructions remain in the document. |
| `pinned_target_missing` | 필수 문구가 문서에서 빠졌습니다. | Required text is missing from the document. |
| `expected_text_missing` | 필수 문구가 문서에서 빠졌습니다. | Required text is missing from the document. |
| `source_not_found` | 문서 파일을 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the document file. Reopen the document. |
| `candidate_not_found` | 문서 파일을 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the document file. Reopen the document. |
| `recovery_receipt_mismatch` | 저장된 수정본이나 검증 기록이 일치하지 않습니다. | The saved revision or verification record does not match. |
| `export_hash_mismatch` | 파일을 내보내지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not export the file. See details for the cause. |
| `export_download_failed` | 파일을 내보내지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not export the file. See details for the cause. |
| `not_invertible` | 이 변경을 자동으로 되돌리는 제안을 만들 수 없습니다. | Could not propose an automatic undo for this change. |
| `previous_value_unreadable` | 이 변경을 자동으로 되돌리는 제안을 만들 수 없습니다. | Could not propose an automatic undo for this change. |
| `cross_run` | 선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다. | This selection cannot be edited at once. Edit smaller sections. |
| `multi_run` | 선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다. | This selection cannot be edited at once. Edit smaller sections. |
| `utf16_split` | 선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다. | This selection cannot be edited at once. Edit smaller sections. |
| `no_host` | 에이전트 연결 설정이 필요합니다. 명령창에서 설정할 수 있습니다. | Set up the agent connection in the command palette. |
| `no_credential` | 에이전트 연결 설정이 필요합니다. 명령창에서 설정할 수 있습니다. | Set up the agent connection in the command palette. |
| `no_credential_name` | 에이전트 연결 설정이 필요합니다. 명령창에서 설정할 수 있습니다. | Set up the agent connection in the command palette. |
| `no_base_url` | 에이전트 연결 설정이 필요합니다. 명령창에서 설정할 수 있습니다. | Set up the agent connection in the command palette. |
| `guard_unavailable` | 지금은 사실 변경 여부를 점검할 수 없습니다. | Cannot check for changes to facts right now. |
| `session_not_found` | 열려 있던 문서를 찾을 수 없습니다. 문서를 다시 열어야 합니다. | Could not find the open document. Reopen it. |
| `plan_not_found` | 변경 제안이나 승인 요청을 찾을 수 없습니다. | Could not find the proposed changes or approval request. |
| `draft_superseded` | 새 변경 제안으로 이전 초안을 바꿨습니다. | New proposed changes replaced the previous draft. |
| `agent_output_unreadable` | 에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다. | Could not display the agent’s proposal. Request it again. |
| `agent_plan_before_unreadable` | 에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다. | Could not display the agent’s proposal. Request it again. |
| `agent_plan_projection_unsupported` | 에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다. | Could not display the agent’s proposal. Request it again. |
| `file_too_large` | 파일 크기가 너무 커서 열 수 없습니다. | The file is too large to open. |
| `plan_behind_head` | 이 변경 제안은 최신 수정본 이전 문서를 기준으로 만들어졌습니다. 그대로 적용하면 최신 수정본의 변경이 빠집니다. | This proposal was made against a document older than the latest revision. Applying it would drop the latest revision's changes. |
| `agent_not_connected` | 에이전트가 아직 연결되지 않았습니다. 명령창의 에이전트 연결에서 설정하면 요청을 보낼 수 있습니다. | No agent is connected yet. Set one up under Agent connection in the command palette to send requests. |
| `superseded_by_newer_candidate` | 더 새 수정본이 생겨 이 변경 제안을 돌려보냈습니다. | Returned because a newer revision exists. |
| `foreign_session_ops` | 다른 문서에서 만든 변경이 섞여 있어 이 문서에 다시 제안할 수 없습니다. | Changes made for another document are mixed in, so they cannot be proposed for this document. |
| `undo_unfixable` | 되돌리기 제안을 만들지 않았습니다. 그대로 만들면 승인할 수 없는 항목이 생깁니다. | No undo proposal was created. It would contain items that cannot be approved. |
| `confirmation_changed` | 승인을 누른 뒤 변경 제안이 바뀌어 적용하지 않았습니다. 바뀐 내용을 보고 다시 승인해야 합니다. | The proposal changed after you approved it, so nothing was applied. Review the new proposal and approve again. |
| `confirmation_required` | 승인 화면에서 확인한 승인만 기록합니다. 승인 화면을 다시 열어 승인해야 합니다. | Only an approval confirmed on the approval sheet is recorded. Open the sheet and approve again. |
| `confirmation_invalid` | 이미 쓴 승인 확인이라 기록하지 않았습니다. 다시 승인해야 합니다. | That approval confirmation was already used, so nothing was recorded. Approve again. |
| `confirmation_expired` | 승인 확인 시간이 지나 기록하지 않았습니다. 다시 승인해야 합니다. | The approval confirmation expired, so nothing was recorded. Approve again. |
| `confirmation_binding_mismatch` | 다른 제안의 승인 확인이라 기록하지 않았습니다. 다시 승인해야 합니다. | The approval confirmation belongs to another proposal, so nothing was recorded. Approve again. |
| `invalid_queue_ops` | 형식이 맞지 않는 변경이 섞여 있어 제안하지 않았습니다. | Some changes are malformed, so nothing was proposed. |
| `undo_conflict` | 되돌리기 제안을 만들지 않았습니다. 이후 수정본에서 같은 자리를 다시 고쳐서, 되돌리면 그 변경이 지워집니다. | No undo proposal was created. A later revision changed the same place, and undoing would erase that change. |

## 5. 화면 일반 문구 (`VOCABULARY`)

탐색 막대, 열기·검토 화면, 명령창, 승인·돌려보내기 대화상자, 오류 경계 및 도움말에서 사용하는 문구입니다.

| Key | Korean | English |
| :--- | :--- | :--- |
| `nav_open` | 열기 | Open |
| `nav_review` | 검토 | Review |
| `nav_fill` | 채우기 | Fill |
| `nav_history` | 기록 | History |
| `nav_settings` | 설정 | Settings |
| `doc_none_open` | 열린 문서 없음 | No document open |
| `action_command_palette` | 명령창 | Command palette |
| `action_export` | 파일 내보내기 | Export file |
| `action_open_doc` | 문서 열기 | Open document |
| `lang_ko` | 한국어 | Korean |
| `lang_en` | 영어 | English |
| `action_switch_lang` | 언어 바꾸기 | Switch language |
| `lang_switched_toast` | 화면 언어를 한국어로 바꿨습니다. | Switched display language to English. |
| `theme_light` | 밝게 | Light |
| `theme_dark` | 어둡게 | Dark |
| `theme_system` | 시스템 설정 | System |
| `action_switch_theme` | 화면 테마 바꾸기 | Change theme |
| `guard_pill_kept` | 점검한 사실 유지 | Checked facts unchanged |
| `guard_pill_changed` | 바뀐 사실 | Changed facts |
| `guard_list_header` | 수정한 문단의 숫자·날짜·인용문·부정 표현·증감 및 방향 표현만 점검하며, 내용이 맞는지는 판단하지 않습니다. | The check looks only at numbers, dates, quotations, negation, and increase, decrease, or direction words in the edited paragraph; it does not judge whether the content is correct. |
| `guard_added_numbers` | 추가된 숫자: | Added numbers: |
| `guard_not_run_invalid` | 점검하지 않았습니다 | Not checked |
| `approve_dialog_effect` | 승인하면 이 컴퓨터에서 변경 {0}건을 적용한 새 수정본을 만들며, 파일 내보내기는 별도 단계이고 어디에도 전송하지 않습니다. | Approval creates a new revision on this machine with {0} changes applied; exporting the file is a separate step, and nothing is sent anywhere. |
| `approve_dialog_guard_skipped` | 점검을 실행할 수 없어 사실 변경 여부를 점검하지 않았습니다. | Changes to facts were not checked because the check could not run. |
| `page_label_review` | 제안을 적용한 모습 · 미리보기 · 실제 인쇄 결과와 다를 수 있습니다. | Preview with proposed changes · May differ from printed output. |
| `page_label_fill` | 미리보기 · 실제 인쇄 결과와 다를 수 있습니다. | Preview · May differ from printed output. |
| `page_omitted_object` | 표시하지 않은 개체 | Object not shown |
| `fill_long_value` | 긴 내용은 인쇄할 때 줄바꿈이 달라질 수 있습니다. | Long entries may wrap differently when printed. |
| `fill_counter` | 입력할 빈칸 {1}개 중 {0}개 입력 | {0} of {1} blanks filled |
| `open_pending_badge` | 검토 대기 {0}건 | {0} pending changes |
| `open_sample_form_label` | 예시 양식 | Example forms |
| `history_title_note` | 변경을 적용한 수정본만 표시하며, 검토를 기다리는 변경 제안은 검토 화면에서 확인할 수 있습니다. | Only revisions with applied changes are listed here; pending proposed changes are available in review. |
| `history_pending_link` | 대기 중인 변경 제안 보기 | View pending proposed changes |
| `history_undo_scope` | 현재 수정본에서 선택한 수정본의 변경을 되돌리는 제안을 만들며, 그 이후의 변경은 유지합니다. | Creates a proposal to reverse the selected revision’s changes in the current revision while keeping later changes. |
| `history_approval_method_direct` | 승인 방식: 직접 승인 | Approval method: Manual approval |
| `settings_folder_locked` | 아직 확정하지 않은 초안이나 검토 중 또는 적용 중인 변경 제안이 있어 작업 폴더를 바꿀 수 없습니다. | The workspace folder cannot be changed while any document has an uncommitted draft or proposed changes under review or being applied. |
| `settings_language_note` | 화면 언어를 바꿔도 문서 내용은 바뀌지 않습니다. | Changing the display language does not change the document text. |
| `settings_theme_note` | 화면 테마를 바꿔도 인쇄할 파일은 바뀌지 않습니다. | Changing the theme does not change the file you print. |
| `settings_folder_note` | 작업 폴더는 이 프로그램이 실행되는 컴퓨터에 작업 사본과 수정 기록을 보관하는 곳이며, 파일 내보내기 위치와는 별개입니다. | The workspace folder stores working copies and revision history on the machine running this application; it is separate from the export destination. |
| `print_view_grade_hancom` | 한글 인쇄 화면 | Hancom print view |
| `print_view_grade_pdf` | 인쇄 화면 | Print view |
| `print_view_grade_own` | 자체 미리보기 · 인쇄 결과와 대조하지 않았습니다. | Rigorloom preview · Not checked against printed output. |
| `open_title` | 문서 열기 | Open document |
| `open_subtitle` | 원본은 그대로 두고 작업 사본을 엽니다. | Opens a working copy while keeping the original file unchanged. |
| `open_drop_prompt` | 한글 문서를 여기에 놓으면 열립니다. | Drop a Hangul document here to open. |
| `open_drop_sub` | 파일이나 예시 양식을 선택할 수 있습니다. | Or choose a file from your computer or an example form. |
| `open_choose_file` | 파일 선택 | Choose file |
| `open_builtin_forms` | 예시 양식 열기 | Open example form |
| `open_recent_title` | 최근 연 문서 | Recent documents |
| `open_recent_hint` | 문서를 선택하면 이어서 작업할 수 있습니다. | Select a document to continue working. |
| `open_empty_recent` | 아직 연 문서가 없습니다. | No documents opened yet. |
| `open_no_changes` | 변경이 없습니다 | No changes |
| `open_pending_review` | 변경 {0}건이 검토를 기다리고 있습니다 | {0} changes awaiting review |
| `open_hwp_help_title` | 한글 파일 열기 안내 | Opening legacy Hangul files |
| `open_hwp_help_body` | 이 파일은 한글에서 다시 저장한 뒤 열어야 합니다. | This file must be saved again in Hancom Office before opening. |
| `open_hwp_help_steps` | 한글에서 파일을 연 뒤 지원하는 한글 문서 형식으로 다시 저장하면 열 수 있습니다. | Open the file in Hancom Office and save it in .hwpx format to open it here. |
| `open_drop_unsupported` | 지원하지 않거나 변환할 수 없는 파일입니다. 지원하는 형식의 문서를 선택해야 합니다. | This file is unsupported or cannot be converted. Choose a supported document. |
| `review_mode_document` | 문서 보기 | Show document |
| `review_mode_print` | 인쇄 화면 보기 | Show print view |
| `review_changes_header` | 변경 {0}건 | {0} changes |
| `review_changed_facts_header` | 바뀐 사실 {0}건 | {0} changed facts |
| `review_before_label` | 변경 전: {0} | Before: {0} |
| `review_after_label` | 변경 후: {0} | After: {0} |
| `review_agent_suggestion` | 에이전트 제안 | Agent suggestion |
| `review_direct_edit` | 직접 고치기 | Edit inline |
| `review_remove_item` | 이 항목 빼기 | Remove |
| `review_collapse` | 접기 | Collapse |
| `review_return` | 돌려보내기 | Return |
| `review_approve` | 승인 | Approve |
| `review_cancel` | 취소 | Cancel |
| `review_return_reason_placeholder` | 돌려보내는 이유 (선택) | Reason for returning (optional) |
| `review_return_to_fill` | 채우기로 돌아가기 | Return to fill |
| `review_confirm_changed_fact` | 바뀐 사실을 확인했습니다 | I have reviewed the changed facts |
| `review_prompt_placeholder` | 추가 요청 입력 | Add another instruction |
| `review_prompt_submit` | 요청 보내기 | Send request |
| `review_prev` | 이전 | Previous |
| `review_next` | 다음 | Next |
| `review_zoom_fit` | 폭 맞춤 | Fit width |
| `review_zoom_label` | 배율 {0}% | Zoom {0}% |
| `review_page_counter` | {0} / {1}쪽 | Page {0} of {1} |
| `review_empty_changes` | 검토할 변경 제안이 없습니다. | No proposed changes to review. |
| `review_approve_dialog_title` | 변경 {0}건을 적용할까요? | Apply {0} changes? |
| `review_plan_hash_label` | 변경 제안 검증값 | Plan verification value |
| `review_doc_hash_label` | 문서 검증값 | Document verification value |
| `review_date_change_preview` | {0}번 항목의 날짜가 {1}에서 {2}로 바뀝니다. | Item {0} date changes from {1} to {2}. |
| `review_mobile_sheet_tab` | 문서 | Document |
| `review_mobile_list_tab` | 변경 {0}건 | {0} changes |
| `review_applied_ok` | 변경 내용을 적용했습니다. | Changes applied. |
| `review_placeholder_ready` | 문서 검토 화면을 준비했습니다. 문서를 선택하면 변경 제안을 볼 수 있습니다. | Review view is ready. Select a document to inspect proposed changes. |
| `field_blank_fallback` | 빈칸 {0} | Blank {0} |
| `palette_placeholder` | 명령 입력... | Type a command... |
| `palette_empty` | 일치하는 명령이 없습니다. | No matching commands. |
| `cmd_approve` | 변경 승인 | Approve changes |
| `cmd_return` | 변경 돌려보내기 | Return changes |
| `cmd_export` | 파일 내보내기 | Export file |
| `cmd_open_doc` | 문서 열기 | Open document |
| `cmd_open_builtin` | 예시 양식 열기 | Open example form |
| `cmd_go_review` | 검토로 이동 | Go to review |
| `cmd_go_fill` | 채우기로 이동 | Go to fill |
| `cmd_go_history` | 기록으로 이동 | Go to history |
| `cmd_jump_changed_fact` | 다음 바뀐 사실로 이동 | Jump to next changed fact |
| `cmd_jump_empty_blank` | 첫 빈칸으로 이동 | Go to first empty blank |
| `cmd_propose_delete_guides` | 안내문 삭제 제안 | Propose removing form instructions |
| `cmd_toggle_print_view` | 인쇄 화면 보기 | Show print view |
| `cmd_propose_undo_latest` | 최신 수정본 되돌리기 제안 | Propose undo of latest revision |
| `cmd_switch_language` | 언어 바꾸기 | Switch language |
| `cmd_change_theme` | 화면 테마 바꾸기 | Change theme |
| `cmd_open_settings` | 설정 열기 | Open settings |
| `cmd_open_by_path_details` | 경로로 문서 열기 (자세히) | Open document by path (details) |
| `cmd_operator_agent_details` | 에이전트 연결 및 작업 기록 (자세히) | Agent connection and activity log (details) |
| `splash_loading` | 작업 공간을 준비하고 있습니다. | Preparing workspace. |
| `splash_connecting` | 문서 도구를 불러오고 있습니다. | Loading document tools. |
| `fatal_title` | 작업 공간을 열 수 없습니다 | Could not open workspace |
| `error_boundary_title` | 화면을 표시할 수 없습니다 | Could not display view |
| `error_boundary_body` | 예기치 않은 오류가 발생했습니다. 다시 시도하거나 자세히에서 원인을 확인할 수 있습니다. | An unexpected error occurred. Try reloading or open Details for the cause. |
| `error_boundary_retry` | 다시 불러오기 | Reload |
| `browser_open_title` | 경로로 문서 열기 | Open document by path |
| `browser_open_path_label` | 파일 경로 | File path |
| `browser_open_path_placeholder` | 열 문서 파일의 전체 경로 입력 | Enter the full path to a document |
| `browser_open_submit` | 열기 | Open |
| `browser_open_loading` | 불러오는 중입니다... | Loading... |
| `browser_open_empty_corpus` | 열 수 있는 예시 양식이 없습니다. | No example forms available. |
| `operator_modal_title` | 에이전트 연결 및 작업 기록 | Agent connection and activity log |
| `operator_tab_agent` | 에이전트 연결 | Agent connection |
| `operator_tab_events` | 작업 기록 | Activity log |
| `operator_close` | 닫기 | Close |
| `operator_no_session` | 작업 기록을 보려면 먼저 문서를 열어야 합니다. | Open a document first to view its activity log. |
| `detail_label` | 자세히 | Details |
| `detail_internal_state` | 내부 상태 | Internal state |
| `detail_internal_code` | 오류 코드 | Error code |
| `detail_pid_process` | 실행 프로세스 번호 · 하위 프로세스 종료 상태 | Runtime process ID · child process status |
| `detail_receipt_verify` | 검증 기록 확인 | Verification record check |
| `detail_file_hash` | 파일 검증값 | File verification value |
| `detail_raw_log` | 원본 기록 보기 | View raw log |
| `time_just_now` | 방금 전 | Just now |
| `time_today` | 오늘 {0} | Today {0} |
| `time_yesterday` | 어제 {0} | Yesterday {0} |
| `copy_done` | 복사했습니다. | Copied. |
| `close` | 닫기 | Close |
| `fallback_unknown_action` | 편집 작업 | Edit action |
| `fallback_unknown_error` | 작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다. | Could not complete the task. See details for the cause. |
| `open_samples_show` | 목록 펼치기 | Show forms |
| `open_samples_hide` | 목록 접기 | Hide forms |
| `open_path_disclosure_hint` | 직접 파일 경로를 입력해 문서를 열어야 할 때 사용합니다. | Use this if you need to open a document directly by file path. |
| `review_suggest_body_style` | 권장 본문 서식 적용 | Use suggested body style |
| `review_save_edit` | 적용 | Save |
| `review_repropose` | 다시 제안하기 | Re-propose |
| `review_check_status` | 적용 여부 확인 | Check revision status |
| `review_applying` | 적용 중... | Applying... |
| `review_guard_checking` | 사실 변경 여부를 점검하고 있습니다. | Checking protected facts... |
| `pipeline_checking_gates` | 조회 중... | Checking... |
| `pipeline_load_gates` | 게이트 조회 | Load gates |
| `review_zoom_out` | 축소 | Zoom out |
| `review_zoom_in` | 확대 | Zoom in |
| `delete_guides_noninvertible` | 안내문을 지울 때 사라진 문단 서식을 되살릴 수 없어 자동으로 되돌릴 수 없습니다. | Removing form instructions cannot be undone automatically because removed paragraph formatting cannot be restored. |
| `op_clear_symbol` | 기호 지움 | Remove symbol |
| `guard_added_numbers_more` | 외 {0}개 | and {0} more |
| `topbar_more_menu` | 메뉴 | Menu |
| `export_no_revision_toast` | 아직 내보낼 수정본이 없습니다. 변경 제안을 승인해 적용한 뒤 내보낼 수 있습니다. | No revision to export yet. Approve and apply changes first. |
| `field_body_fallback` | 본문 | Body |
| `fill_title` | 양식 채우기 | Fill form |
| `fill_empty_fields` | 입력할 빈칸이 없습니다. | No blank fields found in this document. |
| `fill_select_prompt` | 왼쪽 문서에서 빈칸을 클릭하거나 아래에서 항목을 고르면 바로 입력할 수 있습니다. | Click any dashed blank on the page or pick a field below to fill it in. |
| `fill_field_placeholder` | 내용 입력 | Enter text |
| `fill_multiline_enable` | 여러 줄 입력 | Multi-line input |
| `fill_multiline_disable` | 한 줄 입력 | Single-line input |
| `fill_multiline_hint` | 여러 줄로 입력할 수 있습니다. 입력을 마치면 ‘입력 저장’을 선택합니다. | You can enter several lines. Select Save entry or press Ctrl/Cmd+Enter when finished. |
| `fill_singleline_hint` | 엔터 키를 누르거나 ‘입력 저장’을 선택하면 저장합니다. 여러 줄로 입력하려면 ‘여러 줄 입력’을 선택합니다. | Press Enter or select Save entry to save. Select Multi-line input to enter several lines. |
| `fill_escape_hint` | 문서 안 빈칸에서 취소 키를 누르면 빈칸 선택을 마칩니다. | In the document, press Esc to leave blank selection. |
| `fill_static_notice` | 이 칸은 입력용 빈칸이 아닙니다. | This cell is not a fillable blank. |
| `fill_static_replace` | 기존 문구 바꾸기 | Replace existing text |
| `fill_static_current_label` | 현재 들어 있는 문구 | Current text in cell |
| `fill_filled_list_header` | 변경 제안 | Proposed changes |
| `fill_filled_list_empty` | 아직 추가한 변경 제안이 없습니다 | No proposed changes yet. |
| `fill_previous_form_text` | 기존 양식 문구: {0} | Previous form text: {0} |
| `fill_previous_blank` | (비어 있음) | (empty) |
| `fill_to_review` | 검토로 이동 | Go to review |
| `fill_reproposing` | 검토 화면을 준비하고 있습니다 | Preparing review... |
| `fill_delete_guides_btn` | 안내문 삭제 제안 | Propose removing form instructions |
| `fill_delete_guides_done` | 안내문 지움 {0}건을 변경 제안에 추가했습니다 | Queued {0} guide deletions. |
| `fill_delete_guides_queued` | 안내문 지움 {0}건을 제안에 포함했습니다 | Guide deletion queued ({0}) |
| `fill_undo_removed` | ‘{0}’ 항목을 변경 제안에서 뺐습니다 | Removed entry for '{0}'. |
| `fill_undo_restore` | 방금 뺀 항목 되살리기 | Undo remove |
| `fill_undo_empty` | ‘{0}’ 입력을 지워 변경 제안에서 뺐습니다 | Removed the proposed entry for '{0}' after clearing its input. |
| `fill_ambiguous_warning` | 이름이 ‘{0}’인 빈칸이 {1}개 있습니다. 입력할 칸의 위치를 확인해야 합니다. | There are {1} blanks named '{0}'. Confirm the selected slot below. |
| `fill_ambiguous_slot_option` | {0}번째 빈칸 · {1} | Blank #{0} · {1} |
| `fill_clear_value` | 입력 지우기 | Clear entry |
| `fill_save_entry` | 입력 저장 | Save entry |
| `fill_edit_entry` | 고치기 | Edit |
| `fill_guide_caption` | 작성 안내문: {0} | Form instructions: {0} |
| `action_export_revision` | 수정본 {0} 내보내기 | Export revision {0} |
| `export_done_toast` | 수정본 파일을 저장했습니다 | Exported revision file. |
| `apply_done_toast` | 수정본 {0}을 만들었습니다 | Created revision {0}. |
| `detail_cell_address` | 표 칸 위치 | Cell location |
| `detail_cell_class` | 표 칸 분류 | Cell classification |
| `detail_suggested_char_style` | 권장 글자 서식 | Suggested character style |
| `fill_row_label` | {0}행 | Row {0} |
| `detail_run_id` | 실행 식별자 | Run ID |
| `detail_plan_id` | 변경 제안 식별자 | Change proposal ID |
| `detail_approver_record` | 승인 주체 기록 | Recorded approval actor |
| `detail_base_run_id` | 기준 수정본 실행 식별자 | Base revision run ID |
| `detail_reversed_run_id` | 되돌리기 대상 실행 식별자 | Run ID being reversed |
| `detail_regions_equal` | 영역 일치 여부 | Regions match |
| `detail_regions_compared` | 비교한 영역 수 | Regions compared |
| `detail_normalizer` | 비교 전 정리 방식 | Comparison normalization method |
| `history_title` | 수정 기록 | Revision history |
| `history_empty` | 아직 만든 수정본이 없습니다 | No revisions created yet. |
| `history_revision_label` | 수정본 {0} | Revision {0} |
| `history_revision_current` | 현재 수정본 | Current |
| `history_changes_count` | 변경 {0}건 | {0} changes |
| `history_approved_at_label` | 승인 시각 | Approved at |
| `history_applied_at_label` | 적용 시각 | Applied at |
| `history_unknown_time` | 기록 없음 | Not recorded |
| `history_propose_undo` | 되돌리기 제안 | Propose undo |
| `history_proposing_undo` | 되돌리기 제안을 만들고 있습니다 | Preparing undo proposal... |
| `history_undo_noninvertible` | 안내문 지움 {0}건이 포함되어 있어 자동으로 되돌리는 제안을 만들 수 없습니다. | Includes {0} form instruction removals; an automatic undo proposal cannot be created. |
| `history_export_prev_revision` | 이전 수정본 {0} 내보내기 | Export previous revision {0} |
| `history_export_original` | 원본 문서 내보내기 | Export original document |
| `history_compare_title` | 문서 비교 | Compare documents |
| `history_compare_base` | 비교 기준 | Comparison base |
| `history_compare_target` | 비교 대상 | Comparison target |
| `history_compare_original` | 원본 문서 | Original document |
| `history_compare_changed_count` | 바뀐 문단 {0}개 | {0} paragraphs changed |
| `history_compare_same` | 비교한 문서의 내용이 같습니다 | The compared documents have the same content. |
| `history_compare_loading` | 선택한 문서를 비교하고 있습니다 | Comparing selected documents... |
| `history_compare_need_two` | 비교 기준과 비교 대상을 선택해야 합니다. | Select a comparison base and target. |
| `history_approval_method_auto` | 승인 방식: 자동 승인 규칙 | Approval method: Automatic approval rule |
| `history_receipt_unavailable` | 승인 기록을 아직 불러오지 못했습니다. | Approval record is not available yet. |
| `history_snapshot_diff_note` | 비교 기준과 비교 대상의 문단 내용을 비교한 결과입니다. | Results of comparing paragraph text between the comparison base and target. |
| `settings_title` | 설정 | Settings |
| `settings_section_language` | 언어 | Language |
| `settings_section_theme` | 화면 테마 | Appearance |
| `settings_section_folder` | 작업 폴더 | Workspace folder |
| `settings_folder_change` | 폴더 바꾸기 | Change folder |
| `settings_folder_changing` | 작업 폴더를 바꾸고 있습니다 | Switching workspace folder... |
| `settings_folder_changed` | 작업 폴더를 바꿨습니다 | Workspace folder updated. |
| `settings_folder_prompt` | 새 작업 폴더 경로 입력 | Enter new workspace folder path |
| `settings_folder_apply` | 폴더 바꾸기 | Change folder |
| `settings_folder_reset_default` | 기본 폴더 사용 | Use default folder |
| `settings_folder_current_label` | 현재 작업 폴더 | Current folder |
| `operator_tab_credentials` | 에이전트 인증 및 서비스 제공자 | Credentials & provider |
| `cmd_export_revision` | 현재 수정본 내보내기 | Export current revision |
| `cmd_open_workspace_settings` | 언어·화면 테마·작업 폴더 설정 | Language, theme & workspace settings |
| `err_invalid_json` | 서버 응답 형식이 올바르지 않습니다. | Server response is not valid JSON. |
| `err_rpc_failed` | 요청을 처리하지 못했습니다. | Could not process the request. |
| `seat_editor_aria_label` | 이 자리에 넣을 값 | Value for this blank |
| `approval_kind_count` | {0}건 | {0} |
| `cmd_kw_open_doc` | 열기 파일 선택 | open file |
| `cmd_kw_open_builtin` | 예시 양식 열기 기본 | open form example |
| `cmd_kw_go_review` | 검토 화면 이동 | review |
| `cmd_kw_go_fill` | 채우기 빈칸 양식 입력 | fill |
| `cmd_kw_go_history` | 기록 수정본 이력 비교 | history revisions |
| `cmd_kw_toggle_print_view` | 인쇄 화면 문서 보기 | print view |
| `cmd_kw_approve` | 승인 적용 | approve |
| `cmd_kw_return` | 돌려보내기 | return |
| `cmd_kw_export` | 내보내기 저장 수정본 | export revision |
| `cmd_kw_switch_language` | 언어 한국어 영어 | language |
| `cmd_kw_change_theme` | 화면 테마 밝게 어둡게 | theme |
| `cmd_kw_open_settings` | 설정 언어 화면 테마 작업 폴더 | settings language theme workspace folder |
| `cmd_kw_open_by_path` | 경로 자세히 열기 | path details |
| `cmd_kw_operator_agent` | 에이전트 연결 작업 기록 인증 공급자 자세히 | agent log credentials provider details |
| `corpus_title_gianmun_1` | 기안문 (별지 제1호서식) | Drafting Form (Annex 1) |
| `corpus_title_gianmun_2` | 기안문 (별지 제2호서식) | Drafting Form (Annex 2) |
| `corpus_title_jumin` | 주민등록표 등·초본 교부 신청서 | Resident Registration Copy Request |
| `corpus_title_jeongbo_gonggae` | 정보공개 청구서 | Information Disclosure Request |
| `corpus_title_saeopja` | 사업자등록 신청서 (개인사업자용) | Business Registration Application |
| `corpus_title_gajokdolbom` | 가족돌봄 휴직·휴가 신청서 | Family Care Leave Request |
| `corpus_title_moel_2025` | 표준근로계약서 (2025) | Standard Employment Contract (2025) |
| `corpus_title_moel_2013` | 표준근로계약서 (2013) | Standard Employment Contract (2013) |
| `corpus_title_nrf_report` | 연구결과보고서 양식 | Research Result Report Form |
| `corpus_title_kstartup` | 예비창업가 지원 신청서 및 사업계획서 | Startup Support Application & Plan |
| `corpus_title_pps_collab` | 협업 승인 신청서 | Collaboration Approval Request |
| `corpus_title_pps_consent` | 정보공개 동의서 (개인정보 수집·이용) | Information Disclosure Consent Form |
| `corpus_title_render_check` | 문서 배치 확인용 예시 | Layout Check Sample |
| `corpus_title_table_break` | 표 페이지 나눔 확인용 예시 | Table Break Check Sample |
| `corpus_source_mois` | 행정안전부 예시 | MOIS example |
| `corpus_source_nts` | 국세청 예시 | NTS example |
| `corpus_source_nsm` | 국립중앙과학관 예시 | NSM example |
| `corpus_source_moel` | 고용노동부 예시 | MOEL example |
| `corpus_source_nrf` | 한국연구재단 예시 | NRF example |
| `corpus_source_kised` | 창업진흥원 예시 | KISED example |
| `corpus_source_pps` | 조달청 예시 | PPS example |
| `corpus_source_internal` | 내부 점검 예시 | Internal check sample |
| `proj_unimpl_normalize_clones` | 중복 글자 서식 정리는 문서의 서식 정보를 다시 쓰는 작업이어서 검토 대기열에 정확히 표시할 수 없습니다. | Style clone normalization rewrites headers and cannot be accurately shown in the review queue. |
| `proj_unimpl_goto_text` | 위치 이동은 검토 대기열에서 지원하지 않는 작업입니다. | Jumping to text is not supported in the review queue. |
| `proj_refuse_op_unrepresentable` | 변경 작업을 검토 대기열에 정확히 표시할 수 없습니다. | This change operation cannot be accurately shown in the review queue. |
| `proj_refuse_partial_unrepresentable` | 일부 작업의 내용을 검토 대기열에 정확히 표시할 수 없습니다. | Some operations cannot be accurately represented in the review queue. |
| `proj_refuse_kind_unsupported` | 이 변경 작업은 검토 대기열에서 지원하지 않습니다. | This change operation is not supported in the review queue. |
| `proj_refuse_invalid_params` | 입력한 변경 내용을 확인해야 합니다. | Check the change details. |
| `proj_refuse_invalid_fields` | 입력한 변경 내용을 검토 대기열에 표시할 수 없습니다. | The change details cannot be shown in the review queue. |
| `proj_guide_color_prefix` | 색상 {0} | color {0} |
| `proj_guide_charpr_prefix` | 서식 번호 {0} | charPr {0} |
| `proj_guide_target_with_parts` | 안내문 ({0}) | Guides ({0}) |
| `proj_guide_target_default` | 대상 안내문 | Target guide text |
| `proj_guides_deleted` | (안내문 삭제됨) | (Guide text removed) |
| `proj_addr_table_cell` | 표 {0} {1}행 {2}열 | Table {0} R{1}C{2} |
| `proj_addr_run_suffix` | · 글자 구간 {0} | · Run {0} |
| `proj_addr_para_run` | 문단 {0} · 글자 구간 {1} | Paragraph {0} · Run {1} |
| `proj_addr_delete_guides` | 안내문 삭제 | Delete guides |
| `proj_inverse_delete_guides` | 안내문 지움은 지운 안내 문단과 서식을 되살릴 수 없어 되돌릴 수 없습니다. | Guide text removal cannot be undone because deleted guide paragraphs and formatting cannot be restored. |
| `proj_inverse_unsupported_kind` | 이 변경 작업은 되돌릴 수 없습니다. | This change operation cannot be undone. |
| `action_open_hwpx_title` | 한글 문서 열기 | Open Hangul document |
| `action_open_hwpx_filter` | 한글 문서 | Hangul documents |
| `toast_hwpx_only` | 지원하지 않는 파일 형식입니다. 한글 문서만 열 수 있습니다. | Only Hangul documents (.hwpx, .hwp) can be opened. |
| `toast_opened_first_of_many` | {0}개 중 첫 문서만 열었습니다 | Opened only the first of {0} documents. |
| `toast_not_editable_cell` | 이 칸은 입력용 빈칸이 아닙니다. | This cell is not a fillable blank. |
| `overlay_not_editable_cell` | {0} — 이 칸은 입력용 빈칸이 아닙니다. | {0} — Not a fillable blank |
| `caret_refusal_no_address` | 이 줄의 문단 위치를 확인할 수 없습니다. | This line has no paragraph address. |
| `caret_refusal_multi_run` | 선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다. | This selection cannot be edited at once. Edit smaller sections. |
| `caret_refusal_run_text_differs` | 이 줄에서 수정할 글자 위치를 정확히 찾을 수 없습니다. | Cannot resolve a single cursor offset within this text segment. |
| `caret_refusal_no_inventory` | 이 문단의 글자 구간 정보를 확인할 수 없습니다. | The runtime did not return text segments for this paragraph. |
| `caret_refusal_revision_mismatch` | 표시 중인 문서와 읽은 문서가 다릅니다. 이 줄에는 커서를 놓을 수 없습니다. | Displayed document differs from the loaded document; cannot place cursor. |
| `caret_refusal_cross_run` | 선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다. | This selection cannot be edited at once. Edit smaller sections. |
| `caret_refusal_utf16_split` | 선택한 위치가 한 글자의 중간이어서 수정할 수 없습니다. 글자 앞이나 뒤를 선택해야 합니다. | This position is inside a character and cannot be edited. Select a position before or after the character. |
| `overlay_caret_snapped` | 글자별 위치를 확인할 수 없어 줄 앞에 커서를 놓았습니다 | Snapped cursor to start of line |
| `overlay_caret_offset` | {0}번째 글자 앞 | Before character {0} |
| `toast_removed_from_queue` | 대기열에서 뺐습니다. 이 동작으로 문서 내용은 바뀌지 않습니다. | Removed from queue. This action does not change the document content. |
| `err_undo_not_invertible` | 이 수정본에는 되돌릴 수 없는 작업이 있습니다: {0}. 안내문 지움은 지운 안내문을 원래 서식과 위치로 되살릴 수 없으며, 빈칸 채움·칸 문구 바꿈·본문 문구 바꿈 작업만 되돌릴 수 있습니다. | This revision contains operations that cannot be undone: {0}. Removing guide text cannot be restored with original formatting and position; only blank fills, cell text replacements, and body text replacements can be undone. |
| `err_undo_no_addresses` | 이 변경 제안의 작업들이 주소를 갖고 있지 않아 이전 값을 읽을 수 없습니다. | Operations in this change proposal carry no addresses, so previous values cannot be read. |
| `err_undo_previous_unreadable` | 되돌릴 이전 값을 런타임이 돌려주지 못한 자리가 있습니다. 빈 값으로 짐작해서 덮어쓰지 않습니다. | The runtime did not return a previous value for some targets. Refusing to guess an empty value. |
| `toast_undo_proposed` | 되돌리기를 제안했습니다. 승인해야 수정본이 하나 더 생깁니다. | Proposed undo. Approving creates a new revision. |
| `toast_proposal_returned` | 변경 제안을 돌려보냈습니다. 문서는 그대로입니다. | Returned the change proposal. The document is unchanged. |
| `reapproval_prompt` | 문서 또는 수정본이 바뀌어 기존 승인이 무효화되었습니다. 변경 제안을 다시 확인하고 승인해야 합니다. | The document or revision changed and invalidated the previous approval. Review the updated change proposal and approve again. |
| `toast_apply_cancelling` | 적용을 멈추라고 알렸습니다. 진행 중인 한 단계는 끝납니다. | Requested cancellation. The current step will finish first. |
| `err_pipeline_workspace_missing` | 작업 폴더 경로를 입력해야 합니다. | Please enter a workspace path. |
| `gate_decision_approved` | 승인했습니다 | Approved |
| `gate_decision_rejected` | 돌려보냈습니다 | Returned |
| `toast_gate_resolved` | {1} | {1} |
| `err_recovery_receipt_mismatch` | 복구 대상 수정본의 검증 기록이 중단된 적용 요청과 일치하지 않습니다. | The recovery revision's verification record does not match the interrupted apply request. |
| `action_export_revision_dialog_title` | 수정본 내보내기 | Export revision |
| `err_export_file_mismatch` | 내보낸 파일이 수정본과 일치하지 않습니다. 이 파일을 제출하지 마십시오. | The exported file does not match the revision. Do not submit this file. |
| `err_export_download_failed` | 수정본 내려받기에 실패했습니다 (상태 {0}). | Failed to download revision (HTTP {0}). |
| `err_export_download_mismatch` | 내려받은 파일이 수정본과 일치하지 않습니다. 이 파일을 제출하지 마십시오. | The downloaded file does not match the revision. Do not submit this file. |
| `addr_table_cell` | 표 {0} {1}행 {2}열 | Table {0} R{1}C{2} |
| `addr_paragraph` | 문단 {0} | Paragraph {0} |
| `addr_anchor` | 위치 “{0}” | Anchor “{0}” |
| `addr_none` | 주소 없음 | No address |
| `deriv_cell_borders` | 칸 테두리를 기준으로 위치를 찾았습니다 | Matched by cell borders |
| `deriv_matched_text` | 칸의 문구를 기준으로 위치를 찾았습니다 | Matched by cell text |
| `deriv_interpolated` | 항목 이름을 기준으로 위치를 추정했습니다 | Inferred from label |
| `overlay_ambiguous_pick` | 후보 {0}개 — 직접 선택 | {0} matches — choose one |
| `overlay_unmapped_sidecar` | {0}번째 줄 — 양식에서 이 줄의 위치를 확인할 수 없습니다. 미리보기에 표시된 위치만으로는 수정할 위치를 정할 수 없습니다. | Line {0} — Could not verify this line’s position in the form. Its preview position alone cannot identify where to edit. |
| `overlay_unmapped_plain` | {0}번째 줄 — 양식에서 이 줄의 위치를 확인할 수 없습니다. | Line {0} — could not match this line to any position in the form. |
| `overlay_user_selected` | {0} — 사용자가 선택했습니다 | {0} — selected by user |
| `prepare_note_revision_ready` | 수정본 인쇄 화면을 준비했습니다 | Prepared revision print view |
| `prepare_note_original_ready` | 원본 인쇄 화면을 준비했습니다 | Prepared original print view |
| `prepare_note_already_ready` | 이미 준비되어 있습니다 | Already prepared |
| `err_agent_output_unreadable` | 에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다. | Could not display the agent’s proposal. Request it again. |
| `err_agent_draft_superseded` | 제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 이 제안을 대기열에 넣지 않았습니다. | The document or review queue changed while this proposal arrived, so it was not queued. |
| `finding_where_checker` | 점검 항목 | Check |
| `finding_reason_none` | 이유 없음 | no reason given |
| `finding_check_not_run` | 이 점검은 실행되지 않았습니다. 실행하지 않은 점검은 통과로 세지 않습니다. | This check did not run. Checks that did not run are not counted as passes. |
| `finding_where_cell` | 표 {0} {1}행 {2}열 | Table {0} R{1}C{2} |
| `finding_color_anomaly` | 글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다. | Text colour differs from body baseline; filling as-is leaves coloured text. |
| `finding_script_anomaly` | 글자 속성이 본문 기준과 다릅니다. 서식 번호 {0} 대신 {1} 사용을 권장합니다. | Character formatting differs from body baseline; charPr {0} -> {1} recommended. |
| `finding_where_cell_run` | 표 {0} {1}행 {2}열 · 글자 구간 {3} | Table {0} R{1}C{2} #{3} |
| `finding_where_para_run` | 문단 {0} · 글자 구간 {1} | Paragraph {0} #{1} |
| `finding_color_unknown` | 알 수 없음 | unknown |
| `finding_run_color_anomaly` | 본문 기준과 다른 글자색을 사용하는 문구가 있습니다. 문구: “{1}”. | Some text uses a different colour from the body text. Text: “{1}”. |
| `finding_script_anomaly_target` | 글자 서식이 본문 기준과 다릅니다. 서식 번호 {1} 대신 {2} 사용을 권장합니다. | Character formatting differs from the body text. Use format {2} instead of {1}. |
| `finding_where_document` | 문서 전체 | Whole document |
| `finding_clean_notice` | 현재 점검할 수 있는 범위에서는 문제가 발견되지 않았습니다. 인쇄 확인과 제출 전 점검은 아직 실행할 수 없습니다. | No issues found within what this build can inspect. Print verification and submission checks cannot run yet. |
| `toast_nothing_to_copy` | 복사할 글이 없습니다 | Nothing to copy |
| `toast_copied_label` | {0} 복사를 마쳤습니다 | Copied {0} |
| `boot_checking_capabilities` | 지원 기능을 확인하고 있습니다 | Checking capabilities... |
| `boot_finding_open_docs` | 열린 문서를 찾고 있습니다 | Finding open documents... |
| `boot_reloading_doc` | 문서를 다시 읽고 있습니다 | Reloading document... |
| `boot_restarting_runtime` | 작업 공간 연결을 다시 시작하고 있습니다 | Restarting runtime... |
| `err_credential_name_missing` | 먼저 자격 증명 이름을 정해야 합니다. | Set a credential key name first. |
| `toast_credential_stored` | 자격 증명을 이 기계의 저장소에 넣었습니다 | Stored credential in this machine's keyring. |
| `err_agent_host_exit` | 에이전트 호스트가 종료 코드 {0}로 끝났습니다. | Agent host exited with code {0}. |
| `err_agent_plan_before_unreadable` | 에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다. | Could not display the agent’s proposal. Request it again. |
| `agent_guide_summary_empty` | 문서에 있는 삭제 대상 안내문 | Guide text marked for removal |
| `agent_guide_summary_preview` | 안내문 {0}건 ({1}) | {0} guide entries ({1}) |
| `agent_guide_summary_count` | 안내문 {0}건 | {0} guide entries |
| `err_agent_cancelled` | 사람이 중간에 멈췄습니다. | Stopped by operator. |
| `toast_open_doc_before_check` | 점검하려면 먼저 문서를 열어야 합니다. | Open a document before running checks. |
| `err_invalid_root_path` | 작업 폴더 경로를 입력해야 합니다. | Enter a workspace folder path. |
| `err_workspace_start_failed` | 새 작업 폴더로 작업 공간을 시작하지 못했습니다. | Failed to start workspace with the new folder. |
| `operator_host_heading` | 에이전트 연결 | Agent connection |
| `operator_host_available` | 사용할 수 있습니다 | Available |
| `operator_host_unavailable` | 사용할 수 없습니다 | Unavailable |
| `operator_host_unknown_reason` | 확인하지 못했습니다. | Could not verify. |
| `operator_host_status_btn` | 상태 새로고침 | Refresh status |
| `operator_host_boundary_note` | 서비스 제공자와 통신하는 것은 이 별도 프로세스뿐이며, 문서 처리 쪽은 네트워크에 연결되지 않습니다. | Only this separate process talks to providers; document processing stays offline. |
| `operator_session_summary` | 현재 문서: {0} · 수정본 {1}건 | Current document: {0} · {1} revisions |
| `operator_no_open_doc` | 열린 문서가 없습니다 | No open document |
| `operator_prompt_placeholder` | 작업 지시 입력 | Enter an instruction for the agent |
| `operator_prompt_submit` | 실행 | Run |
| `operator_prompt_stop` | 멈추기 | Stop |
| `operator_composer_blocked` | 지금은 실행할 수 없습니다. | Cannot run right now. |
| `operator_turns_empty` | 아직 실행한 작업이 없습니다. 지시를 보내면 이력이 여기에 표시됩니다. | No turns yet. Sent instructions will appear here. |
| `operator_turn_working` | 실행 중입니다 | Running |
| `operator_turn_fault` | 서비스 제공자 오류가 발생했습니다 | Provider fault |
| `operator_turn_failed` | 실행하지 못했습니다 | Failed |
| `operator_turn_plan_ready` | 변경 제안이 도착했습니다 | Proposal arrived |
| `operator_turn_no_plan` | 변경 제안이 없습니다 | No proposal |
| `operator_turn_count` | {0}단계 | {0} turns |
| `operator_turn_fault_note` | 문서에 대한 판정이 아닙니다. 변경 제안과 승인 상태는 그대로입니다. | This is not a document verdict; proposals and approvals are unchanged. |
| `operator_turn_plan_adopted` | 검토 대기열에 반영되었습니다. 검토 화면에서 직접 승인해야 문서에 적용됩니다. | Adopted into the review queue. Approve on the Review screen to apply. |
| `operator_turn_plan_not_queued` | 제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 대기열에는 넣지 않았습니다. | The document or review queue changed in flight, so this proposal was not queued. |
| `operator_turn_never_compiled` | 현재 연결에서는 요청한 기능을 지원하지 않습니다. | The requested capability is not supported in this session. |
| `operator_turn_events_summary` | 세부 기록 ({0}) | Host events ({0}) |
| `operator_events_heading` | 문서 작업 기록 | Document activity log |
| `operator_events_count` | {0}건 | {0} events |
| `operator_events_live` | 실시간 | Live |
| `operator_events_disconnected` | 연결이 끊겼습니다 | Disconnected |
| `operator_events_idle` | 대기 중입니다 | Idle |
| `operator_events_sub_error` | 작업 기록을 받아오지 못했습니다. | Failed to subscribe to events |
| `operator_events_empty` | 아직 이 문서에 기록된 사건이 없습니다. | No events recorded for this document yet. |
| `operator_protocol_chatter` | 프로토콜 통신 기록 ({0}) | Protocol trace ({0}) |
| `operator_protocol_note` | 위쪽은 문서 사건 기록이고, 여기는 진단용 내부 통신 내역입니다. | Above is the document event log; below is diagnostic shell-runtime traffic. |
| `operator_provider_heading` | 서비스 제공자 | Provider |
| `operator_provider_mock_label` | 내장 모의 제공자 | Built-in mock |
| `operator_provider_mock_blurb` | 네트워크도 시계도 없는 결정론 제공자입니다. 같은 문서에는 같은 요청을 냅니다. | Deterministic offline provider without network or clock. |
| `operator_provider_router_label` | 사용자 지정 라우터 | Custom router |
| `operator_provider_router_blurb` | 호환 접속 주소와 모델 이름을 직접 지정합니다. | OpenAI-compatible endpoint with custom base URL and model. |
| `operator_provider_anthropic_label` | 앤스로픽 | Anthropic |
| `operator_provider_anthropic_blurb` | 공식 메시지 연결입니다. 키를 저장하고 지시를 보낼 때만 호출합니다. | Official Messages API; network calls occur only when credentials are set and run. |
| `operator_scenario_heading` | 모의 대본 | Mock scenario |
| `operator_scenario_propose_one` | 한 칸 채우기 제안 | Propose single blank |
| `operator_scenario_propose_invalid` | 쓰기 전 확인에서 막히는 제안 | Propose invalid plan |
| `operator_scenario_propose_wait` | 제안 후 승인 대기 | Propose and await approval |
| `operator_scenario_escalate` | 적용 시도 후 차단 확인 | Attempt apply (blocked at gate) |
| `operator_scenario_note` | 인증 키나 네트워크 없이 동작합니다. | Uses neither credentials nor network. |
| `operator_router_heading` | 라우터 설정 | Router configuration |
| `operator_field_base_url` | 접속 주소 | Base URL |
| `operator_field_model` | 모델 이름 | Model |
| `operator_field_store_key` | 자격 증명 이름 | Credential key name |
| `operator_anthropic_heading` | 앤스로픽 설정 | Anthropic configuration |
| `operator_anthropic_model_placeholder` | 비워 두면 기본값 사용 | Leave empty for adapter default |
| `operator_model_empty_note` | 모델 이름을 비워 두면 연결 쪽 기본값을 사용합니다. | Leaving model blank uses the adapter's default. |
| `operator_save_settings` | 설정 저장 | Save settings |
| `operator_settings_dirty` | 저장되지 않은 변경이 있습니다 | Unsaved changes |
| `operator_credential_heading` | 자격 증명 | Credentials |
| `operator_credential_note` | 비밀 값은 이 기계의 자격 증명 저장소에만 들어가며, 설정 파일에는 이름만 저장되고 화면에 다시 표시되지 않습니다. | Secrets go straight to the OS credential store; config stores only the key name and secrets are never read back. |
| `operator_credential_status_label` | 현재 상태 | Status |
| `operator_credential_stored` | 저장되어 있습니다 ({0} · {1}바이트) | Present ({0} · {1} bytes) |
| `operator_credential_absent` | 저장된 자격 증명이 없습니다 ({0}) | Absent ({0}) |
| `operator_credential_unnamed` | 이름 없음 | unnamed |
| `operator_credential_paste_label` | 값 붙여넣기 | Paste secret |
| `operator_credential_placeholder` | 자격 증명 값 입력 | Enter credential value |
| `operator_credential_store_btn` | 저장소에 넣기 | Store credential |
| `operator_credential_forget_btn` | 지우기 | Forget |
| `operator_probe_heading` | 지원 기능 확인 | Check supported capabilities |
| `operator_probe_btn` | 지원 기능 확인 | Check supported capabilities |
| `operator_probe_busy` | 확인 중입니다 | Probing... |
| `operator_probe_note` | 어댑터가 무엇을 지원하는지만 로컬에서 확인합니다. | Asks the adapter locally what it supports; touches neither document nor network. |
| `operator_cap_model_prefix` | 모델: {0} | Model: {0} |
| `operator_cap_verdict_label` | 자격 증명 참조 | Credential ref |
| `operator_cap_th_capability` | 기능 | Capability |
| `operator_cap_th_supported` | 지원 | Support |
| `operator_cap_th_reason` | 사유 | Reason |
| `operator_cap_th_source` | 출처 | Source |
| `operator_cap_text` | 글 생성 | Text generation |
| `operator_cap_tools` | 도구 호출 | Structured tool use |
| `operator_cap_streaming` | 토막 전송 | Streaming |
| `operator_cap_structured` | 구조화 출력 | Structured output |
| `operator_cap_models` | 모델 목록 | Model discovery |
| `operator_cap_thread` | 대화 이어받기 | Resumable thread |
| `operator_cap_vision` | 그림 입력 | Vision |
| `operator_state_yes` | 예 | Yes |
| `operator_state_no` | 아니오 | No |
| `operator_state_unknown` | 확인하지 못했습니다 | Unknown |
| `operator_cred_configured` | 설정되어 있습니다 | Configured |
| `operator_cred_missing` | 자격 증명이 없습니다 | Missing |
| `operator_cred_not_required` | 자격 증명이 필요하지 않습니다 | Not required |
| `operator_cred_unsupported` | 이 인증 방식은 지원하지 않습니다 | Unsupported |
| `operator_own_none` | 인증 키가 필요하지 않습니다 | No key required |
| `operator_own_env` | 환경 변수 이름으로 참조합니다 | Referenced via environment variable |
| `operator_own_os` | 운영체제 저장소 키로 참조합니다 | Referenced via OS credential store |
| `operator_own_managed` | 서비스 제공자가 인증을 관리합니다 | Provider-managed authentication |
| `operator_config_heading` | 이 제공자가 읽을 설정 파일 | Provider config file |
| `operator_config_note` | 이 설정에는 비밀 값 대신 자격 증명 이름만 저장됩니다. | This configuration stores credential names instead of secret values. |
| `operator_config_empty` | 아직 저장된 설정 파일이 없습니다. | No config file saved yet. |
| `operator_event_opened` | 문서를 열었습니다 — {0} | Opened document — {0} |
| `operator_event_proposed` | 변경 작업 {0}건을 제안했습니다 — {1} | Proposed {0} operations — {1} |
| `operator_event_validated_ok` | 쓰기 전 확인을 통과했습니다 | Pre-write validation passed |
| `operator_event_validated_fail` | 쓰기 전 확인에서 막혔습니다 | Pre-write validation blocked |
| `operator_event_approval_req` | 승인을 요청했습니다 — {0} | Approval requested — {0} |
| `operator_event_approved` | {0}이(가) 승인했습니다 | Approved by {0} |
| `operator_event_rejected` | {0}이(가) 돌려보냈습니다 | Returned by {0} |
| `operator_event_applied` | 변경 제안을 사본에 적용했습니다 | Applied change proposal to copy |
| `operator_event_candidate` | 수정본을 남겼습니다 · 검사 {0} | Saved revision · checks {0} |
| `operator_event_check_pass` | 통과 | passed |
| `operator_event_check_fail` | 미통과 | not passed |
| `operator_event_pdf` | 인쇄 화면용 문서를 준비했습니다 | Prepared print view document |
| `review_behind_head_banner` | 이 변경 제안은 수정본 {0} 이전 문서를 기준으로 만들어졌습니다. 그대로 적용하면 수정본 {0}의 변경이 빠집니다. | This proposal was made against a document older than revision {0}. Applying it would drop the changes in revision {0}. |
| `review_repropose_on_head` | 수정본 {0} 기준으로 다시 제안 | Re-propose on revision {0} |
| `review_repropose_on_latest` | 최신 수정본 기준으로 다시 제안 | Re-propose on the latest revision |
| `proposer_mock` | 시험용 제안 | Test proposal |
| `proposer_agent` | 에이전트 | Agent |
| `proposer_user` | 직접 입력 | Typed by you |
| `review_prompt_not_connected` | 에이전트가 연결되지 않았습니다 | No agent connected |
| `review_prompt_connect` | 연결 설정 | Connection settings |
| `review_prompt_mock_note` | 시험용 에이전트가 시험용 값을 제안합니다 | The test agent proposes test values |
| `page_label_original` | 원본 · 미리보기 · 실제 인쇄 결과와 다를 수 있습니다. | Original · Preview · May differ from printed output. |
| `page_label_revision` | 수정본 {0} (현재) · 미리보기 · 실제 인쇄 결과와 다를 수 있습니다. | Revision {0} (current) · Preview · May differ from printed output. |
| `page_label_review_on_revision` | 수정본 {0}에 제안을 적용한 모습 · 미리보기 · 실제 인쇄 결과와 다를 수 있습니다. | Revision {0} with proposed changes · Preview · May differ from printed output. |
| `page_show_original` | 원본 보기 | Show original |
| `page_show_revision` | 수정본 보기 | Show revision |
| `guard_tag_new_values` | 새로 넣은 숫자·날짜 | New numbers or dates |
| `guard_tag_removed_with_guide` | 안내문과 함께 빠진 표현 | Removed with guide text |
| `guard_value_gone` | 없어짐 | gone |
| `approval_warn_changed` | 바뀐 사실 {0}곳: {1}. | {0} changed facts: {1}. |
| `approval_warn_removed` | 안내문과 함께 빠지는 표현 {0}곳: {1}. | {0} expressions removed with guide text: {1}. |
| `approval_warn_added` | 새로 넣은 숫자·날짜 {0}곳: {1}. | {0} new numbers or dates: {1}. |
| `approval_warn_unattributed` | 어느 변경에서 생겼는지 알 수 없는 차이 {0}곳. | {0} differences not tied to any change. |
| `approval_warn_show_all` | 경고 {0}건 모두 보기 | Show all {0} warnings |
| `approval_warn_full_changed` | 바뀐 사실 · {0} | Changed fact · {0} |
| `approval_warn_full_removed` | 안내문과 함께 빠지는 표현 · {0} | Removed with guide text · {0} |
| `approval_warn_full_added` | 새로 넣은 숫자·날짜 · {0} | New number or date · {0} |
| `approval_warn_full_unattributed` | 변경과 연결되지 않은 차이 · 문단 {0} {1} | Untied difference · Paragraph {0} {1} |
| `undo_conflict_item` | {0}: 지금 ‘{1}’, 되돌릴 변경이 넣은 값 ‘{2}’ | {0}: now ‘{1}’, the reversed change wrote ‘{2}’ |
| `undo_before_after` | {0}: ‘{1}’ → ‘{2}’ | {0}: ‘{1}’ → ‘{2}’ |
| `base_source` | 원본 | Original |
| `base_revision` | 수정본 {0} | Revision {0} |
| `base_revision_unknown` | 이전 수정본 | Earlier revision |
| `approval_meta_line` | 제안: {0} · 기준: {1} | Proposed by: {0} · Based on: {1} |
| `approval_step_checking` | 변경 제안을 다시 확인하는 중입니다 | Re-checking the proposal |
| `approval_step_recording` | 승인을 기록하는 중입니다 | Recording the approval |
| `approval_step_applying` | 수정본을 만들고 점검하는 중입니다 | Creating and checking the revision |
| `approval_copy_hash` | 복사 | Copy |
| `toast_hash_copied` | 검증값을 복사했습니다 | Copied the verification value |
| `approval_mock_ack` | 시험용 값임을 확인했습니다 | I understand these are test values |
| `review_char_shape_applied` | 본문 글자 모양에 맞춤 | Matched to body text style |
| `review_blocked_hard` | {0}건을 고쳐야 승인할 수 있습니다 | Fix {0} items to approve |
| `review_blocked_returned` | 돌려보낸 변경 {0}건을 빼거나 다시 넣어야 승인할 수 있습니다 | Remove or re-add {0} returned changes to approve |
| `review_blocked_behind_head` | 최신 수정본 기준으로 다시 제안해야 승인할 수 있습니다 | Re-propose on the latest revision to approve |
| `review_returned_tag` | 돌려보낸 변경 | Returned change |
| `review_readd` | 다시 넣기 | Re-add |
| `draft_restored` | 입력해 둔 값 {0}개를 불러왔습니다 | Restored {0} values you had entered |
| `history_proposer_line` | 제안: {0} | Proposed by: {0} |
| `history_receipt_verified` | 영수증을 확인했습니다 | Receipt verified |
| `history_receipt_failed` | 영수증이 수정본과 맞지 않습니다 | Receipt does not match the revision |
| `history_receipt_checking` | 영수증을 확인하고 있습니다 | Checking the receipt |
| `history_checks_open` | 자동 점검에서 확인할 항목이 남아 있습니다 | Automatic checks left items to review |
| `review_applied_guard_line` | 사실 점검에서 확인할 변경 {0}건을 함께 적용했습니다 | Applied with {0} changes flagged by the fact check |
| `err_undo_unfixable` | 되돌리기 제안을 만들지 않았습니다. 그대로 만들면 승인할 수 없는 항목이 생깁니다. {0} | No undo proposal was created. It would contain items that cannot be approved. {0} |
| `settings_agent_label` | 에이전트 | Agent |
| `settings_agent_not_connected` | 연결되지 않았습니다 | Not connected |
| `settings_agent_mock` | 시험용 에이전트를 쓰고 있습니다 | Using the test agent |
| `settings_agent_connected` | 연결되어 있습니다 | Connected |
| `settings_agent_dev_mock` | 시험용 에이전트 쓰기 (개발자 설정) | Use the test agent (developer setting) |
| `settings_agent_note` | 에이전트는 변경을 제안만 하며 승인할 수 없습니다. | Agents can only propose changes; they cannot approve them. |
| `guard_noun_numbers` | 숫자 | number |
| `guard_noun_dates` | 날짜 | date |
| `guard_noun_direct_quotes` | 인용문 | quotation |
| `guard_noun_qualifiers` | 부정·한정 표현 | negation or qualifier |
| `guard_noun_quantifiers` | 수량 표현 | quantity expression |
| `guard_noun_causal_markers` | 인과 표현 | causal phrasing |
| `guard_noun_direction_words` | 증감·방향 표현 | direction word |
| `guard_noun_urls` | 웹 주소 | web address |
| `guard_noun_citations` | 출처 표기 | citation |
| `guard_noun_inline_math` | 수식 | formula |
| `guard_noun_headings` | 제목·보호 문구 | heading or protected text |
