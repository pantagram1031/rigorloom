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
| `open_drop_sub` | 파일이나 기본 양식을 선택할 수 있습니다. | Or choose a file from your computer or a built-in form. |
| `open_choose_file` | 파일 선택 | Choose file |
| `open_builtin_forms` | 기본 양식 열기 | Open built-in form |
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
| `review_approve_dialog_title` | 변경 {0}건 적용 승인 | Approve {0} changes |
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
| `cmd_open_builtin` | 기본 양식 열기 | Open built-in form |
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
