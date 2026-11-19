/**
 * The i18n/v2 loader (J1 §5: new strings go in `i18n/v2/<wp>.ts`; WP7 folds them).
 *
 * Each package ships one table:
 *
 *   // i18n/v2/canvas.ts
 *   import { defineStrings } from "./index.ts";
 *   export const S = defineStrings("canvas", {
 *     canvas_view_marks: { ko: "변경 표시", en: "Show changes" },
 *   });
 *   // in a component
 *   S.t("canvas_view_marks", lang)
 *
 * Keys start with the package prefix (`shell_`, `canvas_`, `panel_` ...) and are
 * unique across all v2 tables and across `vocabulary.ts`; a clash
 * throws at load in development and fails `scripts/shell-contracts.test.mjs`.
 * Placeholders are `{0}`, `{1}` or `{name}`, formatted by `vocabulary.ts`'s
 * `formatTemplate`. Never attach a particle to a placeholder (C-copy §1).
 */
import { formatTemplate, type UiLanguage } from "../vocabulary.ts";

export interface V2Entry {
  ko: string;
  en: string;
}

export type Vars = Record<string, string | number> | ReadonlyArray<string | number>;

export interface StringTable<K extends string> {
  readonly wp: string;
  readonly table: Readonly<Record<K, V2Entry>>;
  t(key: K, lang: UiLanguage, vars?: Vars): string;
  has(key: string): key is K;
}

const tables = new Map<string, Readonly<Record<string, V2Entry>>>();
const owner = new Map<string, string>();

export function defineStrings<K extends string>(wp: string, table: Record<K, V2Entry>): StringTable<K> {
  for (const key of Object.keys(table)) {
    const prev = owner.get(key);
    if (prev && prev !== wp) {
      throw new Error(`i18n/v2: key "${key}" defined by both ${prev} and ${wp}`);
    }
    owner.set(key, wp);
  }
  tables.set(wp, table);
  return {
    wp,
    table,
    t(key, lang, vars) {
      const entry = table[key];
      if (!entry) return String(key);
      return formatTemplate(entry[lang] ?? entry.ko, vars);
    },
    has(key: string): key is K {
      return Object.prototype.hasOwnProperty.call(table, key);
    },
  };
}

/** Every table loaded so far, by package. For WP7's fold and the tests. */
export function allStringTables(): ReadonlyMap<string, Readonly<Record<string, V2Entry>>> {
  return tables;
}
