import { formatTemplate, type UiLanguage, type VocabEntry } from "../vocabulary.ts";

export type Wp1bVars = Record<string, string | number> | ReadonlyArray<string | number>;

export const WP1B_STRINGS = {
  approval_col_propose: { ko: "제안", en: "Proposal" },
  approval_col_check: { ko: "점검", en: "Check" },
  approval_col_approve: { ko: "승인", en: "Approval" },
  sheet_close: { ko: "창 닫기", en: "Close sheet" },
  menu_app_label: { ko: "프로그램 메뉴", en: "Application menu" },

  gallery_title: { ko: "기본 구성 요소 점검판", en: "UI Primitives Gallery" },
  gallery_theme_light: { ko: "밝은 화면", en: "Light" },
  gallery_theme_dark: { ko: "어두운 화면", en: "Dark" },
  gallery_lang_ko: { ko: "한국어", en: "Korean" },
  gallery_lang_en: { ko: "영어", en: "English" },

  gallery_sec_buttons: { ko: "버튼과 단축키", en: "Buttons and keycaps" },
  gallery_sec_tags: { ko: "표식과 출처", en: "Tags and sources" },
  gallery_sec_tabs: { ko: "창 전환과 보기 스위치", en: "Tabs and view switch" },
  gallery_sec_rows: { ko: "목록 행과 변경 행", en: "List and change rows" },
  gallery_sec_approval: { ko: "승인란과 고정 창", en: "Approval box and docked sheet" },
  gallery_sec_overlays: { ko: "메뉴와 팝오버", en: "Menu, popover and tooltip" },
  gallery_sec_icons: { ko: "아이콘과 상표 표식", en: "Icons and brand mark" },

  demo_approve: { ko: "승인", en: "Approve" },
  demo_accept: { ko: "받아들이기", en: "Accept" },
  demo_exclude: { ko: "빼기", en: "Exclude" },
  demo_edit: { ko: "고치기", en: "Edit" },
  demo_return: { ko: "돌려보내기", en: "Return" },
  demo_export: { ko: "내보내기", en: "Export" },
  demo_cancel: { ko: "취소", en: "Cancel" },
  demo_send: { ko: "요청 보내기", en: "Send request" },
  demo_cmd_find: { ko: "명령, 문서, 빈칸 찾기", en: "Find command, document, blank" },

  demo_source_agent: { ko: "에이전트", en: "Agent" },
  demo_source_user: { ko: "내 입력", en: "My input" },
  demo_source_test: { ko: "시험용", en: "Test" },
  demo_source_revert: { ko: "되돌리기", en: "Undo" },
  demo_tag_fact: { ko: "바뀐 사실", en: "Changed fact" },
  demo_tag_attn: { ko: "확인 {0}", en: "Review · {0}" },
  demo_tag_numbers: { ko: "새로 넣은 숫자·날짜", en: "Added numbers or dates" },
  demo_tag_prefilled: { ko: "양식 문구가 있던 칸", en: "Cell had form text" },

  demo_pane_files: { ko: "파일", en: "Files" },
  demo_pane_outline: { ko: "개요", en: "Outline" },
  demo_pane_blanks: { ko: "빈칸", en: "Blanks" },
  demo_pane_find: { ko: "찾기", en: "Find" },
  demo_pane_history: { ko: "기록", en: "History" },

  demo_panel_changes: { ko: "변경", en: "Changes" },
  demo_panel_agent: { ko: "에이전트", en: "Agent" },
  demo_panel_check: { ko: "점검", en: "Checks" },

  demo_seg_marks: { ko: "변경 표시", en: "Show changes" },
  demo_seg_clean: { ko: "표시 없이", en: "Clean view" },
  demo_seg_base: { ko: "원본", en: "Original" },

  demo_row_agency: { ko: "행정기관명", en: "Agency name" },
  demo_row_op_fill: { ko: "빈칸 채움", en: "Fill blank" },
  demo_row_agency_val: { ko: "가온공공기록원", en: "Gaon Public Archives" },
  demo_row_accepted: { ko: "받아들임", en: "Accepted" },
  demo_row_excluded: { ko: "뺌", en: "Excluded" },
  demo_row_body: { ko: "본문", en: "Body" },
  demo_row_before: { ko: "변경 전", en: "Before" },
  demo_row_after: { ko: "변경 후", en: "After" },
  demo_row_body_after: {
    ko: "관련 문서에 따라 보존 포맷 호환성을 공동 점검합니다",
    en: "Jointly inspect preservation format compatibility per related notice",
  },
  demo_row_term: { ko: "계약 시작일", en: "Contract start date" },
  demo_row_op_replace: { ko: "칸 문구 바꿈", en: "Replace cell text" },
  demo_row_term_diff: {
    ko: "2026년 1월 1일 → 2027년 1월 1일",
    en: "Jan 1, 2026 → Jan 1, 2027",
  },
  demo_outline_heading: { ko: "서식 머리", en: "Form header" },
  demo_outline_body: { ko: "두문 및 본문", en: "Header and body" },

  demo_box_propose_val: { ko: "에이전트 · {0}건", en: "Agent · {0}" },
  demo_box_check_val: { ko: "바뀐 사실 {0} · 확인 {1}", en: "Facts {0} · Review {1}" },
  demo_box_approved_val: { ko: "직접 승인 · 오후 2:31", en: "Direct · 2:31 PM" },

  demo_sheet_title: { ko: "변경 {0}건 승인", en: "Approve changes · {0}" },
  demo_sheet_sub: {
    ko: "빈칸 채움 16 · 안내문 지움 6 · 기호 지움 2",
    en: "Fill 16 · Remove guide 6 · Remove symbol 2",
  },
  demo_sheet_base_label: { ko: "기준 문서", en: "Based on" },
  demo_sheet_base_val: { ko: "원본", en: "Original" },
  demo_sheet_next_label: { ko: "새 수정본", en: "New revision" },
  demo_sheet_next_val: { ko: "수정본 1", en: "Revision 1" },
  demo_fact_confirm: { ko: "바뀐 사실을 확인했습니다", en: "I reviewed the changed facts" },

  demo_menu_open: { ko: "파일 열기", en: "Open file" },
  demo_menu_folder: { ko: "폴더 열기", en: "Open folder" },
  demo_menu_settings: { ko: "설정", en: "Settings" },
  demo_pop_return_label: { ko: "돌려보내는 이유 (선택)", en: "Reason for returning (optional)" },
  demo_pop_return_rerequest: { ko: "이유와 함께 다시 요청", en: "Return and request again" },
  demo_tooltip_left: { ko: "왼쪽 창 여닫기", en: "Toggle left pane" },
  demo_tooltip_right: { ko: "오른쪽 창 여닫기", en: "Toggle right panel" },
} as const satisfies Record<string, VocabEntry>;

export type Wp1bStringKey = keyof typeof WP1B_STRINGS;

export function tWp1b(key: Wp1bStringKey, lang: UiLanguage, vars?: Wp1bVars): string {
  const entry = WP1B_STRINGS[key];
  return formatTemplate(entry[lang] ?? entry.ko, vars);
}
