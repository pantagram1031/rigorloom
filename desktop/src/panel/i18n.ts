/**
 * Panel strings. Reads `i18n/v2/wp4.ts` until WP2's v2 loader and WP7's fold
 * land; the call sites do not change when they do.
 */
import { WP4_STRINGS, type Wp4Key } from "../i18n/v2/wp4.ts";
import type { UiLanguage } from "../i18n/vocabulary.ts";

export type { Wp4Key };

export function tp(key: Wp4Key, lang: UiLanguage, args?: ReadonlyArray<string | number>): string {
  const template: string = WP4_STRINGS[key][lang];
  if (!args) return template;
  return template.replace(/\{(\d+)\}/g, (full, idx: string) => {
    const value = args[Number(idx)];
    return value === undefined ? full : String(value);
  });
}

/** `원본` for revision 0, `수정본 N` otherwise. */
export function revisionName(revision: number, lang: UiLanguage): string {
  return revision <= 0 ? tp("revision_source", lang) : tp("revision_n", lang, [revision]);
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
