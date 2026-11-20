import { WP4, type Wp4Key } from "../i18n/v2/wp4.ts";
import type { UiLanguage } from "../i18n/vocabulary.ts";

export type { Wp4Key };

export const tp = WP4.t;

/** `원본` for revision 0, `수정본 N` otherwise. */
export function revisionName(revision: number, lang: UiLanguage): string {
  return revision <= 0 ? tp("wp4_revision_source", lang) : tp("wp4_revision_n", lang, [revision]);
}

const TIME_FORMATS: Partial<Record<UiLanguage, Intl.DateTimeFormat>> = {};

/** `오후 2:13`. One format for the panel; WPS's dates helper replaces this. */
export function clockTime(iso: string | null | undefined, lang: UiLanguage): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const fmt =
    TIME_FORMATS[lang] ??
    (TIME_FORMATS[lang] = new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
      hour: "numeric",
      minute: "2-digit",
    }));
  return fmt.format(date);
}
