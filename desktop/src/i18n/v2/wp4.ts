/**
 * WP4 strings: right panel, the 결재란 footer, the approval sheet, the return
 * popover, the stale banner, the thread, the composer and the 점검 pane.
 *
 * Korean values carry no Latin letters; key names
 * are drawn by the Keycap component, never written into a value. No particle
 * is attached to a placeholder.
 */

import { defineStrings } from "./index.ts";

export const WP4_STRINGS = {
  // --- right panel tabs ------------------------------------------------------------
  wp4_panel_tab_changes: { ko: "변경", en: "Changes" },
  wp4_panel_tab_agent: { ko: "에이전트", en: "Agent" },
  wp4_panel_tab_checks: { ko: "점검", en: "Checks" },
  wp4_panel_aria: { ko: "오른쪽 창", en: "Right panel" },

  // --- sources and states ----------------------------------------------------------
  wp4_source_agent: { ko: "에이전트", en: "Agent" },
  wp4_source_user: { ko: "내 입력", en: "My input" },
  wp4_source_test: { ko: "시험용", en: "Test" },
  wp4_source_revert: { ko: "되돌리기", en: "Undo" },
  wp4_decision_pending: { ko: "대기", en: "Pending" },
  wp4_decision_accepted: { ko: "받아들임", en: "Accepted" },
  wp4_decision_rejected: { ko: "뺌", en: "Excluded" },
  wp4_revision_source: { ko: "원본", en: "Original" },
  wp4_revision_n: { ko: "수정본 {0}", en: "Revision {0}" },

  // --- 변경 pane -----------------------------------------------------------------
  wp4_filter_all: { ko: "전체", en: "All" },
  wp4_filter_pending: { ko: "남음", en: "Left" },
  wp4_filter_accepted: { ko: "받아들임", en: "Accepted" },
  wp4_filter_rejected: { ko: "뺌", en: "Excluded" },
  wp4_filter_attn: { ko: "확인", en: "Check" },
  wp4_filters_aria: { ko: "변경 거르기", en: "Filter changes" },
  wp4_changes_empty: { ko: "검토할 변경이 없습니다.", en: "No changes to review." },
  wp4_changes_filter_empty: { ko: "해당하는 변경이 없습니다.", en: "No changes match." },
  wp4_thread_row: { ko: "변경 {0}건 제안", en: "Proposed {0} changes" },
  wp4_row_before: { ko: "변경 전", en: "Before" },
  wp4_row_after: { ko: "변경 후", en: "After" },
  wp4_row_empty_value: { ko: "빈칸", en: "Empty" },
  wp4_row_removed_value: { ko: "지움", en: "Removed" },
  wp4_act_accept: { ko: "받아들이기", en: "Accept" },
  wp4_act_reject: { ko: "빼기", en: "Exclude" },
  wp4_act_edit: { ko: "고치기", en: "Edit" },
  wp4_act_undo: { ko: "결정 취소", en: "Undo decision" },
  wp4_act_add_back: { ko: "다시 넣기", en: "Add back" },
  wp4_act_accept_all: { ko: "모두 받아들이기", en: "Accept all" },
  wp4_tag_fact: { ko: "바뀐 사실", en: "Changed fact" },
  wp4_tag_attn: { ko: "확인", en: "Check" },
  wp4_tag_new_values: { ko: "새 숫자·날짜", en: "New numbers or dates" },
  wp4_tag_not_checked: { ko: "점검하지 않음", en: "Not checked" },
  wp4_tag_hard: { ko: "고쳐야 함", en: "Needs a fix" },
  wp4_restored_drafts: { ko: "입력해 둔 값 {0}개를 불러왔습니다", en: "Restored {0} saved entries" },

  // --- 결재란 ---------------------------------------------------------------------
  wp4_box_propose: { ko: "제안", en: "Proposed" },
  wp4_box_check: { ko: "점검", en: "Checked" },
  wp4_box_approve: { ko: "승인", en: "Approved" },
  wp4_box_propose_body: { ko: "{0} · {1}건", en: "{0} · {1}" },
  wp4_box_check_body: { ko: "바뀐 사실 {0} · 확인 {1}", en: "Changed facts {0} · Check {1}" },
  wp4_box_check_not_run: { ko: "점검하지 않음", en: "Not checked" },
  wp4_box_check_running: { ko: "점검 중", en: "Checking" },
  wp4_box_approved_direct: { ko: "직접 승인 · {0}", en: "Approved directly · {0}" },
  wp4_box_approved_policy: { ko: "정책으로 적용", en: "Applied by policy" },
  wp4_box_aria: { ko: "제안·점검·승인", en: "Proposal, check and approval" },

  // --- footer ---------------------------------------------------------------------
  wp4_gate_remaining: { ko: "{0}건이 남았습니다", en: "{0} left" },
  wp4_gate_hard: { ko: "{0}건을 고쳐야 승인할 수 있습니다", en: "Fix {0} before approval" },
  wp4_gate_hard_view: { ko: "보기", en: "View" },
  wp4_gate_none_accepted: { ko: "받아들인 변경이 없습니다", en: "No accepted changes" },
  wp4_gate_stale: { ko: "지난 제안", en: "Out-of-date proposal" },
  wp4_gate_busy: { ko: "처리 중", en: "Working" },
  wp4_gate_checking: { ko: "사실 점검 중", en: "Checking facts" },
  wp4_act_return: { ko: "돌려보내기", en: "Return" },
  wp4_act_approve: { ko: "승인", en: "Approve" },
  wp4_applied_status: { ko: "수정본 {0} 생성", en: "Revision {0} created" },
  wp4_applied_export: { ko: "내보내기", en: "Export" },
  wp4_applied_residue: { ko: "확인할 항목 {0}건", en: "Items to review · {0}" },

  // --- approval sheet ----------------------------------------------------------------
  wp4_sheet_title: { ko: "변경 {0}건 승인", en: "Approve changes · {0}" },
  wp4_sheet_aria: { ko: "승인", en: "Approval" },
  wp4_sheet_tally_item: { ko: "{0} {1}", en: "{0} {1}" },
  wp4_sheet_fact_row: { ko: "{0} · {1} → {2}", en: "{0} · {1} → {2}" },
  wp4_sheet_fact_value_none: { ko: "없음", en: "none" },
  wp4_sheet_tick_facts: { ko: "바뀐 사실을 확인했습니다", en: "I reviewed the changed facts" },
  wp4_sheet_tick_test: { ko: "시험용 값임을 확인했습니다", en: "I understand these are test values" },
  wp4_sheet_expected_row: { ko: "{0} · {1}", en: "{0} · {1}" },
  wp4_sheet_expected_view: { ko: "보기", en: "View" },
  wp4_sheet_expected_hide: { ko: "접기", en: "Hide" },
  wp4_sheet_base: { ko: "기준 문서", en: "Based on" },
  wp4_sheet_result: { ko: "새 수정본", en: "New revision" },
  wp4_sheet_details: { ko: "자세히", en: "Details" },
  wp4_sheet_doc_hash: { ko: "문서 검증값", en: "Document hash" },
  wp4_sheet_plan_hash: { ko: "제안 검증값", en: "Proposal hash" },
  wp4_sheet_copy: { ko: "복사", en: "Copy" },
  wp4_sheet_copied: { ko: "복사했습니다", en: "Copied" },
  wp4_sheet_digest_aria: { ko: "변경 범위", en: "Change ranges" },
  wp4_sheet_guard_scope: {
    ko: "수정한 문단의 숫자·날짜·인용문·부정 표현·증감 및 방향 표현만 점검하며, 내용이 맞는지는 판단하지 않습니다.",
    en: "This check compares only numbers, dates, quotations, negation, and expressions of increase, decrease or direction in edited paragraphs. It does not determine whether the content is correct.",
  },
  wp4_sheet_guard_skipped: { ko: "사실 점검을 실행할 수 없었습니다.", en: "The fact check could not run." },
  wp4_sheet_effect: {
    ko: "승인하면 이 컴퓨터에 새 수정본을 만듭니다. 원본은 바뀌지 않습니다. 파일은 따로 내보내며, 승인할 때는 어디에도 전송하지 않습니다.",
    en: "Approval creates a new revision on this computer. The original does not change. You export the file separately, and nothing is sent when you approve.",
  },
  wp4_sheet_cancel: { ko: "취소", en: "Cancel" },
  wp4_sheet_confirm: { ko: "승인", en: "Approve" },
  wp4_sheet_close: { ko: "닫기", en: "Close" },
  wp4_step_applying: { ko: "수정본을 만드는 중", en: "Creating revision" },
  wp4_step_checking: { ko: "점검하는 중", en: "Checking" },
  wp4_step_requesting: { ko: "승인 요청 중", en: "Requesting approval" },
  wp4_apply_failed: { ko: "수정본을 만들지 못했습니다. 문서는 그대로입니다.", en: "Could not create the revision. The document is unchanged." },

  // --- return popover ------------------------------------------------------------------
  wp4_return_title: { ko: "제안 돌려보내기", en: "Return proposal" },
  wp4_return_reason: { ko: "돌려보내는 이유 (선택)", en: "Reason for returning (optional)" },
  wp4_return_cancel: { ko: "취소", en: "Cancel" },
  wp4_return_confirm: { ko: "돌려보내기", en: "Return" },
  wp4_return_rerequest: { ko: "이유와 함께 다시 요청", en: "Request again with reason" },
  wp4_return_done: { ko: "제안을 돌려보냈습니다.", en: "Proposal returned." },
  wp4_return_done_no_request: { ko: "돌려보냈습니다. 다시 요청하지는 않았습니다.", en: "Returned. No new request was sent." },
  wp4_returned_row: { ko: "돌려보낸 제안 · {0}건", en: "Returned proposal · {0}" },

  // --- stale banner --------------------------------------------------------------------
  wp4_stale_banner: { ko: "이 제안은 {0} 기준입니다. 현재 문서는 {1}입니다.", en: "This proposal is based on {0}. The current document is {1}." },
  wp4_stale_repropose: { ko: "{0} 기준으로 다시 제안", en: "Propose again on {0}" },
  wp4_stale_return: { ko: "돌려보내기", en: "Return" },
  wp4_stale_thread: { ko: "지난 제안 · 닫힘", en: "Earlier proposal · closed" },

  // --- thread ------------------------------------------------------------------------------
  wp4_thread_me: { ko: "내 요청", en: "My request" },
  wp4_thread_agent: { ko: "에이전트", en: "Agent" },
  wp4_thread_proposal: { ko: "변경 {0}건 제안 · {1} 기준", en: "Proposed {0} changes · based on {1}" },
  wp4_thread_connected: { ko: "{0} 연결됨", en: "Connected to {0}" },
  wp4_thread_empty: { ko: "아직 요청한 작업이 없습니다.", en: "No requests yet." },
  wp4_thread_step_fallback: { ko: "제안 작성 중", en: "Preparing proposal" },
  wp4_thread_failed: { ko: "요청을 처리하지 못했습니다.", en: "Could not complete the request." },
  wp4_thread_cancelled: { ko: "요청을 취소했습니다.", en: "Request cancelled." },
  wp4_thread_no_proposal: { ko: "제안한 변경이 없습니다.", en: "No changes proposed." },
  wp4_thread_details: { ko: "자세히", en: "Details" },
  wp4_thread_attachment_aria: { ko: "첨부", en: "Attachment" },

  // --- composer --------------------------------------------------------------------------
  wp4_composer_placeholder: { ko: "요청할 작업 입력", en: "Describe the task" },
  wp4_composer_placeholder_test: { ko: "시험용 제안 만들기", en: "Make a test proposal" },
  wp4_composer_send: { ko: "요청 보내기", en: "Send request" },
  wp4_composer_cancel: { ko: "요청 취소", en: "Cancel request" },
  wp4_composer_disconnected: { ko: "에이전트 연결 안 됨", en: "Agent not connected" },
  wp4_composer_connect: { ko: "연결 설정", en: "Set up connection" },
  wp4_composer_key_needed: { ko: "{0} 연결에 인증 키가 필요합니다.", en: "An API key is required to connect to {0}." },
  wp4_composer_aria: { ko: "에이전트 요청", en: "Agent request" },
  wp4_composer_context_remove: { ko: "빼기", en: "Remove" },

  // --- 점검 pane ---------------------------------------------------------------------
  wp4_checks_group_hard: { ko: "고쳐야 승인할 수 있음", en: "Fix before approval" },
  wp4_checks_group_fact: { ko: "바뀐 사실", en: "Changed facts" },
  wp4_checks_group_attn: { ko: "확인", en: "Check" },
  wp4_checks_group_style: { ko: "문체", en: "Style" },
  wp4_checks_group_layout: { ko: "조판", en: "Layout" },
  wp4_checks_group_after: { ko: "확인할 항목", en: "Items to review" },
  wp4_checks_empty: { ko: "찾은 항목이 없습니다.", en: "Nothing found." },
  wp4_checks_style_run: { ko: "문체 점검", en: "Style check" },
  wp4_checks_style_running: { ko: "문체 점검 중", en: "Checking style" },
  wp4_checks_style_result: { ko: "검토할 표현 {0}곳", en: "Expressions to review · {0}" },
  wp4_checks_style_none: { ko: "검토할 표현이 없습니다.", en: "No expressions to review." },
  wp4_checks_style_failed: { ko: "문체 점검을 실행할 수 없었습니다.", en: "The style check could not run." },
  wp4_checks_not_run: { ko: "점검하지 않음", en: "Not checked" },
  wp4_checks_guard_running: { ko: "사실 점검 중", en: "Checking facts" },
  wp4_checks_font_sub: { ko: "글꼴 대체 · {0} → {1}", en: "Font substitution · {0} → {1}" },
} as const;

export const WP4 = defineStrings("wp4", WP4_STRINGS);

export type Wp4Key = keyof typeof WP4_STRINGS;
