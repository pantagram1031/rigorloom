/**
 * Integration strings (editor glue). Folded into vocabulary.ts by WP7.
 * Copy follows out/C-copy.md and J1 §3 Copy.
 */
import { defineStrings } from "./index.ts";

export const E = defineStrings("editor", {
  editor_history_aria: { ko: "수정본 기록", en: "Revision history" },
  editor_history_source: { ko: "원본", en: "Original" },
  editor_history_revision: { ko: "수정본 {0}", en: "Revision {0}" },
  editor_history_current: { ko: "현재", en: "Current" },
  editor_history_none: { ko: "수정본 없음", en: "No revisions" },
  editor_history_ops: { ko: "변경 {0}건", en: "{0} changes" },
  editor_history_revert: { ko: "되돌리기", en: "Revert" },
});
