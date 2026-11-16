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

  // Fill screen (§2.3, Rulings H & J)
  fill_title: { ko: "양식 채우기", en: "Fill form" },
  fill_empty_fields: {
    ko: "입력할 빈칸이 없습니다.",
    en: "No blank fields found in this document.",
  },
  fill_select_prompt: {
    ko: "왼쪽 문서에서 빈칸을 클릭하거나 아래에서 항목을 고르면 바로 입력할 수 있습니다.",
    en: "Click any dashed blank on the page or pick a field below to fill it in.",
  },
  fill_field_placeholder: { ko: "내용 입력", en: "Enter text" },
  fill_multiline_enable: { ko: "여러 줄 입력", en: "Multi-line input" },
  fill_multiline_disable: { ko: "한 줄 입력", en: "Single-line input" },
  fill_multiline_hint: {
    ko: "여러 줄로 입력할 수 있습니다. 입력을 마치면 ‘입력 저장’을 선택합니다.",
    en: "You can enter several lines. Select Save entry or press Ctrl/Cmd+Enter when finished.",
  },
  fill_singleline_hint: {
    ko: "엔터 키를 누르거나 ‘입력 저장’을 선택하면 저장합니다. 여러 줄로 입력하려면 ‘여러 줄 입력’을 선택합니다.",
    en: "Press Enter or select Save entry to save. Select Multi-line input to enter several lines.",
  },
  fill_escape_hint: {
    ko: "문서 안 빈칸에서 취소 키를 누르면 빈칸 선택을 마칩니다.",
    en: "In the document, press Esc to leave blank selection.",
  },
  fill_static_notice: {
    ko: "이 칸은 입력용 빈칸이 아닙니다.",
    en: "This cell is not a fillable blank.",
  },
  fill_static_replace: { ko: "기존 문구 바꾸기", en: "Replace existing text" },
  fill_static_current_label: {
    ko: "현재 들어 있는 문구",
    en: "Current text in cell",
  },
  fill_filled_list_header: {
    ko: "변경 제안",
    en: "Proposed changes",
  },
  fill_filled_list_empty: {
    ko: "아직 추가한 변경 제안이 없습니다",
    en: "No proposed changes yet.",
  },
  fill_previous_form_text: {
    ko: "기존 양식 문구: {0}",
    en: "Previous form text: {0}",
  },
  fill_previous_blank: { ko: "(비어 있음)", en: "(empty)" },
  fill_to_review: {
    ko: "검토로 이동",
    en: "Go to review",
  },
  fill_reproposing: {
    ko: "검토 화면을 준비하고 있습니다",
    en: "Preparing review...",
  },
  fill_delete_guides_btn: {
    ko: "안내문 삭제 제안",
    en: "Propose removing form instructions",
  },
  fill_delete_guides_done: {
    ko: "안내문 지움 {0}건을 변경 제안에 추가했습니다",
    en: "Queued {0} guide deletions.",
  },
  fill_delete_guides_queued: {
    ko: "안내문 지움 {0}건을 제안에 포함했습니다",
    en: "Guide deletion queued ({0})",
  },
  fill_undo_removed: {
    ko: "‘{0}’ 항목을 변경 제안에서 뺐습니다",
    en: "Removed entry for '{0}'.",
  },
  fill_undo_restore: { ko: "방금 뺀 항목 되살리기", en: "Undo remove" },
  fill_undo_empty: {
    ko: "‘{0}’의 입력을 지워 변경 제안에서 뺐습니다",
    en: "Removed the proposed entry for '{0}' after clearing its input.",
  },
  fill_ambiguous_warning: {
    ko: "이름이 ‘{0}’인 빈칸이 {1}개 있습니다. 입력할 칸의 위치를 확인해야 합니다.",
    en: "There are {1} blanks named '{0}'. Confirm the selected slot below.",
  },
  fill_ambiguous_slot_option: {
    ko: "{0}번째 빈칸 · {1}",
    en: "Blank #{0} · {1}",
  },
  fill_clear_value: { ko: "입력 지우기", en: "Clear entry" },
  fill_save_entry: {
    ko: "입력 저장",
    en: "Save entry",
  },
  fill_edit_entry: { ko: "고치기", en: "Edit" },
  fill_guide_caption: {
    ko: "작성 안내문: {0}",
    en: "Form instructions: {0}",
  },

  // Revision export (Ruling K & §2.4)
  action_export_revision: { ko: "수정본 {0} 내보내기", en: "Export revision {0}" },
  export_done_toast: {
    ko: "수정본 파일을 저장했습니다",
    en: "Exported revision file.",
  },
  apply_done_toast: {
    ko: "수정본 {0}을 만들었습니다",
    en: "Created revision {0}.",
  },
  detail_cell_address: {
    ko: "표 칸 위치",
    en: "Cell location",
  },
  detail_cell_class: {
    ko: "표 칸 분류",
    en: "Cell classification",
  },
  detail_suggested_char_style: {
    ko: "권장 글자 서식",
    en: "Suggested character style",
  },
  fill_row_label: {
    ko: "{0}행",
    en: "Row {0}",
  },
  detail_run_id: {
    ko: "실행 식별자",
    en: "Run ID",
  },
  detail_plan_id: {
    ko: "변경 제안 식별자",
    en: "Change proposal ID",
  },
  detail_approver_record: {
    ko: "승인 주체 기록",
    en: "Recorded approval actor",
  },
  detail_base_run_id: {
    ko: "기준 수정본 실행 식별자",
    en: "Base revision run ID",
  },
  detail_reversed_run_id: {
    ko: "되돌리기 대상 실행 식별자",
    en: "Run ID being reversed",
  },
  detail_regions_equal: {
    ko: "영역 일치 여부",
    en: "Regions match",
  },
  detail_regions_compared: {
    ko: "비교한 영역 수",
    en: "Regions compared",
  },
  detail_normalizer: {
    ko: "비교 전 정리 방식",
    en: "Comparison normalization method",
  },

  // History screen (§2.4, Ruling K)
  history_title: { ko: "수정 기록", en: "Revision history" },
  history_empty: {
    ko: "아직 만든 수정본이 없습니다",
    en: "No revisions created yet.",
  },
  history_revision_label: { ko: "수정본 {0}", en: "Revision {0}" },
  history_revision_current: { ko: "현재 수정본", en: "Current" },
  history_changes_count: { ko: "변경 {0}건", en: "{0} changes" },
  history_approved_at_label: { ko: "승인 시각", en: "Approved at" },
  history_applied_at_label: { ko: "적용 시각", en: "Applied at" },
  history_unknown_time: { ko: "기록 없음", en: "Not recorded" },
  history_propose_undo: { ko: "되돌리기 제안", en: "Propose undo" },
  history_proposing_undo: {
    ko: "되돌리기 제안을 만들고 있습니다",
    en: "Preparing undo proposal...",
  },
  history_undo_noninvertible: {
    ko: "안내문 지움 {0}건이 포함되어 있어 자동으로 되돌리는 제안을 만들 수 없습니다.",
    en: "Includes {0} form instruction removals; an automatic undo proposal cannot be created.",
  },
  history_export_prev_revision: {
    ko: "이전 수정본 {0} 내보내기",
    en: "Export previous revision {0}",
  },
  history_export_original: {
    ko: "원본 문서 내보내기",
    en: "Export original document",
  },
  history_compare_title: {
    ko: "문서 비교",
    en: "Compare documents",
  },
  history_compare_base: {
    ko: "비교 기준",
    en: "Comparison base",
  },
  history_compare_target: {
    ko: "비교 대상",
    en: "Comparison target",
  },
  history_compare_original: { ko: "원본 문서", en: "Original document" },
  history_compare_changed_count: {
    ko: "바뀐 문단 {0}개",
    en: "{0} paragraphs changed",
  },
  history_compare_same: {
    ko: "비교한 문서의 내용이 같습니다",
    en: "The compared documents have the same content.",
  },
  history_compare_loading: {
    ko: "선택한 문서를 비교하고 있습니다",
    en: "Comparing selected documents...",
  },
  history_compare_need_two: {
    ko: "비교 기준과 비교 대상을 선택해야 합니다.",
    en: "Select a comparison base and target.",
  },
  history_approval_method_auto: {
    ko: "승인 방식: 자동 승인 규칙",
    en: "Approval method: Automatic approval rule",
  },
  history_receipt_unavailable: {
    ko: "승인 기록을 아직 불러오지 못했습니다.",
    en: "Approval record is not available yet.",
  },
  history_snapshot_diff_note: {
    ko: "비교 기준과 비교 대상의 문단 내용을 비교한 결과입니다.",
    en: "Results of comparing paragraph text between the comparison base and target.",
  },

  // Settings screen (§2.5, Ruling M) & Operator modal tab
  settings_title: { ko: "설정", en: "Settings" },
  settings_section_language: { ko: "언어", en: "Language" },
  settings_section_theme: { ko: "화면 테마", en: "Appearance" },
  settings_section_folder: { ko: "작업 폴더", en: "Workspace folder" },
  settings_folder_change: { ko: "폴더 바꾸기", en: "Change folder" },
  settings_folder_changing: {
    ko: "작업 폴더를 바꾸고 있습니다",
    en: "Switching workspace folder...",
  },
  settings_folder_changed: {
    ko: "작업 폴더를 바꿨습니다",
    en: "Workspace folder updated.",
  },
  settings_folder_prompt: {
    ko: "새 작업 폴더 경로 입력",
    en: "Enter new workspace folder path",
  },
  settings_folder_apply: {
    ko: "폴더 바꾸기",
    en: "Change folder",
  },
  settings_folder_reset_default: { ko: "기본 폴더 사용", en: "Use default folder" },
  settings_folder_current_label: { ko: "현재 작업 폴더", en: "Current folder" },
  operator_tab_credentials: {
    ko: "에이전트 인증 및 서비스 제공자",
    en: "Credentials & provider",
  },
  cmd_export_revision: { ko: "현재 수정본 내보내기", en: "Export current revision" },
  cmd_open_workspace_settings: {
    ko: "언어·화면 테마·작업 폴더 설정",
    en: "Language, theme & workspace settings",
  },
  err_invalid_json: {
    ko: "서버 응답 형식이 올바르지 않습니다.",
    en: "Server response is not valid JSON.",
  },
  err_rpc_failed: {
    ko: "요청을 처리하지 못했습니다.",
    en: "Could not process the request.",
  },
  seat_editor_aria_label: {
    ko: "이 자리에 넣을 값",
    en: "Value for this blank",
  },
  approval_kind_count: { ko: "{0}건", en: "{0}" },
  cmd_kw_open_doc: { ko: "열기 파일 선택", en: "open file" },
  cmd_kw_open_builtin: { ko: "예시 양식 열기 기본", en: "open form example" },
  cmd_kw_go_review: { ko: "검토 화면 이동", en: "review" },
  cmd_kw_go_fill: { ko: "채우기 빈칸 양식 입력", en: "fill" },
  cmd_kw_go_history: { ko: "기록 수정본 이력 비교", en: "history revisions" },
  cmd_kw_toggle_print_view: { ko: "인쇄 화면 문서 보기", en: "print view" },
  cmd_kw_approve: { ko: "승인 적용", en: "approve" },
  cmd_kw_return: {
    ko: "돌려보내기",
    en: "return",
  },
  cmd_kw_export: { ko: "내보내기 저장 수정본", en: "export revision" },
  cmd_kw_switch_language: { ko: "언어 한국어 영어", en: "language" },
  cmd_kw_change_theme: { ko: "화면 테마 밝게 어둡게", en: "theme" },
  cmd_kw_open_settings: {
    ko: "설정 언어 화면 테마 작업 폴더",
    en: "settings language theme workspace folder",
  },
  cmd_kw_open_by_path: { ko: "경로 자세히 열기", en: "path details" },
  cmd_kw_operator_agent: {
    ko: "에이전트 연결 작업 기록 인증 공급자 자세히",
    en: "agent log credentials provider details",
  },
  corpus_title_gianmun_1: {
    ko: "기안문 (별지 제1호서식)",
    en: "Drafting Form (Annex 1)",
  },
  corpus_title_gianmun_2: {
    ko: "기안문 (별지 제2호서식)",
    en: "Drafting Form (Annex 2)",
  },
  corpus_title_jumin: {
    ko: "주민등록표 등·초본 교부 신청서",
    en: "Resident Registration Copy Request",
  },
  corpus_title_jeongbo_gonggae: {
    ko: "정보공개 청구서",
    en: "Information Disclosure Request",
  },
  corpus_title_saeopja: {
    ko: "사업자등록 신청서 (개인사업자용)",
    en: "Business Registration Application",
  },
  corpus_title_gajokdolbom: {
    ko: "가족돌봄 휴직·휴가 신청서",
    en: "Family Care Leave Request",
  },
  corpus_title_moel_2025: {
    ko: "표준근로계약서 (2025)",
    en: "Standard Employment Contract (2025)",
  },
  corpus_title_moel_2013: {
    ko: "표준근로계약서 (2013)",
    en: "Standard Employment Contract (2013)",
  },
  corpus_title_nrf_report: {
    ko: "연구결과보고서 양식",
    en: "Research Result Report Form",
  },
  corpus_title_kstartup: {
    ko: "예비창업가 지원 신청서 및 사업계획서",
    en: "Startup Support Application & Plan",
  },
  corpus_title_pps_collab: {
    ko: "협업 승인 신청서",
    en: "Collaboration Approval Request",
  },
  corpus_title_pps_consent: {
    ko: "정보공개 동의서 (개인정보 수집·이용)",
    en: "Information Disclosure Consent Form",
  },
  corpus_title_render_check: {
    ko: "문서 배치 확인용 예시",
    en: "Layout Check Sample",
  },
  corpus_title_table_break: {
    ko: "표 페이지 나눔 확인용 예시",
    en: "Table Break Check Sample",
  },
  corpus_source_mois: { ko: "행정안전부 예시", en: "MOIS example" },
  corpus_source_nts: { ko: "국세청 예시", en: "NTS example" },
  corpus_source_nsm: { ko: "국립중앙과학관 예시", en: "NSM example" },
  corpus_source_moel: { ko: "고용노동부 예시", en: "MOEL example" },
  corpus_source_nrf: { ko: "한국연구재단 예시", en: "NRF example" },
  corpus_source_kised: { ko: "창업진흥원 예시", en: "KISED example" },
  corpus_source_pps: { ko: "조달청 예시", en: "PPS example" },
  corpus_source_internal: { ko: "내부 점검 예시", en: "Internal check sample" },
  proj_unimpl_normalize_clones: {
    ko: "중복 글자 서식 정리는 문서의 서식 정보를 다시 쓰는 작업이어서 검토 대기열에 정확히 표시할 수 없습니다.",
    en: "Style clone normalization rewrites headers and cannot be accurately shown in the review queue.",
  },
  proj_unimpl_goto_text: {
    ko: "위치 이동은 검토 대기열에서 지원하지 않는 작업입니다.",
    en: "Jumping to text is not supported in the review queue.",
  },
  proj_refuse_op_unrepresentable: {
    ko: "변경 작업을 검토 대기열에 정확히 표시할 수 없습니다.",
    en: "This change operation cannot be accurately shown in the review queue.",
  },
  proj_refuse_partial_unrepresentable: {
    ko: "일부 작업의 내용을 검토 대기열에 정확히 표시할 수 없습니다.",
    en: "Some operations cannot be accurately represented in the review queue.",
  },
  proj_refuse_kind_unsupported: {
    ko: "이 변경 작업은 검토 대기열에서 지원하지 않습니다.",
    en: "This change operation is not supported in the review queue.",
  },
  proj_refuse_invalid_params: {
    ko: "입력한 변경 내용을 확인해야 합니다.",
    en: "Check the change details.",
  },
  proj_refuse_invalid_fields: {
    ko: "입력한 변경 내용을 검토 대기열에 표시할 수 없습니다.",
    en: "The change details cannot be shown in the review queue.",
  },
  proj_guide_color_prefix: { ko: "색상 {0}", en: "color {0}" },
  proj_guide_charpr_prefix: { ko: "서식 번호 {0}", en: "charPr {0}" },
  proj_guide_target_with_parts: { ko: "안내문 ({0})", en: "Guides ({0})" },
  proj_guide_target_default: { ko: "대상 안내문", en: "Target guide text" },
  proj_guides_deleted: { ko: "(안내문 삭제됨)", en: "(Guide text removed)" },
  proj_addr_table_cell: { ko: "표 {0} {1}행 {2}열", en: "Table {0} R{1}C{2}" },
  proj_addr_run_suffix: {
    ko: "· 글자 구간 {0}",
    en: "· Run {0}",
  },
  proj_addr_para_run: {
    ko: "문단 {0} · 글자 구간 {1}",
    en: "Paragraph {0} · Run {1}",
  },
  proj_addr_delete_guides: { ko: "안내문 삭제", en: "Delete guides" },
  proj_inverse_delete_guides: {
    ko: "안내문 지움은 지운 안내 문단과 서식을 되살릴 수 없어 되돌릴 수 없습니다.",
    en: "Guide text removal cannot be undone because deleted guide paragraphs and formatting cannot be restored.",
  },
  proj_inverse_unsupported_kind: {
    ko: "이 변경 작업은 되돌릴 수 없습니다.",
    en: "This change operation cannot be undone.",
  },
  action_open_hwpx_title: { ko: "한글 문서 열기", en: "Open Hangul document" },
  action_open_hwpx_filter: { ko: "한글 문서", en: "Hangul documents" },
  toast_hwpx_only: {
    ko: "지원하지 않는 파일 형식입니다. 한글 문서만 열 수 있습니다.",
    en: "Only Hangul documents (.hwpx, .hwp) can be opened.",
  },
  toast_opened_first_of_many: {
    ko: "{0}개 중 첫 문서만 열었습니다",
    en: "Opened only the first of {0} documents.",
  },
  toast_not_editable_cell: {
    ko: "이 칸은 입력용 빈칸이 아닙니다.",
    en: "This cell is not a fillable blank.",
  },
  overlay_not_editable_cell: {
    ko: "{0} — 이 칸은 입력용 빈칸이 아닙니다.",
    en: "{0} — Not a fillable blank",
  },
  caret_refusal_no_address: {
    ko: "이 줄의 문단 위치를 확인할 수 없습니다.",
    en: "This line has no paragraph address.",
  },
  caret_refusal_multi_run: {
    ko: "선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다.",
    en: "This selection cannot be edited at once. Edit smaller sections.",
  },
  caret_refusal_run_text_differs: {
    ko: "이 줄에서 수정할 글자 위치를 정확히 찾을 수 없습니다.",
    en: "Cannot resolve a single cursor offset within this text segment.",
  },
  caret_refusal_no_inventory: {
    ko: "이 문단의 글자 구간 정보를 확인할 수 없습니다.",
    en: "The runtime did not return text segments for this paragraph.",
  },
  caret_refusal_revision_mismatch: {
    ko: "표시 중인 문서와 읽은 문서가 다릅니다. 이 줄에는 커서를 놓을 수 없습니다.",
    en: "Displayed document differs from the loaded document; cannot place cursor.",
  },
  caret_refusal_cross_run: {
    ko: "선택한 범위를 한 번에 고칠 수 없습니다. 문구를 나눠서 수정해야 합니다.",
    en: "This selection cannot be edited at once. Edit smaller sections.",
  },
  caret_refusal_utf16_split: {
    ko: "선택한 위치가 한 글자의 중간이어서 수정할 수 없습니다. 글자 앞이나 뒤를 선택해야 합니다.",
    en: "This position is inside a character and cannot be edited. Select a position before or after the character.",
  },
  overlay_caret_snapped: {
    ko: "글자별 위치를 확인할 수 없어 줄 앞에 커서를 놓았습니다",
    en: "Snapped cursor to start of line",
  },
  overlay_caret_offset: {
    ko: "{0}번째 글자 앞",
    en: "Before character {0}",
  },
  toast_removed_from_queue: {
    ko: "대기열에서 뺐습니다. 이 동작으로 문서 내용은 바뀌지 않습니다.",
    en: "Removed from queue. This action does not change the document content.",
  },
  err_undo_not_invertible: {
    ko: "이 수정본에는 되돌릴 수 없는 작업이 있습니다: {0}. 안내문 지움은 지운 안내문을 원래 서식과 위치로 되살릴 수 없으며, 빈칸 채움·칸 문구 바꿈·본문 문구 바꿈 작업만 되돌릴 수 있습니다.",
    en: "This revision contains operations that cannot be undone: {0}. Removing guide text cannot be restored with original formatting and position; only blank fills, cell text replacements, and body text replacements can be undone.",
  },
  err_undo_no_addresses: {
    ko: "이 변경 제안의 작업들이 주소를 갖고 있지 않아 이전 값을 읽을 수 없습니다.",
    en: "Operations in this change proposal carry no addresses, so previous values cannot be read.",
  },
  err_undo_previous_unreadable: {
    ko: "되돌릴 이전 값을 런타임이 돌려주지 못한 자리가 있습니다. 빈 값으로 짐작해서 덮어쓰지 않습니다.",
    en: "The runtime did not return a previous value for some targets. Refusing to guess an empty value.",
  },
  toast_undo_proposed: {
    ko: "되돌리기를 제안했습니다. 승인해야 수정본이 하나 더 생깁니다.",
    en: "Proposed undo. Approving creates a new revision.",
  },
  toast_proposal_returned: {
    ko: "변경 제안을 돌려보냈습니다. 문서는 그대로입니다.",
    en: "Returned the change proposal. The document is unchanged.",
  },
  reapproval_prompt: {
    ko: "문서 또는 수정본이 바뀌어 기존 승인이 무효화되었습니다. 변경 제안을 다시 확인하고 승인해야 합니다.",
    en: "The document or revision changed and invalidated the previous approval. Review the updated change proposal and approve again.",
  },
  toast_apply_cancelling: {
    ko: "적용을 멈추라고 알렸습니다. 진행 중인 한 단계는 끝납니다.",
    en: "Requested cancellation. The current step will finish first.",
  },
  err_pipeline_workspace_missing: {
    ko: "작업 폴더 경로를 입력해야 합니다.",
    en: "Please enter a workspace path.",
  },
  gate_decision_approved: {
    ko: "승인했습니다",
    en: "Approved",
  },
  gate_decision_rejected: {
    ko: "돌려보냈습니다",
    en: "Returned",
  },
  toast_gate_resolved: {
    ko: "{1}",
    en: "{1}",
  },
  err_recovery_receipt_mismatch: {
    ko: "복구 대상 수정본의 검증 기록이 중단된 적용 요청과 일치하지 않습니다.",
    en: "The recovery revision's verification record does not match the interrupted apply request.",
  },
  action_export_revision_dialog_title: { ko: "수정본 내보내기", en: "Export revision" },
  err_export_file_mismatch: {
    ko: "내보낸 파일이 수정본과 일치하지 않습니다. 이 파일을 제출하지 마십시오.",
    en: "The exported file does not match the revision. Do not submit this file.",
  },
  err_export_download_failed: {
    ko: "수정본 내려받기에 실패했습니다 (상태 {0}).",
    en: "Failed to download revision (HTTP {0}).",
  },
  err_export_download_mismatch: {
    ko: "내려받은 파일이 수정본과 일치하지 않습니다. 이 파일을 제출하지 마십시오.",
    en: "The downloaded file does not match the revision. Do not submit this file.",
  },
  addr_table_cell: {
    ko: "표 {0} {1}행 {2}열",
    en: "Table {0} R{1}C{2}",
  },
  addr_paragraph: { ko: "문단 {0}", en: "Paragraph {0}" },
  addr_anchor: { ko: "위치 “{0}”", en: "Anchor “{0}”" },
  addr_none: { ko: "주소 없음", en: "No address" },
  deriv_cell_borders: {
    ko: "칸 테두리를 기준으로 위치를 찾았습니다",
    en: "Matched by cell borders",
  },
  deriv_matched_text: {
    ko: "칸의 문구를 기준으로 위치를 찾았습니다",
    en: "Matched by cell text",
  },
  deriv_interpolated: {
    ko: "항목 이름을 기준으로 위치를 추정했습니다",
    en: "Inferred from label",
  },
  overlay_ambiguous_pick: {
    ko: "후보 {0}개 — 직접 선택",
    en: "{0} matches — choose one",
  },
  overlay_unmapped_sidecar: {
    ko: "{0}번째 줄 — 양식에서 이 줄의 위치를 확인할 수 없습니다. 미리보기에 표시된 위치만으로는 수정할 위치를 정할 수 없습니다.",
    en: "Line {0} — Could not verify this line’s position in the form. Its preview position alone cannot identify where to edit.",
  },
  overlay_unmapped_plain: {
    ko: "{0}번째 줄 — 양식에서 이 줄의 위치를 확인할 수 없습니다.",
    en: "Line {0} — could not match this line to any position in the form.",
  },
  overlay_user_selected: {
    ko: "{0} — 사용자가 선택했습니다",
    en: "{0} — selected by user",
  },
  prepare_note_revision_ready: {
    ko: "수정본 인쇄 화면을 준비했습니다",
    en: "Prepared revision print view",
  },
  prepare_note_original_ready: {
    ko: "원본 인쇄 화면을 준비했습니다",
    en: "Prepared original print view",
  },
  prepare_note_already_ready: {
    ko: "이미 준비되어 있습니다",
    en: "Already prepared",
  },
  err_agent_output_unreadable: {
    ko: "에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다.",
    en: "Could not display the agent’s proposal. Request it again.",
  },
  err_agent_draft_superseded: {
    ko: "제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 이 제안을 대기열에 넣지 않았습니다.",
    en: "The document or review queue changed while this proposal arrived, so it was not queued.",
  },
  finding_where_checker: {
    ko: "점검 항목",
    en: "Check",
  },
  finding_reason_none: { ko: "이유 없음", en: "no reason given" },
  finding_check_not_run: {
    ko: "이 점검은 실행되지 않았습니다. 실행하지 않은 점검은 통과로 세지 않습니다.",
    en: "This check did not run. Checks that did not run are not counted as passes.",
  },
  finding_where_cell: { ko: "표 {0} {1}행 {2}열", en: "Table {0} R{1}C{2}" },
  finding_color_anomaly: {
    ko: "글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다.",
    en: "Text colour differs from body baseline; filling as-is leaves coloured text.",
  },
  finding_script_anomaly: {
    ko: "글자 속성이 본문 기준과 다릅니다. 서식 번호 {0} 대신 {1} 사용을 권장합니다.",
    en: "Character formatting differs from body baseline; charPr {0} -> {1} recommended.",
  },
  finding_where_cell_run: {
    ko: "표 {0} {1}행 {2}열 · 글자 구간 {3}",
    en: "Table {0} R{1}C{2} #{3}",
  },
  finding_where_para_run: {
    ko: "문단 {0} · 글자 구간 {1}",
    en: "Paragraph {0} #{1}",
  },
  finding_color_unknown: { ko: "알 수 없음", en: "unknown" },
  finding_run_color_anomaly: {
    ko: "본문 기준과 다른 글자색을 사용하는 문구가 있습니다. 문구: “{1}”.",
    en: "Some text uses a different colour from the body text. Text: “{1}”.",
  },
  finding_script_anomaly_target: {
    ko: "글자 서식이 본문 기준과 다릅니다. 서식 번호 {1} 대신 {2} 사용을 권장합니다.",
    en: "Character formatting differs from the body text. Use format {2} instead of {1}.",
  },
  finding_where_document: { ko: "문서 전체", en: "Whole document" },
  finding_clean_notice: {
    ko: "현재 점검할 수 있는 범위에서는 문제가 발견되지 않았습니다. 인쇄 확인과 제출 전 점검은 아직 실행할 수 없습니다.",
    en: "No issues found within what this build can inspect. Print verification and submission checks cannot run yet.",
  },
  toast_nothing_to_copy: { ko: "복사할 글이 없습니다", en: "Nothing to copy" },
  toast_copied_label: {
    ko: "{0} 복사를 마쳤습니다",
    en: "Copied {0}",
  },
  boot_checking_capabilities: {
    ko: "지원 기능을 확인하고 있습니다",
    en: "Checking capabilities...",
  },
  boot_finding_open_docs: {
    ko: "열린 문서를 찾고 있습니다",
    en: "Finding open documents...",
  },
  boot_reloading_doc: {
    ko: "문서를 다시 읽고 있습니다",
    en: "Reloading document...",
  },
  boot_restarting_runtime: {
    ko: "작업 공간 연결을 다시 시작하고 있습니다",
    en: "Restarting runtime...",
  },
  err_credential_name_missing: {
    ko: "먼저 자격 증명 이름을 정해야 합니다.",
    en: "Set a credential key name first.",
  },
  toast_credential_stored: {
    ko: "자격 증명을 이 기계의 저장소에 넣었습니다",
    en: "Stored credential in this machine's keyring.",
  },
  err_agent_host_exit: {
    ko: "에이전트 호스트가 종료 코드 {0}로 끝났습니다.",
    en: "Agent host exited with code {0}.",
  },
  err_agent_plan_before_unreadable: {
    ko: "에이전트 제안을 표시할 수 없습니다. 다시 요청해야 합니다.",
    en: "Could not display the agent’s proposal. Request it again.",
  },
  agent_guide_summary_empty: {
    ko: "문서에 있는 삭제 대상 안내문",
    en: "Guide text marked for removal",
  },
  agent_guide_summary_preview: {
    ko: "안내문 {0}건 ({1})",
    en: "{0} guide entries ({1})",
  },
  agent_guide_summary_count: {
    ko: "안내문 {0}건",
    en: "{0} guide entries",
  },
  err_agent_cancelled: { ko: "사람이 중간에 멈췄습니다.", en: "Stopped by operator." },
  toast_open_doc_before_check: {
    ko: "점검하려면 먼저 문서를 열어야 합니다.",
    en: "Open a document before running checks.",
  },
  err_invalid_root_path: {
    ko: "작업 폴더 경로를 입력해야 합니다.",
    en: "Enter a workspace folder path.",
  },
  err_workspace_start_failed: {
    ko: "새 작업 폴더로 작업 공간을 시작하지 못했습니다.",
    en: "Failed to start workspace with the new folder.",
  },
  operator_host_heading: {
    ko: "에이전트 연결",
    en: "Agent connection",
  },
  operator_host_available: {
    ko: "사용할 수 있습니다",
    en: "Available",
  },
  operator_host_unavailable: {
    ko: "사용할 수 없습니다",
    en: "Unavailable",
  },
  operator_host_unknown_reason: { ko: "확인하지 못했습니다.", en: "Could not verify." },
  operator_host_status_btn: { ko: "상태 새로고침", en: "Refresh status" },
  operator_host_boundary_note: {
    ko: "서비스 제공자와 통신하는 것은 이 별도 프로세스뿐이며, 문서 처리 쪽은 네트워크에 연결되지 않습니다.",
    en: "Only this separate process talks to providers; document processing stays offline.",
  },
  operator_session_summary: {
    ko: "현재 문서: {0} · 수정본 {1}건",
    en: "Current document: {0} · {1} revisions",
  },
  operator_no_open_doc: {
    ko: "열린 문서가 없습니다",
    en: "No open document",
  },
  operator_prompt_placeholder: {
    ko: "작업 지시 입력",
    en: "Enter an instruction for the agent",
  },
  operator_prompt_submit: { ko: "실행", en: "Run" },
  operator_prompt_stop: { ko: "멈추기", en: "Stop" },
  operator_composer_blocked: {
    ko: "지금은 실행할 수 없습니다.",
    en: "Cannot run right now.",
  },
  operator_turns_empty: {
    ko: "아직 실행한 작업이 없습니다. 지시를 보내면 이력이 여기에 표시됩니다.",
    en: "No turns yet. Sent instructions will appear here.",
  },
  operator_turn_working: {
    ko: "실행 중입니다",
    en: "Running",
  },
  operator_turn_fault: {
    ko: "서비스 제공자 오류가 발생했습니다",
    en: "Provider fault",
  },
  operator_turn_failed: {
    ko: "실행하지 못했습니다",
    en: "Failed",
  },
  operator_turn_plan_ready: {
    ko: "변경 제안이 도착했습니다",
    en: "Proposal arrived",
  },
  operator_turn_no_plan: {
    ko: "변경 제안이 없습니다",
    en: "No proposal",
  },
  operator_turn_count: { ko: "{0}단계", en: "{0} turns" },
  operator_turn_fault_note: {
    ko: "문서에 대한 판정이 아닙니다. 변경 제안과 승인 상태는 그대로입니다.",
    en: "This is not a document verdict; proposals and approvals are unchanged.",
  },
  operator_turn_plan_adopted: {
    ko: "검토 대기열에 반영되었습니다. 검토 화면에서 직접 승인해야 문서에 적용됩니다.",
    en: "Adopted into the review queue. Approve on the Review screen to apply.",
  },
  operator_turn_plan_not_queued: {
    ko: "제안이 도착하는 동안 문서나 검토 대기열이 바뀌어 대기열에는 넣지 않았습니다.",
    en: "The document or review queue changed in flight, so this proposal was not queued.",
  },
  operator_turn_never_compiled: {
    ko: "현재 연결에서는 요청한 기능을 지원하지 않습니다.",
    en: "The requested capability is not supported in this session.",
  },
  operator_turn_events_summary: { ko: "세부 기록 ({0})", en: "Host events ({0})" },
  operator_events_heading: { ko: "문서 작업 기록", en: "Document activity log" },
  operator_events_count: { ko: "{0}건", en: "{0} events" },
  operator_events_live: { ko: "실시간", en: "Live" },
  operator_events_disconnected: {
    ko: "연결이 끊겼습니다",
    en: "Disconnected",
  },
  operator_events_idle: {
    ko: "대기 중입니다",
    en: "Idle",
  },
  operator_events_sub_error: {
    ko: "작업 기록을 받아오지 못했습니다.",
    en: "Failed to subscribe to events",
  },
  operator_events_empty: {
    ko: "아직 이 문서에 기록된 사건이 없습니다.",
    en: "No events recorded for this document yet.",
  },
  operator_protocol_chatter: { ko: "프로토콜 통신 기록 ({0})", en: "Protocol trace ({0})" },
  operator_protocol_note: {
    ko: "위쪽은 문서 사건 기록이고, 여기는 진단용 내부 통신 내역입니다.",
    en: "Above is the document event log; below is diagnostic shell-runtime traffic.",
  },
  operator_provider_heading: { ko: "서비스 제공자", en: "Provider" },
  operator_provider_mock_label: { ko: "내장 모의 제공자", en: "Built-in mock" },
  operator_provider_mock_blurb: {
    ko: "네트워크도 시계도 없는 결정론 제공자입니다. 같은 문서에는 같은 요청을 냅니다.",
    en: "Deterministic offline provider without network or clock.",
  },
  operator_provider_router_label: { ko: "사용자 지정 라우터", en: "Custom router" },
  operator_provider_router_blurb: {
    ko: "호환 접속 주소와 모델 이름을 직접 지정합니다.",
    en: "OpenAI-compatible endpoint with custom base URL and model.",
  },
  operator_provider_anthropic_label: { ko: "앤스로픽", en: "Anthropic" },
  operator_provider_anthropic_blurb: {
    ko: "공식 메시지 연결입니다. 키를 저장하고 지시를 보낼 때만 호출합니다.",
    en: "Official Messages API; network calls occur only when credentials are set and run.",
  },
  operator_scenario_heading: { ko: "모의 대본", en: "Mock scenario" },
  operator_scenario_propose_one: { ko: "한 칸 채우기 제안", en: "Propose single blank" },
  operator_scenario_propose_invalid: {
    ko: "쓰기 전 확인에서 막히는 제안",
    en: "Propose invalid plan",
  },
  operator_scenario_propose_wait: { ko: "제안 후 승인 대기", en: "Propose and await approval" },
  operator_scenario_escalate: {
    ko: "적용 시도 후 차단 확인",
    en: "Attempt apply (blocked at gate)",
  },
  operator_scenario_note: {
    ko: "인증 키나 네트워크 없이 동작합니다.",
    en: "Uses neither credentials nor network.",
  },
  operator_router_heading: { ko: "라우터 설정", en: "Router configuration" },
  operator_field_base_url: { ko: "접속 주소", en: "Base URL" },
  operator_field_model: { ko: "모델 이름", en: "Model" },
  operator_field_store_key: { ko: "자격 증명 이름", en: "Credential key name" },
  operator_anthropic_heading: { ko: "앤스로픽 설정", en: "Anthropic configuration" },
  operator_anthropic_model_placeholder: {
    ko: "비워 두면 기본값 사용",
    en: "Leave empty for adapter default",
  },
  operator_model_empty_note: {
    ko: "모델 이름을 비워 두면 연결 쪽 기본값을 사용합니다.",
    en: "Leaving model blank uses the adapter's default.",
  },
  operator_save_settings: { ko: "설정 저장", en: "Save settings" },
  operator_settings_dirty: { ko: "저장되지 않은 변경이 있습니다", en: "Unsaved changes" },
  operator_credential_heading: { ko: "자격 증명", en: "Credentials" },
  operator_credential_note: {
    ko: "비밀 값은 이 기계의 자격 증명 저장소에만 들어가며, 설정 파일에는 이름만 저장되고 화면에 다시 표시되지 않습니다.",
    en: "Secrets go straight to the OS credential store; config stores only the key name and secrets are never read back.",
  },
  operator_credential_status_label: { ko: "현재 상태", en: "Status" },
  operator_credential_stored: {
    ko: "저장되어 있습니다 ({0} · {1}바이트)",
    en: "Present ({0} · {1} bytes)",
  },
  operator_credential_absent: {
    ko: "저장된 자격 증명이 없습니다 ({0})",
    en: "Absent ({0})",
  },
  operator_credential_unnamed: { ko: "이름 없음", en: "unnamed" },
  operator_credential_paste_label: { ko: "값 붙여넣기", en: "Paste secret" },
  operator_credential_placeholder: {
    ko: "자격 증명 값 입력",
    en: "Enter credential value",
  },
  operator_credential_store_btn: { ko: "저장소에 넣기", en: "Store credential" },
  operator_credential_forget_btn: { ko: "지우기", en: "Forget" },
  operator_probe_heading: {
    ko: "지원 기능 확인",
    en: "Check supported capabilities",
  },
  operator_probe_btn: {
    ko: "지원 기능 확인",
    en: "Check supported capabilities",
  },
  operator_probe_busy: {
    ko: "확인 중입니다",
    en: "Probing...",
  },
  operator_probe_note: {
    ko: "어댑터가 무엇을 지원하는지만 로컬에서 확인합니다.",
    en: "Asks the adapter locally what it supports; touches neither document nor network.",
  },
  operator_cap_model_prefix: { ko: "모델: {0}", en: "Model: {0}" },
  operator_cap_verdict_label: { ko: "자격 증명 참조", en: "Credential ref" },
  operator_cap_th_capability: { ko: "기능", en: "Capability" },
  operator_cap_th_supported: { ko: "지원", en: "Support" },
  operator_cap_th_reason: { ko: "사유", en: "Reason" },
  operator_cap_th_source: { ko: "출처", en: "Source" },
  operator_cap_text: { ko: "글 생성", en: "Text generation" },
  operator_cap_tools: { ko: "도구 호출", en: "Structured tool use" },
  operator_cap_streaming: { ko: "토막 전송", en: "Streaming" },
  operator_cap_structured: { ko: "구조화 출력", en: "Structured output" },
  operator_cap_models: { ko: "모델 목록", en: "Model discovery" },
  operator_cap_thread: { ko: "대화 이어받기", en: "Resumable thread" },
  operator_cap_vision: { ko: "그림 입력", en: "Vision" },
  operator_state_yes: { ko: "예", en: "Yes" },
  operator_state_no: { ko: "아니오", en: "No" },
  operator_state_unknown: {
    ko: "확인하지 못했습니다",
    en: "Unknown",
  },
  operator_cred_configured: {
    ko: "설정되어 있습니다",
    en: "Configured",
  },
  operator_cred_missing: {
    ko: "자격 증명이 없습니다",
    en: "Missing",
  },
  operator_cred_not_required: {
    ko: "자격 증명이 필요하지 않습니다",
    en: "Not required",
  },
  operator_cred_unsupported: {
    ko: "이 인증 방식은 지원하지 않습니다",
    en: "Unsupported",
  },
  operator_own_none: {
    ko: "인증 키가 필요하지 않습니다",
    en: "No key required",
  },
  operator_own_env: { ko: "환경 변수 이름으로 참조합니다", en: "Referenced via environment variable" },
  operator_own_os: {
    ko: "운영체제 저장소 키로 참조합니다",
    en: "Referenced via OS credential store",
  },
  operator_own_managed: {
    ko: "서비스 제공자가 인증을 관리합니다",
    en: "Provider-managed authentication",
  },
  operator_config_heading: { ko: "이 제공자가 읽을 설정 파일", en: "Provider config file" },
  operator_config_note: {
    ko: "이 설정에는 비밀 값 대신 자격 증명 이름만 저장됩니다.",
    en: "This configuration stores credential names instead of secret values.",
  },
  operator_config_empty: { ko: "아직 저장된 설정 파일이 없습니다.", en: "No config file saved yet." },
  operator_event_opened: { ko: "문서를 열었습니다 — {0}", en: "Opened document — {0}" },
  operator_event_proposed: {
    ko: "변경 작업 {0}건을 제안했습니다 — {1}",
    en: "Proposed {0} operations — {1}",
  },
  operator_event_validated_ok: {
    ko: "쓰기 전 확인을 통과했습니다",
    en: "Pre-write validation passed",
  },
  operator_event_validated_fail: {
    ko: "쓰기 전 확인에서 막혔습니다",
    en: "Pre-write validation blocked",
  },
  operator_event_approval_req: {
    ko: "승인을 요청했습니다 — {0}",
    en: "Approval requested — {0}",
  },
  operator_event_approved: { ko: "{0}이(가) 승인했습니다", en: "Approved by {0}" },
  operator_event_rejected: { ko: "{0}이(가) 돌려보냈습니다", en: "Returned by {0}" },
  operator_event_applied: {
    ko: "변경 제안을 사본에 적용했습니다",
    en: "Applied change proposal to copy",
  },
  operator_event_candidate: {
    ko: "수정본을 남겼습니다 · 검사 {0}",
    en: "Saved revision · checks {0}",
  },
  operator_event_check_pass: { ko: "통과", en: "passed" },
  operator_event_check_fail: { ko: "미통과", en: "not passed" },
  operator_event_pdf: {
    ko: "인쇄 화면용 문서를 준비했습니다",
    en: "Prepared print view document",
  },
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
