/**
 * Which editor the window shows: the v1 screens or the editor v2 shell.
 *
 * v1 stays the default until the switch. Editor v2 is opt-in: `?ui=v2` in the
 * browser, or the `devEditorV2` developer preference (prefs.json, read through
 * the same prefs route as `devMockAgent`) in the desktop app. `?ui=v1` always
 * wins, so a v1 link keeps working with the preference on.
 *
 * The choice is marked on <html> as `data-ui`, which scopes the v1 palette
 * (v1-tokens.css) to the v1 screens.
 */

export type UiVariant = "v1" | "v2";

/** The developer preference that opens editor v2 when no `?ui=` is given. */
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

/** The address wins; then the developer preference; then v1. */
export function resolveUiVariant(query: UiVariant | null, prefs: Record<string, unknown> | null | undefined): UiVariant {
  if (query) return query;
  return prefs?.[EDITOR_V2_PREF] === true ? "v2" : "v1";
}

let current: UiVariant = "v1";

/** The variant chosen at start (or by the smoke driver since). */
export function uiVariant(): UiVariant {
  return current;
}

/** Record the variant and mark <html> with it. */
export function setUiVariant(variant: UiVariant): void {
  current = variant;
  if (typeof document !== "undefined") document.documentElement.dataset.ui = variant;
}
