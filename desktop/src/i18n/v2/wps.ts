/**
 * Editor v2 string entries owned by WPS Helpers (titles, dates, export naming).
 * Folded into `i18n/vocabulary.ts` by WP7 during final integration.
 */
import type { UiLanguage } from "../../types.ts";

export interface WpsVocabEntry {
  readonly ko: string;
  readonly en: string;
}

export const WPS_VOCABULARY = {
  wps_window_title_app: {
    ko: "Rigorloom",
    en: "Rigorloom",
  },
  wps_window_title_doc: {
    ko: "{0} — Rigorloom",
    en: "{0} — Rigorloom",
  },
  wps_untitled_document: {
    ko: "제목 없는 문서",
    en: "Untitled document",
  },
  wps_original_label: {
    ko: "원본",
    en: "Original",
  },
  wps_revision_label: {
    ko: "수정본 {0}",
    en: "Revision {0}",
  },
  wps_revision_file_token: {
    ko: "수정본",
    en: "rev",
  },
  wps_original_file_token: {
    ko: "원본",
    en: "original",
  },
  wps_export_default_stem: {
    ko: "문서",
    en: "document",
  },
  wps_date_am: {
    ko: "오전",
    en: "AM",
  },
  wps_date_pm: {
    ko: "오후",
    en: "PM",
  },
  wps_date_time_format: {
    ko: "{0}월 {1}일 {2} {3}:{4}",
    en: "{0} {1}, {3}:{4} {2}",
  },
  wps_time_format: {
    ko: "{0} {1}:{2}",
    en: "{1}:{2} {0}",
  },
  wps_date_unknown: {
    ko: "시각 없음",
    en: "No timestamp",
  },
  wps_export_same_as_source: {
    ko: "원본과 같은 이름으로는 저장할 수 없습니다.",
    en: "Cannot save over the original file.",
  },
  wps_export_empty_name: {
    ko: "파일 이름을 입력해 주세요.",
    en: "Enter a file name.",
  },
  wps_export_invalid_name: {
    ko: "사용할 수 없는 파일 이름입니다.",
    en: "Invalid file name.",
  },
  wps_export_toast_desktop: {
    ko: "내보냈습니다.",
    en: "File exported.",
  },
  wps_export_toast_browser: {
    ko: "다운로드를 시작했습니다.",
    en: "Download started.",
  },
  wps_export_open_folder: {
    ko: "폴더 열기",
    en: "Open folder",
  },
} as const satisfies Record<string, WpsVocabEntry>;

export type WpsVocabularyKey = keyof typeof WPS_VOCABULARY;

export function tWps(
  key: WpsVocabularyKey,
  language: UiLanguage = "ko",
  args?: ReadonlyArray<string | number>,
): string {
  const entry = WPS_VOCABULARY[key];
  let out: string = language === "en" ? entry.en : entry.ko;
  if (!args || args.length === 0) {
    return out;
  }
  for (let i = 0; i < args.length; i += 1) {
    out = out.split(`{${i}}`).join(String(args[i]));
  }
  return out;
}
