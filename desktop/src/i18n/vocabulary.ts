export type UiLanguage = "ko" | "en";

export interface VocabEntry {
  readonly ko: string;
  readonly en: string;
}

export const OP_KIND_VOCAB = {
  fill_cell: { ko: "빈칸 채움", en: "Fill blank" },
  replace_at_cell: { ko: "칸 문구 바꿈", en: "Replace cell text" },
  set_run: { ko: "본문 문구 바꿈", en: "Replace body text" },
  delete_guides: { ko: "안내문 지움", en: "Remove guide text" },
  normalize_clones: {
    ko: "중복 글자 서식 정리",
    en: "Clean up duplicate text styles",
  },
  goto_text: { ko: "문구 위치로 이동", en: "Jump to text" },
  insert_text: { ko: "문구 넣기", en: "Insert text" },
  insert_equation: { ko: "수식 넣기", en: "Insert equation" },
  insert_table: { ko: "표 넣기", en: "Insert table" },
  page_binding: { ko: "제본 여백 조정", en: "Set binding margin" },
  replace_all: { ko: "문구 일괄 바꿈", en: "Replace all occurrences" },
  insert_blank_before: { ko: "앞에 빈 줄 넣기", en: "Insert blank line above" },
  insert_picture: { ko: "그림 넣기", en: "Insert image" },
  set_line_spacing: { ko: "줄 간격 조정", en: "Adjust line spacing" },
  put_field: { ko: "누름틀 값 채움", en: "Fill form field" },
  find_delete: { ko: "문구 찾아 지움", en: "Find and remove text" },
  move: { ko: "커서 이동", en: "Move cursor" },
  edit_equation: { ko: "수식 고침", en: "Edit equation" },
  set_cell: { ko: "표 칸 내용 입력", en: "Enter table cell content" },
  set_char_color: { ko: "글자 색 바꿈", en: "Change text colour" },
  delete_ctrls: { ko: "개체 삭제", en: "Remove objects" },
  collapse_empty_paragraphs: { ko: "연속 빈 줄 합침", en: "Collapse blank lines" },
  delete_blank_after: { ko: "뒤쪽 빈 줄 지움", en: "Remove blank line below" },
  delete_blank_before: { ko: "앞쪽 빈 줄 지움", en: "Remove blank line above" },
  set_para_align: { ko: "문단 정렬 바꿈", en: "Change paragraph alignment" },
  insert_hyperlink: { ko: "웹 링크 넣기", en: "Insert web link" },
  page_break_before: { ko: "앞쪽 쪽 나누기", en: "Insert page break before" },
} as const satisfies Record<string, VocabEntry>;

export const OP_KIND_MODE_VOCAB = {
  "replace_at_cell:replace": { ko: "칸 문구 바꿈", en: "Replace cell text" },
  "replace_at_cell:append": { ko: "칸 문구 덧붙임", en: "Append to cell" },
} as const satisfies Record<string, VocabEntry>;

export const PLAN_STATE_VOCAB = {
  proposed: { ko: "제안이 도착했습니다", en: "Proposed" },
  validated: { ko: "검토 중입니다", en: "In review" },
  invalid: { ko: "수정이 필요합니다", en: "Needs fixes" },
  approved: { ko: "승인했습니다", en: "Approved" },
  rejected: { ko: "돌려보냈습니다", en: "Returned" },
  applied: { ko: "적용했습니다", en: "Applied" },
} as const satisfies Record<string, VocabEntry>;

export const RULE_STATE_VOCAB = {
  clean: {
    ko: "제출 전 점검을 통과했습니다",
    en: "Pre-submission check passed",
  },
  warn: { ko: "추가 확인이 필요합니다", en: "Needs review" },
  hard: { ko: "수정 후 적용할 수 있습니다", en: "Fix issues before applying" },
  skipped: { ko: "점검하지 않았습니다", en: "Check skipped" },
} as const satisfies Record<string, VocabEntry>;

export const CHECK_STATE_VOCAB = {
  ran: { ko: "점검을 마쳤습니다", en: "Check complete" },
  unavailable: { ko: "지금은 점검할 수 없습니다", en: "Check unavailable" },
  skipped: { ko: "점검하지 않았습니다", en: "Check skipped" },
  not_run: { ko: "아직 점검하지 않았습니다", en: "Not checked yet" },
  pass: {
    ko: "제출 전 점검을 통과했습니다",
    en: "Pre-submission check passed",
  },
  partial: { ko: "추가 확인이 필요합니다", en: "Needs review" },
  fail: { ko: "수정 후 적용할 수 있습니다", en: "Fix issues before applying" },
} as const satisfies Record<string, VocabEntry>;

export const APPROVAL_STATE_VOCAB = {
  pending: { ko: "승인을 기다리고 있습니다", en: "Awaiting approval" },
  approved: { ko: "승인했습니다", en: "Approved" },
  auto_approved: {
    ko: "규칙에 따라 자동 승인했습니다",
    en: "Automatically approved by rule",
  },
  rejected: { ko: "돌려보냈습니다", en: "Returned" },
} as const satisfies Record<string, VocabEntry>;

export const RENDER_GRADE_VOCAB = {
  hancom: { ko: "한글 인쇄 화면", en: "Hancom print view" },
  pdf: { ko: "인쇄 화면", en: "Print view" },
  "own-uncertified": {
    ko: "자체 미리보기 · 인쇄 결과와 대조하지 않았습니다.",
    en: "Rigorloom preview · Not checked against printed output.",
  },
} as const satisfies Record<string, VocabEntry>;

export const CELL_CLASS_VOCAB = {
  fill_target: { ko: "입력할 빈칸", en: "Blank to fill" },
  static: {
    ko: "이 칸은 입력용 빈칸이 아닙니다.",
    en: "This cell is not a fillable blank.",
  },
  guide: { ko: "작성 안내문", en: "Form instructions" },
  spacer: { ko: "여백용 칸", en: "Spacing cell" },
} as const satisfies Record<string, VocabEntry>;

export const GUARD_CATEGORY_VOCAB = {
  paragraph_count_changed: {
    ko: "문단 수가 바뀌었습니다",
    en: "Paragraph count changed",
  },
  numbers: { ko: "바뀐 숫자", en: "Changed number" },
  dates: { ko: "바뀐 날짜", en: "Changed date" },
  direct_quotes: { ko: "바뀐 인용문", en: "Changed quotation" },
  qualifiers: {
    ko: "바뀐 부정·한정 표현",
    en: "Changed negation or qualifier",
  },
  quantifiers: { ko: "바뀐 수량 표현", en: "Changed quantity expression" },
  causal_markers: { ko: "바뀐 인과 표현", en: "Changed causal phrasing" },
  direction_words: {
    ko: "바뀐 증감·방향 표현",
    en: "Changed increase, decrease, or direction",
  },
  urls: { ko: "바뀐 웹 주소", en: "Changed web address" },
  markdown_links: { ko: "바뀐 웹 주소", en: "Changed web address" },
  citations: { ko: "바뀐 출처 표기", en: "Changed citation" },
  source_ids: { ko: "바뀐 출처 표기", en: "Changed citation" },
  inline_math: { ko: "바뀐 수식", en: "Changed formula" },
  headings: {
    ko: "바뀐 제목·태그·보호 문구",
    en: "Changed heading, tag, or protected text",
  },
  tags: {
    ko: "바뀐 제목·태그·보호 문구",
    en: "Changed heading, tag, or protected text",
  },
  protected_spans: {
    ko: "바뀐 제목·태그·보호 문구",
    en: "Changed heading, tag, or protected text",
  },
} as const satisfies Record<string, VocabEntry>;

const MSG_CELL_NOT_FILL_TARGET: VocabEntry = {
  ko: "이 칸은 입력용 빈칸이 아닙니다.",
  en: "This cell is not a fillable blank.",
};
const MSG_COLOR_ANOMALY: VocabEntry = {
  ko: "빈칸의 기본 글자색이 본문과 다릅니다. 확인이 필요합니다.",
  en: "The blank’s default text colour differs from the body text. Check the colour.",
};
const MSG_SCRIPT_ANOMALY: VocabEntry = {
  ko: "위첨자나 아래첨자 서식이 있는 칸입니다. 글자 크기 확인이 필요합니다.",
  en: "This blank uses superscript or subscript formatting. Check the text size.",
};
const MSG_REPLACE_AMBIGUOUS: VocabEntry = {
  ko: "같은 칸에 같은 문구가 여러 번 있어 바꿀 위치를 찾을 수 없습니다.",
  en: "The same text appears more than once in this cell. Could not identify which occurrence to change.",
};
const MSG_RUN_UNAVAILABLE: VocabEntry = {
  ko: "이 문구의 위치나 서식 정보를 확인할 수 없어 직접 고칠 수 없습니다.",
  en: "Could not find the text or its formatting information. Inline editing is unavailable.",
};
const MSG_OP_INVALID: VocabEntry = {
  ko: "입력한 변경 내용을 확인해야 합니다.",
  en: "Check the change details.",
};
const MSG_MALFORMED: VocabEntry = {
  ko: "문서 파일 구조에 문제가 있습니다.",
  en: "There is a problem with the document’s file structure.",
};
const MSG_PINNED_MISSING: VocabEntry = {
  ko: "필수 문구가 문서에서 빠졌습니다.",
  en: "Required text is missing from the document.",
};
const MSG_SOURCE_REJECTED: VocabEntry = {
  ko: "지원하지 않거나 변환할 수 없는 파일입니다. 지원하는 형식의 문서를 선택해야 합니다.",
  en: "This file is unsupported or cannot be converted. Choose a supported document.",
};
const MSG_NEEDS_HANCOM: VocabEntry = {
  ko: "파일을 변환할 수 없습니다. 한글에서 지원하는 형식으로 다시 저장한 뒤 열어야 합니다.",
  en: "Could not convert the file. Save it as .hwpx in Hancom Office, then open it again.",
};
const MSG_TOO_LARGE: VocabEntry = {
  ko: "문서나 선택 영역이 너무 커서 한 번에 불러올 수 없습니다.",
  en: "The document or selection is too large to load at once.",
};
const MSG_ARTIFACT_MISSING: VocabEntry = {
  ko: "문서 파일을 찾을 수 없습니다. 문서를 다시 열어야 합니다.",
  en: "Could not find the document file. Reopen the document.",
};
const MSG_HASH_MISMATCH: VocabEntry = {
  ko: "저장된 수정본이나 검증 기록이 일치하지 않습니다.",
  en: "The saved revision or verification record does not match.",
};
const MSG_EXPORT_FAILED: VocabEntry = {
  ko: "파일을 내보내지 못했습니다. 자세히에서 원인을 확인할 수 있습니다.",
  en: "Could not export the file. See details for the cause.",
};
const MSG_NOT_INVERTIBLE: VocabEntry = {
  ko: "이 변경을 자동으로 되돌리는 제안을 만들 수 없습니다.",
  en: "Could not propose an automatic undo for this change.",
};
const MSG_CARET_REFUSAL: VocabEntry = {
  ko: "선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다.",
  en: "This selection cannot be edited at once. Edit smaller sections.",
};
const MSG_AGENT_CONFIG: VocabEntry = {
  ko: "에이전트 연결 설정이 필요합니다. 명령창에서 설정할 수 있습니다.",
  en: "Set up the agent connection in the command palette.",
};
const MSG_SESSION_UNKNOWN: VocabEntry = {
  ko: "열려 있던 문서를 찾을 수 없습니다. 문서를 다시 열어야 합니다.",
  en: "Could not find the open document. Reopen it.",
};
const MSG_PLAN_UNKNOWN: VocabEntry = {
  ko: "변경 제안이나 승인 요청을 찾을 수 없습니다.",
  en: "Could not find the proposed changes or approval request.",
};
const MSG_UNSUPPORTED_ACTION: VocabEntry = {
  ko: "현재 환경에서는 이 편집을 지원하지 않습니다.",
  en: "This edit is not supported in the current environment.",
};
const MSG_RENDER_UNAVAILABLE: VocabEntry = {
  ko: "요청한 인쇄 화면을 표시할 수 없습니다.",
  en: "Cannot display the requested print view.",
};
const MSG_INTERNAL_ERROR: VocabEntry = {
  ko: "작업을 처리하지 못했습니다. 자세히에서 원인을 확인할 수 있습니다.",
  en: "Could not complete the task. See details for the cause.",
};
const MSG_CONNECTION_PROBLEM: VocabEntry = {
  ko: "작업 공간 연결에 문제가 있습니다. 자세히에서 원인을 확인할 수 있습니다.",
  en: "There is a problem with the workspace connection. See details for the cause.",
};
const MSG_AGENT_UNREADABLE: VocabEntry = {
  ko: "에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다.",
  en: "Could not display the agent’s proposal. Request it again.",
};

export const ERROR_CODE_VOCAB = {
  // Transport codes (rt_codes.py TRANSPORT_CODES)
  protocol_version_unsupported: MSG_CONNECTION_PROBLEM,
  not_initialized: MSG_CONNECTION_PROBLEM,
  already_initialized: MSG_CONNECTION_PROBLEM,
  frame_too_large: MSG_TOO_LARGE,
  frame_malformed: MSG_CONNECTION_PROBLEM,
  duplicate_key: MSG_CONNECTION_PROBLEM,
  nonfinite_number: MSG_CONNECTION_PROBLEM,
  unknown_field: MSG_CONNECTION_PROBLEM,
  unknown_method: MSG_CONNECTION_PROBLEM,
  invalid_params: MSG_OP_INVALID,
  duplicate_request_id: MSG_CONNECTION_PROBLEM,
  response_too_large: MSG_TOO_LARGE,
  cancelled: { ko: "작업을 취소했습니다.", en: "Task cancelled." },
  internal_error: MSG_INTERNAL_ERROR,

  // Domain codes (rt_codes.py DOMAIN_CODES)
  unknown_session: MSG_SESSION_UNKNOWN,
  unknown_plan: MSG_PLAN_UNKNOWN,
  unknown_approval: MSG_PLAN_UNKNOWN,
  unknown_op_kind: MSG_UNSUPPORTED_ACTION,
  unsupported_backend: MSG_UNSUPPORTED_ACTION,
  plan_stale: {
    ko: "문서가 바뀌었습니다. 최신 문서에 맞춰 변경 제안을 다시 만들어야 합니다.",
    en: "The document has changed. Recreate the proposed changes using the latest version.",
  },
  plan_not_approved: {
    ko: "승인 후 적용할 수 있습니다.",
    en: "Approve the changes before applying them.",
  },
  apply_in_progress: {
    ko: "변경 내용을 문서에 적용하고 있습니다.",
    en: "Applying changes to the document.",
  },
  apply_outcome_unknown: {
    ko: "적용을 마쳤는지 확인할 수 없습니다. 기록에서 적용 여부를 확인해야 합니다.",
    en: "Could not confirm whether the changes were applied. Check history for the result.",
  },
  plan_invalid: {
    ko: "수정할 항목이 있어 아직 적용할 수 없습니다.",
    en: "Resolve the flagged items before applying the changes.",
  },
  approval_binding_mismatch: {
    ko: "승인한 뒤 문서나 변경 제안이 바뀌었습니다. 다시 검토하고 승인해야 합니다.",
    en: "The document or proposed changes have changed since approval. Review and approve them again.",
  },
  approval_already_resolved: {
    ko: "이미 처리한 승인 요청입니다.",
    en: "This approval request has already been resolved.",
  },
  region_too_large: MSG_TOO_LARGE,
  source_rejected: MSG_SOURCE_REJECTED,
  path_escape: {
    ko: "허용된 작업 폴더 밖의 파일은 열 수 없습니다.",
    en: "Cannot access files outside the allowed workspace folder.",
  },
  artifact_missing: MSG_ARTIFACT_MISSING,
  candidate_hash_mismatch: MSG_HASH_MISMATCH,
  receipt_body_mismatch: MSG_HASH_MISMATCH,
  capability_unavailable: MSG_UNSUPPORTED_ACTION,
  publication_failed: MSG_INTERNAL_ERROR,
  backend_refused: MSG_UNSUPPORTED_ACTION,
  child_python_invalid: MSG_INTERNAL_ERROR,
  render_failed: MSG_RENDER_UNAVAILABLE,
  page_out_of_range: MSG_RENDER_UNAVAILABLE,
  unknown_subscription: MSG_CONNECTION_PROBLEM,
  subscription_limit: MSG_CONNECTION_PROBLEM,
  com_busy: {
    ko: "한글에서 다른 작업을 처리하고 있습니다. 잠시 후 다시 시도할 수 있습니다.",
    en: "Hancom Office is busy. Try again shortly.",
  },
  needs_hancom: MSG_NEEDS_HANCOM,
  convert_failed: MSG_NEEDS_HANCOM,
  not_convertible: MSG_SOURCE_REJECTED,
  ambiguous_fill_keys: {
    ko: "이름이 같은 빈칸이 여러 개 있습니다. 입력할 칸을 구분해야 합니다.",
    en: "Multiple blanks have the same label. Identify the blank to fill.",
  },

  // Plan validation findings & UI refusal codes
  cell_not_fill_target: MSG_CELL_NOT_FILL_TARGET,
  cell_address_unknown: {
    ko: "양식에서 해당 칸을 찾을 수 없습니다.",
    en: "Could not find this cell in the form.",
  },
  fill_charpr_color_anomaly: MSG_COLOR_ANOMALY,
  color_anomaly: MSG_COLOR_ANOMALY,
  fill_charpr_script_anomaly: MSG_SCRIPT_ANOMALY,
  script_anomaly_target: MSG_SCRIPT_ANOMALY,
  run_color_anomaly: {
    ko: "바꾸려는 문구에 강조색이 있습니다.",
    en: "The text to replace contains an emphasis colour.",
  },
  at_cell_expect_mismatch: {
    ko: "처음 읽은 뒤 칸의 문구가 바뀌었습니다.",
    en: "The cell text has changed since it was read.",
  },
  replace_key_ambiguous: MSG_REPLACE_AMBIGUOUS,
  at_cell_run_ambiguous: MSG_REPLACE_AMBIGUOUS,
  run_inventory_unavailable: MSG_RUN_UNAVAILABLE,
  run_address_unknown: MSG_RUN_UNAVAILABLE,
  op_field_invalid: MSG_OP_INVALID,
  xml_wellformedness: MSG_MALFORMED,
  artifact_malformed: MSG_MALFORMED,
  form_residue: {
    ko: "작성 안내문이 남아 있습니다.",
    en: "Form instructions remain in the document.",
  },
  pinned_target_missing: MSG_PINNED_MISSING,
  expected_text_missing: MSG_PINNED_MISSING,
  source_not_found: MSG_ARTIFACT_MISSING,
  candidate_not_found: MSG_ARTIFACT_MISSING,
  recovery_receipt_mismatch: MSG_HASH_MISMATCH,
  export_hash_mismatch: MSG_EXPORT_FAILED,
  export_download_failed: MSG_EXPORT_FAILED,
  not_invertible: MSG_NOT_INVERTIBLE,
  previous_value_unreadable: MSG_NOT_INVERTIBLE,
  cross_run: MSG_CARET_REFUSAL,
  multi_run: MSG_CARET_REFUSAL,
  utf16_split: MSG_CARET_REFUSAL,
  no_host: MSG_AGENT_CONFIG,
  no_credential: MSG_AGENT_CONFIG,
  no_credential_name: MSG_AGENT_CONFIG,
  no_base_url: MSG_AGENT_CONFIG,
  guard_unavailable: {
    ko: "지금은 사실 변경 여부를 점검할 수 없습니다.",
    en: "Cannot check for changes to facts right now.",
  },
  session_not_found: MSG_SESSION_UNKNOWN,
  plan_not_found: MSG_PLAN_UNKNOWN,
  draft_superseded: {
    ko: "새 변경 제안으로 이전 초안을 바꿨습니다.",
    en: "New proposed changes replaced the previous draft.",
  },
  agent_output_unreadable: MSG_AGENT_UNREADABLE,
  agent_plan_before_unreadable: MSG_AGENT_UNREADABLE,
  agent_plan_projection_unsupported: MSG_AGENT_UNREADABLE,
  file_too_large: {
    ko: "파일 크기가 너무 커서 열 수 없습니다.",
    en: "The file is too large to open.",
  },
} as const satisfies Record<string, VocabEntry>;

export const VOCABULARY = {
  // Navigation & top bar
  nav_open: { ko: "열기", en: "Open" },
  nav_review: { ko: "검토", en: "Review" },
  nav_fill: { ko: "채우기", en: "Fill" },
  nav_history: { ko: "기록", en: "History" },
  nav_settings: { ko: "설정", en: "Settings" },
  doc_none_open: { ko: "열린 문서 없음", en: "No document open" },
  action_command_palette: { ko: "명령창", en: "Command palette" },
  action_export: { ko: "파일 내보내기", en: "Export file" },
  action_open_doc: { ko: "문서 열기", en: "Open document" },
  lang_ko: { ko: "한국어", en: "Korean" },
  lang_en: { ko: "영어", en: "English" },
  action_switch_lang: { ko: "언어 바꾸기", en: "Switch language" },
  lang_switched_toast: {
    ko: "화면 언어를 한국어로 바꿨습니다.",
    en: "Switched display language to English.",
  },
  theme_light: { ko: "밝게", en: "Light" },
  theme_dark: { ko: "어둡게", en: "Dark" },
  theme_system: { ko: "시스템 설정", en: "System" },
  action_switch_theme: { ko: "화면 테마 바꾸기", en: "Change theme" },

  // Guard & review addendum (verbatim wording)
  guard_pill_kept: { ko: "점검한 사실 유지", en: "Checked facts unchanged" },
  guard_pill_changed: { ko: "바뀐 사실", en: "Changed facts" },
  guard_list_header: {
    ko: "수정한 문단의 숫자·날짜·인용문·부정 표현·증감 및 방향 표현만 점검하며, 내용이 맞는지는 판단하지 않습니다.",
    en: "The check looks only at numbers, dates, quotations, negation, and increase, decrease, or direction words in the edited paragraph; it does not judge whether the content is correct.",
  },
  guard_added_numbers: { ko: "추가된 숫자:", en: "Added numbers:" },
  guard_not_run_invalid: { ko: "점검하지 않았습니다", en: "Not checked" },
  approve_dialog_effect: {
    ko: "승인하면 이 컴퓨터에서 변경 {0}건을 적용한 새 수정본을 만들며, 파일 내보내기는 별도 단계이고 어디에도 전송하지 않습니다.",
    en: "Approval creates a new revision on this machine with {0} changes applied; exporting the file is a separate step, and nothing is sent anywhere.",
  },
  approve_dialog_guard_skipped: {
    ko: "점검을 실행할 수 없어 사실 변경 여부를 점검하지 않았습니다.",
    en: "Changes to facts were not checked because the check could not run.",
  },
  page_label_review: {
    ko: "제안을 적용한 모습 · 미리보기 · 실제 인쇄 결과와 다를 수 있습니다.",
    en: "Preview with proposed changes · May differ from printed output.",
  },
  page_label_fill: {
    ko: "미리보기 · 실제 인쇄 결과와 다를 수 있습니다.",
    en: "Preview · May differ from printed output.",
  },
  page_omitted_object: { ko: "표시하지 않은 개체", en: "Object not shown" },
  fill_long_value: {
    ko: "긴 내용은 인쇄할 때 줄바꿈이 달라질 수 있습니다.",
    en: "Long entries may wrap differently when printed.",
  },
  fill_counter: {
    ko: "입력할 빈칸 {1}개 중 {0}개 입력",
    en: "{0} of {1} blanks filled",
  },
  open_pending_badge: {
    ko: "검토 대기 {0}건",
    en: "{0} pending changes",
  },
  open_sample_form_label: { ko: "예시 양식", en: "Example forms" },
  history_title_note: {
    ko: "변경을 적용한 수정본만 표시하며, 검토를 기다리는 변경 제안은 검토 화면에서 확인할 수 있습니다.",
    en: "Only revisions with applied changes are listed here; pending proposed changes are available in review.",
  },
  history_pending_link: {
    ko: "대기 중인 변경 제안 보기",
    en: "View pending proposed changes",
  },
  history_undo_scope: {
    ko: "현재 수정본에서 선택한 수정본의 변경을 되돌리는 제안을 만들며, 그 이후의 변경은 유지합니다.",
    en: "Creates a proposal to reverse the selected revision’s changes in the current revision while keeping later changes.",
  },
  history_approval_method_direct: {
    ko: "승인 방식: 직접 승인",
    en: "Approval method: Manual approval",
  },
  settings_folder_locked: {
    ko: "아직 확정하지 않은 초안이나 검토 중 또는 적용 중인 변경 제안이 있어 작업 폴더를 바꿀 수 없습니다.",
    en: "The workspace folder cannot be changed while any document has an uncommitted draft or proposed changes under review or being applied.",
  },
  settings_language_note: {
    ko: "화면 언어를 바꿔도 문서 내용은 바뀌지 않습니다.",
    en: "Changing the display language does not change the document text.",
  },
  settings_theme_note: {
    ko: "화면 테마를 바꿔도 인쇄할 파일은 바뀌지 않습니다.",
    en: "Changing the theme does not change the file you print.",
  },
  settings_folder_note: {
    ko: "작업 폴더는 이 프로그램이 실행되는 컴퓨터에 작업 사본과 수정 기록을 보관하는 곳이며, 파일 내보내기 위치와는 별개입니다.",
    en: "The workspace folder stores working copies and revision history on the machine running this application; it is separate from the export destination.",
  },
  print_view_grade_hancom: {
    ko: "한글 인쇄 화면",
    en: "Hancom print view",
  },
  print_view_grade_pdf: { ko: "인쇄 화면", en: "Print view" },
  print_view_grade_own: {
    ko: "자체 미리보기 · 인쇄 결과와 대조하지 않았습니다.",
    en: "Rigorloom preview · Not checked against printed output.",
  },

  // Open screen
  open_title: { ko: "문서 열기", en: "Open document" },
  open_subtitle: {
    ko: "원본은 그대로 두고 작업 사본을 엽니다.",
    en: "Opens a working copy while keeping the original file unchanged.",
  },
  open_drop_prompt: {
    ko: "한글 문서를 여기에 놓으면 열립니다.",
    en: "Drop a Hangul document here to open.",
  },
  open_drop_sub: {
    ko: "파일이나 예시 양식을 선택할 수 있습니다.",
    en: "Or choose a file from your computer or an example form.",
  },
  open_choose_file: { ko: "파일 선택", en: "Choose file" },
  open_builtin_forms: { ko: "예시 양식 열기", en: "Open example form" },
  open_recent_title: { ko: "최근 연 문서", en: "Recent documents" },
  open_recent_hint: {
    ko: "문서를 선택하면 이어서 작업할 수 있습니다.",
    en: "Select a document to continue working.",
  },
  open_empty_recent: {
    ko: "아직 연 문서가 없습니다.",
    en: "No documents opened yet.",
  },
  open_no_changes: { ko: "변경이 없습니다", en: "No changes" },
  open_pending_review: {
    ko: "변경 {0}건이 검토를 기다리고 있습니다",
    en: "{0} changes awaiting review",
  },
  open_hwp_help_title: {
    ko: "한글 파일 열기 안내",
    en: "Opening legacy Hangul files",
  },
  open_hwp_help_body: {
    ko: "이 파일은 한글에서 다시 저장한 뒤 열어야 합니다.",
    en: "This file must be saved again in Hancom Office before opening.",
  },
  open_hwp_help_steps: {
    ko: "한글에서 파일을 연 뒤 지원하는 한글 문서 형식으로 다시 저장하면 열 수 있습니다.",
    en: "Open the file in Hancom Office and save it in .hwpx format to open it here.",
  },
  open_drop_unsupported: MSG_SOURCE_REJECTED,

  // Review screen
  review_mode_document: { ko: "문서 보기", en: "Show document" },
  review_mode_print: { ko: "인쇄 화면 보기", en: "Show print view" },
  review_changes_header: { ko: "변경 {0}건", en: "{0} changes" },
  review_changed_facts_header: {
    ko: "바뀐 사실 {0}건",
    en: "{0} changed facts",
  },
  review_before_label: { ko: "변경 전: {0}", en: "Before: {0}" },
  review_after_label: { ko: "변경 후: {0}", en: "After: {0}" },
  review_agent_suggestion: { ko: "에이전트 제안", en: "Agent suggestion" },
  review_direct_edit: { ko: "직접 고치기", en: "Edit inline" },
  review_remove_item: { ko: "이 항목 빼기", en: "Remove" },
  review_collapse: { ko: "접기", en: "Collapse" },
  review_return: { ko: "돌려보내기", en: "Return" },
  review_approve: { ko: "승인", en: "Approve" },
  review_cancel: { ko: "취소", en: "Cancel" },
  review_return_reason_placeholder: {
    ko: "돌려보내는 이유 (선택)",
    en: "Reason for returning (optional)",
  },
  review_return_to_fill: { ko: "채우기로 돌아가기", en: "Return to fill" },
  review_confirm_changed_fact: {
    ko: "바뀐 사실을 확인했습니다",
    en: "I have reviewed the changed facts",
  },
  review_prompt_placeholder: {
    ko: "추가 요청 입력",
    en: "Add another instruction",
  },
  review_prompt_submit: { ko: "요청 보내기", en: "Send request" },
  review_prev: { ko: "이전", en: "Previous" },
  review_next: { ko: "다음", en: "Next" },
  review_zoom_fit: { ko: "폭 맞춤", en: "Fit width" },
  review_zoom_label: { ko: "배율 {0}%", en: "Zoom {0}%" },
  review_page_counter: { ko: "{0} / {1}쪽", en: "Page {0} of {1}" },
  review_empty_changes: {
    ko: "검토할 변경 제안이 없습니다.",
    en: "No proposed changes to review.",
  },
  review_approve_dialog_title: {
    ko: "변경 {0}건 적용 승인",
    en: "Approve {0} changes",
  },
  review_plan_hash_label: {
    ko: "변경 제안 검증값",
    en: "Plan verification value",
  },
  review_doc_hash_label: {
    ko: "문서 검증값",
    en: "Document verification value",
  },
  review_date_change_preview: {
    ko: "{0}번 항목의 날짜가 {1}에서 {2}로 바뀝니다.",
    en: "Item {0} date changes from {1} to {2}.",
  },
  review_mobile_sheet_tab: { ko: "문서", en: "Document" },
  review_mobile_list_tab: { ko: "변경 {0}건", en: "{0} changes" },
  review_applied_ok: {
    ko: "변경 내용을 적용했습니다.",
    en: "Changes applied.",
  },
  review_placeholder_ready: {
    ko: "문서 검토 화면을 준비했습니다. 문서를 선택하면 변경 제안을 볼 수 있습니다.",
    en: "Review view is ready. Select a document to inspect proposed changes.",
  },

  // Field label fallback
  field_blank_fallback: { ko: "빈칸 {0}", en: "Blank {0}" },

  // Command palette & actions (§6)
  palette_placeholder: { ko: "명령 입력...", en: "Type a command..." },
  palette_empty: {
    ko: "일치하는 명령이 없습니다.",
    en: "No matching commands.",
  },
  cmd_approve: { ko: "변경 승인", en: "Approve changes" },
  cmd_return: { ko: "변경 돌려보내기", en: "Return changes" },
  cmd_export: { ko: "파일 내보내기", en: "Export file" },
  cmd_open_doc: { ko: "문서 열기", en: "Open document" },
  cmd_open_builtin: { ko: "예시 양식 열기", en: "Open example form" },
  cmd_go_review: { ko: "검토로 이동", en: "Go to review" },
  cmd_go_fill: { ko: "채우기로 이동", en: "Go to fill" },
  cmd_go_history: { ko: "기록으로 이동", en: "Go to history" },
  cmd_jump_changed_fact: {
    ko: "다음 바뀐 사실로 이동",
    en: "Jump to next changed fact",
  },
  cmd_jump_empty_blank: {
    ko: "첫 빈칸으로 이동",
    en: "Go to first empty blank",
  },
  cmd_propose_delete_guides: {
    ko: "안내문 삭제 제안",
    en: "Propose removing form instructions",
  },
  cmd_toggle_print_view: {
    ko: "인쇄 화면 보기",
    en: "Show print view",
  },
  cmd_propose_undo_latest: {
    ko: "최신 수정본 되돌리기 제안",
    en: "Propose undo of latest revision",
  },
  cmd_switch_language: { ko: "언어 바꾸기", en: "Switch language" },
  cmd_change_theme: { ko: "화면 테마 바꾸기", en: "Change theme" },
  cmd_open_settings: { ko: "설정 열기", en: "Open settings" },
  cmd_open_by_path_details: {
    ko: "경로로 문서 열기 (자세히)",
    en: "Open document by path (details)",
  },
  cmd_operator_agent_details: {
    ko: "에이전트 연결 및 작업 기록 (자세히)",
    en: "Agent connection and activity log (details)",
  },

  // Splash, error boundary, dialogs, operator modal, details
  splash_loading: {
    ko: "작업 공간을 준비하고 있습니다.",
    en: "Preparing workspace.",
  },
  splash_connecting: {
    ko: "문서 도구를 불러오고 있습니다.",
    en: "Loading document tools.",
  },
  fatal_title: {
    ko: "작업 공간을 열 수 없습니다",
    en: "Could not open workspace",
  },
  error_boundary_title: {
    ko: "화면을 표시할 수 없습니다",
    en: "Could not display view",
  },
  error_boundary_body: {
    ko: "예기치 않은 오류가 발생했습니다. 다시 시도하거나 자세히에서 원인을 확인할 수 있습니다.",
    en: "An unexpected error occurred. Try reloading or open Details for the cause.",
  },
  error_boundary_retry: { ko: "다시 불러오기", en: "Reload" },
  browser_open_title: {
    ko: "경로로 문서 열기",
    en: "Open document by path",
  },
  browser_open_path_label: { ko: "파일 경로", en: "File path" },
  browser_open_path_placeholder: {
    ko: "열 문서 파일의 전체 경로 입력",
    en: "Enter the full path to a document",
  },
  browser_open_submit: { ko: "열기", en: "Open" },
  browser_open_loading: { ko: "불러오는 중입니다...", en: "Loading..." },
  browser_open_empty_corpus: {
    ko: "열 수 있는 예시 양식이 없습니다.",
    en: "No example forms available.",
  },
  operator_modal_title: {
    ko: "에이전트 연결 및 작업 기록",
    en: "Agent connection and activity log",
  },
  operator_tab_agent: { ko: "에이전트 연결", en: "Agent connection" },
  operator_tab_events: { ko: "작업 기록", en: "Activity log" },
  operator_close: { ko: "닫기", en: "Close" },
  operator_no_session: {
    ko: "작업 기록을 보려면 먼저 문서를 열어야 합니다.",
    en: "Open a document first to view its activity log.",
  },
  detail_label: { ko: "자세히", en: "Details" },
  detail_internal_state: { ko: "내부 상태", en: "Internal state" },
  detail_internal_code: { ko: "오류 코드", en: "Error code" },
  detail_pid_process: {
    ko: "실행 프로세스 번호 · 하위 프로세스 종료 상태",
    en: "Runtime process ID · child process status",
  },
  detail_receipt_verify: { ko: "검증 기록 확인", en: "Verification record check" },
  detail_file_hash: { ko: "파일 검증값", en: "File verification value" },
  detail_raw_log: { ko: "원본 기록 보기", en: "View raw log" },
  time_just_now: { ko: "방금 전", en: "Just now" },
  time_today: { ko: "오늘 {0}", en: "Today {0}" },
  time_yesterday: { ko: "어제 {0}", en: "Yesterday {0}" },
  copy_done: { ko: "복사했습니다.", en: "Copied." },
  close: { ko: "닫기", en: "Close" },
  fallback_unknown_action: { ko: "편집 작업", en: "Edit action" },
  fallback_unknown_error: MSG_INTERNAL_ERROR,
  open_samples_show: { ko: "목록 펼치기", en: "Show forms" },
  open_samples_hide: { ko: "목록 접기", en: "Hide forms" },
  open_path_disclosure_hint: {
    ko: "직접 파일 경로를 입력해 문서를 열어야 할 때 사용합니다.",
    en: "Use this if you need to open a document directly by file path.",
  },
  review_suggest_body_style: {
    ko: "권장 본문 서식 적용",
    en: "Use suggested body style",
  },
  review_save_edit: { ko: "적용", en: "Save" },
  review_repropose: { ko: "다시 제안하기", en: "Re-propose" },
  review_check_status: { ko: "적용 여부 확인", en: "Check revision status" },
  review_applying: { ko: "적용 중...", en: "Applying..." },
  review_guard_checking: {
    ko: "사실 변경 여부를 점검하고 있습니다.",
    en: "Checking protected facts...",
  },
  pipeline_checking_gates: { ko: "조회 중...", en: "Checking..." },
  pipeline_load_gates: { ko: "게이트 조회", en: "Load gates" },
  review_zoom_out: { ko: "축소", en: "Zoom out" },
  review_zoom_in: { ko: "확대", en: "Zoom in" },
  delete_guides_noninvertible: {
    ko: "안내문을 지울 때 사라진 문단 서식을 되살릴 수 없어 자동으로 되돌릴 수 없습니다.",
    en: "Removing form instructions cannot be undone automatically because removed paragraph formatting cannot be restored.",
  },
  op_clear_symbol: { ko: "기호 지움", en: "Remove symbol" },
  guard_added_numbers_more: { ko: "외 {0}개", en: "and {0} more" },
  topbar_more_menu: { ko: "메뉴", en: "Menu" },
  export_no_revision_toast: {
    ko: "아직 내보낼 수정본이 없습니다. 변경 제안을 승인해 적용한 뒤 내보낼 수 있습니다.",
    en: "No revision to export yet. Approve and apply changes first.",
  },
  field_body_fallback: { ko: "본문", en: "Body" },
} as const satisfies Record<string, VocabEntry>;

export type VocabularyKey = keyof typeof VOCABULARY;

function resolveNamedVar(
  vars: Record<string, string | number>,
  token: string,
): string | number | undefined {
  if (Object.prototype.hasOwnProperty.call(vars, token)) {
    return vars[token];
  }
  const index = Number(token);
  if (Number.isInteger(index) && index >= 0) {
    const values = Object.values(vars);
    if (index < values.length) return values[index];
  }
  return undefined;
}

export function formatTemplate(
  template: string,
  vars?: Record<string, string | number> | ReadonlyArray<string | number>,
): string {
  if (!vars) return template;
  if (Array.isArray(vars)) {
    return template.replace(/\{(\d+)\}/g, (full, idx) => {
      const value = vars[Number(idx)];
      return value === undefined ? full : String(value);
    });
  }
  return template.replace(/\{([^}]+)\}/g, (full, name: string) => {
    const value = resolveNamedVar(vars as Record<string, string | number>, name);
    return value === undefined ? full : String(value);
  });
}

export function t(
  key: VocabularyKey,
  lang: UiLanguage,
  vars?: Record<string, string | number> | ReadonlyArray<string | number>,
): string {
  const entry = VOCABULARY[key];
  return formatTemplate(entry[lang], vars);
}

export function opKindLabel(
  kind: string,
  lang: UiLanguage,
  mode?: string | null,
): string {
  if (mode) {
    const modedKey = `${kind}:${mode}` as keyof typeof OP_KIND_MODE_VOCAB;
    if (modedKey in OP_KIND_MODE_VOCAB) {
      return OP_KIND_MODE_VOCAB[modedKey][lang];
    }
  }
  if (kind in OP_KIND_VOCAB) {
    return OP_KIND_VOCAB[kind as keyof typeof OP_KIND_VOCAB][lang];
  }
  return VOCABULARY.fallback_unknown_action[lang];
}

export function errorCodeMessage(code: string, lang: UiLanguage): string {
  if (code in ERROR_CODE_VOCAB) {
    return ERROR_CODE_VOCAB[code as keyof typeof ERROR_CODE_VOCAB][lang];
  }
  return VOCABULARY.fallback_unknown_error[lang];
}

export function ruleStateLabel(state: string, lang: UiLanguage): string {
  if (state in RULE_STATE_VOCAB) {
    return RULE_STATE_VOCAB[state as keyof typeof RULE_STATE_VOCAB][lang];
  }
  return RULE_STATE_VOCAB.skipped[lang];
}

export function checkStateLabel(state: string, lang: UiLanguage): string {
  if (state in CHECK_STATE_VOCAB) {
    return CHECK_STATE_VOCAB[state as keyof typeof CHECK_STATE_VOCAB][lang];
  }
  return CHECK_STATE_VOCAB.not_run[lang];
}

export function approvalStateLabel(state: string, lang: UiLanguage): string {
  if (state in APPROVAL_STATE_VOCAB) {
    return APPROVAL_STATE_VOCAB[state as keyof typeof APPROVAL_STATE_VOCAB][lang];
  }
  return APPROVAL_STATE_VOCAB.pending[lang];
}

export function planStateLabel(state: string, lang: UiLanguage): string {
  if (state in PLAN_STATE_VOCAB) {
    return PLAN_STATE_VOCAB[state as keyof typeof PLAN_STATE_VOCAB][lang];
  }
  return PLAN_STATE_VOCAB.proposed[lang];
}

export function renderGradeLabel(grade: string, lang: UiLanguage): string {
  if (grade in RENDER_GRADE_VOCAB) {
    return RENDER_GRADE_VOCAB[grade as keyof typeof RENDER_GRADE_VOCAB][lang];
  }
  return RENDER_GRADE_VOCAB["own-uncertified"][lang];
}

export function cellClassLabel(cellClass: string, lang: UiLanguage): string {
  if (cellClass in CELL_CLASS_VOCAB) {
    return CELL_CLASS_VOCAB[cellClass as keyof typeof CELL_CLASS_VOCAB][lang];
  }
  return CELL_CLASS_VOCAB.static[lang];
}

export function guardCategoryLabel(category: string, lang: UiLanguage): string {
  if (category in GUARD_CATEGORY_VOCAB) {
    return GUARD_CATEGORY_VOCAB[category as keyof typeof GUARD_CATEGORY_VOCAB][lang];
  }
  return VOCABULARY.guard_pill_changed[lang];
}
