import type { UiLanguage } from "../vocabulary";

export interface Wp3VocabEntry {
  readonly ko: string;
  readonly en: string;
}

export const WP3_VOCABULARY = {
  // Document strip, view switch, grade label, stepper
  canvas_view_marks: { ko: "교정부호", en: "Markup" },
  canvas_chart_not_drawn: {
    ko: "차트: 미리 보기에서는 그리지 않습니다",
    en: "Chart: not drawn in the preview",
  },
  canvas_view_clean: { ko: "완성본", en: "Clean copy" },
  canvas_view_base_source: { ko: "원본", en: "Original" },
  canvas_view_base_revision: { ko: "수정본 {0}", en: "Revision {0}" },
  canvas_grade_preview: {
    ko: "미리보기 · 인쇄 결과와 다를 수 있습니다",
    en: "Preview · Printed output may differ",
  },
  status_cell_position: { ko: "{0}쪽 · 표 {1}줄 {2}칸", en: "Page {0} · Table row {1}, column {2}" },
  status_page_position: { ko: "{0}쪽", en: "Page {0}" },
  canvas_strip_breadcrumb: { ko: "{0} › 변경 {1}건", en: "{0} › {1} changes" },
  canvas_strip_stale: {
    ko: "{0} · 지난 제안 {1}건",
    en: "{0} · {1} outdated changes",
  },
  canvas_strip_readonly: { ko: "{0} · 읽기 전용", en: "{0} · Read-only" },
  canvas_stepper_pos: { ko: "변경 {0} / {1}", en: "Change {0} of {1}" },
  canvas_stepper_short: { ko: "{0} / {1}", en: "{0} / {1}" },
  canvas_stepper_prev: { ko: "이전 변경", en: "Previous change" },
  canvas_stepper_next: { ko: "다음 변경", en: "Next change" },
  canvas_export: { ko: "내보내기", en: "Export" },

  // Mark toolbar & mark states
  mark_accept: { ko: "받아들이기", en: "Accept" },
  mark_reject: { ko: "빼기", en: "Exclude" },
  mark_restore: { ko: "다시 넣기", en: "Add back" },
  mark_edit: { ko: "고치기", en: "Edit" },
  mark_source_agent: { ko: "에이전트", en: "Agent" },
  mark_source_user: { ko: "내 입력", en: "My edit" },
  mark_source_test: { ko: "시험용", en: "Test" },
  mark_source_revert: { ko: "되돌리기", en: "Undo" },
  mark_fact_changed: { ko: "바뀐 사실", en: "Changed fact" },
  mark_form_had_text: { ko: "양식 문구가 있던 칸", en: "Cell with form text" },
  mark_body_style_matched: {
    ko: "본문 글자 모양에 맞춤",
    en: "Matched to body style",
  },

  // Seat editing & status bar & zoom
  seat_editor_label: { ko: "칸 편집", en: "Edit cell" },
  seat_narrow_commit: { ko: "입력", en: "Apply" },
  seat_narrow_cancel: { ko: "취소", en: "Cancel" },
  seat_location_table: {
    ko: "{0} · {1}쪽 · 표 {2} {3}행 {4}열",
    en: "{0} · Page {1} · Table {2}, row {3}, col {4}",
  },
  seat_location_short: {
    ko: "{0}쪽 · 표 {1} {2}행 {3}열",
    en: "Page {0} · Table {1}, row {2}, col {3}",
  },
  seat_location_no_page: {
    ko: "표 {0} {1}행 {2}열",
    en: "Table {0}, row {1}, col {2}",
  },
  seat_location_cell: {
    ko: "{0}행 {1}열",
    en: "row {0}, col {1}",
  },
  seat_group_page_table: {
    ko: "{0}쪽 · 표 {1}",
    en: "Page {0} · Table {1}",
  },
  seat_group_table: {
    ko: "표 {0}",
    en: "Table {0}",
  },
  para_not_editable_status: {
    ko: "이 문단은 아직 화면에서 고칠 수 없습니다",
    en: "This paragraph cannot be edited on the page yet",
  },
  cell_object_only_readonly: {
    ko: "표나 그림만 담긴 칸이라 글자를 입력할 문단이 없습니다",
    en: "This cell holds only tables or objects and has no text paragraph to edit",
  },
  status_page_pos: { ko: "{0} / {1}쪽", en: "Page {0} of {1}" },
  page_previous: { ko: "이전 쪽", en: "Previous page" },
  page_next: { ko: "다음 쪽", en: "Next page" },
  page_source_engine: { ko: "문서 엔진으로 그린 쪽", en: "Page drawn by the document engine" },
  page_source_hancom: { ko: "한글에서 만든 PDF", en: "PDF from Hancom Hangul" },
  page_source_pdf: { ko: "준비된 PDF", en: "Prepared PDF" },
  page_source_own: { ko: "내장 기능으로 그린 쪽", en: "Page drawn by Rigorloom" },
  page_source_projection: { ko: "간이로 그린 쪽", en: "Simplified page" },
  page_render_failed: { ko: "다시 그리지 못했습니다", en: "Could not redraw the page" },
  status_char_count: { ko: "글자 {0}", en: "{0} chars" },
  status_char_shape: { ko: "글자 모양: {0}", en: "Character shape: {0}" },
  status_font_sub: { ko: "글꼴 대체 {0}", en: "{0} font substituted" },
  status_font_sub_detail: {
    ko: "글꼴 대체 · {0} → {1}",
    en: "Font substitution · {0} → {1}",
  },
  font_install_title: { ko: "대체 글꼴", en: "Substitute fonts" },
  font_install_body: {
    ko: "아래 글꼴은 대체 글꼴로 표시됩니다. 공식 배포처에서 받아 설치한 뒤 다시 확인해 주세요.",
    en: "The faces below use substitutes. Download and install the fonts from the official source, then check again.",
  },
  font_install_substituted: { ko: "아래 글꼴은 대체 글꼴로 표시됩니다.", en: "The faces below use substitutes." },
  font_install_drawn_with: { ko: "표시 글꼴 · {0}", en: "Drawn with {0}" },
  font_install_drawn_unknown: { ko: "표시 글꼴을 확인할 수 없습니다.", en: "The substitute face is unknown." },
  font_install_source: { ko: "공식 배포처 열기", en: "Open official source" },
  font_install_recheck: { ko: "다시 확인", en: "Check again" },
  font_install_close: { ko: "닫기", en: "Close" },
  font_install_checking: { ko: "설치된 글꼴을 확인하는 중…", en: "Checking installed fonts…" },
  font_install_unknown: { ko: "글꼴 설치 여부를 확인할 수 없습니다.", en: "Font installation could not be verified." },
  font_install_checked: { ko: "누락된 한컴 글꼴이 없습니다.", en: "No Hancom fonts are missing." },
  font_install_open_failed: { ko: "공식 배포처를 열지 못했습니다.", en: "Could not open the official source." },
  zoom_fit_width: { ko: "폭 맞춤", en: "Fit width" },
  zoom_fit_page: { ko: "쪽 맞춤", en: "Fit page" },
  zoom_out: { ko: "축소", en: "Zoom out" },
  zoom_in: { ko: "확대", en: "Zoom in" },
  zoom_label: { ko: "배율 {0}%", en: "Zoom {0}%" },

  // Left panes: Outline, Blanks, Find
  pane_outline_title: { ko: "개요", en: "Outline" },
  pane_blanks_title: { ko: "빈칸", en: "Blanks" },
  pane_find_title: { ko: "찾기", en: "Find" },
  outline_page_header: { ko: "{0}쪽", en: "Page {0}" },
  outline_page_header_count: { ko: "{0}쪽 · {1}건", en: "Page {0} · {1}" },
  outline_tables_group: { ko: "표 및 서식", en: "Tables and forms" },
  outline_table_item: { ko: "표 {0}", en: "Table {0}" },
  outline_empty: {
    ko: "문서에 제목이 없습니다.",
    en: "This document has no headings.",
  },
  outline_form_head: { ko: "서식 머리", en: "Form header" },
  outline_form_opening: { ko: "두문", en: "Opening block" },
  outline_form_body: { ko: "본문", en: "Body" },
  outline_form_closing: { ko: "발신명의", en: "Sender" },
  outline_form_signers: { ko: "서명란", en: "Signers" },
  outline_form_coop: { ko: "협조자", en: "Cooperation" },
  outline_form_dispatch: { ko: "시행 · 접수", en: "Dispatch · Receipt" },
  outline_form_contact: { ko: "주소 · 연락처", en: "Address · Contact" },
  outline_form_note: { ko: "비고", en: "Notes" },
  outline_form_attachment: { ko: "붙임", en: "Attachments" },

  blanks_counter: {
    ko: "빈칸 {1}개 중 {0}개 입력",
    en: "{0} of {1} blanks filled",
  },
  blanks_empty: { ko: "입력할 빈칸이 없습니다.", en: "No blanks to fill." },
  blanks_agency_group: {
    ko: "접수 기관이 쓰는 칸",
    en: "Receiving agency blanks",
  },
  blanks_status_filled: { ko: "채움", en: "Filled" },
  blanks_status_empty: { ko: "비어 있음", en: "Empty" },

  find_input_placeholder: { ko: "찾을 문구", en: "Find text" },
  replace_input_placeholder: { ko: "바꿀 문구", en: "Replace with" },
  find_match_pos: { ko: "{1}건 중 {0}번째", en: "Result {0} of {1}" },
  find_no_matches: {
    ko: "‘{0}’ 검색 결과가 없습니다.",
    en: "No matches for “{0}”.",
  },
  find_prev: { ko: "이전", en: "Previous" },
  find_next: { ko: "다음", en: "Next" },
  replace_one: { ko: "바꾸기", en: "Replace" },
  replace_all: { ko: "모두 바꾸기", en: "Replace all" },

  // Font substitution target labels
  font_nanum_myeongjo: { ko: "나눔명조", en: "Nanum Myeongjo" },
  font_nanum_gothic: { ko: "나눔고딕", en: "Nanum Gothic" },

  // Accessibility & command labels
  paper_aria_label: { ko: "문서 쪽", en: "Document page" },
  scrollmap_aria_label: { ko: "변경 위치 지도", en: "Change locations map" },
  margin_mark_aria: { ko: "변경 {0}", en: "Change {0}" },
  cmd_category_canvas: { ko: "문서 화면", en: "Canvas" },
  cmd_cycle_view: { ko: "변경 표시 방식 전환", en: "Cycle change view" },
  cmd_fit_width: { ko: "폭 맞춤", en: "Fit width" },
  cmd_fit_page: { ko: "쪽 맞춤", en: "Fit page" },
  cmd_zoom_in: { ko: "화면 확대", en: "Zoom in" },
  cmd_zoom_out: { ko: "화면 축소", en: "Zoom out" },
  cmd_find: { ko: "문서에서 찾기", en: "Find in document" },
  cmd_replace: { ko: "찾아 바꾸기", en: "Find and replace" },
  cmd_open_blanks: { ko: "빈칸 목록 보기", en: "Show blanks pane" },
  cmd_open_outline: { ko: "개요 보기", en: "Show outline pane" },
} as const satisfies Record<string, Wp3VocabEntry>;

export type Wp3VocabKey = keyof typeof WP3_VOCABULARY;

export function wp3t(
  key: Wp3VocabKey,
  lang: UiLanguage = "ko",
  args: readonly (string | number)[] = [],
): string {
  const entry = WP3_VOCABULARY[key];
  let out: string = entry[lang] ?? entry.ko;
  for (let i = 0; i < args.length; i += 1) {
    out = out.split(`{${i}}`).join(String(args[i]));
  }
  return out;
}

export default WP3_VOCABULARY;
