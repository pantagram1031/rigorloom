/**
 * WP4 strings: right panel, the 결재란 footer, the approval sheet, the return
 * popover, the stale banner, the thread, the composer and the 점검 pane.
 *
 * WP7 folds this file into the vocabulary. Until then the panel reads it
 * through `panel/i18n.ts`. Korean values carry no Latin letters; key names
 * are drawn by the Keycap component, never written into a value. No particle
 * is attached to a placeholder.
 */

export const WP4_STRINGS = {
  // --- right panel tabs ------------------------------------------------------------
  panel_tab_changes: { ko: "변경", en: "Changes" },
  panel_tab_agent: { ko: "에이전트", en: "Agent" },
  panel_tab_checks: { ko: "점검", en: "Checks" },
  panel_aria: { ko: "오른쪽 창", en: "Right panel" },

  // --- sources and states ----------------------------------------------------------
  source_agent: { ko: "에이전트", en: "Agent" },
  source_user: { ko: "내 입력", en: "My input" },
  source_test: { ko: "시험용", en: "Test" },
  source_revert: { ko: "되돌리기", en: "Undo" },
  decision_pending: { ko: "대기", en: "Pending" },
  decision_accepted: { ko: "받아들임", en: "Accepted" },
  decision_rejected: { ko: "뺌", en: "Excluded" },
  revision_source: { ko: "원본", en: "Original" },
  revision_n: { ko: "수정본 {0}", en: "Revision {0}" },

  // --- 변경 pane -----------------------------------------------------------------
  filter_all: { ko: "전체", en: "All" },
  filter_pending: { ko: "남음", en: "Left" },
  filter_accepted: { ko: "받아들임", en: "Accepted" },
  filter_rejected: { ko: "뺌", en: "Excluded" },
  filter_attn: { ko: "확인", en: "Check" },
  filters_aria: { ko: "변경 거르기", en: "Filter changes" },
  changes_empty: { ko: "검토할 변경이 없습니다.", en: "No changes to review." },
  changes_filter_empty: { ko: "해당하는 변경이 없습니다.", en: "No changes match." },
  thread_row: { ko: "변경 {0}건 제안", en: "Proposed {0} changes" },
  row_before: { ko: "변경 전", en: "Before" },
  row_after: { ko: "변경 후", en: "After" },
  row_empty_value: { ko: "빈칸", en: "Empty" },
  row_removed_value: { ko: "지움", en: "Removed" },
  act_accept: { ko: "받아들이기", en: "Accept" },
  act_reject: { ko: "빼기", en: "Exclude" },
  act_edit: { ko: "고치기", en: "Edit" },
  act_undo: { ko: "결정 취소", en: "Undo decision" },
  act_add_back: { ko: "다시 넣기", en: "Add back" },
  act_accept_all: { ko: "모두 받아들이기", en: "Accept all" },
  tag_fact: { ko: "바뀐 사실", en: "Changed fact" },
  tag_attn: { ko: "확인", en: "Check" },
  tag_new_values: { ko: "새 숫자·날짜", en: "New numbers or dates" },
  tag_not_checked: { ko: "점검하지 않음", en: "Not checked" },
  tag_hard: { ko: "고쳐야 함", en: "Needs a fix" },
  restored_drafts: { ko: "입력해 둔 값 {0}개를 불러왔습니다", en: "Restored {0} saved entries" },

  // --- 결재란 ---------------------------------------------------------------------
  box_propose: { ko: "제안", en: "Proposed" },
  box_check: { ko: "점검", en: "Checked" },
  box_approve: { ko: "승인", en: "Approved" },
  box_propose_body: { ko: "{0} · {1}건", en: "{0} · {1}" },
  box_check_body: { ko: "바뀐 사실 {0} · 확인 {1}", en: "Changed facts {0} · Check {1}" },
  box_check_not_run: { ko: "점검하지 않음", en: "Not checked" },
  box_check_running: { ko: "점검 중", en: "Checking" },
  box_approved_direct: { ko: "직접 승인 · {0}", en: "Approved directly · {0}" },
  box_approved_policy: { ko: "정책으로 적용", en: "Applied by policy" },
  box_aria: { ko: "제안·점검·승인", en: "Proposal, check and approval" },

  // --- footer ---------------------------------------------------------------------
  gate_remaining: { ko: "{0}건이 남았습니다", en: "{0} left" },
  gate_hard: { ko: "{0}건을 고쳐야 승인할 수 있습니다", en: "Fix {0} before approval" },
  gate_hard_view: { ko: "보기", en: "View" },
  gate_none_accepted: { ko: "받아들인 변경이 없습니다", en: "No accepted changes" },
  gate_stale: { ko: "지난 제안", en: "Out-of-date proposal" },
  gate_busy: { ko: "처리 중", en: "Working" },
  gate_checking: { ko: "사실 점검 중", en: "Checking facts" },
  act_return: { ko: "돌려보내기", en: "Return" },
  act_approve: { ko: "승인", en: "Approve" },
  applied_status: { ko: "수정본 {0} 생성", en: "Revision {0} created" },
  applied_export: { ko: "내보내기", en: "Export" },
  applied_residue: { ko: "확인할 항목 {0}건", en: "Items to review · {0}" },

  // --- approval sheet ----------------------------------------------------------------
  sheet_title: { ko: "변경 {0}건 승인", en: "Approve changes · {0}" },
  sheet_aria: { ko: "승인", en: "Approval" },
  sheet_tally_item: { ko: "{0} {1}", en: "{0} {1}" },
  sheet_fact_row: { ko: "{0} · {1} → {2}", en: "{0} · {1} → {2}" },
  sheet_fact_value_none: { ko: "없음", en: "none" },
  sheet_tick_facts: { ko: "바뀐 사실을 확인했습니다", en: "I reviewed the changed facts" },
  sheet_tick_test: { ko: "시험용 값임을 확인했습니다", en: "I understand these are test values" },
  sheet_expected_row: { ko: "{0} · {1}", en: "{0} · {1}" },
  sheet_expected_view: { ko: "보기", en: "View" },
  sheet_expected_hide: { ko: "접기", en: "Hide" },
  sheet_base: { ko: "기준 문서", en: "Based on" },
  sheet_result: { ko: "새 수정본", en: "New revision" },
  sheet_details: { ko: "자세히", en: "Details" },
  sheet_doc_hash: { ko: "문서 검증값", en: "Document hash" },
  sheet_plan_hash: { ko: "제안 검증값", en: "Proposal hash" },
  sheet_copy: { ko: "복사", en: "Copy" },
  sheet_copied: { ko: "복사했습니다", en: "Copied" },
  sheet_digest_aria: { ko: "변경 범위", en: "Change ranges" },
  sheet_guard_scope: {
    ko: "수정한 문단의 숫자·날짜·인용문·부정 표현·증감 및 방향 표현만 점검하며, 내용이 맞는지는 판단하지 않습니다.",
    en: "This check compares only numbers, dates, quotations, negation, and expressions of increase, decrease or direction in edited paragraphs. It does not determine whether the content is correct.",
  },
  sheet_guard_skipped: { ko: "사실 점검을 실행할 수 없었습니다.", en: "The fact check could not run." },
  sheet_effect: {
    ko: "승인하면 이 컴퓨터에 새 수정본을 만듭니다. 원본은 바뀌지 않습니다. 파일은 따로 내보내며, 승인할 때는 어디에도 전송하지 않습니다.",
    en: "Approval creates a new revision on this computer. The original does not change. You export the file separately, and nothing is sent when you approve.",
  },
  sheet_cancel: { ko: "취소", en: "Cancel" },
  sheet_confirm: { ko: "승인", en: "Approve" },
  sheet_close: { ko: "닫기", en: "Close" },
  step_applying: { ko: "수정본을 만드는 중", en: "Creating revision" },
  step_checking: { ko: "점검하는 중", en: "Checking" },
  step_requesting: { ko: "승인 요청 중", en: "Requesting approval" },
  apply_failed: { ko: "수정본을 만들지 못했습니다. 문서는 그대로입니다.", en: "Could not create the revision. The document is unchanged." },

  // --- return popover ------------------------------------------------------------------
  return_title: { ko: "제안 돌려보내기", en: "Return proposal" },
  return_reason: { ko: "돌려보내는 이유 (선택)", en: "Reason for returning (optional)" },
  return_cancel: { ko: "취소", en: "Cancel" },
  return_confirm: { ko: "돌려보내기", en: "Return" },
  return_rerequest: { ko: "이유와 함께 다시 요청", en: "Request again with reason" },
  return_done: { ko: "제안을 돌려보냈습니다.", en: "Proposal returned." },
  return_done_no_request: { ko: "돌려보냈습니다. 다시 요청하지는 않았습니다.", en: "Returned. No new request was sent." },
  returned_row: { ko: "돌려보낸 제안 · {0}건", en: "Returned proposal · {0}" },

  // --- stale banner --------------------------------------------------------------------
  stale_banner: { ko: "이 제안은 {0} 기준입니다. 현재 문서는 {1}입니다.", en: "This proposal is based on {0}. The current document is {1}." },
  stale_repropose: { ko: "{0} 기준으로 다시 제안", en: "Propose again on {0}" },
  stale_return: { ko: "돌려보내기", en: "Return" },
  stale_thread: { ko: "지난 제안 · 닫힘", en: "Earlier proposal · closed" },

  // --- thread ------------------------------------------------------------------------------
  thread_me: { ko: "내 요청", en: "My request" },
  thread_agent: { ko: "에이전트", en: "Agent" },
  thread_proposal: { ko: "변경 {0}건 제안 · {1} 기준", en: "Proposed {0} changes · based on {1}" },
  thread_connected: { ko: "{0} 연결됨", en: "Connected to {0}" },
  thread_empty: { ko: "아직 요청한 작업이 없습니다.", en: "No requests yet." },
  thread_step_fallback: { ko: "제안 작성 중", en: "Preparing proposal" },
  thread_failed: { ko: "요청을 처리하지 못했습니다.", en: "Could not complete the request." },
  thread_cancelled: { ko: "요청을 취소했습니다.", en: "Request cancelled." },
  thread_no_proposal: { ko: "제안한 변경이 없습니다.", en: "No changes proposed." },
  thread_details: { ko: "자세히", en: "Details" },
  thread_attachment_aria: { ko: "첨부", en: "Attachment" },

  // --- composer --------------------------------------------------------------------------
  composer_placeholder: { ko: "요청할 작업 입력", en: "Describe the task" },
  composer_placeholder_test: { ko: "시험용 제안 만들기", en: "Make a test proposal" },
  composer_send: { ko: "요청 보내기", en: "Send request" },
  composer_cancel: { ko: "요청 취소", en: "Cancel request" },
  composer_disconnected: { ko: "에이전트 연결 안 됨", en: "Agent not connected" },
  composer_connect: { ko: "연결 설정", en: "Set up connection" },
  composer_key_needed: { ko: "{0} 연결에 인증 키가 필요합니다.", en: "An API key is required to connect to {0}." },
  composer_aria: { ko: "에이전트 요청", en: "Agent request" },
  composer_context_remove: { ko: "빼기", en: "Remove" },

  // --- 점검 pane ---------------------------------------------------------------------
  checks_group_hard: { ko: "고쳐야 승인할 수 있음", en: "Fix before approval" },
  checks_group_fact: { ko: "바뀐 사실", en: "Changed facts" },
  checks_group_attn: { ko: "확인", en: "Check" },
  checks_group_style: { ko: "문체", en: "Style" },
  checks_group_layout: { ko: "조판", en: "Layout" },
  checks_group_after: { ko: "확인할 항목", en: "Items to review" },
  checks_empty: { ko: "찾은 항목이 없습니다.", en: "Nothing found." },
  checks_style_run: { ko: "문체 점검", en: "Style check" },
  checks_style_running: { ko: "문체 점검 중", en: "Checking style" },
  checks_style_result: { ko: "검토할 표현 {0}곳", en: "Expressions to review · {0}" },
  checks_style_none: { ko: "검토할 표현이 없습니다.", en: "No expressions to review." },
  checks_style_failed: { ko: "문체 점검을 실행할 수 없었습니다.", en: "The style check could not run." },
  checks_not_run: { ko: "점검하지 않음", en: "Not checked" },
  checks_guard_running: { ko: "사실 점검 중", en: "Checking facts" },
  checks_font_sub: { ko: "글꼴 대체 · {0} → {1}", en: "Font substitution · {0} → {1}" },
} as const;

export type Wp4Key = keyof typeof WP4_STRINGS;
