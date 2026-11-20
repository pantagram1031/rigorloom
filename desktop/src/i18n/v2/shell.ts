/**
 * Shell strings (WP2). Folded into vocabulary.ts by WP7.
 * Copy follows out/C-copy.md and J1 §3 Copy.
 */
import { defineStrings } from "./index.ts";

export const S = defineStrings("shell", {
  // title bar and tabs
  shell_app_name: { ko: "Rigorloom", en: "Rigorloom" },
  shell_window_title_doc: { ko: "{0} — Rigorloom", en: "{0} — Rigorloom" },
  shell_tab_start: { ko: "시작", en: "Start" },
  shell_tab_untitled: { ko: "제목 없는 문서", en: "Untitled document" },
  shell_tab_close: { ko: "탭 닫기 · {0}", en: "Close tab · {0}" },
  shell_tab_add: { ko: "문서 열기", en: "Open document" },
  shell_tab_list: { ko: "열린 문서 목록", en: "Open documents" },
  shell_tab_changes_count: { ko: "변경 {0}건 대기", en: "{0} changes pending" },
  shell_tab_failed: { ko: "열지 못함", en: "Could not open" },
  shell_tab_opening: { ko: "문서 여는 중", en: "Opening document" },
  shell_palette_field: { ko: "명령, 문서, 빈칸 찾기", en: "Commands, documents, blanks" },
  shell_toggle_left: { ko: "왼쪽 창", en: "Left pane" },
  shell_narrow_changes_open: { ko: "변경 {0}건 · 열기", en: "{0} changes · Open" },
  shell_narrow_changes_close: { ko: "변경 창 닫기", en: "Close review panel" },
  shell_toggle_right: { ko: "오른쪽 창", en: "Right panel" },
  shell_app_menu: { ko: "메뉴", en: "Menu" },
  shell_win_minimize: { ko: "최소화", en: "Minimize" },
  shell_win_maximize: { ko: "최대화", en: "Maximize" },
  shell_win_close: { ko: "닫기", en: "Close" },

  // left pane tabs
  shell_pane_files: { ko: "파일", en: "Files" },
  shell_pane_outline: { ko: "개요", en: "Outline" },
  shell_pane_blanks: { ko: "빈칸", en: "Blanks" },
  shell_pane_find: { ko: "찾기", en: "Find" },
  shell_pane_history: { ko: "기록", en: "History" },
  shell_panes_label: { ko: "왼쪽 창 전환", en: "Left pane" },

  // files pane
  shell_files_doc_folder: { ko: "문서 폴더", en: "Documents folder" },
  shell_files_open_docs: { ko: "열린 문서", en: "Open documents" },
  shell_files_samples: { ko: "예시 양식", en: "Sample forms" },
  shell_files_empty: { ko: "이 폴더에 열 수 있는 문서가 없습니다.", en: "No documents in this folder." },
  shell_files_unavailable: { ko: "문서 폴더를 읽을 수 없습니다.", en: "The documents folder cannot be read." },
  shell_files_loading: { ko: "폴더 읽는 중", en: "Reading folder" },
  shell_open_filter: { ko: "문서", en: "Documents" },

  // start tab
  shell_start_boundary: {
    ko: "에이전트는 제안하고, 사람이 승인합니다. 승인한 변경만 새 수정본이 되고 원본은 바뀌지 않습니다.",
    en: "Agents propose. A person approves. Only approved changes become a new revision, and the original never changes.",
  },
  shell_start_open_file: { ko: "파일 열기", en: "Open file" },
  shell_start_open_folder: { ko: "폴더 열기", en: "Open folder" },
  shell_start_samples: { ko: "예시 양식", en: "Sample forms" },
  shell_start_recent: { ko: "최근 문서", en: "Recent documents" },
  shell_start_drop: { ko: "놓으면 엽니다", en: "Drop to open" },
  shell_start_engine_missing: {
    ko: "문서 엔진이 없습니다. 엔진을 설치해야 문서를 열 수 있습니다.",
    en: "The document engine is missing. Install it to open documents.",
  },
  shell_start_engine_help: { ko: "설치 방법", en: "How to install" },
  shell_recent_pending: { ko: "변경 {0}건 대기", en: "{0} changes pending" },
  shell_recent_revision: { ko: "수정본 {0}", en: "Revision {0}" },
  shell_recent_original: { ko: "원본", en: "Original" },
  shell_recent_sample: { ko: "예시 양식", en: "Sample form" },

  // document states in the canvas column
  shell_doc_opening: { ko: "문서 여는 중", en: "Opening document" },
  shell_doc_failed: {
    ko: "문서를 읽지 못했습니다. 파일이 손상됐거나 지원하지 않는 구조입니다.",
    en: "The document could not be read. The file is damaged or uses an unsupported structure.",
  },
  shell_doc_failed_hwp: {
    ko: "한글에서 .hwpx로 다시 저장한 뒤 열어 주세요.",
    en: "Save it again as .hwpx in Hangul, then open it.",
  },
  shell_doc_open_other: { ko: "다른 파일 열기", en: "Open another file" },
  shell_details: { ko: "자세히", en: "Details" },

  // status bar
  shell_status_engine_ready: { ko: "엔진 준비됨", en: "Engine ready" },
  shell_status_engine_checking: { ko: "엔진 확인 중", en: "Checking engine" },
  shell_status_engine_missing: { ko: "엔진 없음", en: "Engine missing" },
  shell_status_engine_stopped: { ko: "엔진 멈춤", en: "Engine stopped" },
  shell_status_agent_none: { ko: "에이전트 연결 안 됨", en: "Agent not connected" },
  shell_status_agent_ready: { ko: "{0} 연결됨", en: "Connected to {0}" },
  shell_status_agent_test: { ko: "시험용 제안", en: "Test proposal" },
  shell_status_saved: { ko: "저장됨", en: "Saved" },
  shell_status_saving: { ko: "저장 중", en: "Saving" },
  shell_status_save_failed: { ko: "저장하지 못함", en: "Save failed" },
  shell_status_doc_folder: { ko: "문서 폴더 {0}", en: "Documents folder {0}" },
  shell_status_changes: { ko: "변경 {0}", en: "Changes {0}" },
  shell_status_zoom: { ko: "{0}%", en: "{0}%" },

  // command palette
  shell_palette_placeholder: { ko: "명령 찾기", en: "Find a command" },
  shell_palette_group_commands: { ko: "명령", en: "Commands" },
  shell_palette_group_docs: { ko: "열린 문서", en: "Open documents" },
  shell_palette_group_files: { ko: "문서 폴더", en: "Documents folder" },
  shell_palette_group_samples: { ko: "예시 양식", en: "Sample forms" },
  shell_palette_empty: { ko: "‘{0}’ 검색 결과가 없습니다.", en: "No matches for “{0}”." },
  shell_palette_hint_select: { ko: "선택", en: "Select" },
  shell_palette_hint_run: { ko: "실행", en: "Run" },
  shell_palette_hint_close: { ko: "닫기", en: "Close" },
  shell_palette_label: { ko: "명령창", en: "Command palette" },

  // commands (palette rows and the app menu)
  shell_cmd_open_file: { ko: "파일 열기", en: "Open file" },
  shell_cmd_open_folder: { ko: "폴더 열기", en: "Open folder" },
  shell_cmd_new_tab: { ko: "시작 탭 열기", en: "Open Start tab" },
  shell_cmd_close_tab: { ko: "탭 닫기", en: "Close tab" },
  shell_cmd_next_tab: { ko: "다음 탭", en: "Next tab" },
  shell_cmd_prev_tab: { ko: "이전 탭", en: "Previous tab" },
  shell_cmd_settings: { ko: "설정", en: "Settings" },
  shell_cmd_fullscreen: { ko: "전체 화면", en: "Full screen" },
  shell_cmd_toggle_left: { ko: "왼쪽 창 열기·닫기", en: "Toggle left pane" },
  shell_cmd_toggle_right: { ko: "오른쪽 창 열기·닫기", en: "Toggle right panel" },
  shell_cmd_pane_files: { ko: "파일 창", en: "Files pane" },
  shell_cmd_pane_outline: { ko: "개요 창", en: "Outline pane" },
  shell_cmd_pane_blanks: { ko: "빈칸 창", en: "Blanks pane" },
  shell_cmd_pane_find: { ko: "찾기 창", en: "Find pane" },
  shell_cmd_pane_history: { ko: "기록 창", en: "History pane" },
  shell_cmd_save: { ko: "저장", en: "Save" },
  shell_cmd_theme_light: { ko: "밝은 화면", en: "Light theme" },
  shell_cmd_theme_dark: { ko: "어두운 화면", en: "Dark theme" },
  shell_cmd_theme_system: { ko: "시스템 화면 설정", en: "System theme" },
  shell_cmd_language_ko: { ko: "화면 언어 한국어", en: "Language Korean" },
  shell_cmd_language_en: { ko: "화면 언어 영어", en: "Language English" },
  shell_cmd_samples: { ko: "예시 양식 열기", en: "Open sample form" },

  // settings dialog
  shell_settings_title: { ko: "설정", en: "Settings" },
  shell_settings_general: { ko: "일반", en: "General" },
  shell_settings_folders: { ko: "폴더", en: "Folders" },
  shell_settings_dev: { ko: "개발", en: "Developer" },
  shell_settings_agent: { ko: "에이전트", en: "Agent" },
  shell_settings_language: { ko: "화면 언어", en: "Language" },
  shell_settings_theme: { ko: "화면 테마", en: "Theme" },
  shell_settings_theme_system: { ko: "시스템", en: "System" },
  shell_settings_theme_light: { ko: "밝게", en: "Light" },
  shell_settings_theme_dark: { ko: "어둡게", en: "Dark" },
  shell_settings_lang_ko: { ko: "한국어", en: "Korean" },
  shell_settings_lang_en: { ko: "영어", en: "English" },
  shell_settings_work_folder: { ko: "작업 폴더", en: "Working folder" },
  shell_settings_work_folder_note: { ko: "작업 사본과 기록을 보관합니다.", en: "Keeps working copies and history." },
  shell_settings_doc_folder: { ko: "문서 폴더", en: "Documents folder" },
  shell_settings_close: { ko: "닫기", en: "Close" },
  shell_settings_ui_zoom: { ko: "화면 배율", en: "Interface zoom" },

  // misc
  shell_slot_failed: { ko: "이 영역을 표시할 수 없습니다.", en: "This area cannot be shown." },
  shell_slot_pending: { ko: "준비 중", en: "Not available yet" },
});
