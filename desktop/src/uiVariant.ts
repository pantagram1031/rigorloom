/**
 * Which editor the window shows: the editor v2 shell (default) or the previous
 * v1 screens.
 *
 * Precedence:
 * 1. `?ui=v1|v2` in the address;
 * 2. `editorVariant` ("v1" or "v2") in prefs.json;
 * 3. `devEditorV2` (false -> "v1", true -> "v2"), kept only for reading old
 *    prefs files;
 * 4. otherwise "v2".
 *
 * The choice is marked on <html> as `data-ui`, which scopes the v1 palette
 * (v1-tokens.css) to the v1 screens.
 */

export type UiVariant = "v1" | "v2";

/** The preference that chooses between the editor v2 shell and the v1 screens. */
export const EDITOR_VARIANT_PREF = "editorVariant";

/** Legacy preference kept only for reading old prefs files (`false` -> v1, `true` -> v2). */
export const EDITOR_V2_PREF = "devEditorV2";

/** `?ui=v1` or `?ui=v2`, or null when the address names neither. */
export function uiVariantFromQuery(search: string): UiVariant | null {
  try {
    const ui = new URLSearchParams(search).get("ui");
    return ui === "v1" || ui === "v2" ? ui : null;
  } catch {
    return null;
  }
}

/**
 * Precedence: `?ui=v1|v2` > `editorVariant` ("v1" | "v2") > legacy `devEditorV2`
 * (false -> v1, true -> v2) > default v2.
 */
export function resolveUiVariant(query: UiVariant | null, prefs: Record<string, unknown> | null | undefined): UiVariant {
  if (query === "v1" || query === "v2") return query;
  const saved = prefs?.[EDITOR_VARIANT_PREF];
  if (saved === "v1" || saved === "v2") return saved;
  const legacy = prefs?.[EDITOR_V2_PREF];
  if (legacy === false) return "v1";
  if (legacy === true) return "v2";
  return "v2";
}

let current: UiVariant = "v2";

/** The variant chosen at start (or by the smoke driver since). */
export function uiVariant(): UiVariant {
  return current;
}

/** Record the variant and mark <html> with it. */
export function setUiVariant(variant: UiVariant): void {
  current = variant;
  if (typeof document !== "undefined") document.documentElement.dataset.ui = variant;
}
